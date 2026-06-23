import os
import base64
import asyncio
import httpx
import time
import re
from fastapi import HTTPException

AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT")
AZURE_OCR_KEY = os.getenv("AZURE_OCR_KEY")
MODEL_ID = os.getenv("MODEL_ID", "prebuilt-receipt")

def clean_string_field(val: str) -> str:
    """Strip common leading/trailing punctuation like parentheses, brackets, trailing commas, dots, and quotes."""
    if not val:
        return ""
    val = str(val).strip()
    val = re.sub(r'^[()\s\-\[\]{}.,;:\"\'\u201c\u201d]+', '', val)
    val = re.sub(r'[()\s\-\[\]{}.,;:\"\'\u201c\u201d]+$', '', val)
    return val.strip()

_global_client = None

def get_azure_client() -> httpx.AsyncClient:
    global _global_client
    if _global_client is None or _global_client.is_closed:
        _global_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=15, max_connections=30)
        )
    return _global_client

class ReusableClientContext:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
    async def __aenter__(self) -> httpx.AsyncClient:
        return self.client
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

async def submit_azure_model(image_bytes: bytes, model_id: str, client: httpx.AsyncClient = None) -> dict:
    """Submit image to Azure Document Intelligence model and return the raw response JSON."""
    if not AZURE_ENDPOINT or not AZURE_OCR_KEY:
        raise HTTPException(
            status_code=400,
            detail="Azure Document Intelligence credentials (AZURE_ENDPOINT or AZURE_OCR_KEY) are not configured."
        )
        
    analyze_url = (
        f"{AZURE_ENDPOINT.rstrip('/')}/documentintelligence/documentModels/{model_id}:analyze?api-version=2024-11-30"
    )
    submit_headers = {
        "Ocp-Apim-Subscription-Key": AZURE_OCR_KEY,
        "Content-Type": "application/json",
    }
    poll_headers = {"Ocp-Apim-Subscription-Key": AZURE_OCR_KEY}
    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    payload = {"base64Source": b64_image}

    async def _execute(cl: httpx.AsyncClient) -> dict:
        response = await cl.post(analyze_url, headers=submit_headers, json=payload)
        if response.status_code != 202:
            raise HTTPException(
                status_code=502,
                detail=f"Azure model {model_id} submission failed ({response.status_code}): {response.text}",
            )
        operation_url = response.headers.get("Operation-Location")
        if not operation_url:
            raise HTTPException(status_code=502, detail=f"Azure model {model_id} did not return an Operation-Location header.")
        
        # Optimize polling sleep: wait 0.8s for the first poll, then poll every 0.2s to reduce completion delay
        await asyncio.sleep(0.8)
        for _ in range(50):
            poll = await cl.get(operation_url, headers=poll_headers)
            result = poll.json()
            status = result.get("status", "")
            if status == "succeeded":
                return result.get("analyzeResult", {})
            if status == "failed":
                raise HTTPException(status_code=502, detail=f"Azure model {model_id} processing failed.")
            await asyncio.sleep(0.2)
        raise HTTPException(status_code=504, detail=f"Azure model {model_id} timed out after 15 seconds.")

    if client is None:
        client = get_azure_client()
    return await _execute(client)



async def submit_prebuilt_receipt(image_bytes: bytes) -> dict:
    """Submit image to Azure Document Intelligence model and return parsed receipt.
    Returns a dict with keys like 'MerchantName', 'TransactionDate', 'Total', 'Items'.
    """
    try:
        analyze_result = await submit_azure_model(image_bytes, MODEL_ID)
        documents = analyze_result.get("documents", [])
        if documents:
            doc = documents[0]
            fields = doc.get("fields", {})
            return {
                "MerchantName": fields.get("MerchantName", {}).get("valueString", ""),
                "TransactionDate": fields.get("TransactionDate", {}).get("valueDate", ""),
                "Total": fields.get("Total", {}).get("valueNumber", 0),
                "Items": fields.get("Items", {}).get("valueArray", []),
            }
        return {}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=502, detail=f"Azure receipt model failed: {e}")


def extract_text_from_read(analyze_result: dict) -> str:
    content = analyze_result.get("content", "")
    if content:
        return content
    lines = []
    for page in analyze_result.get("pages", []):
        for line in page.get("lines", []):
            lines.append(line.get("content", ""))
    return "\n".join(lines)


def extract_fields_from_document(analyze_result: dict) -> dict:
    documents = analyze_result.get("documents", [])
    if not documents:
        return {}
    doc = documents[0]
    fields = doc.get("fields", {})
    return fields


def get_clean_fields(fields: dict) -> dict:
    clean = {}
    for key, val in fields.items():
        if not isinstance(val, dict):
            continue
        v_type = val.get("type")
        if v_type == "string":
            clean[key] = val.get("valueString", "")
        elif v_type == "number":
            clean[key] = val.get("valueNumber", 0)
        elif v_type == "date":
            clean[key] = val.get("valueDate", "")
        elif v_type == "phoneNumber":
            clean[key] = val.get("valuePhoneNumber", "")
        elif v_type == "time":
            clean[key] = val.get("valueTime", "")
        elif v_type == "array":
            clean[key] = val.get("valueArray", [])
            # Fallback checks
            for k in ["valueString", "valueNumber", "valueInteger", "valueBoolean", "valueDate", "valuePhoneNumber", "valueTime", "valueArray", "value"]:
                if k in val:
                    clean[key] = val[k]
                    break
    return clean


async def process_azure_document_intelligence(image_bytes: bytes, content_type: str) -> dict:
    """
    Executes the receipt scan concurrently using three Azure Document Intelligence models:
    - prebuilt-read (layout/text extraction)
    - prebuilt-receipt (receipt fields extraction)
    - prebuilt-invoice (invoice fields extraction)
    
    Uses an optimized early-return architecture:
    If prebuilt-read completes first and local regex parsing successfully extracts 
    core fields (vendor, expense_date, amount), it cancels the heavier models 
    and returns immediately to keep latency under 3 seconds.
    Otherwise, it awaits the other models as fallback.
    """
    start_time = time.time()
    preprocessed_bytes = image_bytes

    async with ReusableClientContext(get_azure_client()) as client:
        # 1. OCR using Azure prebuilt-read
        try:
            read_res = await submit_azure_model(preprocessed_bytes, "prebuilt-read", client)
            raw_text = extract_text_from_read(read_res)
        except Exception as read_err:
            raise HTTPException(
                status_code=502,
                detail=f"Azure Document Intelligence OCR failed: {str(read_err)}"
            )

        if not raw_text:
            raise HTTPException(
                status_code=502,
                detail="Azure Document Intelligence OCR returned empty text."
            )

        # 2. Run LLM text completions on raw_text using llm_providers
        from llm_providers import get_llm_provider
        from engine.prompts import (
            build_pass1_prompt,
            build_pass2_prompt,
            build_single_pass_prompt,
        )
        from engine.category import detect_category_from_llm_response
        from engine.field_mapper import extract_and_map_fields
        from engine.validator import validate_extracted_fields, filter_fields_by_category

        provider = get_llm_provider()
        print(f"[Azure+LLM Pipeline] Using provider: {provider.provider_name}")

        single_pass = os.getenv("SINGLE_PASS_MODE", "true").lower().strip() == "true"

        if single_pass:
            print("[Azure+LLM Pipeline] Running in SINGLE-PASS mode...")
            prompt = build_single_pass_prompt()
            try:
                response = await provider.extract_from_text(raw_text, prompt)
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"Azure+LLM Single-Pass extraction failed ({provider.provider_name}): {str(e)}"
                )

            if not response:
                raise HTTPException(
                    status_code=502,
                    detail=f"Azure+LLM Single-Pass returned empty response ({provider.provider_name})"
                )

            category = detect_category_from_llm_response(response)
            print(f"[Azure+LLM Pipeline] Detected category: {category}")
            merged = response
            merged["category"] = category
        else:
            print("[Azure+LLM Pipeline] Running in TWO-PASS mode...")
            # Pass 1: Category detection & general extraction on raw_text
            pass1_prompt = build_pass1_prompt()
            try:
                pass1_response = await provider.extract_from_text(raw_text, pass1_prompt)
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"Azure+LLM Pass 1 failed ({provider.provider_name}): {str(e)}"
                )

            if not pass1_response:
                raise HTTPException(
                    status_code=502,
                    detail=f"Azure+LLM Pass 1 returned empty response ({provider.provider_name})"
                )

            category = detect_category_from_llm_response(pass1_response)
            print(f"[Azure+LLM Pipeline] Detected category: {category}")

            # Pass 2: Category-specific extraction on raw_text
            pass2_prompt = build_pass2_prompt(category)
            try:
                pass2_response = await provider.extract_from_text(raw_text, pass2_prompt)
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"Azure+LLM Pass 2 failed ({provider.provider_name}): {str(e)}"
                )

            if not pass2_response:
                raise HTTPException(
                    status_code=502,
                    detail=f"Azure+LLM Pass 2 returned empty response ({provider.provider_name})"
                )

            # Merge results
            merged = {}
            for key in set(list(pass1_response.keys()) + list(pass2_response.keys())):
                val2 = pass2_response.get(key)
                val1 = pass1_response.get(key)
                if val2 is not None and val2 != "" and val2 != "null":
                    merged[key] = val2
                elif val1 is not None and val1 != "" and val1 != "null":
                    merged[key] = val1

            merged["category"] = category

        # Extract & Map
        mapped_fields = extract_and_map_fields(merged, category)

        # Validate
        validated = validate_extracted_fields(mapped_fields, category)

        # Add remarks with the Azure DI Read + LLM label
        mode_label = "Single-Pass" if single_pass else "Two-Pass"
        validated["remarks"] = f"[Azure DI Read + LLM {mode_label}: {provider.provider_name}]"
        # Ensure raw_text is populated in the result
        validated["raw_text"] = raw_text

        # Filter by category using smart engine filtering
        filtered = filter_fields_by_category(validated, category)

        return _filter_and_format_response(filtered, category, start_time)


def _filter_and_format_response(parsed: dict, category: str, start_time: float) -> dict:
    from services.db_service import filter_db_record_by_category
    filtered = filter_db_record_by_category(parsed)
    latency = time.time() - start_time
    return {
        "latency_seconds": round(latency, 2),
        "result": filtered
    }

import os
import base64
import asyncio
import time
import httpx
from fastapi import HTTPException

# Reuse the main pipeline functions and validators
from main import (
    parse_receipt, 
    clean_llm_output, 
    preprocess_image_with_opencv
)
from utils_llm import validate_and_parse_with_llm

AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT")
AZURE_OCR_KEY = os.getenv("AZURE_OCR_KEY")
MODEL_ID = os.getenv("MODEL_ID", "prebuilt-receipt")

async def submit_prebuilt_receipt(image_bytes: bytes) -> dict:
    """Submit image to Azure Document Intelligence model and return parsed receipt."""
    if not AZURE_ENDPOINT or not AZURE_OCR_KEY:
        raise HTTPException(
            status_code=400,
            detail="Azure Document Intelligence credentials (AZURE_ENDPOINT or AZURE_OCR_KEY) are not configured."
        )
        
    analyze_url = (
        f"{AZURE_ENDPOINT.rstrip('/')}/documentintelligence/documentModels/{MODEL_ID}:analyze?api-version=2024-11-30"
    )
    submit_headers = {
        "Ocp-Apim-Subscription-Key": AZURE_OCR_KEY,
        "Content-Type": "application/json",
    }
    poll_headers = {"Ocp-Apim-Subscription-Key": AZURE_OCR_KEY}
    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    payload = {"base64Source": b64_image}

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(analyze_url, headers=submit_headers, json=payload)
        if response.status_code != 202:
            raise HTTPException(
                status_code=502,
                detail=f"Azure receipt model submission failed ({response.status_code}): {response.text}",
            )
        operation_url = response.headers.get("Operation-Location")
        if not operation_url:
            raise HTTPException(status_code=502, detail="Azure did not return an Operation-Location header.")
        for _ in range(40):
            await asyncio.sleep(0.5)
            poll = await client.get(operation_url, headers=poll_headers)
            result = poll.json()
            status = result.get("status", "")
            if status == "succeeded":
                analyze_result = result.get("analyzeResult", {})
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
            if status == "failed":
                raise HTTPException(status_code=502, detail="Azure receipt model processing failed.")
        raise HTTPException(status_code=504, detail="Azure receipt model timed out after 20 seconds.")

async def run_azure_ocr(image_bytes: bytes) -> str:
    """Submit image to Azure AI Document Intelligence Read API and poll for result."""
    if not AZURE_ENDPOINT or not AZURE_OCR_KEY:
        raise HTTPException(
            status_code=400,
            detail="Azure Document Intelligence credentials (AZURE_ENDPOINT or AZURE_OCR_KEY) are not configured."
        )

    analyze_url = f"{AZURE_ENDPOINT.rstrip('/')}/documentintelligence/documentModels/prebuilt-read:analyze?api-version=2024-11-30"
    submit_headers = {
        "Ocp-Apim-Subscription-Key": AZURE_OCR_KEY,
        "Content-Type": "application/json",
    }
    poll_headers = {"Ocp-Apim-Subscription-Key": AZURE_OCR_KEY}

    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    payload = {"base64Source": b64_image}

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(analyze_url, headers=submit_headers, json=payload)
        if response.status_code != 202:
            raise HTTPException(
                status_code=502,
                detail=f"Azure OCR submission failed ({response.status_code}): {response.text}"
            )

        operation_url = response.headers.get("Operation-Location")
        if not operation_url:
            raise HTTPException(status_code=502, detail="Azure did not return an Operation-Location header.")

        for _ in range(40):
            await asyncio.sleep(0.5)
            poll = await client.get(operation_url, headers=poll_headers)
            result = poll.json()
            status = result.get("status", "")

            if status == "succeeded":
                analyze_result = result.get("analyzeResult", {})
                content = analyze_result.get("content", "")
                if content:
                    return content
                
                lines = []
                for page in analyze_result.get("pages", []):
                    for line in page.get("lines", []):
                        lines.append(line.get("content", ""))
                return "\n".join(lines)

            if status == "failed":
                raise HTTPException(status_code=502, detail="Azure OCR processing failed.")

        raise HTTPException(status_code=504, detail="Azure OCR timed out after 20 seconds.")


async def process_azure_only(image_bytes: bytes, content_type: str) -> dict:
    """
    Executes the receipt scan strictly using Azure Document Intelligence (no LLMs).
    """
    from utils_azure import process_azure_document_intelligence
    return await process_azure_document_intelligence(image_bytes, content_type)


async def process_llm_only(image_bytes: bytes, content_type: str) -> dict:
    """
    Executes the receipt scan strictly using OpenCV + GPT-5.5 Vision (no Azure DocIn).
    """
    start_time = time.time()
    
    # 1. Preprocess the image
    if content_type == "application/pdf":
        preprocessed_bytes = image_bytes
    else:
        preprocessed_bytes = await asyncio.to_thread(preprocess_image_with_opencv, image_bytes, content_type)
        
    # Check if LLM keys are configured
    llm_configured = bool(os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("AZURE_OPENAI_KEY"))
    if not llm_configured:
        raise HTTPException(
            status_code=400,
            detail="Multimodal LLM API keys are not configured in .env."
        )

    try:
        # 2. Call the multimodal LLM directly
        llm_parsed = await asyncio.to_thread(validate_and_parse_with_llm, preprocessed_bytes, content_type)
        if not llm_parsed:
            raise HTTPException(
                status_code=502,
                detail="Multimodal LLM was unable to analyze the document."
            )

        # 3. Perform regex validation & sanitization
        cleaned = clean_llm_output(llm_parsed)
        cleaned["remarks"] = f"[GPT-5.5 Vision Only (No Azure DocIn)] {cleaned.get('remarks') or ''}".strip()[:255]
        
        latency = time.time() - start_time
        return {
            "latency_seconds": round(latency, 2),
            "result": cleaned
        }
        
    except Exception as e:
        print(f"[Compare Pipeline] LLM Only processing failed: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=502, detail=f"LLM Only processing failed: {e}")

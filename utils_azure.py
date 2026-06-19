import os
import base64
import asyncio
import httpx
import time
import re
from datetime import datetime
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
        else:
            # Fallback checks
            for k in ["valueString", "valueNumber", "valueDate", "valuePhoneNumber", "valueTime", "valueArray"]:
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
        # Start all tasks concurrently
        read_task = asyncio.create_task(submit_azure_model(preprocessed_bytes, "prebuilt-read", client))
        receipt_task = asyncio.create_task(submit_azure_model(preprocessed_bytes, "prebuilt-receipt", client))
        invoice_task = asyncio.create_task(submit_azure_model(preprocessed_bytes, "prebuilt-invoice", client))
        
        # 1. Wait for prebuilt-read first (fast path)
        read_res = None
        raw_text = ""
        regex_parsed = {}
        try:
            read_res = await read_task
            raw_text = extract_text_from_read(read_res)
            from main import parse_receipt
            regex_parsed = parse_receipt(raw_text) if raw_text else {}
            
            # Fast-path check: do we have all critical fields?
            if (
                regex_parsed.get("vendor") 
                and regex_parsed.get("expense_date") 
                and regex_parsed.get("amount")
            ):
                # Core fields exist, cancel standard models to return early
                receipt_task.cancel()
                invoice_task.cancel()
                # Await cancellation silently
                try:
                    await asyncio.gather(receipt_task, invoice_task, return_exceptions=True)
                except asyncio.CancelledError:
                    pass
                
                # Build result using regex parsed values
                vendor = regex_parsed.get("vendor")
                category = regex_parsed.get("category", "Other")
                expense_date = regex_parsed.get("expense_date")
                amount = regex_parsed.get("amount") or 0.0
                invoice_number = regex_parsed.get("invoice_number")
                location = regex_parsed.get("location") or ""
                remarks = "[Azure DI Read+Regex (Fast Early Return)]"
                
                parsed = {
                    "category": category,
                    "expense_date": expense_date,
                    "amount": float(amount) if amount else 0.0,
                    "liters": regex_parsed.get("liters"),
                    "rate_per_liter": regex_parsed.get("rate_per_liter"),
                    "petrol_pump": clean_string_field(vendor) if category == "Fuel" else None,
                    "vendor": clean_string_field(vendor),
                    "registration_no": clean_string_field(regex_parsed.get("registration_no") or ""),
                    "odometer": regex_parsed.get("odometer"),
                    "location": clean_string_field(location),
                    "service_type": clean_string_field(regex_parsed.get("service_type") or ""),
                    "remarks": remarks,
                    "paid": True,
                    "invoice_number": clean_string_field(invoice_number),
                    "taxable_amount": regex_parsed.get("taxable_amount"),
                    "non_taxable_amount": regex_parsed.get("non_taxable_amount"),
                    "gst_percentage": regex_parsed.get("gst_percentage"),
                    "gst_amount": regex_parsed.get("gst_amount"),
                    "gst_invoicing_type": clean_string_field(regex_parsed.get("gst_invoicing_type")),
                    "paid_to": clean_string_field(regex_parsed.get("paid_to")),
                    "contact_number": clean_string_field(regex_parsed.get("contact_number")),
                }
                
                return _filter_and_format_response(parsed, category, start_time)
                
        except Exception as read_err:
            print(f"[Azure Pipeline] prebuilt-read failed: {read_err}")
            
        # 2. Fallback path: wait for receipt and invoice models
        receipt_res, invoice_res = await asyncio.gather(
            receipt_task, invoice_task, return_exceptions=True
        )
        
        # Check if all models failed
        if isinstance(read_res, Exception) and isinstance(receipt_res, Exception) and isinstance(invoice_res, Exception):
            raise HTTPException(
                status_code=502,
                detail=f"All Azure DI models failed. Read: {read_res}, Receipt: {receipt_res}, Invoice: {invoice_res}"
            )
            
        receipt_fields = {}
        if not isinstance(receipt_res, Exception):
            receipt_fields = get_clean_fields(extract_fields_from_document(receipt_res))
        else:
            print(f"[Azure Pipeline] prebuilt-receipt failed: {receipt_res}")
            
        invoice_fields = {}
        if not isinstance(invoice_res, Exception):
            invoice_fields = get_clean_fields(extract_fields_from_document(invoice_res))
        else:
            print(f"[Azure Pipeline] prebuilt-invoice failed: {invoice_res}")

        # Resolve merged values
        vendor = (
            receipt_fields.get("MerchantName") or 
            invoice_fields.get("VendorName") or 
            regex_parsed.get("vendor") or 
            ""
        )
        vendor_lower = str(vendor).lower()
        
        category = "Other"
        if any(k in vendor_lower for k in ["hpcl", "iocl", "bpcl", "indian oil", "petrol", "diesel", "fuel", "nayara", "shell", "bp"]):
            category = "Fuel"
        elif regex_parsed.get("category") and regex_parsed.get("category") != "Other":
            category = regex_parsed["category"]
            
        expense_date = (
            receipt_fields.get("TransactionDate") or 
            invoice_fields.get("InvoiceDate") or 
            regex_parsed.get("expense_date")
        )
        if expense_date:
            expense_date = str(expense_date)[:10]
        else:
            expense_date = datetime.now().strftime("%Y-%m-%d")
            
        amount = (
            receipt_fields.get("Total") or 
            invoice_fields.get("InvoiceTotal") or 
            invoice_fields.get("AmountDue") or 
            regex_parsed.get("amount") or 
            0.0
        )
        
        invoice_number = (
            invoice_fields.get("InvoiceId") or 
            receipt_fields.get("ReceiptId") or 
            regex_parsed.get("invoice_number")
        )
        taxable_amount = invoice_fields.get("SubTotal") or regex_parsed.get("taxable_amount")
        gst_amount = invoice_fields.get("TotalTax") or regex_parsed.get("gst_amount")
        
        location = (
            receipt_fields.get("MerchantAddress") or 
            invoice_fields.get("VendorAddress") or 
            ""
        )
        if location.lower().strip() in {"particulars", "sr. no.", "amount", "rate", "qty", "total", "g. total"}:
            location = ""
        if not location:
            location = regex_parsed.get("location") or ""
            
        model_flags = []
        if not isinstance(read_res, Exception): model_flags.append("Read")
        if not isinstance(receipt_res, Exception): model_flags.append("Receipt")
        if not isinstance(invoice_res, Exception): model_flags.append("Invoice")
        models_string = "+".join(model_flags)
        remarks = f"[Azure DI {models_string} (No LLM)]"
        
        parsed = {
            "category": category,
            "expense_date": expense_date,
            "amount": float(amount) if amount else 0.0,
            "liters": regex_parsed.get("liters"),
            "rate_per_liter": regex_parsed.get("rate_per_liter"),
            "petrol_pump": clean_string_field(vendor) if category == "Fuel" else None,
            "vendor": clean_string_field(vendor),
            "registration_no": clean_string_field(regex_parsed.get("registration_no") or ""),
            "odometer": regex_parsed.get("odometer"),
            "location": clean_string_field(location),
            "service_type": clean_string_field(regex_parsed.get("service_type") or ""),
            "remarks": remarks,
            "paid": True,
            "invoice_number": clean_string_field(invoice_number),
            "taxable_amount": float(taxable_amount) if taxable_amount else None,
            "non_taxable_amount": regex_parsed.get("non_taxable_amount"),
            "gst_percentage": regex_parsed.get("gst_percentage"),
            "gst_amount": float(gst_amount) if gst_amount else None,
            "gst_invoicing_type": clean_string_field(regex_parsed.get("gst_invoicing_type")),
            "paid_to": clean_string_field(regex_parsed.get("paid_to")),
            "contact_number": clean_string_field(receipt_fields.get("MerchantPhoneNumber") or regex_parsed.get("contact_number")),
        }
        
        return _filter_and_format_response(parsed, category, start_time)

def _filter_and_format_response(parsed: dict, category: str, start_time: float) -> dict:
    if category == "Fuel":
        allowed_keys = {
            "category", "expense_date", "amount", "liters", "rate_per_liter",
            "petrol_pump", "vendor", "odometer", "registration_no", "location",
            "remarks", "paid", "invoice_number", "contact_number"
        }
    elif category == "Maintenance":
        allowed_keys = {
            "category", "expense_date", "amount", "vendor", "registration_no",
            "odometer", "location", "service_type", "remarks", "paid",
            "vendor_type", "maintenance_item", "custom_maintenance_item",
            "invoice_number", "taxable_amount", "non_taxable_amount",
            "gst_percentage", "gst_amount", "gst_invoicing_type", "paid_to",
            "contact_number"
        }
    elif category == "Vehicle":
        allowed_keys = {
            "category", "expense_date", "amount", "registration_no", "location",
            "remarks", "paid", "challan_no", "challan_type", "violation_type",
            "issued_by", "due_date", "parking_location", "km_limit", "hour_limit",
            "excess_km_rate", "excess_hour_rate", "excess_km_amount", "excess_hour_amount",
            "driver_allowance", "toll_charges", "parking_charges", "other_charges",
            "gst_applicable_on_parking", "gst_applicable_on_toll",
            "gst_applicable_on_other_charges", "gst_percentage", "gst_amount",
            "tds_percentage", "tds_amount", "service_type", "invoice_number",
            "contact_number", "paid_to"
        }
    else: # "Other"
        allowed_keys = {
            "category", "expense_date", "amount", "registration_no", "location",
            "remarks", "paid", "party_type", "party", "contact", "expense_name",
            "invoice_number", "contact_number", "paid_to"
        }
        
    parsed = {k: v for k, v in parsed.items() if k in allowed_keys}
    latency = time.time() - start_time
    return {
        "latency_seconds": round(latency, 2),
        "result": parsed
    }

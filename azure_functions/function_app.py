"""
azure_functions/function_app.py — Azure Functions Stage Chain (Python v2 model).

Each function is triggered by its corresponding Azure Service Bus queue and
forwards the result to the next queue in the chain.

Stage Chain:
    receipt-stage1 → Stage1Validate   → receipt-stage2
    receipt-stage2 → Stage2Preprocess → receipt-stage3
    receipt-stage3 → Stage3Extract    → receipt-stage4
    receipt-stage4 → Stage4Map        → receipt-stage5
    receipt-stage5 → Stage5Filter     → receipt-stage6
    receipt-stage6 → Stage6Persist    → MySQL (end of chain)

All functions POST status updates back to the FastAPI app at
    POST {FASTAPI_BASE_URL}/job-status/{job_id}
so the browser can poll GET /job-status/{job_id}.
"""

import io
import json
import os
import sys
import time
import re
import logging
from datetime import datetime
from typing import Optional

import azure.functions as func
import httpx
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.storage.blob import BlobServiceClient, ContentSettings

# ─────────────────────────────────────────────────────────────────────────────
#  App instance (Azure Functions Python v2 model)
# ─────────────────────────────────────────────────────────────────────────────
app = func.FunctionApp()

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Shared utilities
# ─────────────────────────────────────────────────────────────────────────────

def _sb_connection() -> str:
    conn = os.environ.get("AZURE_SERVICEBUS_CONNECTION_STRING") or os.environ.get("ServiceBusConnection")
    if not conn:
        raise RuntimeError("AZURE_SERVICEBUS_CONNECTION_STRING is not set.")
    return conn


def _blob_client() -> BlobServiceClient:
    conn = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    return BlobServiceClient.from_connection_string(conn)


def _download_blob(blob_url: str) -> bytes:
    """Download image bytes from the given Azure Blob URL."""
    client = _blob_client()
    parts = blob_url.split(".blob.core.windows.net/")
    rest = parts[1]
    container, _, blob_path = rest.partition("/")
    blob_c = client.get_blob_client(container=container, blob=blob_path)
    return blob_c.download_blob().readall()


def _upload_blob(job_id: str, blob_name: str, data: bytes, content_type: str) -> str:
    """Upload bytes to blob storage and return the URL."""
    container = os.environ.get("AZURE_STORAGE_CONTAINER", "receipt-images")
    client = _blob_client()
    cc = client.get_container_client(container)
    try:
        cc.create_container()
    except Exception:
        pass
    blob_path = f"{job_id}/{blob_name}"
    bc = cc.get_blob_client(blob_path)
    bc.upload_blob(data, overwrite=True, content_settings=ContentSettings(content_type=content_type))
    return bc.url


def _forward_to_queue(queue_name: str, payload: dict) -> None:
    """Send payload JSON to the given Service Bus queue."""
    client = ServiceBusClient.from_connection_string(_sb_connection())
    with client:
        with client.get_queue_sender(queue_name=queue_name) as sender:
            sender.send_messages(ServiceBusMessage(json.dumps(payload, default=str)))
    logger.info(f"[Chain] Job {payload.get('job_id')} → {queue_name}")


def _notify_status(job_id: str, status: str, detail: str = "") -> None:
    """POST a status update back to the FastAPI app (fire and forget)."""
    base = os.environ.get("FASTAPI_BASE_URL", "http://localhost:8000").rstrip("/")
    try:
        httpx.post(
            f"{base}/job-status/{job_id}",
            json={"status": status, "detail": detail},
            timeout=5.0,
        )
    except Exception as e:
        logger.warning(f"[Chain] Could not notify FastAPI of status {status}: {e}")


def _queue(n: int) -> str:
    """Return the queue name for stage N."""
    return os.environ.get(f"AZURE_QUEUE_STAGE{n}", f"receipt-stage{n}")


# ─────────────────────────────────────────────────────────────────────────────
#  Stage 1 — Validation
#  Trigger: receipt-stage1
#  Output:  receipt-stage2  (validated image bytes stored in blob)
# ─────────────────────────────────────────────────────────────────────────────
@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="%AZURE_QUEUE_STAGE1%",
    connection="ServiceBusConnection",
)
def stage1_validate(msg: func.ServiceBusMessage) -> None:
    """Stage 1: Validate content-type and convert non-JPEG formats to JPEG."""
    payload = json.loads(msg.get_body().decode("utf-8"))
    job_id = payload["job_id"]
    blob_url = payload["blob_url"]
    filename = payload.get("filename", "receipt.jpg")
    content_type = payload.get("content_type", "image/jpeg")

    _notify_status(job_id, "stage_1", "Validating file format")
    logger.info(f"[Stage1] job={job_id} file={filename} type={content_type}")

    _SUPPORTED = {"image/jpeg", "image/png", "image/bmp", "image/tiff", "image/webp", "application/pdf"}

    # Download original blob
    image_bytes = _download_blob(blob_url)

    # Convert non-JPEG to JPEG (mirrors stage1_validation.py logic)
    if content_type not in _SUPPORTED:
        logger.warning(f"[Stage1] Unsupported type {content_type} — converting to JPEG")
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        image_bytes = buf.getvalue()
        content_type = "image/jpeg"

    # Upload validated bytes
    validated_url = _upload_blob(job_id, "validated.jpg", image_bytes, content_type)

    # Forward to Stage 2
    _forward_to_queue(_queue(2), {
        "job_id": job_id,
        "blob_url": validated_url,
        "filename": filename,
        "content_type": content_type,
    })


# ─────────────────────────────────────────────────────────────────────────────
#  Stage 2 — Preprocessing
#  Trigger: receipt-stage2
#  Output:  receipt-stage3  (preprocessed/resized image in blob)
# ─────────────────────────────────────────────────────────────────────────────
@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="%AZURE_QUEUE_STAGE2%",
    connection="ServiceBusConnection",
)
def stage2_preprocess(msg: func.ServiceBusMessage) -> None:
    """Stage 2: Resize and compress the image (mirrors stage2_preprocessing.py)."""
    import cv2
    import numpy as np

    payload = json.loads(msg.get_body().decode("utf-8"))
    job_id = payload["job_id"]
    content_type = payload.get("content_type", "image/jpeg")

    _notify_status(job_id, "stage_2", "Preprocessing image")
    logger.info(f"[Stage2] job={job_id}")

    image_bytes = _download_blob(payload["blob_url"])

    if content_type != "application/pdf":
        try:
            nparr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is not None:
                h, w = img.shape[:2]
                max_dim = 1600
                if max(h, w) > max_dim:
                    scale = max_dim / max(h, w)
                    img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
                success, encoded = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                if success:
                    image_bytes = encoded.tobytes()
        except Exception as e:
            logger.warning(f"[Stage2] Preprocessing error (using original): {e}")

    preprocessed_url = _upload_blob(job_id, "preprocessed.jpg", image_bytes, "image/jpeg")

    _forward_to_queue(_queue(3), {
        "job_id": job_id,
        "blob_url": preprocessed_url,
        "filename": payload.get("filename"),
        "content_type": content_type,
    })


# ─────────────────────────────────────────────────────────────────────────────
#  Stage 3 — LLM Extraction
#  Trigger: receipt-stage3
#  Output:  receipt-stage4  (raw LLM JSON + category, no blobs needed after)
# ─────────────────────────────────────────────────────────────────────────────

def _build_single_pass_prompt() -> str:
    return """You are analyzing an Indian financial document (receipt, invoice, bill, or statement).
**Task**: Identify the category and extract all relevant fields as a JSON object.

**1. Classify the Category**:
- "Fuel" — petrol/diesel receipts from fuel stations (HPCL, BPCL, Indian Oil, Shell, etc.)
- "Maintenance" — vehicle repair/service invoices from workshops/garages
- "Vehicle" — challans, traffic fines, toll receipts, parking tickets
- "Other" — any other transaction or general receipt.

**2. Extract the Relevant Fields** based on category (see your FastAPI stage3_extraction.py for full schema).

**3. Output Requirements**:
- Return ONLY a valid JSON object.
- Dates must be in YYYY-MM-DD format.
- Currency must be in INR.
- Automatically correct spelling errors (e.g. "balab" → "Bulb").
- Do not include markdown fences, comments, or extra text."""


async def _call_llm(image_bytes: bytes, content_type: str) -> dict:
    """Call Azure AI Foundry (OpenAI) with the image and return parsed JSON."""
    import base64

    endpoint = os.environ["AZURE_AI_FOUNDRY_ENDPOINT"].rstrip("/")
    api_key = os.environ["AZURE_AI_FOUNDRY_KEY"]
    model = os.environ.get("AZURE_AI_FOUNDRY_MODEL", "gpt-4.1-mini-553107")

    b64 = base64.b64encode(image_bytes).decode("utf-8")
    prompt = _build_single_pass_prompt()

    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{b64}"}},
                ],
            }
        ],
        "max_tokens": 2048,
        "temperature": 0.1,
    }

    chat_url = f"{endpoint}/openai/deployments/{model}/chat/completions?api-version=2024-02-15-preview"
    resp = httpx.post(
        chat_url,
        headers={"api-key": api_key, "Content-Type": "application/json"},
        json=body,
        timeout=60.0,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]

    # Strip markdown fences if present
    content = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.IGNORECASE)
    content = re.sub(r"\s*```$", "", content.strip())
    return json.loads(content)


def _detect_category(llm_response: dict) -> str:
    cat = str(llm_response.get("category", "Other")).lower().strip()
    if cat in ("fuel", "petrol", "diesel", "gas"):
        return "Fuel"
    if cat in ("maintenance", "repair", "service", "workshop"):
        return "Maintenance"
    if cat in ("vehicle", "challan", "toll", "parking", "traffic"):
        return "Vehicle"
    return "Other"


@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="%AZURE_QUEUE_STAGE3%",
    connection="ServiceBusConnection",
)
def stage3_extract(msg: func.ServiceBusMessage) -> None:
    """Stage 3: Send image to LLM for extraction & categorization."""
    import asyncio

    payload = json.loads(msg.get_body().decode("utf-8"))
    job_id = payload["job_id"]
    content_type = payload.get("content_type", "image/jpeg")

    _notify_status(job_id, "stage_3", "Extracting with LLM")
    logger.info(f"[Stage3] job={job_id}")

    image_bytes = _download_blob(payload["blob_url"])

    start = time.time()
    try:
        raw_response = asyncio.get_event_loop().run_until_complete(
            _call_llm(image_bytes, content_type)
        )
    except Exception as e:
        _notify_status(job_id, "failed", f"LLM extraction failed: {e}")
        raise

    category = _detect_category(raw_response)
    raw_response["category"] = category
    latency = round(time.time() - start, 2)

    logger.info(f"[Stage3] job={job_id} category={category} latency={latency}s")

    _forward_to_queue(_queue(4), {
        "job_id": job_id,
        "raw_response": raw_response,
        "category": category,
        "extraction_latency": latency,
        "filename": payload.get("filename"),
    })


# ─────────────────────────────────────────────────────────────────────────────
#  Stage 4 — Field Mapping
#  Trigger: receipt-stage4
#  Output:  receipt-stage5  (mapped fields dict)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_number(val) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    s = re.sub(r"[₹$€£]", "", s)
    s = re.sub(r"(?i)^rs\.?\s*", "", s)
    s = re.sub(r"(?i)^inr\s*", "", s)
    s = s.replace(",", "").replace("/-", "")
    m = re.search(r"[-+]?\d*\.?\d+", s)
    return float(m.group(0)) if m else None


def _clean_string(val: str) -> str:
    if not val:
        return ""
    val = str(val).strip()
    val = re.sub(r'^[()\s\-\[\]{}.,;"\'\u201c\u201d]+', "", val)
    val = re.sub(r'[()\s\-\[\]{}.,;"\'\u201c\u201d]+$', "", val)
    return val.strip()


def _map_fields(raw_response: dict, category: str) -> dict:
    """Minimal field mapper (mirrors stage4_mapping.py logic)."""
    result = {}
    for k, v in raw_response.items():
        if v is None or v == "" or v == "null":
            result[k] = None
            continue
        if isinstance(v, (int, float)):
            result[k] = v
        elif isinstance(v, str):
            cleaned = _clean_string(v)
            result[k] = cleaned if cleaned else None
        else:
            result[k] = v

    result.setdefault("category", category)
    result.setdefault("expense_date", datetime.now().strftime("%Y-%m-%d"))
    result.setdefault("amount", 0.0)
    result["paid"] = True
    return result


@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="%AZURE_QUEUE_STAGE4%",
    connection="ServiceBusConnection",
)
def stage4_map(msg: func.ServiceBusMessage) -> None:
    """Stage 4: Map raw LLM response fields to the standardized schema."""
    payload = json.loads(msg.get_body().decode("utf-8"))
    job_id = payload["job_id"]
    raw_response = payload["raw_response"]
    category = payload.get("category", "Other")

    _notify_status(job_id, "stage_4", "Mapping fields")
    logger.info(f"[Stage4] job={job_id} category={category}")

    mapped = _map_fields(raw_response, category)

    _forward_to_queue(_queue(5), {
        "job_id": job_id,
        "mapped": mapped,
        "category": category,
        "filename": payload.get("filename"),
    })


# ─────────────────────────────────────────────────────────────────────────────
#  Stage 5 — Validation & Filtering
#  Trigger: receipt-stage5
#  Output:  receipt-stage6  (validated + filtered fields dict)
# ─────────────────────────────────────────────────────────────────────────────

def _robust_date(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    date_str = re.sub(r"(?i)\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\b", "", date_str)
    date_str = re.sub(r"[\s,]+", " ", date_str).strip()
    date_str = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_str, flags=re.IGNORECASE)
    formats = [
        "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y",
        "%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y",
        "%d-%b-%Y", "%d/%b/%Y", "%d-%m-%y", "%d/%m/%y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    m = re.search(r"\b(\d{1,2})([-\/\.])(\d{1,2})\2(\d{2,4})\b", date_str)
    if m:
        for fmt in formats:
            try:
                return datetime.strptime(m.group(0), fmt)
            except ValueError:
                continue
    return None


def _validate_fields(fields: dict, category: str) -> dict:
    # Date
    raw_date = fields.get("expense_date")
    if raw_date:
        dt = _robust_date(str(raw_date).strip())
        fields["expense_date"] = dt.strftime("%Y-%m-%d") if dt else datetime.now().strftime("%Y-%m-%d")
    else:
        fields["expense_date"] = datetime.now().strftime("%Y-%m-%d")

    # Amount
    try:
        amt = float(fields.get("amount") or 0)
        amt = abs(amt) if amt < 0 else amt
        fields["amount"] = round(min(amt, 10_000_000), 2)
    except (ValueError, TypeError):
        fields["amount"] = 0.0

    # Registration
    reg = fields.get("registration_no")
    if reg:
        reg_clean = re.sub(r"[\s\-\./]", "", str(reg)).upper()
        fields["registration_no"] = reg_clean[:20]

    # Phone
    phone = fields.get("contact_number")
    if phone:
        phone_clean = re.sub(r"[\s\-\+]", "", str(phone))
        if phone_clean.startswith("91") and len(phone_clean) == 12:
            phone_clean = phone_clean[2:]
        elif phone_clean.startswith("0"):
            phone_clean = phone_clean[1:]
        fields["contact_number"] = phone_clean[:15]

    # Total amount fallback
    fields.setdefault("total_amount", fields.get("amount", 0.0))

    return fields


def _filter_fields(fields: dict, category: str) -> dict:
    common_keys = {
        "category", "expense_date", "amount", "paid",
        "location", "registration_no", "contact_number",
        "invoice_number", "paid_to", "total_amount", "payment_mode",
    }
    category_keys = {
        "Fuel": {"liters", "rate_per_liter", "petrol_pump", "vendor", "odometer", "fuel_type"},
        "Maintenance": {
            "vendor", "odometer", "service_type", "vendor_type",
            "maintenance_item", "custom_maintenance_item", "taxable_amount",
            "non_taxable_amount", "gst_percentage", "gst_amount", "gst_invoicing_type",
            "next_service_due", "work_order_number", "start_odometer_reading",
            "end_odometer_reading", "items",
        },
        "Vehicle": {
            "challan_no", "challan_type", "violation_type", "issued_by", "due_date",
            "parking_location", "km_limit", "hour_limit", "excess_km_rate",
            "excess_hour_rate", "excess_km_amount", "excess_hour_amount",
            "driver_allowance", "toll_charges", "parking_charges", "other_charges",
            "gst_applicable_on_parking", "gst_applicable_on_toll",
            "gst_applicable_on_other_charges", "gst_percentage", "gst_amount",
            "tds_percentage", "tds_amount", "service_type",
            "action_type", "start_odometer_reading", "end_odometer_reading",
            "journey_start_datetime", "journey_end_datetime", "items",
        },
        "Other": {"party_type", "party", "expense_name", "action_type", "items"},
    }
    if category not in category_keys:
        return fields
    allowed = common_keys | category_keys.get(category, category_keys["Other"])
    return {k: v for k, v in fields.items() if k in allowed}


@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="%AZURE_QUEUE_STAGE5%",
    connection="ServiceBusConnection",
)
def stage5_filter(msg: func.ServiceBusMessage) -> None:
    """Stage 5: Validate and filter mapped fields by business rules."""
    payload = json.loads(msg.get_body().decode("utf-8"))
    job_id = payload["job_id"]
    mapped = payload["mapped"]
    category = payload.get("category", "Other")

    _notify_status(job_id, "stage_5", "Applying validation & filtering")
    logger.info(f"[Stage5] job={job_id}")

    validated = _validate_fields(mapped, category)
    filtered = _filter_fields(validated, category)

    _forward_to_queue(_queue(6), {
        "job_id": job_id,
        "filtered": filtered,
        "filename": payload.get("filename"),
    })


# ─────────────────────────────────────────────────────────────────────────────
#  Stage 6 — DB Persistence
#  Trigger: receipt-stage6
#  Output:  MySQL INSERT (end of chain)
# ─────────────────────────────────────────────────────────────────────────────

def _get_db_conn():
    import pymysql
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        charset="utf8mb4",
        autocommit=False,
    )


def _insert_expense_from_dict(fields: dict) -> int:
    """
    Insert the normalized expense dict into the appropriate MySQL table.
    Mirrors the logic in stage6_db_service.py insert_expense().
    Returns the inserted row ID.
    """
    category = fields.get("category", "Other")
    base_cat = category if category in ("Fuel", "Maintenance", "Vehicle", "Other") else "Other"

    def s(key: str, max_len: int = None) -> Optional[str]:
        v = fields.get(key)
        if v is None:
            return None
        sv = str(v)
        return sv[:max_len] if max_len else sv

    def n(key: str) -> Optional[float]:
        v = fields.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def i(key: str) -> Optional[int]:
        v = n(key)
        return int(v) if v is not None else None

    conn = _get_db_conn()
    try:
        with conn.cursor() as cursor:
            if base_cat == "Fuel":
                cursor.execute(
                    """INSERT INTO fuel (
                        vehicle, registration_no, expense_date, petrol_pump, location,
                        fuel_type, liters, rate_per_liter, odometer, amount,
                        total_amount, invoice_number, taxable_amount, non_taxable_amount,
                        gst_percentage, gst_amount, payment_mode, paid, paid_to, contact_number
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        s("vehicle", 50), s("registration_no", 20), s("expense_date"),
                        s("petrol_pump", 100), s("location", 100), s("fuel_type", 20),
                        n("liters"), n("rate_per_liter"), i("odometer"), n("amount"),
                        n("total_amount"), s("invoice_number", 50), n("taxable_amount"),
                        n("non_taxable_amount"), n("gst_percentage"), n("gst_amount"),
                        s("payment_mode", 50), True, s("paid_to", 255), s("contact_number", 15),
                    ),
                )
            elif base_cat == "Maintenance":
                cursor.execute(
                    """INSERT INTO maintenance (
                        vehicle, registration_no, expense_date, service_type, vendor,
                        vendor_type, maintenance_item, custom_maintenance_item, action_type, odometer,
                        next_service_due, work_order_number, invoice_number, amount, total_amount,
                        taxable_amount, non_taxable_amount, gst_percentage, gst_amount, payment_mode,
                        paid, paid_to, contact_number, items
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        s("vehicle", 50), s("registration_no", 20), s("expense_date"),
                        s("service_type", 100), s("vendor", 100), s("vendor_type", 20),
                        s("maintenance_item", 100), s("custom_maintenance_item", 255),
                        s("action_type", 50), i("odometer"), i("next_service_due"),
                        s("work_order_number", 50), s("invoice_number", 50),
                        n("amount"), n("total_amount"), n("taxable_amount"),
                        n("non_taxable_amount"), n("gst_percentage"), n("gst_amount"),
                        s("payment_mode", 50), True, s("paid_to", 255),
                        s("contact_number", 15), s("items"),
                    ),
                )
            elif base_cat == "Vehicle":
                cursor.execute(
                    """INSERT INTO vehicle (
                        vehicle, registration_no, expense_date, challan_no, challan_type,
                        violation_type, issued_by, due_date, parking_location, km_limit,
                        hour_limit, excess_km_rate, excess_hour_rate, excess_km_amount, excess_hour_amount,
                        driver_allowance, toll_charges, parking_charges, other_charges, start_odometer_reading,
                        end_odometer_reading, journey_start_datetime, journey_end_datetime, invoice_number, amount,
                        total_amount, taxable_amount, non_taxable_amount, gst_percentage, gst_amount,
                        gst_invoicing_type, gst_applicable_on_parking, gst_applicable_on_toll,
                        gst_applicable_on_other_charges, tds_percentage, tds_amount,
                        payment_mode, paid, paid_to, contact_number, items
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        s("vehicle", 50), s("registration_no", 20), s("expense_date"),
                        s("challan_no", 50), s("challan_type", 100), s("violation_type", 255),
                        s("issued_by", 100), s("due_date"), s("parking_location", 100),
                        i("km_limit"), i("hour_limit"), n("excess_km_rate"), n("excess_hour_rate"),
                        n("excess_km_amount"), n("excess_hour_amount"), n("driver_allowance"),
                        n("toll_charges"), n("parking_charges"), n("other_charges"),
                        n("start_odometer_reading"), n("end_odometer_reading"),
                        s("journey_start_datetime"), s("journey_end_datetime"),
                        s("invoice_number", 50), n("amount"), n("total_amount"),
                        n("taxable_amount"), n("non_taxable_amount"), n("gst_percentage"),
                        n("gst_amount"), s("gst_invoicing_type", 50),
                        bool(fields.get("gst_applicable_on_parking")),
                        bool(fields.get("gst_applicable_on_toll")),
                        bool(fields.get("gst_applicable_on_other_charges")),
                        n("tds_percentage"), n("tds_amount"), s("payment_mode", 50),
                        True, s("paid_to", 255), s("contact_number", 15), s("items"),
                    ),
                )
            else:  # Other
                cursor.execute(
                    """INSERT INTO other (
                        vehicle, registration_no, expense_date, party_type, party,
                        expense_name, vendor, location, invoice_number, amount,
                        total_amount, taxable_amount, non_taxable_amount, gst_percentage,
                        gst_amount, payment_mode, paid, paid_to, contact_number, items
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        s("vehicle", 50), s("registration_no", 20), s("expense_date"),
                        s("party_type", 100), s("party", 100), s("expense_name", 100),
                        s("vendor", 100), s("location", 100), s("invoice_number", 50),
                        n("amount"), n("total_amount"), n("taxable_amount"),
                        n("non_taxable_amount"), n("gst_percentage"), n("gst_amount"),
                        s("payment_mode", 50), True, s("paid_to", 255),
                        s("contact_number", 15), s("items"),
                    ),
                )
            conn.commit()
            return cursor.lastrowid
    finally:
        conn.close()


@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="%AZURE_QUEUE_STAGE6%",
    connection="ServiceBusConnection",
)
def stage6_persist(msg: func.ServiceBusMessage) -> None:
    """Stage 6: Persist the validated expense to MySQL. End of the chain."""
    payload = json.loads(msg.get_body().decode("utf-8"))
    job_id = payload["job_id"]
    filtered = payload["filtered"]

    _notify_status(job_id, "stage_6", "Persisting to database")
    logger.info(f"[Stage6] job={job_id} category={filtered.get('category')}")

    try:
        row_id = _insert_expense_from_dict(filtered)
    except Exception as e:
        logger.error(f"[Stage6] DB insert failed: {e}")
        _notify_status(job_id, "failed", f"DB persistence failed: {e}")
        raise

    logger.info(f"[Stage6] Inserted row_id={row_id} for job={job_id}")
    _notify_status(job_id, "done", f"Expense saved (row_id={row_id})")

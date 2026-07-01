import json
import os
import sys
import logging
import re
from datetime import datetime
from typing import Optional
import azure.functions as func
import httpx
import pymysql
from azure.servicebus import ServiceBusClient, ServiceBusMessage

# Add wwwroot to path so relative imports like pipeline.stage3_extraction work
sys.path.append("/home/site/wwwroot")

from pipeline.stage3_extraction.schemas import CATEGORY_SCHEMAS
from pipeline.stage3_extraction.stage3_extraction import get_schema_for_category


def run_stage4(raw_response: dict, category: str) -> dict:
    """Stage 4: Extract and Map Fields to standardized schema."""
    return extract_and_map_fields(raw_response, category)


def extract_and_map_fields(llm_response: dict, category: str) -> dict:
    """
    Map the LLM response fields to the database schema format.
    Ensures all fields are properly typed and formatted.
    """
    is_custom = category not in CATEGORY_SCHEMAS
    schema = get_schema_for_category(category)

    result = {}
    for field_name, field_info in schema.items():
        raw_val = llm_response.get(field_name)

        if field_name == "items" and isinstance(raw_val, list):
            descriptions = []
            for item in raw_val:
                if isinstance(item, dict) and item.get("description"):
                    desc = str(item["description"]).strip()
                    qty = item.get("quantity")
                    if qty:
                        try:
                            qty_val = int(float(qty))
                            descriptions.append(f"{desc} (x{qty_val})")
                        except (ValueError, TypeError):
                            descriptions.append(desc)
                    else:
                        descriptions.append(desc)
                elif isinstance(item, str):
                    descriptions.append(item.strip())
            raw_val = ", ".join(descriptions) if descriptions else None

        if raw_val is None or raw_val == "" or raw_val == "null":
            result[field_name] = None
            continue

        field_type = field_info["type"]

        try:
            if field_type == "string":
                result[field_name] = _clean_string(str(raw_val))
            elif field_type == "number":
                result[field_name] = _parse_number(raw_val)
            elif field_type == "integer":
                num = _parse_number(raw_val)
                result[field_name] = int(num) if num is not None else None
            else:
                result[field_name] = raw_val
        except (ValueError, TypeError):
            result[field_name] = None

    # For custom categories, copy any extra keys extracted dynamically by the LLM
    if is_custom:
        for key, val in llm_response.items():
            if key not in result and val is not None and val != "" and val != "null":
                if isinstance(val, str):
                    cleaned = _clean_string(val)
                    parsed_num = _parse_number(cleaned)
                    if parsed_num is not None and len(str(parsed_num)) == len(cleaned.replace(',', '').replace(' ', '')):
                        result[key] = parsed_num
                    else:
                        result[key] = cleaned
                else:
                    result[key] = val

    # Ensure required fields have defaults
    result.setdefault("category", category)
    result.setdefault("expense_date", datetime.now().strftime("%Y-%m-%d"))
    result.setdefault("amount", 0.0)
    result["paid"] = True

    return result


def _clean_string(val: str) -> str:
    """Clean up a string value from LLM response."""
    if not val:
        return ""
    val = str(val).strip()
    # Remove common LLM artifacts
    val = re.sub(r'^[()\\s\\-\\[\\]{}.,;:\\"\\\'\\u201c\\u201d]+', '', val)
    val = re.sub(r'[()\\s\\-\\[\\]{}.,;:\\"\\\'\\u201c\\u201d]+$', '', val)
    return val.strip()


def _parse_number(val) -> Optional[float]:
    """Parse a numeric value from LLM response, handling commas, Rs., ₹, etc."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    # Remove currency symbols and common prefixes
    s = re.sub(r'[₹$€£]', '', s)
    s = re.sub(r'(?i)^rs\.?\s*', '', s)
    s = re.sub(r'(?i)^inr\s*', '', s)
    s = s.replace(',', '')
    s = s.replace('/-', '')

    match = re.search(r'[-+]?\d*\.?\d+', s)
    if match:
        return float(match.group(0))
    return None


app = func.FunctionApp()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────
def _get_db_conn():
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", 3306)),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", "1234"),
        database=os.environ.get("DB_NAME", "expenses"),
        cursorclass=pymysql.cursors.DictCursor
    )

def _update_stage_tracking(job_id: str, filename: str = None, status: str = None, 
                           current_stage: str = None, original_url: str = None, 
                           preprocessed_url: str = None, category: str = None, 
                           expense_row_id: int = None, error_message: str = None, 
                           completed_stage_num: int = None):
    try:
        conn = _get_db_conn()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM stage_tracking WHERE job_id = %s", (job_id,))
                exists = cursor.fetchone()
                
                if not exists:
                    sql = """
                    INSERT INTO stage_tracking (job_id, filename, status, current_stage, original_url)
                    VALUES (%s, %s, %s, %s, %s)
                    """
                    cursor.execute(sql, (job_id, filename or "unknown", status or "queued", 
                                         current_stage or "stage4_map", original_url))
                else:
                    updates = []
                    params = []
                    
                    if status:
                        updates.append("status = %s")
                        params.append(status)
                    if current_stage:
                        updates.append("current_stage = %s")
                        params.append(current_stage)
                    if original_url:
                        updates.append("original_url = %s")
                        params.append(original_url)
                    if preprocessed_url:
                        updates.append("preprocessed_url = %s")
                        params.append(preprocessed_url)
                    if category:
                        updates.append("category = %s")
                        params.append(category)
                    if expense_row_id is not None:
                        updates.append("expense_row_id = %s")
                        params.append(expense_row_id)
                    if error_message:
                        updates.append("error_message = %s")
                        params.append(error_message)
                    if completed_stage_num:
                        updates.append(f"stage{completed_stage_num}_completed_at = CURRENT_TIMESTAMP")
                        
                    if updates:
                        sql = f"UPDATE stage_tracking SET {', '.join(updates)} WHERE job_id = %s"
                        params.append(job_id)
                        cursor.execute(sql, tuple(params))
            conn.commit()
    except Exception as e:
        logger.error(f"[Tracking Error] Failed to update stage_tracking for job {job_id}: {e}")

def _send_callback(job_id: str, status: str, detail: str = None):
    base_url = os.environ.get("FASTAPI_BASE_URL", "http://localhost:8000")
    url = f"{base_url}/job-status/{job_id}"
    payload = {"status": status}
    if detail:
        payload["detail"] = detail
    try:
        httpx.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"[Callback Error] Failed to send status to {url}: {e}")

def _forward_to_next_stage(stage_num: int, payload: dict):
    conn_str = os.environ.get("AZURE_SERVICEBUS_CONNECTION_STRING")
    queue_name = os.environ.get(f"AZURE_QUEUE_STAGE{stage_num}", f"receipt-stage{stage_num}")
    client = ServiceBusClient.from_connection_string(conn_str)
    with client:
        with client.get_queue_sender(queue_name) as sender:
            msg = ServiceBusMessage(json.dumps(payload, default=str))
            sender.send_messages(msg)


# ─────────────────────────────────────────────────────────
#  Service Bus Queue Trigger
# ─────────────────────────────────────────────────────────
@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="%AZURE_QUEUE_STAGE4%",
    connection="ServiceBusConnection"
)
def stage4_map(msg: func.ServiceBusMessage):
    body = msg.get_body().decode('utf-8')
    try:
        payload = json.loads(body)
    except Exception as e:
        logger.error(f"[Stage4] Failed to parse message body JSON: {e}")
        return

    job_id = payload.get("job_id")
    blob_url = payload.get("blob_url")
    filename = payload.get("filename")
    content_type = payload.get("content_type")
    category = payload.get("category")
    raw_response = payload.get("raw_response")

    if not job_id or not raw_response or not category:
        logger.error(f"[Stage4] Missing job_id, raw_response, or category in payload: {payload}")
        return

    logger.info(f"[Stage4] Starting field mapping for job={job_id}")

    try:
        # 1. Update status to stage_4
        _update_stage_tracking(
            job_id=job_id,
            status="stage_4",
            current_stage="stage4_map"
        )
        _send_callback(job_id, "stage_4")

        # 2. Run schema mapping
        mapped_fields = run_stage4(raw_response, category)

        # 3. Update tracking
        _update_stage_tracking(job_id=job_id, completed_stage_num=4)

        # 4. Forward to Stage 5
        next_payload = {
            "job_id": job_id,
            "blob_url": blob_url,
            "filename": filename,
            "content_type": content_type,
            "category": category,
            "mapped_fields": mapped_fields
        }
        _forward_to_next_stage(5, next_payload)
        _send_callback(job_id, "stage_5")
        logger.info(f"[Stage4] Completed successfully for job={job_id}")

    except Exception as e:
        error_msg = f"Stage 4 failed: {str(e)}"
        logger.error(f"[Stage4] {error_msg}")
        _update_stage_tracking(job_id=job_id, status="failed", error_message=error_msg)
        _send_callback(job_id, "failed", error_msg)

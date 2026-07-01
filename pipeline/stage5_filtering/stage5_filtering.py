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


def run_stage5(mapped_fields: dict, category: str) -> dict:
    """Stage 5: Validate and Filter Fields by Category."""
    validated = validate_extracted_fields(mapped_fields, category)
    return filter_fields_by_category(validated, category)


# ──────────────────────────────────────────────────────────────────────
#  Business Rule Validation
# ──────────────────────────────────────────────────────────────────────
def parse_robust_date(date_str: str) -> Optional[datetime]:
    """Parse a date string robustly, trying multiple formats and resolving ambiguous strings."""
    if not date_str:
        return None

    # Clean the string (strip extra characters)
    # Remove day of week (e.g. Monday, Mon)
    date_str = re.sub(r'(?i)\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\b', '', date_str)
    date_str = re.sub(r'[\s,]+', ' ', date_str).strip()
    
    # Clean ordinal suffixes (e.g. 25th -> 25)
    date_str = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_str, flags=re.IGNORECASE)

    # Standard formats to try
    formats = [
        # YYYY-MM-DD and variations
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        # DD-MM-YYYY and variations
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d.%m.%Y",
        # MM-DD-YYYY and variations
        "%m-%d-%Y",
        "%m/%d/%Y",
        "%m.%d.%Y",
        # 2-digit year variations (YY)
        "%d-%m-%y",
        "%d/%m/%y",
        "%d.%m.%y",
        "%y-%m-%d",
        "%y/%m/%d",
        "%y.%m.%d",
        "%m-%d-%y",
        "%m/%d/%y",
        # Textual month variations
        "%d %b %Y",
        "%d %B %Y",
        "%b %d %Y",
        "%B %d %Y",
        "%d-%b-%Y",
        "%d-%B-%Y",
        "%d/%b/%Y",
        "%d/%B/%Y",
        # 2-digit year textual month
        "%d %b %y",
        "%d %B %y",
        "%b %d %y",
        "%B %d %y",
        "%d-%b-%y",
        "%d-%B-%y",
        "%d/%b/%y",
        "%d/%B/%y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    # Try regex extraction of numeric date within string (e.g., "Date: 25-06-2026")
    numeric_pattern = r'\b(\d{1,2})([-\/\.])(\d{1,2})\2(\d{2,4})\b'
    match = re.search(numeric_pattern, date_str)
    if match:
        matched_str = match.group(0)
        for fmt in formats:
            try:
                return datetime.strptime(matched_str, fmt)
            except ValueError:
                continue

    # Try matching yyyy/mm/dd or yyyy-mm-dd
    yyyy_pattern = r'\b(\d{4})([-\/\.])(\d{1,2})\2(\d{1,2})\b'
    match = re.search(yyyy_pattern, date_str)
    if match:
        matched_str = match.group(0)
        for fmt in formats:
            try:
                return datetime.strptime(matched_str, fmt)
            except ValueError:
                continue

    # Try text month pattern like "25 Jun 2026" or "Jun 25, 2026"
    text_month_pattern = r'\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{2,4})\b|\b([A-Za-z]{3,9})\s+(\d{1,2})\s+(\d{2,4})\b'
    match = re.search(text_month_pattern, date_str)
    if match:
        matched_str = match.group(0)
        for fmt in formats:
            try:
                return datetime.strptime(matched_str, fmt)
            except ValueError:
                continue

    return None


def validate_extracted_fields(fields: dict, category: str) -> dict:
    """
    Apply business-rule validation to extracted fields.
    Corrects obvious errors and fills in computable missing values.
    """
    # ── Date validation ──
    expense_date = fields.get("expense_date")
    if expense_date:
        dt = parse_robust_date(str(expense_date).strip())
        if dt:
            fields["expense_date"] = dt.strftime("%Y-%m-%d")
        else:
            fields["expense_date"] = datetime.now().strftime("%Y-%m-%d")
    else:
        fields["expense_date"] = datetime.now().strftime("%Y-%m-%d")

    # ── Amount validation ──
    amount = fields.get("amount")
    if amount is not None:
        try:
            amount = float(amount)
        except (ValueError, TypeError):
            amount = 0.0
        if amount > 10_000_000:
            amount = 0.0
        if amount < 0:
            amount = abs(amount)
        fields["amount"] = round(amount, 2)
    else:
        fields["amount"] = 0.0

    # ── Odometer and service due bounds validation ──
    for field_name in ("odometer", "next_service_due", "start_odometer_reading", "end_odometer_reading"):
        val = fields.get(field_name)
        if val is not None:
            try:
                numeric_val = float(val)
                if numeric_val < 0 or numeric_val > 9_999_999:
                    fields[field_name] = None
                else:
                    if field_name in ("odometer", "next_service_due"):
                        fields[field_name] = int(numeric_val)
                    else:
                        fields[field_name] = round(numeric_val, 2)
            except (ValueError, TypeError):
                fields[field_name] = None

    # ── Registration number cleanup ──
    reg = fields.get("registration_no")
    if reg:
        reg_clean = re.sub(r'[\s\-\./]', '', str(reg)).upper()
        if re.match(r'^[A-Z]{1,2}\d{1,2}[A-Z]{0,3}\d{1,4}$', reg_clean):
            fields["registration_no"] = reg_clean
        else:
            fields["registration_no"] = reg_clean[:20]

    # ── Fuel-specific validation ──
    if category == "Fuel":
        rate = fields.get("rate_per_liter")
        if rate is not None and (rate > 250.0 or rate <= 0.0):
            fields["rate_per_liter"] = None

        liters = fields.get("liters")
        rate = fields.get("rate_per_liter")
        amount = fields.get("amount", 0.0)

        if amount and liters and liters > 0 and not rate:
            fields["rate_per_liter"] = round(amount / liters, 2)
        elif amount and rate and rate > 0 and not liters:
            fields["liters"] = round(amount / rate, 2)
        elif liters and rate and (not amount or amount == 0.0):
            fields["amount"] = round(liters * rate, 2)

    # ── GST mathematical correction ──
    amount = fields.get("amount", 0.0)
    taxable = fields.get("taxable_amount")
    gst_amt = fields.get("gst_amount")
    gst_pct = fields.get("gst_percentage")

    if amount and amount > 0:
        if taxable and not gst_amt:
            fields["gst_amount"] = round(amount - taxable, 2)
        elif gst_amt and not taxable:
            fields["taxable_amount"] = round(amount - gst_amt, 2)
        elif gst_pct and gst_pct > 0 and not taxable and not gst_amt:
            fields["taxable_amount"] = round(amount / (1.0 + gst_pct / 100.0), 2)
            fields["gst_amount"] = round(amount - fields["taxable_amount"], 2)

    # ── Contact number validation ──
    phone = fields.get("contact_number")
    if phone:
        phone_clean = re.sub(r'[\s\-\+]', '', str(phone))
        if phone_clean.startswith("91") and len(phone_clean) == 12:
            phone_clean = phone_clean[2:]
        elif phone_clean.startswith("0"):
            phone_clean = phone_clean[1:]
        if re.match(r'^[6-9]\d{9}$', phone_clean):
            fields["contact_number"] = phone_clean
        else:
            fields["contact_number"] = phone_clean[:15]

    # ── total_amount validation & fallback ──
    total_amt = fields.get("total_amount")
    amt = fields.get("amount", 0.0)
    if total_amt is not None:
        try:
            total_amt = float(total_amt)
            if total_amt > 10_000_000:
                total_amt = 0.0
            if total_amt < 0:
                total_amt = abs(total_amt)
            fields["total_amount"] = round(total_amt, 2)
        except (ValueError, TypeError):
            fields["total_amount"] = amt
    else:
        fields["total_amount"] = amt

    # ── Journey datetime validation ──
    for field_name in ("journey_start_datetime", "journey_end_datetime"):
        dt_val = fields.get(field_name)
        if dt_val:
            dt_str = str(dt_val).strip()
            parsed_dt = None
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%d-%m-%Y %H:%M:%S",
                "%d-%m-%Y %H:%M",
                "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M",
                "%Y-%m-%d",
            ):
                try:
                    parsed_dt = datetime.strptime(dt_str, fmt)
                    break
                except ValueError:
                    continue
            if parsed_dt:
                fields[field_name] = parsed_dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                fields[field_name] = None

    return fields


def filter_fields_by_category(fields: dict, category: str, include_db_keys: bool = False) -> dict:
    """Filter extracted fields to only include those relevant to the category."""
    if category not in CATEGORY_SCHEMAS:
        return fields

    common_keys = {
        "category", "expense_date", "amount", "paid",
        "location", "registration_no", "contact_number", "invoice_number", "paid_to",
        "total_amount", "payment_mode",
    }

    if include_db_keys:
        common_keys.add("expense_id")
        common_keys.add("vehicle")

    category_keys = {
        "Fuel": {"liters", "rate_per_liter", "petrol_pump", "vendor", "odometer", "fuel_type"},
        "Maintenance": {
            "vendor", "odometer", "service_type", "vendor_type",
            "maintenance_item", "custom_maintenance_item", "taxable_amount",
            "non_taxable_amount", "gst_percentage", "gst_amount", "gst_invoicing_type",
            "next_service_due", "work_order_number", "start_odometer_reading", "end_odometer_reading", "items"
        },
        "Vehicle": {
            "challan_no", "challan_type", "violation_type", "issued_by", "due_date",
            "parking_location", "km_limit", "hour_limit", "excess_km_rate",
            "excess_hour_rate", "excess_km_amount", "excess_hour_amount",
            "driver_allowance", "toll_charges", "parking_charges", "other_charges",
            "gst_applicable_on_parking", "gst_applicable_on_toll",
            "gst_applicable_on_other_charges", "gst_percentage", "gst_amount",
            "tds_percentage", "tds_amount", "service_type",
            "action_type", "start_odometer_reading", "end_odometer_reading", "journey_start_datetime", "journey_end_datetime", "items"
        },
        "Other": {"party_type", "party", "expense_name", "action_type", "items"},
    }

    allowed = common_keys | category_keys.get(category, category_keys["Other"])
    return {k: v for k, v in fields.items() if k in allowed}


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
                                         current_stage or "stage5_filter", original_url))
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
    queue_name="%AZURE_QUEUE_STAGE5%",
    connection="ServiceBusConnection"
)
def stage5_filter(msg: func.ServiceBusMessage):
    body = msg.get_body().decode('utf-8')
    try:
        payload = json.loads(body)
    except Exception as e:
        logger.error(f"[Stage5] Failed to parse message body JSON: {e}")
        return

    job_id = payload.get("job_id")
    blob_url = payload.get("blob_url")
    filename = payload.get("filename")
    content_type = payload.get("content_type")
    category = payload.get("category")
    mapped_fields = payload.get("mapped_fields")

    if not job_id or not mapped_fields or not category:
        logger.error(f"[Stage5] Missing job_id, mapped_fields, or category in payload: {payload}")
        return

    logger.info(f"[Stage5] Starting filtering & business validation for job={job_id}")

    try:
        # 1. Update status to stage_5
        _update_stage_tracking(
            job_id=job_id,
            status="stage_5",
            current_stage="stage5_filter"
        )
        _send_callback(job_id, "stage_5")

        # 2. Filter & business rules validation
        filtered_fields = run_stage5(mapped_fields, category)

        # 3. Update tracking
        _update_stage_tracking(job_id=job_id, completed_stage_num=5)

        # 4. Forward to Stage 6
        next_payload = {
            "job_id": job_id,
            "blob_url": blob_url,
            "filename": filename,
            "content_type": content_type,
            "category": category,
            "filtered_fields": filtered_fields
        }
        _forward_to_next_stage(6, next_payload)
        _send_callback(job_id, "stage_6")
        logger.info(f"[Stage5] Completed successfully for job={job_id}")

    except Exception as e:
        error_msg = f"Stage 5 failed: {str(e)}"
        logger.error(f"[Stage5] {error_msg}")
        _update_stage_tracking(job_id=job_id, status="failed", error_message=error_msg)
        _send_callback(job_id, "failed", error_msg)

import json
import os
import sys
import logging
import azure.functions as func
import httpx
import pymysql

# Add wwwroot to path so relative imports like models.py, services.db work
sys.path.append("/home/site/wwwroot")

from services.db import get_connection
from models import Expense
from pipeline.stage5_filtering.stage5_filtering import filter_fields_by_category


def insert_expense(cursor, expense: Expense) -> int:
    """Execute the INSERT SQL statement for the corresponding category table. Returns lastrowid."""
    category = expense.category
    
    # Resolve base category for table routing
    base_category = category
    if category not in ("Fuel", "Maintenance", "Vehicle", "Other"):
        base_category = "Other"
        
    if base_category == "Fuel":
        sql = """
        INSERT INTO fuel (
            vehicle, registration_no, expense_date, petrol_pump, location,
            fuel_type, liters, rate_per_liter, odometer, amount,
            total_amount, invoice_number, taxable_amount, non_taxable_amount, gst_percentage,
            gst_amount, payment_mode, paid, paid_to, contact_number, job_id
        ) VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
        )
        """
        cursor.execute(sql, (
            expense.vehicle[:50] if expense.vehicle else None,
            expense.registration_no[:20] if expense.registration_no else None,
            expense.expense_date,
            expense.petrol_pump[:100] if expense.petrol_pump else None,
            expense.location[:100] if expense.location else None,
            expense.fuel_type[:20] if expense.fuel_type else None,
            expense.liters,
            expense.rate_per_liter,
            expense.odometer,
            expense.amount,
            expense.total_amount,
            expense.invoice_number[:50] if expense.invoice_number else None,
            expense.taxable_amount,
            expense.non_taxable_amount,
            expense.gst_percentage,
            expense.gst_amount,
            expense.payment_mode[:50] if expense.payment_mode else None,
            expense.paid,
            expense.paid_to[:255] if expense.paid_to else None,
            expense.contact_number[:15] if expense.contact_number else None,
            expense.job_id[:36] if getattr(expense, "job_id", None) else None,
        ))
        
    elif base_category == "Maintenance":
        sql = """
        INSERT INTO maintenance (
            vehicle, registration_no, expense_date, service_type, vendor,
            vendor_type, maintenance_item, custom_maintenance_item, action_type, odometer,
            next_service_due, work_order_number, invoice_number, amount, total_amount,
            taxable_amount, non_taxable_amount, gst_percentage, gst_amount, payment_mode,
            paid, paid_to, contact_number, items, job_id
        ) VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
        )
        """
        cursor.execute(sql, (
            expense.vehicle[:50] if expense.vehicle else None,
            expense.registration_no[:20] if expense.registration_no else None,
            expense.expense_date,
            expense.service_type[:100] if expense.service_type else None,
            expense.vendor[:100] if expense.vendor else None,
            expense.vendor_type[:20] if expense.vendor_type else None,
            expense.maintenance_item[:100] if expense.maintenance_item else None,
            expense.custom_maintenance_item[:255] if expense.custom_maintenance_item else None,
            expense.action_type[:50] if expense.action_type else None,
            expense.odometer,
            expense.next_service_due,
            expense.work_order_number[:50] if expense.work_order_number else None,
            expense.invoice_number[:50] if expense.invoice_number else None,
            expense.amount,
            expense.total_amount,
            expense.taxable_amount,
            expense.non_taxable_amount,
            expense.gst_percentage,
            expense.gst_amount,
            expense.payment_mode[:50] if expense.payment_mode else None,
            expense.paid,
            expense.paid_to[:255] if expense.paid_to else None,
            expense.contact_number[:15] if expense.contact_number else None,
            expense.items,
            expense.job_id[:36] if getattr(expense, "job_id", None) else None,
        ))
        
    elif base_category == "Vehicle":
        sql = """
        INSERT INTO vehicle (
            vehicle, registration_no, expense_date, challan_no, challan_type,
            violation_type, issued_by, due_date, parking_location, km_limit,
            hour_limit, excess_km_rate, excess_hour_rate, excess_km_amount, excess_hour_amount,
            driver_allowance, toll_charges, parking_charges, other_charges, start_odometer_reading,
            end_odometer_reading, journey_start_datetime, journey_end_datetime, invoice_number, amount,
            total_amount, taxable_amount, non_taxable_amount, gst_percentage, gst_amount,
            gst_invoicing_type, gst_applicable_on_parking, gst_applicable_on_toll, gst_applicable_on_other_charges, tds_percentage,
            tds_amount, payment_mode, paid, paid_to, contact_number, items, job_id
        ) VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
        )
        """
        cursor.execute(sql, (
            expense.vehicle[:50] if expense.vehicle else None,
            expense.registration_no[:20] if expense.registration_no else None,
            expense.expense_date,
            expense.challan_no[:50] if expense.challan_no else None,
            expense.challan_type[:100] if expense.challan_type else None,
            expense.violation_type[:255] if expense.violation_type else None,
            expense.issued_by[:100] if expense.issued_by else None,
            expense.due_date,
            expense.parking_location[:100] if expense.parking_location else None,
            expense.km_limit if hasattr(expense, 'km_limit') else None,
            expense.hour_limit if hasattr(expense, 'hour_limit') else None,
            expense.excess_km_rate if hasattr(expense, 'excess_km_rate') else None,
            expense.excess_hour_rate if hasattr(expense, 'excess_hour_rate') else None,
            expense.excess_km_amount if hasattr(expense, 'excess_km_amount') else None,
            expense.excess_hour_amount if hasattr(expense, 'excess_hour_amount') else None,
            expense.driver_allowance,
            expense.toll_charges,
            expense.parking_charges,
            expense.other_charges,
            expense.start_odometer_reading,
            expense.end_odometer_reading,
            expense.journey_start_datetime,
            expense.journey_end_datetime,
            expense.invoice_number[:50] if expense.invoice_number else None,
            expense.amount,
            expense.total_amount,
            expense.taxable_amount,
            expense.non_taxable_amount,
            expense.gst_percentage,
            expense.gst_amount,
            expense.gst_invoicing_type[:50] if expense.gst_invoicing_type else None,
            expense.gst_applicable_on_parking,
            expense.gst_applicable_on_toll,
            expense.gst_applicable_on_other_charges,
            expense.tds_percentage,
            expense.tds_amount,
            expense.payment_mode[:50] if expense.payment_mode else None,
            expense.paid,
            expense.paid_to[:255] if expense.paid_to else None,
            expense.contact_number[:15] if expense.contact_number else None,
            expense.items,
            expense.job_id[:36] if getattr(expense, "job_id", None) else None,
        ))
        
    else:  # Other or Custom category
        sql = """
        INSERT INTO other (
            vehicle, registration_no, expense_date, party_type, party,
            expense_name, vendor, location, invoice_number, amount,
            total_amount, taxable_amount, non_taxable_amount, gst_percentage, gst_amount,
            payment_mode, paid, paid_to, contact_number, items, job_id
        ) VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
        )
        """
        cursor.execute(sql, (
            expense.vehicle[:50] if expense.vehicle else None,
            expense.registration_no[:20] if expense.registration_no else None,
            expense.expense_date,
            expense.party_type[:100] if expense.party_type else None,
            expense.party[:100] if expense.party else None,
            expense.expense_name[:100] if expense.expense_name else None,
            expense.vendor[:100] if expense.vendor else None,
            expense.location[:100] if expense.location else None,
            expense.invoice_number[:50] if expense.invoice_number else None,
            expense.amount,
            expense.total_amount,
            expense.taxable_amount,
            expense.non_taxable_amount,
            expense.gst_percentage,
            expense.gst_amount,
            expense.payment_mode[:50] if expense.payment_mode else None,
            expense.paid,
            expense.paid_to[:255] if expense.paid_to else None,
            expense.contact_number[:15] if expense.contact_number else None,
            expense.items,
            expense.job_id[:36] if getattr(expense, "job_id", None) else None,
        ))
        
    return cursor.lastrowid


def save_expenses_to_db(parsed_list: list[dict]) -> list[int]:
    """Insert a list of parsed expense dicts into their category tables. Returns inserted encoded IDs."""
    expense_ids = []
    from models import encode_expense_id
    conn = get_connection()
    with conn.cursor() as cursor:
        for parsed in parsed_list:
            # Re-validate and normalize the LLM parsed dict through the Expense model
            expense = Expense(parsed)
            db_id = insert_expense(cursor, expense)
            
            # Resolve category for encoding
            cat = expense.category
            if cat not in ("Fuel", "Maintenance", "Vehicle", "Other"):
                cat = "Other"
                
            encoded_id = encode_expense_id(db_id, cat)
            expense_ids.append(encoded_id)
        conn.commit()
    conn.close()
    return expense_ids


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
                                         current_stage or "stage6_persist", original_url))
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


# ─────────────────────────────────────────────────────────
#  Service Bus Queue Trigger
# ─────────────────────────────────────────────────────────
@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="%AZURE_QUEUE_STAGE6%",
    connection="ServiceBusConnection"
)
def stage6_persist(msg: func.ServiceBusMessage):
    body = msg.get_body().decode('utf-8')
    try:
        payload = json.loads(body)
    except Exception as e:
        logger.error(f"[Stage6] Failed to parse message body JSON: {e}")
        return

    job_id = payload.get("job_id")
    category = payload.get("category")
    filtered_fields = payload.get("filtered_fields")

    if not job_id or not filtered_fields or not category:
        logger.error(f"[Stage6] Missing job_id, filtered_fields, or category in payload: {payload}")
        return

    logger.info(f"[Stage6] Starting DB persistence for job={job_id}")

    try:
        # 1. Update status to stage_6
        _update_stage_tracking(
            job_id=job_id,
            status="stage_6",
            current_stage="stage6_persist"
        )
        _send_callback(job_id, "stage_6")

        # 2. Add job_id to the expense fields before DB insert
        filtered_fields["job_id"] = job_id

        # 3. Save to MySQL database
        expense_ids = save_expenses_to_db([filtered_fields])
        expense_row_id = expense_ids[0] if expense_ids else None

        # 4. Update tracking table to 'done'
        _update_stage_tracking(
            job_id=job_id,
            status="done",
            expense_row_id=expense_row_id,
            completed_stage_num=6
        )

        # 5. Send final success callback
        _send_callback(job_id, "done", f"Successfully persisted expense_id: {expense_row_id}")
        logger.info(f"[Stage6] Completed successfully for job={job_id} row_id={expense_row_id}")

    except Exception as e:
        error_msg = f"Stage 6 failed: {str(e)}"
        logger.error(f"[Stage6] {error_msg}")
        _update_stage_tracking(job_id=job_id, status="failed", error_message=error_msg)
        _send_callback(job_id, "failed", error_msg)

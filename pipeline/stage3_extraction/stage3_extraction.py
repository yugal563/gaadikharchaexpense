import json
import os
import sys
import logging
import time
from fastapi import HTTPException
import azure.functions as func
import httpx
import pymysql
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.storage.blob import BlobServiceClient

# Add wwwroot to path so services can be imported correctly
sys.path.append("/home/site/wwwroot")

from services.llm_providers import get_llm_provider
try:
    from .schemas import CATEGORY_SCHEMAS
except ImportError:
    from schemas import CATEGORY_SCHEMAS

# ──────────────────────────────────────────────────────────────────────
#  Category Detection & Schema Helper
# ──────────────────────────────────────────────────────────────────────
def detect_category_from_llm_response(llm_response: dict) -> str:
    """
    Determine the expense category from the LLM's initial extraction response.
    Uses the LLM's own classification plus keyword-based verification.
    """
    category = llm_response.get("category", "Other")
    cat_lower = str(category).lower().strip()

    if cat_lower in ("fuel", "petrol", "diesel", "gas"):
        return "Fuel"
    if cat_lower in ("maintenance", "repair", "service", "workshop"):
        return "Maintenance"
    if cat_lower in ("vehicle", "challan", "toll", "parking", "traffic"):
        return "Vehicle"

    return "Other"


def get_schema_for_category(category: str) -> dict:
    """Return the field schema for the given expense category."""
    return CATEGORY_SCHEMAS.get(category, CATEGORY_SCHEMAS["Other"])


# ──────────────────────────────────────────────────────────────────────
#  LLM Prompt Builders
# ──────────────────────────────────────────────────────────────────────
def build_single_pass_prompt() -> str:
    """Build a single-pass extraction prompt containing schemas for all categories."""
    return """You are analyzing an Indian financial document (receipt, invoice, bill, or statement).
**Task**: Identify the category and extract all relevant fields as a JSON object.

**1. Classify the Category**:
- "Fuel" — petrol/diesel receipts from fuel stations (HPCL, BPCL, Indian Oil, Shell, etc.)
- "Maintenance" — vehicle repair/service invoices from workshops/garages
- "Vehicle" — challans, traffic fines, toll receipts, parking tickets
- "Other" — any other transaction or general receipt.

**2. Extract the Relevant Fields Based on the Category**:

If the category is **Fuel**, extract:
  - "category": "Fuel"
  - "expense_date" (string): YYYY-MM-DD
  - "amount" (number): total amount paid in INR (₹)
  - "vendor" (string): fuel station name
  - "petrol_pump" (string): HPCL, BPCL, Indian Oil, Nayara, Shell, etc.
  - "liters" (number): volume of fuel in liters
  - "rate_per_liter" (number): price per liter in INR
  - "registration_no" (string): vehicle registration number
  - "odometer" (integer): odometer reading in km
  - "location" (string): city/location
  - "invoice_number" (string): bill/receipt number
  - "contact_number" (string): phone number
  - "total_amount" (number): total transaction/bill amount in INR. Defaults to amount if same.
  - "fuel_type" (string): type of fuel (e.g., Petrol, Diesel, CNG, EV)
  - "payment_mode" (string): payment mode (e.g., Cash, Card, UPI, Net Banking)

If the category is **Maintenance**, extract:
  - "category": "Maintenance"
  - "expense_date" (string): YYYY-MM-DD
  - "amount" (number): total amount paid in INR (₹)
  - "vendor" (string): workshop/garage name
  - "registration_no" (string): vehicle registration number
  - "odometer" (integer): odometer reading in km
  - "location" (string): city/location
  - "service_type" (string): periodic maintenance, general repair, oil change, etc.
  - "invoice_number" (string): invoice number
  - "taxable_amount" (number): subtotal before tax
  - "non_taxable_amount" (number): non-taxable portion
  - "gst_percentage" (number): GST rate (e.g. 18)
  - "gst_amount" (number): total GST amount
  - "gst_invoicing_type" (string): tax invoice, bill of supply, etc.
  - "paid_to" (string): payee name
  - "contact_number" (string): phone number
  - "total_amount" (number): total transaction/bill amount in INR. Defaults to amount if same.
  - "payment_mode" (string): payment mode (e.g., Cash, Card, UPI, Net Banking)
  - "next_service_due" (integer): odometer reading in km when next service is due
  - "work_order_number" (string): work order or job card number
  - "start_odometer_reading" (number): odometer reading at the start of service/trip
  - "items" (string): comma-separated list of parts, line items, or components serviced (e.g. "Engine Oil, Brake Pads")
  - "end_odometer_reading" (number): odometer reading at the end of service/trip

If the category is **Vehicle**, extract:
  - "category": "Vehicle"
  - "expense_date" (string): YYYY-MM-DD
  - "amount" (number): total amount paid in INR (₹)
  - "registration_no" (string): vehicle registration number
  - "location" (string): city/location
  - "challan_no" (string): challan number
  - "challan_type" (string): traffic, parking, toll, etc.
  - "violation_type" (string): violation type
  - "issued_by" (string): issuing authority
  - "due_date" (string): YYYY-MM-DD
  - "parking_location" (string): parking location
  - "toll_charges" (number): toll charges
  - "parking_charges" (number): parking charges
  - "other_charges" (number): other charges
  - "gst_percentage" (number): GST rate
  - "gst_amount" (number): GST amount
  - "tds_percentage" (number): TDS rate
  - "tds_amount" (number): TDS amount
  - "service_type" (string): toll, parking, challan, etc.
  - "invoice_number" (string): receipt number
  - "contact_number" (string): contact number
  - "paid_to" (string): payee name
  - "total_amount" (number): total transaction/bill amount in INR. Defaults to amount if same.
  - "payment_mode" (string): payment mode (e.g., Cash, Card, UPI, Net Banking)
  - "action_type" (string): type of action/transaction description (e.g., Rent, Fine, Tax, Toll)
  - "start_odometer_reading" (number): odometer reading at the start of trip/journey
  - "end_odometer_reading" (number): odometer reading at the end of trip/journey
  - "items" (string): comma-separated list of items, parts, or components purchased (e.g. "Toll Charge, Parking Fee")
  - "journey_start_datetime" (string): start date and time of journey in YYYY-MM-DD HH:MM:SS format
  - "journey_end_datetime" (string): end date and time of journey in YYYY-MM-DD HH:MM:SS format

If the category is **Other**, extract:
  - "category": "Other"
  - "expense_date" (string): YYYY-MM-DD
  - "amount" (number): total amount paid in INR (₹)
  - "registration_no" (string): vehicle registration number
  - "location" (string): city/location
  - "party_type" (string): vendor, customer, etc.
  - "party" (string): party name
  - "expense_name" (string): description of the expense
  - "invoice_number" (string): invoice/bill number
  - "contact_number" (string): phone number
  - "paid_to" (string): payee name
  - "total_amount" (number): total transaction/bill amount in INR. Defaults to amount if same.
  - "payment_mode" (string): payment mode (e.g., Cash, Card, UPI, Net Banking)
  - "items" (string): comma-separated list of items or components purchased
  - "action_type" (string): type of action/expense description

**3. Output Requirements**:
- Return ONLY a valid JSON object.
- Dates must be in YYYY-MM-DD format (use Indian DD/MM/YYYY rules for parsing).
- Datetimes must be in YYYY-MM-DD HH:MM:SS format if present.
- Currency must be in INR.
- Automatically correct obvious handwriting spelling errors, typos, or local phonetics in extracted text to standard English terms (e.g., correct "balab" to "Bulb", "wayring" to "Wiring", "butten" to "Button", "hadlight" to "Headlight", "pip" to "Pipe").
- Do not include markdown fences, comments, or extra text.
"""


def build_pass1_prompt() -> str:
    """Build the Pass 1 (general extraction) prompt."""
    return """You are analyzing an Indian financial document (receipt, invoice, bill, or statement).

**Task**: Extract the following information and return it as a JSON object.

**Instructions**:
1. Identify the type of document:
   - "Fuel" — petrol/diesel receipts from fuel stations (HPCL, BPCL, Indian Oil, Nayara, Shell, etc.)
   - "Maintenance" — vehicle repair/service invoices from workshops/garages
   - "Vehicle" — challans, toll receipts, parking tickets, traffic fines
   - "Other" — any other type of transaction or general receipt.

2. Extract these fields:
   - "category": one of "Fuel", "Maintenance", "Vehicle", or "Other"
   - "vendor": name of the business/station/workshop/authority
   - "expense_date": date in YYYY-MM-DD format (use Indian DD/MM/YYYY convention for ambiguous dates)
   - "amount": total/grand total amount in INR (the final payable amount, not subtotals)
   - "registration_no": vehicle registration number if visible (Indian format like MH12AB1234)
   - "raw_text": all readable text from the document

3. Important context:
   - Dates in India follow DD/MM/YYYY format (not MM/DD/YYYY)
   - Currency is INR (₹ or Rs.)
   - GST = Goods and Services Tax (Indian tax)
   - Common fuel brands: HPCL, BPCL, Indian Oil (IOCL), Nayara, Shell

Return ONLY a valid JSON object, no markdown fences, no explanation."""


def build_pass2_prompt(category: str) -> str:
    """Build the Pass 2 (category-specific extraction) prompt."""
    if category in CATEGORY_SCHEMAS:
        schema = CATEGORY_SCHEMAS[category]
        fields_desc = []
        for field_name, field_info in schema.items():
            required = " (REQUIRED)" if field_info.get("required") else ""
            field_type = field_info["type"]
            desc = field_info["description"]
            fields_desc.append(f'  - "{field_name}" ({field_type}){required}: {desc}')

        fields_text = "\n".join(fields_desc)

        category_hints = {
            "Fuel": """
**Fuel Receipt Specific Instructions**:
- Look for "Sale", "Volume", "Qty", "Liters/Ltrs" for fuel quantity
- Look for "Rate", "Price/Ltr", "Rate/Ltr" for rate per liter
- The vendor is the fuel station name (NOT the oil company brand)
- Petrol pump brand: HPCL, BPCL, Indian Oil, Nayara, Shell, etc.
- Common unit: "HSD" = High Speed Diesel, "MS" = Motor Spirit (Petrol)
- Amount is usually the "Sale" or "Total" value
- Rate per liter is typically between ₹80-₹120 for petrol and ₹70-₹100 for diesel in India""",

            "Maintenance": """
**Maintenance Invoice Specific Instructions**:
- Look for "Grand Total", "Net Payable", "Total Amount" for the final amount
- Look for "Sub Total" or "Taxable Amount" for pre-tax amount
- GST is usually 18% for vehicle services in India
- Service type examples: "Periodic Maintenance", "General Repair", "Oil Change", "Tyre Replacement"
- The vendor is the workshop/garage/service center name
- Look for GSTIN number to confirm it's a tax invoice""",

            "Vehicle": """
**Vehicle Expense Specific Instructions**:
- For challans: look for challan number, violation type, issuing authority
- For toll receipts: look for toll plaza name, lane type, vehicle class
- For parking: look for parking location, duration, rate
- Due date is important for challans
- Vehicle registration number is critical for this category""",

            "Other": """
**General Expense Instructions**:
- Extract the party/vendor name who received the payment
- Identify what the expense was for (expense_name)
- Look for any invoice/bill reference numbers""",
        }

        hints = category_hints.get(category, "")

        return f"""You are analyzing an Indian expense document image classified as: **{category}**

**Task**: Extract ALL the following fields from this document and return as a JSON object.

**Fields to extract**:
{fields_text}

**General Rules**:
- Dates MUST be in YYYY-MM-DD format. Indian dates are DD/MM/YYYY.
- Amounts are in INR (₹ / Rs.). Extract numeric values only (no currency symbols).
- For missing/unclear fields, use null.
- Vehicle registration format: 2 letters + 2 digits + 1-3 letters + 1-4 digits (e.g., MH12AB1234)
- Phone numbers: 10 digits starting with 6-9 (Indian mobile)
{hints}

**CRITICAL**: Return ONLY a valid JSON object. No markdown fences, no explanation, no extra text.
Just the raw JSON object starting with {{ and ending with }}."""
    else:
        return f"""You are analyzing an Indian expense document image classified as: **{category}**

**Task**: Extract standard fields from this document and return as a JSON object.

**Standard fields to extract**:
  - "category" (string) (REQUIRED): Must be exactly "{category}"
  - "expense_date" (string) (REQUIRED): Date of the bill/transaction in YYYY-MM-DD format
  - "amount" (number) (REQUIRED): Total amount paid or payable in INR (₹). This is the final/grand total.
  - "vendor" (string): Business/authority name issuing the bill
  - "invoice_number" (string): Bill number, consumer ID, or invoice reference number
  - "contact_number" (string): Any contact phone number visible on the bill
  - "paid_to" (string): Payee name if visible

**General Rules**:
- Dates MUST be in YYYY-MM-DD format. Indian dates are DD/MM/YYYY.
- Amounts are in INR (₹ / Rs.). Extract numeric values only (no currency symbols).
- For missing/unclear fields, use null.

**CRITICAL**: Return ONLY a valid JSON object. No markdown fences, no explanation, no extra text.
Just the raw JSON object starting with {{ and ending with }}."""


async def run_stage3(image_bytes: bytes, content_type: str) -> dict:
    """
    Stage 3: LLM Extraction & Categorization.
    Runs LLM Vision processing (single pass or two-pass) and returns raw output & category.
    """
    start_time = time.time()
    provider = get_llm_provider()
    single_pass = os.getenv("SINGLE_PASS_MODE", "true").lower().strip() == "true"

    if single_pass:
        print("[LLM Stage 3] Running in SINGLE-PASS mode...")
        prompt = build_single_pass_prompt()
        try:
            response = await provider.extract_from_image(
                image_bytes, prompt, content_type
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"LLM Single-Pass extraction failed ({provider.provider_name}): {str(e)}"
            )

        if not response:
            raise HTTPException(
                status_code=502,
                detail=f"LLM Single-Pass returned empty response ({provider.provider_name})"
            )

        category = detect_category_from_llm_response(response)
        print(f"[LLM Stage 3] Detected category: {category}")
        merged = response
        merged["category"] = category
    else:
        print("[LLM Stage 3] Running in TWO-PASS mode...")
        print("[LLM Stage 3] Pass 1: General extraction & category detection...")
        pass1_prompt = build_pass1_prompt()

        try:
            pass1_response = await provider.extract_from_image(
                image_bytes, pass1_prompt, content_type
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"LLM Pass 1 failed ({provider.provider_name}): {str(e)}"
            )

        if not pass1_response:
            raise HTTPException(
                status_code=502,
                detail=f"LLM Pass 1 returned empty response ({provider.provider_name})"
            )

        category = detect_category_from_llm_response(pass1_response)
        print(f"[LLM Stage 3] Detected category: {category}")

        print(f"[LLM Stage 3] Pass 2: {category}-specific extraction...")
        pass2_prompt = build_pass2_prompt(category)

        try:
            pass2_response = await provider.extract_from_image(
                image_bytes, pass2_prompt, content_type
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"LLM Pass 2 failed ({provider.provider_name}): {str(e)}"
            )

        if not pass2_response:
            raise HTTPException(
                status_code=502,
                detail=f"LLM Pass 2 returned empty response ({provider.provider_name})"
            )

        merged = pass2_response
        merged["category"] = category

    latency = time.time() - start_time
    return {
        "raw_response": merged,
        "category": category,
        "extraction_latency": round(latency, 2)
    }


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
                                         current_stage or "stage3_extract", original_url))
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

def _download_blob(blob_url: str) -> bytes:
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    client = BlobServiceClient.from_connection_string(conn_str)
    
    parts = blob_url.split(".blob.core.windows.net/")
    if len(parts) < 2:
        raise ValueError(f"Invalid blob URL: {blob_url}")
    rest = parts[1]
    container, _, blob_path = rest.partition("/")
    blob_c = client.get_blob_client(container=container, blob=blob_path)
    return blob_c.download_blob().readall()


# ─────────────────────────────────────────────────────────
#  Service Bus Queue Trigger
# ─────────────────────────────────────────────────────────
@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="%AZURE_QUEUE_STAGE3%",
    connection="ServiceBusConnection"
)
async def stage3_extract(msg: func.ServiceBusMessage):
    body = msg.get_body().decode('utf-8')
    try:
        payload = json.loads(body)
    except Exception as e:
        logger.error(f"[Stage3] Failed to parse message body JSON: {e}")
        return

    job_id = payload.get("job_id")
    blob_url = payload.get("blob_url")
    filename = payload.get("filename")
    content_type = payload.get("content_type")

    if not job_id or not blob_url:
        logger.error(f"[Stage3] Missing job_id or blob_url in payload: {payload}")
        return

    logger.info(f"[Stage3] Starting LLM vision extraction for job={job_id}")

    try:
        # 1. Update status to stage_3
        _update_stage_tracking(
            job_id=job_id,
            status="stage_3",
            current_stage="stage3_extract"
        )
        _send_callback(job_id, "stage_3")

        # 2. Download preprocessed image bytes
        image_bytes = _download_blob(blob_url)

        # 3. Call LLM extraction logic
        result = await run_stage3(image_bytes, content_type)
        raw_response = result["raw_response"]
        category = result["category"]

        # 4. Update tracking with category
        _update_stage_tracking(
            job_id=job_id,
            category=category,
            completed_stage_num=3
        )

        # 5. Forward to Stage 4
        next_payload = {
            "job_id": job_id,
            "blob_url": blob_url,
            "filename": filename,
            "content_type": content_type,
            "category": category,
            "raw_response": raw_response
        }
        _forward_to_next_stage(4, next_payload)
        _send_callback(job_id, "stage_4")
        logger.info(f"[Stage3] Completed successfully for job={job_id} detected_category={category}")

    except Exception as e:
        error_msg = f"Stage 3 failed: {str(e)}"
        logger.error(f"[Stage3] {error_msg}")
        _update_stage_tracking(job_id=job_id, status="failed", error_message=error_msg)
        _send_callback(job_id, "failed", error_msg)

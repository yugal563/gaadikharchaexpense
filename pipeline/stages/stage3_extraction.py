import os
import time
from fastapi import HTTPException
from services.llm_providers import get_llm_provider
from pipeline.stages.schemas import CATEGORY_SCHEMAS

# ──────────────────────────────────────────────────────────────────────
#  Category Detection & Schema Helper (from category.py)
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
#  LLM Prompt Builders (from prompts.py)
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
  - "items" (array of objects): list of line items, each with "description", "quantity", "unit_price", and "total".

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
  - "items" (array of objects): list of line items, each with "description", "quantity", "unit_price", and "total".
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
  - "items" (array of objects): list of line items, each with "description", "quantity", "unit_price", and "total".
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
  - "items" (array of objects): list of line items, each with "description", "quantity", "unit_price", and "total".
  - "action_type" (string): type of action/expense description

**3. Output Requirements**:
- Return ONLY a valid JSON object.
- Dates must be in YYYY-MM-DD format (use Indian DD/MM/YYYY rules for parsing).
- Datetimes must be in YYYY-MM-DD HH:MM:SS format if present.
- Currency must be in INR.
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


# ──────────────────────────────────────────────────────────────────────
#  Stage 3 Orchestrator (run_stage3)
# ──────────────────────────────────────────────────────────────────────
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

"""
engine/prompts.py — LLM prompt builders for single-pass and two-pass extraction.
"""

from engine.schemas import CATEGORY_SCHEMAS


def build_single_pass_prompt() -> str:
    """
    Build a single-pass extraction prompt containing schemas for all categories.
    Used for extremely low latency document parsing.
    """
    return """You are analyzing an Indian financial document (receipt, invoice, bill, payslip, or statement).
**Task**: Identify the category and extract all relevant fields as a JSON object.

**1. Classify the Category**:
- "Fuel" — petrol/diesel receipts from fuel stations (HPCL, BPCL, Indian Oil, Shell, etc.)
- "Maintenance" — vehicle repair/service invoices from workshops/garages
- "Vehicle" — challans, traffic fines, toll receipts, parking tickets
- "Salary Slip" — payslips, salary statements, pay stubs showing employee earnings and deductions
- "Rent Receipt" — house/office rent receipts or lease agreements
- "Hotel Bill" — hotel stay, accommodation, lodge bills
- "Food Bill" — restaurant, canteen, food delivery receipts
- "Medical Bill" — hospital, pharmacy, clinic, lab test bills
- "Internet Bill" — broadband, mobile data, ISP bills
- "Electricity Bill" — electricity/power utility bills
- "Water Bill" — water utility bills
- Any other **specific descriptive name** (e.g., "Insurance Premium", "Stationery Invoice", "Air Ticket", "Train Ticket") if the document is a clearly identifiable type.
- Otherwise, default to "Other".

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

If the category is **Salary Slip**, extract:
  - "category": "Salary Slip"
  - "expense_date" (string): YYYY-MM-DD — use the pay date / paid_on date (last day of the pay period)
  - "amount" (number): Net Pay / Take-home pay in INR — this is the most important field
  - "employee_name" (string): full name of the employee
  - "employee_id" (string): employee ID exactly as shown (e.g. PS67890) — keep alphabetic prefix
  - "designation" (string): job title/designation
  - "department" (string): department name
  - "employer" (string): company/employer name
  - "pay_period" (string): month and year (e.g. "January 2024")
  - "bank_name" (string): bank name
  - "bank_account_number" (string): bank account number
  - "uan" (string): Universal Account Number (UAN)
  - "date_of_joining" (string): YYYY-MM-DD
  - "total_working_days" (integer): total working days in pay period
  - "lop_days" (integer): loss of pay days
  - "paid_days" (integer): actual paid days
  - "gross_earnings" (number): total gross earnings before deductions
  - "total_deductions" (number): total of all deductions
  - "net_pay" (number): net / take-home pay (= gross_earnings - total_deductions)
  - "amount_in_words" (string): net pay in words
  - "earnings" (object): breakdown of earnings components (basic_salary, hra, conveyance, etc.)
  - "deductions" (object): breakdown of deduction components (epf, esi, professional_tax, etc.)
  - "paid" (boolean): true if salary has been disbursed

If the category is a **specific custom bill** (e.g. Water Bill, Electricity Bill):
  - "category" (string): the specific bill category name (e.g. "Water Bill")
  - "expense_date" (string): YYYY-MM-DD
  - "amount" (number): total amount paid in INR (₹)
  - "vendor" (string): payee/utility name
  - "invoice_number" (string): invoice/bill reference number
  - "contact_number" (string): phone number
  - "paid_to" (string): payee name
  - Dynamically extract any other relevant fields visible on the bill as custom JSON keys (e.g. "units_consumed", "meter_reading", "consumer_no", "due_date", "previous_reading", etc.).

If the category is **Other**, extract:
  - "category": "Other"
  - "expense_date" (string): YYYY-MM-DD
  - "amount" (number): total amount paid in INR (₹)
  - "registration_no" (string): vehicle registration number
  - "location" (string): city/location
  - "party_type" (string): vendor, customer, etc.
  - "party" (string): party name
  - "contact" (string): contact details
  - "expense_name" (string): description of the expense
  - "invoice_number" (string): invoice/bill number
  - "contact_number" (string): phone number
  - "paid_to" (string): payee name

**3. Output Requirements**:
- Return ONLY a valid JSON object.
- Dates must be in YYYY-MM-DD format (use Indian DD/MM/YYYY rules for parsing).
- Currency must be in INR.
- Do not include markdown fences, comments, or extra text.
"""


def build_pass1_prompt() -> str:
    """
    Build the Pass 1 (general extraction) prompt.

    This prompt asks the LLM to:
    1. Read all text from the document
    2. Classify the expense category
    3. Extract basic fields (vendor, date, amount)
    """
    return """You are analyzing an Indian financial document (receipt, invoice, bill, payslip, or statement).

**Task**: Extract the following information and return it as a JSON object.

**Instructions**:
1. Identify the type of document:
   - "Fuel" — petrol/diesel receipts from fuel stations (HPCL, BPCL, Indian Oil, Nayara, Shell, etc.)
   - "Maintenance" — vehicle repair/service invoices from workshops/garages
   - "Vehicle" — challans, toll receipts, parking tickets, traffic fines
   - "Salary Slip" — payslips, salary statements, pay stubs (employee name, basic pay, deductions, net pay)
   - "Rent Receipt" — rent/lease payment receipts
   - "Hotel Bill" — hotel/lodge/accommodation bills
   - "Food Bill" — restaurant, canteen, or food delivery receipts
   - "Medical Bill" — hospital, pharmacy, diagnostic lab bills
   - "Internet Bill", "Electricity Bill", "Water Bill" — utility bills
   - Any other clearly identifiable document type — return a specific, descriptive name (e.g. "Air Ticket", "Train Ticket", "Insurance Premium", "Stationery Invoice").
   - Otherwise, default to "Other".

2. Extract these fields:
   - "category": one of "Fuel", "Maintenance", "Vehicle", "Other" or a specific name like "Water Bill"
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
    """
    Build the Pass 2 (category-specific extraction) prompt.

    This prompt uses the exact schema for the detected category,
    asking the LLM to extract all relevant fields with precise formatting.
    """
    if category in CATEGORY_SCHEMAS:
        schema = CATEGORY_SCHEMAS[category]

        # Build field descriptions for the prompt
        fields_desc = []
        for field_name, field_info in schema.items():
            required = " (REQUIRED)" if field_info.get("required") else ""
            field_type = field_info["type"]
            desc = field_info["description"]
            fields_desc.append(f'  - "{field_name}" ({field_type}){required}: {desc}')

        fields_text = "\n".join(fields_desc)

        # Category-specific extraction hints
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
        # Custom category prompt
        return f"""You are analyzing an Indian expense document image classified as a custom category: **{category}**

**Task**: 
1. Identify the key fields unique to a **{category}** document (e.g., consumer number, connection ID, billing cycle, units consumed, previous reading, etc.).
2. Extract those custom fields along with the standard common fields below.
3. Return all extracted information as a single JSON object.

**Standard fields to extract**:
  - "category" (string) (REQUIRED): Must be exactly "{category}"
  - "expense_date" (string) (REQUIRED): Date of the bill/transaction in YYYY-MM-DD format
  - "amount" (number) (REQUIRED): Total amount paid or payable in INR (₹). This is the final/grand total.
  - "vendor" (string): Business/authority name issuing the bill
  - "invoice_number" (string): Bill number, consumer ID, or invoice reference number
  - "contact_number" (string): Any contact phone number visible on the bill
  - "paid_to" (string): Payee name if visible

**Custom fields to extract**:
- Identify 3 to 6 fields most relevant to a **{category}** (e.g., "consumer_no", "units_consumed", "billing_cycle", etc.). Use clean snake_case names for these keys and extract their values from the document.

**General Rules**:
- Dates MUST be in YYYY-MM-DD format. Indian dates are DD/MM/YYYY.
- Amounts are in INR (₹ / Rs.). Extract numeric values only (no currency symbols).
- For missing/unclear fields, use null.

**CRITICAL**: Return ONLY a valid JSON object. No markdown fences, no explanation, no extra text.
Just the raw JSON object starting with {{ and ending with }}."""

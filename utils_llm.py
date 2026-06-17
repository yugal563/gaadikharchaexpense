import os
import json
from pydantic import BaseModel, Field

class LLMParsedReceipt(BaseModel):
    category: str = Field(
        ...,
        description="The category of the expense. Must be exactly one of: 'Fuel', 'Maintenance', 'Vehicle', or 'Other'."
    )
    expense_date: str = Field(
        ...,
        description="The date of the receipt/transaction in YYYY-MM-DD format."
    )
    amount: float = Field(
        ...,
        description="The total amount of the transaction. Must be a non-negative float."
    )
    liters: float | None = Field(
        None,
        description="The fuel volume in liters, if the category is 'Fuel'."
    )
    rate_per_liter: float | None = Field(
        None,
        description="The fuel rate per liter, if the category is 'Fuel'."
    )
    petrol_pump: str | None = Field(
        None,
        description="The name or brand of the petrol pump (e.g. 'HPCL', 'Indian Oil', 'BPCL', 'Nayara', 'Shell'), if the category is 'Fuel'."
    )
    vendor: str | None = Field(
        None,
        description="The name of the vendor or merchant (e.g. workshop name, store, pump name)."
    )
    service_type: str | None = Field(
        None,
        description="The type of service done (e.g. 'Periodic Maintenance', 'Car Washing', 'General Service', 'Tire Alignment'), if category is 'Maintenance' or 'Vehicle'."
    )
    odometer: int | None = Field(
        None,
        description="The odometer reading shown on the receipt, if present."
    )
    registration_no: str | None = Field(
        None,
        description="The vehicle registration number (license plate), MH12AB1234 or similar format, if present."
    )
    location: str | None = Field(
        None,
        description="The city, state, or location of the transaction, if present."
    )
    remarks: str | None = Field(
        None,
        description="Any other interesting notes or comments from the receipt text."
    )
    
    # --- New Additional Fields ---
    invoice_number: str | None = Field(None, description="The invoice number or receipt number.")
    taxable_amount: float | None = Field(None, description="The taxable amount before GST/taxes.")
    non_taxable_amount: float | None = Field(None, description="Any non-taxable amount mentioned.")
    total_amount: float | None = Field(None, description="The grand total amount on the invoice (should generally match 'amount').")
    gst_percentage: float | None = Field(None, description="The GST percentage applied (e.g. 5, 12, 18, 28).")
    gst_amount: float | None = Field(None, description="The total GST tax amount.")
    gst_invoicing_type: str | None = Field(None, description="Type of GST invoicing (e.g., 'B2B', 'B2C').")
    
    maintenance_item: str | None = Field(None, description="Specific maintenance item or spare part mentioned.")
    custom_maintenance_item: str | None = Field(None, description="Any custom or miscellaneous maintenance item.")
    
    km_limit: int | None = Field(None, description="Kilometer limit for rentals or travel.")
    hour_limit: int | None = Field(None, description="Hour limit for rentals or travel.")
    excess_km_rate: float | None = Field(None, description="Rate charged per excess kilometer.")
    excess_hour_rate: float | None = Field(None, description="Rate charged per excess hour.")
    excess_km_amount: float | None = Field(None, description="Total amount charged for excess kilometers.")
    excess_hour_amount: float | None = Field(None, description="Total amount charged for excess hours.")
    driver_allowance: float | None = Field(None, description="Allowance provided for the driver.")
    
    toll_charges: float | None = Field(None, description="Toll tax or FASTag charges.")
    parking_charges: float | None = Field(None, description="Parking charges.")
    other_charges: float | None = Field(None, description="Any other miscellaneous charges.")
    
    tds_percentage: float | None = Field(None, description="TDS (Tax Deducted at Source) percentage.")
    tds_amount: float | None = Field(None, description="TDS amount deducted.")
    
    gst_applicable_on_parking: bool | None = Field(None, description="Whether GST was applied on parking charges.")
    gst_applicable_on_toll: bool | None = Field(None, description="Whether GST was applied on toll charges.")
    gst_applicable_on_other_charges: bool | None = Field(None, description="Whether GST was applied on other charges.")
    
    paid_to: str | None = Field(None, description="The name of the person or entity to whom payment was made.")
    contact_number: str | None = Field(None, description="Phone number or contact info found on the receipt.")


def validate_and_parse_with_llm(ocr_text: str) -> dict | None:
    """
    Sends the raw OCR text to Gemini or OpenAI for structured extraction and semantic cleanup.
    Returns a dict containing the parsed fields, or None if keys are missing or calls fail.
    """
    gemini_key = os.getenv("GEMINI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    azure_openai_key = os.getenv("AZURE_OPENAI_KEY")
    azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")

    if not gemini_key and not openai_key and not azure_openai_key:
        print("[LLM Pipeline] No GEMINI_API_KEY, OPENAI_API_KEY, or AZURE_OPENAI_KEY found. Skipping LLM validation.")
        return None

    prompt = (
        "You are an expert receipt OCR parsing validator. Your job is to extract receipt fields from raw OCR text.\n"
        "Here is the raw OCR text from a receipt:\n\n"
        f"--- START OCR TEXT ---\n{ocr_text}\n--- END OCR TEXT ---\n\n"
        "IMPORTANT: The input raw OCR text might come from a handwritten, faint, or unclear receipt. "
        "It may contain spelling mistakes, layout shifts, or character substitutions due to OCR errors (for example: "
        "letter 'S' or 's' instead of digit '5', letter 'I', 'l', or 'i' instead of '1', letter 'O' or 'o' instead of '0', or letter 'Z' or 'z' instead of '2'). "
        "Use semantic context, word shapes, and standard pricing/liter structures in Indian Rupees to reconstruct the correct details. "
        "For example, if a fuel rate says '1O4.3' or '104.3O', correct it to '104.30'. If registration number says 'MHl2', correct to 'MH12'.\n\n"
        "Please extract and populate the fields in the requested schema. Ensure the category is normalized to "
        "one of the allowed strings ('Fuel', 'Maintenance', 'Vehicle', 'Other'), the date is YYYY-MM-DD, and the numbers are correctly parsed. "
        "Verify standard calculations: if Fuel, check if amount, liters, and rate_per_liter are mathematically consistent. "
        "Pay special attention to extracting Invoice Numbers, GST Percentages, Taxable/Total Amounts, Toll/Parking Charges, and any specific Maintenance Items or Limits mentioned in the text."
    )

    # 1. Prioritize Azure OpenAI / AI Studio if key and endpoint are provided
    if azure_openai_key and azure_openai_endpoint:
        try:
            print("[LLM Pipeline] Calling Azure AI Studio GPT model for structured validation...")
            from openai import OpenAI

            # Ensure we append /openai/v1 if not present in the endpoint
            base_url = azure_openai_endpoint.rstrip('/')
            if not base_url.endswith("/openai/v1"):
                base_url = f"{base_url}/openai/v1"

            client = OpenAI(
                api_key=azure_openai_key,
                base_url=base_url
            )
            model_name = os.getenv("AZURE_OPENAI_MODEL_NAME", "gpt-4o-mini")

            completion = client.beta.chat.completions.parse(
                model=model_name,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                response_format=LLMParsedReceipt,
            )
            parsed_data = completion.choices[0].message.parsed
            if parsed_data:
                data = parsed_data.model_dump()
                print(f"[LLM Pipeline] Azure OpenAI successfully validated fields: {data}")
                return data
        except Exception as e:
            print(f"[LLM Pipeline] Azure OpenAI validation failed: {e}")

    # 2. Fallback to Gemini if its key is available
    if gemini_key:
        try:
            print("[LLM Pipeline] Calling Gemini 2.5 Flash for structured validation...")
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=gemini_key)
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=LLMParsedReceipt,
                )
            )
            # Parse the response JSON
            data = json.loads(response.text)
            print(f"[LLM Pipeline] Gemini successfully validated fields: {data}")
            return data
        except Exception as e:
            print(f"[LLM Pipeline] Gemini validation failed: {e}")

    # 3. Fallback to standard OpenAI if key is available
    if openai_key:
        try:
            print("[LLM Pipeline] Calling OpenAI GPT-4o-mini for structured validation...")
            from openai import OpenAI

            client = OpenAI(api_key=openai_key)
            completion = client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                response_format=LLMParsedReceipt,
            )
            parsed_data = completion.choices[0].message.parsed
            if parsed_data:
                data = parsed_data.model_dump()
                print(f"[LLM Pipeline] OpenAI successfully validated fields: {data}")
                return data
        except Exception as e:
            print(f"[LLM Pipeline] OpenAI validation failed: {e}")

    return None

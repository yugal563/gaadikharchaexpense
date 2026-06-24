"""
engine/validator.py — Business-rule validation and category-based field filtering.
"""

import re
from datetime import datetime

from engine.schemas import CATEGORY_SCHEMAS


def validate_extracted_fields(fields: dict, category: str) -> dict:
    """
    Apply business-rule validation to extracted fields.
    Corrects obvious errors and fills in computable missing values.
    """
    # ── Date validation ──
    expense_date = fields.get("expense_date")
    if expense_date:
        date_str = str(expense_date)[:10]
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            fields["expense_date"] = dt.strftime("%Y-%m-%d")
        except ValueError:
            try:
                dt = datetime.strptime(date_str, "%d-%m-%Y")
                fields["expense_date"] = dt.strftime("%Y-%m-%d")
            except ValueError:
                try:
                    dt = datetime.strptime(date_str, "%d/%m/%Y")
                    fields["expense_date"] = dt.strftime("%Y-%m-%d")
                except ValueError:
                    fields["expense_date"] = datetime.now().strftime("%Y-%m-%d")
    else:
        fields["expense_date"] = datetime.now().strftime("%Y-%m-%d")

    # ── Amount validation ──
    amount = fields.get("amount")
    if amount is not None:
        amount = float(amount) if amount else 0.0
        # Cap at 10 million (₹1 crore) — beyond this is likely a parsing error
        if amount > 10_000_000:
            amount = 0.0
        if amount < 0:
            amount = abs(amount)
        fields["amount"] = round(amount, 2)
    else:
        fields["amount"] = 0.0


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

    return fields


def filter_fields_by_category(fields: dict, category: str, include_db_keys: bool = False) -> dict:
    """
    Filter extracted fields to only include those relevant to the category.
    Mirrors the filter_db_record_by_category logic in main.py.
    """
    # For custom categories, keep all extracted fields dynamically
    if category not in CATEGORY_SCHEMAS:
        return fields

    common_keys = {
        "category", "expense_date", "amount", "paid", "remarks",
        "location", "registration_no", "contact_number", "invoice_number", "paid_to",
    }

    if include_db_keys:
        common_keys.add("expense_id")
        common_keys.add("vehicle")

    category_keys = {
        "Fuel": {"liters", "rate_per_liter", "petrol_pump", "vendor", "odometer"},
        "Maintenance": {
            "vendor", "odometer", "service_type", "vendor_type",
            "maintenance_item", "custom_maintenance_item", "taxable_amount",
            "non_taxable_amount", "gst_percentage", "gst_amount", "gst_invoicing_type",
        },
        "Vehicle": {
            "challan_no", "challan_type", "violation_type", "issued_by", "due_date",
            "parking_location", "km_limit", "hour_limit", "excess_km_rate",
            "excess_hour_rate", "excess_km_amount", "excess_hour_amount",
            "driver_allowance", "toll_charges", "parking_charges", "other_charges",
            "gst_applicable_on_parking", "gst_applicable_on_toll",
            "gst_applicable_on_other_charges", "gst_percentage", "gst_amount",
            "tds_percentage", "tds_amount", "service_type",
        },
        "Other": {"party_type", "party", "expense_name"},
    }

    allowed = common_keys | category_keys.get(category, category_keys["Other"])
    return {k: v for k, v in fields.items() if k in allowed}

"""
services/db_service.py — Database persistence helpers.

Provides:
    - save_expenses_to_db()         — Bulk-insert parsed expense records into MySQL
    - filter_db_record_by_category() — Strip irrelevant columns per expense category
"""

import json
from db import get_connection


def save_expenses_to_db(parsed_list: list[dict]) -> list[int]:
    """Insert a list of parsed expense dicts into the expenses table. Returns inserted IDs."""
    expense_ids = []
    conn = get_connection()
    with conn.cursor() as cursor:
        sql = """
        INSERT INTO expenses
        (
            category, vehicle, expense_date, petrol_pump, location,
            liters, rate_per_liter, odometer, service_type, vendor,
            amount, paid, registration_no, challan_no, challan_type,
            violation_type, issued_by, due_date, remarks,
            party_type, party, contact, expense_name,
            vendor_type, parking_location, maintenance_item, custom_maintenance_item,
            invoice_number, taxable_amount, non_taxable_amount,
            km_limit, hour_limit, excess_km_rate, excess_hour_rate,
            excess_km_amount, excess_hour_amount, driver_allowance,
            toll_charges, parking_charges, other_charges, tds_percentage,
            tds_amount, gst_percentage, gst_amount, gst_invoicing_type,
            gst_applicable_on_parking, gst_applicable_on_toll, gst_applicable_on_other_charges,
            paid_to, contact_number
        )
        VALUES
        (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
         %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """
        for parsed in parsed_list:
            orig_category = parsed.get("category", "Other")
            if orig_category not in ("Fuel", "Maintenance", "Vehicle", "Other"):
                db_category = "Other"
                custom_remarks = f"[Custom JSON]: {json.dumps(parsed)}"
                expense_name_val = parsed.get("expense_name") or orig_category
            else:
                db_category = orig_category
                custom_remarks = parsed.get("remarks")
                expense_name_val = parsed.get("expense_name")

            cursor.execute(sql, (
                db_category,
                parsed.get("vehicle")[:50] if parsed.get("vehicle") else None,
                parsed.get("expense_date"),
                parsed.get("petrol_pump")[:100] if parsed.get("petrol_pump") else None,
                parsed.get("location")[:100] if parsed.get("location") else None,
                parsed.get("liters"),
                parsed.get("rate_per_liter"),
                parsed.get("odometer"),
                parsed.get("service_type")[:100] if parsed.get("service_type") else None,
                parsed.get("vendor")[:100] if parsed.get("vendor") else None,
                parsed.get("amount"),
                parsed.get("paid"),
                parsed.get("registration_no")[:20] if parsed.get("registration_no") else None,
                parsed.get("challan_no")[:50] if parsed.get("challan_no") else None,
                parsed.get("challan_type")[:100] if parsed.get("challan_type") else None,
                parsed.get("violation_type")[:255] if parsed.get("violation_type") else None,
                parsed.get("issued_by")[:100] if parsed.get("issued_by") else None,
                parsed.get("due_date"),
                custom_remarks,
                parsed.get("party_type")[:100] if parsed.get("party_type") else None,
                parsed.get("party")[:100] if parsed.get("party") else None,
                parsed.get("contact")[:100] if parsed.get("contact") else None,
                expense_name_val[:100] if expense_name_val else None,
                parsed.get("vendor_type")[:20] if parsed.get("vendor_type") else None,
                parsed.get("parking_location")[:100] if parsed.get("parking_location") else None,
                parsed.get("maintenance_item")[:100] if parsed.get("maintenance_item") else None,
                parsed.get("custom_maintenance_item")[:255] if parsed.get("custom_maintenance_item") else None,
                parsed.get("invoice_number")[:50] if parsed.get("invoice_number") else None,
                parsed.get("taxable_amount"),
                parsed.get("non_taxable_amount"),
                parsed.get("km_limit"),
                parsed.get("hour_limit"),
                parsed.get("excess_km_rate"),
                parsed.get("excess_hour_rate"),
                parsed.get("excess_km_amount"),
                parsed.get("excess_hour_amount"),
                parsed.get("driver_allowance"),
                parsed.get("toll_charges"),
                parsed.get("parking_charges"),
                parsed.get("other_charges"),
                parsed.get("tds_percentage"),
                parsed.get("tds_amount"),
                parsed.get("gst_percentage"),
                parsed.get("gst_amount"),
                parsed.get("gst_invoicing_type")[:50] if parsed.get("gst_invoicing_type") else None,
                parsed.get("gst_applicable_on_parking"),
                parsed.get("gst_applicable_on_toll"),
                parsed.get("gst_applicable_on_other_charges"),
                parsed.get("paid_to")[:255] if parsed.get("paid_to") else None,
                parsed.get("contact_number")[:15] if parsed.get("contact_number") else None,
            ))
            expense_ids.append(cursor.lastrowid)
        conn.commit()
    conn.close()
    return expense_ids


def filter_db_record_by_category(record: dict) -> dict:
    """Filter a DB record's columns to only those relevant to its expense category."""
    if not record:
        return record

    remarks = record.get("remarks")
    if remarks and isinstance(remarks, str) and remarks.startswith("[Custom JSON]:"):
        try:
            custom_data = json.loads(remarks[len("[Custom JSON]:"):].strip())
            record.update(custom_data)
            record["remarks"] = custom_data.get("remarks")
            return record
        except Exception:
            pass

    category = record.get("category")

    common_keys = {
        "expense_id", "category", "vehicle", "expense_date", "amount",
        "paid", "remarks", "location", "registration_no", "contact_number",
        "invoice_number", "paid_to"
    }

    if category == "Fuel":
        category_keys = {"liters", "rate_per_liter", "petrol_pump", "vendor", "odometer"}
    elif category == "Maintenance":
        category_keys = {
            "vendor", "odometer", "service_type", "vendor_type",
            "maintenance_item", "custom_maintenance_item", "taxable_amount",
            "non_taxable_amount", "gst_percentage", "gst_amount", "gst_invoicing_type"
        }
    elif category == "Vehicle":
        category_keys = {
            "challan_no", "challan_type", "violation_type", "issued_by", "due_date",
            "parking_location", "km_limit", "hour_limit", "excess_km_rate",
            "excess_hour_rate", "excess_km_amount", "excess_hour_amount",
            "driver_allowance", "toll_charges", "parking_charges", "other_charges",
            "gst_applicable_on_parking", "gst_applicable_on_toll",
            "gst_applicable_on_other_charges", "gst_percentage", "gst_amount",
            "tds_percentage", "tds_amount", "service_type"
        }
    elif category == "Other":
        category_keys = {"party_type", "party", "contact", "expense_name"}
    else:
        # Custom category — return all fields
        return record

    allowed_keys = common_keys | category_keys
    return {k: v for k, v in record.items() if k in allowed_keys}

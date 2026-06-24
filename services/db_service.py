"""
services/db_service.py — Database persistence helpers.

Provides:
    - insert_expense()              — Execute the INSERT SQL statement for a single Expense object
    - save_expenses_to_db()         — Bulk-insert parsed expense records into MySQL
"""

import json
from services.db import get_connection
from models import Expense
from engine.validator import filter_fields_by_category


def insert_expense(cursor, expense: Expense) -> int:
    """Execute the INSERT SQL statement for a single Expense object. Returns lastrowid."""
    sql = """
    INSERT INTO expenses
    (
        category, vehicle, expense_date, petrol_pump, location,
        liters, rate_per_liter, odometer, service_type, vendor,
        amount, paid, registration_no, challan_no, challan_type,
        violation_type, issued_by, due_date, remarks,
        party_type, party, expense_name,
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
    (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
     %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """
    cursor.execute(sql, (
        expense.category,
        expense.vehicle[:50] if expense.vehicle else None,
        expense.expense_date,
        expense.petrol_pump[:100] if expense.petrol_pump else None,
        expense.location[:100] if expense.location else None,
        expense.liters,
        expense.rate_per_liter,
        expense.odometer,
        expense.service_type[:100] if expense.service_type else None,
        expense.vendor[:100] if expense.vendor else None,
        expense.amount,
        expense.paid,
        expense.registration_no[:20] if expense.registration_no else None,
        expense.challan_no[:50] if expense.challan_no else None,
        expense.challan_type[:100] if expense.challan_type else None,
        expense.violation_type[:255] if expense.violation_type else None,
        expense.issued_by[:100] if expense.issued_by else None,
        expense.due_date,
        expense.remarks,
        expense.party_type[:100] if expense.party_type else None,
        expense.party[:100] if expense.party else None,
        expense.expense_name[:100] if expense.expense_name else None,
        expense.vendor_type[:20] if expense.vendor_type else None,
        expense.parking_location[:100] if expense.parking_location else None,
        expense.maintenance_item[:100] if expense.maintenance_item else None,
        expense.custom_maintenance_item[:255] if expense.custom_maintenance_item else None,
        expense.invoice_number[:50] if expense.invoice_number else None,
        expense.taxable_amount,
        expense.non_taxable_amount,
        expense.km_limit,
        expense.hour_limit,
        expense.excess_km_rate,
        expense.excess_hour_rate,
        expense.excess_km_amount,
        expense.excess_hour_amount,
        expense.driver_allowance,
        expense.toll_charges,
        expense.parking_charges,
        expense.other_charges,
        expense.tds_percentage,
        expense.tds_amount,
        expense.gst_percentage,
        expense.gst_amount,
        expense.gst_invoicing_type[:50] if expense.gst_invoicing_type else None,
        expense.gst_applicable_on_parking,
        expense.gst_applicable_on_toll,
        expense.gst_applicable_on_other_charges,
        expense.paid_to[:255] if expense.paid_to else None,
        expense.contact_number[:15] if expense.contact_number else None,
    ))
    return cursor.lastrowid


def save_expenses_to_db(parsed_list: list[dict]) -> list[int]:
    """Insert a list of parsed expense dicts into the expenses table. Returns inserted IDs."""
    expense_ids = []
    conn = get_connection()
    with conn.cursor() as cursor:
        for parsed in parsed_list:
            # Re-validate and normalize the LLM parsed dict through the Expense model
            expense = Expense(parsed)
            expense_id = insert_expense(cursor, expense)
            expense_ids.append(expense_id)
        conn.commit()
    conn.close()
    return expense_ids

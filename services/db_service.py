"""
services/db_service.py — Database persistence helpers.

Provides:
    - insert_expense()              — Execute the INSERT SQL statement for a single Expense object
    - save_expenses_to_db()         — Bulk-insert parsed expense records into MySQL
"""

import json
from services.db import get_connection
from models import Expense
from pipeline.stages.stage5_filtering import filter_fields_by_category


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
            gst_amount, payment_mode, paid, paid_to, contact_number
        ) VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
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
        ))
        
    elif base_category == "Maintenance":
        sql = """
        INSERT INTO maintenance (
            vehicle, registration_no, expense_date, service_type, vendor,
            vendor_type, maintenance_item, custom_maintenance_item, action_type, odometer,
            next_service_due, work_order_number, invoice_number, amount, total_amount,
            taxable_amount, non_taxable_amount, gst_percentage, gst_amount, payment_mode,
            paid, paid_to, contact_number, items
        ) VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
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
            tds_amount, payment_mode, paid, paid_to, contact_number, items
        ) VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
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
        ))
        
    else:  # Other or Custom category
        sql = """
        INSERT INTO other (
            vehicle, registration_no, expense_date, party_type, party,
            expense_name, vendor, location, invoice_number, amount,
            total_amount, taxable_amount, non_taxable_amount, gst_percentage, gst_amount,
            payment_mode, paid, paid_to, contact_number, items
        ) VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
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

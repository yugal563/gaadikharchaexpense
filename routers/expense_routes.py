"""
routers/expense_routes.py — CRUD endpoints for expense records.

Endpoints:
    POST   /expenses                        → Create a new expense manually
    GET    /expenses                        → List all expenses (newest first)
    GET    /expenses/{expense_id}           → Get a single expense by ID
    DELETE /expenses/{expense_id}           → Delete an expense by ID
    GET    /expenses/category/{category}    → Filter expenses by category
"""

import json

from fastapi import APIRouter, HTTPException

from db import get_connection
from models import Expense
from services.db_service import filter_db_record_by_category

router = APIRouter()


@router.post("/expenses")
def create_expense(expense: Expense):
    """Manually create a new expense record."""
    try:
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
            orig_category = expense.category
            expense_dict = expense.model_dump()
            if expense.model_extra:
                expense_dict.update(expense.model_extra)

            if orig_category not in ("Fuel", "Maintenance", "Vehicle", "Other"):
                db_category = "Other"
                custom_remarks = f"[Custom JSON]: {json.dumps(expense_dict)}"
                expense_name_val = expense.expense_name or orig_category
            else:
                db_category = orig_category
                custom_remarks = expense.remarks
                expense_name_val = expense.expense_name

            cursor.execute(sql, (
                db_category,
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
                custom_remarks,
                expense.party_type[:100] if expense.party_type else None,
                expense.party[:100] if expense.party else None,
                expense.contact[:100] if expense.contact else None,
                expense_name_val[:100] if expense_name_val else None,
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
            conn.commit()
        conn.close()
        return {"message": "Expense added successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/expenses")
def get_expenses():
    """Return all expenses, newest first, with category-filtered columns."""
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM expenses ORDER BY expense_id DESC")
        data = cursor.fetchall()
        if data and not isinstance(data[0], dict):
            columns = [col[0] for col in cursor.description]
            data = [dict(zip(columns, row)) for row in data]
        data = [filter_db_record_by_category(row) for row in data]
    conn.close()
    return data


@router.get("/expenses/{expense_id}")
def get_expense(expense_id: int):
    """Return a single expense by ID."""
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM expenses WHERE expense_id=%s", (expense_id,))
        data = cursor.fetchone()
        if data and not isinstance(data, dict):
            columns = [col[0] for col in cursor.description]
            data = dict(zip(columns, data))
        if data:
            data = filter_db_record_by_category(data)
    conn.close()
    return data


@router.delete("/expenses/{expense_id}")
def delete_expense(expense_id: int):
    """Permanently delete an expense by ID."""
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM expenses WHERE expense_id=%s", (expense_id,))
        conn.commit()
    conn.close()
    return {"message": "Deleted successfully"}


@router.get("/expenses/category/{category}")
def get_expenses_by_category(category: str):
    """Return expenses filtered by category. Handles both standard and custom categories."""
    conn = get_connection()
    with conn.cursor() as cursor:
        if category not in ("Fuel", "Maintenance", "Vehicle", "Other"):
            # Custom category is stored as 'Other' in the DB; filter by original name in remarks
            cursor.execute("SELECT * FROM expenses WHERE category = 'Other'")
            data = cursor.fetchall()
            if data and not isinstance(data[0], dict):
                columns = [col[0] for col in cursor.description]
                data = [dict(zip(columns, row)) for row in data]
            mapped_data = []
            for row in data:
                mapped_row = filter_db_record_by_category(row)
                if mapped_row.get("category") == category:
                    mapped_data.append(mapped_row)
            data = mapped_data
        elif category == "Other":
            # Only return genuine 'Other' expenses (not custom categories stored as Other)
            cursor.execute("SELECT * FROM expenses WHERE category = 'Other'")
            data = cursor.fetchall()
            if data and not isinstance(data[0], dict):
                columns = [col[0] for col in cursor.description]
                data = [dict(zip(columns, row)) for row in data]
            mapped_data = []
            for row in data:
                mapped_row = filter_db_record_by_category(row)
                if mapped_row.get("category") == "Other":
                    mapped_data.append(mapped_row)
            data = mapped_data
        else:
            cursor.execute("SELECT * FROM expenses WHERE category = %s", (category,))
            data = cursor.fetchall()
            if data and not isinstance(data[0], dict):
                columns = [col[0] for col in cursor.description]
                data = [dict(zip(columns, row)) for row in data]
            data = [filter_db_record_by_category(row) for row in data]
    conn.close()
    return data

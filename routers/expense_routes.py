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

from services.db import get_connection
from models import Expense
from services.db_service import insert_expense
from engine.validator import filter_fields_by_category

router = APIRouter()


@router.post("/expenses")
def create_expense(payload: dict):
    """Manually create a new expense record."""
    try:
        expense = Expense(payload)
        conn = get_connection()
        with conn.cursor() as cursor:
            insert_expense(cursor, expense)
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
        data = [filter_fields_by_category(row, row.get("category", "Other"), include_db_keys=True) for row in data]
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
            data = filter_fields_by_category(data, data.get("category", "Other"), include_db_keys=True)
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
                mapped_row = filter_fields_by_category(row, row.get("category", "Other"), include_db_keys=True)
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
                mapped_row = filter_fields_by_category(row, row.get("category", "Other"), include_db_keys=True)
                if mapped_row.get("category") == "Other":
                    mapped_data.append(mapped_row)
            data = mapped_data
        else:
            cursor.execute("SELECT * FROM expenses WHERE category = %s", (category,))
            data = cursor.fetchall()
            if data and not isinstance(data[0], dict):
                columns = [col[0] for col in cursor.description]
                data = [dict(zip(columns, row)) for row in data]
            data = [filter_fields_by_category(row, row.get("category", "Other"), include_db_keys=True) for row in data]
    conn.close()
    return data

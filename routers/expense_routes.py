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
from models import Expense, encode_expense_id, decode_expense_id, parse_category_from_remarks
from pipeline.stage6_db_service.stage6_db_service import insert_expense
from pipeline.stage5_filtering.stage5_filtering import filter_fields_by_category

CATEGORY_TABLE_MAP = {
    "Fuel":        ("fuel", "fuel_id"),
    "Maintenance": ("maintenance", "maintenance_id"),
    "Vehicle":     ("vehicle", "vehicle_expense_id"),
    "Other":       ("other", "other_id"),
}

router = APIRouter()


@router.post("/expenses")
def create_expense(payload: dict):
    """Manually create a new expense record."""
    try:
        expense = Expense(payload)
        with get_connection() as conn:
            with conn.cursor() as cursor:
                db_id = insert_expense(cursor, expense)
                cat = expense.category
                if cat not in ("Fuel", "Maintenance", "Vehicle", "Other"):
                    cat = "Other"
                encoded_id = encode_expense_id(db_id, cat)
            conn.commit()
        return {"message": "Expense added successfully", "expense_id": encoded_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/expenses")
def get_expenses():
    """Return all expenses, newest first, with category-filtered columns."""
    all_expenses = []

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                for category, (table_name, id_column) in CATEGORY_TABLE_MAP.items():
                    cursor.execute(f"SELECT * FROM {table_name}")
                    rows = cursor.fetchall()
                    for row in rows:
                        if category == "Other":
                            row["category"] = parse_category_from_remarks(row.get("remarks"))
                        else:
                            row["category"] = category
                        row["expense_id"] = encode_expense_id(row[id_column], category)
                        all_expenses.append(row)

        # Sort and filter
        all_expenses.sort(key=lambda row: row.get("expense_date"), reverse=True)
        filtered_data = [
            filter_fields_by_category(row, row.get("category", "Other"), include_db_keys=True)
            for row in all_expenses
        ]
        return filtered_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _get_table_and_id_col(category: str) -> tuple[str, str]:
    """Get table name and primary key column for a given category."""
    base_category = category
    if category not in CATEGORY_TABLE_MAP:
        base_category = "Other"
    return CATEGORY_TABLE_MAP.get(base_category, CATEGORY_TABLE_MAP["Other"])


def _get_expense_by_id(expense_id: int, cursor):
    """
    Fetches and processes a single expense from the database using its encoded ID.
    This is a reusable helper function.
    """
    db_id, category = decode_expense_id(expense_id)
    
    table_name, id_column = _get_table_and_id_col(category)
    sql = f"SELECT * FROM {table_name} WHERE {id_column} = %s"
    cursor.execute(sql, (db_id,))
    data = cursor.fetchone()
            
    if data:
        # For 'other' table, extract the original category from remarks
        if table_name == "other":
            data["category"] = parse_category_from_remarks(data.get("remarks"))
        else:
            data["category"] = category
        data["expense_id"] = expense_id
        return filter_fields_by_category(data, data.get("category", "Other"), include_db_keys=True)
    return None


@router.get("/expenses/{expense_id}")
def get_expense(expense_id: int):
    """Return a single expense by ID."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                expense_data = _get_expense_by_id(expense_id, cursor)
        if expense_data:
            return expense_data
        else:
            raise HTTPException(status_code=404, detail="Expense not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/expenses/{expense_id}")
def delete_expense(expense_id: int):
    """Permanently delete an expense by ID."""
    try:
        db_id, category = decode_expense_id(expense_id)
        
        table_name, id_column = _get_table_and_id_col(category)
        sql = f"DELETE FROM {table_name} WHERE {id_column} = %s"

        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (db_id,))
            conn.commit()
        return {"message": "Deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/expenses/category/{category}")
def get_expenses_by_category(category: str):
    """Return expenses filtered by category. Handles both standard and custom categories."""
    try:
        all_expenses = []
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # For standard categories, we can query the specific table
                if category in ("Fuel", "Maintenance", "Vehicle"):
                    table_name, id_column = _get_table_and_id_col(category)
                    cursor.execute(f"SELECT * FROM {table_name}")
                    rows = cursor.fetchall()
                    for row in rows:
                        row["category"] = category
                        row["expense_id"] = encode_expense_id(row[id_column], category)
                        all_expenses.append(row)
                else:
                    # For 'Other' or any custom category, we must scan the 'other' table
                    cursor.execute("SELECT * FROM other")
                    rows = cursor.fetchall()
                    id_column = CATEGORY_TABLE_MAP["Other"][1]
                    for row in rows:
                        row_cat = parse_category_from_remarks(row.get("remarks"))
                        if row_cat == category:
                            row["category"] = row_cat
                            row["expense_id"] = encode_expense_id(row[id_column], "Other")
                            all_expenses.append(row)
                            
        # Sort and filter the category matches
        all_expenses.sort(key=lambda row: row.get("expense_date"), reverse=True)
        filtered_data = [
            filter_fields_by_category(row, category, include_db_keys=True)
            for row in all_expenses
        ]
        return filtered_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

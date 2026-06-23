"""
routers/scan_routes.py — Receipt scanning endpoints (LLM Vision).

Endpoints:
    POST /scan-receipt        → Unified scanner (routes to LLM; Azure disabled)
    POST /scan-receipt-debug  → Same as /scan-receipt but does NOT save to DB
"""

import asyncio

from fastapi import APIRouter, File, HTTPException, UploadFile

from services.db_service import save_expenses_to_db
from services.scan_service import _process_single_file

router = APIRouter()


@router.post("/scan-receipt")
async def scan_receipt(files: list[UploadFile] = File(...)):
    """Unified receipt scanner — routes to LLM by default (Azure disabled on this branch)."""
    try:
        parsed_list = await asyncio.gather(*[_process_single_file(f) for f in files])
        expense_ids = save_expenses_to_db(parsed_list)
        return {
            "message":     f"{len(parsed_list)} Receipt(s) scanned and saved successfully!",
            "expense_ids": expense_ids,
            "extracted":   parsed_list,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scan-receipt-debug")
async def scan_receipt_debug(files: list[UploadFile] = File(...)):
    """Debug endpoint — runs extraction but does NOT persist to DB."""
    try:
        parsed_list = await asyncio.gather(*[_process_single_file(f) for f in files])
        return {"receipts": parsed_list}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

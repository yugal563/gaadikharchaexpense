"""
routers/scan_routes.py — Receipt scanning endpoints (LLM Vision).

Active Scanner Pipeline Orchestrator:
Coordinates the execution of Stage 1 (Validation), Stage 2 (Preprocessing), 
Stage 3 (Extraction), Stage 4 (Mapping), and Stage 5 (Validation & Filtering) 
for the receipt scanning process.

Endpoints:
    POST /scan-receipt        → Unified scanner (routes to LLM; Azure disabled)
    POST /scan-receipt-debug  → Same as /scan-receipt but does NOT save to DB
"""

import os
import asyncio
from fastapi import APIRouter, File, HTTPException, UploadFile

from pipeline.stages.stage1_validation import run_stage1
from pipeline.stages.stage2_preprocessing import run_stage2
from pipeline.stages.stage3_extraction import run_stage3
from pipeline.stages.stage4_mapping import run_stage4
from pipeline.stages.stage5_filtering import run_stage5
from services.db_service import save_expenses_to_db

router = APIRouter()

async def process_single_file(f: UploadFile, scanner_type: str = None) -> dict:
    """
    Unified file processor for a single upload file.
    Runs stage 1 (validation), stage 2 (preprocessing), stage 3 (extraction),
    stage 4 (mapping), and stage 5 (validation & category filtering).
    """
    if not scanner_type:
        scanner_type = os.getenv("SCANNER_TYPE", "llm").lower().strip()

    if scanner_type == "azure":
        raise HTTPException(
            status_code=400,
            detail="Azure Document Intelligence scanner is disabled in this branch."
        )

    # Stage 1: Validation
    image_bytes, content_type = await run_stage1(f)

    # Stage 2: Quality check / preprocessing
    preprocessed_bytes = run_stage2(image_bytes, content_type)

    # Stage 3: Extraction & Categorization
    extraction_res = await run_stage3(preprocessed_bytes, content_type)
    raw_response = extraction_res["raw_response"]
    category = extraction_res["category"]
    
    # Stage 4: Field Mapping
    mapped = run_stage4(raw_response, category)
    
    # Stage 5: Validation & Filtering
    filtered = run_stage5(mapped, category)
    
    result = filtered
    result["latency_seconds"] = extraction_res["extraction_latency"]
    result["filename"] = f.filename
    return result

async def process_receipt_files(files: list[UploadFile], save_to_db: bool = False) -> dict:
    """
    Orchestrates the receipt processing pipeline for multiple files.
    """
    parsed_list = await asyncio.gather(*[process_single_file(f) for f in files])
    
    if save_to_db:
        expense_ids = save_expenses_to_db(parsed_list)
        return {
            "message": f"{len(parsed_list)} Receipt(s) scanned and saved successfully!",
            "expense_ids": expense_ids,
            "expense_id": expense_ids[0] if expense_ids else None,
            "extracted": parsed_list[0] if parsed_list else None,
            "all_extracted": parsed_list,
        }
    else:
        return {"receipts": parsed_list}

async def _process_and_save_receipts(files: list[UploadFile], save_to_db: bool = False):
    """Helper to process files and optionally save them to the database."""
    try:
        return await process_receipt_files(files, save_to_db=save_to_db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scan-receipt")
async def scan_receipt(files: list[UploadFile] = File(...)):
    """Unified receipt scanner — routes to LLM by default (Azure disabled on this branch)."""
    return await _process_and_save_receipts(files, save_to_db=True)

@router.post("/scan-receipt-debug")
async def scan_receipt_debug(files: list[UploadFile] = File(...)):
    """Debug endpoint — runs extraction but does NOT persist to DB."""
    return await _process_and_save_receipts(files, save_to_db=False)


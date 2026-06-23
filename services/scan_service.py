"""
services/scan_service.py — File validation and scan orchestration helpers.

Provides:
    - _read_and_validate_file()     — Validate uploaded file type and read bytes
    - _process_single_file_llm()    — Run LLM Vision extraction on one file
    - _process_single_file()        — Unified dispatcher (LLM-only on this branch)
"""

from fastapi import HTTPException, UploadFile

from services.image_utils import (
    normalize_content_type,
    convert_to_jpeg_if_needed,
    run_image_quality_check,
)


async def _read_and_validate_file(f: UploadFile) -> tuple[bytes, str]:
    """Validate uploaded file MIME type and return (image_bytes, content_type)."""
    content_type = normalize_content_type(f)
    allowed = {"image/jpeg", "image/png", "image/bmp", "image/tiff", "image/webp", "application/pdf"}
    if content_type not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported file type for {f.filename}.")
    image_bytes = await f.read()
    image_bytes = convert_to_jpeg_if_needed(image_bytes, content_type)
    return image_bytes, content_type


async def _process_single_file_llm(f: UploadFile) -> dict:
    """Preprocess one uploaded file and run the LLM Vision extraction pipeline."""
    image_bytes, content_type = await _read_and_validate_file(f)
    image_bytes = run_image_quality_check(image_bytes, content_type)
    from utils_llm_pipeline import process_llm_extraction
    res = await process_llm_extraction(image_bytes, content_type)
    result = res["result"]
    result["latency_seconds"] = res["latency_seconds"]
    return result


async def _process_single_file(f: UploadFile, scanner_type: str = None) -> dict:
    """
    Unified file processor. Only LLM scanning is supported on this branch.
    Raises HTTP 400 if SCANNER_TYPE=azure is requested.
    """
    import os
    if not scanner_type:
        scanner_type = os.getenv("SCANNER_TYPE", "llm").lower().strip()

    if scanner_type == "azure":
        raise HTTPException(
            status_code=400,
            detail="Azure Document Intelligence scanner is disabled in this branch."
        )
    return await _process_single_file_llm(f)

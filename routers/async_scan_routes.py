"""
routers/async_scan_routes.py — Async receipt scan routes using Azure Service Bus.

POST /scan-receipt-async
    Accepts an image file, uploads it to Azure Blob Storage, and enqueues
    a job to the receipt-stage1 queue. Returns {job_id} immediately.
    The full pipeline (Stages 1–6) runs asynchronously via Azure Functions.

GET /job-status/{job_id}
    Returns the current processing status of an async scan job.
    Status is stored in an in-memory dict (replace with Redis for production).
"""

import uuid
import os
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from services.blob_service import upload_image
from services.queue_service import enqueue_stage1
from pipeline.stages.stage1_validation import normalize_content_type

router = APIRouter()

# ─────────────────────────────────────────────────────────
#  In-memory job status store (replace with Redis / DB in prod)
# ─────────────────────────────────────────────────────────
_JOB_STATUS: dict[str, dict] = {}

_SUPPORTED_MIME = {
    "image/jpeg", "image/png", "image/bmp",
    "image/tiff", "image/webp", "application/pdf",
}


# ─────────────────────────────────────────────────────────
#  Helper: update job status (also callable by webhook / worker)
# ─────────────────────────────────────────────────────────
def update_job_status(job_id: str, status: str, detail: Optional[str] = None) -> None:
    """Update the status of a scan job. Called externally by Azure Function callbacks."""
    entry = _JOB_STATUS.get(job_id, {})
    entry["status"] = status
    if detail:
        entry["detail"] = detail
    _JOB_STATUS[job_id] = entry


# ─────────────────────────────────────────────────────────
#  POST /scan-receipt-async
# ─────────────────────────────────────────────────────────
@router.post("/scan-receipt-async")
async def scan_receipt_async(file: UploadFile = File(...)):
    """
    Fire-and-forget async scan.

    1. Reads and validates the uploaded file (content-type check only).
    2. Uploads raw bytes to Azure Blob Storage.
    3. Enqueues a message to the receipt-stage1 Azure Service Bus queue.
    4. Returns {job_id} immediately — no waiting for LLM/DB.

    The Azure Function chain (Stage 1 → 6) picks up the message and processes
    it asynchronously, ultimately writing the expense to MySQL.
    """
    # ── Step 1: Content-type validation ─────────────────
    content_type = normalize_content_type(file)
    if content_type not in _SUPPORTED_MIME:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{content_type}' for file '{file.filename}'. "
                   f"Supported types: {', '.join(_SUPPORTED_MIME)}",
        )

    # ── Step 2: Read bytes ──────────────────────────────
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # ── Step 3: Generate job ID & upload to Blob Storage ─
    job_id = str(uuid.uuid4())
    blob_name = f"original{_ext_for(content_type)}"

    try:
        blob_url = upload_image(job_id, image_bytes, content_type, blob_name)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload image to Azure Blob Storage: {e}",
        )

    # ── Step 4: Enqueue to Stage 1 queue ────────────────
    try:
        enqueue_stage1(
            job_id=job_id,
            blob_url=blob_url,
            filename=file.filename or blob_name,
            content_type=content_type,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to enqueue scan job to Azure Service Bus: {e}",
        )

    # ── Step 5: Record initial status & return ───────────
    _JOB_STATUS[job_id] = {
        "status": "queued",
        "stage": 0,
        "filename": file.filename,
        "blob_url": blob_url,
    }

    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "status": "queued",
            "message": (
                f"Receipt '{file.filename}' accepted for async processing. "
                f"Track status at GET /job-status/{job_id}"
            ),
        },
    )


# ─────────────────────────────────────────────────────────
#  GET /job-status/{job_id}
# ─────────────────────────────────────────────────────────
@router.get("/job-status/{job_id}")
async def get_job_status(job_id: str):
    """
    Return the current async pipeline status for the given job_id.

    Possible statuses:
        queued      — Message enqueued, waiting for Stage 1 to pick up
        stage_1     — Stage 1 (Validation) in progress
        stage_2     — Stage 2 (Preprocessing) in progress
        stage_3     — Stage 3 (LLM Extraction) in progress
        stage_4     — Stage 4 (Field Mapping) in progress
        stage_5     — Stage 5 (Filtering) in progress
        stage_6     — Stage 6 (DB Persist) in progress
        done        — All stages complete, expense saved to MySQL
        failed      — One stage failed (see 'detail' for reason)
    """
    job = _JOB_STATUS.get(job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' not found. It may have expired or the job_id is incorrect.",
        )
    return job


# ─────────────────────────────────────────────────────────
#  POST /job-status/{job_id} — called by Azure Function callbacks
# ─────────────────────────────────────────────────────────
@router.post("/job-status/{job_id}")
async def update_job_status_endpoint(job_id: str, body: dict):
    """
    Internal callback endpoint.
    Azure Functions POST here to update job stage/status.

    Expected body: {"status": "stage_3", "detail": "optional message"}
    """
    status = body.get("status")
    detail = body.get("detail")
    if not status:
        raise HTTPException(status_code=400, detail="'status' is required in request body.")
    update_job_status(job_id, status, detail)
    return {"ok": True, "job_id": job_id, "status": status}


# ─────────────────────────────────────────────────────────
#  Private helpers
# ─────────────────────────────────────────────────────────
def _ext_for(content_type: str) -> str:
    """Return file extension for a given MIME type."""
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/bmp": ".bmp",
        "image/tiff": ".tiff",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
    }.get(content_type, ".jpg")

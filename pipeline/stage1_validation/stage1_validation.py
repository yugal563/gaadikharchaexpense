import io
import json
import os
import logging
import azure.functions as func
import httpx
import pymysql
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.storage.blob import BlobServiceClient, ContentSettings
from PIL import Image

_SUPPORTED_MIME = {"image/jpeg", "image/png", "image/bmp", "image/tiff", "image/webp", "application/pdf"}

def normalize_content_type(file) -> str:
    """Normalize file content type based on its filename extension if possible."""
    content_type = getattr(file, "content_type", None)
    filename = getattr(file, "filename", None)
    if filename:
        fn = filename.lower()
        if fn.endswith(".pdf"):
            return "application/pdf"
        elif fn.endswith(".png"):
            return "image/png"
        elif fn.endswith((".jpg", ".jpeg")):
            return "image/jpeg"
        elif fn.endswith(".bmp"):
            return "image/bmp"
        elif fn.endswith((".tif", ".tiff")):
            return "image/tiff"
        elif fn.endswith(".webp"):
            return "image/webp"
    return content_type or "image/jpeg"

def convert_to_jpeg_if_needed(image_bytes: bytes, content_type: str) -> bytes:
    """Convert unsupported image formats to JPEG."""
    if content_type in _SUPPORTED_MIME:
        return image_bytes
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()

async def run_stage1(f) -> tuple[bytes, str]:
    """Validate uploaded file MIME type and return (image_bytes, content_type)."""
    content_type = normalize_content_type(f)
    if content_type not in _SUPPORTED_MIME:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Unsupported file type for {f.filename}.")
    image_bytes = await f.read()
    image_bytes = convert_to_jpeg_if_needed(image_bytes, content_type)
    return image_bytes, content_type


app = func.FunctionApp()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────
def _get_db_conn():
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", 3306)),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", "1234"),
        database=os.environ.get("DB_NAME", "expenses"),
        cursorclass=pymysql.cursors.DictCursor
    )

def _update_stage_tracking(job_id: str, filename: str = None, status: str = None, 
                           current_stage: str = None, original_url: str = None, 
                           preprocessed_url: str = None, category: str = None, 
                           expense_row_id: int = None, error_message: str = None, 
                           completed_stage_num: int = None):
    try:
        conn = _get_db_conn()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM stage_tracking WHERE job_id = %s", (job_id,))
                exists = cursor.fetchone()
                
                if not exists:
                    sql = """
                    INSERT INTO stage_tracking (job_id, filename, status, current_stage, original_url)
                    VALUES (%s, %s, %s, %s, %s)
                    """
                    cursor.execute(sql, (job_id, filename or "unknown", status or "queued", 
                                         current_stage or "stage1_validate", original_url))
                else:
                    updates = []
                    params = []
                    
                    if status:
                        updates.append("status = %s")
                        params.append(status)
                    if current_stage:
                        updates.append("current_stage = %s")
                        params.append(current_stage)
                    if original_url:
                        updates.append("original_url = %s")
                        params.append(original_url)
                    if preprocessed_url:
                        updates.append("preprocessed_url = %s")
                        params.append(preprocessed_url)
                    if category:
                        updates.append("category = %s")
                        params.append(category)
                    if expense_row_id is not None:
                        updates.append("expense_row_id = %s")
                        params.append(expense_row_id)
                    if error_message:
                        updates.append("error_message = %s")
                        params.append(error_message)
                    if completed_stage_num:
                        updates.append(f"stage{completed_stage_num}_completed_at = CURRENT_TIMESTAMP")
                        
                    if updates:
                        sql = f"UPDATE stage_tracking SET {', '.join(updates)} WHERE job_id = %s"
                        params.append(job_id)
                        cursor.execute(sql, tuple(params))
            conn.commit()
    except Exception as e:
        logger.error(f"[Tracking Error] Failed to update stage_tracking for job {job_id}: {e}")

def _send_callback(job_id: str, status: str, detail: str = None):
    base_url = os.environ.get("FASTAPI_BASE_URL", "http://localhost:8000")
    url = f"{base_url}/job-status/{job_id}"
    payload = {"status": status}
    if detail:
        payload["detail"] = detail
    try:
        httpx.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"[Callback Error] Failed to send status to {url}: {e}")

def _forward_to_next_stage(stage_num: int, payload: dict):
    conn_str = os.environ.get("AZURE_SERVICEBUS_CONNECTION_STRING")
    queue_name = os.environ.get(f"AZURE_QUEUE_STAGE{stage_num}", f"receipt-stage{stage_num}")
    client = ServiceBusClient.from_connection_string(conn_str)
    with client:
        with client.get_queue_sender(queue_name) as sender:
            msg = ServiceBusMessage(json.dumps(payload, default=str))
            sender.send_messages(msg)

def _download_blob(blob_url: str) -> bytes:
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    client = BlobServiceClient.from_connection_string(conn_str)
    
    parts = blob_url.split(".blob.core.windows.net/")
    if len(parts) < 2:
        raise ValueError(f"Invalid blob URL: {blob_url}")
    rest = parts[1]
    container, _, blob_path = rest.partition("/")
    blob_c = client.get_blob_client(container=container, blob=blob_path)
    return blob_c.download_blob().readall()

def _upload_blob(job_id: str, blob_name: str, data: bytes, content_type: str, container: str) -> str:
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    client = BlobServiceClient.from_connection_string(conn_str)
    cc = client.get_container_client(container)
    try:
        cc.create_container()
    except Exception:
        pass
    blob_path = f"{job_id}/{blob_name}"
    bc = cc.get_blob_client(blob_path)
    bc.upload_blob(data, overwrite=True, content_settings=ContentSettings(content_type=content_type))
    return bc.url


# ─────────────────────────────────────────────────────────
#  Service Bus Queue Trigger
# ─────────────────────────────────────────────────────────
@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="%AZURE_QUEUE_STAGE1%",
    connection="ServiceBusConnection"
)
def stage1_validate(msg: func.ServiceBusMessage):
    body = msg.get_body().decode('utf-8')
    try:
        payload = json.loads(body)
    except Exception as e:
        logger.error(f"[Stage1] Failed to parse message body JSON: {e}")
        return

    job_id = payload.get("job_id")
    blob_url = payload.get("blob_url")
    filename = payload.get("filename")
    content_type = payload.get("content_type")

    if not job_id or not blob_url:
        logger.error(f"[Stage1] Missing job_id or blob_url in payload: {payload}")
        return

    logger.info(f"[Stage1] Starting validation for job={job_id}")

    try:
        # 1. Update status to stage_1 (processing)
        _update_stage_tracking(
            job_id=job_id,
            filename=filename,
            status="stage_1",
            current_stage="stage1_validate",
            original_url=blob_url
        )
        _send_callback(job_id, "stage_1")

        # 2. Download original image bytes
        image_bytes = _download_blob(blob_url)

        # 3. Clean filename and normalize content type
        class MockFile:
            def __init__(self, filename, content_type):
                self.filename = filename
                self.content_type = content_type
        mock_file = MockFile(filename, content_type)
        norm_type = normalize_content_type(mock_file)

        # 4. Convert format if needed
        processed_bytes = convert_to_jpeg_if_needed(image_bytes, norm_type)
        norm_type = "image/jpeg" if norm_type != "application/pdf" else norm_type
        ext = ".jpg" if norm_type == "image/jpeg" else ".pdf"

        # 5. Upload processed image to stage 1 container
        container_name = os.environ.get("AZURE_STORAGE_CONTAINER", "receipt-stage1")
        new_blob_url = _upload_blob(job_id, f"stage1{ext}", processed_bytes, norm_type, container_name)

        # 6. Update tracking database
        _update_stage_tracking(job_id=job_id, completed_stage_num=1)

        # 7. Forward to Stage 2
        next_payload = {
            "job_id": job_id,
            "blob_url": new_blob_url,
            "filename": filename,
            "content_type": norm_type
        }
        _forward_to_next_stage(2, next_payload)
        _send_callback(job_id, "stage_2")
        logger.info(f"[Stage1] Completed successfully for job={job_id}")

    except Exception as e:
        error_msg = f"Stage 1 failed: {str(e)}"
        logger.error(f"[Stage1] {error_msg}")
        _update_stage_tracking(job_id=job_id, status="failed", error_message=error_msg)
        _send_callback(job_id, "failed", error_msg)

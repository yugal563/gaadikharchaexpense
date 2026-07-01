import json
import os
import logging
import cv2
import numpy as np
import azure.functions as func
import httpx
import pymysql
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.storage.blob import BlobServiceClient, ContentSettings

def run_stage2(image_bytes: bytes, content_type: str) -> bytes:
    """
    Preprocess the image bytes:
    1. Decode the image.
    2. Resize if the maximum dimension exceeds 1600 pixels.
    3. Re-encode as JPEG with quality 85 to reduce network payload.
    """
    if content_type == "application/pdf":
        return image_bytes

    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return image_bytes

        # Downscale large images to speed up preprocessing and reduce network payload
        max_dim = 1600
        h, w = img.shape[:2]
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

        # Encode back to JPEG with quality 85
        success, encoded_img = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if success:
            return encoded_img.tobytes()
    except Exception as e:
        print(f"[Pipeline] Preprocessing error: {e}. Returning original bytes.")

    return image_bytes


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
                                         current_stage or "stage2_preprocess", original_url))
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
    queue_name="%AZURE_QUEUE_STAGE2%",
    connection="ServiceBusConnection"
)
def stage2_preprocess(msg: func.ServiceBusMessage):
    body = msg.get_body().decode('utf-8')
    try:
        payload = json.loads(body)
    except Exception as e:
        logger.error(f"[Stage2] Failed to parse message body JSON: {e}")
        return

    job_id = payload.get("job_id")
    blob_url = payload.get("blob_url")
    filename = payload.get("filename")
    content_type = payload.get("content_type")

    if not job_id or not blob_url:
        logger.error(f"[Stage2] Missing job_id or blob_url in payload: {payload}")
        return

    logger.info(f"[Stage2] Starting preprocessing for job={job_id}")

    try:
        # 1. Update status to stage_2
        _update_stage_tracking(
            job_id=job_id,
            status="stage_2",
            current_stage="stage2_preprocess"
        )
        _send_callback(job_id, "stage_2")

        # 2. Download output of stage 1
        image_bytes = _download_blob(blob_url)

        # 3. Process image (downscaling/compression)
        preprocessed_bytes = run_stage2(image_bytes, content_type)
        ext = ".jpg" if content_type == "image/jpeg" else ".pdf"

        # 4. Upload preprocessed image
        container_name = os.environ.get("AZURE_STORAGE_CONTAINER", "receipt-stage2")
        new_blob_url = _upload_blob(job_id, f"stage2{ext}", preprocessed_bytes, content_type, container_name)

        # 5. Update tracking
        _update_stage_tracking(
            job_id=job_id,
            preprocessed_url=new_blob_url,
            completed_stage_num=2
        )

        # 6. Forward to Stage 3
        next_payload = {
            "job_id": job_id,
            "blob_url": new_blob_url,
            "filename": filename,
            "content_type": content_type
        }
        _forward_to_next_stage(3, next_payload)
        _send_callback(job_id, "stage_3")
        logger.info(f"[Stage2] Completed successfully for job={job_id}")

    except Exception as e:
        error_msg = f"Stage 2 failed: {str(e)}"
        logger.error(f"[Stage2] {error_msg}")
        _update_stage_tracking(job_id=job_id, status="failed", error_message=error_msg)
        _send_callback(job_id, "failed", error_msg)

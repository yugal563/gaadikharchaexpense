import io
import json
import logging

import azure.functions as func
from PIL import Image

from services.blob_service import download_blob, upload_stage_artifact
from services.queue_service import forward_to_stage
from services.stage_tracking import update_stage_tracking

_SUPPORTED_MIME = {
    "image/jpeg", "image/png", "image/bmp", "image/tiff", "image/webp", "application/pdf"
}


def normalize_content_type(filename: str, content_type: str = None) -> str:
    if filename:
        fn = filename.lower()
        if fn.endswith(".pdf"):
            return "application/pdf"
        if fn.endswith(".png"):
            return "image/png"
        if fn.endswith((".jpg", ".jpeg")):
            return "image/jpeg"
        if fn.endswith(".bmp"):
            return "image/bmp"
        if fn.endswith((".tif", ".tiff")):
            return "image/tiff"
        if fn.endswith(".webp"):
            return "image/webp"
    return content_type or "image/jpeg"


def convert_to_jpeg_if_needed(image_bytes: bytes, content_type: str) -> bytes:
    if content_type in _SUPPORTED_MIME:
        return image_bytes
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def validate_bytes(filename: str, content_type: str, image_bytes: bytes) -> tuple[bytes, str]:
    norm_type = normalize_content_type(filename, content_type)
    if norm_type not in _SUPPORTED_MIME:
        raise ValueError(f"Unsupported file type for {filename}.")
    processed = convert_to_jpeg_if_needed(image_bytes, norm_type)
    if norm_type != "application/pdf":
        norm_type = "image/jpeg"
    return processed, norm_type


app = func.FunctionApp()
logger = logging.getLogger(__name__)


@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="%AZURE_QUEUE_STAGE1%",
    connection="ServiceBusConnection",
)
def stage1_validate(msg: func.ServiceBusMessage):
    body = msg.get_body().decode("utf-8")
    try:
        payload = json.loads(body)
    except Exception as e:
        logger.error("[Stage1] Failed to parse message body JSON: %s", e)
        return

    job_id = payload.get("job_id")
    blob_url = payload.get("blob_url")
    filename = payload.get("filename")
    content_type = payload.get("content_type")

    if not job_id or not blob_url:
        logger.error("[Stage1] Missing job_id or blob_url in payload: %s", payload)
        return

    logger.info("[Stage1] Starting validation for job=%s", job_id)

    try:
        update_stage_tracking(
            job_id=job_id,
            filename=filename,
            status="stage_1",
            current_stage="stage1_validate",
            original_url=blob_url,
            default_current_stage="stage1_validate",
        )

        image_bytes = download_blob(blob_url)
        processed_bytes, norm_type = validate_bytes(filename, content_type, image_bytes)
        ext = ".pdf" if norm_type == "application/pdf" else ".jpg"

        artifact_url = upload_stage_artifact(
            job_id, 1, processed_bytes, f"validated{ext}", norm_type
        )

        update_stage_tracking(job_id=job_id, completed_stage_num=1)

        forward_to_stage(
            2,
            {
                "job_id": job_id,
                "blob_url": artifact_url,
                "filename": filename,
                "content_type": norm_type,
            },
        )
        logger.info("[Stage1] Completed successfully for job=%s", job_id)

    except Exception as e:
        error_msg = f"Stage 1 failed: {str(e)}"
        logger.error("[Stage1] %s", error_msg)
        update_stage_tracking(job_id=job_id, status="failed", error_message=error_msg)

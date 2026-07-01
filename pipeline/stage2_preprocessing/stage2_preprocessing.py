import json
import logging

import azure.functions as func
import cv2
import numpy as np

from services.blob_service import download_blob, upload_stage_artifact
from services.queue_service import forward_to_stage
from services.stage_tracking import update_stage_tracking


def run_stage2(image_bytes: bytes, content_type: str) -> bytes:
    if content_type == "application/pdf":
        return image_bytes

    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return image_bytes

        max_dim = 1600
        h, w = img.shape[:2]
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

        success, encoded_img = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if success:
            return encoded_img.tobytes()
    except Exception as e:
        print(f"[Pipeline] Preprocessing error: {e}. Returning original bytes.")

    return image_bytes


app = func.FunctionApp()
logger = logging.getLogger(__name__)


@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="%AZURE_QUEUE_STAGE2%",
    connection="ServiceBusConnection",
)
def stage2_preprocess(msg: func.ServiceBusMessage):
    body = msg.get_body().decode("utf-8")
    try:
        payload = json.loads(body)
    except Exception as e:
        logger.error("[Stage2] Failed to parse message body JSON: %s", e)
        return

    job_id = payload.get("job_id")
    blob_url = payload.get("blob_url")
    filename = payload.get("filename")
    content_type = payload.get("content_type")

    if not job_id or not blob_url:
        logger.error("[Stage2] Missing job_id or blob_url in payload: %s", payload)
        return

    logger.info("[Stage2] Starting preprocessing for job=%s", job_id)

    try:
        update_stage_tracking(
            job_id=job_id,
            status="stage_2",
            current_stage="stage2_preprocess",
            default_current_stage="stage2_preprocess",
        )

        image_bytes = download_blob(blob_url)
        preprocessed_bytes = run_stage2(image_bytes, content_type)
        ext = ".pdf" if content_type == "application/pdf" else ".jpg"

        artifact_url = upload_stage_artifact(
            job_id, 2, preprocessed_bytes, f"preprocessed{ext}", content_type
        )

        update_stage_tracking(
            job_id=job_id,
            preprocessed_url=artifact_url,
            completed_stage_num=2,
        )

        forward_to_stage(
            3,
            {
                "job_id": job_id,
                "blob_url": artifact_url,
                "filename": filename,
                "content_type": content_type,
            },
        )
        logger.info("[Stage2] Completed successfully for job=%s", job_id)

    except Exception as e:
        error_msg = f"Stage 2 failed: {str(e)}"
        logger.error("[Stage2] %s", error_msg)
        update_stage_tracking(job_id=job_id, status="failed", error_message=error_msg)

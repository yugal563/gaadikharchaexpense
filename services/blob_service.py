"""
services/blob_service.py — Azure Blob Storage wrapper for the receipt pipeline.

Each stage writes artifacts to its own container: receipt-stage{N}
"""

import json
import os

from azure.storage.blob import BlobServiceClient, ContentSettings


def _get_blob_client():
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING is not set in environment.")
    return BlobServiceClient.from_connection_string(conn_str)


def container_for_stage(stage_num: int) -> str:
    override = os.getenv(f"AZURE_STORAGE_CONTAINER_STAGE{stage_num}")
    if override:
        return override
    default = os.getenv("AZURE_STORAGE_CONTAINER")
    if default and stage_num == int(os.getenv("STAGE_NUMBER", "0") or "0"):
        return default
    return f"receipt-stage{stage_num}"


def upload_stage_artifact(
    job_id: str,
    stage_num: int,
    data: bytes,
    blob_name: str,
    content_type: str,
) -> str:
    container = container_for_stage(stage_num)
    blob_path = f"{job_id}/{blob_name}"

    client = _get_blob_client()
    container_client = client.get_container_client(container)
    try:
        container_client.create_container()
    except Exception:
        pass

    blob_client = container_client.get_blob_client(blob_path)
    blob_client.upload_blob(
        data,
        overwrite=True,
        content_settings=ContentSettings(content_type=content_type),
    )
    return blob_client.url


def upload_json_artifact(job_id: str, stage_num: int, blob_name: str, payload: dict) -> str:
    return upload_stage_artifact(
        job_id,
        stage_num,
        json.dumps(payload, default=str).encode("utf-8"),
        blob_name,
        "application/json",
    )


def download_blob(blob_url: str) -> bytes:
    client = _get_blob_client()
    parts = blob_url.split(".blob.core.windows.net/")
    if len(parts) < 2:
        raise ValueError(f"Invalid blob URL: {blob_url}")
    rest = parts[1]
    container, _, blob_path = rest.partition("/")
    blob_client = client.get_blob_client(container=container, blob=blob_path)
    return blob_client.download_blob().readall()


def download_json_artifact(blob_url: str) -> dict:
    return json.loads(download_blob(blob_url).decode("utf-8"))


# Backward-compatible aliases
def upload_image(job_id: str, image_bytes: bytes, content_type: str, blob_name: str = "original.jpg") -> str:
    return upload_stage_artifact(job_id, 1, image_bytes, blob_name, content_type)


def download_image(blob_url: str) -> bytes:
    return download_blob(blob_url)

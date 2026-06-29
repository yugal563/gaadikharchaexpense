"""
services/blob_service.py — Azure Blob Storage wrapper for receipt image storage.

Used by the async pipeline to store image bytes between Azure Function stages.
Images are stored under: receipt-images/{job_id}/{blob_name}
"""

import os
import uuid
from azure.storage.blob import BlobServiceClient, ContentSettings


def _get_blob_client():
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING is not set in environment.")
    return BlobServiceClient.from_connection_string(conn_str)


def upload_image(
    job_id: str,
    image_bytes: bytes,
    content_type: str,
    blob_name: str = "original.jpg",
) -> str:
    """
    Upload image bytes to Azure Blob Storage.
    Returns the full blob URL.
    """
    container = os.getenv("AZURE_STORAGE_CONTAINER", "receipt-images")
    blob_path = f"{job_id}/{blob_name}"

    client = _get_blob_client()
    container_client = client.get_container_client(container)

    # Create container if it doesn't exist (idempotent)
    try:
        container_client.create_container()
    except Exception:
        pass  # Already exists

    blob_client = container_client.get_blob_client(blob_path)
    blob_client.upload_blob(
        image_bytes,
        overwrite=True,
        content_settings=ContentSettings(content_type=content_type),
    )

    return blob_client.url


def download_image(blob_url: str) -> bytes:
    """
    Download image bytes from a blob URL.
    The URL must be within the configured storage account.
    """
    client = _get_blob_client()
    # Parse container and blob path from the URL
    # URL format: https://<account>.blob.core.windows.net/<container>/<blob_path>
    parts = blob_url.split(".blob.core.windows.net/")
    if len(parts) < 2:
        raise ValueError(f"Invalid blob URL: {blob_url}")
    rest = parts[1]
    container, _, blob_path = rest.partition("/")
    blob_client = client.get_blob_client(container=container, blob=blob_path)
    return blob_client.download_blob().readall()


def delete_job_blobs(job_id: str) -> None:
    """Delete all blobs for a given job_id (cleanup after processing)."""
    container = os.getenv("AZURE_STORAGE_CONTAINER", "receipt-images")
    client = _get_blob_client()
    container_client = client.get_container_client(container)
    blobs = container_client.list_blobs(name_starts_with=f"{job_id}/")
    for blob in blobs:
        container_client.delete_blob(blob.name)

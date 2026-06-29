"""
services/queue_service.py — Azure Service Bus wrapper for the async receipt pipeline.

Used by the FastAPI app to enqueue a new scan job to the Stage 1 queue.
Azure Functions consume each queue and run the corresponding pipeline stage.

Queue name convention: receipt-stage{N}  (e.g., receipt-stage1 … receipt-stage6)
"""

import json
import os
from azure.servicebus import ServiceBusClient, ServiceBusMessage


# ─────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────

def _get_sender(queue_name: str):
    conn_str = os.getenv("AZURE_SERVICEBUS_CONNECTION_STRING")
    if not conn_str:
        raise RuntimeError("AZURE_SERVICEBUS_CONNECTION_STRING is not set in environment.")
    client = ServiceBusClient.from_connection_string(conn_str)
    return client, client.get_queue_sender(queue_name=queue_name)


def _send_message(queue_name: str, payload: dict) -> None:
    """Serialize payload as JSON and send to the given Service Bus queue."""
    client, sender = _get_sender(queue_name)
    with client:
        with sender:
            msg = ServiceBusMessage(json.dumps(payload, default=str))
            sender.send_messages(msg)


# ─────────────────────────────────────────────────────────
#  Public API — called by FastAPI to kick off async pipeline
# ─────────────────────────────────────────────────────────

def enqueue_stage1(
    job_id: str,
    blob_url: str,
    filename: str,
    content_type: str,
) -> None:
    """
    Enqueue a new scan job to the receipt-stage1 queue.
    This is the entry point of the async Azure Function stage chain.

    Message schema:
        {
            "job_id": str,
            "blob_url": str,         # Azure Blob URL of the uploaded image
            "filename": str,
            "content_type": str,
        }
    """
    payload = {
        "job_id": job_id,
        "blob_url": blob_url,
        "filename": filename,
        "content_type": content_type,
    }
    queue_name = os.getenv("AZURE_QUEUE_STAGE1", "receipt-stage1")
    _send_message(queue_name, payload)
    print(f"[QueueService] Enqueued job {job_id} → {queue_name}")


# ─────────────────────────────────────────────────────────
#  Helpers re-used by Azure Functions to forward messages
# ─────────────────────────────────────────────────────────

def forward_to_stage(stage_number: int, payload: dict) -> None:
    """
    Forward a message to the next stage's queue.
    Called internally by Azure Functions at the end of each stage.
    """
    queue_name = os.getenv(
        f"AZURE_QUEUE_STAGE{stage_number}", f"receipt-stage{stage_number}"
    )
    _send_message(queue_name, payload)
    print(f"[QueueService] Forwarded job {payload.get('job_id')} → {queue_name}")

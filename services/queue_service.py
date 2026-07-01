"""
services/queue_service.py — Azure Service Bus wrapper for the receipt pipeline.

Queue name convention: receipt-stage{N}
"""

import json
import os

from azure.servicebus import ServiceBusClient, ServiceBusMessage


def _get_sender(queue_name: str):
    conn_str = os.getenv("AZURE_SERVICEBUS_CONNECTION_STRING")
    if not conn_str:
        raise RuntimeError("AZURE_SERVICEBUS_CONNECTION_STRING is not set in environment.")
    client = ServiceBusClient.from_connection_string(conn_str)
    return client, client.get_queue_sender(queue_name=queue_name)


def _send_message(queue_name: str, payload: dict) -> None:
    client, sender = _get_sender(queue_name)
    with client:
        with sender:
            msg = ServiceBusMessage(json.dumps(payload, default=str))
            sender.send_messages(msg)


def forward_to_stage(stage_number: int, payload: dict) -> None:
    queue_name = os.getenv(
        f"AZURE_QUEUE_STAGE{stage_number}", f"receipt-stage{stage_number}"
    )
    _send_message(queue_name, payload)
    print(f"[QueueService] Forwarded job {payload.get('job_id')} -> {queue_name}")

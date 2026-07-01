#!/usr/bin/env python3
"""Upload a receipt to blob storage and enqueue stage 1 for pipeline testing."""

import argparse
import mimetypes
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from services.blob_service import upload_stage_artifact
from services.queue_service import forward_to_stage


def main():
    parser = argparse.ArgumentParser(description="Enqueue a receipt for async pipeline processing")
    parser.add_argument("file", type=Path, help="Path to receipt PDF or image")
    args = parser.parse_args()

    path = args.file.expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"File not found: {path}")

    job_id = str(uuid.uuid4())
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    ext = path.suffix or ".bin"
    data = path.read_bytes()

    blob_url = upload_stage_artifact(job_id, 1, data, f"original{ext}", content_type)

    forward_to_stage(
        1,
        {
            "job_id": job_id,
            "blob_url": blob_url,
            "filename": path.name,
            "content_type": content_type,
        },
    )

    print(f"job_id:    {job_id}")
    print(f"blob_url:  {blob_url}")
    print(f"queue:     receipt-stage1")
    print("Track status in MySQL stage_tracking table.")


if __name__ == "__main__":
    main()

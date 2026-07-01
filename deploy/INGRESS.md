# Pipeline Ingress Contract

External systems start a receipt job by:

1. Uploading the original file to blob container **`receipt-stage1`**
2. Sending a JSON message to Service Bus queue **`receipt-stage1`**

## Blob upload

- **Container:** `receipt-stage1`
- **Path:** `{job_id}/original.{ext}` (e.g. `a1b2c3.../original.pdf`)
- **Storage account:** `gkexpensedevstorage`

## Queue message (receipt-stage1)

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "blob_url": "https://gkexpensedevstorage.blob.core.windows.net/receipt-stage1/550e8400-e29b-41d4-a716-446655440000/original.pdf",
  "filename": "invoice.pdf",
  "content_type": "application/pdf"
}
```

## Pipeline flow

| Stage | Queue trigger | Output container | Artifact |
|-------|---------------|------------------|----------|
| 1 | receipt-stage1 | receipt-stage1 | `{job_id}/validated.{ext}` |
| 2 | receipt-stage2 | receipt-stage2 | `{job_id}/preprocessed.{ext}` |
| 3 | receipt-stage3 | receipt-stage3 | `{job_id}/extraction.json` |
| 4 | receipt-stage4 | receipt-stage4 | `{job_id}/mapped.json` |
| 5 | receipt-stage5 | receipt-stage5 | `{job_id}/filtered.json` |
| 6 | receipt-stage6 | receipt-stage6 | `{job_id}/result.json` |

Stages 3–6 pass **`artifact_url`** (blob URL) in queue messages instead of large JSON payloads.

## Job status

Query the MySQL `stage_tracking` table by `job_id`:

- `status`: `stage_1` … `stage_6`, `done`, or `failed`
- `error_message`: failure reason if `failed`
- `expense_row_id`: populated when stage 6 completes

## Manual test

```bash
python deploy/test-enqueue.py /path/to/receipt.pdf
```

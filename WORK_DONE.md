# Work Done — Expense OCR Pipeline Restructure

Summary of changes made to turn the project into a **queue-only Azure Functions pipeline** with local Docker dev, Cloudflare tunnel for status, and shared services.

---

## 1. Removed FastAPI / frontend

Deleted the HTTP API layer so the app is **queue-driven only**:

| Removed | Purpose |
|---------|---------|
| `main.py` | FastAPI entrypoint |
| `routers/` | HTTP routes (upload, status, etc.) |
| `static/` | React frontend (`index.html`, `app.jsx`) |
| Root `requirements.txt` | FastAPI deps |

**Ingress now:** upload blob → enqueue `receipt-stage1` (see `deploy/INGRESS.md`).

---

## 2. Shared services (`services/`)

| File | What it does |
|------|----------------|
| `db.py` | MySQL via env (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`; default `127.0.0.1:3307`) |
| `stage_tracking.py` | Single `update_stage_tracking()` for all stages |
| `blob_service.py` | Per-stage containers (`receipt-stage{N}`), upload/download artifacts |
| `queue_service.py` | `forward_to_stage()` only |
| `llm_providers.py` | Azure AI Foundry env fallbacks (`AZURE_AI_FOUNDRY_*`) |

Schemas moved to `pipeline/schemas.py` (from stage3).

---

## 3. Six pipeline stages refactored

Each stage is an Azure Function triggered by Service Bus. All use shared services and write artifacts to their own blob container.

| Stage | Queue | Blob artifact |
|-------|-------|---------------|
| 1 Validation | `receipt-stage1` | `{job_id}/validated.{ext}` |
| 2 Preprocessing | `receipt-stage2` | `{job_id}/preprocessed.{ext}` |
| 3 Extraction (LLM) | `receipt-stage3` | `{job_id}/extraction.json` |
| 4 Mapping | `receipt-stage4` | `{job_id}/mapped.json` |
| 5 Filtering | `receipt-stage5` | `{job_id}/filtered.json` |
| 6 DB persist | `receipt-stage6` | `{job_id}/result.json` + MySQL insert |

Removed per-stage `_send_callback()` and duplicated DB/blob helpers. Stages 3–6 pass `artifact_url` in queue messages instead of large JSON payloads.

---

## 4. Docker images (6 stages)

- Base image: `mcr.microsoft.com/azure-functions/python:4-python3.11`
- Each Dockerfile copies `services/` and sets `STAGE_NUMBER`
- Build script: `deploy/build-and-push.sh`
  - `BUILD_ONLY=true` — local tags `gk-expense-stage{N}:local`
  - `PLATFORM=linux/amd64` — required on Apple Silicon
- Local compose: `docker-compose.functions.yml` (6 containers → Azure SB/Blob + local MySQL on `host.docker.internal:3307`)

**Dependency fixes during local builds:**

- Stage 3: added `Pillow` (was missing `PIL`)
- Stages 4–6: added `azure-storage-blob`

---

## 5. Local dev & testing

| Script / file | Purpose |
|---------------|---------|
| `deploy/test-enqueue.py` | Upload invoice to blob + enqueue stage 1 |
| `deploy/test-full-flow.sh` | **Full E2E:** stack check → status server → Cloudflare tunnel → enqueue → poll public `/status/{job_id}` |
| `deploy/status_server.py` | Minimal HTTP API: `/health`, `/status/{job_id}` from MySQL |
| `deploy/run-local-stage.sh` | Run a single stage locally |
| `deploy/INGRESS.md` | Queue/blob contract for external systems |

### Cloudflare (temporary public URL)

| Script | Purpose |
|--------|---------|
| `deploy/cloudflare/run-temporary.sh` | MySQL + 6 containers + quick tunnel |
| `deploy/cloudflare/run-quick-tunnel.sh` | Status server + `*.trycloudflare.com` tunnel (no CF account) |
| `deploy/cloudflare/run-named-tunnel.sh` | Named tunnel (requires `cloudflared tunnel login`) |
| `deploy/cloudflare/config.yml` | Template for named tunnel |
| `deploy/cloudflare/TUNNEL_URL.txt` | Last known public URL |

Quick tunnel exposes **status API only** — not the pipeline itself. Jobs are submitted via Service Bus; status is read over HTTPS.

---

## 6. Verified locally

- **Sync Python pipeline** (no queues): success on sample invoice (Tholia Motors, Maintenance, ₹13,461.84)
- **Docker containers + Azure queues:** success (~20s end-to-end)
  - Example job: `67f56654-48b2-4b06-a692-feba6c312210` → `done`, `expense_row_id=2000004`
- **Cloudflare quick tunnel:** `/health` and `/status/{job_id}` work when status server is running

### Full flow test (one command)

```bash
# Stack already running:
./deploy/test-full-flow.sh "/path/to/invoice.pdf"

# Start MySQL + 6 containers first:
./deploy/test-full-flow.sh "/path/to/invoice.pdf" --start-stack

# Longer timeout (default 180s):
./deploy/test-full-flow.sh "/path/to/invoice.pdf" --timeout 300
```

Prerequisites: `.env` with Azure Service Bus, Blob, and LLM keys; `docker`, `cloudflared`, `python3`.

---

## 7. Azure infrastructure (partial — not fully deployed)

Existing in resource group **GK-Azure_Pocs**:

- ACR: `gkexpensedevacr.azurecr.io`
- 6 Function Apps: `gk-expense-dev-stage1` … `stage6` (still zip deploy, not Docker yet)
- Service Bus: `gkexpensedev-bus`, queues `receipt-stage1` … `receipt-stage6`
- Blob containers: `receipt-stage1` … `receipt-stage6`
- **No Azure MySQL** — local Docker MySQL only

**Not done yet:**

- Push images to ACR and switch Function Apps to container deploy (`deploy/deploy.sh`)
- Purge stuck queue messages on Azure
- Remove obsolete app settings (e.g. `FASTAPI_BASE_URL`)
- Cloud DB or TCP tunnel if Azure-hosted stage 6 must write to your MySQL

---

## 8. Required `.env` keys (local + Azure SB/Blob)

```
Endpoint=...          # Azure OpenAI / AI Foundry
Key=...
Model=gpt-4.1-mini
AZURE_SERVICEBUS_CONNECTION_STRING=...
AZURE_STORAGE_CONNECTION_STRING=...
```

---

## Quick reference

```bash
# Build local images
BUILD_ONLY=true ./deploy/build-and-push.sh

# Start stack
docker compose up -d mysql
docker compose -f docker-compose.yml -f docker-compose.functions.yml up -d

# E2E test with Cloudflare
./deploy/test-full-flow.sh "/path/to/invoice.pdf" --start-stack

# Tunnel only (status API)
./deploy/cloudflare/run-quick-tunnel.sh

# Azure deploy (when ready)
./deploy/deploy.sh
```

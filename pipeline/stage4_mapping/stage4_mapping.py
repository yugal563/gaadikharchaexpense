import json
import logging
import re
from datetime import datetime
from typing import Optional

import azure.functions as func

from pipeline.schemas import CATEGORY_SCHEMAS, get_schema_for_category
from services.blob_service import download_json_artifact, upload_json_artifact
from services.queue_service import forward_to_stage
from services.stage_tracking import update_stage_tracking


def run_stage4(raw_response: dict, category: str) -> dict:
    """Stage 4: Extract and Map Fields to standardized schema."""
    return extract_and_map_fields(raw_response, category)


def extract_and_map_fields(llm_response: dict, category: str) -> dict:
    """
    Map the LLM response fields to the database schema format.
    Ensures all fields are properly typed and formatted.
    """
    is_custom = category not in CATEGORY_SCHEMAS
    schema = get_schema_for_category(category)

    result = {}
    for field_name, field_info in schema.items():
        raw_val = llm_response.get(field_name)

        if field_name == "items" and isinstance(raw_val, list):
            descriptions = []
            for item in raw_val:
                if isinstance(item, dict) and item.get("description"):
                    desc = str(item["description"]).strip()
                    qty = item.get("quantity")
                    if qty:
                        try:
                            qty_val = int(float(qty))
                            descriptions.append(f"{desc} (x{qty_val})")
                        except (ValueError, TypeError):
                            descriptions.append(desc)
                    else:
                        descriptions.append(desc)
                elif isinstance(item, str):
                    descriptions.append(item.strip())
            raw_val = ", ".join(descriptions) if descriptions else None

        if raw_val is None or raw_val == "" or raw_val == "null":
            result[field_name] = None
            continue

        field_type = field_info["type"]

        try:
            if field_type == "string":
                result[field_name] = _clean_string(str(raw_val))
            elif field_type == "number":
                result[field_name] = _parse_number(raw_val)
            elif field_type == "integer":
                num = _parse_number(raw_val)
                result[field_name] = int(num) if num is not None else None
            else:
                result[field_name] = raw_val
        except (ValueError, TypeError):
            result[field_name] = None

    # For custom categories, copy any extra keys extracted dynamically by the LLM
    if is_custom:
        for key, val in llm_response.items():
            if key not in result and val is not None and val != "" and val != "null":
                if isinstance(val, str):
                    cleaned = _clean_string(val)
                    parsed_num = _parse_number(cleaned)
                    if parsed_num is not None and len(str(parsed_num)) == len(cleaned.replace(',', '').replace(' ', '')):
                        result[key] = parsed_num
                    else:
                        result[key] = cleaned
                else:
                    result[key] = val

    # Ensure required fields have defaults
    result.setdefault("category", category)
    result.setdefault("expense_date", datetime.now().strftime("%Y-%m-%d"))
    result.setdefault("amount", 0.0)
    result["paid"] = True

    return result


def _clean_string(val: str) -> str:
    """Clean up a string value from LLM response."""
    if not val:
        return ""
    val = str(val).strip()
    # Remove common LLM artifacts
    val = re.sub(r'^[()\\s\\-\\[\\]{}.,;:\\"\\\'\\u201c\\u201d]+', '', val)
    val = re.sub(r'[()\\s\\-\\[\\]{}.,;:\\"\\\'\\u201c\\u201d]+$', '', val)
    return val.strip()


def _parse_number(val) -> Optional[float]:
    """Parse a numeric value from LLM response, handling commas, Rs., ₹, etc."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    # Remove currency symbols and common prefixes
    s = re.sub(r'[₹$€£]', '', s)
    s = re.sub(r'(?i)^rs\.?\s*', '', s)
    s = re.sub(r'(?i)^inr\s*', '', s)
    s = s.replace(',', '')
    s = s.replace('/-', '')

    match = re.search(r'[-+]?\d*\.?\d+', s)
    if match:
        return float(match.group(0))
    return None


app = func.FunctionApp()
logger = logging.getLogger(__name__)


@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="%AZURE_QUEUE_STAGE4%",
    connection="ServiceBusConnection",
)
def stage4_map(msg: func.ServiceBusMessage):
    body = msg.get_body().decode("utf-8")
    try:
        payload = json.loads(body)
    except Exception as e:
        logger.error("[Stage4] Failed to parse message body JSON: %s", e)
        return

    job_id = payload.get("job_id")
    filename = payload.get("filename")
    content_type = payload.get("content_type")
    category = payload.get("category")
    artifact_url = payload.get("artifact_url")

    if not job_id or not artifact_url or not category:
        logger.error("[Stage4] Missing job_id, artifact_url, or category in payload: %s", payload)
        return

    logger.info("[Stage4] Starting field mapping for job=%s", job_id)

    try:
        update_stage_tracking(
            job_id=job_id,
            status="stage_4",
            current_stage="stage4_map",
            default_current_stage="stage4_map",
        )

        extraction = download_json_artifact(artifact_url)
        raw_response = extraction.get("raw_response", extraction)
        mapped_fields = run_stage4(raw_response, category)

        mapped_artifact_url = upload_json_artifact(
            job_id, 4, "mapped.json", {"category": category, "mapped_fields": mapped_fields}
        )

        update_stage_tracking(job_id=job_id, completed_stage_num=4)

        forward_to_stage(
            5,
            {
                "job_id": job_id,
                "filename": filename,
                "content_type": content_type,
                "category": category,
                "artifact_url": mapped_artifact_url,
            },
        )
        logger.info("[Stage4] Completed successfully for job=%s", job_id)

    except Exception as e:
        error_msg = f"Stage 4 failed: {str(e)}"
        logger.error("[Stage4] %s", error_msg)
        update_stage_tracking(job_id=job_id, status="failed", error_message=error_msg)

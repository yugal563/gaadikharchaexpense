import re
from datetime import datetime
from typing import Optional

from pipeline.stages.schemas import CATEGORY_SCHEMAS
from pipeline.stages.stage3_extraction import get_schema_for_category


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

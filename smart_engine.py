"""
smart_engine.py — Backward-compatibility shim.

All logic has been modularised into the engine/ package:
    engine/schemas.py       — CATEGORY_SCHEMAS
    engine/category.py      — detect_category_from_llm_response, get_schema_for_category
    engine/prompts.py       — build_single_pass_prompt, build_pass1_prompt, build_pass2_prompt
    engine/field_mapper.py  — extract_and_map_fields
    engine/validator.py     — validate_extracted_fields, filter_fields_by_category

Existing imports from smart_engine (e.g. in utils_llm_pipeline.py, utils_azure.py)
continue to work without any changes.
"""

# Re-export everything so existing callers need zero changes
from engine.schemas import CATEGORY_SCHEMAS                                    # noqa: F401
from engine.category import (                                                  # noqa: F401
    detect_category_from_llm_response,
    get_schema_for_category,
)
from engine.prompts import (                                                   # noqa: F401
    build_single_pass_prompt,
    build_pass1_prompt,
    build_pass2_prompt,
)
from engine.field_mapper import extract_and_map_fields                         # noqa: F401
from engine.validator import validate_extracted_fields, filter_fields_by_category  # noqa: F401

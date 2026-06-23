"""
LLM Extraction Pipeline — Orchestrates the full document extraction flow.

Pipeline:
    Upload → Preprocessing → LLM Pass 1 (category detection) →
    LLM Pass 2 (schema-specific extraction) → Validation → Response

This module connects:
    - llm_providers.py (LLM Abstraction Layer)
    - smart_engine.py (Smart Modeling Engine)
    - Existing preprocessing from main.py
"""

import time
from fastapi import HTTPException

from llm_providers import get_llm_provider
from engine.prompts import (
    build_pass1_prompt,
    build_pass2_prompt,
    build_single_pass_prompt,
)
from engine.category import detect_category_from_llm_response
from engine.field_mapper import extract_and_map_fields
from engine.validator import validate_extracted_fields, filter_fields_by_category


async def process_llm_extraction(image_bytes: bytes, content_type: str) -> dict:
    """
    Execute the full LLM-based extraction pipeline.
    
    Two-pass strategy:
        Pass 1: Send image with general prompt → detect category + raw fields
        Pass 2: Send image with category-specific schema prompt → precise extraction
    
    Args:
        image_bytes: Preprocessed image bytes (JPEG/PNG) or PDF bytes.
        content_type: MIME type of the input.
        
    Returns:
        dict with "latency_seconds" and "result" keys.
    """
    start_time = time.time()

    try:
        provider = get_llm_provider()
        print(f"[LLM Pipeline] Using provider: {provider.provider_name}")

        import os
        single_pass = os.getenv("SINGLE_PASS_MODE", "true").lower().strip() == "true"

        if single_pass:
            print("[LLM Pipeline] Running in SINGLE-PASS mode...")
            prompt = build_single_pass_prompt()
            try:
                response = await provider.extract_from_image(
                    image_bytes, prompt, content_type
                )
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"LLM Single-Pass extraction failed ({provider.provider_name}): {str(e)}"
                )

            if not response:
                raise HTTPException(
                    status_code=502,
                    detail=f"LLM Single-Pass returned empty response ({provider.provider_name})"
                )

            category = detect_category_from_llm_response(response)
            print(f"[LLM Pipeline] Detected category: {category}")
            merged = response
            merged["category"] = category
        else:
            print("[LLM Pipeline] Running in TWO-PASS mode...")
            # ── Pass 1: General extraction & category detection ──
            print("[LLM Pipeline] Pass 1: General extraction & category detection...")
            pass1_prompt = build_pass1_prompt()

            try:
                pass1_response = await provider.extract_from_image(
                    image_bytes, pass1_prompt, content_type
                )
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"LLM Pass 1 failed ({provider.provider_name}): {str(e)}"
                )

            if not pass1_response:
                raise HTTPException(
                    status_code=502,
                    detail=f"LLM Pass 1 returned empty response ({provider.provider_name})"
                )

            # Detect category from Pass 1 response
            category = detect_category_from_llm_response(pass1_response)
            print(f"[LLM Pipeline] Detected category: {category}")

            # ── Pass 2: Category-specific extraction ──
            print(f"[LLM Pipeline] Pass 2: {category}-specific extraction...")
            pass2_prompt = build_pass2_prompt(category)

            try:
                pass2_response = await provider.extract_from_image(
                    image_bytes, pass2_prompt, content_type
                )
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"LLM Pass 2 failed ({provider.provider_name}): {str(e)}"
                )

            if not pass2_response:
                raise HTTPException(
                    status_code=502,
                    detail=f"LLM Pass 2 returned empty response ({provider.provider_name})"
                )

            # Direct use of Pass 2 response (No fallback to Pass 1)
            merged = pass2_response
            # Force the detected category (don't let Pass 2 override if it disagrees)
            merged["category"] = category

        # ── Field Extraction & Mapping ──
        print("[LLM Pipeline] Extracting and mapping fields...")
        mapped_fields = extract_and_map_fields(merged, category)

        # ── Validation ──
        print("[LLM Pipeline] Validating fields...")
        validated = validate_extracted_fields(mapped_fields, category)

        # Add remarks
        mode_label = "Single-Pass" if single_pass else "Two-Pass"
        validated["remarks"] = f"[LLM {mode_label}: {provider.provider_name}]"

        # ── Filter by category ──
        filtered = filter_fields_by_category(validated, category)

        latency = time.time() - start_time
        print(f"[LLM Pipeline] Complete in {latency:.2f}s. Category: {category}, Amount: {filtered.get('amount')}")

        return {
            "latency_seconds": round(latency, 2),
            "result": filtered,
        }

    except HTTPException:
        raise
    except Exception as e:
        latency = time.time() - start_time
        print(f"[LLM Pipeline] Unexpected error after {latency:.2f}s: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"LLM extraction pipeline failed: {str(e)}"
        )




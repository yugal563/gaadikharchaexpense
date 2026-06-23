"""
engine/category.py — Category detection and schema lookup.
"""

from engine.schemas import CATEGORY_SCHEMAS


def detect_category_from_llm_response(llm_response: dict) -> str:
    """
    Determine the expense category from the LLM's initial extraction response.
    Uses the LLM's own classification plus keyword-based verification.

    Standard categories: Fuel, Maintenance, Vehicle, Other
    """
    category = llm_response.get("category", "Other")

    # Normalize for comparison only — preserve original casing for custom names
    cat_lower = str(category).lower().strip()

    # ── Map known standard aliases → canonical names ──────────────────────────
    if cat_lower in ("fuel", "petrol", "diesel", "gas"):
        return "Fuel"
    if cat_lower in ("maintenance", "repair", "service", "workshop"):
        return "Maintenance"
    if cat_lower in ("vehicle", "challan", "toll", "parking", "traffic"):
        return "Vehicle"

    # ── Vendor-hint fallback for when category field is unhelpful ─────────────
    vendor = str(llm_response.get("vendor", "")).lower()
    fuel_hints = ["hpcl", "iocl", "bpcl", "indian oil", "bharat petroleum",
                  "hindustan petroleum", "nayara", "shell", "petrol", "diesel", "fuel"]
    if any(h in vendor for h in fuel_hints):
        return "Fuel"

    maintenance_hints = ["service", "repair", "workshop", "garage", "mechanic",
                         "spare", "tyre", "tire", "battery"]
    if any(h in vendor for h in maintenance_hints):
        return "Maintenance"

    vehicle_hints = ["challan", "toll", "parking", "traffic"]
    if any(h in vendor for h in vehicle_hints):
        return "Vehicle"

    return "Other"


def get_schema_for_category(category: str) -> dict:
    """Return the field schema for the given expense category."""
    return CATEGORY_SCHEMAS.get(category, CATEGORY_SCHEMAS["Other"])

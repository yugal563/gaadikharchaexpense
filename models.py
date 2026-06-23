"""
models.py — Pydantic data models for the Expense Tracker API.
"""

from pydantic import BaseModel


class Expense(BaseModel):
    category: str
    vehicle: str | None = None
    expense_date: str
    petrol_pump: str | None = None
    location: str | None = None
    liters: float | None = None
    rate_per_liter: float | None = None
    odometer: int | None = None
    service_type: str | None = None
    vendor: str | None = None
    amount: float
    paid: bool
    registration_no: str | None = None
    challan_no: str | None = None
    challan_type: str | None = None
    violation_type: str | None = None
    issued_by: str | None = None
    due_date: str | None = None
    remarks: str | None = None
    party_type: str | None = None
    party: str | None = None
    contact: str | None = None
    expense_name: str | None = None

    # --- Additional DB Fields ---
    vendor_type: str | None = None
    parking_location: str | None = None
    maintenance_item: str | None = None
    custom_maintenance_item: str | None = None
    invoice_number: str | None = None
    taxable_amount: float | None = None
    non_taxable_amount: float | None = None
    km_limit: int | None = None
    hour_limit: int | None = None
    excess_km_rate: float | None = None
    excess_hour_rate: float | None = None
    excess_km_amount: float | None = None
    excess_hour_amount: float | None = None
    driver_allowance: float | None = None
    toll_charges: float | None = None
    parking_charges: float | None = None
    other_charges: float | None = None
    tds_percentage: float | None = None
    tds_amount: float | None = None
    gst_percentage: float | None = None
    gst_amount: float | None = None
    gst_invoicing_type: str | None = None
    gst_applicable_on_parking: bool | None = None
    gst_applicable_on_toll: bool | None = None
    gst_applicable_on_other_charges: bool | None = None
    paid_to: str | None = None
    contact_number: str | None = None

    model_config = {
        "extra": "allow"
    }

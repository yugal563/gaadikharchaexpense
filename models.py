"""
models.py — Data models and validation for the Expense Tracker API.
"""

class Expense:
    def __init__(self, data: dict):
        # 1. Validate required fields
        required_fields = ["category", "expense_date", "amount", "paid"]
        for field in required_fields:
            if field not in data or data[field] is None or data[field] == "":
                raise ValueError(f"Missing required field: '{field}'")
        
        # 2. Coerce required types
        self.category = str(data["category"]).strip()
        self.expense_date = str(data["expense_date"]).strip()
        
        try:
            self.amount = float(data["amount"])
        except (ValueError, TypeError):
            raise ValueError("Field 'amount' must be a valid number.")
            
        paid_val = data["paid"]
        if isinstance(paid_val, str):
            self.paid = paid_val.lower() in ("true", "1", "yes", "on")
        else:
            self.paid = bool(paid_val)

        # 3. Predefined optional fields in the DB schema
        optional_fields = [
            "vehicle", "petrol_pump", "location", "liters", "rate_per_liter",
            "odometer", "service_type", "vendor", "registration_no", "challan_no",
            "challan_type", "violation_type", "issued_by", "due_date",
            "party_type", "party", "expense_name",
            "vendor_type", "parking_location", "maintenance_item", "custom_maintenance_item",
            "invoice_number", "taxable_amount", "non_taxable_amount",
            "km_limit", "hour_limit", "excess_km_rate", "excess_hour_rate",
            "excess_km_amount", "excess_hour_amount", "driver_allowance",
            "toll_charges", "parking_charges", "other_charges", "tds_percentage",
            "tds_amount", "gst_percentage", "gst_amount", "gst_invoicing_type",
            "gst_applicable_on_parking", "gst_applicable_on_toll", "gst_applicable_on_other_charges",
            "paid_to", "contact_number",
            "total_amount", "fuel_type", "payment_mode", "action_type",
            "next_service_due", "work_order_number", "start_odometer_reading", "end_odometer_reading",
            "journey_start_datetime", "journey_end_datetime", "items"
        ]

        # 4. Map optional fields. Ignore any custom/dynamic attributes completely.
        for key in optional_fields:
            val = data.get(key)
            if val is None or val == "null" or val == "":
                setattr(self, key, None)
            else:
                if key in ("odometer", "km_limit", "hour_limit", "next_service_due") and val is not None:
                    try:
                        parsed_val = int(float(val))
                        if parsed_val < 0 or parsed_val > 9999999:
                            setattr(self, key, None)
                        else:
                            setattr(self, key, parsed_val)
                    except (ValueError, TypeError):
                        setattr(self, key, None)
                elif key in ("liters", "rate_per_liter", "taxable_amount", "non_taxable_amount",
                             "excess_km_rate", "excess_hour_rate", "excess_km_amount", "excess_hour_amount",
                             "driver_allowance", "toll_charges", "parking_charges", "other_charges",
                             "tds_percentage", "tds_amount", "gst_percentage", "gst_amount",
                             "total_amount", "start_odometer_reading", "end_odometer_reading") and val is not None:
                    try:
                        parsed_val = float(val)
                        if parsed_val < 0 or parsed_val > 99999999:
                            setattr(self, key, None)
                        else:
                            setattr(self, key, parsed_val)
                    except (ValueError, TypeError):
                        setattr(self, key, None)
                elif key in ("gst_applicable_on_parking", "gst_applicable_on_toll", "gst_applicable_on_other_charges") and val is not None:
                    if isinstance(val, str):
                        setattr(self, key, val.lower() in ("true", "1", "yes"))
                    else:
                        setattr(self, key, bool(val))
                else:
                    setattr(self, key, str(val).strip())

        # Ensure all optional fields have a default None if they weren't in data
        for field in optional_fields:
            if not hasattr(self, field):
                setattr(self, field, None)

        pass

        # Empty dict for API route compatibility
        self.model_extra = {}

    def model_dump(self) -> dict:
        """Dump model fields into a dictionary for database persistence compatibility."""
        dumped = {
            "category": self.category,
            "expense_date": self.expense_date,
            "amount": self.amount,
            "paid": self.paid
        }
        
        # Add optional attributes dynamically
        optional_fields = [
            "vehicle", "petrol_pump", "location", "liters", "rate_per_liter",
            "odometer", "service_type", "vendor", "registration_no", "challan_no",
            "challan_type", "violation_type", "issued_by", "due_date",
            "party_type", "party", "expense_name",
            "vendor_type", "parking_location", "maintenance_item", "custom_maintenance_item",
            "invoice_number", "taxable_amount", "non_taxable_amount",
            "km_limit", "hour_limit", "excess_km_rate", "excess_hour_rate",
            "excess_km_amount", "excess_hour_amount", "driver_allowance",
            "toll_charges", "parking_charges", "other_charges", "tds_percentage",
            "tds_amount", "gst_percentage", "gst_amount", "gst_invoicing_type",
            "gst_applicable_on_parking", "gst_applicable_on_toll", "gst_applicable_on_other_charges",
            "paid_to", "contact_number",
            "total_amount", "fuel_type", "payment_mode", "action_type",
            "next_service_due", "work_order_number", "start_odometer_reading", "end_odometer_reading",
            "journey_start_datetime", "journey_end_datetime", "items"
        ]
        for field in optional_fields:
            if hasattr(self, field):
                dumped[field] = getattr(self, field)
        return dumped


import re

def encode_expense_id(db_id: int, category: str) -> int:
    offset = {
        "Fuel": 1000000,
        "Maintenance": 2000000,
        "Vehicle": 3000000,
        "Other": 4000000
    }
    return offset.get(category, 4000000) + db_id

def decode_expense_id(expense_id: int) -> tuple[int, str]:
    if 1000000 <= expense_id < 2000000:
        return expense_id - 1000000, "Fuel"
    elif 2000000 <= expense_id < 3000000:
        return expense_id - 2000000, "Maintenance"
    elif 3000000 <= expense_id < 4000000:
        return expense_id - 3000000, "Vehicle"
    elif 4000000 <= expense_id:
        return expense_id - 4000000, "Other"
    return expense_id, "Other"

def parse_category_from_remarks(remarks: str) -> str:
    return "Other"

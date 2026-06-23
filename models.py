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
            "challan_type", "violation_type", "issued_by", "due_date", "remarks",
            "party_type", "party", "contact", "expense_name",
            "vendor_type", "parking_location", "maintenance_item", "custom_maintenance_item",
            "invoice_number", "taxable_amount", "non_taxable_amount",
            "km_limit", "hour_limit", "excess_km_rate", "excess_hour_rate",
            "excess_km_amount", "excess_hour_amount", "driver_allowance",
            "toll_charges", "parking_charges", "other_charges", "tds_percentage",
            "tds_amount", "gst_percentage", "gst_amount", "gst_invoicing_type",
            "gst_applicable_on_parking", "gst_applicable_on_toll", "gst_applicable_on_other_charges",
            "paid_to", "contact_number"
        ]

        # 4. Map optional fields. Ignore any custom/dynamic attributes completely.
        for key in optional_fields:
            val = data.get(key)
            if val is None or val == "null" or val == "":
                setattr(self, key, None)
            else:
                if key in ("odometer", "km_limit", "hour_limit") and val is not None:
                    try: setattr(self, key, int(float(val)))
                    except (ValueError, TypeError): setattr(self, key, None)
                elif key in ("liters", "rate_per_liter", "taxable_amount", "non_taxable_amount",
                             "excess_km_rate", "excess_hour_rate", "excess_km_amount", "excess_hour_amount",
                             "driver_allowance", "toll_charges", "parking_charges", "other_charges",
                             "tds_percentage", "tds_amount", "gst_percentage", "gst_amount") and val is not None:
                    try: setattr(self, key, float(val))
                    except (ValueError, TypeError): setattr(self, key, None)
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
            "challan_type", "violation_type", "issued_by", "due_date", "remarks",
            "party_type", "party", "contact", "expense_name",
            "vendor_type", "parking_location", "maintenance_item", "custom_maintenance_item",
            "invoice_number", "taxable_amount", "non_taxable_amount",
            "km_limit", "hour_limit", "excess_km_rate", "excess_hour_rate",
            "excess_km_amount", "excess_hour_amount", "driver_allowance",
            "toll_charges", "parking_charges", "other_charges", "tds_percentage",
            "tds_amount", "gst_percentage", "gst_amount", "gst_invoicing_type",
            "gst_applicable_on_parking", "gst_applicable_on_toll", "gst_applicable_on_other_charges",
            "paid_to", "contact_number"
        ]
        for field in optional_fields:
            if hasattr(self, field):
                dumped[field] = getattr(self, field)
        return dumped

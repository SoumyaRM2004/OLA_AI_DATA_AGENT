import io
import os
import re
import math
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, List, Optional, Tuple, Set, Union
import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values
import pandas as pd
import numpy as np
from utils.database import DatabaseConnection, get_db_config, get_session_schema_name, sanitize_session_id

# ============================================================
# 1. CANONICAL DATABASE SCHEMAS & METADATA
# Defines exact types, required fields, constraints, and dependencies
# for OLA-inspired mobility datasets.
# ============================================================

TABLE_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "users": {
        "label": "Users",
        "primary_key": "user_id",
        "target_table": "public.users",
        "load_order": 1,
        "columns": {
            "user_id": {"type": "int", "required": True, "nullable": False, "unique": True},
            "first_name": {"type": "str", "required": True, "nullable": False, "max_len": 100},
            "last_name": {"type": "str", "required": True, "nullable": False, "max_len": 100},
            "email": {"type": "str", "required": True, "nullable": False, "unique": True, "max_len": 255},
            "phone": {"type": "str", "required": False, "nullable": True, "max_len": 50},
            "city": {"type": "str", "required": False, "nullable": True, "max_len": 100},
            "province": {"type": "str", "required": False, "nullable": True, "max_len": 50},
            "user_type": {"type": "str", "required": True, "nullable": False, "max_len": 20},
            "signup_date": {"type": "date", "required": False, "nullable": True},
            "is_active": {"type": "bool", "required": False, "nullable": True}
        },
        "foreign_keys": {}
    },
    "vehicles": {
        "label": "Vehicles",
        "primary_key": "vehicle_id",
        "target_table": "public.vehicles",
        "load_order": 2,
        "columns": {
            "vehicle_id": {"type": "int", "required": True, "nullable": False, "unique": True},
            "driver_id": {"type": "int", "required": True, "nullable": False},
            "make": {"type": "str", "required": False, "nullable": True, "max_len": 50},
            "model": {"type": "str", "required": False, "nullable": True, "max_len": 50},
            "year": {"type": "int", "required": False, "nullable": True},
            "license_plate": {"type": "str", "required": False, "nullable": True, "unique": True, "max_len": 20},
            "color": {"type": "str", "required": False, "nullable": True, "max_len": 30},
            "is_active": {"type": "bool", "required": False, "nullable": True}
        },
        "foreign_keys": {
            "driver_id": ("users", "user_id")
        }
    },
    "rides": {
        "label": "Rides",
        "primary_key": "ride_id",
        "target_table": "public.rides",
        "load_order": 3,
        "columns": {
            "ride_id": {"type": "int", "required": True, "nullable": False, "unique": True},
            "rider_id": {"type": "int", "required": True, "nullable": False},
            "driver_id": {"type": "int", "required": True, "nullable": False},
            "requested_at": {"type": "timestamp", "required": False, "nullable": True},
            "pickup_time": {"type": "timestamp", "required": False, "nullable": True},
            "dropoff_time": {"type": "timestamp", "required": False, "nullable": True},
            "pickup_latitude": {"type": "decimal", "required": False, "nullable": True, "precision": (9, 6)},
            "pickup_longitude": {"type": "decimal", "required": False, "nullable": True, "precision": (9, 6)},
            "dropoff_latitude": {"type": "decimal", "required": False, "nullable": True, "precision": (9, 6)},
            "dropoff_longitude": {"type": "decimal", "required": False, "nullable": True, "precision": (9, 6)},
            "distance_km": {"type": "decimal", "required": False, "nullable": True, "precision": (6, 2)},
            "fare": {"type": "decimal", "required": False, "nullable": True, "precision": (10, 2)},
            "surge_multiplier": {"type": "decimal", "required": False, "nullable": True, "precision": (3, 2)},
            "status": {"type": "str", "required": False, "nullable": True, "max_len": 30},
            "cancellation_reason": {"type": "str", "required": False, "nullable": True, "max_len": 100}
        },
        "foreign_keys": {
            "rider_id": ("users", "user_id"),
            "driver_id": ("users", "user_id")
        }
    },
    "payments": {
        "label": "Payments",
        "primary_key": "payment_id",
        "target_table": "public.payments",
        "load_order": 4,
        "columns": {
            "payment_id": {"type": "int", "required": True, "nullable": False, "unique": True},
            "ride_id": {"type": "int", "required": True, "nullable": False},
            "user_id": {"type": "int", "required": True, "nullable": False},
            "amount": {"type": "decimal", "required": False, "nullable": True, "precision": (10, 2)},
            "payment_method": {"type": "str", "required": False, "nullable": True, "max_len": 50},
            "payment_status": {"type": "str", "required": False, "nullable": True, "max_len": 30},
            "transaction_id": {"type": "str", "required": False, "nullable": True, "unique": True, "max_len": 100},
            "payment_time": {"type": "timestamp", "required": False, "nullable": True}
        },
        "foreign_keys": {
            "ride_id": ("rides", "ride_id"),
            "user_id": ("users", "user_id")
        }
    },
    "ratings": {
        "label": "Ratings",
        "primary_key": "rating_id",
        "target_table": "public.ratings",
        "load_order": 5,
        "columns": {
            "rating_id": {"type": "int", "required": True, "nullable": False, "unique": True},
            "ride_id": {"type": "int", "required": True, "nullable": False},
            "rider_id": {"type": "int", "required": True, "nullable": False},
            "driver_id": {"type": "int", "required": True, "nullable": False},
            "rating": {"type": "int", "required": False, "nullable": True, "check_min": 1, "check_max": 5},
            "comment": {"type": "str", "required": False, "nullable": True},
            "rated_at": {"type": "timestamp", "required": False, "nullable": True}
        },
        "foreign_keys": {
            "ride_id": ("rides", "ride_id"),
            "rider_id": ("users", "user_id"),
            "driver_id": ("users", "user_id")
        }
    }
}

# Add convenience helper lists to TABLE_SCHEMAS for backwards compatibility
for tbl, info in TABLE_SCHEMAS.items():
    cols_dict = info["columns"]
    info["required_columns"] = [c for c, meta in cols_dict.items() if meta.get("required", False)]
    info["all_columns"] = list(cols_dict.keys())
    info["timestamp_columns"] = [c for c, meta in cols_dict.items() if meta.get("type") == "timestamp"]
    info["date_columns"] = [c for c, meta in cols_dict.items() if meta.get("type") == "date"]
    info["numeric_columns"] = [c for c, meta in cols_dict.items() if meta.get("type") in ("int", "decimal")]


# ============================================================
# 2. COLUMN ALIASES & SYNONYMS
# Deterministic mapping rules for user-uploaded CSV headers.
# ============================================================

COLUMN_ALIASES: Dict[str, Dict[str, str]] = {
    "users": {
        "customer_id": "user_id",
        "client_id": "user_id",
        "usr_id": "user_id",
        "account_id": "user_id",
        "id": "user_id",
        "firstname": "first_name",
        "first": "first_name",
        "fname": "first_name",
        "given_name": "first_name",
        "lastname": "last_name",
        "last": "last_name",
        "lname": "last_name",
        "surname": "last_name",
        "family_name": "last_name",
        "email_address": "email",
        "mail": "email",
        "user_email": "email",
        "email_id": "email",
        "mobile": "phone",
        "phone_number": "phone",
        "contact": "phone",
        "telephone": "phone",
        "mobile_no": "phone",
        "phone_no": "phone",
        "cell": "phone",
        "location": "city",
        "city_name": "city",
        "town": "city",
        "state": "province",
        "region": "province",
        "state_province": "province",
        "customer_type": "user_type",
        "usertype": "user_type",
        "role": "user_type",
        "account_type": "user_type",
        "signup_date": "signup_date",
        "sign_up_date": "signup_date",
        "joined_date": "signup_date",
        "registration_date": "signup_date",
        "created_at": "signup_date",
        "active": "is_active",
        "status_active": "is_active",
        "enabled": "is_active"
    },
    "vehicles": {
        "vehicle_id": "vehicle_id",
        "car_id": "vehicle_id",
        "auto_id": "vehicle_id",
        "veh_id": "vehicle_id",
        "id": "vehicle_id",
        "driver_id": "driver_id",
        "driver": "driver_id",
        "owner_id": "driver_id",
        "user_id": "driver_id",
        "make": "make",
        "brand": "make",
        "manufacturer": "make",
        "model": "model",
        "model_name": "model",
        "vehicle_model": "model",
        "year": "year",
        "model_year": "year",
        "manufacturing_year": "year",
        "manufacture_year": "year",
        "license_plate": "license_plate",
        "plate_number": "license_plate",
        "plate_no": "license_plate",
        "registration_no": "license_plate",
        "registration_number": "license_plate",
        "plate": "license_plate",
        "color": "color",
        "colour": "color",
        "active": "is_active",
        "is_active": "is_active",
        "enabled": "is_active"
    },
    "rides": {
        "ride_id": "ride_id",
        "trip_id": "ride_id",
        "booking_id": "ride_id",
        "id": "ride_id",
        "rider_id": "rider_id",
        "passenger_id": "rider_id",
        "customer_id": "rider_id",
        "client_id": "rider_id",
        "driver_id": "driver_id",
        "driver": "driver_id",
        "chauffeur_id": "driver_id",
        "vehicle_id": "vehicle_id",
        "car_id": "vehicle_id",
        "auto_id": "vehicle_id",
        "pickup_lat": "pickup_latitude",
        "pickup_latitude": "pickup_latitude",
        "start_latitude": "pickup_latitude",
        "start_lat": "pickup_latitude",
        "origin_lat": "pickup_latitude",
        "pickup_long": "pickup_longitude",
        "pickup_longitude": "pickup_longitude",
        "pickup_lng": "pickup_longitude",
        "start_longitude": "pickup_longitude",
        "start_long": "pickup_longitude",
        "origin_lng": "pickup_longitude",
        "dropoff_lat": "dropoff_latitude",
        "dropoff_latitude": "dropoff_latitude",
        "end_latitude": "dropoff_latitude",
        "end_lat": "dropoff_latitude",
        "dest_lat": "dropoff_latitude",
        "destination_lat": "dropoff_latitude",
        "dropoff_long": "dropoff_longitude",
        "dropoff_longitude": "dropoff_longitude",
        "dropoff_lng": "dropoff_longitude",
        "end_longitude": "dropoff_longitude",
        "end_long": "dropoff_longitude",
        "dest_lng": "dropoff_longitude",
        "destination_long": "dropoff_longitude",
        "requested_at": "requested_at",
        "booking_time": "requested_at",
        "request_time": "requested_at",
        "booked_at": "requested_at",
        "created_at": "requested_at",
        "pickup_time": "pickup_time",
        "trip_start": "pickup_time",
        "start_time": "pickup_time",
        "picked_up_at": "pickup_time",
        "dropoff_time": "dropoff_time",
        "trip_end": "dropoff_time",
        "end_time": "dropoff_time",
        "dropped_off_at": "dropoff_time",
        "fare": "fare",
        "price": "fare",
        "trip_fare": "fare",
        "cost": "fare",
        "ride_fare": "fare",
        "distance_km": "distance_km",
        "distance": "distance_km",
        "trip_distance": "distance_km",
        "km": "distance_km",
        "duration_minutes": "duration_minutes",
        "duration": "duration_minutes",
        "trip_duration": "duration_minutes",
        "duration_min": "duration_minutes",
        "surge_multiplier": "surge_multiplier",
        "surge": "surge_multiplier",
        "surge_rate": "surge_multiplier",
        "multiplier": "surge_multiplier",
        "status": "status",
        "ride_status": "status",
        "trip_status": "status",
        "booking_status": "status",
        "cancellation_reason": "cancellation_reason",
        "cancel_reason": "cancellation_reason"
    },
    "payments": {
        "payment_id": "payment_id",
        "txn_id": "payment_id",
        "receipt_id": "payment_id",
        "id": "payment_id",
        "ride_id": "ride_id",
        "trip_id": "ride_id",
        "booking_id": "ride_id",
        "user_id": "user_id",
        "customer_id": "user_id",
        "payer_id": "user_id",
        "rider_id": "user_id",
        "amount": "amount",
        "payment_amount": "amount",
        "total_amount": "amount",
        "fare_paid": "amount",
        "price": "amount",
        "payment_method": "payment_method",
        "method": "payment_method",
        "payment_type": "payment_method",
        "pay_method": "payment_method",
        "payment_status": "payment_status",
        "status": "payment_status",
        "pay_status": "payment_status",
        "transaction_id": "transaction_id",
        "reference_number": "transaction_id",
        "transaction_no": "transaction_id",
        "ref_id": "transaction_id",
        "payment_time": "payment_time",
        "paid_at": "payment_time",
        "transaction_time": "payment_time",
        "txn_time": "payment_time"
    },
    "ratings": {
        "rating_id": "rating_id",
        "review_id": "rating_id",
        "feedback_id": "rating_id",
        "id": "rating_id",
        "ride_id": "ride_id",
        "trip_id": "ride_id",
        "booking_id": "ride_id",
        "rider_id": "rider_id",
        "passenger_id": "rider_id",
        "user_id": "rider_id",
        "customer_id": "rider_id",
        "driver_id": "driver_id",
        "driver": "driver_id",
        "rated_driver_id": "driver_id",
        "rating": "rating",
        "score": "rating",
        "stars": "rating",
        "rate": "rating",
        "comment": "comment",
        "review": "comment",
        "feedback": "comment",
        "notes": "comment",
        "rated_at": "rated_at",
        "rating_time": "rated_at",
        "review_date": "rated_at",
        "created_at": "rated_at"
    }
}


# ============================================================
# 3. STRUCTURED ERROR MODEL & FORMATTING
# ============================================================

class StructuredValidationError:
    """
    Standardized, rich validation & import error container.
    """
    def __init__(
        self,
        dataset: str,
        file: str,
        target_table: str,
        problem: str,
        error_type: str,
        suggested_action: str,
        row: Optional[int] = None,
        column: Optional[str] = None,
        value: Optional[Any] = None,
        expected: Optional[str] = None,
        severity: str = "error",
        technical_details: Optional[str] = None
    ):
        self.dataset = dataset
        self.file = file
        self.target_table = target_table
        self.problem = problem
        self.error_type = error_type
        self.suggested_action = suggested_action
        self.row = row
        self.column = column
        self.value = str(value) if value is not None else None
        self.expected = expected
        self.severity = severity
        self.technical_details = technical_details

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset,
            "file": self.file,
            "target_table": self.target_table,
            "row": self.row,
            "column": self.column,
            "value": self.value,
            "error_type": self.error_type,
            "problem": self.problem,
            "message": self.problem,
            "expected": self.expected,
            "suggested_action": self.suggested_action,
            "severity": self.severity,
            "technical_details": self.technical_details
        }

    def to_formatted_string(self) -> str:
        lines = []
        icon = "❌" if self.severity == "error" else "⚠️"
        lines.append(f"{icon} {self.error_type.replace('_', ' ').title()}")
        if self.file:
            lines.append(f"File: {self.file}")
        if self.dataset:
            lines.append(f"Dataset: {self.dataset}")
        if self.target_table:
            lines.append(f"Target: {self.target_table}")
        if self.row is not None:
            lines.append(f"Row: {self.row}")
        if self.column:
            lines.append(f"Column: {self.column}")
        if self.value is not None:
            lines.append(f"Value: {self.value}")
        lines.append(f"Problem: {self.problem}")
        if self.expected:
            lines.append(f"Expected: {self.expected}")
        if self.suggested_action:
            lines.append(f"Suggested action: {self.suggested_action}")
        return "\n".join(lines)


def format_import_error(
    dataset: str,
    target_table: Optional[str] = None,
    column: Optional[str] = None,
    row: Optional[Any] = None,
    value: Optional[Any] = None,
    problem: Optional[str] = None,
    suggested_action: Optional[str] = None,
    expected: Optional[str] = None,
    error_type: str = "import_error",
    file: Optional[str] = None
) -> str:
    """Backwards-compatible string formatter returning clean structured text."""
    err = StructuredValidationError(
        dataset=dataset,
        file=file or (f"{dataset.lower()}.csv" if dataset else "uploaded.csv"),
        target_table=target_table or "public.unknown",
        problem=problem or "Unknown validation issue",
        error_type=error_type,
        suggested_action=suggested_action or "Review dataset values.",
        row=row,
        column=column,
        value=value,
        expected=expected
    )
    return err.to_formatted_string()


# ============================================================
# 4. DETERMINISTIC VALUE NORMALIZATION & TYPE PARSERS
# Ensures raw CSV values (NaN, NULL, empty strings, etc.) are converted
# deterministically to Python None / SQL NULL or validated strict types.
# ============================================================

NULL_LITERALS = {
    "", "nan", "nat", "null", "none", "n/a", "na", "undefined", "<na>", "nil", "void"
}

def is_null_or_empty(val: Any) -> bool:
    """
    Deterministically checks if a value represents null, NaN, NaT, or empty missing value.
    """
    if val is None:
        return True
    if isinstance(val, (float, np.floating)):
        return math.isnan(val) or pd.isna(val)
    if pd.isna(val):
        return True
    if isinstance(val, str):
        return val.strip().lower() in NULL_LITERALS
    return False


def normalize_string_value(val: Any, nullable: bool = True, max_len: Optional[int] = None) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Normalizes string values.
    Returns (is_valid, normalized_str_or_None, error_detail).
    """
    if is_null_or_empty(val):
        if nullable:
            return True, None, None
        return False, None, "Missing value in non-nullable string column"
    
    s = str(val).strip()
    if max_len and len(s) > max_len:
        return False, None, f"String length ({len(s)}) exceeds maximum allowed ({max_len} characters)"
    return True, s, None


def normalize_integer_value(val: Any, nullable: bool = True) -> Tuple[bool, Optional[int], Optional[str]]:
    """
    Normalizes and validates integer values.
    Rejects floats with non-zero decimal portions, NaNs, and unparseable strings.
    """
    if is_null_or_empty(val):
        if nullable:
            return True, None, None
        return False, None, "Missing value in non-nullable integer column"

    if isinstance(val, (bool, np.bool_)):
        return False, None, f"Boolean value '{val}' is not a valid integer"

    if isinstance(val, (int, np.integer)):
        return True, int(val), None

    if isinstance(val, (float, np.floating)):
        if math.isnan(val) or math.isinf(val):
            return False, None, "Invalid numeric value (NaN or Infinity)"
        if val.is_integer():
            return True, int(val), None
        return False, None, f"Decimal value '{val}' cannot be converted to integer"

    if isinstance(val, str):
        s = val.strip()
        if s.lower() in NULL_LITERALS:
            if nullable:
                return True, None, None
            return False, None, "Missing value in non-nullable integer column"
        try:
            # First try direct integer conversion
            return True, int(s), None
        except ValueError:
            # Check if float string like "123.0"
            try:
                f = float(s)
                if math.isnan(f) or math.isinf(f):
                    return False, None, f"Invalid numeric value '{s}'"
                if f.is_integer():
                    return True, int(f), None
                return False, None, f"Value '{s}' contains decimal fraction and is not a valid integer"
            except ValueError:
                return False, None, f"Cannot parse '{s}' as an integer"

    return False, None, f"Unsupported data type for integer conversion: {type(val).__name__}"


def normalize_decimal_value(
    val: Any,
    nullable: bool = True,
    precision: Optional[Tuple[int, int]] = None
) -> Tuple[bool, Optional[Union[float, Decimal]], Optional[str]]:
    """
    Normalizes and validates decimal/numeric values.
    Rejects NaN / inf and invalid strings.
    """
    if is_null_or_empty(val):
        if nullable:
            return True, None, None
        return False, None, "Missing value in non-nullable numeric column"

    if isinstance(val, (bool, np.bool_)):
        return False, None, f"Boolean value '{val}' is not a valid numeric value"

    if isinstance(val, (int, float, np.integer, np.floating)):
        if isinstance(val, (float, np.floating)) and (math.isnan(val) or math.isinf(val)):
            return False, None, "Invalid numeric value (NaN or Infinity)"
        return True, float(val), None

    if isinstance(val, Decimal):
        if val.is_nan() or val.is_infinite():
            return False, None, "Invalid numeric value (NaN or Infinity)"
        return True, float(val), None

    if isinstance(val, str):
        s = val.strip().replace("$", "").replace(",", "")
        if s.lower() in NULL_LITERALS:
            if nullable:
                return True, None, None
            return False, None, "Missing value in non-nullable numeric column"
        try:
            f = float(s)
            if math.isnan(f) or math.isinf(f):
                return False, None, f"Invalid numeric value '{s}'"
            return True, f, None
        except ValueError:
            return False, None, f"Cannot parse '{s}' as a numeric/decimal value"

    return False, None, f"Unsupported data type for numeric conversion: {type(val).__name__}"


def normalize_boolean_value(val: Any, nullable: bool = True) -> Tuple[bool, Optional[bool], Optional[str]]:
    """
    Normalizes boolean representations (true/false, 1/0, t/f, yes/no).
    Rejects ambiguous strings.
    """
    if is_null_or_empty(val):
        if nullable:
            return True, None, None
        return False, None, "Missing value in non-nullable boolean column"

    if isinstance(val, (bool, np.bool_)):
        return True, bool(val), None

    if isinstance(val, (int, np.integer)):
        if val == 1:
            return True, True, None
        if val == 0:
            return True, False, None
        return False, None, f"Integer value '{val}' is not a valid boolean (expected 0 or 1)"

    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("true", "t", "1", "yes", "y"):
            return True, True, None
        if s in ("false", "f", "0", "no", "n"):
            return True, False, None
        return False, None, f"Ambiguous or invalid boolean value '{val}' (expected true/false, 1/0, yes/no)"

    return False, None, f"Unsupported data type for boolean conversion: {type(val).__name__}"


def parse_and_validate_timestamp(val: Any, nullable: bool = True) -> Tuple[bool, Optional[datetime], Optional[str]]:
    """
    Safely parses timestamp values into Python datetime objects or None.
    Rejects invalid timestamp strings and never returns float NaN.
    """
    if is_null_or_empty(val):
        if nullable:
            return True, None, None
        return False, None, "Missing value in non-nullable timestamp column"

    if isinstance(val, (datetime, pd.Timestamp)):
        if pd.isna(val):
            return (True, None, None) if nullable else (False, None, "Missing value in non-nullable timestamp column")
        return True, val.to_pydatetime() if isinstance(val, pd.Timestamp) else val, None

    if isinstance(val, date) and not isinstance(val, datetime):
        return True, datetime.combine(val, datetime.min.time()), None

    if isinstance(val, str):
        s = val.strip()
        if s.lower() in NULL_LITERALS:
            if nullable:
                return True, None, None
            return False, None, "Missing value in non-nullable timestamp column"
        try:
            dt = pd.to_datetime(s, errors="raise")
            if pd.isna(dt):
                return False, None, f"Cannot parse '{s}' as a valid timestamp"
            return True, dt.to_pydatetime() if isinstance(dt, pd.Timestamp) else dt, None
        except Exception:
            return False, None, f"Cannot parse '{s}' as a valid timestamp"

    return False, None, f"Invalid timestamp type: {type(val).__name__}"


def parse_and_validate_date(val: Any, nullable: bool = True) -> Tuple[bool, Optional[date], Optional[str]]:
    """
    Safely parses date values into Python date objects or None.
    """
    if is_null_or_empty(val):
        if nullable:
            return True, None, None
        return False, None, "Missing value in non-nullable date column"

    if isinstance(val, (datetime, pd.Timestamp)):
        if pd.isna(val):
            return (True, None, None) if nullable else (False, None, "Missing value in non-nullable date column")
        return True, val.date(), None

    if isinstance(val, date):
        return True, val, None

    if isinstance(val, str):
        s = val.strip()
        if s.lower() in NULL_LITERALS:
            if nullable:
                return True, None, None
            return False, None, "Missing value in non-nullable date column"
        try:
            dt = pd.to_datetime(s, errors="raise")
            if pd.isna(dt):
                return False, None, f"Cannot parse '{s}' as a valid date"
            return True, dt.date(), None
        except Exception:
            return False, None, f"Cannot parse '{s}' as a valid date"

    return False, None, f"Invalid date type: {type(val).__name__}"


def normalize_value_by_type(
    val: Any,
    col_type: str,
    nullable: bool = True,
    meta: Optional[Dict[str, Any]] = None
) -> Tuple[bool, Any, Optional[str]]:
    """
    Master dispatcher for deterministic value normalization.
    """
    meta = meta or {}
    if col_type == "int":
        valid, n_val, err = normalize_integer_value(val, nullable=nullable)
        if valid and n_val is not None:
            # Check range if configured
            if "check_min" in meta and n_val < meta["check_min"]:
                return False, None, f"Value {n_val} is below minimum allowed ({meta['check_min']})"
            if "check_max" in meta and n_val > meta["check_max"]:
                return False, None, f"Value {n_val} exceeds maximum allowed ({meta['check_max']})"
        return valid, n_val, err

    elif col_type == "decimal":
        return normalize_decimal_value(val, nullable=nullable, precision=meta.get("precision"))

    elif col_type == "timestamp":
        return parse_and_validate_timestamp(val, nullable=nullable)

    elif col_type == "date":
        return parse_and_validate_date(val, nullable=nullable)

    elif col_type == "bool":
        return normalize_boolean_value(val, nullable=nullable)

    elif col_type == "str":
        return normalize_string_value(val, nullable=nullable, max_len=meta.get("max_len"))

    else:
        # Fallback
        if is_null_or_empty(val):
            return True, None, None
        return True, val, None


def normalize_generic_value(val: Any) -> Any:
    """
    Converts pandas / numpy NaN / NaT / missing values to Python None.
    """
    if is_null_or_empty(val):
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, (np.bool_,)):
        return bool(val)
    return val


def normalize_header_name(header: Any) -> str:
    """
    Deterministically normalizes header names for comparison:
    - Lowercases
    - Strips whitespace
    - Replaces spaces, hyphens, dots, slashes with underscores
    - Removes non-alphanumeric/underscore characters
    Example: 'User ID' -> 'user_id', '  first-name. ' -> 'first_name'
    """
    if header is None:
        return ""
    s = str(header).strip().lower()
    s = re.sub(r'[\s\-./\\]+', '_', s)
    s = re.sub(r'[^a-z0-9_]', '', s)
    s = re.sub(r'_+', '_', s).strip('_')
    return s


# ============================================================
# CANONICAL SAMPLES DICTIONARY (Single Source of Truth)
# ============================================================

CANONICAL_SAMPLES: Dict[str, str] = {
    "users": """user_id,first_name,last_name,email,phone,city,province,user_type,signup_date,is_active
101,Aarav,Sharma,aarav.sharma@example.com,+14165550101,Toronto,ON,rider,2024-01-15,True
102,Priya,Patel,priya.patel@example.com,+16045550102,Vancouver,BC,rider,2024-02-20,True
103,Rohan,Verma,rohan.verma@example.com,+14035550103,Calgary,AB,rider,2024-03-10,True
104,Ananya,Iyer,ananya.iyer@example.com,+15145550104,Montreal,QC,rider,2024-04-05,True
105,Kavita,Rao,kavita.rao@example.com,+16135550105,Ottawa,ON,rider,2024-05-12,False
106,Vikram,Singh,vikram.singh@example.com,+14165550106,Toronto,ON,driver,2023-11-01,True
107,Rahul,Nair,rahul.nair@example.com,+16045550107,Vancouver,BC,driver,2023-12-15,True
108,Amit,Gupta,amit.gupta@example.com,+14035550108,Calgary,AB,driver,2024-01-20,True
109,Deepak,Kumar,deepak.kumar@example.com,+15145550109,Montreal,QC,driver,2024-02-10,True
110,Suresh,Reddy,suresh.reddy@example.com,+16135550110,Ottawa,ON,driver,2024-03-01,True""",
    "vehicles": """vehicle_id,driver_id,make,model,year,license_plate,color,is_active
201,106,Toyota,Camry,2022,TO-106-AB,Silver,True
202,107,Honda,Civic,2021,VA-107-CD,White,True
203,108,Hyundai,Elantra,2023,CA-108-EF,Black,True
204,109,Nissan,Sentra,2020,MO-109-GH,Blue,True
205,110,Kia,Forte,2022,OT-110-IJ,Grey,True""",
    "rides": """ride_id,rider_id,driver_id,requested_at,pickup_time,dropoff_time,pickup_latitude,pickup_longitude,dropoff_latitude,dropoff_longitude,distance_km,fare,surge_multiplier,status,cancellation_reason
301,101,106,2025-01-10 08:30:00,2025-01-10 08:35:00,2025-01-10 08:52:00,43.653226,-79.383184,43.642567,-79.387057,6.20,28.50,1.00,completed,
302,102,107,2025-01-10 09:15:00,2025-01-10 09:20:00,2025-01-10 09:40:00,49.282729,-123.120738,49.260605,-123.146027,8.10,34.00,1.20,completed,
303,103,108,2025-01-10 10:00:00,2025-01-10 10:06:00,2025-01-10 10:22:00,51.044733,-114.071883,51.050110,-114.085200,4.30,19.75,1.00,completed,
304,104,109,2025-01-10 11:30:00,,,45.501689,-73.567256,45.510000,-73.570000,0.00,0.00,1.00,cancelled,Rider cancelled
305,105,110,2025-01-10 12:00:00,2025-01-10 12:05:00,2025-01-10 12:25:00,45.421530,-75.697193,45.430000,-75.700000,5.00,22.50,1.00,completed,""",
    "payments": """payment_id,ride_id,user_id,amount,payment_method,payment_status,transaction_id,payment_time
401,301,101,28.50,card,success,TXN-401-20250110,2025-01-10 08:53:00
402,302,102,34.00,upi,success,TXN-402-20250110,2025-01-10 09:41:00
403,303,103,19.75,wallet,success,TXN-403-20250110,2025-01-10 10:23:00
404,305,105,22.50,cash,success,TXN-404-20250110,2025-01-10 12:26:00""",
    "ratings": """rating_id,ride_id,rider_id,driver_id,rating,comment,rated_at
501,301,101,106,5,Great ride very polite driver!,2025-01-10 08:55:00
502,302,102,107,4,Smooth trip through downtown,2025-01-10 09:45:00
503,303,103,108,5,Quick arrival and clean car,2025-01-10 10:25:00
504,305,105,110,5,Excellent route navigation,2025-01-10 12:30:00"""
}


# ============================================================
# COMPOSITE MAPPINGS REGISTRY
# Controlled composite column transformations (e.g. name -> first_name + last_name)
# ============================================================

COMPOSITE_MAPPINGS: Dict[str, Dict[str, List[str]]] = {
    "users": {
        "name": ["first_name", "last_name"],
        "full_name": ["first_name", "last_name"],
        "fullname": ["first_name", "last_name"],
        "user_name": ["first_name", "last_name"],
        "customer_name": ["first_name", "last_name"],
        "client_name": ["first_name", "last_name"]
    }
}


def split_full_name(name_val: Any) -> Tuple[Optional[str], Optional[str]]:
    """
    Deterministically splits a full name string:
    - First whitespace-delimited token -> first_name
    - Remaining tokens joined with single space -> last_name
    - If single token (e.g. 'Madonna') -> ('Madonna', None)
    - If empty/None -> (None, None)
    """
    if name_val is None or pd.isna(name_val):
        return None, None
    s = str(name_val).strip()
    if not s:
        return None, None
    tokens = s.split()
    if len(tokens) == 0:
        return None, None
    if len(tokens) == 1:
        return tokens[0], None
    return tokens[0], " ".join(tokens[1:])


# ============================================================
# 5. DATASET AUTO-DETECTION & COLUMN MAPPING ENGINE
# Header-based scoring engine and synonym matcher.
# ============================================================

def detect_dataset_from_headers(
    headers: List[str]
) -> Dict[str, Any]:
    """
    Inspects CSV headers and computes deterministic match scores against all 5 supported schemas.
    Evaluates exact matches, aliases, and controlled composite mappings.
    Does NOT use the filename to determine dataset.
    """
    clean_headers = [normalize_header_name(h) for h in headers if h is not None and str(h).strip()]
    if not clean_headers:
        return {
            "detected_dataset": None,
            "label": "Unknown",
            "confidence": "Low",
            "confidence_score": 0.0,
            "proposed_mappings": {},
            "all_scores": {}
        }

    scores: Dict[str, float] = {}
    mappings_by_dataset: Dict[str, Dict[str, str]] = {}

    for tbl_name, schema in TABLE_SCHEMAS.items():
        canonical_cols = set(schema["columns"].keys())
        req_cols = set(schema["required_columns"])
        pk = schema["primary_key"]
        aliases = COLUMN_ALIASES.get(tbl_name, {})
        composites = COMPOSITE_MAPPINGS.get(tbl_name, {})

        matched_canonical = set()
        table_mappings = {}

        # 1. Check exact matches and aliases
        for orig_h, h in zip(headers, clean_headers):
            canonical = None
            if h in canonical_cols:
                canonical = h
            elif h in aliases:
                canonical = aliases[h]
            
            if canonical:
                matched_canonical.add(canonical)
                table_mappings[orig_h] = canonical

        # 2. Check composite mappings if canonical fields are unmapped
        for orig_h, h in zip(headers, clean_headers):
            if orig_h not in table_mappings and h in composites:
                comp_targets = composites[h]
                if any(t not in matched_canonical for t in comp_targets):
                    for t in comp_targets:
                        matched_canonical.add(t)
                    table_mappings[orig_h] = " + ".join(comp_targets)

        missing_req = req_cols - matched_canonical
        
        # Perfect exact match on all uploaded columns matching canonical columns
        if len(clean_headers) > 0 and len(matched_canonical) == len(clean_headers) and not missing_req and not any(" + " in m for m in table_mappings.values()):
            score = 100.0
        else:
            req_coverage = len(req_cols.intersection(matched_canonical)) / max(len(req_cols), 1)
            all_coverage = len(matched_canonical) / max(len(canonical_cols), 1)
            score = (req_coverage * 70.0) + (all_coverage * 30.0)
            if missing_req:
                score = score * 0.5  # Penalize missing required columns

        scores[tbl_name] = round(max(0.0, min(100.0, score)), 1)
        mappings_by_dataset[tbl_name] = table_mappings

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_table, best_score = sorted_scores[0]
    second_table, second_score = sorted_scores[1] if len(sorted_scores) > 1 else (None, 0.0)

    if best_score >= 80.0:
        confidence = "High"
        detected = best_table
    elif best_score >= 45.0:
        confidence = "Medium"
        detected = best_table
    else:
        confidence = "Low"
        detected = None

    return {
        "detected_dataset": detected,
        "label": TABLE_SCHEMAS.get(detected, {}).get("label", "Unknown") if detected else "Unknown",
        "confidence": confidence,
        "confidence_score": best_score,
        "proposed_mappings": mappings_by_dataset.get(detected or "", {}),
        "all_scores": scores
    }


def map_columns_to_schema(
    uploaded_columns: List[str],
    dataset_type: str,
    custom_mappings: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Maps uploaded columns to canonical schema columns using:
    1. Exact canonical column match (Highest priority)
    2. Known deterministic aliases
    3. Controlled composite mappings (e.g. name -> first_name + last_name)
    4. Manual user custom mapping override
    5. Reject if required columns remain unresolved
    """
    clean_dataset = (dataset_type or "").lower().strip()
    if clean_dataset not in TABLE_SCHEMAS:
        return {
            "valid": False,
            "error": f"Invalid dataset type '{dataset_type}'.",
            "mapped_columns": {},
            "composite_columns": {},
            "mapping_details": [],
            "extra_columns": [],
            "missing_required": [],
            "ambiguous_columns": [],
            "review_required": False
        }

    schema = TABLE_SCHEMAS[clean_dataset]
    canonical_cols = set(schema["columns"].keys())
    req_cols = set(schema["required_columns"])
    aliases = COLUMN_ALIASES.get(clean_dataset, {})
    composites = COMPOSITE_MAPPINGS.get(clean_dataset, {})
    custom = {normalize_header_name(k): normalize_header_name(v) for k, v in (custom_mappings or {}).items()}

    mapped_columns: Dict[str, str] = {}         # uploaded -> canonical column
    composite_columns: Dict[str, List[str]] = {}  # uploaded -> list of canonical columns (e.g. name -> ['first_name', 'last_name'])
    mapping_details: List[Dict[str, Any]] = []
    used_canonical: Set[str] = set()

    # Pass 1: Handle custom mappings, exact matches, and known aliases
    for col in uploaded_columns:
        norm = normalize_header_name(col)
        target = None
        status = "unmapped"
        confidence = 0
        reason = "No safe mapping found (Extra column)"

        if norm in custom:
            custom_target = custom[norm]
            if custom_target in canonical_cols:
                target = custom_target
                status = "custom"
                confidence = 100
                reason = "User custom mapping override"
            elif "+" in custom_target:
                # Custom composite mapping
                comp_targets = [normalize_header_name(t) for t in custom_target.split("+")]
                if all(t in canonical_cols for t in comp_targets):
                    composite_columns[col] = comp_targets
                    for t in comp_targets:
                        used_canonical.add(t)
                    mapped_columns[col] = " + ".join(comp_targets)
                    mapping_details.append({
                        "uploaded": col,
                        "canonical": " + ".join(comp_targets),
                        "status": "composite",
                        "confidence": 95,
                        "reason": f"Custom composite mapping: split into {', '.join(comp_targets)}"
                    })
                    continue

        elif norm in canonical_cols:
            target = norm
            status = "exact"
            confidence = 100
            reason = "Exact normalized header match"
        elif norm in aliases:
            alias_target = aliases[norm]
            if alias_target in canonical_cols:
                target = alias_target
                status = "alias"
                confidence = 95
                reason = "Known configured alias"

        if target:
            mapped_columns[col] = target
            used_canonical.add(target)
            mapping_details.append({
                "uploaded": col,
                "canonical": target,
                "status": status,
                "confidence": confidence,
                "reason": reason
            })
        else:
            # Keep placeholder for Pass 2 composite check
            mapping_details.append({
                "uploaded": col,
                "canonical": None,
                "status": "extra",
                "confidence": 0,
                "reason": "No safe mapping found (Extra column)"
            })

    # Pass 2: Check controlled composite mappings for unmapped columns
    for idx, item in enumerate(mapping_details):
        if item["status"] == "extra":
            col = item["uploaded"]
            norm = normalize_header_name(col)
            if norm in composites:
                comp_targets = composites[norm]
                # Only activate if any of the target canonical columns are still unmapped
                if any(t not in used_canonical for t in comp_targets):
                    composite_columns[col] = comp_targets
                    for t in comp_targets:
                        used_canonical.add(t)
                    mapped_columns[col] = " + ".join(comp_targets)
                    mapping_details[idx] = {
                        "uploaded": col,
                        "canonical": " + ".join(comp_targets),
                        "status": "composite",
                        "confidence": 90,
                        "reason": f"Composite mapping: split into {', '.join(comp_targets)} (Review required)"
                    }

    extra_columns = [col for col in uploaded_columns if col not in mapped_columns]
    missing_required = sorted(list(req_cols - used_canonical))
    review_required = len(composite_columns) > 0 or any(m["status"] == "alias" for m in mapping_details)

    return {
        "valid": len(missing_required) == 0,
        "dataset_type": clean_dataset,
        "mapped_columns": mapped_columns,
        "composite_columns": composite_columns,
        "mapping_details": mapping_details,
        "extra_columns": extra_columns,
        "missing_required": missing_required,
        "review_required": review_required,
        "ambiguous_columns": []
    }


# ============================================================
# 6. DATABASE POSTGRES ERROR TRANSLATOR
# Wraps PostgreSQL error strings into clear, actionable context.
# ============================================================

def parse_postgres_error_details(
    err_str: str,
    current_tbl: str,
    df: Optional[pd.DataFrame] = None,
    filename: Optional[str] = None
) -> StructuredValidationError:
    """
    Parses a PostgreSQL database error and wraps it in a structured, actionable object.
    """
    tbl = current_tbl or "unknown"
    fn = filename or f"{tbl}.csv"
    col = None
    row = None
    val = None
    problem = None
    expected = None
    suggested = None
    err_type = "database_load_error"

    if 'timestamp without time zone but expression is of type double precision' in err_str or "'NaN'" in err_str:
        col_match = re.search(r'column "([^"]+)"', err_str)
        col = col_match.group(1) if col_match else "pickup_time"
        val = "NaN"
        err_type = "invalid_timestamp"
        problem = "Missing or invalid timestamp value was passed as float NaN instead of SQL NULL."
        expected = "A valid timestamp such as 2026-02-27 20:13:30 or NULL."
        suggested = "Replace the missing timestamp with a valid timestamp or leave it empty if nullable."

    elif 'violates not-null constraint' in err_str:
        col_match = re.search(r'column "([^"]+)"', err_str)
        col = col_match.group(1) if col_match else None
        err_type = "not_null_violation"
        problem = f"Column '{col}' contains NULL values violating NOT NULL constraint." if col else "NOT NULL constraint violated."
        expected = f"Non-null value for column '{col}'." if col else "Non-null value."
        suggested = f"Provide non-empty values for required column '{col}'." if col else "Provide non-empty values for required fields."

    elif 'violates foreign key constraint' in err_str:
        key_match = re.search(r'Key \(([^)]+)\)=\(([^)]+)\)', err_str)
        if key_match:
            col = key_match.group(1)
            val = key_match.group(2)
        tbl_match = re.search(r'table "([^"]+)"', err_str)
        parent_tbl = tbl_match.group(1) if tbl_match else "parent table"
        err_type = "foreign_key_violation"
        problem = f"Referenced {col} value ({val}) does not exist in {parent_tbl}." if col else "Foreign key constraint violated."
        expected = f"A valid foreign key that exists in {parent_tbl}."
        suggested = f"Load the required parent records in '{parent_tbl}' first or correct '{col}'."

    elif 'violates unique constraint' in err_str:
        key_match = re.search(r'Key \(([^)]+)\)=\(([^)]+)\)', err_str)
        if key_match:
            col = key_match.group(1)
            val = key_match.group(2)
        err_type = "unique_constraint_violation"
        problem = f"Duplicate value '{val}' violates unique constraint on column '{col}'." if col else "Unique constraint violated."
        expected = f"Unique value for column '{col}'."
        suggested = f"Ensure all records have distinct '{col}' values."

    elif 'violates check constraint' in err_str:
        chk_match = re.search(r'constraint "([^"]+)"', err_str)
        chk_name = chk_match.group(1) if chk_match else "check constraint"
        err_type = "check_constraint_violation"
        problem = f"Value violates check constraint '{chk_name}'."
        expected = "Value satisfying constraint criteria."
        suggested = "Ensure data meets table check constraints (e.g. ratings between 1 and 5)."

    else:
        col_match = re.search(r'column "([^"]+)"', err_str)
        if col_match:
            col = col_match.group(1)
        problem = err_str.strip().split('\n')[0]
        suggested = "Review dataset column types and constraints against schema."

    # Try to locate exact CSV row number if dataframe is available
    if df is not None and col is not None and val is not None and col in df.columns:
        try:
            matches = df[df[col].astype(str) == str(val)].index
            if len(matches) > 0:
                row = matches[0] + 2
        except Exception:
            pass

    return StructuredValidationError(
        dataset=TABLE_SCHEMAS.get(tbl, {}).get("label", tbl),
        file=fn,
        target_table=f"public.{tbl}",
        row=row,
        column=col,
        value=val,
        problem=problem,
        expected=expected,
        suggested_action=suggested,
        error_type=err_type,
        technical_details=err_str
    )


# ============================================================
# 7. MAIN VALIDATION WORKFLOW
# Validates CSV content, normalizes records, and checks constraints.
# ============================================================

def validate_csv_content(
    file_bytes: bytes,
    filename: str,
    dataset_type: Optional[str] = None,
    custom_mappings: Optional[Dict[str, str]] = None,
    default_values: Optional[Dict[str, Any]] = None,
    import_mode: str = "upsert"
) -> Tuple[bool, Optional[pd.DataFrame], Optional[str], List[Dict[str, Any]], List[str], Dict[str, Any]]:
    """
    Strictly validates and normalizes an uploaded CSV file against the target schema.
    Supports controlled schema-adaptation (aliases, composite name splitting, and user default values).
    
    Returns:
        (is_valid, normalized_dataframe, table_name, structured_errors, warnings, metadata)
    """
    structured_errors: List[Dict[str, Any]] = []
    warnings: List[str] = []
    metadata: Dict[str, Any] = {
        "filename": filename,
        "dataset_type": dataset_type,
        "validation_state": "INVALID",
        "detection_info": None,
        "mapping_info": None,
        "row_count": 0,
        "columns": [],
        "extra_columns": []
    }

    # 1. Check basic file validity
    if not filename.lower().endswith(".csv"):
        err = StructuredValidationError(
            dataset=dataset_type or "Unknown",
            file=filename,
            target_table="unknown",
            problem=f"Invalid file format for '{filename}'. Only CSV files (.csv) are supported.",
            error_type="invalid_file_format",
            suggested_action="Upload a valid .csv file."
        )
        structured_errors.append(err.to_dict())
        return False, None, None, structured_errors, warnings, metadata

    if not file_bytes or len(file_bytes.strip()) == 0:
        metadata["validation_state"] = "EMPTY_CSV"
        err = StructuredValidationError(
            dataset=dataset_type or "Unknown",
            file=filename,
            target_table="unknown",
            problem=f"Uploaded file '{filename}' is empty (0 bytes).",
            error_type="empty_file",
            suggested_action="Ensure the CSV file contains a header row and data records."
        )
        structured_errors.append(err.to_dict())
        return False, None, None, structured_errors, warnings, metadata

    # 2. Parse raw CSV into DataFrame
    try:
        raw_df = pd.read_csv(io.BytesIO(file_bytes), dtype=object)
    except Exception as e:
        metadata["validation_state"] = "CSV_PARSE_FAILED"
        err = StructuredValidationError(
            dataset=dataset_type or "Unknown",
            file=filename,
            target_table="unknown",
            problem=f"Failed to parse CSV in '{filename}': {str(e)}",
            error_type="csv_syntax_error",
            suggested_action="Verify that the CSV file syntax, quoting, and delimiters are valid."
        )
        structured_errors.append(err.to_dict())
        return False, None, None, structured_errors, warnings, metadata

    if raw_df.empty:
        metadata["validation_state"] = "EMPTY_CSV"
        err = StructuredValidationError(
            dataset=dataset_type or "Unknown",
            file=filename,
            target_table="unknown",
            problem=f"CSV file '{filename}' contains 0 data rows.",
            error_type="empty_dataframe",
            suggested_action="Provide a CSV file with at least one record."
        )
        structured_errors.append(err.to_dict())
        return False, None, None, structured_errors, warnings, metadata

    uploaded_cols = list(raw_df.columns)
    metadata["row_count"] = len(raw_df)
    metadata["columns"] = uploaded_cols

    # 3. Handle Auto-Detection or Selected Dataset Type
    table_name = (dataset_type or "").lower().strip()
    if not table_name or table_name == "auto" or table_name == "auto_detect":
        detection = detect_dataset_from_headers(uploaded_cols)
        metadata["detection_info"] = detection
        if not detection["detected_dataset"]:
            err = StructuredValidationError(
                dataset="Unknown",
                file=filename,
                target_table="unknown",
                problem="Could not automatically detect a supported dataset type (Users, Vehicles, Rides, Payments, Ratings) from the CSV headers.",
                error_type="unsupported_dataset",
                suggested_action="Please manually select the target Dataset Type or verify header names."
            )
            structured_errors.append(err.to_dict())
            metadata["validation_state"] = "UNSUPPORTED_DATASET"
            return False, None, None, structured_errors, warnings, metadata
        table_name = detection["detected_dataset"]

    if table_name not in TABLE_SCHEMAS:
        err = StructuredValidationError(
            dataset=dataset_type or "Unknown",
            file=filename,
            target_table="unknown",
            problem=f"Unsupported dataset type '{dataset_type}'. Supported types: Users, Vehicles, Rides, Payments, Ratings.",
            error_type="unsupported_dataset",
            suggested_action="Select one of the 5 supported dataset types."
        )
        structured_errors.append(err.to_dict())
        metadata["validation_state"] = "UNSUPPORTED_DATASET"
        return False, None, None, structured_errors, warnings, metadata

    schema = TABLE_SCHEMAS[table_name]
    target_table = schema["target_table"]
    dataset_label = schema["label"]
    pk = schema["primary_key"]
    columns_spec = schema["columns"]
    req_cols = schema["required_columns"]

    # 4. Map Columns
    mapping_res = map_columns_to_schema(uploaded_cols, table_name, custom_mappings=custom_mappings)
    metadata["mapping_info"] = mapping_res
    col_map = mapping_res["mapped_columns"]  # uploaded -> canonical
    extra_cols = mapping_res["extra_columns"]
    missing_req = mapping_res["missing_required"]

    if extra_cols:
        metadata["extra_columns"] = extra_cols
        warnings.append(
            f"Additional columns detected: {', '.join(extra_cols)}. "
            f"These columns are not part of the {dataset_label} schema and will not be loaded into PostgreSQL."
        )

    # 5. Check Missing Required Columns and evaluate Default Values
    clean_defaults = {normalize_header_name(k): v for k, v in (default_values or {}).items() if v is not None and str(v).strip()}
    unresolved_missing = []

    for req_c in missing_req:
        if req_c in clean_defaults:
            val = clean_defaults[req_c]
            warnings.append(
                f"Applied user-configured default value '{val}' to required column '{req_c}' for all {len(raw_df)} records."
            )
        else:
            unresolved_missing.append(req_c)

    if unresolved_missing:
        err = StructuredValidationError(
            dataset=dataset_label,
            file=filename,
            target_table=target_table,
            problem=f"Missing required column(s): {', '.join(unresolved_missing)}",
            error_type="missing_required_column",
            expected=f"All required columns present: {', '.join(req_cols)}",
            suggested_action=f"Add the required column(s) ({', '.join(unresolved_missing)}) or provide a valid column mapping/default value."
        )
        structured_errors.append(err.to_dict())
        metadata["validation_state"] = "INVALID"
        metadata["missing_required"] = unresolved_missing
        return False, None, table_name, structured_errors, warnings, metadata

    # 6. Build Normalized Canonical Records via Schema Adaptation Layer
    composite_cols = mapping_res.get("composite_columns", {})
    raw_records = raw_df.to_dict(orient="records")
    canonical_raw_records: List[Dict[str, Any]] = []

    # Map uploaded column to canonical column for 1-to-1 mappings
    one_to_one_map: Dict[str, str] = {
        upl: can for upl, can in col_map.items() if upl not in composite_cols
    }

    for raw_row in raw_records:
        canon_row: Dict[str, Any] = {}

        # 1. Apply 1-to-1 mappings
        for upl_col, can_col in one_to_one_map.items():
            if can_col in columns_spec:
                canon_row[can_col] = raw_row.get(upl_col)

        # 2. Apply composite mappings (e.g. name -> first_name, last_name)
        for upl_col, target_cols in composite_cols.items():
            raw_val = raw_row.get(upl_col)
            if table_name == "users" and target_cols == ["first_name", "last_name"]:
                fn, ln = split_full_name(raw_val)
                # Exact / 1-to-1 matches take precedence over composite parts
                if "first_name" not in canon_row or is_null_or_empty(canon_row.get("first_name")):
                    canon_row["first_name"] = fn
                if "last_name" not in canon_row or is_null_or_empty(canon_row.get("last_name")):
                    canon_row["last_name"] = ln

        # 3. For any canonical columns not present in uploaded CSV:
        for can_col, col_spec in columns_spec.items():
            if can_col not in canon_row or is_null_or_empty(canon_row.get(can_col)):
                if can_col in clean_defaults:
                    canon_row[can_col] = clean_defaults[can_col]
                else:
                    canon_row[can_col] = None

        canonical_raw_records.append(canon_row)

    # Check for Duplicate Primary Keys in Canonical Records
    pk_values = [r.get(pk) for r in canonical_raw_records if not is_null_or_empty(r.get(pk))]
    seen_pks = set()
    dup_pks = set()
    for v in pk_values:
        str_v = str(v).strip()
        if str_v in seen_pks:
            dup_pks.add(str_v)
        seen_pks.add(str_v)

    if dup_pks:
        sample_dup = list(dup_pks)[0]
        dup_rows = [i + 2 for i, r in enumerate(canonical_raw_records) if str(r.get(pk)).strip() == sample_dup]
        err = StructuredValidationError(
            dataset=dataset_label,
            file=filename,
            target_table=target_table,
            row=dup_rows[0] if dup_rows else None,
            column=pk,
            value=str(sample_dup),
            problem=f"Duplicate primary key value '{sample_dup}' found {len(dup_rows)} times in uploaded file.",
            error_type="duplicate_primary_key",
            expected=f"Unique '{pk}' value for every row.",
            suggested_action=f"Ensure primary key column '{pk}' has unique values for all rows in {filename}."
        )
        structured_errors.append(err.to_dict())

    # 7. Row-by-Row Value Normalization & Type Checking
    max_row_errors = 25  # Limit error accumulation for giant CSVs
    error_count = len(structured_errors)
    normalized_records = []

    for row_idx, canon_row in enumerate(canonical_raw_records):
        csv_row_num = row_idx + 2  # 1-indexed data row in CSV (row 1 is header)
        cleaned_row_dict: Dict[str, Any] = {}

        for can_col, col_spec in columns_spec.items():
            raw_val = canon_row.get(can_col)
            col_type = col_spec.get("type", "str")
            is_nullable = col_spec.get("nullable", True)
            is_req = col_spec.get("required", False)

            # Check if null in required / non-nullable column
            if is_null_or_empty(raw_val):
                if is_req or not is_nullable:
                    if error_count < max_row_errors:
                        err = StructuredValidationError(
                            dataset=dataset_label,
                            file=filename,
                            target_table=target_table,
                            row=csv_row_num,
                            column=can_col,
                            value=str(raw_val),
                            problem=f"Required column '{can_col}' contains a missing/null value.",
                            error_type="null_required_value",
                            expected=f"Non-empty {col_type} value.",
                            suggested_action=f"Provide a non-empty value for required column '{can_col}'."
                        )
                        structured_errors.append(err.to_dict())
                        error_count += 1
                    cleaned_row_dict[can_col] = None
                    continue
                else:
                    cleaned_row_dict[can_col] = None
                    continue

            # Deterministic type normalization
            is_valid, norm_val, type_err = normalize_value_by_type(
                raw_val,
                col_type=col_type,
                nullable=is_nullable,
                meta=col_spec
            )

            if not is_valid:
                if error_count < max_row_errors:
                    err_type_name = f"invalid_{col_type}"
                    if col_type == "timestamp":
                        exp_str = "A valid timestamp such as '2026-02-27 20:13:30'"
                        sugg_str = "Convert timestamp to 'YYYY-MM-DD HH:MM:SS' or leave empty if nullable."
                    elif col_type == "date":
                        exp_str = "A valid date such as '2026-02-27'"
                        sugg_str = "Convert date to 'YYYY-MM-DD' or leave empty if nullable."
                    elif col_type == "int":
                        exp_str = "A whole integer number"
                        sugg_str = f"Ensure column '{can_col}' contains integer values without decimals."
                    elif col_type == "decimal":
                        exp_str = "A valid numeric/decimal value"
                        sugg_str = f"Ensure column '{can_col}' contains numeric values (e.g. 12.50)."
                    elif col_type == "bool":
                        exp_str = "A boolean value ('true' or 'false')"
                        sugg_str = f"Use true/false or 1/0 for boolean column '{can_col}'."
                    else:
                        exp_str = f"Valid {col_type} value"
                        sugg_str = f"Provide a valid value for column '{can_col}'."

                    err = StructuredValidationError(
                        dataset=dataset_label,
                        file=filename,
                        target_table=target_table,
                        row=csv_row_num,
                        column=can_col,
                        value=str(raw_val),
                        problem=f"Invalid {col_type} value in column '{can_col}': '{raw_val}'. {type_err or ''}".strip(),
                        error_type=err_type_name,
                        expected=exp_str,
                        suggested_action=sugg_str
                    )
                    structured_errors.append(err.to_dict())
                    error_count += 1
                cleaned_row_dict[can_col] = None
            else:
                cleaned_row_dict[can_col] = norm_val

        normalized_records.append(cleaned_row_dict)

    # 8. Check Existing Primary Keys in Database (if Append mode or info)
    norm_df = pd.DataFrame(normalized_records)
    if pk in norm_df.columns and not structured_errors:
        valid_pks = [v for v in norm_df[pk] if v is not None]
        if valid_pks:
            try:
                db_conn = DatabaseConnection()
                conn = db_conn.get_connection()
                if conn:
                    with conn.cursor() as cur:
                        # Check existence in chunks to avoid parameter limits
                        sample_pks = tuple(valid_pks[:1000])
                        if len(sample_pks) == 1:
                            query = sql.SQL("SELECT {} FROM {} WHERE {} = %s").format(
                                sql.Identifier(pk),
                                sql.Identifier("public", table_name),
                                sql.Identifier(pk)
                            )
                            cur.execute(query, (sample_pks[0],))
                        else:
                            query = sql.SQL("SELECT {} FROM {} WHERE {} IN %s").format(
                                sql.Identifier(pk),
                                sql.Identifier("public", table_name),
                                sql.Identifier(pk)
                            )
                            cur.execute(query, (sample_pks,))
                        existing_rows = cur.fetchall()
                        existing_pks = [r[0] for r in existing_rows]

                        if existing_pks:
                            if import_mode == "append":
                                first_exist = existing_pks[0]
                                err = StructuredValidationError(
                                    dataset=dataset_label,
                                    file=filename,
                                    target_table=target_table,
                                    column=pk,
                                    value=str(first_exist),
                                    problem=f"Primary key '{first_exist}' already exists in {target_table} (Append mode prohibits existing PKs).",
                                    error_type="existing_primary_key",
                                    expected="Unique new primary key values not already in the database.",
                                    suggested_action="Use 'Upsert' mode to update existing records, or remove duplicate PKs."
                                )
                                structured_errors.append(err.to_dict())
                            elif import_mode == "replace":
                                warnings.append(
                                    f"{len(existing_pks)} existing record(s) in {target_table} will be cleared and replaced with uploaded dataset (Replace mode)."
                                )
                            else:
                                warnings.append(
                                    f"{len(existing_pks)} record(s) already exist in {target_table} and will be updated (Upsert mode)."
                                )
            except Exception as e:
                # Non-blocking DB check warning
                warnings.append(f"Database pre-check note: {str(e)}")

    is_valid = len(structured_errors) == 0
    if is_valid:
        metadata["validation_state"] = "VALID_WITH_WARNINGS" if warnings else "VALID"
    else:
        metadata["validation_state"] = "INVALID"

    return is_valid, norm_df if is_valid else None, table_name, structured_errors, warnings, metadata


# ============================================================
# 8. BATCH FOREIGN KEY VALIDATION
# Validates parent-child foreign key integrity across batch & database.
# ============================================================

def validate_batch_foreign_keys(
    datasets: Dict[str, pd.DataFrame],
    session_id: Optional[str] = None
) -> Tuple[bool, List[Dict[str, Any]], List[str]]:
    """
    Validates foreign key integrity across a batch of uploaded datasets and live PostgreSQL.
    Supports session-isolated parent schemas when session_id is provided.
    Returns:
        (is_valid, structured_errors, warnings)
    """
    structured_errors: List[Dict[str, Any]] = []
    warnings: List[str] = []

    # 1. Collect all primary keys available inside current batch
    batch_ids: Dict[str, Set[Any]] = {}
    for tbl, df in datasets.items():
        if tbl in TABLE_SCHEMAS:
            pk = TABLE_SCHEMAS[tbl]["primary_key"]
            if pk in df.columns:
                batch_ids[tbl] = set(df[pk].dropna().tolist())

    # 2. Check each dataset against batch + database
    db_conn = None
    conn = None
    session_tables = set()
    session_schema = get_session_schema_name(session_id)
    try:
        db_conn = DatabaseConnection()
        conn = db_conn.get_connection()
        if session_schema and db_conn:
            session_tables = db_conn.get_session_tables(session_id)
    except Exception:
        pass

    for tbl, df in datasets.items():
        if tbl not in TABLE_SCHEMAS:
            continue
        schema = TABLE_SCHEMAS[tbl]
        target_table = schema["target_table"]
        dataset_label = schema["label"]
        fk_rules = schema.get("foreign_keys", {})

        for fk_col, (parent_tbl, parent_pk) in fk_rules.items():
            if fk_col not in df.columns:
                continue

            # Non-null values present in child dataset
            child_fk_values = set(df[fk_col].dropna().tolist())
            if not child_fk_values:
                continue

            available_parent_ids = set()
            if parent_tbl in batch_ids:
                available_parent_ids.update(batch_ids[parent_tbl])

            # Determine parent schema (session schema if parent table exists there, otherwise public)
            parent_schema = session_schema if (session_schema and parent_tbl in session_tables) else "public"

            # Query database for parent IDs not found in batch
            remaining_to_check = child_fk_values - available_parent_ids
            if remaining_to_check and conn:
                try:
                    with conn.cursor() as cur:
                        chunk = tuple(list(remaining_to_check)[:1000])
                        if len(chunk) == 1:
                            q = sql.SQL("SELECT {} FROM {}.{} WHERE {} = %s").format(
                                sql.Identifier(parent_pk),
                                sql.Identifier(parent_schema),
                                sql.Identifier(parent_tbl),
                                sql.Identifier(parent_pk)
                            )
                            cur.execute(q, (chunk[0],))
                        else:
                            q = sql.SQL("SELECT {} FROM {}.{} WHERE {} IN %s").format(
                                sql.Identifier(parent_pk),
                                sql.Identifier(parent_schema),
                                sql.Identifier(parent_tbl),
                                sql.Identifier(parent_pk)
                            )
                            cur.execute(q, (chunk,))
                        db_parent_ids = {r[0] for r in cur.fetchall()}
                        available_parent_ids.update(db_parent_ids)
                except Exception as e:
                    warnings.append(f"Could not verify foreign keys in database for '{parent_tbl}': {str(e)}")

            # Check if any child records are missing parent
            missing_ids = child_fk_values - available_parent_ids
            if missing_ids:
                first_missing = list(missing_ids)[0]
                # Find exact row number
                matching_rows = df[df[fk_col] == first_missing].index
                row_num = matching_rows[0] + 2 if len(matching_rows) > 0 else None

                err = StructuredValidationError(
                    dataset=dataset_label,
                    file=f"{tbl}.csv",
                    target_table=target_table,
                    row=row_num,
                    column=fk_col,
                    value=str(first_missing),
                    problem=f"No matching {parent_pk} exists in {parent_schema}.{parent_tbl}.",
                    error_type="foreign_key_validation_failed",
                    expected=f"A valid parent record in {parent_schema}.{parent_tbl} with {parent_pk} = {first_missing}.",
                    suggested_action=f"Load the required parent record into {parent_tbl} first or correct the {fk_col} value."
                )
                structured_errors.append(err.to_dict())

    return len(structured_errors) == 0, structured_errors, warnings


def relink_session_foreign_keys(cursor, target_schema: str) -> None:
    """
    Ensures all foreign key relationships in target_schema point to session parent tables
    if the parent exists in target_schema, otherwise referencing public.<parent>.
    """
    if not target_schema or target_schema == "public":
        return

    cursor.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s;",
        (target_schema,)
    )
    existing_session_tables = {r[0] for r in cursor.fetchall()}

    for tbl, schema_spec in TABLE_SCHEMAS.items():
        if tbl not in existing_session_tables:
            continue
        fk_rules = schema_spec.get("foreign_keys", {})
        for fk_col, (parent_tbl, parent_pk) in fk_rules.items():
            parent_schema = target_schema if parent_tbl in existing_session_tables else "public"
            fk_name = f"fk_{target_schema}_{tbl}_{fk_col}"[:63]

            # Drop existing constraint if already present
            cursor.execute(sql.SQL("""
                ALTER TABLE {}.{} DROP CONSTRAINT IF EXISTS {};
            """).format(
                sql.Identifier(target_schema),
                sql.Identifier(tbl),
                sql.Identifier(fk_name)
            ))

            # Add updated foreign key constraint
            try:
                cursor.execute(sql.SQL("""
                    ALTER TABLE {}.{} 
                    ADD CONSTRAINT {} 
                    FOREIGN KEY ({}) REFERENCES {}.{}({}) 
                    ON DELETE CASCADE;
                """).format(
                    sql.Identifier(target_schema),
                    sql.Identifier(tbl),
                    sql.Identifier(fk_name),
                    sql.Identifier(fk_col),
                    sql.Identifier(parent_schema),
                    sql.Identifier(parent_tbl),
                    sql.Identifier(parent_pk)
                ))
            except Exception:
                pass


# ============================================================
# 9. ATOMIC TRANSACTIONAL DATABASE LOADER
# Loads validated datasets into PostgreSQL inside a single atomic transaction.
# Supports session-isolated dataset schemas.
# ============================================================

def load_datasets_transactional(
    datasets: Dict[str, pd.DataFrame],
    import_mode: str = "upsert",
    session_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Loads validated datasets into PostgreSQL inside a single atomic transaction.
    Enforces strict dependency order:
    1. users
    2. vehicles
    3. rides
    4. payments
    5. ratings

    If session_id is provided, data is written into an isolated session schema
    (e.g. session_<safe_id>), protecting the public base dataset from corruption or leakage.
    If any table or row fails, the entire transaction is rolled back immediately.
    """
    if not datasets:
        return {
            "success": False,
            "error": "No datasets provided for loading.",
            "errors": ["No datasets provided for loading."],
            "loaded_counts": {}
        }

    # Sort tables by topological dependency load order
    sorted_tables = sorted(
        datasets.keys(),
        key=lambda tbl: TABLE_SCHEMAS.get(tbl, {}).get("load_order", 99)
    )

    target_schema = get_session_schema_name(session_id) or "public"
    is_session_scoped = (target_schema != "public")

    db_config = get_db_config()
    conn = None
    cursor = None
    loaded_counts: Dict[str, int] = {}
    current_loading_table = None

    try:
        conn = psycopg2.connect(**db_config)
        conn.autocommit = False  # Start single atomic transaction
        cursor = conn.cursor()

        # Ensure session schema exists if session scoped
        if is_session_scoped:
            cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {};").format(
                sql.Identifier(target_schema)
            ))

        # Handle 'replace' mode
        if import_mode == "replace":
            for tbl in reversed(sorted_tables):
                if is_session_scoped:
                    # Check if table already exists in session schema
                    cursor.execute(
                        "SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s;",
                        (target_schema, tbl)
                    )
                    if cursor.fetchone():
                        cursor.execute(sql.SQL("TRUNCATE TABLE {}.{} CASCADE;").format(
                            sql.Identifier(target_schema),
                            sql.Identifier(tbl)
                        ))
                    else:
                        cursor.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {}.{} (LIKE public.{} INCLUDING ALL);").format(
                            sql.Identifier(target_schema),
                            sql.Identifier(tbl),
                            sql.Identifier(tbl)
                        ))
                else:
                    cursor.execute(sql.SQL("TRUNCATE TABLE {}.{} CASCADE;").format(
                        sql.Identifier("public"),
                        sql.Identifier(tbl)
                    ))

        for tbl in sorted_tables:
            current_loading_table = tbl
            df = datasets[tbl]
            schema = TABLE_SCHEMAS[tbl]
            pk = schema["primary_key"]
            all_cols = list(schema["columns"].keys())
            columns_spec = schema["columns"]

            # Filter DataFrame to valid table columns present in data
            load_cols = [c for c in all_cols if c in df.columns]
            if not load_cols:
                raise ValueError(f"No valid columns found to load for table '{tbl}'.")

            # For session-isolated append/upsert, clone base table from public if not yet in session schema
            if is_session_scoped and import_mode in ("append", "upsert"):
                cursor.execute(
                    "SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s;",
                    (target_schema, tbl)
                )
                if not cursor.fetchone():
                    cursor.execute(sql.SQL("CREATE TABLE {}.{} (LIKE public.{} INCLUDING ALL);").format(
                        sql.Identifier(target_schema),
                        sql.Identifier(tbl),
                        sql.Identifier(tbl)
                    ))
                    cursor.execute(sql.SQL("INSERT INTO {}.{} SELECT * FROM public.{};").format(
                        sql.Identifier(target_schema),
                        sql.Identifier(tbl),
                        sql.Identifier(tbl)
                    ))

            # Clean and prepare records with strict type adaptation for PostgreSQL
            records = []
            for row_idx, row in enumerate(df.to_dict(orient="records")):
                csv_row_num = row_idx + 2
                cleaned_row = []
                for c in load_cols:
                    raw_val = row[c]
                    col_spec = columns_spec.get(c, {})
                    col_type = col_spec.get("type", "str")
                    is_nullable = col_spec.get("nullable", True)

                    # Strict normalization before SQL execution
                    is_valid, norm_val, err_msg = normalize_value_by_type(
                        raw_val,
                        col_type=col_type,
                        nullable=is_nullable,
                        meta=col_spec
                    )

                    if not is_valid:
                        raise ValueError(format_import_error(
                            dataset=schema["label"],
                            file=f"{tbl}.csv",
                            target_table=f"{target_schema}.{tbl}",
                            column=c,
                            row=csv_row_num,
                            value=str(raw_val),
                            problem=err_msg or f"Invalid {col_type} value",
                            suggested_action=f"Provide a valid {col_type} value for column '{c}'."
                        ))

                    cleaned_row.append(norm_val)
                records.append(cleaned_row)

            if not records:
                continue

            # Build query based on import_mode
            cols_str = ", ".join([f'"{c}"' for c in load_cols])

            if import_mode == "append":
                insert_query = f"""
                    INSERT INTO {target_schema}.{tbl} ({cols_str})
                    VALUES %s;
                """
            else:
                # Upsert mode (default) / Replace mode
                update_cols = [c for c in load_cols if c != pk]
                if update_cols:
                    update_str = ", ".join([f'"{c}" = EXCLUDED."{c}"' for c in update_cols])
                    conflict_clause = f'ON CONFLICT ("{pk}") DO UPDATE SET {update_str}'
                else:
                    conflict_clause = f'ON CONFLICT ("{pk}") DO NOTHING'

                insert_query = f"""
                    INSERT INTO {target_schema}.{tbl} ({cols_str})
                    VALUES %s
                    {conflict_clause};
                """

            execute_values(cursor, insert_query, records, page_size=1000)
            loaded_counts[tbl] = len(records)

        # Ensure session foreign key constraints point to session parent tables when present
        if is_session_scoped:
            relink_session_foreign_keys(cursor, target_schema)

        # Commit all table inserts and constraint updates atomically
        conn.commit()

        return {
            "success": True,
            "message": f"All datasets loaded successfully into PostgreSQL ({target_schema}).",
            "loaded_counts": loaded_counts,
            "session_id": session_id,
            "schema": target_schema
        }

    except Exception as e:
        if conn:
            try:
                conn.rollback()  # Rollback entire transaction
            except Exception:
                pass

        err_msg = str(e)
        tbl_name = current_loading_table or "unknown"
        structured_err = parse_postgres_error_details(
            err_msg,
            tbl_name,
            datasets.get(tbl_name) if datasets else None,
            filename=f"{tbl_name}.csv"
        )

        formatted_err_str = structured_err.to_formatted_string()

        return {
            "success": False,
            "error": formatted_err_str,
            "structured_error": structured_err.to_dict(),
            "technical_error": err_msg,
            "errors": [formatted_err_str],
            "loaded_counts": {}
        }

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

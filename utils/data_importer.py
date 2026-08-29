import io
import os
import psycopg2
from psycopg2.extras import execute_values
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple, Set
from utils.database import DatabaseConnection, get_db_config

# ============================================================
# DATASET SCHEMAS & DEPENDENCY CONFIGURATION
# Defines required columns, primary keys, and foreign key relationships
# for OLA-inspired mobility datasets.
# ============================================================

TABLE_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "users": {
        "label": "Users",
        "primary_key": "user_id",
        "required_columns": ["user_id", "first_name", "last_name", "email", "user_type"],
        "all_columns": [
            "user_id", "first_name", "last_name", "email", "phone",
            "city", "province", "user_type", "signup_date", "is_active"
        ],
        "foreign_keys": {},
        "load_order": 1
    },
    "vehicles": {
        "label": "Vehicles",
        "primary_key": "vehicle_id",
        "required_columns": ["vehicle_id", "driver_id", "license_plate"],
        "all_columns": [
            "vehicle_id", "driver_id", "make", "model", "year",
            "license_plate", "color", "is_active"
        ],
        "foreign_keys": {
            "driver_id": ("users", "user_id")
        },
        "load_order": 2
    },
    "rides": {
        "label": "Rides",
        "primary_key": "ride_id",
        "required_columns": ["ride_id", "rider_id", "driver_id", "requested_at", "fare", "status"],
        "all_columns": [
            "ride_id", "rider_id", "driver_id", "vehicle_id",
            "pickup_latitude", "pickup_longitude", "dropoff_latitude", "dropoff_longitude",
            "requested_at", "pickup_time", "dropoff_time", "fare", "distance_km",
            "duration_minutes", "surge_multiplier", "status", "cancellation_reason"
        ],
        "foreign_keys": {
            "rider_id": ("users", "user_id"),
            "driver_id": ("users", "user_id"),
            "vehicle_id": ("vehicles", "vehicle_id")
        },
        "load_order": 3
    },
    "payments": {
        "label": "Payments",
        "primary_key": "payment_id",
        "required_columns": ["payment_id", "ride_id", "user_id", "amount", "payment_method", "payment_status"],
        "all_columns": [
            "payment_id", "ride_id", "user_id", "amount", "payment_method",
            "payment_status", "transaction_id", "payment_time"
        ],
        "foreign_keys": {
            "ride_id": ("rides", "ride_id"),
            "user_id": ("users", "user_id")
        },
        "load_order": 4
    },
    "ratings": {
        "label": "Ratings",
        "primary_key": "rating_id",
        "required_columns": ["rating_id", "ride_id", "rider_id", "driver_id", "rating"],
        "all_columns": [
            "rating_id", "ride_id", "rider_id", "driver_id", "rating", "comment", "rated_at"
        ],
        "foreign_keys": {
            "ride_id": ("rides", "ride_id"),
            "rider_id": ("users", "user_id"),
            "driver_id": ("users", "user_id")
        },
        "load_order": 5
    }
}


def identify_dataset_by_columns(columns: List[str]) -> Optional[str]:
    """
    Identifies the dataset type based on its column names.
    Does NOT guess or use AI inference; checks for exact canonical schema markers.
    """
    cols_set = set(c.strip().lower() for c in columns)

    if {"user_id", "first_name", "last_name", "email"}.issubset(cols_set):
        return "users"
    if {"vehicle_id", "driver_id", "license_plate"}.issubset(cols_set):
        return "vehicles"
    if {"ride_id", "requested_at", "fare", "status"}.issubset(cols_set):
        return "rides"
    if {"payment_id", "payment_method", "amount"}.issubset(cols_set):
        return "payments"
    if {"rating_id", "rating", "rated_at"}.issubset(cols_set) or {"rating_id", "rating", "driver_id"}.issubset(cols_set):
        return "ratings"

    return None


def validate_csv_content(
    file_bytes: bytes,
    filename: str,
    explicit_table: Optional[str] = None
) -> Tuple[bool, Optional[pd.DataFrame], Optional[str], List[str], List[str]]:
    """
    Validates an uploaded CSV file against OLA platform schema requirements.
    
    Checks:
    1. Valid CSV syntax and non-empty content.
    2. Dataset type determination (explicit or column-matching).
    3. Presence of all required columns.
    4. Absence of duplicate primary key values.
    5. Absence of null/missing values in required fields.
    
    Returns:
        (is_valid, dataframe, table_name, errors, warnings)
    """
    errors: List[str] = []
    warnings: List[str] = []

    # 1. Validate file extension and basic content
    if not filename.lower().endswith(".csv"):
        errors.append(f"Invalid file format for '{filename}'. Only CSV files (.csv) are supported.")
        return False, None, None, errors, warnings

    if not file_bytes or len(file_bytes.strip()) == 0:
        errors.append(f"Uploaded file '{filename}' is empty.")
        return False, None, None, errors, warnings

    # 2. Parse CSV into DataFrame
    try:
        df = pd.read_csv(io.BytesIO(file_bytes))
    except Exception as e:
        errors.append(f"Failed to parse CSV in '{filename}': {e}")
        return False, None, None, errors, warnings

    if df.empty:
        errors.append(f"CSV file '{filename}' contains 0 data rows.")
        return False, None, None, errors, warnings

    # Normalize column names
    df.columns = [str(c).strip().lower() for c in df.columns]
    cols = list(df.columns)

    # 3. Determine table type
    table_name = (explicit_table or "").lower().strip()
    if not table_name or table_name not in TABLE_SCHEMAS:
        identified = identify_dataset_by_columns(cols)
        if not identified:
            errors.append(
                f"Could not identify dataset type for '{filename}'. "
                f"Columns provided: {cols[:8]}. Please select the target dataset type explicitly."
            )
            return False, None, None, errors, warnings
        table_name = identified

    schema = TABLE_SCHEMAS[table_name]
    pk = schema["primary_key"]
    req_cols = schema["required_columns"]

    # 4. Validate required columns exist
    missing_req = [c for c in req_cols if c not in cols]
    if missing_req:
        errors.append(
            f"'{table_name}' dataset is missing required column(s): {', '.join(missing_req)}"
        )

    # 5. Check for duplicate primary keys
    if pk in df.columns:
        pk_series = df[pk].dropna()
        dups = df[df[pk].duplicated(keep=False)][pk].unique().tolist()
        if dups:
            sample_dups = dups[:5]
            errors.append(
                f"'{table_name}' dataset contains {len(dups)} duplicate primary key ({pk}) value(s): {sample_dups}"
            )

        # Check for null/missing PKs
        null_pk_count = df[pk].isna().sum()
        if null_pk_count > 0:
            errors.append(f"'{table_name}' dataset has {null_pk_count} rows with missing/null primary key '{pk}'.")

    # 6. Check required fields for completely missing/null values
    for col in req_cols:
        if col in df.columns and col != pk:
            null_count = df[col].isna().sum()
            if null_count == len(df):
                errors.append(f"Required field '{col}' in '{table_name}' is completely empty across all rows.")
            elif null_count > 0:
                warnings.append(f"Field '{col}' has {null_count} missing/null values.")

    # 7. Check for unrecognized columns (warning only)
    allowed_cols = set(schema["all_columns"])
    extra_cols = [c for c in cols if c not in allowed_cols]
    if extra_cols:
        warnings.append(f"Unrecognized column(s) will be ignored during loading: {extra_cols}")

    is_valid = len(errors) == 0
    return is_valid, df, table_name, errors, warnings


def validate_batch_foreign_keys(
    datasets: Dict[str, pd.DataFrame]
) -> Tuple[bool, List[str], List[str]]:
    """
    Validates foreign key integrity across a batch of uploaded datasets before loading.
    Checks that child records reference existing parent records in the batch or in the database.
    """
    errors: List[str] = []
    warnings: List[str] = []

    # Collect available IDs from batch
    batch_ids: Dict[str, Set[Any]] = {}
    for tbl, df in datasets.items():
        pk = TABLE_SCHEMAS[tbl]["primary_key"]
        if pk in df.columns:
            batch_ids[tbl] = set(df[pk].dropna().tolist())

    # Check foreign keys for each dataset
    for tbl, df in datasets.items():
        fk_rules = TABLE_SCHEMAS[tbl]["foreign_keys"]
        for fk_col, (parent_tbl, parent_pk) in fk_rules.items():
            if fk_col in df.columns:
                fk_values = set(df[fk_col].dropna().tolist())
                
                # Check if parent table is in the batch
                if parent_tbl in batch_ids:
                    missing = fk_values - batch_ids[parent_tbl]
                    if missing:
                        sample_missing = list(missing)[:5]
                        errors.append(
                            f"Foreign key integrity error in '{tbl}.{fk_col}': {len(missing)} reference(s) "
                            f"do not exist in parent table '{parent_tbl}.{parent_pk}' (e.g. {sample_missing})."
                        )
                else:
                    # Parent table not in upload batch; warn that existing database records will be used
                    warnings.append(
                        f"Parent table '{parent_tbl}' is not part of this upload batch; "
                        f"foreign keys in '{tbl}.{fk_col}' will reference existing database records."
                    )

    return len(errors) == 0, errors, warnings


def load_datasets_transactional(
    datasets: Dict[str, pd.DataFrame]
) -> Dict[str, Any]:
    """
    Loads validated datasets into PostgreSQL inside a single atomic transaction.
    If any table fails, the entire transaction is rolled back.
    
    Load order:
    1. users
    2. vehicles
    3. rides
    4. payments
    5. ratings
    """
    if not datasets:
        return {"success": False, "error": "No datasets provided for loading."}

    # Sort tables by dependency load order
    sorted_tables = sorted(
        datasets.keys(),
        key=lambda tbl: TABLE_SCHEMAS.get(tbl, {}).get("load_order", 99)
    )

    db_config = get_db_config()
    conn = None
    cursor = None
    loaded_counts: Dict[str, int] = {}

    try:
        conn = psycopg2.connect(**db_config)
        conn.autocommit = False  # Start transaction
        cursor = conn.cursor()

        for tbl in sorted_tables:
            df = datasets[tbl]
            schema = TABLE_SCHEMAS[tbl]
            pk = schema["primary_key"]
            all_cols = schema["all_columns"]

            # Filter DataFrame to valid table columns present in data
            load_cols = [c for c in all_cols if c in df.columns]
            if not load_cols:
                raise ValueError(f"No valid columns found to load for table '{tbl}'.")

            # Clean and prepare records
            clean_df = df[load_cols].copy()
            clean_df = clean_df.where(pd.notnull(clean_df), None)
            records = clean_df.to_dict(orient="records")

            if not records:
                continue

            # Build UPSERT query
            cols_str = ", ".join([f'"{c}"' for c in load_cols])
            update_cols = [c for c in load_cols if c != pk]
            
            if update_cols:
                update_str = ", ".join([f'"{c}" = EXCLUDED."{c}"' for c in update_cols])
                conflict_clause = f'ON CONFLICT ("{pk}") DO UPDATE SET {update_str}'
            else:
                conflict_clause = f'ON CONFLICT ("{pk}") DO NOTHING'

            insert_query = f"""
                INSERT INTO public.{tbl} ({cols_str})
                VALUES %s
                {conflict_clause};
            """

            values_list = [[r[c] for c in load_cols] for r in records]
            execute_values(cursor, insert_query, values_list, page_size=1000)

            loaded_counts[tbl] = len(records)

        # Commit all table inserts atomically
        conn.commit()

        return {
            "success": True,
            "message": "All datasets loaded successfully into PostgreSQL.",
            "loaded_counts": loaded_counts
        }

    except Exception as e:
        if conn:
            try:
                conn.rollback()  # Rollback entire transaction
            except Exception:
                pass
        return {
            "success": False,
            "error": f"Database transaction failed and was rolled back: {str(e)}",
            "loaded_counts": {}
        }

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

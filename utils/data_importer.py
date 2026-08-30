import io
import os
import re
import math
from datetime import datetime, date
import psycopg2
from psycopg2.extras import execute_values
import pandas as pd
import numpy as np
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
        "date_columns": ["signup_date"],
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
        "timestamp_columns": ["requested_at", "pickup_time", "dropoff_time"],
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
        "timestamp_columns": ["payment_time"],
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
        "timestamp_columns": ["rated_at"],
        "foreign_keys": {
            "ride_id": ("rides", "ride_id"),
            "rider_id": ("users", "user_id"),
            "driver_id": ("users", "user_id")
        },
        "load_order": 5
    }
}


def format_import_error(
    dataset: str,
    target_table: Optional[str] = None,
    column: Optional[str] = None,
    row: Optional[Any] = None,
    value: Optional[Any] = None,
    problem: Optional[str] = None,
    suggested_action: Optional[str] = None
) -> str:
    """
    Formats an import error with structured dataset, column, row, value, problem, and suggested action context.
    """
    lines = [f"Dataset: {dataset}"]
    if target_table:
        lines.append(f"Target table: {target_table}")
    if column:
        lines.append(f"Column: {column}")
    if row is not None:
        lines.append(f"Row: {row}")
    if value is not None:
        val_str = str(value)
        if len(val_str) > 80:
            val_str = val_str[:77] + "..."
        lines.append(f"Value: {val_str}")
    if problem:
        lines.append(f"Problem: {problem}")
    if suggested_action:
        lines.append(f"Suggested action: {suggested_action}")
    return "\n".join(lines)


def is_null_or_empty(val: Any) -> bool:
    """
    Checks if a value represents a null, NaN, NaT, or empty missing value.
    """
    if val is None:
        return True
    if isinstance(val, (float, np.floating)) and (math.isnan(val) or pd.isna(val)):
        return True
    if pd.isna(val):
        return True
    if isinstance(val, str):
        if val.strip().lower() in ("", "null", "none", "nan", "nat", "undefined"):
            return True
    return False


def parse_and_validate_timestamp(val: Any) -> Tuple[bool, Optional[datetime]]:
    """
    Validates and parses a value into a Python datetime object or None if missing.
    Returns (is_valid, datetime_obj_or_None).
    """
    if is_null_or_empty(val):
        return True, None
    if isinstance(val, (datetime, pd.Timestamp)):
        return True, val.to_pydatetime() if isinstance(val, pd.Timestamp) else val
    if isinstance(val, date) and not isinstance(val, datetime):
        return True, datetime.combine(val, datetime.min.time())
    if isinstance(val, str):
        s = val.strip()
        if s.lower() in ("", "null", "none", "nan", "nat", "undefined"):
            return True, None
        try:
            dt = pd.to_datetime(s, errors="raise")
            if pd.isna(dt):
                return False, None
            return True, dt.to_pydatetime() if isinstance(dt, pd.Timestamp) else dt
        except Exception:
            return False, None
    return False, None


def parse_and_validate_date(val: Any) -> Tuple[bool, Optional[date]]:
    """
    Validates and parses a value into a Python date object or None if missing.
    Returns (is_valid, date_obj_or_None).
    """
    if is_null_or_empty(val):
        return True, None
    if isinstance(val, (datetime, pd.Timestamp)):
        return True, val.date()
    if isinstance(val, date):
        return True, val
    if isinstance(val, str):
        s = val.strip()
        if s.lower() in ("", "null", "none", "nan", "nat", "undefined"):
            return True, None
        try:
            dt = pd.to_datetime(s, errors="raise")
            if pd.isna(dt):
                return False, None
            return True, dt.date()
        except Exception:
            return False, None
    return False, None


def normalize_generic_value(val: Any) -> Any:
    """
    Converts pandas / numpy NaN / NaT / missing values to Python None
    so PostgreSQL receives SQL NULL instead of 'NaN'::float.
    """
    if val is None:
        return None
    if isinstance(val, (float, np.floating)) and (math.isnan(val) or pd.isna(val)):
        return None
    if pd.isna(val):
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, (np.bool_,)):
        return bool(val)
    if isinstance(val, str) and val.strip().lower() in ("nan", "nat"):
        return None
    return val


def parse_postgres_error_details(
    err_str: str,
    current_tbl: str,
    df: Optional[pd.DataFrame] = None
) -> str:
    """
    Parses a PostgreSQL database error and wraps it in clear application-level context
    identifying the dataset filename, target table, column, row (if known), problem, and suggested action.
    """
    col = None
    row = None
    val = None
    problem = None
    suggested = None

    if 'timestamp without time zone but expression is of type double precision' in err_str or "'NaN'" in err_str:
        col_match = re.search(r'column "([^"]+)"', err_str)
        col = col_match.group(1) if col_match else "pickup_time"
        problem = "missing timestamp value was passed as NaN instead of SQL NULL."
        suggested = "Ensure missing timestamps are represented as Python None (SQL NULL)."
    elif 'violates not-null constraint' in err_str:
        col_match = re.search(r'column "([^"]+)"', err_str)
        col = col_match.group(1) if col_match else None
        problem = f"Column '{col}' contains null values violating NOT NULL constraint." if col else "NOT NULL constraint violated."
        suggested = f"Provide non-empty values for required column '{col}'." if col else "Provide non-empty values for required fields."
    elif 'violates foreign key constraint' in err_str:
        key_match = re.search(r'Key \(([^)]+)\)=\(([^)]+)\)', err_str)
        if key_match:
            col = key_match.group(1)
            val = key_match.group(2)
        problem = f"Referenced {col} value ({val}) does not exist in parent table." if col else "Foreign key constraint violated."
        suggested = f"Ensure all referenced values in column '{col}' exist in parent dataset before importing." if col else "Ensure referenced parent records exist."
    elif 'violates unique constraint' in err_str:
        key_match = re.search(r'Key \(([^)]+)\)=\(([^)]+)\)', err_str)
        if key_match:
            col = key_match.group(1)
            val = key_match.group(2)
        problem = f"Duplicate value ({val}) violates unique constraint on column '{col}'." if col else "Unique constraint violated."
        suggested = f"Ensure all values in column '{col}' are unique." if col else "Ensure unique column values."
    else:
        col_match = re.search(r'column "([^"]+)"', err_str)
        if col_match:
            col = col_match.group(1)
        problem = err_str.strip().split('\n')[0]
        suggested = "Review dataset column types and constraints against schema."

    # If key value was found and dataframe is available, try to locate exact CSV row number (header is row 1)
    if df is not None and col is not None and val is not None and col in df.columns:
        try:
            matches = df[df[col].astype(str) == str(val)].index
            if len(matches) > 0:
                row = matches[0] + 2
        except Exception:
            pass

    return format_import_error(
        dataset=f"{current_tbl}.csv",
        target_table=f"public.{current_tbl}",
        column=col,
        row=row,
        value=val,
        problem=problem,
        suggested_action=suggested
    )


def validate_csv_content(
    file_bytes: bytes,
    filename: str,
    dataset_type: str
) -> Tuple[bool, Optional[pd.DataFrame], Optional[str], List[str], List[str]]:
    """
    Validates an uploaded CSV file strictly against the user-selected dataset type schema.
    No automatic column guessing, AI inference, or filename guessing is performed.
    
    Checks:
    1. Valid CSV syntax and non-empty content.
    2. Validated selection of one of the 5 supported dataset types (Users, Vehicles, Rides, Payments, Ratings).
    3. Presence of all required columns for the selected schema.
    4. Absence of duplicate primary key values.
    5. Absence of null/missing values in required fields.
    6. Correct format for timestamp and date columns (valid datetime strings, or None for nullable fields).
    
    Returns:
        (is_valid, dataframe, table_name, errors, warnings)
    """
    errors: List[str] = []
    warnings: List[str] = []

    # 1. Validate dataset type parameter
    table_name = (dataset_type or "").lower().strip()
    valid_types = list(TABLE_SCHEMAS.keys())
    if not table_name or table_name not in TABLE_SCHEMAS:
        errors.append(format_import_error(
            dataset=filename or "unknown",
            problem=f"Dataset Type selection is required. Please select one of: {', '.join([s['label'] for s in TABLE_SCHEMAS.values()])}.",
            suggested_action="Select a valid dataset type from the dropdown."
        ))
        return False, None, None, errors, warnings

    # 2. Validate file extension and basic content
    if not filename.lower().endswith(".csv"):
        errors.append(format_import_error(
            dataset=filename,
            problem=f"Invalid file format for '{filename}'. Only CSV files (.csv) are supported.",
            suggested_action="Upload a valid .csv file."
        ))
        return False, None, None, errors, warnings

    if not file_bytes or len(file_bytes.strip()) == 0:
        errors.append(format_import_error(
            dataset=filename,
            target_table=f"public.{table_name}",
            problem=f"Uploaded file '{filename}' is empty.",
            suggested_action="Ensure the CSV file contains a header row and data records."
        ))
        return False, None, None, errors, warnings

    # 3. Parse CSV into DataFrame
    try:
        df = pd.read_csv(io.BytesIO(file_bytes))
    except Exception as e:
        errors.append(format_import_error(
            dataset=filename,
            target_table=f"public.{table_name}",
            problem=f"Failed to parse CSV in '{filename}': {e}",
            suggested_action="Verify that the CSV file syntax, quoting, and delimiters are valid."
        ))
        return False, None, None, errors, warnings

    if df.empty:
        errors.append(format_import_error(
            dataset=filename,
            target_table=f"public.{table_name}",
            problem=f"CSV file '{filename}' contains 0 data rows.",
            suggested_action="Provide a CSV file with at least one record."
        ))
        return False, None, None, errors, warnings

    # Normalize column names
    df.columns = [str(c).strip().lower() for c in df.columns]
    cols = list(df.columns)

    schema = TABLE_SCHEMAS[table_name]
    pk = schema["primary_key"]
    req_cols = schema["required_columns"]

    # 4. Validate required columns exist for the selected schema
    missing_req = [c for c in req_cols if c not in cols]
    if missing_req:
        errors.append(format_import_error(
            dataset=filename,
            target_table=f"public.{table_name}",
            problem=f"'{schema['label']}' dataset is missing required column(s): {', '.join(missing_req)}",
            suggested_action=f"Add missing required column(s) ({', '.join(missing_req)}) to the CSV."
        ))

    # 5. Check for duplicate primary keys
    if pk in df.columns:
        pk_series = df[pk].dropna()
        dup_mask = df[pk].duplicated(keep=False)
        if dup_mask.any():
            dup_df = df[dup_mask]
            dups = dup_df[pk].unique().tolist()
            sample_dups = dups[:5]
            dup_rows = [i + 2 for i in dup_df.index[:5]]
            row_str = ", ".join(map(str, dup_rows)) + ("..." if len(dup_df) > 5 else "")
            errors.append(format_import_error(
                dataset=filename,
                target_table=f"public.{table_name}",
                column=pk,
                row=row_str,
                value=f"{sample_dups}",
                problem=f"Contains {len(dups)} duplicate primary key ({pk}) value(s): {sample_dups}",
                suggested_action=f"Ensure primary key column '{pk}' contains unique values for all rows."
            ))

        # Check for null/missing PKs
        null_pk_rows = [i + 2 for i, v in enumerate(df[pk]) if is_null_or_empty(v)]
        if null_pk_rows:
            row_str = ", ".join(map(str, null_pk_rows[:5])) + ("..." if len(null_pk_rows) > 5 else "")
            errors.append(format_import_error(
                dataset=filename,
                target_table=f"public.{table_name}",
                column=pk,
                row=row_str,
                problem=f"Contains {len(null_pk_rows)} row(s) with missing/null primary key '{pk}'.",
                suggested_action=f"Ensure every row has a non-null, unique '{pk}' value."
            ))

    # 6. Check required fields for missing/null values
    for col in req_cols:
        if col in df.columns and col != pk:
            missing_rows = [i + 2 for i, v in enumerate(df[col]) if is_null_or_empty(v)]
            if len(missing_rows) == len(df):
                errors.append(format_import_error(
                    dataset=filename,
                    target_table=f"public.{table_name}",
                    column=col,
                    problem=f"Required field '{col}' in '{table_name}' is completely empty across all rows.",
                    suggested_action=f"Provide non-empty values for required column '{col}'."
                ))
            elif len(missing_rows) > 0:
                row_str = ", ".join(map(str, missing_rows[:5])) + ("..." if len(missing_rows) > 5 else "")
                errors.append(format_import_error(
                    dataset=filename,
                    target_table=f"public.{table_name}",
                    column=col,
                    row=row_str,
                    problem=f"Required field '{col}' contains {len(missing_rows)} missing/null value(s).",
                    suggested_action=f"Ensure required column '{col}' is populated for all rows."
                ))

    # 7. Validate timestamp columns format
    timestamp_cols = schema.get("timestamp_columns", [])
    for col in timestamp_cols:
        if col in df.columns:
            invalid_rows = []
            for i, v in enumerate(df[col]):
                is_valid_ts, _ = parse_and_validate_timestamp(v)
                if not is_valid_ts:
                    invalid_rows.append((i + 2, v))
            if invalid_rows:
                first_row, first_val = invalid_rows[0]
                row_str = f"{first_row}" if len(invalid_rows) == 1 else f"{first_row} (and {len(invalid_rows)-1} other rows)"
                errors.append(format_import_error(
                    dataset=filename,
                    target_table=f"public.{table_name}",
                    column=col,
                    row=row_str,
                    value=str(first_val),
                    problem=f"Expected valid timestamp format (e.g. 'YYYY-MM-DD HH:MM:SS') but received invalid timestamp value(s).",
                    suggested_action="Convert timestamp strings to standard 'YYYY-MM-DD HH:MM:SS' format or leave empty for SQL NULL."
                ))

    # 8. Validate date columns format
    date_cols = schema.get("date_columns", [])
    for col in date_cols:
        if col in df.columns:
            invalid_rows = []
            for i, v in enumerate(df[col]):
                is_valid_d, _ = parse_and_validate_date(v)
                if not is_valid_d:
                    invalid_rows.append((i + 2, v))
            if invalid_rows:
                first_row, first_val = invalid_rows[0]
                row_str = f"{first_row}" if len(invalid_rows) == 1 else f"{first_row} (and {len(invalid_rows)-1} other rows)"
                errors.append(format_import_error(
                    dataset=filename,
                    target_table=f"public.{table_name}",
                    column=col,
                    row=row_str,
                    value=str(first_val),
                    problem=f"Expected valid date format (e.g. 'YYYY-MM-DD') but received invalid date value(s).",
                    suggested_action="Convert date strings to 'YYYY-MM-DD' format or leave empty for SQL NULL."
                ))

    # 9. Check for unrecognized columns (warning only)
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
                        errors.append(format_import_error(
                            dataset=f"{tbl}.csv",
                            target_table=f"public.{tbl}",
                            column=fk_col,
                            value=f"{sample_missing}",
                            problem=f"Foreign key integrity error: {len(missing)} reference(s) do not exist in parent dataset '{parent_tbl}.csv' (table 'public.{parent_tbl}', column '{parent_pk}').",
                            suggested_action=f"Ensure all {fk_col} values in {tbl}.csv correspond to existing {parent_pk} records in {parent_tbl}.csv before uploading."
                        ))
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
    current_loading_table = None

    try:
        conn = psycopg2.connect(**db_config)
        conn.autocommit = False  # Start transaction
        cursor = conn.cursor()

        for tbl in sorted_tables:
            current_loading_table = tbl
            df = datasets[tbl]
            schema = TABLE_SCHEMAS[tbl]
            pk = schema["primary_key"]
            all_cols = schema["all_columns"]

            # Filter DataFrame to valid table columns present in data
            load_cols = [c for c in all_cols if c in df.columns]
            if not load_cols:
                raise ValueError(format_import_error(
                    dataset=f"{tbl}.csv",
                    target_table=f"public.{tbl}",
                    problem=f"No valid columns found to load for table '{tbl}'.",
                    suggested_action="Ensure the dataset has valid columns corresponding to the schema."
                ))

            timestamp_cols = set(schema.get("timestamp_columns", []))
            date_cols = set(schema.get("date_columns", []))
            req_cols = set(schema.get("required_columns", []))

            # Clean and prepare records with strict type adaptation for PostgreSQL
            records = []
            for row_idx, row in enumerate(df[load_cols].to_dict(orient="records")):
                cleaned_row = []
                for c in load_cols:
                    val = row[c]
                    if c in timestamp_cols:
                        is_valid, dt_val = parse_and_validate_timestamp(val)
                        if not is_valid:
                            raise ValueError(format_import_error(
                                dataset=f"{tbl}.csv",
                                target_table=f"public.{tbl}",
                                column=c,
                                row=row_idx + 2,
                                value=str(val),
                                problem=f"Expected timestamp but received invalid value '{val}'.",
                                suggested_action="Format timestamp as 'YYYY-MM-DD HH:MM:SS' or leave empty for SQL NULL."
                            ))
                        if dt_val is None and c in req_cols:
                            raise ValueError(format_import_error(
                                dataset=f"{tbl}.csv",
                                target_table=f"public.{tbl}",
                                column=c,
                                row=row_idx + 2,
                                problem=f"Missing value in required timestamp column '{c}'.",
                                suggested_action=f"Provide a valid timestamp for required field '{c}'."
                            ))
                        cleaned_row.append(dt_val)
                    elif c in date_cols:
                        is_valid, d_val = parse_and_validate_date(val)
                        if not is_valid:
                            raise ValueError(format_import_error(
                                dataset=f"{tbl}.csv",
                                target_table=f"public.{tbl}",
                                column=c,
                                row=row_idx + 2,
                                value=str(val),
                                problem=f"Expected date but received invalid value '{val}'.",
                                suggested_action="Format date as 'YYYY-MM-DD' or leave empty for SQL NULL."
                            ))
                        if d_val is None and c in req_cols:
                            raise ValueError(format_import_error(
                                dataset=f"{tbl}.csv",
                                target_table=f"public.{tbl}",
                                column=c,
                                row=row_idx + 2,
                                problem=f"Missing value in required date column '{c}'.",
                                suggested_action=f"Provide a valid date for required field '{c}'."
                            ))
                        cleaned_row.append(d_val)
                    else:
                        cleaned_val = normalize_generic_value(val)
                        if cleaned_val is None and c in req_cols:
                            raise ValueError(format_import_error(
                                dataset=f"{tbl}.csv",
                                target_table=f"public.{tbl}",
                                column=c,
                                row=row_idx + 2,
                                problem=f"Missing value in required column '{c}'.",
                                suggested_action=f"Provide a non-empty value for required field '{c}'."
                            ))
                        cleaned_row.append(cleaned_val)
                records.append(cleaned_row)

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

            execute_values(cursor, insert_query, records, page_size=1000)
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
        
        err_msg = str(e)
        tbl_name = current_loading_table or "unknown"
        if "Dataset:" in err_msg and "Problem:" in err_msg:
            structured_error = err_msg
        else:
            structured_error = parse_postgres_error_details(
                err_msg,
                tbl_name,
                datasets.get(tbl_name) if datasets else None
            )

        return {
            "success": False,
            "error": structured_error,
            "technical_error": err_msg,
            "errors": [structured_error],
            "loaded_counts": {}
        }

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()



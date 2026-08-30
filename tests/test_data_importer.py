import os
import io
import unittest
import pandas as pd
from utils.data_importer import (
    validate_csv_content,
    validate_batch_foreign_keys,
    detect_dataset_from_headers,
    map_columns_to_schema,
    load_datasets_transactional,
    TABLE_SCHEMAS,
    COLUMN_ALIASES
)
from utils.database import DatabaseConnection

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

class TestMobilityDataImporter(unittest.TestCase):
    """
    Comprehensive test suite for the Mobility CSV Dataset Importer.
    Tests all 10+ positive, negative, auto-detection, alias mapping,
    and atomic rollback scenarios.
    """

    def read_fixture(self, filename: str) -> bytes:
        filepath = os.path.join(FIXTURES_DIR, filename)
        with open(filepath, "rb") as f:
            return f.read()

    # 1. Valid Users CSV
    def test_01_valid_users_csv(self):
        content = self.read_fixture("valid_users.csv")
        valid, df, table_name, errors, warnings, meta = validate_csv_content(
            content, "valid_users.csv", "users"
        )
        self.assertTrue(valid, f"Validation failed: {errors}")
        self.assertEqual(table_name, "users")
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 10)
        self.assertIn(meta["validation_state"], ["VALID", "VALID_WITH_WARNINGS"])

    # 2. Valid Vehicles CSV
    def test_02_valid_vehicles_csv(self):
        content = self.read_fixture("valid_vehicles.csv")
        valid, df, table_name, errors, warnings, meta = validate_csv_content(
            content, "valid_vehicles.csv", "vehicles"
        )
        self.assertTrue(valid, f"Validation failed: {errors}")
        self.assertEqual(table_name, "vehicles")
        self.assertEqual(len(df), 5)
        self.assertIn("driver_id", df.columns)

    # 3. Valid Rides CSV (with timestamps and nullable checks)
    def test_03_valid_rides_csv(self):
        content = self.read_fixture("valid_rides.csv")
        valid, df, table_name, errors, warnings, meta = validate_csv_content(
            content, "valid_rides.csv", "rides"
        )
        self.assertTrue(valid, f"Validation failed: {errors}")
        self.assertEqual(table_name, "rides")
        self.assertEqual(len(df), 5)

    # 4. Valid Payments CSV
    def test_04_valid_payments_csv(self):
        content = self.read_fixture("valid_payments.csv")
        valid, df, table_name, errors, warnings, meta = validate_csv_content(
            content, "valid_payments.csv", "payments"
        )
        self.assertTrue(valid, f"Validation failed: {errors}")
        self.assertEqual(table_name, "payments")
        self.assertEqual(len(df), 4)

    # 5. Valid Ratings CSV (with rating in 1-5 range)
    def test_05_valid_ratings_csv(self):
        content = self.read_fixture("valid_ratings.csv")
        valid, df, table_name, errors, warnings, meta = validate_csv_content(
            content, "valid_ratings.csv", "ratings"
        )
        self.assertTrue(valid, f"Validation failed: {errors}")
        self.assertEqual(table_name, "ratings")
        self.assertEqual(len(df), 4)

    # 6. Auto-Detection without relying on filename
    def test_06_auto_detect_dataset(self):
        content = self.read_fixture("customer_export_auto_detect.csv")
        valid, df, table_name, errors, warnings, meta = validate_csv_content(
            content, "customer_export_auto_detect.csv", "auto"
        )
        self.assertTrue(valid, f"Auto-detection failed: {errors}")
        self.assertEqual(table_name, "users")
        self.assertIsNotNone(meta.get("detection_info"))
        self.assertEqual(meta["detection_info"]["detected_dataset"], "users")
        self.assertIn(meta["detection_info"]["confidence"], ["High", "Medium"])

    # 7. Column Aliases & Mapping
    def test_07_column_aliases_mapping(self):
        content = self.read_fixture("users_with_aliases.csv")
        valid, df, table_name, errors, warnings, meta = validate_csv_content(
            content, "users_with_aliases.csv", "users"
        )
        self.assertTrue(valid, f"Alias mapping failed: {errors}")
        self.assertEqual(table_name, "users")
        # Ensure canonical column names are produced
        self.assertIn("user_id", df.columns)
        self.assertIn("first_name", df.columns)
        self.assertIn("last_name", df.columns)
        self.assertIn("email", df.columns)
        self.assertIn("phone", df.columns)
        self.assertIn("city", df.columns)
        self.assertIn("user_type", df.columns)
        self.assertIn("signup_date", df.columns)
        self.assertIn("is_active", df.columns)

    # 8. Missing Required Column Error
    def test_08_missing_required_column(self):
        content = self.read_fixture("users_missing_required.csv")
        valid, df, table_name, errors, warnings, meta = validate_csv_content(
            content, "users_missing_required.csv", "users"
        )
        self.assertFalse(valid)
        self.assertEqual(meta["validation_state"], "INVALID")
        self.assertGreaterEqual(len(errors), 1)
        err = errors[0]
        self.assertEqual(err["error_type"], "missing_required_column")
        self.assertIn("first_name", err["problem"])
        self.assertIn("last_name", err["problem"])
        self.assertIn("user_type", err["problem"])

    # 9. Duplicate PK inside Uploaded CSV
    def test_09_duplicate_pk_in_csv(self):
        content = self.read_fixture("users_duplicate_pk.csv")
        valid, df, table_name, errors, warnings, meta = validate_csv_content(
            content, "users_duplicate_pk.csv", "users"
        )
        self.assertFalse(valid)
        dup_errs = [e for e in errors if e.get("error_type") == "duplicate_primary_key"]
        self.assertGreaterEqual(len(dup_errs), 1)
        self.assertEqual(dup_errs[0]["column"], "user_id")
        self.assertEqual(dup_errs[0]["value"], "90040")

    # 10. NaN / Null in Nullable Timestamp column
    def test_10_nan_in_nullable_timestamp(self):
        content = self.read_fixture("rides_nan_pickup_time.csv")
        valid, df, table_name, errors, warnings, meta = validate_csv_content(
            content, "rides_nan_pickup_time.csv", "rides"
        )
        self.assertTrue(valid, f"Nullable timestamp with NaN should be valid: {errors}")
        # Ensure values in pickup_time became None instead of float NaN
        for val in df["pickup_time"]:
            self.assertIsNone(val)

    # 11. Invalid Corrupted Timestamp String Rejected
    def test_11_invalid_timestamp_rejected(self):
        content = self.read_fixture("rides_invalid_timestamp.csv")
        valid, df, table_name, errors, warnings, meta = validate_csv_content(
            content, "rides_invalid_timestamp.csv", "rides"
        )
        self.assertFalse(valid)
        ts_errs = [e for e in errors if e.get("error_type") == "invalid_timestamp"]
        self.assertGreaterEqual(len(ts_errs), 1)
        self.assertEqual(ts_errs[0]["column"], "requested_at")
        self.assertEqual(ts_errs[0]["value"], "not_a_valid_timestamp")
        self.assertEqual(ts_errs[0]["row"], 2)

    # 12. Invalid Numeric Value Rejected
    def test_12_invalid_numeric_fare_rejected(self):
        content = self.read_fixture("rides_invalid_fare.csv")
        valid, df, table_name, errors, warnings, meta = validate_csv_content(
            content, "rides_invalid_fare.csv", "rides"
        )
        self.assertFalse(valid)
        fare_errs = [e for e in errors if e.get("error_type") == "invalid_decimal"]
        self.assertGreaterEqual(len(fare_errs), 1)
        self.assertEqual(fare_errs[0]["column"], "fare")
        self.assertEqual(fare_errs[0]["value"], "INVALID_FARE")
        self.assertEqual(fare_errs[0]["row"], 2)

    # 13. Invalid Foreign Key Detection
    def test_13_invalid_foreign_key_detection(self):
        content = self.read_fixture("rides_invalid_fk.csv")
        valid, df, table_name, errors, warnings, meta = validate_csv_content(
            content, "rides_invalid_fk.csv", "rides"
        )
        self.assertTrue(valid) # Individual schema is valid
        # When checking batch FKs:
        batch = {"rides": df}
        fk_valid, fk_errors, fk_warnings = validate_batch_foreign_keys(batch)
        self.assertFalse(fk_valid)
        self.assertGreaterEqual(len(fk_errors), 1)
        self.assertEqual(fk_errors[0]["column"], "rider_id")
        self.assertEqual(fk_errors[0]["value"], "9999999")
        self.assertEqual(fk_errors[0]["row"], 2)

    # 14. Extra Columns Warning & Exclusion
    def test_14_extra_columns_warning(self):
        content = self.read_fixture("rides_extra_columns.csv")
        valid, df, table_name, errors, warnings, meta = validate_csv_content(
            content, "rides_extra_columns.csv", "rides"
        )
        self.assertTrue(valid)
        self.assertEqual(meta["validation_state"], "VALID_WITH_WARNINGS")
        self.assertGreaterEqual(len(warnings), 1)
        self.assertIn("weather", warnings[0])
        self.assertIn("campaign_id", warnings[0])
        # Verify extra columns are not in normalized canonical DataFrame
        self.assertNotIn("weather", df.columns)
        self.assertNotIn("campaign_id", df.columns)

    # 15. Rating Check Constraint (1-5 range)
    def test_15_rating_check_constraint(self):
        content = self.read_fixture("ratings_check_violation.csv")
        valid, df, table_name, errors, warnings, meta = validate_csv_content(
            content, "ratings_check_violation.csv", "ratings"
        )
        self.assertFalse(valid)
        rating_errs = [e for e in errors if e.get("column") == "rating"]
        self.assertGreaterEqual(len(rating_errs), 1)
        self.assertEqual(rating_errs[0]["value"], "10")

    # 16. Invalid Boolean Value Rejected
    def test_16_invalid_boolean_rejected(self):
        content = self.read_fixture("users_invalid_boolean.csv")
        valid, df, table_name, errors, warnings, meta = validate_csv_content(
            content, "users_invalid_boolean.csv", "users"
        )
        self.assertFalse(valid)
        bool_errs = [e for e in errors if e.get("error_type") == "invalid_bool"]
        self.assertGreaterEqual(len(bool_errs), 1)
        self.assertEqual(bool_errs[0]["column"], "is_active")
        self.assertEqual(bool_errs[0]["value"], "maybe_active")

    # 17. Atomic Multi-Dataset Transaction & Rollback
    def test_17_atomic_multi_dataset_transaction_and_rollback(self):
        users_content = self.read_fixture("valid_users.csv")
        vehicles_content = self.read_fixture("valid_vehicles.csv")
        rides_content = self.read_fixture("rides_invalid_timestamp.csv")

        _, users_df, _, _, _, _ = validate_csv_content(users_content, "valid_users.csv", "users")
        _, veh_df, _, _, _, _ = validate_csv_content(vehicles_content, "valid_vehicles.csv", "vehicles")

        # Intentionally create invalid dataframe to force transaction error on table 3
        bad_rides_df = pd.DataFrame([{
            "ride_id": 90099,
            "rider_id": 90001,
            "driver_id": 90002,
            "requested_at": "THIS_IS_CORRUPT",
            "fare": 25.0,
            "status": "completed"
        }])

        datasets = {
            "users": users_df,
            "vehicles": veh_df,
            "rides": bad_rides_df
        }

        # Attempt transactional load
        result = load_datasets_transactional(datasets)
        self.assertFalse(result["success"])
        self.assertIn("error", result)

        # Verify rollback: check that test users were NOT partially inserted
        db = DatabaseConnection()
        conn = db.get_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM public.users WHERE user_id IN (90001, 90002, 90003);")
                found = cur.fetchall()
                self.assertEqual(len(found), 0, f"Rollback failed, found partial users: {found}")


if __name__ == "__main__":
    unittest.main()

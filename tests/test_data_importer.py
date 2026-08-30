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

    # 18. Scenario F: Users missing last_name -> FAIL
    def test_18_users_missing_last_name_fails(self):
        csv_text = "user_id,first_name,email,user_type\n901,John,john@example.com,rider\n"
        valid, df, tbl, errors, warns, meta = validate_csv_content(csv_text.encode("utf-8"), "users_no_last.csv", "users")
        self.assertFalse(valid)
        self.assertTrue(any("last_name" in str(e) for e in errors))

    # 19. Scenario G: Users missing user_type -> FAIL
    def test_19_users_missing_user_type_fails(self):
        csv_text = "user_id,first_name,last_name,email\n902,John,Doe,john@example.com\n"
        valid, df, tbl, errors, warns, meta = validate_csv_content(csv_text.encode("utf-8"), "users_no_type.csv", "users")
        self.assertFalse(valid)
        self.assertTrue(any("user_type" in str(e) for e in errors))

    # 20. Scenario H: Users with extra age column -> PASS with warning and ignore
    def test_20_users_with_extra_age_column_passes(self):
        csv_text = "user_id,first_name,last_name,email,user_type,age\n903,John,Doe,john903@example.com,rider,30\n"
        valid, df, tbl, errors, warns, meta = validate_csv_content(csv_text.encode("utf-8"), "users_with_age.csv", "users")
        self.assertTrue(valid)
        self.assertNotIn("age", df.columns)
        self.assertTrue(any("age" in w for w in warns))

    # 21. Scenario I: Exact user_id mapping -> 100% confidence
    def test_21_exact_user_id_mapping_confidence(self):
        from utils.data_importer import map_columns_to_schema
        res = map_columns_to_schema(["User ID", "First_Name", "last-name", "Email", "user_type"], "users")
        self.assertTrue(res["valid"])
        for item in res["mapping_details"]:
            self.assertEqual(item["confidence"], 100)
            self.assertEqual(item["status"], "exact")

    # 22. Scenario J: Known alias mapping -> deterministic 95% confidence
    def test_22_known_alias_mapping_confidence(self):
        from utils.data_importer import map_columns_to_schema
        res = map_columns_to_schema(["customer_id", "fname", "lname", "email_address", "role"], "users")
        self.assertTrue(res["valid"])
        for item in res["mapping_details"]:
            self.assertEqual(item["confidence"], 95)
            self.assertEqual(item["status"], "alias")

    # 23. Scenario O: Empty CSV -> FAIL cleanly
    def test_23_empty_csv_clean_failure(self):
        valid, df, tbl, errors, warns, meta = validate_csv_content(b"", "empty.csv", "users")
        self.assertFalse(valid)
        self.assertEqual(meta["validation_state"], "EMPTY_CSV")
        self.assertIn("empty", errors[0]["problem"].lower())

    # 24. Scenario P: Malformed CSV -> FAIL cleanly
    def test_24_malformed_csv_clean_failure(self):
        corrupt_bytes = b"\x00\xff\xfe\x00\x12\x34\x56"
        valid, df, tbl, errors, warns, meta = validate_csv_content(corrupt_bytes, "corrupt.csv", "users")
        self.assertFalse(valid)
        self.assertIn(meta["validation_state"], ["CSV_PARSE_FAILED", "INVALID"])

    # 25. Authoritative CANONICAL_SAMPLES generation test
    def test_25_all_canonical_samples_valid(self):
        from utils.data_importer import CANONICAL_SAMPLES, validate_batch_foreign_keys
        sample_dfs = {}
        for tbl, csv_content in CANONICAL_SAMPLES.items():
            valid, df, name, errors, warns, meta = validate_csv_content(csv_content.encode("utf-8"), f"{tbl}_sample.csv", tbl, import_mode="upsert")
            self.assertTrue(valid, f"Canonical sample {tbl} failed validation: {errors}")
            sample_dfs[tbl] = df
        
        fk_valid, fk_errors, _ = validate_batch_foreign_keys(sample_dfs)
        self.assertTrue(fk_valid, f"Batch FK validation on canonical samples failed: {fk_errors}")

    # 26. External Users CSV with composite 'name' (Aarav Sharma & Mary Jane Watson) -> PASS
    def test_26_users_composite_name_splitting_passes(self):
        csv_text = (
            "user_id,name,email,phone,city,user_type\n"
            "201,Aarav Sharma,aarav@example.com,+919999999999,Bengaluru,rider\n"
            "202,Mary Jane Watson,mj.watson@example.com,+14165550202,Toronto,rider\n"
        )
        valid, df, tbl, errors, warns, meta = validate_csv_content(
            csv_text.encode("utf-8"), "external_users.csv", "users"
        )
        self.assertTrue(valid, f"Composite name validation failed: {errors}")
        self.assertEqual(len(df), 2)
        # Verify first row
        row1 = df[df["user_id"] == 201].iloc[0]
        self.assertEqual(row1["first_name"], "Aarav")
        self.assertEqual(row1["last_name"], "Sharma")
        # Verify second row (multi-word name)
        row2 = df[df["user_id"] == 202].iloc[0]
        self.assertEqual(row2["first_name"], "Mary")
        self.assertEqual(row2["last_name"], "Jane Watson")
        # Verify missing optional fields are safely None
        self.assertIsNone(row1["province"])

    # 27. External Users CSV with 'Madonna' (single name) -> FAILS on missing required last_name
    def test_27_users_composite_madonna_fails_required_last_name(self):
        csv_text = (
            "user_id,name,email,user_type\n"
            "203,Madonna,madonna@example.com,rider\n"
        )
        valid, df, tbl, errors, warns, meta = validate_csv_content(
            csv_text.encode("utf-8"), "madonna_user.csv", "users"
        )
        self.assertFalse(valid)
        ln_errs = [e for e in errors if e.get("column") == "last_name"]
        self.assertGreaterEqual(len(ln_errs), 1)
        self.assertIn("missing", ln_errs[0]["problem"].lower())

    # 28. Priority Rule: Exact first_name and last_name ALWAYS WIN over 'name'
    def test_28_priority_exact_match_wins_over_composite_name(self):
        csv_text = (
            "user_id,first_name,last_name,name,email,user_type\n"
            "204,Bruce,Wayne,Ignore Me,bruce@example.com,rider\n"
        )
        valid, df, tbl, errors, warns, meta = validate_csv_content(
            csv_text.encode("utf-8"), "exact_and_composite.csv", "users"
        )
        self.assertTrue(valid, f"Validation failed: {errors}")
        row = df.iloc[0]
        self.assertEqual(row["first_name"], "Bruce")
        self.assertEqual(row["last_name"], "Wayne")

    # 29. External CSV with customer_id, firstName, lastName, email_address, mobile, location
    def test_29_external_csv_aliases_pass(self):
        csv_text = (
            "customer_id,firstName,lastName,email_address,mobile,location,user_type\n"
            "205,Diana,Prince,diana@example.com,+14165550205,Themyscira,rider\n"
        )
        valid, df, tbl, errors, warns, meta = validate_csv_content(
            csv_text.encode("utf-8"), "external_aliases.csv", "users"
        )
        self.assertTrue(valid, f"Alias mapping failed: {errors}")
        row = df.iloc[0]
        self.assertEqual(row["user_id"], 205)
        self.assertEqual(row["first_name"], "Diana")
        self.assertEqual(row["last_name"], "Prince")
        self.assertEqual(row["email"], "diana@example.com")
        self.assertEqual(row["phone"], "+14165550205")
        self.assertEqual(row["city"], "Themyscira")

    # 30. Auto-detection handles external CSV with 'name' and detects Users with High confidence
    def test_30_auto_detect_users_from_external_name_header(self):
        from utils.data_importer import detect_dataset_from_headers
        headers = ["user_id", "name", "email", "phone", "city", "user_type"]
        detection = detect_dataset_from_headers(headers)
        self.assertEqual(detection["detected_dataset"], "users")
        self.assertEqual(detection["confidence"], "High")
        self.assertIn("name", detection["proposed_mappings"])

    # 31. TEST C: External Users CSV (user_id, name, email, city, signup_date) missing user_type
    def test_31_external_users_missing_user_type_resolved_with_default(self):
        csv_text = (
            "user_id,name,email,city,signup_date\n"
            "301,Aarav Sharma,aarav301@example.com,Bengaluru,2025-01-10\n"
            "302,Priya Patel,priya302@example.com,Mumbai,2025-01-11\n"
        )
        # Step 1: Without explicit default -> FAILS cleanly on missing_required_column, NOT CSV parse failure
        valid, df, tbl, errors, warns, meta = validate_csv_content(
            csv_text.encode("utf-8"), "external_users_no_type.csv", "users"
        )
        self.assertFalse(valid)
        self.assertEqual(meta["validation_state"], "INVALID")
        self.assertEqual(meta["row_count"], 2)
        self.assertIn("user_type", meta["missing_required"])
        self.assertTrue(any(e.get("error_type") == "missing_required_column" for e in errors))

        # Step 2: With user-selected explicit default value {"user_type": "rider"} -> PASSES and applies to all rows
        valid2, df2, tbl2, errors2, warns2, meta2 = validate_csv_content(
            csv_text.encode("utf-8"), "external_users_no_type.csv", "users",
            default_values={"user_type": "rider"}
        )
        self.assertTrue(valid2, f"Validation with default failed: {errors2}")
        self.assertEqual(len(df2), 2)
        self.assertEqual(df2.iloc[0]["first_name"], "Aarav")
        self.assertEqual(df2.iloc[0]["last_name"], "Sharma")
        self.assertEqual(df2.iloc[0]["user_type"], "rider")
        self.assertEqual(df2.iloc[1]["first_name"], "Priya")
        self.assertEqual(df2.iloc[1]["last_name"], "Patel")
        self.assertEqual(df2.iloc[1]["user_type"], "rider")

    # 32. TEST D: Madonna single-name fail verified row-by-row
    def test_32_madonna_single_name_exact_row_failure(self):
        csv_text = (
            "user_id,name,email,user_type\n"
            "401,Aarav Sharma,aarav401@example.com,rider\n"
            "402,Madonna,madonna@example.com,rider\n"
        )
        valid, df, tbl, errors, warns, meta = validate_csv_content(
            csv_text.encode("utf-8"), "madonna_test.csv", "users"
        )
        self.assertFalse(valid)
        ln_errs = [e for e in errors if e.get("column") == "last_name" and e.get("row") == 3]
        self.assertEqual(len(ln_errs), 1, f"Expected error on row 3 for Madonna, got: {errors}")
        self.assertEqual(ln_errs[0]["error_type"], "null_required_value")

    # 33. TEST E: Duplicate PK failure inside uploaded CSV
    def test_33_duplicate_pk_inside_csv_fails(self):
        csv_text = (
            "user_id,first_name,last_name,email,user_type\n"
            "501,Clark,Kent,clark@dailyplanet.com,rider\n"
            "501,Superman,Kent,superman@dailyplanet.com,rider\n"
        )
        valid, df, tbl, errors, warns, meta = validate_csv_content(
            csv_text.encode("utf-8"), "duplicate_pk.csv", "users"
        )
        self.assertFalse(valid)
        pk_errs = [e for e in errors if e.get("error_type") == "duplicate_primary_key"]
        self.assertEqual(len(pk_errs), 1)
        self.assertEqual(pk_errs[0]["value"], "501")


if __name__ == "__main__":
    unittest.main()

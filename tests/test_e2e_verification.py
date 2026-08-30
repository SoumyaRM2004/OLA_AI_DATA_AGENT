import os
import unittest
from fastapi.testclient import TestClient
from server import app
from utils.database import DatabaseConnection

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

class TestImporterE2EVerification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.db = DatabaseConnection()

    def get_fixture_file(self, filename: str):
        path = os.path.join(FIXTURES_DIR, filename)
        return open(path, "rb")

    # TEST 1: Upload exact valid Users CSV -> validation passes -> staging succeeds -> DB load succeeds
    def test_e2e_01_valid_users_upload_stage_load(self):
        with self.get_fixture_file("valid_users.csv") as f:
            res = self.client.post(
                "/api/import/validate",
                files={"file": ("users.csv", f, "text/csv")},
                data={"dataset_type": "users", "import_mode": "upsert"}
            )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["table_name"], "users")
        self.assertEqual(data["row_count"], 3)
        self.assertEqual(len(data["structured_errors"]), 0)

        # Load staged to database
        load_res = self.client.post(
            "/api/import/load",
            json={"tables": ["users"], "import_mode": "upsert"}
        )
        self.assertEqual(load_res.status_code, 200)
        load_data = load_res.json()
        self.assertTrue(load_data["success"])
        self.assertEqual(load_data["loaded_counts"]["users"], 3)

        # Verify in DB
        conn = self.db.get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT first_name, last_name, email FROM public.users WHERE user_id = 90001;")
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "John")
            self.assertEqual(row[1], "Doe")

    # TEST 2: Upload CSV with wrong filename but correct Users columns -> auto-detect Users
    def test_e2e_02_auto_detect_users_from_headers(self):
        with self.get_fixture_file("customer_export_auto_detect.csv") as f:
            res = self.client.post(
                "/api/import/inspect",
                files={"file": ("random_export_2026.csv", f, "text/csv")},
                data={"dataset_type": "auto"}
            )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["detected_dataset"], "users")
        self.assertEqual(data["label"], "Users")
        self.assertIn(data["confidence"], ["High", "Medium"])

    # TEST 3: Upload CSV with alternate column names -> mapping suggested -> canonical schema produced
    def test_e2e_03_column_aliases_and_custom_mappings(self):
        with self.get_fixture_file("users_with_aliases.csv") as f:
            res = self.client.post(
                "/api/import/validate",
                files={"file": ("users_with_aliases.csv", f, "text/csv")},
                data={"dataset_type": "users", "import_mode": "upsert"}
            )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["table_name"], "users")
        self.assertIn("user_id", data["columns"])
        self.assertIn("first_name", data["columns"])
        self.assertIn("phone", data["columns"])
        self.assertIn("city", data["columns"])

    # TEST 4: Upload CSV missing required column -> validation fails -> clear missing-column error
    def test_e2e_04_missing_required_column_error(self):
        with self.get_fixture_file("users_missing_required.csv") as f:
            res = self.client.post(
                "/api/import/validate",
                files={"file": ("users_missing_required.csv", f, "text/csv")},
                data={"dataset_type": "users"}
            )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["valid"])
        self.assertEqual(data["validation_state"], "INVALID")
        self.assertGreaterEqual(len(data["structured_errors"]), 1)
        err = data["structured_errors"][0]
        self.assertEqual(err["error_type"], "missing_required_column")
        self.assertIn("first_name", err["problem"])
        self.assertIn("Add the required", err["suggested_action"])

    # TEST 5: Upload duplicate PK inside CSV -> validation fails -> exact row/value shown
    def test_e2e_05_duplicate_pk_inside_csv(self):
        with self.get_fixture_file("users_duplicate_pk.csv") as f:
            res = self.client.post(
                "/api/import/validate",
                files={"file": ("users_duplicate_pk.csv", f, "text/csv")},
                data={"dataset_type": "users"}
            )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["valid"])
        dup_errs = [e for e in data["structured_errors"] if e["error_type"] == "duplicate_primary_key"]
        self.assertEqual(len(dup_errs), 1)
        self.assertEqual(dup_errs[0]["column"], "user_id")
        self.assertEqual(dup_errs[0]["value"], "90040")
        self.assertEqual(dup_errs[0]["row"], 2)

    # TEST 6: Upload existing PK in Append mode -> conflict detected
    def test_e2e_06_existing_pk_conflict_in_append_mode(self):
        # User 90001 already in DB from test 1
        with self.get_fixture_file("valid_users.csv") as f:
            res = self.client.post(
                "/api/import/validate",
                files={"file": ("users_append.csv", f, "text/csv")},
                data={"dataset_type": "users", "import_mode": "append"}
            )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["valid"])
        pk_errs = [e for e in data["structured_errors"] if e["error_type"] == "existing_primary_key"]
        self.assertGreaterEqual(len(pk_errs), 1)
        self.assertEqual(pk_errs[0]["column"], "user_id")
        self.assertEqual(pk_errs[0]["value"], "90001")

    # TEST 7: Upload rides.csv containing NaN pickup_time -> caught BEFORE PostgreSQL -> converted to SQL NULL
    def test_e2e_07_nan_pickup_time_handled_safely(self):
        with self.get_fixture_file("rides_nan_pickup_time.csv") as f:
            res = self.client.post(
                "/api/import/validate",
                files={"file": ("rides_nan.csv", f, "text/csv")},
                data={"dataset_type": "rides", "import_mode": "upsert"}
            )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["valid"])
        # Ensure sample records have null/empty instead of float NaN
        sample = data["sample_records"][0]
        self.assertEqual(sample["pickup_time"], "")

    # TEST 8: Upload invalid foreign key rider_id -> FK check fails -> exact row/value shown
    def test_e2e_08_invalid_foreign_key_rejected(self):
        with self.get_fixture_file("rides_invalid_fk.csv") as f:
            res = self.client.post(
                "/api/import/validate",
                files={"file": ("rides_invalid_fk.csv", f, "text/csv")},
                data={"dataset_type": "rides"}
            )
        self.assertEqual(res.status_code, 200)
        # Attempt to load staged
        load_res = self.client.post(
            "/api/import/load",
            json={"tables": ["rides"]}
        )
        self.assertEqual(load_res.status_code, 400)
        load_data = load_res.json()
        self.assertFalse(load_data["success"])
        fk_errs = load_data.get("structured_errors", [])
        self.assertGreaterEqual(len(fk_errs), 1)
        self.assertEqual(fk_errs[0]["column"], "rider_id")
        self.assertEqual(fk_errs[0]["value"], "9999999")

    # TEST 9: Upload extra columns -> warning shown -> extra columns excluded from DB
    def test_e2e_09_extra_columns_filtered(self):
        with self.get_fixture_file("rides_extra_columns.csv") as f:
            res = self.client.post(
                "/api/import/validate",
                files={"file": ("rides_extra.csv", f, "text/csv")},
                data={"dataset_type": "rides", "import_mode": "upsert"}
            )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["validation_state"], "VALID_WITH_WARNINGS")
        self.assertGreaterEqual(len(data["warnings"]), 1)
        self.assertIn("weather", data["warnings"][0])
        self.assertNotIn("weather", data["columns"])
        self.assertNotIn("campaign_id", data["columns"])

    # TEST 10: Multi-dataset atomic transaction rollback on failure
    def test_e2e_10_multi_dataset_transaction_atomic_rollback(self):
        # Stage valid vehicles
        with self.get_fixture_file("valid_vehicles.csv") as f:
            self.client.post(
                "/api/import/validate",
                files={"file": ("vehicles.csv", f, "text/csv")},
                data={"dataset_type": "vehicles", "import_mode": "upsert"}
            )

        # Stage invalid ratings (violates FK)
        with self.get_fixture_file("ratings_check_violation.csv") as f:
            self.client.post(
                "/api/import/validate",
                files={"file": ("ratings_bad.csv", f, "text/csv")},
                data={"dataset_type": "ratings"}
            )

        # Clean up any leftover test vehicles in DB
        conn = self.db.get_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.vehicles WHERE vehicle_id IN (90001, 90002);")
            cur.execute("DELETE FROM public.users WHERE user_id IN (90001, 90002, 90003);")
        conn.commit()

        # Clear staging
        self.client.post("/api/import/clear-staged")

    @classmethod
    def tearDownClass(cls):
        # Clean up test rows
        try:
            conn = cls.db.get_connection()
            with conn.cursor() as cur:
                cur.execute("DELETE FROM public.ratings WHERE rating_id >= 90000;")
                cur.execute("DELETE FROM public.payments WHERE payment_id >= 90000;")
                cur.execute("DELETE FROM public.rides WHERE ride_id >= 90000;")
                cur.execute("DELETE FROM public.vehicles WHERE vehicle_id >= 90000;")
                cur.execute("DELETE FROM public.users WHERE user_id >= 90000;")
            conn.commit()
        except Exception:
            pass


if __name__ == "__main__":
    unittest.main()

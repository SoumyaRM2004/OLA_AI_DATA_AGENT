import os
import unittest
import pandas as pd
import psycopg2
from psycopg2 import sql
from fastapi.testclient import TestClient

from server import app
from utils.database import DatabaseConnection, get_db_config, sanitize_session_id, get_session_schema_name
from utils.data_importer import load_datasets_transactional, validate_batch_foreign_keys
from utils.chat_store import ChatStore

client = TestClient(app)


class TestDatasetIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseConnection()
        cls.db_config = get_db_config()
        cls.session_a = "test_user_alpha_123"
        cls.session_b = "test_user_beta_456"
        cls.session_c = "test_user_gamma_789"
        cls.schema_a = get_session_schema_name(cls.session_a)
        cls.schema_b = get_session_schema_name(cls.session_b)
        cls.schema_c = get_session_schema_name(cls.session_c)
        cls._cleanup_test_schemas()

        # Seed Session A with 3 users (replace mode)
        df_a = pd.DataFrame([
            {"user_id": 99001, "first_name": "Alice", "last_name": "Alpha", "email": "alice@test.com", "phone": "1234567890", "city": "Toronto", "province": "ON", "user_type": "rider", "signup_date": "2025-01-01", "is_active": True},
            {"user_id": 99002, "first_name": "Alan", "last_name": "Apex", "email": "alan@test.com", "phone": "1234567891", "city": "Toronto", "province": "ON", "user_type": "rider", "signup_date": "2025-01-02", "is_active": True},
            {"user_id": 99003, "first_name": "Amy", "last_name": "Arrow", "email": "amy@test.com", "phone": "1234567892", "city": "Toronto", "province": "ON", "user_type": "rider", "signup_date": "2025-01-03", "is_active": True},
        ])
        load_a = load_datasets_transactional({"users": df_a}, import_mode="replace", session_id=cls.session_a)
        assert load_a["success"], f"Setup failed for Session A: {load_a}"

        # Seed Session B with 2 users (replace mode)
        df_b = pd.DataFrame([
            {"user_id": 88001, "first_name": "Bob", "last_name": "Beta", "email": "bob@test.com", "phone": "2234567890", "city": "Vancouver", "province": "BC", "user_type": "driver", "signup_date": "2025-01-01", "is_active": True},
            {"user_id": 88002, "first_name": "Bella", "last_name": "Beam", "email": "bella@test.com", "phone": "2234567891", "city": "Vancouver", "province": "BC", "user_type": "driver", "signup_date": "2025-01-02", "is_active": True},
        ])
        load_b = load_datasets_transactional({"users": df_b}, import_mode="replace", session_id=cls.session_b)
        assert load_b["success"], f"Setup failed for Session B: {load_b}"

    @classmethod
    def tearDownClass(cls):
        cls._cleanup_test_schemas()

    @classmethod
    def _cleanup_test_schemas(cls):
        try:
            conn = psycopg2.connect(**cls.db_config)
            conn.autocommit = True
            with conn.cursor() as cur:
                if cls.schema_a:
                    cur.execute(f"DROP SCHEMA IF EXISTS {cls.schema_a} CASCADE;")
                if cls.schema_b:
                    cur.execute(f"DROP SCHEMA IF EXISTS {cls.schema_b} CASCADE;")
                if cls.schema_c:
                    cur.execute(f"DROP SCHEMA IF EXISTS {cls.schema_c} CASCADE;")
            conn.close()
        except Exception as e:
            print(f"Cleanup error: {e}")

    def test_01_session_a_upload_does_not_modify_public(self):
        """1. Verify Session A upload of 3 users does NOT modify public.users (retains 10,000 base users)."""
        pub_res = self.db.execute_query_structured("SELECT COUNT(*) AS total FROM public.users;")
        self.assertIsNone(pub_res["error"])
        total_pub = int(pub_res["records"][0]["total"])
        self.assertEqual(total_pub, 10000, "public.users base dataset must remain exactly 10,000 records.")

    def test_02_session_b_upload_does_not_modify_session_a(self):
        """2. Verify Session B upload of 2 users does NOT overwrite or leak into Session A (still 3 users)."""
        res_a = self.db.execute_query_structured("SELECT COUNT(*) AS total FROM public.users;", session_id=self.session_a)
        self.assertIsNone(res_a["error"])
        self.assertEqual(int(res_a["records"][0]["total"]), 3, "Session A must retain exactly its 3 uploaded users.")

    def test_03_session_a_sees_its_own_overridden_table(self):
        """3. Verify Session A queries return its own 3 uploaded user records (Alice, Alan, Amy)."""
        res_a = self.db.execute_query_structured(
            "SELECT user_id, first_name FROM public.users ORDER BY user_id ASC;",
            session_id=self.session_a
        )
        self.assertIsNone(res_a["error"])
        records = res_a["records"]
        self.assertEqual(len(records), 3)
        self.assertEqual([r["first_name"] for r in records], ["Alice", "Alan", "Amy"])

    def test_04_session_b_sees_its_own_overridden_table(self):
        """4. Verify Session B queries return its own 2 uploaded user records (Bob, Bella)."""
        res_b = self.db.execute_query_structured(
            "SELECT user_id, first_name FROM public.users ORDER BY user_id ASC;",
            session_id=self.session_b
        )
        self.assertIsNone(res_b["error"])
        records = res_b["records"]
        self.assertEqual(len(records), 2)
        self.assertEqual([r["first_name"] for r in records], ["Bob", "Bella"])

    def test_05_non_overridden_tables_fall_back_to_public(self):
        """5. Verify tables not overridden in Session A (vehicles, rides, payments, ratings) fall back to public base dataset."""
        # Query non-overridden vehicles table in Session A
        res_v = self.db.execute_query_structured("SELECT COUNT(*) AS total FROM public.vehicles;", session_id=self.session_a)
        self.assertIsNone(res_v["error"])
        self.assertEqual(int(res_v["records"][0]["total"]), 3000, "Non-overridden vehicles table must fall back to 3,000 public records.")

        # Query non-overridden rides table in Session A
        res_r = self.db.execute_query_structured("SELECT COUNT(*) AS total FROM public.rides;", session_id=self.session_a)
        self.assertIsNone(res_r["error"])
        self.assertEqual(int(res_r["records"][0]["total"]), 20000, "Non-overridden rides table must fall back to 20,000 public records.")

    def test_06_session_child_parent_foreign_key_behavior(self):
        """6. Verify FK integrity when both parent & child exist in session, and when child references public parent."""
        # Scenario 6A: In Session A (users overridden), vehicles with driver_id 99001 (in session users) passes FK check
        df_v_valid = pd.DataFrame([
            {"vehicle_id": 55001, "driver_id": 99001, "make": "Toyota", "model": "Prius", "year": 2023, "license_plate": "ABC1234", "status": "active", "created_at": "2025-01-01"}
        ])
        is_val_a, errs_a, _ = validate_batch_foreign_keys({"vehicles": df_v_valid}, session_id=self.session_a)
        self.assertTrue(is_val_a, f"Valid session parent FK must pass: {errs_a}")

        # Scenario 6B: Vehicle with non-existent driver_id in Session A fails FK check
        df_v_invalid = pd.DataFrame([
            {"vehicle_id": 55002, "driver_id": 999999, "make": "Toyota", "model": "Prius", "year": 2023, "license_plate": "XYZ1234", "status": "active", "created_at": "2025-01-01"}
        ])
        is_val_inv, errs_inv, _ = validate_batch_foreign_keys({"vehicles": df_v_invalid}, session_id=self.session_a)
        self.assertFalse(is_val_inv, "Non-existent session parent FK must fail validation.")

        # Scenario 6C: In Session C (no users overridden), vehicle with driver_id 1 (in public.users) passes FK check
        df_v_pub = pd.DataFrame([
            {"vehicle_id": 55003, "driver_id": 1, "make": "Honda", "model": "Civic", "year": 2022, "license_plate": "PUB1234", "status": "active", "created_at": "2025-01-01"}
        ])
        is_val_c, _, _ = validate_batch_foreign_keys({"vehicles": df_v_pub}, session_id=self.session_c)
        self.assertTrue(is_val_c, "Child table referencing public parent table must pass FK check.")

    def test_07_sql_rewrite_does_not_modify_strings_or_comments(self):
        """7. Verify resolve_query_for_session does not rewrite table names inside SQL strings or comments."""
        query = (
            "-- SELECT * FROM users WHERE status = 'users'\n"
            "/* Multi-line block comment mentioning users and public.users */\n"
            "SELECT u.user_id, 'users in Toronto' AS note, 'public.users' AS label\n"
            "FROM users u WHERE u.city = 'Users City';"
        )
        resolved = self.db.resolve_query_for_session(query, self.session_a)

        # Comments and string literals must NOT be modified
        self.assertIn("-- SELECT * FROM users WHERE status = 'users'", resolved)
        self.assertIn("/* Multi-line block comment mentioning users and public.users */", resolved)
        self.assertIn("'users in Toronto'", resolved)
        self.assertIn("'public.users'", resolved)
        self.assertIn("'Users City'", resolved)

        # SQL FROM clause must be rewritten to session schema
        self.assertIn(f"FROM {self.schema_a}.users u", resolved)

    def test_08_sql_rewrite_handles_aliases_ctes_and_subqueries(self):
        """8. Verify resolve_query_for_session handles CTEs, aliases, and nested subqueries."""
        query = (
            "WITH user_summary AS (\n"
            "    SELECT u.user_id, COUNT(*) AS ride_count\n"
            "    FROM public.users u\n"
            "    JOIN rides r ON u.user_id = r.rider_id\n"
            "    GROUP BY u.user_id\n"
            ")\n"
            "SELECT us.user_id, us.ride_count\n"
            "FROM user_summary us\n"
            "WHERE us.user_id IN (SELECT user_id FROM users WHERE is_active = true);"
        )
        resolved = self.db.resolve_query_for_session(query, self.session_a)

        # public.users in CTE rewritten to session_schema.users
        self.assertIn(f"FROM {self.schema_a}.users u", resolved)
        # CTE name user_summary in main query is NOT modified
        self.assertIn("FROM user_summary us", resolved)
        # rides (not in session A) remains unchanged
        self.assertIn("JOIN rides r", resolved)
        # nested subquery FROM users rewritten to session_schema.users
        self.assertIn(f"SELECT user_id FROM {self.schema_a}.users WHERE is_active = true", resolved)

    def test_09_already_qualified_session_tables_are_not_double_rewritten(self):
        """9. Verify already session-qualified table names are NOT double-prefixed."""
        query = f"SELECT * FROM {self.schema_a}.users u JOIN public.vehicles v ON u.user_id = v.driver_id;"
        resolved = self.db.resolve_query_for_session(query, self.session_a)

        # Must not contain double schema prefix like session_xxx.session_xxx.users
        self.assertNotIn(f"{self.schema_a}.{self.schema_a}.users", resolved)
        self.assertIn(f"FROM {self.schema_a}.users u", resolved)
        self.assertIn("JOIN public.vehicles v", resolved)

    def test_10_chat_from_session_a_cannot_be_accessed_through_session_b(self):
        """10. Verify chat created in Session A is inaccessible (404) from Session B across GET, PUT, DELETE, and CLEAR."""
        # Create chat under Session A
        chat_a = ChatStore.create_chat(title="Alpha Private Chat", session_id=self.session_a)
        chat_a_id = chat_a["id"]

        # Session A can access its chat
        resp_get_a = client.get(f"/api/chats/{chat_a_id}", headers={"X-Session-ID": self.session_a})
        self.assertEqual(resp_get_a.status_code, 200)
        self.assertEqual(resp_get_a.json()["title"], "Alpha Private Chat")

        # Session B is rejected with 404 when accessing Session A's chat
        resp_get_b = client.get(f"/api/chats/{chat_a_id}", headers={"X-Session-ID": self.session_b})
        self.assertEqual(resp_get_b.status_code, 404)

        # Session B is rejected with 404 when attempting to rename Session A's chat
        resp_put_b = client.put(
            f"/api/chats/{chat_a_id}",
            json={"title": "Hacked Title"},
            headers={"X-Session-ID": self.session_b}
        )
        self.assertEqual(resp_put_b.status_code, 404)

        # Session B is rejected with 404 when attempting to clear Session A's chat
        resp_clear_b = client.post(f"/api/chats/{chat_a_id}/clear", headers={"X-Session-ID": self.session_b})
        self.assertEqual(resp_clear_b.status_code, 404)

        # Session B is rejected with 404 when attempting to delete Session A's chat
        resp_del_b = client.delete(f"/api/chats/{chat_a_id}", headers={"X-Session-ID": self.session_b})
        self.assertEqual(resp_del_b.status_code, 404)

        # Session A can cleanly delete its own chat
        resp_del_a = client.delete(f"/api/chats/{chat_a_id}", headers={"X-Session-ID": self.session_a})
        self.assertEqual(resp_del_a.status_code, 200)

    def test_11_public_base_dataset_remains_unchanged(self):
        """11. Verify all 5 public base tables retain their complete baseline row counts."""
        expected_counts = {
            "users": 10000,
            "vehicles": 3000,
            "rides": 20000,
            "payments": 16073,
            "ratings": 12000
        }
        for table, expected in expected_counts.items():
            res = self.db.execute_query_structured(f"SELECT COUNT(*) AS total FROM public.{table};")
            self.assertIsNone(res["error"])
            actual = int(res["records"][0]["total"])
            self.assertEqual(
                actual,
                expected,
                f"Base table public.{table} count mismatch: expected {expected}, found {actual}."
            )


if __name__ == "__main__":
    unittest.main()

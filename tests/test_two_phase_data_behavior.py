import unittest
import io
import json
import psycopg2
from psycopg2 import sql
from fastapi.testclient import TestClient
from server import app
from utils.database import DatabaseConnection, get_db_config
from utils.chat_store import ChatStore
from agents.data_agent import execute_agent_query


class TestTwoPhaseDataBehavior(unittest.TestCase):
    """
    Automated verification of the Two-Phase Data Lifecycle:
    Phase 1: Initial state against existing PostgreSQL database.
    Phase 2: Post-import state reflecting current PostgreSQL data with cache invalidation
             and live SQL querying in both same chat and new chat sessions.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.db = DatabaseConnection()

    def test_two_phase_data_lifecycle_and_multichat(self):
        # ----------------------------------------------------
        # STEP 1: Connect to initial existing PostgreSQL data
        # ----------------------------------------------------
        conn = self.db.get_connection()
        self.assertIsNotNone(conn, "Database connection must be active.")

        # ----------------------------------------------------
        # STEP 2: Record initial PostgreSQL counts using SQL
        # ----------------------------------------------------
        init_res = self.db.execute_query_structured("SELECT COUNT(*) AS total FROM public.users;")
        self.assertTrue(len(init_res["records"]) > 0)
        initial_users_count = int(init_res["records"][0]["total"])
        self.assertGreater(initial_users_count, 0, "PostgreSQL should have existing user records.")

        # Verify initial Analytics stats
        stats_res = self.client.get("/api/stats")
        self.assertEqual(stats_res.status_code, 200)
        stats_data = stats_res.json()
        self.assertEqual(stats_data["total_users"], initial_users_count)

        # Verify initial Database Explorer schema
        schema_res = self.client.get("/api/schema")
        self.assertEqual(schema_res.status_code, 200)
        schema_data = schema_res.json()
        self.assertEqual(schema_data["tables"]["users"]["row_count"], initial_users_count)

        # ----------------------------------------------------
        # STEP 3 & 8 (Part 1): Query AI Chat Session 1
        # ----------------------------------------------------
        chat_1 = ChatStore.create_chat(title="User Count Chat")
        chat_1_id = chat_1["id"]

        # Run AI Chat query via endpoint
        chat_res_1 = self.client.post("/api/chat", json={
            "message": "How many users are there?",
            "chat_id": chat_1_id
        })
        self.assertEqual(chat_res_1.status_code, 200)
        agent_data_1 = chat_res_1.json()
        self.assertTrue(agent_data_1.get("success"))
        self.assertEqual(agent_data_1.get("route"), "sql")
        # Ensure count matches initial database count
        count_str_1 = f"{initial_users_count:,}"
        self.assertTrue(
            str(initial_users_count) in agent_data_1["answer"] or count_str_1 in agent_data_1["answer"],
            f"Agent answer should mention initial count {initial_users_count}. Got: {agent_data_1['answer']}"
        )

        # ----------------------------------------------------
        # STEP 4 & 5: Upload and commit new CSV dataset (Upsert mode)
        # ----------------------------------------------------
        new_test_pk = 999901
        new_users_csv = f"""user_id,first_name,last_name,email,phone,city,province,user_type,signup_date,is_active
{new_test_pk},Alex,Hamilton,alex.h.phase2.test@example.com,555-0199,Toronto,ON,rider,2026-01-15,true
{new_test_pk+1},Beatrice,Smith,beatrice.s.phase2.test@example.com,555-0198,Calgary,AB,driver,2026-01-16,true
"""
        # Validate CSV upload
        val_res = self.client.post(
            "/api/import/validate",
            data={"dataset_type": "users", "import_mode": "upsert"},
            files={"file": ("users_phase2_test.csv", io.BytesIO(new_users_csv.encode("utf-8")), "text/csv")}
        )
        self.assertEqual(val_res.status_code, 200)
        val_data = val_res.json()
        self.assertTrue(val_data["valid"], f"CSV validation failed: {val_data.get('errors')}")

        # Load staged dataset into PostgreSQL
        load_res = self.client.post("/api/import/load", json={
            "tables": ["users"],
            "import_mode": "upsert"
        })
        self.assertEqual(load_res.status_code, 200)
        load_data = load_res.json()
        self.assertTrue(load_data["success"])

        try:
            # ----------------------------------------------------
            # STEP 5 & 6: Verify PostgreSQL and Analytics changed
            # ----------------------------------------------------
            updated_res = self.db.execute_query_structured("SELECT COUNT(*) AS total FROM public.users;")
            updated_users_count = int(updated_res["records"][0]["total"])
            self.assertEqual(updated_users_count, initial_users_count + 2)

            # Analytics KPI reflect current PostgreSQL
            new_stats_res = self.client.get("/api/stats")
            self.assertEqual(new_stats_res.status_code, 200)
            self.assertEqual(new_stats_res.json()["total_users"], updated_users_count)

            # Database Explorer reflects current PostgreSQL
            new_schema_res = self.client.get("/api/schema")
            self.assertEqual(new_schema_res.status_code, 200)
            self.assertEqual(new_schema_res.json()["tables"]["users"]["row_count"], updated_users_count)

            # ----------------------------------------------------
            # STEP 8 (Part 2): Ask in the SAME CHAT: "How many users are there now?"
            # ----------------------------------------------------
            chat_res_2 = self.client.post("/api/chat", json={
                "message": "How many users are there now?",
                "chat_id": chat_1_id
            })
            self.assertEqual(chat_res_2.status_code, 200)
            agent_data_2 = chat_res_2.json()
            self.assertTrue(agent_data_2.get("success"))
            self.assertEqual(agent_data_2.get("route"), "sql")
            
            # The agent must return the UPDATED count, not the old initial count
            count_str_2 = f"{updated_users_count:,}"
            self.assertTrue(
                str(updated_users_count) in agent_data_2["answer"] or count_str_2 in agent_data_2["answer"],
                f"Agent in same chat must return updated count {updated_users_count}. Got: {agent_data_2['answer']}"
            )

            # ----------------------------------------------------
            # STEP 9: Create a NEW CHAT and ask the same question
            # ----------------------------------------------------
            chat_2 = ChatStore.create_chat(title="New Chat Verification")
            chat_2_id = chat_2["id"]

            chat_res_3 = self.client.post("/api/chat", json={
                "message": "How many users are currently in the database?",
                "chat_id": chat_2_id
            })
            self.assertEqual(chat_res_3.status_code, 200)
            agent_data_3 = chat_res_3.json()
            self.assertTrue(agent_data_3.get("success"))
            self.assertTrue(
                str(updated_users_count) in agent_data_3["answer"] or count_str_2 in agent_data_3["answer"],
                f"Agent in new chat must return updated count {updated_users_count}. Got: {agent_data_3['answer']}"
            )

            # ----------------------------------------------------
            # STEP 10: Switch back to old chat and verify history
            # ----------------------------------------------------
            old_chat_data = ChatStore.get_chat(chat_1_id)
            self.assertIsNotNone(old_chat_data)
            self.assertEqual(len(old_chat_data["messages"]), 4)  # 2 user msgs + 2 assistant msgs
            self.assertEqual(old_chat_data["messages"][0]["content"], "How many users are there?")
            self.assertEqual(old_chat_data["messages"][2]["content"], "How many users are there now?")

        finally:
            # Cleanup test rows to restore original DB state
            clean_conn = self.db.get_connection()
            if clean_conn:
                with clean_conn.cursor() as cur:
                    cur.execute("DELETE FROM public.users WHERE user_id IN (%s, %s);", (new_test_pk, new_test_pk + 1))
                clean_conn.commit()


if __name__ == "__main__":
    unittest.main()

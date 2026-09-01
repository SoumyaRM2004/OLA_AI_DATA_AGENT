import unittest
import os
import json
from utils.database import DatabaseConnection
from utils.chat_store import ChatStore
from server import app
from fastapi.testclient import TestClient


class TestDataFreshnessAndMultiChat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.db = DatabaseConnection()

    def test_01_database_connection_and_live_schema(self):
        """Verify that Database Explorer and Schema endpoints query PostgreSQL live."""
        res = self.client.get("/api/schema")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("tables", data)
        self.assertIsNone(data.get("error"))

        for tbl in ["users", "vehicles", "rides", "payments", "ratings", "weather_data"]:
            self.assertIn(tbl, data["tables"])
            t_info = data["tables"][tbl]
            self.assertIn("row_count", t_info)
            self.assertIn("columns", t_info)

    def test_02_database_stats_live_kpi(self):
        """Verify that Analytics KPIs are computed directly from current PostgreSQL database."""
        res = self.client.get("/api/stats")
        self.assertEqual(res.status_code, 200)
        stats = res.json()
        self.assertIn("total_users", stats)
        self.assertIn("total_rides", stats)
        self.assertIn("total_vehicles", stats)
        self.assertIn("total_revenue", stats)
        self.assertIn("avg_rating", stats)
        self.assertIn("weather_stats", stats)

        # Cross-verify with direct PostgreSQL query
        db_user_count = self.db.execute_query_structured("SELECT COUNT(*) AS total FROM public.users;")["records"][0]["total"]
        self.assertEqual(stats["total_users"], db_user_count)

        db_ride_count = self.db.execute_query_structured("SELECT COUNT(*) AS total FROM public.rides;")["records"][0]["total"]
        self.assertEqual(stats["total_rides"], db_ride_count)

    def test_03_database_explorer_table_content(self):
        """Verify /api/tables/{table_name} fetches live rows from PostgreSQL."""
        for tbl in ["users", "vehicles", "rides", "payments", "ratings", "weather_data"]:
            res = self.client.get(f"/api/tables/{tbl}?limit=10")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("columns", data)
            self.assertIn("rows", data)
            self.assertIsNone(data.get("error"))

    def test_04_multi_chat_crud_operations(self):
        """Verify creation, retrieval, renaming, clearing, and deleting of independent chat sessions."""
        # 1. Create Chat A
        chat_a = self.client.post("/api/chats", json={"title": "Chat A Initial"}).json()
        self.assertIn("id", chat_a)
        chat_a_id = chat_a["id"]
        self.assertEqual(chat_a["title"], "Chat A Initial")

        # 2. Create Chat B
        chat_b = self.client.post("/api/chats", json={"title": "Chat B Initial"}).json()
        self.assertIn("id", chat_b)
        chat_b_id = chat_b["id"]
        self.assertEqual(chat_b["title"], "Chat B Initial")

        # 3. Add message to Chat A
        msg_a = ChatStore.add_message(chat_a_id, role="user", content="Message in Chat A")
        self.assertEqual(msg_a["chat_id"], chat_a_id)

        # 4. Add message to Chat B
        msg_b = ChatStore.add_message(chat_b_id, role="user", content="Message in Chat B")
        self.assertEqual(msg_b["chat_id"], chat_b_id)

        # 5. Verify isolation: Chat A does not contain Chat B messages
        fetched_a = self.client.get(f"/api/chats/{chat_a_id}").json()
        fetched_b = self.client.get(f"/api/chats/{chat_b_id}").json()

        self.assertEqual(len(fetched_a["messages"]), 1)
        self.assertEqual(fetched_a["messages"][0]["content"], "Message in Chat A")

        self.assertEqual(len(fetched_b["messages"]), 1)
        self.assertEqual(fetched_b["messages"][0]["content"], "Message in Chat B")

        # 6. Rename Chat A
        renamed_a = self.client.put(f"/api/chats/{chat_a_id}", json={"title": "Rainy Ride Analysis"}).json()
        self.assertEqual(renamed_a["title"], "Rainy Ride Analysis")

        # Verify Chat B title is unchanged
        fetched_b_after = self.client.get(f"/api/chats/{chat_b_id}").json()
        self.assertEqual(fetched_b_after["title"], "Chat B Initial")

        # 7. Clear Chat A
        clear_res = self.client.post(f"/api/chats/{chat_a_id}/clear").json()
        self.assertTrue(clear_res.get("success"))
        cleared_a = self.client.get(f"/api/chats/{chat_a_id}").json()
        self.assertEqual(len(cleared_a["messages"]), 0)

        # Verify Chat B messages remain intact
        fetched_b_intact = self.client.get(f"/api/chats/{chat_b_id}").json()
        self.assertEqual(len(fetched_b_intact["messages"]), 1)

        # 8. Delete Chat A and Chat B
        del_a = self.client.delete(f"/api/chats/{chat_a_id}").json()
        self.assertTrue(del_a.get("success"))
        del_b = self.client.delete(f"/api/chats/{chat_b_id}").json()
        self.assertTrue(del_b.get("success"))


if __name__ == "__main__":
    unittest.main()

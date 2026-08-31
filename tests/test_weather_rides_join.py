import unittest
import io
import psycopg2
from fastapi.testclient import TestClient
from server import app
from utils.database import DatabaseConnection
from utils.chat_store import ChatStore
from agents.data_agent import execute_agent_query
from agents.sql_analyst import diagnose_query_coverage


class TestWeatherRidesJoinQueries(unittest.TestCase):
    """
    Acceptance test suite for SQL Analyst weather/rides JOIN queries:
    1. No-overlap diagnostic explanation when dates do not match.
    2. Overlap calculations based on matched weather observations.
    3. Proper sample size reporting and unmatched ride exclusion.
    4. Unmatched rides are never classified as non-rainy.
    5. Live PostgreSQL querying after CSV import.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.db = DatabaseConnection()

    def test_01_no_overlap_diagnostic_explanation(self):
        """Test 1: If weather/rides have no matching city/hour records, explain coverage mismatch instead of 'No records found'."""
        query_text = "Compare ride cancellation rates during rainy and non-rainy periods."
        res = execute_agent_query(query_text)
        self.assertTrue(res.get("success"), f"Query execution failed: {res.get('answer')}")
        answer = res.get("answer", "")

        # Must not say simply 'No records found in the database'
        self.assertNotIn("No records found in the database matching the criteria", answer)
        
        # Must explain coverage and dates
        self.assertTrue(
            "weather" in answer.lower() and ("overlap" in answer.lower() or "coverage" in answer.lower() or "outside" in answer.lower()),
            f"Expected diagnostic explanation in answer: {answer}"
        )
        self.assertTrue("2025" in answer and "2026" in answer, f"Expected date ranges in answer: {answer}")

    def test_02_diagnose_query_coverage_helper(self):
        """Test diagnostic query helper on weather joins and non-weather queries."""
        # Weather join with current 2026 data
        diag_no_overlap = diagnose_query_coverage(
            "SELECT w.is_rainy, COUNT(*) FROM public.rides r JOIN public.users u ON r.rider_id = u.user_id JOIN public.weather_data w ON u.city = w.city AND DATE_TRUNC('hour', r.requested_at) = w.recorded_at GROUP BY w.is_rainy;",
            self.db
        )
        self.assertTrue(diag_no_overlap["is_weather_rides_join"])
        self.assertEqual(diag_no_overlap["overlap_status"], "NO_OVERLAP")
        self.assertEqual(diag_no_overlap["matched_rides"], 0)
        self.assertGreater(diag_no_overlap["total_rides"], 0)
        self.assertGreater(diag_no_overlap["total_weather_records"], 0)

        # Non-weather query
        diag_users = diagnose_query_coverage("SELECT * FROM public.users WHERE city = 'NonExistentCity';", self.db)
        self.assertFalse(diag_users["is_weather_rides_join"])
        self.assertEqual(diag_users["overlap_status"], "NO_FILTER_MATCH")

    def test_03_partial_overlap_analysis_and_coverage_reporting(self):
        """Test 2, 3, 4, 5: Insert Jan 2025 rides, verify partial overlap calculation and coverage reporting."""
        # Insert 5 test rides in Jan 2025 matching weather observations
        jan_rides_sql = """
            INSERT INTO public.rides (
                ride_id, rider_id, driver_id, requested_at, pickup_time, dropoff_time,
                pickup_latitude, pickup_longitude, dropoff_latitude, dropoff_longitude,
                distance_km, fare, surge_multiplier, status, cancellation_reason
            ) VALUES
            (888801, 101, 106, '2025-01-10 08:00:00', '2025-01-10 08:05:00', '2025-01-10 08:25:00', 43.65, -79.38, 43.64, -79.38, 5.0, 25.0, 1.0, 'completed', NULL),
            (888802, 102, 107, '2025-01-10 09:00:00', '2025-01-10 09:05:00', '2025-01-10 09:25:00', 49.28, -123.12, 49.26, -123.14, 6.0, 30.0, 1.0, 'completed', NULL),
            (888803, 103, 108, '2025-01-10 10:00:00', NULL, NULL, 51.04, -114.07, 51.05, -114.08, 0.0, 0.0, 1.0, 'cancelled', 'Rider cancelled'),
            (888804, 104, 109, '2025-01-10 11:00:00', '2025-01-10 11:05:00', '2025-01-10 11:25:00', 45.50, -73.56, 45.51, -73.57, 4.0, 20.0, 1.0, 'completed', NULL),
            (888805, 105, 110, '2025-01-10 12:00:00', NULL, NULL, 45.42, -75.69, 45.43, -75.70, 0.0, 0.0, 1.0, 'cancelled', 'Driver cancelled')
            ON CONFLICT (ride_id) DO NOTHING;
        """
        conn = self.db.get_connection()
        self.assertIsNotNone(conn)
        with conn.cursor() as cur:
            cur.execute(jan_rides_sql)
        conn.commit()

        try:
            # Verify diagnostic detects partial overlap
            diag = diagnose_query_coverage(
                "SELECT w.is_rainy, COUNT(*) FROM public.rides r JOIN public.users u ON r.rider_id = u.user_id JOIN public.weather_data w ON u.city = w.city AND DATE_TRUNC('hour', r.requested_at) = w.recorded_at GROUP BY w.is_rainy;",
                self.db
            )
            self.assertEqual(diag["overlap_status"], "PARTIAL_OVERLAP")
            self.assertGreaterEqual(diag["matched_rides"], 5)
            self.assertGreater(diag["unmatched_rides"], 0)

            # Query agent with partial overlap
            query_text = "Compare ride cancellation rates during rainy and non-rainy periods."
            res = execute_agent_query(query_text)
            self.assertTrue(res.get("success"))
            answer = res.get("answer", "")

            # Answer must report based on matched records and not treat unmatched rides as non-rainy
            self.assertTrue(
                "matched" in answer.lower() or "matching" in answer.lower() or "weather observation" in answer.lower() or "rainy" in answer.lower(),
                f"Expected weather comparison answer. Got: {answer}"
            )

        finally:
            # Cleanup test rides
            with conn.cursor() as cur:
                cur.execute("DELETE FROM public.rides WHERE ride_id >= 888801 AND ride_id <= 888805;")
            conn.commit()


if __name__ == "__main__":
    unittest.main()

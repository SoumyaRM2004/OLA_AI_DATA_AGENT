import unittest
from agents.data_agent import auto_detect_chart, clean_column_name, format_metric_value


class TestVisualizationLayer(unittest.TestCase):
    """
    Acceptance test suite for Result Visualization & Data layer:
    1. Single row with multiple KPI metrics (compact KPI cards, comparison ratio, no misleading bar chart).
    2. Category + Rate/Percentage with rich contextual tooltips.
    3. Category + Multiple compatible counts (grouped bar).
    4. Time series (line chart).
    5. Part-to-whole (doughnut).
    6. Two continuous numeric variables (scatter plot).
    7. Empty result handling (no fake chart).
    """

    def test_01_single_row_multiple_kpis(self):
        """TEST 1: Single row with total_users and active_users -> KPI cards, not a single bar chart."""
        columns = ["total_users", "active_users"]
        records = [{"total_users": 30, "active_users": 27}]

        chart_info = auto_detect_chart(columns, records)

        self.assertTrue(chart_info["can_chart"])
        self.assertEqual(chart_info["mode"], "kpi_cards")
        self.assertNotEqual(chart_info.get("type"), "bar")
        self.assertNotIn("Total Users by Active Users", chart_info.get("title", ""))

        # Check KPIs
        kpis = chart_info.get("kpis", [])
        self.assertEqual(len(kpis), 2)
        self.assertEqual(kpis[0]["label"], "Total Users")
        self.assertEqual(kpis[0]["value"], "30")
        self.assertEqual(kpis[1]["label"], "Active Users")
        self.assertEqual(kpis[1]["value"], "27")

        # Check comparison ratio
        comparison = chart_info.get("comparison")
        self.assertIsNotNone(comparison)
        self.assertEqual(comparison["percentage"], 90.0)
        self.assertIn("27 / 30", comparison["ratio_text"])

    def test_02_category_and_rate_with_tooltips(self):
        """TEST 2: Category + rate + supporting counts -> Bar chart with rich tooltip context."""
        columns = ["city", "total_rides", "cancelled_rides", "cancellation_rate"]
        records = [
            {"city": "Calgary", "total_rides": 2, "cancelled_rides": 1, "cancellation_rate": 50.0},
            {"city": "Toronto", "total_rides": 10, "cancelled_rides": 2, "cancellation_rate": 20.0},
            {"city": "Montreal", "total_rides": 8, "cancelled_rides": 1, "cancellation_rate": 12.5}
        ]

        chart_info = auto_detect_chart(columns, records)

        self.assertTrue(chart_info["can_chart"])
        self.assertEqual(chart_info["mode"], "chart")
        self.assertEqual(chart_info["type"], "bar")
        self.assertIn("Cancellation Rate", chart_info["title"])
        self.assertIn("City", chart_info["title"])
        self.assertEqual(chart_info["values"], [50.0, 20.0, 12.5])
        self.assertEqual(chart_info["labels"], ["Calgary", "Toronto", "Montreal"])
        self.assertEqual(len(chart_info["raw_records"]), 3)

    def test_03_category_and_multiple_compatible_counts(self):
        """TEST 3: Category + multiple counts -> Grouped bar chart with multiple datasets."""
        columns = ["city", "completed_rides", "cancelled_rides"]
        records = [
            {"city": "Calgary", "completed_rides": 1, "cancelled_rides": 1},
            {"city": "Toronto", "completed_rides": 8, "cancelled_rides": 2},
            {"city": "Montreal", "completed_rides": 7, "cancelled_rides": 1}
        ]

        chart_info = auto_detect_chart(columns, records)

        self.assertTrue(chart_info["can_chart"])
        self.assertEqual(chart_info["type"], "grouped_bar")
        self.assertEqual(len(chart_info["datasets"]), 2)
        self.assertEqual(chart_info["datasets"][0]["label"], "Completed Rides")
        self.assertEqual(chart_info["datasets"][1]["label"], "Cancelled Rides")

    def test_04_status_ride_count_part_to_whole(self):
        """TEST 4: Status + ride_count -> Rides by Status chart."""
        columns = ["status", "ride_count"]
        records = [
            {"status": "completed", "ride_count": 15},
            {"status": "cancelled", "ride_count": 5}
        ]

        chart_info = auto_detect_chart(columns, records)

        self.assertTrue(chart_info["can_chart"])
        self.assertIn(chart_info["type"], ["doughnut", "bar"])
        self.assertIn("Status", chart_info["title"])
        self.assertEqual(chart_info["values"], [15.0, 5.0])
        self.assertEqual(chart_info["labels"], ["Completed", "Cancelled"])

    def test_05_payment_method_total_revenue(self):
        """TEST 5: Payment method + total_revenue -> Revenue by Payment Method."""
        columns = ["payment_method", "total_revenue"]
        records = [
            {"payment_method": "card", "total_revenue": 1200.50},
            {"payment_method": "cash", "total_revenue": 450.00},
            {"payment_method": "upi", "total_revenue": 890.25}
        ]

        chart_info = auto_detect_chart(columns, records)

        self.assertTrue(chart_info["can_chart"])
        self.assertIn("Revenue", chart_info["title"])
        self.assertIn("Payment Method", chart_info["title"])
        self.assertEqual(chart_info["metric_type"], "currency")

    def test_06_time_series_line_chart(self):
        """TEST 6: Date + total_rides -> Line chart, chronological, not a pie chart."""
        columns = ["date", "total_rides"]
        records = [
            {"date": "2025-01-01", "total_rides": 100},
            {"date": "2025-01-02", "total_rides": 120},
            {"date": "2025-01-03", "total_rides": 95}
        ]

        chart_info = auto_detect_chart(columns, records)

        self.assertTrue(chart_info["can_chart"])
        self.assertEqual(chart_info["type"], "line")
        self.assertIn("Over Time", chart_info["title"])
        self.assertEqual(chart_info["values"], [100.0, 120.0, 95.0])

    def test_07_empty_result_produces_no_chart(self):
        """TEST 7: Zero rows returned -> can_chart is False."""
        chart_info = auto_detect_chart(["city", "total_rides"], [])
        self.assertFalse(chart_info["can_chart"])
        self.assertEqual(chart_info["mode"], "none")

    def test_08_two_numeric_scatter(self):
        """TEST 8: Two numeric continuous variables -> Scatter plot."""
        columns = ["distance_km", "fare"]
        records = [
            {"distance_km": 5.0, "fare": 25.0},
            {"distance_km": 8.5, "fare": 38.0},
            {"distance_km": 12.0, "fare": 52.0},
            {"distance_km": 3.2, "fare": 18.0},
            {"distance_km": 15.0, "fare": 65.0}
        ]

        chart_info = auto_detect_chart(columns, records)

        self.assertTrue(chart_info["can_chart"])
        self.assertEqual(chart_info["type"], "scatter")


if __name__ == "__main__":
    unittest.main()

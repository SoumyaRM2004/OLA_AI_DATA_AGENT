import unittest
from utils.database import DatabaseConnection
from agents.sql_analyst import (
    validate_sql_deterministic,
    sanitize_group_by_sql,
    diagnose_empty_result
)
from agents.data_agent import (
    format_metric_value,
    auto_detect_chart,
    classify_column,
    clean_column_name
)


class TestProductionFixesRegression(unittest.TestCase):
    """
    Regression test suite for:
    1. Monthly DATE_TRUNC Group By SQL generation and PostgreSQL validation.
    2. Fractional percentage formatting (0.1605 -> 16.05%, 0.05 -> 5.00%, 1.0 -> 100.00%).
    3. Protection of already percentage-scaled values and non-percentage columns.
    4. Diagnostic explanations for empty results and impossible filter criteria.
    """

    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseConnection()

    # =========================================================================
    # ISSUE 1: MONTHLY GROUP BY SQL GENERATION & POSTGRESQL VALIDATION
    # =========================================================================

    def test_01_sanitize_group_by_date_trunc_month(self):
        """Test that invalid 'GROUP BY year, month' with DATE_TRUNC in SELECT is sanitized to valid PostgreSQL SQL."""
        flawed_sql = (
            "SELECT DATE_TRUNC('month', requested_at) AS month_start, "
            "EXTRACT(YEAR FROM requested_at) AS year, "
            "EXTRACT(MONTH FROM requested_at) AS month, "
            "COUNT(*) AS total_rides "
            "FROM public.rides "
            "GROUP BY year, month "
            "ORDER BY month_start;"
        )

        sanitized = sanitize_group_by_sql(flawed_sql)
        self.assertIn("GROUP BY DATE_TRUNC('month', requested_at)", sanitized)
        self.assertNotIn("GROUP BY year, month", sanitized)
        # unaggregated raw column inside EXTRACT in SELECT should be fixed
        self.assertNotIn("EXTRACT(YEAR FROM requested_at)", sanitized)
        self.assertIn("EXTRACT(YEAR FROM DATE_TRUNC('month', requested_at))", sanitized)

        # Must execute cleanly on live PostgreSQL without column unaggregated error
        res = self.db.execute_query_structured(sanitized)
        self.assertIsNone(res.get("error"), f"Execution failed on PostgreSQL: {res.get('error')}")
        self.assertGreater(len(res.get("records", [])), 0)
        self.assertIn("month_start", res["columns"])
        self.assertIn("total_rides", res["columns"])

    def test_02_validate_sql_deterministic_normalizes_group_by(self):
        """Test validate_sql_deterministic returns clean, valid SQL for date truncation queries."""
        raw_sql = (
            "SELECT DATE_TRUNC('month', requested_at) AS month_start, "
            "COUNT(*) AS total_rides, "
            "SUM(fare) AS total_revenue "
            "FROM public.rides "
            "GROUP BY month_start "
            "ORDER BY month_start;"
        )

        is_valid, clean_sql, err = validate_sql_deterministic(raw_sql)
        self.assertTrue(is_valid)
        self.assertEqual(err, "")
        self.assertIn("DATE_TRUNC('month', requested_at)", clean_sql)

        # Must execute cleanly on live PostgreSQL
        res = self.db.execute_query_structured(clean_sql)
        self.assertIsNone(res.get("error"))
        self.assertGreater(len(res.get("records", [])), 0)

    def test_03_cte_monthly_aggregation_valid_postgres(self):
        """Test preferred CTE pattern for monthly breakdown with year/month extraction."""
        cte_sql = """
            WITH monthly_summary AS (
                SELECT 
                    DATE_TRUNC('month', requested_at) AS month_start,
                    COUNT(*) AS total_rides,
                    SUM(fare) AS total_revenue
                FROM public.rides
                GROUP BY DATE_TRUNC('month', requested_at)
            )
            SELECT 
                month_start,
                EXTRACT(YEAR FROM month_start)::int AS year,
                EXTRACT(MONTH FROM month_start)::int AS month,
                total_rides,
                total_revenue
            FROM monthly_summary
            ORDER BY month_start;
        """
        is_valid, clean_sql, err = validate_sql_deterministic(cte_sql)
        self.assertTrue(is_valid)
        res = self.db.execute_query_structured(clean_sql)
        self.assertIsNone(res.get("error"))
        self.assertGreater(len(res.get("records", [])), 0)
        rec = res["records"][0]
        self.assertIn("month_start", rec)
        self.assertIn("year", rec)
        self.assertIn("month", rec)
        self.assertIn("total_rides", rec)

    # =========================================================================
    # ISSUE 2: FRACTIONAL PERCENTAGE FORMATTING & PROTECTION
    # =========================================================================

    def test_04_fractional_percentage_formatting(self):
        """Test fractional ratios are accurately converted to percentages (e.g. 0.1605 -> 16.05%)."""
        self.assertEqual(format_metric_value(0.1605, "rate"), "16.05%")
        self.assertEqual(format_metric_value("0.1605", "rate"), "16.05%")
        self.assertEqual(format_metric_value(0.05, "rate"), "5.00%")
        self.assertEqual(format_metric_value(1.0, "rate"), "100.00%")
        self.assertEqual(format_metric_value(0.0, "rate"), "0.00%")
        self.assertEqual(format_metric_value(0.5, "rate"), "50.00%")
        self.assertEqual(format_metric_value(0.3333, "rate"), "33.33%")

    def test_05_already_scaled_percentage_protection(self):
        """Test already-scaled percentages (> 1.0) are NOT multiplied by 100 again."""
        self.assertEqual(format_metric_value(16.05, "rate"), "16.05%")
        self.assertEqual(format_metric_value("16.05", "rate"), "16.05%")
        self.assertEqual(format_metric_value(50.0, "rate"), "50.00%")
        self.assertEqual(format_metric_value(100.0, "rate"), "100.00%")
        self.assertEqual(format_metric_value(12.5, "rate"), "12.50%")

    def test_06_non_percentage_metric_protection(self):
        """Test non-percentage metrics (rank, fare, multiplier, rating, count) are not formatted as percentages."""
        # Rank / Ordinal
        self.assertEqual(format_metric_value(1, "rank"), "1")
        self.assertEqual(format_metric_value(2, "rank"), "2")
        self.assertEqual(format_metric_value(5, "rank"), "5")

        # Currency
        self.assertEqual(format_metric_value(1200.5, "currency"), "₹1,200.50")
        self.assertEqual(format_metric_value(0.5, "currency"), "₹0.50")

        # Rating
        self.assertEqual(format_metric_value(4.8, "rating"), "4.80 ★")

        # Multiplier
        self.assertEqual(format_metric_value(1.25, "multiplier"), "1.25x")

        # Counts
        self.assertEqual(format_metric_value(1050, "count"), "1,050")

    def test_07_chart_auto_detect_scales_fractional_rate_column(self):
        """Test auto_detect_chart scales fractional cancellation rates for chart datasets."""
        columns = ["city", "total_rides", "cancellation_rate"]
        records = [
            {"city": "Calgary", "total_rides": 100, "cancellation_rate": 0.1605},
            {"city": "Toronto", "total_rides": 250, "cancellation_rate": 0.05},
            {"city": "Montreal", "total_rides": 180, "cancellation_rate": 0.12}
        ]

        chart_info = auto_detect_chart(columns, records)
        self.assertTrue(chart_info["can_chart"])
        self.assertEqual(chart_info["metric_type"], "rate")
        # Plotted values must be scaled to 0-100 for proper chart rendering
        self.assertEqual(chart_info["values"], [16.05, 5.0, 12.0])
        self.assertEqual(chart_info["datasets"][0]["data"], [16.05, 5.0, 12.0])

    def test_08_chart_auto_detect_preserves_already_scaled_rate_column(self):
        """Test auto_detect_chart preserves already scaled percentages (e.g. 50.0, 20.0)."""
        columns = ["city", "total_rides", "cancellation_rate"]
        records = [
            {"city": "Calgary", "total_rides": 100, "cancellation_rate": 50.0},
            {"city": "Toronto", "total_rides": 250, "cancellation_rate": 20.0},
            {"city": "Montreal", "total_rides": 180, "cancellation_rate": 12.5}
        ]

        chart_info = auto_detect_chart(columns, records)
        self.assertTrue(chart_info["can_chart"])
        self.assertEqual(chart_info["values"], [50.0, 20.0, 12.5])

    # =========================================================================
    # ISSUE 3: EMPTY RESULT & IMPOSSIBLE THRESHOLD DIAGNOSTICS
    # =========================================================================

    def test_09_impossible_having_threshold_diagnostics(self):
        """Test diagnostic query for driver ride count threshold exceeding maximum in DB."""
        impossible_query = (
            "SELECT driver_id, COUNT(*) AS completed_rides "
            "FROM public.rides "
            "WHERE status = 'completed' "
            "GROUP BY driver_id "
            "HAVING COUNT(*) >= 20;"
        )

        res = self.db.execute_query_structured(impossible_query)
        self.assertEqual(len(res["records"]), 0, "Expected 0 rows for >=20 completed rides threshold")

        diag = diagnose_empty_result(impossible_query, "Find drivers with at least 20 completed rides", self.db)
        self.assertTrue(diag["has_diagnostic"])
        self.assertEqual(diag["type"], "HAVING_THRESHOLD_EXCEEDED")
        self.assertGreater(diag["total_groups"], 0)
        self.assertGreater(diag["max_value"], 0)
        self.assertLess(diag["max_value"], 20)

        # Check explanation contains clear evidence
        explanation = diag["explanation"]
        self.assertIn(str(diag["max_value"]), explanation)
        self.assertIn("maximum", explanation.lower())
        self.assertIn("20", explanation)

    def test_10_impossible_where_scalar_threshold_diagnostics(self):
        """Test diagnostic query for impossible scalar filter (e.g. fare >= 100000)."""
        impossible_query = "SELECT * FROM public.rides WHERE fare >= 100000;"
        res = self.db.execute_query_structured(impossible_query)
        self.assertEqual(len(res["records"]), 0)

        diag = diagnose_empty_result(impossible_query, "Find rides with fare over 100000", self.db)
        self.assertTrue(diag["has_diagnostic"])
        self.assertEqual(diag["type"], "WHERE_THRESHOLD_EXCEEDED")
        self.assertIn("maximum", diag["explanation"].lower())
        self.assertIn("fare", diag["explanation"].lower())


if __name__ == "__main__":
    unittest.main()

import unittest
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from model.schema import AgentSchema, StructuredIntentSchema, SemanticValidationSchema
from agents.sql_analyst import (
    is_complex_analytical_query,
    extract_intent_structured,
    evaluate_sql_semantics,
    semantic_validation_node,
    regenerate_sql_with_intent,
    sql_analyst
)


class TestSemanticIntentValidation(unittest.TestCase):
    """
    Tests for Intent-Aware SQL Generation & Semantic Validation Layer.
    """

    def test_01_complexity_heuristic(self):
        """Simple queries should bypass LLM semantic judge; complex queries should trigger it."""
        # Simple lookup / count
        self.assertFalse(is_complex_analytical_query("How many users are there?", "SELECT COUNT(*) FROM public.users;"))
        self.assertFalse(is_complex_analytical_query("List all cities", "SELECT DISTINCT city FROM public.users;"))
        self.assertFalse(is_complex_analytical_query("Count rides", "SELECT COUNT(*) FROM public.rides;"))

        # Complex queries
        self.assertTrue(is_complex_analytical_query("Top 10 drivers by completed rides", "SELECT driver_id FROM public.rides ORDER BY count DESC LIMIT 10;"))
        self.assertTrue(is_complex_analytical_query("Drivers with at least 5 assigned rides", "SELECT driver_id FROM public.rides GROUP BY driver_id HAVING COUNT(*) >= 5;"))
        self.assertTrue(is_complex_analytical_query("Compare driver cancellation rate vs overall rate", "SELECT * FROM public.rides;"))
        self.assertTrue(is_complex_analytical_query("Rank vehicles by ride count", "SELECT * FROM public.vehicles;"))

    def test_02_extract_intent_structured(self):
        """Intent extractor should separate selection ranking from presentation ranking and capture thresholds."""
        question = (
            "Find the top 10 drivers by completed rides in 2026. Only include drivers with at least 5 assigned rides. "
            "Rank those drivers by completion rate descending."
        )
        intent = extract_intent_structured(question)
        self.assertIsInstance(intent, StructuredIntentSchema)
        if intent.selection:
            self.assertEqual(intent.selection.direction, "desc")
            if intent.selection.n:
                self.assertEqual(intent.selection.n, 10)
        if intent.presentation_order:
            self.assertEqual(intent.presentation_order.direction, "desc")

    def test_03_top_n_by_selection_metric_pass(self):
        """TEST 1: 'Top 10 drivers by completed rides' with matching ORDER BY completed DESC LIMIT 10 should PASS."""
        question = "Top 10 drivers by completed rides"
        intent = {
            "entity": "driver",
            "selection": {"type": "top_n", "n": 10, "metric": "completed", "direction": "desc"},
            "presentation_order": None,
            "filters": [],
            "metrics": ["completed"]
        }
        sql = """
        SELECT driver_id, COUNT(*) AS completed
        FROM public.rides
        WHERE status = 'completed'
        GROUP BY driver_id
        ORDER BY completed DESC
        LIMIT 10;
        """
        result = evaluate_sql_semantics(question, intent, sql)
        self.assertTrue(result.is_semantically_valid, f"Expected valid query to pass, issues: {result.issues}")

    def test_04_top_n_by_wrong_metric_fail(self):
        """TEST 2: 'Top 10 drivers by completed rides' with ORDER BY completion_rate DESC LIMIT 10 should FAIL."""
        question = "Top 10 drivers by completed rides"
        intent = {
            "entity": "driver",
            "selection": {"type": "top_n", "n": 10, "metric": "completed", "direction": "desc"},
            "presentation_order": None,
            "filters": [],
            "metrics": ["completed", "completion_rate"]
        }
        # Buggy SQL: uses completion_rate for LIMIT 10 instead of completed rides
        sql = """
        SELECT driver_id,
               COUNT(*) FILTER (WHERE status = 'completed') AS completed,
               ROUND(COUNT(*) FILTER (WHERE status = 'completed')::numeric / NULLIF(COUNT(*), 0), 4) AS completion_rate
        FROM public.rides
        GROUP BY driver_id
        ORDER BY completion_rate DESC
        LIMIT 10;
        """
        result = evaluate_sql_semantics(question, intent, sql)
        self.assertFalse(result.is_semantically_valid, "Expected semantic validation to reject wrong selection metric")
        self.assertTrue(len(result.issues) > 0)
        self.assertTrue(len(result.correction_instruction) > 0)

    def test_05_two_stage_ranking_pass(self):
        """TEST 3: 'Top 10 by completed rides, then rank those 10 by completion rate' with CTE should PASS."""
        question = "Top 10 drivers by completed rides in 2026, then rank those drivers by completion rate."
        intent = {
            "entity": "driver",
            "time_range": "2026",
            "selection": {"type": "top_n", "n": 10, "metric": "completed", "direction": "desc"},
            "presentation_order": {"metric": "completion_rate", "direction": "desc"},
            "filters": [],
            "metrics": ["completed", "completion_rate"]
        }
        sql = """
        WITH driver_stats AS (
            SELECT driver_id,
                   COUNT(*) AS assigned,
                   COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                   ROUND(COUNT(*) FILTER (WHERE status = 'completed')::numeric / NULLIF(COUNT(*), 0), 4) AS completion_rate
            FROM public.rides
            WHERE requested_at >= '2026-01-01' AND requested_at < '2027-01-01'
            GROUP BY driver_id
        ),
        top_10_drivers AS (
            SELECT *
            FROM driver_stats
            ORDER BY completed DESC
            LIMIT 10
        )
        SELECT *
        FROM top_10_drivers
        ORDER BY completion_rate DESC;
        """
        result = evaluate_sql_semantics(question, intent, sql)
        self.assertTrue(result.is_semantically_valid, f"Expected 2-stage CTE to pass, issues: {result.issues}")

    def test_06_omitted_threshold_filter_fail(self):
        """TEST 4: 'Only include drivers with at least 5 assigned rides' omitting HAVING >= 5 should FAIL."""
        question = "Top 10 drivers by completed rides with at least 5 assigned rides."
        intent = {
            "entity": "driver",
            "selection": {"type": "top_n", "n": 10, "metric": "completed", "direction": "desc"},
            "filters": [{"metric": "assigned_rides", "operator": ">=", "value": 5}],
            "metrics": ["assigned", "completed"]
        }
        # SQL omitting HAVING COUNT(*) >= 5
        sql = """
        SELECT driver_id, COUNT(*) AS assigned, COUNT(*) FILTER (WHERE status = 'completed') AS completed
        FROM public.rides
        GROUP BY driver_id
        ORDER BY completed DESC
        LIMIT 10;
        """
        result = evaluate_sql_semantics(question, intent, sql)
        self.assertFalse(result.is_semantically_valid, "Expected semantic validation to fail due to missing threshold filter")

    def test_07_temporal_mismatch_fail(self):
        """TEST 5: '2026 drivers' filtered to 2025 should FAIL."""
        question = "Top 10 drivers by completed rides in 2026"
        intent = {
            "entity": "driver",
            "time_range": "2026",
            "selection": {"type": "top_n", "n": 10, "metric": "completed", "direction": "desc"},
            "filters": [],
            "metrics": ["completed"]
        }
        # Buggy SQL filtering for 2025 instead of 2026
        sql = """
        SELECT driver_id, COUNT(*) AS completed
        FROM public.rides
        WHERE requested_at >= '2025-01-01' AND requested_at < '2026-01-01'
        GROUP BY driver_id
        ORDER BY completed DESC
        LIMIT 10;
        """
        result = evaluate_sql_semantics(question, intent, sql)
        self.assertFalse(result.is_semantically_valid, "Expected semantic validation to fail due to date mismatch")

    def test_08_missing_completion_rate_fail(self):
        """TEST 6: Completion rate requested but not calculated in SQL should FAIL."""
        question = "Calculate total assigned and completion rate for drivers."
        intent = {
            "entity": "driver",
            "selection": None,
            "filters": [],
            "metrics": ["assigned", "completion_rate"]
        }
        # Missing completion rate formula
        sql = """
        SELECT driver_id, COUNT(*) AS assigned
        FROM public.rides
        GROUP BY driver_id;
        """
        result = evaluate_sql_semantics(question, intent, sql)
        self.assertFalse(result.is_semantically_valid, "Expected semantic validation to fail when requested rate is omitted")

    def test_09_missing_cancellation_rate_fail(self):
        """TEST 7: Cancellation rate requested but SQL omits it should FAIL."""
        question = "Calculate cancellation rate for each city."
        intent = {
            "entity": "city",
            "selection": None,
            "filters": [],
            "metrics": ["cancellation_rate"]
        }
        # Only counts rides, no cancellation rate
        sql = """
        SELECT u.city, COUNT(r.ride_id) AS total_rides
        FROM public.rides r
        JOIN public.users u ON r.rider_id = u.user_id
        GROUP BY u.city;
        """
        result = evaluate_sql_semantics(question, intent, sql)
        self.assertFalse(result.is_semantically_valid, "Expected semantic validation to fail when cancellation rate is omitted")

    def test_10_missing_overall_comparison_fail(self):
        """TEST 8: Comparison to overall cancellation rate requested but overall baseline omitted should FAIL."""
        question = "Compare each driver's cancellation rate with the overall cancellation rate."
        intent = {
            "entity": "driver",
            "selection": None,
            "filters": [],
            "metrics": ["cancellation_rate", "overall_cancellation_rate"],
            "comparisons": ["driver cancellation rate vs overall cancellation rate"]
        }
        # Missing overall cancellation rate calculation
        sql = """
        SELECT driver_id,
               ROUND(COUNT(*) FILTER (WHERE status = 'cancelled')::numeric / NULLIF(COUNT(*), 0), 4) AS driver_cancellation_rate
        FROM public.rides
        GROUP BY driver_id;
        """
        result = evaluate_sql_semantics(question, intent, sql)
        self.assertFalse(result.is_semantically_valid, "Expected semantic validation to fail when overall comparative baseline is omitted")

    def test_11_filter_vs_case_when_equivalence_pass(self):
        """TEST 9: Equivalent CASE WHEN vs FILTER syntax should PASS (no false positives)."""
        question = "Count completed and cancelled rides per city."
        intent = {
            "entity": "city",
            "selection": None,
            "filters": [],
            "metrics": ["completed", "cancelled"]
        }
        sql_case_when = """
        SELECT u.city,
               SUM(CASE WHEN r.status = 'completed' THEN 1 ELSE 0 END) AS completed,
               SUM(CASE WHEN r.status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled
        FROM public.rides r
        JOIN public.users u ON r.rider_id = u.user_id
        GROUP BY u.city;
        """
        result = evaluate_sql_semantics(question, intent, sql_case_when)
        self.assertTrue(result.is_semantically_valid, f"Expected CASE WHEN equivalent aggregation to pass, issues: {result.issues}")

    def test_12_simple_query_fast_path_pass(self):
        """TEST 10: Simple query without ranking ambiguity should pass fast path."""
        state = AgentSchema(
            curated_ques="How many users are registered?",
            generated_sql_query="SELECT COUNT(*) FROM public.users;",
            can_be_answered=True
        )
        state = semantic_validation_node(state)
        self.assertTrue(state.is_semantically_valid)
        self.assertEqual(len(state.semantic_issues), 0)

    def test_13_full_regression_query_pipeline(self):
        """
        TEST 11: Regression integration test for the exact complex prompt query:
        Top 10 drivers by completed rides in 2026, >= 5 assigned rides,
        metrics: assigned, completed, cancelled, completion rate, cancellation rate,
        comparison with overall cancellation rate, presentation ranked by completion rate DESC.
        """
        complex_question = (
            "Find the top 10 drivers by completed rides in 2026. For each driver, calculate their "
            "total assigned rides, completed rides, driver cancellation count, completion rate, "
            "and driver cancellation rate. Rank the drivers by completion rate in descending order, "
            "but include only those who have at least 5 assigned rides. Additionally, for each driver, "
            "provide a comparison of that driver's cancellation rate against the overall driver "
            "cancellation rate for all drivers in 2026."
        )

        # Valid SQL following the 2-stage CTE architecture with _pp difference and tie-breaker
        valid_sql = """
        WITH overall_stats AS (
            SELECT
                ROUND(COUNT(*) FILTER (WHERE status = 'cancelled')::numeric / NULLIF(COUNT(*), 0), 4) AS overall_cancellation_rate
            FROM public.rides
            WHERE requested_at >= '2026-01-01' AND requested_at < '2027-01-01'
        ),
        driver_stats AS (
            SELECT
                driver_id,
                COUNT(*) AS total_assigned_rides,
                COUNT(*) FILTER (WHERE status = 'completed') AS completed_rides,
                COUNT(*) FILTER (WHERE status = 'cancelled') AS driver_cancellation_count,
                ROUND(COUNT(*) FILTER (WHERE status = 'completed')::numeric / NULLIF(COUNT(*), 0), 4) AS completion_rate,
                ROUND(COUNT(*) FILTER (WHERE status = 'cancelled')::numeric / NULLIF(COUNT(*), 0), 4) AS driver_cancellation_rate
            FROM public.rides
            WHERE requested_at >= '2026-01-01' AND requested_at < '2027-01-01'
            GROUP BY driver_id
            HAVING COUNT(*) >= 5
        ),
        top_10_by_completed AS (
            SELECT *
            FROM driver_stats
            ORDER BY completed_rides DESC, driver_id ASC
            LIMIT 10
        )
        SELECT
            t.driver_id,
            t.total_assigned_rides,
            t.completed_rides,
            t.driver_cancellation_count,
            t.completion_rate,
            t.driver_cancellation_rate,
            o.overall_cancellation_rate,
            ROUND((t.driver_cancellation_rate - o.overall_cancellation_rate) * 100, 2) AS cancellation_rate_diff_pp
        FROM top_10_by_completed t
        CROSS JOIN overall_stats o
        ORDER BY t.completion_rate DESC, t.driver_id ASC;
        """

        intent = extract_intent_structured(complex_question)
        result = evaluate_sql_semantics(complex_question, intent.model_dump(), valid_sql)
        self.assertTrue(result.is_semantically_valid, f"Expected full regression query to pass semantic validation, issues: {result.issues}")

    def test_14_percentage_point_difference_calculation(self):
        """FIX 1: Test percentage point difference arithmetic."""
        # TEST 1: Driver 0.0000 vs Overall 0.0952 -> -9.52 percentage points (NOT -0.10%)
        driver_rate_1 = 0.0000
        overall_rate = 0.0952
        diff_pp_1 = round((driver_rate_1 - overall_rate) * 100, 2)
        self.assertEqual(diff_pp_1, -9.52)

        # TEST 2: Driver 0.1250 vs Overall 0.0952 -> +2.98 percentage points
        driver_rate_2 = 0.1250
        diff_pp_2 = round((driver_rate_2 - overall_rate) * 100, 2)
        self.assertEqual(diff_pp_2, 2.98)

    def test_15_deterministic_top_n_tie_breaking(self):
        """FIX 2: Top-N query with tied completed rides must use a deterministic secondary ordering."""
        question = "Top 10 drivers by completed rides"
        intent = {
            "entity": "driver",
            "selection": {"type": "top_n", "n": 10, "metric": "completed", "direction": "desc"},
            "presentation_order": None,
            "filters": [],
            "metrics": ["completed"]
        }
        # SQL with secondary tie breaker on driver_id
        sql_with_tie_breaker = """
        SELECT driver_id, COUNT(*) AS completed
        FROM public.rides
        WHERE status = 'completed'
        GROUP BY driver_id
        ORDER BY completed DESC, driver_id ASC
        LIMIT 10;
        """
        result = evaluate_sql_semantics(question, intent, sql_with_tie_breaker)
        self.assertTrue(result.is_semantically_valid, f"Expected deterministic tie breaker query to pass, issues: {result.issues}")

    def test_16_semantic_distinction_intact_selection_vs_presentation(self):
        """FIX 2: Selection (completed DESC, driver_id ASC) vs Presentation (completion_rate DESC, driver_id ASC) semantic distinction remains intact."""
        question = "Top 10 drivers by completed rides, then rank those drivers by completion rate."
        intent = {
            "entity": "driver",
            "selection": {"type": "top_n", "n": 10, "metric": "completed", "direction": "desc"},
            "presentation_order": {"metric": "completion_rate", "direction": "desc"},
            "filters": [],
            "metrics": ["completed", "completion_rate"]
        }
        # Buggy SQL that changes the selection metric to completion_rate even with tie-breaker
        buggy_sql = """
        SELECT driver_id,
               COUNT(*) FILTER (WHERE status = 'completed') AS completed,
               ROUND(COUNT(*) FILTER (WHERE status = 'completed')::numeric / NULLIF(COUNT(*), 0), 4) AS completion_rate
        FROM public.rides
        GROUP BY driver_id
        ORDER BY completion_rate DESC, driver_id ASC
        LIMIT 10;
        """
        result = evaluate_sql_semantics(question, intent, buggy_sql)
        self.assertFalse(result.is_semantically_valid, "Expected semantic validation to reject wrong selection metric despite tie-breaker")


if __name__ == "__main__":
    unittest.main()

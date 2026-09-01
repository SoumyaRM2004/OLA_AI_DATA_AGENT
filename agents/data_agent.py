import os
import sys
import logging
from typing import Dict, Any, List, Optional

logging.getLogger("google.genai").setLevel(logging.ERROR)
logging.getLogger("google_genai").setLevel(logging.ERROR)

sys.path.append(
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..")
    )
)

from utils.llm_pick import pick_llm, get_message_text
from model.schema import RouterSchema, DataAgentSchema
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from agents.etl_analyst import etl_analyst
from agents.sql_analyst import sql_analyst

llm_router = pick_llm("low").with_structured_output(RouterSchema, method="json_mode")


# ----------------------- DATA AGENT NODES -----------------------

def router_node(state: DataAgentSchema) -> DataAgentSchema:
    messages = get_message_text(state.messages[-1])
    try:
        route_response_dict = llm_router.invoke(
            f"""Classify whether this query requires querying an SQL database or running an ETL task (API extraction / file transformation):
Query: {messages}
Return 'sql' for database questions/analytics, or 'etl' for API extraction/data transformations."""
        )
        state.route_response = route_response_dict.answer
    except Exception:
        # Fallback: rule-based / groq fallback on transient network disconnect
        lower_q = messages.lower()
        if any(k in lower_q for k in ["extract", "transform", "fetch api", "http://", "https://", "load to database", "save to data/"]):
            state.route_response = "etl"
        else:
            state.route_response = "sql"
    return state


def etl_node(state: DataAgentSchema) -> DataAgentSchema:
    messages = get_message_text(state.messages[-1])
    response = etl_analyst.invoke(
        {
            "messages": [HumanMessage(content=messages)]
        }
    )
    last_msg = response["messages"][-1]
    final_text = get_message_text(last_msg)

    state.final_answer = final_text
    state.etl_state = {"raw_messages": [str(m) for m in response.get("messages", [])], "result": final_text}
    state.messages = state.messages + [AIMessage(content=final_text)]
    return state


def sql_node(state: DataAgentSchema) -> DataAgentSchema:
    message = get_message_text(state.messages[-1])
    input_schema = {
        "messages": [],
        "user_question": message,
        "curated_ques": "",
        "Prompt_query_context": "",
        "can_be_answered": True,
        "schema_explanation": "",
        "generated_sql_query": "",
        "is_safe": "No",
        "comments": "",
        "sql_query_execution_result": "",
        "data_columns": [],
        "data_rows": [],
        "data_dicts": [],
        "final_answer": "",
        "error": "",
        "session_id": state.session_id
    }

    response = sql_analyst.invoke(input_schema)

    state.sql_state = {
        "curated_ques": response.get("curated_ques", ""),
        "can_be_answered": response.get("can_be_answered", True),
        "schema_explanation": response.get("schema_explanation", ""),
        "generated_sql_query": response.get("generated_sql_query", ""),
        "is_safe": response.get("is_safe", "No"),
        "comments": response.get("comments", ""),
        "data_columns": response.get("data_columns", []),
        "data_rows": response.get("data_rows", []),
        "data_dicts": response.get("data_dicts", []),
        "execution_result": response.get("sql_query_execution_result", ""),
        "final_answer": response.get("final_answer", ""),
        "error": response.get("error", "")
    }

    state.final_answer = response.get("final_answer", "")
    state.messages = state.messages + [AIMessage(content=state.final_answer)]
    return state


# ----------------------- BUILD GRAPH -----------------------

data_agent_graph = StateGraph(DataAgentSchema)
data_agent_graph.add_node("router_node", router_node)
data_agent_graph.add_node("etl_node", etl_node)
data_agent_graph.add_node("sql_node", sql_node)

data_agent_graph.add_edge(START, "router_node")


def route_edge(state: DataAgentSchema) -> str:
    if state.route_response == "sql":
        return "sql_node"
    elif state.route_response == "etl":
        return "etl_node"
    else:
        return "sql_node"


data_agent_graph.add_conditional_edges(
    "router_node",
    route_edge,
    {
        "sql_node": "sql_node",
        "etl_node": "etl_node"
    }
)

data_agent_graph.add_edge("sql_node", END)
data_agent_graph.add_edge("etl_node", END)

data_agent = data_agent_graph.compile()


# ----------------------- UNIFIED QUERY HELPER -----------------------

# ----------------------- UNIFIED QUERY HELPER & VISUALIZATION ENGINE -----------------------

COLUMN_NAME_MAP = {
    "user_id": "User ID",
    "rider_id": "Rider ID",
    "driver_id": "Driver ID",
    "vehicle_id": "Vehicle ID",
    "ride_id": "Ride ID",
    "payment_id": "Payment ID",
    "rating_id": "Rating ID",
    "total_users": "Total Users",
    "active_users": "Active Users",
    "inactive_users": "Inactive Users",
    "total_rides": "Total Rides",
    "ride_count": "Ride Count",
    "completed_rides": "Completed Rides",
    "cancelled_rides": "Cancelled Rides",
    "cancellation_rate": "Cancellation Rate (%)",
    "percent_canceled_rainy": "Rainy Cancellation Rate (%)",
    "percent_canceled_non_rainy": "Non-Rainy Cancellation Rate (%)",
    "total_revenue": "Total Revenue",
    "revenue": "Revenue",
    "avg_fare": "Average Fare",
    "fare": "Fare",
    "amount": "Amount",
    "total_amount": "Total Amount",
    "surge_multiplier": "Surge Multiplier",
    "avg_surge": "Average Surge Multiplier",
    "avg_rating": "Average Rating",
    "rating": "Rating",
    "distance_km": "Distance (km)",
    "avg_distance": "Average Distance (km)",
    "payment_method": "Payment Method",
    "payment_status": "Payment Status",
    "vehicle_type": "Vehicle Type",
    "user_type": "User Type",
    "city": "City",
    "status": "Ride Status",
    "cancellation_reason": "Cancellation Reason",
    "is_rainy": "Weather Condition",
    "is_active": "Account Status",
    "recorded_at": "Recorded At",
    "requested_at": "Requested At",
    "pickup_time": "Pickup Time",
    "dropoff_time": "Dropoff Time",
    "signup_date": "Signup Date",
    "temperature_c": "Temperature (°C)",
    "precipitation_mm": "Precipitation (mm)",
    "rain_mm": "Rainfall (mm)",
    "avg_rainfall_mm": "Average Rainfall (mm)",
    "weather_code": "Weather Code"
}


def clean_column_name(col_name: str) -> str:
    """Returns a deterministic, human-readable title for any column name."""
    col_l = col_name.lower().strip()
    if col_l in COLUMN_NAME_MAP:
        return COLUMN_NAME_MAP[col_l]
    if col_l.endswith("_rank"):
        prefix = col_name[:-5].replace("_", " ").title()
        return f"{prefix} Rank"
    if col_l.startswith("is_"):
        return col_name[3:].replace("_", " ").title() + " Status"
    if col_l.endswith("_count"):
        prefix = col_name[:-6].replace("_", " ").title()
        return f"{prefix} Count"
    if col_l.endswith("_rate"):
        prefix = col_name[:-5].replace("_", " ").title()
        return f"{prefix} Rate (%)"
    return col_name.replace("_", " ").title()


def format_display_label(col_name: str, raw_val: Any) -> str:
    """Formats category/boolean labels cleanly for charts and tables."""
    if raw_val is None:
        return "Unknown"
    s_val = str(raw_val).lower().strip()
    if isinstance(raw_val, bool) or s_val in ("true", "false"):
        is_true = raw_val is True or s_val == "true"
        col_l = col_name.lower()
        if "rain" in col_l or "weather" in col_l:
            return "Rainy" if is_true else "Non-Rainy"
        elif "active" in col_l:
            return "Active" if is_true else "Inactive"
        elif "completed" in col_l:
            return "Completed" if is_true else "Incomplete"
        elif "cancel" in col_l:
            return "Cancelled" if is_true else "Not Cancelled"
        elif "success" in col_l:
            return "Successful" if is_true else "Failed"
        return "Yes" if is_true else "No"
    return str(raw_val).replace("_", " ").title() if isinstance(raw_val, str) and len(str(raw_val)) < 30 else str(raw_val)


def is_bool_val(v: Any) -> bool:
    return isinstance(v, bool) or str(v).lower().strip() in ("true", "false")


def is_numeric_val(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    try:
        float(v)
        return True
    except (ValueError, TypeError):
        return False


def is_temporal_val(col: str, v: Any) -> bool:
    col_l = col.lower()
    if any(k in col_l for k in ["date", "time", "day", "month", "year", "recorded_at", "requested_at", "signup_date", "created_at"]):
        return True
    v_str = str(v).strip()
    return len(v_str) >= 10 and (v_str[4] == "-" or v_str[2] == "/")


def classify_column(col: str, vals: List[Any]) -> Dict[str, Any]:
    """Classifies a column into semantic types based on schema and values."""
    col_l = col.lower().strip()
    non_null_vals = [v for v in vals if v is not None]

    if not non_null_vals:
        return {"type": "text", "is_numeric": False, "is_temporal": False, "is_boolean": False, "metric_type": "unknown"}

    # 1. Boolean check
    if all(is_bool_val(v) for v in non_null_vals):
        return {"type": "boolean", "is_numeric": False, "is_temporal": False, "is_boolean": True, "metric_type": "boolean"}

    # 2. Temporal check
    if any(is_temporal_val(col, v) for v in non_null_vals):
        return {"type": "temporal", "is_numeric": False, "is_temporal": True, "is_boolean": False, "metric_type": "date"}

    # 3. Numeric check
    if all(is_numeric_val(v) for v in non_null_vals):
        # PRIORITY A: Ranking / Ordinal / Position check (MUST precede rate/currency checks)
        # e.g., rank, rate_rank, ranking, position, row_number, dense_rank
        if col_l == "rank" or any(k in col_l for k in ["_rank", "rank_", "ranking", "position", "row_number", "dense_rank"]):
            m_type = "rank"
        # PRIORITY B: Rate / Percentage check
        # e.g., cancellation_rate, completion_rate, percentage, percent, pct, percent_canceled_rainy
        elif any(k in col_l for k in ["rate", "percentage", "percent", "pct", "_rate"]):
            m_type = "rate"
        # PRIORITY C: Monetary / Currency check
        # e.g., fare, revenue, amount, price, cost, total_revenue, avg_fare
        elif any(k in col_l for k in ["fare", "amount", "revenue", "price", "cost"]):
            m_type = "currency"
        # PRIORITY D: Ratings & Scores
        elif any(k in col_l for k in ["rating", "score"]):
            m_type = "rating"
        # PRIORITY E: Multipliers
        elif any(k in col_l for k in ["surge", "multiplier"]):
            m_type = "multiplier"
        # PRIORITY F: Distance
        elif any(k in col_l for k in ["distance", "km", "miles"]):
            m_type = "distance"
        # PRIORITY G: Averages
        elif any(k in col_l for k in ["avg", "average", "mean"]):
            m_type = "average"
        # PRIORITY H: Integer Counts
        elif any(k in col_l for k in ["count", "total", "rides", "users", "vehicles", "payments", "ratings", "records", "completed", "cancelled", "num_"]):
            m_type = "count"
        else:
            try:
                if all(float(v).is_integer() for v in non_null_vals):
                    m_type = "count"
                else:
                    m_type = "numeric"
            except Exception:
                m_type = "numeric"

        return {"type": "numeric", "is_numeric": True, "is_temporal": False, "is_boolean": False, "metric_type": m_type}

    # 4. Text / Categorical
    return {"type": "categorical", "is_numeric": False, "is_temporal": False, "is_boolean": False, "metric_type": "text"}


def format_metric_value(raw_val: Any, metric_type: str) -> str:
    """Formats metric numbers for display with appropriate units."""
    if raw_val is None:
        return "N/A"
    try:
        val_f = float(raw_val)
        if metric_type == "rank":
            return f"{int(val_f)}"
        elif metric_type == "rate":
            # If fractional ratio <= 1.0 (e.g. 0.1605, 0.05, 1.0), scale to percentage (16.05%, 5.00%, 100.00%)
            # If already percentage-scaled (> 1.0, e.g. 16.05, 50.0, 100.0), preserve existing value
            if 0.0 < val_f <= 1.0:
                val_f = val_f * 100.0
            return f"{val_f:.2f}%"
        elif metric_type == "currency":
            return f"₹{val_f:,.2f}"
        elif metric_type == "count":
            return f"{int(val_f):,}"
        elif metric_type == "rating":
            return f"{val_f:.2f} ★"
        elif metric_type == "multiplier":
            return f"{val_f:.2f}x"
        elif metric_type == "distance":
            return f"{val_f:.2f} km"
        else:
            if val_f.is_integer():
                return f"{int(val_f):,}"
            return f"{val_f:,.2f}"
    except (ValueError, TypeError):
        return str(raw_val)


def auto_detect_chart(columns: List[str], records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Schema-aware, semantic, and deterministic visualization generator.
    Inspects SQL column names, PostgreSQL data types, and value distributions.
    
    Generates:
    - compact KPI cards for single-row multi-metric results (e.g. total_users & active_users)
    - line charts for time-series data
    - bar charts with rich context tooltips for category + rate/count
    - grouped bar charts for multiple compatible counts
    - doughnut charts for mutually exclusive part-to-whole categories (<= 6 slices)
    - scatter plots for 2 continuous numeric variables
    - table-only when data structure has no suitable chart
    """
    if not records or len(records) < 1 or not columns:
        return {"can_chart": False, "mode": "none"}

    col_profiles = {}
    for col in columns:
        vals = [r.get(col) for r in records]
        col_profiles[col] = classify_column(col, vals)

    # -------------------------------------------------------------
    # SCENARIO 1: SINGLE ROW WITH MULTIPLE KPI METRICS (len(records) == 1)
    # -------------------------------------------------------------
    if len(records) == 1:
        row = records[0]
        numeric_cols = [c for c in columns if col_profiles[c]["is_numeric"]]

        if len(numeric_cols) >= 1:
            kpis = []
            for c in numeric_cols:
                raw_val = row.get(c)
                fmt_val = format_metric_value(raw_val, col_profiles[c]["metric_type"])
                kpis.append({
                    "column": c,
                    "label": clean_column_name(c),
                    "value": fmt_val,
                    "raw_value": raw_val,
                    "metric_type": col_profiles[c]["metric_type"]
                })

            # Check for logical denominator/numerator comparison (e.g. active_users / total_users)
            comparison = None
            if len(numeric_cols) >= 2:
                denom_col = next((c for c in numeric_cols if any(k in c.lower() for k in ["total", "all", "sum"])), None)
                if denom_col:
                    num_col = next((c for c in numeric_cols if c != denom_col), None)
                    if num_col:
                        try:
                            n_val = float(row.get(num_col) or 0)
                            d_val = float(row.get(denom_col) or 0)
                            if d_val > 0:
                                pct = round((n_val / d_val) * 100.0, 2)
                                comparison = {
                                    "numerator_label": clean_column_name(num_col),
                                    "denominator_label": clean_column_name(denom_col),
                                    "numerator_val": n_val,
                                    "denominator_val": d_val,
                                    "percentage": pct,
                                    "ratio_text": f"{int(n_val) if n_val.is_integer() else n_val:,} / {int(d_val) if d_val.is_integer() else d_val:,} ({pct:.2f}%)"
                                }
                        except Exception:
                            pass

            return {
                "can_chart": True,
                "mode": "kpi_cards",
                "title": "Summary Metrics",
                "kpis": kpis,
                "comparison": comparison,
                "columns": columns,
                "records": records
            }
        else:
            return {"can_chart": False, "mode": "table_only"}

    # -------------------------------------------------------------
    # SCENARIO 2: MULTI-ROW DATA (len(records) >= 2)
    # -------------------------------------------------------------
    temporal_cols = [c for c in columns if col_profiles[c]["is_temporal"]]
    boolean_cols = [c for c in columns if col_profiles[c]["is_boolean"]]
    categorical_cols = [c for c in columns if not col_profiles[c]["is_numeric"] and not col_profiles[c]["is_temporal"]]
    numeric_cols = [c for c in columns if col_profiles[c]["is_numeric"]]

    # CASE A: TIME SERIES (Temporal column exists + numeric columns)
    if temporal_cols and numeric_cols:
        time_col = temporal_cols[0]
        labels = [str(r.get(time_col))[:16] for r in records]

        datasets = []
        for n_col in numeric_cols[:3]:
            m_type = col_profiles[n_col]["metric_type"]
            col_raw_vals = [r.get(n_col) for r in records if r.get(n_col) is not None]
            col_numeric_vals = [float(v) for v in col_raw_vals if is_numeric_val(v)]
            is_frac = m_type == "rate" and len(col_numeric_vals) > 0 and all(0.0 <= v <= 1.0 for v in col_numeric_vals)

            vals = []
            for r in records:
                v = r.get(n_col)
                if v is None:
                    vals.append(0.0)
                else:
                    try:
                        vf = float(v)
                        if is_frac and 0.0 < vf <= 1.0:
                            vf = round(vf * 100.0, 4)
                        vals.append(vf)
                    except (ValueError, TypeError):
                        vals.append(0.0)

            datasets.append({
                "label": clean_column_name(n_col),
                "column": n_col,
                "data": vals,
                "metric_type": m_type
            })

        title = "Rides Over Time" if any("ride" in c.lower() for c in numeric_cols) else f"{clean_column_name(numeric_cols[0])} Over Time"
        return {
            "can_chart": True,
            "mode": "chart",
            "type": "line",
            "title": title,
            "label_column": time_col,
            "labels": labels,
            "values": datasets[0]["data"] if datasets else [],
            "datasets": datasets,
            "raw_records": records
        }

    # CASE B: CATEGORY (or Boolean) + NUMERIC METRICS
    category_col = None
    if categorical_cols:
        category_col = categorical_cols[0]
    elif boolean_cols:
        category_col = boolean_cols[0]

    if category_col and numeric_cols:
        labels = [format_display_label(category_col, r.get(category_col)) for r in records]

        rate_cols = [c for c in numeric_cols if col_profiles[c]["metric_type"] == "rate"]
        count_cols = [c for c in numeric_cols if col_profiles[c]["metric_type"] == "count"]

        # 1. Category + Rate/Percentage with Supporting Metrics
        if rate_cols:
            primary_rate_col = rate_cols[0]
            raw_vals = [r.get(primary_rate_col) for r in records if r.get(primary_rate_col) is not None]
            numeric_vals = [float(v) for v in raw_vals if is_numeric_val(v)]
            is_fractional = len(numeric_vals) > 0 and all(0.0 <= v <= 1.0 for v in numeric_vals)

            values = []
            for r in records:
                v = r.get(primary_rate_col)
                if v is None:
                    values.append(0.0)
                else:
                    try:
                        vf = float(v)
                        if is_fractional and 0.0 < vf <= 1.0:
                            vf = round(vf * 100.0, 4)
                        values.append(vf)
                    except (ValueError, TypeError):
                        values.append(0.0)

            title = f"{clean_column_name(primary_rate_col)} by {clean_column_name(category_col)}"
            return {
                "can_chart": True,
                "mode": "chart",
                "type": "bar",
                "title": title,
                "label_column": category_col,
                "value_column": primary_rate_col,
                "labels": labels,
                "values": values,
                "metric_type": "rate",
                "datasets": [{
                    "label": clean_column_name(primary_rate_col),
                    "column": primary_rate_col,
                    "data": values,
                    "metric_type": "rate"
                }],
                "raw_records": records
            }

        # 2. Category + Multiple Compatible Counts (Grouped Bar Chart)
        if len(count_cols) >= 2:
            datasets = []
            for n_col in count_cols[:4]:
                vals = [float(r.get(n_col) or 0) if r.get(n_col) is not None else 0.0 for r in records]
                datasets.append({
                    "label": clean_column_name(n_col),
                    "column": n_col,
                    "data": vals,
                    "metric_type": "count"
                })
            title = f"{' & '.join(clean_column_name(c) for c in count_cols[:2])} by {clean_column_name(category_col)}"
            return {
                "can_chart": True,
                "mode": "chart",
                "type": "grouped_bar",
                "title": title,
                "label_column": category_col,
                "labels": labels,
                "values": datasets[0]["data"] if datasets else [],
                "datasets": datasets,
                "raw_records": records
            }

        # 3. Category + Single Numeric Metric
        primary_metric = numeric_cols[0]
        values = [float(r.get(primary_metric) or 0) if r.get(primary_metric) is not None else 0.0 for r in records]

        # Part-to-whole check (doughnut)
        is_part_to_whole = (
            len(records) <= 6 and
            any(k in category_col.lower() for k in ["status", "payment_method", "user_type", "vehicle_type", "method"])
        )
        chart_type = "doughnut" if is_part_to_whole else "bar"

        cat_clean = clean_column_name(category_col)
        metric_clean = clean_column_name(primary_metric)

        if "status" in category_col.lower():
            title = f"Rides by {cat_clean}" if "ride" in primary_metric.lower() or "count" in primary_metric.lower() else f"{metric_clean} by {cat_clean}"
        elif "payment_method" in category_col.lower():
            title = f"{metric_clean} by {cat_clean}"
        else:
            title = f"{metric_clean} by {cat_clean}"

        return {
            "can_chart": True,
            "mode": "chart",
            "type": chart_type,
            "title": title,
            "label_column": category_col,
            "value_column": primary_metric,
            "labels": labels,
            "values": values,
            "metric_type": col_profiles[primary_metric]["metric_type"],
            "datasets": [{
                "label": metric_clean,
                "column": primary_metric,
                "data": values,
                "metric_type": col_profiles[primary_metric]["metric_type"]
            }],
            "raw_records": records
        }

    # CASE C: TWO CONTINUOUS NUMERIC VARIABLES (Scatter Plot)
    if len(numeric_cols) >= 2 and len(records) >= 5 and not categorical_cols:
        x_col = numeric_cols[0]
        y_col = numeric_cols[1]
        scatter_points = [{"x": float(r.get(x_col) or 0), "y": float(r.get(y_col) or 0)} for r in records]
        return {
            "can_chart": True,
            "mode": "chart",
            "type": "scatter",
            "title": f"{clean_column_name(y_col)} vs {clean_column_name(x_col)}",
            "x_column": x_col,
            "y_column": y_col,
            "x_label": clean_column_name(x_col),
            "y_label": clean_column_name(y_col),
            "values": [],
            "datasets": [{
                "label": f"{clean_column_name(y_col)} vs {clean_column_name(x_col)}",
                "data": scatter_points
            }],
            "raw_records": records
        }

    return {"can_chart": False, "mode": "table_only"}


def execute_agent_query(
    user_question: str,
    chat_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes the multi-agent workflow for a given question and returns
    rich metadata for the UI including reasoning steps, SQL, table data, and chart info.
    Supports session-isolated dataset execution via session_id or chat_id.
    """
    import time
    last_error = None

    if not session_id and chat_id:
        try:
            from utils.chat_store import ChatStore
            chat_obj = ChatStore.get_chat(chat_id)
            if chat_obj and chat_obj.get("session_id"):
                session_id = chat_obj.get("session_id")
        except Exception:
            pass

    for attempt in range(3):
        try:
            response = data_agent.invoke(
                {
                    "messages": [HumanMessage(content=user_question)],
                    "route_response": "",
                    "session_id": session_id
                }
            )

            route = response.get("route_response", "sql")
            final_answer = response.get("final_answer", "")
            sql_state = response.get("sql_state") or {}
            etl_state = response.get("etl_state") or {}

            # Build timeline steps
            timeline = [
                {"step": "router", "title": "Intent Classification", "status": "completed", "detail": f"Routed to {route.upper()} Analyst"}
            ]

            if route == "sql":
                timeline.extend([
                    {"step": "curate", "title": "Question Curation", "status": "completed", "detail": sql_state.get("curated_ques", "")},
                    {"step": "generate_sql", "title": "SQL Generation", "status": "completed", "detail": sql_state.get("generated_sql_query", "")},
                    {"step": "judge", "title": "Security Check (LLM as Judge)", "status": "completed", "detail": f"Status: {sql_state.get('is_safe', 'Unknown')} — {sql_state.get('comments', '')}"},
                    {"step": "execute", "title": "Database Execution", "status": "completed", "detail": f"Returned {len(sql_state.get('data_rows', []))} rows"},
                    {"step": "format", "title": "Answer Synthesis", "status": "completed", "detail": "Formatted final answer"}
                ])

                columns = sql_state.get("data_columns", [])
                records = sql_state.get("data_dicts", [])
                chart_info = auto_detect_chart(columns, records)

                return {
                    "success": True,
                    "route": "sql",
                    "question": user_question,
                    "answer": final_answer,
                    "curated_question": sql_state.get("curated_ques", ""),
                    "sql_query": sql_state.get("generated_sql_query", ""),
                    "is_safe": sql_state.get("is_safe", "Yes"),
                    "judge_comments": sql_state.get("comments", ""),
                    "columns": columns,
                    "rows": sql_state.get("data_rows", []),
                    "records": records,
                    "chart": chart_info,
                    "timeline": timeline
                }

            else:  # ETL
                timeline.extend([
                    {"step": "etl_tools", "title": "ETL Tool Invocation", "status": "completed", "detail": "Processed API extract / transformation"}
                ])

                return {
                    "success": True,
                    "route": "etl",
                    "question": user_question,
                    "answer": final_answer,
                    "etl_output": etl_state.get("result", ""),
                    "timeline": timeline,
                    "columns": [],
                    "rows": [],
                    "records": [],
                    "chart": {"can_chart": False, "mode": "none"}
                }

        except Exception as e:
            last_error = e
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue

    return {
        "success": False,
        "route": "unknown",
        "question": user_question,
        "answer": f"Agent encountered an error: {str(last_error)}",
        "timeline": [
            {"step": "error", "title": "Error Occurred", "status": "failed", "detail": str(last_error)}
        ],
        "columns": [],
        "rows": [],
        "records": [],
        "chart": {"can_chart": False, "mode": "none"}
    }


if __name__ == "__main__":
    test_question = "What are the top 5 driver IDs with the most ratings?"
    res = execute_agent_query(test_question)
    print("Agent Result:")
    print("Route:", res.get("route"))
    print("Answer:", res.get("answer"))
    print("Chart Can Draw:", res.get("chart", {}).get("can_chart"))
import os
import sys
import logging
from typing import Dict, Any, List

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
        "error": ""
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

def auto_detect_chart(columns: List[str], records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyzes query result columns and records to automatically detect categorical (X-axis)
    and numeric metric (Y-axis) columns, formatting boolean labels and generating human-readable titles.
    """
    if not records or len(records) < 1 or len(columns) < 2:
        return {"can_chart": False}

    def is_bool_val(v: Any) -> bool:
        return isinstance(v, bool) or str(v).lower() in ("true", "false")

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
        if any(k in col_l for k in ["date", "time", "day", "month", "year", "recorded_at", "requested_at"]):
            return True
        v_str = str(v)
        return len(v_str) >= 10 and (v_str[4] == "-" or v_str[2] == "/")

    num_candidates = []
    cat_candidates = []

    for col in columns:
        vals = [r.get(col) for r in records if r.get(col) is not None]
        if not vals:
            continue

        # 1. Boolean check (categorical)
        if all(is_bool_val(v) for v in vals):
            cat_candidates.append((col, "boolean", 12))
        elif any(is_bool_val(v) for v in vals):
            cat_candidates.append((col, "boolean", 10))
        # 2. Temporal check (categorical / line axis)
        elif any(is_temporal_val(col, v) for v in vals):
            cat_candidates.append((col, "temporal", 11))
        # 3. Numeric check (metric axis)
        elif all(is_numeric_val(v) for v in vals):
            score = 10
            col_l = col.lower()
            if any(k in col_l for k in ["count", "avg", "sum", "total", "fare", "rate", "revenue", "amount", "temp", "precip", "rain", "percent", "pct"]):
                score += 5
            num_candidates.append((col, score))
        # 4. Standard categorical (string)
        else:
            cat_candidates.append((col, "categorical", 5))

    # Pick best numeric and categorical columns
    num_candidates.sort(key=lambda x: x[1], reverse=True)
    cat_candidates.sort(key=lambda x: x[2], reverse=True)

    num_col = None
    cat_col = None

    if num_candidates:
        num_col = num_candidates[0][0]

    if cat_candidates:
        for c in cat_candidates:
            if c[0] != num_col:
                cat_col = c[0]
                break

    # Fallbacks if one is missing
    if cat_col is None and num_col is not None:
        for c in columns:
            if c != num_col:
                cat_col = c
                break
    elif num_col is None and cat_col is not None:
        for c in columns:
            if c != cat_col and is_numeric_val(records[0].get(c)):
                num_col = c
                break

    if not cat_col or not num_col or cat_col == num_col:
        return {"can_chart": False}

    def format_display_label(col_name: str, raw_val: Any) -> str:
        if is_bool_val(raw_val):
            is_true = raw_val is True or str(raw_val).lower() == "true"
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
            else:
                return "Yes" if is_true else "No"
        return str(raw_val)

    def clean_column_name(col_name: str) -> str:
        col_l = col_name.lower()
        if col_l == "is_rainy":
            return "Weather Condition"
        elif col_l.startswith("is_"):
            return col_name[3:].replace("_", " ").title() + " Status"
        name_map = {
            "avg_rainfall_mm": "Average Rainfall (mm)",
            "avg_rainfall": "Average Rainfall (mm)",
            "total_precip_mm": "Total Precipitation (mm)",
            "ride_count": "Ride Count",
            "total_rides": "Total Rides",
            "avg_fare": "Average Fare",
            "avg_rating": "Average Rating",
            "total_revenue": "Total Revenue",
            "cancellation_rate": "Cancellation Rate (%)",
            "percent_canceled_rainy": "Rainy Cancellation %",
            "percent_canceled_non_rainy": "Non-Rainy Cancellation %",
            "surge_multiplier": "Surge Multiplier",
            "avg_surge": "Average Surge Multiplier",
            "transaction_count": "Transaction Count",
            "user_count": "User Count"
        }
        return name_map.get(col_l, col_name.replace("_", " ").title())

    labels = [format_display_label(cat_col, r.get(cat_col)) for r in records]
    values = []
    for r in records:
        try:
            v = r.get(num_col)
            values.append(float(v) if v is not None else 0.0)
        except (ValueError, TypeError):
            values.append(0.0)

    # Determine chart type
    is_temporal = any(k in cat_col.lower() for k in ["date", "time", "day", "month", "year", "recorded_at", "requested_at"])
    if is_temporal:
        chart_type = "line"
    elif len(records) <= 6 and any(k in cat_col.lower() for k in ["status", "payment_method", "method", "user_type", "type"]):
        chart_type = "doughnut"
    else:
        chart_type = "bar"

    title = f"{clean_column_name(num_col)} by {clean_column_name(cat_col)}"

    return {
        "can_chart": True,
        "type": chart_type,
        "label_column": cat_col,
        "value_column": num_col,
        "labels": labels,
        "values": values,
        "title": title
    }


def execute_agent_query(user_question: str) -> Dict[str, Any]:
    """
    Executes the multi-agent workflow for a given question and returns
    rich metadata for the UI including reasoning steps, SQL, table data, and chart info.
    """
    import time
    for attempt in range(2):
        try:
            response = data_agent.invoke(
                {
                    "messages": [HumanMessage(content=user_question)],
                    "route_response": ""
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
                    "chart": {"can_chart": False}
                }

        except Exception as e:
            if attempt == 0 and ("connection" in str(e).lower() or "timeout" in str(e).lower() or "disconnected" in str(e).lower()):
                time.sleep(1)
                continue
            return {
                "success": False,
                "route": "unknown",
                "question": user_question,
                "answer": f"Agent encountered an error: {str(e)}",
                "timeline": [
                    {"step": "error", "title": "Error Occurred", "status": "failed", "detail": str(e)}
                ],
                "columns": [],
                "rows": [],
                "records": [],
                "chart": {"can_chart": False}
            }


if __name__ == "__main__":
    test_question = "What are the top 5 driver IDs with the most ratings?"
    res = execute_agent_query(test_question)
    print("Agent Result:")
    print("Route:", res.get("route"))
    print("Answer:", res.get("answer"))
    print("Chart Can Draw:", res.get("chart", {}).get("can_chart"))
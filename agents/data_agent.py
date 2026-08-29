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

from utils.llm_pick import pick_llm
from model.schema import RouterSchema, DataAgentSchema
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from agents.etl_analyst import etl_analyst
from agents.sql_analyst import sql_analyst

llm = pick_llm("gemini")
llm_router = llm.with_structured_output(RouterSchema)


# ----------------------- DATA AGENT NODES -----------------------

def router_node(state: DataAgentSchema) -> DataAgentSchema:
    messages = state.messages[-1].content
    route_response_dict = llm_router.invoke(
        f"""Classify whether this query requires querying an SQL database or running an ETL task (API extraction / file transformation):
Query: {messages}
Return 'sql' for database questions/analytics, or 'etl' for API extraction/data transformations."""
    )
    state.route_response = route_response_dict.answer
    return state


def etl_node(state: DataAgentSchema) -> DataAgentSchema:
    messages = state.messages[-1].content
    response = etl_analyst.invoke(
        {
            "messages": [HumanMessage(content=messages)]
        }
    )
    last_msg = response["messages"][-1]
    final_content = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    if isinstance(final_content, list):
        final_text = "".join(item.get("text", "") for item in final_content if isinstance(item, dict))
    else:
        final_text = str(final_content)

    state.final_answer = final_text
    state.etl_state = {"raw_messages": [str(m) for m in response.get("messages", [])], "result": final_text}
    state.messages = state.messages + [AIMessage(content=final_text)]
    return state


def sql_node(state: DataAgentSchema) -> DataAgentSchema:
    message = state.messages[-1].content
    input_schema = {
        "messages": [],
        "user_question": message,
        "curated_ques": "",
        "Prompt_query_context": "",
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
    Analyzes the query result structure and suggests chart configurations (bar, line, doughnut)
    for seamless visualization in the frontend.
    """
    if not records or len(records) < 1 or len(columns) < 2:
        return {"can_chart": False}

    # Find string/categorical and numeric columns
    cat_col = None
    num_col = None

    for col in columns:
        first_val = records[0].get(col)
        if isinstance(first_val, (int, float)) and num_col is None:
            num_col = col
        elif isinstance(first_val, str) and cat_col is None:
            cat_col = col

    # If first pass didn't find them, try second col
    if cat_col is None and len(columns) > 0:
        cat_col = columns[0]
    if num_col is None and len(columns) > 1:
        num_col = columns[1]

    if not cat_col or not num_col:
        return {"can_chart": False}

    # Prepare labels and values
    labels = [str(r.get(cat_col, "")) for r in records]
    values = []
    for r in records:
        try:
            values.append(float(r.get(num_col, 0)))
        except (ValueError, TypeError):
            values.append(0)

    # Determine best chart type
    if len(records) <= 6 and ("status" in cat_col.lower() or "method" in cat_col.lower() or "type" in cat_col.lower()):
        chart_type = "doughnut"
    elif any(k in cat_col.lower() for k in ["date", "time", "day", "month", "year"]):
        chart_type = "line"
    else:
        chart_type = "bar"

    return {
        "can_chart": True,
        "type": chart_type,
        "label_column": cat_col,
        "value_column": num_col,
        "labels": labels,
        "values": values,
        "title": f"{num_col.replace('_', ' ').title()} by {cat_col.replace('_', ' ').title()}"
    }


def execute_agent_query(user_question: str) -> Dict[str, Any]:
    """
    Executes the multi-agent workflow for a given question and returns
    rich metadata for the UI including reasoning steps, SQL, table data, and chart info.
    """
    steps = [
        {"step": "router", "title": "Classifying Intent", "status": "running"}
    ]

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
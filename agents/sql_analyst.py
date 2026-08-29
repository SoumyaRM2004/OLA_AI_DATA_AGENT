import os
import sys
import json
import re
from typing import Dict, Any, Tuple, Optional

sys.path.append(
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..")
    )
)

from utils.llm_pick import pick_llm
from utils.database import DatabaseConnection
from model.schema import AgentSchema, JudgeSchema, SQLGenerationSchema
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import StateGraph, START, END


# ============================================================
# DETERMINISTIC SQL VALIDATOR
# ============================================================

DISALLOWED_KEYWORDS = [
    r"\bINSERT\b", r"\bUPDATE\b", r"\bDELETE\b", r"\bDROP\b",
    r"\bALTER\b", r"\bTRUNCATE\b", r"\bCREATE\b", r"\bGRANT\b",
    r"\bREVOKE\b", r"\bEXECUTE\b", r"\bEXEC\b", r"\bCOPY\b",
    r"\bVACUUM\b", r"\bREINDEX\b"
]

def validate_sql_deterministic(raw_sql: str) -> Tuple[bool, str, str]:
    """
    Deterministically validates a generated SQL query before sending to Security Judge or PostgreSQL.
    
    Returns:
        (is_valid: bool, clean_sql: str, error_message: str)
    """
    if not raw_sql or not isinstance(raw_sql, str):
        return False, "", "SQL query is empty or not a valid string."

    sql = raw_sql.strip()

    # 1. Reject obvious markdown fences
    if "```" in sql:
        return False, "", "SQL contains markdown code fences."

    # 2. Reject reasoning tokens
    if "<think>" in sql.lower() or "</think>" in sql.lower():
        return False, "", "SQL contains reasoning or thought tokens."

    # 3. Reject backticks (PostgreSQL uses standard quotes or double quotes, not MySQL backticks)
    if "`" in sql:
        return False, "", "SQL contains invalid backtick identifier characters (`)."

    # 4. Reject conversational punctuation (question marks or exclamation marks outside string literals)
    in_str = False
    for ch in sql:
        if ch == "'":
            in_str = not in_str
        elif ch in ["?", "!"] and not in_str:
            return False, "", f"SQL contains invalid conversational punctuation ('{ch}')."

    # 5. Reject conversational or explanatory phrasing
    conversational_patterns = [
        r"\bhere is\b", r"\blet me\b", r"\blet us\b", r"\bwait,\b",
        r"\bmaybe\b", r"\bno,\b", r"\bi will\b", r"\byou can\b",
        r"\bexplanation:\b", r"\bnote:\b", r"\bthe query is\b"
    ]
    for cp in conversational_patterns:
        if re.search(cp, sql, flags=re.IGNORECASE):
            return False, "", "SQL contains conversational or explanatory text."

    # 6. Ensure statement starts strictly with SELECT or WITH
    if not re.match(r"^\s*(SELECT|WITH)\b", sql, flags=re.IGNORECASE):
        return False, "", "SQL query must strictly begin with SELECT or WITH."

    # 7. Reject mutating/dangerous SQL keywords
    for pattern in DISALLOWED_KEYWORDS:
        if re.search(pattern, sql, flags=re.IGNORECASE):
            match = re.search(pattern, sql, flags=re.IGNORECASE).group(0)
            return False, "", f"Disallowed SQL operation detected: {match.upper()}"

    # 8. Check for chained statements / multiple semicolons outside single quotes
    cleaned_body = sql.rstrip(";").strip()
    semicolon_outside_quotes = False
    in_single_quotes = False
    for char in cleaned_body:
        if char == "'":
            in_single_quotes = not in_single_quotes
        elif char == ";" and not in_single_quotes:
            semicolon_outside_quotes = True
            break
            
    if semicolon_outside_quotes:
        return False, "", "Multiple SQL statements detected (chained queries not allowed)."

    # Clean, single-statement SQL with terminating semicolon
    final_sql = cleaned_body + ";"
    return True, final_sql, ""


# ============================================================
# HELPER: EXTRACT JSON
# ============================================================

def extract_json(text: str) -> dict:
    text = text.strip()
    if "<think>" in text and "</think>" in text:
        text = text.split("</think>", 1)[1].strip()

    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse valid JSON from output: {text[:200]}")


# ============================================================
# 1. CURATE USER QUESTION
# ============================================================

def curate_ques(state: AgentSchema) -> AgentSchema:
    user_question = state.user_question
    llm = pick_llm("low")

    prompt = f"""
You are a question-curation assistant for an SQL data analyst in an OLA-inspired mobility platform.

Rewrite the user's question into a clear, precise analytical question for querying a PostgreSQL database containing rides, drivers, vehicles, payments, ratings, and weather data.

Do not answer the question.
Do not generate SQL.

Return only the curated question text.

User Question:
{user_question}
"""

    response = llm.invoke(prompt)
    curated_question = response.content.strip()

    if "<think>" in curated_question:
        curated_question = curated_question.split("</think>")[-1].strip()

    state.curated_ques = curated_question
    state.messages = state.messages + [HumanMessage(content=curated_question)]

    return state


# ============================================================
# 2. CREATE SQL GENERATION CONTEXT
# ============================================================

def prompt_query_context(state: AgentSchema) -> AgentSchema:
    curated_question = state.curated_ques
    db = DatabaseConnection()
    schema_info = db.schema_details("public")

    prompt = f"""
You are an expert SQL Data Analyst Agent for a PostgreSQL database in an OLA-inspired mobility platform.

Your task is to analyze the user question against the provided database schema and determine if it can be answered.

DATABASE SCHEMA:
{schema_info}

TABLES OVERVIEW:
- users: user_id, first_name, last_name, email, phone, city, user_type ('rider', 'driver'), signup_date, is_active.
- vehicles: vehicle_id, driver_id, vehicle_type, make, model, year, license_plate.
- rides: ride_id, rider_id, driver_id, vehicle_id, pickup_lat, pickup_lon, dropoff_lat, dropoff_lon, requested_at, pickup_time, dropoff_time, fare, distance_km, duration_min, surge_multiplier, status ('completed', 'cancelled', 'in_progress'), cancellation_reason.
- payments: payment_id, ride_id, amount, payment_method ('card', 'cash', 'upi', 'wallet'), payment_status ('completed', 'successful', 'failed', 'refunded'), transaction_id.
- ratings: rating_id, ride_id, rider_id, driver_id, rating (1-5), comment, created_at.
- weather_data: weather_id, recorded_at (timestamp), city, latitude, longitude, temperature_c, precipitation_mm, rain_mm, weather_code, is_rainy (boolean). (NOTE: There is NO 'timezone' or 'wind_speed' column).

RULES FOR OUTPUT FORMAT:
Return ONLY a valid JSON object matching this structure:
{{
  "can_be_answered": true,
  "sql_query": "SELECT ...;",
  "explanation": ""
}}

CRITICAL SCHEMA LIMITATION RULES:
1. Examine the schema carefully. If the user asks for attributes, metrics, or columns that DO NOT EXIST in the schema (e.g. timezone, user age, driver salary, wind speed):
   - Set "can_be_answered": false
   - Set "sql_query": ""
   - Set "explanation": "Provide a clear, helpful statement explaining what columns/information exist and that the requested attribute (e.g. timezone) is not available in the database schema."
   - NEVER hallucinate or invent non-existent column names or tables!
2. If "can_be_answered": true:
   - "sql_query" MUST contain ONLY the single executable PostgreSQL statement (SELECT or WITH).
   - Do NOT include markdown code fences, comments, thoughts, or conversational text in "sql_query".
   - Use appropriate JOINs between tables.
   - For correlation between rides and weather, join on hourly timestamp: `JOIN public.weather_data w ON DATE_TRUNC('hour', rides.requested_at) = w.recorded_at` or date: `rides.requested_at::date = w.recorded_at::date`.
   - If user does not specify row count, limit to 10 rows.
   - For text comparisons, use case-insensitive matching with ILIKE.
   - Set "explanation": ""

USER QUESTION:
{curated_question}
"""

    state.Prompt_query_context = prompt
    return state


# ============================================================
# 3. GENERATE STRUCTURED SQL
# ============================================================

def generate_sql(state: AgentSchema) -> AgentSchema:
    prompt = state.Prompt_query_context
    llm = pick_llm("medium")

    try:
        response = llm.invoke(prompt)
        raw_text = response.content.strip()
        data = extract_json(raw_text)
        validated = SQLGenerationSchema.model_validate(data)

        state.can_be_answered = validated.can_be_answered
        state.schema_explanation = validated.explanation or ""
        state.generated_sql_query = validated.sql_query or ""

    except Exception as e:
        # Fallback: attempt structured invocation with Gemini if medium LLM output malformed JSON
        try:
            gemini_llm = pick_llm("gemini")
            response = gemini_llm.invoke(prompt)
            raw_text = response.content.strip()
            data = extract_json(raw_text)
            validated = SQLGenerationSchema.model_validate(data)

            state.can_be_answered = validated.can_be_answered
            state.schema_explanation = validated.explanation or ""
            state.generated_sql_query = validated.sql_query or ""
        except Exception as e2:
            state.can_be_answered = False
            state.schema_explanation = f"Could not generate a structured query for this request: {e2}"
            state.generated_sql_query = ""
            state.error = str(e2)

    return state


# ============================================================
# 4. DETERMINISTIC VALIDATION NODE
# ============================================================

def validate_sql_node(state: AgentSchema) -> AgentSchema:
    # If the model marked the question as unanswerable from the schema
    if not state.can_be_answered:
        return state

    # Deterministically validate the generated SQL string
    is_valid, clean_sql, err = validate_sql_deterministic(state.generated_sql_query)

    if not is_valid:
        state.error = f"Invalid SQL generated: {err}"
        state.generated_sql_query = ""
    else:
        state.generated_sql_query = clean_sql
        state.error = ""

    return state


def route_after_validation(state: AgentSchema) -> str:
    if not state.can_be_answered:
        return "unanswerable_question"
    if state.error:
        return "invalid_sql"
    return "is_safe_sql"


# ============================================================
# 5. HANDLE UNANSWERABLE QUESTIONS & INVALID SQL
# ============================================================

def unanswerable_question(state: AgentSchema) -> AgentSchema:
    explanation = state.schema_explanation or (
        f"The requested information cannot be retrieved because the required fields or columns "
        f"are not present in the current database schema for '{state.curated_ques}'."
    )
    state.final_answer = explanation
    state.messages = state.messages + [AIMessage(content=explanation)]
    return state


def invalid_sql(state: AgentSchema) -> AgentSchema:
    state.final_answer = (
        f"⚠️ **Unable to Generate Valid SQL**\n\n"
        f"The system generated a query that failed strict deterministic syntax validation.\n"
        f"**Reason:** {state.error}"
    )
    state.messages = state.messages + [AIMessage(content=state.final_answer)]
    return state


# ============================================================
# 6. SQL SECURITY JUDGE (AUDITS ONLY CLEAN SQL)
# ============================================================

def is_safe_sql(state: AgentSchema) -> AgentSchema:
    sql_query = state.generated_sql_query
    llm = pick_llm("high")

    prompt = f"""
You are an SQL Security Judge for a PostgreSQL database.

Your task is to determine whether the generated SQL query is safe to execute.

A query is SAFE ONLY when it performs read-only data retrieval (SELECT, WITH).

The following operations are strictly UNSAFE:
- INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, GRANT, REVOKE, EXECUTE, COPY

Return ONLY valid JSON:
{{
    "answer": "Yes",
    "comments": "Brief explanation."
}}

Rules:
"Yes" = SQL query is safe (read-only).
"No" = SQL query is unsafe.

SQL QUERY:
{sql_query}
"""

    try:
        response = llm.invoke(prompt)
        data = extract_json(response.content)
        result = JudgeSchema.model_validate(data)
        state.is_safe = result.answer
        state.comments = result.comments
    except Exception as e:
        # Strict security default on parse failure
        state.is_safe = "No"
        state.comments = f"Security judge failed to evaluate safely: {e}"

    return state


def is_safe_sql_edge(state: AgentSchema) -> str:
    if state.is_safe.lower() == "yes":
        return "execute_sql"
    return "canceled_sql"


# ============================================================
# 7. CANCEL UNSAFE SQL
# ============================================================

def canceled_sql(state: AgentSchema) -> AgentSchema:
    state.final_answer = (
        "⚠️ **Query Blocked by Security Judge**: The generated SQL query was flagged as potentially unsafe.\n\n"
        f"**Reason:** {state.comments}\n\n"
        f"**Blocked SQL:**\n```sql\n{state.generated_sql_query}\n```"
    )
    state.messages = state.messages + [AIMessage(content=state.final_answer)]
    return state


# ============================================================
# 8. EXECUTE SQL (STRUCTURED FOR CHARTS & TABLES)
# ============================================================

def execute_sql(state: AgentSchema) -> AgentSchema:
    sql_query = state.generated_sql_query
    db = DatabaseConnection()

    result_dict = db.execute_query_structured(sql_query)

    state.data_columns = result_dict.get("columns", [])
    state.data_rows = result_dict.get("rows", [])
    state.data_dicts = result_dict.get("records", [])
    state.sql_query_execution_result = result_dict.get("raw_text", "")
    if result_dict.get("error"):
        state.error = result_dict["error"]

    return state


# ============================================================
# 9. REPRESENT FINAL ANSWER
# ============================================================

def represent_final_answer(state: AgentSchema) -> AgentSchema:
    execution_result = state.sql_query_execution_result
    curated_question = state.curated_ques

    if state.error:
        state.final_answer = f"Error executing query: {state.error}"
        state.messages = state.messages + [AIMessage(content=state.final_answer)]
        return state

    if not state.data_rows:
        state.final_answer = f"No records found in the database matching the criteria for '{curated_question}'."
        state.messages = state.messages + [AIMessage(content=state.final_answer)]
        return state

    llm = pick_llm("low")

    prompt = f"""
You are an SQL Data Analyst assistant for an OLA-inspired mobility platform.

The user asked: "{curated_question}"
Database returned: {execution_result}

Your task is to present this data in a clear, well-structured, natural language response.
- Highlight key insights directly with exact numbers from the data.
- When presenting weather vs ride metrics, express results in terms of **observed correlations** (e.g., "The data indicates that during rainy periods..."). Avoid claiming direct causality.
- Format multi-row results neatly with bullet points or summary tables.

Provide a concise and helpful answer:
"""

    response = llm.invoke(prompt)
    final_answer = response.content.strip()

    if "<think>" in final_answer:
        final_answer = final_answer.split("</think>")[-1].strip()

    state.final_answer = final_answer
    state.messages = state.messages + [AIMessage(content=final_answer)]

    return state


# ============================================================
# 10. BUILD LANGGRAPH
# ============================================================

sql_agent_graph = StateGraph(AgentSchema)

sql_agent_graph.add_node("curate_ques", curate_ques)
sql_agent_graph.add_node("prompt_query_context", prompt_query_context)
sql_agent_graph.add_node("generate_sql", generate_sql)
sql_agent_graph.add_node("validate_sql_node", validate_sql_node)
sql_agent_graph.add_node("unanswerable_question", unanswerable_question)
sql_agent_graph.add_node("invalid_sql", invalid_sql)
sql_agent_graph.add_node("is_safe_sql", is_safe_sql)
sql_agent_graph.add_node("canceled_sql", canceled_sql)
sql_agent_graph.add_node("execute_sql", execute_sql)
sql_agent_graph.add_node("represent_final_answer", represent_final_answer)

# Graph wiring
sql_agent_graph.add_edge(START, "curate_ques")
sql_agent_graph.add_edge("curate_ques", "prompt_query_context")
sql_agent_graph.add_edge("prompt_query_context", "generate_sql")
sql_agent_graph.add_edge("generate_sql", "validate_sql_node")

sql_agent_graph.add_conditional_edges(
    "validate_sql_node",
    route_after_validation,
    {
        "unanswerable_question": "unanswerable_question",
        "invalid_sql": "invalid_sql",
        "is_safe_sql": "is_safe_sql"
    }
)

sql_agent_graph.add_edge("unanswerable_question", END)
sql_agent_graph.add_edge("invalid_sql", END)

sql_agent_graph.add_conditional_edges(
    "is_safe_sql",
    is_safe_sql_edge,
    {
        "execute_sql": "execute_sql",
        "canceled_sql": "canceled_sql"
    }
)

sql_agent_graph.add_edge("execute_sql", "represent_final_answer")
sql_agent_graph.add_edge("represent_final_answer", END)
sql_agent_graph.add_edge("canceled_sql", END)

sql_analyst = sql_agent_graph.compile()


if __name__ == "__main__":
    test_input = {
        "messages": [],
        "user_question": "What location and timezone does the weather_data table represent?",
        "curated_ques": "",
        "Prompt_query_context": "",
        "can_be_answered": True,
        "schema_explanation": "",
        "generated_sql_query": "",
        "is_safe": "No",
        "comments": "",
        "sql_query_execution_result": "",
        "final_answer": "",
        "error": ""
    }
    res = sql_analyst.invoke(test_input)
    print("\n--- SQL Analyst Result ---")
    print("Can be answered:", res.get("can_be_answered"))
    print("SQL Query:", res.get("generated_sql_query"))
    print("Final Answer:\n", res.get("final_answer"))
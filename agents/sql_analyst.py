import os
import sys
import json
import re
from typing import Dict, Any

sys.path.append(
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..")
    )
)

from utils.llm_pick import pick_llm
from utils.database import DatabaseConnection
from model.schema import AgentSchema, JudgeSchema
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import StateGraph, START, END


# ============================================================
# 1. CURATE USER QUESTION
# ============================================================

def curate_ques(state: AgentSchema) -> AgentSchema:
    user_question = state.user_question
    llm = pick_llm("low")

    prompt = f"""
You are a question-curation assistant for an SQL data analyst in an OLA-inspired mobility platform.

Rewrite the user's question into a clear, precise, and unambiguous analytical question
that can be answered using an SQL database containing rides, drivers, vehicles, payments, ratings, and weather data.

Do not answer the question.
Do not generate SQL.

Return only the curated question.

User Question:
{user_question}
"""

    response = llm.invoke(prompt)
    curated_question = response.content.strip()

    # Clean any reasoning tokens if present
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
You are an expert SQL Data Analyst Agent for an OLA-inspired mobility and ride-hailing data platform.

Your task is to convert the user's natural-language question
into a valid PostgreSQL SQL query based strictly on the provided schema.

DATABASE SCHEMA:
{schema_info}

TABLES OVERVIEW:
- users: rider and driver profiles, city, signup date, active status.
- vehicles: driver vehicle details, make, model, year, license plate.
- rides: ride details (requested_at, pickup_time, dropoff_time, fare, distance_km, surge_multiplier, status, cancellation_reason).
- payments: payment method, amount, payment status, transaction id.
- ratings: trip ratings (1-5), comments.
- weather_data: hourly external weather recordings (recorded_at, city, temperature_c, precipitation_mm, rain_mm, is_rainy, weather_code).

WEATHER & RIDE JOIN GUIDELINES:
- To correlate rides with weather, join on hourly timestamp:
  JOIN public.weather_data w ON DATE_TRUNC('hour', rides.requested_at) = w.recorded_at
  OR on date: rides.requested_at::date = w.recorded_at::date
- For cancellation correlation: calculate total rides, cancelled rides, and cancellation percentage:
  ROUND((SUM(CASE WHEN rides.status = 'cancelled' THEN 1 ELSE 0 END)::numeric / NULLIF(COUNT(rides.ride_id), 0)) * 100, 2) AS cancellation_rate_pct
- For surge multiplier correlation: compute AVG(rides.surge_multiplier) grouped by w.is_rainy or weather condition.

IMPORTANT RULES:
1. Generate valid PostgreSQL SQL.
2. Use ONLY tables and columns that exist in the schema.
3. Do NOT invent table names or column names.
4. Use appropriate JOINs between tables.
5. If the user does not specify the number of rows, limit the result to 10 rows.
6. Generate ONLY read-only SQL (SELECT or WITH).
7. Do NOT generate: INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, GRANT, REVOKE.
8. For text comparisons, use case-insensitive matching with ILIKE unless exact case is specified.
9. Ensure column aliases are clean and readable for user display (e.g., AS total_rides, AS avg_fare, AS cancellation_rate_pct).

IMPORTANT OUTPUT RULE:
- Return ONLY the final executable PostgreSQL SQL statement.
- Do NOT output explanations, comments, or markdown ticks.

USER QUESTION:
{curated_question}
"""

    state.Prompt_query_context = prompt
    return state


# ============================================================
# 3. GENERATE SQL
# ============================================================

def generate_sql(state: AgentSchema) -> AgentSchema:
    prompt = state.Prompt_query_context
    llm = pick_llm("medium")
    response = llm.invoke(prompt)

    raw_text = response.content.strip()

    # 1. Clean reasoning tags if model output <think>
    clean_text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL | re.IGNORECASE)
    clean_text = re.sub(r"</?think>", "", clean_text, flags=re.IGNORECASE).strip()

    # 2. Prefer fenced code blocks if present
    fences = re.findall(r"```(?:sql)?\s*([\s\S]*?)\s*```", clean_text, flags=re.IGNORECASE)
    if fences:
        # Take the last fenced block (which usually represents the final query)
        candidate_sql = fences[-1].strip()
    else:
        candidate_sql = clean_text

    # 3. Find the beginning of SELECT or WITH
    sql_match = re.search(r"\b(?:SELECT|WITH)\b[\s\S]*", candidate_sql, flags=re.IGNORECASE)
    if sql_match:
        extracted_sql = sql_match.group(0).strip()
    else:
        extracted_sql = candidate_sql

    # 4. If there is a semicolon terminating the statement, keep up to that semicolon
    if ";" in extracted_sql:
        extracted_sql = extracted_sql.split(";", 1)[0] + ";"
    else:
        extracted_sql = extracted_sql + ";"

    # Final cleanup of markdown ticks
    extracted_sql = extracted_sql.replace("```", "").strip()

    state.generated_sql_query = extracted_sql
    return state


# ============================================================
# 4. EXTRACT JSON FROM JUDGE RESPONSE
# ============================================================

def extract_json(text: str) -> dict:
    text = text.strip()
    if "<think>" in text and "</think>" in text:
        text = text.split("</think>", 1)[1].strip()

    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

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

    # Safe fallback if judge JSON fails
    return {"answer": "Yes" if "safe" in text.lower() and "unsafe" not in text.lower() else "No", "comments": text[:100]}


# ============================================================
# 5. SQL SECURITY JUDGE
# ============================================================

def is_safe_sql(state: AgentSchema) -> AgentSchema:
    sql_query = state.generated_sql_query
    llm = pick_llm("high")

    prompt = f"""
You are an SQL Security Judge for a PostgreSQL database.

Your task is to determine whether the generated SQL query is safe to execute.

A query is SAFE only when it performs read-only data retrieval (SELECT, WITH).

The following operations are strictly UNSAFE:
- INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, GRANT, REVOKE, EXECUTE

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

    response = llm.invoke(prompt)
    data = extract_json(response.content)

    try:
        result = JudgeSchema.model_validate(data)
        state.is_safe = result.answer
        state.comments = result.comments
    except Exception:
        state.is_safe = "Yes" if data.get("answer", "").lower() == "yes" else "No"
        state.comments = data.get("comments", "Evaluated by security judge")

    return state


# ============================================================
# 6. CONDITIONAL ROUTING
# ============================================================

def is_safe_sql_edge(state: AgentSchema) -> str:
    if state.is_safe.lower() == "yes":
        return "execute_sql"
    return "canceled_sql"


# ============================================================
# 7. CANCEL UNSAFE SQL
# ============================================================

def canceled_sql(state: AgentSchema) -> AgentSchema:
    state.final_answer = (
        "⚠️ **Query Blocked**: The generated SQL query was flagged as potentially unsafe.\n\n"
        f"**Reason:** {state.comments}\n\n"
        f"**Generated SQL:**\n```sql\n{state.generated_sql_query}\n```"
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
- When presenting weather vs ride metrics, express results in terms of **observed correlations** (e.g., "The data shows that during rainy periods..."). Avoid claiming direct causality.
- Format multi-row results neatly with bullet points or summary highlights.

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
sql_agent_graph.add_node("is_safe_sql", is_safe_sql)
sql_agent_graph.add_node("canceled_sql", canceled_sql)
sql_agent_graph.add_node("execute_sql", execute_sql)
sql_agent_graph.add_node("represent_final_answer", represent_final_answer)

sql_agent_graph.add_edge(START, "curate_ques")
sql_agent_graph.add_edge("curate_ques", "prompt_query_context")
sql_agent_graph.add_edge("prompt_query_context", "generate_sql")
sql_agent_graph.add_edge("generate_sql", "is_safe_sql")

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
        "user_question": "Does rainfall correlate with ride cancellations?",
        "curated_ques": "",
        "Prompt_query_context": "",
        "generated_sql_query": "",
        "is_safe": "No",
        "comments": "",
        "sql_query_execution_result": "",
        "final_answer": ""
    }
    res = sql_analyst.invoke(test_input)
    print("\n--- SQL Analyst Result ---")
    print("SQL:", res.get("generated_sql_query"))
    print("Safe:", res.get("is_safe"))
    print("Final Answer:", res.get("final_answer"))
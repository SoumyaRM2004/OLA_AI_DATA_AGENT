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

from utils.llm_pick import pick_llm, get_message_text
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


def find_top_level_clause(sql: str, keyword: str) -> int:
    """Finds the index of a top-level SQL keyword (outside parentheses and string literals)."""
    depth = 0
    in_str = False
    kw_len = len(keyword)
    sql_upper = sql.upper()
    kw_upper = keyword.upper()

    for i in range(len(sql)):
        ch = sql[i]
        if ch == "'":
            in_str = not in_str
        elif not in_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif depth == 0:
                if sql_upper[i:i + kw_len] == kw_upper:
                    before_ok = (i == 0 or (not sql[i - 1].isalnum() and sql[i - 1] != '_'))
                    after_ok = (i + kw_len >= len(sql) or (not sql[i + kw_len].isalnum() and sql[i + kw_len] != '_'))
                    if before_ok and after_ok:
                        return i
    return -1


def sanitize_group_by_sql(sql: str) -> str:
    """
    Ensures SQL queries with date truncation or temporal grouping are PostgreSQL-valid.
    Fixes cases where DATE_TRUNC is in SELECT but GROUP BY uses alias or partial extract (year, month).
    """
    if not sql or not isinstance(sql, str):
        return sql

    cleaned = sql.strip()

    # Find all DATE_TRUNC expressions
    date_trunc_matches = list(re.finditer(r"DATE_TRUNC\s*\(\s*'(\w+)'\s*,\s*([a-zA-Z0-9_\.]+)\s*\)", cleaned, re.IGNORECASE))
    if not date_trunc_matches:
        return cleaned

    group_by_idx = find_top_level_clause(cleaned, "GROUP BY")
    if group_by_idx == -1:
        return cleaned

    gb_start = group_by_idx + len("GROUP BY")
    next_clause_indices = []
    for next_kw in ["HAVING", "ORDER BY", "LIMIT"]:
        idx = find_top_level_clause(cleaned[gb_start:], next_kw)
        if idx != -1:
            next_clause_indices.append(gb_start + idx)

    gb_end = min(next_clause_indices) if next_clause_indices else (len(cleaned) - 1 if cleaned.endswith(";") else len(cleaned))
    group_by_clause = cleaned[gb_start:gb_end].strip()

    for m in date_trunc_matches:
        col = m.group(2)
        full_expr = m.group(0)

        full_expr_norm = re.sub(r"\s+", "", full_expr.lower())
        gb_norm = re.sub(r"\s+", "", group_by_clause.lower())
        col_norm = re.sub(r"\s+", "", col.lower())

        if full_expr_norm not in gb_norm and col_norm not in gb_norm:
            # Replace invalid temporal aliases or EXTRACT expressions in GROUP BY
            items = [it.strip() for it in group_by_clause.split(",")]
            new_items = []
            replaced = False
            for it in items:
                it_l = it.lower().strip()
                if it_l in ("year", "month", "day", "hour", "week", "quarter", "month_start", "date") or "extract(" in it_l:
                    if not replaced:
                        new_items.append(full_expr)
                        replaced = True
                else:
                    new_items.append(it)
            if not replaced:
                new_items.append(full_expr)
            new_gb = " " + ", ".join(new_items) + " "

            # Reconstruct SQL with new GROUP BY
            cleaned = cleaned[:gb_start] + new_gb + cleaned[gb_end:]

            # Re-locate from_idx and fix unaggregated raw column inside EXTRACT in SELECT
            from_idx = find_top_level_clause(cleaned, "FROM")
            if from_idx != -1:
                select_portion = cleaned[:from_idx]
                pattern = re.compile(
                    r"\bEXTRACT\s*\(\s*(YEAR|MONTH|DAY|HOUR|QUARTER|WEEK)\s+FROM\s+" + re.escape(col) + r"\s*\)",
                    re.IGNORECASE
                )
                fixed_select = pattern.sub(lambda match: f"EXTRACT({match.group(1)} FROM {full_expr})", select_portion)
                if fixed_select != select_portion:
                    cleaned = fixed_select + cleaned[from_idx:]

    return cleaned.strip()


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

    # 8. Check for placeholder ellipsis (...)
    if "..." in sql:
        return False, "", "Incomplete SQL query containing ellipsis '...' detected."

    # 9. Check for chained statements / multiple semicolons outside single quotes
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

    # 10. Automatically sanitize & normalize GROUP BY expressions (e.g. DATE_TRUNC temporal grouping)
    sanitized_body = sanitize_group_by_sql(cleaned_body)

    # Clean, single-statement SQL with terminating semicolon
    final_sql = sanitized_body.rstrip(";").strip() + ";"
    return True, final_sql, ""


# ============================================================
# HELPER: EXTRACT JSON
# ============================================================

def extract_json(raw_input: Any) -> dict:
    """
    Safely parses JSON dictionary from string or list content.
    """
    text = get_message_text(raw_input)
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

IMPORTANT ENTITY & SCOPE RULES:
1. "Users" without qualification refers to ALL users in the users table (total users count). Do NOT restrict "users" to only riders or only drivers unless explicitly asked (e.g. "how many riders", "how many drivers").
2. "Now", "currently", "at this moment", or "how many users are there now?" refers to querying the CURRENT live PostgreSQL database state.
3. Do not answer the question.
4. Do not write SQL.
5. Return ONLY the refined, standalone question.

User Question:
{user_question}
"""

    response = llm.invoke(prompt)
    curated_question = get_message_text(response)

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

IMPORTANT DATABASE STATE & AUTHORITY RULES:
- PostgreSQL is the single authoritative source of truth. The database state is dynamic and may have been updated recently via CSV data imports (Upsert, Append, Replace).
- Always generate a fresh SQL query against PostgreSQL to retrieve current database facts and metrics.
- For general user count ("how many users", "total users", "users count", "how many users now"), generate `SELECT COUNT(*) FROM public.users;`. Only filter by `user_type = 'rider'` or `user_type = 'driver'` when explicitly asked for riders or drivers.
- For total rides: `SELECT COUNT(*) FROM public.rides;`.
- For total vehicles: `SELECT COUNT(*) FROM public.vehicles;`.
- For total payments: `SELECT COUNT(*) FROM public.payments;`.
- For total ratings: `SELECT COUNT(*) FROM public.ratings;`.

DATABASE SCHEMA:
{schema_info}

TABLES & RELATIONSHIPS OVERVIEW:
- users: user_id, first_name, last_name, email, phone, city (Calgary, Edmonton, Halifax, Montreal, Ottawa, Toronto, Vancouver, Winnipeg), user_type ('rider', 'driver'), signup_date, is_active.
- vehicles: vehicle_id, driver_id, vehicle_type, make, model, year, license_plate.
- rides: ride_id, rider_id, driver_id, vehicle_id, pickup_latitude, pickup_longitude, dropoff_latitude, dropoff_longitude, requested_at, pickup_time, dropoff_time, fare, distance_km, surge_multiplier, status ('completed', 'cancelled', 'in_progress'), cancellation_reason.
  * NOTE: rides does NOT have a direct 'city' column. To get the city for a ride, JOIN users ON rides.rider_id = users.user_id.
- payments: payment_id, ride_id, user_id, amount, payment_method ('card', 'cash', 'upi', 'wallet'), payment_status ('completed', 'successful', 'failed', 'refunded'), transaction_id.
- ratings: rating_id, ride_id, rider_id, driver_id, rating (1-5), comment, rated_at.
- weather_data: weather_id, recorded_at (timestamp), city (Calgary, Edmonton, Halifax, Montreal, Ottawa, Toronto, Vancouver, Winnipeg), latitude, longitude, temperature_c, precipitation_mm, rain_mm, weather_code, is_rainy (boolean).
  * Temporal Coverage: Hourly observations for January 2025 (2025-01-01 to 2025-01-31) across all 8 cities (5,952 total records).
  * NOTE: There is NO 'timezone' or 'wind_speed' column.

RULES FOR OUTPUT FORMAT:
Return ONLY a valid JSON object matching this structure:
{{
  "can_be_answered": true,
  "sql_query": "SELECT u.city, COUNT(*) FROM public.rides r JOIN public.users u ON r.rider_id = u.user_id GROUP BY u.city;",
  "explanation": ""
}}

CRITICAL SCHEMA LIMITATION RULES:
1. Examine the schema carefully. If the user asks for attributes, metrics, or columns that DO NOT EXIST in the schema (e.g. timezone, user age, driver salary, wind speed):
   - Set "can_be_answered": false
   - Set "sql_query": ""
   - Set "explanation": "Provide a clear, helpful statement explaining what columns/information exist and that the requested attribute (e.g. timezone) is not available in the database schema."
   - NEVER hallucinate or invent non-existent column names or tables!
2. If "can_be_answered": true:
   - "sql_query" MUST contain ONLY the full, single executable PostgreSQL statement (SELECT or WITH).
   - NEVER use ellipsis '...' in sql_query. Write the full query explicitly.
   - Do NOT include markdown code fences, comments, thoughts, or conversational text in "sql_query".
   - Use appropriate JOINs between tables.
   - For correlation between rides and weather, join via users and hourly timestamp:
     `JOIN public.users u ON rides.rider_id = u.user_id JOIN public.weather_data w ON u.city = w.city AND DATE_TRUNC('hour', rides.requested_at) = w.recorded_at`
     (or date match: `u.city = w.city AND rides.requested_at::date = w.recorded_at::date`).
   - COMPARATIVE WEATHER QUERIES: If the user asks whether rain increases, decreases, or is associated with cancellations, fares, or surge in a city (e.g. Ottawa) or overall, generate a query comparing BOTH rainy and non-rainy conditions (e.g. `w.is_rainy`, ride count, cancellations, cancellation rate) so a direct, valid comparison can be made:
     `SELECT u.city, w.is_rainy, COUNT(r.ride_id) AS total_rides, SUM(CASE WHEN r.status = 'cancelled' THEN 1 ELSE 0 END) AS cancellations, ROUND(SUM(CASE WHEN r.status = 'cancelled' THEN 1 ELSE 0 END) * 100.0 / COUNT(r.ride_id), 2) AS cancellation_rate FROM public.rides r JOIN public.users u ON r.rider_id = u.user_id JOIN public.weather_data w ON u.city = w.city AND DATE_TRUNC('hour', r.requested_at) = w.recorded_at WHERE u.city ILIKE 'Ottawa' GROUP BY u.city, w.is_rainy;`
   - POSTGRESQL TEMPORAL & DATE-TRUNCATION GROUP BY RULES:
     * When grouping or aggregating by time periods (monthly, daily, hourly, weekly):
       - ALWAYS group by the single `DATE_TRUNC` expression directly:
         `SELECT DATE_TRUNC('month', requested_at) AS month_start, COUNT(*) AS total_rides, SUM(fare) AS total_revenue FROM public.rides GROUP BY DATE_TRUNC('month', requested_at) ORDER BY month_start;`
       - If separate year and month columns are needed, derive them from `month_start` in a CTE / outer query, OR use `EXTRACT(YEAR FROM DATE_TRUNC('month', requested_at))` with `GROUP BY DATE_TRUNC('month', requested_at)`:
         `WITH monthly_summary AS (SELECT DATE_TRUNC('month', requested_at) AS month_start, COUNT(*) AS total_rides, SUM(fare) AS total_revenue FROM public.rides GROUP BY DATE_TRUNC('month', requested_at)) SELECT month_start, EXTRACT(YEAR FROM month_start)::int AS year, EXTRACT(MONTH FROM month_start)::int AS month, total_rides, total_revenue FROM monthly_summary ORDER BY month_start;`
       - STRICT POSTGRESQL RULE: NEVER write `DATE_TRUNC('month', requested_at) AS month_start, EXTRACT(YEAR FROM requested_at) ... GROUP BY year, month`. In PostgreSQL, every non-aggregated column or expression in SELECT must appear in the GROUP BY clause.
   - RESULT LIMITING RULES (Context-Aware):
     * If the user specifically asks for top/bottom/first N rows (e.g., 'top 5', 'first 10', 'city with highest rainfall'), add LIMIT N.
     * For group-by aggregations (e.g., by date, by status, by city across all 8 cities, by payment method, coverage comparisons), do NOT arbitrarily add LIMIT 10 so the full aggregated dataset is available.
     * For large raw table dumps without aggregation (e.g., SELECT * FROM rides), apply a reasonable LIMIT 50.
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

    for tier in ["medium", "high"]:
        try:
            llm = pick_llm(tier)
            response = llm.invoke(prompt)
            raw_text = get_message_text(response)
            data = extract_json(raw_text)
            validated = SQLGenerationSchema.model_validate(data)

            if validated.can_be_answered and validated.sql_query:
                query_str = validated.sql_query.strip()
                if "..." in query_str:
                    raise ValueError("Generated query contains ellipsis '...'")
                valid, clean_sql, err = validate_sql_deterministic(query_str)
                if not valid:
                    raise ValueError(f"Deterministic validation failed: {err}")
                state.can_be_answered = True
                state.schema_explanation = ""
                state.generated_sql_query = clean_sql
                return state
            else:
                state.can_be_answered = False
                state.schema_explanation = validated.explanation or ""
                state.generated_sql_query = ""
                return state

        except Exception as e:
            if tier == "high":
                state.can_be_answered = False
                state.schema_explanation = f"Could not generate a structured query for this request: {e}"
                state.generated_sql_query = ""
                state.error = str(e)
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
        raw_text = get_message_text(response)
        data = extract_json(raw_text)
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

# ============================================================
# 8. EXECUTE SQL & DIAGNOSTIC COVERAGE ANALYZER
# ============================================================

def diagnose_query_coverage(sql_query: str, db: DatabaseConnection) -> Dict[str, Any]:
    """
    Analyzes dataset coverage and overlap when queries involve joins (especially rides and weather_data)
    or when queries return zero rows.
    
    Distinguishes:
    - NO_OVERLAP: rides and weather records exist, but there is 0 city/hour overlap
    - PARTIAL_OVERLAP: some rides match hourly weather observations, some do not
    - FULL_OVERLAP: all scoped rides have matching weather observations
    - EMPTY_RIDES: rides table is empty
    - EMPTY_WEATHER: weather_data table is empty
    - NO_FILTER_MATCH: non-weather query where table has rows but filter matched 0 rows
    """
    sql_l = sql_query.lower()
    is_weather_query = "weather_data" in sql_l or "weather" in sql_l
    is_rides_query = "rides" in sql_l or "ride" in sql_l
    is_users_query = "users" in sql_l or "user" in sql_l

    diagnostics: Dict[str, Any] = {
        "is_weather_rides_join": False,
        "overlap_status": "NORMAL",
        "total_rides": 0,
        "total_weather_records": 0,
        "scoped_rides": 0,
        "matched_rides": 0,
        "unmatched_rides": 0,
        "min_ride_time": None,
        "max_ride_time": None,
        "min_weather_time": None,
        "max_weather_time": None,
        "city_filter": None,
        "explanation": ""
    }

    try:
        if is_weather_query and (is_rides_query or is_users_query):
            diagnostics["is_weather_rides_join"] = True

            # Detect city filter if present
            cities = ["Calgary", "Edmonton", "Halifax", "Montreal", "Ottawa", "Toronto", "Vancouver", "Winnipeg"]
            filtered_city = None
            for c in cities:
                if f"'{c.lower()}'" in sql_l or f"'%{c.lower()}%'" in sql_l or f"\"{c.lower()}\"" in sql_l or f" {c.lower()} " in sql_l:
                    filtered_city = c
                    break
            diagnostics["city_filter"] = filtered_city

            city_where = f"WHERE u.city ILIKE '%{filtered_city}%'" if filtered_city else ""
            weather_city_where = f"WHERE city ILIKE '%{filtered_city}%'" if filtered_city else ""

            diag_sql = f"""
                SELECT 
                    (SELECT COUNT(*) FROM public.rides) AS total_rides,
                    (SELECT COUNT(*) FROM public.weather_data {weather_city_where}) AS total_weather,
                    (SELECT MIN(requested_at) FROM public.rides) AS min_ride_time,
                    (SELECT MAX(requested_at) FROM public.rides) AS max_ride_time,
                    (SELECT MIN(recorded_at) FROM public.weather_data {weather_city_where}) AS min_weather_time,
                    (SELECT MAX(recorded_at) FROM public.weather_data {weather_city_where}) AS max_weather_time,
                    COUNT(r.ride_id) AS scoped_rides,
                    COUNT(w.recorded_at) AS matched_rides,
                    COUNT(r.ride_id) - COUNT(w.recorded_at) AS unmatched_rides
                FROM public.rides r
                JOIN public.users u ON r.rider_id = u.user_id
                LEFT JOIN public.weather_data w 
                    ON u.city = w.city 
                   AND DATE_TRUNC('hour', r.requested_at) = w.recorded_at
                {city_where};
            """

            res = db.execute_query_structured(diag_sql)
            if res["records"]:
                rec = res["records"][0]
                total_rides = int(rec.get("total_rides") or 0)
                total_weather = int(rec.get("total_weather") or 0)
                scoped_rides = int(rec.get("scoped_rides") or 0)
                matched_rides = int(rec.get("matched_rides") or 0)
                unmatched_rides = int(rec.get("unmatched_rides") or 0)

                min_ride = rec.get("min_ride_time")
                max_ride = rec.get("max_ride_time")
                min_weather = rec.get("min_weather_time")
                max_weather = rec.get("max_weather_time")

                diagnostics["total_rides"] = total_rides
                diagnostics["total_weather_records"] = total_weather
                diagnostics["scoped_rides"] = scoped_rides
                diagnostics["matched_rides"] = matched_rides
                diagnostics["unmatched_rides"] = unmatched_rides
                diagnostics["min_ride_time"] = str(min_ride) if min_ride else "N/A"
                diagnostics["max_ride_time"] = str(max_ride) if max_ride else "N/A"
                diagnostics["min_weather_time"] = str(min_weather) if min_weather else "N/A"
                diagnostics["max_weather_time"] = str(max_weather) if max_weather else "N/A"

                min_r_str = diagnostics["min_ride_time"][:10]
                max_r_str = diagnostics["max_ride_time"][:10]
                min_w_str = diagnostics["min_weather_time"][:10]
                max_w_str = diagnostics["max_weather_time"][:10]

                if total_rides == 0:
                    diagnostics["overlap_status"] = "EMPTY_RIDES"
                    diagnostics["explanation"] = "No comparable rides were found because the public.rides table is currently empty in the database."
                elif total_weather == 0:
                    diagnostics["overlap_status"] = "EMPTY_WEATHER"
                    diagnostics["explanation"] = "No comparable weather observations were found because the public.weather_data table is currently empty in the database."
                elif matched_rides == 0:
                    diagnostics["overlap_status"] = "NO_OVERLAP"
                    scope_info = f" in {filtered_city}" if filtered_city else ""
                    diagnostics["explanation"] = (
                        f"No comparable rides were found{scope_info} because the available weather data does not overlap the ride timestamps/cities.\n\n"
                        f"**Dataset Coverage:**\n"
                        f"- **Rides in database**: {scoped_rides:,} records spanning {min_r_str} to {max_r_str}.\n"
                        f"- **Weather observations**: {total_weather:,} hourly observations covering {min_w_str} to {max_w_str} across 8 Canadian cities.\n\n"
                        f"Because the ride timestamps fall outside the available weather observation window, a comparison between rainy and non-rainy periods cannot be computed for these records."
                    )
                elif matched_rides < scoped_rides:
                    diagnostics["overlap_status"] = "PARTIAL_OVERLAP"
                    diagnostics["explanation"] = (
                        f"Partial weather overlap detected: {matched_rides:,} of {scoped_rides:,} rides have corresponding hourly weather observations. "
                        f"{unmatched_rides:,} rides have no matching weather data and are excluded from the comparison."
                    )
                else:
                    diagnostics["overlap_status"] = "FULL_OVERLAP"
                    diagnostics["explanation"] = f"Full weather overlap: all {matched_rides:,} rides have matching hourly weather observations."

        else:
            # Check non-weather empty queries
            tables = ["users", "rides", "vehicles", "payments", "ratings", "weather_data"]
            matched_table = None
            for tbl in tables:
                if f"public.{tbl}" in sql_l or f" {tbl} " in sql_l or f" {tbl}," in sql_l:
                    matched_table = tbl
                    break

            if matched_table:
                count_res = db.execute_query_structured(f"SELECT COUNT(*) AS total FROM public.{matched_table};")
                if count_res["records"]:
                    tbl_count = int(count_res["records"][0].get("total") or 0)
                    if tbl_count == 0:
                        diagnostics["overlap_status"] = "EMPTY_TABLE"
                        diagnostics["explanation"] = f"The public.{matched_table} table is currently empty in the database."
                    else:
                        diagnostics["overlap_status"] = "NO_FILTER_MATCH"
                        diagnostics["explanation"] = f"No records in public.{matched_table} matched the specific filter criteria (the table contains {tbl_count:,} total records)."
    except Exception as e:
        print(f"Error analyzing query diagnostics: {e}")

    return diagnostics


def diagnose_empty_result(sql_query: str, curated_question: str, db: DatabaseConnection) -> Dict[str, Any]:
    """
    Runs lightweight diagnostic queries when an analytical query returns 0 rows.
    Determines whether a requested filter/threshold (e.g. >= 20 completed rides) is impossible
    and provides factual supporting evidence (e.g. actual max completed rides in the database)
    without relaxing the threshold or fabricating results.
    """
    diag = {
        "has_diagnostic": False,
        "type": "NONE",
        "explanation": ""
    }
    if not sql_query:
        return diag

    sql_clean = sql_query.strip().rstrip(";")

    # 1. Check for HAVING clause threshold (e.g. HAVING COUNT(*) >= 20)
    having_idx = find_top_level_clause(sql_clean, "HAVING")
    if having_idx != -1:
        having_start = having_idx + len("HAVING")
        next_indices = []
        for kw in ["ORDER BY", "LIMIT"]:
            idx = find_top_level_clause(sql_clean[having_start:], kw)
            if idx != -1:
                next_indices.append(having_start + idx)
        having_end = min(next_indices) if next_indices else len(sql_clean)
        having_expr = sql_clean[having_start:having_end].strip()

        # Base grouping query without HAVING, ORDER BY, LIMIT
        base_query = sql_clean[:having_idx].strip()
        
        try:
            # Check column count
            sample_res = db.execute_query_structured(f"SELECT * FROM ({base_query}) AS sub LIMIT 1;")
            num_cols = len(sample_res.get("columns", []))
            metric_col_idx = num_cols if num_cols >= 1 else 2
            
            top_sql = f"SELECT * FROM ({base_query}) AS sub ORDER BY {metric_col_idx} DESC LIMIT 1;"
            count_sql = f"SELECT COUNT(*) AS total_groups FROM ({base_query}) AS sub;"

            res_top = db.execute_query_structured(top_sql)
            res_cnt = db.execute_query_structured(count_sql)

            if res_top.get("records") and res_cnt.get("records"):
                top_rec = res_top["records"][0]
                total_groups = int(res_cnt["records"][0].get("total_groups") or 0)

                cols = res_top["columns"]
                metric_col = cols[-1] if cols else "count"
                max_val = top_rec.get(metric_col)

                clean_metric_name = str(metric_col).replace("_", " ")
                entity = "drivers" if "driver" in curated_question.lower() or "driver" in sql_clean.lower() else (
                    "riders" if "rider" in curated_question.lower() or "rider" in sql_clean.lower() else (
                        "users" if "user" in curated_question.lower() or "user" in sql_clean.lower() else "entities"
                    )
                )

                diag["has_diagnostic"] = True
                diag["type"] = "HAVING_THRESHOLD_EXCEEDED"
                diag["max_value"] = max_val
                diag["total_groups"] = total_groups
                diag["metric_column"] = metric_col
                diag["having_expr"] = having_expr

                diag["explanation"] = (
                    f"No {entity} in the database met the requested criterion (`{having_expr}`).\n\n"
                    f"**Diagnostic Evidence:**\n"
                    f"- Across all **{total_groups:,}** {entity} in the database with matching activity, "
                    f"the maximum **{clean_metric_name}** achieved is **{max_val}**.\n"
                    f"- Because no {entity} has reached the requested threshold (`{having_expr}`), zero rows were returned."
                )
                return diag
        except Exception as e:
            print(f"Error diagnosing HAVING empty result: {e}")

    # 2. Check for WHERE clause numeric threshold (e.g. fare >= 5000, distance_km >= 500, rating >= 6)
    where_idx = find_top_level_clause(sql_clean, "WHERE")
    if where_idx != -1:
        where_start = where_idx + len("WHERE")
        next_indices = []
        for kw in ["GROUP BY", "HAVING", "ORDER BY", "LIMIT"]:
            idx = find_top_level_clause(sql_clean[where_start:], kw)
            if idx != -1:
                next_indices.append(where_start + idx)
        where_end = min(next_indices) if next_indices else len(sql_clean)
        where_expr = sql_clean[where_start:where_end].strip()

        num_comp = re.search(r"([a-zA-Z0-9_\.]+)\s*(>=|>|<=|<|=)\s*([0-9\.]+)", where_expr)
        if num_comp:
            col_name = num_comp.group(1).split(".")[-1]
            op = num_comp.group(2)
            val = num_comp.group(3)

            tables = ["rides", "users", "vehicles", "payments", "ratings", "weather_data"]
            tbl = next((t for t in tables if f"public.{t}" in sql_clean.lower() or f" {t} " in sql_clean.lower()), None)
            if tbl:
                try:
                    stats_sql = f"SELECT COUNT(*) AS total, MIN({col_name}) AS min_v, MAX({col_name}) AS max_v, ROUND(AVG({col_name}), 2) AS avg_v FROM public.{tbl} WHERE {col_name} IS NOT NULL;"
                    stats_res = db.execute_query_structured(stats_sql)
                    if stats_res.get("records"):
                        s = stats_res["records"][0]
                        total_cnt = int(s.get('total') or 0)
                        max_v = s.get('max_v')
                        min_v = s.get('min_v')
                        avg_v = s.get('avg_v')
                        
                        diag["has_diagnostic"] = True
                        diag["type"] = "WHERE_THRESHOLD_EXCEEDED"
                        diag["explanation"] = (
                            f"No records in `public.{tbl}` matched the filter `{where_expr}`.\n\n"
                            f"**Diagnostic Evidence:**\n"
                            f"- The table contains **{total_cnt:,}** total records.\n"
                            f"- The range of `{col_name}` in the database is from **{min_v}** to **{max_v}** (average: **{avg_v}**).\n"
                            f"- Because the maximum value recorded in the database is **{max_v}**, the condition `{col_name} {op} {val}` cannot be satisfied by any record."
                        )
                        return diag
                except Exception as e:
                    print(f"Error diagnosing WHERE numeric empty result: {e}")

    return diag


def execute_sql(state: AgentSchema) -> AgentSchema:
    sql_query = state.generated_sql_query
    db = DatabaseConnection()

    result_dict = db.execute_query_structured(sql_query)

    # Self-healing: if PostgreSQL returned a GROUP BY error, sanitize and retry once
    if result_dict.get("error") and "must appear in the GROUP BY clause" in str(result_dict.get("error")):
        sanitized_sql = sanitize_group_by_sql(sql_query)
        if sanitized_sql != sql_query:
            retry_dict = db.execute_query_structured(sanitized_sql)
            if not retry_dict.get("error"):
                result_dict = retry_dict
                state.generated_sql_query = sanitized_sql

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
    sql_query = state.generated_sql_query
    db = DatabaseConnection()

    if state.error:
        state.final_answer = f"Error executing query: {state.error}"
        state.messages = state.messages + [AIMessage(content=state.final_answer)]
        return state

    # Perform diagnostic analysis on coverage and joins
    diag = diagnose_query_coverage(sql_query, db)

    # 1. Handle No-Overlap scenario (INNER JOIN produced zero rows due to date/city mismatch)
    if diag["is_weather_rides_join"] and diag["overlap_status"] == "NO_OVERLAP":
        state.final_answer = diag["explanation"]
        state.messages = state.messages + [AIMessage(content=state.final_answer)]
        return state

    # 2. Handle empty source tables
    if diag["overlap_status"] in ("EMPTY_RIDES", "EMPTY_WEATHER", "EMPTY_TABLE"):
        state.final_answer = diag["explanation"]
        state.messages = state.messages + [AIMessage(content=state.final_answer)]
        return state

    # 3. Handle zero rows returned on non-weather query
    if not state.data_rows:
        diag_empty = diagnose_empty_result(sql_query, curated_question, db)
        if diag_empty.get("has_diagnostic") and diag_empty.get("explanation"):
            state.final_answer = diag_empty["explanation"]
        elif diag.get("explanation"):
            state.final_answer = f"{diag['explanation']} for query '{curated_question}'."
        else:
            state.final_answer = f"No records found in the database matching the criteria for '{curated_question}'."
        state.messages = state.messages + [AIMessage(content=state.final_answer)]
        return state

    # Build coverage instruction for LLM synthesis
    coverage_context = ""
    if diag["is_weather_rides_join"] and diag["overlap_status"] == "PARTIAL_OVERLAP":
        coverage_context = f"""
DIAGNOSTIC DATA COVERAGE (PARTIAL OVERLAP):
- Total rides in database: {diag['scoped_rides']:,}
- Rides with matching hourly weather observations: {diag['matched_rides']:,}
- Rides without weather observations (excluded): {diag['unmatched_rides']:,}
- Weather observation window: {diag['min_weather_time'][:10]} to {diag['max_weather_time'][:10]}

CRITICAL PARTIAL OVERLAP RULES:
1. Explicitly state that this analysis is based on the {diag['matched_rides']:,} rides with matching weather observations (out of {diag['scoped_rides']:,} total rides).
2. Report that {diag['unmatched_rides']:,} rides had no matching weather observations in the dataset and were excluded from this weather comparison.
3. NEVER classify rides with no weather observation as non-rainy or false. Unmatched rides are strictly excluded.
"""

    llm = pick_llm("low")

    prompt = f"""
You are an SQL Data Analyst assistant for an OLA-inspired mobility platform.

The user asked: "{curated_question}"
SQL Query Executed: {sql_query}
Database returned: {execution_result}
{coverage_context}

Your task is to present this data in a clear, well-structured, natural language response following strict analytical precision rules:

ANALYTICAL INTERPRETATION RULES:
1. FACTUAL DATA ACCURACY (POSTGRESQL AUTHORITY):
   - PostgreSQL is the single authoritative source of truth. Always report the exact numbers, metrics, and counts returned by the database execution result above.
   - For direct count questions (e.g. "How many users are there?", "How many users are in the database now?"), state the current number clearly and directly (e.g. "There are currently 10,020 users registered in the database.").
   - Never assume static numbers or rely on prior conversational assumptions for factual counts.
2. WEATHER AND RIDE ANALYSIS & COVERAGE:
   - If partial weather coverage is indicated, explicitly state that results are based on the matched rides (e.g., "Based on 1,057 rides with matching weather observations out of 20,000 total rides...").
   - A ride without a weather observation must NEVER be classified as false or non-rainy. Unmatched rides must strictly remain excluded.
3. DISTINGUISH SUBGROUP HIGHESTS FROM COMPARISONS:
   - Distinguish "highest cancellation rate among rainy rides" from "rain is associated with a higher cancellation rate".
   - If the query only analyzes rainy rides (e.g. across 8 cities), state:
     "Among the eight cities, Ottawa had the highest observed cancellation rate for rainy rides in January 2025: 21.43% (3 cancellations out of 14 rainy rides)."
   - Do NOT claim that rainy weather is associated with higher cancellations unless the query explicitly compares rainy AND non-rainy cancellation rates for the same city/scope.
4. ALWAYS INCLUDE SAMPLE SIZES:
   - When reporting a rate or percentage, always mention the numerator and denominator:
     e.g., "21.43% based on 14 rainy rides and 3 cancellations."
5. DO NOT CLAIM STATISTICAL SIGNIFICANCE:
   - Do not call a small sample statistically significant unless a formal statistical hypothesis test (e.g., p-value) has actually been performed.
6. STRICT NON-CAUSAL LANGUAGE:
   - Express results purely in terms of observed numbers and correlations (e.g., "During the observed period...", "coincided with..."). NEVER state that rain *causes* cancellations, surge pricing, or higher fares.
7. FORMATTING:
   - Format multi-row results neatly with markdown tables or bullet points.

Provide a concise, professional, and helpful answer:
"""

    response = llm.invoke(prompt)
    final_answer = get_message_text(response)

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
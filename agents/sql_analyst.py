import os
import sys
import json
import re

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
You are a question-curation assistant for an SQL data analyst.

Rewrite the user's question into a clear and concise question
that can be answered using a PostgreSQL database.

Do not answer the question.
Do not generate SQL.

Return only the curated question.

User Question:
{user_question}
"""

    response = llm.invoke(prompt)

    curated_question = response.content.strip()

    state.curated_ques = curated_question

    state.messages = state.messages + [
        HumanMessage(content=curated_question)
    ]

    return state


# ============================================================
# 2. CREATE SQL GENERATION CONTEXT
# ============================================================

def prompt_query_context(state: AgentSchema) -> AgentSchema:

    curated_question = state.curated_ques

    conn_details = {
        "host": os.getenv("host"),
        "port": os.getenv("port"),
        "user": os.getenv("user"),
        "password": os.getenv("password"),
        "dbname": os.getenv("database")
    }

    obj = DatabaseConnection(conn_details)

    # Get database schema
    schema_info = obj.schema_details("public")

    prompt = f"""
You are an SQL Data Analyst Agent.

Your task is to convert the user's natural-language question
into a valid PostgreSQL SQL query.

IMPORTANT RULES:

1. Generate valid PostgreSQL SQL.
2. Use ONLY tables and columns that exist in the schema.
3. Do NOT invent table names or column names.
4. Use appropriate JOINs when required.
5. If the user does not specify the number of rows,
   limit the result to 10 rows.
6. Generate ONLY read-only SQL.
7. Do NOT generate:
   INSERT
   UPDATE
   DELETE
   DROP
   ALTER
   TRUNCATE
   CREATE
   GRANT
   REVOKE
8. For text/string comparisons, use case-insensitive matching with ILIKE unless the user explicitly requires exact case.

IMPORTANT OUTPUT RULE:

Do not show your reasoning.
Do not output <think> or </think>.
Do not explain how you arrived at the query.
Return ONLY the final PostgreSQL SQL statement.

USER QUESTION:
{curated_question}

DATABASE SCHEMA:
{schema_info}
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

    generated_sql = response.content.strip()

    # --------------------------------------------------------
    # Remove <think>...</think> blocks
    # --------------------------------------------------------

    generated_sql = re.sub(
        r"<think>.*?</think>",
        "",
        generated_sql,
        flags=re.DOTALL | re.IGNORECASE
    )

    # Remove any remaining reasoning tags
    generated_sql = re.sub(
        r"</?think>",
        "",
        generated_sql,
        flags=re.IGNORECASE
    )

    # --------------------------------------------------------
    # Remove Markdown code fences
    # --------------------------------------------------------

    generated_sql = re.sub(
        r"```(?:sql)?",
        "",
        generated_sql,
        flags=re.IGNORECASE
    )

    generated_sql = generated_sql.replace("```", "").strip()


    # Find the beginning of the SQL statement

    sql_match = re.search(
        r"\b(?:SELECT|WITH)\b",
        generated_sql,
        flags=re.IGNORECASE
    )

    if not sql_match:
        raise ValueError(
            "The SQL generation model did not return "
            "a SELECT or WITH query."
        )

    generated_sql = generated_sql[sql_match.start():].strip()

    # Keep ONLY the first SQL statement


    if ";" in generated_sql:
        generated_sql = generated_sql.split(";", 1)[0] + ";"


    # Final cleanup


    generated_sql = generated_sql.strip()

    state.generated_sql_query = generated_sql

    return state

# ============================================================
# 4. EXTRACT JSON FROM JUDGE RESPONSE
# ============================================================

def extract_json(text: str) -> dict:

    text = text.strip()

    # Remove <think>...</think> if a reasoning model returns it
    if "<think>" in text and "</think>" in text:
        text = text.split("</think>", 1)[1].strip()

    # Remove Markdown JSON code fences
    text = re.sub(
        r"^```json\s*",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"\s*```$",
        "",
        text
    )

    # Try direct JSON parsing
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting the JSON object
    match = re.search(
        r"\{.*\}",
        text,
        re.DOTALL
    )

    if not match:
        raise ValueError(
            f"Judge did not return valid JSON.\nResponse:\n{text}"
        )

    return json.loads(match.group())


# ============================================================
# 5. SQL SECURITY JUDGE
# ============================================================

def is_safe_sql(state: AgentSchema) -> AgentSchema:

    sql_query = state.generated_sql_query

    llm = pick_llm("high")

    prompt = f"""
You are an SQL Security Judge.

Your task is to determine whether the generated SQL query
is safe to execute on a PostgreSQL database.

A query is SAFE only when it performs data retrieval.

The following operations are UNSAFE:

- INSERT
- UPDATE
- DELETE
- DROP
- ALTER
- TRUNCATE
- CREATE
- GRANT
- REVOKE

Any SQL operation that modifies database data or database
structure must be considered unsafe.

SELECT queries used only for retrieving data are generally safe.

Return ONLY valid JSON.

The JSON MUST have exactly these two fields:

{{
    "answer": "Yes",
    "comments": "Brief explanation."
}}

Rules for answer:

"Yes" = SQL query is safe to execute.

"No" = SQL query is unsafe to execute.

Keep comments short and clear.

SQL QUERY:
{sql_query}
"""

    response = llm.invoke(prompt) #model_dump()

    # Extract JSON from model response
    data = extract_json(response.content)

    # Validate response using Pydantic
    result = JudgeSchema.model_validate(data)

    state.is_safe= result.answer
    state.comments = result.comments

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
        "The generated SQL query was blocked because it was "
        f"considered unsafe.\n\nReason: {state.comments}"
    )

    state.messages = state.messages + [
        AIMessage(content=state.final_answer)
    ]

    return state


# ============================================================
# 8. EXECUTE SQL
# ============================================================

def execute_sql(state: AgentSchema) -> AgentSchema:

    sql_query = state.generated_sql_query

    conn_details = {
        "host": os.getenv("host"),
        "port": os.getenv("port"),
        "user": os.getenv("user"),
        "password": os.getenv("password"),
        "dbname": os.getenv("database")
    }

    obj = DatabaseConnection(conn_details)

    execution_result = obj.execute_query(sql_query)

    state.sql_query_execution_result = execution_result

    return state


# ============================================================
# 9. REPRESENT FINAL ANSWER
# ============================================================

def represent_final_answer(state: AgentSchema) -> AgentSchema:

    execution_result = state.sql_query_execution_result
    curated_question = state.curated_ques

    llm = pick_llm("low")

    prompt = f"""
You are an SQL Data Analyst assistant.

The user's question was answered by executing a SQL query
against a PostgreSQL database.

Your task is to present the database result to the user
in a clear, concise, natural-language answer.

Do not generate SQL.

Do not invent information.

Use only the provided execution result.

USER QUESTION:
{curated_question}

DATABASE EXECUTION RESULT:
{execution_result}

Provide a concise and useful answer.
"""

    response = llm.invoke(prompt)

    final_answer = response.content.strip()

    state.final_answer = final_answer

    state.messages = state.messages + [
        AIMessage(content=final_answer)
    ]

    return state


# ============================================================
# 10. BUILD LANGGRAPH
# ============================================================

sql_agent_graph = StateGraph(AgentSchema)


# ---------------------- Nodes ----------------------

sql_agent_graph.add_node(
    "curate_ques",
    curate_ques
)

sql_agent_graph.add_node(
    "prompt_query_context",
    prompt_query_context
)

sql_agent_graph.add_node(
    "generate_sql",
    generate_sql
)

sql_agent_graph.add_node(
    "is_safe_sql",
    is_safe_sql
)

sql_agent_graph.add_node(
    "canceled_sql",
    canceled_sql
)

sql_agent_graph.add_node(
    "execute_sql",
    execute_sql
)

sql_agent_graph.add_node(
    "represent_final_answer",
    represent_final_answer
)


# ---------------------- Normal Edges ----------------------

sql_agent_graph.add_edge(
    START,
    "curate_ques"
)

sql_agent_graph.add_edge(
    "curate_ques",
    "prompt_query_context"
)

sql_agent_graph.add_edge(
    "prompt_query_context",
    "generate_sql"
)

sql_agent_graph.add_edge(
    "generate_sql",
    "is_safe_sql"
)


# ---------------------- Conditional Edge ----------------------

sql_agent_graph.add_conditional_edges(
    "is_safe_sql",
    is_safe_sql_edge,
    {
        "execute_sql": "execute_sql",
        "canceled_sql": "canceled_sql"
    }
)

# sql_agent_graph.add_edge("is_safe_sql","execute_sql")
# sql_agent_graph.add_edge("is_safe_sql","canceled_sql")


# ---------------------- Remaining Edges ----------------------

sql_agent_graph.add_edge(
    "execute_sql",
    "represent_final_answer"
)

sql_agent_graph.add_edge(
    "represent_final_answer",
    END
)

sql_agent_graph.add_edge(
    "canceled_sql",
    END
)

sql_analyst = sql_agent_graph.compile()

# ============================================================
# 11. COMPILE
# ============================================================
if __name__=="__main__":
   



# ============================================================
# 12. DISPLAY GRAPH  #optional
# ============================================================

   from IPython.display import display, Image

   Img = Image(
      sql_analyst.get_graph().draw_mermaid_png()
   )

   display(Img)

   with open("sql_analyst_graph.png", "wb") as f:
      f.write(Img.data)

   print("Graph saved to sql_analyst_graph.png")
   
   input_schema={
      "messages":[],
      "user_question":"Give the driver id which get comment as Smooth ride ",
      "curated_ques":"",
      "Prompt_query_context":"",
      "generated_sql_query":"",
      "is_safe":"No",
      "comments":"",
      "sql_query_execution_result":"",
      "final_answer":""
   }
   
   #execute the graph
   sql_analyst_response=sql_analyst.invoke(input_schema)
   print("\nFinal Answer:")
   print(sql_analyst_response["final_answer"])
import os
import sys
import re
import logging

logging.getLogger("google.genai").setLevel(logging.ERROR)
logging.getLogger("google_genai").setLevel(logging.ERROR)

sys.path.append(
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..")
    )
)

from utils.llm_pick import pick_llm, get_message_text
from utils.etl_tools import ETLTools, CITY_COORDINATES
from model.schema import EtlAgentSchema
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from langchain.tools import tool


# ----------------------------------AGENT TOOLS----------------------------------------------------------

@tool
def extract_8_cities_weather_tool(
    start_date: str = "2025-01-01",
    end_date: str = "2025-01-31",
    output_folder: str = "data/extract",
    output_format: str = "csv"
) -> str:
    """
    Extracts hourly weather data for all 8 ride-hailing cities (Calgary, Edmonton, Halifax,
    Montreal, Ottawa, Toronto, Vancouver, Winnipeg) from Open-Meteo Archive API and
    saves the consolidated dataset into data/extract/weather_data.csv.
    
    Args:
        start_date: Start date in YYYY-MM-DD format (default: 2025-01-01).
        end_date: End date in YYYY-MM-DD format (default: 2025-01-31).
        output_folder: The directory to save the file into (default: data/extract).
        output_format: 'csv', 'json', or 'parquet'.
    """
    etl_tools = ETLTools()
    result = etl_tools.extract_multi_city_weather(start_date, end_date, output_folder, output_format)
    return result


@tool
def extract_load_tool(url: str, output_folder: str = "data/extract", output_format: str = "csv") -> str:
    """
    Extracts data from an external API (such as Open-Meteo Weather API or any REST endpoint)
    and saves it to the specified folder in CSV, JSON, or Parquet format.
    
    Args:
        url: The API URL endpoint.
        output_folder: The directory to save the file into (default: data/extract).
        output_format: 'csv', 'json', or 'parquet'.
    """
    etl_tools = ETLTools()
    result = etl_tools.extract_load(url, output_folder, output_format)
    return result


@tool
def transform_load_tool(
    input_file_path: str,
    output_folder: str = "data/transform",
    output_format: str = "csv",
    user_question: str = ""
) -> str:
    """
    Transforms data from an existing dataset file (e.g. weather data, ride data) using Pandas
    and saves the transformed dataset to the output folder.
    
    Args:
        input_file_path: Path to the raw data file (e.g. data/extract/weather_data.csv).
        output_folder: Directory to save transformed data (default: data/transform).
        output_format: 'csv', 'json', or 'parquet'.
        user_question: Specific filtering, cleaning, or aggregation requirement.
    """
    etl_tools = ETLTools()
    top_3_rows = etl_tools.transform_load_context(input_file_path)
    llm = pick_llm("low")

    prompt = f"""
You are an expert Python Data Analyst who uses Pandas to transform datasets.
Write ONLY executable Python code (using pandas as pd and os) that performs the requested ETL transformation.

RULES:
1. Load dataset from: '{input_file_path}'
2. Perform transformation: '{user_question}'
3. Save result to directory: '{output_folder}' with format '{output_format}' (e.g., 'weather_transformed.{output_format}')
4. Ensure os.makedirs('{output_folder}', exist_ok=True) is called.
5. Return ONLY python code without markdown fences, explanation, or comments.

Dataset Context:
{top_3_rows}
"""

    response = llm.invoke(prompt)
    pandas_code = get_message_text(response)

    pandas_code = pandas_code.strip()
    pandas_code = re.sub(r"^```(?:python)?\s*", "", pandas_code, flags=re.IGNORECASE)
    pandas_code = re.sub(r"\s*```$", "", pandas_code).strip()

    # Execute the code
    results = etl_tools.execute_code(pandas_code)

    return f"Transformation complete.\n\nGenerated Code:\n```python\n{pandas_code}\n```\n\nExecution Log:\n{results}"


@tool
def load_to_postgres_tool(file_path: str = "data/extract/weather_data.csv", table_name: str = "weather_data") -> str:
    """
    Loads an extracted or transformed CSV/JSON dataset into a PostgreSQL database table (e.g. weather_data)
    with duplicate prevention (upsert on city + recorded_at).
    
    Args:
        file_path: Path to the dataset file to load.
        table_name: Target PostgreSQL table name (default: weather_data).
    """
    etl_tools = ETLTools()
    result = etl_tools.load_to_database(file_path, table_name)
    return result


tools = [extract_8_cities_weather_tool, extract_load_tool, transform_load_tool, load_to_postgres_tool]
llm = pick_llm("low")
llm_bind = llm.bind_tools(tools)


# -------------------------------------------------------AGENT GRAPH-------------------------------------------------------------------------------------

def llm_node(state: EtlAgentSchema):
    messages = state.messages
    prompt = f"""
You are an ETL Data Analyst for an OLA-inspired mobility platform with tools to:
1. Extract weather data across all 8 ride-hailing cities (Calgary, Edmonton, Halifax, Montreal, Ottawa, Toronto, Vancouver, Winnipeg) from Open-Meteo Archive API.
2. Extract generic API data from REST endpoints.
3. Transform datasets using Pandas.
4. Load datasets into PostgreSQL tables (e.g. weather_data) with duplicate prevention.

Available 8 Cities: {', '.join(CITY_COORDINATES.keys())}
Rides Date Overlap: January 2025 (2025-01-01 to 2025-01-31)

Given the user request, call the appropriate tool with the right parameters.
"""
    history = [HumanMessage(content=prompt)] + messages
    response = llm_bind.invoke(history)
    return {"messages": [response]}


def tool_execution(state: EtlAgentSchema):
    last_message = state.messages[-1]
    tool_calls = getattr(last_message, "tool_calls", [])
    tool_messages = []

    tools_dict = {
        "extract_8_cities_weather_tool": extract_8_cities_weather_tool,
        "extract_load_tool": extract_load_tool,
        "transform_load_tool": transform_load_tool,
        "load_to_postgres_tool": load_to_postgres_tool
    }

    for tool_call in tool_calls:
        name = tool_call["name"]
        args = tool_call["args"]
        call_id = tool_call["id"]

        if name in tools_dict:
            try:
                selected_tool = tools_dict[name]
                tool_output = selected_tool.invoke(args)
            except Exception as e:
                tool_output = f"Tool execution failed: {e}"
        else:
            tool_output = f"Unknown tool: {name}"

        tool_messages.append(ToolMessage(
            content=str(tool_output),
            tool_call_id=call_id
        ))

    return {"messages": tool_messages}


def condition_node(state: EtlAgentSchema):
    last_message = state.messages[-1]
    tool_calls = getattr(last_message, "tool_calls", [])
    if len(tool_calls) > 0:
        return "tool_execution"
    return END


# ----------------------------------------------------GRAPH COMPILATION---------------------------------------------------

graph = StateGraph(EtlAgentSchema)
graph.add_node("llm_node", llm_node)
graph.add_node("tool_execution", tool_execution)

graph.add_edge(START, "llm_node")
graph.add_conditional_edges("llm_node", condition_node)
graph.add_edge("tool_execution", "llm_node")

etl_analyst = graph.compile()
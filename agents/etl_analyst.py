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
from utils.etl_tools import ETLTools
from model.schema import EtlAgentSchema
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from langchain.tools import tool


# ----------------------------------AGENT TOOLS----------------------------------------------------------

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
    llm = pick_llm("gemini")

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
    for subsequent SQL analysis and cross-table joins.
    
    Args:
        file_path: Path to the dataset file to load.
        table_name: Target PostgreSQL table name (default: weather_data).
    """
    etl_tools = ETLTools()
    result = etl_tools.load_to_database(file_path, table_name)
    return result


tools = [extract_load_tool, transform_load_tool, load_to_postgres_tool]
llm = pick_llm("gemini")
llm_bind = llm.bind_tools(tools)


# -------------------------------------------------------AGENT GRAPH-------------------------------------------------------------------------------------

def llm_node(state: EtlAgentSchema):
    messages = state.messages
    prompt = f"""
You are an ETL Data Analyst for an OLA-inspired mobility platform with tools to:
1. Extract external API data (such as Open-Meteo Weather data or other open data endpoints).
2. Transform datasets using Pandas.
3. Load extracted datasets into PostgreSQL tables (like weather_data) for cross-table analytics.

Given the user request, call the appropriate tool with the right parameters.

Chat History:
{messages}
"""
    response = llm_bind.invoke(prompt)
    state.messages = messages + [response]
    return state


def tool_node(state: EtlAgentSchema):
    tools_results = []
    tools_by_name = {tool.name: tool for tool in tools}
    tool_calls = state.messages[-1].tool_calls

    for tool_call in tool_calls:
        tool_obj = tools_by_name[tool_call["name"]]
        observation = tool_obj.invoke(tool_call["args"])
        tools_results.append(
            ToolMessage(
                content=str(observation),
                tool_call_id=tool_call["id"]
            )
        )

    state.messages = state.messages + tools_results
    return state


# ------------------------------------------Nodes & Edges--------------------------------------------------------

etl_analyst_graph = StateGraph(EtlAgentSchema)
etl_analyst_graph.add_node("llm_node", llm_node)
etl_analyst_graph.add_node("tool_node", tool_node)

etl_analyst_graph.add_edge(START, "llm_node")


def is_tool_call(state: EtlAgentSchema):
    tool_calls = state.messages[-1].tool_calls
    if tool_calls:
        return "tool_node"
    return "END"


etl_analyst_graph.add_conditional_edges(
    "llm_node",
    is_tool_call,
    {
        "tool_node": "tool_node",
        "END": END
    }
)

etl_analyst_graph.add_edge("tool_node", "llm_node")

etl_analyst = etl_analyst_graph.compile()


if __name__ == "__main__":
    test_req = {
        "messages": [
            HumanMessage(
                content="Extract weather data from https://api.open-meteo.com/v1/forecast?latitude=43.65&longitude=-79.38&hourly=temperature_2m,precipitation,rain,weather_code and save to data/extract as csv"
            )
        ]
    }
    res = etl_analyst.invoke(test_req)
    print("\n--- ETL Result ---")
    print(res["messages"][-1].content)
import os
import sys
import json
import re
import logging


logging.getLogger("google.genai").setLevel(logging.ERROR)
logging.getLogger("google_genai").setLevel(logging.ERROR)

sys.path.append(
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..")
    )
)


from utils.llm_pick import pick_llm
from utils.etl_tools import ETLTools
from model.schema import EtlAgentSchema
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langchain.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI


#----------------------------------AGENT TOOLS----------------------------------------------------------

@tool
def extract_load_tool(url:str,output_folder:str,output_format:str) ->str:
  """
    This tool extract the data from the API and loads it into the desired location
    
    Args:
      url: The URL of the API from which the data is to be extracted.
      output_folder: The folder path where the extracted data is to be loaded.
      format: The format in which the extracted data is to be loaded.
      
    Returns:
      str: A message indicating the success or failure of the operation
  """
  etl_tools=ETLTools()
  result=etl_tools.extract_load(url,output_folder,output_format)
  return result 


@tool
def transform_load_tool(input_file_path:str,output_folder:str,output_format:str,user_question:str) -> str:
  """
    This tool transform the data and loads it into the desired location
    
    Args:
      file_path: The path of the file from which the data is to be transformed.
      output_folder: The folder path where the transformed data is to be loaded.
      output_format: The format in which the transformed data is to be loaded.
      
    Returns:
      str: A message indicating the success or failure of the operation
  """
  etl_tools=ETLTools()
  top_3_rows=etl_tools.transform_load_context(input_file_path)
  llm=pick_llm("gemini")
  
  prompt = f"""
You are a Python Data Analyst who uses Pandas to analyze data.
You need to provide only the Pandas code that will help to perform the right ETL operations as per the user's question.
Do not provide any explanation or comments, only the code should be provided.
The code should be in a format that can be executed in a Python environment with Pandas installed.
Don't write anything else than Pandas code.

Create the Pandas DataFrame from the data stored in the file: {input_file_path}
and write the code to transform and save the data at {output_folder}.

Here's the user's question: {user_question}\n

Here's the context of the data you will be analyzing: {top_3_rows}\n
"""

  print("Starting Gemini transformation...")
  response = llm.invoke(prompt)
  print("Gemini transformation response received!")

  if isinstance(response.content, str):
      pandas_code = response.content
  else:
      pandas_code = "".join(
          block.get("text", "")
          for block in response.content
          if isinstance(block, dict)
      )

  pandas_code = pandas_code.strip()

  if pandas_code.startswith("```"):
      pandas_code = re.sub(
          r"^```(?:python)?\s*",
          "",
          pandas_code,
          flags=re.IGNORECASE
      )
      pandas_code = re.sub(
          r"\s*```$",
          "",
          pandas_code
      ).strip()

  #execute the code
  print("Starting code execution...")
  results = etl_tools.execute_code(pandas_code)
  print("Code execution finished!")

  return f"The data is transformed and saved at {output_folder} in {output_format} format. \n\n Pandas Code Executed: \n {pandas_code}\n\n Results: \n {results}"


tools=[extract_load_tool,transform_load_tool]

llm=pick_llm("gemini")
llm_bind=llm.bind_tools(tools)


#-------------------------------------------------------AGENT GRAPH-------------------------------------------------------------------------------------

def llm_node(state: EtlAgentSchema):

    messages = state.messages

    prompt = f"""
You are a Python Data Analyst who has access to tools that can extract and load,
transform and load data. You will be provided with a user's question
and you would need to perform the right ETL operations as per the user's question.

If the operation is performed then inform the user and end the conversation.

Here's the chat history:
{messages}
"""

    response = llm_bind.invoke(prompt)

    state.messages = messages + [response]

    return state



def tool_node(state: EtlAgentSchema):

    tools_results = []

    tools_by_name = {
        tool.name: tool
        for tool in tools
    }

    tool_calls = state.messages[-1].tool_calls

    for tool_call in tool_calls:

        tool = tools_by_name[tool_call["name"]]

        observation = tool.invoke(
            tool_call["args"]
        )

        tools_results.append(
            ToolMessage(
                content=str(observation),
                tool_call_id=tool_call["id"]
            )
        )

    state.messages = state.messages + tools_results

    return state

  
  
#------------------------------------------Nodes & Edges--------------------------------------------------------
  
etl_analyst_graph = StateGraph(EtlAgentSchema)

etl_analyst_graph.add_node("llm_node", llm_node)
etl_analyst_graph.add_node("tool_node", tool_node)

etl_analyst_graph.add_edge(START, "llm_node")


def is_tool_call(state: EtlAgentSchema):

    tool_calls = state.messages[-1].tool_calls

    if tool_calls:
        return "tool_node"
    else:
        return "END"


etl_analyst_graph.add_conditional_edges(
    "llm_node",
    is_tool_call,
    {
        "tool_node": "tool_node",   
        "END": END
    }
)

etl_analyst_graph.add_edge(
    "tool_node",
    "llm_node"
)

etl_analyst = etl_analyst_graph.compile()

if __name__ == "__main__":

    from IPython.display import display, Image

    img = Image(
        etl_analyst.get_graph().draw_mermaid_png()
    )

    display(img)

    with open("etl_analyst_graph.png", "wb") as f:
        f.write(img.data)
        
        
    response=etl_analyst.invoke(
      {
        "messages":[
          HumanMessage(content=f"""
            I want to transform the data and stored in the 'D:\\Project\\OLA_AI_DataAgent\\data\\extract\\extracted_data.csv' file
            and save the transformed data in the 'D:\\Project\\OLA_AI_DataAgent\\data\\transform' folder in the csv format.
            The transform should filter the data to show bulbasaur pokemon only
            """
            )
        ]
      }
    )
    
    final_content = response["messages"][-1].content

    if isinstance(final_content, list):
        final_answer = "".join(
            item["text"]
            for item in final_content
            if isinstance(item, dict) and "text" in item
        )
    else:
        final_answer = final_content

    print("\nFinal Answer:")
    print(final_answer)
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
from model.schema import RouterSchema,DataAgentSchema
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langchain.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from agents.etl_analyst import etl_analyst
from agents.sql_analyst import sql_analyst

llm=pick_llm("gemini")
llm_router=llm.with_structured_output(RouterSchema)

#-----------------------DATA AGENT GRAPH---------------------------------------

def router_node(state:DataAgentSchema):
  
  messages=state.messages[-1].content
  
  route_response_dict=llm_router.invoke(messages)
  route_response=route_response_dict.answer
  state.route_response=route_response
  
  return state


def etl_node(state: DataAgentSchema):
  messages=state.messages[-1].content
  
  response=etl_analyst.invoke(
      {
        "messages":[
          HumanMessage(content=f"""
            {messages}
            """
            )
        ]
      }
    )
  state.messages = state.messages + [response]
  
  
def sql_node(state: DataAgentSchema):
  message=state.messages[-1].content
  
  input_schema={
      "messages":[],
      "user_question":f"{message}",
      "curated_ques":"",
      "Prompt_query_context":"",
      "generated_sql_query":"",
      "is_safe":"No",
      "comments":"",
      "sql_query_execution_result":"",
      "final_answer":""
   }
  
  response=sql_analyst.invoke(input_schema)

  state.messages=state.messages+[response]
  
  return state

data_agent_graph=StateGraph(DataAgentSchema)

data_agent_graph.add_node("router_node", router_node)
data_agent_graph.add_node("etl_node", etl_node)
data_agent_graph.add_node("sql_node", sql_node)

data_agent_graph.add_edge(START, "router_node")

def route_edge(state: DataAgentSchema) ->str:
  if state.route_response == "sql":
    return "sql_node"
  elif state.route_response == "etl":
    return "etl_node"
  else:
    raise ValueError(f"Invalid route response {state.route_response}")
  
data_agent_graph.add_conditional_edges(
    "router_node",
    route_edge,
    {
        "sql_node": "sql_node",
        "etl_node": "etl_node"
    }
)

data_agent = data_agent_graph.compile()


    

# ---------------DISPLAY GRAPH  #optional----------------


from IPython.display import display, Image

Img = Image(
      data_agent.get_graph().draw_mermaid_png()
   )

display(Img)

with open("data_agent_graph.png", "wb") as f:
      f.write(Img.data)

print("Graph saved to data_agent_graph.png")

if __name__=="__main__":
  response=data_agent.invoke(
    {"messages":[HumanMessage(content="Give the driver id which get comment as Smooth Ride ") ],
    "route_response": ""
  }
  )
  
  answer = response["messages"][-1]["final_answer"]

  print(answer)
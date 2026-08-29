from agents.data_agent import data_agent

from langchain_core.messages import HumanMessage

# if __name__=="__main__":
#   response=data_agent.invoke(
#     {"messages":[HumanMessage
#               #(content="Give the driver id which get comment as Smooth Ride ") 
#               (content=f"I want to extract the data from the API end point 'https://pokeapi.co/api/v2/pokemon' and save it to data/extract folder as csv format"

#               )],
     
#     "route_response": ""
#   }
#   )
  
#   answer = response["messages"][-1]["final_answer"]

#   print(answer)

if __name__ == "__main__":

    response = data_agent.invoke(
        {
            "messages": [
                HumanMessage(
                    content="I want to extract the data from the API end point 'https://pokeapi.co/api/v2/pokemon' and save it to data/extract folder as csv format"
                )
            ],
            "route_response": ""
        }
    )

    print(response["messages"][-1]["final_answer"])
  


from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()


def pick_llm(level: str):

    if level.lower() == "low":
        llm = ChatGroq(
            model_name="openai/gpt-oss-20b",
            temperature=0
        )

    elif level.lower() == "medium":
        llm = ChatGroq(
            model_name="qwen/qwen3.6-27b",
            temperature=0
        )

    elif level.lower() == "high":
        llm = ChatGroq(
            model_name="openai/gpt-oss-120b",
            temperature=0
        )
        
    elif level.lower()=="gemini":
        llm=ChatGoogleGenerativeAI(
            model="gemini-3.5-flash",  #not support model_name
            temperature=0
        )

    else:
        raise ValueError(f"Unsupported level {level}")

    return llm
  
  
if __name__ == "__main__":
    llm_obj = pick_llm("low")

    response = llm_obj.invoke("What is Python?")

    answer = response.content

    if "<think>" in answer:
        answer = answer.split("</think>")[-1].strip()

    print(answer)
    
    

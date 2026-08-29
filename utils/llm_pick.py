from typing import Any
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()


def get_message_text(content: Any) -> str:
    """
    Safely extracts string content from an LLM response or content property.
    Properly handles strings, LangChain list-of-blocks (dicts/strings), and AIMessage objects.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, str):
                text_parts.append(block)
            elif isinstance(block, dict):
                if "text" in block:
                    text_parts.append(str(block["text"]))
                elif "content" in block:
                    text_parts.append(str(block["content"]))
            elif hasattr(block, "text"):
                text_parts.append(str(block.text))
            elif hasattr(block, "content"):
                text_parts.append(str(block.content))
        return "".join(text_parts).strip()
    if hasattr(content, "content"):
        return get_message_text(content.content)
    return str(content).strip()


def pick_llm(level: str):
    if level.lower() == "low":
        return ChatGroq(
            model_name="openai/gpt-oss-20b",
            temperature=0
        )
    elif level.lower() == "medium":
        return ChatGroq(
            model_name="qwen/qwen3.6-27b",
            temperature=0
        )
    elif level.lower() == "high":
        return ChatGroq(
            model_name="openai/gpt-oss-120b",
            temperature=0
        )
    elif level.lower() == "gemini":
        try:
            return ChatGoogleGenerativeAI(
                model="gemini-3.5-flash",
                temperature=0
            )
        except Exception:
            return ChatGroq(
                model_name="openai/gpt-oss-20b",
                temperature=0
            )
    else:
        raise ValueError(f"Unsupported level {level}")


if __name__ == "__main__":
    llm_obj = pick_llm("low")
    response = llm_obj.invoke("What is Python?")
    answer = get_message_text(response)
    if "<think>" in answer:
        answer = answer.split("</think>")[-1].strip()
    print("Test Answer:", answer[:80])

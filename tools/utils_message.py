from langchain_openai import ChatOpenAI
from config import OPENAI_MODEL, OPENAI_BASE_URL, OPENAI_API_KEY


def get_llm(temperature):
    llm = ChatOpenAI(
        model=OPENAI_MODEL,
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL,
        temperature=temperature
    )
    return llm
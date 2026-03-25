from langchain_openai import ChatOpenAI
from config import OPENAI_MODEL, OPENAI_BASE_URL, OPENAI_API_KEY


def _validate_llm_config():
    # 启动前尽早暴露配置问题，减少运行期隐性报错
    missing = []
    if not OPENAI_MODEL:
        missing.append("OPENAI_MODEL")
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if not OPENAI_BASE_URL:
        missing.append("OPENAI_BASE_URL")
    if missing:
        raise ValueError(f"Missing LLM config: {', '.join(missing)}")


def get_llm(temperature):
    # 调用前先校验配置
    _validate_llm_config()
    llm = ChatOpenAI(
        model=OPENAI_MODEL,
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL,
        temperature=temperature
    )
    return llm

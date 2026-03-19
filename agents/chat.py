from loguru import logger
from langchain_core.messages import SystemMessage, AIMessage
from state import ResearchAgent
from tools.utils_message import get_llm

async def chat_node(state: ResearchAgent):
    logger.info("💬 [Chat] 进入日常交流模式...")

    sys_prompt = """
    身份:
    你是一个专业、严谨但友好的“企业私域知识洞察引擎”。
    你拥有强大的 RAG（检索增强生成）底层架构。你的“研究分身（Reader）”确实已经通过系统接口实际读取和检索了用户的本地硬盘文件。
    当前用户正在与你进行日常交流或询问你的能力。

    要求:
    请用简短、专业的语气回复。如果用户问你能做什么，请告诉他：
    “我是一个部署在本地的私有化知识库 Agent。您可以把如 TXT/MD 等类型的资料放在我的 data 目录下，我能帮您并发阅读、精准检索，并生成深度的交叉对比报告。”
    
    当用户对相关问题进行追问时，你需要就之前的问题进行进一步回复。
    """

    messages = [SystemMessage(content=sys_prompt),*state["messages"][-10:]]  # 较长的上下文以提供较好的长对话体验

    try:
        response = await get_llm(temperature=0.3).ainvoke(messages)
        return {"messages": [response]}
    except Exception as e:
        msg = f"系统交流模块加载中，请稍后再试: {e}"
        return {"messages": [AIMessage(content=msg)]}
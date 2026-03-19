import json
from langchain_core.messages import SystemMessage
from loguru import logger
from state import ResearchAgent
from tools.utils_message import get_llm

SYS_PROMPT = """
    身份:
    你是研究规划师。将用户需求拆解为 2-4 个具体子任务，输出纯 JSON，不要输出其他内容。
    
    要求格式:
    {"tasks": ["子任务1", "子任务2"]}
    """

FALLBACK = ["检索与用户需求相关的核心数据和策略信息"]

async def planner_node(state: ResearchAgent):
    logger.info("🎯 [Planner] 生成检索计划...")
    try:
        response = await get_llm(0.1).ainvoke([SystemMessage(content=SYS_PROMPT), *state["messages"][-4:]])
        tasks = json.loads(response.content)["tasks"]
        if tasks:
            logger.success(f"✅ [Planner] {tasks}")
            return {"tasks": tasks, "research_data": [None]}
    except Exception as e:
        logger.error(f"❌ [Planner] {e}")
    return {"tasks": FALLBACK, "research_data": [None]}
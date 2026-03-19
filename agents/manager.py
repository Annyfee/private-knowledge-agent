from langchain_core.messages import SystemMessage
from loguru import logger
from state import ResearchAgent
from tools.utils_message import get_llm


SYS_PROMPT = """
    身份:
    你是一个意图识别器。请判断用户消息属于哪种意图，按输出格式输出。
    
    规则：
    - 如果用户在打招呼、闲聊、或询问你的能力、你是谁、刚才报告质量如何等无需深度研究的话语 → 输出：chat
    - 如果用户要求分析、总结、对比、查找具体数据或知识等具体需要深度调研的话语 → 输出：research
    
    举例:
    User: 你能做什么;你是谁;你好;今天天气如何;刚才的对话报告质量如何;你觉得这篇报告质量好吗   输出:chat
    User: 帮我深度调研...;针对当前文件进行...的报告;系统分析本地所有文件;                 输出:research
    
    只输出 chat 或 research，不要输出任何其他文字。
    """


async def manager_node(state: ResearchAgent):
    logger.info("🚦 [Manager] 正在进行意图识别...")

    messages = [SystemMessage(content=SYS_PROMPT), *state["messages"][-1:]] # 不要给过多上下文

    try:
        response = await get_llm(temperature=0.0).ainvoke(messages)
        text = response.content.strip().lower()

        # 在返回文本里直接找关键词，不依赖任何格式
        if text == "chat":
            intent = "chat"
        else:
            intent = "research"
        logger.success(f"✅ [Manager] 意图识别完成: {intent} (原始响应: '{text}')")
        return {"intent": intent}

    except Exception as e:
        logger.error(f"❌ [Manager] LLM 调用失败，默认 research: {e}")
        return {"intent": "research"}
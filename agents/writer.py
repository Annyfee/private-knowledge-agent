from loguru import logger
from langchain_core.messages import SystemMessage, HumanMessage
from state import ResearchAgent
from tools.utils_message import get_llm


async def writer_node(state: ResearchAgent):
    logger.info("✍️ [Writer] 正在汇总本地数据并撰写报告...")

    # 取出 Local Reader 收集到的所有本地数据
    collected_data = "\n\n".join(state.get("research_data", []))

    if not collected_data.strip():
        collected_data = "未从本地知识库中提取到有效信息。"

    sys_prompt = f"""
    身份:
    你是一名企业级数据分析师。请基于以下【本地私有数据提取结果】，回答用户的原始提问。

    【本地私有数据提取结果】：
    {collected_data}

    要求：
    1. 必须基于上述提取的数据进行回答，绝不允许编造任何外部数据。
    2. 向用户建议可以加入哪些资料以丰富最终报告。
    3. 使用清晰的 Markdown 结构（标题、加粗、无序列表）排版。

    """
    last_human = [m for m in state["messages"] if isinstance(m,HumanMessage)][-1:]
    messages = [SystemMessage(content=sys_prompt),*last_human] # 只给一个用户提问
    try:
        response = await get_llm(0.3).ainvoke(messages)
        logger.success("✅ [Writer] 报告撰写完成")
        return {"final_answer": response.content, "messages": [response]}
    except Exception as e:
        logger.error(f"❌ [Writer] 撰写失败: {e}")
        msg = f"⚠️ 系统生成报告时发生异常，请重试。错误信息: {str(e)}"
        return {"final_answer": msg}
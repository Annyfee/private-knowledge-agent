from loguru import logger
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, SystemMessage
from state import ReaderState
from tools.registry import load_all_tools
from tools.utils_message import get_llm


async def reader_node(state: ReaderState):
    task = state["task"]
    logger.info(f"📂 [Reader] 正在自主研究子任务: {task}")

    sys_prompt = f"""
    身份:
    你是一个高级的本地知识库研究员。
    当前专属研究任务：{task}

    要求:
    1. 请自主选择并调用工具（search_local_knowledge / list_local_files / read_local_file）来获取数据。
    2. 面对宽泛概念，优先使用 search_local_knowledge 检索核心关键词。
    3. 工具返回的数据中带有来源标签，你在撰写总结时，必须在每条关键数据后严格保留【来源文件名】。
    4. 收集到足够的信息后，请直接输出详实、客观的分析长文。
    
    限制:
    ⚠️ 工具调用次数最多为 3 次。达到 3 次后必须停止调用工具，直接输出最终的纯文本分析报告。
    """
    try:
        tools_list = await load_all_tools()
        if not tools_list:
            logger.error("❌ [Reader] MCP 工具未就绪，无法执行基于知识库的研究任务")  # 工具不可用时显式失败，避免无依据输出“研究结论”
            return {"research_data": [f"【任务结果】 {task}\n知识库检索工具当前不可用，无法生成基于本地资料的可靠结论。"]}
        agent = create_react_agent(get_llm(temperature=0.1), tools=tools_list)
        input_messages = [
            SystemMessage(content=sys_prompt),
            HumanMessage(content="请开始深度调研，给出详尽结论并务必标注来源。")
        ]
        response = await agent.ainvoke({"messages": input_messages}, {"recursion_limit": 15})
        final_result = response["messages"][-1].content
        logger.success(f"✅ [Reader] 任务完成: {task}...")
        return {"research_data": [f"【任务结果: {task}】\n{final_result}"]}
    except Exception as e:
        logger.error(f"❌ [Reader] 执行异常: {e}")
        return {"research_data": [f"【任务结果: {task}】\n研究失败，请检查数据来源或重试。"]}
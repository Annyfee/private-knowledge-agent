# 【搜索员】 负责调用工具并搜索。
from datetime import datetime
from loguru import logger

import openai
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, AIMessage
from langchain_openai import ChatOpenAI

from agents.researcher.state import Researcher
from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from tools.utils_message import clean_msg_for_deepseek



llm = ChatOpenAI(
    model=OPENAI_MODEL,
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
    temperature=0.6
)


async def surfer_node(state:Researcher,tools=None):
    """
    【搜索员】
    职责: 针对单任务 state["task"] 进行搜索
    """
    task = state["task"]
    retry_count = state["retry_count"]
    task_idx = state["task_idx"]

    prefix = f"🏄 [Surfer #{task_idx}]"

    # 快速判断是否有工具返回
    has_search_result = any(isinstance(msg,ToolMessage) for msg in state["messages"])

    stage = "深度抓取" if has_search_result else "广度搜索"

    logger.info(f"{prefix} 启动执行 | 阶段: {stage} | 任务: {task} (重试: {retry_count})")

    sys_prompt = f"""你是一名专业的全网信息采集专家。
        当前任务: "{task}"
        当前时间: {datetime.now().strftime("%Y-%m-%d")}

        ### 🛠️ 你的标准作业程序 (SOP):
        你处于“Map-Reduce”架构的【采集端】。你的唯一目标是**获取高质量的全文数据**。

        请根据当前的【执行状态】灵活选择下一步行动：

        **状态 A: 起步阶段 (无历史搜索结果)**
        - **动作**: 调用 `web_search` 进行广撒网。
        - **策略**: 构造精准的关键词组合，寻找该领域的权威信源。

        **状态 B: 推进阶段 (已有搜索列表)**
        - **动作**: 分析上一步 `web_search` 返回的列表。
        - **决策**: 挑选 1-3 个最匹配、最有深度的 URL（优先选长文、研报、深度解析）。
        - **执行**: 立即调用 `batch_fetch` 或 `get_page_content` 抓取正文。
        - **禁忌**: 不要重复搜索！除非上一步的搜索结果全是垃圾。

        ### ⚠️ 执行严律:
        1. **拒绝废话**: 这是一个自动化接口，严禁输出“好的我来搜”、“根据结果我决定”等思考过程。
        2. **工具优先**: 直接输出 Tool Call。
        3. **目标导向**: 优先获取长文、研报、深度解析。
        """



    for msg in reversed(state["messages"]):
        if isinstance(msg,ToolMessage):
            break

    if retry_count > 0:
        has_search_result = any(
            isinstance(msg,ToolMessage) and msg.name == "web_search"
            for msg in state["messages"]
        )
        if has_search_result:
            advice = f"⚠️ 第 {retry_count} 次重试。上方已有搜索结果，禁止再次调用 web_search，直接从列表中挑选URL调用 batch_fetch。"
        else:
            advice = f"⚠️ 第 {retry_count} 次重试。请更换关键词重新搜索。"

        messages = [SystemMessage(content=sys_prompt)]

        # 找最后一对 AI+Tool 消息，成对携带
        last_pair_start = -1
        for i, msg in enumerate(reversed(state["messages"])):
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                last_pair_start = len(state["messages"]) - 1 - i
                break

        if last_pair_start >= 0:
            messages.extend(state["messages"][last_pair_start:])

        messages.append(HumanMessage(content=f"当前具体任务: {task}\n{advice}"))
    # 首轮搜索时，取六条来判断上下文
    else:
        messages = [
            SystemMessage(content=sys_prompt),
            *state["messages"][-6:],  # 只取最近 4 条，足够判断上下文
            HumanMessage(content=f"当前具体任务: {task}")
        ]

    safe_messages = clean_msg_for_deepseek(messages)


    if not tools:
        logger.error("❌ Surfer 没拿到工具列表")
        return {"messages": [HumanMessage(content="系统错误：工具未加载")]}

    try:
        response = await llm.bind_tools(tools).ainvoke(safe_messages)

        # 打印它的行为逻辑
        if response.tool_calls:
            tools_name = ",".join([t['name'] for t in response.tool_calls])
            logger.success(f"🤖 {prefix} 决策: 调用 {tools_name}")
        else:
            logger.warning(f"🤔 {prefix} 思考中(无工具调用)")


        return {"messages":[response]}
    # AI的api可能会拒绝生成内容，需要做防护
    except openai.BadRequestError as e:
        # 捕获 llm 的内容风控错误
        err_dict = e.body or {}
        err_str = str(err_dict)
        if "Content Exists Risk" in str(err_dict) or "DataInspectionFailed" in err_str:
            logger.error(f"🚫 {prefix} 触发内容风控，强制跳过当前轮次。")
            # 返回一个由 Human 构造的 System 提示，假装这一步失败了，让 Leader 决定是否重试
            return {"messages": [AIMessage(content="⚠️ [安全拦截] 该话题涉及敏感内容，无法继续执行检索。")]}
        else:
            logger.error(f"❌ {prefix} API 请求错误: {e}")
            return {"messages": [AIMessage(content=f"[FATAL_ERROR] 发生致命错误: {str(e)}，强制结束搜索。")]}

    except Exception as e:
        logger.error(f"❌ {prefix} 未知错误: {e}")
        return {"messages": [AIMessage(content=f"[FATAL_ERROR] 发生致命错误: {str(e)}，强制结束搜索。")]}

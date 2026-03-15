# 【资料员】 整理数据:清洗数据并将其整理入库 core -> lead
import re
from loguru import logger

from langchain_core.messages import ToolMessage, HumanMessage, AIMessage
from agents.researcher.state import Researcher

from tools.registry import global_rag_store




async def core_node(state:Researcher):
    """
    针对获取的数据，将其整理并入库，并返回给LLM已入库的信息
    """

    task_idx = state["task_idx"]
    messages = state["messages"]
    last_msg = messages[-1]

    prefix = f"🧹 [Core #{task_idx}]"

    # 确定返回数据是源自获取全文内容的工具
    source_url = "未知来源"
    if isinstance(last_msg,ToolMessage) and last_msg.name in ["get_page_content","batch_fetch"]:

        logger.info(f"{prefix} 拦截到长文本 ({last_msg.name}) | 正在清洗入库...")

        target_id = last_msg.tool_call_id
        # 找AI的原始指令，获取source_url
        for msg in reversed(messages):
            if hasattr(msg,"tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc["id"] == target_id:
                        args = tc["args"]
                        source_url = str(args.get("urls") or args.get("url"))
                        break

        # 数据清洗
        raw_content = str(last_msg.content)

        cleaned = re.sub(r"!\[.*?\]\(.*?\)","",raw_content) # 去掉![]()的图片格式
        noise_keywords = ["版权所有", "©", "备案", "110报警", "营业执照", "免责声明", "出版物许可证"] # 去掉噪音
        filtered_lines = []
        for line in cleaned.split("\n"):
            keep = True
            for noise_keyword in noise_keywords:
                if noise_keyword in line:
                    keep = False
                    break
            if keep:
                filtered_lines.append(line)
        final_text = "\n".join(filtered_lines)


        if len(final_text) > 200: # 字数必须200+才记录
            # 物理入库
            global_rag_store.add_documents(final_text, source_url,session_id=state.get("session_id","default_session"))
            # 构造简单通知以返回
            new_msg = ToolMessage(
                content="✅ [系统] 内容已存入 RAG。由于原文过长，已在当前上下文中物理删除，请调用检索工具。",
                tool_call_id=target_id,
                name=last_msg.name,
                id=last_msg.id
            )
            # 后面的graph根据cur_task_idx判断，如果没有变化，就正常返还给surfer做进一步搜索
            return {
                "messages":[new_msg],
                "next_node":"leader",
            }
        else:
            new_msg = ToolMessage(
                content=f"❌ [无效数据] 内容过短 ({len(final_text)}字)，已丢弃。可能是反爬虫或无效页面。",
                tool_call_id=target_id,
                name=last_msg.name,
                id=last_msg.id
            )
            return {
                "messages": [new_msg],
                "next_node": "leader",
            }

    # 对来自surfer的报警强制拦截并交给Leader
    if isinstance(last_msg,AIMessage) and "[FATAL_ERROR]" in str(last_msg.content):
        logger.error(f"{prefix} 接收到致命错误信号，强制熔断至 Leader。")
        return {
            "next_node":"leader"
        }

    # 非全文内容正常返回，不做拦截
    return {
        "next_node":"leader"
    }
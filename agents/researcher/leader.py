# 【导演】 路由:闭环控制与反思 - 看生成数量与质量是否足够，不够继续寻找，够了输出 leader -> writer/surfer
from loguru import logger

from langchain_core.messages import ToolMessage
from agents.researcher.state import Researcher




async def leader_node(state:Researcher):
    """
    【小组长】
    职责：检查结果，并在 state 里写下明确的 next_node
    """
    messages = state["messages"]
    last_msg = messages[-1]
    cur_retry = state.get("retry_count", 0)
    task_idx = state["task_idx"]

    prefix = f"👩‍✈️ [Leader #{task_idx}]"


    # 1. 检查是否成功 (Core 发出了 ✅)
    if isinstance(last_msg, ToolMessage) and "✅" in last_msg.content:
        logger.info(f"{prefix}🏁 任务完成 | 获得有效数据")
        return {
            "next_node": "end"  # 明确指令：结束
        }

    # 2. 检查是否超限
    if cur_retry >= 3:
        logger.error(f"{prefix} 🛑 尝试 {cur_retry} 次均失败，强制放弃。")
        return {
            "next_node": "end"  # 明确指令：结束
        }

    # 3. 决定重试
    logger.warning(f"{prefix} 🔄 数据无效 (收到 ❌)，要求 Surfer 换词重搜 (第 {cur_retry + 1} 次)")
    return {
        "retry_count": cur_retry + 1,
        "next_node": "surfer"  # 明确指令：回 Surfer
    }
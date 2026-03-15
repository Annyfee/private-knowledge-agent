# 注:LangChain会将ToolMessage调整为list类型，但部分llm(如deepseek)只能接收str。所以我们需要中间件来处理
import json
from langchain_core.messages import ToolMessage


def clean_msg_for_deepseek(messages):
    """
    专门为DeepSeek清洗消息格式的中间件
    将所有List类型的ToolMessage content 转化为 JSON String
    """
    cleaned = []
    for msg in messages:
        if isinstance(msg,ToolMessage) and isinstance(msg.content,list):
            # 直接序列化为JSON类型
            msg_copy = ToolMessage(
                content=json.dumps(msg.content,ensure_ascii=False),
                tool_call_id=msg.tool_call_id,
                name=msg.name,
                id=msg.id
            )
            cleaned.append(msg_copy)
        else:
            cleaned.append(msg)
    return cleaned


def slice_messages(messages):
    """
    完全过滤工具相关信息（AI 的 tool_calls + ToolMessage）
    用于 chat/planner 等不需要工具信息的场景

    (信息列表中的ToolMessage与tool_call_id必须连在一块，单独摘一个会报错--比如直接切state["messages"][-8]。所以要么直接去掉工具信息(本函数)，要么完整保留工具调用不切片)
    """
    return [
        msg for msg in messages
        if not isinstance(msg, ToolMessage)
        and not (hasattr(msg, 'tool_calls') and msg.tool_calls)
    ]
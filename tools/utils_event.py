# 把langgraph的原始事件流，统一清洗成前端可消费的标准事件格式，并且过滤掉不该展示的内容
def parse_langgraph_event(event):
    """
    输入:langgraph的原始event
    输出:清洗好的标准数据
    返回 None:无需处理
    """
    kind = event["event"]
    meta = event.get("metadata",{}) or {} # 防止键不存在或为空
    node = meta.get("langgraph_node") # 标记事件来源节点

    # LLM吐字-token流式:仅允许chat与writer两个节点吐字
    if  kind == "on_chat_model_stream":
        if node not in ("chat", "writer"):
            return None
        chunk = event.get("data", {}).get("chunk")
        content = getattr(chunk, "content", "")
        if content is None:
            return None
        if isinstance(content, list):
            # 兼容富文本/分片结构
            content = "".join(
                c if isinstance(c, str) else str(c.get("text", "")) if isinstance(c, dict) else str(c)
                for c in content
            )
        elif not isinstance(content, str):
            content = str(content)
        if not content.strip():
            return None
        return {"type": "token", "content": content, "source": node}
    # 工具调用
    elif kind == "on_tool_start":
        tool_name = event.get("name", "")
        raw_input = event.get("data", {}).get("input", {})
        if isinstance(raw_input, dict):
            safe_input = {}
            for k, v in raw_input.items():
                if k not in ("runtime", "callbacks", "config"):
                    safe_input[k] = v
        else:
            # 非 dict 输入兜底
            safe_input = {"value": raw_input}
        return {
            "type": "tool_start",
            "tool": tool_name,
            "input": safe_input,
            "source": node,
        }
    # 调用结束
    elif kind == "on_tool_end":
        tool_name = event["name"]
        if not tool_name.startswith("_"):
            output = str(event["data"]["output"])
            return {
                "type":"tool_end",
                "tool":tool_name,
                "output":output[:200] + "..." if len(output) > 200 else output,
                "source":node
            }
    # 节点执行完成后触发 / 因为所有节点都在token输出，这里不用管
    elif kind == "on_chain_end":
        pass
    return None
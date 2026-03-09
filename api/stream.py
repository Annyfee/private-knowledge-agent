import asyncio
import json
import uuid
import time
from loguru import logger


# 全局并发限制
MAX_CONCURRENT_USERS = asyncio.Semaphore(5)
GRAPH_RUN_TIMEOUT_SEC = 240

def _to_phase_from_source(source:str):
    """把LangGraph的节点名，映射成前端UI阶段名"""
    if source == "planner":
        return "planning"
    if source in ("researcher","leader","surfer"):
        return "researching"
    if source == "writer":
        return "writing"
    return None

# 统一事件封装函数
def make_event(event_type:str,run_id:str,sid:str,**payload):
    """统一构造成发给前端的事件对象"""
    return{
        "type":event_type,
        "protocol_version":"v1",
        "ts":int(time.time()*1000),
        "run_id":run_id, # 运行实例id
        "session_id":sid,
        **payload
    }

def _phase_event(node:str,fsm_state:dict,run_id:str,sid:str):
    """判断这次事件是否是 阶段切换 """
    phase = _to_phase_from_source(node)
    # 根据来源事件，自动判断并切换到对应的阶段 - phase自动推进并变化
    if not phase or phase == fsm_state["phase"]:
        return None
    fsm_state["phase"] = phase
    return make_event("phase", run_id, sid, phase=phase, source=node)


def _extract_text_content(event:dict):
    """从LangGraph里的stream事件里，提取出真正能展示的文本"""
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
    return content

def _sanitize_tool_input(event:dict):
    """清洗工具调用下的无关参数(源于框架内部)"""
    raw_input = event.get("data", {}).get("input", {})
    if isinstance(raw_input, dict):
        safe_input = {}
        for k, v in raw_input.items():
            if k not in ("runtime", "callbacks", "config"):
                safe_input[k] = v
        return safe_input
    # 非dict下兜底
    return {"value":raw_input}

def _transform_event(event:dict,fsm_state:dict,run_id:str,sid:str):
    """把一个LangGraph原始事件，转换成多个UI事件"""
    kind = event.get("event")
    meta = event.get("metadata")
    node = meta.get("langgraph_node")
    out = []

    phase_event = _phase_event(node,fsm_state,run_id,sid)
    if phase_event:
        out.append(phase_event)
    # 流式
    if kind == "on_chat_model_stream":
        if node not in ("chat", "writer"):
            return out
        content = _extract_text_content(event)
        if content:
            out.append(make_event("token",run_id,sid,content=content))
        return out
    # 工具调用
    elif kind == "on_tool_start":
        tool_name = event.get("name", "")
        safe_input = _sanitize_tool_input(event)
        out.append(make_event(
            "tool_start",run_id,sid,
            source=node,
            tool=tool_name,
            input=safe_input
        ))
        return out
    # 事件节点结束，希望捕获某个节点的信息
    elif kind == "on_chain_end" and node == "planner":
        output = event.get("data").get("output")
        tasks = []
        if isinstance(output,dict):
            tasks = output.get("tasks", [])
        if tasks:
            # 发送任务列表
            out.append(make_event("tasks",run_id,sid,tasks=tasks))
    return out

# 流式输出
async def event_generator(graph,inputs:dict,config:dict,sid:str):
    """
    翻译层 | 将LangGraph事件转换为SSE数据流
    """
    # 限制最大并发数
    async with MAX_CONCURRENT_USERS:
        run_id = str(uuid.uuid4())
        try:
            fsm_state = {"phase": None}
            async with asyncio.timeout(GRAPH_RUN_TIMEOUT_SEC):
                # 启动Graph流式执行 - 这里只负责丢数据，展示什么数据(如on_tool_start)由前端来管
                async for event in graph.astream_events(inputs,config,version="v2"):# 产出原始事件
                    ui_events = _transform_event(event,fsm_state,run_id,sid)
                    for data in ui_events:
                        # 返回SSE协议格式数据
                        yield f"data: {json.dumps(data,ensure_ascii=False)}\n\n"
        except TimeoutError:
            err_str = f"⏰ 本次研究超时（>{GRAPH_RUN_TIMEOUT_SEC}s），请缩小问题范围或稍后重试。"
            logger.warning(f"Graph run timeout | sid={sid} run_id={run_id}")
            error_data = make_event("error", run_id, sid, source="system", content=err_str)
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
        except Exception as e:
            err_str = str(e)
            # 如果是风控导致的后续崩溃，直接返回用户
            if "Content Exists Risk" in err_str or "No AIMessage found" in err_str:
                err_str = "⚠️ 系统安全策略拦截：该话题无法继续研究。"
            logger.exception("❌ 运行出错")
            error_data = make_event("error",run_id,sid,source="system",content=err_str)
            yield f"data: {json.dumps(error_data,ensure_ascii=False)}\n\n"
        finally:
            done = make_event("done",run_id,sid)
            yield f"data: {json.dumps(done,ensure_ascii=False)}\n\n"
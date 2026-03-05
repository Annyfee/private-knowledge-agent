import asyncio
import json
import re
import uuid
import time
from loguru import logger
from tools.utils_event import parse_langgraph_event


# 全局并发限制
MAX_CONCURRENT_USERS = asyncio.Semaphore(5)
GRAPH_RUN_TIMEOUT_SEC = 240

def _to_phase_from_source(source:str):
    if source in ("manager","planner"):
        return "planning"
    if source in ("researcher","leader","surfer"):
        return "researching"
    if source == "writer":
        return "writing"
    return None

# 统一事件封装函数
def make_event(event_type:str,run_id:str,sid:str,**payload):
    return{
        "type":event_type,
        "protocol_version":"v1",
        "ts":int(time.time()*1000),
        "run_id":run_id, # 运行实例id
        "session_id":sid,
        **payload
    }


def adapt_event_for_ui(data:dict,fsm_state:dict,run_id:str,sid:str):
    """
    输入 parse_langgraph_event的结果，输出 0-n 个统一UI事件
    只允许输出协议事件，禁止透传原始data
    """
    if not data:
        return [] # 无UI事件
    out = [] # 收集UI
    source = data.get("source","unknown")
    t = data.get("type", "unknown")
    text = data.get("content","")
    phase = _to_phase_from_source(source)
    # 根据来源事件，自动判断并切换到对应的阶段 - phase自动推进并变化
    if phase and phase != fsm_state["phase"]:
        fsm_state["phase"] = phase
        out.append(make_event("phase", run_id, sid, phase=phase, source=source)) # 更新状态
    if t == "token":
        out.append(make_event("token",run_id,sid,source=source,content=text))
        return out
    if t == "message":
        out.append(make_event("message",run_id,sid,source=source,content=text))
        return out
    if t == "tool_start":
        out.append(make_event(
            "tool_start",run_id,sid,
            source=source,
            tool=data.get("tool",""),
            input=data.get("input",{})
        ))
        return out
    if t == "tool_end":
        out.append(make_event(
            "tool_end",run_id,sid,
            source=source,
            tool=data.get("tool",""),
            output=data.get("output",{}) # 注意区分:input & output
        ))
        return out
    if t == "error":
        out.append(make_event(
            "error",run_id,sid,
            source=source,
            content=text or "未知错误"
        ))
        return out
    # 未知事件统一转status，不透传
    out.append(make_event(
        "status",run_id,sid,
        source=source,
        content=text or f'{t}'
    ))
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
                    data = parse_langgraph_event(event)
                    ui_events = adapt_event_for_ui(data,fsm_state,run_id,sid)
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
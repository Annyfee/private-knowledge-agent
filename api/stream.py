import asyncio
import json
import uuid
import time
from loguru import logger

GRAPH_RUN_TIMEOUT_SEC = 240


def _to_phase_from_source(source: str):
    if source == "planner": return "planning"
    if source == "reader": return "researching"
    if source == "writer": return "writing"
    return None


def make_event(event_type: str, run_id: str, sid: str, **payload):
    return {
        "type": event_type, "protocol_version": "v1",
        "ts": int(time.time() * 1000), "run_id": run_id,
        "session_id": sid, **payload
    }


def _phase_event(node: str, fsm_state: dict, run_id: str, sid: str):
    phase = _to_phase_from_source(node)
    if not phase or phase == fsm_state["phase"]: return None
    fsm_state["phase"] = phase
    return make_event("phase", run_id, sid, phase=phase, source=node)


def _extract_text_content(event: dict):
    chunk = event.get("data", {}).get("chunk")
    content = getattr(chunk, "content", "")
    if content is None: return None
    if isinstance(content, list):
        content = "".join(
            c if isinstance(c, str) else str(c.get("text", "")) if isinstance(c, dict) else str(c) for c in content)
    elif not isinstance(content, str):
        content = str(content)
    if not content.strip(): return None
    return content


def _sanitize_tool_input(event: dict):
    raw_input = event.get("data", {}).get("input", {})
    if isinstance(raw_input, dict):
        return {k: v for k, v in raw_input.items() if k not in ("runtime", "callbacks", "config")}
    return {"value": raw_input}


def _transform_event(event: dict, fsm_state: dict, run_id: str, sid: str):
    kind = event.get("event")
    meta = event.get("metadata") or {}
    node = meta.get("langgraph_node", "")
    out = []

    phase_event = _phase_event(node, fsm_state, run_id, sid)
    if phase_event: out.append(phase_event)

    if kind == "on_chat_model_stream":
        if node not in ("chat", "writer"): return out
        content = _extract_text_content(event)
        if content: out.append(make_event("token", run_id, sid, content=content))

    elif kind == "on_tool_start":
        safe_input = _sanitize_tool_input(event)
        out.append(make_event("tool_start", run_id, sid, source=node, tool=event.get("name", ""), input=safe_input))

    elif kind == "on_chain_end":
        output = event.get("data", {}).get("output")
        if node in ("planner", "reader", "writer") and isinstance(output, dict):
            messages = output.get("messages", [])
            if messages:
                content = getattr(messages[-1], "content", "")
                if content and ("发生异常" in content or "执行时发生异常" in content) and "错误信息" in content:
                    out.append(make_event("error", run_id, sid, content=content, source=node))

        if node == "planner" and isinstance(output, dict):
            tasks = output.get("tasks", [])
            if tasks: out.append(make_event("tasks", run_id, sid, tasks=tasks))
    return out


async def event_generator(graph, inputs: dict, config: dict, sid: str):
    run_id = str(uuid.uuid4())
    try:
        fsm_state = {"phase": None}
        async with asyncio.timeout(GRAPH_RUN_TIMEOUT_SEC):
            async for event in graph.astream_events(inputs, config, version="v2"):
                ui_events = _transform_event(event, fsm_state, run_id, sid)
                for data in ui_events:
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
    except TimeoutError:
        error_data = make_event("error", run_id, sid, source="system", content="⏰ 超时处理...")
        logger.warning(f"⏰ 图结构运行超时")
        yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
    except Exception as e:
        logger.error(f"⚠️ 未知报错 {e}")
        error_data = make_event("error", run_id, sid, source="system", content=str(e))
        yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
    finally:
        yield f"data: {json.dumps(make_event('done', run_id, sid), ensure_ascii=False)}\n\n"
import uuid
from fastapi import APIRouter, Request
from langchain_core.messages import HumanMessage
from loguru import logger
from pydantic import BaseModel
from starlette.responses import StreamingResponse
from api.stream import event_generator
from tools.registry import SERVICE_STATUS, load_all_tools

class ChatRequest(BaseModel):
    message: str
    session_id: str = None

router = APIRouter()

@router.post("/chat")
async def chat_endpoint(payload: ChatRequest, request: Request):
    sid = payload.session_id or str(uuid.uuid4())
    logger.info(f"⚡ 收到单机请求 | Session: {sid}")

    config = {"configurable": {"thread_id": sid}, "recursion_limit": 100}
    inputs = {"messages": [HumanMessage(content=payload.message)], "session_id": sid}
    graph = request.app.state.graph

    return StreamingResponse(
        event_generator(graph, inputs, config, sid),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@router.get("/service/status")
async def service_status():
    if not SERVICE_STATUS.get("mcp_online"):
        try:
            logger.info("🔄 前端请求刷新状态，主动尝试重连 MCP...")
            await load_all_tools()
        except Exception:
            pass
    return SERVICE_STATUS
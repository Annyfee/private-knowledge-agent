import time
import uuid
from collections import defaultdict
from fastapi import APIRouter,Request
from langchain_core.messages import HumanMessage
from loguru import logger
from pydantic import BaseModel
from starlette.responses import JSONResponse, StreamingResponse
from api.stream import event_generator
from tools.registry import SERVICE_STATUS

class ChatRequest(BaseModel):
    message:str
    session_id:str = None


# 限流存储（内存级别，重启清零，够用） - 不存在key 自动创建空list
request_counts = defaultdict(list)

# 挂载路由
router = APIRouter()
# 聊天接口
@router.post("/chat") # 前者取参数，后者取上下文
async def chat_endpoint(payload:ChatRequest,request:Request): # 其中payload与message都是从前端的请求体接收的，这里无需做显式接收，但可使用
    # 获取session_id
    sid = payload.session_id or str(uuid.uuid4())
    logger.info(f"收到请求 | Session: {sid}")

    # 限流检查
    now = time.time()
    request_counts[sid] = [t for t in request_counts[sid] if now - t < 3600]  # 清理一小时前的记录
    if len(request_counts[sid]) >= 6: # 超过六次拒绝
        logger.warning(f"🚫 限流触发 | Session: {sid}")
        return JSONResponse(
            status_code=429,
            content={"detail":"每小时最多访问6次，请稍后再试!"}
        )
    request_counts[sid].append(now)


    # 构造config(为数据库指明会话)
    config = {
        "configurable":{"thread_id":sid},
        "recursion_limit":100
    }
    # 构造Input(为RAG指明用户)
    inputs = {
        "messages":[HumanMessage(content=payload.message)],
        "session_id":sid
    }
    graph = request.app.state.graph
    # 返回流式响应
    return StreamingResponse(
        event_generator(graph,inputs, config,sid),
        media_type="text/event-stream", # SSE流
        # 减少中间件缓冲
        headers={
            "Cache-Control": "no-cache", # 不要缓存流
            "Connection": "keep-alive", # 保持长连接
            "X-Accel-Buffering": "no", # 不要缓冲
        },
    )

@router.get("/service/status")
async def service_status():
    return SERVICE_STATUS
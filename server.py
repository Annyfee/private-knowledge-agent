import logging
import os
from fastapi import FastAPI
from loguru import logger
from starlette.middleware.cors import CORSMiddleware
from api.routes import router
from bootstrap.lifespan import lifespan
from config import LANGCHAIN_API_KEY


if LANGCHAIN_API_KEY:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = "private-knowledge-agent"
    os.environ["LANGCHAIN_API_KEY"] = LANGCHAIN_API_KEY
else:
    logger.warning("⚠️ 未配置 LANGCHAIN_API_KEY，LangSmith 追踪已禁用")

# --- 消音代码 --- 等级低于Warning的提示全部屏蔽
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("chromadb").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)
# -----------------------

# 文件夹不存在，则创建
for path in ["logs", "db"]:
    os.makedirs(path, exist_ok=True)

# 创建日志
logger.add("logs/server.log", rotation="10 MB")

# 初始化FastAPI
app = FastAPI(title="Deep Research Agent API", lifespan=lifespan)

# 插入中间件，对请求域名做检测
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# 挂载路由
app.include_router(router)

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8011)
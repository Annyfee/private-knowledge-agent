import asyncio
import os
from langchain_mcp_adapters.client import MultiServerMCPClient
from loguru import logger

SERVICE_STATUS = {
    "backend_online": True,
    "mcp_online": False
}

GLOBAL_MCP_CLIENT = None # 全局复用单个客户端实例
GLOBAL_TOOLS = [] # 全局工具缓存

# 协程锁
_LOAD_LOCK = asyncio.Lock()


async def load_all_tools():
    """初始化并返回所有可用工具列表 (带单例缓存 + 并发安全锁)"""
    global GLOBAL_MCP_CLIENT, GLOBAL_TOOLS

    # 快速路径：已缓存直接返回，不进锁
    if GLOBAL_TOOLS:
        return GLOBAL_TOOLS

    # 并发高峰，只允许一个协程能进入
    async with _LOAD_LOCK:
        # double-check：拿到锁后再判断一次，防止锁等待期间其他协程已完成初始化
        if GLOBAL_TOOLS:
            return GLOBAL_TOOLS

        mcp_host = os.getenv("MCP_HOST", "127.0.0.1")
        mcp_url = f"http://{mcp_host}:8003/mcp"

        mcp_config = {
            "本地私有检索服务": {
                "transport": "http",
                "url": mcp_url,
            }
        }

        logger.info("🔌 正在初始化 MCP 服务器全局连接...")
        try:
            GLOBAL_MCP_CLIENT = MultiServerMCPClient(mcp_config)
            mcp_tools = await GLOBAL_MCP_CLIENT.get_tools()
            logger.success(f"✅ MCP 工具全局加载成功: {[t.name for t in mcp_tools]}")

            SERVICE_STATUS["mcp_online"] = True
            GLOBAL_TOOLS = mcp_tools

        except Exception as e:
            logger.error(f"❌ MCP 全局连接失败: {e}")
            GLOBAL_TOOLS = []
            SERVICE_STATUS["mcp_online"] = False

    return GLOBAL_TOOLS
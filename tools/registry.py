import os

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from loguru import logger


from tools.rag_store import RAGStore

global_rag_store = RAGStore()

# 全局服务状态
SERVICE_STATUS = {
    "backend_online":True,
    "mcp_online":False
}


# 定义 RAG 检索工具 (给 Agent 查库用)
@tool
def search_knowledge_base(query: str,config:RunnableConfig): # 声明使用RunnableConfig来提取我们最初定义的thread_id
    """
    当系统提示'资料已存入知识库'时，或者需要回答基于事实的问题时，
    必须调用此工具从本地知识库(RAG)中检索。
    """
    session_id = config.get("configurable",{}).get("thread_id","default_session")
    logger.info(f"📚 Agent 正在查询知识库: {query} | Session_ID: {session_id}")
    return global_rag_store.query_formatted(query,session_id)

# 加载所有工具
async def load_all_tools():
    """
    初始化并返回所有可用工具列表(MCP+RAG)
    """
    # 动态地址获取 docker环境会自动注入MCP_HOST
    mcp_host = os.getenv("MCP_HOST","127.0.0.1") #
    mcp_url = f"http://{mcp_host}:8003/mcp"

    mcp_config = {
        "搜索服务": {
            "transport": "http",
            "url": mcp_url,
        }
    }
    logger.info("🔌 正在连接 MCP 服务器...")
    try:
        client = MultiServerMCPClient(mcp_config)
        mcp_tools = await client.get_tools()
        logger.success(f"✅ MCP 工具加载成功: {[t.name for t in mcp_tools]}")
        # 记录成功状态
        SERVICE_STATUS["mcp_online"] = True
    except Exception as e:
        logger.error(f"❌ MCP 连接失败: {e}")
        mcp_tools = []
        # 记录失败状态
        SERVICE_STATUS["mcp_online"] = False
    return mcp_tools + [search_knowledge_base]
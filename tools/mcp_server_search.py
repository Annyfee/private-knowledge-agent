import re
import httpx
from mcp.server.fastmcp import FastMCP
import asyncio
from loguru import logger
from mcp.server.transport_security import TransportSecuritySettings
from config import TAVILY_API_KEY


SINGLE_FETCH_TIMEOUT_SEC = 25 # 单URL超时
BATCH_FETCH_TIMEOUT_SEC = 90 # 批量总超时
MAX_BATCH_CONCURRENCY = 3 # 批量并发上限

mcp = FastMCP(
    "SearchService",
    host="0.0.0.0",   # 必须：让容器可访问宿主机上的 8003
    port=8003,
    streamable_http_path="/mcp", # mcp HTTP入口
    json_response=True, # 返回JSON格式响应
    stateless_http=True, # 无状态HTTP，每个请求独立，不依赖会话状态
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,  # 关闭保护
        allowed_hosts=["*"],  # 允许所有 Host
        allowed_origins=["*"],  # 允许所有 Origin
    )
)

@mcp.tool()
async def web_search(query: str):
    """
    使用搜索关键词进行全网搜索，返回最多 15 条结果摘要。
    参数:
    - query: 必填，非空字符串。表示搜索关键词或搜索短句。
    要求:
    - 禁止省略 query
    - 禁止传空字符串
    """
    try:
        logger.info(f'🔍 [Async/Tavily] 正在搜索: {query}')
        api_key = TAVILY_API_KEY
        if not api_key:
            return "Error: 搜索服务未配置 TAVILY_API_KEY 环境变量"

        # 并发爬取
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "advanced", # 深度爬取
                    "max_results": 15
                },
                timeout=SINGLE_FETCH_TIMEOUT_SEC
            )
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                return "未找到相关结果，请尝试更换关键词。"

            search_results = []
            for i, r in enumerate(results):
                content = f"结果 [{i}]\n标题: {r.get('title')}\n链接: {r.get('url')}\n摘要: {r.get('content')}\n"
                search_results.append(content)

            return "\n---\n".join(search_results)

    except httpx.TimeoutException:
        logger.error(f"搜索请求超时: {query}")
        return '搜索服务暂时不可用: 请求超时'
    except Exception as e:
        logger.error(f"搜索服务出错: {e}")
        return f'搜索服务暂时不可用: {str(e)}'


@mcp.tool()
async def get_page_content(url: str):
    """
    获取单个url里的全文信息
    """
    logger.info(f'⚡ [Async/Jina] 正在抓取: {url}')

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://r.jina.ai/{url}",
                timeout=SINGLE_FETCH_TIMEOUT_SEC
            )
            response.raise_for_status()
            raw_response = response.text

            if not raw_response:
                return "Error: 提取正文内容为空"

            # 剔除 Markdown 中的超长 Base64 图片数据或无效的图片占位符
            dehydrated_text = re.sub(r'!\[.*?\]\(data:image/.*?\)', '[图片已脱水]', raw_response)
            dehydrated_text = re.sub(r'!\[.*?\]\([^)]+\.(jpg|png|gif|svg)\)', '[图片已移除]', dehydrated_text)

            return dehydrated_text

    except httpx.TimeoutException:
        logger.warning(f"⏰ 单URL抓取超时: {url}")
        return f"Error: 抓取超时（>{SINGLE_FETCH_TIMEOUT_SEC}s）: {url}"
    except httpx.HTTPStatusError as e:
        return f"Error: 目标网站拒绝访问或不存在 (HTTP {e.response.status_code})"
    except Exception as e:
        return f"Error: 抓取时发生未知错误:{str(e)}"


@mcp.tool()
async def batch_fetch(urls: list[str]):
    """
    批量获取url里的全文信息(并行)
    如果是批量获取，优先使用该工具
    """
    logger.info(f'正在批量获取{len(urls)}个URL的全文信息...')
    sem = asyncio.Semaphore(MAX_BATCH_CONCURRENCY)

    async def fetch_one(url: str):
        async with sem:
            # 复用异步 get_page_content
            return await get_page_content(url)
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*(fetch_one(url) for url in urls)),
            timeout=BATCH_FETCH_TIMEOUT_SEC
        )
    except asyncio.TimeoutError:
        return "Error: 批量抓取总时长超时，请减少URL数量后重试。"

    return "\n\n=== 文章分隔线 ===\n\n".join(results)


if __name__ == '__main__':
    mcp.run("streamable-http")
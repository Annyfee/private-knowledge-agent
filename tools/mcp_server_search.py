from mcp.server.fastmcp import FastMCP

import asyncio
from loguru import logger

from ddgs import DDGS
import trafilatura
from mcp.server.transport_security import TransportSecuritySettings

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


SINGLE_FETCH_TIMEOUT_SEC = 25 # 单URL超时
BATCH_FETCH_TIMEOUT_SEC = 90 # 批量总超时
MAX_BATCH_CONCURRENCY = 3 # 批量并发上限



@mcp.tool()
async def web_search(query:str):
    """
    使用搜索关键词进行全网搜索，返回最多 15 条结果摘要。
    参数:
    - query: 必填，非空字符串。表示搜索关键词或搜索短句。
    要求:
    - 禁止省略 query
    - 禁止传空字符串
    """
    try:
        logger.info(f'🔍 [Async] 正在搜索: {query}')
        # 确保时效性:最近一个月 | 后续更新可以自由选择需要的时间段

        # 【核心逻辑】使用同步的 DDGS，但用 to_thread 包装成异步
        # 理由：DDGS 官方库变动频繁，AsyncDDGS 可能不存在，而 to_thread 是 Python 标准库，永远稳定。
        def _sync_search():
            # max_results 建议 10-15
            # timelimit="y" (过去一年)
            return list(DDGS().text(query, max_results=15, timelimit="y"))

        # 扔到线程池跑，不阻塞主线程
        results = await asyncio.to_thread(_sync_search)

        if not results:
            return "未找到相关结果，请尝试更换关键词。"

        search_results = []
        for i,r in enumerate(results):
            content = f"结果 [{i}]\n标题: {r['title']}\n链接: {r['href']}\n摘要: {r['body']}\n"
            search_results.append(content)
        return "\n---\n".join(search_results)
    except Exception as e:
        logger.error(f"搜索服务出错: {e}")
        return f'搜索服务暂时不可用: {str(e)}'


@mcp.tool()
async def get_page_content(url: str):
    """
    获取单个url里的全文信息
    """
    logger.info(f'⚡ [Async] 正在抓取: {url}')

    def _fetch():
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return "Error: 无法访问该页面"
        result = trafilatura.extract(downloaded)
        return result or "Error: 无法提取正文内容"

    try:
        # 单URL超时兜底
        return await asyncio.wait_for(
            asyncio.to_thread(_fetch),
            timeout=SINGLE_FETCH_TIMEOUT_SEC
        )
    except asyncio.TimeoutError:
        logger.warning(f"⏰ 单URL抓取超时: {url}")
        return f"Error: 抓取超时（>{SINGLE_FETCH_TIMEOUT_SEC}s）: {url}"
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
    async def fetch_one(url:str):
        async with sem:
            try:
                return await asyncio.wait_for(
                    get_page_content(url),
                    timeout=SINGLE_FETCH_TIMEOUT_SEC
                )
            except Exception as e:
                return f"Error: {url} 抓取失败: {e}"
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*(fetch_one(url) for url in urls)),
            timeout=BATCH_FETCH_TIMEOUT_SEC
        )
    except asyncio.TimeoutError:
        return "Error: 批量抓取超时，请减少URL数量后重试。"
    return "\n\n=== 文章分隔线 ===\n\n".join(results)

if __name__ == '__main__':
    mcp.run("streamable-http")
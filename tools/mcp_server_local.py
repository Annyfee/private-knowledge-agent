import os
import pdfplumber
import docx
import concurrent.futures
from mcp.server.fastmcp import FastMCP
from loguru import logger
from tools.rag_store import RAGStore

mcp = FastMCP("LocalKnowledgeServer", host="0.0.0.0", port=8003)

DATA_DIR = os.path.realpath(os.path.join(os.getcwd(), "data"))
GLOBAL_SESSION_ID = "enterprise_local_kb"
rag = RAGStore()

SUPPORTED_EXTS = ('.txt', '.md', '.pdf', '.docx')

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)


def extract_text_from_file(file_path: str) -> str:
    """文件解析器：加入 GBK 与 UTF-8 双重编码防线"""
    ext = os.path.splitext(file_path)[-1].lower()
    try:
        if ext in ('.txt', '.md'):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except UnicodeDecodeError:
                with open(file_path, 'r', encoding='gbk', errors='ignore') as f:
                    return f.read()

        elif ext == '.pdf':
            text = ""
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            return text.replace('\ufffd', '')

        elif ext == '.docx':
            doc = docx.Document(file_path)
            return "\n".join([para.text for para in doc.paragraphs])

        return ""
    except Exception as e:
        logger.error(f"解析文件 {file_path} 失败: {e}")
        return ""


@mcp.tool()
async def list_local_files() -> str:
    """列出本地企业知识库(data目录)下的所有可用文件。"""
    files = [f for f in os.listdir(DATA_DIR) if f.lower().endswith(SUPPORTED_EXTS)]
    if not files:
        return "本地知识库目前为空。"
    return "【本地知识库文件列表】:\n" + "\n".join([f"- {f}" for f in files])


@mcp.tool()
async def read_local_file(filename: str) -> str:
    """读取指定本地文件的全文内容。如果文件过长报错，必须改用 search_local_knowledge"""
    file_path = os.path.realpath(os.path.join(DATA_DIR, filename))
    if os.path.commonpath([file_path, DATA_DIR]) != DATA_DIR:
        return "Error: 非法文件路径，拒绝访问。"

    if not os.path.exists(file_path):
        return f"Error: 文件 '{filename}' 不存在。"

    content = extract_text_from_file(file_path)
    if len(content) > 6000:
        return f"Error: 文件过长。请改用 'search_local_knowledge' 工具，并搜索诸如 '摘要'、'总结'、'结论' 等关键词来提取核心思想。"
    return f"【来源文件: {filename}】\n{content}"


@mcp.tool()
async def search_local_knowledge(query: str) -> str:
    """语义检索工具：用于寻找具体数据指标，或超长文件的局部查询"""
    logger.info(f"🔍 [RAG Search] 正在检索私有知识库: {query}")
    try:
        return rag.query_formatted(query=query, session_id=GLOBAL_SESSION_ID)
    except Exception as e:
        return f"检索失败: {str(e)}"


def process_single_file(filename: str):
    try:
        file_path = os.path.join(DATA_DIR, filename)
        mtime = os.path.getmtime(file_path)
        content = extract_text_from_file(file_path)

        if content.strip():
            rag.add_documents(text_content=content, source_url=filename, session_id=GLOBAL_SESSION_ID, mtime=mtime)
            logger.success(f"✅ 文件增量入库成功: {filename}")
    except Exception as e:
        logger.error(f"❌ 文件入库失败 [{filename}]: {e}")


def ingest_local_files_to_rag():
    """具备智能 Diff 能力的增量同步调度器"""

    current_files = {}
    for f in os.listdir(DATA_DIR):
        if f.lower().endswith(SUPPORTED_EXTS):
            file_path = os.path.join(DATA_DIR, f)
            current_files[f] = os.path.getmtime(file_path)

    if not current_files:
        logger.warning("⚠️ 本地 knowledge 库为空。")
        rag.clear_session(GLOBAL_SESSION_ID)
        return

    indexed_mtimes = rag.get_indexed_file_mtimes(GLOBAL_SESSION_ID)

    files_to_delete = []
    files_to_add = []

    for filename, indexed_mtime in indexed_mtimes.items():
        if filename not in current_files:
            files_to_delete.append(filename)
        elif current_files[filename] > indexed_mtime:
            files_to_delete.append(filename)
            files_to_add.append(filename)

    for filename in current_files:
        if filename not in indexed_mtimes:
            files_to_add.append(filename)

    if not files_to_delete and not files_to_add:
        logger.success(f"⚡ 知识库已是最新状态 (共监控 {len(current_files)} 个文件)，跳过向量化计算，秒速启动！")
        return

    logger.info(f"🔄 检测到文件变动: 需新增/更新 {len(files_to_add)} 个, 需移除 {len(files_to_delete)} 个")

    for filename in files_to_delete:
        rag.delete_file(filename, GLOBAL_SESSION_ID)

    if files_to_add:
        max_workers = 5
        logger.info(f"⚡ 启动多线程计算引擎，仅对变动文件进行向量化处理...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            executor.map(process_single_file, files_to_add)

    logger.success("🎉 私有知识库增量同步完成！")


if __name__ == "__main__":
    ingest_local_files_to_rag()
    logger.info("🚀 本地私域知识 MCP Server 启动 | 监听: 8003")
    mcp.run("streamable-http")
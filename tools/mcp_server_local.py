import os
import json
import pdfplumber
import docx
import concurrent.futures
from mcp.server.fastmcp import FastMCP
from loguru import logger
from tools.rag_store import RAGStore

mcp = FastMCP("LocalKnowledgeServer", host="0.0.0.0", port=8003)

DATA_DIR = os.path.realpath(os.path.join(os.getcwd(), "data"))
DB_DIR = os.path.realpath(os.path.join(os.getcwd(), "db"))  # 新增 DB_DIR，让索引状态与 data 目录隔离
INDEX_STATE_FILE = os.path.join(DB_DIR, "index_state.json")  # 索引状态落盘位置改到db，避免污染输入目录
GLOBAL_SESSION_ID = "enterprise_local_kb"
rag = RAGStore()

SUPPORTED_EXTS = ('.txt', '.md', '.pdf', '.docx')

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
if not os.path.exists(DB_DIR):
    os.makedirs(DB_DIR)  # 确保 db 存在，避免首次写索引状态失败


def extract_text_from_file(file_path: str) -> str:
    """万能文件解析器：支持 UTF-8 和 GBK 编码"""
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


def get_current_file_fingerprints() -> dict:
    """获取当前所有文件的指纹：文件名 -> 文件大小"""
    fingerprints = {}
    for f in os.listdir(DATA_DIR):
        if f.lower().endswith(SUPPORTED_EXTS):
            file_path = os.path.join(DATA_DIR, f)
            file_stat = os.stat(file_path)
            # 指纹从仅 size 改成 size+mtime_ns,降低内容变更漏检风险
            fingerprints[f] = {"size": file_stat.st_size, "mtime_ns": file_stat.st_mtime_ns}
    return fingerprints


def load_last_index_state() -> dict:
    """加载上次索引状态"""
    try:
        if os.path.exists(INDEX_STATE_FILE):
            with open(INDEX_STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"读取索引状态失败: {e}")
    return {}


def save_index_state(fingerprints: dict):
    """保存当前索引状态"""
    try:
        with open(INDEX_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(fingerprints, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存索引状态失败: {e}")


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
    # 路径安全校验改为 commonpathm，避免路径前缀绕过
    if os.path.commonpath([DATA_DIR, file_path]) != DATA_DIR:
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
    """处理单个文件：解析并存入向量库"""
    try:
        file_path = os.path.join(DATA_DIR, filename)
        content = extract_text_from_file(file_path)
        if not content.strip():
            logger.warning(f"⚠️ 文件内容为空，跳过: {filename}")
            return
        rag.add_documents(text_content=content, source_url=filename, session_id=GLOBAL_SESSION_ID)
    except Exception as e:
        logger.error(f"❌ 文件入库失败 [{filename}]: {e}")

def ingest_local_files_to_rag():
    """极简增量检测：文件指纹一致则跳过，否则全量重建"""
    current = get_current_file_fingerprints()
    last = load_last_index_state()
    if current == last:
        logger.success(f"⚡ 文件未变动，跳过向量化 ({len(current)} 个文件)")
        return
    total = len(current)
    logger.info(f"🔄 检测到文件变动，开始重建 ({total} 个文件)")
    rag.clear_session(GLOBAL_SESSION_ID)
    if current:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(process_single_file, f): f for f in current.keys()}
            for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
                logger.info(f"📦 [{i}/{total}] 已完成: {futures[future]} | 剩余 {total - i} 个")
    # save_index_state 移到 if 外，即使 data 为空也保存状态，避免反复重建
    save_index_state(current)
    logger.success("🎉 知识库构建完成！")


if __name__ == "__main__":
    ingest_local_files_to_rag()
    logger.info("🚀 本地私域知识 MCP Server 启动 | 监听: 8003")
    mcp.run("streamable-http")
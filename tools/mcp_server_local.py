import os
import json
import pdfplumber
import docx
import concurrent.futures
import threading
from mcp.server.fastmcp import FastMCP
from loguru import logger
from tools.rag_store import RAGStore

mcp = FastMCP("LocalKnowledgeServer", host="0.0.0.0", port=8003)

DATA_DIR = os.path.realpath(os.path.join(os.getcwd(), "data")) # 要读的文档
DB_DIR = os.path.realpath(os.path.join(os.getcwd(), "db"))  # 存放 AI 处理后的数据（索引），这样下次就不用重新读了
INDEX_STATE_FILE = os.path.join(DB_DIR, "index_state.json")  # 记录文件的“指纹”，用来判断文件有没有变动
GLOBAL_SESSION_ID = "enterprise_local_kb"
rag = RAGStore()

SUPPORTED_EXTS = ('.txt', '.md', '.pdf', '.docx')
_INGEST_LOCK = threading.Lock()  # 防止运行中 data 已更新但仍命中旧索引

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(DB_DIR, exist_ok=True)  # 确保文件存在，避免首次写索引状态失败


def extract_text_from_file(file_path: str) -> str:
    """文件解析器：支持 UTF-8 和 GBK 编码"""
    ext = os.path.splitext(file_path)[-1].lower() # 获取文件后缀名
    try:
        if ext in ('.txt', '.md'): # 直接读
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except UnicodeDecodeError:
                with open(file_path, 'r', encoding='gbk', errors='ignore') as f: # 双重保障，遇到坏字节跳过，保证流程继续
                    return f.read()

        elif ext == '.pdf': # 按页提取，过滤乱码字符
            text = ""
            with pdfplumber.open(file_path) as pdf: # 打开pdf
                for page in pdf.pages: # 按页遍历
                    page_text = page.extract_text() # 从这页提取文本
                    if page_text: # 保证有文本在的情况下
                        text += page_text + "\n"
            return text.replace('\ufffd', '') # 去掉乱码字符

        elif ext == '.docx': # 按段提取，换行拼接保持语义边界
            doc = docx.Document(file_path) # 读取doc为document对象
            return "\n".join([para.text for para in doc.paragraphs])

        return ""
    except Exception as e:
        logger.error(f"解析文件 {file_path} 失败: {e}")
        return ""


def get_current_file_fingerprints() -> dict:
    """扫描DATA_DIR下支持的文件，生成文件指纹字典：文件名 -> 文件大小"""
    fingerprints = {}
    for f in os.listdir(DATA_DIR): # 列出当前目录下的名字列表
        if f.lower().endswith(SUPPORTED_EXTS): # 过滤无关文件
            file_path = os.path.join(DATA_DIR, f)
            file_stat = os.stat(file_path) # 读取文件的元信息
            # 指纹为 size(大小)+mtime_ns(最后修改时间) 双重保险,降低内容变更漏检风险
            fingerprints[f] = {"size": file_stat.st_size, "mtime_ns": file_stat.st_mtime_ns}
    return fingerprints


def load_last_index_state() -> dict:
    """读取上一次索引快照"""
    try:
        if os.path.exists(INDEX_STATE_FILE):
            with open(INDEX_STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"读取索引状态失败: {e}")
    return {}


def save_index_state(fingerprints: dict):
    """保存当前索引状态，写入文件"""
    try:
        with open(INDEX_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(fingerprints, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存索引状态失败: {e}")


def process_single_file(filename: str):
    """处理单个文件：解析并存入向量库"""
    try:
        file_path = os.path.join(DATA_DIR, filename)
        content = extract_text_from_file(file_path) # 解析文件内容
        if not content.strip():
            logger.warning(f"⚠️ 文件内容为空，跳过: {filename}")
            return
        rag.add_documents(text_content=content, source_file=filename, session_id=GLOBAL_SESSION_ID) # 文本向量入库，加入sour_url与session_id保证隔离与可溯源
    except Exception as e:
        logger.error(f"❌ 文件入库失败 [{filename}]: {e}")


def ingest_local_files_to_rag():
    """增量检测：文件指纹一致则跳过，否则全量重建"""
    current = get_current_file_fingerprints() # 生成当前文件指纹
    last = load_last_index_state() # 读取上次索引快照
    if current == last:
        logger.success(f"⚡ 文件未变动，跳过向量化 ({len(current)} 个文件)")
        return
    total = len(current)
    logger.info(f"🔄 检测到文件变动，开始重建 ({total} 个文件)")
    rag.clear_session(GLOBAL_SESSION_ID) # 清理旧session的旧向量数据，避免新旧索引混在一起

    if current: # 确保文件存在才进入线程池并发处理
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor: # 创建线程池，最多5个工程线程并发执行任务
            futures = {}
            for f in current.keys():
                future = executor.submit(process_single_file, f) # 向线程池提交一个任务(解析文件并存入数据库)，返回一个Future对象
                futures[future] = f # 将future与文件f对应
            for i, future in enumerate(concurrent.futures.as_completed(futures), 1): # 按谁先完成谁先产出的顺序产出future
                logger.info(f"📦 [{i}/{total}] 已完成: {futures[future]} | 剩余 {total - i} 个")

    # save_index_state 移到 if 外，即使 data 为空也保存状态，避免反复重建
    save_index_state(current)
    logger.success("🎉 知识库构建完成！")


def ensure_index_is_fresh():
    """若 data 变化且服务未重启，自动触发索引重建。"""
    current = get_current_file_fingerprints() # 现场扫描
    last = load_last_index_state()
    if current == last:
        return # 一样就结束

    with _INGEST_LOCK: # 多个并发请求会触发同一份共享状态更新，需要 互斥+重检(锁) 保证只做一次有效更新
        # 避免并发请求重复重建
        current = get_current_file_fingerprints()
        last = load_last_index_state()
        if current != last:
            logger.warning("⚠️ 发现 data 与索引状态不一致，正在自动重建索引...")
            ingest_local_files_to_rag()


@mcp.tool()
async def list_local_files() -> str:
    """列出本地知识库(data目录)下的所有可用文件。"""
    files = [f for f in os.listdir(DATA_DIR) if f.lower().endswith(SUPPORTED_EXTS)]
    if not files:
        return "本地知识库目前为空。"
    return "【本地知识库文件列表】:\n" + "\n".join([f"- {f}" for f in files])


@mcp.tool()
async def read_local_file(filename: str) -> str:
    """读取指定本地文件的全文内容。如果文件过长报错，必须改用 search_local_knowledge"""
    file_path = os.path.realpath(os.path.join(DATA_DIR, filename))  # 文件路径
    # 路径安全校验改为公共父路径，避免路径前缀绕过
    if os.path.commonpath([DATA_DIR, file_path]) != DATA_DIR:
        return "Error: 非法文件路径，拒绝访问。"

    if not os.path.exists(file_path):
        return f"Error: 文件 '{filename}' 不存在。"

    content = extract_text_from_file(file_path) # 获取内容
    if len(content) > 3000:
        return "Error: 文件过长。请改用 'search_local_knowledge' 工具，并搜索诸如 '摘要'、'总结'、'结论' 等关键词来提取核心思想。"
    return f"【来源文件: {filename}】\n{content}" # 保证可溯源


@mcp.tool()
async def search_local_knowledge(query: str) -> str:
    """语义检索工具：用于寻找具体数据指标，或超长文件的局部查询"""
    logger.info(f"🔍 [RAG Search] 正在检索私有知识库: {query}")
    try:
        ensure_index_is_fresh()  # 每次检索前确认索引与 data 同步
        return rag.query_formatted(query=query, session_id=GLOBAL_SESSION_ID)
    except Exception as e:
        return f"检索失败: {str(e)}"


if __name__ == "__main__":
    ingest_local_files_to_rag() # 增量检测
    logger.info("🚀 本地私域知识 MCP Server 启动 | 监听: 8003")
    mcp.run("streamable-http")
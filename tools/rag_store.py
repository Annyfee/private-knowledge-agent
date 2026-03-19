# 导入 Flashrank (Reranker 始终用轻量级本地版)
from flashrank import Ranker, RerankRequest
# LangChain 组件
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from loguru import logger

# 导入配置
from config import USE_LOCAL_EMBEDDING, EMBEDDING_API_KEY, EMBEDDING_BASE_URL, EMBEDDING_MODEL_NAME


class RAGStore:
    def __init__(self):
        logger.info(f"🚀 [Init] 初始化 RAG 系统 | 模式: {'纯本地' if USE_LOCAL_EMBEDDING else '云端API'}")

        # Embedding
        if USE_LOCAL_EMBEDDING:
            # 【本地模式】加载 HuggingFace 模型 (吃内存，省钱)
            from langchain_huggingface import HuggingFaceEmbeddings
            logger.info(f"📥 正在加载本地模型: {EMBEDDING_MODEL_NAME} (请确保显存/内存充足)...")
            self.embedding = HuggingFaceEmbeddings(
                model_name=EMBEDDING_MODEL_NAME,
                model_kwargs={'device': 'cpu'},
                encode_kwargs={'normalize_embeddings': True}# 输出的向量做归一化，方便后续做相似度搜索
            )
        else:
            # 【云端模式】调用 SiliconFlow API (省内存，极速)
            from langchain_openai import OpenAIEmbeddings
            if not EMBEDDING_API_KEY or not EMBEDDING_API_KEY.startswith("sk-"):
                logger.error("❌ 未配置 EMBEDDING_API_KEY，无法使用云端模式！")
                raise ValueError("API Key Missing")

            logger.info(f"☁️ 正在连接云端 Embedding: {EMBEDDING_MODEL_NAME}...")
            self.embedding = OpenAIEmbeddings(
                model=EMBEDDING_MODEL_NAME,
                openai_api_key=EMBEDDING_API_KEY,
                openai_api_base=EMBEDDING_BASE_URL,
                check_embedding_ctx_length=False
            )

        # 切分器
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=1200,
            chunk_overlap=250,
            # 明确指明切割方法，按这个顺序依次往后排（如果不指定会默认切）
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " "]
        )

        # 向量库
        self.vector_store = Chroma(
            persist_directory="./chroma_db",
            # 选择用该模型来做embedding的工作
            embedding_function=self.embedding
        )

        # Reranker:精排序 (Flashrank:为了适应格式，在精排序前后要转换协议)
        self.reranker = Ranker(
            model_name="ms-marco-MiniLM-L-12-v2",
            cache_dir="./models"
        )

        logger.info("✅ [Init] RAG 系统就绪")

    # RAG - 离线模块(加载与切块/向量化/存入向量数据库)
    def add_documents(self, text_content: str, source_url: str = "", session_id: str = None, mtime: float = 0.0):
        """存入向量数据库"""
        if not text_content or len(text_content) < 50:
            logger.warning("⚠️ 内容过短，跳过入库")
            return False

        # 封装 Document(Document是langchain固定接收的对象格式) metadata则指明具体身份
        # 注:后续我们会不断沿用这个数据结构，可以理解为数据库反复读写查询，但其参数没变
        raw_doc = Document(page_content=text_content, metadata={"source_url": source_url, "session_id": session_id})
        # 切片
        chunks = self.splitter.split_documents([raw_doc])

        for chunk in chunks:
            chunk.metadata = {"source_url": source_url, "session_id": session_id, "mtime": mtime}

        # --- 分批入库 ---
        # 某些API平台限制单次 batch，我们设为 50 比较安全
        batch_size = 50
        total_chunks = len(chunks)

        for i in range(0, total_chunks, batch_size):
            batch = chunks[i: i + batch_size]
            self.vector_store.add_documents(batch)
            # 调用向量库内置方法:将这一批次(50个)文本片段发送给 Embedding模型进行向量化，再将生成的向量连同原始文本、元数据一同持久化存储到本地Chroma数据库中
            # 简单讲，此处囊括了 文本向量化+存入向量数据库 两步
            # 注意:在此步前，我们的batch一直都还是非向量形态
            logger.info(f"💾 [Store] 分批入库: {len(batch)} 个片段 ({i + len(batch)}/{total_chunks})")

        logger.info(f"✅ [Store] 全部入库完成 (共 {total_chunks} 个片段 | 来源: {source_url})")
        return True

    # RAG - 在线模块(粗排/精排/过滤)
    def query(self, question: str, session_id: str, k_retrieve=50, k_final=6, score_threshold=0.7):
        """
        检索流程: 向量粗排 -> Flashrank 精排
        粗排 - 计算数学距离（长得像就行）；
        精排 - 进行语义对齐（仔细理解出核心逻辑）

        question:问题；
        k_retrieve:粗排个数;
        k_final:精排个数;
        score_threshold:得分阈值/低于此抛弃
        """
        logger.info(f"🔍 [Search] 向量检索 Top-{k_retrieve}...")

        docs = self.vector_store.similarity_search(question, k=k_retrieve, filter={"session_id": session_id})

        if not docs:
            logger.warning("⚠️ 未找到相关文档")
            return []

        # 精排
        logger.info(f"⚡️ [Rerank] Flashrank 重排序...")
        # 把数据封装成FlashRank接受的格式(doc.page_content是原始文本内容;doc.metadata是档案来源：比如你可以指定为last_msg.tool_call_id)
        # FlashRank是针对精排序的。所以这里在数据传过去与传回来都需要调整格式。
        passages = []
        for i, doc in enumerate(docs):
            passages.append({"id": str(i), "text": doc.page_content, "meta": doc.metadata})

        # 把LangChain的Document列表转换为FlashRank理解的passages列表
        rerank_request = RerankRequest(query=question, passages=passages)
        # 将数据喂给精排模型，并返回一个打分列表
        results = self.reranker.rerank(rerank_request)

        # 过滤
        final_docs = []
        score = []
        # 必须得分超过对应阈值才能返回
        for res in results:
            if res['score'] >= score_threshold:
                # 将FlashRank返回的py字典转化为LangChain接受的Document对象
                doc = Document(page_content=res['text'], metadata=res['meta'])
                doc.metadata['rerank_score'] = res['score']
                score.append(res['score'])
                final_docs.append(doc)
            if len(final_docs) >= k_final:
                break

        # 兜底机制：无结果达到阈值则返回 top3
        if not final_docs and results:
            logger.warning(f"⚠️ [Result] 无结果达到阈值 ({score_threshold})，返回 top3 兜底数据")
            for res in results[:3]:
                doc = Document(page_content=res['text'], metadata=res['meta'])
                doc.metadata['rerank_score'] = res['score']
                score.append(res['score'])
                final_docs.append(doc)

        logger.info(f"✅ [Result] 返回 {len(final_docs)} 个结果 | 打分结果:{score}")
        return final_docs

    def clear_session(self, session_id: str):
        """任务完成时，清空该用户的RAG数据"""
        try:
            self.vector_store._collection.delete(where={"session_id": session_id})
            logger.success(f"🧹 [Clear] 已清空用户({session_id}) 的临时 RAG 数据")
        except Exception as e:
            logger.error(f"❌ 清库失败 (可能库为空): {e}")

    def query_formatted(self, query: str, session_id: str):
        """直接返回格式化好的字符串，给Tool和Writer用"""
        results = self.query(query, session_id)

        if not results:
            return "知识库中未找到相关内容。"

        # 格式化返回结果
        formatted_res = []
        for doc in results:
            source = doc.metadata.get('source_url', 'unknown')
            score = doc.metadata.get('rerank_score', 0)
            formatted_res.append(f"[来源: {source} | 置信度: {score:.2f}]\n{doc.page_content}")

        return "\n\n---\n\n".join(formatted_res)

    def get_indexed_file_mtimes(self, session_id: str) -> dict:
        """获取当前知识库中已索引的文件及其最后修改时间"""
        try:
            results = self.vector_store.get(where={"session_id": session_id}, include=["metadatas"])
            file_mtimes = {}
            if results and results.get("metadatas"):
                for meta in results["metadatas"]:
                    if meta and "source_url" in meta:
                        url = meta["source_url"]
                        mtime = meta.get("mtime", 0.0)
                        file_mtimes[url] = mtime
            return file_mtimes
        except Exception as e:
            logger.error(f"获取已索引文件失败: {e}")
            return {}

    def delete_file(self, source_url: str, session_id: str):
        """从知识库中精确删除某个特定文件的所有切片"""
        try:
            self.vector_store._collection.delete(
                where={"$and": [{"source_url": source_url}, {"session_id": session_id}]}
            )
            logger.info(f"🗑️ [Store] 已从向量库精准移除失效文件: {source_url}")
        except Exception as e:
            logger.error(f"❌ [Store] 移除失效文件失败 {source_url}: {e}")
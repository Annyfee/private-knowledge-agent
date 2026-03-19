import os
from flashrank import Ranker, RerankRequest
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from loguru import logger

from config import USE_LOCAL_EMBEDDING, EMBEDDING_API_KEY, EMBEDDING_BASE_URL, EMBEDDING_MODEL_NAME


class RAGStore:
    def __init__(self):
        logger.info(f"🚀 [Init] 初始化 RAG 系统 | 模式: {'纯本地' if USE_LOCAL_EMBEDDING else '云端API'}")

        # Embedding 初始化
        if USE_LOCAL_EMBEDDING:
            from langchain_huggingface import HuggingFaceEmbeddings
            logger.info(f"📥 正在加载本地模型: {EMBEDDING_MODEL_NAME}...")
            self.embedding = HuggingFaceEmbeddings(
                model_name=EMBEDDING_MODEL_NAME,
                model_kwargs={'device': 'cpu'},
                encode_kwargs={'normalize_embeddings': True}
            )
        else:
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

        # 文本切分器
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=1200,
            chunk_overlap=250,
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " "]
        )

        # 向量数据库
        self.vector_store = Chroma(
            persist_directory="./chroma_db",
            embedding_function=self.embedding
        )

        # 重排序模型
        self.reranker = Ranker(
            model_name="ms-marco-MiniLM-L-12-v2",
            cache_dir="./models"
        )

        logger.info("✅ [Init] RAG 系统就绪")

    def add_documents(self, text_content: str, source_url: str = "", session_id: str = None):
        """存入向量数据库"""
        if not text_content or len(text_content) < 50:
            logger.warning("⚠️ 内容过短，跳过入库")
            return False

        raw_doc = Document(page_content=text_content, metadata={"source_url": source_url, "session_id": session_id})
        chunks = self.splitter.split_documents([raw_doc])
        # --- 分批入库 ---
        # 某些API平台限制单次 batch，我们设为 50 比较安全
        batch_size = 50
        for i in range(0,len(chunks),batch_size):
            # 调用向量库内置方法:将这一批次(50个)文本片段发送给 Embedding模型进行向量化，再将生成的向量连同原始文本、元数据一同持久化存储到本地Chroma数据库中
            # 简单讲，此处囊括了 文本向量化+存入向量数据库 两步
            # 注意:在此步前，我们的batch一直都还是非向量形态
            self.vector_store.add_documents(chunks[i:i+batch_size])
        logger.info(f"💾   {source_url} -> {len(chunks)} 个片段")
        return True

    def query(self, question: str, session_id: str, k_retrieve=50, k_final=6, score_threshold=0.5):
        """检索 + 重排序"""
        docs = self.vector_store.similarity_search(question, k=k_retrieve, filter={"session_id": session_id})

        if not docs:
            logger.warning("⚠️ 未找到相关文档")
            return []

        # FlashRank 重排序
        passages = [{"id": str(i), "text": d.page_content, "meta": d.metadata} for i, d in enumerate(docs)]
        results = self.reranker.rerank(RerankRequest(query=question, passages=passages))

        # 筛选高分结果
        final_docs = []
        scores = []
        for res in results:
            if res['score'] >= score_threshold:
                doc = Document(page_content=res['text'], metadata=res['meta'])
                doc.metadata['rerank_score'] = res['score']
                final_docs.append(doc)
                scores.append(res['score'])
            if len(final_docs) >= k_final:
                break

        # 兜底：无结果达到阈值则返回 top3
        if not final_docs and results:
            logger.warning(f"⚠️ 无结果达到阈值 ({score_threshold})，返回 top3 兜底")
            for res in results[:3]:
                doc = Document(page_content=res['text'], metadata=res['meta'])
                doc.metadata['rerank_score'] = res['score']
                final_docs.append(doc)
                scores.append(res['score'])

        logger.info(f"✅ 返回 {len(final_docs)} 个结果 | 分数: {scores}")
        return final_docs

    def clear_session(self, session_id: str):
        """清空指定会话的所有数据"""
        try:
            self.vector_store._collection.delete(where={"session_id": session_id})
            logger.success(f"🧹 已清空会话 ({session_id}) 的 RAG 数据")
        except Exception as e:
            logger.error(f"❌ 清库失败: {e}")

    def query_formatted(self, query: str, session_id: str):
        """格式化查询结果"""
        results = self.query(query, session_id)

        if not results:
            return "知识库中未找到相关内容。"

        formatted = []
        for doc in results:
            source = doc.metadata.get('source_url', 'unknown')
            score = doc.metadata.get('rerank_score', 0)
            formatted.append(f"[来源: {source} | 置信度: {score:.2f}]\n{doc.page_content}")

        return "\n\n---\n\n".join(formatted)
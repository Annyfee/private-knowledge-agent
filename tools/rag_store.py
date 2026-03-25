import os
import threading
from flashrank import Ranker, RerankRequest
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from loguru import logger
from langchain_huggingface import HuggingFaceEmbeddings
from config import EMBEDDING_MODEL_NAME, EMBEDDING_MODEL_LOCAL_PATH, EMBEDDING_LOCAL_ONLY


class RAGStore:
    def __init__(self):
        logger.info("🚀 [Init] 初始化 RAG 系统 | 模式: 纯本地")  # 固定为本地 Embedding 模式

        # 本地 Embedding 初始化
        model_source = EMBEDDING_MODEL_LOCAL_PATH if os.path.isdir(EMBEDDING_MODEL_LOCAL_PATH) else EMBEDDING_MODEL_NAME  # 优先使用已挂载的本地目录模型
        if EMBEDDING_LOCAL_ONLY and model_source == EMBEDDING_MODEL_NAME:
            raise FileNotFoundError(
                f"本地模型目录不存在: {EMBEDDING_MODEL_LOCAL_PATH}。"
                f"请先下载模型到该目录，或确认卷挂载是否生效。"
            )  # 本地模式下快速失败并给出明确原因，避免远程下载长时间阻塞
        logger.info(f"📥 正在加载本地模型: {model_source}...")

        # 向量化模型
        self.embedding = HuggingFaceEmbeddings(
            model_name=model_source,
            model_kwargs={'device': 'cpu', 'local_files_only': EMBEDDING_LOCAL_ONLY},  # 强制仅从本地文件加载，不触发网络下载
            encode_kwargs={'normalize_embeddings': True} # 向量是否归一化->把向量长度统一成1的单位向量，便利之后的相似度计算
        )

        # 文本切分器
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=1200,
            chunk_overlap=250,
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " "] # 优先按这些格式切
        )

        # 向量数据库
        self.vector_store = Chroma(
            persist_directory="./chroma_db", # 存储在本地数据库
            embedding_function=self.embedding # 为向量库指定向量化模型
        )

        # 并发加锁
        self._write_lock = threading.Lock()  # 为向量库写入加锁，降低并发写入不稳定风险

        # 重排序模型
        self.reranker = Ranker(
            model_name="ms-marco-MiniLM-L-12-v2",
            cache_dir="./models"
        )

        logger.info("✅ [Init] RAG 系统就绪")

    def add_documents(self, text_content: str, source_file: str = "", session_id: str = None):
        """存入向量数据库"""
        raw_doc = Document(page_content=text_content, metadata={"source_file": source_file, "session_id": session_id}) # 包装成LangChain的Document对象，metadata放可溯源字段
        chunks = self.splitter.split_documents([raw_doc]) # 分块与切割
        # --- 分批入库 --- | 某些平台要求batch_size<64
        batch_size = 50
        with self._write_lock:  # 多线程调用时，保证每次只有一个线程调用，防止并发写入不稳定
            for i in range(0,len(chunks),batch_size):
                # 调用向量库内置方法:将这一批次(50个)文本片段发送给 Embedding模型进行向量化，再将生成的向量连同原始文本、元数据一同持久化存储到本地Chroma数据库中
                # 此处囊括 文本向量化+存入向量数据库 两步 | 在此前，batch还是非向量状态
                self.vector_store.add_documents(chunks[i:i+batch_size])
        logger.info(f"💾   {source_file} -> {len(chunks)} 个片段")
        return True

    def query(self, question: str, session_id: str, k_retrieve=50, k_final=6, score_threshold=0.5):
        """粗排 + 精排"""

        docs = self.vector_store.similarity_search(question, k=k_retrieve, filter={"session_id": session_id}) # 向量粗召回

        if not docs:
            logger.warning("⚠️ 未找到相关文档")
            return []

        # FlashRank 重排序
        passages = [{"id": str(i), "text": d.page_content, "meta": d.metadata} for i, d in enumerate(docs)] # 把Document转为FlashRank需要的结构
        results = self.reranker.rerank(RerankRequest(query=question, passages=passages))

        # 筛选高分结果
        final_docs = []
        scores = []
        for res in results:
            if res['score'] >= score_threshold:
                doc = Document(page_content=res['text'], metadata=res['meta'])# 再把原先放过去的的几个key拿回来
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
            self.vector_store._collection.delete(where={"session_id": session_id}) # 做条件删除
            logger.success(f"🧹 已清空会话 ({session_id}) 的 RAG 数据")
        except Exception as e:
            logger.error(f"❌ 清库失败: {e}")

    def query_formatted(self, query: str, session_id: str):
        """把query的结构化结果，转化成LLM可直接消费dee字符串"""
        results = self.query(query, session_id)

        if not results:
            return "知识库中未找到相关内容。"

        formatted = []
        for doc in results:
            source = doc.metadata.get('source_file', 'unknown')
            score = doc.metadata.get('rerank_score', 0)
            formatted.append(f"[来源: {source} | 置信度: {score:.2f}]\n{doc.page_content}")

        return "\n\n---\n\n".join(formatted)

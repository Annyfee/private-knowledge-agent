import os
from dotenv import load_dotenv

# 1. 加载.env文件
load_dotenv()


# 2. 获取API_KEYS
OPENAI_MODEL = os.getenv("OPENAI_MODEL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY")
LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")


# 3.加载embedding模式

# --- 核心配置开关 ---
# True = 使用本地模型 (适合 16G+ 内存电脑)
# False = 使用硅基流动 API (适合 4G 服务器，省内存)
USE_LOCAL_EMBEDDING = False

# --- API 配置 ---
# 从环境变量获取，或者在本地测试时临时填在这里
# 部署时在服务器设置 export EMBEDDING_API_KEY="sk-..."
# EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "你的硅基流动sk-xxxx")
EMBEDDING_BASE_URL = "https://api.siliconflow.cn/v1"

# --- 模型选择 ---
# 云端和本地都用 BGE-M3，保持效果一致
EMBEDDING_MODEL_NAME = "BAAI/bge-m3"
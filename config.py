import os
from dotenv import load_dotenv

# 1. 加载.env文件
load_dotenv()


# 2. 获取API_KEYS
# 其余项均为可选，不配置时走默认值或不启用对应能力
OPENAI_MODEL = os.getenv("OPENAI_MODEL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY")

# --- 模型选择 ---
EMBEDDING_MODEL_NAME = "BAAI/bge-m3"
EMBEDDING_MODEL_LOCAL_PATH = "./models/embedding/bge-m3"  # 固定本地模型目录，优先直接加载本地文件
EMBEDDING_LOCAL_ONLY = True  # 强制仅本地加载，避免容器启动时走远程下载导致长时间卡住
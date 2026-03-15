import operator
from typing import Annotated

from langgraph.graph import MessagesState


class Researcher(MessagesState):
    # 全局上下文
    session_id:str
    # --- 子图业务状态 ---
    task:str
    # next_node只会给那些无法确定下个node的多状态节点来选择
    next_node:str
    task_idx:int
    retry_count:int
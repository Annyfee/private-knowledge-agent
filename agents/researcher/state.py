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
    # 记录子图内部一共跑了多少步
    step_count:Annotated[int,operator.add] # 当多个分支被更新赋值时，进行加法合并
import operator
from typing import Annotated, Sequence, TypedDict
from langchain_core.messages import BaseMessage


# 原来用 operator.add，research_data 只增不清。
# 同一 session 发第二次 research，Writer 会把新旧数据混着写报告。
# 用自定义 reducer：planner 发 [None] 作为 reset 信号，触发清空。
def _reset_or_add(existing: list, update: list) -> list:
    if update and update[0] is None:
        return list(update[1:])   # None 是哨兵，清空旧数据，保留 None 之后的内容
    return existing + update


class ResearchAgent(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    tasks: list[str]
    research_data: Annotated[list[str], _reset_or_add]  # 改为可重置的 reducer
    session_id: str
    intent: str
    final_answer: str


# 子图使用的 State
class ReaderState(TypedDict):
    task: str
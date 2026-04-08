from typing import Annotated, TypedDict
from langgraph.graph import MessagesState


# 原来用 operator.add，research_data 只增不清。
# 同一 session 发第二次 research，Writer 会把新旧数据混着写报告。
# 接收多列表，并决定它们合并的方式  如果第二个列表的第一个是None，扔掉第一个列表，只保留第二个列表。否则，俩列表拼接
def _reset_or_add(existing: list, update: list) -> list:
    if update and update[0] is None:
        return list(update[1:])   # 清空旧数据，保留 None 之后的内容
    return existing + update


class ResearchAgent(MessagesState):
    tasks: list[str]
    research_data: Annotated[list[str], _reset_or_add]  # 改为可重置的 reset函数，方便处理并发
    session_id: str
    intent: str
    final_answer: str


# 子图使用的 State
class ReaderState(TypedDict):
    task: str
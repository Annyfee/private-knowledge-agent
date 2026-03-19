from langgraph.graph import StateGraph, END, START
from langgraph.constants import Send
from loguru import logger

from state import ResearchAgent
from agents.manager import manager_node
from agents.chat import chat_node
from agents.planner import planner_node
from agents.reader import reader_node
from agents.writer import writer_node


def route_intent(state: ResearchAgent):
    intent = state.get("intent", "research")
    if intent == "chat":
        return "chat"
    else:
        return "planner"


def distribute_tasks(state: ResearchAgent):
    tasks = state.get("tasks", [])
    logger.info(f"🚀 [Graph] 正在并发分发 {len(tasks)} 个本地阅读任务...")
    return [Send("reader", {"task": t}) for t in tasks]

# 封装成lifespan需要的异步函数
async def build_graph(checkpointer=None):
    builder = StateGraph(ResearchAgent)

    # 注册所有节点
    builder.add_node("manager", manager_node)
    builder.add_node("chat", chat_node)
    builder.add_node("planner", planner_node)
    builder.add_node("reader", reader_node)
    builder.add_node("writer", writer_node)

    # 第一步：进入 Manager 识别意图
    builder.add_edge(START, "manager")

    # 第二步：根据意图分流
    builder.add_conditional_edges("manager", route_intent, {"chat": "chat", "planner": "planner"})

    # 闲聊流：直接结束
    builder.add_edge("chat", END)

    # 调研流：Planner -> 并发 Reader -> Writer -> 结束
    builder.add_conditional_edges("planner", distribute_tasks, ["reader"])
    builder.add_edge("reader", "writer")
    builder.add_edge("writer", END)

    graph = builder.compile(checkpointer=checkpointer)
    logger.info("✅ [Graph] 私域研报图网络编译完成 (带智能意图路由版)")
    return graph
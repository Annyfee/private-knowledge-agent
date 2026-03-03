from functools import partial

from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode

from agents.researcher.core import core_node
from agents.researcher.leader import leader_node
from agents.researcher.state import Researcher
from agents.researcher.surfer import surfer_node
from tools.registry import load_all_tools


# 检查返回的数据是否应还给surfer
async def route(state:Researcher):
    return state.get("next_node","end")


async def build_researcher_graph():
    """
    构建 研究员 子图
    """
    tools = await load_all_tools()

    workflow = StateGraph(Researcher)

    # 注意:这里partial是指定"有什么":让Agent看菜单;之后的node节点则是"走哪里":让Agent具体节点怎么选
    workflow.add_node("surfer",partial(surfer_node,tools=tools))
    workflow.add_node("tools",ToolNode(tools))
    workflow.add_node("core",core_node)
    workflow.add_node("leader",leader_node)

    # 连线
    # surfer -> tools -> core -> surfer/leader -> surfer/END
    workflow.add_edge(START,"surfer")
    workflow.add_edge("surfer","tools")
    workflow.add_edge("tools","core")
    workflow.add_conditional_edges(
        "core",
        route,
        {
            "surfer": "surfer",
            "leader":"leader",
        }
    )
    workflow.add_conditional_edges(
        "leader",
        route,
        {
            "surfer":"surfer",
            "end":END
        }
    )
    return workflow.compile() # 单轮对话无需长久记忆。只需要此次对话上下文保存即可。 不加相当于只靠return来进行单轮存储。
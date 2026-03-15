# 【规划员】 任务拆解:将用户问题分成3-5个具体的指令 planner -> surfer
import json
from datetime import datetime
from loguru import logger

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI

from state import ResearchAgent
from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from tools.utils_message import clean_msg_for_deepseek, slice_messages

llm = ChatOpenAI(
    model=OPENAI_MODEL,
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
    temperature=0.3
)


async def planner_node(state:ResearchAgent):
    """
    【规划员】
    职责: 将模糊的用户需求拆解为 2-4 个具体的、可执行的搜索指令。
    """

    logger.info(f"🎯 [Planner] 正在基于上下文拆解课题...")


    sys_prompt = f"""你是一名首席研究规划师。当前时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}。
    你的任务是将用户模糊、庞大的需求，拆解为 **3-5 个具体的、可执行的搜索引擎关键词**。

    【拆解原则】
    1. **多维视角**: 不要只换一种说法搜。要从“定义/背景”、“技术原理”、“市场数据”、“竞品对比”、“最新评价”等不同维度拆解。
    2. **关键词化**: 输出必须是适合 Google/Bing 搜索的关键词组合，而不是长难句。
    3. **逻辑递进**: 子任务应当有先后逻辑，帮助后续的 Writer 建立完整的知识链条。
    
    ### 🚫 严禁事项:
    1. **严禁输出任何 XML 标签**（如 <｜DSML｜> 等）。
    2. **严禁尝试调用工具**，你只需要输出计划列表。
    3. 不要输出任何解释性文字。

    【输出格式】
    {{
        "tasks":[
            "搜索 DeepSeek 公司的融资历程",
            "查找 DeepSeek-V3 模型的评测数据",
            "分析当前开源大模型市场的竞争格局"
        ]
    }}

    不要输出任何多余的解释或废话，只输出JSON。
    """

    # 选择最近8条相关数据返回
    messages = [SystemMessage(content=sys_prompt)] + state["messages"][-8:]
    slice_message = slice_messages(messages)
    safe_msg = clean_msg_for_deepseek(slice_message)

    # 保底确定返回数据格式正确
    try:
        response = await llm.ainvoke(safe_msg)
        # 防止可能存在的markdown语法
        content = response.content.replace("```json","").replace("```","").strip()
        tasks = json.loads(content)["tasks"]
        # 二次兜底，防止任务为空或值不是列表
        if not tasks or not isinstance(tasks,list):
            raise ValueError("任务为空或不是列表")
        return {
            "tasks": tasks,
        }
    except Exception as e:
        logger.warning(f"⚠️ [Planner] 解析失败，回滚到单任务模式: {e}")
        # 保底:把用户原话当做任务
        return {
            "tasks":[state["messages"][-1].content]
        }
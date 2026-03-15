# 【前台】 分析话术，选择是否传递当前任务，还是判定用户在闲聊，不往后启动。
import json
from datetime import datetime
from typing import Literal

from loguru import logger

from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from state import ResearchAgent
from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from tools.utils_message import clean_msg_for_deepseek,slice_messages



# 定义决策模型，用于路由判断
class RouteDecision(BaseModel):
    """路由决策"""
    mode:Literal["chat","research"] # 规定好确定的mode
    reasoning:str = "" # LLM的判断理由(日志)


# llm每次初始化放在外面，避免每次连接都重新调用
llm = ChatOpenAI(
    model=OPENAI_MODEL,
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
    temperature=0
)

async def chat_node(state:ResearchAgent):
    """
    闲聊回复节点(只在非任务状态下调用)
    """
    sys_prompt = f"""你是一名**专业的研究助手**，核心职责是引导用户进行有价值的课题研究。
    ### 🎯 你的使命
    1. **专注研究领域**: 只回答与研究、调查、分析相关的话题
    2. **引导深度思考**: 将简单问题引导到研究层面
    3. **婉拒离题话题**: 礼貌地将无关话题拉回研究主题
    ### 💬 回复策略
    #### ✅ 应该回答的问题：
    - "如何研究XXX？"
    - "帮我分析XXX的最新趋势"
    - "XXX领域的核心技术是什么？"
    - "关于XXX，你有哪些数据来源？"
    #### 🔄 需要引导的问题：
    用户问："今天天气不错啊？"
    ❌ 不要："是啊，我也这么觉得"
    ✅ 引导："谢谢！不过我是研究助手，更擅长帮你分析课题。比如你想了解气象研究领域的数据吗？"
    用户问："你会讲笑话吗？"
    ❌ 不要："当然，小明去买书..."
    ✅ 引导："我不擅长讲笑话，但如果你对幽默研究、脱口秀产业分析感兴趣，我可以帮你调研相关资料！"
    #### 🚫 应该婉拒的问题：
    用户问："推荐几首歌"
    ❌ 不要：[列出歌曲列表]
    ✅ 引导："音乐推荐不是我的专长，但我可以帮你研究音乐产业的趋势、流媒体平台的发展，或者音乐技术（如AI作曲）的现状。你对哪个方向感兴趣？"
    ### 📋 回复模板
    对于离题问题，使用以下结构：
    1. **礼貌承认**: "感谢你的兴趣/好问题"
    2. **表明局限**: "不过我的专长是研究领域"
    3. **提供替代**: "我可以帮你研究XXX相关的课题"
    4. **引导提问**: "你想了解哪方面的内容？"
    ### ⚠️ 约束
    - 保持专业但友好的语气
    - 不要在闲聊话题上展开对话
    - 每次回复都要尝试引导回研究主题
    - 如果用户坚持闲聊，礼貌地说明你的定位
    当前时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}
    """
    messages = [SystemMessage(content=sys_prompt)] + state['messages'][-8:]
    slice_message = slice_messages(messages)
    safe_msg = clean_msg_for_deepseek(slice_message)
    try:
        response = await llm.ainvoke(safe_msg)
        logger.info("☕ [Chat] 闲聊回复已生成")
        return {
            "main_route":"end_chat",
            "messages":[response]
        }
    except Exception as e:
        logger.error(f"Chat 节点异常: {e}")
        return {
            "main_route":"end_chat",
            "messages":[AIMessage(content="⚠️ 系统暂时异常，请稍后重试。")]
        }





async def manager_node(state:ResearchAgent):
    """
    【意图识别】 只做路由决策，不生成用户回复
    """

    # 用暗号，比常规JSON回复更稳定
    sys_prompt = f"""你是一名专业的 AI 助手项目经理。当前时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}。

        你的核心职责是【意图识别】。请根据用户的输入，严格遵守以下判断逻辑：

        ### 🛑 判定为【闲聊/回复】的情况:
        1. **闲聊/问候**: "你好", "你是谁", "天气不错"。
        2. **追问/纠正**: "不对", "我问的是这个", "停下", "在这个基础上再详细点"。
        3. **针对上一轮报告的提问**: "你觉得刚才的报告质量好吗", "为什么结果这么短"。
        4. **简单的知识问答**: "1+1等于几", "Python是什么" (不需要联网深挖的)。
        5. **无意义/模糊的短语**: "呃", "啊?", "测试", "123"。
        - 此时mode应为chat

        ### 🚀 判定为【研究任务】的情况:
        只有当用户**明确要求进行深度调查、搜索最新信息、或分析复杂话题**时。
        例如: "帮我查一下DeepSeek的最新融资", "分析2026年美国对委内瑞拉政策", "调研AI Agent的技术栈"。
        - 此时mode应为research
        
        
        ### ⚠️ 要求:
        请你只返回一个 JSON 对象，不要返回任何额外解释，不要加 Markdown 代码块。
        返回格式必须严格为：
        {{
          "mode": "chat" 或 "research",
        }}
        """


    messages = [SystemMessage(content=sys_prompt),HumanMessage(content=state['messages'][-1].content)]

    # 中间件清洗
    safe_meg = clean_msg_for_deepseek(messages)

    try:
        # with_structured_output:强制LLM输出符合预定义格式的数据
        # decision = await llm.with_structured_output(RouteDecision, method="function_calling").ainvoke(safe_meg)
        response = await llm.ainvoke(safe_meg)
        mode = json.loads(response.content)["mode"]
        logger.info(f"🧭 [Manager] 意图识别结果: {mode}")
        if mode == "chat":
            # 闲聊模式:路由到chat_node
            return {"main_route":"chat"}
        if mode == "research":
            # 研究模式:路由到 planner
            return {"main_route":"planner"}

    except Exception as e:
        # 针对 400 风控错误的特殊处理
        if "Content Exists Risk" in str(e):
            logger.error(f"🛡️ Manager 触发内容风控，拦截敏感话题。")
            return {
                "main_route": "end_chat",  # 👈 强制走结束路由，不再移交 Planner
                "messages": [AIMessage(content="⚠️ 抱歉，该话题涉及敏感内容，为了系统安全，研究程序已自动拦截。")]
            }
        logger.error(f"Manager 决策异常: {e}")
        # 遇到错误保守起见，当做闲聊处理，避免死循环
        return {"main_route": "end_chat","messages":[AIMessage(content="⚠️ 系统暂时异常，请稍后重试。")]}
# 【输出员】 高质量输出:只阅读RAG来产出报告
# 总流程: manager() -  planner(确认搜索方向) - surfer(开始搜寻) - core(数据入库) - leader(对数据做检查，是否进行第二轮检索) - writer(生成报告)
from datetime import datetime
from loguru import logger

import openai
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_openai import ChatOpenAI

from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from state import ResearchAgent
from tools.registry import global_rag_store

llm = ChatOpenAI(
    model=OPENAI_MODEL,
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
    temperature=0.3
)


async def writer_node(state:ResearchAgent):
    """
    [最终整合]
    职责:根据planner拆解的课题，从RAG中提取精准知识，撰写深度报告
    """
    logger.info("✍️ [Writer] 正在构建上下文并撰写报告...")

    # 检索rag数据
    content_blocks = []
    tasks = state.get("tasks",[])

    session_id = state.get("session_id","default_session")

    for i,task in enumerate(tasks):
        retrieved_text = global_rag_store.query_formatted(task,session_id=session_id)
        block = f"""
        ### 子课题 {i + 1}: {task}
        【检索到的信息】(注意：以下内容可能来自多个来源，可能存在差异或冲突，请交叉验证后使用):
        {retrieved_text}
        ---
        """
        content_blocks.append(block)

    full_context_str= "\n".join(content_blocks)

    # 提取最近的历史上下文(这里不直接使用state["messages"][-10:] 还特地转换格式，是为了将其给llm读，而不是直接用invoke的语法)
    chat_history = []
    for message in state["messages"][-5:]:
        role = "用户" if message.type == "human" else "AI"
        chat_history.append(f'{role}:{message.content}')
    history_str = "\n".join(chat_history)

    sys_prompt = f"""
    你是一名资深研究分析师，擅长将复杂信息整合成有洞察力的专业报告。
    ## 你的任务
    基于下方【研究资料】，为用户撰写一份有深度、有边界的分析报告。
    当前日期：{datetime.now().strftime("%Y-%m-%d")}(围绕当前时间点展开)
    ## 核心原则
    1. **证据优先**: 每个重要判断都必须有资料支撑。但允许在证据不足时给出合理推断，并简要提示“仍有进一步验证空间”即可。
    2. **区分事实与推断**: 明确说明哪些是资料中的事实，哪些是你的分析推断。
    3. **逻辑清晰、表达自信**: 用专业的语气呈现结论，不要过度强调“缺口”或“无法判断”。
    ## 分析框架 (按此思考，但不必机械套用)
    - **现象层**: 发生了什么？主要趋势是什么？
    - **机制层**: 背后的驱动因素是什么？
    - **影响层**: 对相关方意味着什么？
    - **边界层**: 结论在哪些情况下需要进一步验证？
    ## 输出结构
    请用以下结构组织报告，但各部分之间要有逻辑衔接，不是机械填空:
    # [标题：体现核心论点，而非泛泛而谈]
    ## 一、核心结论 (200-300 字)
    用 3-4 句话概括最关键发现，让读者快速把握要点。
    ## 二、关键发现 (4-6 条，每条含：发现 + 证据 + 含义)
    格式示例："发现：美国企业在华营收已超过美中货物贸易逆差。证据：70 家样本美企 2024 年在华营收达 3127 亿美元。含义：单纯看贸易逆差会低估中美经济捆绑程度。"
    ## 三、深度分析
    围绕主题分 3-5 个小节，每节聚焦一个核心维度。每节建议包含:
    - 关键事实/数据 (标注来源，如"据商务部统计")
    - 背后的机制或原因
    - 这一发现的重要性
    ## 四、风险与不确定性
    - 列出 2-4 条需进一步验证的点，避免过度强调不足
    ## 五、资料来源评估
    简要说明:
    - 主要依赖哪些类型的来源及可信度 (官方文件/学术研究/媒体报道/第三方调研)
    ## 六、参考资料
    列出你在报告中实际引用的数据或观点的来源（如：网站名称、报告名称、或具体URL）。必须严格基于【研究资料】中提供的信息，禁止编造。
    - 参考资料应加上中文注释，格式如下:
    * https://www.xx.html  中华人民共和国xx公报
    * https://www.yy.com   美国国家战略xx白皮书
    ## 用户对话历史
    {history_str}
    ---
    ## 研究资料
    {full_context_str}
    ---
    **重要提醒**: 
    - 不要编造任何数据、来源或引文
    - 若个别点资料不足，可简要提示“仍需验证”
    - 引用数据时尽量保留原始来源线索 (如"据商务部统计"、"胡润研究院报告显示")
    - 深度分析部分建议总字数 1500-2000 字，避免过于简略
    """
    message = [SystemMessage(content=sys_prompt)]
    try:
        response = await llm.ainvoke(message)
        logger.success("✅ [Writer] 报告撰写完成")

        global_rag_store.clear_session(session_id)
        logger.info(f"🧹 [Writer] 任务完成，清理 Session: {session_id}")

        return {
            "messages":[response]
        }
    # AI的api可能会拒绝生成内容，需要做防护
    except openai.BadRequestError as e:
        # 捕获 llm 的内容风控错误
        err_dict = e.body or {}
        if "Content Exists Risk" in str(err_dict):
            logger.error(f"🚫 [Writer] 触发内容风控，内容无法生成")
            # 告知风控
            msg = "⚠️ 抱歉，由于内容安全策略，我无法生成关于该主题的详细报告。请尝试更换关键词。"
            return {
                "messages":[AIMessage(content=msg)]
            }
        else:
            logger.error(f"❌ API 请求错误: {e}")
            msg = f"❌ API 请求错误: {e}"
            return {
                "messages": [AIMessage(content=msg)]
            }
    except Exception as e:
        logger.error(f"❌ 未知错误: {e}")
        msg = f"⚠️ 系统运行异常，请检查日志。错误详情: {str(e)}"
        return {
            "messages": [AIMessage(content=msg)]
        }

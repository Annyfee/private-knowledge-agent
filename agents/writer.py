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
    当前日期：{datetime.now().strftime("%Y-%m-%d")}
    ## 核心原则
    1. **证据优先**: 每个重要判断都必须有资料支撑。如果资料不足，明确说明"现有证据不足以支持更强结论"
    2. **区分事实与推断**: 清楚区分"资料中的事实"和"你的分析推断"
    3. **展现思考过程**: 不仅说"是什么"，还要说"为什么重要"、"有什么限制"
    4. **主动评估证据质量**: 对关键数据，简要说明来源可信度 (如：官方统计 > 学术研究 > 媒体报道 > 未验证数据)
    ## 分析框架 (按此思考，但不必机械套用)
    - **现象层**: 发生了什么？数据呈现什么趋势？
    - **机制层**: 背后的驱动因素是什么？(政策/市场/技术/结构变化)
    - **影响层**: 对各方利益相关者意味着什么？
    - **边界层**: 结论的适用范围和不确定性在哪里？
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
    - 资料局限或不确定性
    ## 四、风险与不确定性
    - **较稳健的判断**: 列出证据充分的结论 (3-5 条)
    - **需谨慎的判断**: 列出依赖有限资料或存在争议的推断 (2-4 条)
    - **关键未知**: 指出还需要哪些数据才能做出更强判断
    ## 五、资料来源评估
    简要说明:
    - 主要依赖哪些类型的来源 (官方文件/学术研究/媒体报道/第三方调研)
    - 证据链的主要缺口在哪里
    ## 六、参考资料
    列出实际引用的来源链接 (必须真实存在于研究资料中)
    ---
    ## 用户对话历史
    {history_str}
    ---
    ## 研究资料
    {full_context_str}
    ---
    **重要提醒**: 
    - 不要编造任何数据、来源或引文
    - 如果某个子课题的资料明显不足，在报告中说明而非强行展开
    - 引用数据时尽量保留原始来源线索 (如"据商务部统计"、"胡润研究院报告显示")
    - 深度分析部分建议总字数 800-1500 字，避免过于简略
    """
    message = [SystemMessage(content=sys_prompt)]
    try:
        response = await llm.ainvoke(message)
        logger.success("✅ [Writer] 报告撰写完成")

        global_rag_store.clear_session(session_id)
        logger.info(f"🧹 [Writer] 任务完成，清理 Session: {session_id}")

        return {
            "final_answer":response.content,
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
                "final_answer":msg,
                "messages":[AIMessage(content=msg)]
            }
        else:
            logger.error(f"❌ API 请求错误: {e}")
            msg = f"❌ API 请求错误: {e}"
            return {
                "final_answer":msg,
                "messages": [AIMessage(content=msg)]
            }
    except Exception as e:
        logger.error(f"❌ 未知错误: {e}")
        msg = f"⚠️ 系统运行异常，请检查日志。错误详情: {str(e)}"
        return {
            "final_answer":msg,
            "messages": [AIMessage(content=msg)]
        }

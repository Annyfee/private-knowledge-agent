# streamlit前端ui

import streamlit as st

def setup_page():
    # 页面基础配置
    st.set_page_config(
        page_title="深度搜索智能体",
        page_icon="🔎",
        layout="wide",
        initial_sidebar_state="expanded" # 初始侧边栏展开
    )

    # CSS美化
    st.markdown("""
    <style>
        /* 聊天气泡样式 */
        .stChatMessage {
            padding: 1.5rem;
            border-radius: 12px;
            margin-bottom: 1rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        }
        /* 状态容器样式 (显示工具调用) */
        [data-testid="stStatusWidget"] {
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            background-color: #f9f9f9;
        }
    </style>
    """,unsafe_allow_html=True) # 允许渲染

def render_sidebar(status):
    new_chat_clicked = False
    # 侧边栏
    with st.sidebar:
        st.header("🔬 研究控制台")
        st.caption(f"Session ID:{st.session_state.session_id}")

        # 检测后端联通
        if status["backend_online"]:
            st.success("🟢 后端服务在线")
            if status["mcp_online"]:
                st.success("🟢 MCP服务在线")
            else:
                st.warning("⚪ MCP服务未启动 （可能是协议不匹配或暂时无响应）")
        else:
            st.error("🔴 后端服务离线(请启动docker)")

        st.divider()

        # 历史记录管理
        col1, col2 = st.columns(2)  # 侧边栏分两列
        with col1:
            if st.button("🧹 新对话", use_container_width=True):
                new_chat_clicked = True
        st.info("""
        **架构说明**：
        - **Frontend**: Streamlit (UI/交互)
        - **Backend**: FastAPI + LangGraph (Docker容器)
        - **Protocol**: HTTP + SSE 流式传输
        """)
        return new_chat_clicked

def render_header():
    # 主界面:渲染历史消息
    st.title("🔎 Deep Research Agent")
    st.caption("基于 LangGraph 多智能体架构 | Docker 容器化部署")

def render_history():
    # 遍历历史记录并将其渲染
    for msg in st.session_state.message:
        role = "user" if msg["role"] == "user" else "assistant"
        avatar = "👤" if role == "user" else "🤖"

        with st.chat_message(role, avatar=avatar):
            # 有工具日志，则渲染
            if "tools" in msg and msg["tools"]:
                with st.status("✅ 历史思考过程", state="complete", expanded=False) as status:
                    with status.expander("**📋 研究任务拆解:**", expanded=True):
                        st.json(msg["tasks"])  # 在 status 内显示
                    for tool in msg["tools"]:
                        st.write(f"🔨 调用工具: **{tool['name']}**")
                        with status.expander("查看参数详情:"):
                            st.json(tool['input'])

            # 再渲染正文
            st.markdown(msg["content"])
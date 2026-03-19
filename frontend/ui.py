import streamlit as st


def setup_page():
    st.set_page_config(
        page_title="私域知识洞察引擎",
        page_icon="🗂️",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    st.markdown("""
    <style>
        .stChatMessage {
            padding: 1.5rem;
            border-radius: 12px;
            margin-bottom: 1rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        }
        [data-testid="stStatusWidget"] {
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            background-color: #f9f9f9;
        }
    </style>
    """, unsafe_allow_html=True)


def render_sidebar(status):
    new_chat_clicked = False
    with st.sidebar:
        st.header("🗂️ 知识控制台")
        st.caption(f"Session ID:{st.session_state.session_id}")

        # 【新增】手动刷新状态按钮，解决启动慢半拍的问题
        col_a, col_b = st.columns([4, 1])
        with col_a:
            st.markdown("**服务监控**")
        with col_b:
            if st.button("🔄", help="刷新服务状态"):
                st.rerun()

        if status["backend_online"]:
            st.success("🟢 后端引擎在线")
            if status["mcp_online"]:
                st.success("🟢 私有知识库(MCP)就绪")
            else:
                st.warning("⚪ 知识库挂载中 (可点击🔄刷新)")
        else:
            st.error("🔴 引擎离线 (请检查Docker)")

        st.divider()

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🧹 新对话", use_container_width=True):
                new_chat_clicked = True

        st.info("""
        **系统特性**：
        - 🔒 **隐私安全**：100% 本地环境断网运行
        - 📚 **私域底座**：自动解析 `data/` 目录文档
        - 🧠 **双核驱动**：支持全文精读与 RAG 语义检索
        """)
        return new_chat_clicked


def render_header():
    st.title("🕵️ Private Knowledge Agent")
    st.caption("基于 LangGraph 架构 | 企业级私域数据洞察引擎")


def render_history():
    for msg in st.session_state.message:
        role = "user" if msg["role"] == "user" else "assistant"
        avatar = "👤" if role == "user" else "🤖"

        with st.chat_message(role, avatar=avatar):
            if "tools" in msg and msg["tools"]:
                with st.status("✅ 历史思考过程", state="complete", expanded=False) as status:
                    tasks = msg.get("tasks", [])
                    if tasks:
                        with status.expander("**📋 知识库检索策略:**", expanded=True):
                            st.json(msg["tasks"])
                    for tool in msg["tools"]:
                        st.write(f"🔨 调用工具: **{tool['name']}**")
                        with status.expander("查看参数详情:"):
                            st.json(tool['input'])

            st.markdown(msg["content"])
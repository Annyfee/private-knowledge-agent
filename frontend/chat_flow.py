import streamlit as st
from backend_client import stream_from_backend


def handle_chat_turn(prompt):
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)
    st.session_state.message.append({"role": "user", "content": prompt})

    with st.chat_message("assistant", avatar="🤖"):
        status_placeholder = st.empty()
        with status_placeholder.container():
            status_container = st.status("🤔 Agent正在思考...", expanded=True)
        response_placeholder = st.empty()
        full_response = ""
        tool_logs = []
        tasks_logs = []

        is_research = False
        shown_waiting_text = False
        is_error = False

        for data in stream_from_backend(prompt, st.session_state.session_id):
            content = data.get("content", "")
            event_type = data.get("type", "")

            if event_type == "phase":
                phase = data.get("phase", "")
                phase_map = {
                    "planning": "🧭 正在规划阅读策略...",
                    "researching": "📂 正在翻阅本地资料库...",
                    "writing": "✍️ 正在提炼核心观点..."
                }
                msg = phase_map.get(phase, "")
                if msg:
                    status_container.info(msg)
                continue

            elif event_type == "token":
                if content:
                    full_response += content
                    response_placeholder.markdown(full_response)
                continue

            elif event_type == "tool_start":
                if not shown_waiting_text:
                    response_placeholder.markdown("正在深入比对本地文档，请耐心等待...")
                    shown_waiting_text = True
                is_research = True
                tool_name = data.get("tool", "unknown_tool")
                tool_input = data.get("input", {})
                tool_logs.append({"name": tool_name, "input": tool_input})
                status_container.write(f"🔨 调用工具:**{tool_name}**")
                with status_container.expander(f"⚙️ 展开{tool_name}底层参数"):
                    st.json(tool_input)
                continue

            elif event_type == "tasks":
                tasks = data.get("tasks", [])
                if tasks:
                    with status_container.expander("**📋 知识库检索策略:**", expanded=True):
                        st.json(tasks)
                tasks_logs.append(tasks)
                continue

            elif event_type == "error":
                st.error(f"后端错误:{data.get('content', '未知错误')}")
                status_container.update(label="❌ 生成失败", state="error", expanded=False)
                is_error = True
                break

            elif event_type == "done":
                break

        if not is_error:
            if is_research:
                status_container.update(label="✅️ 洞察报告生成完毕", state="complete", expanded=False)
            else:
                status_placeholder.empty()

        if not full_response or not full_response.strip():
            full_response = "未在本地库中提取到有效内容，请换个问法。"

        response_placeholder.markdown(full_response) # 确保跳出循环后的文字会被渲染出来

        st.session_state.message.append(
            {"role": "assistant", "content": full_response, "tools": tool_logs, "tasks": tasks_logs}
        )
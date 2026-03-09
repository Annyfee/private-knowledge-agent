# 处理对话时逻辑
import streamlit as st
from backend_client import stream_from_backend

def handle_chat_turn(prompt):
    # A.显示用户提问
    with st.chat_message("user",avatar="👤"):
        st.markdown(prompt)
    st.session_state.message.append({"role":"user","content":prompt})

    # B.请求后端并流式显示
    with st.chat_message("assistant",avatar="🤖"):
        # 俩容器:思考中 & 正文
        status_placeholder = st.empty()
        with status_placeholder.container():
            status_container = st.status("🤔 Agent正在思考...",expanded=True)
        response_placeholder = st.empty()
        full_response = ""
        tool_logs = []
        tasks_logs = []

        # 仅由工具事件判断“研究模式”
        is_research = False
        # 等待文本
        shown_waiting_text = False

        # 调用工具函数,接收数据
        for data in stream_from_backend(prompt,st.session_state.session_id):
            content = data.get("content", "")
            event_type = data.get("type","")
            # source = data.get("source","")
            if event_type == "phase":
                phase = data.get("phase","")
                phase_map = {
                "planning": "🧭 正在规划任务...",
                "researching": "🔎 正在检索资料...",
                "writing": "✍️ 正在撰写报告..."
            }
                msg = phase_map.get(phase,"")
                if msg:
                    status_container.info(msg)
                continue
            elif event_type == "token": # 流式输出
                if content:
                    full_response += content
                    response_placeholder.markdown(full_response)
                continue
            elif event_type == "tool_start":
                if not shown_waiting_text:
                    response_placeholder.markdown("正在并发搜索资料中，请耐心等待...")
                    shown_waiting_text = True
                is_research = True
                tool_name = data.get("tool","unknown_tool")
                tool_input = data.get("input",{})
                # 存入工具列表
                tool_logs.append({"name": tool_name, "input": tool_input})
                status_container.write(f"🔨 调用工具:**{tool_name}**")
                with status_container.expander(f"⚙️ 展开{tool_name}底层参数"):
                    st.json(tool_input) # 参数细节
                continue
            elif event_type == "tasks":
                tasks = data.get("tasks", [])  # 默认值改为 []
                if tasks:
                    with status_container.expander("**📋 研究任务拆解:**",expanded=True):
                        st.json(tasks)  # 在 status 内显示
                tasks_logs.append(tasks)
                continue
            elif event_type == "error": # 错误信息
                st.error(f"后端错误:{data.get('content', '未知错误')}")
            elif event_type == "done":
                break

        # 单次回复结束
        if is_research:
            status_container.update(label="✅️ 生成完毕", state="complete", expanded=False)
        else:
            status_placeholder.empty()
        if not full_response or not full_response.strip():
            full_response = "未生成有效内容，请重试。"
        # 最终回复记入历史
        st.session_state.message.append(
            {"role":"assistant","content":full_response,"tools":tool_logs,"tasks":tasks_logs}
        )
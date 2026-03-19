# 处理SSE协议的工具函数
import json
import os
import requests
from urllib.parse import urlparse

_raw_url = os.getenv("BACKEND_URL") or "http://localhost"

# 检测 URL 是否已带端口，没有才补
_parsed = urlparse(_raw_url)
BACKEND_BASE = _raw_url if _parsed.port else f"{_raw_url}:8011"


def stream_from_backend(user_input, session_id):
    """
    连接docker后端，并把复杂的数据流按SSE协议解析成简单的Py对象
    """
    api_url = f"{BACKEND_BASE}/chat"
    try:
        with requests.post(
            api_url,
            json={"message": user_input, "session_id": session_id},
            stream=True,
            timeout=(3, 300)
        ) as response:
            if response.status_code == 429:
                yield {"type": "error", "content": "⚠️ 每小时最多使用6次，请稍后再试"}
                return

            if response.status_code != 200:
                yield {"type": "error", "content": f"服务器报错: {response.status_code}"}
                return

            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode("utf-8")
                    if decoded_line.startswith("data:"):
                        json_str = decoded_line[5:].strip()
                        if not json_str:
                            continue
                        if "[DONE]" in json_str:
                            break
                        try:
                            yield json.loads(json_str)
                        except Exception:
                            pass
    except Exception as e:
        yield {"type": "error", "content": f"连接失败:{str(e)}"}


def check_services_status():
    """检查服务是否在线"""
    status = {
        "backend_online": False,
        "mcp_online": False,
    }
    try:
        r = requests.get(f"{BACKEND_BASE}/service/status", timeout=1.5)
        if r.status_code == 200:
            data = r.json()
            status["backend_online"] = True
            status["mcp_online"] = data.get("mcp_online", False)
        else:
            status["backend_online"] = False
    except Exception:
        status["backend_online"] = False
    return status
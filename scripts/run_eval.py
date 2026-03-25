# run_eval.py
import argparse
import csv
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import requests

DEFAULT_BACKEND = os.getenv("BACKEND_URL", "http://localhost:8011")
DEFAULT_TIMEOUT = 180
CSV_FIELDS = ["id", "type", "tags", "latency_ms", "ok", "answer_ok", "source_ok",
              "error", "misses", "question", "answer"] # CSV文件标头

@dataclass
class Sample:
    id: str
    question: str
    must_include: list[str]  # 必需的关键词
    must_not_include: list[str] # 禁止的关键词
    expected_sources: list[str] # 期望的来源文件
    type: str
    tags: list[str]

def call_chat_sse(backend: str, question: str, timeout_sec: int = DEFAULT_TIMEOUT) -> dict:
    """调用SSE接口并消费"""
    url = f"{backend}/chat"
    payload = {"message": question, "session_id": str(uuid.uuid4())}
    chunks, error = [], ""  # 存储SSE返回的token字段 | 存储错误信息
    start = time.perf_counter()

    try:
        with requests.post(url, json=payload, stream=True, timeout=(5, timeout_sec)) as resp:
            if resp.status_code != 200:
                return {"ok": False, "answer": "", "error": f"http_{resp.status_code}",
                        "latency_ms": int((time.perf_counter() - start) * 1000)}

            for raw in resp.iter_lines(): # 流式处理
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="ignore") # 解码字符，无法解读字符略过
                if not line.startswith("data:"): # 流式格式必须data开头
                    continue
                try:
                    data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue

                if data.get("type") == "token":
                    chunks.append(data.get("content", "")) # 只存储token字段
                elif data.get("type") == "error":
                    error = data.get("content", "unknown_error")
                elif data.get("type") == "done":
                    break

    except Exception as e:
        return {"ok": False, "answer": "".join(chunks).strip(),
                "error": f"request_error:{type(e).__name__}",
                "latency_ms": int((time.perf_counter() - start) * 1000)}

    return {"ok": error == "", "answer": "".join(chunks).strip(),
            "error": error, "latency_ms": int((time.perf_counter() - start) * 1000)}

def eval_answer(sample: Sample, answer: str) -> tuple[bool, bool, list[str]]:
    """
    评估回答质量

    返回:
    answer_ok:内容是否通过规则
    source_ok:来源是否命中
    misses:失败明细列表
    """
    misses, text = [], answer or ""

    for kw in sample.must_include: # 检查必需词
        if kw not in text:
            misses.append(f"missing:{kw}")
    for kw in sample.must_not_include: # 检查禁词
        if kw and kw in text:
            misses.append(f"forbidden:{kw}")

    answer_ok = not misses and bool(text.strip()) # 三合一:有必需词+无禁词+存在

    if sample.expected_sources: # 有明确期望来源
        source_ok = any(src in text for src in sample.expected_sources)
    elif sample.type in {"research", "fact", "compare", "summary"}: # 有
        source_ok = "来源" in text or "source" in text.lower()
    else:
        source_ok = True

    return answer_ok, source_ok, misses

def main():
    parser = argparse.ArgumentParser() # 创建参数解析器
    parser.add_argument("--dataset", default="evals/eval_set.jsonl") # 测试集路径
    parser.add_argument("--out", default="") # 输出结果路径
    parser.add_argument("--backend", default=DEFAULT_BACKEND) # 后端地址
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args()

    ds_path = Path(args.dataset) # 将命令行输入的参数转为py对象|args.xx
    if not ds_path.exists():
        raise FileNotFoundError(f"数据集不存在: {ds_path}")

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out) if args.out else Path(f"evals/results/eval_set_{ts}.csv")

    samples = []
    for line in ds_path.read_text(encoding="utf-8").splitlines(): # 读取文件为字符串后，将其拆分成list[str]
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        samples.append(
            Sample(
            id=item["id"], question=item["question"], # id与question必须存在
            must_include=item.get("must_include", []),
            must_not_include=item.get("must_not_include", []),
            expected_sources=item.get("expected_sources", []),
            type=item.get("type", ""), tags=item.get("tags", []),
            )
        )

    api_ok = answer_ok = source_ok = total_latency = 0 # 接口/回答通过/请求总延时
    out_path.parent.mkdir(parents=True, exist_ok=True) # 创建输出目录

    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS) # 按列的顺序，将字典转换为csv
        writer.writeheader() # 将fieldnames作为第一行写入CSV文件

        # 遍历并批量写入
        for i, s in enumerate(samples, 1):
            ret = call_chat_sse(args.backend, s.question, args.timeout)
            ans_ok, src_ok, misses = eval_answer(s, ret["answer"])

            writer.writerow({
                "id": s.id,
                "type": s.type,
                "tags": ",".join(s.tags),
                "latency_ms": ret["latency_ms"],
                "ok": ret["ok"],
                "answer_ok": ans_ok,
                "source_ok": src_ok,
                "error": ret["error"],
                "misses": ";".join(misses),
                "question": s.question,
                "answer": ret["answer"]
            })

            api_ok += ret["ok"]; answer_ok += ans_ok; source_ok += src_ok
            total_latency += ret["latency_ms"]
            print(f"[{i}/{len(samples)}] id={s.id} ok={ret['ok']} "
                  f"answer_ok={ans_ok} source_ok={src_ok} latency={ret['latency_ms']}ms")

    n = max(len(samples), 1)
    print(f"\n=== SUMMARY ===\n数据集: {ds_path}\n输出:   {out_path}")
    print(f"API 成功率:  {api_ok}/{n} = {api_ok/n:.2%}")
    print(f"回答通过率:  {answer_ok}/{n} = {answer_ok/n:.2%}")
    print(f"来源通过率:  {source_ok}/{n} = {source_ok/n:.2%}")
    print(f"平均延迟:    {int(total_latency/n)} ms")

if __name__ == "__main__":
    main()
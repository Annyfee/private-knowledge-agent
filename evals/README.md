# 评测说明

这个目录用于做工程回归评测，重点验证 Agent 在真实项目中的可用性。

评测主要回答 4 个问题：

1. 接口能不能稳定返回
2. 回答有没有满足预期约束
3. 回答是否给出了可追溯来源
4. 改动之后表现是变好了还是变差了

---

## 文件说明

- `eval_set.jsonl`：主评测集，适合版本回归和正式对比
- `eval_test.jsonl`：轻量测试集，适合快速验证
- `EVAL_CASE_GUIDE.md`：样本清单，说明每条题目的能力目标和预期来源
- `results/`：评测结果目录，保存每次运行生成的 CSV
- `../scripts/run_eval.py`：评测脚本

---

## 前置条件

运行评测前，需要先确保：

- 后端服务已启动
- `/chat` 接口可访问
- 知识库文件已准备并完成索引
- `BACKEND_URL` 正确，或通过 `--backend` 显式指定

默认后端地址：

```bash
http://localhost:8011
```

---

## 数据集格式

评测集采用 `jsonl` 格式，每行一条样本。当前脚本识别这些核心字段：

- `id`：样本编号
- `type`：场景类型，例如 `research`、`failure`
- `question`：发送给 Agent 的问题
- `must_include`：回答中必须出现的关键词列表
- `must_not_include`：回答中禁止出现的关键词列表
- `expected_sources`：期望在回答里出现的来源文件名列表
- `tags`：标签列表，便于后续统计和筛选

示例：

```json
{
  "id": "research_002",
  "type": "research",
  "question": "请基于本地知识库说明 QUIC 的定位，并明确它和 UDP 的关系。回答末尾请写【来源文件: xxx】。",
  "must_include": ["QUIC", "UDP"],
  "must_not_include": [],
  "expected_sources": ["EVAL_02_quic_transport.txt"],
  "tags": ["research", "quic", "txt"]
}
```

---

## 如何运行

完整评测：

```bash
python scripts/run_eval.py --dataset evals/eval_set.jsonl --timeout 200
```

快速冒烟：

```bash
python scripts/run_eval.py --dataset evals/eval_test.jsonl --timeout 200
```

指定后端地址：

```bash
python scripts/run_eval.py --dataset evals/eval_set.jsonl --backend http://localhost:8011 --timeout 200
```

---

## 输出结果

脚本会产生两类输出：

- 控制台逐题日志
- `evals/results/` 下的结果 CSV

结果文件名示例：

```bash
eval_set_20260325_135831.csv
```

CSV 中会保留这些关键字段：

- `id`
- `type`
- `tags`
- `latency_ms`
- `ok`
- `answer_ok`
- `source_ok`
- `error`
- `misses`
- `question`
- `answer`

---

## 判分逻辑

脚本主要统计 4 个指标：

1. `API 成功率`
是否成功返回 `200`，SSE 是否正常结束，且没有收到 error 事件。

2. `回答通过率`
回答是否满足 `must_include`，同时不包含 `must_not_include`。

3. `来源通过率`
回答中是否出现 `expected_sources` 里的文件名。

4. `平均延迟`
每条样本的平均响应耗时，单位为毫秒。

补充说明：

- 对于配置了 `expected_sources` 的样本，回答里需要出现对应文件名
- 对于没有配置来源但属于 `research` 类的问题，脚本会检查回答中是否显式给出“来源”提示
- `failure` 类样本更关注安全边界和拒答行为

---

## 如何解读结果

建议按下面顺序看结果：

1. 先看 `ok` 和 `error`
如果这里失败，优先排查接口、超时或 SSE 流程问题。

2. 再看 `answer_ok`
如果失败，通常说明召回不足、回答模板不稳定或关键词遗漏。

3. 再看 `source_ok`
如果失败，通常说明回答没有正确暴露来源文件，或者引用了错误来源。

4. 最后看 `latency_ms`
如果延迟明显上升，通常需要回查检索链路、模型调用或重排序开销。

---

## 常见失败类型

- 检索到了内容，但回答没带来源文件名
- 回答方向正确，但漏掉了 `must_include` 的关键词
- 拒答策略不稳，`failure` 样本没有正确拦截
- SSE 超时或异常中断，导致 `ok=False`

---

## 使用建议

- 改动检索、提示词或回答模板后，至少跑一次 `eval_test.jsonl`
- 做版本对比时，固定使用 `eval_set.jsonl`
- 不要只看平均分，必须结合 `misses` 和具体回答内容复盘失败样本
- 只有在同一套数据集上重复运行，结果才具备横向可比性

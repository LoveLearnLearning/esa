# 给 Coding Agent 的最终执行提示词

你正在 `LoveLearnLearning/esa` 仓库中工作。

我已经把 `backend/scripts/student_eval/` 放进仓库。你的任务不是重新设计实验，而是：

1. 审核这些脚本与当前仓库 HEAD 是否兼容；
2. 只做必要兼容修复；
3. 实际运行实验；
4. 得到真实数据；
5. 保存完整 raw results；
6. 生成图表和《06》可直接使用的结果摘要。

## 硬性资源限制

完整 ESA 前后端运行时已经占用现有全部 GPU 额度。

因此：

- 禁止启动任何新的本地 LLM；
- 禁止启动第二套 vLLM；
- 禁止下载并加载学生模拟模型；
- 禁止启动本地 Judge 模型；
- Experiment A 必须保持 CPU-only；
- Experiment B 只能通过已经运行中的 ESA API 串行发请求；
- ESA Agent concurrency 必须为 1；
- 默认只做 12 个配对样本（24 次 Agent 请求）；
- 不得影响当前前端 Demo 的正常使用。

## 先检查代码事实

重点核对：

- `backend/agent/learning/student_model.py`
- `backend/agent/learning/learning_state_service.py`
- `backend/agent/learning/evidence_store.py`
- `backend/agent/memories/mastery_store.py`
- `backend/agent/memories/knowledge_graph.py`
- `backend/agent/memories/kg_loader.py`
- `backend/agent/memories/paths.py`
- `backend/core/web/schemas.py`
- `backend/core/web/routers/chat.py`
- `backend/core/web/webAPI.py`

不要根据旧文档覆盖当前代码事实。

## 实验 A

目标：

比较 Hidden Ground Truth weak KPs 与 ESA Student Model 最终 `status == "weak"` 的知识点。

固定 30 个学生：

- weak 10
- medium 10
- strong 10

固定 6 个数据结构知识点：

- 线性表
- 栈
- 队列
- 图
- 深度优先搜索
- 广度优先搜索

使用 `data/questions.json` 的 12 道固定题。

不得临时改题来提高结果。

FAST 规则：

- mastered：2/2 correct
- partial：1/2 correct
- weak：0/2 correct

通过真实 `LearningStateService.record_event()` 写证据。

Experiment A 必须使用临时 DB，不污染生产库。

先跑 3 人 pilot，再跑 30 人。

如果结果不理想，先检查是否是代码 bug；若不是 bug，不得修改阈值、Profile 或题目来美化结果。

## 实验 B

Experiment B 需要 Full ESA 真正读到学习历史，因此 `eval_accounts.py` 会：

- 创建唯一前缀临时账号；
- Full 账号写入与 Profile 一致的学习证据；
- Baseline 账号没有历史证据；
- 两者都通过正在运行的正式 ESA API 请求。

先 `--limit 1`。

确认：

- health 正常；
- Full 和 Baseline 都能返回；
- 前端仍可使用；
- 没有 OOM；
- Full 条件确实能在 Profile/学习工具中看到历史；
- Baseline 确实没有历史。

若发现当前 HTTP 返回结构与 `http_client.py` 不一致，只修解析，不改变实验条件。

然后跑 3 对，再跑 12 对。

## 盲评

不得本地启动 Judge。

运行 `blind_judge_template.py` 后：

1. 不读取 `judge_blind_key.json`；
2. 只基于 `judge_blinded_input.json` 做评分；
3. 每个 A/B 回答按 5 个维度各 0–2：
   - 薄弱点针对性
   - 前置知识处理
   - 难度匹配
   - 教学脚手架
   - 冗余控制
4. 总分 0–10；
5. 生成 `judge_blinded_results.json`；
6. 确认评分文件写完后才能运行 `score_ablation.py` 解盲。

如果你自身不适合充当 Judge，但环境已有外部云 API，可以用外部模型完成；禁止调用本地 ESA 主模型给自己打分。

## 结束前

必须执行：

```bash
python -m backend.scripts.student_eval.cleanup_eval_data --run-id "$RUN_ID" --yes
```

清除 `eval26_<run_id>_` 临时账号、Mastery 和 Evidence。

绝对不能删除其他用户数据。

## 最终必须返回给我

- 实际 git commit
- RUN_ID
- Experiment A 完成数量
- Overall Precision / Recall / F1
- weak / medium / strong F1
- Experiment B 完成配对数量
- Full ESA mean score
- Baseline mean score
- paired difference
- Full win / tie / loss
- 所有失败样本
- 至少 1 个 Full ESA 失败或 Baseline 获胜案例（如果存在）
- 3 张图
- `diagnosis_raw.jsonl`
- `ablation_raw.jsonl`
- `ablation_metrics.json`
- `06_AI补充验证_结果摘要.md`
- 实际总运行耗时
- 明确指出哪些结果可安全写进《06》

禁止捏造任何未跑出的数字。

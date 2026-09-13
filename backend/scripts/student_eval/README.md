# ESA 轻量化虚拟学生效果验证

本目录只服务于比赛《06—效果验证报告》的补充机制验证，不是产品功能。

## 资源约束

- 不启动任何新的本地 LLM / vLLM。
- Experiment A：CPU + 临时 SQLite，0 次 ESA 模型调用。
- Experiment B：复用已经运行的 ESA 后端，默认 12 个配对样本，共 24 次串行 Agent 请求。
- 不使用现有 Demo 学生账号。Experiment B 创建带唯一 `eval26_<run_id>_` 前缀的临时账号，结束后必须清理。
- AI/虚拟学生不计入真实用户数量。

## 固定知识子图

课程：数据结构

- 线性表 → 栈
- 线性表 → 队列
- 线性表 → 图
- 图 + 栈 → 深度优先搜索
- 图 + 队列 → 广度优先搜索

节点和边必须由当前真实 KG 校验，代码不允许静默造节点。

## 推荐运行流程

在仓库根目录执行。

```bash
RUN_ID=comp_20260913

python -m backend.scripts.student_eval.profiles --run-id "$RUN_ID"
python -m backend.scripts.student_eval.run_diagnosis --run-id "$RUN_ID" --students 3
python -m backend.scripts.student_eval.run_diagnosis --run-id "$RUN_ID" --students 30
python -m backend.scripts.student_eval.make_figures --run-id "$RUN_ID"
python -m backend.scripts.student_eval.write_report --run-id "$RUN_ID"
```

到这里 Experiment A 已完成，而且不需要项目主模型。

### Experiment B 前置检查

先确认正在运行的 ESA：

```bash
curl http://127.0.0.1:51024/health
```

然后准备 12 组临时账号与 Full 条件的学习证据：

```bash
python -m backend.scripts.student_eval.eval_accounts --run-id "$RUN_ID"
```

先只跑 1 组：

```bash
python -m backend.scripts.student_eval.run_ablation --run-id "$RUN_ID" --limit 1 --cooldown 5
```

确认前端、后端、GPU 和输出都正常，再跑 3 组：

```bash
python -m backend.scripts.student_eval.run_ablation --run-id "$RUN_ID" --limit 3 --cooldown 5
```

最后跑 12 组：

```bash
python -m backend.scripts.student_eval.run_ablation --run-id "$RUN_ID" --limit 12 --cooldown 2
```

> 注意：`run_ablation.py` 每次会覆盖 `ablation_raw.jsonl`，正式 12 组前确保前面的 pilot 结果无需保留，或复制出去。

### 盲评

```bash
python -m backend.scripts.student_eval.blind_judge_template --run-id "$RUN_ID"
```

产生：

- `judge_blinded_input.json`
- `judge_blind_key.json`

让外部云 LLM 或执行本实验的 AI 只读取 `judge_blinded_input.json`，按照其中 rubric 填写：

`judge_blinded_results.json`

**评分冻结前不得读取 `judge_blind_key.json`。**

再运行：

```bash
python -m backend.scripts.student_eval.score_ablation --run-id "$RUN_ID"
python -m backend.scripts.student_eval.make_figures --run-id "$RUN_ID"
python -m backend.scripts.student_eval.write_report --run-id "$RUN_ID"
```

### 清理 Experiment B 临时账号

确认 raw data 已保存后：

```bash
python -m backend.scripts.student_eval.cleanup_eval_data --run-id "$RUN_ID" --yes
```

必须执行。

## 最终结果

`backend/scripts/student_eval/outputs/<run_id>/`

至少应有：

- `profiles.json`
- `diagnosis_raw.jsonl`
- `diagnosis_metrics.json`
- `ablation_raw.jsonl`
- `judge_blinded_input.json`
- `judge_blinded_results.json`
- `ablation_metrics.json`
- `figures/*.png`
- `06_AI补充验证_结果摘要.md`

## 重要口径

报告可以写：

> 6 名真实目标用户完成实际试用，另构造 30 个认知约束虚拟学生进行补充机制验证。

不能写：

> 共测试 36 名用户。

不能把虚拟学生的结果写成真实学生学习成绩提升。

# ESA 数据集流水线

面向计算机学科的教育 Agent SFT 数据集。基座 Qwen3.5，训练框架 LLaMA-Factory 0.9.4。

## 为什么要有中间表示（IR）

生成器**只产出 IR**，不直接产出训练用 jsonl：

```
seeds/*.yaml  →  generators/*.py  →  data/ir/*.jsonl  →  data/out/*.jsonl
   种子库           程序化展开            中间表示          ShareGPT 训练数据
                  + 真实执行工具
```

好处是工具调用格式还没和后端定死之前就能开工。IR 只记录「调了哪个工具、参数是什么」这个语义事实，渲染层负责翻译成任何目标格式。

## 快速开始

```bash
# 三个计算器的观测值来自后端真实函数，先抓一次（联网下载后端快照，只读不改）
python3 dataset/tools/capture_math_outputs.py

for g in calculators scenarios new_tools negatives external skills_rag tool_errors; do
  python3 dataset/generators/gen_$g.py                              # 生成 IR
done
PYTHONPATH=dataset python3 -m esa.validate dataset/data/ir/*.jsonl  # 校验（必须 0 错误）
PYTHONPATH=dataset python3 -m esa.evalset                           # 先挑评测集（防泄题）
PYTHONPATH=dataset python3 -m esa.split dataset/data/eval/train_ir.jsonl  # 切分 + 渲染
```

自检（五个都必须全绿）：

```bash
python3 dataset/tests/test_validator.py         # 校验器负向测试
python3 dataset/tests/test_fixture_contract.py  # 工具返回结构契约
python3 dataset/tests/test_parser_compat.py     # 后端 parser 兼容性
python3 dataset/tests/test_eval_scoring.py      # 判分逻辑（合成模型，不需要 GPU）
python3 dataset/tests/test_review_ledger.py     # 人工复核闸门
```

## 目录

| 路径 | 内容 |
|---|---|
| `esa/ir.py` | IR 定义、schema 版本指纹 |
| `esa/render.py` | IR → ShareGPT；线上文本预览 |
| `esa/validate.py` | 准入门禁，20+ 项检查 |
| `esa/tools_exec.py` | 工具返回值：三个计算器查真实执行缓存，禁止编造 |
| `esa/fixtures.py` | 学情类工具的测试库，严格复刻后端公式与字段 |
| `esa/split.py` | 按 template_id 整组切分 |
| `esa/evalset.py` / `esa/eval.py` | 评测集构建 / 评测器（predict-score 分离） |
| `esa/review.py` / `seeds/reviewed.yaml` | 人工复核闸门：登记过的样本才进训练集，**只能人手写** |
| `seeds/` | 种子库（人写的部分） |
| `generators/` | 生成器（程序化展开） |
| `tools/capture_math_outputs.py` | 执行后端真实计算器函数，抓观测值入缓存 |
| `docs/后端问题反馈.md` | 给后端的问题清单（每条带 `文件:行号`） |

---

## ⚠️ 格式规范：会议事程.md 的三处错误

以下均已从 LLaMA-Factory 0.9.4 源码核实，**不要照抄会议事程里的第一个示例**。

### 1. 角色标签是 `function_call`，不是 `function`

默认 tag 定义在 `src/llamafactory/data/parser.py:58-64`：

| 语义 | 正确标签 |
|---|---|
| 用户 | `human` |
| 助手 | `gpt` |
| 工具调用 | **`function_call`** ← 会议事程写成了 `function` |
| 工具返回 | `observation` |
| 系统 | `system` |

### 2. `dataset_info.json` 必须声明 `system` 列

会议事程里的版本只声明了 `messages` 和 `tools`，导致所有顶层 `system` 字段被**静默丢弃**（`data/parser.py:81-84`），模型拿不到任何系统提示。正确写法：

```json
"columns": { "messages": "conversations", "system": "system", "tools": "tools" }
```

### 3. 角色顺序是强制的，违规样本被静默跳过

规则在 `data/converter.py:144-177`：

- 偶数下标（0,2,4…）只能是 `human` 或 `observation`
- 奇数下标（1,3,5…）只能是 `gpt` 或 `function_call`
- **总消息数必须是偶数**
- 必须以 `gpt` 结尾

违规只打一行 `logger.warning_rank0` 就跳过整条。**500 条坏数据 = 悄悄少训 500 条，没有任何显式报错。**

合法的链式调用（长度 6）：
```
human → function_call → observation → function_call → observation → gpt
```

并行调用把多个调用放进**同一条** `function_call`，value 写成 JSON 数组（`data/formatter.py:104-108`）。

---

## 训练配置注意事项

| 项 | 值 | 原因 |
|---|---|---|
| `template` | `qwen3` | **不能用 `qwen3_nothink`** —— 它不产出 `<think>`，后端 `StreamOutputParser` 会把整个回答当 reasoning 吐出、正文为空 |
| `enable_thinking` | 保持默认 `true` | ReasoningTemplate 会自动补空 CoT 并计算 loss（`template.py:424-431`），这正是前端解析所依赖的 |
| `cutoff_len` | **≥ 8192** | 默认 2048。32 个工具的 schema 区 + `get_mastery_report` 约 1851 token 的返回，4096 都装不下 |

### 训练时必须核对的一件事

LLaMA-Factory 静默跳过坏样本，所以每次训练都要对数：

```bash
wc -l dataset/data/out/esa_agent_train.jsonl   # 文件行数
# 训练日志里的 num_examples 必须等于这个数，对不上就停下来查
```

---

## 待定项

完整清单见 [`docs/后端问题反馈.md`](docs/后端问题反馈.md)（每条带后端 `文件:行号`）。这里只留和本目录直接相关的：

- **工具调用线上格式**（P0-1）：后端 `parse_output` 用 XML 风格，LLaMA-Factory qwen 模板产出 JSON。跑 `tests/test_parser_compat.py` 看实证。**这个决定不阻塞数据生成** —— ShareGPT 文件本身格式无关。
- **`tool_schemas.json` 应由后端导出**，不是手抄。当前 `schemas/tool_schemas.json` 与后端仓库 `backend/agent/tools/tool_schemas.json` **逐字节一致**（规范化指纹 `749b8a84`，32 个工具），是从仓库取的；根目录那份 16 工具的旧版**已废弃，不要用**。
- ~~**`load_skill` 的 `name` 参数没有 enum**，模型无从得知有哪些技能，必然幻觉。需要后端补。~~
  → **这条是错的，已推翻。** 可用 Skill 索引本来就注入在 system prompt 里（后端 `core/message/build_prompt.py:80`），
  模型看得到有哪些技能，所以 `load_skill` 不需要 enum。这句话曾经写进计划、待办和口头汇报，
  重复了一周才发现，见交接文档 5.7 —— 留着划掉的原文，是为了别人不要重新犯一遍。
- **并行调用的 observation 渲染方式**需要用真 tokenizer 实测确认（`render.py:_tool_result_value`）。在确认之前不生成并行调用样本。

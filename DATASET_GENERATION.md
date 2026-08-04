# ESA Agent 数据集生成方案

> 最后核对：2026-08-04。目标基座为 `Qwen/Qwen3.5-122B-A10B`，训练框架为 LLaMA-Factory。工具名称和参数必须以运行时导出的 Schema 为准。

你的数据集应该分成两部分生成：

1. 教学能力数据：讲概念、解题、苏格拉底式引导、Markdown/LaTeX。
2. Agent 行为数据：判断是否调用工具、选择正确工具、填写参数、根据工具结果回答。

不要把所有样本都做成工具调用，否则模型以后会“逢问必调工具”。

## 一、先确定数据格式

你的项目最适合 LLaMA-Factory 的 ShareGPT 格式：

```json
{
  "conversations": [
    {
      "from": "human",
      "value": "用户问题"
    },
    {
      "from": "gpt",
      "value": "模型答案"
    }
  ],
  "system": "系统提示词",
  "tools": "工具定义"
}
```

工具调用样本需要使用以下角色顺序：

```text
human
function_call
observation
gpt
```

LLaMA-Factory 会根据 `template: qwen3_5` 把结构化数据转换成 Qwen3.5 原生工具调用文本。不要在数据源里手写 `<tool_call>` XML，否则会把训练数据绑定到你现在的正则解析器上。[LLaMA-Factory 数据格式](https://github.com/hiyouga/LlamaFactory/blob/main/data/README.md)

## 二、建议的数据组成

第一版可以做 10,000 条高质量数据：

| 类型                 |  数量 | 目的                  |
| -------------------- | ----: | --------------------- |
| 不调用工具的普通回答 | 3,000 | 防止滥用工具          |
| 概念讲解             | 1,500 | 新名词、知识点讲解    |
| 数学解题             | 1,500 | Markdown、LaTeX、步骤 |
| 单工具调用           | 2,000 | 工具选择和参数生成    |
| 多轮工具调用         |   800 | 工具结果后的继续处理  |
| 缺少参数时追问       |   500 | 防止编造参数          |
| 工具失败处理         |   300 | 错误恢复              |
| 拒绝危险或错误操作   |   400 | 行为边界              |

对于 122B 模型，数据质量比盲目增加数量更重要。建议先做 1,000～2,000 条验证行为是否正确，再扩大到 10,000～30,000 条。

## 三、普通教学数据怎么生成

示例：

```json
{
  "conversations": [
    {
      "from": "human",
      "value": "什么是特征值？我在线性代数试卷上看到了这个词。"
    },
    {
      "from": "gpt",
      "value": "特征值描述的是：一个向量经过线性变换后，方向保持不变，只发生长度缩放。\n\n若\n\n$$\nA\\mathbf{v}=\\lambda\\mathbf{v}\n$$\n\n其中 $\\mathbf{v}\\ne 0$，那么 $\\lambda$ 就是矩阵 $A$ 的一个特征值，$\\mathbf{v}$ 是对应的特征向量。"
    }
  ],
  "system": "你是 ESA，一名帮助学生理解知识点的学习辅助 Agent。回答应准确、清晰，并正确使用 Markdown 和 LaTeX。"
}
```

生成题目时，可以从以下来源组合：

- 课程教学大纲
- 教材目录和知识点
- 公开题库中允许使用的题目
- 教师整理的问题
- 匿名化的真实用户问题
- 由教师模型根据知识点合成的问题

每个知识点至少生成这些变体：

```text
定义是什么
为什么成立
直观含义是什么
举一个例子
与相近概念有什么区别
常见误区是什么
试题里怎么识别
从简单到复杂讲解
学生答案哪里错了
用苏格拉底方式提示
```

## 四、工具调用数据怎么生成

你当前后端已有这些工具类型：

- `web_search`
- `arxiv_search`
- `calculator`
- `math_solver`
- `bitwise_calculator`
- `save_core_memory`
- `get_core_memories`
- `delete_core_memory`
- `recommend_practice`
- `get_mastery_report`
- `record_answer`
- `load_skill`
- 以及 RAG 工具，但你之前说 RAG 不由你负责，可以先不放进数据集。

### 导出当前全部 Tool Schema

所有工具通过 `ToolRegistry` 注册，完整列表位于 `backend.agent.tools.tr.schemas`。建议新增 `backend/scripts/export_tool_schemas.py`：

```python
import argparse
import json
from pathlib import Path

from backend.agent.tools import tr


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("tool_schemas.json"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(tr.schemas, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"exported {len(tr.schemas)} tools to {args.output}")


if __name__ == "__main__":
    main()
```

从仓库根目录运行：

```bash
python -m backend.scripts.export_tool_schemas \
  --output training/tool_schemas.json
```

不要直接在 `tool_register.py` 中导入全局 `tr`，否则容易形成 `tools.py ↔ tool_register.py` 循环导入。每次新增、删除或修改工具后都应重新导出并对训练数据执行 JSON Schema 校验。

### 工具调用样本

```json
{
  "conversations": [
    {
      "from": "human",
      "value": "帮我计算 sin(pi/2) + sqrt(16)"
    },
    {
      "from": "function_call",
      "value": "{\"name\":\"calculator\",\"arguments\":{\"expression\":\"sin(pi/2) + sqrt(16)\"}}"
    },
    {
      "from": "observation",
      "value": "{\"value\":5.0}"
    },
    {
      "from": "gpt",
      "value": "计算结果是 $5$。"
    }
  ],
  "system": "你是 ESA 学习辅助 Agent。需要精确计算时调用适当工具。",
  "tools": "[{\"type\":\"function\",\"function\":{\"name\":\"calculator\",\"description\":\"数学计算器\",\"parameters\":{\"type\":\"object\",\"properties\":{\"expression\":{\"type\":\"string\"}},\"required\":[\"expression\"]}}}]"
}
```

注意：

- `function_call.value` 是 JSON 字符串。
- `tools` 也是序列化后的 JSON 字符串。
- 参数名必须和后端 schema 完全一致。
- `observation` 应模拟工具的真实返回值。
- 最终 `gpt` 回答必须使用工具结果，不能重新编造。

## 五、必须生成“不要调用工具”的负样本

这是 Agent 数据里最容易遗漏的部分。

```json
{
  "conversations": [
    {
      "from": "human",
      "value": "为什么二次函数的图像是抛物线？"
    },
    {
      "from": "gpt",
      "value": "因为二次函数经过平移和伸缩后都可以化为顶点式……"
    }
  ],
  "system": "你是 ESA 学习辅助 Agent。",
  "tools": "[...]"
}
```

即使样本提供了工具，也让模型直接回答。这是在训练“工具选择边界”。

每个工具建议同时准备：

- 应当调用：正样本。
- 不应调用：困难负样本。
- 参数不完整：追问样本。
- 参数格式容易混淆：边界样本。
- 工具返回错误：恢复样本。
- 用户要求越权操作：拒绝样本。

例如记忆工具：

```json
{
  "conversations": [
    {
      "from": "human",
      "value": "我今天有点困。"
    },
    {
      "from": "gpt",
      "value": "那可以先休息一会儿，再安排强度较低的学习任务。"
    }
  ],
  "system": "只有用户明确要求记住，或者信息明显长期稳定时，才能保存核心记忆。",
  "tools": "[save_core_memory 的 schema]"
}
```

这是 `save_core_memory` 的负样本，因为“今天有点困”不是长期信息。

正样本则是：

```json
{
  "conversations": [
    {
      "from": "human",
      "value": "请记住，我更喜欢先看直观例子，再看公式推导。"
    },
    {
      "from": "function_call",
      "value": "{\"name\":\"save_core_memory\",\"arguments\":{\"memory_key\":\"explanation_preference\",\"content\":\"喜欢先看直观例子，再看公式推导\"}}"
    },
    {
      "from": "observation",
      "value": "{\"success\":true}"
    },
    {
      "from": "gpt",
      "value": "记住了。以后讲解时我会先给直观例子，再展开公式推导。"
    }
  ],
  "system": "你是 ESA 学习辅助 Agent。",
  "tools": "[save_core_memory 的 schema]"
}
```

## 六、建议的数据生成流水线

```text
后端工具 schema
       ↓
生成场景模板
       ↓
生成用户问题
       ↓
确定标准决策：调用/不调用/追问
       ↓
生成结构化 function_call
       ↓
执行或模拟 observation
       ↓
生成最终回答
       ↓
自动校验
       ↓
教师模型复核
       ↓
人工抽检
       ↓
去重与训练集切分
```

### 第一阶段：程序化生成场景

不要让教师模型决定所有参数。像下面这些可以程序生成：

```python
{
    "tool": "calculator",
    "user_query": "计算 sqrt(144) + 2^5",
    "arguments": {
        "expression": "sqrt(144) + 2^5"
    },
    "observation": {
        "value": 44
    }
}
```

然后只让教师模型负责：

- 改写不同风格的用户问题。
- 生成自然的最终解释。
- 生成易混淆负样本。
- 判断回答是否清晰。

这样工具参数正确率会明显高于让模型自由生成。

### 第二阶段：执行真实工具

能真实执行的工具尽量真实执行：

```text
calculator
math_solver
bitwise_calculator
get_mastery_report（使用测试数据库）
recommend_practice（使用测试学情）
```

把真实返回值放进 `observation`，不要让教师模型编造工具结果。

网络搜索涉及时间变化，不适合把某一天的搜索结果大规模固化进训练集。主要训练“什么时候搜索、搜索什么关键词、怎样引用结果”，实时事实仍应靠工具获取。

### 第三阶段：教师模型生成最终回答

教师模型输入：

```text
系统规则
用户问题
工具 schema
标准工具调用
真实工具返回值
期望回答风格
```

要求教师只生成最终回答，不允许修改标准工具调用。

## 七、自动校验必须检查什么

每条数据至少检查：

```text
JSON 能否解析
角色顺序是否合法
function_call 是否紧跟 human/gpt 等合法位置
工具名称是否真实存在
arguments 是否符合 JSON Schema
必填参数是否完整
是否包含未知参数
observation 是否能解析
最终回答是否引用工具结果
LaTeX 定界符是否配对
代码块是否闭合
是否包含隐私数据
是否出现重复样本
长度是否超过 cutoff_len
```

还应通过 Qwen3.5 Tokenizer 做最终验证：

```python
tokenizer.apply_chat_template(
    messages,
    tools=tools,
    tokenize=True,
    add_generation_prompt=False,
)
```

只要这一步报错，该样本就不能进入训练集。

## 八、不要直接训练完整思维链

你现在的 `backend/core/utils/parser.py` 会解析 `<think>...</think>`，但训练数据不建议保存教师模型冗长的隐藏推理：

- 容易引入错误推理。
- 数据成本和长度大幅增加。
- 可能让模型输出不必要的长思考。
- 会降低 Agent 工具调用的稳定性。

第一版建议主要训练最终答案和工具调用。LLaMA-Factory 对具备推理能力的 Qwen 模型支持空 CoT，并要求训练与推理的 `enable_thinking` 保持一致。[官方数据说明](https://github.com/hiyouga/LlamaFactory/blob/main/data/README.md)

## 九、训练集切分

建议：

```text
train       90%
validation   5%
test         5%
```

不能简单随机切分相似题目。例如同一个模板：

```text
计算 sqrt(16)
计算 sqrt(25)
计算 sqrt(36)
```

必须整体放进同一个集合，否则测试集会数据泄漏。

最终推荐你先做：

```text
200 条普通问答
200 条概念讲解
200 条数学讲解
300 条正确工具调用
300 条不调用工具的负样本
100 条缺参追问
100 条工具失败与边界情况
```

先用这 1,400 条验证模型行为。确认工具调用率、参数正确率和 parser 兼容性后，再建设大规模数据。

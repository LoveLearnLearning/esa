# ESA Learning Optimization v2 — 修复说明

本版废弃上一版 overlay，针对代码审查发现的“半重构”问题重新收口。

## 已修复 1：CoreMemory 真正改成 Tool 按需读取

### `backend/agent/agent.py`

已删除：

```python
from backend.agent.tools.memory_tools import core_memory
```

以及：

```python
core_context = core_memory.build_context(user_name)
```

`Agent._prepare_run()` 不再读取 CoreMemory，也不再向 `build_system_prompt()` 传 `core_memory`。

### `backend/core/message/build_prompt.py`

`build_system_prompt()` 已删除 `core_memory` 参数，并删除固定的：

```text
# 核心记忆
...
```

分节。

### `backend/agent/memories/core_memory.py`

删除公共方法 `build_context()`。

新增数据层方法：

```python
CoreMemory.search(user_name, query, category=None, limit=5)
```

无相关命中时返回空列表，不回退为全量记忆。

### `backend/agent/tools/memory_tools.py`

新增：

```text
search_core_memories(query, category="", limit=5)
```

普通任务需要历史信息时使用该 Tool；只有用户明确要求“查看你记住了什么”时才使用 `get_core_memories()`。

`isolated` 继续禁止读取，`no_write` 可读但不可写。

### `ProfileBuilder` 旁路也已断开

原代码的 `_build_inferred_patterns()` 会调用 `core_memory.get_all()`，这会让 CoreMemory
虽然不再出现在 `# 核心记忆` 分节，却仍通过 `inferred_patterns` 自动进入 Prompt。

修正版应用时会对现有 `profile_builder.py` 做严格的外科式 patch：

- `ProfileBuilder.__init__` 删除 `core_memory` 依赖；
- `_build_inferred_patterns()` 不再读取 CoreMemory；
- 只从 `ProfileStore(status=active)` 读取已经结构化、可审核的 inferred/confirmed 画像维度；
- `webAPI.py` 同步删除 `core_memory=core_memory`；
- 对应 profile tests 同步迁移。

这样 raw CoreMemory 的唯一读取入口才真正只剩 memory tools。

---

## 已修复 2：Prompt 文案唯一来源

新增并正式接线：

```text
backend/core/message/system.py
backend/core/message/style_tone.py
```

职责现在为：

```text
system.py
  └─ SYSTEM_PROMPT（唯一系统基础提示词）

style_tone.py
  ├─ STYLE_RULES（唯一风格表）
  ├─ TONE_RULES（唯一语调表）
  └─ resolve_style_tone()

build_prompt.py
  └─ 只负责动态组装，不再保存上述副本
```

`build_prompt.py` 中已经不存在：

```python
SYSTEM_PROMPT
_STYLE_RULES
_TONE_RULES
```

并增加测试动态替换 `system.py / style_tone.py` 的内容，验证 `build_prompt.py` 确实读取这两个模块，而不是复制了一份常量。

---

## 已修复 3：删除公共方法后同步所有调用方

新增回归断言：

```python
assert not hasattr(CoreMemory(...), "build_context")
```

以及：

```python
source = inspect.getsource(Agent._prepare_run)
assert "core_memory" not in source
assert "build_context" not in source
assert "core_context" not in source
```

避免以后再次出现“删了实现但调用方仍引用”的问题。

---

## 新增回归测试

- `backend/tests/test_memory_on_demand.py`
- `backend/tests/test_agent_memory_architecture.py`
- 扩展 `backend/tests/test_memory_mode_guards.py`
- 扩展 `backend/tests/test_pedagogy_prompt.py`

本次修复核心定向测试结果：

```text
21 passed
```

另有 ProfileBuilder 外科 patch smoke test：`1 passed`。

测试覆盖：

- CoreMemory 无 `build_context`
- Agent 无 eager CoreMemory read
- Prompt 无 `# 核心记忆` 分节
- Prompt 拆分模块真正接线
- 按需记忆检索有相关性与 limit
- 无匹配不回退全量
- isolated 模式阻止按需检索
- Skill contract / Pedagogy Router / LearningEvidence 原有测试

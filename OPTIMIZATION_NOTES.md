# ESA Learning Engine 优化覆盖包 v2（修正版）

基于 `LoveLearnLearning/esa` 当前架构制作。**本包替代上一版 overlay，不要叠加使用旧包。**

## 核心结构

```text
TaskMode / 用户消息
        ↓
PedagogyRouter
        ↓
Skill
        ↓
Tool
   ┌────┴───────────────┐
   │                    │
Mastery          LearningEvidence
   │                    │
   └────────┬───────────┘
            ↓
       Learner State
```

长期 CoreMemory 与上述学习状态分开：

```text
普通对话
   ↓
不读取 CoreMemory

确实需要历史信息
   ↓
search_core_memories(query, limit)
   ↓
只返回相关少量记忆
```

## v2 重点修复

### 1. CoreMemory 不再常驻 Prompt

- `Agent._prepare_run()` 不再调用 `core_memory.build_context()`。
- `build_system_prompt()` 不再接收 `core_memory` 参数。
- system prompt 不再输出 `# 核心记忆` 分节。
- `CoreMemory.build_context()` 已删除。
- 新增 `CoreMemory.search()` + `search_core_memories` Tool。
- 无匹配时返回空，不允许退化为“全量注入”。
- `ProfileBuilder` 同步删除 `core_memory` 构造依赖，不再通过 `inferred_patterns` 旁路读取 raw CoreMemory。
- 结构化推断画像改为只读取 `ProfileStore(status=active)` 中已持久化的 inferred/confirmed 维度。

### 2. Prompt 模块彻底收口

唯一来源：

- `backend/core/message/system.py`：系统基础提示词
- `backend/core/message/style_tone.py`：风格/语调规则

`build_prompt.py` 只做动态组装，不再维护副本。

### 3. Skill 契约与启动校验

- YAML frontmatter
- `version/category/priority/autoload/triggers/requires_tools/related_skills`
- Skill -> Tool / Skill -> Skill 校验
- Agent 加载 vLLM 前 fail-fast

### 4. Learning Evidence

记录：

- `self_confidence`
- `evidence_reliability`
- `hint_level`
- `attempts`
- `independent`
- recall / explanation / transfer score
- error type / misconception

### 5. Pedagogy Router

确定性第一层路由：显式 TaskMode 优先；工程任务不强制教学脚手架；学习任务选择候选 Skill。

### 6. 新教学 Skill

- `error_diagnosis`
- `progressive_hint`
- `retrieve_first`
- `teach_back`

并重写原有 homework/mastery/recommendation/study-plan 相关 Skill。

### 7. 其他修复

- 暴露缺失的 Mastery Tool
- `isolated/no_write` 长期状态权限边界
- 过滤 `depth=0` 自身节点，不再把目标知识点算成自己的薄弱前置
- 修复 Prompt tuple repr

## 应用

Windows：

```powershell
.\APPLY_WINDOWS.ps1 -RepoRoot "D:\path\to\esa"
```

Linux/macOS：

```bash
bash ./APPLY_LINUX.sh /path/to/esa
```

> 建议使用上面的 APPLY 脚本，不要只拖拽覆盖。`profile_builder.py`、`webAPI.py` 和两份既有 profile 测试会由 `apply_source_refactors.py` 进行严格的外科式 patch；如果你的本地文件结构已经偏离预期，脚本会直接失败而不是静默覆盖。

应用后：

```bash
python -m backend.agent.tools.export_schemas
pytest backend/tests
```

## 本次修复新增回归门槛

必须同时满足：

```text
CoreMemory 没有 build_context
Agent._prepare_run 不引用 core_memory/build_context/core_context
ProfileBuilder 构造函数不再依赖 core_memory，且推断画像不调用 _core_memory
Prompt 不含 # 核心记忆 / 暂无核心记忆
build_prompt.py 不定义 SYSTEM_PROMPT/_STYLE_RULES/_TONE_RULES
system.py/style_tone.py 的修改会直接反映到 build_system_prompt
search_core_memories 无匹配时不回退全量
isolated 禁止长期状态读取
```

定向测试结果：`21 passed`。

完整仓库仍建议在你的实际环境执行一次 `pytest backend/tests`，尤其是你本地若已有尚未 push 的修改时。

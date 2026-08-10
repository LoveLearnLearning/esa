# ESA 工程优化与修复记录

> 最后核对：2026-08-09。本文合并原 `CHANGED_FILES.md`、`FIXED_ISSUES.md`
> 和旧版优化说明，只保留当前代码仍然有效的设计与验证结论。

## Learning Engine v2

学习引擎当前按下面的路径组织：

```text
TaskMode / 用户消息
        ↓
PedagogyRouter
        ↓
Skill → Tool
   ┌────┴───────────────┐
   │                    │
Mastery          LearningEvidence
   │                    │
   └────────┬───────────┘
            ↓
       Learner State
```

### CoreMemory 按需读取

- `Agent._prepare_run()` 不再预读取全部 CoreMemory，也不再把原始记忆常驻注入 Prompt。
- `CoreMemory.build_context()` 已删除，相关历史信息通过
  `search_core_memories(query, category, limit)` Tool 按需检索。
- 无相关命中返回空列表，不回退为全量记忆。
- `isolated` 模式禁止读取长期状态，`no_write` 模式允许读取但禁止写入。
- `ProfileBuilder` 只读取已经结构化、可审核的画像维度，不通过
  `inferred_patterns` 旁路注入原始 CoreMemory。

### Prompt、Skill 与教学状态

- `backend/core/message/system.py` 是系统基础提示词的唯一来源。
- `backend/core/message/style_tone.py` 是风格和语调规则的唯一来源。
- `build_prompt.py` 只负责动态组装，用户画像按不可信数据处理。
- Skill 使用 YAML frontmatter 声明版本、类别、触发词和工具依赖，启动时执行契约校验。
- `LearningEvidence` 记录置信度、可靠性、提示层级、尝试次数、独立完成情况和迁移表现。
- `PedagogyRouter` 优先尊重显式 TaskMode，工程任务不强制套用教学脚手架。

主要实现位于：

- `backend/agent/agent.py`
- `backend/agent/learning/`
- `backend/agent/memories/`
- `backend/agent/tools/`
- `backend/agent/skills/`
- `backend/core/message/`

## 数据完整性与并发修复

2026-08-09 完成 SQLite 和聊天并发边界收口：

- 所有项目 SQLite 连接统一通过 `connect_sqlite()` 创建，每次连接都启用
  `PRAGMA foreign_keys = ON` 和 `busy_timeout`。
- 会话、分组、对话、消息、画像和版本表补齐外键与级联规则。
- V5 迁移原子重建旧表；无法归属的数据写入 `migration_orphans`，不静默删除。
- 对话与分组的用户归属由数据库触发器兜底，禁止跨用户挂载分组。
- 同一对话从“读取历史并写入用户消息”到“推理结束并写入助手消息”全程持有租约。
- SQLite 行租约覆盖多个 Uvicorn worker，本地 keyed lock 降低轮询；心跳、TTL、
  短暂写锁重试保证异常退出后可恢复。
- 不同对话使用不同租约，可继续并行推理。

主要实现位于：

- `backend/core/stores/sqlite_connection.py`
- `backend/core/stores/migrations.py`
- `backend/core/stores/*_store.py`
- `backend/core/web/concurrency.py`
- `backend/core/web/routers/chat.py`
- `backend/tests/test_sqlite_integrity.py`
- `backend/tests/test_chat_concurrency.py`

## 质量门禁

- `requirements.txt` 包含运行时代码直接使用的 `requests`。
- `requirements-dev.txt` 提供不下载 CUDA/vLLM 的 CPU-only 测试依赖。
- `pyproject.toml` 集中管理 pytest、Ruff 和 mypy。
- `Makefile` 提供 `make quality`、`make lint`、`make typecheck` 和 `make test`。
- `.github/workflows/quality.yml` 在 Python 3.10.20 上执行静态检查和测试。
- Web 路由统一位于 `backend/core/web/routers/`，不再保留漂移的旧版副本。

## 五卡双模型与离线上下文压缩

2026-08-10 将第五张 A800 隔离给本机 Qwen3.5-9B 辅助服务：

- 122B 主模型固定使用前 4 张可见 GPU，辅助模型固定使用第 5 张，两个进程拥有独立的
  `CUDA_VISIBLE_DEVICES` 和 Triton 缓存目录。
- 辅助 OpenAI 兼容接口仅监听 `127.0.0.1:51025`，课表文件结构化提取不再占用主模型。
- 认证请求刷新持久化在线时间；显式退出或 5 分钟无活动后，对话进入后台压缩候选集。
- 压缩始终保留最近 8 条原始消息，历史消息从不删除；下一轮主模型上下文由“系统摘要 +
  最近原文”组成。
- 摘要写入前在同一 SQLite 写事务内复核用户仍离线且没有活跃对话租约，避免与新消息竞态。
- 辅助模型不可用只影响课表智能导入和新摘要生成，不阻止主后端启动，已有摘要和原始消息
  仍可正常使用。

主要实现位于：

- `backend/scripts/run_esa_stack.sh`
- `backend/core/services/auxiliary_llm_service.py`
- `backend/core/services/conversation_compression_service.py`
- `backend/core/stores/conversation_summary_store.py`
- `backend/core/stores/user_presence_store.py`

## 最近验证结果

```text
SQLite/并发定向测试：10 passed
其余可运行测试：168 passed, 24 skipped
Ruff：通过
mypy：通过（关键持久化路径）
compileall：通过
git diff --check：通过
```

24 个跳过项依赖仓库外的 MinerU、真实语料或评测数据。当前超算节点上的
Starlette `TestClient` 会卡在 AnyIO blocking portal，`test_profile_api.py` 应继续由
干净 CI 环境验证；线程栈显示卡点发生在进入业务路由之前。

真实 `user.db` 的副本已完成 V5 迁移烟测：外键检查无违规、迁移可重复执行，
一条历史孤儿消息被隔离，其余有效数据均保留。真实数据库未在验证过程中写入。

## 本地验证

```bash
python -m pip install -r requirements-dev.txt
make quality
```

GPU 推理依赖仍由 `requirements.txt` 和集群环境管理，常规质量检查不需要 GPU。

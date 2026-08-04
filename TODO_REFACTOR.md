# 后端代码重构待办清单

> 基于代码质量评估报告，按优先级排序。最后核对：2026-08-04。已修复项标记为 ✅。

---

## 第1梯队（高风险，建议立即执行）

### ✅ ~~1. AST 求值器重复代码~~（已修复）
- **文件**: `calculator.py` / `bitwise_calculator.py`
- **重构**: 抽取 `BaseSafeEvaluator` 基类到 `_base_evaluator.py`

### 2. 删除所有死代码
- **文件**: [main.py](backend/main.py) L1-L77
- **问题**: 约 70 行代码被完全注释掉（占文件 80%+），包括 Agent 初始化、用户登录、对话循环等
- **建议**: 删除所有被注释的代码，git 历史可追溯

### 3. 替换硬编码配置为环境变量
- **文件**: [config.py](backend/core/utils/config.py) L1-L17
- **问题**: `MODEL_PATH`、`DEBUG_MODE`、量化参数、GPU 内存使用率全部硬编码为模块级常量
- **建议**: 使用 `pydantic-settings` 或 `python-dotenv` 管理配置

### 4. 数据库操作添加异常处理
- **文件**: 
  - [core_memory.py](backend/agent/memories/core_memory.py) L88-L114 `set()`
  - [core_memory.py](backend/agent/memories/core_memory.py) L136-L155 `get()`
  - [core_memory.py](backend/agent/memories/core_memory.py) L176-L194 `get_all()`
  - [core_memory.py](backend/agent/memories/core_memory.py) L209-L222 `delete()`
  - [core_memory.py](backend/agent/memories/core_memory.py) L232-L241 `clear()`
  - 以及 `mastery_store.py`、`stores/*` 中所有数据库操作
- **问题**: 所有 SQLite 操作均无 `try-except`，数据库文件损坏或并发写入冲突时会静默崩溃
- **建议**: 使用 `try-except sqlite3.Error` 包裹所有数据库操作

---

## 第2梯队（中风险，建议本周内执行）

### ✅ ~~5. ToolRegistry 错误处理改进~~（已修复）
- **文件**: [tool_register.py](backend/agent/tools/tool_register.py) L73-L80
- **结果**: 当前仅捕获 `ValueError`、`TypeError` 和 `RuntimeError`，不再盲目捕获 `Exception`

### ✅ ~~6. 修复 auth_service ValueError 未捕获~~（已修复）
- **文件**: [auth_service.py](backend/core/services/auth_service.py) L125-L129
- **结果**: `auth.py` 已捕获该 `ValueError` 并转换为 `400 Bad Request`；修改成功后撤销用户全部会话

### 7. 修复 SessionPrincipal 默认值问题
- **文件**: [models.py](backend/core/utils/models.py) L67-L68
- **问题**: `expires_at` 默认值与 `issued_at` 相同，直接构造会创建立即过期的 session
- **建议**: `expires_at` 默认工厂应设为 `issued_at + timedelta(hours=2)`

### 8. 模块内部 import 导致性能开销
- **文件**: [tools.py](backend/agent/tools/tools.py) L72
- **问题**: `get_time()` 函数内 `from datetime import datetime`，每次调用都执行 import
- **建议**: 移到文件顶部 import

---

## 第3梯队（低风险，迭代中优化）

### 9. 简化为 PromptConfig
- **文件**: [build_prompt.py](backend/core/message/build_prompt.py) L48-L57
- **问题**: `build_system_prompt()` 8 个参数全是 `str | None`，调用方需记住每个参数含义
- **建议**: 引入 `PromptConfig` dataclass 封装参数

### 10. RAG 系统单例模式不规范
- **文件**: [retriever.py](backend/agent/rag/retriever.py) L280-L304
- **问题**: 手动实现单例，线程不安全，`config` 参数只在首次调用生效
- **建议**: 使用 FastAPI `app.state` 或 `functools.lru_cache`

### 11. LLMProvider 缺乏资源管理
- **文件**: [vllm_service.py](backend/core/services/vllm_service.py) L45-L46
- **问题**: 初始化即加载模型，无 `__aenter__`/`__aexit__` 上下文管理器
- **建议**: 实现 `AsyncContextManager` 协议

### 12. ChatStore 迁移代码混在业务逻辑中
- **文件**: [chat_store.py](backend/core/stores/chat_store.py) L50-L61
- **问题**: `is_visible` 列迁移检查每次启动都执行，不可扩展
- **建议**: 使用简单版本化迁移机制

### 13. ChatStore 事务管理不严谨
- **文件**: [chat_store.py](backend/core/stores/chat_store.py) L227-L259
- **问题**: `executemany` 和 `UPDATE` 隐式事务，部分失败导致数据不一致
- **建议**: 使用显式 `BEGIN/COMMIT/ROLLBACK`

### 14. 移除 RAG mock 实现
- **文件**: 
  - [rag/vectorstore/memory.py](backend/agent/rag/vectorstore/memory.py)
  - [rag/embeddings/simple.py](backend/agent/rag/embeddings/simple.py)
- **问题**: 开发/测试用的 mock 实现仍保留为 fallback 选项
- **建议**: 移除或标记为 `@deprecated`

### 15. 日志系统缺少模块级别控制
- **文件**: [logger.py](backend/core/log/logger.py)
- **问题**: 所有模块日志统一 `DEBUG` 级别，无法按模块调整
- **建议**: 支持通过环境变量或配置文件按模块设置日志级别

### 16. parser.py 文件路径错误
- **文件**: [parser.py](backend/core/utils/parser.py) L1
- **问题**: 文件头注释写的是 `core/agent/utils.py`，与实际路径不符
- **建议**: 修正注释

### 17. 硬编码路径
- **文件**: 
  - [webAPI.py](backend/core/web/webAPI.py) L25: `DB_PATH`
  - [memory_tools.py](backend/agent/tools/memory_tools.py) L15: `MEMORIES_DIR`
  - [mastery_tools.py](backend/agent/tools/mastery_tools.py) L30: `MEMORIES_DIR`
- **建议**: 统一使用配置管理路径

### 18. `get_time` 日期格式问题
- **文件**: [tools.py](backend/agent/tools/tools.py) L74
- **问题**: `strftime("%D-%H:%M:%S")` 中 `%D` 是 `%m/%d/%y`，输出如 `08/01/26-14:30:00`，格式不直观
- **建议**: 使用 `%Y-%m-%d %H:%M:%S`

---

## 统计数据

| 优先级 | 数量 | 预计工作量 |
|--------|------|-----------|
| 第1梯队 | 3 项 | ~3.5h |
| 第2梯队 | 2 项 | ~2h |
| 第3梯队 | 10 项 | ~5h |
| **剩余总计** | **15 项** | **~10.5h** |

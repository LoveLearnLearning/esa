# 在这里 submit 更改

## 2026-07-19 第一次大提交

> 修改人：yyf

完成 Agent 后端基础骨架 让模型能够识别和调用工具 并根据工具结果继续生成回答

### 已实现

- 搭建 Agent 基本执行循环
  - 构建 system user assistant tool 消息
  - 解析模型生成结果
  - 执行模型请求的工具
  - 将工具结果加入上下文并继续推理

- 接入 vLLM 和 Transformers
  - 支持加载和卸载 Qwen 模型
  - 支持向模型传递 tools schema
  - 配置模型采样参数和最大上下文长度

- 实现 `ToolRegistry` 工具注册器
  - 通过装饰器注册工具
  - 汇总已注册工具的 schemas
  - 根据工具名称调用对应函数
  - 捕获工具执行过程中产生的异常

- 添加基础工具
  - `get_weather` 查询模拟天气信息
  - `add_two_nums` 计算两个数字之和
  - `web_search` 通过本地 SearXNG 搜索互联网信息

- 实现模型输出解析
  - 提取 `reasoning`
  - 提取普通文本 `content`
  - 解析一个或多个 `tool_call`
  - 对工具参数进行整数 浮点数 布尔值等基础类型转换

- 添加基础 system prompt 将 Agent 定义为学习辅助 Agent

- 添加日志系统
  - 在终端输出运行日志
  - 将日志写入 `logs/backend.log`
  - 支持日志文件滚动和历史日志保留

### 当前注意事项

- SearXNG 需要运行在 `127.0.0.1:8888`

- SearXNG 的 `settings.yml` 需要启用 JSON 输出格式

  ```yaml
  search:
    formats:
      - html
      - json
  ```

## 2026-07-19 第二次提交

> 修改人：zcx

添加计算器工具 让 Agent 能够安全地执行数学计算

### 已实现

- 添加 `calculator` 计算器工具
  - 支持四则运算 幂运算 取整和取模
  - 支持科学函数 包括三角函数 对数 指数 双曲函数等
  - 支持数学常量 pi e tau inf
  - 兼容数学惯用写法 将 `^` 自动转换为 `**`

- 实现基于 AST 白名单的安全求值器
  - 不使用 `eval()` 防止代码注入
  - 仅允许数值常量 预定义常量 白名单运算符与函数调用
  - 拒绝属性访问 下标 赋值 lambda 等危险 AST 节点

- 完善错误处理
  - 捕获除零错误并返回友好提示
  - 检测 NaN 和无穷大结果
  - 整数值的浮点数自动转为 int 输出
  - 表达式长度限制防止 DoS

### 当前注意事项

- 计算器工具在 `backend/agent/tools/calculator.py` 中实现

- 已在 `backend/agent/tools/__init__.py` 中声明导入 触发工具注册

## 2026-07-19 第三次提交

> 修改人：zcx

添加位运算计算器和符号计算工具 让 Agent 覆盖计算机学科与大学数学全场景

### 已实现

- 添加 `bitwise_calculator` 位运算计算器工具
  - 支持位运算 `&` `|` `^` `~` `<<` `>>`
  - 支持布尔运算 `and` `or` `not`
  - 支持算术运算便于混合表达式如 `0xFF + 1`
  - 支持函数 `bin` `oct` `hex` `int` `abs` `bit_length` `popcount`
  - 支持 `0b` `0o` `0x` 进制前缀
  - 结果自动返回二进制 八进制 十进制 十六进制多进制表示

- 添加 `math_solver` 符号计算工具
  - 支持求导 `diff` 包括高阶求导
  - 支持积分 `integrate` 包括定积分和不定积分
  - 支持极限 `limit` 支持左右极限方向
  - 支持泰勒级数展开 `series`
  - 支持解方程 `solve`
  - 支持化简 `simplify` 展开 `expand` 因式分解 `factor`
  - 支持组合数 `binomial` 排列数 `permutation` 求和 `summation`
  - 基于 sympy 实现符号计算

- 实现安全机制
  - `bitwise_calculator` 使用 AST 白名单求值 不使用 `eval()`
  - `math_solver` 使用 sympy `parse_expr` 配合白名单全局字典 限制可用符号与函数
  - 两个工具均拒绝属性访问 函数调用注入等危险操作
  - 表达式长度限制防止 DoS

### 当前注意事项

- `math_solver` 依赖 sympy 库 已确认环境安装 1.14.0 版本

- 三个计算工具的分工
  - `calculator` 负责数值计算 `^` 表示幂
  - `bitwise_calculator` 负责位运算 `^` 表示异或
  - `math_solver` 负责符号推导如微积分和方程

## 2026-07-22 第四次提交

> 修改人：yyf

添加临时记忆和核心记忆系统 让 Agent 能够保留用户最近的对话内容和长期稳定信息

### 已实现

- 添加 `TempMemory` 临时记忆
  - 按 `user_name` 隔离不同用户的消息
  - 保存 user assistant tool 三种消息
  - 支持获取和清空指定用户的临时记忆
  - 将临时消息转换为适合模型读取的上下文
  - 每个用户最多保留 20 条消息
  - 超过限制时自动删除该用户最早的消息
  - 清理消息时不会影响其他用户

- 添加 `CoreMemory` 核心记忆
  - 使用 SQLite 持久化保存用户长期信息
  - 使用 `user_name` 和 `memory_key` 唯一标识一条记忆
  - 支持新增 更新 查询 删除和清空核心记忆
  - 支持保存记忆分类和创建更新时间
  - 相同 `memory_key` 再次写入时自动更新原有内容
  - 使用参数化 SQL 防止 SQL 注入

- 添加核心记忆 tools
  - `save_core_memory` 保存或更新当前用户的核心记忆
  - `get_core_memories` 查询当前用户的全部核心记忆
  - `delete_core_memory` 删除当前用户的指定核心记忆
  - 支持 profile preference learning project constraint general 六种记忆分类

- 添加用户上下文管理
  - 使用 `ContextVar` 保存当前执行用户
  - Agent 每次运行前设置当前用户名
  - 记忆 tools 不需要模型提供 `user_name`
  - 防止模型通过工具参数访问其他用户的核心记忆
  - 为后续异步和并发请求提供用户上下文隔离基础

- 完善 Agent 记忆接入
  - 每轮运行前读取当前用户的临时记忆和核心记忆
  - 将用户输入和 Agent 最终回答保存到临时记忆
  - 将工具调用结果保存到临时记忆
  - 将两种记忆分别注入 system prompt

- 完善记忆使用规则
  - 只使用与当前问题相关的用户记忆
  - 用户最新要求和已有记忆冲突时使用最新要求
  - 禁止向用户暴露内部记忆结构
  - 禁止编造不存在的用户记忆

- 修正记忆工具实现
  - 使用当前文件位置构建核心记忆数据库路径
  - 移除对程序启动目录和 tools 包 `ROOT_DIR` 的依赖
  - 避免 memory tools 和 tools 包之间产生循环导入
  - 将 `memory_key` 的 schema description 修正为字符串

### 当前注意事项

- 临时记忆只保存在程序内存中 程序退出后会清空

- 核心记忆保存在 `backend/agent/memories/data/core_memory.db`

- 核心记忆只应该保存用户偏好 学习目标 项目信息等长期稳定内容

- 核心记忆不应该保存临时问题 reasoning 工具搜索结果 密码或 token

## 2026-07-22 第五次提交

> 修改人：zcx

添加 arXiv 文献搜索工具 让 Agent 具备学术论文检索能力

### 已实现

- 添加 `arxiv_search` 文献搜索工具
  - 通过 arXiv 公开 API 搜索学术论文
  - 支持按字段搜索 all(全文) title(标题) author(作者) abstract(摘要) category(分类)
  - 支持排序方式 relevance(相关度) lastUpdated(最后更新) submitted(提交时间)
  - 支持升序降序排列
  - 返回结构化信息包括 arXiv ID 标题 作者列表 摘要 PDF链接 发表日期 分类 DOI 期刊引用等
  - 自动从 arXiv URL 提取论文 ID 并去除版本号
  - 最大返回结果限制为 20 条

- 实现网络请求健壮性
  - 429 限流时自动重试 最多 5 次 间隔 10 秒
  - 请求超时自动重试 最多 5 次
  - 请求超时时间 60 秒
  - 设置 User-Agent 头标识
  - XML 解析错误捕获

- 修复 ElementTree 命名空间解析 bug
  - ElementTree 的 Element 对象无子节点时为 falsy
  - 所有 `if elem and elem.text` 改为 `if elem is not None and elem.text`
  - 确保 title author abstract 等文本字段正确解析

### 当前注意事项

- arXiv API 要求请求间隔 3 秒 工具内置重试机制处理限流

- 已在 `backend/agent/tools/__init__.py` 中声明导入

## 2026-07-23 第六次提交

> 修改人：yyf

迁移并适配用户认证服务 存储层从 JSON 全面切换到 SQLite 添加历史对话与聊天记录持久化 Agent 支持多轮对话历史

### 已实现

- 迁移并适配认证服务
  - `AuthService` 提供登录和注册接口
  - `PasswordService` 使用 bcrypt 对密码加盐哈希 不存明文
  - 登录成功签发 2 小时有效期的 `SessionPrincipal` 会话
  - 移除旧项目遗留的 `company_id` 参数
  - 补齐缺失的 `UserStore` `SessionStore` 导入

- 实现 SQLite 存储层 替换原 JSON 文件存储
  - 添加 `BaseSQLiteStore` 基类
    - 统一管理数据库连接 每次操作独立连接并正确关闭
    - 提供 `query_one` `query_all` `execute` 通用方法
    - 自动创建数据目录 子类各自初始化数据表
  - 添加 `UserStore` 用户表
    - `id` 主键 `username` 唯一约束
    - 依靠数据库约束原子地拦截重复注册 避免先查后插的并发竞态
  - 添加 `SessionStore` 会话表
    - 支持创建 查询 注销 清理过期会话
    - 时间统一存 UTC ISO 格式字符串 过期清理为单条 SQL
  - 删除 `BaseJsonStore` 及相关 JSON 存储代码

- 添加 `ChatStore` 聊天记录持久化
  - `conversations` 表保存历史对话列表 按最近更新排序
  - `messages` 表保存对话内消息 兼容 user assistant tool 三种角色
  - 支持创建 查询 重命名 删除对话 删除时级联清理消息
  - 追加消息与刷新对话更新时间在同一事务内完成
  - `get_history` 返回完整消息记录 供前端展示
  - `get_model_messages` 返回纯净模型格式 供多轮对话回放
  - 所有方法返回 dict 可直接被 FastAPI 序列化为 JSON

- Agent 支持多轮对话历史
  - `Agent.run()` 新增 `history` 参数 接收历史消息拼入上下文
  - `run()` 返回本轮新产生的消息 供调用方持久化
  - 持久化的助手消息为解析后内容 不含 reasoning
  - `main.py` CLI 循环接入历史 命令行下支持多轮对话

- 统一注释格式
  - 全部 docstring 对齐 `core_memory.py` 的 `参数: 类型 => 说明` 风格
  - 修正 `password_service.py` 中的拼写错误
  - 修正 `services` 目录迁移后遗留的文件头路径注释

### 当前注意事项

- 用户 会话 聊天记录默认共用一个数据库文件 `data/esa.db` 各自建表 初始化时自动创建

- 后端 web 层尚未实现 `webAPI.py` 待接入 FastAPI 后暴露给前端 通信格式为 JSON

- 多轮对话完整链路 `get_model_messages` 取历史 传入 `Agent.run()` 返回值交给 `append_messages` 存库

- `PasswordService` 依赖 bcrypt 库 部署环境需要安装

- 项目目前没有 requirements.txt 建议后续补充依赖清单

## 2026-07-24 第七次提交

> 修改人：yyf

接入 FastAPI 搭建后端 web 层 完成认证相关接口 打通 注册 登录 登出 完整链路 前后端通信格式定为 JSON

### 已实现

- 调整 `AuthService` 适配 web 层
  - `login` 改为按 `username` 查询用户 与前端登录表单对齐
  - 会话中保存的 `user_id` 仍为用户真实 uuid 供下游归属校验使用
  - `register` 不再由外部传入 `user_id` 改为服务端 `uuid` 生成
  - `register` 返回值从 `bool` 改为 `UserRecord | None` 路由层可直接取新用户信息构造响应

- 搭建 FastAPI 应用骨架 `webAPI.py`
  - 使用 `lifespan` 在启动时装配 `UserStore` `SessionStore` `ChatStore` `AuthService`
  - 所有依赖挂载到 `app.state` 全局复用 不在请求内重复创建
  - 数据库文件统一为 `backend/core/stores/data/user.db`
  - 通过 `include_router` 挂载 auth 路由

- 定义 JSON 通信契约 `schemas.py`
  - 请求模型 `RegisterRequest` `LoginRequest` `SendMessageRequest`
  - 响应模型 `LoginResponse` `MessageOut`
  - 使用 pydantic `Field` 声明校验规则 用户名 1-32 位 密码 8-128 位
  - 校验不通过由 FastAPI 自动返回 422 后端不手写校验逻辑

- 实现会话认证依赖 `deps.py`
  - `get_current_session` 从 `Authorization: Bearer <session_id>` 请求头解析令牌
  - 校验会话存在性和有效期 过期会话顺手 `revoke` 清理
  - 认证失败统一返回 401
  - 业务接口通过 `Depends` 注入 自动拦截未登录请求

- 实现认证路由 `routers/auth.py`
  - `POST /auth/register` 注册 成功 201 用户名重复 409
  - `POST /auth/login` 登录 成功返回 `LoginResponse` 失败 401
  - `POST /auth/logout` 登出 注销当前会话 返回 204
  - 登录失败时 用户不存在 和 密码错误 返回同一文案 避免泄露已注册用户名

- 建立 `API.md` 接口文档 记录全部 endpoint 请求响应格式与错误码 作为前后端对接依据

### 当前注意事项

- web 层依赖 fastapi uvicorn pydantic 部署环境需要安装 启动命令 `uvicorn backend.core.web.webAPI:app --reload`

- CORS 中间件尚未配置 Flutter web 端跨域请求会被浏览器拦截 对接前端前需要加上 `CORSMiddleware`

- `deps.py` 中 401 错误文案为调试用玩笑话 会原样返回给客户端 对接前端前必须替换为正式文案

- `backend/core/stores/data/user.db` 数据库文件被提交进了 git 内含测试用户密码哈希 建议从版本库移除并加入 `.gitignore`

- 聊天相关路由 `routers/chat.py` 尚未实现 对话列表 历史消息 发消息接口待接入 `ChatStore` 与 `Agent`

- 前端登录页密码校验规则为 大于 8 位 与后端 schema 的 8-128 位不一致 且前端对密码做 trim 需要前端调整对齐

## 2026-07-24 第八次提交

> 修改人：zcx

实现 RAG (检索增强生成) 模块基础架构 作为占位组件验证系统流程 为后续自研模型预留扩展接口

### 已实现

- **模块化架构设计**
  - 定义抽象接口 `EmbeddingProvider` `VectorStore` `DocumentLoader`
  - 采用依赖注入模式 核心组件可独立替换
  - 配置化管理 参数集中存放在 `RAGConfig` dataclass

- **文档处理模块**
  - `TextLoader`: 支持 .txt/.md 格式文档加载
  - `TextSplitter`: 固定大小分块 + 智能分隔符识别
  - 保留来源元数据 (文件名、章节、页码)

- **Embedding 实现占位**
  - `SimpleEmbedding`: 使用哈希生成向量 作为占位实现
  - `BGEEmbedding`: 使用 BAAI/bge-small-zh 真实语义向量 (512维)
  - 支持批量向量化 向量维度自动归一化

- **向量存储实现占位**
  - `MemoryVectorStore`: 内存向量存储 测试用 不持久化
  - `FAISSVectorStore`: FAISS 向量存储 支持持久化 L2/IP 相似度计算
  - 相似度检索支持阈值过滤

- **检索策略占位**
  - `BM25Retriever`: BM25 关键词检索 (rank_bm25)
  - `HybridRetriever`: 混合检索 (BM25 + 向量) RRF 融合算法
  - 权重可配置 `bm25_weight` `vector_weight`

- **Agent 工具集成**
  - `retrieve_knowledge`: 从知识库检索相关文档
  - `index_knowledge_base`: 索引文档目录到知识库
  - `get_knowledge_base_stats`: 获取知识库统计
  - `clear_knowledge_base`: 清空知识库
  - 工具已注册到 `ToolRegistry` Agent 可自动调用

- **来源可追溯**
  - 每条检索结果标注来源文档 章节信息
  - 格式化模板可自定义 默认格式 "【来源 1】文件名 · 章节 · 第N页"
  - 满足赛题要求的答案来源标注

- **文档与测试**
  - `RAG_API.md`: 接口文档 包含使用示例和扩展指南
  - `MIGRATION_GUIDE.md`: 自研模型迁移指南 详细步骤与兼容性说明
  - `INSTALL.md`: 依赖安装说明
  - `benchmark.py`: 性能基准测试脚本
  - `test_rag.py`: 功能测试脚本
  - 示例文档: math_basics.txt, python_intro.txt

### 技术决策

- **不使用 LangChain/LlamaIndex 等框架**: 采用底层库直接集成 避免与 Agent 工具注册机制冲突 保持轻量可控
- **默认配置**: BGE Embedding + FAISS 存储 + 混合检索
- **占位性质明确**: SimpleEmbedding 仅用于验证流程 无语义理解能力

### 当前注意事项

- **依赖安装**: 
  ```bash
  pip install sentence-transformers faiss-cpu rank_bm25
  ```

- **当前为占位实现**: 
  - SimpleEmbedding 使用哈希向量 不具备语义理解能力
  - MemoryVectorStore 不持久化 重启后数据丢失
  - 生产环境应使用 BGEEmbedding + FAISSVectorStore

- **后续改进方向**:
  1. 替换为自研 Embedding 模型
  2. 替换为自研向量数据库或优化检索算法
  3. 扩展 PDF/Word 等文档格式支持
  4. 添加知识图谱和用户掌握度模型
  5. 实现个性化题目推荐引擎

- **迁移指引**: 
  - 自研模型只需继承 `EmbeddingProvider` 或 `VectorStore` 抽象类
  - 详细步骤见 `backend/agent/rag/MIGRATION_GUIDE.md`

- **Python 版本兼容性**:
  - 已修复所有 Python 3.9 类型注解兼容性问题
  - 使用 `Optional[Type]` 替代 `Type | None`
  - 使用 `Union[Type1, Type2]` 替代 `Type1 | Type2`

- **命名冲突已解决**:
  - 检索策略目录重命名为 `retrieval_strategies/`
  - 主检索器文件保持 `retriever.py`

- **文件结构**:
  ```
  backend/agent/rag/
  ├── document/           # 文档处理
  ├── embeddings/         # Embedding 实现
  ├── vectorstore/        # 向量存储
  ├── retrieval_strategies/  # 检索策略
  ├── sample_docs/        # 示例文档
  ├── base.py             # 抽象接口
  ├── config.py           # 配置管理
  ├── retriever.py        # 主检索器
  └── rag_tool.py         # Agent 工具注册
  ```

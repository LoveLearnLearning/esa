# 用户风格/语调/自定义指令设置 — 实施计划

## Summary

为用户增加"输出风格 + 语调 + 自定义指令"三项偏好设置,支持在设置界面调用接口编辑,并注入到 Agent 的 system prompt 中生效。本次只做**用户级**(全局生效),不做对话级覆盖。

## Current State Analysis

### 已有基础
- `UserStore` / `UserRecord` 只含 `id / username / password_hash / status` 四字段。
- `build_system_prompt()` 拼接角色 + 记忆 + Skills,不接收任何风格参数。
- `Agent.run()` 调用 `build_system_prompt` 时只传 `user_name / temp_memory / core_memory / skills_context`。
- [chat_store.py:50-61](file:///d:/4github/esa/backend/core/stores/chat_store.py#L50-L61) 已有现成的迁移模式:`PRAGMA table_info` 检查列是否存在 → `ALTER TABLE ADD COLUMN`。
- 认证依赖 `get_current_session`(Bearer token → `SessionPrincipal`),路由模式见 [auth.py](file:///d:/4github/esa/backend/core/web/routers/auth.py)。
- 路由注册集中在 [webAPI.py:65-66](file:///d:/4github/esa/backend/core/web/webAPI.py#L65-L66)。

### 缺失
- users 表无偏好字段;`UserRecord` 无对应字段;无 settings 路由;`build_system_prompt` 无风格参数;前端无设置入口(前端不在本次范围)。

## Decisions(已与用户确认)

| 决策点 | 取值 |
|--------|------|
| 风格枚举 | `concise`(简洁) / `detailed`(详细) / `socratic`(启发式反问) |
| 语调枚举 | `friendly`(友好) / `formal`(严谨) / `encouraging`(鼓励) / `strict`(严厉) |
| 默认值 | 新用户默认 `concise + friendly`,`custom_instruction` 默认空串 |
| 自定义指令长度上限 | 500 字符 |
| 作用域 | 仅用户级(全局生效) |

## Proposed Changes

按 4 层自下而上实施,每层独立可验证。

### 层 1 — 数据层:users 表加 3 列

**文件**:[user_store.py](file:///d:/4github/esa/backend/core/stores/user_store.py)

**改 `_initialize()`**:照搬 [chat_store.py:50-61](file:///d:/4github/esa/backend/core/stores/chat_store.py#L50-L61) 的迁移模式。把当前 `self.execute(CREATE TABLE ...)` 改成 `with self._connect() as connection:` 块,在同一连接里:

1. `CREATE TABLE IF NOT EXISTS users (... 新增 3 列 ...)` — 新库直接建全。
2. `PRAGMA table_info(users)` 取现有列名集合。
3. 对 3 个新列逐个判断:不在集合里就 `ALTER TABLE users ADD COLUMN ...`。

新列定义:
```sql
preferred_style     TEXT NOT NULL DEFAULT 'concise'
preferred_tone      TEXT NOT NULL DEFAULT 'friendly'
custom_instruction  TEXT NOT NULL DEFAULT ''
```

**为何用 `self._connect()` 而非 `self.execute`**:PRAGMA 检查与 ALTER 需在同一连接/事务流里完成,`BaseSQLiteStore.execute` 每次开关一个连接,不适合连续迁移判断。

### 层 2 — Store/Model 层

**文件 1**:[models.py](file:///d:/4github/esa/backend/core/utils/models.py) 的 `UserRecord`

加 3 字段,带默认值,保证 `AuthService.register()` 构造新用户时不破:
```python
preferred_style: str = "concise"
preferred_tone: str = "friendly"
custom_instruction: str = ""
```

**文件 2**:[user_store.py](file:///d:/4github/esa/backend/core/stores/user_store.py)

1. `to_model()`:读 3 个新列赋给 `UserRecord`。
2. `get_by_id()` / `get_by_username()` 的 `SELECT` 补上 3 列。
3. `create()`:INSERT 补上 3 列(用 `user.preferred_style` 等)。
4. 新增方法:
```python
def update_preferences(
    self,
    user_id: str,
    preferred_style: str | None = None,
    preferred_tone: str | None = None,
    custom_instruction: str | None = None,
) -> bool:
    """部分更新用户偏好 只更新非 None 的字段"""
```
实现用动态拼 `SET` 子句 + `execute`。返回 `rowcount > 0`。

### 层 3 — API 层:新建 settings 路由

**文件 1**:[schemas.py](file:///d:/4github/esa/backend/core/web/schemas.py) 加两个模型

```python
class UserSettingsOut(BaseModel):
    preferred_style: str
    preferred_tone: str
    custom_instruction: str

class UpdateSettingsRequest(BaseModel):
    preferred_style: str | None = Field(None)
    preferred_tone: str | None = Field(None)
    custom_instruction: str | None = Field(None, max_length=500)
```

校验枚举值:在路由里用集合校验,非法值返回 400(不用 `Literal`,保持前端可扩展性,校验集中在一处)。

合法集合:
- `preferred_style ∈ {concise, detailed, socratic}`
- `preferred_tone ∈ {friendly, formal, encouraging, strict}`

**文件 2**:新建 `backend/core/web/routers/settings.py`

照 [auth.py](file:///d:/github/esa/backend/core/web/routers/auth.py) 的模式:

```python
router = APIRouter(prefix="/me/settings", tags=["settings"])
CurrentSession = Annotated[SessionPrincipal, Depends(get_current_session)]

VALID_STYLES = {"concise", "detailed", "socratic"}
VALID_TONES = {"friendly", "formal", "encouraging", "strict"}

@router.get("")
def get_settings(request: Request, session: CurrentSession) -> UserSettingsOut:
    # user_store.get_by_id → 取三字段返回

@router.patch("")
def update_settings(
    body: UpdateSettingsRequest,
    request: Request,
    session: CurrentSession,
) -> UserSettingsOut:
    # 1. exclude_unset=True 取仅传入字段
    # 2. 校验枚举 非法抛 400
    # 3. custom_instruction 截断到 500 字符(防御)
    # 4. user_store.update_preferences(...)
    # 5. 重新 get_by_id 返回最新值
```

**文件 3**:[webAPI.py](file:///d:/4github/esa/backend/core/web/webAPI.py)

- 顶部 `from backend.core.web.routers import auth, chat, settings`
- [第 66 行后](file:///d:/4github/esa/backend/core/web/webAPI.py#L66) 加 `app.include_router(settings.router)`

### 层 4 — Prompt 层:build_system_prompt 接入

**文件 1**:[build_prompt.py](file:///d:/4github/esa/backend/core/message/build_prompt.py)

1. `build_system_prompt()` 加 3 参:`preferred_style: str = "concise"` / `preferred_tone: str = "friendly"` / `custom_instruction: str = ""`。
2. 新增内部函数 `_style_rule(style) -> str` 和 `_tone_rule(tone) -> str`,把枚举映射成给 LLM 的具体指令:
   - `concise` → "回答控制在 3 句内,先给结论,不铺陈背景"
   - `detailed` → "完整展开,含背景、步骤、示例"
   - `socratic` → "用反问引导用户思考,不直接给答案"
   - `friendly` → "口语化,可用鼓励性表达"
   - `formal` → "书面语,术语准确,避免口语"
   - `encouraging` → "多肯定用户的进展"
   - `strict` → "直接指出错误,不客套"
3. 在拼好的 prompt 里加一段 `# 输出风格` 把规则和 `custom_instruction`(非空时)拼进去。
4. `custom_instruction` 为空串时不输出该段。

**文件 2**:[agent.py](file:///d:/4github/esa/backend/agent/agent.py) 的 `_prepare_run`

当前 [第 66-71 行](file:///d:/4github/esa/backend/agent/agent.py#L66-L71) 调用 `build_system_prompt` 不传风格。改为接收 `user_preferences` 参数并透传。

`_prepare_run` 签名加 `preferred_style: str / preferred_tone: str / custom_instruction: str` 三参(带默认值),`run` 和 `run_stream` 同步加参并透传给 `_prepare_run`。

**文件 3**:[chat.py](file:///d:/4github/esa/backend/core/web/routers/chat.py)

[第 133 行 `agent.run`](file:///d:/4github/esa/backend/core/web/routers/chat.py#L133) 调用处:`user` 已从 `user_store.get_by_id` 取到([第 113 行](file:///d:/4github/esa/backend/core/web/routers/chat.py#L113)),把 `user.preferred_style / preferred_tone / custom_instruction` 透传给 `agent.run`。

`stream_message` 端点([第 150 行](file:///d:/4github/esa/backend/core/web/routers/chat.py#L150))当前是假数据,本次**不修**,留待 SSE 任务处理。

## Assumptions & Decisions

1. **不引入 `Literal` 类型**:枚举校验集中在 settings 路由,前端扩展不改 schema 类型。
2. **不做对话级覆盖**:仅用户级,按用户确认。
3. **不建独立的 settings_service**:逻辑简单,直接在路由里调 `user_store`,与 `auth.py` 调 `auth_service` 的轻量风格一致;`update_preferences` 放 store 层即可。
4. **`stream_message` 不改**:当前是占位假数据,风格注入等 SSE 实施时统一处理。
5. **前端不在本次范围**:本次只做后端接口,前端设置页另开任务。
6. **`AuthService.register` 无需改**:`UserRecord` 新字段有默认值,现有构造不破。
7. **迁移幂等**:`PRAGMA table_info` 检查保证重复启动不报错。

## Verification

1. **启动验证**:服务能正常启动,老库自动迁移加列(检查 `PRAGMA table_info(users)` 含 3 新列)。
2. **GET 接口**:登录后 `GET /me/settings` 返回 `concise / friendly / ""`。
3. **PATCH 全量**:`PATCH /me/settings` 传三字段,再 GET 确认更新生效。
4. **PATCH 部分更新**:只传 `preferred_tone`,其他两字段保持不变。
5. **枚举校验**:传 `preferred_style="xxx"` 返回 400。
6. **长度校验**:传 `custom_instruction` 超 500 字符返回 422(pydantic `max_length`)。
7. **Prompt 注入**:改完偏好后发一条消息,打印 system prompt 确认风格规则和自定义指令已拼入。
8. **未认证**:不带 Bearer token 访问 `/me/settings` 返回 401。

## 实施顺序(todo-list)

1. 层 1 + 层 2:user_store + UserRecord(迁移 + 字段 + update_preferences)
2. 层 3:schemas + settings 路由 + webAPI 注册
3. 层 4:build_system_prompt + agent 透传 + chat 调用
4. 启动 + 接口自测

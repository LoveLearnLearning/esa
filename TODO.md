# 这里是 TODO List

TODO List 中为待办事项 以及还未实现的功能

## 后端 (Backend)

1. [x] 实现修改密码的接口 *****
2. [x] 实现 SSE 流式输出 **
3. [x] 将 vLLM 同步接口换成异步接口 ****
4. [ ] 实现多模态 增加上传附件的支持 ****
5. [ ] 给搜索引擎的结果做一个 Reranker **
6. [ ] 核心记忆加上限 防止 system prompt 膨胀 **
    - `CoreMemory.build_context` 加 `max_items: int = 20` 参数
    - 超出时按 `updated_at DESC` 截断（`get_all` 已有此排序）
    - 调用方 `agent.py` 使用默认值无需改动
    - 约 10 分钟工作量
7. [ ] 模型不能正确区分 skills 和 tools 的区别

## 前端 (Frontend)

1. [x] 实现模型思考内容的展开与缩略显示
    - 前端已支持响应中的 `reasoning`（兼容 `thinking`）字段
    - 支持思考内容渐进显示、两行缩略和点击展开 Markdown 全文
    - 真正的实时思考输出仍需后端在普通响应或 SSE 中返回该字段
2. [x] 新增“知识点 / 概念讲解”独立板块 ***
    - 用于询问试卷、试题、课件中遇到的陌生名词、新颖概念或知识点
    - 支持直接输入概念，也支持粘贴题目上下文后指定需要解释的部分
    - 讲解内容应包含：通俗定义、正式定义、典型例子、与相近概念的区别、在题目中的使用方式
    - 该能力可以和“讲解一道题”联动，但需要保留独立入口，方便用户不依赖完整题目单独提问
3. [x] 重构首页学习任务卡片的交互 ****
    - “讲解一道题 / 生成复习计划 / 检索我的课件 / 批改作业”等卡片应作为任务模式入口，而不是点击后立即发送一条对话
    - 点击卡片后只选中并高亮对应模式，同时更新输入框提示、所需信息说明和可选的提示词模板
    - 用户补充题目、考试时间、课件关键词或作业内容后，再主动点击发送
    - 允许用户先输入内容再切换任务模式，切换时不得清空已经输入的内容
    - 增加“知识点 / 概念讲解”卡片，并为不同任务模式提供对应的附件提示
4. [x] 前端对接偏好/学情档案设置 ****
    - `models.dart` 加 `UserPreferences` / `UserProfile` 数据类
    - `api_client.dart` 加 `getPreferences` / `updatePreferences` / `getProfile` / `updateProfile` 四个方法
    - `app_state.dart` 加偏好/档案状态字段 + `loadPreferencesAndProfile` / `updatePreferences` / `updateProfile` 方法，登录后自动加载
    - `profile_sheet.dart` 加输出偏好区块（风格三档/语调四档/自定义指令）+ 学情档案区块（开关/专业/年级/教学周）
    - 后端接口已就绪：`GET/PATCH /me/preferences` 和 `GET/PATCH /me/profile`

5. [ ] 前端添加 markdown 代码块代码高亮 然后能够提供编辑和运行代码功能 **
<<<<<<< HEAD
6. [ ] pdf 阅读器功能，能够提供pdf的阅读和标注功能 **
=======
    - [x] Markdown 代码块语法高亮
    - [x] 代码复制、编辑与预览切换
    - [x] 前端运行入口和未配置状态提示
    - [ ] 对接后端隔离代码执行沙箱（不在浏览器内直接执行任意代码）
>>>>>>> refs/remotes/origin/main

---

## 对话分组 + 分组内自定义指令（新功能）

> 完整需求文档（项目全景分析 / 市场调研 / 用户场景 / 交互细节 / 技术方案 / 开发计划）见 [GROUP_FEATURE.md](GROUP_FEATURE.md)

### 后端 (Backend)

1. [ ] 新增 `groups` 表与 `GroupStore`（建表 + 老库迁移） ****
    - 分组字段：名称(≤20 字) / 描述(≤100 字) / 自定义指令(≤500 字) / 可选 style/tone（缺省继承用户级）
    - 分组上限 20 个/用户
2. [ ] `conversations` 表加 `group_id` 列（NULL=未分组）+ 索引（含老库迁移） ****
3. [ ] 分组 CRUD 接口 `GET/POST /groups`、`PATCH/DELETE /groups/{group_id}` ****
    - 归属校验 / 字段校验 / 删除分组时组内对话事务内移回未分组
4. [ ] `POST /conversations` 支持 `group_id`；`PATCH /conversations/{id}` 支持移动分组；列表返回 `group_id` ****
5. [ ] 分组指令注入链路：`build_system_prompt` / `agent.run` / `chat.py` 按对话分组注入 ***
    - 合并顺序：系统基础规则 → 用户级 → 分组级 → 当前消息
    - 无分组或分组无指令时与现状行为一致
6. [ ] 更新 `API.md` 接口文档 *

### 前端 (Frontend)

1. [ ] `models.dart` 新增 `ChatGroup`；`ChatConversation` 加 `groupId` ****
2. [ ] `api_client.dart` 新增 `listGroups` / `createGroup` / `updateGroup` / `deleteGroup` ****
3. [ ] `app_state.dart` 新增 `groups` / `activeGroupId` + 增删改/移动逻辑，登录后加载 ****
4. [ ] `history_drawer.dart` 重构为「分组区 + 时间区」双区列表，"未分组"常驻 ****
5. [ ] 新建分组弹窗、分组行 3-dot 菜单（重命名/编辑指令/删除）、移动分组选择器、删除确认 ****
6. [ ] 分组指令编辑器：0/500 字数统计 + 模板库 + 风格/语调覆盖 **
7. [ ] 增强可选：拖拽归档 / 分组内搜索 / 智能分组建议 *

# 在这里 submit 更改

## 2026-07-19 第一次大提交

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

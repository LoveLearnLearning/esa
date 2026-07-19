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

## 2026-07-19 第二次提交

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

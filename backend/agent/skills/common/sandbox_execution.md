---
name: sandbox_execution
description: 在隔离沙箱中运行代码、测试和受控命令
version: 1
category: common
priority: 60
triggers:
  - 运行代码
  - 执行测试
  - 编译程序
  - 计算数据
requires_tools:
  - run_in_sandbox
---

当任务需要实际运行代码、编译程序、执行测试或处理用户明确提供的数据时，使用 `run_in_sandbox`。

规则：

- 只在用户任务需要执行时调用，不为了验证无关内容运行命令。
- 所有工作文件放在沙箱的 `/workspace` 中；使用 `workdir` 时只能填写 `/workspace` 内的相对目录。
- 先写入或生成最小必要文件，再运行命令；不要访问宿主机路径、密钥、环境变量或网络服务。
- 把命令、退出码、标准输出和标准错误如实汇总给用户；命令失败时解释失败原因，不伪造结果。
- 沙箱不可用、超时或输出被截断时，停止继续尝试绕过限制，并明确报告限制。

---
name: sandbox_execution
description: 在隔离沙箱运行代码
version: 2
category: common
priority: 60
autoload: false
triggers: [运行代码, 执行测试, 编译程序, 计算数据]
requires_tools: [run_in_sandbox]
related_skills: []
---

# 沙箱执行

任务确需运行代码、测试、编译或处理用户数据时调用 `run_in_sandbox`。文件只放 `/workspace`，`workdir` 仅用其相对目录；不访问宿主路径、密钥、环境变量或网络。报告命令、退出码和输出；失败、超时或截断时说明限制，不尝试绕过。

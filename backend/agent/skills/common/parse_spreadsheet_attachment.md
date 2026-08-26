---
name: parse_spreadsheet_attachment
description: 读取电子表格附件
version: 2
category: attachment
priority: 96
autoload: false
triggers: [spreadsheet_attachment]
requires_tools: [parse_spreadsheet_attachment]
related_skills: []
---

# 电子表格附件

确需表格数据时，从系统清单取 `attachment_id`，用包含工作表、字段或范围的 `query` 调用 `parse_spreadsheet_attachment`。区分原值和推断，不补造缺失值。

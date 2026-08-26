---
name: parse_image_attachment
description: 读取图片附件
version: 2
category: attachment
priority: 96
autoload: false
triggers: [image_attachment]
requires_tools: [parse_image_attachment]
related_skills: []
---

# 图片附件

确需图中文字、公式、图表或画面时，从系统清单取 `attachment_id`，用明确 `query` 调用 `parse_image_attachment`。区分可见事实与推断，模糊或失败时不猜。

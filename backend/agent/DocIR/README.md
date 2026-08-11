# DocIR

DocIR 是解析器无关的文档中间表示。它把 MinerU 等解析器给出的内容、结构、资源、可选定位和来源信息整理成一个可校验、可追踪、可由 RAG 稳定消费的快照。

项目中只有一个当前 DocIR contract。内容是否有效不依赖 Page、bbox 或其它空间信息。

## 架构

```text
Parser artifacts
      │
      ▼
MinerU adapter
      │
      ▼
Document
├── source
├── parse_revision
├── enrichment_revisions[] # optional VLM/model-derived audit records
├── elements[]
│   ├── semantic payload
│   ├── locators[]       optional
│   └── provenance[]
├── sections[]
├── pages[]              optional spatial metadata
├── assets[]
├── quality_issues[]
└── validation
      │
      ▼
ChunkBuilder → Index → Retrieval → Agent
```

核心原则：

- `Element` 是主要内容单元。
- 模型 enrichment 不覆盖 parser 原文；派生 Element 通过
  `enrichment_revision_id`、`parent_element_id` 和 `related_asset_ids` 回连来源。
- `Section` 和 Element relation 只表达 parser 明确提供的逻辑结构；缺失关系保持为空。
- `Asset` 表达原文件、parser artifacts 和视觉资源。
- `Locator` 只描述内容在哪里；它不决定内容能否存在。
- `ElementProvenance` 把 Element 回连到 parser artifact、group 和 block。
- `Page` 只在 parser 确实提供页面空间信息时存在。

## 核心对象

### Document

`Document` 直接持有全局有序的 Element、Section、Asset、可选 Page，以及源文件和解析元数据。`pages=()` 是合法状态；此时 `parsed_page_count=0`，`source_page_count` 可以为空。

### Element

当前判别联合类型包括：

| `kind` | 主要语义字段 |
| --- | --- |
| `heading` | `level` |
| `paragraph` | `text` |
| `list` | `ordered`, `items` |
| `table` | `html`, `asset_id` |
| `formula` | `latex`, `asset_id` |
| `figure` | `asset_id`, `structured_content` |
| `code` | `language` |
| `unknown` | `raw_type`, `raw_payload` |

每个 Element 都有 `document_order`；`locators` 和 `provenance` 均可为空。`UnknownElement` 是未识别 parser 类型的保真逃生口，不用于替代已经稳定的语义类型。

### Locator

Locator 是一个小而宽松的定位模型：

```text
Locator
├── locator_id
├── kind
├── container_id / container_index
├── label
├── optional page_id
├── optional bbox / polygon / source_geometry
└── metadata
```

当前 MinerU adapter 使用：

- PDF、PNG、JPG：`kind="page"`，保存真实 page、bbox 和 source geometry。
- DOCX、PPTX、XLSX：`kind="group"`，保存 MinerU 的真实 group 顺序，不生成 Page 或 bbox，也不把 group 臆测成更具体的 slide/sheet 语义。

### Provenance

`ElementProvenance` 保存：

- `artifact_id`
- `json_path`
- `group_index`
- `block_index`
- `source_anchor`

因此可以沿 `Chunk → Element → MinerU middle/content_list_v2 artifact` 回查。

### Page 与空间信息

Page 仍保留 `page_index`、尺寸、可选单位、rotation 和 transform。Page locator 可保留规范化 bbox 与 MinerU 原始坐标。它们是 PDF/Image 的能力，不是所有格式的共同前提。

## MinerU adapter

`load_bundle()` 无损读取 MinerU 的：

- `*_middle.json`
- `*_content_list_v2.json`
- optional `*_content_list.json`
- optional `*_model.json`

`align_page()` 同时支持：

- 有 geometry 时的 type + bbox + text 对齐；
- 双方都没有 geometry 时的 type + text 对齐。

Adapter 不生成虚构 page size、bbox、Page、slide 或 sheet。

MinerU 标题只有在 raw `level` 明确、合法且 middle/V2 一致时才进入
`Section` 层级栈；父章节由这些显式 heading level 和文档顺序确定。缺失、
非法或冲突的 level 保持 `HeadingElement.level=None`，不从字号、编号或版面位置
猜测，并记录质量问题。类似地，MinerU 只标出“跨页续表”却没有提供目标表 ID
时，adapter 保留独立 Element 和 provenance，不把它连接到猜测的上一张表。

真实 fixture 覆盖：PDF、PNG、JPG、DOCX、PPTX、XLSX。六种格式都必须实际完成 `MinerU output → DocIR → Chunk`。

## Assets 与文字

- 原文件和 raw JSON 都通过 Asset 保存相对路径、大小和 SHA-256。
- Table、Formula、Figure 可直接引用视觉 Asset。
- Asset 可通过 `locator_ids` 关联真实定位。
- TextLayer 明确记录 origin、confidence 和 quote eligibility。
- MinerU 无法证明 native/OCR 来源时使用 `native_or_ocr_unverified`。

## RAG contract

ChunkBuilder 只依赖 Element 顺序、Section、Element 类型、文字和角色，不判断源格式。

Chunk Evidence 保存 Element、可选 Locator、Asset、文本层和 span。没有 Locator 的 Element 仍可生成合法 Evidence。Agent citation 根据 Locator 渲染页面或 parser group；没有 Locator 时退化为文档/章节来源，不会构造页码。

## 使用

```python
from pathlib import Path

from backend.agent.DocIR import load_document

document = load_document(Path("artifacts/docir/runs/<run>/<document>/document.json"))
for element in document.elements:
    print(element.document_order, element.kind, element.locators)
```

运行核心回归：

```bash
python -m pytest backend/agent/DocIR/tests backend/agent/rag/chunk/tests backend/agent/rag/tests
```

## 证明边界

- DocIR 校验快照内部身份、顺序、引用、hash、定位和 provenance 一致性。
- DocIR 承接 parser 已提供的信息，但不证明 parser 的语义识别一定正确。
- 视觉 Asset 可追踪不等于已经执行 VLM 或多模态 embedding。
- 对无法确认的 parser 字段语义，应保留 raw provenance，而不是补造数据。

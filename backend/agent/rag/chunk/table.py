# backend/agent/rag/chunk/table.py

"""

这个文件干什么：把 DocIR 表格 HTML 转换为连续的可检索行组。

直白点说就是：把 HTML 表格拆成连续的行组，必要时重复表头，让每个表格 Chunk 单独看也能读懂。

把 DocIR 表格 HTML 转换为连续的可检索行组。
"""

from __future__ import annotations

from html.parser import HTMLParser

from .models import ChunkConfig
from .text import split_text_spans


class _TableHTMLParser(HTMLParser):
    """只提取表格行、单元格和表头身份。"""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[tuple[str, ...], bool]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._header = False
        self._thead_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        tag = tag.lower()
        if tag == "thead":
            self._thead_depth += 1
        elif tag == "tr":
            self._row = []
            self._header = self._thead_depth > 0
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = []
            self._header = self._header or tag == "th"
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"th", "td"}:
            self._finish_cell()
        elif tag == "tr":
            self._finish_row()
        elif tag == "thead" and self._thead_depth:
            self._thead_depth -= 1

    def _finish_cell(self) -> None:
        if self._cell is None or self._row is None:
            return
        self._row.append(" ".join("".join(self._cell).split()))
        self._cell = None

    def _finish_row(self) -> None:
        if self._row is not None and any(self._row):
            self.rows.append((tuple(self._row), self._header))
        self._row = None
        self._cell = None


def parse_table_rows(html: str) -> list[tuple[tuple[str, ...], bool]]:
    """解析 HTML 表格，返回单元格与表头标志。"""

    parser = _TableHTMLParser()
    parser.feed(html)
    parser.close()
    return parser.rows


def table_text_groups(html: str, config: ChunkConfig) -> list[str]:
    """按完整行构造不超过 Chunk 上限的连续文本组。"""

    rows = parse_table_rows(html)
    if not rows:
        return []
    header, data = _separate_header(rows)
    prefix = header if config.repeat_table_header else ""
    if len(prefix) >= config.max_chars:
        data = [prefix, *data]
        prefix = ""
    available = config.max_chars - len(prefix) - (1 if prefix else 0)
    expanded = _split_oversized_rows(data, max(1, available))
    groups = _group_rows(expanded, prefix, config.target_chars)
    output = ["\n".join(([prefix] if prefix else []) + group).strip() for group in groups]
    if any(len(value) > config.max_chars for value in output):
        raise ValueError("表格行组超过 max_chars")
    return output


def _separate_header(
    rows: list[tuple[tuple[str, ...], bool]],
) -> tuple[str, list[str]]:
    """提取连续表头；无显式表头时将第一行视为表头。"""

    rendered = [(" | ".join(cells).strip(), header) for cells, header in rows]
    rendered = [(text, header) for text, header in rendered if text]
    header_count = 0
    while header_count < len(rendered) and rendered[header_count][1]:
        header_count += 1
    if header_count == 0 and rendered:
        header_count = 1
    header = "\n".join(text for text, _ in rendered[:header_count])
    data = [text for text, _ in rendered[header_count:]]
    if not data:
        return "", [header]
    return header, data


def _split_oversized_rows(rows: list[str], available: int) -> list[str]:
    """只在单行本身超过可用空间时切分该行。"""

    output: list[str] = []
    for row in rows:
        if len(row) <= available:
            output.append(row)
        else:
            output.extend(
                text
                for text, _start, _end in split_text_spans(row, available)
            )
    return output


def _group_rows(rows: list[str], prefix: str, target_chars: int) -> list[list[str]]:
    """按目标长度聚合连续行，不重排表格内容。"""

    groups: list[list[str]] = []
    current: list[str] = []
    for row in rows:
        candidate_rows = [*current, row]
        candidate = "\n".join(([prefix] if prefix else []) + candidate_rows)
        if current and len(candidate) > target_chars:
            groups.append(current)
            current = [row]
        else:
            current = candidate_rows
    if current:
        groups.append(current)
    return groups

# backend/agent/rag/document/splitter.py
"""
文本分块器实现

提供文本分块功能，支持：
- 固定大小分块
- 重叠分块
- 保留元数据
"""

from typing import Any

from backend.agent.rag.base import Document, DocumentChunk


class TextSplitter:
    """文本分块器

    将长文本分割成固定大小的块，支持重叠分块以保持上下文连贯性。
    """

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 100,
        length_function: callable = len,
    ):
        """初始化文本分块器

        Args:
            chunk_size: 每个分块的最大字符数
            chunk_overlap: 分块之间的重叠字符数
            length_function: 计算文本长度的函数，默认为 len

        Raises:
            ValueError: 参数不合法
        """
        if chunk_size <= 0:
            raise ValueError(f"chunk_size 必须大于 0，当前值: {chunk_size}")

        if chunk_overlap < 0:
            raise ValueError(
                f"chunk_overlap 不能为负数，当前值: {chunk_overlap}"
            )

        if chunk_overlap >= chunk_size:
            raise ValueError(
                f"chunk_overlap ({chunk_overlap}) "
                f"必须小于 chunk_size ({chunk_size})"
            )

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.length_function = length_function

    def split_text(self, text: str) -> list[str]:
        """分割单段文本

        Args:
            text: 输入文本

        Returns:
            list[str]: 分块列表
        """
        if not text.strip():
            return []

        # 如果文本长度小于分块大小，直接返回
        if self.length_function(text) <= self.chunk_size:
            return [text.strip()]

        chunks: list[str] = []
        start = 0

        while start < len(text):
            # 计算当前分块的结束位置
            end = start + self.chunk_size

            # 如果不是最后一块，尝试在句号、换行等自然边界处分割
            if end < len(text):
                # 查找最近的分隔符
                separator_pos = self._find_separator(text, start, end)
                if separator_pos > start:
                    end = separator_pos + 1

            # 提取分块
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            # 计算下一块的起始位置（考虑重叠）
            start = end - self.chunk_overlap

            # 避免死循环
            if start <= 0:
                start = end

        return chunks

    def split_document(self, document: Document) -> list[DocumentChunk]:
        """分割文档为多个分块

        Args:
            document: 输入文档

        Returns:
            list[DocumentChunk]: 文档分块列表
        """
        text_chunks = self.split_text(document.content)

        chunks: list[DocumentChunk] = []
        current_pos = 0

        for i, chunk_content in enumerate(text_chunks):
            # 计算在原文中的位置
            start_idx = document.content.find(
                chunk_content[:50],  # 用前 50 字符定位
                current_pos,
            )
            if start_idx == -1:
                start_idx = current_pos

            end_idx = start_idx + len(chunk_content)
            current_pos = end_idx

            # 生成分块 ID
            chunk_id = f"{document.source}_chunk_{i}"

            chunk = DocumentChunk(
                content=chunk_content,
                document=document,
                chunk_id=chunk_id,
                start_idx=start_idx,
                end_idx=end_idx,
            )

            chunks.append(chunk)

        return chunks

    def split_documents(self, documents: list[Document]) -> list[DocumentChunk]:
        """批量分割文档

        Args:
            documents: 文档列表

        Returns:
            list[DocumentChunk]: 所有文档的分块列表
        """
        all_chunks: list[DocumentChunk] = []

        for document in documents:
            chunks = self.split_document(document)
            all_chunks.extend(chunks)

        return all_chunks

    def _find_separator(self, text: str, start: int, end: int) -> int:
        """在指定范围内查找分隔符位置

        优先级：句号 > 换行 > 空格

        Args:
            text: 文本
            start: 起始位置
            end: 结束位置

        Returns:
            int: 分隔符位置，未找到返回 end
        """
        # 在 [start, end) 范围内查找
        search_range = text[start:end]

        # 优先找句号
        for sep in ["。", ".", "！", "!", "？", "?"]:
            pos = search_range.rfind(sep)
            if pos != -1:
                return start + pos

        # 其次找换行
        for sep in ["\n\n", "\n", "\r\n"]:
            pos = search_range.rfind(sep)
            if pos != -1:
                return start + pos

        # 最后找空格
        pos = search_range.rfind(" ")
        if pos != -1:
            return start + pos

        # 未找到分隔符，返回原结束位置
        return end
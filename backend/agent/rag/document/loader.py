# backend/agent/rag/document/loader.py
"""
文档加载器实现

提供文本文件的加载功能，支持：
- .txt 文本文件
- 保留来源元数据
"""

from pathlib import Path
from typing import Any, Optional

from backend.agent.rag.base import Document, DocumentLoader


class TextLoader(DocumentLoader):
    """文本文件加载器

    支持 .txt 格式的文本文件加载，提取内容并保留来源信息。
    """

    def __init__(self, encoding: str = "utf-8"):
        """初始化文本加载器

        Args:
            encoding: 文件编码，默认 utf-8
        """
        self.encoding = encoding

    def load(self, file_path: Path) -> Document:
        """加载单个文本文件

        Args:
            file_path: 文本文件路径

        Returns:
            Document: 加载的文档对象

        Raises:
            FileNotFoundError: 文件不存在
            UnicodeDecodeError: 编码错误
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        if not self.supports_format(file_path.suffix):
            raise ValueError(
                f"不支持的文件格式: {file_path.suffix}，"
                f"当前仅支持 .txt 格式"
            )

        # 读取文件内容
        content = file_path.read_text(encoding=self.encoding)

        # 提取元数据
        source = file_path.name

        # 尝试从文件名提取章节信息（可选）
        # 例如: math_chapter1_section2.txt -> chapter1_section2
        section = self._extract_section_from_filename(file_path.stem)

        return Document(
            content=content.strip(),
            source=source,
            section=section,
            metadata={
                "file_path": str(file_path),
                "file_size": file_path.stat().st_size,
            },
        )

    def load_directory(
        self,
        dir_path: Path,
        pattern: str = "*.txt",
    ) -> list[Document]:
        """加载目录下所有文本文件

        Args:
            dir_path: 目录路径
            pattern: 文件匹配模式，默认 *.txt

        Returns:
            list[Document]: 文档列表

        Raises:
            NotADirectoryError: 路径不是目录
        """
        dir_path = Path(dir_path)

        if not dir_path.exists():
            raise FileNotFoundError(f"目录不存在: {dir_path}")

        if not dir_path.is_dir():
            raise NotADirectoryError(f"路径不是目录: {dir_path}")

        documents: list[Document] = []

        # 遍历目录中的所有匹配文件
        for file_path in sorted(dir_path.glob(pattern)):
            if file_path.is_file() and self.supports_format(file_path.suffix):
                try:
                    doc = self.load(file_path)
                    documents.append(doc)
                except Exception as e:
                    # 记录错误但继续加载其他文件
                    print(f"加载文件失败 {file_path}: {e}")
                    continue

        return documents

    def supports_format(self, file_extension: str) -> bool:
        """检查是否支持该文件格式

        Args:
            file_extension: 文件扩展名（如 '.txt'）

        Returns:
            bool: 是否支持
        """
        supported_formats = {".txt", ".text", ".md"}
        return file_extension.lower() in supported_formats

    def _extract_section_from_filename(self, filename: str) -> Optional[str]:
        """从文件名提取章节信息（辅助函数）

        Args:
            filename: 文件名（不含扩展名）

        Returns:
            Optional[str]: 章节信息
        """
        # 简单实现：如果文件名包含 "chapter" 或 "section" 字样，提取出来
        # 例如: math_chapter1 -> chapter1
        filename_lower = filename.lower()

        if "chapter" in filename_lower:
            idx = filename_lower.find("chapter")
            return filename[idx:].replace("_", " ")

        if "section" in filename_lower:
            idx = filename_lower.find("section")
            return filename[idx:].replace("_", " ")

        return None
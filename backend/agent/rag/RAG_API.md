# RAG 模块接口文档

## 概述

RAG（Retrieval-Augmented Generation，检索增强生成）模块为 ESA Agent 提供知识库检索功能。该模块采用模块化设计，支持无缝替换 Embedding 模型和向量存储后端。

## 架构设计

```
backend/agent/rag/
├── __init__.py          # 模块入口
├── base.py              # 抽象接口定义
├── config.py            # 配置管理
├── retriever.py         # 检索器（核心）
├── rag_tool.py          # Agent 工具注册
├── document/            # 文档处理模块
│   ├── loader.py        # 文档加载器
│   └── splitter.py      # 文本分块器
├── embeddings/          # Embedding 模块
│   └── simple.py        # 占位实现
├── vectorstore/         # 向量存储模块
│   └── memory.py        # 内存存储
└── sample_docs/         # 示例文档
    ├── math_basics.txt
    └── python_intro.txt
```

## 核心接口

### 1. 配置类（RAGConfig）

```python
from backend.agent.rag.config import RAGConfig

config = RAGConfig(
    chunk_size=500,           # 文本分块大小（字符数）
    chunk_overlap=100,        # 分块重叠大小
    top_k=5,                  # 检索返回数量
    similarity_threshold=0.5, # 相似度阈值
    embedding_provider="simple",  # Embedding 提供者
    vector_store_type="memory",   # 向量存储类型
)
```

### 2. 检索器（Retriever）

```python
from backend.agent.rag.retriever import Retriever

# 创建检索器
retriever = Retriever(config)

# 索引文档目录
chunk_count = retriever.index_directory("/path/to/docs")

# 检索相关文档
results = retriever.retrieve("什么是极限？", top_k=5)

# 检索并获取完整上下文
context = retriever.retrieve_with_context("什么是极限？")
```

### 3. 抽象接口

#### EmbeddingProvider

```python
from backend.agent.rag.base import EmbeddingProvider

class MyEmbeddingProvider(EmbeddingProvider):
    def embed(self, text: str) -> list[float]:
        """将文本转换为向量"""
        pass

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量向量化"""
        pass

    def get_dimension(self) -> int:
        """获取向量维度"""
        pass
```

#### VectorStore

```python
from backend.agent.rag.base import VectorStore

class MyVectorStore(VectorStore):
    def add(self, chunks: list[DocumentChunk]) -> None:
        """添加文档分块"""
        pass

    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        similarity_threshold: float = 0.0,
    ) -> list[RetrievalResult]:
        """检索相似文档"""
        pass

    def clear(self) -> None:
        """清空向量库"""
        pass

    def count(self) -> int:
        """获取文档数量"""
        pass
```

## Agent 工具接口

RAG 模块注册了 4 个 Agent 工具：

### 1. retrieve_knowledge

从知识库检索相关文档。

**参数：**
- `query`（必需）：查询文本
- `top_k`（可选，默认 5）：返回结果数量
- `similarity_threshold`（可选，默认 0.5）：相似度阈值

**返回：**
```json
{
  "query": "什么是极限？",
  "result_count": 2,
  "results": [
    {
      "content": "极限的定义...",
      "source": "math_basics.txt",
      "section": "第一章 极限与连续",
      "page": null,
      "score": 0.85,
      "rank": 1
    }
  ],
  "sources": [
    "【来源 1】math_basics.txt · 第一章 极限与连续 · 第未知页"
  ],
  "context_text": "..."
}
```

### 2. index_knowledge_base

索引文档目录到知识库。

**参数：**
- `dir_path`（可选）：文档目录路径，默认使用配置路径

**返回：**
```json
{
  "success": true,
  "indexed_chunks": 10,
  "total_chunks_in_store": 10,
  "message": "成功索引 10 个文档分块"
}
```

### 3. get_knowledge_base_stats

获取知识库统计信息。

**返回：**
```json
{
  "total_chunks": 10,
  "embedding_dimension": 128,
  "config": {
    "chunk_size": 500,
    "chunk_overlap": 100,
    "top_k": 5,
    "similarity_threshold": 0.5,
    "embedding_provider": "simple",
    "vector_store_type": "memory"
  }
}
```

### 4. clear_knowledge_base

清空知识库索引。

**返回：**
```json
{
  "success": true,
  "message": "知识库已清空"
}
```

## 使用示例

### 基础使用

```python
from backend.agent.rag import Retriever, RAGConfig

# 创建配置
config = RAGConfig(
    chunk_size=300,
    top_k=3,
)

# 创建检索器
retriever = Retriever(config)

# 索引文档
retriever.index_directory("/path/to/docs")

# 检索
results = retriever.retrieve("查询内容")
for result in results:
    print(f"来源: {result.chunk.document.source}")
    print(f"内容: {result.chunk.content}")
    print(f"相似度: {result.score}")
```

### 自定义 Embedding

```python
from backend.agent.rag import Retriever
from backend.agent.rag.base import EmbeddingProvider
from backend.agent.rag.vectorstore.memory import MemoryVectorStore

# 自定义 Embedding（示例：使用真实模型）
class BGEEmbedding(EmbeddingProvider):
    def __init__(self):
        # 加载 BGE 模型
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer('BAAI/bge-small-zh')

    def embed(self, text: str) -> list[float]:
        return self.model.encode(text).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts).tolist()

    def get_dimension(self) -> int:
        return 512

# 使用自定义 Embedding
retriever = Retriever(
    embedding_provider=BGEEmbedding(),
    vector_store=MemoryVectorStore(),
)
```

### 在 Agent 中使用

Agent 会自动调用 `retrieve_knowledge` 工具，无需手动调用：

```
用户: 请解释一下什么是极限？

Agent: 我将从知识库中查找相关内容。
[调用 retrieve_knowledge 工具]

Agent: 根据知识库内容，极限是高等数学中最基础的概念之一...
【来源 1】math_basics.txt · 第一章 极限与连续 · 第未知页
```

## 扩展指南

### 添加新的文档加载器

```python
# backend/agent/rag/document/pdf_loader.py

from backend.agent.rag.base import Document, DocumentLoader
from pathlib import Path

class PDFLoader(DocumentLoader):
    def load(self, file_path: Path) -> Document:
        # 使用 PyPDF2 或 pdfplumber 提取文本
        import pdfplumber

        with pdfplumber.open(file_path) as pdf:
            content = ""
            for page in pdf.pages:
                content += page.extract_text()

        return Document(
            content=content,
            source=file_path.name,
        )

    def supports_format(self, file_extension: str) -> bool:
        return file_extension.lower() == ".pdf"
```

### 替换为 ChromaDB

```python
# backend/agent/rag/vectorstore/chroma.py

import chromadb
from backend.agent.rag.base import VectorStore, DocumentChunk, RetrievalResult

class ChromaVectorStore(VectorStore):
    def __init__(self, persist_directory: str = "./chroma_db"):
        self.client = chromadb.PersistentClient(path=persist_directory)
        self.collection = self.client.get_or_create_collection("knowledge")

    def add(self, chunks: list[DocumentChunk]) -> None:
        for chunk in chunks:
            self.collection.add(
                ids=[chunk.chunk_id],
                embeddings=[chunk.embedding],
                documents=[chunk.content],
                metadatas=[{
                    "source": chunk.document.source,
                    "section": chunk.document.section,
                }]
            )

    # ... 实现其他方法
```

## 注意事项

1. **当前使用占位 Embedding**：SimpleEmbedding 使用哈希生成向量，不具备语义理解能力。生产环境应替换为 BGE、text2vec 等真实模型。

2. **内存存储限制**：MemoryVectorStore 不持久化，重启后数据丢失。生产环境应使用 ChromaDB 或 FAISS。

3. **来源标注**：赛题要求每条回答必须标注来源，`retrieve_with_context` 方法会自动格式化来源信息。

4. **文档格式**：当前仅支持 .txt 和 .md 格式，需要扩展 PDF 等格式支持。

## 测试

运行测试脚本：

```bash
python -m backend.agent.rag.test_rag
```

## 参考资料

- [ChromaDB 文档](https://docs.trychroma.com/)
- [BGE Embedding 模型](https://huggingface.co/BAAI/bge-small-zh)
- [LangChain RAG 教程](https://python.langchain.com/docs/use_cases/question_answering/)
# RAG 模块迁移指南

## 概述

本文档详细说明如何从当前 RAG 模块迁移至自研模型。系统采用**依赖注入**和**抽象接口**设计，确保替换组件时无需修改核心逻辑。

---

## 当前架构设计

### 模块划分

```
backend/agent/rag/
├── base.py                  # 抽象接口定义
├── config.py                # 配置管理
├── retriever.py             # 核心检索器
├── rag_tool.py              # Agent 工具注册
├── document/                # 文档处理模块
│   ├── loader.py            # 文档加载器
│   └── splitter.py          # 文本分块器
├── embeddings/              # Embedding 模块
│   ├── simple.py            # 占位实现
│   └── bge_embedding.py     # BGE 模型实现
├── vectorstore/             # 向量存储模块
│   ├── memory.py            # 内存存储
│   └── faiss_store.py       # FAISS 持久化存储
└── retriever/               # 检索器模块
    ├── bm25_retriever.py    # BM25 关键词检索
    └── hybrid_retriever.py  # 混合检索（BM25 + 向量）
```

### 核心抽象接口

所有核心组件都通过 `base.py` 中的抽象类定义接口：

1. **EmbeddingProvider**：文本向量化接口
2. **VectorStore**：向量存储与检索接口
3. **DocumentLoader**：文档加载接口

---

## 接口规范

### 1. EmbeddingProvider 接口

```python
from backend.agent.rag.base import EmbeddingProvider

class MyCustomEmbedding(EmbeddingProvider):
    def embed(self, text: str) -> list[float]:
        """
        将文本转换为向量
        
        Args:
            text: 输入文本
            
        Returns:
            list[float]: 固定维度的向量（维度必须与配置一致）
        """
        # 你的实现
        pass
    
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量向量化（可选，默认循环调用 embed）"""
        pass
    
    def get_dimension(self) -> int:
        """
        返回向量维度
        
        Returns:
            int: 向量维度（必须与向量存储配置一致）
        """
        return 768  # 你的维度
```

**输入输出规范：**
- 输入：文本字符串（任意长度）
- 输出：固定维度的浮点数列表
- 要求：向量应归一化，便于余弦相似度计算

---

### 2. VectorStore 接口

```python
from backend.agent.rag.base import VectorStore, DocumentChunk, RetrievalResult

class MyCustomVectorStore(VectorStore):
    def add(self, chunks: list[DocumentChunk]) -> None:
        """
        添加文档分块到向量库
        
        Args:
            chunks: 分块列表，每个 chunk 必须包含 embedding
        """
        # 你的实现
        pass
    
    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        similarity_threshold: float = 0.0,
    ) -> list[RetrievalResult]:
        """
        根据向量检索相似文档
        
        Args:
            query_vector: 查询向量
            top_k: 返回的最大结果数
            similarity_threshold: 相似度阈值
            
        Returns:
            list[RetrievalResult]: 检索结果列表
        """
        # 你的实现
        pass
    
    def clear(self) -> None:
        """清空向量库"""
        pass
    
    def count(self) -> int:
        """返回向量库中的文档数量"""
        return 0
```

**数据结构规范：**
- `DocumentChunk`：包含 content、document（来源）、chunk_id、embedding
- `RetrievalResult`：包含 chunk、score（相似度）、rank（排名）

---

### 3. DocumentLoader 接口

```python
from backend.agent.rag.base import DocumentLoader, Document

class MyCustomLoader(DocumentLoader):
    def load(self, file_path: Path) -> Document:
        """
        加载单个文档
        
        Args:
            file_path: 文档路径
            
        Returns:
            Document: 文档对象，包含 content、source、section 等
        """
        # 你的实现
        pass
    
    def supports_format(self, file_extension: str) -> bool:
        """检查是否支持该格式"""
        return file_extension.lower() in [".pdf", ".docx"]
```

---

## 迁移步骤

### 步骤 1：安装依赖

```bash
# 安装必需库
pip install sentence-transformers  # BGE Embedding
pip install faiss-cpu              # FAISS 向量存储
pip install rank_bm25              # BM25 检索

# 如果使用 GPU
pip install faiss-gpu
```

---

### 步骤 2：创建自研 Embedding 类

```python
# backend/agent/rag/embeddings/my_embedding.py

from backend.agent.rag.base import EmbeddingProvider

class MyCustomEmbedding(EmbeddingProvider):
    """自研 Embedding 模型"""
    
    def __init__(self, model_path: str = "path/to/my/model"):
        # 加载你的模型
        self.model = self._load_model(model_path)
        self.dimension = 768  # 你的维度
    
    def embed(self, text: str) -> list[float]:
        # 你的推理逻辑
        vector = self.model.encode(text)
        return vector.tolist()
    
    def get_dimension(self) -> int:
        return self.dimension
```

---

### 步骤 3：创建自研向量存储类

```python
# backend/agent/rag/vectorstore/my_store.py

from backend.agent.rag.base import VectorStore, DocumentChunk, RetrievalResult

class MyCustomVectorStore(VectorStore):
    """自研向量存储"""
    
    def __init__(self, db_path: str = "data/my_vectors"):
        # 初始化你的向量数据库
        self.db = self._init_database(db_path)
    
    def add(self, chunks: list[DocumentChunk]) -> None:
        # 添加到你的向量库
        for chunk in chunks:
            self.db.insert(chunk.embedding, metadata={
                "content": chunk.content,
                "source": chunk.document.source,
            })
    
    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        similarity_threshold: float = 0.0,
    ) -> list[RetrievalResult]:
        # 你的检索逻辑
        results = self.db.search(query_vector, top_k)
        # 转换为 RetrievalResult 格式
        return [RetrievalResult(chunk=..., score=..., rank=i+1) 
                for i, result in enumerate(results)]
```

---

### 步骤 4：注册到配置系统

修改 `config.py`，添加你的模型选项：

```python
@dataclass
class RAGConfig:
    # Embedding 配置
    embedding_provider: Literal["simple", "bge", "my_custom"] = "bge"
    
    # 添加你的模型路径配置
    my_model_path: str = "path/to/my/model"
```

修改 `retriever.py`，添加创建逻辑：

```python
def _create_embedding_provider(self) -> EmbeddingProvider:
    if self.config.embedding_provider == "bge":
        return BGEEmbedding()
    elif self.config.embedding_provider == "my_custom":
        from backend.agent.rag.embeddings.my_embedding import MyCustomEmbedding
        return MyCustomEmbedding(self.config.my_model_path)
    else:
        return SimpleEmbedding()
```

---

### 步骤 5：验证替换

运行测试脚本验证：

```python
from backend.agent.rag import Retriever, RAGConfig
from backend.agent.rag.embeddings.my_embedding import MyCustomEmbedding

# 使用自研模型
config = RAGConfig(embedding_provider="my_custom")
retriever = Retriever(config)

# 索引文档
retriever.index_directory("path/to/docs")

# 检索测试
results = retriever.retrieve("测试查询")
for result in results:
    print(f"来源: {result.chunk.document.source}")
    print(f"分数: {result.score}")
```

---

## 数据格式转换

### 从 SimpleEmbedding 迁移到 BGE

**注意事项：**
- SimpleEmbedding 使用哈希生成向量，维度为 128
- BGE 使用真实语义向量，维度为 512
- **必须重新索引所有文档**，向量不兼容

```python
# 迁移脚本
from backend.agent.rag import Retriever, RAGConfig

# 1. 清空旧索引
config = RAGConfig(embedding_provider="simple")
old_retriever = Retriever(config)
old_retriever.clear_index()

# 2. 使用新模型重建索引
config = RAGConfig(embedding_provider="bge")
new_retriever = Retriever(config)
new_retriever.index_directory("path/to/docs")

# 3. 持久化
new_retriever.save_index()
```

---

### 从 Memory 存储迁移到 FAISS

```python
# 1. 加载内存中的数据（如果有）
config = RAGConfig(vector_store_type="memory")
memory_retriever = Retriever(config)

# 2. 切换到 FAISS
config = RAGConfig(vector_store_type="faiss")
faiss_retriever = Retriever(config)

# 3. 重新索引
faiss_retriever.index_directory("path/to/docs")
faiss_retriever.save_index()
```

---

## 性能评估与对比指标

### 评估维度

| 维度 | 指标 | 测试方法 |
|------|------|----------|
| **检索准确率** | Recall@K, Precision@K | 标注测试集 |
| **响应时间** | 平均延迟、P99 延迟 | 压力测试 |
| **资源占用** | 内存、CPU、GPU | 监控工具 |
| **扩展性** | 并发处理能力 | 多线程测试 |

### 性能基准测试

```python
import time
from backend.agent.rag import Retriever

def benchmark_retriever(retriever, queries: list[str], top_k: int = 5):
    """性能基准测试"""
    latencies = []
    
    for query in queries:
        start = time.time()
        results = retriever.retrieve(query, top_k=top_k)
        latency = time.time() - start
        latencies.append(latency)
    
    return {
        "avg_latency": sum(latencies) / len(latencies),
        "max_latency": max(latencies),
        "min_latency": min(latencies),
        "p99_latency": sorted(latencies)[int(len(latencies) * 0.99)],
    }

# 对比测试
simple_retriever = Retriever(RAGConfig(embedding_provider="simple"))
bge_retriever = Retriever(RAGConfig(embedding_provider="bge"))

test_queries = ["查询1", "查询2", "查询3"]  # 测试查询集

print("Simple Embedding:", benchmark_retriever(simple_retriever, test_queries))
print("BGE Embedding:", benchmark_retriever(bge_retriever, test_queries))
```

---

## 灰度迁移策略

### 双路运行

```python
class DualRetriever:
    """双路检索器：新旧模型并行运行"""
    
    def __init__(self, old_config: RAGConfig, new_config: RAGConfig):
        self.old_retriever = Retriever(old_config)
        self.new_retriever = Retriever(new_config)
    
    def retrieve(self, query: str, top_k: int = 5):
        # 并行检索
        old_results = self.old_retriever.retrieve(query, top_k)
        new_results = self.new_retriever.retrieve(query, top_k)
        
        # 记录对比日志
        self._log_comparison(query, old_results, new_results)
        
        # 返回新模型结果
        return new_results
    
    def _log_comparison(self, query, old_results, new_results):
        # 记录对比数据，用于后续分析
        log_data = {
            "query": query,
            "old_scores": [r.score for r in old_results],
            "new_scores": [r.score for r in new_results],
        }
        # 写入日志文件...
```

---

### A/B 测试

```python
import random

def ab_test_retriever(query: str, old_retriever, new_retriever, ratio: float = 0.5):
    """A/B 测试"""
    if random.random() < ratio:
        # 50% 流量使用新模型
        return new_retriever.retrieve(query)
    else:
        # 50% 流量使用旧模型
        return old_retriever.retrieve(query)
```

---

## 潜在兼容性问题

### 1. 向量维度不匹配

**问题：** 自研模型维度与 FAISS 配置不一致

**解决方案：**
```python
# 确保 embedding 和 vector_store 维度一致
embedding = MyCustomEmbedding()  # dimension=768
vector_store = FAISSVectorStore(
    dimension=embedding.get_dimension()  # 自动匹配
)
```

---

### 2. 内存占用激增

**问题：** 真实 Embedding 模型内存占用大

**解决方案：**
- 使用量化模型：`BAAI/bge-small-zh`
- 使用 CPU 模式：`device="cpu"`
- 限制批处理大小：`batch_size=16`

---

### 3. 推理速度下降

**问题：** 真实模型推理慢于 SimpleEmbedding

**解决方案：**
- 启用 GPU 加速
- 批量向量化：`embed_batch(texts)`
- 缓存热点查询结果

---

## 迁移检查清单

- [ ] 安装必需依赖（sentence-transformers, faiss-cpu, rank_bm25）
- [ ] 实现自研 Embedding 类（继承 EmbeddingProvider）
- [ ] 实现自研向量存储类（继承 VectorStore）
- [ ] 更新配置文件
- [ ] 重新索引所有文档
- [ ] 运行单元测试验证功能
- [ ] 性能基准测试对比
- [ ] 部署灰度迁移策略
- [ ] 监控生产环境指标

---

## 技术支持

如遇到迁移问题，请查看：
- [RAG_API.md](file:///d:/4github/esa/backend/agent/rag/RAG_API.md) - 接口文档
- [test_rag.py](file:///d:/4github/esa/backend/agent/rag/test_rag.py) - 测试脚本
- GitHub Issues: 提交问题和反馈
# RAG 模块依赖安装

## 必需依赖

```bash
# 核心依赖（必需）
pip install sentence-transformers  # BGE Embedding 模型
pip install faiss-cpu              # FAISS 向量存储
pip install rank_bm25              # BM25 检索算法
pip install numpy                  # 数值计算
```

## 可选依赖

```bash
# GPU 加速（如果有 GPU）
pip install faiss-gpu

# PDF 文档支持
pip install pdfplumber

# 中文分词（提高 BM25 效果）
pip install jieba
```

## 版本要求

- Python >= 3.9
- sentence-transformers >= 2.2.0
- faiss-cpu >= 1.7.0
- rank_bm25 >= 0.2.2

## 安装验证

```python
# 验证安装
try:
    from sentence_transformers import SentenceTransformer
    print("✓ sentence-transformers 安装成功")
except ImportError:
    print("✗ sentence-transformers 未安装")

try:
    import faiss
    print("✓ faiss 安装成功")
except ImportError:
    print("✗ faiss 未安装")

try:
    from rank_bm25 import BM25Okapi
    print("✓ rank_bm25 安装成功")
except ImportError:
    print("✗ rank_bm25 未安装")
```

## 常见问题

### 1. faiss-cpu 安装失败

**解决方案：**
```bash
# 尝试使用 conda 安装
conda install -c conda-forge faiss-cpu

# 或使用预编译 wheel
pip install faiss-cpu --no-cache-dir
```

### 2. BGE 模型下载慢

**解决方案：**
```python
# 使用国内镜像
export HF_ENDPOINT=https://hf-mirror.com

# 或手动下载模型到本地
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('BAAI/bge-small-zh', cache_folder='./models')
```

### 3. GPU 内存不足

**解决方案：**
```python
# 使用 CPU 模式
embedding = BGEEmbedding(device='cpu')

# 或使用小批次
embedding.embed_batch(texts[:100])  # 分批处理
```
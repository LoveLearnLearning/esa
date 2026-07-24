#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RAG 模块性能基准测试

对比不同 Embedding 和向量存储的性能：
- SimpleEmbedding vs BGE Embedding
- Memory vs FAISS 向量存储
- 纯向量检索 vs 混合检索
"""

import time
from pathlib import Path

from backend.agent.rag import Retriever, RAGConfig


class PerformanceBenchmark:
    """性能基准测试类"""

    def __init__(self, test_queries: list[str]):
        """初始化测试

        Args:
            test_queries: 测试查询列表
        """
        self.test_queries = test_queries
        self.results = {}

    def benchmark_embedding_providers(self, retriever: Retriever) -> dict:
        """测试不同 Embedding 提供者的性能

        Args:
            retriever: 检索器实例

        Returns:
            dict: 性能指标
        """
        latencies = []

        for query in self.test_queries:
            start = time.time()
            results = retriever.retrieve(query)
            latency = time.time() - start
            latencies.append(latency)

        return {
            "avg_latency": round(sum(latencies) / len(latencies), 4),
            "max_latency": round(max(latencies), 4),
            "min_latency": round(min(latencies), 4),
            "p99_latency": round(
                sorted(latencies)[int(len(latencies) * 0.99)], 4
            ),
        }

    def run_comparison(self, docs_path: Path):
        """运行完整对比测试

        Args:
            docs_path: 测试文档路径
        """
        print("=" * 60)
        print("RAG 性能基准测试")
        print("=" * 60)

        # 测试 1: SimpleEmbedding + Memory
        print("\n1. 测试 SimpleEmbedding + Memory 存储...")
        config = RAGConfig(
            embedding_provider="simple",
            vector_store_type="memory",
            use_hybrid=False,
        )
        retriever = Retriever(config)
        retriever.index_directory(docs_path)

        self.results["simple_memory"] = self.benchmark_embedding_providers(
            retriever
        )
        print(f"   平均延迟: {self.results['simple_memory']['avg_latency']}s")

        # 清理
        retriever.clear_index()

        # 测试 2: BGE Embedding + FAISS（如果有依赖）
        print("\n2. 测试 BGE Embedding + FAISS 存储...")
        try:
            config = RAGConfig(
                embedding_provider="bge",
                vector_store_type="faiss",
                use_hybrid=False,
            )
            retriever = Retriever(config)
            retriever.index_directory(docs_path)

            self.results["bge_faiss"] = self.benchmark_embedding_providers(
                retriever
            )
            print(f"   平均延迟: {self.results['bge_faiss']['avg_latency']}s")

            # 保存索引
            retriever.save_index()

        except ImportError as e:
            print(f"   ✗ 跳过: {e}")

        # 测试 3: 混合检索（BM25 + 向量）
        print("\n3. 测试混合检索（BM25 + 向量）...")
        try:
            config = RAGConfig(
                embedding_provider="bge",
                vector_store_type="faiss",
                use_hybrid=True,
                bm25_weight=0.5,
                vector_weight=0.5,
            )
            retriever = Retriever(config)
            retriever.index_directory(docs_path)

            self.results["hybrid"] = self.benchmark_embedding_providers(
                retriever
            )
            print(f"   平均延迟: {self.results['hybrid']['avg_latency']}s")

        except ImportError as e:
            print(f"   ✗ 跳过: {e}")

        # 输出结果对比
        self._print_comparison()

    def _print_comparison(self):
        """打印对比结果"""
        print("\n" + "=" * 60)
        print("性能对比结果")
        print("=" * 60)

        print(f"\n{'配置':<20} {'平均延迟(s)':<15} {'最大延迟(s)':<15}")
        print("-" * 60)

        for name, metrics in self.results.items():
            print(
                f"{name:<20} {metrics['avg_latency']:<15} {metrics['max_latency']:<15}"
            )


def main():
    """运行基准测试"""
    # 测试查询集
    test_queries = [
        "什么是极限？",
        "如何定义导数？",
        "Python 中的列表是什么？",
        "如何使用 for 循环？",
        "不定积分的定义是什么？",
    ]

    # 文档路径
    docs_path = Path(__file__).resolve().parent / "sample_docs"

    if not docs_path.exists():
        print(f"错误: 测试文档目录不存在: {docs_path}")
        return

    # 运行测试
    benchmark = PerformanceBenchmark(test_queries)
    benchmark.run_comparison(docs_path)


if __name__ == "__main__":
    main()
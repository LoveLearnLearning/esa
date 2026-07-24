#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RAG 模块测试脚本

测试 RAG 模块的完整流程：
1. 文档加载
2. 文本分块
3. 向量化
4. 检索
"""

from pathlib import Path

from backend.agent.rag.config import RAGConfig
from backend.agent.rag.retriever import Retriever


def test_rag_module():
    """测试 RAG 模块"""
    print("=" * 60)
    print("RAG 模块测试")
    print("=" * 60)

    # 1. 创建配置
    print("\n1. 创建 RAG 配置...")
    config = RAGConfig(
        chunk_size=300,
        chunk_overlap=50,
        top_k=3,
        similarity_threshold=0.3,
    )
    print(f"   - 分块大小: {config.chunk_size}")
    print(f"   - 重叠大小: {config.chunk_overlap}")
    print(f"   - Top-K: {config.top_k}")
    print(f"   - 相似度阈值: {config.similarity_threshold}")

    # 2. 创建检索器
    print("\n2. 创建 RAG 检索器...")
    retriever = Retriever(config)
    print("   ✓ 检索器已创建")

    # 3. 加载文档
    print("\n3. 加载示例文档...")
    sample_dir = Path(__file__).resolve().parent / "sample_docs"

    if not sample_dir.exists():
        print(f"   ✗ 示例文档目录不存在: {sample_dir}")
        return

    documents = retriever.load_documents(sample_dir)
    print(f"   ✓ 已加载 {len(documents)} 个文档")

    for doc in documents:
        print(f"      - {doc.source} ({len(doc.content)} 字符)")

    # 4. 索引文档
    print("\n4. 索引文档（分块 + 向量化 + 存储）...")
    chunk_count = retriever.index_documents(documents)
    print(f"   ✓ 已索引 {chunk_count} 个文档分块")

    # 5. 获取统计信息
    print("\n5. 知识库统计信息:")
    stats = retriever.get_stats()
    print(f"   - 总分块数: {stats['total_chunks']}")
    print(f"   - 向量维度: {stats['embedding_dimension']}")
    print(f"   - Embedding 提供者: {stats['config']['embedding_provider']}")
    print(f"   - 向量存储类型: {stats['config']['vector_store_type']}")

    # 6. 执行检索测试
    print("\n6. 执行检索测试...")

    test_queries = [
        "什么是极限？",
        "Python 如何定义函数？",
        "导数的定义是什么？",
    ]

    for query in test_queries:
        print(f"\n   查询: {query}")
        result = retriever.retrieve_with_context(query, top_k=2)

        print(f"   结果数量: {result['result_count']}")

        for i, res in enumerate(result["results"], 1):
            print(f"\n   结果 {i}:")
            print(f"      来源: {res['source']}")
            print(f"      章节: {res['section']}")
            print(f"      相似度: {res['score']}")
            print(f"      内容片段: {res['content'][:100]}...")

        print(f"\n   来源标注:")
        for source in result["sources"]:
            print(f"      {source}")

    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)


def test_rag_tool_registration():
    """测试 RAG 工具注册"""
    print("\n" + "=" * 60)
    print("RAG 工具注册测试")
    print("=" * 60)

    # 导入工具注册模块
    from backend.agent.rag import rag_tool
    from backend.agent.tools import tr

    print("\n已注册的 RAG 工具:")
    rag_tools = [
        schema
        for schema in tr.schemas
        if schema.get("function", {}).get("name", "").startswith("retrieve")
        or schema.get("function", {}).get("name", "").startswith("index")
        or schema.get("function", {}).get("name", "").startswith("get_knowledge")
        or schema.get("function", {}).get("name", "").startswith("clear_knowledge")
    ]

    for tool in rag_tools:
        func_name = tool.get("function", {}).get("name", "未知")
        description = tool.get("function", {}).get("description", "")
        print(f"   - {func_name}")
        print(f"     {description}")

    print("\n" + "=" * 60)


def test_tool_calls():
    """测试工具调用"""
    print("\n" + "=" * 60)
    print("RAG 工具调用测试")
    print("=" * 60)

    # 导入工具函数
    from backend.agent.rag.rag_tool import (
        get_knowledge_base_stats,
        index_knowledge_base,
        retrieve_knowledge,
    )

    # 1. 索引知识库
    print("\n1. 索引知识库...")
    result = index_knowledge_base()
    print(f"   ✓ {result['message']}")
    print(f"   - 索引分块数: {result['indexed_chunks']}")

    # 2. 获取统计信息
    print("\n2. 获取知识库统计...")
    stats = get_knowledge_base_stats()
    print(f"   - 总分块数: {stats['total_chunks_in_store']}")

    # 3. 执行检索
    print("\n3. 执行检索...")
    query = "什么是导数？"
    result = retrieve_knowledge(query, top_k=2)

    print(f"   查询: {query}")
    print(f"   结果数量: {result['result_count']}")

    for i, res in enumerate(result["results"], 1):
        print(f"\n   结果 {i}:")
        print(f"      来源: {res['source']}")
        print(f"      相似度: {res['score']}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    # 运行所有测试
    test_rag_module()
    test_rag_tool_registration()
    test_tool_calls()
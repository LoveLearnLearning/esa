# backend/tests/test_kp_resolver.py

"""验证 `kp_resolver` 相关行为与回归场景。"""

import pytest

from backend.agent.memories.kg_loader import ensure_knowledge_graph_seeded
from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.memories.kp_resolver import KnowledgePointResolver


@pytest.fixture(scope="module")
def resolver(tmp_path_factory) -> KnowledgePointResolver:
    """处理 `resolver` 相关逻辑。"""
    store = KnowledgeGraphStore(
        tmp_path_factory.mktemp("kp_resolver") / "knowledge_graph.db"
    )
    ensure_knowledge_graph_seeded(store)
    return KnowledgePointResolver(store)


def test_resolves_chinese_knowledge_point_name(resolver):
    """验证 `resolves_chinese_knowledge_point_name` 场景。"""
    matches = resolver.resolve("给我讲讲二叉树")
    assert matches[0].kp_id == "二叉树"


def test_resolves_bst_alias(resolver):
    """验证 `resolves_bst_alias` 场景。"""
    matches = resolver.resolve("BST 删除节点")
    assert matches[0].kp_id == "二叉搜索树"


def test_resolves_dfs_alias(resolver):
    """验证 `resolves_dfs_alias` 场景。"""
    matches = resolver.resolve("DFS 怎么写")
    assert matches[0].kp_id == "深度优先搜索"


def test_single_character_point_does_not_match_inside_sentence(resolver):
    """验证 `single_character_point_does_not_match_inside_sentence` 场景。"""
    matches = resolver.resolve("我画了一张图")
    assert all(match.kp_id != "图" for match in matches)


def test_resolves_hash_table_name(resolver):
    """验证 `resolves_hash_table_name` 场景。"""
    matches = resolver.resolve("哈希表为什么快")
    assert matches[0].kp_id == "哈希表"


def test_resolves_probability_theory_alias(resolver):
    """课程简称“概率论”应解析到知识图谱中的 canonical 知识点。"""
    matches = resolver.resolve("给我讲一下概率论")

    assert matches[0].kp_id == "概率论基础"
    assert matches[0].matched_by == "alias"


def test_ascii_acronym_requires_word_boundaries(resolver):
    """验证 `ascii_acronym_requires_word_boundaries` 场景。"""
    matches = resolver.resolve("endpoint configuration")
    assert all(match.kp_id != "动态规划" for match in matches)

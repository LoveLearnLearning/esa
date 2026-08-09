import pytest

from backend.agent.memories.kg_loader import ensure_knowledge_graph_seeded
from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.memories.kp_resolver import KnowledgePointResolver


@pytest.fixture(scope="module")
def resolver(tmp_path_factory) -> KnowledgePointResolver:
    store = KnowledgeGraphStore(
        tmp_path_factory.mktemp("kp_resolver") / "knowledge_graph.db"
    )
    ensure_knowledge_graph_seeded(store)
    return KnowledgePointResolver(store)


def test_resolves_chinese_knowledge_point_name(resolver):
    matches = resolver.resolve("给我讲讲二叉树")
    assert matches[0].kp_id == "二叉树"


def test_resolves_bst_alias(resolver):
    matches = resolver.resolve("BST 删除节点")
    assert matches[0].kp_id == "二叉搜索树"


def test_resolves_dfs_alias(resolver):
    matches = resolver.resolve("DFS 怎么写")
    assert matches[0].kp_id == "深度优先搜索"


def test_single_character_point_does_not_match_inside_sentence(resolver):
    matches = resolver.resolve("我画了一张图")
    assert all(match.kp_id != "图" for match in matches)


def test_resolves_hash_table_name(resolver):
    matches = resolver.resolve("哈希表为什么快")
    assert matches[0].kp_id == "哈希表"


def test_ascii_acronym_requires_word_boundaries(resolver):
    matches = resolver.resolve("endpoint configuration")
    assert all(match.kp_id != "动态规划" for match in matches)

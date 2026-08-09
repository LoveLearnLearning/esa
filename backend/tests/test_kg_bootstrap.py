from backend.agent.memories.kg_loader import ensure_knowledge_graph_seeded
from backend.agent.memories.knowledge_graph import KnowledgeGraphStore


def test_empty_knowledge_graph_is_seeded_idempotently(tmp_path):
    store = KnowledgeGraphStore(tmp_path / "knowledge_graph.db")

    assert store.count_points() == 0
    assert store.count_prerequisites() == 0

    synced_points, synced_edges = ensure_knowledge_graph_seeded(store)
    first_counts = (store.count_points(), store.count_prerequisites())

    assert synced_points > 0
    assert synced_edges > 0
    assert first_counts[0] > 0
    assert first_counts[1] > 0
    assert synced_points == first_counts[0]
    assert synced_edges == first_counts[1]

    ensure_knowledge_graph_seeded(store)

    assert (store.count_points(), store.count_prerequisites()) == first_counts


def test_batch_point_lookup_preserves_input_order(tmp_path):
    store = KnowledgeGraphStore(tmp_path / "knowledge_graph.db")
    store.add_point("kp-a", "A", "course")
    store.add_point("kp-b", "B", "course")

    points = store.get_points(["kp-b", "missing", "kp-a", "kp-b"])

    assert [point["id"] for point in points] == ["kp-b", "kp-a", "kp-b"]

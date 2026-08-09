# backend/agent/memories/seed_knowledge_graph.py
# 知识图谱种子数据入口：从 YAML 外置文件加载并写入 KnowledgeGraphStore
# 数据文件：data/knowledge_graph/core_courses.yaml（16 门核心必修）
#           data/knowledge_graph/elective_courses.yaml（30 门选修 + 数学基础）
# 数据来源：9 所顶尖高校培养方案并集，知识点粒度对齐名校课程大纲

from backend.agent.memories.kg_loader import load_into_store, load_yaml_files
from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.memories.paths import KNOWLEDGE_GRAPH_DB_PATH

# 向后兼容：从 YAML 加载后暴露为模块级常量
POINTS, PREREQUISITES, ALIASES, COURSES = load_yaml_files()


def seed(store: KnowledgeGraphStore) -> tuple[int, int]:
    """向指定 store 写入知识点与依赖边（从 YAML 加载）

    Args:
        store: KnowledgeGraphStore  => 目标数据层实例

    Returns:
        tuple[int, int]             => 同步的知识点数量与依赖边数量
    """
    return load_into_store(store)


def main() -> None:
    """直接执行脚本时同步运行时实际使用的知识图谱数据库。"""
    store = KnowledgeGraphStore(database_path=KNOWLEDGE_GRAPH_DB_PATH)

    point_count, edge_count = seed(store)

    print(
        f"知识图谱同步完成: 知识点 {point_count} 个, "
        f"依赖边 {edge_count} 条"
    )


if __name__ == "__main__":
    main()

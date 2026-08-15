# backend/agent/memories/kg_loader.py

"""提供 `kg_loader` 相关功能。"""

# 知识图谱 YAML 数据加载器：将外置 YAML 文件载入 KnowledgeGraphStore
# 数据文件：data/knowledge_graph/core_courses.yaml（16 门核心必修）
#           data/knowledge_graph/elective_courses.yaml（30 门选修 + 数学基础）

import yaml

from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.memories.paths import (
    COURSE_ALIASES_YAML,
    CORE_COURSES_YAML,
    ELECTIVE_COURSES_YAML,
    KNOWLEDGE_ALIASES_YAML,
)

YAML_FILES = [CORE_COURSES_YAML, ELECTIVE_COURSES_YAML]


def load_yaml_files() -> tuple[list[tuple], list[tuple], list[tuple], list[str]]:
    """从 YAML 文件加载知识点与依赖边

    Returns:
        (points, prerequisites, aliases, courses) 四元组
        points: list of (id, name, course, weight, category)
        prerequisites: list of (kp_id, prerequisite_kp_id)
        courses: list of course names
    """
    points: list[tuple] = []
    prerequisites: list[tuple] = []
    aliases: list[tuple] = []
    courses: list[str] = []

    for yaml_file in YAML_FILES:
        if not yaml_file.exists():
            continue
        with open(yaml_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for course_entry in data.get("courses", []):
            course_name = course_entry["course"]
            category = course_entry.get("category", "general")
            courses.append(course_name)
            for pt in course_entry.get("points", []):
                points.append(
                    (
                        pt["id"],
                        pt["name"],
                        course_name,
                        float(pt.get("weight", 0.0)),
                        category,
                    )
                )
                aliases.extend(
                    (str(alias).strip(), pt["id"])
                    for alias in pt.get("aliases", [])
                    if str(alias).strip()
                )
            for edge in course_entry.get("prerequisites", []):
                prerequisites.append((edge[0], edge[1]))

    # 兼容已有 aliases.yaml：键可以是 canonical id，也可以是知识点名称。
    if KNOWLEDGE_ALIASES_YAML.exists():
        with open(KNOWLEDGE_ALIASES_YAML, "r", encoding="utf-8") as file:
            alias_data = yaml.safe_load(file) or {}
        name_to_id = {point[1]: point[0] for point in points}
        known_ids = {point[0] for point in points}
        for point_key, values in alias_data.get("aliases", {}).items():
            kp_id = point_key if point_key in known_ids else name_to_id.get(point_key)
            if kp_id is None:
                continue
            aliases.extend(
                (str(alias).strip(), kp_id)
                for alias in values or []
                if str(alias).strip()
            )

    return points, prerequisites, aliases, courses


def load_into_store(store: KnowledgeGraphStore) -> tuple[int, int]:
    """从 YAML 文件幂等同步知识点与依赖边到指定 store。

    Returns:
        (同步的知识点数量, 同步的依赖边数量)
    """
    points, prerequisites, aliases, _ = load_yaml_files()
    point_count = 0
    edge_count = 0
    for point in points:
        if store.add_point(*point):
            point_count += 1
    seen_edges: set[tuple[str, str]] = set()
    for kp_id, prerequisite_kp_id in prerequisites:
        edge = (kp_id, prerequisite_kp_id)
        if edge in seen_edges:
            continue
        seen_edges.add(edge)
        if store.add_prerequisite(kp_id, prerequisite_kp_id):
            edge_count += 1
    for alias, kp_id in dict(aliases).items():
        store.add_alias(alias, kp_id)
    if COURSE_ALIASES_YAML.exists():
        with open(COURSE_ALIASES_YAML, "r", encoding="utf-8") as file:
            course_alias_data = yaml.safe_load(file) or {}
        for course, values in course_alias_data.get("course_aliases", {}).items():
            for alias in values or []:
                store.add_course_alias(str(alias), str(course))
    return point_count, edge_count


def ensure_knowledge_graph_seeded(
    store: KnowledgeGraphStore,
) -> tuple[int, int]:
    """幂等同步 YAML 中的知识点和依赖关系。

    ``add_point`` 使用 UPSERT，``add_prerequisite`` 使用 INSERT OR IGNORE，
    因此每次启动都可安全执行，已有数据库也会获得新增的 YAML 数据。
    """
    return load_into_store(store)

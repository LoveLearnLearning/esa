# backend/agent/memories/kg_loader.py
# 知识图谱 YAML 数据加载器：将外置 YAML 文件载入 KnowledgeGraphStore
# 数据文件：data/knowledge_graph/core_courses.yaml（16 门核心必修）
#           data/knowledge_graph/elective_courses.yaml（30 门选修 + 数学基础）

from pathlib import Path

import yaml

from backend.agent.memories.knowledge_graph import KnowledgeGraphStore

DATA_DIR = Path(__file__).parent / "data" / "knowledge_graph"
YAML_FILES = [DATA_DIR / "core_courses.yaml", DATA_DIR / "elective_courses.yaml"]


def load_yaml_files() -> tuple[list[tuple], list[tuple], list[str]]:
    """从 YAML 文件加载知识点与依赖边

    Returns:
        (points, prerequisites, courses) 三元组
        points: list of (id, name, course, weight, category)
        prerequisites: list of (kp_id, prerequisite_kp_id)
        courses: list of course names
    """
    points: list[tuple] = []
    prerequisites: list[tuple] = []
    courses: list[str] = []

    for yaml_file in YAML_FILES:
        if not yaml_file.exists():
            continue
        with open(yaml_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for course_entry in data.get("courses", []):
            course_name = course_entry["course"]
            category = course_entry.get("category", "general")
            courses.append(course_name)
            for pt in course_entry.get("points", []):
                points.append(
                    (pt["id"], pt["name"], course_name, pt["weight"], category)
                )
            for edge in course_entry.get("prerequisites", []):
                prerequisites.append((edge[0], edge[1]))

    return points, prerequisites, courses


def load_into_store(store: KnowledgeGraphStore) -> int:
    """从 YAML 文件载入数据并写入指定 store

    Returns:
        成功写入的知识点数量
    """
    points, prerequisites, _ = load_yaml_files()
    count = 0
    for point in points:
        if store.add_point(*point):
            count += 1
    for kp_id, prerequisite_kp_id in prerequisites:
        store.add_prerequisite(kp_id, prerequisite_kp_id)
    return count

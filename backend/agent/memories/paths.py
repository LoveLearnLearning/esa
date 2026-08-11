"""Canonical filesystem paths for ESA memory stores and source data."""

from pathlib import Path


MEMORIES_DIR = Path(__file__).resolve().parent
MEMORY_DATA_DIR = MEMORIES_DIR / "data"

KNOWLEDGE_GRAPH_DB_PATH = MEMORY_DATA_DIR / "knowledge_graph.db"
MASTERY_DB_PATH = MEMORY_DATA_DIR / "mastery.db"
CORE_MEMORY_DB_PATH = MEMORY_DATA_DIR / "core_memory.db"
LEARNING_EVIDENCE_DB_PATH = MEMORY_DATA_DIR / "learning_evidence.db"
USER_DB_PATH = MEMORIES_DIR.parents[1] / "core" / "stores" / "data" / "user.db"

KNOWLEDGE_GRAPH_SOURCE_DIR = MEMORY_DATA_DIR / "knowledge_graph"

CORE_COURSES_YAML = KNOWLEDGE_GRAPH_SOURCE_DIR / "core_courses.yaml"
ELECTIVE_COURSES_YAML = KNOWLEDGE_GRAPH_SOURCE_DIR / "elective_courses.yaml"
KNOWLEDGE_ALIASES_YAML = KNOWLEDGE_GRAPH_SOURCE_DIR / "aliases.yaml"
COURSE_ALIASES_YAML = KNOWLEDGE_GRAPH_SOURCE_DIR / "course_aliases.yaml"

# backend/agent/memories/knowledge_graph.py

"""提供 `knowledge_graph` 相关功能。"""

from __future__ import annotations

import sqlite3
from collections import deque
from pathlib import Path

from backend.core.stores.sqlite_connection import connect_sqlite


class KnowledgeGraphStore:
    """
    知识图谱数据层

    存储学科知识点及其前置依赖关系 支撑掌握度模型与推题逻辑
    """

    def __init__(
        self,
        database_path: str | Path = "data/knowledge_graph.db",
    ) -> None:
        """初始化 `KnowledgeGraphStore` 实例。"""
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.__initialize()

    def __connect(self) -> sqlite3.Connection:
        """辅助函数 链接 SQLite 数据库"""
        return connect_sqlite(self.database_path)

    def __initialize(self) -> None:
        """辅助函数 初始化 SQLite 数据库"""
        with self.__connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_points (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    course TEXT NOT NULL,
                    weight REAL DEFAULT 0.0,
                    category TEXT DEFAULT 'general'
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_prerequisites (
                    kp_id TEXT NOT NULL,
                    prerequisite_kp_id TEXT NOT NULL,
                    PRIMARY KEY (kp_id, prerequisite_kp_id),
                    FOREIGN KEY (kp_id) REFERENCES knowledge_points(id),
                    FOREIGN KEY (prerequisite_kp_id) REFERENCES knowledge_points(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_point_aliases (
                    alias TEXT PRIMARY KEY,
                    kp_id TEXT NOT NULL,
                    FOREIGN KEY (kp_id)
                        REFERENCES knowledge_points(id)
                        ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS course_aliases (
                    alias TEXT PRIMARY KEY,
                    course TEXT NOT NULL
                )
                """
            )

    def add_point(
        self,
        id: str,
        name: str,
        course: str,
        weight: float = 0.0,
        category: str = "general",
    ) -> bool:
        """在数据库中添加或更新某条知识点
        Args:
            id: str                    => 知识点唯一 id
            name: str                  => 知识点名称
            course: str                => 所属课程
            weight: float = 0.0        => 考试权重 0-1
            category: str = "general"  => 知识点类别 默认为 "general"

        Returns:
            bool                       => 写入数据是否成功
        """
        id = id.strip()
        name = name.strip()
        course = course.strip()
        category = category.strip() or "general"

        if not id:
            return False

        if not name:
            return False

        if not course:
            return False

        with self.__connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_points (id, name, course, weight, category)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id)
                DO UPDATE SET
                    name = excluded.name,
                    course = excluded.course,
                    weight = excluded.weight,
                    category = excluded.category
                """,
                (
                    id,
                    name,
                    course,
                    weight,
                    category,
                ),
            )

        return True

    def add_prerequisite(
        self,
        kp_id: str,
        prerequisite_kp_id: str,
    ) -> bool:
        """添加一条前置依赖关系 两个知识点都存在才会写入
        Args:
            kp_id: str                => 知识点 id
            prerequisite_kp_id: str   => 前置知识点 id

        Returns:
            bool                      => 写入数据是否成功
        """
        kp_id = kp_id.strip()
        prerequisite_kp_id = prerequisite_kp_id.strip()

        if not kp_id:
            return False

        if not prerequisite_kp_id:
            return False

        if kp_id == prerequisite_kp_id:
            return False

        with self.__connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM knowledge_points
                WHERE id IN (?, ?)
                """,
                (
                    kp_id,
                    prerequisite_kp_id,
                ),
            ).fetchone()

            if row["cnt"] < 2:
                return False

            connection.execute(
                """
                INSERT OR IGNORE INTO knowledge_prerequisites (kp_id, prerequisite_kp_id)
                VALUES (?, ?)
                """,
                (
                    kp_id,
                    prerequisite_kp_id,
                ),
            )

        return True

    def add_alias(self, alias: str, kp_id: str) -> bool:
        """添加或更新知识点别名。"""
        alias = alias.strip()
        kp_id = kp_id.strip()
        if not alias or not kp_id or self.get_point(kp_id) is None:
            return False
        with self.__connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_point_aliases (alias, kp_id)
                VALUES (?, ?)
                ON CONFLICT(alias) DO UPDATE SET kp_id = excluded.kp_id
                """,
                (alias, kp_id),
            )
        return True

    def resolve_kp_id(self, value: str) -> str | None:
        """将规范 ID、知识点名称或别名解析成规范 ID。"""
        value = value.strip()
        if not value:
            return None
        with self.__connect() as connection:
            row = connection.execute(
                """
                SELECT id
                FROM knowledge_points
                WHERE id = ? OR name = ?
                ORDER BY CASE WHEN id = ? THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (value, value, value),
            ).fetchone()
            if row is not None:
                return str(row["id"])
            row = connection.execute(
                """
                SELECT kp_id
                FROM knowledge_point_aliases
                WHERE alias = ?
                LIMIT 1
                """,
                (value,),
            ).fetchone()
        return None if row is None else str(row["kp_id"])

    def get_point(self, id: str) -> dict | None:
        """获取数据库中单条知识点
        Args:
            id: str  => 知识点唯一 id

        Returns:
            dict | None:
                dict    => 返回数据库中对应知识点 包含 id name course weight category
                None    => 没有该 id 对应的知识点
        """
        id = id.strip()

        if not id:
            return None

        with self.__connect() as connection:
            row = connection.execute(
                """
                SELECT id, name, course, weight, category
                FROM knowledge_points
                WHERE id = ?
                """,
                (id,),
            ).fetchone()

        if row is None:
            return None

        return dict(row)

    def get_course_points(self, course: str) -> list[dict]:
        """获取某门课程的全部知识点
        Args:
            course: str  => 课程名

        Returns:
            list[dict]   => 该课程全部知识点 按考试权重降序
        """
        course = course.strip()

        with self.__connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, course, weight, category
                FROM knowledge_points
                WHERE course = ?
                ORDER BY weight DESC, id ASC
                """,
                (course,),
            ).fetchall()

        return [dict(row) for row in rows]

    def list_all(self) -> list[dict]:
        """获取全部知识点
        Returns:
            list[dict]   => 全部知识点列表 按课程与 id 升序
        """
        with self.__connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, course, weight, category
                FROM knowledge_points
                ORDER BY course ASC, id ASC
                """
            ).fetchall()

        return [dict(row) for row in rows]

    def count_points(self) -> int:
        """返回知识点总数。"""
        with self.__connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS cnt FROM knowledge_points"
            ).fetchone()

        return int(row["cnt"]) if row else 0

    def count_prerequisites(self) -> int:
        """返回知识点依赖边总数。"""
        with self.__connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS cnt FROM knowledge_prerequisites"
            ).fetchone()

        return int(row["cnt"]) if row else 0

    def get_points(self, ids: list[str]) -> list[dict]:
        """批量读取知识点，并保持调用方给出的 ID 顺序。"""
        normalized = [
            item.strip()
            for item in ids
            if isinstance(item, str) and item.strip()
        ]

        if not normalized:
            return []

        placeholders = ",".join("?" for _ in normalized)

        with self.__connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, name, course, weight, category
                FROM knowledge_points
                WHERE id IN ({placeholders})
                """,
                tuple(normalized),
            ).fetchall()

        by_id = {row["id"]: dict(row) for row in rows}
        return [by_id[kp_id] for kp_id in normalized if kp_id in by_id]

    def get_points_by_ids(self, ids: list[str]) -> list[dict]:
        """Knowledge Map 服务使用的批量查询别名。"""
        return self.get_points(ids)

    def list_courses(self) -> list[str]:
        """列出 `courses` 相关数据。"""
        with self.__connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT course
                FROM knowledge_points
                ORDER BY course ASC
                """
            ).fetchall()
        return [str(row["course"]) for row in rows]

    def resolve_course_name(self, value: str) -> str | None:
        """Resolve an exact canonical name or configured course alias."""
        normalized = "".join(value.split()).casefold()
        if not normalized:
            return None
        for course in self.list_courses():
            if "".join(course.split()).casefold() == normalized:
                return course
        with self.__connect() as connection:
            row = connection.execute(
                "SELECT course FROM course_aliases WHERE alias = ?",
                (normalized,),
            ).fetchone()
        return str(row["course"]) if row is not None else None

    def add_course_alias(self, alias: str, course: str) -> bool:
        """添加 `course alias` 相关数据。

        Args:
            alias: str => `alias` 参数。
            course: str => `course` 参数。

        Returns:
            bool => 处理结果。
        """
        normalized = "".join(alias.split()).casefold()
        canonical = course.strip()
        if not normalized or canonical not in set(self.list_courses()):
            return False
        with self.__connect() as connection:
            connection.execute(
                """
                INSERT INTO course_aliases (alias, course)
                VALUES (?, ?)
                ON CONFLICT(alias) DO UPDATE SET course = excluded.course
                """,
                (normalized, canonical),
            )
        return True

    def list_course_aliases(self) -> list[dict]:
        """列出 `course aliases` 相关数据。"""
        with self.__connect() as connection:
            rows = connection.execute(
                "SELECT alias, course FROM course_aliases ORDER BY alias"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_edges(
        self,
        course: str | None = None,
        include_external_prerequisites: bool = False,
    ) -> list[dict]:
        """返回前置知识点到依赖知识点的有向边。"""
        params: tuple[str, ...] = ()
        condition = ""
        if course is not None and course.strip():
            if include_external_prerequisites:
                condition = "WHERE dependent.course = ?"
                params = (course.strip(),)
            else:
                condition = (
                    "WHERE dependent.course = ? AND prerequisite.course = ?"
                )
                params = (course.strip(), course.strip())
        with self.__connect() as connection:
            rows = connection.execute(
                f"""
                SELECT p.prerequisite_kp_id AS "from", p.kp_id AS "to"
                FROM knowledge_prerequisites p
                JOIN knowledge_points dependent ON dependent.id = p.kp_id
                JOIN knowledge_points prerequisite
                    ON prerequisite.id = p.prerequisite_kp_id
                {condition}
                ORDER BY p.prerequisite_kp_id ASC, p.kp_id ASC
                """,
                params,
            ).fetchall()
        return [
            {"from": row["from"], "to": row["to"], "type": "prerequisite"}
            for row in rows
        ]

    def get_prerequisites(
        self,
        kp_id: str,
        max_depth: int = 3,
    ) -> list[dict]:
        """BFS 遍历获取某知识点的前置依赖链
        Args:
            kp_id: str              => 知识点 id
            max_depth: int = 3      => 最大遍历深度

        Returns:
            list[dict]              => 按深度有序的依赖链 深度 0 表示知识点本身:
                depth: int          => 依赖深度
                kp_id: str          => 知识点 id
                name: str           => 知识点名称
                course: str         => 所属课程
                weight: float       => 考试权重
        """
        kp_id = kp_id.strip()

        if not kp_id:
            return []

        start = self.get_point(kp_id)

        if start is None:
            return []

        results = [
            {
                "depth": 0,
                "kp_id": start["id"],
                "name": start["name"],
                "course": start["course"],
                "weight": start["weight"],
            }
        ]

        visited = {kp_id}
        queue = deque([(kp_id, 0)])

        while queue:
            current_id, depth = queue.popleft()

            if depth >= max_depth:
                continue

            with self.__connect() as connection:
                rows = connection.execute(
                    """
                    SELECT
                        p.prerequisite_kp_id AS kp_id,
                        kp.name AS name,
                        kp.course AS course,
                        kp.weight AS weight
                    FROM knowledge_prerequisites p
                    JOIN knowledge_points kp
                        ON kp.id = p.prerequisite_kp_id
                    WHERE p.kp_id = ?
                    """,
                    (current_id,),
                ).fetchall()

            for row in rows:
                if row["kp_id"] in visited:
                    continue

                visited.add(row["kp_id"])

                results.append(
                    {
                        "depth": depth + 1,
                        "kp_id": row["kp_id"],
                        "name": row["name"],
                        "course": row["course"],
                        "weight": row["weight"],
                    }
                )

                queue.append((row["kp_id"], depth + 1))

        return results

# backend/agent/learning/knowledge_map_service.py

"""Read model for the personal knowledge map UI and APIs."""

from __future__ import annotations

from collections import defaultdict, deque

from backend.agent.learning.evidence_store import LearningEvidenceStore
from backend.agent.memories.knowledge_graph import KnowledgeGraphStore
from backend.agent.memories.mastery_store import MasteryStore


class KnowledgeMapService:
    """提供 `knowledge map service` 领域服务。"""
    def __init__(
        self,
        *,
        kg_store: KnowledgeGraphStore,
        mastery_store: MasteryStore,
        evidence_store: LearningEvidenceStore,
    ) -> None:
        """初始化 `KnowledgeMapService` 实例。"""
        self.kg_store = kg_store
        self.mastery_store = mastery_store
        self.evidence_store = evidence_store

    @staticmethod
    def _levels(node_ids: set[str], edges: list[dict]) -> dict[str, int]:
        """处理 `_levels` 相关逻辑。"""
        incoming = {node_id: 0 for node_id in node_ids}
        children: dict[str, list[str]] = defaultdict(list)
        for edge in edges:
            source, target = edge["from"], edge["to"]
            if source not in node_ids or target not in node_ids:
                continue
            incoming[target] += 1
            children[source].append(target)
        queue = deque(
            node_id for node_id, degree in incoming.items() if degree == 0
        )
        levels = {node_id: 0 for node_id in queue}
        while queue:
            current = queue.popleft()
            for child in children[current]:
                levels[child] = max(
                    levels.get(child, 0), levels[current] + 1
                )
                incoming[child] -= 1
                if incoming[child] == 0:
                    queue.append(child)
        fallback = max(levels.values(), default=0) + 1
        for node_id in node_ids:
            levels.setdefault(node_id, fallback)
        return levels

    @staticmethod
    def _course_node_id(course: str) -> str:
        """处理 `_course_node_id` 相关逻辑。"""
        return f"__course__:{course}"

    @staticmethod
    def _component_roots(node_ids: set[str], edges: list[dict]) -> list[str]:
        """Return every DAG root, plus one representative for cyclic components."""
        incoming = {node_id: 0 for node_id in node_ids}
        adjacency: dict[str, set[str]] = {
            node_id: set() for node_id in node_ids
        }
        for edge in edges:
            source, target = edge["from"], edge["to"]
            if source not in node_ids or target not in node_ids:
                continue
            incoming[target] += 1
            adjacency[source].add(target)
            adjacency[target].add(source)

        roots: list[str] = []
        remaining = set(node_ids)
        while remaining:
            start = min(remaining)
            component = {start}
            queue = deque([start])
            while queue:
                current = queue.popleft()
                for neighbor in adjacency[current]:
                    if neighbor in component:
                        continue
                    component.add(neighbor)
                    queue.append(neighbor)
            remaining.difference_update(component)
            component_roots = sorted(
                node_id for node_id in component if incoming[node_id] == 0
            )
            roots.extend(component_roots or [min(component)])
        return roots

    def get_courses(
        self, *, user_name: str, course_names: list[str] | None = None
    ) -> dict:
        """获取 `courses` 相关数据。

        Args:
            user_name: str => `user_name` 参数。
            course_names: list[str] | None => `course_names` 参数。

        Returns:
            dict => 处理结果。
        """
        states = {
            state["kp_id"]: state
            for state in self.mastery_store.list_for_user(user_name)
        }
        courses = []
        supported_courses = set(self.kg_store.list_courses())
        selected_courses = (
            self.kg_store.list_courses()
            if course_names is None
            else [course for course in course_names if course in supported_courses]
        )
        for course in selected_courses:
            points = self.kg_store.get_course_points(course)
            course_states = [
                states[point["id"]]
                for point in points
                if point["id"] in states
            ]
            courses.append(
                {
                    "name": course,
                    "total_points": len(points),
                    "evaluated_points": len(course_states),
                    "weak_points": sum(
                        state["status"] == "weak" for state in course_states
                    ),
                    "review_points": sum(
                        bool(state["needs_review"]) for state in course_states
                    ),
                    "average_mastery": (
                        round(
                            sum(state["mastery_level"] for state in course_states)
                            / len(course_states),
                            2,
                        )
                        if course_states
                        else None
                    ),
                }
            )
        return {"courses": courses}

    def get_course_map(self, *, user_name: str, course: str) -> dict:
        """获取 `course map` 相关数据。

        Args:
            user_name: str => `user_name` 参数。
            course: str => `course` 参数。

        Returns:
            dict => 处理结果。
        """
        points = self.kg_store.get_course_points(course)
        if not points:
            return {"course": course, "nodes": [], "edges": []}
        node_ids = {point["id"] for point in points}
        edges = self.kg_store.get_edges(
            course=course, include_external_prerequisites=True
        )
        for edge in edges:
            node_ids.update((edge["from"], edge["to"]))
        all_points = {
            point["id"]: point
            for point in self.kg_store.get_points_by_ids(list(node_ids))
        }
        node_ids.intersection_update(all_points)
        edges = [
            edge
            for edge in edges
            if edge["from"] in node_ids and edge["to"] in node_ids
        ]
        course_node_id = self._course_node_id(course)
        course_edges = [
            {
                "from": course_node_id,
                "to": root_id,
                "type": "course_root",
            }
            for root_id in self._component_roots(node_ids, edges)
        ]
        edges = [*course_edges, *edges]
        levels = self._levels({*node_ids, course_node_id}, edges)
        nodes = []
        for node_id in node_ids:
            point = all_points[node_id]
            state = self.mastery_store.get_state(user_name, node_id)
            summary = self.evidence_store.get_summary(
                user_name, kp_id=node_id, limit=50
            )
            weak_prerequisites = self.mastery_store.get_weak_prerequisites(
                user_name, node_id, self.kg_store
            )
            nodes.append(
                {
                    "id": node_id,
                    "node_type": "knowledge_point",
                    "name": point["name"],
                    "course": point["course"],
                    "category": point["category"],
                    "weight": point["weight"],
                    "external": point["course"] != course,
                    "has_record": state["has_record"],
                    "mastery_level": state["mastery_level"],
                    "status": state["status"],
                    "retention": state["retention"],
                    "evidence_confidence": state["evidence_confidence"],
                    "needs_review": state["needs_review"],
                    "practice_count": state["practice_count"],
                    "evidence_count": summary["evidence_count"],
                    "weak_prerequisite_count": len(weak_prerequisites),
                    "level": levels[node_id],
                }
            )
        nodes.append(
            {
                "id": course_node_id,
                "node_type": "course",
                "name": course,
                "course": course,
                "category": "course",
                "weight": 0.0,
                "external": False,
                "has_record": False,
                "mastery_level": None,
                "status": "course",
                "retention": None,
                "evidence_confidence": None,
                "needs_review": False,
                "practice_count": 0,
                "evidence_count": 0,
                "weak_prerequisite_count": 0,
                "level": levels[course_node_id],
            }
        )
        nodes.sort(
            key=lambda item: (
                item["level"],
                item["node_type"] != "course",
                item["name"],
            )
        )
        return {"course": course, "nodes": nodes, "edges": edges}

    def get_point_detail(self, *, user_name: str, kp_id: str) -> dict | None:
        """获取 `point detail` 相关数据。

        Args:
            user_name: str => `user_name` 参数。
            kp_id: str => kp ID。

        Returns:
            dict | None => 处理结果。
        """
        resolved = self.kg_store.resolve_kp_id(kp_id)
        if resolved is None:
            return None
        point = self.kg_store.get_point(resolved)
        if point is None:
            return None
        return {
            "point": point,
            "state": self.mastery_store.get_state(user_name, resolved),
            "evidence_summary": self.evidence_store.get_summary(
                user_name, kp_id=resolved, limit=50
            ),
            "weak_prerequisites": self.mastery_store.get_weak_prerequisites(
                user_name, resolved, self.kg_store
            ),
        }

    def get_review_queue(
        self, *, user_name: str, course: str | None = None
    ) -> dict:
        """获取 `review queue` 相关数据。

        Args:
            user_name: str => `user_name` 参数。
            course: str | None => `course` 参数。

        Returns:
            dict => 处理结果。
        """
        allowed_ids = None
        if course:
            allowed_ids = {
                point["id"] for point in self.kg_store.get_course_points(course)
            }
        states = self.mastery_store.list_for_user(
            user_name, kp_ids=allowed_ids
        )
        items = []
        for state in states:
            if not state["needs_review"]:
                continue
            point = self.kg_store.get_point(state["kp_id"])
            if point is None:
                continue
            timing = self.mastery_store.get_review_timing(
                user_name, state["kp_id"]
            )
            items.append(
                {
                    "kp_id": state["kp_id"],
                    "name": point["name"],
                    "course": point["course"],
                    "mastery_level": state["mastery_level"],
                    "retention": state["retention"],
                    "evidence_confidence": state["evidence_confidence"],
                    "needs_review": True,
                    "recommended_at": timing["recommended_date"],
                }
            )
        items.sort(key=lambda item: (item["retention"], -item["mastery_level"]))
        return {"items": items}

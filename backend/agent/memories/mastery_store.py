# backend/agent/memories/mastery_store.py

import sqlite3
from datetime import datetime, timedelta
from math import exp, log
from pathlib import Path


class MasteryStore:
    """
    用户掌握度数据层

    为每个 用户-知识点 对维护掌握度评分 随答题动态更新 随长时间未练衰减
    掌握度范围 10-95 不归零不到 100

    理论依据:
        - 衰减算法: Ebbinghaus 遗忘曲线 + HLR (Settles & Meeder 2016)
          R = exp(-Δ/S), S 随练习次数增长 练越多忘越慢
        - 更新算法: Bloom 掌握学习 + BKT (Corbett & Anderson 1995)
          confidence 参数模拟 BKT 的 P(G)/P(S) 概率
        - 优先级公式: desirable difficulties (Bjork 1994) + 过度练习 (Zhang et al. 2025)
        - 复习时机: HLR 半衰期预测 p 降到阈值时触发复习
    """

    # 掌握度边界
    MIN_MASTERY: float = 10.0
    MAX_MASTERY: float = 95.0
    DEFAULT_MASTERY: float = 50.0

    # 衰减参数 (Ebbinghaus 遗忘曲线 + HLR)
    BASE_STABILITY: float = 5.0       # 基础记忆稳定性(天) 初次学习后约 5 天衰减到 1/e
    PRACTICE_FACTOR: float = 2.0      # 每次练习使稳定性增加 2 天
    REVIEW_THRESHOLD: float = 0.7     # 回忆概率低于此值时建议复习

    # 答题更新参数 (Bloom 掌握学习 + BKT)
    CORRECT_DECREMENT_RATE: float = 0.15
    LEARNING_RATE_INIT: float = 0.3
    LEARNING_RATE_MIN: float = 0.05
    LEARNING_RATE_DECAY: float = 0.01

    # 优先级参数 (desirable difficulties + 过度练习研究)
    CHALLENGE_LOW: float = 40.0       # 适度挑战区间下界
    CHALLENGE_HIGH: float = 70.0      # 适度挑战区间上界
    CHALLENGE_BONUS: float = 0.15     # 适度挑战加分
    OVERPRACTICE_MASTERY: float = 85  # 过度练习掌握度阈值
    OVERPRACTICE_COUNT: int = 10      # 过度练习次数阈值
    OVERPRACTICE_PENALTY: float = 0.15  # 过度练习惩罚

    def __init__(
        self,
        database_path: str | Path = "data/mastery.db",
    ) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.__initialize()

    def __connect(self) -> sqlite3.Connection:
        """辅助函数 链接 SQLite 数据库"""
        connection: sqlite3.Connection = sqlite3.connect(
            self.database_path,
        )

        connection.row_factory = sqlite3.Row

        return connection

    def __initialize(self) -> None:
        """辅助函数 初始化 SQLite 数据库"""
        with self.__connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_mastery (
                    user_name TEXT NOT NULL,
                    kp_id TEXT NOT NULL,
                    mastery_level REAL NOT NULL DEFAULT 50.0,
                    practice_count INTEGER NOT NULL DEFAULT 0,
                    correct_count INTEGER NOT NULL DEFAULT 0,
                    last_practiced_at TEXT NOT NULL,
                    last_decay_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_name, kp_id)
                )
                """
            )

            # 旧库迁移: 早期版本列名为 user_id(实际存用户名) 统一改为 user_name
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(user_mastery)").fetchall()
            }
            if "user_id" in columns and "user_name" not in columns:
                connection.execute(
                    "ALTER TABLE user_mastery RENAME COLUMN user_id TO user_name"
                )

    @staticmethod
    def __now_iso() -> str:
        """辅助函数 当前时间 ISO 格式字符串"""
        return datetime.now().isoformat()

    def __compute_decayed_mastery(
        self,
        mastery: float,
        last_practiced_at: str,
        last_decay_at: str,
        practice_count: int,
    ) -> float:
        """辅助函数 计算指数衰减后的掌握度

        基于 Ebbinghaus 遗忘曲线: R = exp(-Δ/S)
        记忆稳定性 S = BASE_STABILITY * (1 + PRACTICE_FACTOR * practice_count)
        练得越多 稳定性越高 衰减越慢

        衰减窗口 从 max(last_decay_at, last_practiced_at) 到 now
        last_decay_at 是上次固化衰减的时间 之前的时间已经衰减过

        Args:
            mastery: float            => 数据库中的掌握度
            last_practiced_at: str    => 上次练习时间 ISO
            last_decay_at: str        => 上次衰减固化时间 ISO
            practice_count: int       => 练习次数 影响记忆稳定性

        Returns:
            float                     => 衰减后掌握度 不低于 MIN_MASTERY
        """
        now = datetime.now()
        last_practiced = datetime.fromisoformat(last_practiced_at)
        last_decay = datetime.fromisoformat(last_decay_at)

        # 衰减起点 取 上次固化时间 与 上次练习时间 的较大者
        decay_start = max(last_decay, last_practiced)

        if now <= decay_start:
            return mastery

        days = (now - decay_start).total_seconds() / 86400.0  # 转为天(含小数)

        if days <= 0:
            return mastery

        # 记忆稳定性 练得越多越不容易忘
        stability = self.BASE_STABILITY * (1.0 + self.PRACTICE_FACTOR * practice_count)

        # 指数衰减 R = exp(-Δ/S)
        retention = exp(-days / stability)

        decayed = mastery * retention

        return max(self.MIN_MASTERY, decayed)

    def __compute_retention(
        self,
        mastery: float,
        last_practiced_at: str,
        last_decay_at: str,
        practice_count: int,
    ) -> float:
        """辅助函数 计算当前回忆概率 (0-1)

        基于 HLR: p = exp(-Δ/S)
        用于复习时机预测

        Returns:
            float => 回忆概率 0.0-1.0
        """
        now = datetime.now()
        last_practiced = datetime.fromisoformat(last_practiced_at)
        last_decay = datetime.fromisoformat(last_decay_at)

        decay_start = max(last_decay, last_practiced)
        days = (now - decay_start).total_seconds() / 86400.0

        if days <= 0:
            return 1.0

        stability = self.BASE_STABILITY * (1.0 + self.PRACTICE_FACTOR * practice_count)
        return exp(-days / stability)

    def get(
        self,
        user_name: str,
        kp_id: str,
    ) -> dict | None:
        """获取数据库中单条掌握度记录 不存在返回 None

        Args:
            user_name: str  => 用户名称
            kp_id: str    => 知识点 id

        Returns:
            dict | None   => 记录字典 含 mastery_level(已衰减) practice_count correct_count last_practiced_at
        """
        user_name = user_name.strip()
        kp_id = kp_id.strip()

        if not user_name or not kp_id:
            return None

        with self.__connect() as connection:
            row = connection.execute(
                """
                SELECT user_name, kp_id, mastery_level, practice_count, correct_count,
                       last_practiced_at, last_decay_at, created_at, updated_at
                FROM user_mastery
                WHERE user_name = ? AND kp_id = ?
                """,
                (user_name, kp_id),
            ).fetchone()

        if row is None:
            return None

        # 返回实时衰减后的掌握度 不写库
        decayed = self.__compute_decayed_mastery(
            row["mastery_level"],
            row["last_practiced_at"],
            row["last_decay_at"],
            row["practice_count"],
        )

        return {
            "user_name": row["user_name"],
            "kp_id": row["kp_id"],
            "mastery_level": round(decayed, 2),
            "practice_count": row["practice_count"],
            "correct_count": row["correct_count"],
            "last_practiced_at": row["last_practiced_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_mastery_level(
        self,
        user_name: str,
        kp_id: str,
    ) -> float:
        """获取某知识点的掌握度 不存在返回默认值 50.0

        Args:
            user_name: str  => 用户名称
            kp_id: str    => 知识点 id

        Returns:
            float         => 掌握度 10-95 不存在返回 50.0
        """
        record = self.get(user_name, kp_id)

        if record is None:
            return self.DEFAULT_MASTERY

        return record["mastery_level"]

    def record_answer(
        self,
        user_name: str,
        kp_id: str,
        correct: bool,
        confidence: float = 1.0,
    ) -> dict:
        """记录一次答题并更新掌握度

        答对 min(95, mastery + learning_rate * (1 - mastery/100) * confidence)
            learning_rate = max(0.05, 0.3 * exp(-0.01 * practice_count))
            confidence 模拟 BKT 的 P(G) 低置信度答对增幅打折
        答错 max(10, mastery - 0.15 * (mastery/100) * confidence)
            confidence 模拟 BKT 的 P(S) 低置信度答错减幅打折

        Args:
            user_name: str        => 用户名称
            kp_id: str          => 知识点 id
            correct: bool       => 是否答对
            confidence: float   => 答题置信度 0.0-1.0
                                   1.0 = 高置信度 (填空/编程/证明)
                                   0.5 = 低置信度 (选择题 可能蒙对)

        Returns:
            dict                => 更新后的记录 含 mastery_level practice_count correct_count
        """
        user_name = user_name.strip()
        kp_id = kp_id.strip()
        confidence = max(0.0, min(1.0, confidence))

        if not user_name or not kp_id:
            return {
                "user_name": user_name,
                "kp_id": kp_id,
                "mastery_level": self.DEFAULT_MASTERY,
                "practice_count": 0,
                "correct_count": 0,
                "last_practiced_at": self.__now_iso(),
            }

        now_iso = self.__now_iso()

        with self.__connect() as connection:
            row = connection.execute(
                """
                SELECT mastery_level, practice_count, correct_count,
                       last_practiced_at, last_decay_at
                FROM user_mastery
                WHERE user_name = ? AND kp_id = ?
                """,
                (user_name, kp_id),
            ).fetchone()

            if row is None:
                # 新记录 初始化
                mastery = self.DEFAULT_MASTERY
                practice_count = 0
                correct_count = 0
                last_practiced_at = now_iso
                last_decay_at = now_iso
                created_at = now_iso
            else:
                # 先计算衰减后的掌握度 再应用答题更新
                mastery = self.__compute_decayed_mastery(
                    row["mastery_level"],
                    row["last_practiced_at"],
                    row["last_decay_at"],
                    row["practice_count"],
                )
                practice_count = row["practice_count"]
                correct_count = row["correct_count"]
                last_practiced_at = row["last_practiced_at"]
                last_decay_at = row["last_decay_at"]
                created_at = None  # 已存在不更新

            # 应用答题更新 (confidence 模拟 BKT 的 P(G)/P(S))
            if correct:
                learning_rate = max(
                    self.LEARNING_RATE_MIN,
                    self.LEARNING_RATE_INIT * exp(-self.LEARNING_RATE_DECAY * practice_count),
                )
                increment = learning_rate * (1.0 - mastery / 100.0) * confidence
                mastery = min(
                    self.MAX_MASTERY,
                    mastery + increment,
                )
                correct_count += 1
            else:
                decrement = self.CORRECT_DECREMENT_RATE * (mastery / 100.0) * confidence
                mastery = max(self.MIN_MASTERY, mastery - decrement)

            practice_count += 1

            # 练习后重置衰减基准
            last_practiced_at = now_iso
            last_decay_at = now_iso

            if created_at is None:
                # 更新已有记录
                connection.execute(
                    """
                    UPDATE user_mastery
                    SET mastery_level = ?,
                        practice_count = ?,
                        correct_count = ?,
                        last_practiced_at = ?,
                        last_decay_at = ?,
                        updated_at = ?
                    WHERE user_name = ? AND kp_id = ?
                    """,
                    (
                        round(mastery, 4),
                        practice_count,
                        correct_count,
                        last_practiced_at,
                        last_decay_at,
                        now_iso,
                        user_name,
                        kp_id,
                    ),
                )
            else:
                # 插入新记录
                connection.execute(
                    """
                    INSERT INTO user_mastery
                        (user_name, kp_id, mastery_level, practice_count, correct_count,
                         last_practiced_at, last_decay_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_name,
                        kp_id,
                        round(mastery, 4),
                        practice_count,
                        correct_count,
                        last_practiced_at,
                        last_decay_at,
                        created_at,
                        now_iso,
                    ),
                )

        return {
            "user_name": user_name,
            "kp_id": kp_id,
            "mastery_level": round(mastery, 2),
            "practice_count": practice_count,
            "correct_count": correct_count,
            "last_practiced_at": last_practiced_at,
        }

    def apply_decay(
        self,
        user_name: str,
    ) -> int:
        """对某用户的所有掌握度记录执行衰减固化

        遍历该用户全部记录 计算实时指数衰减 写回 mastery_level 并重置 last_decay_at
        适用于定期任务 如每日凌晨批量衰减

        Args:
            user_name: str  => 用户名称

        Returns:
            int           => 实际衰减的记录数
        """
        user_name = user_name.strip()

        if not user_name:
            return 0

        now_iso = self.__now_iso()
        count = 0

        with self.__connect() as connection:
            rows = connection.execute(
                """
                SELECT kp_id, mastery_level, practice_count, last_practiced_at, last_decay_at
                FROM user_mastery
                WHERE user_name = ?
                """,
                (user_name,),
            ).fetchall()

            for row in rows:
                decayed = self.__compute_decayed_mastery(
                    row["mastery_level"],
                    row["last_practiced_at"],
                    row["last_decay_at"],
                    row["practice_count"],
                )

                # 跳过未衰减的记录
                if abs(decayed - row["mastery_level"]) < 0.01:
                    continue

                connection.execute(
                    """
                    UPDATE user_mastery
                    SET mastery_level = ?,
                        last_decay_at = ?,
                        updated_at = ?
                    WHERE user_name = ? AND kp_id = ?
                    """,
                    (
                        round(decayed, 4),
                        now_iso,
                        now_iso,
                        user_name,
                        row["kp_id"],
                    ),
                )
                count += 1

        return count

    def get_top_weak(
        self,
        user_name: str,
        k: int = 3,
    ) -> list[dict]:
        """获取用户掌握度最低的 k 个知识点

        Args:
            user_name: str   => 用户名称
            k: int = 3     => 返回数量

        Returns:
            list[dict]     => 掌握度升序列表 含 kp_id mastery_level practice_count last_practiced_at
        """
        return self.__query_top_points(
            user_name=user_name,
            k=k,
            ascending=True,
        )

    def get_top_strong(
        self,
        user_name: str,
        k: int = 3,
    ) -> list[dict]:
        """获取用户掌握度最高的 k 个知识点

        Args:
            user_name: str   => 用户名称
            k: int = 3     => 返回数量

        Returns:
            list[dict]     => 掌握度降序列表
        """
        return self.__query_top_points(
            user_name=user_name,
            k=k,
            ascending=False,
        )

    def __query_top_points(
        self,
        user_name: str,
        k: int,
        ascending: bool,
    ) -> list[dict]:
        """查询掌握度最低或最高的 k 个知识点

        Args:
            user_name: str      => 用户名称
            k: int            => 返回数量
            ascending: bool   => True 按掌握度升序(最弱) False 按降序(最强)

        Returns:
            list[dict]        => 知识点列表 含 kp_id mastery_level practice_count correct_count last_practiced_at
        """
        user_name = user_name.strip()

        if not user_name or k <= 0:
            return []

        # order 仅来自布尔参数的两个固定常量 无注入风险
        order = "ASC" if ascending else "DESC"

        with self.__connect() as connection:
            rows = connection.execute(
                f"""
                SELECT kp_id, mastery_level, practice_count, correct_count,
                       last_practiced_at, last_decay_at
                FROM user_mastery
                WHERE user_name = ?
                ORDER BY mastery_level {order}, kp_id ASC
                LIMIT ?
                """,
                (user_name, k),
            ).fetchall()

        results = []
        for row in rows:
            decayed = self.__compute_decayed_mastery(
                row["mastery_level"],
                row["last_practiced_at"],
                row["last_decay_at"],
                row["practice_count"],
            )
            results.append(
                {
                    "kp_id": row["kp_id"],
                    "mastery_level": round(decayed, 2),
                    "practice_count": row["practice_count"],
                    "correct_count": row["correct_count"],
                    "last_practiced_at": row["last_practiced_at"],
                }
            )

        return results

    def get_report(
        self,
        user_name: str,
        course: str | None = None,
        kg_store=None,
    ) -> dict:
        """获取用户掌握度报告

        Args:
            user_name: str          => 用户名称
            course: str | None    => 课程名 None 表示全部
            kg_store: KnowledgeGraphStore | None => 知识图谱数据层 course 非空时必需

        Returns:
            dict                  => 报告:
                user_name, course, total_points, avg_mastery
                weak_points (掌握度最低 5 个)
                strong_points (掌握度最高 5 个)
                stale_points (超过 7 天未练习)
        """
        user_name = user_name.strip()

        empty = {
            "user_name": user_name,
            "course": course,
            "total_points": 0,
            "avg_mastery": 0.0,
            "weak_points": [],
            "strong_points": [],
            "stale_points": [],
        }

        if not user_name:
            return empty

        # 若指定课程 从 kg_store 获取该课程知识点 id 集合
        course_kp_ids: set[str] | None = None
        if course and course.strip():
            if kg_store is None:
                return {**empty, "error": "kg_store is required when course is specified"}
            course_points = kg_store.get_course_points(course.strip())
            course_kp_ids = {pt["id"] for pt in course_points}
            if not course_kp_ids:
                return empty

        with self.__connect() as connection:
            rows = connection.execute(
                """
                SELECT kp_id, mastery_level, practice_count, correct_count,
                       last_practiced_at, last_decay_at
                FROM user_mastery
                WHERE user_name = ?
                """,
                (user_name,),
            ).fetchall()

        # 在 Python 层过滤课程
        if course_kp_ids is not None:
            rows = [row for row in rows if row["kp_id"] in course_kp_ids]

        if not rows:
            return empty

        now = datetime.now()
        points = []
        for row in rows:
            decayed = self.__compute_decayed_mastery(
                row["mastery_level"],
                row["last_practiced_at"],
                row["last_decay_at"],
                row["practice_count"],
            )
            last_practiced = datetime.fromisoformat(row["last_practiced_at"])
            days_since = (now - last_practiced).days
            points.append(
                {
                    "kp_id": row["kp_id"],
                    "mastery_level": round(decayed, 2),
                    "practice_count": row["practice_count"],
                    "correct_count": row["correct_count"],
                    "last_practiced_at": row["last_practiced_at"],
                    "days_since_practice": days_since,
                }
            )

        avg_mastery = round(sum(p["mastery_level"] for p in points) / len(points), 2)

        weak = sorted(points, key=lambda x: x["mastery_level"])[:5]
        strong = sorted(points, key=lambda x: -x["mastery_level"])[:5]
        stale = sorted(
            [p for p in points if p["days_since_practice"] > 7],
            key=lambda x: -x["days_since_practice"],
        )[:5]

        return {
            "user_name": user_name,
            "course": course,
            "total_points": len(points),
            "avg_mastery": avg_mastery,
            "weak_points": weak,
            "strong_points": strong,
            "stale_points": stale,
        }

    def get_priority_ranking(
        self,
        user_name: str,
        course: str,
        weeks_to_exam: int,
        total_weeks: int,
        kg_store,
    ) -> list[dict]:
        """计算某课程内知识点的推荐优先级排序

        优先级 = 基础分 + 适度挑战加分 - 过度练习惩罚

        基础分 = 0.4*(1-mastery/100) + 0.25*weight + 0.15*time_factor
          掌握度越低 权重越高 距期末越近 优先级越高

        适度挑战加分 (desirable difficulties, Bjork 1994):
          mastery 在 40-70 范围 +0.15 (适度挑战促进学习)
          mastery 在 30-40 或 70-80 范围 +0.075 (边缘区间)

        过度练习惩罚 (Zhang et al. 2025, over-practice 占 58%):
          mastery > 85 且 practice_count > 10 时 -0.15

        Args:
            user_name: str            => 用户名称
            course: str             => 课程名
            weeks_to_exam: int      => 距期末周数
            total_weeks: int        => 学期总周数
            kg_store: KnowledgeGraphStore => 知识图谱数据层

        Returns:
            list[dict]              => 优先级降序列表:
                kp_id, name, course, weight, mastery_level, practice_count, priority
        """
        user_name = user_name.strip()
        course = course.strip()

        if not user_name or not course:
            return []

        course_points = kg_store.get_course_points(course)
        if not course_points:
            return []

        # 时间因子
        time_factor = 0.0
        if total_weeks > 0:
            time_factor = max(0.0, 1.0 - weeks_to_exam / total_weeks)

        # 一次性批量读取该用户全部掌握度记录 避免循环内逐条开库查询
        records: dict[str, dict] = {}
        with self.__connect() as connection:
            rows = connection.execute(
                """
                SELECT kp_id, mastery_level, practice_count, last_practiced_at, last_decay_at
                FROM user_mastery
                WHERE user_name = ?
                """,
                (user_name,),
            ).fetchall()

        for row in rows:
            decayed = self.__compute_decayed_mastery(
                row["mastery_level"],
                row["last_practiced_at"],
                row["last_decay_at"],
                row["practice_count"],
            )
            records[row["kp_id"]] = {
                "mastery_level": round(decayed, 2),
                "practice_count": row["practice_count"],
            }

        results = []
        for pt in course_points:
            kp_id = pt["id"]
            weight = pt["weight"]

            # 读取掌握度和练习次数
            record = records.get(kp_id)
            if record is None:
                mastery = self.DEFAULT_MASTERY
                practice_count = 0
            else:
                mastery = record["mastery_level"]
                practice_count = record["practice_count"]

            # 基础优先级
            base = 0.4 * (1.0 - mastery / 100.0) + 0.25 * weight + 0.15 * time_factor

            # 适度挑战加分 (desirable difficulties)
            if self.CHALLENGE_LOW <= mastery <= self.CHALLENGE_HIGH:
                challenge = self.CHALLENGE_BONUS
            elif 30.0 <= mastery < self.CHALLENGE_LOW or self.CHALLENGE_HIGH < mastery <= 80.0:
                challenge = self.CHALLENGE_BONUS * 0.5
            else:
                challenge = 0.0

            # 过度练习惩罚
            if mastery > self.OVERPRACTICE_MASTERY and practice_count > self.OVERPRACTICE_COUNT:
                penalty = self.OVERPRACTICE_PENALTY
            else:
                penalty = 0.0

            priority = base + challenge - penalty

            results.append(
                {
                    "kp_id": kp_id,
                    "name": pt["name"],
                    "course": course,
                    "weight": weight,
                    "mastery_level": mastery,
                    "practice_count": practice_count,
                    "priority": round(priority, 4),
                }
            )

        results.sort(key=lambda x: -x["priority"])
        return results

    def get_review_timing(
        self,
        user_name: str,
        kp_id: str,
        threshold: float | None = None,
    ) -> dict:
        """预测复习时机 (基于 HLR 半衰期模型)

        回忆概率 p = exp(-Δ/S)
        预测 p 降到 threshold 时的天数 Δ = -S * ln(threshold)
        当 p 低于 threshold 时建议立即复习

        Args:
            user_name: str              => 用户名称
            kp_id: str                => 知识点 id
            threshold: float | None   => 复习触发阈值 默认 REVIEW_THRESHOLD (0.7)

        Returns:
            dict => {
                needs_review: bool          # 当前是否需要复习
                current_retention: float    # 当前回忆概率 0-1
                days_until_review: int      # 距推荐复习的天数 (0=立即)
                recommended_date: str       # 推荐复习日期 ISO
                stability_days: float       # 记忆稳定性(天) 越大越不容易忘
                practice_count: int         # 练习次数
            }
        """
        if threshold is None:
            threshold = self.REVIEW_THRESHOLD

        user_name = user_name.strip()
        kp_id = kp_id.strip()

        empty = {
            "needs_review": True,
            "current_retention": 0.0,
            "days_until_review": 0,
            "recommended_date": datetime.now().date().isoformat(),
            "stability_days": self.BASE_STABILITY,
            "practice_count": 0,
        }

        if not user_name or not kp_id:
            return empty

        with self.__connect() as connection:
            row = connection.execute(
                """
                SELECT mastery_level, practice_count, last_practiced_at, last_decay_at
                FROM user_mastery
                WHERE user_name = ? AND kp_id = ?
                """,
                (user_name, kp_id),
            ).fetchone()

        if row is None:
            return empty

        practice_count = row["practice_count"]
        stability = self.BASE_STABILITY * (1.0 + self.PRACTICE_FACTOR * practice_count)

        # 当前回忆概率
        retention = self.__compute_retention(
            row["mastery_level"],
            row["last_practiced_at"],
            row["last_decay_at"],
            practice_count,
        )

        # 已经过去的天数（从衰减起点到现在）
        now = datetime.now()
        last_practiced = datetime.fromisoformat(row["last_practiced_at"])
        last_decay = datetime.fromisoformat(row["last_decay_at"])
        decay_start = max(last_decay, last_practiced)
        days_elapsed = (now - decay_start).total_seconds() / 86400.0

        # 从衰减起点到 retention 降到 threshold 的总天数
        total_days_to_threshold = -stability * log(threshold)

        # 从现在开始的剩余天数 = 总天数 - 已过天数
        days_until = max(0, int(total_days_to_threshold - days_elapsed))

        recommended_date = (now + timedelta(days=days_until)).date().isoformat()

        return {
            "needs_review": retention < threshold,
            "current_retention": round(retention, 3),
            "days_until_review": days_until,
            "recommended_date": recommended_date,
            "stability_days": round(stability, 1),
            "practice_count": practice_count,
        }

    def get_weak_prerequisites(
        self,
        user_name: str,
        kp_id: str,
        kg_store,
        mastery_threshold: float = 50.0,
        max_depth: int = 5,
    ) -> list[dict]:
        """追溯薄弱的前置知识点

        从知识图谱获取 kp_id 的全部前置知识点(BFS)
        筛选掌握度低于阈值的 按深度降序排列(最深层的前置最先补)

        用于推理引擎决策: 直接推题 vs 先补前置

        Args:
            user_name: str              => 用户名称
            kp_id: str                => 目标知识点 id
            kg_store: KnowledgeGraphStore => 知识图谱数据层
            mastery_threshold: float  => 薄弱判定阈值 默认 50.0
            max_depth: int            => 最大追溯深度 默认 5

        Returns:
            list[dict] => 薄弱前置知识点列表:
                kp_id, name, course, depth, mastery_level
        """
        user_name = user_name.strip()
        kp_id = kp_id.strip()

        if not user_name or not kp_id:
            return []

        # 从知识图谱获取前置链
        prereqs = kg_store.get_prerequisites(kp_id, max_depth=max_depth)

        if not prereqs:
            return []

        # 一次性批量读取该用户全部掌握度记录 避免循环内逐条开库查询
        mastery_by_kp: dict[str, float] = {}
        with self.__connect() as connection:
            rows = connection.execute(
                """
                SELECT kp_id, mastery_level, practice_count, last_practiced_at, last_decay_at
                FROM user_mastery
                WHERE user_name = ?
                """,
                (user_name,),
            ).fetchall()

        for row in rows:
            decayed = self.__compute_decayed_mastery(
                row["mastery_level"],
                row["last_practiced_at"],
                row["last_decay_at"],
                row["practice_count"],
            )
            mastery_by_kp[row["kp_id"]] = round(decayed, 2)

        weak = []
        for p in prereqs:
            mastery = mastery_by_kp.get(p["kp_id"], self.DEFAULT_MASTERY)
            if mastery < mastery_threshold:
                weak.append(
                    {
                        "kp_id": p["kp_id"],
                        "name": p["name"],
                        "course": p["course"],
                        "depth": p["depth"],
                        "mastery_level": mastery,
                    }
                )

        # 按 depth 降序 (最深层的前置最先补)
        weak.sort(key=lambda x: -x["depth"])
        return weak

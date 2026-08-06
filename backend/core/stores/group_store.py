# backend/core/stores/group_store.py

import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from backend.core.stores.base_sqlite_store import BaseSQLiteStore


class GroupStore(BaseSQLiteStore):
    """
    对话分组读写类

    groups 表存用户自定义的分组 conversations 通过 group_id 归组
    方法统一返回 dict 方便 FastAPI 直接序列化成 JSON 返回给前端
    """

    # 允许动态更新的字段白名单 防止字段名被拼进 SQL SET 子句
    _UPDATEABLE_FIELDS = frozenset(
        {"name", "description", "custom_instruction", "style", "tone"}
    )

    def __init__(self, database_path: str | Path = "data/esa.db") -> None:
        super().__init__(database_path)

    def _initialize(self) -> None:
        """辅助函数 初始化 groups 表"""
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS groups (
                    group_id           TEXT PRIMARY KEY,
                    user_id            TEXT NOT NULL,
                    name               TEXT NOT NULL,
                    description        TEXT NOT NULL DEFAULT '',
                    custom_instruction TEXT NOT NULL DEFAULT '',
                    style              TEXT,
                    tone               TEXT,
                    created_at         TEXT NOT NULL,
                    updated_at         TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_groups_user
                ON groups (user_id, updated_at)
                """
            )

    @staticmethod
    def _now() -> str:
        """辅助函数 当前 UTC 时间的 ISO 字符串"""
        return datetime.now(timezone.utc).isoformat()

    def create_group(
        self,
        user_id: str,
        name: str,
        description: str = "",
        custom_instruction: str = "",
        style: str | None = None,
        tone: str | None = None,
        group_limit: int | None = None,
    ) -> dict | None:
        """创建一个新分组
        Args:
            user_id: str                  => 用户 id
            name: str                     => 分组名称(必填)
            description: str = ""         => 分组描述(选填)
            custom_instruction: str = ""  => 分组内自定义指令(选填)
            style: str | None = None      => 分组级风格  None 表示继承用户级
            tone: str | None = None       => 分组级语调  None 表示继承用户级
            group_limit: int | None = None => 分组数量上限 传入时在事务内
                                              校验 达到上限返回 None 不创建
                                              防止并发请求突破上限

        Returns:
            dict | None:
                dict => 新建分组的完整信息
                None => 分组数量已达上限
        """
        group: dict = {
            "group_id": str(uuid.uuid4()),
            "user_id": user_id,
            "name": name,
            "description": description,
            "custom_instruction": custom_instruction,
            "style": style,
            "tone": tone,
            "created_at": self._now(),
            "updated_at": self._now(),
        }

        with closing(self._connect()) as connection, connection:
            if group_limit is not None:
                # BEGIN IMMEDIATE 获取写锁 把"计数+插入"串行化
                # 保证并发建组时不会两个请求同时通过上限校验
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM groups
                    WHERE user_id = ?
                    """,
                    (user_id,),
                ).fetchone()
                if int(row["count"]) >= group_limit:
                    # 已达上限 回滚事务 返回 None 由路由层转 409
                    connection.rollback()
                    return None

            connection.execute(
                """
                INSERT INTO groups (
                    group_id,
                    user_id,
                    name,
                    description,
                    custom_instruction,
                    style,
                    tone,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    group["group_id"],
                    group["user_id"],
                    group["name"],
                    group["description"],
                    group["custom_instruction"],
                    group["style"],
                    group["tone"],
                    group["created_at"],
                    group["updated_at"],
                ),
            )
            # with connection 上下文正常退出时自动 commit

        return group

    def get_group(self, group_id: str) -> dict | None:
        """获取单个分组的信息(含真实对话数)
        Args:
            group_id: str => 分组 id

        Returns:
            dict | None:
                dict => 分组信息 含 conversation_count
                None => 分组不存在
        """
        row = self.query_one(
            """
            SELECT g.group_id, g.user_id, g.name, g.description,
                   g.custom_instruction, g.style, g.tone,
                   g.created_at, g.updated_at,
                   (SELECT COUNT(*) FROM conversations c
                    WHERE c.group_id = g.group_id) AS conversation_count
            FROM groups g
            WHERE g.group_id = ?
            """,
            (group_id,),
        )

        if row is None:
            return None

        return dict(row)

    def list_groups(self, user_id: str) -> list[dict]:
        """获取用户的分组列表 含每组对话数 按最近更新排序

        Args:
            user_id: str => 用户 id

        Returns:
            list[dict]   => 分组信息列表 每组含 conversation_count
        """
        rows = self.query_all(
            """
            SELECT g.group_id, g.user_id, g.name, g.description,
                   g.custom_instruction, g.style, g.tone,
                   g.created_at, g.updated_at,
                   COUNT(c.conversation_id) AS conversation_count
            FROM groups g
            LEFT JOIN conversations c ON c.group_id = g.group_id
            WHERE g.user_id = ?
            GROUP BY g.group_id
            ORDER BY g.updated_at DESC
            """,
            (user_id,),
        )

        return [dict(row) for row in rows]

    def update_group(self, group_id: str, **fields: str | None) -> bool:
        """部分更新分组 只更新传入的字段

        注意: 语义上"把 style/tone 改回继承用户级"需显式传 None
        因此这里把 None 也作为有效更新值 路由层用 exclude_unset 过滤未传字段
        仅白名单内的字段允许更新 其余字段抛 ValueError 拒绝执行
        updated_at 由本方法内部刷新 不接受外部传入

        Args:
            group_id: str           => 分组 id
            **fields: str | None    => 要更新的字段名到值的映射

        Returns:
            bool                    => 是否更新成功 分组不存在时返回 False

        Raises:
            ValueError              => 传入白名单之外的字段时
        """
        # 字段白名单过滤 防止字段名被拼进 SQL SET 子句
        unknown = set(fields) - self._UPDATEABLE_FIELDS
        if unknown:
            raise ValueError(f"不允许更新的字段: {sorted(unknown)}")

        if not fields:
            return True

        fields["updated_at"] = self._now()
        set_clause = ", ".join(f"{name} = ?" for name in fields)
        params = (*fields.values(), group_id)

        count = self.execute(
            f"""
            UPDATE groups
            SET {set_clause}
            WHERE group_id = ?
            """,
            params,
        )

        return count > 0

    def delete_group(self, group_id: str, user_id: str) -> bool:
        """删除分组 组内对话自动移回未分组(事务内完成)
        Args:
            group_id: str => 分组 id
            user_id: str  => 用户 id 用于校验归属 防止误删他人分组

        Returns:
            bool          => 是否删除成功 分组不存在或不属于该用户时返回 False
        """
        with closing(self._connect()) as connection, connection:
            # 先置回未分组 再删分组 保证中途失败也不会留下孤儿 group_id
            connection.execute(
                """
                UPDATE conversations
                SET group_id = NULL
                WHERE group_id = ? AND user_id = ?
                """,
                (group_id, user_id),
            )
            cursor = connection.execute(
                """
                DELETE FROM groups
                WHERE group_id = ? AND user_id = ?
                """,
                (group_id, user_id),
            )

        return cursor.rowcount > 0

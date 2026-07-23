# backend/core/stores/base_sqlite_store.py

import sqlite3
from contextlib import closing
from pathlib import Path


class BaseSQLiteStore:
    """
    基础的 SQLite 读写类

    子类需要实现 _initialize() 来建自己的数据表
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        """辅助函数 连接 SQLite 数据库
        Returns:
            sqlite3.Connection => 数据库连接对象
        """
        connection: sqlite3.Connection = sqlite3.connect(
            self.database_path,
        )

        connection.row_factory = sqlite3.Row

        return connection

    def _initialize(self) -> None:
        """辅助函数 初始化数据表 由子类实现"""
        raise NotImplementedError

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        """查询单条记录
        Args:
            sql: str      => SQL 查询语句
            params: tuple => 查询参数

        Returns:
            sqlite3.Row | None:
                sqlite3.Row => 查到的记录
                None        => 没有匹配的记录
        """
        with closing(self._connect()) as connection:
            return connection.execute(sql, params).fetchone()

    def query_all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """查询多条记录
        Args:
            sql: str      => SQL 查询语句
            params: tuple => 查询参数

        Returns:
            list[sqlite3.Row] => 查到的记录列表
        """
        with closing(self._connect()) as connection:
            return connection.execute(sql, params).fetchall()

    def execute(self, sql: str, params: tuple = ()) -> int:
        """执行写入类语句并提交事务
        Args:
            sql: str      => SQL 写入语句
            params: tuple => 语句参数

        Returns:
            int           => 受影响的行数
        """
        with closing(self._connect()) as connection, connection:
            cursor: sqlite3.Cursor = connection.execute(sql, params)
            return cursor.rowcount

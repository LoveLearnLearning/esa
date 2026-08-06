"""定期清理过期的画像维度记录

作为 cron job 运行:
    0 3 * * * python -m backend.scripts.cleanup_profile_dimensions --retention-days 90

清理规则:
    - expires_at 已过期的记录
    - status=suppressed 且 updated_at 超过 retention_days 天的记录
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from backend.core.stores.profile_store import ProfileStore


def cleanup(retention_days: int, db_path: str | Path) -> int:
    """执行清理 返回删除的记录数

    Args:
        retention_days: int        => suppressed 记录的保留天数
        db_path: str | Path        => SQLite 数据库路径

    Returns:
        int => 删除的记录数
    """
    store = ProfileStore(db_path)
    return store.cleanup_expired_dimensions(retention_days=retention_days)


def main() -> int:
    parser = argparse.ArgumentParser(description="清理过期的画像维度记录")
    parser.add_argument(
        "--retention-days",
        type=int,
        default=90,
        help="suppressed 记录的保留天数 (默认 90)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default="data/esa.db",
        help="SQLite 数据库路径 (默认 data/esa.db)",
    )
    args = parser.parse_args()

    try:
        deleted = cleanup(retention_days=args.retention_days, db_path=args.db_path)
    except Exception as exc:
        print(f"清理失败: {exc}", file=sys.stderr)
        return 1

    print(
        f"清理完成: 删除 {deleted} 条过期画像维度记录 "
        f"(retention_days={args.retention_days}, db_path={args.db_path})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

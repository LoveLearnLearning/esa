"""Persistent, single-use email verification challenges."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.core.stores.base_sqlite_store import BaseSQLiteStore


@dataclass(frozen=True)
class IssueResult:
    verification_id: str
    retry_after_seconds: int = 0


class VerificationRateLimited(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("email verification rate limit exceeded")
        self.retry_after_seconds = max(1, retry_after_seconds)


class EmailVerificationStore(BaseSQLiteStore):
    def __init__(self, database_path: str | Path = "data/esa.db") -> None:
        super().__init__(database_path)

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS email_verification_codes (
                    verification_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL COLLATE NOCASE,
                    purpose TEXT NOT NULL,
                    code_digest TEXT NOT NULL,
                    requested_ip TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    CHECK(purpose IN ('register', 'bind'))
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_email_codes_email_created
                ON email_verification_codes(email, purpose, created_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_email_codes_ip_created
                ON email_verification_codes(requested_ip, created_at)
                """
            )

    def issue(
        self,
        *,
        email: str,
        purpose: str,
        code_digest: str,
        requested_ip: str,
        ttl_seconds: int,
        cooldown_seconds: int,
        email_hourly_limit: int,
        ip_hourly_limit: int,
        max_attempts: int,
        now: datetime | None = None,
    ) -> IssueResult:
        current = now or datetime.now(timezone.utc)
        current_iso = current.isoformat()
        hour_ago = (current - timedelta(hours=1)).isoformat()
        retention_cutoff = (current - timedelta(days=1)).isoformat()
        verification_id = str(uuid.uuid4())

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM email_verification_codes WHERE created_at < ?",
                (retention_cutoff,),
            )
            latest = connection.execute(
                """
                SELECT created_at FROM email_verification_codes
                WHERE email = ? COLLATE NOCASE AND purpose = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (email, purpose),
            ).fetchone()
            if latest is not None:
                elapsed = (current - datetime.fromisoformat(latest["created_at"])).total_seconds()
                if elapsed < cooldown_seconds:
                    raise VerificationRateLimited(int(cooldown_seconds - elapsed + 0.999))

            email_count = connection.execute(
                """
                SELECT COUNT(*) AS value FROM email_verification_codes
                WHERE email = ? COLLATE NOCASE AND created_at >= ?
                """,
                (email, hour_ago),
            ).fetchone()["value"]
            ip_count = connection.execute(
                """
                SELECT COUNT(*) AS value FROM email_verification_codes
                WHERE requested_ip = ? AND created_at >= ?
                """,
                (requested_ip, hour_ago),
            ).fetchone()["value"]
            if email_count >= email_hourly_limit or ip_count >= ip_hourly_limit:
                raise VerificationRateLimited(3600)

            connection.execute(
                """
                UPDATE email_verification_codes SET consumed_at = ?
                WHERE email = ? COLLATE NOCASE AND purpose = ? AND consumed_at IS NULL
                """,
                (current_iso, email, purpose),
            )
            connection.execute(
                """
                INSERT INTO email_verification_codes (
                    verification_id, email, purpose, code_digest, requested_ip,
                    max_attempts, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    verification_id,
                    email,
                    purpose,
                    code_digest,
                    requested_ip,
                    max_attempts,
                    current_iso,
                    (current + timedelta(seconds=ttl_seconds)).isoformat(),
                ),
            )
            connection.commit()
            return IssueResult(verification_id=verification_id)
        except (sqlite3.Error, VerificationRateLimited):
            connection.rollback()
            raise
        finally:
            connection.close()

    def revoke(self, verification_id: str) -> None:
        self.execute(
            "UPDATE email_verification_codes SET consumed_at = ? WHERE verification_id = ?",
            (datetime.now(timezone.utc).isoformat(), verification_id),
        )

    def discard(self, verification_id: str) -> None:
        """Remove an undelivered challenge so it does not consume rate quota."""
        self.execute(
            "DELETE FROM email_verification_codes WHERE verification_id = ?",
            (verification_id,),
        )

    def consume(
        self,
        *,
        email: str,
        purpose: str,
        code_digest: str,
        now: datetime | None = None,
    ) -> str:
        """Return ok/invalid/expired/attempts_exceeded and atomically consume on success."""
        import hmac

        current = now or datetime.now(timezone.utc)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM email_verification_codes
                WHERE email = ? COLLATE NOCASE AND purpose = ? AND consumed_at IS NULL
                ORDER BY created_at DESC LIMIT 1
                """,
                (email, purpose),
            ).fetchone()
            if row is None:
                connection.commit()
                return "invalid"
            if datetime.fromisoformat(row["expires_at"]) <= current:
                connection.execute(
                    "UPDATE email_verification_codes SET consumed_at = ? WHERE verification_id = ?",
                    (current.isoformat(), row["verification_id"]),
                )
                connection.commit()
                return "expired"
            if row["attempts"] >= row["max_attempts"]:
                connection.commit()
                return "attempts_exceeded"

            attempts = int(row["attempts"]) + 1
            if not hmac.compare_digest(row["code_digest"], code_digest):
                consumed = current.isoformat() if attempts >= row["max_attempts"] else None
                connection.execute(
                    """
                    UPDATE email_verification_codes
                    SET attempts = ?, consumed_at = COALESCE(?, consumed_at)
                    WHERE verification_id = ?
                    """,
                    (attempts, consumed, row["verification_id"]),
                )
                connection.commit()
                return "attempts_exceeded" if consumed else "invalid"

            connection.execute(
                """
                UPDATE email_verification_codes
                SET attempts = ?, consumed_at = ? WHERE verification_id = ?
                """,
                (attempts, current.isoformat(), row["verification_id"]),
            )
            connection.commit()
            return "ok"
        except sqlite3.Error:
            connection.rollback()
            raise
        finally:
            connection.close()

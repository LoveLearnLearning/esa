"""Persistence for the classroom and homework demo workflow."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4

from backend.core.stores.base_sqlite_store import BaseSQLiteStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


class TeachingStore(BaseSQLiteStore):
    """Single-database aggregate for the first teaching vertical slice."""

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS teaching_classes (
                    class_id TEXT PRIMARY KEY,
                    owner_teacher_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    canonical_course TEXT NOT NULL,
                    term TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(owner_teacher_id) REFERENCES users(id) ON DELETE CASCADE,
                    CHECK(status IN ('active', 'archived'))
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_teaching_classes_owner_name
                ON teaching_classes(owner_teacher_id, name) WHERE status = 'active';

                CREATE TABLE IF NOT EXISTS teaching_memberships (
                    membership_id TEXT PRIMARY KEY,
                    class_id TEXT NOT NULL,
                    student_id TEXT NOT NULL,
                    invited_by TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    responded_at TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(class_id, student_id),
                    FOREIGN KEY(class_id) REFERENCES teaching_classes(class_id) ON DELETE CASCADE,
                    FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY(invited_by) REFERENCES users(id) ON DELETE CASCADE,
                    CHECK(status IN ('pending', 'active', 'declined', 'removed', 'left'))
                );
                CREATE INDEX IF NOT EXISTS idx_teaching_memberships_student
                ON teaching_memberships(student_id, status);

                CREATE TABLE IF NOT EXISTS teaching_assignments (
                    assignment_id TEXT PRIMARY KEY,
                    class_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    instructions TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    due_at TEXT,
                    total_points REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    published_at TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(class_id) REFERENCES teaching_classes(class_id) ON DELETE CASCADE,
                    CHECK(status IN ('draft', 'published', 'closed', 'archived'))
                );
                CREATE INDEX IF NOT EXISTS idx_teaching_assignments_class
                ON teaching_assignments(class_id, status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS teaching_questions (
                    question_id TEXT PRIMARY KEY,
                    assignment_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    question_type TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    max_points REAL NOT NULL,
                    rubric TEXT NOT NULL DEFAULT '',
                    reference_answer TEXT NOT NULL DEFAULT '',
                    kp_id TEXT,
                    FOREIGN KEY(assignment_id) REFERENCES teaching_assignments(assignment_id) ON DELETE CASCADE,
                    UNIQUE(assignment_id, position),
                    CHECK(question_type IN ('short_answer', 'code'))
                );

                CREATE TABLE IF NOT EXISTS teaching_submissions (
                    submission_id TEXT PRIMARY KEY,
                    assignment_id TEXT NOT NULL,
                    student_id TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'submitted',
                    submitted_at TEXT NOT NULL,
                    is_late INTEGER NOT NULL DEFAULT 0,
                    analysis_status TEXT NOT NULL DEFAULT 'pending',
                    feedback_status TEXT NOT NULL DEFAULT 'unpublished',
                    total_score REAL,
                    published_at TEXT,
                    UNIQUE(assignment_id, student_id, version),
                    FOREIGN KEY(assignment_id) REFERENCES teaching_assignments(assignment_id) ON DELETE CASCADE,
                    FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE,
                    CHECK(status IN ('submitted', 'withdrawn')),
                    CHECK(analysis_status IN ('pending', 'running', 'completed', 'failed')),
                    CHECK(feedback_status IN ('unpublished', 'ready', 'published'))
                );
                CREATE INDEX IF NOT EXISTS idx_teaching_submissions_assignment
                ON teaching_submissions(assignment_id, student_id, version DESC);

                CREATE TABLE IF NOT EXISTS teaching_answers (
                    answer_id TEXT PRIMARY KEY,
                    submission_id TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    answer_text TEXT NOT NULL DEFAULT '',
                    ai_score REAL,
                    ai_error_type TEXT,
                    ai_feedback TEXT,
                    ai_confidence REAL,
                    ai_kp_id TEXT,
                    final_score REAL,
                    final_error_type TEXT,
                    final_feedback TEXT,
                    final_kp_id TEXT,
                    reviewed_at TEXT,
                    FOREIGN KEY(submission_id) REFERENCES teaching_submissions(submission_id) ON DELETE CASCADE,
                    FOREIGN KEY(question_id) REFERENCES teaching_questions(question_id) ON DELETE CASCADE,
                    UNIQUE(submission_id, question_id)
                );

                CREATE TABLE IF NOT EXISTS teaching_evidence_publications (
                    answer_id TEXT PRIMARY KEY,
                    evidence_id TEXT,
                    published_at TEXT NOT NULL,
                    FOREIGN KEY(answer_id) REFERENCES teaching_answers(answer_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS teaching_audit_log (
                    audit_id TEXT PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(actor_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_teaching_audit_resource
                ON teaching_audit_log(resource_type, resource_id, created_at DESC);
                """
            )

    def audit(
        self,
        *,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        summary: dict | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        target = connection or self._connect()
        should_close = connection is None
        try:
            target.execute(
                """INSERT INTO teaching_audit_log
                   (audit_id, actor_id, action, resource_type, resource_id,
                    summary_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    uuid4().hex,
                    actor_id,
                    action,
                    resource_type,
                    resource_id,
                    json.dumps(summary or {}, ensure_ascii=False),
                    _now(),
                ),
            )
            if should_close:
                target.commit()
        finally:
            if should_close:
                target.close()

    # Classes and membership
    def create_class(
        self, *, owner_id: str, name: str, course: str, term: str, description: str
    ) -> dict:
        class_id = uuid4().hex
        now = _now()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """INSERT INTO teaching_classes
                   (class_id, owner_teacher_id, name, canonical_course, term,
                    description, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (class_id, owner_id, name, course, term, description, now, now),
            )
            self.audit(
                actor_id=owner_id,
                action="class.created",
                resource_type="class",
                resource_id=class_id,
                connection=connection,
            )
        return self.get_class(class_id) or {}

    def get_class(self, class_id: str) -> dict | None:
        return _row(
            self.query_one(
                """SELECT c.*,
                          (SELECT COUNT(*) FROM teaching_memberships m
                           WHERE m.class_id=c.class_id AND m.status='active') AS student_count,
                          (SELECT COUNT(*) FROM teaching_assignments a
                           WHERE a.class_id=c.class_id AND a.status='published') AS open_assignment_count
                   FROM teaching_classes c WHERE c.class_id=?""",
                (class_id,),
            )
        )

    def list_teacher_classes(self, teacher_id: str) -> list[dict]:
        return [
            dict(item)
            for item in self.query_all(
                """SELECT c.*,
                          (SELECT COUNT(*) FROM teaching_memberships m
                           WHERE m.class_id=c.class_id AND m.status='active') AS student_count,
                          (SELECT COUNT(*) FROM teaching_assignments a
                           WHERE a.class_id=c.class_id AND a.status='published') AS open_assignment_count
                   FROM teaching_classes c WHERE c.owner_teacher_id=?
                   ORDER BY c.status ASC, c.updated_at DESC""",
                (teacher_id,),
            )
        ]

    def list_student_classes(self, student_id: str) -> list[dict]:
        return [
            dict(item)
            for item in self.query_all(
                """SELECT c.*, m.membership_id,
                          m.status AS membership_status, m.created_at AS invited_at,
                          m.responded_at, u.username AS teacher_username
                   FROM teaching_memberships m
                   JOIN teaching_classes c ON c.class_id=m.class_id
                   JOIN users u ON u.id=c.owner_teacher_id
                   WHERE m.student_id=?
                   ORDER BY CASE m.status WHEN 'pending' THEN 0 WHEN 'active' THEN 1 ELSE 2 END,
                            m.updated_at DESC""",
                (student_id,),
            )
        ]

    def invite_student(
        self, *, class_id: str, teacher_id: str, student_id: str
    ) -> dict:
        now = _now()
        membership_id = uuid4().hex
        with closing(self._connect()) as connection, connection:
            existing = connection.execute(
                "SELECT membership_id FROM teaching_memberships WHERE class_id=? AND student_id=?",
                (class_id, student_id),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """INSERT INTO teaching_memberships
                       (membership_id, class_id, student_id, invited_by, status,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
                    (membership_id, class_id, student_id, teacher_id, now, now),
                )
            else:
                membership_id = str(existing["membership_id"])
                connection.execute(
                    """UPDATE teaching_memberships SET status='pending', invited_by=?,
                       responded_at=NULL, updated_at=? WHERE membership_id=?""",
                    (teacher_id, now, membership_id),
                )
            self.audit(
                actor_id=teacher_id,
                action="membership.invited",
                resource_type="membership",
                resource_id=membership_id,
                summary={"class_id": class_id, "student_id": student_id},
                connection=connection,
            )
        return self.get_membership(membership_id) or {}

    def get_membership(self, membership_id: str) -> dict | None:
        return _row(
            self.query_one(
                """SELECT m.*, u.username AS student_username
                   FROM teaching_memberships m JOIN users u ON u.id=m.student_id
                   WHERE m.membership_id=?""",
                (membership_id,),
            )
        )

    def get_membership_for_student(
        self, *, class_id: str, student_id: str
    ) -> dict | None:
        return _row(
            self.query_one(
                "SELECT * FROM teaching_memberships WHERE class_id=? AND student_id=?",
                (class_id, student_id),
            )
        )

    def list_members(self, class_id: str) -> list[dict]:
        return [
            dict(item)
            for item in self.query_all(
                """SELECT m.*, u.username AS student_username,
                          (SELECT COUNT(*) FROM teaching_submissions s
                           JOIN teaching_assignments a ON a.assignment_id=s.assignment_id
                           WHERE a.class_id=m.class_id AND s.student_id=m.student_id
                             AND s.status='submitted') AS submission_count
                   FROM teaching_memberships m JOIN users u ON u.id=m.student_id
                   WHERE m.class_id=? ORDER BY m.status ASC, u.username ASC""",
                (class_id,),
            )
        ]

    def respond_membership(
        self, *, membership_id: str, student_id: str, accept: bool
    ) -> dict | None:
        status = "active" if accept else "declined"
        now = _now()
        with closing(self._connect()) as connection, connection:
            changed = connection.execute(
                """UPDATE teaching_memberships SET status=?, responded_at=?, updated_at=?
                   WHERE membership_id=? AND student_id=? AND status='pending'""",
                (status, now, now, membership_id, student_id),
            ).rowcount
            if not changed:
                return None
            self.audit(
                actor_id=student_id,
                action=f"membership.{status}",
                resource_type="membership",
                resource_id=membership_id,
                connection=connection,
            )
        return self.get_membership(membership_id)

    def remove_member(self, *, class_id: str, student_id: str, teacher_id: str) -> bool:
        now = _now()
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT membership_id FROM teaching_memberships WHERE class_id=? AND student_id=?",
                (class_id, student_id),
            ).fetchone()
            if row is None:
                return False
            connection.execute(
                "UPDATE teaching_memberships SET status='removed', updated_at=? WHERE membership_id=?",
                (now, row["membership_id"]),
            )
            self.audit(
                actor_id=teacher_id,
                action="membership.removed",
                resource_type="membership",
                resource_id=str(row["membership_id"]),
                connection=connection,
            )
        return True

    # Assignments and submissions
    def create_assignment(
        self,
        *,
        class_id: str,
        title: str,
        instructions: str,
        due_at: str | None,
        questions: list[dict],
        teacher_id: str,
    ) -> dict:
        assignment_id = uuid4().hex
        now = _now()
        total = sum(float(item["max_points"]) for item in questions)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """INSERT INTO teaching_assignments
                   (assignment_id, class_id, title, instructions, due_at,
                    total_points, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (assignment_id, class_id, title, instructions, due_at, total, now, now),
            )
            for position, question in enumerate(questions, start=1):
                connection.execute(
                    """INSERT INTO teaching_questions
                       (question_id, assignment_id, position, question_type, prompt,
                        max_points, rubric, reference_answer, kp_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        uuid4().hex,
                        assignment_id,
                        position,
                        question["question_type"],
                        question["prompt"],
                        float(question["max_points"]),
                        question.get("rubric", ""),
                        question.get("reference_answer", ""),
                        question.get("kp_id"),
                    ),
                )
            self.audit(
                actor_id=teacher_id,
                action="assignment.created",
                resource_type="assignment",
                resource_id=assignment_id,
                connection=connection,
            )
        return self.get_assignment(assignment_id) or {}

    def get_assignment(self, assignment_id: str) -> dict | None:
        item = _row(
            self.query_one(
                """SELECT a.*, c.name AS class_name, c.canonical_course,
                          c.owner_teacher_id,
                          (SELECT COUNT(DISTINCT s.student_id) FROM teaching_submissions s
                           WHERE s.assignment_id=a.assignment_id AND s.status='submitted') AS submitted_count,
                          (SELECT COUNT(*) FROM teaching_memberships m
                           WHERE m.class_id=a.class_id AND m.status='active') AS student_count
                   FROM teaching_assignments a
                   JOIN teaching_classes c ON c.class_id=a.class_id
                   WHERE a.assignment_id=?""",
                (assignment_id,),
            )
        )
        if item is None:
            return None
        item["questions"] = [
            dict(row)
            for row in self.query_all(
                "SELECT * FROM teaching_questions WHERE assignment_id=? ORDER BY position",
                (assignment_id,),
            )
        ]
        return item

    def list_class_assignments(self, class_id: str) -> list[dict]:
        return [
            dict(item)
            for item in self.query_all(
                """SELECT a.*,
                          (SELECT COUNT(DISTINCT s.student_id) FROM teaching_submissions s
                           WHERE s.assignment_id=a.assignment_id AND s.status='submitted') AS submitted_count,
                          (SELECT COUNT(*) FROM teaching_submissions s
                           WHERE s.assignment_id=a.assignment_id AND s.feedback_status='ready') AS ready_count,
                          (SELECT COUNT(*) FROM teaching_memberships m
                           WHERE m.class_id=a.class_id AND m.status='active') AS student_count
                   FROM teaching_assignments a WHERE a.class_id=?
                   ORDER BY a.updated_at DESC""",
                (class_id,),
            )
        ]

    def list_student_assignments(self, student_id: str) -> list[dict]:
        return [
            dict(item)
            for item in self.query_all(
                """SELECT a.*, c.name AS class_name, c.canonical_course,
                          s.submission_id, s.status AS submission_status,
                          s.analysis_status, s.feedback_status, s.total_score,
                          s.submitted_at
                   FROM teaching_assignments a
                   JOIN teaching_classes c ON c.class_id=a.class_id
                   JOIN teaching_memberships m ON m.class_id=a.class_id
                   LEFT JOIN teaching_submissions s ON s.submission_id=(
                       SELECT s2.submission_id FROM teaching_submissions s2
                       WHERE s2.assignment_id=a.assignment_id AND s2.student_id=?
                       ORDER BY s2.version DESC LIMIT 1)
                   WHERE m.student_id=?
                     AND (m.status='active' OR (
                         m.status IN ('left','removed')
                         AND s.feedback_status='published'
                     ))
                     AND a.status IN ('published','closed','archived')
                   ORDER BY CASE WHEN s.submission_id IS NULL THEN 0 ELSE 1 END,
                            a.due_at ASC, a.updated_at DESC""",
                (student_id, student_id),
            )
        ]

    def get_latest_submission_for_student(
        self, *, assignment_id: str, student_id: str
    ) -> dict | None:
        row = self.query_one(
            """SELECT submission_id FROM teaching_submissions
               WHERE assignment_id=? AND student_id=?
               ORDER BY version DESC LIMIT 1""",
            (assignment_id, student_id),
        )
        if row is None:
            return None
        return self.get_submission(str(row["submission_id"]))

    def publish_assignment(self, *, assignment_id: str, teacher_id: str) -> bool:
        now = _now()
        with closing(self._connect()) as connection, connection:
            changed = connection.execute(
                """UPDATE teaching_assignments SET status='published', published_at=?, updated_at=?
                   WHERE assignment_id=? AND status='draft'""",
                (now, now, assignment_id),
            ).rowcount
            if changed:
                self.audit(
                    actor_id=teacher_id,
                    action="assignment.published",
                    resource_type="assignment",
                    resource_id=assignment_id,
                    connection=connection,
                )
        return bool(changed)

    def submit(
        self, *, assignment_id: str, student_id: str, answers: list[dict]
    ) -> dict:
        assignment = self.get_assignment(assignment_id)
        if assignment is None:
            raise ValueError("assignment_not_found")
        now = _now()
        due = datetime.fromisoformat(assignment["due_at"]) if assignment.get("due_at") else None
        late = bool(due and datetime.now(timezone.utc) > due.astimezone(timezone.utc))
        with closing(self._connect()) as connection, connection:
            version = int(
                connection.execute(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM teaching_submissions WHERE assignment_id=? AND student_id=?",
                    (assignment_id, student_id),
                ).fetchone()[0]
            )
            submission_id = uuid4().hex
            connection.execute(
                """INSERT INTO teaching_submissions
                   (submission_id, assignment_id, student_id, version, submitted_at, is_late)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (submission_id, assignment_id, student_id, version, now, int(late)),
            )
            valid_question_ids = {item["question_id"] for item in assignment["questions"]}
            for answer in answers:
                if answer["question_id"] not in valid_question_ids:
                    raise ValueError("invalid_question")
                connection.execute(
                    """INSERT INTO teaching_answers
                       (answer_id, submission_id, question_id, answer_text)
                       VALUES (?, ?, ?, ?)""",
                    (uuid4().hex, submission_id, answer["question_id"], answer["answer_text"]),
                )
            self.audit(
                actor_id=student_id,
                action="submission.created",
                resource_type="submission",
                resource_id=submission_id,
                summary={"assignment_id": assignment_id, "version": version},
                connection=connection,
            )
        return self.get_submission(submission_id) or {}

    def get_submission(self, submission_id: str) -> dict | None:
        item = _row(
            self.query_one(
                """SELECT s.*, a.title AS assignment_title, a.total_points,
                          a.class_id, c.name AS class_name, c.canonical_course,
                          c.owner_teacher_id, u.username AS student_username
                   FROM teaching_submissions s
                   JOIN teaching_assignments a ON a.assignment_id=s.assignment_id
                   JOIN teaching_classes c ON c.class_id=a.class_id
                   JOIN users u ON u.id=s.student_id
                   WHERE s.submission_id=?""",
                (submission_id,),
            )
        )
        if item is None:
            return None
        item["answers"] = [
            dict(row)
            for row in self.query_all(
                """SELECT ans.*, q.position, q.question_type, q.prompt,
                          q.max_points, q.rubric, q.reference_answer, q.kp_id
                   FROM teaching_answers ans JOIN teaching_questions q
                     ON q.question_id=ans.question_id
                   WHERE ans.submission_id=? ORDER BY q.position""",
                (submission_id,),
            )
        ]
        return item

    def list_submissions(self, assignment_id: str) -> list[dict]:
        return [
            dict(item)
            for item in self.query_all(
                """SELECT s.*, u.username AS student_username
                   FROM teaching_submissions s JOIN users u ON u.id=s.student_id
                   WHERE s.assignment_id=? AND s.version=(
                       SELECT MAX(s2.version) FROM teaching_submissions s2
                       WHERE s2.assignment_id=s.assignment_id AND s2.student_id=s.student_id)
                   ORDER BY s.submitted_at ASC""",
                (assignment_id,),
            )
        ]

    def save_analysis(self, *, submission_id: str, results: list[dict], actor_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE teaching_submissions SET analysis_status='running' WHERE submission_id=?",
                (submission_id,),
            )
            for result in results:
                connection.execute(
                    """UPDATE teaching_answers SET ai_score=?, ai_error_type=?, ai_feedback=?,
                       ai_confidence=?, ai_kp_id=? WHERE answer_id=? AND submission_id=?""",
                    (
                        result["score"], result.get("error_type"), result.get("feedback", ""),
                        result.get("confidence", 0.5), result.get("kp_id"),
                        result["answer_id"], submission_id,
                    ),
                )
            connection.execute(
                "UPDATE teaching_submissions SET analysis_status='completed' WHERE submission_id=?",
                (submission_id,),
            )
            self.audit(
                actor_id=actor_id,
                action="submission.analyzed",
                resource_type="submission",
                resource_id=submission_id,
                connection=connection,
            )

    def mark_analysis_failed(self, submission_id: str) -> None:
        self.execute(
            "UPDATE teaching_submissions SET analysis_status='failed' WHERE submission_id=?",
            (submission_id,),
        )

    def review_submission(
        self, *, submission_id: str, reviews: list[dict], teacher_id: str
    ) -> dict:
        now = _now()
        with closing(self._connect()) as connection, connection:
            for review in reviews:
                connection.execute(
                    """UPDATE teaching_answers SET final_score=?, final_error_type=?,
                       final_feedback=?, final_kp_id=?, reviewed_at=?
                       WHERE answer_id=? AND submission_id=?""",
                    (
                        review["score"], review.get("error_type"), review.get("feedback", ""),
                        review.get("kp_id"), now, review["answer_id"], submission_id,
                    ),
                )
            total = float(
                connection.execute(
                    "SELECT COALESCE(SUM(final_score), 0) FROM teaching_answers WHERE submission_id=?",
                    (submission_id,),
                ).fetchone()[0]
            )
            connection.execute(
                """UPDATE teaching_submissions SET total_score=?, feedback_status='ready'
                   WHERE submission_id=?""",
                (total, submission_id),
            )
            self.audit(
                actor_id=teacher_id,
                action="submission.reviewed",
                resource_type="submission",
                resource_id=submission_id,
                summary={"total_score": total},
                connection=connection,
            )
        return self.get_submission(submission_id) or {}

    def mark_feedback_published(self, *, submission_id: str, teacher_id: str) -> dict:
        now = _now()
        with closing(self._connect()) as connection, connection:
            existing = connection.execute(
                "SELECT feedback_status FROM teaching_submissions WHERE submission_id=?",
                (submission_id,),
            ).fetchone()
            if existing is not None and existing["feedback_status"] == "published":
                return self.get_submission(submission_id) or {}
            changed = connection.execute(
                """UPDATE teaching_submissions SET feedback_status='published', published_at=?
                   WHERE submission_id=? AND feedback_status='ready'""",
                (now, submission_id),
            ).rowcount
            if not changed:
                raise ValueError("not_ready")
            self.audit(
                actor_id=teacher_id,
                action="feedback.published",
                resource_type="submission",
                resource_id=submission_id,
                connection=connection,
            )
        return self.get_submission(submission_id) or {}

    def mark_evidence_written(self, answer_id: str, evidence_id: str) -> bool:
        with closing(self._connect()) as connection, connection:
            return bool(
                connection.execute(
                    """INSERT OR IGNORE INTO teaching_evidence_publications
                       (answer_id, evidence_id, published_at) VALUES (?, ?, ?)""",
                    (answer_id, evidence_id, _now()),
                ).rowcount
            )

    def has_evidence(self, answer_id: str) -> bool:
        return self.query_one(
            "SELECT 1 FROM teaching_evidence_publications WHERE answer_id=?",
            (answer_id,),
        ) is not None

    def dashboard(self, teacher_id: str) -> dict:
        row = self.query_one(
            """SELECT
                 (SELECT COUNT(*) FROM teaching_classes c WHERE c.owner_teacher_id=? AND c.status='active') AS class_count,
                 (SELECT COUNT(*) FROM teaching_submissions s
                  JOIN teaching_assignments a ON a.assignment_id=s.assignment_id
                  JOIN teaching_classes c ON c.class_id=a.class_id
                  WHERE c.owner_teacher_id=? AND s.analysis_status='completed'
                    AND s.feedback_status='unpublished') AS pending_review_count,
                 (SELECT COUNT(*) FROM teaching_submissions s
                  JOIN teaching_assignments a ON a.assignment_id=s.assignment_id
                  JOIN teaching_classes c ON c.class_id=a.class_id
                  WHERE c.owner_teacher_id=? AND s.feedback_status='ready') AS ready_feedback_count""",
            (teacher_id, teacher_id, teacher_id),
        )
        return dict(row) if row else {}

    def class_learning_rows(self, class_id: str) -> list[dict]:
        """Published, teacher-reviewed evidence used by the class dashboard."""
        return [
            dict(item)
            for item in self.query_all(
                """SELECT s.student_id, u.username AS student_username,
                          s.submission_id, s.assignment_id, a.title AS assignment_title,
                          ans.answer_id, ans.final_score, q.max_points,
                          COALESCE(ans.final_kp_id, q.kp_id) AS kp_id,
                          ans.final_error_type, ans.final_feedback, s.published_at
                   FROM teaching_submissions s
                   JOIN teaching_assignments a ON a.assignment_id=s.assignment_id
                   JOIN teaching_answers ans ON ans.submission_id=s.submission_id
                   JOIN teaching_questions q ON q.question_id=ans.question_id
                   JOIN users u ON u.id=s.student_id
                   WHERE a.class_id=? AND s.feedback_status='published'
                     AND ans.final_score IS NOT NULL
                   ORDER BY s.published_at DESC""",
                (class_id,),
            )
        ]

    def student_class_summary(self, *, class_id: str, student_id: str) -> dict:
        membership = self.get_membership_for_student(
            class_id=class_id, student_id=student_id
        )
        rows = [
            item
            for item in self.class_learning_rows(class_id)
            if item["student_id"] == student_id
        ]
        submissions = [
            dict(item)
            for item in self.query_all(
                """SELECT s.submission_id, s.assignment_id, a.title,
                          s.total_score, a.total_points, s.feedback_status,
                          s.submitted_at, s.published_at
                   FROM teaching_submissions s
                   JOIN teaching_assignments a ON a.assignment_id=s.assignment_id
                   WHERE a.class_id=? AND s.student_id=?
                   ORDER BY s.submitted_at DESC""",
                (class_id, student_id),
            )
        ]
        return {"membership": membership, "evidence": rows, "submissions": submissions}

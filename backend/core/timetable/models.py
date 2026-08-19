from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class TimetableEntryDraft:
    """尚未写入数据库的具体上课事件。

    教务接口返回的是指定日期范围内的具体日历事件，因此这里有明确日期，
    而不是把单双周等规则继续留给客户端展开。
    """

    course_name: str
    course_code: str
    teacher: str
    location: str
    date: str
    start_time: str
    end_time: str
    week_number: int
    weekday: int
    campus: str = ""
    source_event_id: str = ""

    def canonical_key(self) -> str:
        if self.source_event_id.strip():
            return self.source_event_id.strip()
        payload = asdict(self)
        payload.pop("source_event_id", None)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class TimetableSemester:
    id: str
    source: str
    external_id: str
    name: str
    start_date: str
    end_date: str
    total_weeks: int
    entry_count: int
    imported_at: str

    def contains(self, value: date) -> bool:
        return date.fromisoformat(self.start_date) <= value <= date.fromisoformat(
            self.end_date
        )


@dataclass(frozen=True, slots=True)
class TimetableEntry:
    id: str
    course_name: str
    course_code: str
    teacher: str
    location: str
    date: str
    start_time: str
    end_time: str
    week_number: int
    weekday: int
    campus: str


@dataclass(frozen=True, slots=True)
class TimetableImportWrite:
    semester: TimetableSemester
    imported_entries: int

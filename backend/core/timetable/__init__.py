"""课表领域模型、解析器与学校导入适配器。"""

from backend.core.timetable.models import (
    TimetableEntry,
    TimetableEntryDraft,
    TimetableSemester,
)

__all__ = ["TimetableEntry", "TimetableEntryDraft", "TimetableSemester"]

from __future__ import annotations

import ast
import html
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from backend.core.timetable.models import TimetableEntryDraft

SHANGHAI_TZ = timezone(timedelta(hours=8))


class TimetableParseError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedTimetable:
    entries: list[TimetableEntryDraft]
    skipped_entries: int
    warnings: list[str]


_EVENT_LIST_KEYS = ("events", "rows", "list", "data", "result", "items")
_COURSE_NAME_KEYS = (
    "course_name",
    "KCMC",
    "KTMC",
    "KCZWMC",
    "kcName",
    "courseName",
    "name",
)
_COURSE_CODE_KEYS = ("course_code", "KCH", "KCDM", "courseCode", "code")
_TEACHER_KEYS = ("teacher", "JGXM", "JSXM", "SKJS", "RKJS", "teacherName")
_LOCATION_KEYS = ("location", "JSMC", "SKDD", "CDMC", "room", "classroom")
_CAMPUS_KEYS = ("campus", "XQMC", "campusName", "campus_name")
_SOURCE_ID_KEYS = ("id", "eventId", "event_id", "ID")


def _first(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    lowered = {str(key).lower(): value for key, value in mapping.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_txt(value: Any, event_number: int) -> tuple[dict[str, Any], str | None]:
    if value in (None, ""):
        return {}, None
    if isinstance(value, Mapping):
        return dict(value), None
    if not isinstance(value, str):
        return {}, f"第 {event_number} 条事件的 txt 不是对象或字符串，已忽略"

    raw = html.unescape(value).strip()
    if not raw:
        return {}, None
    for loader in (json.loads, ast.literal_eval):
        try:
            parsed = loader(raw)
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, Mapping):
            return dict(parsed), None
    return {}, f"第 {event_number} 条事件的 txt 无法解析，已仅使用顶层字段"


def _parse_datetime(value: Any, field: str, event_number: int) -> datetime:
    if value is None:
        raise TimetableParseError(f"第 {event_number} 条事件缺少 {field}")
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if abs(timestamp) > 10_000_000_000:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp, timezone.utc).astimezone(SHANGHAI_TZ)

    raw = str(value).strip()
    if not raw:
        raise TimetableParseError(f"第 {event_number} 条事件的 {field} 为空")
    if re.fullmatch(r"\d{10,13}", raw):
        return _parse_datetime(int(raw), field, event_number)

    normalized = raw.replace("/", "-")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None
        for pattern in (
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                parsed = datetime.strptime(normalized, pattern)
                break
            except ValueError:
                continue
        if parsed is None:
            raise TimetableParseError(
                f"第 {event_number} 条事件的 {field} 时间格式无法识别: {raw!r}"
            )
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(SHANGHAI_TZ).replace(tzinfo=None)
    return parsed


def _extract_events(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload.lstrip("\ufeff"))
        except json.JSONDecodeError as error:
            raise TimetableParseError(f"课表响应不是合法 JSON: {error.msg}") from error
    if isinstance(payload, list):
        if not all(isinstance(item, Mapping) for item in payload):
            raise TimetableParseError("课表事件数组中包含非对象元素")
        return list(payload)
    if isinstance(payload, Mapping):
        for key in _EVENT_LIST_KEYS:
            value = _first(payload, (key,))
            if isinstance(value, list):
                if not all(isinstance(item, Mapping) for item in value):
                    raise TimetableParseError(f"课表响应字段 {key} 不是对象数组")
                return list(value)
            if isinstance(value, Mapping):
                try:
                    return _extract_events(value)
                except TimetableParseError:
                    pass
    raise TimetableParseError("课表响应中未找到事件数组（支持 events/rows/list/data/result）")


def total_weeks_between(start_date: date, end_date: date) -> int:
    if end_date < start_date:
        raise ValueError("结束日期不能早于开始日期")
    return max(1, math.ceil(((end_date - start_date).days + 1) / 7))


def parse_hust_schedule(
    payload: Any,
    *,
    semester_start: date,
    semester_end: date,
) -> ParsedTimetable:
    """解析华科旧课表接口的具体日历事件。

    兼容顶层数组及常见包装字段。`txt` 先按 JSON，再按
    `ast.literal_eval` 解析，绝不执行源字符串。
    """

    if semester_end < semester_start:
        raise TimetableParseError("学期结束日期不能早于开始日期")
    source_events = _extract_events(payload)
    entries: list[TimetableEntryDraft] = []
    warnings: list[str] = []
    skipped = 0
    seen: set[str] = set()

    for index, event in enumerate(source_events, 1):
        metadata, txt_warning = _parse_txt(_first(event, ("txt", "detail")), index)
        if txt_warning:
            warnings.append(txt_warning)
        combined = {**event, **metadata}
        try:
            start = _parse_datetime(
                _first(event, ("start", "startTime", "begin", "KSSJ")),
                "start",
                index,
            )
            end = _parse_datetime(
                _first(event, ("end", "endTime", "finish", "JSSJ")),
                "end",
                index,
            )
            if end <= start:
                raise TimetableParseError(f"第 {index} 条事件的结束时间不晚于开始时间")
            event_date = start.date()
            if not semester_start <= event_date <= semester_end:
                skipped += 1
                warnings.append(f"第 {index} 条事件不在所选学期日期范围内，已跳过")
                continue

            course_name = _clean_text(_first(combined, _COURSE_NAME_KEYS))
            if not course_name:
                course_name = _clean_text(_first(event, ("title", "TITLE")))
            if not course_name:
                raise TimetableParseError(f"第 {index} 条事件缺少课程名称/title")

            entry = TimetableEntryDraft(
                course_name=course_name,
                course_code=_clean_text(_first(combined, _COURSE_CODE_KEYS)),
                teacher=_clean_text(_first(combined, _TEACHER_KEYS)),
                location=_clean_text(_first(combined, _LOCATION_KEYS)),
                date=event_date.isoformat(),
                start_time=start.strftime("%H:%M"),
                end_time=end.strftime("%H:%M"),
                week_number=((event_date - semester_start).days // 7) + 1,
                weekday=event_date.isoweekday(),
                campus=_clean_text(_first(combined, _CAMPUS_KEYS)),
                source_event_id=_clean_text(_first(event, _SOURCE_ID_KEYS)),
            )
            key = entry.canonical_key()
            if key in seen:
                skipped += 1
                warnings.append(f"第 {index} 条事件与前一事件重复，已跳过")
                continue
            seen.add(key)
            entries.append(entry)
        except TimetableParseError as error:
            skipped += 1
            warnings.append(str(error))

    if source_events and not entries:
        detail = "；".join(warnings[:3])
        raise TimetableParseError(
            f"课表响应包含 {len(source_events)} 条事件，但没有可导入事件"
            + (f"：{detail}" if detail else "")
        )
    return ParsedTimetable(entries, skipped, warnings)

import unittest
from datetime import date

from backend.core.timetable.parser import TimetableParseError, parse_hust_schedule


class HustTimetableParserTests(unittest.TestCase):
    def test_parses_json_and_safe_python_literal_metadata(self):
        payload = {
        "data": {
            "rows": [
                {
                    "id": "event-1",
                    "title": "编译原理",
                    "start": "2026-09-07 08:00",
                    "end": "2026-09-07 09:35",
                    "txt": '{"KCMC":"编译原理","JGXM":"张老师","JSMC":"东九楼 A101","KCH":"CS301"}',
                },
                {
                    "title": "数据库系统",
                    "start": "2026-09-15T10:10:00",
                    "end": "2026-09-15T11:45:00",
                    "txt": "{'teacherName': '李老师', 'room': '南一楼 201'}",
                },
            ]
        }
    }
        result = parse_hust_schedule(
            payload,
            semester_start=date(2026, 9, 7),
            semester_end=date(2027, 1, 24),
        )
        self.assertEqual(len(result.entries), 2)
        self.assertEqual(result.entries[0].teacher, "张老师")
        self.assertEqual(result.entries[0].course_code, "CS301")
        self.assertEqual(result.entries[1].week_number, 2)


    def test_rejects_payload_without_usable_events(self):
        with self.assertRaisesRegex(TimetableParseError, "没有可导入事件"):
            parse_hust_schedule(
                [{"title": "缺少时间"}],
                semester_start=date(2026, 9, 7),
                semester_end=date(2027, 1, 24),
            )


if __name__ == "__main__":
    unittest.main()

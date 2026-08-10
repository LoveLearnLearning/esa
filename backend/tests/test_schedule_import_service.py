import asyncio

from backend.core.services import schedule_import_service


def test_document_extraction_supports_html_pdf_and_images(monkeypatch):
    html = asyncio.run(
        schedule_import_service.extract_document_text(
            filename="schedule.html",
            content_type="text/html",
            data=b"<style>hidden</style><p>Data Structure</p>",
        )
    )
    monkeypatch.setattr(schedule_import_service, "_pdf_text", lambda _data: "PDF课程")
    monkeypatch.setattr(
        schedule_import_service,
        "_image_text",
        lambda _data: "图片课程",
    )
    pdf = asyncio.run(
        schedule_import_service.extract_document_text(
            filename="schedule.pdf",
            content_type="application/pdf",
            data=b"pdf",
        )
    )
    image = asyncio.run(
        schedule_import_service.extract_document_text(
            filename="schedule.png",
            content_type="image/png",
            data=b"png",
        )
    )

    assert html == "Data Structure"
    assert pdf == "PDF课程"
    assert image == "图片课程"


def test_schedule_structure_is_extracted_by_auxiliary_client():
    class _Client:
        async def chat(self, messages, *, max_tokens, temperature):
            assert "课表结构化提取器" in messages[0]["content"]
            assert "数据结构" in messages[1]["content"]
            assert max_tokens == 512
            assert temperature == 0.0
            return """```json
            [{
              "name": "数据结构",
              "teacher": "张老师",
              "location": "A101",
              "weekday": 1,
              "start_period": 1,
              "end_period": 2
            }]
            ```"""

    courses = asyncio.run(
        schedule_import_service.extract_schedule_courses(
            llm_client=_Client(),
            document_text="周一第1-2节 数据结构 张老师 A101",
            total_weeks=18,
            settings={},
            max_output_tokens=512,
        )
    )

    assert courses == [
        {
            "name": "数据结构",
            "teacher": "张老师",
            "location": "A101",
            "weekday": 1,
            "start_period": 1,
            "end_period": 2,
            "start_week": 1,
            "end_week": 18,
        }
    ]

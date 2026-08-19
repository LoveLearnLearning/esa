# backend/tests/test_schedule_import_service.py

"""验证 `schedule_import_service` 相关行为与回归场景。"""

import asyncio
import io
from types import SimpleNamespace

import pytest
from PIL import Image

from backend.core.services import schedule_import_service


def _png_bytes() -> bytes:
    """处理 `_png_bytes` 相关逻辑。"""
    output = io.BytesIO()
    Image.new("RGB", (32, 24), "white").save(output, format="PNG")
    return output.getvalue()


def test_document_extraction_supports_html_pdf_and_images(monkeypatch):
    """验证 `document_extraction_supports_html_pdf_and_images` 场景。"""
    html = asyncio.run(
        schedule_import_service.extract_schedule_document(
            filename="schedule.html",
            content_type="text/html",
            data=b"<style>hidden</style><p>Data Structure</p>",
        )
    )
    monkeypatch.setattr(
        schedule_import_service,
        "_pdf_image_data_urls",
        lambda _data: ("data:image/jpeg;base64,cGRm",),
    )
    pdf = asyncio.run(
        schedule_import_service.extract_schedule_document(
            filename="schedule.pdf",
            content_type="application/pdf",
            data=b"pdf",
        )
    )
    image = asyncio.run(
        schedule_import_service.extract_schedule_document(
            filename="schedule.png",
            content_type="image/png",
            data=_png_bytes(),
        )
    )

    assert html.text == "Data Structure"
    assert not html.is_multimodal
    assert pdf.image_data_urls == ("data:image/jpeg;base64,cGRm",)
    assert image.is_multimodal
    assert image.image_data_urls[0].startswith("data:image/jpeg;base64,")


def test_pdf_pages_are_rendered_to_multimodal_images():
    """验证 `pdf_pages_are_rendered_to_multimodal_images` 场景。"""
    pdf = io.BytesIO()
    pages = [
        Image.new("RGB", (64, 48), "white"),
        Image.new("RGB", (64, 48), "lightgray"),
    ]
    pages[0].save(
        pdf,
        format="PDF",
        save_all=True,
        append_images=pages[1:],
    )

    images = schedule_import_service._pdf_image_data_urls(pdf.getvalue())

    assert len(images) == 2
    assert all(item.startswith("data:image/jpeg;base64,") for item in images)


def test_pdf_page_limit_prevents_oversized_multimodal_prompt():
    """验证 `pdf_page_limit_prevents_oversized_multimodal_prompt` 场景。"""
    pdf = io.BytesIO()
    pages = [
        Image.new("RGB", (16, 16), "white")
        for _ in range(schedule_import_service.MAX_PDF_PAGES + 1)
    ]
    pages[0].save(
        pdf,
        format="PDF",
        save_all=True,
        append_images=pages[1:],
    )

    with pytest.raises(ValueError, match="PDF 最多支持"):
        schedule_import_service._pdf_image_data_urls(pdf.getvalue())


def test_schedule_structure_is_extracted_by_auxiliary_client():
    """验证 `schedule_structure_is_extracted_by_auxiliary_client` 场景。"""
    class _Client:
        """封装 `_Client` 的状态与行为。"""
        async def chat(self, messages, *, max_tokens, temperature):
            """处理 `chat` 相关逻辑。

            Args:
                messages: object => 消息列表。
                max_tokens: object => `max_tokens` 参数。
                temperature: object => `temperature` 参数。

            Returns:
                object => 处理结果。
            """
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
            document=schedule_import_service.ExtractedScheduleDocument(
                text="周一第1-2节 数据结构 张老师 A101"
            ),
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


def test_schedule_image_is_sent_as_multimodal_content():
    """验证 `schedule_image_is_sent_as_multimodal_content` 场景。"""
    image_url = "data:image/jpeg;base64,aW1hZ2U="

    class _Client:
        """封装 `_Client` 的状态与行为。"""
        async def chat(self, messages, *, max_tokens, temperature):
            """处理 `chat` 相关逻辑。

            Args:
                messages: object => 消息列表。
                max_tokens: object => `max_tokens` 参数。
                temperature: object => `temperature` 参数。

            Returns:
                object => 处理结果。
            """
            content = messages[1]["content"]
            assert isinstance(content, list)
            assert content[0]["type"] == "text"
            assert content[1] == {
                "type": "image_url",
                "image_url": {"url": image_url},
            }
            return """[{
              "name": "高等数学",
              "weekday": 2,
              "start_period": 3,
              "end_period": 4
            }]"""

    courses = asyncio.run(
        schedule_import_service.extract_schedule_courses(
            llm_client=_Client(),
            document=schedule_import_service.ExtractedScheduleDocument(
                image_data_urls=(image_url,)
            ),
            total_weeks=18,
            settings={},
            max_output_tokens=512,
        )
    )

    assert courses[0]["name"] == "高等数学"
    assert courses[0]["weekday"] == 2


def test_schedule_docir_projection_preserves_metadata_and_original_name(
    monkeypatch,
):
    """验证 `schedule_docir_projection_preserves_metadata_and_original_name` 场景。"""
    class _Sessions:
        """封装 `_Sessions` 的状态与行为。"""
        def __init__(self):
            """初始化 `_Sessions` 实例。"""
            self.cleared = False

        async def prepare(self, session_key, paths):
            """准备 `prepare` 相关数据。

            Args:
                session_key: object => `session_key` 参数。
                paths: object => `paths` 参数。

            Returns:
                object => 处理结果。
            """
            source = paths[0]
            assert source.name == "课程表.xlsx"
            assert source.read_bytes() == b"xlsx"
            document = SimpleNamespace(
                document_id="schedule-doc",
                validation=SimpleNamespace(
                    status=SimpleNamespace(value="passed")
                ),
                elements=(1, 2, 3),
                source_page_count=None,
                parsed_page_count=1,
            )
            return (SimpleNamespace(document=document),)

        async def clear(self, session_key):
            """清空 `clear` 相关数据。"""
            self.cleared = True

    sessions = _Sessions()
    monkeypatch.setattr(
        schedule_import_service,
        "render_document_markdown",
        lambda document: "| 周一 | 周二 |\n| 数据结构 | 高等数学 |",
    )

    document = asyncio.run(
        schedule_import_service.extract_schedule_document_via_docir(
            mm_sessions=sessions,
            session_key="schedule:u1:run",
            filename="课程表.xlsx",
            data=b"xlsx",
        )
    )

    assert document.pipeline == "docir"
    assert document.docir_document_id == "schedule-doc"
    assert document.docir_element_count == 3
    assert "数据结构" in document.text
    assert sessions.cleared

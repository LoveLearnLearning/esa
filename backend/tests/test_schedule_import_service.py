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

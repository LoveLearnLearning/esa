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


def test_html_table_preserves_row_and_column_structure():
    html = asyncio.run(
        schedule_import_service.extract_document_text(
            filename="schedule.html",
            content_type="text/html",
            data=(
                "<table>"
                "<tr><th>节次</th><th>周一</th><th>周二</th></tr>"
                "<tr><td>1-2</td><td></td><td>数据结构</td></tr>"
                "</table>"
            ).encode("utf-8"),
        )
    )
    # 表头与单元格保持行列对应，空单元格保留占位，星期信息不丢失
    assert "节次 | 周一 | 周二" in html
    assert "1-2 | - | 数据结构" in html


def test_normalization_keeps_intra_line_spacing():
    text = asyncio.run(
        schedule_import_service.extract_document_text(
            filename="schedule.html",
            content_type="text/html",
            data="<pre>节次    周一        周二</pre>".encode("utf-8"),
        )
    )
    # layout 模式抽取的 PDF 依赖行内连续空格表达列位置，不能被压缩
    assert "节次    周一        周二" == text

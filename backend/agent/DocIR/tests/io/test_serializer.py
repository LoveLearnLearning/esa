# backend/agent/DocIR/tests/io/test_serializer.py

"""

这个文件干什么：验证当前 DocIR JSON 往返读写和 Schema 导出行为。

直白点说就是：检查文档保存后再读回来是否一致，并确认只有一个当前 contract。
"""

import json

from backend.agent.DocIR.io import export_json_schema, load_document, save_document
from backend.agent.DocIR.tests.core.test_document import make_document


def test_round_trip_and_schema(tmp_path):
    path = tmp_path / "document.json"
    save_document(make_document(), path)
    assert load_document(path) == make_document().model_copy(update={"created_at": load_document(path).created_at})
    schema = tmp_path / "schema.json"
    export_json_schema(schema)
    payload = json.loads(schema.read_text())
    assert "Element" in json.dumps(payload)
    assert "schema_version" not in payload.get("properties", {})

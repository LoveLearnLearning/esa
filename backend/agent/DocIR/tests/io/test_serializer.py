# backend/agent/DocIR/tests/io/test_serializer.py

"""

这个文件干什么：验证 DocIR JSON 往返读写、Schema 导出和版本拒绝行为。

直白点说就是：检查文档保存后再读回来是否一致，并确保旧版本不会被当成 V0.2 悄悄读入。
"""

import json

import pytest

from backend.agent.DocIR.io import export_json_schema, load_document, save_document
from backend.agent.DocIR.tests.core.test_v02_document import make_document


def test_round_trip_and_schema(tmp_path):
    path = tmp_path / "document.json"
    save_document(make_document(), path)
    assert load_document(path) == make_document().model_copy(update={"created_at": load_document(path).created_at})
    schema = tmp_path / "schema.json"
    export_json_schema(schema)
    payload = json.loads(schema.read_text())
    assert "Element" in json.dumps(payload)


def test_v01_is_not_loaded_silently(tmp_path):
    path = tmp_path / "old.json"
    path.write_text('{"schema_version":"0.1"}')
    with pytest.raises(ValueError, match="显式迁移"):
        load_document(path)

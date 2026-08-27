import json
from pathlib import Path

from projector import project_for_model, project_for_query
from router import Profile, RuleBasedRouter
from serializer import token_count


def fixture():
    path = Path(__file__).parents[1] / "fixtures" / "sample_result.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_minimal_projection_has_only_ref_and_content_and_preserves_channels():
    payload = fixture()
    result = project_for_model(payload, Profile.MINIMAL)
    assert all(set(item) == {"ref", "content"} for item in result["model_content"]["results"])
    assert result["audit_metadata"]["full_retrieval"] == payload
    assert set(result["audit_metadata"]["ref_registry"]) == {"C1", "C2", "C3"}
    assert result["display_content"]["results"][0]["page"] == 12


def test_profiles_add_metadata_progressively():
    payload = fixture()
    minimal = project_for_model(payload, Profile.MINIMAL)["model_content"]["results"][0]
    source = project_for_model(payload, Profile.SOURCE)["model_content"]["results"][0]
    location = project_for_model(payload, Profile.LOCATION)["model_content"]["results"][0]
    full = project_for_model(payload, Profile.FULL)["model_content"]["results"][0]
    assert set(minimal) == {"ref", "content"}
    assert source["source"] == "软件测试基础.pdf"
    assert location["page"] == 12 and location["section"] == "第三章 / 测试方法"
    assert full["metadata"]["element_id"] == "el-black"
    assert token_count(minimal) < token_count(source) < token_count(location) < token_count(full)


def test_router_examples_and_explicit_negative():
    router = RuleBasedRouter()
    assert router.route("黑盒测试和白盒测试有什么区别？").profile is Profile.MINIMAL
    assert router.route("这个结论来自哪份文档？").profile is Profile.SOURCE
    assert router.route("这段内容在哪一页？").profile is Profile.LOCATION
    assert router.route("不用告诉我出处，直接解释").profile is Profile.MINIMAL
    assert router.route("给我检索 score 和完整 metadata").profile is Profile.FULL
    decision, result = project_for_query(fixture(), "这个结论来自哪份文档？", router)
    assert decision.need_provenance is True
    assert result["model_content"]["profile"] == "SOURCE"

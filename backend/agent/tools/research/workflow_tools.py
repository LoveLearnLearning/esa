"""Schema registrations; trusted identity/resources are bound by the executor."""

from __future__ import annotations

from backend.agent.tools.tools import tr


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type":"function","function":{"name":name,"description":description,
        "parameters":{"type":"object","properties":properties,"required":required}}}


@tr.register(_schema("start_frontier_tracking","为当前已绑定科研项目创建前沿追踪任务",
    {"query":{"type":"string"},"time_window_years":{"type":"integer","default":5},
     "max_results":{"type":"integer","default":20}},["query"]))
def start_frontier_tracking(query: str, time_window_years: int=5, max_results: int=20) -> dict:
    raise RuntimeError("workflow tool requires BoundToolExecutor")


@tr.register(_schema("start_research_writing","为已授权科研文档创建写作任务",
    {"document_id":{"type":"string"},"operation":{"type":"string"},
     "instruction":{"type":"string","default":""},"source_text":{"type":"string","default":""}},
    ["document_id","operation"]))
def start_research_writing(document_id: str, operation: str, instruction: str="", source_text: str="") -> dict:
    raise RuntimeError("workflow tool requires BoundToolExecutor")


@tr.register(_schema("start_dataset_analysis","为已授权科研数据集创建分析任务",
    {"dataset_id":{"type":"string"},"analysis_type":{"type":"string"},
     "parameters":{"type":"object"}},["dataset_id","analysis_type","parameters"]))
def start_dataset_analysis(dataset_id: str, analysis_type: str, parameters: dict) -> dict:
    raise RuntimeError("workflow tool requires BoundToolExecutor")


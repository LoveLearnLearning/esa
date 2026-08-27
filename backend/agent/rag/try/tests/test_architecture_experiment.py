from architecture_experiment import run


def test_extra_llm_tool_hop_costs_more_and_keeps_baseline_observation():
    report = run()
    rows = {item["candidate"]: item for item in report["candidates"]}
    middleware = rows["C_internal_middleware"]
    naive_tool = rows["B_llm_tool_naive"]
    opaque_tool = rows["B_llm_tool_opaque_handle"]
    assert middleware["generation_calls"] == 2
    assert middleware["tool_calls"] == 1
    assert naive_tool["generation_calls"] == 3
    assert naive_tool["persisted_model_observation_tokens"] > middleware["persisted_model_observation_tokens"]
    assert naive_tool["total_input_prompt_proxy_tokens"] > opaque_tool["total_input_prompt_proxy_tokens"] > middleware["total_input_prompt_proxy_tokens"]


def test_integrated_and_middleware_have_same_model_visible_topology():
    rows = {item["candidate"]: item for item in run()["candidates"]}
    integrated = rows["A_integrated_retrieve"]
    middleware = rows["C_internal_middleware"]
    assert integrated["input_prompt_proxy_tokens_by_generation"] == middleware["input_prompt_proxy_tokens_by_generation"]
    assert integrated["final_prompt_proxy_tokens"] == middleware["final_prompt_proxy_tokens"]


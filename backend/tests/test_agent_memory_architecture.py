# backend/tests/test_agent_memory_architecture.py

"""验证 `agent_memory_architecture` 相关行为与回归场景。"""

import inspect

from backend.agent.agent import Agent


def test_agent_public_entrypoints_only_accept_run_spec():
    """验证 `agent_public_entrypoints_only_accept_run_spec` 场景。"""
    run_parameters = tuple(inspect.signature(Agent.run).parameters)
    stream_parameters = tuple(inspect.signature(Agent.run_stream).parameters)
    assert run_parameters == ("self", "run_spec")
    assert stream_parameters == ("self", "run_spec")
    assert not hasattr(Agent, "_prepare_run")

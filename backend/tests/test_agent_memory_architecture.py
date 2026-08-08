import inspect

from backend.agent.agent import Agent


def test_agent_prepare_run_does_not_eagerly_read_core_memory():
    source = inspect.getsource(Agent._prepare_run)

    assert "core_memory" not in source
    assert "build_context" not in source
    assert "core_context" not in source

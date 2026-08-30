"""Tests for the in-process Agent runtime metric aggregator."""

from __future__ import annotations

from backend.agent.runtime_metrics import AgentRuntimeMetrics
from backend.agent.workspaces.models import AgentLoopState


def _state(
    *,
    iteration: int,
    tool_attempts: int = 0,
    retries: int = 0,
    retry_successes: int = 0,
    timeouts: int = 0,
    duplicates: int = 0,
    termination_reason: str | None = None,
) -> AgentLoopState:
    return AgentLoopState(
        started_at=0.0,
        iteration=iteration,
        tool_attempts=tool_attempts,
        retry_counts={"test_tool": retries} if retries else {},
        termination_reason=termination_reason,
        timeout_count=timeouts,
        retry_success_count=retry_successes,
        duplicate_call_count=duplicates,
    )


def test_agent_runtime_metrics_empty_snapshot_is_zeroed():
    metrics = AgentRuntimeMetrics()

    assert metrics.snapshot() == {
        "runs_total": 0,
        "termination_counts": {},
        "iteration_limit_ratio": 0.0,
        "tool_call_limit_ratio": 0.0,
        "tool_timeout_ratio": 0.0,
        "tool_retry_success_ratio": 0.0,
        "duplicate_call_ratio": 0.0,
        "final_answer_empty_ratio": 0.0,
        "average_iterations_by_workspace": {},
        "latency_ms_p95": 0.0,
        "latency_ms_p99": 0.0,
        "tool_attempts": 0,
        "timeout_count": 0,
        "retry_count": 0,
        "retry_success_count": 0,
        "duplicate_call_count": 0,
    }


def test_agent_runtime_metrics_aggregate_ratios_and_workspace_averages():
    metrics = AgentRuntimeMetrics()
    observations = (
        (
            "learning",
            _state(
                iteration=2,
                tool_attempts=4,
                retries=1,
                retry_successes=1,
                timeouts=1,
                duplicates=1,
                termination_reason="iteration_limit",
            ),
            100.0,
            False,
        ),
        (
            "learning",
            _state(
                iteration=4,
                tool_attempts=6,
                retries=2,
                retry_successes=1,
                timeouts=2,
                termination_reason="tool_call_limit",
            ),
            200.0,
            True,
        ),
        (
            "research",
            _state(
                iteration=3,
                duplicates=1,
                termination_reason="completed",
            ),
            300.0,
            False,
        ),
    )
    for workspace, state, latency_ms, final_answer_empty in observations:
        metrics.record(
            workspace=workspace,
            state=state,
            latency_ms=latency_ms,
            final_answer_empty=final_answer_empty,
        )

    snapshot = metrics.snapshot()
    assert snapshot["runs_total"] == 3
    assert snapshot["termination_counts"] == {
        "completed": 1,
        "iteration_limit": 1,
        "tool_call_limit": 1,
    }
    assert snapshot["iteration_limit_ratio"] == 0.333333
    assert snapshot["tool_call_limit_ratio"] == 0.333333
    assert snapshot["tool_timeout_ratio"] == 0.3
    assert snapshot["tool_retry_success_ratio"] == 0.666667
    assert snapshot["duplicate_call_ratio"] == 0.166667
    assert snapshot["final_answer_empty_ratio"] == 0.333333
    assert snapshot["average_iterations_by_workspace"] == {
        "learning": 3.0,
        "research": 3.0,
    }
    assert snapshot["latency_ms_p95"] == 300.0
    assert snapshot["latency_ms_p99"] == 300.0


def test_agent_runtime_metrics_latency_window_and_prometheus_output():
    metrics = AgentRuntimeMetrics(latency_window=100)
    for latency_ms in range(1, 101):
        metrics.record(
            workspace="learning",
            state=_state(iteration=1),
            latency_ms=float(latency_ms),
            final_answer_empty=False,
        )

    snapshot = metrics.snapshot()
    assert snapshot["latency_ms_p95"] == 95.0
    assert snapshot["latency_ms_p99"] == 99.0

    prometheus = metrics.to_prometheus()
    assert "agent_runs_total 100\n" in prometheus
    assert 'agent_latency_ms{quantile="0.95"} 95.0\n' in prometheus
    assert 'agent_latency_ms{quantile="0.99"} 99.0\n' in prometheus
    assert 'agent_average_iterations{workspace="learning"} 1.0\n' in prometheus


def test_agent_runtime_metrics_rejects_invalid_latency_window():
    try:
        AgentRuntimeMetrics(latency_window=0)
    except ValueError as exc:
        assert str(exc) == "latency_window must be positive"
    else:
        raise AssertionError("invalid latency window must be rejected")

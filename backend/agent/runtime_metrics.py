"""In-process operational metrics for bounded Agent turns."""

from __future__ import annotations

import math
import threading
from collections import Counter, defaultdict, deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.agent.workspaces.models import AgentLoopState


class AgentRuntimeMetrics:
    """Aggregate termination, retry, duplicate, and latency observations."""

    def __init__(self, *, latency_window: int = 4096) -> None:
        if latency_window < 1:
            raise ValueError("latency_window must be positive")
        self._lock = threading.Lock()
        self._runs_total = 0
        self._termination_counts: Counter[str] = Counter()
        self._tool_attempts = 0
        self._timeout_count = 0
        self._retry_count = 0
        self._retry_success_count = 0
        self._duplicate_call_count = 0
        self._empty_final_count = 0
        self._workspace_runs: Counter[str] = Counter()
        self._workspace_iterations: defaultdict[str, int] = defaultdict(int)
        self._latencies_ms: deque[float] = deque(maxlen=latency_window)

    def record(
        self,
        *,
        workspace: str,
        state: AgentLoopState,
        latency_ms: float,
        final_answer_empty: bool,
    ) -> None:
        reason = state.termination_reason or "completed"
        with self._lock:
            self._runs_total += 1
            self._termination_counts[reason] += 1
            self._tool_attempts += state.tool_attempts
            self._timeout_count += state.timeout_count
            self._retry_count += state.retry_count
            self._retry_success_count += state.retry_success_count
            self._duplicate_call_count += state.duplicate_call_count
            self._empty_final_count += int(final_answer_empty)
            self._workspace_runs[workspace] += 1
            self._workspace_iterations[workspace] += state.iteration
            self._latencies_ms.append(max(0.0, latency_ms))

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            runs_total = self._runs_total
            attempts = self._tool_attempts
            retry_count = self._retry_count
            latencies = sorted(self._latencies_ms)
            workspace_averages = {
                workspace: round(
                    self._workspace_iterations[workspace] / run_count, 3
                )
                for workspace, run_count in sorted(self._workspace_runs.items())
                if run_count
            }
            return {
                "runs_total": runs_total,
                "termination_counts": dict(sorted(self._termination_counts.items())),
                "iteration_limit_ratio": self._ratio(
                    self._termination_counts["iteration_limit"], runs_total
                ),
                "tool_call_limit_ratio": self._ratio(
                    self._termination_counts["tool_call_limit"], runs_total
                ),
                "tool_timeout_ratio": self._ratio(self._timeout_count, attempts),
                "tool_retry_success_ratio": self._ratio(
                    self._retry_success_count, retry_count
                ),
                "duplicate_call_ratio": self._ratio(
                    self._duplicate_call_count,
                    attempts + self._duplicate_call_count,
                ),
                "final_answer_empty_ratio": self._ratio(
                    self._empty_final_count, runs_total
                ),
                "average_iterations_by_workspace": workspace_averages,
                "latency_ms_p95": self._percentile(latencies, 0.95),
                "latency_ms_p99": self._percentile(latencies, 0.99),
                "tool_attempts": attempts,
                "timeout_count": self._timeout_count,
                "retry_count": retry_count,
                "retry_success_count": self._retry_success_count,
                "duplicate_call_count": self._duplicate_call_count,
            }

    def to_prometheus(self) -> str:
        snapshot = self.snapshot()
        lines = [
            "# TYPE agent_runs_total counter",
            f"agent_runs_total {snapshot['runs_total']}",
            "# TYPE agent_iteration_limit_ratio gauge",
            f"agent_iteration_limit_ratio {snapshot['iteration_limit_ratio']}",
            "# TYPE agent_tool_call_limit_ratio gauge",
            f"agent_tool_call_limit_ratio {snapshot['tool_call_limit_ratio']}",
            "# TYPE agent_tool_timeout_ratio gauge",
            f"agent_tool_timeout_ratio {snapshot['tool_timeout_ratio']}",
            "# TYPE agent_tool_retry_success_ratio gauge",
            f"agent_tool_retry_success_ratio {snapshot['tool_retry_success_ratio']}",
            "# TYPE agent_duplicate_call_ratio gauge",
            f"agent_duplicate_call_ratio {snapshot['duplicate_call_ratio']}",
            "# TYPE agent_final_answer_empty_ratio gauge",
            f"agent_final_answer_empty_ratio {snapshot['final_answer_empty_ratio']}",
            "# TYPE agent_latency_ms gauge",
            f"agent_latency_ms{{quantile=\"0.95\"}} {snapshot['latency_ms_p95']}",
            f"agent_latency_ms{{quantile=\"0.99\"}} {snapshot['latency_ms_p99']}",
        ]
        for workspace, value in snapshot["average_iterations_by_workspace"].items():
            lines.append(
                "agent_average_iterations{workspace=\""
                + workspace
                + f'"}} {value}'
            )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 6) if denominator else 0.0

    @staticmethod
    def _percentile(values: list[float], ratio: float) -> float:
        if not values:
            return 0.0
        index = max(0, math.ceil(len(values) * ratio) - 1)
        return round(values[index], 3)


AGENT_RUNTIME_METRICS = AgentRuntimeMetrics()

# backend/agent/rag/evaluation/benchmark.py

"""

这个文件干什么：为 vLLM、Transformers、Sentence Transformers 提供后端无关的基础压测框架。

直白点说就是：用同一套计时和统计方法测试不同模型后端的启动速度、延迟、吞吐和内存占用。
"""

from __future__ import annotations

import resource
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from statistics import mean
from typing import Protocol, TypeVar


class BatchOperation(Protocol):
    """描述接受一批文本的可调用压测操作。"""

    def __call__(self, values: Sequence[str]) -> object:
        """执行一次批处理推理或评分操作。"""

        ...


T = TypeVar("T")


@dataclass(frozen=True)
class BenchmarkResult:
    """一次可比较的模型后端基础压测结果。"""

    backend: str
    startup_seconds: float
    batch_size: int
    iterations: int
    mean_latency_seconds: float
    p95_latency_seconds: float
    items_per_second: float
    max_rss_kib: int

    def as_dict(self) -> dict[str, object]:
        """把不可变压测结果转换为便于序列化的字典。"""

        return asdict(self)


def benchmark_backend(
    backend_name: str,
    factory: Callable[[], T],
    operation: Callable[[T, Sequence[str]], object],
    samples: Sequence[str],
    *,
    iterations: int = 5,
) -> BenchmarkResult:
    """用同一批输入探测 vLLM、Transformers 或 Sentence Transformers。

    GPU 显存和模型共存干扰应由部署压测脚本采集；max_rss_kib 只是可移植的
    进程级基线，不能替代 A800 上的显存监测。
    """
    if not samples or iterations <= 0:
        raise ValueError("samples and positive iterations are required")
    started = time.perf_counter()
    backend = factory()
    # 首次调用包含模型加载/图编译等冷启动成本，因此与稳态迭代分开记录。
    operation(backend, samples[:1])
    startup = time.perf_counter() - started
    latencies = []
    for _ in range(iterations):
        started = time.perf_counter()
        operation(backend, samples)
        latencies.append(time.perf_counter() - started)
    ordered = sorted(latencies)
    p95_index = min(len(ordered) - 1, math_ceil(0.95 * len(ordered)) - 1)
    average = mean(latencies)
    return BenchmarkResult(
        backend=backend_name,
        startup_seconds=startup,
        batch_size=len(samples),
        iterations=iterations,
        mean_latency_seconds=average,
        p95_latency_seconds=ordered[p95_index],
        items_per_second=len(samples) / average if average else float("inf"),
        max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    )


def math_ceil(value: float) -> int:
    """避免为一个简单 P95 索引额外引入数值计算依赖。"""

    integer = int(value)
    return integer if integer == value else integer + 1

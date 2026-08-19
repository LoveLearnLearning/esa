# backend/core/services/research_data_service.py

"""提供领域服务实现。"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import math
import re
import statistics
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from backend.core.stores.research_data_store import ResearchDataStore

MAX_DATASET_BYTES = 15 * 1024 * 1024
MAX_PROFILE_ROWS = 100_000
_TEXT_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9-]{2,}|[\u4e00-\u9fff]{2,}")


class ResearchDataService:
    """提供 `research data service` 领域服务。"""
    def __init__(
        self,
        store: ResearchDataStore,
        storage_root: str | Path,
    ) -> None:
        """初始化 `ResearchDataService` 实例。"""
        self.store = store
        self.storage_root = Path(storage_root).resolve()
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    def start(self, *, recover_interrupted: bool = True) -> None:
        """启动 `start` 相关数据。"""
        if self._worker is not None and not self._worker.done():
            return
        if recover_interrupted:
            for job_id in self.store.requeue_interrupted():
                self._queue.put_nowait(job_id)
        self._worker = asyncio.create_task(self._run_worker())

    async def stop(self) -> None:
        """停止 `stop` 相关数据。"""
        worker = self._worker
        self._worker = None
        if worker is None:
            return
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass

    def submit(self, job_id: str) -> None:
        """处理 `submit` 相关逻辑。"""
        self._queue.put_nowait(job_id)

    async def _run_worker(self) -> None:
        """执行 `worker` 相关数据。"""
        while True:
            job_id = await self._queue.get()
            try:
                await asyncio.to_thread(self.run_job, job_id)
            finally:
                self._queue.task_done()

    def ingest(
        self,
        *,
        project_id: str,
        user_id: str,
        name: str,
        filename: str,
        media_type: str,
        content: bytes,
    ) -> dict:
        """处理 `ingest` 相关逻辑。

        Args:
            project_id: str => 项目 ID。
            user_id: str => 用户 ID。
            name: str => `name` 参数。
            filename: str => 文件名。
            media_type: str => `media_type` 参数。
            content: bytes => 待处理内容。

        Returns:
            dict => 处理结果。
        """
        if not content:
            raise ValueError("dataset file is empty")
        if len(content) > MAX_DATASET_BYTES:
            raise ValueError("dataset file exceeds 15 MB")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".csv", ".json", ".txt"}:
            raise ValueError("only CSV, JSON, and TXT datasets are supported")
        dataset_id = str(uuid.uuid4())
        directory = (self.storage_root / user_id / project_id).resolve()
        if self.storage_root not in directory.parents:
            raise ValueError("invalid dataset storage path")
        directory.mkdir(parents=True, exist_ok=True)
        file_path = directory / f"{dataset_id}{suffix}"
        file_path.write_bytes(content)
        try:
            rows = self._read_rows(file_path)
            profile = self.profile(rows)
            return self.store.create_dataset(
                dataset_id=dataset_id,
                project_id=project_id,
                user_id=user_id,
                name=name,
                original_filename=Path(filename).name,
                media_type=media_type or "application/octet-stream",
                file_path=str(file_path),
                size_bytes=len(content),
                profile=profile,
            )
        except Exception:
            file_path.unlink(missing_ok=True)
            raise

    def run_job(self, job_id: str) -> dict | None:
        """执行 `job` 相关数据。

        Args:
            job_id: str => job ID。

        Returns:
            dict | None => 处理结果。
        """
        job = self.store.claim_job(job_id)
        if job is None:
            return None
        dataset = self.store.get_dataset(
            job["dataset_id"], job["user_id"], include_path=True
        )
        if dataset is None:
            self.store.fail_job(job_id, "dataset no longer exists")
            return self.store.get_job(job_id)
        try:
            rows = self._read_rows(Path(dataset["file_path"]))
            result = self.analyze(job["analysis_type"], rows, job["parameters"])
            self.store.complete_job(job_id, result)
        except Exception as error:
            self.store.fail_job(job_id, str(error))
        return self.store.get_job(job_id)

    @classmethod
    def _read_rows(cls, path: Path) -> list[dict[str, Any]]:
        """读取 `rows` 相关数据。"""
        suffix = path.suffix.lower()
        text = path.read_text(encoding="utf-8-sig")
        if suffix == ".csv":
            reader = csv.DictReader(io.StringIO(text))
            if not reader.fieldnames:
                raise ValueError("CSV has no header row")
            return [dict(row) for _, row in zip(range(MAX_PROFILE_ROWS), reader)]
        if suffix == ".json":
            payload = json.loads(text)
            if isinstance(payload, dict):
                payload = payload.get("data", [payload])
            if not isinstance(payload, list) or not all(
                isinstance(item, dict) for item in payload
            ):
                raise ValueError("JSON dataset must be an object or a list of objects")
            return [dict(item) for item in payload[:MAX_PROFILE_ROWS]]
        return [{"text": line} for line in text.splitlines() if line.strip()][
            :MAX_PROFILE_ROWS
        ]

    @classmethod
    def profile(cls, rows: list[dict[str, Any]]) -> dict:
        """处理 `profile` 相关逻辑。

        Args:
            rows: list[dict[str, Any]] => `rows` 参数。

        Returns:
            dict => 处理结果。
        """
        if not rows:
            raise ValueError("dataset contains no records")
        columns = list(dict.fromkeys(key for row in rows for key in row))
        column_profiles = []
        for column in columns:
            values = [row.get(column) for row in rows]
            present = [value for value in values if value not in (None, "")]
            numeric = [value for value in (cls._number(item) for item in present) if value is not None]
            is_numeric = bool(present) and len(numeric) / len(present) >= 0.9
            profile: dict[str, Any] = {
                "name": column,
                "type": "numeric" if is_numeric else "text",
                "missing_count": len(values) - len(present),
                "unique_count": len({str(item) for item in present}),
            }
            if is_numeric and numeric:
                profile.update(
                    min=min(numeric),
                    max=max(numeric),
                    mean=round(statistics.fmean(numeric), 6),
                    median=round(statistics.median(numeric), 6),
                )
            else:
                profile["top_values"] = [
                    {"value": value, "count": count}
                    for value, count in Counter(str(item) for item in present).most_common(5)
                ]
            column_profiles.append(profile)
        return {
            "row_count": len(rows),
            "column_count": len(columns),
            "columns": column_profiles,
            "profile_limited": len(rows) >= MAX_PROFILE_ROWS,
        }

    @classmethod
    def analyze(
        cls,
        analysis_type: str,
        rows: list[dict[str, Any]],
        parameters: dict,
    ) -> dict:
        """处理 `analyze` 相关逻辑。

        Args:
            analysis_type: str => `analysis_type` 参数。
            rows: list[dict[str, Any]] => `rows` 参数。
            parameters: dict => `parameters` 参数。

        Returns:
            dict => 处理结果。
        """
        if analysis_type == "descriptive":
            return {"analysis_type": analysis_type, "profile": cls.profile(rows)}
        if analysis_type == "correlation":
            return cls._correlations(rows)
        if analysis_type == "group_compare":
            return cls._group_compare(rows, parameters)
        if analysis_type == "text_frequency":
            return cls._text_frequency(rows, parameters)
        raise ValueError(f"unsupported analysis type: {analysis_type}")

    @classmethod
    def _correlations(cls, rows: list[dict[str, Any]]) -> dict:
        """处理 `_correlations` 相关逻辑。"""
        columns = list(dict.fromkeys(key for row in rows for key in row))
        numeric_columns = [
            column
            for column in columns
            if sum(cls._number(row.get(column)) is not None for row in rows)
            >= max(3, math.ceil(len(rows) * 0.8))
        ]
        pairs = []
        for index, left in enumerate(numeric_columns):
            for right in numeric_columns[index + 1 :]:
                paired = [
                    (a, b)
                    for row in rows
                    if (a := cls._number(row.get(left))) is not None
                    and (b := cls._number(row.get(right))) is not None
                ]
                if len(paired) < 3:
                    continue
                xs, ys = zip(*paired, strict=True)
                mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
                numerator = sum((x - mean_x) * (y - mean_y) for x, y in paired)
                denominator = math.sqrt(
                    sum((x - mean_x) ** 2 for x in xs)
                    * sum((y - mean_y) ** 2 for y in ys)
                )
                correlation = numerator / denominator if denominator else 0.0
                pairs.append(
                    {
                        "left": left,
                        "right": right,
                        "pearson_r": round(correlation, 6),
                        "sample_size": len(paired),
                    }
                )
        pairs.sort(key=lambda item: abs(item["pearson_r"]), reverse=True)
        return {
            "analysis_type": "correlation",
            "numeric_columns": numeric_columns,
            "pairs": pairs,
            "method_note": "Pearson correlation is descriptive and does not establish causality.",
        }

    @classmethod
    def _group_compare(cls, rows: list[dict[str, Any]], parameters: dict) -> dict:
        """处理 `_group_compare` 相关逻辑。"""
        group_column = str(parameters.get("group_column", ""))
        metric_column = str(parameters.get("metric_column", ""))
        if not group_column or not metric_column:
            raise ValueError("group_column and metric_column are required")
        groups: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            value = cls._number(row.get(metric_column))
            group = row.get(group_column)
            if value is not None and group not in (None, ""):
                groups[str(group)].append(value)
        if not groups:
            raise ValueError("no usable grouped numeric values")
        return {
            "analysis_type": "group_compare",
            "group_column": group_column,
            "metric_column": metric_column,
            "groups": [
                {
                    "group": group,
                    "count": len(values),
                    "mean": round(statistics.fmean(values), 6),
                    "median": round(statistics.median(values), 6),
                    "min": min(values),
                    "max": max(values),
                }
                for group, values in sorted(groups.items())
            ],
            "method_note": "This is a descriptive comparison without significance testing.",
        }

    @classmethod
    def _text_frequency(cls, rows: list[dict[str, Any]], parameters: dict) -> dict:
        """处理 `_text_frequency` 相关逻辑。"""
        requested = str(parameters.get("text_column", ""))
        columns = [requested] if requested else list(
            dict.fromkeys(key for row in rows for key in row)
        )
        counts: Counter[str] = Counter()
        for row in rows:
            for column in columns:
                counts.update(token.lower() for token in _TEXT_TOKEN.findall(str(row.get(column, ""))))
        return {
            "analysis_type": "text_frequency",
            "columns": columns,
            "terms": [
                {"term": term, "count": count}
                for term, count in counts.most_common(50)
            ],
            "method_note": "Counts are lexical frequencies without semantic clustering.",
        }

    @staticmethod
    def _number(value: Any) -> float | None:
        """处理 `_number` 相关逻辑。"""
        if value in (None, "") or isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

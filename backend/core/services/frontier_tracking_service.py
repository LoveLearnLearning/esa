from __future__ import annotations

import asyncio
import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from backend.agent.tools.arxiv_search import arxiv_search
from backend.core.stores.frontier_tracking_store import FrontierTrackingStore

SearchFunction = Callable[..., dict[str, Any]]
_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9-]{2,}")
_STOP_WORDS = frozenset(
    {
        "the", "and", "for", "with", "from", "that", "this", "using",
        "based", "via", "towards", "toward", "into", "over", "under",
        "model", "models", "method", "methods", "approach", "study",
        "analysis", "learning", "research", "paper", "results", "new",
    }
)


class FrontierTrackingService:
    """Single-process worker backed by a durable SQLite queue."""

    def __init__(
        self,
        store: FrontierTrackingStore,
        *,
        search: SearchFunction = arxiv_search,
    ) -> None:
        self.store = store
        self.search = search
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    def start(self, *, recover_interrupted: bool = True) -> None:
        if self._worker is not None and not self._worker.done():
            return
        if recover_interrupted:
            for job_id in self.store.requeue_interrupted():
                self._queue.put_nowait(job_id)
        self._worker = asyncio.create_task(self._run_worker())

    async def stop(self) -> None:
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
        self._queue.put_nowait(job_id)

    async def _run_worker(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await asyncio.to_thread(self.run_job, job_id)
            finally:
                self._queue.task_done()

    def run_job(self, job_id: str) -> dict | None:
        job = self.store.claim_job(job_id)
        if job is None:
            return None
        try:
            result = self._search_and_analyze(job)
        except Exception as error:
            self.store.fail_job(job_id, str(error))
            return self.store.get_job(job_id)
        self.store.complete_job(job_id, result)
        return self.store.get_job(job_id)

    def _search_and_analyze(self, job: dict) -> dict:
        requested = int(job["max_results"])
        recent_count = min(20, max(5, math.ceil(requested / 2)))
        relevant_count = min(20, max(5, requested - recent_count))
        recent = self.search(
            job["query"],
            max_results=recent_count,
            sort_by="submitted",
            sort_order="descending",
        )
        relevant = self.search(
            job["query"],
            max_results=relevant_count,
            sort_by="relevance",
            sort_order="descending",
        )
        papers = self._deduplicate(
            [*recent.get("results", []), *relevant.get("results", [])],
            requested,
        )
        cutoff_year = datetime.now(timezone.utc).year - int(job["time_window_years"]) + 1
        papers = [paper for paper in papers if self._year(paper) >= cutoff_year]
        if not papers:
            raise RuntimeError("arXiv returned no papers in the requested time window")
        return self.analyze(
            query=job["query"],
            papers=papers,
            time_window_years=int(job["time_window_years"]),
            source_total=max(
                int(recent.get("total_results", 0)),
                int(relevant.get("total_results", 0)),
            ),
        )

    @classmethod
    def analyze(
        cls,
        *,
        query: str,
        papers: list[dict],
        time_window_years: int,
        source_total: int = 0,
    ) -> dict:
        year_counts: Counter[int] = Counter()
        category_counts: Counter[str] = Counter()
        keyword_counts: Counter[str] = Counter()
        keyword_years: dict[str, Counter[int]] = defaultdict(Counter)
        keyword_papers: dict[str, list[str]] = defaultdict(list)

        for paper in papers:
            year = cls._year(paper)
            year_counts[year] += 1
            for category in paper.get("categories", []):
                category_counts[category] += 1
            tokens = set(cls._tokens(f"{paper.get('title', '')} {paper.get('abstract', '')}"))
            for token in tokens:
                keyword_counts[token] += 1
                keyword_years[token][year] += 1
                if len(keyword_papers[token]) < 3:
                    keyword_papers[token].append(paper.get("arxiv_id", ""))

        years = sorted(year_counts)
        midpoint = years[len(years) // 2] if years else 0
        trends = []
        for keyword, count in keyword_counts.most_common(30):
            older = sum(
                value for year, value in keyword_years[keyword].items() if year < midpoint
            )
            newer = sum(
                value for year, value in keyword_years[keyword].items() if year >= midpoint
            )
            growth = round((newer + 1) / (older + 1), 2)
            trends.append(
                {
                    "term": keyword,
                    "paper_count": count,
                    "growth_score": growth,
                    "representative_paper_ids": keyword_papers[keyword],
                }
            )

        trends.sort(key=lambda item: (item["growth_score"], item["paper_count"]), reverse=True)
        hotspots = [
            {
                "term": keyword,
                "paper_count": count,
                "share": round(count / len(papers), 3),
                "representative_paper_ids": keyword_papers[keyword],
            }
            for keyword, count in keyword_counts.most_common(10)
        ]
        return {
            "query": query,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "arXiv",
            "source_total_results": source_total,
            "paper_count": len(papers),
            "time_window_years": time_window_years,
            "year_distribution": [
                {"year": year, "paper_count": year_counts[year]}
                for year in sorted(year_counts, reverse=True)
            ],
            "top_categories": [
                {"category": category, "paper_count": count}
                for category, count in category_counts.most_common(8)
            ],
            "hotspots": hotspots,
            "emerging_terms": trends[:10],
            "papers": papers,
            "method_note": (
                "Hotspots use document frequency in titles and abstracts. "
                "Growth scores compare the newer and older halves of the returned sample; "
                "they are screening signals, not bibliometric proof."
            ),
        }

    @staticmethod
    def _deduplicate(papers: list[dict], limit: int) -> list[dict]:
        seen: set[str] = set()
        output = []
        for paper in papers:
            key = paper.get("arxiv_id") or paper.get("arxiv_url") or paper.get("title")
            if not key or key in seen:
                continue
            seen.add(key)
            output.append(paper)
            if len(output) >= limit:
                break
        return output

    @staticmethod
    def _year(paper: dict) -> int:
        value = str(paper.get("published", ""))
        try:
            return int(value[:4])
        except ValueError:
            return 0

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [
            token
            for token in (item.lower() for item in _TOKEN_PATTERN.findall(text))
            if token not in _STOP_WORDS
        ]

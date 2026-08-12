from __future__ import annotations

import asyncio

from backend.core.services.auxiliary_llm_service import AuxiliaryLLMClient
from backend.core.stores.research_writing_store import ResearchWritingStore


class ResearchWritingService:
    def __init__(
        self,
        store: ResearchWritingStore,
        llm_client: AuxiliaryLLMClient,
    ) -> None:
        self.store = store
        self.llm_client = llm_client
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
                await self.run_job(job_id)
            finally:
                self._queue.task_done()

    async def run_job(self, job_id: str) -> dict | None:
        job = self.store.claim_job(job_id)
        if job is None:
            return None
        document = self.store.get_document(job["document_id"], job["user_id"])
        if document is None:
            self.store.fail_job(job_id, "research document no longer exists")
            return self.store.get_job(job_id)
        try:
            content = await self.llm_client.chat(
                self._messages(job, document),
                max_tokens=3000,
                temperature=0.2,
            )
            self.store.complete_job(job_id, content)
        except Exception as error:
            self.store.fail_job(job_id, str(error))
        return self.store.get_job(job_id)

    @staticmethod
    def _messages(job: dict, document: dict) -> list[dict]:
        operation_rules = {
            "outline": "生成层级清晰的论文或综述大纲，并说明各部分承担的论证职责。",
            "literature_review": (
                "基于提供的资料撰写文献综述，按主题或发展脉络组织。"
                "不得虚构作者、年份、题名、DOI 或引用。"
            ),
            "polish": "保持事实、论点和引文不变，提升学术表达、连贯性与术语一致性。",
            "format_check": (
                "检查学术语言、结构、术语、引用占位和格式问题；"
                "输出修订后的完整文本，并在末尾列出关键修改。"
            ),
        }
        source = job["source_text"].strip() or document["content"]
        return [
            {
                "role": "system",
                "content": (
                    "你是科研写作助手。只使用用户提供的事实与材料；"
                    "不得编造来源、数据、实验结果或引用。缺少证据时用[待补来源]明确标记。"
                    "输出可直接保存的 Markdown 正文，不要解释内部推理。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"任务：{operation_rules[job['operation']]}\n"
                    f"文档标题：{document['title']}\n"
                    f"补充要求：{job['instruction'] or '无'}\n\n"
                    f"当前材料：\n{source or '[暂无材料]'}"
                ),
            },
        ]

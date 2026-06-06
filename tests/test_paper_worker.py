import asyncio

import pytest

from services.thesis.generation.paper_queue import PaperQueueJob
from tasks import paper_worker


def test_paper_worker_dispatches_available_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int]] = []
    jobs: list[PaperQueueJob | None] = [
        PaperQueueJob("order", 1),
        PaperQueueJob("order", 2),
        PaperQueueJob("task", 10),
        None,
    ]

    async def fake_run_order(order_id: int) -> None:
        calls.append(("order", order_id))

    async def fake_run_generation_task(generation_task_id: int) -> None:
        calls.append(("task", generation_task_id))

    async def fake_pop_ready_generation_job() -> PaperQueueJob | None:
        return jobs.pop(0)

    monkeypatch.setattr(paper_worker, "pop_ready_generation_job", fake_pop_ready_generation_job)
    monkeypatch.setattr(paper_worker, "run_paid_paper_order", fake_run_order)
    monkeypatch.setattr(paper_worker, "run_generation_task", fake_run_generation_task)

    running_tasks: set[asyncio.Task[None]] = set()

    async def run() -> None:
        await paper_worker._dispatch_pending_jobs(running_tasks, available_slots=3)
        await asyncio.gather(*running_tasks)

    asyncio.run(run())

    assert calls == [("order", 1), ("order", 2), ("task", 10)]


def test_paper_worker_drops_completed_tasks() -> None:
    async def noop() -> None:
        return None

    async def run() -> set[asyncio.Task[None]]:
        task = asyncio.create_task(noop())
        await task
        running_tasks = {task}
        paper_worker._forget_done_tasks(running_tasks)
        return running_tasks

    assert asyncio.run(run()) == set()

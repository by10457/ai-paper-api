from __future__ import annotations

import asyncio

import pytest

from core import redis as redis_module
from services.thesis.generation import paper_queue


class _FakeRedis:
    def __init__(self) -> None:
        self.ready: list[str] = []
        self.delayed: dict[str, float] = {}
        self.enqueued: set[str] = set()

    async def rpush(self, key: str, payload: str) -> None:
        assert key == paper_queue.PAPER_QUEUE_READY_KEY
        self.ready.append(payload)

    async def lpop(self, key: str) -> str | None:
        assert key == paper_queue.PAPER_QUEUE_READY_KEY
        if not self.ready:
            return None
        return self.ready.pop(0)

    async def zadd(self, key: str, mapping: dict[str, float]) -> None:
        assert key == paper_queue.PAPER_QUEUE_DELAYED_KEY
        self.delayed.update(mapping)

    async def srem(self, key: str, payload: str) -> None:
        assert key == paper_queue.PAPER_QUEUE_ENQUEUED_KEY
        self.enqueued.discard(payload)

    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> int:
        assert numkeys == 2
        if script == paper_queue._MOVE_DUE_DELAYED_SCRIPT:
            delayed_key, ready_key, max_score, raw_limit = keys_and_args
            assert delayed_key == paper_queue.PAPER_QUEUE_DELAYED_KEY
            assert ready_key == paper_queue.PAPER_QUEUE_READY_KEY
            due_payloads = [
                payload for payload, score in self.delayed.items() if score <= float(str(max_score))
            ][: int(str(raw_limit))]
            for payload in due_payloads:
                self.delayed.pop(payload, None)
                self.ready.append(payload)
            return len(due_payloads)

        enqueued_key, queue_key, raw_payload, *args = keys_and_args
        assert enqueued_key == paper_queue.PAPER_QUEUE_ENQUEUED_KEY
        assert isinstance(raw_payload, str)
        payload = raw_payload
        if payload in self.enqueued:
            return 0

        self.enqueued.add(payload)
        if queue_key == paper_queue.PAPER_QUEUE_READY_KEY:
            self.ready.append(payload)
        else:
            assert queue_key == paper_queue.PAPER_QUEUE_DELAYED_KEY
            score = float(str(args[0]))
            self.delayed[payload] = score
        return 1

    async def zrangebyscore(
        self,
        key: str,
        _min_score: int,
        max_score: float,
        *,
        start: int,
        num: int,
    ) -> list[str]:
        assert key == paper_queue.PAPER_QUEUE_DELAYED_KEY
        assert start == 0
        due_payloads = [payload for payload, score in self.delayed.items() if score <= max_score]
        return due_payloads[:num]

    def pipeline(self, *, transaction: bool) -> _FakePipeline:
        assert transaction is True
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, client: _FakeRedis) -> None:
        self.client = client

    async def __aenter__(self) -> _FakePipeline:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def zrem(self, key: str, payload: str) -> None:
        assert key == paper_queue.PAPER_QUEUE_DELAYED_KEY
        self.client.delayed.pop(payload, None)

    async def rpush(self, key: str, payload: str) -> None:
        await self.client.rpush(key, payload)

    async def execute(self) -> None:
        return None


def test_paper_queue_pushes_ready_job(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = _FakeRedis()
    monkeypatch.setattr(redis_module, "redis_client", fake_redis)

    async def run() -> None:
        assert await paper_queue.enqueue_order_generation(7)
        job = await paper_queue.pop_ready_generation_job()
        assert job == paper_queue.PaperQueueJob("order", 7)

    asyncio.run(run())


def test_paper_queue_ignores_duplicate_job(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = _FakeRedis()
    monkeypatch.setattr(redis_module, "redis_client", fake_redis)

    async def run() -> None:
        assert await paper_queue.enqueue_order_generation(7)
        assert await paper_queue.enqueue_order_generation(7)
        assert fake_redis.ready == ["order:7"]

    asyncio.run(run())


def test_paper_queue_moves_due_delayed_job(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = _FakeRedis()
    monkeypatch.setattr(redis_module, "redis_client", fake_redis)

    async def run() -> None:
        assert await paper_queue.enqueue_direct_generation(11, delay_seconds=1)
        for payload in fake_redis.delayed:
            fake_redis.delayed[payload] = 0
        assert await paper_queue.move_due_delayed_jobs() == 1
        job = await paper_queue.pop_ready_generation_job()
        assert job == paper_queue.PaperQueueJob("direct", 11)

    asyncio.run(run())

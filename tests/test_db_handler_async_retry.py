import asyncio
import time

import pytest

from database.db_handler import DBHandler


class _FailingQuery:
    def __init__(self, fail_times=2):
        self.fail_times = fail_times
        self.calls = 0

    def execute(self):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("RemoteProtocolError: simulated")
        return {"ok": True, "calls": self.calls}


@pytest.mark.asyncio
async def test_safe_execute_async_non_blocking_backoff(monkeypatch):
    db = DBHandler()

    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        # Yield control without real waiting to prove cooperative behavior.
        await asyncio.sleep(0)

    monkeypatch.setattr("database.db_handler.asyncio.sleep", fake_sleep)

    ticks = {"count": 0}

    async def ticker():
        for _ in range(5):
            ticks["count"] += 1
            await asyncio.sleep(0)

    q = _FailingQuery(fail_times=2)
    result, _ = await asyncio.gather(db._safe_execute_async(q), ticker())

    assert result["ok"] is True
    assert q.calls == 3
    assert sleep_calls == [1.0, 2.0]
    assert ticks["count"] > 0


def test_safe_execute_sync_compatibility():
    db = DBHandler()
    q = _FailingQuery(fail_times=1)
    started = time.perf_counter()
    result = db._safe_execute(q)
    elapsed = time.perf_counter() - started

    assert result["ok"] is True
    assert q.calls == 2
    assert elapsed >= 1.0

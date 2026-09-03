"""Process lifecycle, drain, and bounded shutdown cleanup."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.lifecycle import (
    ProcessState,
    begin_drain,
    current_state,
    is_accepting_traffic,
    mark_ready,
    mark_stopped,
    reset_lifecycle_for_tests,
)
from app.core.shutdown import shutdown_runtime_resources
from app.main import app_lifespan


def test_starting_is_not_ready() -> None:
    reset_lifecycle_for_tests()
    assert current_state() is ProcessState.STARTING
    assert not is_accepting_traffic()


def test_ready_then_drain_then_stopped() -> None:
    reset_lifecycle_for_tests()
    mark_ready()
    assert current_state() is ProcessState.READY
    assert is_accepting_traffic()
    begin_drain()
    assert current_state() is ProcessState.DRAINING
    assert not is_accepting_traffic()
    mark_stopped()
    assert current_state() is ProcessState.STOPPED
    assert not is_accepting_traffic()


@pytest.mark.asyncio
async def test_lifespan_marks_ready_then_drains_and_cleans_up() -> None:
    reset_lifecycle_for_tests()
    cleaned = False

    async def _cleanup() -> None:
        nonlocal cleaned
        cleaned = True

    with patch("app.main.shutdown_runtime_resources", _cleanup):
        async with app_lifespan(MagicMock()):
            assert current_state() is ProcessState.READY
        assert cleaned
        assert current_state() is ProcessState.STOPPED


@pytest.mark.asyncio
async def test_in_flight_work_can_finish_after_drain_starts() -> None:
    reset_lifecycle_for_tests()
    mark_ready()
    finished = asyncio.Event()

    async def _in_flight() -> None:
        await asyncio.sleep(0.05)
        finished.set()

    task = asyncio.create_task(_in_flight())
    begin_drain()
    assert not is_accepting_traffic()
    await task
    assert finished.is_set()
    assert current_state() is ProcessState.DRAINING


@pytest.mark.asyncio
async def test_resource_shutdown_is_bounded_when_redis_hangs() -> None:
    def _hang() -> None:
        import time

        time.sleep(30)

    engine = MagicMock()
    engine.dispose = AsyncMock(return_value=None)
    with (
        patch("app.core.rate_limit.close_rate_limiter", _hang),
        patch("app.db.session.engine", engine),
    ):
        started = asyncio.get_running_loop().time()
        await shutdown_runtime_resources()
        elapsed = asyncio.get_running_loop().time() - started
    assert elapsed < 8
    engine.dispose.assert_awaited()

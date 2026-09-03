"""Process-local application lifecycle. Not persisted and not a cluster lock."""

from __future__ import annotations

from enum import StrEnum
from threading import Lock

from app.core.metrics import LIFECYCLE_STATE, READINESS


class ProcessState(StrEnum):
    STARTING = "starting"
    READY = "ready"
    DRAINING = "draining"
    STOPPED = "stopped"


_STATE_VALUES = {
    ProcessState.STARTING: 0.0,
    ProcessState.READY: 1.0,
    ProcessState.DRAINING: 2.0,
    ProcessState.STOPPED: 3.0,
}

_lock = Lock()
_state = ProcessState.STARTING


def reset_lifecycle_for_tests() -> None:
    """Return this process to ``starting``. Tests only."""
    _set_state(ProcessState.STARTING)


def current_state() -> ProcessState:
    with _lock:
        return _state


def is_accepting_traffic() -> bool:
    return current_state() is ProcessState.READY


def mark_starting() -> None:
    _set_state(ProcessState.STARTING)


def mark_ready() -> None:
    _set_state(ProcessState.READY)
    READINESS.set(1)


def begin_drain() -> None:
    _set_state(ProcessState.DRAINING)
    READINESS.set(0)


def mark_stopped() -> None:
    _set_state(ProcessState.STOPPED)
    READINESS.set(0)


def _set_state(state: ProcessState) -> None:
    global _state
    with _lock:
        _state = state
    LIFECYCLE_STATE.set(_STATE_VALUES[state])

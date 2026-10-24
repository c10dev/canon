"""작업 취소 신호. 웹 작업(jobs.start)이 스레드마다 Event 를 두고, 화면이 멈추기를 누르면 세운다.
LLM 호출 직전과 작품 저장 직전에 check() 로 확인해, 멈춘 작업이 결과를 저장하지 못하게 한다.
이미 보낸 LLM 호출은 끊을 수 없으므로 그 응답은 버린다. 신호가 없는 곳(CLI, 자동 집필)에서는 아무것도 하지 않는다."""
from __future__ import annotations

import threading
from contextvars import ContextVar


class Cancelled(Exception):
    """사용자가 작업을 멈췄다."""


current: ContextVar[threading.Event | None] = ContextVar("cancel", default=None)


def check() -> None:
    ev = current.get()
    if ev is not None and ev.is_set():
        raise Cancelled("작업을 멈췄어요")

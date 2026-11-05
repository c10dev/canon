"""작업 취소 신호. 웹 작업(jobs.start)이 스레드마다 Event 를 두고, 화면이 멈추기를 누르면 세운다.
LLM 호출 직전과 작품 저장 직전에 check() 로 확인해, 멈춘 작업이 결과를 저장하지 못하게 한다.
이미 보낸 LLM 호출은 대개 끊을 수 없으므로 그 응답은 버린다. Claude 두 백엔드는 기다리는 동안에도 신호를 보고 호출을 끊는다(claude.py). 신호가 없는 곳(CLI, 자동 집필)에서는 아무것도 하지 않는다."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable


class Cancelled(Exception):
    """사용자가 작업을 멈췄다."""


current: ContextVar[threading.Event | None] = ContextVar("cancel", default=None)
# 작업 진행 줄에 잠깐 띄울 글을 받는 곳 (jobs.start 가 Job.retry 에 쓰게 둔다). AI 호출이 요청 한도 · 응답 지연으로
# 기다리거나 다시 부를 때 알린다. 신호가 없는 곳(CLI, 자동 집필)에서는 아무것도 하지 않는다
notice: ContextVar[Callable[[str], None] | None] = ContextVar("notice", default=None)


def say(text: str) -> None:
    """작업 진행 줄에 text 를 띄운다. 빈 글이면 지운다."""
    fn = notice.get()
    if fn is not None:
        fn(text)


def check() -> None:
    ev = current.get()
    if ev is not None and ev.is_set():
        raise Cancelled("작업을 멈췄어요")


def stopped() -> bool:
    """멈추기 신호가 섰는가. check 와 달리 오류를 내지 않는다 (멈춘 뒤 온 응답을 버리지 않고 표시해 남기는 곳이 쓴다)."""
    ev = current.get()
    return ev is not None and ev.is_set()


@contextmanager
def ignored():
    """멈추기 신호를 잠시 보지 않는다. 멈춘 뒤 온 응답을 남기는 곳이 저장(store.save 의 check)을 지나게 쓴다."""
    tok = current.set(None)
    try:
        yield
    finally:
        current.reset(tok)

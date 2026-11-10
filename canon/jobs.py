"""오래 걸리는 AI 작업(설정 제안, 구조 제안, 플롯 초안, 본문, 상태 변경안)을 백그라운드에서 돌린다.

웹 화면은 작업을 시작만 하고 GET /api/jobs 로 진행 상황을 본다. 그동안 다른 화면을 쓸 수 있다.
같은 작품의 같은 작업(같은 화)은 하나만 돌고, 작업 목록은 서버 메모리에만 있어 다시 시작하면 사라진다.

작업이 project.json 을 고치는 동안 화면이 작품 전체를 저장(PUT)하면 작업 결과를 덮을 수 있다.
그래서 작업이 맡은 화(owned)는 작업 중에는 PUT 에서 서버 쪽 내용을 지키고, 끝난 뒤에도 화면이
결과를 받아 갔다고 알려 줄 때까지(최대 OWN_GRACE 초) 지킨다.
"""
from __future__ import annotations

import contextlib
import contextvars
import fcntl
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from . import cancel, store
from .llm import explain_error

KEEP_SECONDS = 600  # 끝난 작업을 목록에 남겨 두는 시간
OWN_GRACE = 30  # 끝난 뒤에도 화면이 새 내용을 받아 갈 때까지 맡은 화를 지키는 시간


@dataclass
class Job:
    id: str
    project: str
    kind: str
    ep: int | None
    label: str
    total: int = 1
    done: int = 0
    note: str = ""
    retry: str = ""  # AI 호출이 기다리거나 다시 부르는 중이면 그 사정 (cancel.say). 다음 호출이 되면 비운다
    retries: dict = field(default_factory=dict)  # 스레드마다의 사정. 함께 부르는 호출(검수 뽑기)이 서로 지우지 않게
    status: str = "running"  # running | done | error | cancelled
    result: Any = None
    error: str = ""
    started: float = field(default_factory=time.time)
    step_at: float = 0  # 지금 단계를 시작한 시각. 0 이면 started. 단계마다 AI 를 부르는 작업(agent.run_turn)이 고친다
    step_wait: float = 0  # 한 단계 AI 호출을 기다리는 초 (agent.step_wait). 0 이면 화면이 기본값을 쓴다
    finished: float | None = None
    owned: set[int] = field(default_factory=set)
    pending: list[int] = field(default_factory=list)  # 맡은 화 중 아직 결과를 쓰지 않은 화 (화면이 그 화만 잠근다)
    released: dict[int, tuple[float, set[int]]] = field(default_factory=dict)  # 단계(done) → (내려놓은 시각, 화). release 참고
    stop: threading.Event = field(default_factory=threading.Event)  # 멈추기 신호 (cancel.current)
    step_ep: int | None = None  # 단계 하나가 마지막으로 끝낸 화. 자동 집필이 화를 반영할 때마다 고친다 (화면이 화마다 알린다)
    target: str = ""  # 같은 종류를 나눠 돌리는 대상 (인물 id 등). 대상이 다르면 함께 돈다
    alive: bool = True  # 스레드가 아직 돈다. 멈춘 작업도 이미 보낸 AI 호출의 응답을 기다리는 동안은 참 (waiting)
    partial: str = ""  # 흘려 받는 중인 AI 글 (본문 쓰기). 저장한 글이 아니다. 작업이 도는 동안만 있고 끝나면 비운다 (set_partial)

    def say(self, text: str) -> None:
        """이 스레드의 AI 호출 사정을 고친다(빈 글이면 지운다). 화면에는 남은 사정 하나를 보인다 (cancel.notice)."""
        key = threading.get_ident()
        if text:
            self.retries[key] = text
        else:
            self.retries.pop(key, None)
        self.retry = next(iter(self.retries.values()), "")

    def set_partial(self, text: str) -> None:
        """흘려 받은 글(지금까지 받은 글 전체)을 고친다. 백엔드의 text_stream 이 조각마다 부른다 (llm.family_text).
        도는 작업만 받는다: 멈춘 뒤 늦게 온 조각이 부분 글을 되살리지 않게 한다. 빈 글이면 지운다."""
        with _lock:
            self.partial = text if self.status == "running" else ""

    def public(self) -> dict:
        return {
            "id": self.id, "project": self.project, "kind": self.kind, "ep": self.ep, "label": self.label,
            "total": self.total, "done": self.done, "note": self.note, "retry": self.retry, "status": self.status,
            "result": self.result, "error": self.error, "started": self.started, "step_at": self.step_at or self.started, "finished": self.finished,
            "step_wait": self.step_wait, "pending": sorted(self.pending), "waiting": self.waiting, "step_ep": self.step_ep,
            "target": self.target, "partial": self.partial if self.status == "running" else "",
        }

    @property
    def waiting(self) -> bool:
        """멈췄지만 이미 보낸 AI 호출의 응답을 아직 기다린다 (호출은 끊을 수 없어 비용이 든다)."""
        return self.status == "cancelled" and self.alive

    def release(self, eps: set[int]) -> None:
        """단계 하나가 eps 화의 결과를 저장했다. 작업이 도는 중에도 그 화는 확정하고 고칠 수 있게 맡은 화에서 뺀다.
        화면이 그 단계 결과를 받아 갔다고 알릴 때까지(merged 의 '<id>:<done>') 저장에서는 OWN_GRACE 초 더 지킨다."""
        self.owned -= eps
        self.pending = [n for n in self.pending if n not in eps]
        self.released[self.done] = (time.time(), set(eps))


class Draining(ValueError):
    """서버가 자동 업데이트로 다시 시작하려고 작업이 끝나기를 기다린다. 새 작업은 받지 않는다 (화면에는 400 으로 보인다)."""

    def __init__(self):
        super().__init__("서버를 곧 다시 시작해요. 잠시 뒤 다시 시도하세요")


class Busy(Exception):
    """같은 작업이 이미 돌고 있다."""

    def __init__(self, job: Job):
        super().__init__(job.label)
        self.job = job


_jobs: dict[str, Job] = {}
# 자동 업데이트가 다시 시작하려고 기다리는 중. 자동 집필은 다음 단계 전에 멈추고(상태는 진행 중으로 둔 채)
# 다시 시작한 서버가 이어 간다 (canon/autorun.py resume_all).
draining = threading.Event()
DRAIN_LIMIT = 1800  # 이 시간(초)을 기다려도 작업이 끝나지 않으면 그대로 다시 시작한다 (canon/web.py _drain)
_lock = threading.Lock()
_project_locks: dict[str, threading.Lock] = {}
EDIT_LOCK = ".edit.lock"  # project_lock 이 작품 폴더에 거는 flock 파일. store.save 의 .lock 과 따로 둬서 같은 스레드가 안에서 저장해도 막히지 않는다
LOCK_WAIT = 30.0  # 다른 프로세스(명령줄 등)가 작품을 고치는 동안 기다리는 상한(초). 넘기면 Locked


class Locked(ValueError):
    """다른 프로세스가 작품을 고치는 중이라 LOCK_WAIT 초를 기다려도 잠금을 잡지 못했다 (화면에는 400 으로 보인다)."""

    def __init__(self):
        super().__init__("다른 프로그램(명령줄 등)이 이 작품을 고치고 있어요. 잠시 뒤 다시 시도하세요")


def _flock(path: str) -> int:
    """path 에 flock 을 건다. 다른 프로세스가 쥐고 있으면 LOCK_WAIT 초까지 기다리고, 넘기면 Locked."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    deadline = time.monotonic() + LOCK_WAIT
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            if time.monotonic() >= deadline:
                os.close(fd)
                raise Locked() from None
            time.sleep(0.05)


@contextlib.contextmanager
def project_lock(name: str) -> Iterator[None]:
    """project.json 을 읽고 고쳐 저장하는 동안 잡는 작품별 잠금. 한 스레드 안에서 다시 잡으면 멈춘다(재진입하지 않는다).
    프로세스 안 잠금을 잡은 뒤 작품 폴더의 EDIT_LOCK 에 flock 을 걸어 명령줄과 웹 서버 사이에서도 잠근다.
    점으로 시작하는 열쇠(revlab.lock_key 등)와 폴더가 없는 작품은 프로세스 안에서만 잠근다."""
    with _lock:
        lock = _project_locks.setdefault(name, threading.Lock())
    with lock:
        d = store.project_dir(name)
        fd = _flock(str(d / EDIT_LOCK)) if not name.startswith(".") and d.is_dir() else None
        try:
            yield
        finally:
            if fd is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)


def _prune() -> None:
    """KEEP_SECONDS 전에 끝난 작업을 목록에서 뺀다. 멈췄지만 아직 AI 응답을 기다리는 작업(waiting)은 남긴다:
    빼면 waiting_on · lingering 이 못 찾아 같은 화의 호출이 겹친다 (Claude · 로컬은 900초까지 기다린다)."""
    now = time.time()
    for jid in [j.id for j in _jobs.values() if j.finished and not j.waiting and now - j.finished > KEEP_SECONDS]:
        del _jobs[jid]


def start(project: str, kind: str, ep: int | None, label: str, fn: Callable[[Job], Any],
          total: int = 1, owned: set[int] | None = None, target: str = "") -> Job:
    """fn(job) 을 스레드에서 돌린다. fn 은 job.done/note 를 갱신할 수 있고, 돌려준 값이 job.result 가 된다.
    다시 시작하려고 기다리는 중(draining)이면 Draining 으로 거절한다. 자동 집필(auto)은 받는다: 첫 단계 전에
    멈추고 다시 시작한 서버가 이어 간다 (autorun.Runner._checkpoint)."""
    if draining.is_set() and kind != "auto":
        raise Draining()
    with _lock:
        _prune()
        for j in _jobs.values():
            if j.status == "running" and (j.project, j.kind, j.ep, j.target) == (project, kind, ep, target):
                raise Busy(j)
        job = Job(id=uuid.uuid4().hex[:12], project=project, kind=kind, ep=ep, label=label,
                  total=total, owned=set(owned or ()), pending=sorted(owned or ()), target=target)
        _jobs[job.id] = job

    def run() -> None:
        store.writer.set("")  # 작업의 저장은 시작한 화면의 저장이 아니다 (다른 화면에 충돌로 보이지 않게)
        cancel.current.set(job.stop)
        cancel.notice.set(job.say)
        try:
            out = fn(job)
            if job.status == "running":
                job.result, job.done, job.status = out, job.total, "done"
            else:  # 멈춘 작업은 끝나도 done 이 되지 않는다. 멈춘 뒤 온 응답을 남긴 작업(revlab.run_write)은 그 결과를 싣는다
                job.result = out
        except cancel.Cancelled:
            job.status, job.error = "cancelled", "멈췄어요"
        except Exception as e:  # 화면에 그대로 보여 준다. 원인을 찾을 수 있게 호출 경로는 서버 로그에 남긴다
            logging.getLogger("canon").exception("작업 %s(%s, %s) 실패", job.kind, job.project, job.id)
            if job.status == "running":
                job.error = explain_error(e)  # 원인과 할 일. 전체 예외는 위 서버 로그에 있다
                job.status = "error"
        finally:
            job.finished = job.finished or time.time()
            job.alive = False
            job.set_partial("")  # 끝나거나 멈추거나 실패하면 흘려 받던 글은 버린다 (저장한 글이 아니다)

    # 사용량 기록이 어느 작품의 어떤 작업인지 알도록 부른 쪽의 컨텍스트(usage.scope)를 스레드에 넘긴다
    ctx = contextvars.copy_context()
    threading.Thread(target=ctx.run, args=(run,), name=f"job-{kind}-{job.id}", daemon=True).start()
    return job


def stop(jid: str) -> Job:
    """작업을 멈춘다. 바로 멈춘 것으로 보이고, 스레드는 다음 LLM 호출이나 저장 전에 그만둔다 (그 사이 결과는 버린다)."""
    job = _jobs.get(jid)
    if job is None:
        raise KeyError(f"작업이 없어요: {jid}")
    if job.status == "running":
        job.stop.set()
        job.status, job.error, job.finished = "cancelled", "멈췄어요", time.time()
        job.set_partial("")
    return job


def lingering(project: str, kind: str, ep: int | None) -> Job | None:
    """같은 작업 가운데 멈췄지만 아직 AI 응답을 기다리는 것 (Job.waiting). 다시 시작하면 호출이 겹친다."""
    return next((j for j in list(_jobs.values()) if j.waiting and (j.project, j.kind, j.ep) == (project, kind, ep)), None)


# 한 화를 두고 AI 를 부르는 작업. 같은 화에서 멈춘 작업이 아직 응답을 기다리면 이 작업은 새로 시작하지 않는다 (waiting_on)
EP_AI_KINDS = frozenset({"board", "check", "cues", "fix_one", "fixes", "plot_one", "recheck", "recheck_one", "state", "write"})


def waiting_on(project: str, ep: int | None) -> Job | None:
    """그 화의 EP_AI_KINDS 작업 가운데 멈췄지만 아직 AI 응답을 기다리는 것. 종류가 달라도 다시 시작하면 호출이 겹친다."""
    if ep is None:
        return None
    return next((j for j in list(_jobs.values())
                 if j.waiting and j.kind in EP_AI_KINDS and (j.project, j.ep) == (project, ep)), None)


def get(jid: str) -> Job | None:
    return _jobs.get(jid)


def listing(project: str | None = None) -> list[Job]:
    with _lock:
        _prune()
        jobs = [j for j in _jobs.values() if project is None or j.project == project]
    return sorted(jobs, key=lambda j: j.started)


def running() -> int:
    """도는 작업 수. 다른 스레드가 작업을 더해도 순회가 깨지지 않게 잠금 안에서 센다."""
    with _lock:
        return sum(1 for j in _jobs.values() if j.status == "running")


def running_owned(project: str) -> set[int]:
    """지금 도는 작업이 맡은 화. 그 화를 확정하면 작업 결과가 확정 화를 덮지 못해 버려진다."""
    return {n for j in list(_jobs.values()) if j.project == project and j.status == "running" for n in j.owned}


def _unmerged(j: Job, merged: set[str], now: float) -> set[int]:
    """작업이 단계마다 내려놓은 화 중 화면이 아직 받아 가지 않은 화. 화면은 '<id>:<done>' 으로 done 단계까지 받았다고 알린다."""
    if j.id in merged:
        return set()
    seen = max((int(t.split(":", 1)[1]) for t in merged if t.startswith(j.id + ":") and t.split(":", 1)[1].isdigit()), default=0)
    return {n for k, (at, eps) in j.released.items() if k > seen and now - at < OWN_GRACE for n in eps}


def owned_episodes(project: str, merged: set[str] = frozenset()) -> set[int]:
    """화면의 저장이 덮으면 안 되는 화. 도는 작업이 맡은 화와, 끝났지만 화면이 아직 받아 가지 않은(merged 에 없는) 작업의 화."""
    now = time.time()
    out: set[int] = set()
    for j in list(_jobs.values()):
        if j.project != project:
            continue
        if j.status == "running" or (j.id not in merged and j.finished and now - j.finished < OWN_GRACE):
            out |= j.owned
        out |= _unmerged(j, merged, now)
    return out

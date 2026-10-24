"""오래 걸리는 AI 작업(설정 제안, 구조 제안, 플롯 초안, 본문, 상태 변경안)을 백그라운드에서 돌린다.

웹 화면은 작업을 시작만 하고 GET /api/jobs 로 진행 상황을 본다. 그동안 다른 화면을 쓸 수 있다.
같은 작품의 같은 작업(같은 화)은 하나만 돌고, 작업 목록은 서버 메모리에만 있어 다시 시작하면 사라진다.

작업이 project.json 을 고치는 동안 화면이 작품 전체를 저장(PUT)하면 작업 결과를 덮을 수 있다.
그래서 작업이 맡은 화(owned)는 작업 중에는 PUT 에서 서버 쪽 내용을 지키고, 끝난 뒤에도 화면이
결과를 받아 갔다고 알려 줄 때까지(최대 OWN_GRACE 초) 지킨다.
"""
from __future__ import annotations

import contextvars
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from . import cancel, store

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
    status: str = "running"  # running | done | error | cancelled
    result: Any = None
    error: str = ""
    started: float = field(default_factory=time.time)
    finished: float | None = None
    owned: set[int] = field(default_factory=set)
    pending: list[int] = field(default_factory=list)  # 맡은 화 중 아직 결과를 쓰지 않은 화 (화면이 그 화만 잠근다)
    released: dict[int, tuple[float, set[int]]] = field(default_factory=dict)  # 단계(done) → (내려놓은 시각, 화). release 참고
    stop: threading.Event = field(default_factory=threading.Event)  # 멈추기 신호 (cancel.current)

    def public(self) -> dict:
        return {
            "id": self.id, "project": self.project, "kind": self.kind, "ep": self.ep, "label": self.label,
            "total": self.total, "done": self.done, "note": self.note, "status": self.status,
            "result": self.result, "error": self.error, "started": self.started, "finished": self.finished,
            "pending": sorted(self.pending),
        }

    def release(self, eps: set[int]) -> None:
        """단계 하나가 eps 화의 결과를 저장했다. 작업이 도는 중에도 그 화는 확정하고 고칠 수 있게 맡은 화에서 뺀다.
        화면이 그 단계 결과를 받아 갔다고 알릴 때까지(merged 의 '<id>:<done>') 저장에서는 OWN_GRACE 초 더 지킨다."""
        self.owned -= eps
        self.pending = [n for n in self.pending if n not in eps]
        self.released[self.done] = (time.time(), set(eps))


class Busy(Exception):
    """같은 작업이 이미 돌고 있다."""

    def __init__(self, job: Job):
        super().__init__(job.label)
        self.job = job


_jobs: dict[str, Job] = {}
# 자동 업데이트가 다시 시작하려고 기다리는 중. 자동 집필은 다음 단계 전에 멈추고(상태는 진행 중으로 둔 채)
# 다시 시작한 서버가 이어 간다 (canon/autorun.py resume_all).
draining = threading.Event()
_lock = threading.Lock()
_project_locks: dict[str, threading.Lock] = {}


def project_lock(name: str) -> threading.Lock:
    """project.json 을 읽고 고쳐 저장하는 동안 잡는 작품별 잠금."""
    with _lock:
        return _project_locks.setdefault(name, threading.Lock())


def _prune() -> None:
    now = time.time()
    for jid in [j.id for j in _jobs.values() if j.finished and now - j.finished > KEEP_SECONDS]:
        del _jobs[jid]


def start(project: str, kind: str, ep: int | None, label: str, fn: Callable[[Job], Any],
          total: int = 1, owned: set[int] | None = None) -> Job:
    """fn(job) 을 스레드에서 돌린다. fn 은 job.done/note 를 갱신할 수 있고, 돌려준 값이 job.result 가 된다."""
    with _lock:
        _prune()
        for j in _jobs.values():
            if j.status == "running" and (j.project, j.kind, j.ep) == (project, kind, ep):
                raise Busy(j)
        job = Job(id=uuid.uuid4().hex[:12], project=project, kind=kind, ep=ep, label=label,
                  total=total, owned=set(owned or ()), pending=sorted(owned or ()))
        _jobs[job.id] = job

    def run() -> None:
        store.writer.set("")  # 작업의 저장은 시작한 화면의 저장이 아니다 (다른 화면에 충돌로 보이지 않게)
        cancel.current.set(job.stop)
        try:
            out = fn(job)
            if job.status == "running":  # 멈춘 작업은 끝나도 결과를 내지 않는다
                job.result, job.done, job.status = out, job.total, "done"
        except cancel.Cancelled:
            job.status, job.error = "cancelled", "멈췄어요"
        except Exception as e:  # 화면에 그대로 보여 준다
            if job.status == "running":
                job.error = getattr(e, "message", None) or str(e) or type(e).__name__
                job.status = "error"
        finally:
            job.finished = job.finished or time.time()

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
    return job


def get(jid: str) -> Job | None:
    return _jobs.get(jid)


def listing(project: str | None = None) -> list[Job]:
    with _lock:
        _prune()
        jobs = [j for j in _jobs.values() if project is None or j.project == project]
    return sorted(jobs, key=lambda j: j.started)


def running() -> int:
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

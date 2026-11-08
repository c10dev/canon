"""자동 집필: 목표 화수까지 본문 → 검수 + 상태 변경안 → 반영 → 다음 화를 반복한다.

화는 앞 화의 상태가 반영돼야 쓸 수 있어 차례로만 진행한다. 한 화 안에서 검수와 상태 변경안은 같은 본문만
보므로 동시에 부른다. 배치(Gemini Batch API)를 켜면 단계마다 배치 작업을 보내고 결과를 기다린다. 비용은
절반이지만 단계마다 몇 분에서 길게는 24시간이 걸릴 수 있다. 끄면 일반 호출이다. 배치가 없는 백엔드(로컬,
mock 제외)는 켜 둬도 일반 호출로 돈다.

사람 승인을 건너뛰는 대신 정책(Policy)에 걸리면 그 화에서 멈추고 변경안을 검토 대기(pending)로 둔다.
자동으로 반영한 화는 Episode.auto 로 표시하고, 화마다 스냅샷이 남아 pipeline.revert 로 되돌릴 수 있다.

진행 상태와 로그는 projects/<이름>/autorun.json 에 따로 둔다 (project.json 저장과 부딪치지 않게).
서버가 다시 시작돼도 진행 중이던 실행은 이어서 돌고, 기다리던 배치 작업에는 다시 붙는다.
도는 실행은 작품 폴더의 .autorun.lock 에 flock 을 쥔다. 명령줄과 웹 서버가 같은 작품을 함께 돌리지 않게 하고,
다른 프로세스가 쥔 실행에 보내는 일시정지 · 중지는 autorun.want 파일로 넘긴다.
"""
from __future__ import annotations

import fcntl
import logging
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, Field

from . import anchor, atlas, board, cue, dynamics, features, findings, jobs, pipeline, prompts, settings, store, timeline, usage
from . import stage as stage_mod
from .llm import BatchLLM, Interrupted, SchemaMismatch, get_llm
from .research import JSON_OUTPUT_RESERVE, _filler
from .schema import ConsistencyReport, Project, RewriteRequest, StateDelta, TextVersion

_log = logging.getLogger("canon")

LOG_KEEP = 500
STEP_NAMES = {"board": "스토리보드", "write": "본문", "revise": "서술 다듬기", "check": "검수", "state": "상태 변경안"}
# 루프 단계(Run.step) 이름: 서버 재시작 뒤 어느 단계를 다시 하는지 알릴 때
RUN_STEPS = {"board": "스토리보드 만들기", "cues": "큐 시트 만들기", "write": "본문 쓰기", "polish": "서술 다듬기", "review": "검수와 상태 변경안 만들기", "confirm": "플롯 확정"}
# 지울 수 있는 인물 상태 칸 이름 (CharacterState.cleared, Policy.stop_on_clear 의 멈춘 이유)
CLEAR_NAMES = {"current_goal": "목표", "location": "위치", "notes": "메모", "attire": "차림", "emotional_state": "감정"}
# 화 상태 이름 (화면 STATUS 와 같은 말)
EP_STATUS = {"draft": "초안", "confirmed": "확정", "written": "작성됨", "finalized": "반영 완료"}
# 측정값이 없을 때 쓰는 단계별 소요 시간 추정 (초, 일반 호출)
SECONDS = {"board": 90.0, "write": 90.0, "revise": 90.0, "check": 40.0, "state": 40.0}
# 스토리보드 추정: 출력 토큰, 쓰기 프롬프트에 붙는 블록 글자 수 (손으로 채운 스토리보드 예시에서 잰 어림, DESIGN.md)
BOARD_OUT, BOARD_CHARS = 3500, 3500
# 큐 시트 추정: 출력 토큰, 쓰기 프롬프트에 붙는 블록 글자 수 (11화 실측: 출력 1,524토큰, 쓰기 입력 +1,375토큰, DESIGN.md)
CUE_OUT, CUE_CHARS = 1600, 2400
# 배치 한 번 기다리는 시간 가정 (초): 보통 범위. 최악은 24시간
BATCH_WAIT = (3 * 60.0, 60 * 60.0)

RunStatus = Literal["running", "paused", "review", "stopped", "done", "error"]


class Policy(BaseModel):
    """사람 검토 없이 반영할지 정하는 기준. 하나라도 걸리면 그 화에서 멈춘다."""
    check: bool = Field(True, description="화마다 검수를 돌린다")
    max_issues: int = Field(0, description="검수에서 나온 어긋남이 이 개수를 넘으면 멈춤")
    ignore_minor: bool = Field(False, description="어긋남 개수를 셀 때 심각도 '사소'는 세지 않음")
    stop_on_critical: bool = Field(True, description="심각도 '치명'인 어긋남이 하나라도 있으면 멈춤 (max_issues 와 상관없이)")
    max_shift: float = Field(0.3, description="한 인물이 다른 인물을 보는 온기나 신뢰가 한 화에 이만큼 넘게 바뀌면 멈춤. 0 이면 보지 않음")
    stop_on_stage: bool = Field(False, description="관계 단계(호감 → 균열 등)가 바뀌면 멈춤")
    stop_on_warnings: bool = Field(False, description="상태 변경안에 경고(플롯 누락, 설정 위반)가 있으면 멈춤")
    confirm_plots: bool = Field(False, description="초안 플롯을 만나면 자동으로 확정하고 쓴다. 끄면 그 화에서 멈춤")
    review_every: int = Field(0, description="이번 실행에서 N화를 반영할 때마다 멈춤. 0 이면 멈추지 않음")
    hand_pick_opening: bool = Field(True, description="1~3화는 쓰고 검수한 뒤 반영하기 전에 멈춤. 독자가 계속 읽을지 정하는 화라 작가가 읽고 고른다")
    storyboard: bool = Field(True, description="화마다 쓰기 전에 스토리보드를 만들어 쓴다 (작품이 스토리보드를 쓸 때만, board.on)")
    stop_on_board_warnings: bool = Field(True, description="AI 가 만든 스토리보드에 이번 화 플롯과 어긋남(plot_vs_state · plot_vs_text · time)이나 "
                                         "값 범위 경고가 있으면 멈춤. 다음 화 플롯 경고는 기록만. 작가가 고친 스토리보드로는 멈추지 않는다")
    cue_sheet: bool = Field(True, description="화마다 쓰기 전에 큐 시트를 만들어 쓴다 (작품이 큐 시트를 쓸 때만, cue.on)")
    polish: bool = Field(False, description="화마다 본문을 쓴 뒤 서술 문장만 다듬은 판으로 바꾼다 (revise 단계 모델, pipeline.polish_episode). "
                         "쓴 판은 이전 판으로 남는다. 다듬기가 대사 줄을 바꿔 멈추면 쓴 글로 이어 간다. 검수와 상태 변경안은 다듬은 글을 본다")
    max_style_distance: float = Field(0, description="작품 정착 문체에서 최근 화 평균 문체 거리(anchor.rolling)가 이만큼 넘으면 멈춤. "
                                     "0 이면 보지 않음. 정착 문체가 없으면 보지 않음")
    # 아래 칸은 모두 기본으로 꺼 둔다 (켜기 전 동작과 같게). 기본값을 조이는 것은 작가와 정한다
    stop_on_new_characters: bool = Field(False, description="상태 변경안에 새 인물(new_characters)이 있으면 멈춤. 이미 있는 인물 id 는 세지 않음")
    stop_on_secrets: bool = Field(False, description="상태 변경안에 새 비밀(secrets_added)이 있으면 멈춤. 이미 있거나 겹친 비밀 id, 설정에 없는 인물의 비밀은 세지 않음")
    stop_on_resolve: bool = Field(False, description="상태 변경안이 열린 복선을 하나라도 회수하면 멈춤")
    stop_on_early_resolve: bool = Field(False, description="회수 예정 화(due_ep)보다 일찍 회수하거나 범위가 부 · 작품 전체(part · series)인 복선을 회수하면 멈춤")
    stop_on_deadline_done: bool = Field(False, description="상태 변경안이 열린 기한을 닫으면(deadlines_done) 멈춤")
    max_time_jump_days: int = Field(0, description="작품 속 시간이 직전 화 끝보다 이 날수를 넘게 앞으로 가면 멈춤. 0 이면 보지 않음. 어느 쪽 날수든 모르면 보지 않음")
    stop_on_clear: bool = Field(False, description="상태 변경안이 인물 상태 칸을 지우면(CharacterState.cleared) 멈춤")


class LogEntry(BaseModel):
    at: str
    ep: Optional[int] = None
    step: str = ""
    level: Literal["info", "warn", "error"] = "info"
    message: str
    tokens_in: int = 0
    tokens_out: int = 0
    calls: int = Field(1, description="이 단계에서 부른 LLM 호출 수. tokens_out 은 그 합이다 (추정은 호출 하나의 평균으로 나눠 쓴다)")
    seconds: float = 0.0
    batch: bool = False


class Run(BaseModel):
    target: int
    batch: bool = False
    policy: Policy = Field(default_factory=Policy)
    status: RunStatus = "running"
    ep: Optional[int] = None
    step: str = ""
    reasons: list[str] = Field(default_factory=list, description="멈춘 이유")
    halt: str = Field("", description="멈춘 종류. 화면이 고칠 곳으로 가는 버튼을 고른다: "
                      "plot_missing | plot_draft | board | board_stale | review | every | changed | reverted | schema | cut | error")
    restarts: int = Field(0, description="서버가 다시 시작돼 이어 간 횟수 (그때 하던 단계는 처음부터 다시 한다)")
    pending: Optional[StateDelta] = Field(None, description="검토 대기 중인 변경안")
    pending_text: str = Field("", description="검토 대기 변경안을 만든 본문. 그 뒤 본문을 고쳤으면 그대로 반영하지 않는다")
    batches: dict[str, str] = Field(default_factory=dict, description="기다리는 배치 작업 slot -> 이름")
    batch_keys: dict[str, str] = Field(default_factory=dict, description="기다리는 배치 작업 slot -> 보낸 프롬프트 지문. "
                                       "이어 갈 때 프롬프트가 달라졌으면 (멈춘 사이 본문 · 플롯을 고침) 그 배치는 취소하고 다시 보낸다")
    applied: list[int] = Field(default_factory=list, description="이번 실행에서 자동 반영한 화")
    polish_due: list[int] = Field(default_factory=list, description="이번 실행이 쓰고 아직 다듬지 않은 화 (Policy.polish). "
                                  "서버가 다시 시작해도 이어서 다듬는다. 작가가 쓴 본문은 넣지 않는다")
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    started: str = ""
    updated: str = ""
    log: list[LogEntry] = Field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- 저장 ----------

def _path(name: str):
    return store.project_dir(name) / "autorun.json"


def load_run(name: str) -> Optional[Run]:
    path = _path(name)
    if not path.exists():
        return None
    try:
        return Run.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _write(name: str, run: Run) -> None:
    run.updated = _now()
    path = _path(name)
    store.write_atomic(path, run.model_dump_json(indent=2))  # tmp 이름에 프로세스 · 스레드가 들어가 autorun.want 의 tmp 와 겹치지 않는다


# ---------- 실행 주인 (프로세스 사이) ----------

OWNER_FILE = ".autorun.lock"  # 도는 실행이 flock 을 쥔다. 프로세스가 죽으면 OS 가 푼다
WANT_FILE = "autorun.want"  # 다른 프로세스가 쥔 실행에 보내는 요청 (pause | stop)
ELSEWHERE = "다른 곳(명령줄 canon auto 나 다른 서버)에서 이 작품의 자동 집필이 돌고 있어요. 그곳에서 멈춘 뒤 다시 하세요"
STARTING = "이 서버에서 이 작품의 자동 집필을 이미 시작하고 있어요. 잠시 뒤에 다시 보세요"


def _take(name: str) -> Optional[int]:
    """이 프로세스가 실행 주인이 된다. 잠금 파일의 fd 를 돌려주고, 다른 프로세스가 쥐고 있으면 None."""
    d = store.project_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    fd = os.open(d / OWNER_FILE, os.O_RDWR | os.O_CREAT, 0o644)
    for _ in range(5):  # elsewhere() 가 잠깐 잡아 보는 동안이면 기다렸다 다시 잡는다
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            time.sleep(0.05)
            continue
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()} {socket.gethostname()} {_now()}\n".encode())
        (d / WANT_FILE).unlink(missing_ok=True)  # 지난 실행에 남은 요청은 버린다
        return fd
    os.close(fd)
    return None


def elsewhere(name: str) -> bool:
    """다른 프로세스가 이 작품의 자동 집필을 돌리는가 (잠금 파일을 쥔 프로세스가 있는데 이 프로세스의 실행이 아니다)."""
    with _lock:
        if name in _taking:  # 이 프로세스의 _control 이 잠금 파일을 잡는 중이다 (Control 등록 전)
            return False
        ctl = _controls.get(name)
    if ctl and ctl.owner is not None:
        return False
    path = store.project_dir(name) / OWNER_FILE
    if not path.exists():
        return False
    fd = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)


def _ask(name: str, what: str) -> None:
    """다른 프로세스가 쥔 실행에 일시정지 · 중지를 청한다. 중지를 청했으면 일시정지로 낮추지 않는다."""
    path = store.project_dir(name) / WANT_FILE
    try:
        if path.read_text(encoding="utf-8").strip() == "stop":
            return
    except OSError:
        pass
    store.write_atomic(path, what)  # tmp 이름이 주인의 _write · 다른 요청과 겹치지 않는다


# ---------- 실행 제어 (프로세스 안) ----------

class Control:
    def __init__(self, name: str, run: Run):
        self.name, self.run = name, run
        self.lock = threading.RLock()
        self.want = ""  # "" | pause | stop
        self.wake = threading.Event()
        self.thread_alive = False
        self.owner: Optional[int] = None  # 쥔 잠금 파일의 fd (_take)

    def release(self) -> None:
        """실행 주인 잠금을 푼다. 여러 번 불러도 된다."""
        fd, self.owner = self.owner, None
        if fd is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def poll_want(self) -> None:
        """다른 프로세스가 남긴 요청(autorun.want)을 읽어 want 에 둔다."""
        path = store.project_dir(self.name) / WANT_FILE
        try:
            what = path.read_text(encoding="utf-8").strip()
        except OSError:
            return
        path.unlink(missing_ok=True)
        if what in ("pause", "stop") and self.want != "stop":
            self.want = what

    def save(self) -> None:
        with self.lock:
            _write(self.name, self.run)

    def wait(self, seconds: float) -> str:
        """배치 결과를 기다린다. 멈추라는 요청이 오면 바로 깬다."""
        self.wake.wait(seconds)
        self.wake.clear()
        self.poll_want()
        if self.want:
            return self.want
        return "pause" if jobs.draining.is_set() else ""


_controls: dict[str, Control] = {}
_taking: set[str] = set()  # 이 프로세스에서 시작 · 이어 가기가 잠금 파일을 잡는 중인 작품 (_control)
_lock = threading.Lock()


def get_run(name: str) -> Optional[Run]:
    with _lock:
        ctl = _controls.get(name)
    # 끝난 실행의 메모리 값은 다른 프로세스가 그 뒤에 이어 간 기록보다 오래됐을 수 있어 파일을 읽는다
    return ctl.run if ctl and ctl.thread_alive else load_run(name)


def wanted(name: str) -> str:
    """도는 실행에 받아 둔 요청(pause | stop). 지금 단계가 끝나야 멈추므로 화면이 '멈추는 중'을 보인다. 없으면 빈 글.
    다른 프로세스가 쥔 실행이면 그 주인이 아직 읽지 않은 요청 파일(autorun.want)을 본다."""
    with _lock:
        ctl = _controls.get(name)
    if ctl and ctl.thread_alive:
        return ctl.want
    if not elsewhere(name):
        return ""
    try:
        what = (store.project_dir(name) / WANT_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return what if what in ("pause", "stop") else ""


def active(name: str) -> bool:
    """자동 집필이 이 작품을 고치고 있는가 (화면 저장이 진행 상태를 덮으면 안 되는 동안). 다른 프로세스의 실행도 본다."""
    with _lock:
        ctl = _controls.get(name)
    return bool(ctl and ctl.thread_alive) or elsewhere(name)


# ---------- 승인 정책 ----------

def _names(p: Project) -> dict[str, str]:
    return {c.id: c.name or c.id for c in p.characters}


def review_reasons(p: Project, delta: StateDelta, report: Optional[ConsistencyReport], policy: Policy) -> list[str]:
    """정책에 걸린 이유. 빈 목록이면 자동으로 반영해도 된다. p 는 반영 전 상태이고 바꾸지 않는다."""
    out: list[str] = []
    # 작가가 그대로 둠 · 잘못 짚음으로 정해 둔 지적은 다시 나와도 세지 않는다
    ep = p.episode(delta.episode)
    all_issues = findings.counted(ep, report.issues) if report is not None else []
    issues = findings.counted(ep, report.issues, policy.ignore_minor) if report is not None else []
    if len(issues) > policy.max_issues:
        kinds = ", ".join(sorted({i.type for i in issues}))
        out.append(f"검수에서 어긋난 곳 {len(issues)}개 ({kinds}){' · 사소한 것은 세지 않았어요' if policy.ignore_minor else ''}")
    crit = [i for i in all_issues if i.severity == "crit"]
    if policy.stop_on_critical and crit and len(issues) <= policy.max_issues:  # 개수로 이미 멈추면 한 번만 적는다
        out.append(f"검수에서 치명적인 어긋남 {len(crit)}개: {crit[0].description}")
    if policy.hand_pick_opening and prompts.is_opening(delta.episode):
        out.append(f"{delta.episode}화는 초반 화라 직접 읽고 반영하도록 멈춰요 (집필 화면에서 초반 점검과 여는 방식 비교를 쓸 수 있어요)")
    if policy.stop_on_warnings and delta.warnings:
        out.append(f"상태 변경안 경고 {len(delta.warnings)}개: {delta.warnings[0]}")
    if policy.max_style_distance > 0 and not anchor.voiced(p, delta.episode):
        r = anchor.rolling(p, delta.episode)
        if r is not None and r > policy.max_style_distance:
            out.append(f"정착 문체에서 멀어졌어요: 최근 {anchor.WINDOW}화 평균 문체 거리 {r} (멈춤 기준 {policy.max_style_distance})")
    names = _names(p)
    unknown = sorted({u.character_id for u in delta.character_updates if u.character_id not in names})
    if unknown:
        out.append(f"설정에 없는 인물의 상태가 나왔어요: {', '.join(unknown)}")
    if policy.max_shift > 0 or policy.stop_on_stage:
        # 실제 반영(put)처럼 hold 로 뺀 제안은 빼고 흉내 낸다. apply_delta 가 여러 칸을 고쳐 작품 전체를 복사한다
        sim, sd = p.model_copy(deep=True), delta.model_copy(deep=True)
        features.hold(sim, sd)
        pipeline.apply_delta(sim, sd)
        big: list[tuple[float, str]] = []
        stages: list[str] = []
        for t in sim.ties:
            b = dynamics.find_tie(p.ties, t.source, t.target)
            if b is None:
                continue
            who = f"{names.get(t.source, t.source)}→{names.get(t.target, t.target)}"
            dw, dt = t.warmth - b.warmth, t.trust - b.trust
            if policy.max_shift > 0 and max(abs(dw), abs(dt)) > policy.max_shift:
                big.append((max(abs(dw), abs(dt)), f"{who} 온기 {dw:+.2f}, 신뢰 {dt:+.2f}"))
            if policy.stop_on_stage and t.stage != b.stage:
                stages.append(f"{who} {b.stage}→{t.stage}")
        if big:
            out.append("관계가 크게 움직였어요: " + "; ".join(s for _, s in sorted(big, reverse=True)[:3]))
        if stages:
            out.append("관계 단계가 바뀌었어요: " + ", ".join(stages[:3]))
    out += _story_reasons(p, delta, policy, names)
    return out


def _story_reasons(p: Project, delta: StateDelta, policy: Policy, names: dict[str, str]) -> list[str]:
    """새 인물 · 비밀 · 복선 회수 · 기한 닫힘 · 시간 건너뜀 · 지운 칸 정책. 모두 기본으로 꺼져 있다."""
    out: list[str] = []
    n = delta.episode
    # 반영(pipeline.apply_delta)이 더하지 않고 빼는 항목은 세지 않는다: 이미 있는 인물 id, 이미 있거나 같은 변경안에서 겹친 비밀 id, 설정에 없는 인물의 비밀
    fresh = [c for c in delta.new_characters if c.id not in names]
    if policy.stop_on_new_characters and fresh:
        who = ", ".join(c.name or c.id for c in fresh[:3])
        out.append(f"새 인물 {len(fresh)}명이 나왔어요: {who}")
    owners = set(names) | {c.id for c in fresh}
    seen = {s.id for s in p.secrets}
    secrets = [s for s in delta.secrets_added if s.owner in owners and s.id not in seen and not seen.add(s.id)]
    if policy.stop_on_secrets and secrets:
        out.append(f"새 비밀 {len(secrets)}개가 생겼어요: {secrets[0].content}")
    if policy.stop_on_resolve or policy.stop_on_early_resolve:
        fs = {f.id: f for f in p.foreshadows if f.status == "open"}
        hits: list[str] = []
        for fid in delta.foreshadow_resolved:
            f = fs.get(fid)
            if f is None:  # 없는 복선은 반영할 때 버린다 (pipeline.drop_invalid)
                continue
            why = []
            if f.due_ep and n < f.due_ep:
                why.append(f"예정 {f.due_ep}화보다 일찍")
            if f.scope != "arc":
                why.append("부 범위" if f.scope == "part" else "작품 전체 범위")
            if policy.stop_on_resolve or why:
                hits.append(f.description + (f" ({', '.join(why)})" if why else ""))
        if hits:
            out.append(f"복선 {len(hits)}개를 회수했어요: " + "; ".join(hits[:3]))
    if policy.stop_on_deadline_done and delta.deadlines_done:
        dl = {d.id: d for d in p.timeline.deadlines if not d.done_ep}
        done = [dl[i].what or i for i in delta.deadlines_done if i in dl]
        if done:
            out.append(f"기한 {len(done)}개가 닫혔어요: " + ", ".join(done[:3]))
    if policy.max_time_jump_days > 0 and timeline.enabled(p) and delta.time.day > 0:
        cur = timeline.current_day(p, n)
        if cur > 0 and delta.time.day - cur > policy.max_time_jump_days:
            out.append(f"작품 속 시간이 {delta.time.day - cur}일 건너뛰었어요: {cur}일째 → {delta.time.day}일째 (멈춤 기준 {policy.max_time_jump_days}일)")
    if policy.stop_on_clear:
        cleared = [f"{names.get(u.character_id, u.character_id)} {', '.join(CLEAR_NAMES.get(x, x) for x in u.cleared)}"
                   for u in delta.character_updates if u.cleared]
        if cleared:
            out.append("지운 상태 칸이 있어요: " + "; ".join(cleared[:3]))
    return out


# ---------- 비용과 시간 추정 ----------

def stage_cost(stage: str, tin: float, tout: float, batch: bool) -> Optional[float]:
    """단계가 쓰는 모델로 tin/tout 토큰을 쓸 때의 USD. 가격은 사용량 화면과 같은 가격표(usage.prices)를 쓴다.
    로컬은 0원, 가격표에 없는 Gemini 모델이면 None."""
    prov = settings.stage_provider(stage)[0]
    return usage.stage_cost(prov, gemini_model(stage), tin, tout, batch and prov == "gemini" and batchable(stage))


def gemini_model(stage: str) -> str:
    """단계가 쓰는 Gemini 모델. 단계별 모델이 없으면 전체 모델."""
    return settings.stage_model(stage)[0] or settings.model()[0]


def batchable(stage: str) -> bool:
    prov = settings.stage_provider(stage)[0]
    # Vertex AI 배치는 Cloud Storage 를 거쳐야 해서 지원하지 않는다 (llm.GeminiLLM.can_batch)
    return prov == "mock" or (prov == "gemini" and settings.gemini_auth()[0] != "vertex")


def _todo(p: Project, target: int) -> list[int]:
    have = {e.plot.number: e.status for e in p.episodes}
    return [n for n in range(1, target + 1) if have.get(n) != "finalized"]


def _measured(name: str | None) -> dict[str, dict[str, float]]:
    """지난 실행 로그에서 단계별 평균 출력 토큰과 걸린 시간 (일반/배치 따로)."""
    run = load_run(name) if name else None
    acc: dict[str, list[LogEntry]] = {}
    for e in (run.log if run else []):
        step = "board" if e.step == "plan" else e.step  # 옛 실행 로그는 스토리보드 단계를 plan 으로 적었다
        if step in SECONDS and e.seconds and e.level == "info":
            acc.setdefault(step + (":batch" if e.batch else ""), []).append(e)
    # tokens_out 은 단계 안 모든 호출의 합이라 호출 수로 나눠 호출 하나의 평균을 낸다 (estimate 가 호출마다 더한다)
    return {k: {"out": sum(x.tokens_out for x in v) / max(1, sum(x.calls for x in v)), "seconds": sum(x.seconds for x in v) / len(v)}
            for k, v in acc.items()}


def estimate(p: Project, target: int, batch: bool, policy: Policy, name: str | None = None) -> dict:
    """남은 화를 끝까지 쓸 때의 토큰, 비용, 시간 추정. 아직 안 쓴 화는 목표 분량으로 쓰였다고 가정한다."""
    todo = _todo(p, target)
    have = {e.plot.number: e for e in p.episodes}
    sim = p.model_copy(deep=True)
    for e in sim.episodes:
        if not e.text:
            e.text = _filler(p, p.meta.words_per_episode)
    measured = _measured(name)
    steps = {"board": 0, "write": 0, "revise": 0, "check": 0, "state": 0}
    # 단계 백엔드 · 모델마다 글자 → 토큰 직선이 다르다 (Claude 는 Gemini 보다 글자당 토큰이 많다, usage.token_rate)
    rates = {s: usage.stage_rate(s) for s in steps}
    write_out = usage.est_output(p.meta.words_per_episode, rates["write"])
    revise_out = usage.est_output(p.meta.words_per_episode, rates["revise"])
    boards = policy.storyboard and board.on(p)
    cues = policy.cue_sheet and cue.on(p)
    tokens = {s: [0.0, 0.0] for s in steps}
    missing = []
    stage_waves = 0
    for n in todo:
        e = have.get(n)
        if e is None:
            missing.append(n)
            continue
        calls = [("state", prompts.SYSTEM_EDITOR, prompts.state_prompt(sim, n), JSON_OUTPUT_RESERVE)]
        if policy.check:
            calls.append(("check", prompts.SYSTEM_CHECKER, prompts.check_prompt(sim, n, sized=True), JSON_OUTPUT_RESERVE))
            if sim.serial and sim.settings.check_widen:  # 검수 넓히기: 진술 뽑기 + 다시 묻기 (근거는 진술마다 다 찬다고 본다)
                calls.append(("check", prompts.SYSTEM_CLAIMS, prompts.claims_prompt(sim, n), JSON_OUTPUT_RESERVE))
                calls.append(("check", prompts.SYSTEM_CHECKER, prompts.widen_prompt(sim, n, [], []) + " " * (
                    prompts.WIDEN_MAX * prompts.TWOSTEP_EVIDENCE), JSON_OUTPUT_RESERVE))
            if sim.settings.check_motion:  # 동선 따로 보기: 본 검수와 동시에 부르므로 시간은 늘지 않는다
                calls.append(("check", prompts.SYSTEM_MOTION, prompts.motion_prompt(sim, n), JSON_OUTPUT_RESERVE))
            if sim.settings.stage_extract:  # 검수 때 함께 뽑기: 계획 장면이 있는 사건마다 본문 장면 뽑기 (본문이 새로 쓰이므로 모두 돈다)
                planned = [i for i in range(len(e.plot.events)) if stage_mod.scenes_of(e, i)[0] is not None]
                for i in planned:
                    calls.append(("check", prompts.SYSTEM_STAGE, prompts.stage_extract_prompt(sim, n, i), JSON_OUTPUT_RESERVE))
                stage_waves += -(-len(planned) // pipeline.STAGE_EXTRACT_WORKERS)
        if e.status in ("draft", "confirmed"):
            made = boards and e.storyboard is None
            if made:  # 스토리보드 만들기 한 번 + 쓰기 프롬프트에 들어갈 스토리보드 블록
                calls.append(("board", prompts.SYSTEM_PLANNER, prompts.storyboard_prompt(sim, n), BOARD_OUT))
            sheet = cues and e.cue_sheet is None
            if sheet:  # 큐 시트 만들기 한 번 (방금 만든 스토리보드가 있으면 그 요청 글 + 스토리보드 블록이 앞에 온다) + 쓰기 프롬프트 끝에 붙는 큐 시트 블록
                lead = prompts.storyboard_prompt(sim, n) if made else ""
                calls.append(("board", prompts.SYSTEM_PLANNER, prompts.cue_sheet_prompt(sim, n, lead=lead) + " " * (BOARD_CHARS if made else 0), CUE_OUT))
            calls.append(("write", prompts.writer_system(sim), prompts.episode_prompt(sim, n)
                          + " " * ((BOARD_CHARS if made else 0) + (CUE_CHARS if sheet else 0)), write_out))
            if policy.polish:  # 서술 다듬기 한 번: 작품 고정 블록 + 쓴 본문(목표 분량) + 규칙, 본문 전체를 다시 낸다
                calls.append(("revise", prompts.writer_system(sim), prompts.polish_prompt(sim, n, sim.episode(n).text), revise_out))
        for step, system, text, out in calls:
            m = measured.get(step + (":batch" if batch and batchable(step) else "")) or measured.get(step)
            steps[step] += 1
            tokens[step][0] += usage.est_input(len(text), rates[step], len(system))
            tokens[step][1] += m["out"] if m and m["out"] else out
    cost: Optional[float] = 0.0
    unpriced = []
    for step, (tin, tout) in tokens.items():
        c = stage_cost(step, tin, tout, batch and step != "board")
        if c is None:
            unpriced.append(gemini_model(step))
        elif cost is not None:
            cost += c
    if unpriced:
        cost = None
    eps = len(todo) - len(missing)

    def secs(step: str) -> float:
        if batch and batchable(step) and step != "board":
            return 0.0  # 배치 대기는 rounds 로 따로 센다
        m = measured.get(step)
        return m["seconds"] if m else SECONDS[step]

    review = [s for s in ("check", "state") if steps[s]]
    # 검수 넓히기는 검수 뒤에 진술 뽑기 · 다시 묻기를 차례로 부른다 (화마다 검수 호출 3번)
    widen = 3 if policy.check and p.serial and p.settings.check_widen else 1
    eps_n = len(todo) - len(missing)
    widen += stage_waves / eps_n if eps_n else 0  # 장면 뽑기도 검수 뒤에 부른다 (동시 호출 수만큼 묶어 한 차례)
    slow = widen if "check" not in measured else 1  # 잰 검수 시간은 넓히기까지 든 시간이다
    # 일반 호출: 본문 + (동시에 부르는 검수와 상태 변경안 중 긴 쪽)
    normal = steps["board"] * secs("board") + steps["write"] * secs("write") + steps["revise"] * secs("revise") + eps * max((secs(s) * (slow if s == "check" else 1) for s in review), default=0.0)
    # 배치: 본문 한 번, 검수 + 상태 변경안 한 번을 기다린다 (넓히기를 켜면 검수 배치를 두 번 더 기다린다)
    rounds = ((steps["write"] if batchable("write") else 0) + (steps["revise"] if batchable("revise") else 0)
              + (eps if any(batchable(s) for s in review) else 0)
              + (eps * (widen - 1) if "check" in review and batchable("check") else 0)) if batch else 0
    waits = [v["seconds"] for k, v in measured.items() if k.endswith(":batch")]
    return {
        "episodes": eps, "from": todo[0] if todo else None, "to": target, "missing": missing,
        # 초안 플롯 자동 확정이 꺼져 있으면 그 화에서 멈춘다. 첫 화부터 초안이면 곧바로 멈춘다
        "drafts": [] if policy.confirm_plots else [n for n in todo if n in have and have[n].status == "draft"],
        "calls": steps, "tokens_in": round(sum(t[0] for t in tokens.values())),
        "tokens_out": round(sum(t[1] for t in tokens.values())),
        "cost": round(cost, 2) if cost is not None else None, "batch": batch,
        "batch_rounds": rounds, "seconds_min": round(normal + rounds * BATCH_WAIT[0]),
        "seconds_max": round(normal + rounds * BATCH_WAIT[1]), "seconds_worst": round(normal + rounds * 86400),
        "batch_avg_seconds": round(sum(waits) / len(waits)) if waits else None,
        "measured": bool(measured), "model": gemini_model("write"), "unpriced": sorted(set(unpriced)),
        "stages": {s: settings.stage_provider(s)[0] for s in steps},
        "token_rates": {s: r._asdict() for s, r in rates.items()},
    }


# ---------- 실행 ----------

class _Halt(Exception):
    """루프를 끝낸다. status 가 None 이면 상태를 바꾸지 않고(서버 재시작 대기) 나간다."""

    def __init__(self, status: Optional[str], message: str = "", reasons: list[str] | None = None, kind: str = ""):
        super().__init__(message)
        self.status, self.message, self.reasons, self.kind = status, message, reasons or [], kind


def _edit(name: str, fn: Callable[[Project], Any]) -> Project:
    with jobs.project_lock(name):
        p = store.load(name)
        fn(p)
        store.save(name, p)
    return p


class Runner:
    def __init__(self, ctl: Control, job: Optional[jobs.Job] = None, echo: Callable[[str], None] | None = None):
        self.ctl, self.name, self.job, self.echo = ctl, ctl.name, job, echo
        self.no_cues: set[int] = set()  # 낡은 큐 시트를 다시 받았는데 비어 온 화: 낡은 시트를 넣지 않고 쓴다 (_cues, _write)
        self.board_lead: tuple[int, str, list[str]] | None = None  # 방금 만든 스토리보드 (화, made_at, 보낸 요청 글). _cues 가 앞에 둔다

    @property
    def run(self) -> Run:
        return self.ctl.run

    def log(self, message: str, level: str = "info", step: str | None = None, **kw: Any) -> None:
        with self.ctl.lock:
            self.run.log.append(LogEntry(at=_now(), ep=self.run.ep, step=step or self.run.step, level=level,
                                         message=message, **kw))  # type: ignore[arg-type]
            self.run.log = self.run.log[-LOG_KEEP:]
            self.ctl.save()
        if self.echo:
            self.echo(f"[{self.run.ep or '-'}화] {message}")
        if self.job is not None:
            self.job.note = message

    def _set(self, ep: Optional[int], step: str) -> None:
        with self.ctl.lock:
            self.run.ep, self.run.step = ep, step
            self.ctl.save()

    def _checkpoint(self) -> None:
        self.ctl.poll_want()
        if self.ctl.want == "stop":
            raise _Halt("stopped", "중지했어요")
        if self.ctl.want == "pause":
            raise _Halt("paused", "일시정지했어요")
        if jobs.draining.is_set():
            raise _Halt(None, "서버를 다시 시작한 뒤 이어 가요")

    def call(self, stage: str, n: int, fn: Callable[[Any], Any]) -> tuple[Any, dict]:
        """stage 의 백엔드로 fn(llm) 을 부르고 (결과, 토큰과 시간) 을 돌려준다. 배치가 켜져 있으면 배치로."""
        with usage.scope(project=self.name, episode=n, source="autorun", task="auto"):
            return self._call(stage, n, fn)

    def _call(self, stage: str, n: int, fn: Callable[[Any], Any]) -> tuple[Any, dict]:
        llm = get_llm(stage)
        # 스토리보드 · 큐 시트(board)는 배치로 보내지 않는다: 쓰기를 바로 이어야 하고 한 화에 한 번이라 아낄 것이 적다
        use_batch = self.run.batch and stage != "board" and hasattr(llm, "batch_submit") and getattr(llm, "can_batch", True)
        if use_batch:
            llm = BatchLLM(llm, f"{n}:{stage}", self.run.batches, self.ctl.save, self.ctl.wait,
                           label=f"canon {self.name}", note=lambda m: self.log(f"{n}화 {STEP_NAMES[stage]}: {m}", "warn"),
                           keys=self.run.batch_keys)
        t = time.time()
        try:
            with usage.collect() as rows:
                out = fn(llm)
        except SchemaMismatch as e:
            # 본문은 그대로 두고 이 화에서 멈춘다. 이어 가면 이 단계만 새로 요청한다
            raise _Halt("paused", f"{n}화 {STEP_NAMES[stage]} 응답이 형식에 맞지 않아 멈췄어요", kind="schema", reasons=[
                f"{n}화 {STEP_NAMES[stage]}: 다시 요청해도 모델 응답이 {e.schema} 형식과 맞지 않았어요 ({e.brief})",
                "쓴 본문은 그대로 있어요. 이어 가면 이 단계만 다시 요청해요"
                + (". 배치에서 되풀이되면 배치를 끄고 이어 가 보세요" if use_batch else ""),
            ])
        except Interrupted as e:
            if e.cancelled:
                raise _Halt("stopped", "중지했어요 (기다리던 배치 작업을 취소)")
            if self.ctl.want == "pause":
                raise _Halt("paused", "일시정지했어요. 배치 작업은 계속 돌고, 이어 가면 결과를 받아 와요")
            raise _Halt(None, "서버를 다시 시작한 뒤 배치 결과를 이어 받아요")
        if rows:  # 단계 안의 모든 호출(형식 고치기 재시도, 검수의 여러 호출)을 사용량 화면과 같은 값으로 더한다
            tin, tout, c = usage.totals(rows)
        else:  # 기록하지 않는 LLM(mock 등)은 마지막 호출 값으로 짐작한다
            u = getattr(llm, "last_usage", None) or {}
            tin = int(u.get("prompt_tokens") or 0)
            tout = int(u.get("completion_tokens") or 0) + int(u.get("thought_tokens") or 0)
            c = stage_cost(stage, tin, tout, use_batch)
        with self.ctl.lock:
            self.run.tokens_in += tin
            self.run.tokens_out += tout
            if c:
                self.run.cost = round(self.run.cost + c, 4)
        return out, dict(step=stage, tokens_in=tin, tokens_out=tout, calls=max(1, len(rows)),
                         seconds=round(time.time() - t, 1), batch=use_batch)

    def loop(self) -> None:
        run = self.run
        try:
            while True:
                self._checkpoint()
                p = store.load(self.name)
                todo = _todo(p, run.target)
                if not todo:
                    raise _Halt("done", f"{run.target}화까지 모두 반영했어요")
                n = todo[0]
                if self.job is not None:
                    self.job.done = max(0, self.job.total - len(todo))
                try:
                    e = p.episode(n)
                except KeyError:
                    raise _Halt("paused", f"{n}화 플롯이 없어요", [f"{n}화 플롯이 없어요. 플롯을 만들고 확정한 뒤 이어 가세요"],
                                kind="plot_missing")
                if e.status == "draft":
                    if not run.policy.confirm_plots:
                        raise _Halt("paused", f"{n}화 플롯이 초안이에요",
                                    [f"{n}화 플롯이 아직 초안이에요. 확정한 뒤 이어 가세요 (또는 '초안 플롯도 자동으로 확정하고 쓰기'를 켜세요)"],
                                    kind="plot_draft")
                    _edit(self.name, lambda q: pipeline.confirm_plot(q, n))
                    self._set(n, "confirm")
                    self.log(f"{n}화 플롯을 자동으로 확정했어요")
                    continue
                self._fill_old_spots(p)
                if e.status == "confirmed":
                    self._recap_note(p)
                    if self._board(p, n):
                        continue  # 새 스토리보드를 저장했다. 다시 읽고 쓴다
                    if self._cues(p, n):
                        continue  # 새 큐 시트를 저장했다. 다시 읽고 쓴다
                    self._write(p, n)
                    continue
                if n in run.polish_due:
                    self._polish(p, n)
                    continue
                self._review(p, n)
        except _Halt as h:
            self._finish(h)
        except Exception as e:  # 화면과 로그에 그대로 보여 준다
            _log.exception("자동 집필이 오류로 멈췄어요 (%s)", self.name)
            msg = getattr(e, "message", None) or str(e) or type(e).__name__
            hint = " 배치를 끄고 이어 가 보세요." if run.batch and "batch" in msg.lower() else ""
            # 이유 칸에도 남겨 자동 집필 카드가 무엇 때문에 멈췄는지 보인다
            self._finish(_Halt("error", f"오류로 멈췄어요: {msg}{hint}", [f"{msg}{hint}"], kind="error"), level="error")

    def _fill_old_spots(self, p: Project) -> None:
        """쓰기 · 검수 전에 건물 한 줄이 빈 옛 핀을 채운다 (프롬프트의 '장소가 놓인 건물' 블록). 채웠으면 저장한다."""
        folder = store.project_dir(self.name) / "map"
        if atlas.fill_old_spots(p, folder):
            _edit(self.name, lambda q: atlas.fill_old_spots(q, folder))

    def _recap_note(self, p: Project) -> None:
        """요약을 기다리는 아크 · 부가 있으면 한 번 알린다. 멈추지는 않는다 (그동안은 화마다 첫 문장으로 접어 넣는다)."""
        seen = self.__dict__.setdefault("_recaps_noted", set())
        for kind, num in pipeline.pending_recaps(p):
            if (kind, num) in seen:
                continue
            seen.add((kind, num))
            unit = "아크" if kind == "arc" else "부"
            self.log(f"{unit} {num} 요약이 아직 없어요. 요약을 저장하기 전까지 그 {unit}의 줄거리는 화마다 첫 문장으로만 "
                     "들어가 앞 이야기가 흐려질 수 있어요. 기획 화면에서 요약을 저장해 주세요", "warn")

    def _board(self, p: Project, n: int) -> bool:
        """쓰기 전 스토리보드. 없거나 낡았으면 새로 만들어 저장하고 True. 작가가 고친 스토리보드가 낡았거나,
        AI 스토리보드에 이번 화 플롯과 어긋남 경고가 있으면(정책) 멈춘다. 다음 화 플롯 경고는 기록만 한다."""
        if not (self.run.policy.storyboard and board.on(p)):
            return False
        b = p.episode(n).storyboard
        if b is not None and not board.stale(p, n):
            if b.made_by == "ai" and self.run.policy.stop_on_board_warnings:
                reasons = board.stop_reasons(p, n, b)
                if reasons:
                    raise _Halt("paused", f"{n}화 스토리보드가 플롯과 어긋나 멈췄어요", reasons + [
                        "집필 화면의 스토리보드 카드에서 고치거나 그대로 저장한 뒤 이어 가세요"], kind="board")
            return False
        if b is not None and b.made_by != "ai":
            raise _Halt("paused", f"{n}화 스토리보드를 만든 뒤 앞 화나 플롯이 바뀌었어요", [
                f"작가가 고친 {n}화 스토리보드는 새로 만들지 않아요. 집필 화면에서 다시 만들거나 그대로 저장한 뒤 이어 가세요"],
                kind="board_stale")
        self._set(n, "board")
        self.log(f"{n}화 스토리보드를 만드는 중")
        lead: list[str] = []
        made, use = self.call("board", n, lambda llm: pipeline.make_storyboard(llm, p, n, lead=lead))

        def put(q: Project) -> None:
            st = q.episode(n).status
            if st != "confirmed":
                raise _Halt("paused", f"{n}화 상태가 '{EP_STATUS.get(st, st)}'(으)로 바뀌어 멈췄어요", [
                    f"스토리보드를 만드는 사이 {n}화가 '{EP_STATUS.get(st, st)}' 상태로 바뀌어 만든 스토리보드는 버렸어요",
                    f"이어 가면 {n}화의 지금 상태에서 다시 시작해요"], kind="changed")
            pipeline.set_storyboard(q, n, made, by="ai")
        _edit(self.name, put)
        self.board_lead = (n, made.made_at, lead)
        self.log(f"{n}화 스토리보드: 장면 {len(made.scenes)}개", **use)
        for w in made.warnings:
            if w.target == "next" or w.kind not in board.STOP_KINDS:
                self.log(f"스토리보드 {board.WARN_LABELS[w.kind]} 경고: {w.text}", "warn")
        return True

    def _cues(self, p: Project, n: int) -> bool:
        """쓰기 전 큐 시트 (스토리보드 다음). 없거나, AI · 뼈대로 만든 시트가 낡았으면 새로 만들어 저장하고 True.
        작가가 고친 시트는 낡아도 새로 만들지 않고 그대로 쓴다 (큐 시트는 확정 값이 아니라 연출 메모라 멈추지 않는다)."""
        if not (self.run.policy.cue_sheet and cue.on(p)):
            return False
        s = p.episode(n).cue_sheet
        if not cue.remake(p, n):
            if s.made_by in ("author", "both") and cue.stale(p, n):
                self.log(f"{n}화 큐 시트를 만든 뒤 앞 화나 플롯이 바뀌었어요. 작가가 고친 시트라 그대로 써요", "warn")
            return False
        self._set(n, "cues")
        self.log(f"{n}화 큐 시트를 만드는 중")
        # 방금 만든 스토리보드 요청 글로 시작하게 보내 캐시가 맞게 한다. 작가가 고쳤거나 낡았으면 예전 요청 (pipeline.cue_lead)
        bl = self.board_lead if self.board_lead and self.board_lead[0] == n else None
        lead = pipeline.cue_lead(p, n, bl[2], bl[1]) if bl else ""
        made, use = self.call("board", n, lambda llm: pipeline.make_cue_sheet(llm, p, n, lead=lead))
        if not made.cues:
            self.log(f"{n}화 큐 시트가 비어 왔어요. 큐 시트 없이 써요", "warn", **use)
            self.no_cues.add(n)
            return False

        def put(q: Project) -> None:
            st = q.episode(n).status
            if st != "confirmed":
                raise _Halt("paused", f"{n}화 상태가 '{EP_STATUS.get(st, st)}'(으)로 바뀌어 멈췄어요", [
                    f"큐 시트를 만드는 사이 {n}화가 '{EP_STATUS.get(st, st)}' 상태로 바뀌어 만든 큐 시트는 버렸어요",
                    f"이어 가면 {n}화의 지금 상태에서 다시 시작해요"], kind="changed")
            cue.set_episode(q, n, made, by="ai")
        _edit(self.name, put)
        self.log(f"{n}화 큐 시트: 큐 {len(made.cues)}개", **use)
        return True

    def _write(self, p: Project, n: int) -> None:
        self._set(n, "write")
        self.log(f"{n}화 본문을 쓰는 중" + (" (배치)" if self.run.batch and batchable("write") else ""))
        cut: list = []
        use_cues = n not in self.no_cues
        try:
            (text, model), usage = self.call("write", n, lambda llm: (pipeline.write_episode(llm, p, n, use_cues=use_cues, cut=cut),
                                                                      pipeline.writer_of(llm)))
        except pipeline.WriteCut as e:  # 끊긴 본문은 반영하지 않는다. 이어 가면 이 화 본문을 다시 쓴다
            raise _Halt("paused", f"{n}화 본문이 출력 길이 한도에 걸려 끊겨 멈췄어요",
                        [str(e), f"{n}화에 끊긴 본문을 넣지 않았어요. 이어 가면 {n}화 본문을 다시 써요"], kind="cut") from e

        def put(q: Project) -> None:
            ep = q.episode(n)
            if ep.status != "confirmed":
                raise _Halt("paused", f"{n}화 상태가 '{EP_STATUS.get(ep.status, ep.status)}'(으)로 바뀌어 멈췄어요",
                            _changed_while_writing(n, ep.status), kind="changed")
            ep.text, ep.status, ep.written_by, ep.meta_cut = text, "written", model, cut
            cue.mark_used(q, n, use_cues)  # 자동 집필은 있는 큐 시트를 넣어 쓴다. 다시 받은 시트가 비어 왔으면 빼고 쓴다
            anchor.stamp(q, n)
        q = _edit(self.name, put)
        if self.run.policy.polish:
            with self.ctl.lock:
                self.run.polish_due = [x for x in self.run.polish_due if x != n] + [n]
                self.ctl.save()
        self.log(f"{n}화 본문 {len(text):,}자", **usage)
        _, drift = pipeline.style_drift(q, n)
        for w in drift[:3]:
            self.log(f"문체: {w}", "warn")
        if prompts.is_opening(n):
            for w in pipeline.opening_metrics(q, n)[1][:3]:
                self.log(f"초반: {w}", "warn")

    def _polish(self, p: Project, n: int) -> None:
        """방금 쓴 본문의 서술 문장만 다듬어 본문으로 바꾼다 (Policy.polish). 쓴 판은 이전 판으로 남는다 (pipeline.replace_text).
        다듬기가 멈추거나(대사 줄이 바뀜), 그사이 본문이 바뀌었으면 쓴 글 그대로 검수로 간다. 화를 멈추지 않는다."""
        self._set(n, "polish")
        self.log(f"{n}화 서술을 다듬는 중" + (" (배치)" if self.run.batch and batchable("revise") else ""))
        before = p.episode(n).text
        cut: list = []

        def done(note: str = "", level: str = "info", **kw: Any) -> None:
            with self.ctl.lock:
                self.run.polish_due = [x for x in self.run.polish_due if x != n]
                self.ctl.save()
            if note:
                self.log(note, level, **kw)

        try:
            (text, model), use = self.call("revise", n, lambda llm: (pipeline.polish_episode(llm, p, n, cut), pipeline.writer_of(llm)))
        except ValueError as e:
            done(f"{n}화 서술 다듬기를 건너뛰고 쓴 글로 이어 가요: {e}", "warn")
            return
        kept = {"same": True}

        def put(q: Project) -> None:
            ep = q.episode(n)
            if ep.status != "written" or ep.text != before:
                kept["same"] = False
                return
            pipeline.replace_text(ep, text, made_by=RewriteRequest(mode="polish"), written_by=model, meta_cut=cut)
            anchor.stamp(q, n)
        q = _edit(self.name, put)
        if not kept["same"]:
            done(f"{n}화 본문이 그사이 바뀌어 다듬은 글은 버렸어요", "warn", **use)
            return
        done(f"{n}화 서술 다듬기: {len(before):,}자 → {len(text):,}자 (쓴 판은 이전 판에 있어요)", **use)
        _, drift = pipeline.style_drift(q, n)
        for w in drift[:3]:
            self.log(f"문체: {w}", "warn")

    def _review(self, p: Project, n: int) -> None:
        self._set(n, "review")
        run = self.run
        steps = ["state"] + (["check"] if run.policy.check else [])
        self.log(f"{n}화 {'검수와 ' if run.policy.check else ''}상태 변경안을 만드는 중"
                 + (" (배치)" if run.batch and any(batchable(s) for s in steps) else ""))
        fns = {"state": lambda llm: pipeline.extract_state(llm, p, n),
               "check": lambda llm: pipeline.check_episode(llm, p, n)}
        with ThreadPoolExecutor(max_workers=len(steps)) as pool:
            futures = {s: pool.submit(self.call, s, n, fns[s]) for s in steps}
            errors = []
            results: dict[str, Any] = {}
            for s, f in futures.items():
                try:
                    results[s] = f.result()
                except _Halt as h:
                    errors.append(h)
                except Exception as e:
                    errors.append(e)
            if errors:
                if "check" in results:  # 받아 온 검수는 버리지 않는다 (참고용이라 승인 없이 저장)
                    _edit(self.name, lambda q: pipeline.apply_check(q, results["check"][0], "auto", pipeline.widen_on(q)))
                # 한쪽만 멈춤 요청을 받았으면 다른 쪽(기다리는 배치)도 같은 이유로 멈춘다
                raise next((e for e in errors if not isinstance(e, _Halt)), errors[0])
        delta: StateDelta = results["state"][0]
        report: Optional[ConsistencyReport] = results["check"][0] if "check" in results else None
        self.log(f"{n}화 상태 변경안: 인물 {len(delta.character_updates)}, 사건 {len(delta.events)}, "
                 f"사실 {len(delta.new_facts)}", **results["state"][1])
        if report is not None:
            _edit(self.name, lambda q: pipeline.apply_check(q, report, "auto", pipeline.widen_on(q)))
            self.log(f"{n}화 검수: 어긋난 곳 {len(report.issues)}개", "warn" if report.issues else "info",
                     **results["check"][1])
        p = store.load(self.name)
        _same_text(p, n, delta)
        reasons = review_reasons(p, delta, report, run.policy)
        if reasons:
            with self.ctl.lock:
                run.pending, run.pending_text = delta, p.episode(n).text
            raise _Halt("review", f"{n}화는 검토가 필요해 멈췄어요", reasons, kind="review")

        def put(q: Project) -> None:
            st = q.episode(n).status
            if st != "written":
                raise _Halt("paused", f"{n}화 상태가 '{EP_STATUS.get(st, st)}'(으)로 바뀌어 멈췄어요", [
                    f"상태 변경안을 만드는 사이 {n}화가 '{EP_STATUS.get(st, st)}' 상태로 바뀌어 만든 변경안은 버렸어요",
                    f"이어 가면 {n}화의 지금 상태에서 다시 시작해요"], kind="changed")
            _same_text(q, n, delta)
            try:
                pipeline.check_applicable(q, n)  # 그사이 앞 화를 반영 취소했으면 반영하지 않는다
            except ValueError as e:
                raise _Halt("paused", f"{n}화 상태 변경안을 반영하지 못해 멈췄어요", [str(e), "앞 화를 반영한 뒤 이어 가세요"], kind="changed")
            held[0] = features.hold(q, delta)  # 인물 설정 · 호칭은 작가가 골라야 바뀐다. 인물 화면에 남겨 둔다
            dropped[:] = pipeline.apply_delta(q, delta)
            q.episode(n).auto = True
        held = [0]
        dropped: list[str] = []
        _edit(self.name, put)
        _drop_pending_state(self.name, n)
        with self.ctl.lock:
            run.applied.append(n)
        self._set(n, "applied")
        if self.job is not None:
            self.job.step_ep = n  # 화면이 'n화를 반영했어요' 알림을 보낸다 (notify.js)
        self.log(f"{n}화를 자동으로 반영했어요")
        for m in dropped:
            self.log(f"{n}화 반영에서 뺐어요: {m}", "warn")
        if held[0]:
            self.log(f"{n}화 설정 바꾸기 · 호칭 제안 {held[0]}개는 반영하지 않고 인물 · 관계도 화면에 남겨 뒀어요", "warn")
        every = run.policy.review_every
        if every and len(run.applied) % every == 0 and _todo(store.load(self.name), run.target):
            raise _Halt("paused", f"{every}화마다 멈추도록 설정해 멈췄어요",
                        [f"{every}화마다 검토하도록 설정했어요. 읽어 보고 이어 가세요"], kind="every")

    def _finish(self, h: _Halt, level: str = "info") -> None:
        with self.ctl.lock:
            if h.status is not None:
                self.run.status = h.status  # type: ignore[assignment]
                self.run.reasons = h.reasons
                self.run.halt = h.kind
                if h.status != "review":
                    self.run.step = "" if h.status == "done" else self.run.step
            self.ctl.save()
        lvl = level if h.status != "review" else "warn"
        self.log(h.message + (": " + " / ".join(h.reasons) if h.reasons else ""), lvl)
        if self.job is not None:
            self.job.note = h.message


def _launch(name: str, ctl: Control, echo: Callable[[str], None] | None = None, foreground: bool = False) -> None:
    def body(job: Optional[jobs.Job]) -> dict:
        try:
            Runner(ctl, job, echo).loop()
        finally:
            with _lock:
                ctl.thread_alive = False
                ctl.release()
        if job is not None:
            job.total, job.done = 1, 0  # 끝나도 'n/n 완료'로 보이지 않게 (멈춘 이유는 note 에 있다)
        return {"status": ctl.run.status, "reasons": ctl.run.reasons, "ep": ctl.run.ep}

    ctl.thread_alive = True
    if foreground:
        body(None)
        return
    p = store.load(name)
    try:
        jobs.start(name, "auto", None, f"자동 집필 ({ctl.run.target}화까지)", body,
                   total=max(1, len(_todo(p, ctl.run.target)) + len(ctl.run.applied)))
    except jobs.Busy:
        ctl.thread_alive = False
        ctl.release()
        raise ValueError("자동 집필이 이미 돌고 있어요")


def _control(name: str, run: Run) -> Control:
    """이 프로세스가 실행 주인이 되어 Control 을 등록한다.
    같은 프로세스의 두 번째 시작 · 이어 가기는 잠금 파일을 보기 전에 STARTING 으로 거절한다.
    잠금 파일을 다시 잡아 보는 대기(_take)는 전역 _lock 밖에서 해서 다른 작품의 요청을 막지 않는다."""
    with _lock:
        ctl = _controls.get(name)
        if ctl and ctl.thread_alive:
            raise ValueError("자동 집필이 이미 돌고 있어요. 일시정지나 중지 후 다시 시작하세요")
        if name in _taking or (ctl and ctl.owner is not None):  # 다른 스레드가 시작 · 이어 가기를 준비하는 중이다
            raise ValueError(STARTING)
        _taking.add(name)
    try:
        fd = _take(name)
        if fd is None:
            raise ValueError(ELSEWHERE)
        ctl = Control(name, run)
        ctl.owner = fd
        with _lock:
            _controls[name] = ctl
        return ctl
    finally:
        with _lock:
            _taking.discard(name)


def start(name: str, target: int, batch: bool, policy: Policy, *, foreground: bool = False,
          echo: Callable[[str], None] | None = None) -> Run:
    """새 실행을 시작한다. 지난 실행의 로그는 이어 붙이고, 기다리던 배치나 검토 대기는 버린다."""
    p = store.load(name)
    if not 1 <= target <= max(p.meta.target_episodes, 1):
        raise ValueError(f"목표 화수는 1~{p.meta.target_episodes}화 사이여야 해요")
    if elsewhere(name):
        raise ValueError(ELSEWHERE)
    if active(name):
        raise ValueError("자동 집필이 이미 돌고 있어요. 일시정지나 중지 후 다시 시작하세요")
    old = load_run(name)
    if old and old.batches:
        _cancel_batches(old)
    run = Run(target=target, batch=batch, policy=policy, started=_now(), log=old.log if old else [])
    ctl = _control(name, run)
    try:
        ctl.save()
        Runner(ctl).log(f"{target}화까지 자동 집필을 시작해요 (배치 {'켬' if batch else '끔'})", step="start")
        if batch and any(settings.stage_provider(s)[0] == "gemini" and not batchable(s) for s in STEP_NAMES):
            Runner(ctl).log("Vertex AI 로 부르는 Gemini 는 배치를 지원하지 않아 그 단계는 일반 호출로 진행해요", "warn")
    except BaseException:
        ctl.release()
        raise
    _launch(name, ctl, echo, foreground)
    return ctl.run


def resume(name: str, approve: bool = False, rewrite: bool = False, *, foreground: bool = False,
           echo: Callable[[str], None] | None = None) -> Run:
    """멈춘 실행을 이어 간다. 검토 대기 중이면 approve 는 변경안을 그대로 반영하고, rewrite 는 그 화를 다시 쓴다.
    사용자가 검토 화면에서 직접 반영했으면 둘 다 없이 이어 가면 된다."""
    run = get_run(name)
    if run is None:
        raise ValueError("이어 갈 자동 집필이 없어요")
    ctl = _control(name, run)
    r = Runner(ctl)
    try:
        if run.status == "review" and run.ep is not None:
            n = run.ep
            status = store.load(name).episode(n).status
            if status == "written" and approve and run.pending is not None:
                d = run.pending
                if run.pending_text and store.load(name).episode(n).text.strip() != run.pending_text.strip():
                    raise ValueError(f"변경안을 만든 뒤 {n}화 본문을 고쳤어요. 그대로 반영하면 옛 본문 기준의 요약 · 인물 상태 · 사건이 들어가요. "
                                     "검토하기에서 변경안을 다시 만들거나, 다시 쓰기를 고르세요")
                def take(q: Project) -> None:
                    pipeline.check_applicable(q, n)
                    held[0] = features.hold(q, d)  # 검토 화면 없이 반영하면 설정 바꾸기 · 호칭 제안은 고르지 않은 것으로 남겨 둔다
                    dropped[:] = pipeline.apply_delta(q, d)
                held = [0]
                dropped: list[str] = []
                _edit(name, take)
                _drop_pending_state(name, n)
                r.log(f"{n}화 변경안을 검토 화면 없이 그대로 반영했어요 (사용자 승인)")
                for m in dropped:
                    r.log(f"{n}화 반영에서 뺐어요: {m}", "warn")
                if held[0]:
                    r.log(f"{n}화 설정 바꾸기 · 호칭 제안 {held[0]}개는 반영하지 않고 인물 · 관계도 화면에 남겨 뒀어요", "warn")
            elif status == "written" and rewrite:
                def back(q: Project) -> None:
                    ep = q.episode(n)
                    if ep.text:  # 집필 화면의 다시 생성처럼 지금 본문을 이전 판으로 남긴다
                        pipeline._keep_version(ep, TextVersion(id=pipeline._version_id(ep), at=pipeline._now(), text=ep.text, kind="previous",
                                                               model=ep.written_by, meta_cut=ep.meta_cut))
                    ep.text, ep.status, ep.written_by, ep.meta_cut = "", "confirmed", "", []
                    findings.clear(ep)
                _edit(name, back)
                r.log(f"{n}화를 다시 써요")
            elif status == "written":
                raise ValueError(f"{n}화 변경안이 검토 대기 중이에요. 검토 화면에서 반영하거나, 그대로 반영 또는 다시 쓰기를 고르세요")
        with ctl.lock:
            run.status, run.reasons, run.pending, run.pending_text, run.halt = "running", [], None, "", ""
            ctl.save()
        r.log("이어 가요")
    except BaseException:
        ctl.release()
        raise
    _launch(name, ctl, echo, foreground)
    return run


def check_renumber(name: str) -> None:
    """화를 끼워 넣거나 빼기 전에 본다. 도는 중이거나 결과를 기다리는 배치가 있으면 화 번호가 어긋나므로 막는다."""
    if active(name):
        raise ValueError("자동 집필이 도는 중이에요. 일시정지한 뒤에 하세요")
    run = get_run(name)
    if run and run.batches and run.status not in ("done", "stopped"):
        raise ValueError("자동 집필이 결과를 기다리는 배치 작업이 있어요. 중지한 뒤에 하세요")


def renumber(name: str, end: Callable[[int], int]) -> None:
    """화를 끼워 넣거나 뺀 뒤 멈춘 실행의 목표 화를 옮긴다. end 는 '몇 화까지'를 옮기는 규칙이다."""
    with _lock:
        ctl = _controls.get(name)
    run = ctl.run if ctl and ctl.thread_alive else load_run(name)
    if run is None or run.status in ("done", "stopped"):
        return
    target = max(1, end(run.target))
    if target == run.target:
        return
    run.target = target
    _write(name, run)


def request(name: str, what: str) -> Run:
    """일시정지(pause) 또는 중지(stop) 요청. 돌고 있지 않으면 바로 상태만 바꾼다."""
    if what not in ("pause", "stop"):
        raise ValueError(what)
    with _lock:
        ctl = _controls.get(name)
    if ctl and ctl.thread_alive:
        ctl.want = what
        ctl.wake.set()
        return ctl.run
    run = get_run(name)
    if run is None:
        raise ValueError("자동 집필이 없어요")
    if elsewhere(name):  # 그 프로세스의 러너가 다음 확인 때 읽는다. 배치 취소와 상태 쓰기도 그쪽이 한다
        _ask(name, what)
        return run
    if what == "stop":
        _cancel_batches(run)
        run.status, run.pending, run.pending_text, run.reasons, run.halt = "stopped", None, "", [], ""
        _write(name, run)
    return run


def set_batch(name: str, on: bool) -> Run:
    """배치를 켜거나 끈다. 돌고 있으면 다음 단계부터 적용된다. 기다리던 배치는 그대로 받아 온다."""
    run = get_run(name)
    if run is None:
        raise ValueError("자동 집필이 없어요")
    if elsewhere(name):
        raise ValueError(ELSEWHERE)
    with _lock:
        ctl = _controls.get(name)
    run.batch = on
    if ctl and ctl.thread_alive:
        ctl.save()
        Runner(ctl).log(f"배치를 {'켰' if on else '껐'}어요. 다음 단계부터 적용돼요")
    else:
        _write(name, run)
    return run


def set_policy(name: str, policy: Policy) -> Run:
    """멈춘 실행의 승인 정책을 바꾼다. 검토 대기 변경안과 기다리던 배치는 그대로 두고, 다음 판정부터 적용된다."""
    run = get_run(name)
    if run is None:
        raise ValueError("자동 집필이 없어요")
    if run.status in ("done", "stopped"):
        raise ValueError("끝나거나 중지한 자동 집필이에요. 새로 시작할 때 정하세요")
    if elsewhere(name):
        raise ValueError(ELSEWHERE)
    with _lock:
        ctl = _controls.get(name)
    run.policy = policy
    # 화 번호 없이 남긴다 (멈춘 화는 정책 변경과 상관없다)
    run.log = (run.log + [LogEntry(at=_now(), step="policy", message="승인 정책을 바꿨어요. 다음 판정부터 적용돼요")])[-LOG_KEEP:]
    if ctl and ctl.thread_alive:
        ctl.save()
    else:
        _write(name, run)
    return run


def after_revert(name: str, n: int) -> Optional[Run]:
    """화면에서 n화부터 반영을 취소한 뒤 실행 기록을 맞춘다. 이번 실행의 자동 반영 목록에서 n화 이상을 빼고 로그를 남긴다.
    끝난 실행에 남은 화가 생기면 일시정지로 바꿔 이어 갈 수 있게 한다. 그 화들의 검토 대기 변경안은 버린다."""
    run = get_run(name)
    if run is None or active(name):
        return run
    run.applied = [x for x in run.applied if x < n]
    entry = LogEntry(at=_now(), ep=n, step="revert", level="warn", message=f"{n}화부터 반영을 취소했어요")
    run.log = (run.log + [entry])[-LOG_KEEP:]
    left = _todo(store.load(name), run.target)
    stale = run.status == "review" and run.ep is not None and run.ep >= n
    if left and (run.status == "done" or stale):
        run.status, run.halt, run.pending, run.pending_text = "paused", "reverted", None, ""
        run.reasons = [f"{n}화부터 반영을 취소했어요. 이어 가면 {left[0]}화부터 다시 이어 가요"]
    _write(name, run)
    return run


def _changed_while_writing(n: int, status: str) -> list[str]:
    """본문을 쓰는 사이 사용자가 그 화를 바꿔 멈출 때의 이유. AI가 쓴 본문은 버렸다."""
    if status == "written":
        return [f"{n}화 본문을 직접 저장해서 멈췄어요. 직접 쓴 본문을 남기고 AI가 쓴 본문은 버렸어요",
                "이어 가면 이 본문으로 상태 변경안을 만들어요"]
    if status == "draft":
        return [f"{n}화 플롯을 초안으로 되돌려서 멈췄어요. AI가 쓴 본문은 버렸어요",
                f"플롯을 확정한 뒤 이어 가면 {n}화를 새로 써요"]
    return [f"{n}화가 '{EP_STATUS.get(status, status)}' 상태로 바뀌어 AI가 쓴 본문은 버렸어요",
            f"이어 가면 {n}화의 지금 상태에서 다시 시작해요"]


def _drop_pending_state(name: str, n: int) -> None:
    """자동으로 반영한 화의 검토 대기 변경안(pending.json 의 state:<화>, web.auto_review · 반영 취소가 둔 것)을 지운다.
    남겨 두면 작품 목록이 반영한 화의 변경안을 알리고, 반영 뒤 고친 화의 다시 맞추기 후보로 옛 변경안이 놓인다."""
    if f"state:{n}" in store.load_pending(name)["results"]:
        store.edit_pending(name, lambda d: d["results"].pop(f"state:{n}", None))


def _same_text(p: Project, n: int, delta: StateDelta) -> None:
    """변경안이 지금 본문으로 만든 것인지 본다. 만드는 사이 (일시정지 중 배치를 기다리는 동안) 본문을 고쳤으면 반영하지 않고 멈춘다."""
    if delta.basis and delta.basis != pipeline.text_basis(p.episode(n).text):
        raise _Halt("paused", f"{n}화 본문이 바뀌어 멈췄어요", [
            f"상태 변경안을 만드는 사이 {n}화 본문이 바뀌어, 옛 본문으로 만든 변경안은 버렸어요",
            "이어 가면 지금 본문으로 상태 변경안을 새로 만들어요"], kind="changed")


def _cancel_batches(run: Run) -> None:
    """기다리던 배치 작업을 취소한다. 이미 끝났거나 키가 없어 취소하지 못해도 목록은 비운다."""
    for slot, bname in list(run.batches.items()):
        try:
            get_llm(slot.split(":")[1]).batch_cancel(bname)  # type: ignore[attr-defined]  # "<화>:<단계>[:fix]"
        except Exception as e:  # 취소하지 못한 배치는 서비스 쪽에서 계속 돌아 요금이 나갈 수 있다. 콘솔에서 지울 수 있게 이름을 남긴다
            _log.warning("배치 %s(%s)를 취소하지 못했어요: %s", bname, slot, getattr(e, "message", None) or e)
    run.batches = {}
    run.batch_keys = {}


def resume_all() -> list[str]:
    """서버가 시작할 때 진행 중이던 실행을 다시 띄운다 (배치 작업에 다시 붙는다)."""
    out = []
    if not store.ROOT.exists():
        return out
    for d in sorted(store.ROOT.iterdir()):
        run = load_run(d.name) if (d / "autorun.json").exists() else None
        if run and run.status == "running" and store.exists(d.name):
            try:
                ctl = _control(d.name, run)
            except ValueError:  # 명령줄 canon auto 같은 다른 프로세스가 돌리고 있다
                _log.info("자동 집필 %s 은(는) 다른 프로세스가 돌리고 있어 이어 가지 않아요", d.name)
                continue
            run.restarts += 1
            # 기다리던 배치는 다시 붙어 결과를 받는다. 일반 호출은 끊긴 호출을 버리고 그 단계를 처음부터 다시 한다
            redo = "" if run.batches or not run.ep or run.step not in RUN_STEPS else \
                f". {run.ep}화 {RUN_STEPS[run.step]}를 처음부터 다시 해요 (끊긴 호출은 버려요)"
            Runner(ctl).log("서버가 다시 시작돼 이어 가요" + redo, "warn" if redo else "info", step="restart")
            _launch(d.name, ctl)
            out.append(d.name)
    return out


def progress_mark(p: Project) -> tuple:
    """상태 반영 진행을 나타내는 값. 화면이 가진 작품과 디스크가 다르면 화면이 오래된 것이다."""
    return tuple(d.episode for d in p.history), len(p.events), tuple(s.episode for s in p.snapshots)


PROGRESS_FIELDS = ("states", "relationships", "ties", "secrets", "events", "facts", "foreshadows", "history", "snapshots")


def protected(name: str, disk: Project, mine: Project) -> list[dict]:
    """화면이 작품 전체를 저장할 때, 자동 집필이 도는 중이거나 화면이 반영 진행을 모르는(오래된) 상태면
    진행 상태(인물 상태, 관계, 사건, 스냅샷 등)와 본문이 있는 화는 디스크 것을 지킨다.
    아직 안 쓴 화의 플롯과 다른 설정은 화면 것을 쓴다.
    화면이 고칠 수 있는 칸 중 화면 값과 다른 디스크 것을 둔 칸을 돌려준다 (화면이 고친 칸인지 가려 알린다):
    {"field": "relationships"} · {"field": "plot", "ep": n} · {"field": "character", "name": 이름}."""
    if not active(name) and progress_mark(disk) == progress_mark(mine):
        return []
    kept: list[dict] = []
    if mine.relationships != disk.relationships:  # 진행 칸 중 화면이 직접 고치는 것은 관계뿐이다
        kept.append({"field": "relationships"})
    for f in PROGRESS_FIELDS:
        setattr(mine, f, getattr(disk, f))
    # 승인된 변경안이 더한 인물(new_characters)도 진행이다. 화면이 그 반영 전에 읽은 인물 목록으로 덮지 않게 한다
    added = {c.id for d in disk.history for c in d.new_characters}
    have = {c.id for c in mine.characters}
    back = [c for c in disk.characters if c.id in added and c.id not in have]
    mine.characters += back
    kept += [{"field": "character", "name": c.name or c.id} for c in back]
    # 승인된 변경안이 본문에서 등록한 장소(인과율 '장소' 요소)도 진행이다
    ids = {el.id for el in mine.elements}
    mine.elements += [el for el in disk.elements if el.found_in == "본문" and el.id not in ids]
    run = get_run(name)
    cur = run.ep if run and active(name) else None
    d = {e.plot.number: e for e in disk.episodes}
    m = {e.plot.number: e for e in mine.episodes}
    body = ("written", "finalized")
    for n, e in d.items():
        if e.status in body or n == cur or (n in m and m[n].status in body):
            if n in m and m[n].plot != e.plot:
                kept.append({"field": "plot", "ep": n})
            m[n] = e
    mine.episodes = [m[k] for k in sorted(m)]
    return kept

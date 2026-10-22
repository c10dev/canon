"""자동 집필: 목표 화수까지 본문 → 검수 + 상태 변경안 → 반영 → 다음 화를 반복한다.

화는 앞 화의 상태가 반영돼야 쓸 수 있어 차례로만 진행한다. 한 화 안에서 검수와 상태 변경안은 같은 본문만
보므로 동시에 부른다. 배치(Gemini Batch API)를 켜면 단계마다 배치 작업을 보내고 결과를 기다린다. 비용은
절반이지만 단계마다 몇 분에서 길게는 24시간이 걸릴 수 있다. 끄면 일반 호출이다. 배치가 없는 백엔드(로컬,
mock 제외)는 켜 둬도 일반 호출로 돈다.

사람 승인을 건너뛰는 대신 정책(Policy)에 걸리면 그 화에서 멈추고 변경안을 검토 대기(pending)로 둔다.
자동으로 반영한 화는 Episode.auto 로 표시하고, 화마다 스냅샷이 남아 pipeline.revert 로 되돌릴 수 있다.

진행 상태와 로그는 projects/<이름>/autorun.json 에 따로 둔다 (project.json 저장과 부딪치지 않게).
서버가 다시 시작돼도 진행 중이던 실행은 이어서 돌고, 기다리던 배치 작업에는 다시 붙는다.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, Field

from . import dynamics, jobs, pipeline, prompts, settings, store, usage
from .llm import BatchLLM, Interrupted, SchemaMismatch, get_llm
from .research import CHARS_PER_TOKEN, JSON_OUTPUT_RESERVE, _filler
from .schema import ConsistencyReport, Project, StateDelta

LOG_KEEP = 500
STEP_NAMES = {"write": "본문", "check": "검수", "state": "상태 변경안"}
# 측정값이 없을 때 쓰는 단계별 소요 시간 추정 (초, 일반 호출)
SECONDS = {"write": 90.0, "check": 40.0, "state": 40.0}
# 배치 한 번 기다리는 시간 가정 (초): 보통 범위. 최악은 24시간
BATCH_WAIT = (3 * 60.0, 60 * 60.0)

RunStatus = Literal["running", "paused", "review", "stopped", "done", "error"]


class Policy(BaseModel):
    """사람 검토 없이 반영할지 정하는 기준. 하나라도 걸리면 그 화에서 멈춘다."""
    check: bool = Field(True, description="화마다 검수를 돌린다")
    max_issues: int = Field(0, description="검수에서 나온 어긋남이 이 개수를 넘으면 멈춤")
    max_shift: float = Field(0.3, description="한 인물이 다른 인물을 보는 온기나 신뢰가 한 화에 이만큼 넘게 바뀌면 멈춤. 0 이면 보지 않음")
    stop_on_stage: bool = Field(False, description="관계 단계(호감 → 균열 등)가 바뀌면 멈춤")
    stop_on_warnings: bool = Field(False, description="상태 변경안에 경고(플롯 누락, 설정 위반)가 있으면 멈춤")
    confirm_plots: bool = Field(False, description="초안 플롯을 만나면 자동으로 확정하고 쓴다. 끄면 그 화에서 멈춤")
    review_every: int = Field(0, description="이번 실행에서 N화를 반영할 때마다 멈춤. 0 이면 멈추지 않음")
    hand_pick_opening: bool = Field(True, description="1~3화는 쓰고 검수한 뒤 반영하기 전에 멈춤. 독자가 계속 읽을지 정하는 화라 작가가 읽고 고른다")


class LogEntry(BaseModel):
    at: str
    ep: Optional[int] = None
    step: str = ""
    level: Literal["info", "warn", "error"] = "info"
    message: str
    tokens_in: int = 0
    tokens_out: int = 0
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
    pending: Optional[StateDelta] = Field(None, description="검토 대기 중인 변경안")
    batches: dict[str, str] = Field(default_factory=dict, description="기다리는 배치 작업 slot -> 이름")
    applied: list[int] = Field(default_factory=list, description="이번 실행에서 자동 반영한 화")
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
    tmp = path.with_suffix(".tmp")
    tmp.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------- 실행 제어 (프로세스 안) ----------

class Control:
    def __init__(self, name: str, run: Run):
        self.name, self.run = name, run
        self.lock = threading.RLock()
        self.want = ""  # "" | pause | stop
        self.wake = threading.Event()
        self.thread_alive = False

    def save(self) -> None:
        with self.lock:
            _write(self.name, self.run)

    def wait(self, seconds: float) -> str:
        """배치 결과를 기다린다. 멈추라는 요청이 오면 바로 깬다."""
        self.wake.wait(seconds)
        self.wake.clear()
        if self.want:
            return self.want
        return "pause" if jobs.draining.is_set() else ""


_controls: dict[str, Control] = {}
_lock = threading.Lock()


def get_run(name: str) -> Optional[Run]:
    with _lock:
        ctl = _controls.get(name)
    return ctl.run if ctl else load_run(name)


def active(name: str) -> bool:
    """자동 집필이 이 작품을 고치고 있는가 (화면 저장이 진행 상태를 덮으면 안 되는 동안)."""
    with _lock:
        ctl = _controls.get(name)
    return bool(ctl and ctl.thread_alive)


# ---------- 승인 정책 ----------

def _names(p: Project) -> dict[str, str]:
    return {c.id: c.name or c.id for c in p.characters}


def review_reasons(p: Project, delta: StateDelta, report: Optional[ConsistencyReport], policy: Policy) -> list[str]:
    """정책에 걸린 이유. 빈 목록이면 자동으로 반영해도 된다. p 는 반영 전 상태이고 바꾸지 않는다."""
    out: list[str] = []
    if report is not None and len(report.issues) > policy.max_issues:
        kinds = ", ".join(sorted({i.type for i in report.issues}))
        out.append(f"검수에서 어긋난 곳 {len(report.issues)}개 ({kinds})")
    if policy.hand_pick_opening and prompts.is_opening(delta.episode):
        out.append(f"{delta.episode}화는 초반 화라 직접 읽고 반영하도록 멈춥니다 (집필 화면에서 초반 점검과 여는 방식 비교를 쓸 수 있어요)")
    if policy.stop_on_warnings and delta.warnings:
        out.append(f"상태 변경안 경고 {len(delta.warnings)}개: {delta.warnings[0]}")
    names = _names(p)
    unknown = sorted({u.character_id for u in delta.character_updates if u.character_id not in names})
    if unknown:
        out.append(f"설정에 없는 인물의 상태가 나왔습니다: {', '.join(unknown)}")
    if policy.max_shift > 0 or policy.stop_on_stage:
        sim = p.model_copy(deep=True)
        pipeline.apply_delta(sim, delta.model_copy(deep=True))
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
            out.append("관계가 크게 움직였습니다: " + "; ".join(s for _, s in sorted(big, reverse=True)[:3]))
        if stages:
            out.append("관계 단계가 바뀌었습니다: " + ", ".join(stages[:3]))
    return out


# ---------- 비용과 시간 추정 ----------

def stage_cost(stage: str, tin: float, tout: float, batch: bool) -> Optional[float]:
    """단계가 쓰는 모델로 tin/tout 토큰을 쓸 때의 USD. 가격은 사용량 화면과 같은 가격표(usage.prices)를 쓴다.
    로컬은 0원, 가격표에 없는 Gemini 모델이면 None."""
    prov = settings.stage_provider(stage)[0]
    return usage.stage_cost(prov, gemini_model(stage), tin, tout, batch and prov == "gemini")


def gemini_model(stage: str) -> str:
    """단계가 쓰는 Gemini 모델. 단계별 모델이 없으면 전체 모델."""
    return settings.stage_model(stage)[0] or settings.model()[0]


def batchable(stage: str) -> bool:
    return settings.stage_provider(stage)[0] in ("gemini", "mock")


def _todo(p: Project, target: int) -> list[int]:
    have = {e.plot.number: e.status for e in p.episodes}
    return [n for n in range(1, target + 1) if have.get(n) != "finalized"]


def _measured(name: str | None) -> dict[str, dict[str, float]]:
    """지난 실행 로그에서 단계별 평균 출력 토큰과 걸린 시간 (일반/배치 따로)."""
    run = load_run(name) if name else None
    acc: dict[str, list[LogEntry]] = {}
    for e in (run.log if run else []):
        if e.step in SECONDS and e.seconds and e.level == "info":
            acc.setdefault(e.step + (":batch" if e.batch else ""), []).append(e)
    return {k: {"out": sum(x.tokens_out for x in v) / len(v), "seconds": sum(x.seconds for x in v) / len(v)}
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
    write_out = p.meta.words_per_episode / CHARS_PER_TOKEN
    steps = {"write": 0, "check": 0, "state": 0}
    tokens = {s: [0.0, 0.0] for s in steps}
    missing = []
    for n in todo:
        e = have.get(n)
        if e is None:
            missing.append(n)
            continue
        calls = [("state", prompts.SYSTEM_EDITOR + prompts.state_prompt(sim, n), JSON_OUTPUT_RESERVE)]
        if policy.check:
            calls.append(("check", prompts.SYSTEM_CHECKER + prompts.check_prompt(sim, n), JSON_OUTPUT_RESERVE))
        if e.status in ("draft", "confirmed"):
            calls.append(("write", prompts.writer_system(sim) + prompts.episode_prompt(sim, n), write_out))
        for step, text, out in calls:
            m = measured.get(step + (":batch" if batch and batchable(step) else "")) or measured.get(step)
            steps[step] += 1
            tokens[step][0] += len(text) / CHARS_PER_TOKEN
            tokens[step][1] += m["out"] if m and m["out"] else out
    cost: Optional[float] = 0.0
    unpriced = []
    for step, (tin, tout) in tokens.items():
        c = stage_cost(step, tin, tout, batch)
        if c is None:
            unpriced.append(gemini_model(step))
        elif cost is not None:
            cost += c
    if unpriced:
        cost = None
    eps = len(todo) - len(missing)

    def secs(step: str) -> float:
        if batch and batchable(step):
            return 0.0  # 배치 대기는 rounds 로 따로 센다
        m = measured.get(step)
        return m["seconds"] if m else SECONDS[step]

    review = [s for s in ("check", "state") if steps[s]]
    # 일반 호출: 본문 + (동시에 부르는 검수와 상태 변경안 중 긴 쪽)
    normal = steps["write"] * secs("write") + eps * max((secs(s) for s in review), default=0.0)
    # 배치: 본문 한 번, 검수 + 상태 변경안 한 번을 기다린다
    rounds = ((steps["write"] if batchable("write") else 0) + (eps if any(batchable(s) for s in review) else 0)) if batch else 0
    waits = [v["seconds"] for k, v in measured.items() if k.endswith(":batch")]
    return {
        "episodes": eps, "from": todo[0] if todo else None, "to": target, "missing": missing,
        "calls": steps, "tokens_in": round(sum(t[0] for t in tokens.values())),
        "tokens_out": round(sum(t[1] for t in tokens.values())),
        "cost": round(cost, 2) if cost is not None else None, "batch": batch,
        "batch_rounds": rounds, "seconds_min": round(normal + rounds * BATCH_WAIT[0]),
        "seconds_max": round(normal + rounds * BATCH_WAIT[1]), "seconds_worst": round(normal + rounds * 86400),
        "batch_avg_seconds": round(sum(waits) / len(waits)) if waits else None,
        "measured": bool(measured), "model": gemini_model("write"), "unpriced": sorted(set(unpriced)),
        "stages": {s: settings.stage_provider(s)[0] for s in steps},
    }


# ---------- 실행 ----------

class _Halt(Exception):
    """루프를 끝낸다. status 가 None 이면 상태를 바꾸지 않고(서버 재시작 대기) 나간다."""

    def __init__(self, status: Optional[str], message: str = "", reasons: list[str] | None = None):
        super().__init__(message)
        self.status, self.message, self.reasons = status, message, reasons or []


def _edit(name: str, fn: Callable[[Project], Any]) -> Project:
    with jobs.project_lock(name):
        p = store.load(name)
        fn(p)
        store.save(name, p)
    return p


class Runner:
    def __init__(self, ctl: Control, job: Optional[jobs.Job] = None, echo: Callable[[str], None] | None = None):
        self.ctl, self.name, self.job, self.echo = ctl, ctl.name, job, echo

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
        if self.ctl.want == "stop":
            raise _Halt("stopped", "중지했습니다")
        if self.ctl.want == "pause":
            raise _Halt("paused", "일시정지했습니다")
        if jobs.draining.is_set():
            raise _Halt(None, "서버를 다시 시작한 뒤 이어 갑니다")

    def call(self, stage: str, n: int, fn: Callable[[Any], Any]) -> tuple[Any, dict]:
        """stage 의 백엔드로 fn(llm) 을 부르고 (결과, 토큰과 시간) 을 돌려준다. 배치가 켜져 있으면 배치로."""
        with usage.scope(project=self.name, episode=n, source="autorun", task="auto"):
            return self._call(stage, n, fn)

    def _call(self, stage: str, n: int, fn: Callable[[Any], Any]) -> tuple[Any, dict]:
        llm = get_llm(stage)
        use_batch = self.run.batch and hasattr(llm, "batch_submit")
        if use_batch:
            llm = BatchLLM(llm, f"{n}:{stage}", self.run.batches, self.ctl.save, self.ctl.wait,
                           label=f"canon {self.name}", note=lambda m: self.log(f"{n}화 {STEP_NAMES[stage]}: {m}", "warn"))
        t = time.time()
        try:
            out = fn(llm)
        except SchemaMismatch as e:
            # 본문은 그대로 두고 이 화에서 멈춘다. 이어 가면 이 단계만 새로 요청한다
            raise _Halt("paused", f"{n}화 {STEP_NAMES[stage]} 응답이 형식에 맞지 않아 멈췄습니다", [
                f"{n}화 {STEP_NAMES[stage]}: 다시 요청해도 모델 응답이 {e.schema} 형식과 맞지 않았습니다 ({e.brief})",
                "쓴 본문은 그대로 있습니다. 이어 가면 이 단계만 다시 요청합니다"
                + (". 배치에서 되풀이되면 배치를 끄고 이어 가 보세요" if use_batch else ""),
            ])
        except Interrupted as e:
            if e.cancelled:
                raise _Halt("stopped", "중지했습니다 (기다리던 배치 작업을 취소)")
            if self.ctl.want == "pause":
                raise _Halt("paused", "일시정지했습니다. 배치 작업은 계속 돌고, 이어 가면 결과를 받아 옵니다")
            raise _Halt(None, "서버를 다시 시작한 뒤 배치 결과를 이어 받습니다")
        u = getattr(llm, "last_usage", None) or {}
        tin = int(u.get("prompt_tokens") or 0)
        tout = int(u.get("completion_tokens") or 0) + int(u.get("thought_tokens") or 0)
        c = stage_cost(stage, tin, tout, use_batch)
        with self.ctl.lock:
            self.run.tokens_in += tin
            self.run.tokens_out += tout
            if c:
                self.run.cost = round(self.run.cost + c, 4)
        return out, dict(step=stage, tokens_in=tin, tokens_out=tout, seconds=round(time.time() - t, 1), batch=use_batch)

    def loop(self) -> None:
        run = self.run
        try:
            while True:
                self._checkpoint()
                p = store.load(self.name)
                todo = _todo(p, run.target)
                if not todo:
                    raise _Halt("done", f"{run.target}화까지 모두 반영했습니다")
                n = todo[0]
                if self.job is not None:
                    self.job.done = max(0, self.job.total - len(todo))
                try:
                    e = p.episode(n)
                except KeyError:
                    raise _Halt("paused", f"{n}화 플롯이 없습니다", [f"{n}화 플롯이 없습니다. 플롯을 만들고 확정한 뒤 이어 가세요"])
                if e.status == "draft":
                    if not run.policy.confirm_plots:
                        raise _Halt("paused", f"{n}화 플롯이 초안입니다",
                                    [f"{n}화 플롯이 아직 초안입니다. 확정한 뒤 이어 가세요 (또는 '초안 플롯 자동 확정'을 켜세요)"])
                    _edit(self.name, lambda q: setattr(q.episode(n), "status", "confirmed"))
                    self._set(n, "confirm")
                    self.log(f"{n}화 플롯을 자동으로 확정했습니다")
                    continue
                if e.status == "confirmed":
                    self._write(p, n)
                    continue
                self._review(p, n)
        except _Halt as h:
            self._finish(h)
        except Exception as e:  # 화면과 로그에 그대로 보여 준다
            msg = getattr(e, "message", None) or str(e) or type(e).__name__
            hint = " 배치를 끄고 이어 가 보세요." if run.batch and "batch" in msg.lower() else ""
            self._finish(_Halt("error", f"오류로 멈췄습니다: {msg}{hint}"), level="error")

    def _write(self, p: Project, n: int) -> None:
        self._set(n, "write")
        self.log(f"{n}화 본문을 쓰는 중" + (" (배치)" if self.run.batch and batchable("write") else ""))
        text, usage = self.call("write", n, lambda llm: pipeline.write_episode(llm, p, n))

        def put(q: Project) -> None:
            ep = q.episode(n)
            if ep.status != "confirmed":
                raise _Halt("paused", f"{n}화 상태가 바뀌어 멈춥니다 (현재: {ep.status})")
            ep.text, ep.status = text, "written"
        q = _edit(self.name, put)
        self.log(f"{n}화 본문 {len(text):,}자", **usage)
        _, drift = pipeline.style_drift(q, n)
        for w in drift[:3]:
            self.log(f"문체: {w}", "warn")
        if prompts.is_opening(n):
            for w in pipeline.opening_metrics(q, n)[1][:3]:
                self.log(f"초반: {w}", "warn")

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
                    _edit(self.name, lambda q: pipeline.apply_check(q, results["check"][0]))
                # 한쪽만 멈춤 요청을 받았으면 다른 쪽(기다리는 배치)도 같은 이유로 멈춘다
                raise next((e for e in errors if not isinstance(e, _Halt)), errors[0])
        delta: StateDelta = results["state"][0]
        report: Optional[ConsistencyReport] = results["check"][0] if "check" in results else None
        self.log(f"{n}화 상태 변경안: 인물 {len(delta.character_updates)}, 사건 {len(delta.events)}, "
                 f"사실 {len(delta.new_facts)}", **results["state"][1])
        if report is not None:
            _edit(self.name, lambda q: pipeline.apply_check(q, report))
            self.log(f"{n}화 검수: 어긋난 곳 {len(report.issues)}개", "warn" if report.issues else "info",
                     **results["check"][1])
        p = store.load(self.name)
        reasons = review_reasons(p, delta, report, run.policy)
        if reasons:
            with self.ctl.lock:
                run.pending = delta
            raise _Halt("review", f"{n}화는 검토가 필요해 멈췄습니다", reasons)

        def put(q: Project) -> None:
            if q.episode(n).status != "written":
                raise _Halt("paused", f"{n}화 상태가 바뀌어 멈춥니다 (현재: {q.episode(n).status})")
            pipeline.apply_delta(q, delta)
            q.episode(n).auto = True
        _edit(self.name, put)
        with self.ctl.lock:
            run.applied.append(n)
        self._set(n, "applied")
        self.log(f"{n}화를 자동으로 반영했습니다")
        every = run.policy.review_every
        if every and len(run.applied) % every == 0 and _todo(store.load(self.name), run.target):
            raise _Halt("paused", f"{every}화마다 멈추도록 설정해 멈췄습니다",
                        [f"{every}화마다 검토하도록 설정했습니다. 읽어 보고 이어 가세요"])

    def _finish(self, h: _Halt, level: str = "info") -> None:
        with self.ctl.lock:
            if h.status is not None:
                self.run.status = h.status  # type: ignore[assignment]
                self.run.reasons = h.reasons
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
        raise ValueError("자동 집필이 이미 돌고 있습니다")


def _control(name: str, run: Run) -> Control:
    with _lock:
        ctl = _controls.get(name)
        if ctl and ctl.thread_alive:
            raise ValueError("자동 집필이 이미 돌고 있습니다. 일시정지나 중지 후 다시 시작하세요")
        ctl = Control(name, run)
        _controls[name] = ctl
    return ctl


def start(name: str, target: int, batch: bool, policy: Policy, *, foreground: bool = False,
          echo: Callable[[str], None] | None = None) -> Run:
    """새 실행을 시작한다. 지난 실행의 로그는 이어 붙이고, 기다리던 배치나 검토 대기는 버린다."""
    p = store.load(name)
    if not 1 <= target <= max(p.meta.target_episodes, 1):
        raise ValueError(f"목표 화수는 1~{p.meta.target_episodes}화 사이여야 합니다")
    if active(name):
        raise ValueError("자동 집필이 이미 돌고 있습니다. 일시정지나 중지 후 다시 시작하세요")
    old = load_run(name)
    if old and old.batches:
        _cancel_batches(old)
    run = Run(target=target, batch=batch, policy=policy, started=_now(), log=old.log if old else [])
    ctl = _control(name, run)
    ctl.save()
    Runner(ctl).log(f"{target}화까지 자동 집필을 시작합니다 (배치 {'켬' if batch else '끔'})")
    _launch(name, ctl, echo, foreground)
    return ctl.run


def resume(name: str, approve: bool = False, rewrite: bool = False, *, foreground: bool = False,
           echo: Callable[[str], None] | None = None) -> Run:
    """멈춘 실행을 이어 간다. 검토 대기 중이면 approve 는 변경안을 그대로 반영하고, rewrite 는 그 화를 다시 쓴다.
    사용자가 검토 화면에서 직접 반영했으면 둘 다 없이 이어 가면 된다."""
    run = get_run(name)
    if run is None:
        raise ValueError("이어 갈 자동 집필이 없습니다")
    ctl = _control(name, run)
    r = Runner(ctl)
    if run.status == "review" and run.ep is not None:
        n = run.ep
        status = store.load(name).episode(n).status
        if status == "written" and approve and run.pending is not None:
            d = run.pending
            _edit(name, lambda q: pipeline.apply_delta(q, d))
            r.log(f"{n}화 변경안을 검토 화면 없이 그대로 반영했습니다 (사용자 승인)")
        elif status == "written" and rewrite:
            def back(q: Project) -> None:
                ep = q.episode(n)
                ep.text, ep.status, ep.issues = "", "confirmed", []
            _edit(name, back)
            r.log(f"{n}화를 다시 씁니다")
        elif status == "written":
            raise ValueError(f"{n}화 변경안이 검토 대기 중입니다. 검토 화면에서 반영하거나, 그대로 반영 또는 다시 쓰기를 고르세요")
    with ctl.lock:
        run.status, run.reasons, run.pending = "running", [], None
        ctl.save()
    r.log("이어 갑니다")
    _launch(name, ctl, echo, foreground)
    return run


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
        raise ValueError("자동 집필이 없습니다")
    if what == "stop":
        _cancel_batches(run)
        run.status, run.pending, run.reasons = "stopped", None, []
        _write(name, run)
    return run


def set_batch(name: str, on: bool) -> Run:
    """배치를 켜거나 끈다. 돌고 있으면 다음 단계부터 적용된다. 기다리던 배치는 그대로 받아 온다."""
    run = get_run(name)
    if run is None:
        raise ValueError("자동 집필이 없습니다")
    with _lock:
        ctl = _controls.get(name)
    run.batch = on
    if ctl:
        ctl.save()
        Runner(ctl).log(f"배치를 {'켰' if on else '껐'}습니다. 다음 단계부터 적용됩니다")
    else:
        _write(name, run)
    return run


def _cancel_batches(run: Run) -> None:
    """기다리던 배치 작업을 취소한다. 이미 끝났거나 키가 없어 취소하지 못해도 목록은 비운다."""
    for slot, bname in list(run.batches.items()):
        try:
            get_llm(slot.split(":")[1]).batch_cancel(bname)  # type: ignore[attr-defined]  # "<화>:<단계>[:fix]"
        except Exception:
            pass
    run.batches = {}


def resume_all() -> list[str]:
    """서버가 시작할 때 진행 중이던 실행을 다시 띄운다 (배치 작업에 다시 붙는다)."""
    out = []
    if not store.ROOT.exists():
        return out
    for d in sorted(store.ROOT.iterdir()):
        run = load_run(d.name) if (d / "autorun.json").exists() else None
        if run and run.status == "running" and store.exists(d.name):
            ctl = _control(d.name, run)
            Runner(ctl).log("서버가 다시 시작돼 이어 갑니다")
            _launch(d.name, ctl)
            out.append(d.name)
    return out


def progress_mark(p: Project) -> tuple:
    """상태 반영 진행을 나타내는 값. 화면이 가진 작품과 디스크가 다르면 화면이 오래된 것이다."""
    return tuple(d.episode for d in p.history), len(p.events), tuple(s.episode for s in p.snapshots)


PROGRESS_FIELDS = ("states", "relationships", "ties", "secrets", "events", "facts", "foreshadows", "history", "snapshots")


def protected(name: str, disk: Project, mine: Project) -> None:
    """화면이 작품 전체를 저장할 때, 자동 집필이 도는 중이거나 화면이 반영 진행을 모르는(오래된) 상태면
    진행 상태(인물 상태, 관계, 사건, 스냅샷 등)와 본문이 있는 화는 디스크 것을 지킨다.
    아직 안 쓴 화의 플롯과 다른 설정은 화면 것을 쓴다."""
    if not active(name) and progress_mark(disk) == progress_mark(mine):
        return
    for f in PROGRESS_FIELDS:
        setattr(mine, f, getattr(disk, f))
    run = get_run(name)
    cur = run.ep if run and active(name) else None
    d = {e.plot.number: e for e in disk.episodes}
    m = {e.plot.number: e for e in mine.episodes}
    body = ("written", "finalized")
    for n, e in d.items():
        if e.status in body or n == cur or (n in m and m[n].status in body):
            m[n] = e
    mine.episodes = [m[k] for k in sorted(m)]

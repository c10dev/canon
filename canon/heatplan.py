"""열 계획: 화마다 긴장과 보상(열)을 얼마나, 어떤 몫으로 쓰나.

기승전결이 '무슨 일이 일어나나'를 정하면, 열 계획은 '열을 언제 아끼고 언제 쓰나'를 정한다.
단편은 작품 전체에 계획 하나(`Project.heat` · `heat_rule` · `heat_turn`)를 둔다. 장편 아크는 아직 계획을 갖지 않는다.
경고 · 화면 · 프롬프트는 형식을 가리지 않고 `plan` · `step` · `turn` 으로 찾는다.
경고와 실제 열 재기는 AI 를 부르지 않고, 막지 않는다.
"""
from __future__ import annotations

import re
from statistics import mean, pstdev

from . import foreshadows
from .schema import CueSheet, EpisodePlot, Foreshadow, HeatActual, HeatStep, HeatTurn, HeatWarn, Project

LEVEL_MIN, LEVEL_MAX = 0, 5
FILL_LEVEL = 2  # 계획에 빠진 화를 채우는 눈금
FILL_ROLE = "build"
ROLES = {"build": "쌓기", "hold": "미루기", "peak": "터뜨리기", "after": "뒷날", "rest": "쉬기"}
KINDS = foreshadows.KINDS


def plan(p: Project) -> list[HeatStep]:
    """이 작품의 열 계획. 장편은 아직 빈 목록."""
    return [] if p.serial else p.heat


def step(p: Project, n: int) -> HeatStep | None:
    """n화의 열 계획 한 줄. 계획이 없거나 그 화가 계획에 없으면 None."""
    return next((s for s in plan(p) if s.ep == n), None)


def turn(p: Project) -> HeatTurn | None:
    """뒤집힘. 정하지 않았으면 None."""
    t = None if p.serial else p.heat_turn
    return t if t and t.plant_ep > 0 else None


def _eps(eps: list[int]) -> str:
    return " · ".join(map(str, eps)) + "화"


def fit(steps: list[HeatStep], start: int, end: int) -> tuple[list[HeatStep], list[str]]:
    """start~end 화를 빈틈없이 덮는 계획으로 고친다. 범위 밖 화와 같은 화의 두 번째 줄은 버리고,
    빠진 화는 FILL_LEVEL · FILL_ROLE 로 채운다. 눈금은 0~5 로 자르고, 터뜨리기가 아닌 화의 정점 종류는 지운다.
    빈 계획은 그대로 둔다(계획을 쓰지 않음). 고친 것은 화면 문구로 돌려준다."""
    if not steps:
        return [], []
    notes: list[str] = []
    seen: dict[int, HeatStep] = {}
    outside: list[int] = []
    for s in steps:
        if not start <= s.ep <= end:
            outside.append(s.ep)
        elif s.ep not in seen:
            level = min(max(s.level, LEVEL_MIN), LEVEL_MAX)
            seen[s.ep] = s.model_copy(update={"level": level, "kind": s.kind.strip() if s.role == "peak" else ""})
    if outside:
        notes.append(f"범위({start}~{end}화) 밖의 {_eps(sorted(set(outside)))}를 열 계획에서 뺐어요")
    missing = [n for n in range(start, end + 1) if n not in seen]
    for n in missing:
        seen[n] = HeatStep(ep=n, level=FILL_LEVEL, role=FILL_ROLE)
    if missing:
        notes.append(f"열 계획에 없던 {_eps(missing)}를 열 {FILL_LEVEL} · {ROLES[FILL_ROLE]}로 채웠어요")
    return [seen[n] for n in range(start, end + 1)], notes


def fit_turn(t: HeatTurn, start: int, end: int) -> tuple[HeatTurn, list[str]]:
    """뒤집힘이 범위 안에 있고 심은 화가 들킨 화보다 앞서지 않으면 그대로, 아니면 비운다."""
    if t.plant_ep <= 0:
        return HeatTurn(), []
    if start <= t.plant_ep <= t.fail_ep <= end:
        return t, []
    return HeatTurn(), [f"뒤집힘({t.plant_ep}화에 심고 {t.fail_ep}화에 들킴)이 {start}~{end}화 안에 차례로 놓이지 않아 뺐어요"]


# ---------- 경고 (AI 없음, 막지 않음) ----------

CV_MIN = 0.5  # 열 눈금 변동계수가 이보다 작으면 기복이 작다 (subway 0.61 · 경멸 1.07 을 보고 정한 임시 값)
FLAT_MIN_EPS = 4  # 이보다 짧은 계획은 기복을 보지 않는다
EARLY_SHARE = 0.3  # 작품 앞 이 몫 안의 터뜨리기는 이르다
HOT_CUE = 4  # 쌓기 · 쉬기 화에 이 긴장도 이상 큐가 있으면 경고
WARN_CODES = {
    "flat": "기복이 작음",
    "early_peak": "이른 정점",
    "no_stake": "판돈 없는 정점",
    "no_pressure": "관객 · 제약 없는 정점",
    "same_kind": "같은 종류 정점",
    "same_stake": "커지지 않은 판돈",
    "no_aftermath": "관객이 본 일의 결과 없음",
    "late_turn": "늦은 뒤집힘",
    "hot_cue": "쌓기 화의 높은 긴장",
}


def peak_runs(steps: list[HeatStep]) -> list[list[HeatStep]]:
    """잇닿은 터뜨리기 화를 한 정점으로 묶는다 (경멸 9~13화처럼 정점이 여러 화에 걸친다)."""
    runs: list[list[HeatStep]] = []
    for s in sorted(steps, key=lambda s: s.ep):
        if s.role != "peak":
            continue
        if runs and runs[-1][-1].ep == s.ep - 1:
            runs[-1].append(s)
        else:
            runs.append([s])
    return runs


def _plot(p: Project, n: int) -> EpisodePlot | None:
    return next((e.plot for e in p.episodes if e.plot.number == n), None)


def _paid(p: Project, run: list[HeatStep], fs: dict[str, Foreshadow], kinds: set[str]) -> set[str]:
    """정점 화들의 플롯이 회수하는 복선 가운데 그 갈래인 것."""
    out: set[str] = set()
    for s in run:
        plot = _plot(p, s.ep)
        out |= {i for i in (plot.foreshadow_payoff if plot else []) if i in fs and fs[i].kind in kinds}
    return out


def _kind(run: list[HeatStep]) -> str:
    return next((re.sub(r"\s+", " ", s.kind).strip() for s in run if s.kind.strip()), "")


def warnings(p: Project) -> list[HeatWarn]:
    """열 계획과 플롯 · 복선 · 큐 시트를 견준 경고. 계획이 없으면 빈 목록."""
    steps = plan(p)
    if not steps:
        return []
    out: list[HeatWarn] = []

    def warn(ep: int, code: str, text: str) -> None:
        out.append(HeatWarn(ep=ep, code=code, text=text))

    fs = {f.id: f for f in p.foreshadows}
    levels = [s.level for s in steps]
    if len(steps) >= FLAT_MIN_EPS:
        cv = pstdev(levels) / mean(levels) if mean(levels) else 0.0
        if cv < CV_MIN:
            warn(0, "flat", f"열 눈금의 기복이 작아요 (변동계수 {cv:.2f}, {CV_MIN} 이상을 권해요). 아끼는 화와 터뜨리는 화의 차이를 키워 보세요")
    total = max(p.meta.target_episodes, max(s.ep for s in steps))
    gi = next((a for a in p.arc if a.name == "기"), None)
    runs = peak_runs(steps)
    for run in runs:
        for s in run:
            if s.ep <= total * EARLY_SHARE or (gi and gi.start_ep <= s.ep <= gi.end_ep):
                warn(s.ep, "early_peak", f"{s.ep}화의 터뜨리기가 일러요. 앞쪽은 쌓기 · 미루기로 열을 아껴요")
        first = run[0].ep
        if not any(f.kind == "stake" and f.planted_ep < first and (f.status == "open" or (f.payoff_ep or 0) >= first)
                   for f in p.foreshadows):
            warn(first, "no_stake", f"{first}화 정점 전에 심은 판돈(stake)이 없어요. 잃을 수 있는 것을 앞 화에 심어 보세요")
        for s in run:
            plot = _plot(p, s.ep)
            if plot and not _paid(p, [s], fs, {"audience", "constraint"}):
                warn(s.ep, "no_pressure", f"{s.ep}화 플롯이 거두는 관객(audience)이나 제약(constraint) 복선이 없어요")
    seen: dict[str, int] = {}
    for run in runs:
        k = _kind(run)
        if k and k in seen:
            warn(run[0].ep, "same_kind", f"{run[0].ep}화 정점이 {seen[k]}화 정점과 종류가 같아요 ({k}). 정점마다 종류를 바꿔 보세요")
        seen.setdefault(k, run[0].ep)
    if len(runs) >= 2:
        last = _paid(p, runs[-1], fs, {"stake"})
        before = set().union(*(_paid(p, r, fs, {"stake"}) for r in runs[:-1]))
        if last and last <= before:
            warn(runs[-1][0].ep, "same_stake", f"{runs[-1][0].ep}화 큰 정점의 판돈이 앞 정점과 같아요. 남에게 드러나는 쪽으로 키워 보세요")
    shown: set[str] = set()  # 관객을 처음 거둔 화만 본다. 결과를 다룬 다음 화가 또 거둬도 그다음 화를 요구하지 않는다
    for e in sorted(p.episodes, key=lambda e: e.plot.number):
        first = [i for i in e.plot.foreshadow_payoff if i in fs and fs[i].kind == "audience" and i not in shown]
        shown.update(first)
        nxt = _plot(p, e.plot.number + 1)
        if not nxt:
            continue
        nxt_text = " ".join([nxt.summary, *nxt.events, *nxt.foreshadow_payoff])
        for i in first:
            if i not in nxt_text:
                warn(nxt.number, "no_aftermath", f"{e.plot.number}화에서 거둔 관객 '{fs[i].description}'이 본 일의 결과가 {nxt.number}화 플롯에 없어요")
    t = turn(p)
    if t and runs and t.fail_ep >= runs[-1][0].ep:
        warn(t.fail_ep, "late_turn", f"반격이 {t.fail_ep}화에 들켜요. 큰 정점({runs[-1][0].ep}화) 전에 들켜야 판돈이 커져요")
    for s in steps:
        sheet = next((e.cue_sheet for e in p.episodes if e.plot.number == s.ep), None)
        if s.role in ("build", "rest") and sheet and any(c.tension >= HOT_CUE for c in sheet.cues):
            warn(s.ep, "hot_cue", f"{s.ep}화는 {ROLES[s.role]} 화인데 큐 시트에 긴장도 {HOT_CUE} 이상 큐가 있어요")
    return sorted(out, key=lambda w: w.ep)


def warnings_for(p: Project, n: int) -> list[HeatWarn]:
    """n화를 가리키는 경고와 계획 전체 경고."""
    return [w for w in warnings(p) if w.ep in (0, n)]


# ---------- 실제 열 재기 (AI 없음, 참고값) ----------

def density(text: str, words: list[str]) -> float | None:
    """열 낱말 수 / 공백 뺀 1천 자. 낱말이 없거나 본문이 없으면 None."""
    words = [w.strip() for w in words if w.strip()]
    chars = len(re.sub(r"\s", "", text))
    if not words or not chars:
        return None
    return round(sum(text.count(w) for w in words) * 1000 / chars, 2)


def cue_tension(sheet: CueSheet | None) -> float | None:
    """큐 긴장도를 목표 글자 수로 가중한 평균. 글자 수가 모두 0 이면 큐마다 같은 무게."""
    cues = sheet.cues if sheet and not sheet.skipped else []
    if not cues:
        return None
    weights = [c.length for c in cues] if any(c.length > 0 for c in cues) else [1] * len(cues)
    total = sum(max(w, 0) for w in weights)
    return round(sum(min(max(c.tension, 1), 5) * max(w, 0) for c, w in zip(cues, weights)) / total, 2) if total else None


def actual(p: Project) -> list[HeatActual]:
    """본문이 있는 화마다 실제 열 참고값."""
    out = []
    for e in sorted(p.episodes, key=lambda e: e.plot.number):
        if not e.text:
            continue
        out.append(HeatActual(ep=e.plot.number, density=density(e.text, p.settings.heat_words), tension=cue_tension(e.cue_sheet)))
    return out

"""작품 정착 문체: 작가가 고른 반영한 화를 이 작품의 문체 기준으로 고정한다 (Project.anchor, StyleAnchor).

레퍼런스는 작품이 따라갈 목표이고, 정착 문체는 작품이 1~몇 화에서 실제로 굳힌 목소리다. 기준이 있으면
문체 지표 · 경고(pipeline.style_baseline · style_drift)와 쓰기 프롬프트의 문체 예시(prompts.style_passages)가 이것을 본다.
라이브러리에는 올리지 않는다 (library.push_project 는 p.style 만 올린다).

흐름 경고는 한 화가 아니라 최근 화 평균(rolling)으로 본다. 사람이 쓴 웹소설 4편(1,532화)을 1~5화 기준으로 쟀더니
80화쯤까지 0.1~0.2 멀어진 뒤 0.85~1.05 에 머물렀고, 다른 작품 화까지는 평균 1.33 이었다 (reports/문체 흐름 실측 2026-11-02.md).
그래서 연재하며 생기는 흐름(HUMAN_BAND)은 경고하지 않고, 다른 작가 쪽에 가까워질 때(DRIFT_WARN) 알린다.
LLM 호출 없음.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from statistics import mean
from typing import Optional

from . import metrics, prompts
from .llm import dump
from .schema import Project, StyleAnchor, StyleMarker

PICK = 5            # 처음 추천하는 정착 화 수
WINDOW = 5          # 흐름을 보는 최근 화 수
MIN_WINDOW = 3      # 이만큼 모이기 전에는 흐름 평균을 내지 않는다
LATER = 10          # 잴 때 '고른 화 뒤 화'로 보는 화 수
DRIFT_WARN = 1.15   # 최근 화 평균이 이를 넘으면 경고. 사람 연재의 흐름(≤1.05)과 다른 작품(평균 1.33) 사이
HUMAN_BAND = (0.85, 1.05)  # 사람 웹소설이 80화 뒤 머문 범위 (추이 그래프의 띠)
OTHER_AUTHOR = 1.33        # 사람 웹소설 다른 작품끼리의 평균 거리
MIN_CHARS = metrics.STYLE_CHUNK * metrics.STYLE_MIN_CHUNKS  # 문체 거리 기준을 만들 수 있는 가장 짧은 원문
MAX_PASSAGES = 4
PASSAGE_MIN, PASSAGE_MAX = 150, 900  # 대표 문단 글자 수
CANDIDATE_TARGET = 450               # 후보 문단 묶음의 목표 글자 수


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def voiced(p: Project, n: int) -> bool:
    """시점 인물의 서술 말투로 쓴 화. 어미가 기준과 달라야 맞으므로 정착 화로도, 흐름으로도 세지 않는다."""
    c = prompts.pov_character(p, n)
    return c is not None and bool(c.narration_voice.strip())


def _text(p: Project, n: int) -> str:
    e = next((x for x in p.episodes if x.plot.number == n), None)
    return e.text if e else ""


def usable(p: Project) -> list[int]:
    """정착 화로 고를 수 있는 화: 상태 반영이 끝났고(작가가 승인한 본문), 본문이 있고, 서술 말투 화가 아닌 화."""
    return [e.plot.number for e in sorted(p.episodes, key=lambda x: x.plot.number)
            if e.status == "finalized" and e.text.strip() and not voiced(p, e.plot.number)]


def suggest(p: Project) -> list[int]:
    """처음 추천: 고를 수 있는 앞 화 PICK 개. 작가가 확정하기 전에는 저장하지 않는다."""
    return usable(p)[:PICK]


def basis(p: Project, episodes: list[int]) -> str:
    """고른 화 본문의 지문. 화가 없어지거나 본문을 고치면 달라진다. 화 번호만 옮기면(renumber) 그대로다."""
    h = hashlib.sha1()
    for n in sorted(episodes):
        h.update(f"{_text(p, n)}\n\0".encode("utf-8"))
    return h.hexdigest()[:16]


def stale(p: Project) -> bool:
    """정착 화 본문이 잰 뒤로 바뀌었는지 (고침, 지움, 갈래에서 비움)."""
    return p.anchor is not None and basis(p, p.anchor.episodes) != p.anchor.basis


def joined(p: Project, episodes: list[int]) -> str:
    return "\n\n".join(_text(p, n).strip() for n in sorted(episodes) if _text(p, n).strip())


def _check(p: Project, episodes: list[int]) -> list[int]:
    eps = sorted(dict.fromkeys(episodes))
    if not eps:
        raise ValueError("이 작품의 문체로 쓸 화를 하나 넘게 골라 주세요")
    ok = set(usable(p))
    bad = [n for n in eps if n not in ok]
    if bad:
        raise ValueError(f"{', '.join(f'{n}화' for n in bad)}는 고를 수 없어요. 상태 반영이 끝났고 서술 말투가 없는 화만 고를 수 있어요")
    chars = len(joined(p, eps))
    if chars < MIN_CHARS:
        raise ValueError(f"고른 화가 {chars:,}자예요. 문체 거리를 재려면 {MIN_CHARS:,}자 넘게 골라 주세요")
    return eps


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _later(p: Project, base: metrics.StyleMetrics, episodes: list[int]) -> Optional[float]:
    after = [n for n in usable(p) if n > max(episodes)][:LATER]
    ds = [d for n in after if (d := metrics.style_distance(base, _text(p, n))) is not None]
    return round(mean(ds), 2) if ds else None


def measure(p: Project, episodes: list[int], passages: list[str] | None = None) -> StyleAnchor:
    """고른 화로 정착 문체를 잰다. 저장하지 않는다. 대표 문단은 고른 화 본문에 글자 그대로(공백 빼고) 있어야 한다."""
    eps = _check(p, episodes)
    text = joined(p, eps)
    keep = []
    flat = _norm(text)
    for s in passages or []:
        s = s.strip()
        if not s:
            continue
        if not PASSAGE_MIN <= len(s) <= PASSAGE_MAX:
            raise ValueError(f"대표 문단은 {PASSAGE_MIN}~{PASSAGE_MAX}자로 골라 주세요 ({len(s)}자: '{s[:20]}…')")
        if _norm(s) not in flat:
            raise ValueError(f"대표 문단은 고른 화 본문에서 그대로 가져와야 해요: '{s[:20]}…'")
        keep.append(s)
    if len(keep) > MAX_PASSAGES:
        raise ValueError(f"대표 문단은 {MAX_PASSAGES}개까지 고를 수 있어요")
    base = metrics.measure(text, p.style.banned_phrases)
    marks = [StyleMarker(text=m.text, note=m.note, per_1k=metrics.marker_rate(text, m.text))
             for m in p.style.markers if m.text.strip()]
    return StyleAnchor(episodes=eps, basis=basis(p, eps), metrics=base, markers=marks, passages=keep,
                       later=_later(p, base, eps), at=_now())


def set_anchor(p: Project, episodes: list[int], passages: list[str] | None = None) -> StyleAnchor:
    p.anchor = measure(p, episodes, passages)
    return p.anchor


def clear(p: Project) -> None:
    p.anchor = None


def markers(p: Project) -> list[StyleMarker]:
    """문체 표지와 빈도: 프로필 표지마다 정착 문체에서 센 빈도가 있으면 그 빈도, 없으면 프로필(원문) 빈도.
    잰 뒤에 더한 표지는 프로필 빈도를 쓴다."""
    if p.anchor is None:
        return p.style.markers
    rate = {m.text: m.per_1k for m in p.anchor.markers}
    return [m.model_copy(update={"per_1k": rate[m.text]}) if m.text in rate else m for m in p.style.markers]


def candidates(p: Project, episodes: list[int], limit: int = 6) -> list[str]:
    """대표 문단 후보: 고른 화마다 문단을 CANDIDATE_TARGET 자 안팎으로 묶고, 문장 길이와 대사 비율이
    정착 기준(고른 화 전체)에 가장 가까운 묶음을 하나씩 고른다. 대사 위주 · 서술 위주가 섞이게 둘씩 고른 화도 있다."""
    eps = _check(p, episodes)
    base = metrics.measure(joined(p, eps))
    scored: list[tuple[float, int, str, bool]] = []
    for n in eps:
        cur, blocks = "", []
        for para in (x.strip() for x in re.split(r"\n+", _text(p, n))):
            if not para:
                continue
            cur = f"{cur}\n\n{para}" if cur else para
            if len(cur) >= CANDIDATE_TARGET:
                if len(cur) <= PASSAGE_MAX:
                    blocks.append(cur)
                cur = ""
        for b in blocks:
            m = metrics.measure(b)
            if m.sentences < 3:
                continue
            gap = abs(m.sentence_len_mean - base.sentence_len_mean) / max(base.sentence_len_mean, 1)
            gap += abs(m.dialogue_ratio - base.dialogue_ratio)
            scored.append((gap, n, b, m.dialogue_ratio >= max(base.dialogue_ratio, 0.2)))
    out: list[tuple[int, str]] = []
    for want in (True, False):  # 대사 위주 하나, 서술 위주 하나를 먼저
        pick = next((x for x in sorted(scored) if x[3] == want), None)
        if pick:
            out.append((pick[1], pick[2]))
    for gap, n, b, _ in sorted(scored):
        if len(out) >= limit:
            break
        if b not in (x[1] for x in out) and sum(1 for x in out if x[0] == n) < 1:
            out.append((n, b))
    return [b for _, b in sorted(out)]


# ---------- 흐름 ----------

def distance(p: Project, n: int) -> Optional[float]:
    """n화 본문이 정착 문체에서 떨어진 거리. 기준이 없거나 거리 기준이 없으면 None."""
    a = p.anchor
    if a is None or a.metrics is None:
        return None
    return metrics.style_distance(a.metrics, _text(p, n))


def _counted(p: Project, n: int) -> bool:
    return bool(_text(p, n).strip()) and not voiced(p, n) and not (p.anchor and n in p.anchor.episodes)


def rolling(p: Project, n: int) -> Optional[float]:
    """n화까지 본문이 있는 최근 WINDOW 화(서술 말투 화 · 정착 화 빼고)의 평균 거리. MIN_WINDOW 화가 모이지 않으면 None."""
    if p.anchor is None or p.anchor.metrics is None:
        return None
    nums = sorted(e.plot.number for e in p.episodes if e.plot.number <= n and _counted(p, e.plot.number))[-WINDOW:]
    ds = [d for x in nums if (d := distance(p, x)) is not None]
    return round(mean(ds), 2) if len(ds) >= MIN_WINDOW else None


def warning(p: Project, n: int) -> str:
    """흐름 경고 한 줄. 서술 말투 화에는 내지 않는다."""
    if voiced(p, n):
        return ""
    r = rolling(p, n)
    if r is None or r <= DRIFT_WARN:
        return ""
    return (f"이 작품의 문체에서 멀어짐: 최근 {WINDOW}화 평균 {r} (사람 연재는 {HUMAN_BAND[0]}~{HUMAN_BAND[1]}에 머물고, "
            f"다른 작품 글은 평균 {OTHER_AUTHOR}, {DRIFT_WARN} 넘으면 알려요)")


def style_basis(p: Project) -> str:
    """지금 쓰기에 쓰는 문체(스타일 프로필 + 정착 대표 문단)의 지문. 추이 그래프가 문체를 바꾼 화를 표시한다."""
    passages = p.anchor.passages if p.anchor else []
    return hashlib.sha1(dump({"style": p.style.model_dump(), "passages": passages}).encode("utf-8")).hexdigest()[:10]


def stamp(p: Project, n: int) -> None:
    """AI 가 쓴 본문을 저장할 때 부른다. 그때의 문체 지문을 화에 남긴다."""
    p.episode(n).style_basis = style_basis(p)


def trend(p: Project) -> list[dict]:
    """본문이 있는 화마다 정착 문체 거리와 최근 화 평균. 문체를 바꾼 화(changed)는 앞 화와 문체 지문이 다른 화."""
    out, last = [], ""
    for e in sorted(p.episodes, key=lambda x: x.plot.number):
        n = e.plot.number
        if not e.text.strip():
            continue
        v = voiced(p, n)
        changed = bool(e.style_basis and last and e.style_basis != last)
        last = e.style_basis or last
        out.append({"n": n, "distance": None if v else distance(p, n), "rolling": rolling(p, n), "voiced": v,
                    "anchor": bool(p.anchor and n in p.anchor.episodes), "auto": e.auto, "changed": changed})
    return out


def view(p: Project) -> dict:
    """문체 화면의 정착 문체 카드 값."""
    a = p.anchor
    ref = p.style_baseline or (metrics.measure("\n\n".join(p.style.sample_passages)) if p.style.sample_passages else None)

    def brief(m: metrics.StyleMetrics | None) -> dict | None:
        if m is None or not m.chars:
            return None
        return {"chars": m.chars, "sentence_len": m.sentence_len_mean, "dialogue_ratio": m.dialogue_ratio,
                "past_tense_ratio": m.past_tense_ratio, "distance_ready": bool(m.style_centroid)}

    return {
        "anchor": None if a is None else {"episodes": a.episodes, "passages": a.passages, "later": a.later, "at": a.at,
                                          "stale": stale(p), "metrics": brief(a.metrics)},
        "reference": brief(ref),
        "usable": usable(p), "suggest": suggest(p), "trend": trend(p),
        "window": WINDOW, "warn": DRIFT_WARN, "band": list(HUMAN_BAND), "other": OTHER_AUTHOR, "min_chars": MIN_CHARS,
        "per_episode_warn": metrics.STYLE_DISTANCE_WARN,
    }


def move(p: Project, f, gone: int = 0) -> None:
    """화 번호를 옮길 때 (renumber.move_points). 빠진 화는 정착 화에서 빼고, 그러면 지문이 달라져 화면이 다시 재라고 알린다."""
    if p.anchor is None:
        return
    p.anchor.episodes = sorted(f(n) for n in p.anchor.episodes if n != gone)

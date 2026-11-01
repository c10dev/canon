"""쓰기 블록 시험 (명령줄 blocktrial): 같은 화를 쓰기 프롬프트의 블록 하나만 빼거나 바꿔 써 보고 쇠맛 지표로 견준다.

새 블록을 쓰기 프롬프트에 넣을지 검수 쪽에 둘지 데이터로 정하려고 둔다 (쇠맛 연구 2026-10-30).
반영이 끝난 화 n 마다 작품 사본을 메모리에서 n-1 화로 되돌리고(stattrial.before), 조건마다 사본을 바꿔 n 화를 쓴다.
작품에는 저장하지 않는다. 화마다 조건별 첫 안을 블라인드 비교본(research.save_compare, kind blocks)으로 남긴다.

채점은 LLM 을 부르지 않는다: 쇠맛 패턴 · 상투 표현 · 쉼표 문장 비율 · 문장 평균 길이 · 반복 구 · 문체 거리(기준 원문),
설계 메모(감정 변화 · 스토리보드 장면 메모 · 큐의 일)를 옮긴 문장(pipeline.memo_copied), 예시 문단을 옮긴 문장.
"""
from __future__ import annotations

from datetime import date
from typing import Callable

from . import cancel, metrics, pipeline, prompts, research, usage
from .context import CHARS_PER_TOKEN
from .schema import Project
from .stattrial import before

# 조건: (화면 이름, 설명, 사본 바꾸기, write_episode 인자)
_STYLE_TEXT = ("narration_pov", "tense", "sentence_rhythm", "description_density", "dialogue_ratio", "dialogue_style",
               "inner_monologue", "pacing", "scene_transition", "vocabulary")


def _same(q: Project) -> None:
    return None


def _no_profile(q: Project) -> None:
    for k in _STYLE_TEXT:
        setattr(q.style, k, "")
    q.style.dos, q.style.donts = [], []


def _no_relations(q: Project) -> None:
    q.ties, q.relationships = [], []


def _no_address(q: Project) -> None:
    q.address_forms = []


def _no_knows(q: Project) -> None:
    for s in q.states:
        s.knows = []


CONDITIONS: dict[str, tuple[str, str, Callable[[Project], None], dict]] = {
    "base": ("지금 쓰기 프롬프트", "아무것도 빼지 않아요.", _same, {}),
    "no_board": ("스토리보드 빼기", "그 화에 스토리보드가 있어도 넣지 않아요 (직전 화도 끝부분만).", _same, {"use_board": False}),
    "no_cues": ("큐 시트 빼기", "그 화에 큐 시트가 있어도 넣지 않아요.", _same, {"use_cues": False}),
    "no_profile": ("스타일 프로필 글 빼기", "스타일 프로필의 글 칸과 지킬 것 · 피할 것을 비워요. 예시 문단 · 금지 표현은 그대로예요.", _no_profile, {}),
    "no_relations": ("관계 블록 빼기", "인물 사이 관계 줄을 넣지 않아요.", _no_relations, {}),
    "no_address": ("호칭 블록 빼기", "호칭 · 말씨 줄을 넣지 않아요.", _no_address, {}),
    "no_knows": ("아는 정보 빼기", "인물 상태의 아는 정보를 넣지 않아요.", _no_knows, {}),
}
MAX_WRITES = 60  # 한 번에 쓰는 본문 수 상한 (비용 사고 막기)


def variant(p: Project, cond: str) -> tuple[Project, dict]:
    if cond not in CONDITIONS:
        raise ValueError(f"알 수 없는 조건: {cond} ({' | '.join(CONDITIONS)})")
    q = p.model_copy(deep=True)
    CONDITIONS[cond][2](q)
    return q, CONDITIONS[cond][3]


def candidates(p: Project) -> list[int]:
    """시험할 수 있는 화: 반영이 끝났고 직전 화 스냅샷이 있는 화."""
    return [e.plot.number for e in sorted(p.episodes, key=lambda x: x.plot.number)
            if e.status == "finalized" and p.snapshot(e.plot.number - 1) is not None]


def default_pick(cands: list[int], k: int = 8) -> list[int]:
    """뒤쪽 화(블록이 가장 큰 화)부터 k 개."""
    return sorted(cands[-k:])


def prompt_size(q: Project, n: int, kw: dict) -> int:
    """쓰기 요청 글자 수 (시스템 지시 포함)."""
    return len(prompts.writer_system(q)) + len(prompts.episode_prompt(q, n, **kw))


def score(q: Project, n: int, text: str) -> dict:
    """본문 하나 채점 (LLM 없음). q 는 n 화를 쓰기 직전 사본."""
    m = metrics.measure(text, q.style.banned_phrases)
    k = max(len(text), 1) / 1000
    patterns = sum(v for name, v in metrics.pattern_counts(text).items() if name != "서식 흔적")
    return {"chars": len(text), "pattern_per_1k": round(patterns / k, 3), "cliche_per_1k": round(len(m.cliche_hits) / k, 3),
            "comma_ratio": m.comma_sentence_ratio, "sentence_mean": m.sentence_len_mean, "repeated": len(m.repeated_phrases),
            "style_distance": metrics.style_distance(pipeline.style_baseline(q), text),
            "memo_copied": len(pipeline.memo_copied(q, n, text)),
            "sample_copied": len(metrics.copied_sentences(text, q.style.sample_passages))}


def estimate(p: Project, episodes: list[int], repeats: int = 1, conditions: list[str] | None = None,
             model: str = "", batch: bool = False) -> dict:
    """쓰기 호출 수와 비용 추정. 입력은 조건마다 실제 요청 글자 수로, 출력은 화당 분량으로 잰다(글자 ÷ CHARS_PER_TOKEN)."""
    from . import settings

    conditions = conditions or ["base"]
    model = model or settings.stage_model("write")[0] or settings.model()[0]
    price = usage.rate(model, date.today().isoformat())
    out_tokens = p.meta.words_per_episode / CHARS_PER_TOKEN
    rows, total = [], 0.0
    for cond in conditions:
        sizes = [prompt_size(q, n, kw) for n in episodes for q, kw in [variant(before(p, n), cond)]]
        tin = sum(sizes) / CHARS_PER_TOKEN * repeats
        tout = out_tokens * len(episodes) * repeats
        c = usage.cost(price, tin, tout, 0, batch) if price else None
        total += c or 0
        rows.append({"condition": cond, "label": CONDITIONS[cond][0], "writes": len(episodes) * repeats,
                     "input_tokens": round(tin), "output_tokens": round(tout), "usd": round(c, 3) if c is not None else None})
    return {"model": model, "priced": price is not None, "batch": batch, "writes": sum(r["writes"] for r in rows),
            "usd": round(total, 3) if price else None, "rows": rows,
            "note": "입력은 실제 요청 글자 수, 출력은 화당 분량을 글자당 토큰 추정값으로 나눠 셌어요. 생각 토큰과 캐시는 넣지 않았어요."}


def run(name: str, p: Project, llm, episodes: list[int], repeats: int = 1, conditions: list[str] | None = None,
        progress=None) -> dict:
    """시험을 돌리고 research/log.jsonl 에 남긴다 (kind blocks). progress(done, total, note) 는 진행률용."""
    conditions = conditions or ["base"]
    bad = [c for c in conditions if c not in CONDITIONS]
    if bad:
        raise ValueError(f"알 수 없는 조건: {', '.join(bad)} ({' | '.join(CONDITIONS)})")
    ok = set(candidates(p))
    bad_eps = [n for n in episodes if n not in ok]
    if bad_eps:
        raise ValueError(f"시험할 수 없는 화예요: {', '.join(map(str, bad_eps))}화 (반영이 끝나고 직전 화 스냅샷이 있어야 해요)")
    if not 1 <= repeats <= 5:
        raise ValueError("반복은 1~5번이에요")
    total = len(episodes) * repeats * len(conditions)
    if not total or total > MAX_WRITES:
        raise ValueError(f"한 번에 쓰는 본문은 1~{MAX_WRITES}개예요 (지금 {total}개)")
    drafts, done = [], 0
    for n in episodes:
        base = before(p, n)
        first: dict[str, str] = {}
        for cond in conditions:
            q, kw = variant(base, cond)
            size = prompt_size(q, n, kw)
            for r in range(repeats):
                cancel.check()
                if progress:
                    progress(done, total, f"{n}화 · {CONDITIONS[cond][0]} · {r + 1}번")
                text = pipeline.write_episode(llm, q, n, **kw)
                first.setdefault(cond, text)
                drafts.append({"episode": n, "condition": cond, "repeat": r + 1, "prompt_chars": size, **score(q, n, text)})
                done += 1
        if len(first) > 1:
            research.save_compare(name, n, first, kind="blocks", models=dict.fromkeys(first, pipeline.writer_of(llm)))
    res = {"episodes": episodes, "repeats": repeats, "conditions": conditions, "drafts": drafts, "summary": summary(drafts)}
    return research.record(name, "blocks", res)


_KEYS = ("prompt_chars", "chars", "pattern_per_1k", "cliche_per_1k", "comma_ratio", "sentence_mean", "repeated",
         "style_distance", "memo_copied", "sample_copied")


def summary(drafts: list[dict]) -> list[dict]:
    """조건마다 지표 평균. 값이 없는 지표(짧은 글의 문체 거리 등)는 있는 것만으로."""
    out = []
    for cond in dict.fromkeys(d["condition"] for d in drafts):
        xs = [d for d in drafts if d["condition"] == cond]
        row = {"condition": cond, "label": CONDITIONS.get(cond, (cond,))[0], "drafts": len(xs)}
        for k in _KEYS:
            vals = [d[k] for d in xs if d.get(k) is not None]
            row[k] = round(sum(vals) / len(vals), 3) if vals else None
        out.append(row)
    return out


def describe(res: dict) -> str:
    """명령줄 출력."""
    def f(v, fmt):
        return "-" if v is None else format(v, fmt)
    return "\n".join(
        f"{s['label']:14s} 본문 {s['drafts']}개 · 요청 {f(s['prompt_chars'], ',.0f')}자 · 쇠맛 {f(s['pattern_per_1k'], '.2f')}/1k"
        f" · 상투 {f(s['cliche_per_1k'], '.2f')}/1k · 쉼표 문장 {f(s['comma_ratio'], '.2f')} · 문장 {f(s['sentence_mean'], '.1f')}자"
        f" · 반복 구 {f(s['repeated'], '.1f')} · 문체 거리 {f(s['style_distance'], '.2f')} · 메모 옮김 {f(s['memo_copied'], '.1f')}"
        f" · 예시 옮김 {f(s['sample_copied'], '.1f')}"
        for s in res["summary"])

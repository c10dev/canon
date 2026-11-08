"""쓰기 블록 시험 (명령줄 blocktrial): 같은 화를 쓰기 프롬프트의 블록 하나만 빼거나 바꿔 써 보고 쇠맛 지표로 견준다.

새 블록을 쓰기 프롬프트에 넣을지 검수 쪽에 둘지 데이터로 정하려고 둔다 (쇠맛 연구 2026-10-30).
반영이 끝난 화 n 마다 작품 사본을 메모리에서 n-1 화로 되돌리고(stattrial.before), 조건마다 사본을 바꿔 n 화를 쓴다.
작품에는 저장하지 않는다. 화마다 조건별 첫 안을 블라인드 비교본(research.save_compare, kind blocks)으로 남긴다.

채점은 LLM 을 부르지 않는다: 쇠맛 패턴 · 상투 표현 · 쉼표 문장 비율 · 문장 평균 길이 · 반복 구 · 문체 거리(기준 원문),
설계 메모(감정 변화 · 스토리보드 장면 메모 · 큐의 일)를 옮긴 문장(pipeline.memo_copied), 예시 문단을 옮긴 문장.
이름이 fs_ 로 시작하는 조건(열린 복선 블록 줄이기 확인 (나), spec 10)은 본문마다 같은 llm 으로 복선 판정을 한 번 불러 모순 · 미리 회수 수를 센다.
"""
from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager, nullcontext
from datetime import date
from typing import Callable, Iterator, Optional

from . import cancel, metrics, pipeline, prompts, research, usage
from .schema import ForeshadowBreaks, Project
from .stattrial import before

# 조건: (화면 이름, 설명, 사본 바꾸기, write_episode 인자, 문맥 고리)
# 문맥 고리는 그 조건의 쓰기 요청(write_episode · episode_prompt)을 감싼다. ContextVar 로만 바꿀 수 있는 것(열린 복선 꼴)에 쓴다
_STYLE_TEXT = ("narration_pov", "tense", "sentence_rhythm", "description_density", "dialogue_ratio", "dialogue_style",
               "inner_monologue", "pacing", "scene_transition", "vocabulary", "sound_effects")


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
        s.knows, s.knows_folded = [], []  # 접은 줄도 knows.view 가 '(요약)' 으로 넣는다
    q.knows_folds = []


def _foreshadow_json(on: bool) -> Callable[[], AbstractContextManager]:
    """장편 쓰기의 열린 복선 꼴을 고르는 문맥 고리 (prompts.FORESHADOW_JSON). 참이면 예전 JSON, 거짓이면 한 줄 꼴."""
    @contextmanager
    def hook() -> Iterator[None]:
        token = prompts.FORESHADOW_JSON.set(on)
        try:
            yield
        finally:
            prompts.FORESHADOW_JSON.reset(token)
    return hook


Hook = Optional[Callable[[], AbstractContextManager]]
CONDITIONS: dict[str, tuple[str, str, Callable[[Project], None], dict, Hook]] = {
    "base": ("지금 쓰기 프롬프트", "아무것도 빼지 않아요.", _same, {}, None),
    "no_board": ("스토리보드 빼기", "그 화에 스토리보드가 있어도 넣지 않아요 (직전 화도 끝부분만).", _same, {"use_board": False}, None),
    "no_cues": ("큐 시트 빼기", "그 화에 큐 시트가 있어도 넣지 않아요.", _same, {"use_cues": False}, None),
    "no_profile": ("스타일 프로필 글 빼기", "스타일 프로필의 글 칸과 지킬 것 · 피할 것을 비워요. 예시 문단 · 금지 표현은 그대로예요.", _no_profile, {}, None),
    "no_relations": ("관계 블록 빼기", "인물 사이 관계 줄을 넣지 않아요.", _no_relations, {}, None),
    "no_address": ("호칭 블록 빼기", "호칭 · 말씨 줄을 넣지 않아요.", _no_address, {}, None),
    "no_knows": ("아는 정보 빼기", "인물 상태의 아는 정보를 넣지 않아요.", _no_knows, {}, None),
    "fs_json": ("열린 복선 JSON", "장편 쓰기의 열린 복선을 예전처럼 JSON 으로 넣어요 (줄이기 전).", _same, {}, _foreshadow_json(True)),
    "fs_line": ("열린 복선 한 줄", "장편 쓰기의 열린 복선을 설명 전부와 함께 한 줄씩 넣어요 (지금 방식).", _same, {}, _foreshadow_json(False)),
}
FS_PAIR = ("fs_json", "fs_line")  # 두 조건의 쓰기 요청이 같은 화는 건너뛴다
MAX_WRITES = 60  # 한 번에 쓰는 본문 수 상한 (비용 사고 막기)
JUDGE_OUTPUT_TOKENS = 400  # 복선 판정 응답 토큰 어림 (estimate). 어긴 곳 몇 개를 적는 짧은 JSON


def judged(cond: str) -> bool:
    """본문마다 복선 판정을 부르는 조건인지 (이름이 fs_ 로 시작)."""
    return cond.startswith("fs_")


def hook(cond: str) -> AbstractContextManager:
    """그 조건의 쓰기 요청을 감쌀 문맥. 고리가 없으면 아무것도 하지 않는다."""
    h = CONDITIONS[cond][4]
    return h() if h else nullcontext()


def write_request(q: Project, n: int, cond: str, kw: dict) -> str:
    """그 조건의 쓰기 요청 전체 (시스템 지시 + 본문 쓰기 요청). 고리 안에서 만든다."""
    with hook(cond):
        return prompts.writer_system(q) + "\n\n" + prompts.episode_prompt(q, n, **kw)


def same_fs(base: Project, n: int, conditions: list[str]) -> bool:
    """fs_json · fs_line 을 함께 고른 화에서 두 조건의 쓰기 요청이 글자까지 같은지 (단편 화는 같다: 장편 쓰기 블록을 쓰지 않음)."""
    if not set(FS_PAIR) <= set(conditions):
        return False
    a, b = (write_request(q, n, c, kw) for c in FS_PAIR for q, kw in [variant(base, c)])
    return a == b


def plan(p: Project, episodes: list[int], conditions: list[str]) -> tuple[list[tuple[int, list[str]]], list[dict]]:
    """화마다 쓸 조건과 건너뛴 화. 두 fs_ 조건의 요청이 같은 화는 그 둘만 뺀다."""
    out, skipped = [], []
    for n in episodes:
        conds = list(conditions)
        if same_fs(before(p, n), n, conditions):
            conds = [c for c in conds if c not in FS_PAIR]
            skipped.append({"episode": n, "conditions": list(FS_PAIR),
                            "note": f"{n}화는 단편 화라 두 조건의 쓰기 요청이 같아서 건너뛰었어요."})
        out.append((n, conds))
    return out, skipped


def judge(llm, q: Project, n: int, text: str) -> dict:
    """복선 판정 한 번 (같은 llm, prompts.foreshadow_judge_prompt). 어긴 곳과 kind 별 수."""
    fs, _ = prompts.relevant_foreshadows(q, n)
    try:
        pays = q.episode(n).plot.foreshadow_payoff
    except KeyError:
        pays = []
    rep = llm.json(prompts.SYSTEM_CHECKER, prompts.foreshadow_judge_prompt(q, n, text), ForeshadowBreaks,
                   hint={"ids": [f.id for f in fs], "pays": list(pays), "text": text})
    breaks = [b.model_dump() for b in rep.items]
    return {"breaks": breaks, "contradictions": sum(b["kind"] == "모순" for b in breaks),
            "early_payoffs": sum(b["kind"] == "미리 회수" for b in breaks)}


def variant(p: Project, cond: str) -> tuple[Project, dict]:
    if cond not in CONDITIONS:
        raise ValueError(f"알 수 없는 조건: {cond} ({' | '.join(CONDITIONS)})")
    q = p.model_copy(deep=True)
    CONDITIONS[cond][2](q)
    return q, dict(CONDITIONS[cond][3])


def candidates(p: Project) -> list[int]:
    """시험할 수 있는 화: 반영이 끝났고 직전 화 스냅샷이 있는 화."""
    return [e.plot.number for e in sorted(p.episodes, key=lambda x: x.plot.number)
            if e.status == "finalized" and p.snapshot(e.plot.number - 1) is not None]


def default_pick(cands: list[int], k: int = 8) -> list[int]:
    """뒤쪽 화(블록이 가장 큰 화)부터 k 개."""
    return sorted(cands[-k:])


def prompt_size(q: Project, n: int, kw: dict, cond: str = "base") -> int:
    """쓰기 요청 글자 수 (시스템 지시 포함). cond 의 문맥 고리 안에서 잰다."""
    with hook(cond):
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
            "sample_copied": len(metrics.copied_sentences(text, q.style.sample_passages)),
            "speech_copied": len(pipeline.speech_copied(q, text))}


def estimate(p: Project, episodes: list[int], repeats: int = 1, conditions: list[str] | None = None,
             model: str = "", batch: bool = False) -> dict:
    """쓰기 호출 수와 비용 추정. 입력은 조건마다 실제 요청 글자 수로, 출력은 화당 분량으로 잰다(usage.token_rate 의 글자 → 토큰 직선)."""
    from . import settings

    conditions = conditions or ["base"]
    model = model or settings.stage_model("write")[0] or settings.model()[0]
    price = usage.rate(model, date.today().isoformat())
    backend, stage_model = usage.stage_llm("write")
    rate = usage.token_rate(backend if model == stage_model else "", model)  # 고른 모델이 단계 모델과 다르면 이름으로 백엔드를 고른다
    out_tokens = usage.est_output(p.meta.words_per_episode, rate)
    steps, skipped = plan(p, episodes, conditions)
    rows, total = [], 0.0
    for cond in conditions:
        eps = [n for n, conds in steps if cond in conds]
        qs = [(q, n, kw) for n in eps for q, kw in [variant(before(p, n), cond)]]
        # prompt_size 는 시스템 지시를 품는다. 직선의 붙는 토큰이 시스템 지시를 이미 세므로 빼고 넘긴다
        tin = sum(usage.est_input(prompt_size(q, n, kw, cond) - (sys := len(prompts.writer_system(q))), rate, sys)
                  for q, n, kw in qs) * repeats
        tout = out_tokens * len(eps) * repeats
        jin = jout = 0.0
        if judged(cond):  # 판정 요청: 본문 자리는 화당 분량으로 센다
            jin = sum(usage.est_input(len(prompts.foreshadow_judge_prompt(q, n, "")) + p.meta.words_per_episode, rate,
                                      len(prompts.SYSTEM_CHECKER)) for q, n, _ in qs) * repeats
            jout = JUDGE_OUTPUT_TOKENS * len(eps) * repeats
        c = usage.cost(price, tin + jin, tout + jout, 0, batch) if price else None
        total += c or 0
        rows.append({"condition": cond, "label": CONDITIONS[cond][0], "writes": len(eps) * repeats,
                     "input_tokens": round(tin), "output_tokens": round(tout),
                     "judge_input_tokens": round(jin), "judge_output_tokens": round(jout),
                     "usd": round(c, 3) if c is not None else None})
    return {"model": model, "priced": price is not None, "batch": batch, "writes": sum(r["writes"] for r in rows),
            "usd": round(total, 3) if price else None, "rows": rows, "skipped": skipped,
            "note": "입력은 실제 요청 글자 수, 출력은 화당 분량에 백엔드 · 모델별 글자당 토큰 추정값을 곱해 셌어요. 생각 토큰과 캐시는 넣지 않았어요."
                    " 복선 판정(fs_ 조건)은 본문을 화당 분량으로, 응답을 판정마다 %d토큰으로 어림해 비용에 더했어요." % JUDGE_OUTPUT_TOKENS}


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
    steps, skipped = plan(p, episodes, conditions)
    total = sum(len(conds) for _, conds in steps) * repeats
    if not total and skipped:
        raise ValueError("고른 화 모두 두 조건(fs_json · fs_line)의 쓰기 요청이 같아요. 장편 화를 골라 주세요")
    if not total or total > MAX_WRITES:
        raise ValueError(f"한 번에 쓰는 본문은 1~{MAX_WRITES}개예요 (지금 {total}개)")
    drafts, done = [], 0
    try:
        for n, conds in steps:
            base = before(p, n)
            first: dict[str, str] = {}
            for cond in conds:
                q, kw = variant(base, cond)
                size = prompt_size(q, n, kw, cond)
                for r in range(repeats):
                    cancel.check()
                    if progress:
                        progress(done, total, f"{n}화 · {CONDITIONS[cond][0]} · {r + 1}번")
                    with hook(cond):
                        text = pipeline.write_episode(llm, q, n, **kw)
                    first.setdefault(cond, text)
                    draft = {"episode": n, "condition": cond, "repeat": r + 1, "prompt_chars": size, **score(q, n, text)}
                    drafts.append(draft)  # 판정이 실패해도 쓴 본문의 지표는 남긴다
                    done += 1
                    if judged(cond):
                        cancel.check()
                        draft.update(judge(llm, q, n, text))
            if len(first) > 1:
                research.save_compare(name, n, first, kind="blocks", models=dict.fromkeys(first, pipeline.writer_of(llm)))
    except BaseException as e:  # 멈추거나 한 번 실패해도 그때까지 쓴 본문(돈 든 결과)은 남긴다
        if drafts:
            research.record(name, "blocks", {"episodes": episodes, "repeats": repeats, "conditions": conditions, "drafts": drafts,
                                            "summary": summary(drafts), "skipped": skipped,
                                            "stopped": research.stopped_note(done, total, e)})
        raise
    res = {"episodes": episodes, "repeats": repeats, "conditions": conditions, "drafts": drafts, "summary": summary(drafts),
           "skipped": skipped}
    return research.record(name, "blocks", res)


_KEYS = ("prompt_chars", "chars", "pattern_per_1k", "cliche_per_1k", "comma_ratio", "sentence_mean", "repeated",
         "style_distance", "memo_copied", "sample_copied", "speech_copied", "contradictions", "early_payoffs")


def summary(drafts: list[dict]) -> list[dict]:
    """조건마다 지표 평균. 값이 없는 지표(짧은 글의 문체 거리, 판정하지 않은 조건의 모순 수 등)는 있는 것만으로.
    contradictions · early_payoffs 는 본문 하나당 복선 '모순' · '미리 회수' 수다 (fs_ 조건만)."""
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
    def fs(s):
        if s.get("contradictions") is None and s.get("early_payoffs") is None:
            return ""
        return f" · 복선 모순 {f(s.get('contradictions'), '.2f')}/화 · 미리 회수 {f(s.get('early_payoffs'), '.2f')}/화"
    lines = [
        f"{s['label']:14s} 본문 {s['drafts']}개 · 요청 {f(s['prompt_chars'], ',.0f')}자 · 쇠맛 {f(s['pattern_per_1k'], '.2f')}/1k"
        f" · 상투 {f(s['cliche_per_1k'], '.2f')}/1k · 쉼표 문장 {f(s['comma_ratio'], '.2f')} · 문장 {f(s['sentence_mean'], '.1f')}자"
        f" · 반복 구 {f(s['repeated'], '.1f')} · 문체 거리 {f(s['style_distance'], '.2f')} · 메모 옮김 {f(s['memo_copied'], '.1f')}"
        f" · 예시 옮김 {f(s['sample_copied'], '.1f')} · 말투 예시 옮김 {f(s.get('speech_copied'), '.1f')}{fs(s)}"
        for s in res["summary"]]
    return "\n".join(lines + [x["note"] for x in res.get("skipped", [])])

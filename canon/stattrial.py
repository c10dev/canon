"""상태창 넣기 시험 (연구 화면): 같은 화를 상태창 수치를 넣는 방식(stat_window.prompt)만 바꿔 써 보고 견준다.

조건은 none(넣지 않음) · json(지금 방식, 인물 상태 안에 그대로) · lines(이번 화 인물만 줄 형식과 도감 줄)이다.
반영이 끝난 화 n 마다 작품 사본을 메모리에서 n-1 화로 되돌리고(pipeline.revert), 그 상태로 조건마다 n 화를 쓴다.
작품에는 저장하지 않는다. 블라인드 고르기용으로 조건마다 첫 안을 비교본(research.save_compare, kind statwin)으로 남긴다.

채점은 LLM 을 부르지 않는다. 기준은 원래 반영 기록(stat_log)이다:
- 그 화에 바뀌지 않은 항목이 본문에 다른 값으로 나오면 '바뀌지 않을 값 오류'
- 그 화에 바뀐 항목이 직전 값도 바뀐 값도 아니면 '바뀔 값 오류'
- 저장한 서식으로 읽은 상태창에 기록에 없는 항목이 있으면 '없던 항목'
- 플롯에 상태창 장면이 없는데 상태창 블록이 나오면 '남용'
"""
from __future__ import annotations

import re
from datetime import date

from . import cancel, metrics, pipeline, prompts, research, statwin, usage
from .context import CHARS_PER_TOKEN
from .schema import Project

CONDITIONS: dict[str, str] = {"none": "상태창 없음", "json": "지금 방식", "lines": "고른 줄 형식"}
ABOUT: dict[str, str] = {
    "none": "쓰기 요청에 상태창 수치와 상태창 규칙을 넣지 않아요.",
    "json": "지금처럼 인물 상태 안에 수치를 그대로 넣고, 매 화 상태창 서식 예시를 붙여요.",
    "lines": "이번 화 인물의 수치만 한 줄씩, 가진 스킬은 도감 한 줄로 넣어요. 서식 예시는 플롯에 상태창 장면이 있을 때만 붙여요.",
}
MAX_WRITES = 120  # 한 번에 쓰는 본문 수 상한 (비용 사고 막기)
_SEP = r"[:：┃|│]"


def variant(p: Project, cond: str) -> Project:
    if cond not in CONDITIONS:
        raise ValueError(f"알 수 없는 조건: {cond} ({' | '.join(CONDITIONS)})")
    q = p.model_copy(deep=True)
    q.stat_window.prompt = cond  # type: ignore[assignment]
    return q


def before(p: Project, n: int) -> Project:
    """n 화를 쓰기 직전 상태의 사본. 작품은 그대로다."""
    q = p.model_copy(deep=True)
    if n > 1 or q.snapshot(0) is not None:
        pipeline.revert(q, n - 1)
    return q


def changes(p: Project, n: int) -> dict[tuple[str, str], tuple[str, str]]:
    """원래 반영에서 n 화에 바뀐 상태창 항목: {(인물, 항목): (직전 값, 바뀐 값)}."""
    out: dict[tuple[str, str], tuple[str, str]] = {}
    for r in p.stat_log:
        if r.episode == n:
            k = (r.character_id, r.name)
            out[k] = (out[k][0] if k in out else r.before, r.value)
    return out


def candidates(p: Project) -> list[dict]:
    """시험할 수 있는 화: 반영이 끝났고 직전 화 스냅샷이 있는 화. 수치가 바뀐 화인지, 플롯에 상태창 장면이 있는지."""
    out = []
    for e in sorted(p.episodes, key=lambda x: x.plot.number):
        n = e.plot.number
        if e.status != "finalized" or p.snapshot(n - 1) is None:
            continue
        out.append({"episode": n, "title": e.plot.title, "changed": bool(changes(p, n)), "wants": statwin.wants_window(p, n)})
    return out


def default_pick(cands: list[dict], k: int = 12) -> list[int]:
    """수치가 바뀐 화와 바뀌지 않은 화를 반씩, 상태창 장면이 있는 화를 먼저."""
    def take(xs: list[dict], m: int) -> list[int]:
        xs = sorted(xs, key=lambda c: (not c["wants"], c["episode"]))
        return [c["episode"] for c in xs[:m]]
    ch = [c for c in cands if c["changed"]]
    un = [c for c in cands if not c["changed"]]
    a = take(ch, k // 2)
    b = take(un, k - len(a))
    a += take([c for c in ch if c["episode"] not in a], k - len(a) - len(b))
    return sorted(a + b)


def _shown(q: Project, text: str) -> list[tuple[str, str, str, str]]:
    """본문에 나온 상태창 값: [(인물, 항목, 값, 원문 줄)]. 서식과 상관없이 '항목: 값' · '항목 ┃ 값' 꼴의 줄을 읽는다.
    인물은 상태창이 있는 인물이 하나면 그 인물, 여럿이면 가장 최근에 이름이 나온 줄의 인물(없으면 첫 인물)."""
    stats = {s.character_id: [x.name for x in s.stats] for s in q.states if s.stats}
    if not stats:
        return []
    names = {c.id: c.name for c in q.characters if c.id in stats and c.name}
    pats = {cid: re.compile(r"^[\s\-•·▸▶◆*\[【<〈]*(" + "|".join(map(re.escape, sorted(ns, key=len, reverse=True))) + r")\s*" + _SEP + r"\s*(.+?)\s*[\]】>〉]*$")
            for cid, ns in stats.items() if ns}
    cur = next(iter(stats))
    out = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        hit = next((cid for cid, nm in names.items() if nm in s), None)
        if hit and len(stats) > 1:
            cur = hit
        m = pats.get(cur).match(s) if cur in pats else None
        if m:
            out.append((cur, m.group(1), m.group(2), s))
    return out


def score(q: Project, n: int, text: str, ref: dict[tuple[str, str], tuple[str, str]]) -> dict:
    """본문 하나 채점 (LLM 없음). q 는 n 화를 쓰기 직전 사본, ref 는 원래 반영의 바뀐 항목(changes)."""
    pre = {(s.character_id, x.name): x.value for s in q.states for x in s.stats}
    wrong_unchanged, wrong_changed, samples = 0, 0, []
    shown = _shown(q, text)
    for cid, key, val, line in shown:
        if (cid, key) in ref:
            b, a = ref[(cid, key)]
            ok = (b and statwin.same(val, b)) or (a and statwin.same(val, a))
            if not ok:
                wrong_changed += 1
                samples.append(f"«{line}» 기록: {b or '없음'} → {a or '지움'}")
        elif (cid, key) in pre and not statwin.same(val, pre[(cid, key)]):
            wrong_unchanged += 1
            samples.append(f"«{line}» 기록: {pre[(cid, key)]} (이 화에 바뀌지 않음)")
    wins = statwin.read_windows(q, text)
    known = {k for (_, k) in pre} | {k for (_, k) in ref}
    invented = sorted({key for w in wins for key, _, _ in w["rows"] if key not in known})
    blocks = len(wins) or len(re.findall(r"^\s*[\[【<〈][^\]】>〉\n]*(?:상태창|" + re.escape(q.stat_window.title or "상태창") + r")[^\]】>〉\n]*[\]】>〉]\s*$", text, re.M))
    wants = statwin.wants_window(q, n)
    return {"chars": len(text), "shown": len(shown), "wrong_unchanged": wrong_unchanged, "wrong_changed": wrong_changed,
            "invented": invented, "windows": blocks, "wants": wants, "unwanted_windows": 0 if wants else blocks,
            "bracket_ratio": metrics.measure_opening(text, []).status_ratio if text.strip() else 0, "samples": samples[:5]}


def prompt_size(q: Project, n: int) -> int:
    """쓰기 요청 글자 수 (시스템 지시 포함)."""
    return len(prompts.writer_system(q)) + len(prompts.episode_prompt(q, n))


def estimate(p: Project, episodes: list[int], repeats: int = 1, conditions: list[str] | None = None,
             model: str = "", batch: bool = False) -> dict:
    """쓰기 호출 수와 비용 추정. 입력은 조건마다 실제 요청 글자 수로, 출력은 화당 분량으로 잰다(글자 ÷ CHARS_PER_TOKEN)."""
    conditions = conditions or list(CONDITIONS)
    from . import settings

    model = model or settings.stage_model("write")[0] or settings.model()[0]
    price = usage.rate(model, date.today().isoformat())
    out_tokens = p.meta.words_per_episode / CHARS_PER_TOKEN
    rows, total = [], 0.0
    for cond in conditions:
        sizes = [prompt_size(variant(before(p, n), cond), n) for n in episodes]
        tin = sum(sizes) / CHARS_PER_TOKEN * repeats
        tout = out_tokens * len(episodes) * repeats
        c = usage.cost(price, tin, tout, 0, batch) if price else None
        total += c or 0
        rows.append({"condition": cond, "label": CONDITIONS[cond], "writes": len(episodes) * repeats,
                     "input_tokens": round(tin), "output_tokens": round(tout), "usd": round(c, 3) if c is not None else None})
    return {"model": model, "priced": price is not None, "batch": batch, "writes": sum(r["writes"] for r in rows),
            "usd": round(total, 3) if price else None, "rows": rows,
            "note": "입력은 실제 요청 글자 수, 출력은 화당 분량을 글자당 토큰 추정값으로 나눠 셌어요. 생각 토큰과 캐시는 넣지 않았어요."}


def run(name: str, p: Project, llm, episodes: list[int], repeats: int = 1, conditions: list[str] | None = None,
        progress=None) -> dict:
    """시험을 돌리고 research/log.jsonl 에 남긴다. progress(done, total, note) 는 화면 진행률용."""
    conditions = conditions or list(CONDITIONS)
    ok = {c["episode"] for c in candidates(p)}
    bad = [n for n in episodes if n not in ok]
    if bad:
        raise ValueError(f"시험할 수 없는 화예요: {', '.join(map(str, bad))}화 (반영이 끝나고 직전 화 스냅샷이 있어야 해요)")
    if not 1 <= repeats <= 5:
        raise ValueError("반복은 1~5번이에요")
    total = len(episodes) * repeats * len(conditions)
    if not total or total > MAX_WRITES:
        raise ValueError(f"한 번에 쓰는 본문은 1~{MAX_WRITES}개예요 (지금 {total}개)")
    drafts, done = [], 0
    for n in episodes:
        base = before(p, n)
        ref = changes(p, n)
        first: dict[str, str] = {}
        for cond in conditions:
            q = variant(base, cond)
            size = prompt_size(q, n)
            for r in range(repeats):
                cancel.check()
                if progress:
                    progress(done, total, f"{n}화 · {CONDITIONS[cond]} · {r + 1}번")
                text = pipeline.write_episode(llm, q, n)
                first.setdefault(cond, text)
                drafts.append({"episode": n, "condition": cond, "repeat": r + 1, "prompt_chars": size,
                               "prompt_tokens": round(size / CHARS_PER_TOKEN), **score(q, n, text, ref)})
                done += 1
        research.save_compare(name, n, first, kind="statwin")
    res = {"episodes": episodes, "repeats": repeats, "conditions": conditions, "drafts": drafts, "summary": summary(drafts)}
    return research.record(name, "statwin", res)


def summary(drafts: list[dict]) -> list[dict]:
    """조건마다 합: 보인 값, 오류율, 없던 항목, 남용 상태창, 평균 요청 토큰 · 본문 글자."""
    out = []
    for cond in dict.fromkeys(d["condition"] for d in drafts):
        xs = [d for d in drafts if d["condition"] == cond]
        shown = sum(d["shown"] for d in xs)
        wrong = sum(d["wrong_unchanged"] + d["wrong_changed"] for d in xs)
        out.append({"condition": cond, "label": CONDITIONS.get(cond, cond), "drafts": len(xs), "shown": shown,
                    "wrong": wrong, "error_rate": round(wrong / shown, 3) if shown else None,
                    "invented": sum(len(d["invented"]) for d in xs), "windows": sum(d["windows"] for d in xs),
                    "unwanted_windows": sum(d["unwanted_windows"] for d in xs),
                    "prompt_tokens": round(sum(d["prompt_tokens"] for d in xs) / len(xs)),
                    "chars": round(sum(d["chars"] for d in xs) / len(xs))})
    return out


def describe(res: dict) -> str:
    """명령줄 출력."""
    rows = [f"{s['label']:8s} 본문 {s['drafts']}개 · 보인 값 {s['shown']} · 틀린 값 {s['wrong']}"
            + (f" ({s['error_rate']:.0%})" if s["error_rate"] is not None else "")
            + f" · 없던 항목 {s['invented']} · 상태창 {s['windows']} (플롯에 없던 것 {s['unwanted_windows']}) · 요청 약 {s['prompt_tokens']:,}토큰 · 본문 {s['chars']:,}자"
            for s in res["summary"]]
    return "\n".join(rows)

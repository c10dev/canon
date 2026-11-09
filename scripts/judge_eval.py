"""판단기 평가 세트 (두 걸음 검수의 판단기 칸: 진술 하나 + 근거 묶음 → 맞음 / 어긋남 / 없음).

build: 작품 사본으로 평가 줄(JSONL)을 만든다. 작품 폴더는 임시 폴더에 복사해서 쓰고, 원본은 바꾸지 않는다.
  plant     심은 모순(prompts.plant_prompt, LLM 호출). 바꾼 문장 → 정답 '어긋남'
  original  심기 전 문장 → 정답 'ok'(맞음 또는 없음)
  finding   고친 검수 지적(사실 · 시간 · 인물 정보 · 말투 · 세계관). 지적한 문장 → 정답 '어긋남'
  random    심지 않은 본문 문장 → 정답 'ok'. 아직 찾지 못한 모순이 드물게 섞일 수 있다
  줄마다 근거 묶음(prompts.claim_evidence, LLM 없음)과 has_source(심을 때 고른 어긋나는 원문이 근거 묶음에 들었는지)를 적는다.
  has_source 는 그 원문 하나만 본다. 다른 단락 · 확정 사실도 같은 모순의 근거가 될 수 있어, 거짓이어도 판단기가 찾을 수 있다.
  모순을 심은 화는 심기 전 · 뒤 본문에서 두 걸음 검수와 같은 진술 뽑기(claims_prompt)를 한 번씩 불러, 그 문장에서 뽑은
  진술(claim)로 근거를 찾는다. 뽑히지 않은 문장은 claimed 가 거짓이고 문장 그대로 쓴다. 고친 지적은 본문이 바뀌어 문장 그대로다.

run: 판단기(mock | local)로 평가 줄을 판정하고 문턱별 재현율과 헛지적률을 낸다.
  --blind 는 근거를 빼고 판정한다. 근거가 없으면 판단기는 대개 '없음'을 골라, 문장의 티를 보는지는 --shuffle 로 본다.
  --shuffle SEED 는 다른 화의 근거 묶음을 붙인다. 엉뚱한 근거로도 심은 문장을 '어긋남'으로 고르면 판단기가 문장의 티를 보는 것이다.

실행:
  CANON_USAGE=$PWD/projects/.usage/usage.jsonl python scripts/judge_eval.py build --src projects \\
      --project subway-1-수정본 --provider gemini --model gemini-3.8-flash --out reports/judge-eval/set.jsonl
  CANON_JUDGE_URL=http://127.0.0.1:18001/v1 python scripts/judge_eval.py run reports/judge-eval/set.jsonl --judge local
가짜 LLM 으로 흐름만: python scripts/judge_eval.py build --src <폴더> --project <이름> --provider mock --out /tmp/set.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from canon import context, prompts, store, usage  # noqa: E402
from canon.judge import Question, make_judge  # noqa: E402
from canon.research import Backend, make_backend  # noqa: E402
from canon.schema import Claim, ClaimSet, PlantSet, Project  # noqa: E402

FINDING_TYPES = {"사실", "시간", "인물 정보", "말투", "세계관"}  # 옛 화 · 설정과 견주는 갈래 (동선 · 시점 · 플롯은 판단기가 보지 않는다)
SOURCE_OVERLAP = 0.5  # 어긋나는 원문의 글 조각이 근거 묶음에 이만큼 있으면 근거에 든 것으로 센다 (research.HIT_OVERLAP 와 같은 값)
THRESHOLDS = (0.1, 0.25, 0.5, 0.75)
SENT_MIN, SENT_MAX = 15, 200
_SENT = re.compile(r"[^.!?…\n]+[.!?…]+[\"'”’」』)]*|[^.!?…\n]+$")


def sentences(text: str) -> list[str]:
    """본문 문장 (줄과 문장 부호로 나눔). 너무 짧거나 긴 문장은 뺀다."""
    out = []
    for line in text.splitlines():
        buf = ""
        for s in _SENT.findall(line):  # 짧은 조각(대사 뒤 '민재가 물었다.')은 앞 조각에 붙인다
            buf = f"{buf} {s.strip()}".strip()
            if len(buf) >= SENT_MIN:
                out.append(buf)
                buf = ""
        if buf and out and len(out[-1]) + len(buf) <= SENT_MAX:
            out[-1] = f"{out[-1]} {buf}"
    return [x for x in out if SENT_MIN <= len(x) <= SENT_MAX]


def has_source(source_quote: str, evidence: str) -> bool | None:
    """어긋나는 원문이 근거 묶음에 들었나. 원문이 비었거나 한글 조각이 없으면 None."""
    g = context.grams(source_quote)
    if not g:
        return None
    return len(context.grams(evidence) & g) / len(g) >= SOURCE_OVERLAP


def plant_episodes(p: Project, k: int) -> list[int]:
    """모순을 심을 화: 옛 화가 있는(직전 화들보다 앞선 화가 있는) 화 가운데 고르게 k 개."""
    ok = [e.plot.number for e in sorted(p.episodes, key=lambda e: e.plot.number)
          if e.text and any(o.text and o.plot.number < e.plot.number - context.CHECK_RECENT for o in p.episodes)]
    if k <= 0:
        return []
    if k >= len(ok):
        return ok
    step = len(ok) / k
    return [ok[int(i * step + step / 2)] for i in range(k)]


def match_claim(quote: str, claims: list[Claim]) -> Claim | None:
    """평가 문장과 같은 문장에서 뽑은 진술 (글 조각이 SOURCE_OVERLAP 넘게 겹치는 것 가운데 가장 많이 겹치는 것)."""
    g = context.grams(quote)
    if not g:
        return None
    best = max(claims, key=lambda c: len(context.grams(c.quote) & g), default=None)
    return best if best is not None and len(context.grams(best.quote) & g) / len(g) >= SOURCE_OVERLAP else None


def _row(p: Project, n: int, source: str, quote: str, label: str, index: context.PassageIndex,
         claims: list[Claim] | None = None, **kw) -> dict:
    """claims 를 주면(진술 뽑기를 돌린 화) 그 문장에서 뽑은 진술로 근거를 찾는다. 뽑히지 않았으면 claimed 가 거짓이고 문장 그대로 쓴다."""
    hit = match_claim(quote, claims) if claims is not None else None
    claim = Claim(quote=quote, claim=hit.claim if hit else quote)
    ev = prompts.claim_evidence(p, n, claim, index)
    sq = kw.get("source_quote", "")
    plain = prompts.claim_evidence(p, n, Claim(quote=quote, claim=quote), index) if hit else ev
    return {"episode": n, "source": source, "quote": quote, "claim": claim.claim, "label": label,
            "claimed": (hit is not None) if claims is not None else None,
            "type": kw.get("type", ""), "source_episode": kw.get("source_episode"), "source_quote": sq,
            "cross": kw.get("source_episode") != n if kw.get("source_episode") is not None else None,
            "has_source": has_source(sq, ev) if sq else None,
            "has_source_plain": has_source(sq, plain) if sq else None,  # 진술 대신 문장 그대로 찾았을 때
            "evidence": ev, **{k: v for k, v in kw.items() if k in ("seed", "part", "closed_by")}}


def _claims(llm, p: Project, name: str, n: int, text: str, task: str) -> list[Claim]:
    """두 걸음 검수 1단계와 같은 진술 뽑기 (본문을 text 로 바꾼 사본)."""
    q = p.model_copy(deep=True)
    q.episode(n).text = text
    with usage.scope(project=f"judge-eval:{name}", episode=n, task=task):
        got = llm.json(prompts.SYSTEM_CLAIMS, prompts.claims_prompt(q, n), ClaimSet, hint={"episode": n, "text": text}).claims
    return [c for c in got if c.quote.strip() and c.claim.strip()][:prompts.TWOSTEP_CLAIMS]


def build_project(p: Project, name: str, llm, episodes: list[int], plants: int, randoms: int, seed: int,
                  with_claims: bool = True) -> list[dict]:
    rows: list[dict] = []
    for n in episodes:
        ep = p.episode(n)
        index = context.PassageIndex(p, n)
        s = seed + n
        with usage.scope(project=f"judge-eval:{name}", episode=n, task="plant"):
            plan = llm.json(prompts.SYSTEM_PLANTER, prompts.plant_prompt(p, n, plants, s), PlantSet,
                            hint={"episode": n, "count": plants, "text": ep.text})
        used = [x for x in plan.items if x.quote and x.replacement and x.replacement != x.quote and x.quote in ep.text]
        planted = ep.text
        for x in used:
            planted = planted.replace(x.quote, x.replacement, 1)
        after = _claims(llm, p, name, n, planted, "claims-planted") if with_claims else None
        before = _claims(llm, p, name, n, ep.text, "claims-original") if with_claims else None
        for x in used:
            kw = {"type": x.type, "source_episode": x.source_episode, "source_quote": x.source_quote, "seed": s, "part": x.part}
            rows.append(_row(p, n, "plant", x.replacement, "어긋남", index, after, **kw))
            rows.append(_row(p, n, "original", x.quote, "ok", index, before, **kw))
        taken = {x.quote for x in used}
        pool = [x for x in sentences(ep.text) if x not in taken and not any(x in q or q in x for q in taken)]
        for x in random.Random(s).sample(pool, min(randoms, len(pool))):
            rows.append(_row(p, n, "random", x, "ok", index, before, seed=s))
        said = f", 진술 {len(after)}·{len(before)}개(상한 {prompts.TWOSTEP_CLAIMS})" if with_claims else ""
        print(f"  {name} {n}화: 심음 {len(used)}/{len(plan.items)}, 무작위 {min(randoms, len(pool))}{said}", file=sys.stderr)
    for e in sorted(p.episodes, key=lambda e: e.plot.number):
        n = e.plot.number
        hits = [f for f in e.findings if f.status == "fixed" and f.type in FINDING_TYPES
                and f.current_quote.strip() and f.source_episode != n]
        if not hits:
            continue
        index = context.PassageIndex(p, n)
        for f in hits:
            rows.append(_row(p, n, "finding", f.current_quote.strip(), "어긋남", index, type=f.type,
                             source_episode=f.source_episode, source_quote=f.source_quote, closed_by=f.closed_by))
    for r in rows:
        r["project"] = name
    return rows


def build(args) -> None:
    src = Path(args.src)
    home = Path(tempfile.mkdtemp(prefix="judge-eval-"))
    old_root = store.ROOT
    llm = make_backend(Backend(provider=args.provider, model=args.model or ""))
    rows: list[dict] = []
    try:
        for name in args.project:
            shutil.copytree(src / name, home / name)
        store.ROOT = home
        for name in args.project:
            p = store.load(name)
            eps = plant_episodes(p, args.episodes)
            print(f"{name}: 모순 심을 화 {eps}", file=sys.stderr)
            rows += build_project(p, name, llm, eps, args.plants, args.random, args.seed, not args.no_claims)
    finally:
        store.ROOT = old_root
        shutil.rmtree(home, ignore_errors=True)
    for i, r in enumerate(rows):
        r["id"] = f"{r['project']}:{r['episode']}:{r['source']}:{i}"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(json.dumps(summary(rows), ensure_ascii=False, indent=1))


def summary(rows: list[dict]) -> dict:
    c = Counter((r["source"], r["label"]) for r in rows)
    pos = [r for r in rows if r["label"] == "어긋남"]
    return {"rows": len(rows), "by_source": {f"{s}:{lab}": v for (s, lab), v in sorted(c.items())},
            "contradiction_cross": sum(bool(r["cross"]) for r in pos),
            "contradiction_cross_in_evidence": sum(bool(r["cross"]) and r["has_source"] is True for r in pos),
            "contradiction_cross_in_evidence_plain": sum(bool(r["cross"]) and r.get("has_source_plain") is True for r in pos),
            "claimed": dict(Counter(f"{r['source']}:{r.get('claimed')}" for r in rows if r.get("claimed") is not None)),
            "contradiction_types": dict(Counter(r["type"] for r in pos)),
            "evidence_chars_mean": round(sum(len(r["evidence"]) for r in rows) / max(1, len(rows)))}


def groups(rows: list[dict]) -> dict[str, list[int]]:
    """재현율을 볼 묶음(정답 '어긋남')과 헛지적률을 볼 묶음(정답 'ok')."""
    g: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        keys = []
        if r["label"] == "어긋남":
            kind = "plant" if r["source"] == "plant" else "finding"
            if r["cross"]:
                keys.append(f"{kind}·옛근거")
                if r["has_source"] is True:
                    keys.append(f"{kind}·옛근거·근거에 듦")
            else:
                keys.append(f"{kind}·같은 화")
        else:
            keys.append(r["source"])
        for k in keys:
            g.setdefault(k, []).append(i)
    return g


def auc(pos: list[float], neg: list[float]) -> float | None:
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 3)


def metrics(rows: list[dict], bad: list[float]) -> dict:
    g = groups(rows)
    table = {}
    for k, idx in sorted(g.items()):
        table[k] = {"n": len(idx), **{f"≥{t}": round(sum(bad[i] >= t for i in idx) / len(idx), 3) for t in THRESHOLDS}}
    neg = [bad[i] for k in ("original", "random") for i in g.get(k, [])]
    key = "plant·옛근거·근거에 듦"
    return {"flag_rate": table, "auc_plant_in_evidence_vs_ok": auc([bad[i] for i in g.get(key, [])], neg),
            "auc_plant_vs_original": auc([bad[i] for i in g.get(key, [])], [bad[i] for i in g.get("original", [])])}


def shuffled(rows: list[dict], seed: int) -> list[dict]:
    """줄마다 다른 화 줄의 근거 묶음으로 바꾼 사본 (seed 로 같은 짝)."""
    rng = random.Random(seed)
    out = []
    for r in rows:
        others = [x for x in rows if x["episode"] != r["episode"]] or rows
        out.append({**r, "evidence": rng.choice(others)["evidence"]})
    return out


def run(args) -> None:
    rows = [json.loads(x) for x in Path(args.set).read_text(encoding="utf-8").splitlines() if x.strip()]
    if args.only_cross:
        rows = [r for r in rows if r["label"] == "ok" or r["cross"]]
    if args.shuffle:  # 다른 화의 근거 묶음을 붙인다. 엉뚱한 근거로도 '어긋남'을 고르면 문장의 티를 보는 것이다
        rows = shuffled(rows, args.shuffle)
    judge = make_judge(args.judge, args.model or None, args.url or None)
    qs = [Question(id=r["id"], state="" if args.blind else r["evidence"],
                   text=prompts.claim_question(Claim(quote=r["quote"], claim=r.get("claim") or r["quote"])), options=prompts.CLAIM_OPTIONS)
          for r in rows]
    with usage.scope(project="judge-eval", task="judge-blind" if args.blind else "judge"):
        answers = judge.decide(prompts.SYSTEM_JUDGE_CHECK, qs)
    bad = [a.probs[1] if len(a.probs) > 1 else 0.0 for a in answers]
    res = {"set": args.set, "judge": args.judge, "model": getattr(judge, "model", ""), "blind": args.blind, "shuffle": args.shuffle,
           "rows": len(rows), "low_mass": sum(a.mass < 0.5 for a in answers), **metrics(rows, bad)}
    if args.out:
        Path(args.out).write_text("".join(json.dumps({"id": r["id"], "probs": a.probs, "mass": a.mass}, ensure_ascii=False) + "\n"
                                          for r, a in zip(rows, answers)), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="평가 줄 만들기")
    b.add_argument("--src", required=True, help="작품 폴더들이 있는 곳 (복사해서 쓴다)")
    b.add_argument("--project", action="append", required=True, help="작품 이름 (여러 번)")
    b.add_argument("--provider", default="gemini")
    b.add_argument("--model", default="")
    b.add_argument("--episodes", type=int, default=20, help="작품마다 모순을 심을 화 수")
    b.add_argument("--plants", type=int, default=4, help="화마다 심을 모순 수")
    b.add_argument("--random", type=int, default=6, help="화마다 넣을 심지 않은 문장 수")
    b.add_argument("--seed", type=int, default=20261109)
    b.add_argument("--no-claims", action="store_true", help="진술 뽑기(claims_prompt)를 부르지 않고 문장 그대로 근거를 찾는다")
    b.add_argument("--out", required=True)
    r = sub.add_parser("run", help="판단기로 판정하고 재현율 · 헛지적률 내기")
    r.add_argument("set")
    r.add_argument("--judge", default="local", help="local | mock")
    r.add_argument("--model", default="")
    r.add_argument("--url", default="")
    r.add_argument("--blind", action="store_true", help="근거를 빼고 판정")
    r.add_argument("--shuffle", type=int, default=0, metavar="SEED", help="다른 화의 근거 묶음을 붙여 판정 (0 이면 끔)")
    r.add_argument("--only-cross", action="store_true", help="같은 화 근거의 '어긋남' 줄(동선 등)을 뺀다")
    r.add_argument("--out", default="", help="줄마다 확률을 적을 JSONL")
    args = ap.parse_args(argv)
    build(args) if args.cmd == "build" else run(args)


if __name__ == "__main__":
    main()

"""내용 맞춘 짝 목록 만들기: 레퍼런스 대목에서 사실 카드를 뽑고, canon 이 같은 장면을 써서 판별 묶음용 짝 목록을 만든다.

차례: pick -> gen -> pairs -> blind_ident.py check -> blind_ident.py build.
  python scripts/blind_scene_pairs.py estimate --rid RID [--rid ...] --n 10 --reps 2 --model gemini:모델이름
  python scripts/blind_scene_pairs.py pick --rid RID [--rid ...] --n 10 --model gemini:모델이름 --dir 폴더
  python scripts/blind_scene_pairs.py gen --dir 폴더 --model gemini:모델이름 [--reps 2]
  python scripts/blind_scene_pairs.py pairs --dir 폴더 --out 짝목록.json
  python scripts/blind_ident.py check --pairs 짝목록.json
  python scripts/blind_ident.py build --pairs 짝목록.json --out 묶음폴더
대목은 한 화의 이웃한 두 대목(약 1,800자)을 이은 것이다. 자르개가 첫 · 마지막 문단을 버려도 MIN_CHARS 를 채우게 하려는 것이다.
쓰기 카드의 목표 글자 수는 그 대목 길이(50 단위 반올림)라서 canon 글도 같은 분량이다.
유료 모델을 부르므로 돌리기 전에 estimate 로 비용을 본다. AGENTS.md '비용 드는 모델 실험'의 한도(실험 하나 $5, 세션 합계 $10)를 지킨다.
--model 은 백엔드:모델 꼴이고 기본값이 없다. pick 은 폴더/passages.json 을, gen 은 폴더/gen.json 을 쓰고(이어 돌리기), pairs 는 --out 을 쓴다.
pick · gen · pairs 가 찍는 글에는 본문 · 인물 이름 · 원고 이름을 싣지 않는다. 시험은 tests/test_blind_scene_pairs.py (가짜 LLM).
"""
from __future__ import annotations

import argparse
import contextvars
import json
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from canon import drill, metrics, pipeline, prompts, studio, usage  # noqa: E402
from canon.schema import DrillFacts, DrillRound, SceneCard, StudioDraft  # noqa: E402

SEED = 20261117
REPS = 2                          # 대목마다 쓰는 횟수 (기본)
KO_CHARS_PER_TOKEN = 1.7
OUT_TOKENS_FACTS = 800            # 사실 뽑기 응답 토큰 어림
MAX_DRAWS_PER_RID = 20
THREADS = 6


def pick_passages(rids: list[str], n: int, llm, rng: random.Random) -> tuple[list[dict], dict]:
    """원고들에서 대목 n 개(원고마다 고르게 돌아가며)를 고르고 사실을 뽑는다. 대목은 이웃 대목과 이은 것이다.
    같은 화에서 이미 쓴 대목과 겹치는 대목은 다시 고르지 않는다."""
    rows: list[dict] = []
    seen: dict[tuple, set] = {}
    draws = {r: 0 for r in rids}
    stats = {"draws": 0, "failed": 0, "kept": 0}
    with usage.scope(project="", task="blind_scene_pairs: 사실 뽑기"):
        while len(rows) < n and any(d < MAX_DRAWS_PER_RID for d in draws.values()):
            for rid in rids:
                if len(rows) >= n:
                    break
                if draws[rid] >= MAX_DRAWS_PER_RID:
                    continue
                draws[rid] += 1
                stats["draws"] += 1
                row = _draw(rid, len(rows) + 1, llm, rng, seen)
                if row == "failed":
                    stats["failed"] += 1
                elif row:
                    rows.append(row)
    stats["kept"] = len(rows)
    return rows, stats


def _join(rid: str, p: dict) -> dict | None:
    """고른 대목 p 와 이웃 대목을 이은 {order, part, source, lead}. 대목이 하나뿐인 화는 None.
    자르개가 첫 문단과 마지막 문단을 버리므로 대목 둘(약 1,800자)을 잇는다."""
    ep = next((e for e in drill._episodes(rid) if e["order"] == p["order"]), None)
    if ep is None:
        return None
    ps = drill.passages(ep["text"])
    i = p["part"] - 1
    if i + 1 < len(ps):
        a, b = i, i + 1
    elif i >= 1:
        a, b = i - 1, i
    else:
        return None
    text = ep["text"]
    lead = text[max(0, ps[a]["start"] - drill.LEAD_MAX):ps[a]["start"]].strip()
    return {"order": p["order"], "part": a + 1, "used": {a, b}, "source": text[ps[a]["start"]:ps[b]["end"]].strip(), "lead": lead}


def _draw(rid: str, k: int, llm, rng: random.Random, seen: dict):
    """대목 하나(이웃 대목과 이은 것) + 사실. 이미 쓴 대목과 겹치면 None, 실패하면 'failed'."""
    try:
        j = _join(rid, drill.pick(rid, rng=rng))
    except (KeyError, ValueError):
        return "failed"
    if j is None:
        return None
    used = seen.setdefault((rid, j["order"]), set())
    if used & j["used"]:
        return None
    used |= j["used"]
    try:
        facts = drill.clean_facts(pipeline.drill_facts(llm, j["source"], j["lead"]), j["source"], j["lead"])
    except Exception:  # noqa: BLE001 - 어떤 실패든 건너뛰고 센다
        return "failed"
    return {"id": f"S{k:02d}", "rid": rid, "order": j["order"], "part": j["part"], "source": j["source"], "lead": j["lead"],
            "facts": facts.model_dump()}


def card_for(row: dict) -> SceneCard:
    """사실만 담은 카드 (인물 · 시점 · 장소 · 때 · 직전 상황 · 일어나는 일). 쓰는 방식과 속사정은 비운다.
    목표 글자 수는 레퍼런스 대목의 길이(50 단위 반올림)다. 두 글이 같은 사건 범위를 담게 한다."""
    r = DrillRound(id=row["id"], source=row["source"], lead=row["lead"], style_id="", facts=DrillFacts(**row["facts"]))
    b = drill.facts_brief(r.facts)
    return drill.card_of(r, b.model_copy(update={"inner": ""}), bare=True).model_copy(update={"length": round(len(row["source"]) / 50) * 50})


def _write_one(row: dict, llm) -> dict:
    try:
        card = card_for(row)
        p = studio.world(card)
        out = llm.json(prompts.system_prompt(prompts._PARAGRAPH_WRITER, korean=False), prompts.paragraph_prompt(p, card, 1, []), StudioDraft,
                       hint={"n": 1, "action": card.action, "source": "", "names": [], "extra": ""})
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", out.candidates[0].text).strip()
        return {"text": text} if text else {"error": "빈 글"}
    except Exception as e:  # noqa: BLE001 - 실패는 남기고 다음으로 간다
        return {"error": str(e)[:200]}


def write_scenes(rows: list[dict], llm, reps: int, done: dict) -> dict:
    """대목마다 reps 번 쓴다. 키 f"{id}|{k}". done 에 이미 있는 키는 다시 쓰지 않는다. done 에 새 결과를 더한 사전을 돌려준다."""
    todo = [(f"{r['id']}|{k}", r) for r in rows for k in range(1, reps + 1) if f"{r['id']}|{k}" not in done]
    out = dict(done)
    with usage.scope(project="", task="blind_scene_pairs: 장면 쓰기"), ThreadPoolExecutor(max_workers=THREADS) as pool:
        futs = [(key, pool.submit(contextvars.copy_context().run, _write_one, r, llm)) for key, r in todo]
        for key, f in futs:
            out[key] = f.result()
    return out


def make_pairs(rows: list[dict], done: dict) -> tuple[list[dict], dict]:
    """짝 목록과 센 값. 글이 없거나 오류이면 missing, 대목 문장을 옮겼으면 copied 로 뺀다."""
    pairs: list[dict] = []
    stats = {"rows": len(rows), "pairs": 0, "missing": 0, "copied": 0}
    for r in rows:
        base = (done.get(f"{r['id']}|1") or {}).get("text") or ""
        if not base:
            stats["missing"] += 1
            continue
        if metrics.copied_sentences(base, [r["source"], r["lead"]]):
            stats["copied"] += 1
            continue
        f = r["facts"]
        names = list(dict.fromkeys(x for x in [*(p["name"] for p in f["people"]), f["pov"]] if x))
        pair = {"ref": r["source"], "base": base, "names": names, "rid": r["rid"], "order": r["order"]}
        base2 = (done.get(f"{r['id']}|2") or {}).get("text") or ""
        if base2:
            pair["base2"] = base2
        pairs.append(pair)
    stats["pairs"] = len(pairs)
    return pairs, stats


def _sample(rid: str, rng: random.Random) -> dict:
    """표본 대목 하나 (이은 것). 대목이 하나뿐인 화는 다시 뽑는다."""
    for _ in range(MAX_DRAWS_PER_RID):
        j = _join(rid, drill.pick(rid, rng=rng))
        if j:
            return j
    raise SystemExit("이을 대목이 둘 이상인 화가 없어요")


def _empty_card(sample: dict) -> SceneCard:
    row = {"id": "S00", "source": sample["source"], "lead": sample["lead"],
           "facts": DrillFacts(people=[], pov="", place="", time="", before="", inner=[], events=[]).model_dump()}
    return card_for(row)


def estimate(rids: list[str], n: int, reps: int, backend: str, model: str) -> dict:
    """호출 수와 어림 비용. 사실 뽑기 n 번 + 쓰기 n*reps 번. 호출하지 않는다."""
    rng = random.Random(SEED)
    samples = [_sample(rid, rng) for rid in rids]
    facts_in = sum(len(prompts.drill_facts_prompt(s["source"], s["lead"])) for s in samples) / len(samples) / KO_CHARS_PER_TOKEN
    write_in = sum(len(prompts.paragraph_prompt(studio.world(c), c, 1, [])) for c in map(_empty_card, samples)) / len(samples) / KO_CHARS_PER_TOKEN
    tin = n * facts_in + n * reps * write_in
    write_out = sum(len(s["source"]) for s in samples) / len(samples) / KO_CHARS_PER_TOKEN
    tout = n * OUT_TOKENS_FACTS + n * reps * write_out
    price = usage.rate(model)
    out = {"calls": {"facts": n, "write": n * reps}, "tokens": {"in": round(tin), "out": round(tout)}, "usd": None,
           "model": f"{backend}:{model}"}
    if price is None:
        out["note"] = "가격표에 없어요"
    else:
        out["usd"] = round(usage.cost(price, tin, tout), 4)
    return out


# ---------- 명령줄 ----------

def _split_model(text: str) -> tuple[str, str]:
    backend, _, model = text.partition(":")
    if not backend or not model:
        raise SystemExit("--model 은 백엔드:모델 꼴이어야 해요 (예: gemini:모델이름)")
    return backend, model


def _llm(text: str):
    from canon import llm as llm_mod

    backend, model = _split_model(text)
    return llm_mod.make_llm(backend, model)


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_pick(a) -> dict:
    out = Path(a.dir) / "passages.json"
    if out.exists():
        raise SystemExit(f"이미 있어요: {out}")
    rows, stats = pick_passages(a.rid, a.n, _llm(a.model), random.Random(SEED))
    out.parent.mkdir(parents=True, exist_ok=True)
    _write(out, {"rows": rows, "stats": stats})
    return stats


def cmd_gen(a) -> dict:
    d = Path(a.dir)
    rows = _read(d / "passages.json")["rows"]
    f = d / "gen.json"
    done = _read(f) if f.exists() else {}
    got = write_scenes(rows, _llm(a.model), a.reps, done)
    _write(f, got)
    return {"new": len(got) - len(done), "errors": sum(1 for v in got.values() if "error" in v), "total": len(got)}


def cmd_pairs(a) -> dict:
    out = Path(a.out)
    if out.exists():
        raise SystemExit(f"이미 있어요: {out}")
    d = Path(a.dir)
    f = d / "gen.json"
    pairs, stats = make_pairs(_read(d / "passages.json")["rows"], _read(f) if f.exists() else {})
    _write(out, pairs)
    return stats


def cmd_estimate(a) -> dict:
    backend, model = _split_model(a.model)
    return estimate(a.rid, a.n, a.reps, backend, model)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="레퍼런스 대목에서 내용 맞춘 짝 목록 만들기")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, text in (("estimate", "호출 수와 어림 비용만 찍어요"), ("pick", "대목과 사실을 뽑아요")):
        s = sub.add_parser(name, help=text)
        s.add_argument("--rid", action="append", required=True, metavar="RID")
        s.add_argument("--n", type=int, required=True)
        s.add_argument("--model", required=True, metavar="백엔드:모델")
        if name == "estimate":
            s.add_argument("--reps", type=int, default=REPS)
        else:
            s.add_argument("--dir", required=True)
    g = sub.add_parser("gen", help="대목마다 canon 장면을 써요")
    g.add_argument("--dir", required=True)
    g.add_argument("--model", required=True, metavar="백엔드:모델")
    g.add_argument("--reps", type=int, default=REPS)
    p = sub.add_parser("pairs", help="짝 목록을 써요")
    p.add_argument("--dir", required=True)
    p.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    result = {"estimate": cmd_estimate, "pick": cmd_pick, "gen": cmd_gen, "pairs": cmd_pairs}[a.cmd](a)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

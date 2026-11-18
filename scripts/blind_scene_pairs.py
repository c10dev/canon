"""내용 맞춘 짝 목록 만들기: 레퍼런스 대목에서 사실 카드를 뽑고, canon 이 같은 장면을 써서 판별 묶음용 짝 목록을 만든다.

차례: pick -> gen -> pairs -> blind_ident.py check -> blind_ident.py build.
  python scripts/blind_scene_pairs.py estimate --rid RID [--rid ...] --n 10 --reps 2 --model gemini:모델이름
  python scripts/blind_scene_pairs.py pick --rid RID [--rid ...] --n 10 --model gemini:모델이름 --dir 폴더
  python scripts/blind_scene_pairs.py style --rid RID --out 문체.json [--model 백엔드:모델]
  python scripts/blind_scene_pairs.py gen --dir 폴더 [--path episode|paragraph] --settings-from 작품 --style RID=문체 [--reps 1] [--limit K]
  python scripts/blind_scene_pairs.py pairs --dir 폴더 --out 짝목록.json
  python scripts/blind_ident.py check --pairs 짝목록.json
  python scripts/blind_ident.py build --pairs 짝목록.json --out 묶음폴더
대목은 한 화의 이웃한 두 대목(약 1,800자)을 이은 것이다. 자르개가 첫 · 마지막 문단을 버려도 MIN_CHARS 를 채우게 하려는 것이다.
쓰기 카드의 목표 글자 수는 그 대목 길이(50 단위 반올림)라서 canon 글도 같은 분량이다.
기본 길(--path episode)은 사실 카드 하나로 임시 장편 작품을 만들고 canon 의 화 쓰기 길(조율 메모 · 스토리보드 · 큐 시트 · 본문)로 쓴다. 작품 · 문체 · 원고는 저장하지 않는다.
--path paragraph 는 예전 문단 연습장 길이다.
유료 모델을 부르므로 돌리기 전에 estimate 로 비용을 본다. AGENTS.md '비용 드는 모델 실험'의 한도(실험 하나 $5, 세션 합계 $10)를 지킨다.
--model 은 백엔드:모델 꼴이다. paragraph 길은 필수, episode 길은 선택(없으면 canon 단계 기본 모델)이다. pick 은 폴더/passages.json 을, gen 은 폴더/gen.json 을 쓰고(이어 돌리기), pairs 는 --out 을 쓴다.
pick · gen · pairs 가 찍는 글에는 본문 · 인물 이름 · 원고 이름을 싣지 않는다. 시험은 tests/test_blind_scene_pairs.py (가짜 LLM).
"""
from __future__ import annotations

import argparse
import contextvars
import copy
import json
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from canon import board, coord, cue, drill, library, metrics, pipeline, prompts, refs, studio, usage  # noqa: E402
from canon.metrics import StyleMetrics  # noqa: E402
from canon.schema import (  # noqa: E402
    Character,
    CoordMemo,
    CueSheet,
    DrillFacts,
    DrillRound,
    Episode,
    EpisodePlot,
    Meta,
    Project,
    SceneCard,
    Settings,
    StoryArc,
    Storyboard,
    StudioDraft,
    StyleProfile,
)
from canon.schema import Part as SPart  # noqa: E402

SEED = 20261117
REPS = 1                          # 대목마다 쓰는 횟수 (기본)
KO_CHARS_PER_TOKEN = 1.7
OUT_TOKENS_FACTS = 800            # 사실 뽑기 응답 토큰 어림
OUT_TOKENS_BOARD = 1500           # 스토리보드 응답 토큰 어림
OUT_TOKENS_CUE = 2000             # 큐 시트 응답 토큰 어림
OUT_TOKENS_COORD = 600            # 조율 메모 응답 토큰 어림 (실측 아님)
THOUGHT_TOKENS = {"facts": 3000, "board": 6000, "cue": 6000, "coord": 3000, "write": 17000}  # 생각 토큰 어림 (지난 실측: 장면 쓰기 한 번에 약 1만 7천)
EP_NO = prompts.OPENING_EPISODES + 1  # 4화: 1~3화 여는 규칙이 걸리지 않는 첫 화
ARC_END = EP_NO + 6
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


def write_scenes(rows: list[dict], llm, reps: int, done: dict) -> dict:  # paragraph 길
    """대목마다 reps 번 쓴다. 키 f"{id}|{k}". done 에 이미 있는 키는 다시 쓰지 않는다. done 에 새 결과를 더한 사전을 돌려준다."""
    todo = [(f"{r['id']}|{k}", r) for r in rows for k in range(1, reps + 1) if f"{r['id']}|{k}" not in done]
    out = dict(done)
    with usage.scope(project="", task="blind_scene_pairs: 장면 쓰기"), ThreadPoolExecutor(max_workers=THREADS) as pool:
        futs = [(key, pool.submit(contextvars.copy_context().run, _write_one, r, llm)) for key, r in todo]
        for key, f in futs:
            out[key] = f.result()
    return out


# ---------- 화 쓰기 길 (--path episode) ----------

def make_style(rid: str, llm) -> dict:
    """레퍼런스 원고 전체에서 화면의 문체 만들기와 같은 길로 문체를 만든다. 저장하지 않는다."""
    orders = [e.order for e in refs.load(rid).eps]
    s = refs.sample(rid, orders)
    with usage.scope(project="", task="blind_scene_pairs: 문체 분석"):
        prof = pipeline.analyze_style(llm, s["text"], corpus=refs.corpus(rid, orders))
    return {"profile": prof.model_dump(), "sample": s["text"]}


def load_style(src: str) -> tuple[StyleProfile, StyleMetrics | None, str]:
    """(프로필, 기준 지표, 견줄 원문). 라이브러리 id 면 그 항목의 profile · baseline · sample, 파일이면 JSON 의 profile 과 sample (기준 지표 None)."""
    if library.exists(src):
        e = library.load(src)
        return e.profile.model_copy(deep=True), e.baseline, e.sample
    d = _read(Path(src))
    return StyleProfile.model_validate(d["profile"]), None, d.get("sample", "")


def episode_project(row: dict, settings: Settings, style: tuple) -> Project:
    """사실 카드 하나로 만든 임시 장편 작품. 저장하지 않는다. style 은 load_style 의 값이다."""
    facts = DrillFacts(**row["facts"])
    p = Project(meta=Meta(title="판별 묶음", form="serial", words_per_episode=round(len(row["source"]) / 50) * 50))
    p.settings = copy.deepcopy(settings)
    for i, person in enumerate(facts.people, 1):
        p.characters.append(Character(id=f"c{i}", name=person.name, role=person.note or "인물",
                                      tier="main" if person.name == facts.pov else "support"))
    pov = next((c.id for c in p.characters if c.name == facts.pov), "")
    if facts.pov and not pov:
        pov = f"c{len(p.characters) + 1}"
        p.characters.append(Character(id=pov, name=facts.pov, role="인물", tier="main"))
    p.parts = [SPart(number=1, title="1부", start_ep=1, end_ep=ARC_END, goal="")]
    p.story_arcs = [StoryArc(number=1, title="1아크", start_ep=1, end_ep=ARC_END, goal="")]
    for i in range(1, EP_NO):
        plot = EpisodePlot(number=i, act="기", title="", summary="", events=["앞 이야기"], characters=[], emotional_shift="", ending_hook="")
        p.episodes.append(Episode(plot=plot, status="finalized", summary=facts.before if i == EP_NO - 1 else ""))
    plot = EpisodePlot(number=EP_NO, act="승", title="", summary=" ".join(facts.events), events=facts.events,
                       characters=[c.id for c in p.characters], emotional_shift="", ending_hook=facts.events[-1] if facts.events else "",
                       pov=pov, time=facts.time, opening=f"장소: {facts.place}" if facts.place else "")
    p.episodes.append(Episode(plot=plot, status="confirmed"))
    p.style = style[0].model_copy(deep=True)
    if style[1] is not None:
        p.style_baseline = style[1]
    return p


def _plan_coord(p: Project, board_llm) -> dict:
    """쓰기 재료 조율(write_material=coord)이면 조율 메모를 만들어 임시 작품의 화에 넣는다 (실제 쓰기의 coord.remake 와 같다).
    받지 못하면 {"coord_error": 앞 200자} 만 남기고 원래 플롯으로 쓴다 (웹 쓰기 · 자동 집필과 같다)."""
    if not coord.remake(p, EP_NO):
        return {}
    try:
        m = pipeline.make_coord(board_llm, p, EP_NO)
    except Exception as e:  # noqa: BLE001 - 조율 메모는 연출 메모라 멈추지 않는다
        return {"coord_error": str(e)[:200]}
    p.episode(EP_NO).coord = m
    return {"coord": m.model_dump()}


def plan_scene(row: dict, p: Project, board_llm) -> dict:
    """쓰기 재료. 조율이면 조율 메모를 먼저(스토리보드도 메모를 플롯으로 본다), 스토리보드와 큐 시트를 켠 작품이면 그것도 만들어
    임시 작품의 화에 넣는다. board_llm 은 board 단계(비우면 plan 단계) 모델이다. 실패는 {"error": 앞 200자}."""
    try:
        ep = p.episode(EP_NO)
        lead: list[str] = []
        b = c = None
        memo = _plan_coord(p, board_llm)
        if board.on(p):
            b = pipeline.make_storyboard(board_llm, p, EP_NO, lead=lead)
            ep.storyboard = b
        if cue.on(p):
            c = pipeline.make_cue_sheet(board_llm, p, EP_NO, lead=pipeline.cue_lead(p, EP_NO, lead, b.made_at if b else ""))
            ep.cue_sheet = c
        return {**memo, "storyboard": b.model_dump() if b else None, "cue_sheet": c.model_dump() if c else None}
    except Exception as e:  # noqa: BLE001 - 실패는 남기고 다음으로 간다
        return {"error": str(e)[:200]}


def _attach(p: Project, plan: dict) -> None:
    """이어 돌릴 때 남겨 둔 쓰기 재료를 임시 작품의 화에 다시 넣는다."""
    ep = p.episode(EP_NO)
    if plan.get("coord"):
        ep.coord = CoordMemo.model_validate(plan["coord"])
    if plan.get("storyboard"):
        ep.storyboard = Storyboard.model_validate(plan["storyboard"])
    if plan.get("cue_sheet"):
        ep.cue_sheet = CueSheet.model_validate(plan["cue_sheet"])


def _style_overlap(source: str, passages: list[str]) -> bool:
    return any(h["kind"] == "quote" for x in passages for h in refs.overlap(source, [x]))


def _write_ep(llm, p: Project) -> dict:
    try:
        text = pipeline.write_episode(llm, p, EP_NO).strip()
        return {"text": text} if text else {"error": "빈 글"}
    except Exception as e:  # noqa: BLE001 - 실패는 남기고 다음으로 간다
        return {"error": str(e)[:200]}


def _todo(done: dict, key: str) -> bool:
    return key not in done or "error" in done[key]


def _scene_job(row: dict, settings: Settings, style: tuple, llms: tuple, reps: int, done: dict) -> dict:
    """대목 하나의 새 결과 {키: 값}. done 은 읽기만 한다. 재료 → 쓰기는 차례로 부른다."""
    pkey = f"{row['id']}|plan"
    plan = done.get(pkey)
    if plan is not None and "skip" in plan:
        return {}
    new: dict = {}
    passages = list(style[0].sample_passages)
    if _todo(done, pkey) and _style_overlap(row["source"], passages):
        return {pkey: {"skip": "style_overlap"}}
    p = episode_project(row, settings, style)
    if _todo(done, pkey):
        plan = plan_scene(row, p, llms[0])
        if "error" not in plan:
            plan["style_passages"] = passages
        new[pkey] = plan
        if "error" in plan:
            return new
    else:
        _attach(p, plan)
    for k in range(1, reps + 1):
        if _todo(done, f"{row['id']}|{k}"):
            new[f"{row['id']}|{k}"] = _write_ep(llms[1], p)
    return new


def write_episode_scenes(rows: list[dict], settings, styles: dict[str, tuple], board_llm, write_llm, reps: int, done: dict, limit: int = 0) -> dict:
    """대목마다: 문체 겹침 검사 → 임시 작품 → 쓰기 재료(키 id|plan) → reps 번 쓰기(키 id|k). 이미 있는 키(오류 아닌 것)는 다시 부르지 않는다.
    대목 사이는 스레드 THREADS 개로 나란히, 한 대목 안은 차례로. done 에 새 결과를 더한 사전을 돌려준다."""
    rows = rows[:limit] if limit else rows
    out = dict(done)
    with usage.scope(project="", task="blind_scene_pairs: 화 쓰기"), ThreadPoolExecutor(max_workers=THREADS) as pool:
        futs = [pool.submit(contextvars.copy_context().run, _scene_job, r, settings, styles[r["rid"]], (board_llm, write_llm), reps, done)
                for r in rows]
        for f in futs:
            out.update(f.result())
    out["_meta"] = {"path": "episode", "write_model": usage.model_id(write_llm), "board_model": usage.model_id(board_llm)}
    return out


def make_pairs(rows: list[dict], done: dict) -> tuple[list[dict], dict]:
    """짝 목록과 센 값. 글이 없거나 오류이면 missing, 문체 겹침으로 쓰지 않은 대목은 style_overlap,
    대목 · 문체 예시 문단의 문장을 옮겼으면 copied 로 뺀다. names 는 같은 rid 모든 대목의 사실 카드 이름을 합친다."""
    rid_names: dict[str, list[str]] = {}
    for r in rows:
        f = r["facts"]
        got = rid_names.setdefault(r["rid"], [])
        got.extend(x for x in [*(p["name"] for p in f["people"]), f["pov"]] if x)
    rid_names = {k: list(dict.fromkeys(v)) for k, v in rid_names.items()}
    pairs: list[dict] = []
    stats = {"rows": len(rows), "pairs": 0, "missing": 0, "copied": 0, "style_overlap": 0}
    for r in rows:
        plan = done.get(f"{r['id']}|plan") or {}
        if plan.get("skip") == "style_overlap":
            stats["style_overlap"] += 1
            continue
        base = (done.get(f"{r['id']}|1") or {}).get("text") or ""
        if not base:
            stats["missing"] += 1
            continue
        if metrics.copied_sentences(base, [r["source"], r["lead"], *plan.get("style_passages", [])]):
            stats["copied"] += 1
            continue
        pair = {"ref": r["source"], "base": base, "names": rid_names[r["rid"]], "rid": r["rid"], "order": r["order"]}
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


def _fact_row(sample: dict) -> dict:
    """어림용 사실 카드: 인물 둘, 일어나는 일 다섯 (표본 대목의 앞 문장 다섯을 40자로 자른 것)."""
    parts = [x.strip()[:40] for x in re.split(r"(?<=[.!?。])\s+|\n+", sample["source"]) if x.strip()][:5]
    facts = DrillFacts(people=[{"name": "가", "note": "인물"}, {"name": "나", "note": "인물"}], pov="가", place="", time="", before="",
                       inner=[], events=parts or [sample["source"][:40]])
    return {"id": "S00", "source": sample["source"], "lead": sample["lead"], "facts": facts.model_dump()}


def _group_cost(model: str, tin: float, tout: float, tries: int, assume: str) -> dict:
    """모델 하나 몫의 어림. 가격표에 없으면 usd None 과 note, assume 을 주면 그 모델 줄 값을 대신 쓴다."""
    g: dict = {"model": model, "tokens": {"in": round(tin), "out": round(tout)}, "usd": None, "usd_worst": None}
    price = usage.rate(model.partition(":")[2] or model)
    if price is None and assume:
        price = usage.rate(assume)
        g["assumed"] = assume
    if price is None:
        g["note"] = "가격표에 없어요"
    else:
        g["usd"] = round(usage.cost(price, tin, tout), 4)
        g["usd_worst"] = round(usage.cost(price, tin * tries, tout * tries), 4)
    return g


def estimate_episode(rids: list[str], n: int, reps: int, models: dict, settings: Settings, styles: dict[str, tuple], assume: str = "") -> dict:
    """화 쓰기 길의 호출 수와 어림 비용. 호출하지 않는다. 사실 뽑기는 스토리보드 모델 몫에 넣는다(같은 모델로 본다)."""
    rng = random.Random(SEED)
    samples = [(rid, _sample(rid, rng)) for rid in rids]
    k = len(samples)
    projs = [episode_project(_fact_row(sm), settings, styles.get(rid, (StyleProfile(), None, ""))) for rid, sm in samples]
    use_board, use_cue, use_coord = board.on(projs[0]), cue.on(projs[0]), coord.on(projs[0])
    avg = lambda xs: sum(xs) / k / KO_CHARS_PER_TOKEN  # noqa: E731 - 글자 수 평균을 토큰으로
    facts_in = avg([len(prompts.drill_facts_prompt(sm["source"], sm["lead"])) for _, sm in samples])
    board_in = avg([len(prompts.storyboard_prompt(p, EP_NO)) for p in projs]) if use_board else 0
    cue_in = avg([len(prompts.cue_sheet_prompt(p, EP_NO)) for p in projs]) if use_cue else 0
    coord_in = avg([len(prompts.SYSTEM_PLANNER) + len(prompts.coord_prompt(p, EP_NO)) for p in projs]) if use_coord else 0
    write_in = avg([len(prompts.episode_prompt(p, EP_NO)) + len(prompts.writer_system(p)) for p in projs])
    write_out = avg([len(sm["source"]) for _, sm in samples])
    plan_in = n * (facts_in + board_in + cue_in + coord_in)
    plan_out = n * (OUT_TOKENS_FACTS + THOUGHT_TOKENS["facts"] + (OUT_TOKENS_BOARD + THOUGHT_TOKENS["board"]) * bool(use_board)
                    + (OUT_TOKENS_CUE + THOUGHT_TOKENS["cue"]) * bool(use_cue) + (OUT_TOKENS_COORD + THOUGHT_TOKENS["coord"]) * bool(use_coord))
    w_in, w_out = n * reps * write_in, n * reps * (write_out + THOUGHT_TOKENS["write"])
    board_g = _group_cost(models["board"], plan_in, plan_out, 1, assume)
    write_g = _group_cost(models["write"], w_in, w_out, pipeline.WRITE_TRIES, assume)
    parts = (board_g, write_g)
    out = {"path": "episode", "calls": {"facts": n, "coord": n * use_coord, "board": n * use_board, "cue": n * use_cue, "write": n * reps},
           "tokens": {"in": round(plan_in + w_in), "out": round(plan_out + w_out)}, "models": {"board": board_g, "write": write_g},
           "usd": None, "usd_worst": None}
    if all(g["usd"] is not None for g in parts):
        out["usd"] = round(board_g["usd"] + write_g["usd"], 4)
        out["usd_worst"] = round(board_g["usd"] + write_g["usd_worst"], 4)
    else:
        out["note"] = "가격표에 없어요"
    if assume:
        out["assumed"] = assume
    return out


def estimate(rids: list[str], n: int, reps: int, backend: str = "", model: str = "", path: str = "paragraph",
             settings: Settings | None = None, styles: dict[str, tuple] | None = None, assume: str = "", models: dict | None = None) -> dict:
    """호출 수와 어림 비용. paragraph: 사실 뽑기 n 번 + 쓰기 n*reps 번. episode: 사실 + 조율 메모 + 스토리보드 + 큐 시트 + 쓰기. 호출하지 않는다."""
    if path == "episode":
        both = f"{backend}:{model}"
        return estimate_episode(rids, n, reps, models or {"board": both, "write": both}, settings or Settings(), styles or {}, assume)
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


def _stage_llm(model: str, stage: str):
    """--model 을 주면 그 모델 하나, 아니면 canon 단계 기본 모델."""
    from canon import llm as llm_mod

    return _llm(model) if model else llm_mod.get_llm(stage)


def _parse_styles(specs: list[str], rows: list[dict] | None) -> dict[str, tuple]:
    """--style RID=문체 를 읽는다. rows 를 주면 모든 rid 에 하나씩 있어야 한다(없으면 개수만 알리고 멈춘다)."""
    out = {}
    for x in specs or []:
        rid, _, src = x.partition("=")
        if not rid or not src:
            raise SystemExit("--style 은 RID=문체 꼴이어야 해요")
        out[rid] = load_style(src)
    if rows is not None:
        missing = {r["rid"] for r in rows} - set(out)
        if missing:
            raise SystemExit(f"--style 이 {len(missing)}개 원고만큼 빠졌어요")
    return out


def _settings_from(name: str) -> Settings:
    """작품의 설정을 읽기만 한다. 임시 작품이 깊은 복사로 받는다."""
    from canon import store

    if not name:
        raise SystemExit("episode 길은 --settings-from 작품이 필요해요")
    return store.load(name).settings


def cmd_style(a) -> dict:
    out = Path(a.out)
    if out.exists():
        raise SystemExit(f"이미 있어요: {out}")
    data = make_style(a.rid, _stage_llm(a.model, "plan"))
    out.parent.mkdir(parents=True, exist_ok=True)
    _write(out, data)
    prof = StyleProfile.model_validate(data["profile"])
    return {"chars": len(data["sample"]), "markers": len(prof.markers), "sample_passages": len(prof.sample_passages)}


def _gen_summary(got: dict, done: dict) -> dict:
    keys = [k for k in got if not k.startswith("_")]
    return {"new": len(keys) - sum(1 for k in done if not k.startswith("_")), "errors": sum(1 for k in keys if "error" in got[k]),
            "coord_errors": sum(1 for k in keys if "coord_error" in got[k]), "total": len(keys)}  # 조율 메모 없이 원래 플롯으로 쓴 대목


def cmd_gen(a) -> dict:
    if a.path == "paragraph" and not a.model:
        raise SystemExit("paragraph 길은 --model 이 필요해요")
    settings = _settings_from(a.settings_from) if a.path == "episode" else None
    d = Path(a.dir)
    rows = _read(d / "passages.json")["rows"]
    f = d / "gen.json"
    done = _read(f) if f.exists() else {}
    if settings is None:
        llm = _llm(a.model)
        got = write_scenes(rows, llm, a.reps, done)
        got["_meta"] = {"path": "paragraph", "write_model": usage.model_id(llm)}
    else:
        styles = _parse_styles(a.style, rows)
        got = write_episode_scenes(rows, settings, styles, _stage_llm(a.model, "board"), _stage_llm(a.model, "write"), a.reps, done, a.limit)
    _write(f, got)
    return _gen_summary(got, done)


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
    if a.path == "paragraph":
        if not a.model:
            raise SystemExit("paragraph 길은 --model 이 필요해요")
        backend, model = _split_model(a.model)
        return estimate(a.rid, a.n, a.reps, backend, model)
    settings = _settings_from(a.settings_from)
    styles = _parse_styles(a.style, None)
    if a.model:
        both = f"{_split_model(a.model)[0]}:{_split_model(a.model)[1]}"
        models = {"board": both, "write": both}
    else:
        models = {"board": usage.model_id(_stage_llm("", "board")), "write": usage.model_id(_stage_llm("", "write"))}
    return estimate(a.rid, a.n, a.reps, path="episode", settings=settings, styles=styles, assume=a.assume_price, models=models)


def _episode_args(s) -> None:
    s.add_argument("--path", choices=("episode", "paragraph"), default="episode")
    s.add_argument("--settings-from", default="", metavar="작품", help="episode 길: 이 작품의 설정을 읽기만 해요")
    s.add_argument("--style", action="append", default=[], metavar="RID=문체", help="episode 길: 원고마다 문체(라이브러리 id 나 style 이 쓴 파일)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="레퍼런스 대목에서 내용 맞춘 짝 목록 만들기")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("estimate", help="호출 수와 어림 비용만 찍어요")
    e.add_argument("--rid", action="append", required=True, metavar="RID")
    e.add_argument("--n", type=int, required=True)
    e.add_argument("--reps", type=int, default=REPS)
    e.add_argument("--model", default="", metavar="백엔드:모델")
    e.add_argument("--assume-price", default="", metavar="모델이름", help="가격표에 없는 모델의 셈에 이 모델 줄 값을 써요")
    _episode_args(e)
    k = sub.add_parser("pick", help="대목과 사실을 뽑아요")
    k.add_argument("--rid", action="append", required=True, metavar="RID")
    k.add_argument("--n", type=int, required=True)
    k.add_argument("--model", required=True, metavar="백엔드:모델")
    k.add_argument("--dir", required=True)
    t = sub.add_parser("style", help="레퍼런스 원고에서 문체를 만들어 파일로 써요")
    t.add_argument("--rid", required=True, metavar="RID")
    t.add_argument("--out", required=True)
    t.add_argument("--model", default="", metavar="백엔드:모델")
    g = sub.add_parser("gen", help="대목마다 canon 장면을 써요")
    g.add_argument("--dir", required=True)
    g.add_argument("--model", default="", metavar="백엔드:모델")
    g.add_argument("--reps", type=int, default=REPS)
    g.add_argument("--limit", type=int, default=0, help="passages.json 의 앞 K 대목만 써요")
    _episode_args(g)
    p = sub.add_parser("pairs", help="짝 목록을 써요")
    p.add_argument("--dir", required=True)
    p.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    result = {"estimate": cmd_estimate, "pick": cmd_pick, "style": cmd_style, "gen": cmd_gen, "pairs": cmd_pairs}[a.cmd](a)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

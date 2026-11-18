"""인물 자취 9-0 시험: 기획 요청의 자취 블록과 보는 눈 블록 견주기 (docs/trail/specs/09-0-compare.md).

판 넷(N 블록 없음 · V 보는 눈 · T 자취 · TV 둘 다)으로 기획 모델이 고른 이어받기 결정(carry)을 모은다.
자취 기획 블록은 아직 코드가 없어 이 스크립트 안에서만 만든다(trail_block).
작품은 임시 CANON_HOME 사본만 읽는다. store.save 를 부르지 않는다. 결과는 --out 폴더에만 쓴다.
유료 LLM 을 부른다(collect · plan). 사용량은 CANON_USAGE 에 남는다.

실행:
  CANON_HOME=<임시> CANON_USAGE=<usage.jsonl> python scripts/trail_plan_compare.py collect --work ref --out DIR --refs 8d46da028a60 --to 85
  CANON_HOME=<임시> CANON_USAGE=<usage.jsonl> python scripts/trail_plan_compare.py collect --work nsfw_saintess --out DIR --to 76
  CANON_HOME=<임시> CANON_USAGE=<usage.jsonl> python scripts/trail_plan_compare.py plan --passage S77 --arm T --runs 1 --out DIR
  python scripts/trail_plan_compare.py sheet --out DIR      # 판 이름을 가린 매김 표 sheet.tsv 와 key.json
  python scripts/trail_plan_compare.py score --out DIR      # 매긴 sheet.tsv 로 판별 표 score.md
"""
from __future__ import annotations

import argparse
import contextvars
import importlib.util
import json
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from canon import charviews, context, llm, prompts, store, trails  # noqa: E402
from canon.schema import (  # noqa: E402
    Character, CharTrail, CharView, PlotBatch, Project, StateDelta, TrailChange, ViewChange,
)

ARMS = ("N", "V", "T", "TV")
FAR = trails.FAR
BUDGET = context.BUDGET["plan_views"]  # 두 블록 모두 같은 예산
QUOTE_MAX = 60
# 레퍼런스(1-5 의 작품) 거두기 인물. 기획 인물은 앞의 둘이다(8-0 의 손 요청 [인물])
REF_CAST = (("seo_haeun", "서하은"), ("kang_juhyuk", "강주혁"), ("seo_jia", "서지아"), ("hinami", "히나미"))
REF_PLAN_IDS = {"seo_haeun", "kang_juhyuk"}
# 8-0 의 손 요청(기획 요청 2판 REQ 가 끝에 붙은 글)
VIEWS_DIR = Path("/home/c10/canon/reports/trail-views-2026-11-18")
PASSAGES = {
    "R18": {"work": "ref", "start": 18, "base": "prompt_18N_plan.txt"},
    "F86": {"work": "ref", "start": 86, "base": "prompt_F86N_plan.txt"},
    "S77": {"work": "nsfw_saintess", "start": 77, "end": 79},
}
PLAN_SYS = "당신은 장편 웹소설의 기획 편집자입니다."  # 8-0 의 손 요청과 같은 시스템 글
COLLECT_SYS = "당신은 장편 소설의 편집자입니다. 승인된 본문에서 뒤 화가 이어 받을 기록을 거둡니다."


class Collect(BaseModel):
    """거두기 응답: 상태 변경안의 trails · views 칸만 (설명은 StateDelta 와 같다)."""
    trails: list[TrailChange] = Field(default_factory=list, description=StateDelta.model_fields["trails"].description)
    views: list[ViewChange] = Field(default_factory=list, description=StateDelta.model_fields["views"].description)


def _load_module(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make(model: str, effort: str, stage: str):
    m = llm.make_llm("gemini", model, effort)
    m.stage = stage
    return m


# ---------- 거두기 ----------

def ref_project() -> Project:
    return Project(characters=[Character(id=i, name=n, role="주역", tier="main") for i, n in REF_CAST])


def work_texts(work: str, refs_ids: list[str], lo: int, hi: int) -> tuple[Project, list[tuple[int, str]]]:
    """(인물 목록이 든 작품, [(화, 본문)]). 레퍼런스는 여러 원고 id 를 이어 읽는다."""
    if work == "ref":
        tm = _load_module("trail_measure")
        rows = [r for rid in refs_ids for r in tm.ref_episodes(rid, lo, hi)]
        return ref_project(), sorted(dict(rows).items())
    p = store.load(work)
    rows = [(e.plot.number, e.final_text or e.text) for e in p.episodes if lo <= e.plot.number <= hi]
    return p, sorted(r for r in rows if r[1])


def collect_prompt(p: Project, n: int, text: str) -> str:
    cast = "\n".join(f"- {c.id}: {c.name}" for c in p.characters)
    return (f"[인물 (id: 이름)]\n{cast}\n\n[{n}화 본문]\n{text}\n\n"
            f"요구사항: 이번 화 본문만 보고 trails 와 views 를 채웁니다. 인물은 위 id 로만 적습니다."
            f"{trails.state_rule(p)}{charviews.state_rule(p)}")


def collect_one(m, p: Project, n: int, text: str, path: Path) -> str:
    if path.exists():
        return "있음"
    try:
        got = m.json(COLLECT_SYS, collect_prompt(p, n, text), Collect)
    except Exception as e:  # noqa: BLE001  화 하나가 실패해도 나머지는 거둔다
        return f"실패 {type(e).__name__}: {str(e)[:120]}"
    path.write_text(got.model_dump_json(indent=1), encoding="utf-8")
    return f"자취 {len(got.trails)} · 보는 눈 {len(got.views)}"


def cmd_collect(a) -> None:
    p, rows = work_texts(a.work, a.refs, 1, a.to)
    d = Path(a.out) / "collect" / a.work
    d.mkdir(parents=True, exist_ok=True)
    m = _make(a.model, a.effort, "state")
    with ThreadPoolExecutor(a.jobs) as ex:
        futs = {n: ex.submit(contextvars.copy_context().run, collect_one, m, p, n, t, d / f"{n:03d}.json") for n, t in rows}
        for n, f in futs.items():
            print(n, f.result(), flush=True)


def _squash(s: str) -> str:
    return " ".join(s.split())


def clean_work(work: str, refs_ids: list[str], out: Path, to: int) -> tuple[list[CharTrail], list[CharView]]:
    """거둔 줄을 일감 6 · 8-2 규칙으로 정리한다: 없는 인물 · 빈 라벨 뺌, 본문에 없는 구절 비움, 한 화 자취 3 · 보는 눈 4, 같은 최근 평가 거름."""
    p, rows = work_texts(work, refs_ids, 1, to)
    ids = {c.id for c in p.characters}
    texts = dict(rows)
    tr: list[CharTrail] = []
    vw: list[CharView] = []
    last: dict[tuple[str, str], str] = {}
    for n in sorted(texts):
        f = out / "collect" / work / f"{n:03d}.json"
        if not f.exists():
            continue
        got = Collect.model_validate_json(f.read_text(encoding="utf-8"))
        d = StateDelta(episode=n, summary="", trails=got.trails)
        for k, x in enumerate(trails._clean_trails(d, ids, texts[n]), 1):
            tr.append(CharTrail(id=f"tr-{n:03d}-{k}", character=x.character, episode=n, kind=x.kind, label=x.label,
                                quote=x.quote, witnesses=x.witnesses))
        vw += _clean_views(got.views, ids, n, last)
    return tr, vw


def _clean_views(rows: list[ViewChange], ids: set[str], n: int, last: dict[tuple[str, str], str]) -> list[CharView]:
    out: list[CharView] = []
    for v in rows:
        key = (v.viewer, v.target)
        verdict = v.verdict.strip()
        if v.viewer not in ids or v.target not in ids or v.viewer == v.target or not verdict or last.get(key) == verdict:
            continue
        last[key] = verdict
        out.append(CharView(viewer=v.viewer, target=v.target, episode=n, verdict=verdict, surface=v.surface.strip()))
        if len(out) == 4:
            break
    return out


# ---------- 블록 ----------

def _spread(rows: list[CharTrail], name: dict[str, str], room: int) -> tuple[list[CharTrail], int]:
    """rows(화 차례)를 room 글자 안에 고르게 솎는다. 앞 · 뒤 끝을 남기고 같은 간격. (고른 줄, 쓴 글자)"""
    for k in range(len(rows), 0, -1):
        idx = sorted({round(i * (len(rows) - 1) / max(1, k - 1)) for i in range(k)}) if k > 1 else [len(rows) - 1]
        pick = [rows[i] for i in idx]
        used = sum(len(trail_line(t, name)) + 1 for t in pick)
        if used <= room:
            return pick, used
    return [], 0


def trail_line(t: CharTrail, name: dict[str, str]) -> str:
    line = f"- {t.episode}화 {name.get(t.character, t.character)} · {t.kind} '{t.label}'"
    if t.witnesses:
        line += f" (본 사람: {', '.join(name.get(w, w) for w in t.witnesses)})"
    if t.quote:
        q = t.quote if len(t.quote) <= QUOTE_MAX else t.quote[:QUOTE_MAX] + "…"
        line += f' — "{q}"'
    return line


def trail_block(p: Project, ids: set[str] | None, start: int) -> str:
    """임시 자취 기획 블록. 주인이나 본 사람이 기획 인물인 앞 화 자취. 먼 화를 먼저 넣고 남은 예산에 가까운 화."""
    name = {c.id: c.name for c in p.characters}
    rows = [t for t in trails.live(p) if t.episode < start
            and (ids is None or t.character in ids or any(w in ids for w in t.witnesses))]
    rows.sort(key=lambda t: t.episode)
    far, used = _spread([t for t in rows if start - t.episode > FAR], name, BUDGET)
    near, _ = _spread([t for t in rows if start - t.episode <= FAR], name, BUDGET - used)
    keep = sorted(far + near, key=lambda t: t.episode)
    if not keep:
        return ""
    head = "[인물이 남긴 자취 (앞 화에서 한 선택 · 말 · 드러냄. 본 사람은 그 자리에서 보거나 들은 인물. 앞이 오래된 것)]"
    return "\n" + head + "\n" + "\n".join(trail_line(t, name) for t in keep)


def with_data(p: Project, tr: list[CharTrail], vw: list[CharView], arm: str, start: int) -> Project:
    """판에 맞게 start 앞 화 줄만 넣은 사본."""
    q = p.model_copy(deep=True)
    q.trails = [t for t in tr if t.episode < start] if "T" in arm else []
    q.views = [v for v in vw if v.episode < start] if "V" in arm else []
    return q


def blocks(p: Project, ids: set[str] | None, start: int) -> str:
    """보는 눈 블록 + 자취 블록 (각각 데이터가 없으면 빈 글)."""
    return charviews.plan_block(p, ids) + trail_block(p, ids, start)


def block_episodes(text: str) -> list[int]:
    return sorted({int(x) for x in re.findall(r"(\d+)화", text)})


# ---------- 기획 ----------

def ref_prompt(q: Project, base: str, start: int) -> str:
    b = blocks(q, REF_PLAN_IDS, start).strip()
    head = f"[이번 화({start}화) 플롯]"
    return base.replace(head, (b + "\n\n" if b else "") + head, 1)


def parse_lines(raw: str, start: int) -> list[dict]:
    out = []
    for line in raw.splitlines():
        parts = [x.strip(" -*`") for x in line.split("|")]
        if len(parts) < 3:
            continue
        m = re.search(r"\d+", parts[1])
        out.append({"plot": start, "character": parts[0], "episode": int(m.group()) if m else 0, "meaning": parts[2]})
    return out[:2]


def saintess_base(out: Path) -> Project:
    """76화를 반영한 직후로 되돌린 nsfw_saintess 사본 (context_measure.rebuild 'exact')."""
    cm = _load_module("context_measure")
    return cm.rebuild(store.load("nsfw_saintess"), PASSAGES["S77"]["start"], "exact")


def run_ref(a, spec: dict, q: Project) -> tuple[str, str, list[dict], str]:
    base = (Path(a.out) / f"base_{a.passage}.txt")
    if not base.exists():
        base.write_text((VIEWS_DIR / spec["base"]).read_text(encoding="utf-8"), encoding="utf-8")
    pp = ref_prompt(q, base.read_text(encoding="utf-8"), spec["start"])
    raw = _make(a.model, a.effort, "plan").text(PLAN_SYS, pp)
    return pp, raw, parse_lines(raw, spec["start"]), blocks(q, REF_PLAN_IDS, spec["start"])


def run_saintess(a, spec: dict, q: Project) -> tuple[str, str, list[dict], str]:
    orig = charviews.plan_block
    seen: list[str] = []

    def patched(p: Project, ids: set[str] | None) -> str:
        seen.append(orig(p, ids) + trail_block(p, ids, spec["start"]))
        return seen[-1]
    prompts.charviews.plan_block = patched
    try:
        pp = prompts.serial_plot_prompt(q, spec["start"], spec["end"], ahead=False, redo=True)
    finally:
        prompts.charviews.plan_block = orig
    got = _make(a.model, a.effort, "plan").json(prompts.SYSTEM_PLANNER, pp, prompts.arc_schema(q, PlotBatch))
    name = {c.id: c.name for c in q.characters}
    rows = [{"plot": e.number, "character": name.get(c.character, c.character), "episode": c.episode, "meaning": c.meaning}
            for e in got.episodes for c in e.carry]
    return pp, got.model_dump_json(indent=1), rows, seen[0] if seen else ""


def cmd_plan(a) -> None:
    spec = PASSAGES[a.passage]
    out = Path(a.out)
    (out / "plans").mkdir(parents=True, exist_ok=True)
    if spec["work"] == "ref":
        base, run = ref_project(), run_ref
    else:
        base, run = saintess_base(out), run_saintess
    tr, vw = clean_work(spec["work"], a.refs, out, spec["start"] - 1)
    q = with_data(base, tr, vw, a.arm, spec["start"])
    for k in range(a.first, a.first + a.runs):
        stem = f"{a.passage}_{a.arm}_{a.model}_{k}"
        if (out / "plans" / f"{stem}.json").exists():
            print(stem, "있음")
            continue
        pp, raw, rows, used = run(a, spec, q)
        (out / "plans" / f"{stem}.prompt.txt").write_text(pp, encoding="utf-8")
        (out / "plans" / f"{stem}.raw.txt").write_text(raw, encoding="utf-8")
        rec = {"passage": a.passage, "arm": a.arm, "model": a.model, "run": k, "carry": rows,
               "block_eps": block_episodes(used)}
        (out / "plans" / f"{stem}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        print(stem, rows, flush=True)


def cmd_blocks(a) -> None:
    """판마다 들어갈 블록 글만 찍는다(LLM 없음). 형식 · 길이 확인용."""
    spec = PASSAGES[a.passage]
    out = Path(a.out)
    base = ref_project() if spec["work"] == "ref" else saintess_base(out)
    tr, vw = clean_work(spec["work"], a.refs, out, spec["start"] - 1)
    q = with_data(base, tr, vw, "TV", spec["start"])
    ids = REF_PLAN_IDS if spec["work"] == "ref" else None
    print(f"자취 {len(q.trails)}줄 · 보는 눈 {len(q.views)}줄")
    print(charviews.plan_block(q, ids))
    print(trail_block(q, ids, spec["start"]))


# ---------- 매김 표 · 셈 ----------

SHEET_COLS = ("id", "passage", "plot", "character", "episode", "dist", "meaning", "o57", "story_absent", "halluc", "note")


def cmd_sheet(a) -> None:
    out = Path(a.out)
    rows, key = [], {}
    for f in sorted((out / "plans").glob("*.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        for c in rec["carry"]:
            rows.append((rec, c))
    random.Random(a.seed).shuffle(rows)
    lines = ["\t".join(SHEET_COLS)]
    for i, (rec, c) in enumerate(rows, 1):
        sid = f"c{i:03d}"
        key[sid] = {"arm": rec["arm"], "model": rec["model"], "run": rec["run"], "block_eps": rec["block_eps"]}
        dist = c["plot"] - c["episode"] if c["episode"] else ""
        lines.append("\t".join(map(str, (sid, rec["passage"], c["plot"], c["character"], c["episode"], dist,
                                         c["meaning"].replace("\t", " "), "", "", "", ""))))
    if (out / "sheet.tsv").exists() and not a.force:
        raise SystemExit("sheet.tsv 가 이미 있어요. 매긴 것을 지우지 않으려면 --force 없이 멈춰요")
    (out / "sheet.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(rows), "줄")


def _flag(v: str) -> bool:
    return v.strip() in ("1", "y", "Y", "o", "O")


def tally(sheet: list[dict], key: dict) -> dict[tuple[str, str, str], dict[str, int]]:
    """(모델, 대목, 판) → 줄 · 먼 화 · 5~7 · 블록에서 옴 · 헛줄."""
    out: dict[tuple[str, str, str], dict[str, int]] = {}
    for r in sheet:
        k = key[r["id"]]
        t = out.setdefault((k["model"], r["passage"], k["arm"]), {"lines": 0, "far": 0, "o57": 0, "block": 0, "halluc": 0})
        t["lines"] += 1
        if _flag(r["halluc"]):
            t["halluc"] += 1
            continue
        ep = int(r["episode"] or 0)
        t["far"] += int(bool(ep) and int(r["plot"]) - ep > FAR)
        t["o57"] += int(_flag(r["o57"]))
        t["block"] += int(_flag(r["story_absent"]) and ep in k["block_eps"])
    return out


def runs_per(out: Path) -> dict[tuple[str, str, str], int]:
    n: dict[tuple[str, str, str], int] = {}
    for f in (out / "plans").glob("*.json"):
        rec = json.loads(f.read_text(encoding="utf-8"))
        k = (rec["model"], rec["passage"], rec["arm"])
        n[k] = n.get(k, 0) + 1
    return n


def cmd_score(a) -> None:
    out = Path(a.out)
    text = (out / "sheet.tsv").read_text(encoding="utf-8").splitlines()
    head = text[0].split("\t")
    sheet = [dict(zip(head, line.split("\t") + [""] * len(head))) for line in text[1:] if line.strip()]
    t = tally(sheet, json.loads((out / "key.json").read_text(encoding="utf-8")))
    runs = runs_per(out)
    md = ["| 모델 | 대목 | 판 | 번 | 줄 | 먼 화 | 5~7 | 블록에서 옴 | 헛줄 |", "|---|---|---|---|---|---|---|---|---|"]
    for k in sorted(runs, key=lambda k: (k[0], k[1], ARMS.index(k[2]))):
        v = t.get(k, {"lines": 0, "far": 0, "o57": 0, "block": 0, "halluc": 0})
        md.append(f"| {k[0]} | {k[1]} | {k[2]} | {runs[k]} | {v['lines']} | {v['far']} | {v['o57']} | {v['block']} | {v['halluc']} |")
    (out / "score.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("collect", "plan", "blocks", "sheet", "score"):
        s = sub.add_parser(name)
        s.add_argument("--out", required=True)
        s.add_argument("--refs", nargs="*", default=["8d46da028a60", "dbfe0e355c16"])
        s.add_argument("--model", default="gemini-3.8-flash")
        s.add_argument("--effort", default="medium")
    sub.choices["collect"].add_argument("--work", required=True)
    sub.choices["collect"].add_argument("--to", type=int, required=True)
    sub.choices["collect"].add_argument("--jobs", type=int, default=6)
    for name in ("plan", "blocks"):
        sub.choices[name].add_argument("--passage", choices=sorted(PASSAGES), required=True)
    sub.choices["plan"].add_argument("--arm", choices=ARMS, required=True)
    sub.choices["plan"].add_argument("--runs", type=int, default=1)
    sub.choices["plan"].add_argument("--first", type=int, default=1)
    sub.choices["sheet"].add_argument("--seed", type=int, default=20261118)
    sub.choices["sheet"].add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    {"collect": cmd_collect, "plan": cmd_plan, "blocks": cmd_blocks, "sheet": cmd_sheet, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    main()

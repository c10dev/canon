"""장면 연출 추출 측정 (docs/stage/specs/03-ai.md '평가'). 측정 세트는 tests/fixtures/stage_eval.json.

사람이 쓴 장면 본문 6개와 정답 본문 장면(StageDraft 모양, 이름)으로 pipeline.extract_stage 를 잰다.
  (a) SpRL 정답률: 정답 박자마다 그 문장까지 읽은 상태를 견준다. 자리(who · ref · rel), 자세(선 자세인지), 접촉(누가 · 누구에게 · 손 또는 부위 · 닿는 부위)
  (b) 규칙 판정 재현율: 모순을 하나 심은 판에서 심은 규칙이 기대한 문장을 짚은 비율
  (c) 헛지적률: 원본에서 나온 규칙 지적 수
  (d) 비용: usage 기록의 토큰과 추정 비용

실행 (실제 Gemini, 키는 Canon 설정을 쓴다):
  CANON_HOME=$(mktemp -d) CANON_LLM_CHECK=gemini python scripts/stage_eval.py --out result.json
가짜 LLM 으로 흐름만: CANON_LLM=mock python scripts/stage_eval.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from canon import pipeline, stage, usage  # noqa: E402
from canon.schema import Character, Episode, EpisodePlot, Meta, Project, StageDraft, StageScene  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "stage_eval.json"


def cases() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def planted(case: dict) -> tuple[str, dict]:
    """모순판: (바꾼 본문, 바꾼 정답)."""
    pl = case["plant"]
    gold = json.loads(json.dumps(case["gold"]))
    b = gold["beats"][pl["beat"] - 1]
    b["quote"], b["bodies"] = pl["to"], pl["bodies"]
    return case["text"].replace(pl["from"], pl["to"], 1), gold


def project(case: dict, text: str) -> tuple[Project, Episode]:
    """사건 하나짜리 화. 방은 고정하려고 같은 사건에 빈 계획 장면을 둔다 (뽑기가 그 방을 쓴다. 칸이 없어 계획과 다른 곳은 없다)."""
    chars = [Character(id=i, name=n, age=a, role=r) for i, n, a, r in case["cast"]]
    ep = Episode(plot=EpisodePlot(number=1, act="기", title=case["id"], summary=case["event"], events=[case["event"]],
                                  characters=[c.id for c in chars], emotional_shift="", ending_hook=""), text=text, status="written")
    p = Project(meta=Meta(title="측정", target_episodes=1), characters=chars, episodes=[ep])
    room = stage.new_room(p, case["room"])
    ep.stage.append(StageScene(id="p0", event=0, event_text=case["event"], room=room.id, cast=[c.id for c in chars], role="plan"))
    return p, ep


def gold_scene(p: Project, ep: Episode, gold: dict) -> StageScene:
    room = p.rooms[0]
    s, _, notes = stage.from_draft(StageDraft.model_validate({"new_anchors": [], **gold}), p, ep, 0, room, "text")  # 정답 세트는 기준점 제안 칸 전에 만들었다
    assert not notes, notes  # 정답은 이름 · 기준점이 모두 맞아야 한다
    return s


def _pos(text: str, quote: str) -> int:
    """문장 끝 위치. 본문에 없으면 -1."""
    i = text.find(quote.strip()) if quote.strip() else -1
    return i + len(quote.strip()) if i >= 0 else -1


def _upto(scene: StageScene, text: str, end: int) -> int:
    """본문 end 글자까지 읽었을 때의 박자 번호: 인용이 그 안에서 끝나는 마지막 박자 (인용을 못 찾은 박자는 앞 박자를 잇는다)."""
    k, at = 0, -1
    for i, b in enumerate(scene.beats, 1):
        q = _pos(text, b.quote)
        if q >= 0:
            at = q
        if 0 <= at <= end:
            k = i
    return k


def _contacts(now: dict) -> set[tuple]:
    return {(w, c.to, "hand" if c.by in stage.HANDS else c.by, c.part.removesuffix("_l").removesuffix("_r"))
            for w, s in now.items() for c in s.contacts.values()}


def _spot(at, room, p) -> tuple:
    if at is None:
        return ("", "")
    ref = at.ref if at.ref.startswith("@") else next((a.name for a in room.anchors if a.id == at.ref), at.ref)
    return (ref, at.rel)


def score(got: StageScene, gold: StageScene, p: Project, text: str) -> dict:
    """정답 박자(시작 상태 포함)마다 같은 문장까지 읽은 상태를 견준다. 정답이 모르는 칸은 세지 않는다.
    접촉 부위는 좌우를 보지 않는다 (본문이 어느 쪽인지 자주 말하지 않는다)."""
    room = p.rooms[0]
    n = {"ref": [0, 0], "ref_rel": [0, 0], "upright": [0, 0], "contact_recall": [0, 0], "contact_precision": [0, 0]}
    for k in range(len(gold.beats) + 1):
        end = 0 if k == 0 else _pos(text, gold.beats[k - 1].quote)
        g, x = stage.state_at(gold, k), stage.state_at(got, 0 if k == 0 else _upto(got, text, end))
        for w, gs in g.items():
            xs = x.get(w)
            if gs.at is not None:
                gr, xr = _spot(gs.at, room, p), _spot(xs.at if xs else None, room, p)
                n["ref"][1] += 1
                n["ref"][0] += gr[0] == xr[0]
                n["ref_rel"][1] += 1
                n["ref_rel"][0] += gr == xr
            if gs.posture in stage.POSTURES:
                n["upright"][1] += 1
                n["upright"][0] += bool(xs and xs.posture in stage.POSTURES and
                                        stage.POSTURES[xs.posture].upright == stage.POSTURES[gs.posture].upright)
        gc, xc = _contacts(g), _contacts(x)
        n["contact_recall"][1] += len(gc)
        n["contact_recall"][0] += len(gc & xc)
        n["contact_precision"][1] += len(xc)
        n["contact_precision"][0] += len(gc & xc)
    return n


def rule_issues(p: Project, ep: Episode, scene: StageScene) -> list:
    return stage.to_issues(scene, p.rooms[0], p, 1, ep.text, 0)


def hit(issues: list, expect: dict) -> bool:
    return any(any(pipeline._same_quote(i.current_quote, q) for q in expect["quotes"]) and
               stage.RULES[expect["rule"]] in i.description for i in issues)


def _limited(fn, limit: float):
    """fn 을 limit 초 안에 끝내지 못하면 TimeoutError (응답 없이 멈춘 호출을 건너뛴다. 스레드는 버린다)."""
    import contextvars
    import threading

    box: dict = {}
    ctx = contextvars.copy_context()  # usage.scope 를 넘긴다

    def go():
        try:
            box["out"] = ctx.run(fn)
        except BaseException as e:  # noqa: BLE001
            box["err"] = e
    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(limit)
    if t.is_alive():
        raise TimeoutError(f"{limit:g}초 안에 응답이 없었어요")
    if "err" in box:
        raise box["err"]
    return box["out"]


def run(llm, tries: int = 2, log=print, limit: float = 300) -> dict:
    """원본 · 모순판마다 뽑기 한 번 (실패하면 tries 번까지). 결과와 합계."""
    rows, total = [], {k: [0, 0] for k in ("ref", "ref_rel", "upright", "contact_recall", "contact_precision")}
    for case in cases():
        for variant in ("orig", "plant"):
            text, gold = (case["text"], case["gold"]) if variant == "orig" else planted(case)
            p, ep = project(case, text)
            g = gold_scene(p, ep, gold)
            row = {"id": case["id"], "variant": variant}
            t0 = time.perf_counter()
            for attempt in range(1, tries + 1):
                try:
                    with usage.scope(project="stage-eval", episode=1, task=f"{case['id']}:{variant}", attempt=attempt):
                        prop = _limited(lambda: pipeline.extract_stage(llm, p, 1, 0), limit)
                    break
                except Exception as e:  # 응답 형식 오류 · 시간 초과. 다시 한 번
                    row["error"] = f"{type(e).__name__}: {e}"[:300]
                    prop = None
            row["seconds"] = round(time.perf_counter() - t0, 1)
            if prop is None:
                rows.append(row)
                log(f"{case['id']} {variant}: 실패 {row['error']}")
                continue
            row.pop("error", None)
            got = prop.scene
            s = score(got, g, p, text)
            for k, v in s.items():
                total[k][0] += v[0]
                total[k][1] += v[1]
            issues = rule_issues(p, ep, got)
            row.update(score=s, beats=len(got.beats), notes=prop.notes, dropped=prop.dropped,
                       issues=[{"quote": i.current_quote, "text": i.description} for i in issues],
                       scene=got.model_dump(include={"cast", "start", "beats"}))
            if variant == "plant":
                row["found"] = hit(issues, case["plant"]["expect"])
                row["kind"] = case["plant"]["kind"]
            rows.append(row)
            log(f"{case['id']} {variant}: 박자 {len(got.beats)}, 규칙 지적 {len(issues)}" + (f", 심은 것 {'찾음' if row.get('found') else '놓침'}" if variant == "plant" else ""))
    plants = [r for r in rows if r["variant"] == "plant" and "score" in r]
    origs = [r for r in rows if r["variant"] == "orig" and "score" in r]
    return {"rows": rows, "total": total,
            "rate": {k: round(v[0] / v[1], 3) if v[1] else None for k, v in total.items()},
            "recall": [sum(r["found"] for r in plants), len(plants)],
            "false_alarms": [sum(len(r["issues"]) for r in origs), len(origs)]}


def cost(since: str) -> dict:
    rows = [r for r in usage.read() if r.get("project") == "stage-eval" and r.get("at", "") >= since]
    table = usage.prices()
    money = [usage.row_cost(r, table)[0] for r in rows]
    return {"calls": len(rows), "ok": sum(bool(r.get("ok")) for r in rows), "in": sum(r.get("in", 0) for r in rows),
            "out": sum(r.get("out", 0) + r.get("thought", 0) for r in rows), "cached": sum(r.get("cached", 0) for r in rows),
            "usd": None if any(m is None for m in money) else round(sum(money), 4),
            "models": sorted({r.get("model", "") for r in rows})}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", help="결과 JSON 파일")
    ap.add_argument("--tries", type=int, default=2)
    ap.add_argument("--limit", type=float, default=300, help="호출 하나의 시간 제한(초)")
    a = ap.parse_args()
    from datetime import datetime
    from canon.llm import get_llm

    since = datetime.now().astimezone().isoformat(timespec="seconds")
    res = run(get_llm("check"), a.tries, limit=a.limit)
    res["cost"] = cost(since)
    res["at"] = since
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, ensure_ascii=False, indent=1))
    if a.out:
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

"""레퍼런스 원고의 구조 보기와 아크 나누기 (canon/refdigest.py 의 pace · run_arcs). 원고는 tests/fixtures/refs_story.txt."""
import time
from pathlib import Path

import pytest

from canon import context, prompts, refdigest, refs
from canon.llm import get_llm
from canon.schema import RefCut

STORY = (Path(__file__).parent / "fixtures" / "refs_story.txt").read_text(encoding="utf-8")


def _book():
    d = refs.preview(STORY, repeats=[])
    cuts = [RefCut(**{k: c[k] for k in ("line", "body", "head", "label", "title", "kind")}) for c in d["cuts"] if c["on"]]
    return refs.create("등대", STORY, cuts, rights=True)


def _row(n, kind="대화", tension=3, cast=()):
    return {"n": n, "label": f"{n}화", "chars": 5000, "dialogue": 0.3, "basis": f"b{n}", "kind": kind, "tension": tension, "hook": "여운",
            "events": [f"{n}화 첫 사건이다. 둘째 문장.", f"{n}화 둘째 사건"], "ending": f"{n}화가 끝난다. 덧붙임.", "place": "등대", "cast": list(cast)}


def test_cast_table_merges_short_names_and_drops_generic_words():
    rows = [_row(1, cast=["서지아", "서술자"]), _row(2, cast=["지아", "강주혁"]), _row(3, cast=["주혁", "남자"]), _row(4, cast=["서지아", "김지아"])]
    got = {c["name"]: (c["episodes"], c["first"]) for c in refdigest.cast_table(rows)}
    assert got == {"서지아": (3, 1), "강주혁": (2, 2), "김지아": (1, 4)}  # '지아'는 더 많이 나온 '서지아'로, 부름말은 뺀다


def test_pace_is_empty_before_reading_and_summarises_after(client):
    b = _book()
    assert refdigest.pace(b.id) == {"episodes": 0, "blocks": [], "peaks": [], "kinds": [], "tension": [], "cast": []}
    refdigest.run(b.id, refdigest.llm_for(b.id))
    p = refdigest.pace(b.id)
    assert p["episodes"] == 14 and p["block_size"] == 5 and [x["episodes"] for x in p["blocks"]] == [5, 5, 4]
    assert p["blocks"][0]["from"] == "프롤로그" and p["blocks"][0]["start"] == 1 and 1 <= p["blocks"][0]["tension"] <= 5
    assert sum(n for _, n in p["kinds"]) == 14 and sum(n for _, n in p["tension"]) == 14 and "hook" not in p
    r = client.get(f"/api/refs/{b.id}/digest/pace").json()
    assert r["episodes"] == 14 and r["arcs"] == {"plan": None, "stale": False, "labels": {str(x["n"]): x["label"] for x in refdigest._rows(b, refdigest.load(b.id))}}


def test_arcs_need_every_episode_read(client):
    b = _book()
    with pytest.raises(ValueError, match="읽히지 않은 화가 14개"):
        refdigest.arcs_ready(b.id)
    assert client.post(f"/api/refs/{b.id}/digest/arcs").status_code == 400
    assert client.get(f"/api/refs/{b.id}/digest/arcs/estimate").status_code == 400


def test_run_arcs_covers_every_episode_and_goes_stale(client):
    b = _book()
    refdigest.run(b.id, refdigest.llm_for(b.id))
    est = refdigest.arcs_estimate(b.id)
    assert est["episodes"] == 14 and est["provider"] == "mock" and est["usd"] == 0.0 and not est["folded"]
    assert refdigest.run_arcs(b.id, get_llm("plan")) == {"arcs": 2, "parts": 2}
    v = refdigest.arcs_view(b.id)
    arcs = v["plan"]["arcs"]
    assert not v["stale"] and (arcs[0]["start_ep"], arcs[-1]["end_ep"]) == (1, 14) and arcs[0]["end_ep"] + 1 == arcs[1]["start_ep"]
    assert all(len(a["acts"]) == 4 for a in arcs) and "유령" not in arcs[0]["cast"] and arcs[1]["climax_ep"] == 0
    assert v["labels"]["1"] == "프롤로그" and v["plan"]["by"] == "ai"
    # 화 카드가 바뀌면 낡은 아크다
    cuts = sorted(refs.load(b.id).cuts, key=lambda c: c.line)
    refs.update(b.id, cuts=cuts[:2] + cuts[3:])
    refdigest.run(b.id, refdigest.llm_for(b.id))
    assert refdigest.arcs_view(b.id)["stale"]
    refdigest.clear_arcs(b.id)
    assert refdigest.arcs_view(b.id)["plan"] is None


def test_arcs_job_and_clear_api(client):
    b = _book()
    refdigest.run(b.id, refdigest.llm_for(b.id))
    j = client.post(f"/api/refs/{b.id}/digest/arcs").json()
    assert j["kind"] == "ref_arcs" and j["target"] == b.id
    end = time.time() + 10
    while time.time() < end:
        cur = next(x for x in client.get("/api/jobs").json() if x["id"] == j["id"])
        if cur["status"] != "running":
            break
        time.sleep(0.02)
    assert cur["status"] == "done" and cur["result"] == {"arcs": 2, "parts": 2}
    assert len(client.get(f"/api/refs/{b.id}/digest/pace").json()["arcs"]["plan"]["arcs"]) == 2
    assert client.delete(f"/api/refs/{b.id}/digest/arcs").json() == {"ok": True}
    assert client.get(f"/api/refs/{b.id}/digest/pace").json()["arcs"]["plan"] is None


def test_arcs_prompt_folds_under_the_budget():
    few = prompts.ref_arcs_prompt([_row(n) for n in range(1, 6)], ["서윤"])
    assert "## 1번 · 1화 [대화 · 긴장 3]" in few and "사건: 1화 첫 사건이다. 둘째 문장. / 1화 둘째 사건" in few and "끝: 1화가 끝난다. 덧붙임." in few
    assert "# 인물\n서윤" in few and "1번부터 5번까지 빈틈없이" in few and "화 이름으로 부릅니다" in few and "세부(누가 했는지, 차례)가 틀릴 수 있습니다" in few
    many = prompts.ref_arcs_prompt([_row(n) for n in range(1, 601)], [])
    assert "## 600번 · 600화" in many and "화가 600개라 화마다 첫 사건과 끝 첫 문장만" in many and "둘째 사건" not in many
    assert len(many) <= context.BUDGET["ref_arcs"] + 2000
    huge = prompts.ref_arcs_prompt([_row(n) for n in range(1, 1501)], [])
    assert "화마다 첫 사건만 넣었습니다" in huge and "## 1500번 · 1500화" in huge and "끝난다" not in huge

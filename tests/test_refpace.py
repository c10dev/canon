"""레퍼런스 원고의 구조 보기와 아크 나누기 (canon/refdigest.py 의 pace · run_arcs). 원고는 tests/fixtures/refs_story.txt."""
import json
import re
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
    labels = {str(x["n"]): x["label"] for x in refdigest._rows(b, refdigest.load(b.id))}
    assert r["episodes"] == 14 and r["arcs"] == {"plan": None, "stale": False, "offer": None, "orders": list(range(1, 15)), "labels": labels}


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
    assert refdigest.run_arcs(b.id, get_llm("plan")) == {"arcs": 2, "parts": 2, "offer": False}
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
    assert cur["status"] == "done" and cur["result"] == {"arcs": 2, "parts": 2, "offer": False}
    assert len(client.get(f"/api/refs/{b.id}/digest/pace").json()["arcs"]["plan"]["arcs"]) == 2
    assert client.delete(f"/api/refs/{b.id}/digest/arcs").json() == {"ok": True}
    assert client.get(f"/api/refs/{b.id}/digest/pace").json()["arcs"]["plan"] is None


def _arc(title, start, end, **kw):
    return {"title": title, "start_ep": start, "end_ep": end, **kw}


def test_author_edits_arcs_and_the_next_ai_plan_waits_as_an_offer(client):
    b = _book()
    refdigest.run(b.id, refdigest.llm_for(b.id))
    refdigest.run_arcs(b.id, get_llm("plan"))
    url = f"/api/refs/{b.id}/digest/arcs"
    # 빈틈(5~6)과 겹침(9~10)을 두고 저장한다: 빈틈없이 맞추고 맞춘 것을 적는다
    body = {"parts": [], "arcs": [_arc(" 만남 ", 1, 4, goal="서로를 알아본다", climax_ep=3), _arc("", 7, 10, conflict="막는 사람", climax_ep=2),
                                  _arc("끝", 9, 14, payoff="화해", climax_ep=14)]}
    v = client.put(url, json=body).json()
    arcs = v["plan"]["arcs"]
    assert [(a["title"], a["start_ep"], a["end_ep"], a["climax_ep"]) for a in arcs] == [("만남", 1, 4, 3), ("아크 2", 5, 10, 0), ("끝", 11, 14, 14)]
    assert v["plan"]["by"] == "both" and v["plan"]["parts"] == [] and any("빈틈없이" in n for n in v["plan"]["notes"])
    assert arcs[0]["goal"] == "서로를 알아본다" and all(len(a["acts"]) == 4 for a in arcs) and not v["stale"] and v["offer"] is None
    # 다시 열어도 그대로다
    assert client.get(f"/api/refs/{b.id}/digest/pace").json()["arcs"]["plan"]["arcs"] == arcs
    # 고친 아크가 있으면 새 AI 안은 덮지 않고 제안으로 둔다
    assert refdigest.run_arcs(b.id, get_llm("plan")) == {"arcs": 2, "parts": 2, "offer": True}
    v = refdigest.arcs_view(b.id)
    assert len(v["plan"]["arcs"]) == 3 and v["plan"]["by"] == "both" and len(v["offer"]["arcs"]) == 2 and v["offer"]["by"] == "ai"
    # 버리면 고친 아크가 남는다
    v = client.post(f"{url}/offer", json={"take": False}).json()
    assert v["offer"] is None and len(v["plan"]["arcs"]) == 3
    assert client.post(f"{url}/offer", json={"take": False}).status_code == 400
    # 고르면 AI 안으로 바뀐다
    refdigest.run_arcs(b.id, get_llm("plan"))
    v = client.post(f"{url}/offer", json={"take": True}).json()
    assert v["offer"] is None and len(v["plan"]["arcs"]) == 2 and v["plan"]["by"] == "ai" and not v["stale"]
    # 지우면 제안도 함께 지운다
    client.put(url, json=body)
    refdigest.run_arcs(b.id, get_llm("plan"))
    client.delete(url)
    v = refdigest.arcs_view(b.id)
    assert v["plan"] is None and v["offer"] is None
    assert client.put(url, json={"parts": [], "arcs": []}).status_code == 400


def test_author_can_split_arcs_from_nothing_before_every_episode_is_read(client):
    b = _book()
    v = client.put(f"/api/refs/{b.id}/digest/arcs", json={"arcs": [_arc("앞", 1, 6), _arc("뒤", 7, 14)], "parts": [_arc("1부", 1, 14)]}).json()
    assert v["plan"]["by"] == "author" and [a["end_ep"] for a in v["plan"]["arcs"]] == [6, 14] and v["plan"]["parts"][0]["title"] == "1부"
    assert v["plan"]["model"] == "" and v["plan"]["notes"] == []
    # 작가가 처음부터 나눈 아크도 AI 안이 덮지 않는다
    refdigest.run(b.id, refdigest.llm_for(b.id))
    assert refdigest.run_arcs(b.id, get_llm("plan"))["offer"] and refdigest.arcs_view(b.id)["plan"]["by"] == "author"


def test_arcs_skip_excluded_episodes(client):
    b = _book()
    cuts = sorted(refs.load(b.id).cuts, key=lambda c: c.line)
    gone = 7  # 일곱째 화를 제외한다
    cuts[gone - 1].kind = "skip"
    orders = refdigest._orders(refs.update(b.id, cuts=cuts))
    assert gone not in orders and len(orders) == 13
    k = orders.index(gone + 1)
    v = client.put(f"/api/refs/{b.id}/digest/arcs", json={"arcs": [_arc("앞", orders[0], gone), _arc("뒤", gone, orders[-1], climax_ep=gone)]}).json()
    a, z = v["plan"]["arcs"]
    assert a["end_ep"] == orders[k - 1] and z["start_ep"] == orders[k] and z["climax_ep"] == 0 and v["orders"] == orders
    assert str(gone) not in v["labels"] and v["plan"]["notes"] == []


def test_digest_file_without_offer_fields_still_loads(client):
    b = _book()
    refdigest.run(b.id, refdigest.llm_for(b.id))
    refdigest.run_arcs(b.id, get_llm("plan"))
    f = refdigest._path(b.id)
    raw = json.loads(f.read_text(encoding="utf-8"))
    raw.pop("arc_offer"), raw.pop("arc_offer_basis")
    f.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    assert refdigest.arcs_view(b.id)["offer"] is None and len(refdigest.arcs_view(b.id)["plan"]["arcs"]) == 2


def test_arcs_prompt_folds_under_the_budget():
    few = prompts.ref_arcs_prompt([_row(n) for n in range(1, 6)], ["서윤"])
    assert "## 1번 · 1화 [대화 · 긴장 3]" in few and "사건: 1화 첫 사건이다. 둘째 문장. / 1화 둘째 사건" in few and "끝: 1화가 끝난다. 덧붙임." in few
    assert "# 인물\n서윤" in few and "1번부터 5번까지 빈틈없이" in few and "화 이름으로 부릅니다" in few and "세부(누가 했는지, 차례)가 틀릴 수 있습니다" in few
    many = prompts.ref_arcs_prompt([_row(n) for n in range(1, 601)], [])
    assert "## 600번 · 600화" in many and "화가 600개라 화마다 첫 사건과 끝 첫 문장만" in many and "둘째 사건" not in many
    assert len(many) <= context.BUDGET["ref_arcs"] + 2000
    huge = prompts.ref_arcs_prompt([_row(n) for n in range(1, 1501)], [])
    assert "화마다 첫 사건만 넣었습니다" in huge and "## 1500번 · 1500화" in huge and "끝난다" not in huge


# ---------- 화면 (static/refs.js 의 아크 고치기) ----------

from .jsvm import STATIC, needs_node, run_js  # noqa: E402

JS_FILES = re.findall(r'src="/static/([a-z0-9-]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))


@needs_node
def test_js_arc_steps_over_excluded_episodes_and_halves():
    orders = [1, 2, 3, 5, 6, 9]  # 4 · 7 · 8번째 화는 제외
    got = run_js(JS_FILES, "[refArcStep(data, 3, 1), refArcStep(data, 5, -1), refArcStep(data, 9, 1), refArcStep(data, 4, 1)]", orders)
    assert got == [5, 3, 0, 0]
    arc = {"title": "앞", "start_ep": 1, "end_ep": 9, "climax_ep": 6, "cast": ["서윤"], "goal": "목표"}
    a, b = run_js(JS_FILES, "refArcHalves(data.arc, data.orders)", {"arc": arc, "orders": orders})
    assert (a["start_ep"], a["end_ep"], a["climax_ep"], a["goal"]) == (1, 3, 0, "목표")
    assert (b["start_ep"], b["end_ep"], b["climax_ep"], b["title"], b["cast"]) == (5, 9, 6, "새 아크", ["서윤"])
    assert run_js(JS_FILES, "refArcHalves(data.arc, data.orders)", {"arc": {**arc, "start_ep": 9}, "orders": orders}) is None
    assert run_js(JS_FILES, "refArcSpan({start_ep: 5, end_ep: 9}, {5: '4화', 9: '6화'})", None) == "4화~6화"

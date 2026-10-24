"""단편 → 장편 재구성 테스트 (mock LLM). 실행: python -m pytest tests"""
import importlib

import pytest
from fastapi.testclient import TestClient

from canon import pipeline, prompts
from canon.schema import RebuildEpisode, Storyline
from tests.test_convert import LLM, _short


def _rebuilt(written=8, total=200):
    p = _short(written=written)
    el = p.elements[0]
    el.since_ep, el.reveal_ep, el.episodes = 3, 12, [3, 12]
    p.storylines.append(Storyline(id="sl-01", title="도현의 빚", branch_ep=6, join_ep=12))
    p.episode(7).plot.storyline = "sl-01"
    snap0 = p.snapshot(0).model_copy(deep=True)
    prop = pipeline.propose_rebuild(LLM, p, total)
    before, notes = pipeline.apply_rebuild(p, prop, at="2026-10-22T00:00:00+00:00")
    return p, before, notes, snap0, prop


def test_propose_cleans_map():
    p = _short(written=8)
    lo, default, hi = pipeline.rebuild_span(p)
    assert (lo, default, hi) == (12, 36, 120)
    prop = pipeline.propose_rebuild(LLM, p, 200, ending_at="part")
    assert prop.ending_at == "part"  # 작가가 고른 결말 위치가 이긴다
    assert [(a.number, a.start_ep, a.end_ep) for a in prop.arcs] == [(1, 1, 18), (2, 19, 36)]
    assert [x.number for x in prop.episodes] == list(range(1, 37))  # 1화부터 마지막 아크 끝까지 빠짐없이
    assert "nobody" not in prop.arcs[0].cast
    m = {x.number: x for x in prop.episodes}
    assert (m[1].use, m[2].use, m[3].use) == ("new", "keep", "revise")
    assert m[4].use == "rewrite" and m[4].sources == [3, 4]  # 옛 화 둘을 그대로 둘 수는 없다
    assert "[4]화는 옛 본문을 그대로 쓸 수 없어" in prop.reply
    assert m[18].sources == [12]  # 단편 결말은 첫 아크 끝으로
    assert prop.dropped == []
    assert prop.parts[0].end_ep >= 36 and prop.parts[-1].end_ep == 200
    assert [t.id for t in prop.tiers] == ["ally"]
    assert [f.id for f in prop.foreshadows] == ["fs-r-door"]


def test_clean_rules():
    p = _short(written=8)
    prop = pipeline.propose_rebuild(LLM, p, 200)
    prop.episodes = [x for x in prop.episodes if x.number != 20]  # 빠진 화
    prop.episodes[5].sources = [2, 99]  # 없는 옛 화, 이미 다듬기에 쓴 옛 화
    prop.episodes[5].use = "keep"
    prop.episodes.append(RebuildEpisode(number=500, title="범위 밖", summary="", use="new"))
    c = pipeline.clean_rebuild(p, prop)
    m = {x.number: x for x in c.episodes}
    assert m[20].use == "new" and "[20]화는 새 화로 채웠어요" in c.reply
    assert m[6].sources == [2] and m[6].use == "rewrite"
    assert 500 not in m and len(c.episodes) == 36
    assert c.dropped == [6]  # 이제 아무 화도 쓰지 않는 옛 화
    prop.arcs[1].start_ep = 20
    with pytest.raises(ValueError, match="아크 2가 20화에서 시작"):
        pipeline.clean_rebuild(p, prop)
    with pytest.raises(ValueError, match="결말 위치"):
        pipeline.propose_rebuild(LLM, p, 200, ending_at="middle")
    with pytest.raises(ValueError, match="12~120화"):
        pipeline.propose_rebuild(LLM, p, 200, span=8)


def test_apply_resets_state_and_moves_episodes():
    p, before, notes, snap0, prop = _rebuilt()
    assert before.meta.form == "short" and len(before.episodes) == 12 and before.history
    assert p.serial and p.meta.target_episodes == 200 and p.arc == [] and len(p.story_arcs) == 2
    assert p.conversion.mode == "rebuild" and p.conversion.history == 0 and p.conversion.ending == "arc"
    # 상태 · 관계는 1화 시작 전으로
    assert p.history == [] and p.events == []
    assert [s.model_dump() for s in p.states] == [s.model_dump() for s in snap0.states]
    assert [t.model_dump() for t in p.ties] == [t.model_dump() for t in snap0.ties]
    assert p.secrets == [] and p.facts == snap0.facts
    assert [f.id for f in p.foreshadows] == ["fs-r-door"]
    assert [s.episode for s in p.snapshots] == [0]
    assert next(c for c in p.characters if c.id == "ally").tier == "support"
    # 옛 화는 보관함에 그대로
    assert [e.text for e in p.archive.episodes] == [e.text for e in before.episodes]
    assert len(p.archive.history) == 8
    # 그대로 · 다듬기는 옛 본문, 나머지는 플롯 초안 자리
    e2, e3, e4 = p.episode(2), p.episode(3), p.episode(4)
    assert e2.text == "1화 본문. 바람이 불었다." and e2.status == "written" and e2.plot.number == 2
    assert e2.plot.title == before.episode(1).plot.title
    assert e3.text == "2화 본문. 바람이 불었다." and e3.status == "written"
    assert e4.text == "" and e4.status == "draft" and e4.plot.events == [] and e4.plot.title == prop.episodes[3].title
    assert p.episode(1).status == "draft" and len(p.episodes) == 36
    assert p.act_for(2).name == e2.plot.act
    # 인과율 · 줄기는 새 화 번호로
    el = p.elements[0]
    assert (el.since_ep, el.reveal_ep, el.episodes) == (4, 18, [4, 18])
    sl = p.storylines[0]
    assert (sl.branch_ep, sl.join_ep) == (6, 18)
    assert notes == []


def test_lost_numbers_are_reported():
    p = _short(written=8)
    p.elements[0].reveal_ep = 12
    prop = pipeline.propose_rebuild(LLM, p, 200)
    for x in prop.episodes:  # 결말 화를 버린다
        if 12 in x.sources:
            x.sources, x.use = [], "new"
    _, notes = pipeline.apply_rebuild(p, prop)
    assert 12 in p.archive.dropped
    assert any("등대" in n for n in notes) and any("쓰지 않는 옛 화" in n for n in notes)


def test_kept_episode_reuses_old_delta():
    p, before, *_ = _rebuilt()
    with pytest.raises(ValueError):  # 새 1화가 아직 없다
        pipeline.extract_state(LLM, p, 1)
    e1 = p.episode(1)
    e1.text, e1.status = "새 1화 본문", "written"
    pipeline.apply_delta(p, pipeline.extract_state(LLM, p, 1))
    d = pipeline.extract_state(LLM, p, 2)  # 그대로 둔 화: AI 를 부르지 않는다
    old = before.history[0]
    assert d.episode == 2 and d.summary == old.summary
    assert "단편 1화 때 승인한 변경안" in d.warnings[0]
    assert all(e.episode == 2 for e in d.events) and [f.planted_ep for f in d.foreshadow_planted] == [2]
    assert p.archive.history[0].episode == 1  # 보관함 원본은 그대로
    pipeline.apply_delta(p, d)
    assert p.episode(2).status == "finalized"
    # 본문을 고치면 옛 변경안을 쓰지 않는다
    assert pipeline.carried_delta(p, 3) is not None
    p.episode(3).text += " 덧붙임."
    assert pipeline.carried_delta(p, 3) is None
    assert pipeline.carried_delta(p, 4) is None  # 새로 쓰는 화


def test_prompts_use_map_and_material():
    p, *_ = _rebuilt()
    plan = prompts.serial_plot_prompt(p, 1, 18)
    block = prompts.rebuild_map_block(p, 1, 18)
    assert "[재구성 지도" in block and "2화 [옛 본문 그대로]" in block and "단편 1화" in block
    assert "본문이 이미 있어 플롯 고정" in block and "[본문이 있는 화의 플롯" in block
    assert "[재구성 지도" in plan and "2화 [옛 본문 그대로]" in plan
    assert "옛 화:" not in prompts.rebuild_map_block(p, 19, 36)  # 아크 2는 새 화뿐
    # 재료로 새로 쓰는 화는 옛 원고가 들어간다
    mat = prompts.material_block(p, 5)
    assert "# 원고 재료" in mat and "5화 본문" in mat and "살릴 것" in mat
    assert "(본문 없음." in prompts.material_block(p, 9)  # 옛 화에 본문이 없으면 플롯 요약으로
    assert prompts.material_block(p, 2) == "" and prompts.material_block(p, 1) == ""
    # 플롯 초안은 본문이 있는 화를 덮지 않는다
    pipeline.apply_plots(p, pipeline.draft_plots(LLM, p, 1, 18))
    assert p.episode(2).text and p.episode(2).plot.title == p.archive.source(1).plot.title
    assert p.episode(4).plot.events
    text = prompts.rebuild_prompt(_short(written=8), 200, 36, "series", "북쪽으로")
    assert "1~36화" in text and "작품의 결말" in text and "북쪽으로" in text and "1~3화" in text


def test_rework():
    p, before, *_ = _rebuilt()
    with pytest.raises(ValueError, match="다듬기로 고른 화가 아니에요"):
        pipeline.propose_rework(LLM, p, 2)
    rw = pipeline.propose_rework(LLM, p, 3)
    assert rw.text.startswith("2화 본문") and rw.text != p.episode(3).text
    assert prompts.rework_prompt(p, 3).count("2화 본문") >= 1
    assert pipeline.undo_blockers(p, before) == []
    edit = pipeline.accept_rework(p, 3, rw.text + " 손봄", rw.text)
    assert p.episode(3).text.endswith("손봄") and edit.source == "ai" and edit.proposed == rw.text
    assert "도현" in edit.instruction
    assert "본문" in pipeline.undo_blockers(p, before)[0]  # 다듬은 본문은 옛 원고 어디에도 없다
    with pytest.raises(ValueError, match="되돌릴 수 없어요"):
        pipeline.undo_conversion(p, before)


def test_undo_right_after_rebuild():
    p, before, *_ = _rebuilt()
    back = pipeline.undo_conversion(p, before)
    assert not back.serial and back.archive is None and back.conversion is None
    assert len(back.history) == 8 and [e.plot.number for e in back.episodes] == list(range(1, 13))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store, web

    importlib.reload(store)
    importlib.reload(web)
    return TestClient(web.app), store


def test_web_rebuild_flow(client):
    c, store = client
    from tests.test_web import _wait

    store.save("lh", _short(written=8))
    st = c.get("/api/projects/lh/convert").json()
    assert st["rebuild"] == {"min": 12, "default": 36, "max": 120}
    assert c.post("/api/projects/lh/jobs", json={"kind": "rebuild", "length": 200, "span": 5}).status_code == 400
    j = _wait(c, c.post("/api/projects/lh/jobs", json={"kind": "rebuild", "length": 200, "span": 24, "ending": "series"}).json()["id"])
    assert j["status"] == "done", j
    prop = j["result"]
    assert prop["ending_at"] == "series" and prop["arcs"][-1]["end_ep"] == 24
    prop["tiers"] = []
    out = c.post("/api/projects/lh/convert/rebuild/apply", json=prop).json()
    p = out["project"]
    assert p["meta"]["form"] == "serial" and p["conversion"]["mode"] == "rebuild" and len(p["episodes"]) == 24
    assert p["archive"]["map"][2]["use"] == "revise"
    assert store.backup_path("lh", "before-serial").exists()
    assert c.get("/api/projects/lh/convert").json()["undo_blockers"] == []
    assert c.put("/api/projects/lh", json=p).status_code == 200  # 장편 검사를 통과한다

    assert c.post("/api/projects/lh/jobs", json={"kind": "rework", "ep": 2}).status_code == 400
    j = _wait(c, c.post("/api/projects/lh/jobs", json={"kind": "rework", "ep": 3}).json()["id"])
    assert j["status"] == "done", j
    p = c.post("/api/projects/lh/episodes/3/rework", json={"text": j["result"]["text"], "proposed": j["result"]["text"]}).json()
    ep3 = next(e for e in p["episodes"] if e["plot"]["number"] == 3)
    assert ep3["text"] == j["result"]["text"] and ep3["edits"][-1]["source"] == "ai"
    assert c.get("/api/projects/lh/convert").json()["undo_blockers"]
    assert c.post("/api/projects/lh/convert/undo").status_code == 400

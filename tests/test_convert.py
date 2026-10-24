"""단편 → 장편 전환 테스트 (mock LLM). 실행: python -m pytest tests"""
import importlib

import pytest
from fastapi.testclient import TestClient

from canon import pipeline, prompts
from canon.mock import MockLLM
from canon.schema import Foreshadow, Project, StoryElement, Storyline

LLM = MockLLM()


def _short(total=12, written=12) -> Project:
    """단편을 만들고 앞 written 화를 써서 상태까지 반영한다."""
    p = Project()
    p.meta.title, p.meta.target_episodes = "등대", total
    pipeline.apply_setup(p, pipeline.suggest_setup(LLM, p))
    p.arc = pipeline.plan_arc(LLM, p).acts
    pipeline.apply_plots(p, pipeline.draft_plots(LLM, p, 1, total))
    for e in p.episodes:
        e.status = "confirmed"
    p.elements.append(StoryElement(id="el-1", kind="장소", name="등대", description="10년 전 폐쇄"))
    for n in range(1, written + 1):
        e = p.episode(n)
        e.text, e.status = f"{n}화 본문. 바람이 불었다.", "written"
        pipeline.apply_delta(p, pipeline.extract_state(LLM, p, n))
    return p


def test_finished_short_becomes_arc_one():
    p = _short()
    acts = [a.model_dump() for a in p.arc]
    texts = [e.text for e in p.episodes]
    ties, events = [t.model_dump() for t in p.ties], len(p.events)
    prop = pipeline.propose_conversion(LLM, p, 200, "keep")
    assert prop.ending == "keep" and prop.total_episodes == 200
    a = prop.arc
    assert (a.number, a.start_ep, a.end_ep) == (1, 1, 12)
    assert [x.model_dump() for x in a.acts] == acts  # 단편 기승전결을 그대로 옮긴다
    assert "nobody" not in a.cast  # 없는 인물은 뺀다
    assert a.summary  # 다 쓴 단편은 아크 1 요약까지 제안
    assert prop.parts[0].start_ep == 1 and prop.parts[-1].end_ep == 200 and prop.parts[0].end_ep >= 12
    assert [t.id for t in prop.tiers] == ["ally"]
    assert not prop.foreshadows and not prop.episodes

    before = pipeline.apply_conversion(p, prop)
    assert before.meta.form == "short" and before.arc and not before.story_arcs
    assert p.serial and p.meta.target_episodes == 200 and p.arc == []
    assert [x.model_dump() for x in p.story_arcs[0].acts] == acts
    assert p.story_arcs[0].summary and p.parts == prop.parts
    assert [e.text for e in p.episodes] == texts and [e.status for e in p.episodes] == ["finalized"] * 12
    assert [t.model_dump() for t in p.ties] == ties and len(p.events) == events
    assert p.elements[0].name == "등대" and p.style == before.style
    assert next(c for c in p.characters if c.id == "ally").tier == "support"
    assert p.conversion.from_total == 12 and p.conversion.arc_end == 12 and p.conversion.history == 12
    assert p.act_for(5).name == before.act_for(5).name  # 화의 소속 구간이 그대로

    # 장편 흐름이 이어진다: 다음 아크는 13화부터, 줄거리는 아크 1 요약으로 접힌다
    nxt = pipeline.plan_next_arc(LLM, p)
    assert nxt.arc.start_ep == 13 and nxt.arc.number == 2
    pipeline.apply_arc(p, nxt)
    assert "[아크 1" in prompts.story_so_far(p, 30)
    assert pipeline.pending_recaps(p) == []


def test_reopen_unfinished_short_keeps_written_text():
    p = _short(written=8)
    p.foreshadows.append(Foreshadow(id="fs-old", description="낡은 지도", planted_ep=3))
    p.storylines.append(Storyline(id="sl-01", title="도현의 빚", branch_ep=6, join_ep=10))
    p.episode(9).plot.storyline = "sl-01"
    prop = pipeline.propose_conversion(LLM, p, 120, "reopen")
    assert prop.ending == "reopen"
    assert prop.arc.summary == ""  # 아직 다 쓰지 않았으면 요약하지 않는다
    assert [f.id for f in prop.foreshadows] == ["fs-s-shadow"]  # 이미 있는 id 는 뺀다
    assert prop.foreshadows[0].planted_ep == 12 and prop.foreshadows[0].scope == "series"
    assert [s.id for s in prop.scopes] == [next(f.id for f in p.foreshadows if f.status == "open")]
    assert [e.number for e in prop.episodes] == [12]  # 본문 없는 화만
    assert prop.facts == ["오빠의 배는 끝내 발견되지 않았다"]

    # 화면에서 뺀 것은 반영하지 않는다
    prop.facts = []
    pipeline.apply_conversion(p, prop)
    assert p.episode(12).plot.ending_hook == "수평선에 낯선 불빛이 켜졌다" and p.episode(12).status == "draft"
    assert p.episode(8).status == "finalized" and p.episode(8).text
    assert p.storylines[0].join_ep == 10 and p.episode(9).plot.storyline == "sl-01"  # 화 번호가 그대로라 줄기도 그대로
    assert "오빠의 배는 끝내 발견되지 않았다" not in p.facts
    assert any(f.id == "fs-s-shadow" for f in p.foreshadows)


def test_locked_plots_and_bad_ranges():
    p = _short(written=8)
    prop = pipeline.propose_conversion(LLM, p, 200, "reopen")
    prop.episodes.append(p.episode(3).plot.model_copy(update={"title": "바뀐 제목"}))
    prop.parts[0].end_ep = 5  # 아크 1을 품지 못하는 부 구성
    cleaned = pipeline.clean_conversion(p, prop)
    assert 3 not in [e.number for e in cleaned.episodes] and "본문이 있거나" in cleaned.reply
    assert cleaned.parts == [] and "부 구성" in cleaned.reply
    with pytest.raises(ValueError, match="총 화수"):
        pipeline.propose_conversion(LLM, p, 14)
    pipeline.apply_conversion(p, cleaned)
    with pytest.raises(ValueError, match="이미 장편"):
        pipeline.propose_conversion(LLM, p, 200)


def test_no_main_left_drops_tiers():
    p = _short(written=2)
    prop = pipeline.propose_conversion(LLM, p, 100)
    prop.tiers = [t.model_copy(update={"id": c.id, "tier": "minor"}) for c, t in zip(p.characters, prop.tiers * 2)]
    assert pipeline.clean_conversion(p, prop).tiers == []


def test_undo():
    p = _short(written=4)
    before = pipeline.apply_conversion(p, pipeline.propose_conversion(LLM, p, 100))
    back = pipeline.undo_conversion(p, before)
    assert not back.serial and back.arc and back.conversion is None and back.meta.target_episodes == 12
    # 전환 뒤 새로 반영하거나 쓴 화가 있으면 되돌리지 않는다
    e = p.episode(5)
    e.text, e.status = "새 본문", "written"
    assert "본문" in pipeline.undo_blockers(p, before)[0]
    pipeline.apply_delta(p, pipeline.extract_state(LLM, p, 5))
    with pytest.raises(ValueError, match="상태를 반영한 화"):
        pipeline.undo_conversion(p, before)
    assert pipeline.undo_blockers(Project(), None) == ["단편에서 전환한 작품이 아니에요"]


def test_convert_prompt_has_short_story():
    p = _short(written=8)
    text = prompts.convert_prompt(p, 200, "", "북쪽으로 무대를 넓혀 줘")
    assert "end_ep 12" in text and "1화 " in text and "북쪽으로" in text
    assert "keep(닫고 다음 이야기로)" in text and "비워 둡니다 (아직 다 쓰지 않았습니다)" in text
    assert "8화 본문" in text  # 마지막으로 쓴 화 끝부분


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store, web

    importlib.reload(store)
    importlib.reload(web)
    return TestClient(web.app), store


def test_web_convert_and_undo(client):
    c, store = client
    from tests.test_web import _wait

    store.save("lh", _short(written=12))
    st = c.get("/api/projects/lh/convert").json()
    assert st["min"] == 16 and st["end"] == 12 and st["conversion"] is None
    assert c.post("/api/projects/lh/jobs", json={"kind": "convert", "length": 13}).status_code == 400
    j = _wait(c, c.post("/api/projects/lh/jobs", json={"kind": "convert", "length": 150, "ending": "reopen"}).json()["id"])
    assert j["status"] == "done", j
    prop = j["result"]
    assert prop["ending"] == "reopen" and prop["arc"]["end_ep"] == 12
    prop["tiers"] = []  # 화면에서 비중 조정을 빼고 반영
    p = c.post("/api/projects/lh/convert/apply", json=prop).json()
    assert p["meta"]["form"] == "serial" and p["story_arcs"][0]["end_ep"] == 12 and p["conversion"]["ending"] == "reopen"
    assert all(ch["tier"] == "main" for ch in p["characters"])
    assert store.backup_path("lh", "before-serial").exists()
    assert c.get("/api/projects/lh/convert").json()["undo_blockers"] == []
    assert c.put("/api/projects/lh", json=p).status_code == 200  # 장편 검사를 통과한다

    p = c.post("/api/projects/lh/convert/undo").json()
    assert p["meta"]["form"] == "short" and p["conversion"] is None and len(p["arc"]) == 4
    assert not store.backup_path("lh", "before-serial").exists()
    assert c.post("/api/projects/lh/convert/undo").status_code == 400

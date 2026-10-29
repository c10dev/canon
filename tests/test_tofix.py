"""고칠 곳: 작가가 본문 문장에 다는 '나중에 고칠 곳' 표시 (tofix.py, …/tofix). 실행: python -m pytest tests"""
import pytest

from canon import prompts, tofix
from canon.schema import Episode, EpisodePlot, Project

from .test_passage import TEXT, _ep, _written
from .test_restate import _two_done
from .test_web import client  # noqa: F401  (pytest fixture)

TWICE = "그는 웃었다. 비가 왔다. 그는 웃었다."


def _episode(text: str) -> Episode:
    plot = EpisodePlot(number=1, act="기", title="첫 화", summary="", events=[], characters=[], emotional_shift="", ending_hook="")
    return Episode(plot=plot, status="written", text=text)


def test_spot_picks_nearest_copy():
    assert tofix.spot(TWICE, "그는 웃었다.") == (0, 7)
    assert tofix.spot(TWICE, "그는 웃었다.", 20) == (len(TWICE) - 7, len(TWICE))
    assert tofix.spot(TWICE, "없는 문장") is None
    assert tofix.spot(TWICE, "  ") is None


def test_add_update_remove():
    e = _episode(TWICE)
    m = tofix.add(e, " 그는 웃었다. ", "어색함", 20, "t1")
    assert (m.id, m.quote, m.start, m.status) == ("x1", "그는 웃었다.", len(TWICE) - 7, "open")
    # 같은 자리에 다시 달면 새로 만들지 않고 메모만 바꾼다. 다른 자리의 같은 문장은 따로 단다
    assert tofix.add(e, "그는 웃었다.", "말투", 20, "t2") is m and m.note == "말투"
    assert tofix.add(e, "그는 웃었다.", "", 0, "t3").id == "x2"
    assert len(e.to_fix) == 2

    tofix.update(e, "x1", "t4", status="done")
    assert (m.status, m.done_at, m.note) == ("done", "t4", "말투")
    tofix.update(e, "x1", "t5", note="  고침 확인 ", status="open")
    assert (m.status, m.done_at, m.note) == ("open", "", "고침 확인")
    assert [x.id for x in tofix.open_marks(e)] == ["x1", "x2"]

    tofix.remove(e, "x2")
    assert [x.id for x in e.to_fix] == ["x1"]
    assert tofix.add(e, "비가 왔다.", "", 0, "t6").id == "x2"  # 지운 id 는 마지막 번호 뒤로
    with pytest.raises(KeyError):
        tofix.remove(e, "x9")


def test_add_rejects_bad_input():
    e = _episode(TWICE)
    with pytest.raises(ValueError, match="찾지 못했어요"):
        tofix.add(e, "본문에 없는 글", "", 0, "t")
    with pytest.raises(ValueError, match="골라"):
        tofix.add(e, " ", "", 0, "t")
    with pytest.raises(ValueError, match="메모"):
        tofix.add(e, "비가 왔다.", "가" * (tofix.MAX_NOTE + 1), 0, "t")
    tofix.add(e, "비가 왔다.", "", 0, "t")
    with pytest.raises(ValueError, match="상태"):
        tofix.update(e, "x1", "t", status="later")


def test_collect_marks_missing_quotes():
    p = Project.model_validate({"meta": {"title": "t", "genre": "로맨스", "logline": "l", "target_episodes": 2}})
    e = _episode(TWICE)
    p.episodes = [e]
    tofix.add(e, "비가 왔다.", "", 0, "t1")
    tofix.add(e, "그는 웃었다.", "", 0, "t2")
    tofix.update(e, "x2", "t3", status="done")
    e.text = e.text.replace("비가 왔다.", "눈이 왔다.")
    rows = tofix.collect(p)
    assert [(r["ep"], r["mark"].id, r["found"]) for r in rows] == [(1, "x1", False)]
    assert [r["mark"].id for r in tofix.collect(p, "all")] == ["x1", "x2"]


def test_web_flow_and_prompts(client):
    _written(client)
    p = client.post("/api/projects/lh/episodes/1/tofix", json={"quote": "바람이 불었다.", "note": "첫 문장이 밋밋함"}).json()
    assert _ep(p)["to_fix"][0] | {"at": ""} == {"id": "x1", "quote": "바람이 불었다.", "note": "첫 문장이 밋밋함", "start": 0,
                                                 "status": "open", "at": "", "done_at": ""}
    r = client.post("/api/projects/lh/episodes/1/tofix", json={"quote": "없는 문장이에요."})
    assert r.status_code == 400 and "찾지 못했어요" in r.json()["detail"]

    # 메모는 프롬프트에 들어가지 않는다
    q = Project.model_validate(client.get("/api/projects/lh").json())
    assert "밋밋함" not in prompts.build_episode_context(q, 1) and "밋밋함" not in prompts.check_prompt(q, 1)

    p = client.put("/api/projects/lh/episodes/1/tofix/x1", json={"status": "done"}).json()
    assert _ep(p)["to_fix"][0]["status"] == "done" and _ep(p)["to_fix"][0]["note"] == "첫 문장이 밋밋함"
    assert client.put("/api/projects/lh/episodes/1/tofix/x9", json={"status": "done"}).status_code == 400
    assert client.put("/api/projects/lh/episodes/1/tofix/x1", json={"status": "later"}).status_code == 422
    p = client.delete("/api/projects/lh/episodes/1/tofix/x1").json()
    assert _ep(p)["to_fix"] == []


def test_marks_while_autorun_runs(client, monkeypatch):
    """자동 집필이 도는 동안: 본문 저장은 막히고, 고칠 곳은 달린다. 화면이 들고 있던 옛 작품을 통째로 저장해도 지워지지 않는다."""
    from canon import autorun

    stale = _written(client)
    monkeypatch.setattr(autorun, "active", lambda name: True)
    assert client.put("/api/projects/lh/episodes/1/text", json={"text": TEXT + "\n\n덧붙임."}).status_code == 400
    p = client.post("/api/projects/lh/episodes/1/tofix", json={"quote": "도현은 대답하지 않았다.", "note": "침묵이 너무 길다"}).json()
    assert [m["id"] for m in _ep(p)["to_fix"]] == ["x1"]
    monkeypatch.setattr(autorun, "active", lambda name: False)
    stale["edit_rev"] = p["edit_rev"]
    p = client.put("/api/projects/lh", json=stale).json()
    assert [m["note"] for m in _ep(p)["to_fix"]] == ["침묵이 너무 길다"]


def test_deleting_body_clears_marks(client):
    _two_done(client)
    client.post("/api/projects/lh/episodes/2/tofix", json={"quote": "2화 본문."})
    p = client.post("/api/projects/lh/episodes/2/delete", json={"keep_plot": True}).json()["project"]
    assert p["episodes"][1]["to_fix"] == []

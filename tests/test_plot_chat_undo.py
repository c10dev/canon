"""플롯 대화 변경안 적용 취소 테스트 (mock LLM). 실행: python -m pytest tests"""
import pytest

from canon import pipeline
from canon.schema import ChatScope

from .test_arc_chat import _three_arcs
from .test_plot_chat import _last, _project
from .test_serial import LLM
from .test_web import client  # noqa: F401  (pytest fixture)


def _ask(client, message):
    p = client.post("/api/projects/lh/chat/plot", json={"message": message}).json()
    return _last(p)[0]


def _undo(client, i):
    r = client.post(f"/api/projects/lh/chat/plot/{i}/undo")
    assert r.status_code == 200, r.text
    return r.json()


def test_undo_episode_restores_plot_and_confirmed_status(client):
    before = _project(client)
    client.post("/api/projects/lh/episodes/3/confirm")
    confirmed = client.get("/api/projects/lh").json()["episodes"][2]
    i = _ask(client, "3화 전개가 너무 빨라")
    p = client.post(f"/api/projects/lh/chat/plot/{i}/apply", json={"episodes": [3]}).json()
    assert p["episodes"][2]["status"] == "draft"

    out = _undo(client, i)
    assert (out["restored"], out["kept"]) == (["3"], [])
    ep3 = out["project"]["episodes"][2]
    assert ep3["plot"] == confirmed["plot"] and ep3["status"] == "confirmed"  # 확정했던 화는 확정으로 돌아온다
    assert ep3["plot"]["summary"] == before["episodes"][2]["plot"]["summary"]
    m = _last(out["project"])[1]
    assert (m["outcome"], m["applied"], m["plot_before"]) == ("", [], None)  # 다시 고를 수 있게 열린다

    # 다시 적용할 수 있고, 적용하지 않은 변경안은 취소할 수 없다
    assert client.post(f"/api/projects/lh/chat/plot/{i}/apply", json={"episodes": [3]}).status_code == 200
    assert _undo(client, i)["restored"] == ["3"]
    assert client.post(f"/api/projects/lh/chat/plot/{i}/undo").status_code == 400
    assert client.post(f"/api/projects/lh/chat/plot/{i - 1}/undo").status_code == 404  # 작가가 보낸 말


def test_undo_keeps_reedited_and_written_episodes(client):
    _project(client)
    i = _ask(client, "1화 바꿔 줘")
    j = _ask(client, "2화 늘려 줘")
    client.post(f"/api/projects/lh/chat/plot/{i}/apply", json={"episodes": [1]})
    p = client.post(f"/api/projects/lh/chat/plot/{j}/apply", json={"episodes": [2]}).json()

    p["episodes"][1]["plot"]["title"] = "작가가 다시 고친 제목"  # 적용 뒤 작가가 손봄
    client.put("/api/projects/lh", json=p)
    client.post("/api/projects/lh/episodes/1/confirm")
    client.post("/api/projects/lh/episodes/1/write")  # 1화는 본문이 생김

    out = _undo(client, j)
    assert out["restored"] == [] and out["kept"] == ["2"] and "다시 고침" in out["reasons"][0]
    assert out["project"]["episodes"][1]["plot"]["title"] == "작가가 다시 고친 제목"
    out = _undo(client, i)
    assert out["kept"] == ["1"] and "본문" in out["reasons"][0]
    assert out["project"]["episodes"][0]["status"] == "written"


def test_undo_structure_and_resize(client):
    before = _project(client, eps=10)
    i = _ask(client, "결말을 비극으로")
    client.post(f"/api/projects/lh/chat/plot/{i}/apply", json={"acts": True})
    out = _undo(client, i)
    assert out["restored"] == ["acts"] and out["project"]["arc"] == before["arc"]

    i = _ask(client, "12화로 늘려 줘")
    client.post(f"/api/projects/lh/chat/plot/{i}/apply", json={"acts": True, "episodes": [11, 12]})
    out = _undo(client, i)
    p = out["project"]
    assert sorted(out["restored"]) == ["11", "12", "acts"]
    assert p["meta"]["target_episodes"] == 10 and len(p["episodes"]) == 10 and p["arc"] == before["arc"]

    # 늘린 화를 작가가 손봤으면 그 화와 구조는 남긴다 (구조만 줄이면 11화가 총 화수 밖에 남는다)
    p = client.post(f"/api/projects/lh/chat/plot/{i}/apply", json={"acts": True, "episodes": [11, 12]}).json()
    p["episodes"][10]["plot"]["summary"] = "작가가 쓴 11화"
    client.put("/api/projects/lh", json=p)
    out = _undo(client, i)
    assert out["restored"] == ["12"] and sorted(out["kept"]) == ["11", "acts"]
    p = out["project"]
    assert p["meta"]["target_episodes"] == 12 and [e["plot"]["number"] for e in p["episodes"]][-1] == 11


def test_undo_shrink_brings_back_cut_episodes(client):
    before = _project(client, eps=10)
    i = _ask(client, "8화로 줄여 줘")
    p = client.post(f"/api/projects/lh/chat/plot/{i}/apply", json={"acts": True}).json()
    assert len(p["episodes"]) == 8
    out = _undo(client, i)
    p = out["project"]
    assert out["restored"] == ["acts"] and p["meta"]["target_episodes"] == 10
    assert [e["plot"] for e in p["episodes"]] == [e["plot"] for e in before["episodes"]]


def test_serial_undo_arc_end_and_parts():
    p, a1, a2, a3 = _three_arcs()
    old = a3.model_copy(deep=True)
    p.parts[1].summary = "2부 요약"
    parts = [x.model_copy(deep=True) for x in p.parts]
    rev = pipeline.revise_plot(LLM, p, f"갈등을 바꾸고 끝 화 {old.end_ep + 4}", ChatScope(target="arc:3"))
    pipeline.record_chat(p, "plot", "갈등", rev, ChatScope(target="arc:3"))
    i = len(p.chat("plot").messages) - 1
    assert pipeline.apply_plot_chat(p, i, False, [], arc=True) == ["arc", "acts"]
    assert p.story_arcs[2].end_ep == old.end_ep + 4
    done, kept, _ = pipeline.undo_plot_chat(p, i)
    assert sorted(done) == ["acts", "arc"] and kept == []
    assert p.story_arcs[2] == old and p.planned_until() == old.end_ep

    rev = pipeline.revise_plot(LLM, p, "부 구성에서 1부 목표를 고쳐 줘", ChatScope(target="arc:2"))
    pipeline.record_chat(p, "plot", "부", rev, ChatScope(target="arc:2"))
    i = len(p.chat("plot").messages) - 1
    pipeline.apply_plot_chat(p, i, False, [], parts=True)
    assert p.parts != parts
    assert pipeline.undo_plot_chat(p, i)[0] == ["parts"] and p.parts == parts

    # 아크 칸을 적용한 뒤 작가가 다시 고쳤으면 남긴다
    rev = pipeline.revise_plot(LLM, p, "갈등을 바꿔 줘", ChatScope(target="arc:2"))
    pipeline.record_chat(p, "plot", "갈등", rev, ChatScope(target="arc:2"))
    i = len(p.chat("plot").messages) - 1
    pipeline.apply_plot_chat(p, i, False, [], arc=True)
    p.story_arcs[1].goal = "작가가 다시 쓴 목표"
    done, kept, why = pipeline.undo_plot_chat(p, i)
    assert done == [] and kept == ["arc"] and p.story_arcs[1].conflict == "옛 동료의 배신"
    with pytest.raises(ValueError):
        pipeline.undo_plot_chat(p, i)

"""집필 화면 플롯 띠의 쓴 사건 체크 (Episode.events_done, PUT …/events-done). 실행: python -m pytest tests"""
from canon import prompts
from canon.schema import Project

from .test_plot_chat import _project
from .test_restate import _two_done
from .test_web import client  # noqa: F401  (pytest fixture)


def test_check_keeps_only_this_episode_events(client):
    p = _project(client)
    events = p["episodes"][0]["plot"]["events"]
    client.post("/api/projects/lh/episodes/1/confirm")
    r = client.put("/api/projects/lh/episodes/1/events-done", json={"done": [events[1], "없는 사건", events[0]]})
    assert r.status_code == 200 and r.json() == [events[0], events[1]]  # 플롯 순서로, 이 화 사건만
    assert client.get("/api/projects/lh").json()["episodes"][0]["events_done"] == [events[0], events[1]]
    assert client.put("/api/projects/lh/episodes/1/events-done", json={"done": []}).json() == []


def test_draft_plot_cannot_be_checked(client):
    p = _project(client)
    r = client.put("/api/projects/lh/episodes/2/events-done", json={"done": p["episodes"][1]["plot"]["events"][:1]})
    assert r.status_code == 400 and "확정" in r.json()["detail"]


def test_checks_stay_out_of_prompts(client):
    p = _project(client)
    events = p["episodes"][0]["plot"]["events"]
    client.post("/api/projects/lh/episodes/1/confirm")
    client.put("/api/projects/lh/episodes/1/events-done", json={"done": events[:1]})
    q = Project.model_validate(client.get("/api/projects/lh").json())
    assert "events_done" not in prompts.build_episode_context(q, 1)


def test_deleting_body_clears_checks(client):
    p = _two_done(client)
    events = p["episodes"][1]["plot"]["events"]
    assert client.put("/api/projects/lh/episodes/2/events-done", json={"done": events}).json() == events
    p = client.post("/api/projects/lh/episodes/2/delete", json={"keep_plot": True}).json()["project"]
    assert p["episodes"][1]["events_done"] == []

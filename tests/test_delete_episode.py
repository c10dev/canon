"""마지막 화 지우기 테스트 (mock LLM): 반영 취소 → 본문 비우기 → 화 빼기, 플롯 남기기, 중간 화는 막기. 실행: python -m pytest tests"""
import os
from pathlib import Path

import pytest

from canon import pipeline
from canon.schema import Chat, ChatMessage, Foreshadow, ForeshadowClue, Project

from .test_restate import _two_done
from .test_web import client  # noqa: F401  (pytest fixture)


def _dir() -> Path:
    return Path(os.environ["CANON_HOME"]) / "lh"


def test_delete_last_finalized(client):
    p = _two_done(client)
    total, count, third = p["meta"]["target_episodes"], len(p["episodes"]), p["episodes"][2]["plot"]["title"]
    assert (_dir() / "episodes" / "02.md").exists()

    # 중간 화는 뒤 화가 그 위에 쌓여 있어 지우지 않는다. 화 빼기도 그대로 막힌다
    r = client.post("/api/projects/lh/episodes/1/delete", json={})
    assert r.status_code == 400 and "마지막 화부터" in r.json()["detail"]
    assert client.delete("/api/projects/lh/episodes/2").status_code == 400
    # 본문도 반영도 없는 화는 화 빼기를 쓴다
    assert "화 빼기" in client.post("/api/projects/lh/episodes/3/delete", json={}).json()["detail"]

    r = client.post("/api/projects/lh/episodes/2/delete", json={})
    assert r.status_code == 200, r.text
    p, notes = r.json()["project"], " ".join(r.json()["notes"])
    assert "반영을 취소" in notes and "before-delete-2.json" in notes
    assert len(p["episodes"]) == count - 1 and p["meta"]["target_episodes"] == total - 1
    assert p["episodes"][0]["status"] == "finalized" and p["episodes"][1]["plot"]["title"] == third  # 3화가 2화로 당겨졌다
    assert p["episodes"][1]["status"] == "draft" and not p["episodes"][1]["text"]
    assert all(x["episode"] <= 1 for x in [*p["history"], *p["snapshots"], *p["events"]])
    assert not (_dir() / "episodes" / "02.md").exists() and (_dir() / "episodes" / "01.md").exists()

    # 지우기 전 작품이 백업으로 남는다
    back = Project.model_validate_json((_dir() / "before-delete-2.json").read_text(encoding="utf-8"))
    assert back.episode(2).status == "finalized" and back.episode(2).text == "2화 본문."

    # 이제 1화가 마지막 화라 지울 수 있다
    p = client.post("/api/projects/lh/episodes/1/delete", json={"keep_plot": True}).json()["project"]
    assert p["episodes"][0]["status"] == "confirmed" and not p["snapshots"][1:] and not p["history"]


def test_delete_keep_plot(client):
    p = _two_done(client)
    count, title = len(p["episodes"]), p["episodes"][1]["plot"]["title"]
    q = Project.model_validate(p)  # 작가가 2화 문장에 건 복선과 2화 본문 대화
    for fs in [q.foreshadows, *(s.foreshadows for s in q.snapshots if s.episode >= 1)]:
        fs.append(Foreshadow(id="fs-01-bell", description="종소리", planted_ep=1))
    q.foreshadow_clues += [ForeshadowClue(foreshadow="fs-01-bell", episode=n, quote="본문", by="author") for n in (1, 2)]
    q.chats.append(Chat(topic="text:2", messages=[ChatMessage(role="user", text="더 짧게")]))
    assert client.put("/api/projects/lh", json=q.model_dump()).status_code == 200

    p = client.post("/api/projects/lh/episodes/2/delete", json={"keep_plot": True}).json()["project"]
    e = p["episodes"][1]
    assert len(p["episodes"]) == count and e["plot"]["title"] == title
    assert e["status"] == "confirmed" and e["text"] == "" and e["summary"] == "" and not e["edits"] and not e["versions"]
    assert [c["episode"] for c in p["foreshadow_clues"] if c["foreshadow"] == "fs-01-bell"] == [1]
    assert not [c for c in p["chats"] if c["topic"] == "text:2"]
    assert p["episodes"][0]["status"] == "finalized"


def test_delete_written_not_applied(client):
    _two_done(client)
    client.post("/api/projects/lh/episodes/3/confirm")
    client.put("/api/projects/lh/episodes/3/text", json={"text": "3화 본문."})
    r = client.post("/api/projects/lh/episodes/3/delete", json={}).json()
    p = r["project"]
    assert not any("반영을 취소" in x for x in r["notes"])  # 반영하지 않은 화라 반영은 그대로
    assert [e["status"] for e in p["episodes"][:3]] == ["finalized", "finalized", "draft"]
    assert p["episodes"][1]["text"] == "2화 본문." and len(p["history"]) == 2


def test_delete_is_all_or_nothing(client):
    """화를 빼다 막히면 (구간이 빔) 반영 취소도 본문 비우기도 하지 않는다."""
    p = Project.model_validate(_two_done(client))
    for a in p.arc:  # 2화만 든 구간을 만든다
        a.start_ep, a.end_ep = (1, 1) if a.name == "기" else (2, 2) if a.name == "승" else (a.start_ep, a.end_ep)
    p.arc = [a for a in p.arc if a.name in ("기", "승")] + [a.model_copy(update={"start_ep": 3, "end_ep": 99}) for a in p.arc if a.name == "전"]
    before = p.model_dump()
    with pytest.raises(ValueError, match="비어요"):
        pipeline.delete_last(p, 2)
    assert p.model_dump() == before

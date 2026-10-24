"""반영 뒤 고친 화 테스트 (mock LLM): 다음 화가 있는 화의 본문 고치기, 다시 맞추기(요약 · 새 사실 · 새 복선), 그대로 두기. 실행: python -m pytest tests"""
from canon import pipeline
from canon.schema import Project, RewriteRequest

from .test_passage import TEXT, _ep, _written
from .test_web import client  # noqa: F401  (pytest fixture)


def _two_done(client):
    """1화 · 2화까지 반영한 작품. 1화가 '다음 화가 쓰인 화'다."""
    _written(client)
    client.post("/api/projects/lh/episodes/1/apply", json=client.post("/api/projects/lh/episodes/1/state").json())
    client.post("/api/projects/lh/episodes/2/confirm")
    client.put("/api/projects/lh/episodes/2/text", json={"text": "2화 본문."})
    return client.post("/api/projects/lh/episodes/2/apply", json=client.post("/api/projects/lh/episodes/2/state").json()).json()


def test_edit_earlier_episode_keeps_state(client):
    p = _two_done(client)
    assert [e["status"] for e in p["episodes"][:2]] == ["finalized", "finalized"]
    before = {k: p[k] for k in ("states", "relationships", "facts", "foreshadows", "history")}

    # 직접 고치기 · 통째로 저장 · 되돌리기 모두 된다. 반영 상태는 그대로이고 처음 본문이 final_text 에 남는다
    sel = {"start": 0, "text": "바람이 불었다."}
    p = client.post("/api/projects/lh/episodes/1/edits", json={"selection": sel, "after": "비가 왔다."}).json()
    assert _ep(p)["status"] == "finalized" and _ep(p)["final_text"] == TEXT
    assert {k: p[k] for k in before} == before
    p = client.put("/api/projects/lh/episodes/1/text", json={"text": _ep(p)["text"] + "\n\n덧붙인 줄."}).json()
    assert _ep(p)["status"] == "finalized" and _ep(p)["final_text"] == TEXT and _ep(p)["edits"][-1]["source"] == "typed"
    assert client.put("/api/projects/lh/episodes/1/text", json={"text": " "}).status_code == 400  # 반영한 화는 비우지 않는다
    assert pipeline.edited_after_final(Project.model_validate(p).episode(1))

    # 손댄 것을 모두 되돌려 반영 때 본문과 같아지면 고친 것으로 보지 않는다
    q = Project.model_validate(p)
    q.episode(1).text = TEXT
    assert not pipeline.edited_after_final(q.episode(1))

    # 그대로 두기: 표시만 지운다
    p = client.post("/api/projects/lh/episodes/1/keep-state").json()
    assert _ep(p)["final_text"] == "" and {k: p[k] for k in before} == before
    assert client.post("/api/projects/lh/episodes/3/keep-state").status_code == 400  # 반영한 화가 아니다


def test_restate_adds_summary_facts_foreshadows(client):
    p = _two_done(client)
    p = client.post("/api/projects/lh/episodes/1/edits", json={"selection": {"start": 0, "text": "바람이 불었다."}, "after": "비가 왔다."}).json()
    states, events = p["states"], p["events"]
    d = client.post("/api/projects/lh/episodes/1/state").json()  # 반영한 화도 변경안을 다시 뽑는다
    old_fs = d["foreshadow_planted"][0]["id"] if d["foreshadow_planted"] else None
    d["summary"] = "고친 1화 요약"
    d["new_facts"] = p["facts"][:1] + ["등대지기는 왼손잡이다"]  # 이미 있는 사실은 다시 넣지 않는다
    d["foreshadow_planted"] = d["foreshadow_planted"] + [{"id": "fs-01-rain", "description": "비 냄새", "planted_ep": 7}]
    p = client.post("/api/projects/lh/episodes/1/restate", json=d).json()
    e = _ep(p)
    assert e["status"] == "finalized" and e["summary"] == "고친 1화 요약" and e["final_text"] == ""
    assert p["facts"].count("등대지기는 왼손잡이다") == 1 and len(p["facts"]) == len(set(p["facts"]))
    rain = [f for f in p["foreshadows"] if f["id"] == "fs-01-rain"]
    assert len(rain) == 1 and rain[0]["planted_ep"] == 1 and rain[0]["status"] == "open"
    if old_fs:
        assert sum(f["id"] == old_fs for f in p["foreshadows"]) == 1
    assert p["states"] == states and p["events"] == events  # 인물 상태 · 관계 사건은 바꾸지 않는다

    # 1화 · 2화 스냅샷과 1화 반영 기록에도 들어가 되돌려도 남는다
    for s in p["snapshots"]:
        if s["episode"] >= 1:
            assert "등대지기는 왼손잡이다" in s["facts"] and any(f["id"] == "fs-01-rain" for f in s["foreshadows"])
    h = next(x for x in reversed(p["history"]) if x["episode"] == 1)
    assert h["summary"] == "고친 1화 요약" and "등대지기는 왼손잡이다" in h["new_facts"]
    p = client.post("/api/projects/lh/revert/1").json()
    assert "등대지기는 왼손잡이다" in p["facts"] and _ep(p, 2)["status"] == "written"

    # 반영이 끝나지 않은 화는 다시 맞추기가 아니라 상태 승인으로 반영한다
    assert client.post("/api/projects/lh/episodes/2/restate", json={"episode": 2, "summary": "x"}).status_code == 400


def test_rewrite_and_revert_on_finalized(client):
    p = Project.model_validate(_two_done(client))
    req = RewriteRequest(feedback="더 차분하게")
    pipeline.set_candidate(p, 1, "새 판 1화 본문.", req)
    pipeline.adopt_candidate(p, 1)
    ep = p.episode(1)
    assert ep.status == "finalized" and ep.text == "새 판 1화 본문." and ep.final_text == TEXT
    assert ep.versions[-1].text == TEXT
    pipeline.restore_version(p, 1, ep.versions[-1].id)
    assert ep.text == TEXT and not pipeline.edited_after_final(ep)  # 반영 때 본문으로 돌아왔다

    # 반영을 취소하면 표시도 지운다
    ep.text = "또 고침."
    pipeline.revert(p, 0)
    assert ep.status == "written" and ep.final_text == ""

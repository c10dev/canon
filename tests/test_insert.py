"""화 끼워 넣기 · 빼기 테스트 (mock LLM). 실행: python -m pytest tests"""
import pytest

from canon import pipeline, prompts
from canon.mock import MockLLM
from canon.schema import Chat, Foreshadow, Project, StoryElement, Storyline

from .test_serial import _finish, _plan_arc, _serial
from .test_web import _wait, client  # noqa: F401  (pytest fixture)

LLM = MockLLM()


def _short(total=12, written=5) -> Project:
    """total 화 단편. written 화까지 쓰고 상태를 반영했고, 그 다음 화는 확정만 했다."""
    p = Project()
    p.meta.title, p.meta.target_episodes = "등대", total
    pipeline.apply_setup(p, pipeline.suggest_setup(LLM, p))
    p.arc = pipeline.plan_arc(LLM, p).acts
    pipeline.apply_plots(p, pipeline.draft_plots(LLM, p, 1, total))
    for n in range(1, written + 1):
        e = p.episode(n)
        e.text, e.status = "본문", "written"
        pipeline.apply_delta(p, pipeline.extract_state(LLM, p, n))
    p.episode(written + 1).status = "confirmed"
    return p


def _acts(p: Project) -> list[tuple[str, int, int]]:
    return [(a.name, a.start_ep, a.end_ep) for a in p.beats()]


def test_insert_shifts_unwritten_and_keeps_confirmed():
    p = _short()
    assert pipeline.insert_range(p) == (6, 13)
    old6 = p.episode(6).plot.title
    p.foreshadows.append(Foreshadow(id="fs-x", description="열쇠", planted_ep=3, due_ep=8))
    p.elements.append(StoryElement(id="el-1", name="폭풍", description="섬에 폭풍", since_ep=3, episodes=[6, 9], reveal_ep=10))
    p.storylines.append(Storyline(id="sl-01", kind="외전", title="등대지기", branch_ep=6, join_ep=7))
    p.chats.append(Chat(topic="text:7"))
    notes = pipeline.insert_episode(p, 6, "외전: 겨울", "서윤의 어린 시절", "sl-01")
    assert [e.plot.number for e in p.episodes] == list(range(1, 14)) and p.meta.target_episodes == 13
    new = p.episode(6)
    assert (new.status, new.plot.title, new.plot.summary, new.plot.storyline) == ("draft", "외전: 겨울", "서윤의 어린 시절", "sl-01")
    assert p.episode(7).plot.title == old6 and p.episode(7).status == "confirmed"  # 밀린 화는 확정 상태 그대로
    assert p.episode(5).status == "finalized" and p.history[-1].episode == 5  # 쓴 화와 기록은 그대로
    assert _acts(p) == [("기", 1, 2), ("승", 3, 8), ("전", 9, 11), ("결", 12, 13)]  # 6화가 든 승 구간이 늘어난다
    assert p.foreshadows[-1].due_ep == 9 and p.foreshadows[-1].planted_ep == 3
    el = p.elements[0]
    assert (el.since_ep, el.episodes, el.reveal_ep) == (3, [7, 10], 11)
    assert (p.storylines[0].branch_ep, p.storylines[0].join_ep) == (7, 8)
    assert p.chats[-1].topic == "text:8"
    assert "승 구간 3~7화 → 3~8화" in " ".join(notes) and "총 화수 12화 → 13화." in notes


def test_insert_refuses_written_and_out_of_range():
    p = _short()
    before = p.model_dump()
    with pytest.raises(ValueError, match="6화부터"):
        pipeline.insert_episode(p, 5)
    with pytest.raises(ValueError, match="13화"):
        pipeline.insert_episode(p, 15)
    with pytest.raises(KeyError):
        pipeline.insert_episode(p, 6, storyline="sl-없음")
    assert p.model_dump() == before


def test_append_after_last_extends_last_act():
    p = _short()
    pipeline.insert_episode(p, 13, "에필로그")
    assert _acts(p)[-1] == ("결", 11, 13) and p.episode(13).plot.act == "결" and p.meta.target_episodes == 13


def test_remove_pulls_back_and_points_to_next():
    p = _short()
    title7 = p.episode(7).plot.title
    p.foreshadows.append(Foreshadow(id="fs-x", description="열쇠", planted_ep=3, due_ep=6))
    pipeline.remove_episode(p, 6)
    assert p.meta.target_episodes == 11 and p.episode(6).plot.title == title7 and len(p.episodes) == 11
    assert _acts(p) == [("기", 1, 2), ("승", 3, 6), ("전", 7, 9), ("결", 10, 11)]
    assert p.foreshadows[-1].due_ep == 6  # 뺀 화를 가리키던 번호는 그 자리에 온 다음 화
    with pytest.raises(ValueError, match="뺄 수 없어요"):
        pipeline.remove_episode(p, 5)


def test_remove_refuses_emptying_an_act():
    p = _short()
    p.arc[0].end_ep, p.arc[1].start_ep = 1, 2  # 기 구간이 한 화
    p.episode(1).text, p.episode(1).status = "", "draft"
    p.history, p.snapshots, p.events = [], [], []
    for e in p.episodes:
        e.text, e.status = "", "draft"
    before = p.model_dump()
    with pytest.raises(ValueError, match="기 구간"):
        pipeline.remove_episode(p, 1)
    assert p.model_dump() == before


def test_insert_then_remove_round_trips():
    p = _short()
    before = p.model_dump()
    pipeline.insert_episode(p, 8, "끼운 화")
    pipeline.remove_episode(p, 8)
    assert p.model_dump() == before


def test_draft_episode_bridges_and_keeps_author_fields():
    p = _short()
    pipeline.insert_episode(p, 6, "외전: 겨울", "서윤의 어린 시절")
    prompt = prompts.episode_plot_prompt(p, 6)
    assert "서윤의 어린 시절" in prompt and p.episode(7).plot.title in prompt and "6화 하나만" in prompt
    batch = pipeline.draft_episode(LLM, p, 6)
    pipeline.apply_plots(p, batch)
    assert p.episode(6).plot.title == "외전: 겨울" and p.episode(6).plot.events
    with pytest.raises(ValueError, match="확정된 화"):
        pipeline.draft_episode(LLM, p, 7)


def test_draft_episode_without_fitting_next_marks_next():
    p = _short()
    p.episode(8).plot.summary = "서윤이 오빠의 편지를 찾아 모든 걸 알게 된다"
    fit = prompts.episode_plot_prompt(p, 8)
    free = prompts.episode_plot_prompt(p, 8, fit_next=False)
    assert "바꾸지 않음" in fit and "next_gap" not in fit
    assert "참고만" in free and "next_gap" in free and "뒤 화로 미루지 않습니다" in free
    assert p.episode(9).plot.title in free
    batch = pipeline.draft_episode(LLM, p, 8, fit_next=False)
    assert batch.next_gap
    assert pipeline.apply_draft(p, batch) == 9
    assert p.episode(9).realign == batch.next_gap and not p.episode(8).realign
    # 뒤 화를 다시 짜면 표시가 지워진다
    pipeline.apply_draft(p, pipeline.draft_episode(LLM, p, 9))
    assert not p.episode(9).realign
    # 맞추기를 켜거나 뒤 화가 없으면 표시하지 않는다
    assert pipeline.apply_draft(p, pipeline.draft_episode(LLM, p, 10)) is None
    last = p.meta.target_episodes
    batch = pipeline.draft_episode(LLM, p, last, fit_next=False)
    assert not getattr(batch, "next_gap", "") and pipeline.apply_draft(p, batch) is None


def test_web_realign_mark_survives_save_and_clears(client):
    from canon import store

    store.save("rea", _short())
    j = client.post("/api/projects/rea/jobs", json={"kind": "plot_one", "ep": 8, "fit_next": False}).json()
    done = _wait(client, j["id"])
    assert done["status"] == "done" and done["result"]["realign"] == 9 and done["result"]["gap"]
    p = client.get("/api/projects/rea").json()
    assert p["episodes"][8]["realign"]
    p["episodes"][8]["realign"] = ""  # 표시를 받기 전에 읽은 화면이 저장해도 지우지 않는다
    assert client.put("/api/projects/rea", json=p).json()["episodes"][8]["realign"]
    r = client.post("/api/projects/rea/episodes/9/realign/clear")
    assert r.status_code == 200 and r.json()["episodes"][8]["realign"] == ""


def test_serial_insert_at_arc_start_grows_that_arc_and_total():
    p = _serial(300)
    a1 = _plan_arc(p)
    _finish(p, a1)
    a2 = _plan_arc(p)
    s1, s2, part = (a1.start_ep, a1.end_ep), (a2.start_ep, a2.end_ep), (p.parts[0].start_ep, p.parts[0].end_ep)
    at = a2.start_ep
    pipeline.insert_episode(p, at, "외전")
    assert (p.story_arcs[0].start_ep, p.story_arcs[0].end_ep) == s1  # 앞 아크(쓴 아크)는 그대로
    assert (p.story_arcs[1].start_ep, p.story_arcs[1].end_ep) == (s2[0], s2[1] + 1)
    assert p.story_arcs[1].acts[0].start_ep == at and p.episode(at).plot.act == "기"
    assert (p.parts[0].start_ep, p.parts[0].end_ep) == (part[0], part[1] + 1) and p.parts[1].start_ep == part[1] + 2
    assert p.meta.target_episodes == 301 and p.parts[-1].end_ep == 301
    pipeline.validate_story_arcs(p)


def test_serial_append_after_written_arc():
    p = _serial(300)
    a1 = _plan_arc(p)
    _finish(p, a1)
    end = a1.end_ep
    assert pipeline.insert_range(p) == (end + 1, end + 1)
    pipeline.insert_episode(p, end + 1, "외전")
    assert p.story_arcs[0].end_ep == end + 1 and p.story_arcs[0].acts[-1].end_ep == end + 1
    assert p.episode(end + 1).plot.act == "결"


def test_web_insert_draft_and_remove(client):
    from canon import store

    p = _short()
    store.save("ins", p)
    r = client.post("/api/projects/ins/episodes/insert", json={"at": 6, "title": "외전", "summary": "겨울 이야기"})
    assert r.status_code == 200, r.text
    assert len(r.json()["project"]["episodes"]) == 13 and r.json()["notes"][0].startswith("6화에 새 화")
    j = client.post("/api/projects/ins/jobs", json={"kind": "plot_one", "ep": 6}).json()
    assert _wait(client, j["id"])["status"] == "done"
    e6 = client.get("/api/projects/ins").json()["episodes"][5]["plot"]
    assert e6["title"] == "외전" and e6["events"]
    assert client.post("/api/projects/ins/jobs", json={"kind": "plot_one", "ep": 7}).status_code == 400  # 확정된 화
    assert client.post("/api/projects/ins/episodes/insert", json={"at": 3}).status_code == 400
    r = client.delete("/api/projects/ins/episodes/6")
    assert r.status_code == 200 and len(r.json()["project"]["episodes"]) == 12

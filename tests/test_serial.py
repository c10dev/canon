"""장편 연재(부 → 아크 → 화) 테스트 (mock LLM). 실행: python -m pytest tests"""
import pytest

from canon import pipeline, prompts
from canon.mock import MockLLM
from canon.schema import Character, EpisodePlot, Foreshadow, Project, StateDelta

LLM = MockLLM()


def _serial(total=300) -> Project:
    p = Project()
    p.meta.title, p.meta.form, p.meta.target_episodes = "탑", "serial", total
    pipeline.apply_setup(p, pipeline.suggest_setup(LLM, p))
    pipeline.apply_series(p, pipeline.plan_series(LLM, p))
    return p


def _plan_arc(p: Project, length=0):
    a = pipeline.apply_arc(p, pipeline.plan_next_arc(LLM, p, length))
    pipeline.apply_plots(p, pipeline.draft_plots(LLM, p, a.start_ep, a.end_ep))
    for e in p.episodes:
        if e.status == "draft":
            e.status = "confirmed"
    return a


def _finish(p: Project, a, text="본문"):
    """아크의 화를 모두 쓴 것으로 하고 상태를 반영한다."""
    for n in range(a.start_ep, a.end_ep + 1):
        e = p.episode(n)
        e.text, e.status = text, "written"
        d = pipeline.extract_state(LLM, p, n)
        d.summary = f"{n}화 요약 " + "가" * 300
        pipeline.apply_delta(p, d)


def test_old_project_is_short_and_unchanged():
    p = Project.model_validate({"meta": {"title": "x"}, "characters": [{"id": "a", "name": "A", "role": "주인공"}]})
    assert p.meta.form == "short" and not p.serial
    assert p.characters[0].tier == "main"
    assert p.beats() == p.arc
    assert prompts.static_characters(p) == p.characters


def test_series_and_rolling_arcs():
    p = _serial()
    assert [(x.start_ep, x.end_ep) for x in p.parts] == [(1, 100), (101, 200), (201, 300)]
    a1 = _plan_arc(p)
    assert (a1.number, a1.start_ep, a1.end_ep) == (1, 1, 12)
    assert [e.plot.number for e in p.episodes] == list(range(1, 13))
    assert all(e.plot.act == p.act_for(e.plot.number).name for e in p.episodes)
    with pytest.raises(ValueError, match="다음 아크"):
        pipeline.draft_plots(LLM, p, 13, 20)

    a2 = _plan_arc(p, length=10)
    assert (a2.start_ep, a2.end_ep) == (13, 22)
    guest = next(c for c in p.characters if c.id == "guest2")
    assert (guest.tier, guest.first_ep) == ("support", 13)  # 새 인물은 조연으로 들어온다
    assert p.state_of("guest2") is not None


def test_arc_cannot_cross_part():
    p = _serial(300)
    p.story_arcs = []
    for _ in range(8):
        _plan_arc(p)
    last = p.story_arcs[-1]
    assert last.end_ep == 96
    a = pipeline.apply_arc(p, pipeline.plan_next_arc(LLM, p))
    assert a.end_ep == 100  # 1부 끝에서 멈춘다
    assert pipeline.plan_next_arc(LLM, p).arc.start_ep == 101


def test_arc_stretches_to_part_end_when_leftover_is_too_short():
    p = _serial(300)
    for _ in range(7):
        _plan_arc(p)
    prop = pipeline.plan_next_arc(LLM, p, length=14)
    a = pipeline.apply_arc(p, prop)
    assert a.end_ep == 100 and a.acts[-1].end_ep == 100  # 2화만 남으면 아크를 부 끝까지 늘린다
    assert "100화까지" in prop.reply


def test_remove_last_arc_only_when_draft():
    p = _serial()
    a = pipeline.apply_arc(p, pipeline.plan_next_arc(LLM, p))
    pipeline.apply_plots(p, pipeline.draft_plots(LLM, p, a.start_ep, a.end_ep))
    p.episode(1).status = "confirmed"
    with pytest.raises(ValueError, match="지울 수 없습니다"):
        pipeline.remove_last_arc(p)
    p.episode(1).status = "draft"
    pipeline.remove_last_arc(p)
    assert p.story_arcs == [] and p.episodes == []


def test_context_stays_bounded_at_300():
    p = _serial(300)
    sizes = {}
    while p.planned_until() < 260:
        a = _plan_arc(p, length=24)
        _finish(p, a)
        for kind, num in pipeline.pending_recaps(p):
            pipeline.apply_recap(p, kind, num, pipeline.recap(LLM, p, kind, num).summary)
        nxt = a.end_ep + 1
        sizes[nxt] = len(prompts.story_so_far(p, nxt))
    assert all(x.summary for x in p.parts[:2])
    assert all(a.summary for a in p.story_arcs)
    # 지금 방식(화별 요약 전부)은 화수에 비례해 커지지만, 접은 줄거리는 거의 그대로다
    flat = sum(len(e.summary) for e in p.episodes)
    assert flat > 80_000
    last = sizes[max(sizes)]
    assert max(sizes) > 260 and last < 6_000 and last < sizes[25] * 1.5

    # 마지막 아크 안에서 본문 프롬프트를 만들어도 크기가 일정하다
    a = _plan_arc(p, length=11)
    p.episode(a.start_ep + 5).status = "confirmed"
    for n in range(a.start_ep, a.start_ep + 5):
        e = p.episode(n)
        e.text, e.status, e.summary = "본문", "finalized", "요약"
    ctx = prompts.build_episode_context(p, a.start_ep + 5)
    assert "[3부" in ctx and "아크 " in ctx
    assert len(ctx) < 30_000
    hero = next(s for s in p.states if s.character_id == "hero")
    assert len(hero.knows) > 200 and f'"{a.start_ep - 30}화 단서"' not in ctx  # 알게 된 정보는 최근 것만
    # 스냅샷은 시작점, 아크 끝, 최근 20개만 남는다
    assert len(p.snapshots) <= 1 + len(p.story_arcs) + pipeline.SNAPSHOT_KEEP


def test_story_so_far_falls_back_to_episode_summaries():
    p = _serial(300)
    a = _plan_arc(p)
    _finish(p, a)
    b = _plan_arc(p)
    text = prompts.story_so_far(p, b.start_ep + 5)
    assert "[아크 1 아크 1 (1~12화)]" in text and "1화 요약" in text  # 아크 요약이 아직 없으면 화별 요약으로
    pipeline.apply_recap(p, "arc", 1, "첫 시험을 넘겼다")
    text = prompts.story_so_far(p, b.start_ep + 5)
    assert "첫 시험을 넘겼다" in text and "1화 요약" not in text
    text = prompts.story_so_far(p, b.start_ep)  # 아크 첫머리에는 직전 아크 마지막 화도 본다
    assert "12화 요약" in text


def test_recap_needs_finished_arc():
    p = _serial()
    _plan_arc(p)
    with pytest.raises(ValueError, match="끝나야"):
        pipeline.recap(LLM, p, "arc", 1)


def test_cast_filter_and_foreshadow_filter():
    p = _serial()
    a = _plan_arc(p)
    p.characters.append(Character(id="extra", name="행인", role="단역", tier="minor"))
    p.episode(3).plot.characters = ["hero", "extra"]
    p.episode(1).status = p.episode(2).status = "finalized"
    p.foreshadows = [
        Foreshadow(id="fs-old", description="오래된 열쇠", planted_ep=1),
        Foreshadow(id="fs-big", description="세계의 비밀", planted_ep=1, scope="series"),
    ]
    ctx = prompts.build_episode_context(p, 3)
    static = prompts.static_context(p)
    assert "행인" not in static and "행인" in ctx  # 단역은 나오는 화에만
    assert "세계의 비밀" in ctx
    fs, cut = prompts.relevant_foreshadows(p, 200)
    assert [f.id for f in fs] == ["fs-big"] and cut == 1
    a.payoffs = ["fs-old"]
    fs, _ = prompts.relevant_foreshadows(p, 3)
    assert {f.id for f in fs} == {"fs-old", "fs-big"}


def test_facts_filter():
    p = _serial()
    p.facts = ["서윤의 칼은 부러졌다"] + [f"사실 {i}" for i in range(100)]
    facts, cut = prompts.relevant_facts(p, {"hero"})
    assert "서윤의 칼은 부러졌다" in facts and "사실 0" not in facts and cut == 70
    assert prompts.relevant_facts(p, {"ally"})[1] == 71


def test_new_characters_from_state_delta():
    p = _serial()
    a = _plan_arc(p)
    e = p.episode(1)
    e.text, e.status = "본문", "written"
    d = StateDelta(episode=1, summary="요약", new_characters=[Character(id="smith", name="대장장이", role="조연")])
    pipeline.apply_delta(p, d)
    smith = next(c for c in p.characters if c.id == "smith")
    assert (smith.tier, smith.first_ep) == ("support", 1)
    assert a.start_ep == 1


def test_plot_chat_in_serial_edits_focus_arc():
    p = _serial()
    a1 = _plan_arc(p)
    a2 = _plan_arc(p)
    for n in range(a1.start_ep, a1.end_ep + 1):
        p.episode(n).status = "finalized"
    assert pipeline.focus_arc(p).number == 2
    rev = pipeline.revise_plot(LLM, p, "결말을 비극으로")
    assert rev.acts and rev.acts[0].start_ep == a2.start_ep
    pipeline.apply_revision(p, rev, True, [])
    assert p.story_arcs[1].acts[-1].goal == "비극으로 끝난다"
    assert p.story_arcs[0].acts[-1].goal != "비극으로 끝난다"
    rev = pipeline.revise_plot(LLM, p, "40화로 늘려 줘")
    assert rev.total_episodes == 0 and "부 구성" in rev.reply
    assert p.meta.target_episodes == 300


def test_serial_plot_prompt_has_no_full_history():
    p = _serial()
    for _ in range(3):
        a = _plan_arc(p)
        _finish(p, a)
    pr = prompts.plot_prompt(p, p.story_arcs[-1].end_ep + 1, p.story_arcs[-1].end_ep + 5)
    assert '"number": 1,' not in pr  # 1화 플롯 전체는 들어가지 않는다
    assert "지금까지의 줄거리" in pr


def test_series_rejects_gaps():
    p = _serial(300)
    plan = pipeline.plan_series(LLM, p)
    plan.parts[1].start_ep = 120
    with pytest.raises(ValueError):
        pipeline.apply_series(p, plan)


def test_episode_plot_unchanged_shape():
    # 화별 플롯 스키마는 그대로라 예전 PlotBatch 를 읽는다
    EpisodePlot(number=1, act="기", title="t", summary="s", events=[], characters=[], emotional_shift="", ending_hook="")


def test_cli_serial_flow(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CANON_LLM", "mock")
    from canon import store
    from canon.cli import main

    monkeypatch.setattr(store, "ROOT", tmp_path)

    main(["new", "tower", "--title", "탑", "--genre", "판타지", "--logline", "x", "--episodes", "200", "--serial", "-y"])
    main(["series", "tower", "-y"])
    main(["nextarc", "tower", "--len", "6", "-y"])
    main(["plot", "tower"])
    main(["confirm", "tower", "all"])
    main(["run", "tower", "-y", "--no-check"])
    out = capsys.readouterr().out
    assert "다음 아크: nextarc tower" in out and "recap tower arc 1" in out
    main(["recap", "tower", "-y"])
    main(["nextarc", "tower", "-y"])
    main(["arcs", "tower"])
    p = store.load("tower")
    assert p.serial and len(p.parts) == 2 and p.story_arcs[0].summary
    assert [s.end_ep for s in p.story_arcs] == [6, 18]
    main(["nextarc", "tower", "--redo", "--len", "8", "-y"])
    assert store.load("tower").story_arcs[1].end_ep == 14


def test_web_serial_flow(tmp_path, monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    from .test_web import _wait

    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store, web

    importlib.reload(store)
    importlib.reload(web)
    c = TestClient(web.app)
    meta = {"title": "탑", "target_episodes": 200, "form": "serial"}
    assert c.post("/api/projects", json={"name": "t", "meta": meta}).status_code == 200
    c.post("/api/projects/t/suggest/apply", json=c.post("/api/projects/t/suggest").json())

    j = _wait(c, c.post("/api/projects/t/jobs", json={"kind": "series"}).json()["id"])
    p = c.post("/api/projects/t/series/apply", json=j["result"]).json()
    assert len(p["parts"]) == 2
    assert c.post("/api/projects/t/jobs", json={"kind": "plots"}).status_code == 400  # 아크 없음

    j = _wait(c, c.post("/api/projects/t/jobs", json={"kind": "nextarc", "length": 8, "note": "시험"}).json()["id"])
    assert j["status"] == "done" and j["result"]["arc"]["end_ep"] == 8
    p = c.post("/api/projects/t/arcs/apply", json=j["result"]).json()
    assert p["story_arcs"][0]["number"] == 1
    j = _wait(c, c.post("/api/projects/t/jobs", json={"kind": "plots", "ep": 1}).json()["id"])
    assert j["status"] == "done", j["error"]
    p = c.get("/api/projects/t").json()
    assert [e["plot"]["number"] for e in p["episodes"]] == list(range(1, 9))

    # 화면 저장(PUT)은 아크 안 기승전결이 어긋나면 막는다
    bad = dict(p)
    bad["story_arcs"] = [dict(p["story_arcs"][0], end_ep=9)]
    assert c.put("/api/projects/t", json=bad).status_code == 400
    assert c.put("/api/projects/t", json=p).status_code == 200

    assert c.post("/api/projects/t/jobs", json={"kind": "recap_arc", "ep": 1}).status_code == 200
    p = c.delete("/api/projects/t/arcs/last").json()
    assert p["story_arcs"] == [] and p["episodes"] == []
    p = c.post("/api/projects/t/recap/part/1", json={"summary": "1부 요약"}).json()
    assert p["parts"][0]["summary"] == "1부 요약"

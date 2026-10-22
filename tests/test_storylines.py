"""이야기 줄기(서브플롯 · 과거 회상 · 외전) 테스트 (mock LLM). 실행: python -m pytest tests"""
import pytest

from canon import pipeline, prompts, storylines
from canon.mock import MockLLM
from canon.schema import PlotRevision, Project, Storyline, StorylineProposal

from .test_web import _wait, client  # noqa: F401  (pytest fixture)

LLM = MockLLM()


def _short(total=12) -> Project:
    p = Project()
    p.meta.title, p.meta.target_episodes = "등대", total
    pipeline.apply_setup(p, pipeline.suggest_setup(LLM, p))
    p.arc = pipeline.plan_arc(LLM, p).acts
    pipeline.apply_plots(p, pipeline.draft_plots(LLM, p, 1, total))
    return p


def _flashback(p: Project) -> Storyline:
    return pipeline.apply_storyline(p, pipeline.suggest_storyline(LLM, p, "4화에 과거 회상"))


def test_old_project_has_no_storylines():
    p = Project.model_validate({"episodes": [{"plot": {"number": 1, "act": "기", "title": "t", "summary": "s", "events": [],
                                                        "characters": [], "emotional_shift": "", "ending_hook": ""}}]})
    assert p.storylines == [] and p.episodes[0].plot.storyline == "" and p.episodes[0].plot.threads == []
    assert storylines.episode_block(p, 1) == "" and prompts.lines_block(p) == ""
    assert "이야기 줄기" not in prompts.plot_rules(p)


def test_suggest_cleans_and_apply_tags():
    p = _short()
    p.episodes[0].text = "본문"  # 1화는 본문이 있어 붙이지 않는다
    prop = pipeline.suggest_storyline(LLM, p, "1화와 4화")
    assert prop.storyline.id == "sl-01" and prop.storyline.focus == ["hero"]  # 없는 인물은 빠진다
    prop2 = pipeline.suggest_storyline(LLM, p, "4화에 과거 회상")
    assert prop2.episodes == [4] and prop2.threads == [5] and "999" in prop2.reply  # 플롯 없는 화는 빠지고 이유를 말한다
    s = pipeline.apply_storyline(p, prop2)
    assert p.episode(4).plot.storyline == s.id and s.id in p.episode(5).plot.threads
    assert storylines.episodes_of(p, s.id) == [(4, "main"), (5, "thread")]
    assert storylines.span(p, s) == (4, 6) and storylines.is_open(p, s)
    with pytest.raises(ValueError):
        pipeline.apply_storyline(p, StorylineProposal(storyline=Storyline(id="x", title=" ")))


def test_tagging_keeps_confirmed_status_and_redraft_keeps_tags():
    p = _short()
    p.episode(4).status = "confirmed"
    s = _flashback(p)
    assert p.episode(4).status == "confirmed"
    pipeline.apply_plots(p, pipeline.draft_plots(LLM, p, 5, 6))  # 다시 초안을 만들어도 작가가 붙인 줄기는 남는다
    assert s.id in p.episode(5).plot.threads


def test_remove_storyline_untags():
    p = _short()
    s = _flashback(p)
    pipeline.remove_storyline(p, s.id)
    assert p.storylines == [] and p.episode(4).plot.storyline == "" and p.episode(5).plot.threads == []


def test_unknown_storyline_ids_are_dropped_from_plots():
    p = _short()
    batch = pipeline.draft_plots(LLM, p, 2, 3)
    batch.episodes[0].storyline, batch.episodes[1].threads = "sl-99", ["sl-98"]
    pipeline.apply_plots(p, batch)
    assert p.episode(2).plot.storyline == "" and p.episode(3).plot.threads == []


def test_flashback_context_and_state_rules():
    p = _short()
    s = _flashback(p)
    ctx = prompts.build_episode_context(p, 4)
    assert "# 이번 화의 이야기 줄기" in ctx and "10년 전" in ctx and "몰랐던 것" in ctx
    assert ctx.index("# 지금까지의 줄거리") < ctx.index("# 이번 화의 이야기 줄기") < ctx.index("# 직전 화")
    five = prompts.build_episode_context(p, 5)
    assert "장면으로 끼어드는 줄기" in five and "몰랐던 것" not in five
    assert "# 이번 화의 이야기 줄기" not in prompts.build_episode_context(p, 7)
    assert "emotional_state" in prompts.state_prompt(p, 4) and "과거:" in prompts.state_prompt(p, 4)
    assert "과거:" not in prompts.state_prompt(p, 5)
    p.episode(4).text = "본문"
    assert "4화의 이야기 줄기" in prompts.check_prompt(p, 4)
    # 줄거리 요약에 줄기가 표시된다
    p.episode(4).summary = "오빠가 떠난 밤"
    assert f"[과거 회상: {s.title}]" in prompts.story_so_far(p, 6)


def test_plan_prompts_list_storylines():
    p = _short()
    _flashback(p)
    for pr in (prompts.plot_prompt(p, 6, 8), prompts.plot_chat_prompt(p, "4화 고쳐"), prompts.storyline_prompt(p, "", "")):
        assert "서윤의 오빠가 떠난 밤" in pr
    assert "threads" in prompts.plot_rules(p)


def test_ascii_map():
    p = _short()
    s = _flashback(p)
    m = storylines.ascii_map(p)
    row = next(line for line in m.splitlines() if line.startswith(s.id))
    cells = row[10:22]
    assert cells[3] == "●" and cells[4] == "·" and cells[5] == "╯"


def test_web_storyline_flow(client):  # noqa: F811
    c = client
    assert c.post("/api/projects", json={"name": "줄기", "meta": {"title": "줄기", "target_episodes": 12}}).status_code == 200
    p = Project.model_validate(c.get("/api/projects/줄기").json())
    p.meta.title = "줄기"
    pipeline.apply_setup(p, pipeline.suggest_setup(LLM, p))
    p.arc = pipeline.plan_arc(LLM, p).acts
    pipeline.apply_plots(p, pipeline.draft_plots(LLM, p, 1, 12))
    assert c.put("/api/projects/줄기", json=p.model_dump()).status_code == 200
    job = c.post("/api/projects/줄기/jobs", json={"kind": "storyline", "note": "4화에 과거 회상"}).json()
    prop = _wait(c, job["id"])["result"]
    assert prop["storyline"]["id"] == "sl-01" and prop["episodes"] == [4]
    r = c.post("/api/projects/줄기/storylines/apply", json={"proposal": prop, "episodes": [4], "threads": []})
    assert r.status_code == 200
    q = r.json()
    assert q["storylines"][0]["id"] == "sl-01" and q["episodes"][3]["plot"]["storyline"] == "sl-01"
    assert q["episodes"][4]["plot"]["threads"] == []  # 고르지 않은 장면 화는 붙이지 않는다
    bad = q | {"episodes": [e | {"plot": e["plot"] | {"storyline": "sl-77"}} if e["plot"]["number"] == 2 else e for e in q["episodes"]]}
    assert c.put("/api/projects/줄기", json=bad).status_code == 400
    q = c.delete("/api/projects/줄기/storylines/sl-01").json()
    assert q["storylines"] == [] and q["episodes"][3]["plot"]["storyline"] == ""


def test_plot_chat_keeps_storyline_tags():
    p = _short()
    s = _flashback(p)
    changed = p.episode(4).plot.model_copy(update={"summary": "더 천천히", "storyline": "", "threads": []})
    rev = pipeline.clean_revision(p, PlotRevision(reply="고쳤어요", episodes=[changed]))
    assert rev.episodes[0].storyline == s.id  # AI 가 줄기를 빠뜨려도 작가가 붙인 줄기는 남는다
    pipeline.apply_revision(p, rev, False, [4])
    assert p.episode(4).plot.storyline == s.id and p.episode(4).plot.summary == "더 천천히"

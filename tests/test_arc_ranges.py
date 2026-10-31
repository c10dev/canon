"""기승전결 구간 범위: 짧은 작품(1~3화)의 구간 공유와 AI 가 낸 어긋난 범위 고치기. 실행: python -m pytest tests"""
import pytest
from fastapi.testclient import TestClient

from canon import pipeline, prompts
from canon.mock import MockLLM
from canon.schema import Act, ArcPlan, Project

LLM = MockLLM()


def _plan(ranges) -> ArcPlan:
    return ArcPlan(acts=[Act(name=n, start_ep=a, end_ep=b, goal=f"{n} 목표", key_turn=f"{n} 전환")
                         for n, (a, b) in zip("기승전결", ranges)])


def _ranges(plan: ArcPlan):
    return [(a.start_ep, a.end_ep) for a in sorted(plan.acts, key=pipeline.act_order)]


@pytest.mark.parametrize("total", [1, 2, 3, 4, 5, 12, 16, 20, 40])
def test_act_ranges_cover_every_episode(total):
    r = pipeline.act_ranges(total)
    pipeline.validate_arc(_plan(r), total)
    assert r[0][0] == 1 and r[-1][1] == total
    assert {n for a, b in r for n in range(a, b + 1)} == set(range(1, total + 1))


def test_short_work_shares_episodes():
    assert pipeline.act_ranges(3) == [(1, 1), (2, 2), (3, 3), (3, 3)]
    pipeline.validate_arc(_plan([(1, 1), (1, 2), (2, 3), (3, 3)]), 3)  # 이웃 구간이 한 화를 함께 쓴다
    with pytest.raises(ValueError):
        pipeline.validate_arc(_plan([(1, 2), (2, 5), (6, 9), (10, 12)]), 12)  # 4화 이상은 겹치면 안 된다
    with pytest.raises(ValueError):
        pipeline.validate_arc(_plan([(1, 1), (1, 1), (3, 3), (3, 3)]), 3)  # 2화가 빠졌다


def test_fit_arc_repairs_model_ranges_keeping_goals():
    plan = _plan([(1, 2), (3, 6), (6, 9), (10, 11)])  # 승과 전이 겹치고 12화가 빠졌다
    assert pipeline.fit_arc(plan, 12)
    assert _ranges(plan) == [(1, 2), (3, 6), (7, 10), (11, 12)]
    assert [a.goal for a in plan.acts] == ["기 목표", "승 목표", "전 목표", "결 목표"]
    ok = _plan([(1, 3), (4, 9), (10, 13), (14, 16)])
    assert not pipeline.fit_arc(ok, 16)
    assert _ranges(ok) == [(1, 3), (4, 9), (10, 13), (14, 16)]
    with pytest.raises(ValueError):
        pipeline.fit_arc(ArcPlan(acts=_plan([(1, 1)] * 4).acts[:3]), 3)  # 구간이 셋뿐이면 고치지 않는다


def test_three_episode_flow():
    p = Project()
    p.meta.title, p.meta.target_episodes = "세 화", 3
    pipeline.apply_setup(p, pipeline.suggest_setup(LLM, p))
    p.arc = pipeline.plan_arc(LLM, p).acts
    assert [a.name for a in p.acts_for(3)] == ["전", "결"]
    assert "이웃한 구간이 한 화를 함께" in prompts.arc_prompt(p)
    pipeline.apply_plots(p, pipeline.draft_plots(LLM, p, 1, 3))
    assert [e.plot.act for e in p.episodes] == ["기", "승", "전"]  # plot.act 는 한 구간 이름만 받는다
    Project.model_validate(p.model_dump())  # 저장한 뒤 다시 읽혀야 한다
    for e in p.episodes:
        e.status = "confirmed"
    ctx = prompts.build_episode_context(p, 3)
    assert "이 화에 이어서 들어갈 구간: 결" in ctx


def test_web_plot_job_groups_shared_acts(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_LLM", "mock")
    from canon import web
    p = Project()
    p.meta.title, p.meta.target_episodes = "세 화", 3
    p.arc = [Act(name=n, start_ep=a, end_ep=b, goal="g", key_turn="k")
             for n, (a, b) in zip("기승전결", pipeline.act_ranges(3))]
    assert web._plot_ranges(p) == [("기", 1, 1), ("승", 2, 2), ("전·결", 3, 3)]
    c = TestClient(web.app)
    assert c.post("/api/projects", json={"name": "t3", "meta": {"title": "세 화", "target_episodes": 3}}).status_code == 200
    cur = c.get("/api/projects/t3").json()
    cur["arc"] = [a.model_dump() for a in p.arc]
    assert c.put("/api/projects/t3", json=cur).status_code == 200  # 저장 검증도 구간 공유를 받아들인다


def test_empty_plot_batch_says_so_with_model_note():
    """AI 가 형식은 맞지만 화를 하나도 내지 않으면, 범위가 다르다는 말 대신 빈 결과와 AI 가 남긴 말을 알린다."""
    from canon.schema import PlotBatch

    class Empty:
        last_note = "이 범위는\n쓰지 않겠습니다."

        def json(self, system, prompt, schema, hint=None):
            return PlotBatch(episodes=[])

    p = Project()
    p.meta.target_episodes = 4
    p.arc = _plan(pipeline.act_ranges(4)).acts
    with pytest.raises(ValueError, match="1~4화 플롯을 하나도 내지 않았어요. AI가 남긴 말: 이 범위는 쓰지 않겠습니다."):
        pipeline.draft_plots(Empty(), p, 1, 4)
    Empty.last_note = ""
    with pytest.raises(ValueError, match="AI가 이유를 남기지 않았어요"):
        pipeline.draft_plots(Empty(), p, 1, 4)

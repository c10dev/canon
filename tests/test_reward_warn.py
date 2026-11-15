"""웹소설 틀 장편의 보상 박자 경고 (docs/webnovel/specs/07-reward-warn.md, canon/reward.py): 하렘 균열이 김 · 아크에 성장이 없음.
화면 static/plot.js 의 rewardRows 가 같은 규칙인지 node 로 맞춰 본다 (mock LLM). 실행: python -m pytest tests/test_reward_warn.py"""
from canon import dynamics, reward
from canon.schema import AbilityPlan

from .jsvm import dump, needs_node, run_js
from .test_serial import _plan_arc, _serial

FILES = ["app.js", "home.js", "plot.js"]


def _work(done: int = 4, stage: str = "균열", since: int = 2):
    """웹소설 틀 · 하렘 요소 장편. 아크 1 의 공략 대상은 ally, 1~done 화를 반영했고 hero ↔ ally 가 since 화부터 stage 다."""
    p = _serial()
    p.meta.frame, p.meta.genres = "webnovel", [*p.meta.genres, "harem"]
    a = _plan_arc(p)
    a.focus, a.gain = "ally", "검술 해금"
    for e in p.episodes:
        if e.plot.number <= done:
            e.text, e.status = "본문", "finalized"
    for s, t in (("hero", "ally"), ("ally", "hero")):
        tie = dynamics.get_tie(p.ties, s, t)
        tie.stage, tie.stage_since = stage, since
    return p, a


def _name(p, cid):
    return next(c.name for c in p.characters if c.id == cid)


def _js(p):
    return run_js(FILES, "rewardRows(data.p)", {"p": dump(p)})


def test_hero_is_the_protagonist():
    p, _ = _work()
    assert reward.hero_id(p) == "hero"


def test_harem_rift_counts_finalized_and_planned_episodes():
    """정할 것 8: 3화까지는 괜찮고 4화째부터 알린다. 반영한 화(stage_since 부터)와 회복하지 않는 안 쓴 화 플롯을 함께 센다."""
    p, a = _work(done=4, since=2)  # 반영한 화 2~4: 3화
    hero, ally = _name(p, "hero"), _name(p, "ally")
    p.episode(5).plot.summary = f"{hero}와 {ally}는 서로를 용서하고 화해한다."
    assert reward.harem_rows(p) == []  # 3화 뒤 바로 다음 화에 화해
    p.episode(5).plot.summary = "다른 일이 일어난다."
    p.episode(6).plot.summary = f"{hero}와 {ally}가 화해한다."
    rows = reward.harem_rows(p)
    assert [(r["kind"], r["n"]) for r in rows] == [("harem", 5)] and "4화 이어져요" in rows[0]["text"]
    assert "안 쓴 화 플롯 1화" in rows[0]["text"]


def test_harem_rift_boundary_from_finalized_only():
    p, _ = _work(done=5, since=3)  # 3~5화: 3화
    hero, ally = _name(p, "hero"), _name(p, "ally")
    p.episode(6).plot.summary = f"{hero}와 {ally}가 화해한다."
    assert reward.harem_rows(p) == []
    p, _ = _work(done=5, since=2)  # 2~5화: 4화
    p.episode(6).plot.summary = f"{_name(p, 'hero')}와 {_name(p, 'ally')}가 화해한다."
    rows = reward.harem_rows(p)
    assert len(rows) == 1 and "4화 이어져요" in rows[0]["text"] and "안 쓴 화" not in rows[0]["text"]


def test_harem_rift_needs_frame_harem_and_focus():
    p, a = _work(done=6, since=1)
    assert reward.harem_rows(p)
    p.meta.frame = "drama"  # 드라마 틀 하렘 작품에는 내지 않는다 (정할 것 5)
    assert reward.rows(p) == []
    p.meta.frame, p.meta.genres = "webnovel", [g for g in p.meta.genres if g != "harem"]
    assert reward.harem_rows(p) == []
    p.meta.genres.append("harem")
    a.focus = ""
    assert reward.harem_rows(p) == []
    a.focus = "ally"
    for t in p.ties:
        t.stage = "호감"
    assert reward.harem_rows(p) == []


def test_growth_needs_gain_or_ability_plan():
    p, a = _work(done=0, stage="호감")
    assert reward.growth_rows(p) == []
    a.gain = ""
    rows = reward.growth_rows(p)
    assert [(r["kind"], r["n"]) for r in rows] == [("growth", a.number)]
    p.blueprint.ability_plans = [AbilityPlan(character="hero", ability="화염구", from_ep=a.end_ep, to_ep=a.end_ep + 5)]
    assert reward.growth_rows(p) == []
    p.blueprint.ability_plans = []
    for e in p.episodes:  # 모든 화를 쓴 아크는 고칠 플롯이 없어 알리지 않는다
        if a.start_ep <= e.plot.number <= a.end_ep:
            e.text = "본문"
    assert reward.growth_rows(p) == []


def test_drama_and_short_stay_empty():
    p, a = _work(done=6, since=1)
    a.gain = ""
    p.meta.frame = "drama"
    assert reward.rows(p) == []
    p.meta.frame, p.meta.form = "webnovel", "short"
    assert reward.rows(p) == []


@needs_node
def test_js_matches_python():
    p, a = _work(done=4, since=2)
    hero, ally = _name(p, "hero"), _name(p, "ally")
    p.episode(6).plot.summary = f"{hero}와 {ally}가 화해한다."
    a.gain = ""
    want = reward.rows(p)
    assert {r["kind"] for r in want} == {"harem", "growth"}
    assert _js(p) == want
    p.meta.frame = "drama"
    assert _js(p) == [] == reward.rows(p)
    p.meta.frame = "webnovel"
    for since, done in ((3, 5), (2, 5), (0, 3)):
        q, _ = _work(done=done, since=since)
        assert _js(q) == reward.rows(q), (since, done)


@needs_node
def test_todos_show_only_for_webnovel_serial():
    p, a = _work(done=6, since=1)
    a.gain = ""
    todos = run_js(FILES, "rewardTodos(data.p)", {"p": dump(p)})
    assert [t["text"].split(" · ")[0] for t in todos] == ["하렘 균열이 김", "아크 성장 없음"]
    assert todos[1]["action"] == "selectArc" and todos[0]["n"] == 7
    p.meta.frame = "drama"
    assert run_js(FILES, "rewardTodos(data.p)", {"p": dump(p)}) == []

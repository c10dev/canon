"""장편 상태 변경안의 '[이미 있는 확정 사실]'과 비슷한 새 사실: 블록 · 뺀 수 · 요구사항, 비슷한 사실 표시(fact_near),
자동 반영은 빼 둠(dismissed), 반영 기록에서 나중에 넣기, 상태 승인 화면 기본 체크. 실행: python -m pytest tests"""
from canon import context, features, pipeline, prompts, store
from canon.schema import StateDelta

from .jsvm import needs_node, run_js
from .test_char_context import _long, _short
from .test_storylines import _short as _short8
from .test_timeline import LLM, _play

HEAD = "[이미 있는 확정 사실 — 다시 적지 않습니다]"
RULE = "에 없는 새 사실만 적습니다"


def _next(p):
    return max(e.plot.number for e in p.episodes if e.text)


def test_serial_state_prompt_lists_facts_and_rule():
    p = _long()
    n = _next(p)
    p.facts.append("등대지기는 매일 밤 불을 켠다")
    out = prompts.state_prompt(p, n)
    assert HEAD in out and "- 등대지기는 매일 밤 불을 켠다" in out
    assert "new_facts 에는 [이미 있는 확정 사실]" + RULE in out
    assert out.index(HEAD) < out.index("[이미 있는 장소]")


def test_short_state_prompt_unchanged():
    p = _short()
    p.facts.append("등대지기는 매일 밤 불을 켠다")
    out = prompts.state_prompt(p, 2)
    assert HEAD not in out and RULE not in out


def test_state_facts_budget_counts_cut(monkeypatch):
    p = _long()
    n = _next(p)
    p.facts = [f"오래된 사실 {i}: 바다 건너 마을의 우물은 {i}번째 해에 말랐다" for i in range(80)]
    monkeypatch.setitem(context.BUDGET, "state_facts", 200)
    out = prompts.state_prompt(p, n)
    kept = [x for x in out.split(HEAD)[1].split("[이미 있는 장소]")[0].splitlines() if x.startswith("- ")]
    assert len(kept) == context.FACTS_RECENT  # 최근 것은 늘 넣고, 겹치지 않는 옛 사실은 뺀다
    assert f"{80 - len(kept)}개 생략" in out


def test_play_state_prompt_uses_play_budget(monkeypatch):
    p = _long()
    n = _next(p)
    seen = []
    real = context.pick_facts
    monkeypatch.setattr(context, "pick_facts", lambda q, ids, query, budget, terms=(): seen.append(budget) or real(q, ids, query, budget, terms))
    prompts.play_state_prompt(p, n)
    assert context.BUDGET["play_state_facts"] in seen and context.BUDGET["state_facts"] not in seen


def test_near_fact_threshold():
    old = ["학과 단톡방 인원은 마흔 명쯤이다.", "지훈에게서는 섬유유연제 냄새 밑에 마른 삼나무 같은 나무 향이 난다"]
    assert context.near_fact("학과 단톡방 인원은 마흔 명이다", old) == old[0]
    assert context.near_fact("지훈에게서는 섬유유연제 냄새와 그 밑에 깔린 마른 삼나무 향이 난다", old) == old[1]
    assert context.near_fact("아영의 집은 신도림역 근처 아파트다", old) == ""
    assert context.near_fact("비", old) == ""  # 짧은 사실은 견주지 않는다
    assert context.near_fact(old[0], old) == ""  # 같은 글은 반영이 거른다


def _delta(p, n):
    p.facts.append("학과 단톡방 인원은 마흔 명쯤이다.")
    return StateDelta(episode=n, summary=f"{n}화", new_facts=["학과 단톡방 인원은 마흔 명이다", "등대 계단은 백십 칸이다"])


NEAR = "학과 단톡방 인원은 마흔 명이다"


def test_clean_marks_near_facts_and_hold_dismisses():
    p = _long()
    d = _delta(p, _next(p))
    pipeline.clean_delta(p, d)
    assert [(x.fact, x.like) for x in d.fact_near] == [(NEAR, "학과 단톡방 인원은 마흔 명쯤이다.")]
    assert not any("확정 사실" in w for w in d.warnings)  # 화면은 경고 대신 그 줄에 적는다
    features.hold(p, d)
    assert d.new_facts == ["등대 계단은 백십 칸이다"] and d.dismissed.new_facts == [NEAR]
    assert d.warnings[-1] == f"확정 사실: 이미 있는 사실과 비슷해 자동 반영에서 뺐어요: {NEAR}"
    assert len(d.warn_to) == len(d.warnings)


def test_short_does_not_mark_or_hold():
    p = _play(_short8(8), 1, 2)
    d = _delta(p, 3)
    pipeline.clean_delta(p, d)
    assert d.fact_near == []
    features.hold(p, d)
    assert NEAR in d.new_facts and d.dismissed.new_facts == []


def test_take_dismissed_fact_later():
    from canon.schema import FactNear
    p = _play(_short8(8), 1, 2)
    pipeline.confirm_plot(p, 3)
    p.episode(3).text, p.episode(3).status = pipeline.write_episode(LLM, p, 3), "written"
    d = _delta(p, 3)
    d.new_facts = ["등대 계단은 백십 칸이다"]
    pipeline.apply_delta(p, d)
    rec = p.history[-1]
    rec.dismissed.new_facts = [NEAR, "학과 단톡방 인원은 마흔 명쯤이다."]  # 자동 반영이 뺀 것처럼 둔다
    rec.fact_near = [FactNear(fact=NEAR, like="학과 단톡방 인원은 마흔 명쯤이다.")]
    assert pipeline.take_dismissed_fact(p, 3, 0) == NEAR
    assert p.facts[-1] == NEAR and rec.dismissed.new_facts == ["학과 단톡방 인원은 마흔 명쯤이다."] and rec.fact_near == []
    assert NEAR in rec.new_facts and NEAR in rec.added.facts and NEAR in p.snapshot(3).facts
    n = len(p.facts)
    assert pipeline.take_dismissed_fact(p, 3, 0) == "" and len(p.facts) == n  # 이미 있는 사실은 빼 둔 목록에서만 지운다
    assert rec.dismissed.new_facts == []
    pipeline.revert(p, 2)  # 반영 취소하면 함께 빠진다
    assert NEAR not in p.facts
    try:
        pipeline.take_dismissed_fact(p, 3, 0)
        raise AssertionError("반영 기록이 없으면 막아야 해요")
    except ValueError as e:
        assert "빼 둔 사실이 없어요" in str(e)


def test_take_dismissed_fact_endpoint(client):
    p = _play(_short8(8), 1, 2)
    p.history[-1].dismissed.new_facts = ["등대 계단은 백십 칸이다"]
    store.save("lh", p)
    r = client.post("/api/projects/lh/episodes/2/dismissed-facts/0")
    assert r.status_code == 200 and "등대 계단은 백십 칸이다" in r.json()["facts"]
    assert client.post("/api/projects/lh/episodes/2/dismissed-facts/0").status_code == 400


@needs_node
def test_review_unchecks_near_facts():
    d = {"new_facts": ["학과 단톡방 인원은 마흔 명이다", "등대 계단은 백십 칸이다"],
         "fact_near": [{"fact": "학과 단톡방 인원은 마흔 명이다", "like": "학과 단톡방 인원은 마흔 명쯤이다."}]}
    expr = """(() => { S.project = {characters: [], relationships: [], foreshadows: [], episodes: []};
      const d = {character_updates: [], events: [], secrets_added: [], relationship_updates: [], foreshadow_planted: [], foreshadow_resolved: [], ...data};
      const o = defaultPicks(d); return [o.f0, o.f1]; })()"""
    assert run_js(["app.js", "review.js"], expr, d) == [False, True]


def test_cli_asks_near_facts(monkeypatch, capsys):
    from canon import cli
    p = _long()
    d = _delta(p, _next(p))
    pipeline.clean_delta(p, d)
    monkeypatch.setattr(cli, "confirm", lambda msg, yes=False: False)
    cli._ask_near_facts(d)
    assert d.new_facts == ["등대 계단은 백십 칸이다"] and d.dismissed.new_facts == ["학과 단톡방 인원은 마흔 명이다"]
    assert "← 학과 단톡방 인원은 마흔 명쯤이다." in capsys.readouterr().out and d.fact_near == []

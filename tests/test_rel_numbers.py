"""관계 수치는 AI 가 적지 않는다: 상태 변경안의 응답 형식에 수치 칸이 없고, 반영은 relationship_updates 의 수치를 쓰지 않는다.
예전 반영 기록(legacy_rel)만 다시 계산할 때 예전 방식으로 돈다."""
import json

from canon import dynamics, pipeline, prompts
from canon.llm import _inline_refs
from canon.schema import Character, Relationship, StateDelta, StateDeltaAI, StoryEvent, to_delta
from .test_storylines import _short


def _ready(p, n):
    pipeline.confirm_plot(p, n)
    ep = p.episode(n)
    ep.text, ep.status = "본문.", "written"


def _warmth(p, a, b):
    return dynamics.find_tie(p.ties, a, b).warmth


def test_ai_schema_has_no_numbers():
    js = _inline_refs(StateDeltaAI.model_json_schema())
    text = json.dumps(js, ensure_ascii=False)
    for k in ("affinity", "tension", "goal_conflict", "a_view", "b_view", "destination", "set_warmth", "set_trust", "legacy_rel"):
        assert f'"{k}"' not in text, k
    ev = js["properties"]["events"]["items"]
    assert "episode" not in ev["properties"]
    assert "수동보정" not in ev["properties"]["kind"]["enum"] and "도움" in ev["properties"]["kind"]["enum"]
    p = _short(4)
    _ready(p, 1)
    assert '"affinity"' not in prompts.state_brief(p, 1).split("## 출력 형식")[1]


def test_old_json_numbers_are_dropped():
    old = {"episode": 9, "summary": "s",
           "events": [{"episode": 99, "actor": "hero", "target": "ally", "kind": "수동보정", "set_warmth": 1.0, "set_trust": 1.0},
                      {"actor": "ally", "target": "hero", "kind": "도움", "intensity": 7}],
           "relationship_updates": [{"a": "hero", "b": "ally", "type": "원수", "affinity": -5, "tension": 10,
                                     "goal_conflict": 1, "a_view": ["미워한다"], "destination": "연인"}]}
    d = to_delta(StateDeltaAI.model_validate(old), 3)
    assert d.episode == 3 and [e.episode for e in d.events] == [3, 3]
    assert d.events[0].set_warmth is None and d.events[0].set_trust is None and d.events[1].intensity == 3
    r = d.relationship_updates[0]
    assert (r.type, r.affinity, r.tension, r.goal_conflict, r.a_view, r.destination) == ("원수", 0, 0, 0.0, [], "")
    # 가짜 LLM 이 StateDelta 를 그대로 돌려줘도 같게 바꾼다
    full = StateDelta(episode=1, summary="s", relationship_updates=[Relationship(a="hero", b="ally", type="t", affinity=5)],
                      events=[StoryEvent(episode=1, actor="hero", target="ally", kind="도움")])
    d = to_delta(full, 2)
    assert d.relationship_updates[0].affinity == 0 and d.events[0].episode == 2


def test_apply_ignores_numbers_without_events():
    p = _short(4)
    _ready(p, 1)
    r = p.relationships[0]
    base = p.model_copy(deep=True)
    pipeline.apply_delta(base, StateDelta(episode=1, summary="s"))
    upd = Relationship(a=r.a, b=r.b, type="원수", affinity=-5, tension=10)
    pipeline.apply_delta(p, StateDelta(episode=1, summary="s", relationship_updates=[upd]))  # 사건 없음 (작가가 모두 풀었을 때와 같다)
    got = next(x for x in p.relationships if {x.a, x.b} == {r.a, r.b})
    want = next(x for x in base.relationships if {x.a, x.b} == {r.a, r.b})
    assert got.type == "원수"
    assert (got.affinity, got.tension) == (want.affinity, want.tension)
    assert _warmth(p, r.a, r.b) == _warmth(base, r.a, r.b) and _warmth(p, r.b, r.a) == _warmth(base, r.b, r.a)
    rec = p.history[-1]
    assert rec.legacy_rel is False and rec.relationship_updates[0].affinity == 0 and rec.relationship_updates[0].tension == 0


def test_new_pair_starts_neutral():
    p = _short(4)
    _ready(p, 1)
    hero = p.characters[0].id
    new = Character(id="courier", name="배달부", role="minor")
    upd = Relationship(a=hero, b="courier", type="은인", affinity=5, tension=8, a_view=["믿는다"], b_view=["좋아한다"])
    pipeline.apply_delta(p, StateDelta(episode=1, summary="s", new_characters=[new], relationship_updates=[upd]))
    r = next(x for x in p.relationships if {x.a, x.b} == {hero, "courier"})
    assert r.type == "은인" and r.a_view == [] and r.b_view == [] and r.affinity == 0
    assert abs(_warmth(p, hero, "courier")) < 0.05 and abs(_warmth(p, "courier", hero)) < 0.05


def test_replay_numbers_only_for_legacy_records():
    p = _short(4)
    _ready(p, 1)
    r = p.relationships[0]
    pipeline.apply_delta(p, StateDelta(episode=1, summary="s", relationship_updates=[Relationship(a=r.a, b=r.b, type="원수", affinity=-5)]))
    live = {(t.source, t.target): t.warmth for t in p.ties}
    assert abs(live[(r.a, r.b)]) > 0.05  # 설정의 시작 관계가 남아 있어야 아래 비교가 뜻이 있다
    again = {(t.source, t.target): t.warmth for t in dynamics.replay(p)}
    assert again == live  # 지금 반영한 기록은 다시 계산해도 수치를 쓰지 않는다
    # 예전 반영 기록(칸이 없어 True 로 읽힘)은 그때처럼 수치로 온기를 맞춘다
    old = json.loads(p.history[-1].model_dump_json(exclude={"legacy_rel"}))
    old["relationship_updates"][0]["affinity"] = -5
    p.history[-1] = StateDelta.model_validate(old)
    assert p.history[-1].legacy_rel is True
    assert dynamics.find_tie(dynamics.replay(p), r.a, r.b).warmth < -0.5

"""관계 단계에 들어온 화(Tie.stage_since): run_episode 가 적고, 관계 줄에 'n화부터' 로 보이고, replay 가 다시 채운다. 검수 한 줄.
LLM 을 부르지 않는다. 실행: python -m pytest tests"""
from canon import dynamics, prompts
from canon.schema import Character, Project, Relationship, StoryEvent, Tie

from .test_storylines import _short
from .test_timeline import LLM, _play


def _pair() -> Project:
    p = Project(characters=[Character(id="a", name="가람", role="주인공"), Character(id="b", name="나래", role="조연")],
                relationships=[Relationship(a="a", b="b", type="같은 반")])
    dynamics.seed_ties(p)
    return p


def _hurt(n: int) -> list[StoryEvent]:
    return [StoryEvent(episode=n, actor=x, target=y, kind=k, intensity=3)
            for x, y in (("a", "b"), ("b", "a")) for k in ("배신", "모욕", "위협")]


def test_run_episode_records_entry_episode():
    p = _pair()
    assert all(t.stage_since == 0 for t in p.ties)
    seen = []
    for n, events in ((1, []), (2, _hurt(2)), (3, []), (4, []), (5, [])):
        dynamics.run_episode(p, n, events, ["a", "b"])
        t = dynamics.find_tie(p.ties, "a", "b")
        seen.append((n, t.stage, t.stage_since))
    # 단계가 바뀐 화에만 들어온 화가 그 화로 바뀌고, 그대로인 화는 앞 값을 지킨다
    for (_, s0, since0), (n, s1, since1) in zip(seen, seen[1:]):
        assert since1 == (n if s1 != s0 else since0)
    assert any(s != "낯섦" for _, s, _ in seen)
    last = seen[-1]
    assert f"단계: {last[1]}({last[2]}화부터)" in dynamics.describe_relations(p)


def test_label_only_when_known():
    t = Tie(source="a", target="b", stage="적대")
    assert dynamics.since(t) == "" and dynamics.since(t.model_copy(update={"stage_since": 7})) == "(7화부터)"
    assert Tie.model_validate({"source": "a", "target": "b", "stage": "경계"}).stage_since == 0  # 옛 파일


def test_replay_fills_since():
    p = _play(_short(8), 1, 3)
    for t in p.ties:
        t.stage_since = 0  # 필드가 생기기 전에 저장한 작품처럼
    again = {(t.source, t.target): t for t in dynamics.replay(p)}
    want = {(t.source, t.target): t.stage for t in p.ties}
    assert all(again[k].stage == v for k, v in want.items() if k in again)
    assert any(t.stage_since for t in again.values()) == any(t.stage != "낯섦" for t in again.values())


def test_check_rule_only_with_ties():
    p = _play(_short(8), 1, 2)
    assert "- 관계 단계:" in prompts.check_prompt(p, 3)
    assert prompts.stage_check_rule(Project()) == ""


def test_replay_keeps_relations_added_mid_story():
    """1화 뒤에 작가가 더한 관계와 상태 변경안이 더한 새 쌍도 다시 계산(replay)에서 그대로 나온다.
    예전에는 둘 다 빠져 기본값(낯섦)으로 바뀌었다 (2026-11-01 서버 작품 캠핑카 · saintess)."""
    from canon import pipeline
    from canon.schema import StateDelta

    p = _play(_short(8), 1, 2)
    ids = [c.id for c in p.characters]
    pairs = {frozenset((r.a, r.b)) for r in p.relationships}
    a, b = next((x, y) for x in ids for y in ids if x < y and frozenset((x, y)) not in pairs)
    p.relationships.append(Relationship(a=a, b=b, type="경계", a_view=["경계한다"], b_view=["미워한다"]))  # 작가가 2화 뒤에 더함
    _play(p, 3, 4)
    others = [(x, y) for x in ids for y in ids if x < y and frozenset((x, y)) not in pairs | {frozenset((a, b))}]
    if others:  # 상태 변경안이 5화에 새 쌍을 더한다
        c, d = others[0]
        pipeline.confirm_plot(p, 5)
        p.episode(5).text = "본문."
        p.episode(5).status = "written"
        delta = pipeline.extract_state(LLM, p, 5).model_copy(update={"relationship_updates": [Relationship(a=c, b=d, type="동료", affinity=3)]})
        pipeline.apply_delta(p, StateDelta.model_validate(delta.model_dump()))
    live = {(t.source, t.target): t for t in p.ties}
    again = {(t.source, t.target): t for t in dynamics.replay(p)}
    assert set(again) == set(live)
    for k, t in live.items():
        assert again[k].stage == t.stage and abs(again[k].warmth - t.warmth) < 1e-9, k
    assert live[(a, b)].stage != "낯섦"  # 작가가 정한 경계가 살아 있다
    # 스냅샷이 지워진 장편처럼: 그 화 스냅샷이 없으면 지금 반영과 같은 차례로 만든다 (작가가 정한 시작 관계를 잃지 않는다)
    p.snapshots = [s for s in p.snapshots if s.episode == 0 or s.episode >= 5]
    pruned = {(t.source, t.target): t for t in dynamics.replay(p)}
    assert set(pruned) == set(live) and pruned[(a, b)].stage != "낯섦"

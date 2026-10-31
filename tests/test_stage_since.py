"""관계 단계에 들어온 화(Tie.stage_since): run_episode 가 적고, 관계 줄에 'n화부터' 로 보이고, replay 가 다시 채운다. 검수 한 줄.
LLM 을 부르지 않는다. 실행: python -m pytest tests"""
from canon import dynamics, prompts
from canon.schema import Character, Project, Relationship, StoryEvent, Tie

from .test_storylines import _short
from .test_timeline import _play


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

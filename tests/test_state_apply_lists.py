"""상태 반영(pipeline.apply_delta)의 목록 칸: 복사해 넣기, 한 변경안 안의 겹침, AI 가 적은 복선 칸, 이미 회수한 복선."""
from canon import dynamics, features, pipeline
from canon.schema import Character, Foreshadow, ForeshadowClue, Relationship, Secret, StateDelta, StoryEvent

from .test_storylines import _short


def _new_pair_delta() -> StateDelta:
    return StateDelta(
        episode=1, summary="요약",
        new_characters=[Character(id="mira", name="미라", role="조연")],
        relationship_updates=[Relationship(a="hero", b="mira", type="동료", affinity=3, tension=1)],
        events=[StoryEvent(episode=1, actor="hero", target="mira", kind="배신", intensity=3),
                StoryEvent(episode=1, actor="mira", target="hero", kind="배신", intensity=3)])


def test_new_relationship_is_copied_into_project():
    p = _short()
    p.episodes[0].text = "본문"
    pipeline.apply_delta(p, _new_pair_delta())
    sent = p.history[-1].relationship_updates[0]
    live = next(r for r in p.relationships if {r.a, r.b} == {"hero", "mira"})
    assert live is not sent
    assert (sent.affinity, sent.tension) == (3, 1)  # 반영 뒤 사건으로 바뀐 값이 기록에 새지 않는다
    assert (live.affinity, live.tension) != (3, 1)


def test_replay_without_snapshots_matches_live_ties():
    p = _short()
    p.episodes[0].text = "본문"
    pipeline.apply_delta(p, _new_pair_delta())
    live = {(t.source, t.target): round(t.warmth, 6) for t in p.ties}
    p.snapshots = [s for s in p.snapshots if s.episode == 0]  # 장편이 지운 스냅샷
    again = {(t.source, t.target): round(t.warmth, 6) for t in dynamics.replay(p)}
    assert again == live


def test_duplicates_in_one_delta_keep_first():
    p = _short()
    p.episodes[0].text = "본문"
    d = StateDelta(
        episode=1, summary="요약", new_facts=["등대는 북쪽에 있다", "등대는 북쪽에 있다"],
        foreshadow_planted=[Foreshadow(id="fs-1", description="첫째", planted_ep=1),
                            Foreshadow(id="fs-1", description="둘째", planted_ep=1)],
        secrets_added=[Secret(id="sec-1", owner="hero", content="첫째"), Secret(id="sec-1", owner="hero", content="둘째")])
    pipeline.apply_delta(p, d)
    assert p.facts.count("등대는 북쪽에 있다") == 1
    assert [f.description for f in p.foreshadows if f.id == "fs-1"] == ["첫째"]
    assert [s.content for s in p.secrets if s.id == "sec-1"] == ["첫째"]
    h = p.history[-1]
    assert h.new_facts == ["등대는 북쪽에 있다"]
    assert [f.description for f in h.foreshadow_planted] == ["첫째"]
    assert [s.content for s in h.secrets_added] == ["첫째"]
    assert [f.description for f in h.dismissed.foreshadow_planted] == ["둘째"]
    assert [s.content for s in h.dismissed.secrets_added] == ["둘째"]


def test_planted_foreshadow_fields_are_normalised_and_copied():
    p = _short()
    p.episodes[0].text = "본문"
    d = StateDelta(episode=1, summary="요약",
                   foreshadow_planted=[Foreshadow(id="fs-1", description="열쇠", planted_ep=9, status="resolved", payoff_ep=5)])
    pipeline.apply_delta(p, d)
    f = next(f for f in p.foreshadows if f.id == "fs-1")
    assert (f.planted_ep, f.status, f.payoff_ep) == (1, "open", None)
    assert f is not p.history[-1].foreshadow_planted[0]
    assert p.history[-1].foreshadow_planted[0].planted_ep == 1


def test_resolving_resolved_foreshadow_is_skipped_with_warning():
    p = _short()
    for ep in p.episodes[:2]:
        ep.text = "본문"
    pipeline.apply_delta(p, StateDelta(episode=1, summary="요약", foreshadow_planted=[Foreshadow(id="fs-1", description="열쇠", planted_ep=1)],
                                       foreshadow_resolved=["fs-1"]))
    assert next(f for f in p.foreshadows if f.id == "fs-1").payoff_ep == 1  # 심은 화에 회수해도 된다
    d = StateDelta(episode=2, summary="요약", foreshadow_resolved=["fs-1", "fs-1"])
    features.clean(p, d)
    d.foreshadow_clues = [ForeshadowClue(foreshadow="fs-1", kind="payoff", quote="열쇠", episode=2)]
    assert any("이미 1화에 회수한 복선을 다시 회수했어요: fs-1" in w for w in d.warnings)
    pipeline.apply_delta(p, d)
    assert next(f for f in p.foreshadows if f.id == "fs-1").payoff_ep == 1
    assert p.history[-1].foreshadow_resolved == []
    assert p.history[-1].dismissed.foreshadow_resolved == ["fs-1"]
    # 뺀 회수의 회수 문장은 다시 떠올린 문장으로 남아 기록과 맞는다
    assert [(c.episode, c.kind) for c in p.foreshadow_clues if c.foreshadow == "fs-1"] == [(2, "plant")]
    assert [c.kind for c in p.history[-1].foreshadow_clues] == ["plant"]

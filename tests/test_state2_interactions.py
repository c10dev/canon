"""상태 승인 흐름을 고친 여러 변경이 서로 맞는지 (반영 취소 · 목록 정리 · 관계 수치 · 자동 집필 정책 · 명령줄 미리 보기). mock LLM.
실행: python -m pytest tests"""
from canon import autorun, cli, dynamics, pipeline, web
from canon.mock import MockLLM
from canon.schema import Character, Foreshadow, Relationship, Secret, StateDelta, StoryEvent

from .test_revert_author import _extract
from .test_storylines import _short
from .test_timeline import _play

LLM = MockLLM()


def _ties(ts):
    return sorted((t.source, t.target, round(t.warmth, 4), round(t.trust, 4), t.stage) for t in ts)


def _busy_delta(p):
    """새 관계 쌍(수치 포함) · 겹친 사실 · 겹친 복선 · 겹친 비밀 · 이미 있는 인물이 든 2화 변경안."""
    d = _extract(p, 2)
    d.relationship_updates.append(Relationship(a="hero", b="innkeeper", type="AI 관계", affinity=4, tension=3))
    d.new_facts += ["2화 사실", "2화 사실"]
    d.foreshadow_planted += [Foreshadow(id="fs-x", description="x", planted_ep=9, status="resolved"),
                             Foreshadow(id="fs-x", description="겹침", planted_ep=2)]
    d.secrets_added += [Secret(id="s-x", owner="hero", content="a", hidden_from=["ally"]), Secret(id="s-x", owner="hero", content="b")]
    d.new_characters.append(next(c for c in p.characters if c.id == "hero").model_copy())
    return d


def test_revert_then_reapply_kept_record_matches_first_apply():
    p = _play(_short(8), 1, 1)
    pipeline.apply_delta(p, _busy_delta(p))
    assert _ties(dynamics.replay(p)) == _ties(p.ties)
    first = p.model_copy(deep=True)
    rec = p.history[-1]
    assert rec.legacy_rel is False
    assert rec.added.relationships == [["hero", "innkeeper"]] and rec.added.secrets == ["s-x"]
    assert rec.added.facts == ["2화 사실"] and rec.added.foreshadows == ["fs-x"]
    assert [c.id for c in rec.dismissed.new_characters] == ["hero"]
    assert [s.content for s in rec.dismissed.secrets_added] == ["b"]
    assert [f.description for f in rec.dismissed.foreshadow_planted] == ["겹침"]

    kept = web._revert_kept(p, 1)
    pipeline.revert(p, 1)
    assert _ties(dynamics.replay(p)) == _ties(p.ties)
    assert not any({r.a, r.b} == {"hero", "innkeeper"} for r in p.relationships)

    again = StateDelta.model_validate(kept["state:2"]["result"])  # 이전 반영의 added · legacy_rel · dismissed 가 든 채 돌아온다
    assert again.added is not None and again.legacy_rel is False
    pipeline.apply_delta(p, again)
    rec = p.history[-1]
    assert rec.added == first.history[-1].added  # 다시 셌고 두 번 넣지 않았다
    assert [c.id for c in rec.dismissed.new_characters] == ["hero"]
    assert [s.content for s in rec.dismissed.secrets_added] == ["b"]
    assert [f.description for f in rec.dismissed.foreshadow_planted] == ["겹침"]
    assert _ties(p.ties) == _ties(first.ties) and _ties(dynamics.replay(p)) == _ties(p.ties)
    rels = lambda q: sorted((r.a, r.b, r.type, r.affinity, r.tension) for r in q.relationships)  # noqa: E731
    assert rels(p) == rels(first)
    assert sorted(f.model_dump_json() for f in p.foreshadows) == sorted(f.model_dump_json() for f in first.foreshadows)


def test_carried_delta_from_archive_resets_added():
    from .test_rebuild import _rebuilt

    p, *_ = _rebuilt()
    e1 = p.episode(1)
    e1.text, e1.status = "새 1화 본문", "written"
    pipeline.apply_delta(p, pipeline.extract_state(LLM, p, 1))
    d = pipeline.carried_delta(p, 2)
    assert d is not None and d.added is not None  # 단편 때 반영 기록의 added 를 그대로 들고 온다
    d.added.facts.append("옛 기록에만 있는 사실")
    pipeline.apply_delta(p, d)
    rec = p.history[-1]
    assert "옛 기록에만 있는 사실" not in rec.added.facts
    assert rec.added.foreshadows == [f.id for f in rec.foreshadow_planted]
    assert set(rec.added.facts) <= set(p.facts)


def test_story_policy_ignores_items_apply_drops():
    p = _play(_short(8), 1, 1)
    d = _extract(p, 2)
    d.new_characters = [next(c for c in p.characters if c.id == "hero").model_copy()]
    known = p.secrets[0].id
    d.secrets_added = [Secret(id="s-ghost", owner="nobody", content="주인 없음"),
                       Secret(id=known, owner="hero", content="이미 있음")]
    pol = autorun.Policy(stop_on_new_characters=True, stop_on_secrets=True)
    why = autorun.review_reasons(p, d, None, pol)
    assert not any("새 인물" in w or "새 비밀" in w for w in why), why

    d.new_characters.append(Character(id="zz", name="새사람", role="행인"))
    d.secrets_added += [Secret(id="s-new", owner="zz", content="새 비밀"), Secret(id="s-new", owner="zz", content="겹침")]
    why = autorun.review_reasons(p, d, None, pol)
    assert any(w.startswith("새 인물 1명") for w in why), why
    sim = p.model_copy(deep=True)
    pipeline.apply_delta(sim, d.model_copy(deep=True))
    assert any(w.startswith(f"새 비밀 {len(sim.history[-1].added.secrets)}개") for w in why), why


def test_cli_preview_does_not_eat_dropped_messages():
    p = _play(_short(8), 1, 1)
    d = _extract(p, 2)
    d.new_characters.append(next(c for c in p.characters if c.id == "hero").model_copy())
    d.events.append(StoryEvent(episode=2, actor="nobody", target="hero", kind="도움"))
    cli._print_relation_preview(p, d)
    assert d.dismissed.new_characters == [] and d.dismissed.events == []
    dropped = pipeline.apply_delta(p, d)
    assert any("이미 있는 인물" in m for m in dropped)
    assert any("nobody" in m for m in dropped)

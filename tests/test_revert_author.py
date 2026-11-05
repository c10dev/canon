"""반영 취소(pipeline.revert)가 n화 뒤 작가가 더하거나 고친 것을 남기고, 뒤 반영이 한 일만 되돌리는지 (mock LLM). 실행: python -m pytest tests"""
from canon import features, pipeline
from canon.mock import MockLLM
from canon.schema import Character, Foreshadow, Relationship, Secret

from .test_storylines import _short
from .test_timeline import _play

LLM = MockLLM()


def _extract(p, n):
    pipeline.confirm_plot(p, n)
    p.episode(n).text = pipeline.write_episode(LLM, p, n)
    p.episode(n).status = "written"
    return pipeline.extract_state(LLM, p, n)


def test_revert_keeps_author_items_and_drops_later_ai_items():
    p = _play(_short(8), 1, 1)
    d = _extract(p, 2)  # mock 2화: fs-01-key 회수, sec-ally-letter 를 드러내는 사건
    d.new_facts.append("2화: AI 사실")
    d.foreshadow_planted.append(Foreshadow(id="fs-02-ai", description="AI 복선", planted_ep=2))
    d.secrets_added.append(Secret(id="sec-02-ai", owner="hero", content="AI 비밀", hidden_from=["ally"]))
    d.relationship_updates.append(Relationship(a="hero", b="innkeeper", type="AI 관계"))
    pipeline.apply_delta(p, d)
    fs1 = next(f for f in p.foreshadows if f.id == "fs-01-key")
    assert fs1.status == "resolved"
    hidden = list(next(s for s in p.snapshot(1).secrets if s.id == "sec-ally-letter").hidden_from)

    # 2화 반영 뒤 작가가 고친 것
    p.foreshadows.append(Foreshadow(id="fs-author", description="작가 복선", planted_ep=1, due_ep=6))
    fs1.due_ep = 7
    p.facts.append("작가 사실")
    p.relationships.append(Relationship(a="ally", b="innkeeper", type="작가 관계"))
    p.secrets.append(Secret(id="sec-author", owner="ally", content="작가 비밀", hidden_from=["hero"]))
    p.characters.append(Character(id="extra", name="작가인물", role="이웃"))
    pipeline._init_states(p)
    p.state_of("extra").notes = "작가 메모"

    pipeline.revert(p, 1)

    fs = {f.id: f for f in p.foreshadows}
    assert "fs-02-ai" not in fs and "fs-author" in fs and fs["fs-author"].due_ep == 6
    assert fs["fs-01-key"].status == "open" and fs["fs-01-key"].payoff_ep is None and fs["fs-01-key"].due_ep == 7
    assert "2화: AI 사실" not in p.facts and "작가 사실" in p.facts and "1화: 등대는 10년 전 폐쇄되었다" in p.facts
    pairs = {frozenset((r.a, r.b)): r for r in p.relationships}
    assert frozenset(("hero", "innkeeper")) not in pairs
    assert pairs[frozenset(("ally", "innkeeper"))].type == "작가 관계"
    assert pipeline.dynamics.find_tie(p.ties, "ally", "innkeeper") is not None
    sec = {s.id: s for s in p.secrets}
    assert "sec-02-ai" not in sec and "sec-author" in sec
    assert sec["sec-ally-letter"].hidden_from == hidden and hidden  # 2화 사건이 드러낸 비밀은 1화 때로
    assert p.state_of("extra").notes == "작가 메모"
    assert {s.character_id for s in p.states} >= {c.id for c in p.characters}


def test_existing_id_in_new_characters_is_not_kept_and_revert_keeps_it():
    p = _play(_short(8), 1, 1)
    d = _extract(p, 2)
    hero = next(c for c in p.characters if c.id == "hero")
    d.new_characters.append(Character(id="hero", name=hero.name, role="중복"))
    assert any("이미 있는 인물" in w for w in (features.clean(p, d) or d.warnings))
    dropped = pipeline.apply_delta(p, d)
    assert any("이미 있는 인물" in m for m in dropped)
    rec = p.history[-1]
    assert [c.id for c in rec.new_characters] == [] and [c.id for c in rec.dismissed.new_characters] == ["hero"]
    pipeline.revert(p, 1)
    assert any(c.id == "hero" for c in p.characters)


def test_revert_defends_old_history_with_existing_id():
    p = _play(_short(8), 1, 2)
    # 고치기 전 반영이 남긴 기록: 이미 있는 주인공이 2화 새 인물로 적혀 있다
    p.history[-1].new_characters.append(next(c for c in p.characters if c.id == "hero").model_copy())
    p.setting_log.insert(0, p.setting_log[0].model_copy(update={"episode": 1, "source": "author"}))  # 1화 때 작가 기록
    pipeline.revert(p, 1)
    assert any(c.id == "hero" for c in p.characters) and p.state_of("hero") is not None
    assert [(r.episode, r.source) for r in p.setting_log if r.character_id == "hero"] == [(1, "author")]


def test_author_relationship_updated_by_later_delta_survives():
    p = _play(_short(8), 1, 1)
    p.relationships.append(Relationship(a="ally", b="innkeeper", type="작가 관계"))  # 1화 스냅샷 뒤, 2화 반영 전
    p.facts.append("작가 사실")
    d = _extract(p, 2)
    d.relationship_updates.append(Relationship(a="ally", b="innkeeper", type="AI 관계"))
    d.new_facts.append("작가 사실")
    pipeline.apply_delta(p, d)
    assert p.history[-1].added is not None and ["ally", "innkeeper"] not in p.history[-1].added.relationships
    pipeline.revert(p, 1)
    assert any({r.a, r.b} == {"ally", "innkeeper"} for r in p.relationships)
    assert "작가 사실" in p.facts


def test_ai_character_with_low_first_ep_is_still_removed():
    p = _play(_short(8), 1, 1)
    d = _extract(p, 2)
    d.new_characters.append(Character(id="zz", name="새사람", role="행인", first_ep=1))  # AI 가 처음 나온 화를 잘못 적음
    pipeline.apply_delta(p, d)
    pipeline.revert(p, 1)
    assert not any(c.id == "zz" for c in p.characters)


def test_restate_facts_are_removed_by_revert():
    p = _play(_short(8), 1, 2)
    d = p.history[-1].model_copy(deep=True, update={"new_facts": ["고친 2화 사실"], "foreshadow_planted": [], "new_places": []})
    pipeline.apply_restate(p, d)
    assert "고친 2화 사실" in p.history[-1].added.facts
    pipeline.revert(p, 1)
    assert "고친 2화 사실" not in p.facts

"""관계 속도 테스트 (mock LLM): 글 극성, 관계 유형이 반영 뒤 단계와 반대일 때 경고 · 기본 체크 해제, 두 층 감정은 빼기,
결정적 사건 남발, 사람 검토 없이 반영할 때 빼기. 실행: python -m pytest tests"""
from canon import dynamics, features, pace, pipeline, prompts
from canon.schema import CharacterState, Relationship, StateDelta, StoryEvent

from .test_storylines import _short
from .test_timeline import _play


def _set(p, stage: str, warmth: float):
    r = next(r for r in p.relationships if {r.a, r.b} == {"hero", "ally"})
    r.type, r.description = "같은 마을 사람", ""  # mock 의 '동료'(긍정)에서 극성이 새로 바뀌게 중립으로 둔다
    for s, t in (("hero", "ally"), ("ally", "hero")):
        tie = dynamics.get_tie(p.ties, s, t)
        tie.stage, tie.warmth, tie.grievance = stage, warmth, 0.0


def _name(p, cid):
    return next(c.name for c in p.characters if c.id == cid)


def _delta(**kw):
    return StateDelta(episode=2, summary="2화", **kw)


def test_polarity():
    assert pace.polarity("서로의 약점을 아는 틱틱대는 친구") == 1
    assert pace.polarity("협박을 극복한 적대 관계") == -1
    assert pace.polarity("앙숙에서 연인으로") == 0  # 목적지를 적은 글은 판정하지 않는다
    assert pace.polarity("믿지 않는 사이") == -1
    assert pace.polarity("") == 0
    # 유형이 중립이면 설명을 보되, 따옴표 속 대사는 빼고 본다
    assert pace.rel_polarity("거래를 마친 상대", "민정이 먼저 '고마워요'라고 했다") == 0
    assert pace.rel_polarity("거래를 마친 상대", "서로 믿게 되었다") == 1
    assert pace.rel_polarity("협박을 극복한 적대 관계", "‘친구’라고 불렀다") == -1


def test_flag_type_against_stage():
    p = _play(_short(8), 1, 1)
    _set(p, "적대", -0.6)
    d = _delta(relationship_updates=[Relationship(a="hero", b="ally", type="서로 믿는 친구")])
    pipeline.clean_delta(p, d)
    assert d.rel_flagged == [0]
    assert any(w.startswith("관계 유형:") and "적대" in w for w in d.warnings)


def test_no_flag_when_stage_agrees_or_already_same():
    p = _play(_short(8), 1, 1)
    _set(p, "호감", 0.3)
    d = _delta(relationship_updates=[Relationship(a="hero", b="ally", type="친구")])
    pipeline.clean_delta(p, d)
    assert d.rel_flagged == []
    _set(p, "적대", -0.6)
    r = next(r for r in p.relationships if {r.a, r.b} == {"hero", "ally"})
    r.type = "오랜 친구"  # 이미 긍정인 유형을 고쳐 쓴 것은 새로 바뀐 것이 아니다
    d = _delta(relationship_updates=[Relationship(a="hero", b="ally", type="둘도 없는 친구")])
    pipeline.clean_delta(p, d)
    assert d.rel_flagged == []


def test_two_layer_mask_is_not_flagged():
    p = _play(_short(8), 1, 1)
    _set(p, "적대", -0.6)
    ally = _name(p, "ally")
    d = _delta(relationship_updates=[Relationship(a="hero", b="ally", type="친구")],
               character_updates=[CharacterState(character_id="hero", emotional_state=f"겉: {ally}에게 다정하게 웃음 / 속: {ally}를 경계")])
    pipeline.clean_delta(p, d)
    assert d.rel_flagged == []


def test_many_decisive_events_warn():
    p = _play(_short(8), 1, 1)
    evs = [StoryEvent(episode=2, actor="hero", target="ally", kind=k, intensity=3) for k in ("도움", "희생", "진심고백")]
    d = _delta(events=evs)
    assert any("결정적(3) 사건이 3개" in w for w in pace.clean_delta(p, d))
    assert not any("결정적" in w for w in pace.clean_delta(p, _delta(events=evs[:2])))


def test_hold_drops_flagged():
    p = _play(_short(8), 1, 1)
    _set(p, "적대", -0.6)
    d = _delta(relationship_updates=[Relationship(a="hero", b="ally", type="연인")])
    pipeline.clean_delta(p, d)
    held = features.hold(p, d)
    assert d.relationship_updates == [] and d.rel_flagged == [] and held == 0  # 인물 화면에 남기지 않으니 세지 않는다
    assert any("자동 반영에서 뺐어요" in w for w in d.warnings)


def test_state_prompt_rules():
    s = prompts.state_prompt(_short(8), 1)
    assert "3 은 한 쌍에 그 화의 전환점 하나에만" in s and "유형은 이번 화까지 쌓인 사건만큼만" in s


# ---------- 쓰기 전: 화별 플롯 ----------

def _plot(p, n, text):
    e = p.episode(n)
    e.text, e.status = "", "confirmed"
    e.plot.summary, e.plot.events, e.plot.emotional_shift = text, [], ""
    for cid in ("hero", "ally"):
        if cid not in e.plot.characters:
            e.plot.characters.append(cid)


def test_plot_jump_warns():
    p = _play(_short(8), 1, 1)
    _set(p, "적대", -0.6)
    hero, ally = _name(p, "hero"), _name(p, "ally")
    _plot(p, 2, f"{hero}와 {ally}는 서로를 용서하고 친구가 된다.")
    assert pace.plot_shifts(p, 2) == [("ally", "hero", ("호감", "신뢰"))]  # 문장 끝 쪽 '친구가 되' 가 닿는 곳
    w = pace.plot_warnings(p, 2)
    assert len(w) == 1 and "2칸" in w[0] and "적대" in w[0]
    assert [n for n, _ in pace.plan_warnings(p)] == [2]


def test_plot_makeup_is_one_step():
    p = _play(_short(8), 1, 1)
    _set(p, "적대", -0.6)
    _plot(p, 2, f"{_name(p, 'hero')}와 {_name(p, 'ally')}가 마침내 화해한다.")
    assert pace.plot_warnings(p, 2) == []  # 적대 → 화해는 한 칸


def test_earlier_plot_gives_room():
    p = _play(_short(8), 1, 1)
    _set(p, "적대", -0.6)
    hero, ally = _name(p, "hero"), _name(p, "ally")
    _plot(p, 2, f"{hero}는 {ally}와 화해하기 시작한다.")
    _plot(p, 3, f"{hero}와 {ally}는 친구가 된다.")
    assert pace.plot_warnings(p, 3) == []  # 2화가 같은 쪽으로 한 칸 다리를 놓았다


def test_plot_mask_is_skipped():
    p = _play(_short(8), 1, 1)
    _set(p, "적대", -0.6)
    hero, ally = _name(p, "hero"), _name(p, "ally")
    p.state_of("hero").emotional_state = f"겉: {ally}에게 웃음 / 속: {ally}를 경계"
    _plot(p, 2, f"{hero}와 {ally}는 친구가 된다.")
    assert pace.plot_warnings(p, 2) == []


def test_spaced_names():
    assert pace.name_forms("야마이 렌") == ["야마이 렌", "야마이"]
    assert pace.name_forms("최건우") == ["최건우", "건우"]


def test_board_checks_include_plot_pace():
    from canon import board
    from canon.schema import Storyboard
    p = _play(_short(8), 1, 1)
    _set(p, "적대", -0.6)
    _plot(p, 2, f"{_name(p, 'hero')}와 {_name(p, 'ally')}는 친구가 된다.")
    assert any(c.startswith("2화 플롯:") for c in board.checks(p, 2, Storyboard()))


def test_serial_plot_prompt_has_stages_and_rule():
    from .test_serial import _plan_arc, _serial
    p = _serial(40)
    a = _plan_arc(p)
    assert prompts.plan_stage_block(p.model_copy(update={"ties": []}), {c.id for c in p.characters}) == ""  # 관계 수치가 없으면 빈 글
    text = prompts.serial_plot_prompt(p, a.start_ep, a.end_ep)
    assert "[지금 관계 단계 (한 화에 한 칸씩 움직임)]" in text and " → " in text.split("[지금 관계 단계")[1]
    assert "관계 단계(낯섦" in prompts.plot_rules(p) and "관계 단계(낯섦" not in prompts.plot_rules(_short(8))
    assert "[지금 관계 단계" not in prompts.plot_prompt(_short(8), 1, 8)  # 단편 플롯 초안은 그대로

"""자취 거두기(docs/trail 일감 6) 테스트 (mock LLM): 상태 변경안 요청의 블록과 규칙, 정리, 반영, 되돌리기, hold 안 함, mock. 실행: python -m pytest tests"""
from canon import context, features, pipeline, prompts, trails
from canon.schema import CarryOver, CharTrail, DismissedItems, Project, StateDelta, StateDeltaAI, TrailChange, TrailEcho, TrailEchoChange, to_delta

from .test_storylines import _short
from .test_timeline import _play


def _p() -> Project:
    return _play(_short(8), 1, 1)


def _chars(p: Project, *ids: str) -> None:
    for i in ids:
        p.characters.append(p.characters[0].model_copy(update={"id": i, "name": i}))


def _t(tid: str, who: str = "hero", ep: int = 1, wit=(), label: str = "약속", echoes=()) -> CharTrail:
    return CharTrail(id=tid, character=who, episode=ep, label=label, witnesses=list(wit), echoes=list(echoes))


def _tc(who="hero", label="약속", quote="", wit=(), kind="선택") -> TrailChange:
    return TrailChange(character=who, kind=kind, label=label, quote=quote, witnesses=list(wit))


def _ec(trail="tr-001-1", who="ally", meaning="기억", conflict="") -> TrailEchoChange:
    return TrailEchoChange(trail=trail, character=who, meaning=meaning, conflict=conflict)


def _order(block: str) -> list[str]:
    return [line.split()[1] for line in block.splitlines() if line.startswith("- ")]


def test_old_records_read_without_new_fields():
    d = StateDelta.model_validate({"episode": 1, "summary": ""})
    assert d.trails == [] and d.trail_echoes == []
    x = DismissedItems.model_validate({})
    assert x.trails == [] and x.trail_echoes == []


def test_state_prompt_has_rule_always_and_block_only_with_trails():
    p = _p()
    p.trails = []
    s = prompts.state_prompt(p, 2)
    assert "- trails 에는" in s and "\n[앞 화 자취 (" not in s  # 규칙 줄이 '[앞 화 자취]'를 말하므로 블록 머리글로 본다
    p.trails = [_t("tr-001-1", wit=["ally"], echoes=[TrailEcho(episode=1, character="ally", meaning="기억")])]
    s = prompts.state_prompt(p, 2)
    assert "\n[앞 화 자취 (다시 꺼냈으면 trail_echoes 에 이 id 로 적는다)]\n" in s
    assert "- tr-001-1 서윤 · 선택 · 1화 '약속' (본 사람: 도현) · 다시 꺼냄: 1화 '기억'" in s


def test_block_order_decided_then_far_then_near():
    p = _short(12)
    _chars(p, "c3")
    p.episode(12).plot.carry = [CarryOver(character="hero", episode=10, meaning="x")]
    p.trails = [_t("a", ep=11, wit=["ally"]), _t("b", "ally", ep=10), _t("c", ep=2), _t("d", ep=4), _t("e", ep=3)]
    assert _order(trails.state_block(p, None, 12)) == ["b", "e", "c", "a", "d"]  # 4화는 12-4=8 이라 먼 화가 아니다
    p.episode(12).plot.carry = []
    p.trails = [_t("x", ep=5, wit=["ally"]), _t("y", ep=6), _t("z", "c3", ep=9, wit=["hero"])]
    assert _order(trails.state_block(p, {"hero", "ally"}, 12)) == ["x", "y", "z"]  # 함께 > 주인만 > 본 사람만, 최근 화보다 먼저
    assert _order(trails.state_block(p, {"hero"}, 12)) == ["y", "x", "z"]  # x: 주인만(본 사람은 ids 밖) · z: 본 사람만 · 최근 화 차례
    assert trails.state_block(p, {"ghost"}, 12) == ""


def test_decided_zero_ignored_and_current_or_later_excluded():
    p = _short(12)
    p.episode(5).plot.carry = [CarryOver(character="hero", episode=0, meaning="x")]
    p.trails = [_t("t0", ep=0), _t("t1", ep=1), _t("t4", ep=4), _t("t5", ep=5), _t("t6", ep=6)]
    assert _order(trails.state_block(p, None, 5)) == ["t4", "t1", "t0"]
    assert trails.state_block(Project(), None, 3) == ""  # 화 플롯이 없어도 막히지 않는다


def test_block_budget(monkeypatch):
    p = _short(8)
    p.trails = [_t("t1", ep=1), _t("t2", ep=2), _t("t3", ep=3)]
    lines = [x for x in trails.state_block(p, None, 5).splitlines() if x.startswith("- ")]
    monkeypatch.setitem(context.BUDGET, "state_trails", len(lines[0]) + len(lines[1]) + 3)
    out = trails.state_block(p, None, 5)
    assert _order(out) == ["t3", "t2"] and out.endswith("(그 밖 1줄 생략)")


def test_clean_trails():
    p = _p()
    p.trails = []
    _chars(p, "c3", "c4")
    new = p.characters[0].model_copy(update={"id": "newbie", "name": "새사람"})
    p.episode(2).text = "서윤은   등대 앞에\n섰다. 도현이 봤다."
    d = StateDelta(episode=2, summary="", new_characters=[new], trails=[
        _tc("ghost", "유령"), _tc(label="  "),
        _tc(label="가", wit=["hero", "ghost", "ally", "ally", "c3"], quote=" 서윤은 등대 앞에 섰다. "),  # 공백만 다른 구절은 남는다
        _tc(label=" 가 ", wit=["c4"], quote="본문에 없는 말"),  # 같은 (주인, 라벨)은 뒤의 것만
        _tc(label="나", quote="본문에 없는 말"),
        _tc("newbie", "다", wit=["ally"]),
        _tc(label="라"),
    ])
    assert trails.clean_delta(p, d) == []
    assert [(x.character, x.label) for x in d.trails] == [("hero", "가"), ("hero", "나"), ("newbie", "다")]  # 상한 3
    assert d.trails[0].witnesses == ["c4"] and d.trails[0].quote == ""
    d.trails = [_tc(label="가", wit=["hero", "ghost", "ally", "ally", "c3"], quote=" 서윤은 등대 앞에 섰다. ")]
    trails.clean_delta(p, d)
    assert d.trails[0].witnesses == ["ally", "c3"] and d.trails[0].quote == "서윤은 등대 앞에 섰다."
    d.trails = [_tc(label="가", quote="없는 구절")]
    trails.clean_delta(p, d)
    assert d.trails[0].quote == ""


def test_clean_echoes_and_conflict_warning():
    p = _p()
    _chars(p, "c3", "c4")
    p.trails = [_t("tr-001-1", wit=["ally"], label="약속"), _t("tr-001-2", "c3", wit=["ally"], label="말"), _t("tr-002-1", ep=2)]
    d = StateDelta(episode=2, summary="", trail_echoes=[
        _ec("nope"), _ec("tr-002-1"), _ec(who="ghost"), _ec(meaning="  "),
        _ec("tr-001-1", "hero"), _ec("tr-001-1", "c3"), _ec("tr-001-1", "c4", conflict=" 날짜가 달라요 "),
        _ec("tr-001-2", "hero"), _ec("tr-001-2", "ally"), _ec("tr-001-1", "ally", "첫째"), _ec("tr-001-1", "ally", " 둘째 "),
    ])
    warns = trails.clean_delta(p, d)
    kept = [(x.trail, x.character, x.meaning) for x in d.trail_echoes]
    assert kept == [("tr-001-2", "ally", "기억"), ("tr-001-1", "ally", "둘째"), ("tr-001-1", "c3", "기억"), ("tr-001-1", "c4", "기억")]  # 주인 줄이 먼저 빠짐
    assert warns == [("'약속' 다시 꺼냄이 앞 화와 달라요: 날짜가 달라요", "c4")]
    d.trail_echoes = [_ec("tr-001-1", "ally", conflict="다르다")]
    d.warnings, d.warn_to = ["앞 경고"], ["hero"]
    features.clean(p, d)
    assert d.warnings[-1] == "'약속' 다시 꺼냄이 앞 화와 달라요: 다르다" and d.warn_to[-1] == "ally" and len(d.warn_to) == len(d.warnings)


def test_apply_delta():
    p = _p()
    p.trails = [_t("tr-001-1", wit=["ally"])]
    d = StateDelta(episode=2, summary="", trails=[_tc(label="하나", wit=["ally", "ghost", "hero"]), _tc("ghost", "건너뜀"), _tc(label="둘")],
                   trail_echoes=[_ec(who="ally", meaning="첫째"), _ec(who="ally", meaning="둘째"), _ec(who="ghost"), _ec("nope")])
    trails.apply_delta(p, d)
    assert [(t.id, t.episode, t.witnesses) for t in p.trails] == [("tr-001-1", 1, ["ally"]), ("tr-002-1", 2, ["ally"]), ("tr-002-2", 2, [])]
    assert [(e.episode, e.character, e.meaning) for e in p.trails[0].echoes] == [(2, "ally", "둘째")]


def test_pipeline_apply_and_revert():
    p = _p()
    assert [t.id for t in p.trails] == ["tr-001-1"]
    d = StateDelta(episode=2, summary="", trails=[_tc(label="이튿날")], trail_echoes=[_ec(who="ally")])
    pipeline.apply_delta(p, d)
    assert [t.id for t in p.trails] == ["tr-001-1", "tr-002-1"] and [e.episode for e in p.trails[0].echoes] == [2]
    pipeline.revert(p, 1)
    assert [t.id for t in p.trails] == ["tr-001-1"] and p.trails[0].echoes == []


def test_hold_keeps_trails():
    p = _p()
    d = StateDelta(episode=2, summary="", trails=[_tc()], trail_echoes=[_ec()])
    features.hold(p, d)
    assert len(d.trails) == 1 and len(d.trail_echoes) == 1


def test_mock_collects_one_trail_and_its_echo():
    p = _play(_short(8), 1, 2)
    assert [(t.id, t.character, t.witnesses) for t in p.trails] == [("tr-001-1", "hero", ["ally"])]
    assert [(e.episode, e.character) for e in p.trails[0].echoes] == [(2, "ally")]


def test_to_delta_keeps_both_lists():
    raw = StateDeltaAI(episode=1, summary="", trails=[_tc()], trail_echoes=[_ec()])
    d = to_delta(raw, 3)
    assert d.trails == [_tc()] and d.trail_echoes == [_ec()]


def test_write_and_check_requests_have_no_trail_block():
    p = _p()
    p.trails = [_t("tr-001-1", wit=["ally"])]
    assert "[앞 화 자취" not in prompts.episode_prompt(p, 2) and "[앞 화 자취" not in prompts.check_prompt(p, 2)

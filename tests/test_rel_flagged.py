"""StateDelta.rel_flagged (기본으로 체크하지 않는 relationship_updates 차례)가 행을 뺀 뒤에도 같은 행을 가리키는지:
drop_invalid · pace.hold 가 차례를 다시 매기고, 반영 기록은 범위 안의 차례만 남기고, 반영 취소로 다시 놓인 변경안이 맞는 행을 가리킨다.
실행: python -m pytest tests"""
from canon import features, pipeline, web
from canon.schema import Relationship, StateDelta

from .test_storylines import _short
from .test_timeline import LLM, _play


def _rows():
    return [Relationship(a="hero", b="ghost", type="원수"), Relationship(a="hero", b="ally", type="동료"),
            Relationship(a="ally", b="hero", type="연인")]


def test_drop_invalid_remaps_rel_flagged():
    p = _short(8)
    d = StateDelta(episode=1, summary="", rel_flagged=[2], relationship_updates=_rows())
    pipeline.drop_invalid(p, d)  # 0번(설정에 없는 인물)을 뺀다
    assert [r.type for r in d.relationship_updates] == ["동료", "연인"]
    assert d.rel_flagged == [1]  # 같은 행('연인')을 가리킨다
    d = StateDelta(episode=1, summary="", rel_flagged=[0, 2], relationship_updates=_rows())
    pipeline.drop_invalid(p, d)
    assert d.rel_flagged == [1]  # 뺀 행의 차례는 버린다


def test_hold_ignores_out_of_range_flag():
    p = _short(8)
    d = StateDelta(episode=1, summary="", rel_flagged=[1, 7], relationship_updates=_rows()[1:])
    features.hold(p, d)
    assert [r.type for r in d.relationship_updates] == ["동료"] and d.rel_flagged == []
    assert [r.type for r in d.dismissed.relationship_updates] == ["연인"]


def test_history_keeps_only_valid_rel_flagged():
    p = _play(_short(8), 1, 2)
    pipeline.confirm_plot(p, 3)
    p.episode(3).text, p.episode(3).status = pipeline.write_episode(LLM, p, 3), "written"
    d = StateDelta(episode=3, summary="3화", rel_flagged=[2, 2, 0, 9], relationship_updates=_rows())
    pipeline.apply_delta(p, d)  # 다른 클라이언트가 보낸 차례도 기록에는 남은 행의 차례로만 둔다
    rec = p.history[-1]
    assert [r.type for r in rec.relationship_updates] == ["동료", "연인"] and rec.rel_flagged == [1]


def test_auto_apply_then_revert_reoffers_right_rows():
    p = _play(_short(8), 1, 2)
    pipeline.confirm_plot(p, 3)
    p.episode(3).text, p.episode(3).status = pipeline.write_episode(LLM, p, 3), "written"
    d = StateDelta(episode=3, summary="3화", rel_flagged=[2], relationship_updates=_rows())
    features.hold(p, d)  # 자동 집필 put 과 같은 차례
    pipeline.apply_delta(p, d)
    res = StateDelta.model_validate(web._revert_kept(p, 2)["state:3"]["result"])
    assert [r.type for r in res.relationship_updates] == ["동료"]
    assert all(i < len(res.relationship_updates) for i in res.rel_flagged)
    assert sorted(r.type for r in res.dismissed.relationship_updates) == ["연인", "원수"]  # 다시 놓일 때 체크를 푼 채

"""화 끼워 넣기 · 빼기가 완급 계획(heat)의 화 번호도 옮기는지 (pipeline.insert_episode · remove_episode, renumber.move_points)."""
from canon import heatplan, pipeline
from canon.schema import HeatStep, HeatTurn

from .test_insert import _short
from .test_serial import _finish, _plan_arc, _serial


def _plan(start: int, end: int) -> list[HeatStep]:
    """화마다 눈금이 다른 계획. 눈금 = 화 번호 % 6 이라 옮긴 뒤 어느 줄이 어디로 갔는지 보인다."""
    return [HeatStep(ep=n, level=n % 6, role="peak" if n % 6 == 5 else "build", note=f"원래 {n}화") for n in range(start, end + 1)]


def _notes(steps: list[HeatStep]) -> dict[int, str]:
    return {s.ep: s.note for s in steps}


def test_short_insert_moves_heat_and_fills_new_episode():
    p = _short()
    p.heat, p.heat_rule, p.heat_turn = _plan(1, 12), "아낀다", HeatTurn(plant_ep=7, fail_ep=9, gain="사진")
    notes = pipeline.insert_episode(p, 6, "외전")
    assert [s.ep for s in p.heat] == list(range(1, 14))
    got = _notes(p.heat)
    assert got[5] == "원래 5화" and got[7] == "원래 6화" and got[13] == "원래 12화"
    assert (got[6], p.heat[5].level, p.heat[5].role) == ("", heatplan.FILL_LEVEL, heatplan.FILL_ROLE)  # 새 화는 채운 줄
    assert (p.heat_turn.plant_ep, p.heat_turn.fail_ep, p.heat_turn.gain) == (8, 10, "사진")
    assert p.heat_rule == "아낀다"
    assert any("완급 계획 줄" in x for x in notes)


def test_short_remove_drops_gone_step_and_pulls_back():
    p = _short()
    p.heat, p.heat_turn = _plan(1, 12), HeatTurn(plant_ep=6, fail_ep=9, gain="사진")
    pipeline.remove_episode(p, 6)
    assert [s.ep for s in p.heat] == list(range(1, 12))
    got = _notes(p.heat)
    assert got[5] == "원래 5화" and got[6] == "원래 7화" and got[11] == "원래 12화"
    assert (p.heat_turn.plant_ep, p.heat_turn.fail_ep) == (6, 8)  # 뺀 화에 심은 반격은 그 자리에 온 다음 화
    assert heatplan.turn(p) is not None


def test_short_insert_then_remove_round_trips_heat():
    p = _short()
    p.heat, p.heat_turn = _plan(1, 12), HeatTurn(plant_ep=7, fail_ep=9, gain="사진")
    before = p.model_dump()
    pipeline.insert_episode(p, 8, "끼운 화")
    pipeline.remove_episode(p, 8)
    assert p.model_dump() == before


def test_serial_insert_and_remove_move_arc_heat():
    p = _serial(300)
    a1 = _plan_arc(p)
    _finish(p, a1)
    a2 = _plan_arc(p)
    s, e = a2.start_ep, a2.end_ep
    a2.heat, a2.heat_turn = _plan(s, e), HeatTurn(plant_ep=s + 1, fail_ep=s + 2, gain="칼")
    a1.heat = _plan(a1.start_ep, a1.end_ep)
    first = [x.model_copy() for x in a1.heat]
    pipeline.insert_episode(p, s + 1, "외전")
    a1, a2 = p.story_arcs[0], p.story_arcs[1]
    assert a1.heat == first  # 쓴 앞 아크의 계획은 그대로
    assert [x.ep for x in a2.heat] == list(range(s, e + 2))
    got = _notes(a2.heat)
    assert got[s] == f"원래 {s}화" and got[s + 1] == "" and got[s + 2] == f"원래 {s + 1}화" and got[e + 1] == f"원래 {e}화"
    assert (a2.heat_turn.plant_ep, a2.heat_turn.fail_ep) == (s + 2, s + 3)
    assert heatplan.step(p, e + 1).note == f"원래 {e}화"
    pipeline.remove_episode(p, s + 1)
    a2 = p.story_arcs[1]
    assert [x.ep for x in a2.heat] == list(range(s, e + 1)) and _notes(a2.heat) == _notes(_plan(s, e))
    assert (a2.heat_turn.plant_ep, a2.heat_turn.fail_ep) == (s + 1, s + 2)

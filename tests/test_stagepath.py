"""박자 사이 이동 경로 (canon/stagepath.py, docs/stage/specs/10-path.md)."""
import math
import re

import pytest
from shapely.geometry import LineString, box

from canon import stage, stagepath
from canon.schema import Character, Project, StageAnchor, StageBeat, StageBody, StageScene, StageSpot
from canon.stage3d import frames

from .jsvm import STATIC, episode, needs_node, run_js


def _a(room, name):
    return next(a.id for a in room.anchors if a.name == name)


def _body(room, ref, rel, posture="walk", who="d"):
    return StageBody(who=who, at=StageSpot(ref=_a(room, ref), rel=rel), posture=posture)


def _scene(room, start, *beats):
    return StageScene(id="s1", room=room.id, cast=["d"], start=[start], beats=[StageBeat(bodies=[b]) for b in beats])


def _clear_of(via, room, skip=()):
    """꺾은선이 뺀 기준점 말고 다른 단단한 가구 바닥을 지나지 않는다."""
    from canon.stage3d import furniture
    line = LineString(via)
    for s in furniture.solids(room):
        x0, y0, z0, x1, y1, z1 = s.box
        if s.solid and z0 < stagepath.HEAD and s.anchor not in skip and x1 > x0 and y1 > y0:
            assert not line.crosses(box(x0, y0, x1, y1)) and not line.within(box(x0, y0, x1, y1)), s.anchor


def test_detour_around_desk():
    room = stage.make_room("office", "r1")
    sc = _scene(room, _body(room, "손님 의자", "on", "chair"), _body(room, "의자", "on", "chair"), _body(room, "문", "front"))
    got = stagepath.paths(sc, room)
    assert got[0] == {}
    via = got[1]["d"]["via"]
    assert len(via) > 2 and not got[1]["d"]["blocked"]
    spots = stage.layouts(room, sc)
    assert via[0] == pytest.approx(list(spots[0]["d"]), abs=1e-3) and via[-1] == pytest.approx(list(spots[1]["d"]), abs=1e-3)
    _clear_of(via, room, skip={_a(room, "손님 의자"), _a(room, "의자")})
    # 돌아가는 길은 곧은 길보다 길고, 방 안(몸 반지름 안쪽)에 있다
    assert sum(math.dist(p, q) for p, q in zip(via, via[1:])) > math.dist(via[0], via[-1])
    assert all(stage.BODY - 1e-3 <= x <= room.w - stage.BODY + 1e-3 and stage.BODY - 1e-3 <= y <= room.h - stage.BODY + 1e-3 for x, y in via)


def test_straight_moves_are_not_listed():
    room = stage.make_room("empty", "r1")
    sc = _scene(room, StageBody(who="d", at=StageSpot(ref=_a(room, "문"), rel="front"), posture="stand"),
                StageBody(who="d", at=StageSpot(ref=_a(room, "문"), rel="left"), posture="walk"))
    assert stagepath.paths(sc, room) == [{}, {}]


def test_own_seat_is_not_an_obstacle():
    # 의자에서 일어나 걷는 이동: 떠나는 의자는 장애물이 아니다 (경로가 의자 안에서 시작한다)
    room = stage.make_room("office", "r1")
    sc = _scene(room, _body(room, "의자", "on", "chair"), _body(room, "의자", "back"))
    row = stagepath.paths(sc, room)[1]
    assert not row.get("d", {}).get("blocked")


def test_boarding_a_car_skips_the_car():
    room = stage.make_room("car_side", "r1")
    sc = _scene(room, StageBody(who="d", at=StageSpot(ref=_a(room, "운전석 문"), rel="front"), posture="stand"),
                _body(room, "운전석", "on", "chair"))
    row = stagepath.paths(sc, room)[1]
    assert "d" not in row or not row["d"]["blocked"]


def test_boxed_in_is_blocked():
    walls = [StageAnchor(id=f"w{i}", name=f"벽{i}", kind="other", x=x, y=y, w=w, h=h) for i, (x, y, w, h) in
             enumerate([(1.5, 1.0, 2.0, 0.2), (1.5, 2.8, 2.0, 0.2), (1.5, 1.2, 0.2, 1.6), (3.3, 1.2, 0.2, 1.6)])]
    room = stage.make_room("empty", "r1").model_copy(update={"w": 6.0, "h": 4.0})
    room = room.model_copy(update={"anchors": room.anchors + walls})
    # 갇힌 칸 가운데(빈 기준점 자리)에서 문 앞으로
    spot = StageAnchor(id="mid", name="가운데", kind="ground", x=2.3, y=1.8, w=0.4, h=0.4)
    room = room.model_copy(update={"anchors": room.anchors + [spot]})
    sc = StageScene(id="s1", room=room.id, cast=["d"], start=[StageBody(who="d", at=StageSpot(ref="mid", rel="on"), posture="stand")],
                    beats=[StageBeat(bodies=[StageBody(who="d", at=StageSpot(ref=_a(room, "문"), rel="front"), posture="walk")])])
    row = stagepath.paths(sc, room)[1]
    assert row["d"]["blocked"] and len(row["d"]["via"]) == 2


def test_check_and_frames_carry_paths():
    room = stage.make_room("office", "r1")
    p = Project(characters=[Character(id="d", name="도윤", role="조연", age="29")], rooms=[room])
    sc = _scene(room, _body(room, "손님 의자", "on", "chair"), _body(room, "의자", "on", "chair"))
    ck = stage.check(p, episode(1), sc, room)
    assert ck["paths"][1]["d"]["via"] == stagepath.paths(sc, room)[1]["d"]["via"]
    out = frames(sc, room).to_dict()
    assert out["beats"][0]["paths"] == {} and out["beats"][1]["paths"]["d"]["via"] == ck["paths"][1]["d"]["via"]


@needs_node
def test_js_path_for_and_path_at():
    files = re.findall(r'src="/static/([a-z0-9-]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))
    paths = [{}, {"d": {"via": [[0, 0], [0, 2], [2, 2]], "blocked": False}}]
    got = run_js(files, """[
      stagePathFor(data.paths, 1, 'd', [0, 0], [2, 2]),
      stagePathFor(data.paths, 0, 'd', [2, 2], [0, 0]),
      stagePathFor(data.paths, 1, 'd', [0, 0.5], [2, 2]),
      stagePathFor(data.paths, 1, 'x', [0, 0], [2, 2]),
      stagePathAt([[0, 0], [0, 2], [2, 2]], 0.25), stagePathAt([[0, 0], [0, 2], [2, 2]], 0.75),
      stagePathAt([[0, 0], [0, 2], [2, 2]], 0), stagePathAt([[0, 0], [0, 2], [2, 2]], 1),
    ]""", {"paths": paths})
    assert got[0] == [[0, 0], [0, 2], [2, 2]]
    assert got[1] == [[2, 2], [0, 2], [0, 0]]  # 뒤로 넘길 때는 다음 박자 경로를 거꾸로
    assert got[2] is None and got[3] is None   # 끝점이 다르거나(고친 뒤 판정 전) 경로가 없으면 곧게
    assert got[4] == pytest.approx([0, 1]) and got[5] == pytest.approx([1, 2])
    assert got[6] == pytest.approx([0, 0]) and got[7] == pytest.approx([2, 2])

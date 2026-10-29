"""시험용 가짜 자세 · 장소. 등록부(postures/ · rooms/)가 읽지 않는다.

각도는 시안(docs/stage/mockup-3d.html 의 POSE) 첫 값이다. 실제 자세 · 장소 모듈이 생겨도 이 값은 시험용으로 그대로 둔다.
쓰는 법: frames(scene, room, postures=fake.POSTURES, rooms=fake.ROOMS), 또는 monkeypatch 로 postures.load · rooms.load 를 바꾼다.
"""
from __future__ import annotations

from .. import stage
from .body import Angles, PostureSpec, Reach
from .furniture import KINDS, Box, Furniture, RoomSpec

POSTURES = {
    "stand": PostureSpec("stand", Angles(0.92, abduct=(8, 8), elbow=(10, 10)), ("floor", "top")),
    "chair": PostureSpec("chair", Angles(0.08, spine=6, shoulder=(22, 22), abduct=(6, 6), elbow=(60, 60), hip=(90, 90), knee=(90, 90),
                                         shift=-0.13), ("seat",), Reach(lean=30, twist=45), feet_to_floor=True),
    "lie": PostureSpec("lie", Angles(0.12, pitch=-90, abduct=(14, 14), elbow=(10, 10), knee=(8, 8)), ("lie", "floor"), Reach(lean=0, twist=0)),
    "squat": PostureSpec("squat", Angles(0.42, spine=30, shoulder=(45, 45), abduct=(6, 6), elbow=(60, 60), hip=(120, 120), knee=(140, 140)),
                         ("floor", "top")),
}

# 모든 틀: 천장 2.4, 기준점은 종류 기본값. 차 뒷좌석은 눕기 참이라 눕는 면을 더한다
_BENCH = Furniture(KINDS["seat"].boxes, seat=0.45, lie=0.45)
ROOMS = {t: RoomSpec(t, anchors={"뒷좌석": _BENCH} if t == "car" else {}) for t in stage.ROOMS}


def box_room(ceiling: float = 2.4, template: str = "empty") -> RoomSpec:
    """상자 하나 방 시험용: 천장만 바꾼 틀."""
    return RoomSpec(template, ceiling)


BLOCK = Furniture((Box(0, 1, 0, 1, 0, 1.0),))  # 높이 1m 통상자: 기준점 이름으로 덮어쓸 때

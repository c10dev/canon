"""장면 연출 3D: 높이와 몸 부피로 평면 판정이 못 보는 어긋남을 찾는 계산 (docs/stage/3d/).

body.py 마네킹 계약 · frames, furniture.py 가구 모양, postures/<자세 id>.py · rooms/<틀 id>.py 는 모듈이 스스로 등록한다.
fake.py 는 시험용 가짜 자세 · 장소다 (등록부가 읽지 않는다). LLM 호출 없음.
"""
from __future__ import annotations

from .. import stage
from . import postures as _postures, rooms as _rooms
from .body import (ACT3D, ARM, HEIGHT, JOINTS, PART_POINTS, PART_SEGMENT, SEGMENTS, SURFACES, Angles, Body, Capsule, Contact,
                   BeatFrame, Frames, L, Person, PlaceCtx, Placement, PostureSpec, Reach, capsules, frames, look_at, part_point,
                   penetration, pose, reach_to)
from .furniture import KINDS, Box, Furniture, RoomSpec, Solid, solids, surface


def posture_specs() -> dict[str, PostureSpec]:
    """등록된 자세: id → PostureSpec."""
    return _postures.load()


def room_specs() -> dict[str, RoomSpec]:
    """등록된 장소: 틀 id → RoomSpec."""
    return _rooms.load()


def missing() -> dict[str, list[str]]:
    """아직 모듈이 없는 자세 · 틀 (stage 순서)."""
    ps, rs = posture_specs(), room_specs()
    return {"postures": [k for k in stage.POSTURES if k not in ps], "rooms": [k for k in stage.ROOMS if k not in rs]}


def complete() -> bool:
    """자세 12개 · 틀 7개가 다 등록됐나. 다 있을 때만 3D 판정을 켠다 (docs/stage/3d/README.md 정할 것 10)."""
    m = missing()
    return not m["postures"] and not m["rooms"]

"""장면 연출 3D: 가구 모양. 기준점 자리(평면 x · y · w · h · rot)는 StageRoom 의 것을 쓰고 여기서는 높이와 모양만 더한다.

장소 모듈(rooms/<틀>.py)이 RoomSpec 을 내고, 없는 기준점은 종류 기본값 KINDS 로 떨어진다. 설계는 docs/stage/3d/specs/01-body.md.
좌표: 평면도 x(오른쪽) · y(아래쪽)에 높이 z(위)를 더한다. 단위 m. LLM 호출 없음.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .. import stage
from ..schema import StageAnchor, StageRoom


@dataclass(frozen=True)
class Box:
    """기준점 자리 안의 상자. u · v 는 기준점 폭 · 깊이의 비율(0~1), z 는 m.
    v 는 기준점 앞쪽(rot)으로 0 → 1, u 는 앞에서 바라본 왼쪽 → 오른쪽으로 0 → 1."""
    u0: float
    u1: float
    v0: float
    v1: float
    z0: float
    z1: float
    solid: bool = True  # False 면 판정이 겹침을 보지 않는다
    barrier: bool = False  # 차체 옆면처럼 두 사람을 가르는 막: 두 사람 사이를 막으면 몸 겹침을 보지 않고, 손이 이 상자를 지나 닿지 못한다


@dataclass(frozen=True)
class Furniture:
    boxes: tuple[Box, ...]
    seat: Optional[float] = None  # 앉는 면 높이 (sit 참일 때)
    lie: Optional[float] = None   # 눕는 면 높이 (lie 참일 때)
    head: str = "back"            # 누울 때 머리 쪽: back(앞의 반대) · left · right


@dataclass(frozen=True)
class RoomSpec:
    template: str                 # stage.ROOMS 의 키
    ceiling: float = 2.4          # 천장 높이 m
    anchors: dict[str, Furniture] = field(default_factory=dict)  # 틀의 기준점 이름 → 모양
    open: bool = False            # 야외: 벽 · 천장이 없다 (판정이 벽 · headroom 을 보지 않고, 그림은 낮은 테두리만). ceiling 은 그림 높이


@dataclass(frozen=True)
class Solid:
    """세계 좌표의 축 맞춤 상자 하나. rot 은 90° 단위라 축 맞춤으로 충분하다."""
    anchor: str                                        # 기준점 id
    box: tuple[float, float, float, float, float, float]  # x0, y0, z0, x1, y1, z1
    solid: bool = True
    barrier: bool = False


KINDS = {
    "bed": Furniture((Box(0, 1, 0, 1, 0, 0.5), Box(0, 1, 0, 0.05, 0, 0.9)), seat=0.5, lie=0.5),
    "chair": Furniture((Box(0, 1, 0, 1, 0.40, 0.45), Box(0, 1, 0, 0.1, 0.45, 0.9)), seat=0.45),
    "sofa": Furniture((Box(0, 1, 0, 1, 0, 0.42), Box(0, 1, 0, 0.25, 0, 0.8), Box(0, 0.1, 0, 1, 0, 0.6), Box(0.9, 1, 0, 1, 0, 0.6)),
                      seat=0.42, lie=0.42, head="left"),  # 가로로 긴 소파: 앞에서 본 왼쪽 팔걸이 쪽에 머리
    "seat": Furniture((Box(0, 1, 0, 1, 0, 0.45), Box(0, 1, 0, 0.15, 0, 0.9)), seat=0.45),
    "desk": Furniture((Box(0, 1, 0, 1, 0.72, 0.75),)),
    "table": Furniture((Box(0, 1, 0, 1, 0.69, 0.72),)),
    "door": Furniture((Box(0, 1, 0, 1, 0, 2.1, solid=False),)),
    "window": Furniture((Box(0, 1, 0, 1, 0.9, 2.0, solid=False),)),  # 벽은 방 테두리가 맡는다
    "wall": Furniture((Box(0, 1, 0, 1, 0, 2.4),)),
    "vehicle": Furniture((Box(0, 1, 0, 1, 0.3, 2.0, barrier=True),)),  # 차 몸체: 뚫고 지나가지 못하는 덩어리 (바닥 틈 0.3m)
    "landmark": Furniture((Box(0, 1, 0, 1, 0, 1.0),)),                  # 나무 · 바위 · 표지판 같은 야외 표지
    "ground": Furniture((Box(0, 1, 0, 1, 0, 0.02, solid=False),)),       # 길 · 땅: 그 위를 걷는다
    "other": Furniture((Box(0, 1, 0, 1, 0, 0.8),)),
}


def lookup(anchor: StageAnchor, spec: Optional[RoomSpec]) -> Furniture:
    """기준점 모양: 장소 모듈의 이름 → 종류 기본값 → other."""
    if spec and anchor.name in spec.anchors:
        return spec.anchors[anchor.name]
    return KINDS.get(anchor.kind) or KINDS["other"]


def world_box(anchor: StageAnchor, b: Box) -> tuple[float, float, float, float, float, float]:
    """u · v 상자 → 세계 좌표 상자."""
    fx, fy = stage._front(anchor.rot)
    cx, cy = anchor.x + anchor.w / 2, anchor.y + anchor.h / 2
    depth = abs(fx) * anchor.w + abs(fy) * anchor.h
    width = abs(fy) * anchor.w + abs(fx) * anchor.h
    rx, ry = fy, -fx  # 앞에서 바라본 오른쪽 (stage._anchor_point 와 같음)

    def at(u: float, v: float) -> tuple[float, float]:
        return (cx + (v - 0.5) * depth * fx + (u - 0.5) * width * rx,
                cy + (v - 0.5) * depth * fy + (u - 0.5) * width * ry)

    (ax, ay), (bx, by) = at(b.u0, b.v0), at(b.u1, b.v1)
    return (min(ax, bx), min(ay, by), b.z0, max(ax, bx), max(ay, by), b.z1)


def solids(room: StageRoom, spec: Optional[RoomSpec] = None) -> list[Solid]:
    """방의 모든 가구 상자 (기준점 순, 상자 순)."""
    return [Solid(a.id, world_box(a, b), b.solid, b.barrier) for a in room.anchors for b in lookup(a, spec).boxes]


def top(f: Furniture) -> float:
    """윗면 높이: 눕는 면 · 앉는 면이 있으면 그것, 없으면 단단한 상자의 가장 높은 곳."""
    if f.lie is not None:
        return f.lie
    if f.seat is not None:
        return f.seat
    return max((b.z1 for b in f.boxes if b.solid), default=0.0)


def surface(anchor: StageAnchor, spec: Optional[RoomSpec], what: str) -> Optional[float]:
    """기준점의 면 높이. what: seat(sit 참일 때) · lie(lie 참일 때) · top(윗면). 그 면이 없으면 None."""
    f = lookup(anchor, spec)
    if what == "seat":
        return (f.seat if f.seat is not None else top(f)) if anchor.sit else None
    if what == "lie":
        return (f.lie if f.lie is not None else top(f)) if anchor.lie else None
    if what == "top":
        return top(f)
    return None

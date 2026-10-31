"""의자에 앉기 (docs/stage/3d/specs/postures/chair.md). 침대 가장자리 · 소파 · 차 좌석도 이 자세다.

골반은 앉는 면 위 0.08m, 엉덩이는 등받이 쪽으로 0.13m(shift). 앉는 면이 0.45m 와 다르면 무릎을 고쳐 발을 바닥에 댄다.
엉덩 · 무릎은 시안 90° 에서 87° 로 고쳤다: 90° 면 0.45m 의자에서 발목이 바닥 위 5cm 에 뜬다(마네킹 정강이 0.46m).
87° 면 발목이 2.7cm, 넓적다리가 앉는 면을 2.5cm 파고든다(명세 한도 3cm).
"""
from __future__ import annotations

import math

from ... import stage
from .. import furniture
from ..body import Angles, PlaceCtx, Placement, PostureSpec, Reach

SEAT = 0.45  # 앉는 면이 없을 때 둘 높이 (furniture.KINDS 의 chair)

ANGLES = Angles(0.08, spine=6, shoulder=(22, 22), abduct=(6, 6), elbow=(60, 60), hip=(87, 87), knee=(87, 87), shift=-0.13)


def place(ctx: PlaceCtx) -> Placement:
    """몸은 향함을 따른다. 기준점 앞쪽과 90° 넘게 다르면 등받이에 등이 닿지 않으므로 shift 를 없앤다(옆으로 걸터앉기).
    앉는 면이 없으면 판정 no_support 가 짚고, 그림은 기준점 위(앉기 거짓인 책상)면 그 윗면, 기준점 밖이면 0.45m 에 둔다."""
    x, y = ctx.xy
    base = ctx.base
    at = ctx.now.at
    a = next((a for a in ctx.room.anchors if at and a.id == at.ref), None)
    on = a is not None and at.rel in ("on", "in")
    if base <= 0:
        base = (furniture.surface(a, ctx.spec, "top") if on else None) or SEAT
    if on:
        fx, fy = stage._front(a.rot)
        if math.sin(ctx.yaw) * fx + math.cos(ctx.yaw) * fy < -1e-6:
            x -= math.sin(ctx.yaw) * ANGLES.shift
            y -= math.cos(ctx.yaw) * ANGLES.shift
    return Placement(x, y, ctx.yaw, base)


POSTURE = PostureSpec(id="chair", angles=ANGLES, surface=("seat",), reach=Reach(lean=30, twist=40), feet_to_floor=True,
                      place_hook=place)

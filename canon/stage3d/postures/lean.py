"""자세 모듈: 기대 서기 (lean). 명세는 docs/stage/3d/specs/postures/lean.md.

각도는 시안(POSE.lean) 값 그대로다: 몸을 뒤로 10° 기울이고 오른발을 굽혀 벽 쪽으로 올린다.
특수 배치(place_hook): 등을 벽 · 기준점에 대고 등이 그 면에서 GAP 떨어지게 옮긴다.
- 자리가 기준점 against 이면 그 기준점의 상자 면을 쓴다(문처럼 solid 가 아닌 상자도).
- 아니면 등 뒤 SEARCH 안의 방 벽 · 단단한 가구 면을 찾는다.
- 향함이 면 반대쪽 ±90° 밖이면(벽을 보고 선다) 그 면을 쓰지 않는다. 그때와 면을 못 찾았을 때는 그 자리에 두고 판정(no_support)이 짚는다.
면을 쓰면 몸은 면을 등지고, 고개는 frames 가 향함 대상으로 돌린다.
"""
from __future__ import annotations

import math
from typing import Optional

from ... import stage
from ..body import Angles, Placement, PlaceCtx, PostureSpec, Reach, pose

ANGLES = Angles(pelvis_h=0.90, pitch=-10, spine=2, shoulder=(-8, -8), abduct=(6, 6), elbow=(15, 15), hip=(0, 30), knee=(0, 75))
GAP = 0.03      # 등 → 기댄 면 (m)
SEARCH = 0.35   # 기준점이 아닐 때 등 뒤에서 면을 찾는 거리 (m)
REACH_Z = 0.7   # 이보다 낮은 가구는 기댈 면이 아니다 (m, 책상 판 0.72 는 엉덩이를 댄다)
_UPPER = ("head", "torso", "pelvis", "upper_arm_l", "upper_arm_r")


def _back_depth() -> float:
    """골반 자리에서 몸 뒤 끝(윗몸 캡슐 겉)까지 거리. yaw 0 이면 앞이 +y 다."""
    caps = [c for c in pose(ANGLES, 0.0, 0.0).capsules() if c.segment in _UPPER]
    return max(max(-c.a[1], -c.b[1]) + c.r for c in caps)


BACK = _back_depth()

Face = tuple[tuple[float, float], float]  # (면 밖으로 향한 단위 법선, xy 에서 면까지 거리)


def _rect_faces(xy: tuple[float, float], x0: float, y0: float, x1: float, y1: float, inside: bool) -> list[Face]:
    """직사각형 네 변 가운데 xy 쪽을 향한 면. inside 면 방 벽(안쪽을 향함), 아니면 가구(바깥을 향함).
    xy 가 그 변의 범위(양끝 0.1m 여유) 앞에 있을 때만 면으로 친다."""
    x, y = xy
    if inside:
        sides = [((1.0, 0.0), x - x0, y, y0, y1), ((-1.0, 0.0), x1 - x, y, y0, y1),
                 ((0.0, 1.0), y - y0, x, x0, x1), ((0.0, -1.0), y1 - y, x, x0, x1)]
    else:
        sides = [((-1.0, 0.0), x0 - x, y, y0, y1), ((1.0, 0.0), x - x1, y, y0, y1),
                 ((0.0, -1.0), y0 - y, x, x0, x1), ((0.0, 1.0), y - y1, x, x0, x1)]
    return [(n, d) for n, d, along, lo, hi in sides if d >= -1e-9 and lo - 0.1 <= along <= hi + 0.1]


def _faces(ctx: PlaceCtx) -> tuple[list[Face], bool]:
    """기댈 수 있는 면 후보와, 기준점 against 인지."""
    at = ctx.now.at
    if at and at.rel == "against" and not at.ref.startswith("@"):
        boxes = [s.box for s in ctx.solids if s.anchor == at.ref]
        return [f for b in boxes for f in _rect_faces(ctx.xy, b[0], b[1], b[3], b[4], inside=False)], True
    faces = _rect_faces(ctx.xy, 0.0, 0.0, ctx.room.w, ctx.room.h, inside=True)
    for s in ctx.solids:
        b = s.box
        if s.solid and b[5] >= REACH_Z:
            faces += _rect_faces(ctx.xy, b[0], b[1], b[3], b[4], inside=False)
    return [f for f in faces if f[1] - BACK <= SEARCH], False


def _faces_ok(n: tuple[float, float], ctx: PlaceCtx) -> bool:
    """향함이 면 반대쪽(법선) ±90° 안인가. 향함을 모르면 맞다고 본다."""
    v = stage.facing_vec(ctx.now.facing, ctx.xy, ctx.room, ctx.pos)
    return v is None or v[0] * n[0] + v[1] * n[1] >= -1e-9


def find_back(ctx: PlaceCtx) -> Optional[Face]:
    """등을 댈 면 (법선, 거리). 못 찾으면 None."""
    faces, _ = _faces(ctx)
    ok = [f for f in faces if _faces_ok(f[0], ctx)]
    return min(ok, key=lambda f: f[1]) if ok else None


def place(ctx: PlaceCtx) -> Placement:
    face = find_back(ctx)
    if face is None:
        return Placement(ctx.xy[0], ctx.xy[1], ctx.yaw, ctx.base)
    (nx, ny), d = face
    move = BACK + GAP - d
    return Placement(ctx.xy[0] + nx * move, ctx.xy[1] + ny * move, math.atan2(nx, ny), ctx.base)


POSTURE = PostureSpec(
    id="lean",
    angles=ANGLES,
    surface=("back_support",),
    reach=Reach(lean=10, twist=30),
    place_hook=place,
)

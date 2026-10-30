"""눕는 자세(눕기 · 옆으로 눕기 · 엎드리기)가 함께 쓰는 몸축 배치. 등록부가 읽지 않는다 (`_` 로 시작).

몸축(골반 → 머리)을 정하고, 그 축이 되도록 yaw 를 고른다. 각도 표마다 머리가 몸 어느 쪽으로 가는지가 다르므로
yaw 0 에서 FK 로 재서 맞춘다. 설계는 docs/stage/3d/specs/postures/lie.md · side.md · prone.md. LLM 호출 없음.
"""
from __future__ import annotations

import math
from typing import Optional

from ... import stage
from .. import furniture
from ..body import Angles, Body, L, PlaceCtx, Placement, pose

HEAD_CLEAR = 0.05  # 머리 꼭대기와 머리 쪽 가구(머리판 · 팔걸이) 사이
CLOSE = 0.30       # 다른 누운 인물 옆에 붙어 누울 때 두 몸축 사이 (몸통 두께 0.21 + 틈)
_TALL = 0.05       # 눕는 면보다 이만큼 높은 상자가 끝을 막는다


def _xy(v) -> tuple[float, float]:
    return (v[0], v[1])


def _ang(v: tuple[float, float]) -> float:
    """평면 벡터의 각: (sin a, cos a) 꼴 (Placement.yaw 와 같은 각)."""
    return math.atan2(v[0], v[1])


def _wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


def head_dir(body: Body) -> tuple[float, float]:
    """놓인 몸의 몸축 (골반 → 머리, 평면 단위 벡터)."""
    j = body.joints()
    dx, dy = j["head"][0] - j["pelvis"][0], j["head"][1] - j["pelvis"][1]
    d = math.hypot(dx, dy) or 1.0
    return (dx / d, dy / d)


def face_dir(body: Body) -> tuple[float, float]:
    """놓인 몸의 몸 앞 (등 → 가슴, 평면 단위 벡터)."""
    c, b = body.part_point("chest"), body.part_point("back")
    dx, dy = c[0] - b[0], c[1] - b[1]
    d = math.hypot(dx, dy) or 1.0
    return (dx / d, dy / d)


def yaw_for_head(angles: Angles, hd: tuple[float, float]) -> float:
    """몸축이 hd 가 되는 yaw."""
    return _wrap(_ang(hd) - _ang(head_dir(pose(angles, 0, 0))))


def yaw_for_face(angles: Angles, fd: tuple[float, float]) -> float:
    """몸 앞이 fd 를 보는 yaw."""
    return _wrap(_ang(fd) - _ang(face_dir(pose(angles, 0, 0))))


def head_reach(angles: Angles) -> float:
    """골반에서 몸축 쪽으로 머리 꼭대기까지 (평면 m)."""
    b = pose(angles, 0, 0)
    hd = head_dir(b)
    return max(j[0] * hd[0] + j[1] * hd[1] for j in b.joints().values()) + L.head


def _insets(f: furniture.Furniture, axis: str, lie_h: float) -> tuple[float, float]:
    """축(u · v) 양 끝을 막은 높은 상자의 두께 비율 (앞 끝, 뒤 끝)."""
    lo = hi = 0.0
    for b in f.boxes:
        if not b.solid or b.z1 <= lie_h + _TALL:
            continue
        a0, a1 = (b.u0, b.u1) if axis == "u" else (b.v0, b.v1)
        if a0 <= 0.01 and a1 < 0.5:
            lo = max(lo, a1)
        elif a1 >= 0.99 and a0 > 0.5:
            hi = max(hi, 1 - a0)
    return lo, hi


def on_furniture(ctx: PlaceCtx, angles: Angles, anchor) -> Placement:
    """누울 수 있는 기준점 위: 몸축은 기준점의 긴 쪽, 머리는 Furniture.head 쪽 끝.
    head 가 긴 쪽 끝을 가리키지 않으면 긴 쪽이 앞뒤일 때는 뒤(back), 가로일 때는 앞에서 본 왼쪽 끝에 머리를 둔다
    (소파 기본값 back 은 가로로 긴 소파에서 왼쪽 끝이 된다). 가로로는 높은 상자(등받이)를 뺀 칸 가운데에 눕는다."""
    f = furniture.lookup(anchor, ctx.spec)
    fx, fy = stage._front(anchor.rot)
    rx, ry = fy, -fx  # 앞에서 바라본 오른쪽 (furniture.world_box 와 같음)
    depth = abs(fx) * anchor.w + abs(fy) * anchor.h
    width = abs(fy) * anchor.w + abs(fx) * anchor.h
    cx, cy = anchor.x + anchor.w / 2, anchor.y + anchor.h / 2
    lie_h = ctx.base
    if depth >= width:
        axis, e, n, length, side, side_len = "v", (fx, fy), (rx, ry), depth, "u", width
        head_hi = False  # back: v = 0 쪽
    else:
        axis, e, n, length, side, side_len = "u", (rx, ry), (fx, fy), width, "v", depth
        head_hi = f.head == "right"
    lo, hi = _insets(f, axis, lie_h)
    reach = head_reach(angles)
    t = (length - hi * length - HEAD_CLEAR - reach) if head_hi else (lo * length + HEAD_CLEAR + reach)
    slo, shi = _insets(f, side, lie_h)
    mid = (slo * side_len + side_len - shi * side_len) / 2
    s = (ctx.xy[0] - cx) * n[0] + (ctx.xy[1] - cy) * n[1]  # stage.place 가 여럿을 옆으로 편 몫
    x = cx + (t - length / 2) * e[0] + (mid - side_len / 2 + s) * n[0]
    y = cy + (t - length / 2) * e[1] + (mid - side_len / 2 + s) * n[1]
    hd = e if head_hi else (-e[0], -e[1])
    return Placement(x, y, yaw_for_head(angles, hd), lie_h)


def beside(ctx: PlaceCtx, angles: Angles, other: Body) -> Placement:
    """누운 다른 인물 옆: 같은 면 · 같은 몸축, 골반을 나란히 CLOSE 만큼 옆에. 어느 쪽인지는 stage.place 좌표가 정한다."""
    hd = head_dir(other)
    n = (hd[1], -hd[0])
    p = other.joints()["pelvis"]
    s = (ctx.xy[0] - p[0]) * n[0] + (ctx.xy[1] - p[1]) * n[1]
    sign = -1.0 if s < 0 else 1.0
    return Placement(p[0] + n[0] * CLOSE * sign, p[1] + n[1] * CLOSE * sign, yaw_for_head(angles, hd), other.base)


def place(ctx: PlaceCtx, angles: Angles, floor: str = "head") -> Placement:
    """눕는 자세 공통 배치.
    1. 자리가 누울 수 있는 기준점 on · in: on_furniture.
    2. 자리가 @인물(위 · 안 빼고)이고 그 인물이 누워 있으면: beside.
    3. 바닥: 골반은 stage.place 좌표. floor 가 head 면 머리를 향함 쪽에, face 면 몸 앞을 향함 쪽에 둔다."""
    at = ctx.now.at
    if at and at.rel in ("on", "in"):
        anchor = next((a for a in ctx.room.anchors if a.id == at.ref), None)
        if anchor is not None and anchor.lie:
            return on_furniture(ctx, angles, anchor)
    if at and at.ref.startswith("@") and at.rel not in ("on", "in"):
        other: Optional[Body] = ctx.bodies.get(at.ref[1:])
        if other is not None and not other.upright:
            return beside(ctx, angles, other)
    v = (math.sin(ctx.yaw), math.cos(ctx.yaw))
    yaw = yaw_for_face(angles, v) if floor == "face" else yaw_for_head(angles, v)
    return Placement(ctx.xy[0], ctx.xy[1], yaw, ctx.base)

"""자세 모듈: 안기거나 업히기 (docs/stage/3d/specs/postures/held.md). 받치는 사람에게 매단다. 첫 값은 시안 POSE.held 를 고친 값."""
from __future__ import annotations

import math
from typing import Optional

from ... import stage
from ..body import Angles, PlaceCtx, Placement, PostureSpec, Reach

ANGLES = Angles(1.05, pitch=6, spine=10, shoulder=(80, 80), abduct=(18, 18), elbow=(50, 50), hip=(75, 75), knee=(85, 85),
                leg_abduct=(38, 38))  # pelvis_h 는 받치는 사람이 없을 때

BACK = (-0.30, 0.12)   # 업힘: 받치는 사람 골반에서 앞쪽 m, 위 m (같은 방향)
FRONT = (0.25, 0.12)   # 안겨 들림: 골반 앞 · 위 (마주 봄)


def supporter(ctx: PlaceCtx) -> Optional[tuple[str, str]]:
    """받치는 사람 (id, 받침 동작 id). 1. 선 자세로 이 사람에게 받침 동작 접촉을 하는 인물 2. 자리가 @인물 이면 그 인물."""
    for o, s in ctx.state.items():
        if o == ctx.who or o not in ctx.bodies:
            continue
        p = stage.POSTURES.get(s.posture or "stand")
        if not p or not p.upright:
            continue
        for c in s.contacts.values():
            a = stage.ACTS.get(c.act)
            if c.to == ctx.who and a and a.support:
                return o, c.act
    at = ctx.now.at
    if at and at.ref.startswith("@") and at.ref[1:] in ctx.bodies and at.ref[1:] != ctx.who:
        return at.ref[1:], ""
    return None


def place(ctx: PlaceCtx) -> Placement:
    """자리가 @받치는 사람 back 이거나 받침 동작이 업다(carry)면 업힘, 아니면 안겨 들림.
    받치는 사람이 없으면 제자리에 표 값 높이로 두고 attach 를 비운다 (판정이 no_support 로 짚는다)."""
    got = supporter(ctx)
    if got is None:
        return Placement(ctx.xy[0], ctx.xy[1], ctx.yaw, ctx.base)
    o, act = got
    at = ctx.now.at
    rel = at.rel if at and at.ref == "@" + o else ""
    back = rel == "back" or (act == "carry" and rel != "front")
    sup = ctx.bodies[o]
    p = sup.joints()["pelvis"]
    f = (math.sin(sup.yaw), math.cos(sup.yaw))
    ahead, up = BACK if back else FRONT
    yaw = sup.yaw if back else math.atan2(math.sin(sup.yaw + math.pi), math.cos(sup.yaw + math.pi))
    return Placement(p[0] + f[0] * ahead, p[1] + f[1] * ahead, yaw, p[2] + up - ANGLES.pelvis_h, attach=o)


POSTURE = PostureSpec("held", ANGLES, ("carrier",), Reach(lean=0, twist=20), place_hook=place)

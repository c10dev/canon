"""자세 모듈: 옆으로 눕기 (docs/stage/3d/specs/postures/side.md). 첫 값은 시안 POSE.side (오른쪽이 아래, roll +90)."""
import math
from dataclasses import replace

from ..body import Angles, Placement, PostureSpec, Reach, pose
from . import _lying

ANGLES = Angles(0.20, roll=90, spine=10, shoulder=(60, 60), elbow=(70, 70), hip=(35, 45), knee=(45, 60))


def _mirror(a: Angles) -> Angles:
    """왼쪽이 아래(roll -90): 좌우 짝을 바꿔 위쪽 다리가 늘 더 굽게 둔다."""
    sw = {f: getattr(a, f)[::-1] for f in ("shoulder", "abduct", "elbow", "hip", "knee", "leg_abduct", "hip_rot", "ankle")}
    return replace(a, roll=-a.roll, **sw)


LEFT_DOWN = _mirror(ANGLES)


def roll_for(head: tuple[float, float], facing: tuple[float, float]) -> float:
    """몸 앞이 향함 쪽을 보는 roll. roll +90(오른쪽이 아래)이면 몸 앞이 몸축의 왼쪽 (hy, -hx) 을 본다.
    향함이 몸축과 나란하면 +90 (명세 정할 것 1)."""
    d = facing[0] * head[1] - facing[1] * head[0]
    return -90.0 if d < -1e-6 else 90.0


def place(ctx):
    """기준점 위 · 다른 누운 인물 옆은 몸축이 '눕기'와 같고, 향함 쪽으로 몸 앞이 오게 roll 을 고른다(Placement.angles).
    바닥이면 몸 앞을 향함 쪽에 둔다 (roll +90)."""
    pl = _lying.place(ctx, ANGLES, floor="face")
    hd = _lying.head_dir(pose(ANGLES, pl.x, pl.y, pl.yaw, pl.base))
    want = (math.sin(ctx.yaw), math.cos(ctx.yaw))
    if roll_for(hd, want) > 0:
        return pl
    return Placement(pl.x, pl.y, _lying.yaw_for_head(LEFT_DOWN, hd), pl.base, pl.attach, LEFT_DOWN)


POSTURE = PostureSpec("side", ANGLES, ("lie", "floor"), Reach(lean=0, twist=0), place_hook=place)

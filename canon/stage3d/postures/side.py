"""자세 모듈: 옆으로 눕기 (docs/stage/3d/specs/postures/side.md). 첫 값은 시안 POSE.side (오른쪽이 아래, roll +90)."""
from ..body import Angles, PostureSpec, Reach
from . import _lying

ANGLES = Angles(0.20, roll=90, spine=10, shoulder=(60, 60), elbow=(70, 70), hip=(35, 45), knee=(45, 60))


def roll_for(head: tuple[float, float], facing: tuple[float, float]) -> float:
    """몸 앞이 향함 쪽을 보는 roll. roll +90(오른쪽이 아래)이면 몸 앞이 몸축의 왼쪽 (hy, -hx) 을 본다.
    향함이 몸축과 나란하면 +90 (명세 정할 것 1)."""
    d = facing[0] * head[1] - facing[1] * head[0]
    return -90.0 if d < -1e-6 else 90.0


def place(ctx):
    """기준점 위 · 다른 누운 인물 옆은 몸축이 '눕기'와 같다. 바닥이면 몸 앞을 향함 쪽에 둔다.
    기준점 위에서 향함이 몸축 오른쪽이면 roll -90 이 맞지만 Placement 가 각도를 바꾸지 못해 +90 그대로 둔다 (01 계약 빈틈)."""
    return _lying.place(ctx, ANGLES, floor="face")


POSTURE = PostureSpec("side", ANGLES, ("lie", "floor"), Reach(lean=0, twist=0), place_hook=place)

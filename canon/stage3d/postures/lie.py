"""자세 모듈: 눕기 (docs/stage/3d/specs/postures/lie.md). 등을 대고 눕는다. 첫 값은 시안 POSE.lie."""
from ..body import Angles, PostureSpec, Reach
from . import _lying

ANGLES = Angles(0.12, pitch=-90, abduct=(14, 14), elbow=(10, 10), knee=(8, 8))  # 얼굴이 위


def place(ctx):
    """누울 수 있는 기준점 위면 몸축을 긴 쪽에, 머리를 Furniture.head 쪽에. 바닥이면 머리를 향함 쪽에. 향함은 고개 돌리기로만 쓴다."""
    return _lying.place(ctx, ANGLES, floor="head")


POSTURE = PostureSpec("lie", ANGLES, ("lie", "floor"), Reach(lean=0, twist=0), place_hook=place)

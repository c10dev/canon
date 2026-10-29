"""자세 모듈: 엎드리기 (docs/stage/3d/specs/postures/prone.md). 배를 대고 엎드린다. 팔은 몸 옆(시안 값). 첫 값은 시안 POSE.prone."""
from ..body import Angles, PostureSpec, Reach
from . import _lying

ANGLES = Angles(0.12, pitch=90, abduct=(12, 12), elbow=(6, 6), knee=(10, 10))  # 얼굴이 아래


def place(ctx):
    """몸축은 '눕기'와 같다. 고개 위아래를 0 으로 두는 것은 frames 의 look_at 이 정해서 이 모듈이 막지 못한다."""
    return _lying.place(ctx, ANGLES, floor="head")


POSTURE = PostureSpec("prone", ANGLES, ("lie", "floor"), Reach(lean=0, twist=0), place_hook=place)

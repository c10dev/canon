"""자세 모듈: 서기 (stand). 명세는 docs/stage/3d/specs/postures/stand.md.

시안(docs/stage/mockup-3d.html 의 POSE.stand) 값 그대로다. 다른 자세 시험의 기준 몸이다.
침대 · 의자 위에 서기(top)를 허락한다. 차 안 · 마차 안은 천장 판정(headroom)이 막는다.
"""
from ..body import Angles, PostureSpec, Reach

POSTURE = PostureSpec(
    id="stand",
    angles=Angles(pelvis_h=0.92, abduct=(8, 8), elbow=(10, 10)),
    surface=("floor", "top"),
    reach=Reach(lean=30, twist=45),
)

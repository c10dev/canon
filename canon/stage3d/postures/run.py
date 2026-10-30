"""자세 모듈: 뛰기 (run). 명세는 docs/stage/3d/specs/postures/run.md.

시안(POSE.run) 값에서 골반 높이만 0.86 → 0.82 로 고쳤다. 0.86 이면 낮은 발(뒷발 발끝)이 바닥에서
6.6cm 떠서 '낮은 발이 바닥 0.05m 안' 을 넘는다. 0.82 이면 2.6cm 다. 다리 각도는 그대로다.
두 발이 다 떠 있어도 낮은 발이 0.05m 안이면 받침이 있는 것으로 본다(공중 자세를 받침 판정에서 빼지 않는다).
"""
from ..body import Angles, PostureSpec, Reach

POSTURE = PostureSpec(
    id="run",
    angles=Angles(pelvis_h=0.82, spine=16, shoulder=(-40, 50), abduct=(8, 8), elbow=(85, 85), hip=(62, -22), knee=(70, 40)),
    surface=("floor",),
    reach=Reach(lean=15, twist=20),
)

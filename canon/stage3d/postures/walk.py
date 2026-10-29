"""자세 모듈: 걷기 (walk). 명세는 docs/stage/3d/specs/postures/walk.md.

시안(POSE.walk) 값에서 왼무릎만 28 → 22 로 고쳤다. 28 이면 뒷발 발끝이 바닥에서 2cm 떠서
'낮은 발이 바닥 ±0.02' 를 겨우 넘는다. 22 이면 뒷발 발끝이 바닥에 닿는다(차고 나가는 발).
보폭 모양은 한 가지다. 박자 끝 상태만 보므로 걸음 위상은 뜻이 없다.
"""
from ..body import Angles, PostureSpec, Reach

POSTURE = PostureSpec(
    id="walk",
    angles=Angles(pelvis_h=0.90, spine=4, shoulder=(25, -20), abduct=(6, 6), elbow=(20, 20), hip=(-18, 24), knee=(22, 6)),
    surface=("floor",),
    reach=Reach(lean=20, twist=30),
)

"""쪼그려 앉기 (docs/stage/3d/specs/postures/squat.md). 발바닥을 대고 쪼그린다.

각도는 시안 그대로지만 골반을 0.42 에서 0.28 로 내렸다: 0.42 면 발이 바닥 위 14cm 에 뜬다.
발목 각이 없어 발은 정강이에 수직이다. 발끝이 바닥에 닿고 뒤꿈치는 5cm 들린다.
"""
from __future__ import annotations

from ..body import Angles, PostureSpec, Reach

POSTURE = PostureSpec(
    id="squat",
    angles=Angles(0.28, spine=30, shoulder=(45, 45), abduct=(6, 6), elbow=(60, 60), hip=(120, 120), knee=(140, 140)),
    surface=("floor", "top"),
    reach=Reach(lean=20, twist=30),  # 균형
)

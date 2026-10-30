"""쪼그려 앉기 (docs/stage/3d/specs/postures/squat.md). 발바닥을 대고 쪼그린다.

시안은 엉덩 120 · 무릎 140 · 골반 0.42 였다. 발목 각이 없던 뼈대에서는 발이 떠서 골반을 0.28 로 내리고 뒤꿈치를 들었다.
발목을 발등 쪽으로 32° 젖혀(ankle -32) 발바닥을 바닥에 붙이고, 무릎을 150 으로 더 접어 골반을 0.21 에 둔다(엉덩이가 발뒤꿈치 위).
"""
from __future__ import annotations

from ..body import Angles, PostureSpec, Reach

POSTURE = PostureSpec(
    id="squat",
    angles=Angles(0.21, spine=30, shoulder=(45, 45), abduct=(6, 6), elbow=(60, 60), hip=(120, 120), knee=(150, 150), ankle=(-32, -32)),
    surface=("floor", "top"),
    reach=Reach(lean=20, twist=30),  # 균형
)

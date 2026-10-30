"""무릎 꿇기 (docs/stage/3d/specs/postures/kneel.md). 두 무릎을 대고 상체를 세운다.

무릎을 시안 90° 에서 105° 로, 골반을 0.50 에서 0.51 로 고쳤다: 90° 면 정강이가 수평이라
정강이에 수직인 발이 바닥 아래 0.13m 로 들어간다. 105° 면 발등이 비스듬히 서고 무릎 점 · 발끝이 바닥 ±0.01 이다.
"""
from __future__ import annotations

from ..body import Angles, PostureSpec, Reach

POSTURE = PostureSpec(
    id="kneel",
    angles=Angles(0.51, shoulder=(10, 10), abduct=(6, 6), elbow=(30, 30), knee=(105, 105)),
    surface=("floor", "lie", "top"),
    reach=Reach(lean=30, twist=40),
)

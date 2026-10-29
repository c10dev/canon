"""바닥에 앉기 (docs/stage/3d/specs/postures/floor.md). 바닥 · 침대 위 · 윗면에 앉는다.

시안은 책상다리(엉덩 82 · 무릎 120 · 다리 벌림 25)지만 이 뼈대로는 책상다리를 만들 수 없다:
엉덩관절 돌림과 발목 각이 없어 정강이를 접으면 발끝이 면 아래 0.09m 이상으로 들어간다(계약 시험의 가장 낮은 관절 -0.02 를 못 넘음).
그래서 다리를 25° 벌려 앞으로 뻗고 무릎을 조금 세운 모양으로 둔다(엉덩 96 · 무릎 16). 뒤꿈치가 면에 닿고 발끝은 위를 본다.
"""
from __future__ import annotations

from ..body import Angles, PostureSpec, Reach

POSTURE = PostureSpec(
    id="floor",
    angles=Angles(0.10, spine=12, shoulder=(25, 25), abduct=(6, 6), elbow=(40, 40), hip=(96, 96), knee=(16, 16), leg_abduct=(25, 25)),
    surface=("floor", "lie", "top"),
    reach=Reach(lean=35, twist=45),
)

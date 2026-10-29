"""바닥에 앉기 (docs/stage/3d/specs/postures/floor.md). 바닥 · 침대 위 · 윗면에 양반다리로 앉는다.

시안(엉덩 82 · 무릎 120 · 다리 벌림 25)은 엉덩이 돌림이 없던 뼈대라 정강이가 면 아래로 들어갔다.
엉덩이 바깥돌림(hip_rot)으로 무릎을 굽힌 정강이가 몸 가운데로 눕게 했다. 두 다리가 같으면 정강이가 한자리에서 겹치므로
왼 정강이를 깊이 접어(무릎 145) 사타구니 앞에, 오른 정강이를 덜 접어(무릎 110) 그 앞에 둔다.
골반은 면 위 0.12m (0.10 이면 발 캡슐이 면을 2cm 파고든다). 무릎은 면 위 약 0.16m.
"""
from __future__ import annotations

from ..body import Angles, PostureSpec, Reach

POSTURE = PostureSpec(
    id="floor",
    angles=Angles(0.12, spine=12, shoulder=(25, 25), abduct=(6, 6), elbow=(40, 40), hip=(100, 100), knee=(145, 110),
                  leg_abduct=(35, 35), hip_rot=(75, 70)),
    surface=("floor", "lie", "top"),
    reach=Reach(lean=35, twist=45),
)

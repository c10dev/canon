"""차 안 (docs/stage/3d/specs/rooms/car.md). 차 바닥이 z 0, 실내 높이 1.15m.

자리 · 크기 · rot 은 stage.ROOMS["car"] 에서 읽는다. 앞좌석 사이 콘솔은 두지 않는다.
뒷좌석은 폭(1.5m) 방향으로 눕게 머리 쪽을 left 로 둔다.
앞좌석 아래 0.15m 는 비운다: 뒷좌석에 앉은 사람의 발이 앞좌석 밑으로 들어간다(어림, 명세 표의 '앉는 판 0~0.30' 에서 바꿈).
"""
from ..furniture import Box, Furniture, RoomSpec

_FRONT = Furniture((Box(0, 1, 0, 1, 0.15, 0.30), Box(0, 1, 0, 0.15, 0.15, 0.95)), seat=0.30)  # 앉는 면 약 0.25~0.30
_REAR = Furniture((Box(0, 1, 0, 1, 0, 0.30), Box(0, 1, 0, 0.15, 0, 0.85)), seat=0.30, lie=0.30, head="left")

ROOM = RoomSpec(template="car", ceiling=1.15, anchors={
    "운전석": _FRONT,
    "조수석": _FRONT,
    "뒷좌석": _REAR,
    "앞유리": Furniture((Box(0, 1, 0, 1, 0.6, 1.1, solid=False),)),
})

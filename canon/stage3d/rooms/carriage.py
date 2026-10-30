"""마차 안 (docs/stage/3d/specs/rooms/carriage.md). 실내 높이 1.6m(역사 마차 약 1.5~1.7, 작품 세계마다 다름).

자리 · 크기 · rot 은 stage.ROOMS["carriage"] 에서 읽는다. 두 좌석은 0.8m 사이를 두고 마주 본다.
"""
from ..furniture import Box, Furniture, RoomSpec

_BENCH = Furniture((Box(0, 1, 0, 1, 0, 0.45), Box(0, 1, 0, 0.15, 0, 1.1)), seat=0.45)

ROOM = RoomSpec(template="carriage", ceiling=1.6, anchors={
    "앞좌석": _BENCH,
    "뒷좌석": _BENCH,
    "문": Furniture((Box(0, 1, 0, 1, 0.3, 1.5, solid=False),)),
})

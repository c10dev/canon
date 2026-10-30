"""교실 (docs/stage/3d/specs/rooms/classroom.md). 교탁 · 칠판 · 자리(책상 겸 의자)를 덮어쓴다.

자리 · 크기 · rot 은 stage.ROOMS["classroom"] 에서 읽는다. 자리는 앞쪽(v 0.5~1, 칠판 쪽)이 책상 판, 뒤쪽(v 0~0.45)이 의자다.
판 아래는 비워 둬 앉은 사람의 무릎이 책상 아래로 들어간다.
"""
from ..furniture import Box, Furniture, RoomSpec

_SPOT = Furniture((Box(0, 1, 0.5, 1, 0.68, 0.72),     # 책상 판 0.68~0.72
                   Box(0, 1, 0, 0.45, 0.40, 0.43),    # 앉는 판 0.40~0.43
                   Box(0, 1, 0, 0.08, 0.43, 0.8)),    # 등받이
                  seat=0.43)

ROOM = RoomSpec(template="classroom", ceiling=3.0, anchors={
    "교탁": Furniture((Box(0, 1, 0, 1, 0, 1.0),)),          # 서서 쓰는 교탁 약 1.0, 다리 공간 없음
    "칠판": Furniture((Box(0, 1, 0, 1, 0.9, 2.1),)),        # 칠판 아래 끝 약 0.9
    "앞자리": _SPOT,
    "뒷자리": _SPOT,
    "창가 자리": _SPOT,
})

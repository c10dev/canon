"""야외 빈터 (docs/stage/3d/specs/rooms/outdoor.md). 땅이 z 0, 벽 · 천장 없음(open). ceiling 은 그림 높이만.

자리 · 크기 · rot 은 stage.ROOMS["outdoor"] 에서 읽는다. 길은 종류 기본값(ground, 걸어 다니는 면)이다.
"""
from ..furniture import Box, Furniture, RoomSpec

ROOM = RoomSpec(template="outdoor", ceiling=4.0, open=True, anchors={
    "큰 나무": Furniture((Box(0.4, 0.6, 0.4, 0.6, 0, 2.4), Box(0, 1, 0, 1, 2.4, 4.0, solid=False))),  # 줄기 지름 약 0.25m, 가지는 머리 위
    "바위": Furniture((Box(0, 1, 0, 1, 0, 0.5),), seat=0.5),        # 걸터앉는 바위
    "표지판": Furniture((Box(0.45, 0.55, 0.3, 0.7, 0, 1.4), Box(0, 1, 0.3, 0.7, 1.4, 2.0))),  # 기둥과 판
    "모닥불": Furniture((Box(0, 1, 0, 1, 0, 0.3),)),                 # 돌로 두른 불 자리
})

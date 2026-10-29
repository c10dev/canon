"""사무실 (docs/stage/3d/specs/rooms/office.md). 책상 · 의자 · 손님 의자 · 문은 종류 기본값이고 책장만 덮어쓴다.

자리 · 크기 · rot 은 stage.ROOMS["office"] 에서 읽는다.
"""
from ..furniture import Box, Furniture, RoomSpec

ROOM = RoomSpec(template="office", ceiling=2.6, anchors={
    "책장": Furniture((Box(0, 1, 0, 1, 0, 2.0),)),  # 책장 높이 1.8~2.1
})

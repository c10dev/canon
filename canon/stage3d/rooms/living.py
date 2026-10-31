"""거실 (docs/stage/3d/specs/rooms/living.md). 탁자는 낮은 탁자, 텔레비전은 받침장 + 화면으로 덮어쓴다.

자리 · 크기 · rot 은 stage.ROOMS["living"] 에서 읽는다. 소파는 종류 기본값의 모양이고, 2.2m 길이로 눕게 머리 쪽만 left 로 바꾼다.
"""
from ..furniture import KINDS, Box, Furniture, RoomSpec

_SOFA = KINDS["sofa"]

ROOM = RoomSpec(template="living", ceiling=2.4, anchors={
    "소파": Furniture(_SOFA.boxes, seat=_SOFA.seat, lie=_SOFA.lie, head="left"),
    "탁자": Furniture((Box(0, 1, 0, 1, 0.40, 0.45),)),                                # 소파 탁자 0.40~0.45
    "텔레비전": Furniture((Box(0, 1, 0, 1, 0, 0.5), Box(0, 1, 0.3, 0.7, 0.5, 1.1))),  # 받침장 0.45~0.5, 55인치 화면 약 0.7
})

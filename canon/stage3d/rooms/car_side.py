"""차 옆 (docs/stage/3d/specs/rooms/car_side.md). 땅이 z 0, 벽 · 천장 없음(open). 캠핑카 · 승합차 크기의 차 한 대.

자리 · 크기 · rot 은 stage.ROOMS["car_side"] 에서 읽는다. 차체는 막힌 덩어리(barrier)이고, 운전석 칸(앞 1.2m)만 비어 있다.
운전석 칸은 옆판(창 아래) · 지붕으로 막고, 창 높이(1.25~2.1m)는 열려 있어 창 너머로 손이 닿는다.
차체 rot 90: v 1 이 운전석 쪽 옆면(x 3.9), u 0 → 1 이 차 앞(보닛) → 뒤. 운전석 칸은 u 0~0.23 (y 2.0~3.2).
차 바닥 높이는 두지 않는다: 앉은 사람의 발은 땅까지 내려간다(어림).
"""
from ..furniture import Box, Furniture, RoomSpec

_CAB = 1.2 / 5.2   # 운전석 칸 길이 / 차체 길이
_SIDE = 0.1 / 2.2  # 옆판 두께 / 차 폭
_SILL, _ROOF = 1.25, 2.1  # 창 아래 끝 · 지붕 아래 끝 (m)

_BODY = Furniture((
    Box(_CAB, 1, 0, 1, 0.3, 3.0, barrier=True),                 # 뒤 생활칸: 캠핑카 높이 약 3.0m
    Box(0, _CAB, 1 - _SIDE, 1, 0.45, _SILL, barrier=True),      # 운전석 쪽 옆판 (창 아래)
    Box(0, _CAB, 0, _SIDE, 0.45, _SILL, barrier=True),          # 조수석 쪽 옆판
    Box(0, _CAB, 0, 1, _ROOF, 2.5),                             # 운전석 칸 지붕
))
_SEAT = Furniture((Box(0, 1, 0, 1, 0, 1.05), Box(0, 1, 0, 0.15, 1.05, 1.75)), seat=1.05)  # 1톤 트럭 바탕 캠핑카 좌석 약 1.0~1.1m
_WINDOW = Furniture((Box(0, 1, 0, 1, _SILL, _ROOF, solid=False),))

ROOM = RoomSpec(template="car_side", ceiling=4.0, open=True, anchors={
    "보닛": Furniture((Box(0, 1, 0, 1, 0.35, 1.15, barrier=True),)),  # 보닛 높이 약 1.1m
    "차체": _BODY,
    "운전석": _SEAT,
    "조수석": _SEAT,
    "운전석 문": Furniture((Box(0, 1, 0, 1, 0.45, _ROOF, solid=False),)),  # 닫힌 문의 막은 차체 옆판이 맡는다
    "운전석 창": _WINDOW,
    "조수석 창": _WINDOW,
})

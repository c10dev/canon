"""침실 (docs/stage/3d/specs/rooms/bedroom.md). 침대 · 책상 · 의자 · 창 · 문은 모두 종류 기본값이다.

자리 · 크기 · rot 은 stage.ROOMS["bedroom"] 에서 읽는다. 침대 머리판은 종류 기본값(v 0~0.05, 0~0.9)에 있고 머리 쪽은 back.
"""
from ..furniture import RoomSpec

ROOM = RoomSpec(template="bedroom", ceiling=2.4)

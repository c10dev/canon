"""빈 방 (docs/stage/3d/specs/rooms/empty.md). 문은 종류 기본값이고, 작가가 더한 기준점도 모두 종류 기본값(KINDS)을 쓴다.

자리 · 크기 · rot 은 stage.ROOMS["empty"] 에서 읽는다.
"""
from ..furniture import RoomSpec

ROOM = RoomSpec(template="empty", ceiling=2.4)

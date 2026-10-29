# 03-07. 장소 모듈: 빈 방 (`empty`)

상태: 완료 (`canon/stage3d/rooms/empty.py`, 시험 `tests/test_stage3d_rooms.py`) · 묶음: R · 공통: [../03-room.md](../03-room.md) · 먼저: [../01-body.md](../01-body.md)

## 목표

`stage.ROOMS["empty"]`(빈 방, 4.0 × 3.0m)의 기준점에 높이 · 모양을 더하고 천장 높이를 정한다.

## 정할 것

1. 더한 기준점의 이름으로 모양을 짐작할까(이름에 '소파'가 들어가면 sofa) — 추천: 하지 않는다. 종류가 이미 있다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/stage3d/rooms/empty.py` (새) | `ROOM = RoomSpec(template="empty", ceiling=2.4, anchors={...})` |
| `tests/test_stage3d_room_empty.py` (새) | 아래 '시험' |

## 계약 (입력 · 출력)

천장: **2.4m**

| 기준점 이름 | 종류 | 모양 (높이 m) | 앉는 면 · 눕는 면 | 근거 (흔한 치수 어림) |
|---|---|---|---|---|
| 문 | `door` | 문틀 0~2.0 | — |  |

'종류 기본값'이라 적은 줄은 `anchors` 에 넣지 않는다. '덮어씀'만 넣는다.

## 특이점

작가가 기준점을 더해 쓰는 틀이다. 더한 기준점은 모두 종류 기본값(`KINDS`)을 쓴다. 이 틀이 종류 기본값의 시험대다.

## 시험

- 계약 시험과 빈자리 시험([../03-room.md](../03-room.md))이 이 틀에서 통과한다.
- 빈 방에 종류마다 기준점 하나씩 더해(bed · chair · sofa · desk · table · seat · wall · other) 빈자리 시험을 돌린다.
- 위에서 · 비스듬히 사진 두 장을 PR 에 붙인다.

## 확인하지 못할 것

치수가 작품 세계에 맞는지는 사용자 판단이다.

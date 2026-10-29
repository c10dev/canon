# 02-08. 자세 모듈: 무릎 꿇기 (`kneel`)

상태: 명세 · 묶음: P2 · 공통: [../02-posture.md](../02-posture.md) · 먼저: [../01-body.md](../01-body.md)

## 목표

두 무릎을 대고 상체를 세운다.

## 정할 것

1. 한쪽 무릎만 꿇기 — 추천: 따로 두지 않고 메모로 적는다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/stage3d/postures/kneel.py` (새) | `POSTURE = PostureSpec(id="kneel", ...)` |
| `tests/test_stage3d_posture_kneel.py` (새) | 아래 '시험' |

## 계약 (입력 · 출력)

| 칸 | 값 |
|---|---|
| `id` | `kneel` (`stage.POSTURES["kneel"]`: 무릎 꿇기) |
| `angles` 첫 값 (시안) | pelvis_h 0.50, 어깨 10, 팔꿈치 30, 무릎 90 |
| `surface` | `floor`, `lie`(침대 위), `top` |
| `reach` | 숙임 30° · 비틀기 40° |
| 특수 배치 | 없음 |

## 시안 검토

시안에서 그대로 읽혔다.

## 시험

- 무릎 점 · 발끝이 면 ±0.02.
- 넓적다리가 수직 ±5°.
- 계약 시험(`tests/test_stage3d_contract.py`)이 이 자세에서 통과한다.
- 앞 · 옆 · 위 사진 세 장을 PR 에 붙인다.

## 확인하지 못할 것

자연스러운지는 사용자가 사진으로 본다.

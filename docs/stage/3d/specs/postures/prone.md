# 02-11. 자세 모듈: 엎드리기 (`prone`)

상태: 구현 (2026-10-29, PR #171, 시험 `tests/test_stage3d_postures_p3.py`, 사진 세 장은 아직) · 묶음: P3 · 공통: [../02-posture.md](../02-posture.md) · 먼저: [../01-body.md](../01-body.md)

## 목표

배를 대고 엎드린다.

## 정할 것

1. 팔을 머리 위로 올릴까 — 추천: 몸 옆(시안 값). 팔베개는 메모로.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/stage3d/postures/prone.py` (새) | `POSTURE = PostureSpec(id="prone", ...)` |
| `tests/test_stage3d_posture_prone.py` (새) | 아래 '시험' |

## 계약 (입력 · 출력)

| 칸 | 값 |
|---|---|
| `id` | `prone` (`stage.POSTURES["prone"]`: 엎드리기) |
| `angles` 첫 값 (시안) | pelvis_h 0.12, 기울기 90(얼굴이 아래), 팔 벌림 12, 팔꿈치 6, 무릎 10 |
| `surface` | `lie`, `floor` |
| `reach` | 숙임 0° · 비틀기 0°(팔만) |
| 특수 배치 | `place_hook`: 몸축은 '눕기'와 같다. 고개는 좌우로만 돌린다(위아래 0). |

## 시안 검토

시안에서 그대로 읽혔다.

## 시험

- 가슴 부위 점이 등 부위 점보다 낮다.
- 모든 관절이 눕는 면 +0~0.25.
- 계약 시험(`tests/test_stage3d_contract.py`)이 이 자세에서 통과한다.
- 앞 · 옆 · 위 사진 세 장을 PR 에 붙인다.

## 확인하지 못할 것

자연스러운지는 사용자가 사진으로 본다.

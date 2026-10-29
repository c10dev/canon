# 01. 뼈대 · 마네킹 공통 (계약)

상태: 명세 · 지도: [../README.md](../README.md) 의 01 · 먼저: 없음 · 시안: [../../mockup-3d.html](../../mockup-3d.html)

## 목표

3D 모듈 모두가 믿는 계약을 만든다. 좌표계, 마네킹 마디, 관절 계산(FK), 손 IK, 부위 점, 몸 캡슐, 가구 모양 틀, 자세 · 장소 등록부, 박자마다 관절 좌표를 내는 `frames` 다. 작가에게 보이는 동작은 아직 없다. 이 일감이 병합돼야 자세 · 장소 · 판정 · 렌더러 세션이 갈라진다.

실제 자세 12개와 방 틀 7개는 만들지 않는다. 시험은 시험 폴더 안의 가짜 자세 · 가짜 장소로 한다.

## 정할 것

[../README.md](../README.md) 의 정할 것 1(파이썬이 계산), 4(같은 마네킹), 8(판정은 `place` 좌표 그대로), 9(이름으로 찾고 종류 기본값)를 전제로 한다. 이 모듈만의 것:

1. 수학 도구 — 추천: 순수 파이썬(`math`)으로 3차원 벡터 · 회전 행렬만 짧게 둔다. `requirements.txt` 에 numpy 가 없고, 한 장면 계산은 관절 수십 개라 느리지 않다.
2. 부위 점 · 캡슐을 frames 에 다 넣을까 — 추천: 관절 좌표와 캡슐은 넣고 부위 점 45개는 접촉에 쓰인 것만 넣는다(응답 크기). 판정은 `part_point()` 로 필요한 점을 다시 구한다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/stage3d/__init__.py` (새) | 공개 이름: `frames`, `Frames`, `postures()`, `rooms()`, `missing()` |
| `canon/stage3d/body.py` (새) | 벡터 · 회전, 마디 길이 `L`, `Angles`, `Reach`, `PostureSpec`, 관절 이름 `JOINTS`, FK `pose()`, 손 IK `reach_to()`, 부위 점 `PART_POINTS` · `part_point()`, 캡슐 `capsules()`, 겹침 깊이 `penetration()`, 동작별 손 배치 `ACT3D`, `frames()` 본체 |
| `canon/stage3d/furniture.py` (새) | `Box`, `Furniture`, `RoomSpec`, 종류 기본값 `KINDS`, 기준점 → 세계 상자 `solids()`, 앉는 면 높이 `surface()` |
| `canon/stage3d/postures/__init__.py` (새) | 등록부: 이 폴더의 모듈을 훑어 `POSTURE` 를 모은다(`pkgutil.iter_modules`). 자세 모듈은 만들지 않는다 |
| `canon/stage3d/rooms/__init__.py` (새) | 등록부: 같은 방식으로 `ROOM` 을 모은다. 장소 모듈은 만들지 않는다 |
| `tests/test_stage3d_body.py` (새) | 아래 '시험' |
| `tests/test_stage3d_contract.py` (새) | 자세 · 장소 모듈이 계약을 지키는지 등록부를 훑어 본다(모듈이 하나도 없어도 통과) |

`canon/stage.py` · `schema.py` · `web.py` 는 고치지 않는다. `stage` 는 읽기만 한다(`POSTURES`, `PARTS`, `ACTS`, `ROOMS`, `state_at`, `place` · `layouts`, `facing_vec`, `_front`). 01 은 일감 1-1(PR #163) 브랜치 위에서 시작하는 것이 좋다(`layouts` · `Violation.contact` · 고친 의자 `rot`).

## 계약 (입력 · 출력)

### 좌표계

- 평면도와 같은 x(오른쪽) · y(아래쪽)에 높이 z(위)를 더한다. 단위 m. 바닥은 z = 0.
- 인물 몸의 앞은 향함 벡터(`stage.facing_vec`, 평면 (fx, fy))다. 향함을 모르면 `place` 처럼 (0, 1)이다.
- 인물의 왼쪽은 앞에서 시계 반대로 90°다(평면도 y 가 아래이므로 (fy, −fx)). 시안의 three.js 좌표(+x 왼쪽, +z 앞)는 렌더러가 바꾼다.

### 마디 (`body.L`, m)

넓적다리 0.44, 정강이 0.46, 몸통(골반 → 어깨선) 0.50, 목 0.08, 머리 반지름 0.11, 위팔 0.30, 아래팔 0.27, 손 0.08, 어깨 반폭 0.19, 엉덩이 반폭 0.10, 발 길이 0.22. 키 약 1.72m. 시안 값 그대로다.

### 관절 각도 `Angles` (도, 굽힘이 +)

시안의 자세 표와 같은 칸: `pelvis_h`(바닥 또는 앉는 면에서 골반까지 m), `pitch`(몸 전체 앞 +), `roll`(옆으로 눕기 +는 오른쪽이 아래), `spine`(허리 앞굽힘), `shoulder` · `abduct` · `elbow` · `hip` · `knee` · `leg_abduct`(모두 `(왼, 오른)`), `shift`(향한 쪽으로 옮김 m, 의자에 앉기 −0.13).

### 자세 모듈이 내는 것 `PostureSpec`

```python
@dataclass(frozen=True)
class Reach:
    lean: float = 30     # 손이 모자랄 때 허리를 더 숙일 수 있는 최대(도)
    twist: float = 45    # 몸통을 비틀 수 있는 최대(도)

@dataclass(frozen=True)
class PostureSpec:
    id: str                                   # stage.POSTURES 의 키
    angles: Angles
    surface: tuple[str, ...]                  # 놓일 수 있는 면: floor · seat · lie · top · back_support · carrier
    reach: Reach = Reach()
    feet_to_floor: bool = False               # 앉는 면이 0.45m 와 다르면 무릎을 고쳐 발을 바닥에 댄다
    place_hook: Optional[Callable[[PlaceCtx], Placement]] = None   # 기대기 · 매달기 같은 특수 배치
```

- `surface` 의 뜻: `floor` 바닥, `seat` 앉을 수 있는 기준점(`sit` 참)의 앉는 면, `lie` 누울 수 있는 기준점(`lie` 참)의 눕는 면, `top` 기준점 윗면(침대 위에 선다), `back_support` 등 뒤에 벽 · 기준점, `carrier` 다른 인물이 받친다.
- `place_hook` 은 `PlaceCtx`(인물, 상태, 평면 좌표, 방, 가구, 다른 인물의 배치)를 받아 `Placement`(평면 x · y, yaw, 바닥 높이, 매단 인물 id)를 돌려준다. 없으면 공통 배치를 쓴다.

### 장소 모듈이 내는 것 `RoomSpec`

```python
@dataclass(frozen=True)
class Box:            # 기준점 자리 안의 상자. u · v 는 기준점 폭 · 깊이의 비율(0~1), z 는 m
    u0: float; u1: float; v0: float; v1: float; z0: float; z1: float
    solid: bool = True     # False 면 판정이 겹침을 보지 않는다 (책상 다리 사이 공간을 따로 적을 때)

@dataclass(frozen=True)
class Furniture:
    boxes: tuple[Box, ...]
    seat: Optional[float] = None    # 앉는 면 높이 (sit 참일 때)
    lie: Optional[float] = None     # 눕는 면 높이 (lie 참일 때)
    head: str = "back"              # 누울 때 머리 쪽: back(앞의 반대) · left · right

@dataclass(frozen=True)
class RoomSpec:
    template: str                          # stage.ROOMS 의 키
    ceiling: float = 2.4                   # 천장 높이 m
    anchors: dict[str, Furniture] = {}     # 틀의 기준점 이름 → 모양
```

- 기준점 자리 좌표: v 는 기준점 앞쪽(`rot`)으로 0 → 1, u 는 앞에서 바라본 왼쪽 → 오른쪽으로 0 → 1. 그래서 `rot` 이 바뀌어도 모양이 같이 돈다.
- 평면 자리(x · y · w · h · rot)는 작가가 고친 `StageRoom` 의 값을 쓴다. 장소 모듈은 다시 적지 않는다.
- 기준점 모양 찾기: `RoomSpec.anchors[기준점 이름]` → 없으면 `furniture.KINDS[종류]` → 없으면 `KINDS["other"]`. `StageRoom.template` 이 비었거나 장소 모듈이 없으면 `KINDS` 만 쓴다.

### `furniture.KINDS` (종류 기본값)

| 종류 | 모양 | 앉는 면 · 눕는 면 |
|---|---|---|
| bed | 매트리스 0~0.5, 머리판(v 0~0.05) 0~0.9 | seat 0.5, lie 0.5 |
| chair | 앉는 판 0.4~0.45, 등받이(v 0~0.1) 0.45~0.9, 다리 사이는 비움 | seat 0.45 |
| sofa | 앉는 판 0~0.42, 등받이(v 0~0.25) 0~0.8, 팔걸이(u 0~0.1 · 0.9~1) 0~0.6 | seat 0.42, lie 0.42 |
| seat | 앉는 판 0~0.45, 등받이(v 0~0.15) 0~0.9 | seat 0.45 |
| desk | 판 0.72~0.75, 다리 사이는 비움 | — |
| table | 판 0.69~0.72, 다리 사이는 비움 | — |
| door | 문틀만 (solid 아님) | — |
| window | 창틀 0.9~2.0 (solid 아님. 벽은 방 테두리가 맡는다) | — |
| wall | 0~2.4 | — |
| other | 0~0.8 | — |

### 손 IK `reach_to(body, side, target, pole, reach) -> float`

- 어깨에서 목표까지 두 마디 IK. 위팔 방향은 '어깨 → 목표' 방향을 **pole 쪽으로** 돌려 얻는다(시안 첫판은 부호가 반대였다. 시험으로 막는다).
- 모자라면 먼저 몸통을 비틀고(최대 `reach.twist`) 숙인다(최대 `reach.lean`). 시안처럼 숙인 뒤 어깨 자리를 네 번까지 다시 잰다. 서거나 앉은 자세(pitch · roll 0)만 숙인다.
- 돌려주는 값은 남은 틈(손끝 → 목표, m). 0 이면 닿음.
- 기본 pole 은 아래 · 바깥 · 뒤. `ACT3D` 가 동작마다 바꾼다.

### 동작별 손 배치 `ACT3D`

시안 값: `hug` · `embrace` 는 두 손으로 등을 감는다(한 손 `back`, 한 손 그 0.2m 아래, 손은 제 쪽으로 5cm · 등 겉 3cm 뒤, pole `(0.8, −0.2, 1.0)`). `carry` 는 업힌 사람이 뒤에 매달렸으면 두 손을 그 사람의 `knee_l` · `knee_r` 로 보낸다(기본 pole). `by == both` 의 다른 동작은 부위 점 좌우 7cm 씩. `by` 가 부위 id 이면 손 없이 부위 점 사이를 잰다. 받침 동작(`stage.ACTS[act].support`)의 받는 쪽 매달기는 자세 모듈 `held` 의 `place_hook` 이 한다.

### 부위 점 `PART_POINTS`

`stage.PARTS` 의 모든 id(지금 47개: 기본 13 + 쌍 17 × 2)에 점이 있다. 시안의 `PART3D` 표 값을 쓰고 `forearm` 을 더한다. 쌍은 `_l` 값을 적고 `_r` 은 몸 바깥 방향을 뒤집는다.

### 몸 캡슐 `capsules(body) -> list[Capsule]`

판정이 겹침을 재는 몸 부피. 마디마다 하나: 머리(구), 몸통(반지름 0.13, 앞뒤 납작함은 무시), 골반(0.10), 위팔 · 아래팔(0.045 · 0.04), 넓적다리 · 정강이(0.065 · 0.05), 발(0.04). 각 캡슐은 `segment` 이름(`torso`, `thigh_l` …)을 가진다. 판정은 접촉 부위가 속한 segment 를 겹침에서 뺄 때 이 이름을 쓴다(`PART_SEGMENT` 표).

### 겹침 계산 `penetration()`

`penetration(capsule, box) -> float` 와 `penetration(capsule, capsule) -> float`: 파고든 깊이(m, 떨어져 있으면 0). 판정(04)과 장소 모듈 시험(03)이 함께 쓴다. 판정 규칙(무엇을 빼고 몇 cm 부터 짚나)은 04 가 정하고, 01 은 깊이만 잰다.

### 박자마다 좌표 `frames(scene, room, project=None) -> Frames`

1. `stage.state_at` 과 `stage.layouts`(일감 1-1, PR #163: 박자마다 앞 박자 좌표를 `place` 의 `prev` 로 넘긴다)로 평면 좌표를 얻는다. 2D 판정과 같은 값이고 그림만의 보정은 없다. #163 이 병합되기 전이면 `place` 를 박자마다 부르고, 병합 뒤 `layouts` 로 바꾼다.
2. 인물마다 자세 모듈을 찾는다. 없으면 그 인물은 `body = None`, `missing = 자세 id` 로 두고 넘어간다.
3. 공통 배치: 자리가 기준점 `on` · `in` 이고 자세 `surface` 에 `seat` · `lie` · `top` 이 있으면 그 면 높이에서, 아니면 바닥에서 시작한다. `shift` 를 향한 쪽으로 더한다. `place_hook` 이 있으면 그 결과를 쓴다.
4. FK 로 관절을 구한 뒤, 이어지는 접촉마다 손 IK 를 두 번 푼다(두 사람이 서로 손을 뻗을 때). 고개는 향함 대상(인물이면 머리, 기준점이면 윗면)을 본다(좌우 70°, 위아래 35°).
5. 결과 모양 (`Frames.to_dict()` 가 JSON 으로 내는 것, 렌더러 계약):

```json
{"ceiling": 2.4,
 "solids": [{"anchor": "a1", "box": [x0, y0, z0, x1, y1, z1], "solid": true}],
 "beats": [{"k": 0,
   "bodies": {"h": {"posture": "chair", "missing": null, "attach": null,
                    "joints": {"pelvis": [x, y, z], "neck": […], "head": […], "shoulder_l": […], "elbow_l": […], "wrist_l": […], "hand_l": […],
                               "hip_l": […], "knee_l": […], "ankle_l": […], "toe_l": […], "…_r": […]}}},
   "contacts": [{"id": "c1", "who": "d", "to": "h", "part": "wrist_l", "hands": ["r"], "gap": 0.642, "points": [[…], […]]}]}]}
```

`solids` 의 상자는 기준점 `rot` 을 반영한 세계 좌표의 축 맞춤 상자다(`rot` 은 90° 단위라 축 맞춤으로 충분하다).

## 규칙

- 같은 입력이면 같은 결과(난수 없음).
- 한 장면(인물 4명, 박자 20개) `frames` 가 50ms 안(제안값, 시험에서 잰다).
- `frames` 는 장면 · 방을 바꾸지 않는다.

## 화면 · 명령줄 · 프롬프트

없음. 프롬프트에 넣지 않는다(3D 좌표는 AI 가 읽지 않는다, README 의 좌표 결정).

## 시험

- `tests/test_stage3d_body.py`
  - 모든 각도 0 인 선 자세의 머리 꼭대기 높이가 1.72m ± 0.02.
  - FK: 엉덩관절 90° · 무릎 90° 이면 발목이 골반 앞 0.44m, 아래 0.46m.
  - IK: 팔 길이 안의 목표는 틈 0.01m 안, 밖의 목표는 팔이 곧고 틈 > 0. 팔꿈치가 pole 쪽 반공간에 있다(부호 시험).
  - 숙이기: 틈이 0.1m 인 목표는 숙인 뒤 틈 0, 숙임은 `reach.lean` 을 넘지 않는다. 누운 자세(pitch ≠ 0)는 숙이지 않는다.
  - `PART_POINTS` 가 `stage.PARTS` 의 모든 id 를 덮는다. `PART_SEGMENT` 도 같다.
  - `furniture.solids`: `rot` 0 · 90 · 180 · 270 에서 등받이가 앞의 반대쪽에 온다.
  - `penetration`: 떨어진 캡슐 · 상자는 0, 반지름만큼 겹치면 그 깊이.
  - `frames`: 가짜 자세 · 장소로 장면 하나를 돌려 모양(위 JSON 키)을 본다. 자세 모듈이 없는 인물은 `missing` 이다.
- `tests/test_stage3d_contract.py`: 등록부의 자세마다 `id in stage.POSTURES`, 각도 범위(−180~180), 바닥 면 자세는 FK 의 가장 낮은 관절이 −0.02m 위. 등록부의 장소마다 `template in stage.ROOMS`, 틀의 기준점 이름이 모두 모양을 갖거나 종류 기본값이 있다, `sit` 참이면 `seat`, `lie` 참이면 `lie` 높이가 있다. `test_registry_complete` 는 빠진 자세 · 틀이 있으면 그 목록을 사유로 건너뛴다(연결 일감 07 이 엄격하게 바꾼다).
- 전체 시험: `CANON_HOME=$(mktemp -d) python -m pytest -q tests`.

## 문서

AGENTS.md 의 구조 표에 `canon/stage3d/` 줄(공통 · 자세 · 장소 · 판정 폴더 설명). 이 폴더 README 의 상태 표.

## 확인하지 못할 것

없음(순수 계산, LLM 없음).

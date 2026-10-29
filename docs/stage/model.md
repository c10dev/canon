# 장면 연출 데이터

스키마 이름은 제안이다. 일감 01 에서 확정하고 이 문서를 고친다. LLM 이 채우는 스키마에는 dict 필드를 쓰지 않는다(AGENTS.md).

## 저장 자리

| 자리 | 형식 | 이유 |
|---|---|---|
| `Project.rooms: list[Room]` | 방 목록 | 방은 여러 화 · 장면이 다시 쓴다 |
| `Episode.stage: list[StageScene]` | 그 화의 장면 목록 | 플롯이 `Episode.plot` 에 있으므로 화 끼워 넣기 · 빼기(`renumber`)가 화와 함께 옮긴다 |
| `Settings.stage_extract: bool = False` | 검수 때 함께 뽑기 | `Settings.check_widen` 과 같은 모양 |

옛 `project.json` 은 빈 목록 · 거짓 기본값으로 읽힌다.

## 방

```
Room
  id: str                 # "r1" …
  name: str               # "하린의 방"
  place: str = ""         # 지도 장소 이름(atlas.places). 비면 장면 전용 방
  template: str = ""      # 고른 틀 id (bedroom, living, classroom, office, car, carriage, …)
  w: float, h: float      # 방 크기 m (틀 기본값, 작가가 고침)
  anchors: list[Anchor]

Anchor                    # 기준점: 가구 · 문 · 창
  id: str                 # "a1" …
  name: str               # "침대", "문", "창", "책상"
  kind: str               # bed · door · window · desk · chair · sofa · table · wall · seat · other
  x, y, w, h: float       # 방 안 m, 왼쪽 위 기준
  rot: int = 0            # 0 · 90 · 180 · 270
  sit: bool, lie: bool    # 앉을 수 · 누울 수 있는 기준점 (틀 기본값)
```

틀은 `canon/stage.py` 의 `ROOMS` 에 둔다. 장면 전용 방은 `place` 가 비고 장면 하나만 가리킨다. '장소에 묶기'는 `place` 를 채운다.

## 장면

```
StageScene
  id: str
  event: int              # 플롯 사건 번호 (0부터)
  event_text: str         # 사건 글 사본. 사건 찾기에 쓴다
  room: str               # Room.id
  cast: list[str]         # 인물 id
  start: list[StageBody]  # 시작 상태: 인물마다 모든 칸
  beats: list[StageBeat]
  source: "manual" | "plot" | "text"   # 마지막으로 통째 적용한 출처
  basis: str = ""         # 본문에서 뽑았을 때 본문 지문(pipeline.text_basis)
  prompt: bool = True     # 쓰기 프롬프트에 넣기
  prev: StageScene | None # 마지막 AI 적용 전 장면 (적용 취소 한 번)

StageBeat
  quote: str = ""         # 본문 문장 원문 (쓰기 전에는 빈칸)
  note: str = ""          # 작가 한 줄 설명 ("하린이 문을 열고 들어온다")
  bodies: list[StageBody] # 바뀐 인물만. 적지 않은 칸은 앞 박자 그대로

StageBody
  who: str                # 인물 id
  at: Spot | None
  posture: str = ""       # POSTURES id
  facing: str = ""        # 8방향(n ne e se s sw w nw) 또는 "@<인물 id>" · "#<기준점 id>"
  left: Hand | None
  right: Hand | None
  contacts: list[Contact] # 이 박자에 새로 시작한 접촉. 끝난 접촉은 ends 로
  ends: list[str] = []    # 끝난 Contact.id
  memo: str = ""          # 목록 밖 자유 메모

Spot
  ref: str                # 기준점 id 또는 "@<인물 id>"
  rel: str                # on · front · back · left · right · beside · in

Hand
  holds: str = ""         # 쥔 물건 이름. 비면 빈손
  contact: str = ""       # 이 손이 맡은 Contact.id

Contact
  id: str
  by: str                 # left · right · both · 부위 id (입술, 이마 …)
  to: str                 # 인물 id
  part: str               # PARTS id
  act: str                # ACTS id
```

LLM 출력용 `StageDraft` 는 같은 모양에서 id 대신 이름을 쓴다(인물 이름, 기준점 이름). `stage.clean` 이 이름을 id 로 바꾸고, 목록 밖 값을 `memo` 로 옮기고, 막는 접촉을 뺀다.

## 고정 어휘

목록은 `canon/stage.py` 에 두고 화면은 서버가 준 목록을 쓴다(JS 에 두 번 적지 않는다).

**부위 `PARTS`** (쌍은 `_l` · `_r`): 머리, 머리카락, 이마, 눈, 뺨, 귀, 입술, 턱, 목, 목덜미, 어깨, 위팔, 팔꿈치, 손목, 손, 손가락, 가슴, 배, 옆구리, 등, 허리, 엉덩이, 사타구니, 허벅지, 무릎, 종아리, 발목, 발. 각 부위는 `side`(front · back · both)와 `sexual`(가슴 · 엉덩이 · 사타구니 · 허벅지 안쪽 계열 참)을 가진다.

**자세 `POSTURES`** (12): 서기, 걷기, 뛰기, 기대 서기, 의자에 앉기, 바닥에 앉기, 쪼그려 앉기, 무릎 꿇기, 눕기(등), 옆으로 눕기, 엎드리기, 안기거나 업힘. 각 자세는 `upright`(서기 · 걷기 · 뛰기 · 기대 서기 참)를 가진다.

**향함**: 방 기준 8방향, 또는 인물 · 기준점을 향함. 화면은 인물을 향함을 기본으로 보인다.

**접촉 동작 `ACTS`** (약 30): 스치다, 짚다, 잡다, 움켜쥐다, 끌어당기다, 밀다, 치다, 붙들다, 쓰다듬다, 토닥이다, 감싸다, 안다, 끌어안다, 업다, 받치다, 기대다, 머리를 기대다, 입 맞추다, 깨물다, 핥다, 문지르다, 주무르다, 닦아 주다, 매만지다(옷 · 머리), 손깍지 끼다, 팔짱 끼다, 어깨동무하다, 목을 조르다, 비틀다, 애무하다. 각 동작은 `hands`(필요한 손 수 0 · 1 · 2), `sexual`, 그리고 삽화 태그 이름(2차, `IllustCharacter.action` 의 `source#hug` 꼴)을 가진다.

`sexual` 접촉 = 부위나 동작 중 하나가 `sexual`. 이 표시는 미성년 막기와 전연령 프롬프트 빼기에만 쓴다.

## 위치 계산

`stage.place(room, bodies) -> {who: (x, y)}` 는 Python 과 JS(`stageLayout`)에 같은 규칙으로 둔다(node 시험으로 맞춰 본다, `tests/test_stage_js.py`).

1. 기준점 위치: `rel` 이 on · in 이면 기준점 안 가운데, front · back · left · right 는 기준점 `rot` 을 따른 그 쪽 바깥 0.4m, beside 는 가장 가까운 빈 옆.
2. 인물 기준(`@id`)은 그 인물 좌표에서 같은 규칙, 몸 반지름 0.25m.
3. 같은 자리에 둘 이상이면 0.5m 간격으로 나란히 편다(순서는 `cast` 순서).
4. 인물 기준이 고리를 이루면 고리 첫 인물을 방 가운데에 둔다.

작가가 평면도에서 인물을 끌어 놓으면 화면은 가장 가까운 기준점과 관계로 바꿔 저장한다(`stageSnap`). 끌어 놓은 정확한 자리는 저장하지 않는다.

## 검수 규칙 (1차)

판정은 `stage.judge(scene, room, project) -> list[Violation]` 이고 LLM 을 부르지 않는다. 박자를 차례로 겹쳐 상태를 만들고, 박자마다 아래를 본다. `Violation` 은 박자 번호, 그 상태를 만든 박자(`cause`, 시작 상태면 -1), 인물, 규칙, 해요체 설명이다.

| 규칙 id | 판정 | 비고 |
|---|---|---|
| `hand_busy` | 한 손이 물건을 쥐었거나 접촉을 맡은 채 다른 물건 · 접촉을 맡는다. `both` 접촉은 두 손을 다 쓴다 | 손 상태가 `?`(모름)면 짚지 않는다 |
| `move_posture` | 자리(`at`)가 바뀐 박자에 자세가 `upright` 가 아니다. 안기거나 업힘이면 업은 사람이 `upright` 인지 본다 | 같은 박자에 자세도 서기로 바꿨으면 통과 |
| `reach` | 손 접촉의 두 사람 좌표 거리가 1.2m 를 넘는다. 손 아닌 부위 접촉은 0.6m | 제안값: 팔 길이 약 0.7m + 몸 반지름 둘. 시험 장면으로 고친다 |
| `behind_front` | 손 쓴 사람이 대상의 등 뒤 반원(대상 향함 기준 ±90° 밖)에 있는데 부위 `side` 가 front 다 | 향함을 모르면 짚지 않는다 |
| `handoff` | 한 손에 쥔 물건을 놓는 박자 없이 다른 손이 같은 물건을 쥔다 | shadowcast 규칙 이름과 같다 |

시작 상태의 손은 쓰기 전 연출이면 빈손, 본문에서 뽑았으면 본문이 말하기 전까지 `?` 다(DESIGN.md shadowcast 계획의 `?` 손 규칙과 같다).

## 막기

`stage.blocked(contact, project) -> bool`: 접촉이 `sexual` 이고 두 인물 중 하나가 `cast.is_minor_age` 면 참. `clean`(AI 결과), 웹 저장(작가 입력), 프롬프트 블록 세 곳이 이 함수로 거른다. 화면은 미성년이 낀 접촉에서 `sexual` 부위 · 동작을 고를 수 없게 감춘다.

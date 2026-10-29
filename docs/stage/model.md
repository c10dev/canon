# 장면 연출 데이터

스키마는 일감 01 에서 `canon/schema.py` 에 넣었다(아래와 같다). LLM 이 채우는 스키마에는 dict 필드를 쓰지 않는다(AGENTS.md).

## 저장 자리

| 자리 | 형식 | 이유 |
|---|---|---|
| `Project.rooms: list[StageRoom]` | 방 목록 | 방은 여러 화 · 장면이 다시 쓴다 |
| `Episode.stage: list[StageScene]` | 그 화의 장면 목록 | 플롯이 `Episode.plot` 에 있으므로 화 끼워 넣기 · 빼기(`renumber`)가 화와 함께 옮긴다 |
| `Settings.stage_extract: bool = False` | 검수 때 함께 뽑기 | `Settings.check_widen` 과 같은 모양 |

옛 `project.json` 은 빈 목록 · 거짓 기본값으로 읽힌다.

## 방

```
StageRoom
  id: str                 # "r1" …
  name: str               # "하린의 방"
  place: str = ""         # 지도 장소 이름(atlas.places). 비면 장면 전용 방
  template: str = ""      # 고른 틀 id (bedroom, living, classroom, office, car, carriage, …)
  w: float, h: float      # 방 크기 m (틀 기본값, 작가가 고침)
  anchors: list[StageAnchor]

StageAnchor               # 기준점: 가구 · 문 · 창
  id: str                 # "a1" …
  name: str               # "침대", "문", "창", "책상"
  kind: str               # bed · door · window · desk · chair · sofa · table · wall · seat · other
  x, y, w, h: float       # 방 안 m, 왼쪽 위 기준
  rot: int = 0            # 앞쪽: 0 아래(+y) · 90 왼쪽 · 180 위 · 270 오른쪽. 아래 벽의 문은 180
                          # 의자 · 자리 · 소파의 앞은 마주 보는 가구 쪽 (침실 의자는 오른쪽 책상을 봐서 270)
  sit: bool, lie: bool    # 앉을 수 · 누울 수 있는 기준점 (틀 기본값)
```

틀은 `canon/stage.py` 의 `ROOMS`(침실 · 거실 · 교실 · 사무실 · 차 안 · 마차 안 · 빈 방)에 두고 `make_room` 으로 만든다. 장면 전용 방은 `place` 가 비고 장면 하나만 가리킨다. '장소에 묶기'는 `place` 를 채운다.

## 장면

```
StageScene
  id: str
  event: int              # 플롯 사건 번호 (0부터)
  event_text: str         # 사건 글 사본. 사건 찾기에 쓴다
  room: str               # StageRoom.id
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
  at: StageSpot | None    # None 은 앞 그대로
  posture: str = ""       # POSTURES id. 빈칸은 앞 그대로
  facing: str = ""        # 8방향(n ne e se s sw w nw) 또는 "@<인물 id>" · "#<기준점 id>"
  left: str | None        # 왼손에 쥔 것. "" 빈손, "?" 모름, None 앞 그대로
  right: str | None
  contacts: list[StageContact]  # 이 박자에 새로 시작한 접촉. 끝난 접촉은 ends 로
  ends: list[str] = []    # 끝난 StageContact.id
  memo: str = ""          # 목록 밖 자유 메모

StageSpot
  ref: str                # 기준점 id 또는 "@<인물 id>"
  rel: str                # on · in · front · back · left · right · beside · across · against

StageContact
  id: str
  by: str                 # left · right · both · 부위 id (입술, 이마 …)
  to: str                 # 인물 id
  part: str               # PARTS id
  act: str                # ACTS id
```

LLM 출력용 `StageDraft` 는 같은 모양에서 id 대신 이름을 쓴다(인물 이름, 기준점 이름). 일감 03 의 정리 함수가 이름을 id 로 바꾼 뒤 `stage.clean_scene` 을 부른다. `clean_scene` 은 목록 밖 자세 · 향함 · 자리와 모르는 부위 · 동작 접촉을 `memo` 로 옮기고, 막는 접촉을 빼고, 접촉 id 를 겹치지 않게 단다. 작가 입력 저장(일감 02)도 같은 함수를 쓴다.

## 고정 어휘

목록은 `canon/stage.py` 에 두고 화면은 서버가 준 목록을 쓴다(JS 에 두 번 적지 않는다).

**부위 `PARTS`** (쌍은 `_l` · `_r`): 머리, 머리카락, 이마, 눈, 뺨, 귀, 입술, 턱, 목, 목덜미, 어깨, 위팔, 팔꿈치, 아래팔, 손목, 손, 손가락, 가슴, 배, 옆구리, 등, 허리, 엉덩이, 사타구니, 허벅지, 무릎, 종아리, 발목, 발. 각 부위는 `side`(front · back · both)와 `sexual`(가슴 · 엉덩이 · 사타구니 · 허벅지 안쪽 계열 참)을 가진다.

**자세 `POSTURES`** (12): 서기, 걷기, 뛰기, 기대 서기, 의자에 앉기, 바닥에 앉기, 쪼그려 앉기, 무릎 꿇기, 눕기(등), 옆으로 눕기, 엎드리기, 안기거나 업힘. 각 자세는 `upright`(서기 · 걷기 · 뛰기 · 기대 서기 참)를 가진다.

**향함**: 방 기준 8방향, 또는 인물 · 기준점을 향함. 화면은 인물을 향함을 기본으로 보인다.

**접촉 동작 `ACTS`** (약 30): 스치다, 짚다, 잡다, 움켜쥐다, 끌어당기다, 밀다, 치다, 붙들다, 쓰다듬다, 토닥이다, 감싸다, 안다, 끌어안다, 업다, 받치다, 기대다, 머리를 기대다, 입 맞추다, 깨물다, 핥다, 문지르다, 주무르다, 닦아 주다, 매만지다(옷 · 머리), 손깍지 끼다, 팔짱 끼다, 어깨동무하다, 목을 조르다, 비틀다, 애무하다. 각 동작은 `hands`(보통 쓰는 손 수 0 · 1 · 2), `sexual`(동작 자체가 성적: 핥다 · 애무하다), `intimate`(성적 부위에 닿으면 성적: 쓰다듬다 · 감싸다 · 입 맞추다 · 깨물다 · 문지르다 · 주무르다 · 움켜쥐다), `support`(몸무게를 받친다: 안다 · 끌어안다 · 업다 · 받치다 · 기대다 · 머리를 기대다. DECO 의 받침 구분)를 가진다. 삽화 태그 이름(`IllustCharacter.action` 의 `source#hug` 꼴)은 2차에 더한다.

성적 접촉(`stage.is_sexual`) = 동작이 `sexual` 이거나, 동작이 `intimate` 이고 부위가 `sexual`. 가슴을 미는 접촉은 성적 접촉이 아니다. 이 표시는 미성년 막기와 전연령 프롬프트 빼기에만 쓴다.

## 위치 계산

기준틀(ISO-Space OLINK 이름): 기준점의 앞 · 뒤는 기준점 자신의 앞(`rot`, 내재)이고, 왼쪽 · 오른쪽은 그 앞에 서서 바라본 쪽(상대)이다. 인물 기준(`@id`)은 그 인물이 향한 쪽을 따른다(내재: 본문의 "그의 왼쪽"). 방 기준(절대)은 향함의 8방향에만 쓴다. AI 추출(일감 03)도 이 규칙으로 적는다.

`stage.place(room, state, order, prev) -> {who: (x, y)}` 는 Python 과 JS(`stageLayout`)에 같은 규칙으로 둔다(node 시험으로 맞춰 본다, `tests/test_stage_js.py`). `prev` 는 앞 박자 좌표다. 박자마다 좌표는 `stage.layouts(room, scene)`(JS `stageLayouts`)가 시작 상태부터 차례로 앞 박자 좌표를 넘겨 계산하고, 판정(`judge`)과 평면도가 이 값을 쓴다.

1. 기준점 위치: `rel` 이 on · in 이면 기준점 가운데, front · back · left · right 는 기준점 `rot` 을 따른 그 쪽 바깥 0.4m(`GAP`). 왼쪽 · 오른쪽은 기준점 앞에 서서 바라본 쪽이다. beside 는 오른쪽과 같고, 겹치면 3번이 편다. across(맞은편)는 뒤와 같은 자리다(책상 건너편). against(기대어 맞닿음)는 앞쪽에 몸 반지름만큼만 떨어진다(벽 · 문에 기댐, `기대 서기` 와 짝).
2. 인물 기준(`@id`): 그 인물이 향한 쪽 기준 앞 · 뒤 · 왼쪽 · 오른쪽으로 0.55m(몸 반지름 0.25m 둘 + 0.05m). 왼쪽 · 오른쪽은 그 인물의 왼쪽 · 오른쪽이다. 기준 인물이 나를 향하는데(`@나`) 내 자리를 아직 모르면, 앞 박자의 내 좌표 쪽을 그 인물의 앞으로 친다(서로를 기준으로 삼는 순환. 예: 하린이 '@도윤 앞'으로 가고 도윤이 하린을 향하면 하린은 앞 박자 자리 쪽으로 한 걸음 거리에 선다). 앞 박자에 내 자리도 없거나 향함을 모르면 아래를 본다고 친다. on · in(안김 · 업힘)은 0.15m 옆. across 는 향한 쪽으로 1.2m(`ACROSS`, 마주 봄), against 는 향한 쪽으로 0.5m(몸이 맞닿음).
3. 같은 기준점 · 관계에 둘 이상이면 기준점 앞쪽에 수직으로 0.5m(`SPREAD`) 간격으로 번갈아 편다(순서는 `cast` 순서).
4. 인물 기준이 고리를 이루면 고리 첫 인물을 방 가운데에 둔다.
5. 모든 좌표는 벽에서 몸 반지름 안쪽으로 자른다.

작가가 평면도에서 인물을 끌어 놓으면 화면은 가장 가까운 기준점과 관계로 바꿔 저장한다(`stageSnap`). 끌어 놓은 정확한 자리는 저장하지 않는다.

## 검수 규칙 (1차)

판정은 `stage.judge(scene, room, project) -> list[Violation]` 이고 LLM 을 부르지 않는다. 박자를 차례로 겹쳐 상태를 만들고, 박자마다 아래를 본다. `Violation` 은 박자 번호(1부터), 그 상태를 만든 박자(`cause`, 시작 상태면 0), 인물, 규칙, 해요체 설명, 접촉 id(`contact`)다. `contact` 는 reach · behind_front 이면 그 접촉, hand_busy 이면 이번 박자에 그 손으로 시작한 접촉(물건만 새로 쥐었으면 빈칸)이고, 다른 규칙은 빈칸이다. 평면도는 `contact` 가 가리키는 접촉 선만 빨갛게 그린다(한 박자에 두 접촉을 시작해 하나만 어긋나도 둘 다 빨갛지 않게).

| 규칙 id | 판정 | 비고 |
|---|---|---|
| `hand_busy` | 이번 박자에 손에 새로 맡긴 것이 있는데, 그 손이 쥔 물건과 그 손 · 두 손 접촉이 둘 이상이다 | `?`(모름) 손은 쥔 것으로 세지 않는다 |
| `move_posture` | 자리(`at`)가 바뀐 박자에 자세가 `upright` 가 아니다. 안기거나 업힘이면 선 인물이 이 인물에게 받침 접촉(`ACTS` 의 `support`)을 하고 있는지 본다 | 같은 박자에 자세도 서기로 바꿨으면 통과. 앞 자리를 모르면 짚지 않는다 |
| `reach` | 이번 박자에 시작한 손 접촉의 두 사람 좌표 거리가 1.2m(`REACH_HAND`)를 넘는다. 손 아닌 부위 접촉은 0.6m(`REACH_BODY`) | 제안값(2026-10-29 사용자 승인): 팔 길이 약 0.7m + 몸 반지름 둘. 일감 03 시험 장면으로 고친다 |
| `behind_front` | 손 쓴 사람이 대상의 등 뒤 반원(대상 향함 기준 ±90° 밖)에 있는데 부위 `side` 가 front 다 | 향함을 모르면 짚지 않는다 |
| `handoff` | 한 손에 쥔 물건을 놓지 않은 채 같은 박자에 다른 손이 같은 물건을 쥔다. 같은 박자에 놓으면(빈칸) 건네 쥔 것이라 통과 | shadowcast 규칙 이름과 같다 |

시작 상태의 손은 쓰기 전 연출이면 빈손, 본문에서 뽑았으면 본문이 말하기 전까지 `?` 다(DESIGN.md shadowcast 계획의 `?` 손 규칙과 같다).

## 막기

`stage.blocked(contact, who, project) -> bool`: 접촉이 성적 접촉(`is_sexual`)이고 두 인물 중 하나가 `cast.is_minor_age` 면 참. `clean_scene`(AI 결과와 작가 입력)과 프롬프트 블록(일감 05)이 이 함수로 거른다. 화면은 미성년이 낀 접촉에서 `sexual` 부위 · 동작을 고를 수 없게 감춘다.

## 사건 찾기 · 본문과 잇기

- `find_event(ep, scene) -> (번호 | None, 바뀌었나)`: 사건 글이 같은 사건이 있으면 그 번호(바뀌지 않음). 없으면 저장한 번호의 사건(바뀜). 그 번호도 없으면 None(바뀜). 장면은 지우지 않는다.
- `stale(scene, text) -> [박자 번호]`: 인용이 본문에 없는 박자. 띄어쓰기 차이는 무시한다.

# 장면 연출 데이터

스키마는 일감 01 에서 `canon/schema.py` 에 넣었다(아래와 같다). LLM 이 채우는 스키마에는 dict 필드를 쓰지 않는다(AGENTS.md).

## 저장 자리

| 자리 | 형식 | 이유 |
|---|---|---|
| `Project.rooms: list[StageRoom]` | 방 목록 | 방은 여러 화 · 장면이 다시 쓴다 |
| `Episode.stage: list[StageScene]` | 그 화의 장면 목록 | 플롯이 `Episode.plot` 에 있으므로 화 끼워 넣기 · 빼기(`renumber`)가 화와 함께 옮긴다 |
| `Settings.stage_extract: bool = True` | 검수 때 함께 뽑기 (두 역할 결정으로 기본 켬) | `Settings.check_widen` 과 같은 모양 |

옛 `project.json` 은 빈 목록 · 거짓 기본값으로 읽힌다.

### 스토리보드와의 관계 (일감 08)

화별 스토리보드(`Episode.storyboard`, `canon/board.py`)와 장면 연출은 데이터를 따로 둔다. 장면 연출은 읽기만 하고 스토리보드에 아무것도 쓰지 않는다. 스토리보드도 장면 연출을 읽지 않는다.

- 잇는 열쇠는 플롯 사건 번호다. `StageScene.event`(0부터)와 `BoardScene.events`(1부터)가 같은 사건을 가리키면 그 스토리보드 장면이 그 사건을 맡는다(`stage.board_scene_of`). 스토리보드 장면 번호는 저장하지 않는다(다시 만들면 바뀐다).
- 새 장면의 출연진은 맡은 스토리보드 장면의 `present` 중 인물 목록에 있는 id 다. 비면 플롯 등장 인물이다(`stage.new_scene`).
- 방 후보(`stage.room_hints`): 이름이 `spot` 과 같은 방 → `spot` 과 서로 포함하는 방 → `StageRoom.place` 가 `place` 와 같은 방 → 이름이 `place` 와 서로 포함하는 방. 띄어쓰기 · 가운뎃점은 무시한다.
- 화면 값(`stage.view` 의 `board`, `board_view`): `stale`(`board.stale`) 과 사건마다 `{no, place, spot, hints}` 또는 `null`. 스토리보드가 없으면 `events` 가 빈 목록이다.

## 방

```
StageRoom
  id: str                 # "r1" …
  name: str               # "하린의 방"
  place: str = ""         # 지도 장소 이름(atlas.places). 비면 장면 전용 방
  template: str = ""      # 고른 틀 id (bedroom, living, classroom, office, car, carriage, empty, car_side, outdoor)
  w: float, h: float      # 방 크기 m (틀 기본값, 작가가 고침)
  anchors: list[StageAnchor]
  attached: bool = False  # 옛 방 짐작(stage.attach_guess)을 마친 방 (일감 09)

StageAnchor               # 기준점: 가구 · 문 · 창
  id: str                 # "a1" …
  parent: str = ""        # 붙은 곳: 기준점 id, 방 벽이면 "room" (일감 09). 붙으면 x · y · w · h · rot 는 부모 기준
  face: str = ""          # 기준점이면 inside · top · front · back · left · right, 방 벽이면 n · e · s · w
  name: str               # "침대", "문", "창", "책상"
  kind: str               # bed · door · window · desk · chair · sofa · table · wall · seat · other
  x, y, w, h: float       # 방 안 m, 왼쪽 위 기준
  rot: int = 0            # 앞쪽: 0 아래(+y) · 90 왼쪽 · 180 위 · 270 오른쪽. 아래 벽의 문은 180
                          # 의자 · 자리 · 소파의 앞은 마주 보는 가구 쪽 (침실 의자는 오른쪽 책상을 봐서 270)
  sit: bool, lie: bool    # 앉을 수 · 누울 수 있는 기준점 (틀 기본값)
```

틀은 `canon/stage.py` 의 `ROOMS`(침실 · 거실 · 교실 · 사무실 · 차 안 · 마차 안 · 빈 방, 야외 틀 차 옆 · 야외 빈터)에 두고 `make_room` 으로 만든다. 장면 전용 방은 `place` 가 비고 장면 하나만 가리킨다. '장소에 묶기'는 `place` 를 채운다.

### AI 가 더하는 기준점 (`stage.place_anchors`)

플롯 초안(`StageDraft.new_anchors`, `DraftAnchor`: 이름 · 종류 · `near` · `rel`)은 방에 없는 장소를 더하자고 할 수 있다. 좌표는 코드가 정한다.

1. `near` 가 방에 있거나 앞 제안이면 그 `rel` 쪽 곁(기준틀은 `_anchor_point` 와 같다). 창 · 문 · 벽(`ATTACH`)은 맞붙이고 앞쪽이 `near` 의 반대쪽(바깥)이다: 운전석 곁 창의 앞은 창밖에 선 자리다. 그 밖은 `ANCHOR_GAP` 1.35m(두 기준점의 맞보는 앞자리에 선 두 사람이 겹치지 않는 틈) 떨어지고 앞쪽이 `near` 를 본다.
1-2. AI 장면이 사람을 창 · 문 · 벽(`ATTACH`) 위(on) · 안(in)에 세우면 그 앞(front)으로 읽는다(`stage.from_draft`). 15화 초안이 '운전석 창 바깥' 위에 세워 몸이 차 옆면에 걸렸다.
1-3. 붙은 기준점 (일감 09, [specs/09-attach.md](specs/09-attach.md)): 차 안 자리 · 차 옆면 창 · 문은 차에 붙고(`parent` · `face`), `part` 가 참인 제안은 `near` 안의 `rel` 쪽 끝 구역(폭은 near 를 채우고 깊이는 길이의 1/3, 많아야 2.5m, 앞쪽은 그 끝 바깥)이나 `rel` 쪽 면(창 · 문 · 벽)에 붙는다. 방을 넓힐 때는 뿌리와 벽 기준점만 옮긴다(`shift_room`). 벽 기준점은 풀 때 늘 그 벽에 맞추므로 방을 아래 · 오른쪽으로 넓혀도 떨어지지 않는다.
1-1. 차 안 (2026-10-29, 15화에서 운전석 · 창이 캠핑카 밖에 놓였다): `near` 가 차(vehicle)인 자리(seat)는 그 차 안 운전 칸에 놓는다(`_in_vehicle`: 차 앞 끝에서 `CAB_SEAT` 1.3m 뒤, 안에서 앞을 보고 왼쪽(운전석) 먼저 · 오른쪽 · 뒷줄, 자리 앞은 차 앞). 차의 앞(rot)은 긴 쪽이다. `near` 가 차 안 자리이거나 차인 창 · 문은 차 옆면에 붙인다(`_on_vehicle_wall`: 자리 앞뒤 높이에, 자리에 가까운 옆면 먼저 · 맞은편, 앞은 바깥). 차 안인지는 `stage.container`(가운데를 품은 차). 3D 는 자리를 품은 차(장소 모듈이 모양을 정하지 않은 것)의 앞 `CAB` 1.9m 를 비우고 옆판 · 계기판 · 지붕만 둔다(`stage3d.furniture.shape` · `cab_vehicle`, 창 높이 1.0~1.75m 는 열림).
2. 기준점이나 그 앞자리(`GAP` + 몸 반지름)가 다른 기준점 · 앞자리와 겹치면 관계 쪽과 수직으로 0.5m씩 밀고, 그래도 겹치면 바깥으로 민다.
3. `near` 가 없거나 모르면 방 안 빈 자리(다른 기준점과 `ROOM_PAD`), 없으면 방 오른쪽 바깥.
4. 더한 기준점 둘레 0.9m(`ROOM_PAD`: 앞자리 0.4 + 몸 반지름 0.25 + 걸음 0.25)가 방 밖이면 방을 넓힌다(한 변 40m 까지). 왼쪽 · 위로 넓히면 옛 기준점을 그만큼 옮긴다(`StageProposal.shift_x` · `shift_y`).
5. 크기는 종류 기본값(`ANCHOR_SIZES`, 종류는 `ANCHOR_KINDS` 와 같다), 모르는 종류는 other. 같은 이름은 건너뛰고 한 번에 10개(`MAX_ADDS`)까지. 넘은 기준점은 정리 기록에 이름을 적는다(`pipeline._stage_ask`). 6개였을 때 차 안 자리 · 창으로 6개를 채워 정비차가 말없이 빠졌다(2026-10-29 15화).

`StageProposal`: 새 방이면 `room` 에 이미 더해져 있고, 이미 있는 방이면 `grown`(더하고 넓힌 모습, id 그대로)과 `adds`(기준점과 자리 말 `where`)를 든다. 적용(`pipeline.apply_stage(…, shared)`)은 적용 때의 방에 다시 더한다(`stage.grow_room`, 그사이 작가가 고친 방을 지키고 겹친 id 는 새 id 로 바꿔 장면도 고침). 공용 방(`stage.room_shared`: 장소에 묶였거나 다른 사건의 장면이 씀)이면 복사한 장면 전용 방 '이름 · n화 사건 k' 에 더하고, `shared` 면 그 방에 바로 더한다. 장면에는 `room_prev`(바꾼 방의 적용 전 모습)와 `room_made`(만든 방 id)를 남기고, 적용 취소(`undo_stage`)가 방을 되돌리거나 다른 장면이 쓰지 않는 만든 방을 뺀다.


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
  role: "plan" | "text" = "plan"   # 계획 장면(쓰기 전) · 본문 장면(본문에서 뽑음). 한 사건에 역할마다 하나
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

LLM 출력용 `StageDraft` 는 같은 모양에서 id 대신 이름을 쓴다(인물 이름, 기준점 이름). 자리는 평평한 두 칸(`DraftBody.at_ref` · `at_rel`), 손은 빈칸이 앞 그대로 · '빈손' · '?', 끝난 접촉은 대상 이름 + 부위(`DraftEnd`)다. `stage.from_draft` 가 이름을 id 로 바꾼 뒤 `stage.clean_scene` 을 부른다. `cast` · `start` · `beats` · `new_anchors` 는 기본값 없는 필수 칸이다(기본값이 있으면 Gemini 가 박자를 건너뛴다, 03 명세서 '측정'). `clean_scene` 은 목록 밖 자세 · 향함 · 자리와 모르는 부위 · 동작 접촉을 `memo` 로 옮기고, 막는 접촉을 빼고, 접촉 id 를 겹치지 않게 단다. 작가 입력 저장(일감 02)도 같은 함수를 쓴다.

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
2. 인물 기준(`@id`): 그 인물이 향한 쪽 기준 앞 · 뒤 · 왼쪽 · 오른쪽으로 0.55m(몸 반지름 0.25m 둘 + 0.05m). 왼쪽 · 오른쪽은 그 인물의 왼쪽 · 오른쪽이다. 기준 인물이 나를 향하는데(`@나`) 내 자리를 아직 모르면, 앞 박자의 내 좌표 쪽을 그 인물의 앞으로 친다(서로를 기준으로 삼는 순환. 예: 하린이 '@도윤 앞'으로 가고 도윤이 하린을 향하면 하린은 앞 박자 자리 쪽으로 한 걸음 거리에 선다). 이때 관계 말이 앞 · 뒤 · 왼쪽 · 오른쪽 무엇이든 앞 박자 쪽에 선다(관계 말을 따르면 박자마다 90도씩 돈다, 2026-10-29 15화 사건 1). 앞 박자에 내 자리도 없거나 향함을 모르면 아래를 본다고 친다. on · in(안김 · 업힘)은 0.15m 옆. across 는 향한 쪽으로 1.2m(`ACROSS`, 마주 봄), against 는 향한 쪽으로 0.5m(몸이 맞닿음).
3. 같은 기준점 · 관계에 둘 이상이면 기준점 앞쪽에 수직으로 0.5m(`SPREAD`) 간격으로 번갈아 편다(순서는 `cast` 순서).
4. 인물 기준이 고리를 이루면 고리 첫 인물을 방 가운데에 둔다.
5. 모든 좌표는 벽에서 몸 반지름 안쪽으로 자른다.

작가가 평면도에서 인물을 끌어 놓으면 화면은 가장 가까운 기준점과 관계로 바꿔 저장한다(`stageSnap`). 끌어 놓은 정확한 자리는 저장하지 않는다.

## 검수 규칙 (1차)

판정은 `stage.judge(scene, room, project) -> list[Violation]` 이고 LLM 을 부르지 않는다. 박자를 차례로 겹쳐 상태를 만들고, 박자마다 아래를 본다. `Violation` 은 박자 번호(1부터), 그 상태를 만든 박자(`cause`, 시작 상태면 0), 인물, 규칙, 해요체 설명, 접촉 id(`contact`)다. `contact` 는 reach · behind_front 이면 그 접촉, hand_busy 이면 이번 박자에 그 손으로 시작한 접촉(물건만 새로 쥐었으면 빈칸)이고, 다른 규칙은 빈칸이다. 평면도는 `contact` 가 가리키는 접촉 선만 빨갛게 그린다(한 박자에 두 접촉을 시작해 하나만 어긋나도 둘 다 빨갛지 않게).

| 규칙 id | 판정 | 비고 |
|---|---|---|
| `hand_busy` | 이번 박자에 손에 새로 맡긴 것이 있는데, 그 손이 쥔 물건과 그 손 · 두 손 접촉이 둘 이상이다 | `?`(모름) 손은 쥔 것으로 세지 않는다 |
| `move_posture` | 자리(`at`)가 바뀐 박자에 자세가 `upright` 가 아니고, 그 자세가 앞 박자 자세 그대로다(앉은 채로 옮김). 안기거나 업힘이면 선 인물이 이 인물에게 받침 접촉(`ACTS` 의 `support`)을 하고 있는지 본다 | 같은 박자에 자세를 바꿨으면 옮긴 다음 그 자세가 된 것으로 보고 통과("걸어와 앉았다", 2026-10-29 03 측정의 헛지적 4개). 안기거나 업힘으로 바뀐 박자는 이 통과가 없다. 앞 자리를 모르면 짚지 않는다 |
| `reach` | 이번 박자에 시작한 손 접촉의 두 사람 좌표 거리가 1.4m(`REACH_HAND`)를 넘는다. 손 아닌 부위 접촉은 0.6m(`REACH_BODY`) | 처음 1.2m(팔 길이 약 0.7m + 몸 반지름 둘)에서 1.4m 로 올렸다(2026-10-29, [03 '측정'](specs/03-ai.md#측정-2026-10-29-실제-gemini)): 기준점 자리는 가구 바깥 0.4m 라 같은 가구 앞 · 옆에 선 두 사람이 1.2m 를 조금 넘었다. 1.2~1.4m 접촉은 3D `reach3d` 가 숙임 · 비틂까지 넣어 다시 본다(침대 한가운데 앉은 사람을 침대 앞에서 잡기 1.4m 는 3D 가 짚는다, `tests/stage3d_scenes/bad_reach_bed_center.json`). `REACH_BODY` 는 측정 세트에 근거가 없어 그대로 |
| `behind_front` | 손 쓴 사람이 대상의 등 뒤 반원(대상 향함 기준 ±90° 밖)에 있는데 부위 `side` 가 front 다 | 향함을 모르면 짚지 않는다 |
| `handoff` | 한 손에 쥔 물건을 놓지 않은 채 같은 박자에 다른 손이 같은 물건을 쥔다. 같은 박자에 놓으면(빈칸) 건네 쥔 것이라 통과 | shadowcast 규칙 이름과 같다 |

### 3D 규칙 (`stage3d.judge`, 2026-10-29 07 연결)

`stage.judge_all` 이 평면 규칙 뒤에 더한다. 자세 12 · 틀 7 모듈이 다 있을 때만 돈다. 평면 `reach` 가 짚은 접촉은 다시 짚지 않는다. 심각도 · 출처는 평면 규칙과 같다(사소 · 규칙). 좌표는 `stage.layouts` 그대로다.

| 규칙 id | 화면 이름 | 판정 | 문턱 |
|---|---|---|---|
| `reach3d` | 높이 | 이어지는 접촉의 손끝(부위 접촉은 두 부위 점) 틈. 접촉이 시작된 박자와 두 사람 중 하나의 자리 · 자세가 바뀐 박자 | 손 0.05m, 부위 0.08m. 두 사람이 같은 기준점 위 · 안이면 보지 않는다. 선 사람(서기 · 걷기 · 뛰기)은 상대 쪽으로 0.4m(`stage.GAP`, 기준점 자리 틈)까지 다가서서 다시 잰다. 가구 · 벽 · 다른 사람이 막으면 거기서 멈춘다 |
| `body_overlap` | 몸 겹침 | 두 사람의 팔을 뺀 몸 캡슐이 파고듦. 앉은 자세(의자 · 쪼그림 · 무릎 꿇기)는 정강이 · 발, 바닥에 앉기는 다리 전체도 뺀다(다리를 어디 둘지 작가가 정하지 않는다). 접촉 · 받침 중이면 접촉 부위도 뺀다 | 0.03m, 매단 사람과 받치는 사람 0.08m |
| `furniture_overlap` | 가구 | 팔을 뺀 몸 캡슐(앉은 자세의 다리는 몸 겹침과 같이 뺀다)이 가구 상자 · 벽을 파고듦. 앉거나 누운 · 기댄 기준점, 앉거나 눕는 기준점 위 · 안에서 걷기 · 뛰기면 그 기준점(일어나 떠나는 중)은 뺀다 | 0.05m, 발 · 가구는 0.10m. 받침 지적이 난 사람은 내지 않는다 |
| `no_support` | 받침 | 앉을 곳 · 누울 곳 · 기댈 곳 · 받치는 사람이 없음, 눕는 면 밖으로 몸이 나감 | 눕는 면 0.15m |
| `headroom` | 천장 | 머리 꼭대기가 장소 모듈 천장보다 높음 | 선 자세 0, 그 밖 0.05m |

3D 헛지적을 나눈 표와 고친 근거는 [3d/specs/04-judge.md](3d/specs/04-judge.md) 의 '헛지적 고침'(2026-10-29).

향함이 비면 3D 는 몸 방향을 정해 둔다(`stage3d.body.default_facing`: 기준점 위 · 기대기면 그 앞, 손을 뻗으면 그 사람 쪽, 기준점 옆 자리면 그 기준점 앞, 인물 기준 자리면 그 인물 쪽). 평면 `behind_front` 는 여전히 향함을 모르는 것으로 둔다.

시작 상태의 손은 쓰기 전 연출이면 빈손, 본문에서 뽑았으면 본문이 말하기 전까지 `?` 다(DESIGN.md shadowcast 계획의 `?` 손 규칙과 같다).

## 막기

`stage.blocked(contact, who, project) -> bool`: 접촉이 성적 접촉(`is_sexual`)이고 두 인물 중 하나가 `cast.is_minor_age` 면 참. `clean_scene`(AI 결과와 작가 입력)과 프롬프트 블록(일감 05)이 이 함수로 거른다. 화면은 미성년이 낀 접촉에서 `sexual` 부위 · 동작을 고를 수 없게 감춘다.

## 사건 찾기 · 본문과 잇기

- `find_event(ep, scene) -> (번호 | None, 바뀌었나)`: 사건 글이 같은 사건이 있으면 그 번호(바뀌지 않음). 없으면 저장한 번호의 사건(바뀜). 그 번호도 없으면 None(바뀜). 장면은 지우지 않는다.
- `stale(scene, text) -> [박자 번호]`: 인용이 본문에 없는 박자. 띄어쓰기 차이는 무시한다.

## 계획 장면과 본문 장면 · 견주기 (일감 07)

한 사건에 계획 장면(`role = plan`)과 본문 장면(`role = text`)을 하나씩 둔다. 옛 장면은 plan 으로 읽힌다. `stage.scenes_of(ep, event) -> (plan, text)` 가 사건 찾기(`find_event`)로 짝을 찾는다. `new_scene(…, role)` 과 `save_scene` 은 같은 사건 · 같은 역할의 다른 장면이 있으면 막는다(본문 장면이 계획을 덮지 않게, 역할을 바꿔 덮는 것도 막는다).

`stage.align(plan, text, room, p, text_room) -> (match, gaps)`, `stage.diff(...) -> gaps`:

1. 계획 박자 k(0 은 시작 상태)에서 적은 칸을 사실로 모은다. 자리는 (인물, 기준점), 자세는 (인물, `upright`), 접촉은 (인물, 대상, 손이면 '손' 아니면 부위, 닿는 부위). 본문 장면 출연진에 없는 인물은 건너뛴다.
2. 사실마다 지금 본문 박자 j 부터 그 사실이 이뤄지는 첫 박자를 찾는다. 본문 상태에서 자리 · 자세를 모르면 이뤄졌다고 본다(짚지 않는다). 접촉은 그 인물에게 같은 대상 · 부위 · 손 종류의 접촉이 이어지고 있어야 한다.
3. 찾은 박자 중 가장 늦은 박자가 다음 계획 박자를 찾기 시작할 j 다. 못 찾은 사실이 `Gap` 이다.
4. `Gap`: `plan_beat`, `text_beat`(본문이 계획 대신 한 박자: j 뒤에 그 인물의 그 칸을 처음 바꾼 본문 박자, 없으면 j. 접촉은 j), `who`, `field`(at · posture · contact), `plan` · `actual`(화면 글), `text`(해요체 설명), `contact`(계획 접촉 id).
5. `match[k]` 는 계획 박자 k 에 견주는 본문 박자다(줄지 않음). 하나도 이뤄지지 않은 계획 박자는 다음 본문 박자에 견준다. 화면의 겹쳐 보기는 본문 박자 t 에서 `match` 가 t 이하인 마지막 계획 박자(`stagePlanBeat`)를 흐린 원으로 그린다.

향함 · 손에 쥔 것은 견주지 않는다. `check`(그래서 `view` 와 `POST …/check`)는 장면마다 `pair`(짝 장면 id), `gaps`, `match` 를 함께 준다. 짝이 없으면 `pair` 는 null, 나머지는 빈 목록이다. 차이는 '사소' 지적 재료이고 작가가 '그대로 둠'으로 닫는다(검수 연결은 일감 04).

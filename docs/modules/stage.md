# 모듈 지도: 장면 연출

이 파일의 줄은 [AGENTS.md](../../AGENTS.md) 의 '문서 줄 규칙'을 따른다.

### `canon/stage.py`

- 장면 연출 계산(설계 `docs/stage/`): 방 틀(`ROOMS`: 방 7 · 야외 차 옆 `car_side` · 야외 빈터 `outdoor`, `make_room`, `Project.rooms`, 기준점 종류 `ANCHOR_KINDS`, 크기 `ANCHOR_SIZES`)
- 고정 어휘(부위 `PARTS` · 자세 `POSTURES` · 접촉 동작 `ACTS` · 관계 `RELS` · 향함 `FACINGS`, 화면용 `vocab`)
- 새 장면 방 고르기의 작은 그림 재료는 `vocab` 의 `room_shapes`(틀마다 크기 · 기준점 상자)
- 박자 겹치기(`state_at`)
- 기준점 + 관계 → 좌표(`place`, 박자마다 앞 박자 좌표를 잇는 `layouts`, 화면 `static/stage.js` 의 `stageLayout` · `stageLayouts` 와 같은 규칙)
- 규칙 판정(`judge`: 손 · 이동 자세 · 거리 · 향함 · 물건, `Violation`, 어긋난 접촉 `contact`)
- 계획 장면의 빠진 이동 안내(`move_gaps`: 기준점 쪽으로 걷고 자리를 안 바꿈 · 떠난 적 없이 돌아옴, 검수 지적 아님)
- AI 계획 초안의 빠진 도착 자리 채우기(`fill_arrivals`, `pipeline._stage_ask` 가 부름)
- 성적 접촉(`is_sexual`)과 미성년 막기(`blocked`)
- 작가 입력 정리(`clean_scene`)
- 사건 찾기(`find_event`)
- 본문과 다른 박자(`stale`)
- 계획 장면 · 본문 장면(`StageScene.role` plan · text, 사건마다 역할 하나, 짝 `scenes_of`)과 계획과 다른 곳(`align` · `diff`, `Gap`: 박자 끝 상태의 차례로 자리 · 자세 · 접촉을 견줌)
- 장면은 `Episode.stage`(`StageScene`)
- 작가 자료라 스냅샷에 넣지 않는다
- 화별 스토리보드는 읽기만 한다(일감 08): 사건을 맡은 스토리보드 장면 `board_scene_of`
- 방 후보 `room_hints`
- 새 장면 출연진은 그 장면의 `present`
- 화면 값 `board_view`(`view` 의 `board`)
- 프롬프트 머리의 스토리보드 장면 번호 `episode_lines(board=True)`(`prompts.stage_block`, 스토리보드 블록 바로 뒤)
- 초안 재료 `prompts.stage_board_lines`
- LLM 호출 없음
- 화면용 새 방 · 새 장면 · 저장 · 지우기 · 화면 값(`new_room`, `new_scene`, `save_scene`, `remove_scene`, `check`(박자 사이 돌아가는 이동 `paths`, 계산은 `stagepath.paths`), `view`: 장면마다 짝 `pair` · `gaps` · `match`, 웹 `…/stage/{화}`)
- AI 장면(`StageDraft`, 이름 기반)을 id 로 바꾸기(`from_draft`: 모르는 인물은 박자 설명, 모르는 기준점 · 향함은 메모, 본문 장면 시작 손은 '?', 그 뒤 `clean_scene`)
- 장면 끝 상태 줄(`end_lines`, 다음 장면 프롬프트 재료)
- 검수 지적(`to_issues` · `episode_issues`: 인용이 본문에 있는 박자만, 한 문장은 지적 하나, 동선 · low · `origin` rule · `stage_event` · `stage_beat`)
- AI 가 더하자는 기준점의 자리
  - `place_anchors`: 관계 쪽 곁 · 빈 자리 · 방 넓히기
  - 차에 붙는 자리는 차 안 `_in_vehicle` · 그 곁 창 · 문은 차 옆면 `_on_vehicle_wall` · 차 안인지 `container`
  - `DraftAnchor.part` 는 near 안 끝 구역 `_part_zone` · 면 `_on_face`
  - 적용 때 지금 방에 합치기 `grow_room`
  - 공용 방 `room_shared`
- 붙은 기준점(09, `StageAnchor.parent` · `face`, 면 `FACES` · 방 벽 `WALLS`): 자식은 부모 기준 좌표로 저장하고 좌표를 읽는 곳은 모두 푼 방 `resolve`(푼 방은 `StageRoom._world`, 저장하지 않음)를 쓴다
- 세계 → 부모 기준 `to_local`
- 자식들 `children`
- 저장 전 정리 `clean_room`(`save_scene` · `grow_room`)
- 왼쪽 · 위로 넓히기 `shift_room`(뿌리 · 벽 기준점만)
- 옛 방 짐작 `attach_guess`(`StageRoom.attached` 가 거짓이면 `model_validator` 가 부름)
- AI 호출은 `pipeline.draft_stage`(plan, 빈 방에서 받기 `fresh`, 공용 방이면 복사한 장면 전용 방에 더함) · `extract_stage`(check) · 검수 때 함께 뽑기 `stage_extract_all`(`Settings.stage_extract`, 본문 지문이 같으면 건너뜀, 작가가 손본 본문 장면 `source manual` 은 덮지 않음)
- 적용 · 적용 취소 `apply_stage` · `undo_stage`(`prev`, id 가 빈 prev 는 '적용 전에 없었음')
- 프롬프트 `prompts.stage_draft_prompt` · `stage_extract_prompt`
- 가짜 응답 `mock_stage.py`
- 추출 측정 `scripts/stage_eval.py`(세트 `tests/fixtures/stage_eval.json`, 실제 호출은 `CANON_STAGE_LIVE=1`)
- 웹은 결과를 `pending.json` 의 `stage:<화>:<사건>:<역할>` 로 두고 `GET …/stage/{화}` 의 `proposals` 로 보인다(`POST …/apply`, `DELETE …/proposal/{사건}/{역할}`, `POST …/{장면}/undo`, `PUT …/stage-extract`)

### `canon/stage3d/`

- 장면 연출 3D 판별(설계 `docs/stage/3d/`, 정한 것은 그 README): 공통 뼈대 `body.py`
  - 마네킹 마디 `L` · 키 1.72m
  - 좌표는 평면도 x · y + 높이 z
  - 각도 `Angles`
  - 자세 계약 `PostureSpec` · `Reach` · 특수 배치 `PlaceCtx` → `Placement`
  - FK `pose` → `Body`(`joints` · `part_point` · `capsules` · `head_top`)
  - 손 IK `reach_to`(모자라면 비틀고 숙임)
  - 고개 `look_at`
  - 부위 점 `PART_POINTS` · 캡슐 `PART_SEGMENT`
  - 겹침 깊이 `penetration`
  - 동작별 손 배치 `ACT3D`
  - 박자마다 관절 좌표 `frames` → `Frames.to_dict()`(렌더러 계약)
- 가구 `furniture.py`
  - `Box` · `Furniture` · `RoomSpec`
  - 종류 기본값 `KINDS`(기준점 종류 목록은 `stage.ANCHOR_KINDS`, 화면 `static/stage.js` 의 kinds 와 같다)
  - 세계 상자 `solids`(푼 방으로, 위(top)에 붙은 자식은 부모 윗면 높이에서. 자리를 품은 차는 운전 칸을 비운 `cab_vehicle`, 부모 안의 앉지 않는 구역은 테두리만, 고르기 `shape`)
  - 면 높이 `surface`
  - 야외 틀 `RoomSpec.open`: 벽 · 천장 판정 없음
  - 사람을 가르는 막 `Box.barrier`: 차체 옆판
  - `judge._parted` · `_blocked`
- 자세 모듈 `postures/<자세 id>.py`(`POSTURE`) · 장소 모듈 `rooms/<틀 id>.py`(`ROOM`)는 폴더를 훑어 스스로 등록(`postures.load` · `rooms.load`, 공통 파일을 고치지 않음)
- 등록 상태 `posture_specs` · `room_specs` · `missing` · `complete`
- 시험용 가짜 `fake.py`
- 판정 `judge.py`(`judge3d`, 규칙 `RULES3D`, 문턱 상수, 등록부가 다 차야 도는 `judge_if_ready`)
- 켜기 `ready`
- `stage.judge_all` 이 평면 판정에 3D 를 더해 `stage.check` · `to_issues` · AI 장면 비교로 보낸다(07, `docs/stage/3d/specs/07-wire.md`)
- 엉덩이 돌림 `hip_rot` · 발목 `ankle`
- 배치 뒤 각도 `Placement.angles`
- 고개 한도 `PostureSpec.head`
- 빈 향함의 몸 방향 `default_facing`
- 시험 장면 `tests/stage3d_scenes/*.json`(ok_ · bad_, `tests/test_stage3d_wire.py`)
- 좌표는 `stage.layouts`
- 3D 좌표는 프롬프트에 넣지 않는다
- LLM 호출 없음

### `canon/stagepath.py`

- 장면 연출 박자 사이 이동 경로(설계 `docs/stage/specs/10-path.md`): 3D 가구 상자(`stage3d.furniture.solids`, 머리 `HEAD` 아래에서 시작하는 단단한 상자)의 바닥 사각형을 몸 반지름만큼 부풀린 장애물 사이 가장 짧은 꺾은선
  - `route`: shapely 로 부풀리기 · 덮음
  - networkx 가시성 그래프
  - 끝점이 가까운 가구는 그 거리까지만 부풀림
  - 길이 없으면 막힘
- 머문 기준점 · 조상 · 자식 · 품은 차는 빼기(`_skip`)
- 박자마다 인물별 `{"via", "blocked"}`(`paths`, 곧은 이동은 싣지 않음)를 `stage.check` 와 `stage3d.frames`(`Frames.paths`)가 싣는다
- 그림에만 쓰고 검수 지적이 아니다
- LLM 호출 없음

### `canon/static/stage.js`

- 장면 연출 화면(주소 `stage/<화>/<사건 번호>`, `viewStage`, 불러오기 `stgLoad`): 평면도
  - `stgPlanSvg`
  - 글자 · 인물 원은 칸 폭과 상관없이 화면에서 같은 크기(`stgU`: `stgDrawPlan` 이 `getScreenCTM` 으로 잼, CSS 변수 `--u`)
  - 좁은 칸(`stgU` > 1.3)의 이름표는 자세를 빼고 이름만
  - 박자 사이 보간 `stgDrawPlan`: 가구를 돌아가는 꺾은선은 `check` 의 `paths` 에서 `stagePathFor` 로 고르고 `stagePathAt` 으로 따라감
  - 막힌 이동은 빨간 점선과 '막힌 이동' 안내
  - 이름표 겹침은 순수 함수 `stageLabelPlace`(평면도 · 3D `s3PlaceTags` 가 함께 씀, 앞 프레임 자리 `stgLabelMem`, `tests/test_stage_labels.py`)
  - 끌어 놓기 → `stageSnap`
- 화면 틀은 공용 목차 틀(`outlineDoc` · `outlineNav`, 틀 클래스 `.stg-wrap`)
- 목차 `stgToc`: 화 고르기 · 사건(상태 글 계획 · 본문 · 없음) · 지금 사건의 박자(지적 수 · 본문과 달라요 · 계획과 달라요)
- 무대 카드: 평면도(또는 3D)와 그 박자 칸 `stgNow`(박자 글 · 바뀐 것 `stgChange` · 그 박자의 지적과 안내)
- 박자 글은 '박자 글 고치기'로 그 칸에서 편다(`S.stg.beatEdit`)
- 박자 줄 `stgBar`: 재생 · 박자 눈금(지적이 있는 박자에 빨간 점)
- 좁은 칸(`@container outline` 720px 이하)의 박자 줄은 아래에 붙고 앞뒤 버튼(`stgStep`) · 'k / N박자'로 바뀐다
- 인물 카드 `stgPeople`: 인물마다 한 줄 요약(`stgSummary`, 손 `stgHands`)
- 인물 줄은 '고치기'로 그 줄만 편다(`S.stg.open`, `stgOpen`, 평면도에서 인물을 눌러도 편다)
- 편 줄의 칸(`stgPersonCard`: 자세 · 자리 · 향함 · 손 · 접촉 · 부위 도식 · 출연진에서 빼기, 미성년이면 성적 부위 · 동작 감춤)
- 방 카드 `stgRoomCard`: 읽는 모양이고 '방 고치기'로 편다(`S.stg.mode` room, 평면도는 기준점 끌기)
  - `stgRoomPanel`: 끌기 `stageDragTo` · ↻ `stageTurn` · 붙은 곳 `stageAttach` · `stageAttachOptions` · 함께 빼기 `stgDropNote`
  - 붙은 기준점 풀기 `stageResolve` · `stageToLocal` · `stageChildren` · `stageShiftRoom` 은 `stage.resolve` · `to_local` · `children` · `shift_room` 과 같은 규칙
  - `tests/test_stage_attach.py`
- 새 장면(`stgNewCard`): 이 작품의 방 · 틀을 작은 그림 칸(`stgThumb`)으로 고른다
- 머리의 '계획 | 본문' 전환(`S.stg.role`, `stgRole`, 본문 장면이 없으면 '본문에서 뽑기 전이에요')
- 겹쳐 보기(`stgGhostSvg`, 계획 박자는 `stagePlanBeat`)
- 계획과 다른 박자 표시(`stgGaps`)
- 고치는 장면은 `S.stg` 에 따로 들고 저장(`PUT …/stage/{화}/{장면}`)
- 고칠 때마다 판정만(`POST …/check`)
- 저장 안 한 변경은 `S.stgDirty`
- AI 버튼(`stgAiBtn`: 계획은 '플롯에서 초안' 작업 `stage_draft`, 본문은 '본문에서 뽑기' `stage_extract`)
- 검토를 기다리는 AI 장면 비교(`stgProposal` · `stgCompare`: 끝 상태 작은 평면도 `stgMiniSvg` 나란히, 박자 목록 차이 `stgBeatList`, 적용 `stgApply` · 버리기 `stgDiscard`)
- 적용 취소(`stgUndo`)는 머리의 ⋯ 메뉴(`stg-more`)에 장면 지우기와 함께 있다
- 작업이 끝나면 다시 받기(`stageJobResult`)
- 검수 화면에서 그 박자로 오기(`S.stgJump`)
- 스토리보드 장면별 목차 사건 묶음(`stgEventGroups`, 낡으면 '스토리보드가 낡았어요') · 새 장면 방 순서(`stgRoomOrder`, '스토리보드 장소')
- 스토리보드 카드 장면 줄의 '장면 연출'은 `board.js` `boardStageLink`(`tests/test_stage_board.py`)
- `stageState` · `stageLayout` · `stageAnchorPoint` · `stageFacing` · `stageSnap` · `stageSexual` 은 `stage.state_at` · `place` · `is_sexual` 과 같은 규칙(`tests/test_stage_js.py`)
- CSS 는 JS 에서 주입
- 인물 색은 `STG_COLORS`: 토큰 `stage-1`~`stage-6`(빨강은 지적에만), 원 안 글자 `on-stage`
- 무대 카드 안 칸 폭 규칙은 `@container stgcol`(820px 이상이면 평면도 옆에 그 박자 칸)

### `canon/static/stage3d-load.js`

- three.js 늦게 읽기(`load3d()`): 3D 보기를 처음 열 때만 `vendor/three` 의 ES 모듈 셋을 `import()` 로 한 번 읽고 `{THREE, OrbitControls, CSS2DRenderer, CSS2DObject}` 를 돌려준다
- 실패하면 해요체 오류로 거부하고 다음 호출에서 다시 읽는다
- 평소 화면은 three.js 를 받지 않는다(`tests/test_stage3d_vendor.py`)

### `canon/static/stage3d.js`

- 장면 연출 3D 보기(설계 `docs/stage/3d/specs/05-render.md`)
- `stage.js` · `stage3d-load.js` 와 `app.js` 의 `S` · `actions` · `api` · `render` 를 쓴다
- 읽기 전용이다: 고치기는 평면도에서만 한다
- 3D 로 바꾸면 방 고치기 · 인물 줄 · 박자 글 고치기를 닫고 그 버튼을 숨긴다(`stgView`)
- 그림 칸은 4:3, 무대 카드 폭 480px 이하는 1:1
- 서버(`GET …/stage/{화}/{장면}/frames`, `stage3d.frames`)가 낸 관절 좌표를 그리기만 한다
- 박자 슬라이더 · 재생은 평면도와 같은 `S.stg.beat` 를 쓴다
- three.js 는 '3D' 를 처음 누를 때 `load3d()` 로 읽는다
- 좌표: 서버 (x, y, z) = 평면도 x · y + 높이 z → three.js (x, z, y)

### `canon/static/vendor/`

- 바깥 라이브러리
- 고치지 않는다
- `vendor/three/` 는 three.js 0.170.0(MIT): `three.module.min.js` · `OrbitControls.js` · `CSS2DRenderer.js` · `LICENSE`
- addon 두 파일의 import 경로 한 줄만 바꿨다
- 판 · 받은 곳 · 크기 · sha256 · 올리는 법은 그 폴더의 `README.md`(`tests/test_stage3d_vendor.py` 가 맞춰 본다)

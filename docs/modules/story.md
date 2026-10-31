# 모듈 지도: 이야기 데이터 기능과 그 화면

이 파일의 줄은 [AGENTS.md](../../AGENTS.md) 의 '문서 줄 규칙'을 따른다.

### `canon/abilities.py`

- 스킬 · 특성 도감
- 상태창 목록 조각(스킬 · 특성 · 칭호, 이름 `LIST_NAMES` 이거나 조각이 둘 이상, 인벤토리는 도감 항목이 가리킬 때만 `list_stats`)마다 설명 · 효과 · 대가 · 등급별 효과(`Project.abilities`, `Ability`)
- 정의는 인물 사이에 하나
- 등급 꼬리를 뗀 이름으로 잇는다(`split`, `key`, `find`, `statwin._GRADE` 재사용)
- 가진 인물(`owners`)
- 얻은 화 · 바뀐 기록은 `stat_log` 에서 계산(`history`, `acquired`, 저장 안 함)
- 도감에 없는 조각(`unlinked`)
- AI 에게 보이는 한 줄(`line`: 이름(=다른 이름) [상태창 항목 · 가진 인물 등급]: 효과 / 가진 등급 효과 / 대가, 다음 단계 프롬프트가 같은 함수를 쓴다)
- 화면 값(`catalog`, `lookup`)
- 작가 편집(`upsert`, `remove`)
- 명령줄 `abilities`
- LLM 호출 없음
- 화면은 `static/abilities.js`

### `canon/address.py`

- 호칭 · 말씨
- 인물 A 가 B 를 부르는 말 · 말씨(`AddressForm`, 방향마다 하나, `Project.address_forms`)
- 작가가 정하기(`set_form`, 1화 반영 뒤 작가 기록)
- 상태 변경안의 바뀜(`StateDelta.address_changes`, `AddressChange`) 정리 · 반영 · 되돌리기(features 훅 `clean_delta` · `apply_delta` · `revert`, 기록 `Project.address_log`)
- 자동 집필 · `run -y` · 플레이의 남겨 두기(`hold`, `Project.address_held`, `take_held` · `drop_held`)
- 프롬프트 블록(`block`, 장편 예산 `context.BUDGET["address"]`) · 검수 규칙(`check_rule`) · 상태 규칙(`state_rule`)
- 자주 쓰는 말씨 `SPEECH_LEVELS`
- LLM 호출 없음
- 화면은 `static/address.js` (두 사람 상세 `addressCard` · 인물 카드 `addressHeldCard` · 상태 승인 '직접 정할 것' 줄 `addressDeltaRows`, 말씨 목록 `ADDRESS_LEVELS` 는 `SPEECH_LEVELS` 와 같음 `tests/test_address.py`)

### `canon/agent.py`

- 대화 에이전트(지금은 플롯 대화 `plot`만)
- 세션(`AgentSession`, 주제마다 여럿, 기본 대상 · 권한 모드 `ask|draft|all`)
- 턴(`AgentTurn`)을 백그라운드 작업 `agent` 로 돌린다(`run_turn`, 단계마다 `llm.json(PlotAgentStep)`, 최대 `MAX_STEPS`=8, 단계마다 저장)
- 도구는 읽기(`read_plots` · `read_summaries` · `find_text`(`context.recall`) · `read_cast`, 결과 `RESULT_LIMIT` 자)와 쓰기 `edit_plot`
- 되묻기 `ask`
- 쓰기는 `clean_revision` 으로 거른다(본문이 있는 화는 막힘)
- 쓰기 부분마다 종류(`KIND_LABELS`)를 매긴다
- 권한(`permit`) 안이면 `pipeline.plot_apply` 로 바로 쓴다(`WriteRecord`)
- 권한 밖이면 승인 카드(`Approval`, `decide`)로 남기고 턴을 끝낸다
- 다음 아크 칸 · 구조는 화면 초안('draft')으로만 간다
- 되돌리기(`undo`)는 `pipeline.plot_undo`
- 멈추거나 실패한 턴은 `reconcile`
- 프롬프트 `prompts.agent_plot_prompt`

### `canon/archetypes.py`

- 원형 도감
- 인물 유형 카드(`CATALOG`, `Archetype`)
- 상처(`WOUNDS`)
- 말투 틀(`SPEECH`)
- 장르로 거르기(`match`)
- 빈 칸만 채우기(`fill`, 비틀기는 아크 끝 한 줄)
- 고른 원형 기록(`Project.cast_archetypes`, `remember` · `prune`, 프롬프트에 넣지 않음)
- 주사위(`roll`, 이름은 `naming`)
- 명령줄 `dex`
- LLM 호출 없음
- 화면은 `static/archetypes.js` (설정 도우미의 도감 주사위만, `dexRemember` 는 `remember` 와 같은 규칙, `tests/test_archetypes_js.py`)
- 글은 새로 쓴다(TV Tropes · 나무위키 옮기지 않음)

### `canon/birth.py`

- 무작위 출생과 새 세계
- 코드가 시드로 굴린 출생
  - `roll`
  - `Birth`: 원형 · 상처 · 말투 · 비틀기는 `archetypes.match` · `roll`
  - 이름은 `naming.character_candidates`(세계 인물 · 인물 후보와 겹치지 않게)
  - 태어난 곳은 `birth_places`(`atlas.places` 에서 반영한 마지막 화 `last_finalized` 까지 생기고 드러난 곳)
  - 나이는 장르 범위 `AGE_RANGES`
  - 성인 작품은 19세부터
  - 갈래마다 시드에서 난수원을 따로 둔다
- AI 배경 채우기(`sketch`, `BirthSketch`, `prompts.birth_prompt`: 세계 · 장소 · 세력 · 인물 한 줄이 앞, 굴린 값이 뒤)
- 플레이어 인물 만들기(`to_character`: id `player_id`, 빈 칸은 `archetypes.fill`, 세계 작품은 바꾸지 않음)
- 장르 · 한 줄로 새 세계 작품(`new_world`: 웹 새 작품 만들기와 `pipeline.suggest_setup` · `apply_setup`, 장소가 없으면 `naming.location_candidates` 로 채움, AI 제안 뒤에만 저장)
- LLM 호출은 `sketch` · `new_world` 뿐

### `canon/branches.py`

- 갈래
- 같은 작품을 복사해 n화부터 다른 전개를 쓰는 사본
- 갈래 하나는 작품 폴더 하나
- 갈래 정보(`BranchInfo`)는 `project.json` 밖의 `branch.json`(`store.load_branch` · `save_branch` · `drop_branch`, 화면 저장이 덮지 않게)
- 만들기(`make` → `fork`: 복사본을 `pipeline.revert(n-1)`, 뒤 아크 · 부 요약 비움, `clear` 는 n화부터 본문을 이전 판으로)
- 함께 쓰는 앞 화 고침(`shared_edited`, `base` 해시)
- 집안 계산(`family`, `order`, `diverge`, `promote` · `promote_saved`, `remove`, `{폴더: BranchInfo}` 만 받는 순수 함수)
- 비교(`compare` · `compare_saved`)
- 합치기는 없다
- 원본 `project.json` 은 바꾸지 않는다
- 작품 복제는 `branch.json` 을 옮기지 않는다
- 명령줄 `branch` · `branches` · `branch-compare` · `promote`
- LLM 호출 없음

### `canon/cast.py`

- 인물 화면 계산
- 화별 관계 프레임(스냅샷, 지워진 화는 사건 로그로 다시 계산)
- 인물별 등장 화
- 화별 타임라인
- 명령줄 `cast` 출력
- 반영 때 본문에 이름이 나오고 상태 변경안이 다룬 인물을 그 화 등장 인물에 붙이기(`cast_to_add`, features 훅 `clean_delta` · `apply_delta` · `revert`, 기록 `StateDelta.cast_added`, 상태 승인 화면은 `review.js` `castAdd`)
- LLM 호출 없음

### `canon/charlog.py`

- 인물 설정 변경
- 상태 변경안의 설정 바꾸기 제안(`StateDelta.setting_changes`, 외모 · 성격 · 말투 등 뒤 화까지 이어지는 변화) 정리(`clean_delta`)와 반영(`apply`, 작가가 고른 것만)
- 변경 기록(`Project.setting_log`: 화, 칸, 전후 값, AI · 작가)
- 1화 반영 뒤 설정 화면 수정 기록(`record_author`, `web.put_project`)
- 되돌리기(`revert`, 스냅샷에 인물 설정이 없어 기록으로 되돌림)
- 자동 집필 · `run -y` 가 남겨 둔 제안(`hold`, `Project.setting_held`, `take_held` · `drop_held`)
- 기록은 프롬프트에 넣지 않는다
- LLM 호출 없음
- 화면은 `static/charlog.js`

### `canon/dynamics.py`

- 관계 역학
- 사건(`StoryEvent`)으로 방향 관계(`Tie`)를 계산
- 긴장도
- 스냅샷 재생
- 숫자를 말로 바꾸기
- 단계에 들어온 화(`Tie.stage_since`, `run_episode` 가 적고 `replay` 가 다시 채움)를 관계 줄에 '(n화부터)'로(`since`)
- 말로 고른 보는 방식(`VIEWS`)으로 시작 관계 만들기
- LLM 을 부르지 않는 순수 계산

### `canon/elements.py`

- 인과율
- 작가가 언제든 더하는 이야기 요소(`StoryElement`)의 관련 화 지도(`links`)
- 화별로 넣을 요소(`episode_block`)
- 시점 설명
- 본문 · 플롯에서 처음 나온 장소(`NewPlace`)를 '장소' 요소로 등록(`clean_places`, `add_places`, 반영 취소 `unregister_places`, 플롯 후보 `place_candidates`)
- 장편은 그런 장소를 예산(`context.BUDGET["places"]`)까지만
- 비슷한 지명은 `naming.similar_place`
- LLM 호출 없음
- 영향 분석과 반영은 `pipeline.analyze_impact` / `apply_impact`

### `canon/foreshadows.py`

- 복선 센터
- 복선을 본문 문장에 건다(`ForeshadowClue`, `Project.foreshadow_clues`, 본문은 바꾸지 않음)
- AI 문장 정리(`clean_delta`)와 반영 · 되돌리기
- 작가가 걸기 · 복선 고치기(그 화 이후 스냅샷도)
- 센터 계산(`center`: 회수율, 끊어진 연결, 예정 지남, 오래 묵음, 플롯 회수 계획)
- 명령줄 `foreshadows`
- LLM 호출 없음

### `canon/genres.py`

- 장르 목록(`CATALOG`)과 장르별 안내
- 프롬프트의 장르 안내와 수위 블록(`guide`)
- 설정 화면의 장르별 로그라인 예시(`Genre.logline`)

### `canon/illust.py`

- NovelAI 삽화 프롬프트 조립
- AI 원안(`IllustDraft`)에 저장된 인물 외형 태그(`Project.visuals`)
- 인물 수
- 등급
- 모델별 품질 태그(`MODELS`)를 붙여 기본 · 인물 · 부정 프롬프트로(`assemble`)
- 태그 정리(`clean`)
- LLM 호출 없음
- AI 호출은 `pipeline.illustrate` / `suggest_look` (`illustration` 단계)

### `canon/knows.py`

- 인물이 아는 정보(`CharacterState.knows`)
- 알게 된 화(`learned`, 반영 기록에서 셈, 저장 안 함)
- 장편 프롬프트 보기(`view`: 접은 줄 + '(n화)' 붙인 고른 줄, `prompts.state_view` 가 부름)
- 상태 변경안이 따라 적은 표시 떼기(features 훅 `clean_delta`)
- 아크 요약 뒤 접기 대상(`targets`) · 정리(`clean_fold`) · 적용(`apply_fold`, `CharacterState.knows_folded`, 기록 `Project.knows_folds`) · 되돌리기(`undo_fold`, 반영 취소 훅 `revert`)
- LLM 호출 없음
- 접기 제안은 `pipeline.fold_knows`(작업 `fold_knows`, 프롬프트 `prompts.fold_prompt`, 응답 `KnowsFoldSet`)
- 화면은 `static/knows.js` (`knowsFoldBox`, 아크 카드 요약 칸 아래, `KNOWS_KEEP` 은 `context.KNOWS_KEEP` 과 같음 `tests/test_knows.py`)

### `canon/library.py`

- 문체 라이브러리
- 작품과 따로 `projects/.styles/<id>.json` 에 문체(원문, 프로필, 기준 지표)를 저장
- 작품에 적용하면 복사하고 `Project.style_id` · `style_version` 으로 출처만 기억
- 저장마다 버전(`StyleVersion`)
- 칸별 비교(`diff`)
- 되돌리기(`restore`)

### `canon/logline.py`

- 로그라인 다섯 칸 합치기(`compose`, 조사 자동)
- 형식 점검(`checks`)
- 톤 다이얼 문장(`tone_text`)
- LLM 호출 없음
- `static/setup.js` 에 같은 규칙이 있어 함께 고친다(`tests/test_logline_js.py`)

### `canon/naming.py`

- 이름·지명 무작위 생성(세계관별 스타일, 나이에 맞는 한국 이름)과 출연진 이름 점검
- 새 인물을 들일 때의 이름 점검 · 한 화 새 인물 수(`new_cast_warnings`, 상태 변경안 정리 `features._new_cast_names`)
- LLM 을 부르지 않는다
- 자료와 출처는 `canon/naming_data.py`

### `canon/pace.py`

- 관계 속도: 상태 변경안의 관계 유형 · 설명이 반영 뒤 관계 단계와 반대인지 본다(features 훅 `clean_delta`, 등장 인물 붙이기 뒤)
- 사건을 사본에 돌린 반영 뒤 단계(`_after`, `dynamics.run_episode`), 두 방향 단계의 극성(`STAGE_SIGN`, 엇갈리면 0)
- 글 극성(`polarity`: 낱말 사전 `POSITIVE` · `NEGATIVE`, 바로 뒤 '않 · 못 · 없'은 뒤집음), 관계 극성(`rel_polarity`: 유형 먼저, 중립이면 대사를 뺀 설명)
- 반대인 유형 바뀜의 차례 `StateDelta.rel_flagged` → 상태 승인 화면 기본 체크 해제(`review.js` `setDelta`), 사람 검토 없이 반영할 때는 빼기(`hold`, 남긴 개수로 세지 않음)
- 두 층 감정(`prompts.LAYER`)으로 상대를 적은 쌍은 빼기(`_masked`)
- 한 쌍 한 화 결정적(3) 사건 `BIG`(3)개 이상 경고
- 쓰기 전 플롯: 화 플롯이 바라는 관계 바뀜(`plot_shifts`: 바뀜 말 `SHIFTS` · 가장 뒤 말 `_last_shift` · 이름 `name_forms`)
- 지금 단계에서 칸 수가 쓸 수 있는 칸보다 많으면 경고(`plot_warnings` · 안 쓴 화 모두 `plan_warnings`)
- 보이는 곳은 `board.checks` 와 `static/plot.js` `pacePlot`(같은 규칙, `tests/test_plot_pace_js.py`)
- LLM 호출 없음

### `canon/pairlog.py`

- 두 사람 사이 이력(장편)
- 승인된 관계 사건(`Project.events`)을 쌍마다 모으기(`history`)
- 쓰기 블록(`write_block` · `write_lines`: 이번 화 플롯 인물끼리 한 줄 라벨, 근거 문장 없음, 예산 `context.BUDGET['pairs']`)
- 검수 블록(`check_block`: 갈래별 처음 일어난 화와 근거 문장, 예산 `check_pairs`, `prompts.pair_check_block`) · 확인할 것(`check_rule`)
- 새 데이터 없음
- LLM 호출 없음

### `canon/play.py`

- 플레이 모드(작업 중, 명령줄 `play`, 웹 화면 `static/play.js`)
- 세계 작품을 복사한 플레이 사본(`start` → `prepare`, `play.json`, `PlayInfo`, `store.load_play` · `save_play`, 함께 저장 `save`)
- 세계의 마지막 반영 화(`world_ep`) 뒤를 지우고 단편이면 아크 1 로 묶어 `serial` 로
- 시간 단위는 세계의 화 사이 날수로(`pick_unit`)
- 시간이 흐르는 구간(코드 이름은 턴 `PlayTurn`, Episode 하나)마다 흘러간 일(`PlayScene.beats`) + 있으면 결정 장면(`text` · `choices` · `lean`)을 쓴다
  - `scene`
  - `play` 단계
  - `prompts.play_scene_prompt`
  - 본문 `segment_text`
  - 막기 `check_turn`
  - 결정 대기 `waiting`
  - 선택 `choice_action` · 자동 결정 `auto_action`
- 플레이어가 닿은 구간(`see`, `PlayInfo.seen`)보다 한 구간 넘게 앞서 쓰지 않는다(비용 상한)
- 흐르는 중 행동하면 보지 않은 구간을 버린다(`drop_unseen`)
- 상태 반영(`settle`, `prompts.play_state_prompt`, `clean_delta` → `charlog.hold` → `apply_delta` → `Episode.auto`, 실패는 `PlayTurn.state` failed 로 두고 다시)
- 장(StoryArc)은 다음 구간을 덮게 미리 연다(`open_chapter`, `CHAPTER_LEN` 20, 세계에 부가 있으면 '플레이' 부)
- 장을 다 반영하면 요약으로 접는다(`fold`, `pipeline.recap`)
- 되감기(`rewind` · `trim_after`)
- 다르게 해 보기(`fork`: 폴더 복사 + `rewind`, play.json 은 옮기고 branch.json 은 안 옮김)
- 운(`roll_luck`, 시드 · 구간으로 정함, 숨김)
- 결말(`PlayTurn.ending` · 구간 수 · 결정 수 · 날수 한도 `_limit_reason` → `end`)
- 설계는 DESIGN.md 10장

### `canon/publish.py`

- 복사 · 내보내기
- 본문을 다른 사이트에 붙여 넣기 좋게 다듬기(줄바꿈 형식 `FORMATS`, 마크다운 흔적 지우기, HTML)
- 여러 화 잇기(`export`)
- LLM 호출 없음
- 화면은 `static/publish.js`

### `canon/renumber.py`

- 화 끼워 넣기 · 빼기
- 안 쓴 화의 번호를 옮길 때 함께 옮길 곳(플롯, 구간 · 아크 · 부 범위, 복선, 인과율 요소, 줄기, 인물 첫 등장 화, 대화 주제)
- LLM 호출 없음
- 검사와 새 화는 `pipeline.insert_episode` / `remove_episode`
- 새 화 AI 초안은 `draft_episode`(`prompts.episode_plot_prompt`)
- 본문이 있거나 반영한 마지막 화 지우기는 `delete_last`(반영 취소 → 본문 비우기 → 화 빼기, 웹은 `before-delete-<화>.json` 백업)
- 화 번호를 품은 칸을 새로 만들면 `move_points` 에도 넣는다
- 화면은 `static/insert.js` (넣을 수 있는 자리 `lastFixed` 는 `last_fixed` 와 같은 규칙, `tests/test_insert_js.py`)

### `canon/setupchat.py`

- 설정 도우미 대화(대화 주제 `setup`)
- AI 변경안(`SetupRevision`: 기본 정보 · 세계관 칸 `SetupEdit`, 인물 칸 `CharacterEdit`, 새 인물, 관계, 방향 여러 안) 정리(`clean`)
- 고른 부분만 적용(`apply`, 부분 id `part_ids`)
- 변경안 단위 적용 취소(`undo`, `ChatMessage.setup_before`)
- 기록(`record`)
- AI 는 칸 · 인물 · 관계를 지우지 않는다
- 첫 반영 뒤에는 AI 가 관계의 시작 방식과 수치를 바꾸지 않는다
- 1화 반영 뒤 바꾼 인물 칸은 `charlog.record_author` 로 남긴다
- LLM 호출은 `pipeline.revise_setup`
- 프롬프트는 `prompts.setup_chat_prompt`
- 명령줄 `setupchat`

### `canon/static/abilities.js`

- 스킬 도감 화면(사이드바 도구, 공용 목차 틀 `outline.js`)
- 주소 `abilities`(개요) · `abilities/_missing`(도감에 없는 조각) · `abilities/_new`(새 항목) · `abilities/<항목 id>`
- 왼쪽 목차 `abToc`(찾기 칸, 개요, 도감에 없는 조각, 상태창 항목별 묶음 `abGroups`, 줄 끝 `abTail`)
- 개요 `abOverview`(수 타일, 손볼 것, 도감에 없는 조각 다섯)
- 도감에 없는 조각 쪽 `abMissingPage`(상태창 항목 거르기, 가진 인물, '도감에 만들기')
- 항목 쪽 `abItemPage`: 머리(⋯ 메뉴에 지우기) · 설명 · 효과 · 대가 · 등급별 효과 · 가진 인물(바뀐 걸음 `abSteps`) · AI 에게 보이는 줄
- 카드는 읽기 먼저이고 '고치기'로 그 카드만 편다(`S.abEdit`: base · grades · new)
- 넣기 방식 `context` 는 나눔 버튼으로 바로 저장한다(`abContext`)
- 넣는 방식 `stat_window.prompt` 가 lines 가 아니면 AI 에게 보이는 줄 카드가 알린다
- 인물 카드 · 상태창 수치의 상태창 칩(`abChip`)을 누르면 뜨는 도감 카드(`abShow`, 공통 대화상자 `showDialog`)
- 칩의 '도감에 설명 없음' 점은 `abNoDoc`(`abFindLocal` 은 `abilities.find` 와 같다)
- 목록 이름 `AB_LIST_NAMES` 는 `abilities.LIST_NAMES` 와 같다(`tests/test_statwin_js.py`)
- `abSplit` · `abKey` 는 `abilities.split` · `key` 와 같다(`tests/test_statwin_js.py`)

### `canon/static/agent.js`

- 대화 에이전트 패널(`chat.js` 의 `chatPanel('plot')` 이 부른다)
- 세션 머리와 목록(보관함, '이전 대화'는 옛 `Project.chats` 를 `chatLog` 로)
- 턴마다 단계 줄 · 바로 쓴 것(항목 · 턴 되돌리기) · 승인 카드 · 되묻기 카드
- 입력 상자(+ 재료, `/` 빠른 요청 `AGENT_CMDS`, 보내기 · 멈추기)와 상태 줄(권한 모드 · 대상 · 모델 · 단계 상한)
- 진행은 `pollJobs` 가 `agentJobUpdate` 로 알린다
- 권한 이름 `AGENT_MODES` · `AGENT_KINDS` 는 `agent.MODE_LABELS` · `KIND_LABELS` 와 같다(`tests/test_agent_js.py`)

### `canon/static/branches.js`

- 갈래 화면
- 작품 머리 띠(`branchStrip`)
- 띠는 화면 머리 아래 한 줄이고 집안 작품 열기는 ⋯ 메뉴(넣는 자리 `branchPlace`, 머리로 시작하지 않는 화면은 맨 위)
- 함께 쓰는 앞 화를 고친 경고와 남겨 둔 본문 이어 가기는 띠 아래 Note
- 사이드바 갈래 줄(`branchSideTag`)
- 갈래 만들기 칸(`branchFormCard`, 폴더 이름 `branchFolder` 는 `home.js` `folderOf` 와 같은 규칙)
- 만들기 칸은 화면 머리 아래에서 펴고 시작 화를 화 칸 띠로 보이며 폴더 이름은 접어 둔다
- 작품 목록 묶기(`branchGroups`)
- 작품 홈 갈래 카드(`branchHomeCard`: 비교 버튼, ⋯ 메뉴에 작품 열기 · 본편으로 올리기 · 갈래 끊기)
- 갈래 지도 줄(`branchMapRows`)은 작품 홈 갈래 카드와 갈래 비교 화면이 함께 쓴다
- 갈래 비교 화면(`viewBranches`, 공용 목차 틀 `outline.js`)
- 갈래 비교 목차(`bcToc`): 견줄 작품(집안 나무) · 이 비교(갈라진 길 · 화별 줄거리 · n화 본문 · n화 반영 뒤 상태)
- 갈래 비교 본문은 문단을 맞춰 나란히 둔다(`bcParaDiff`, 기본은 다른 문단만 `S.bcAll`)
- 갈래 비교 화면 · 띠 · 만들기 칸 시험은 `tests/test_tools_js.py`
- 이름 없는 갈래는 폴더 이름으로 부른다(`branchName`, 명령줄 `branches` 와 같은 규칙, `tests/test_branches_js.py`)

### `canon/static/cast.js`

- 인물 · 관계도 화면(공용 목차 틀 `outline.js`)
- 왼쪽 목차 `castToc`(관계도 · 등장표 · 비중별 인물, 단역이 많으면 접음 `castMinorFold`)
- 오른쪽 한 열의 쪽 `castPage`(`S.castView`: map · table · char · pair, 옮기기 `castShow`, 주소 `cast/<map · table · c:id · p:a|b>?f=` 와 옛 `?tab=` 은 `castParse`)
- 열 맨 위 시점 띠 `castBar`(좁은 칸은 아래에 붙음)
- 관계도 `castMapPage`(SVG, 화별 재생, 칸 폭에 맞추고 크게 보기 `CAST_ZOOM`, 누르면 고르기만 `castMapPick` · 고른 줄 `castMapSel`, 끌어 옮긴 배치는 localStorage)
- 인물 쪽 `castCharPage`
  - 머리 `castHead` · 보는 시점의 상태 · 상태창 수치(바뀐 양 `castStatDelta`, 카드 | 시스템 창 보기는 localStorage, 창 모양은 작품 스킨 `stat_window.skin`) · 관계 줄 `castSheetRels`(온기 막대 `castMeter`) · 비밀 · 설정과 남겨 둔 제안 · 읽기 먼저인 'AI · 서술 · 신체 · 삽화' 카드 `castEditCard`
    - 상태창 칸 모양은 `statwin.js` `swStatsBody` 와 같이 쓴다
    - 고치기 `S.castEdit`: AI에 넣기 `charContextField` · 서술 말투 `plot.js` `voiceField` · 신체 프로필 `bodyFields` · 삽화 외형 태그 `illust.js` `visualFields`
    - AI 제안 동작은 `research.js` `bodyAI`
  - 타임라인(앞뒤 `CAST_TL_NEAR` 화)
- 두 사람 쪽 `castPairDetail`(추이 그래프 · 보정 · 호칭)
- 등장표
- 인물 원은 목차 24 · 줄 36 · 머리 64px(`castAva`)
- 온기 색 구간은 `dynamics.warmth_word` 경계와 같다(`tests/test_labels_js.py`)
- 주소 읽기는 `tests/test_cast_js.py`

### `canon/static/causal.js`

- 인과율 화면
- 요소 추가·편집
- 관련 화 지도
- 영향 분석 변경안 고르기
- `elements.basis` 와 같은 모양(`elBasis`)으로 분석이 지났는지 본다(`tests/test_causal_js.py`)

### `canon/static/charlog.js`

- 상태 승인 화면 '직접 정할 것'의 인물 설정 바꾸기 줄(`scDeltaRows`, 키 `t`, 기본으로 체크하지 않음, 값 고치기)
- 반영 기록(`scHistory`)
- 인물 화면의 남겨 둔 제안(`scHeldCard`) · 설정 변경 기록(`scLogCard`) · 보는 시점의 설정(`scAt`)
- 칸 이름 `SC_LABELS` 는 `charlog.LOG_FIELDS` 와 같다(`tests/test_labels_js.py`)

### `canon/static/foreshadow.js`

- 복선 센터 화면(주소 `foreshadow[/<복선 id>]`, `viewForeshadow`, 불러오기 `fsLoad`)
- 공용 목차 틀(`outline.js`, 목차 `fsToc`: 개요 · 손볼 것 · 열린 복선 · 접은 회수한 복선 `S.fsDoneOpen`) 위에 쪽 셋: 개요 · 복선 하나 · 빈 화면
- 개요
  - 수치 `fsStats` → 손볼 것 `fsTodoCard` → 복선 지도 `fsMapCard`: 화 축 하나
  - 아크 · 구간 띠 `fsBands`
  - 줄마다 `fsTrack`
  - 거르기는 Seg `S.fsTab` · `S.fsScope` → 앞으로 회수할 것 `fsAheadCard`
- 복선 하나(`fsDetail`: 축 → 본문에 걸린 문장과 흐름 `fsFlowCard` → 회수 계획 읽기 카드 `fsPlanCard`, 고치기 `S.fsEdit`, 회수로 표시 `S.fsResolving`)
- 본문에서 고른 문장을 거는 칸은 본문 부분 수정 도구(`passage.js` `#sel-tool`)의 mode 'foreshadow'
  - `fsLinkShow` · `fsLinkHtml`: 이미 있는 복선 찾기 · 이 화 가까이 나온 후보 `fsCandidates` / 새 복선
  - 고치는 본문은 메뉴에 '복선으로'
  - 반영한 화의 읽기 전용 본문은 `illust.js` 도구에 '복선으로'
  - 640px 이하 아래 시트
- 상태 승인 화면의 복선 문장 고르기(`fsClueRows`, `q` 항목)
- `fsBands` · `fsAt` · `fsMarks` · `fsFlag` · `fsTail` · `fsAttention` · `fsTodo` · `fsTocRows` · `fsFlow` · `fsAhead` · `fsTicks` · `fsCandidates` 는 순수 함수(`tests/test_foreshadow_js.py`)
- CSS 는 JS 에서 주입

### `canon/static/illust.js`

- 집필 화면 삽화 프롬프트 카드(칸별 복사, 다시 조립, 외형 고정)
- 읽기 전용 본문에서 고르는 도구
- 인물 화면 인물 카드의 삽화 외형 태그(`visualFields`)
- 고치는 본문의 도구 버튼은 `passage.js`

### `canon/static/lines.js`

- 이야기 줄기 화면
- SVG 노선도
- 줄기 편집
- 화 붙이기
- AI 제안
- 플롯 편집기의 줄기 칸(`lineField`)과 화 카드 표시(`lineBadge`)도 여기 있다
- `storylines.span` · `tag` 와 같은 규칙이라 함께 고친다(`tests/test_lines_js.py`)

### `canon/static/play.js`

- 플레이 화면(DESIGN.md 10.4, 시안 안 A)
- 새 플레이(`#/play/new[/세계]`, 출생 카드 · 새 세계)
- 플레이(`#/play/<폴더>`: 시간 흐름 막대, 흘러간 일, 결정 장면, 끼어들기, 옆 패널)
- 지난 일 · 되감기(`/past`, `<dialog>`)
- 생애 기록(`/life`)
- 작품 홈 카드(`playHomeCard`)
- 시계 규칙은 DOM 없는 순수 함수(`playItems` · `playGap` · `playClockStart` · `playPhase` · `playTick` · `playClock`, `tests/test_play_js.py`)
- 서버는 `web.py` 의 `/api/projects/{이름}/play…` 와 `/api/play/worlds`: 구간 작업 `play_turn`(남은 반영 → 장면 → 반영, 플레이 잠금 `_play_lock`, 다음 흐름 `_play_continue`)
- 배경 `play_sketch`
- 새 세계 `play_world`
- 앞 둘은 작업 목록에 넣지 않는다(`app.js` `QUIET_JOBS`)

### `canon/static/publish.js`

- 집필 화면 본문 띠의 분할 복사 버튼(`copySplit`: 복사 + ▾ 메뉴 `copyMenu` 의 줄바꿈 형식 · 제목 줄 · .txt)과 '여러 화 내보내기' 대화상자(`exportDialogHtml`)
- 텍스트와 HTML 을 함께 클립보드에 넣는다(보안 연결이 아니면 복사 이벤트로)
- 클립보드가 막히면 .txt 내려받기

### `canon/static/setupchat.js`

- 설정 도우미의 대화로 다듬기 패널(`CHAT_TOPICS.setup`)
- 칸별 변경안과 지금 값 비교(이미 채운 칸을 바꾸는 부분은 기본으로 체크하지 않음)
- 새 인물을 고르지 않으면 그 인물과의 관계는 끔
- 방향 여러 안(`chat.js` 의 `optionsCard`)
- 적용 · 적용 취소
- 칸 이름(`SETUP_KEYS`, `SETUP_CHAR_LABEL`)과 부분 id 는 `setupchat.KEY_LABELS` · `CHAR_LABELS` · `part_ids` 와 같다

### `canon/static/statwin.js`

- 상태창 수치 화면(공용 목차 틀 `outline.js`)
  - 주소 `statwin/<인물 id>` · `statwin/_frame` · `statwin/_decor`
  - 왼쪽 목차 `swToc`(작품 틀 · 처음 수치, 꾸미기, 비중별 인물, 상태창 없는 인물 접음, 스킬 도감)
  - 인물 쪽 `swPersonPage`: 머리 `swHead` · 지금 상태창 `swNowCard` · 본문에 넣을 상태창 `swTextCard` · 화별 변화 `swLogCard`
  - 지금 상태창은 읽기 먼저이고 '고치기'로 이 카드만 편다(`S.swEdit`, `swEditor`)
  - 고치는 칸 옆 계산 값 `swCalc`
  - 항목 고치기 · 순서 `swMove`
  - 틀 · 작품 틀
  - 복사
  - 화별 변화는 바뀐 화 목록(`swChangeParts`, 목록은 같은 이름끼리 짝지음) | 표
  - 작품 틀 · 처음 수치 쪽 `swFramePage`: 작품 틀 · 인물별 처음 수치 표 `swInitCard` · AI 처음 수치 제안
  - 1화 반영 뒤 잠금 `swLocked`, 잠긴 표는 0화 기록의 시작 값 `swStartValues`
  - 틀 `SW_PRESETS` 는 `statwin.PRESETS` 와 같음
  - 꾸미기 쪽 `swDecorPage`: 창 이름 · 본문 서식(읽기 카드) · 화면 스킨 `SW_SKINS` · AI 안 고르기와 적용 취소
- 상태창 칸 모양 `swStatsBody`(카드 칸 | 작품 스킨 창, 칩은 `abChip`)는 인물 화면 `cast.js` `castSheetStats` 와 함께 쓴다
- 상태 승인 화면의 상태창 줄(`swDeltaRows`)
- `swResolve` 는 `statwin.resolve` 와 같은 규칙(`tests/test_statwin_js.py` 가 node 로 맞춰 본다)

### `canon/static/tofix.js`

- 고칠 곳 화면(사이드바 도구, 주소 `tofix`, `viewToFix`: 남음 · 고침 · 모두, 메모 고치기, 본문에서 고치기 `tofixGo`)
- 고칠 곳 화면은 공용 목차 틀이다(화별 목차 `tofixToc`, 화마다 카드 한 장)
- 거르기는 머리의 나눔 버튼(Seg)이다
- 줄은 앞뒤 문맥과 함께 보인다(`tofixContext`)
- 메모는 읽는 글이고 ⋯ '메모 고치기'로 그 줄만 칸을 편다(`S.tofixEdit`, Ctrl+Enter 저장 · Esc 취소)
- 본문 도구의 '나중에 고치기'와 메모 칸(`showTool` 을 감싼다, mode `tofix`)
- 밑줄(`tofixRanges` 를 `marks.js` `allRanges` 가 함께 그림)
- 집필 화면 본문 띠의 '고칠 곳 N'(`tofixBtn`, `tofixNext`)
- 서버 응답은 to_fix 만 가져온다(`takeToFix`)
- `tofixSpot` · `tofixList` 는 `tofix.spot` · `collect` 와 같은 규칙(`tests/test_tofix_js.py`)

### `canon/statwin.py`

- 상태창 수치
- 인물의 수치(`CharacterState.stats`)가 하나라도 있으면 켜짐
- 바뀐 항목만 합치기(`merge`, `+3` · 단위 붙은 돈 `+300` · 한도 붙은 수 `4.3/60L` + `-0.7` · 목록 `+독 내성` / `-은신` 계산은 `resolve`)
- 기록(`Project.stat_log`, 목록은 더한 것 · 뺀 것 `diff`)
- 작가 수정(`set_stats`)
- 화별 비교표
- 본문 상태창 글(`render`, 서식 `Project.stat_window`)
- 본문 상태창 읽기 · 대조(`read_windows`, `window_warnings`: 반영하면 될 값 `after_delta` 와 다르면 변경안 정리 `pipeline.clean_delta` 가 경고로)
- 0 아래 · 한도 위 경고(`out_of_range`, `range_warnings`)
- 처음 수치 AI 제안 정리(`clean_init`, AI 호출은 `pipeline.suggest_initial_stats`, 1화 반영 뒤에는 막음, 프롬프트 `prompts.stat_init_prompt`)
- 꾸미기(AI 안 정리 `clean_options`, 화면 스킨 `SKINS`, 창 이름 · 작품 틀은 `StatWindow.title` · `names`, AI 호출은 `pipeline.suggest_stat_window`, 프롬프트 `prompts.stat_window_prompt`)
- 프롬프트 규칙
  - `write_rule(p, n)`: 넣는 방식 `Project.stat_window.prompt` 가 json 이면 지금처럼
  - `write_rule` 은 lines 면 이번 화 인물(`episode_cast`)의 수치 줄과 도감 줄을 예산 `context.BUDGET['stat_lines']` 까지 넣는 `lines_block`(서식 예시는 플롯에 상태창 장면이 있을 때만 `wants_window`)
  - `write_rule` 은 none 이면 빈 글
  - 쓰기 컨텍스트의 인물 상태는 `prompts.write_states` 가 lines · none 에서 stats 를 뺀다
  - `state_rule`
  - 검수 `check_rule`: 직전 화 수치와 대조
  - 인벤토리 항목이 있으면 꺼내 쓰는 물건과 지금 차림 나누기 `inventory`
- 명령줄 `statwin`
- LLM 호출 없음

### `canon/storylines.py`

- 이야기 줄기
- 메인에서 갈라졌다 합류하는 서브플롯 · 과거 회상 · 외전 · 인물 이야기(`Storyline`)
- 화의 줄기는 `EpisodePlot.storyline`(주로 따라가는 줄기, 비면 메인)과 `threads`(끼어드는 장면)
- 범위(`span`)
- 프롬프트 블록(`plan_block`, `episode_block`, `state_rule`)
- 명령줄 노선도(`ascii_map`)
- LLM 호출 없음
- 제안과 반영은 `pipeline.suggest_storyline` / `apply_storyline`

### `canon/timeline.py`

- 작품 속 시간
- 화가 끝난 시점(`Episode.time`, `StoryTime`: 날수 · 시간대 · 날짜)
- 플롯의 시점(`EpisodePlot.time`)
- 기한(`Timeline.deadlines`, `Deadline`)과 남은 날(`left`)
- 상태 변경안 정리 · 반영 · 되돌리기(`clean_delta`, `apply_delta`, `revert`, 기한은 `Snapshot.deadlines`)
- 작가가 기한 고치기(`upsert`, `remove`)
- 프롬프트 블록(쓰기 · 검수 `episode_block`, 요약 줄 `tag`, 기획 `plan_block`, 상태 `state_block` · `state_rule`, 검수 `check_rule`, 기한은 `context.BUDGET["deadlines"]`)
- 날짜 · 요일 계산(1일째 날짜 `Timeline.start_date` 가 있으면 날짜로 보임 `dated`, `calendar`, `day_label`, `when`, 본문 날짜 → 날수 `day_from_text`, 쓰기 블록의 요일 셈 `weekday_hint`. 저장은 날수)
- 기록이 없거나 꺼지면 블록이 빈다
- 명령줄 `time`
- LLM 호출 없음
- 화면은 `static/timeline.js` (`tlLeft` · `tlDay` · `tlCalendar` · `tlDayLabel` · `tlWhen` · `tlISO` · `tlDayOf` 는 `left` · `current_day` · `calendar` · `day_label` · `when` · `date_of` 와 같은 규칙, `tests/test_timeline_js.py`)

### `canon/tofix.py`

- 고칠 곳
- 작가가 본문 글에 단 '나중에 고칠 곳' 표시와 메모(`Episode.to_fix`, `ToFix`, 상태 open · done)
- 글 찾기(`spot`, 담을 때 자리에 가까운 것)
- 달기(`add`, 저장된 본문에 있는 글만 · 같은 자리면 메모만 바꿈) · 고치기(`update`) · 지우기(`remove`)
- 모으기(`collect`)
- 본문을 바꾸지 않아 웹 `…/tofix` 는 자동 집필 중에도 받는다(작품 잠금 안에서 `_edit`)
- 화면의 작품 전체 저장(`_save`)은 디스크 표시를 지킨다
- 프롬프트에 넣지 않는다
- 명령줄 `tofix`
- LLM 호출 없음

# 모듈 지도: 데이터 · 프롬프트 · 파이프라인

이 파일의 줄은 [AGENTS.md](../../AGENTS.md) 의 '문서 줄 규칙'을 따른다.

### `canon/autorun.py`

- 자동 집필
- 목표 화까지 (스토리보드 `_board`, `Policy.storyboard` · `stop_on_board_warnings`) → (큐 시트 `_cues`, `Policy.cue_sheet`) → write → check + state → 정책(`Policy`) 통과 시 반영을 반복
- 배치(`llm.BatchLLM`) 켜고 끄기
- 비용·시간 추정
- `autorun.json` 에 진행 기록
- 서버 재시작 후 이어 가기
- 화면은 `static/auto.js`

### `canon/board.py`

- 화별 스토리보드 계산
- 켜짐(`on`)
- 직전 화 원문(`prev_text`)
- 만든 입력의 지문(`basis`) · 낡음(`stale`, 본문을 쓰기 전에만)
- 날수 · 요일(`days`, `weekday`: 작품 기준이 없으면 직전 화 기록 글의 요일에서)
- 시간 한 줄(`time_line`)
- 상태창 단계마다 바뀌기 전 · 뒤 값(`steps`, `statwin.resolve`) · 창 글(`window_text`)
- Canon 경고(`checks`: 맡은 장면 없는 사건 · 모르는 id · 값 범위 · 관계 단계를 두 칸 넘게 옮기는 플롯 `pace.plot_warnings`)
- 자동 집필 멈춤 이유(`stop_reasons`, `STOP_KINDS`)
- 화면 값(`view`)
- LLM 호출 없음
- AI 호출은 `pipeline.make_storyboard`
- 화면은 `static/board.js`

### `canon/cancel.py`

- 웹 작업 멈추기 신호
- `jobs.start` 가 스레드마다 둔다
- LLM 호출 전과 저장 전에 `check()` 로 확인해 멈춘 작업이 결과를 저장하지 못하게 한다

### `canon/cli.py`

- 명령줄 (`python -m canon ...`)
- 전체 명령 목록은 `python -m canon --help`
- 단편 흐름: `new` → `style` → `arc` → `plot` → (사용자 수정) → `confirm` → (스토리보드 → 큐 시트, 웹 집필 화면 · 자동 집필) → `write` → `check` → `update` 반복
- `run` 이 쓰기 · 검수 · 반영을 자동으로 되풀이한다
- 장편(`new --serial`)은 `arc` 대신 `series` 를 한 번 부른다
- 장편은 아크마다 `nextarc` → `plot` → `confirm` → `run` → `recap` 을 되풀이한다
- 명령별 쓰임
  - `abilities`: 스킬 · 특성 도감(설명 · 효과 · 대가, 가진 인물과 얻은 화) 보기
  - `arcs`: 장편 진행 보기
  - `branch`: 반영까지 끝난 전개를 지우지 않고 n화부터 다른 전개를 쓰는 갈래(원본은 그대로)
  - `branch-compare`: 갈래 비교
  - `branches`: 갈래 보기
  - `cast`: 인물별 등장 · 지금 관계 · 화별 타임라인(바뀐 설정 포함) 보기
  - `compare`: 같은 화를 두 백엔드로 써서 가려 비교
  - `convert`: 단편을 장편으로 바꾸기(단편 전체가 아크 1)
  - `convert --rebuild`: 단편을 씨앗으로 앞부분을 다시 짜기
  - `convert --undo`: 전환 되돌리기
  - `dex`: 원형 도감 보기 · 인물 빈 칸 채우기 · 주사위
  - `edits`: 수정 기록 보기 · 되돌리기 · 내보내기
  - `export`: 다른 사이트에 붙여 넣을 본문 내보내기
  - `fix`: 본문 일부를 AI 후보로 고치기
  - `hook`: 1~3화 흡입력 판정
  - `illust`: NovelAI 삽화 프롬프트
  - `insert`: 짜 둔 플롯 사이에 외전이나 새 화 넣기 · 안 쓴 화 빼기(뒤 화 번호와 범위 · 복선 · 요소 · 줄기를 함께 옮김)
  - `insert --delete`: 마지막으로 쓴 화 지우기
  - `learn`: 수정 기록에서 문체 규칙 후보 찾기
  - `lines`: 서브플롯 · 과거 회상 · 외전 이야기 줄기를 만들고 화에 붙이기
  - `look`: 인물 외형 태그
  - `map`: 장소와 인물별로 옮겨 다닌 길 보기
  - `map fill`: OpenStreetMap 지도의 빈 블록 채우기
  - `map gen`: 마을 만들기
  - `map gen city`: 도시 만들기
  - `map travel`: 이동 시간 검사
  - `model`: 작품이 쓸 단계 프리셋(단계별 백엔드 · 모델 묶음) 고르기
  - `openings`: 1~3화 여는 방식 여러 안(플롯 `--plot` · 본문 블라인드 비교)
  - `pov`: 화별 서술 시점(남주 → 여주 등) 보기 · 정하기
  - `promote`: 본편 고르기
  - `rewrite`: 피드백 · 검수 결과 등을 반영해 그 화를 다시 생성(새 판과 바꿀지 고르기, 이전 판 되돌리기)
  - `rework`: 재구성의 다듬기 화
  - `setupchat`: 설정을 말로 다듬기
  - `stats`: 화별 문체 지표 확인
  - `styles versions` · `restore`: 문체 버전
  - `time`: 작품 속 시간(화별로 끝난 시점, 기한) 보기 · 고치기
  - `tofix`: 본문에 담아 둔 '나중에 고칠 곳' 보기 · 고침으로 바꾸기
  - `usage`: AI 사용량과 추정 비용 보기
  - `voice`: 시점 인물별 서술 말투

### `canon/context.py`

- 장편 프롬프트 크기 관리
- 블록 재기(`blocks`, 사용량 기록 · 연구 화면)
- 블록 글자 예산(`BUDGET`)
- 관련 사실(`pick_facts`) · 비밀(`pick_secrets`) · 떡밥(`rank_foreshadows`) · 인물이 아는 정보(`pick_knows`, 뺀 수는 `prompts.knows_note`) 고르기
- 기획 프롬프트 인물(`planning_cast`)
- 인물 이름(`names_of`: 세 글자 이름은 성을 뗀 이름도, `metrics.name_forms`)
- 이름으로 켜는 인물(`named_ids` · `name_pattern`, 남은 예산 `fit_named`) · 마지막으로 나온 화(`last_seen`)
- 검수용 옛 본문 단락 찾기(`recall`, 질문 여러 개는 색인 `PassageIndex` 하나로, 검수 넓히기도 이 색인)
- 진술과 겹치는 줄 · 사실(`related_lines` · `related_facts`, 셈이 있는 진술은 셈이 있는 줄을 앞세움 `has_count`)
- LLM 호출 없음
- 단편 경로는 쓰지 않는다

### `canon/cue.py`

- 집필 경로의 화별 큐 시트(`Episode.cue_sheet`): 켜짐(`on`)
- 입력 지문(`ep_basis`: 스토리보드 입력 + 스토리보드 내용) · 낡음(`stale`)
- 넣기 · 지우기(`set_episode`)
- 화면 값(`ep_view`: 낡음 · 핵심 대사가 들어간 수)
- 큐 시트 집필 실험(사이드바 '본편과 분리', 주소 `cue/<화>`, 실험 사본은 화의 큐 시트를 지움 `before`): 한 화를 악보처럼 큐로 나눈 큐 시트(`CueSheet`: 조성 · 끝 종지, 큐 `Cue`: 기능 T · S · D · 긴장도 · 템포 · 편성 · 일 · 핵심 대사 `CueLine` · 끝 상태 · 글자 수)
- AI 없는 뼈대(`from_board`)
- 정리(`clean`) · 지문(`basis`) · 넣기(`set_sheet`)
- 시험할 화(`candidates`, 반영 끝난 화는 사본을 되돌림 `before`)
- 조건(`CONDITIONS`: oneshot · score · cues)
- LLM 없는 채점(`score`: 핵심 대사 `line_hits` · 되풀이 `repeats` · 이음매 `seams` · 여운 닫기 `closing` · 정지 장면 끝 `still` · 줄표로 자른 끝 `cut` · 큐별 `cue_rows` · `tempo_order`)
- 비용 추정(`estimate`)
- 실행(`run`, 실험 기록 · 블라인드 비교본 kind cue)
- AI 호출은 `pipeline.make_cue_sheet` · `write_scored` · `play_cues`
- 프롬프트 `prompts.cue_sheet_prompt` · `cue_sheet_block` · `cue_score_prompt` · `cue_head` · `cue_step` · `cue_play_prompt`(k번째 요청이 앞 요청과 응답을 통째로 품음)
- 작품에 저장하지 않고 `cuelab/<화>.json`(`store.load_cuelab` · `save_cuelab`)
- 화면은 `static/cue.js`
  - 실험 화면과 집필 화면의 큐 시트 카드 `cueCard`
  - 역설계 실험도 편집기를 함께 씀(열쇠 `rev:<화>`) · 쓴 화의 접은 카드 `cuePanel` · 켜기 `cueToggle`
  - 편집기 `cueEditor` 와 막대 `cueScore` 는 둘이 함께 씀
  - 고치는 시트는 열쇠마다 `cueBind`
  - 순수 함수 `cueLinesParse` · `cueLinesText` · `cueBars` · `cueCurveOk` · 말투가 빈 핵심 대사 인물 `cueVoiceGaps`
  - `tests/test_cue.py` · `test_cue_write.py`
- 웹은 작업 `cues`
- 쓰기 작업의 `cues`(none)
- `…/episodes/{n}/cue-sheet`
- `…/cue-setting`

### `canon/features.py`

- 상태 변경안 수명 주기에 기능이 끼어드는 자리
- 정리(`CLEAN`) · 반영(`APPLY_FIRST` 새 인물 직후, `APPLY_LAST` 기록 전) · 되돌리기(`REVERT_FIRST` 스냅샷으로 덮기 전, `REVERT_LAST` 뒤) 목록
- `pipeline.clean_delta` · `apply_delta` · `revert` 가 목록을 차례로 부른다
- 사람 검토 없이 반영할 때(자동 집필 · `run -y` · 플레이)는 `hold`(`HOLD`)가 작가가 골라야 하는 제안을 빼서 남겨 둔다. 관계 단계와 반대인 유형 바뀜(`pace.hold`)은 남기지 않고 빼서 경고에 적는다
- 상태를 가진 기능을 더할 때는 `pipeline.py` 를 고치지 않고 기능 모듈에 훅을 두고 이 목록에 넣는다(목록 순서가 부르는 순서)
- LLM 호출 없음

### `canon/findings.py`

- 검수 세션
- 회차(`Episode.rounds`, `CheckRound`: 새로 · 다시 · 사라진 지적 id)마다 검수 결과를 지적 목록(`Episode.findings`)에 합친다(`merge`, `pipeline.apply_check` 가 부름)
- 지적 `Finding`: 상태 open · fixed · kept · wrong, 메모, 심각도 crit · mid · low, 처리 기록 `log`
- 같은 문장(`same_quote`)이면 이어 붙이고 kept · wrong 과 작가가 정한 심각도는 지키며 fixed 가 다시 나오면 연다
- 열린 지적(`open_findings`)
- 검수가 끝났는지(`check_done`, `home.js` `checkState` 의 done 과 같은 규칙, 작품 목록 `open_checked`)
- 자동 집필이 세는 지적(`counted`, 사소 빼기)
- 작가가 정하기(`set_status` · `set_severity`, 웹 `set_finding`, 명령줄 `check --keep` · `--sev`)
- 고침안이 건드리는 다른 지적(`touches`)
- 지적 하나 다시 검수 결과 넣기(`settle`: 고침으로 닫기, 딸린 지적 `add_children`)
- 새 판(`new_version`: 결정한 지적만 남김)
- 세션 비우기(`clear`)
- 합치기는 출처(`ConsistencyIssue.origin`: ai · rule)가 같은 지적끼리
- 규칙 지적의 다시 검수는 `pipeline.recheck_finding` 이 LLM 없이 판정만
- 고침안 · 다시 검수의 AI 호출은 `pipeline.propose_fixes` · `apply_fix` · `undo_fix` · `recheck_finding`
- 프롬프트 `prompts.fix_prompt` · `recheck_prompt`(앞부분은 검수와 같은 `check_material`)
- 결정은 검수 프롬프트에 넣지 않는다
- LLM 호출 없음

### `canon/jobs.py`

- 웹의 오래 걸리는 AI 작업을 스레드로 돌리는 메모리 작업 목록
- 중복 실행 막기
- 진행률
- 작업이 맡은 화를 저장 덮어쓰기에서 지키기(`owned_episodes`)
- 멈추기(`stop`)

### `canon/metatail.py`

- 본문 앞뒤에 섞인 작업 설명(메타 코멘트) 찾기
- 확실한 머리말 · 꼬리 떼기(`split`): 대사 · 대괄호 글을 뺀 서술에 Canon 작업 낱말(`STRONG`: 스타일 프로필 · 플롯 · 본문을 · 요청하신 · 짚어 둘 …)이 있고 존댓말이 반 넘는 앞뒤 문단, 'n화 본문입니다' 머리말, '작가 메모' 머리와 목록, 한글이 거의 없는 영어 메모. 서술이 원래 존댓말인 작품은 작업 낱말 둘 이상
- 응답 전체가 작업 설명 · 거절 · 되묻기인지(`whole`)
- 흔한 말(`SOFT`: 원고 · 다음 화 · 원하시면 …)만 있는 앞뒤 문단은 떼지 않고 경고(`warnings`). 작가물 · 편지 · 시스템 알림 · 이야기꾼의 맺음말을 지키려는 것(2026-10-31 적대적 검토)
- `pipeline._write` 가 떼고(서버 기록 warning) 다시 쓰며(`whole`), `pipeline.style_drift` 가 경고를 붙인다
- LLM 호출 없음

### `canon/pipeline.py`

- 단계별 로직
- 차례: 설정 제안 → 스타일 분석 → 기승전결 → 화별 플롯 → 스토리보드 → 큐 시트 → 본문 → 검수 → 상태 추출/반영
- 화별 플롯
  - 대화로 다듬기 `revise_plot`/`apply_revision` 포함
  - 대상 `chat_target`: 고른 아크 · 다음 아크
  - 아크 칸 · 부 구성 변경안
  - 방향 여러 안
  - 플롯 · 다음 아크(`apply_arc`)가 데려온 새 인물은 후보 `Project.cast_candidates`(아크 주요 인물에 있으면 플롯에 없어도 남김 `sync_candidates`)
  - 새 장소는 `Project.place_candidates` 로 두고 화 확정 `confirm_plot` 때 등록
  - 작품 전체 저장에서 본문이 있는 화의 플롯은 디스크 것으로 둔다(`keep_locked_plots`, 줄기 표시 `LOCKED_FREE` 만 받음, `web.put_project`)
  - 상태 변경안 정리 `clean_delta`
  - 설정 칸 하나 AI 후보 `suggest_field` · 단계 `field_stage`
  - 칸 목록 `prompts.FIELD_IDEAS`
  - 인물 칸 키 `prompts.idea_key`
  - 빈칸 제안은 이미 있는 인물도 빈 칸만 `fill_character`
- 스토리보드: `make_storyboard` · `set_storyboard` · 낡음 지문 `board_basis`, `write_episode(use_board=)`
- 큐 시트: `make_cue_sheet`, 넣기는 `cue.set_episode`, `write_episode(use_cues=)`
- 검수
  - 장편 넓혀 찾기 `widen_check`: 첫 검수에 없던 옛 단락이 근거로 나온 진술만 다시 묻기
  - `Settings.check_widen`
  - 프롬프트 `prompts.widen_prompt`
- 장면 연출은 플롯에서 초안 `draft_stage` · 본문에서 뽑기 `extract_stage`(박자가 빈 응답이면 한 번 다시 묻기) · 검수 때 함께 뽑기 `stage_extract_all` · 적용 `apply_stage` · 적용 취소 `undo_stage`(`stage.py`)
- 동선 지적 고침안은 새 문장을 더한 안을 거른다(`clean_fixes` 의 `_adds_sentence`)
- 장편은 부 계획(`plan_series`) → 다음 아크(`plan_next_arc`/`apply_arc`, 기획 전 경고 `plan_ahead`: 본문 없는 아크 2개 이상 · 요약 없는 끝난 아크 · 부, 막지 않음) → 아크 · 부 요약(`recap`/`apply_recap`)
- 단편 → 장편 전환은 이어 쓰기 `propose_conversion`/`apply_conversion`
- 재구성 `propose_rebuild`/`apply_rebuild`(옛 상태 변경안 재사용 `carried_delta`, 다듬기 `propose_rework`/`accept_rework`)
- 되돌리기 `undo_conversion`

### `canon/prompts.py`

- 프롬프트 템플릿
- 화별 컨텍스트 조립(`build_episode_context`)
- 작업지시서(`episode_brief`, `state_brief`)
- 인물 고르기는 `static_characters` · `side_characters` · `roster_line` · `cast_block` 이 `Character.context` 를 따른다
- 장편은 플롯 인물 목록 밖이라도 이름이 나온 조연을 넣는다(쓰기 `named_block`, 검수 `check_cast`, 상태 변경안)
- 오랜만에 나오는 인물은 `return_block`
- 스토리보드 만들기 `storyboard_prompt`(Canon 이 센 값 `canon_values_block`)
- 쓰기에 넣는 `board_block`(직전 화 본문 뒤, 이번 화 플롯 바로 앞, 시간 · 이동 블록을 대신함)
- 직전 화 블록 `prev_block`(스토리보드를 넣는 화와 스토리보드 만들기만 원문 전체, `build_episode_context(full_prev=)`)
- 쇠맛을 줄이는 쓰기 규칙: 블록 차례 한 줄 `priority_line`
- 장편 관계 줄 `serial_relations` · 인물 상태 `fit_states`(예산 `context.BUDGET` 의 `relations` · `states`)
- 예시 문단이 있는 작품의 스타일 프로필 `style_rules_view`(칸마다 `STYLE_FIELD_LIMIT`, 예시 문단이 앞)
- 스토리보드 깨지 않을 것을 검수에 `protect_block` · `protect_check_rule`
- 지시 수 · 크기 상한 시험 `tests/test_write_budget.py`
- 화에 큐 시트가 있으면 `episode_prompt` 맨 끝에 `cue_write_block`(실험의 조건 score 와 같은 글, `use_cues=False` 면 뺌)
- 화별 플롯 초안(`plot_prompt` · `serial_plot_prompt`)은 범위 안 · 범위 뒤 3화(`PLAN_AHEAD`)의 이미 정해진 화를 `fixed_plots` · `fixed_block` 으로 넣고 요구사항에 `fixed_rule` 을 붙인다(장편은 `context.BUDGET["plan_fixed"]`, 한 화 초안은 `ahead=False`)
- 장편 화별 플롯 초안은 `[관계]` 뒤에 지금 관계 단계 라벨(`plan_stage_block`, 예산 `context.BUDGET["plan_stages"]`), 장편 `plot_rules` 에 '단계는 한 화에 한 칸' 한 줄
- 검수 요구사항의 관계 단계 한 줄(`stage_check_rule`, 관계 수치가 있을 때만)
- 관계 설정 `rels(plan=)`: 가 닿을 곳(`Relationship.destination`)은 기획 프롬프트에만, 말로 넣는 기획은 `destination_block`
- 다음 아크 기획(`next_arc_prompt`)은 관련 확정 사실(`plan_facts`) · 작품 속 시간(`time_plan`, 끝 줄 `ARC_TIME_RULE`) · 주역 밖 기획 인물 상태(`plan_side_states`)를 예산(`context.BUDGET` 의 `plan_facts` · `plan_states`) 안에서 넣는다

### `canon/schema.py`

- pydantic 데이터 스키마
- 모든 상태는 `Project` 하나(`project.json`)에 저장
- 인물 신체 프로필(`Character.body`)은 작가 메모라 AI 응답 형식(`SkipJsonSchema`)과 프롬프트(`llm.dump` 의 context `prompt`)에서 빠진다
- 이 칸을 다루는 AI 호출은 신체 프로필 제안(`pipeline.suggest_body`)뿐이다
- 미성년(`cast.is_minor_age`)이면 쓰리사이즈를 제안하지 않는다
- 인물 프롬프트 넣기(`Character.context`: auto 비중대로 · always 늘 · off 이름만)도 작가 전용이라 같은 방식으로 빠진다
- 인물 프롬프트 넣기를 고르는 규칙은 `context.core_ids` · `off_ids` · `without_off`(모두 auto 면 예전 규칙과 같다)
- 화별 쓴 사건 체크(`Episode.events_done`, 사건 글 목록)는 집필 화면 표시용이라 `EpisodePlot` 밖에 두어 프롬프트에 들어가지 않는다
- 지금 본문을 쓴 모델(`Episode.written_by`, 판마다 `TextVersion.model`)도 프롬프트 밖이다. 값은 `usage.model_id` 의 '<백엔드>:<모델>' 이나 'import', 모르면 빈 칸
- AI 가 본문 전체를 쓰는 호출자가 `pipeline.writer_of(llm)` 을 `replace_text(written_by=)` · `set_candidate(model=)` · `research.save_compare(models=)` 로 넘긴다. 작가 수정은 바꾸지 않는다(수정 기록 `edits`)
- 인물 지금 차림(`CharacterState.attire`, 옷 · 상처 · 지닌 물건)은 지금 값만 덮어쓰고 지난 값은 스냅샷
- 차림 규칙은 `prompts.ATTIRE_STATE_RULE` · `attire_write_rule` · `attire_check_rule`
- 인물 감정(`CharacterState.emotional_state`)은 맞서는 감정이면 두 층 라벨('겉: … / 속: …', '머리: … / 몸: …'). 상태 규칙 `prompts.LAYER_STATE_RULE`, 찾기 `LAYER` · `layered`, 검수 규칙 `layer_check_rule`(두 층 라벨이 있을 때만). 쓰기 규칙은 없다
- 작품이 쓸 단계 프리셋(`Settings.model_preset`, 비우면 전체 설정)은 `settings.project_preset` 이 찾고 `stage_provider` · `stage_model` 이 지금 작업의 작품(`usage.scope`)에서 저절로 쓴다
- 화별 스토리보드(`Episode.storyboard`, `Storyboard`: 장면 · 시간 · 상태창 바뀐 양 · 이동 · 끝 차림 · 넘겨받을 것 · 깨지 않을 것 · 경고)는 상태 승인 대상이 아니다
- 스토리보드 켜기는 `Settings.storyboard`(비우면 장편 켬 · 단편 끔)
- 화별 큐 시트(`Episode.cue_sheet`, `CueSheet`)도 상태 승인 대상이 아니다
- 큐 시트 켜기는 `Settings.cue_sheet`(비우면 장편 켬 · 단편 끔)

### `canon/settings.py`

- 사용자 설정(LLM 프로바이더, 모델, API 키, 로컬 서버, 단계별 백엔드)
- 웹 설정 화면에서 저장하면 `~/.canon/config.json` 에 들어간다(`CANON_CONFIG` 로 경로 변경)
- 환경 변수가 있으면 파일보다 우선한다
- 단계 이름 목록은 `STAGES`
- 단계별 환경 변수 이름은 `stage_env`
- 기본 모델은 `DEFAULT_MODEL`
- 작품별 단계 프리셋은 `project_preset` · `stage_provider` · `stage_model`

### `canon/static/auto.js`

- 자동 집필 화면(`viewAuto`, 서버 `autorun.py`)
- 실행이 있으면 공용 목차 틀이다(목차 `autoToc`: 지금 실행 · 멈춘 이유 · 검토 없이 반영한 화 · 진행 기록 · 승인 정책)
- 실행이 없으면 시작 칸 하나이고, 쓸 화가 없으면 빈 화면(`autoEmpty`)
- 머리 주 버튼은 그때 할 일 하나(n화 변경안 검토하기 · 이어 가기 · n화까지 자동 집필 시작)
- 중지 · 설정을 바꿔 새로 시작은 머리 '실행 ▾' 메뉴
- 지금 실행 카드는 화 칸 띠(`autoCells`, 40칸까지)와 수 칸 넷
- 멈춘 이유마다 갈 곳 버튼(`autoReasonLink`: 검수 결과 · 관계도 · 그 화 읽기)
- 진행 기록은 이번 실행을 화별로 묶는다(`autoLogGroups`, '모든 줄'은 예전 표)
- 승인 정책은 읽기 카드(`autoPolicySummary`)이고 멈춘 실행에서만 '고치기'로 칸을 편다
- 시험은 `tests/test_tools_js.py`

### `canon/store.py`

- `projects/<이름>/project.json` 저장
- 본문을 `episodes/NN.md` 로 내보내기
- 읽기 전용 GET 의 작품 캐시(`load_view`, 같은 판이면 검증을 건너뜀, 돌려받은 작품은 고치지 않음, 웹은 `web._view`)
- 화면 저장 기록(`writer`, `edit_rev` · `saved_by`, 파일 끝만 읽음)
- 검토를 기다리는 AI 결과와 실패한 작업(`pending.json`, `load_pending` / `edit_pending`)

### `canon/updater.py`

- 코드 자동 업데이트
- `origin/main` fast-forward
- 의존성 설치
- 프로세스 재시작
- `serve` 가 시작 때와 주기적으로 부른다
- `POST /api/update/check`(머지 때 GitHub Actions `notify-server.yml`)는 `wake` 로 바로 부르게 한다

### `canon/web.py`

- 웹 UI 서버(`python -m canon serve`)
- CLI 와 같은 store · pipeline · prompts 를 쓰고 화면은 `canon/static/` 의 정적 파일이다
- AI 가 만든 제안(설정, 문체, 구조, 상태 변경안)은 바로 저장하지 않고 돌려준다
- 사용자가 화면에서 고르거나 고친 뒤 저장 요청을 보낼 때 반영한다
- 오래 걸리는 AI 작업은 `jobs.start` 로 돌린다
- 읽기 전용 GET 은 `_view`(`store.load_view`)로 작품을 읽는다
- 작품 전체 저장은 `put_project`

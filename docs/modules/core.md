# 모듈 지도: 데이터 · 프롬프트 · 파이프라인

이 파일의 줄은 [AGENTS.md](../../AGENTS.md) 의 '문서 줄 규칙'을 따른다.

### `canon/autorun.py`

- 자동 집필
- `wanted(name)`: 도는 실행에 받아 둔 일시정지 · 중지 요청. 웹 `AutoView.want` 로 보내 화면이 지금 단계가 끝날 때까지 '멈추는 중'을 보인다
- 목표 화까지 (스토리보드 `_board`, `Policy.storyboard` · `stop_on_board_warnings`) → (큐 시트 `_cues`, `Policy.cue_sheet`) → write → (서술 다듬기 `_polish`, `Policy.polish`, 다듬을 화 `Run.polish_due`) → check + state → 정책(`Policy`) 통과 시 반영을 반복
- 관계 정책(`max_shift` · `stop_on_stage`)은 작품 복사본에 `features.hold` 로 뺀 변경안을 반영해 본다(`review_reasons`)
- 그래서 관계 정책은 실제 반영(`put`)과 같은 제안만 센다
- 배치(`llm.BatchLLM`) 켜고 끄기
- 배치를 취소하지 못하면 배치 이름을 서버 로그(`canon` 로거)에 경고로 남긴다(`_cancel_batches`)
- 오류로 멈추면 호출 경로를 서버 로그에 남긴다
- 비용·시간 추정
- 실행 중 토큰 · 비용(`Run.tokens_in` · `cost`)은 `Runner._call` 이 `usage.collect()` 로 모은 단계 안의 모든 호출을 더한다(형식 고치기 재시도, 검수의 여러 호출, 다른 스레드의 동작 검사)
- 실행 중 비용은 `usage.totals` 로 사용량 화면과 같은 값(캐시 · 배치 요금)이다. 기록하지 않는 LLM(mock)은 마지막 호출의 `last_usage` 로 짐작한다
- 로그 줄(`LogEntry`)의 `tokens_out` 은 단계 안 호출의 합이고 `calls` 에 호출 수를 남긴다. 옛 기록은 호출 하나로 읽는다
- 비용 · 시간 추정(`_measured`)은 지난 로그의 출력 토큰을 호출 수로 나눠 호출 하나의 평균으로 쓴다
- 정착 문체 흐름 멈춤(`Policy.max_style_distance`, 0 이면 끔, `anchor.rolling`)
- `autorun.json` 에 진행 기록
- 서버 재시작 후 이어 가기
- 화를 반영할 때마다 작업의 `step_ep` 를 그 화로 고친다(화면 알림 `notify.js`)
- 반영에서 뺀 항목(`pipeline.apply_delta` 가 돌려준 것)은 화마다 경고 기록으로 남긴다. 검토 화면 없이 승인한 반영도 같다
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
- AI 호출은 `pipeline.make_storyboard`, 작가 요청대로 고치기는 `pipeline.revise_storyboard`
- 화면은 `static/board.js`

### `canon/cancel.py`

- 웹 작업 멈추기 신호
- `notice` · `say`: 작업 진행 줄에 잠깐 띄울 글. `jobs.start` 가 `Job.retry` 에 쓰게 둔다
- `jobs.start` 가 스레드마다 둔다
- LLM 호출 전과 저장 전에 `check()` 로 확인해 멈춘 작업이 결과를 저장하지 못하게 한다
- 멈춘 뒤 온 응답을 남기는 곳은 `ignored()` 안에서 저장한다(스토리보드 `_keep_late_board`)

### `canon/cli.py`

- 명령줄 (`python -m canon ...`)
- 전체 명령 목록은 `python -m canon --help`
- 해석기는 `build_parser` 가 만들고, 명령은 갈래 함수(`_plan_commands` · `_write_commands` · `_tool_commands` · `_app_commands` · `_data_commands` · `_lab_commands`)가 더한다. 새 명령은 맞는 갈래 함수에 넣는다
- 단편 흐름: `new` → `style` → `arc` → `plot` → (사용자 수정) → `confirm` → (스토리보드 → 큐 시트, 웹 집필 화면 · 자동 집필) → `write` → `check` → `update` 반복
- `run` 이 쓰기 · 검수 · 반영을 자동으로 되풀이한다
- `update -y` 의 관계 미리 보기는 반영처럼 `features.hold` 로 뺀 제안을 빼고 계산한다(`_print_relation_preview`)
- 장편(`new --serial`)은 `arc` 대신 `series` 를 한 번 부른다
- 장편은 아크마다 `nextarc` → `plot` → `confirm` → `run` → `recap` 을 되풀이한다
- 명령별 쓰임
  - `abilities`: 스킬 · 특성 도감(설명 · 효과 · 대가, 가진 인물과 얻은 화) 보기
  - `arcs`: 장편 진행 보기
  - `backups`: 백업 목록 보기 · `--restore` 로 그 판으로 되돌리기(지금 판은 먼저 백업으로 남김)
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
  - `rewrite --polish`: 대사 · 사건은 그대로 두고 서술 문장만 다듬은 새 판(revise 단계 모델)
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
- 넣기 · 지우기(`set_episode`, 본문이 있으면 `skipped` 를 그대로 둠)
- 새로 만들지(`remake`: 없거나 낡은 AI · 뼈대 시트, 웹 쓰기 작업 · 자동 집필 `_cues`)
- 방금 쓴 본문에 시트를 넣었는지(`mark_used` → `CueSheet.skipped`, 없이 쓴 화는 `ep_view` 가 세지 않고 다시 생성 `prompts.rewrite_prompt` · `pipeline.memo_texts` 도 뺌)
- 화면 값(`ep_view`: 낡음 · 핵심 대사가 들어간 수)
- 쓴 화의 큐 실현도 `realized`(목표 글자 수 비율로 자른 대략 위치 `split_by_target`, 편성 `voice_ok` · 템포 `tempo_ok`: fast 는 화 평균보다 짧은 문장, slow 는 긴 문장)
- 쓴 화의 템포 곡선(`ep_view` 의 `curve`, `metrics.tempo_curve`)
- 큐 시트 집필 실험(사이드바 '본편과 분리', 주소 `cue/<화>`, 실험 사본은 화의 큐 시트를 지움 `before`): 한 화를 악보처럼 큐로 나눈 큐 시트(`CueSheet`: 조성 · 끝 종지, 큐 `Cue`: 기능 T · S · D · 긴장도 · 템포 · 편성 · 일 · 핵심 대사 `CueLine` · 끝 상태 · 글자 수)
- AI 없는 뼈대(`from_board`)
- 정리(`clean`) · 지문(`basis`) · 넣기(`set_sheet`)
- 시험할 화(`candidates`, 반영 끝난 화는 사본을 되돌림 `before`)
- 조건(`CONDITIONS`: oneshot · score · cues)
- LLM 없는 채점(`score`: 핵심 대사 `line_hits` · 되풀이 `repeats` · 이음매 `seams` · 여운 닫기 `closing` · 정지 장면 끝 `still` · 줄표로 자른 끝 `cut` · 큐별 `cue_rows` · `tempo_order`)
- 비용 추정(`estimate`)
- 실행(`run`, 실험 기록 · 블라인드 비교본 kind cue)
- AI 호출은 `pipeline.make_cue_sheet` · `write_scored` · `play_cues`
- 프롬프트 `prompts.cue_sheet_prompt`(대사 큐 몫은 작품 문체 기준에서 `cue_dialogue_share`) · `cue_sheet_block` · `cue_score_prompt` · `cue_head` · `cue_step` · `cue_play_prompt`(k번째 요청이 앞 요청과 응답을 통째로 품음)
- 작품에 저장하지 않고 `cuelab/<화>.json`(`store.load_cuelab` · `save_cuelab`)
- 화면은 `static/cue.js`
  - 실험 화면과 집필 화면의 큐 시트 카드 `cueCard`
  - 역설계 실험도 편집기를 함께 씀(열쇠 `rev:<화>`) · 쓴 화의 접은 카드 `cuePanel` · 켜기 `cueToggle`
  - 편집기 `cueEditor` 와 막대 `cueScore` 는 둘이 함께 씀
  - 고치는 시트는 열쇠마다 `cueBind`(집필 · 실험 열쇠는 작품 이름을 붙인 `cueKeyOf`, '없이 쓰기' `S.cueSkip` 도)
  - 핵심 대사 칸은 인물 이름(`cueName` · `cueId`)
  - 순수 함수 `cueLinesParse` · `cueLinesText` · `cueBars` · `cueCurveOk` · 말투가 빈 핵심 대사 인물 `cueVoiceGaps`
  - `tests/test_cue.py` · `test_cue_write.py`
- 웹은 작업 `cues`
- 쓰기 작업의 `cues`(none)
- `…/episodes/{n}/cue-sheet`
- `…/cue-setting`
- `…/recent-echoes`(`Settings.recent_echoes`, 블록 `prompts.echo_block`)
- `…/write-material`

### `canon/echoes.py`

- 최근 화에서 되풀이한 구절(`recent`): 본문이 있는 직전 `WINDOW`(5)화에서 `MIN_EPISODES`(3)개 화 이상에 그대로 나온 서술 구절과 그 화 번호
- 쓰기 요청은 앞 화 본문 전체를 넣지 않아, 모델이 지난 화 비유를 보지 못하고 다시 만든다. `metrics.measure` 의 반복 구는 한 화 안만 센다
- 3어절(`SEED`)에서 시작해 앞뒤로 늘린다(`_grow`, `MAX_WORDS` 까지, 나온 곳의 `GROW_SHARE` 이상에서 같은 어절일 때만)
- 대사(따옴표 안)는 세지 않는다
- 인물 이름(성을 뗀 이름 포함) · 부르는 말 · 이야기 요소 이름이 든 구절은 뺀다(`_names`)
- 확정 사실 · 세계관 · 인물 설정 · 상태 · 이야기 요소에 조사만 다르게 적힌 3어절 묶음이 든 구절은 뺀다(`_in_canon`)
- 짧은 구절(`MIN_CHARS`)은 빼고, 많이 나온 화부터 `LIMIT`(10)개
- 블록은 `prompts.echo_block`, 켜기는 `Settings.recent_echoes`
- LLM 호출 없음
- `tests/test_echoes.py`

### `canon/features.py`

- 상태 변경안 수명 주기에 기능이 끼어드는 자리
- 정리(`CLEAN`) · 반영(`APPLY_FIRST` 새 인물 직후, `APPLY_LAST` 기록 전) · 되돌리기(`REVERT_FIRST` 스냅샷으로 덮기 전, `REVERT_LAST` 뒤) 목록
- `pipeline.clean_delta` · `apply_delta` · `revert` 가 목록을 차례로 부른다
- 정리 훅은 한 인물에 대한 경고를 (글, 인물 id) 로 돌려준다(`Warn`)
- `clean` 이 그 id 를 `StateDelta.warn_to` 의 같은 차례에 넣는다
- 글만 돌려준 경고, 훅이 `d.warnings` 에 바로 붙인 경고, AI 경고는 대상이 "" 다
- `align_warn_to` 가 `warn_to` 길이를 `warnings` 에 맞춘다
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
- 고침안 한꺼번에: 받을 지적 `pipeline.fix_targets`(넣을 수 있는 안 `fix_usable` 이 없는 열린 지적, `check.js` `fbNeed` 와 같은 셈), 웹 작업 `fixes`(`FIX_WORKERS` 개씩 동시에, 받는 대로 `store_fixes`), 고른 안 넣기 `apply_fixes`(웹 `POST …/fixes/apply`, 못 넣은 것은 까닭과 함께)
- 프롬프트 `prompts.fix_prompt` · `recheck_prompt`(앞부분은 검수와 같은 `check_material`)
- 결정은 검수 프롬프트에 넣지 않는다
- LLM 호출 없음

### `canon/jobs.py`

- 웹의 오래 걸리는 AI 작업을 스레드로 돌리는 메모리 작업 목록
- `Job.retry`: AI 호출이 기다리거나 다시 부르는 중인 사정(`cancel.say` → `Job.say`). 스레드마다 `retries` 에 두고 남은 하나를 보인다. `public()` 에 싣는다
- 중복 실행 막기
- 진행률
- 작업이 맡은 화를 저장 덮어쓰기에서 지키기(`owned_episodes`)
- 멈추기(`stop`)
- 실패한 작업의 호출 경로를 서버 로그(`canon` 로거)에 남긴다. 화면에는 오류 문구만 보인다
- 멈췄지만 AI 응답을 기다리는 같은 작업 찾기(`lingering`)
- 같은 화의 AI 작업(`EP_AI_KINDS`) 가운데 응답을 기다리는 것 찾기(`waiting_on`). 종류가 달라도 같은 화면 호출이 겹친다
- 단계 하나가 마지막으로 끝낸 화(`Job.step_ep`). 화면 `notify.js` 가 바뀔 때마다 알린다

### `canon/metatail.py`

- 본문 앞뒤에 섞인 작업 설명(메타 코멘트) 찾기
- 확실한 머리말 · 꼬리 떼기(`split`): 대사 · 대괄호 글을 뺀 서술에 Canon 작업 낱말(`STRONG`: 스타일 프로필 · 플롯 · 본문을 · 요청하신 · 짚어 둘 …)이 있고 존댓말이 반 넘는 앞뒤 문단, 'n화 본문입니다' 머리말, '작가 메모' 머리와 목록, 한글이 거의 없는 영어 메모. 서술이 원래 존댓말인 작품은 작업 낱말 둘 이상
- 응답 전체가 작업 설명 · 거절 · 되묻기인지(`whole`)
- 흔한 말(`SOFT`: 원고 · 다음 화 · 원하시면 …)만 있는 앞뒤 문단은 떼지 않고 경고(`warnings`). 작가물 · 편지 · 시스템 알림 · 이야기꾼의 맺음말을 지키려는 것(2026-10-31 적대적 검토)
- 앞 · 뒤를 나눠 주는 `parts`(되살릴 자리). `split` 은 그 위의 옛 모양
- `pipeline._write` 가 떼고(서버 기록 warning, `cut` 목록을 주면 `MetaCut` 으로 채움) 다시 쓰며(`whole`), `pipeline.style_drift` 가 경고를 붙인다
- LLM 호출 없음

### `canon/opening.py`

- 초반 1~3화: 지표, 흡입력 판정, 여는 방식 여러 안
- `pipeline.py` 에서 옮긴 구역이다. `pipeline` 맨 끝의 `_attach_split` 이 `EXPORTS` 의 이름을 `pipeline` 에도 둬서 `pipeline.<이름>` 으로 그대로 부른다

### `canon/pipeline.py`

- 장편 전환(`serialize.py`) · 재구성(`reshape.py`) · 초반 1~3화(`opening.py`)는 따로 둔 모듈이다(`SPLIT`). 새 공용 도우미는 이 파일에 두고 그 모듈이 불러 쓴다
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
  - 반영 전 검사 `validate_delta`: 설정에 없는 인물 id(이번 새 인물은 앎) · 같은 인물끼리이거나 설정에 없는 인물의 관계 사건과 관계 바뀜 · 없는 복선 id 회수(이번에 심는 복선은 앎)
  - `apply_delta` 는 검사에 걸린 항목과 설정에 없는 사건 목격자를 빼고(`drop_invalid`) 반영한 뒤 뺀 항목 문구를 돌려준다
  - `drop_invalid` 가 뺀 항목은 `d.dismissed` 의 같은 칸에 남는다(반영 기록에서 보이고 반영 취소로 돌아오면 체크를 푼 채 다시 놓인다)
  - 상태 변경안의 본문 지문 `StateDelta.basis`(`text_basis`)는 `extract_state` · `carried_delta` 가 채운다
  - 반영 `apply_delta` 는 인물 상태의 빈 칸을 그대로 두고, `CharacterState.cleared` 에 적힌 칸(목표 · 위치 · 메모 · 차림 · 감정)은 비운다
  - 설정 칸 하나 AI 후보 `suggest_field` · 단계 `field_stage`
  - 칸 목록 `prompts.FIELD_IDEAS`, 목록 칸 `prompts.IDEA_LISTS`(후보는 한 줄, 있는 항목은 뺌)
  - 인물 칸 키 `prompts.idea_key`
  - 빈칸 제안은 이미 있는 인물도 빈 칸만 `fill_character`
- 스토리보드: `make_storyboard` · `set_storyboard` · 낡음 지문 `board_basis`, `write_episode(use_board=)`, AI 고치기 `revise_storyboard` → `apply_storyboard_revision`(고치기 전 것은 `Episode.storyboard_prev`) · 적용 취소 `undo_storyboard`
- 큐 시트: `make_cue_sheet`, 넣기는 `cue.set_episode`, `write_episode(use_cues=)`
- 문체 분석 `analyze_style` 뒤 `count_markers` 가 표지 · 장치 단서를 거른다: 원문에 없는 것, 한글 2자 미만(`MARKER_MIN_HANGUL`), 인물 이름(2자 이상)이 든 것
- `count_markers` 는 원문 표본에 없는(공백 빼고 견줌) 장치 예시를 비운다
- 검수
  - 장편 넓혀 찾기 `widen_check`: 첫 검수에 없던 옛 단락이 근거로 나온 진술만 다시 묻기
  - `Settings.check_widen`
  - 프롬프트 `prompts.widen_prompt`
  - 동선 따로 보기 `motion_check`: 본 검수와 동시에 이번 화 본문만 넣고 동선만 묻기, 합치기 `merge_motion`(본 검수가 짚은 문장은 뺌)
  - `Settings.check_motion`(기본 켬), 프롬프트 `prompts.motion_prompt` · `SYSTEM_MOTION`
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
- 스토리보드 만들기 `storyboard_prompt`(Canon 이 센 값 `canon_values_block`), 고치기 `storyboard_revise_prompt`(만들기 프롬프트 뒤에 지금 스토리보드와 요청)
- 쓰기에 넣는 `board_block`(직전 화 본문 뒤, 이번 화 플롯 바로 앞, 시간 · 이동 블록을 대신함)
- 직전 화 블록 `prev_block`(스토리보드를 넣는 화와 스토리보드 만들기만 원문 전체, `build_episode_context(full_prev=)`)
- 쇠맛을 줄이는 쓰기 규칙: 블록 차례 한 줄 `priority_line`
- 이번 화 플롯은 쓰기 · 검수(`check_material`) · 상태 변경안(`state_prompt`) · 부분 수정(`passage_prompt`)이 모두 `write_plot` 으로 넣는다(라벨 모양이 아닌 예전 `emotional_shift` 를 뺌). 플롯 화면 · 흡입력 판정은 그대로
- 상태 변경안 요구사항은 빈 칸이 '그대로 둠'이라 지울 칸 이름을 `cleared` 에 넣게 한다(`state_prompt`)
- 장편 관계 줄 `serial_relations` · 인물 상태 `fit_states`(예산 `context.BUDGET` 의 `relations` · `states`)
- 예산으로 뺀 비밀 · 복선 수는 장편 쓰기(관계 머리글) · 상태 변경안 · 검수 비밀 칸 · 다음 아크 기획(관계 머리글)에 `cut_note` 로 적는다
- 상태 변경안의 뺀 수 안내에는 '목록에 없는 비밀 · 복선의 id 는 쓰지 않습니다'를 붙인다
- 플레이는 `state_prompt(cuts=)` 로 `play_view` 의 뺀 수를 넘겨 머리글이 원래 작품 기준 수를 적는다
- 예시 문단이 있는 작품의 스타일 프로필 `style_rules_view`(칸마다 `STYLE_FIELD_LIMIT`, 예시 문단이 앞)
- 스토리보드 깨지 않을 것을 검수에 `protect_block` · `protect_check_rule`
- 지시 수 · 크기 상한 시험 `tests/test_write_budget.py`
- 장편 본문 쓰기 요청(`build_episode_context(write=True)`)의 뒤쪽, 가끔 쓰는 장치 뒤에 '최근 화에서 되풀이한 구절' 블록 `echo_block`(`echoes.recent`, `Settings.recent_echoes`, 단편 · 스토리보드 만들기에는 넣지 않음)
- 화에 큐 시트가 있으면 `episode_prompt` 맨 끝에 `cue_write_block`(실험의 조건 score 와 같은 글, `use_cues=False` 면 뺌)
- `episode_prompt` 끝(큐 시트 블록 앞)의 문장 끝 섞기 줄 `ending_line`('~다.' 몫과 현재형 몫은 문체 기준에서 `ENDING_SHARE` · `PRESENT_SHARE_MAX` 안으로, 서술 말투가 있는 화는 뺌)
- 화별 플롯 초안(`plot_prompt` · `serial_plot_prompt`)은 범위 안 · 범위 뒤 3화(`PLAN_AHEAD`)의 이미 정해진 화를 `fixed_plots` · `fixed_block` 으로 넣고 요구사항에 `fixed_rule` 을 붙인다(장편은 `context.BUDGET["plan_fixed"]`, 한 화 초안은 `ahead=False`)
- 장편 화별 플롯 초안은 `[관계]` 뒤에 지금 관계 단계 라벨(`plan_stage_block`, 예산 `context.BUDGET["plan_stages"]`), 장편 `plot_rules` 에 '단계는 한 화에 한 칸' 한 줄
- 검수 요구사항의 관계 단계 한 줄(`stage_check_rule`, 관계 수치가 있을 때만)
- 관계 설정 `rels(plan=)`: 가 닿을 곳(`Relationship.destination`)은 기획 프롬프트에만, 말로 넣는 기획은 `destination_block`
- 다음 아크 기획(`next_arc_prompt`)은 관련 확정 사실(`plan_facts`) · 작품 속 시간(`time_plan`, 끝 줄 `ARC_TIME_RULE`) · 주역 밖 기획 인물 상태(`plan_side_states`)를 예산(`context.BUDGET` 의 `plan_facts` · `plan_states`) 안에서 넣는다

### `canon/reshape.py`

- 단편을 씨앗으로 장편 앞부분을 다시 짜는 재구성(웹 `rebuild` 작업)
- `pipeline.py` 에서 옮긴 구역이다. `pipeline` 맨 끝의 `_attach_split` 이 `EXPORTS` 의 이름을 `pipeline` 에도 둬서 `pipeline.<이름>` 으로 그대로 부른다

### `canon/schema.py`

- pydantic 데이터 스키마
- 모든 상태는 `Project` 하나(`project.json`)에 저장
- 인물 신체 프로필(`Character.body`)은 작가 메모라 AI 응답 형식(`SkipJsonSchema`)과 프롬프트(`llm.dump` 의 context `prompt`)에서 빠진다
- 이 칸을 다루는 AI 호출은 신체 프로필 제안(`pipeline.suggest_body`)뿐이다
- 미성년(`cast.is_minor_age`)이면 쓰리사이즈를 제안하지 않는다
- 인물 프롬프트 넣기(`Character.context`: auto 비중대로 · always 늘 · off 이름만)도 작가 전용이라 같은 방식으로 빠진다
- 인물 상태의 지울 칸(`CharacterState.cleared`)은 변경안에만 쓴다. 비었으면 직렬화에서 빼서 저장한 상태 · 프롬프트에 들어가지 않는다
- 지울 칸에 값이 함께 오면 검증(`_blank_cleared`)이 그 칸을 비워 차림 · 이동 거리 경고가 새 값으로 보지 않는다
- 인물 프롬프트 넣기를 고르는 규칙은 `context.core_ids` · `off_ids` · `without_off`(모두 auto 면 예전 규칙과 같다)
- 상태 변경안의 본문 지문(`StateDelta.basis`)도 프로그램이 채워 AI 응답 형식에서 빠진다(`SkipJsonSchema`). 비면 모름
- 상태 승인에서 반영하지 않은 항목(`StateDelta.dismissed`, `DismissedItems`)은 AI 응답 형식에서 빠지고 반영 기록(`Project.history`)에만 남는다
- 반영 취소는 그 화 기록과 함께 빼 둔 항목도 지운다
- 지운 기록은 `_revert_kept` 가 pending.json 에 남기고, 상태 승인 화면이 빼 둔 항목을 체크를 푼 채 다시 놓는다
- 화별 쓴 사건 체크(`Episode.events_done`, 사건 글 목록)는 집필 화면 표시용이라 `EpisodePlot` 밖에 두어 프롬프트에 들어가지 않는다
- 지금 본문을 쓴 모델(`Episode.written_by`, 판마다 `TextVersion.model`)도 프롬프트 밖이다. 값은 `usage.model_id` 의 '<백엔드>:<모델>' 이나 'import', 모르면 빈 칸
- 쓴 모델은 집필 화면 머리 · 이전 판 · 새 판 카드 · 작품 홈 화 칸 툴팁에 보인다(`app.js` `writerLabel`)
- 쓰기가 본문 앞뒤에서 뗀 작업 설명(`Episode.meta_cut`, 판마다 `TextVersion.meta_cut`, `MetaCut`: 글 · 앞 head | 뒤 tail)도 프롬프트 밖이다. 집필 화면에서 되살리기 `pipeline.restore_cut`(수정 기록에 남음) · 지우기 `drop_cut`
- 뗀 문단은 `write_episode(cut=)` · `rewrite_episode(cut)` 에 빈 목록을 주고 받아 `replace_text(meta_cut=)` · `set_candidate(meta_cut=)` 로 저장한다(웹 쓰기 작업 · 동기 쓰기 · 다시 생성 작업, 명령줄 `write` · `run` · `rewrite`, 자동 집필). 실험 · 비교 쓰기는 받지 않는다
- 서술 다듬기 `polish_episode`(다시 생성의 방식 `polish`, 프롬프트 `prompts.polish_prompt` · `POLISH_RULES`, 문장 끝 몫은 쓰기와 같은 `ending_rule`)
- 다듬은 글은 대사 · 효과음 줄(`fixed_lines`)이 같고 글자 수가 `POLISH_SPAN` 안이어야 쓴다(`polish_problem`, `POLISH_TRIES` 번까지 다시 부름)
- 말줄임으로 끊는 서술 · 서술 물음(`metrics.narration_tics`)이 종류마다 `POLISH_TIC_RETRY` 를 넘고 늘면 다시 부르고(`polish_tics`), 끝내 넘으면 덜 늘린 판을 낸다
- 웹 쓰기 작업과 명령줄은 `polish` 일 때 revise 단계 모델을 부른다
- AI 가 본문 전체를 쓰는 호출자가 `pipeline.writer_of(llm)` 을 `replace_text(written_by=)` · `set_candidate(model=)` · `research.save_compare(models=)` 로 넘긴다. 작가 수정은 바꾸지 않는다(수정 기록 `edits`)
- 인물 지금 차림(`CharacterState.attire`, 옷 · 상처 · 지닌 물건)은 지금 값만 덮어쓰고 지난 값은 스냅샷
- 차림 규칙은 `prompts.ATTIRE_STATE_RULE` · `attire_write_rule` · `attire_check_rule`. 옷 · 가방 · 신발은 종류(백팩 · 숄더백 · 핸드백 …)와 가방의 메는 자리까지 적고, 쓰기는 그 종류 · 메는 방식을 지키고, 검수는 같은 물건의 종류 · 메는 방식 · 색이 설명 없이 바뀐 곳을 본다. 종류를 모르는 조각 경고는 `attire.py`
- 인물 감정(`CharacterState.emotional_state`)은 맞서는 감정이면 두 층 라벨('겉: … / 속: …', '머리: … / 몸: …'). 상태 규칙 `prompts.LAYER_STATE_RULE`, 찾기 `LAYER` · `layered`, 검수 규칙 `layer_check_rule`(두 층 라벨이 있을 때만). 쓰기 규칙은 없다
- 작품이 쓸 단계 프리셋(`Settings.model_preset`, 비우면 전체 설정)은 `settings.project_preset` 이 찾고 `stage_provider` · `stage_model` 이 지금 작업의 작품(`usage.scope`)에서 저절로 쓴다
- 화별 스토리보드(`Episode.storyboard`, `Storyboard`: 장면 · 시간 · 상태창 바뀐 양 · 이동 · 끝 차림 · 넘겨받을 것 · 깨지 않을 것 · 경고)는 상태 승인 대상이 아니다
- 스토리보드 켜기는 `Settings.storyboard`(비우면 장편 켬 · 단편 끔)
- 쓰기 재료는 `Settings.write_material`(fixed 면 고정점만: `board.fixed_only`, 장면 목록 · 큐 시트를 쓰기 요청에서 뺌, `cue.on` 끔)
- 화별 큐 시트(`Episode.cue_sheet`, `CueSheet`)도 상태 승인 대상이 아니다
- 큐 시트 켜기는 `Settings.cue_sheet`(비우면 장편 켬 · 단편 끔)
- 되풀이한 구절 블록 켜기는 `Settings.recent_echoes`(기본 켬, 장편에만 넣음)

### `canon/serialize.py`

- 단편을 장편 연재로 바꾸는 이어 쓰기 전환(CLI `convert`, 웹 `convert` 작업)
- `pipeline.py` 에서 옮긴 구역이다. `pipeline` 맨 끝의 `_attach_split` 이 `EXPORTS` 의 이름을 `pipeline` 에도 둬서 `pipeline.<이름>` 으로 그대로 부른다

### `canon/settings.py`

- 사용자 설정(LLM 프로바이더, 모델, API 키, 로컬 서버, 단계별 백엔드)
- 웹 설정 화면에서 저장하면 `~/.canon/config.json` 에 들어간다(`CANON_CONFIG` 로 경로 변경)
- 환경 변수가 있으면 파일보다 우선한다
- 단계 이름 목록은 `STAGES`
- 단계별 환경 변수 이름은 `stage_env`
- 기본 모델은 `DEFAULT_MODEL`
- 작품별 단계 프리셋은 `project_preset` · `stage_provider` · `stage_model`
- 단계별 추론 강도는 `stage_effort`(설정 파일 `stage_efforts`, `CANON_EFFORT_<단계>`)
- 백엔드에 넘길 강도는 `provider_effort`(Claude `EFFORTS`, Gemini `GEMINI_EFFORTS`, Gemini 는 xhigh · max 를 high 로)

### `canon/static/auto.js`

- 자동 집필 화면(`viewAuto`, 서버 `autorun.py`)
- 일시정지 · 중지를 누른 뒤 지금 단계가 끝날 때까지 머리 버튼이 '멈추는 중…' · '중지하는 중…'(`AutoView.want`, aria-busy)이다
- 서버 재시작 칸은 '끊긴 호출 비용은 빠졌어요' 를 글로 보인다(title 에만 두지 않음)
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
- 본문을 `episodes/NN.md` 로 내보내기(바뀐 화만 다시 씀), project.json 은 들여쓰기 없이
- 마지막 화가 100화 이상이면 본문 파일 이름을 세 자리(`NNN.md`)로 쓰고 옛 두 자리 파일은 지운다(`ep_file`)
- 저장 전 직전 판을 `project.prev.json` 으로, 시간마다 첫 저장 직전 판을 `backups/project.<날짜-시>.json` 으로 남긴다(하드 링크라 복사하지 않음)
- 시간별 백업은 최근 `BACKUP_HOURS`(24) 개를 모두 남기고, 그 전은 `BACKUP_DAYS`(14) 일 동안 하루에 그날 마지막 하나만 남긴다(`backup_prune`, 시간별 이름만 지움)
- `backup_list` 는 시간별 · 직전 판 · `before-delete-<화>.json` · `before-serial.json` · 되돌리기 전 판을 새것부터 준다(UTC 시각 · 화 수 · 반영한 마지막 화, 판마다 기억)
- `restore_backup` 은 `backup_list` 의 id 만 받는다. 지금 판을 `backups/before-restore.<시각>.json`(최근 `RESTORE_KEEP` 개)으로 남긴 뒤 저장한다
- `backups/` 안 판의 스냅샷 파일은 작품 폴더의 `snapshots/` 에서 읽는다(`read_disk` 의 `home`)
- 갈래 · 복제 · 플레이 사본은 `backups/` 를 옮기지 않는다(`branches.COPY_SKIP`)
- 작품 캐시: 같은 판이면 검증을 건너뜀. `load_view` 는 캐시 것(고치지 않음, 웹은 `web._view`), `load` 는 깊은 복사본. 저장하면 저장한 내용을 바로 캐시에 둠(`_remember`)
- 파일 판(`tag`, 작품 GET 의 ETag). 웹 요청이 저장한 판은 `saved` 에 남아 응답의 `X-Project-ETag` 가 된다
- 스냅샷은 `snapshots/<화>-<내용 해시>.json` 에 하나씩 두고 project.json 맨 앞 `snapshot_files` 가 차례대로 적는다(`read_disk`). 옛 project.json 안의 스냅샷도 읽는다
- 지난 저장과 같은 스냅샷은 다시 직렬화하지 않는다(`_snap_written`). 어느 판(project.json · prev · backups)도 적지 않은 스냅샷 파일은 지운다
- `backups/` 의 모든 `.json`(되돌리기 전 판 포함)이 적은 스냅샷 파일을 남긴다
- 아무 판도 적지 않아도 `SNAP_GRACE`(60초) 안에 쓴 스냅샷 파일은 지우지 않는다
- `save` 는 판 기록 읽기부터 옛 스냅샷 지우기까지 작품 폴더의 `.lock` 에 `fcntl.flock` 을 잡는다(`_disk_lock`). 명령줄과 웹 서버가 함께 저장해도 서로의 새 스냅샷 파일을 지우지 않는다
- 화면 저장 기록(`writer`, `edit_rev` · `saved_by`, 파일 끝만 읽음)
- 파일 끝에서 두 칸을 찾지 못하면 파일 전체를 읽는다. 두 칸은 `Project` 의 마지막 필드여야 한다(`tests/test_store_backup.py`)
- 검토를 기다리는 AI 결과와 실패한 작업(`pending.json`, `load_pending` / `edit_pending`)
- 상태 변경안 결과(`state:<화>`)는 작가가 고르던 체크와 고친 변경안을 `draft` 칸에 함께 둔다
- 결과를 지우거나 새 결과로 바꾸면 초안도 사라진다

### `canon/updater.py`

- 코드 자동 업데이트
- `origin/main` fast-forward
- 의존성 설치(`requirements.lock` 이 있으면 그것대로)
- 다시 시작하기 전에 새 프로세스에서 `canon.web` 을 불러 보고, 불러지지 않으면 이전 커밋으로 돌린다(`_smoke`)
- 프로세스 재시작
- `serve` 가 시작 때와 주기적으로 부른다
- `POST /api/update/check`(머지 때 GitHub Actions `notify-server.yml`)는 `wake` 로 바로 부르게 한다

### `canon/web.py`

- 웹 UI 서버(`python -m canon serve`)
- 맨 바깥 미들웨어 `_guard_host` 는 Host 가 IP 주소 · localhost · `*.ts.net` · 이 컴퓨터 이름 · `CANON_ALLOWED_HOSTS` 의 이름이 아니면 403 으로 막는다(DNS 리바인딩)
- `_guard_host` 는 POST · PUT · PATCH · DELETE 에 Origin 이 있으면 그 이름이 Host 나 X-Forwarded-Host 와 같아야 받는다(CSRF). Origin 이 없는 요청(명령줄 · curl)은 받는다- 작품 문체 분석은 작업 `style`(`_job_style`, `JobIn.text` 200자 이상): 프로필과 원문 전체 기준 지표를 돌려주고 결과는 pending 에 남는다(`PENDING_KINDS`). 옛 `POST …/style` 은 그대로 둔다
- 결과 지우기 `DELETE …/pending/{key}?id=` 는 id 가 같을 때만 지운다. 화면이 옛 결과를 반영하는 사이 같은 키에 새 결과가 들어왔으면 남긴다(`syncPending` 이 id 를 보낸다)
- 작품 카드 `setup_ready`: 설정 도우미 필수 칸이 다 찼는지(`_setup_ready`, setup.js `setupReqs` 와 같은 규칙)
- `/api/config/health` 는 Claude 단계가 있으면 `claude_api`(Anthropic 키 유무)와 `claude` · `claude_message`(구독 설치 · 로그인, `claude.status` 를 60초 기억)를 싣는다. 설정 저장은 기억을 지우고, `/api/claude/status` 는 새로 읽은 값으로 바꾸고, error 는 기억하지 않는다
- 키 없음(`MissingKey`) 답의 문구는 낸 백엔드의 것(Gemini · Vertex · Anthropic)을 쓴다
- 대화 세션 칸만 바꾸는 요청(세션 만들기 · 이름 · 대상 · 권한 모드 · 보관, `_session_edit`)은 화면 저장으로 치지 않는다(`store.writer` 를 비움). 저장하지 않은 변경이 있는 탭의 다음 저장이 다른 탭과의 충돌(409)을 그대로 받는다
- 기능별 라우트 일곱 묶음은 `canon/routes/` 에 있다(`ROUTES`: 문단 연습장 · 레퍼런스 · 지도 · 역설계 · 쇠맛 · 플레이 · 연구). 맨 끝의 `_attach_routes` 가 붙인다
- 붙인 라우트는 `app.routes` 에 감싼 모양으로만 들어가서, 응답 모양을 바꾸는 코드는 `_ROUTERS` 의 라우트도 함께 본다(`_SNAPSHOT_LIGHT`)
- `serve` 는 로깅 설정이 없으면 INFO 수준, 시각 · 수준 · 로거 이름을 붙인 형식으로 정한다. 업데이트 · 자동 집필 이어 가기 안내도 이 로그로 낸다
- 작품 GET 과 작품을 돌려주는 응답은 스냅샷을 화 번호만 보낸다(`_SNAPSHOT_LIGHT`). 작품 저장(PUT)은 디스크 스냅샷을 지킨다
- `GET /` 는 index.html 의 `/static/*.js` 태그를 내용 해시가 붙은 묶음 하나(`/bundle/<해시>.js`, 오래 캐시)로 바꿔 보낸다(`_bundle`). 파일을 고치면 해시가 바뀐다
- 화면의 작품 저장은 `PATCH /api/projects/{name}`(`ProjectPatch`): 바뀐 최상위 칸만 받고 보내지 않은 칸은 디스크 것을 쓴다. 그 뒤는 `put_project` 와 같다
- PATCH 의 `episodes` 에서 `{"$same": 화}` 는 디스크의 그 화다. 디스크에 없는 화면 409
- 작품 저장(PUT · PATCH)은 디스크 읽기 · `edit_rev` 충돌 검사 · 디스크 칸 지키기 · 저장을 한 번의 `jobs.project_lock` 안에서 한다(`_put_locked` · `_patch_locked`)
- 잠금은 재진입하지 않는다. 잠금을 잡은 채 저장하는 코드는 `_save` 대신 `_save_locked` 를 부른다
- 작품 저장(PUT · PATCH)은 디스크에도 있는 화의 `JOB_EP_FIELDS` 칸(검수 결과 · 흡입력 판정 · 다시 맞추기 표시 · 고칠 곳 · 장면 연출)을 디스크 값으로 둔다(`_keep_job_fields`)
- 작업이나 전용 엔드포인트만 쓰는 화의 칸을 새로 만들면 `JOB_EP_FIELDS` 에 더한다. 그래야 작업 전에 읽은 화면의 저장이 작업 결과를 덮지 않는다
- 인물 · 관계도와 지도 응답은 작품 판으로 JSON 을 기억하고 ETag 를 붙인다(`_json_view`)
- CLI 와 같은 store · pipeline · prompts 를 쓰고 화면은 `canon/static/` 의 정적 파일이다
- AI 가 만든 제안(설정, 문체, 구조, 상태 변경안)은 바로 저장하지 않고 돌려준다
- 사용자가 화면에서 고르거나 고친 뒤 저장 요청을 보낼 때 반영한다
- 상태 반영 `POST …/apply` 는 `pipeline.validate_delta` 에 걸린 항목이 있으면 400 으로 막고 항목을 줄마다 적는다
- 상태 반영은 변경안 지문(`basis`)이 지금 본문과 다르면 409(`code` `stale_delta`)로 막는다. `?force=1` 이면 반영한다
- 빈 지문(옛 결과 · 손으로 만든 변경안)은 맞춰 보지 않는다. 채팅 앱 변경안 가져오기 `state/parse` 도 지문을 채운다
- 오래 걸리는 AI 작업은 `jobs.start` 로 돌린다
- `start_job` 은 작업 종류마다 `JOB_MAKERS` 의 준비 함수(`_job_<종류>`)를 부른다. 함수는 (이름표, 전체 걸음, 맡은 화, 할 일)을 돌려준다. 새 작업은 함수를 더하고 `JOB_MAKERS` 에 넣는다
- `start_job` 은 같은 화에서 멈춘 작업이 AI 응답을 기다리면 `EP_AI_KINDS` 작업을 409 로 막는다(`_waiting_409`, 역설계 실험 `rev_job` 과 같은 문구)
- 멈춘 스토리보드 작업의 늦은 응답은 그 화에 스토리보드 · 본문이 없고 플롯이 확정돼 있으면 남긴다(`_keep_late_board`, 결과 `{kept}`)
- `_keep_pending` 은 멈춘 작업의 결과를 pending.json 에 남기지 않고 지난 실패도 지우지 않는다
- 반영 취소(`POST …/revert/{n}`)는 n+1화부터의 반영 기록을 pending.json 의 상태 변경안(`state:<화>`)으로 남긴다(`_revert_kept`)
- 남긴 변경안의 base 는 반영 때 본문이다(반영 뒤 고쳤으면 `final_text`)
- 반영 뒤 고친 화에서 이미 뽑아 둔 상태 변경안은 반영 기록으로 덮지 않는다
- `PUT /api/projects/{name}/pending/{key}/draft`(`save_state_draft`)는 상태 변경안 결과에 초안을 붙인다
- 초안 저장은 pending.json 만 고쳐 작품 저장으로 치지 않는다
- 초안 저장 본문의 `picks` 가 null 이면 남긴 체크를 그대로 둔다(화면의 체크가 다른 화의 것일 때)
- 초안 저장은 결과가 없거나 상태 변경안이 아니거나 보낸 `id` 가 결과의 작업 id 와 다르면 아무것도 바꾸지 않는다(반영 · 버림 · 다시 만들기 뒤 늦게 온 저장)
- 읽기 전용 GET 은 `_view`(`store.load_view`)로 작품을 읽는다
- `GET …/backups` · `POST …/backups/restore` 는 백업 목록과 되돌리기(`store.restore_backup`). 자동 집필 · 돌고 있는 AI 작업 · 검토를 기다리는 결과가 있으면 막고, 반영한 화가 줄면 `autorun.after_revert` 를 부른다
- 작품 전체 저장은 `put_project`

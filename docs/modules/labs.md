# 모듈 지도: 실험 · 연구 · 지표

이 파일의 줄은 [AGENTS.md](../../AGENTS.md) 의 '문서 줄 규칙'을 따른다.

### `canon/blocktrial.py`

- 쓰기 블록 시험(명령줄 `blocktrial`)
- 블록 하나를 뺀 사본 조건 `CONDITIONS`(base · no_board · no_cues · no_profile · no_relations · no_address · no_knows, 사본 바꾸기와 `write_episode` 인자)
- 시험할 화(`candidates`, 뒤쪽부터 `default_pick`)
- 사본은 `stattrial.before`
- LLM 없는 채점(`score`: 쇠맛 · 상투 · 쉼표 · 문장 길이 · 반복 구 · 문체 거리 · 설계 메모 옮김 `pipeline.memo_copied` · 예시 옮김)
- 비용 추정(`estimate`)
- 실행(`run`: 실험 기록 · 블라인드 비교본 kind blocks)
- 작품은 저장하지 않는다
- 웹 화면은 아직 없음

### `canon/labstats.py`

- 쇠맛 실험실 통계(표준 라이브러리만, 시드 고정)
- 함수: `auroc` · `auroc_boot` · `cluster_boot`(묶음 부트스트랩 2,000번) · `wilson` · `kappa` · `kappa_boot` · `sign_test` · `spearman` · `holm` · `roc_points` · `pair_agree` · `verdict`(동시 구간 99.64%, 하한 > 0.5 · 값 0.7)

### `canon/metrics.py`

- 문체 지표(문장 길이, 대사 비율, 과거형 비율, 어휘 다양도, 반복 구, 상투 표현, 쇠맛 패턴과 쉼표·대명사 지표, 문체 거리, 문체 표지 빈도, 예시 문단 베끼기)와 기준 대비 경고
- 1~3화 초반 지표(`measure_opening`)
- 지표 판 `METRICS_VERSION`(상수나 셈 로직을 바꿔 같은 글의 값이 달라지면 올림, `tests/test_metrics_version.py` 가 상수 해시와 fixture `tests/fixtures/soelab/` 결과 스냅샷으로 막음)
- 쇠맛 패턴 · 상투 표현 자리 `pattern_spans`(`Span`, `pattern_counts` 는 이 위에서 셈)
- 문장 경계 자리 `sentence_spans`(`sentences` 와 같은 경계)
- 화당 상한 없는 1,000자당 횟수 `rates_per_1k`
- LLM 호출 없음
- 문체 거리 기준표는 `style_background.py`(`scripts/make_style_background.py` 로 생성)

### `canon/research.py`

- 연구 화면(모델 실험) 로직
- 서버 점검
- 샘플 비교
- 단계 시험
- 컨텍스트 크기
- 검수 시험
  - 모순을 심고 `TRIAL_MODES` 마다 찾는지
  - `check_trial`
  - 장편은 검수 넓히기 `widen`
  - 판단기를 주면 두 걸음 검수 `twostep`도
  - 장면 연출 규칙 검수 `stage` 는 고르면: 사건마다 `pipeline.extract_stage` → `stage.episode_issues`
  - `_stage_run`
  - 갈래별 찾은 수 `by_kind` · 기록 합계 `check_totals`
- 블라인드 비교
- 고르지 않은 비교본 목록 `open_compares`
- 작품 데이터와 분리해 `research/log.jsonl` 에 기록
- 갈래마다 마지막 기록 `latest`(연구 개요가 `history` 30개 밖의 실험도 보인다)

### `canon/revlab.py`

- 역설계 실험(작품 밖 화면, 주소 `#/revlab/<번호>/<화>`, 작품을 열지 않고 쓴다)
- 작가가 넣은 소설을 거꾸로 화별 플롯 · 스토리보드 · 큐 시트 · 이야기 줄기로 푼다
- 그 큐 시트로 같은 화를 다시 써서(되돌려 쓰기) 원문과 견준다
- 작품 밖 `<CANON_HOME>/.revlab/<번호>.json`(`RevLab`, `load` · `save` · `with_lock` · `create` · `replace_text`, 화 이어 붙이기 `append_text`: 마지막 화 + 1 부터, 앞 화 결과는 그대로)
- 화 하나 고치기(`edit_episode`, 웹 `PUT /api/revlab/{번호}/episodes/{n}`): 글이 바뀌면 그 화의 결과 · 되돌려 쓴 판만 지운다. 제목 줄만 바뀌면 결과는 그대로
- 화 빼기(`drop_episode`, 웹 `DELETE /api/revlab/{번호}/episodes/{n}`): 뒤 화 번호와 줄기의 `branch_ep` · `join_ep` 를 하나씩 당긴다. 마지막 남은 화는 빼지 않는다
- 화 고치기 · 빼기는 그 실험의 작업이 도는 동안 409(`web._rev_idle`, 작업이 화 번호로 결과를 넣는다)
- 화 나누기(`split`: 'n화' 제목 줄 → `===` 줄 → 빈 줄 셋 넘게 → 한 화, `check_text`, 화면 `revSplit` 과 같은 규칙)
- 큐 경계(`locate`: AI 가 원문 글자 그대로 인용한 시작 문장 `RevCue.start` 를 차례로 찾음, 글자 수는 `measured`)
- 원문에 없는 핵심 대사 빼기(`keep_lines`, `cue._flat`)
- 응답 넣기(`apply_episode` · 줄기 `apply_lines` · 인물 `merge_cast`, 화마다 배경 · 사실 · 관계 · 호칭)
- 첫 화 번호(`guess_first` · `renumber`)
- 작가 고침(`set_sheet`, 큐 수가 바뀌면 경계를 지움)
- 되돌려 쓰기 사본
  - `world`: 앞 화는 원문을 반영한 화
  - 인물 id 는 이름
  - 그 화까지 읽은 배경 · 사실 · 관계 · 호칭 `context_upto`
  - 문체 프로필은 고를 때만이고 예시 문단은 늘 비움
- 되돌려 쓰기 실행(`run_write`, 판 둘 `take` · `take_style`, `pipeline.write_scored`)
- 블라인드 고르기(`pick`, `blind_of`)
- 지표(`compare`, `cue.score`)
- 문체 역설계(`run_style`, `pipeline.analyze_style`)
- 비용 추정(`estimate`: parse · write · style)
- 역설계 실행(`run_parse`)
- 화면 값(`view`, 고르기 전에는 차례를 뺌)
- AI 호출은 `pipeline.reverse_episode` · `reverse_lines`(plan 단계, 응답 칸은 모두 required, 사건 · 장면 · 큐가 비면 한 번 더 묻고 그래도 비면 저장하지 않음 `rev_empty`)
- 프롬프트 `prompts.rev_rules` · `rev_prompt` · `rev_lines_prompt` · `SYSTEM_REVERSE`
- 가짜 응답 `mock_revlab.py`
- 웹은 `/api/revlab…`
- 작업은 `POST /api/revlab/{번호}/jobs`(kind parse · write · style → 작업 `rev_parse` · `rev_write` · `rev_style`, ep 가 실험 번호, project 자리는 `JOBS`, 사용량 범위에 작품 없음)
- 화면은 `static/revlab.js`
- 시험 `tests/test_revlab.py`(글은 `tests/fixtures/revlab_story.txt`, 직접 지은 글)

### `canon/soelab.py`

- 쇠맛 실험실(작품 밖 `<CANON_HOME>/.soelab/`, 화면은 PR3)
- 쇠맛 지표가 사람 글과 AI 글 · 작가 판정을 가르는지 잰다
- 프로세스 사이 잠금 `_lock`(`fcntl.flock`) · `save_json` · `append_label`(labels.jsonl 덧붙이기)
- 정규화 `normalize` · `chunks`(2,000자 문장 끝)
- 모으기 `collect_revlab` · `collect_episodes`(모델은 `write_models`: usage.jsonl 마지막 성공한 write) · `collect_edits` · `collect_research` · `collect_paste` → `add`(같은 글 한 번 · 원천 상한 `CAP`)
- 대기열 `extend_queue`(판정한 자리 · 다시 읽기 예정은 고정, 1차 `FIRST` 묶음마다 한 조각)
- 판정 `judge` · `redo`(7일 뒤) · `hidden_ids`
- 채점 `features`(저장 안 함, 열쇠 `METRICS_VERSION`)
- 보고서 `report`(출처 기준 · revlab 짝 · 작가 판정 · 모델별 참고 · 패턴 · 판정 일관성) · `view` · `export`(원문 · quote · 메모 없음)
- 스키마 `SoeSource` · `SoePiece` · `SoeSpan` · `SoeLabel`
- 명령줄 `soelab collect | report | export`
- LLM 호출 없음

### `canon/static/revlab.js`

- 역설계 실험 화면
  - 작품 밖 `#/revlab[/<번호>[/<화 · cast · style · lines · metrics>]]`
  - `app.js` 라우팅이 `viewRev` 를 그림
  - 불러오기 `revLoad` · `revFetch`
  - 작업 시작 `revStartJob`
  - 작품 사이드바 · ⋯ 메뉴의 링크
  - 작품 밖 사이드바(`outSidebar`)
  - 작품에서 들어왔으면 머리에 그 작품으로 가는 버튼 `revBackBtns`(`S.revFrom`, `routeNow` 가 적음)
- 처음 화면(`revHome`)은 이어 하기 카드(목록 값 `revlab.summary` 의 `steps` · `updated` → `revLabLite` · `revHomeCard`)와 머리 '+ 새 실험 만들기'으로 펴는 새 실험 칸(`revNewToggle`, 붙여 넣기 · 첫 화 번호 짐작 `revGuessFirst` · 나누기 미리보기 `revPreview`, `revNewCard`)
- 실험 화면은 다른 단계 화면과 같은 공용 목차 틀(`outline.js`)의 왼쪽 목차 + 오른쪽 칸(`revLayout` · `revToc`, 칸은 남은 폭을 다 씀 `wide`, 위쪽 띠가 없어 `--outline-band: 0px`)
- 목차 맨 위 개요
  - 주소에 화가 없을 때
  - `revOverview`: 역설계 전 풀 화 표 `revPickCard` · 받는 것 `revGetCard`
  - 뒤 화별 진행 `revProgressCard` · `revOverviewRow` · 실험 전체 카드 `revLabCards`
- 단계 다섯(`revSteps` · `revStepShare`, 누르면 그 단계 자리 `revStep`) · 화(`revTocEps`, 제목 옆 ＋ 로 화 이어 붙이기 칸 `revAddCard`, 미리보기 `revAppendPreview` 는 `append_text` 와 같은 규칙) · 실험 전체
  - 인물 · 관계 · 배경 `revContextCard`
  - 문체 프로필 `revStyleCard`
  - 이야기 줄기 `revLinesCard`
  - 지표 모아 보기 `revMetricsAll`
- 목차의 화 줄마다 ⋯ 메뉴(`revEpMenu`): 글 고치기 칸 `revEpEditCard` · 지우기(위험한 묶음에 접음)
- 머리 주 버튼은 다음 할 일(`revNext`, `revGoBtn`) · ⋯ 메뉴(글 · 이름 고치기 `revEditCard` · 다시 역설계 `revRedo`(개요의 풀 화 표) · 지우기)
- 오른쪽 맨 위 도는 작업 카드(`revRunCard`: 화별 줄 `revRunRows`, 작업의 `pending` · `done`, 한 화가 끝날 때마다 다시 받기 `revJobStep`)
- 화 탭 셋
  - 원문 · 큐 `revTextTab`: 큐 띠로 나눈 원문 `revText` · `revSegments`
  - 큐 목록 `revCueCard`(고른 큐만 펼침 `revCueGo`)
  - 큐 시트 편집기 `cue.js` `cueEditor`(열쇠 `rev:<화>`, `cueCtx` 의 kind rev)
  - 플롯 · 스토리보드
  - 되돌려 쓰기 `revWriteTab`: 가려 읽기 `revPick` · 지표 견주기 `revMetricRows` · 나란히 읽기 `revRead` · 다시 쓰기
- 비용 추정은 고를 때 바로 묻고 버튼 글에 적는다(`revEst` · `revCost`, AI 없음)
- `revSplit` · `revPreview` · `revAppendPreview` · `revSegments` · `revEpTitle` · `revSteps` · `revNext` · `revTocEps` · `revRunRows` · `revMetricRows` · `revLabLite` · `revHomeCard` · `revOverviewRow` 는 순수 함수(`tests/test_revlab.py`)
- CSS 는 JS 에서 주입

### `canon/stattrial.py`

- 상태창 넣기 시험(연구 화면 '상태창 시험' 쪽, 명령줄 `stattrial`)
- 조건 `CONDITIONS`(none · json · lines, `stat_window.prompt` 만 바꾼 사본 `variant`)
- 시험할 화(`candidates`, 추천 `default_pick`)
- 그 화를 쓰기 직전 사본(`before`, `pipeline.revert`)
- 원래 반영의 바뀐 항목(`changes`)
- LLM 없는 채점(`score`: 바뀌지 않을 값 · 바뀔 값 오류, 없던 항목, 플롯에 없던 상태창)
- 비용 추정(`estimate`, 실제 요청 글자 수와 `usage` 가격표)
- 실행(`run`: 실험 기록 kind statwin, 조건마다 첫 안을 블라인드 비교본 kind statwin 으로)
- 작품은 저장하지 않는다
- 화면은 `static/stattrial.js`
- 화면은 고를 때마다 비용을 추정해(`stEst`, AI 없음) 머리 주 버튼 글에 적는다(`stHeadBtn`)
- 지난 시험은 틀린 비율 막대(`stBars`, 한 계열)와 방식별 표
- 웹 작업 `stattrial`

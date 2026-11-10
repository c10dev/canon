# 모듈 지도: 실험 · 연구 · 지표

이 파일의 줄은 [AGENTS.md](../../AGENTS.md) 의 '문서 줄 규칙'을 따른다.

### `canon/blocktrial.py`

- 쓰기 블록 시험(명령줄 `blocktrial`)
- 블록 하나를 뺀 사본 조건 `CONDITIONS`(base · no_board · no_cues · no_profile · no_relations · no_address · no_knows · fs_json · fs_line, 사본 바꾸기와 `write_episode` 인자와 문맥 고리)
- 문맥 고리(`CONDITIONS` 의 다섯째 칸, `hook`)는 그 조건의 `write_episode` · `episode_prompt` 호출을 감싼다
- 문맥 고리는 `run` · `estimate` · `prompt_size` 가 쓴다
- fs_json 은 고리로 `prompts.FORESHADOW_JSON` 을 참으로 두어 장편 쓰기의 열린 복선을 예전 JSON 꼴로 넣는다
- fs_line 은 지금 방식인 한 줄 꼴이다(spec 10 의 확인 (나))
- fs_json · fs_line 을 함께 고르면 두 조건의 쓰기 요청이 글자까지 같은 화(단편 화)는 그 둘만 건너뛰고 `skipped` 에 적는다(`plan`, `run` · `estimate` 둘 다)
- 이름이 fs_ 로 시작하는 조건(`judged`)은 본문마다 같은 `llm` 으로 복선 판정(`judge`: `prompts.foreshadow_judge_prompt`, 응답 `ForeshadowBreaks`)을 한 번 부른다
- 판정 결과는 본문 기록의 `breaks` 와 kind 별 수 `contradictions`('모순') · `early_payoffs`('미리 회수')다
- 판정 결과의 `summary` 는 본문 하나당 평균이고, `describe` 는 '/화' 로 찍는다
- 시험할 화(`candidates`, 뒤쪽부터 `default_pick`)
- 사본은 `stattrial.before`
- LLM 없는 채점(`score`: 쇠맛 · 상투 · 쉼표 · 문장 길이 · 반복 구 · 문체 거리 · 설계 메모 옮김 `pipeline.memo_copied` · 예시 옮김)
- `score` 의 `speech_copied` 는 인물 말투의 대사 예시를 그대로 쓴 문장 수다(`pipeline.speech_copied`, 명령줄 '말투 예시 옮김')
- 비용 추정(`estimate`)
- 비용 추정의 토큰은 본문 단계 백엔드 · 모델의 `usage.token_rate` 로 센다
- fs_ 조건의 비용 추정은 판정 요청 토큰(`judge_input_tokens` · `judge_output_tokens`)도 세어 금액에 더한다
- 판정 요청의 본문 자리는 화당 분량으로, 응답은 `JUDGE_OUTPUT_TOKENS` 로 어림한다
- 실행(`run`: 실험 기록 · 블라인드 비교본 kind blocks)
- 도중에 실패하거나 멈추면 그때까지 쓴 본문을 기록에 남기고 `stopped` 에 까닭을 적은 뒤 오류를 다시 낸다(`research.stopped_note`)
- 작품은 저장하지 않는다
- 웹 화면은 아직 없음

### `canon/labstats.py`

- 쇠맛 실험실 통계(표준 라이브러리만, 시드 고정)
- 함수: `auroc` · `auroc_boot` · `cluster_boot`(묶음 부트스트랩 2,000번) · `wilson` · `kappa` · `kappa_boot` · `sign_test` · `spearman` · `holm` · `roc_points` · `pair_agree` · `verdict`(동시 구간 99.64%, 하한 > 0.5 · 값 0.7)

### `canon/metrics.py`

- 문체 지표(문장 길이, 대사 비율, 과거형 비율, 어휘 다양도, 반복 구, 상투 표현, 쇠맛 패턴과 쉼표·대명사 지표, 문체 거리, 문체 버릇 빈도, 예시 문단 베끼기)와 기준 대비 경고
- 말투 대사 예시 뽑기 `speech_examples`(큰따옴표 · 작은따옴표 · 낫표, 바로 앞에 '말버릇' · '입버릇' 이 있으면 뺌)
- 말투 대사 예시 옮김 `speech_copied`: 예시 문장마다 그 길이(최대 `COPY_SPAN`)로 `copied_sentences` 를 부른다. 끝 문장부호는 빼고, `SPEECH_COPY_MIN`(6)자 미만 예시는 보지 않는다
- 1~3화 초반 지표(`measure_opening`)
- 지표 판 `METRICS_VERSION`(상수나 셈 로직을 바꿔 같은 글의 값이 달라지면 올림, `tests/test_metrics_version.py` 가 상수 해시와 fixture `tests/fixtures/soelab/` 결과 스냅샷으로 막음)
- 쇠맛 패턴 · 상투 표현 자리 `pattern_spans`(`Span`, `pattern_counts` 는 이 위에서 셈)
- 문장 경계 자리 `sentence_spans`(`sentences` 와 같은 경계)
- 화당 상한 없는 1,000자당 횟수 `rates_per_1k`
- 서술 문장 끝 `_endings`(`da_ending_ratio` · `da_run_ratio`, 따옴표로 여는 줄은 대사로 빼고 덩어리를 끊음, 서술 문장이 `ENDING_MIN` 개 미만이면 재지 않음)
- 문장 끝 경고는 기준값이 비면 사람 웹소설 중앙값 `ENDING_DEFAULTS` 와 견줌
- 효과음 줄 `is_sfx_line` · `sfx_lines`(소리나 몸짓만 적은 한 줄 문단, 낱말 꼴로만 판별, 근거는 reports/소리 표현 실측 2026-11-05.md)
- 효과음 끝 표시 `sfx_mark` · 몫 `sfx_marks`(효과음 줄이 `SFX_MARK_MIN` 줄 미만이면 비움)
- `measure` 의 효과음 지표: `sfx_per_1k` · `sfx_marks` · `sound_word_per_1k`(낱말 '소리', 합성어와 '소리치다 · 소리 지르다'는 뺌)
- '소리' 낱말 밀도는 재기만 하고 경고하지 않음(2026-11-05 실험에서 이 값이 높은 판을 판정이 골랐음)
- 대사 꼴 `_dialogue_shape`: 큰따옴표 · 낫표로 여는 줄을 대사 줄로 셈(작은따옴표 줄은 속생각이 많아 뺌)
- `measure` 의 대사 꼴 지표: `dialogue_tilde_ratio`(물결표가 든 대사 줄의 몫) · `dialogue_line_len`(대사 줄 평균 글자 수)
- 대사 줄이 `DIALOGUE_MIN` 줄 미만이면 대사 꼴을 재지 않음
- 대사 꼴은 `drift` 가 기준값과 견줘 경고함(물결표는 차이 0.15, 길이는 30%). 옛 기준값에는 값이 없어 경고하지 않음
- 대사 꼴을 더한 근거는 reports/지표 사각지대 2026-11-07.md(대사 비율로는 갈리지 않던 작품과 레퍼런스가 이 값으로 갈림)
- 문단 경계 창 `_para_windows`(`tempo_curve` 와 `peak_window` 가 함께 씀)
- 정점 대목 `peak_window`: 절정 낱말(`Settings.heat_words`)이 가장 많이 든 `PEAK_WINDOW` 자 창의 자리 · 절정 낱말 수 · 문장 평균 길이. 낱말이 없거나 `PEAK_MIN_HITS` 개 미만이면 None
- 정점 대목 경고 `peak_drift`: 그 창의 문장 평균이 기준값보다 `PEAK_LIMIT`(30%) 넘게 길면 한 줄. `pipeline.style_drift` 가 붙임
- 정점 대목을 더한 근거는 reports/열 판정 시트 2 2026-11-07(같은 출처끼리 문장 길이가 다른 짝 13개 중 12개에서 짧은 쪽이 더 달아오름, 작품 평균은 그 차이를 가림)
- 효과음 끝 표시 경고 `sfx_mark_drift`(원문이 `SFX_MARK_RARE` 미만으로 쓰는 표시를 이번 화 효과음 줄 `SFX_MARK_NEW` 이상에 쓰면)
- 문체 분석 요청에 넣는 원문 효과음 줄 요약 `sfx_summary`(`prompts.sfx_note`)
- 말줄임 · 물음 셈 `narration_tics` 는 효과음 줄을 서술로 세지 않음
- 템포 곡선 `tempo_curve`(400자 창마다 대사 비율 · 문장 길이, 화면 표시용, 경고 없음)
- LLM 호출 없음
- 문체 거리 기준표는 `style_background.py`(`scripts/make_style_background.py` 로 생성) · 문체 기준 `_style_reference` 는 조각 합에서 빼는 방식이라 조각 수에 비례하고, 같은 글은 `_reference` 가 기억한다(`lru_cache` 32개)

### `canon/promptlab.py`

- 프롬프트 놀이터(작품 밖 `<CANON_HOME>/.promptlab/<id>.json`, `CANON_PROMPTLAB` 으로 경로 변경, 화면은 `static/promptlab.js`, 웹 `/api/promptlab/...`)
- 시스템 · 요청 프롬프트를 직접 써서 고른 백엔드(`PROVIDERS` = `research.PROVIDERS`: gemini · local · claude · claude-api · mock)로 돌리고 결과를 시도로 남긴다. 작품과 상관없다
- 세션 `PromptSession` 은 지금 칸(제목 · 시스템 · 요청 · 온도 · 백엔드 `PromptBackend`)과 시도 `PromptTrial`
- 시도는 그때의 시스템 · 요청 · 온도와 백엔드마다 결과 `PromptRun`(글 · 오류 · 초 · 글자 · 토큰 · 어림 비용), 고름 `star`, 메모 `note`
- 저장 `load` · `save`(`store.write_atomic`) · `sessions` · `create` · `update` · `delete` · `duplicate`(프롬프트 · 백엔드만 복사)
- 백엔드 정리 `clean_backends`: 모르는 백엔드는 막고 같은 것은 한 번만, 주소는 로컬만 남기고 `MAX_BACKENDS` 개까지
- 제목은 비우면 요청 첫 줄로 짓는다(`title_of`). 작가가 적은 제목은 프롬프트를 바꿔도 남는다
- 돌리기 `run` 은 `research.sample` 을 그대로 부른다(동시에 부름, 한 쪽이 실패해도 나머지는 돎). 세션은 바꾸지 않고 `add_trial` 로 붙인다
- 불러온 갈래가 있으면 `run_spec` 대로 돌린다: 응답 스키마(구조화 출력 `llm.json`), 그 단계의 모델 · 추론 강도, 출력 한도
- 출력 한도 `OUT_TOKENS`(갈래 → 모듈 · 이름): 스토리보드 · 큐 시트는 `pipeline.BOARD_OUT_TOKENS` · `CUE_OUT_TOKENS`, 대화 에이전트는 `agent.STEP_OUT_TOKENS`, 나머지는 기본 한도
- 고른 작품에서 불러왔으면 그 작품의 단계 프리셋(`settings.project_preset`)을 쓴다
- 칸을 고쳐도 출처가 있으면 같은 방식으로 돌린다. 불러온 출처가 없는 세션은 예전처럼 글로 받는다
- 시도의 결과마다 받은 스키마 · 추론 강도 · 출력 한도를 남긴다(`PromptRun.schema_name` · `effort` · `out_tokens`)
- 실패한 결과는 마지막으로 받은 원문(`PromptRun.raw`, `research.RAW_MAX` 자까지)과 끝난 이유(`finish`)를 남긴다
- 구조화 출력 결과 검사 `inspect`: 빈 칸(`research.empty_fields`, 앞쪽 `EMPTY_SHOWN` 개와 수)을 남긴다
- `canon_notes` 는 실제 경로의 정리 함수(`clean_storyboard` · `cue.clean` · `fit_arc` · `clean_heat` · `validate_parts`, 화 번호 맞춤)를 사본에 돌려 Canon 이 정리하거나 거절하는 것을 `PromptRun.notes` 에 적는다
- 검사는 작품을 바꾸지 않고, 검사가 실패해도 결과는 남긴다
- `view` 의 `spec` 은 화면에 보일 돌리는 방식(스키마 이름 · 단계 이름 `STAGE_LABELS` · 한도 · 백엔드마다 쓸 모델과 추론 강도)이다
- 어림 비용 `run_cost`: `usage.PRICED` 백엔드만 `usage.rate` · `usage.cost` 로 센다. 로컬 · mock 은 0, 가격 · 토큰을 모르면 None
- 세션마다 시도 `MAX_TRIALS` 개까지. 저절로 지우지 않고 막는다(`room`)
- 되돌리기 `restore`: 그 시도의 프롬프트 · 온도 · 출처를 지금 칸으로. 백엔드는 그대로 둔다
- 불러오기 `load_prompt`: Canon 프롬프트를 `prompts.brief_request` 로 조립해 시스템 · 요청 칸에 채운다. 스키마 글은 칸에 넣지 않고 출처(`PromptSource.schema_name` · `stage`)에 둔다
- 갈래는 `prompts.BRIEF_KINDS` 그대로다. 작품에 맞는 갈래만 `kinds_for` 로 고른다(부 구성은 장편만)
- 대화로 다듬기 갈래(설정 도우미 · 문체 · 플롯 대화 에이전트 첫 단계 · 본문 부분 수정)는 작가의 말 자리에 `prompts.CHAT_MESSAGE` 를 넣는다. 작가가 그 줄을 바꿔 돌린다
- 대화로 다듬기 갈래는 `canon_notes` 검사가 없다(빈 칸 검사만 한다)
- 고르는 단위(`BriefKind.scope`): 화, 플롯 초안 구간(`groups_of`, `pipeline.act_groups`), 작품 하나(구조 · 완급 계획 · 부 구성, 화를 쓰지 않아 n 은 0)
- 한 화 플롯은 플롯이 초안인 화만 조립한다(`pipeline.draft_episode` 와 같다)
- 스토리보드 · 큐 시트는 플롯을 확정한 화만 조립한다(`pipeline` 과 같다). 앞 화가 끝났는지(`require_previous`)는 보지 않는다
- 불러오기 재료는 예시 작품(`example_project`, mock LLM 으로 만든 저장하지 않는 6화 단편, 한 번 만들어 사본을 줌)이나 고른 작품(`store.load`, 읽기만)
- 예시 작품은 1 · 2화에 본문과 상태 반영이 있고 3화는 플롯만 확정했다. 갈래마다 조립하는 화는 `EXAMPLE_N`, 없는 갈래는 `default_n`
- 예시 장편 `example_serial`: mock LLM 으로 만든 저장하지 않는 300화 장편이다. 첫 아크는 본문과 상태 반영까지, 둘째 아크는 끝 세 화만 플롯 초안이다
- 예시 장편은 프롬프트 관리 페이지(`routes/prompts.py`)의 견본이다. 한 번 만들어 사본을 준다
- 단계 이름 `STAGE_LABELS` 에는 부분 수정(`revise`) · 플롯 대화(`chat`)도 있다
- 고른 작품의 기본 화 `default_n`: 본문이 있어야 하는 갈래는 본문이 있는 마지막 화, 나머지는 본문이 없는 첫 화
- 확정 · 초안이어야 하는 갈래는 본문이 없고 그 조건에 맞는 첫 화, 플롯 초안은 초안이 든 첫 구간
- 불러온 출처 `PromptSource`(갈래 · 이름 · 작품 · 화 · 지문 `sig`)를 세션에 두고, 돌릴 때 시도에 옮긴다. 지문이 다르면 `source_edited`
- 조립한 프롬프트가 `TEXT_MAX` 를 넘으면 자르지 않고 막는다
- 제목이 요청 첫 줄이나 앞서 불러온 이름으로 지은 것이면 이번 불러온 이름으로 바꾼다. 작가가 적은 제목은 남긴다
- 한 화 플롯 프롬프트의 새 인물 이름 후보(`prompts.new_cast_rule`)는 불러올 때마다 무작위로 바뀐다
- 고르기 칸 재료 `sources`(갈래 · 화 목록 · 플롯 초안 구간 · 갈래별 기본 화)
- `llm.POLICY_NOTE` 는 칸에 넣지 않는다. Gemini · 로컬 백엔드가 보낼 때 붙이므로(`llm.with_note`) 칸에 넣으면 두 번 붙는다
- 대신 `limits` 가 `policy_note` 로 그 줄을 주고 화면이 요청 칸 아래에 보인다
- 시험 `tests/test_promptlab.py`

### `canon/refs.py`

- 레퍼런스 원고(작품 밖 화면, 주소 `#/refs[/<id>[/<차례> | cuts]]`, 설계는 [docs/refs/](../refs/README.md))
- 작가가 넣은 다른 소설 원고 txt 를 화 표시로 화 단위로 나눠 작품 밖에 둔다
- 작품에는 연결하지 않는다. 고른 화로 문체 라이브러리 항목이나 역설계 실험을 만들고 그 결과물만 작품에 들어간다
- 작품 밖 `<CANON_HOME>/.refs/<id>/`(`CANON_REFS` 로 경로 변경): 정규화한 원문 `source.txt` 와 `ref.json`(`RefBook`)
- `source.txt` 와 `ref.json` 은 `store.write_atomic` 으로 바꿔치기해 쓴다
- 경계는 줄 번호(`RefCut.line` · 본문 시작 `body`)로만 적는다. 합치기 · 나누기를 다시 해도 원문은 그대로다
- 화 글은 읽을 때 켠 경계로 잘라 낸다(`assemble`, 화 끝 작가의 말 떼기 `_tail` · `strip_tails`)
- 되풀이 줄 찾기 `find_repeats`: 켠 화의 첫머리 · 끝 `REPEAT_EDGE` 줄에서 `REPEAT_LEN` 자 넘는 같은 줄이 `REPEAT_SHARE` 넘는 화(적어도 `REPEAT_MIN_EPS` 화)에 나오면 고지문 · 공지로 본다
- 고른 되풀이 줄(`RefBook.strip_repeats`)은 `assemble` 이 화 어디서든 빼고(`_drop_repeats`, 뒤 빈 줄도) 그 뒤에 작가의 말을 뗀다. 뗀 글자 수는 `repeat_cut`
- 미리보기는 찾은 줄 `repeats_found` 와 뗄 줄 `repeats` 를 준다. `repeats` 를 보내지 않으면 찾은 줄을 모두 뗀다. 옛 ref.json 은 `strip_repeats` 가 비어 떼지 않는다
- 나누기 규칙은 여기 한 곳이다(`detect` · `preview` · 역설계용 `split`): 화 표시 줄 → 기호 줄 → 빈 줄 셋 넘게 → 한 화
- 화 표시 후보 `candidates`: 단위 화 · 회 · 편 · 話 · 장(숫자 뒤) · EP · Chapter(숫자 앞), 특수 화(프롤로그 · 외전 · 에필로그 · 후기)
- 숫자 앞 글은 비었거나 `COMMON_MIN` 번 넘게 같을 때만 받는다(공통 머리 `common_head`, 본문 속 '영화 3편' 거르기)
- 단위마다 번호 줄기(`_lis`, 가장 긴 증가 수열)를 재 가장 긴 단위를 고르고 나머지는 `alts` 로 준다
- 표시 `_mark`: 목차(`toc`) · 반복 머리 묶기 · 본문 속 언급(`mention`, 줄기 밖이라 끔) · 빠짐 · 겹침 · 거꾸로 · 다시 시작(파일 경계)
- 번호가 1부터 다시 시작하는 자리(2부 1화)는 새 줄기로 나눠 잰다(`_runs`: 앞 두 줄보다 작거나 같고 뒤로 세 줄 넘게 이어 오를 때). 다시 시작한 첫 화에 `restart` 를 단다
- 제목은 화 표시 전체를 감싼 괄호의 닫는 쪽을 뗀다(`_title`, '< EP.1 : 시작 >' → '시작')
- 번호 화 표시의 제목이 특수 화 이름뿐이면 그 종류로 본다(`_special`, 'EP.0 : 프롤로그' → 프롤로그)
- 직접 패턴(`rule` custom)은 예시 한 줄에서 꼴을 만든다(`_custom_re`)
- 직접 패턴의 예시 끝 기호 묶음('<-- 01. 제목 -->' 의 '-->')은 닫는 기호로 보고 제목에서 뗀다
- 직접 패턴의 같은 번호가 200자 넘게 떨어져 되풀이되고 번호가 줄지 않으면 그 번호를 부 번호(`part`)로 보고 화 번호를 1부터 매긴다(`_parts`, 응답 `parts` 는 부 수)
- 부 번호가 거꾸로 가는 곳은 부 표시 수의 5%(`PART_BACK`, 적어도 1번)까지 견디고 그 화에 '번호 거꾸로' 를 단다
- 저장 `create`(권리 확인 `rights` 필수) · `update` · `delete` · `entries` · `summary`
- 저장 때 화별 지표(`RefEp`: 글자 수 · 대사 비율 · 문장 · 문단 평균, `metrics.measure`)를 재 둔다. AI 호출 없음
- 문체 만들기 원문 `sample`(고른 화를 이어 `SAMPLE_MAX` 자까지) · 역설계 실험 만들기 `to_revlab`(`revlab.create_episodes`, 화 수는 막지 않고 글자 수만 `revlab.MAX_CHARS`) · 있는 실험에 잇기 `to_lab`(`revlab.append_episodes`, 화마다 출처 `RevSource`) · 화 차례별 지금 글 `texts`(출처 상태용)
- 이 원고로 만든 것 `made`(`RefMade`, 문체는 `POST /api/styles` 의 `ref` · `ref_eps` 로 남긴다)
- 내 작품과 견주기 `compare`(본문 있는 화 지표, 작품에 쓰지 않음)
- 받은 화 대기열 `inbox` · `inbox_add` · `inbox_clear`: newto 로 가져온 화를 `<refs 폴더>/inbox.json` 에 둔다(원고 폴더가 아니라 `entries` 가 읽지 않음)
- newto 가져오기 `newto_fetch`: newto 폴더(`newto_dir`, `CANON_NEWTO` 또는 저장소 옆 `newto`)에서 `npm run verify -- --headless --work <번호> --wait-on-limit` 를 돌린다
- 마지막 출력 줄은 작업 `note`, `[i/n]` 줄은 `done` · `total` 로 둔다. 멈추기는 프로세스 묶음(npm · node · Chrome)에 SIGTERM 을 보낸다
- 끝나거나 멈추면 합본 `<작품 이름> [<번호>].txt` 의 화(`newto_sections`, `===== 001화 [회차] =====` 머리)를 받은 화에 넣는다(`newto_import`). 화 이름이 `title`, 작품 이름이 `book`
- 끝 코드가 0 이 아니어도 합본에 화가 있으면 성공으로 본다(접근 제한 · 요청 한도로 남은 화는 다시 돌리면 잇는다)
- 같은 글은 한 번만 둔다(주소가 같아도 글이 다른 사이트가 있어 글로 견줌). 상한 `INBOX_MAX` 화 · 한 화 `INBOX_TEXT_MAX` 자
- 웹은 `/api/refs…`(`routes/refs.py`)
- 화면은 `static/refs.js`
- 시험 `tests/test_refs.py`(원고는 `tests/fixtures/refs_story.txt`, 직접 지은 글)

### `canon/research.py`

- 연구 화면(모델 실험) 로직
- 서버 점검
- 샘플 비교
- 실험 백엔드 `PROVIDERS`: gemini · local · claude · claude-api · mock. `make_backend` 가 Claude 두 백엔드는 `llm.make_llm` 으로 만들고 온도는 넘기지 않는다
- 샘플 생성 `sample` 은 백엔드마다 스레드를 띄워 동시에 부르고(`_sample_one`), 결과는 고른 차례로 준다. 스레드마다 `contextvars.copy_context()` 로 사용량 기록 정보를 넘긴다
- 샘플 생성 `sample` 은 실패하면 받은 원문(`last_raw`, `RAW_MAX` 자까지)과 끝난 이유(`last_finish`)를 줄에 남긴다
- 샘플 생성 `sample` 은 schema 를 주면 `llm.json` 으로 받아 검증한 JSON 을 글로 돌려준다. mock 은 hint 없이 스키마 응답을 짓지 못해 글로 받는다
- `sample` 의 stage · out_tokens: 모델 칸이 빈 백엔드는 그 단계의 모델 · 추론 강도(`stage_defaults`)로 만들고 출력 한도(`llm.out_cap`)를 건다
- `stage_defaults`: 단계 모델은 그 단계 백엔드가 같을 때만 쓰고, 추론 강도는 `settings.provider_effort` 로 바꿔 Gemini · Claude 에만 넘긴다
- 단계 시험
- 컨텍스트 크기
- 검수 시험
  - 모순을 심고 `TRIAL_MODES` 마다 찾는지
  - `check_trial`
  - 장편은 검수 넓히기 `widen`
  - 판단기를 주면 두 걸음 검수 `twostep`도
  - 판단기를 고르지 않았거나 모델 · 주소가 비면 `judge_backend` 가 `CANON_JUDGE` · `_MODEL` · `_URL` 로 채운다
  - 장면 연출 규칙 검수 `stage` 는 고르면: 사건마다 `pipeline.extract_stage` → `stage.episode_issues`
  - `_stage_run`
  - 갈래별 찾은 수 `by_kind` · 기록 합계 `check_totals`
  - 검수 지시문 영어판 비교 `TRIAL_LANGS`(=`prompts.CHECK_LANGS`): `langs` 에 en 을 주면 같은 사본의 full · budget 을 영어판으로도 검수한다(`_check_run`)
  - 영어판은 시스템 프롬프트 `prompts.checker_system` · 자료 칸 제목 · 요구사항 · 응답 설명 `schema.ConsistencyReportEn` 만 영어다. 작품 자료 · 인용 · 기능별 검수 규칙은 한국어 그대로
  - 한국어판 · 영어판 짝 누적 `lang_tally`(두 판 모두 성공한 줄만). `check_totals` 는 한국어판만 센다
- 블라인드 비교
- 그 화를 이미 쓴 모델은 다시 쓰지 않고 그 판을 가져온다(`kept_draft`: 지금 본문 → 고르기를 기다리는 새 판 → 남겨 둔 판, `Episode.written_by` · `TextVersion.model` 과 모델 이름이 같을 때)
- 두 안이 같은 모델이면 아무것도 가져오지 않는다(`kept_drafts`). 모델 이름을 모르는 백엔드(`…:default`, 이름 없는 Claude 구독)는 가져오지 않는다
- 가져온 안과 출처는 `key.json` 의 `kept` 에 두고, 고르기 전에는 수(`kept_count`)만 준다
- 가져온 안을 고르면 규칙을 다시 걸지 않는다(`_adopt`: 지금 본문이면 그대로, 새 판이면 `adopt_candidate`, 남겨 둔 판이면 `restore_version`)
- 비교본 폴더 `compare/<화 두 자리>/` 는 `store.compare_dir` 가 정한다. 화를 넣고 빼면 `store.renumber_side_files` 가 옮긴다
- 비교본(`<번호>.md`) · `key.json` · hook 보고서는 `store.write_atomic` 으로 바꿔치기해 쓴다. `log.jsonl` 은 덧붙인다
- 고르지 않은 비교본 목록 `open_compares`
- `open_compares` 는 폴더 이름이 아니라 화 번호 차례로 준다(100화가 99화 앞에 오지 않게)
- 작품 데이터와 분리해 `research/log.jsonl` 에 기록
- 읽을 때(`history` · `latest`) 쓰다 끊긴 줄과 빈 줄은 건너뛴다(`_row`)
- 갈래마다 마지막 기록 `latest`(연구 개요가 `history` 30개 밖의 실험도 보인다)

### `canon/revlab.py`

- 역설계 실험(작품 밖 화면, 주소 `#/revlab/<번호>/<화>`, 작품을 열지 않고 쓴다)
- 작가가 넣은 소설을 거꾸로 화별 플롯 · 스토리보드 · 큐 시트 · 이야기 줄기로 푼다
- 그 큐 시트로 같은 화를 다시 써서(되돌려 쓰기) 원문과 견준다
- 작품 밖 `<CANON_HOME>/.revlab/<번호>.json`(`RevLab`, `load` · `save` · `with_lock` · `create` · `replace_text`, 화 이어 붙이기 `append_text`: 마지막 화 + 1 부터, 앞 화 결과는 그대로)
- `save` 는 `store.write_atomic` 으로 바꿔치기해 쓴다
- 화 하나 고치기(`edit_episode`, 웹 `PUT /api/revlab/{번호}/episodes/{n}`): 글이 바뀌면 그 화의 결과 · 되돌려 쓴 판만 지운다. 제목 줄만 바뀌면 결과는 그대로
- 화 빼기(`drop_episode`, 웹 `DELETE /api/revlab/{번호}/episodes/{n}`): 뒤 화 번호와 줄기의 `branch_ep` · `join_ep` 를 하나씩 당긴다. 마지막 남은 화는 빼지 않는다
- 화 고치기 · 빼기는 그 실험의 작업이 도는 동안 409(`web._rev_idle`, 작업이 화 번호로 결과를 넣는다)
- 문체 프로필 고르기 · 지우기(웹 `POST /api/revlab/{번호}/styles/{id}/select` · `DELETE …/styles/{id}`)는 `rev_style` 작업이 도는 동안만 409
- 문체 프로필 하나 보기 · 견주기 `GET /api/revlab/{번호}/styles/{id}?against=` · 메모 `PUT …/styles/{id}`
- 화 나누기(`split`: 레퍼런스 원고와 같은 규칙 `refs.split` 에 앞머리 200자 넘으면 화 하나 규칙을 더함, `check_text`)
- 나눠 둔 화로 실험 만들기(`create_episodes`, 레퍼런스 원고에서 보내기) · 잇기(`append_episodes`: 다시 나누지 않음, 같은 원고 화는 뺌, 웹은 `POST /api/revlab/{번호}/episodes` 의 `{ref, eps}`)
- 화 출처 `RevEpisode.source`(`RevSource`, 프롬프트에 넣지 않음)와 화면 값의 출처 상태 `sources`(same · changed · gone)
- 큐 경계(`locate`: AI 가 원문 글자 그대로 인용한 시작 문장 `RevCue.start` 를 차례로 찾음, 글자 수는 `measured`)
- 원문에 없는 핵심 대사 빼기(`keep_lines`, `cue._flat`)
- 응답 넣기(`apply_episode` · 줄기 `apply_lines` · 인물 `merge_cast`, 화마다 배경 · 사실 · 관계 · 호칭)
- 줄기를 다시 넣으면(`apply_lines`) 앞 답이 화에 붙인 줄기 id 를 먼저 뗀다
- 첫 화 번호(`guess_first` · `renumber`)
- 작가 고침(`set_sheet`, 큐 수가 바뀌면 경계를 지움)
- 되돌려 쓰기 사본
  - `world`: 앞 화는 원문을 반영한 화
  - 인물 id 는 이름
  - 그 화까지 읽은 배경 · 사실 · 관계 · 호칭 `context_upto`
  - 문체 프로필은 고를 때만이고 예시 문단은 늘 비움
- 되돌려 쓰기 실행(`run_write`, 새 판을 `RevEpisode.takes` 에 더함, `pipeline.write_scored`)
- 판 상한 `MAX_TAKES`(8, 저절로 지우지 않음, 자리 확인 `room`) · 판 번호 `next_no`(지운 번호를 다시 쓰지 않음, `RevEpisode.last_take`) · 판 지우기 `drop_take`(웹 `DELETE /api/revlab/{번호}/episodes/{n}/takes/{판}`)
- 판마다 가려 읽기(`RevBlind`: 차례 · 고름 · 앞서 끝낸 가려 읽기 수 `seen`), 가려 읽을 판 `pending`(먼저 쓴 판부터)
- 옛 파일의 `take` · `take_style` 은 `RevEpisode` before 검사기가 판 1 · 2 로 옮긴다
- 블라인드 고르기(`pick`, 판 번호를 주면 지금 가려 읽을 판인지 확인)
- 지표(`compare`, `cue.score`, 원문과 판마다 condition 't<판 번호>')
- 문체 측정(`compare`): 이 화를 뺀 원문 기준 문체 거리(`style_base`, 기준을 못 만들면 `style_note` 에 이유) · 쉼표 문장 비율 · 표지 빈도 경고 · 판이 원문과 장치 예시를 옮긴 문장(`copied` · `copied_examples`)
- 문체 역설계(`run_style`, `pipeline.analyze_style(passages=False)`: 버릴 대표 문단은 묻지 않는다, `prompts.style_prompt`)
- 문체 역설계는 실험 인물 이름을 `count_markers` 에 넘겨 이름이 든 표지를 거른다
- 문체 프로필 기록(`RevLab.styles` · `style_id`, 더하기 `add_style`, 같은 프로필이면 더하지 않고 고름)
- 기록 상한 `STYLE_KEEP`(넘치면 지금 프로필과 판이 가리키는 프로필을 빼고 오래된 것부터 지움, 지울 것이 없으면 `check_style_room` 이 AI 를 부르기 전에 막음)
- 고르기 `select_style` · 지우기 `drop_style`(지금 프로필은 하나만 남았을 때만) · 메모 `note_style`
- 견주기 `style_diff` · `style_view`(`library.diff`, 기본은 지금 프로필과)
- 구조 · 호흡 `pace`(화마다 `_pace_row`: 큐 글자 수로 가중한 평균 긴장 · 최고 긴장과 자리 · 끝 긴장 · D 큐 · 빠른 템포 비율, 원문에서 잰 대사 비율 · 문장 길이, 끝맺음. 요약: 끝맺음 수 · 숨 고르기 화 `REST_PEAK` · 긴장 `TOP_TENSION` 화와 간격 · 분량 변동. 저장 안 함, AI 없음), 웹 `GET /api/revlab/<번호>/pace`
- 아크 · 부 역설계 `run_arcs`(`can_arcs`: 4화 넘게 · 모든 화 역설계, `pipeline.reverse_arcs`, 응답 `RevArcSet`), 정리 `clean_arcs`(`_cover` · `_fit_acts`), 저장 `RevLab.arcs`(`RevArcPlan`)
  - 작가 고침 `set_arcs`(by author · both), 그 뒤 AI 안은 `arc_offer`(`put_arcs`, 고르기 `take_offer`), 지우기 `clear_arcs`
  - 화 번호 옮기기 `_shift_arcs`, 낡음 `arc_state`(아크 밖 화 · 다시 역설계한 화). 웹 `PUT` · `DELETE /api/revlab/<번호>/arcs`, `POST .../arcs/offer`
- 라이브러리에 저장 `to_library`(원문 앞부분과 AI 없이 고른 대표 문단 `pick_passages`, 항목 id `RevStyle.library`, 라이브러리에서 지우면 화면 값 `library` 가 빔), 웹 `POST /api/revlab/<번호>/styles/<id>/library`
- 문단 연습장 카드 `paragraph_card`: 원문에서 고른 문단으로 `SceneCard` 를 채운다. AI 없음, 실험은 바꾸지 않음
  - 원문 자리 `find_passage`: 글자 그대로 없으면 공백 묶음을 느슨하게 찾는다 (화면은 큐 칸마다 앞뒤 줄바꿈을 뗀다)
  - 든 큐 `_cue_at`(경계가 큐 수와 맞을 때만)의 일 · 장면(장소 · 자리 · 때 · 있는 인물), 화 플롯 시점 인물, 실험 인물(성격 · 말투)
  - 큐 기능 · 긴장 · 템포 · 편성은 '더 지킬 것' 한 줄. 문단은 본보기 `SceneCard.model`, 출처 `ref`
  - 지금 프로필을 라이브러리에 저장했으면 그 문체를 고른다
  - 웹 `POST /api/revlab/<번호>/episodes/<화>/studio`(세션을 만들어 돌려줌)
- 기록 화면 값 `style_items`(원문 앞부분이 바뀌었는지 `basis_ok`, `style_basis`)
- 판은 넣은 프로필 번호 `RevTake.style_id` 를 남기고, `compare` · `_take_view` 가 `style_old` · `style_gone` 을 붙임
- 글을 통째로 바꾸면(`replace_text`) 기록은 남기고 `style_id` 만 비움
- 옛 파일의 `style` · `style_model` · `style_at` 은 읽을 때 1번 항목으로 옮김(`RevLab._old_style`)
- 비용 추정(`estimate`: parse · write · style)
- 실험별 AI(`RevLab.ai`, `RevAI`): 단계 `AI_STAGES`(plan 역설계 · 줄기 · 문체, write 되돌려 쓰기)마다 프리셋 id 또는 백엔드 `AI_PROVIDERS` + 모델
- 쓸 AI 풀기 `ai_choice`(mock 설정 → 프리셋 → 직접 고름 → 설정 단계 칸, 작품 프리셋은 보지 않음) · LLM 만들기 `llm_for` · 고르기 `set_ai`(웹 `PUT /api/revlab/{번호}/ai`) · 화면 값 `ai_view` · 기본 모델 이름 `default_model`
- 비용 추정 모델도 `ai_choice` 로 고른다
- 비용 추정의 토큰은 고른 백엔드 · 모델의 `usage.token_rate` 로 센다
- 역설계 실행(`run_parse`)
- 화면 값(`view`, 고르기 전에는 차례를 뺌)
- AI 호출은 `pipeline.reverse_episode` · `reverse_lines`(plan 단계, 응답 칸은 모두 required, 사건 · 장면 · 큐가 비면 한 번 더 묻고 그래도 비면 저장하지 않음 `rev_empty`)
- 프롬프트 `prompts.rev_rules` · `rev_prompt` · `rev_lines_prompt` · `SYSTEM_REVERSE`
- 가짜 응답 `mock_revlab.py`
- 웹은 `/api/revlab…`
- 작업은 `POST /api/revlab/{번호}/jobs`(kind parse · write · style → 작업 `rev_parse` · `rev_write` · `rev_style`, ep 가 실험 번호, project 자리는 `JOBS`, 사용량 범위에 작품 없음)
- 화면은 `static/revlab.js`
- 시험 `tests/test_revlab.py`(글은 `tests/fixtures/revlab_story.txt`, 직접 지은 글)

### `canon/routes/promptlab.py`

- 프롬프트 놀이터 웹 라우트(`/api/promptlab/...`)
- `web.py` 맨 끝의 `_attach_routes` 가 `router` 를 앱에 붙이고 `EXPORTS` 의 이름을 `web` 에도 둔다
- 돌리기 `POST /api/promptlab/{id}/run` 은 받은 칸을 먼저 저장하고, 작업 목록을 거치지 않고 바로 돌려준다(`usage.scope(task="promptlab")`)
- 도는 동안 바뀐 시도(별표 · 메모)를 덮지 않게 저장 직전에 세션을 다시 읽는다
- 불러오기 고르기 재료 `GET /api/promptlab/sources?project=` · 불러오기 `POST /api/promptlab/{id}/load`(갈래 · 작품 · 화)

### `canon/routes/prompts.py`

- 프롬프트 관리 페이지 웹 라우트(`/api/prompts/...`). LLM 을 부르지 않고 아무것도 저장하지 않는다
- `web.py` 맨 끝의 `_attach_routes` 가 `router` 를 앱에 붙이고 `EXPORTS` 의 이름을 `web` 에도 둔다
- 표 `GET /api/prompts/kinds`: 갈래(`prompts.KINDS`) · 조각(`prompts.PIECES`, 조각마다 들어가는 갈래) · 주제 꼬리표 · 자리 · 묶음 차례
- 한 갈래 `GET /api/prompts/kinds/{id}?project=&n=`: 조립 보기가 있으면 `prompts.view_request` 로 견본 요청을 조립하고 조각마다 견본 글 · 글자 · 추정 토큰 · `found` 를 붙인다
- `found` 는 조각 글이 조립한 요청에 있는지(`prompts.found_in`)다. 보내기 직전 조각(`SEND_PIECES`)은 조립한 글에 없어 `None` 이다
- 견본 `project`: 빈 값은 예시 작품, `:serial` 은 예시 장편(`promptlab.example_serial`), 그 밖은 작품 폴더 이름(`promptlab._project`, 읽기만)
- 장편에만 있는 갈래(부 구성)는 예시 작품을 골라도 예시 장편으로 조립한다
- 화를 주지 않으면 놀이터 불러오기와 같은 기본 화(`promptlab._default`)다. 다시 생성 · 서술 다듬기 · 동선 검수는 본문이 있는 마지막 화다
- 만들 수 없는 견본(본문이 없는 화, 단편의 장편 갈래)은 200 으로 `error` 에 까닭을 담는다. 모르는 갈래 · 작품은 404
- 조립 보기가 없는 갈래는 표 줄과 그 갈래의 조각만 준다
- 주제 `GET /api/prompts/topics/{tag}`: 그 꼬리표를 단 조각을 모든 갈래에서 모아, 조립 보기가 있는 첫 갈래로 만든 견본 글을 붙인다
- 조각 `GET /api/prompts/pieces/{id}`: 조각 하나와 그 견본 글
- 시험 `tests/test_prompt_registry.py` 의 `test_routes`

### `canon/routes/refs.py`

- 레퍼런스 원고 웹 라우트(`/api/refs/...`)
- `web.py` 맨 끝의 `_attach_routes` 가 `router` 를 앱에 붙이고 `EXPORTS` 의 이름을 `web` 에도 둔다
- 공용 도우미(`_load` · `_save` · `_edit` 등)는 `..web` 에서 불러 쓴다
- 받은 화 `GET` · `DELETE /api/refs/inbox`. `GET` 은 newto 폴더가 있는지(`newto`)도 준다. `/api/refs/{rid}` 보다 먼저 붙인다
- newto 가져오기 `POST /api/refs/newto`(작업 kind `ref_newto`, project `REF_JOBS` = `.refs`, 한 번에 하나)

### `canon/routes/research.py`

- 연구 화면 웹 라우트(`/api/projects/{name}/research/...`)
- 실험 다섯(샘플 · 단계 · 검수 시험 · 프롬프트 재기 · 블라인드 비교 쓰기)은 작업 `rs_<실험>` 으로도 돈다(`_job_research`, `JobIn.trial` 에 옛 요청 모양). 화면은 작업으로 부른다
- 작업은 옛 경로와 같은 기록 줄을 `research/log.jsonl` 에 남기고, 사용량을 source · stage `research` 와 실험 이름으로 적는다(`_rs_scope`)
- 기록에 결과 전체가 남는 실험(샘플 · 단계 · 검수 시험)은 작업 결과에 기록 id 만 싣는다. 프롬프트 재기는 기록이 요약뿐이라 표 전체를 싣는다
- 실험이 고른 백엔드를 쓰므로 `OWN_LLM_KINDS` 에 든다. 모르는 백엔드 · 같은 두 백엔드 · 없는 화는 시작 전에 400 이다
- 옛 동기 경로(`research/sample` · `stage` · `check` · `budget` · `compare/{n}`)는 시험이 쓰는 동안 남긴다
- 사용량 응답 모델(`UsageBucket` · `UsageCall` · `PriceTable`)은 `usage.summary` · `usage.price_table` 의 칸 가운데 적힌 것만 내보낸다
- `usage` 의 묶음 · 호출 줄 · 가격표에 새 칸을 더하면 이 응답 모델에도 더한다
- `web.py` 맨 끝의 `_attach_routes` 가 `router` 를 앱에 붙이고 `EXPORTS` 의 이름을 `web` 에도 둔다
- 공용 도우미(`_load` · `_save` · `_edit` 등)는 `..web` 에서 불러 쓴다

### `canon/routes/revlab.py`

- 역설계 실험 웹 라우트(`/api/revlab/...`)
- `web.py` 맨 끝의 `_attach_routes` 가 `router` 를 앱에 붙이고 `EXPORTS` 의 이름을 `web` 에도 둔다
- 공용 도우미(`_load` · `_save` · `_edit` 등)는 `..web` 에서 불러 쓴다

### `canon/routes/soelab.py`

- 쇠맛 실험실 웹 라우트(`/api/soelab/...`)
- `web.py` 맨 끝의 `_attach_routes` 가 `router` 를 앱에 붙이고 `EXPORTS` 의 이름을 `web` 에도 둔다
- 공용 도우미(`_load` · `_save` · `_edit` 등)는 `..web` 에서 불러 쓴다

### `canon/routes/studio.py`

- 문단 연습장 웹 라우트(`/api/studio/...`)
- AI 호출 넷(AI 안 · 박자 짚기 · 다른 상황 · 독자로 읽기)은 작업으로도 돈다(`POST /api/studio/{sid}/jobs`, 종류 `stu_<kind>`)
- 작품 밖이라 작업 목록의 project 자리는 `STU_JOBS`(`.studio`), 대상은 세션 id, 독자로 읽기는 화 자리에 시도 번호다
- 작업은 시작할 때 카드로 부르고, 결과를 남기기 직전에 세션을 다시 읽어 그사이 바뀐 시도를 덮지 않는다
- 옛 동기 경로(`draft` · `anatomy` · `variants` · `tries/{no}/reader`)는 시험이 쓰는 동안 남긴다
- `web.py` 맨 끝의 `_attach_routes` 가 `router` 를 앱에 붙이고 `EXPORTS` 의 이름을 `web` 에도 둔다
- 공용 도우미(`_load` · `_save` · `_edit` 등)는 `..web` 에서 불러 쓴다

### `canon/soelab.py`

- 쇠맛 실험실(작품 밖 `<CANON_HOME>/.soelab/`, 화면은 `static/soelab.js`, 웹 `/api/soelab/...`)
- 쇠맛 지표가 사람 글과 AI 글 · 작가 판정을 가르는지 잰다
- 프로세스 사이 잠금 `_lock`(`fcntl.flock`) · `save_json` · `append_label`(labels.jsonl 덧붙이기)
- `save_json` 은 잠금 안에서 `store.write_atomic` 으로 바꿔치기해 쓴다
- 정규화 `normalize` · `chunks`(2,000자 문장 끝)
- 모으기 `collect_revlab`(판마다 원천 take 't<판 번호>', 모델은 판의 백엔드 기록이 있으면 그것) · `collect_episodes`(모델은 `Episode.written_by` 가 있으면 record, 없으면 `write_models`: usage.jsonl 마지막 성공한 write) · `collect_edits` · `collect_research` · `collect_paste` → `add`(같은 글 한 번 · 원천 상한 `CAP`)
- 대기열 `extend_queue`(판정한 자리 · 다시 읽기 예정 · 예비는 고정, 1차 `FIRST` 묶음마다 한 조각)
- 세 자리마다 다시 읽기 자리 하나(`_redo_slot`), 여섯 자리마다 예비 자리 하나(`_spare_slot`)를 시드로 섞는다(이번 10개 안 자리가 짐작되지 않게)
- 판정 `judge` · `redo`(7일 뒤) · `hidden_ids`
- 화면에서 빼는 조각 `masked_ids`: 가린 조각 + 끝나지 않은 '이번 10개' `open_batch`
- 예비(모두의 1/6, `SPARE_EVERY`): 판정 뒤에도 정답을 숨기는 조각 `spare_ids` · 화면 값 `spare_state`
- 예비 열기: 판정 일관성이 보류일 때만 `open_spares`(15개까지 `SPARE_OPEN`)
- 판정 60개에 닿으면 재판정을 30개까지 예비로 채운다 `fill_at_60`(`FILL_AT` · `FILL_TO`, 한 번)
- 예비 정답 보여 주기 `show_spares`: 보류 아님 보고서 · 여기서 멈추기 · 90개 끝 가운데 먼저 온 때
- 채점 `features`(저장 안 함, 열쇠 `METRICS_VERSION`)
- 보고서 `report`(출처 기준 · revlab 짝 · 작가 판정 · 모델별 참고 · 패턴 · 판정 일관성) · `view` · `export`(원문 · quote · 메모 없음)
- 보고서는 끝나지 않은 이번 10개의 판정을 작가 판정 기준 · 패턴 · 판정 일관성에 넣지 않는다
- 화면 값 `screen`(진행 · 다시 읽기 `redo_state` · 최근 보고서 `latest_report` · `report_summary` · 낡음 `corpus_key` · `labels_key`)
- 진행 상태 `load_state` · `set_state`(`state.json`: 목표 40 · 60 · 90, 멈춤, 넘긴 정답 카드, `spare_shown`, `filled`)
- 가려 읽기 `judge_view` · `save_judge`(이번 10개를 마치면 다시 채점) · 정답 `batch_reveal`(끝난 이번 10개만) · `redo_view`
- 모으기 화면 `sources` · `gather` · `plan_add`(저장 없는 미리보기) · `collect`
- 조각 `pieces_view` · `piece_view` · `remove_piece` · `set_origin`(붙여 넣은 글만)
- 지표 하나 `metric_view`(점 그림 · 곡선 · 끝 조각은 가린 조각을 뺌)
- 패턴 확인 `check_items` · `check_view` · `save_check`(`SoeLabel` kind hit, 가리지 않음) · 혼동표 `patterns_view`
- 기록 `reports`, 지금 경고 기준 글 `threshold_text`
- 스키마 `SoeSource` · `SoePiece` · `SoeSpan` · `SoeLabel`
- 명령줄 `soelab collect | report | export`
- 시험 `tests/test_soelab.py` · `tests/test_soelab_web.py`
- LLM 호출 없음

### `canon/static/promptlab.js`

- 프롬프트 놀이터 화면(작품 밖 `#/promptlab[/<세션 id>]`)
- `app.js` 라우팅이 작품 밖 사이드바(`outSidebar`) 옆에 `viewPromptLab` 을 그린다(불러오기 `pgLoad`, 본문 폭 1280px)
- 작품 밖 도구 🧫 · 작품 사이드바 ⋯ 메뉴에서 들어온다
- 처음 화면 `pgHome`: 세션 카드(`.grid-auto`)와 머리 '+ 새 세션'
- 세션 화면 `pgSession`: 왼쪽 열 프롬프트 칸 `pgForm`, 오른쪽 넓은 열 시도 카드 `pgTrialCard`(고른 것 먼저, 그다음 최근 것 `pgOrder`)
- 칸은 `DRAFT_ROOTS.pgForm` 으로 묶고, 칸을 벗어날 때(change) 조용히 저장한다(`pgSave`). 돌리기는 칸을 함께 보낸다(`pgBody`)
- 온도 칸이 비었거나 숫자가 아니면 설정 값(null)을 보낸다(`pgBody`)
- 왼쪽 열 맨 위 불러오기 카드 `pgLoadCard`: 프롬프트 갈래 · 작품(예시 작품 또는 `S.projects`) · 화를 고르고 '불러오기'(`pgLoadPrompt`). 고르기 칸은 `S.pgSrc`(`pgSources`)
- 화 고르기 칸 `pgSrcChoices`: 작품 하나를 짜는 갈래는 칸이 없고, 플롯 초안은 구간, 나머지는 그 갈래의 조건(본문 · 확정 · 초안)에 맞는 화만
- 작품을 단편으로 바꿔 고른 갈래가 없으면 본문 쓰기로 돌아간다(`pgSources`)
- 요청 칸 아래에 Gemini · 로컬이 보낼 때 붙이는 `POLICY_NOTE` 줄을 보인다(`S.pgLimits.policyNote`)
- 불러온 갈래가 있으면 돌리는 방식 한 줄(`pgSpecLine`)과 모델 칸 안내(`pgModelHint`, 그 단계 모델 · 추론 강도)를 보인다
- 단계 모델이 없거나 칸에서 백엔드를 바꾼 줄의 모델 칸 안내는 그 백엔드의 기본 모델이다(`defaultModelName`)
- 결과 카드는 받은 형식 · 추론 강도 · 출력 한도를 함께 적는다(`pgRunCard`)
- 구조화 출력 결과는 Canon 정리와 빈 칸 수를 보이고 빈 칸 경로는 펼쳐 본다(`pgCheckHtml`)
- 실패한 결과는 받은 원문과 끝난 이유를 펼쳐 본다(`pgRawHtml`, MAX_TOKENS 면 출력 한도)
- 칸에 글이 있으면 불러오기 전에 묻는다. 불러온 출처는 프롬프트 카드와 시도 카드에 칩으로 보인다(`pgSourceLabel`, 고쳤으면 '(고침)')
- 시도 카드: 그 시도의 프롬프트(접힘), 지금 칸과 다른지(`pgDiff`), 백엔드마다 결과 카드 `pgRunCard`(초 · 글자 · 토큰 · 어림 비용 `usd`)
- 시도 동작: 고르기 `pgStar` · 메모 `data-pg-note` · 되돌리기 `pgRestore` · 결과 복사 `pgCopy` · 지우기 `pgDrop`
- 머리 주 버튼은 '돌리기'(백엔드가 둘 이상이면 곳 수). 시도가 꽉 차거나 백엔드가 없으면 막는다
- 공용 클래스(`.cols` · `.card` · `.grid-auto` · `.chip` · `.rw-text`)만 쓰고 CSS 를 더하지 않는다
- 순수 함수 · 화면 시험 `tests/test_promptlab_js.py`

### `canon/static/prompts.js`

- 프롬프트 관리 화면(작품 밖 `#/prompts[/<갈래>|/topic/<꼬리표>|/piece/<조각>]`, 서버 `routes/prompts.py`)
- `app.js` 라우팅이 작품 밖 사이드바 옆에 `viewPrompts` 를 그린다(불러오기 `pcLoad`, 본문 폭 1280px)
- 작품 밖 도구 🧩(놀이터 바로 뒤) · 작품 사이드바 ⋯ 메뉴 · 찾기 팔레트에서 들어온다
- 집필 화면 컨텍스트 대화상자의 펼친 블록에 '프롬프트 관리에서 보기' 링크가 있다(`write.js` `ctxMore`, 조각 id 는 블록 id 그대로)
- 머리의 `.seg` 로 갈래별 · 주제별을 바꾼다. 주 버튼은 없다
- 찾기 칸(`S.pcQ`)은 왼쪽 갈래 목록과 조각 줄을 이름 · 코드 이름 · 글로 거른다(`pcMatch`)
- 견본 칸(`S.pcSample`): 예시 작품 · 예시 장편 · `S.projects` 의 작품. 바꾸면 지금 화면을 다시 읽는다
- 왼쪽 갈래 목록 `pcGroups`: 조립 보기가 있는 갈래를 묶음 차례로, 나머지는 접힌 '표에만' 아래에 묶음별로
- 갈래 보기 `pcKindView`: 단계 · 응답 · 시스템 · 요청 · 호출 이름, 견본 합계(추정 토큰), 자리마다 카드와 캐시 설명(`PC_PLACE_NOTE`)
- 조각 줄 `pcPieceRow`: 이름 · 꼬리표 칩(주제 보기로 감) · 코드 이름 · 글자 수 · 횟수 처방 칩 · '이 견본에는 없음' 칩. 펼치면 들어가는 조건과 견본 글
- 펼친 조각은 `S.pcOpen` 에 남긴다
- 횟수 처방 `pcCounts`(`PC_COUNT_RX`): '열에 셋쯤' · '화에 셋까지' · '한두 번' · '3~7개' · '세 줄 넘게' 같은 숫자 지시를 표시만 한다
- '놀이터에서 열기'(`pcPlayground`): 작업지시서 갈래는 놀이터의 불러오기로, 그 밖이나 예시 장편은 조립한 글 그대로 새 놀이터 세션을 만든다
- 주제 보기 `pcTopicView`: 꼬리표를 단 조각을 자리 차례로(`pcTopic`) 모으고, 조각마다 자리 · 들어가는 갈래 · 견본을 만든 갈래를 적는다
- 조각 보기 `pcPieceView`: 자리 · 코드 · 조건 · 꼬리표 · 들어가는 갈래 링크 · 견본 글
- CSS 는 `.pc-` 묶음(왼쪽 목록 · 조각 줄)만 더했다
- 순수 함수 · 화면 시험 `tests/test_prompts_page_js.py`

### `canon/static/refs.js`

- 레퍼런스 원고 화면
  - 작품 밖 `#/refs` 목록 · `#/refs/new` 넣기 · `#/refs/<id>` 개요 · `#/refs/<id>/<차례>` 화 읽기 · `#/refs/<id>/cuts` 경계 고치기
  - `app.js` 라우팅이 `refLoad` 를 부르고 `viewRefs` 를 그림
  - 작품 밖 사이드바 도구 줄(`outNav`, 원고 수 `S.refList`)과 작품 사이드바 ⋯ 메뉴의 링크
- 화 표는 머리 줄이 위에 붙고(`thead th` sticky), 640px 이하에서는 안쪽 높이 제한(70vh)을 풀어 페이지와 함께 구른다
- 넣기: 파일 고르기 · 끌어 놓기(여러 파일은 이름 차례로 잇고 파일마다 시작 줄 `fileLines`) · 붙여 넣기
- 손가락 기기에서는 끌어 놓기 안내 대신 '파일 고르기'만 안내한다(`REF_TOUCH`)
- 인코딩은 브라우저가 푼다(`refDecode`: BOM → UTF-8 엄격 → CP949, 깨진 글자 수 `bad`, 고르기 칸)
- 사이트에서 가져오기: 넣기 화면의 newto 카드(`refClipCard`). 작품 번호 칸 · 가져오기(`POST /api/refs/newto`) · 진행 줄(멈추기는 `data-job-stop`) · 받은 화 목록
- 받은 화(`S.refInbox`)와 newto 폴더 유무(`S.refNewtoOk`)는 넣기 화면을 열 때 · 새로고침 · `ref_newto` 작업이 끝날 때(`refNewtoDone`) 읽는다
- '원고로 가져오기'는 받은 화를 원고 끝에 잇고(`refClipAppend`, 화 이름이 첫 줄) 그 화를 대기열에서 뺀다. 이름이 비었으면 작품 이름(`book`)을 넣는다
- 화 나누기는 서버(`POST /api/refs/split`)에 묻고, 켠 경계로 화를 자르고 글자 수를 세는 일은 화면이 한다(`refAssemble`, `refs.assemble` 과 같은 규칙)
- 경계 고치기(`refDraftView`): 규칙 줄(단위 칩 · 다른 규칙 · 직접 패턴 · 작가의 말 떼기 · 되돌리기) · 경계 목록(거르기 모두 · 확인할 것 · 끈 줄) · 원문 보기(줄을 눌러 여기서 나누기)
- 규칙 줄 아래 '화마다 되풀이되는 줄'(`refRepeatBox`): 찾은 줄마다 체크와 나온 화 수. 체크를 바꾸면 화면이 글자 수를 다시 센다(`refAssemble` 의 repeats, `refDropRepeats`)
- 고른 경계 칸(`refCutEditor`): 번호 · 제목 · 종류 · 여기부터 번호 다시 매기기 · 앞 화와 합치기
- 개요(`refOverview`): 고른 화로 하기(범위 `refRange`, 문체 만들기 `refToStyle`, 역설계 실험 만들기 `refToRevlab`) · 분량 막대 · 내 작품과 견주기 · 화 표(정렬) · 만든 것
- 문체 만들기는 `S.libFromRef` 에 원문을 담아 `#/styles/new` 로 간다(라이브러리 새 항목의 원문 칸)
- `refDecode` · `refAssemble` · `refRange` · `refEpRows` 는 순수 함수(`tests/test_refs.py`)
- CSS 는 JS 에서 주입

### `canon/static/revlab.js`

- 역설계 실험 화면
  - 작품 밖 `#/revlab[/<번호>[/<화 · cast · style · lines · metrics · ai>]]`
  - `app.js` 라우팅이 `viewRev` 를 그림
  - 불러오기 `revLoad` · `revFetch`
  - 작업 시작 `revStartJob`
  - 작품 사이드바 · ⋯ 메뉴의 링크
  - 작품 밖 사이드바(`outSidebar`)
  - 작품에서 들어왔으면 머리에 그 작품으로 가는 버튼 `revBackBtns`(`S.revFrom`, `routeNow` 가 적음)
- 원문에서 고르면 뜨는 '문단 연습장으로' 도구도 왼쪽을 0으로 두고 너비를 잰다(`passage.js` 의 `placeTool` 과 같은 규칙)
- 처음 화면(`revHome`)은 이어 하기 카드(목록 값 `revlab.summary` 의 `steps` · `updated` → `revLabLite` · `revHomeCard`)와 머리 '+ 새 실험 만들기'으로 펴는 새 실험 칸(`revNewToggle`, 붙여 넣기 · 첫 화 번호 짐작 `revGuessFirst` · 나누기 미리보기 `revPreview`, `revNewCard`)
- 나누기 미리보기는 서버(`POST /api/revlab/split`, 화 글 대신 글자 수)에 묻는다(`revSplitOf`, 잠깐 기다려 한 번, 받으면 `revSplitDone`)
- 실험 화면은 다른 단계 화면과 같은 공용 목차 틀(`outline.js`)의 왼쪽 목차 + 오른쪽 칸(`revLayout` · `revToc`, 칸은 남은 폭을 다 씀 `wide`)
- 목차 맨 위 개요
  - 주소에 화가 없을 때
  - `revOverview`: 역설계 전 풀 화 표 `revPickCard` · 받는 것 `revGetCard`
  - 뒤 화별 진행 `revProgressCard` · `revOverviewRow` · 실험 전체 카드 `revLabCards`
- 단계 다섯(`revSteps` · `revStepShare`, 누르면 그 단계 자리 `revStep`) · 화(`revTocEps`, 제목 옆 ＋ 로 화 이어 붙이기 칸 `revAddCard`, 미리보기 `revAppendPreview` 는 `append_text` 와 같은 규칙, '레퍼런스 원고에서' 갈래는 `revRefAddHtml` · 미리보기 `revRefPreview` · 다음 화 `revRefNext` 가 `append_episodes` 와 같은 규칙, 화 머리 출처 칩) · 실험 전체
  - 인물 · 관계 · 배경 `revContextCard`
  - 문체 프로필 `revStyleCard`
  - 문체 프로필 기록 목록(`.version-list`, 이 프로필 쓰기 `revStyleUse` · 지금과 견주기 `revStyleDiff` 가 `mystyle.js` 의 `changeLines` 로 그림 · 메모 `revStyleNote` · 지우기 `revStyleDrop` · 라이브러리에 저장 `revStyleToLib`, 저장한 뒤에는 라이브러리에서 보기 링크)
  - 판의 문체 한 줄 `revTakeStyle` · 다른 프로필로 쓴 판의 칩 `revStyleTag`(판 목록 · 지표 머리 · 나란히 읽기)
  - 이야기 줄기 `revLinesCard`
  - 구조 · 호흡 `revPaceCard`(칸을 열 때와 실험을 다시 받을 때 `revPaceLoad`, 화별 띠 그래프 `revPaceStrip`, 큐 긴장 계단 `revPaceSpark` · 순수 함수 `revPaceSteps`)
  - 아크 · 부 `revArcsCard`(띠 `revArcBand`, 표 `revArcTable`, 고치기 `revArcEditor` · `revArcInput`, 새 AI 안 고르기)
  - 지표 모아 보기 `revMetricsAll`
  - AI 모델 `revAICard`: 단계마다 설정을 따름 · 프리셋 · 직접 고르기(백엔드 나눔 버튼 · 모델 칸, 추천 목록은 `settings.js` `modelDatalist`), 만든 결과의 모델 `revAiMade`(지금 모델과 다르면 '다름'), 저장 `revAiSave`
  - 역설계할 화 표 · 문체 프로필 · 되돌려 쓰기 칸 아래 '쓸 AI' 줄 `revAiLine`(글은 `revAiText`, `app.js` `writerLabel` 재사용)
- 목차의 화 줄마다 ⋯ 메뉴(`revEpMenu`): 글 고치기 칸 `revEpEditCard` · 지우기(위험한 묶음에 접음)
- 머리 주 버튼은 다음 할 일(`revNext`, `revGoBtn`) · ⋯ 메뉴(글 · 이름 고치기 `revEditCard` · 다시 역설계 `revRedo`(개요의 풀 화 표) · 지우기)
- 글 · 이름 고치기 칸의 값은 `S.revEditDraft` 에 묶여 다시 그려도 남는다. 고친 것이 있으면 닫기 전에 묻는다
- 다른 실험으로 옮기면 고치던 글(글 · 이름 고치기 · 화 글 고치기 · 이어 붙일 글)을 그 실험 몫으로 맡기고(`revKeep`, `S.revKept`) 돌아오면 되살린다(`revRestore`)
- 고치던 글과 맡겨 둔 글은 페이지를 떠날 때 묻는다(`revUnsaved`, `app.js` `onKeptDraft`, `tests/test_revlab_js.py`)
- 오른쪽 맨 위 도는 작업 카드(`revRunCard`: 화별 줄 `revRunRows`, 작업의 `pending` · `done`, 한 화가 끝날 때마다 다시 받기 `revJobStep`)
- 화 탭 셋
  - 원문 · 큐 `revTextTab`: 큐 띠로 나눈 원문 `revText` · `revSegments`
  - 큐 목록 `revCueCard`(고른 큐만 펼침 `revCueGo`)
  - 큐 시트 편집기 `cue.js` `cueEditor`(열쇠 `rev:<화>`, `cueCtx` 의 kind rev)
  - 플롯 · 스토리보드
  - 되돌려 쓰기 `revWriteTab`: 가려 읽기(판마다, `revPick` 이 판 번호를 보냄) · 되돌려 쓴 판 표(`revTakePickHtml`, 읽기 `revReadTake` · 지우기 `revTakeDrop`) · 지표 견주기 `revMetricRows`(머리 `revScoreHead`) · 나란히 읽기(왼쪽 · 오른쪽 고름 `S.revRead`) · 새 판 쓰기
- 원문 칸(`.rev-src`)에서 글을 고르면 뜨는 '문단 연습장으로' 도구(`revParaTool` · `revParaSel` · `onRevParaSelect`, 동작 `revToStudio` → `#/studio/<id>`)
- 비용 추정은 고를 때 바로 묻고 버튼 글에 적는다(`revEst` · `revCost`, AI 없음)
- `revPreview` · `revAppendPreview` · `revSegments` · `revEpTitle` · `revSteps` · `revNext` · `revTocEps` · `revRunRows` · `revMetricRows` · `revStyleTag` · `revLabLite` · `revHomeCard` · `revOverviewRow` · `revAiText` · `revEpRange` · `revAiMade` · `revTakePicks` 는 순수 함수(`tests/test_revlab.py`)
- CSS 는 JS 에서 주입

### `canon/static/soelab.js`

- 쇠맛 실험실 화면(작품 밖 `#/soelab[/corpus | judge | redo | metrics[/<지표 id>] | patterns[/check] | log]`)
- 손가락 기기에서 '끌어 고르기' 를 고르면 길게 눌러 고른 뒤 손을 뗄 때(`touchend`) 문장을 고른다(`soeDragPick`)
- `app.js` 라우팅이 작품 밖 사이드바(`outSidebar`) 옆에 `viewSoe` 를 그린다(불러오기 `soeLoad`)
- 작품 사이드바 '실험' 묶음 🧪 · ⋯ 메뉴 · 작품 밖 도구에서 들어온다
- 공용 목차 틀(`outline.js`)의 목차 `soeToc`(개요 · 단계 넷 `soeSteps` · 지표 14줄 · 전체), 판정하는 동안은 지표 · 전체를 접음
- 오른쪽 칸 `.soe-main`(container `soe`: 760 · 560px)
- 머리 주 버튼 `soeGoBtn`(다음 할 일 `soeNext`)
- 개요 `soeOverview`(진행 `soeProgress`, 보류 `soeHoldCard`, 표 `soeTable`: 칸 `soeCell` · 범위 막대 `soeRng` · 모델별 줄)
- 말뭉치 `soeCorpus`(모으기 카드 `soeCollectCard` · 미리보기 `soePreviewHtml`)
- 가려 읽기 `soeJudgePane`(원고 `soeMs`, 떠 있는 도구 `soeTool` · 자리 `soePlace`, 판정 띠 `soeStrip`, 손가락 기기는 문장 누르기)
- 정답 카드 `soeBatchCard`, 1차 · 60 · 90개 카드 `soeMilestoneCard`, 다시 읽기 `soeRedoPane`
- 지표 대조 `soeMetricsPane` · 지표 하나 `soeMetricOne`(`soeDotPlot` · `soeRoc`)
- 패턴 혼동표 `soePatterns` · 패턴 확인 `soeCheckPane` · 기록 `soeLogPane`
- 순수 함수 `soeVerdict`(labstats.verdict 와 같은 규칙) · `soeSentences` · `soeSentenceAt`(metrics.sentence_spans 와 같은 경계) · `soeRedoDue` · `soeNext` · `soeSteps` · `soeRound` · `soeMarkMerge`
- 순수 함수 시험 `tests/test_soelab_js.py`
- CSS 는 JS 에서 주입한다

### `canon/static/studio.js`

- 문단 연습장 화면(작품 밖 `#/studio[/<세션 id>]`)
- `app.js` 라우팅이 작품 밖 사이드바(`outSidebar`) 옆에 `viewStudio` 를 그린다(불러오기 `stuLoad`, 본문 폭 1180px)
- 작품 밖 도구 ✍️ · 작품 사이드바 ⋯ 메뉴에서 들어온다
- 처음 화면 `stuHome`: 세션 카드(`.grid-auto`)와 머리 '+ 새 연습'(빈 카드로 세션을 바로 만든다)
- 세션 화면 `stuSession`: 왼쪽 열 상황 카드 `stuCardForm`, 오른쪽 넓은 열 본보기 문단 `stuModelCard`(있을 때만, 지표 `model_measure`, 출발 글로 넣기 `stuModelSource` · 복사) · 직접 쓰기 `stuWriteCard` 와 시도 카드 `stuTryCard`(고른 것 먼저, 그다음 최근 것)
- 카드 칸은 `DRAFT_ROOTS.stuForm` 으로 묶고, 칸을 벗어날 때(change) 조용히 저장한다(`stuSaveCard`). AI 안 쓰기 · 시도 저장 전에도 먼저 저장한다
- 연습 고르기는 체크 칸 `data-stu-drill`(목록은 서버 `GET /api/studio` 의 `drills`)
- 구조 칸 `stuStructureForm`: 박자 줄(`data-stu-beat`, 더하기 `stuBeatAdd` · 옮기기 `stuBeatMove` · 빼기 `stuBeatDrop`, 목록은 `beats`) · 가릴 것 · 감각 전환 · 본보기 보이기
- 본보기 카드의 뜯어보기 `stuAnatomy` · 결과 `stuAnatomyHtml` · 카드에 적용 `stuAnatomyApply`, 상황 바꿔 보기 카드 `stuVariantCard`(`stuVariants`, 새 연습 `stuFromVariant`), 시도의 독자 질문 `stuReader` · `stuReaderHtml`
- AI 호출 전 카드 저장 `stuCall`. CSS 는 JS 에서 주입(`STU_CSS`)
- AI 안 쓰기 · 뜯어보기 · 상황 바꿔 보기 · 독자 질문은 화면을 막지 않는 작업이다(`stuStartJob`, 고친 카드를 먼저 저장). 버튼은 `stuBtn`(`jobBtn(…, STU_JOBS, 세션 id)`)으로 '만드는 중'을 그린다
- 작업이 끝나면 그 세션을 보고 있을 때 다시 받는다(`stuJobDone`). 고치던 카드(`S.stuDirty`)는 서버 것으로 바꾸지 않고 남긴다
- 시도 카드: 지표 칩(`stuChecks`: 지켰나 ✓ · 못 지킴 ✕ · 읽고 판단 ?), 글자 · 문장 · 대사 비율, 걸린 곳 «인용», 문체 버릇 횟수
- 고쳐 쓰기(`stuRewrite`)는 그 시도 글을 직접 쓰기 칸에 옮기고 `base` 로 남긴다. AI 안은 고치지 않고 작가 글만 고친다(`stuEditOpen`)
- 시도 고치기 칸의 글은 `S.stuEditText`(`data-local`)에 두어 다른 버튼으로 다시 그려도 남는다. 다른 시도를 열거나 그만둘 때 고친 것이 있으면 묻는다(`tests/test_studio_js.py`)
- 직접 쓰기 칸과 고친 시도 글은 페이지를 떠날 때 묻는다(`app.js` `onKeptDraft`)
- 오른쪽 열 맨 위 보기 줄 `stuViewBar`: 줄 간격(`STU_LH`) · 문단 간격(`STU_GAP`)을 고르면 본보기 · 시도 글과 쓰기 칸에 바로 적용한다
- 보기 값은 이 브라우저에만 둔다(localStorage `canon.studioView`, 고르기 `stuViewPick`, `tests/test_studio_js.py`)
- 본보기 · 시도 글은 줄 바꿈마다 `<p>` 로 나눠 그린다(`stuParas`). 문단 간격은 CSS 변수 `--stu-gap` 이 정한다
- 머리 주 버튼은 'AI 안 n개 쓰기'(n 은 카드 아래 고르기 `S.stuN`, 1~4). 시도가 꽉 차면 막는다
- 공용 클래스(`.cols` · `.card` · `.chip.ok` · `.chip.bad` · `.check-row` · `.rw-text` · `.rs-table`)에 구조 · 상황 목록 칸만 `STU_CSS` 로 더한다

### `canon/stattrial.py`

- 상태창 넣기 시험(연구 화면 '상태창 시험' 쪽, 명령줄 `stattrial`)
- 조건 `CONDITIONS`(none · json · lines, `stat_window.prompt` 만 바꾼 사본 `variant`)
- 시험할 화(`candidates`, 추천 `default_pick`)
- 그 화를 쓰기 직전 사본(`before`, `pipeline.revert`)
- 컨텍스트 놓침 실측 `scripts/context_measure.py` 도 이 사본으로 화마다 쓰기 프롬프트를 다시 만든다(LLM 없음, `docs/context/specs/01-measure.md`, 시험 `tests/test_context_measure.py`)
- `scripts/context_measure.py` 의 열린 복선 블록 흉내는 장편 화마다 `prompts.serial_foreshadow_block` 으로 한 줄 꼴과 예전 JSON 꼴을 찍어 줄어든 글자를 센다(LLM 없음, `docs/context/specs/10-foreshadow-trim.md` 의 확인 (가))
- 복선 흉내는 한 줄 블록이 실제 쓰기 프롬프트에 없으면 `align` 에 `foreshadow-block` 을 적는다
- 복선 흉내의 옵션은 `--fs-works` · `--fs-mode` · `--fs-only` · `--fs-table` 이고 결과 JSON 에 `foreshadow` 키를 더한다
- 복선 흉내의 판정은 합친 값과 독립 작품 셋(`FS_WORKS`)의 블록 글자가 모두 `FS_CHARS`(40%) 이상 줄어야 통과다
- 원래 반영의 바뀐 항목(`changes`)
- LLM 없는 채점(`score`: 바뀌지 않을 값 · 바뀔 값 오류, 없던 항목, 플롯에 없던 상태창)
- 비용 추정(`estimate`, 실제 요청 글자 수와 `usage` 가격표)
- 비용 추정의 토큰은 본문 단계 백엔드 · 모델의 `usage.token_rate` 로 센다
- 실행(`run`: 실험 기록 kind statwin, 조건마다 첫 안을 블라인드 비교본 kind statwin 으로)
- 도중에 실패하거나 멈추면 그때까지 쓴 본문을 기록에 남기고 `stopped` 에 까닭을 적는다(blocktrial 과 같다)
- 작품은 저장하지 않는다
- 화면은 `static/stattrial.js`
- 화면은 고를 때마다 비용을 추정해(`stEst`, AI 없음) 머리 주 버튼 글에 적는다(`stHeadBtn`)
- 지난 시험은 틀린 비율 막대(`stBars`, 한 계열)와 방식별 표
- 웹 작업 `stattrial`

### `canon/studio.py`

- 문단 연습장(작품 밖 `<CANON_HOME>/.studio/<id>.json`, `CANON_STUDIO` 로 경로 변경, 화면은 `static/studio.js`, 웹 `/api/studio/...`)
- 한 문단짜리 장면을 상황 카드(`SceneCard`: 인물 · 시점 · 장소 · 때 · 무슨 일 · 남길 것 · 목표 글자 수 · 연습 · 더 지킬 것 · 출발 글 · 문체 · 본보기 문단 `model` · 출처 `ref`)로 쓴다
- 본보기 문단은 역설계 실험에서 가져온다(`revlab.paragraph_card`). 프롬프트에는 넣지 않고, `view` 가 시도와 같은 지표로 잰 `model_measure` 를 붙인다
- 세션 `StudioSession` 은 카드 하나와 시도 `StudioTry`(AI 안 · 작가 글, 고쳐 쓴 시도 번호 `base`, 고름 `star`)
- 저장 `load` · `save`(임시 파일 뒤 바꿔 넣기) · `sessions` · `create` · `update` · `delete` · `duplicate`(카드만 복사)
- `save` 는 `store.write_atomic` 으로 쓴다. 임시 파일 이름에 pid 와 스레드 id 가 들어가 두 스레드가 함께 저장해도 섞이지 않는다
- 카드 정리 `clean_card`: 빈 인물 · 모르는 연습을 빼고 길이를 `LENGTH` 로 맞추고, 문체 라이브러리에 없는 문체는 막는다
- 시도 `add_ai` · `add_author`(고친 곳이 없으면 막음) · `edit`(작가 글만 고침, 고르기는 모두) · `remove`(그 시도를 고쳐 쓴 글은 `base` 0)
- 세션마다 시도 `MAX_TRIES` 개까지. 저절로 지우지 않고 막는다(`room`)
- 연습 종류 `DRILLS`(`Drill`: 이름 · 프롬프트 지시 · 지표 확인). 확인이 없는 연습(소리 · 냄새 · 촉감, 자리 · 자세)은 작가가 읽고 판단한다
- 문단 지표 `measure`: 비율 대신 개수로 센다. 길이 · 연습 확인, 걸린 곳(`metrics.pattern_spans`), 문체 버릇 횟수(`metrics.marker_count`)
- 화 단위 지표(어휘 다양도 · 문체 거리 · 쇠맛 화당 상한)는 문단에 맞지 않아 쓰지 않는다. 문장 길이 변화폭은 4문장부터 잰다
- 감정 이름 확인은 대사 밖 서술에서만 `EMOTION_WORDS` 와 쇠맛 패턴 '감정 이름 서술'을 본다
- 프롬프트 재료 `world`: 고른 문체만 채운 저장하지 않는 `Project`(프롬프트는 `prompts.paragraph_system` · `paragraph_prompt`)
- AI 호출은 `pipeline.draft_paragraph`(write 단계, 빈 안 · 겹치는 안 · 출발 글과 같은 안을 빼고 굵은 글씨를 뗌)
- 구조: 카드의 문장 차례 `beats`(박자 `BEATS`, 화면 목록 `beats()`) · 가릴 것 `withhold` · 감각 전환 `sense` · 본보기 보이기 `show_model`, 프롬프트 블록 `prompts.structure_block`
- 뜯어보기 `pipeline.anatomize_paragraph`(plan) → `clean_anatomy`(본보기에 없는 인용은 버림) · `set_anatomy`(지문 `anatomy_of`, 화면 `anatomy_stale`) · `apply_anatomy`
- 상황 바꿔 보기 `pipeline.vary_scene`(plan, `can_vary`, `clean_variants`, 수 `VARIANTS`) → 고른 상황으로 새 세션 `from_variant`
- 독자 질문 `pipeline.reader_check`(check) → `set_reader`(본문에 없는 인용은 비움), 시도 글을 고치면 지움
- 지표의 본보기 베끼기 `copied`(`metrics.copied_sentences`), 연습 '가정 문장 하나'(`IMAGINE_RE`, 대사 밖)
- 웹 `POST /api/studio/{id}/anatomy` · `anatomy/apply` · `variants` · `variants/{i}` · `tries/{no}/reader`
- 웹은 작업 목록을 거치지 않고 바로 돌려준다(`POST /api/studio/{id}/draft`, 사용량 작업 이름 `studio`). 쓰는 동안 바뀐 시도를 덮지 않게 저장 직전에 다시 읽는다
- 작품에는 넣지 않는다. 본문으로 보내기 · 문체 학습으로 보내기는 아직 없다
- 가짜 응답 `mock_studio.py`
- 시험 `tests/test_studio.py`
- LLM 호출 없음

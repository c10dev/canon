# 모듈 지도: LLM 백엔드 · 사용량 · 가짜 응답

이 파일의 줄은 [AGENTS.md](../../AGENTS.md) 의 '문서 줄 규칙'을 따른다.

### `canon/claude.py`

- Claude 백엔드
- `ClaudeAPILLM` 은 Anthropic 키가 없으면 `MissingKey` 를 낸다(웹은 설정 안내 code `no_key`)
- 구독 로그인(`claude`, 설치된 Claude Code 를 `claude -p` 로 부름, 로그인 상태 `status`)과 API 키(`claude-api`, Anthropic SDK)
- Canon 은 Claude 계정 로그인을 직접 받거나 토큰을 저장하지 않는다(Anthropic 정책)
- Canon 전용 로그인: `settings.claude_config_dir`(설정 `claude_separate` 면 설정 파일 옆 `claude-code` 폴더, `CANON_CLAUDE_CONFIG_DIR` 가 우선)를 `child_env` 가 `CLAUDE_CONFIG_DIR` 로 넘긴다
- `start_login` 은 그 폴더로 `claude auth login --claudeai` 를 띄우기만 한다(입출력을 잇지 않음, 10분 뒤 끝냄). 웹 `POST /api/claude/login` 은 Canon 을 실행하는 컴퓨터에서 온 요청만 받는다
- `logout` 은 전용 폴더를 쓸 때만 `claude auth logout` 을 부른다(평소 Claude Code 로그인은 건드리지 않음)
- 단계별 추론 강도(`settings.stage_effort`)를 구독은 `--effort`(모르는 버전이면 뺌), API 는 `output_config.effort` 로 넘긴다. 비우면 모델 기본값. 사용량 기록 줄의 `effort`
- 프롬프트 캐시는 두 백엔드가 같은 `shared_cut`(같은 모델 · 시스템 · 스키마의 직전 요청과 겹치는 앞부분, 단락 경계, 2,000자 이상)으로 자른다
- API 는 그 끝에 `cache_control` 을 단다(`cache_blocks`)
- 구독은 캐시 표시를 고를 수 없어 그 앞부분을 시스템 프롬프트 뒤로 옮겨 `--system-prompt-file` 로 넘긴다(`ClaudeCodeLLM._split`)
- Claude Code 는 시스템 프롬프트 끝에 캐시 표시를 단다
- 형식 고치기 재시도는 첫 시도와 같은 자리에서 자른다(`last_cut`). 처음 요청 뒤에 덧붙이므로 첫 시도의 캐시를 읽는다
- `--system-prompt-file` 은 2.1.x `--help` 에 `--system-prompt[-file]` 로만 나온다. 모르는 버전이면 예전처럼 사용자 메시지에 둔다
- 같은 시스템 프롬프트를 동시에 보내면 먼저 보낸 호출이 끝나거나 보낸 지 `CACHE_PREFILL_SECONDS`(30초)가 지날 때까지 뒤 호출이 기다린다(`_claim` · `_release`). 고침안 받기(`FIX_WORKERS` 3)가 모두 캐시를 새로 쓰지 않게 하려는 것
- 모델까지 간 호출은 보낸 시각부터 `CACHE_WARM_SECONDS`(300초) 동안 캐시에 있다고 보고 기다리지 않는다
- 기다린 시간은 사용량 기록의 `seconds` 에 넣지 않는다
- 사용량 기록의 글자 수 · 블록 크기는 옮기기 전 원래 프롬프트 기준이다
- 두 백엔드도 `llm.wait_cap` · `llm.out_cap` 을 따른다(`llm.caps` 로 읽음)
- 구독은 제한 시간을 `min(CANON_CLAUDE_TIMEOUT, wait_cap)` 으로 둔다. 넘기면 다시 부르지 않고 `ClaudeCodeError`
- API 는 `max_tokens` 를 `min(MAX_TOKENS, out_cap)` 으로, SDK 요청 옵션 `timeout` 을 `wait_cap` 으로 보낸다
- 두 백엔드는 호출마다(형식 고치기 재시도도) 보내기 전에 `cancel.check()` 를 부른다
- 구독은 `_run` 이 `Popen` 으로 띄우고 `STOP_POLL`(0.25초)마다 멈추기 신호를 보다가 서면 하위 프로세스를 끝내고 `cancel.Cancelled`
- API 는 스트림 조각마다 `cancel.check()` 를 불러 멈추면 스트림을 닫는다
- 화면은 `static/claude.js`

### `canon/judge.py`

- 판단기
- 글을 쓰지 않고 선택지 확률만 낸다(Jev 의 System One 방식)
- `LocalJudge`(OpenAI 호환 서버 logprobs, 출력 1토큰)
- `MockJudge`
- `make_judge` / `get_judge`(`CANON_JUDGE`)
- 환경 변수 값은 `env_choice` 로 읽는다. 연구 화면 검수 시험도 판단기를 고르지 않았거나 모델 · 주소가 비면 이 값을 쓴다(`research.judge_backend`)
- 호출마다 `usage.record`(단계 `judge`)
- 두 걸음 검수 `pipeline.check_two_step`(진술 `prompts.claims_prompt` → 근거 `claim_evidence` → 의심 `verdict_prompt`)가 쓴다
- 두 걸음 검수는 아직 연구 화면에서만 쓴다

### `canon/llm.py`

- LLM 프로바이더 인터페이스(`json`, `text`)와 Gemini(API 키 또는 Vertex AI 서비스 계정 `_vertex_client`)
- 키 · 권한 오류(401, 403, 400 API_KEY_INVALID, `is_bad_key`)는 다시 부르지 않고 `BadKey`(`KEY_HINT`, Vertex 는 `VERTEX_HINT`)를 낸다. 웹은 code `bad_key` 로 답한다
- 요청 한도로 기다리거나 응답 지연으로 다시 부를 때 `cancel.say` 로 작업 진행 줄에 알리고, 그 호출이 끝나면 비운다
- 로컬(OpenAI 호환) 구현
- 단계별 선택(`get_llm(stage)`)
- 단계 이름은 `settings.STAGES` 다
- Gemini 429 요청 한도는 `GeminiLLM._call` 이 `RATE_WAITS`(30 · 60 · 120초)만큼 기다려 다시 부른다(기다리기 전 `cancel.check`, 실패한 시도는 하나씩 사용량에 실패로)
- 429 오류에 서버가 `RetryInfo.retryDelay` 를 주면 `rate_pause` 가 그 값(올림, `RATE_WAITS` 의 가장 긴 값까지)을 기다린다(`retry_delay`)
- 끝내 막히면 해요체 안내 `RateLimited`(`RATE_HINT`)
- 500 · 502 · 503(`is_transient`: 과부하 UNAVAILABLE · INTERNAL)은 `SERVER_WAITS`(5 · 15 · 45초)만큼 기다려 다시 부른다
- 끝내 풀리지 않으면 해요체 안내 `ServerBusy`(`SERVER_HINT`)
- 429 · 서버 오류 · 시간 초과는 따로 센다
- 응답 시간 한도는 요청마다 SDK `HttpOptions(timeout)` 로 준다(`GEMINI_TIMEOUT` 600초, `CANON_GEMINI_TIMEOUT` 초로 바꿈, `gemini_timeout`)
- 시간 한도를 넘기면(`is_timeout`) `cancel.check` 뒤 한 번 더 부른다
- 또 넘기면 해요체 안내 `TimedOut`(`TIMEOUT_HINT`)
- 넘긴 시도도 사용량에 실패로
- 배치는 429 · 서버 오류 · 시간 한도 경로 밖
- 모든 요청 맨 끝(사용자 메시지)에 `POLICY_NOTE` 한 줄(`with_note`, Gemini · 배치 · 로컬 · `claude.py` 두 백엔드가 보내기 직전에). 수위 지시는 프롬프트에 두지 않는다
- 응답 읽기 `_validate`: 통째로 읽히지 않으면 글 속 최상위 JSON 객체(`_json_objects`)를 뒤에서부터 읽는다(생각 글이 앞에 새는 응답, Gemini · 배치 · Claude 공통)
- 형식 고치기 `repair_prompt`: 응답에 JSON 객체가 없으면 처음 요청을 그대로 다시 보낸다
- Gemini 응답이 끝난 이유는 `last_finish`(두 번째도 실패하고 `MAX_TOKENS` 면 `SchemaMismatch` 글에 길이 한도를 적는다)
- Gemini 추론 강도(`GeminiLLM.effort`, `settings.GEMINI_EFFORTS`)는 `thinking_config.thinking_level` 로 넘긴다(일반 호출과 배치)
- 강도를 비우면 `thinking_config` 를 보내지 않는다(모델 기본값)
- Gemini 명시 캐시(`GeminiLLM._cached`)는 플롯 대화 단계(`stage == "chat"`)에서 `settings.gemini_cache` 가 켜져 있을 때만 쓴다
- 같은 종류 직전 요청과 겹치는 앞부분은 `claude.shared_cut` 으로 찾는다(열쇠 `("gemini", vertex, 모델, 시스템)`, 단락 경계)
- 겹치는 앞부분이 `GEMINI_CACHE_MIN_CHARS`(16,000자) 이상이고 덮는 캐시가 없으면 `client.caches.create`(시스템 프롬프트 + 앞부분, `GEMINI_CACHE_TTL` 600초)로 만든다
- 만든 캐시는 `(vertex, 모델, 시스템 해시)` 별로 앞부분 길이 · 해시 · 이름 · 만료 시각으로 기억한다(`_GEM_CACHES`, `_cache_find`)
- 살아 있는 캐시가 겹치는 앞부분의 절반 이상을 덮으면 그것을 다시 쓴다. 만료 `GEMINI_CACHE_MARGIN`(60초) 전부터는 쓰지 않는다
- 캐시를 쓰는 요청은 `GenerateContentConfig(cached_content=이름)` 과 나머지 글만 보낸다. 시스템 프롬프트는 넣지 않는다(API 가 거절한다)
- 캐시를 만들거나 쓰다 난 오류는 모두 일반 호출로 넘어간다(`_cache_failed`). 넘어간 호출 하나만 사용량에 기록한다
- 429 · 시간 초과 · 서버 오류가 아닌 캐시 오류는 그 모델의 캐시를 `GEMINI_CACHE_BACKOFF`(1시간) 동안 끈다. 404(먼저 만료된 캐시)는 그 캐시만 잊는다
- 캐시를 쓰는 요청이 429 · 시간 초과 · 서버 오류면 일반 호출로 넘어가지 않고 `_call` 의 다시 부르기에 맡긴다
- Vertex AI 도 같은 경로다. SDK 가 Vertex 캐시를 지원하지만 실제 Vertex(`global` 위치)에서 되는지는 재지 않았다. 안 되면 첫 오류 뒤 1시간씩 꺼진다
- 캐시 저장 요금은 사용량 비용 추정에 넣지 않는다. 기본값 근거(저장 요금 가정)는 `llm.py` 의 `GEMINI_CACHE_TTL` 위 주석
- 시험은 `tests/test_gemini_cache.py`(가짜 google-genai 클라이언트)
- 생각 토큰도 출력 한도(`out_cap`)에 든다
- 설정 화면의 Gemini 연결 방식은 `static/vertex.js`
- 환경 변수
  - `ANTHROPIC_API_KEY`: Claude API 키(`claude-api` 만 키를 씀)
  - `CANON_ALLOWED_HOSTS`: 웹 서버가 더 받을 Host 이름(쉼표로 나눔, `web._host_allowed`). IP 주소 · localhost · `*.ts.net` · 이 컴퓨터 이름은 늘 받는다
  - `CANON_BATCH_POLL`: 배치 결과를 묻는 간격 초(기본 30, `llm.BatchLLM`)
  - `CANON_CLAUDE_BIN` · `CANON_CLAUDE_MODEL` · `CANON_CLAUDE_TIMEOUT`: Claude
  - `CANON_CLAUDE_CONFIG_DIR`: Canon 전용 Claude Code 설정 폴더(구독 계정을 따로 로그인)
  - `CANON_CONFIG`: 설정 파일 위치(기본 `~/.canon/config.json`, `settings.path`)
  - `CANON_EFFORT_<단계>`: 단계별 추론 강도(low · medium · high · xhigh · max, `settings.stage_effort`). Claude · Gemini 만 쓴다
  - `CANON_GEMINI_AUTH`: Gemini 연결 방식(key | vertex)
  - `CANON_GEMINI_CACHE`: 0 · off 면 Gemini 명시 캐시를 끈다(기본 agent: 플롯 대화 단계만, `settings.gemini_cache`)
  - `CANON_GEMINI_TIMEOUT`: Gemini 응답을 기다리는 초(기본 600)
  - `CANON_HOME`: 프로젝트 저장 위치(기본 `projects/`)
  - `CANON_JUDGE`: 판단기(local | mock, `judge.env_choice`)
  - `CANON_JUDGE_MODEL` · `CANON_JUDGE_URL`: 로컬 판단기 서버(비면 로컬 서버 설정)
  - `CANON_JUDGE_WORKERS`: 판단기 동시 요청 수(기본 16, `judge.LocalJudge`)
  - `CANON_LLM`: gemini | local | claude | claude-api | mock
  - `CANON_LLM_<단계>`: 단계별 백엔드(`CANON_LLM_PLAN` · `_WRITE` · `_CHECK` · `_STATE` · `_NAME` · `_REVISE` · `_ILLUSTRATION` · `_PLAY` · `_CHAT`, 이름은 `settings.stage_env`)
  - `CANON_LOCAL_KEY` · `CANON_LOCAL_MODEL` · `CANON_LOCAL_URL`: 로컬 서버
  - `CANON_LOCAL_TIMEOUT`: 로컬 서버 응답을 기다리는 초(기본 900)
  - `CANON_MOCK_BATCH_POLLS`: 가짜 배치가 끝나기 전에 물어볼 횟수(기본 0)
  - `CANON_MOCK_DELAY`: 가짜 응답이 기다리는 초(기본 0, 화면 진행 표시 확인용)
  - `CANON_MODEL`: Gemini 모델(기본 `gemini-4-argon`)
  - `CANON_MODEL_<단계>`: 단계별 모델(`CANON_MODEL_PLAN` · `_WRITE` · `_CHECK` · `_STATE` · `_NAME` · `_REVISE` · `_ILLUSTRATION` · `_PLAY` · `_CHAT`)
  - `CANON_NO_BROWSER`: 1 이면 `serve` 가 브라우저를 열지 않는다(`updater` 가 다시 띄울 때 쓴다)
  - `CANON_NO_BUNDLE`: 1 이면 웹 화면 스크립트를 묶지 않고 파일마다 보낸다(오류 위치 보기, `web._bundle`)
  - `CANON_PORT`: `scripts/canon-mac.command` 가 띄우는 웹 포트(기본 8000)
  - `CANON_REFS`: 레퍼런스 원고 폴더(기본 `<CANON_HOME>/.refs`, `refs.py`)
  - `CANON_STUDIO`: 문단 연습장 세션 폴더(기본 `<CANON_HOME>/.studio`, `studio.py`)
  - `CANON_STYLES`: 문체 라이브러리 폴더(기본 `<CANON_HOME>/.styles`, `library.py`)
  - `CANON_USAGE`: 사용량 기록 파일(기본 `projects/.usage/usage.jsonl`)
  - `CANON_VERTEX_CREDENTIALS` · `GOOGLE_CLOUD_LOCATION` · `GOOGLE_CLOUD_PROJECT`: Vertex AI 서비스 계정
  - `GEMINI_API_KEY`: Gemini API 키

### `canon/mock.py`

- 테스트용 가짜 LLM
- `MockLLM.json` 은 스키마로 `RESPONDERS` 만 찾는다. `mock.py` 의 응답도 `@responds` 함수(`_r_<스키마>`)이고 `json` 안에 스키마 분기를 두지 않는다(`tests/test_mock_registry.py`)
- 가짜 문체 프로필은 시험 원문에 있는 표지 · 장치와 걸러져야 할 표지 · 장치를 함께 낸다 (`count_markers` 와 문체 넣은 쓰기 경로 시험)
- 새 기능의 가짜 응답은 `mock_<기능>.py` 에 `@responds(스키마)` 로 두고(`RESPONDERS`) `mock.py` 맨 끝에서 불러온다
  - `mock_birth.py` 출생 배경
  - `mock_board.py` 스토리보드
  - `mock_cue.py` 큐 시트와 큐 본문
  - `mock_knows.py` 아는 정보 접기
  - `mock_play.py` 장면
  - `mock_revlab.py` 역설계
  - `mock_stage.py` 장면 연출
  - `mock_studio.py` 문단 연습장

### `canon/usage.py`

- AI 사용량과 비용
- LLM 구현이 실제 호출마다 `record` 로 `projects/.usage/usage.jsonl` 에 남긴다
- `read` 는 읽은 끝 위치를 기억하고 다음에는 늘어난 줄만 읽는다(`_read_cache`)
- 작품 · 화 · 작업은 `scope(...)` 로 붙인다(웹 미들웨어, `jobs.start`, 자동 집필, CLI)
- `collect()` 는 안에서 `record` 한 줄을 목록에 모은다(`_acc`). `copy_context` 로 넘긴 스레드의 호출도 같은 목록에 모인다
- `totals(rows)` 는 모은 줄의 입력 · 출력(생각 포함) 토큰과 `row_cost` 비용 합이다. 가격을 모르는 줄이 있으면 비용은 None
- 가격표(`DEFAULT_PRICES` + 설정의 `prices`, 날짜별 `since`)로 볼 때 비용을 계산한다
- 자동 집필 추정도 같은 가격표를 쓴다
- 화면은 `static/usage.js`
- `usage.js` 는 손가락 기기에서 차트 안내를 '막대를 누르면 날짜별 값을 봐요' 로 보인다(←/→ 키 안내는 aria-label 에만)
- 화면 차례: 기간 · 작품 거르기 → 비용 타일 → 날짜별 막대 → '어디에 썼나' 막대 목록 → 호출 목록 → 접힌 가격표
- 날짜별 막대는 비용 · 호출 수 중 하나(축 하나, 눈금 `usageTicks`)
- '어디에 썼나'는 단계 · 모델 · 작품(작품 안에서는 화) · 어디서 중 하나(`usageBreakdown`)
- 가격표 카드는 읽는 모양이 기본이고 '고치기'로 편다(`S.priceOpen`)
- 칸 폭 규칙은 `@container usage`

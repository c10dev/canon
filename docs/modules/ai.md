# 모듈 지도: LLM 백엔드 · 사용량 · 가짜 응답

이 파일의 줄은 [AGENTS.md](../../AGENTS.md) 의 '문서 줄 규칙'을 따른다.

### `canon/claude.py`

- Claude 백엔드
- 구독 로그인(`claude`, 설치된 Claude Code 를 `claude -p` 로 부름, 로그인 상태 `status`)과 API 키(`claude-api`, Anthropic SDK)
- Canon 은 Claude 계정 로그인을 직접 받거나 토큰을 저장하지 않는다(Anthropic 정책)
- 화면은 `static/claude.js`

### `canon/judge.py`

- 판단기
- 글을 쓰지 않고 선택지 확률만 낸다(Jev 의 System One 방식)
- `LocalJudge`(OpenAI 호환 서버 logprobs, 출력 1토큰)
- `MockJudge`
- `make_judge` / `get_judge`(`CANON_JUDGE`)
- 호출마다 `usage.record`(단계 `judge`)
- 두 걸음 검수 `pipeline.check_two_step`(진술 `prompts.claims_prompt` → 근거 `claim_evidence` → 의심 `verdict_prompt`)가 쓴다
- 두 걸음 검수는 아직 연구 화면에서만 쓴다

### `canon/llm.py`

- LLM 프로바이더 인터페이스(`json`, `text`)와 Gemini(API 키 또는 Vertex AI 서비스 계정 `_vertex_client`)
- 로컬(OpenAI 호환) 구현
- 단계별 선택(`get_llm(stage)`)
- 단계 이름은 `settings.STAGES` 다
- Gemini 429 요청 한도는 `GeminiLLM._call` 이 `RATE_WAITS`(30 · 60 · 120초)만큼 기다려 다시 부른다(기다리기 전 `cancel.check`, 실패한 시도는 하나씩 사용량에 실패로)
- 끝내 막히면 해요체 안내 `RateLimited`(`RATE_HINT`)
- 응답 시간 한도는 요청마다 SDK `HttpOptions(timeout)` 로 준다(`GEMINI_TIMEOUT` 600초, `CANON_GEMINI_TIMEOUT` 초로 바꿈, `gemini_timeout`)
- 시간 한도를 넘기면(`is_timeout`) `cancel.check` 뒤 한 번 더 부른다
- 또 넘기면 해요체 안내 `TimedOut`(`TIMEOUT_HINT`)
- 넘긴 시도도 사용량에 실패로
- 배치는 429 · 시간 한도 경로 밖
- 응답 읽기 `_validate`: 통째로 읽히지 않으면 글 속 최상위 JSON 객체(`_json_objects`)를 뒤에서부터 읽는다(생각 글이 앞에 새는 응답, Gemini · 배치 · Claude 공통)
- 형식 고치기 `repair_prompt`: 응답에 JSON 객체가 없으면 처음 요청을 그대로 다시 보낸다
- Gemini 응답이 끝난 이유는 `last_finish`(두 번째도 실패하고 `MAX_TOKENS` 면 `SchemaMismatch` 글에 길이 한도를 적는다)
- 설정 화면의 Gemini 연결 방식은 `static/vertex.js`
- 환경 변수
  - `ANTHROPIC_API_KEY`: Claude API 키(`claude-api` 만 키를 씀)
  - `CANON_CLAUDE_BIN` · `CANON_CLAUDE_MODEL` · `CANON_CLAUDE_TIMEOUT`: Claude
  - `CANON_GEMINI_AUTH`: Gemini 연결 방식(key | vertex)
  - `CANON_GEMINI_TIMEOUT`: Gemini 응답을 기다리는 초(기본 600)
  - `CANON_HOME`: 프로젝트 저장 위치(기본 `projects/`)
  - `CANON_LLM`: gemini | local | claude | claude-api | mock
  - `CANON_LLM_<단계>`: 단계별 백엔드(`CANON_LLM_PLAN` · `_WRITE` · `_CHECK` · `_STATE` · `_NAME` · `_REVISE` · `_ILLUSTRATION` · `_PLAY`, 이름은 `settings.stage_env`)
  - `CANON_LOCAL_KEY` · `CANON_LOCAL_MODEL` · `CANON_LOCAL_URL`: 로컬 서버
  - `CANON_MODEL`: Gemini 모델(기본 `gemini-4-argon`)
  - `CANON_MODEL_<단계>`: 단계별 모델(`CANON_MODEL_PLAN` · `_WRITE` · `_CHECK` · `_STATE` · `_NAME` · `_REVISE` · `_ILLUSTRATION` · `_PLAY`)
  - `CANON_USAGE`: 사용량 기록 파일(기본 `projects/.usage/usage.jsonl`)
  - `CANON_VERTEX_CREDENTIALS` · `GOOGLE_CLOUD_LOCATION` · `GOOGLE_CLOUD_PROJECT`: Vertex AI 서비스 계정
  - `GEMINI_API_KEY`: Gemini API 키

### `canon/mock.py`

- 테스트용 가짜 LLM
- 가짜 문체 프로필은 시험 원문에 있는 표지 · 장치와 걸러져야 할 표지 · 장치를 함께 낸다 (`count_markers` 와 문체 넣은 쓰기 경로 시험)
- 새 기능의 가짜 응답은 `mock_<기능>.py` 에 `@responds(스키마)` 로 두고(`RESPONDERS`) `mock.py` 맨 끝에서 불러온다
  - `mock_birth.py` 출생 배경
  - `mock_board.py` 스토리보드
  - `mock_cue.py` 큐 시트와 큐 본문
  - `mock_knows.py` 아는 정보 접기
  - `mock_play.py` 장면
  - `mock_revlab.py` 역설계
  - `mock_stage.py` 장면 연출

### `canon/usage.py`

- AI 사용량과 비용
- LLM 구현이 실제 호출마다 `record` 로 `projects/.usage/usage.jsonl` 에 남긴다
- 작품 · 화 · 작업은 `scope(...)` 로 붙인다(웹 미들웨어, `jobs.start`, 자동 집필, CLI)
- 가격표(`DEFAULT_PRICES` + 설정의 `prices`, 날짜별 `since`)로 볼 때 비용을 계산한다
- 자동 집필 추정도 같은 가격표를 쓴다
- 화면은 `static/usage.js`
- 화면 차례: 기간 · 작품 거르기 → 비용 타일 → 날짜별 막대 → '어디에 썼나' 막대 목록 → 호출 목록 → 접힌 가격표
- 날짜별 막대는 비용 · 호출 수 중 하나(축 하나, 눈금 `usageTicks`)
- '어디에 썼나'는 단계 · 모델 · 작품(작품 안에서는 화) · 어디서 중 하나(`usageBreakdown`)
- 가격표 카드는 읽는 모양이 기본이고 '고치기'로 편다(`S.priceOpen`)
- 칸 폭 규칙은 `@container usage`

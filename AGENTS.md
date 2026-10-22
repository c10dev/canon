# AGENTS.md

Canon 저장소에서 작업하는 AI 에이전트(Claude Code, Codex, Gemini CLI 등)를 위한 안내서.

## 프로젝트 목표

AI 로 소설을 길게 쓸수록 인물 관계, 심리, 말투, 복선, 문체가 무너진다. Canon 은 이것들을 **구조화된 데이터**로 관리하고, 매 화마다 그 데이터로 프롬프트를 조립해 일관성을 유지한다. 본문을 쓴 뒤 AI 가 상태 변경안을 만들고, **사용자가 승인해야** 데이터에 반영된다.

현재 범위(MVP): 단편 1권, 10~20화. 자세한 설계는 [DESIGN.md](DESIGN.md).

## 구조

| 파일 | 역할 |
|---|---|
| `canon/schema.py` | pydantic 데이터 스키마. 모든 상태는 `Project` 하나(`project.json`)에 저장 |
| `canon/prompts.py` | 프롬프트 템플릿, 화별 컨텍스트 조립(`build_episode_context`), 작업지시서(`episode_brief`, `state_brief`) |
| `canon/pipeline.py` | 단계별 로직: 설정 제안 → 스타일 분석 → 기승전결 → 화별 플롯(대화로 다듬기 `revise_plot`/`apply_revision` 포함) → 본문 → 검수 → 상태 추출/반영 |
| `canon/metrics.py` | 문체 지표(문장 길이, 대사 비율, 과거형 비율, 어휘 다양도, 반복 구, 상투 표현, 쇠맛 패턴과 쉼표·대명사 지표)와 기준 대비 경고. LLM 호출 없음 |
| `canon/genres.py` | 장르 목록(`CATALOG`)과 장르별 안내. 프롬프트의 장르 안내와 수위 블록(`guide`), 설정 화면의 장르별 로그라인 예시(`Genre.logline`) |
| `canon/logline.py` | 로그라인 다섯 칸 합치기(`compose`, 조사 자동), 형식 점검(`checks`), 톤 다이얼 문장(`tone_text`). LLM 호출 없음. `static/app.js` 에 같은 규칙이 있어 함께 고친다 |
| `canon/dynamics.py` | 관계 역학: 사건(`StoryEvent`)으로 방향 관계(`Tie`)를 계산, 긴장도, 스냅샷 재생, 숫자를 말로 바꾸기, 말로 고른 보는 방식(`VIEWS`)으로 시작 관계 만들기. LLM 을 부르지 않는 순수 계산 |
| `canon/static/chat.js` | 화면에 붙는 AI 대화 패널(지금은 기승전결 · 플롯 화면). 변경안을 칸별로 지금 값과 비교해 보여 주고 고른 것만 반영 요청. 화면 본체는 `app.js` |
| `canon/llm.py` | LLM 프로바이더 인터페이스(`json`, `text`)와 Gemini 구현 |
| `canon/mock.py` | 테스트용 가짜 LLM |
| `canon/library.py` | 문체 라이브러리: 작품과 따로 `projects/.styles/<id>.json` 에 문체(원문, 프로필, 기준 지표)를 저장. 작품에 적용하면 복사하고 `Project.style_id` 로 출처만 기억 |
| `canon/store.py` | `projects/<이름>/project.json` 저장, 본문을 `episodes/NN.md` 로 내보내기 |
| `canon/cli.py` | 명령줄 (`python -m canon ...`) |
| `canon/jobs.py` | 웹의 오래 걸리는 AI 작업을 스레드로 돌리는 메모리 작업 목록. 중복 실행 막기, 진행률, 작업이 맡은 화를 저장 덮어쓰기에서 지키기(`owned_episodes`) |
| `canon/updater.py` | 코드 자동 업데이트: `origin/main` fast-forward, 의존성 설치, 프로세스 재시작. `serve` 가 시작 때와 주기적으로 부른다 |

흐름: `new` → `style` → `arc` → `plot` → (사용자 수정) → `confirm` → `write` → `check` → `update` 반복 (`run` 이 자동 반복). `stats` 로 화별 문체 지표 확인.

## 설계 원칙 (깨지 않기)

- **인물은 불변 설정(`Character`)과 가변 상태(`CharacterState`)로 나눈다.** 말투와 성격은 고정, 감정·목표·아는 정보만 화마다 바뀐다.
- **AI 출력은 제안일 뿐이다.** 설정, 플롯, 상태 변경은 사용자 확인(`confirm` 또는 `-y`) 후에만 저장한다.
- **확정된 것은 덮어쓰지 않는다.** confirmed 이상인 화의 플롯은 재생성해도 유지한다. 사용자가 입력한 설정은 AI 제안이 덮지 않는다.
- **순서를 지킨다.** 이전 화가 `finalized` 가 아니면 다음 화를 쓰지 않는다.
- **관계 수치는 AI 가 적지 않는다.** AI 는 사건만 뽑고 `dynamics.py` 가 계산한다. 사용자가 고칠 때는 `수동보정` 사건으로 기록해 재생할 수 있게 한다.
- **컨텍스트는 일정한 크기로.** 이전 본문 전체가 아니라 화별 요약 + 직전 화 끝부분 + 현재 데이터만 넣는다. (검수는 예외로 앞선 본문 전체를 본다.)
- **바뀌지 않는 블록이 앞, 화마다 바뀌는 블록이 뒤.** `static_context()` 를 앞에 둬야 Gemini 암묵적 캐시가 맞는다. 컨텍스트에 블록을 추가할 때 이 순서를 지킨다.
- **API 경로와 작업지시서 경로는 같은 프롬프트를 공유한다.** 프롬프트를 고칠 때는 `prompts.py` 한 곳만 고치고, `brief` 출력도 함께 확인한다. 나중에 MCP 서버도 이 함수들을 재사용한다.
- **LLM 호출은 `LLM` 인터페이스 뒤에만 둔다.** pipeline 이나 cli 에서 SDK 를 직접 부르지 않는다.
- LLM 이 채우는 스키마(`SetupSuggestion`, `StyleProfile`, `ArcPlan`, `PlotBatch`, `PlotRevision`, `StateDelta`, `StoryEvent`, `ConsistencyReport`)에는 dict 타입 필드를 쓰지 않는다 (Gemini 구조화 출력 호환).

## 개발 명령

```bash
pip install -r requirements.txt
python -m unittest                  # mock LLM 으로 전체 흐름 스모크 테스트 (API 키 불필요)
CANON_LLM=mock python -m canon ...  # 수동 확인
```

환경 변수: `GEMINI_API_KEY`, `CANON_LLM`(gemini | mock), `CANON_MODEL`(기본 `gemini-2.5-pro`), `CANON_HOME`(프로젝트 저장 위치, 기본 `projects/`).

스키마나 파이프라인을 바꾸면 `canon/mock.py` 도 맞춰 고치고 `python -m unittest` 가 통과하는지 확인한다. 실제 Gemini 호출은 키가 있을 때만 확인할 수 있으니, 확인하지 못했다면 그렇다고 밝힌다.

## 규칙

- 사용자에게 보이는 문구, 프롬프트, 문서는 **한국어**로 쓴다. 코드 식별자는 영어.
- 기본 LLM 은 **Gemini** 다 (사용자 결정). 다른 프로바이더는 `LLM` 구현을 추가하는 방식으로만 넣는다.
- **API 키, `.env`, `projects/`(사용자 소설 데이터)는 커밋하지 않는다.** `.gitignore` 에 있다.
- 스키마 필드를 바꾸면 기존 `project.json` 이 읽히도록 기본값을 둔다.
- 기능을 바꾸면 README.md 와 DESIGN.md 의 해당 부분도 고친다.

## 로드맵

1. Gemini 실호출 검증과 프롬프트 튜닝, 화별 상태 스냅샷과 되돌리기
2. 구독형 채팅 앱(Claude, Gemini, ChatGPT)용 작업지시서 고도화 (`brief`, `import`, `update --from-json` 은 이미 있음)
3. MCP 서버: 작업지시서 조회, 본문 제출, 상태 변경 제안/반영을 tool 로 노출
4. 웹 UI: 설정 폼, 관계도, 기승전결 플롯 보드, 상태 변경 승인 화면
5. 장편 확장

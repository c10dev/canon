# AGENTS.md

Canon 저장소에서 작업하는 AI 에이전트(Claude Code, Codex, Gemini CLI 등)를 위한 안내서.

## 프로젝트 목표

AI 로 소설을 길게 쓸수록 인물 관계, 심리, 말투, 복선, 문체가 무너진다. Canon 은 이것들을 **구조화된 데이터**로 관리하고, 매 화마다 그 데이터로 프롬프트를 조립해 일관성을 유지한다. 본문을 쓴 뒤 AI 가 상태 변경안을 만들고, **사용자가 승인해야** 데이터에 반영된다.

현재 범위(MVP): 단편 1권 10~20화, 그리고 부 → 아크 → 화로 나눠 쓰는 200~300화 장편 연재(`Meta.form = "serial"`). 자세한 설계는 [DESIGN.md](DESIGN.md).

## 구조

| 파일 | 역할 |
|---|---|
| `canon/schema.py` | pydantic 데이터 스키마. 모든 상태는 `Project` 하나(`project.json`)에 저장 |
| `canon/prompts.py` | 프롬프트 템플릿, 화별 컨텍스트 조립(`build_episode_context`), 작업지시서(`episode_brief`, `state_brief`) |
| `canon/pipeline.py` | 단계별 로직: 설정 제안 → 스타일 분석 → 기승전결 → 화별 플롯(대화로 다듬기 `revise_plot`/`apply_revision` 포함, 플롯이 데려온 새 인물은 후보 `Project.cast_candidates` 로 두고 화 확정 `confirm_plot` 때 등록) → 본문 → 검수 → 상태 추출/반영. 장편은 부 계획(`plan_series`) → 다음 아크(`plan_next_arc`/`apply_arc`) → 아크 · 부 요약(`recap`/`apply_recap`). 단편 → 장편 전환은 이어 쓰기 `propose_conversion`/`apply_conversion`, 재구성 `propose_rebuild`/`apply_rebuild`(옛 상태 변경안 재사용 `carried_delta`, 다듬기 `propose_rework`/`accept_rework`), 되돌리기 `undo_conversion` |
| `canon/metrics.py` | 문체 지표(문장 길이, 대사 비율, 과거형 비율, 어휘 다양도, 반복 구, 상투 표현, 쇠맛 패턴과 쉼표·대명사 지표, 문체 거리, 문체 표지 빈도, 예시 문단 베끼기)와 기준 대비 경고, 1~3화 초반 지표(`measure_opening`). LLM 호출 없음. 문체 거리 기준표는 `style_background.py`(`scripts/make_style_background.py` 로 생성) |
| `canon/genres.py` | 장르 목록(`CATALOG`)과 장르별 안내. 프롬프트의 장르 안내와 수위 블록(`guide`), 설정 화면의 장르별 로그라인 예시(`Genre.logline`) |
| `canon/logline.py` | 로그라인 다섯 칸 합치기(`compose`, 조사 자동), 형식 점검(`checks`), 톤 다이얼 문장(`tone_text`). LLM 호출 없음. `static/app.js` 에 같은 규칙이 있어 함께 고친다 |
| `canon/naming.py` | 이름·지명 무작위 생성(세계관별 스타일, 나이에 맞는 한국 이름)과 출연진 이름 점검. LLM 을 부르지 않는다. 자료와 출처는 `canon/naming_data.py` |
| `canon/dynamics.py` | 관계 역학: 사건(`StoryEvent`)으로 방향 관계(`Tie`)를 계산, 긴장도, 스냅샷 재생, 숫자를 말로 바꾸기, 말로 고른 보는 방식(`VIEWS`)으로 시작 관계 만들기. LLM 을 부르지 않는 순수 계산 |
| `canon/cast.py` | 인물 화면 계산: 화별 관계 프레임(스냅샷, 지워진 화는 사건 로그로 다시 계산), 인물별 등장 화, 화별 타임라인, 명령줄 `cast` 출력. LLM 호출 없음 |
| `canon/static/cast.js` | 인물 · 관계도 화면: 화 슬라이더로 재생하는 SVG 관계도(끌어 옮긴 배치는 localStorage), 인물 상세 · 타임라인, 두 사람 추이 그래프, 등장표. 온기 색 구간은 `dynamics.warmth_word` 경계와 같다 |
| `canon/elements.py` | 인과율: 작가가 언제든 더하는 이야기 요소(`StoryElement`)의 관련 화 지도(`links`), 화별로 넣을 요소(`episode_block`), 시점 설명. LLM 호출 없음. 영향 분석과 반영은 `pipeline.analyze_impact` / `apply_impact` |
| `canon/storylines.py` | 이야기 줄기: 메인에서 갈라졌다 합류하는 서브플롯 · 과거 회상 · 외전 · 인물 이야기(`Storyline`). 화의 줄기는 `EpisodePlot.storyline`(주로 따라가는 줄기, 비면 메인)과 `threads`(끼어드는 장면). 범위(`span`), 프롬프트 블록(`plan_block`, `episode_block`, `state_rule`), 명령줄 노선도(`ascii_map`). LLM 호출 없음. 제안과 반영은 `pipeline.suggest_storyline` / `apply_storyline` |
| `canon/static/lines.js` | 이야기 줄기 화면: SVG 노선도, 줄기 편집, 화 붙이기, AI 제안. 플롯 편집기의 줄기 칸(`lineField`)과 화 카드 표시(`lineBadge`)도 여기 있다. `storylines.span` · `tag` 와 같은 규칙이라 함께 고친다 |
| `canon/static/causal.js` | 인과율 화면: 요소 추가·편집, 관련 화 지도, 영향 분석 변경안 고르기. `elements.basis` 와 같은 모양(`elBasis`)으로 분석이 지났는지 본다 |
| `canon/static/convert.js` | 단편 → 장편 전환 화면: 이어 쓰기(총 화수 · 결말 처리, AI 전환 계획에서 항목 골라 반영)와 재구성(화 지도 고치기, 반영), 되돌리기. 집필 화면의 재구성 안내 · 다듬기 비교(`rebuildNote`)도 여기 있다 |
| `canon/static/chat.js` | 화면에 붙는 AI 대화 패널(기승전결 · 플롯 화면 `plot`, 집필 화면 `text:<화>`). 변경안을 칸별로 지금 값과 비교해 보여 주고 고른 것만 반영 요청. 주제마다 요청 내용과 변경안 그리기를 `CHAT_TOPICS` 에서 바꿔 끼운다. 화면 본체는 `app.js` |
| `canon/static/passage.js` | 본문 부분 수정: 본문에서 고르면 뜨는 도구(직접 수정, AI에게 고치기), 후보를 원문과 단어 단위로 비교, 수정 기록과 되돌리기, 고친 뒤 다시 할 단계 알림. 서버는 `pipeline.edit_text` · `revise_passage` · `apply_passage` · `undo_edit` |
| `canon/static/opening.js` | 초반 1~3화: 집필 화면의 초반 점검 카드(지표 경고, 흡입력 판정, 여는 방식 비교본), 플롯 편집기의 여는 방식별 플롯 안. 서버는 `pipeline.opening_metrics` · `check_hook` · `suggest_openings` · `apply_opening` · `research.run_opening_compare`. 규칙은 `prompts.opening_rules` / `OPENING_APPROACHES`, 지표는 `metrics.measure_opening` |
| `canon/publish.py` | 복사 · 내보내기: 본문을 다른 사이트에 붙여 넣기 좋게 다듬기(줄바꿈 형식 `FORMATS`, 마크다운 흔적 지우기, HTML), 여러 화 잇기(`export`). LLM 호출 없음. 화면은 `static/publish.js` |
| `canon/illust.py` | NovelAI 삽화 프롬프트 조립: AI 원안(`IllustDraft`)에 저장된 인물 외형 태그(`Project.visuals`), 인물 수, 등급, 모델별 품질 태그(`MODELS`)를 붙여 기본 · 인물 · 부정 프롬프트로(`assemble`), 태그 정리(`clean`). LLM 호출 없음. AI 호출은 `pipeline.illustrate` / `suggest_look` (`illustration` 단계) |
| `canon/static/illust.js` | 집필 화면 삽화 프롬프트 카드(칸별 복사, 다시 조립, 외형 고정), 읽기 전용 본문에서 고르는 도구, 설정 화면 인물 카드의 삽화 외형 태그(`visualFields`). 고치는 본문의 도구 버튼은 `passage.js` |
| `canon/static/publish.js` | 집필 화면의 복사 · 내보내기 카드와 복사 버튼. 텍스트와 HTML 을 함께 클립보드에 넣고(보안 연결이 아니면 복사 이벤트로), 막히면 .txt 내려받기 |
| `canon/llm.py` | LLM 프로바이더 인터페이스(`json`, `text`)와 Gemini, 로컬(OpenAI 호환) 구현, 단계별 선택(`get_llm(stage)`) |
| `canon/usage.py` | AI 사용량과 비용: LLM 구현이 실제 호출마다 `record` 로 `projects/.usage/usage.jsonl` 에 남기고, 작품 · 화 · 작업은 `scope(...)` 로 붙인다(웹 미들웨어, `jobs.start`, 자동 집필, CLI). 가격표(`DEFAULT_PRICES` + 설정의 `prices`, 날짜별 `since`)로 볼 때 비용을 계산하고 자동 집필 추정도 같은 표를 쓴다. 화면은 `static/usage.js` |
| `canon/research.py` | 연구 화면(모델 실험) 로직. 서버 점검, 샘플 비교, 단계 시험, 컨텍스트 크기, 블라인드 비교. 작품 데이터와 분리해 `research/log.jsonl` 에 기록 |
| `canon/mock.py` | 테스트용 가짜 LLM |
| `canon/library.py` | 문체 라이브러리: 작품과 따로 `projects/.styles/<id>.json` 에 문체(원문, 프로필, 기준 지표)를 저장. 작품에 적용하면 복사하고 `Project.style_id` · `style_version` 으로 출처만 기억. 저장마다 버전(`StyleVersion`), 칸별 비교(`diff`), 되돌리기(`restore`) |
| `canon/static/marks.js` | 집필 화면 문체 표시: 장치마다 이번 화 배지(`deviceBadges`), 본문에서 장치 글자 · 금지 표현 밑줄(고치는 본문은 textarea 뒤에 깐 칸 `hl-layer`, 읽기 전용은 `<mark>`), 밑줄에서 부분 수정 도구 띄우기. 쓴 화 세기와 쉬는 화 판정은 `metrics.device_hits` · `device_last` · `prompts.device_block` 과 같은 규칙이라 함께 고친다(`tests/test_marks_js.py` 가 node 로 맞춰 본다) |
| `canon/static/mystyle.js` | 나만의 문체: 스타일 프로필의 가끔 쓰는 장치 칸(`deviceFields`), 문체 화면의 '내 수정에서 배우기' 카드(서버 `pipeline.learn_style` / `apply_learning`), 라이브러리 항목의 버전 목록. 장치의 쓴 화 세기는 `metrics.device_last` 와 같은 규칙 |
| `canon/store.py` | `projects/<이름>/project.json` 저장, 본문을 `episodes/NN.md` 로 내보내기 |
| `canon/cli.py` | 명령줄 (`python -m canon ...`) |
| `canon/jobs.py` | 웹의 오래 걸리는 AI 작업을 스레드로 돌리는 메모리 작업 목록. 중복 실행 막기, 진행률, 작업이 맡은 화를 저장 덮어쓰기에서 지키기(`owned_episodes`) |
| `canon/autorun.py` | 자동 집필: 목표 화까지 write → check + state → 정책(`Policy`) 통과 시 반영을 반복. 배치(`llm.BatchLLM`) 켜고 끄기, 비용·시간 추정, `autorun.json` 에 진행 기록, 서버 재시작 후 이어 가기. 화면은 `static/auto.js` |
| `canon/updater.py` | 코드 자동 업데이트: `origin/main` fast-forward, 의존성 설치, 프로세스 재시작. `serve` 가 시작 때와 주기적으로 부른다 |

흐름: `new` → `style` → `arc` → `plot` → (사용자 수정) → `confirm` → `write` → `check` → `update` 반복 (`run` 이 자동 반복). 장편(`new --serial`)은 `arc` 대신 `series` 한 번, 그리고 아크마다 `nextarc` → `plot` → `confirm` → `run` → `recap` 을 반복한다 (`arcs` 로 진행 보기). 단편은 `convert` 로 장편으로 바꿀 수 있다(단편 전체가 아크 1, `--rebuild` 는 단편을 씨앗으로 앞부분을 다시 짜고 다듬기 화는 `rework`, `--undo` 로 되돌리기). 서브플롯 · 과거 회상 · 외전은 `lines` 로 이야기 줄기를 만들고 화에 붙인다. `fix` 로 본문 일부를 AI 후보로 고치고 `edits` 로 수정 기록 보기 · 되돌리기 · 내보내기. `learn` 으로 수정 기록에서 문체 규칙 후보 찾기, `styles versions` · `restore` 로 문체 버전. `export` 로 다른 사이트에 붙여 넣을 본문 내보내기. `illust` 로 NovelAI 삽화 프롬프트, `look` 으로 인물 외형 태그. `pov` 로 화별 서술 시점(남주 → 여주 등) 보기 · 정하기. `cast` 로 인물별 등장 · 지금 관계 · 화별 타임라인 보기. `stats` 로 화별 문체 지표 확인. 1~3화는 `openings` 로 여는 방식 여러 안(플롯 `--plot` · 본문 블라인드 비교), `hook` 으로 흡입력 판정. `usage` 로 AI 사용량과 추정 비용 보기. `compare` 로 같은 화를 두 백엔드로 써서 가려 비교.

## 설계 원칙 (깨지 않기)

- **인물은 불변 설정(`Character`)과 가변 상태(`CharacterState`)로 나눈다.** 말투와 성격은 고정, 감정·목표·아는 정보만 화마다 바뀐다.
- **AI 출력은 제안일 뿐이다.** 설정, 플롯, 상태 변경은 사용자 확인(`confirm` 또는 `-y`) 후에만 저장한다. 자동 집필은 사용자가 정한 승인 정책을 통과한 화만 반영하고 `Episode.auto` 로 표시한다. 정책을 느슨하게 만드는 기본값 변경은 사용자와 정한다.
- **확정된 것은 덮어쓰지 않는다.** confirmed 이상인 화의 플롯은 재생성해도 유지한다. 사용자가 입력한 설정은 AI 제안이 덮지 않는다.
- **순서를 지킨다.** 이전 화가 `finalized` 가 아니면 다음 화를 쓰지 않는다.
- **관계 수치는 AI 가 적지 않는다.** AI 는 사건만 뽑고 `dynamics.py` 가 계산한다. 사용자가 고칠 때는 `수동보정` 사건으로 기록해 재생할 수 있게 한다.
- **컨텍스트는 일정한 크기로.** 이전 본문 전체가 아니라 화별 요약 + 직전 화 끝부분 + 현재 데이터만 넣는다. (검수는 예외로 앞선 본문 전체를 본다.)
- **장편은 줄거리를 접는다.** 화별 요약을 다 넣지 않고 `story_so_far`(끝난 부 · 아크 요약 + 지금 아크 화별 요약)를 쓴다. 인물 · 떡밥 · 사실 · 알게 된 정보도 `prompts.py` 의 필터를 거친다. 새 블록도 화수에 따라 끝없이 커지지 않게 한다. 단편(`form = "short"`) 경로는 바꾸지 않는다.
- **바뀌지 않는 블록이 앞, 화마다 바뀌는 블록이 뒤.** `static_context()` 를 앞에 둬야 Gemini 암묵적 캐시가 맞는다. 컨텍스트에 블록을 추가할 때 이 순서를 지킨다.
- **API 경로와 작업지시서 경로는 같은 프롬프트를 공유한다.** 프롬프트를 고칠 때는 `prompts.py` 한 곳만 고치고, `brief` 출력도 함께 확인한다. 나중에 MCP 서버도 이 함수들을 재사용한다.
- **LLM 호출은 `LLM` 인터페이스 뒤에만 둔다.** pipeline 이나 cli 에서 SDK 를 직접 부르지 않는다. 새 LLM 구현이나 새 API 호출 경로는 `usage.record` 를 불러 사용량 화면에 잡히게 한다. 스레드를 새로 띄우면 `contextvars.copy_context()` 로 작품 · 화 정보를 넘긴다.
- LLM 이 채우는 스키마(`SetupSuggestion`, `StyleProfile`, `ArcPlan`, `PlotBatch`, `PlotRevision`, `NameOptions`, `PassageRevision`, `StateDelta`, `StoryEvent`, `ConsistencyReport`, `SeriesPlan`, `ArcProposal`, `Recap`, `ImpactReport`, `StorylineProposal`, `SerialConversion`, `SerialRebuild`, `Rework`, `HookReport`, `OpeningPlots`, `IllustDraft`, `LookSuggestion`, `StyleLearning`)에는 dict 타입 필드를 쓰지 않는다 (Gemini 구조화 출력 호환).

## 개발 명령

```bash
pip install -r requirements.txt
python -m unittest                  # mock LLM 으로 전체 흐름 스모크 테스트 (API 키 불필요)
CANON_LLM=mock python -m canon ...  # 수동 확인
```

환경 변수: `GEMINI_API_KEY`, `CANON_LLM`(gemini | local | mock), `CANON_MODEL`(기본 `gemini-4-argon`), `CANON_LOCAL_URL` / `CANON_LOCAL_MODEL` / `CANON_LOCAL_KEY`(로컬 서버), `CANON_LLM_PLAN` / `_WRITE` / `_CHECK` / `_STATE` / `_NAME` / `_REVISE` / `_ILLUSTRATION`(단계별 백엔드), `CANON_MODEL_PLAN` / `_WRITE` / `_CHECK` / `_STATE` / `_NAME` / `_REVISE` / `_ILLUSTRATION`(단계별 모델), `CANON_HOME`(프로젝트 저장 위치, 기본 `projects/`), `CANON_USAGE`(사용량 기록 파일, 기본 `projects/.usage/usage.jsonl`).

스키마나 파이프라인을 바꾸면 `canon/mock.py` 도 맞춰 고치고 `python -m unittest` 가 통과하는지 확인한다. 실제 Gemini 호출은 키가 있을 때만 확인할 수 있으니, 확인하지 못했다면 그렇다고 밝힌다.

## 규칙

- 사용자에게 보이는 문구, 프롬프트, 문서는 **한국어**로 쓴다. 코드 식별자는 영어.
- 기본 LLM 은 **Gemini** 다 (사용자 결정). 다른 프로바이더는 `LLM` 구현을 추가하는 방식으로만 넣는다. 로컬 모델은 `LocalLLM`(OpenAI 호환) 하나로 Ollama, llama.cpp, vLLM, LM Studio 를 모두 다룬다. 파이프라인 호출부는 `get_llm("plan" | "write" | "check" | "state" | "name" | "revise" | "illustration")` 로 단계를 밝힌다.
- **API 키, `.env`, `projects/`(사용자 소설 데이터)는 커밋하지 않는다.** `.gitignore` 에 있다.
- 스키마 필드를 바꾸면 기존 `project.json` 이 읽히도록 기본값을 둔다.
- 기능을 바꾸면 README.md 와 DESIGN.md 의 해당 부분도 고친다.

## 로드맵

1. Gemini 실호출 검증과 프롬프트 튜닝, 화별 상태 스냅샷과 되돌리기
2. 구독형 채팅 앱(Claude, Gemini, ChatGPT)용 작업지시서 고도화 (`brief`, `import`, `update --from-json` 은 이미 있음)
3. MCP 서버: 작업지시서 조회, 본문 제출, 상태 변경 제안/반영을 tool 로 노출
4. 웹 UI: 설정 폼, 관계도, 기승전결 플롯 보드, 상태 변경 승인 화면
5. 장편 확장 (부 · 아크 · 롤링 기획 · 접은 줄거리는 완료. 관계 시간 감쇠, 장르 프리셋 남음)

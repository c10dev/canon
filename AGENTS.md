# AGENTS.md

Canon 저장소에서 작업하는 AI 에이전트(Claude Code, Codex, Gemini CLI 등)를 위한 안내서.
이 파일은 모든 작업에 실린다. 모듈 하나하나의 설명은 아래 '언제 무엇을 읽나'의 문서에 있고, 그 작업을 할 때만 읽는다.

## 프로젝트 목표

AI 로 소설을 길게 쓸수록 인물 관계, 심리, 말투, 복선, 문체가 무너진다. Canon 은 이것들을 **구조화된 데이터**로 관리하고, 매 화마다 그 데이터로 프롬프트를 조립해 일관성을 유지한다. 본문을 쓴 뒤 AI 가 상태 변경안을 만들고, **사용자가 승인해야** 데이터에 반영된다.

현재 범위(MVP): 단편 1권 10~20화, 그리고 부 → 아크 → 화로 나눠 쓰는 200~300화 장편 연재(`Meta.form = "serial"`). 자세한 설계는 [DESIGN.md](DESIGN.md).

흐름: `new` → `style` → `arc` → `plot` → `confirm` → (스토리보드 → 큐 시트) → `write` → `check` → `update` 반복(`run` 이 자동 반복).
장편(`new --serial`)은 `arc` 대신 `series` 한 번, 그리고 아크마다 `nextarc` → `plot` → `confirm` → `run` → `recap` 을 반복한다. 명령별 쓰임은 [docs/modules/core.md](docs/modules/core.md) 의 `canon/cli.py` 절.

## 언제 무엇을 읽나

| 이런 일을 할 때 | 먼저 읽을 문서 |
|---|---|
| 지도 기능(`canon/atlas.py` · `canon/maps/` · `static/atlas*.js`)을 고칠 때 | [docs/map/](docs/map/README.md): 모듈 경계, 지도 데이터 형식, 일감 차례와 작업 명세서. 일감을 끝내면 그 명세서의 상태와 `docs/map/plan.md` 를 고친다 |
| 장면 연출(방 안 자리 · 자세 · 신체 접촉을 박자마다 적고 재생하는 도구, `stage`)을 만들거나 고칠 때 | [docs/stage/](docs/stage/README.md): 정한 규칙, 데이터 형식, 일감 차례와 작업 명세서, 화면 시안 |
| 컨텍스트 조립(`context.py` 의 활성화 · 프롬프트 보기와 블록 설정 · 정규식 규칙 · 선언형 규칙 · 접은 줄거리 고르기)을 고칠 때 | [docs/context/](docs/context/README.md). 일감을 끝내면 그 명세서의 상태와 `docs/context/plan.md` 를 고친다 |
| 설계도(`canon/blueprint.py`: 관계 이정표 · 접촉 사다리, 탑다운 작품 설계)를 만들거나 고칠 때 | [docs/blueprint/](docs/blueprint/README.md): 정한 규칙, 일감 차례와 작업 명세서. 일감을 끝내면 그 명세서의 상태와 `docs/blueprint/plan.md` 를 고친다 |
| 작품 구축 형식(로그라인 · 부와 아크 기획 · 완급 계획 · 플롯 규칙)을 웹소설 · 라이트노벨식(짧은 고구마 · 잦은 사이다 · 성장 축 · 하렘)으로 가르는 일을 할 때 | [docs/webnovel/](docs/webnovel/README.md): 바꿀 곳 조사, 제안, 일감 차례와 정할 것. 일감을 끝내면 그 명세서의 상태와 `docs/webnovel/plan.md` 를 고친다 |
| 웹 화면(`canon/static/`)의 모양을 고칠 때 | [docs/design/](docs/design/README.md): 디자인 시스템의 원본: 문구 · 색 · 글자 · 간격 규칙(README), 화면 배치(`layout.md`), 토큰 값(`tokens.json`), 컴포넌트별 문서와 미리보기(`components/<이름>/README.md` · `preview.html`), 미리보기가 읽는 컴포넌트 CSS 사본(`components/bundle.css`) |
| 웹 화면의 쓰는 흐름(가림막 · 다시 그릴 때 본문 칸 지키기 · 대화 에이전트 하나로 합치기 · AI 답 흘려 보이기 · 집필 화면의 상태 변경안 · 메뉴 정리)을 고칠 때 | [docs/ux/](docs/ux/README.md): 2026-11-09 관찰 결과, 일감 차례와 작업 명세서. 일감을 끝내면 그 명세서의 상태와 `docs/ux/plan.md` 를 고친다 |
| 프롬프트 글(`prompts.py` 의 지시 · 규칙 줄 · `PREAMBLE`, `llm.POLICY_NOTE` · `ADULT_NOTE`)을 다듬거나 줄일 때 | [docs/prompts/editing.md](docs/prompts/editing.md): 편집 AI의 가치관 · 제공자 정책을 끼워 넣지 않는 원칙(0절), 뜻 지도, 확인 층 |
| 스키마 · 프롬프트 · 파이프라인 · 검수 · 스토리보드 · 큐 시트 · 저장 · 작업 · 자동 집필 · 명령줄 · 웹 서버를 고칠 때 | [docs/modules/core.md](docs/modules/core.md) |
| LLM 백엔드 · 사용량 · 판단기 · 가짜 응답(mock) · 환경 변수를 고칠 때 | [docs/modules/ai.md](docs/modules/ai.md) |
| 인물 · 관계 · 호칭 · 복선 · 상태창 · 도감 · 시간 · 인과율 · 줄기 · 갈래 · 플레이 같은 이야기 데이터 기능과 그 화면을 고칠 때 | [docs/modules/story.md](docs/modules/story.md) |
| 화면 뼈대(`app.js` · `outline.js` · `hub.js` · 팔레트 · 대화 패널)나 단계 화면 파일(`settings.js` · `home.js` · `setup.js` · `style.js` · `plot.js` · `write.js` · `check.js` · `review.js` 등)을 고칠 때 | [docs/modules/web.md](docs/modules/web.md) |
| 역설계 · 레퍼런스 원고 · 쇠맛 실험실 · 문단 연습장 · 문체 지표 · 연구 화면 · 시험(`stattrial` · `blocktrial`)을 고칠 때 | [docs/modules/labs.md](docs/modules/labs.md). 레퍼런스 원고의 정한 규칙과 남은 일감은 [docs/refs/](docs/refs/README.md) |
| 장면 연출 코드(`stage` · `stagepath` · `stage3d` · `static/stage*.js`)를 고칠 때 | [docs/modules/stage.md](docs/modules/stage.md) |
| 지도 코드를 고칠 때 | [docs/modules/map.md](docs/modules/map.md) |

- 모듈을 고치기 전에 `docs/modules/` 에서 그 파일의 절(`### 경로`)을 읽는다. 다른 모듈과 같이 맞춰야 하는 규칙('같은 규칙', '함께 고친다')이 거기 적혀 있다.
- 모듈의 동작을 바꾸거나 새 파일을 더하면 같은 변경 안에서 그 절을 고친다. 새 파일은 갈래 파일에 새 절을 더한다(`tests/test_agents_docs.py` 가 `canon/` 의 파일마다 이름이 있는지 본다).
- 기능의 py 와 그 화면 js 는 같은 갈래 파일에 둔다(예: `statwin.py` 와 `static/statwin.js` 는 `story.md`).

## 설계 원칙 (깨지 않기)

- **인물은 불변 설정(`Character`)과 가변 상태(`CharacterState`)로 나눈다.** 말투와 성격은 고정, 감정·목표·아는 정보만 화마다 바뀐다. 본문에서 뒤 화까지 이어지게 바뀐 설정(머리를 자름, 영구 흉터, 말투를 바꾸기로 함)은 상태 변경안의 설정 바꾸기 제안으로만 오고, 작가가 상태 승인 화면에서 골라야 바뀐다(기본으로 체크하지 않음). 자동 집필과 `-y` 는 반영하지 않고 남겨 둔다(`charlog.hold`). 바뀐 것은 `Project.setting_log` 에 전후 값으로 남긴다.
- **AI 출력은 작가가 승인하거나 작가가 고른 권한 안에서만 저장한다.** 설정, 플롯, 상태 변경은 사용자 확인(`confirm` 또는 `-y`) 후에만 저장한다. 자동 집필은 사용자가 정한 승인 정책을 통과한 화만 반영하고 `Episode.auto` 로 표시한다. 대화 에이전트(`agent.py`)는 작가가 세션에 고른 권한 모드 안의 쓰기만 바로 저장하고, 모두 되돌릴 수 있게 쓰기 전 · 뒤 값을 남긴다. 본문이 있는 화의 플롯 · 상태, 관계 수치, 인물 설정 바꾸기 반영, 지우기는 어느 모드에서도 AI 가 하지 않는다. 정책이나 권한 모드를 느슨하게 만드는 기본값 변경은 사용자와 정한다.
- **확정된 것은 덮어쓰지 않는다.** confirmed 이상인 화의 플롯은 재생성해도 유지한다. 사용자가 입력한 설정은 AI 제안이 덮지 않는다.
- **순서를 지킨다.** 이전 화가 `finalized` 가 아니면 다음 화를 쓰지 않는다.
- **관계 수치는 AI 가 적지 않는다.** AI 는 사건만 뽑고 `dynamics.py` 가 계산한다. 사용자가 고칠 때는 `수동보정` 사건으로 기록해 재생할 수 있게 한다.
- **컨텍스트는 일정한 크기로.** 이전 본문 전체가 아니라 화별 요약 + 직전 화 끝부분 + 현재 데이터만 넣는다. (검수는 예외로 앞선 본문 전체를 본다.)
- **장편은 줄거리를 접는다.** 화별 요약을 다 넣지 않고 `story_so_far`(끝난 부 · 아크 요약 + 지금 아크 화별 요약)를 쓴다. 인물 · 떡밥 · 사실 · 비밀 · 알게 된 정보도 `prompts.py` 의 필터와 `context.BUDGET` 예산을 거친다. 장편 검수는 `budget` 방식(직전 3화 원문 + 옛 화 관련 단락)이 기본이다. 새 블록도 화수에 따라 끝없이 커지지 않게 하고, 예산을 넘겨 뺐으면 몇 개 뺐는지 적는다. 단편(`form = "short"`) 경로는 바꾸지 않는다.
- **바뀌지 않는 블록이 앞, 화마다 바뀌는 블록이 뒤.** 컨텍스트에 블록을 추가할 때 이 순서를 지킨다. `static_context()` 를 앞에 둬야 화 사이 Claude API 캐시(`claude.cache_blocks`)가 맞는다. Gemini 암묵적 캐시는 앞 요청을 통째로 품은 요청에만 맞으므로, 요청이나 재료는 프롬프트 맨 뒤에 덧붙인다. 실측은 DESIGN.md 4장 '컨텍스트 조립'.
- **API 경로와 작업지시서 경로는 같은 프롬프트를 공유한다.** 프롬프트를 고칠 때는 `prompts.py` 한 곳만 고치고, `brief` 출력도 함께 확인한다.
- **LLM 호출은 `LLM` 인터페이스 뒤에만 둔다.** pipeline 이나 cli 에서 SDK 를 직접 부르지 않는다. 새 LLM 구현이나 새 API 호출 경로는 `usage.record` 를 불러 사용량 화면에 잡히게 한다. 스레드를 새로 띄우면 `contextvars.copy_context()` 로 작품 · 화 정보를 넘긴다.
- **LLM 이 채우는 스키마에는 dict 타입 필드를 쓰지 않는다.** Gemini 구조화 출력이 받지 못한다. `tests/test_schema_nodict.py` 가 `.json(…)` 으로 받는 모든 응답 형식과 그 안의 모델을 본다.

## 개발 명령

```bash
pip install -r requirements.lock   # 검증한 버전으로 고정한 목록
CANON_HOME=$(mktemp -d) python -m pytest -q -n auto tests  # 전체 시험 (mock LLM, API 키 불필요, 9코어에서 약 2분, -n 없이 약 6분)
CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_timeline.py  # 고친 기능의 시험만 빠르게
CANON_LLM=mock python -m canon ...  # 수동 확인
ruff check canon tests scripts      # 정적 검사 (쓰지 않는 import · 변수, 정의 안 된 이름, 설정은 pyproject.toml)
```

- 시험은 `CANON_HOME` 을 임시 폴더로 두고 돌린다. `tests/conftest.py` 도 값이 없으면 임시 폴더를 정하므로, 이 값은 덤 안전장치다.
- `tests/conftest.py` 는 `CANON_CONFIG` 를 `CANON_HOME` 안으로 돌리고 `CANON_USAGE` · `CANON_STYLES` · `CANON_RULES` · `CANON_REFS` · `CANON_STUDIO` · `CANON_PROMPTLAB` · `CANON_PROMPTSETS` 을 지운다.
- 저장 위치가 저장소의 `projects/` 이면 `tests/conftest.py` 가 시험을 시작하지 않는다(`tests/test_conftest_isolation.py`).
- 공통 `client` fixture 는 `tests/conftest.py` 에 있다. `canon.web` 을 다시 불러오지 않고 `store.ROOT` 만 시험 폴더로 바꾼다.
- 시험은 `importlib.reload(store)` · `reload(web)` 를 쓰지 않는다(한 번에 1~2.5초). 저장 위치는 `monkeypatch.setattr(store, "ROOT", tmp_path)` 로 바꾼다(`tests/test_conftest_isolation.py`).
- `store` · `web` 의 모듈 캐시는 `tests/conftest.py` 의 autouse fixture `_fresh_caches` 가 시험마다 비운다. 캐시를 더하면 그 목록에도 더한다.
- `python -m unittest` 는 쓰지 않는다. 시험 대부분(pytest 형식 함수)을 건너뛴다.
- 스키마나 파이프라인을 바꾸면 `canon/mock.py`(새 기능은 `mock_<기능>.py`)도 맞춰 고치고 전체 시험이 통과하는지 확인한다.
- 실제 Gemini 호출은 키가 있을 때만 확인할 수 있다. 확인하지 못했다면 그렇다고 밝힌다.
- 의존성은 `requirements.txt` 에 범위로 적고, 바꾸면 `uv pip compile --universal --python-version 3.12 requirements.txt -o requirements.lock` 으로 잠금 파일을 다시 만든다(`tests/test_requirements_lock.py`).
- 환경 변수 목록은 [docs/modules/ai.md](docs/modules/ai.md) 의 `canon/llm.py` 절.

## 비용 드는 모델 실험

에이전트는 이 규칙 안에서 유료 API(Gemini, Vertex AI, `claude-api`)를 부르는 실험을 사용자에게 묻지 않고 돌린다. 이 규칙은 "비용이 걸린 확인은 돌리지 않는다" 같은 전역 규칙보다 우선한다.

- **할 수 있는 것**: 실호출 검증, 프롬프트 튜닝, 모델 · 백엔드 비교, 검수 시험, 캐시 · 토큰 실측. 연구 화면 로직(`research.py`), `compare`, `openings`, `hook`, 스크립트로 부른다.
- **예산**: 실험 하나의 추정 비용이 $5 이하이고 세션 합계가 $10 이하면 묻지 않는다. 넘을 것 같으면 추정 비용과 이유를 적어 먼저 묻는다. 사용자가 그 세션에서 다른 한도를 정하면 그 한도를 쓴다.
- **추정 먼저**: 돌리기 전에 호출 수 × 프롬프트 크기(한국어 1.7자/토큰)로 비용을 어림한다. 가격은 `python -m canon usage --prices` 의 가격표를 쓴다. 표본은 작게 시작한다(1~2회로 형식과 비용을 본 뒤 늘린다).
- **싼 쪽부터**: 같은 질문에 답할 수 있으면 mock → 로컬 → 싼 모델(flash 급) → 비싼 모델 순으로 고른다. 기다려도 되는 대량 호출은 배치(절반 가격)를 쓴다.
- **작품 데이터 보호**: 사용자 작품(`projects/<이름>/`)은 바꾸지 않는다. 작품이 필요하면 임시 `CANON_HOME` 에 복사해 쓴다. 블라인드 비교의 '본문으로 채택'은 켜지 않는다.
- **사용량 기록**: 호출은 실제 사용량 기록에 남긴다. 임시 `CANON_HOME` 을 쓸 때도 `CANON_USAGE=$PWD/projects/.usage/usage.jsonl` 로 둔다. 시작 전과 끝난 뒤 `python -m canon usage --days 1` 을 견줘 세션 비용을 센다.
- **멈출 때**: 형식 오류 · 실패가 연달아 나거나 같은 호출을 세 번 넘게 다시 보내면 멈추고 원인을 먼저 본다. 끝없이 도는 반복문이나 자동 집필(`auto`)을 목표 없이 띄우지 않는다.
- **결과**: 실험마다 목적, 모델, 표본 수, 결과, 쓴 비용을 남긴다. 연구 화면 실험은 `research/log.jsonl` 에 저절로 남고, 정리한 글은 `reports/` 에 둔다(커밋하지 않음). 설계를 바꾸는 실측값은 DESIGN.md 에 날짜와 함께 옮긴다(예: 캐시 실측 2026-10-27).
- **보고**: 작업 보고에 쓴 비용(가격표 추정치)과 모델별 호출 수를 적는다. 키가 없거나 호출이 막혀 못 돌린 실험은 그렇다고 적는다.
- 키와 결제 설정은 바꾸지 않는다. 키를 화면 · 로그 · 보고에 찍지 않는다.

## 규칙

- 사용자에게 보이는 문구, 프롬프트, 문서는 **한국어**로 쓴다. 코드 식별자는 영어.
- 화면 문구는 해요체로 쓴다("저장했어요"). 화면에 보이는 서버 문구(오류, 작업 기록, 자동 집필 멈춤 이유, 명령줄 안내)도 같다. LLM 에게 주는 프롬프트는 이 규칙 밖이다. 영문 뒤 조사는 붙인다("AI가", "JSON을"). 단계 이름은 사이드바와 같게, '반영'은 상태 승인으로 데이터에 들어가는 뜻에만, AI 제안을 받아들이는 동작은 '적용'으로 쓴다. 날짜는 `fmtDate` · `fmtDateTime`, 화 범위는 'a~b화'. 화면 문구의 나머지 규칙은 `docs/design/README.md`.
- **Swift 앱(`swift/`) 개발은 멈췄다 (2026-10-28, 사용자 결정).** 웹과 Swift 를 함께 고치면 에이전트 시간이 두 배로 든다. 다시 시작하자고 사용자가 말할 때까지 아래를 지킨다.
  - `swift/` 의 파일을 고치지 않는다. Swift 를 빌드하거나 시험하지 않는다.
  - `web.py` 를 바꿔도 `python scripts/make_openapi.py` 를 돌리지 않는다.
  - 코드 주석과 문서의 "Swift 앱도 함께 고친다"는 지금 따르지 않는다. 웹 쪽만 고친다.
  - Swift 와 맞추는 시험(`tests/test_openapi.py`, `test_logline.py` 의 `test_swift_tone_words_match`)은 `CANON_SWIFT=1` 일 때만 돈다.
  - 다시 시작할 때: `python scripts/make_openapi.py` 로 명세를 다시 만들고, `CANON_SWIFT=1` 로 Swift 맞춤 시험을 돌리고, `swift/README.md` 의 표대로 웹에서 바뀐 표시 규칙을 옮긴다.
- 기본 LLM 은 **Gemini** 다 (사용자 결정). 다른 프로바이더는 `LLM` 구현을 추가하는 방식으로만 넣는다. Claude 구독 로그인은 설치된 Claude Code 를 부르는 방식만 쓴다. Claude 계정 로그인 화면을 Canon 에 만들거나 OAuth 토큰을 읽고 저장하는 코드는 넣지 않는다 (Anthropic 약관). 로컬 모델은 `LocalLLM`(OpenAI 호환) 하나로 Ollama, llama.cpp, vLLM, LM Studio 를 모두 다룬다. 파이프라인 호출부는 `get_llm(단계)` 로 단계를 밝힌다(단계 이름은 `settings.STAGES`).
- **API 키, `.env`, `projects/`(사용자 소설 데이터)는 커밋하지 않는다.** `.gitignore` 에 있다.
- 스키마 필드를 바꾸면 기존 `project.json` 이 읽히도록 기본값을 둔다.
- 기능을 바꾸면 README.md 와 DESIGN.md 의 해당 부분도 고친다.
- 화면 모양(색, 글자, 간격, 컴포넌트, 배치, 폭 구간)을 바꾸면 같은 변경 안에서 `docs/design/` 도 고친다. 색 토큰을 더하거나 바꾸면 `canon/static/app.css` 의 두 `:root` 블록과 `docs/design/tokens.json` 을 함께 고친다(`tests/test_design_tokens.py` 가 맞춰 본다). 컴포넌트 규칙을 바꾸면 `components/bundle.css` 의 그 줄도 app.css 와 같게 고친다. Claude 디자인 시스템 페이지는 이 폴더에서 다시 올리는 보기라 그 페이지만 고치지 않는다.
- 화면에 늘 보이는 버튼 · 안내 문장 · 메뉴를 더하면 `docs/design/README.md` 의 '덜기' 절을 따른다.
- 여러 에이전트 세션이 동시에 일할 때는 코드를 고치는 세션마다 자기 git worktree 와 브랜치를 쓴다. 같은 폴더 · 같은 브랜치에서 둘 이상이 고치면 변경이 섞여 커밋할 때 hunk 를 손으로 골라야 한다. 읽기만 하는 세션은 같은 폴더를 써도 된다.

## 문서 줄 규칙

여러 세션의 PR 이 같은 문서를 함께 고친다. git 은 줄 단위로 병합하므로, 같은 줄이나 바로 이웃한 줄을 두 PR 이 고치면 충돌한다. `docs/modules/` 를 고칠 때는 아래를 지킨다. README.md · DESIGN.md 의 목록에도 되도록 지킨다.

- 한 줄에는 사실 하나만 쓴다. 긴 설명에 몇 낱말을 덧붙이지 말고 새 줄을 더한다.
- 새 항목이 계속 붙는 이름 목록(가짜 응답 파일, 명령, 환경 변수 등)은 한 줄에 한 항목, 알파벳 · 가나다 차례로 쓴다.
- 줄 끝에 쉼표나 '·' 처럼 다음 줄과 잇는 문장부호를 두지 않는다. 새 줄을 더할 때 앞줄을 고치지 않게 하려는 것이다.
- 새 사실은 절 끝에 덧붙이지 말고 가장 가까운 관련 줄 바로 뒤에 넣는다. 새 절(`### 경로`)은 경로 차례에 맞는 자리에 넣는다.
- 고치지 않는 줄은 다시 감싸거나 옮기지 않는다.
- 한 줄은 300자를 넘지 않는다(`tests/test_agents_docs.py`).

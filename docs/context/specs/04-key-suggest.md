# 04. 키워드 AI 제안

상태: 설계 · 계획: [plan.md](../plan.md) 의 4번 · 먼저: 2번

## 목표

작가가 인물 · 이야기 요소 · 복선마다 키워드(찾는 키 · 보조 키 · 제외 키)를 손으로 다 적지 않아도 된다.
AI 가 항목의 설정과 본문을 읽고 키워드를 제안하고, 작가가 고른 것만 적용한다(2026-11-08 정함, Q16 b).
대화 에이전트도 권한 모드 안에서 키워드를 고칠 수 있고, 고친 것은 되돌릴 수 있다(2026-11-08 정함, Q29).
키워드는 2번 일감의 활성화 묶음(`Activation`)이 판정에 쓰는 값이다. 이 일감은 판정 규칙을 바꾸지 않는다.

## 정할 것

시작 전에 사용자와 정한다. 추천안을 먼저 쓴다. 정하면 결과를 적고 [README.md](../README.md) 의 정한 규칙에도 더한다.

1. 부를 단계(`get_llm` 의 단계 이름, `settings.STAGES`) — 추천: `"plan"`. 같은 꼴의 설정 제안(`pipeline.suggest_body` · `suggest_voice`)이 `"plan"` 을 쓴다. 다른 안은 `"name"` 이다(부모가 `plan`, 기본 묶음은 flash 급).
2. 제안 단위 — 추천: 항목 하나(화면의 항목 카드 버튼)와 목록 한 번(한 종류에서 작가가 고른 항목들, 한 번 부를 때 `KEY_BATCH` 개까지) 둘 다 둔다.
3. 동기 호출인지 백그라운드 작업인지 — 추천: 항목 하나는 동기 엔드포인트, 목록 한 번은 백그라운드 작업(`jobs`, 종류 이름 `keys`)으로 둔다.
   - 항목 하나가 동기로 돌 수 있는 것은 화 수 세기의 비용 규칙(아래 '화 수 세기') 덕분이다.
4. 적용 방법 — 추천: `suggest_body` 처럼 화면이 고른 값을 항목에 넣고 작품 저장으로 저장한다. 따로 적용 엔드포인트를 두지 않는다.
5. 에이전트 쓰기 종류 — 추천: `permit(s, kind)` 는 종류 하나만 받으므로 쓰기 종류를 셋으로 나눈다.
   - `keys_new`(화면 이름 '빈 키워드 칸'): 빈 칸에 더하기. `DRAFT_KINDS` 에 더해 '빈 곳 · 초안만 자동'에서 바로 쓴다.
   - `keys`(화면 이름 '키워드'): 키가 있는 칸에 더하기. '모두 자동'에서만 바로 쓴다.
   - `keys_remove`(화면 이름 '키워드 빼기'): 빼기. 정할 것 6을 따른다.
6. 에이전트가 키를 빼는 것 — 추천: 빼기는 '모두 자동'에서도 승인 카드로 묻는다. AGENTS.md 의 '지우기는 어느 모드에서도 AI 가 하지 않는다'에 가깝게 둔다.
   - `permit` 에 `outside` 처럼 `all` 판정보다 앞서는 `keys_remove` 갈래를 둔다('이 세션에서 묻지 않기'는 따른다).
7. 이야기 요소의 다른 이름(`StoryElement.aliases`) 제안을 둘지 — 추천: 두지 않는다.
   - `Activation` 의 키는 02 의 규칙대로 `elements.basis` 에 넣지 않으므로 적용해도 영향 분석이 낡지 않는다.
   - `aliases` 는 `elements.basis` 에 들어가고 프롬프트에도 찍힌다. 그래서 제안을 적용하면 영향 분석이 지난 것으로 보인다.
   - 두기로 하면 요소 카드에만 '다른 이름' 칩을 더한다.
8. 명령줄 — 추천: 이 일감에서는 명령을 더하지 않는다. 화면과 에이전트로만 쓴다.
9. AI 제안의 범위 — 추천: 제안은 더할 키만 낸다. 빼기는 작가가 손으로 하거나 에이전트 `edit_keys` 로 한다(정할 것 6).
   - 까닭: 제안 화면은 체크한 칩을 더하기만 한다. 빼기 제안을 받으면 빼기 칩이라는 다른 동작이 생긴다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/schema.py` | LLM 응답 형식 `KeySuggestion` · `KeyIdea`, 프로그램이 채우는 `KeyHit`, 에이전트 쓰기 `KeyEdit`, 에이전트 되돌리기 값 `KeyUndo` |
| `canon/schema.py` 의 `Approval` | 묻는 키워드 쓰기를 담는 `keys_edit: list[KeyEdit]`(기본값 빈 목록). 지금 `revision` 은 `PlotRevision`, `op` 는 `RenumberOp` 만 담는다 |
| `canon/keys.py` (새 파일) | 제안 정리(`clean`), 화 수 세기(`hits`), 에이전트 쓰기와 되돌리기(`apply_edit` · `undo_edit`). LLM 을 부르지 않는다 |
| `canon/prompts.py` | `key_prompt(p, targets)` 하나. 시스템 문은 `SYSTEM_PLANNER` 를 쓴다 |
| `canon/prompts.py` 의 `AGENT_PLOT_TOOLS` | 도구 목록 글에 `read_keys` · `edit_keys` 줄 |
| `canon/pipeline.py` | `suggest_keys(llm, p, targets)`: `llm.json(..., KeySuggestion)` 을 부르고 `keys.clean` · `keys.hits` 를 거쳐 돌려준다. 저장하지 않는다 |
| `canon/web.py` | 항목 하나 제안 `POST /api/projects/{name}/keys/{target}`(지금 `characters/{cid}/voice` · `body` 제안 곁). `KeySuggestion` 을 돌려준다. 단계는 `get_llm("plan")`(정할 것 1) |
| `canon/web.py` 의 `JOB_MAKERS` · `JobIn` | 목록 작업 `keys`. `JobIn` 에 `targets: list[str] = []`('c:<id>' 꼴)를 더한다. 작업은 `kind="keys"` 와 `targets` 로 부른다 |
| `canon/agent.py` | 쓰기 도구 `edit_keys`, `permit` 의 `keys_remove` 갈래(정할 것 6), `undo` 의 `KeyUndo` 갈래 |
| `canon/agent.py` 의 `READ_TOOLS` · `KIND_LABELS` · `DRAFT_KINDS` | `READ_TOOLS` 에 `read_keys`, `KIND_LABELS` 에 `keys_new` · `keys` · `keys_remove`, `DRAFT_KINDS` 에 `keys_new`(정할 것 5) |
| `canon/schema.py` 의 `PlotAgentStep` | `tool` 목록에 `read_keys` · `edit_keys`, `edit_keys` 일 때 채우는 칸 `keys_edit: list[KeyEdit]` |
| `canon/mock.py` 의 `_agent_step` | `edit_keys` 를 내는 갈래(시험 문구에 맞춰) |
| `canon/mock_keys.py` (새 파일) | `@responds(KeySuggestion)` 가짜 응답. `canon/mock.py` 맨 아래 import 줄에 더한다 |
| `canon/static/cast.js` | 인물 카드의 '키워드 제안' 버튼과 고르기 칸 |
| `canon/static/causal.js` | 이야기 요소 카드의 같은 버튼과 고르기 칸 |
| `canon/static/foreshadow.js` | 복선 카드의 같은 버튼과 고르기 칸 |
| `canon/static/agent.js` | 도구 이름 표에 `read_keys` · `edit_keys` 이름표, `edit_keys` 단계와 승인 카드 표시 |

- 키워드가 놓이는 자리는 2번 일감이 정한 `Activation.keys` · `secondary_keys` · `exclude_keys` 다. 이 일감은 그 자리를 읽고 쓰기만 한다.
- 판정 함수는 `canon/context.py` 에만 있다(Q7). `keys.hits` 는 그 함수와 02 의 낱말 맞추기 함수를 부르고 판정을 따로 만들지 않는다.

## 데이터 · 스키마

### LLM 응답 형식

```
KeySuggestion
  items: list[KeyIdea]
  notices: list[str]    # SkipJsonSchema. 프로그램이 채우는 알림 줄 (뺀 키 수 등)

KeyIdea
  target: str           # 'c:<인물 id>' · 'e:<요소 id>' · 'f:<복선 id>'
  keys: list[str]       # 더할 찾는 키 (Activation.keys)
  secondary_keys: list[str]  # 더할 보조 키 (Activation.secondary_keys, 주 키와 함께 있어야 켜진다)
  exclude_keys: list[str]    # 더할 제외 키 (Activation.exclude_keys, 있으면 꺼진다)
  reason: str           # 작가에게 보일 한두 문장
```

- dict 필드를 쓰지 않는다. `tests/test_schema_nodict.py` 가 `.json(…)` 으로 받는 형식을 본다.
- AI 는 더할 키만 낸다. 빼거나 바꾸는 제안은 받지 않는다(정할 것 9).
- 이름은 2번 일감의 `Activation` 필드 이름과 맞춘다. 2번이 다른 이름을 쓰면 이 절을 먼저 고친다.
- 정할 것 7에서 요소의 다른 이름 제안을 두기로 하면 `KeyIdea` 에 `aliases: list[str]` 를 더하고 `e:` 항목에만 받는다.

### 프로그램이 채우는 것

```
KeyHit (SkipJsonSchema)
  key: str
  kind: 'key' | 'secondary' | 'exclude'
  episodes: list[int]   # 이 키가 맞는 쓴 화 (아래 '화 수 세기')
  clash: str            # 다른 항목의 이름 · 다른 이름과 겹치면 그 항목 이름, 아니면 빈 글
```

- `KeyIdea` 에 `hits: list[KeyHit]` 를 SkipJsonSchema 로 붙인다. AI 는 채우지 않는다.

- `KeyIdea` 에 `changed: list[int]` 를 SkipJsonSchema 로 붙인다. 고른 키를 모두 더했을 때 판정이 바뀌는 쓴 화다.

### 에이전트 쓰기

```
KeyEdit
  target: str
  add_keys: list[str]
  add_secondary: list[str]
  add_exclude: list[str]
  remove_keys: list[str]
  remove_secondary: list[str]
  remove_exclude: list[str]
```

- dict 필드를 쓰지 않는다. `PlotAgentStep.keys_edit` 와 `Approval.keys_edit` 가 이 모델을 쓴다.

### 에이전트 되돌리기 값

```
KeyUndo
  target: str
  keys: list[str]
  secondary_keys: list[str]
  exclude_keys: list[str]
```

- `WriteRecord` 에 `keys_before` · `keys_after: list[KeyUndo]` 를 기본값 빈 목록으로 더한다. 옛 세션 파일도 읽힌다.
- `WriteRecord.tool` 은 `"edit_keys"` 다.

## 규칙

### 제안 재료 (`prompts.key_prompt`)

- 항목마다 지금 설정 한 줄(인물은 이름 · 역할 · 설명 칸, 요소는 `elements.describe` 꼴, 복선은 `description`)을 넣는다.
- 항목마다 지금 키워드를 넣는다. AI 가 이미 있는 키를 다시 내지 않게 한다.
- 항목마다 본문에서 그 항목이 나온 단락을 `KEY_SAMPLE` 자까지 넣는다.
- 단락은 02 가 `context.name_pattern` 에서 떼는 낱말 맞추기 함수를 본문 단락에 돌려 이름 · 다른 이름 · 지금 키가 맞은 곳이다.
- 이것은 낱말 맞추기이지 판정이 아니다. `context.activate` 는 단락 자리가 아니라 항목을 돌려주고, 본문이 아니라 찾는 범위(Q9)를 본다. 그래서 판정은 여전히 `context.py` 에만 있다(Q7).
- 이름이 본문에 없는 항목(복선 대부분)은 `context.recall` 로 설명과 겹치는 단락을 찾는다. 임베딩은 쓰지 않는다(DESIGN.md 7장, 2026-11-03 실측).
- 다른 항목의 이름과 다른 이름 목록을 넣는다. 제외 키를 고르는 데 쓰고, 겹치는 다른 이름을 피하게 한다.
- 바뀌지 않는 블록(작품 정보 · 항목 목록)이 앞, 항목별 단락이 뒤다.
- 요청 문장은 프롬프트 맨 뒤에 둔다(Gemini 암묵적 캐시).
- 재료는 화수에 따라 끝없이 커지지 않는다. 단락은 최근 화부터 채우고, 넘쳐 뺀 단락 수를 프롬프트에 적는다.

### 프롬프트가 AI 에게 시키는 것

- 찾는 키: 본문에서 그 항목을 실제로 부른 말(별명 · 호칭 · 줄임말). 조사를 붙이지 않은 꼴로 쓴다.
- 보조 키: 주 키가 흔한 낱말이라 다른 뜻으로도 나올 때, 그 항목일 때만 함께 나오는 말.
- 제외 키: 주 키가 나와도 그 항목이 아닌 글에 나오는 말.
- 근거 단락이 없는 키는 내지 않는다.

### 정리 (`keys.clean`, LLM 없음)

- 앞뒤 빈칸과 따옴표를 지운다.
- 두 글자보다 짧은 키는 뺀다(`elements.terms` 의 두 글자 규칙과 같다).
- `KEY_MAX_LEN` 자를 넘는 키는 뺀다.
- 항목의 이름이나 이미 있는 키와 같은 키는 뺀다.
- 한 항목 안에서 겹치는 키는 하나만 둔다.
- 제외 키가 그 항목의 이름이나 다른 이름에 들어 있으면 뺀다. 그 키가 늘 항목을 끄기 때문이다.
- 없는 항목을 가리키는 `target` 은 뺀다.
- 다른 항목의 이름 · 다른 이름 · 찾는 키와 같은 찾는 키는 빼지 않고 `KeyHit.clash` 에 적는다. 작가가 판단한다.
- 뺀 키 수는 `KeySuggestion.notices` 의 알림 줄로 돌려준다.

### 화 수 세기 (`keys.hits`, LLM 없음)

- 비용 규칙: 키마다 `context.activate` 를 부르지 않는다. sticky · 한 단계 더 찾기 때문에 한 번 부를 때마다 앞 화에 기대므로, 화 × 키 × 항목만큼 부르면 87화 장편에서 수만 번이 된다.
- 세는 화는 본문이 있는 화(`written` · `finalized`) 가운데 최근 `KEY_HIT_EPS` 화로 끊는다.
- 키 하나의 `KeyHit.episodes` 는 02 의 낱말 맞추기 함수를 각 화의 찾는 범위 글에 돌려 센다. 판정 함수를 부르지 않는다.
- 찾는 키 · 보조 키는 그 키가 맞고 이름 · 지금 키는 맞지 않는 화를 담는다.
- 제외 키는 그 키가 맞고 지금 이름 · 키로 찾히는 화를 담는다.
- `context.activate` 는 항목마다 두 번만 부른다. 지금 값으로 한 번, 제안한 키를 모두 더한 값으로 한 번 부르고, 판정이 바뀐 화를 `KeyIdea.changed` 에 담는다.
- 찾는 범위 글은 1번 측정이 정한 범위(02 의 `SCAN`)와 같다(Q9).
- 지금 데이터로 센다. 그 화를 쓸 때의 상태로 되돌리지 않는다. 화면에 '지금 설정으로 센 값'이라고 적는다.

### 적용

- AI 제안은 작가가 고른 키만 들어간다. 기본으로 체크하지 않는다.
- 제안 적용과 에이전트는 `Activation.keys` · `secondary_keys` · `exclude_keys` 에만 쓴다. 02 의 규칙대로 프롬프트용 직렬화가 `activation` 을 빼므로 프롬프트에 찍히지 않는다.
- `Character` 의 설정 칸(`name` · `role` · `appearance` · `personality` · `background` · `speech_style` · `narration_voice` · `secrets` 등)과 `StoryElement.aliases` 에는 쓰지 않는다.
- 그래서 키워드는 인물 설정 바꾸기가 아니고, `charlog` 의 설정 바꾸기 기록에 남기지 않는다.
- 자동 집필은 키워드 제안을 부르지 않는다.
- 단편과 장편 모두에서 쓴다. 판정이 두 꼴 모두에 걸리기 때문이다(Q18).

### 에이전트 (`agent.py`)

- `read_keys`: 인물 · 요소 · 복선의 이름과 지금 키워드를 `RESULT_LIMIT` 안에서 돌려준다.
- `edit_keys`: 항목마다 `KeyEdit`(더할 키와 뺄 키)를 받는다. 더할 키는 `keys.clean` 을 거친다.
- 칸마다 쓰기 종류를 정한다. 빈 칸에 더하면 `keys_new`, 키가 있는 칸에 더하면 `keys`, 빼면 `keys_remove` 다(정할 것 5).
- 종류마다 `permit(s, 종류)` 로 바로 쓸지 물을지 정한다. 묻는 부분은 `Approval.keys_edit` 에 담는다.
- 에이전트도 `Activation` 의 세 칸에만 쓴다. `Character` 설정 칸과 `StoryElement.aliases` 는 고치지 않는다.
- 바로 쓰면 쓰기 전 · 뒤 값을 `KeyUndo` 로 남긴다.
- 되돌리기는 지금 값이 쓴 직후 값과 같은 항목만 돌린다(`pipeline.plot_undo` 와 같은 규칙).
- 에이전트는 블록 켜고 끄기와 블록 예산을 고치지 않는다(Q29).
- 에이전트는 정규식 규칙과 선언형 규칙을 제안만 한다(Q29). 그 도구는 이 일감에서 만들지 않는다.
- 지금 에이전트는 플롯 대화(`TOPICS = ("plot",)`)만 돈다. 키워드 도구는 그 주제에 더한다.

### 처음 값

- `KEY_BATCH = 10`: 한 번 부를 때 항목 수. 근거 없는 처음 값이다. mock 과 실호출 1~2회로 응답 크기를 본 뒤 고친다.
- `KEY_SAMPLE = 3000`: 항목 하나의 단락 글자 예산. 근거 없는 처음 값이다. 같은 방법으로 고친다.
- `KEY_MAX_LEN = 20`: 키 하나의 최대 글자 수. 근거 없는 처음 값이다.
- `KEY_HIT_EPS = 30`: 화 수 세기가 보는 최근 화 수. 근거 없는 처음 값이다. 시간 시험(아래 '시험')을 보고 고친다.

## 화면 · 명령줄 · 프롬프트

- 인물 카드(`cast.js`), 요소 카드(`causal.js`), 복선 카드(`foreshadow.js`)에 '키워드 제안' 버튼을 둔다.
- 제안은 종류별(찾는 키 · 보조 키 · 제외 키)로 칩을 보이고, 칩마다 체크 칸과 '12개 화에서 켜져요' 같은 화 수를 단다.
- 제외 키 칩은 '3개 화에서 꺼져요'로 적는다.
- 겹치는 키는 '‹다른 항목›의 이름과 같아요'라고 적는다.
- 고른 칩을 넣은 뒤에는 화면 아래 저장 띠의 작품 저장으로 저장한다.
- 단계 이름 '반영'은 쓰지 않는다. 제안을 받아들이는 동작은 '적용'이다.
- 문구 예: '키워드를 제안받았어요', '고른 키워드를 적용했어요', '근거가 없어 뺀 키워드가 2개 있어요'.
- 프롬프트는 쓰기 프롬프트(`build_episode_context`)에 들어가지 않는다. 그래서 `context.BUDGET` 키를 더하지 않는다.
- 작업지시서(`brief_parts`)에는 넣지 않는다. 설정 제안(`suggest_body`)처럼 화면 전용이다.
- 명령줄은 더하지 않는다(정할 것 8).

## 시험

- 새 시험 `tests/test_keys.py`: `clean` 의 각 규칙(두 글자, 이름과 같음, 겹침, 자기 이름을 끄는 제외 키, 없는 항목), `hits` 가 켜지고 꺼지는 화를 맞게 세는지.
- 같은 파일: mock 으로 `suggest_keys` 를 불러 저장하지 않는지(작품 파일이 바뀌지 않음).
- 같은 파일: 단편 작품에서도 제안과 화 수 세기가 도는지.
- 같은 파일: 화가 많은 장편 작품(측정 작품과 같은 87화를 mock 으로 만든 것)에서 항목 하나의 `hits` 가 정한 시간 안에 끝나는지, `context.activate` 를 항목마다 두 번만 부르는지.
- 웹: `POST /api/projects/{name}/keys/{target}` 와 작업 `keys`(`targets` 인자)가 `client` fixture 로 도는지, 없는 `target` 은 404 인지.
- 에이전트(`tests/test_agent.py` 꼴): `permit` 이 모드와 `keys_new` · `keys` · `keys_remove` 에 따라 맞게 정하는지, '모두 자동'에서도 `keys_remove` 는 묻는지.
- 같은 꼴: 바로 쓴 키를 되돌리면 전 값으로 돌아가는지, 작가가 그 사이 고친 항목은 되돌리지 않는지, 에이전트가 `Character` 설정 칸과 `StoryElement.aliases` 를 바꾸지 않는지.
- `tests/test_schema_nodict.py` 가 `KeySuggestion` 을 함께 보는지 확인한다.
- `canon/mock_keys.py` 를 더했으니 `tests/test_agents_docs.py` 가 새 파일 이름을 찾는지 본다.
- 전체 시험: `CANON_HOME=$(mktemp -d) python -m pytest -q -n auto tests`.
- 정적 검사: `ruff check canon tests scripts`.
- Swift 개발이 멈춰 있어 `python scripts/make_openapi.py` 는 돌리지 않는다(AGENTS.md).

## 문서

- `docs/modules/story.md`: 새 절 `### canon/keys.py`, `### canon/agent.py` 에 `read_keys` · `edit_keys` · 쓰기 종류 `keys_new` · `keys` · `keys_remove` 줄, `cast.js` · `causal.js` · `foreshadow.js` 절에 제안 버튼 줄.
- `docs/modules/core.md`: `prompts.py` 절에 `key_prompt`, `pipeline.py` 절에 `suggest_keys`, `schema.py` 절에 새 모델, `web.py` 절에 엔드포인트와 작업 `keys`.
- `docs/modules/ai.md`: `canon/mock.py` 절의 가짜 응답 파일 목록에 `mock_keys.py` 를 가나다 · 알파벳 차례로 한 줄.
- README.md: 인물 · 인과율 · 복선 화면 설명에 키워드 제안 한 줄.
- DESIGN.md: 컨텍스트 조립 장의 활성 조건 설명 뒤에 '키워드는 AI 가 제안하고 작가가 적용한다' 한 줄.
- 이 폴더의 [plan.md](../plan.md) 4번 상태와 [README.md](../README.md) 의 정한 규칙.

## 확인하지 못할 것

- 실제 Gemini 호출로 제안 품질과 응답 크기를 보는 것은 키가 있을 때만 한다. 비용 규칙(AGENTS.md '비용 드는 모델 실험') 안에서 1~2회로 시작한다.
- 제안된 키가 판정을 실제로 낫게 하는지는 1번 측정의 대리 지표로만 본다. 그 대리 지표는 이름과 다른 이름만 쓰므로, 제안된 키가 찾은 항목이 실제로 나왔는지는 지표로 알 수 없다. 사람이 표본을 읽어 확인한다.
- 작가가 칩을 고르는 화면이 편한지는 작가가 직접 써 봐야 안다.

### 시작 전에 확인할 것

- 이 문서의 키 이름은 02 의 `Activation.keys` · `secondary_keys` · `exclude_keys` 를 따른다. 머지된 2번 일감의 이름이 다르면 이 문서를 먼저 고친다.
- 2번 일감의 판정 함수(`context.activate`)와 낱말 맞추기 함수의 이름, 키를 더한 `Activation` 을 넘겨 결과를 미리 볼 수 있는 꼴인지.
- 1번 측정이 정한 판정 글 범위(Q9).
- `PlotAgentStep` 에 칸을 더하면 에이전트 단계 프롬프트가 얼마나 커지는지. 칸 설명을 짧게 둔다.

## 비용

- 키워드 제안은 새 LLM 호출이다. 단계는 정할 것 1 을 따른다.
- 시험은 가짜 응답(`canon/mock_keys.py`)만 쓴다.
- 처음 값(`KEY_BATCH` · `KEY_SAMPLE`)을 고치는 실호출 1~2회는 AGENTS.md '비용 드는 모델 실험' 규칙 안에서 돌린다. 돌리기 전에 `python -m canon usage --prices` 로 어림한다.
- 모델별 호출 수와 쓴 비용을 PR 에 적는다.

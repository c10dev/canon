# 호환 대응표

Canon 의 활성화 · 정규식 규칙 · 읽기 매크로를 Character Card V3(이하 CCv3) 로어북과 RisuAI 의 같은 기능에 1:1 로 맞춘 표다.
2026-11-08 에 사용자와 정한 Q26(a)에 따라 Canon 필드 이름은 Canon 것을 그대로 쓴다.
이 문서는 뜻만 맞춰 둔다.
가져오기 · 내보내기 코드는 지금 범위 밖이다(Q1 의 E, Q26).
이 표는 나중에 그 코드를 쓸 때 바로 옮길 수 있게 하려고 둔다.

관련 일감은 [plan.md](plan.md) 의 2번(활성화), 5번(CBS 읽기 매크로), 6번(정규식 규칙 묶음), 7번(선언형 규칙)이다.
각 일감의 명세서가 필드 이름을 바꾸면 같은 변경 안에서 이 표도 고친다.

## 용어

이 폴더의 다른 문서와 같은 이름을 쓴다.

| 용어 | 뜻 |
|---|---|
| 활성화 묶음(`Activation`) | 항목마다 붙는 활성화 설정 묶음. 활성화는 항목을 이번 화 프롬프트에 넣을지 판정하는 일이다. `StoryElement` · `Character` · 복선 · 사실이 함께 쓴다(Q7) |
| 키워드 | 활성화를 일으키는 낱말. 이름, 다른 이름, 찾기만 하는 키워드(`activation.keys`), 보조 키, 제외 키를 모두 이른다 |
| 보조 키 | 키워드가 맞은 뒤 함께 맞아야 하는 낱말 목록(AND, Q8) |
| 제외 키 | 하나라도 맞으면 활성화를 막는 낱말 목록(Q8) |
| 재귀 | `activation.recursive` 를 켠 항목의 글에서 다른 항목의 키워드를 한 번 더 찾는 것(한 단계, Q8) |
| 유지 | 키워드가 맞은 뒤 N화 동안 활성화를 이어 가는 것(Q8 의 sticky, `activation.sticky_episodes`) |
| 조건 | 상태창 값 · 관계 수치 · 화 번호 · 복선 상태 · 플롯 등장 여부를 보는 식. 활성화와 선언형 규칙이 함께 쓴다(Q27) |
| 정규식 규칙 | 본문에 정규식을 맞춰 경고하거나 고치는 규칙(Q12) |
| 규칙 묶음 | 정규식 규칙을 모은 전역 묶음. 작품마다 켤 묶음을 고른다(Q21) |
| 경고(`warn`) | 맞은 곳을 검수 결과와 함께 보이고 본문은 바꾸지 않는 동작 |
| 고침(`fix`) | 맞은 곳을 정해진 대로 바꾸는 동작. 작가가 보기 전에 적용하고 기록해 되돌릴 수 있다 |
| 읽기 매크로 | 값을 읽어 그 자리에 넣기만 하는 `{{함수::인자}}` 표기(Q11). 조건문과 값 쓰기는 없다 |
| 날것 보관 | Canon 이 쓰지 않는 원본 값을 잃지 않게 따로 적어 두는 것 |

## 원칙

- Canon 필드 이름은 바꾸지 않는다. CCv3 · RisuAI 이름은 이 표에만 적는다(Q26).
- RisuAI 생각은 Canon 의 구조화 데이터와 승인 흐름으로 옮긴 꼴로만 들어온다(Q2).
- Canon 이 받지 않는 기능(확률, N화마다, 정규식 키워드, 깊이 · 자리 지정)은 가져올 때 버리지 않고 날것 보관하거나 경고한다.
- 가져온 값이 Canon 의 활성화 판정을 몰래 바꾸지 않게 한다. 뜻이 다른 값은 옮기지 않고 경고한다.
- 판정은 `canon/context.py` 한 곳에서만 한다(Q7). 대응표는 판정 규칙을 새로 만들지 않는다.

## 1. 활성화 대응표

Canon 열의 이름은 [02 명세서](specs/02-activation.md) 의 '데이터 · 스키마' 절 이름이다.
`activation.` 으로 시작하는 이름은 `StoryElement` · `Character` · `Foreshadow` 의 `activation` 필드(`Activation` 모델) 안의 칸이다.
지금 있는 필드는 `canon/schema.py` 의 `StoryElement`(name, aliases, description, context, since_ep, episodes, reveal_ep, characters)와 `Character`(name, context)다.
`Character` 에는 지금 다른 이름 필드가 없다.
인물은 `context.name_pattern` 이 이름에서 조사를 가려 찾는다.
CCv3 열은 [SPEC_V3.md](https://github.com/kwaroran/character-card-spec-v3/blob/main/SPEC_V3.md) 의 'Lorebook Fields' · 'entries Fields' · 'Decorators' 절이다.
RisuAI 열은 RisuAI 저장소 `src/ts/storage/database.svelte.ts` 의 로어북 항목 형식과 `src/ts/process/lorebook.svelte.ts` 의 처리, `src/ts/characterCards.ts` 의 CCv3 가져오기 · 내보내기다.
RisuAI 열의 동작은 아직 커밋 해시와 함께 다시 확인하지 않았다('시작 전에 확인할 것' 7).

### 1-1. 로어북 전체 설정

| Canon | CCv3 로어북 | RisuAI | 가져올 때 할 일 |
|---|---|---|---|
| (작품 이름 · 설명과 따로 없음) | `name` · `description` | 캐릭터 · 모듈 이름 | 묶음 이름으로만 보인다. 프롬프트에 넣지 않는다(CCv3 도 `description` 은 프롬프트에 쓰지 않는다) |
| 찾는 범위: 측정(Q9)으로 정하는 작품 공통 범위 | `scan_depth` | `loreSettings.scanDepth` | 옮기지 않는다. 메시지 수와 Canon 의 플롯 · 직전 화 범위는 뜻이 달라 경고한다 |
| 블록 예산: `context.BUDGET` 과 작품별 블록 예산(Q10) | `token_budget` | `loreSettings.tokenBudget` | 옮기지 않는다. 토큰과 글자 수는 단위가 달라 경고만 한다 |
| 재귀: 항목마다 `activation.recursive` (Q8) | `recursive_scanning` | `loreSettings.recursiveScanning` | 옮기지 않는다. `false` 면 묶음 안 모든 항목의 `activation.recursive` 를 False 로 둔다. `true` 나 비어 있을 때는 '정할 것' 11 |
| (없음) | `extensions` | (RisuAI 확장) | 날것 보관 |

### 1-2. 항목 필드

| Canon | CCv3 항목 | RisuAI 항목 | 받나 | 가져올 때 할 일 |
|---|---|---|---|---|
| `name` | `name` · `comment` | `comment` | 받음 | `name` 이 있으면 쓰고 없으면 `comment` 를 쓴다(RisuAI 가져오기와 같은 차례) |
| `description` (요소) 또는 인물 설정 필드 | `content` | `content` | 받음 | 요소는 `description` 에 넣는다. 인물 설정으로 나누지 않는다. 앞머리의 데코레이터 줄은 떼어 아래 1-3 표로 읽는다 |
| `name` + `activation.keys` | `keys` | `key` (쉼표로 나눈 글) | 받음 | 첫 키가 이름과 같으면 빼고 나머지를 `activation.keys` 에 넣는다. `aliases` 에는 넣지 않는다(프롬프트에 '다른 이름'으로 찍히므로, 02 정할 것 1). RisuAI 는 쉼표로 나누고 앞뒤 빈칸을 지운다 |
| `context == "always"` | `constant` | `alwaysActive` · `mode: "constant"` | 받음 | `always` 로 넣는다 |
| `context == "off"` | `enabled: false` | (필드 없음) | 받음 | `off` 로 넣는다. RisuAI 는 이 필드가 없어 내보낼 때 늘 `true` 를 쓴다 |
| `activation.secondary_keys` | `selective` + `secondary_keys` | `selective` + `secondkey` | 받음 | `selective` 가 참일 때만 옮긴다. 보조 키 안에서는 하나만 맞아도 된다(02 정할 것 4) |
| `activation.exclude_keys` | 데코레이터 `@@exclude_keys` | 같은 데코레이터 | 받음 | 하나라도 맞으면 막는다. 뜻이 같다 |
| 유지 `activation.sticky_episodes` (N화) | 데코레이터 `@@keep_activate_after_match` | 같은 데코레이터 | 일부 | CCv3 는 한 번 맞으면 끝까지 이어 간다. Canon 은 N화로 끊는다. 아래 '정할 것' 2 |
| `since_ep` (지금 있음) | 데코레이터 `@@activate_only_after` | 같은 데코레이터 | 안 받음 | 메시지 수와 화 번호는 뜻이 달라 옮기지 않는다. 날것 보관하고 경고한다 |
| `activation.conditions` (Q27) | (없음) | (로어북에는 없음) | Canon 만 | 가져올 값이 없다. 내보낼 때는 '정할 것' 4. RisuAI 트리거는 1-6 |
| `activation.recursive` | (명세 데코레이터 없음) | `@@recursive` · `@@unrecursive` · `@@no_recursive_search` | 일부 | 1-3 표의 재귀 데코레이터 줄을 따른다 |
| (없음, 우선순위를 두지 않음, Q17) | `insertion_order` · `priority` | `insertorder` | 안 받음 | 블록 차례는 `prompts.py` 가 정하고 예산을 넘으면 활성 이유 차례로 뺀다(Q17). 날것 보관한다 |
| (없음, Q8) | `use_regex` | `useRegex` | 안 받음 | 키를 정규식으로 맞추지 않는다. 날것 보관하고 항목은 `off` 로 넣고 경고한다 |
| (없음) | `case_sensitive` | `extentions.risu_case_sensitive` | 안 받음 | `false` 나 비어 있으면 버린다. `true` 면 날것 보관하고 경고한다('정할 것' 5) |
| (없음) | `position` | (대응 없음) | 안 받음 | 블록 자리는 고정이다(Q10). 날것 보관한다 |
| (없음) | `id` | `id` | 안 받음 | Canon 은 새 id 를 만든다. 원래 id 는 날것 보관한다 |
| (없음) | (없음) | `mode: "folder"` · `"child"` · `"multiple"` | 안 받음 | 폴더 항목은 넣지 않는다. 나머지는 날것 보관하고 경고한다 |
| (없음, Q8) | (없음) | `activationPercent` | 안 받음 | 비었거나 100 이면 버린다. 그 밖의 값은 날것 보관하고 경고한다 |
| (없음) | `extensions` | `extentions` | 안 받음 | 날것 보관 |

### 1-3. 본문 데코레이터

CCv3 데코레이터는 `content` 앞머리의 `@@이름 값` 줄이다.
모르는 데코레이터는 무시하는 것이 CCv3 규칙이다.
Canon 은 무시하지 않고 날것 보관해 경고 목록에 이름을 보인다.

| 데코레이터 | 뜻 (CCv3 · RisuAI) | Canon | 가져올 때 할 일 |
|---|---|---|---|
| `@@additional_keys a,b` | 여러 번 쓸 수 있고 줄마다 함께 맞아야 하는 키 묶음이 하나씩 붙는다 | `activation.secondary_keys` (묶음 하나) | 한 줄이고 `activation.secondary_keys` 가 비었으면 옮긴다. 묶음이 둘 이상이면 날것 보관하고 경고한다 |
| `@@exclude_keys a,b` | 하나라도 맞으면 끈다 | `activation.exclude_keys` | 옮긴다 |
| `@@exclude_keys_all a,b` | (RisuAI 확장) 모두 맞을 때만 끈다 | (없음) | 날것 보관, 경고 |
| `@@keep_activate_after_match` | 한 번 맞으면 그 뒤 계속 켠다 | 유지 `activation.sticky_episodes` | '정할 것' 2 |
| `@@dont_activate_after_match` | 한 번 맞으면 그 뒤 계속 끈다 | (없음) | 날것 보관, 경고 |
| `@@activate` | 키를 보지 않고 켠다 | `context == "always"` | `always` 로 옮긴다 |
| `@@dont_activate` | 키를 보지 않고 끈다 | `context == "off"` | `off` 로 옮긴다 |
| `@@activate_only_after N` | 메시지 N개 전에는 끈다 | (없음, `since_ep` 와 뜻이 다름) | 날것 보관, 경고 |
| `@@activate_only_every N` | N번마다 켠다 | (없음, Q8 에서 받지 않음) | 날것 보관, 경고 |
| `@@probability N` | N% 확률로 켠다 (RisuAI) | (없음, Q8 에서 받지 않음) | 100 이면 버리고 그 밖은 날것 보관, 경고 |
| `@@recursive` | 이 항목의 글을 재귀 출처로 쓴다 (RisuAI) | `activation.recursive = True` | 옮긴다 |
| `@@unrecursive` | 이 항목의 글을 재귀 출처로 쓰지 않는다 (RisuAI) | `activation.recursive = False` (기본값) | 기본값과 같아 날것 보관만 한다 |
| `@@no_recursive_search` | 재귀로 찾은 글에서는 이 항목을 찾지 않는다 (RisuAI) | (없음) | 날것 보관, 경고 |
| `@@depth N` · `@@reverse_depth N` · `@@instruct_depth N` · `@@reverse_instruct_depth N` | 대화 안 몇 번째 자리에 넣을지 | (없음, 블록 자리 고정, Q10) | 날것 보관, 경고 |
| `@@position 값` · `@@role 값` | 어느 칸 앞뒤에, 어떤 역할로 넣을지 | (없음, 블록 자리 고정) | 날것 보관, 경고 |
| `@@scan_depth N` · `@@instruct_scan_depth N` | 이 항목만 찾는 범위를 바꾼다 | (없음, 범위는 측정으로 정한 작품 공통, Q9) | 날것 보관, 경고 |
| `@@ignore_on_max_context` | 예산이 차면 먼저 뺀다 | (없음, 빼는 차례는 활성 이유, Q17) | 날것 보관 |
| `@@priority N` | 우선순위 (RisuAI) | (없음, Q17) | 날것 보관 |
| `@@is_greeting N` · `@@is_user_icon 이름` · `@@disable_ui_prompt 값` | 대화 앱 전용 | (없음, 대화 모드를 들이지 않음, Q1 의 D) | 날것 보관 |
| `@@inject_lore` · `@@inject_at` · `@@inject_replace` · `@@inject_prepend` · `@@match_full_word` · `@@match_partial_word` · `@@end` | RisuAI 전용 | (없음) | 날것 보관, 경고 |
| `@@@` 대체 줄 | 앞 데코레이터가 안 될 때 쓰는 대체 값 | (없음) | 앞 줄과 함께 날것 보관한다 |

### 1-4. 내보낼 때

- 키워드: `keys` 에 `name`, `aliases`, `activation.keys` 를 이 차례로 넣는다.
- Canon 은 이름을 따로 적지 않아도 맞추므로 내보낼 때 이름을 첫 키로 꼭 넣는다.
- 내용: 요소는 `canon/elements.py` 의 `describe` 한 줄, 인물은 프롬프트에 넣는 설정 직렬화와 같은 글로 `content` 를 만든다.
- 보조 키는 `selective` + `secondary_keys` 로 쓴다.
- 제외 키는 `@@exclude_keys` 줄로 쓴다.
- `activation.recursive = True` 는 `@@recursive` 줄로 쓴다.
- `context == "always"` 는 `constant: true` 로 쓴다.
- `context == "off"` 는 `enabled: false` 로 쓴다.
- 날것 보관한 값은 원래 자리로 되돌려 쓴다.
- Canon 에만 있는 값(`activation.sticky_episodes`, `activation.conditions`, `since_ep`, `episodes`, `reveal_ep`)은 '정할 것' 4 를 따른다.

### 1-5. 항목 종류

- 가져오기는 로어북 항목을 모두 `StoryElement` 로 넣는다.
- 가져온 항목의 `kind` 는 '정할 것' 12 를 따른다.
- 인물(`Character`)로 나누어 넣지 않는다. 인물 카드의 설정은 이 표의 범위 밖이다.
- 복선(`Foreshadow.activation`)과 사실(`Project.fact_activations`)도 활성화를 쓴다(Q7, 02 명세서).
- 복선과 사실을 내보낼지, 어떻게 내보낼지는 '정할 것' 13 을 따른다.
- 사실을 내보낸다면 `FactActivation.text` 는 `content` 에, `FactActivation.context == "always"` 는 `constant` 에 맞는다(02 정할 것 16 의 추천안).

### 1-6. 트리거

- RisuAI 트리거(triggerscript · Lua)는 Canon 에 대응이 없다(Q13).
- 가져올 때 트리거는 날것 보관하고 경고한다.
- 트리거의 뜻은 작가가 선언형 규칙([07 명세서](specs/07-rules.md))으로 옮겨 적는다.

## 2. 정규식 규칙 대응표

Canon 정규식 규칙 모델은 RisuAI regex script 필드(in, out, type, flag)를 따르고 Canon 동작 필드 하나를 더한다(Q26).
Canon 열의 이름은 [06 명세서](specs/06-regex-rules.md) 의 `RegexRule` 이름이다.
RisuAI 형식은 `src/ts/storage/database.svelte.ts` 의 스크립트 형식(comment, in, out, type, flag, ableFlag)과 `src/ts/process/scripts.ts` 의 처리다.
CCv3 명세에는 정규식 스크립트가 없다.

### 2-1. 필드

| Canon | RisuAI | 뜻 | 가져올 때 할 일 |
|---|---|---|---|
| `in_` (JSON 키 `in`) | `in` | 찾을 정규식 | 옮긴다. 비었으면 RisuAI 처럼 그 규칙을 건너뛴다. 문법 차이는 2-3 |
| `out` | `out` | 바꿀 글 (JavaScript 꼴로 저장, 06 정할 것 4) | 옮긴다. 경고 규칙에서는 쓰지 않고 보관만 한다. 표기 차이는 2-3 |
| `type` (`output` \| `export`) | `type` | 언제 쓰는지 | 2-2 표대로 바꿔 넣는다 |
| `flag` | `flag` | 정규식 플래그 | 2-3 표대로 옮긴다 |
| (대응 없음, Canon 은 늘 `flag` 를 읽는다) | `ableFlag` | `flag` 를 쓸지 | 거짓이면 `flag` 를 `g` 로 바꿔 넣는다 |
| `comment` | `comment` | 규칙 이름 | 옮긴다. 경고가 검수 결과에 보일 때 이 이름을 쓴다 |
| `action` (`warn` \| `fix`) | (대응 없음) | Canon 동작(Q12) | `warn` 으로 넣는다(06 의 기본값). 원래 바꾸는 규칙이었다는 사실은 날것 보관에 적고, 작가가 `fix` 로 바꾼다 |
| `enabled` | (대응 없음) | 묶음 안에서 이 규칙만 끈다 | 기본 `True`. 아래 표들이 '꺼 둔 채'라고 한 규칙만 `False` 로 넣는다 |
| `id` | (대응 없음) | 기록 · 지적이 가리키는 이름 | 새로 만든다 |

- 바꿀 글에 `{{` 가 들었으면 규칙을 꺼 둔 채 넣는다(2-3).
- `type = "export"` 규칙은 `warn` 을 저장할 수 없다(06 명세서). 이 규칙은 `fix` 로 두고 꺼 둔 채 넣는다.

규칙 묶음은 문체 라이브러리처럼 전역에 두고 작품이 켤 묶음을 고른다(Q21).
묶음 하나가 RisuAI 의 스크립트 목록 하나에 맞는다.

### 2-2. type

| RisuAI `type` | RisuAI 에서 언제 | Canon | 가져올 때 할 일 |
|---|---|---|---|
| `editoutput` | 모델 출력을 받은 뒤 | `type = "output"`: 본문 생성 직후 작가가 보기 전에 건다(Q21). 다시 생성 · 부분 고치기 출력과 자동 집필도 같다 | `output` 으로 넣는다 |
| `editdisplay` | 화면에 보일 때만, 저장 글은 그대로 | `type = "export"`: 내보내기(`publish.export`)에서만 건다(06 정할 것 9) | `export` 로 넣는다. 2-1 의 `export` 줄을 따른다 |
| `editinput` | 사용자 입력을 보내기 전 | 대응 없음 (Canon 에 대화 입력이 없다) | 넣지 않는다. 날것 보관하고 경고한다 |
| `editprocess` | 요청을 만들 때 프롬프트에 | 대응 없음 (블록 문구는 `prompts.py` 고정, Q10) | 넣지 않는다. 날것 보관하고 경고한다 |

### 2-3. 문법 차이

RisuAI 는 JavaScript 정규식이고 Canon 은 Python `re` 다.
같은 글이라도 뜻이 다를 수 있다.
Canon 은 `out` 을 JavaScript 꼴로 저장하고 `regexrules.to_python` 이 Python 꼴로 바꾼다(06 정할 것 4).

| 항목 | RisuAI (JavaScript) | Canon (Python) | 가져올 때 할 일 |
|---|---|---|---|
| `g` | 모두 바꿈. 없으면 첫 하나만 | `re.sub` 의 `count=0` / `count=1` | 옮긴다 |
| `i` | 대소문자 무시 | `re.IGNORECASE` | 옮긴다 |
| `m` | 줄마다 `^` `$` | `re.MULTILINE` | 옮긴다 |
| `s` | `.` 이 줄바꿈도 맞춤 | `re.DOTALL` | 옮긴다 |
| `u` | 유니코드 | Python 문자열은 늘 유니코드 | 버린다 |
| `d` | 자리 정보 | 대응 없음 (06 은 무시한다. Canon 은 자리를 늘 센다) | `flag` 에서 떼고 버린다 |
| `y` · `v` | 붙여 찾기 · 집합 표기 | 대응 없음 (06 은 저장할 때 막는다) | `flag` 에서 떼어 날것 보관하고, 규칙을 꺼 둔 채 넣고 경고한다 |
| `flag` 안의 `<...>` 조각 | `order N` 과 동작 이름(`cbs`, `move_top` 등) | 받지 않음 (차례는 목록 차례, 06 정할 것 5) | `flag` 에서 뗀다. `<order N>` 은 목록 차례로 옮긴다. 나머지는 날것 보관하고 경고한다 |
| 바꿀 글의 `$1` · `$<이름>` | 묶음 번호 · 이름 붙은 묶음 | `\g<1>` · `\g<이름>` | 그대로 저장한다. `to_python` 이 `\g<N>` 으로 바꿔 `\1` 뒤에 숫자가 오는 모호함을 피한다 |
| 바꿀 글의 `$&` | 맞은 글 전체 | `\g<0>` | 그대로 저장한다 |
| 바꿀 글의 `$$` | 달러 하나 | `$` | 그대로 저장한다. `to_python` 이 `$` 로 바꾼다 |
| 바꿀 글의 `\` | 글자 그대로 | `re.sub` 바꿀 글에서는 이스케이프 | 그대로 저장한다. `to_python` 이 `\\` 로 바꾸거나, 바꿀 글을 함수 치환으로 풀어 Python 이스케이프를 피한다 |
| 바꿀 글의 `$n` | RisuAI 는 줄바꿈으로 바꾼다 | 받지 않음 (06 정할 것 4) | 가져올 때 줄바꿈 글자로 옮겨 적는다 |
| `@@` 로 시작하는 바꿀 글 | RisuAI 특수 명령 | 받지 않음 (06 은 저장할 때 막는다) | 넣지 않는다. 날것 보관하고 경고한다 |
| 바꿀 글 안의 `{{...}}` | RisuAI 는 바꾼 뒤 CBS 를 푼다 | '정할 것' 7 | 그대로 두고 규칙을 꺼 둔 채 넣고 경고한다 |
| 이름 붙은 묶음 `(?<이름>...)` · 뒤 보기 등 | JavaScript 문법 | Python 문법과 다를 수 있음 | '시작 전에 확인할 것' 2 |

`re.compile` 이 실패하는 규칙은 넣지 않고 날것 보관하고 경고한다(06 은 컴파일 오류를 저장할 때 막는다).
`fix` 규칙은 정해진 결과만 내야 하므로(Q12) 바꿀 글에 무작위나 시간 값이 들어가면 안 된다.

## 3. CBS 읽기 매크로 대응표

Canon 은 RisuAI CBS 이름을 쓴다(Q20).
값을 읽기만 하고 조건문과 값 쓰기는 없다(Q11).
표기는 `{{함수::인자}}` 이다.
RisuAI 는 인자를 `::` 로 나눈다(`src/ts/cbs.ts`).
CCv3 명세의 CBS 절은 `{{random:A,B}}` 처럼 `:` 하나를 쓴다.
이 차이는 '시작 전에 확인할 것' 3.

| CBS | RisuAI 뜻 | Canon 뜻 (Q25) | Canon 이 읽는 곳 |
|---|---|---|---|
| `{{user}}` | 사용자 이름 | 주인공 이름 | `opening.hero_name` 규칙([05 명세서](specs/05-macros.md)): 역할에 '주인공'이 든 인물, 없으면 첫 `tier == "main"` 인물 |
| `{{char}}` (`{{bot}}`) | 지금 캐릭터의 별명, 없으면 이름 | 항목에 이어진 인물. 없으면 이번 화 시점 인물. `EpisodePlot.pov` 가 비면 주인공(05 정할 것 9) | `StoryElement.characters` 의 첫 인물, `prompts.pov_character(p, n)` |
| `{{getvar::인물.스탯}}` | 대화 변수 읽기 | 상태창 값 | `Project.state_of(인물 id)` 의 `stats` 에서 `name` 이 같은 값 |
| 화 번호 함수 | (`{{chatindex}}` 는 메시지 번호) | 이번 화 번호 | 이름은 '정할 것' 9 |
| `{{setvar::...}}` · `{{addvar::...}}` · `{{setdefaultvar::...}}` | 대화 변수 쓰기 | 값을 쓰지 않는다 | 경고만 하고 글은 그대로 둔다 |
| `{{#when::...}}` 블록 | 조건문 | 받지 않는다 | 그대로 두고 경고한다 |
| `{{random::...}}` · `{{pick::...}}` · `{{roll::...}}` | 무작위 고르기 | 받지 않는다(읽기 값이 아님) | 모르는 함수로 다룬다 |
| `{{// 글}}` · `{{comment::글}}` · `{{hidden_key::글}}` | 주석 · 사용자에게만 보임 · 재귀 찾기용 숨은 키 | 받지 않는다 | 모르는 함수로 다룬다. '정할 것' 10 |
| `{{reverse::...}}` · 그 밖의 함수 | RisuAI 함수 약 200개 | 받지 않는다 | 그대로 두고 경고한다(Q25) |

- `{{getvar::인물.스탯}}` 의 인물은 인물 id 나 이름이 똑같을 때 찾는다(05 정할 것 7). 이름을 못 찾거나 그 스탯이 없으면 빈 글로 바꾸지 않고 그대로 두고 경고한다.
- 관계 수치 · 복선 상태처럼 조건(Q27)이 보는 값은 매크로로 읽지 않는다. 조건이 맡는다.
- 매크로는 항목 글을 블록에 넣을 때 푼다(`elements.describe` 등에 `env` 를 넘긴다, 05 명세서).
- 매크로는 블록 문구에는 쓰지 않는다(Q10).
- `static_context` 안의 글(`Meta.notes`)에서는 화마다 같은 값(`{{user}}`)만 펼친다(05 정할 것 11).

## 4. 라이선스

- RisuAI(github.com/kwaroran/RisuAI)는 GPL-3.0 이다. Canon 은 생각과 공개 데이터 형식만 쓴다(Q4).
- RisuAI 코드와 기본 프롬프트 글은 옮기지 않는다. 이 문서도 파일 경로와 필드 이름만 적고 코드를 옮기지 않았다.
- 이 문서가 읽은 RisuAI 판은 v2026.10.294 다. 커밋 해시는 적지 않았다('시작 전에 확인할 것' 7).
- 읽은 RisuAI 파일: `src/ts/process/lorebook.svelte.ts`, `src/ts/process/scripts.ts`, `src/ts/cbs.ts`, `src/ts/storage/database.svelte.ts`, `src/ts/characterCards.ts`.
- CCv3 명세(github.com/kwaroran/character-card-spec-v3, `SPEC_V3.md`)는 MIT 다. 필드 이름과 데코레이터 이름은 이 명세를 따른다.
- 가져오기 · 내보내기 코드의 CCv3 필드 해석은 CCv3 명세만 보고 쓴다.
- RisuAI 전용 필드(`mode`, `folder`, `activationPercent`, `extentions.risu_case_sensitive`, `ableFlag`)는 이 표의 뜻만 쓴다. 그 뜻은 '시작 전에 확인할 것' 7 에서 다시 확인한다.

## 정할 것

가져오기 · 내보내기 일감이나 관련 일감(2 · 5 · 6번)을 시작할 때 사용자와 정한다.
추천안을 먼저 쓴다.

1. 날것 보관 자리
   - 추천: 지금은 필드를 더하지 않는다. 가져오기 일감에서 항목마다 JSON 글을 담는 문자열 필드 하나를 `SkipJsonSchema` 로 둔다.
   - 이유: LLM 이 채우는 스키마에 dict 필드를 쓰지 않는 규칙(AGENTS.md)을 지킨다.
2. `@@keep_activate_after_match` 를 `activation.sticky_episodes` 로 어떻게 옮길지
   - 추천: 옮기지 않고 날것 보관하고, 가져온 뒤 작가가 N 을 정하게 경고 문구로 알린다.
   - 이유: 아주 큰 N 으로 바꾸면 Q17 의 빼는 차례를 흐린다.
3. `use_regex` 항목
   - 추천: 1-2 표처럼 `off` 로 넣고 경고한다.
   - 이유: 키를 글자 그대로 바꿔 켜면 뜻이 달라진다.
4. Canon 에만 있는 활성화 값(`activation.sticky_episodes`, `activation.conditions`, `since_ep`, `episodes`, `reveal_ep`)을 내보낼 때
   - 추천: CCv3 `extensions.canon` 아래에 Canon 필드 이름 그대로 넣는다.
   - 이유: CCv3 는 `extensions` 를 앱마다 쓰라고 둔다.
5. 라틴 글자 이름의 대소문자
   - 추천: 대소문자를 가리지 않는다. `case_sensitive: true` 는 1-2 표대로 날것 보관하고 경고한다.
   - 이유: RisuAI 도 정규식이 아닌 키는 가리지 않는다.
   - 5번 일감의 매크로 이름도 CCv3 처럼 가리지 않는다.
6. `editdisplay` 규칙
   - 06 명세서가 `type = "export"` 와 그 정할 것 9 로 다룬다. 여기서 따로 정하지 않는다.
7. 정규식 규칙의 바꿀 글 안 매크로
   - 추천: 풀지 않는다.
   - 이유: `fix` 결과가 데이터에 따라 바뀌면 되돌리기 기록과 검수가 흐려진다.
8. `{{user}}` 의 주인공을 정하는 방법
   - 05 명세서가 `opening.hero_name` 규칙으로 정한다. 여기서 따로 정하지 않는다.
9. 화 번호 함수 이름
   - 추천: `{{episode}}` 로 한다.
   - 이유: 가져올 때 `{{chatindex}}` 는 메시지 번호라 뜻이 달라 바꾸지 않고 경고한다.
10. `{{// 글}}` 주석
    - 추천: 프롬프트에 넣을 때 지운다.
    - 이유: CCv3 가 지우라고 정한 표기라 경고만 남기면 작가 메모가 프롬프트로 샌다.
    - 05 명세서 정할 것 17 은 이번에는 지우지 않는 안을 추천한다. 둘을 함께 정한다.
11. 로어북 `recursive_scanning` 을 각 항목의 `activation.recursive` 로 어떻게 옮길지
    - 추천: `false` 면 모든 항목을 False 로 둔다. `true` 나 비어 있어도 `@@recursive` 가 있는 항목만 True 로 두고 경고한다.
    - 이유: CCv3 의 `true` 는 모든 항목을 재귀 출처로 쓴다. 모두 True 로 옮기면 가져오자마자 프롬프트가 커진다.
12. 가져온 로어북 항목의 `StoryElement.kind`
    - 추천: '기타'로 넣는다. 작가가 종류를 고른다.
    - 이유: CCv3 · RisuAI 항목에는 종류 필드가 없다.
13. 복선(`Foreshadow`)과 사실(`FactActivation`)을 내보낼 때
    - 추천: 이야기 요소와 같은 로어북 항목으로 내보내고, 어느 모델이었는지는 `extensions.canon` 에 적는다.
    - 이유: 다른 앱은 항목 종류를 모르지만, Canon 으로 다시 가져올 때 원래 모델로 되돌릴 수 있다.

## 시작 전에 확인할 것

1. RisuAI 가 모르는 CBS 함수를 어떻게 남기는지 확인한다. 파서(`src/ts/parser/parser.svelte.ts`)를 읽지 못했다.
2. JavaScript 정규식과 Python `re` 의 문법 차이(이름 붙은 묶음, 뒤 보기, 유니코드 속성 `\p{...}`)를 가져오기 시험 자료로 하나씩 확인한다.
3. RisuAI 가 `:` 하나로 쓴 CBS 인자를 받는지 확인한다. CCv3 명세 예와 RisuAI 표기가 다르다.
4. 두 저장소의 LICENSE 파일을 가져오기 코드를 쓰기 직전에 다시 본다.
5. RisuAI 데코레이터 해석은 바깥 라이브러리(CCardLib)가 한다. `@@@` 대체 줄과 겹친 데코레이터를 어떻게 다루는지 읽지 못했다.
6. CCv3 `position` 필드는 명세에 뜻이 없고 RisuAI 도 옮기지 않는다. 다른 앱이 쓰는 값이 있는지 가져오기 일감에서 본다.
7. 이 문서의 RisuAI 동작 설명은 커밋 해시 없이 판 번호만 남았다. 가져오기 일감을 시작할 때 읽은 파일과 커밋 해시를 적고 다시 확인한다.
   - 다시 볼 동작: `alwaysActive` · `mode: "constant"`, `ableFlag` 가 거짓일 때 `g`, 바꿀 글의 `$n` 줄바꿈, `activationPercent`, 쉼표로 나눈 `key`, 재귀 데코레이터 셋의 뜻, `type` 네 값의 적용 시점.

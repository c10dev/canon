# 10. 인물 표지

상태: 진행 (claude/cast-marks-22fd2d) · 계획: [plan.md](../plan.md) 의 10번 · 먼저: 11

## 목표

작가가 승인한 본문에서 독자가 인물을 알아보는 표지(말버릇 · 버릇 · 외모 특징)를 골라 인물 카드에 기록한다.
표지는 AI 가 미리 지어 넣지 않는다. 본문을 쓰다 자연스럽게 생긴 것을 작가가 거둔다.
거둔 표지는 쓰기 요청에 넣지 않는다. 인물 화면의 기록으로만 쓴다.
이 일감은 [README.md](../README.md) 정한 규칙의 2026-11-14 줄(정할 것 14 · 15)과 'AI 느낌을 만드는 프롬프트' 절의 작가 동의(버릇은 승인한 본문에서 작가가 거둔다)를 따른다.
이야기 틀과 상관없이 모든 작품에 닿는다.

## 정할 것

정한 것(사용자, 2026-11-14):

- 정할 것 14 (정함 2026-11-14: 추천안대로): 인물 표지 칸은 모든 작품에 둔다. 비면 어디에도 넣지 않는다.
- 정할 것 15 (정함 2026-11-14: 추천안대로): 거둔 표지는 쓰기 요청에 넣지 않는다. 검수 · 인물 화면의 기록으로만 쓴다.

계획 세션이 추천안으로 진행하라고 한 것이다. 사용자가 다르게 정하면 고친다.

1. 표지의 꼴 — 추천: `Character.marks` 목록. 줄 하나는 [갈래(말버릇 · 버릇 · 외모), 글, 거둔 화, 근거 구절]이다. 프로그램과 작가만 채우는 칸이라 응답 형식에서 뺀다(`SkipJsonSchema`, `Character.body` · `aliases` 와 같다).
2. 거두는 자리 — 추천: 집필 화면에서 본문 대목을 고르면 뜨는 도구에 '인물 표지로 거두기'를 둔다. 반영한 화(`finalized`)에서만 뜬다. 인물 화면에서 거둔 표지를 보고 고치고 지운다.
3. AI 가 표지 후보를 뽑아 주는 기능 — 추천: 넣지 않는다. 작가가 거둔다는 방향과 어긋나고 새 LLM 호출 경로가 생긴다. 장기 후보로 둔다.
4. 불변 설정과의 경계 — 추천: 표지는 본문에서 본 사실의 기록이다. `appearance` · `personality` · `speech_style` 을 바꾸지 않는다. 설정 변경 기록(`setting_log`)에 남기지 않는다. 표지 줄이 스스로 화와 근거 구절을 품어 따로 기록할 것이 없다.
5. 검수가 표지를 볼지 — 추천: 이번에는 검수 프롬프트에 넣지 않는다. 인물 화면 기록까지만 한다. 넣는 일은 예산(`context.BUDGET`)과 함께 따로 정한다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/schema.py` | 새 모델 `CharMark`, `Character.marks`(`SkipJsonSchema`), `_prompt_view` 가 `marks` 를 뺌 |
| `canon/charmarks.py` | 새 파일: 더하기 · 고치기 · 지우기, 근거 구절 찾기, 화면 저장이 표지를 덮지 않게 디스크 값 지키기, 화 번호 옮기기 |
| `canon/renumber.py` | `move_points` 가 표지의 거둔 화를 옮김(`charmarks.move`) |
| `canon/prompts.py` | `cast_view` · `setup_chat_prompt` 의 `exclude` 에 `marks` |
| `canon/echoes.py` | `_canon_text` 가 표지를 빼고 인물 설정을 읽음 |
| `canon/pipeline.py` | 인용 근거 찾기(`_quoted` 의 설정 갈래)가 표지를 빼고 읽음 |
| `canon/web.py` | 표지 라우트 셋, `_put_locked` 가 디스크의 표지를 지킴 |
| `canon/cast.py` | 명령줄 `cast` 출력에 표지 줄 |
| `canon/static/passage.js` | 고른 부분 도구의 '인물 표지로 거두기'와 거두기 칸 |
| `canon/static/cast.js` | 인물 쪽의 표지 카드(보기 · 고치기 · 지우기, '본문에서 못 찾음') |
| `tests/test_char_marks.py` · `tests/test_char_marks_js.py` | 새 시험 |

`canon/mock.py` 는 고치지 않는다. 응답 형식이 바뀌지 않는다.

## 데이터 · 스키마

- `CharMark`
  - `id: str`: 인물 안에서 겹치지 않는 짧은 열쇠(`m` + 8자리 16진수)
  - `kind: Literal["말버릇", "버릇", "외모"] = "버릇"`
  - `text: str = ""`: 작가가 적은 한 줄. 비우고 거두면 근거 구절을 그대로 쓴다
  - `episode: int = 0`: 거둔 화
  - `quote: str = ""`: 근거가 된 본문 구절. 거둘 때 본문에서 찾은 글 그대로(`elements.find` 가 준 자리의 글)를 저장한다
- `Character.marks: SkipJsonSchema[list[CharMark]] = []`. 옛 `project.json` 은 고치지 않고 읽힌다.
- 글 길이 상한: `text` 200자, `quote` 400자(`charmarks.TEXT_MAX` · `QUOTE_MAX`). 표지는 한 줄 기록이라 길게 받지 않는다. 고른 부분 도구의 다른 동작에는 상한이 없다.
- dict 칸이 없다. 응답 형식에 들어가지 않는다(`Character.model_json_schema()` 에 `marks` 가 없다).

## 규칙

- 거두기는 반영한 화(`status == "finalized"`)에서만 된다. 일감 글의 '승인한 본문'이다. 다른 화는 400 '반영한 화에서만 표지를 거둘 수 있어요'.
- 근거 구절은 그 화의 저장된 본문에 있어야 한다(`elements.find`: 공백 · 줄바꿈 차이는 봐준다). 없으면 400.
- 화면은 저장하지 않은 본문이 있으면 먼저 저장한다. 서버는 저장된 본문으로 확인한다.
- 본문이 나중에 고쳐져 구절이 사라져도 표지는 지우지 않는다. 인물 화면과 명령줄이 '본문에서 못 찾음'으로 알린다.
- 반영 취소(`revert`) · 마지막 화 지우기(`delete_last`)도 표지를 지우지 않는다. 그 화 본문이 비면 '본문에서 못 찾음'이 된다.
- 고치기는 갈래와 글만 바꾼다. 거둔 화와 근거 구절은 바꾸지 않는다(근거를 바꾸려면 지우고 다시 거둔다).
- 인물 지우기는 그 인물의 표지도 함께 지운다(표지는 인물 칸이다). 인물 합치기 기능은 없다.
- 반영 취소로 인물 후보에 돌아간 인물은 표지를 그대로 가진다.
- 화면 저장(`PUT` · `PATCH /api/projects/{name}`)은 표지를 고치지 않는다. 디스크의 표지를 인물 id 로 지킨다(`charmarks.keep`). 표지는 표지 라우트로만 바뀐다. `state_log` · `address_forms` 와 같은 방식이다.
- 화 끼워 넣기 · 빼기는 거둔 화 번호를 한 화 번호처럼 옮긴다(`renumber.move_points` 의 `characters` 셈). 반영한 화는 옮길 수 없는 화(`last_fixed`)라 실제로는 옮길 일이 없다. 뺀 화를 가리키는 표지도 지우지 않는다.
- 설정 변경 기록(`setting_log`)에 남기지 않는다(정할 것 4). `charlog.LOG_FIELDS` 에 넣지 않는다.
- 설정 제안 적용(`apply_setup`)과 설정 대화 적용(`setupchat`)은 표지를 건드리지 않는다. 표지는 응답 형식에 없고 설정 대화의 칸 목록(`CHAR_FIELDS`)에도 없다.
- 대화 에이전트(`canon/agent.py`)는 표지를 쓰지 않는다. 표지 도구를 더하지 않는다.
- 자동 집필 · `-y` 와 상관없다. AI 가 표지를 만들지 않는다.
- 단편 · 장편 모두 같은 규칙이다.

## 화면 · 명령줄 · 프롬프트

### 프롬프트

- 표지는 어떤 요청에도 들어가지 않는다(정할 것 15).
- 빼는 곳: `Character._prompt_view`(프롬프트 직렬화), `cast_view`, `setup_chat_prompt` 의 인물 덤프.
- 프롬프트 직렬화를 거치지 않는 인물 덤프도 뺀다: `echoes._canon_text`(반복 검사의 '되풀이해도 되는 말'), `pipeline._quoted` 의 설정 갈래(인용 근거 찾기). 표지 구절이 이 둘에 들어가면 거둔 말버릇이 반복 경고에서 빠지거나, 본문 구절이 설정에 있는 것처럼 보인다.
- 다른 인물 덤프는 `include` 로 칸을 골라 표지가 들어가지 않는다.
- 응답 형식이 든 작업지시서(`brief`)도 그대로다. `SkipJsonSchema` 라 `Character` 스키마가 바뀌지 않는다.
- 새 블록이 없다. 예산은 바뀌지 않는다. 프롬프트 해시 스냅샷은 바뀌지 않는다.

### 웹 엔드포인트

- `POST /api/projects/{name}/characters/{cid}/marks` 몸 `{kind, text, episode, quote}` → `Project`
- `PUT /api/projects/{name}/characters/{cid}/marks/{mid}` 몸 `{kind, text}` → `Project`
- `DELETE /api/projects/{name}/characters/{cid}/marks/{mid}` → `Project`
- 없는 작품은 404다. 없는 인물 · 표지와 규칙에 어긋난 요청은 400 이다(다른 라우트처럼 `KeyError` · `ValueError` 를 400 으로 돌린다).
- 세 라우트 모두 작품 잠금 안에서 저장한다(`_edit`).

### 집필 화면

- 본문을 고르면 뜨는 도구(`passage.js` `showTool`)에 '인물 표지로 거두기'(`selMark`)를 둔다. 반영한 화에서만 보인다. 주 버튼이 아니다.
- 누르면 같은 도구가 거두기 칸으로 바뀐다: 인물 고르기, 갈래 고르기(말버릇 · 버릇 · 외모), 한 줄 글(비우면 고른 구절), 고른 구절 미리보기, '거두기' · '취소'.
- 인물 고르기의 처음 값은 고른 구절에 이름이 먼저 나오는 인물, 없으면 그 화 플롯의 첫 인물이다.
- 늘 보이는 버튼 · 안내 문장은 늘지 않는다. 도구는 고를 때만 뜨고 `<main>` 밖이다.

### 인물 화면

- 인물 쪽(`castCharPage`)의 설정 카드 뒤에 '표지' 카드(`castMarksCard`)를 둔다. 표지가 없으면 카드를 그리지 않는다(정할 것 14: 비면 어디에도 넣지 않는다).
- 줄 하나: 갈래 칩, 글, 'n화', 근거 구절(접어 보임), 찾지 못하면 '본문에서 못 찾음' 칩.
- 줄마다 '고치기'(갈래 · 글) · '지우기'(확인 창). 저장하지 않은 작품 변경이 있으면 먼저 저장한다(`castStateSave` 와 같다).
- '본문에서 못 찾음'은 화면이 가진 그 화 본문으로 정한다(`castMarkFound`, 서버 `charmarks.found` 와 같은 규칙: 공백을 한 칸으로 줄여 찾는다).

### 명령줄

- `cast <작품> <인물>` 출력의 설정 줄 뒤에 표지가 있으면 '표지' 줄을 더한다. 줄마다 `[갈래] 글 (n화)`, 찾지 못하면 '(본문에서 못 찾음)'.
- 새 명령은 없다.

### 디자인 문서

- `docs/design/components/` 에 새 컴포넌트를 더하지 않는다. 표지 카드는 인물 쪽의 기존 카드(`card pf-sec`)와 칩을 쓴다.
- `docs/design/layout.md` 의 인물 쪽 카드 차례에 표지 카드를 더한다.

## 시험

- `tests/test_char_marks.py`
  - 옛 작품이 표지 없이 읽히고, `Character.model_json_schema()` 에 `marks` 가 없다.
  - 표지 글과 근거 구절에 고유한 표시를 넣은 시험 작품(단편 · 장편)의 모든 요청 글(`test_prompt_registry._requests`)과 설정 대화 · 상태 변경안 요청이 표지를 넣지 않은 작품과 같고, 표시가 없다.
  - 더하기: 반영한 화만, 본문에 있는 구절만, 공백 차이를 봐주고 본문의 글 그대로 저장, 길이 상한, 빈 글은 구절로.
  - 고치기 · 지우기, 없는 인물 · 표지.
  - 본문을 고쳐 구절이 사라지면 표지는 남고 `found` 가 거짓.
  - 화면 저장이 표지를 덮지 않는다(옛 사본으로 저장, 표지를 지운 사본으로 저장).
  - 화 끼워 넣기 · 빼기가 거둔 화를 옮기고 되돌리면 같다(`move_points` 직접).
  - 반영 취소 · 마지막 화 지우기 뒤에도 표지가 남는다.
  - 설정 제안을 다시 적용해도 표지가 남는다.
  - 명령줄 `cast` 출력의 표지 줄.
  - 웹 라우트 셋.
- `tests/test_char_marks_js.py`(node 가 있을 때만): `castMarkFound` 가 서버 `charmarks.found` 와 같은 답을 낸다, 표지 카드는 표지가 없으면 그리지 않는다, 고른 부분 도구의 거두기 버튼은 반영한 화에서만 보인다.
- 스냅샷(`prompt_registry`, `char_context_auto`)은 바뀌지 않는다.

## 문서

- 이 폴더의 [plan.md](../plan.md) 10번 줄과 정할 것 14 · 15, [README.md](../README.md) 의 정한 규칙.
- `docs/modules/story.md` 의 `canon/cast.py` · `canon/renumber.py` · `canon/static/cast.js` 절과 새 절 `canon/charmarks.py`.
- `docs/modules/core.md` 의 `canon/schema.py` · `canon/web.py` 절.
- `docs/modules/web.md` 의 `canon/static/passage.js` 절.
- DESIGN.md 의 인물 대목과 README.md 의 인물 화면 줄.
- `docs/design/layout.md` 의 인물 쪽 카드 차례.

## 확인하지 못할 것

- 작가가 실제 연재 원고에서 표지를 거둬 쓰기 편한지는 작가가 써 봐야 안다.
- 손가락 기기에서 거두기 칸이 아래 붙는 도구(`toolDocked`) 안에서 편한지는 실기기에서 본다.

사용자가 할 단계:

1. 반영한 화의 집필 화면에서 대목을 골라 '인물 표지로 거두기'를 눌러 본다.
2. 인물 화면에서 표지 카드를 보고 고치고 지워 본다.
3. 정할 것 1~5 의 추천안이 맞는지 정한다.

## 비용

- LLM 비용 없음.

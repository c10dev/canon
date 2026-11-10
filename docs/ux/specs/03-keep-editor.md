# 03. 다시 그려도 본문 칸 지키기

상태: 끝 (#428) · 계획: [plan.md](../plan.md) 의 03번 · 먼저: —

## 목표

저장, AI 작업 끝, 알림 같은 일로 화면을 다시 그려도 집필 본문 칸의 Ctrl+Z 기록이 남는다.
README 관찰 바.

## 지금 동작 (2026-11-09 확인)

- `render` → `drawApp` 이 `#app` 의 innerHTML 을 통째로 바꾼다.
- 그래서 본문 `textarea` 가 새 요소로 바뀐다. 브라우저의 되돌리기 기록은 요소에 붙어 있어 함께 사라진다.
- `focusMark` · `afterDraw` 가 포커스, 커서(`selectionStart` · `selectionEnd`), 칸 안 스크롤을 되살린다.
- 실제 키로 확인: 글자를 친 뒤 Ctrl+Z 는 듣는다. 글자를 치고 Ctrl+S 로 저장한 뒤 Ctrl+Z 는 듣지 않는다.

## 정할 것

1. 지키는 방법 — 정함(2026-11-09, #428 에서 잰 결과로 바꿈): 지킬 칸에 `data-keep="<키>"` 를 달고, 그 칸과 조상은 제자리에 두고 나머지 노드만 바꾼다(`app.js` `paintApp` · `keepSwap`).
   - 처음 추천(떼어 두었다가 새 HTML 에 끼우기)은 쓰지 않는다. Chrome 은 요소가 문서를 떠나거나 옮겨지면(`moveBefore` 포함) 되돌리기 기록을 지운다(HeadlessChrome 156 시험 페이지).
   - 키가 새 HTML 에 없거나, 조상 깊이 · 태그가 다르면 지금처럼 `#app` 을 통째로 바꾼다.
   - 밑줄 층(`.hl-wrap`)이 생기거나 사라지면 조상 깊이가 바뀌어 새 요소가 되고, 이때는 되돌리기 기록이 사라진다.
   - 새 HTML 의 칸 속성(class, `aria-*`, `readonly`, `data-*`)은 제자리에 둔 옛 칸에 옮긴다.
   - 새 요소의 `value` 가 옛 요소의 `value` 와 다르면(서버가 본문을 바꿈: AI 본문 채택, 버전 되돌리기, 다시 불러오기) 칸을 지키지 않고 `#app` 을 통째로 바꾼다. 이때는 되돌리기 기록이 사라져도 맞다.
   - 화면 전체를 바뀐 곳만 고치는 방식(morph)은 장기 후보다([plan.md](../plan.md)).
2. 지킬 칸 — 추천: 집필 본문 칸 하나로 시작한다. 플롯 · 설정의 긴 글 칸은 같은 문제가 보고되면 같은 속성만 달아 넓힌다.
3. 본문 칸 위 밑줄 층(이름 · 표시 밑줄) — 추천: 밑줄 층은 지금처럼 새로 그리고, `syncMarks` 가 끼운 옛 칸을 기준으로 자리를 다시 잰다.

## 바꿀 곳

| 파일 | 바꿀 것 |
|---|---|
| `canon/static/app.js` | `drawApp`: `data-keep` 요소 떼어 두기와 끼우기. `afterDraw`: 끼운 요소는 포커스 · 커서를 다시 옮기지 않는다 |
| `canon/static/write.js` | 본문 `textarea` 에 `data-keep` |
| `canon/static/marks.js` | 끼운 칸에서 밑줄 자리 다시 재기 (필요하면) |

## 규칙

- 끼운 요소의 `input` 이벤트 바인딩은 `document` 위임이라 그대로 듣는다. 요소에 직접 붙인 처리기가 있으면 확인한다.
- 저장하지 않은 초안(`S.textDraft`), 이 브라우저 임시본(`keepDrafts`)은 바뀌지 않는다.
- 다른 화면으로 옮기면(키가 새 HTML 에 없음) 떼어 둔 요소를 버린다.

## 시험

- 새 JS 시험: 같은 값으로 다시 그리면 본문 칸이 같은 요소인지, 값이 바뀌면 새 요소인지 본다.
- 브라우저 확인(손으로 또는 Playwright): 글자를 치고 Ctrl+S 뒤 Ctrl+Z 가 그 글자를 지운다.
- `tests/test_write_js.py` · `tests/test_app_core_js.py` 가 그대로 통과하는지 본다.

## 문서

- `docs/modules/web.md` 의 `canon/static/app.js` 절 '다시 그리기와 포커스' 근처에 `data-keep` 규칙을 한 줄씩 더한다.
- `docs/modules/web.md` 의 `canon/static/write.js` 절에 본문 칸이 `data-keep` 이라는 줄을 더한다.

## 확인하지 못할 것

- 한국어 입력기(IME)로 조합 중에 다시 그려질 때의 동작은 실제 기기 · 입력기에서 사용자가 본다.
  1. 집필 화면에서 한글을 치다가 조합이 끝나기 전에 Ctrl+S 를 누른다.
  2. 글자가 깨지거나 두 번 들어가지 않는지 본다.

## 비용

LLM 비용 없음.

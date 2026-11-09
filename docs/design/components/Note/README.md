# Note

화면 안에 붙는 안내 상자로, `<div class="note info|warn|ok|err|plain">`에 한두 문장을 쓴다.

## 쓰는 법

- 쓰는 쪽이 줄 것: 상자 종류, 해요체 문장, 필요하면 작은 버튼(`.btn.small`)이나 링크.
- 종류와 색:
  - `info` 안내: `accent-soft` 면, `info-ink` 글자.
  - `warn` 경고: `amber-soft` 면, `amber-ink` 글자, `warn-line` 테두리.
  - `ok` 성공: `green-soft` 면, `green-ink` 글자.
  - `err` 오류: `red-soft` 면, `err-ink` 글자.
  - `plain` 덧붙임: `bg` 면, `text-2` 글자.
- 글자는 `note`(13px, 줄 간격 1.55), 안쪽 12px · 14px, 모서리 `radius-8`.
- 바뀌어 나타나는 상자는 `role="status"`를 준다.
- 접는 알림은 `<details class="note plain">`에 요약 한 줄을 `summary`로 둔다: 뗀 작업 설명(`metaCutNote`), 규칙 고침(`ruleRunsNote`).
- 규칙 고침 알림은 걸기 한 번마다 하나다. 요약은 '규칙으로 N곳 고쳤어요' 와 작은 글자의 종류 · 시각 · 되돌린 수다.
- 펴면 바뀐 곳마다 규칙 이름(굵게) · 전 글(`del`, `red-soft` 면) → 뒤 글(`ins`, `green-soft` 면) · `되돌리기`(`.btn.small`)가 한 줄이다(`.rx-change`). 지운 곳은 '(지움)', 줄바꿈은 ↵ 로 보인다.
- 시간 한도로 건너뛴 걸기는 접지 않은 `note warn` 한 줄이다.

## 지킬 것

- 색만으로 종류를 말하지 않는다. 문장이 무엇이 일어났는지 말한다.
- 오류 문장은 무엇이 막혔고 어떻게 풀지 쓴다.
- 문장 밖 경고 글자 한 줄은 상자 없이 `.warn-text`.

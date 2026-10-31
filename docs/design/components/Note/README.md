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

## 지킬 것

- 색만으로 종류를 말하지 않는다. 문장이 무엇이 일어났는지 말한다.
- 오류 문장은 무엇이 막혔고 어떻게 풀지 쓴다.
- 문장 밖 경고 글자 한 줄은 상자 없이 `.warn-text`.

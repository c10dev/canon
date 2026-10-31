# Field

이름표가 붙은 입력칸으로, `<div class="field">` 안에 `label`과 `input` · `textarea` · `select`를 둔다.

## 쓰는 법

- 쓰는 쪽이 줄 것: `label`(입력칸 `id`와 `for`로 잇기), 입력칸, 필요하면 이름표 안 도움말 `<span class="hint">`.
- 한 줄 칸 · 고르기 칸 높이 `control-input`(42px), 테두리 `line-strong`, 모서리 `radius-8`, 글자 14px. 손가락 기기에서는 16px.
- 여러 줄 칸은 안쪽 10px · 12px, 줄 간격 1.6, 세로로만 늘린다.
- 이름표는 `label`(13px, 500), 칸과 사이 `space-6`.
- 읽기 전용은 `readonly`: `bg` 면, `muted` 글자, 점선 테두리.
- 체크박스는 `checkbox`(20px), `accent` 색.
- 켜기 · 끄기는 스위치(`.set-sw`, `role="switch"`, `aria-checked`)다. 누름 영역 52 × 44px, 막대 44 × 26px. 꺼지면 `line-strong`, 켜지면 `accent` 막대, 손잡이는 흰색. 설정 대화상자가 쓴다.
- 설정 대화상자의 줄 안 입력칸(`.set-inp`)은 38px다. 줄(64px) 안에 나란히 놓여 나눔 버튼(38px)과 높이를 맞춘다.

## 지킬 것

- 이름표 없는 입력칸을 두지 않는다. 보이는 이름표가 없으면 `aria-label`.
- 포커스 링(`accent` 3px)을 지우지 않는다.
- 원고를 고치는 칸은 `serif`(`.field.passage textarea`).

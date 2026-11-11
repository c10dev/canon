# Field

이름표가 붙은 입력칸으로, `<div class="field">` 안에 `label`과 `input` · `textarea` · `select`를 둔다.

## 쓰는 법

- 쓰는 쪽이 줄 것: `label`(입력칸 `id`와 `for`로 잇기), 입력칸, 필요하면 이름표 안 도움말 `<span class="hint">`.
- 한 줄 칸 · 고르기 칸 높이 `control-input`(42px), 테두리 `line-strong`, 모서리 `radius-8`, 글자 14px. 손가락 기기에서는 16px.
- `type` 을 적지 않은 `<input>` 도 한 줄 칸과 같은 모양이다. 이 규칙이 없으면 브라우저 기본 모양(24px, 안쪽 여백 없음)이 나온다.
- 여러 줄 칸은 안쪽 10px · 12px, 줄 간격 1.6, 세로로만 늘린다.
- 이름표는 `label`(13px, 500), 칸과 사이 `gap-label`(6px).
- 입력칸 묶음 ↔ 묶음은 `gap-group`(12px)이다. 카드 안에 바로 놓으면 카드 간격이 그 값이고, 두 칸은 `.grid-2`(사이 12px).
- 읽기 전용은 `readonly`: `bg` 면, `muted` 글자, 점선 테두리.
- 칸 옆 AI 후보 버튼(`.ai-mini`, `후보 받기`)은 그 칸에 포인터나 포커스가 있을 때만 보인다(투명도 0 → 1, 숨은 동안 누를 수 없음). 자리는 비워 두어 나타나도 칸이 움직이지 않는다. 후보를 펼친 칸은 늘 보인다.
- 체크박스는 `checkbox`(20px), `accent` 색.
- 숫자 칸(`type=number`)은 휴대폰 숫자 자판을 띄운다. 앱이 `inputmode` 를 붙인다(소수 칸은 `decimal`, 나머지는 `numeric`).
- 켜기 · 끄기는 스위치(`.set-sw`, `role="switch"`, `aria-checked`)다. 누름 영역 52 × 44px, 막대 44 × 26px. 꺼지면 `line-strong`, 켜지면 `accent` 막대, 손잡이는 흰색. 설정 대화상자와 문체 화면의 '쓴 뒤 퇴고'가 쓴다.
- 설정 대화상자의 줄 안 입력칸(`.set-inp`)은 38px다. 줄(64px) 안에 나란히 놓여 나눔 버튼(38px)과 높이를 맞춘다.
- 설정 대화상자의 숫자 칸(`.set-inp.set-num`, 블록 예산)은 110px, 오른쪽 맞춤 `tabular-nums` 다. 뒤에 단위 글자와 '기본값으로' 버튼을 둔다(`.set-bud`). 기본값이면 버튼을 쓸 수 없게 둬 줄마다 칸 자리를 맞춘다.

## 지킬 것

- 이름표 없는 입력칸을 두지 않는다. 보이는 이름표가 없으면 `aria-label`.
- 포커스 링(`accent` 3px)을 지우지 않는다.
- 칸에 딸린 버튼을 숨길 때 `display: none` · `visibility: hidden` 을 쓰지 않는다. Tab 으로 닿지 못한다. 투명도로 숨기고 `:focus-within` 에서 보인다.
- 원고를 고치는 칸은 `serif`(`.field.passage textarea`).

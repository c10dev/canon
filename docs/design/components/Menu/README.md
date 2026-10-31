# Menu

버튼을 누르면 그 아래에 뜨는 펼침 창으로, 앱의 `menuBtn(id, label, body, opt)`가 `<div class="menu">` 안에 버튼과 `.pop-panel`을 그린다.

## 쓰는 법

- 쓰는 쪽이 줄 것: 메뉴 id, 버튼 글자(⋯ 메뉴는 기호와 `aria-label`), 열렸을 때만 부르는 내용 함수, 필요하면 버튼 클래스(`cls`, 기본 `btn`)와 왼쪽 맞춤(`align: 'left'`).
- 버튼은 `aria-expanded`와 `aria-controls`를 단다. 열린 버튼은 `accent` 테두리와 `accent-soft` 면(켜진 토글과 같다).
- 창(`.pop-panel`): 버튼 오른쪽 끝에 맞춰 6px 아래, 폭 `min(320px, 100vw - 32px)`, 높이 `min(70vh, 560px)`까지(넘으면 안에서 굴림), 안쪽 8px, `surface` 면, `line-strong` 테두리, `radius-12`, `shadow-float`, 글자 13px. 왼쪽 밖으로 나가면 앱이 버튼 왼쪽 끝에 다시 맞춘다(`fitMenus`).
- 창 안의 부품:
  - 동작 줄 `.pop-item`: 44px, `radius-8`, 마우스를 올리면 `bg` 면. 덧붙임은 오른쪽 끝 `.small`. 위험한 동작은 `.pop-item.danger`.
  - 고르기 줄 `.pop-radio` · `.pop-check`: 40px, 20px 라디오 · 체크박스(`accent` 색), 이름 아래 설명.
  - 묶음 `.pop-sec`과 묶음 이름 `.pop-legend`(12px 700 `muted`), 나누는 선 `.pop-sep`(`rule`).
  - 지우기 같은 위험한 묶음은 `<details class="pop-danger">`로 한 번 더 접는다. 머리 글자는 `red`.
  - 창 안에 나눔 버튼(Seg)을 둘 수 있다. 줄이 넘치면 다음 줄로 간다.
- 분할 버튼(`.split`): 주 동작 버튼 + 오른쪽 ▾ 메뉴 버튼(36px 폭). 두 면 사이를 `surface` 1px 틈으로 나눈다. 집필 화면의 `복사 ▾`가 그 예다.

## 지킬 것

- 창 안 `[data-action]`을 누르면 창을 닫는다. 라디오 · 체크박스는 고른 뒤에도 창을 열어 둔다.
- 바깥을 누르거나 Esc를 누르면 닫는다. Esc로 닫으면 포커스를 메뉴 버튼으로 돌린다. 열린 메뉴는 화면을 다시 그려도 열려 있다.
- `role="menu"`를 쓰지 않는다. 창 안에 라디오 · 체크박스 · 나눔 버튼이 섞여서 메뉴 역할 키 규칙과 맞지 않는다. 창 안은 Tab으로 옮긴다.
- 한 화면에 메뉴 창은 하나만 열린다.
- 화면의 주 동작을 메뉴 안에 숨기지 않는다. 메뉴는 덜 쓰는 동작(생성 방식, 내려받기, 화 지우기)을 모은다.

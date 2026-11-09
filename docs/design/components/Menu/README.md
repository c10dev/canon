# Menu

버튼을 누르면 그 아래에 뜨는 펼침 창으로, 앱의 `menuBtn(id, label, body, opt)`가 `<div class="menu">` 안에 버튼과 `.pop-panel`을 그린다.

## 쓰는 법

- 쓰는 쪽이 줄 것: 메뉴 id, 버튼 글자(⋯ 메뉴는 기호와 `aria-label`), 열렸을 때만 부르는 내용 함수, 필요하면 버튼 클래스(`cls`, 기본 `btn`)와 왼쪽 맞춤(`align: 'left'`).
- 버튼은 `aria-expanded`와 `aria-controls`를 단다. 열린 버튼은 `accent` 테두리와 `accent-soft` 면(켜진 토글과 같다).
- 창(`.pop-panel`): 버튼 오른쪽 끝에 맞춰 6px 아래, 폭 `min(320px, 100vw - 32px)`, 높이 `min(70vh, 560px)`까지(넘으면 안에서 굴림), 안쪽 8px, `surface` 면, `line-strong` 테두리, `radius-12`, `shadow-float`, 글자 13px. 왼쪽 밖으로 나가면 앱이 버튼 왼쪽 끝에 다시 맞춘다(`fitMenus`).
- 버튼이 줄 가운데에 있어 양쪽 어느 끝에 맞춰도 화면 밖으로 나가면, 앱이 창을 화면 안(좌우 8px)으로 옆으로 민다(`fitMenus`, `.fit-shift`).
- 창 아래가 화면 밖으로 나가면(가로 휴대폰, 화면 아래쪽 버튼) 앱이 위 · 아래 중 넓은 쪽으로 펼치고 그쪽 남은 높이 안에서 굴린다(`fitMenus`, `.pop-panel.up`). 쓴 사람이 정한 위로 펼침은 그대로 둔다.
- 창 안의 부품:
  - 동작 줄 `.pop-item`: 44px, `radius-8`, 마우스를 올리면 `bg` 면. 덧붙임은 오른쪽 끝 `.small`. 위험한 동작은 `.pop-item.danger`.
  - 다른 화면으로 가는 줄은 `<a class="pop-item">`이다. 밑줄 없이 `text` 글자로 동작 줄과 같게 그린다.
  - 고르기 줄 `.pop-radio` · `.pop-check`: 40px, 20px 라디오 · 체크박스(`accent` 색), 이름 아래 설명. 손가락 기기와 640px 이하에서는 44px.
  - 묶음 `.pop-sec`과 묶음 이름 `.pop-legend`(12px 700 `muted`), 나누는 선 `.pop-sep`(`rule`).
  - 지우기 같은 위험한 묶음은 `<details class="pop-danger">`로 한 번 더 접는다. 머리 글자는 `red`.
  - 창 안에 나눔 버튼(Seg)을 둘 수 있다. 줄이 넘치면 다음 줄로 간다.
- 메뉴 버튼을 쓰지 않는 뜨는 창도 같은 가장자리를 쓴다: `line-strong` 테두리, `radius-12`, `shadow-float`.
  - 대화 패널의 세션 · 빠른 요청 · 권한 모드 창(`.pop`, agent.js): 높이 `min(70vh, 560px)`까지. 자리는 패널 안 버튼 위 · 아래에 화면이 정한다.
  - 인물 · 지명 이름 카드(`.mn-card`, mentions.js): 폭 `min(340px, 100vw - 16px)`, 높이 `min(70vh, 480px)`까지, `z-float`.
  - 본문 부분 수정 도구(`.sel-tool`): 고른 글 위에 뜨는 버튼 줄과 고치는 칸, `z-float`.
- 분할 버튼(`.split`): 주 동작 버튼 + 오른쪽 ▾ 메뉴 버튼(36px 폭). 두 면 사이를 `surface` 1px 틈으로 나눈다. 집필 화면의 `복사 ▾`가 그 예다.

## 지킬 것

- 창 안 `[data-action]`을 누르면 창을 닫는다. 라디오 · 체크박스는 고른 뒤에도 창을 열어 둔다.
- 바깥을 누르거나 Esc를 누르면 닫는다. Esc로 닫으면 포커스를 메뉴 버튼으로 돌린다. 열린 메뉴는 화면을 다시 그려도 열려 있다.
- `role="menu"`를 쓰지 않는다. 창 안에 라디오 · 체크박스 · 나눔 버튼이 섞여서 메뉴 역할 키 규칙과 맞지 않는다. 창 안은 Tab으로 옮긴다.
- 한 화면에 메뉴 창은 하나만 열린다.
- 화면의 주 동작을 메뉴 안에 숨기지 않는다. 메뉴는 덜 쓰는 동작(생성 방식, 내려받기, 화 지우기)을 모은다.

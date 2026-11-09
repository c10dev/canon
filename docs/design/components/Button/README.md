# Button

화면의 동작 하나를 실행하는 버튼으로, `<button type="button" class="btn">`에 변형 클래스를 더해 쓴다.

## 쓰는 법

- 쓰는 쪽이 줄 것: `<button type="button">` 요소, 동사로 된 글자, 동작을 잇는 `data-action`(필요하면 `data-arg`).
- 변형: 기본 `.btn`(테두리 없이 `btn` 면), 주 동작 `.btn.primary`(본문 `main` 안에 하나, `accent` 면. README '주 버튼 셈'), 뜨는 띠 위 `.btn.dark`, 덧붙이는 동작 `.btn.ghost`(면 · 테두리 없이 `link` 글자, 올리면 `btn` 면), 지우기 같은 위험한 동작 `.btn.danger`, 켜진 토글 `.btn.on`과 `aria-pressed="true"`(`accent` 테두리와 `accent-soft` 면).
- 크기: 기본 `control`(44px), 작은 `.btn.small`은 `control-small`(36px). 작은 버튼은 카드 안 보조 동작에만 쓴다.
- 손가락 기기(`pointer: coarse`)와 640px 이하에서 `.btn.small`은 `touch-min`(44px)이다. 한 줄의 작은 버튼이 함께 커져 높이가 같다.
- 글자 없는 버튼은 `.icon-btn`(폭 44px, `btn` 면)에 `aria-label`을 준다. 사이드바 안의 글자 없는 버튼만 면 없는 `.side-ico`를 쓴다(Nav).
- 대화 패널 열기(`chat.js` `chatButton`)는 `.btn.icon-btn.chat-toggle`이다: 사이드바와 같은 대화 기호(`SIDE_ICON.chat`, 18px), `aria-label` · `title` '대화로 다듬기', `aria-pressed`.
- 대화 패널 열기는 켜져도 `.btn.on`의 `accent` 테두리를 쓰지 않는다. 면만 `btn-hover`다. 패널이 열린 것은 옆 칸이 보여 준다.
- 예외: 640px 이하 집필 화면의 붙는 줄 도구(문체 · 고칠 곳 · 수정 기록 · 복사)와 머리의 화 앞뒤 · ⋯ 버튼은 면 없는 아이콘 버튼이다. 터치 칸은 44px 그대로이고 누르는 동안만 `btn` 면이다.
- 그 도구 버튼은 글자 대신 아이콘(`.lbl-i`)을 보인다. 이름은 `aria-label`이나 낭독 전용 글자(`.lbl-t`)가 말한다.
- 켜진 토글과 열린 메뉴 버튼은 그 폭에서도 원래 모양(`accent` 테두리 · `accent-soft` 면)이다.
- 쓸 수 없을 때는 `disabled`. 링크 모양 버튼(`<a class="btn">`)은 `aria-disabled="true"`.
- AI 작업이 도는 동안은 `disabled` 대신 `aria-disabled="true"` · `aria-busy="true"`를 단다(Busy).
- 펼침 창을 여는 버튼은 `menuBtn`이 만든다(Menu). 열린 동안 켜진 토글과 같은 모양이다.

## 지킬 것

- 한 줄에 나란히 놓인 버튼은 같은 높이다. 한 버튼에만 `min-height`를 덮어쓰지 않는다. 덮어써야 하면 그 줄의 버튼 모두에 같은 규칙을 건다.
- 좁은 화면 위 띠의 `찾기` · `메뉴`는 둘 다 `touch-min` 44px다.
- `.btn.small.icon-btn`은 폭 44px, 높이 36px라 정사각형이 아니다(손가락 기기는 44px 정사각형). 화살표 한 쌍처럼 둘이 같은 크기로 붙어 있을 때만 쓴다.
- 주 버튼은 오른쪽 끝에 둔다: [버리기] [반영]. 머리 줄에서는 대화 패널 열기 아이콘 버튼만 그 뒤 맨 끝에 둔다.
- 포커스 링을 지우지 않는다(`accent` 3px, 2px 띄움).
- 버튼에 테두리를 그리지 않는다. 테두리 칸은 1px 투명으로 남겨 켜진 토글 · 주 버튼과 크기가 같다.
- 분할 버튼(복사 + ▾, `.split`)은 두 면 사이를 `surface` 색 1px 틈으로 나눈다(Menu).
- `.btn.danger` 글자(`red`)는 두 테마 모두 `btn` · `btn-hover` 면 위 4.5:1 이상이다. 위험한 동작은 글자로도 뜻을 말한다(`초고 지우기`).
- 작품 데이터(작품 · 인물 · 관계 · 문체 · 삽화 등)를 지우는 버튼은 `.btn.danger` 이고 동사는 `지우기`다. 화면 문구에 `삭제`를 쓰지 않는다. 확인 창도 `지울까요?` · `지우기`로 맞춘다.

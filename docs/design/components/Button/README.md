# Button

화면의 동작 하나를 실행하는 버튼으로, `<button type="button" class="btn">`에 변형 클래스를 더해 쓴다.

## 쓰는 법

- 쓰는 쪽이 줄 것: `<button type="button">` 요소, 동사로 된 글자, 동작을 잇는 `data-action`(필요하면 `data-arg`).
- 변형: 기본 `.btn`(테두리 없이 `btn` 면), 주 동작 `.btn.primary`(한 화면에 하나, `accent` 면), 뜨는 띠 위 `.btn.dark`, 덧붙이는 동작 `.btn.ghost`(면 · 테두리 없이 `link` 글자, 올리면 `btn` 면), 지우기 같은 위험한 동작 `.btn.danger`, 켜진 토글 `.btn.on`과 `aria-pressed="true"`(`accent` 테두리와 `accent-soft` 면).
- 크기: 기본 `control`(44px), 작은 `.btn.small`은 `control-small`(36px). 작은 버튼은 카드 안 보조 동작에만 쓴다.
- 글자 없는 버튼은 `.icon-btn`(폭 44px, `btn` 면)에 `aria-label`을 준다. 사이드바 안의 글자 없는 버튼만 면 없는 `.side-ico`를 쓴다(Nav).
- 쓸 수 없을 때는 `disabled`. 링크 모양 버튼(`<a class="btn">`)은 `aria-disabled="true"`.
- AI 작업이 도는 동안은 `disabled` 대신 `aria-disabled="true"` · `aria-busy="true"`를 단다(Busy).
- 펼침 창을 여는 버튼은 `menuBtn`이 만든다(Menu). 열린 동안 켜진 토글과 같은 모양이다.

## 지킬 것

- 한 줄에 나란히 놓인 버튼은 같은 높이다. 한 버튼에만 `min-height`를 덮어쓰지 않는다. 덮어써야 하면 그 줄의 버튼 모두에 같은 규칙을 건다.
- 좁은 화면 위 띠의 `찾기` · `메뉴`는 둘 다 `touch-min` 44px다.
- `.btn.small.icon-btn`은 폭 44px, 높이 36px라 정사각형이 아니다. 화살표 한 쌍처럼 둘이 같은 크기로 붙어 있을 때만 쓴다.
- 주 버튼은 오른쪽 끝에 둔다: [버리기] [반영].
- 포커스 링을 지우지 않는다(`accent` 3px, 2px 띄움).
- 버튼에 테두리를 그리지 않는다. 테두리 칸은 1px 투명으로 남겨 켜진 토글 · 주 버튼과 크기가 같다.
- 분할 버튼(복사 + ▾, `.split`)은 두 면 사이를 `surface` 색 1px 틈으로 나눈다(Menu).
- 어두운 테마의 `.btn.danger` 글자는 아직 4.5:1에 못 미친다(README '코드와 아직 다른 곳'). 위험한 동작은 글자로도 뜻을 말한다(`초고 지우기`).

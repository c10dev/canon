# Tabs

한 화면 안의 여러 판을 오가는 탭으로, `<div class="tabs" role="tablist">` 안에 `role="tab"` 버튼을 둔다.

## 쓰는 법

- 쓰는 쪽이 줄 것: 탭 묶음 이름(`aria-label`), 탭 버튼(`role="tab"`, `aria-selected`, `aria-controls`), 그 아래 `role="tabpanel"`.
- 탭 높이 `touch-min`(44px), 고른 탭은 `accent` 밑줄 3px와 `accent-ink` 글자 700.
- 탭이 많으면 기본은 옆으로 스크롤한다. 줄을 넘겨야 하면 `.tabs.wrap`.
- 왼쪽 · 오른쪽 화살표와 Home · End 키로 탭을 옮긴다(앱이 `role="tablist"`마다 붙인다).
- 탭 버튼마다 `id`를 두고, 아래 판은 `role="tabpanel"` · `aria-labelledby`(고른 탭 id)로 잇는다.
- 판 안에 덩어리가 여럿이면 `.tab-panel`로 감싼다. 부모 칸의 간격을 그대로 쓴다(`gap: inherit`).

## 지킬 것

- 탭 글자는 판 이름 명사로 쓴다: `관계도`, `인물 카드`, `등장표`.
- 같은 화면의 보기 방식만 바꾸면 나눔 버튼(Seg)을 쓴다.

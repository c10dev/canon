# Table

값을 줄과 칸으로 견주는 표다. `<table>`을 굴림 칸(`.rs-scroll` · `.sw-table-wrap`) 안에 두고, 화면 클래스로 모양을 고른다.

## 쓰는 법

- 쓰는 쪽이 줄 것: 머리 줄(`<thead>`의 `th scope="col"`), 줄 이름 칸(`th scope="row"`), 값 칸(`td`), 넓으면 굴림 칸.
- 공통: 칸끼리 붙임(`border-collapse`), 글자 13px, 왼쪽 맞춤, 수는 `tabular-nums`.
- 머리 칸: 12px, 500, `muted`, 아래 선 `line`.
- 줄 사이: 1px `rule` 선.
- 변형은 넷이다.
  - 기본 표(`.sw-table`): 안쪽 `space-8` · `space-10`, 첫 칸(`tbody th`) 700에 왼쪽 고정(`position: sticky`, `surface` 면). 상태창 수치 · 역설계 실험 · 큐 시트 실험이 쓴다.
  - 촘촘한 표(`.rs-table`): 안쪽 `space-6` · `space-8`, 칸 글 한 줄. 연구 · 사용량 · 자동 집필 기록이 쓴다.
  - 카드 안 표(`.pf-table`): 바깥 테두리 없이 줄 위 선, 수 칸(`.num`)은 오른쪽 맞춤.
  - 재구성 대응표(`.rb-map`): 머리 줄이 위에 붙는다(`position: sticky`). 줄 앞 3px 선으로 처리(그대로 · 고침 · 다시 씀)를 보인다.
- 지도 '어디에 있었나'(`.at-table`, atlas.js)와 스토리보드 상태창 값(`.bd-table`, board.js)은 화면 CSS 안에 같은 머리 · 줄 선 규칙을 쓴다.
- 강조 칸은 면과 굵기를 함께 쓴다: 바뀐 값 `accent-soft` 면 · 700, 빠듯함 `amber-soft` 면 · 700, 넘침 `red-soft` 면 · 700.
- 640px 이하에서 칸이 많은 표는 줄을 카드처럼 쌓는다: `.rs-stack`(칸마다 `data-label` 이름), `.rs-table.auto-log`, `.rb-map`.

## 지킬 것

- 페이지를 가로로 굴리지 않는다. 넓은 표는 굴림 칸 안에서만 굴린다(화면 배치 문서).
- 머리 칸에는 `scope`를 단다.
- 면 색만으로 상태를 말하지 않는다. 굵기 · 글자 · 칩을 함께 쓴다.
- 새 표는 위 변형 가운데 하나를 쓴다. 화면만의 칸 규칙은 그 화면 클래스 아래에 둔다.

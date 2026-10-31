# Outline

구역이 여럿인 긴 화면의 짜임으로, 왼쪽 목차 열과 오른쪽 카드 한 열이다. 설정 도우미 기획서(`.setup-doc`), 문체 화면과 문체 라이브러리 항목(`.sty-doc`), 역설계 실험(`.rev-doc`), 복선 센터(`.fs-wrap`, 공용 틀 `outline.js` 의 `outlineDoc` · `outlineNav`)가 쓴다.

## 쓰는 법

- 감싸는 칸(`.setup-wrap` · `.sty-wrap` · `.rev-wrap`)에 이름 붙은 `@container`(`setup` · `sty` · `rev`)를 둔다. 폭 규칙은 창이 아니라 이 칸의 폭을 따른다. 대화 패널을 열어도 같은 규칙이 맞는다.
- 두 열: 목차 220px + 카드 열. 카드 열은 설정 도우미 · 문체가 최대 760px(`measure`), 역설계 실험 · 복선 센터는 남는 폭 모두. 열 사이 `space-32`.
- 목차(`.setup-toc` · `.sty-toc` · `.rev-toc`): 위에 붙어 있다(`position: sticky`, 위 16px). 목차 머리 아래에 구역 줄을 둔다.
  - 구역 줄: 38~40px, `radius-8`, `text-2` 500. 마우스를 올리면 `surface` 면. 지금 구역은 `aria-current`: `accent-soft` 면, `accent-ink` 700.
  - 줄 끝에 상태 글(`.st`, 12px `muted`)을 둔다. 할 일이 있으면 `written-ink` · `amber-ink` 700과 `amber` 점.
  - 설정 도우미는 줄 앞에 번호 칸(`.n`, 22px, `radius-6`, `chip` 면)을 둔다. 지금 구역은 `accent` 면, 끝난 구역은 `green-soft` 면.
  - 목차 줄을 누르면 그 카드로 옮기고 포커스를 준다.
- 카드 열은 카드(Card)를 `space-14` 사이로 쌓는다.
- 칸 폭 720px 이하: 한 열. 목차는 위에 붙는 '지금 구역 ▾' 버튼(`aria-expanded`)이 되고, 누르면 그 아래에 구역 목록이 뜬다(`surface` 면, `radius-12`, 높이 70vh까지). 이때 구역 줄은 44px. 900px 이하에서는 위쪽 띠 아래(`--band`)에 붙는다.
- 설정 도우미 새 작품 마법사는 목차 대신 걸음 막대(`.setup-toc.steps`)와 아래 버튼 줄(`.setup-foot`)을 쓴다.

## 지킬 것

- 목차는 이동만 한다. 저장 · AI 동작은 머리 버튼 줄이나 카드 안에 둔다.
- 목차 줄 글은 카드 제목과 같게 쓴다.
- 새 화면에 이 짜임이 필요하면 같은 크기 · 같은 색을 쓴다. 지금은 화면마다 CSS가 따로 있다(README '코드와 아직 다른 곳').

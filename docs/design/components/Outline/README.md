# Outline

구역이 여럿인 긴 화면의 짜임으로, 왼쪽 목차 열과 오른쪽 카드 한 열이다. 설정 도우미(기획서 · 새 작품 걸음), 문체 화면과 문체 라이브러리 항목, 기승전결 · 플롯(보드 · 화 플롯 페이지), 역설계 실험, 인물 · 관계도(`.cast-wrap`: 목차는 관계도 · 등장표 · 비중별 인물, 줄 앞 인물 원 24px), 복선 센터(개요 · 복선 하나), 장면 연출(`.stg-wrap`: 목차는 화 · 사건 · 지금 사건의 박자, 박자 줄 끝에 지적 수)이 같은 컴포넌트를 쓴다. 코드는 `canon/static/outline.js` 와 `app.css` 의 '공용 목차 틀' 절이다.

작품 도구 넷도 같은 컴포넌트를 쓴다: 갈래 비교(`.bc-wrap`), 채팅 앱 작업지시서(`.brief-wrap`), 자동 집필(`.auto-wrap`), 고칠 곳(`.tofix-wrap`).

## 쓰는 법

- 틀은 `outlineDoc(목차, 카드 열, { wide, cls })` 로 그린다. 감싸는 칸 `.outline-wrap` 에 컨테이너 `outline` 을 둔다. 폭 규칙은 창이 아니라 이 칸의 폭을 따른다. 대화 패널을 열어도 같은 규칙이 맞는다. 화면만의 칸 규칙도 `@container outline` 으로 건다.
- 두 열(`.outline-doc`): 목차 220px + 카드 열, 열 사이 `space-32`. 카드 열은 최대 760px(`measure`)이고, `.wide`(역설계 실험, 플롯 보드, 복선 센터, 장면 연출)는 남는 폭을 모두 쓴다.
- 갈래 비교는 `.wide` 다. 작업지시서 · 자동 집필 · 고칠 곳은 760px 열이다.
- 목차는 `outlineNav({ id, label, now, body })` 로 그린다(`nav.outline`). 위에 붙어 있다(`position: sticky`, 위 16px).
  - 구역 줄(`.outline-item`, button 또는 a): 38px, `radius-8`, `text-2` 500. 마우스를 올리면 `surface` 면. 지금 구역은 `aria-current`: `accent-soft` 면, `accent-ink` 700.
  - 줄 안: 번호 칸 `.n`(22px, `radius-6`, `chip` 면) · 이름 `.tl` · 끝 상태 글 `.st`(12px `muted`).
  - 번호 칸 상태: 끝남 ✓ `.ok`(`green-soft` 면), 지금 줄 · 지금 할 단계 `.now`(`accent` 면), 하는 중 `.run`(`accent-soft` 면). 지금 줄(`aria-current`)의 번호 칸도 `accent` 면이다.
  - 할 일: `.st.warn` 또는 줄에 `.warn`. `amber-ink` 700, `.warn` 줄은 이름 앞에 `amber` 점.
  - 수 칩은 `.st` 안이나 이름 뒤에 Chip 으로 둔다.
  - 묶음 이름 `.outline-h`(12px `muted`), 구분선 `.outline-sep`, 설명 글 `.outline-note`.
  - 목차 줄을 누르면 그 카드로 옮기고 포커스를 준다.
  - 목록 묶음(역설계 실험의 '화')은 묶음 이름 오른쪽에 더하기 버튼(＋), 줄 오른쪽에 ⋯ 메뉴(`menuBtn`)를 둘 수 있다. ⋯ 는 줄에 마우스를 올리거나 포커스가 들어오거나 메뉴가 열렸을 때 보이고, 그동안 상태 글을 가린다. 마우스를 올릴 수 없는 기기(`hover: none`)에서는 늘 보이고 줄 글이 버튼 자리를 비운다. 두 버튼은 `.icon-btn` 에 같은 크기를 건다: 36px 정사각형, 손가락 기기(`pointer: coarse`)는 44px이고 그때 줄도 44px. 기호는 SVG(⋯ 는 `SIDE_ICON.more`)이고 `aria-label` 을 준다. 오른쪽 카드 열에 칸을 펴는 버튼(＋, 메뉴의 고치기)은 `data-outline-close` 를 달아 펼친 목록을 닫는다.
- 카드 열은 카드(Card)를 쌓는다. 사이는 화면이 정한다(설정 도우미 22px, 문체 `space-14`, 역설계 실험 16px).
- 칸 폭 720px 이하: 한 열(사이 12px). 목차는 위에 붙는 '지금 구역 ▾' 버튼(`.outline-now`, `aria-expanded`)이 되고, 누르면 그 아래에 구역 목록이 뜬다(`surface` 면, `radius-12`, 높이 70vh까지, 넘치면 스크롤). 이때 구역 줄은 44px. 900px 이하에서는 위쪽 띠 아래(`--band`)에 붙는다. 위쪽 띠가 없는 화면(역설계 실험)은 틀에 `--outline-band: 0px`.
- 펼친 목록은 바깥을 누르거나, 목록의 줄을 누르거나, Esc 를 누르거나, 다른 화면으로 가면 닫힌다. Esc 는 버튼으로 포커스를 돌린다. 목록 안에서 펼침을 바꾸는 줄(부 접기 등)은 `data-outline-keep` 으로 열어 두고, 줄이 아닌 버튼이 화면을 옮기면 `data-outline-close` 를 단다.
- 열림은 `OUTLINE_OPEN` 이 기억한다. 스크롤로 지금 구역이 바뀌어 목차를 다시 그려도(`outlineRefresh`) 열림 · `aria-expanded` · 목차 안 포커스가 그대로다. 지금 구역은 `outlineSpy` 가 센다(화면 위 120px 줄을 지난 마지막 구역, 맨 아래면 마지막 구역).
- 설정 도우미 새 작품 마법사는 버튼 없이(`now` 없음) 목차에 `.steps` 를 달아 720px 이하에서 걸음 막대로 바꾸고, 아래 버튼 줄(`.setup-foot`)을 쓴다.

## 지킬 것

- 목차는 이동만 한다. 저장 · AI 동작은 머리 버튼 줄이나 카드 안에 둔다. 예외로 목록 묶음의 ＋ · ⋯ 는 그 목록 항목을 더하거나 고치거나 빼는 덜 쓰는 동작만 연다. 누르면 오른쪽 카드 열에 칸을 펴거나 확인을 받고, 목차 안에서 바로 저장하지 않는다.
- ⋯ 메뉴의 지우기는 Menu 규칙대로 위험한 묶음(`.pop-sec.pop-danger` 안 `<details>`)으로 한 번 더 접는다.
- 목차 줄 글은 카드 제목과 같게 쓴다.
- 새 화면에 이 짜임이 필요하면 `outlineDoc` · `outlineNav` 를 쓴다. 클래스 · 토글을 화면마다 새로 만들지 않는다. 화면만의 줄 모양은 그 화면 클래스 아래(`.plot-wrap .outline-item.act` 처럼)에 둔다.

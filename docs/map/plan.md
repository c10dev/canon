# 지도 계획

단기는 차례가 정해진 일감이다. 장기는 아직 정하지 않은 후보다. 일감을 끝내면 이 표의 상태와 [README.md](README.md) 의 정한 규칙을 고친다.

## 단기

차례는 2026-10-28 에 사용자와 정했다. 모듈 정리(1~3)는 같은 날 사용자가 먼저 하자고 한 일이다. 8~10 은 남은 일로 적어 두었고 차례는 아직 정하지 않았다. 11~13 은 2026-10-29 에 사용자가 [research-look.md](research-look.md) 의 제안 P1~P3 을 골라 넣었다.

| # | 일감 | 상태 | 명세서 | 먼저 끝날 것 |
|---|---|---|---|---|
| 0 | AI 설정 제안의 현대 동네 · 이름으로 자리 찾기 · 건물 한 줄 | [#139](https://github.com/c10dev/canon/pull/139) 머지, [#140](https://github.com/c10dev/canon/pull/140)(초안) 리뷰 대기 | — | — |
| 1 | 경계 정리 (파일은 그대로) | 구현, 초안 PR [#148](https://github.com/c10dev/canon/pull/148) | [01-boundaries.md](specs/01-boundaries.md) | 0 |
| 2 | `canon/maps/` 패키지로 옮기기 | 설계 | [02-package.md](specs/02-package.md) | 1 |
| 3 | `static/atlas.js` 나누기 | 구현, 초안 PR [#148](https://github.com/c10dev/canon/pull/148) | [03-atlas-js.md](specs/03-atlas-js.md) | 0 |
| 4 | OSM 빈 블록 채우기 | 구현, 초안 PR [#148](https://github.com/c10dev/canon/pull/148) | [04-empty-blocks.md](specs/04-empty-blocks.md) | 1 |
| 5 | 바다 (OSM 해안선) | 구현, 초안 PR [#148](https://github.com/c10dev/canon/pull/148) | [05-coastline.md](specs/05-coastline.md) | 0 |
| 6 | 지하철 노선과 역 사이 이동 시간 | 설계 | [06-subway.md](specs/06-subway.md) | 5 |
| 7 | 길 이름표 다듬기 | 구현, 초안 PR [#148](https://github.com/c10dev/canon/pull/148) | [07-street-labels.md](specs/07-street-labels.md) | 3 |
| 8 | 현대 장소 종류 | 차례 미정 | [08-modern-kinds.md](specs/08-modern-kinds.md) | 1 |
| 9 | 옛 핀의 건물 한 줄 채우기 | 차례 미정 | [09-spot-backfill.md](specs/09-spot-backfill.md) | 0 |
| 10 | 구불구불한 하천 (현대 동네) | 차례 미정 | [10-winding-river.md](specs/10-winding-river.md) | 1 |
| 11 | 지도 장식 (축척 · 나침반 · 제목 틀) | 구현, 초안 PR [#148](https://github.com/c10dev/canon/pull/148) | [11-map-frame.md](specs/11-map-frame.md) | 3 |
| 12 | 이름표 충돌 보강 | 구현, 초안 PR [#148](https://github.com/c10dev/canon/pull/148) | [12-label-collisions.md](specs/12-label-collisions.md) | 7 |
| 13 | 화풍을 따라가는 동선 · 핀 | 설계 | [13-style-trails.md](specs/13-style-trails.md) | 3 |

'먼저 끝날 것'은 코드가 겹쳐서 먼저 머지되어야 하는 일감이다. 1 · 3 은 2026-10-28 에 0 의 두 PR 위에 쌓은 브랜치 `claude/map-stack` 에서 두 세션이 함께 했고, 4 는 그 위에서 했고, 5 · 7 은 그 위에서 두 세션이 함께 했다(05 는 `osm.py` 와 물 그림, 07 은 이름표 코드만 고쳤다). 3 · 5 · 9 는 1 · 2 와 따로 할 수 있다. 같은 파일을 고치는 일감은 동시에 하지 않는다(AGENTS.md 의 worktree 규칙). 11 · 12 · 13 은 모두 `static/atlas.js` 의 그림 코드를 고쳐서 차례로 한다. 06 도 지도에 노선을 그리면 `atlas.js` 와 겹치니 시작 전에 고칠 파일을 견준다.

## 장기 후보

정하지 않은 것이다. 시작하기 전에 사용자와 정하고, 정하면 단기로 옮겨 명세서를 쓴다.

| 후보 | 왜 | 먼저 필요한 것 |
|---|---|---|
| 지도 여러 장 (세계 → 도시 → 동네) | 지금 작품 하나에 지도 하나다(`Project.atlas`). 여러 마을을 오가는 작품은 장소 일부만 놓인다. | `Atlas` 를 목록으로 바꾸는 스키마 설계, 장소가 어느 지도에 있는지, 지도 사이 이동 시간 |
| 왕국 · 대륙 생성기 | `atlas.MAKERS` 주석과 AGENTS.md 의 towngen 줄이 '왕국은 다음 단계'라고 적어 둔 일이다. 이동 시간 검사가 먼 거리를 지도로 셀 수 있다. | 지도 여러 장, 지형(산 · 강 · 바다) 생성 |
| OSM 직접 받기 | 작가가 파일을 받는 수고를 던다. | 따로 운영하는 Overpass 서버 (README.md 의 정한 규칙) |
| Swift 지도 화면 | Swift 앱에는 지도 화면이 없다(`swift/Sources` 에 지도 모듈 없음). | 단계 2 · 3 뒤의 안정된 API |
| 화별 지도 변화 | 불탄 건물, 새로 연 가게처럼 이야기 속에서 지도가 바뀐다. | 고친 건물(`Atlas.buildings`)에 화 범위, 스냅샷 · 되돌리기와 맞추기 |
| 기획 프롬프트에 지도 | 플롯을 짤 때 거리 · 건물을 보면 이동이 맞는 플롯이 나온다. | 건물 한 줄(#140) 뒤 실제 효과 확인 |
| 플레이 모드 연동 | 플레이 모드가 장소 목록을 쓴다(`birth.py` 의 `atlas.places`). 인물이 지도를 걸으며 시간이 흐를 수 있다. | 플레이 모드 설계(DESIGN.md 10장) |
| 실내 평면도 | 저택 · 학교 안에서 벌어지는 장면이 많은 작품. | 지도 여러 장 |

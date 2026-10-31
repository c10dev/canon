# 지도 데이터 형식 (레이아웃)

지도 데이터는 생성기 · 가져오기와 나머지 지도 기능 사이의 약속이다. 마을 · 도시 · 현대 동네 생성기, Watabou 파일, OpenStreetMap 파일이 모두 이 모양을 낸다. 그리기 · 길찾기 · 건물 정보 · 이동 시간은 이 모양만 읽는다.
새 생성기나 새 가져오기를 더할 때는 이 표의 '꼭 있음' 키를 내면 된다. 새 키를 더하면 이 표에 줄을 더한다.

기준은 main `d61a100` 이다. `#140` 표시는 열린 PR [#140](https://github.com/c10dev/canon/pull/140) 에서 더하는 키다.

## 좌표

- 점은 `[x, y]` 이고 0~1 비율이다. x 는 폭 `w`, y 는 높이 `h` 의 비율이다. y 는 아래로 커진다(`atlas.read_layout` 설명).
- `w` · `h` 는 원래 단위의 폭 · 높이다. 생성기와 OSM 은 m 이다. Watabou 파일은 그 생성기의 단위이고, `Atlas.meters` 가 1단위의 m 를 정한다.
- 다각형은 점 목록이다. 처음 점을 끝에 되풀이하지 않는다.

## 키

| 키 | 모양 | 꼭 있음 | 만드는 곳 | 읽는 곳 |
|---|---|---|---|---|
| `w`, `h` | 수 | 예 | 모두 | 그리기 비율, 길찾기 거리, `bldgs.describe`, `atlas.village_title`, 축척(`Atlas.layout_size`) |
| `generator` | 글 | 예 | `read_layout`(파일 값), `canon-village` · `canon-city` · `canon-modern` · `osm` | 그리기(지붕 모양, 이름표), `bldgs.describe`(실제 · 현대 경로), `village_title` |
| `version` | 글 | 예 | 생성기 `VERSION`, 파일 값 | 읽는 곳 없음 (기록용) |
| `roads` | `[{kind: road \| bridge, width, points, name?}]` | 예, 하나 이상 | 모두. `name` 은 OSM 만 (현대 동네는 `streets` 에 이름을 짓는다) | 그리기, `road_graph` · `route`, `bldgs.describe`(거리 나누기 · 이름), #140 `_road_near` |
| `buildings` | `[다각형]` | 아니요 | 모두 | 그리기, `bldgs.describe`, `makers._blocked`, 건물 메뉴(번호 = 순서), #140 `find_spots` · `spot_line` |
| `water`, `fields`, `greens`, `squares` | `[다각형]` | 아니요 | 모두. OSM `water` 에는 해안선으로 닫은 바다(`osm._sea`)도 든다 | 그리기, `makers._blocked`(물), `bldgs.describe`(광장 · 물가), `fill`(물 · 녹지로 세고 닿는 필지를 버림) |
| `land` | `[다각형]` | 아니요 | OSM(`osm._sea`): 범위 안에 다 든 해안선 고리(섬). 다각형에 구멍을 낼 수 없어 바다 위에 땅을 다시 그린다 | 그리기(바다 위 땅 · 섬 안 밭 · 녹지 · 광장 다시 그리기), `makers._blocked` · `routes._field`(섬은 물이 아님), `bldgs.describe`(섬 둘레도 물가) |
| `coast_broken` | `true` | 아니요 | OSM(`osm._sea`): 해안선 방향이 어긋나 바다를 닫지 못함(바다를 그리지 않음) | `atlas.layout_info`(`coast_broken`), 지도 데이터 칸 알림 '해안선이 끊겨 바다를 그리지 못했어요'(`atlasLayoutBox`) |
| `rivers`, `walls` | `[{width, points}]` | 아니요 | 생성기, OSM(`rivers`), Watabou | 그리기, `makers._blocked`(강) |
| `trees` | `[점]` | 아니요 | 모두 | 그리기 |
| `houses` | 수 | 아니요 | 생성기 | `village_title`(인구), 미리보기 정보 |
| `numbers` | `[수]` | 아니요 | 생성기 | 그리기(집 번호 겹), `village_title` |
| `parts` | `[{lot, part, zone, use, …}]` 건물마다 | 아니요 | 생성기, OSM(+ `name` · `levels` · `addr` · `tenants`), `fill.fill`(지은 건물 + `levels` · `made`) | `bldgs.describe`(본채 · 곁채, 쓰임) |
| `parts[i].made` | `true` | 아니요 | `fill.fill`: 빈 블록에 지은 건물. 늘 `buildings` 끝에 모여 있다 | `bldgs._describe_osm`(이름 · 주소 · 입점 · 앞길을 비운다), 그리기(흐린 색 · 점선 `at-v-made`), `fill.clear` · `made_count`, `atlas.layout_info`(`made`) |
| `spots` | `[{key, name, kind, x, y}]` | 아니요 | 생성기 | `atlas.generate`(장소 자리 제안), `bldgs.describe`(장소 건물 이름) |
| `missing` | `[{key, name, reason}]` | 아니요 | 생성기 | `atlas.generate`(못 놓은 장소) |
| `wards` | `[{kind, shape}]` | 아니요 | 도시 · 현대 동네 | 그리기(구역 겹 · 이름), `bldgs.describe` |
| `gates` | `[점]` | 아니요 | 도시 | 그리기 |
| `source` | 글 | OSM 은 예 | OSM(`osm.SOURCE`), 빈 블록을 채우면 `fill.FILLED_SOURCE`('© OpenStreetMap 기여자 · 빈 블록 건물은 Canon 이 지음') | 그리기(출처 글), `layout_info` |
| `transit` | `{stations: [{name, x, y, lines}], lines: [{name, stations, gaps?}]}` (`stations` 는 역 번호를 노선 차례로, `gaps[i]` 는 `stations[i]` 와 `stations[i+1]` 사이 파일에 없는 역 수) | 아니요 | OSM .osm 의 지하철 역 · 노선(`osm._transit`). 역 자리는 지도 밖 3km 안까지라 0~1 밖일 수 있다(이 키만 예외) | 작품 사본 `Atlas.transit`(`atlas.fill_spots`) → 이동 시간 검사(`travel.rail` · `trip`), 그리기(역 표지 `atlasStations`, 지도 안 역만) |
| `marks` | `[{name, use, x, y}]` | 아니요 | #140 OSM: 건물 밖 이름 붙은 점 · 넓이 | #140 `find_spots`, `spot_line` |
| `blds` | 건물마다 `{use, floors, people, street?, no?, name?, addr?, tenants?, place?, made?}` 또는 곁채 `{use, of}` | 저장 때 | `bldgs.describe`(`atlas.enrich`) | 그리기(쓰임 겹, 메뉴), `atlas.building`, `village_title`(사람 수), #140 `find_spots` · `spot_line` |
| `streets` | `[{id, name, kind, width, length, roads, mid}]` (`roads` 는 `roads` 의 번호) | 저장 때 | `bldgs.describe` | 그리기(길 이름표), `atlas.building` |
| `bver` | 수 | 저장 때 | `bldgs.describe`(`bldgs.VERSION`) | `atlas.load_layout`(옛 판이면 다시 채운다) |

`blds` · `streets` · `bver` 는 생성기 · 가져오기가 내지 않는다. 저장하기 전에 `atlas.enrich` 가 붙인다.

## 판 규칙

- 생성기 결과가 바뀌면 그 생성기의 `VERSION` 을 올리고 스냅샷 시험을 고친다(`tests/test_mapgen.py`, `tests/test_citygen.py`, `tests/test_moderngen.py`). 같은 시드는 같은 지도를 낸다.
- 건물 정보 규칙이 바뀌면 `bldgs.VERSION` 을 올린다. 옛 파일은 `atlas.load_layout` 이 열 때 다시 채운다.
- 키를 지우거나 뜻을 바꾸지 않는다. 옛 파일이 `map/` 에 남아 있다. 바꿔야 하면 `load_layout` 에 옛 모양을 고치는 길을 둔다.
- 새 키는 '꼭 있음'을 '아니요'로 더한다. 읽는 곳은 키가 없을 때도 돌아가야 한다.

## 작가 값은 따로 둔다

작가가 고친 것은 지도 파일이 아니라 `project.json` 의 `Project.atlas` 에 있다: 장소 자리(`pins`), 위치 글 잇기(`links`), 고친 건물(`buildings`, 건물 번호로), 이름(`title`), 축척(`meters`), 지도 만들기 입력(`spec`), 빈 블록 채우기 입력(`fill`: `seed` · `rule`).
지도 파일을 바꾸면 건물 번호가 바뀌므로 고친 건물을 비운다(`atlas.apply_generated`, `web.atlas_layout_set`). 빈 블록 채우기는 지도 파일을 다시 쓰지만 지은 건물을 끝에 붙이므로 OSM 건물을 고친 기록은 남기고, 지은 건물을 고친 기록만 지운다(`atlas.apply_fill` · `clear_fill`). #140 의 `MapPin.spot` 은 지도 파일에서 계산한 값을 핀에 적어 둔 것이고, 지도 · 핀 · 건물을 바꿀 때 다시 쓴다. `Atlas.transit` 도 지도 파일의 `transit` 을 옮겨 적은 사본이다(같은 때 `fill_spots` 가 다시 쓴다). 키가 없는 옛 지도 파일이면 비운다.

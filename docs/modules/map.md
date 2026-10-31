# 모듈 지도: 지도

이 파일의 줄은 [AGENTS.md](../../AGENTS.md) 의 '문서 줄 규칙'을 따른다.

### `canon/atlas.py`

- 지도의 공개 면
- 계산이 없다
- `canon/maps/` 의 공개 이름을 하나씩 다시 내보낸다(`import *` 없음)
- 웹 · 명령줄 · 파이프라인 · 자동 집필 · 출생은 `atlas.이름` 으로 부른다
- 이동 시간 `maps/travel` · 장소 종류 `maps/kinds` · 프롬프트 블록 `maps/prompt` 는 이 면을 거치지 않는다(`from .maps import travel` · `kinds as placekinds` · `prompt as mapprompt`)
- 층 차례는 `tests/test_map_imports.py` 의 `TIERS`
- 명령줄 `map`
- 화면은 `static/atlas.js` 와 기능 파일 `atlas-*.js` (배경 그림 · 마을 데이터는 작품 폴더 `map/`)

### `canon/maps/blocks.py`

- 블록 · 필지 쪼개기 도구
- 길 선이 나누는 가장 작은 면(블록) 찾기(`faces`, 빈 블록 채우기)
- 직선과 선분이 만나는 곳(`line_hit`, `crossings`)
- 꼬리표 달린 볼록 다각형 자르기 · 줄이기(`cut`, `inset`)
- 다각형 안에 직사각형 · 점 놓기(`fit_rect`, `scatter`)
- 꼭짓점을 나눠 쓰는 길 덩어리(`parts`)
- `unit`
- `citygen` · `moderngen` · `fill` 이 함께 쓴다(생성기끼리 가져오지 않게)
- 바꾸면 두 생성기 스냅샷이 함께 바뀐다
- `geom` 만 가져온다
- LLM 호출 없음

### `canon/maps/buildings.py`

- 건물 정보
- 마을 · 도시 데이터(생성기 결과나 올린 파일)에 건물마다 쓰임 · 층수 · 사는 사람 · 거리 · 번지 · 간판
- 길마다 거리 이름을 더한다(`describe`)
- 생성기가 내는 `parts`(필지의 본채 · 곁채 · 헛간, 구역)를 쓴다
- `parts` 가 없으면 모두 본채로 본다
- 가게 수는 인구 ÷ SV(`TRADES`, Ross 의 Medieval Demographics Made Easy)
- 쓰임 이름은 작품 이름 스타일을 따른다(`label`)
- 현대 쓰임 `MODERN`(아파트 · 빌라 · 편의점 · 학교 등)은 실제 지도와 현대 동네 생성기 경로(`_describe_osm`)만 쓴다
- 현대 동네 생성기 지도(`MADE_MODERN`)는 쓰임 · 층수를 `parts` 에서 받고 거리 이름 · 번지만 짓는다(`_name_streets` 의 `modern`, 장소 쓰임은 `MODERN_PLACE_USE`)
- 같은 입력이면 같은 결과
- 알고리즘을 바꾸면 `VERSION` 을 올린다(옛 파일은 `atlas.load_layout` 이 다시 채운다)
- 작가가 고친 건물은 `Atlas.buildings`(`BuildingNote`)
- 읽기 · 고치기는 `atlas.building` · `set_building`
- 빈 블록에 지은 건물(`parts[i].made`, `fill`)은 `blds[i].made` 와 쓰임 · 층수 · 사람 수만 둔다(이름 · 주소 · 입점 · 앞길 없음)
- LLM 호출 없음

### `canon/maps/fill.py`

- 빈 블록 채우기(OpenStreetMap 지도만)
- 빈 블록: 길이 나누는 블록(`blocks.faces`) 가운데 건물이 10% 아래 · 물과 녹지가 절반 이하인 블록(`EMPTY` · `OPEN`)
- 둘레 절반 이상이 큰길 30m 안인 모퉁이 블록은 건너뛴다(`BIG_ROAD` · `BIG_NEAR` · `BIG_SHARE`)
- 빈 블록에 빌라촌 규칙(필지 수치는 `moderngen.DIVIDE["villa"]`, 블록 변을 따라 필지)으로 건물을 짓는다(`fill`)
- 한 변 150m 넘는 블록(`BIG`)은 아파트 단지 규칙으로 짓는다
- 지은 건물은 `buildings` · `parts` 끝에 `made: true` 로 붙여 OSM 건물 번호를 지킨다
- 지우기는 `clear`
- 출처 글 `FILLED_SOURCE`
- 쓰임은 빌라 · 단독주택 · 아파트뿐
- 미리보기 · 적용 · 지우기는 `atlas.fill_preview` · `apply_fill` · `clear_fill`(웹 `POST /atlas/layout/fill`, 입력 `Atlas.fill`)
- 명령줄 `map <작품> fill`
- 화면은 `static/atlas-fill.js`
- LLM 호출 없음

### `canon/maps/gen/citygen.py`

- 도시 생성기(지도 만들기에서 `MapSpec.kind` 가 `city` 이면 `atlas.generate` 가 부른다, `atlas.MAKERS`, 설정 칸 `OPTIONS`)
- `MapSpec`(kind `city`)으로 만드는 것
  - 구역 Voronoi
  - 강 · 바다
  - 성벽 · 성문
  - 간선도로
  - 구역 종류(`WARD_KINDS`, 같은 값을 `ZONES` 로도 낸다)
  - 블록 쪼개기와 골목(블록 도구는 `blocks`)
  - 성 밖 집 · 밭 · 숲
  - 이야기 장소 자리
- 만든 것을 `atlas.read_layout` 과 같은 모양(+ `wards`, `gates`)으로 낸다(`city`)
- 단계마다 난수원을 따로 둬 같은 입력이면 같은 도시
- 모든 길은 꼭짓점을 나눠 쓰는 한 덩어리
- 알고리즘을 바꾸면 `VERSION` 과 `tests/test_citygen.py` 스냅샷을 함께 고친다
- LLM 호출 없음
- 다른 생성기를 가져오지 않는다(장소 종류는 `kinds`)

### `canon/maps/gen/moderngen.py`

- 현대 동네 생성기(`MapSpec.kind` 가 `modern`, `atlas.MAKERS`, 설정 칸 `OPTIONS`: 크기 · 하천 · 공원)
- 대로 격자(곧은 선, 가운데 줄은 넓은 대로)와 하천 · 강변길(노이즈로 굽힌 하천과 세로 대로마다 꺾이는 곧은 강변길 조각 `_wind`, 굽은 선 밀기 `_offset`)을 긋는다
- 슈퍼블록 종류(`ZONES`: 역 앞 · 아파트 단지 · 빌라촌 · 학교 · 공원)를 정한다
- 블록을 새 길로 되풀이해 쪼갠다(`_divide`, 새 길 끝은 둘레 길 가운데 선 위 점이고 그 길의 꼭짓점으로도 넣는 `_Roads`, 블록 자르기는 `blocks.cut` · `inset`)
- 필지(`_lots`)와 건물
- 아파트 동 배치(`_rects`)
- 쓰임(`buildings.MODERN` id, `SHOPS` · `CIVIC`)과 층수를 `parts` 에 적어 `atlas.read_layout` 과 같은 모양(+ `wards`)으로 낸다(`neighborhood`)
- 단계마다 난수원을 따로 둬 같은 입력이면 같은 동네
- 이야기 장소 종류는 현대 id(`kinds.kind_ids("modern")`, 옛 id 는 `to_era` 로 읽고 대응이 없으면 `house`)다
- 자리 규칙은 `_place_spots`
- 자리 글은 `KIND_SPOTS`
- 놓인 건물 쓰임 바꾸기는 `USE_OF`
- `roadnet.grow` 는 쓰지 않는다(격자 목표를 주면 고리 · 막다른 길이 된다)
- 알고리즘을 바꾸면 `VERSION` 과 `tests/test_moderngen.py` 스냅샷을 함께 고친다
- LLM 호출 없음

### `canon/maps/gen/roadnet.py`

- 길망
- Parish–Müller 식 지역 규칙으로 길을 키운다(`Net`)
- 정해 둔 길 넣기(`add`, 지나는 곳에 두 길 모두 꼭짓점)
- 간선 모양(`walk`)
- 우선순위 큐로 가지길 함께 키우기(`grow`: 앞 길에 늘려 잇기, 가까운 마디에 붙기, 최소 각도, 나란히 너무 가까우면 멈춤, 전역 목표 `goal`)
- 막다른 끝 이어 고리 만들기(`close_loops`)
- 강 위를 다리로 나누기(`bridges`)
- 물 · 영역 · 필지는 `blocked` 콜백으로 받는다
- 길끼리는 같은 점(튜플)을 꼭짓점으로 함께 써서 `atlas.road_graph` 에서 이어진다
- `geom` 재사용
- LLM 호출 없음

### `canon/maps/gen/towngen.py`

- 마을 생성기
- `MapSpec`(시드, 크기 · 길 모양 · 물 · 밭 · 숲)으로 길(`roadnet`) · 다리 · 필지(가운데 연립 줄 · 바깥 농가 헛간) · 상징 건물(`_landmark`) · 집 · 밭 · 나무를 만들어 `atlas.read_layout` 과 같은 모양으로 낸다(`village`)
- 단계마다 난수원을 따로 둬 같은 입력이면 같은 마을
- 장소 종류별 자리 고르기(종류는 `kinds`)
- AI 설정 제안은 `pipeline.suggest_map`(`MapSuggestion`, `plan` 단계)
- 알고리즘을 바꾸면 `VERSION` 과 `tests/test_mapgen.py` 스냅샷을 함께 고친다
- LLM 호출 없음
- 도시는 `citygen`
- 왕국은 다음 단계

### `canon/maps/geom.py`

- 지도 생성기의 기하 도구
- 다각형(넓이 · 무게중심 · 겹침 · 자르기)
- Delaunay · Voronoi · Lloyd
- 노이즈
- Poisson disk
- 격자 찾기
- 순수 파이썬
- 지도를 모른다

### `canon/maps/kinds.py`

- 지도 장소 종류
- 모든 생성기가 쓰는 종류 표(`KINDS`, `Kind`: id · 화면 이름 · 시대 old · modern · both · 단어)
- 지도 종류의 시대(`era_of`, `MAP_ERA`: 마을 · 도시는 old, 현대 동네는 modern)와 그 시대의 종류(`kinds_for` · `kind_ids`, 화면 이름 `label`)
- 옛 시대 3칸 목록(`CATEGORIES`, `CATEGORY_IDS`, 옛 호출부용으로 그대로)
- 이름 · 설명의 단어로 고르기(`classify(name, desc, era="old")`, 못 찾으면 `FALLBACK`)
- 옛 id ↔ 현대 id 대응(`to_era`, `OLD_TO_MODERN` · `MODERN_TO_OLD`)
- 지도에 놓는지 기본값(`default_put`)
- 놓을 장소가 바라는 물(`water_for`, `atlas.default_spec`)
- 계약은 `docs/map/specs/08-modern-kinds.md` '종류 표'
- 아무 지도 모듈도 가져오지 않는다
- LLM 호출 없음

### `canon/maps/layout.py`

- 지도 데이터 형식
- 올린 파일 가르기(`parse_upload`) · 읽기(`read_layout`) · 불러오기(`load_layout`, 옛 건물 정보는 다시 채운다) · 넓히기(`enrich`)
- 마을 데이터(Watabou 생성기 JSON `read_layout`, OpenStreetMap 은 `osm.parse`, 가르기는 `parse_upload`)
- `travel` · `context` 를 가져오지 않는다(지도 화면의 이동 시간 칸은 `web.atlas_view` 가 붙인다)
- LLM 호출 없음

### `canon/maps/makers.py`

- 지도 만들기 · 지도 시대(`map_era`) · 빈 블록 채우기 적용
- 지도 만들기(마을 생성기 `towngen`)의 장소 표(`gen_places`: 종류는 지도 종류의 시대 id, 저장된 종류는 `kinds.to_era` 로, 시대별로 찾은 값 `found_in`)
- 지도 종류마다 종류 목록(`gen_info` 의 `kinds` · `eras` · `kind_to`)
- 미리보기(`generate`, 저장 안 함)
- 적용(`apply_generated`, `Atlas.spec`)
- 옛 그림 · 마을 파일 지우기(`drop_old_file`: map/ 안의 맨 파일 이름만, web · cli 가 함께 씀)
- 마을 이름 · 인구(`village_title`, `Atlas.title`)
- 만들 수 있는 지도 종류와 생성기(`MAKERS`: 마을 `towngen`, 도시 `citygen`, 현대 동네 `moderngen`. 설정 칸 `OPTIONS` · 버전 · 구역 이름 `ZONES` 는 이것으로만 읽는다)
- 빈 블록 채우기 미리보기 · 적용 · 지우기(`fill_preview` · `apply_fill` · `clear_fill`)
- `travel` · `context` 를 가져오지 않는다(지도 화면의 이동 시간 칸은 `web.atlas_view` 가 붙인다)
- LLM 호출 없음

### `canon/maps/places.py`

- 지도 장소 · 핀 · 위치 글
- 장소(설정 장소 칸 + 인과율 '장소' 요소, `places`, 지도 화면 값 `summary` 는 지금 지도 시대 `map_era` 의 종류 `place_kinds` 를 `kind` 로 싣는다) 위에 자리 · 배경 그림 · 위치 글 잇기(`Project.atlas`)를 얹는다
- 지도에서 장소 더하기(`add_place`)
- 이름 후보(`name_ideas`)
- 인물 위치 글을 장소와 맞추기(`match`)
- 화별 인물 자리(`frames`, `cast.walk` 재사용)
- 장소와 맞지 않은 위치 글(`unmatched`)과 한 번에 정리(`clean_sort`, `apply_sort`, AI 제안은 `pipeline.sort_places`)
- `travel` · `context` 를 가져오지 않는다(지도 화면의 이동 시간 칸은 `web.atlas_view` 가 붙인다)
- LLM 호출 없음

### `canon/maps/prompt.py`

- 지도 프롬프트 블록
- `travel.episode_moves` · `atlas.episode_spots` 의 줄 데이터를 쓰기 · 검수 프롬프트 글로 바꾸고 예산(`context.BUDGET["travel"]` · `["spots"]`)에 맞춰 뺀 수를 적는다
  - `travel_block`: 지하철이 빠른 줄은 '지하철로 약 n분 (역 → 역 n정거장, …)'
  - `travel_check_rule`
  - `spot_block`
- `prompts.py` 가 부른다
- LLM 호출 없음

### `canon/maps/routes.py`

- 길찾기
- 길 따라 동선 · 거리(`road_graph`, `route`, `add_routes`)
- 걷는 속도 `WALK_MPS` · 격자 `WALK_GRID`
- `travel` · `context` 를 가져오지 않는다(지도 화면의 이동 시간 칸은 `web.atlas_view` 가 붙인다)
- LLM 호출 없음

### `canon/maps/sources/osm.py`

- 실제 지도
- OpenStreetMap .osm(XML) · overpass-turbo GeoJSON 을 `atlas.read_layout` 과 같은 모양으로(`parse`, 올리기는 `atlas.parse_upload` 가 가름 `is_osm`)
- 평면 m 좌표 · 범위 자르기
- 길 폭(width · lanes · 종류 `WIDTHS`)
- 땅속 · 지붕 빼기
- multipolygon 고리(`_rings`)
- 끊긴 큰 물 닫기(`_close_open`)
- 바다는 해안선(natural=coastline, 바다가 오른쪽)을 잇고 테두리로 닫아 `water` 에(`_sea`, 섬은 새 키 `land`, 닫지 못하면 `coast_broken`)
- 건물 쓰임(`use_of`, `buildings.MODERN`) · 이름 · 층수 · 주소 · 입점한 곳을 `parts` 에
- 건물 정보는 `buildings._describe_osm`(태그 그대로, 이름 · 번지를 짓지 않음)
- 출처 `SOURCE`(ODbL)를 지도에 그린다
- 건물 밖 이름 붙은 점 · 넓이는 표지 `marks`(`_stop`, 철길 정차 위치는 빼기 `_rail_stop`)
- 지하철 역 · 노선(정차 차례, 두 방향 묶기, 파일에 없는 역 수 `gaps`, 지도 밖 `TRANSIT_PAD` 안 역)은 `transit`(`_transit`, .osm 만, 작품 사본은 `atlas.fill_spots` 가 `Atlas.transit` 에)
- 빈 블록 채우기는 `fill` 이 하고 이 모듈은 고치지 않는다
- LLM 호출 없음

### `canon/maps/spots.py`

- 자리 찾기 · 건물 한 줄
- 이름으로 자리 찾기(`find_spots`: 장소 이름과 같은 건물 · 표지 · 입점)
- 장소가 놓인 건물 한 줄(`MapPin.spot`, `spot_line` · `fill_spots`, 줄이 빈 옛 핀만 채우기 `fill_old_spots`: 지도 화면은 응답에만, 쓰기 · 검수 작업은 web · cli · autorun 이 시작할 때 채워 저장, 쓰기 · 검수 블록의 줄 데이터 `episode_spots`, 글은 `prompt.spot_block`)
- `travel` · `context` 를 가져오지 않는다(지도 화면의 이동 시간 칸은 `web.atlas_view` 가 붙인다)
- LLM 호출 없음

### `canon/maps/travel.py`

- 이동 시간 검사
- 인물이 옮겨 간 거리와 그동안 지난 작품 속 시간을 이 세계의 가장 빠른 탈것(`TravelSetting`, `MODES`, `speed` · `need`)과 견준다
- 거리: 장소 자리 사이 곧은 거리 × 길 굽음 `DETOUR`
- 지도 크기는 `Atlas.layout_size` × 축척 또는 `Atlas.span_km`(`scale` · `km`)
- 지난 시간: `Episode.time` 을 가장 넉넉하게 읽은 `window`, 시간대 글 `hours`
- 대중교통(`mode` `transit`)은 장소 사이마다 걸어서만과 지하철(`rail`: 작품 사본 `Atlas.transit` 위 (역, 노선) 최단 경로, 표정속도 `RAIL_KMH` · 기다림 · 갈아타기 · 역 안 걷기 분, 출처는 `docs/map/specs/06-subway.md`) 가운데 짧은 쪽(`trip`, 글 `rail_text`)
- 반영한 화의 이동(`moves`, 지도 화면 `view`: 지하철로 센 이동 `rail`)
- 상태 변경안 경고(`delta_warnings`, `pipeline.clean_delta`)
- '괜찮아요'(`accept`)
- 쓰기 · 검수 프롬프트의 이동 거리 줄 데이터(`episode_moves`, 글과 검수 줄은 `prompt.travel_block` · `travel_check_rule`)
- 명령줄 `map <작품> travel`
- 마을 길 데이터(`atlas.route`)는 쓰지 않는다
- LLM 호출 없음
- 화면은 `static/atlas-travel.js` 의 `atlasTravelBox`

### `canon/maps/view.py`

- 지도 화면 값(`summary`)과 명령줄 출력(`describe`)
- `places` · `makers` 사이의 import 고리를 피하려고 따로 둔다
- LLM 호출 없음

### `canon/static/atlas-export.js`

- 지도 화면 기능 파일
- 내보내기(`atlasExportSvg`, SVG · PNG `atlasExport`)

### `canon/static/atlas-fill.js`

- 지도 화면 기능 파일
- 빈 블록 채우기(`atlasFillBox` · 미리보기 `atlasFillSvg` · `atlasFillApply` · `atlasFillClear`, 지은 건물 그리기는 `atlas.js` 의 건물 그리기 `at-v-made`)

### `canon/static/atlas-find.js`

- 지도 화면 기능 파일
- 이름으로 자리 찾기(`atlasFindLoad` · `atlasFindBox` · `atlasFindApply`)

### `canon/static/atlas-gen.js`

- 지도 화면 기능 파일
- 지도 만들기(`atlasGen*`: 설정 칸 · 지도 종류의 장소 종류 드롭다운 `atlasGenKinds` · 지도 종류를 바꿀 때 종류 옮기기 `atlasKindShift`(순수 함수, `tests/test_atlas_kinds.py`) · 미리보기 · 미리보기 막대 `atlasGenBar` · AI 설정 제안 · 적용)

### `canon/static/atlas-icons.js`

- 지도 화면 기능 파일
- 장소 종류 기호와 범례
  - 기호 표 `ATLAS_GLYPHS` · 종류 → 기호 `ATLAS_ICON_OF`(`kinds.KINDS` 와 같은 id, `tests/test_atlas_icons.py`) · 핀 기호 `atlasIconSvg` · 범례 줄 `atlasLegendKinds` · 칸 나누기 `atlasLegendFit` · 그리기 `atlasLegend`
  - 장소 종류는 서버 `atlas.summary` 의 `kind`

### `canon/static/atlas-table.js`

- 지도 화면 기능 파일
- 어디에 있었나 표(`atlasTable`)와 장소와 맞지 않은 위치(`atlasUnmatched`, AI 정리 `atlasSort` · 적용 `atlasApply`)

### `canon/static/atlas-travel.js`

- 지도 화면 기능 파일
- 이동 시간 검사 칸(`atlasTravelBox`, '괜찮아요' `atlasTravelOk`)

### `canon/static/atlas.js`

- 지도 화면 뼈대
- 상태 · 불러오기(`atlasLoad`, 미리보기 · 자리 찾기 상태 `atlasGenPreview` · `atlasFindNow`)
- 지도 그림(`atlasSvg`, 마을 `atlasVillageSvg`)
- 화면을 모르는 계산
  - 되돌리기 `atlasPinDiff` · `atlasPinApply`
  - 자리 찾기 처음 고름 `atlasFindDefault` · `atlasFindPins`
  - 따라가기 `atlasFollowView`
  - 같은 이름 거리 · 구역 이름표 고르기 `atlasLabelPick` · `atlasWardPick`
  - 인물 표 자리 `atlasTokenAt`
  - 축척 막대 둥근 값 `atlasScaleBar`
  - 인물 잉크 · 흑백 인쇄 무늬 `atlasInk` · `ATLAS_DASHES`
  - 화풍 기본값 `atlasStyleFor`(평지붕 지도 `atlasFlat` 는 '현대')
  - 길 위계 `atlasRoadRank` · `atlasRoadRanks`
  - 현대 화풍 건물 톤 `atlasModernTone` · 층수 그림자 `atlasShadowLen` · `atlasShadowPath`
  - 동선 화살표 · 화 번호 점 자리 `atlasTrailMarks` · 겹친 점 빼기 `atlasTrailDots`
  - `tests/test_atlas_js.py` 가 섹션 주석으로 잘라 돌린다
- 화풍 다섯(`ATLAS_STYLES`, 단축키 1~5, 지금 화풍 `atlasStyleNow`, 마을 · 도시와 평지붕 지도를 따로 기억 `S.atlasStyles`)
- 인물 색은 화풍별 CSS 변수 `--v-ink0`…`--v-ink9`(옆 칸 · 표 견본 `atlasSwatch`)
- 지도 장식(`atlasDeco`: 제목 틀 · 축척 막대 · 북쪽 화살표(OSM 만) · 출처 글 · 왼쪽 아래 범례(`atlas-icons.js`), 겹 '장식' D, 이름표보다 먼저 `taken`, 지도 단위의 m `atlasMpu`)
- 확대 · 이동 · 이름표(`atlasLabels`, 놓는 차례: 장식 · 인물 표 → 장소 이름표 → 구역 → 길)
- 옆 칸(`atlasSide`)과 화면 조립(`viewAtlas`, `atlasRefresh`)
- 저장(`atlasSavePins`)
- 장소 이동 되돌리기
- 재생할 때 따라가기
- 공통 동작과 입력(끌어 옮기기 · 단축키 · 파일 올리기)
- CSS
- 기능은 바로 뒤에 읽는 파일에 있다
- 기능 파일은 `Object.assign(actions, ...)` 와 그 기능의 `change` 처리로 붙는다
- 기능 파일은 `index.html` 에서 `atlas.js` 바로 뒤에 `atlas-icons.js` · `atlas-gen.js` · `atlas-travel.js` · `atlas-table.js` · `atlas-export.js` · `atlas-find.js` · `atlas-fill.js` 차례로 읽는다

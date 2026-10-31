# 02. `canon/maps/` 패키지로 옮기기

상태: 구현 · 계획: [plan.md](../plan.md) 의 2번 · 설계: [modules.md](../modules.md) 4절

## 목표

동작은 바뀌지 않는다. 지도 Python 코드를 `canon/maps/` 한 폴더에 모으고 `canon/atlas.py` 를 공개 면으로 남긴다. 다음 지도 일감은 `canon/maps/` 만 보면 된다.

## 정할 것

1. 공개 면을 남길지 — 정함(2026-10-28): 남긴다. `canon/atlas.py` 는 `canon/maps/*` 의 이름을 다시 내보내고, `web.py` · `cli.py` · `pipeline.py` · `prompts.py` · `birth.py` · `features.py` 는 고치지 않는다. 다른 안: 부르는 곳을 모두 `canon.maps` 로 고친다(main 의 `web` · `cli` · `pipeline` · `prompts` · `birth` · `features` · `mock` 에서 지도 모듈 이름을 104번 부른다).
2. 생성기 모듈 이름 — 정함(2026-10-29, 추천안): 지금 이름을 지킨다(`maps/gen/towngen.py` 등). 시험 · 문서 · 기록에 그 이름이 많다.
3. `cli` · `pipeline` · `mock` 이 장소 종류를 읽는 길 — 정함(2026-10-29): 공개 면을 거치지 않고 `from .maps import kinds as placekinds` 로 바로 가져온다. `kinds` 는 아무 지도 모듈도 가져오지 않는 표라 바로 가져와도 순환 위험이 없고, 공개 면에 종류 이름 열 개 남짓을 더 얹으면 `atlas` 가 '장소 · 지도' 밖의 이름까지 맡게 된다. `travel` · `prompt` 도 같은 꼴로 바로 가져온다(아래 표).

## 바꿀 곳

| 지금 | 옮길 곳 |
|---|---|
| `canon/atlas.py` 의 장소 · 핀 · 잇기 · frames · 위치 글 정리 | `canon/maps/places.py` |
| `canon/atlas.py` 의 Watabou 읽기 · 지도 파일 · `parse_upload` · `layout_info` · `enrich` | `canon/maps/layout.py` |
| `canon/atlas.py` 의 길찾기 · 길 밖 걷기 · `add_routes` | `canon/maps/routes.py` |
| `canon/bldgs.py` + `atlas.building` · `set_building` · `building_counts` | `canon/maps/buildings.py` |
| `canon/atlas.py` 의 `find_spots` · `spot_line` · `fill_spots` (#140) | `canon/maps/spots.py` |
| `canon/atlas.py` 의 `MAKERS` · `gen_places` · `gen_info` · `generate` · `apply_generated` | `canon/maps/makers.py` |
| `canon/towngen.py` · `citygen.py` · `moderngen.py` · `roadnet.py` | `canon/maps/gen/` |
| `canon/osm.py` | `canon/maps/sources/osm.py` |
| `canon/geom.py` · `canon/travel.py` | `canon/maps/` |
| 01 의 `blocks.py` · `placekinds.py` · `mapprompt.py` | `canon/maps/blocks.py` · `kinds.py` · `prompt.py` |
| `features.py` · `web.py` · `cli.py` 의 `from . import travel` | `from .maps import travel` (공개 면은 `atlas` 이름만 맡는다) |
| `tests/` 에서 지도 모듈을 가져오는 9개 파일의 `from canon import towngen` 등 | `from canon.maps.gen import towngen` 등 |
| `canon/fill.py` (04, 빈 블록 채우기 알고리즘) | `canon/maps/fill.py` |
| `canon/atlas.py` 의 빈 블록 채우기 적용 `fill_preview` · `made_count` · `apply_fill` · `clear_fill` · `_write_fill` (04) | `canon/maps/makers.py` (`enrich` · `fill_spots` 를 부른다) |
| `canon/atlas.py` 의 `map_era` (08a) · `MODERN_STYLES` | `canon/maps/makers.py` (`moderngen` · `osm` 을 본다) |
| `canon/atlas.py` 의 `place_kinds` (15) | `canon/maps/places.py` |
| `canon/atlas.py` 의 `summary` · `describe` | 새 `canon/maps/view.py` (아래 구현 메모) |
| `canon/atlas.py` 의 `village_title` · `set_title` · `POP_PER_HOUSE` | `canon/maps/makers.py` (`gen_places` 를 부른다) |
| `canon/atlas.py` 의 `add_place` · `name_ideas` · `set_pins` · `set_link` · `prune` · `clean_sort` · `apply_sort` | `canon/maps/places.py` |
| `canon/atlas.py` 의 `fill_old_spots` · `episode_spots` (#140 · 일감 뒤) | `canon/maps/spots.py` |
| `canon/atlas.py` 의 `set_meters` · `IMAGE_*` · `LAYOUT_LIMIT` | `canon/maps/layout.py` |
| `osm._sea` · `_transit` (05 · 06) | `osm.py` 와 함께 `canon/maps/sources/osm.py` |
| `travel.trip` · `rail` 등 지하철 (06) | `travel.py` 와 함께 `canon/maps/travel.py` |
| `placekinds` 의 시대 표 `KINDS` · `ERAS` · `kinds_for` · `to_era` (08a) | `placekinds.py` 와 함께 `canon/maps/kinds.py` |
| `prompts.py` 의 `from . import mapprompt`, `cli` · `pipeline` · `mock` 의 `placekinds` | `from .maps import prompt as mapprompt`, `from .maps import kinds as placekinds` (정할 것 3) |

`canon/atlas.py` 의 `describe`(명령줄 출력)는 `canon/maps/places.py` 로 간다. — 구현은 `canon/maps/view.py` (구현 메모).

01 이 남긴 것도 여기서 정리한다([01 구현 메모](01-boundaries.md#구현-메모-2026-10-28)):

- `travel.episode_block` · `atlas.episode_block` 감싸개와 `towngen` 의 다시 내보내기를 지우고, 시험(`test_travel.py` · `test_osm.py` · `test_mapgen.py` 등)이 새 이름을 부르게 한다.
- `cli` · `pipeline` · `mock` 이 `placekinds` 를 바로 읽는 것을 공개 면으로 거칠지 정한다.
- `schema.py` 설명 글의 옛 이름을 새 이름으로 고친다.

## 지도 데이터

바뀌지 않는다. 같은 시드의 지도 데이터가 바이트까지 같다.

## 규칙

- `git mv` 로 옮겨 기록을 잇는다. 옮기는 커밋과 가져오기를 고치는 커밋을 나눈다.
- 공개 면은 `from .maps.places import places, match, …` 처럼 이름을 하나씩 적는다. `import *` 를 쓰지 않는다.
- 몸은 고치지 않는다.

## 시험

[modules.md](../modules.md) 5절의 받아들이는 조건 넷. 01 의 가져오기 그래프 시험을 `canon/maps/` 기준으로 고친다.

## 문서

AGENTS.md 의 지도 줄을 `canon/maps/` 아래로 묶는다. DESIGN.md 의 파일 이름. [modules.md](../modules.md) 1 · 2절을 새 구조로.

## 확인하지 못할 것

Swift 빌드(맥). `openapi.json` 이 같으면 영향이 없다.

## 구현 메모 (2026-10-29)

옮긴 파일(`git mv`, 첫 커밋은 옮기기만):

| 전 | 뒤 |
|---|---|
| `canon/atlas.py` | `canon/maps/places.py` (나머지는 둘째 커밋에서 `layout` · `routes` · `spots` · `makers` · `view` · `buildings` 로 나눔) |
| `canon/bldgs.py` | `canon/maps/buildings.py` |
| `canon/towngen.py` · `citygen.py` · `moderngen.py` · `roadnet.py` | `canon/maps/gen/` 같은 이름 |
| `canon/osm.py` | `canon/maps/sources/osm.py` |
| `canon/geom.py` · `travel.py` · `fill.py` · `blocks.py` | `canon/maps/` 같은 이름 |
| `canon/placekinds.py` | `canon/maps/kinds.py` |
| `canon/mapprompt.py` | `canon/maps/prompt.py` |
| 새 파일 | `canon/atlas.py`(공개 면 31줄), `canon/maps/view.py`, `__init__.py` 셋 |

명세서와 다르게 한 곳:

- `summary` · `describe` 는 `places.py` 가 아니라 새 `view.py` 에 두었다. `summary` 가 `village_title`(→ `gen_places` → `places`)과 `add_routes` · `layout_info` 를 부르고, `describe` 는 `summary` 를 부른다. `places.py` 에 두면 `places` ↔ `makers` 순환이 생긴다.
- 층 차례가 [modules.md](../modules.md) 4절 글과 다르다. `layout`(`load_layout` · `enrich`)이 `buildings.describe` · `VERSION` 을 부르므로 `buildings` 가 `layout` 아래다. `routes` 는 지도 모듈을 가져오지 않는다. `fill` 은 `gen.moderngen` 의 수치를 읽어 생성기 위 층이다. 실제 층은 modules.md 2절과 `tests/test_map_imports.py` 의 `TIERS`.
- 함수 몸을 고친 곳: `buildings.py` 로 들어온 `building` · `building_counts` · `set_building` 에서 `bldgs.` 를 뗐다(같은 모듈이 되었다). `travel.py` 에서 `atlas.places` · `frames` · `match` · `mentions` 의 `atlas.` 를 뗐다(`from .places import …`). `prompt.py` 에서 `atlas.episode_spots` 의 `atlas.` 를 뗐다. 나머지 몸은 그대로다. 그대로 두려고 `canon/maps/` 안에서는 `from . import buildings as bldgs` · `from . import kinds as placekinds` 로 가져온다.
- 바깥이 바로 가져오는 것: `travel`(`web` · `cli` · `features` · `prompts`), `kinds`(정할 것 3), `prompt`(`prompts`). 공개 면은 `atlas` 이름만 맡는다. 지역 변수 `kinds` · `prompt` 와 겹치지 않게 `as placekinds` · `as mapprompt` 로 가져온다.
- 공개 면은 옛 `atlas.py` 의 공개 이름(밑줄 없는 이름)을 모두 내보낸다. 밑줄 이름을 부르던 시험은 새 모듈을 부른다(`routes._walk`, `makers._blocked`). `atlas.BuildingNote` 는 `canon.schema` 에서 가져온다.
- 01 이 남긴 정리: `travel.episode_block` · `atlas.episode_block` 감싸개와 `towngen` 의 다시 내보내기(`CATEGORIES` · `classify` · `water_for` · `default_put`)를 지웠다. 시험은 `mapprompt.travel_block` · `spot_block` 과 `placekinds.*` 를 부른다. `schema.py` 설명 글의 옛 이름 · 경로, `web.py` · `cli.py` 독스트링의 경로(`canon/fill.py`, `canon/travel.py`)도 고쳤다. `web.py` 독스트링과 `schema.py` 설명은 `openapi.json` 에 들어가지만 Swift 개발을 멈춰서 다시 만들지 않았다.

확인한 것:

- 같은 입력의 결과가 바이트까지 같다: 옮기기 전(main `2116824`)과 뒤에 마을 · 마을(강) · 도시 · 도시(바다) · 현대 동네(하천 없음 · 있음)를 시드 1 · 4 · 17 로 만든 미리보기와 길망, `gen_info`, OSM 파일 셋(망원 · 강남 · 해운대)의 읽기 · 빈 블록 채우기 미리보기 · 자리 찾기, 이동 거리 · 장소가 놓인 건물 시험 작품의 쓰기 · 검수 프롬프트 전체, 지도 화면 값 · 명령줄 출력, 지하철 시험 작품의 화면 값과 쓰기 프롬프트(57개)를 JSON 하나로 떠서 `cmp` 로 견줬다. 생성기 스냅샷 시험은 고치지 않고 통과한다(`VERSION` 그대로).

남은 것:

- 화면 파일 머리 주석의 옛 경로(`atlas-gen.js` 의 `canon/towngen.py` 등, `atlas-fill.js` · `atlas-travel.js` · `atlas-icons.js`)는 고치지 않았다. `canon/static/` 은 다른 세션이 고칠 수 있어서다.
- 모듈 몸의 독스트링 · 주석 가운데 `atlas.read_layout` 처럼 공개 면 이름을 적은 곳은 그대로 맞아서 두었다.

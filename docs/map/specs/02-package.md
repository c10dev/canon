# 02. `canon/maps/` 패키지로 옮기기

상태: 설계 · 계획: [plan.md](../plan.md) 의 2번 · 설계: [modules.md](../modules.md) 4절

## 목표

동작은 바뀌지 않는다. 지도 Python 코드를 `canon/maps/` 한 폴더에 모으고 `canon/atlas.py` 를 공개 면으로 남긴다. 다음 지도 일감은 `canon/maps/` 만 보면 된다.

## 정할 것

1. 공개 면을 남길지 — 정함(2026-10-28): 남긴다. `canon/atlas.py` 는 `canon/maps/*` 의 이름을 다시 내보내고, `web.py` · `cli.py` · `pipeline.py` · `prompts.py` · `birth.py` · `features.py` 는 고치지 않는다. 다른 안: 부르는 곳을 모두 `canon.maps` 로 고친다(main 의 `web` · `cli` · `pipeline` · `prompts` · `birth` · `features` · `mock` 에서 지도 모듈 이름을 104번 부른다).
2. 생성기 모듈 이름 — 추천: 지금 이름을 지킨다(`maps/gen/towngen.py` 등). 시험 · 문서 · 기록에 그 이름이 많다.

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

`canon/atlas.py` 의 `describe`(명령줄 출력)는 `canon/maps/places.py` 로 간다.

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

"""지도의 공개 면: 화면(web) · 명령줄(cli) · 파이프라인 · 자동 집필 · 출생이 부르는 지도 이름을 canon/maps/ 에서 다시 내보낸다.

장소는 따로 정의하지 않는다. 설정의 장소 칸(world.locations)과 인과율 '장소' 요소가 장소이고,
지도(Project.atlas)는 그 위에 자리(pins), 배경 그림, 위치 글 잇기(links)만 더한다 (maps/places.py).
마을 · 도시 데이터를 올리거나(maps/layout.py) 지도 만들기로 만들면(maps/makers.py, 생성기는 maps/gen/) 건물 · 길 · 물을 바탕으로 그리고,
화별로 옮겨 간 인물은 길을 따라 걸은 경로와 거리 · 걷는 시간을 붙인다 (maps/routes.py).

이 파일에는 계산이 없다. 이름은 하나씩 적는다 (import * 를 쓰지 않는다). 이동 시간 검사(maps/travel.py),
장소 종류(maps/kinds.py), 프롬프트 블록(maps/prompt.py)은 이 면을 거치지 않고 바로 가져온다.
화면은 canon/static/atlas.js, 명령줄은 `map`.
"""
from __future__ import annotations

from .maps.buildings import building, building_counts, set_building  # noqa: F401
from .maps.layout import (  # noqa: F401
    AREAS, IMAGE_LIMIT, IMAGE_TYPES, LAYOUT_LIMIT, STROKES, WALKABLE, enrich, layout_info, load_layout, parse_upload,
    read_layout, set_meters,
)
from .maps.makers import (  # noqa: F401
    CITY_POP_PER_HOUSE, MAKERS, MODERN_STYLES, POP_PER_HOUSE, apply_fill, apply_generated, clear_fill, default_spec,
    fill_preview, gen_info, gen_places, generate, made_count, map_era, set_title, village_title,
)
from .maps.places import (  # noqa: F401
    SORT_CHUNK, add_place, apply_sort, clean_sort, frames, match, mentions, name_ideas, place_by_name, place_kinds,
    places, prune, set_link, set_pins, unmatched,
)
from .maps.routes import WALK_GRID, WALK_MPS, add_routes, road_graph, route  # noqa: F401
from .maps.spots import (  # noqa: F401
    FIND_LIMIT, MARK_WORDS, SPOT_NEAR, episode_spots, fill_old_spots, fill_spots, find_spots, spot_line,
)
from .maps.view import describe, summary  # noqa: F401

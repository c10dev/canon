"""건물 하나하나에 쓰임 · 층수 · 사는 사람 · 주소를, 길에 이름을 붙인다. LLM 을 부르지 않는다.

마을 · 도시 생성기(towngen, citygen)가 낸 지도나 올린 Watabou 파일(read_layout 모양)을 받아 아래를 더한다 (`describe`).
- streets: 길 선을 이어 붙인 거리와 이름. 이어진 길 조각 가운데 곧게 이어지고 폭이 같은 것끼리 한 거리다.
- blds: buildings 와 같은 순서의 건물 정보. 본채는 쓰임 · 층수 · 사는 사람 · 거리 · 번지 · 간판 이름, 곁채 · 헛간은 본채 번호(of).

쓰임은 인구에 맞춰 정한다. '인구 몇 명이 가게 하나를 먹여 살리는지'(TRADES 의 SV, S. John Ross, Medieval Demographics
Made Easy v1.10 의 표. Ross 는 1292 년 파리 세금 장부에서 가져왔다고 쓴다)로 인구 ÷ SV 개를 둔다. 소수 부분은 그만큼의
확률로 하나 더 둔다. 그래서 SV 보다 작은 마을에서는 인구 ÷ SV 가 그 가게가 있을 확률이다 (Ross 의 규칙). 지도마다
SV 를 (4d4 - 10) × 10% 만큼 흔든다 (Ross 의 도시별 편차).
사는 사람은 주거 한 칸에 2~5명(Ross: 보통 3명), 층수는 1~3층(Ross: 목조 · 반목조 건물)이다.
번지는 작가가 건물을 가리키기 쉽게 붙인다. 중세 도시에는 번지가 거의 없었고 간판이나 집 이름으로 가리켰다(번지가 널리
쓰인 것은 1750~70년대). 그래서 여관 · 주점에는 간판 이름을 붙인다.
가게는 종류마다 좋아하는 자리(광장 가까이, 큰길가, 물가, 마을 끝, 도시 구역)에 점수를 매겨 고른다.
이야기 장소가 놓인 건물은 그 장소의 종류와 이름을 쓴다. 생성기가 알려 준 필지 정보(parts)가 없으면(올린 파일) 모든 건물을 본채로 본다.
OpenStreetMap 지도(canon/osm.py)는 쓰임 · 이름 · 주소를 태그에서 가져오고 가게 수 · 간판 · 번지를 짓지 않는다 (_describe_osm).
현대 동네 생성기(canon/moderngen.py)도 쓰임 · 층수는 생성기가 정한 parts 를 그대로 쓰고, 거리 이름 · 번지만 짓는다 (가상의 동네라서).

같은 지도 · 시드 · 장소면 언제나 같은 결과다 (난수원 f"{seed}:bldgs:{단계}"). 알고리즘을 바꾸면 VERSION 을 올린다.
"""
from __future__ import annotations

import math
import random
from typing import Callable, Optional

from . import geom
from .geom import Point

VERSION = 1

# 쓰임: id → (화면 이름, 묶음). 묶음은 지도 색과 범례에 쓴다
USES: dict[str, tuple[str, str]] = {
    "home": ("집", "home"), "farm": ("농가", "home"), "tenement": ("셋집", "home"), "mansion": ("저택", "noble"),
    "barn": ("헛간", "store"), "annex": ("곁채", "home"), "warehouse": ("창고", "store"), "tower": ("등대", "civic"),
    "temple": ("신전", "faith"), "shrine": ("사당", "faith"), "hall": ("장터 회관", "civic"), "office": ("관아", "civic"),
    "inn": ("여관", "lodging"), "tavern": ("주점", "lodging"),
    "smith": ("대장간", "craft"), "carpenter": ("목공소", "craft"), "mason": ("석공", "craft"), "cooper": ("통 공방", "craft"),
    "weaver": ("베 짜는 집", "craft"), "tanner": ("무두질 집", "craft"), "potter": ("옹기 공방", "craft"),
    "shoemaker": ("신발 가게", "shop"), "tailor": ("옷 가게", "shop"), "barber": ("이발소", "shop"), "jeweler": ("보석상", "shop"),
    "chandler": ("초 가게", "shop"), "mercer": ("포목점", "shop"), "spice": ("향신료 가게", "shop"), "general": ("잡화점", "shop"),
    "baker": ("빵집", "food"), "butcher": ("푸줏간", "food"), "fishmonger": ("생선 가게", "food"), "brewer": ("술도가", "food"),
    "mill": ("방앗간", "food"),
    "doctor": ("의원", "care"), "bathhouse": ("목욕탕", "care"), "chapel": ("예배당", "faith"),
    "furrier": ("모피 가게", "shop"), "oldclothes": ("헌옷 가게", "shop"), "pastry": ("과자 가게", "food"),
    "wine": ("포도주 가게", "food"), "hatter": ("모자 가게", "shop"), "saddler": ("마구 공방", "craft"),
    "locksmith": ("자물쇠 공방", "craft"), "ropemaker": ("밧줄 공방", "craft"), "copyist": ("필경소", "civic"),
    "bookseller": ("책방", "shop"),
}
# 현대 쓰임: OpenStreetMap 지도(canon/osm.py)가 태그에서, 현대 동네 생성기(canon/moderngen.py)가 블록 종류에서 고른다.
# 중세 지도의 가게 수(TRADES)에는 들지 않는다
MODERN: dict[str, tuple[str, str]] = {
    "building": ("건물", "home"), "apartment": ("아파트", "home"), "villa": ("빌라", "home"), "dorm": ("기숙사", "home"),
    "store": ("가게", "shop"), "convenience": ("편의점", "shop"), "mart": ("마트", "shop"), "department": ("백화점", "shop"),
    "salon": ("미용실", "shop"), "laundry": ("세탁소", "shop"), "fuel": ("주유소", "shop"),
    "cafe": ("카페", "food"), "restaurant": ("식당", "food"), "hotel": ("호텔", "lodging"),
    "hospital": ("병원", "care"), "pharmacy": ("약국", "care"), "gym": ("체육 시설", "care"), "kinder": ("유치원", "care"),
    "school": ("학교", "civic"), "academy": ("학원", "civic"), "university": ("대학교", "civic"), "library": ("도서관", "civic"),
    "police": ("경찰서", "civic"), "fire": ("소방서", "civic"), "post": ("우체국", "civic"), "government": ("관공서", "civic"),
    "station": ("역", "civic"), "culture": ("문화 시설", "civic"), "parking": ("주차장", "store"),
    "bank": ("은행", "work"), "company": ("회사 · 사무실", "work"), "factory": ("공장", "work"),
    "church": ("교회", "faith"), "buddhist": ("절", "faith"),
}
USES.update(MODERN)
HOMES = ("home", "farm", "tenement", "building", "apartment", "dorm")  # 사는 곳 (쓰임 목록에서 뒤로)
# 작품 이름 스타일(naming.STYLE_IDS)마다 바꿔 부르는 쓰임
STYLE_LABELS = {
    "joseon": {"inn": "주막", "tavern": "주막", "temple": "절", "baker": "떡집", "barber": "상투 손질집", "school": "서당",
               "office": "관아", "doctor": "의원", "brewer": "술도가", "bathhouse": "목욕간", "tenement": "행랑채",
               "chapel": "사당", "wine": "술집", "pastry": "엿집", "copyist": "필방", "bookseller": "책방", "furrier": "갖옷 가게"},
    "wuxia": {"inn": "객잔", "tavern": "주루", "temple": "사원", "baker": "만두 가게", "school": "서원", "office": "관부"},
    "korea_modern": {"inn": "여관", "tavern": "술집", "temple": "교회", "baker": "빵집", "office": "주민센터"},
    "japan": {"inn": "료칸", "tavern": "이자카야", "temple": "신사", "baker": "빵집", "school": "학교", "office": "관청"},
}

# 가게: 인구 몇 명에 하나(SV, Ross 의 표)와 좋아하는 자리
# where: center(광장 · 시장 가까이), main(큰길가), water(물가), edge(끝자락), quiet(뒷길)
TRADES: dict[str, tuple[int, str]] = {
    "shoemaker": (150, "center"), "furrier": (250, "center"), "tailor": (250, "center"), "barber": (350, "center"),
    "jeweler": (400, "center"), "tavern": (400, "main"), "oldclothes": (400, "quiet"), "chapel": (400, "quiet"),
    "pastry": (500, "center"), "mason": (500, "quiet"), "carpenter": (550, "quiet"), "weaver": (600, "quiet"),
    "chandler": (700, "center"), "mercer": (700, "center"), "cooper": (700, "water"), "baker": (800, "center"),
    "wine": (900, "main"), "hatter": (950, "center"), "saddler": (1000, "main"), "butcher": (1200, "center"),
    "fishmonger": (1200, "water"), "brewer": (1400, "water"), "spice": (1400, "center"), "smith": (1500, "edge"),
    "doctor": (1700, "center"), "locksmith": (1900, "quiet"), "bathhouse": (1900, "water"), "ropemaker": (1900, "water"),
    "inn": (2000, "main"), "tanner": (2000, "water"), "copyist": (2000, "quiet"), "bookseller": (6300, "center"),
    "mansion": (200, "quiet"),  # Ross: 귀족 가구는 200명에 하나
}
# 도시 구역(citygen.WARD_KINDS) 이 바라는 가게 묶음과 기본 쓰임
WARD_LIKES = {"market": ("shop", "food"), "merchant": ("shop", "lodging", "care"), "craft": ("craft",),
              "harbor": ("store", "food", "lodging"), "slum": ("lodging", "craft"), "noble": ("care",), "plaza": ("shop", "lodging"),
              "temple": ("faith", "care")}
WARD_HOME = {"noble": "mansion", "slum": "tenement", "harbor": "warehouse"}

# 층수 (낮은 값, 높은 값). Ross: 목조 · 반목조 건물은 1~3층
FLOORS = {"row": (1, 2), "house": (1, 1), "farm": (1, 1), "landmark": (1, 1), "outskirts": (1, 1),
          "market": (2, 3), "merchant": (2, 3), "craft": (1, 3), "harbor": (1, 2), "slum": (2, 3), "noble": (2, 3), "plaza": (2, 3)}
HOUSEHOLD = (2, 5)  # 주거 한 칸에 사는 사람 (Ross: 보통 3명, 2~5명)

# OpenStreetMap 지도: 층수 태그(building:levels)가 없을 때의 어림 층수. 목록에 없으면 3층
MODERN_FLOORS = {"apartment": 15, "villa": 4, "dorm": 5, "home": 2, "farm": 1, "barn": 1, "building": 3, "store": 2, "convenience": 1,
                 "fuel": 1, "parking": 1, "company": 8, "department": 7, "hospital": 6, "hotel": 10, "university": 5,
                 "school": 4, "kinder": 2, "station": 2, "church": 2, "buddhist": 1, "factory": 2, "warehouse": 1}
MODERN_HOMES = ("home", "apartment", "villa", "dorm", "farm")  # 사람 수를 어림하는 쓰임
FLAT_AREA = 85.0  # 주거 한 칸 넓이 (m², 국민주택 규모)
FLAT_SHARE = 0.6  # 연면적 가운데 주거 칸 몫 (어림: 복도 · 계단 · 벽)
HOUSEHOLD_SIZE = 2.2  # 한 가구 사람 수 (국가데이터처 지표: 2024년 평균 가구원 수 2.2명)

# 이야기 장소 종류(placekinds.CATEGORIES) → 쓰임
PLACE_USE = {"center": "office", "market": "hall", "well": "", "temple": "temple", "inn": "inn", "smith": "smith",
             "mill": "mill", "manor": "mansion", "home": "home", "shore": "warehouse", "bridge": "", "river": "", "pond": "",
             "forest": "", "field": "farm", "far": ""}
MODERN_PLACE_USE = {"center": "government", "market": "mart", "temple": "church", "inn": "hotel", "smith": "factory",
                    "mill": "factory", "manor": "home", "shore": "", "field": ""}  # 현대 동네 생성기 지도
MADE_MODERN = "canon-modern"  # moderngen.GENERATOR

SIGN_HEAD = ["황금", "붉은", "푸른", "늙은", "은빛", "검은", "웃는", "졸린", "세 마리", "외눈"]
SIGN_TAIL = ["사자", "까마귀", "닻", "솥", "달", "여우", "곰", "수탉", "물고기", "등잔"]

# 거리 이름 끝말: 스타일마다 (큰길, 길, 골목)
STREET_TAILS = {"joseon": ("큰길", "길", "골"), "korea_modern": ("로", "길", "골목"), "wuxia": ("대로", "가", "골목"),
                "japan": ("도리", "길", "골목"), "western_fantasy": ("대로", "거리", "골목"), "sf": ("대로", "가", "통로")}
DIRS = ["동", "남동", "남", "남서", "서", "북서", "북", "북동"]  # 화면 각도(아래가 남) 0°=동쪽부터 45° 씩
STREET_WORD = {"temple": "신전", "mill": "방앗간", "smith": "대장간", "tanner": "무두장이", "cooper": "통장이", "weaver": "베틀",
               "brewer": "술도가", "inn": "여관", "ropemaker": "밧줄", "chapel": "예배당"}  # 거리 이름에 쓰는 짧은 말


def label(use: str, style: str = "") -> str:
    """쓰임의 화면 이름 (작품 스타일에 맞춰)."""
    return STYLE_LABELS.get(style, {}).get(use) or USES.get(use, (use, ""))[0]


def describe(layout: dict, seed: str | int, style: str = "western_fantasy", spots: Optional[list[dict]] = None) -> dict:
    """{streets, blds, bver}. layout 은 read_layout 모양 (+ parts, wards, spots). spots 를 주지 않으면 layout["spots"]."""
    w, h = layout["w"], layout["h"]
    rng = lambda stage: random.Random(f"{seed}:bldgs:{stage}")  # noqa: E731
    M = lambda q: (q[0] * w, q[1] * h)  # noqa: E731
    polys = [[M(q) for q in ln] for ln in layout.get("buildings", [])]
    n = len(polys)
    parts = layout.get("parts") or [{"lot": i, "part": "main", "zone": "", "use": ""} for i in range(n)]
    if len(parts) != n:
        parts = [{"lot": i, "part": "main", "zone": "", "use": ""} for i in range(n)]
    city = layout.get("generator") == "canon-city" or bool(layout.get("wards"))
    cents = [geom.centroid(p) if len(p) >= 3 else (p[0] if p else (0.0, 0.0)) for p in polys]
    areas = [abs(geom.area(p)) if len(p) >= 3 else 0.0 for p in polys]

    # 본채와 곁채: 같은 필지의 첫 건물이 본채
    main_of: dict[int, int] = {}
    owner = [-1] * n
    for i, pt in enumerate(parts):
        if pt["part"] in ("main", "hall", "temple", "tower") or pt["lot"] < 0:
            owner[i] = i
            if pt["lot"] >= 0:
                main_of.setdefault(pt["lot"], i)
        else:
            owner[i] = main_of.get(pt["lot"], i)
    mains = [i for i in range(n) if owner[i] == i]

    streets, segs = _streets(layout, M)
    center = _center(layout, M, cents, mains)
    reach = max((math.dist(center, cents[i]) for i in mains), default=1.0) or 1.0
    squares = [[M(q) for q in sq] for sq in layout.get("squares", [])]
    wet = [[M(q) for q in ln] for ln in layout.get("water", [])]
    rivers = [([M(q) for q in rv["points"]], rv.get("width", 4)) for rv in layout.get("rivers", [])]

    def near_water(q: Point) -> float:
        d = min((geom.seg_dist(q, a, b) for poly in wet for a, b in zip(poly, poly[1:] + poly[:1])), default=1e9)
        d = min([d] + [geom.seg_dist(q, a, b) - wd / 2 for pts, wd in rivers for a, b in zip(pts, pts[1:])])
        return d

    def near_square(q: Point) -> float:
        return min((math.dist(q, geom.centroid(sq)) for sq in squares), default=math.dist(q, center))

    # 앞길 · 번지: 본채마다 가장 가까운 길 조각
    grid = geom.Grid(40)
    for k, (a, b, sid, t0) in enumerate(segs):
        grid.add(geom.bbox([a, b]), k)
    front: dict[int, tuple[int, float, int]] = {}  # 건물 → (거리, 거리 위 위치 m, 왼쪽 1 / 오른쪽 -1)
    for i in mains:
        q = cents[i]
        cand = grid.near((q[0], q[1], q[0], q[1]), 3) or range(len(segs))
        best = None
        for k in cand:
            a, b, sid, t0 = segs[k]
            d = geom.seg_dist(q, a, b)
            if best is None or d < best[0]:
                best = (d, k)
        if best is None:
            continue
        a, b, sid, t0 = segs[best[1]]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy or 1.0
        t = max(0.0, min(1.0, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / L2))
        side = 1 if dx * (q[1] - a[1]) - dy * (q[0] - a[0]) > 0 else -1
        front[i] = (sid, t0 + t * math.sqrt(L2), side)
    numbers: dict[int, int] = {}
    for sid in range(len(streets)):
        for side, first in ((1, 1), (-1, 2)):
            row = sorted((pos, i) for i, (s, pos, sd) in front.items() if s == sid and sd == side)
            for k, (_, i) in enumerate(row):
                numbers[i] = first + 2 * k

    if layout.get("generator") in ("osm", MADE_MODERN):
        made = layout["generator"] == MADE_MODERN
        if made:  # 큰길 · 길 · 골목은 폭으로 가른다 (대로 15m 넘게, 소로 6m 넘게)
            for st in streets:
                st["kind"] = "main" if st["width"] >= 15 else "street" if st["width"] >= 6 else "lane"
        namer = (lambda out: _name_streets(streets, front, out, mains, center, cents, style, rng("streets"), layout, M,
                                           modern=True)) if made else None
        return _describe_osm(layout, parts, areas, mains, streets, front, polys, owner,
                             spots if spots is not None else layout.get("spots", []), M, numbers if made else None, namer)

    # 건물 자리 맛: 가운데 가까움, 광장 가까움, 물가, 큰길가, 구역
    ctx: dict[int, dict] = {}
    for i in mains:
        q = cents[i]
        st = streets[front[i][0]] if i in front else None
        ctx[i] = {"core": 1 - min(1.0, math.dist(q, center) / reach), "square": near_square(q), "water": near_water(q),
                  "main": bool(st and st["kind"] == "main"), "zone": parts[i]["zone"], "area": areas[i]}

    # 층수 · 사는 사람
    fr, pr = rng("floors"), rng("people")
    out: list[dict] = [{} for _ in range(n)]
    for i in mains:
        zone = ctx[i]["zone"] or ("market" if city else "house")
        f0, f1 = FLOORS.get(zone, (1, 2) if city else (1, 1))
        if city and ctx[i]["core"] > 0.6:
            f0 = min(f1, f0 + 1)  # 도시 한가운데는 높은 쪽으로 (3층을 넘지 않는다)
        floors = fr.randint(f0, f1)
        if not city and zone == "row" and ctx[i]["core"] < 0.4:
            floors = 1
        out[i] = {"use": "home", "floors": floors, "people": 0}
        if parts[i]["part"] in ("hall", "temple"):
            out[i]["use"] = parts[i]["part"]
        elif parts[i]["part"] == "tower":
            out[i]["use"] = "tower"
        elif zone == "landmark":
            out[i]["use"] = "temple"
        elif zone == "farm":
            out[i]["use"] = "farm"
        elif zone in WARD_HOME and pr.random() < 0.6:
            out[i]["use"] = WARD_HOME[zone]
    for i in mains:
        if out[i]["use"] in ("hall", "temple", "tower", "warehouse"):
            continue
        # 주거 칸: 마을은 한 채에 한 칸, 도시는 층마다 한 칸쯤 (Ross: 건물 수는 주거 수의 1~2배라 2~3층 건물에 두 칸이 보통)
        homes = 1 if not city else max(1, out[i]["floors"] - pr.randint(0, 1))
        out[i]["people"] = sum(pr.randint(*HOUSEHOLD) for _ in range(homes))
    people = sum(out[i]["people"] for i in mains)

    # 이야기 장소: 장소가 놓인 건물은 그 장소의 쓰임 · 이름
    for sp in spots if spots is not None else layout.get("spots", []):
        q = M((sp["x"], sp["y"]))
        i = next((j for j in mains if geom.inside(q, polys[j])), None)
        if i is None:
            i = next((j for j in range(n) if geom.inside(q, polys[j])), None)
            i = owner[i] if i is not None else None
        if i is None:
            continue
        use = PLACE_USE.get(sp.get("kind", ""), "") or out[i]["use"]
        out[i].update({"use": use, "name": sp["name"], "place": sp["key"]})

    # 가게: 인구에 맞춘 수, 좋아하는 자리 순서로
    tr = rng("trades")
    jitter = 1 + (sum(tr.randint(1, 4) for _ in range(4)) - 10) / 10  # Ross: 도시마다 SV 를 (4d4 - 10) × 10%
    taken = {i for i in mains if out[i]["use"] not in ("home", "tenement")}
    want: list[tuple[float, str]] = []
    for trade, (sv, where) in TRADES.items():
        per = sv * jitter
        x = people / per
        have = sum(1 for i in mains if out[i]["use"] == trade)
        count = int(x) + (1 if tr.random() < x - int(x) else 0) - have
        want += [(per, trade)] * max(0, count)
    want.sort(key=lambda t: -t[0])  # 드문 가게부터 좋은 자리를 고른다

    def score(i: int, trade: str) -> float:
        c = ctx[i]
        where = TRADES[trade][1]
        s = {"center": 2 * c["core"] - c["square"] / reach, "main": (1.2 if c["main"] else 0) + c["core"],
             "water": -c["water"] / 60, "edge": 1 - c["core"] + (0.6 if c["main"] else 0),
             "quiet": (0 if c["main"] else 0.8) + 0.5 * c["core"]}[where]
        group = USES[trade][1]
        if city and c["zone"] in WARD_LIKES:
            s += 1.5 if group in WARD_LIKES[c["zone"]] else -0.5
        return s + tr.uniform(0, 0.6)

    for _, trade in want:
        free = [i for i in mains if i not in taken and out[i]["use"] in ("home", "tenement")]
        if not free:
            break
        i = max(free, key=lambda j: score(j, trade))
        out[i]["use"] = trade
        taken.add(i)

    # 간판 이름: 여관 · 주점 (이야기 장소 이름이 있으면 그대로)
    nr = rng("signs")
    used_names: set[str] = set()
    for i in mains:
        if out[i]["use"] in ("inn", "tavern") and not out[i].get("name"):
            for _ in range(20):
                nm = f"{nr.choice(SIGN_HEAD)} {nr.choice(SIGN_TAIL)} {label(out[i]['use'], style)}"
                if nm not in used_names:
                    break
            used_names.add(nm)
            out[i]["name"] = nm

    _name_streets(streets, front, out, mains, center, cents, style, rng("streets"), layout, M)

    # 곁채 · 헛간은 본채를 가리킨다
    for i in range(n):
        if owner[i] != i:
            out[i] = {"use": "barn" if parts[i]["part"] == "barn" else "annex", "of": owner[i]}
    for i in mains:
        if i in front:
            out[i]["street"] = front[i][0]
            out[i]["no"] = numbers.get(i, 0)
    return {"streets": [{k: v for k, v in st.items() if k != "segs"} for st in streets], "blds": out, "bver": VERSION}


def _describe_osm(layout: dict, parts: list[dict], areas: list[float], mains: list[int], streets: list[dict], front: dict,
                  polys: list, owner: list[int], spots: list[dict], M, numbers: Optional[dict] = None,
                  namer: Optional[Callable[[list[dict]], None]] = None) -> dict:
    """OpenStreetMap 지도(canon/osm.py): 쓰임 · 이름 · 주소 · 입점한 곳은 태그 그대로, 층수는 태그가 없으면 쓰임마다 어림.
    사는 사람은 주거 쓰임만 연면적 × FLAT_SHARE ÷ FLAT_AREA 가구 × HOUSEHOLD_SIZE 명. 가게를 더 두거나 간판을 짓지 않는다.
    거리 이름은 길 이름(name) 가운데 가장 많은 것, 이름 없는 길은 비워 둔다. 번지(no)는 0 이다.
    실제 지도에 없는 이름 · 번지를 지어 넣지 않는다 (실제 주소처럼 보여 헷갈린다).
    현대 동네 생성기 지도는 같은 규칙에 numbers(번지)와 namer(out 을 받아 거리 이름을 짓는다)를 준다."""
    out: list[dict] = [{} for _ in parts]
    for i in mains:
        pt = parts[i]
        use = pt.get("use") or "building"
        floors = pt.get("levels") or MODERN_FLOORS.get(use, 3)
        people = 0
        if use in MODERN_HOMES:
            people = round(max(1, round(areas[i] * floors * FLAT_SHARE / FLAT_AREA)) * HOUSEHOLD_SIZE)
        out[i] = {"use": use, "floors": floors, "people": people}
        for key in ("name", "addr"):
            if pt.get(key):
                out[i][key] = pt[key]
        if pt.get("tenants"):
            out[i]["tenants"] = list(pt["tenants"])
    for sp in spots:
        q = M((sp["x"], sp["y"]))
        i = next((j for j in mains if geom.inside(q, polys[j])), None)
        if i is not None:
            uses = MODERN_PLACE_USE if namer else PLACE_USE
            out[i].update({"use": uses.get(sp.get("kind", ""), "") or out[i]["use"], "name": sp["name"], "place": sp["key"]})
    roads = layout.get("roads", [])
    if namer:
        namer(out)
    else:
        for st in streets:
            names = [roads[k].get("name", "") for k in st["roads"] if roads[k].get("name")]
            st["name"] = max(set(names), key=lambda x: (names.count(x), x)) if names else ""
    for i in range(len(parts)):
        if owner[i] != i:
            out[i] = {"use": "annex", "of": owner[i]}
    for i in mains:
        if i in front:  # 앞길만 적고 번지는 짓지 않는다 (실제 주소는 addr). 지어낸 동네는 번지도 짓는다
            out[i]["street"] = front[i][0]
            out[i]["no"] = (numbers or {}).get(i, 0)
    return {"streets": [{k: v for k, v in st.items() if k != "segs"} for st in streets], "blds": out, "bver": VERSION}


def _center(layout: dict, M, cents: list[Point], mains: list[int]) -> Point:
    """마을 가운데: 광장이 있으면 첫 광장, 없으면 첫 길의 첫 점, 그것도 없으면 건물 평균."""
    if layout.get("squares"):
        return geom.centroid([M(q) for q in layout["squares"][0]])
    if layout.get("roads"):
        return M(layout["roads"][0]["points"][0])
    pts = [cents[i] for i in mains] or [(layout["w"] / 2, layout["h"] / 2)]
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _streets(layout: dict, M) -> tuple[list[dict], list[tuple[Point, Point, int, float]]]:
    """길 조각을 거리로 묶는다. 끝점을 나눠 쓰는 조각끼리, 폭이 같고 30° 안으로 곧게 이어지는 쌍을 먼저 잇는다.
    돌려주는 것: 거리 [{id, kind, width, roads, mid, angle}], 선분 [(a, b, 거리 id, 거리 시작부터 a 까지 m)]."""
    roads = layout.get("roads", [])
    key = lambda q: (round(q[0], 1), round(q[1], 1))  # noqa: E731
    lines = [[M(q) for q in rd["points"]] for rd in roads]
    ends: dict[tuple, list[tuple[int, int]]] = {}
    for k, ln in enumerate(lines):
        if len(ln) >= 2 and roads[k]["kind"] == "road":
            ends.setdefault(key(ln[0]), []).append((k, 0))
            ends.setdefault(key(ln[-1]), []).append((k, -1))

    def heading(k: int, at: int) -> float:  # 끝점에서 바깥으로 나가는 방향
        ln = lines[k]
        a, b = (ln[0], ln[1]) if at == 0 else (ln[-1], ln[-2])
        return math.atan2(a[1] - b[1], a[0] - b[0])

    nxt: dict[tuple[int, int], tuple[int, int]] = {}
    for node, items in ends.items():
        pairs = []
        for x in range(len(items)):
            for y in range(x + 1, len(items)):
                (k1, e1), (k2, e2) = items[x], items[y]
                if k1 == k2 or abs(roads[k1]["width"] - roads[k2]["width"]) > 0.6:
                    continue
                turn = abs((heading(k1, e1) - heading(k2, e2) + math.pi) % (2 * math.pi) - math.pi)
                bend = math.pi - turn  # 0 이면 곧게 이어진다
                if bend < math.radians(30):
                    pairs.append((bend, items[x], items[y]))
        for _, a, b in sorted(pairs):
            if a not in nxt and b not in nxt:
                nxt[a], nxt[b] = b, a
    seen: set[int] = set()
    streets: list[dict] = []
    segs: list[tuple[Point, Point, int, float]] = []
    for start in range(len(lines)):
        if start in seen or roads[start]["kind"] != "road" or len(lines[start]) < 2:
            continue
        # 사슬의 한쪽 끝으로 간 뒤 반대쪽으로 모은다
        k, e = start, 0
        guard = 0
        while (k, e) in nxt and guard < len(lines):
            k2, e2 = nxt[(k, e)]
            k, e = k2, (-1 if e2 == 0 else 0)
            guard += 1
        chain: list[tuple[int, bool]] = []  # (조각, 뒤집기)
        cur, at = k, e
        guard = 0
        while guard <= len(lines):
            if cur in seen:
                break
            seen.add(cur)
            chain.append((cur, at == -1))
            other = -1 if at == 0 else 0
            if (cur, other) not in nxt:
                break
            cur, at = nxt[(cur, other)]
            guard += 1
        sid = len(streets)
        pts: list[Point] = []
        for k, rev in chain:
            ln = lines[k][::-1] if rev else lines[k]
            pts += ln if not pts else ln[1:]
        run = 0.0
        for a, b in zip(pts, pts[1:]):
            segs.append((a, b, sid, run))
            run += math.dist(a, b)
        width = max(roads[k]["width"] for k, _ in chain)
        mid_k = max(range(len(pts) - 1), key=lambda j: math.dist(pts[j], pts[j + 1]))
        a, b = pts[mid_k], pts[mid_k + 1]
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        if ang > 90 or ang < -90:
            ang -= 180 * (1 if ang > 0 else -1)
        streets.append({"id": sid, "name": "", "kind": "", "width": round(width, 2), "length": round(run),
                        "roads": [k for k, _ in chain], "mid": [round(((a[0] + b[0]) / 2) / layout["w"], 5),
                                                                round(((a[1] + b[1]) / 2) / layout["h"], 5)],
                        "angle": round(ang, 1)})
    if streets:
        widths = sorted(s["width"] for s in streets)
        top = widths[-1]
        for s in streets:
            s["kind"] = "main" if s["width"] >= top - 0.6 or s["width"] >= 6 else "lane" if s["width"] < 3.6 else "street"
    return streets, segs


def _heads(style: str, r: random.Random, n: int) -> list[str]:
    """거리 이름 앞말 후보 (스타일에 맞는 땅이름 머리, 겹치지 않게 섞어서)."""
    from . import naming_data as D

    if style in ("joseon", "korea_modern"):
        pool = list(D.KO_NATIVE_HEAD) + ["".join(r.sample(D.KO_PLACE_SYL, 2)) for _ in range(n)]
    elif style == "wuxia":
        pool = ["".join(r.sample(D.WUXIA_PLACE_SYL, 2)) for _ in range(n)]
    elif style == "japan":
        pool = list(D.JA_PLACE_HEAD)
    elif style == "sf":
        pool = list(D.SF_PLACE_HEAD)
    else:
        pool = [h + (r.choice(D.WEST_MID) if len(h) == 1 else "") for h in D.WEST_HEAD]
    pool = list(dict.fromkeys(pool))
    r.shuffle(pool)
    return pool


def _name_streets(streets: list[dict], front: dict, out: list[dict], mains: list[int], center: Point, cents: list[Point],
                  style: str, r: random.Random, layout: dict, M, modern: bool = False) -> None:
    """거리 이름. 큰길은 장터 · 신전 · 방앗간이 있으면 그 이름, 없으면 가운데에서 본 방향. 다른 길은 길가의 이름난
    가게(대장간 · 무두질 집 등), 그것도 없으면 땅이름 머리를 붙인다. 이름은 겹치지 않는다.
    modern(현대 동네): 가게 · 방향 이름 없이 모두 땅이름 머리를 붙인다."""
    big, mid, small = STREET_TAILS.get(style, STREET_TAILS["western_fantasy"])
    on: dict[int, list[int]] = {}
    for i, (sid, _, _) in front.items():
        on.setdefault(sid, []).append(i)
    used: set[str] = set()
    pool = _heads(style, r, 60)
    join = lambda head, tail: f"{head}{tail}" if tail in ("길", "골", "가", "로", "도리") else f"{head} {tail}"  # noqa: E731
    for st in sorted(streets, key=lambda s: -s["length"]):
        tail = {"main": big, "street": mid, "lane": small}[st["kind"]]
        uses = [out[i]["use"] for i in on.get(st["id"], [])]
        marks = () if modern else ("hall", "temple", "mill") if st["kind"] == "main" else (
            "hall", "temple", "mill", "smith", "tanner", "brewer", "inn", "cooper", "weaver", "ropemaker", "chapel")
        name = ""
        for u in marks:
            if u in uses:
                word = "장터" if u == "hall" else STYLE_LABELS.get(style, {}).get(u) or STREET_WORD.get(u) or label(u, style)
                cand = join(word.replace(" ", ""), tail)
                if cand not in used:
                    name = cand
                    break
        if not name and st["kind"] == "main" and not modern:
            x, y = st["mid"][0] * layout["w"], st["mid"][1] * layout["h"]
            ang = math.degrees(math.atan2(y - center[1], x - center[0])) % 360
            cand = join(f"{DIRS[int((ang + 22.5) // 45) % 8]}쪽", big)
            name = cand if cand not in used else ""
        while not name or name in used:
            name = join(pool.pop() if pool else f"{len(used) + 1}번", tail)
        used.add(name)
        st["name"] = name

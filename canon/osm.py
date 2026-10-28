"""OpenStreetMap 데이터를 지도 화면이 그릴 모양(atlas.read_layout 과 같은 모양)으로 바꾼다. LLM 을 부르지 않는다.

받는 파일
- .osm (XML): openstreetmap.org 의 '내보내기', JOSM 저장. <bounds> 가 지도 범위다.
- GeoJSON: overpass-turbo 의 '내보내기 → GeoJSON'(osmtogeojson). 범위가 없어서 건물이 있는 곳에서 PAD 만큼 넓힌 범위를 쓴다.

바꾸는 것
- 좌표: 범위 가운데 위도로 경도 1도의 길이를 셈한 평면(m)으로 바꾸고 y 는 아래로(북쪽이 위). 축척은 1단위 = 1m.
- 범위 밖으로 나간 길은 범위 테두리에서 자르고, 건물 · 물 · 풀밭은 테두리 안쪽만 남긴다.
- 길(highway): 폭은 width 태그, 없으면 차로 수(lanes) × 3.3m + 2m, 그것도 없으면 길 종류의 기본 폭(WIDTHS).
  bridge 는 다리, 땅속(tunnel, 음수 layer, covered)은 그리지 않는다. 이름(name)은 거리 이름이 된다.
- 건물(building): 땅속 건물(음수 layer, location=underground)과 지붕만 있는 것(building=roof)은 뺀다.
  건물마다 쓰임 · 층수 · 이름 · 주소 · 입점한 곳을 `parts` 에 적는다(bldgs.describe 가 읽는다).
  쓰임은 건물 자신의 태그, 없으면 건물 안에 있는 가게 · 시설 점(amenity, shop 등)에서 고른다(use_of).
- 물(natural=water 등)과 강(waterway): 범위에 다 들어오지 않은 큰 물(한강 같은 multipolygon)은 끊긴 물가 선만 온다.
  물가 선의 양쪽 가운데 건물 · 길이 덜 촘촘한 쪽을 물로 보고 테두리를 따라 닫는다(_close_open).
- 풀밭 · 숲 · 공원은 greens, 논밭은 fields, 광장 · 보행 구역은 squares, 나무 점(natural=tree)은 trees.

다 들어오지 않은 multipolygon 의 안쪽 고리(물 속 섬, 건물 안뜰)는 쓰지 않는다. 지하철 · 철길과 바다(natural=coastline)는
그리지 않는다.
OpenStreetMap 데이터는 ODbL 이라 지도 화면 · 내보낸 그림에 출처(SOURCE)를 적는다.
"""
from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from typing import Optional

from . import geom
from .geom import Point

GENERATOR = "osm"
SOURCE = "© OpenStreetMap 기여자"
SOURCE_URL = "https://www.openstreetmap.org/copyright"
MAX_SIDE = 6000.0  # m. 이보다 넓은 범위는 받지 않는다 (지도 화면이 무거워진다)
MAX_BUILDINGS = 20000
PAD = 30.0  # m. 범위가 없는 GeoJSON 은 건물이 있는 곳에서 이만큼 넓힌 범위를 쓴다 (가장자리 길이 남게)

# 길 종류 → 기본 폭 (m). 목록에 없는 highway(공사 중, 계획, 승강장 등)는 그리지 않는다
WIDTHS = {"motorway": 24, "trunk": 24, "primary": 20, "secondary": 16, "tertiary": 12, "unclassified": 7,
          "residential": 6, "living_street": 5, "service": 4, "pedestrian": 5, "track": 3, "road": 6,
          "motorway_link": 8, "trunk_link": 8, "primary_link": 8, "secondary_link": 7, "tertiary_link": 6,
          "footway": 2, "path": 2, "cycleway": 2, "steps": 2, "bridleway": 2}
RIVER_WIDTHS = {"river": 30, "canal": 12, "stream": 4, "ditch": 2, "drain": 2}
WATER = {("natural", "water"), ("waterway", "riverbank"), ("landuse", "reservoir"), ("landuse", "basin"), ("natural", "bay")}
GREEN = {("leisure", "park"), ("leisure", "garden"), ("leisure", "pitch"), ("leisure", "playground"), ("landuse", "grass"),
         ("landuse", "forest"), ("landuse", "recreation_ground"), ("landuse", "meadow"), ("landuse", "village_green"),
         ("landuse", "cemetery"), ("natural", "wood"), ("natural", "scrub"), ("natural", "grassland"), ("natural", "heath")}
FIELD = {("landuse", "farmland"), ("landuse", "orchard"), ("landuse", "allotments"), ("landuse", "vineyard")}
POI_KEYS = ("amenity", "shop", "office", "tourism", "leisure", "healthcare", "railway", "public_transport", "craft")

# 태그 → 건물 쓰임 (bldgs.USES 의 id). 먼저 맞는 것이 이긴다
_AMENITY = {"cafe": "cafe", "restaurant": "restaurant", "fast_food": "restaurant", "food_court": "restaurant",
            "bar": "tavern", "pub": "tavern", "nightclub": "tavern", "bank": "bank", "pharmacy": "pharmacy",
            "hospital": "hospital", "clinic": "doctor", "doctors": "doctor", "dentist": "doctor", "school": "school",
            "kindergarten": "kinder", "childcare": "kinder", "university": "university", "college": "university",
            "library": "library", "police": "police", "fire_station": "fire", "post_office": "post", "townhall": "office",
            "community_centre": "office", "courthouse": "government", "cinema": "culture", "theatre": "culture", "arts_centre": "culture",
            "parking": "parking", "fuel": "fuel", "marketplace": "hall", "prep_school": "academy", "language_school": "academy",
            "music_school": "academy", "driving_school": "academy", "public_bath": "bathhouse"}
_SHOP = {"convenience": "convenience", "supermarket": "mart", "department_store": "department", "mall": "department",
         "bakery": "baker", "pastry": "pastry", "hairdresser": "salon", "beauty": "salon", "laundry": "laundry",
         "dry_cleaning": "laundry", "butcher": "butcher", "seafood": "fishmonger", "clothes": "tailor", "shoes": "shoemaker",
         "books": "bookseller", "jewelry": "jeweler", "alcohol": "wine"}
_BUILDING = {"apartments": "apartment", "house": "home", "detached": "home", "residential": "home",
             "semidetached_house": "home", "terrace": "home", "dormitory": "dorm", "commercial": "store", "retail": "store",
             "kiosk": "store", "office": "company", "industrial": "factory", "factory": "factory", "warehouse": "warehouse",
             "school": "school", "university": "university", "college": "university", "kindergarten": "kinder",
             "hospital": "hospital", "church": "church", "cathedral": "church", "chapel": "church", "temple": "buddhist",
             "train_station": "station", "transportation": "station", "public": "government", "government": "government",
             "civic": "government", "garage": "parking", "garages": "parking", "parking": "parking", "hotel": "hotel",
             "supermarket": "mart", "farm": "farm", "barn": "barn", "shed": "barn"}
# 한 건물에 시설이 여럿이면 앞 묶음이 건물의 쓰임이 된다 (역 · 병원 · 학교 같은 큰 시설이 가게보다 앞)
_RANK = ["station", "hospital", "university", "school", "police", "fire", "government", "office", "post", "library", "church", "buddhist",
         "temple", "department", "hotel", "mart", "culture", "bank", "kinder", "academy", "doctor", "pharmacy"]


def is_osm(raw: object) -> bool:
    """GeoJSON 이 OpenStreetMap 에서 온 것인가 (Watabou 파일은 id 가 'buildings' 같은 겹 이름이다)."""
    if not isinstance(raw, dict) or raw.get("type") != "FeatureCollection" or not isinstance(raw.get("features"), list):
        return False
    for f in raw["features"][:200]:
        if not isinstance(f, dict):
            continue
        if re.match(r"^(node|way|relation)/\d+$", str(f.get("id") or "")):
            return True
        props = f.get("properties")
        if isinstance(props, dict) and ("@id" in props or isinstance(props.get("tags"), dict)
                                        or any(k in props for k in ("building", "highway", "natural", "landuse", "waterway"))):
            return True
    return False


def parse(text: str) -> dict:
    """.osm (XML) 글 또는 OSM GeoJSON 글 → 지도 모양. 읽지 못하면 ValueError (해요체 까닭)."""
    s = text.lstrip()
    if s.startswith("<"):
        return convert(*_from_xml(s))
    try:
        raw = json.loads(s)
    except ValueError:
        raise ValueError("OpenStreetMap 파일을 읽지 못했어요") from None
    if not is_osm(raw):
        raise ValueError("OpenStreetMap에서 받은 GeoJSON이 아니에요")
    return convert(*_from_geojson(raw))


# ---------- 읽기: (태그, 모양, 좌표) 목록 ----------
# 모양: point (lon, lat) | line [(lon, lat)] | area [고리] (닫힌 바깥 고리들) | open [사슬] (닫히지 않은 바깥 고리 조각)

Feature = tuple[dict, str, object]


def _from_xml(text: str) -> tuple[list[Feature], Optional[tuple[float, float, float, float]]]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        raise ValueError("OpenStreetMap .osm 파일을 읽지 못했어요") from None
    if root.tag != "osm":
        raise ValueError("OpenStreetMap .osm 파일이 아니에요")
    bounds = None
    b = root.find("bounds")
    if b is not None:
        try:
            bounds = tuple(float(b.get(k)) for k in ("minlat", "minlon", "maxlat", "maxlon"))
        except (TypeError, ValueError):
            bounds = None
    tags = lambda el: {t.get("k"): t.get("v") for t in el.findall("tag") if t.get("k")}  # noqa: E731
    nodes: dict[str, tuple[float, float]] = {}
    feats: list[Feature] = []
    for nd in root.iter("node"):
        try:
            q = (float(nd.get("lon")), float(nd.get("lat")))
        except (TypeError, ValueError):
            continue
        nodes[nd.get("id")] = q
        t = tags(nd)
        if t:
            feats.append((t, "point", q))
    ways: dict[str, list] = {}
    for w in root.iter("way"):
        pts = [nodes[r.get("ref")] for r in w.findall("nd") if r.get("ref") in nodes]
        ways[w.get("id")] = pts
        t = tags(w)
        if t and len(pts) >= 2:
            closed = len(pts) >= 4 and pts[0] == pts[-1]
            feats.append((t, "area", [pts]) if closed and _is_area(t) else (t, "line", pts))
    for rel in root.iter("relation"):
        t = tags(rel)
        if t.get("type") != "multipolygon":
            continue
        t = {k: v for k, v in t.items() if k != "type"}
        outers = [ways[m.get("ref")] for m in rel.findall("member")
                  if m.get("type") == "way" and m.get("role") in ("outer", "") and ways.get(m.get("ref"))]
        if not t or not outers:
            continue
        rings, chains = _rings(outers)
        if rings:
            feats.append((t, "area", rings))
        if chains:
            feats.append((t, "open", chains))
    return feats, bounds


def _from_geojson(raw: dict) -> tuple[list[Feature], None]:
    feats: list[Feature] = []
    for f in raw["features"]:
        if not isinstance(f, dict) or not isinstance(f.get("geometry"), dict):
            continue
        props = f.get("properties") if isinstance(f.get("properties"), dict) else {}
        src = props["tags"] if isinstance(props.get("tags"), dict) else props
        t = {str(k): str(v) for k, v in src.items() if not str(k).startswith("@") and k != "id" and isinstance(v, (str, int, float))}
        if not t:
            continue
        g = f["geometry"]
        kind, c = g.get("type"), g.get("coordinates") or []
        try:
            if kind == "Point":
                feats.append((t, "point", (float(c[0]), float(c[1]))))
            elif kind == "LineString":
                feats.append((t, "line", [(float(q[0]), float(q[1])) for q in c]))
            elif kind == "MultiLineString":
                feats += [(t, "line", [(float(q[0]), float(q[1])) for q in ln]) for ln in c]
            elif kind in ("Polygon", "MultiPolygon"):
                polys = [c] if kind == "Polygon" else c
                rings = [[(float(q[0]), float(q[1])) for q in poly[0]] for poly in polys if poly and len(poly[0]) >= 4]
                if rings:
                    feats.append((t, "area", rings))
        except (TypeError, ValueError, IndexError):
            continue
    return feats, None


def _is_area(t: dict) -> bool:
    """닫힌 길(way)을 넓이로 볼까. 길(highway)은 area=yes 일 때만."""
    if t.get("area") == "no":
        return False
    if "highway" in t:
        return t.get("area") == "yes"
    return (t.get("area") == "yes" or "building" in t or "landuse" in t or "leisure" in t or "amenity" in t
            or t.get("place") == "square" or t.get("waterway") == "riverbank"
            or (t.get("natural") not in (None, "coastline", "tree_row", "cliff")))


def _rings(parts: list[list]) -> tuple[list[list], list[list]]:
    """multipolygon 의 바깥 선들을 끝점끼리 이어 고리로. 닫히지 않은 사슬(범위 밖 조각이 빠진 큰 물)은 따로."""
    chains = [list(p) for p in parts if len(p) >= 2]
    rings, loose = [], []
    while chains:
        cur = chains.pop()
        grown = True
        while cur[0] != cur[-1] and grown:
            grown = False
            for k, c in enumerate(chains):
                if c[0] == cur[-1]:
                    cur = cur + c[1:]
                elif c[-1] == cur[-1]:
                    cur = cur + c[-2::-1]
                elif c[-1] == cur[0]:
                    cur = c[:-1] + cur
                elif c[0] == cur[0]:
                    cur = c[:0:-1] + cur
                else:
                    continue
                chains.pop(k)
                grown = True
                break
        (rings if cur[0] == cur[-1] and len(cur) >= 4 else loose).append(cur)
    return rings, loose


# ---------- 바꾸기 ----------

def convert(feats: list[Feature], bounds: Optional[tuple[float, float, float, float]] = None) -> dict:
    """읽은 것 → read_layout 모양 (+ generator 'osm', parts, source). bounds: (남, 서, 북, 동)."""
    if bounds is None:
        pts = [q for t, kind, g in feats if "building" in t and kind == "area" for ring in g for q in ring]
        pts = pts or [q for _, kind, g in feats for q in _coords(kind, g)]
        if not pts:
            raise ValueError("파일에 좌표가 없어요")
        lat = (min(q[1] for q in pts) + max(q[1] for q in pts)) / 2
        px, py = PAD / (111320.0 * math.cos(math.radians(lat))), PAD / 110574.0
        bounds = (min(q[1] for q in pts) - py, min(q[0] for q in pts) - px, max(q[1] for q in pts) + py, max(q[0] for q in pts) + px)
    s, w, n, e = bounds
    mx = 111320.0 * math.cos(math.radians((s + n) / 2))
    my = 110574.0
    W, H = (e - w) * mx, (n - s) * my
    if W < 20 or H < 20:
        raise ValueError("지도 범위가 너무 좁아요. 더 넓게 받아 주세요")
    if W > MAX_SIDE or H > MAX_SIDE:
        raise ValueError(f"지도 범위가 너무 넓어요 (약 {W / 1000:.1f} × {H / 1000:.1f}km). 한 변 {MAX_SIDE / 1000:.0f}km 안으로 받아 주세요")
    P = lambda q: ((q[0] - w) * mx, (n - q[1]) * my)  # noqa: E731
    box = [(0.0, 0.0), (W, 0.0), (W, H), (0.0, H)]  # 화면 좌표(y 아래)에서 넓이가 양수인 방향
    norm = lambda pts: [[round(x / W, 6), round(y / H, 6)] for x, y in pts]  # noqa: E731

    roads: list[dict] = []
    rivers: list[dict] = []
    areas: dict[str, list] = {"buildings": [], "water": [], "greens": [], "fields": [], "squares": []}
    btags: list[dict] = []
    pois: list[tuple[Point, dict]] = []
    trees: list[Point] = []
    loose: list[list[Point]] = []
    for t, kind, g in feats:
        if kind == "point":
            q = P(g)
            if not (0 <= q[0] <= W and 0 <= q[1] <= H):
                continue
            if t.get("natural") == "tree":
                trees.append(q)
            elif any(k in t for k in POI_KEYS):
                pois.append((q, t))
            continue
        under = _under(t)
        if kind == "line":
            line = [P(q) for q in g]
            hw = t.get("highway")
            if hw in WIDTHS and not under:
                for piece in _clip_line(line, W, H):
                    roads.append({"kind": "bridge" if t.get("bridge") not in (None, "no") else "road",
                                  "width": _width(t), "points": norm(piece), "name": t.get("name", "")})
            elif t.get("waterway") in RIVER_WIDTHS and not under:
                for piece in _clip_line(line, W, H):
                    rivers.append({"width": _num(t.get("width")) or RIVER_WIDTHS[t["waterway"]], "points": norm(piece)})
            continue
        layer = _area_layer(t)
        if layer is None or (layer == "buildings" and under):
            continue
        if kind == "open":
            if layer == "water":
                loose += [[P(q) for q in ch] for ch in g]
            continue
        for ring in g:
            poly = [P(q) for q in ring[:-1] if q] if ring[0] == ring[-1] else [P(q) for q in ring]
            if len(poly) < 3:
                continue
            if layer == "buildings" and not (0 <= geom.centroid(poly)[0] <= W and 0 <= geom.centroid(poly)[1] <= H):
                continue
            cut = geom.clip_convex(poly if geom.area(poly) > 0 else poly[::-1], box)
            if len(cut) >= 3 and abs(geom.area(cut)) > 1.0:
                areas[layer].append(cut)
                if layer == "buildings":
                    btags.append(t)
    if len(areas["buildings"]) > MAX_BUILDINGS:
        raise ValueError(f"건물이 너무 많아요 ({len(areas['buildings']):,}채). {MAX_BUILDINGS:,}채 안으로 좁혀 받아 주세요")
    if loose:
        areas["water"] += _close_open(loose, W, H, areas["buildings"], roads)
    if areas["water"] and rivers:  # 강이 넓이로 그려졌으면 가운데 선은 시내 · 도랑만
        rivers = [r for r in rivers if r["width"] <= RIVER_WIDTHS["stream"]]
    if not roads:
        raise ValueError("파일에 길이 없어요. 길이 있는 곳을 받아 주세요")
    parts = _parts(areas["buildings"], btags, pois)
    out: dict = {"w": round(W, 3), "h": round(H, 3), "generator": GENERATOR, "version": "", "source": SOURCE,
                 "roads": roads, "trees": norm(trees), "parts": parts}
    for key, polys in areas.items():
        if polys:
            out[key] = [norm(p) for p in polys]
    if rivers:
        out["rivers"] = rivers
    return out


def _coords(kind: str, g) -> list:
    if kind == "point":
        return [g]
    if kind == "line":
        return list(g)
    return [q for ring in g for q in ring]


def _under(t: dict) -> bool:
    """땅속이나 덮인 것 (지하상가, 터널, 지하 주차장)."""
    layer = _num(t.get("layer"))
    return (layer is not None and layer < 0) or t.get("location") in ("underground", "indoor") or t.get("tunnel") not in (None, "no") \
        or t.get("covered") == "yes"


def _area_layer(t: dict) -> Optional[str]:
    if "building" in t:
        return None if t["building"] in ("roof", "no") else "buildings"
    pairs = set(t.items())
    if pairs & WATER:
        return "water"
    if pairs & FIELD:
        return "fields"
    if pairs & GREEN:
        return "greens"
    if t.get("place") == "square" or (t.get("highway") == "pedestrian" and t.get("area") == "yes"):
        return "squares"
    return None


def _num(v) -> Optional[float]:
    """'12', '12.5 m', '3;4' 같은 태그 값의 첫 수."""
    if v is None:
        return None
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", str(v))
    return float(m.group(1)) if m else None


def _width(t: dict) -> float:
    w = _num(t.get("width"))
    if w and 1 <= w <= 120:
        return round(w, 1)
    lanes = _num(t.get("lanes"))
    if lanes and 1 <= lanes <= 16:
        return round(lanes * 3.3 + 2, 1)
    return float(WIDTHS[t["highway"]])


def _clip_line(line: list[Point], W: float, H: float) -> list[list[Point]]:
    """꺾은선을 범위 [0, W] × [0, H] 안의 조각들로 (선분마다 Liang–Barsky)."""
    out: list[list[Point]] = []
    cur: list[Point] = []
    for a, b in zip(line, line[1:]):
        seg = _clip_seg(a, b, W, H)
        if seg is None:
            if len(cur) >= 2:
                out.append(cur)
            cur = []
            continue
        p, q = seg
        if cur and cur[-1] == p:
            cur.append(q)
        else:
            if len(cur) >= 2:
                out.append(cur)
            cur = [p, q]
        if q != b:  # 범위 밖으로 나갔다
            out.append(cur)
            cur = []
    if len(cur) >= 2:
        out.append(cur)
    return [c for c in out if geom.polyline_length(c) > 0.5]


def _clip_seg(a: Point, b: Point, W: float, H: float) -> Optional[tuple[Point, Point]]:
    t0, t1 = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in ((-dx, a[0]), (dx, W - a[0]), (-dy, a[1]), (dy, H - a[1])):
        if p == 0:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
        if t0 > t1:
            return None
    pa = a if t0 == 0 else (a[0] + t0 * dx, a[1] + t0 * dy)
    pb = b if t1 == 1 else (a[0] + t1 * dx, a[1] + t1 * dy)
    return pa, pb


def _close_open(chains: list[list[Point]], W: float, H: float, blds: list, roads: list[dict]) -> list[list[Point]]:
    """범위에 다 들어오지 않은 물의 끊긴 물가 선 → 범위 테두리를 따라 닫은 물 다각형.
    물가 선 조각마다 범위를 두 쪽으로 나누고, 건물 · 길이 덜 촘촘한 쪽을 물로 본다. 물이 오른쪽에 오도록 조각 방향을
    맞춘 뒤, 조각 끝에서 테두리를 따라(시계 방향) 가장 먼저 만나는 조각 시작으로 이어 고리를 만든다."""
    per = 2 * (W + H)

    def tpos(q: Point) -> float:  # 테두리 위 자리: 왼쪽 위에서 시계 방향 (y 아래 화면 기준)
        x, y = q
        if y <= 1e-6:
            return x
        if x >= W - 1e-6:
            return W + y
        if y >= H - 1e-6:
            return W + H + (W - x)
        return 2 * W + H + (H - y)

    corners = [(0.0, (0.0, 0.0)), (W, (W, 0.0)), (W + H, (W, H)), (2 * W + H, (0.0, H))]

    def walk(t_from: float, t_to: float) -> list[Point]:  # 테두리를 시계 방향으로 t_from → t_to 사이 모서리
        span = (t_to - t_from) % per
        ahead = sorted(((tc - t_from) % per, c) for tc, c in corners)
        return [c for d, c in ahead if 0 < d < span]

    on_rim = lambda q: q[0] <= 1e-6 or q[0] >= W - 1e-6 or q[1] <= 1e-6 or q[1] >= H - 1e-6  # noqa: E731
    pieces = [pc for ch in chains for pc in _clip_line(ch, W, H) if on_rim(pc[0]) and on_rim(pc[-1]) and pc[0] != pc[-1]]
    if not pieces:
        return []
    marks = [geom.centroid(b) for b in blds] + [(q[0] * W, q[1] * H) for r in roads if r["kind"] == "road" for q in r["points"][::2]]

    def busy(poly: list[Point]) -> float:
        a = abs(geom.area(poly))
        return sum(1 for q in marks if geom.inside(q, poly)) / a if a > 1 else math.inf

    oriented = []
    for pc in pieces:
        fwd = pc + walk(tpos(pc[-1]), tpos(pc[0]))  # 조각 + 끝에서 시계 방향으로 시작까지
        back = pc[::-1] + walk(tpos(pc[0]), tpos(pc[-1]))
        oriented.append(pc if busy(fwd) <= busy(back) else pc[::-1])
    used = [False] * len(oriented)
    out = []
    for k in range(len(oriented)):
        if used[k]:
            continue
        ring: list[Point] = []
        cur = k
        for _ in range(len(oriented) + 1):
            used[cur] = True
            ring += oriented[cur]
            t_end = tpos(oriented[cur][-1])
            nxt = min(range(len(oriented)), key=lambda j: ((tpos(oriented[j][0]) - t_end) % per) if (not used[j] or j == k) else math.inf)
            ring += walk(t_end, tpos(oriented[nxt][0]))
            if nxt == k:
                break
            cur = nxt
        if len(ring) >= 3 and abs(geom.area(ring)) > 1:
            out.append(ring)
    return out


def use_of(t: dict) -> str:
    """태그 하나의 쓰임 (bldgs.USES id). 모르면 ''."""
    if t.get("railway") == "station" or t.get("public_transport") == "station":
        return "station"
    a = t.get("amenity")
    if a == "place_of_worship":
        rel = t.get("religion", "")
        return "church" if rel == "christian" else "buddhist" if rel == "buddhist" else "temple"
    if a in _AMENITY:
        return _AMENITY[a]
    if "shop" in t:
        return _SHOP.get(t["shop"], "store")
    if "office" in t:
        return "company"
    if t.get("tourism") in ("hotel", "motel", "hostel", "guest_house"):
        return "hotel"
    if t.get("leisure") in ("fitness_centre", "sports_centre", "sports_hall", "swimming_pool"):
        return "gym"
    if t.get("healthcare") in ("hospital",):
        return "hospital"
    if t.get("healthcare") in ("clinic", "doctor", "dentist"):
        return "doctor"
    if t.get("healthcare") == "pharmacy":
        return "pharmacy"
    return _BUILDING.get(t.get("building", ""), "")


def _parts(polys: list[list[Point]], btags: list[dict], pois: list[tuple[Point, dict]]) -> list[dict]:
    """건물마다 {lot, part, zone, use, name, levels, addr, tenants}. 가게 · 시설 점은 그 점이 든 건물에 붙인다."""
    grid = geom.Grid(40)
    for i, p in enumerate(polys):
        grid.add(geom.bbox(p), i)
    inside: dict[int, list[dict]] = {}
    for q, t in pois:
        i = next((j for j in grid.near((q[0], q[1], q[0], q[1])) if geom.inside(q, polys[j])), None)
        if i is not None:
            inside.setdefault(i, []).append(t)
    out = []
    for i, t in enumerate(btags):
        own = use_of({k: v for k, v in t.items() if k != "building"}) or ""
        found = [use_of(x) for x in inside.get(i, [])]
        found = [u for u in found if u]
        use = own or min(found, key=lambda u: _RANK.index(u) if u in _RANK else len(_RANK), default="") \
            or _BUILDING.get(t.get("building", ""), "") or "building"
        tenants = list(dict.fromkeys(x["name"] for x in inside.get(i, []) if x.get("name")))[:12]
        name = t.get("name", "") or (tenants[0] if len(tenants) == 1 else "")
        street, no = t.get("addr:street", ""), t.get("addr:housenumber", "")
        levels = _num(t.get("building:levels"))
        out.append({"lot": i, "part": "main", "zone": "", "use": use, "name": name,
                    "levels": int(round(levels)) if levels and 0 < levels < 200 else 0,
                    "addr": f"{street} {no}".strip() if street and no else "", "tenants": tenants})
    return out

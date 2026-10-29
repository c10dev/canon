"""지도: 장소를 지도 위에 놓고, 화별 인물 위치를 재생한다. LLM 을 부르지 않는다.

장소는 따로 정의하지 않는다. 설정의 장소 칸(world.locations)과 인과율 '장소' 요소가 장소이고,
지도(Project.atlas)는 그 위에 자리(pins), 배경 그림, 위치 글 잇기(links)만 더한다.
인물 위치는 상태 변경안이 적은 CharacterState.location 글을 화별 상태(cast.walk)에서 읽어 장소 이름과 맞춘다.
'하르덴에서 벨라 항구로 가는 길'처럼 두 곳이 나오면 뒤에 나온 곳을 지금 자리로, 앞의 곳을 거쳐 온 곳으로 본다.

마을 · 도시 데이터(Watabou 마을 · 도시 생성기의 JSON 내보내기)를 올리면 건물 · 길 · 물을 바탕으로 그리고,
화별로 옮겨 간 인물은 길을 따라 걸은 경로(route)와 거리 · 걷는 시간을 붙인다 (read_layout, road_graph, route).
마을 · 도시 · 현대 동네는 지도 만들기(towngen 마을 생성기, citygen 도시 생성기, moderngen 현대 동네 생성기)로 직접 만들 수도 있다: 미리보기(generate)는 저장하지 않고,
적용(apply_generated)하면 같은 입력으로 다시 만들어 저장하고 고른 장소만 생성기가 고른 자리에 놓는다.

화면은 canon/static/atlas.js, 명령줄은 `map`.
"""
from __future__ import annotations

import heapq
import json
import math
from pathlib import Path
from typing import Optional

from . import bldgs, cast, citygen, elements, fill, geom, moderngen, naming, osm, placekinds, towngen
from .schema import BuildingNote, MapFill, MapPin, MapSpec, NewPlace, PlaceLink, PlaceSort, Project

IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
IMAGE_LIMIT = 15 * 1024 * 1024
SORT_CHUNK = 60  # AI 정리 한 번에 보낼 위치 글 수
LAYOUT_LIMIT = 20 * 1024 * 1024  # 마을 데이터 파일 크기 (OpenStreetMap .osm 은 같은 넓이에 Watabou 파일보다 크다)
WALK_MPS = 1.3  # 걷는 속도 (m/초)
WALK_GRID = 200  # 길 밖을 걸을 때 지도의 긴 변을 나누는 칸 수


def places(p: Project) -> list[dict]:
    """지도에 놓을 수 있는 장소. 인과율 장소 요소 먼저, 그다음 요소와 겹치지 않는 설정 장소 칸.
    known_from 은 독자가 이 장소를 아는 화(0 이면 처음부터): 생긴 화, 처음 나온 화, 드러나는 화 중 가장 늦은 것."""
    out, seen = [], set()
    for el in p.elements:
        if el.kind != "장소" or not el.name.strip():
            continue
        seen |= {naming.place_key(t) for t in [el.name, *el.aliases] if t.strip()}
        out.append({"key": el.id, "name": el.name.strip(), "aliases": [a for a in el.aliases if a.strip()],
                    "description": el.description, "since_ep": el.since_ep, "found_ep": el.found_ep,
                    "reveal_ep": el.reveal_ep, "known_from": max(el.since_ep, el.found_ep, el.reveal_ep, 0), "source": "요소"})
    for raw in p.world.locations:
        name = naming.place_base(raw)
        k = naming.place_key(name)
        if not k or k in seen:
            continue
        seen.add(k)
        desc = raw.strip()[len(name):].strip().lstrip(":：-–—,").strip()
        out.append({"key": "w:" + name, "name": name, "aliases": [], "description": desc, "since_ep": 0,
                    "found_ep": 0, "reveal_ep": 0, "known_from": 0, "source": "설정"})
    return out


def match(p: Project, text: str, pls: Optional[list[dict]] = None) -> list[str]:
    """위치 글에 나오는 장소 키를 글 순서대로. 작가가 이어 둔 글(atlas.links)이 먼저다.
    띄어쓰기는 무시하고, 다른 장소 이름 안에 든 짧은 이름(하르덴 왕궁 안의 하르덴)은 뺀다."""
    t = text.strip()
    if not t:
        return []
    link = next((ln for ln in p.atlas.links if ln.text.strip() == t), None)
    if link is not None:
        return [link.place] if link.place else []
    key = naming.place_key(t)
    hits = []
    for pl in pls if pls is not None else places(p):
        for term in [pl["name"], *pl["aliases"]]:
            k = naming.place_key(term)
            i = key.find(k) if len(k) >= 2 else -1
            if i >= 0:
                hits.append((i, i + len(k), pl["key"]))
    inner = lambda h: any(o[0] <= h[0] and h[1] <= o[1] and o[1] - o[0] > h[1] - h[0] for o in hits)  # noqa: E731
    out: list[str] = []
    for _, _, pk in sorted(h for h in hits if not inner(h)):
        if pk not in out:
            out.append(pk)
    return out


def mentions(text: str, pls: list[dict]) -> list[str]:
    """본문이나 플롯 글에 이름이 나오는 장소 키."""
    return [pl["key"] for pl in pls if any(len(term.strip()) >= 2 and term.strip() in text for term in [pl["name"], *pl["aliases"]])]


def frames(p: Project, pls: Optional[list[dict]] = None) -> list[dict]:
    """화별 인물 자리. 0 은 1화 시작 전, n 은 n화 반영 뒤 (인물 · 관계도 화면과 같은 시점).
    rows: 인물마다 위치 글, 맞춘 장소(place), 거쳐 온 곳(via), 앞 시점과 장소가 바뀌었는지(moved).
    mentioned: n화 본문(없으면 플롯)에 이름이 나온 장소."""
    pls = pls if pls is not None else places(p)
    out, prev = [], {}
    for n, sim in cast.walk(p):
        rows = []
        for s in sim.states:
            loc = s.location.strip()
            keys = match(p, loc, pls)
            at = keys[-1] if keys else ""
            before = prev.get(s.character_id, "")
            rows.append({"cid": s.character_id, "location": loc, "place": at, "via": keys[:-1],
                         "moved": bool(at and before and before != at)})
            if at:
                prev[s.character_id] = at
        e = p.episode(n) if n else None
        text = (e.text or "\n".join([e.plot.title, e.plot.summary, *e.plot.events])) if e else ""
        out.append({"episode": n, "rows": rows, "mentioned": mentions(text, pls) if text else []})
    return out


def unmatched(p: Project, fs: list[dict]) -> list[dict]:
    """어느 장소와도 맞지 않은 위치 글 (작가가 '그리지 않음'으로 이은 글은 뺀다). 처음 나온 화 순."""
    linked = {ln.text.strip() for ln in p.atlas.links}
    seen: dict[str, dict] = {}
    for f in fs:
        for r in f["rows"]:
            if not r["location"] or r["place"] or r["location"] in linked:
                continue
            x = seen.setdefault(r["location"], {"text": r["location"], "episodes": [], "characters": []})
            if f["episode"] not in x["episodes"]:
                x["episodes"].append(f["episode"])
            if r["cid"] not in x["characters"]:
                x["characters"].append(r["cid"])
    return list(seen.values())


def summary(p: Project, layout: Optional[dict] = None) -> dict:
    """지도 화면 한 번에 필요한 계산값. layout(read_layout 결과)을 주면 옮겨 간 인물에 길 따라 걸은 경로를 붙인다.
    이동 시간 검사 칸(travel.view)은 web.atlas_view 가 places · frames 로 붙인다 (atlas 는 travel 을 가져오지 않는다)."""
    pls = places(p)
    pins = {pin.place: [pin.x, pin.y] for pin in p.atlas.pins}
    for pl in pls:
        pl["pin"] = pins.get(pl["key"])
    fs = frames(p, pls)
    if layout:
        add_routes(fs, pins, road_graph(layout), p.atlas.meters)
        if not p.atlas.layout_size:  # 이 칸이 생기기 전에 올린 마을 데이터 (저장은 다음에 지도를 고칠 때)
            p.atlas.layout_size = [layout["w"], layout["h"]]
    aspect = round(layout["w"] / layout["h"], 4) if layout else p.atlas.aspect  # 마을 데이터가 있으면 마을을 그린다
    return {"places": pls, "frames": fs, "unmatched": unmatched(p, fs), "image": p.atlas.image,
            "aspect": aspect, "links": [ln.model_dump() for ln in p.atlas.links],
            "layout": layout_info(p, layout) if layout else None, "title": village_title(p, layout) if layout else None}


# ---------- 마을 · 도시 데이터 (Watabou 생성기 JSON) ----------

WALKABLE = {"roads": "road", "streets": "road", "alleys": "road", "planks": "bridge", "bridges": "bridge"}
AREAS = {"buildings": "buildings", "prisms": "buildings", "water": "water", "fields": "fields",
         "greens": "greens", "squares": "squares", "plazas": "squares"}
STROKES = {"rivers": "rivers", "walls": "walls"}  # 폭이 있는 선으로 그린다 (도시 생성기의 강 · 성벽)


def _lines(g: dict) -> list[list]:
    """GeoJSON 도형에서 선(점 목록)들. 다각형은 바깥 테두리를 선으로 본다."""
    t, c = g.get("type"), g.get("coordinates") or []
    if t == "GeometryCollection":
        return [ln for x in g.get("geometries") or [] for ln in _lines(x)]
    if t == "LineString":
        return [c]
    if t == "MultiLineString":
        return list(c)
    if t == "Polygon":
        return c[:1]
    if t == "MultiPolygon":
        return [poly[0] for poly in c if poly]
    return []


def parse_upload(text: str) -> dict:
    """올린 지도 파일 글 → 그릴 모양. .osm (XML) 과 OpenStreetMap GeoJSON 은 canon/osm.py, 나머지는 Watabou JSON (read_layout)."""
    s = text.lstrip()
    if s.startswith("<"):
        return osm.parse(s)
    try:
        raw = json.loads(s)
    except ValueError:
        raise ValueError("JSON 파일을 읽지 못했어요") from None
    return osm.parse(s) if osm.is_osm(raw) else read_layout(raw)


def read_layout(raw: dict) -> dict:
    """Watabou 마을 · 도시 생성기가 내보낸 JSON 을 지도 화면이 그릴 모양으로 바꾼다.
    좌표는 0~1 비율 (x 는 폭, y 는 높이 기준. 생성기 화면처럼 y 가 아래로 커진다).
    w, h 는 원래 단위의 폭 · 높이 (거리 계산), road 선마다 폭 width (원래 단위)."""
    if not isinstance(raw, dict) or raw.get("type") != "FeatureCollection" or not isinstance(raw.get("features"), list):
        raise ValueError("Watabou 생성기에서 Export as → JSON으로 받은 파일을 올리세요 (GeoJSON FeatureCollection)")
    feats = {}
    meta = {}
    for f in raw["features"]:
        if not isinstance(f, dict):
            continue
        g = f.get("geometry") if isinstance(f.get("geometry"), dict) else f
        fid = str(f.get("id") or (f.get("properties") or {}).get("id") or "")
        if fid == "values":
            meta = {k: v for k, v in f.items() if k in ("generator", "version", "roadWidth")}
            continue
        feats[fid] = g
    pts = [pt for g in feats.values() for ln in _lines(g) for pt in ln if isinstance(pt, list) and len(pt) >= 2]
    earth = _lines(feats["earth"])[0] if "earth" in feats and _lines(feats["earth"]) else pts
    if not earth:
        raise ValueError("파일에 좌표가 없어요")
    xs, ys = [float(q[0]) for q in earth], [float(q[1]) for q in earth]
    x0, y0, w, h = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
    if w <= 0 or h <= 0:
        raise ValueError("지도 범위를 알 수 없어요")
    norm = lambda ln: [[round((float(q[0]) - x0) / w, 5), round((float(q[1]) - y0) / h, 5)] for q in ln if len(q) >= 2]  # noqa: E731
    out: dict = {"w": round(w, 3), "h": round(h, 3), "generator": str(meta.get("generator", "")),
                 "version": str(meta.get("version", "")), "roads": [], "trees": []}
    for fid, kind in WALKABLE.items():
        g = feats.get(fid)
        for x in (g.get("geometries") or [g]) if g else []:
            for ln in _lines(x):
                if len(ln) >= 2:
                    out["roads"].append({"kind": kind, "width": float(x.get("width") or 1), "points": norm(ln)})
    for fid, key in AREAS.items():
        g = feats.get(fid)
        if g:
            out.setdefault(key, []).extend(norm(ln) for ln in _lines(g) if len(ln) >= 3)
    for fid, key in STROKES.items():
        g = feats.get(fid)
        for x in (g.get("geometries") or [g]) if g else []:
            for ln in _lines(x):
                if len(ln) >= 2:
                    out.setdefault(key, []).append({"width": float(x.get("width") or 1), "points": norm(ln)})
    if "trees" in feats and feats["trees"].get("type") == "MultiPoint":
        out["trees"] = norm(feats["trees"].get("coordinates") or [])
    if not out["roads"]:
        raise ValueError("파일에 길(roads)이 없어요. 마을 · 도시 생성기의 JSON을 올리세요")
    return out


def load_layout(folder: Path, p: Project) -> Optional[dict]:
    """작품 폴더 map/ 의 마을 데이터. 없거나 읽지 못하면 None.
    건물 정보(blds, streets)가 없거나 옛 판이면 만들어 파일에 다시 쓴다 (이 기능 전에 만든 · 올린 지도)."""
    if not p.atlas.layout:
        return None
    path = folder / p.atlas.layout
    try:
        lo = json.loads(path.read_text(encoding="utf-8")) if path.is_file() and path.parent == folder else None
    except (OSError, ValueError):
        return None
    if lo is not None and lo.get("bver") != bldgs.VERSION:
        enrich(p, lo, p.atlas.spec.seed if p.atlas.spec else p.atlas.layout)
        try:
            path.write_text(json.dumps(lo, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return lo


def enrich(p: Project, lo: dict, seed) -> dict:
    """마을 데이터에 건물 쓰임 · 층수 · 사는 사람 · 주소와 거리 이름을 더한다 (canon/bldgs.py). 작품 이름 스타일을 따른다."""
    lo.update(bldgs.describe(lo, seed, naming.resolve_style(p)))
    return lo


def building(p: Project, layout: dict, i: int) -> dict:
    """건물 하나의 정보: 생성기 값에 작가가 고친 값(Atlas.buildings)을 덮는다. 곁채는 본채 정보를 쓴다.
    돌려주는 것: {i, main, use, label, group, floors, people, street, no, addr, tenants, name, note, residents, place, edited, made}.
    addr · tenants 는 OpenStreetMap 지도의 실제 주소 · 입점한 곳 (없으면 빈 값)."""
    blds = layout.get("blds") or []
    if not 0 <= i < len(blds):
        raise KeyError(f"건물이 없어요: {i}")
    main = blds[i].get("of", i)
    b = dict(blds[main])
    mine = next((x for x in p.atlas.buildings if x.i == main), None)
    style = naming.resolve_style(p)
    use = (mine.use if mine and mine.use else "") or b.get("use", "home")
    streets = layout.get("streets") or []
    st = streets[b["street"]]["name"] if isinstance(b.get("street"), int) and b["street"] < len(streets) else ""
    return {"i": i, "main": main, "use": use, "label": bldgs.label(use, style), "group": bldgs.USES.get(use, ("", "home"))[1],
            "floors": b.get("floors", 1), "people": b.get("people", 0), "street": st, "no": b.get("no", 0),
            "addr": b.get("addr", ""), "tenants": list(b.get("tenants", [])),
            "name": (mine.name if mine and mine.name else "") or b.get("name", ""), "note": mine.note if mine else "",
            "residents": list(mine.residents) if mine else [], "place": b.get("place", ""), "edited": bool(mine),
            "made": bool(b.get("made"))}


def building_counts(p: Project, layout: dict) -> list[tuple[str, int]]:
    """본채 쓰임별 수 (작가가 고친 값 반영), 많은 것부터. 집 · 농가 · 셋집은 뒤로."""
    blds = layout.get("blds") or []
    mine = {x.i: x.use for x in p.atlas.buildings if x.use}
    style = naming.resolve_style(p)
    count: dict[str, int] = {}
    for i, b in enumerate(blds):
        if "of" in b:
            continue
        u = mine.get(i) or b.get("use", "home")
        count[u] = count.get(u, 0) + 1
    order = sorted(count.items(), key=lambda kv: (kv[0] in bldgs.HOMES, -kv[1], kv[0]))
    return [(bldgs.label(u, style), n) for u, n in order]


def set_building(p: Project, layout: dict, i: int, use: str, name: str, note: str, residents: list[str]) -> None:
    """작가가 건물 하나를 고친다. 곁채를 고르면 본채를 고친다. 모두 비우면 고친 기록을 지운다."""
    blds = layout.get("blds") or []
    if not 0 <= i < len(blds):
        raise KeyError(f"건물이 없어요: {i}")
    main = blds[i].get("of", i)
    if use and use not in bldgs.USES:
        raise ValueError(f"모르는 쓰임이에요: {use}")
    name, note = " ".join(name.split())[:40], note.strip()[:500]
    cids = {c.id for c in p.characters}
    bad = [c for c in residents if c not in cids]
    if bad:
        raise ValueError(f"없는 인물이에요: {', '.join(bad)}")
    rest = [x for x in p.atlas.buildings if x.i != main]
    if use or name or note or residents:
        rest.append(BuildingNote(i=main, use=use, name=name, note=note, residents=list(dict.fromkeys(residents))))
    p.atlas.buildings = sorted(rest, key=lambda x: x.i)


def layout_info(p: Project, layout: dict) -> dict:
    """화면 · 명령줄에 보일 요약."""
    m = p.atlas.meters
    return {"file": p.atlas.layout, "roads": sum(r["kind"] == "road" for r in layout["roads"]),
            "bridges": sum(r["kind"] == "bridge" for r in layout["roads"]), "buildings": len(layout.get("buildings", [])),
            "width_m": round(layout["w"] * m), "height_m": round(layout["h"] * m), "meters": m,
            "generator": layout.get("generator", ""), "source": layout.get("source", ""), "made": fill.made_count(layout),
            "coast_broken": bool(layout.get("coast_broken"))}


def road_graph(layout: dict) -> dict:
    """길을 길찾기 그래프로. 좌표는 원래 단위(거리 그대로). 끝이 맞닿은 길끼리 잇고, 가장 큰 덩어리에 속한 길만 쓴다
    (다른 길과 이어지지 않은 다리 같은 조각에 장소가 붙어 길을 못 찾는 일이 없게)."""
    w, h = layout["w"], layout["h"]
    ids: dict[tuple, int] = {}
    nodes: list[tuple] = []
    adj: list[dict] = []

    def node(q):
        k = (round(q[0] * w, 2), round(q[1] * h, 2))
        if k not in ids:
            ids[k] = len(nodes)
            nodes.append(k)
            adj.append({})
        return ids[k]

    for r in layout["roads"]:
        for a, b in zip(r["points"], r["points"][1:]):
            i, j = node(a), node(b)
            if i != j:
                d = math.dist(nodes[i], nodes[j])
                adj[i][j] = adj[j][i] = min(d, adj[i].get(j, d))
    # 가장 큰 덩어리
    seen, best = set(), set()
    for s in range(len(nodes)):
        if s in seen:
            continue
        comp, stack = set(), [s]
        while stack:
            u = stack.pop()
            if u in comp:
                continue
            comp.add(u)
            stack.extend(v for v in adj[u] if v not in comp)
        seen |= comp
        if len(comp) > len(best):
            best = comp
    segs = [(i, j) for i in best for j in adj[i] if i < j]
    return {"w": w, "h": h, "nodes": nodes, "adj": adj, "segs": segs, "layout": layout}


# ---------- 길 밖 걷기: 장소 자리에서 길까지, 이웃한 곳끼리 ----------

def _field(g: dict) -> dict:
    """길 밖을 걸을 때 쓰는 칸 지도. 긴 변을 WALK_GRID 칸으로 나누고, 칸 가운데가 건물 · 물(섬 land 는 빼고) 안이거나
    강 · 성벽 선 폭 안이면 막힌 칸이다. owner 는 칸마다 건물 번호(0 부터), 물 · 강 · 성벽은 -2, 빈 땅은 -1.
    처음 쓸 때 한 번 만든다."""
    if "field" in g:
        return g["field"]
    w, h, lo = g["w"], g["h"], g["layout"]
    c = max(w, h) / WALK_GRID
    nx, ny = max(1, math.ceil(w / c)), max(1, math.ceil(h / c))
    owner = [-1] * (nx * ny)

    def fill(poly: list, k: int) -> None:  # 칸 가운데를 지나는 가로줄과 테두리가 만나는 곳 사이를 채운다
        pts = [(q[0] * w, q[1] * h) for q in poly]
        ys = [y for _, y in pts]
        for j in range(max(0, int(min(ys) / c - 0.5)), min(ny, int(max(ys) / c + 0.5) + 1)):
            y = (j + 0.5) * c
            xs = sorted(ax + (y - ay) * (bx - ax) / (by - ay)
                        for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]) if (ay <= y < by) or (by <= y < ay))
            for x1, x2 in zip(xs[::2], xs[1::2]):
                for i in range(max(0, math.ceil(x1 / c - 0.5)), min(nx, math.floor(x2 / c - 0.5) + 1)):
                    owner[j * nx + i] = k

    def stroke(line: dict) -> None:  # 선에서 폭의 절반 + 칸 반 안쪽의 칸을 막는다
        pts = [(q[0] * w, q[1] * h) for q in line["points"]]
        r = line["width"] / 2 + c / 2
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            for j in range(max(0, int((min(ay, by) - r) / c)), min(ny, int((max(ay, by) + r) / c) + 1)):
                for i in range(max(0, int((min(ax, bx) - r) / c)), min(nx, int((max(ax, bx) + r) / c) + 1)):
                    q = ((i + 0.5) * c, (j + 0.5) * c)
                    dx, dy = bx - ax, by - ay
                    t = max(0.0, min(1.0, ((q[0] - ax) * dx + (q[1] - ay) * dy) / (dx * dx + dy * dy or 1)))
                    if math.dist(q, (ax + t * dx, ay + t * dy)) <= r:
                        owner[j * nx + i] = -2

    polys: list[list] = []  # 건물 · 물 다각형 (원래 단위). 칸 검사가 놓치는 모서리를 정확히 본다
    near: dict[tuple, list] = {}  # 칸 → 그 칸에 걸친 다각형 번호 (다각형을 감싸는 네모 기준)
    for k, poly in enumerate(lo.get("water", []) + lo.get("buildings", [])):
        pts = [(q[0] * w, q[1] * h) for q in poly]
        polys.append(pts)
        xs, ys = [x for x, _ in pts], [y for _, y in pts]
        for j in range(max(0, int(min(ys) / c)), min(ny, int(max(ys) / c) + 1)):
            for i in range(max(0, int(min(xs) / c)), min(nx, int(max(xs) / c) + 1)):
                near.setdefault((i, j), []).append(k)
    for poly in lo.get("water", []):
        fill(poly, -2)
    for poly in lo.get("land", []):  # 바다 속 섬은 걷는 땅
        fill(poly, -1)
    for k, poly in enumerate(lo.get("buildings", [])):
        fill(poly, k)
    for line in lo.get("rivers", []) + lo.get("walls", []):
        stroke(line)
    g["field"] = {"c": c, "nx": nx, "ny": ny, "owner": owner, "polys": polys, "near": near}
    return g["field"]


def _inside(q: tuple, poly: list) -> bool:
    x, y, n = q[0], q[1], False
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            n = not n
    return n


def _meets(p: tuple, q: tuple, poly: list) -> bool:
    """선분 pq 가 다각형 안을 지나는지 (끝점이 안에 있거나 테두리와 엇갈린다)."""
    turn = lambda a, b, o: (b[0] - a[0]) * (o[1] - a[1]) - (b[1] - a[1]) * (o[0] - a[0])  # noqa: E731
    if _inside(p, poly) or _inside(q, poly):
        return True
    for a, b in zip(poly, poly[1:] + poly[:1]):
        if turn(p, q, a) * turn(p, q, b) < 0 and turn(a, b, p) * turn(a, b, q) < 0:
            return True
    return False


def _walk(g: dict, a: tuple, b: tuple) -> tuple[list, float]:
    """a 에서 b 까지 길 밖을 걷는 경로 (원래 단위): 건물 · 물 · 강 · 성벽을 돌아간다.
    a, b 가 들어 있는 건물은 지나갈 수 있다 (장소 자리는 건물 가운데에 놓인다).
    돌아갈 길이 없으면(물 안에 놓인 자리 등) 곧장 걷는다. 돌려주는 것: (점 목록, 길이)."""
    straight = ([a, b], math.dist(a, b))
    if math.dist(a, b) < 1e-9:
        return straight
    f = _field(g)
    c, nx, ny, owner = f["c"], f["nx"], f["ny"], f["owner"]
    cell = lambda q: (min(nx - 1, max(0, int(q[0] / c))), min(ny - 1, max(0, int(q[1] / c))))  # noqa: E731
    ca, cb = cell(a), cell(b)
    own = {owner[j * nx + i] for i, j in (ca, cb)} - {-1, -2}
    ends = {ca, cb}

    def free(i: int, j: int) -> bool:
        return owner[j * nx + i] == -1 or owner[j * nx + i] in own or (i, j) in ends

    polys, near = f["polys"], f["near"]
    skip = {k for q, cq in ((a, ca), (b, cb)) for k in near.get(cq, []) if _inside(q, polys[k])}  # a, b 가 든 건물 · 물

    def clear(p: tuple, q: tuple) -> bool:  # 선분이 막힌 칸을 지나지 않고 (칸 3분의 1 간격) 건물 · 물 모서리도 자르지 않는지
        n = max(1, math.ceil(math.dist(p, q) / (c / 3)))
        cells = {cell((p[0] + (q[0] - p[0]) * s / n, p[1] + (q[1] - p[1]) * s / n)) for s in range(n + 1)}
        if not all(free(*x) for x in cells):
            return False
        return not any(_meets(p, q, polys[k]) for k in {k for x in cells for k in near.get(x, [])} - skip)

    if clear(a, b):
        return straight

    def shore(x: tuple) -> tuple:  # 물 안의 끝(물가로 이어진 길 끝 등)은 가장 가까운 빈 칸에서 들어간다
        if free(*x) and owner[x[1] * nx + x[0]] != -2:
            return x
        best = min(((i, j) for j in range(max(0, x[1] - 8), min(ny, x[1] + 9)) for i in range(max(0, x[0] - 8), min(nx, x[0] + 9))
                    if owner[j * nx + i] == -1), key=lambda y: math.dist(y, x), default=x)
        ends.add(best)
        return best

    if (owner[ca[1] * nx + ca[0]] == -2) != (owner[cb[1] * nx + cb[0]] == -2):
        ca, cb = shore(ca), shore(cb)
    # A* (여덟 방향, 막힌 칸의 모서리는 자르지 않는다)
    guess = lambda i, j: c * (max(abs(i - cb[0]), abs(j - cb[1])) + (math.sqrt(2) - 1) * min(abs(i - cb[0]), abs(j - cb[1])))  # noqa: E731
    dist, prev, heap = {ca: 0.0}, {}, [(guess(*ca), 0.0, ca)]
    steps = [(di, dj, c * math.hypot(di, dj)) for di in (-1, 0, 1) for dj in (-1, 0, 1) if di or dj]
    while heap:
        _, d, u = heapq.heappop(heap)
        if u == cb:
            break
        if d > dist.get(u, math.inf):
            continue
        for di, dj, cost in steps:
            v = (u[0] + di, u[1] + dj)
            if not (0 <= v[0] < nx and 0 <= v[1] < ny) or not free(*v):
                continue
            if di and dj and not (free(u[0] + di, u[1]) and free(u[0], u[1] + dj)):
                continue
            if d + cost < dist.get(v, math.inf):
                dist[v], prev[v] = d + cost, u
                heapq.heappush(heap, (d + cost + guess(*v), d + cost, v))
    if cb not in dist:
        return straight
    cells, u = [cb], cb
    while u != ca:
        u = prev[u]
        cells.append(u)
    mid = [((i + 0.5) * c, (j + 0.5) * c) for i, j in reversed(cells)]
    pts = [a, *mid[1:-1], b] if (cell(a), cell(b)) == (ca, cb) else [a, *mid, b]
    out, k = [a], 0  # 보이는 가장 먼 점으로 건너뛰어 계단 모양을 편다
    while k < len(pts) - 1:
        nxt = next(m for m in range(len(pts) - 1, k, -1) if m == k + 1 or clear(pts[k], pts[m]))
        out.append(pts[nxt])
        k = nxt
    return out, sum(math.dist(p, q) for p, q in zip(out, out[1:]))


def _snap(g: dict, q: tuple) -> tuple:
    """점에서 가장 가까운 길 위의 점: (거리, 구간 i, j, 그 점)."""
    best = None
    for i, j in g["segs"]:
        (ax, ay), (bx, by) = g["nodes"][i], g["nodes"][j]
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((q[0] - ax) * dx + (q[1] - ay) * dy) / (dx * dx + dy * dy or 1)))
        pt = (ax + t * dx, ay + t * dy)
        d = math.dist(q, pt)
        if best is None or d < best[0]:
            best = (d, i, j, pt)
    return best  # type: ignore[return-value]


def route(g: dict, a: list, b: list) -> Optional[dict]:
    """0~1 좌표 a 에서 b 까지 길을 따라 가는 경로. 가장 가까운 길까지는 건물 · 물을 돌아 걷는다(_walk).
    길까지 가는 것보다 서로 가까우면 길을 타지 않고 걷는다. 돌려주는 것: points(0~1), length(원래 단위). 길이 없으면 None."""
    if not g["segs"]:
        return None
    w, h = g["w"], g["h"]
    pa, pb = (a[0] * w, a[1] * h), (b[0] * w, b[1] * h)
    da, ia, ja, sa = _snap(g, pa)
    db, ib, jb, sb = _snap(g, pb)
    norm = lambda pts: [[round(x / w, 5), round(y / h, 5)] for x, y in pts]  # noqa: E731
    if math.dist(pa, pb) <= da + db:  # 길까지 가는 것보다 서로 가까우면 길을 타지 않는다 (같은 곳, 이웃한 집)
        pts, length = _walk(g, pa, pb)
        return {"points": norm(pts), "length": length}
    nodes, adj = g["nodes"], g["adj"]
    S, T = -1, -2
    ext: dict[int, dict] = {S: {ia: math.dist(sa, nodes[ia]), ja: math.dist(sa, nodes[ja])}}
    into_t = {ib: math.dist(sb, nodes[ib]), jb: math.dist(sb, nodes[jb])}
    if {ia, ja} == {ib, jb}:
        ext[S][T] = math.dist(sa, sb)
    dist, prev, heap = {S: 0.0}, {}, [(0.0, S)]
    while heap:
        d, u = heapq.heappop(heap)
        if u == T:
            break
        if d > dist.get(u, math.inf):
            continue
        nxt = dict(ext.get(u, {})) if u < 0 else dict(adj[u])
        if u in into_t:
            nxt[T] = into_t[u]
        for v, c in nxt.items():
            if d + c < dist.get(v, math.inf):
                dist[v], prev[v] = d + c, u
                heapq.heappush(heap, (d + c, v))
    if T not in dist:
        return None
    chain, u = [], T
    while u != S:
        u = prev[u]
        if u >= 0:
            chain.append(nodes[u])
    (to_road, la), (from_road, lb) = _walk(g, pa, sa), _walk(g, sb, pb)
    pts = [*to_road, *reversed(chain), *from_road]
    clean = [pts[0]]
    for q in pts[1:]:
        if math.dist(q, clean[-1]) > 1e-6:
            clean.append(q)
    return {"points": norm(clean), "length": la + dist[T] + lb}


def add_routes(fs: list[dict], pins: dict, g: dict, meters: float) -> None:
    """옮겨 간 인물(moved)의 줄에 앞 장소에서 거쳐 온 곳을 지나 지금 장소까지 길 따라 걸은 경로를 붙인다.
    route: {points, meters, minutes}. 어느 장소라도 지도에 안 놓였으면 붙이지 않는다."""
    cache: dict[tuple, Optional[dict]] = {}
    last: dict[str, str] = {}
    for f in fs:
        for r in f["rows"]:
            at, before = r["place"], last.get(r["cid"], "")
            if at:
                last[r["cid"]] = at
            if not (r["moved"] and before):
                continue
            stops = [before, *[k for k in r["via"] if k != before], at]
            if not all(k in pins for k in stops):
                continue
            pts, length = [], 0.0
            for x, y in zip(stops, stops[1:]):
                if (x, y) not in cache:
                    cache[(x, y)] = route(g, pins[x], pins[y])
                leg = cache[(x, y)]
                if leg is None:
                    break
                pts += leg["points"] if not pts else leg["points"][1:]
                length += leg["length"]
            else:
                m = length * meters
                r["route"] = {"points": pts, "meters": round(m), "minutes": max(1, round(m / WALK_MPS / 60))}


# ---------- 마을 이름 · 인구, 지도에서 장소 더하기 ----------

POP_PER_HOUSE = 5.5  # 집 한 채에 사는 사람 (어림. Watabou 마을의 인구 표시와 비슷한 규모)
CITY_POP_PER_HOUSE = 8.0  # 도시 집은 층이 높고 세 든 사람이 많다 (어림)


def village_title(p: Project, layout: dict) -> dict:
    """지도 위 제목: 작가가 정한 이름, 없으면 '마을 가운데' 종류 장소 이름. 인구는 집 수 × 집 한 채에 사는 사람을 10 단위로
    (도시 생성기가 만든 지도는 CITY_POP_PER_HOUSE). kind: 이름 칸에 쓸 말 (마을 · 도시 · 동네), unit: 수를 세는 말 (집 · 건물).
    OpenStreetMap 지도와 현대 동네 생성기 지도는 건물을 세고, 인구는 주거 건물에서 어림한 사람 수만 쓴다 (canon/bldgs.py)."""
    name = p.atlas.title
    if not name:
        name = next((x["name"] for x in gen_places(p, p.atlas.spec) if x["kind"] == "center" and x["put"]), "")
    houses = layout.get("houses") or len(layout.get("numbers") or layout.get("buildings") or [])
    city = layout.get("generator") == citygen.GENERATOR
    real = layout.get("generator") in (osm.GENERATOR, moderngen.GENERATOR)
    per = CITY_POP_PER_HOUSE if city else POP_PER_HOUSE
    people = sum(b.get("people", 0) for b in layout.get("blds") or [])  # 건물마다 센 사람이 있으면 그 합
    return {"title": name, "custom": bool(p.atlas.title), "houses": houses, "population": int(round(people if real else people or houses * per, -1)),
            "kind": "도시" if city else "동네" if real else "마을", "unit": "건물" if real else "집"}


def set_title(p: Project, title: str) -> None:
    t = " ".join(title.split())
    if len(t) > 40:
        raise ValueError("지도 이름은 40자까지 적을 수 있어요")
    p.atlas.title = t


def add_place(p: Project, name: str, x: float, y: float, kind: str = "") -> str:
    """지도에서 고른 자리(건물 등)를 새 장소로 등록하고 그 자리에 놓는다. 인과율 '장소' 요소가 된다 (작가가 더한 요소).
    돌려주는 것: 새 장소 키."""
    n = " ".join(name.split())
    if not n:
        raise ValueError("장소 이름을 적어 주세요")
    pls = places(p)
    if place_by_name(n, pls):
        raise ValueError(f"이미 있는 장소예요: {n}")
    if not elements.add_places(p, [NewPlace(name=n, kind=kind.strip(), description="지도에서 더한 곳")], 0, ""):
        raise ValueError(f"비슷한 이름의 장소가 이미 있어요: {n}")
    key = place_by_name(n, places(p))
    set_pins(p, [*p.atlas.pins, MapPin(place=key, x=x, y=y)])
    return key


def name_ideas(p: Project, n: int = 6) -> list[str]:
    """새 장소 이름 후보 (작품 이름 스타일, 이미 있는 장소 이름은 뺀다). LLM 을 부르지 않는다."""
    have = {pl["name"] for pl in places(p)}
    return [c.name for c in naming.generate_places(naming.resolve_style(p), n, exclude=have)]


# ---------- 이름으로 자리 찾기 ----------

FIND_LIMIT = 8  # 장소 하나에 보일 후보 수
MARK_WORDS = {"bus": "버스 정류장", "entrance": "역 출입구"}  # 건물 쓰임이 아닌 표지 (osm._stop)


# ---------- 장소가 놓인 건물 (프롬프트 줄 데이터, 글은 mapprompt.spot_block) ----------

SPOT_NEAR = 25.0  # 핀이 건물 밖이면 이 거리(원래 단위) 안의 표지를 쓴다


def spot_line(p: Project, layout: dict, x: float, y: float) -> str:
    """0~1 자리가 든 건물의 한 줄: 이름(쓰임) · 층수 · 주소 · 입점한 곳 · 사는 인물 · 작가 메모.
    건물 밖이면 SPOT_NEAR 안의 표지(역 · 정류장 등). 둘 다 없으면 빈 글."""
    q = (x, y)
    blds = layout.get("blds") or []
    for i, poly in enumerate(layout.get("buildings") or []):
        if i >= len(blds) or not (min(v[0] for v in poly) <= x <= max(v[0] for v in poly)
                                  and min(v[1] for v in poly) <= y <= max(v[1] for v in poly)):
            continue
        if not geom.inside(q, [tuple(v) for v in poly]):
            continue
        b = building(p, layout, i)
        out = [f"{b['name']} ({b['label']})" if b["name"] else b["label"], f"{b['floors']}층"]
        where = b["addr"] or (f"{b['street']} {b['no']}" if b["street"] and b["no"] else b["street"])
        if where:
            out.append(where)
        if b["tenants"]:
            more = len(b["tenants"]) - 3
            out.append("입점: " + ", ".join(b["tenants"][:3]) + (f" 외 {more}곳" if more > 0 else ""))
        who = {c.id: c.name for c in p.characters}
        if b["residents"]:
            out.append("사는 인물: " + ", ".join(who.get(c, c) for c in b["residents"]))
        if b["note"]:
            out.append(" ".join(b["note"].split())[:80])
        return " · ".join(out)
    w, h = layout["w"], layout["h"]
    best, line = SPOT_NEAR, ""
    style = naming.resolve_style(p)
    for m in layout.get("marks") or []:
        d = math.hypot((m["x"] - x) * w, (m["y"] - y) * h)
        if d < best:
            use = m.get("use", "")
            what = bldgs.label(use, style) if use in bldgs.USES else MARK_WORDS.get(use, "")
            near = _road_near(layout, m["x"], m["y"])
            best, line = d, " · ".join(t for t in [f"{m['name']} ({what})" if what else m["name"], near] if t)
    return line


def fill_spots(p: Project, layout: Optional[dict]) -> None:
    """핀마다 놓인 건물 한 줄(MapPin.spot)을 다시 쓴다. 마을 데이터가 없으면 비운다.
    핀 · 마을 데이터 · 건물 고치기 뒤에 부른다 (web, 명령줄, apply_generated)."""
    for pin in p.atlas.pins:
        pin.spot = spot_line(p, layout, pin.x, pin.y) if layout else ""


def episode_spots(p: Project, n: int) -> list[tuple[str, str]]:
    """n화를 쓰거나 검수할 때 넣는 장소의 건물 줄 데이터: 플롯에 이름이 나온 장소 가운데 건물 한 줄(MapPin.spot)이 있는 것의
    (장소 이름, 한 줄), 플롯에 나온 차례. 글과 예산은 mapprompt.spot_block. 넣을 것이 없으면 빈 목록."""
    spots = {pin.place: pin.spot for pin in p.atlas.pins if pin.spot}
    ep = next((e for e in p.episodes if e.plot.number == n), None)
    if not spots or ep is None:
        return []
    pls = places(p)
    names = {pl["key"]: pl["name"] for pl in pls}
    keys = [k for k in mentions("\n".join([ep.plot.title, ep.plot.summary, *ep.plot.events]), pls) if k in spots]
    return [(names[k], spots[k]) for k in keys]


def episode_block(p: Project, n: int, budget: int = 0) -> str:
    """옛 이름 (시험이 부른다). 글은 mapprompt.spot_block 이 만든다. mapprompt 가 atlas 를 가져오므로 함수 안에서 가져온다."""
    from . import mapprompt

    return mapprompt.spot_block(p, n, budget)


def _road_near(layout: dict, x: float, y: float, within: float = 60.0) -> str:
    """0~1 자리에서 within(원래 단위) 안의 가장 가까운 이름 있는 길. 없으면 빈 글."""
    w, h = layout["w"], layout["h"]
    q = (x * w, y * h)
    best, name = within, ""
    for r in layout.get("roads") or []:
        if not r.get("name"):
            continue
        for a, b in zip(r["points"], r["points"][1:]):
            d = geom.seg_dist(q, (a[0] * w, a[1] * h), (b[0] * w, b[1] * h))
            if d < best:
                best, name = d, r["name"]
    return f"{name} 옆" if name else ""


def find_spots(p: Project, layout: dict) -> list[dict]:
    """장소 이름 · 다른 이름과 같은 이름(띄어쓰기 무시, 두 글자 이상)의 건물 · 입점한 곳 · 표지(osm 의 marks)를 찾는다.
    저장하지 않는다. 장소마다 {place, name, had(이미 놓음), options[{x, y, i, kind, what, near}], more(더 있는 수)}.
    kind: building 건물 이름 · mark 건물 밖 표지(역 · 공원 등) · tenant 건물 안 가게.
    건물 이름 → 역 → 다른 표지 → 출입구 · 정류장 → 입점 차례.
    맞는 곳이 없는 장소는 뺀다."""
    blds = layout.get("blds") or []
    polys = layout.get("buildings") or []
    streets = layout.get("streets") or []
    style = naming.resolve_style(p)
    mine = {x.i: x.name for x in p.atlas.buildings if x.name}
    rows: list[tuple[str, str, dict]] = []  # (비교 키, kind, 후보)
    for i, b in enumerate(blds):
        if "of" in b or i >= len(polys) or len(polys[i]) < 3:
            continue
        cx, cy = geom.centroid([tuple(q) for q in polys[i]])
        st = streets[b["street"]]["name"] if isinstance(b.get("street"), int) and b["street"] < len(streets) else ""
        near = b.get("addr") or st
        name = mine.get(i) or b.get("name", "")
        base = {"x": round(cx, 6), "y": round(cy, 6), "i": i, "near": near}
        if name:
            rows.append((naming.place_key(name), "building", {**base, "what": f"건물 '{name}'"}))
        where = name or bldgs.label(b.get("use", "building"), style)
        for t in b.get("tenants") or []:
            if t != name:
                rows.append((naming.place_key(t), "tenant", {**base, "what": f"'{where}' 안의 {t}"}))
    for m in layout.get("marks") or []:
        use = m.get("use", "")
        what = bldgs.label(use, style) if use in bldgs.USES else MARK_WORDS.get(use, "이름 붙은 곳")
        opt = {"x": m["x"], "y": m["y"], "i": -1, "near": "", "what": f"{m['name']} ({what})"}
        kind = "station" if use == "station" else "stop" if use in MARK_WORDS else "mark"
        rows.append((naming.place_key(m["name"]), kind, opt))
        if use == "station" and not m["name"].endswith("역"):  # OSM 역 이름은 '강남'처럼 '역'을 뺀다
            rows.append((naming.place_key(m["name"] + "역"), kind, opt))
    order = {"building": 0, "station": 1, "mark": 2, "stop": 3, "tenant": 4}
    pins = {pin.place for pin in p.atlas.pins}
    out = []
    for pl in places(p):
        keys = {k for k in (naming.place_key(t) for t in [pl["name"], *pl["aliases"]]) if len(k) >= 2}
        hits, seen = [], set()
        for k, kind, opt in sorted((r for r in rows if r[0] in keys), key=lambda r: order[r[1]]):
            spot = opt["i"] if opt["i"] >= 0 else (opt["x"], opt["y"])
            if spot not in seen:
                seen.add(spot)
                hits.append({**opt, "kind": "mark" if kind in ("station", "stop") else kind})
        for opt in hits[:FIND_LIMIT]:
            if opt["i"] < 0:  # 건물 밖 표지는 가까운 길 이름으로 가린다 (같은 이름 정류장이 여럿)
                opt["near"] = _road_near(layout, opt["x"], opt["y"])
        if hits:
            out.append({"place": pl["key"], "name": pl["name"], "had": pl["key"] in pins,
                        "options": hits[:FIND_LIMIT], "more": max(0, len(hits) - FIND_LIMIT)})
    return out


# ---------- 지도 만들기 (마을 생성기 canon/towngen.py, 도시 생성기 canon/citygen.py, 현대 동네 생성기 canon/moderngen.py) ----------

MODERN_STYLES = ("korea_modern", "japan", "sf")  # 건물 고치기 칸에 현대 쓰임을 보이는 이름 스타일
MAKERS = {"village": ("마을", towngen, towngen.village), "city": ("도시", citygen, citygen.city),
          "modern": ("현대 동네", moderngen, moderngen.neighborhood)}
# MapSpec.kind → (화면 이름, 생성기 모듈(OPTIONS · VERSION · ZONES), 만드는 함수). 왕국은 다음 단계


def _maker(kind: str):
    if kind not in MAKERS:
        raise ValueError(f"아직 만들 수 없는 지도예요: {kind}. 마을 · 도시 · 현대 동네 가운데 고르세요")
    return MAKERS[kind]


def gen_places(p: Project, spec: Optional[MapSpec] = None) -> list[dict]:
    """지도 만들기의 장소 표. 장소마다 종류(작가가 고친 값, 없으면 이름 · 설명에서 찾은 값)와 이 지도에 놓을지."""
    mine = {x.key: x for x in (spec.places if spec else [])}
    out = []
    for pl in places(p):
        found, word = placekinds.classify(pl["name"], pl["description"])
        m = mine.get(pl["key"])
        kind = m.kind if m and m.kind in placekinds.CATEGORY_IDS else found
        put = m.put if m and m.put is not None else placekinds.default_put(kind)
        out.append({"key": pl["key"], "name": pl["name"], "kind": kind, "found": found, "word": word, "put": put})
    return out


def default_spec(p: Project) -> MapSpec:
    """지도 만들기 입력. 만든 적이 있으면 그 입력, 없으면 기본값에 물만 장소를 보고 정한다 (등대 · 어시장이면 바다)."""
    if p.atlas.spec:
        return p.atlas.spec
    return MapSpec(water=placekinds.water_for(gen_places(p)))


def gen_info(p: Project) -> dict:
    """지도 화면의 '지도 만들기' 칸: 지금 입력(만든 적 없으면 기본값), 장소 표, 종류 이름.
    maps: 만들 수 있는 지도 [{id, label}], options · version: 지도 종류(MapSpec.kind)마다 설정 칸과 생성기 버전,
    wards: 도시 구역 · 현대 동네 슈퍼블록 종류 이름 (지도에 구역 이름을 쓴다), uses: 건물 쓰임 id → [작품 스타일에 맞는 이름, 묶음],
    modern: 현대 쓰임 id (건물 고치기 칸은 실제 지도 · 현대 동네 지도이거나 modern_style 일 때만 보인다), modern_style: 작품 이름 스타일이 현대인가."""
    spec = default_spec(p)
    style = naming.resolve_style(p)
    return {"spec": spec.model_dump(), "made": p.atlas.spec is not None, "places": gen_places(p, spec),
            "maps": [{"id": k, "label": m[0]} for k, m in MAKERS.items()],
            "options": {k: m[1].OPTIONS for k, m in MAKERS.items()},
            "kinds": [{"id": cid, "label": label} for cid, label, _ in placekinds.CATEGORIES],
            "version": {k: m[1].VERSION for k, m in MAKERS.items()}, "wards": {k: v for m in MAKERS.values() for k, v in m[1].ZONES.items()},
            "uses": {u: [bldgs.label(u, style), grp] for u, (_, grp) in bldgs.USES.items()},
            "modern": list(bldgs.MODERN), "modern_style": style in MODERN_STYLES}


def _blocked(lo: dict, xy: tuple[float, float]) -> bool:
    """0~1 자리가 새 마을의 건물 · 물 위인가 (옛 핀이 어색해지는 곳). 바다 속 섬(land)은 물이 아니다."""
    has = lambda key: any(geom.inside(xy, [tuple(q) for q in poly]) for poly in lo.get(key, []))  # noqa: E731
    if has("buildings") or (has("water") and not has("land")):
        return True
    q = (xy[0] * lo["w"], xy[1] * lo["h"])
    return any(geom.seg_dist(q, (a[0] * lo["w"], a[1] * lo["h"]), (b[0] * lo["w"], b[1] * lo["h"])) <= rv["width"] / 2
               for rv in lo.get("rivers", []) for a, b in zip(rv["points"], rv["points"][1:]))


def generate(p: Project, spec: MapSpec) -> dict:
    """미리보기 (저장하지 않음). spec.kind 로 마을 · 도시 · 현대 동네 생성기를 고른다.
    layout: read_layout 과 같은 모양의 지도, pins: 생성기가 고른 장소 자리
    (had: 이미 지도에 놓은 장소), missing: 놓지 못한 장소와 까닭, blocked: 새 마을에서 건물 · 물 위에 놓이는 옛 자리."""
    put = [x for x in gen_places(p, spec) if x["put"]]
    lo = enrich(p, _maker(spec.kind)[2](spec, put), spec.seed)
    pins = {pin.place: (pin.x, pin.y) for pin in p.atlas.pins}
    spots = {s["key"] for s in lo["spots"]}
    names = {pl["key"]: pl["name"] for pl in places(p)}
    return {"layout": lo,
            "pins": [{"place": s["key"], "name": s["name"], "kind": s["kind"], "x": s["x"], "y": s["y"], "had": s["key"] in pins}
                     for s in lo["spots"]],
            "missing": lo["missing"],
            "blocked": [{"place": k, "name": names.get(k, k)} for k, xy in pins.items() if k not in spots and _blocked(lo, xy)],
            "title": village_title(p, lo),
            "info": {"houses": lo["houses"], "buildings": len(lo["buildings"]), "roads": sum(r["kind"] == "road" for r in lo["roads"]),
                     "bridges": sum(r["kind"] == "bridge" for r in lo["roads"]), "width_m": round(lo["w"]), "height_m": round(lo["h"]),
                     "wards": len(lo.get("wards", [])), "gates": len(lo.get("gates", []))}}


def apply_generated(folder: Path, p: Project, spec: MapSpec, take: list[str]) -> str:
    """미리 본 마을을 적용한다: 같은 입력으로 다시 만들어 map/ 에 저장하고, 입력 · 축척(1단위 = 1m)을 적고,
    take 에 든 장소만 생성기가 고른 자리로 놓는다 (나머지 핀은 그대로). 돌려주는 것: 저장 뒤 지울 옛 파일 이름."""
    out = generate(p, spec)
    folder.mkdir(parents=True, exist_ok=True)
    fname = f"gen-{spec.kind}-{spec.seed}.json"
    (folder / fname).write_text(json.dumps(out["layout"], ensure_ascii=False), encoding="utf-8")
    old = p.atlas.layout
    if old != fname:
        p.atlas.buildings = []  # 건물 번호가 바뀌므로 고친 건물도 비운다
    p.atlas.layout, p.atlas.meters, p.atlas.fill = fname, 1.0, None
    p.atlas.layout_size = [out["layout"]["w"], out["layout"]["h"]]
    p.atlas.spec = spec.model_copy(update={"version": _maker(spec.kind)[1].VERSION})
    chosen = set(take)
    keep = [pin for pin in p.atlas.pins if pin.place not in chosen]
    set_pins(p, keep + [MapPin(place=s["place"], x=s["x"], y=s["y"]) for s in out["pins"] if s["place"] in chosen])
    fill_spots(p, out["layout"])
    return old if old and old != fname else ""


def set_meters(p: Project, meters: float) -> None:
    if not 0.01 <= meters <= 1000:
        raise ValueError("축척은 1단위에 0.01~1000m 사이로 정하세요")
    p.atlas.meters = round(float(meters), 3)


# ---------- 빈 블록 채우기 (OpenStreetMap 지도, canon/fill.py) ----------

def fill_preview(layout: dict, seed: int) -> dict:
    """빈 블록 채우기 미리보기 (저장하지 않음): {seed, blocks, buildings, empty, areas, added, had(지금 지은 건물 수)}.
    areas · added 는 채울 블록과 지을 건물 다각형 (0~1)."""
    _, st = fill.fill(layout, seed)
    return {"seed": seed, **st, "had": fill.made_count(layout)}


def made_count(layout: dict) -> int:
    """빈 블록에 지은 건물 수."""
    return fill.made_count(layout)


def apply_fill(folder: Path, p: Project, layout: dict, seed: int) -> dict:
    """빈 블록을 채워 지도 파일을 다시 쓴다. 지은 건물은 건물 끝에 붙어 OSM 건물 번호와 고친 건물은 그대로다
    (전에 지은 건물을 고친 기록만 지운다). 돌려주는 것: {seed, blocks, buildings, empty}."""
    out, st = fill.fill(layout, seed)
    _write_fill(folder, p, out, fill.base_count(layout))
    p.atlas.fill = MapFill(seed=seed, rule="villa")
    return {"seed": seed, **{k: st[k] for k in ("blocks", "buildings", "empty")}}


def clear_fill(folder: Path, p: Project, layout: dict) -> int:
    """지은 건물을 지워 지도 파일을 다시 쓴다. 돌려주는 것: 지운 건물 수."""
    n = fill.made_count(layout)
    _write_fill(folder, p, fill.clear(layout), fill.base_count(layout))
    p.atlas.fill = None
    return n


def _write_fill(folder: Path, p: Project, lo: dict, base: int) -> None:
    enrich(p, lo, p.atlas.layout)  # 올릴 때와 같은 시드 (파일 이름)
    (folder / p.atlas.layout).write_text(json.dumps(lo, ensure_ascii=False), encoding="utf-8")
    p.atlas.buildings = [x for x in p.atlas.buildings if x.i < base]
    fill_spots(p, lo)


# ---------- 작가가 고치기 ----------

def _clamp(v: float) -> float:
    return min(1.0, max(0.0, float(v)))


def set_pins(p: Project, pins: list[MapPin]) -> None:
    """장소 자리를 통째로 바꾼다. 없는 장소와 겹친 자리는 뺀다 (뒤에 온 것이 이긴다)."""
    keys = {pl["key"] for pl in places(p)}
    out: dict[str, MapPin] = {}
    for pin in pins:
        if pin.place in keys:
            out[pin.place] = MapPin(place=pin.place, x=_clamp(pin.x), y=_clamp(pin.y))
    p.atlas.pins = list(out.values())


def set_link(p: Project, text: str, place: Optional[str]) -> None:
    """위치 글 하나를 장소에 잇는다. place 가 None 이면 잇기를 지우고, 빈 문자열이면 '지도에 그리지 않음'."""
    t = text.strip()
    if not t:
        raise ValueError("위치 글이 비어 있어요")
    if place and place not in {pl["key"] for pl in places(p)}:
        raise ValueError(f"장소를 찾지 못했어요: {place}")
    p.atlas.links = [ln for ln in p.atlas.links if ln.text.strip() != t]
    if place is not None:
        p.atlas.links.append(PlaceLink(text=t, place=place))


def prune(p: Project) -> None:
    """지워진 장소의 자리와 잇기를 정리한다 (지도 화면을 저장할 때)."""
    keys = {pl["key"] for pl in places(p)}
    p.atlas.pins = [pin for pin in p.atlas.pins if pin.place in keys]
    p.atlas.links = [ln for ln in p.atlas.links if not ln.place or ln.place in keys]


# ---------- 맞지 않은 위치 글 한 번에 정리 (AI 제안은 pipeline.sort_places) ----------

def place_by_name(name: str, pls: list[dict]) -> str:
    """이름이나 다른 이름이 같은(띄어쓰기 무시) 장소 키. 없으면 빈 문자열."""
    k = naming.place_key(name.strip())
    if len(k) < 2:
        return ""
    return next((pl["key"] for pl in pls if any(naming.place_key(t) == k for t in [pl["name"], *pl["aliases"]])), "")


def clean_sort(p: Project, items: list[dict], outs: list[PlaceSort]) -> dict:
    """AI 제안을 화면에 보일 모양으로. 장소 이름은 키로 바꾸고, 이미 있는 이름의 새 장소는 그 장소로 돌린다.
    rows: 위치 글마다 {text, characters, episodes, place(키), new_place(이름), skip, note}.
    new_places: 실제로 쓰인 새 장소만, first_ep(그 장소로 이은 위치 글이 처음 나온 화)를 붙여서."""
    pls = places(p)
    guesses = {g.text.strip(): g for s in outs for g in s.matches}
    new: dict[str, NewPlace] = {}
    for s in outs:
        for x in s.new_places:
            k = naming.place_key(x.name.strip())
            if len(k) >= 2 and k not in new and not place_by_name(x.name, pls):
                new[k] = x.model_copy(update={"name": x.name.strip(), "description": x.description.strip(), "kind": x.kind.strip()})
    rows, first = [], {}
    for it in items:
        g = guesses.get(it["text"])
        place = place_by_name(g.place, pls) if g and g.place.strip() else ""
        newp = ""
        if not place and g and g.new_place.strip():
            place = place_by_name(g.new_place, pls)
            k = naming.place_key(g.new_place.strip())
            if not place and len(k) >= 2:
                new.setdefault(k, NewPlace(name=g.new_place.strip()))  # new_places 에 빠뜨린 이름
                newp = new[k].name
                eps = [n for n in it["episodes"] if n] or [0]
                first[k] = min(first.get(k, eps[0]), *eps)
        rows.append({**it, "place": place, "new_place": newp, "skip": bool(g and g.skip and not place and not newp),
                     "note": g.note.strip() if g else ""})
    return {"rows": rows, "new_places": [{**x.model_dump(), "first_ep": first[k]} for k, x in new.items() if k in first]}


def apply_sort(p: Project, new_places: list[tuple[NewPlace, int]], picks: list[tuple[str, str, str]]) -> dict:
    """작가가 고른 정리를 적용한다. new_places: (새 장소, 처음 나온 화). 고른 위치 글이 쓰는 것만 '장소' 요소로 등록한다.
    picks: (위치 글, 장소 키, 새 장소 이름). 장소 키와 새 장소 이름이 모두 비면 '지도에 그리지 않음'."""
    wanted = {naming.place_key(nw) for _, _, nw in picks if nw.strip()}
    added = []
    for x, n in new_places:
        if naming.place_key(x.name) in wanted:
            added += elements.add_places(p, [x], max(0, n), "본문")
    pls = places(p)
    keys = {pl["key"] for pl in pls}
    linked = 0
    for text, place, nw in picks:
        if nw.strip():
            place = place_by_name(nw, pls)
            if not place:
                raise ValueError(f"새 장소를 찾지 못했어요: {nw}")
        elif place and place not in keys:
            raise ValueError(f"장소를 찾지 못했어요: {place}")
        t = text.strip()
        if not t:
            continue
        p.atlas.links = [ln for ln in p.atlas.links if ln.text.strip() != t]
        p.atlas.links.append(PlaceLink(text=t, place=place))
        linked += 1
    return {"added": added, "linked": linked}


# ---------- 명령줄 ----------

def describe(p: Project, layout: Optional[dict] = None) -> str:
    """명령줄 `map <작품>`: 장소(지도에 놓았는지), 인물별 옮겨 다닌 길, 장소와 맞지 않은 위치 글.
    마을 데이터를 주면 옮긴 화마다 길 따라 걸은 거리 · 시간도."""
    s = summary(p, layout)
    pls = {pl["key"]: pl for pl in s["places"]}
    if not pls:
        return "장소가 아직 없어요. 설정의 장소 칸이나 인과율 '장소'에 더하면 지도에 놓을 수 있어요."
    lines = []
    if s["layout"]:
        lo = s["layout"]
        made = f" (지도 만들기, 시드 {p.atlas.spec.seed})" if p.atlas.spec else ""
        what = {citygen.GENERATOR: "도시", moderngen.GENERATOR: "현대 동네"}.get(lo["generator"], "마을")
        lines.append(f"{what} 데이터{made}: 길 {lo['roads']}개 · 다리 {lo['bridges']}개 · 건물 {lo['buildings']}채 · "
                     f"약 {lo['width_m']}×{lo['height_m']}m")
        uses = building_counts(p, layout)
        if uses:
            lines.append("건물 쓰임: " + " · ".join(f"{label} {n}" for label, n in uses[:12]) + (" 등" if len(uses) > 12 else ""))
        lines.append("")
    lines.append("장소")
    for pl in s["places"]:
        when = f" · {pl['known_from']}화부터 독자가 앎" if pl["known_from"] else ""
        lines.append(f"  {pl['name']} ({pl['source']}){when}{'' if pl['pin'] else ' · 지도에 아직 안 놓음'}")
    name = {c.id: c.name or c.id for c in p.characters}
    walks: dict[str, list[str]] = {}
    lastat: dict[str, str] = {}
    for f in s["frames"]:
        for r in f["rows"]:
            path = walks.setdefault(r["cid"], [])
            here = pls[r["place"]]["name"] if r["place"] else (f"'{r['location']}'" if r["location"] else "")
            if here and here != lastat.get(r["cid"]):
                lastat[r["cid"]] = here
                walk = f" (길 따라 {r['route']['meters']}m · 약 {r['route']['minutes']}분)" if r.get("route") else ""
                path.append(f"{f['episode'] or '시작'}{'화' if f['episode'] else ''} {here}{walk}")
    if walks:
        lines.append("\n인물이 있던 곳 (반영한 화 기준, 바뀐 화만)")
        for cid, path in walks.items():
            if path:
                lines.append(f"  {name.get(cid, cid)}: " + " → ".join(path))
    if s["unmatched"]:
        lines.append("\n장소와 맞지 않은 위치 글 (웹 지도 화면에서 장소에 이을 수 있어요)")
        for u in s["unmatched"]:
            lines.append(f"  '{u['text']}' · {', '.join(name.get(c, c) for c in u['characters'])} · {', '.join(f'{n}화' if n else '시작' for n in u['episodes'])}")
    return "\n".join(lines)

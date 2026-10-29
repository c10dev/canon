"""자리 찾기와 장소가 놓인 건물: 장소 이름과 같은 건물 · 표지 · 입점(find_spots), 핀이 놓인 건물 한 줄(spot_line, MapPin.spot),
쓰기 · 검수 프롬프트의 줄 데이터(episode_spots, 글은 prompt.spot_block). LLM 을 부르지 않는다."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from .. import naming
from ..schema import Project, Transit
from . import buildings as bldgs
from . import geom
from .buildings import building
from .layout import load_layout
from .places import mentions, places


# ---------- 이름으로 자리 찾기 ----------

FIND_LIMIT = 8  # 장소 하나에 보일 후보 수
MARK_WORDS = {"bus": "버스 정류장", "entrance": "역 출입구"}  # 건물 쓰임이 아닌 표지 (osm._stop)


# ---------- 장소가 놓인 건물 (프롬프트 줄 데이터, 글은 prompt.spot_block) ----------

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
    """지도 파일에서 셈해 작품에 적어 두는 값을 다시 쓴다: 핀마다 놓인 건물 한 줄(MapPin.spot)과 지하철 사본(Atlas.transit,
    지도 데이터의 transit 키, 이동 시간 검사가 읽는다). 마을 데이터가 없으면 비운다.
    핀 · 마을 데이터 · 건물 고치기 뒤에 부른다 (web, 명령줄, apply_generated)."""
    for pin in p.atlas.pins:
        pin.spot = spot_line(p, layout, pin.x, pin.y) if layout else ""
    tr = layout.get("transit") if layout else None
    p.atlas.transit = Transit.model_validate(tr) if isinstance(tr, dict) and tr.get("stations") else None


def fill_old_spots(p: Project, folder: Path, layout: Optional[dict] = None) -> bool:
    """건물 한 줄(MapPin.spot)이 빈 핀만 채운다 (이 칸이 생기기 전에 놓은 핀). 저장은 부르는 곳이 한다
    (지도 화면은 응답에만 싣고, 쓰기 · 검수 작업은 시작할 때 저장). 빈 핀이 없으면 지도 파일을 읽지 않는다.
    layout 을 주면 그것을 쓴다. 채운 핀이 하나라도 있으면 True (건물 밖 핀은 빈 채로 남아 False)."""
    empty = [pin for pin in p.atlas.pins if not pin.spot]
    if not empty or not p.atlas.layout:
        return False
    layout = layout if layout is not None else load_layout(folder, p)
    if not layout:
        return False
    done = False
    for pin in empty:
        pin.spot = spot_line(p, layout, pin.x, pin.y)
        done = done or bool(pin.spot)
    return done


def episode_spots(p: Project, n: int) -> list[tuple[str, str]]:
    """n화를 쓰거나 검수할 때 넣는 장소의 건물 줄 데이터: 플롯에 이름이 나온 장소 가운데 건물 한 줄(MapPin.spot)이 있는 것의
    (장소 이름, 한 줄), 플롯에 나온 차례. 글과 예산은 prompt.spot_block. 넣을 것이 없으면 빈 목록."""
    spots = {pin.place: pin.spot for pin in p.atlas.pins if pin.spot}
    ep = next((e for e in p.episodes if e.plot.number == n), None)
    if not spots or ep is None:
        return []
    pls = places(p)
    names = {pl["key"]: pl["name"] for pl in pls}
    keys = [k for k in mentions("\n".join([ep.plot.title, ep.plot.summary, *ep.plot.events]), pls) if k in spots]
    return [(names[k], spots[k]) for k in keys]


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

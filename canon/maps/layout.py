"""지도 데이터 형식: Watabou 마을 · 도시 생성기 JSON 읽기(read_layout), 올린 파일 가르기(parse_upload, OpenStreetMap 은 sources.osm),
작품 폴더 map/ 의 지도 파일(load_layout), 건물 정보 더하기(enrich, buildings.describe), 요약(layout_info), 축척. LLM 을 부르지 않는다."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .. import naming
from ..schema import Project
from . import buildings as bldgs
from . import fill
from .sources import osm


IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
IMAGE_LIMIT = 15 * 1024 * 1024
LAYOUT_LIMIT = 20 * 1024 * 1024  # 마을 데이터 파일 크기 (OpenStreetMap .osm 은 같은 넓이에 Watabou 파일보다 크다)


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
    """올린 지도 파일 글 → 그릴 모양. .osm (XML) 과 OpenStreetMap GeoJSON 은 canon/maps/sources/osm.py, 나머지는 Watabou JSON (read_layout)."""
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
    """마을 데이터에 건물 쓰임 · 층수 · 사는 사람 · 주소와 거리 이름을 더한다 (canon/maps/buildings.py). 작품 이름 스타일을 따른다."""
    lo.update(bldgs.describe(lo, seed, naming.resolve_style(p)))
    return lo


def layout_info(p: Project, layout: dict) -> dict:
    """화면 · 명령줄에 보일 요약."""
    m = p.atlas.meters
    return {"file": p.atlas.layout, "roads": sum(r["kind"] == "road" for r in layout["roads"]),
            "bridges": sum(r["kind"] == "bridge" for r in layout["roads"]), "buildings": len(layout.get("buildings", [])),
            "width_m": round(layout["w"] * m), "height_m": round(layout["h"] * m), "meters": m,
            "generator": layout.get("generator", ""), "source": layout.get("source", ""), "made": fill.made_count(layout),
            "coast_broken": bool(layout.get("coast_broken"))}


def set_meters(p: Project, meters: float) -> None:
    if not 0.01 <= meters <= 1000:
        raise ValueError("축척은 1단위에 0.01~1000m 사이로 정하세요")
    p.atlas.meters = round(float(meters), 3)

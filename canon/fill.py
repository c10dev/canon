"""빈 블록 채우기: OpenStreetMap 지도(canon/osm.py)에서 건물이 덜 그려진 블록에 건물을 지어 넣는다. LLM 을 부르지 않는다.

블록은 길 선과 지도 테두리가 나누는 가장 작은 면이다(blocks.faces). 빈 블록은 건물이 덮은 넓이가 EMPTY 아래이고 물 · 녹지 ·
광장 · 밭이 OPEN 을 넘지 않는 블록이다(넓이는 블록 안 격자 점으로 잰다). 채우는 규칙은 현대 동네 생성기(moderngen)의 빌라촌이다:
길에 닿은 변마다 필지 앞 폭(moderngen.DIVIDE["villa"])만큼 필지를 두고 필지마다 빌라 한 채(가끔 단독주택). OSM 블록은 볼록이 아니라
moderngen 의 볼록 다각형 자르기 대신 블록 변을 따라 필지 직사각형을 놓고, 블록 안 · 길 · 다른 건물 · 물과 녹지를 하나씩 확인한다.
블록 한 변이 BIG 을 넘으면 아파트 단지 규칙(판상 동을 줄 지어 놓기), 들어가지 않으면 빌라촌.

필지는 길 폭의 절반 + SETBACK 안쪽에 둔다. 기존 건물과 겹치는 필지는 버린다. 지은 건물은 buildings 끝에 붙이고 parts 에
made: true 를 적는다. 그래서 OSM 건물 번호(작가가 고친 건물 Atlas.buildings)는 바뀌지 않는다. 지은 건물에는 이름 · 주소 · 입점이 없고
쓰임은 빌라 · 단독주택 · 아파트뿐이다(실제 지도에 없는 가게를 짓지 않는다). 같은 지도 · 같은 시드면 같은 결과다(블록마다 난수원을 따로).
"""
from __future__ import annotations

import math
import random
from typing import Optional

from . import blocks, geom, moderngen, osm
from .geom import Point, Poly

RULES = {"villa": "빌라촌 (큰 블록은 아파트 단지)"}
EMPTY = 0.10  # 건물이 덮은 넓이가 블록의 이만큼 아래면 빈 블록
OPEN = 0.5  # 물 · 녹지 · 광장 · 밭이 이만큼 넘으면 채우지 않는다
BIG = 150.0  # 블록 한 변이 이보다 길면 아파트 단지 규칙 (m)
MIN_AREA = 400.0  # 이보다 작은 블록은 보지 않는다 (m²)
MAX_AREA = 250000.0  # 이보다 큰 블록도 보지 않는다 (공원 · 공항 · 지도 끝 큰 땅)
SETBACK = 2.0  # 길 폭의 절반에서 이만큼 더 안쪽에 필지를 둔다 (m)
FRONT, DEPTH = moderngen.DIVIDE["villa"][2], moderngen.DIVIDE["villa"][3]  # 필지 앞 폭 (m), 필지 깊이 (m)
YARD = (1.0, 0.6)  # 필지 안 건물: 길 쪽 · 옆과 뒤를 물리는 폭 (m)
GAP = 1.0  # 기존 건물과 이만큼 떨어진다 (m)
HOME_SHARE = 0.18  # 단독주택 (moderngen 빌라촌과 같은 비율)
SLAB = ((60.0, 90.0), (12.0, 15.0), (16.0, 26.0), (40.0, 50.0))  # 판상 동: 길이, 깊이, 동 사이 틈, 줄 간격 (moderngen 판상)
BUFFER = 6.0  # 단지 담장 안쪽 (moderngen.BUFFER)
SOURCE_NOTE = "빈 블록 건물은 Canon 이 지음"
FILLED_SOURCE = f"{osm.SOURCE} · {SOURCE_NOTE}"


def clear(layout: dict) -> dict:
    """지은 건물을 뺀 지도 (새 dict). 출처 글은 OpenStreetMap 출처로 돌린다. blds · streets 는 다시 채워야 한다(atlas.enrich)."""
    parts = layout.get("parts") or []
    keep = [i for i in range(len(layout.get("buildings", []))) if not (i < len(parts) and parts[i].get("made"))]
    out = {k: v for k, v in layout.items() if k not in ("blds", "streets", "bver")}
    out["buildings"] = [layout["buildings"][i] for i in keep]
    if parts:
        out["parts"] = [parts[i] for i in keep]
    if out.get("source") == FILLED_SOURCE:
        out["source"] = osm.SOURCE
    return out


def base_count(layout: dict) -> int:
    """지은 건물이 아닌 건물 수 (지은 건물은 늘 그 뒤에 있다)."""
    return sum(1 for pt in layout.get("parts") or [] if not pt.get("made")) if layout.get("parts") else len(layout.get("buildings", []))


def made_count(layout: dict) -> int:
    return sum(1 for pt in layout.get("parts") or [] if pt.get("made"))


def fill(layout: dict, seed: int | str, rule: str = "villa") -> tuple[dict, dict]:
    """빈 블록을 채운 지도 (새 dict, 지은 건물을 먼저 지운 뒤 채운다)와 {blocks(채운 블록), buildings(지은 건물), empty(빈 블록),
    areas(채운 블록 다각형, 0~1), added(지은 건물 다각형, 0~1)}. OpenStreetMap 지도만 채운다."""
    if layout.get("generator") != osm.GENERATOR:
        raise ValueError("빈 블록 채우기는 OpenStreetMap 지도에서만 해요")
    if rule not in RULES:
        raise ValueError(f"모르는 채우기 규칙이에요: {rule}")
    out = clear(layout)
    w, h = out["w"], out["h"]
    M = lambda q: (q[0] * w, q[1] * h)  # noqa: E731
    roads = [([M(q) for q in rd["points"]], float(rd.get("width") or 4)) for rd in out.get("roads", [])]
    site = _Site(roads, [[M(q) for q in poly] for poly in out.get("buildings", []) if len(poly) >= 3],
                 [[M(q) for q in poly] for key in ("water", "greens", "squares", "fields") for poly in out.get(key, []) if len(poly) >= 3])
    for rv in out.get("rivers", []):
        roads.append(([M(q) for q in rv["points"]], float(rv.get("width") or 4)))  # 강 가운데 선도 길처럼 비켜 짓는다
        site.add_road(roads[-1])
    added: list[tuple[Poly, str, str, int]] = []  # (다각형, zone, use, 층수)
    areas: list[Poly] = []
    empty = 0
    for k, face in enumerate(blocks.faces([pts for pts, _ in roads], w, h)):
        a = geom.area(face)
        if not MIN_AREA <= a <= MAX_AREA or not site.empty(face):
            continue
        empty += 1
        r = random.Random(f"{seed}:fill:{k}")
        got = _apartments(face, site, r) if _span(face) > BIG else []
        got = got or _villas(face, site, r)
        if got:
            areas.append(face)
            added += got
    n = len(out["buildings"])
    nx = lambda q: [round(q[0] / w, 6), round(q[1] / h, 6)]  # noqa: E731
    out["buildings"] = out["buildings"] + [[nx(q) for q in poly] for poly, *_ in added]
    parts = out.get("parts") or [{"lot": i, "part": "main", "zone": "", "use": ""} for i in range(n)]
    out["parts"] = parts + [{"lot": n + j, "part": "main", "zone": zone, "use": use, "levels": lv, "made": True}
                            for j, (_, zone, use, lv) in enumerate(added)]
    if added:
        out["source"] = FILLED_SOURCE
    return out, {"blocks": len(areas), "buildings": len(added), "empty": empty,
                 "areas": [[nx(q) for q in poly] for poly in areas], "added": out["buildings"][n:]}


# ---------- 둘레 (길 · 건물 · 물과 녹지를 격자에 넣어 가까운 것만 본다) ----------

class _Site:
    def __init__(self, roads: list[tuple[list[Point], float]], bldgs: list[Poly], opens: list[Poly]):
        self.roads = geom.Grid(30)
        for rd in roads:
            self.add_road(rd)
        self.bldgs = geom.Grid(30)
        for poly in bldgs:
            self.bldgs.add(geom.bbox(poly), poly)
        self.opens = geom.Grid(60)
        for poly in opens:
            self.opens.add(geom.bbox(poly), poly)

    def add_road(self, rd: tuple[list[Point], float]) -> None:
        pts, width = rd
        for a, b in zip(pts, pts[1:]):
            self.roads.add(geom.bbox([a, b]), (a, b, width))

    def empty(self, face: Poly) -> bool:
        """건물이 덮은 넓이가 EMPTY 아래이고 물 · 녹지 · 광장 · 밭이 OPEN 을 넘지 않는가 (블록 안 격자 점으로 잰다)."""
        x0, y0, x1, y1 = geom.bbox(face)
        step = max(2.0, math.sqrt(abs(geom.area(face)) / 400))
        pts = [(x0 + step * (i + 0.5), y0 + step * (j + 0.5)) for j in range(int((y1 - y0) / step) + 1)
               for i in range(int((x1 - x0) / step) + 1)]
        pts = [q for q in pts if geom.inside(q, face)]
        if not pts:
            return False
        box = (x0, y0, x1, y1)
        bl = self.bldgs.near(box)
        op = self.opens.near(box)
        built = sum(1 for q in pts if any(geom.inside(q, poly) for poly in bl))
        opened = sum(1 for q in pts if any(geom.inside(q, poly) for poly in op))
        return built < EMPTY * len(pts) and opened <= OPEN * len(pts)

    def width_at(self, q: Point) -> Optional[float]:
        """q 에서 1m 안의 길 폭 (가장 넓은 것). 길이 아니면(지도 테두리) None."""
        near = [wd for a, b, wd in self.roads.near((q[0], q[1], q[0], q[1]), 1.0) if geom.seg_dist(q, a, b) < 1.0]
        return max(near) if near else None

    def free(self, rc: Poly, face: Poly, road_gap: float, bld_gap: float, mine: list[Poly]) -> bool:
        """rc 가 블록 안에 있고, 길(폭의 절반 + road_gap) · 기존 건물(bld_gap) · 지은 건물(bld_gap) · 물과 녹지와 겹치지 않는가."""
        if not all(geom.inside(q, face) for q in rc):
            return False
        n = len(face)
        for i in range(4):
            a, b = rc[i - 1], rc[i]
            if any(geom.seg_cross(a, b, face[j - 1], face[j]) for j in range(n)):
                return False
        box = geom.bbox(rc)
        for a, b, wd in self.roads.near(box, 40):
            if geom.poly_seg_near(rc, a, b, wd / 2 + road_gap):
                return False
        for poly in self.bldgs.near(box, bld_gap + 1):
            if _touch(rc, poly, bld_gap):
                return False
        for poly in self.opens.near(box):
            if _touch(rc, poly, 0.0):
                return False
        return not any(geom.convex_overlap(rc, o, bld_gap) for o in mine)


def _touch(rc: Poly, poly: Poly, gap: float) -> bool:
    """볼록 rc 와 아무 다각형 poly 가 겹치거나 gap 보다 가까운가."""
    if any(geom.inside(q, poly) for q in rc):
        return True
    return any(geom.poly_seg_near(rc, poly[i - 1], poly[i], gap) for i in range(len(poly)))


def _frame(face: Poly) -> tuple[Point, Point]:
    """가장 긴 변 방향과 그 법선."""
    i = max(range(len(face)), key=lambda k: math.dist(face[k - 1], face[k]))
    ax = blocks.unit(face[i][0] - face[i - 1][0], face[i][1] - face[i - 1][1])
    return ax, (-ax[1], ax[0])


def _span(face: Poly) -> float:
    """가장 긴 변 방향과 그 법선 방향 가운데 긴 쪽의 폭."""
    out = 0.0
    for ax in _frame(face):
        proj = [q[0] * ax[0] + q[1] * ax[1] for q in face]
        out = max(out, max(proj) - min(proj))
    return out


# ---------- 빌라촌: 길에 닿은 변마다 필지, 필지마다 한 채 ----------

def _villas(face: Poly, site: _Site, r: random.Random) -> list[tuple[Poly, str, str, int]]:
    mine: list[Poly] = []
    out = []
    n = len(face)
    for i in sorted(range(n), key=lambda i: (-math.dist(face[i - 1], face[i]), i)):  # 긴 변부터
        a, b = face[i - 1], face[i]
        L = math.dist(a, b)
        if L < FRONT[0]:
            continue
        d = blocks.unit(b[0] - a[0], b[1] - a[1])
        mid = geom.lerp(a, b, 0.5)
        inward = (-d[1], d[0])
        if not geom.inside((mid[0] + inward[0] * 0.5, mid[1] + inward[1] * 0.5), face):
            inward = (d[1], -d[0])
        wd = site.width_at(mid)
        off = (wd / 2 + SETBACK if wd is not None else 0.5) + YARD[0]  # 지도 끝 변은 길이 없다
        t = r.uniform(0, 2)
        while t + FRONT[0] <= L:
            front = r.uniform(*FRONT)
            bw = min(front, L - t) - 2 * YARD[1]
            if bw < 6:
                break
            c0 = (a[0] + d[0] * (t + bw / 2 + YARD[1]), a[1] + d[1] * (t + bw / 2 + YARD[1]))
            for depth in (DEPTH, DEPTH * 0.7, DEPTH * 0.5):
                dep = depth - YARD[0] - YARD[1]
                c = (c0[0] + inward[0] * (off + dep / 2), c0[1] + inward[1] * (off + dep / 2))
                rc = geom.rect(c, inward, bw, dep)
                if geom.area(rc) < 0:
                    rc = rc[::-1]
                if site.free(rc, face, SETBACK + YARD[0] - 0.05, GAP, mine):
                    mine.append(rc)
                    home = r.random() < HOME_SHARE
                    out.append((rc, "villa", "home" if home else "villa", 2 if home else r.randint(4, 5)))
                    break
            t += front
    return out


# ---------- 아파트 단지: 판상 동을 줄 지어 ----------

def _apartments(face: Poly, site: _Site, r: random.Random) -> list[tuple[Poly, str, str, int]]:
    ax, nrm = _frame(face)
    pu = [q[0] * ax[0] + q[1] * ax[1] for q in face]
    pv = [q[0] * nrm[0] + q[1] * nrm[1] for q in face]
    ln, dp = r.uniform(*SLAB[0]), r.uniform(*SLAB[1])
    pitch = (ln + r.uniform(*SLAB[2]), r.uniform(*SLAB[3]))
    mine: list[Poly] = []
    v = min(pv) + BUFFER + dp / 2 + r.uniform(0, 8)
    row = 0
    while v < max(pv) - dp / 2:
        u = min(pu) + ln / 2 + (pitch[0] * 0.3 if row % 2 else 0) + r.uniform(0, 6)
        while u < max(pu):
            c = (ax[0] * u + nrm[0] * v, ax[1] * u + nrm[1] * v)
            for k in (1.0, 0.7, 0.5):
                rc = geom.rect(c, nrm, ln * k, dp)
                if geom.area(rc) < 0:
                    rc = rc[::-1]
                if site.free(rc, face, BUFFER, BUFFER, mine):
                    mine.append(rc)
                    break
            u += pitch[0]
        v += pitch[1]
        row += 1
    return [(rc, "apartment", "apartment", r.randint(12, 25)) for rc in mine]

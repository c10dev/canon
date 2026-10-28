"""지도 생성기가 함께 쓰는 블록 · 필지 쪼개기 도구: 직선과 선분이 만나는 곳, 꼬리표 달린 볼록 다각형 자르기 · 줄이기,
다각형 안에 직사각형 · 점 놓기, 꼭짓점을 나눠 쓰는 길 덩어리. 도시(citygen) · 현대 동네(moderngen) 생성기가 쓴다.
지도 데이터를 모르고 LLM 을 부르지 않는다. 바꾸면 두 생성기의 스냅샷 시험이 함께 바뀐다.
"""
from __future__ import annotations

import math
import random
from typing import Callable, Optional

from . import geom
from .geom import Point, Poly


def line_hit(p: Point, d: Point, a: Point, b: Point) -> Optional[tuple[float, Point]]:
    """직선 p + t·d 가 선분 ab 와 만나면 (ab 위 비율, 만나는 점)."""
    ex, ey = b[0] - a[0], b[1] - a[1]
    den = d[0] * ey - d[1] * ex
    if abs(den) < 1e-12:
        return None
    qx, qy = a[0] - p[0], a[1] - p[1]
    u = (qx * d[1] - qy * d[0]) / den
    return (u, geom.lerp(a, b, u)) if 0 <= u <= 1 else None


def unit(x: float, y: float) -> Point:
    n = math.hypot(x, y) or 1.0
    return (x / n, y / n)


# ---------- 꼬리표 달린 볼록 다각형 ----------
# 블록은 꼭짓점 목록 pts 와 변마다 꼬리표 tags (tags[i] 는 pts[i] → pts[i+1] 변이 무엇과 맞닿는지).
# ("e", 모서리) 는 구역 경계, ("a", 번호) 는 골목, ("x",) 는 길과 맞닿지 않은 변 (필지 경계 · 모퉁이).

def cut(pts: Poly, tags: list, a: Point, b: Point, tag) -> tuple[Poly, list]:
    """볼록 다각형에서 직선 a→b 왼쪽(넓이가 양수인 방향의 안쪽)만 남긴다. 새로 생긴 변의 꼬리표는 tag."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    side = [dx * (p[1] - a[1]) - dy * (p[0] - a[0]) for p in pts]
    op: Poly = []
    ot: list = []
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        sp, sq = side[i], side[j]
        if sp >= 0:
            op.append(pts[i])
            ot.append(tags[i])
            if sq < 0:
                op.append(geom.lerp(pts[i], pts[j], sp / (sp - sq)))
                ot.append(tag)
        elif sq >= 0:
            op.append(geom.lerp(pts[i], pts[j], sp / (sp - sq)))
            ot.append(tags[i])
    k = 0
    while k < len(op) and len(op) >= 3:  # 겹친 점은 앞의 것을 지운다 (뒤 점의 꼬리표가 맞다)
        if math.dist(op[k], op[(k + 1) % len(op)]) < 1e-7:
            del op[k], ot[k]
        else:
            k += 1
    if len(op) < 3 or geom.area(op) < 1e-6:
        return [], []
    return op, ot


def inset(pts: Poly, tags: list, ds: list[float]) -> tuple[Poly, list]:
    """변마다 ds[i] 만큼 안으로 민다."""
    P, T = list(pts), list(tags)
    n = len(pts)
    for i in range(n):
        if ds[i] <= 0:
            continue
        a, b = pts[i], pts[(i + 1) % n]
        nx, ny = unit(-(b[1] - a[1]), b[0] - a[0])
        P, T = cut(P, T, (a[0] + nx * ds[i], a[1] + ny * ds[i]), (b[0] + nx * ds[i], b[1] + ny * ds[i]), tags[i])
        if not P:
            return [], []
    return P, T


def crossings(pts: Poly, p: Point, d: Point) -> list[tuple[int, Point]]:
    """직선 p + t·d 가 볼록 다각형 변과 만나는 곳 (변 번호, 점)."""
    side = [d[0] * (q[1] - p[1]) - d[1] * (q[0] - p[0]) for q in pts]
    out = []
    n = len(pts)
    for i in range(n):
        sp, sq = side[i], side[(i + 1) % n]
        if (sp >= 0) != (sq >= 0):
            out.append((i, geom.lerp(pts[i], pts[(i + 1) % n], sp / (sp - sq))))
    return out


def fit_rect(poly: Poly, c: Point, along: Point, w: float, d: float, margin: float) -> Optional[Poly]:
    """c 에 along 방향으로 놓은 직사각형을 poly 안에 margin 을 두고 들어갈 때까지 줄인다."""
    for _ in range(8):
        r = geom.rect(c, along, w, d)
        if all(geom.inside(q, poly) and min(geom.seg_dist(q, poly[i - 1], poly[i]) for i in range(len(poly))) >= margin for q in r):
            return r
        w, d = w * 0.85, d * 0.85
    return None


def scatter(r: random.Random, poly: Poly, gap: float, share: float = 1.0, avoid: Optional[list[Poly]] = None) -> list[Point]:
    """poly 안에 서로 gap 쯤 떨어진 점 (나무). share 만 남긴다."""
    x0, y0, x1, y1 = geom.bbox(poly)
    out = []
    for q in geom.poisson(r, x1 - x0, y1 - y0, gap, k=8):
        p = (q[0] + x0, q[1] + y0)
        if r.random() < share and geom.inside(p, poly) and not any(geom.inside(p, a) for a in avoid or ()):
            out.append(p)
    return out


def parts(roads: list[dict], key: Callable) -> list[list[dict]]:
    """꼭짓점을 나눠 쓰는 길끼리 묶은 덩어리, 큰 것부터."""
    parent: dict = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for rd in roads:
        for a, b in zip(rd["pts"], rd["pts"][1:]):
            parent[find(key(a))] = find(key(b))
    groups: dict = {}
    for rd in roads:
        groups.setdefault(find(key(rd["pts"][0])), []).append(rd)
    return sorted(groups.values(), key=len, reverse=True)


# ---------- 길 선으로 블록 찾기 (평면 그래프의 면) ----------

def faces(lines: list[list[Point]], w: float, h: float, snap: float = 0.3) -> list[Poly]:
    """길 꺾은선들과 지도 테두리 [0, w] × [0, h] 가 나누는 가장 작은 면(블록), 무게중심 차례.
    선이 건너는 곳과 끝이 다른 선에서 snap 안에 닿는 곳(T자)을 꼭짓점으로 나누고, 막다른 길은 지운 뒤 반쪽 변을 따라 돈다.
    돌려주는 다각형은 넓이가 양수(geom.area)인 방향이다. 지도 끝에 걸린 블록은 테두리로 닫힌다."""
    box = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)]
    segs = [(a, b) for ln in lines for a, b in zip(ln, ln[1:]) if math.dist(a, b) > 1e-6]
    segs += [(box[i], box[(i + 1) % 4]) for i in range(4)]
    cuts: list[list[tuple[float, Point]]] = [[(0.0, a), (1.0, b)] for a, b in segs]
    grid = geom.Grid(40)
    for k, (a, b) in enumerate(segs):
        grid.add(geom.bbox([a, b]), k)

    def along(q: Point, a: Point, b: Point) -> float:
        dx, dy = b[0] - a[0], b[1] - a[1]
        return max(0.0, min(1.0, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / (dx * dx + dy * dy)))

    for k, (a, b) in enumerate(segs):
        for j in grid.near(geom.bbox([a, b]), snap):
            if j <= k:
                continue
            c, d = segs[j]
            hit = geom.seg_cross(a, b, c, d)
            if hit:
                cuts[k].append((hit[0], hit[2]))
                cuts[j].append((hit[1], hit[2]))
                continue
            for q in (c, d):  # 끝이 다른 선 위에 닿는다 (그 선에 이 끝을 꼭짓점으로)
                if geom.seg_dist(q, a, b) < snap:
                    cuts[k].append((along(q, a, b), q))
            for q in (a, b):
                if geom.seg_dist(q, c, d) < snap:
                    cuts[j].append((along(q, c, d), q))

    key = lambda q: (round(q[0], 2), round(q[1], 2))  # noqa: E731
    at: dict[tuple, Point] = {}
    adj: dict[tuple, set] = {}
    for cs in cuts:
        cs.sort(key=lambda x: x[0])
        for (_, p), (_, q) in zip(cs, cs[1:]):
            kp, kq = key(p), key(q)
            if kp == kq or math.dist(at.setdefault(kp, p), at.setdefault(kq, q)) < snap:
                continue
            adj.setdefault(kp, set()).add(kq)
            adj.setdefault(kq, set()).add(kp)
    stack = [k for k, ns in adj.items() if len(ns) < 2]
    while stack:  # 막다른 길을 지운다
        k = stack.pop()
        for n in adj.pop(k, set()):
            if n in adj:
                adj[n].discard(k)
                if len(adj[n]) < 2:
                    stack.append(n)
    order = {k: sorted(ns, key=lambda n: math.atan2(at[n][1] - at[k][1], at[n][0] - at[k][0])) for k, ns in adj.items()}
    seen: set[tuple] = set()
    out: list[Poly] = []
    for u in sorted(order):
        for v in order[u]:
            if (u, v) in seen:
                continue
            ring: list[Point] = []
            a, b = u, v
            while (a, b) not in seen and len(ring) <= len(order) + 1:
                seen.add((a, b))
                ring.append(at[a])
                nb = order[b]
                a, b = b, nb[(nb.index(a) - 1) % len(nb)]  # b 에서 들어온 길의 바로 앞(각도 차례) 길로 돈다
            if len(ring) >= 3 and geom.area(ring) > 1e-6:
                out.append(ring)
    return sorted(out, key=lambda poly: (round(geom.centroid(poly)[1], 1), round(geom.centroid(poly)[0], 1)))

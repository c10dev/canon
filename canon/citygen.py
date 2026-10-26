"""도시 생성기: 시드 하나로 성벽 · 성문 · 간선도로 · 구역 · 블록 · 집이 있는 도시를 만든다. LLM 을 부르지 않는다.

순서: 구역 씨앗(가운데에서 나선으로 찍고 흔든 점, Voronoi + Lloyd) → 물(바다는 한쪽 가장자리 구역들, 강은 구역 경계를 따라)
→ 성안 구역 → 강 건너는 자리(강 모서리에 수직인 선으로 양쪽 구역을 자른다) → 성벽(성안 구역 합집합의 바깥 테두리)과 성문
→ 간선도로(성문 → 가운데 광장, 성 밖은 지도 끝까지, 구역 경계 위 최단 경로) → 구역 종류(점수) → 블록 쪼개기(구역을 길 폭만큼
줄이고 긴 변에 거의 수직인 선으로 되풀이해 자른다, 가끔 골목) → 성 밖(간선 따라 성긴 집, 밭 · 숲) → 이야기 장소.
결과는 atlas.read_layout 이 내놓는 것과 같은 모양 (+ wards, gates, spots, missing, houses, numbers). 좌표는 m 로 계산하고
마지막에 0~1 로 나눈다. 단계마다 난수원을 따로 두어(f"{seed}:{단계}") 같은 MapSpec 이면 언제나 같은 도시가 나온다.

Watabou 도시 생성기의 결과물에서 보이는 흐름을 참고했지만 그 코드(GPL)는 읽지도 옮기지도 않았다. 아직 지도 화면에 붙이지 않았다.
"""
from __future__ import annotations

import heapq
import math
import random
from typing import Callable, Optional

from . import geom
from .geom import Point, Poly
from .schema import MapSpec
from .towngen import CATEGORIES

VERSION = 1
GENERATOR = "canon-city"

SIZES = {"small": 15, "medium": 30, "large": 60}  # 성안 구역 수 (강 건너는 자리 · 성문 안쪽에서 둘로 나뉜 구역은 따로 센다)
WARD_AREA = 4200.0  # 성안 구역 하나의 넓이 (m²)
OUTER_AREA = 3.2  # 성 밖 구역은 이만큼 배 넓다
GATES = {"small": (3, 3), "medium": (3, 4), "large": (4, 5)}
CROSSINGS = {"small": 1, "medium": 2, "large": 3}  # 성안에서 강을 건너는 자리
GOLDEN = math.pi * (3 - math.sqrt(5))

WARD_KINDS = {
    "plaza": "광장", "market": "시장", "temple": "신전", "noble": "귀족", "merchant": "상인", "craft": "장인",
    "harbor": "항구", "slum": "빈민", "park": "공원", "farm": "농지", "wood": "숲",
}
# 블록 쪼개기: (집 한 채 넓이 m², 골목을 낼 확률, 빈 필지 확률, 자르는 각도 흔들기 rad)
LOTS = {"merchant": (150, 0.35, 0.03, 0.12), "craft": (120, 0.4, 0.05, 0.16), "harbor": (280, 0.3, 0.05, 0.08),
        "slum": (70, 0.55, 0.1, 0.26), "noble": (560, 0.15, 0.0, 0.1)}
FIELD_SHARE = {"few": 0.35, "some": 0.65, "many": 0.9}  # 성 밖 구역 가운데 밭
FOREST_SHARE = {"few": 0.08, "some": 0.2, "many": 0.4}  # 밭이 아닌 성 밖 구역 가운데 숲 (나머지는 풀밭 농지)
CATEGORY_IDS = [c[0] for c in CATEGORIES]
NEED = {"shore": "물가가 없는 도시예요. 물을 강이나 바다로 바꿔 보세요",
        "bridge": "다리가 없어요. 물을 강으로 바꿔 보세요",
        "river": "강이 없어요. 물을 강으로 바꿔 보세요",
        "pond": "연못이 있는 공원이 없어요. 시드를 바꿔 보세요",
        "forest": "숲이 없어요. 숲을 늘리거나 시드를 바꿔 보세요",
        "field": "밭이 없어요. 밭을 늘려 보세요"}


def city(spec: MapSpec, places: list[dict]) -> dict:
    """도시 지도 (read_layout 과 같은 모양 + wards, gates, spots, missing, houses, numbers, seed, retries).
    places: [{key, name, kind}] 이 지도에 놓을 이야기 장소 (kind 는 towngen.CATEGORIES id).
    spec 가운데 size · water · fields · forest 를 쓴다 (lake 는 강으로 본다. roads 는 쓰지 않는다. 성벽은 늘 있다)."""
    if spec.kind != "city":
        raise ValueError("도시 생성기는 도시만 만들어요")
    for retry in range(4):
        out = _city(spec, places, str(spec.seed) + (f":retry{retry}" if retry else ""))
        if out is not None:
            out["retries"] = retry
            return out
    raise ValueError("도시를 만들지 못했어요. 시드를 바꿔 보세요")


# ---------- 평면 분할 ----------

class _Mesh:
    """Voronoi 칸을 꼭짓점 번호로 묶은 평면 분할. 칸은 넓이가 양수인 방향의 꼭짓점 번호 목록이고,
    이웃 칸은 같은 꼭짓점 번호를 나눠 쓴다 (0.05m 안의 점은 한 꼭짓점)."""

    def __init__(self, polys: list[Poly], w: float, h: float):
        self.w, self.h = w, h
        self.v: list[Point] = []
        self._keys: dict[tuple[int, int], list[int]] = {}
        self.cells: list[list[int]] = []
        for poly in polys:
            ids: list[int] = []
            for q in poly:
                k = self._snap(q)
                if not ids or ids[-1] != k:
                    ids.append(k)
            while len(ids) > 1 and ids[0] == ids[-1]:
                ids.pop()
            self.cells.append(ids)
        self.rebuild()

    def _snap(self, q: Point) -> int:
        kx, ky = round(q[0] * 10), round(q[1] * 10)
        best: Optional[tuple[float, int]] = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i in self._keys.get((kx + dx, ky + dy), ()):
                    d = math.dist(self.v[i], q)
                    if d < 0.05 and (best is None or d < best[0]):
                        best = (d, i)
        if best:
            return best[1]
        self.v.append(q)
        self._keys.setdefault((kx, ky), []).append(len(self.v) - 1)
        return len(self.v) - 1

    def rebuild(self) -> None:
        self.edges: dict[tuple[int, int], list[int]] = {}
        self.vcells: list[list[int]] = [[] for _ in self.v]
        self.adj: list[set[int]] = [set() for _ in self.v]
        for ci, cell in enumerate(self.cells):
            for k, a in enumerate(cell):
                b = cell[(k + 1) % len(cell)]
                self.edges.setdefault((min(a, b), max(a, b)), []).append(ci)
                self.vcells[a].append(ci)
                self.adj[a].add(b)
                self.adj[b].add(a)

    def poly(self, ci: int) -> Poly:
        return [self.v[i] for i in self.cells[ci]]

    def border(self, i: int) -> bool:
        x, y = self.v[i]
        return x < 0.01 or y < 0.01 or x > self.w - 0.01 or y > self.h - 0.01

    def neighbors(self, ci: int) -> list[int]:
        cell = self.cells[ci]
        out = []
        for k, a in enumerate(cell):
            b = cell[(k + 1) % len(cell)]
            out += [x for x in self.edges[(min(a, b), max(a, b))] if x != ci]
        return out

    def insert(self, a: int, b: int, m: int) -> None:
        """모서리 ab 를 나눠 쓰는 칸마다 a 와 b 사이에 꼭짓점 m 을 넣는다."""
        for cell in self.cells:
            n = len(cell)
            for k in range(n):
                if {cell[k], cell[(k + 1) % n]} == {a, b}:
                    cell.insert(k + 1, m)
                    break

    def split(self, ci: int, m: int, d: Point, ok: Callable[[tuple[int, int]], bool],
              ok_v: Callable[[int], bool]) -> Optional[int]:
        """칸 ci 를 꼭짓점 m 에서 d 쪽으로 곧게 자른다. 나가는 모서리가 ok 이면 나간 점을 꼭짓점으로 넣고 (이웃 칸에도),
        모서리 끝에 가까우면 그 꼭짓점(ok_v)까지 대각선으로 자른다. 두 쪽이 고르면 새 칸 번호, 안 되면 아무것도 바꾸지 않고 None."""
        cell = self.cells[ci]
        n = len(cell)
        pm = self.v[m]
        best = None
        for k in range(n):
            a, b = cell[k], cell[(k + 1) % n]
            if m in (a, b):
                continue
            hit = _ray(pm, d, self.v[a], self.v[b])
            if hit and (best is None or hit[0] < best[0]):
                best = (hit[0], hit[1], k)
        if best is None:
            return None
        _, u, k = best
        a, b = cell[k], cell[(k + 1) % n]
        if 0.18 <= u <= 0.82:
            if not ok((min(a, b), max(a, b))):
                return None
            s_pt = geom.lerp(self.v[a], self.v[b], u)
            trial = cell[:k + 1] + [-1] + cell[k + 1:]
            far = -1
        else:
            far = a if u < 0.5 else b
            i = cell.index(m)
            if far in (cell[i - 1], cell[(i + 1) % n]) or not ok_v(far):
                return None
            s_pt = self.v[far]
            trial = list(cell)
        i, j = trial.index(m), trial.index(far)
        c1, c2 = (trial[i:j + 1], trial[j:] + trial[:i + 1]) if i < j else (trial[i:] + trial[:j + 1], trial[j:i + 1])
        pt = lambda x: s_pt if x == -1 else self.v[x]  # noqa: E731
        whole = geom.area(self.poly(ci))
        if min(geom.area([pt(x) for x in c1]), geom.area([pt(x) for x in c2])) < 0.22 * whole:
            return None
        if far == -1:
            self.v.append(s_pt)
            s = len(self.v) - 1
            self.insert(a, b, s)
            c1, c2 = [s if x == -1 else x for x in c1], [s if x == -1 else x for x in c2]
        self.cells[ci] = c1
        self.cells.append(c2)
        self.rebuild()
        return len(self.cells) - 1


def _ray(p: Point, d: Point, a: Point, b: Point) -> Optional[tuple[float, float]]:
    """반직선 p + t·d (t > 0) 가 선분 ab 와 만나면 (t, ab 위 비율)."""
    ex, ey = b[0] - a[0], b[1] - a[1]
    den = d[0] * ey - d[1] * ex
    if abs(den) < 1e-12:
        return None
    qx, qy = a[0] - p[0], a[1] - p[1]
    t = (qx * ey - qy * ex) / den
    u = (qx * d[1] - qy * d[0]) / den
    return (t, u) if t > 1e-6 and 0 <= u <= 1 else None


def _line_hit(p: Point, d: Point, a: Point, b: Point) -> Optional[tuple[float, Point]]:
    """직선 p + t·d 가 선분 ab 와 만나면 (ab 위 비율, 만나는 점)."""
    ex, ey = b[0] - a[0], b[1] - a[1]
    den = d[0] * ey - d[1] * ex
    if abs(den) < 1e-12:
        return None
    qx, qy = a[0] - p[0], a[1] - p[1]
    u = (qx * d[1] - qy * d[0]) / den
    return (u, geom.lerp(a, b, u)) if 0 <= u <= 1 else None


def _unit(x: float, y: float) -> Point:
    n = math.hypot(x, y) or 1.0
    return (x / n, y / n)


def _dijkstra(adj: list[set[int]], start: int, cost: Callable[[int, int], float],
              goals: Optional[set[int]] = None) -> tuple[dict[int, float], dict[int, int], Optional[int]]:
    """cost 가 inf 인 모서리는 지나지 않는다. goals 에 닿으면 멈추고 그 꼭짓점을 돌려준다."""
    dist = {start: 0.0}
    prev: dict[int, int] = {}
    heap = [(0.0, start)]
    while heap:
        du, u = heapq.heappop(heap)
        if du > dist[u]:
            continue
        if goals is not None and u in goals:
            return dist, prev, u
        for x in sorted(adj[u]):
            c = cost(u, x)
            if c == math.inf:
                continue
            nd = du + c
            if nd < dist.get(x, math.inf):
                dist[x] = nd
                prev[x] = u
                heapq.heappush(heap, (nd, x))
    return dist, prev, None


def _trace(prev: dict[int, int], end: int) -> list[int]:
    path = [end]
    while path[-1] in prev:
        path.append(prev[path[-1]])
    return path[::-1]


# ---------- 꼬리표 달린 볼록 다각형 ----------
# 블록은 꼭짓점 목록 pts 와 변마다 꼬리표 tags (tags[i] 는 pts[i] → pts[i+1] 변이 무엇과 맞닿는지).
# ("e", 모서리) 는 구역 경계, ("a", 번호) 는 골목, ("x",) 는 길과 맞닿지 않은 변 (필지 경계 · 모퉁이).

def _cut(pts: Poly, tags: list, a: Point, b: Point, tag) -> tuple[Poly, list]:
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


def _inset(pts: Poly, tags: list, ds: list[float]) -> tuple[Poly, list]:
    """변마다 ds[i] 만큼 안으로 민다."""
    P, T = list(pts), list(tags)
    n = len(pts)
    for i in range(n):
        if ds[i] <= 0:
            continue
        a, b = pts[i], pts[(i + 1) % n]
        nx, ny = _unit(-(b[1] - a[1]), b[0] - a[0])
        P, T = _cut(P, T, (a[0] + nx * ds[i], a[1] + ny * ds[i]), (b[0] + nx * ds[i], b[1] + ny * ds[i]), tags[i])
        if not P:
            return [], []
    return P, T


def _crossings(pts: Poly, p: Point, d: Point) -> list[tuple[int, Point]]:
    """직선 p + t·d 가 볼록 다각형 변과 만나는 곳 (변 번호, 점)."""
    side = [d[0] * (q[1] - p[1]) - d[1] * (q[0] - p[0]) for q in pts]
    out = []
    n = len(pts)
    for i in range(n):
        sp, sq = side[i], side[(i + 1) % n]
        if (sp >= 0) != (sq >= 0):
            out.append((i, geom.lerp(pts[i], pts[(i + 1) % n], sp / (sp - sq))))
    return out


def _fit_rect(poly: Poly, c: Point, along: Point, w: float, d: float, margin: float) -> Optional[Poly]:
    """c 에 along 방향으로 놓은 직사각형을 poly 안에 margin 을 두고 들어갈 때까지 줄인다."""
    for _ in range(8):
        r = geom.rect(c, along, w, d)
        if all(geom.inside(q, poly) and min(geom.seg_dist(q, poly[i - 1], poly[i]) for i in range(len(poly))) >= margin for q in r):
            return r
        w, d = w * 0.85, d * 0.85
    return None


def _longest(poly: Poly) -> Point:
    i = max(range(len(poly)), key=lambda k: math.dist(poly[k - 1], poly[k]))
    return _unit(poly[i][0] - poly[i - 1][0], poly[i][1] - poly[i - 1][1])


def _scatter(r: random.Random, poly: Poly, gap: float, share: float = 1.0, avoid: Optional[list[Poly]] = None) -> list[Point]:
    """poly 안에 서로 gap 쯤 떨어진 점 (나무). share 만 남긴다."""
    x0, y0, x1, y1 = geom.bbox(poly)
    out = []
    for q in geom.poisson(r, x1 - x0, y1 - y0, gap, k=8):
        p = (q[0] + x0, q[1] + y0)
        if r.random() < share and geom.inside(p, poly) and not any(geom.inside(p, a) for a in avoid or ()):
            out.append(p)
    return out


# ---------- 도시 ----------

def _city(spec: MapSpec, places: list[dict], seed: str) -> Optional[dict]:
    rng = lambda stage: random.Random(f"{seed}:{stage}")  # noqa: E731
    n_in = SIZES[spec.size]
    r_in = math.sqrt(n_in * WARD_AREA / math.pi)  # 성안 반지름 (대략)
    h = float(round(r_in * 3.6))
    w = float(round(h * 1.3))
    base = rng("base")
    c = (w / 2 + base.uniform(-0.03, 0.03) * w, h / 2 + base.uniform(-0.03, 0.03) * h)
    aw = {"small": 7.0, "medium": 8.0, "large": 9.0}[spec.size] + base.uniform(0, 1)  # 간선 폭
    sw = base.uniform(4.5, 5.5)  # 거리 폭
    lw = base.uniform(2.4, 3.0)  # 골목 폭
    ww = base.uniform(4.5, 6.0)  # 성벽 두께
    water_kind = "river" if spec.water == "lake" else spec.water
    rw = base.uniform(*{"small": (11, 14), "medium": (13, 17), "large": (15, 21)}[spec.size])  # 강 폭

    # 1. 구역 씨앗: 가운데에서 나선 (성 밖은 점을 성기게), 흔들고 Lloyd 두 번
    sr = rng("wards")
    a0 = sr.uniform(0, 2 * math.pi)
    reach = math.hypot(w, h) / 2 + 40
    pts: list[Point] = []
    i = 0
    while True:
        cum = (i + 0.5) * WARD_AREA if i < n_in else n_in * WARD_AREA + (i - n_in + 0.5) * WARD_AREA * OUTER_AREA
        r = math.sqrt(cum / math.pi)
        if r > reach:
            break
        ang = a0 + i * GOLDEN + sr.uniform(-0.3, 0.3)
        rr = r * (1 + sr.uniform(-0.12, 0.12)) if i else sr.uniform(0, 8)
        p = (c[0] + math.cos(ang) * rr, c[1] + math.sin(ang) * rr)
        if 1 < p[0] < w - 1 and 1 < p[1] < h - 1:
            pts.append(p)
        i += 1
    box = (0.0, 0.0, w, h)
    pts = geom.lloyd(pts, box, 2)
    mesh = _Mesh(geom.voronoi(pts, box), w, h)
    if any(len(cell) < 3 for cell in mesh.cells):
        return None
    plaza = min(range(len(mesh.cells)), key=lambda ci: math.dist(geom.centroid(mesh.poly(ci)), c))

    # 2. 바다: 한쪽 가장자리에서 들어오는 구역들
    wr = rng("water")
    noise = geom.Noise(wr)
    sea: set[int] = set()
    sea_dir: Optional[Point] = None
    if water_kind == "sea":
        side = wr.randrange(4)  # 0 왼쪽, 1 위, 2 오른쪽, 3 아래
        sea_dir = [(-1.0, 0.0), (0.0, -1.0), (1.0, 0.0), (0.0, 1.0)][side]
        coast = r_in * wr.uniform(0.6, 0.85)
        pv = (-sea_dir[1], sea_dir[0])
        cand = set()
        for ci in range(len(mesh.cells)):
            q = geom.centroid(mesh.poly(ci))
            dq = (q[0] - c[0]) * sea_dir[0] + (q[1] - c[1]) * sea_dir[1]
            along = (q[0] - c[0]) * pv[0] + (q[1] - c[1]) * pv[1]
            if dq > coast + noise.fbm(along / 260, 3.7) * 0.3 * r_in:
                cand.add(ci)
        edge_of = lambda ci: any(  # noqa: E731
            (side == 0 and mesh.v[x][0] < 0.01) or (side == 1 and mesh.v[x][1] < 0.01)
            or (side == 2 and mesh.v[x][0] > w - 0.01) or (side == 3 and mesh.v[x][1] > h - 0.01) for x in mesh.cells[ci])
        stack = sorted(ci for ci in cand if edge_of(ci))
        while stack:
            ci = stack.pop()
            if ci in sea:
                continue
            sea.add(ci)
            stack += [x for x in mesh.neighbors(ci) if x in cand and x not in sea]
        land = _flood(mesh, plaza, lambda ci: ci not in sea)  # 뭍과 이어지지 않은 섬은 바다로
        sea = set(range(len(mesh.cells))) - land
        if plaza in sea or not sea:
            return None

    # 3. 성안 구역: 나선 순서로 앞의 n_in 개 (바다 빼고), 성안에 갇힌 성 밖 구역은 성안으로
    inner: set[int] = set()
    for ci in range(len(mesh.cells)):
        if len(inner) >= n_in:
            break
        if ci not in sea:
            inner.add(ci)
    if plaza not in inner or _flood(mesh, plaza, lambda ci: ci in inner) != inner:
        return None
    outside = set()
    for ci in range(len(mesh.cells)):
        if ci not in inner and ci not in outside and any(mesh.border(x) for x in mesh.cells[ci]):
            outside |= _flood(mesh, ci, lambda x: x not in inner)
    inner |= set(range(len(mesh.cells))) - outside - sea

    # 4. 강: 지도 끝에서 끝까지 구역 경계를 따라, 광장을 비켜서
    river: list[int] = []
    if water_kind == "river":
        th = wr.uniform(0, math.pi)
        u = (math.cos(th), math.sin(th))
        pv = (-u[1], u[0])
        off = wr.choice((-1, 1)) * wr.uniform(0.25, 0.5) * r_in
        far = math.hypot(w, h)
        s_pt = (c[0] + u[0] * far + pv[0] * off, c[1] + u[1] * far + pv[1] * off)
        e_off = off * wr.uniform(0.3, 1.3)
        e_pt = (c[0] - u[0] * far + pv[0] * e_off, c[1] - u[1] * far + pv[1] * e_off)
        rim = [x for x in range(len(mesh.v)) if mesh.border(x) and any(not mesh.border(y) for y in mesh.adj[x])]
        start = min(rim, key=lambda x: math.dist(mesh.v[x], s_pt))
        goal = min(rim, key=lambda x: math.dist(mesh.v[x], e_pt))
        near_plaza = set(mesh.cells[plaza])
        around = {x for ci in mesh.neighbors(plaza) for x in mesh.cells[ci]}

        def rcost(a: int, b: int) -> float:
            if b in near_plaza or (mesh.border(b) and b != goal):
                return math.inf
            pa, pb = mesh.v[a], mesh.v[b]
            mid = ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
            k = 1 + 0.8 * (noise.value(mid[0] / 90 + 11, mid[1] / 90) + 1) / 2
            ins = sum(ci in inner for ci in mesh.vcells[b])
            town = 0.6 if ins == len(mesh.vcells[b]) else (2.5 if ins else 1)  # 성안을 지나되 성벽을 따라 돌지 않게
            return math.dist(pa, pb) * k * (4 if b in around else 1) * town

        _, prev, hit = _dijkstra(mesh.adj, start, rcost, {goal})
        if hit is None:
            return None
        river = _trace(prev, goal)
    rset = set(river)
    redges = {(min(a, b), max(a, b)) for a, b in zip(river, river[1:])}

    # 5. 강 건너는 자리: 강 꼭짓점에는 한쪽 기슭으로만 모서리가 나 있어서, 건너편 구역을 그 꼭짓점에서 곧게 잘라
    # 네 갈래 꼭짓점을 만든다 (거리가 다리를 건너 이어진다). 성안에 몇 곳, 성 밖 강줄기마다 한 곳
    cross: set[int] = set()
    street_ok = lambda key: (key not in redges and len(mesh.edges.get(key, ())) == 2  # noqa: E731
                             and all(x in inner for x in mesh.edges[key]))
    solid_v = lambda x: all(ci in inner for ci in mesh.vcells[x]) and x not in rset  # noqa: E731
    wet_v = lambda x: any(ci in sea for ci in mesh.vcells[x])  # noqa: E731
    open_ok = lambda key: key not in redges and all(ci not in inner and ci not in sea for ci in mesh.edges[key])  # noqa: E731
    if river:
        cr = rng("cross")
        spacing = 2.2 * math.sqrt(WARD_AREA)

        def make(x: int, ok: Callable, ok_v: Callable) -> bool:
            """강 꼭짓점 x 의 건너편 구역을 자른다."""
            side = [y for y in mesh.adj[x] if (min(x, y), max(x, y)) not in redges]
            if len(side) != 1 or not ok((min(x, side[0]), max(x, side[0]))):
                return False
            bank = set(mesh.edges[(min(x, side[0]), max(x, side[0]))])
            far = [ci for ci in mesh.vcells[x] if ci not in bank]
            if len(far) != 1 or far[0] == plaza:
                return False
            px, py = mesh.v[x], mesh.v[side[0]]
            q0 = (2 * px[0] - py[0], 2 * px[1] - py[1])
            for q in [q0, geom.centroid(mesh.poly(far[0]))]:
                new = mesh.split(far[0], x, _unit(q[0] - px[0], q[1] - px[1]), ok, ok_v)
                if new is not None:
                    if far[0] in inner:
                        inner.add(new)
                    cross.add(x)
                    return True
            return False

        mid = [x for x in river[1:-1] if all(ci in inner for ci in mesh.vcells[x])]
        mid.sort(key=lambda x: math.dist(mesh.v[x], c) * cr.uniform(0.7, 1.3))
        to_wall = lambda key: street_ok(key) or (  # noqa: E731
            key not in redges and len(mesh.edges[key]) == 2 and sum(x in inner for x in mesh.edges[key]) == 1
            and not any(x in sea for x in mesh.edges[key]))
        for x in mid:
            if len(cross) < CROSSINGS[spec.size] and all(math.dist(mesh.v[x], mesh.v[y]) > spacing for y in cross):
                make(x, to_wall, solid_v)
        inside = [i for i, x in enumerate(river) if any(ci in inner for ci in mesh.vcells[x])]
        if inside:
            for arm in (river[:inside[0]][::-1], river[inside[-1] + 1:]):  # 성에서 나가는 쪽부터
                for x in arm[2:]:
                    if not mesh.border(x) and not wet_v(x) and make(x, open_ok, lambda y: y not in rset and not wet_v(y)):
                        break

    # 6. 성벽: 성안 구역 합집합의 바깥 테두리 (한 바퀴)
    nxt: dict[int, int] = {}
    for ci in sorted(inner):
        cell = mesh.cells[ci]
        for k, a in enumerate(cell):
            b = cell[(k + 1) % len(cell)]
            if sum(x in inner for x in mesh.edges[(min(a, b), max(a, b))]) == 1:
                if a in nxt:
                    return None
                nxt[a] = b
    loop = [next(iter(sorted(nxt)))]
    while nxt[loop[-1]] != loop[0]:
        loop.append(nxt[loop[-1]])
        if len(loop) > len(nxt):
            return None
    if len(loop) != len(nxt):
        return None
    wall = set(loop)
    wall_poly = [mesh.v[x] for x in loop]

    # 7. 성문: 성벽 꼭짓점 가운데 서로 먼 것. 성벽 꼭짓점에는 안이나 밖 한쪽으로만 모서리가 나 있어서
    # 다른 쪽 구역을 성문에서 곧게 잘라 길이 성벽을 꿰뚫고 지나가게 한다. 광장과 지도 끝에 모두 닿는 성문만 쓴다
    # (나중에 자른 칸은 모서리를 둘로 나눌 뿐이라 닿는지는 바뀌지 않는다)
    ar = rng("arteries")
    anoise = geom.Noise(ar)
    inside_v = lambda x: all(ci in inner for ci in mesh.vcells[x])  # noqa: E731
    used: set[tuple[int, int]] = set()
    goal_v = set(mesh.cells[plaza])

    def ecost(a: int, b: int) -> float:
        pa, pb = mesh.v[a], mesh.v[b]
        mid = ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
        k = 1 + 0.5 * (anoise.value(mid[0] / 70, mid[1] / 70 + 5) + 1) / 2
        return math.dist(pa, pb) * k * (0.55 if (min(a, b), max(a, b)) in used else 1)

    def icost(a: int, b: int) -> float:  # 성안: 성벽 · 강 꼭짓점을 피하고 건너는 자리로만 강을 건넌다
        key = (min(a, b), max(a, b))
        if key in redges or (b not in goal_v and not inside_v(b)) or (b in rset and b not in cross):
            return math.inf
        return ecost(a, b) + (60 if b in cross else 0)

    def ocost(a: int, b: int) -> float:  # 성 밖: 성벽 · 바닷가를 피한다
        key = (min(a, b), max(a, b))
        if key in redges or (b in rset and b not in cross) or wet_v(b) or b in wall or any(ci in inner for ci in mesh.edges[key]):
            return math.inf
        return ecost(a, b) + (60 if b in cross else 0)

    def reach(g: int) -> bool:
        return _dijkstra(mesh.adj, g, icost, goal_v)[2] is not None and any(
            mesh.border(x) for x in _dijkstra(mesh.adj, g, ocost)[0])

    gr = rng("gates")
    open_v = lambda x: x not in rset and not wet_v(x) and x not in wall  # noqa: E731
    cands = [x for x in loop if x not in rset and not wet_v(x)]
    want = gr.randint(*GATES[spec.size])
    ang = lambda x: math.atan2(mesh.v[x][1] - c[1], mesh.v[x][0] - c[0])  # noqa: E731
    adiff = lambda p, q: abs((ang(p) - ang(q) + math.pi) % (2 * math.pi) - math.pi)  # noqa: E731
    gates: list[int] = []
    gr.shuffle(cands)
    for sep in (0.75, 0.45):
        left = list(cands)
        while left and len(gates) < want:
            x = max(left, key=lambda y: min((adiff(y, g) for g in gates), default=gr.random()))
            left.remove(x)
            if gates and min(adiff(x, g) for g in gates) < sep:
                break
            ins = [ci for ci in mesh.vcells[x] if ci in inner]
            outs = [ci for ci in mesh.vcells[x] if ci not in inner]
            px = mesh.v[x]
            if len(ins) == 1 and ins[0] != plaza:  # 밖으로 나가는 모서리가 있다: 안쪽 구역을 자른다
                ci, ok, ok_v = ins[0], street_ok, solid_v
                first = [geom.centroid(mesh.poly(ci)), c]
            elif len(outs) == 1 and outs[0] not in sea:  # 안으로 들어오는 모서리가 있다: 바깥 구역을 자른다
                ci, ok, ok_v = outs[0], open_ok, open_v
                first = [(2 * px[0] - c[0], 2 * px[1] - c[1])]
            else:
                continue
            cands.remove(x)
            others = sorted((mesh.v[y] for y in mesh.cells[ci] if y != x), key=lambda q: -math.dist(q, px))
            for q in first + others:
                new = mesh.split(ci, x, _unit(q[0] - px[0], q[1] - px[1]), ok, ok_v)
                if new is not None:
                    if ci in inner:
                        inner.add(new)
                    if reach(x):
                        gates.append(x)
                    break
    if len(gates) < 3:
        return None

    # 8. 간선도로: 성문 → 광장 (성안), 성문 → 지도 끝 (성 밖). 앞선 간선과 겹치면 싸게 쳐서 모이게 한다
    arteries: list[dict] = []
    for g in gates:
        _, prev, hit = _dijkstra(mesh.adj, g, icost, goal_v)
        ipath = _trace(prev, hit)
        dist, prev, _ = _dijkstra(mesh.adj, g, ocost)
        end = min((x for x in dist if mesh.border(x)), key=lambda x: dist[x] * (1 + 2.5 * adiff(x, g) / math.pi))
        opath = _trace(prev, end)
        for path in (ipath, opath):
            used.update((min(a, b), max(a, b)) for a, b in zip(path, path[1:]))
        arteries.append({"gate": g, "path": opath[::-1] + ipath[1:], "out": opath})
    aedges = set(used)

    # 모서리 종류와 띄울 거리
    def etype(key: tuple[int, int]) -> str:
        cells = mesh.edges[key]
        if key in redges:
            return "river"
        if len(cells) == 1:
            return "border"
        if any(x in sea for x in cells):
            return "sea" if all(x in sea for x in cells) else "coast"
        k = sum(x in inner for x in cells)
        if k == 1:
            return "wall"
        if key in aedges:
            return "artery"
        return "street" if k == 2 else "hedge"

    types = {key: etype(key) for key in mesh.edges}
    clear = {"artery": aw / 2 + 0.6, "street": sw / 2 + 0.6, "river": rw / 2 + 2, "coast": ww / 2 + 3, "wall": ww / 2 + 3,
             "hedge": 1.2, "border": 0.0, "sea": 0.0}
    vclear = [max((clear[types[(min(x, y), max(x, y))]] for y in mesh.adj[x]), default=0.0) for x in range(len(mesh.v))]

    # 9. 구역 종류
    kinds = _ward_kinds(spec, mesh, inner, sea, plaza, types, gates, c, rng("kinds"), noise)

    # 10. 블록 쪼개기 · 성안 그림
    splits: dict[tuple[int, int], list[tuple[float, Point]]] = {}  # 길 모서리 위에 골목이 닿은 점
    alleys: list[dict] = []
    lots: list[dict] = []  # {poly, ward, kind}
    landmarks: list[dict] = []  # {poly, ward, kind}
    squares: list[Poly] = []
    greens: list[Poly] = []
    fields: list[Poly] = []
    ponds: list[Poly] = []
    trees: list[Point] = []
    br = rng("blocks")
    tr = rng("trees")
    wards_out = []
    for ci in range(len(mesh.cells)):
        if ci in sea:
            continue
        kind = kinds[ci]
        cell = mesh.cells[ci]
        poly = mesh.poly(ci)
        keys = [(min(a, b), max(a, b)) for a, b in zip(cell, cell[1:] + cell[:1])]
        if ci in inner:
            ds = [clear[types[k]] for k in keys]
        else:
            ds = [{"artery": aw / 2 + 24, "wall": ww / 2 + 8}.get(types[k], clear[types[k]] + 0.6) for k in keys]
        P, T = _inset(poly, [("e", k) for k in keys], ds)
        cen = geom.centroid(poly)
        for x in cell:  # 모퉁이: 꼭짓점에 모인 길 · 강 · 성벽에서 띄운다
            if not P:
                break
            q = mesh.v[x]
            nv = _unit(cen[0] - q[0], cen[1] - q[1])
            r = vclear[x] + (0.6 if ci not in inner else 0.0)
            o = (q[0] + nv[0] * r, q[1] + nv[1] * r)
            P, T = _cut(P, T, (o[0] - nv[1], o[1] + nv[0]), (o[0] + nv[1], o[1] - nv[0]), ("x",))
        wards_out.append({"kind": kind, "shape": poly, "ci": ci, "block": P})
        if not P or abs(geom.area(P)) < 40:
            continue
        if kind in ("plaza", "market"):
            squares.append(P)
            if kind == "market":
                hall = _fit_rect(P, geom.centroid(P), _longest(P), math.sqrt(abs(geom.area(P))) * 0.32,
                                 math.sqrt(abs(geom.area(P))) * 0.2, 3)
                if hall:
                    landmarks.append({"poly": hall, "ward": ci, "kind": "market"})
        elif kind == "temple":
            greens.append(P)
            s = math.sqrt(abs(geom.area(P)))
            t = _fit_rect(P, geom.centroid(P), _longest(P), s * 0.32, s * 0.62, 4)
            if t:
                landmarks.append({"poly": t, "ward": ci, "kind": "temple"})
            trees += _scatter(tr, P, 9, 0.35, [t] if t else [])
        elif kind == "park":
            greens.append(P)
            pond = None
            if tr.random() < 0.6:
                pc, s = geom.centroid(P), math.sqrt(abs(geom.area(P)))
                ang0 = tr.uniform(0, math.pi)
                ring = [(pc[0] + math.cos(t) * s * 0.2 * math.cos(ang0) - math.sin(t) * s * 0.13 * math.sin(ang0),
                         pc[1] + math.cos(t) * s * 0.2 * math.sin(ang0) + math.sin(t) * s * 0.13 * math.cos(ang0))
                        for t in (k * 2 * math.pi / 20 for k in range(20))]
                if all(geom.inside(q, P) for q in ring):
                    pond = ring if geom.area(ring) > 0 else ring[::-1]
                    ponds.append(pond)
            trees += _scatter(tr, P, 8, 0.7, [pond] if pond else [])
        elif kind in LOTS:
            target, alley_p, empty_p, jit = LOTS[kind]
            if kind == "noble":
                greens.append(P)
            for lot in _subdivide(P, T, target, alley_p, jit, br, mesh, types, splits, alleys, lw):
                if br.random() < empty_p:
                    continue
                if kind == "noble":
                    house = geom.scale(lot, 0.62)
                    if br.random() < 0.6:
                        q = lot[br.randrange(len(lot))]
                        trees.append(geom.lerp(geom.centroid(lot), q, 0.82))
                else:
                    house = lot
                lots.append({"poly": house, "ward": ci, "kind": kind})
        elif kind == "farm":
            fields += _fields(P, br, spec)
        elif kind == "wood":
            greens.append(P)
            trees += _scatter(tr, P, 7, 0.9)

    # 11. 길: 간선, 거리, 골목. 모서리 위에 골목이 닿은 점을 넣어 꼭짓점을 나눠 쓴다
    def edge_pts(a: int, b: int) -> list[Point]:
        key = (min(a, b), max(a, b))
        mids = [q for _, q in sorted(splits.get(key, []))]
        if a > b:
            mids.reverse()
        return [mesh.v[a]] + mids + [mesh.v[b]]

    roads: list[dict] = []
    river_segs = [(mesh.v[a], mesh.v[b]) for a, b in zip(river, river[1:])]
    rgrid = geom.Grid(60)
    for a, b in river_segs:
        rgrid.add(geom.bbox([a, b]), (a, b))
    wet = lambda q: any(geom.seg_dist(q, a, b) < rw / 2 + 1 for a, b in rgrid.near((q[0], q[1], q[0], q[1]), rw))  # noqa: E731
    dry = lambda a, b: not rgrid.near(geom.bbox([a, b]), rw)  # noqa: E731

    def add(pts: list[Point], width: float, kind: str = "road") -> None:
        for k2, run in _runs(pts, (wet, dry) if river_segs and kind == "road" else None):
            roads.append({"kind": k2 if kind == "road" else kind, "width": width, "pts": run})

    for art in arteries:
        line = [mesh.v[art["path"][0]]]
        for a, b in zip(art["path"], art["path"][1:]):
            line += edge_pts(a, b)[1:]
        add(line, aw)
    done_edges = set(aedges)
    for m in sorted(cross):  # 다리를 건너는 거리는 한 줄로
        ends = [y for y in sorted(mesh.adj[m]) if (min(m, y), max(m, y)) not in redges]
        if len(ends) == 2 and not any((min(m, y), max(m, y)) in done_edges for y in ends):
            add(edge_pts(ends[0], m) + edge_pts(m, ends[1])[1:], sw)
            done_edges.update((min(m, y), max(m, y)) for y in ends)
    for key in sorted(mesh.edges):
        if types[key] == "street" and key not in done_edges:
            add(edge_pts(*key), sw)
    for al in alleys:
        add([al["a"]] + [q for _, q in sorted(al["splits"])] + [al["b"]], lw)

    # 부두: 항구 구역의 바닷가 꼭짓점 가운데 길이 닿은 곳에서 바다로
    pr = rng("piers")
    road_v = {q for rd in roads for q in rd["pts"]}
    piers = 0
    for ci in sorted(ci for ci in inner if kinds[ci] == "harbor"):
        if not sea:
            break
        for x in mesh.cells[ci]:
            q = mesh.v[x]
            seas = [s for s in mesh.vcells[x] if s in sea]
            if not seas or q not in road_v or piers >= 6 or pr.random() < 0.3:
                continue
            sc = geom.centroid(mesh.poly(seas[0]))
            d = _unit(sc[0] - q[0], sc[1] - q[1])
            ln = pr.uniform(22, 38)
            end = (q[0] + d[0] * ln, q[1] + d[1] * ln)
            if not (2 < end[0] < w - 2 and 2 < end[1] < h - 2) or not any(geom.inside(end, mesh.poly(s)) for s in sea):
                continue
            roads.append({"kind": "bridge", "width": 3.5, "pts": [q, end], "pier": True})
            piers += 1

    # 0~1 좌표는 소수 6자리 (5자리면 큰 도시에서 맞닿은 집이 반올림으로 1cm 겹친다). key 는 atlas.road_graph 와 같은 반올림
    nx = lambda q: [round(q[0] / w, 6), round(q[1] / h, 6)]  # noqa: E731
    key = lambda q: (round(round(q[0] / w, 6) * w, 2), round(round(q[1] / h, 6) * h, 2))  # noqa: E731
    # 강에 막혀 떨어진 길 조각은 가장 가까운 끝끼리 잇는다. 못 이으면 버린다
    roads = _join(roads, key, wet if river_segs else None, rw, lambda pts, wd: add(pts, wd))
    if roads is None:
        return None

    # 12. 성 밖: 간선을 따라 성긴 집
    hr = rng("outskirts")
    obst = geom.Grid(40)  # (a, b, 띄울 거리)
    for rd in roads:
        for a, b in zip(rd["pts"], rd["pts"][1:]):
            obst.add(geom.bbox([a, b]), (a, b, rd["width"] / 2 + 0.3))
    for a, b in river_segs:
        obst.add(geom.bbox([a, b]), (a, b, rw / 2 + 1))
    for a, b in zip(wall_poly, wall_poly[1:] + wall_poly[:1]):
        obst.add(geom.bbox([a, b]), (a, b, ww / 2 + 1.5))
    sea_polys = [mesh.poly(ci) for ci in sorted(sea)]
    house_grid = geom.Grid(30)
    for lot in lots:
        house_grid.add(geom.bbox(lot["poly"]), lot["poly"])
    outskirts: list[dict] = []
    for art in arteries:
        line = [mesh.v[x] for x in art["out"]]
        run = 0.0
        for a, b in zip(line, line[1:]):
            seg = math.dist(a, b)
            u = _unit(b[0] - a[0], b[1] - a[1])
            t = hr.uniform(3, 8)
            while t < seg - 3:
                p = (a[0] + u[0] * t, a[1] + u[1] * t)
                for side in (-1, 1):
                    if hr.random() > 0.85 * math.exp(-(run + t) / (0.55 * r_in)):
                        continue
                    nrm = (-u[1] * side, u[0] * side)
                    hw, hd = hr.uniform(6, 10), hr.uniform(6, 9)
                    off = aw / 2 + 1.2 + hd / 2
                    hc = (p[0] + nrm[0] * off, p[1] + nrm[1] * off)
                    house = geom.rect(hc, nrm, hw, hd)
                    if not all(2 < q[0] < w - 2 and 2 < q[1] < h - 2 for q in house) or geom.inside(hc, wall_poly):
                        continue
                    if any(geom.inside(q, s) for s in sea_polys for q in house):
                        continue
                    bx = geom.bbox(house)
                    if any(geom.poly_seg_near(house, sa, sb, gap) for sa, sb, gap in obst.near(bx, 12)):
                        continue
                    if any(geom.convex_overlap(house, o, 0.8) for o in house_grid.near(bx, 2)):
                        continue
                    house_grid.add(bx, house)
                    outskirts.append({"poly": house, "ward": -1, "kind": "outskirts", "dist": run + t})
                t += hr.uniform(8, 15)
            run += seg

    # 13. 길과 겹친 성안 집은 뺀다 (모퉁이에 여러 길이 모인 곳)
    def clean(poly: Poly) -> bool:
        if len(poly) < 3 or abs(geom.area(poly)) < 18 or 2 * abs(geom.area(poly)) / sum(
                math.dist(poly[k - 1], poly[k]) for k in range(len(poly))) < 1.6:
            return False
        return not any(geom.poly_seg_near(poly, sa, sb, gap) for sa, sb, gap in obst.near(geom.bbox(poly), 12))

    lots = [lot for lot in lots if clean(lot["poly"])]
    landmarks = [lm for lm in landmarks if clean(lm["poly"])]
    houses = lots + outskirts

    # 14. 이야기 장소
    ward_of = {wd["ci"]: wd for wd in wards_out}
    spots, missing = _place_spots(places, houses, landmarks, kinds, ward_of, mesh, plaza, roads, river_segs, rw,
                                  ponds, fields, arteries, sea, c, rng("spots"))

    if len(_parts(roads, key)) != 1:  # 길이 한 덩어리인지 (atlas.road_graph 와 같은 반올림)
        return None

    buildings = [hs["poly"] for hs in houses] + [lm["poly"] for lm in landmarks]
    water_out = [_union(mesh, sea)] if sea else []
    return {
        "w": w, "h": h, "generator": GENERATOR, "version": str(VERSION), "seed": spec.seed,
        "roads": [{"kind": rd["kind"], "width": round(rd["width"], 2), "points": [nx(q) for q in rd["pts"]]} for rd in roads],
        "buildings": [[nx(q) for q in poly] for poly in buildings],
        "water": [[nx(q) for q in poly] for poly in [lp for loops in water_out for lp in loops] + ponds],
        "rivers": [{"width": round(rw, 2), "points": [nx(mesh.v[x]) for x in river]}] if river else [],
        "walls": [{"width": round(ww, 2), "points": [nx(q) for q in wall_poly + wall_poly[:1]]}],
        "gates": [nx(mesh.v[g]) for g in gates],
        "squares": [[nx(q) for q in sq] for sq in squares],
        "fields": [[nx(q) for q in poly] for poly in fields],
        "greens": [[nx(q) for q in poly] for poly in greens],
        "trees": [nx(q) for q in trees],
        "wards": [{"kind": wd["kind"], "shape": [nx(q) for q in wd["shape"]]} for wd in wards_out],
        "spots": [{"key": sp["key"], "name": sp["name"], "kind": sp["kind"], "x": nx(sp["at"])[0], "y": nx(sp["at"])[1]}
                  for sp in spots],
        "missing": missing,
        "houses": len(houses), "numbers": list(range(len(houses))),
    }


def _parts(roads: list[dict], key: Callable) -> list[list[dict]]:
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


def _join(roads: list[dict], key: Callable, wet: Optional[Callable], rw: float,
          add: Callable[[list[Point], float], None]) -> Optional[list[dict]]:
    """작은 덩어리마다 가장 큰 덩어리의 꼭짓점 가운데 가장 가까운 것과 곧은 길로 잇는다: 강을 건너면 다리 (add 가 나눈다),
    30m 안이면 강가를 따라 짧은 길. 이은 길의 끝이 물에 빠져 잘리거나 다리가 강 폭보다 훨씬 길면 잇지 않은 것으로 본다.
    이을 곳이 없는 작은 조각(길 넷 이하)은 버리고, 큰 조각이 남으면 None."""
    for _ in range(12):
        parts = _parts(roads, key)
        if len(parts) == 1:
            return roads
        main = {q for rd in parts[0] for q in rd["pts"]}
        small = parts[-1]
        best = None
        if wet:
            for rd in small:
                for p in rd["pts"]:
                    for q in main:
                        d = math.dist(p, q)
                        if (best is None or d < best[0]) and (d < 30 or (
                                d < rw + 80 and any(wet(geom.lerp(p, q, t / 8)) for t in range(1, 8)))):
                            best = (d, p, q)
        if best:  # 강을 건너면 다리, 강가를 따라 짧게 이으면 길
            n = len(roads)
            add([best[1], best[2]], max(rd["width"] for rd in small))
            ends = {key(q) for rd in roads[n:] for q in rd["pts"]}
            span = sum(geom.polyline_length(rd["pts"]) for rd in roads[n:] if rd["kind"] == "bridge")
            if not {key(best[1]), key(best[2])} <= ends or span > rw * 1.6 + 6:  # 강을 따라 걷는 다리는 안 된다
                del roads[n:]
                best = None
        if best is None:
            if len(small) > 4:
                return None
            roads[:] = [rd for rd in roads if not any(rd is x for x in small)]
    return roads if len(_parts(roads, key)) == 1 else None


def _flood(mesh: _Mesh, start: int, ok: Callable[[int], bool]) -> set[int]:
    seen = {start}
    stack = [start]
    while stack:
        for x in mesh.neighbors(stack.pop()):
            if x not in seen and ok(x):
                seen.add(x)
                stack.append(x)
    return seen


def _union(mesh: _Mesh, cells: set[int]) -> list[Poly]:
    """칸 묶음의 바깥 테두리 (고리마다 다각형)."""
    nxt: dict[int, list[int]] = {}
    for ci in sorted(cells):
        cell = mesh.cells[ci]
        for k, a in enumerate(cell):
            b = cell[(k + 1) % len(cell)]
            if sum(x in cells for x in mesh.edges[(min(a, b), max(a, b))]) == 1:
                nxt.setdefault(a, []).append(b)
    out = []
    while nxt:
        s = min(nxt)
        ring = [s]
        while True:
            b = nxt[ring[-1]].pop()
            if not nxt[ring[-1]]:
                del nxt[ring[-1]]
            if b == s or b not in nxt:
                break
            ring.append(b)
        if len(ring) >= 3:
            out.append([mesh.v[x] for x in ring])
    return out


def _runs(pts: list[Point], test: Optional[tuple[Callable, Callable]]) -> list[tuple[str, list[Point]]]:
    """선을 물 위(다리)와 뭍(길) 구간으로 나눈다. 끝이 물에 빠지는 구간은 버린다 (강가에서 멈추는 거리).
    test: (점이 물 위인가, 선분이 물에서 멀어 볼 필요가 없는가)."""
    if test is None or all(test[1](a, b) for a, b in zip(pts, pts[1:])):
        return [("road", pts)]
    wet = test[0]
    seq: list[tuple[Point, Optional[bool]]] = [(pts[0], wet(pts[0]))]
    for a, b in zip(pts, pts[1:]):
        n = 1 if test[1](a, b) else max(1, int(math.dist(a, b) / 0.7))
        prev_t, prev_w = 0.0, seq[-1][1]
        for k in range(1, n + 1):
            t = k / n
            q = geom.lerp(a, b, t) if k < n else b
            wq = wet(q)
            if wq != prev_w:
                lo, hi = prev_t, t
                for _ in range(12):
                    mid = (lo + hi) / 2
                    if wet(geom.lerp(a, b, mid)) == prev_w:
                        lo = mid
                    else:
                        hi = mid
                seq.append((geom.lerp(a, b, (lo + hi) / 2), None))  # 경계
            if k == n:
                seq.append((b, wq))
            prev_t, prev_w = t, wq
    runs: list[list] = []  # [젖음, 점들]
    cur: list[Point] = []
    state = seq[0][1]
    for q, wq in seq:
        if wq is None:
            cur.append(q)
            runs.append([state, cur])
            cur = [q]
            state = not state
        else:
            cur.append(q)
    runs.append([state, cur])
    out = []
    for i, (wq, run) in enumerate(runs):
        if len(run) < 2 or (wq and (i == 0 or i == len(runs) - 1)):
            continue
        out.append(("bridge" if wq else "road", run))
    return out


def _subdivide(P: Poly, T: list, target: float, alley_p: float, jit: float, r: random.Random, mesh: _Mesh,
               types: dict, splits: dict, alleys: list, lw: float) -> list[Poly]:
    """블록을 긴 변에 거의 수직인 선으로 되풀이해 자른다. 크면 가끔 골목 폭을 띄우고 골목 가운데 선을 alleys 에 넣는다
    (끝점은 둘레 길 · 앞 골목의 가운데 선 위 점이라 그 길에도 splits 로 넣는다)."""
    out: list[Poly] = []
    stack = [(P, T, 0)]
    while stack:
        pts, tags, depth = stack.pop()
        a_ = abs(geom.area(pts))
        if a_ < target * r.uniform(0.9, 1.7) or depth > 14:
            out.append(pts)
            continue
        i = max(range(len(pts)), key=lambda k: math.dist(pts[k], pts[(k + 1) % len(pts)]))
        pa, pb = pts[i], pts[(i + 1) % len(pts)]
        ax = _unit(pb[0] - pa[0], pb[1] - pa[1])
        th = math.pi / 2 + r.uniform(-jit, jit)
        d = (ax[0] * math.cos(th) - ax[1] * math.sin(th), ax[0] * math.sin(th) + ax[1] * math.cos(th))
        made = False
        for _ in range(3):
            m = geom.lerp(pa, pb, r.uniform(0.38, 0.62))
            if a_ > 7 * target and depth < 4 and r.random() < alley_p:
                al = _alley(pts, tags, m, d, mesh, types, alleys, lw)
                if al:
                    (lp, lt), (rp, rt), ends = al
                    if min(abs(geom.area(lp)), abs(geom.area(rp))) > 0.3 * target:
                        k = len(alleys)
                        alleys.append({"a": ends[0][1], "b": ends[1][1], "splits": []})
                        for tgt, q, u in ends:
                            (splits.setdefault(tgt[1], []) if tgt[0] == "e" else alleys[tgt[1]]["splits"]).append((u, q))
                        stack += [(lp, [("a", k) if t == "new" else t for t in lt], depth + 1),
                                  (rp, [("a", k) if t == "new" else t for t in rt], depth + 1)]
                        made = True
                        break
            b2 = (m[0] + d[0], m[1] + d[1])
            lp, lt = _cut(pts, tags, m, b2, ("x",))
            rp, rt = _cut(pts, tags, b2, m, ("x",))
            if lp and rp and min(abs(geom.area(lp)), abs(geom.area(rp))) > 0.35 * target:
                stack += [(lp, lt, depth + 1), (rp, rt, depth + 1)]
                made = True
                break
        if not made:
            out.append(pts)
    return out


def _alley(pts: Poly, tags: list, m: Point, d: Point, mesh: _Mesh, types: dict, alleys: list, lw: float):
    """m 을 지나 d 쪽으로 뻗는 골목. 두 끝이 모두 길 가운데 선에 닿으면 (왼쪽 블록, 오른쪽 블록, 끝점들)."""
    hits = _crossings(pts, m, d)
    if len(hits) != 2:
        return None
    ends = []
    for i, _ in hits:
        tag = tags[i]
        if tag[0] == "e" and types.get(tag[1]) in ("street", "artery"):
            seg = (mesh.v[tag[1][0]], mesh.v[tag[1][1]])
        elif tag[0] == "a":
            seg = (alleys[tag[1]]["a"], alleys[tag[1]]["b"])
        else:
            return None
        hit = _line_hit(m, d, *seg)
        if hit is None or not 0.04 <= hit[0] <= 0.96:
            return None
        ends.append((tag, hit[1], hit[0]))
    g = lw / 2 + 0.5
    nl = (-d[1], d[0])
    a, b = m, (m[0] + d[0], m[1] + d[1])
    left = _cut(pts, tags, (a[0] + nl[0] * g, a[1] + nl[1] * g), (b[0] + nl[0] * g, b[1] + nl[1] * g), "new")
    right = _cut(pts, tags, (b[0] - nl[0] * g, b[1] - nl[1] * g), (a[0] - nl[0] * g, a[1] - nl[1] * g), "new")
    if not left[0] or not right[0]:
        return None
    return left, right, ends


def _fields(P: Poly, r: random.Random, spec: MapSpec) -> list[Poly]:
    """성 밖 구역을 긴 변 방향 띠 밭으로. 몇 띠는 풀밭으로 비운다."""
    ax = _longest(P)
    d = (-ax[1], ax[0])
    proj = [q[0] * ax[0] + q[1] * ax[1] for q in P]
    lo, hi = min(proj), max(proj)
    out = []
    t = lo
    tags = ["x"] * len(P)
    rest, rt = P, tags
    while t < hi and rest:
        step = r.uniform(28, 55)
        t += step
        if t >= hi - 12:
            piece = rest
            rest = []
        else:
            m = (ax[0] * t, ax[1] * t)
            piece, _ = _cut(rest, rt, m, (m[0] + d[0], m[1] + d[1]), "x")
            rest, rt = _cut(rest, rt, (m[0] + d[0], m[1] + d[1]), m, "x")
        if piece and abs(geom.area(piece)) > 250 and r.random() < FIELD_SHARE[spec.fields] + 0.1:
            out.append(geom.scale(piece, 0.94))
    return out


def _ward_kinds(spec: MapSpec, mesh: _Mesh, inner: set[int], sea: set[int], plaza: int, types: dict,
                gates: list[int], c: Point, r: random.Random, noise: geom.Noise) -> dict[int, str]:
    """구역마다 종류. 성안은 점수로 (가운데 광장, 가까이 시장 · 신전, 귀족은 뭉쳐서, 물가 항구, 성벽 가 빈민, 공원),
    성 밖은 농지 · 숲."""
    kinds: dict[int, str] = {}
    cen = {ci: geom.centroid(mesh.poly(ci)) for ci in range(len(mesh.cells))}
    rad = max(math.dist(cen[ci], c) for ci in inner) or 1.0
    near = lambda ci: math.dist(cen[ci], c) / rad  # noqa: E731

    def edges_of(ci: int) -> list[str]:
        cell = mesh.cells[ci]
        return [types[(min(a, b), max(a, b))] for a, b in zip(cell, cell[1:] + cell[:1])]

    et = {ci: edges_of(ci) for ci in inner}
    kinds[plaza] = "plaza"
    for ci in sorted(inner):  # 길이 닿지 않는 구역 (강과 성벽 사이)은 집 없이 공원
        if ci != plaza and not any(t in ("street", "artery") for t in et[ci]):
            kinds[ci] = "park"
    free = lambda: [ci for ci in sorted(inner) if ci not in kinds]  # noqa: E731
    by_plaza = set(mesh.neighbors(plaza))
    n = len(inner)

    def take(kind: str, score: Callable[[int], float], count: int = 1, pool: Optional[list[int]] = None) -> list[int]:
        got = []
        for _ in range(count):
            cand = [ci for ci in (pool if pool is not None else free()) if ci not in kinds]
            if not cand:
                break
            best = max(cand, key=lambda ci: score(ci) + r.uniform(0, 0.25))
            kinds[best] = kind
            got.append(best)
        return got

    if n >= 20:
        take("market", lambda ci: (ci in by_plaza) * 1.5 + et[ci].count("artery") * 0.6 - near(ci))
    take("temple", lambda ci: (ci in by_plaza) * 1.0 - near(ci) - ("wall" in et[ci]) * 2)
    wet_kinds = ("coast", "river")
    shore = [ci for ci in free() if any(t in wet_kinds for t in et[ci])]
    if shore:
        take("harbor", lambda ci: sum(t in wet_kinds for t in et[ci]) * 0.5 + near(ci) * 0.3, max(1, round(n * 0.12)), shore)
    nobles = take("noble", lambda ci: noise.value(cen[ci][0] / 300 + 2, cen[ci][1] / 300) - ("wall" in et[ci]) * 2 - near(ci) * 0.5)
    for _ in range(max(0, round(n * 0.1) - 1)):
        pool = [x for ci in nobles for x in mesh.neighbors(ci) if x in inner and x not in kinds]
        nobles += take("noble", lambda ci: -near(ci) - ("wall" in et[ci]) * 2, 1, pool or None)
    parks = {"small": 0 if r.random() < 0.5 else 1, "medium": 1, "large": 2}[spec.size]
    take("park", lambda ci: -abs(near(ci) - 0.6) - ("artery" in et[ci]) * 0.5, parks)
    gpts = [mesh.v[g] for g in gates]
    walled = [ci for ci in free() if "wall" in et[ci]]
    take("slum", lambda ci: min(math.dist(cen[ci], q) for q in gpts) / rad, round(n * 0.15), walled)
    for ci in free():
        kinds[ci] = "merchant" if "artery" in et[ci] or near(ci) < 0.5 else "craft"
    for ci in range(len(mesh.cells)):
        if ci in inner or ci in sea:
            continue
        fr = r.random()
        if fr < FIELD_SHARE[spec.fields]:
            kinds[ci] = "farm"
        else:
            kinds[ci] = "wood" if r.random() < FOREST_SHARE[spec.forest] / (1 - FIELD_SHARE[spec.fields]) else "farm"
    return kinds


def _place_spots(places: list[dict], houses: list[dict], landmarks: list[dict], kinds: dict[int, str], ward_of: dict,
                 mesh: _Mesh, plaza: int, roads: list[dict], river_segs: list, rw: float,
                 ponds: list[Poly], fields: list[Poly], arteries: list[dict], sea: set[int],
                 c: Point, r: random.Random) -> tuple[list[dict], list[dict]]:
    """이야기 장소마다 자리. 신전 → 신전 구역, 장터 · 광장 → 광장 / 시장, 저택 → 귀족 구역, 나루 · 부두 → 항구,
    마을 밖 → 간선 끝 (지도 가장자리). 집이 필요한 종류는 집을 하나씩 차지한다."""
    spots: list[dict] = []
    missing: list[dict] = []
    used_pts: list[Point] = []
    taken: set[int] = set()
    plaza_c = geom.centroid(mesh.poly(plaza))
    market_c = next((geom.centroid(ward_of[ci]["block"]) for ci in sorted(kinds) if kinds[ci] == "market" and ward_of[ci]["block"]), None)
    centers = [geom.centroid(h["poly"]) for h in houses]
    far_i = 0

    def house(ok: Callable[[dict], bool], score: Callable[[int], float]) -> Optional[Point]:
        cand = [i for i, h in enumerate(houses) if i not in taken and ok(h)]
        spaced = [i for i in cand if all(math.dist(centers[i], u) > 30 for u in used_pts)]
        if not cand:
            return None
        i = min(spaced or cand, key=lambda k: score(k) + r.uniform(0, 1e-6))
        taken.add(i)
        return centers[i]

    def point_at(q: Point) -> Point:
        while any(math.dist(q, u) < 6 for u in used_pts):
            q = (q[0] + 9, q[1] + 3)
        return q

    gate_pts = [mesh.v[a["gate"]] for a in arteries]
    ward_kind = lambda h: kinds.get(h["ward"], "outskirts")  # noqa: E731
    for pl in places:
        kind = pl["kind"] if pl["kind"] in CATEGORY_IDS else "home"
        at: Optional[Point] = None
        reason = ""
        if kind == "center":
            at = point_at(plaza_c)
        elif kind == "market":
            at = point_at(market_c or plaza_c)
        elif kind == "well":
            q = mesh.v[mesh.cells[plaza][0]]
            at = point_at(geom.lerp(plaza_c, q, 0.35))
        elif kind == "temple":
            tm = [lm for lm in landmarks if lm["kind"] == "temple" and all(math.dist(geom.centroid(lm["poly"]), u) > 1 for u in used_pts)]
            if tm:
                at = geom.centroid(tm[0]["poly"])
            else:
                at = house(lambda h: ward_kind(h) in ("merchant", "noble"), lambda i: math.dist(centers[i], c))
        elif kind == "manor":
            at = house(lambda h: ward_kind(h) == "noble", lambda i: -abs(geom.area(houses[i]["poly"])))
        elif kind == "inn":
            at = house(lambda h: ward_kind(h) in ("merchant", "craft"), lambda i: min(math.dist(centers[i], g) for g in gate_pts))
        elif kind == "smith":
            at = house(lambda h: ward_kind(h) == "craft", lambda i: min(math.dist(centers[i], g) for g in gate_pts)) \
                or house(lambda h: ward_kind(h) in ("merchant", "slum"), lambda i: min(math.dist(centers[i], g) for g in gate_pts))
        elif kind == "mill":
            if river_segs:
                at = house(lambda h: ward_kind(h) in ("harbor", "craft", "slum"),
                           lambda i: min(geom.seg_dist(centers[i], a, b) for a, b in river_segs))
            else:
                at = house(lambda h: ward_kind(h) == "outskirts", lambda i: -houses[i].get("dist", 0)) \
                    or house(lambda h: ward_kind(h) == "craft", lambda i: -math.dist(centers[i], c))
        elif kind == "shore":
            if sea or river_segs:
                at = house(lambda h: ward_kind(h) == "harbor", lambda i: math.dist(centers[i], c))
            if at is None:
                reason = NEED["shore"]
        elif kind == "bridge":
            br = [rd for rd in roads if rd["kind"] == "bridge" and not rd.get("pier")]
            if br:
                rd = min(br, key=lambda rd: math.dist(geom.lerp(rd["pts"][0], rd["pts"][-1], 0.5), c))
                at = point_at(geom.lerp(rd["pts"][0], rd["pts"][-1], 0.5))
            else:
                reason = NEED["bridge"]
        elif kind == "river":
            if river_segs:
                a, b = min(river_segs, key=lambda s: geom.seg_dist(c, *s))
                q = geom.lerp(a, b, 0.5)
                d = _unit(c[0] - q[0], c[1] - q[1])
                at = point_at((q[0] + d[0] * (rw / 2 + 1), q[1] + d[1] * (rw / 2 + 1)))
            else:
                reason = NEED["river"]
        elif kind == "pond":
            if ponds:
                at = point_at(geom.centroid(ponds[0]))
            else:
                reason = NEED["pond"]
        elif kind == "forest":
            woods = [wd for ci, wd in sorted(ward_of.items()) if wd["kind"] in ("wood", "park") and wd["block"]]
            if woods:
                at = point_at(geom.centroid(min(woods, key=lambda wd: (wd["kind"] != "wood", math.dist(geom.centroid(wd["block"]), c)))["block"]))
            else:
                reason = NEED["forest"]
        elif kind == "field":
            if fields:
                at = point_at(geom.centroid(min(fields, key=lambda f: math.dist(geom.centroid(f), c))))
            else:
                reason = NEED["field"]
        elif kind == "far":
            art = arteries[far_i % len(arteries)]
            far_i += 1
            at = point_at(mesh.v[art["out"][-1]])
        else:  # home
            at = house(lambda h: ward_kind(h) in ("merchant", "craft", "slum", "harbor"), lambda i: r.random())
        if at is None:
            missing.append({"key": pl["key"], "name": pl["name"], "reason": reason or "놓을 집이 남지 않았어요. 크기를 키워 보세요"})
            continue
        used_pts.append(at)
        spots.append({"key": pl["key"], "name": pl["name"], "kind": kind, "at": at})
    return spots, missing

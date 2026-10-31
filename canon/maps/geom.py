"""지도 생성기가 함께 쓰는 기하 도구: 다각형, 선분, Delaunay · Voronoi, Lloyd 완화, 노이즈, Poisson disk, 격자 찾기.
지도를 모르고 LLM 을 부르지 않는다. 순수 파이썬 (의존성 없음). 같은 난수원이면 언제나 같은 결과가 나온다.

점은 (x, y) 튜플, 다각형은 점 목록(닫는 점 없음)이다. 좌표 단위는 부르는 쪽이 정한다 (마을 생성기는 m).
"""
from __future__ import annotations

import math
import random
from typing import Iterable, Optional

Point = tuple[float, float]
Poly = list[Point]


# ---------- 점 · 선분 ----------

def lerp(a: Point, b: Point, t: float) -> Point:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def seg_dist(q: Point, a: Point, b: Point) -> float:
    """점 q 와 선분 ab 사이 거리."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / (dx * dx + dy * dy or 1)))
    return math.dist(q, (a[0] + t * dx, a[1] + t * dy))


def seg_cross(a: Point, b: Point, c: Point, d: Point) -> Optional[tuple[float, float, Point]]:
    """선분 ab 와 cd 가 만나면 (ab 위 비율 t, cd 위 비율 u, 만나는 점). 평행하거나 안 만나면 None."""
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    den = rx * sy - ry * sx
    if abs(den) < 1e-12:
        return None
    qx, qy = c[0] - a[0], c[1] - a[1]
    t = (qx * sy - qy * sx) / den
    u = (qx * ry - qy * rx) / den
    if 0 <= t <= 1 and 0 <= u <= 1:
        return t, u, (a[0] + t * rx, a[1] + t * ry)
    return None


def polyline_length(pts: list[Point]) -> float:
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


# ---------- 다각형 ----------

def area(poly: Poly) -> float:
    """부호 있는 넓이 (y 가 아래로 커지는 화면 좌표에서 시계 방향이면 양수)."""
    return sum(poly[i - 1][0] * p[1] - p[0] * poly[i - 1][1] for i, p in enumerate(poly)) / 2


def centroid(poly: Poly) -> Point:
    """무게중심. 넓이가 0 에 가까우면 점들의 평균."""
    a = area(poly)
    if abs(a) < 1e-9:
        return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))
    cx = cy = 0.0
    for i, p in enumerate(poly):
        q = poly[i - 1]
        f = q[0] * p[1] - p[0] * q[1]
        cx += (q[0] + p[0]) * f
        cy += (q[1] + p[1]) * f
    return (cx / (6 * a), cy / (6 * a))


def inside(q: Point, poly: Poly) -> bool:
    """점이 다각형 안에 있는가 (짝홀 규칙)."""
    hit = False
    j = len(poly) - 1
    for i in range(len(poly)):
        (xi, yi), (xj, yj) = poly[i], poly[j]
        if (yi > q[1]) != (yj > q[1]) and q[0] < (xj - xi) * (q[1] - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def bbox(pts: Iterable[Point]) -> tuple[float, float, float, float]:
    xs, ys = zip(*pts)
    return min(xs), min(ys), max(xs), max(ys)


def scale(poly: Poly, k: float, about: Optional[Point] = None) -> Poly:
    """about(기본: 무게중심)을 기준으로 k 배. 볼록 다각형을 조금 줄여 틈을 낼 때 쓴다."""
    c = about or centroid(poly)
    return [(c[0] + (p[0] - c[0]) * k, c[1] + (p[1] - c[1]) * k) for p in poly]


def rect(c: Point, along: Point, w: float, d: float) -> Poly:
    """가운데 c, 앞뒤 방향 단위 벡터 along, 폭 w(along 에 수직), 깊이 d(along 방향)인 직사각형."""
    ax, ay = along
    nx, ny = -ay, ax
    hw, hd = w / 2, d / 2
    return [(c[0] - nx * hw - ax * hd, c[1] - ny * hw - ay * hd), (c[0] + nx * hw - ax * hd, c[1] + ny * hw - ay * hd),
            (c[0] + nx * hw + ax * hd, c[1] + ny * hw + ay * hd), (c[0] - nx * hw + ax * hd, c[1] - ny * hw + ay * hd)]


def _axes(poly: Poly) -> list[Point]:
    out = []
    for i, p in enumerate(poly):
        q = poly[i - 1]
        ex, ey = p[0] - q[0], p[1] - q[1]
        n = math.hypot(ex, ey) or 1
        out.append((-ey / n, ex / n))
    return out


def convex_overlap(a: Poly, b: Poly, gap: float = 0.0) -> bool:
    """두 볼록 다각형이 겹치거나 gap 보다 가까운가 (분리축 정리)."""
    for ax in _axes(a) + _axes(b):
        pa = [p[0] * ax[0] + p[1] * ax[1] for p in a]
        pb = [p[0] * ax[0] + p[1] * ax[1] for p in b]
        if max(pa) + gap <= min(pb) or max(pb) + gap <= min(pa):
            return False
    return True


def poly_seg_near(poly: Poly, a: Point, b: Point, gap: float) -> bool:
    """선분 ab 가 다각형 안을 지나거나 gap 보다 가까운가."""
    if inside(a, poly) or inside(b, poly):
        return True
    for i, p in enumerate(poly):
        q = poly[i - 1]
        if seg_cross(q, p, a, b) or seg_dist(p, a, b) < gap or seg_dist(a, q, p) < gap or seg_dist(b, q, p) < gap:
            return True
    return False


def clip_convex(subject: Poly, clip: Poly) -> Poly:
    """subject 를 볼록 다각형 clip 안으로 자른다 (Sutherland–Hodgman). clip 은 넓이가 양수인 방향이어야 한다."""
    out = list(subject)
    for i, c1 in enumerate(clip):
        c0 = clip[i - 1]
        side = lambda p: (c1[0] - c0[0]) * (p[1] - c0[1]) - (c1[1] - c0[1]) * (p[0] - c0[0])  # noqa: E731
        src, out = out, []
        if not src:
            break
        for j, cur in enumerate(src):
            prev = src[j - 1]
            sc, sp = side(cur), side(prev)
            if sc >= 0:
                if sp < 0:
                    out.append(lerp(prev, cur, sp / (sp - sc)))
                out.append(cur)
            elif sp >= 0:
                out.append(lerp(prev, cur, sp / (sp - sc)))
    return out


def split_convex(poly: Poly, a: Point, b: Point) -> tuple[Poly, Poly]:
    """볼록 다각형을 직선 ab 로 두 쪽 낸다. (왼쪽, 오른쪽). 한쪽이 비면 빈 목록."""
    side = lambda p: (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])  # noqa: E731
    left: Poly = []
    right: Poly = []
    for j, cur in enumerate(poly):
        prev = poly[j - 1]
        sc, sp = side(cur), side(prev)
        if (sc >= 0) != (sp >= 0):
            x = lerp(prev, cur, sp / (sp - sc))
            left.append(x)
            right.append(x)
        (left if sc >= 0 else right).append(cur)
    return (left if len(left) >= 3 else []), (right if len(right) >= 3 else [])


# ---------- Delaunay · Voronoi ----------

def _circum(a: Point, b: Point, c: Point) -> tuple[float, float, float]:
    d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-12:
        return (0.0, 0.0, math.inf)
    a2, b2, c2 = a[0] ** 2 + a[1] ** 2, b[0] ** 2 + b[1] ** 2, c[0] ** 2 + c[1] ** 2
    ux = (a2 * (b[1] - c[1]) + b2 * (c[1] - a[1]) + c2 * (a[1] - b[1])) / d
    uy = (a2 * (c[0] - b[0]) + b2 * (a[0] - c[0]) + c2 * (b[0] - a[0])) / d
    return (ux, uy, (ux - a[0]) ** 2 + (uy - a[1]) ** 2)


def delaunay(pts: list[Point]) -> list[tuple[int, int, int]]:
    """Bowyer–Watson 삼각분할. 돌려주는 것: 점 번호 세 개짜리 삼각형 목록 (입력 순서와 상관없이 같은 점이면 같은 결과)."""
    n = len(pts)
    if n < 3:
        return []
    x0, y0, x1, y1 = bbox(pts)
    m = max(x1 - x0, y1 - y0, 1.0) * 20
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    allp = list(pts) + [(cx - m, cy - m), (cx + m, cy - m), (cx, cy + m)]
    tris: dict[tuple[int, int, int], tuple[float, float, float]] = {}
    t0 = (n, n + 1, n + 2)
    tris[t0] = _circum(*(allp[i] for i in t0))
    for i in range(n):
        p = allp[i]
        bad = [t for t, (ux, uy, r2) in tris.items() if (p[0] - ux) ** 2 + (p[1] - uy) ** 2 < r2]
        edges: dict[tuple[int, int], int] = {}
        for t in bad:
            for e in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                k = (min(e), max(e))
                edges[k] = edges.get(k, 0) + 1
            del tris[t]
        for (a, b), cnt in edges.items():
            if cnt == 1:
                t = (a, b, i)
                tris[t] = _circum(allp[a], allp[b], allp[i])
    return [t for t in tris if max(t) < n]


def voronoi(pts: list[Point], box: tuple[float, float, float, float]) -> list[Poly]:
    """점마다 Voronoi 칸을 box(x0, y0, x1, y1) 안으로 잘라 돌려준다. 칸 순서는 입력 점 순서.
    바깥 점의 칸도 닫히게 멀리 네 점을 더해 삼각분할한다."""
    x0, y0, x1, y1 = box
    m = max(x1 - x0, y1 - y0) * 10
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    far = [(cx - m, cy - m), (cx + m, cy - m), (cx + m, cy + m), (cx - m, cy + m)]
    allp = list(pts) + far
    around: list[list[Point]] = [[] for _ in allp]
    for t in delaunay(allp):
        ux, uy, _ = _circum(*(allp[i] for i in t))
        for i in t:
            around[i].append((ux, uy))
    clip = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if area(clip) < 0:
        clip.reverse()
    cells = []
    for i, p in enumerate(pts):
        cs = sorted(set(around[i]), key=lambda q: math.atan2(q[1] - p[1], q[0] - p[0]))
        if area(cs) < 0:
            cs.reverse()
        cells.append(clip_convex(cs, clip) if len(cs) >= 3 else [])
    return cells


def lloyd(pts: list[Point], box: tuple[float, float, float, float], rounds: int = 1) -> list[Point]:
    """칸 무게중심으로 점을 옮겨 칸 크기를 고르게 한다."""
    for _ in range(rounds):
        pts = [centroid(c) if len(c) >= 3 else p for p, c in zip(pts, voronoi(pts, box))]
    return pts


# ---------- 노이즈 · 점 뿌리기 ----------

class Noise:
    """시드 순열표를 쓰는 2D gradient(Perlin) 노이즈. value 는 대략 -1~1, fbm 은 옥타브 합."""

    def __init__(self, rng: random.Random):
        perm = list(range(256))
        rng.shuffle(perm)
        self.p = perm * 2
        self.g = [(math.cos(a), math.sin(a)) for a in (rng.uniform(0, 2 * math.pi) for _ in range(256))]

    def value(self, x: float, y: float) -> float:
        xi, yi = math.floor(x), math.floor(y)
        xf, yf = x - xi, y - yi
        xi &= 255
        yi &= 255
        fade = lambda t: t * t * t * (t * (t * 6 - 15) + 10)  # noqa: E731
        u, v = fade(xf), fade(yf)
        p, g = self.p, self.g

        def dot(ix: int, iy: int, dx: float, dy: float) -> float:
            gx, gy = g[p[p[ix] + iy] & 255]
            return gx * dx + gy * dy

        n00, n10 = dot(xi, yi, xf, yf), dot(xi + 1, yi, xf - 1, yf)
        n01, n11 = dot(xi, yi + 1, xf, yf - 1), dot(xi + 1, yi + 1, xf - 1, yf - 1)
        a = n00 + u * (n10 - n00)
        b = n01 + u * (n11 - n01)
        return (a + v * (b - a)) * 1.414

    def fbm(self, x: float, y: float, octaves: int = 3) -> float:
        total, amp, freq, norm = 0.0, 1.0, 1.0, 0.0
        for _ in range(octaves):
            total += amp * self.value(x * freq, y * freq)
            norm += amp
            amp /= 2
            freq *= 2
        return total / norm


def poisson(rng: random.Random, w: float, h: float, r: float, k: int = 20) -> list[Point]:
    """Bridson Poisson disk: 서로 r 보다 가깝지 않게 w × h 안에 고르게 뿌린 점."""
    cell = r / math.sqrt(2)
    gw, gh = int(w / cell) + 1, int(h / cell) + 1
    grid: list[int] = [-1] * (gw * gh)
    pts: list[Point] = []
    active: list[int] = []

    def put(q: Point) -> None:
        grid[int(q[1] / cell) * gw + int(q[0] / cell)] = len(pts)
        active.append(len(pts))
        pts.append(q)

    put((rng.uniform(0, w), rng.uniform(0, h)))
    while active:
        i = active[rng.randrange(len(active))]
        base = pts[i]
        for _ in range(k):
            a, d = rng.uniform(0, 2 * math.pi), rng.uniform(r, 2 * r)
            q = (base[0] + math.cos(a) * d, base[1] + math.sin(a) * d)
            if not (0 <= q[0] < w and 0 <= q[1] < h):
                continue
            gx, gy = int(q[0] / cell), int(q[1] / cell)
            ok = True
            for yy in range(max(0, gy - 2), min(gh, gy + 3)):
                for xx in range(max(0, gx - 2), min(gw, gx + 3)):
                    j = grid[yy * gw + xx]
                    if j >= 0 and math.dist(q, pts[j]) < r:
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                put(q)
                break
        else:
            active.remove(i)
    return pts


class Grid:
    """bbox 로 물건을 칸에 넣어 두고 가까운 것만 꺼내는 격자. 겹침 검사를 빠르게 한다."""

    def __init__(self, cell: float):
        self.cell = cell
        self.cells: dict[tuple[int, int], list] = {}

    def _keys(self, box: tuple[float, float, float, float]):
        c = self.cell
        for gy in range(int(math.floor(box[1] / c)), int(math.floor(box[3] / c)) + 1):
            for gx in range(int(math.floor(box[0] / c)), int(math.floor(box[2] / c)) + 1):
                yield gx, gy

    def add(self, box: tuple[float, float, float, float], item) -> None:
        for k in self._keys(box):
            self.cells.setdefault(k, []).append(item)

    def near(self, box: tuple[float, float, float, float], pad: float = 0.0) -> list:
        """box 를 pad 만큼 넓혀 닿는 칸의 물건 (한 번씩, 넣은 순서)."""
        seen: set[int] = set()
        out = []
        for k in self._keys((box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)):
            for it in self.cells.get(k, ()):
                if id(it) not in seen:
                    seen.add(id(it))
                    out.append(it)
        return out

"""길찾기: 지도 데이터의 길망(road_graph), 길 따라 걷기와 길 밖 걷기(route), 화별로 옮겨 간 인물의 경로(add_routes). LLM 을 부르지 않는다."""
from __future__ import annotations

import heapq
import math
from typing import Optional


WALK_MPS = 1.3  # 걷는 속도 (m/초)
WALK_GRID = 200  # 길 밖을 걸을 때 지도의 긴 변을 나누는 칸 수


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

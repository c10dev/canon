"""길망: Parish–Müller 식 지역 규칙으로 길을 키운다. 지도를 모르고 LLM 을 부르지 않는다. 순수 파이썬.

길은 꼭짓점 목록(pts)이고, 갈림길은 두 길이 함께 쓰는 같은 점(튜플)이다. atlas.road_graph 가 같은 점을 같은 마디로 보므로
꼭짓점을 공유하면 길찾기 그래프가 이어진다.

지역 규칙 (Parish & Müller 2001, "Procedural Modeling of Cities" 의 local constraints 를 마을 크기로 줄인 것):
- 새 길이 다른 길을 지나면 만나는 점을 두 길 모두의 꼭짓점으로 넣는다. 키우는 길은 거기서 멈춘다.
- 새 길 끝이 기존 마디 가까이(snap)면 그 마디에 붙는다. 앞으로 join 안에 다른 길이 있으면 늘려 잇는다.
- 한 마디에서 길 사이 각도는 min_angle 보다 작지 않다. 맞지 않으면 잇지 않고 멈춘다.
- 다른 길과 나란히 clear 보다 가까워지면 멈춘다 (길 사이에 필지 자리를 남긴다).
- 다 키운 뒤 막다른 끝이 다른 길과 join 안이면 이어 고리를 만든다 (close_loops).
물 · 영역 경계 · 필지는 부르는 쪽이 blocked(a, b) 콜백으로 준다. 강은 river(q) 콜백으로 받아 마지막에 다리로 나눈다 (bridges).
같은 입력과 같은 난수원이면 언제나 같은 길망이 나온다.
"""
from __future__ import annotations

import heapq
import math
import random
from typing import Callable, Optional

from . import geom
from .geom import Point

Blocked = Callable[[Point, Point], bool]


def _ang(u: Point, v: Point) -> float:
    """두 벡터 사이 각도 (0~π)."""
    nu, nv = math.hypot(*u), math.hypot(*v)
    if nu < 1e-9 or nv < 1e-9:
        return math.pi
    return math.acos(max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / (nu * nv))))


def _closest(q: Point, a: Point, b: Point) -> Point:
    """선분 ab 위에서 q 와 가장 가까운 점."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / (dx * dx + dy * dy or 1)))
    return (a[0] + t * dx, a[1] + t * dy)


def walk(start: Point, heading: float, steps: int, step: float, noise: geom.Noise, salt: float, wiggle: float,
         ok: Callable[[Point], bool], w: float, h: float) -> list[Point]:
    """간선 모양: start 에서 heading 쪽으로 걷는 꺾은선. ok(점) 가 거짓이면 방향을 조금씩 틀어 보고, 다 막히면 멈춘다.
    영역 밖으로 나가면 가장자리에서 멈춘다. 길망에 넣는 것은 Net.add 가 한다."""
    pts = [start]
    a0 = heading
    for _ in range(steps):
        p = pts[-1]
        a = heading + noise.value(p[0] / 70 + salt, p[1] / 70 - salt) * wiggle
        for turn in (0, 0.3, -0.3, 0.6, -0.6, 0.9, -0.9, 1.2, -1.2):
            q = (p[0] + math.cos(a + turn) * step, p[1] + math.sin(a + turn) * step)
            if ok(q):
                break
        else:
            break
        heading = a + turn
        heading += (a0 - heading) * 0.15  # 원래 방향으로 조금 돌아온다
        if not (0 <= q[0] <= w and 0 <= q[1] <= h):
            t = min(((w if q[0] > w else 0) - p[0]) / (q[0] - p[0]) if not 0 <= q[0] <= w else 1,
                    ((h if q[1] > h else 0) - p[1]) / (q[1] - p[1]) if not 0 <= q[1] <= h else 1)
            pts.append(geom.lerp(p, q, t))
            break
        pts.append(q)
    return pts


class Net:
    """길 목록(list), 선분 격자, 마디 이웃표. 선분은 [a, b, 길] 목록이라 갈림길을 넣을 때 제자리에서 둘로 나눈다.
    길은 {kind, width, pts, main} 이고 선분은 언제나 길의 pts 순서(a 가 앞)로 둔다."""

    def __init__(self, w: float, h: float, snap: float = 9.0, min_angle: float = 32.0, join: float = 25.0,
                 clear: float = 16.0):
        self.w, self.h = w, h
        self.snap, self.min_angle, self.join, self.clear = snap, math.radians(min_angle), join, clear
        self.list: list[dict] = []
        self.adj: dict[Point, list[Point]] = {}
        self._reset_grids()

    def _reset_grids(self) -> None:
        self.grid = geom.Grid(30)
        self.nodes = geom.Grid(30)

    # ---------- 바탕 ----------

    def _node(self, q: Point) -> None:
        if q not in self.adj:
            self.adj[q] = []
            self.nodes.add((q[0], q[1], q[0], q[1]), [q])

    def _link(self, a: Point, b: Point, road: dict) -> None:
        self._node(a)
        self._node(b)
        self.adj[a].append(b)
        self.adj[b].append(a)
        self.grid.add(geom.bbox([a, b]), [a, b, road])

    def _push(self, road: dict, q: Point) -> None:
        """길 끝에 q 를 잇는다."""
        p = road["pts"][-1]
        road["pts"].append(q)
        self._link(p, q, road)

    def near(self, a: Point, b: Point, pad: float) -> list[list]:
        """선분 ab 의 bbox 를 pad 만큼 넓혀 닿는 선분 [a, b, 길]."""
        return [s for s in self.grid.near(geom.bbox([a, b]), pad) if s[2] is not None]

    def near_nodes(self, q: Point, r: float) -> list[Point]:
        out = []
        for it in self.nodes.near((q[0], q[1], q[0], q[1]), r):
            n = it[0]
            if n in self.adj and n not in out and math.dist(n, q) <= r:
                out.append(n)
        return out

    def split(self, seg: list, x: Point) -> None:
        """선분 seg 위의 점 x 를 그 길의 꼭짓점으로 넣는다 (갈림길이 이어지게)."""
        a, b, road = seg
        if x in (a, b):
            return
        pts = road["pts"]
        i = next(k for k in range(len(pts) - 1) if pts[k] == a and pts[k + 1] == b)
        pts.insert(i + 1, x)
        seg[1] = x
        self.adj[a].remove(b)
        self.adj[b].remove(a)
        self._node(x)
        self.adj[a].append(x)
        self.adj[x] += [a, b]
        self.adj[b].append(x)
        self.grid.add(geom.bbox([x, b]), [x, b, road])

    def _crossings(self, p: Point, q: Point, tip: bool = True) -> list[tuple[float, list, Point]]:
        """선분 pq 가 지나는 다른 선분 (p 나 q 에 붙은 선분은 빼고), p 에서 가까운 순. (비율, 선분, 점).
        p 에서 만나는 것은 빼고, tip 이 거짓이면 q 에서 만나는 것(q 가 그 선분 위에 있음)도 뺀다."""
        out = []
        for s in self.near(p, q, 1):
            if p in (s[0], s[1]) or q in (s[0], s[1]):
                continue
            x = geom.seg_cross(p, q, s[0], s[1])
            if x and math.dist(x[2], p) > 1e-6 and (tip or math.dist(x[2], q) > 1e-6):
                out.append((x[0], s, x[2]))
        out.sort(key=lambda c: c[0])
        return out

    def _fits(self, node: Point, toward: Point, others: Optional[list[Point]] = None) -> bool:
        """node 에서 toward 쪽으로 낸 길이 node 의 다른 길(또는 others)과 min_angle 이상 벌어지는가."""
        v = (toward[0] - node[0], toward[1] - node[1])
        return all(_ang(v, (n[0] - node[0], n[1] - node[1])) >= self.min_angle
                   for n in (self.adj.get(node, []) if others is None else others))

    def _clear_line(self, p: Point, q: Point, blocked: Blocked) -> bool:
        """pq 를 8m 이하 조각으로 나눠 blocked 를 부른다. 하나라도 막히면 거짓."""
        n = max(1, math.ceil(math.dist(p, q) / 8))
        pts = [geom.lerp(p, q, k / n) for k in range(n + 1)]
        return not any(blocked(a, b) for a, b in zip(pts, pts[1:]))

    def _target(self, p: Point, seg: list, x: Point) -> Optional[Point]:
        """p 에서 선분 seg 위 x 로 이을 때 실제로 붙을 점: 선분 끝 마디가 snap 의 반 안이면 그 마디. 각도가 맞지 않으면 None."""
        for e in sorted((seg[0], seg[1]), key=lambda e: math.dist(e, x)):
            if math.dist(e, x) < self.snap / 2 and self._fits(e, p) and self._fits(p, e):
                return e
        if self._fits(x, p, [seg[0], seg[1]]) and self._fits(p, x):
            return x
        return None

    def _join(self, road: dict, target: Point, seg: Optional[list]) -> None:
        if seg is not None and target not in (seg[0], seg[1]):
            self.split(seg, target)
        self._push(road, target)

    # ---------- 정해 둔 길 ----------

    def add(self, kind: str, width: float, pts: list[Point], main: bool = False) -> dict:
        """정해 둔 꺾은선(간선 · 부두)을 길로 넣는다. 다른 길을 지나는 곳은 두 길 모두에 꼭짓점을 넣는다.
        지나는 점이 그 길의 꼭짓점과 1m 안이면 그 꼭짓점을 함께 쓴다."""
        road = {"kind": kind, "width": width, "pts": [pts[0]], "main": main}
        self.list.append(road)
        on = next((s for s in self.near(pts[0], pts[0], 1) if pts[0] not in (s[0], s[1])
                   and geom.seg_dist(pts[0], s[0], s[1]) < 1e-6), None)
        if on:  # 다른 길 가운데에서 시작하면 그 길에도 꼭짓점을 넣는다
            self.split(on, pts[0])
        self._node(pts[0])
        for q in pts[1:]:
            for _, seg, x in self._crossings(road["pts"][-1], q):
                e = min((seg[0], seg[1]), key=lambda e: math.dist(e, x))
                x = e if math.dist(e, x) < 1 else x
                if x != road["pts"][-1]:
                    self.split(seg, x)
                    self._push(road, x)
            if q != road["pts"][-1]:
                self._push(road, q)
        return road

    # ---------- 키우기 ----------

    def _step(self, road: dict, a: float, step: float, blocked: Blocked, start: Point) -> tuple[str, Optional[Point], Optional[list]]:
        """길 끝에서 a 방향으로 한 걸음. ('go', 점, None) | ('join', 붙을 점, 나눌 선분 또는 None) | ('stop', None, None)."""
        pts = road["pts"]
        p = pts[-1]
        u = (math.cos(a), math.sin(a))
        q = (p[0] + u[0] * step, p[1] + u[1] * step)
        tail = set(pts[-4:])
        # 앞으로 join 안에서 다른 길을 만나면 거기까지 늘려 잇는다 (만나는 길은 어떤 것도 빼지 않는다: 꼭짓점 없이 지나가지 않게)
        ahead = (p[0] + u[0] * max(step, self.join), p[1] + u[1] * max(step, self.join))
        hits = self._crossings(p, ahead)
        if hits:
            _, seg, x = hits[0]
            t = self._target(p, seg, x)
            if (t is not None and (t == x or not self._crossings(p, t)) and self._loop_ok(p, t, {seg[0], seg[1]})
                    and self._clear_line(p, t, blocked)):
                return "join", t, (seg if t == x else None)
            if math.dist(p, x) < step + self.snap:
                return "stop", None, None
        # 가까운 마디에 붙는다
        for n in sorted(self.near_nodes(q, self.snap), key=lambda n: math.dist(n, q)):
            if n in tail or n == p:
                continue
            if (self._fits(n, p) and self._fits(p, n) and not self._crossings(p, n) and self._loop_ok(p, n, {n})
                    and self._clear_line(p, n, blocked)):
                return "join", n, None
        # 다른 길과 나란히 너무 가까우면 멈춘다 (나온 길 둘레는 처음 몇 걸음 동안 빼고 본다)
        early = math.dist(q, start) < self.clear + step
        for s in self.near(q, q, self.clear):
            if s[0] in tail and s[1] in tail:
                continue
            if early and geom.seg_dist(start, s[0], s[1]) < self.clear:
                continue
            if geom.seg_dist(q, s[0], s[1]) < self.clear:
                return "stop", None, None
        if blocked(p, q) or not self._fits(p, q):
            return "stop", None, None
        return "go", q, None

    def grow(self, seeds: list[tuple], r: random.Random, noise: geom.Noise,
             blocked: Blocked, enough: Callable[[], bool] = lambda: False, step: float = 8.0, fork: float = 0.1,
             wiggle: float = 0.35) -> list[dict]:
        """가지길을 키운다. seeds: [(시각, 시작 마디, 방향, 길이, 폭, 목표)]. 시각이 이른 것부터 한 걸음씩 번갈아 키워
        길끼리 자리를 다툰다 (Parish–Müller 의 우선순위 큐). 목표(goal(점) → 가고 싶은 방향, None 이면 없음)는 전역 목표라
        걸음마다 방향을 그쪽으로 조금 돌린다. 가지길은 걸음마다 fork 확률로 옆길을 낸다 (깊이 2 까지, 옆길은 목표가 없다).
        enough() 가 참이 되면 새 길은 내지 않고 내던 길만 마저 키운다. 돌려주는 것: 새로 낸 길."""
        queue: list[tuple[float, int]] = []
        items: list[tuple] = []

        def push(t: float, item: tuple) -> None:
            items.append(item)
            heapq.heappush(queue, (t, len(items) - 1))

        for t, p, a, length, width, goal in seeds:
            push(t, (None, p, a, length, width, 0, r.random() * 50, goal))
        made: list[dict] = []
        full = False
        while queue:
            full = full or enough()
            t, i = heapq.heappop(queue)
            road, p, a, remain, width, depth, salt, goal = items[i]
            if road is None:
                if full:  # 다 찼으면 새 길은 내지 않고 내던 길만 마저 키운다
                    continue
                if p not in self.adj or not self._fits(p, (p[0] + math.cos(a), p[1] + math.sin(a))):
                    continue
                road = {"kind": "road", "width": width, "pts": [p], "main": False}
            elif road["pts"][-1] != p:
                continue
            a2 = a + noise.value(p[0] / 60 + salt, p[1] / 60) * wiggle
            if goal is not None:
                a2 += ((goal(p) - a2 + math.pi) % (2 * math.pi) - math.pi) * 0.3
            what, q, seg = self._step(road, a2, step, blocked, road["pts"][0])
            if what == "stop":
                self._drop_stub(road)
                continue
            if len(road["pts"]) == 1:
                self.list.append(road)
                made.append(road)
            if what == "join":
                self._join(road, q, seg)
                continue
            self._push(road, q)
            remain -= step
            if remain > 0:
                push(t + 1, (road, q, a2, remain, width, depth, salt, goal))
            else:
                self._drop_stub(road)
            if not full and depth < 2 and r.random() < fork * (1 - depth * 0.4):
                side = r.choice((1, -1)) * (math.pi / 2 + r.uniform(-0.2, 0.2))
                push(t + 3, (None, q, a2 + side, max(40.0, remain * r.uniform(0.6, 1.0)), max(3.2, width - 0.5),
                             depth + 1, r.random() * 50, None))
        return [rd for rd in made if rd in self.list]

    def _drop_stub(self, road: dict) -> None:
        """막다른 짧은 길(두 걸음 이하)은 지운다. 다른 길이 붙었으면 둔다."""
        pts = road["pts"]
        if len(pts) < 2 or len(pts) > 3 or road not in self.list:
            return
        if len(self.adj[pts[-1]]) != 1 or any(len(self.adj[q]) != 2 for q in pts[1:-1]):
            return
        self.remove(road)

    def remove(self, road: dict) -> None:
        """길 하나를 지운다. 다른 길과 함께 쓰던 마디는 남는다 (다른 길이 이 길 가운데에 붙어 있지 않을 때만 부른다)."""
        pts = road["pts"]
        for a, b in zip(pts, pts[1:]):
            self.adj[a].remove(b)
            self.adj[b].remove(a)
        for q in pts[1:]:
            if not self.adj[q]:
                del self.adj[q]
        for a, b in zip(pts, pts[1:]):
            for s in self.near(a, b, 1):
                if s[2] is road:
                    s[2] = None
        self.list.remove(road)

    # ---------- 고리 ----------

    def _path_len(self, src: Point, goals: set[Point], limit: float) -> float:
        """길을 따라 src 에서 goals 가운데 하나까지 가장 짧은 거리 (limit 을 넘으면 inf)."""
        best = {src: 0.0}
        heap = [(0.0, src)]
        while heap:
            d, u = heapq.heappop(heap)
            if u in goals:
                return d
            if d > best.get(u, math.inf) or d > limit:
                continue
            for v in self.adj[u]:
                nd = d + math.dist(u, v)
                if nd < best.get(v, math.inf) and nd <= limit:
                    best[v] = nd
                    heapq.heappush(heap, (nd, v))
        return math.inf

    def _loop_ok(self, p: Point, t: Point, ends: set[Point]) -> bool:
        """p 와 t 를 이으면 쓸모 있는 고리인가: 길을 따라 p 에서 ends 까지가 곧은 거리의 3배(적어도 60m)보다 멀다."""
        limit = max(60.0, 3 * math.dist(p, t))
        return self._path_len(p, ends, limit) >= limit

    def dead_ends(self, margin: float = 10.0) -> list[Point]:
        """막다른 끝 마디 (영역 가장자리에서 margin 안의 끝은 마을 밖으로 나가는 길이라 뺀다)."""
        return [q for q, ns in self.adj.items() if len(ns) == 1
                and margin < q[0] < self.w - margin and margin < q[1] < self.h - margin]

    def close_loops(self, blocked: Blocked, skip: Callable[[Point], bool] = lambda q: False) -> int:
        """막다른 끝을 join 안의 다른 길에 이어 고리를 만든다. 길을 따라가면 이미 가까운 곳(가까운 거리의 3배 안)은 잇지 않는다.
        돌려주는 것: 이은 수."""
        made = 0
        for d in sorted(self.dead_ends()):
            if skip(d) or len(self.adj.get(d, ())) != 1:
                continue
            prev = self.adj[d][0]
            road = next((s[2] for s in self.near(d, prev, 1) if {s[0], s[1]} == {d, prev}), None)
            if road is None or road["kind"] != "road" or d not in (road["pts"][0], road["pts"][-1]):
                continue
            heading = (d[0] - prev[0], d[1] - prev[1])
            cands = []
            for s in self.near(d, d, self.join):
                if d in (s[0], s[1]) or s[2]["kind"] != "road":
                    continue
                x = _closest(d, s[0], s[1])
                dist = math.dist(d, x)
                if dist < 1 or dist > self.join or _ang(heading, (x[0] - d[0], x[1] - d[1])) > math.radians(100):
                    continue
                cands.append((dist, x, s))
            for dist, x, s in sorted(cands, key=lambda c: c[0]):
                t = self._target(d, s, x)
                if t is None:
                    continue
                if not self._loop_ok(d, t, {s[0], s[1]}):
                    continue
                if self._crossings(d, t, False) or not self._clear_line(d, t, blocked):
                    continue
                if t not in (s[0], s[1]):
                    self.split(s, t)
                if road["pts"][-1] == d:
                    self._push(road, t)
                else:
                    road["pts"].insert(0, t)
                    self._link(t, d, road)
                made += 1
                break
        return made

    # ---------- 마무리 ----------

    def bridges(self, river: Callable[[Point], bool]) -> None:
        """길을 뭍 · 강 구간으로 나눈다. 강 구간(다리)은 양쪽 뭍 점을 끝점으로 갖는다. 강에서 끝나는 꼬리는 버린다.
        kind 가 road 인 길만 본다. 선분 격자와 이웃표를 다시 만든다."""
        out = []
        for road in self.list:
            pts = road["pts"]
            wet = [river(q) for q in pts] if road["kind"] == "road" else [False] * len(pts)
            if not any(wet):
                out.append(road)
                continue
            i = 0
            while i < len(pts):
                j = i
                while j + 1 < len(pts) and wet[j + 1] == wet[i]:
                    j += 1
                if not wet[i]:
                    run, kind = pts[i:j + 1], "road"
                elif i > 0 and j + 1 < len(pts):
                    run, kind = pts[i - 1:j + 2], "bridge"
                else:
                    break  # 강에서 끝나거나 강에서 시작하면 그 뒤는 버린다
                if len(run) >= 2:
                    out.append({**road, "kind": kind, "width": road["width"] if kind == "road" else 6, "pts": run})
                i = j + 1
        self.list = out
        self.adj = {}
        self._reset_grids()
        for road in self.list:
            for a, b in zip(road["pts"], road["pts"][1:]):
                self._link(a, b, road)

    def loops(self) -> int:
        """고리 수 (선분 수 − 마디 수 + 덩어리 수)."""
        seen: set[Point] = set()
        parts = 0
        for s in self.adj:
            if s in seen:
                continue
            parts += 1
            stack = [s]
            while stack:
                u = stack.pop()
                if u not in seen:
                    seen.add(u)
                    stack.extend(self.adj[u])
        edges = sum(len(ns) for ns in self.adj.values()) // 2
        return edges - len(self.adj) + parts

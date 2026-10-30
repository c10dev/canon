"""장면 연출: 박자 사이 이동 경로 (docs/stage/specs/10-path.md).

박자 사이에 자리를 옮기는 인물이 가구 · 차를 뚫지 않게 돌아가는 꺾은선을 찾는다. 장애물은 3D 가구 상자(stage3d.furniture.solids)의
바닥 사각형을 몸 반지름만큼 부풀린 것이고, 그 꼭짓점으로 가시성 그래프를 만들어 가장 짧은 길을 고른다(shapely · networkx).
결과는 화면 그림(평면도 · 3D 보간)에만 쓴다. 검수 지적이 아니다. LLM 호출 없음.
"""
from __future__ import annotations

import math
from typing import Optional

import networkx as nx
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union
from shapely.prepared import prep

from . import stage
from .schema import StageRoom, StageScene

MOVED = 0.05     # 이보다 짧게 옮기면 이동으로 보지 않는다 (m, 평면도 화살표와 같다)
HEAD = 1.5       # 바닥에서 이 높이보다 위에서 시작하는 상자는 그 아래로 지나간다고 본다 (m)
CORNER = 0.03    # 꺾는 점을 부풀린 장애물 모서리보다 이만큼 더 바깥에 둔다 (m)
EPS = 1e-6


def _skip(room: StageRoom, refs: set[str]) -> set[str]:
    """이번 이동에서 장애물로 보지 않을 기준점: 머문 기준점과 그 조상 · 자식, 그 기준점을 품은 차."""
    by = {a.id: a for a in room.anchors}
    out: set[str] = set()
    for r in refs:
        a = by.get(r)
        if a is None:
            continue
        out.add(r)
        seen, p = {r}, a.parent
        while p in by and p not in seen:  # 조상
            out.add(p)
            seen.add(p)
            p = by[p].parent
        out.update(x.id for x in stage.children(room, r))
        v = stage.container(a, room.anchors)
        if v is not None:
            out.add(v.id)
    return out


def _blocks(room: StageRoom, solids) -> dict[str, object]:
    """기준점 id → 바닥 다각형 (단단한 상자 가운데 머리 아래에서 시작하는 것만). 부풀리기는 route 가 한다."""
    out: dict[str, list] = {}
    for s in solids:
        x0, y0, z0, x1, y1, z1 = s.box
        if not s.solid or z0 >= HEAD or x1 - x0 < EPS or y1 - y0 < EPS:
            continue
        out.setdefault(s.anchor, []).append(box(x0, y0, x1, y1))
    return {k: unary_union(v) for k, v in out.items()}


def _corners(geom) -> list[tuple[float, float]]:
    """다각형(여럿일 수 있음)의 바깥 · 구멍 꼭짓점."""
    polys = getattr(geom, "geoms", [geom])
    pts = []
    for g in polys:
        if g.is_empty or not hasattr(g, "exterior"):
            continue
        for ring in [g.exterior, *g.interiors]:
            pts.extend(ring.coords[:-1])
    return pts


def route(a: tuple[float, float], b: tuple[float, float], blocks: list, w: float, h: float) -> tuple[list[tuple[float, float]], bool]:
    """a → b 꺾은선과 막힘. 곧게 갈 수 있으면 [a, b]. 길이 없으면 [a, b] 와 True.
    blocks 는 장애물 바닥 다각형, w · h 는 방 크기 (몸 반지름 안쪽만 다닌다)."""
    pa, pb = Point(a), Point(b)
    obs = []
    for g in blocks:
        # 몸 반지름만큼 부풀린다. 시작 · 끝이 그보다 가까우면(자리 계산이 가구 곁에 바짝 붙였거나 벽에 밀린 경우) 그 거리까지만,
        # 가구 안이면 이번 이동에서 뺀다
        r = min(stage.BODY, g.distance(pa) - CORNER, g.distance(pb) - CORNER)
        if r > 0:
            obs.append(g.buffer(r, join_style="mitre"))
    hall = box(stage.BODY - EPS, stage.BODY - EPS, w - stage.BODY + EPS, h - stage.BODY + EPS)
    free = hall.difference(unary_union(obs)) if obs else hall
    ok = prep(free.buffer(EPS))
    if ok.covers(LineString([a, b])):
        return [a, b], False
    nodes = [a, b] + [p for p in _corners(unary_union([g.buffer(CORNER, join_style="mitre") for g in obs])) if ok.covers(Point(p))]
    g = nx.Graph()
    for i, p in enumerate(nodes):
        for j in range(i + 1, len(nodes)):
            q = nodes[j]
            if ok.covers(LineString([p, q])):
                g.add_edge(i, j, weight=math.dist(p, q))
    try:
        idx = nx.shortest_path(g, 0, 1, weight="weight")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return [a, b], True
    return [nodes[i] for i in idx], False


def _room_spec(room: StageRoom):
    from .stage3d import rooms as room_reg  # stage3d 가 stage 를 읽으므로 늦게 읽는다
    return room_reg.load().get(room.template) if room.template else None


def paths(scene: StageScene, room: StageRoom, spots: Optional[list[dict]] = None) -> list[dict]:
    """박자마다 돌아가는 이동: [k] = {인물 id: {"via": [[x, y], ...], "blocked": bool}} (0 은 시작 상태라 늘 빈칸).
    곧게 가는 이동은 싣지 않는다. spots 는 stage.layouts 결과 (없으면 계산)."""
    from .stage3d import furniture
    room = stage.resolve(room)
    spots = spots if spots is not None else stage.layouts(room, scene)
    blocks = _blocks(room, furniture.solids(room, _room_spec(room)))
    out: list[dict] = [{}]
    for k in range(1, len(spots)):
        before, now = stage.state_at(scene, k - 1), stage.state_at(scene, k)
        row = {}
        for who, b in spots[k].items():
            a = spots[k - 1].get(who)
            if a is None or math.dist(a, b) < MOVED:
                continue
            refs = {s.at.ref for s in (before.get(who), now.get(who)) if s and s.at and not s.at.ref.startswith("@")}
            skip = _skip(room, refs)
            via, blocked = route(a, b, [g for aid, g in blocks.items() if aid not in skip], room.w, room.h)
            if blocked or len(via) > 2:
                row[who] = {"via": [[round(x, 3), round(y, 3)] for x, y in via], "blocked": blocked}
        out.append(row)
    return out

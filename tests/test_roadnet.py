"""길망 테스트: canon/maps/gen/roadnet.py 의 지역 규칙과, 마을 생성기가 만든 길이 고리를 갖고 한 덩어리인지.
실행: python -m pytest tests/test_roadnet.py"""
import math
import os
import random
import tempfile

os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())
os.environ.setdefault("CANON_LLM", "mock")

import pytest  # noqa: E402

from canon import atlas  # noqa: E402
from canon.maps import geom  # noqa: E402
from canon.maps.gen import roadnet, towngen  # noqa: E402
from canon.schema import MapSpec  # noqa: E402

COMBOS = [(size, water, "cross") for size in ("small", "medium") for water in ("none", "river", "lake", "sea")] + \
         [("medium", "none", "square"), ("medium", "river", "line"), ("large", "river", "cross")]


def _never(a, b):
    return False


def _segments(lo: dict) -> list[tuple[tuple, tuple]]:
    """지도의 길 선분 (m 좌표, atlas.road_graph 와 같이 0.01 로 반올림)."""
    k = lambda q: (round(q[0] * lo["w"], 2), round(q[1] * lo["h"], 2))  # noqa: E731
    return [(k(a), k(b)) for r in lo["roads"] for a, b in zip(r["points"], r["points"][1:]) if k(a) != k(b)]


# ---------- 지역 규칙 ----------

def test_add_puts_crossing_on_both_roads():
    net = roadnet.Net(200, 200)
    a = net.add("road", 6, [(0, 50), (100, 50)], main=True)
    b = net.add("road", 6, [(50, 0), (50, 100)], main=True)
    assert (50.0, 50.0) in a["pts"] and (50.0, 50.0) in b["pts"]
    assert len(net.adj[(50.0, 50.0)]) == 4 and net.loops() == 0


def test_branch_joins_road_ahead_and_keeps_angle():
    net = roadnet.Net(300, 300)
    net.add("road", 6, [(0, 100), (100, 100), (200, 100), (300, 100)], main=True)
    net.add("road", 6, [(0, 150), (300, 150)], main=True)
    net.add("road", 6, [(10, 100), (10, 150)], main=True)
    net.add("road", 6, [(290, 100), (290, 150)], main=True)
    noise = geom.Noise(random.Random(1))
    # 위 길에서 아래 길로 곧게: 50m 사이를 지나 아래 길에 꼭짓점을 넣고 붙는다
    made = net.grow([(0, (100.0, 100.0), math.pi / 2, 200, 4, None)], random.Random(2), noise, _never, fork=0, wiggle=0)
    assert len(made) == 1 and made[0]["pts"][-1][1] == 150
    assert made[0]["pts"][-1] in net.adj and len(net.adj[made[0]["pts"][-1]]) == 3
    assert net.loops() == 2
    # 길과 거의 나란히(10°) 내는 길은 각도 규칙에 걸려 내지 않는다
    assert net.grow([(0, (200.0, 100.0), math.radians(10), 100, 4, None)], random.Random(3), noise, _never, fork=0, wiggle=0) == []


def test_branch_snaps_to_nearby_node():
    net = roadnet.Net(300, 300)
    net.add("road", 6, [(0, 100), (146, 100), (300, 100)], main=True)
    net.add("road", 6, [(0, 180), (150, 180), (300, 180)], main=True)
    net.add("road", 6, [(5, 100), (5, 180)], main=True)
    # (146, 100) 에서 74m 올라간 끝은 (150, 180) 마디에서 snap 안이라 그 마디에 붙는다
    road = {"kind": "road", "width": 4, "pts": [(146, 100)], "main": False}
    assert net._step(road, math.pi / 2, 74, _never, (146, 100)) == ("join", (150, 180), None)


def test_close_loops_joins_dead_end_within_reach():
    net = roadnet.Net(300, 300)
    net.add("road", 6, [(0, 50), (100, 50), (200, 50), (300, 50)], main=True)
    side = net.add("road", 4, [(60, 50), (60, 70), (100, 70), (140, 70)])
    assert (140, 70) in net.dead_ends() and net.loops() == 0
    assert net.close_loops(_never) == 1
    assert side["pts"][-1] == (140.0, 50.0) and net.loops() == 1 and not net.dead_ends()
    # 길을 따라가도 가까운 곳(짧은 고리)은 잇지 않는다
    net2 = roadnet.Net(300, 300)
    net2.add("road", 6, [(0, 50), (300, 50)], main=True)
    net2.add("road", 4, [(100, 50), (100, 70), (110, 70)])
    assert net2.close_loops(_never) == 0


def test_bridges_split_road_over_river():
    net = roadnet.Net(200, 200)
    net.add("road", 6, [(0, 100), (40, 100), (90, 100), (100, 100), (110, 100), (160, 100), (200, 100)], main=True)
    net.bridges(lambda q: 95 <= q[0] <= 115)
    assert [(r["kind"], r["pts"][0], r["pts"][-1]) for r in net.list] == [
        ("road", (0, 100), (90, 100)), ("bridge", (90, 100), (160, 100)), ("road", (160, 100), (200, 100))]


# ---------- 마을 길망 ----------

@pytest.mark.parametrize("size,water,roads", COMBOS)
def test_village_road_network(size, water, roads):
    lo = towngen.village(MapSpec(seed=3, size=size, water=water, roads=roads), [])
    segs = _segments(lo)
    nodes = {q for s in segs for q in s}
    adj: dict[tuple, set] = {q: set() for q in nodes}
    for a, b in segs:
        adj[a].add(b)
        adj[b].add(a)
    # 한 덩어리
    g = atlas.road_graph(lo)
    assert len(g["nodes"]) == len(nodes)
    # 고리가 있다 (한길은 가지길로만 고리를 만들어 없을 수도 있다)
    edges = sum(len(v) for v in adj.values()) // 2
    loops = edges - len(nodes) + 1
    assert loops > 0 or roads == "line"
    # 한 마디에서 길 사이 각도는 30° 이상
    for q, ns in adj.items():
        ns = sorted(ns)
        for i, a in enumerate(ns):
            for b in ns[i + 1:]:
                assert roadnet._ang((a[0] - q[0], a[1] - q[1]), (b[0] - q[0], b[1] - q[1])) >= math.radians(30), (q, a, b)
    # 꼭짓점 없이 서로 지나가는 길이 없다
    grid = geom.Grid(30)
    for s in segs:
        grid.add(geom.bbox(s), s)
    for s in segs:
        for o in grid.near(geom.bbox(s), 0.5):
            if o is s or set(s) & set(o):
                continue
            assert geom.seg_cross(s[0], s[1], o[0], o[1]) is None, (s, o)

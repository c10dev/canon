"""마을 생성기: 시드 하나로 길 · 필지 · 집 · 밭 · 물 · 나무가 있는 마을을 만든다. LLM 을 부르지 않는다.

순서: 바탕(물) → 간선(가장자리에서 들어와 마을 가운데서 만나는 길) → 가지길 → 길가 필지와 집 → 이야기 장소 자리 → 밭 · 풀밭 → 나무.
결과는 atlas.read_layout 이 내놓는 것과 같은 모양이라 지도 그리기 · 길찾기 · 인물 동선을 그대로 쓴다.
좌표는 m 로 계산하고 마지막에 0~1 로 나눈다. 단계마다 난수원을 따로 두어(f"{seed}:{단계}") 같은 MapSpec 이면 언제나 같은 마을이 나온다.

장소 종류는 이름 · 설명의 단어로 고른다 (classify, CATEGORIES). 도시 · 왕국 생성기는 다음 단계다.
"""
from __future__ import annotations

import math
import random
from typing import Optional

from . import geom
from .geom import Point, Poly
from .schema import MapSpec

VERSION = 3  # 2: 바닷가 마을을 해안에 붙이고 바다로 가는 길 · 부두, 물가 장소를 물가에. 3: 숲 덩어리 · 생울타리 · 과수원, 길로 자른 큰 밭, 등대는 바다에만
GENERATOR = "canon-village"

SIZES = {"small": (25, 320), "medium": (60, 440), "large": (120, 600)}  # 목표 집 수, 영역 세로(m)
OPTIONS = {
    "size": {"small": "작음 (집 20~30채)", "medium": "보통 (30~60채)", "large": "큼 (50~110채)"},  # 시드 5개씩 재 본 범위. 한길은 적은 쪽
    "roads": {"line": "한길", "cross": "교차로", "square": "광장"},
    "water": {"none": "없음", "river": "강", "lake": "호수", "sea": "바다"},
    "fields": {"few": "적음", "some": "보통", "many": "많음"},
    "forest": {"few": "적음", "some": "보통", "many": "많음"},
}
FIELD_SHARE = {"few": 0.35, "some": 0.65, "many": 0.9}
FOREST_LEVEL = {"few": 0.32, "some": 0.18, "many": 0.04}  # 노이즈가 이 값을 넘는 곳이 숲

# (종류 id, 화면 이름, 이름 · 설명에서 찾을 단어). 가장 긴 단어가 이긴다 (촌장 > 촌)
CATEGORIES: list[tuple[str, str, tuple[str, ...]]] = [
    ("center", "마을 가운데", ("마을", "촌", "동네", "부락", "읍내", "마을회관")),
    ("market", "장터 · 광장", ("장터", "시장", "광장", "장마당")),
    ("well", "우물", ("우물", "샘터")),
    ("temple", "신전 · 사당", ("신전", "사당", "교회", "성당", "예배당", "사원", "사찰", "신당", "수도원", "암자", "서낭당")),
    ("inn", "여관 · 주막", ("여관", "주막", "객잔", "여인숙", "주점", "술집", "선술집", "객주", "숙소")),
    ("smith", "대장간 · 공방", ("대장간", "공방", "마구간", "대장장이", "작업장")),
    ("mill", "방앗간", ("방앗간", "물레방아", "풍차", "제분소")),
    ("manor", "저택 · 관아", ("저택", "영주", "관아", "장원", "대감", "촌장", "이장", "지주", "별장")),
    ("home", "집 · 가게", ("집", "가게", "상점", "빵집", "약방", "의원", "학당", "서당", "학교", "댁")),
    ("shore", "나루 · 부두", ("나루", "부두", "포구", "선착장", "항구", "등대", "해변", "바닷가", "어시장", "수산시장", "어판장", "방파제", "갯벌", "염전")),
    ("bridge", "다리", ("다리", "징검다리")),
    ("river", "강가", ("강", "강가", "개울", "냇가", "시냇가", "하천", "시내")),
    ("pond", "호수 · 연못", ("호수", "연못", "늪", "저수지")),
    ("forest", "숲", ("숲", "숲속", "숲길", "수풀")),
    ("field", "밭 · 농장", ("밭", "논", "들판", "농장", "과수원", "목장")),
    ("far", "마을 밖", ("왕국", "제국", "도시", "수도", "산맥", "대륙", "국경", "왕궁", "황궁", "성", "산", "고개", "바다")),
]
CATEGORY_IDS = [c[0] for c in CATEGORIES]
NEED_WATER = {"shore": "물가가 없는 마을이에요. 물을 강 · 호수 · 바다로 바꿔 보세요",
              "bridge": "다리가 없어요. 물을 강으로 바꿔 보세요",
              "river": "강이 없어요. 물을 강으로 바꿔 보세요",
              "pond": "호수가 없어요. 물을 호수로 바꿔 보세요"}


def classify(name: str, description: str = "") -> tuple[str, str]:
    """장소 종류 (종류 id, 찾은 단어). 이름에서 먼저 찾고 없으면 설명에서. 못 찾으면 ('home', '')."""
    for text in (name, description):
        best: Optional[tuple[int, int, str, str]] = None
        for order, (cid, _, words) in enumerate(CATEGORIES):
            for w in words:
                if w in text and (best is None or (len(w), -order) > (best[0], best[1])):
                    best = (len(w), -order, cid, w)
        if best:
            return best[2], best[3]
    return "home", ""


def default_put(kind: str) -> bool:
    return kind != "far"


RIVER_SHORE = ("나루", "선착장")  # 물가 종류 가운데 강에 어울리는 단어 (나머지는 바다)
LIGHT_WORDS = ("등대", "방파제")  # 물가 종류 가운데 해안 끝(곶)에 서는 것
BEACH_WORDS = ("해변", "바닷가", "갯벌", "염전")  # 물가 종류 가운데 물가 자체 (필지가 아님). 나머지 물가 종류는 부두 옆


def water_for(rows: list[dict]) -> str:
    """놓을 장소가 물을 바라면 그 물 (sea | river | lake), 아니면 none. 지도 만들기 물 칸의 기본값.
    rows: [{kind, word, put}]. 여러 물을 바라면 많이 바라는 쪽, 같으면 바다 > 강 > 호수."""
    votes = {"sea": 0, "river": 0, "lake": 0}
    for r in rows:
        if not r.get("put"):
            continue
        if r["kind"] == "shore":
            votes["river" if r.get("word") in RIVER_SHORE else "sea"] += 1
        elif r["kind"] in ("bridge", "river"):
            votes["river"] += 1
        elif r["kind"] == "pond":
            votes["lake"] += 1
    best = max(votes, key=lambda k: (votes[k], -list(votes).index(k)))
    return best if votes[best] else "none"


# ---------- 물 ----------

class _Water:
    """물 래스터: 고인 물(호수 · 바다)과 강을 3m 칸으로 칠해 두고 margin 안에 물이 있는지 빨리 본다."""
    RES = 3.0

    def __init__(self, w: float, h: float):
        self.w, self.h = w, h
        self.cols, self.rows = int(w / self.RES) + 2, int(h / self.RES) + 2
        self.still = bytearray(self.cols * self.rows)
        self.river = bytearray(self.cols * self.rows)
        self.polys: list[Poly] = []
        self.kinds: list[str] = []  # polys 마다 lake | sea
        self.rivers: list[dict] = []

    def add_poly(self, poly: Poly, kind: str) -> None:
        self.polys.append(poly)
        self.kinds.append(kind)
        r = self.RES
        for row in range(self.rows):
            y = (row + 0.5) * r
            xs = []
            for i, (x1, y1) in enumerate(poly):
                x0, y0 = poly[i - 1]
                if (y0 > y) != (y1 > y):
                    xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
            xs.sort()
            for a, b in zip(xs[::2], xs[1::2]):
                for col in range(max(0, int(a / r)), min(self.cols, int(b / r) + 1)):
                    if a <= (col + 0.5) * r <= b:
                        self.still[row * self.cols + col] = 1

    def add_river(self, pts: list[Point], width: float) -> None:
        self.rivers.append({"width": width, "points": pts})
        r, hw = self.RES, width / 2
        for a, b in zip(pts, pts[1:]):
            x0, y0, x1, y1 = geom.bbox([a, b])
            for row in range(max(0, int((y0 - hw) / r)), min(self.rows, int((y1 + hw) / r) + 1)):
                for col in range(max(0, int((x0 - hw) / r)), min(self.cols, int((x1 + hw) / r) + 1)):
                    if geom.seg_dist(((col + 0.5) * r, (row + 0.5) * r), a, b) <= hw:
                        self.river[row * self.cols + col] = 1

    def _hit(self, grid: bytearray, q: Point, margin: float) -> bool:
        r = self.RES
        k = int(math.ceil(margin / r))
        c0, r0 = int(q[0] / r), int(q[1] / r)
        for row in range(r0 - k, r0 + k + 1):
            if 0 <= row < self.rows:
                for col in range(c0 - k, c0 + k + 1):
                    if 0 <= col < self.cols and grid[row * self.cols + col]:
                        return True
        return False

    def wet(self, q: Point, margin: float = 0.0, river: bool = True) -> bool:
        return self._hit(self.still, q, margin) or (river and self._hit(self.river, q, margin))

    def on_river(self, q: Point) -> bool:
        return self._hit(self.river, q, 0)

    def edge(self) -> list[Point]:
        """물가 점: 호수 · 바다 테두리와 강 선의 점 가운데 지도 안에 있는 것 (바다를 지도 밖으로 닫은 꼭짓점은 뺀다)."""
        pts = [q for poly in self.polys for q in poly] + [q for rv in self.rivers for q in rv["points"]]
        return [q for q in pts if 0 < q[0] < self.w and 0 < q[1] < self.h]

    def inland(self, q: Point, toward: Point, margin: float = 1.5) -> Point:
        """물가 점 q 에서 toward 쪽으로 1m 씩 옮겨 margin 안에 물이 없는 첫 점."""
        d = math.dist(q, toward) or 1
        u = ((toward[0] - q[0]) / d, (toward[1] - q[1]) / d)
        for k in range(int(d)):
            p = (q[0] + u[0] * k, q[1] + u[1] * k)
            if not self.wet(p, margin):
                return p
        return toward


def _make_water(kind: str, rng: random.Random, noise: geom.Noise, w: float, h: float, e: float, c: Point) -> tuple[_Water, Optional[float]]:
    """물을 만든다. 바다면 바다 쪽 방향(라디안)도 돌려준다."""
    water = _Water(w, h)
    sea_dir = None
    if kind == "river":
        width = rng.uniform(10, 16)
        flip = rng.random() < 0.5  # 세로로 흐르는 강
        span, cross = (h, w) if flip else (w, h)
        mid = (c[0] if flip else c[1]) + rng.choice((-1, 1)) * rng.uniform(width + 20, 0.22 * e)
        tilt = rng.uniform(-0.15, 0.15) * cross
        pts = []
        for i in range(int((span + 40) / 8) + 1):
            t = -20 + i * 8
            off = mid + tilt * (t / span - 0.5) + noise.fbm(t / 180, 7.3) * 0.12 * e
            pts.append((off, t) if flip else (t, off))
        water.add_river(pts, width)
    elif kind == "lake":
        a = rng.uniform(0, 2 * math.pi)
        rad = rng.uniform(0.1, 0.15) * e
        d = rng.uniform(rad * 1.5 + 30, rad * 1.5 + 0.2 * e)
        lc = (c[0] + math.cos(a) * d, c[1] + math.sin(a) * d)
        poly = [(lc[0] + math.cos(t) * rad * (1 + 0.35 * noise.value(math.cos(t) * 1.5 + 3, math.sin(t) * 1.5 + 3)),
                 lc[1] + math.sin(t) * rad * (1 + 0.35 * noise.value(math.cos(t) * 1.5 + 3, math.sin(t) * 1.5 + 3)))
                for t in (i * 2 * math.pi / 48 for i in range(48))]
        water.add_poly(poly, "lake")
    elif kind == "sea":
        side = rng.randrange(4)  # 0 왼쪽, 1 위, 2 오른쪽, 3 아래
        sea_dir = [math.pi, -math.pi / 2, 0.0, math.pi / 2][side]
        horiz = side in (1, 3)  # 바닷가 선이 가로로 놓인다
        span = w if horiz else h
        depth_room = h if horiz else w
        depth = rng.uniform(0.18, 0.26) * depth_room
        coast = []
        for i in range(int((span + 40) / 10) + 1):
            t = -20 + i * 10
            d = depth + noise.fbm(t / 160, 11.1) * 0.08 * e
            coast.append(d)
        pts = []
        for i, d in enumerate(coast):
            t = -20 + i * 10
            if side == 0:
                pts.append((d, t))
            elif side == 2:
                pts.append((w - d, t))
            elif side == 1:
                pts.append((t, d))
            else:
                pts.append((t, h - d))
        if side == 0:
            poly = pts + [(-20, pts[-1][1]), (-20, pts[0][1])]
        elif side == 2:
            poly = pts + [(w + 20, pts[-1][1]), (w + 20, pts[0][1])]
        elif side == 1:
            poly = pts + [(pts[-1][0], -20), (pts[0][0], -20)]
        else:
            poly = pts + [(pts[-1][0], h + 20), (pts[0][0], h + 20)]
        water.add_poly(poly, "sea")
    return water, sea_dir


# ---------- 길 ----------

class _Roads:
    """길 목록과 선분 격자. 선분은 [a, b, 길] 목록이라 갈림길을 넣을 때 제자리에서 둘로 나눈다."""

    def __init__(self):
        self.list: list[dict] = []
        self.grid = geom.Grid(30)

    def add(self, kind: str, width: float, pts: list[Point], main: bool = False) -> dict:
        road = {"kind": kind, "width": width, "pts": pts, "main": main}
        self.list.append(road)
        for a, b in zip(pts, pts[1:]):
            self.grid.add(geom.bbox([a, b]), [a, b, road])
        return road

    def near(self, a: Point, b: Point, pad: float) -> list[list]:
        return self.grid.near(geom.bbox([a, b]), pad)

    def split(self, seg: list, x: Point) -> None:
        """선분 seg 위의 점 x 를 그 길의 꼭짓점으로 넣는다 (갈림길이 이어지게)."""
        a, b, road = seg
        if x in (a, b):
            return
        pts = road["pts"]
        i = next(k for k in range(len(pts) - 1) if pts[k] == a and pts[k + 1] == b)
        pts.insert(i + 1, x)
        seg[1] = x
        self.grid.add(geom.bbox([x, b]), [x, b, road])


def _walk(start: Point, heading: float, steps: int, step: float, noise: geom.Noise, salt: float, wiggle: float,
          ok, w: float, h: float) -> list[Point]:
    """start 에서 heading 쪽으로 걷는 길. ok(점) 가 거짓이면 방향을 조금씩 틀어 보고, 다 막히면 멈춘다.
    영역 밖으로 나가면 가장자리에서 멈춘다."""
    pts = [start]
    a0 = heading
    for i in range(steps):
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


def _harbor(c: Point, sea_dir: float, r: random.Random, water: _Water, roads: _Roads, w: float, h: float) -> Optional[dict]:
    """바다로 가는 길과 부두. 가운데에서 바다 쪽으로 곧게 걸어 물가 앞에서 멈추고(길), 거기서 물 위로 20~35m 부두(bridge)를 낸다.
    길 끝 = 부두 뿌리를 두 길이 함께 써서 이어진다. 물가 앞에는 부둣가 빈터(quay)를 둔다. 바다에 닿지 못하면 None."""
    a = sea_dir + r.uniform(-0.2, 0.2)
    u = (math.cos(a), math.sin(a))
    pts = [c]
    while len(pts) < 40:
        q = (pts[-1][0] + u[0] * 6, pts[-1][1] + u[1] * 6)
        if water.wet(q, 3, river=False) or not (2 < q[0] < w - 2 and 2 < q[1] < h - 2):
            break
        pts.append(q)
    root = pts[-1]
    length = r.uniform(20, 35)
    out, wet = root, 0.0
    for _ in range(40):
        q = (out[0] + u[0] * 3, out[1] + u[1] * 3)
        if not (0 <= q[0] <= w and 0 <= q[1] <= h):
            break
        out = q
        if water.wet(q, 0, river=False):
            wet += 3
            if wet >= length:
                break
    if len(pts) < 3 or wet < 12:
        return None
    roads.add("road", r.uniform(5.5, 6.5), pts, main=True)
    roads.add("bridge", 4.0, [root, out], main=True)
    quay = geom.rect((root[0] - u[0] * 7, root[1] - u[1] * 7), u, r.uniform(24, 32), 12)
    return {"root": root, "end": out, "dir": u, "quay": quay}


def _bridge_runs(pts: list[Point], water: _Water) -> list[tuple[str, list[Point]]]:
    """길 점들을 뭍 · 강 구간으로 나눈다. 강 구간(다리)은 양쪽 뭍 점을 끝점으로 갖는다. 강에서 끝나는 꼬리는 버린다."""
    wet = [water.on_river(q) for q in pts]
    runs: list[tuple[str, list[Point]]] = []
    i = 0
    while i < len(pts):
        j = i
        while j + 1 < len(pts) and wet[j + 1] == wet[i]:
            j += 1
        if not wet[i]:
            runs.append(("road", pts[i:j + 1]))
        elif i > 0 and j + 1 < len(pts):
            runs.append(("bridge", pts[i - 1:j + 2]))
        else:
            break  # 강에서 끝나거나 강에서 시작하면 그 뒤는 버린다
        i = j + 1
    return [(k, ln) for k, ln in runs if len(ln) >= 2]


# ---------- 마을 ----------

def village(spec: MapSpec, places: list[dict]) -> dict:
    """마을 지도 (read_layout 과 같은 모양 + spots, missing, houses, target, seed, retries).
    places: [{key, name, kind}] 이 지도에 놓을 이야기 장소 (kind 는 CATEGORIES id)."""
    if spec.kind != "village":
        raise ValueError("지금은 마을만 만들 수 있어요")
    for retry in range(4):
        out = _village(spec, places, str(spec.seed) + (f":retry{retry}" if retry else ""))
        if out is not None:
            out["retries"] = retry
            return out
    raise ValueError("마을을 만들지 못했어요. 시드를 바꿔 보세요")


def _village(spec: MapSpec, places: list[dict], seed: str) -> Optional[dict]:
    rng = lambda stage: random.Random(f"{seed}:{stage}")  # noqa: E731
    target, e = SIZES[spec.size]
    h, w = float(e), float(round(e * 1.3))
    base = rng("base")
    noise = geom.Noise(base)
    c = (w / 2 + base.uniform(-0.05, 0.05) * w, h / 2 + base.uniform(-0.05, 0.05) * h)
    reach = e * 0.42  # 집이 드문드문해지는 반지름
    water, sea_dir = _make_water(spec.water, rng("water"), noise, w, h, e, c)
    if sea_dir is not None:  # 바닷가 마을은 해안에 붙는다: 바다 쪽으로 걸어 해안을 찾고 40~60m 안쪽을 가운데로
        sd = (math.cos(sea_dir), math.sin(sea_dir))
        q = c
        for _ in range(int(e)):
            nq = (q[0] + sd[0] * 2, q[1] + sd[1] * 2)
            if water.wet(nq, 0, river=False) or not (0 < nq[0] < w and 0 < nq[1] < h):
                break
            q = nq
        back = rng("coast").uniform(40, 60)
        c = (q[0] - sd[0] * back, q[1] - sd[1] * back)
    if water.wet(c, 25):
        return None

    roads = _Roads()
    plaza: Optional[Poly] = None
    squares: list[Poly] = []  # 집 · 밭 · 나무가 들어서지 않는 빈터 (광장, 부둣가)
    if spec.roads == "square":
        pr = rng("plaza").uniform(16, 24)
        plaza = [(c[0] + math.cos(t) * pr * (1 + 0.15 * noise.value(t, 5.5)), c[1] + math.sin(t) * pr * (1 + 0.15 * noise.value(t, 5.5)))
                 for t in (i * 2 * math.pi / 10 for i in range(10))]
        squares.append(plaza)

    # 간선: 가운데에서 가장자리로
    r = rng("arms")
    a0 = r.uniform(0, 2 * math.pi)
    if spec.roads == "line":
        angles = [a0, a0 + math.pi] if sea_dir is None else [sea_dir + math.pi / 2, sea_dir - math.pi / 2]
    elif sea_dir is not None:
        angles = [sea_dir + math.pi / 2, sea_dir + math.pi, sea_dir - math.pi / 2]
    else:
        n = 4 if spec.roads == "square" or r.random() < 0.5 else 3
        angles = [a0 + i * 2 * math.pi / n for i in range(n)]
    angles = [a + r.uniform(-0.25, 0.25) for a in angles]
    dry = lambda q: not water.wet(q, 4, river=False)  # noqa: E731  간선은 강을 다리로 건넌다
    arm_ends: list[Point] = []
    for i, a in enumerate(angles):
        pts = _walk(c, a, int(e * 1.2 / 10), 10, noise, 3.1 * i, 0.5, dry, w, h)
        if len(pts) < 4:
            continue
        for kind, ln in _bridge_runs(pts, water):
            roads.add(kind, r.uniform(6, 7.5) if kind == "road" else 6, ln, main=True)
        arm_ends.append(pts[-1])
    if len(arm_ends) < 2 and spec.roads != "line":
        return None
    if not arm_ends:
        return None
    harbor = _harbor(c, sea_dir, rng("harbor"), water, roads, w, h) if sea_dir is not None else None
    if harbor:
        squares.append(harbor["quay"])

    lots: list[dict] = []
    lot_grid = geom.Grid(30)
    lr = rng("lots")

    def free(poly: Poly) -> bool:
        x0, y0, x1, y1 = geom.bbox(poly)
        if x0 < 4 or y0 < 4 or x1 > w - 4 or y1 > h - 4:
            return False
        if any(water.wet(q, 3) for q in poly + [geom.centroid(poly)]):
            return False
        if any(geom.convex_overlap(poly, sq, 2) for sq in squares):
            return False
        for a, b, road in roads.near((x0, y0), (x1, y1), 10):
            if geom.poly_seg_near(poly, a, b, road["width"] / 2 + 0.8):
                return False
        return not any(geom.convex_overlap(poly, lot["poly"], 0.6) for lot in lot_grid.near((x0, y0, x1, y1), 2))

    def lots_along(road: dict) -> None:
        pts = road["pts"]
        if road["kind"] != "road":
            return
        for side in (1, -1):
            s = lr.uniform(4, 10)
            seglens = [math.dist(a, b) for a, b in zip(pts, pts[1:])]
            total = sum(seglens)
            while s < total - 6:
                k, acc = 0, 0.0
                while k < len(seglens) - 1 and acc + seglens[k] < s:
                    acc += seglens[k]
                    k += 1
                a, b = pts[k], pts[k + 1]
                p = geom.lerp(a, b, (s - acc) / (seglens[k] or 1))
                ln = seglens[k] or 1
                d = ((b[0] - a[0]) / ln, (b[1] - a[1]) / ln)
                nrm = (-d[1] * side, d[0] * side)
                dist = math.dist(p, c)
                front = lr.uniform(9, 14) * (1 + 0.5 * dist / reach)
                depth = lr.uniform(14, 22) * (1 + 0.3 * dist / reach)
                keep = max(0.0, min(1.0, 1.3 - (dist / reach) ** 2))
                if plaza is None or dist > 30:
                    off = road["width"] / 2 + 1.5 + depth / 2
                    poly = geom.rect((p[0] + nrm[0] * off, p[1] + nrm[1] * off), nrm, front, depth)
                    if lr.random() < keep and free(poly):
                        lot = {"poly": poly, "front": p, "n": nrm, "d": d, "w": front, "depth": depth, "dist": dist,
                               "main": road["main"], "use": "", "road": road}
                        lots.append(lot)
                        lot_grid.add(geom.bbox(poly), lot)
                s += front + lr.uniform(0, 4)

    # 가지길: 있는 길의 꼭짓점에서 옆으로. 길을 먼저 다 내고 필지를 붙인다 (필지가 먼저 있으면 가지길이 막힌다)
    br = rng("branches")
    branch_noise = geom.Noise(br)
    tries = 0

    def grow() -> Optional[dict]:
        road = br.choice([x for x in roads.list if x["kind"] == "road"])
        pts = road["pts"]
        if len(pts) < 5:
            return None
        k = br.randrange(2, len(pts) - 2)
        p = pts[k]
        dist = math.dist(p, c)
        if dist > reach * 1.1 or (plaza and dist < 30) or dist < 15:
            return None
        a, b = pts[k - 1], pts[k + 1]
        heading = math.atan2(b[1] - a[1], b[0] - a[0]) + br.choice((1, -1)) * (math.pi / 2 + br.uniform(-0.3, 0.3))
        length = br.uniform(50, 130) * (1 - 0.4 * dist / reach)
        return _branch(p, heading, length, roads, lot_grid, water, squares, branch_noise, tries, w, h)

    def frontage() -> float:  # 집이 들어설 만한 길 길이 (가운데에 가까운 구간만)
        return sum(math.dist(a, b) for rd in roads.list if rd["kind"] == "road"
                   for a, b in zip(rd["pts"], rd["pts"][1:]) if math.dist(geom.lerp(a, b, 0.5), c) < reach)

    while frontage() < target * 11 and tries < target * 4:
        tries += 1
        grow()
    for road in list(roads.list):
        lots_along(road)
    while len(lots) < target and tries < target * 6:  # 모자라면 빈 곳에 가지길을 더 낸다
        tries += 1
        built = grow()
        if built:
            lots_along(built)

    if len(lots) > target * 1.15:  # 너무 많으면 먼 필지부터 비운다
        lots.sort(key=lambda lot: lot["dist"])
        lots = lots[:round(target * 1.15)]
        lot_grid = geom.Grid(30)
        for lot in lots:
            lot_grid.add(geom.bbox(lot["poly"]), lot)

    # 이야기 장소 자리
    spots, missing = _place_spots(places, lots, roads, water, plaza, c, arm_ends, reach, rng("spots"), harbor, sea_dir, lot_grid)

    # 집
    hr = rng("houses")
    buildings: list[Poly] = []
    numbers: list[int] = []  # 집 번호를 붙일 건물 (필지마다 본채 하나, 붙은 채 · 등대 탑은 뺀다)
    for lot in lots:
        numbers.append(len(buildings))
        buildings += _houses(lot, hr)
    buildings += [sp["tower"] for sp in spots if sp.get("tower")]
    for sp in spots:
        if sp.get("lot") is not None:
            sp["at"] = geom.centroid(sp["lot"]["houses"][0])

    # 밭 · 풀밭 (숲이 될 곳은 비운다)
    forest = geom.Noise(rng("forest"))
    fields, greens, edge_trees = _fields(spec, rng("fields"), w, h, c, reach, water, roads, lot_grid, squares, forest)
    field_grid = geom.Grid(40)  # 나무가 들어서지 않는 밭 (풀밭에는 과수원 · 외딴 나무가 선다)
    for poly in fields:
        field_grid.add(geom.bbox(poly), poly)
    for sp in spots:
        if sp["kind"] == "field" and sp.get("at") is None:
            if fields:
                sp["at"] = geom.centroid(min(fields, key=lambda f: math.dist(geom.centroid(f), c)))
            else:
                missing.append({"key": sp["key"], "name": sp["name"], "reason": "밭이 없어요. 밭을 늘려 보세요"})

    # 나무
    trees = _trees(spec, rng("trees"), w, h, water, roads, lot_grid, field_grid, squares, forest, edge_trees)
    for sp in spots:
        if sp["kind"] == "forest" and sp.get("at") is None:
            if trees:
                tg = geom.Grid(30)
                for t in trees:
                    tg.add((t[0], t[1], t[0], t[1]), t)
                sp["at"] = max(trees, key=lambda t: sum(1 for u in tg.near((t[0], t[1], t[0], t[1]), 30) if math.dist(t, u) < 30))
            else:
                missing.append({"key": sp["key"], "name": sp["name"], "reason": "숲이 없어요. 숲을 늘려 보세요"})

    # 길이 한 덩어리인지
    parent: dict[Point, Point] = {}

    def find(x: Point) -> Point:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for road in roads.list:
        for a, b in zip(road["pts"], road["pts"][1:]):
            parent[find(a)] = find(b)
    if len({find(q) for road in roads.list for q in road["pts"]}) != 1:
        return None

    nx = lambda q: [round(q[0] / w, 5), round(q[1] / h, 5)]  # noqa: E731
    clip = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)]
    return {
        "w": w, "h": h, "generator": GENERATOR, "version": str(VERSION), "seed": spec.seed,
        "roads": [{"kind": rd["kind"], "width": round(rd["width"], 2), "points": [nx(q) for q in rd["pts"]]} for rd in roads.list],
        "buildings": [[nx(q) for q in poly] for poly in buildings],
        "water": [[nx(q) for q in cp] for cp in (geom.clip_convex(poly, clip) for poly in water.polys) if len(cp) >= 3],
        "rivers": [{"width": round(rv["width"], 2), "points": [nx(q) for q in rv["points"]]} for rv in water.rivers],
        "squares": [[nx(q) for q in sq] for sq in squares],
        "fields": [[nx(q) for q in poly] for poly in fields],
        "greens": [[nx(q) for q in poly] for poly in greens],
        "trees": [nx(q) for q in trees],
        "spots": [{"key": sp["key"], "name": sp["name"], "kind": sp["kind"], "x": nx(sp["at"])[0], "y": nx(sp["at"])[1]}
                  for sp in spots if sp.get("at") is not None],
        "missing": missing,
        "houses": len(lots), "target": target, "numbers": numbers,
    }


def _branch(p: Point, heading: float, length: float, roads: _Roads, lot_grid: geom.Grid, water: _Water,
            squares: list[Poly], noise: geom.Noise, salt: int, w: float, h: float) -> Optional[dict]:
    """가지길 하나를 낸다. 다른 길에 가까워지면 그 길에 이어 붙이고(갈림길), 물 · 필지 · 영역 끝에 막히면 멈춘다.
    짧으면 버린다 (None)."""
    step, width = 8.0, 4.0
    pts = [p]
    hit: Optional[tuple[list, Point]] = None
    for i in range(int(length / step)):
        q0 = pts[-1]
        a = heading + noise.value(q0[0] / 60 + salt, q0[1] / 60) * 0.35
        q = (q0[0] + math.cos(a) * step, q0[1] + math.sin(a) * step)
        if not (8 <= q[0] <= w - 8 and 8 <= q[1] <= h - 8) or water.wet(q, 4):
            break
        if any(geom.inside(q, sq) for sq in squares):
            break
        if any(geom.poly_seg_near(lot["poly"], q0, q, 1.5) for lot in lot_grid.near(geom.bbox([q0, q]), 2)):
            break
        # 다른 길과 만나거나 가까워지면 이어 붙인다 (처음 두 걸음은 나온 길을 빼고 본다)
        ahead = (q0[0] + math.cos(a) * 30, q0[1] + math.sin(a) * 30)
        near = [s for s in roads.near(q0, ahead, 2) if not (i < 2 and min(geom.seg_dist(p, s[0], s[1]), math.dist(p, s[0])) < 14)]
        cross = None
        for s in near:
            x = geom.seg_cross(q0, ahead, s[0], s[1])
            if x and (cross is None or x[0] < cross[0]):
                cross = (x[0], s, x[2])
        if cross and cross[0] * 30 <= step * 2.5:
            hit = (cross[1], cross[2])
            break
        if any(geom.seg_dist(q, s[0], s[1]) < 20 for s in near):
            break
        pts.append(q)
        heading = a
    if hit:
        seg, x = hit
        q0 = pts[-1]
        if math.dist(q0, x) < 0.1 or any(geom.poly_seg_near(lot["poly"], q0, x, 1.5) for lot in lot_grid.near(geom.bbox([q0, x]), 2)):
            hit = None  # 이어 붙일 길 사이에 필지가 있으면 막다른 길로 둔다
        else:
            roads.split(seg, x)
            pts.append(x)
    if len(pts) < 4 and not (hit and len(pts) >= 2):
        return None
    return roads.add("road", width, pts)


def _houses(lot: dict, r: random.Random) -> list[Poly]:
    """필지 안 길 쪽에 집 한 채 (가끔 뒤에 붙은 채 하나 더). 장소가 놓인 필지는 크게."""
    n, d = lot["n"], lot["d"]
    big = lot["use"] in ("temple", "manor")
    bw = min(lot["w"] - (3 if big else 2), r.uniform(6, 11) * (1.6 if big else 1.15 if lot["use"] else 1))
    bd = min(lot["depth"] - 4, r.uniform(5.5, 9) * (1.6 if big else 1.15 if lot["use"] else 1))
    shift = r.uniform(-1, 1) * (lot["w"] - bw) / 4
    fx, fy = lot["front"]
    off = lot["road"]["width"] / 2 + 1.5 + r.uniform(0.5, 2) + bd / 2
    cx, cy = fx + n[0] * off + d[0] * shift, fy + n[1] * off + d[1] * shift
    out = [geom.rect((cx, cy), n, bw, bd)]
    room = lot["depth"] - (off - lot["road"]["width"] / 2 - 1.5) - bd / 2 - 1.5
    if r.random() < 0.3 and room > 4 and not big:
        bd2 = min(room, r.uniform(3.5, 6))
        bw2 = bw * r.uniform(0.4, 0.6)
        side = r.choice((1, -1)) * (bw - bw2) / 2
        c2 = (cx + n[0] * (bd / 2 + bd2 / 2) + d[0] * side, cy + n[1] * (bd / 2 + bd2 / 2) + d[1] * side)
        out.append(geom.rect(c2, n, bw2, bd2))
    lot["houses"] = out
    return out


def _place_spots(places: list[dict], lots: list[dict], roads: _Roads, water: _Water, plaza: Optional[Poly],
                 c: Point, arm_ends: list[Point], reach: float, r: random.Random, harbor: Optional[dict] = None,
                 sea_dir: Optional[float] = None, lot_grid: Optional[geom.Grid] = None) -> tuple[list[dict], list[dict]]:
    """이야기 장소마다 자리를 고른다. 필지가 필요한 종류는 필지를 하나씩 차지한다 (집은 뒤에 짓는다).
    물가 종류는 단어로 나눈다: 등대 · 방파제는 해안 끝(곶)에 탑을 세우고, 해변 · 갯벌은 물가 자체, 나머지(부두 · 수산시장 등)는
    부두 옆 필지 (부두가 없으면 물가에 가장 가까운 필지, 그것도 40m 넘게 떨어지면 물가 자체).
    spots: {key, name, kind, at(점) 또는 lot, tower(등대 건물)}, missing: {key, name, reason}."""
    spots: list[dict] = []
    missing: list[dict] = []
    free = lambda: [lot for lot in lots if not lot["use"]]  # noqa: E731
    shore = water.edge()
    used_pts: list[Point] = []

    def waterline(q: Point) -> Point:
        """물가 점에서 마을 쪽으로 물이 없는 곳까지 옮긴 점."""
        return water.inland(q, c)

    def tower_at() -> Optional[tuple[Point, Poly]]:
        """해안 끝 자리와 등대 탑. 마을 가운데에서 0.3~0.8 반지름 거리의 물가 가운데 바다 쪽으로 가장 튀어나온 곳부터,
        길 · 필지와 겹치지 않는 첫 자리."""
        sd = (math.cos(sea_dir), math.sin(sea_dir)) if sea_dir is not None else None
        ring = [q for q in shore if 0.3 * reach <= math.dist(q, c) <= 0.8 * reach] or shore
        score = (lambda q: q[0] * sd[0] + q[1] * sd[1]) if sd else (lambda q: math.dist(q, c))  # noqa: E731
        for q in sorted(ring, key=score, reverse=True)[:40]:
            p = waterline(q)
            d = math.dist(p, c) or 1
            poly = geom.rect(p, ((c[0] - p[0]) / d, (c[1] - p[1]) / d), 7, 7)
            box = geom.bbox(poly)
            if any(geom.poly_seg_near(poly, a, b, rd["width"] / 2 + 1) for a, b, rd in roads.near(box[:2], box[2:], 8)):
                continue
            if lot_grid and any(geom.convex_overlap(poly, lot["poly"], 1) for lot in lot_grid.near(box, 2)):
                continue
            if any(math.dist(p, u) < 30 for u in used_pts):
                continue
            return p, poly
        return None

    def near_water(lot: dict) -> float:
        return min((math.dist(lot["front"], q) for q in shore), default=math.inf)

    def point_at(q: Point) -> Point:
        while any(math.dist(q, u) < 6 for u in used_pts):  # 같은 자리에 겹치지 않게 조금 옮긴다
            q = (q[0] + 9, q[1] + 3)
        used_pts.append(q)
        return q

    for pl in places:
        kind = pl["kind"] if pl["kind"] in CATEGORY_IDS else "home"
        sp = {"key": pl["key"], "name": pl["name"], "kind": kind, "at": None, "lot": None}
        pick: Optional[dict] = None
        # 다른 장소와 30m 안의 필지는 남는 게 없을 때만 (이름표가 겹쳐 읽히지 않게)
        cand = [lot for lot in free() if all(math.dist(lot["front"], u) > 30 for u in used_pts)] or free()
        if kind == "center":
            sp["at"] = point_at(geom.centroid(plaza) if plaza else c)
        elif kind in ("market", "well"):  # 마을 가운데 둘레, 다른 장소와 떨어진 쪽
            a = r.uniform(0, 2 * math.pi)
            d = 14 if kind == "well" else 24
            ring = [(c[0] + math.cos(a + k * math.pi / 4) * d, c[1] + math.sin(a + k * math.pi / 4) * d) for k in range(8)]
            dry = [q for q in ring if not water.wet(q, 2)] or [c]
            sp["at"] = point_at(max(dry, key=lambda q: min((math.dist(q, u) for u in used_pts), default=0)))
        elif kind == "far":
            sp["at"] = point_at(arm_ends[len(spots) % len(arm_ends)])
        elif kind in NEED_WATER and not shore:
            missing.append({"key": sp["key"], "name": sp["name"], "reason": NEED_WATER[kind]})
            continue
        elif kind == "bridge":
            bridges = [rd for rd in roads.list if rd["kind"] == "bridge"]
            if not bridges:
                missing.append({"key": sp["key"], "name": sp["name"], "reason": NEED_WATER["bridge"]})
                continue
            b = min(bridges, key=lambda rd: math.dist(rd["pts"][len(rd["pts"]) // 2], c))
            sp["at"] = point_at(geom.lerp(b["pts"][0], b["pts"][-1], 0.5))
        elif kind == "river":
            if not water.rivers:
                missing.append({"key": sp["key"], "name": sp["name"], "reason": NEED_WATER["river"]})
                continue
            sp["at"] = point_at(min(water.rivers[0]["points"], key=lambda q: math.dist(q, c)))
        elif kind == "pond":
            ponds = [poly for poly, k in zip(water.polys, water.kinds) if k == "lake"]
            if not ponds:
                missing.append({"key": sp["key"], "name": sp["name"], "reason": NEED_WATER["pond"]})
                continue
            sp["at"] = point_at(geom.centroid(ponds[0]))
        elif kind in ("forest", "field"):
            pass  # 밭 · 나무를 만든 뒤 정한다
        elif not cand:
            missing.append({"key": sp["key"], "name": sp["name"], "reason": "놓을 필지가 모자라요. 마을을 크게 해 보세요"})
            continue
        elif kind == "temple":
            pick = max(cand, key=lambda lot: lot["w"] * lot["depth"] / (1 + lot["dist"] / 40))
        elif kind == "manor":
            ring = [lot for lot in cand if 0.25 * reach <= lot["dist"] <= 0.6 * reach] or cand
            pick = max(ring, key=lambda lot: lot["w"] * lot["depth"])
        elif kind == "inn":
            pick = min([lot for lot in cand if lot["main"]] or cand, key=lambda lot: lot["dist"])
        elif kind == "smith":
            pick = min([lot for lot in cand if lot["main"]] or cand, key=lambda lot: abs(lot["dist"] - 0.75 * reach))
        elif kind == "mill":
            pick = min(cand, key=near_water) if shore else max(cand, key=lambda lot: lot["dist"])
        elif kind == "shore":
            word = pl.get("word", "")
            if word in LIGHT_WORDS and sea_dir is None:  # 등대는 바다에만 선다
                missing.append({"key": sp["key"], "name": sp["name"], "reason": "바다가 없어요. 물을 바다로 바꿔 보세요"})
                continue
            if word in LIGHT_WORDS and (t := tower_at()):
                p, poly = t
                sp["at"], sp["tower"] = point_at(p), poly
                if lot_grid is not None:  # 밭 · 나무가 탑을 비켜 가게
                    lot_grid.add(geom.bbox(poly), {"poly": poly, "houses": [poly]})
            elif word in BEACH_WORDS:
                sp["at"] = point_at(waterline(min(shore, key=lambda q: math.dist(q, c))))
            elif harbor:
                quay = [lot for lot in cand if math.dist(lot["front"], harbor["root"]) < 50]
                if quay:
                    pick = min(quay, key=lambda lot: math.dist(lot["front"], harbor["root"]))
                else:
                    sp["at"] = point_at(geom.centroid(harbor["quay"]))
            else:
                pick = min(cand, key=near_water)
                if near_water(pick) > 40:
                    pick = None
                    sp["at"] = point_at(waterline(min(shore, key=lambda q: math.dist(q, c))))
        else:  # home
            pick = min(cand, key=lambda lot: lot["dist"] + r.uniform(0, 40))
        if pick is not None:
            pick["use"] = kind
            sp["lot"] = pick
            used_pts.append(pick["front"])
        spots.append(sp)
    return spots, missing


def _strips(poly: Poly, angle: float, depth: int = 0) -> list[Poly]:
    """밭을 이랑 띠처럼 나눈다: angle 방향에 수직으로 30m 보다 넓으면 반으로 자른다."""
    nx, ny = -math.sin(angle), math.cos(angle)
    proj = [q[0] * nx + q[1] * ny for q in poly]
    if depth >= 3 or max(proj) - min(proj) < 30:
        return [poly]
    c = geom.centroid(poly)
    a, b = c, (c[0] + math.cos(angle), c[1] + math.sin(angle))
    left, right = geom.split_convex(poly, a, b)
    return [s for half in (left, right) if half for s in _strips(half, angle, depth + 1)]


def _forest_at(forest: geom.Noise, q: Point) -> float:
    return forest.fbm(q[0] / 140, q[1] / 140)


def _cut_by_roads(poly: Poly, roads: _Roads, tries: int = 4) -> list[Poly]:
    """볼록 다각형을 지나는 길로 자른다: 길 선을 길 폭의 반 + 1.5m 만큼 양쪽으로 밀어 두 쪽을 남긴다 (밭이 길가까지 온다).
    tries 번 자른 뒤에도 길에 걸린 조각은 버린다."""
    pieces, done = [poly], []
    for _ in range(tries):
        nxt = []
        for pc in pieces:
            x0, y0, x1, y1 = geom.bbox(pc)
            hit = next(((a, b, rd) for a, b, rd in roads.near((x0, y0), (x1, y1), 8)
                        if geom.poly_seg_near(pc, a, b, rd["width"] / 2 + 1)), None)
            if not hit:
                done.append(pc)
                continue
            a, b, rd = hit
            ln = math.dist(a, b) or 1
            n = (-(b[1] - a[1]) / ln, (b[0] - a[0]) / ln)
            off = rd["width"] / 2 + 1.5
            left, _ = geom.split_convex(pc, (a[0] + n[0] * off, a[1] + n[1] * off), (b[0] + n[0] * off, b[1] + n[1] * off))
            _, right = geom.split_convex(pc, (a[0] - n[0] * off, a[1] - n[1] * off), (b[0] - n[0] * off, b[1] - n[1] * off))
            nxt += [x for x in (left, right) if x and abs(geom.area(x)) > 150]
        pieces = nxt
        if not pieces:
            break
    return done


def _edge_points(poly: Poly, step: float) -> list[Point]:
    """다각형 테두리를 따라 step 간격의 점."""
    out = []
    for i, b in enumerate(poly):
        a = poly[i - 1]
        n = max(1, int(math.dist(a, b) / step))
        out += [geom.lerp(a, b, k / n) for k in range(n)]
    return out


def _fields(spec: MapSpec, r: random.Random, w: float, h: float, c: Point, reach: float, water: _Water, roads: _Roads,
            lot_grid: geom.Grid, squares: list[Poly], forest: geom.Noise) -> tuple[list[Poly], list[Poly], list[Point]]:
    """밭 · 풀밭과 생울타리 · 과수원 나무 자리.
    큰 Voronoi 칸(약 50m)을 길로 잘라 길가까지 채우고, 마을에서 멀거나 숲이 될 곳은 비운다. 밭은 이랑 띠로 나누고,
    밭 테두리 절반쯤에 생울타리 나무를 세운다. 마을 안 빈터 일부는 풀밭, 그 가운데 일부는 과수원(줄 맞춘 나무)."""
    seeds = geom.poisson(r, w, h, 50)
    cells = geom.voronoi(seeds, (0, 0, w, h))
    share = FIELD_SHARE[spec.fields]
    level = FOREST_LEVEL[spec.forest]
    far = reach * (1.35 + 0.5 * share)  # 밭이 있는 가장 먼 거리
    fields: list[Poly] = []
    greens: list[Poly] = []
    edge: list[Point] = []
    for seed_pt, cell in zip(seeds, cells):
        if len(cell) < 3:
            continue
        d = math.dist(seed_pt, c)
        roll = r.random()
        if _forest_at(forest, seed_pt) > level - 0.04:
            continue  # 숲 자리
        if d < reach * 0.45:  # 마을 한가운데: 빈터면 풀밭
            is_green = roll < 0.45
        elif d <= far:  # 둘레: 풀밭 조금, 나머지는 밭 양에 따라
            is_green = roll < 0.25
            if not is_green and roll > 0.25 + share * 0.75:
                continue
        else:
            continue
        if d < reach * 0.45 and not is_green:
            continue
        for piece in _cut_by_roads(cell, roads):
            poly = geom.scale(piece, 0.94)
            x0, y0, x1, y1 = geom.bbox(poly)
            if any(water.wet(q, 2) for q in poly + [geom.centroid(poly)]):
                continue
            if any(geom.convex_overlap(poly, sq, 2) for sq in squares):
                continue
            if any(geom.convex_overlap(poly, lot["poly"], 1) for lot in lot_grid.near((x0, y0, x1, y1), 2)):
                continue
            if is_green:
                greens.append(poly)
                if r.random() < 0.4:  # 과수원: 7m 간격 줄
                    edge += [(x, y) for x in _frange(x0 + 4, x1 - 2, 7) for y in _frange(y0 + 4, y1 - 2, 7)
                             if geom.inside((x, y), geom.scale(poly, 0.85))]
                continue
            angle = r.uniform(0, math.pi)
            fields += [geom.scale(s, 0.93) for s in _strips(poly, angle)]
            if r.random() < 0.55:  # 생울타리
                edge += _edge_points(geom.scale(piece, 0.99), 6.0)
    return fields, greens, edge


def _frange(a: float, b: float, step: float) -> list[float]:
    return [a + i * step for i in range(max(0, int((b - a) / step) + 1))]


def _trees(spec: MapSpec, r: random.Random, w: float, h: float, water: _Water, roads: _Roads, lot_grid: geom.Grid,
           field_grid: geom.Grid, squares: list[Poly], forest: geom.Noise, extra: list[Point]) -> list[Point]:
    """나무: 숲 노이즈가 높은 곳은 촘촘한 숲(5m 간격), 숲 가장자리는 성기게, 그 밖은 아주 드물게.
    extra(생울타리 · 과수원 자리)도 같은 검사를 거쳐 더한다."""
    level = FOREST_LEVEL[spec.forest]
    out = []

    def ok(q: Point, in_forest: bool) -> bool:
        if not (0 <= q[0] <= w and 0 <= q[1] <= h):
            return False
        box = (q[0], q[1], q[0], q[1])
        if water.wet(q, 2) or any(geom.inside(q, sq) for sq in squares):
            return False
        if not in_forest and any(geom.inside(q, lot["poly"]) for lot in lot_grid.near(box)):
            return False
        if any(geom.inside(q, hs) for lot in lot_grid.near(box, 3) for hs in lot.get("houses", [])):
            return False
        if any(geom.inside(q, poly) for poly in field_grid.near(box)):
            return False
        return not any(geom.seg_dist(q, a, b) < rd["width"] / 2 + 2.5 for a, b, rd in roads.near(q, q, 6))

    for q in geom.poisson(r, w, h, 5):
        f = _forest_at(forest, q)
        keep = 1.0 if f > level else 0.35 if f > level - 0.06 else 0.004
        if r.random() < keep and ok(q, f > level):
            out.append(q)
    out += [q for q in extra if ok(q, False)]
    return out

"""현대 동네 생성기: 시드 하나로 대로 격자 · 아파트 단지 · 빌라촌 · 대로변 상가 · 역 앞 · 학교 · 공원이 있는 가상의 동네를 만든다.
LLM 을 부르지 않는다.

순서: 대로 격자(슈퍼블록 한 변 300~450m. 줄마다 자리와 기울기를 조금 흔든 곧은 선, 가운데 줄은 넓은 대로) → (하천: 가로 대로 하나를
하천으로 바꾸고 세로 대로는 다리로 건넌다) → 슈퍼블록 종류(역 앞 · 공원 · 아파트 · 빌라) → 블록 쪼개기(슈퍼블록을 길 폭만큼 줄인 뒤
긴 변에 거의 수직인 선으로 되풀이해 잘라 소로 · 골목을 낸다) → 필지 · 건물(빌라는 두 줄 좁은 필지, 대로에 닿은 필지는 상가, 아파트
단지는 남향 판상 · 탑상 동 배치와 단지 안 길, 학교는 교사와 운동장) → 쓰임 · 층수 → 이야기 장소.

새 길은 늘 곧은 선분이고 두 끝은 둘레 길의 가운데 선 위 점이다. 그 점을 둘레 길의 꼭짓점(splits)으로도 넣어 길이 한 덩어리가 된다
(citygen 의 골목과 같은 방식). 블록은 변마다 무엇과 맞닿았는지 꼬리표를 단 볼록 다각형이다(blocks.cut).
결과는 atlas.read_layout 모양 (+ wards, spots, missing, houses, numbers, parts, seed, retries). 좌표는 m 로 계산하고 마지막에
0~1 로 나눈다. 단계마다 난수원을 따로 두어(f"{seed}:{단계}") 같은 MapSpec 이면 언제나 같은 동네가 나온다.

길 키우기(roadnet.grow)에 격자 방향 목표를 주는 방식은 동심 사각 고리와 막다른 길이 되어 격자 블록이 나오지 않았다. 그래서 대로를
먼저 긋고 블록을 쪼갠다. 텐서장 길 생성(Chen et al. 2008, ProbableTrain MapGenerator)은 쓰지 않았고 코드도 옮기지 않았다.
"""
from __future__ import annotations

import math
import random
from typing import Callable, Optional

from . import blocks, geom
from .geom import Point, Poly
from .placekinds import to_era
from .schema import MapSpec

VERSION = 2
GENERATOR = "canon-modern"

OPTIONS = {  # 지도 만들기 칸 (towngen.OPTIONS 와 같은 모양. 길 모양 · 밭은 쓰지 않고, 호수 · 바다는 하천으로 본다)
    "size": {"small": "작음 (건물 400~900채)", "medium": "보통 (650~1,350채)", "large": "큼 (1,550~2,300채)"},  # 물 둘 × 시드 30개씩 재 본 범위
    "water": {"none": "없음", "river": "하천"},
    "forest": {"few": "적음", "some": "보통", "many": "많음"},
}
GRID = {"small": (3, 3), "medium": (4, 3), "large": (5, 4)}  # 슈퍼블록 가로 × 세로 (가장자리 줄은 지도 끝에서 잘린 조각)
BLOCK = (300.0, 450.0)  # 슈퍼블록 한 변 (m)
EDGE = (0.45, 0.7)  # 가장자리 슈퍼블록은 이만큼만 지도에 든다
SWAY = 14.0  # 대로 끝을 흔드는 폭 (m). 줄이 1~2° 기운다
AVENUE = (20.0, 25.0)  # 대로 폭 (m)
BOULEVARD = (35.0, 40.0)  # 가운데 대로 폭
WALK = 1.0  # 길 가장자리에서 블록까지 (보도)
RIVER = (24.0, 34.0)  # 하천 폭
BANK = 12.0  # 하천 둔치 (풀밭)
RIVERSIDE = 8.0  # 둔치 바깥 강변길 폭
APT_SHARE = 0.4  # 역 · 공원이 아닌 슈퍼블록 가운데 아파트 단지
PARKS = {"few": 0, "some": 1, "many": 2}  # 근린공원 슈퍼블록 수
POCKET = {"few": 0.02, "some": 0.05, "many": 0.1}  # 빌라 블록이 어린이공원이 될 확률
SCHOOL_AREA = (9000.0, 24000.0)  # 학교 터 넓이 (m²)
CELLS_PER_SCHOOL = 6
SCHOOL_GAP = 400.0  # 학교끼리 이만큼 떨어진다 (m)
# 블록 쪼개기: (블록 넓이 m², 단계별 길 폭 m, 필지 앞 폭 m, 필지 깊이 m)
DIVIDE = {"villa": (4600.0, (10.0, 8.0, 8.0, 6.0), (10.0, 15.0), 22.0),
          "commercial": (7000.0, (12.0, 10.0, 8.0), (16.0, 28.0), 30.0)}
STRIP = ((12.0, 20.0), 24.0)  # 아파트 단지 앞 대로변 상가 띠: 필지 앞 폭, 깊이
COMPLEX_ROAD = 10.0  # 단지 안 길 폭
BUFFER = 6.0  # 단지 담장 안쪽 녹지

ZONES = {"station": "역 앞", "apartment": "아파트 단지", "villa": "빌라촌", "school": "학교", "park": "공원"}
# 쓰임 (bldgs.MODERN id) 고르기: 묶음 → [(쓰임, 무게)]
SHOPS = {"strip": [("store", 5), ("restaurant", 5), ("cafe", 3), ("convenience", 2), ("pharmacy", 1), ("academy", 3),
                   ("bank", 1), ("hospital", 1), ("salon", 2), ("company", 2), ("building", 3)],
         "commercial": [("company", 6), ("restaurant", 4), ("cafe", 3), ("academy", 3), ("bank", 2), ("hospital", 2),
                        ("store", 3), ("building", 3), ("hotel", 1)],
         "corner": [("store", 3), ("convenience", 3), ("restaurant", 2), ("cafe", 2), ("laundry", 1), ("salon", 1),
                    ("academy", 1)]}
# 동네에 몇 개씩 두는 공공 · 큰 시설: (쓰임, 지도 크기별 수 (작음, 보통, 큼), 바라는 자리)
CIVIC = [("government", (1, 1, 2), "strip"), ("police", (1, 1, 1), "strip"), ("post", (1, 1, 1), "strip"),
         ("library", (0, 1, 1), "villa"), ("fire", (0, 0, 1), "strip"), ("mart", (1, 1, 2), "big"),
         ("department", (0, 0, 1), "big"), ("fuel", (1, 1, 2), "strip"), ("church", (2, 4, 7), "villa"),
         ("kinder", (2, 3, 5), "villa"), ("gym", (0, 1, 1), "strip")]
# 현대 장소 종류(placekinds.kind_ids("modern"))가 이 동네에서 놓이는 자리 (_place_spots)
KIND_SPOTS = {"station": "역 앞 광장", "convenience": "편의점 (대로변 · 골목 모퉁이 가게)", "cafe": "카페 (역에 가까운 상가)",
              "restaurant": "식당 (역에 가까운 상가)", "mart": "마트 · 상가", "school": "학교 교사",
              "academy": "학원 (역에 가까운 상가)", "hospital": "병원 (역에 가까운 상가)", "police": "경찰서 (대로변)",
              "church": "교회", "company": "회사 (역 앞 사무실)", "factory": "동네 끝 대로변 가게 · 공장",
              "hotel": "호텔 · 모텔 · 역 앞 상가", "apartment": "아파트 단지 동", "villa": "빌라촌 빌라", "house": "단독주택",
              "park": "공원", "shore": "하천 둔치", "bridge": "하천 다리", "river": "하천 둔치", "pond": "공원 연못", "forest": "공원",
              "far": "동네 밖 (대로 끝)"}
# 장소가 놓인 건물의 쓰임 (bldgs.MODERN id). 상가 · 공공 종류만 바꾸고 사는 곳(아파트 · 빌라 · 집)과 학교 · 역은 그대로 둔다
USE_OF = {k: k for k in ("convenience", "cafe", "restaurant", "mart", "academy", "hospital", "police", "church", "company",
                         "factory", "hotel")}
NEED = {"shore": "물가가 없는 동네예요. 물을 하천으로 바꿔 보세요",
        "bridge": "다리가 없어요. 물을 하천으로 바꿔 보세요",
        "river": "하천이 없어요. 물을 하천으로 바꿔 보세요",
        "pond": "연못이 있는 공원이 없어요. 공원을 늘리거나 시드를 바꿔 보세요",
        "forest": "공원이 없어요. 공원을 늘려 보세요",
        "park": "공원이 없어요. 공원을 늘려 보세요",
        "school": "학교가 들어설 블록이 없어요. 크기를 키우거나 시드를 바꿔 보세요"}


def neighborhood(spec: MapSpec, places: list[dict]) -> dict:
    """현대 동네 지도 (read_layout 과 같은 모양 + wards, spots, missing, houses, numbers, parts, seed, retries).
    places: [{key, name, kind}] 이 지도에 놓을 이야기 장소 (kind 는 현대 장소 종류 id, 옛 id 는 placekinds.to_era 로 바꿔 읽는다).
    spots[].kind 는 현대 id 다.
    spec 가운데 size · water · forest 를 쓴다 (호수 · 바다는 하천으로 본다. roads · fields 는 쓰지 않는다)."""
    if spec.kind != "modern":
        raise ValueError("현대 동네 생성기는 현대 동네만 만들어요")
    for retry in range(4):
        out = _neighborhood(spec, places, str(spec.seed) + (f":retry{retry}" if retry else ""))
        if out is not None:
            out["retries"] = retry
            return out
    raise ValueError("동네를 만들지 못했어요. 시드를 바꿔 보세요")


# ---------- 길 ----------

class _Roads:
    """곧은 길 (가운데 선 a → b, 폭, 등급). 다른 길이 닿거나 건너는 점은 splits 에 (a→b 위 비율, 점)으로 넣어 꼭짓점을 나눠 쓴다.
    bridges: 다리로 그릴 비율 구간."""

    def __init__(self):
        self.items: list[dict] = []

    def add(self, a: Point, b: Point, width: float, cls: str) -> int:
        self.items.append({"a": a, "b": b, "width": width, "cls": cls, "splits": [], "bridges": []})
        return len(self.items) - 1

    def hit(self, k: int, p: Point, d: Point) -> Optional[tuple[float, Point]]:
        it = self.items[k]
        return blocks.line_hit(p, d, it["a"], it["b"])

    def mark(self, k: int, u: float, q: Point) -> None:
        self.items[k]["splits"].append((u, q))

    def runs(self, k: int) -> list[tuple[str, list[Point]]]:
        """꼭짓점을 차례로 이은 선을 길 · 다리 조각으로."""
        it = self.items[k]
        pts = [(0.0, it["a"])] + sorted(it["splits"]) + [(1.0, it["b"])]
        out: list[tuple[str, list[Point]]] = []
        for (u0, p), (u1, q) in zip(pts, pts[1:]):
            kind = "bridge" if any(a <= (u0 + u1) / 2 <= b for a, b in it["bridges"]) else "road"
            if out and out[-1][0] == kind:
                out[-1][1].append(q)
            else:
                out.append((kind, [p, q]))
        return out


def _half(P: Poly, T: list, p: Point, d: Point, off: float, sign: int, tag) -> tuple[Poly, list]:
    """직선 p + t·d 를 sign 쪽(1: d 의 왼쪽 법선 쪽)으로 off 만큼 민 선의 그쪽만 남긴다. 새 변 꼬리표는 tag."""
    a = (p[0] - d[1] * off * sign, p[1] + d[0] * off * sign)
    b = (a[0] + d[0], a[1] + d[1])
    return blocks.cut(P, T, a, b, tag) if sign > 0 else blocks.cut(P, T, b, a, tag)


def _side(p: Point, d: Point, q: Point) -> int:
    return 1 if d[0] * (q[1] - p[1]) - d[1] * (q[0] - p[0]) >= 0 else -1


def _frame(P: Poly) -> tuple[Point, Point]:
    """가장 긴 변 방향 ax 와 그 법선."""
    i = max(range(len(P)), key=lambda k: math.dist(P[k - 1], P[k]))
    ax = blocks.unit(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1])
    return ax, (-ax[1], ax[0])


def _extent(P: Poly, ax: Point) -> tuple[float, float]:
    proj = [q[0] * ax[0] + q[1] * ax[1] for q in P]
    return min(proj), max(proj)


def _road_cut(P: Poly, T: list, p: Point, d: Point, width: float, cls: str, roads: _Roads,
              min_area: float) -> Optional[tuple[tuple[Poly, list], tuple[Poly, list]]]:
    """블록을 p 를 지나 d 쪽으로 뻗는 새 길로 둘로 나눈다. 두 끝이 둘레 길의 가운데 선(또는 지도 끝)에 닿고 두 쪽이 min_area 보다
    크면 길을 roads 에 넣고 (왼쪽, 오른쪽) 블록, 아니면 아무것도 바꾸지 않고 None."""
    hits = blocks.crossings(P, p, d)
    if len(hits) != 2:
        return None
    ends = []
    for i, q in hits:
        tag = T[i]
        if tag[0] == "r":
            h = roads.hit(tag[1], p, d)
            if h is None or not 0.002 < h[0] < 0.998:
                return None
            ends.append((tag[1], h[0], h[1]))
        elif tag[0] == "b":
            ends.append((None, 0.0, q))
        else:
            return None
    k = len(roads.items)
    off = width / 2 + WALK
    left = _half(P, T, p, d, off, 1, ("r", k))
    right = _half(P, T, p, d, off, -1, ("r", k))
    if not left[0] or not right[0] or min(abs(geom.area(left[0])), abs(geom.area(right[0]))) < min_area:
        return None
    roads.add(ends[0][2], ends[1][2], width, cls)
    for j, u, q in ends:
        if j is not None:
            roads.mark(j, u, q)
    return left, right


def _divide(P: Poly, T: list, kind: str, roads: _Roads, r: random.Random,
            claim: Optional[Callable[[Poly, list], bool]] = None) -> list[tuple[Poly, list]]:
    """슈퍼블록을 긴 변에 거의 수직인 새 길로 되풀이해 잘라 블록 넓이(DIVIDE)에서 멈춘다. 앞 단계 길이 넓다(소로 → 골목).
    claim(블록) 이 True 이면 그 블록은 더 자르지 않고 빼낸다 (학교 터)."""
    target, widths, _, _ = DIVIDE[kind]
    out = []
    stack = [(P, T, 0)]
    while stack:
        pts, tags, lvl = stack.pop()
        if claim and claim(pts, tags):
            continue
        a_ = abs(geom.area(pts))
        if a_ < target * r.uniform(0.8, 1.3) or lvl > 9:
            out.append((pts, tags))
            continue
        ax, nrm = _frame(pts)
        lo, hi = _extent(pts, ax)
        c = geom.centroid(pts)
        width = widths[min(lvl, len(widths) - 1)]
        cls = "street" if width >= 8 else "lane"
        done = None
        for tries in range(4):
            th = r.uniform(-0.06, 0.06)
            d = (nrm[0] * math.cos(th) - nrm[1] * math.sin(th), nrm[0] * math.sin(th) + nrm[1] * math.cos(th))
            t = lo + (hi - lo) * r.uniform(0.4, 0.6)
            s = t - (c[0] * ax[0] + c[1] * ax[1])
            p = (c[0] + ax[0] * s, c[1] + ax[1] * s)
            done = _road_cut(pts, tags, p, d, width, cls, roads, 0.3 * target)
            if done:
                break
        if done:
            stack += [(*done[0], lvl + 1), (*done[1], lvl + 1)]
        else:
            out.append((pts, tags))
    return out


# ---------- 필지 · 건물 ----------

def _slices(P: Poly, T: list, ax: Point, step: Callable[[], float], last: float) -> list[tuple[Poly, list]]:
    """P 를 ax 에 수직인 선으로 차례로 자른 조각 (조각 폭은 step()). 남은 폭이 last 보다 좁으면 앞 조각에 붙인다."""
    d = (-ax[1], ax[0])
    lo, hi = _extent(P, ax)
    out: list[tuple[Poly, list]] = []
    t = lo
    rest, rt = P, T
    while rest:
        t += step()
        if t >= hi - last:
            out.append((rest, rt))
            break
        m = (ax[0] * t, ax[1] * t)
        piece, pt = blocks.cut(rest, rt, m, (m[0] + d[0], m[1] + d[1]), ("x",))
        rest, rt = blocks.cut(rest, rt, (m[0] + d[0], m[1] + d[1]), m, ("x",))
        if piece:
            out.append((piece, pt))
    return out


def _lots(P: Poly, T: list, front: tuple[float, float], depth: float, r: random.Random) -> list[tuple[Poly, list]]:
    """블록을 필지로: 두께가 깊이 두 배쯤이면 긴 변을 따라 두 줄로 나누고, 줄마다 앞 폭만큼 자른다. 길에 닿지 않은 필지는 뺀다."""
    ax, nrm = _frame(P)
    lo, hi = _extent(P, nrm)
    rows = [(P, T)]
    if hi - lo > 1.6 * depth:
        c = geom.centroid(P)
        rows = [_half(P, T, c, ax, 0, 1, ("x",)), _half(P, T, c, ax, 0, -1, ("x",))]
    out = []
    for rp, rt in rows:
        if not rp:
            continue
        for lot, lt in _slices(rp, rt, ax, lambda: r.uniform(*front), front[0] * 0.6):
            if abs(geom.area(lot)) > 60 and any(tg[0] in ("r", "b") for tg in lt):  # 지도 끝 필지는 지도 밖 길에 닿는다
                out.append((lot, lt))
    return out


def _building(lot: Poly, tags: list, front: float, side: float) -> Optional[Poly]:
    """필지에서 길 쪽은 front, 나머지는 side 만큼 물린 건물. 너무 작거나 가늘면 None."""
    poly, _ = blocks.inset(lot, tags, [front if tg[0] in ("r", "b") else side for tg in tags])
    if len(poly) < 3:
        return None
    a = abs(geom.area(poly))
    per = sum(math.dist(poly[k - 1], poly[k]) for k in range(len(poly)))
    return poly if a >= 36 and 2 * a / per >= 2.2 else None


def _rects(B: Poly, ax: Point, size: tuple[float, float], pitch: tuple[float, float], avoid: list[Poly],
           r: random.Random) -> list[Poly]:
    """B 안에 ax 방향 길이 size[0], 깊이 size[1] 인 직사각형을 pitch 간격 줄로 놓는다 (줄마다 0.3 칸 엇갈림).
    다 들어가지 않으면 길이를 0.7 배로 한 번 줄여 본다. avoid 와 6m 안이면 놓지 않는다."""
    nrm = (-ax[1], ax[0])
    ulo, uhi = _extent(B, ax)
    vlo, vhi = _extent(B, nrm)
    out: list[Poly] = []
    v = vlo + size[1] / 2 + r.uniform(1, pitch[1] - size[1])
    row = 0
    while v < vhi - size[1] / 2:
        u = ulo + size[0] / 2 + (pitch[0] * 0.3 if row % 2 else 0) + r.uniform(0, 6)
        while u < uhi:
            c = (ax[0] * u + nrm[0] * v, ax[1] * u + nrm[1] * v)
            for k in (1.0, 0.7):
                rc = geom.rect(c, nrm, size[0] * k, size[1])
                if all(geom.inside(q, B) for q in rc) and not any(geom.convex_overlap(rc, o, 6) for o in avoid + out):
                    out.append(rc)
                    break
            u += pitch[0]
        v += pitch[1]
        row += 1
    return out


def _pick(r: random.Random, table: list[tuple[str, int]]) -> str:
    x = r.uniform(0, sum(w for _, w in table))
    for use, w in table:
        x -= w
        if x <= 0:
            return use
    return table[-1][0]


# ---------- 동네 ----------

def _neighborhood(spec: MapSpec, places: list[dict], seed: str) -> Optional[dict]:
    rng = lambda stage: random.Random(f"{seed}:{stage}")  # noqa: E731
    size_i = ("small", "medium", "large").index(spec.size)
    nx, ny = GRID[spec.size]

    # 1. 대로 격자: 칸 폭, 줄 자리, 흔든 끝
    gr = rng("grid")
    cols = [gr.uniform(*BLOCK) for _ in range(nx)]
    rows = [gr.uniform(*BLOCK) for _ in range(ny)]
    for xs in (cols, rows):
        xs[0] *= gr.uniform(*EDGE)
        xs[-1] *= gr.uniform(*EDGE)
    w, h = sum(cols), sum(rows)
    xpos = [sum(cols[:i + 1]) for i in range(nx - 1)]
    ypos = [sum(rows[:j + 1]) for j in range(ny - 1)]
    roads = _Roads()
    vlines: list[dict] = []  # {k (길 번호, 하천이면 None), a, b, width, river}
    hlines: list[dict] = []
    river_j = None
    if spec.water != "none" and len(ypos) >= 1:
        river_j = min(range(len(ypos)), key=lambda j: (abs(ypos[j] - h / 2), j))
    rw = gr.uniform(*RIVER)
    mid_v = min(range(len(xpos)), key=lambda i: abs(xpos[i] - w / 2))
    mid_h = min((j for j in range(len(ypos)) if j != river_j), key=lambda j: abs(ypos[j] - h / 2), default=None)
    for i, x in enumerate(xpos):
        a, b = (x + gr.uniform(-SWAY, SWAY), 0.0), (x + gr.uniform(-SWAY, SWAY), h)
        wd = gr.uniform(*(BOULEVARD if i == mid_v else AVENUE))
        vlines.append({"k": roads.add(a, b, wd, "avenue"), "a": a, "b": b, "width": wd})
    for j, y in enumerate(ypos):
        a, b = (0.0, y + gr.uniform(-SWAY, SWAY)), (w, y + gr.uniform(-SWAY, SWAY))
        if j == river_j:
            d = blocks.unit(b[0] - a[0], b[1] - a[1])
            banks = {}
            for sgn in (1, -1):  # 둔치 바깥 양쪽 강변길 (지도 끝에서 끝까지)
                off = (rw / 2 + BANK + RIVERSIDE / 2) * sgn
                o = (a[0] - d[1] * off, a[1] + d[0] * off)
                ba = (0.0, o[1] - o[0] * d[1] / d[0])
                bb = (w, o[1] + (w - o[0]) * d[1] / d[0])
                banks[sgn] = {"k": roads.add(ba, bb, RIVERSIDE, "street"), "a": ba, "b": bb, "width": RIVERSIDE}
            hlines.append({"k": None, "a": a, "b": b, "width": rw, "river": True, "banks": banks})
            continue
        wd = gr.uniform(*(BOULEVARD if j == mid_h else AVENUE))
        hlines.append({"k": roads.add(a, b, wd, "avenue"), "a": a, "b": b, "width": wd})
    river = next((ln for ln in hlines if ln.get("river")), None)
    crossings: list[Point] = []  # 대로 교차점
    bridges: list[tuple[Point, Point]] = []
    for vl in vlines:
        dv = (vl["b"][0] - vl["a"][0], vl["b"][1] - vl["a"][1])
        for hl in hlines:
            dh = blocks.unit(hl["b"][0] - hl["a"][0], hl["b"][1] - hl["a"][1])
            if hl.get("river"):
                ends = []
                for sgn in (1, -1):  # 물가 두 점에서 다리로 바뀐다
                    off = rw / 2 + 1.5
                    o = (hl["a"][0] - dh[1] * off * sgn, hl["a"][1] + dh[0] * off * sgn)
                    hit = blocks.line_hit(o, dh, vl["a"], vl["b"])
                    if hit is None:
                        return None
                    roads.mark(vl["k"], *hit)
                    ends.append(hit)
                roads.items[vl["k"]]["bridges"].append((min(ends)[0], max(ends)[0]))
                bridges.append((ends[0][1], ends[1][1]))
                for bank in hl["banks"].values():
                    hit = blocks.line_hit(vl["a"], dv, bank["a"], bank["b"])
                    hv = blocks.line_hit(bank["a"], dh, vl["a"], vl["b"])
                    if hit is None or hv is None:
                        return None
                    roads.mark(bank["k"], hit[0], hit[1])
                    roads.mark(vl["k"], hv[0], hit[1])
                continue
            hit = blocks.line_hit(vl["a"], dv, hl["a"], hl["b"])
            if hit is None:
                return None
            u, q = hit
            roads.mark(hl["k"], u, q)
            hv = blocks.line_hit(hl["a"], dh, vl["a"], vl["b"])
            roads.mark(vl["k"], hv[0] if hv else 0.5, q)
            crossings.append(q)

    # 2. 슈퍼블록: 지도 네모를 둘레 대로 · 하천의 가운데 선으로 자른 모양(shape)과 길 폭만큼 줄인 블록(P, T)
    box = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)]
    cells: list[dict] = []
    for i in range(nx):
        for j in range(ny):
            c = ((([0.0] + xpos)[i] + (xpos + [w])[i]) / 2, (([0.0] + ypos)[j] + (ypos + [h])[j]) / 2)
            shape, st = list(box), [("b",)] * 4
            P, T = list(box), [("b",)] * 4
            bounds = ([vlines[i - 1]] if i > 0 else []) + ([vlines[i]] if i < nx - 1 else []) + \
                     ([hlines[j - 1]] if j > 0 else []) + ([hlines[j]] if j < ny - 1 else [])
            for ln in bounds:
                d = blocks.unit(ln["b"][0] - ln["a"][0], ln["b"][1] - ln["a"][1])
                sgn = _side(ln["a"], d, c)
                shape, st = _half(shape, st, ln["a"], d, 0, sgn, ("w",) if ln.get("river") else ("r", ln["k"]))
                if ln.get("river"):  # 하천 쪽 블록은 강변길에서 줄인다
                    ln = ln["banks"][sgn]
                    d = blocks.unit(ln["b"][0] - ln["a"][0], ln["b"][1] - ln["a"][1])
                P, T = _half(P, T, ln["a"], d, ln["width"] / 2 + WALK, sgn, ("r", ln["k"]))
            if not P:
                return None
            edge = i in (0, nx - 1) or j in (0, ny - 1)
            cells.append({"i": i, "j": j, "c": c, "shape": shape, "P": P, "T": T, "edge": edge,
                          "area": abs(geom.area(P)), "kind": ""})

    # 3. 슈퍼블록 종류: 역 앞(지도 가운데에 가장 가까운 대로 교차점의 가장 큰 칸), 공원(가장자리를 좋아함), 아파트 · 빌라
    kr = rng("kinds")
    center = (w / 2, h / 2)
    station = min(crossings, key=lambda q: math.dist(q, center)) if crossings else center
    around = sorted(cells, key=lambda cl: math.dist(geom.centroid(cl["P"]), station))[:4]
    max(around, key=lambda cl: cl["area"])["kind"] = "station"
    free = [cl for cl in cells if not cl["kind"]]
    for cl in sorted(free, key=lambda cl: -(cl["edge"] + kr.uniform(0, 0.9)))[:PARKS[spec.forest]]:
        cl["kind"] = "park"
    free = [cl for cl in cells if not cl["kind"]]
    mean = sum(cl["area"] for cl in free) / max(1, len(free))
    order = sorted(free, key=lambda cl: -(cl["area"] / mean + kr.uniform(0, 0.8) - 0.3 * cl["edge"]))
    n_apt = round(len(free) * APT_SHARE)
    if len(free) >= 2:
        n_apt = min(max(1, n_apt), len(free) - 1)
    for k, cl in enumerate(order):
        cl["kind"] = "apartment" if k < n_apt else "villa"
        cl["style"] = "tower" if kr.random() < 0.3 else "slab"

    # 4. 블록 쪼개기 · 필지 · 건물
    br = rng("blocks")
    tr = rng("trees")
    lots: list[dict] = []  # {poly, zone, corner, use, levels}
    wards: list[dict] = []
    squares: list[Poly] = []
    greens: list[Poly] = []
    water: list[Poly] = []
    trees: list[Point] = []
    ponds: list[Poly] = []
    parks: list[Poly] = []
    plaza: Optional[Poly] = None
    schools_left = max(1, round(len(cells) / CELLS_PER_SCHOOL))
    school_at: list[Point] = []
    east = next((blocks.unit(ln["b"][0] - ln["a"][0], ln["b"][1] - ln["a"][1]) for ln in hlines if not ln.get("river")), (1.0, 0.0))

    def avenue(tags: list) -> bool:
        return any(tg[0] == "r" and roads.items[tg[1]]["cls"] == "avenue" for tg in tags)

    def add_lots(pieces: list[tuple[Poly, list]], kind: str) -> None:
        _, _, front, depth = DIVIDE[kind]
        for P, T in pieces:
            for lot, lt in _lots(P, T, front, depth, br):
                strip = avenue(lt)
                zone = "strip" if strip and kind == "villa" else kind
                f, s = (2.0, 0.6) if zone == "villa" else (1.5, 0.4)
                poly = _building(lot, lt, f, s)
                if poly:
                    corner = sum(tg[0] == "r" for tg in lt) >= 2
                    lots.append({"poly": poly, "zone": zone, "corner": corner})

    def school_claim(P: Poly, T: list) -> bool:
        nonlocal schools_left
        a_ = abs(geom.area(P))
        if schools_left <= 0 or not SCHOOL_AREA[0] <= a_ <= SCHOOL_AREA[1] or br.random() < 0.3:
            return False
        if any(math.dist(geom.centroid(P), q) < SCHOOL_GAP for q in school_at):
            return False
        site, _ = blocks.inset(P, T, [3.0] * len(P))
        if not site:
            return False
        schools_left -= 1
        school_at.append(geom.centroid(P))
        greens.append(site)
        wards.append({"kind": "school", "shape": P})
        # 교사는 가장 북쪽(화면 위) 긴 변을 따라, 운동장은 그 남쪽에
        sc = geom.centroid(site)
        k = min((k for k in range(len(site)) if math.dist(site[k - 1], site[k]) >= 40),
                key=lambda k: site[k - 1][1] + site[k][1], default=0)
        a, b = site[k - 1], site[k]
        d = blocks.unit(b[0] - a[0], b[1] - a[1])
        mid = geom.lerp(a, b, 0.5)
        inward = (-d[1], d[0]) if (sc[0] - mid[0]) * -d[1] + (sc[1] - mid[1]) * d[0] > 0 else (d[1], -d[0])
        L = min(70.0, math.dist(a, b) * 0.8)
        at = lambda t: (mid[0] + inward[0] * t, mid[1] + inward[1] * t)  # noqa: E731
        hall = blocks.fit_rect(site, at(9.5), inward, L, 15, 1)
        if hall:
            lots.append({"poly": hall, "zone": "school", "corner": False, "use": "school",
                         "levels": br.randint(4, 5)})
        lo, hi = _extent(site, inward)
        fd = min(70.0, (hi - lo) - 15 - 14)
        field = blocks.fit_rect(site, at(23 + fd / 2), inward, L, fd, 2) if fd > 25 else None
        if field:
            squares.append(field)
        trees.extend(blocks.scatter(tr, site, 9, 0.25, [x for x in (hall, field) if x]))
        return True

    for cl in cells:
        P, T, kind = cl["P"], cl["T"], cl["kind"]
        wards.append({"kind": kind, "shape": cl["shape"]})
        if kind == "park":
            greens.append(P)
            parks.append(P)
            pond = None
            if tr.random() < 0.6:
                pc, s = geom.centroid(P), math.sqrt(cl["area"])
                ang0 = tr.uniform(0, math.pi)
                ring = [(pc[0] + math.cos(t) * s * 0.16 * math.cos(ang0) - math.sin(t) * s * 0.1 * math.sin(ang0),
                         pc[1] + math.cos(t) * s * 0.16 * math.sin(ang0) + math.sin(t) * s * 0.1 * math.cos(ang0))
                        for t in (k * 2 * math.pi / 24 for k in range(24))]
                if all(geom.inside(q, P) for q in ring):
                    pond = ring if geom.area(ring) > 0 else ring[::-1]
                    ponds.append(pond)
            trees += blocks.scatter(tr, P, 8, 0.8, [pond] if pond else [])
        elif kind == "station":
            pieces = _divide(P, T, "commercial", roads, br)
            k0 = min(range(len(pieces)), key=lambda k: math.dist(geom.centroid(pieces[k][0]), station))
            plaza = pieces.pop(k0)[0]
            squares.append(plaza)
            ax, nrm = _frame(plaza)
            pc = geom.centroid(plaza)
            hall = blocks.fit_rect(plaza, geom.lerp(pc, station, 0.25), nrm, 26, 12, 1.5)
            if hall:
                lots.append({"poly": hall, "zone": "station", "corner": False, "use": "station", "levels": 2})
            add_lots(pieces, "commercial")
        elif kind == "villa":
            pieces = _divide(P, T, "villa", roads, br, school_claim)
            keep = []
            for b in pieces:
                if not avenue(b[1]) and tr.random() < POCKET[spec.forest]:
                    greens.append(b[0])
                    trees += blocks.scatter(tr, b[0], 7, 0.6)
                else:
                    keep.append(b)
            add_lots(keep, "villa")
        else:  # 아파트 단지: 대로변 상가 띠, 단지 안 길, 동 배치
            cand = [k for k, tg in enumerate(T) if tg[0] == "r"]
            if cand and br.random() < 0.6:
                k = min(cand, key=lambda k: math.dist(geom.lerp(P[k], P[(k + 1) % len(P)], 0.5), station))
                d = blocks.unit(P[(k + 1) % len(P)][0] - P[k][0], P[(k + 1) % len(P)][1] - P[k][1])
                band = _half(P, T, P[k], d, -STRIP[1], -1, ("x",))  # 블록 안쪽은 d 의 왼쪽: 변에서 STRIP 안쪽 선의 바깥
                rest = _half(P, T, P[k], d, STRIP[1], 1, ("x",))
                if band[0] and rest[0]:
                    for lot, lt in _slices(band[0], band[1], d, lambda: br.uniform(*STRIP[0]), STRIP[0][0] * 0.6):
                        poly = _building(lot, lt, 1.5, 0.4)
                        if poly and any(tg[0] == "r" for tg in lt):
                            lots.append({"poly": poly, "zone": "strip", "corner": False})
                    P, T = rest
            halves = [(P, T)]
            ax, nrm = _frame(P)
            lo, hi = _extent(P, ax)
            if hi - lo > 220:
                c = geom.centroid(P)
                for d in (nrm, ax):
                    done = _road_cut(P, T, c, d, COMPLEX_ROAD, "street", roads, 6000)
                    if done:
                        halves = list(done)
                        break
            for H, HT in halves:
                B, _ = blocks.inset(H, HT, [BUFFER] * len(H))
                if not B:
                    continue
                extra: list[Poly] = []
                for k, tg in enumerate(HT):  # 단지 상가 · 어린이집: 길 쪽 변 가운데 안쪽
                    if tg[0] != "r" or len(extra) >= 2:
                        continue
                    a, b = H[k], H[(k + 1) % len(H)]
                    d = blocks.unit(b[0] - a[0], b[1] - a[1])
                    inward = (-d[1], d[0])
                    dep = 14 if not extra else 12
                    m = geom.lerp(a, b, br.uniform(0.3, 0.7))
                    c = (m[0] + inward[0] * (BUFFER + dep / 2 + 1), m[1] + inward[1] * (BUFFER + dep / 2 + 1))
                    rc = geom.rect(c, inward, 30 if not extra else 18, dep)
                    if all(geom.inside(q, B) for q in rc):
                        extra.append(rc)
                        lots.append({"poly": rc, "zone": "apartment", "corner": False,
                                     "use": "store" if len(extra) == 1 else "kinder", "levels": 2})
                if cl["style"] == "slab":
                    ln = br.uniform(60, 90)
                    dongs = _rects(B, east, (ln, br.uniform(12, 15)), (ln + br.uniform(16, 26), br.uniform(40, 50)), extra, br)
                    lv = (12, 25)
                else:
                    sz = br.uniform(22, 28)
                    dongs = _rects(B, east, (sz, sz), (br.uniform(46, 56), br.uniform(46, 56)), extra, br)
                    lv = (20, 35)
                for dg in dongs:
                    lots.append({"poly": dg, "zone": "apartment", "corner": False,
                                 "use": "apartment", "levels": br.randint(*lv)})
                trees += blocks.scatter(tr, B, 11, 0.35, dongs + extra)

    # 5. 하천: 물 · 둔치 띠 (다리는 길에서 나눴다)
    rivers = []
    if river:
        d = blocks.unit(river["b"][0] - river["a"][0], river["b"][1] - river["a"][1])
        for half_w, out in ((rw / 2 + BANK, greens), (rw / 2, water)):
            nv = (-d[1] * half_w, d[0] * half_w)
            a, b = river["a"], river["b"]
            band = [(a[0] - nv[0], a[1] - nv[1]), (b[0] - nv[0], b[1] - nv[1]), (b[0] + nv[0], b[1] + nv[1]), (a[0] + nv[0], a[1] + nv[1])]
            band = band if geom.area(band) > 0 else band[::-1]
            cut = geom.clip_convex(band, box)
            if len(cut) >= 3:
                out.append(cut)
        rivers.append({"width": rw, "points": [river["a"], river["b"]]})

    # 6. 쓰임 · 층수
    ur = rng("uses")
    for lt in lots:
        lt["c"] = geom.centroid(lt["poly"])
        lt["area"] = abs(geom.area(lt["poly"]))
        near = math.exp(-math.dist(lt["c"], station) / 260)  # 역에 가까울수록 높다
        if lt.get("use"):
            continue
        zone = lt["zone"]
        if zone == "villa":
            if lt["corner"] and ur.random() < 0.35:
                lt["use"], lt["levels"] = _pick(ur, SHOPS["corner"]), ur.randint(3, 4)
            elif ur.random() < 0.18:
                lt["use"], lt["levels"] = "home", 2  # 단독주택
            else:
                lt["use"], lt["levels"] = "villa", ur.randint(4, 5)
        elif zone == "strip":
            lt["use"], lt["levels"] = _pick(ur, SHOPS["strip"]), ur.randint(3, 6) + round(4 * near)
        else:  # commercial
            lt["use"], lt["levels"] = _pick(ur, SHOPS["commercial"]), ur.randint(5, 9) + round(8 * near)
    generic = {"villa", "home", "store", "building", "restaurant", "cafe", "company", "convenience", "salon", "academy"}
    for use, counts, where in CIVIC:
        for _ in range(counts[size_i]):
            if where == "big":
                cand = [lt for lt in lots if lt["zone"] in ("commercial", "strip") and lt["use"] in generic]
                pick = max(cand, key=lambda lt: lt["area"] * (1 + math.exp(-math.dist(lt["c"], station) / 300)), default=None)
            else:
                cand = [lt for lt in lots if lt["zone"] == where and lt["use"] in generic]
                pick = ur.choice(cand) if cand else None
            if pick is None:
                continue
            pick["use"] = use
            pick["levels"] = {"church": 3, "kinder": 2, "fuel": 1, "mart": 3, "department": 8, "library": 3}.get(use, pick["levels"])

    # 7. 길: 대로, 소로, 골목 (하천 위는 다리)
    road_out: list[dict] = []
    for k in range(len(roads.items)):
        for kind, run in roads.runs(k):
            road_out.append({"kind": kind, "width": roads.items[k]["width"], "pts": run, "cls": roads.items[k]["cls"]})
    key = lambda q: (round(round(q[0] / w, 6) * w, 2), round(round(q[1] / h, 6) * h, 2))  # noqa: E731
    if len(blocks.parts(road_out, key)) != 1:  # 길이 한 덩어리인지 (atlas.road_graph 와 같은 반올림)
        return None

    # 8. 이야기 장소
    spots, missing = _place_spots(places, lots, plaza, station, ponds, parks, bridges, river, rw, vlines + hlines,
                                  rng("spots"), w, h)

    nx_ = lambda q: [round(q[0] / w, 6), round(q[1] / h, 6)]  # noqa: E731
    parts = [{"lot": k, "part": "main", "zone": lt["zone"], "use": lt["use"], "levels": lt["levels"]} for k, lt in enumerate(lots)]
    return {
        "w": w, "h": h, "generator": GENERATOR, "version": str(VERSION), "seed": spec.seed,
        "roads": [{"kind": rd["kind"], "width": round(rd["width"], 2), "points": [nx_(q) for q in rd["pts"]]} for rd in road_out],
        "buildings": [[nx_(q) for q in lt["poly"]] for lt in lots],
        "water": [[nx_(q) for q in poly] for poly in water + ponds],
        "rivers": [{"width": round(rv["width"], 2), "points": [nx_(q) for q in rv["points"]]} for rv in rivers],
        "walls": [], "gates": [],
        "squares": [[nx_(q) for q in sq] for sq in squares],
        "fields": [],
        "greens": [[nx_(q) for q in poly] for poly in greens],
        "trees": [nx_(q) for q in trees],
        "wards": [{"kind": wd["kind"], "shape": [nx_(q) for q in wd["shape"]]} for wd in wards],
        "spots": [{"key": sp["key"], "name": sp["name"], "kind": sp["kind"], "x": nx_(sp["at"])[0], "y": nx_(sp["at"])[1]}
                  for sp in spots],
        "missing": missing,
        "houses": len(lots), "numbers": list(range(len(lots))), "parts": parts,
    }


def _place_spots(places: list[dict], lots: list[dict], plaza: Optional[Poly], station: Point, ponds: list[Poly],
                 parks: list[Poly], bridges: list[tuple[Point, Point]], river: Optional[dict], rw: float,
                 lines: list[dict], r: random.Random, w: float, h: float) -> tuple[list[dict], list[dict]]:
    """이야기 장소마다 자리 (KIND_SPOTS). 종류는 현대 id 로 읽는다: 옛 id 는 placekinds.to_era 로 바꾸고, 대응이 없거나 모르는 id 는 집.
    역 → 역 앞 광장, 시장 · 마트 → 마트, 교회 → 교회, 호텔 → 호텔 · 역 앞 상가, 공장 → 동네 끝 대로변 가게 (옛 가운데 · 장터 · 신전 ·
    주막 · 대장간 · 방앗간과 같은 규칙), 상가 종류 → 같은 쓰임 건물이나 대로변 상가, 학교 → 학교 교사, 아파트 · 빌라 → 그 쓰임 건물,
    집 → 단독주택, 공원 · 숲 → 공원, 나루 · 강가 → 하천 둔치, 다리 → 다리 가운데, 호수 → 공원 연못, 마을 밖 → 대로 끝 (지도 가장자리).
    건물이 필요한 종류는 건물을 하나씩 차지하고, 가게 종류(USE_OF)는 그 건물의 쓰임을 장소 종류로 바꾼다."""
    spots: list[dict] = []
    missing: list[dict] = []
    used_pts: list[Point] = []
    taken: set[int] = set()
    plaza_c = geom.centroid(plaza) if plaza else station
    ends = [q for ln in lines if ln["k"] is not None for q in (ln["a"], ln["b"])]
    far_i = 0

    def lot(ok: Callable[[dict], bool], score: Callable[[dict], float]) -> Optional[int]:
        cand = [i for i, lt in enumerate(lots) if i not in taken and ok(lt)]
        spaced = [i for i in cand if all(math.dist(lots[i]["c"], u) > 30 for u in used_pts)]
        if not cand:
            return None
        i = min(spaced or cand, key=lambda k: score(lots[k]) + r.uniform(0, 1e-6))
        taken.add(i)
        return i

    def first(*picks: Callable[[], Optional[int]]) -> Optional[int]:
        for pick in picks:
            i = pick()
            if i is not None:
                return i
        return None

    def point_at(q: Point) -> Point:
        while any(math.dist(q, u) < 6 for u in used_pts):
            q = (q[0] + 9, q[1] + 3)
        return q

    def bank() -> Point:
        d = blocks.unit(river["b"][0] - river["a"][0], river["b"][1] - river["a"][1])
        t = (station[0] - river["a"][0]) * d[0] + (station[1] - river["a"][1]) * d[1] + 40  # 역에서 가까운 물가 (다리 옆)
        m = (river["a"][0] + d[0] * t, river["a"][1] + d[1] * t)
        sgn = _side(river["a"], d, station)
        return point_at((m[0] - d[1] * (rw / 2 + BANK / 2) * sgn, m[1] + d[0] * (rw / 2 + BANK / 2) * sgn))

    dist_st = lambda lt: math.dist(lt["c"], station)  # noqa: E731
    near = lambda zones: lambda: lot(lambda lt: lt["zone"] in zones, dist_st)  # noqa: E731
    use = lambda *uses, score=dist_st: lambda: lot(lambda lt: lt["use"] in uses, score)  # noqa: E731
    shop = lambda lt: lt["zone"] == "strip" or (lt["zone"] == "villa" and lt["corner"] and lt["use"] not in ("villa", "home"))  # noqa: E731
    for pl in places:
        kind = to_era(pl["kind"], "modern") or "house"
        i: Optional[int] = None
        at: Optional[Point] = None
        reason = ""
        if kind == "station":
            at = point_at(plaza_c)
        elif kind == "mart":
            i = first(use("mart", "department"), near(("strip", "commercial")))
        elif kind == "church":
            i = first(use("church"), lambda: lot(lambda lt: lt["zone"] == "villa", lambda lt: r.random()))
        elif kind == "hotel":
            i = first(use("hotel"), near(("commercial", "strip")))
        elif kind == "factory":
            i = lot(lambda lt: lt["zone"] in ("strip", "villa") and lt["use"] not in ("villa", "home"), lambda lt: -dist_st(lt))
        elif kind == "convenience":
            i = first(use("convenience"), lambda: lot(shop, dist_st))
        elif kind in ("cafe", "restaurant", "academy", "hospital", "company"):
            i = first(use(kind), near(("strip", "commercial")))
        elif kind == "police":
            i = first(use("police"), near(("strip",)))
        elif kind == "school":
            i = use("school")()
            reason = "" if i is not None else NEED["school"]
        elif kind in ("apartment", "villa"):
            i = use(kind, score=lambda lt: r.random())()
        elif kind == "house":
            i = first(use("home", score=lambda lt: r.random()), use("villa", score=lambda lt: r.random()))
        elif kind == "shore" or kind == "river":
            if river:
                at = bank()
            else:
                reason = NEED[kind]
        elif kind == "bridge":
            if bridges:
                a, b = min(bridges, key=lambda ab: math.dist(geom.lerp(*ab, 0.5), station))
                at = point_at(geom.lerp(a, b, 0.5))
            else:
                reason = NEED["bridge"]
        elif kind == "pond":
            if ponds:
                at = point_at(geom.centroid(ponds[0]))
            else:
                reason = NEED["pond"]
        elif kind in ("park", "forest"):
            if parks:
                at = point_at(geom.centroid(min(parks, key=lambda g: math.dist(geom.centroid(g), station))))
            else:
                reason = NEED[kind]
        elif kind == "far":
            if ends:
                q = sorted(ends)[far_i % len(ends)]
                far_i += 1
                at = point_at((min(max(q[0], 4.0), w - 4), min(max(q[1], 4.0), h - 4)))
        if i is not None:
            at = lots[i]["c"]
            if kind in USE_OF:
                lots[i]["use"] = USE_OF[kind]
        if at is None:
            missing.append({"key": pl["key"], "name": pl["name"], "reason": reason or "놓을 건물이 남지 않았어요. 크기를 키워 보세요"})
            continue
        used_pts.append(at)
        spots.append({"key": pl["key"], "name": pl["name"], "kind": kind, "at": at})
    return spots, missing

"""쇠맛 실험실(soelab)의 통계. 표준 라이브러리만 쓰고 난수는 늘 시드로 정한다 (같은 입력 · 같은 시드면 같은 범위).

- 가르는 힘(auroc): Mann–Whitney U 를 짝 수로 나눈 값. 동점은 0.5. pos 가 neg 보다 클 확률이다.
- 범위(cluster_boot · auroc_boot): 묶음(같은 화 · 작품) 단위로 다시 뽑는 부트스트랩. 같은 묶음의 조각은 함께 뽑힌다.
- 판정 칩(verdict): 동시 구간의 하한 · 상한과 값으로 정한다. static/soelab.js 의 soeVerdict 와 같은 규칙이다 (PR3).
- 판정 일관성(kappa · kappa_boot): Cohen κ. '모르겠어요'도 한 갈래로 센다.
- 정밀도 · 재현율 · 같은 방향 비율(wilson · pair_agree): Wilson 구간.
- 우연일 가능성(sign_test · holm): 양측 부호 검정과 Holm 보정.
LLM 호출 없음.
"""
from __future__ import annotations

import math
import random
from statistics import NormalDist
from typing import Callable, Optional, Sequence

BOOT = 2000           # 부트스트랩 반복. 500번이면 99.64% 하한이 거칠고 위로 치우친다 (명세 4.6 검토)
METRIC_COUNT = 14     # 칩을 다는 지표 수. 동시 구간은 Bonferroni 로 1 - 0.05 / 14
SIM_LEVEL = 1 - 0.05 / METRIC_COUNT   # 99.64%
SHOW_LEVEL = 0.95     # 표에 숫자로 보이는 범위
STRONG = 0.7          # 하한이 0.5 를 넘고 값이 이만큼이면 '맞아요'
KAPPA_HOLD = 0.3      # 판정 일관성 부트스트랩 하한이 이보다 낮으면 결론을 보류한다 (명세 4.6)
KAPPA_MIN = 30        # 재판정이 이보다 적으면 결론을 보류한다 (미리보기만)

VERDICTS: dict[str, str] = {"yes": "맞아요", "weak": "약해요", "none": "근거 없음", "reverse": "반대 방향"}


def verdict(lo: float, hi: float, value: float) -> str:
    """동시 구간 [lo, hi] 와 값으로 판정 칩 id. 하한 > 0.5 이고 값 ≥ 0.7 이면 yes, 하한 > 0.5 이고 값 < 0.7 이면 weak,
    상한 < 0.5 면 reverse, 구간이 0.5 에 걸치면 none."""
    if lo > 0.5:
        return "yes" if value >= STRONG else "weak"
    if hi < 0.5:
        return "reverse"
    return "none"


# ---------- 가르는 힘 ----------

def _h(a: float, b: float) -> float:
    return 1.0 if a > b else 0.5 if a == b else 0.0


def auroc(pos: Sequence[float], neg: Sequence[float]) -> Optional[float]:
    """pos 의 값이 neg 의 값보다 클 확률 (동점 0.5). 한쪽이 비면 None. 순위로 셈해 O(n log n)."""
    if not pos or not neg:
        return None
    vals = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    rank_sum, i = 0.0, 0
    while i < len(vals):
        j = i
        while j < len(vals) and vals[j][0] == vals[i][0]:
            j += 1
        avg = (i + 1 + j) / 2  # 동점은 평균 순위
        rank_sum += avg * sum(1 for k in range(i, j) if vals[k][1])
        i = j
    n1, n0 = len(pos), len(neg)
    return (rank_sum - n1 * (n1 + 1) / 2) / (n1 * n0)


def roc_points(pos: Sequence[float], neg: Sequence[float]) -> list[tuple[float, float]]:
    """가르는 힘 곡선의 점 (거짓 경보 비율, 잡은 비율). 문턱을 큰 값에서 작은 값으로 내리며 '이 값 이상이면 pos'."""
    if not pos or not neg:
        return []
    out = [(0.0, 0.0)]
    for t in sorted(set(pos) | set(neg), reverse=True):
        out.append((sum(v >= t for v in neg) / len(neg), sum(v >= t for v in pos) / len(pos)))
    return out


# ---------- 묶음 부트스트랩 ----------

def boot_weights(keys: Sequence[str], n: int = BOOT, seed: int = 7) -> list[dict[str, int]]:
    """묶음 열쇠를 다시 뽑은 횟수. 반복마다 {열쇠: 뽑힌 수}. 같은 열쇠 · 같은 시드면 같은 결과 (열쇠는 정렬해 쓴다)."""
    ks = sorted(set(keys))
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        w: dict[str, int] = {}
        for k in rng.choices(ks, k=len(ks)):
            w[k] = w.get(k, 0) + 1
        out.append(w)
    return out


def percentile(xs: Sequence[float], q: float) -> float:
    """0 ≤ q ≤ 1. 선형 보간."""
    s = sorted(xs)
    if not s:
        return math.nan
    at = q * (len(s) - 1)
    lo = math.floor(at)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (at - lo)


def interval(dist: Sequence[float], level: float) -> tuple[float, float]:
    a = (1 - level) / 2
    return percentile(dist, a), percentile(dist, 1 - a)


def cluster_boot(groups: dict[str, list], stat: Callable[[list], Optional[float]], n: int = BOOT, seed: int = 7,
                 weights: Optional[list[dict[str, int]]] = None) -> list[float]:
    """묶음 부트스트랩 분포. groups 는 {묶음: [항목]}, stat 은 항목 목록 → 값(None 이면 그 반복을 버림).
    다시 뽑힌 묶음의 항목은 뽑힌 수만큼 되풀이해 넣는다. weights 를 주면 그 뽑기를 쓴다(지표끼리 같은 뽑기)."""
    ws = weights if weights is not None else boot_weights(list(groups), n, seed)
    out = []
    for w in ws:
        items = [x for k, c in w.items() if k in groups for _ in range(c) for x in groups[k]]
        v = stat(items)
        if v is not None:
            out.append(v)
    return out


def auroc_boot(pos: dict[str, list[float]], neg: dict[str, list[float]], n: int = BOOT, seed: int = 7,
               weights: Optional[list[dict[str, int]]] = None) -> list[float]:
    """가르는 힘의 묶음 부트스트랩 분포. pos · neg 는 {묶음: [값]} (한 묶음에 양쪽이 다 있어도 된다).
    묶음 쌍마다 비교 합을 미리 셈해 두고 반복마다 뽑힌 수로 가중 합만 한다 (cluster_boot 와 같은 분포, 더 빠름)."""
    pk, nk = sorted(pos), sorted(neg)
    s = {(a, b): sum(_h(x, y) for x in pos[a] for y in neg[b]) for a in pk for b in nk}
    cnt = {(a, b): len(pos[a]) * len(neg[b]) for a in pk for b in nk}
    ws = weights if weights is not None else boot_weights(pk + nk, n, seed)
    out = []
    for w in ws:
        num = den = 0.0
        for a in pk:
            wa = w.get(a, 0)
            if not wa:
                continue
            for b in nk:
                wb = w.get(b, 0)
                if wb:
                    num += wa * wb * s[a, b]
                    den += wa * wb * cnt[a, b]
        if den:
            out.append(num / den)
    return out


# ---------- 비율 ----------

def wilson(k: int, n: int, level: float = 0.95) -> tuple[float, float]:
    """k/n 의 Wilson 구간. n 이 0 이면 (0, 1)."""
    if n <= 0:
        return 0.0, 1.0
    z = NormalDist().inv_cdf(1 - (1 - level) / 2)
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def pair_agree(diffs: Sequence[float], level: float = 0.95) -> dict:
    """짝마다 (기대한 쪽 값 − 다른 쪽 값) 의 부호. 0 은 빼고 센다. {agree, n, ratio, lo, hi}."""
    xs = [d for d in diffs if d != 0]
    k = sum(d > 0 for d in xs)
    lo, hi = wilson(k, len(xs), level)
    return {"agree": k, "n": len(xs), "ratio": k / len(xs) if xs else None, "lo": lo, "hi": hi, "ties": len(diffs) - len(xs)}


# ---------- 판정 일관성 ----------

def kappa(a: Sequence[str], b: Sequence[str]) -> Optional[float]:
    """Cohen κ. a · b 는 같은 길이의 갈래 목록. 비면 None. 우연 일치가 1 이면 완전히 같을 때만 1."""
    n = len(a)
    if not n or n != len(b):
        return None
    cats = sorted(set(a) | set(b))
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    if pe == 1:
        return 1.0 if po == 1 else 0.0
    return (po - pe) / (1 - pe)


def kappa_boot(pairs: Sequence[tuple[str, str]], n: int = BOOT, seed: int = 7, level: float = 0.95) -> tuple[float, float]:
    """재판정 짝을 다시 뽑는 부트스트랩 구간. 짝이 없으면 (nan, nan)."""
    if not pairs:
        return math.nan, math.nan
    rng = random.Random(seed)
    dist = []
    for _ in range(n):
        s = rng.choices(list(pairs), k=len(pairs))
        v = kappa([x for x, _ in s], [y for _, y in s])
        if v is not None:
            dist.append(v)
    return interval(dist, level)


# ---------- 그 밖 ----------

def sign_test(k: int, n: int) -> float:
    """양측 부호 검정 p. n 번 중 k 번 한쪽. 8 중 8 이면 2/256 = 0.0078125."""
    if n <= 0:
        return 1.0
    m = max(k, n - k)
    tail = sum(math.comb(n, i) for i in range(m, n + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def holm(ps: Sequence[float]) -> list[float]:
    """Holm 보정 p (입력 차례대로)."""
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    out = [0.0] * len(ps)
    run = 0.0
    for r, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - r) * ps[i]))
        out[i] = run
    return out


def _ranks(xs: Sequence[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j < len(order) and xs[order[j]] == xs[order[i]]:
            j += 1
        for k in range(i, j):
            r[order[k]] = (i + 1 + j) / 2
        i = j
    return r


def spearman(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    """순위 상관 ρ (동점은 평균 순위). 셋 아래거나 한쪽 값이 모두 같으면 None."""
    if len(x) != len(y) or len(x) < 3:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return sxy / (sx * sy) if sx and sy else None

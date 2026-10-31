"""쇠맛 실험실 통계 (canon/labstats.py): 손으로 셈한 값과 경계."""
import math

from canon import labstats as ls


def test_auroc_extremes_and_ties():
    assert ls.auroc([3, 4, 5], [0, 1, 2]) == 1.0
    assert ls.auroc([0, 1, 2], [3, 4, 5]) == 0.0
    assert ls.auroc([1, 1, 1], [1, 1, 1]) == 0.5
    # 동점은 0.5: (2>1)+(2=2)·0.5+(3>1)+(3>2) = 1 + 0.5 + 1 + 1 = 3.5, 짝 4개
    assert ls.auroc([2, 3], [1, 2]) == 3.5 / 4
    assert ls.auroc([], [1]) is None


def test_auroc_matches_pairwise():
    pos, neg = [0.3, 0.7, 0.7, 1.2, 0.1], [0.2, 0.7, 0.5, 0.05]
    brute = sum(1 if a > b else 0.5 if a == b else 0 for a in pos for b in neg) / (len(pos) * len(neg))
    assert math.isclose(ls.auroc(pos, neg), brute)


def test_sign_test():
    assert ls.sign_test(8, 8) == 0.0078125  # 2/256
    assert ls.sign_test(0, 8) == 0.0078125
    assert ls.sign_test(4, 8) == 1.0


def test_kappa_by_hand():
    # 10쌍: 일치 7 (ai 4, human 3). 첫 판정 ai 6 · human 4, 재판정 ai 5 · human 5.
    a = ["ai"] * 6 + ["human"] * 4
    b = ["ai"] * 4 + ["human"] * 2 + ["ai"] + ["human"] * 3
    po = 0.7
    pe = 0.6 * 0.5 + 0.4 * 0.5
    assert math.isclose(ls.kappa(a, b), (po - pe) / (1 - pe))  # 0.4
    assert ls.kappa(["ai"] * 3, ["ai"] * 3) == 1.0
    assert ls.kappa(["unsure", "ai"], ["unsure", "ai"]) == 1.0  # '모르겠어요'도 한 갈래
    assert ls.kappa([], []) is None


def test_same_seed_same_interval():
    pos = {f"a{i}": [i * 0.1, i * 0.1 + 0.05] for i in range(12)}
    neg = {f"h{i}": [i * 0.07] for i in range(12)}
    d1 = ls.auroc_boot(pos, neg, n=300, seed=3)
    d2 = ls.auroc_boot(pos, neg, n=300, seed=3)
    d3 = ls.auroc_boot(pos, neg, n=300, seed=4)
    assert d1 == d2 and d1 != d3
    assert ls.interval(d1, 0.95) == ls.interval(d2, 0.95)
    pairs = [("ai", "ai"), ("human", "ai"), ("unsure", "unsure"), ("ai", "ai"), ("human", "human")] * 4
    assert ls.kappa_boot(pairs, 300, 5) == ls.kappa_boot(pairs, 300, 5)


def test_auroc_boot_matches_generic_cluster_boot():
    pos = {"a": [1.0, 2.0], "b": [0.5], "c": [3.0, 0.2, 1.1]}
    neg = {"x": [0.4, 0.9], "y": [1.5], "c": [0.3]}  # 한 묶음에 양쪽이 다 있어도 된다
    w = ls.boot_weights(sorted(set(pos) | set(neg)), n=200, seed=9)
    fast = ls.auroc_boot(pos, neg, weights=w)
    groups = {k: [(1, v) for v in pos.get(k, [])] + [(0, v) for v in neg.get(k, [])] for k in set(pos) | set(neg)}

    def stat(items):
        return ls.auroc([v for s, v in items if s], [v for s, v in items if not s])
    slow = ls.cluster_boot(groups, stat, weights=w)
    assert len(fast) == len(slow) and all(math.isclose(x, y) for x, y in zip(fast, slow))


def test_verdict_boundaries():
    assert ls.SIM_LEVEL == 1 - 0.05 / 14
    assert ls.verdict(0.51, 0.9, 0.7) == "yes"
    assert ls.verdict(0.51, 0.9, 0.6999) == "weak"
    assert ls.verdict(0.5, 0.9, 0.8) == "none"  # 하한이 0.5 와 같으면 걸친다
    assert ls.verdict(0.2, 0.4999, 0.3) == "reverse"
    assert ls.verdict(0.2, 0.5, 0.3) == "none"


def test_wilson_pair_agree_spearman_holm():
    lo, hi = ls.wilson(8, 8)
    assert 0.67 < lo < 0.68 and hi == 1.0
    assert ls.wilson(0, 0) == (0.0, 1.0)
    r = ls.pair_agree([0.2, 0.1, -0.3, 0.0, 0.4])
    assert (r["agree"], r["n"], r["ties"]) == (3, 4, 1)
    assert math.isclose(ls.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
    assert math.isclose(ls.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
    assert ls.spearman([1, 1, 1], [1, 2, 3]) is None
    assert ls.holm([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]
    pts = ls.roc_points([2, 3], [1, 2])
    assert pts[0] == (0.0, 0.0) and pts[-1] == (1.0, 1.0)

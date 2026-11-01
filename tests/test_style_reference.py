"""문체 기준(_style_reference) 빠른 계산이 예전 계산과 같은 값을 내는지, 화면이 화마다 부를 만큼 빠른지."""
import time
from pathlib import Path
from statistics import mean, median

from canon import metrics

STORY = (Path(__file__).parent / "fixtures" / "revlab_story.txt").read_text(encoding="utf-8")


def _slow(text):
    """예전 계산 (조각마다 나머지 조각 중심을 처음부터 다시 구함)."""
    zs = [metrics._suffix_z(c) for c in metrics.style_chunks(text)]
    if len(zs) < metrics.STYLE_MIN_CHUNKS:
        return {}
    center = lambda rows: [mean(col) for col in zip(*rows)]  # noqa: E731
    spread = median(metrics._cos_dist(zs[i], center(zs[:i] + zs[i + 1:])) for i in range(len(zs)))
    return {"style_centroid": [round(x, 4) for x in center(zs)], "style_spread": round(spread, 4)}


def test_fast_reference_matches_the_old_one():
    for text in (STORY * 8, STORY * 15 + "\n\n짧은 문단 하나.", STORY * 40):
        metrics._reference.cache_clear()
        old, new = _slow(text), metrics._style_reference(text)
        assert new.keys() == old.keys() and abs(new["style_spread"] - old["style_spread"]) <= 1e-4
        assert max(abs(a - b) for a, b in zip(new["style_centroid"], old["style_centroid"])) <= 1e-4
    assert metrics._style_reference(STORY[:3000]) == {}  # 조각이 STYLE_MIN_CHUNKS 보다 적으면 기준이 없다


def test_reference_is_linear_and_cached():
    text = STORY * 120  # 약 10만 자
    metrics._reference.cache_clear()
    t = time.perf_counter()
    first = metrics._style_reference(text)
    took = time.perf_counter() - t
    assert took < 0.5, took  # 예전 계산은 같은 글에 0.2~1초, 화마다 되풀이했다
    first["style_centroid"].append(9.9)  # 돌려준 값을 고쳐도 기억해 둔 값은 그대로다
    t = time.perf_counter()
    again = metrics._style_reference(text)
    assert time.perf_counter() - t < 0.01 and len(again["style_centroid"]) == len(metrics.FEATURES)

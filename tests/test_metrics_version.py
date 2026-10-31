"""지표 판(metrics.METRICS_VERSION)을 지킨다.

상수 해시와 fixture 다섯 편(tests/fixtures/soelab/, 직접 지은 글)의 결과 스냅샷을 판마다 적어 둔다.
상수나 셈 로직이 바뀌어 같은 글의 값이 달라지면, METRICS_VERSION 을 올리고 스냅샷을 다시 만든다:

    CANON_METRICS_SNAPSHOT=1 CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_metrics_version.py

판을 올리지 않고 다시 만들려고 하면 시험이 실패한다(옛 판의 해시는 지우지 않는다).
"""
import hashlib
import json
import os
from pathlib import Path

import pytest

from canon import metrics

DIR = Path(__file__).parent / "fixtures" / "soelab"
SNAP = DIR / "metrics_snapshot.json"


def _texts() -> dict[str, str]:
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(DIR.glob("*.txt"))}


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def constants() -> dict:
    return {
        "AI_PATTERNS": [[n, rx.pattern, rx.flags, cap] for n, rx, cap in metrics.AI_PATTERNS],
        "DEFAULT_CLICHES": metrics.DEFAULT_CLICHES,
        "THRESHOLDS": {k: list(v) for k, v in metrics.THRESHOLDS.items()},
        "UPPER_ONLY": sorted(metrics.UPPER_ONLY),
        "COPY_SPAN": metrics.COPY_SPAN,
        "STYLE_DISTANCE_WARN": metrics.STYLE_DISTANCE_WARN,
        "_SENT_END": metrics._SENT_END.pattern,
    }


def results() -> dict:
    texts = _texts()
    joined = "\n\n".join(texts.values())
    base = metrics.measure(joined + "\n\n" + joined)  # 6,000자를 넘겨 문체 거리 기준까지 만든다
    passages = [texts["04"].split("\n\n")[0]]
    out = {}
    for name, text in texts.items():
        cur = metrics.measure(text)
        cur.style_distance = metrics.style_distance(base, text)
        out[name] = {
            "measure": cur.model_dump(exclude={"style_centroid"}),
            "pattern_counts": metrics.pattern_counts(text),
            "copied": metrics.copied_sentences(text, passages),
            "drift": metrics.drift(base, cur),
        }
    out["base"] = base.model_dump(exclude={"style_centroid"})
    out["base_centroid"] = _hash(base.style_centroid)
    return out


def _load() -> dict:
    return json.loads(SNAP.read_text(encoding="utf-8")) if SNAP.exists() else {"versions": {}}


@pytest.mark.skipif(not os.environ.get("CANON_METRICS_SNAPSHOT"), reason="스냅샷을 다시 만들 때만")
def test_write_snapshot():
    snap = _load()
    now = {"constants": _hash(constants()), "results": _hash(results())}
    had = snap["versions"].get(metrics.METRICS_VERSION)
    assert had in (None, now), f"값이 바뀌었어요. METRICS_VERSION({metrics.METRICS_VERSION})을 올린 뒤 다시 만들어 주세요"
    snap["versions"][metrics.METRICS_VERSION] = now
    snap["current"] = metrics.METRICS_VERSION
    snap["results"] = results()
    SNAP.write_text(json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def test_version_matches_snapshot():
    snap = _load()
    assert snap.get("current") == metrics.METRICS_VERSION, "METRICS_VERSION 을 올렸으면 스냅샷을 다시 만들어 주세요"
    entry = snap["versions"][metrics.METRICS_VERSION]
    assert _hash(constants()) == entry["constants"], "지표 상수가 바뀌었어요. METRICS_VERSION 을 올려 주세요"
    assert results() == snap["results"], "같은 글의 지표 값이 바뀌었어요. METRICS_VERSION 을 올려 주세요"
    assert _hash(results()) == entry["results"]


def test_old_versions_kept_distinct():
    # 한 번 적은 판은 지우지 않고, 판마다 결과가 달라야 판을 올린 뜻이 있다
    vs = _load()["versions"]
    assert metrics.METRICS_VERSION in vs
    assert len({(v["constants"], v["results"]) for v in vs.values()}) == len(vs)


def test_pattern_spans_sum_to_counts():
    for name, text in _texts().items():
        spans = metrics.pattern_spans(text)
        counts = metrics.pattern_counts(text)
        assert sum(s.kind == "pattern" for s in spans) == sum(counts.values()), name
        assert counts == {n: len(rx.findall(text)) for n, rx, _ in metrics.AI_PATTERNS}, name
        for s in spans:
            assert text[s.start:s.end] == s.quote
        cliches = {s.name for s in spans if s.kind == "cliche"}
        assert cliches == set(metrics.measure(text).cliche_hits), name


def test_pattern_spans_order_and_banned():
    text = "그것은 단순한 꿈이 아니었다. 그는 숨을 내쉬었다 — 그리고 또 숨을 내쉬었다. 푸른 별."
    spans = metrics.pattern_spans(text, banned=["푸른 별"])
    assert [s.start for s in spans] == sorted(s.start for s in spans)
    assert sum(s.name == "숨을 내쉬었다" for s in spans) == 2
    assert any(s.kind == "cliche" and s.name == "푸른 별" for s in spans)
    assert any(s.name == "서식 흔적" for s in spans)


def test_sentence_spans_match_sentences():
    samples = list(_texts().values()) + ["", "  한 문장.  ", "\"말했다.\" 그리고 갔다!\n\n…끝?  "]
    for text in samples:
        assert [text[a:b] for a, b in metrics.sentence_spans(text)] == metrics.sentences(text)


def test_rates_per_1k_has_no_cap():
    text = "— " * 10 + "가" * 980
    r = metrics.rates_per_1k(text)
    assert r["서식 흔적"] == round(10 * 1000 / len(text.strip()), 3)
    assert r["ai_patterns"] == r["서식 흔적"]
    assert metrics.rates_per_1k("   ") == {}

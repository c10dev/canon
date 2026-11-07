"""대사의 꼴 지표: 물결표 대사 줄 비율 · 대사 한 줄 평균 길이 (metrics._dialogue_shape, drift, 문체 화면 baselineItems)."""
from canon import metrics

from .jsvm import needs_node, run_js


def _text(lines: list[str], narration: str = "그는 창밖을 보았다.") -> str:
    return "\n\n".join(x for line in lines for x in (narration, line))


def test_measure_counts_tilde_lines_and_length():
    lines = ['"왔어~?"', '"응."', "“그래, 앉아.”", "「싫어~」", '"뭐 해?"'] * 2
    m = metrics.measure(_text(lines))
    assert m.dialogue_tilde_ratio == 0.4
    assert m.dialogue_line_len == round(sum(len(x) for x in lines) / len(lines), 1)


def test_single_quote_lines_are_not_dialogue():
    lines = ['"좋아."'] * 10 + ["'설마~'"] * 10
    m = metrics.measure(_text(lines))
    assert m.dialogue_tilde_ratio == 0.0
    assert m.dialogue_line_len == 5.0


def test_too_few_dialogue_lines_not_measured():
    m = metrics.measure(_text(['"응~"'] * (metrics.DIALOGUE_MIN - 1)))
    assert m.dialogue_tilde_ratio is None and m.dialogue_line_len is None


def test_drift_warns_on_tilde_and_long_lines():
    base = metrics.measure(_text(['"그래."', '"가자."'] * 6))
    cur = metrics.measure(_text(['"아영아~ 오늘도 그 치마 입고 왔네~ 다들 보라고 입은 거지?"'] * 12))
    warns = metrics.drift(base, cur)
    assert any(w.startswith("물결표 대사 줄 비율:") for w in warns)
    assert any(w.startswith("대사 한 줄 평균 길이:") for w in warns)
    assert not [w for w in metrics.drift(cur, cur) if w.startswith(("물결표", "대사 한 줄"))]


def test_old_baseline_without_dialogue_shape_has_no_warning():
    old = metrics.StyleMetrics.model_validate({"chars": 100, "sentence_len_mean": 20, "dialogue_ratio": 0.3})
    assert old.dialogue_tilde_ratio is None and old.dialogue_line_len is None
    cur = metrics.measure(_text(['"아영아~ 오늘도 그 치마 입고 왔네~"'] * 12))
    assert not [w for w in metrics.drift(old, cur) if w.startswith(("물결표", "대사 한 줄"))]


@needs_node
def test_baseline_items_show_dialogue_shape():
    files = ["app.js", "setup.js", "chat.js", "passage.js", "marks.js", "style.js"]
    b = metrics.measure(_text(['"왔어~?"', '"응."'] * 6)).model_dump()
    got = run_js(files, "({ long: baselineItems(data, true), short: baselineItems(data).map((r) => r[0]),"
                        " none: baselineItems({ ...data, dialogue_tilde_ratio: null, dialogue_line_len: null }, true) })", b)
    assert len(got["short"]) == len(got["long"])
    rows = {r[0]: r[1] for r in got["long"]}
    assert rows["물결표 대사 줄"] == "50%"
    assert rows["대사 한 줄 길이"] == f"{round(b['dialogue_line_len'])}자"
    none = {r[0]: r[1] for r in got["none"]}
    assert none["물결표 대사 줄"] == "–" and none["대사 한 줄 길이"] == "–"
    assert "물결표 대사" in got["short"] and "대사 길이" in got["short"]

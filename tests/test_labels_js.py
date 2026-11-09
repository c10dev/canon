"""화면이 따로 들고 있는 칸 이름 · 스킨 · 온기 구간이 서버 표와 같은지. node 가 있을 때만 돈다.
charlog.js SC_LABELS ↔ charlog.LOG_FIELDS, statwin.js SW_SKINS ↔ statwin.SKINS,
stylechat.js STYLE_KEYS · STYLE_LISTS ↔ pipeline.STYLE_KEYS · STYLE_LIST_KEYS · agent_style.STYLE_LABELS,
cast.js warmthColor 구간 ↔ dynamics.warmth_word.
서버 표 pipeline.STYLE_KEYS 는 원본 schema.StyleProfile 과 맞춰 본다 (node 없이 돈다)."""
from typing import get_args, get_origin

from canon import agent_style, charlog, dynamics, pipeline, statwin
from canon.schema import StyleProfile

from .jsvm import needs_node, run_js

FILES = ["app.js", "chat.js", "charlog.js", "statwin.js", "cast.js", "stylechat.js"]


@needs_node
def test_labels_match_server():
    got = run_js(FILES, "({ sc: SC_LABELS, sw: SW_SKINS, style: STYLE_KEYS, lists: STYLE_LISTS })", None)
    assert got["sc"] == charlog.LOG_FIELDS
    assert got["sw"] == {k: v.split(":")[0] for k, v in statwin.SKINS.items()}
    assert [k for k, _ in got["style"]] == list(pipeline.STYLE_KEYS)
    assert dict(got["style"]) == agent_style.STYLE_LABELS
    assert got["lists"] == list(pipeline.STYLE_LIST_KEYS)


def test_style_keys_match_schema():
    """StyleProfile 에 칸을 더하면 pipeline.STYLE_KEYS 에도 더해야 화면 목록 시험까지 이어진다."""
    fields = StyleProfile.model_fields
    assert [*pipeline.STYLE_KEYS, "sample_passages"] == list(fields)
    for key in pipeline.STYLE_TEXT_KEYS:
        assert fields[key].annotation is str, key
    for key in pipeline.STYLE_LIST_KEYS:
        assert get_origin(fields[key].annotation) is list and get_args(fields[key].annotation) == (str,), key


@needs_node
def test_warmth_bands_match_server():
    ws = [-1, -0.61, -0.6, -0.59, -0.2, -0.2001, 0, 0.1999, 0.2, 0.5, 0.6, 0.6001, 1]
    got = run_js(FILES, "data.map((w) => WARMTH_BANDS.find(([cut]) => w < cut)[2])", ws)
    assert got == [dynamics.warmth_word(w) for w in ws]
    assert len(set(got)) == 5

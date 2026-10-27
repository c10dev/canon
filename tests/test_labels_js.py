"""화면이 따로 들고 있는 칸 이름 · 스킨 · 온기 구간이 서버 표와 같은지. node 가 있을 때만 돈다.
charlog.js SC_LABELS ↔ charlog.LOG_FIELDS, statwin.js SW_SKINS ↔ statwin.SKINS,
stylechat.js STYLE_KEYS · STYLE_LISTS ↔ pipeline.STYLE_KEYS · STYLE_LIST_KEYS · prompts.STYLE_KEY_LABELS,
cast.js warmthColor 구간 ↔ dynamics.warmth_word."""
from canon import charlog, dynamics, pipeline, prompts, statwin

from .jsvm import needs_node, run_js

FILES = ["app.js", "chat.js", "charlog.js", "statwin.js", "cast.js", "stylechat.js"]


@needs_node
def test_labels_match_server():
    got = run_js(FILES, "({ sc: SC_LABELS, sw: SW_SKINS, style: STYLE_KEYS, lists: STYLE_LISTS })", None)
    assert got["sc"] == charlog.LOG_FIELDS
    assert got["sw"] == {k: v.split(":")[0] for k, v in statwin.SKINS.items()}
    assert [k for k, _ in got["style"]] == list(pipeline.STYLE_KEYS)
    assert dict(got["style"]) == prompts.STYLE_KEY_LABELS
    assert got["lists"] == list(pipeline.STYLE_LIST_KEYS)


@needs_node
def test_warmth_bands_match_server():
    ws = [-1, -0.61, -0.6, -0.59, -0.2, -0.2001, 0, 0.1999, 0.2, 0.5, 0.6, 0.6001, 1]
    got = run_js(FILES, "data.map((w) => WARMTH_BANDS.find(([cut]) => w < cut)[2])", ws)
    assert got == [dynamics.warmth_word(w) for w in ws]
    assert len(set(got)) == 5

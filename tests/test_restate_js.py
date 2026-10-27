"""반영 뒤 고친 화 알림(static/restate.js editedAfterFinal)이 pipeline.edited_after_final 과 같은지. node 가 있을 때만 돈다."""
import itertools

from canon import pipeline

from .jsvm import dump, episode, needs_node, run_js


@needs_node
def test_edited_after_final_matches_server():
    eps = [episode(1, status=s, text=t, final_text=f)
           for s, t, f in itertools.product(["draft", "written", "finalized"], ["", "본문", "고친 본문"], ["", "본문"])]
    got = run_js(["app.js", "restate.js"], "data.map(editedAfterFinal)", [dump(e) for e in eps])
    assert got == [pipeline.edited_after_final(e) for e in eps]
    assert got.count(True) == 2

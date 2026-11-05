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


DELTA = {"episode": 1, "summary": "요약", "basis": "b1", "new_facts": ["사실"], "new_places": [],
         "foreshadow_planted": [{"id": "fs-a", "description": "가"}, {"id": "fs-b", "description": "나"}],
         "foreshadow_clues": [{"foreshadow": "fs-a", "kind": "plant", "quote": "가 문장"},
                              {"foreshadow": "fs-b", "kind": "plant", "quote": "나 문장"},
                              {"foreshadow": "fs-a", "kind": "payoff", "quote": "가 회수"},
                              {"foreshadow": "fs-old", "kind": "plant", "quote": "옛 복선"}]}


@needs_node
def test_restate_body_keeps_clues_of_picked_plants():
    """다시 맞추기로 보내는 변경안은 고른 새 복선의 plant 근거 문장만 담는다 (pipeline.apply_restate 와 같은 규칙)."""
    got = run_js(["app.js", "restate.js"], "restateBody(data, {sum: true, f0: true, p0: false, p1: true})", DELTA)
    assert [f["id"] for f in got["foreshadow_planted"]] == ["fs-b"]
    assert got["foreshadow_clues"] == [{"foreshadow": "fs-b", "kind": "plant", "quote": "나 문장"}]


@needs_node
def test_apply_restate_resends_with_force_after_stale_confirm():
    """서버가 409 stale_delta 를 주면 작가에게 묻고, 확인하면 ?force=1 로 다시 보낸다. 취소하면 변경안을 남긴다."""
    expr = """(async () => {
      const out = {};
      for (const ok of [true, false]) {
        const calls = [], asks = [];
        S.name = 't'; S.project = {episodes: [], foreshadows: [], facts: []}; S.deltas = {1: structuredClone(data)};
        run = async (label, fn) => { try { await fn(); } catch (e) { calls.push('error:' + e.code); } };
        toast = () => {};
        askConfirm = async (text) => { asks.push(text); return ok; };
        api = async (m, path, body) => {
          calls.push(path);
          if (!path.includes('force')) throw Object.assign(new Error('본문을 또 고쳤어요'), {code: 'stale_delta'});
          return {episodes: []};
        };
        await actions.applyRestate(1);
        out[ok] = {calls, asks: asks.length, kept: !!S.deltas[1]};
      }
      return out;
    })()"""
    got = run_js(["app.js", "restate.js"], expr, DELTA)
    assert got["true"] == {"calls": ["/projects/t/episodes/1/restate", "/projects/t/episodes/1/restate?force=1"], "asks": 1, "kept": False}
    assert got["false"] == {"calls": ["/projects/t/episodes/1/restate"], "asks": 1, "kept": True}

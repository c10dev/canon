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


@needs_node
def test_restate_again_asks_before_dropping_picks_and_lets_start_job_ask_to_save():
    """'다시 뽑기'는 바꾼 체크 · 고친 요약이 있으면 먼저 묻고, 작품 저장은 말없이 하지 않고 startJob 에 맡긴다."""
    got = run_js(["app.js", "restate.js"], """(async () => {
      const calls = [];
      askConfirm = async (msg, o) => { calls.push(['ask', o.ok]); return data.yes; };
      save = async () => { calls.push(['save']); S.dirty = false; };
      startJob = async (kind, n) => { calls.push(['job', kind, n, S.dirty]); };
      const d = { summary: '새 요약', new_facts: ['문이 열렸다'], foreshadow_planted: [], new_places: [] };
      S.project = { facts: [], foreshadows: [], episodes: [], relationships: [] };
      S.deltas = { 2: d };
      S.deltaOrig = { 2: { summary: '새 요약' } };
      const out = {};
      rsPicks(2);
      S.dirty = true;
      await actions.restateEp('2');  // 고친 것이 없다: 묻지 않고, 저장하지 않은 작품은 그대로 startJob 에 간다
      out.clean = calls.splice(0);
      rsPicks(2).f0 = false;
      data.yes = false;
      await actions.restateEp('2');
      out.pickRefused = calls.splice(0);
      rsPicks(2).f0 = true;
      d.summary = '작가가 고친 요약';
      data.yes = true;
      await actions.restateEp('2');
      out.summaryOk = calls.splice(0);
      return out;
    })()""", {"yes": True})
    assert got["clean"] == [["job", "state", 2, True]]
    assert got["pickRefused"] == [["ask", "다시 뽑기"]]
    assert got["summaryOk"] == [["ask", "다시 뽑기"], ["job", "state", 2, True]]


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


@needs_node
def test_restate_items_show_repeated_plant_id_once():
    """변경안 안에서 같은 복선 id 가 두 번 오면 고르기 칸은 앞의 것 하나만 보인다 (서버도 앞의 것만 심는다)."""
    d = {**DELTA, "foreshadow_planted": DELTA["foreshadow_planted"] + [{"id": "fs-a", "description": "가 다시"}]}
    expr = "S.project = {episodes: [], foreshadows: [{id: 'fs-b'}], facts: []}; S.deltas = {1: data}; rsItems(1).plants.map((x) => x.i)"
    assert run_js(["app.js", "restate.js"], expr, d) == [0]

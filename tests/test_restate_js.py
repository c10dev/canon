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

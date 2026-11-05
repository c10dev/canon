"""장편 전환 화면(static/convert.js)의 '다시 받기': 받은 뒤 고친 계획 · 체크가 있으면 새 계획이 덮기 전에 묻는다. node 가 있을 때만 돈다."""
from .jsvm import needs_node, run_js


@needs_node
def test_refetch_asks_only_when_plan_was_edited():
    got = run_js(["app.js", "convert.js"], """(async () => {
      const calls = [];
      askConfirm = async (msg, o) => { calls.push(['ask', o.ok]); return false; };
      startJob = async (kind) => { calls.push(['job', kind]); };
      S.project = { episodes: [{ plot: { number: 3 }, status: 'confirmed' }], relationships: [] };
      S.convForm = { total: 0, ending: '', note: '' };
      S.rbForm = { total: 0, span: 0, ending_at: '', note: '' };
      const plan = { arc: { title: '아크 1' }, parts: [], foreshadows: [], scopes: [], facts: [], tiers: [], episodes: [{ number: 3 }] };
      convertResult({ kind: 'convert', result: structuredClone(plan) });
      convertResult({ kind: 'rebuild', result: { episodes: [{ title: '새 1화' }], foreshadows: [], tiers: [] } });
      const out = {};
      out.fresh = [planEdited('convert'), planEdited('rebuild')];
      await actions.convertPlan();
      await actions.rebuildPlan();
      out.freshCalls = calls.splice(0);
      S.convPicks['ep:3'] = false;  // 받은 그대로 꺼진 체크를 다시 끈 것은 고친 것이 아니다
      S.convPicks['fs:0'] = true;
      out.samePicks = planEdited('convert');
      S.convDraft.arc.title = '고친 제목';
      S.rbDraft.episodes[0].title = '고친 1화';
      await actions.convertPlan();
      await actions.rebuildPlan();
      out.editedCalls = calls.splice(0);
      convertResult({ kind: 'rebuild', result: { episodes: [], foreshadows: [], tiers: [] } });
      S.convPicks['rbfs:0'] = false;
      out.rbPick = planEdited('rebuild');
      return out;
    })()""", {})
    assert got["fresh"] == [False, False]
    assert got["freshCalls"] == [["job", "convert"], ["job", "rebuild"]]
    assert got["samePicks"] is False
    assert got["editedCalls"] == [["ask", "다시 받기"], ["ask", "다시 받기"]]
    assert got["rbPick"] is True

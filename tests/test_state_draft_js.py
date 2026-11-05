"""상태 승인 화면 초안: 새로고침 · 다른 탭이 pending.json 의 초안(고르던 체크 · 고친 칸)을 되살린다. node 가 있을 때만 돈다."""
from canon.schema import Meta, Project, StateDelta

from .jsvm import dump, episode, needs_node, run_js


def _data(draft):
    p = Project(meta=Meta(title="t", target_episodes=3),
                episodes=[episode(1, status="written", text="본문")])
    d = StateDelta(episode=1, summary="받은 요약", new_facts=["사실 하나", "사실 둘"])
    rec = {"key": "state:1", "id": "j1", "kind": "state", "ep": 1, "label": "1화 상태 변경안", "result": dump(d), "base": "본문"}
    if draft:
        rec["draft"] = {"delta": {**dump(d), "summary": "고친 요약"}, "picks": {"f0": False, "f1": True, "sc0": True}}
    return {"project": dump(p), "pending": {"results": {"state:1": rec}, "failures": {}}}


EXPR = """(async () => {
  S.project = data.project; S.name = 't'; S.picks.sc0 = false;
  await loadPending(Promise.resolve(data.pending));
  return { summary: S.deltas[1].summary, orig: S.deltaOrig[1].delta.summary, picks: S.picks, base: S.deltaBase[1], edited: deltaEdited(1) };
})()"""


@needs_node
def test_load_pending_restores_draft():
    got = run_js(["app.js", "review.js"], EXPR, _data(True))
    assert got["summary"] == "고친 요약" and got["orig"] == "받은 요약"  # 받은 그대로는 남아 '고침' 비교가 맞는다
    assert got["picks"]["f0"] is False and got["picks"]["f1"] is True
    assert got["picks"]["sc0"] is False  # 설정 제안 체크는 초안이 건드리지 않는다
    assert got["base"] == "본문"


@needs_node
def test_load_pending_without_draft_uses_defaults():
    got = run_js(["app.js", "review.js"], EXPR, _data(False))
    assert got["summary"] == "받은 요약" and got["picks"]["f0"] is True and got["edited"] is False


@needs_node
def test_save_delta_draft_sends_picks_and_skips_unknown():
    """체크를 바꾸면 변경안 키만 골라 PUT 한다. pending.json 에 결과가 없는 변경안(채팅 앱 JSON)은 보내지 않는다."""
    got = run_js(["app.js", "review.js"], """(async () => {
      S.project = data.project; S.name = 't';
      await loadPending(Promise.resolve(data.pending));
      const calls = [];
      setTimeout = (f) => f();
      api = async (...a) => { calls.push(a); };
      S.picks.f0 = false;
      S.deltas[2] = S.deltas[1];
      saveDeltaDraft(1);
      saveDeltaDraft(2);
      return calls;
    })()""", _data(False))
    assert len(got) == 1
    method, path, body = got[0]
    assert method == "PUT" and path == "/projects/t/pending/state%3A1/draft" and body["id"] == "j1"
    assert body["picks"] == {"f0": False, "f1": True} and body["delta"]["summary"] == "받은 요약"

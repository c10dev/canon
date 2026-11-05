"""자동 집필 검토 대기 변경안을 상태 승인 화면에서 볼 때: 서버 pending.json 결과로 받아 초안이 남고, '그대로 반영'은 고친 것을 버린다고 알린다. node 가 있을 때만 돈다."""
from canon.schema import Meta, Project, StateDelta

from .jsvm import dump, episode, needs_node, run_js

FILES = ["app.js", "review.js", "auto.js"]


def _data(draft=False):
    p = Project(meta=Meta(title="t", target_episodes=3), episodes=[episode(1, status="written", text="본문")])
    d = StateDelta(episode=1, summary="받은 요약", new_facts=["사실 하나", "사실 둘"])
    rec = {"key": "state:1", "id": "auto:t0:1:abc", "kind": "state", "ep": 1, "label": "1화 상태 변경안", "result": dump(d), "base": "만든 본문"}
    if draft:
        rec["draft"] = {"delta": {**dump(d), "summary": "고친 요약"}, "picks": {"f0": False, "f1": True}}
    run = {"status": "review", "ep": 1, "target": 3, "pending": dump(d), "pending_text": "만든 본문", "started": "t0"}
    return {"project": dump(p), "pending": {"results": {"state:1": rec}, "failures": {}}, "auto": {"run": run}}


# 서버 대역: POST /auto/review 는 실행을, GET /pending 은 결과를 돌려준다. 부른 차례를 calls 에 남긴다
SETUP = """
  S.project = data.project; S.name = 't'; S.auto = data.auto;
  globalThis.location = { hash: '' };
  render = () => {}; toast = () => {}; pollJobs = () => {}; autoPoll = () => {};
  autoFlushDrafts = async () => true; saveIfDirty = async () => {};
  run = async (label, f) => f();
  const calls = [];
  api = async (m, path, body) => {
    calls.push([m, path, body]);
    if (path.endsWith('/auto/review')) return data.auto;
    if (path.endsWith('/pending')) return structuredClone(data.pending);
    if (path === '/projects/t') return data.project;
    if (path.includes('/apply')) return { ...data.project, episodes: data.project.episodes.map((e) => ({ ...e, status: 'finalized' })) };
    return {};
  };
"""


@needs_node
def test_open_review_goes_through_pending_and_saves_draft():
    """검토하기는 서버에 결과를 두게 한 뒤 그 결과로 놓는다. 그래서 체크를 바꾸면 초안이 그 결과의 id 로 남는다."""
    got = run_js(FILES, """(async () => {""" + SETUP + """
      await actions.autoOpenReview();
      const out = { calls: calls.map((c) => c[0] + ' ' + c[1]), hash: location.hash, summary: S.deltas[1].summary, base: S.deltaBase[1] };
      setTimeout = (f) => f();
      S.picks.f0 = false;
      saveDeltaDraft(1);
      out.put = calls.filter((c) => c[0] === 'PUT').map((c) => [c[1], c[2].id, c[2].picks]);
      return out;
    })()""", _data())
    assert got["calls"][:2] == ["POST /projects/t/auto/review", "GET /projects/t/pending"]
    assert got["hash"] == "#/p/t/review/1" and got["summary"] == "받은 요약" and got["base"] == "만든 본문"
    assert got["put"] == [["/projects/t/pending/state%3A1/draft", "auto:t0:1:abc", {"f0": False, "f1": True}]]


@needs_node
def test_open_review_restores_draft_and_keeps_screen_edits():
    """다른 기기가 남긴 초안을 되살린다. 같은 결과를 이미 고치고 있으면 다시 눌러도 고친 것을 둔다."""
    got = run_js(FILES, """(async () => {""" + SETUP + """
      await actions.autoOpenReview();
      const out = { first: S.deltas[1].summary, f0: S.picks.f0 };
      S.deltas[1].summary = '이 탭에서 고침';
      await actions.autoOpenReview();
      out.again = S.deltas[1].summary;
      delete S.deltas[1];  // 변경안 버리기 뒤 다시 불러오기
      await actions.autoOpenReview();
      out.reload = S.deltas[1] && S.deltas[1].summary;
      return out;
    })()""", _data(draft=True))
    assert got == {"first": "고친 요약", "f0": False, "again": "이 탭에서 고침", "reload": "고친 요약"}


@needs_node
def test_approve_warns_when_review_has_edits():
    """그대로 반영은 서버의 변경안을 반영한다. 화면에서 고쳤거나 서버에 초안이 있으면 고친 것을 버린다고 묻는다."""
    got = run_js(FILES, """(async () => {""" + SETUP + """
      const asks = [];
      askConfirm = async (text, o) => { asks.push([text, o.ok, !!o.danger]); return false; };
      await actions.autoResume('approve');  // 고친 것 없음
      await actions.autoOpenReview();
      S.deltas[1].summary = '고친 요약';
      await actions.autoResume('approve');  // 이 탭에서 고침
      delete S.deltas[1];
      data.pending.results['state:1'].draft = { delta: data.pending.results['state:1'].result, picks: null };
      await actions.autoResume('approve');  // 다른 기기가 남긴 초안
      askConfirm = async () => true;
      await actions.autoOpenReview();
      await actions.autoResume('approve');
      return { asks, resumed: calls.filter((c) => c[1].endsWith('/auto/resume')).map((c) => c[2]), left: S.deltas[1] === undefined };
    })()""", _data())
    asks = got["asks"]
    assert asks[0][1] == "반영하기" and not asks[0][2] and "고친" not in asks[0][0]
    for text, ok, danger in asks[1:]:
        assert ok == "고친 것 버리고 반영하기" and danger and "검토하기에서 반영하세요" in text
    assert got["resumed"] == [{"approve": True, "rewrite": False}]  # 취소한 세 번은 보내지 않았다
    assert got["left"]  # 반영한 화의 변경안은 화면에서 내려 syncPending 이 서버 결과도 지운다


@needs_node
def test_apply_from_review_returns_to_autorun():
    """상태 승인 화면에서 반영하면 지금처럼 자동 집필 화면으로 돌아가 이어 간다 (applyDelta 의 forAuto)."""
    got = run_js(FILES, """(async () => {""" + SETUP + """
      askConfirm = async () => true;  // 변경안을 만든 본문과 지금 본문이 달라 한 번 묻는다
      await actions.autoOpenReview();
      await actions.applyDelta(1);
      return { hash: location.hash, applied: calls.some((c) => c[0] === 'POST' && c[1].startsWith('/projects/t/episodes/1/apply')), left: S.deltas[1] === undefined };
    })()""", _data())
    assert got == {"hash": "#/p/t/auto", "applied": True, "left": True}

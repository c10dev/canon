"""집필 화면의 상태 변경안 요약 카드 (docs/ux 06): review.js deltaGist 묶음 요지, write.js gistCard 자리 · 접기,
'추천대로 반영'(gistApply)이 상태 승인 화면에서 아무것도 바꾸지 않고 반영할 때와 같은 요청을 보내는지. node 가 있을 때만 돈다."""
import re

from canon import findings
from canon.schema import Character, ConsistencyIssue, Foreshadow, Meta, Project, Snapshot, StateDelta

from .jsvm import STATIC, dump, episode, needs_node, run_js

FILES = re.findall(r'src="/static/([a-z0-9]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))
TEXT = "서윤은 등대 앞에 섰다. 도현이 손전등을 건넸다."


def project(**kw) -> Project:
    chars = [Character(id="a", name="서윤", role="주인공"), Character(id="b", name="도현", role="조연")]
    eps = [episode(1, status="written", text=TEXT, plot={"title": "등대"}), episode(2, status="confirmed", plot={"title": "계단"})]
    return Project(meta=Meta(title="t", target_episodes=2), characters=chars, episodes=eps,
                   foreshadows=[Foreshadow(id="f1", description="오래된 손전등", planted_ep=1)], **kw)


def delta(**kw) -> StateDelta:
    base = {
        "episode": 1, "summary": "서윤과 도현이 등대에서 만난다.",
        "character_updates": [{"character_id": "a", "emotional_state": "긴장"}, {"character_id": "b", "emotional_state": "차분"}],
        "events": [{"episode": 1, "actor": "b", "target": "a", "kind": "도움", "intensity": 2},
                   {"episode": 1, "actor": "a", "target": "b", "kind": "칭찬", "intensity": 1},
                   {"episode": 1, "actor": "a", "target": "zz", "kind": "위협", "intensity": 1}],
        "new_facts": ["등대는 닫혀 있다", "도현은 열쇠를 가졌다"],
        "foreshadow_planted": [{"id": "f2", "description": "등대 꼭대기의 불빛", "planted_ep": 1}],
        "foreshadow_resolved": ["f1"],
        "setting_changes": [{"character_id": "a", "field": "appearance", "value": "짧은 머리"}],
        "secrets_added": [{"id": "s1", "owner": "b", "content": "열쇠를 훔쳤다", "hidden_from": ["a"]}],
    }
    return StateDelta.model_validate({**base, **kw})


def gist(p: Project, d: StateDelta, open_: int = 0):
    return run_js(FILES, """(() => {
      S.project = data.p; S.name = 't';
      return deltaGist(data.d, { picks: defaultPicks(data.d), name: charName, fs: S.project.foreshadows, open: data.open });
    })()""", {"p": dump(p), "d": dump(d), "open": open_})


@needs_node
def test_gist_counts_each_group():
    g = gist(project(), delta())
    rows = {x["key"]: [x["label"], x["count"], x["picked"], x["peek"]] for x in g["groups"]}
    assert rows["summary"] == ["요약", 1, 1, "서윤과 도현이 등대에서 만난다."]
    assert rows["chars"] == ["인물 상태", 2, 2, "서윤, 도현"]
    # 설정에 없는 인물이 낀 사건은 상태 승인 화면처럼 기본으로 빼 둔다. 수치는 없고 사건만 적는다
    assert rows["rel"] == ["관계 사건", 3, 2, "도현 → 서윤 도움 · 서윤 → 도현 칭찬"]
    assert rows["fs"] == ["복선", 2, 2, "심음 등대 꼭대기의 불빛 · 회수 오래된 손전등"]
    assert rows["facts"] == ["사실", 2, 2, "등대는 닫혀 있다 · 도현은 열쇠를 가졌다"]
    assert rows["setting"] == ["설정 바꾸기", 1, 0, "서윤 appearance"]
    assert rows["etc"] == ["그 밖", 1, 1, "비밀 1"]
    assert [g["picked"], g["total"]] == [9, 11]


@needs_node
def test_gist_names_what_it_leaves_out():
    assert gist(project(), delta())["skip"] == "설정 바꾸기 1개는 반영하지 않아요"
    both = delta(address_changes=[{"speaker": "a", "listener": "b", "calls": "도현 씨"}])
    assert gist(project(), both)["skip"] == "설정 바꾸기 1개 · 호칭 1개는 반영하지 않아요"
    assert gist(project(), delta(setting_changes=[]))["skip"] == ""


@needs_node
def test_gist_folds_when_check_issues_remain():
    g = gist(project(), delta(), 2)
    assert [g["fold"], g["head"]] == [True, "검수 지적 2개가 남았어요"]
    assert [gist(project(), delta())["fold"], gist(project(), delta())["head"]] == [False, ""]


def view_write(p: Project, d: StateDelta | None, before: str = "") -> str:
    return run_js(FILES, """(() => {
      S.project = data.p; S.name = 't'; S.route = ['p', 't', 'write', '1'];
      if (data.d) setDelta(1, data.d);
      """ + before + """
      return viewWrite(1);
    })()""", {"p": dump(p), "d": dump(d) if d else None})


@needs_node
def test_write_shows_card_only_with_delta():
    html = view_write(project(), delta())
    card = html[html.index('w-gist'):html.index('</section>', html.index('w-gist'))]
    assert "1화 상태 변경안" in card and "9/11건 고름" in card
    assert 'data-action="gistApply" data-arg="1"' in card and "추천대로 반영" in card
    assert "설정 바꾸기 1개는 반영하지 않아요" in card and "상태 승인으로" in card
    assert 'data-action="gistGo" data-arg="1:rel"' in card
    assert "btn primary" not in card  # 주 버튼은 머리 줄에 하나
    # 카드는 단계 띠 아래, 본문 칸 위
    assert html.index("flow-bar") < html.index("w-gist") < html.index("w-body")
    assert "w-gist" not in view_write(project(), None)


@needs_node
def test_write_card_folds_with_open_issues():
    p = project()
    issue = ConsistencyIssue(type="말투", description="말투가 달라요", source_quote="설정", current_quote="서윤은 등대 앞에 섰다.")
    findings.merge(p.episodes[0], [issue], "2026-11-09T10:00:00", "b")
    html = view_write(p, delta())
    assert '<details class="card tight w-gist" data-rv-grp="1:gist">' in html
    assert "<summary><strong>검수 지적 1개가 남았어요</strong>" in html


@needs_node
def test_write_card_drops_apply_after_review_edits():
    # 상태 승인 화면에서 체크를 바꿨으면 '추천대로'가 아니다. 카드는 상태 승인으로만 보낸다
    html = view_write(project(), delta(), "S.picks.f0 = false;")
    assert "추천대로 반영" not in html and "상태 승인에서 고친 것이 있어요" in html


APPLY = """(async () => {
  const calls = [];
  api = async (m, path, body) => { calls.push([m, path, JSON.parse(JSON.stringify(body))]); return S.project; };
  run = async (label, fn) => { await fn(); };
  askConfirm = async () => true;
  saveIfDirty = async () => {};
  flushText = async () => {};
  toast = () => {};
  render = () => {};
  S.project = data.p; S.name = 't';
  // 상태 승인 화면에서 아무것도 바꾸지 않고 반영
  S.route = ['p', 't', 'review', '1'];
  setDelta(1, structuredClone(data.d));
  await actions.applyDelta(1);
  const review = calls.pop();
  // 다른 화 변경안을 보던 뒤에 집필 화면 요약 카드에서 '추천대로 반영'
  S.project = structuredClone(data.p);
  S.route = ['p', 't', 'write', '1'];
  setDelta(1, structuredClone(data.d));
  setDelta(2, { ...structuredClone(data.d), episode: 2 });
  await actions.gistApply(1);
  const card = calls.pop();
  return { review, card, done: S.gistDone, left: !!S.deltas[1] };
})()"""


@needs_node
def test_gist_apply_sends_same_request_as_review():
    out = run_js(FILES, APPLY, {"p": dump(project()), "d": dump(delta())})
    assert out["review"] == out["card"]
    m, path, body = out["card"]
    assert (m, path) == ("POST", "/projects/t/episodes/1/apply")
    # 인물 설정 바꾸기는 기본으로 체크하지 않아 반영하지 않고 빼 둔 목록에 남는다
    assert body["setting_changes"] == [] and len(body["dismissed"]["setting_changes"]) == 1
    assert [e["target"] for e in body["events"]] == ["a", "b"]
    assert out["done"] == {"name": "t", "n": 1} and out["left"] is False


@needs_node
def test_after_apply_card_offers_next_and_revert():
    p = project()
    p.episodes[0].status = "finalized"
    p.snapshots = [Snapshot(episode=0)]
    html = view_write(p, None, "S.gistDone = { name: 't', n: 1 };")
    card = html[html.index('w-gist'):html.index('</section>', html.index('w-gist'))]
    # 다음 화로: 상태 승인 화면의 반영 뒤 주 버튼(nextStepBtn)과 같은 다음 할 일이다
    assert "1화를 반영했어요" in card and '<a data-gist-next class="btn" href=' in card
    assert 'data-action="revertFrom" data-arg="1"' in card
    # 다른 화에서는 보이지 않는다
    other = run_js(FILES, """(() => { S.project = data; S.name = 't'; S.route = ['p', 't', 'write', '2']; S.gistDone = { name: 't', n: 1 };
      return [viewWrite(2).includes('w-gist'), S.gistDone]; })()""", dump(p))
    assert other == [False, None]

"""상태 승인 화면(static/review.js)의 반영 취소 까닭 표시(revertGone)와 화별 체크 맞추기(pickEp). node 가 있을 때만 돈다."""
import re

from canon.schema import Meta, Project, Settings, Snapshot, StateDelta

from .jsvm import STATIC, dump, episode, needs_node, run_js

FILES = re.findall(r'src="/static/([a-z0-9]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))


def project(form: str, keep: bool = False) -> Project:
    eps = [episode(n, status="finalized", text=f"{n}화 본문.") for n in (1, 2, 3)]
    return Project(meta=Meta(title="t", target_episodes=3, form=form), episodes=eps, settings=Settings(keep_snapshots=keep),
                   history=[StateDelta(episode=n, summary=f"{n}화 요약") for n in (1, 2, 3)],
                   snapshots=[Snapshot(episode=0), Snapshot(episode=3)])


def view(p: Project, n: int) -> str:
    return run_js(FILES, f"(() => {{ S.project = data; S.name = 't'; S.route = ['p', 't', 'review', '{n}']; return viewReview({n}); }})()", dump(p))


@needs_node
def test_revert_reason_when_snapshot_gone():
    # 1화는 0화 스냅샷이 있어 반영 취소 버튼, 3화는 2화 스냅샷이 지워져 까닭을 쓴다
    assert 'data-action="revertFrom" data-arg="1"' in view(project("serial"), 1)
    html = view(project("serial"), 3)
    assert 'data-action="revertFrom"' not in html and "장편은 최근 20화와 각 아크 첫 화부터만 반영을 취소할 수 있어요" in html
    assert "화별 상태 기록이 없어 반영을 취소할 수 없어요" in view(project("serial", keep=True), 3)


@needs_node
def test_pick_ep_restores_own_picks():
    # 반영 취소로 두 화 변경안이 놓이면 체크는 마지막 화 것이다. 다른 화를 열면 그 화 체크로 돌리고, 그 화에서 푼 체크도 남는다
    p = project("serial")
    a = StateDelta(episode=1, summary="", new_facts=["가", "나"])
    b = StateDelta(episode=2, summary="")
    out = run_js(FILES, """(() => {
      S.project = data.p;
      setDelta(1, data.a); S.picks.f1 = false;
      setDelta(2, data.b);
      const lost = 'f0' in S.picks;
      pickEp(1);
      return [lost, S.picks.f0, S.picks.f1, S.picksEp];
    })()""", {"p": dump(p), "a": dump(a), "b": dump(b)})
    assert out == [False, True, False, 1]


@needs_node
def test_pick_ep_recounts_defaults():
    # 반영 취소 직후에는 2화의 새 인물(ha)이 없어 3화 변경안의 그 인물 상태가 기본으로 빠진다. 2화를 반영해 인물이 생긴 뒤 3화를 열면 다시 센다
    p = project("serial")
    b = StateDelta.model_validate({"episode": 2, "summary": "", "new_characters": [{"id": "ha", "name": "하", "role": "조연"}]})
    c = StateDelta.model_validate({"episode": 3, "summary": "", "character_updates": [{"character_id": "ha"}]})
    out = run_js(FILES, """(() => {
      S.project = data.p;
      setDelta(3, data.c);
      const before = S.picks.c0;
      setDelta(2, data.b);
      S.project.characters.push({ ...data.b.new_characters[0] });
      pickEp(3);
      return [before, S.picks.c0, S.deltaOrig[3].picks.c0];
    })()""", {"p": dump(p), "b": dump(b), "c": dump(c)})
    assert out == [False, True, True]


@needs_node
def test_event_kind_tag_text():
    # 좋은 · 나쁜 사건은 색만으로 갈리지 않게 고르기 옆 칩에 기호(읽지 않음)와 글자를 둔다
    p = project("short")
    p.episodes[0].status = "written"
    d = StateDelta.model_validate({"episode": 1, "summary": "", "events": [
        {"episode": 1, "actor": "a", "target": "b", "kind": "도움", "intensity": 1}, {"episode": 1, "actor": "a", "target": "b", "kind": "배신", "intensity": 2}]})
    html = run_js(FILES, """(() => {
      S.project = data.p; S.name = 't'; S.route = ['p', 't', 'review', '1'];
      setDelta(1, data.d);
      return viewReview(1);
    })()""", {"p": dump(p), "d": dump(d)})
    assert '<span class="chip ok" data-kind-tag="ek-0"><span aria-hidden="true">＋</span> 좋은 사건</span>' in html
    assert '<span class="chip bad" data-kind-tag="ek-1"><span aria-hidden="true">－</span> 나쁜 사건</span>' in html

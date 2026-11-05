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
    # 반영 취소로 두 화 변경안이 놓이면 체크는 마지막 화 것이다. 다른 화를 열면 그 화의 받은 그대로 체크로 돌린다
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
    assert out == [False, True, True, 1]

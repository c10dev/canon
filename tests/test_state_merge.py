"""상태 승인 갈래들을 합친 뒤의 맞물림: 빼 둔 항목(dismissed)이 반영 취소 · 자동 반영 · 초안을 거쳐도 사라지거나 몰래 반영되지 않는다.
실행: python -m pytest tests"""
from canon import pipeline
from canon.schema import CharacterState, Meta, Project, StateDelta

from .jsvm import dump, episode, needs_node, run_js
from .test_restate import _two_done
from .test_storylines import _short
from .test_web import client  # noqa: F401  (pytest fixture)


def test_drop_invalid_keeps_dropped_items_in_dismissed():
    """자동 집필 · 명령줄 반영이 뺀 항목(drop_invalid)도 pace.hold 처럼 반영 기록의 빼 둔 항목에 남는다."""
    p = _short(8)
    p.episode(1).status = "written"
    d = StateDelta(episode=1, summary="", foreshadow_resolved=["fs-none"],
                   character_updates=[CharacterState(character_id="ghost", emotional_state="화남")])
    dropped = pipeline.apply_delta(p, d)
    assert len(dropped) == 2
    rec = p.history[-1]
    assert rec.character_updates == [] and [u.character_id for u in rec.dismissed.character_updates] == ["ghost"]
    assert rec.dismissed.foreshadow_resolved == ["fs-none"]


def test_revert_kept_delta_carries_dismissed(client):
    """반영 취소가 pending.json 에 남긴 변경안은 그 화에서 체크를 푼 항목(dismissed)을 그대로 싣는다. 화면이 다시 놓을 재료다."""
    p = _two_done(client)
    h = next(x for x in p["history"] if x["episode"] == 2)
    client.post("/api/projects/lh/revert/1")
    body = {**h, "dismissed": {"new_facts": ["빼 둔 사실"]}}
    client.post("/api/projects/lh/episodes/2/apply", json=body)
    client.post("/api/projects/lh/revert/1")
    r = client.get("/api/projects/lh/pending").json()["results"]["state:2"]
    assert r["result"]["dismissed"]["new_facts"] == ["빼 둔 사실"]


def _pending(draft=None):
    p = Project(meta=Meta(title="t", target_episodes=3), episodes=[episode(1, status="written", text="본문")])
    d = StateDelta(episode=1, summary="요약", new_facts=["반영한 사실"])
    d.dismissed.new_facts = ["빼 둔 사실"]
    rec = {"key": "state:1", "id": "revert:t:1", "kind": "state", "ep": 1, "label": "1화 상태 변경안", "result": dump(d), "base": "본문"}
    if draft:
        rec["draft"] = draft
    return {"project": dump(p), "pending": {"results": {"state:1": rec}, "failures": {}}}


@needs_node
def test_reverted_delta_reoffers_dismissed_unchecked():
    """반영 기록에서 돌아온 변경안의 빼 둔 항목은 목록에 다시 놓이고 체크를 푼 채다. 그대로 반영하면 다시 dismissed 로 간다.
    다른 화를 보고 돌아와 기본 체크를 다시 세도(pickEp) 풀린 채다."""
    got = run_js(["app.js", "review.js"], """(async () => {
      S.project = data.project; S.name = 't';
      await loadPending(Promise.resolve(data.pending));
      const facts = S.deltas[1].new_facts, picks = { ...S.picks };
      S.picksEp = 9; pickEp(1);
      const again = { ...S.picks };
      setDelta(1, S.deltas[1]);  // 같은 변경안을 다시 놓아도 두 번 붙이지 않는다
      const out = JSON.parse(JSON.stringify(pickedDelta(1)));
      return { facts, picks, again, after: S.deltas[1].new_facts, out };
    })()""", _pending())
    assert got["facts"] == ["반영한 사실", "빼 둔 사실"]
    assert got["picks"]["f0"] is True and got["picks"]["f1"] is False
    assert got["again"]["f0"] is True and got["again"]["f1"] is False
    assert got["after"] == ["반영한 사실", "빼 둔 사실"]
    assert got["out"]["new_facts"] == ["반영한 사실"] and got["out"]["dismissed"]["new_facts"] == ["빼 둔 사실"]
    assert "reoffer" not in got["out"]  # 화면 전용 표시는 서버에 보내지 않는다


@needs_node
def test_draft_of_reoffered_delta_keeps_dismissed_once():
    """다시 놓은 변경안의 초안(saveDeltaDraft)을 되살려도 빼 둔 항목이 두 번 붙지 않고, 작가가 다시 체크한 것은 체크된 채다."""
    first = run_js(["app.js", "review.js"], """(async () => {
      S.project = data.project; S.name = 't';
      await loadPending(Promise.resolve(data.pending));
      S.picks.f1 = true;
      const calls = [];
      setTimeout = (f) => f();
      api = async (...a) => { calls.push(a); };
      saveDeltaDraft(1);
      return calls[0][2];
    })()""", _pending())
    draft = {"delta": first["delta"], "picks": first["picks"]}
    got = run_js(["app.js", "review.js"], """(async () => {
      S.project = data.project; S.name = 't';
      await loadPending(Promise.resolve(data.pending));
      return { facts: S.deltas[1].new_facts, picks: S.picks, out: JSON.parse(JSON.stringify(pickedDelta(1))) };
    })()""", _pending(draft))
    assert got["facts"] == ["반영한 사실", "빼 둔 사실"]
    assert got["picks"]["f1"] is True
    assert got["out"]["new_facts"] == ["반영한 사실", "빼 둔 사실"] and got["out"]["dismissed"]["new_facts"] == []

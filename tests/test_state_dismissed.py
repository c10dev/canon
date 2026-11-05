"""상태 승인 화면에서 체크를 푼 항목(StateDelta.dismissed): AI 응답 형식에서 빠짐, 옛 기록 읽힘, 반영 기록에 남음, 반영 취소로 빠짐,
자동 반영이 뺀 관계 유형, 화면 pickedDelta 가 체크를 푼 항목을 보냄. 실행: python -m pytest tests"""
import json
import re
import shutil
import subprocess

import pytest

from canon import pace, pipeline, web
from canon.schema import AddressChange, DismissedItems, Relationship, SettingChange, StateDelta

from .test_delta_count import APP, EDIT_HARNESS
from .test_storylines import _short
from .test_timeline import LLM, _play


def _written(p, n):
    pipeline.confirm_plot(p, n)
    p.episode(n).text = pipeline.write_episode(LLM, p, n)
    p.episode(n).status = "written"


def test_dismissed_not_in_ai_schema_and_old_history_reads():
    assert "dismissed" not in StateDelta.model_json_schema()["properties"]
    d = StateDelta.model_validate({"episode": 1, "summary": "요약"})  # 옛 project.json 의 반영 기록
    assert d.dismissed.new_facts == [] and d.dismissed.events == []


def test_apply_keeps_dismissed_in_history_and_revert_drops_it():
    p = _play(_short(8), 1, 2)
    _written(p, 3)
    d = pipeline.extract_state(LLM, p, 3)
    # 화면이 보내는 모양: 체크를 푼 사실 하나는 dismissed 로 옮긴다
    body = d.model_dump()
    body["dismissed"] = {"new_facts": ["빼 둔 사실"], "foreshadow_resolved": ["fs-x"]}
    picked = StateDelta.model_validate(body)
    pipeline.apply_delta(p, picked)
    assert "빼 둔 사실" not in p.facts  # 반영하지 않는다
    rec = p.history[-1]
    assert rec.episode == 3 and rec.dismissed.new_facts == ["빼 둔 사실"] and rec.dismissed.foreshadow_resolved == ["fs-x"]
    pipeline.revert(p, 2)
    assert all(h.episode <= 2 for h in p.history)
    assert all(not h.dismissed.new_facts for h in p.history)


def test_pace_hold_records_dropped_relationship_updates():
    p = _short(8)
    a, b = p.characters[0].id, p.characters[1].id
    d = StateDelta(episode=1, summary="", rel_flagged=[0], relationship_updates=[
        Relationship(a=a, b=b, type="원수"), Relationship(a=a, b=b, type="친구")])
    pace.hold(p, d)
    assert [r.type for r in d.relationship_updates] == ["친구"]
    assert [r.type for r in d.dismissed.relationship_updates] == ["원수"]


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_picked_delta_sends_unchecked_items():
    js = EDIT_HARNESS.split("const type = ")[0] + """
vm.runInContext('setDelta(1, ' + JSON.stringify(d) + ')', ctx);
vm.runInContext("S.picks.f0 = false; S.picks.e0 = false;", ctx);
process.stdout.write(JSON.stringify(vm.runInContext('pickedDelta(1)', ctx)));
"""
    run = subprocess.run(["node", "-e", js, str(APP)], capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    out = json.loads(run.stdout)
    assert out["new_facts"] == ["배는 사흘에 한 번 온다"] and out["events"] == []
    x = out["dismissed"]
    assert x["new_facts"] == ["등대는 북쪽에 있다"] and [e["kind"] for e in x["events"]] == ["도움"]
    assert x["character_updates"] == [] and x["new_places"] == []
    assert x["setting_changes"] == [] and x["address_changes"] == []
    assert "cast_added" not in x  # 등장 인물 붙이기는 기록하지 않는다


def test_carried_delta_renumbers_dismissed():
    from .test_rebuild import _rebuilt

    p, *_ = _rebuilt()
    e1 = p.episode(1)
    e1.text, e1.status = "새 1화 본문", "written"
    pipeline.apply_delta(p, pipeline.extract_state(LLM, p, 1))
    old = next(d for d in p.archive.history if d.episode == 1)
    old.dismissed.events = [e.model_copy() for e in old.events]
    old.dismissed.foreshadow_planted = [f.model_copy() for f in old.foreshadow_planted]
    d = pipeline.carried_delta(p, 2)
    assert d is not None and d.dismissed.events
    assert all(e.episode == 2 for e in d.dismissed.events)
    assert all(f.planted_ep == 2 for f in d.dismissed.foreshadow_planted)


def test_dismiss_lists_match_dismissed_items():
    """화면이 다시 놓는 목록(DISMISS_LISTS)이 DismissedItems 의 칸과 같다. 빠진 칸은 반영 취소 뒤 사라진다."""
    js = APP.read_text(encoding="utf-8")
    keys = re.findall(r"\['(\w+)', '\w'\]", re.search(r"const DISMISS_LISTS = (\[.*?\]\]);", js).group(1))
    assert sorted(keys) == sorted(DismissedItems.model_fields)


def test_unchecked_setting_and_address_changes_stay_unapplied_and_come_back_on_revert():
    p = _play(_short(8), 1, 2)
    _written(p, 3)
    a, b = p.characters[0].id, p.characters[1].id
    before = p.characters[0].appearance
    forms = [f.model_dump() for f in p.address_forms]
    d = pipeline.extract_state(LLM, p, 3)
    body = d.model_dump()
    body["setting_changes"], body["address_changes"] = [], []
    body["dismissed"] = {"setting_changes": [{"character_id": a, "field": "appearance", "value": "짧은 머리", "quote": "머리를 잘랐다"}],
                         "address_changes": [{"speaker": a, "listener": b, "calls": "형", "speech": "해체(반말)"}]}
    pipeline.apply_delta(p, StateDelta.model_validate(body))
    assert p.characters[0].appearance == before  # 체크를 푼 설정 바꾸기는 반영하지 않는다
    assert not [r for r in p.setting_log if r.episode == 3]
    assert [f.model_dump() for f in p.address_forms] == forms and not [r for r in p.address_log if r.episode == 3]
    assert p.setting_held == [] and p.address_held == []  # 작가가 푼 것은 남겨 둔 제안(자동 집필)으로 가지 않는다
    rec = p.history[-1]
    assert [x.value for x in rec.dismissed.setting_changes] == ["짧은 머리"]
    assert [x.calls for x in rec.dismissed.address_changes] == ["형"]
    kept = web._revert_kept(p, 2)
    again = StateDelta.model_validate(kept["state:3"]["result"])
    assert again.dismissed.setting_changes == [SettingChange(character_id=a, field="appearance", value="짧은 머리", quote="머리를 잘랐다")]
    assert again.dismissed.address_changes == [AddressChange(speaker=a, listener=b, calls="형", speech="해체(반말)")]


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_unchecked_setting_and_address_changes_are_reoffered_unchecked():
    head = EDIT_HARNESS.split("const d = {")[0]
    js = head + """
const d = { summary: '', character_updates: [], events: [], relationship_updates: [], new_facts: [], warnings: [], secrets_added: [],
  foreshadow_planted: [], foreshadow_resolved: [],
  setting_changes: [{ character_id: 'a', field: 'appearance', value: '긴 머리' }],
  address_changes: [{ speaker: 'a', listener: 'b', calls: '선배', speech: '' }] };
vm.runInContext('setDelta(1, ' + JSON.stringify(d) + ')', ctx);
const first = vm.runInContext('pickedDelta(1)', ctx);
// 반영 취소로 돌아온 변경안 (web._revert_kept): 고른 것은 목록에, 체크를 푼 것은 dismissed 에
const back = { ...first, setting_changes: [{ character_id: 'b', field: 'role', value: '선장' }], address_changes: [] };
vm.runInContext('setDelta(1, ' + JSON.stringify(back) + ')', ctx);
const now = vm.runInContext("({ d: S.deltas[1], picks: ['t0', 't1', 'h0'].map((k) => S.picks[k]), again: pickedDelta(1) })", ctx);
process.stdout.write(JSON.stringify({ first, now }));
"""
    run = subprocess.run(["node", "-e", js, str(APP)], capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    out = json.loads(run.stdout)
    x = out["first"]["dismissed"]
    assert out["first"]["setting_changes"] == [] and out["first"]["address_changes"] == []
    assert [s["value"] for s in x["setting_changes"]] == ["긴 머리"] and [h["calls"] for h in x["address_changes"]] == ["선배"]
    now = out["now"]
    assert [s["value"] for s in now["d"]["setting_changes"]] == ["선장", "긴 머리"]
    assert [h["calls"] for h in now["d"]["address_changes"]] == ["선배"]
    assert now["picks"] == [False, False, False]  # 다시 놓아도 체크하지 않는다
    assert now["again"]["setting_changes"] == [] and now["again"]["address_changes"] == []
    assert [s["value"] for s in now["again"]["dismissed"]["setting_changes"]] == ["선장", "긴 머리"]

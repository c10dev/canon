"""상태 승인 화면(static/review.js)이 변경안 항목을 빠짐없이 세는지. 화면의 'n건 중'과 반영 확인창의 '0건'이 같은 목록(DELTA_LISTS)을 쓴다."""
import json
import re
import shutil
import subprocess
import typing
from pathlib import Path

import pytest

from canon.schema import StateDelta

APP = Path(__file__).resolve().parent.parent / "canon" / "static" / "review.js"


def _source(name):
    src = APP.read_text(encoding="utf-8")
    m = re.search(rf"^const {name} = .*?;$", src, re.M)
    assert m, f"review.js 에 {name} 가 없어요"
    return m.group(0)


def test_delta_lists_cover_state_delta():
    lists = re.findall(r"'(\w+)'", _source("DELTA_LISTS"))
    # rel_flagged 는 고르는 항목이 아니라 relationship_updates 의 기본 체크를 정하는 차례 목록이다 (pace.clean_delta)
    want = {k for k, f in StateDelta.model_fields.items() if typing.get_origin(f.annotation) is list} - {"warnings", "rel_flagged"}
    assert set(lists) == want
    assert len(lists) == len(set(lists))


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_delta_count_counts_clues():
    js = _source("DELTA_LISTS") + "\n" + _source("deltaCount") + """
process.stdout.write(JSON.stringify([
  deltaCount({ foreshadow_clues: [{}, {}] }),
  deltaCount({ new_facts: ['a'], events: [{}], foreshadow_clues: [{}], warnings: ['w'] }),
  deltaCount({}),
]));"""
    run = subprocess.run(["node", "-e", js], capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == [2, 3, 0]


def test_event_kinds_match_schema():
    from canon.schema import EventKind
    kinds = re.findall(r"'([^']+)'", _source("EVENT_KINDS"))
    assert kinds == [k for k in typing.get_args(EventKind) if k != "수동보정"]  # 수동보정은 작가가 관계를 직접 고칠 때만


# review.js 가 기대는 app.js 전역을 최소한으로 흉내 내고, 화면 입력이 오는 것처럼 input 처리기를 부른다
EDIT_HARNESS = """
const vm = require('vm');
const fs = require('fs');
const listeners = {};
const ctx = {
  S: { deltas: {}, deltaBase: {}, deltaOrig: {}, picks: {}, route: ['p', 'x', 'review', '1'] },
  actions: {}, setTimeout() {}, clearTimeout() {}, structuredClone, CSS: { escape: (x) => x },
  P: () => ({ characters: [{ id: 'a' }, { id: 'b' }], foreshadows: [], timeline: { deadlines: [] }, states: [] }),
  ep: () => ({ text: '본문' }),
  document: { addEventListener: (k, f) => { (listeners[k] = listeners[k] || []).push(f); }, querySelector: () => null },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const d = {
  summary: '요약', character_updates: [{ character_id: 'a', emotional_state: '불안', attire: '', knows: ['열쇠가 있다', '비밀'], stats: [] }],
  events: [{ actor: 'a', target: 'b', kind: '도움', intensity: 2, witnesses: [] }],
  secrets_added: [], relationship_updates: [], new_facts: ['등대는 북쪽에 있다', '배는 사흘에 한 번 온다'],
  foreshadow_planted: [], foreshadow_resolved: [], time: { day: 0, part: '', label: '' }, warnings: [],
};
const type = (dpath, value) => listeners.input.forEach((f) => f({ target: { dataset: { dedit: '1', dpath, dmark: 'x0' }, value, style: {} } }));
vm.runInContext('setDelta(1, ' + JSON.stringify(d) + ')', ctx);
const out = { before: vm.runInContext('deltaEdited(1)', ctx) };
type('events.0.kind', '배신');
type('events.0.intensity', '3');
type('new_facts.0', '  등대는 남쪽에 있다 ');
type('new_facts.1', '');
type('character_updates.0.emotional_state', '분노');
type('character_updates.0.knows.1', ' ');
Object.assign(out, vm.runInContext(`({ edited: deltaEdited(1), e0: itemEdited(1, 'e0'), f1: itemEdited(1, 'f1'), kn0: itemEdited(1, 'kn0.0'),
  picked: pickedDelta(1), orig: S.deltaOrig[1].delta.events[0] })`, ctx));
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_review_edits_reach_picked_delta():
    run = subprocess.run(["node", "-e", EDIT_HARNESS, str(APP)], capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    out = json.loads(run.stdout)
    assert out["before"] is False  # 받은 그대로면 다시 만들 때 묻지 않는다
    assert out["edited"] and out["e0"] and out["f1"] and not out["kn0"]
    picked = out["picked"]
    assert picked["events"][0]["kind"] == "배신" and picked["events"][0]["intensity"] == 3
    assert picked["new_facts"] == ["등대는 남쪽에 있다"]  # 앞뒤 공백을 지우고 비운 사실은 뺀다
    assert picked["character_updates"][0]["emotional_state"] == "분노"
    assert picked["character_updates"][0]["knows"] == ["열쇠가 있다"]
    assert out["orig"] == {"actor": "a", "target": "b", "kind": "도움", "intensity": 2, "witnesses": []}  # 받은 그대로는 따로 남는다

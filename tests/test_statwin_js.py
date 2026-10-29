"""상태창 화면(static/statwin.js)의 swResolve 가 statwin.resolve 와 같은 값을 내는지. node 가 있을 때만 돈다."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from canon import statwin

from .test_statwin import RESOLVE_CASES

STATWIN = Path(__file__).resolve().parent.parent / "canon" / "static" / "statwin.js"

# statwin.js 가 기대는 app.js 전역을 최소한으로 흉내 낸다. 시험 식은 파일 뒤에 이어 붙어 'use strict' 를 받으므로
# 식 안에서 전역을 새로 만들지 않는다 (render 처럼 쓰는 전역은 여기 ctx 에 둔다)
HARNESS = """
const vm = require('vm');
const fs = require('fs');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const ctx = { data, S: {}, actions: {}, render() {}, document: { addEventListener() {}, createElement: () => ({}), head: { appendChild() {} } } };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + `
;globalThis.out = data.cases.map(([b, v]) => swResolve(b, v));`, ctx);
process.stdout.write(JSON.stringify(ctx.out));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_sw_resolve_matches_server():
    cases = [(b, v) for b, v, _ in RESOLVE_CASES] + [("0.1", "+0.2"), ("1,000", "-0.5"), ("화염구 · 은신", "+독"),
                                                ("1,000.5/2,000L", "-1,200.25"), ("0.0/40L", "+0.1"), ("9.0/40L", "+1L"), ("0.05/1", "-0.05")]
    run = subprocess.run(["node", "-e", HARNESS, str(STATWIN)], input=json.dumps({"cases": cases}),
                         capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    for (b, v), got in zip(cases, json.loads(run.stdout)):
        assert got == statwin.resolve(b, v), (b, v)


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_sw_presets_match_server():
    js = HARNESS.replace("data.cases.map(([b, v]) => swResolve(b, v))", "SW_PRESETS")
    run = subprocess.run(["node", "-e", js, str(STATWIN)], input=json.dumps({"cases": []}), capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == statwin.PRESETS


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_ab_list_names_match_server():
    from canon import abilities
    js = HARNESS.replace("data.cases.map(([b, v]) => swResolve(b, v))", "AB_LIST_NAMES")
    run = subprocess.run(["node", "-e", js, str(STATWIN.with_name("abilities.js"))], input=json.dumps({"cases": []}), capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == list(abilities.LIST_NAMES)


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_sw_move_swaps_rows():
    js = HARNESS.replace("data.cases.map(([b, v]) => swResolve(b, v))",
                         "(S.swRows = data.cases.map((name) => ({ name, value: '' })), "
                         "actions.swMove('0:1'), actions.swMove('2:1'), actions.swMove('0:-1'), actions.swMove('2:-1'), "
                         "[S.swRows.map((r) => r.name), S.swDirty, S.focusTarget])")
    run = subprocess.run(["node", "-e", js, str(STATWIN)], input=json.dumps({"cases": ["레벨", "연료", "기능"]}),
                         capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    # 0↔1, 끝 아래와 처음 위는 그대로, 2↔1
    assert json.loads(run.stdout) == [["연료", "기능", "레벨"], True, '#app [data-action="swMove"][data-arg="1:-1"]']

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


def _run(files, expr, data=None):
    """files 를 차례로 한 맥락에 싣고 expr 의 값을 JSON 으로 돌려준다 (abilities.js 는 statwin.js 의 SW_GRADE 를 쓴다)"""
    js = """
const vm = require('vm');
const fs = require('fs');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const ctx = { data, S: {}, actions: {}, render() {}, document: { addEventListener() {}, createElement: () => ({}), head: { appendChild() {} } } };
vm.createContext(ctx);
vm.runInContext(process.argv.slice(1).map((f) => fs.readFileSync(f, 'utf8')).join(';\\n') + `
;globalThis.out = (${EXPR});`, ctx);
process.stdout.write(JSON.stringify(ctx.out));
""".replace("${EXPR}", expr)
    run = subprocess.run(["node", "-e", js, *[str(STATWIN.with_name(f)) for f in files]], input=json.dumps(data or {}),
                         capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_sw_change_parts_pairs_grades():
    """화별 변화 글: 목록은 같은 이름끼리 짝지어 등급 바뀜으로, 남은 것은 더함 · 뺌. 목록이 아니면 이전 → 새 값"""
    got = _run(["statwin.js"], "data.map(([ch, after]) => swChangeParts(ch, after))", [
        [{"before": "감정 Lv2, 독 내성", "added": ["감정 Lv3", "그림자 걸음"], "removed": ["감정 Lv2", "은신"]}, "감정 Lv3, 독 내성, 그림자 걸음"],
        [{"before": "7", "added": [], "removed": []}, "9"],
        [{"before": "", "added": [], "removed": []}, "첫 균열 생존자"],
    ])
    assert got[0] == [{"kind": "grade", "before": "감정 Lv2", "after": "감정 Lv3"}, {"kind": "add", "before": "", "after": "그림자 걸음"},
                      {"kind": "del", "before": "은신", "after": ""}]
    assert got[1] == [{"kind": "set", "before": "7", "after": "9"}]
    assert got[2] == [{"kind": "set", "before": "", "after": "첫 균열 생존자"}]


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_sw_calc_shows_resolved_value():
    """고치는 칸 옆 계산 값: 바뀐 양이면 '→ 새 값', 목록은 조각 수, 값을 그대로 적으면 빈 글"""
    got = _run(["statwin.js"], "data.map(([b, v]) => swCalc(b, v))",
               [["9", "+2"], ["1,700골드", "+500"], ["감정 Lv3, 독 내성", "+화염 저항"], ["9", "11"], ["B급", "+1"], ["30/100", "-10"]])
    assert got == ["→ 11", "→ 2,200골드", "→ 3개", "", "", "→ 20/100"]


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_ab_key_and_split_match_server():
    from canon import abilities
    names = ["화염구 Lv4", "롱소드 +2 (A급)", "청풍검법 3성", "Lv3", "화염 구 lv2", "감정 Lv3", "  붉은 사자  "]
    got = _run(["statwin.js", "abilities.js"], "data.map((x) => [abSplit(x), abKey(x)])", names)
    assert got == [[list(abilities.split(x)), abilities.key(x)] for x in names]


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_ab_find_local_matches_server():
    """칩의 '도감에 설명 없음' 점: abFindLocal 이 abilities.find 와 같은 항목을 고른다"""
    from canon import abilities
    from canon.schema import Ability, Project
    p = Project()
    p.abilities = [Ability(id="ab-01", name="화염구", aliases=["파이어볼"], effect="불"), Ability(id="ab-02", name="강철 피부", stat="스킬")]
    cases = [["파이어볼 Lv9", ""], ["화염구 Lv3", "스킬"], ["강철 피부", "특성"], ["강철피부", "스킬"], ["은신", "스킬"]]
    got = _run(["statwin.js", "abilities.js"], "(globalThis.P = () => data.p, data.cases.map(([i, s]) => (abFindLocal(i, s) || {}).id || null))",
               {"cases": cases, "p": p.model_dump(mode="json")})
    assert got == [(abilities.find(p, i, s) or Ability(id="", name="")).id or None for i, s in cases]

"""인물 상태창(static/cast.js)의 castStatDelta 가 상태창 수치의 바뀐 양을 맞게 적는지. node 가 있을 때만 돈다."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "canon" / "static"

# cast.js 는 statwin.js 의 금액 · 목록 규칙(SW_AMOUNT, swItems, swKey, swFmt)을 쓴다. app.js 전역은 최소한으로 흉내 낸다
HARNESS = """
const vm = require('vm');
const fs = require('fs');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const noop = { addEventListener() {} };
const ctx = { data, S: {}, actions: {}, document: { ...noop, createElement: () => ({}), head: { appendChild() {} } }, window: noop };
vm.createContext(ctx);
const src = process.argv.slice(1).map((f) => fs.readFileSync(f, 'utf8')).join('\\n;\\n');
vm.runInContext(src + `
;globalThis.out = data.ages ? data.ages.map(isMinorAge) : data.cases.map(([b, a]) => castStatDelta(b === null ? undefined : b, a));`, ctx);
process.stdout.write(JSON.stringify(ctx.out));
"""

CASES = [
    ("4", "5", "+1"),
    ("5", "5", ""),
    ("100", "90", "-10"),
    ("3,000원", "3,300원", "+300원"),
    ("3,000원", "3,000달러", "바뀜"),
    ("1.5", "2", "+0.5"),
    ("화염구, 은신", "화염구, 독 내성", "+독 내성 −은신"),
    ("단검술 Lv.2, 회귀자의 눈", "단검술 Lv.3, 회귀자의 눈", "바뀜"),
    ("회귀자", "영웅", "바뀜"),
    ("회귀자", "", "지움"),
    (None, "12", "새 항목"),
    (None, "", ""),
]


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_stat_delta():
    run = subprocess.run(["node", "-e", HARNESS, str(STATIC / "statwin.js"), str(STATIC / "cast.js")],
                         input=json.dumps({"cases": [[b, a] for b, a, _ in CASES]}),
                         capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    for (b, a, want), got in zip(CASES, json.loads(run.stdout)):
        assert got == want, (b, a, got)


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_minor_age_matches_server():
    from canon import cast

    from .test_body import MINOR_CASES
    run = subprocess.run(["node", "-e", HARNESS, str(STATIC / "statwin.js"), str(STATIC / "cast.js")],
                         input=json.dumps({"ages": MINOR_CASES}), capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == [cast.is_minor_age(a) for a in MINOR_CASES]

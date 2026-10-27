"""집필 화면 본문 속 이름(static/mentions.js)의 이름 찾기 규칙과 문체 밑줄(marks.js)과 함께 그리기. node 가 있을 때만 돈다."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from canon import atlas
from canon.schema import Character, Project, StoryElement

STATIC = Path(__file__).resolve().parent.parent / "canon" / "static"

# marks.js · mentions.js 가 기대는 app.js · passage.js 전역을 최소한으로 흉내 낸다 (document.head 가 없으면 style 을 넣지 않는다)
HARNESS = """
const vm = require('vm');
const fs = require('fs');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const ctx = {
  data, S: {}, actions: {}, P: () => data.project, document: { addEventListener() {} }, window: { addEventListener() {} },
  esc: (t) => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
};
vm.createContext(ctx);
for (const f of process.argv.slice(1)) vm.runInContext(fs.readFileSync(f, 'utf8'), ctx, { filename: f });
vm.runInContext(`
const pick = (t) => mentionRanges(t).map((r) => [t.slice(r.a, r.b), r.id]);
globalThis.out = {
  cases: data.cases.map(pick),
  places: mentionPlaces().map((x) => [x.key, x.name, x.aliases, x.description]),
  html: data.html.map(([t, banned]) => { P().style.banned_phrases = banned; return markHtml(t, markRanges(1, t), mentionsFor(t), true); }),
  shift: data.shift.map(([a, b]) => { const r = mentionRanges(a); return [mentionShift(a, r, b).map((x) => b.slice(x.a, x.b)), mentionRanges(b).map((x) => b.slice(x.a, x.b))]; }),
  few: (() => { const p = data.project; const keep = p.characters; p.characters = keep.filter((c) => c.name === '서윤'); const r = pick(data.alone); p.characters = keep; return r; })(),
};`, ctx);
process.stdout.write(JSON.stringify(ctx.out));
"""

PERF = """
const vm = require('vm');
const fs = require('fs');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const ctx = { data, process, S: {}, actions: {}, P: () => data.project, document: { addEventListener() {} }, window: { addEventListener() {} }, esc: String };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
vm.runInContext(`
mentionRanges('워밍업');
const t0 = process.hrtime.bigint();
let k = 0;
for (let i = 0; i < 20; i++) { mnLast = { sig: null, text: null, ranges: [] }; k = mentionsFor(data.text + i).length; }
globalThis.out = { ms: Number(process.hrtime.bigint() - t0) / 1e6 / 20, k };`, ctx);
process.stdout.write(JSON.stringify(ctx.out));
"""


def _project():
    p = Project()
    p.characters = [Character(id="hero", name="서윤", role="주인공"), Character(id="girl", name="서윤아", role="조연"),
                    Character(id="ally", name="도현", role="조연"), Character(id="x", name="민", role="단역"),
                    Character(id="en", name="Ella", role="단역")]
    p.elements = [StoryElement(id="el1", kind="장소", name="등대", aliases=["빛탑", " "], description="섬 끝의 하얀 등대"),
                  StoryElement(id="el2", kind="물건", name="은장도"), StoryElement(id="el3", kind="장소", name="숲")]
    p.world.locations = ["등대: 겹치는 이름", "수산시장: 새벽 경매", "하르덴 왕궁(북쪽)", ""]
    return p


def _run(script, files, payload):
    run = subprocess.run(["node", "-e", script, *map(str, files)], input=json.dumps(payload),
                         capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_mentions_rules():
    p = _project()
    cases = [
        # 조사 · 호칭이 붙어도 이름만
        "서윤은 등대 앞에 섰다. 서윤이가 웃었다. 서윤의 손, 서윤에게서 온 편지, 서윤님께서는, 서윤이었다.",
        # 더 긴 다른 단어 속 일부는 뺀다: 뒤에 다른 글자(서윤호, 등대지기), 앞에 글자(김서윤, A서윤)
        "서윤호가 왔다. 김서윤이 왔다. 등대지기. A서윤. 서윤2.",
        # 겹치는 이름: 서윤아라는 인물이 있으면 긴 이름이 먼저
        "서윤아는 서윤을 봤다. \"서윤아!\" 도현과 서윤아.",
        # 별칭 · 설정 장소 칸 · 한 글자 이름(민, 숲)은 찾지 않음 · 영문
        "빛탑에서 수산시장으로, 하르덴 왕궁까지. 민은 숲에 갔다. Ella's coat. Ellas.",
    ]
    html = [
        ["서윤은 웃었다. 서윤은 울었다.", ["서윤은"]],  # 문체 밑줄 안에 이름이 통째로
        ["서윤은 등대로 갔다.", ["윤은 등"]],         # 문체 밑줄이 이름 둘에 걸친다
    ]
    shift = [
        ["서윤은 등대로 갔다.", "서윤은 등대로 막 갔다."],  # 이름에 닿지 않게 고치면 그대로 · 뒤는 옮긴다
        ["서윤은 등대로.", "서윤호는 등대로."],      # 이름에 닿게 고치면 다시 찾을 때까지 뺀다
    ]
    out = _run(HARNESS, [STATIC / "marks.js", STATIC / "mentions.js"],
               {"project": json.loads(p.model_dump_json()), "cases": cases, "html": html, "shift": shift, "alone": "서윤아! 서윤아는."})

    c0, c1, c2, c3 = out["cases"]
    assert c0 == [["서윤", "c:hero"], ["등대", "p:el1"]] + [["서윤", "c:hero"]] * 5
    assert c1 == []
    assert c2 == [["서윤아", "c:girl"], ["서윤", "c:hero"], ["서윤아", "c:girl"], ["도현", "c:ally"], ["서윤아", "c:girl"]]
    assert c3 == [["빛탑", "p:el1"], ["수산시장", "p:w:수산시장"], ["하르덴 왕궁", "p:w:하르덴 왕궁"], ["Ella", "c:en"]]
    # 서윤아라는 인물이 없으면 서윤 + 부르는 말 '아'
    assert out["few"] == [["서윤", "c:hero"], ["서윤", "c:hero"]]

    # 장소 목록은 atlas.places 와 같은 키 · 이름 · 다른 이름 · 설명
    want = [[x["key"], x["name"], x["aliases"], x["description"]] for x in atlas.places(p)]
    assert out["places"] == want

    # 문체 밑줄은 쪼개지 않는다 (markNext 가 mark 순서로 찾는다). 걸치는 이름 밑줄을 쪼갠다
    h0, h1 = out["html"]
    assert h0.count("<mark") == 2 and h0.count('class="mn person"') == 2
    assert '<mark class="hl banned"' in h0 and '><span class="mn person" data-mention="c:hero" data-mention-at="0"' in h0
    assert h1.count("<mark") == 1
    assert h1.count('data-mention="c:hero"') == 2 and h1.count('data-mention="p:el1"') == 2  # 서 | 윤, 등 | 대
    assert h1.startswith('<span class="mn person" data-mention="c:hero" data-mention-at="0" tabindex="0" role="button" aria-haspopup="dialog">서</span><mark')

    (moved, fresh0), (dropped, fresh1) = out["shift"]
    assert moved == fresh0 == ["서윤", "등대"]
    assert dropped == ["등대"] and fresh1 == ["등대"]


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_mentions_many_names_fast():
    """인물 50명 · 장소 200곳, 1만 자 본문에서 이름 찾기 한 번이 입력을 막지 않을 만큼 빠른지."""
    p = Project()
    syl = "가나다라마바사아자차카타파하"
    p.characters = [Character(id=f"c{i}", name=f"{syl[i % 14]}{syl[(i // 14) % 14]}윤", role="단역") for i in range(50)]
    p.elements = [StoryElement(id=f"e{i}", kind="장소", name=f"{syl[i % 14]}{syl[(i // 14) % 14]}{syl[(i // 3) % 14]}성",
                               aliases=[f"{syl[i % 14]}{syl[(i // 14) % 14]}탑"]) for i in range(200)]
    names = [c.name for c in p.characters]
    text = "".join(f"{names[i % 50]}은 길을 걸었다. 바람이 불었다. " for i in range(400))[:10000]
    out = _run(PERF, [STATIC / "mentions.js"], {"project": json.loads(p.model_dump_json()), "text": text})
    assert out["k"] > 300
    assert out["ms"] < 50, out

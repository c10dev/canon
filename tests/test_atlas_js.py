"""지도 화면(static/atlas.js) 이름표 놓기가 이름표끼리 겹치지 않는지. node 가 있을 때만 돈다."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ATLAS = Path(__file__).resolve().parent.parent / "canon" / "static" / "atlas.js"

# atlasTextW ~ atlasLabels 만 잘라 esc 만 흉내 내고 돌린다
HARNESS = """
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const part = src.slice(src.indexOf('const atlasTextW'), src.indexOf('\\n// ----- 옆 칸 -----'));
const esc = (t) => String(t);
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
eval(part + ';globalThis.atlasTextW = atlasTextW; globalThis.atlasLabels = atlasLabels;');
process.stdout.write(JSON.stringify({ svg: atlasLabels(data.list, data.sc), w: data.list.map((l) => atlasTextW(l.text, 15 * data.sc)) }));
"""


def _run(labels: list[dict], sc: float = 1.0) -> dict:
    if not shutil.which("node"):
        pytest.skip("node 가 없어요")
    out = subprocess.run(["node", "-e", HARNESS, str(ATLAS)], input=json.dumps({"list": labels, "sc": sc}),
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def _boxes(r: dict, sc: float) -> list[tuple]:
    fs = 15 * sc
    texts = re.findall(r'<text class="at-name[^"]*" x="([-\d.]+)" y="([-\d.]+)" text-anchor="(\w+)"[^>]*>([^<]*)</text>', r["svg"])
    widths = {}
    out = []
    for x, y, a, t in texts:
        w = sum(1.0 if ord(ch) > 0x2E80 else 0.6 for ch in t) * fs
        x0 = float(x) - (w / 2 if a == "middle" else 0 if a == "start" else w)
        out.append((x0, float(y) - fs, x0 + w, float(y) + fs * 0.25))
        widths[t] = w
    return out


def test_crowded_labels_do_not_overlap():
    names = ["흑송촌", "달빛 주막", "수산시장", "물새집", "서낭당", "검은 파도", "효백포구"]
    labels = [{"x": 500 + (i % 3) * 6, "y": 400 + (i // 3) * 6, "text": n, "cls": "", "first": i == 0} for i, n in enumerate(names)]
    r = _run(labels)
    boxes = _boxes(r, 1.0)
    assert len(boxes) == len(names)
    overlaps = [(i, j) for i, a in enumerate(boxes) for j, b in enumerate(boxes) if i < j and a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]]
    assert overlaps == []
    assert "at-leader" in r["svg"]  # 가까이 놓을 자리가 모자라면 멀리 놓고 지시선을 긋는다


def test_lone_label_sits_above_and_scales_with_zoom():
    r = _run([{"x": 100, "y": 100, "text": "등대", "cls": " later", "first": False}], sc=0.5)
    assert 'class="at-name later" x="100.0" y="93.0" text-anchor="middle" font-size="7.50"' in r["svg"]
    assert "at-leader" not in r["svg"] and r["w"] == [15.0]

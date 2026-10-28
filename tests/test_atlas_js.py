"""지도 화면(static/atlas.js)의 계산: 이름표 놓기, 장소 이동 되돌리기, 재생 따라가기. node 가 있을 때만 돈다."""
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
process.stdout.write(JSON.stringify({ svg: atlasLabels(data.list, data.sc, data.fs ?? undefined), w: data.list.map((l) => atlasTextW(l.text, data.fs || 15 * data.sc)) }));
"""

# 되돌리기 · 따라가기 계산 부분만 잘라 돌린다: 입력 { call: 함수 이름, args: [...] }
CALC = """
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const part = src.slice(src.indexOf('// ----- 되돌리기 · 따라가기 계산'), src.indexOf('// ----- 확대 · 이동, 이름표 -----'));
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const fn = eval(part + ';' + data.call);
process.stdout.write(JSON.stringify(fn(...data.args)));
"""


def _node(script: str, data: dict):
    if not shutil.which("node"):
        pytest.skip("node 가 없어요")
    out = subprocess.run(["node", "-e", script, str(ATLAS)], input=json.dumps(data), capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def _run(labels: list[dict], sc: float = 1.0, fs: float | None = None) -> dict:
    return _node(HARNESS, {"list": labels, "sc": sc, "fs": fs})


def _calc(call: str, *args):
    return _node(CALC, {"call": call, "args": list(args)})


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


def test_label_font_size_follows_screen_width():
    # 지도가 화면에 600px 로 보이면 13px 이 되게 지도 단위 21.67 로 쓴다. 글자 테두리도 글자 크기를 따른다
    r = _run([{"x": 100, "y": 100, "text": "등대", "cls": "", "first": False}], sc=1.0, fs=13 * 1000 / 600)
    assert 'font-size="21.67" stroke-width="5.85"' in r["svg"]
    assert r["w"] == [pytest.approx(43.33, abs=0.01)]


def test_pin_undo_keeps_other_places():
    before = {"a": [0.1, 0.1], "b": [0.5, 0.5]}
    after = {"a": [0.2, 0.2], "b": [0.5, 0.5], "c": [0.9, 0.9]}
    d = _calc("atlasPinDiff", before, after)
    assert d == {"b": {"a": [0.1, 0.1], "c": None}, "a": {"a": [0.2, 0.2], "c": [0.9, 0.9]}}
    assert _calc("atlasPinDiff", before, dict(before)) is None
    # 되돌리는 사이 다른 장소 d 가 새로 놓였어도 그 자리는 그대로 둔다
    now = {**after, "d": [0.3, 0.7]}
    undone = _calc("atlasPinApply", now, d["b"])
    assert sorted((x["place"], x["x"], x["y"]) for x in undone) == [("a", 0.1, 0.1), ("b", 0.5, 0.5), ("d", 0.3, 0.7)]


def test_follow_view_moves_only_when_needed():
    view = {"x": 0, "y": 0, "z": 2}  # 1000 × 600 지도의 왼쪽 위 500 × 300
    assert _calc("atlasFollowView", view, [200, 120, 220, 140], 1000, 600) is None
    to = _calc("atlasFollowView", view, [800, 450, 820, 470], 1000, 600)
    assert to["z"] == 2 and to["x"] == pytest.approx(500) and to["y"] == pytest.approx(300)  # 지도 끝을 넘지 않는다
    wide = _calc("atlasFollowView", view, [100, 100, 900, 200], 1000, 600)
    assert 1 <= wide["z"] < 2 and wide["x"] >= 0 and wide["x"] + 1000 / wide["z"] <= 1000.001


def test_find_default_and_pins():
    spots = [{"place": "a", "had": False, "options": [{"x": 0.2, "y": 0.3}]},
             {"place": "b", "had": True, "options": [{"x": 0.4, "y": 0.4}]},
             {"place": "c", "had": False, "options": [{"x": 0.5, "y": 0.5}, {"x": 0.6, "y": 0.6}]}]
    pick = _calc("atlasFindDefault", spots)
    assert pick == {"a": 0, "b": -1, "c": -1}  # 후보가 하나뿐이고 아직 놓지 않은 장소만 고른다
    now = {"b": [0.9, 0.9], "z": [0.1, 0.1]}
    pins = _calc("atlasFindPins", now, spots, {**pick, "c": 1})
    assert sorted((x["place"], x["x"], x["y"]) for x in pins) == [("a", 0.2, 0.3), ("b", 0.9, 0.9), ("c", 0.6, 0.6), ("z", 0.1, 0.1)]

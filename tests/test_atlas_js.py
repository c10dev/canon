"""지도 화면(static/atlas.js)의 계산: 이름표 놓기, 장소 이동 되돌리기, 재생 따라가기, 축척 막대. node 가 있을 때만 돈다."""
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
const taken = data.taken || [];
process.stdout.write(JSON.stringify({ svg: atlasLabels(data.list, data.sc, data.fs ?? undefined, taken), taken, w: data.list.map((l) => atlasTextW(l.text, data.fs || 15 * data.sc)) }));
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


def _run(labels: list[dict], sc: float = 1.0, fs: float | None = None, taken: list | None = None) -> dict:
    return _node(HARNESS, {"list": labels, "sc": sc, "fs": fs, "taken": taken or []})


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


def test_label_avoids_boxes_taken_first():
    # 지도 장식(제목 틀 · 축척 막대)이 먼저 차지한 상자는 비켜 가고, 장식 상자는 taken 에 그대로 남는다
    deco = [50, 70, 150, 95]  # 점 위 자리(y 93 줄)를 덮는다
    r = _run([{"x": 100, "y": 100, "text": "등대", "cls": "", "first": False}], taken=[deco])
    boxes = _boxes(r, 1.0)
    assert len(boxes) == 1
    b = boxes[0]
    assert not (b[0] < deco[2] and b[2] > deco[0] and b[1] < deco[3] and b[3] > deco[1])
    assert r["taken"][0] == deco and len(r["taken"]) == 3  # 장식 + 이름표 + 점


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


def _street(name: str, x: float, length: float = 100) -> dict:
    return {"name": name, "length": length, "mid": [x, 0.5], "angle": 0}


def _picked(streets: list[dict], gap: float = 250) -> list[tuple]:
    return [(s["name"], s["mid"][0]) for s in _calc("atlasLabelPick", streets, 1000, 1000, gap)]


def test_same_name_streets_close_together_get_one_label():
    # 폭이 바뀌어 나뉜 큰길 조각 셋: 서로 화면 폭의 1/4(250) 안이면 가장 긴 조각에만 쓴다
    streets = [_street("테헤란로", 0.10, 80), _street("테헤란로", 0.15, 120), _street("테헤란로", 0.20, 90)]
    assert _picked(streets) == [("테헤란로", 0.15)]


def test_same_name_streets_far_apart_get_one_label_each():
    streets = [_street("테헤란로", 0.10, 120), _street("테헤란로", 0.30, 100), _street("테헤란로", 0.50, 90)]
    assert _picked(streets) == [("테헤란로", 0.10), ("테헤란로", 0.50)]  # 0.30 은 0.10 에서 200 이라 건너뛴다
    assert len(_picked(streets, gap=100)) == 3  # 확대하면 gap 이 줄어 더 자주 보인다


def test_different_names_and_unnamed_streets():
    streets = [_street("테헤란로", 0.10), _street("강남대로", 0.12), _street("논현로", 0.14), _street("", 0.5)]
    assert sorted(_picked(streets)) == [("강남대로", 0.12), ("논현로", 0.14), ("테헤란로", 0.10)]  # 이름 없는 길은 그리지 않는다


def test_label_pick_skips_only_against_drawn_labels():
    # 자리가 없어 못 그린 조각(draw 가 거짓)은 가까운 같은 이름을 막지 않는다
    script = CALC.replace("process.stdout.write(JSON.stringify(fn(...data.args)));",
                          "process.stdout.write(JSON.stringify(fn(...data.args, (st) => st.length !== 120).map((s) => s.mid[0])));")
    streets = [_street("테헤란로", 0.10, 120), _street("테헤란로", 0.15, 100)]
    assert _node(script, {"call": "atlasLabelPick", "args": [streets, 1000, 1000, 250]}) == [0.15]


def test_scale_bar_picks_round_value_near_a_sixth():
    # 1000 단위 지도가 1km(1단위 = 1m): 보이는 폭 1/6 은 약 167m 라 200m
    assert _calc("atlasScaleBar", 1, 1, 1000) == {"meters": 200, "label": "200m", "units": 200}
    # 4배 확대하면 보이는 폭 250m, 1/6 은 약 42m 라 50m
    assert _calc("atlasScaleBar", 1, 4, 1000) == {"meters": 50, "label": "50m", "units": 50}
    # 지도 가로 6km(1단위 = 6m): 1km, 4배면 250m 에 가까운 200m
    assert _calc("atlasScaleBar", 6, 1, 1000) == {"meters": 1000, "label": "1km", "units": pytest.approx(166.667, abs=0.001)}
    assert _calc("atlasScaleBar", 6, 4, 1000)["label"] == "200m"
    # 큰 지도(가로 30km)는 5km, 아주 작게 보면 10m 아래로 내려가지 않는다
    assert _calc("atlasScaleBar", 30, 1, 1000)["label"] == "5km"
    assert _calc("atlasScaleBar", 0.05, 8, 1000)["label"] == "10m"


def test_scale_bar_needs_known_scale():
    for mpu in (0, -1, None, "x"):
        assert _calc("atlasScaleBar", mpu, 1, 1000) is None


def _ward(name: str, x: float, size: float = 0.04) -> dict:
    return {"name": name, "shape": [[x, 0.5], [x + size, 0.5], [x + size, 0.5 + size], [x, 0.5 + size]]}


def test_same_name_wards_close_together_get_one_label():
    # 도시의 '상인' 구역 셋이 화면 폭의 1/4(250) 안에 붙어 있으면 가장 넓은 구역 하나에만 쓴다
    wards = [_ward("상인", 0.10, 0.03), _ward("상인", 0.15, 0.05), _ward("상인", 0.20, 0.04)]
    picked = _calc("atlasWardPick", wards, 1000, 1000, 250)
    assert [(w["name"], w["shape"][0][0]) for w in picked] == [("상인", 0.15)]
    assert picked[0]["mid"] == [pytest.approx(0.175), pytest.approx(0.525)]  # 그릴 자리는 넓이 가운데
    assert picked[0]["length"] == pytest.approx(2500)  # 넓이(지도 단위²)


def test_same_name_wards_far_apart_get_one_label_each():
    wards = [_ward("빈민", 0.10), _ward("빈민", 0.60), _ward("상인", 0.12)]
    picked = _calc("atlasWardPick", wards, 1000, 1000, 250)
    assert sorted((w["name"], w["shape"][0][0]) for w in picked) == [("빈민", 0.10), ("빈민", 0.60), ("상인", 0.12)]
    near = [_ward("빈민", 0.10), _ward("빈민", 0.20)]
    assert len(_calc("atlasWardPick", near, 1000, 1000, 250)) == 1
    assert len(_calc("atlasWardPick", near, 1000, 1000, 250 / 4)) == 2  # 4배 확대하면 gap 이 줄어 둘 다 보인다


def test_place_label_moves_off_character_token():
    # 인물 표는 장소 점의 오른쪽 아래에 놓이고, 그 상자를 먼저 taken 에 넣으면 장소 이름표가 표를 덮지 않는다
    tok = _calc("atlasTokenAt", 100, 100, 0, 1, 1)
    assert tok == {"x": 116, "y": 116, "box": [104, 104, 128, 128]}
    pair = _calc("atlasTokenAt", 100, 100, 0, 2, 1)
    assert pair["box"][2] - pair["box"][0] == 24  # 여럿이면 둘레로 나뉘어도 표 크기는 같다
    # 위 · 아래 · 왼쪽을 다른 이름표가 막아, 비키지 않으면 오른쪽(표 위)에 놓이는 이름
    blocks = [[60, 60, 140, 96], [60, 112, 98, 140], [40, 90, 92, 112]]
    label = {"x": 100, "y": 100, "text": "수산시장", "cls": "", "first": False}
    free = _boxes(_run([label], taken=blocks), 1.0)[0]
    t = tok["box"]
    assert free[0] < t[2] and free[2] > t[0] and free[1] < t[3] and free[3] > t[1]  # 표를 넣지 않으면 겹친다 (고치기 전)
    r = _run([label], taken=blocks + [t])
    b = _boxes(r, 1.0)[0]
    assert not (b[0] < t[2] and b[2] > t[0] and b[1] < t[3] and b[3] > t[1])
    assert r["taken"][3] == t  # 표 상자는 그대로 남아 뒤의 구역 · 길 이름도 비켜 간다

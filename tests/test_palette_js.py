"""작업 목록 남은 시간(static/app.js jobLeft)과 명령 팔레트 검색(static/palette.js)을 node 로 맞춰 본다. node 가 있을 때만 돈다."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "canon" / "static"
PALETTE = STATIC / "palette.js"

# palette.js 가 기대는 app.js 전역을 최소한으로 흉내 낸다
HARNESS = """
const vm = require('vm');
const fs = require('fs');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const ctx = {
  data, S: {}, actions: {}, STATUS: { draft: '플롯 초안', confirmed: '플롯 확정', written: '본문 작성됨', finalized: '반영 완료' },
  document: { addEventListener() {}, createElement: () => ({}), head: { appendChild() {} } }, window: { addEventListener() {} },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + `
;globalThis.out = {
  inside: data.queries.map((q) => paletteMatch(paletteItems(data.inside), q).map((it) => [it.kind, it.label, it.href || it.act])),
  outside: data.queries.map((q) => paletteMatch(paletteItems({ inProject: false }), q).map((it) => it.label)),
};`, ctx);
process.stdout.write(JSON.stringify(ctx.out));
"""

B = "#/p/demo"
NAV = {
    "steps": [["home", B, "H", "작품 홈"], ["setup", B + "/setup", "1", "설정 도우미"], ["style", B + "/style", "2", "문체 레퍼런스"],
              ["arc", B + "/arc", "3", "기승전결 · 플롯"], ["write", B + "/write/3", "4", "집필"], ["review", B + "/review/3", "5", "상태 승인"]],
    "auto": ["auto", B + "/auto", "A", "자동 집필"],
    "tools": [["cast", B + "/cast", "人", "인물 · 관계도", True], ["atlas", B + "/atlas", "地", "지도", False],
              ["brief", B + "/brief/3", "✎", "작업지시서 (API 없이)", True]],
    "apart": [["research", B + "/research", "R", "연구 · 모델 실험"], ["usage", B + "/usage", "$", "사용량 · 비용"]],
    "foot": [["#/settings", "모델 · API 키 설정"], ["#/usage", "모든 작품 사용량 · 비용"], ["#/styles", "문체 라이브러리"], ["#/", "작품 목록"]],
}
INSIDE = {
    "inProject": True, "base": B, "nav": NAV, "next": ["3화 상태 승인", B + "/review/3"], "canSave": False,
    "episodes": [{"n": n, "title": "추격전" if n == 7 else f"{n}화 제목", "status": "finalized" if n < 3 else "written" if n == 3 else "confirmed"}
                 for n in range(1, 16)],
    "characters": [{"id": "c1", "name": "한서윤"}, {"id": "c 2", "name": "도윤"}],
}


def run(queries, inside=INSIDE):
    r = subprocess.run(["node", "-e", HARNESS, str(PALETTE)], input=json.dumps({"inside": inside, "queries": queries}),
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_palette_matches_names_and_episodes():
    qs = ["", "3화", "3", "1", "12 화", "한서", "ㅎㅅㅇ", "도윤", "추격", "인물", "api", "집필", "없는말", "저장", "설정"]
    out = run(qs)
    got = dict(zip(qs, out["inside"]))

    # 검색어가 없으면 동작과 화면만 (화 · 인물은 찾을 때만)
    kinds = {k for k, _, _ in got[""]}
    assert kinds == {"act", "screen"}
    assert got[""][0] == ["act", "다음 할 일 · 3화 상태 승인", B + "/review/3"]
    labels = [lab for _, lab, _ in got[""]]
    # 사이드바 이름 그대로 (접힌 도구도 찾는다)
    for lab in ["작품 홈", "설정 도우미", "집필", "상태 승인", "자동 집필", "지도", "작업지시서 (API 없이)", "연구 · 모델 실험", "문체 라이브러리", "작품 목록"]:
        assert lab in labels

    # 화 번호: 본문을 쓴 화는 상태 승인이 먼저, 쓰지 않은 화는 집필
    assert got["3화"][:2] == [["ep", "3화 상태 승인", B + "/review/3"], ["ep", "3화 집필", B + "/write/3"]]
    assert got["3"] == got["3화"]
    assert got["12 화"] == [["ep", "12화 집필", B + "/write/12"]]
    # '1' 은 1화가 먼저, 그다음 10~15화
    assert [lab for _, lab, _ in got["1"]] == ["1화 집필"] + [f"{n}화 집필" for n in range(10, 16)]

    # 인물 이름 · 초성 → 인물 · 관계도의 그 인물
    assert got["한서"][0] == ["char", "한서윤", B + "/cast/c%3Ac1"]
    assert got["ㅎㅅㅇ"][0][1] == "한서윤"
    assert got["도윤"][0] == ["char", "도윤", B + "/cast/c%3Ac%202"]
    # 화 제목으로도 찾는다
    assert got["추격"] == [["ep", "7화 집필", B + "/write/7"]]
    assert got["인물"][0] == ["screen", "인물 · 관계도", B + "/cast"]
    assert got["api"][0][1] == "작업지시서 (API 없이)" and ["screen", "모델 · API 키 설정", "#/settings"] in got["api"]
    assert got["집필"][0] == ["screen", "집필", B + "/write/3"] and ["screen", "자동 집필", B + "/auto"] in got["집필"]
    assert got["없는말"] == []
    assert got["저장"] == []  # 저장할 것이 없으면 '저장' 동작을 두지 않는다
    assert run(["저장"], {**INSIDE, "canSave": True})["inside"][0][0] == ["act", "저장", "save"]

    # 작품 밖: 작품 목록과 설정만
    outside = dict(zip(qs, out["outside"]))
    assert outside[""] == ["작품 목록", "모델 · API 키 설정"]
    assert outside["설정"] == ["모델 · API 키 설정"]
    assert outside["3화"] == [] and outside["한서"] == []


JOB_LEFT = """
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const m = src.match(/\\nfunction jobLeft\\(j, now\\) \\{[\\s\\S]*?\\n\\}\\n/);
if (!m) throw new Error('jobLeft 를 찾지 못함');
const jobLeft = new Function(m[0] + '; return jobLeft;')();
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map(([j, now]) => jobLeft(j, now))));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_job_left():
    cases = [
        ({"total": 1, "done": 0, "started": 0}, 100, ""),       # 단계가 하나뿐
        ({"total": 5, "done": 0, "started": 0}, 100, ""),       # 아직 한 단계도 끝나지 않음
        ({"total": 10, "done": 2, "started": 0}, 120, "약 8분 남음"),   # 한 단계 60초 × 8
        ({"total": 4, "done": 3, "started": 0}, 90, "곧 끝나요"),    # 30초 남음
        ({"total": 3, "done": 1, "started": 0}, 29, "곧 끝나요"),    # 58초 남음
        ({"total": 3, "done": 1, "started": 0}, 30, "약 1분 남음"),  # 정확히 60초
        ({"total": 5, "done": 5, "started": 0}, 300, "곧 끝나요"),   # 다 끝나고 마무리 중
        ({"total": 6, "done": 2, "started": 1000}, 900, "곧 끝나요"),  # 서버 시각이 앞서 있어도 음수로 가지 않는다
        ({"total": 20, "done": 1, "started": 0}, 45, "약 14분 남음"),  # 45초 × 19 = 855초 ≈ 14.25분
    ]
    r = subprocess.run(["node", "-e", JOB_LEFT, str(STATIC / "app.js")], input=json.dumps([[j, now] for j, now, _ in cases]),
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [want for _, _, want in cases]

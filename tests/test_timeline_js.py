"""작품 속 시간 화면(static/timeline.js)의 달력이 timeline.calendar · day_label · when 과 같게 세는지,
상태 정리 경고에서 본문 문장을 찾는 passage.js warnQuote 가 맞게 찾는지. node 가 있을 때만 돈다."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from canon import timeline
from canon.schema import Project, StoryTime

STATIC = Path(__file__).resolve().parent.parent / "canon" / "static"

# timeline.js · passage.js 가 기대는 app.js · chat.js 전역을 최소한으로 흉내 낸다
HARNESS = """
const vm = require('vm');
const fs = require('fs');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const el = () => ({ appendChild() {}, set textContent(v) {} });
const ctx = {
  data, S: {}, actions: {}, CHAT_TOPICS: {}, P: () => data.project, ep: () => null,
  document: { addEventListener() {}, createElement: el, head: el() },
};
vm.createContext(ctx);
for (const f of process.argv.slice(1)) vm.runInContext(fs.readFileSync(f, 'utf8'), ctx);
vm.runInContext(`globalThis.out = {
  labels: data.cases.map((c) => { data.project.timeline.start = c.start; return c.days.map(tlDayLabel); }),
  whens: (data.project.timeline.start = data.start, data.whens.map(tlWhen)),
  quotes: data.warns.map((w) => warnQuote(w, data.text)),
};`, ctx);
process.stdout.write(JSON.stringify(ctx.out));
"""

CASES = [
    "1일째 월요일",
    "2024년 3월 4일 월요일, 초봄",  # 연도가 있으면 적은 요일보다 날짜가 이긴다
    "2024년 3월 4일 금요일",
    "3월 2일",
    "2월 29일 목요일",
    "2024년 12월 30일",
    "2월 30일 화요일",  # 없는 날: 요일만
    "초봄",
    "",
]
DAYS = [0, 1, 2, 7, 30, 59, 400]
TEXT = ("광장 게시판에 공고문이 붙어 있었다.\n"
        "'29일 후 금요일 오전 10시, 대성당 앞에서 선발 시험을 치른다.' 리안은 손가락으로 날짜를 짚었다. "
        "그는 고개를 끄덕였다.")
WARNS = [
    "시간/요일 모순: 본문 «29일 후 금요일 오전 10시, 대성당 앞에서 선발 시험을 치른다.» 의 요일이 맞지 않습니다.",
    "시간/요일 모순: 게시판 공고문에 '29일 후 금요일 오전 10시'라고 적혀 있습니다.",
    "요일 모순: «29일 뒤 금요일 오전 10시에 대성당 앞에서 선발 시험»",  # 조금 바꿔 옮김 → 겹치는 문장
    "플롯 사건 '시험 등록'이 빠졌습니다.",  # 본문 문장이 아님
    "설정 위반: 말투가 다릅니다.",
]


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_timeline_js_calendar_and_warn_quote():
    p = Project()
    whens = [StoryTime(day=3, part="밤", label="수요일 비 옴"), StoryTime(day=3, part="밤", label="비 옴"),
             StoryTime(day=0, label="그날 밤"), StoryTime()]
    p.timeline.start = "2024년 3월 4일 월요일"
    data = {"project": json.loads(p.model_dump_json()), "cases": [{"start": s, "days": DAYS} for s in CASES],
            "start": p.timeline.start, "whens": [json.loads(t.model_dump_json()) for t in whens], "warns": WARNS, "text": TEXT}
    files = [str(STATIC / "timeline.js"), str(STATIC / "passage.js")]
    run = subprocess.run(["node", "-e", HARNESS, *files], input=json.dumps(data),
                         capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    out = json.loads(run.stdout)

    for start, got in zip(CASES, out["labels"]):
        p.timeline.start = start
        assert got == [timeline.day_label(p, d) for d in DAYS], start
    p.timeline.start = "2024년 3월 4일 월요일"
    assert out["whens"] == [timeline.when(p, t) for t in whens]
    assert out["whens"][0] == "3일째 밤 (3월 6일 수요일)" and out["whens"][1] == "3일째 밤 (3월 6일 수요일, 비 옴)"

    sentence = "'29일 후 금요일 오전 10시, 대성당 앞에서 선발 시험을 치른다.'"
    assert out["quotes"][0] == "29일 후 금요일 오전 10시, 대성당 앞에서 선발 시험을 치른다."
    assert out["quotes"][1] == "29일 후 금요일 오전 10시"
    assert out["quotes"][2] == sentence
    assert out["quotes"][3:] == ["", ""]

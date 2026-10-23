"""집필 화면 문체 표시(static/marks.js)가 metrics.device_* · prompts.device_block 과 같은 규칙으로 세는지. node 가 있을 때만 돈다."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from canon import metrics, prompts
from canon.schema import Episode, EpisodePlot, Project, StyleDevice

MARKS = Path(__file__).resolve().parent.parent / "canon" / "static" / "marks.js"
MANIA = "씻고 온다는 건 온다는 거지? 온다는 건 싫어하지 않았다는 거겠지?"

# marks.js 가 기대는 app.js · passage.js 전역을 최소한으로 흉내 낸다
HARNESS = """
const vm = require('vm');
const fs = require('fs');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const ctx = {
  data, S: {}, actions: {}, P: () => data.project, document: { addEventListener() {} },
  esc: (t) => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + `
;globalThis.out = {
  states: data.ns.map((n) => deviceStates(n, (P().episodes.find((e) => e.plot.number === n) || {}).text || '')
    .map((s) => ({ last: s.last, rest: s.rest, used: s.used, hits: s.hits }))),
  ranges: markRanges(data.ns[0], data.text).map((r) => [r.a, r.b, r.kind]),
  sentence: sentenceAt(data.text, data.text.indexOf('다는 건'), data.text.indexOf('다는 건') + 4),
};`, ctx);
process.stdout.write(JSON.stringify(ctx.out));
"""


def _plot(n):
    return EpisodePlot(number=n, act="기", title=f"{n}화", summary="", events=[], characters=[],
                       emotional_shift="", ending_hook="")


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_marks_js_counts_like_metrics():
    p = Project()
    p.style.devices = [StyleDevice(name="자문자답 망상", cues=["~다는 건", " 거지?"], every=3),
                       StyleDevice(name="빈 장치", cues=[]), StyleDevice(name="", cues=["다는 건"])]
    p.style.banned_phrases = ["묘한", " 묘한 "]
    texts = {1: MANIA, 2: "다는 건 한 번만.", 3: "", 4: f"묘한 날. {MANIA}", 5: "평범한 화.", 7: MANIA}
    for n, t in texts.items():
        p.episodes.append(Episode(plot=_plot(n), status="written" if t else "confirmed", text=t))
    ns = sorted(texts)
    text = f"묘한 날이었다. {MANIA}"
    run = subprocess.run(["node", "-e", HARNESS, str(MARKS)], input=json.dumps({"project": json.loads(p.model_dump_json()), "ns": ns, "text": text}),
                         capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    out = json.loads(run.stdout)

    d = p.style.devices[0]
    for n, states in zip(ns, out["states"]):
        assert len(states) == 2  # 이름 없는 장치는 빠진다 (device_block 과 같다)
        s = states[0]
        last = metrics.device_last(p.episodes, d.cues, n)
        assert s["last"] == last and s["hits"] == metrics.device_hits(texts[n], d.cues)
        assert s["used"] == metrics.device_used(texts[n], d.cues)
        assert s["rest"] == ("이번 화에는 쓰지 않습니다" in prompts.device_block(p, n).splitlines()[0])
        assert states[1] == {"last": 0, "rest": False, "used": False, "hits": 0}

    # 알아보는 글자가 두 번 넘게 나와 장치를 쓴 글이므로 밑줄: 금지 표현 한 번(같은 표현은 한 번만), 다는 건 두 번, 거지? 한 번
    kinds = [k for _, _, k in out["ranges"]]
    assert kinds[0] == "banned" and kinds.count("banned") == 1 and kinds.count("device") == 3
    a, b, _ = out["ranges"][1]
    assert text[a:b] == "다는 건"
    assert text[out["sentence"]["start"]:out["sentence"]["end"]] == "씻고 온다는 건 온다는 거지?"

"""node 대조 시험 공용 하네스: canon/static/*.js 를 vm 하나에 차례로 읽고, 식 하나를 돌려 JSON 으로 받는다.
화면 파일이 맨 위에서 거는 브라우저 전역(document, window, localStorage …)은 무엇을 불러도 조용히 넘어가는 대역으로 둔다.
식 안에서 S.project = data.project 처럼 data 로 상태를 넣는다. 식이 Promise 면 풀린 값을 받는다."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "canon" / "static"

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node 없음")

HARNESS = """
const vm = require('vm');
const fs = require('fs');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const any = new Proxy(function () {}, {
  get: (t, k) => (k === Symbol.toPrimitive ? () => '' : k === 'then' ? undefined : any),
  apply: () => any, construct: () => any,
});
const ctx = { data, console, structuredClone, document: any, window: any, localStorage: any, sessionStorage: any, navigator: any,
  location: any, history: any, matchMedia: any, fetch: any, setInterval() {}, setTimeout() {}, clearTimeout() {}, requestAnimationFrame() {} };
vm.createContext(ctx);
for (const f of process.argv.slice(2)) vm.runInContext(fs.readFileSync(f, 'utf8'), ctx, { filename: f });
// 식이 Promise 를 돌려주면(async 함수 시험) 풀린 값을 쓴다
Promise.resolve(vm.runInContext(process.argv[1], ctx)).then((v) => process.stdout.write(JSON.stringify(v)));
"""


def run_js(files: list[str], expr: str, data):
    """canon/static 의 files 를 읽은 vm 에서 expr 을 돌린 값."""
    # 공용 목차 틀(outline.js)은 화면 파일이 맨 위에서 부르므로 app.js 바로 뒤에 늘 함께 읽는다 (index.html 차례)
    if "app.js" in files and "outline.js" not in files:
        files = [*files[: files.index("app.js") + 1], "outline.js", *files[files.index("app.js") + 1:]]
    paths = [str(STATIC / f) for f in files]
    run = subprocess.run(["node", "-e", HARNESS, expr, *paths], input=json.dumps(data, ensure_ascii=False),
                         capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def episode(n: int, **kw):
    """시험용 화. plot 칸은 plot 사전으로, 나머지는 Episode 칸으로 받는다."""
    from canon.schema import Episode, EpisodePlot
    plot = {"act": "기", "title": "", "summary": "", "events": [], "characters": [], "emotional_shift": "", "ending_hook": ""}
    return Episode(plot=EpisodePlot(number=n, **{**plot, **kw.pop("plot", {})}), **kw)


def dump(m) -> dict:
    return json.loads(m.model_dump_json())

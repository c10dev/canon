"""멈춘 작업이 아직 AI 응답을 기다리는 동안 같은 화의 AI 작업 버튼을 잠근다 (app.js epWaiting · jobBtn, write.js writeGo).
서버 jobs.waiting_on 이 409 로 막는 경우와 같다. node 가 있을 때만 돈다."""
import re

from canon import jobs

from .jsvm import STATIC, needs_node, run_js

FILES = re.findall(r'src="/static/([a-z-]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))


@needs_node
def test_waiting_job_locks_same_episode_buttons():
    got = run_js(FILES, """(() => {
      S.name = 'wt'; S.project = { meta: { form: 'short' }, settings: {}, episodes: [] };
      S.jobsHeld = [{ id: 'a', project: 'wt', kind: 'board', ep: 3, label: '3화 스토리보드', status: 'cancelled', waiting: true }];
      const out = {
        kinds: [...EP_AI_KINDS].sort(),
        write: jobBtn('write', 3, '3화 쓰기'), check: jobBtn('check', 3, '검수하기'),
        other: jobBtn('write', 4, '4화 쓰기'), plots: jobBtn('plots', 3, '초안'), elsewhere: jobBtn('write', 3, '쓰기', 'b'),
        note: epWaitNote(3), go: writeGo(3, []),
      };
      S.jobsHeld[0].waiting = false;
      out.free = jobBtn('write', 3, '3화 쓰기');
      out.freeNote = epWaitNote(3);
      return out;
    })()""", {})
    assert got["kinds"] == sorted(jobs.EP_AI_KINDS)  # 서버와 같은 종류
    for b in (got["write"], got["check"]):
        assert 'aria-disabled="true"' in b["attr"] and b["label"].endswith("· 응답 기다리는 중")
    for b in (got["other"], got["plots"], got["elsewhere"], got["free"]):
        assert b["attr"] == "" and "응답 기다리는 중" not in b["label"]
    assert "'3화 스토리보드'가 아직 AI 응답을 기다려요" in got["note"] and got["freeNote"] == ""
    assert got["go"]["wait"] and 'aria-disabled="true"' in got["go"]["primary"] and "응답 기다리는 중" in got["go"]["primary"]

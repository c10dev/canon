"""연구 · 상태창 시험 · 사용량 화면의 순수 함수(static/research.js · stattrial.js · usage.js).
백엔드 칩 후보, 쪽마다 마지막 결과 요약, 틀린 비율 막대, 막대 축 눈금. node 가 있을 때만 돈다."""
from .jsvm import needs_node, run_js

FILES = ["app.js", "home.js", "research.js", "stattrial.js", "usage.js"]


@needs_node
def test_backend_chips_dedupe_and_filter():
    got = run_js(FILES, """[
      rsCands({ config: data.config, probe: data.probe, probeUrl: 'http://gpu:8001/v1', log: data.log }).map((c) => [c.b.provider, c.b.model, c.b.url, c.sub]),
      rsCands({ config: data.config, log: data.log, kinds: ['local', 'mock'] }).map((c) => c.b.provider + ':' + c.b.model),
      [rsParse('local:qwen3-32b'), rsParse('gemini'), rsParse('claude:x')],
    ]""", {"config": {"provider": "gemini", "model_setting": "gemini-4-argon", "local_url": "http://gpu:8001/v1", "local_model": "qwen3-32b"},
           "probe": {"models": [{"id": "qwen3-32b"}, {"id": "gemma-4-27b"}]},
           "log": [{"kind": "sample", "rows": [{"backend": "local:qwen3-32b"}, {"backend": "gemini"}]}, {"kind": "compare", "backends": ["local:gemma-4-27b", "mock"]}]})
    chips, local_only, parsed = got
    # 설정값 둘 → 서버 점검 모델 → 기록 순서, 같은 백엔드는 한 번만 (설정 주소와 같은 점검 주소는 비운다)
    assert chips == [["gemini", "", "", "Gemini · 설정값 gemini-4-argon"], ["local", "", "", "로컬 · 설정값 qwen3-32b"],
                     ["local", "qwen3-32b", "", "로컬 · 서버 점검에서"], ["local", "gemma-4-27b", "", "로컬 · 서버 점검에서"],
                     ["mock", "", "", "기록에서"]]
    assert local_only == ["local:", "local:qwen3-32b", "local:gemma-4-27b", "mock:"]  # 판단기 칩은 로컬 · mock 만
    assert parsed == [{"provider": "local", "model": "qwen3-32b", "url": ""}, {"provider": "gemini", "model": "", "url": ""}, None]


@needs_node
def test_brief_marks_what_needs_a_look():
    latest = {
        "budget": {"time": "t1", "backend": "local:qwen3-32b", "limit": 32768, "first_over": 8, "first_tight": 7},
        "check": {"time": "t2", "episode": 4, "planted": [{}, {}, {}], "runs": [{"mode": "full", "ok": True, "found": 3}, {"mode": "budget", "ok": True, "found": 2}]},
        "stage": {"time": "t3", "stage": "style", "ok": True, "empty": ["pacing"], "attempts": 2},
    }
    got = run_js(FILES, """[
      rsBrief('budget', { latest: data.latest }),
      rsBrief('check', { latest: data.latest }),
      rsBrief('stage', { latest: data.latest, stages: { style: '문체 분석' } }),
      rsBrief('compare', { latest: data.latest, openCmp: [{ episode: 5 }, { episode: 6 }] }),
      rsBrief('sample', { latest: {} }),
      rsBrief('probe', { probeError: '연결할 수 없어요' }),
      rsBrief('budget', { latest: { budget: { time: '오늘 14:02', limit: 0 } }, when: (t) => t }).st,
    ]""", {"latest": latest})
    budget, check, stage, compare, sample, probe, day = got
    assert budget["warn"] and budget["chip"] == ["bad", "8화부터 넘침"] and budget["st"] == "8화 넘침"
    assert check["chip"] == ["warn", "5/6 찾음"] and check["st"] == "5/6" and not check["warn"]
    assert stage["chip"] == ["warn", "빈 칸 1"] and "문체 분석 · 시도 2번" in stage["line"]
    assert compare["warn"] and compare["st"] == "고르기" and compare["line"].startswith("5 · 6화")
    assert sample == {"st": "", "chip": None, "line": "아직 없어요", "warn": False}
    assert probe["warn"] and probe["chip"] == ["bad", "연결 안 됨"]
    assert day == "오늘"  # 목차 꼬리는 날만


@needs_node
def test_log_line_and_check_calls():
    got = run_js(FILES, """[
      rsLogLine({ kind: 'statwin', episodes: [2, 3], summary: [{ error_rate: 0.17 }, { error_rate: null }] }),
      rsLogLine({ kind: 'pick', episode: 5, picked: 'mock', adopted: true }),
      rsCheckCalls(false, false, false), rsCheckCalls(true, true, false), rsCheckCalls(false, false, true),
    ]""", {})
    assert got[0] == "2 · 3화 × 2방식 · 틀린 값 17% · -"
    assert got[1] == "5화 · mock 고름 (본문 채택)"
    assert got[2:] == [{"n": 3, "more": False}, {"n": 8, "more": True}, {"n": 3, "more": True}]


@needs_node
def test_stattrial_bars_scale_to_largest():
    got = run_js(FILES, "stBars(data.s)", {"s": [
        {"label": "상태창 없음", "error_rate": 0.2, "shown": 10, "wrong": 2},
        {"label": "지금 방식", "error_rate": 0.05, "shown": 20, "wrong": 1},
        {"label": "고른 줄 형식", "error_rate": None, "shown": 0, "wrong": 0},
    ]})
    assert [(b["pct"], b["width"]) for b in got] == [(20, 100), (5, 25), (None, 0)]
    assert got[1]["detail"] == "보인 값 20개 중 1개 틀림"


@needs_node
def test_usage_ticks_cover_max():
    got = run_js(FILES, "[usageTicks(0.52), usageTicks(82), usageTicks(0), usageTicks(0.004), usageTicks(3)]", {})
    assert got == [[0, 0.2, 0.4, 0.6], [0, 50, 100, 150], [0, 1, 2, 3], [0, 0.002, 0.004, 0.006], [0, 1, 2, 3]]

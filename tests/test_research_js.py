"""연구 · 상태창 시험 · 사용량 화면의 순수 함수(static/research.js · stattrial.js · usage.js).
백엔드 칩 후보, 쪽마다 마지막 결과 요약, 틀린 비율 막대, 막대 축 눈금. node 가 있을 때만 돈다."""
from .jsvm import needs_node, run_js

FILES = ["app.js", "home.js", "research.js", "stattrial.js", "usage.js"]


@needs_node
def test_backend_chips_dedupe_and_filter():
    got = run_js(FILES, """[
      rsCands({ config: data.config, probe: data.probe, probeUrl: 'http://gpu:8001/v1', log: data.log }).map((c) => [c.b.provider, c.b.model, c.b.url, c.sub]),
      rsCands({ config: data.config, log: data.log, kinds: ['local', 'mock'] }).map((c) => c.b.provider + ':' + c.b.model),
      [rsParse('local:qwen3-32b'), rsParse('gemini'), rsParse('claude:x'), rsParse('openai:x')],
    ]""", {"config": {"provider": "gemini", "model_setting": "gemini-4-argon", "local_url": "http://gpu:8001/v1", "local_model": "qwen3-32b"},
           "probe": {"models": [{"id": "qwen3-32b"}, {"id": "gemma-4-27b"}]},
           "log": [{"kind": "sample", "rows": [{"backend": "local:qwen3-32b"}, {"backend": "gemini"}]}, {"kind": "compare", "backends": ["local:gemma-4-27b", "mock"]}]})
    chips, local_only, parsed = got
    # 설정값 둘 → 서버 점검 모델 → 기록 순서, 같은 백엔드는 한 번만 (설정 주소와 같은 점검 주소는 비운다)
    assert chips == [["gemini", "", "", "Gemini · 설정값"], ["local", "", "", "로컬 · 설정값"],
                     ["local", "qwen3-32b", "", "로컬 · 서버 점검에서"], ["local", "gemma-4-27b", "", "로컬 · 서버 점검에서"],
                     ["mock", "", "", "기록에서"]]
    assert local_only == ["local:", "local:qwen3-32b", "local:gemma-4-27b", "mock:"]  # 판단기 칩은 로컬 · mock 만
    assert parsed == [{"provider": "local", "model": "qwen3-32b", "url": ""}, {"provider": "gemini", "model": "", "url": ""},
                      {"provider": "claude", "model": "x", "url": ""}, None]


@needs_node
def test_claude_chips_only_when_set_up():
    got = run_js(FILES, """[
      rsClaudeKinds({ provider: 'gemini' }),
      rsClaudeKinds({ provider: 'gemini', stages: { check: { provider: 'claude' } } }),
      rsClaudeKinds({ provider: 'gemini', anthropic_key_hint: '…abcd' }),
      rsCands({ config: data.config, log: data.log }).map((c) => [c.b.provider, c.b.model, c.sub]),
      rsCands({ config: data.config, log: data.log, kinds: ['local', 'mock'] }).map((c) => c.b.provider),
    ]""", {"config": {"provider": "claude", "model_setting": "gemini-4-argon", "claude_model": "claude-opus-5-5", "stages": {"write": {"provider": "gemini"}}},
           "log": [{"kind": "compare", "backends": ["claude-api:claude-opus-5-5", "gemini"]}]})
    plain, by_stage, by_key, chips, judge = got
    assert plain == [] and by_stage == ["claude"] and by_key == ["claude-api"]  # 쓰지 않는 Claude 는 칩으로 내놓지 않는다
    assert chips == [["gemini", "", "Gemini · 설정값"], ["local", "", "로컬 · 설정값"],
                     ["claude", "", "Claude 구독 · 설정값"], ["claude-api", "claude-opus-5-5", "기록에서"]]
    assert judge == ["local"]  # 판단기 칩에는 Claude 가 없다


@needs_node
def test_default_model_and_claude_missing():
    got = run_js(FILES, """[
      ['gemini', 'local', 'claude', 'claude-api', 'mock'].map((p) => defaultModelName(p, data.full)),
      ['gemini', 'local', 'claude', 'claude-api'].map((p) => defaultModelName(p, {})),
      [claudeMissing('claude-api', {}), claudeMissing('claude-api', { anthropic_key_hint: '…abcd' }),
       claudeMissing('claude', {}, { claude: 'install' }), claudeMissing('claude', {}, { claude: 'login' }),
       claudeMissing('claude', {}, { claude: 'ok' }), claudeMissing('claude', {}, null), claudeMissing('gemini', {})],
      (() => { S.config = {}; S.health = null; return [backendOption('claude-api', 'Claude API', 'gemini'), backendOption('claude-api', 'Claude API', 'claude-api')]; })(),
    ]""", {"full": {"model_setting": "gemini-4-argon", "local_model": "qwen3-32b", "claude_model": "claude-opus-5-5"}})
    named, empty, missing, opts = got
    assert named == ["gemini-4-argon", "qwen3-32b", "claude-opus-5-5", "claude-opus-5-5", "설정 값"]
    assert empty == ["설정 값", "서버의 모델", "Claude Code 기본 모델", "Claude API 기본 모델"]
    assert missing == ["키 없음", "", "설치 안 됨", "로그인 필요", "", "", ""]
    # 키 없는 Claude API 는 고를 수 없다. 이미 고른 줄이면 그대로 두고 이유만 붙인다
    assert opts[0] == '<option value="claude-api" disabled>Claude API (키 없음)</option>'
    assert opts[1] == '<option value="claude-api" selected>Claude API (키 없음)</option>'


@needs_node
def test_kept_note_names_the_side_that_reuses_text():
    got = run_js(FILES, """[
      rsModelId({ provider: 'gemini', model: '' }, data.config),
      rsModelId({ provider: 'claude', model: '' }, data.config),
      rsModelId({ provider: 'claude-api', model: '' }, {}),
      rsModelId({ provider: 'local', model: '' }, {}),
      rsModelId({ provider: 'mock' }, data.config),
      rsKeptSource(data.ep, 'claude:claude-opus-5-5'),
      rsKeptSource(data.ep, 'gemini:gemini-3.8-flash'),
      rsKeptSource(data.ep, 'gemini:gemini-4-argon'),
      rsKeptNote(data.ep, { provider: 'gemini', model: '' }, { provider: 'claude', model: '' }, data.config),
      rsKeptNote(data.ep, { provider: 'claude', model: '' }, { provider: 'claude', model: 'claude-opus-5-5' }, data.config),
    ]""", {"config": {"model_setting": "gemini-4-argon", "claude_model": "claude-opus-5-5"},
           "ep": {"text": "본문", "written_by": "claude:claude-opus-5-5", "candidate": None,
                  "versions": [{"text": "옛 판", "model": "gemini:gemini-3.8-flash"}, {"text": "", "model": "gemini:gemini-4-argon"}]}})
    gem, sub, api, local, mock, cur, old, empty, note, same = got
    assert (gem, sub, api, local, mock) == ("gemini:gemini-4-argon", "claude:claude-opus-5-5", "claude-api:claude-opus-5-5", "", "")
    assert (cur, old, empty) == ("text", "version", "")  # 빈 판은 가져오지 않는다
    assert note == "B(claude-opus-5-5)는 이 화를 이미 쓴 모델이라 새로 쓰지 않고 지금 본문을 가져와요."
    assert same == ""  # 두 쪽이 같은 모델이면 둘 다 새로 쓴다


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


@needs_node
def test_usage_pct_formats_cache_rate():
    got = run_js(FILES, "[usagePct(0.134), usagePct(0.059), usagePct(0.011), usagePct(0), usagePct(undefined), usagePct(1)]", {})
    assert got == ["13%", "5.9%", "1.1%", "0%", "0%", "100%"]


@needs_node
def test_usage_saved_line_splits_cache_read_and_write():
    got = run_js(FILES, """[
      usageSavedLine({ batch: 2, saved: 1.5, cache_saved: 0.25, cache_premium: 0.1 }),
      usageSavedLine({ batch: 0, saved: 0, cache_saved: 0.02, cache_premium: 0.05 }),
      usageSavedLine({ batch: 0, saved: 0 }),
    ]""", {})
    assert got == ["배치 2번 $1.50 · 캐시 읽기 $0.2500 · 캐시 쓰기 할증 $0.1000",
                   "배치 안 씀 · 캐시 읽기 $0.0200 · 캐시 쓰기 할증 $0.0500 (아낀 것보다 커요)",
                   "배치 안 씀 · 캐시 아낌 없음"]


@needs_node
def test_usage_task_label_names_new_tasks():
    got = run_js(FILES, "[usageTaskLabel('recheck'), usageTaskLabel('agent 캐시 만들기'), usageTaskLabel('캐시 만들기'), usageTaskLabel('zzz'), usageTaskLabel('')]", {})
    assert got == ["고친 곳만 다시 보기", "AI 대화 에이전트 캐시 만들기", "캐시 만들기", "zzz", ""]


@needs_node
def test_usage_breakdown_by_task_and_effort_shows_cache_and_seconds():
    row = {"calls": 2, "failed": 0, "batch": 0, "in": 2000, "out": 20, "cached": 200, "cost": 0.01, "unpriced": 0,
           "cache_rate": 0.1, "seconds_avg": 15.0}
    u = {"by_task": [{**row, "task": "fixes"}],
         "by_effort": [{**row, "effort": "high"}, {**row, "effort": "기본", "in": 0, "cache_rate": 0, "seconds_avg": 0}]}
    task, effort = run_js(FILES, """(() => {
      S.usageProject = '';
      S.usageBy = 'task'; const task = usageBreakdown(data.u);
      S.usageBy = 'effort'; const effort = usageBreakdown(data.u);
      return [task, effort];
    })()""", {"u": u})
    assert "지적 고치기" in task and "10%" in task and "15.0초" in task and 'aria-pressed="true">작업' in task
    assert "평균 시간" in task and "캐시" in task
    assert "높음" in effort and "기본 (모델 기본값)" in effort and 'aria-pressed="true">추론 강도' in effort


def test_usage_task_labels_cover_scoped_tasks():
    # usage.scope(task="...") 로 적는 작업 이름마다 사용량 화면의 한국어 이름이 있다 (영어 키가 화면에 보이지 않게)
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "canon"
    tasks = set()
    for f in root.rglob("*.py"):
        tasks |= set(re.findall(r'usage\.scope\([^)]*task="([a-z_]+)"', f.read_text(encoding="utf-8")))
    js = (root / "static" / "usage.js").read_text(encoding="utf-8")
    block = js[js.index("const USAGE_TASK = {"):]
    block = block[:block.index("};")]
    labeled = set(re.findall(r"\b([a-z_]+): '", block))
    assert {"play", "studio"} <= tasks
    assert tasks <= labeled, tasks - labeled

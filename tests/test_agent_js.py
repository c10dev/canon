"""대화 에이전트 패널(static/agent.js)의 권한 이름이 서버 canon/agent.py 와 같은지. node 가 있을 때만 돈다."""
from canon import agent

from .jsvm import needs_node, run_js


@needs_node
def test_mode_and_kind_labels_match_server():
    got = run_js(["app.js", "chat.js", "agent.js"],
                 "({ modes: Object.fromEntries(Object.entries(AGENT_MODES).map(([k, v]) => [k, v[0]])), kinds: AGENT_KINDS })", None)
    assert got["modes"] == agent.MODE_LABELS
    assert got["kinds"] == agent.KIND_LABELS


@needs_node
def test_step_wait_matches_server():
    got = run_js(["app.js", "chat.js", "agent.js"],
                 "({ wait: AGENT_STEP_WAIT, text: agentStepWait({ started: Date.now() / 1000 - 75 }),"
                 " step: agentStepWait({ started: 0, step_at: Date.now() / 1000 - 5 }),"
                 " limit: [agentStepLimit({ step_wait: 480 }), agentStepLimit({ step_wait: 0 }), agentStepLimit(null)] })", None)
    assert got["wait"] == agent.STEP_WAIT
    assert got["limit"] == [480, agent.STEP_WAIT, agent.STEP_WAIT]  # 작업이 알려 준 한도(Claude Code 는 더 길다)를 쓴다
    assert got["text"] == "이번 단계 1:15"
    assert got["step"] == "이번 단계 0:05"


@needs_node
def test_step_now_and_turn_end():
    """도는 단계는 AI 호출 사정(Job.retry)을 보이고, 끝난 턴은 단계 수와 걸린 시간을 보인다."""
    got = run_js(["app.js", "chat.js", "agent.js"], """(() => {
      S.agent = { max_steps: 8, sessions: [] };
      const t = { user: '3화', mode: '', steps: [{ kind: 'read', tool: 'read_plots', label: '3화', why: '' }], reply: '그대로 둘게요',
        writes: [], end: 'done', error: '', at: '2026-11-07T10:00:00+00:00', ended: '2026-11-07T10:01:12+00:00' };
      const s = { id: 'a', turns: [t] };
      return {
        idle: agentStepNow({ retry: '' }), retry: agentStepNow({ retry: 'AI 요청 한도에 걸려 60초 기다려요 (1/3)' }),
        took: agentTurnTook(t), short: agentTurnTook({ ...t, ended: '2026-11-07T10:00:45+00:00' }), old: agentTurnTook({ ...t, ended: '' }),
        html: agentTurn(s, t, 0), oldHtml: agentTurn(s, { ...t, ended: '' }, 0),
      };
    })()""", None)
    assert got["idle"] == "AI 응답을 기다리는 중"
    assert got["retry"] == "AI 요청 한도에 걸려 60초 기다려요 (1/3)"
    assert got["took"] == "1분 12초" and got["short"] == "45초" and got["old"] == ""
    assert "끝났어요 · 1단계 · 1분 12초" in got["html"]
    assert "끝났어요 · 1단계</div>" in got["oldHtml"]


@needs_node
def test_continue_keeps_project_data():
    """이어 하기 응답은 작업 정보라 project 칸이 작품 이름 글이다. 2026-11-09 그 글이 S.project 를 덮어
    화면이 'Cannot read properties of undefined (reading 'map')' 으로 깨졌다."""
    got = run_js(["app.js", "chat.js", "agent.js"], """(async () => {
      S.name = 'lh'; S.project = data; S.dirty = false; S.jobs = [];
      saveIfDirty = async () => {}; pollJobs = () => {}; agentLoad = async () => {}; render = () => {};
      await agentAct(async () => ({ id: 'j1', kind: 'agent', project: 'lh', status: 'running' }));
      const kept = S.project === data;
      await agentAct(async () => ({ project: { ...data, title: '새 제목' }, job: { id: 'j2', kind: 'agent', project: 'lh' } }));
      return { kept, title: S.project.title, jobs: S.jobs.map((j) => j.id) };
    })()""", {"title": "옛 제목", "episodes": []})
    assert got == {"kept": True, "title": "새 제목", "jobs": ["j1", "j2"]}

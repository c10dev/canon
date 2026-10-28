"""대화 에이전트 패널(static/agent.js)의 권한 이름이 서버 canon/agent.py 와 같은지. node 가 있을 때만 돈다."""
from canon import agent

from .jsvm import needs_node, run_js


@needs_node
def test_mode_and_kind_labels_match_server():
    got = run_js(["app.js", "chat.js", "agent.js"],
                 "({ modes: Object.fromEntries(Object.entries(AGENT_MODES).map(([k, v]) => [k, v[0]])), kinds: AGENT_KINDS })", None)
    assert got["modes"] == agent.MODE_LABELS
    assert got["kinds"] == agent.KIND_LABELS

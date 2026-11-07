"""프롬프트 놀이터(static/promptlab.js)의 순수 함수와 세션 화면. node 가 있을 때만 돈다."""
from .jsvm import needs_node, run_js


@needs_node
def test_body_order_diff():
    got = run_js(["app.js", "usage.js", "promptlab.js"], """(() => ({
      body: pgBody({ title: 't', system: 's', prompt: 'p', temp: ' 0.7 ', backends: [{ provider: 'gemini', model: ' m ', url: 'x' }, { provider: 'local', model: '', url: ' u ' }] }),
      blank: pgBody({ temp: '' }).temperature,
      bad: pgBody({ temp: 'abc' }).temperature,
      order: pgOrder([{ no: 1, star: false }, { no: 2, star: true }, { no: 3, star: false }]).map((t) => t.no),
      diff: [pgDiff({ system: 'a', prompt: 'b' }, { system: 'a', prompt: 'b' }), pgDiff({ system: 'x', prompt: 'b' }, { system: 'a', prompt: 'b' }),
             pgDiff({ system: 'a', prompt: 'x' }, { system: 'a', prompt: 'b' }), pgDiff({ system: 'x', prompt: 'x' }, { system: 'a', prompt: 'b' })],
    }))()""", {})
    assert got["body"] == {"title": "t", "system": "s", "prompt": "p", "temperature": 0.7,
                           "backends": [{"provider": "gemini", "model": "m", "url": ""}, {"provider": "local", "model": "", "url": "u"}]}
    assert got["blank"] is None and got["bad"] is None
    assert got["order"] == [2, 3, 1]
    assert got["diff"] == ["same", "system", "prompt", "both"]


@needs_node
def test_session_view_draws_trials():
    got = run_js(["app.js", "usage.js", "promptlab.js"], """(() => {
      fmtDateTime = () => '';
      S.pgLimits = { providers: ['gemini', 'local', 'mock'], maxBackends: 4, maxTrials: 40, temperature: [0, 2] };
      pgSet({ id: 'a1', title: '제목', system: '', prompt: '요청', temperature: null, backends: [{ provider: 'mock', model: '', url: '' }], summary: { cost: 0 },
        trials: [{ no: 1, at: '', system: '', prompt: '옛 요청', temperature: null, star: false, note: '', runs: [
          { backend: 'mock', model: 'mock', ok: true, text: '<글>', error: '', seconds: 0.1, chars: 3, tokens_in: 0, tokens_out: 0, cost: 0 },
          { backend: 'gemini', model: '', ok: false, text: '', error: '키 없음', seconds: 0, chars: 0, tokens_in: 0, tokens_out: 0, cost: null }] }] });
      return viewPromptLab();
    })()""", {})
    assert "&lt;글&gt;" in got and "키 없음" in got
    assert "요청 프롬프트가 지금과 달라요" in got and 'data-action="pgRestore" data-arg="1">' in got
    assert 'data-action="pgRun">돌리기</button>' in got

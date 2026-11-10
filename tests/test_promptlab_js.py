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


@needs_node
def test_load_card_and_source_chip():
    got = run_js(["app.js", "usage.js", "promptlab.js"], """(() => {
      fmtDateTime = () => '';
      S.projects = [{ name: 'w1', title: '내 작품' }, { name: 'pl', title: '플레이', play: true }];
      S.pgSrc = { project: '', kind: 'check', n: 2, info: { kinds: [{ id: 'episode', label: '본문 쓰기', needs_text: false }, { id: 'check', label: '검수', needs_text: true }],
        episodes: [{ n: 1, title: '', has_text: true }, { n: 2, title: '', has_text: true }, { n: 3, title: '', has_text: false }], defaults: { episode: 3, check: 2 } } };
      const card = pgLoadCard();
      return { card, label: [pgSourceLabel({ label: '검수 · 예시 작품 2화' }, true), pgSourceLabel(null, false)] };
    })()""", {})
    assert "내 작품" in got["card"] and "플레이" not in got["card"]  # 플레이 사본은 고르지 않는다
    assert ">3화" not in got["card"]  # 검수는 본문이 있는 화만
    assert 'data-action="pgLoadPrompt">' in got["card"]
    assert got["label"] == ["검수 · 예시 작품 2화 (고침)", ""]


@needs_node
def test_load_card_scopes_and_policy_note():
    got = run_js(["app.js", "usage.js", "promptlab.js"], """(() => {
      fmtDateTime = () => '';
      S.projects = [];
      const info = { kinds: [{ id: 'arc', label: '구조', need: '', scope: 'work' }, { id: 'plots', label: '플롯 초안', need: '', scope: 'act' },
          { id: 'cue', label: '큐 시트', need: 'confirmed', scope: 'episode' }],
        episodes: [{ n: 1, title: '', has_text: true, confirmed: true }, { n: 2, title: '', has_text: false, confirmed: false }],
        groups: [{ n: 1, end: 1, label: '기 구간 1화' }, { n: 2, end: 2, label: '승 구간 2화' }], defaults: { arc: 0, plots: 2, cue: 1 } };
      const card = (kind, n) => { S.pgSrc = { project: '', kind, n, info }; return pgLoadCard(); };
      S.pgLimits = { providers: ['mock'], maxBackends: 4, maxTrials: 40, temperature: [0, 2], policyNote: 'POLICY LINE' };
      pgSet({ id: 'a1', title: '', system: '', prompt: '', temperature: null, backends: [], summary: { cost: 0 }, trials: [] });
      const draftOpts = pgSrcChoices(info, { id: 'plot', need: 'draft', scope: 'episode' }).options.map((x) => x.n);
      return { draftOpts, work: card('arc', 0), act: card('plots', 2), cue: card('cue', 1), cueOpts: pgSrcChoices(info, info.kinds[2]).options.map((x) => x.n),
        view: viewPromptLab() };
    })()""", {})
    assert 'id="pg-src-n"' not in got["work"] and "화를 고르지 않아요" in got["work"] and "disabled" not in got["work"].split("pgLoadPrompt")[1][:40]
    assert "승 구간 2화" in got["act"] and '<label for="pg-src-n">구간</label>' in got["act"]
    assert got["cueOpts"] == [1]  # 큐 시트는 플롯을 확정한 화만
    assert got["draftOpts"] == [2]  # 한 화 플롯은 플롯이 초안인 화만
    assert "POLICY LINE" in got["view"]


@needs_node
def test_spec_line_model_hint_and_run_facts():
    got = run_js(["app.js", "usage.js", "promptlab.js"], """(() => {
      const spec = { schema: 'StoryboardDraft', stage: 'board', stage_label: '스토리보드 · 큐 시트', out_tokens: 16384,
        backends: [{ model: 'gemini-x', effort: 'high' }, { model: '', effort: '' }] };
      return {
        line: pgSpecLine(spec), none: pgSpecLine({ stage: '' }),
        hint: [pgModelHint(spec, 0, { provider: 'gemini', model: '' }), pgModelHint(spec, 0, { provider: 'gemini', model: '내 모델' }),
               pgModelHint(spec, 1, { provider: 'claude', model: '' }, [], { claude_model: 'claude-opus-5-5' }),
               pgModelHint(null, 0, { provider: 'gemini', model: '' }, [], { model_setting: 'gemini-4-argon' }),
               pgModelHint(spec, 0, { provider: 'claude', model: '' }, [{ provider: 'gemini' }], {})],
        card: pgRunCard({ backend: 'gemini', model: 'gemini-x', ok: true, text: '{}', seconds: 1, chars: 2, tokens_in: 0, tokens_out: 0, cost: 0,
          schema_name: 'StoryboardDraft', effort: 'high', out_tokens: 16384 }),
      };
    })()""", {})
    assert got["line"].startswith("실제 호출처럼 돌려요: 스토리보드 · 큐 시트 단계의 모델 · 추론 강도") and "StoryboardDraft" in got["line"] and "16,384토큰" in got["line"]
    assert got["none"] == ""
    assert got["hint"] == ["비우면 스토리보드 · 큐 시트 단계 모델(gemini-x, 추론 강도 high)", "비우면 스토리보드 · 큐 시트 단계 모델(gemini-x, 추론 강도 high)",
                           "비우면 claude-opus-5-5", "비우면 gemini-4-argon",
                           "비우면 Claude Code 기본 모델"]  # 칸에서 백엔드를 바꾼 줄은 저장된 단계 값을 쓰지 않는다
    assert "StoryboardDraft 형식" in got["card"] and "추론 강도 high" in got["card"]


@needs_node
def test_run_card_check_and_raw():
    got = run_js(["app.js", "usage.js", "promptlab.js"], """(() => {
      const base = { backend: 'gemini', model: 'g', seconds: 1, chars: 2, tokens_in: 0, tokens_out: 0, cost: 0, schema_name: 'StoryboardDraft' };
      return {
        noted: pgRunCard({ ...base, ok: true, text: '{}', notes: ['빈 장면 1개는 Canon이 빼요'], empty: ['scenes[0].turn'], empty_count: 3 }),
        clean: pgRunCard({ ...base, ok: true, text: '{}', notes: [], empty: [], empty_count: 0 }),
        failed: pgRunCard({ ...base, ok: false, text: '', error: 'SchemaMismatch: x', raw: '<끊긴 답', finish: 'MAX_TOKENS' }),
        text: pgRunCard({ ...base, schema_name: '', ok: true, text: '글' }),
      };
    })()""", {})
    assert "빈 장면 1개는 Canon이 빼요" in got["noted"] and "빈 칸 3곳" in got["noted"] and "외 2곳" in got["noted"]
    assert "Canon이 그대로 받는 응답이에요" in got["clean"] and "빈 칸 없음" in got["clean"]
    assert "&lt;끊긴 답" in got["failed"] and "MAX_TOKENS(출력 한도)" in got["failed"]
    assert "빈 칸" not in got["text"] and "받은 원문" not in got["text"]  # 글로 받은 결과는 검사하지 않는다

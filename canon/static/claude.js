/* 설정 화면의 Claude 칸: 구독 로그인(설치된 Claude Code) 상태와 안내, 모델, API 키. app.js 의 S, actions, api 를 그대로 쓴다.
   서버는 canon/claude.py. 로그인은 Claude Code 가 Anthropic 로그인 화면으로 직접 한다. Anthropic 은 다른 앱이
   Claude 계정 로그인을 받거나 토큰을 보관하는 것을 허용하지 않으므로 여기에는 로그인 칸 없이 상태 확인과 안내만 둔다. */
'use strict';

Object.assign(S, {
  claudeStatus: null, // GET /claude/status 결과. null 이면 확인 중
});

async function claudeStatusLoad() {
  S.claudeStatus = null;
  claudePaint();
  try {
    S.claudeStatus = await api('GET', '/claude/status');
  } catch (e) {
    S.claudeStatus = { error: e.message };
  }
  claudePaint();
}

// 다시 그리면 저장 전 입력이 사라지므로 상태 칸만 바꾼다
function claudePaint() {
  const box = $('#claude-status');
  if (box) box.innerHTML = claudeStatusView();
}

const CLAUDE_CHIP = (text, ok) => `<span class="chip${ok ? ' finalized' : ''}"${ok ? '' : ' style="background:var(--red-soft);color:var(--red)"'}>${text}</span>`;

function claudeStatusView() {
  const s = S.claudeStatus;
  if (!s) return '<div class="small">Claude Code 로그인 상태를 확인하는 중…</div>';
  if (s.error) return `<div class="note warn">상태를 확인하지 못했어요: ${esc(s.error)}</div>`;
  const refresh = '<button class="btn" data-action="claudeRefresh">다시 확인</button>';
  const server = `<div class="small">브라우저가 없는 서버(상시 실행)라면 아무 컴퓨터에서 <code>${esc(s.token_command)}</code> 으로 1년짜리 토큰을 받아,
    Canon 설정이 아니라 서버의 실행 환경 변수 <code>CLAUDE_CODE_OAUTH_TOKEN</code> 에 두세요.</div>`;
  if (!s.installed) {
    return `<div class="field"><label>구독 로그인 ${CLAUDE_CHIP('Claude Code 없음', false)}</label>
      <div class="small">${esc(s.message)}</div>
      <div class="small">설치: <a href="https://code.claude.com/docs/en/setup" target="_blank" rel="noopener">Claude Code 설치 안내</a> → 터미널에서 <code>${esc(s.login_command)}</code></div>
      <div class="row">${refresh}</div></div>`;
  }
  const acct = s.account || {};
  const who = [acct.email, acct.orgName || acct.organizationName, acct.subscriptionType].filter(Boolean).map(esc).join(' · ');
  const head = s.logged_in
    ? `${CLAUDE_CHIP(s.metered ? '로그인됨 (Console API 계정)' : '로그인됨', !s.metered)} <span class="small">${who || esc(s.auth_method || '')}</span>`
    : CLAUDE_CHIP('로그인 필요', false);
  const steps = s.logged_in ? '' : `<ol class="small" style="margin:6px 0 6px 18px;padding:0">
      <li>이 컴퓨터(Canon을 실행하는 곳)에서 터미널을 열어요.</li>
      <li><code>${esc(s.login_command)}</code> 을 실행하면 브라우저에 Anthropic 로그인 화면이 열려요. Pro 또는 Max 구독 계정으로 로그인하세요.</li>
      <li>끝나면 아래 '다시 확인'을 눌러요.</li></ol>`;
  return `<div class="field"><label>구독 로그인 ${head}</label>
    ${['metered', 'error'].includes(s.reason) ? `<div class="note warn">${esc(s.message)}</div>` : ''}
    ${steps}
    ${s.logged_in ? '' : server}
    ${s.env_token ? '<div class="small">환경 변수 CLAUDE_CODE_OAUTH_TOKEN의 토큰으로 로그인해요.</div>' : ''}
    ${s.api_key_ignored ? '<div class="small">환경 변수 ANTHROPIC_API_KEY는 구독 호출에 넘기지 않아요. API 키는 \'Claude API 키\' 방식에서만 써요.</div>' : ''}
    <div class="small">Claude Code ${esc(s.version || '')} · ${esc(s.path)}</div>
    <div class="row">${refresh}</div></div>`;
}

function claudeSettings(c) {
  const src = c.anthropic_key_source;
  const keyState = src === 'none'
    ? CLAUDE_CHIP('없음', false)
    : `${CLAUDE_CHIP(esc(c.anthropic_key_hint), true)} <span class="small">${src === 'env' ? '환경 변수' : '설정 파일'}</span>`;
  // 다른 고급 설정처럼 접어 두고, Claude 를 쓰고 있거나 키를 넣었으면 펼친다
  const open = String(c.provider).startsWith('claude') || Object.values(c.stage_settings || {}).some((v) => String(v).startsWith('claude')) || src !== 'none' || !!c.claude_model;
  return `<details class="set-more"${open ? ' open' : ''}><summary><h2>Claude</h2> <span class="small">구독 로그인이나 API 키로 쓸 때</span></summary>
    <p class="desc">두 가지 방식이 있어요. <b>Claude 구독 로그인</b>은 이 컴퓨터에 설치하고 로그인한 Claude Code를 불러 Pro · Max 구독 한도 안에서 써요.
      <b>Claude API 키</b>는 Claude Console의 키로 종량제로 써요. 위 '생성 방식'이나 아래 단계별 백엔드에서 고르세요.</p>
    <p class="desc">Anthropic 정책상 Canon 같은 다른 앱이 Claude 계정 로그인을 받거나 토큰을 보관할 수 없어서, 로그인은 Claude Code에서 직접 해요.
      Canon은 로그인 상태만 확인하고 계정 정보는 저장하지 않아요. 구독 한도는 평범한 개인 사용을 기준으로 하니, 자동 집필처럼 오래 도는 작업은 API 키가 맞아요.</p>
    <div id="claude-status">${claudeStatusView()}</div>
    <div class="field"><label for="set-claude-model">Claude 모델</label>
      <input id="set-claude-model" type="text" list="model-options" value="${esc(c.claude_model || '')}" placeholder="비우면 구독은 Claude Code 기본 모델, API 키는 claude-opus-5-5">
      <div class="small">구독 방식은 opus · sonnet · haiku 같은 별칭도 받아요. 단계마다 바꾸려면 아래 단계별 모델 칸에 적으세요.</div>
      ${c.claude_model_source === 'env' ? '<div class="small">환경 변수 CANON_CLAUDE_MODEL이 우선해요.</div>' : ''}</div>
    <div class="field"><label for="set-claude-bin">claude 실행 파일 <span class="hint">PATH에서 못 찾을 때만</span></label>
      <input id="set-claude-bin" type="text" value="${esc(c.claude_bin || '')}" placeholder="예: ~/.local/bin/claude">
      ${c.claude_bin_source === 'env' ? '<div class="small">환경 변수 CANON_CLAUDE_BIN이 우선해요.</div>' : ''}</div>
    <div class="field"><label for="set-anthropic-key">Anthropic API 키 <span class="hint">'Claude API 키' 방식만 · 지금: </span>${keyState}</label>
      <input id="set-anthropic-key" type="password" autocomplete="off" placeholder="${src === 'none' ? 'sk-ant- 로 시작하는 키' : '바꿀 때만 입력'}">
      <div class="small"><a href="https://platform.claude.com/settings/keys" target="_blank" rel="noopener">Claude Console</a>에서 발급해요. 구독 로그인 토큰이 아니에요. 저장한 키는 화면에 다시 보여주지 않아요.</div>
      ${src === 'env' ? '<div class="small">환경 변수 ANTHROPIC_API_KEY가 우선해요.</div>' : ''}
      ${src === 'file' ? '<div class="row"><button class="btn danger" data-action="clearAnthropicKey">저장된 Anthropic 키 지우기</button></div>' : ''}</div>
    </details>`;
}

// saveSettings 가 보낼 값에 더한다
function claudeSettingsBody() {
  const body = { claude_model: $('#set-claude-model').value.trim(), claude_bin: $('#set-claude-bin').value.trim() };
  const key = $('#set-anthropic-key').value.trim();
  if (key) body.anthropic_api_key = key;
  return body;
}

Object.assign(actions, {
  async claudeRefresh() {
    await claudeStatusLoad();
  },
  async clearAnthropicKey() {
    if (!confirm('저장된 Anthropic API 키를 지울까요?')) return;
    await run('지우는 중', async () => {
      S.config = await api('PUT', '/config', { clear_anthropic_key: true });
      toast('Anthropic 키를 지웠어요');
    });
  },
});

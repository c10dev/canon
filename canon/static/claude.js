/* 설정 대화상자의 Claude 구독 계정 · 로그인 줄: 설치된 Claude Code 의 로그인 상태와 안내. app.js 의 S, actions, api 와 settings.js 의 setRow 를 쓴다.
   서버는 canon/claude.py. 로그인은 Claude Code 가 Anthropic 로그인 화면으로 직접 한다. Anthropic 은 다른 앱이
   Claude 계정 로그인을 받거나 토큰을 보관하는 것을 허용하지 않으므로 여기에는 로그인 칸이 없다.
   '로그인 시작'은 서버가 `claude auth login` 을 띄우게 할 뿐이고(POST /claude/login), 로그인은 브라우저의 Anthropic 화면에서 한다.
   '계정' 줄에서 Canon 전용 계정을 고르면 Canon 이 부르는 Claude Code 가 따로 로그인한다 (CLAUDE_CONFIG_DIR). */
'use strict';

Object.assign(S, {
  claudeStatus: null, // GET /claude/status 결과. null 이면 확인 중
});

async function claudeStatusLoad({ quiet = false } = {}) {
  if (!quiet) {
    S.claudeStatus = null;
    setPaint();
  }
  try {
    S.claudeStatus = await api('GET', '/claude/status');
  } catch (e) {
    S.claudeStatus = { error: e.message };
  }
  setPaint();
}

let claudeWatch = null; // '로그인 시작' 뒤 로그인을 마칠 때까지 상태를 다시 보는 타이머

/** 로그인 창을 띄운 뒤 3초마다 상태를 본다. 로그인했거나 띄운 로그인이 끝났거나(취소 · 10분) 대화상자를 닫으면 멈춘다 */
function claudeWatchLogin() {
  clearInterval(claudeWatch);
  claudeWatch = setInterval(async () => {
    const dlg = document.getElementById('set-dlg');
    if (dlg && !dlg.open) { clearInterval(claudeWatch); return; }
    await claudeStatusLoad({ quiet: true });
    const s = S.claudeStatus || {};
    if (s.error || s.logged_in || !s.login_running) {
      clearInterval(claudeWatch);
      if (s.logged_in) setNote('claude-login', '로그인했어요', 'ok');
    }
  }, 3000);
}

/** 계정 줄: Canon 이 부르는 Claude Code 가 평소 로그인을 같이 쓸지, Canon 전용 폴더로 따로 로그인할지 */
function claudeAccountRow(id, c) {
  const locked = c.claude_config_dir_source === 'env';
  const v = c.claude_config_dir ? 'canon' : 'shared';
  const desc = v === 'canon'
    ? `Canon만 쓰는 Claude Code 설정 폴더로 따로 로그인해요. 이 컴퓨터의 다른 Claude Code 로그인은 그대로예요. 폴더 <code>${esc(c.claude_config_dir)}</code>`
    : '이 컴퓨터의 Claude Code에 로그인한 계정을 같이 써요. Canon에만 다른 구독 계정을 쓰려면 Canon 전용으로 바꾸세요.';
  return setRow(id, '구독 계정', `${desc}${locked ? ` ${envLine('env', 'CANON_CLAUDE_CONFIG_DIR')}` : ''}`,
    `<div class="seg" role="group" aria-labelledby="rn-${id}">${[['shared', 'Claude Code와 같이'], ['canon', 'Canon 전용']].map(([k, l]) => `<button type="button" aria-pressed="${v === k}" data-action="setSeg" data-arg="claude_separate:${k}"${locked ? ' disabled' : ''}>${l}</button>`).join('')}</div>`);
}

/** 구독 로그인 줄: 이름 옆 상태 칩, 설명에 로그인 순서 · 계정, 오른쪽 '다시 확인' */
function claudeLoginRow(id) {
  const s = S.claudeStatus;
  const refresh = '<button type="button" class="btn" data-action="claudeRefresh">다시 확인</button>';
  const name = (chip) => `구독 로그인 ${chip}`;
  const intro = "이 컴퓨터의 Claude Code로 Pro · Max 구독 한도 안에서 써요. 로그인은 Anthropic 로그인 화면에서 하고, Canon은 계정 정보와 토큰을 받지 않아요.";
  if (!s) return setRow(id, name(SET_CHIP('확인하는 중')), intro, refresh, { wide: false });
  if (s.error) return setRow(id, name(SET_CHIP('모름', 'bad')), `상태를 확인하지 못했어요: ${esc(s.error)}`, refresh, { wide: false });
  if (!s.installed) {
    return setRow(id, name(SET_CHIP('Claude Code 없음', 'bad')),
      `${esc(s.message)} <a href="https://code.claude.com/docs/en/setup" target="_blank" rel="noopener">Claude Code 설치 안내</a>를 따라 설치한 뒤 터미널에서 <code>${esc(s.login_command)}</code> 을 실행하세요.`, refresh, { wide: false });
  }
  const acct = s.account || {};
  const who = [acct.email, acct.orgName || acct.organizationName, acct.subscriptionType].filter(Boolean).map(esc).join(' · ');
  const chip = s.logged_in ? SET_CHIP(s.metered ? '로그인됨 (Console API 계정)' : '로그인됨', s.metered ? '' : 'finalized') : SET_CHIP('로그인 필요', 'bad');
  const steps = s.logged_in ? '' : (s.login_running
    ? ' 브라우저에 열린 Anthropic 로그인 화면에서 Pro 또는 Max 계정으로 로그인하세요. 마치면 여기에 바로 보여요.'
    : ` '로그인 시작'을 누르면 Canon을 실행하는 컴퓨터의 브라우저에 Anthropic 로그인 화면이 열려요. 터미널에서 <code>${esc(s.login_command)}</code> 을 실행해도 돼요.
    브라우저가 없는 서버라면 아무 컴퓨터에서 <code>${esc(s.token_command)}</code> 으로 토큰을 받아 서버의 환경 변수 <code>CLAUDE_CODE_OAUTH_TOKEN</code>에 두세요.`);
  const extra = [
    ['metered', 'error'].includes(s.reason) ? esc(s.message) : '',
    s.env_token ? `환경 변수 CLAUDE_CODE_OAUTH_TOKEN의 토큰으로 로그인해요.${s.separate ? ' 이 토큰이 Canon 전용 로그인보다 먼저 쓰여요.' : ''}` : '',
    s.api_key_ignored ? "환경 변수 ANTHROPIC_API_KEY는 구독 호출에 넘기지 않아요. API 키는 'Claude API 키' 방식에서만 써요." : '',
    `${who ? `${who} · ` : ''}Claude Code ${esc(s.version || '')}`,
  ].filter(Boolean).join(' ');
  const login = !s.logged_in ? `<button type="button" class="btn primary" data-action="claudeLogin"${s.login_running ? ' disabled' : ''}>${s.login_running ? '로그인 기다리는 중' : '로그인 시작'}</button>` : '';
  const logout = s.logged_in && s.separate && !s.env_token ? '<button type="button" class="btn" data-action="claudeLogout">로그아웃</button>' : '';
  return setRow(id, name(chip), `${intro}${steps} ${extra}`, `${login}${logout}${refresh}`, { wide: false });
}

Object.assign(actions, {
  async claudeRefresh() {
    await claudeStatusLoad();
  },
  async claudeLogin() {
    setNote('claude-login', '로그인 화면을 여는 중…');
    try {
      const r = await api('POST', '/claude/login');
      setNote('claude-login', r.message, r.ok ? 'ok' : 'err');
      if (r.ok) {
        await claudeStatusLoad({ quiet: true });
        claudeWatchLogin();
      }
    } catch (e) {
      setNote('claude-login', e.message, 'err');
    }
  },
  async claudeLogout() {
    if (!(await askConfirm('Canon 전용 Claude 계정에서 로그아웃할까요? 이 컴퓨터의 다른 Claude Code 로그인은 그대로예요.', { ok: '로그아웃' }))) return;
    try {
      const r = await api('POST', '/claude/logout');
      setNote('claude-login', r.message, r.ok ? 'ok' : 'err');
    } catch (e) {
      setNote('claude-login', e.message, 'err');
    }
    await claudeStatusLoad({ quiet: true });
  },
});

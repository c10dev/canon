/* 설정 대화상자의 Claude 구독 로그인 줄: 설치된 Claude Code 의 로그인 상태와 안내. app.js 의 S, actions, api 와 settings.js 의 setRow 를 쓴다.
   서버는 canon/claude.py. 로그인은 Claude Code 가 Anthropic 로그인 화면으로 직접 한다. Anthropic 은 다른 앱이
   Claude 계정 로그인을 받거나 토큰을 보관하는 것을 허용하지 않으므로 여기에는 로그인 칸 없이 상태 확인과 안내만 둔다. */
'use strict';

Object.assign(S, {
  claudeStatus: null, // GET /claude/status 결과. null 이면 확인 중
});

async function claudeStatusLoad() {
  S.claudeStatus = null;
  setPaint();
  try {
    S.claudeStatus = await api('GET', '/claude/status');
  } catch (e) {
    S.claudeStatus = { error: e.message };
  }
  setPaint();
}

/** 구독 로그인 줄: 이름 옆 상태 칩, 설명에 로그인 순서 · 계정, 오른쪽 '다시 확인' */
function claudeLoginRow(id) {
  const s = S.claudeStatus;
  const refresh = '<button type="button" class="btn" data-action="claudeRefresh">다시 확인</button>';
  const name = (chip) => `구독 로그인 ${chip}`;
  const intro = '이 컴퓨터의 Claude Code로 Pro · Max 구독 한도 안에서 써요. 로그인은 Claude Code에서 직접 하고, Canon은 상태만 확인해요.';
  if (!s) return setRow(id, name(SET_CHIP('확인하는 중')), intro, refresh, { wide: false });
  if (s.error) return setRow(id, name(SET_CHIP('모름', 'bad')), `상태를 확인하지 못했어요: ${esc(s.error)}`, refresh, { wide: false });
  if (!s.installed) {
    return setRow(id, name(SET_CHIP('Claude Code 없음', 'bad')),
      `${esc(s.message)} <a href="https://code.claude.com/docs/en/setup" target="_blank" rel="noopener">Claude Code 설치 안내</a>를 따라 설치한 뒤 터미널에서 <code>${esc(s.login_command)}</code> 을 실행하세요.`, refresh, { wide: false });
  }
  const acct = s.account || {};
  const who = [acct.email, acct.orgName || acct.organizationName, acct.subscriptionType].filter(Boolean).map(esc).join(' · ');
  const chip = s.logged_in ? SET_CHIP(s.metered ? '로그인됨 (Console API 계정)' : '로그인됨', s.metered ? '' : 'finalized') : SET_CHIP('로그인 필요', 'bad');
  const steps = s.logged_in ? '' : ` 이 컴퓨터(Canon을 실행하는 곳)의 터미널에서 <code>${esc(s.login_command)}</code> 을 실행하고 Pro 또는 Max 계정으로 로그인한 뒤 '다시 확인'을 누르세요.
    브라우저가 없는 서버라면 아무 컴퓨터에서 <code>${esc(s.token_command)}</code> 으로 토큰을 받아 서버의 환경 변수 <code>CLAUDE_CODE_OAUTH_TOKEN</code>에 두세요.`;
  const extra = [
    ['metered', 'error'].includes(s.reason) ? esc(s.message) : '',
    s.env_token ? '환경 변수 CLAUDE_CODE_OAUTH_TOKEN의 토큰으로 로그인해요.' : '',
    s.api_key_ignored ? "환경 변수 ANTHROPIC_API_KEY는 구독 호출에 넘기지 않아요. API 키는 'Claude API 키' 방식에서만 써요." : '',
    `${who ? `${who} · ` : ''}Claude Code ${esc(s.version || '')}`,
  ].filter(Boolean).join(' ');
  return setRow(id, name(chip), `${intro}${steps} ${extra}`, refresh, { wide: false });
}

Object.assign(actions, {
  async claudeRefresh() {
    await claudeStatusLoad();
  },
});

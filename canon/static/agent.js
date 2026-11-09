/* 대화 에이전트 패널 (서버 canon/agent.py). 작품 안의 모든 화면에 하나다. chat.js 의 chatPanel('plot') 이 이 패널을 그린다.
   세션 머리(제목 · 대상 · 세션 목록), 턴마다 단계 줄 · 답 · 바로 쓴 것(되돌리기) · 승인 카드 · 되묻기, 입력 상자(+ 재료, / 빠른 요청, 보내기 · 멈추기),
   상태 줄(권한 모드 · 대상 · 대상 고정 · 모델 · 단계 상한). 턴은 백그라운드 작업 'agent' 로 돌고, pollJobs 가 진행을 알려 주면 세션만 다시 받는다.
   세션 목록은 작품 하나에 하나다(새 세션 topic 'agent', 옛 'plot' 세션도 함께). 대상은 화면이 준다(chat.js chatDefaultTarget).
   고정하지 않은 세션은 턴을 보낼 때 화면 대상으로 바뀌고, 상태 줄의 대상이 바뀌면 한 번 강조하고 #chat-live 로 알린다(agentAfterDraw).
   설정 도구(edit_setup)의 승인 카드와 쓴 것 비교는 agentsetup.js 가 그린다.
   옛 플롯 대화 기록은 '이전 대화'로 지금 카드(chat.js proposal)를 그대로 보인다. 설정 · 문체 · 본문 고치기의 옛 기록은 '이전 대화'에서 읽기만 하고, 적용한 설정 · 문체 변경안은 거기서 취소한다(chat.js chatReadOnlyCard).
   본문 고치기(서버 agent_text, 도구 revise_text): 집필 화면에서 본문을 고르면 입력 상자 위 '재료' 칩으로 붙고(S.agentMaterial), '/' 빠른 요청에
   더 짧게 · 대사 늘리기 같은 본문 빠른 요청(서버 prompts.PASSAGE_PRESETS)이 함께 뜬다. 재료나 빠른 요청이 붙은 말은 서버가 에이전트 단계 없이 그 도구를 바로 부른다.
   결과는 후보 카드(agentTextApproval)이고 권한 모드와 상관없이 늘 묻는다. 고른 후보 하나만 본문에 들어가고 수정 기록에 남는다.
   문체 도구(서버 agent_style, edit_style)는 문체 변경안 카드(agentStyleApproval)로 늘 묻는다. 칸 이름 · 비교 · 시험 문단은 stylechat.js 의
   STYLE_LABEL · styleEditDiff · sampleBlock 을 그대로 쓴다. 문체 대상이면 '+ 재료'에서 참고할 화를 골라 입력 상자 위 칩으로 붙인다(S.styleRefEp).
   권한 이름은 agent.MODE_LABELS · KIND_LABELS 와 같다. */
'use strict';

const AGENT_MODES = { ask: ['물어보기', '쓰기마다 그 자리에서 승인해요.'],
  draft: ['빈 곳 · 초안만 자동', '초안 화 · 새 화 · 다음 아크 초안은 바로 쓰고, 확정한 화와 범위는 물어요.'],
  all: ['모두 자동', '막힌 것 말고는 묻지 않고 써요. 턴마다 되돌릴 수 있어요.'] };
const AGENT_KINDS = { draft: '초안 화', next: '다음 아크 초안', confirmed: '확정한 화', arc: '아크 칸', acts: '구간 · 범위', parts: '부 구성',
  renumber: '화 넣기 · 빼기', outside: '다듬을 곳 밖', text: '본문 고치기', setup: '설정 칸', style: '문체' };
const AGENT_ALWAYS = ['renumber', 'text', 'setup', 'style'];  // 서버 agent.ALWAYS_ASK: 권한 모드와 상관없이 묻고 '이 세션에서 묻지 않기'를 두지 않는다
const AGENT_CMDS = [['/여러안', '바꾸기 전에 방향 여러 안으로 물어요'], ['/대상', '대상 고정을 풀고 지금 보는 곳으로'],
  ['/새세션', '지금 보는 곳으로 새 세션'], ['/되돌리기', '마지막으로 바꾼 턴 되돌리기']];
const AGENT_STEP_ICON = { read: '읽', write: '씀', wait: '물', block: '막', ask: '?', note: '·' };
const AGENT_LEGACY = 'legacy';  // 옛 플롯 대화. 설정 · 문체 · 본문 고치기의 옛 기록은 'legacy:<주제>' (읽기 전용)
const AGENT_SLOW = 60;  // 한 단계를 이 초보다 오래 기다리면 늦음 안내를 보인다 (보통 5~30초)
const AGENT_STEP_WAIT = 300;  // 서버 agent.STEP_WAIT 와 같다. 이만큼 응답이 없으면 한 번 다시 부르고, 또 없으면 오류로 멈춘다
// 작업이 알려 준 한 단계 한도(Job.step_wait, Claude Code 는 agent.STEP_WAIT_CLAUDE). 없으면 AGENT_STEP_WAIT
const agentStepLimit = j => (j && j.step_wait) || AGENT_STEP_WAIT;
const AGENT_ICON = {
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"></path></svg>',
  send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M6 11l6-6 6 6"></path></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2"></rect></svg>',
  down: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"></path></svg>',
  pin: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 17v5M8 3h8l-1 6 3 4H6l3-4z"></path></svg>',
};

Object.assign(S, {
  agent: null,          // 서버 GET sessions: { name, sessions, legacy, model, max_steps }
  agentSid: null,       // 연 세션 id ('legacy' 는 이전 대화)
  agentDraft: '',
  agentMenu: false,     // 세션 목록
  agentModeMenu: false, // 권한 모드 메뉴
  agentTargetMenu: false, // 다듬을 곳 메뉴
  agentPlus: false,     // 함께 넣을 재료
  agentPicks: {},       // '턴:부분' → 승인 카드에서 쓸지
  agentRemember: {},    // 턴 → 이 세션에서 묻지 않기
  agentBusy: false,     // 보내는 중 (작업이 뜨기 전)
  agentShown: null,     // 상태 줄에 마지막으로 보인 대상 ('작품|대상'). 바뀌면 한 번 강조한다
  agentFlash: null,     // 다음 그리기 뒤 강조하고 알릴 대상 이름
  agentMaterial: null,  // 재료 칩: 집필 화면에서 고른 본문 { n, start, text }. 붙어 있으면 말은 본문 고치기로 간다
  agentCand: {},        // '턴:후보' → 손보는 중인 후보 글 (본문 고치기 카드)
});

JOB_PAGES.agent = [];  // 패널만 다시 그린다 (agentJobUpdate)
JOB_DONE_MSG.agent = (j) => `${j.label}: 턴이 끝났어요`;
JOB_LINK.agent = (j) => `#/p/${enc(j.project)}/arc`;

// ----- 빈 세션의 예시 요청 -----

/** 빈 세션에 보일 예시 요청. 틀 문장에 이 작품의 값(인물 이름 · 화 번호 · 아크 번호)을 채우고 둘까지 낸다. AI 를 부르지 않는다.
    채울 값이 없는 틀은 빼고, 하나도 없으면 빈 목록이다(입력칸 예시 글만 남는다). 본문 · 문체 대상은 예시를 두지 않는다 */
function agentExamples(target) {
  const p = P();
  if (!p || target === 'style' || /^text:\d+$/.test(target || '')) return [];
  const named = (p.characters || []).filter((c) => (c.name || '').trim());
  const lead = [...named].sort((a, b) => /주인공/.test(b.role || '') - /주인공/.test(a.role || ''));
  const [c, d] = lead.map((x) => x.name.trim());
  const out = [];
  if (target === 'setup') {
    if (c) out.push(`${c}의 약점을 더 어둡게`);
    if (c && d) out.push(`${c}${josa(c, '과', '와')} ${d} 사이에 갈등을 하나 더`);
    return out;
  }
  const arc = plotTargetArc(target);
  const part = /^part:(\d+)$/.exec(target || '');
  if (arc) {
    out.push(`아크 ${arc.number} 갈등을 더 개인적인 걸로`);
    if (c) out.push(`${c}의 비중을 이 아크에서 늘려 줘`);
  } else if (target === 'next') {
    out.push(`${plannedUntil() + 1}화부터 15화짜리 아크로`);
    if (c) out.push(`다음 아크는 ${c} 중심으로`);
  } else if (part) {
    out.push(`${part[1]}부 전환점을 더 늦게`);
    if (c) out.push(`${part[1]}부에서 ${c}의 목표를 더 분명하게`);
  } else {
    const e = /^ep:(\d+)$/.exec(target || '');
    const open = (p.episodes || []).find((x) => !LOCKED_STATUS.includes(x.status));
    const n = e ? Number(e[1]) : (S.selEp && ep(S.selEp) ? S.selEp : open && open.plot.number);
    if (n) out.push(`${n}화 전개가 너무 빨라`);
    if (c) out.push(`${c}${josa(c, '이', '가')} 진실을 더 늦게 알게 해 줘`);
  }
  return out.slice(0, 2);
}

/** 예시 요청 버튼 줄. 예시가 없으면 빈 글 */
function agentExampleRow(target) {
  const xs = agentExamples(target);
  return xs.length ? `<div class="row">${xs.map((x) => `<button type="button" class="btn small" data-action="agentExample" data-arg="${esc(x)}">${esc(x)}</button>`).join('')}</div>` : '';
}

// ----- 데이터 -----

function agentKey() { return `canon.agent.${S.name}`; }

async function agentLoad() {
  if (!S.name) return;
  const name = S.name;
  const res = await api('GET', `/projects/${enc(name)}/sessions`);
  if (name !== S.name) return;
  S.agent = { name, older: [], ...res };
  const live = res.sessions.filter((s) => !s.archived);
  let sid = S.agentSid;
  if (!sid) { try { sid = localStorage.getItem(agentKey()); } catch { sid = null; } }
  const old = agentOldTopic(sid);
  if (sid !== AGENT_LEGACY && !old && !res.sessions.some((s) => s.id === sid)) sid = null;
  if (sid === AGENT_LEGACY && !res.legacy) sid = null;
  if (old && !S.agent.older.some((x) => x.topic === old)) sid = null;
  if (!sid) sid = live.length ? [...live].sort((a, b) => (b.updated || '').localeCompare(a.updated || ''))[0].id : (res.legacy ? AGENT_LEGACY : null);
  S.agentSid = sid;
}

function agentSession() {
  return S.agent && S.agentSid && !agentIsLegacy(S.agentSid) ? S.agent.sessions.find((s) => s.id === S.agentSid) || null : null;
}

/** 이전 대화를 연 것인지 (옛 플롯 대화 'legacy' 나 읽기 전용 'legacy:<주제>') */
function agentIsLegacy(sid) {
  return sid === AGENT_LEGACY || !!agentOldTopic(sid);
}

/** 읽기 전용 이전 대화의 주제 ('legacy:setup' → 'setup'). 아니면 빈 글 */
function agentOldTopic(sid) {
  return typeof sid === 'string' && sid.startsWith(`${AGENT_LEGACY}:`) ? sid.slice(AGENT_LEGACY.length + 1) : '';
}

/** 화면이 주는 기본 대상 (chat.js chatDefaultTarget, drawApp 이 정한다) */
function agentScreenTarget() {
  return (S.chatHere && S.chatHere.target) || '';
}

/** 이 세션이 다음 턴에 쓸 대상: 고정한 세션은 세션 대상, 아니면 화면 대상 */
function agentTarget(s = agentSession()) {
  return s && s.pinned ? s.target : agentScreenTarget();
}

function agentRunningJob() {
  return S.jobs.find((j) => j.status === 'running' && j.project === S.name && j.kind === 'agent');
}

/** 지금 단계를 기다린 초 (서버 시각 기준이라 몇 초 어긋날 수 있다). */
function agentStepSec(j) {
  return Math.max(0, Math.round(Date.now() / 1000 - (j.step_at || j.started)));
}

function agentStepWait(j) {
  const sec = agentStepSec(j);
  return `이번 단계 ${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
}

/** 지금 단계가 하는 일. AI 호출이 기다리거나 다시 부르는 중이면 그 사정(서버 Job.retry, cancel.say)을 보인다 */
function agentStepNow(j) {
  return (j && j.retry) || 'AI 응답을 기다리는 중';
}

/** 끝난 턴의 걸린 시간 '1분 12초' · '45초'. 시각이 없으면 빈 글 (옛 턴은 ended 가 없다) */
function agentTurnTook(t) {
  const sec = t.at && t.ended ? Math.round((Date.parse(t.ended) - Date.parse(t.at)) / 1000) : NaN;
  if (!(sec >= 0)) return '';
  return sec < 60 ? `${sec}초` : `${Math.floor(sec / 60)}분${sec % 60 ? ` ${sec % 60}초` : ''}`;
}

/** 세션의 다듬을 곳 이름. 부 · 화 · 본문 · 설정 · 문체는 서버 pipeline.chat_focus, 아크 · 다음 아크는 chat_target 과 같은 대상 */
function agentTargetText(target) {
  if (target === 'setup') return '설정';
  if (target === 'style') return '문체';
  const t = /^text:(\d+)$/.exec(target || '');
  if (t) {
    const e = ep(Number(t[1]));
    return `${t[1]}화 본문${e && e.plot.title ? ` ${e.plot.title}` : ''}`;
  }
  const m = /^(part|ep):(\d+)$/.exec(target || '');
  if (m && m[1] === 'part') {
    const x = (P().parts || []).find((y) => y.number === Number(m[2]));
    return x ? `${x.number}부${x.title ? ` ${x.title}` : ''}` : `${m[2]}부`;
  }
  if (m) {
    const e = ep(Number(m[2]));
    return `${m[2]}화 플롯${e && e.plot.title ? ` ${e.plot.title}` : ''}`;
  }
  const a = plotTargetArc(target);
  if (a) return `아크 ${a.number}${a.title ? ` ${a.title}` : ''}`;
  if (target === 'next') return `다음 아크 (${plannedUntil() + 1}화부터)`;
  return serial() && S.route[2] === 'arc' ? '본문이 없는 첫 아크' : '작품 전체';  // 장편 플롯 화면에서 아크를 고르지 않으면 플롯 쓰기는 그 아크로 간다
}

function agentSelect(sid) {
  S.agentSid = sid;
  S.agentMenu = false;
  S.chatScroll = true;
  try { localStorage.setItem(agentKey(), sid); } catch { /* 기억하지 못해도 동작에는 상관없다 */ }
}

// ----- 그리기 -----

function agentPanel() {
  if (!S.agent || S.agent.name !== S.name) {
    agentLoad().then(() => redrawChat()).catch((e) => toast(e.message, true));
    return `<aside class="chat-panel" aria-label="대화 에이전트"><div class="chat-log" id="chat-log" role="log" aria-live="off"><div class="msg ai pending" role="status"><span class="spinner small" aria-hidden="true"></span>대화 세션을 불러오는 중…</div></div></aside>`;
  }
  const s = agentSession();
  const old = agentOldTopic(S.agentSid);
  const legacy = agentIsLegacy(S.agentSid);
  const title = legacy ? '이전 대화' : s ? (s.title || '새 세션') : '새 세션';
  const oldN = old ? (S.agent.older.find((x) => x.topic === old) || {}).count || 0 : S.agent.legacy;
  const target = agentTarget(s);
  const sub = legacy ? `${chatTopicName(old || 'plot')} · 옛 기록 ${oldN}개` : `다듬을 곳: ${agentTargetText(target)}`;
  const shown = `${S.name}|${target}`;
  // 같은 작품에서 대상이 바뀔 때만 알린다 (다른 작품으로 옮긴 첫 그리기는 알리지 않는다)
  if (S.agentShown && S.agentShown !== shown && S.agentShown.startsWith(`${S.name}|`) && !legacy) S.agentFlash = agentTargetText(target);
  if (!legacy) S.agentShown = shown;
  // 마지막 턴이 본문 후보를 고르기를 기다린다. 휴대폰 시트는 후보를 보이려고 높아진다 (app.css .has-cands)
  const last = s && s.turns[s.turns.length - 1];
  const cands = !legacy && last && last.end === 'wait' && last.approval && last.approval.passage;
  return `<aside class="chat-panel${cands ? ' has-cands' : ''}" aria-label="대화 에이전트">
    <div class="chat-head">
      <button type="button" class="sess-btn" data-action="agentMenuToggle" aria-haspopup="true" aria-expanded="${S.agentMenu}">
        <strong><span class="sess-title">${esc(title)}</span>${AGENT_ICON.down}</strong><span class="small">${esc(sub)}</span></button>
      <div class="row" style="gap:4px;flex-wrap:nowrap">
        <button type="button" class="btn small" data-action="agentNew">새 세션 열기</button>
        <button type="button" class="btn icon-btn" data-action="toggleChat" aria-label="닫기">✕</button></div>
      ${S.agentMenu ? agentMenu() : ''}
    </div>
    <div class="chat-log" id="chat-log" role="log" aria-live="off">${agentLog()}</div>
    ${agentComposer()}
  </aside>`;
}

function agentMenu() {
  const all = [...S.agent.sessions].sort((a, b) => (b.updated || '').localeCompare(a.updated || ''));
  const live = all.filter((s) => !s.archived);
  const kept = all.filter((s) => s.archived);
  const chip = (s) => {
    const last = s.turns[s.turns.length - 1];
    if (last && last.end === '') return '<span class="chip">돌아가는 중</span>';
    if (last && last.end === 'wait') return '<span class="chip warn">승인 1</span>';
    const n = s.turns.reduce((k, t) => k + t.writes.reduce((m, w) => m + w.items.filter((i) => i.state === 'done').length, 0), 0);
    return n ? `<span class="chip">바꿈 ${n}</span>` : '';
  };
  const row = (s) => `<button type="button" class="sess-item" aria-current="${s.id === S.agentSid}" data-action="agentPick" data-arg="${s.id}">
    <span class="t">${esc(s.title || '새 세션')}</span><span class="small">${esc(agentTargetText(s.target))} · ${fmtDateTime(s.updated || s.created)}</span>${chip(s)}</button>`;
  const cur = agentSession();
  const olds = S.agent.older || [];
  return `<div class="pop sess-menu" role="group" aria-label="대화 세션">
    <div class="pop-title">대화 세션 · ${live.length}</div>
    ${live.map(row).join('') || '<div class="small" style="padding:6px 10px">아직 세션이 없어요. 말을 보내면 새 세션이 생겨요.</div>'}
    ${S.agent.legacy ? `<button type="button" class="sess-item" aria-current="${S.agentSid === AGENT_LEGACY}" data-action="agentPick" data-arg="${AGENT_LEGACY}"><span class="t">이전 대화 · 플롯</span><span class="small">예전 방식 기록 ${S.agent.legacy}개 · 변경안을 골라 적용</span><span class="chip">읽기</span></button>` : ''}
    ${olds.map((x) => `<button type="button" class="sess-item" aria-current="${S.agentSid === `${AGENT_LEGACY}:${x.topic}`}" data-action="agentPick" data-arg="${esc(`${AGENT_LEGACY}:${x.topic}`)}"><span class="t">이전 대화 · ${esc(chatTopicName(x.topic))}</span><span class="small">예전 방식 기록 ${x.count}개 · 읽기만</span><span class="chip">읽기</span></button>`).join('')}
    ${cur ? `<hr class="pop-sep"><div class="row" style="padding:0 6px"><button type="button" class="btn small" data-action="agentRename">이름 바꾸기</button><button type="button" class="btn small" data-action="agentArchive" data-arg="${cur.id}|1">이 세션 보관</button></div>` : ''}
    ${kept.length ? `<details style="padding:0 10px"><summary>보관함 · ${kept.length}</summary>
      ${kept.map((s) => `<div class="between" style="padding:4px 0"><span class="small">${esc(s.title || '새 세션')} · ${fmtDate(s.updated || s.created)}</span><button type="button" class="btn small" data-action="agentArchive" data-arg="${s.id}|0">꺼내기</button></div>`).join('')}</details>` : ''}
  </div>`;
}

function agentLog() {
  if (S.agentSid === AGENT_LEGACY) {
    return `<div class="note plain">예전 방식(한 번에 변경안 하나) 대화 기록이에요. 변경안은 예전처럼 골라서 적용하거나 취소할 수 있어요. 새로 말하면 새 세션이 열려요.</div>${chatLog('plot')}`;
  }
  const old = agentOldTopic(S.agentSid);
  if (old) {
    const how = old === 'setup' || old === 'style' ? '적용한 변경안은 여기서 취소할 수 있어요.' : '넣은 후보는 집필 화면의 수정 기록에서 되돌려요.';
    return `<div class="note plain">${esc(chatTopicName(old))} 예전 대화 기록이에요. 여기서는 읽기만 해요. ${how} 새로 말하면 새 세션이 열려요.</div>${chatLog(old, { readOnly: true })}`;
  }
  const s = agentSession();
  if (!s || !s.turns.length) {
    const aim = agentTarget(s);
    if (aim === 'setup') return agentSetupIntro();  // 설정 도구가 있다 (agentsetup.js)
    if (/^text:\d+$/.test(aim)) {
      return `<div class="note info">본문에서 고칠 부분을 드래그하면 아래에 재료로 붙어요. 바라는 것을 적거나 '/'를 눌러 더 짧게 · 대사 늘리기 같은 빠른 요청을 고르세요. AI가 후보를 2~3개 내고, 고른 후보만 본문에 들어가요. 권한 모드와 상관없이 늘 골라서 넣고, 넣은 뒤에도 되돌릴 수 있어요.</div>`;
    }
    if (aim === 'style') {  // 문체 도구가 있다 (agent_style)
      return `<div class="note info">문체를 말로 고쳐요. AI가 문체에서 바꿀 칸을 지금 값과 나란히 보여 주고, 바뀐 문체로 쓴 시험 문단도 함께 내요. 고른 칸만 이 작품 문체에 들어가고, 적용한 뒤에도 취소할 수 있어요. 권한 모드와 상관없이 늘 먼저 물어봐요. '+'에서 참고할 화를 고르면 그 화 한 대목을 새 문체로 고쳐 써 봐요.</div>`;
    }
    return `<div class="note info">구조와 플롯을 말로 고쳐요. AI가 필요한 플롯과 본문을 읽고 고치며, 아래 권한 모드에 따라 초안은 바로 쓰고 확정한 화나 범위는 물어봐요. 바로 쓴 것은 되돌릴 수 있고, 본문이 있는 화는 바꾸지 않아요.</div>
      ${agentExampleRow(aim)}`;
  }
  return s.turns.map((t, i) => agentTurn(s, t, i)).join('');
}

/** 화면 낭독기에 알릴 가장 새 답(chat.js chatAnnounce). 끝났거나 묻는 중인 턴의 답만 친다 */
function agentLastReply() {
  const s = agentIsLegacy(S.agentSid) ? null : agentSession();
  const turns = s ? s.turns : [];
  let i = turns.length - 1;
  while (i >= 0 && !(turns[i].reply && turns[i].end !== '')) i -= 1;
  return { scope: `${S.name}|agent:${S.agentSid || ''}`, id: String(i), text: i >= 0 ? turns[i].reply : '' };
}

function agentTurn(s, t, i) {
  const last = i === s.turns.length - 1;
  const running = t.end === '';
  const job = running ? agentRunningJob() : null;
  const count = (k) => t.steps.filter((x) => x.kind === k).length;
  const sum = [['read', '읽음'], ['write', '바꿈'], ['wait', '승인 기다림'], ['block', '막힘'], ['ask', '되물음']]
    .map(([k, l]) => (count(k) ? `${l} ${count(k)}` : '')).filter(Boolean).join(' · ') || (running ? '시작하는 중' : '단계 없음');
  const steps = t.steps.length || running ? `<details class="turn-steps"${running || (last && t.end === 'wait') ? ' open' : ''}>
      <summary><b>${esc(sum)}</b><span class="caret">단계 ${t.steps.length}</span></summary>
      <ol class="step-list">${t.steps.map((x) => `<li class="step ${x.kind}"><span class="ico" aria-hidden="true">${AGENT_STEP_ICON[x.kind] || '·'}</span>
        <span class="what"><b>${esc(agentToolName(x.tool))}</b>${x.label ? ` · ${esc(x.label)}` : ''}</span><span class="why">${esc(x.why)}</span></li>`).join('')}
      ${running ? `<li class="step run"><span class="ico" aria-hidden="true">…</span><span class="what"${job ? ` data-step-now="${job.id}"` : ''}>${esc(agentStepNow(job))}</span><span class="why">${job && job.note ? `방금 생각: ${esc(job.note)}` : ''}</span></li>` : ''}</ol></details>` : '';
  const bar = running ? `<div class="run-bar" role="status"><span class="spinner small" aria-hidden="true"></span>
      <span>${job ? job.done : t.steps.length}/${S.agent.max_steps}단계</span>${job ? `<span data-step-wait="${job.id}" aria-hidden="true">${agentStepWait(job)}</span>` : ''}<span class="run-meter" aria-hidden="true"><i style="width:${Math.round(((job ? job.done : 0) / S.agent.max_steps) * 100)}%"></i></span></div>
      ${job ? `<div class="note warn" data-step-slow="${job.id}"${agentStepSec(job) > AGENT_SLOW && !job.retry ? '' : ' hidden'}>AI 응답이 늦어요. 한 단계는 보통 1분 안에 끝나요. ${agentStepLimit(job) / 60}분 동안 응답이 없으면 한 번 다시 부르고, 또 없으면 오류로 멈춰요. 기다리지 않으려면 ■ 로 멈춘 뒤 '이어 하기'로 다시 보내세요.</div>` : ''}` : '';
  const took = agentTurnTook(t);
  const ends = {
    done: `<div class="small">끝났어요 · ${t.steps.length}단계${took ? ` · ${took}` : ''}</div>`,
    cap: `<div class="note warn"><div>${S.agent.max_steps}단계에서 멈췄어요. 이어서 더 할 수 있어요.</div>${last ? `<div class="row proposal-actions"><button type="button" class="btn small primary" data-action="agentContinue" data-arg="${i}">이어 하기</button></div>` : ''}</div>`,
    stopped: `<div class="note plain"><div>멈췄어요. 쓰던 것은 저장하지 않았어요.${t.error ? ` (${esc(t.error)})` : ''}</div>${last ? `<div class="row proposal-actions"><button type="button" class="btn small" data-action="agentContinue" data-arg="${i}">이어 하기</button></div>` : ''}</div>`,
    error: `<div class="note err"><div>오류로 멈췄어요: ${esc(t.error)}</div>${last ? `<div class="row proposal-actions"><button type="button" class="btn small" data-action="agentContinue" data-arg="${i}">다시 이어 하기</button></div>` : ''}</div>`,
  };
  const blocks = running ? [] : t.steps.filter((x) => x.kind === 'block');
  // 묻는 중이면 답이 카드 앞에(무엇을 묻는지), 끝났으면 쓴 것 뒤에(무엇을 했는지) 온다
  const reply = t.reply ? `<div class="msg-text">${esc(t.reply)}</div>` : '';
  const asking = t.end === 'wait' || t.end === 'ask';
  const quote = t.selection ? `<span class="msg-quote">${t.selection.episode}화 · ${esc(agentClip(t.selection.text, 80))}</span>` : '';
  const preset = t.preset ? agentPresetLabel(t.preset) : '';
  const said = preset && t.user === preset ? '' : esc(t.user);
  return `<div class="msg user">${quote}${t.mode === 'options' ? '<span class="chip" style="background:var(--glass);color:var(--accent-ink)">/여러안</span> ' : ''}${preset ? `<span class="chip" style="background:var(--glass);color:var(--accent-ink)">/${esc(preset)}</span> ` : ''}${said}</div>
    <div class="msg ai">${steps}${bar}${asking ? reply : ''}
      ${blocks.map((x) => `<div class="blocked">${esc(x.label)} · ${esc(x.why)}</div>`).join('')}
      ${t.approval ? agentApproval(t, i, last) : ''}
      ${t.ask ? agentAsk(t, i, last) : ''}
      ${agentWrites(s, t, i)}
      ${asking ? '' : reply}
      ${ends[t.end] || ''}</div>`;
}

function agentToolName(tool) {
  return { read_plots: '화 플롯 읽기', read_summaries: '화 요약 목록', find_text: '본문 단락 찾기', read_cast: '인물 읽기',
    edit_plot: '플롯 고치기', insert_episodes: '화 넣기', remove_episode: '화 빼기', ask: '되묻기', approval: '작가의 답',
    ask_empty: '빈 되묻기', edit_empty: '빈 고치기', reply: '예고만 한 답', revise_text: '본문 고치기',
    edit_setup: '설정 고치기', edit_style: '문체 고치기' }[tool] || tool;
}

const agentClip = (t, n) => (t.length > n ? `${t.slice(0, n)}…` : t);

/** 본문 빠른 요청 이름 (서버 GET /passage/presets, app.js 가 S.presets 에 받아 둔다) */
function agentPresetLabel(id) {
  return ((S.presets || []).find((x) => x.id === id) || {}).label || id;
}

/** 본문 빠른 요청을 '/' 명령으로: [['/더 짧게', '본문 빠른 요청', id], ...]. 본문 대상(집필 · 검수 · 상태 승인)이거나 재료가 붙었을 때만 */
function agentTextCmds() {
  if (!agentMaterialNow() && !/^text:\d+$/.test(agentTarget())) return [];
  return (S.presets || []).map((x) => [`/${x.label}`, '고른 본문을 고쳐요 · 후보를 골라 넣어요', x.id]);
}

/** '/더 짧게 …' 처럼 본문 빠른 요청으로 시작하는 말 → { id, label, rest }. 띄어쓰기 없이 써도('/더짧게') 받는다 */
function agentParsePreset(text) {
  const t = String(text || '').trim();
  if (!t.startsWith('/')) return null;
  for (const x of S.presets || []) {
    for (const k of [`/${x.label}`, `/${x.label.replace(/\s+/g, '')}`]) {
      if (t === k || t.startsWith(`${k} `)) return { id: x.id, label: x.label, rest: t.slice(k.length).trim() };
    }
  }
  return null;
}

/** 지금 붙은 재료. 그 화가 없거나 본문에서 사라졌으면 없는 것으로 본다 */
function agentMaterialNow() {
  const m = S.agentMaterial;
  if (!m || !P() || !ep(m.n)) return null;
  const now = typeof textNow === 'function' ? textNow(m.n) : ep(m.n).text;
  return (now || '').includes(m.text) ? m : null;
}

/** 재료를 붙인다 (passage.js 의 본문 고르기 · 'AI에게 고치기'가 부른다). 패널이 있으면 칩만 다시 그린다 */
function agentAttach(sel) {
  S.agentMaterial = sel ? { n: sel.n, start: sel.start, text: sel.text } : null;
  const box = document.querySelector('.chat-panel .composer-mats');
  if (box) box.outerHTML = agentMats();
  else if (document.querySelector('.chat-panel .composer')) redrawChat();
}

function agentMats() {
  const m = agentMaterialNow();
  if (!m) return '<div class="composer-mats" hidden></div>';
  return `<div class="composer-mats" role="group" aria-label="붙인 재료">
    <span class="mat-chip"><span class="mat-kind">재료</span><span class="mat-text">${m.n}화 · ${esc(agentClip(m.text.replace(/\s+/g, ' '), 60))}</span>
      <span class="small">${m.text.length.toLocaleString()}자</span>
      <button type="button" class="mat-x" data-action="agentMaterialDrop" aria-label="재료 떼기">✕</button></span></div>`;
}

/** 바로 쓴 것 한 부분의 바뀐 칸. 쓰기 전 · 뒤 값(before · after)으로 비교한다 (지금 값은 이미 바뀌었다). */
function agentItemDiff(w, item) {
  if (w.setup) return agentSetupItemDiff(w, item);  // 설정 도구 (agentsetup.js)
  const b = w.before || {};
  const a = w.after || {};
  if (/^\d+$/.test(item.key)) {
    const n = Number(item.key);
    const old = (b.episodes || []).find((e) => e.plot.number === n);
    const now = (a.episodes || []).find((e) => e.plot.number === n);
    if (!now) return '';
    return PLOT_FIELDS.map(([k, l]) => diffField(l, k, old ? old.plot[k] : (Array.isArray(now.plot[k]) ? [] : ''), now.plot[k])).join('');
  }
  if (item.key === 'arc' && b.arc && a.arc) return ARC_FIELDS.map(([k, l]) => diffField(l, k, b.arc[k], a.arc[k])).join('')
    + (b.arc.end_ep !== a.arc.end_ep ? `<div class="diff-row"><span class="act-label">범위</span><del>${epRange(b.arc.start_ep, b.arc.end_ep)}</del><ins>${epRange(a.arc.start_ep, a.arc.end_ep)}</ins></div>` : '');
  if (item.key === 'acts') return actsDiff({ acts: a.arc ? a.arc.acts : a.acts, total_episodes: 0 }, b.arc ? b.arc.acts : b.acts || []);
  if (item.key === 'parts') return (a.parts || []).map((x) => `<div class="diff-row"><span class="act-label">${x.number}부</span><ins>${esc(x.title)} · ${epRange(x.start_ep, x.end_ep)}</ins></div>`).join('');
  if (item.key === 'draft' && w.revision) return arcDiff(w.revision, null, plannedUntil() + 1);
  if (item.key === 'renumber' && w.op) return agentOpNotes(w.op);
  if (item.key === 'text') {
    const x = agentTextEdit(w);
    return x ? `<div class="pdiff small-diff">${typeof wordDiff === 'function' ? wordDiff(x.before, x.after) : esc(x.after)}</div>` : '';
  }
  if (w.style) {  // 문체 칸: 적용하기 전 문체와 넣은 값
    const e = w.style.revision.edits.find((x) => x.key === item.key);
    return e && w.style.before ? styleEditDiff(e, w.style.before[item.key]) : '';
  }
  return '';
}

/** 본문 고치기로 넣은 수정 기록 (Episode.edits). 기록이 잘렸으면 null */
function agentTextEdit(w) {
  const e = w.edit && ep(w.episode);
  return e ? (e.edits || []).find((x) => x.id === w.edit) || null : null;
}

/** 문체 변경안 카드: 바꿀 칸을 지금 값과 나란히 보이고 시험 문단을 함께 보인다. 권한 모드와 상관없이 늘 묻고 '묻지 않기'는 없다 (서버 agent_style) */
function agentStyleApproval(t, i, last) {
  const a = t.approval;
  const wait = a.state === 'wait' && t.end === 'wait' && last;
  const rev = a.style.revision;
  const head = { wait: '<span class="chip warn">승인 기다림</span>', approved: '<span class="chip ok">적용함</span>', denied: '<span class="chip">거절함</span>' }[a.state];
  const rows = rev.edits.map((e) => {
    const key = `${i}:${e.key}`;
    if (S.agentPicks[key] === undefined) S.agentPicks[key] = true;
    const name = esc(STYLE_LABEL[e.key] || e.key);
    // 답한 뒤에는 지금 문체가 이미 바뀌었을 수 있어 비교를 감춘다 (적용한 것은 '이번 턴에 바꾼 것'이 적용 전 · 뒤로 보인다)
    if (!wait) return `<div class="prop-part"><span class="prop-head"><strong>${name}</strong>${a.picked.includes(e.key) ? '<span class="chip ok">적용함</span>' : ''}</span></div>`;
    return `<div class="prop-part"><label class="prop-head"><input type="checkbox" data-agent-pick="${key}"${S.agentPicks[key] ? ' checked' : ''}><strong>${name}</strong></label>
      ${e.why ? `<div class="small">${esc(e.why)}</div>` : ''}<div class="diff">${styleEditDiff(e, P().style[e.key])}</div></div>`;
  }).join('');
  const sample = wait && rev.preview ? `<div class="prop-part"><strong>시험 문단 <span class="small" style="font-weight:400">바뀐 문체로 쓴 글이에요. 본문에는 들어가지 않아요</span></strong>
    ${sampleBlock(rev.preview, rev.preview_source, a.style.episode)}</div>` : '';
  return `<div class="approval${wait ? '' : ' settled'}">
    <div class="row">${head}<strong>문체 ${rev.edits.length}칸 바꾸기</strong></div>
    ${wait ? '<span class="small">문체는 권한 모드와 상관없이 물어봐요. 고른 칸만 이 작품 문체에 들어가고, 적용한 뒤에도 취소할 수 있어요.</span>' : ''}
    ${rows}${sample}
    ${wait ? `<div class="row proposal-actions"><button type="button" class="btn small" data-action="agentDecide" data-arg="${i}|0">거절</button>
        <button type="button" class="btn small primary" data-action="agentDecide" data-arg="${i}|1">고른 칸 적용</button></div>` : ''}
  </div>`;
}

/** 화 넣기 · 빼기의 안내 줄 (agent.apply_op 이 낸 notes, 새 화 제목) */
function agentOpNotes(op) {
  const titles = op.kind === 'insert' ? op.titles.map((t, k) => `<li>${op.at + k}화 ${esc(t || '제목 없음')}${op.summaries[k] ? ` · <span class="small">${esc(op.summaries[k])}</span>` : ''}</li>`).join('') : '';
  return `${titles ? `<ul class="option-changes">${titles}</ul>` : ''}${op.notes.map((x) => `<div class="small">${esc(x)}</div>`).join('')}`;
}

/** 화 넣기 · 빼기 승인 카드: 고를 부분 없이 통째로 승인 · 거절한다. 권한 모드와 상관없이 늘 묻는다 */
function agentOpApproval(t, i, last) {
  const a = t.approval;
  const wait = a.state === 'wait' && t.end === 'wait' && last;
  const head = { wait: '<span class="chip warn">승인 기다림</span>', approved: '<span class="chip ok">승인함</span>', denied: '<span class="chip">거절함</span>' }[a.state];
  const name = a.op.kind === 'remove' ? `${a.op.at}화 빼기` : `${a.op.at}화 앞에 새 화 ${a.op.titles.length}개 넣기`;
  return `<div class="approval${wait ? '' : ' settled'}">
    <div class="row">${head}<strong>${esc(name)}</strong></div>
    ${wait ? `<span class="small">뒤 화 번호가 바뀌어 권한 모드와 상관없이 물어봐요. 상태를 반영한 화는 옮기지 않아요.</span>
      <div class="small"><strong>승인하면 이렇게 돼요</strong></div>${agentOpNotes(a.op)}
      <div class="row proposal-actions"><button type="button" class="btn small" data-action="agentDecide" data-arg="${i}|0">거절</button>
        <button type="button" class="btn small primary" data-action="agentDecide" data-arg="${i}|1">승인하고 이어 하기</button></div>` : ''}
  </div>`;
}

function agentWrites(s, t, i) {
  // 본문 고치기로 넣은 것을 수정 기록에서 되돌렸으면 되돌린 것으로 보인다 (passage.js 의 '되돌리기'와 같은 기록)
  const state = (w, x) => (x.key === 'text' && x.state === 'done' && (agentTextEdit(w) || {}).undone ? 'reverted' : x.state);
  const items = t.writes.flatMap((w, wi) => w.items.map((x) => ({ w, wi, x: { ...x, state: state(w, x) } })));
  if (!items.length) return '';
  const live = items.some(({ x }) => x.state === 'done' && x.key !== 'draft');
  const styleOnly = t.writes.every((w) => w.style);  // 문체 칸은 기록 하나를 통째로 취소한다 (옛 문체 대화의 '적용 취소'와 같다)
  const chip = { done: '<span class="chip ok">바로 씀</span>', reverted: '<span class="chip">되돌림</span>', kept: '<span class="chip warn">남김</span>' };
  const open = false;  // 화 플롯 비교는 길어서 접어 둔다 (펴서 본다)
  return `<div class="writes"><div class="card-head"><strong>이번 턴에 바꾼 것 · ${items.length}</strong>
      ${live ? `<button type="button" class="btn small" data-action="agentUndo" data-arg="${i}">${styleOnly ? '적용 취소' : '이 턴 모두 되돌리기'}</button>` : ''}</div>
    ${items.map(({ w, wi, x }) => {
      const diff = agentItemDiff(w, x);
      const act = x.key === 'draft'
        ? `<button type="button" class="btn small" data-action="agentPutDraft" data-arg="${i}|${wi}">초안에 다시 넣기</button>`
        : x.state === 'done' && !w.style ? `<button type="button" class="btn small" data-action="agentUndo" data-arg="${i}|${wi}|${x.key}">되돌리기</button>` : '';
      const mark = w.style && x.state === 'done' ? '<span class="chip ok">적용함</span>' : chip[x.state];  // 문체 칸은 작가가 카드에서 골라 넣었다
      return `<div class="prop-part"><div class="between"><span class="prop-head"><strong>${esc(x.label)}</strong>${mark}</span>${act}</div>
        ${x.reason ? `<span class="small">${esc(x.reason)}</span>` : ''}
        ${diff ? (open ? `<div class="diff">${diff}</div>` : `<details><summary class="small">바뀐 칸 보기</summary><div class="diff">${diff}</div></details>`) : ''}</div>`;
    }).join('')}</div>`;
}

/** 본문 고치기 카드: 후보 2~3개 가운데 하나를 골라 넣는다(손봐서 넣기 포함). 권한 모드와 상관없이 늘 묻는다 */
function agentTextApproval(t, i, last) {
  const a = t.approval;
  const wait = a.state === 'wait' && t.end === 'wait' && last;
  const orig = a.selection.text;
  const now = typeof textNow === 'function' ? textNow(a.episode) : ((ep(a.episode) || {}).text || '');
  const lost = wait && !now.includes(orig);
  const diff = (b, c) => (typeof wordDiff === 'function' ? wordDiff(b, c) : esc(c));
  const head = { wait: '<span class="chip warn">고르기 기다림</span>', approved: '<span class="chip ok">넣음</span>', denied: '<span class="chip">넣지 않음</span>' }[a.state];
  const cards = a.passage.candidates.map((c, k) => {
    const key = `${i}:${k}`;
    const editing = wait && S.agentCand[key] !== undefined;
    const chosen = a.state === 'approved' && a.picked[0] === String(k);
    const body = editing ? `<textarea rows="5" data-agent-cand="${key}" aria-label="후보 ${k + 1} 손보기">${esc(S.agentCand[key])}</textarea>`
      : `<div class="pdiff">${diff(orig, c.text)}</div>`;
    const btns = !wait || lost ? '' : editing
      ? `<button type="button" class="btn small primary" data-action="agentPickTweak" data-arg="${key}">손본 글로 넣기</button><button type="button" class="btn small" data-action="agentCandTweak" data-arg="${key}">취소</button>`
      : `<button type="button" class="btn small primary" data-action="agentPickCand" data-arg="${key}">이걸로 넣기</button><button type="button" class="btn small" data-action="agentCandTweak" data-arg="${key}">손봐서 넣기</button>`;
    return `<div class="cand${chosen ? ' chosen' : ''}"><div class="between"><strong>후보 ${k + 1}${chosen ? ' · 넣음' : ''}</strong><span class="small">${(c.text.length - orig.length >= 0 ? '+' : '') + (c.text.length - orig.length)}자</span></div>
      ${c.note ? `<div class="small">${esc(c.note)}</div>` : ''}${body}${btns ? `<div class="row">${btns}</div>` : ''}</div>`;
  }).join('');
  const where = `${a.episode}화 «${esc(agentClip(orig.replace(/\s+/g, ' '), 40))}»`;
  if (!wait) return `<details class="approval settled"><summary class="row">${head}<strong>${where} · 후보 ${a.passage.candidates.length}개</strong></summary>${cards}</details>`;
  return `<div class="approval">
    <div class="row">${head}<strong>${where} · 후보 ${a.passage.candidates.length}개</strong></div>
    <span class="small">본문은 권한 모드와 상관없이 골라서 넣어요. 고른 후보 하나만 들어가고 수정 기록에 남아요.</span>
    ${lost ? '<div class="note plain">그사이 이 부분이 바뀌어 후보를 넣을 수 없어요. 다시 골라 요청하세요.</div>' : ''}
    ${cards}
    <div class="row proposal-actions"><button type="button" class="btn small" data-action="agentDecide" data-arg="${i}|0">모두 넣지 않기</button></div>
  </div>`;
}

function agentApproval(t, i, last) {
  const a = t.approval;
  if (a.op) return agentOpApproval(t, i, last);
  if (a.passage) return agentTextApproval(t, i, last);
  if (a.setup) return agentSetupApproval(t, i, last);  // 설정 도구: 칸마다 늘 묻는다 (agentsetup.js)
  if (a.style) return agentStyleApproval(t, i, last);
  const wait = a.state === 'wait' && t.end === 'wait' && last;
  const rev = a.revision;
  const base = revBase({ target: a.target });
  const head = { wait: '<span class="chip warn">승인 기다림</span>', approved: '<span class="chip ok">승인함</span>', denied: '<span class="chip">거절함</span>' }[a.state];
  const part = (k) => {
    const key = `${i}:${k}`;
    if (S.agentPicks[key] === undefined) S.agentPicks[key] = true;
    const box = wait ? `<input type="checkbox" data-agent-pick="${key}"${S.agentPicks[key] ? ' checked' : ''}>` : '';
    let name; let diff;
    if (/^\d+$/.test(k)) {
      const e = rev.episodes.find((x) => x.number === Number(k));
      const cur = ep(Number(k));
      name = `${k}화${e ? ` ${esc(e.title)}` : ''}${cur ? ` <span class="chip ${cur.status}">${STATUS[cur.status]}</span>` : ' <span class="chip ai">새 화</span>'}`;
      diff = e ? plotDiff(e) : '';
    } else if (k === 'arc') { name = base.arc ? `아크 ${base.arc.number} 칸` : '아크 칸'; diff = arcDiff(rev, base.arc, plannedUntil() + 1); }
    else if (k === 'acts') { name = base.arc ? `아크 ${base.arc.number} 기승전결` : '기승전결 구조'; diff = actsDiff(rev, base.acts); }
    else if (k === 'parts') { name = '부 구성'; diff = partsDiff(rev); }
    else if (k === 'draft') { name = '다음 아크 초안'; diff = arcDiff(rev, base.arc, plannedUntil() + 1); }
    else { name = esc(k); diff = ''; }
    // 답한 뒤에는 지금 값이 이미 바뀌었을 수 있어 비교를 감춘다 (쓴 것은 '이번 턴에 바꾼 것'이 쓰기 전 · 뒤로 보인다)
    if (!wait) return `<div class="prop-part"><span class="prop-head"><strong>${name}</strong>${a.picked.includes(k) ? '<span class="chip ok">씀</span>' : ''}</span></div>`;
    return `<div class="prop-part"><label class="prop-head">${box}<strong>${name}</strong></label>
      ${diff ? `<details${a.keys.length <= 2 ? ' open' : ''}><summary class="small">바뀌는 칸 보기</summary><div class="diff">${diff}</div></details>` : ''}</div>`;
  };
  const kinds = a.kinds.map((k) => AGENT_KINDS[k] || k).join(' · ');
  return `<div class="approval${wait ? '' : ' settled'}">
    <div class="row">${head}<strong>${a.keys.length}곳 쓰기</strong></div>
    ${wait ? `<span class="small">${esc(kinds)}${josa(kinds, '은', '는')} 지금 권한 모드(${AGENT_MODES[(agentSession() || {}).mode || 'draft'][0]})에서 물어보고 바꿔요.</span>` : ''}
    ${a.keys.map(part).join('')}
    ${wait ? `${a.kinds.some((k) => AGENT_ALWAYS.includes(k)) ? '' : `<label class="check"><input type="checkbox" data-agent-remember="${i}"${S.agentRemember[i] ? ' checked' : ''}> 이 세션에서 ${esc(kinds)}${josa(kinds, '은', '는')} 묻지 않고 바꾸기</label>`}
      <div class="row proposal-actions"><button type="button" class="btn small" data-action="agentDecide" data-arg="${i}|0">거절</button>
        <button type="button" class="btn small primary" data-action="agentDecide" data-arg="${i}|1">고른 것 승인하고 이어 하기</button></div>` : ''}
  </div>`;
}

function agentAsk(t, i, last) {
  const q = t.ask;
  if (!q.options.length) return '';
  const live = last && !agentRunningJob();
  return `<div class="ask-card"><strong>${esc(q.question || '어느 방향으로 갈까요?')}</strong>
    ${q.options.map((o, k) => `<div class="opt${S.agentPicks[`${i}:opt${k}`] ? ' sel' : ''}">
      <label class="prop-head">${live ? `<input type="checkbox" data-agent-pick="${i}:opt${k}"${S.agentPicks[`${i}:opt${k}`] ? ' checked' : ''}>` : ''}<strong>${k + 1}안 · ${esc(o.title)}</strong></label>
      <span>${esc(o.idea)}</span>
      ${o.changes.length ? `<ul class="option-changes">${o.changes.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
      ${o.tradeoff ? `<span class="small">얻는 것과 잃는 것 · ${esc(o.tradeoff)}</span>` : ''}
      ${live ? `<div class="row proposal-actions"><button type="button" class="btn small" data-action="agentDirection" data-arg="${i}|${k}">이 안으로</button></div>` : ''}</div>`).join('')}
    ${live ? `<div class="row proposal-actions"><button type="button" class="btn small primary" data-action="agentMix" data-arg="${i}">고른 안 섞기</button></div>
      <span class="small">마음에 드는 안이 없으면 아래 입력칸에 직접 답해 주세요.</span>` : ''}
  </div>`;
}

/** 다듬을 곳 고르기: 부 · 아크 · 다음 아크(장편), 작품 전체(단편), 한 화 플롯. 고른 곳 밖을 고치면 늘 물어요 (agent.outside) */
function agentTargetMenu(cur) {
  const p = P();
  const opt = (t, label, sub) => `<button type="button" class="mode-opt" aria-pressed="${t === cur}" data-action="agentTarget" data-arg="${esc(t)}"><strong>${esc(label)}</strong>${sub ? `<span class="small">${esc(sub)}</span>` : ''}</button>`;
  const head = (t) => `<div class="pop-title">${t}</div>`;
  const out = [];
  const here = agentScreenTarget();
  if (/^(text:\d+|setup|style)$/.test(here)) out.push(head('이 화면'), opt(here, agentTargetText(here), here === 'setup' ? '설정은 칸마다 물어보고 고쳐요. 플롯을 고치면 늘 물어봐요' : '읽고 답해요. 플롯을 고치면 늘 물어봐요'));
  if (serial()) out.push(opt('', '작품 전체', '플롯을 고치면 본문이 없는 첫 아크로 가요'));
  if (serial()) {
    if ((p.parts || []).length) out.push(head('부'), ...p.parts.map((x) => opt(`part:${x.number}`, `${x.number}부${x.title ? ` ${x.title}` : ''}`, `${epRange(x.start_ep, x.end_ep)} · 부 구성과 이 부의 아크`)));
    const arcs = [...p.story_arcs].sort((a, b) => a.start_ep - b.start_ep);
    out.push(head('아크'), ...arcs.map((a) => opt(`arc:${a.number}`, `아크 ${a.number}${a.title ? ` ${a.title}` : ''}`, `${epRange(a.start_ep, a.end_ep)} · 아크 칸 · 기승전결 · 화별 플롯`)));
    if (plannedUntil() < p.meta.target_episodes) out.push(opt('next', '다음 아크', `${plannedUntil() + 1}화부터 기획`));
  } else {
    out.push(opt('', '작품 전체', '기승전결 구조와 모든 화'));
  }
  const last = p.episodes.reduce((m, e) => Math.max(m, e.plot.number), 0);
  const open = Number(S.selEp) || 0;
  out.push(head('화 플롯'));
  if (open && ep(open)) out.push(opt(`ep:${open}`, `${open}화 플롯${ep(open).plot.title ? ` ${ep(open).plot.title}` : ''}`, '지금 연 화. 다른 화를 고치면 물어봐요'));
  if (last) {
    out.push(`<div class="row" style="padding:2px 10px 6px;gap:6px;flex-wrap:nowrap"><input id="agent-target-ep" type="number" min="1" max="${last}" value="${open || ''}" placeholder="화 번호" aria-label="다듬을 화 번호" style="width:90px">
      <button type="button" class="btn small" data-action="agentTargetEp">이 화로</button></div>`);
  }
  return `<div class="pop mode-menu target-menu" role="group" aria-label="다듬을 곳">
    <div class="pop-title">이 세션에서 다듬을 곳 · 다음 턴부터 · 고르면 고정돼요</div>
    ${out.join('')}
    <hr class="pop-sep"><span class="small" style="padding:0 10px 4px">고른 곳 밖(다른 화, 부를 골랐으면 그 부 밖)을 고치면 권한 모드와 상관없이 물어봐요.</span>
  </div>`;
}

function agentComposer() {
  const s = agentSession();
  const job = agentRunningJob();
  const mode = (s && s.mode) || 'draft';
  const target = agentTarget(s);
  const pinned = !!(s && s.pinned);
  const here = S.route[2] === 'arc' ? scopeText() : agentTargetText(agentScreenTarget());
  return `<div class="composer">
    <div class="pop slash-menu" id="agent-slash" role="group" aria-label="빠른 요청" hidden>
      <div class="pop-title">빠른 요청</div>
      ${AGENT_CMDS.map(([k, d]) => `<button type="button" class="cmd" data-action="agentCmd" data-arg="${k}" data-cmd="${k}"><b>${k}</b><span>${d}</span></button>`).join('')}
      ${agentTextCmds().map(([k, d, id]) => `<button type="button" class="cmd" data-action="agentPreset" data-arg="${esc(id)}" data-cmd="${esc(k)}"><b>${esc(k)}</b><span>${d}</span></button>`).join('')}
    </div>
    ${S.agentPlus ? `<div class="pop slash-menu" role="group" aria-label="함께 넣을 재료">
      <div class="pop-title">함께 넣을 재료 · 말에 붙여요</div>
      ${typeof curSel === 'function' && curSel() ? `<button type="button" class="cmd" data-action="agentMaterial" data-arg="sel"><b>고른 본문</b><span>${esc(agentClip(curSel().text.replace(/\s+/g, ' '), 40))}</span></button>` : ''}
      <button type="button" class="cmd" data-action="agentMaterial" data-arg="where"><b>보고 있는 곳</b><span>${esc(here)}</span></button>
      ${S.selEp && S.route[2] === 'arc' ? `<button type="button" class="cmd" data-action="agentMaterial" data-arg="ep"><b>${S.selEp}화 플롯</b><span>열린 화를 가리켜요</span></button>` : ''}
      <button type="button" class="cmd" data-action="agentMaterial" data-arg="find"><b>본문에서 찾기</b><span>«찾을 말»을 본문에서 찾아 보라고 해요</span></button>
      ${target === 'style' && textEps().length ? `<div class="cmd"><b>참고할 화</b>${epSelect('styleRefEp', S.styleRefEp, '참고할 화')}</div>` : ''}
    </div>` : ''}
    ${agentMats()}
    ${agentRefChip(target)}
    <div class="composer-box">
      <button type="button" class="comp-icon" data-action="agentPlusToggle" aria-label="함께 넣을 재료" aria-expanded="${S.agentPlus}">${AGENT_ICON.plus}</button>
      <textarea id="chat-input" rows="1" data-local="agentDraft" aria-label="AI에게 할 말" enterkeyhint="${touchFirst() ? 'enter' : 'send'}" placeholder="/ 입력 시 빠른 요청">${esc(S.agentDraft)}</textarea>
      ${job ? `<button type="button" class="comp-send stop" data-action="agentStop" aria-label="멈추기">${AGENT_ICON.stop}</button>`
        : `<button type="button" class="comp-send" data-action="agentSend" aria-label="보내기"${S.agentBusy ? ' disabled' : ''}>${AGENT_ICON.send}</button>`}
    </div>
    <div class="composer-foot">
      <button type="button" class="foot-mode" data-action="agentModeToggle" aria-haspopup="true" aria-expanded="${S.agentModeMenu}">${AGENT_MODES[mode][0]}</button>
      <button type="button" class="foot-mode foot-target" data-action="agentTargetToggle" aria-haspopup="true" aria-expanded="${S.agentTargetMenu}" title="이 세션에서 다듬을 곳. 고정하지 않으면 화면을 옮길 때 바뀌어요">${esc(agentTargetText(target))} ▾</button>
      <button type="button" class="foot-mode foot-pin" data-action="agentPin" aria-pressed="${pinned}" aria-label="${pinned ? '대상 고정 풀기' : '대상 고정'}" title="${pinned ? '고정을 풀면 화면을 옮길 때 대상이 바뀌어요' : '화면을 옮겨도 이 대상을 그대로 둬요'}">${AGENT_ICON.pin}</button>
      <span class="foot-right"><b>${esc(S.agent.model)}</b><span>${S.agent.max_steps}단계</span></span>
      ${S.agentModeMenu ? `<div class="pop mode-menu" role="group" aria-label="권한 모드">
        <div class="pop-title">이 세션의 권한 · 다음 턴부터</div>
        ${Object.entries(AGENT_MODES).map(([k, [l, d]]) => `<button type="button" class="mode-opt" aria-pressed="${k === mode}" data-action="agentMode" data-arg="${k}"><strong>${l}</strong><span class="small">${d}</span></button>`).join('')}
        <hr class="pop-sep"><span class="small" style="padding:0 10px 4px">어느 모드에서도 본문이 있는 화 · 관계 수치 · 지우기는 하지 않아요.</span>
      </div>` : ''}
      ${S.agentTargetMenu ? agentTargetMenu(target) : ''}
    </div>
  </div>`;
}

/** 문체 대상에서 고른 참고할 화 칩 (입력 상자 위). 턴과 함께 episode 로 가고, 지울 때까지 남는다 */
function agentRefChip(target) {
  const n = Number(S.styleRefEp) || 0;
  if (target !== 'style' || !n) return '';
  return `<div class="row" style="gap:6px;padding:0 2px 6px"><span class="chip ai">${n}화 참고</span>
    <button type="button" class="btn small" data-action="agentRefClear" aria-label="${n}화 참고 빼기">✕</button></div>`;
}

/** 진행만 바뀌면 대화 기록과 보내기 버튼만 바꾼다. 입력칸에서 치는 글자와 커서를 지킨다. */
function agentRedraw() {
  const typing = document.activeElement && document.activeElement.id === 'chat-input';
  if (!typing) { redrawChat(); return; }
  const log = $('#chat-log');
  if (log) {
    const atEnd = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    log.innerHTML = agentLog();
    if (atEnd) log.scrollTop = log.scrollHeight;
    chatAnnounce();
  }
  const btn = $('.composer .comp-send');
  const job = agentRunningJob();
  if (btn) btn.outerHTML = job ? `<button type="button" class="comp-send stop" data-action="agentStop" aria-label="멈추기">${AGENT_ICON.stop}</button>`
    : `<button type="button" class="comp-send" data-action="agentSend" aria-label="보내기">${AGENT_ICON.send}</button>`;
}

/** 그린 뒤(chat.js syncChat): 상태 줄의 대상이 바뀌었으면 그 칸을 한 번 강조하고 화면 낭독기에 알린다 */
function agentAfterDraw() {
  if (!S.agentFlash) return;
  const name = S.agentFlash;
  S.agentFlash = null;
  const el = document.querySelector('.chat-panel .foot-target');
  if (!el) return;
  el.classList.remove('flash');
  void el.offsetWidth;  // 같은 칸을 다시 강조할 때도 애니메이션이 처음부터 돈다
  el.classList.add('flash');
  chatSay(`다듬을 곳이 바뀌었어요: ${name}`);
}

/** pollJobs 가 이 작품의 'agent' 작업 진행이 바뀔 때 부른다. 끝났고 쓴 것이 있으면 작품을 다시 받는다. */
async function agentJobUpdate(j, old) {
  if (!S.chatOpen && j.status === 'running') return;
  try { await agentLoad(); } catch { return; }
  if (j.status !== 'running') {
    const s = (S.agent.sessions || []).find((x) => x.turns.some((t) => t.job === j.id));
    const t = s && s.turns.find((x) => x.job === j.id);
    const draft = t && t.writes.flatMap((w) => w.items.filter((i) => i.key === 'draft' && i.state === 'done').map(() => w))[0];
    if (draft && !S.arcDraft) agentPutDraft(draft, t.reply);  // 다음 아크 초안은 화면 초안 칸에 놓는다 (작품은 그대로)
    const wrote = t && t.writes.some((w) => w.items.some((i) => i.state === 'done' && i.key !== 'draft'));
    // 본문 고치기 카드는 작품을 바꾸지 않지만 부분 수정 대화(chats)에 후보를 남긴다. 화면 저장이 옛 사본으로 덮지 않게 받아 둔다
    const card = t && t.end === 'wait' && t.approval && t.approval.passage;
    if (wrote) await agentRefreshProject();
    else if (card) await agentRefreshProject('');
    else if (draft) { if (isTyping() || selecting()) S.renderPending = true; else render(); }
    if ($('.chat-panel')) {  // 패널이 결과를 보여 주므로 작업 목록에서는 바로 내린다
      S.jobsSeen.add(j.id);
      S.jobs = S.jobs.filter((x) => x.id !== j.id);
    }
    S.chatScroll = true;
  }
  if ($('.chat-panel')) agentRedraw();
}

async function agentRefreshProject(msg = 'AI가 플롯을 바꿨어요. 저장하지 않은 수정이 있어 화면은 그대로예요. 저장하면 겹치는 곳을 알려 줘요') {
  const fresh = await api('GET', `/projects/${enc(S.name)}`);
  if (!S.dirty) S.project = fresh;
  else if (msg) toast(msg, true);
  if (isTyping() || selecting()) S.renderPending = true;
  else render();
}

function agentPutDraft(w, reply) {
  S.arcDraft = draftFromRev({ revision: w.revision, text: reply || '' });
  S.selArc = 'next';
}

// ----- 동작 -----

async function agentEnsureSession() {
  if (agentSession()) return agentSession().id;
  const s = await api('POST', `/projects/${enc(S.name)}/sessions`, { topic: 'agent', target: agentScreenTarget() });
  await agentLoad();
  agentSelect(s.id);
  return s.id;
}

async function agentStartTurn(text, mode = '', preset = '') {
  if (S.agentBusy || agentRunningJob()) return toast('지금 턴이 끝난 뒤 보내세요. 멈추려면 ■ 를 누르세요', true);
  const mat = agentMaterialNow();
  if (preset && !mat) return toast('본문에서 고칠 부분을 먼저 드래그해 고르세요. 고른 부분이 재료로 붙어요', true);
  // 턴은 AI가 작품을 읽고 고친다. 저장하지 않은 변경은 묻고 나서 저장한다 (agentAct · startJob 과 같다). 취소하면 쓴 글은 칸에 남는다
  if (S.dirty && !(await askConfirm('저장하지 않은 변경이 있어요. 저장하고 이어갈까요?', { ok: '저장하고 이어가기' }))) return;
  S.agentBusy = true;
  const keep = S.agentDraft;
  S.agentDraft = '';
  S.chatScroll = true;
  redrawChat();
  try {
    await saveIfDirty();
    if (mat && typeof flushText === 'function') await flushText(mat.n);  // 서버는 저장된 본문에서 고른 부분을 찾는다
    const sid = await agentEnsureSession();
    const extra = mat ? { selection: { episode: mat.n, start: mat.start, text: mat.text }, preset } : {};
    const job = await api('POST', `/projects/${enc(S.name)}/sessions/${sid}/turns`, { message: text, mode, ...agentTurnScope(), ...extra });
    if (mat) S.agentMaterial = null;  // 보낸 재료는 뗀다. 후보를 넣으면 넣은 글이, 넣지 않으면 고른 부분이 다시 붙는다 (agentDecide)
    S.jobs = [...S.jobs.filter((x) => x.id !== job.id), job];
    await agentLoad();
    pollJobs(true);
  } catch (e) {
    S.agentDraft = keep;
    toast(e.message, true);
  } finally {
    S.agentBusy = false;
    S.chatScroll = true;
    redrawChat();
    $('#chat-input')?.focus();
  }
}

/** 턴과 함께 보내는 화면 정보. 플롯 화면은 연 구간 · 화와 다음 아크 초안, 다른 화면은 대상만 보낸다(그 화면에서 플롯 화면의 고른 칸은 지난 값이다).
    고정한 세션은 대상을 보내지 않는다 (서버 agent.add_turn 이 고정한 세션의 대상은 그대로 둔다) */
function agentTurnScope(s = agentSession()) {
  const target = agentTarget(s);
  // 문체 대상이면 episode 는 참고할 화 칩 (서버 agent_style.ref_episode)
  const sc = S.route[2] === 'arc' ? plotScope() : { act: '', episode: target === 'style' ? Number(S.styleRefEp) || 0 : 0, draft: target === 'next' ? S.arcDraft || null : null };
  // screen: 보던 화면. 플롯 화면 밖에서 작품 전체가 대상이면 서버가 플롯 쓰기를 늘 묻는다 (agent.off_plot)
  return { act: sc.act, episode: sc.episode, draft: sc.draft, screen: S.route[2] || 'home', ...(s && s.pinned ? {} : { target: agentScreenTarget() }) };
}

/** 세션 동작 공통. save: AI가 작품을 읽거나 고치는 동작이면 저장하지 않은 변경을 먼저 저장한다 (묻고 나서).
    세션 이름 · 대상 · 권한 모드 · 보관처럼 작품과 상관없는 동작은 save: false 로 묻지도 저장하지도 않는다 */
async function agentAct(fn, { save = true } = {}) {
  if (save && S.dirty && !(await askConfirm('저장하지 않은 변경이 있어요. 저장하고 이어갈까요?', { ok: '저장하고 이어가기' }))) return null;
  try {
    if (save) await saveIfDirty();
    const res = await fn();
    // 작업 정보(이어 하기 응답, jobs.Job.public)의 project 는 작품 이름 글이다. 작품 데이터(객체)일 때만 바꾼다
    if (res && res.project && typeof res.project === 'object' && !S.dirty) S.project = res.project;
    if (res && res.job) { S.jobs = [...S.jobs.filter((x) => x.id !== res.job.id), res.job]; pollJobs(true); }
    else if (res && res.id && res.kind === 'agent') { S.jobs = [...S.jobs.filter((x) => x.id !== res.id), res]; pollJobs(true); }
    await agentLoad();
    return res;
  } catch (e) {
    toast(e.message, true);
    return null;
  } finally {
    render();
  }
}

/** 본문 고치기 카드에 답한다. k: 넣을 후보 번호(-1 이면 넣지 않기), text: 손본 글. 넣으면 넣은 글을, 넣지 않으면 고른 부분을 다시 재료로 붙인다 */
async function agentTextDecide(i, k, text) {
  const s = agentSession();
  const a = s.turns[i].approval;
  const n = a.episode;
  if (typeof flushText === 'function') await flushText(n);  // 칸의 초안이 넣은 결과를 가리지 않게 (passage.js passageApply 와 같다)
  const body = k >= 0 ? { approve: true, picked: [String(k)], ...(text !== undefined ? { text } : {}) } : { approve: false };
  const res = await agentAct(() => api('POST', `/projects/${enc(S.name)}/sessions/${s.id}/turns/${i}/approval`, body));
  if (!res) return;
  Object.keys(S.agentCand).filter((x) => x.startsWith(`${i}:`)).forEach((x) => delete S.agentCand[x]);
  if (k < 0) {
    S.agentMaterial = { n, start: a.selection.start, text: a.selection.text };
    return toast('후보를 넣지 않았어요. 고른 부분은 재료로 다시 붙였어요');
  }
  const edit = ((ep(n) || {}).edits || []).slice(-1)[0];
  if (edit) {
    S.agentMaterial = { n, start: edit.start, text: edit.after };  // 이어서 '/더 짧게' 하면 넣은 글을 고친다
    if (typeof focusText === 'function' && S.route[2] === 'write' && Number(S.route[3]) === n && focusText(n, edit.after, edit.start) !== -1) S.selFocus.quiet = true;
    render();
  }
  if (edit && typeof undoToast === 'function') undoToast(`${k + 1}번 후보를 넣었어요.`, edit.id);
  else toast(`${k + 1}번 후보를 넣었어요`);
}

Object.assign(actions, {
  agentSend() {
    const text = (S.agentDraft || '').trim();
    if (!text) return;
    const pre = agentParsePreset(text);
    if (pre) return agentStartTurn(pre.rest || pre.label, '', pre.id);
    if (text.startsWith('/')) {
      const [cmd, ...rest] = text.split(/\s+/);
      if (cmd === '/여러안') {
        const msg = rest.join(' ').trim();
        if (!msg) return toast('무엇을 여러 안으로 받을지 /여러안 뒤에 적어 주세요', true);
        return agentStartTurn(msg, 'options');
      }
      if (AGENT_CMDS.some(([k]) => k === cmd)) { S.agentDraft = rest.join(' '); return actions.agentCmd(cmd); }
    }
    return agentStartTurn(text);
  },
  agentExample(text) {
    S.agentDraft = String(text);
    redrawChat();
    $('#chat-input')?.focus();
  },
  async agentCmd(cmd) {
    $('#agent-slash')?.setAttribute('hidden', '');
    if (cmd === '/여러안') {
      S.agentDraft = '/여러안 ' + (S.agentDraft || '').replace(/^\/\S*\s*/, '');
      redrawChat();
      return $('#chat-input')?.focus();
    }
    if (cmd === '/새세션') return actions.agentNew();
    const s = agentSession();
    if (cmd === '/대상') {
      if (!s) return toast('세션이 없어요. 말을 보내면 지금 보는 곳으로 세션이 생겨요');
      await agentAct(() => api('PATCH', `/projects/${enc(S.name)}/sessions/${s.id}`, { target: agentScreenTarget(), pinned: false }), { save: false });
      S.agentDraft = '';
      return toast(`대상 고정을 풀었어요: ${agentTargetText(agentScreenTarget())}`);
    }
    if (cmd === '/되돌리기') {
      const i = s ? s.turns.map((t, k) => (t.writes.some((w) => w.items.some((x) => x.state === 'done' && x.key !== 'draft')) ? k : -1)).filter((k) => k >= 0).pop() : undefined;
      S.agentDraft = '';
      if (i === undefined) { redrawChat(); return toast('되돌릴 턴이 없어요', true); }
      return actions.agentUndo(String(i));
    }
  },
  async agentNew() {
    S.agentMenu = false;
    await agentAct(async () => {
      const s = await api('POST', `/projects/${enc(S.name)}/sessions`, { topic: 'agent', target: agentScreenTarget() });
      agentSelect(s.id);
      return s;
    }, { save: false });
    $('#chat-input')?.focus();
  },
  agentPick(sid) {
    agentSelect(sid);
    redrawChat();
  },
  agentMenuToggle() {
    S.agentMenu = !S.agentMenu;
    S.agentModeMenu = S.agentPlus = S.agentTargetMenu = false;
    redrawChat();
  },
  agentModeToggle() {
    S.agentModeMenu = !S.agentModeMenu;
    S.agentMenu = S.agentPlus = S.agentTargetMenu = false;
    redrawChat();
  },
  agentTargetToggle() {
    S.agentTargetMenu = !S.agentTargetMenu;
    S.agentMenu = S.agentPlus = S.agentModeMenu = false;
    redrawChat();
  },
  /** 다듬을 곳 메뉴에서 고르면 그 대상으로 고정한다 (화면을 옮겨도 바뀌지 않는다) */
  async agentTarget(target) {
    S.agentTargetMenu = false;
    const s = agentSession();
    const res = await agentAct(async () => {
      if (s) return api('PATCH', `/projects/${enc(S.name)}/sessions/${s.id}`, { target, pinned: true });
      const made = await api('POST', `/projects/${enc(S.name)}/sessions`, { topic: 'agent', target, pinned: true });
      agentSelect(made.id);
      return made;
    }, { save: false });
    if (res) toast(`다듬을 곳을 고정했어요: ${agentTargetText(target)}`);
  },
  /** 상태 줄의 핀: 지금 대상으로 고정하거나 고정을 푼다. 세션이 없으면 고정한 새 세션을 연다 */
  async agentPin() {
    const s = agentSession();
    if (s && s.pinned) {
      const res = await agentAct(() => api('PATCH', `/projects/${enc(S.name)}/sessions/${s.id}`, { pinned: false }), { save: false });
      if (res) toast(`대상 고정을 풀었어요. 화면을 옮기면 바뀌어요: ${agentTargetText(agentScreenTarget())}`);
      return;
    }
    return actions.agentTarget(agentTarget(s));
  },
  agentTargetEp() {
    const n = Number(($('#agent-target-ep') || {}).value);
    if (!n || !ep(n)) return toast('플롯이 있는 화 번호를 넣으세요', true);
    return actions.agentTarget(`ep:${n}`);
  },
  agentPlusToggle() {
    S.agentPlus = !S.agentPlus;
    S.agentMenu = S.agentModeMenu = S.agentTargetMenu = false;
    redrawChat();
  },
  /** '/' 목록의 본문 빠른 요청: 입력칸에 더 적은 말이 있으면 함께 보낸다 */
  agentPreset(id) {
    $('#agent-slash')?.setAttribute('hidden', '');
    const label = agentPresetLabel(id);
    const rest = (S.agentDraft || '').replace(/^\/\S*\s*/, '').trim();
    if (!agentMaterialNow()) { redrawChat(); return toast('본문에서 고칠 부분을 먼저 드래그해 고르세요. 고른 부분이 재료로 붙어요', true); }
    return agentStartTurn(rest || label, '', id);
  },
  /** 집필 화면 머리의 'AI에게 고치기': 대화 에이전트를 열고(대상은 화면이 주는 text:N), 고른 본문이 있으면 재료로 붙인다. 열려 있으면 닫는다 */
  agentOpenText(n) {
    if (S.chatOpen) return actions.toggleChat();
    const sel = typeof curSel === 'function' ? curSel() : null;
    if (sel && sel.n === Number(n)) S.agentMaterial = { n: sel.n, start: sel.start, text: sel.text };
    return actions.toggleChat();
  },
  agentMaterialDrop() {
    agentAttach(null);
    $('#chat-input')?.focus();
  },
  agentMaterial(kind) {
    if (kind === 'sel') {
      const sel = typeof curSel === 'function' && curSel();
      S.agentPlus = false;
      if (sel) S.agentMaterial = { n: sel.n, start: sel.start, text: sel.text };
      redrawChat();
      return $('#chat-input')?.focus();
    }
    const add = { where: `(보고 있는 곳: ${S.route[2] === 'arc' ? scopeText() : agentTargetText(agentScreenTarget())}) `, ep: `${S.selEp}화 플롯을 보고, `, find: '본문에서 «» 이(가) 나온 단락을 찾아 보고, ' }[kind] || '';
    S.agentDraft = `${S.agentDraft || ''}${S.agentDraft && !/\s$/.test(S.agentDraft) ? ' ' : ''}${add}`;
    S.agentPlus = false;
    redrawChat();
    $('#chat-input')?.focus();
  },
  async agentMode(mode) {
    S.agentModeMenu = false;
    const s = agentSession();
    if (!s) { redrawChat(); return toast('세션이 없어요. 말을 보내면 세션이 생기고, 그 뒤 모드를 고를 수 있어요'); }
    await agentAct(() => api('PATCH', `/projects/${enc(S.name)}/sessions/${s.id}`, { mode }), { save: false });
  },
  async agentRename() {
    const s = agentSession();
    if (!s) return;
    const title = await askText('', { title: '세션 이름', value: s.title || '', ok: '이름 바꾸기' });
    if (title == null) return;
    S.agentMenu = false;
    await agentAct(() => api('PATCH', `/projects/${enc(S.name)}/sessions/${s.id}`, { title }), { save: false });
  },
  async agentArchive(arg) {
    const [sid, on] = String(arg).split('|');
    S.agentMenu = false;
    if (sid === S.agentSid && on === '1') S.agentSid = null;
    await agentAct(() => api('PATCH', `/projects/${enc(S.name)}/sessions/${sid}`, { archived: on === '1' }), { save: false });
    if (on === '0') agentSelect(sid);
  },
  async agentStop() {
    const j = agentRunningJob();
    if (!j) return;
    try { await api('POST', `/jobs/${j.id}/stop`); } catch (e) { toast(e.message, true); }
    pollJobs(true);
  },
  async agentContinue(i) {
    const s = agentSession();
    await agentAct(() => api('POST', `/projects/${enc(S.name)}/sessions/${s.id}/turns/${i}/continue`));
  },
  async agentDecide(arg) {
    const [i, yes] = String(arg).split('|');
    const s = agentSession();
    const a = s.turns[Number(i)].approval;
    if (a.passage) return agentTextDecide(Number(i), yes === '1' ? 0 : -1);
    const picked = a.setup ? agentSetupPicks(i, a) : a.keys.filter((k) => S.agentPicks[`${i}:${k}`] !== false);
    if (yes === '1' && !picked.length) return toast('쓸 곳을 체크해서 고르세요', true);
    const res = await agentAct(() => api('POST', `/projects/${enc(S.name)}/sessions/${s.id}/turns/${i}/approval`,
      { approve: yes === '1', picked, remember: !!S.agentRemember[i] }));
    if (res && yes === '1') toast(a.style ? `적용했어요: ${picked.map((k) => STYLE_LABEL[k] || k).join(', ')}. 다음 화부터 이 문체로 써요` : '승인한 곳을 썼어요. 이어서 돌아요');
  },
  /** 본문 고치기 카드의 '이걸로 넣기' (arg '턴:후보') */
  agentPickCand(arg) {
    const [i, k] = String(arg).split(':').map(Number);
    return agentTextDecide(i, k);
  },
  /** 손본 글로 넣기 */
  agentPickTweak(arg) {
    const [i, k] = String(arg).split(':').map(Number);
    return agentTextDecide(i, k, S.agentCand[arg]);
  },
  agentCandTweak(arg) {
    const [i, k] = String(arg).split(':').map(Number);
    if (S.agentCand[arg] !== undefined) delete S.agentCand[arg];
    else S.agentCand[arg] = agentSession().turns[i].approval.passage.candidates[k].text;
    redrawChat();
  },
  async agentUndo(arg) {
    const [i, w, key] = String(arg).split('|');
    const s = agentSession();
    // 본문을 되돌린다: 칸의 초안이 서버 본문을 가리지 않게 먼저 저장한다 (passage.js undoEdit 와 같다)
    const texts = [...new Set(s.turns[Number(i)].writes.filter((x, k) => x.edit && (w === undefined || k === Number(w))).map((x) => x.episode))];
    if (typeof flushText === 'function') for (const n of texts) await flushText(n);
    const res = await agentAct(() => api('POST', `/projects/${enc(S.name)}/sessions/${s.id}/turns/${i}/undo`,
      { write: w === undefined ? null : Number(w), key: key === undefined ? null : key }));
    if (!res) return;
    const kept = res.kept.map((x, k) => `${x}(${res.reasons[k]})`).join(', ');
    toast(res.restored.length ? `되돌렸어요: ${res.restored.join(', ')}${kept ? ` · 그대로 둔 것: ${kept}` : ''}` : `되돌린 것이 없어요. 그대로 둔 것: ${kept}`, !res.restored.length);
  },
  agentRefClear() {
    S.styleRefEp = '';
    redrawChat();
  },
  agentPutDraft(arg) {
    const [i, w] = String(arg).split('|').map(Number);
    const t = agentSession().turns[i];
    agentPutDraft(t.writes[w], t.reply);
    render();
    toast('다음 아크 초안에 넣었어요. 살펴보고 \'이 아크 적용\'을 누르세요');
  },
  agentDirection(arg) {
    const [i, k] = String(arg).split('|').map(Number);
    const o = agentSession().turns[i].ask.options[k];
    agentStartTurn(`${k + 1}안 '${o.title}' 방향으로 고쳐 줘.${S.agentDraft.trim() ? ` ${S.agentDraft.trim()}` : ''}`);
  },
  agentMix(i) {
    const opts = agentSession().turns[Number(i)].ask.options;
    const ks = opts.map((_, k) => k).filter((k) => S.agentPicks[`${i}:opt${k}`]);
    if (!ks.length) return toast('섞을 안을 체크해서 고르세요', true);
    const names = ks.map((k) => `${k + 1}안 '${opts[k].title}'`);
    agentStartTurn(ks.length === 1 ? `${names[0]} 방향으로 고쳐 줘.` : `${names.join('과 ')}을 섞어서 고쳐 줘. 각 안에서 살릴 것을 골라 하나의 흐름으로 이어 줘.`);
  },
});

document.addEventListener('change', (e) => {
  const d = e.target.dataset || {};
  if (d.agentPick) {
    S.agentPicks[d.agentPick] = e.target.checked;
    if (d.agentPick.includes(':opt')) e.target.closest('.opt')?.classList.toggle('sel', e.target.checked);
  }
  if (d.agentRemember) S.agentRemember[d.agentRemember] = e.target.checked;
  if (d.local === 'styleRefEp' && e.target.closest('.composer')) {  // '+ 재료'에서 참고할 화를 고르면 칩으로 붙인다
    S.styleRefEp = e.target.value;
    S.agentPlus = false;
    redrawChat();
  }
});
document.addEventListener('input', (e) => {
  const k = e.target.dataset && e.target.dataset.agentCand;
  if (k !== undefined) S.agentCand[k] = e.target.value;
});

// '/' 로 시작하면 빠른 요청 목록을 띄우고 친 글자로 거른다. 패널을 다시 그리지 않아 커서를 지킨다
document.addEventListener('input', (e) => {
  if (e.target.id !== 'chat-input' || S.chatTopic !== 'plot') return;
  const box = $('#agent-slash');
  if (!box) return;
  // 본문 빠른 요청은 이름에 띄어쓰기가 있다('/더 짧게'). 띄어쓰기를 빼고 견준다
  const v = e.target.value;
  const word = v.startsWith('/') ? v.replace(/\s+/g, '') : null;
  const hits = word === null ? [] : [...box.querySelectorAll('[data-cmd]')].filter((b) => b.dataset.cmd.replace(/\s+/g, '').startsWith(word));
  box.hidden = !hits.length;
  box.querySelectorAll('[data-cmd]').forEach((b) => { b.hidden = !hits.includes(b); });
});

// 패널 밖을 누르면 펼친 목록을 닫는다
document.addEventListener('click', (e) => {
  if (!(S.agentMenu || S.agentModeMenu || S.agentPlus || S.agentTargetMenu)) return;
  if (e.target.closest('.pop, .sess-btn, .foot-mode, .comp-icon')) return;
  S.agentMenu = S.agentModeMenu = S.agentPlus = S.agentTargetMenu = false;
  redrawChat();
});

// 이번 단계에서 기다린 시간과 늦음 안내는 대화 기록을 다시 그리지 않고 1초마다 그 자리만 고친다 (app.js 의 data-elapsed 와 같은 방식)
setInterval(() => {
  document.querySelectorAll('[data-step-wait]').forEach((el) => {
    const j = S.jobs.find((x) => x.id === el.dataset.stepWait);
    if (j && j.status === 'running') el.textContent = agentStepWait(j);
  });
  document.querySelectorAll('[data-step-now]').forEach((el) => {
    const j = S.jobs.find((x) => x.id === el.dataset.stepNow);
    if (j && j.status === 'running') el.textContent = agentStepNow(j);
  });
  document.querySelectorAll('[data-step-slow]').forEach((el) => {
    const j = S.jobs.find((x) => x.id === el.dataset.stepSlow);
    el.hidden = !(j && j.status === 'running' && agentStepSec(j) > AGENT_SLOW && !j.retry);  // 까닭(retry)이 보이면 일반 안내는 숨긴다
  });
}, 1000);

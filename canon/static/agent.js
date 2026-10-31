/* 대화 에이전트 패널 (플롯 대화, 서버 canon/agent.py). chat.js 의 chatPanel('plot') 이 이 패널을 그린다.
   세션 머리(제목 · 대상 · 세션 목록), 턴마다 단계 줄 · 답 · 바로 쓴 것(되돌리기) · 승인 카드 · 되묻기, 입력 상자(+ 재료, / 빠른 요청, 보내기 · 멈추기),
   상태 줄(권한 모드 · 대상 · 모델 · 단계 상한). 턴은 백그라운드 작업 'agent' 로 돌고, pollJobs 가 진행을 알려 주면 세션만 다시 받는다.
   옛 단발 대화 기록은 '이전 대화'로 지금 카드(chat.js proposal)를 그대로 보인다. 권한 이름은 agent.MODE_LABELS · KIND_LABELS 와 같다. */
'use strict';

const AGENT_MODES = { ask: ['물어보기', '쓰기마다 그 자리에서 승인해요.'],
  draft: ['빈 곳 · 초안만 자동', '초안 화 · 새 화 · 다음 아크 초안은 바로 쓰고, 확정한 화와 범위는 물어요.'],
  all: ['모두 자동', '막힌 것 말고는 묻지 않고 써요. 턴마다 되돌릴 수 있어요.'] };
const AGENT_KINDS = { draft: '초안 화', next: '다음 아크 초안', confirmed: '확정한 화', arc: '아크 칸', acts: '구간 · 범위', parts: '부 구성' };
const AGENT_CMDS = [['/여러안', '바꾸기 전에 방향 여러 안으로 물어요'], ['/대상', '이 세션의 대상을 지금 보는 곳으로'],
  ['/새세션', '지금 보는 곳으로 새 세션'], ['/되돌리기', '마지막으로 바꾼 턴 되돌리기']];
const AGENT_STEP_ICON = { read: '읽', write: '씀', wait: '물', block: '막', ask: '?', note: '·' };
const AGENT_LEGACY = 'legacy';
const AGENT_ICON = {
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"></path></svg>',
  send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M6 11l6-6 6 6"></path></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2"></rect></svg>',
  down: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"></path></svg>',
};

Object.assign(S, {
  agent: null,          // 서버 GET sessions: { name, sessions, legacy, model, max_steps }
  agentSid: null,       // 연 세션 id ('legacy' 는 이전 대화)
  agentDraft: '',
  agentMenu: false,     // 세션 목록
  agentModeMenu: false, // 권한 모드 메뉴
  agentPlus: false,     // 함께 넣을 재료
  agentPicks: {},       // '턴:부분' → 승인 카드에서 쓸지
  agentRemember: {},    // 턴 → 이 세션에서 묻지 않기
  agentBusy: false,     // 보내는 중 (작업이 뜨기 전)
});

JOB_PAGES.agent = [];  // 패널만 다시 그린다 (agentJobUpdate)
JOB_DONE_MSG.agent = (j) => `${j.label}: 턴이 끝났어요`;
JOB_LINK.agent = (j) => `#/p/${enc(j.project)}/arc`;

// ----- 데이터 -----

function agentKey() { return `canon.agent.${S.name}`; }

async function agentLoad() {
  if (!S.name) return;
  const name = S.name;
  const res = await api('GET', `/projects/${enc(name)}/sessions?topic=plot`);
  if (name !== S.name) return;
  S.agent = { name, ...res };
  const live = res.sessions.filter((s) => !s.archived);
  let sid = S.agentSid;
  if (!sid) { try { sid = localStorage.getItem(agentKey()); } catch { sid = null; } }
  if (sid !== AGENT_LEGACY && !res.sessions.some((s) => s.id === sid)) sid = null;
  if (sid === AGENT_LEGACY && !res.legacy) sid = null;
  if (!sid) sid = live.length ? [...live].sort((a, b) => (b.updated || '').localeCompare(a.updated || ''))[0].id : (res.legacy ? AGENT_LEGACY : null);
  S.agentSid = sid;
}

function agentSession() {
  return S.agent && S.agentSid && S.agentSid !== AGENT_LEGACY ? S.agent.sessions.find((s) => s.id === S.agentSid) || null : null;
}

function agentRunningJob() {
  return S.jobs.find((j) => j.status === 'running' && j.project === S.name && j.kind === 'agent');
}

function agentTargetText(target) {
  const a = plotTargetArc(target);
  if (a) return `아크 ${a.number}${a.title ? ` ${a.title}` : ''}`;
  if (target === 'next') return `다음 아크 (${plannedUntil() + 1}화부터)`;
  return serial() ? '본문이 없는 첫 아크' : '작품 전체';
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
    return `<aside class="chat-panel" aria-label="대화로 다듬기"><div class="chat-log" id="chat-log"><div class="msg ai pending" role="status"><span class="spinner small" aria-hidden="true"></span>대화 세션을 불러오는 중…</div></div></aside>`;
  }
  const s = agentSession();
  const legacy = S.agentSid === AGENT_LEGACY;
  const title = legacy ? '이전 대화' : s ? (s.title || '새 세션') : '새 세션';
  const sub = legacy ? `플롯 · 옛 기록 ${S.agent.legacy}개` : `플롯 · 대상: ${agentTargetText(s ? s.target : plotScope().target)}`;
  return `<aside class="chat-panel" aria-label="대화로 다듬기">
    <div class="chat-head">
      <button type="button" class="sess-btn" data-action="agentMenuToggle" aria-haspopup="true" aria-expanded="${S.agentMenu}">
        <strong><span class="sess-title">${esc(title)}</span>${AGENT_ICON.down}</strong><span class="small">${esc(sub)}</span></button>
      <div class="row" style="gap:4px;flex-wrap:nowrap">
        <button type="button" class="btn small" data-action="agentNew">새 세션 열기</button>
        <button type="button" class="btn icon-btn" data-action="toggleChat" aria-label="닫기">✕</button></div>
      ${S.agentMenu ? agentMenu() : ''}
    </div>
    <div class="chat-log" id="chat-log">${agentLog()}</div>
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
  return `<div class="pop sess-menu" role="group" aria-label="플롯 대화 세션">
    <div class="pop-title">플롯 대화 세션 · ${live.length}</div>
    ${live.map(row).join('') || '<div class="small" style="padding:6px 10px">아직 세션이 없어요. 말을 보내면 새 세션이 생겨요.</div>'}
    ${S.agent.legacy ? `<button type="button" class="sess-item" aria-current="${S.agentSid === AGENT_LEGACY}" data-action="agentPick" data-arg="${AGENT_LEGACY}"><span class="t">이전 대화</span><span class="small">예전 방식 기록 ${S.agent.legacy}개 · 변경안을 골라 적용</span><span class="chip">읽기</span></button>` : ''}
    ${cur ? `<hr class="pop-sep"><div class="row" style="padding:0 6px"><button type="button" class="btn small" data-action="agentRename">이름 바꾸기</button><button type="button" class="btn small" data-action="agentArchive" data-arg="${cur.id}|1">이 세션 보관</button></div>` : ''}
    ${kept.length ? `<details style="padding:0 10px"><summary>보관함 · ${kept.length}</summary>
      ${kept.map((s) => `<div class="between" style="padding:4px 0"><span class="small">${esc(s.title || '새 세션')} · ${fmtDate(s.updated || s.created)}</span><button type="button" class="btn small" data-action="agentArchive" data-arg="${s.id}|0">꺼내기</button></div>`).join('')}</details>` : ''}
  </div>`;
}

function agentLog() {
  if (S.agentSid === AGENT_LEGACY) {
    return `<div class="note plain">예전 방식(한 번에 변경안 하나) 대화 기록이에요. 변경안은 예전처럼 골라서 적용하거나 취소할 수 있어요. 새로 말하면 새 세션이 열려요.</div>${chatLog('plot')}`;
  }
  const s = agentSession();
  if (!s || !s.turns.length) {
    const t = CHAT_TOPICS.plot;
    return `<div class="note info">구조와 플롯을 말로 고쳐요. AI가 필요한 플롯과 본문을 읽고 고치며, 아래 권한 모드에 따라 초안은 바로 쓰고 확정한 화나 범위는 물어봐요. 바로 쓴 것은 되돌릴 수 있고, 본문이 있는 화는 바꾸지 않아요.</div>
      <div class="row">${t.examples.map((x) => `<button type="button" class="btn small" data-action="agentExample" data-arg="${esc(x)}">${esc(x)}</button>`).join('')}</div>`;
  }
  return s.turns.map((t, i) => agentTurn(s, t, i)).join('');
}

function agentTurn(s, t, i) {
  const last = i === s.turns.length - 1;
  const running = t.end === '';
  const count = (k) => t.steps.filter((x) => x.kind === k).length;
  const sum = [['read', '읽음'], ['write', '바꿈'], ['wait', '승인 기다림'], ['block', '막힘'], ['ask', '되물음']]
    .map(([k, l]) => (count(k) ? `${l} ${count(k)}` : '')).filter(Boolean).join(' · ') || (running ? '시작하는 중' : '단계 없음');
  const steps = t.steps.length || running ? `<details class="turn-steps"${running || (last && t.end === 'wait') ? ' open' : ''}>
      <summary><b>${esc(sum)}</b><span class="caret">단계 ${t.steps.length}</span></summary>
      <ol class="step-list">${t.steps.map((x) => `<li class="step ${x.kind}"><span class="ico" aria-hidden="true">${AGENT_STEP_ICON[x.kind] || '·'}</span>
        <span class="what"><b>${esc(agentToolName(x.tool))}</b>${x.label ? ` · ${esc(x.label)}` : ''}</span><span class="why">${esc(x.why)}</span></li>`).join('')}
      ${running ? `<li class="step run"><span class="ico" aria-hidden="true">…</span><span class="what">다음 단계를 고르는 중</span><span class="why"></span></li>` : ''}</ol></details>` : '';
  const job = running ? agentRunningJob() : null;
  const bar = running ? `<div class="run-bar" role="status"><span class="spinner small" aria-hidden="true"></span>
      <span>${job ? job.done : t.steps.length}/${S.agent.max_steps}단계</span><span class="run-meter" aria-hidden="true"><i style="width:${Math.round(((job ? job.done : 0) / S.agent.max_steps) * 100)}%"></i></span></div>` : '';
  const ends = {
    cap: `<div class="note warn"><div>${S.agent.max_steps}단계에서 멈췄어요. 이어서 더 할 수 있어요.</div>${last ? `<div class="row proposal-actions"><button type="button" class="btn small primary" data-action="agentContinue" data-arg="${i}">이어 하기</button></div>` : ''}</div>`,
    stopped: `<div class="note plain"><div>멈췄어요. 쓰던 것은 저장하지 않았어요.${t.error ? ` (${esc(t.error)})` : ''}</div>${last ? `<div class="row proposal-actions"><button type="button" class="btn small" data-action="agentContinue" data-arg="${i}">이어 하기</button></div>` : ''}</div>`,
    error: `<div class="note err"><div>오류로 멈췄어요: ${esc(t.error)}</div>${last ? `<div class="row proposal-actions"><button type="button" class="btn small" data-action="agentContinue" data-arg="${i}">다시 이어 하기</button></div>` : ''}</div>`,
  };
  const blocks = running ? [] : t.steps.filter((x) => x.kind === 'block');
  // 묻는 중이면 답이 카드 앞에(무엇을 묻는지), 끝났으면 쓴 것 뒤에(무엇을 했는지) 온다
  const reply = t.reply ? `<div class="msg-text">${esc(t.reply)}</div>` : '';
  const asking = t.end === 'wait' || t.end === 'ask';
  return `<div class="msg user">${t.mode === 'options' ? '<span class="chip" style="background:var(--glass);color:var(--accent-ink)">/여러안</span> ' : ''}${esc(t.user)}</div>
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
    edit_plot: '플롯 고치기', ask: '되묻기', approval: '작가의 답' }[tool] || tool;
}

/** 바로 쓴 것 한 부분의 바뀐 칸. 쓰기 전 · 뒤 값(before · after)으로 비교한다 (지금 값은 이미 바뀌었다). */
function agentItemDiff(w, item) {
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
  return '';
}

function agentWrites(s, t, i) {
  const items = t.writes.flatMap((w, wi) => w.items.map((x) => ({ w, wi, x })));
  if (!items.length) return '';
  const live = items.some(({ x }) => x.state === 'done' && x.key !== 'draft');
  const chip = { done: '<span class="chip ok">바로 씀</span>', reverted: '<span class="chip">되돌림</span>', kept: '<span class="chip warn">남김</span>' };
  const open = false;  // 화 플롯 비교는 길어서 접어 둔다 (펴서 본다)
  return `<div class="writes"><div class="card-head"><strong>이번 턴에 바꾼 것 · ${items.length}</strong>
      ${live ? `<button type="button" class="btn small" data-action="agentUndo" data-arg="${i}">이 턴 모두 되돌리기</button>` : ''}</div>
    ${items.map(({ w, wi, x }) => {
      const diff = agentItemDiff(w, x);
      const act = x.key === 'draft'
        ? `<button type="button" class="btn small" data-action="agentPutDraft" data-arg="${i}|${wi}">초안에 다시 넣기</button>`
        : x.state === 'done' ? `<button type="button" class="btn small" data-action="agentUndo" data-arg="${i}|${wi}|${x.key}">되돌리기</button>` : '';
      return `<div class="prop-part"><div class="between"><span class="prop-head"><strong>${esc(x.label)}</strong>${chip[x.state]}</span>${act}</div>
        ${x.reason ? `<span class="small">${esc(x.reason)}</span>` : ''}
        ${diff ? (open ? `<div class="diff">${diff}</div>` : `<details><summary class="small">바뀐 칸 보기</summary><div class="diff">${diff}</div></details>`) : ''}</div>`;
    }).join('')}</div>`;
}

function agentApproval(t, i, last) {
  const a = t.approval;
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
    ${wait ? `<span class="small">${esc(kinds)}은(는) 지금 권한 모드(${AGENT_MODES[(agentSession() || {}).mode || 'draft'][0]})에서 물어보고 바꿔요.</span>` : ''}
    ${a.keys.map(part).join('')}
    ${wait ? `<label class="check"><input type="checkbox" data-agent-remember="${i}"${S.agentRemember[i] ? ' checked' : ''}> 이 세션에서 ${esc(kinds)}은(는) 묻지 않고 바꾸기</label>
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

function agentComposer() {
  const s = agentSession();
  const job = agentRunningJob();
  const mode = (s && s.mode) || 'draft';
  const target = s ? s.target : plotScope().target;
  const here = scopeText();
  return `<div class="composer">
    <div class="pop slash-menu" id="agent-slash" role="group" aria-label="빠른 요청" hidden>
      <div class="pop-title">빠른 요청</div>
      ${AGENT_CMDS.map(([k, d]) => `<button type="button" class="cmd" data-action="agentCmd" data-arg="${k}" data-cmd="${k}"><b>${k}</b><span>${d}</span></button>`).join('')}
    </div>
    ${S.agentPlus ? `<div class="pop slash-menu" role="group" aria-label="함께 넣을 재료">
      <div class="pop-title">함께 넣을 재료 · 말에 붙여요</div>
      <button type="button" class="cmd" data-action="agentMaterial" data-arg="where"><b>보고 있는 곳</b><span>${esc(here)}</span></button>
      ${S.selEp ? `<button type="button" class="cmd" data-action="agentMaterial" data-arg="ep"><b>${S.selEp}화 플롯</b><span>열린 화를 가리켜요</span></button>` : ''}
      <button type="button" class="cmd" data-action="agentMaterial" data-arg="find"><b>본문에서 찾기</b><span>«찾을 말»을 본문에서 찾아 보라고 해요</span></button>
    </div>` : ''}
    <div class="composer-box">
      <button type="button" class="comp-icon" data-action="agentPlusToggle" aria-label="함께 넣을 재료" aria-expanded="${S.agentPlus}">${AGENT_ICON.plus}</button>
      <textarea id="chat-input" rows="1" data-local="agentDraft" aria-label="AI에게 할 말" enterkeyhint="${touchFirst() ? 'enter' : 'send'}" placeholder="/ 입력 시 빠른 요청">${esc(S.agentDraft)}</textarea>
      ${job ? `<button type="button" class="comp-send stop" data-action="agentStop" aria-label="멈추기">${AGENT_ICON.stop}</button>`
        : `<button type="button" class="comp-send" data-action="agentSend" aria-label="보내기"${S.agentBusy ? ' disabled' : ''}>${AGENT_ICON.send}</button>`}
    </div>
    <div class="composer-foot">
      <button type="button" class="foot-mode" data-action="agentModeToggle" aria-haspopup="true" aria-expanded="${S.agentModeMenu}">${AGENT_MODES[mode][0]}</button>
      <span class="foot-meta">${esc(agentTargetText(target))}</span>
      <span class="foot-right"><b>${esc(S.agent.model)}</b><span>${S.agent.max_steps}단계</span></span>
      ${S.agentModeMenu ? `<div class="pop mode-menu" role="group" aria-label="권한 모드">
        <div class="pop-title">이 세션의 권한 · 다음 턴부터</div>
        ${Object.entries(AGENT_MODES).map(([k, [l, d]]) => `<button type="button" class="mode-opt" aria-pressed="${k === mode}" data-action="agentMode" data-arg="${k}"><strong>${l}</strong><span class="small">${d}</span></button>`).join('')}
        <hr class="pop-sep"><span class="small" style="padding:0 10px 4px">어느 모드에서도 본문이 있는 화 · 관계 수치 · 지우기는 하지 않아요.</span>
      </div>` : ''}
    </div>
  </div>`;
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
  }
  const btn = $('.composer .comp-send');
  const job = agentRunningJob();
  if (btn) btn.outerHTML = job ? `<button type="button" class="comp-send stop" data-action="agentStop" aria-label="멈추기">${AGENT_ICON.stop}</button>`
    : `<button type="button" class="comp-send" data-action="agentSend" aria-label="보내기">${AGENT_ICON.send}</button>`;
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
    if (wrote) await agentRefreshProject();
    else if (draft) { if (isTyping() || selecting()) S.renderPending = true; else render(); }
    if ($('.chat-panel')) {  // 패널이 결과를 보여 주므로 작업 목록에서는 바로 내린다
      S.jobsSeen.add(j.id);
      S.jobs = S.jobs.filter((x) => x.id !== j.id);
    }
    S.chatScroll = true;
  }
  if ($('.chat-panel')) agentRedraw();
}

async function agentRefreshProject() {
  const fresh = await api('GET', `/projects/${enc(S.name)}`);
  if (!S.dirty) S.project = fresh;
  else toast('AI가 플롯을 바꿨어요. 저장하지 않은 수정이 있어 화면은 그대로예요. 저장하면 겹치는 곳을 알려 줘요', true);
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
  const s = await api('POST', `/projects/${enc(S.name)}/sessions`, { topic: 'plot', target: plotScope().target });
  await agentLoad();
  agentSelect(s.id);
  return s.id;
}

async function agentStartTurn(text, mode = '') {
  if (S.agentBusy || agentRunningJob()) return toast('지금 턴이 끝난 뒤 보내세요. 멈추려면 ■ 를 누르세요', true);
  S.agentBusy = true;
  const keep = S.agentDraft;
  S.agentDraft = '';
  S.chatScroll = true;
  redrawChat();
  try {
    await saveIfDirty();
    const sid = await agentEnsureSession();
    const sc = plotScope();
    const job = await api('POST', `/projects/${enc(S.name)}/sessions/${sid}/turns`, { message: text, mode, act: sc.act, episode: sc.episode, draft: sc.draft });
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

async function agentAct(fn) {
  try {
    await saveIfDirty();
    const res = await fn();
    if (res && res.project && !S.dirty) S.project = res.project;
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

Object.assign(actions, {
  agentSend() {
    const text = (S.agentDraft || '').trim();
    if (!text) return;
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
      await agentAct(() => api('PATCH', `/projects/${enc(S.name)}/sessions/${s.id}`, { target: plotScope().target }));
      S.agentDraft = '';
      return toast(`대상을 바꿨어요: ${agentTargetText(plotScope().target)}`);
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
      const s = await api('POST', `/projects/${enc(S.name)}/sessions`, { topic: 'plot', target: plotScope().target });
      agentSelect(s.id);
      return s;
    });
    $('#chat-input')?.focus();
  },
  agentPick(sid) {
    agentSelect(sid);
    redrawChat();
  },
  agentMenuToggle() {
    S.agentMenu = !S.agentMenu;
    S.agentModeMenu = S.agentPlus = false;
    redrawChat();
  },
  agentModeToggle() {
    S.agentModeMenu = !S.agentModeMenu;
    S.agentMenu = S.agentPlus = false;
    redrawChat();
  },
  agentPlusToggle() {
    S.agentPlus = !S.agentPlus;
    S.agentMenu = S.agentModeMenu = false;
    redrawChat();
  },
  agentMaterial(kind) {
    const add = { where: `(보고 있는 곳: ${scopeText()}) `, ep: `${S.selEp}화 플롯을 보고, `, find: '본문에서 «» 이(가) 나온 단락을 찾아 보고, ' }[kind] || '';
    S.agentDraft = `${S.agentDraft || ''}${S.agentDraft && !/\s$/.test(S.agentDraft) ? ' ' : ''}${add}`;
    S.agentPlus = false;
    redrawChat();
    $('#chat-input')?.focus();
  },
  async agentMode(mode) {
    S.agentModeMenu = false;
    const s = agentSession();
    if (!s) { redrawChat(); return toast('세션이 없어요. 말을 보내면 세션이 생기고, 그 뒤 모드를 고를 수 있어요'); }
    await agentAct(() => api('PATCH', `/projects/${enc(S.name)}/sessions/${s.id}`, { mode }));
  },
  async agentRename() {
    const s = agentSession();
    if (!s) return;
    const title = prompt('세션 이름', s.title || '');
    if (title == null) return;
    S.agentMenu = false;
    await agentAct(() => api('PATCH', `/projects/${enc(S.name)}/sessions/${s.id}`, { title }));
  },
  async agentArchive(arg) {
    const [sid, on] = String(arg).split('|');
    S.agentMenu = false;
    if (sid === S.agentSid && on === '1') S.agentSid = null;
    await agentAct(() => api('PATCH', `/projects/${enc(S.name)}/sessions/${sid}`, { archived: on === '1' }));
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
    const picked = a.keys.filter((k) => S.agentPicks[`${i}:${k}`] !== false);
    if (yes === '1' && !picked.length) return toast('쓸 곳을 체크해서 고르세요', true);
    const res = await agentAct(() => api('POST', `/projects/${enc(S.name)}/sessions/${s.id}/turns/${i}/approval`,
      { approve: yes === '1', picked, remember: !!S.agentRemember[i] }));
    if (res && yes === '1') toast('승인한 곳을 썼어요. 이어서 돌아요');
  },
  async agentUndo(arg) {
    const [i, w, key] = String(arg).split('|');
    const s = agentSession();
    const res = await agentAct(() => api('POST', `/projects/${enc(S.name)}/sessions/${s.id}/turns/${i}/undo`,
      { write: w === undefined ? null : Number(w), key: key === undefined ? null : key }));
    if (!res) return;
    const kept = res.kept.map((x, k) => `${x}(${res.reasons[k]})`).join(', ');
    toast(res.restored.length ? `되돌렸어요: ${res.restored.join(', ')}${kept ? ` · 그대로 둔 것: ${kept}` : ''}` : `되돌린 것이 없어요. 그대로 둔 것: ${kept}`, !res.restored.length);
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

// 플롯 대화는 이 패널이 보낸다 (Enter 보내기는 chat.js 가 chatSend 를 부른다)
const legacyChatSend = actions.chatSend;
actions.chatSend = function (preset) {
  return S.chatTopic === 'plot' ? actions.agentSend() : legacyChatSend.call(this, preset);
};

document.addEventListener('change', (e) => {
  const d = e.target.dataset || {};
  if (d.agentPick) {
    S.agentPicks[d.agentPick] = e.target.checked;
    if (d.agentPick.includes(':opt')) e.target.closest('.opt')?.classList.toggle('sel', e.target.checked);
  }
  if (d.agentRemember) S.agentRemember[d.agentRemember] = e.target.checked;
});

// '/' 로 시작하면 빠른 요청 목록을 띄우고 친 글자로 거른다. 패널을 다시 그리지 않아 커서를 지킨다
document.addEventListener('input', (e) => {
  if (e.target.id !== 'chat-input' || S.chatTopic !== 'plot') return;
  const box = $('#agent-slash');
  if (!box) return;
  const v = e.target.value;
  const word = v.startsWith('/') && !/\s/.test(v) ? v : null;
  box.hidden = word === null;
  if (word !== null) box.querySelectorAll('[data-cmd]').forEach((b) => { b.hidden = !b.dataset.cmd.startsWith(word); });
});

// 패널 밖을 누르면 펼친 목록을 닫는다
document.addEventListener('click', (e) => {
  if (!(S.agentMenu || S.agentModeMenu || S.agentPlus)) return;
  if (e.target.closest('.pop, .sess-btn, .foot-mode, .comp-icon')) return;
  S.agentMenu = S.agentModeMenu = S.agentPlus = false;
  redrawChat();
});

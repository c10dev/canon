/* 알림: AI 작업과 알림(toast)을 버튼 하나에 모은다.
   버튼은 사이드바 이름 옆 '찾기' 앞(900px 이하는 위쪽 띠, 레일은 찾기 위, 작품 밖 화면은 본문 맨 위 오른쪽)에 있다.
   사이드바와 휴대폰 폭은 글자 없이 기호와 수 배지만 보인다.
   누르면 버튼 아래에 창(#hub-pop)이 열린다: 확인할 것 · 진행 중 · 최근 알림, 접힌 끝난 작업 · 지난 알림.
   알림은 버튼 바로 아래 말풍선(#toast)으로 뜨고 기록(S.notes)에 남는다 (app.js toast).
   보이는 상태 계산(hubState · hubAgo)은 순수 함수라 node 로 맞춰 본다 (tests/test_hub_js.py). */
'use strict';

const HUB_NOTES = 60;   // 기록에 남기는 알림 수
const HUB_RECENT = 5;   // '최근 알림'에 보이는 수. 나머지는 접힌 '지난 알림'

// 검토를 기다리는 결과(서버 pending.json, app.js PENDING_KINDS): 창에 쓸 이름과 그 결과가 보이는 화면
const HUB_RESULT = {
  state: (r) => [`${r.ep}화 상태 변경안`, `/review/${r.ep}`],
  arc: () => ['기승전결 구조 제안', '/arc'],
  suggest: () => ['설정 제안', '/setup'],
  series: () => ['부 구성 제안', '/arc'],
  nextarc: () => ['다음 아크 제안', '/arc'],
  recap_arc: (r) => [`아크 ${r.ep} 요약 제안`, '/arc'],
  recap_part: (r) => [`${r.ep}부 요약 제안`, '/arc'],
  fold_knows: (r) => [`아크 ${r.ep} 아는 정보 접기 제안`, '/arc'],
  storyline: () => ['이야기 줄기 제안', '/lines'],
  convert: () => ['장편 전환 계획', '/convert'],
  rebuild: () => ['재구성 안', '/convert'],
  rework: (r) => [`${r.ep}화 다듬기 안`, `/write/${r.ep}`],
  openings: (r) => [`${r.ep}화 여는 방식 안`, '/arc'],
};
// 자동 집필이 사람을 기다리며 끝난 상태 (옛 작업 목록의 '검토 필요' 표시와 같다)
const HUB_AUTO_WAIT = { review: '검토가 필요해요', paused: '일시정지했어요', error: '오류로 멈췄어요' };

/** 버튼과 창에 보일 것. 순수 함수: 브라우저 상태를 읽지 않는다.
    input: { jobs, pending: { name, results, failures }, notes: [{ at, msg, err }](새것이 앞), offline, seenAt(창을 마지막으로 연 시각 ms),
             seenJobs(창에서 이미 본 끝난 작업 id 목록), name(지금 작품) }
    face: 버튼 모양 'offline' | 'running' | 'attention'(실패 · 멈춘 자동 집필) | 'result'(검토 대기 결과만) | 'done' | 'note'(새 알림만) | 'none'(버튼 없음) */
function hubState(input) {
  const jobs = input.jobs || [];
  const pend = input.pending && input.pending.name === input.name ? input.pending : { results: {}, failures: {} };
  const running = jobs.filter((j) => j.status === 'running');
  const autoWait = (j) => j.kind === 'auto' && j.status === 'done' && j.result && HUB_AUTO_WAIT[j.result.status];
  const failed = jobs.filter((j) => j.status === 'error');
  const waits = jobs.filter(autoWait);
  // 같은 작업이 목록에 실패로 남아 있으면 지난 시도 실패(pending)는 겹쳐 보이지 않는다
  const live = new Set(failed.filter((j) => j.project === input.name).map((j) => `${j.kind}:${j.ep ?? ''}`));
  const fails = Object.values(pend.failures || {}).filter((f) => !live.has(f.key));
  const results = Object.values(pend.results || {}).filter((r) => HUB_RESULT[r.kind]);
  const attention = [
    ...failed.map((j) => ({ type: 'job', job: j })),
    ...waits.map((j) => ({ type: 'auto', job: j, what: HUB_AUTO_WAIT[j.result.status] })),
    ...fails.map((f) => ({ type: 'fail', fail: f })),
    ...results.map((r) => { const [label, path] = HUB_RESULT[r.kind](r); return { type: 'result', result: r, label, path }; }),
  ];
  const red = failed.length + fails.length + waits.filter((j) => j.result.status === 'error').length > 0;
  const finished = jobs.filter((j) => (j.status === 'done' && !autoWait(j)) || j.status === 'cancelled');
  const notes = input.notes || [];
  const unseen = notes.filter((n) => n.at > (input.seenAt || 0)).length;
  const seen = new Set(input.seenJobs || []);
  const freshDone = finished.some((j) => !seen.has(j.id));
  const urgent = attention.length - results.length;  // 결과만 있으면 주황, 실패 · 멈춤이 있으면 빨강
  let face = 'none';
  if (input.offline) face = 'offline';
  else if (running.length) face = 'running';
  else if (urgent) face = 'attention';
  else if (results.length) face = 'result';
  else if (freshDone) face = 'done';
  else if (unseen) face = 'note';
  const label = { offline: '끊김', running: `AI ${running.length}`, attention: `확인 ${attention.length}`, result: `결과 ${results.length}`,
    done: `끝남 ${finished.length}`, note: '알림', none: '알림' }[face];
  const parts = [
    input.offline && '서버 연결 끊김',
    running.length && `AI 작업 ${running.length}개 진행 중`,
    attention.length && `확인할 것 ${attention.length}개`,
    face === 'done' && `끝난 작업 ${finished.length}개`,
    unseen && `새 알림 ${unseen}개`,
  ].filter(Boolean);
  return {
    face, label, aria: `알림${parts.length ? `: ${parts.join(', ')}` : ''}`,
    badge: face === 'running' || face === 'offline' ? attention.length : 0, red,
    running, attention, finished, unseen,
    recent: notes.slice(0, HUB_RECENT), older: notes.slice(HUB_RECENT),
  };
}

/** 알림이 뜬 때를 '방금' · 'n분 전' · 'n시간 전' 으로. 하루가 지나면 날짜 시각. at · now 는 ms. */
function hubAgo(at, now) {
  const s = Math.max(0, Math.round((now - at) / 1000));
  if (s < 60) return '방금';
  if (s < 3600) return `${Math.floor(s / 60)}분 전`;
  if (s < 86400) return `${Math.floor(s / 3600)}시간 전`;
  return typeof fmtDateTime === 'function' ? fmtDateTime(new Date(at).toISOString()) : '';
}

// ---------- 화면 ----------

/** 알림을 기록에 남긴다 (app.js toast 가 부른다). 새것이 앞. */
function hubNote(msg, err) {
  S.notes.unshift({ at: Date.now(), msg: String(msg), err: !!err });
  if (S.notes.length > HUB_NOTES) S.notes.length = HUB_NOTES;
}

function hubNow() {
  return hubState({ jobs: S.jobs, pending: S.pending, notes: S.notes, offline: S.jobsOffline, seenAt: S.hubSeen,
    seenJobs: [...S.hubSeenJobs], name: S.name });
}

const HUB_ICON = {
  offline: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M2 2l10 10M3 7a5 5 0 0 1 4-4M11 7a5 5 0 0 1-4 4"></path></svg>',
  attention: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="7" cy="7" r="5.5"></circle><path d="M7 4v3.6M7 9.6v.2"></path></svg>',
  result: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="7" cy="7" r="5.5"></circle><path d="M4.5 7.2 6.3 9l3.3-3.6"></path></svg>',
  done: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M3.5 7.2 6 9.6l4.5-5"></path></svg>',
  note: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M3.5 10V6.5a3.5 3.5 0 0 1 7 0V10ZM2.5 10h9M5.8 12h2.4"></path></svg>',
};
HUB_ICON.none = HUB_ICON.note;

/** 알림 버튼. 보일 것이 없고 창도 닫혀 있으면 그리지 않는다. 사이드바(app.js sidebar)와 작품 밖 화면 머리가 #hub-slot 에 넣는다. */
function hubButton(st = hubNow()) {
  if (st.face === 'none' && !S.hubOpen) return '';
  const icon = st.face === 'running' ? '<span class="spinner sm" aria-hidden="true"></span>' : HUB_ICON[st.face];
  const mark = st.badge ? `<span class="hub-badge${st.red ? '' : ' amber'}" aria-hidden="true">${st.badge}</span>`
    : st.face === 'note' ? '<span class="hub-dot" aria-hidden="true"></span>' : '';
  // 글자를 빼고 기호만 보이는 자리(넓은 폭 사이드바 · 레일 · 휴대폰 폭)에서 글자 대신 보이는 수 배지 (app.css .hub-n)
  const n = { attention: st.attention.length, result: st.attention.length, done: st.finished.length }[st.face];
  const count = n ? `<span class="hub-badge hub-n${{ attention: '', result: ' amber', done: ' green' }[st.face]}" aria-hidden="true">${n}</span>` : '';
  return `<button type="button" id="hub-btn" class="btn small hub-btn ${st.face}${S.hubOpen ? ' on' : ''}" aria-haspopup="dialog" aria-expanded="${S.hubOpen}" aria-controls="hub-pop" aria-label="${esc(st.aria)}" title="${esc(st.aria)}" data-hub-toggle>${icon}<span aria-hidden="true">${esc(st.label)}</span>${mark}${count}</button>`;
}

/** 작품 밖 화면(작품 목록 · 사용량 · 문체 라이브러리) 본문 맨 위 오른쪽의 버튼 칸. 버튼이 없으면 칸도 접힌다 (app.css .hub-top:empty). */
function hubTop() {
  return `<div class="hub-top" id="hub-slot">${hubButton()}</div>`;
}

/** 작업 한 줄의 덧붙임: 다른 작품 이름, 지금 보는 화면이면 '이 화면' */
function hubWhere(j) {
  if (j.project !== S.name) return ` <span class="chip">${esc(j.project)}</span>`;
  const link = JOB_LINK[j.kind] && JOB_LINK[j.kind](j);
  return link && location.hash.startsWith(link) ? ' <span class="chip">이 화면</span>' : '';
}

function hubAttention(a) {
  if (a.type === 'job') {
    const j = a.job;
    const retry = S.jobArgs[j.id] ? `<button type="button" class="btn small" data-job-retry="${j.id}">다시 시도</button>` : '';
    const keyHelp = /API 키|연결/.test(j.error || '') ? '<a class="btn small" href="#/settings/ai">설정</a>' : '';
    return `<li class="hub-item err"><div class="hub-t"><strong>${esc(j.label)}${josa(j.label, '이', '가')} 실패했어요</strong>${hubWhere(j)}<div class="small">${esc(j.error || '')}</div></div>
      <div class="row">${retry}${keyHelp}<button type="button" class="btn small ghost" data-job-dismiss="${j.id}">닫기</button></div></li>`;
  }
  if (a.type === 'auto') {
    const j = a.job;
    return `<li class="hub-item${j.result.status === 'error' ? ' err' : ' warn'}"><div class="hub-t"><strong>자동 집필이 ${a.what}</strong>${hubWhere(j)}${j.note ? `<div class="small">${esc(j.note)}</div>` : ''}</div>
      <div class="row"><a class="btn small" href="${JOB_LINK.auto(j)}">자동 집필로</a><button type="button" class="btn small ghost" data-job-dismiss="${j.id}">닫기</button></div></li>`;
  }
  if (a.type === 'fail') {
    const f = a.fail;
    const keyHelp = /API 키|연결/.test(f.error || '') ? '<a class="btn small" href="#/settings/ai">설정</a>' : '';
    return `<li class="hub-item err"><div class="hub-t"><strong>지난 시도 실패 · ${esc(f.label)}</strong><div class="small">${esc(f.error || '')}</div></div>
      <div class="row">${keyHelp}<button type="button" class="btn small ghost" data-action="dismissFail" data-arg="${esc(f.key)}">닫기</button></div></li>`;
  }
  return `<li class="hub-item warn"><div class="hub-t"><strong>${esc(a.label)}${josa(a.label, '이', '가')} 도착했어요</strong><div class="small">${a.result.kind === 'state' ? '아직 반영하지 않았어요' : '아직 적용하지 않았어요'}</div></div>
    <a class="btn small" href="${base()}${a.path}">가서 보기</a></li>`;
}

function hubRunning(j) {
  const sub = [j.total > 1 ? `${j.done}/${j.total}단계` : '', j.note, `경과 ${elapsed(j)}`, jobLeft(j, Date.now() / 1000)].filter(Boolean).join(' · ');
  const bar = j.total > 1 ? `<div class="hub-bar" role="progressbar" aria-label="${esc(j.label)} 진행" aria-valuemin="0" aria-valuemax="${j.total}" aria-valuenow="${j.done}"><i style="width:${Math.round((j.done / j.total) * 100)}%"></i></div>` : '';
  const act = j.kind === 'auto' ? `<a class="btn small" href="${JOB_LINK.auto(j)}">자동 집필로</a>` : `<button type="button" class="btn small" data-job-stop="${j.id}">멈추기</button>`;
  return `<li class="hub-item"><div class="hub-t"><strong>${esc(j.label)}</strong>${hubWhere(j)}<div class="small">${esc(sub)}</div>${bar}</div>${act}</li>`;
}

function hubFinished(j) {
  const state = j.status === 'cancelled' ? '<span class="chip">멈춤</span>' : '<span class="chip ok">완료</span>';
  const open = j.status === 'done' && j.kind in JOB_LINK ? `<a href="${JOB_LINK[j.kind](j)}" data-job-open="${j.id}">열기</a>` : '';
  return `<li class="hub-item plain">${state}<div class="hub-t"><strong>${esc(j.label)}</strong>${hubWhere(j)}</div>${open}<button type="button" class="x" data-job-dismiss="${j.id}" aria-label="${esc(j.label)} 목록에서 지우기">✕</button></li>`;
}

function hubNoteRow(n, now) {
  return `<li class="hub-note${n.err ? ' err' : ''}"><span>${esc(n.msg)}</span><span class="small">${hubAgo(n.at, now)}</span></li>`;
}

function hubPopHtml(st) {
  const now = Date.now();
  const any = st.attention.length || st.running.length || st.recent.length || st.finished.length;
  const more = st.finished.length + st.older.length;
  const moreLabel = [st.finished.length && `끝난 작업 ${st.finished.length}`, st.older.length && `지난 알림 ${st.older.length}`].filter(Boolean).join(' · ');
  return `<div class="hub-head"><h2 id="hub-title" tabindex="-1">알림</h2><button type="button" class="icon-btn hub-x" data-hub-close aria-label="알림 닫기">✕</button></div>
    <div class="hub-body">
      ${S.jobsOffline ? '<p class="note warn">서버 연결이 끊겼어요. 다시 연결하는 중…</p>' : ''}
      ${st.attention.length ? `<h3 class="hub-h">확인할 것 ${st.attention.length}</h3><ul class="hub-list">${st.attention.map(hubAttention).join('')}</ul>` : ''}
      ${st.running.length ? `<h3 class="hub-h">진행 중 ${st.running.length}</h3><ul class="hub-list">${st.running.map(hubRunning).join('')}</ul>` : ''}
      ${st.recent.length ? `<h3 class="hub-h">최근 알림</h3><ul class="hub-list notes">${st.recent.map((n) => hubNoteRow(n, now)).join('')}</ul>` : ''}
      ${any ? '' : '<p class="hub-empty">새 알림이 없어요. 시작한 AI 작업과 알림이 여기에 모여요.</p>'}
      ${more ? `<details class="hub-more" id="hub-more"${S.hubMore ? ' open' : ''}><summary>${moreLabel}</summary>
        ${st.finished.length ? `<ul class="hub-list">${st.finished.map(hubFinished).join('')}</ul>` : ''}
        ${st.older.length ? `<ul class="hub-list notes">${st.older.map((n) => hubNoteRow(n, now)).join('')}</ul>` : ''}</details>` : ''}
    </div>
    <div class="hub-foot"><span class="small">Esc로 닫아요</span>${more || st.recent.length ? '<button type="button" class="btn small ghost" data-hub-clear>끝난 것 지우기</button>' : ''}</div>`;
}

/** 버튼 · 창 · 말풍선을 지금 상태로 맞춘다. 작업을 물을 때마다(1.5초) 부르므로 바뀐 것만 다시 그린다. */
function renderHub() {
  const st = hubNow();
  const slot = $('#hub-slot');
  if (slot) {
    const html = hubButton(st);
    if (slot.dataset.html !== html) {
      const had = document.activeElement && document.activeElement.id === 'hub-btn';
      slot.innerHTML = html;
      slot.dataset.html = html;
      if (had && $('#hub-btn')) $('#hub-btn').focus({ preventScroll: true });
    }
  }
  drawHubPop(st);
  placeHub();
}

function drawHubPop(st) {
  let pop = $('#hub-pop');
  const toasts = $('#toast');
  if (toasts) toasts.hidden = !!S.hubOpen;  // 창이 열린 동안 말풍선은 창 안 '최근 알림'으로 본다
  if (!S.hubOpen) { if (pop) pop.remove(); return; }
  if (!pop) {
    pop = document.createElement('section');
    pop.id = 'hub-pop';
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-labelledby', 'hub-title');
    document.body.appendChild(pop);
  }
  const html = hubPopHtml(st);
  if (pop.dataset.html === html) return;
  // 창 안 버튼(멈추기 · 다시 시도 · 닫기)에 있던 포커스를 다시 그린 뒤 같은 버튼에 돌려준다. 접힌 칸 안 스크롤도 남긴다
  const f = pop.contains(document.activeElement) ? document.activeElement : null;
  const keys = ['data-job-stop', 'data-job-retry', 'data-job-dismiss', 'data-job-open', 'data-hub-close', 'data-hub-clear', 'data-arg'];
  const key = f && keys.find((a) => f.hasAttribute(a));
  const val = key ? f.getAttribute(key) : null;
  const body = pop.querySelector('.hub-body');
  const scroll = body ? body.scrollTop : 0;
  pop.dataset.html = html;
  pop.innerHTML = html;
  const nb = pop.querySelector('.hub-body');
  if (nb) nb.scrollTop = scroll;
  if (f) {
    const back = (key && pop.querySelector(`[${key}${val ? `="${CSS.escape(val)}"` : ''}]`)) || $('#hub-title');
    if (back) back.focus({ preventScroll: true });
  }
}

/** 창과 말풍선을 버튼 바로 아래에 둔다. 버튼이 화면 밖(좁은 폭에서 위쪽 띠를 지나 내렸을 때)이거나 없으면 화면 맨 위. */
function placeHub() {
  const btn = $('#hub-btn');
  const r = btn && btn.getBoundingClientRect();
  const shown = !!r && r.width > 0 && r.bottom > 0 && r.top < window.innerHeight;
  const phone = window.innerWidth <= 640;
  const top = shown ? Math.round(r.bottom + 8) : 8;
  const at = (w, edge) => (phone ? edge : shown ? Math.max(14, Math.round(r.right) - w) : edge);
  const pop = $('#hub-pop');
  if (pop) {
    const w = phone ? window.innerWidth - 16 : Math.min(400, window.innerWidth - 16);
    Object.assign(pop.style, { top: `${top}px`, left: `${at(w, 8)}px`, width: `${w}px`, maxHeight: `${Math.max(200, window.innerHeight - top - 16)}px` });
  }
  const toasts = $('#toast');
  if (toasts) {
    const w = phone ? window.innerWidth - 32 : Math.min(360, window.innerWidth - 32);
    Object.assign(toasts.style, { top: `${top}px`, left: `${at(w, 16)}px`, width: `${w}px` });
  }
}

function hubOpen() {
  S.hubOpen = true;
  S.hubSeen = Date.now();
  hubNow().finished.forEach((j) => S.hubSeenJobs.add(j.id));
  renderHub();
  const t = $('#hub-title');
  if (t) t.focus({ preventScroll: true });
}

/** 창을 닫는다. back 이면 버튼으로 포커스를 돌린다 (버튼이 사라졌으면 본문으로). */
function hubClose(back = true) {
  if (!S.hubOpen) return;
  S.hubOpen = false;
  S.hubSeen = Date.now();
  renderHub();
  if (!back) return;
  const btn = $('#hub-btn') || $('#main');
  if (btn) btn.focus({ preventScroll: true });
}

document.addEventListener('click', (e) => {
  const t = e.target.closest && e.target.closest('[data-hub-toggle], [data-hub-close], [data-hub-clear], #hub-pop a[href^="#"]');
  if (!t) return;
  if (t.matches('[data-hub-toggle]')) { if (S.hubOpen) hubClose(); else hubOpen(); return; }
  if (t.matches('[data-hub-close]')) { hubClose(); return; }
  if (t.matches('[data-hub-clear]')) {
    hubNow().finished.forEach((j) => S.jobsSeen.add(j.id));
    S.jobs = S.jobs.filter((j) => j.status === 'running' || j.status === 'error' || (j.kind === 'auto' && j.result && HUB_AUTO_WAIT[j.result.status]));
    S.notes = [];
    renderHub();
    const title = $('#hub-title');
    if (title) title.focus({ preventScroll: true });
    return;
  }
  hubClose(false);  // 창 안 링크: 그 화면으로 가면 화면 이동이 제목으로 포커스를 옮긴다
});
// 창 밖을 누르면 닫는다 (버튼은 위 click 이 여닫는다)
document.addEventListener('mousedown', (e) => {
  if (!S.hubOpen || !e.target.closest) return;
  if (e.target.closest('#hub-pop, #hub-btn, #palette')) return;
  hubClose(false);
});
// Esc: 열린 창을 먼저 닫는다. 명령 팔레트 · 작업 중 상자가 떠 있으면 그쪽이 Esc 를 받는다
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || !S.hubOpen || e.isComposing) return;
  if ($('#palette') || ($('#busy') && !$('#busy').hidden)) return;
  e.preventDefault();
  e.stopPropagation();
  hubClose();
}, true);
// 접힌 '끝난 작업 · 지난 알림' 칸의 펼침을 다시 그려도 남긴다 (toggle 은 거품이 일지 않아 잡기 단계에서 듣는다)
document.addEventListener('toggle', (e) => { if (e.target && e.target.id === 'hub-more') S.hubMore = e.target.open; }, true);
window.addEventListener('hashchange', () => hubClose(false));
window.addEventListener('resize', () => placeHub());
let hubPlaceQueued = false;
window.addEventListener('scroll', () => {
  if (hubPlaceQueued) return;
  hubPlaceQueued = true;
  requestAnimationFrame(() => { hubPlaceQueued = false; placeHub(); });
}, { passive: true });

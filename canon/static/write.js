/* 4단계 집필 화면과 작업지시서(API 없이). app.js 의 S, actions, api, render, input, header 를 그대로 쓴다. */
'use strict';

// ----- 4. 집필 -----

function epNav(page, n) {
  const nums = P().episodes.map((e) => e.plot.number);
  const prev = nums.filter((x) => x < n).pop();
  const next = nums.find((x) => x > n);
  const arrow = (to, label, d) => to ? `<a class="btn icon-btn" href="${base()}/${page}/${to}" aria-label="${label}"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="${d}"></path></svg></a>` : '<span class="btn icon-btn" aria-hidden="true" style="visibility:hidden"></span>';  // 첫 화 · 끝 화는 자리만 남긴다
  return `<nav class="row" aria-label="회차 이동" style="gap:4px">${arrow(prev, '이전 화', 'M10 3 5 8l5 5')}${arrow(next, '다음 화', 'm6 3 5 5-5 5')}</nav>`;
}

function noEpisode() {
  return `<div class="card empty"><p>아직 화별 플롯이 없어요.</p><a class="btn primary" href="${base()}/arc">${stepLabel('arc')} 만들기</a></div>`;
}

/** n화보다 앞인데 상태 반영이 끝나지 않은 화. 있으면 n화 본문을 저장하거나 반영할 수 없다 (서버 pipeline.require_previous). */
const blockedBefore = (n) => P().episodes.filter((x) => x.plot.number < n && x.status !== 'finalized').map((x) => x.plot.number);

function orderNote(blocked) {
  if (!blocked.length) return '';
  const first = ep(blocked[0]);
  return `<div class="note warn">이전 화(${rangeText(blocked)}화)의 상태 반영이 끝나야 쓸 수 있어요. 인물 상태가 꼬이지 않게 하는 규칙이에요. <a href="${base()}/${first.status === 'written' ? 'review' : 'write'}/${blocked[0]}">${blocked[0]}화 ${first.status === 'written' ? '상태 승인으로' : '집필로'}</a></div>`;
}

/** 반영이 끝난 화의 머리 primary: 다음 할 일 (nextStep). 지금 보는 화면으로 가는 일이면 두지 않는다 */
function nextStepBtn() {
  const [label, href] = nextStep();
  return href === `${base()}/${S.route.slice(2).map(enc).join('/')}` ? '' : `<a class="btn primary" href="${href}">${esc(label)}</a>`;
}

// 이번 화 플롯 띠 (본문 칸 머리). 본문이 있는 화는 마지막으로 고른 펼침을 브라우저에 기억하고, 본문이 없는 화는 펼쳐서 시작한다
S.plotOpen = {};     // '작품:화' → 이 화에서 고른 펼침
S.plotMore = false;  // 펼친 띠의 '더 보기'
const plotPref = () => { try { return localStorage.getItem('canon.plotOpen') === '1'; } catch { return false; } };
const hasBody = (n) => !!(ep(n).text || (editableEp(ep(n)) && S.textDraft[n] !== undefined));
function plotOpenOf(n) {
  const k = `${S.name}:${n}`;
  return k in S.plotOpen ? S.plotOpen[k] : hasBody(n) ? plotPref() : true;
}

const CARET = '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="m5 3 4 4-4 4"></path></svg>';

/** 이 화 사건 가운데 작가가 다 썼다고 체크한 것 (Episode.events_done). 사건 글을 고쳤으면 그 체크는 빠진다 */
function doneEvents(e) {
  const done = new Set(e.events_done || []);
  return e.plot.events.map((x) => done.has(x));
}

/** 체크를 막는 까닭. 플롯 초안 화, AI 작업 · 자동 집필이 맡은 화 (서버 set_events_done 과 같은 조건) */
function eventsLock(n) {
  const e = ep(n);
  if (e.status === 'draft') return '플롯을 확정한 뒤에 체크할 수 있어요';
  if (autoOn() || S.jobs.some((j) => j.status === 'running' && j.project === S.name && (j.ep === n || (j.pending || []).includes(n)))) return 'AI 작업이 끝난 뒤에 체크할 수 있어요';
  return '';
}

const FLAG = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M3.5 14V2.5M3.5 3h8l-2 2.75 2 2.75h-8"></path></svg>';

/** 접힌 한 줄: 엔딩 훅(없으면 줄거리) · 사건 진행(체크한 수 / 사건 수, 좁은 화면은 숨김) · 시점이 바뀐 화면 '시점 바뀜'.
    펼치면 위 오른쪽에 '더 보기' · 플롯 페이지 링크, 승인된 요약(반영이 끝난 화), 왼쪽 진행 줄(사건 체크 → 끝에 엔딩 훅 도착점),
    오른쪽 이름 · 값 표(등장 인물 · 서술 시점 · 작품 속 시간), '더 보기'에 구간 목표 · 줄거리 · 감정 변화 · 여는 장면 · 독자 질문.
    펼친 칸(.wp-body)은 머리(.w-top) 밖에 둔다: 좁은 화면은 머리만 붙여 두고 펼친 칸은 본문과 함께 올라간다 (app.css) */
function plotStrip(n, act) {
  const e = ep(n);
  const p = e.plot;
  const open = plotOpenOf(n);
  const pov = povText(n);
  const moved = !!pov && n > 1 && pov !== povText(n - 1);
  const movedChip = moved ? '<span class="chip ai">시점 바뀜</span>' : '';
  const done = doneEvents(e);
  const k = done.filter(Boolean).length;
  const lead = p.ending_hook ? `<b>엔딩 훅</b> ${esc(p.ending_hook)}` : esc(p.summary || '');
  const row = `<div class="wp-row"><button type="button" class="wp-toggle" data-action="togglePlot" data-arg="${n}" aria-expanded="${open}" aria-controls="wp-body">
      <span class="wp-caret">${CARET}</span><span class="wp-label">이번 화 플롯</span><span class="wp-lead">${lead}</span>
      <span class="wp-meta">${p.events.length ? `<span class="chip wp-count" aria-label="사건 ${p.events.length}개 중 ${k}개 씀">사건 ${k}/${p.events.length}</span>` : ''}${movedChip}</span></button></div>`;
  if (!open) return { row, body: '' };
  const f = (label, v) => (v ? `<div class="field"><span class="small">${label}</span><div>${v}</div></div>` : '');
  const lock = eventsLock(n);
  const now = done.indexOf(false);  // 지금 쓸 사건: 체크하지 않은 첫 사건
  const steps = p.events.map((x, i) => {
    const cls = done[i] ? 'done' : i === now ? 'now' : 'todo';
    return `<li class="wp-step ${cls}"><label class="wp-check"${lock ? ` title="${lock}"` : ''}><input type="checkbox" id="ev-${n}-${i}" data-ev="${n}:${i}"${done[i] ? ' checked' : ''}${lock ? ' disabled' : ''}>
      <span class="wp-num">${i + 1}.</span><span class="wp-text">${esc(x)}</span>${i === now ? '<span class="wp-now">지금</span>' : ''}</label></li>`;
  }).join('');
  const goal = p.ending_hook ? `<li class="wp-step goal"><span class="wp-flag">${FLAG}</span><span class="wp-text"><span class="wp-goal-label">엔딩 훅</span> ${esc(p.ending_hook)}</span>${p.events.length && now < 0 ? '<span class="chip finalized">도착</span>' : ''}</li>` : '';
  const dl = [
    ['등장 인물', esc(p.characters.map(charName).join(', '))],
    ['서술 시점', pov ? `${esc(pov)} ${movedChip}` : ''],
    ['작품 속 시간', tlLines(n)],
  ].filter(([, v]) => v).map(([t, v]) => `<dt>${t}</dt><dd>${v}</dd>`).join('');
  const body = `<div class="wp-body" id="wp-body">
      <div class="wp-acts"><button type="button" class="btn small" data-action="togglePlotMore" aria-expanded="${S.plotMore}" aria-controls="wp-more">${S.plotMore ? '접기' : '더 보기'}</button>
        <a href="${base()}/arc/${n}" data-action="gotoPlot" data-arg="${n}">플롯 페이지에서 고치기</a></div>
      ${e.summary ? `<div class="field wp-wide"><span class="small">승인된 요약</span><div class="wp-summary">${esc(e.summary)}</div></div>` : ''}
      <div class="field"><span class="small">사건</span>${p.events.length || goal ? `<ol class="wp-steps">${steps}${goal}</ol>` : '<div class="small">아직 없어요</div>'}</div>
      ${dl ? `<dl class="wp-dl">${dl}</dl>` : '<span></span>'}
      ${S.plotMore ? `<div class="wp-more" id="wp-more">
        ${f('구간 목표', act ? esc(act.goal || '') : '')}${f('줄거리', esc(p.summary || ''))}${f('감정 변화', esc(p.emotional_shift || ''))}
        ${f('여는 장면', esc(p.opening || ''))}${f('독자가 들고 갈 질문', esc(p.reader_question || ''))}</div>` : ''}
    </div>`;
  return { row, body };
}

// 사건 체크: 누르자마자 저장한다 (저장 띠와 섞지 않는다). 서버가 돌려준 체크만 이 화에 합친다.
// 화면 전체를 받은 작품으로 바꾸면 저장하지 않은 다른 편집이 사라진다. 실패하면 되돌리고 알린다
document.addEventListener('change', async (ev) => {
  const key = ev.target.dataset && ev.target.dataset.ev;
  if (!key) return;
  const [n, i] = key.split(':').map(Number);
  const e = ep(n);
  const before = e.events_done || [];
  const done = doneEvents(e);
  done[i] = ev.target.checked;
  e.events_done = e.plot.events.filter((_, k) => done[k]);
  render();
  try {
    e.events_done = await api('PUT', `/projects/${enc(S.name)}/episodes/${n}/events-done`, { done: e.events_done });
  } catch (err) {
    e.events_done = before;
    toast(err.message, true);
  }
  render();
});

let wTopObs = null;
/** render() 직후에 부른다. 붙여 둔 머리(.w-stick, 좁은 화면은 .w-top) 높이를 --wtop 으로 넘겨, 머리가 위에 붙었을 때
    본문 칸이 그 아래 남은 화면을 채우게 한다 (app.css). 본문 칸은 그 안에서 굴러서, 펼친 플롯이 본문을 덮지 않는다 */
function syncWriteTop() {
  if (wTopObs) { wTopObs.disconnect(); wTopObs = null; }
  const stick = document.querySelector('#app .w-stick');
  if (!stick) return;
  const card = stick.closest('.w-body');
  const measure = () => {
    const el = getComputedStyle(stick).display === 'contents' ? stick.querySelector('.w-top') : stick;
    card.style.setProperty('--wtop', `${Math.round(el.getBoundingClientRect().height)}px`);
  };
  measure();
  if (window.ResizeObserver) {
    wTopObs = new ResizeObserver(measure);
    wTopObs.observe(stick.querySelector('.w-top'));
    if (stick.querySelector('.wp-body')) wTopObs.observe(stick.querySelector('.wp-body'));
  }
}

/** AI에게 보내는 컨텍스트 목록. 본문이 없는 화는 쓰기 버튼 아래에, 본문이 생긴 뒤에는 ⋯ 메뉴의 대화상자(ctxDialogHtml)에 보인다 */
function ctxList() {
  return `<ol class="panel-list">${S.context.map((c) => `<li><span>${esc(c.title)}</span><span class="small">${c.chars.toLocaleString()}자</span></li>`).join('')}</ol>
    <div class="small">이전 본문 전체 대신 이 데이터만 매번 같은 순서로 넣어요.</div>`;
}
const ctxTotal = () => `${S.context.length}개 블록 · 합계 ${S.context.reduce((s, c) => s + c.chars, 0).toLocaleString()}자`;
const promptBtn = (n) => `<button type="button" class="btn small" data-action="togglePrompt" data-arg="${n}">${S.promptText ? '프롬프트 닫기' : '프롬프트 원문 보기'}</button>${S.promptText ? `<pre class="brief mono" style="max-height:420px">${esc(S.promptText)}</pre>` : ''}`;

function ctxDialogHtml(n) {
  return `<div class="dlg-body">
    <div class="between"><strong id="w-ctx-title">AI에게 보내는 컨텍스트</strong><button type="button" class="btn small" data-action="closeDialog" data-arg="w-ctx">닫기</button></div>
    ${S.context ? `<div class="small">${ctxTotal()}</div>${ctxList()}<div>${promptBtn(n)}</div>` : '<div class="small">플롯을 확정하면 보여요.</div>'}
  </div>`;
}

/** 머리 ⋯ 메뉴: 생성 방식 · 컨텍스트 대화상자(둘 다 본문이 생긴 뒤. 그전에는 쓰기 버튼 아래에 있다) · 이 화 지우기. 넣을 것이 없으면 빈 글 */
function writeMenu(n, starting, seg) {
  const e = ep(n);
  const parts = [];
  if (seg && !starting) parts.push(`<div class="pop-sec"><span class="pop-legend">생성 방식</span>${seg}</div>`);
  if (S.context && e.status !== 'draft' && !starting) parts.push(`<button type="button" class="pop-item" data-action="openCtx" data-arg="${n}" aria-haspopup="dialog">컨텍스트 · 프롬프트 원문 보기<span class="small">${S.context.length}개 블록</span></button>`);
  const del = deleteBlock(e);
  if (del) parts.push(`<div class="pop-sec pop-danger">${del}</div>`);
  if (!parts.length) return '';
  const dots = '<svg width="18" height="18" viewBox="0 0 18 18" fill="currentColor" aria-hidden="true"><circle cx="4" cy="9" r="1.6"></circle><circle cx="9" cy="9" r="1.6"></circle><circle cx="14" cy="9" r="1.6"></circle></svg>';
  return menuBtn('write', dots, () => parts.join('<div class="pop-sep" role="separator"></div>'), { cls: 'btn icon-btn', aria: `${n}화 더보기` });
}

function viewWrite(n) {
  const e = ep(n);
  if (!e) return header('4단계', '집필', '') + noEpisode();
  const act = actOf(n);
  const blocked = blockedBefore(n);
  const editable = editableEp(e);  // 반영이 끝난 화도 고친다 (restate.js 가 반영 뒤 고침을 알린다)
  // 고칠 수 없는 화(플롯 초안)는 저장된 본문을 보인다. 그 화에 남은 초안이 있으면 따로 꺼내 보인다
  const draft = editable ? S.textDraft[n] : undefined;
  const orphan = !editable && textUnsaved(n);
  const text = draft ?? e.text;
  const isApi = S.mode === 'api';
  const writing = !!jobFor('write', n);
  const locked = writing && !e.text;  // AI가 본문을 처음 쓰는 중: 끝나면 칸이 AI 본문으로 바뀌므로 그동안 쓴 글은 남지 않는다

  // 생성 방식 토글은 설정의 본문 단계 백엔드 이름을 보인다 (설정을 아직 받지 않았으면 이름 없이)
  const wst = ((S.config || {}).stages || {}).write;
  const wname = wst ? ({ gemini: 'Gemini', local: '로컬', mock: 'mock' }[wst.provider] || wst.provider) : '';
  const seg = e.status !== 'finalized' ? `<div class="seg" role="group" aria-label="생성 방식"><button type="button" aria-pressed="${isApi}" data-action="setMode" data-arg="api" title="${wst ? `본문 모델 ${esc(wst.model || '')} · 설정에서 바꿔요` : '설정에서 바꿔요'}">AI로 쓰기${wname ? ` · ${esc(wname)}` : ''}</button><button type="button" aria-pressed="${!isApi}" data-action="setMode" data-arg="brief">채팅 앱 작업지시서</button></div>` : '';
  const starting = e.status !== 'draft' && !e.text && draft === undefined;  // 본문이 없는 화: 쓰기 버튼 아래에 생성 방식 · 컨텍스트

  let center;
  if (e.status === 'draft') {
    center = `<div class="empty"><p>${n}화 플롯이 아직 초안이에요. 확정해야 쓸 수 있어요.</p><a class="btn primary" href="${base()}/arc/${n}" data-action="gotoPlot" data-arg="${n}">${n}화 플롯 확정하러 가기</a></div>`;
  } else if (starting) {
    center = `<div class="empty">
      ${autoLockNote() || orderNote(blocked)}
      ${isApi ? `<p>확정된 플롯과 지금까지의 데이터로 ${n}화를 써요.</p>` : '<p>작업지시서를 채팅 앱에 붙여 넣고, 받은 본문을 가져오세요.</p>'}
      <div class="row" style="justify-content:center">
        ${isApi ? ((b) => `<button class="btn primary" data-action="writeEp" data-arg="${n}"${blocked.length || autoOn() ? ' disabled' : b.attr}>${b.label}</button>`)(jobBtn('write', n, `${n}화 본문 생성`)) : `<a class="btn primary" href="${base()}/brief/${n}">작업지시서 열기</a>`}
        <button class="btn" data-action="startManual" data-arg="${n}"${writing || blocked.length || autoOn() ? ' disabled' : ''}>직접 쓰기</button>
      </div>
      ${isApi && jobFor('write', n) ? '<div class="small">다른 화면으로 옮겨 가도 계속 써요. 끝나면 알려 드려요.</div>' : ''}
      <div class="w-start">
        ${seg ? `<div class="field"><span class="small">생성 방식</span>${seg}</div>` : ''}
        ${S.context ? `<details data-ctx-toggle${S.ctxOpen ? ' open' : ''}><summary>AI에게 보내는 컨텍스트 · ${ctxTotal()}</summary>${ctxList()}<div style="margin-top:8px">${promptBtn(n)}</div></details>` : ''}
      </div>
    </div>`;
  } else {
    center = `<div class="prose">${editable
      ? (locked ? `<div class="note info" id="draft-lock" style="margin:12px 16px 0">${n}화 본문을 만드는 중이에요. 끝나면 이 칸이 AI 본문으로 바뀌니 그때 고치세요.</div>` : '') + draftBox(n, text)
      : `<div class="read" data-read="${n}">${readHtml(n, text)}</div>`}</div>`;
  }

  // 쓴 화의 검수가 끝나지 않았으면 '검수로'가 지금 할 일이다 (검수 화면 check.js). 끝났으면 '상태 승인으로'를 primary 로 올린다
  const cs = checkState(e);
  const toCheck = e.status === 'written' && !cs.done && !autoOn();
  // 머리 버튼: 보조 버튼들 · ⋯ 메뉴 · primary 하나 (디자인 시스템: primary 는 머리 줄 오른쪽 끝)
  const primary = toCheck ? `<a class="btn primary" href="${base()}/check/${n}">검수로</a>`
    : e.status === 'written' ? `<a class="btn primary" href="${base()}/review/${n}">상태 승인으로</a>`
      : e.status === 'finalized' ? nextStepBtn() : '';
  const right = `${e.text && editable ? chatButton(`text:${n}`) : ''}
    ${e.text && editable && (isApi || e.status === 'finalized') ? `${((b) => `<button class="btn${S.rwOpen === n ? ' on' : ''}" data-action="rwOpen" data-arg="${n}" aria-expanded="${S.rwOpen === n}"${b.attr}>${b.label}</button>`)(jobBtn('write', n, '다시 생성'))}` : ''}
    ${editable && !isApi && e.status !== 'finalized' ? `<a class="btn" href="${base()}/brief/${n}">작업지시서</a>` : ''}
    ${toCheck ? `<a class="btn" href="${base()}/review/${n}">상태 승인으로</a>` : ''}
    ${writeMenu(n, starting, seg)}
    ${primary}`;

  const strip = plotStrip(n, act);
  const edits = (e.edits || []).length;
  const goal = Number(P().meta.words_per_episode).toLocaleString();

  return `<header class="page-head"><div class="row" style="gap:12px">${epNav('write', n)}<div class="lead" style="gap:2px"><div class="eyebrow">${act ? act.name + ' 구간 · ' : ''}${n} / ${P().meta.target_episodes}화</div><h1 style="font-size:1.5rem">${n}화 ${esc(e.plot.title)}</h1></div>${povBadge(n)}<span class="chip ${e.status}">${STATUS[e.status]}</span>${e.auto ? '<span class="chip ai">자동 반영</span>' : ''}${cs.open ? `<span class="chip warn">열린 지적 ${cs.open}곳</span>` : ''}</div><div class="row">${right}</div></header>
    ${e.auto ? `<div class="note info">이 화는 자동 집필이 검토 없이 반영했어요. 읽어 보고 문제가 있으면 <a href="${base()}/auto">자동 집필</a>에서 이 화부터 되돌릴 수 있어요.</div>` : ''}
    ${rebuildNote(n)}
    ${e.text ? restateNote(n) : ''}
    ${orphan ? `<div class="note warn">저장하지 않은 ${n}화 초고가 남아 있어요. 이 화는 상태 반영이 끝나 본문으로 저장할 수 없어서, 아래에는 반영된 본문을 보여요.
      <details><summary>남은 초고 보기 (${S.textDraft[n].length.toLocaleString()}자)</summary><textarea readonly id="orphan-${n}" aria-label="${n}화 남은 초고" style="width:100%;min-height:160px;margin-top:6px">${esc(S.textDraft[n])}</textarea></details>
      <div class="row" style="margin-top:6px"><button class="btn small" data-action="copyOrphan" data-arg="${n}">초고 복사</button><button class="btn small danger" data-action="dropOrphan" data-arg="${n}">초고 버리기</button></div></div>` : ''}
    ${editable && autoOn() ? `<div class="note warn">자동 집필이 도는 동안은 본문을 저장할 수 없어요. 쓰던 글은 이 화면에 남아 있어요. 저장하려면 <a href="${base()}/auto">자동 집필</a>을 일시정지하세요. 어색한 곳은 지금도 글을 골라 '나중에 고치기'로 담아 둘 수 있어요.</div>` : ''}
    ${e.text && editable ? candidateCard(n) : ''}
    <section class="card w-body" aria-label="본문">
      <div class="w-stick">
        <div class="w-top">
          <div class="w-bar">
            ${e.status === 'draft' ? '' : `<span class="w-count"><strong id="char-count" style="color:var(--text)">${(text || '').length.toLocaleString()}</strong><span class="lbl-l"> / ${goal}자</span><span class="lbl-s">자</span></span>`}
            ${/* 저장하지 않은 본문이 있으면 저장 띠(app.js renderSavebar)가 이 칸에 들어온다. 떠 있는 띠가 본문 끝 · 대화 입력칸을 가리지 않게 한다 */ ''}
            ${editable && (e.text || draft !== undefined) ? '<div class="savebar-slot"></div>' : '<span class="w-fill"></span>'}
            ${e.status === 'draft' ? '' : `${styleMenu(n)}
            ${editable ? tofixBtn(n) : ''}
            ${edits ? `<button type="button" class="btn small" data-action="openEdits" title="수정 기록을 펼쳐요" aria-label="수정 기록 ${edits}개"><span class="lbl-l">수정 기록</span><span class="lbl-s">기록</span> ${edits}</button>` : ''}
            ${text ? copySplit(n) : ''}`}
            <p class="small w-hint">${e.status === 'draft' ? '플롯을 확정하면 본문을 쓸 수 있어요' : e.text ? '고칠 부분을 드래그하면 직접 고치거나 AI에게 맡기거나 나중에 고칠 곳으로 담을 수 있어요' : '본문을 직접 고친 뒤 저장할 수 있어요'}</p>
          </div>
          ${strip.row}
        </div>
        ${strip.body}
      </div>
      ${e.text ? passageNotes(n) ? `<div style="padding:12px 16px 0;display:flex;flex-direction:column;gap:8px">${passageNotes(n)}</div>` : '' : ''}
      ${center}
    </section>
    ${editHistory(e)}
    ${versionsPanel(e)}
    ${e.text ? illustPanel(n) : ''}
    ${openingPanel(n)}
    ${e.text && editable ? (S.rwOpen === n ? rewritePanel(n) : chatPanel(`text:${n}`)) : ''}`;
}

// ----- 6. 작업지시서 -----

// 화마다 고른 지시서 탭 ('작품:화' → 'episode' | 'check' | 'state'). 고른 적 없는 화는 상태로 정한다:
// 본문이 있고 검수가 끝나지 않았으면 검수 지시서, 끝났으면 상태 승인 지시서
const BRIEF_TABS = {};
const briefTabFor = (n) => BRIEF_TABS[`${S.name}:${n}`] || (ep(n).status === 'written' ? (checkState(ep(n)).done ? 'state' : 'check') : 'episode');
const BRIEF_TAB_NAMES = { episode: '1 본문 작성 지시서', check: '2 검수 지시서', state: '3 상태 승인 지시서' };
let briefImportError = null;  // 받은 JSON 가져오기에서 서버가 거절한 이유 { key: '작품:화', msg }

/** 붙여 넣은 본문 글자 수와 목표 분량. 목표의 70%보다 짧으면 채팅 앱 답이 잘렸는지 보라고 한다. */
function importCount(v) {
  const len = v.trim().length;
  const goal = Number(P().meta.words_per_episode) || 0;
  const short = len && goal && len < goal * 0.7;
  return `<strong>${len.toLocaleString()}</strong> / ${goal.toLocaleString()}자${short ? ' <span class="chip written">목표보다 많이 짧아요. 본문이 잘렸는지 확인하세요</span>' : ''}`;
}

function viewBrief(n) {
  const e = ep(n);
  if (!e) return header('작품 도구', '채팅 앱 작업지시서', '') + noEpisode();
  const body = S.briefTab === 'episode';
  const check = S.briefTab === 'check';
  const stateBlocked = !body && !e.text;
  // 앞 화 반영이 끝나지 않았으면 받은 본문 저장(처음 쓰는 화)과 변경안 반영을 서버가 막는다. 붙여 넣은 글은 칸에 남는다
  const order = check ? [] : (body ? e.status === 'confirmed' : e.status === 'written') ? blockedBefore(n) : [];  // 검수는 순서를 따지지 않는다
  return `<header class="page-head"><div class="row" style="gap:12px">${epNav('brief', n)}<div class="lead" style="gap:2px"><div class="eyebrow">${n}화 ${esc(e.plot.title)} · API 없이 쓰기</div><h1 style="font-size:1.5rem">채팅 앱 작업지시서</h1></div><span class="chip ${e.status}">${STATUS[e.status]}</span></div></header>
    <p class="desc">Claude, Gemini, ChatGPT 구독 앱에 붙여 넣을 지시서예요. API 생성과 똑같은 컨텍스트를 써요.</p>
    <div class="tabs" role="tablist" aria-label="지시서 종류">
      ${Object.entries(BRIEF_TAB_NAMES).map(([k, l]) => `<button type="button" role="tab" aria-selected="${S.briefTab === k}" aria-controls="brief-panel" data-action="setBriefTab" data-arg="${k}">${l}</button>`).join('')}
    </div>
    <div class="cols" role="tabpanel" id="brief-panel" aria-label="${BRIEF_TAB_NAMES[S.briefTab]}">
      <section class="card" style="flex:1.3 1 480px;min-width:0">
        <div class="between"><h2><span class="small" style="font-weight:400">① </span>복사해서 채팅 앱에 붙여 넣기</h2>
          <div class="row"><button class="btn small" data-action="downloadBrief" data-arg="${n}"${stateBlocked ? ' disabled' : ''}>.md 내려받기</button><button class="btn small dark" data-action="copyBrief"${stateBlocked ? ' disabled' : ''}>복사</button></div></div>
        ${e.status === 'draft' && body ? '<div class="note warn">플롯이 아직 초안이에요. 확정 전 내용으로 지시서가 만들어져요.</div>' : ''}
        ${stateBlocked
          ? `<div class="note plain">${n}화 본문이 아직 없어 ${check ? '검수' : '상태 승인'} 지시서를 만들 수 없어요. 본문을 먼저 저장하세요. <button class="btn small" data-action="setBriefTab" data-arg="episode">본문 작성 지시서로</button></div>`
          : `<pre class="brief mono">${esc(S.briefText ?? '불러오는 중…')}</pre>
        ${S.briefText ? `<div class="small">${S.briefText.length.toLocaleString()}자</div>` : ''}`}
      </section>
      <section class="card" style="flex:1 1 380px;min-width:0">
        ${body ? `<h2><span class="small" style="font-weight:400">② </span>받은 본문 가져오기</h2>
          <label for="imp-body" class="small">채팅 앱이 쓴 본문을 그대로 붙여 넣으세요.</label>
          <textarea id="imp-body" rows="12" data-brief="${n}:episode" style="font-family:var(--serif);line-height:1.8"${e.status === 'draft' || e.status === 'finalized' ? ' disabled' : ''}>${esc(S.briefDraft[`${S.name}:${n}:episode`] || '')}</textarea>
          <div class="small" id="imp-count">${importCount(S.briefDraft[`${S.name}:${n}:episode`] || '')}</div>
          ${e.status === 'draft' ? '<div class="small">플롯을 확정해야 본문을 저장할 수 있어요.</div>' : ''}${e.status === 'finalized' ? '<div class="small">이미 끝난 화예요.</div>' : ''}
          ${orderNote(order)}
          <div style="align-self:flex-end"><button class="btn primary" data-action="importText" data-arg="${n}"${e.status === 'draft' || e.status === 'finalized' || order.length ? ' disabled' : ''}>${n}화 본문으로 저장</button></div>`
        : check ? `<h2><span class="small" style="font-weight:400">② </span>받은 검수 JSON 가져오기</h2>
          <label for="imp-check" class="small">채팅 앱의 JSON 답변을 붙여 넣으세요. 코드 블록 표시는 자동으로 지워요. 가져오면 검수 회차 하나로 합쳐요.</label>
          <textarea id="imp-check" rows="12" data-brief="${n}:check" class="mono"${e.text ? '' : ' disabled'}>${esc(S.briefDraft[`${S.name}:${n}:check`] || '')}</textarea>
          ${briefImportError && briefImportError.key === `${S.name}:${n}` ? `<div class="note err" role="alert">${esc(briefImportError.msg)}</div>` : ''}
          <div style="align-self:flex-end"><button class="btn primary" data-action="importCheck" data-arg="${n}"${e.text ? '' : ' disabled'}>가져오고 검수로</button></div>`
        : `<h2><span class="small" style="font-weight:400">② </span>받은 JSON 가져오기</h2>
          <label for="imp-json" class="small">채팅 앱의 JSON 답변을 붙여 넣으세요. 코드 블록 표시는 자동으로 지워요.</label>
          <textarea id="imp-json" rows="12" data-brief="${n}:state" class="mono"${e.status !== 'written' ? ' disabled' : ''}>${esc(S.briefDraft[`${S.name}:${n}:state`] || '')}</textarea>
          ${e.status !== 'written' ? '<div class="small">본문이 작성된 화에서만 쓸 수 있어요.</div>' : ''}
          ${briefImportError && briefImportError.key === `${S.name}:${n}` ? `<div class="note err" role="alert">${esc(briefImportError.msg)}</div>` : ''}
          ${orderNote(order)}
          <div style="align-self:flex-end"><button class="btn primary" data-action="importJson" data-arg="${n}"${e.status !== 'written' || order.length ? ' disabled' : ''}>확인하고 변경안 검토로</button></div>`}
        <div style="padding-top:12px;border-top:1px solid var(--line);display:flex;flex-direction:column;gap:8px">
          <strong style="font-size:0.8125rem">순서</strong>
          <ol style="padding-left:20px;display:flex;flex-direction:column;gap:4px;font-size:0.8125rem;line-height:1.55;color:var(--text-2)">
            <li>본문 작성 지시서 → 받은 본문 저장</li><li>검수 지시서 → 받은 JSON 가져오기 → 검수 화면에서 지적 처리</li><li>상태 승인 지시서 → 받은 JSON 가져오기</li><li>상태 승인 화면에서 반영</li></ol>
        </div>
      </section>
    </div>`;
}


/** 장편 검수 넓히기 켜기 · 끄기 (Settings.check_widen). 작품 설정이라 자동 집필 검수도 따른다.
    켜지면 `.btn.on` (디자인 시스템 Button). small 이 아니면 머리 줄의 다른 버튼과 같은 높이다 */
function widenToggle(small = true) {
  const on = !!P().settings.check_widen;
  return `<button type="button" class="btn${small ? ' small' : ''}${on ? ' on' : ''}" aria-pressed="${on}" data-action="toggleWiden" title="검수 뒤 이번 화 진술마다 옛 화를 더 찾아, 처음 검수에 넣지 못한 근거가 나온 진술만 다시 물어요. 검수 호출이 2번 늘어요">넓혀 찾기 ${on ? '켜짐' : '꺼짐'}</button>`;
}

Object.assign(actions, {
  async toggleWiden() {
    const on = !P().settings.check_widen;
    P().settings.check_widen = on;
    render();
    try {
      S.project = await api('PUT', `/projects/${enc(S.name)}/check-widen`, { on });
    } catch (e) {
      toast(e.message, true);
    }
  },
  // 집필
  setMode(m) {
    S.mode = m;
    localStorage.setItem('canon.mode', m);
    render();
  },
  async writeEp(n) {
    if (ep(n).text && !confirm(`${n}화 본문을 새로 생성할까요? 지금 본문은 사라져요.`)) return;
    await startJob('write', n);
  },
  async saveText(n) {
    await run('본문 저장 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/episodes/${n}/text`, { text: S.textDraft[n] ?? ep(n).text });
      delete S.textDraft[n];  // 만들어 둔 상태 변경안은 남기고, 본문이 바뀌었다고 알린다 (passageNotes)
      toast('본문을 저장했어요');
    });
  },
  startManual(n) {
    S.textDraft[n] = '';
    render();
  },
  gotoPlot(n) {
    return actions.openPlot(n);  // 화 플롯 페이지 (plot.js)
  },
  togglePlot(n) {
    const open = !plotOpenOf(n);
    S.plotOpen[`${S.name}:${n}`] = open;
    if (hasBody(n)) { try { localStorage.setItem('canon.plotOpen', open ? '1' : '0'); } catch { /* 이번 화면에서만 기억한다 */ } }
    render();
  },
  togglePlotMore() {
    S.plotMore = !S.plotMore;
    render();
  },
  openCtx(n) {
    showDialog('w-ctx', ctxDialogHtml(n), '[data-action="menuToggle"][data-arg="write"]');
  },
  async togglePrompt(n) {
    const dlg = () => { if (document.getElementById('w-ctx')?.open) showDialog('w-ctx', ctxDialogHtml(n)); };  // ⋯ 메뉴의 대화상자는 #app 밖이라 따로 채운다
    if (S.promptText) {
      S.promptText = null;
      dlg();
      return render();
    }
    await run('불러오는 중', async () => {
      const r = await api('GET', `/projects/${enc(S.name)}/episodes/${n}/prompt`);
      S.promptText = `[시스템]\n${r.system}\n\n[프롬프트]\n${r.prompt}`;
    });
    dlg();
  },

  // 작업지시서
  openStateBrief(n) {
    BRIEF_TABS[`${S.name}:${n}`] = 'state';
    location.hash = `${base()}/brief/${n}`;
  },
  setBriefTab(t) {
    BRIEF_TABS[`${S.name}:${S.route[3]}`] = t;
    S.briefTab = t;
    S.briefText = null;
    briefImportError = null;
    render();
  },
  async copyBrief() {
    try {
      await navigator.clipboard.writeText(S.briefText || '');
      toast('복사했어요. 채팅 앱에 붙여 넣으세요.');
    } catch {
      toast('복사하지 못했어요. 내용을 직접 선택해 복사하세요.', true);
    }
  },
  downloadBrief(n) {
    const blob = new Blob([S.briefText || ''], { type: 'text/markdown' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${S.name}-${String(n).padStart(2, '0')}-${S.briefTab}.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  },
  async importText(n) {
    const text = $('#imp-body').value.trim();
    if (!text) return toast('본문을 붙여 넣으세요', true);
    if (ep(n).text && !confirm(`${n}화의 지금 본문을 바꿀까요?`)) return;
    await run('가져오는 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/episodes/${n}/text`, { text });
      delete S.textDraft[n];
      delete S.deltas[n];
      delete S.briefDraft[`${S.name}:${n}:episode`];
      toast(`${n}화 본문으로 저장했어요`);
      location.hash = `${base()}/write/${n}`;
    });
  },
  async importCheck(n) {
    n = Number(n);
    const raw = $('#imp-check').value;
    if (!raw.trim()) return toast('JSON을 붙여 넣으세요', true);
    await run('가져오는 중', async () => {
      let pj;
      try {
        pj = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/check/import`, { raw });
      } catch (e) {
        if (e.status !== 400) throw e;
        briefImportError = { key: `${S.name}:${n}`, msg: e.message };
        return;
      }
      briefImportError = null;
      takeCheck(n, pj);
      delete S.briefDraft[`${S.name}:${n}:check`];
      const r = ep(n).rounds[ep(n).rounds.length - 1];
      toast(`${r.no}회차로 합쳤어요: 짚은 곳 ${r.found}개, 새 지적 ${r.added}개`);
      location.hash = `${base()}/check/${n}`;
    });
  },
  async importJson(n) {
    const raw = $('#imp-json').value;
    if (!raw.trim()) return toast('JSON을 붙여 넣으세요', true);
    if (S.deltas[n] && !confirm(`${n}화에 검토 중인 변경안이 있어요. 골라 둔 체크와 함께 가져온 JSON으로 바꿀까요?`)) return;
    await run('확인하는 중', async () => {
      let d;
      try {
        d = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/state/parse`, { raw });
      } catch (e) {
        if (e.status !== 400) throw e;
        briefImportError = { key: `${S.name}:${n}`, msg: e.message };  // 토스트는 사라지니 ② 칸 아래에 남긴다
        return;
      }
      briefImportError = null;
      setDelta(n, d, 'chat');
      delete S.briefDraft[`${S.name}:${n}:state`];
      location.hash = `${base()}/review/${n}`;
    });
  },
});

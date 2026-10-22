/* 인과율 화면. app.js 의 S, actions, api, render 와 chat.js 의 plotDiff 를 그대로 쓴다.
   작가가 요소, 특징, 설정, 사건을 언제든 더하고(작품 저장으로 바로 저장), 요소마다
   관련 화 지도(AI 없이, 서버 elements.links)와 영향 분석(백그라운드 작업 'impact')을 본다.
   영향 분석의 변경안은 고른 것만 반영한다. */
'use strict';

const EL_KINDS = ['세계 규칙', '장소', '물건', '세력', '인물 특징', '과거 사건', '예정 사건', '기타'];
const EL_KIND_HINT = {
  '세계 규칙': '마법은 해가 진 뒤에만 쓸 수 있다',
  '장소': '폐쇄된 등대의 지하 창고',
  '물건': '녹슨 등대 열쇠',
  '세력': '항구를 쥔 선주 조합',
  '인물 특징': '서윤은 왼손잡이고 피를 보면 손이 떨린다',
  '과거 사건': '10년 전 겨울, 등대지기가 실종됐다',
  '예정 사건': '12화에 마을에 태풍이 온다',
  '기타': '',
};
const FIX_CLASS = { '본문 수정': 'written', '플롯 수정': 'confirmed', '설명 추가': 'ai', '시점 변경': 'draft', '그대로 둠': 'draft' };

Object.assign(S, {
  causalSel: null,    // 고른 요소 id
  causalKind: '',     // 종류 거르기
  causalLinks: {},    // 요소 id → 관련 화 지도
  causalPicks: {},    // '요소:분석시각:ep:3' 같은 키 → 반영할지
});

async function causalLoad() {
  S.causalLinks = await api('GET', `/projects/${enc(S.name)}/elements/links`).catch(() => ({}));
}

function causalEl(id = S.causalSel) {
  return (P().elements || []).find((x) => x.id === id);
}

function causalIndex(id) {
  return (P().elements || []).findIndex((x) => x.id === id);
}

function newElementId() {
  const have = new Set(P().elements.map((x) => x.id));
  let n = P().elements.length + 1;
  while (have.has(`el-${String(n).padStart(2, '0')}`)) n++;
  return `el-${String(n).padStart(2, '0')}`;
}

function lastWritten() {
  return Math.max(0, ...P().episodes.filter((e) => e.text).map((e) => e.plot.number));
}

/** 분석한 뒤 요소를 고쳤는가. 서버 elements.basis 와 같은 모양으로 만들어 비교한다. */
function elBasis(el) {
  return JSON.stringify([el.kind, el.name, el.aliases, el.description, el.characters, el.since_ep, el.episodes, el.reveal_ep]);
}

function causalStale(el) {
  return !!(el.impact && el.impact.basis && el.impact.basis !== elBasis(el));
}

function timingText(el) {
  const parts = [el.since_ep > 0 ? `${el.since_ep}화부터` : '처음부터'];
  if (el.episodes.length) parts.push(`나올 화 ${el.episodes.join(', ')}`);
  if (el.reveal_ep) parts.push(`${el.reveal_ep}화 공개`);
  return parts.join(' · ');
}

function impactBadge(el) {
  const imp = el.impact;
  if (!imp) return el.added_after ? '<span class="chip written">분석 전</span>' : '';
  if (imp.outcome === 'applied') return '<span class="chip finalized">반영함</span>';
  if (imp.outcome === 'dismissed') return '<span class="chip">분석 봄</span>';
  const r = imp.report;
  const n = r.conflicts.length + r.episodes.length + r.patches.length;
  return n ? `<span class="chip written">영향 ${n}곳</span>` : '<span class="chip finalized">영향 없음</span>';
}

// ----- 목록 -----

function causalList() {
  const list = (P().elements || []).filter((x) => !S.causalKind || x.kind === S.causalKind);
  const kinds = [...new Set(P().elements.map((x) => x.kind))];
  const filter = kinds.length > 1 ? `<div class="row" style="gap:6px">${['', ...EL_KINDS.filter((k) => kinds.includes(k))].map((k) => `<button type="button" class="btn small${S.causalKind === k ? ' on' : ''}" data-action="causalFilter" data-arg="${esc(k)}" aria-pressed="${S.causalKind === k}">${k || '전부'}</button>`).join('')}</div>` : '';
  const items = list.map((x) => `<button type="button" class="el-item${x.id === S.causalSel ? ' sel' : ''}" data-action="causalSelect" data-arg="${esc(x.id)}">
      <span class="between"><span class="chip">${esc(x.kind)}</span>${impactBadge(x)}</span>
      <strong>${esc(x.name) || '이름 없음'}</strong>
      <span class="small">${esc(timingText(x))}${x.characters.length ? ' · ' + x.characters.map(charName).map(esc).join(', ') : ''}</span>
    </button>`).join('');
  return `<div class="el-list">${filter}${items || '<div class="small">이 종류의 요소가 없어요.</div>'}</div>`;
}

// ----- 편집 -----

function causalEditor(el) {
  const i = causalIndex(el.id);
  const b = `elements.${i}`;
  const chars = P().characters.map((c) => `<label class="row" style="font-size:13px;gap:6px"><input type="checkbox" data-el-char="${esc(c.id)}"${el.characters.includes(c.id) ? ' checked' : ''}>${esc(c.name || c.id)}</label>`).join('');
  const fromStart = el.since_ep <= 0;
  const ctx = [['auto', '관련 있을 때'], ['always', '항상'], ['off', '넣지 않음']];
  return `<div class="card" style="display:flex;flex-direction:column;gap:14px">
    <div class="between"><h2>요소</h2><button class="btn small danger" data-action="causalDelete">삭제</button></div>
    <div class="grid-2">
      <div class="field"><label for="el-kind">종류</label><select id="el-kind" data-el-kind>${EL_KINDS.map((k) => `<option${k === el.kind ? ' selected' : ''}>${k}</option>`).join('')}</select></div>
      ${input('이름', b + '.name', { placeholder: '본문과 플롯에서 찾을 이름' })}
    </div>
    ${input('설명', b + '.description', { rows: 3, autogrow: true, placeholder: EL_KIND_HINT[el.kind] || '', hint: '지켜야 할 내용을 구체적으로' })}
    ${input('다른 이름', b + '.aliases', { kind: 'list', rows: 2, hint: '본문에서 다르게 부르는 말. 두 글자 이상' })}
    <div class="field"><span class="label">관련 인물</span><div class="row">${chars || '<span class="small">인물이 아직 없어요.</span>'}</div></div>
    <div class="field"><span class="label">언제부터 사실인가요?</span>
      <div class="row"><div class="seg" role="group" aria-label="시점">
        <button type="button" aria-pressed="${fromStart}" data-action="causalSince" data-arg="start">처음부터 사실이었다</button>
        <button type="button" aria-pressed="${!fromStart}" data-action="causalSince" data-arg="from">어느 화부터 생긴다</button></div>
        ${fromStart ? '' : `<label class="row" style="gap:6px"><input type="number" id="el-since" min="1" style="width:90px" value="${el.since_ep}" data-bind="${b}.since_ep" data-kind="int">화부터</label>`}</div>
      <span class="small">${fromStart ? '이미 쓴 화도 이 설정과 맞아야 해서, 영향 분석이 본문까지 검사해요.' : `${el.since_ep}화 전 본문은 이 요소가 없던 때라 모순으로 보지 않아요.`}</span></div>
    <div class="grid-2">
      <div class="field"><label for="el-eps">나올 화 <span class="hint">일어나거나 꼭 나와야 하는 화. 쉼표로</span></label><input id="el-eps" type="text" value="${esc(el.episodes.join(', '))}" data-el-eps placeholder="예: 7, 12"></div>
      ${input('독자에게 드러나는 화', b + '.reveal_ep', { type: 'number', min: 0, hint: '0 이면 숨기지 않음. 그 전에는 암시만' })}
    </div>
    <div class="field"><span class="label">본문을 쓸 때 AI 에 넣기</span><div class="seg" role="group" aria-label="AI 에 넣기">${ctx.map(([k, l]) => `<button type="button" aria-pressed="${el.context === k}" data-action="causalContext" data-arg="${k}">${l}</button>`).join('')}</div>
      <span class="small">관련 있을 때: 그 화에 관련 인물이 나오거나, 플롯에 이름이 있거나, 나올 화일 때만 넣어요.</span></div>
  </div>`;
}

// ----- 관련 화 지도 -----

function causalStrip(el) {
  const total = Math.max(P().meta.target_episodes, ...P().episodes.map((e) => e.plot.number));
  const links = new Map((S.causalLinks[el.id] || []).map((l) => [l.episode, l]));
  const r = el.impact && el.impact.outcome !== 'dismissed' ? el.impact.report : null;
  const bad = new Set(r ? r.conflicts.filter((c) => c.episode).map((c) => c.episode) : []);
  const plot = new Set(r ? [...r.episodes.map((e) => e.number), ...r.patches.map((t) => t.episode)] : []);
  const cells = Array.from({ length: total }, (_, k) => {
    const n = k + 1;
    const e = ep(n);
    const l = links.get(n);
    const cls = bad.has(n) ? 'bad' : plot.has(n) ? 'plot' : l ? (l.where.length || l.planned ? 'rel' : 'rel weak') : '';
    const tag = bad.has(n) ? '모순' : plot.has(n) ? '고침' : l ? (l.where.length ? '언급' : l.planned ? '예정' : '인물') : '';
    const marks = (el.since_ep > 0 && n === el.since_ep ? ' since' : '') + (el.reveal_ep === n ? ' reveal' : '') + (e && e.text ? ' has-text' : '');
    const title = [`${n}화`, e ? STATUS[e.status] : '플롯 없음', l && l.terms.length ? `언급: ${l.terms.join(', ')}` : '', l && l.characters.length ? `인물: ${l.characters.map(charName).join(', ')}` : '',
      el.since_ep === n ? '이 화부터 생김' : '', el.reveal_ep === n ? '독자에게 드러남' : ''].filter(Boolean).join(' · ');
    const href = e ? (e.text ? `${base()}/write/${n}` : `${base()}/arc`) : `${base()}/arc`;
    return `<a class="cell ${cls}${marks}${el.since_ep > n ? ' before' : ''}" href="${href}" title="${esc(title)}" aria-label="${esc(title)}">${n}<i>${tag}</i></a>`;
  }).join('');
  const snippets = [...links.values()].filter((l) => l.snippet).slice(0, 6)
    .map((l) => `<li><strong>${l.episode}화 ${l.where.join('·')}</strong> <span class="small">${esc(l.snippet)}</span></li>`).join('');
  return `<div class="card" style="display:flex;flex-direction:column;gap:12px">
    <div class="between"><h2>관련 화 지도</h2><span class="small">이름, 다른 이름, 관련 인물로 찾았어요 (AI 없이)</span></div>
    <div class="strip-scroll"><div class="strip" style="grid-template-columns:repeat(${Math.min(total, 25)}, minmax(30px, 1fr))">${cells}</div></div>
    <div class="legend"><span><i style="background:var(--red-soft);border:1px solid var(--red)"></i>모순</span><span><i style="background:var(--amber-soft);border:1px solid var(--amber)"></i>고칠 화</span><span><i style="background:var(--accent-soft);border:1px solid var(--accent)"></i>언급 · 나올 화</span><span><i style="border:1px dashed var(--accent)"></i>관련 인물만 나옴</span><span><i style="border-bottom:3px solid var(--text-2)"></i>본문 있음</span>${el.since_ep > 0 ? '<span><i style="border-left:3px solid var(--accent)"></i>생기는 화</span>' : ''}${el.reveal_ep ? '<span><i style="outline:2px dashed var(--accent)"></i>드러나는 화</span>' : ''}</div>
    ${snippets ? `<ul class="panel-list">${snippets}</ul>` : ''}
  </div>`;
}

// ----- 영향 분석 -----

function pickId(el, part) {
  return `${el.id}:${el.impact.at}:${part}`;
}

function initCausalPicks(el) {
  const r = el.impact.report;
  const set = (k, v) => { if (S.causalPicks[k] === undefined) S.causalPicks[k] = v; };
  r.episodes.forEach((e) => { const cur = ep(e.number); set(pickId(el, 'ep:' + e.number), !cur || cur.status === 'draft'); });
  r.patches.forEach((t, i) => { const cur = ep(t.episode); set(pickId(el, 'patch:' + i), !!cur && cur.status !== 'finalized'); });
  r.new_facts.forEach((_, i) => set(pickId(el, 'fact:' + i), true));
}

function causalImpact(el) {
  const job = jobFor('impact');
  const btn = job ? `<button class="btn" disabled aria-busy="true">${esc(job.label)} 중…</button>`
    : `<button class="btn${el.impact ? '' : ' primary'}" data-action="causalAnalyze">${el.impact ? '다시 분석' : '영향 분석'}</button>`;
  const lw = lastWritten();
  const head = `<div class="between"><h2>영향 분석</h2>${btn}</div>`;
  if (!el.impact) {
    const why = lw ? `${lw}화까지 쓴 작품이에요. 이 요소가 이미 쓴 화, 확정한 플롯과 부딪치는지 AI 가 근거를 인용해 찾고 고칠 방법을 제안해요.`
      : '정해 둔 플롯이 이 요소와 맞는지, 어느 화에 심고 드러내면 좋을지 AI 가 제안해요.';
    return `<div class="card" style="display:flex;flex-direction:column;gap:12px">${head}<div class="note info">${why} 반영은 고른 것만 해요.</div></div>`;
  }
  const imp = el.impact;
  const r = imp.report;
  const open = !imp.outcome;
  if (open) initCausalPicks(el);
  const box = (part, disabled) => open ? `<input type="checkbox" data-causal-pick="${esc(pickId(el, part))}"${S.causalPicks[pickId(el, part)] && !disabled ? ' checked' : ''}${disabled ? ' disabled' : ''}>` : '';
  const stale = causalStale(el) ? '<div class="note warn">분석한 뒤 요소를 고쳤어요. 다시 분석하면 지금 내용으로 봅니다.</div>' : '';
  const conflicts = r.conflicts.map((c) => `<li class="conflict">
      <div class="row" style="gap:6px"><span class="chip">${c.target}${c.episode ? ` · ${c.episode}화` : ''}</span><span class="chip ${FIX_CLASS[c.fix] || ''}">${c.fix}</span></div>
      <blockquote>${esc(c.quote)}</blockquote><div>${esc(c.problem)}</div></li>`).join('');
  const plots = r.episodes.map((e) => {
    const cur = ep(e.number);
    const locked = cur && LOCKED_STATUS.includes(cur.status);
    const note = locked ? '<div class="note plain">본문이 생겨서 이제는 바꿀 수 없어요.</div>'
      : cur && cur.status === 'confirmed' && open ? '<div class="note warn">확정한 화예요. 반영하면 초안으로 돌아가 다시 확정해야 해요.</div>' : '';
    return `<div class="prop-part"><label class="prop-head">${box('ep:' + e.number, locked)}<strong>${e.number}화</strong> ${esc(e.title)}${cur ? ` <span class="chip ${cur.status}">${STATUS[cur.status]}</span>` : ''}</label>${note}<div class="diff">${plotDiff(e)}</div></div>`;
  }).join('');
  const patches = r.patches.map((t, i) => {
    const cur = ep(t.episode);
    const fin = cur && cur.status === 'finalized';
    return `<div class="prop-part"><label class="prop-head">${box('patch:' + i)}<strong>${t.episode}화 본문</strong>${cur ? ` <span class="chip ${cur.status}">${STATUS[cur.status]}</span>` : ''}</label>
      ${fin && open ? '<div class="note warn">상태 반영까지 끝난 화예요. 본문만 고치고 요약과 인물 상태는 그대로 둬요.</div>' : ''}
      <div class="diff"><div class="diff-row"><del>${esc(t.quote)}</del><ins>${esc(t.replacement)}</ins></div>${t.reason ? `<div class="small">${esc(t.reason)}</div>` : ''}</div></div>`;
  }).join('');
  const facts = r.new_facts.map((f, i) => `<div class="prop-part"><label class="prop-head">${box('fact:' + i)}<strong>확정 사실 더하기</strong></label><div class="diff"><div class="diff-row"><ins>${esc(f)}</ins></div></div></div>`).join('');
  const done = imp.outcome === 'applied' ? `<span class="chip finalized">반영함 · ${imp.applied.map(appliedLabel).join(', ')}</span>`
    : imp.outcome === 'dismissed' ? '<span class="chip">반영 안 함</span>' : '';
  const body = `${conflicts ? `<h3>어긋나는 곳 ${r.conflicts.length}</h3><ul class="conflicts">${conflicts}</ul>` : ''}
    ${plots ? `<h3>플롯 고치기</h3>${plots}` : ''}${patches ? `<h3>이미 쓴 본문 고치기</h3>${patches}` : ''}${facts ? `<h3>설명으로 덮기</h3>${facts}` : ''}`;
  const has = r.episodes.length || r.patches.length || r.new_facts.length;
  const actionsRow = open && has ? `<div class="row"><button class="btn primary" data-action="causalApply">고른 것 반영</button><button class="btn" data-action="causalDismiss">반영 안 함</button></div>` : '';
  const timingTip = open && r.conflicts.some((c) => c.fix === '시점 변경') ? '<div class="note info">시점 변경을 권한 곳이 있어요. 위의 \'언제부터\'를 늦추고 저장한 뒤 다시 분석하면 앞 본문은 모순이 아니게 돼요.</div>' : '';
  return `<div class="card" style="display:flex;flex-direction:column;gap:12px">${head}${stale}
    <div class="small">${fmtDate(imp.at)} 분석 ${done}</div>
    <div class="msg-text" style="white-space:pre-wrap">${esc(r.summary)}</div>${timingTip}
    ${open ? `${body}${actionsRow}` : `<details class="proposal done"><summary>분석 내용 다시 보기</summary>${body}</details>`}
  </div>`;
}

function appliedLabel(x) {
  const [k, v] = x.split(':');
  return { ep: `${v}화 플롯`, patch: `본문 수정 ${Number(v) + 1}`, fact: `사실 ${Number(v) + 1}` }[k] || x;
}

// ----- 화면 -----

function viewCausal() {
  const els = P().elements || [];
  if (S.causalSel && !causalEl()) S.causalSel = null;
  if (!S.causalSel && els.length) S.causalSel = els[0].id;
  const el = causalEl();
  const add = '<button class="btn primary" data-action="causalNew">+ 요소 더하기</button>';
  const desc = '요소, 특징, 설정, 사건을 언제든 더하세요. 더할 때마다 이미 쓴 화와 정해 둔 플롯 중 어디가 흔들리는지 보여 주고, 고칠 방법을 변경안으로 내요. 반영은 고른 것만 해요.';
  if (!els.length) {
    return `${header('요소 · 특징 · 설정 · 사건', '인과율', desc, add)}
      <div class="card empty"><p>아직 더한 요소가 없어요.</p>
        <div class="small">예: "윤만석은 서윤의 친아버지다"(과거 사건, 처음부터 사실), "7화부터 마을에 통금이 생긴다"(세계 규칙, 7화부터)</div>${add}</div>`;
  }
  return `${header('요소 · 특징 · 설정 · 사건', '인과율', desc, add)}
    <div class="causal">${causalList()}
      <div class="causal-main">${el ? causalEditor(el) + causalStrip(el) + causalImpact(el) : ''}</div></div>`;
}

// ----- 동작 -----

function touchEl() {
  markDirty();
}

Object.assign(actions, {
  async causalNew() {
    const kind = S.causalKind || '기타';
    const id = newElementId();
    P().elements.push({ id, kind, name: '', aliases: [], description: '', characters: [], since_ep: 0, episodes: [], reveal_ep: 0, context: 'auto', created_at: '', added_after: 0, impact: null });
    S.causalSel = id;
    await run('더하는 중', async () => { await save(); await causalLoad(); });
    document.getElementById('f-elements-' + causalIndex(id) + '-name')?.focus();
  },
  causalSelect(id) {
    S.causalSel = String(id);
    render();
  },
  causalFilter(kind) {
    S.causalKind = kind || '';
    render();
  },
  async causalDelete() {
    const el = causalEl();
    if (!el || !confirm(`'${el.name || '이름 없음'}' 요소를 지울까요? 이미 반영한 플롯과 본문은 그대로예요.`)) return;
    P().elements = P().elements.filter((x) => x.id !== el.id);
    S.causalSel = null;
    await run('지우는 중', async () => { await save(); await causalLoad(); });
  },
  causalSince(mode) {
    const el = causalEl();
    el.since_ep = mode === 'start' ? 0 : Math.max(1, el.since_ep || lastWritten() + 1);
    touchEl();
    render();
  },
  causalContext(k) {
    causalEl().context = k;
    markDirty();
    render();
  },
  async causalAnalyze() {
    const el = causalEl();
    if (!el.name.trim() || !el.description.trim()) return toast('이름과 설명을 먼저 적으세요', true);
    await startJob('impact', null, { element: el.id });
  },
  async causalApply() {
    const el = causalEl();
    const picked = (part) => {
      const box = document.querySelector(`[data-causal-pick="${CSS.escape(pickId(el, part))}"]`);
      return !!(box && box.checked && !box.disabled);
    };
    const r = el.impact.report;
    const body = {
      episodes: r.episodes.map((e) => e.number).filter((n) => picked('ep:' + n)),
      patches: r.patches.map((_, i) => i).filter((i) => picked('patch:' + i)),
      facts: r.new_facts.map((_, i) => i).filter((i) => picked('fact:' + i)),
    };
    if (!body.episodes.length && !body.patches.length && !body.facts.length) return toast('반영할 부분을 고르세요', true);
    await run('반영하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/elements/${enc(el.id)}/impact/apply`, body);
      await causalLoad();
      toast(`반영했습니다: ${causalEl().impact.applied.map(appliedLabel).join(', ')}`);
    });
  },
  async causalDismiss() {
    const el = causalEl();
    await run('정리하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/elements/${enc(el.id)}/impact/dismiss`);
    });
  },
});

/** 영향 분석 작업이 끝나면 디스크에 쓴 분석만 받아 온다. 저장하지 않은 요소 편집은 그대로 둔다. */
async function mergeImpacts() {
  if (!S.name || !P()) return;
  try {
    const fresh = await api('GET', `/projects/${enc(S.name)}`);
    if (!S.dirty) S.project = fresh;
    else {
      const by = new Map(fresh.elements.map((x) => [x.id, x]));
      P().elements.forEach((x) => { if (by.has(x.id)) x.impact = by.get(x.id).impact; });
    }
    await causalLoad();
  } catch { /* 다음 확인 때 다시 */ }
}

document.addEventListener('change', (e) => {
  const t = e.target;
  if (!t.dataset || S.route[2] !== 'causal') return;
  const el = causalEl();
  if (!el) return;
  if (t.dataset.causalPick) { S.causalPicks[t.dataset.causalPick] = t.checked; return; }
  if (t.dataset.elKind !== undefined) el.kind = t.value;
  else if (t.dataset.elChar) el.characters = t.checked ? [...new Set([...el.characters, t.dataset.elChar])] : el.characters.filter((x) => x !== t.dataset.elChar);
  else if (t.dataset.elEps !== undefined) el.episodes = [...new Set(t.value.split(/[,\s]+/).map((x) => parseInt(x, 10)).filter((x) => x > 0))].sort((a, b) => a - b);
  else {
    // 글을 고친 칸은 다시 그리지 않는다: 다른 칸을 누를 때 change 가 나서 그 칸이 다시 만들어지면 커서를 잃는다
    if ((t.dataset.bind || '').startsWith('elements.')) touchEl();
    return;
  }
  touchEl();
  render();
});

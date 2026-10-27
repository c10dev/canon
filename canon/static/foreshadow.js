/* 복선 센터. app.js 의 S, actions, api, run, render, header, esc, ep 와 passage.js 의 showTool, placeTool, hideTool, flushText 를 쓴다.
   복선마다 심은 문장 · 회수한 문장(Project.foreshadow_clues), 회수율, 끊어진 연결, 회수 예정이 지난 복선을 한곳에서 본다.
   계산값은 서버 canon/foreshadows.py 의 center() 를 /foreshadows 한 번으로 받는다.
   본문에서 문장을 골라 '복선으로' 를 누르면 그 문장을 복선에 건다 (고치는 본문은 passage.js 도구, 반영한 화는 illust.js 도구에 버튼을 붙인다).
   상태 승인 화면에서 AI 가 찾은 문장은 'q' 항목으로 고른다 (fsClueRows). */
'use strict';

Object.assign(S, {
  fs: null,           // 서버 계산값 center()
  fsTab: 'open',      // open | resolved | all | attention
  fsScope: '',        // '' 이면 범위 전체
  fsOpen: {},         // 펼친 복선 {id: true}
  fsAdd: false,       // 직접 더하기 칸 열림
  fsDraft: null,      // 본문에서 고른 문장 { n, quote, foreshadow, kind, description }
});

const FS_SCOPE = { arc: '이번 아크', part: '이번 부', series: '작품 끝까지' };

(function fsStyle() {
  const css = `
.fs-sum { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px; }
.fs-sum .num { font-size: 22px; font-weight: 800; }
.fs-list { display: flex; flex-direction: column; gap: 0; }
.fs-item { padding: 14px 0; border-top: 1px solid var(--line); display: flex; flex-direction: column; gap: 8px; }
.fs-item:first-child { border-top: none; }
.fs-item .desc-line { font-size: 14px; line-height: 1.55; }
.fs-track { position: relative; height: 18px; margin: 2px 6px; }
.fs-track .rail { position: absolute; left: 0; right: 0; top: 8px; height: 2px; background: var(--line); }
.fs-track .span { position: absolute; top: 7px; height: 4px; border-radius: 2px; background: var(--accent-soft); }
.fs-track .dot { position: absolute; top: 3px; width: 12px; height: 12px; margin-left: -6px; border-radius: 50%; border: 2px solid var(--surface); }
.fs-track .dot.plant { background: var(--accent); }
.fs-track .dot.payoff { background: var(--green); }
.fs-track .dot.broken { background: var(--red); }
.fs-track .tick { position: absolute; top: 0; width: 2px; height: 18px; margin-left: -1px; background: var(--amber); }
.fs-track .tick.plan { background: transparent; border-left: 2px dashed var(--green); }
.fs-track .now { position: absolute; top: -2px; bottom: -2px; width: 0; border-left: 1px solid var(--muted); }
.fs-clues { display: flex; flex-direction: column; gap: 6px; padding-left: 4px; }
.fs-clue { display: flex; gap: 10px; align-items: flex-start; font-size: 13px; line-height: 1.6; }
.fs-clue q { font-family: var(--serif); color: var(--text-2); quotes: '“' '”'; }
.fs-clue.broken q { text-decoration: line-through; color: var(--red); }
.fs-edit { display: grid; grid-template-columns: 1fr 140px 120px; gap: 10px; align-items: end; }
@media (max-width: 720px) { .fs-edit { grid-template-columns: 1fr; } }
.fs-pop { position: absolute; z-index: 60; width: min(360px, calc(100vw - 16px)); padding: 14px; border: 1px solid var(--line-strong); border-radius: 10px; background: var(--surface); box-shadow: 0 8px 24px rgba(0,0,0,.12); display: flex; flex-direction: column; gap: 10px; }
.fs-pop [hidden] { display: none !important; }
.fs-pop q { font-family: var(--serif); font-size: 13px; line-height: 1.6; color: var(--text-2); max-height: 6.4em; overflow: auto; display: block; }
.fs-q { font-family: var(--serif); font-size: 13px; line-height: 1.7; color: var(--text-2); }`;
  const el = document.createElement('style');
  el.textContent = css;
  document.head.appendChild(el);
}());

async function fsLoad() {
  S.fs = await api('GET', `/projects/${enc(S.name)}/foreshadows`).catch((e) => ({ error: e.message, items: [] }));
}

function fsShown(x) {
  if (S.fsScope && x.scope !== S.fsScope) return false;
  if (S.fsTab === 'open') return x.status === 'open';
  if (S.fsTab === 'resolved') return x.status === 'resolved';
  if (S.fsTab === 'attention') return x.overdue || x.stale || x.broken > 0;
  return true;
}

function fsTrack(x, last, done) {
  const at = (n) => `${(Math.max(0, n - 1) / Math.max(1, last - 1)) * 100}%`;
  const end = x.payoff_ep || Math.max(done, x.last_seen);
  const dots = [
    ...x.plants.map((c) => `<span class="dot ${c.broken ? 'broken' : 'plant'}" style="left:${at(c.episode)}" title="${c.episode}화 심음"></span>`),
    ...x.payoffs.map((c) => `<span class="dot ${c.broken ? 'broken' : 'payoff'}" style="left:${at(c.episode)}" title="${c.episode}화 회수"></span>`),
  ];
  if (!x.plants.length) dots.unshift(`<span class="dot plant" style="left:${at(x.planted_ep)}" title="${x.planted_ep}화 심음"></span>`);
  if (x.payoff_ep && !x.payoffs.length) dots.push(`<span class="dot payoff" style="left:${at(x.payoff_ep)}" title="${x.payoff_ep}화 회수"></span>`);
  const ticks = [
    x.due_ep ? `<span class="tick" style="left:${at(x.due_ep)}" title="${x.due_ep}화 회수 예정"></span>` : '',
    ...(x.status === 'open' ? x.planned : []).map((n) => `<span class="tick plan" style="left:${at(n)}" title="${n}화 플롯에서 회수"></span>`),
  ].join('');
  return `<div class="fs-track" aria-hidden="true"><span class="rail"></span>
    <span class="span" style="left:${at(x.planted_ep)};width:calc(${at(end)} - ${at(x.planted_ep)})"></span>
    ${done ? `<span class="now" style="left:${at(done)}" title="${done}화까지 반영"></span>` : ''}${ticks}${dots.join('')}</div>`;
}

function fsClueList(x) {
  const rows = [...x.plants.map((c) => ({ ...c, kind: 'plant' })), ...x.payoffs.map((c) => ({ ...c, kind: 'payoff' }))]
    .sort((a, b) => a.episode - b.episode);
  if (!rows.length) return '<div class="small">본문에 걸린 문장이 없어요. 집필 화면에서 문장을 드래그해 \'복선으로\'를 누르면 걸 수 있어요.</div>';
  return `<div class="fs-clues">${rows.map((c) => `<div class="fs-clue${c.broken ? ' broken' : ''}">
      <a class="chip ${c.kind === 'payoff' ? 'finalized' : 'confirmed'}" href="${base()}/write/${c.episode}">${c.episode}화 ${c.kind === 'payoff' ? '회수' : '심음'}</a>
      <div style="flex:1;min-width:0"><q>${esc(c.quote)}</q>${c.by === 'author' ? ' <span class="small">작가</span>' : ''}${c.broken ? ' <span class="small" style="color:var(--red)">본문에서 사라짐</span>' : ''}</div>
      <button type="button" class="btn small ghost" data-action="fsClueDrop" data-arg="${esc(JSON.stringify({ foreshadow: x.id, episode: c.episode, quote: c.quote }))}" aria-label="이 문장 연결 지우기">지우기</button></div>`).join('')}</div>`;
}

function fsEditForm(x, done) {
  const id = esc(x.id);
  return `<div class="fs-edit">
      <div class="field"><label for="fs-d-${id}">내용</label><input id="fs-d-${id}" type="text" value="${esc(x.description)}"></div>
      <div class="field"><label for="fs-s-${id}">회수 범위</label><select id="fs-s-${id}">${Object.entries(FS_SCOPE).map(([k, v]) => `<option value="${k}"${x.scope === k ? ' selected' : ''}>${v}</option>`).join('')}</select></div>
      <div class="field"><label for="fs-u-${id}">회수 예정 화</label><input id="fs-u-${id}" type="number" min="${x.planted_ep}" value="${x.due_ep || ''}" placeholder="미정"></div>
    </div>
    <div class="row"><button type="button" class="btn small primary" data-action="fsSave" data-arg="${id}">저장</button>
      ${x.status === 'open'
    ? `<span class="row" style="gap:6px"><label class="small" for="fs-r-${id}">회수한 화</label><input id="fs-r-${id}" type="number" min="${x.planted_ep}" value="${Math.max(done, x.planted_ep)}" style="width:80px"><button type="button" class="btn small" data-action="fsResolve" data-arg="${id}">회수로 표시</button></span>`
    : `<button type="button" class="btn small" data-action="fsReopen" data-arg="${id}">다시 열기</button>`}
      <button type="button" class="btn small danger" data-action="fsDelete" data-arg="${id}">복선 지우기</button></div>`;
}

function fsItem(x, c) {
  const flags = [
    x.overdue ? `<span class="chip written">예정 ${x.due_ep}화 지남</span>` : '',
    x.stale ? '<span class="chip written">50화 넘게 안 나옴</span>' : '',
    x.broken ? `<span class="chip" style="background:var(--red-soft);color:var(--red)">끊어진 연결 ${x.broken}</span>` : '',
  ].join(' ');
  const when = x.payoff_ep ? `${x.planted_ep}화 → ${x.payoff_ep}화 회수` : `${x.planted_ep}화에 심음 · 마지막 등장 ${x.last_seen}화${x.due_ep ? ` · 예정 ${x.due_ep}화` : ''}`;
  const plan = x.status === 'open' && x.planned.length ? ` · ${x.planned.join(', ')}화 플롯에서 회수 예정` : '';
  const open = !!S.fsOpen[x.id];
  return `<div class="fs-item">
    <div class="between" style="align-items:flex-start;flex-wrap:nowrap;gap:12px">
      <div style="min-width:0"><div class="row" style="gap:6px"><span class="chip ${x.status === 'resolved' ? 'finalized' : 'confirmed'}">${x.status === 'resolved' ? '회수' : '열림'}</span><span class="chip">${FS_SCOPE[x.scope] || x.scope}</span>${flags}</div>
        <div class="desc-line" style="margin-top:6px">${esc(x.description)} <span class="small">${esc(x.id)}</span></div>
        <div class="small">${when}${plan} · 문장 ${x.plants.length + x.payoffs.length}개</div></div>
      <button type="button" class="btn small" data-action="fsToggle" data-arg="${esc(x.id)}" aria-expanded="${open}">${open ? '접기' : '자세히'}</button></div>
    ${fsTrack(x, c.last_ep, c.done)}
    ${open ? `${fsClueList(x)}${fsEditForm(x, c.done)}` : ''}
  </div>`;
}

function fsAddForm(c) {
  if (!S.fsAdd) return '';
  return `<section class="card"><h2>복선 직접 더하기</h2>
    <p class="desc">본문 문장 없이 계획만 적어 둘 수도 있어요. 문장을 함께 걸려면 집필 화면에서 문장을 골라 '복선으로'를 누르세요.</p>
    <div class="fs-edit"><div class="field"><label for="fs-new-d">내용</label><input id="fs-new-d" type="text" placeholder="예: 서윤의 목걸이에 새겨진 문양"></div>
      <div class="field"><label for="fs-new-s">회수 범위</label><select id="fs-new-s">${Object.entries(FS_SCOPE).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></div>
      <div class="field"><label for="fs-new-u">회수 예정 화</label><input id="fs-new-u" type="number" min="1" placeholder="미정"></div></div>
    <div class="row"><label class="small" for="fs-new-e">심은 화</label><input id="fs-new-e" type="number" min="1" value="${Math.max(c.done, 1)}" style="width:80px">
      <button type="button" class="btn primary small" data-action="fsCreate">더하기</button><button type="button" class="btn small" data-action="fsAddToggle">닫기</button></div></section>`;
}

function viewForeshadow() {
  const head = header('복선', '복선 센터', '복선마다 본문 어느 문장에 심고 회수했는지, 회수율과 오래 묵은 복선을 봐요. AI가 찾은 문장은 상태 승인 화면에서 골라 반영돼요.',
    `<button type="button" class="btn" data-action="fsAddToggle">+ 복선 직접 더하기</button>`);
  const c = S.fs;
  if (!c) return `${head}<div class="small">불러오는 중…</div>`;
  if (c.error) return `${head}<div class="note err">${esc(c.error)}</div>`;
  const rate = c.rate == null ? '-' : `${Math.round(c.rate * 100)}%`;
  const sum = `<section class="card"><div class="fs-sum">
      <div><div class="small">복선</div><div class="num">${c.total}</div></div>
      <div><div class="small">열림</div><div class="num">${c.open}</div></div>
      <div><div class="small">회수율</div><div class="num">${rate}</div><div class="meter" aria-hidden="true"><i style="left:0;width:${(c.rate || 0) * 100}%;background:var(--green)"></i></div></div>
      <div><div class="small">예정 지남</div><div class="num" style="${c.overdue ? 'color:var(--amber)' : ''}">${c.overdue}</div></div>
      <div><div class="small">50화 넘게 묵음</div><div class="num" style="${c.stale ? 'color:var(--amber)' : ''}">${c.stale}</div></div>
      <div><div class="small">끊어진 연결</div><div class="num" style="${c.broken ? 'color:var(--red)' : ''}">${c.broken}</div></div></div>
    ${c.broken ? `<div class="note warn">본문을 고쳐 걸어 둔 문장이 사라진 연결이 ${c.broken}개 있어요. 다시 걸거나 정리하세요. <button type="button" class="btn small" data-action="fsPrune">끊어진 연결 정리</button></div>` : ''}
    <div class="legend"><span><i style="background:var(--accent);border-radius:50%"></i>심은 문장</span><span><i style="background:var(--green);border-radius:50%"></i>회수한 문장</span>
      <span><i style="background:var(--amber);width:2px"></i>회수 예정</span><span><i style="border-left:2px dashed var(--green);width:2px;border-radius:0"></i>플롯에서 회수 예정</span>
      <span><i style="background:var(--red);border-radius:50%"></i>끊어진 연결</span><span class="small">세로선은 ${c.done}화(마지막 반영)</span></div></section>`;
  const tab = (k, l) => `<button type="button" role="tab" aria-selected="${S.fsTab === k}" data-action="fsTab" data-arg="${k}">${l}</button>`;
  const items = c.items.filter(fsShown);
  const attention = c.items.filter((x) => x.overdue || x.stale || x.broken > 0).length;
  const list = `<section class="card">
    <div class="between"><div class="tabs" role="tablist" aria-label="복선 거르기">${tab('open', `열린 ${c.open}`)}${tab('resolved', `회수한 ${c.resolved}`)}${tab('all', `전체 ${c.total}`)}${tab('attention', `손볼 것 ${attention}`)}</div>
      <label class="row" style="gap:6px;font-size:13px">범위 <select data-fs-scope><option value="">전체</option>${Object.entries(FS_SCOPE).map(([k, v]) => `<option value="${k}"${S.fsScope === k ? ' selected' : ''}>${v}</option>`).join('')}</select></label></div>
    <div class="fs-list">${items.map((x) => fsItem(x, c)).join('') || '<div class="small" style="padding:12px 0">해당하는 복선이 없어요.</div>'}</div></section>`;
  return `${head}${sum}${fsAddForm(c)}${list}`;
}

// ----- 본문에서 고른 문장을 복선에 걸기 -----

function fsPop() {
  let el = document.getElementById('fs-tool');
  if (!el) {
    el = document.createElement('div');
    el.id = 'fs-tool';
    el.className = 'fs-pop';
    el.hidden = true;
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-label', '복선에 걸기');
    document.body.appendChild(el);
  }
  return el;
}

function fsPopHide() {
  S.fsDraft = null;
  const el = document.getElementById('fs-tool');
  if (el) el.hidden = true;
}

function fsPopShow(rect) {
  const d = S.fsDraft;
  const open = P().foreshadows.filter((f) => f.status === 'open' && f.planted_ep <= d.n);
  const done = P().foreshadows.filter((f) => f.status === 'resolved' && f.planted_ep <= d.n);
  const opt = (f) => `<option value="${esc(f.id)}"${d.foreshadow === f.id ? ' selected' : ''}>${esc(f.description.slice(0, 40))} (${f.planted_ep}화)</option>`;
  const el = fsPop();
  el.innerHTML = `<strong style="font-size:14px">${d.n}화 문장을 복선에 걸기</strong><q>${esc(d.quote)}</q>
    <div class="field"><label for="fs-pick">복선</label><select id="fs-pick">
      <option value=""${d.foreshadow ? '' : ' selected'}>+ 새 복선으로 심기</option>
      ${open.length ? `<optgroup label="열린 복선">${open.map(opt).join('')}</optgroup>` : ''}
      ${done.length ? `<optgroup label="회수한 복선">${done.map(opt).join('')}</optgroup>` : ''}</select></div>
    <div class="field" id="fs-new-wrap"${d.foreshadow ? ' hidden' : ''}><label for="fs-pick-d">새 복선 내용</label><input id="fs-pick-d" type="text" value="${esc(d.description)}" placeholder="무엇을 암시하는지 한 줄로"></div>
    <div class="row" id="fs-kind-wrap"${d.foreshadow ? '' : ' hidden'} style="gap:14px;font-size:13px">
      <label class="row" style="gap:6px"><input type="radio" name="fs-kind" value="plant"${d.kind === 'plant' ? ' checked' : ''}>심음 · 다시 떠올림</label>
      <label class="row" style="gap:6px"><input type="radio" name="fs-kind" value="payoff"${d.kind === 'payoff' ? ' checked' : ''}>회수</label></div>
    <div class="between"><span class="small">작가가 건 문장은 바로 저장돼요</span><span class="row" style="gap:6px"><button type="button" class="btn small" data-action="fsPopCancel">취소</button><button type="button" class="btn small primary" data-action="fsPopSave">걸기</button></span></div>`;
  el.hidden = false;
  const w = el.offsetWidth || 360;
  el.style.left = `${Math.min(Math.max(8, rect.left), document.documentElement.clientWidth - w - 8) + window.scrollX}px`;
  el.style.top = `${rect.bottom + 8 + window.scrollY}px`;
  const box = $('#fs-pick-d');
  if (box && !d.foreshadow) box.focus();
}

document.addEventListener('change', (e) => {
  if (e.target.matches && e.target.matches('[data-fs-scope]')) {
    S.fsScope = e.target.value;
    render();
  }
  if (e.target.id === 'fs-pick' && S.fsDraft) {
    S.fsDraft.foreshadow = e.target.value;
    $('#fs-new-wrap').hidden = !!e.target.value;
    $('#fs-kind-wrap').hidden = !e.target.value;
  }
  if (e.target.name === 'fs-kind' && S.fsDraft) S.fsDraft.kind = e.target.value;
});

document.addEventListener('input', (e) => {
  if (e.target.id === 'fs-pick-d' && S.fsDraft) S.fsDraft.description = e.target.value;
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && S.fsDraft) fsPopHide();
});

// 고치는 본문 칸의 떠 있는 도구(passage.js) 끝에 '복선으로'
const fsShowTool = showTool;
showTool = function showToolWithForeshadow() {
  fsShowTool();
  const t = S.selTool;
  const el = document.getElementById('sel-tool');
  const ta = t && document.querySelector(`textarea[data-draft="${t.n}"]`);
  if (!ta || !el || el.hidden || t.mode !== 'menu') return;
  el.insertAdjacentHTML('beforeend', '<button type="button" class="btn small" data-action="selForeshadow" title="이 문장을 복선을 심거나 회수한 자리로 기억한다">복선으로</button>');
  placeTool(ta, t);
};

// 반영한 화의 읽기 전용 본문 도구(illust.js)에도. illust.js 가 도구를 띄운 다음 차례에 붙인다
document.addEventListener('mouseup', (e) => {
  if (e.target.closest && (e.target.closest('#ill-tool') || e.target.closest('#fs-tool'))) return;
  setTimeout(() => {
    const el = document.getElementById('ill-tool');
    if (!el || el.hidden || el.querySelector('[data-action="fsFromRead"]')) return;
    el.insertAdjacentHTML('beforeend', '<button type="button" class="btn small" data-action="fsFromRead">복선으로</button>');
    const r = el.getBoundingClientRect();
    const over = r.right - (document.documentElement.clientWidth - 8);
    if (over > 0) el.style.left = `${parseFloat(el.style.left) - over}px`;
  }, 0);
});

/** render() 뒤에는 떠 있는 칸을 닫는다 (화면이 바뀌면 고른 자리가 사라진다). */
window.addEventListener('hashchange', fsPopHide);

async function fsSaveDraft() {
  const d = S.fsDraft;
  if (!d) return;
  if (!d.foreshadow && !d.description.trim()) return toast('새 복선 내용을 적어 주세요', true);
  const body = { episode: d.n, quote: d.quote, foreshadow: d.foreshadow, description: d.description.trim(), kind: d.foreshadow ? d.kind : 'plant' };
  fsPopHide();
  await run('복선에 거는 중', async () => {
    await saveIfDirty();
    if (typeof flushText === 'function') await flushText(body.episode);
    S.project = await api('POST', `/projects/${enc(S.name)}/foreshadows/clues`, body);
    if (S.fs) await fsLoad();
    toast(body.kind === 'payoff' ? '회수한 문장으로 걸었어요' : '복선에 걸었어요. 복선 센터에서 볼 수 있어요');
  });
}

async function fsCall(label, method, path, body) {
  await run(label, async () => {
    await saveIfDirty();
    S.project = await api(method, `/projects/${enc(S.name)}/foreshadows${path}`, body);
    await fsLoad();
  });
}

Object.assign(actions, {
  selForeshadow() {
    const t = S.selTool;
    const ta = document.querySelector(`textarea[data-draft="${t.n}"]`);
    const tool = document.getElementById('sel-tool');
    const rect = (tool && !tool.hidden ? tool : ta).getBoundingClientRect();
    S.fsDraft = { n: t.n, quote: t.text, foreshadow: '', kind: 'plant', description: '' };
    hideTool();
    fsPopShow(rect);
  },
  fsFromRead() {
    const s = S.illPending;
    if (typeof hideIlTool === 'function') hideIlTool();
    window.getSelection()?.removeAllRanges();
    if (!s) return;
    S.fsDraft = { n: s.n, quote: s.text, foreshadow: '', kind: 'plant', description: '' };
    fsPopShow(s.rect);
  },
  fsPopCancel() { fsPopHide(); },
  fsPopSave() { fsSaveDraft(); },
  fsTab(k) { S.fsTab = k; render(); },
  fsToggle(id) { S.fsOpen[id] = !S.fsOpen[id]; render(); },
  fsAddToggle() { S.fsAdd = !S.fsAdd; render(); },
  fsCreate() {
    const description = $('#fs-new-d').value.trim();
    if (!description) return toast('복선 내용을 적어 주세요', true);
    const due = Number($('#fs-new-u').value);
    const body = { description, episode: Number($('#fs-new-e').value) || 0, scope: $('#fs-new-s').value, due_ep: due || null };
    S.fsAdd = false;
    S.fsTab = 'open';
    fsCall('복선 더하는 중', 'POST', '', body);
  },
  fsSave(id) {
    const due = Number($(`#fs-u-${CSS.escape(id)}`).value);
    fsCall('저장 중', 'PUT', `/${enc(id)}`, {
      description: $(`#fs-d-${CSS.escape(id)}`).value.trim(), scope: $(`#fs-s-${CSS.escape(id)}`).value, due_ep: due || null, clear_due: !due,
    });
  },
  fsResolve(id) {
    fsCall('회수로 표시하는 중', 'POST', `/${enc(id)}/resolve`, { episode: Number($(`#fs-r-${CSS.escape(id)}`).value) });
  },
  fsReopen(id) { fsCall('다시 여는 중', 'POST', `/${enc(id)}/reopen`); },
  fsDelete(id) {
    if (!confirm('이 복선과 걸어 둔 문장을 모두 지울까요? 플롯의 회수 계획에서도 빠져요.')) return;
    delete S.fsOpen[id];
    fsCall('지우는 중', 'DELETE', `/${enc(id)}`);
  },
  fsClueDrop(raw) { fsCall('연결 지우는 중', 'POST', '/clues/remove', JSON.parse(raw)); },
  fsPrune() { fsCall('끊어진 연결 정리하는 중', 'POST', '/prune'); },
});

// ----- 상태 승인 화면 -----

/** AI 가 본문에서 찾은 복선 문장. 고른 것만 반영한다(q 항목). 이번 화에 심거나 회수하는 복선이면 그 항목을 같이 골라야 남는다. */
function fsClueRows(d, box) {
  const p = P();
  const label = (fid) => {
    const f = p.foreshadows.find((x) => x.id === fid) || d.foreshadow_planted.find((x) => x.id === fid);
    return f ? f.description : fid;
  };
  return (d.foreshadow_clues || []).map((c, i) => {
    const fresh = d.foreshadow_planted.some((x) => x.id === c.foreshadow);
    const note = c.kind === 'payoff' ? '회수한 문장' : fresh ? '심은 문장' : '다시 떠올린 문장';
    return `<div class="change">${box('q' + i)}<label for="pk-q${i}" style="font-size:13px;line-height:1.55"><span class="chip ${c.kind === 'payoff' ? 'finalized' : 'confirmed'}">${note}</span> ${esc(label(c.foreshadow))}
      <div class="fs-q">“${esc(c.quote)}”</div></label></div>`;
  }).join('');
}

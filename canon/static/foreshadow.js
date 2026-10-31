/* 복선 센터. app.js 의 S, actions, api, run, render, header, esc, ep 와 outline.js 의 공용 목차 틀, passage.js 의 떠 있는 도구(showTool, placeTool, hideTool, toolEl, flushText)를 쓴다.
   화면은 공용 목차 틀이다: 왼쪽 목차(개요 · 손볼 것 · 열린 복선 · 회수한 복선), 오른쪽은 개요(주소 foreshadow) 또는 복선 하나(foreshadow/<id>).
   개요: 수치 띠 → 손볼 것(끊어진 연결 · 예정 지남 · 오래 묵음과 할 일) → 복선 지도(화 축 하나, 줄마다 복선 하나) → 앞으로 회수할 것.
   복선 하나: 축 위 한 줄 → 본문에 걸린 문장과 흐름(지난 일 실선, 지금, 앞으로 점선) → 회수 계획(읽기 카드, '고치기'로 그 카드만).
   계산값은 서버 canon/foreshadows.py 의 center() 를 /foreshadows 한 번으로 받는다.
   본문에서 문장을 골라 '복선으로'를 누르면 떠 있는 도구(#sel-tool)가 걸기 칸(mode 'foreshadow')이 된다. 고치는 본문은 passage.js 도구, 반영한 화의 읽기 전용 본문은 illust.js 도구에서 연다.
   상태 승인 화면에서 AI 가 찾은 문장은 'q' 항목으로 고른다 (fsClueRows).
   fsBands · fsAt · fsMarks · fsFlag · fsAttention · fsTodo · fsTocRows · fsFlow · fsAhead · fsTicks · fsCandidates 는 순수 함수(tests/test_foreshadow_js.py) */
'use strict';

Object.assign(S, {
  fs: null,           // 서버 계산값 center()
  fsSel: '',          // 주소의 복선 id. 비면 개요
  fsTab: 'open',      // 지도에 보이는 복선: open | resolved | all
  fsTabPicked: '',    // 작가가 고른 작품. 고르기 전에는 열린 복선이 없을 때 '전체'를 연다
  fsScope: '',        // '' 이면 범위 전체
  fsDoneOpen: false,  // 목차의 회수한 복선 펼침
  fsAdd: false,       // 직접 더하기 칸 열림
  fsEdit: '',         // 회수 계획을 고치는 복선 id
  fsResolving: '',    // 회수한 화를 고르는 복선 id
  fsOwner: '',        // fsEdit · fsResolving · fsScope 를 정한 작품. 작품이 바뀌면 지운다
});

const FS_SCOPE = { arc: '이번 아크', part: '이번 부', series: '작품 끝까지' };
const FS_LONG_OPEN = 50;  // 이 화수 넘게 다시 떠올리지 않은 열린 복선은 오래 묵음. 서버 foreshadows.LONG_OPEN 과 같은 값이라 함께 고친다
const FS_PICK_MAX = 6;    // 걸기 칸에 찾기 없이 보이는 복선 수

(function fsStyle() {
  const css = `
.fs-col { display: flex; flex-direction: column; gap: var(--gap-stack); min-width: 0; container: fscol / inline-size; }
.fs-col > .card { scroll-margin-top: 16px; }
@container outline (min-width: 721px) { .fs-wrap .outline-list { max-height: calc(100vh - 32px); overflow-y: auto; } }
.fs-wrap .outline-item .tl { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fs-wrap .outline-item .mk { flex: none; width: 10px; display: inline-flex; justify-content: center; }
.fs-sym { display: inline-block; flex: none; }
.fs-sym.plant { width: 10px; height: 10px; border-radius: 50%; background: var(--accent); }
.fs-sym.payoff { width: 10px; height: 10px; border-radius: 2px; background: var(--green); transform: rotate(45deg); }
.fs-sym.broken { width: 10px; height: 10px; border-radius: 50%; border: 2px dashed var(--red); background: var(--surface); }
.fs-sym.due { width: 0; height: 0; border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 8px solid var(--amber); }
.fs-sym.plan { width: 0; height: 12px; border-left: 2px dashed var(--green); }
.fs-sym.warnd { width: 8px; height: 8px; border-radius: 50%; background: var(--amber); }
.fs-sym.okd { width: 8px; height: 8px; border-radius: 1px; background: var(--green); transform: rotate(45deg); }
.fs-sym.opend { width: 8px; height: 8px; border-radius: 50%; border: 2px solid var(--accent); }
.fs-sym.nowd { width: 12px; height: 2px; background: var(--muted); }
.fs-legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 0.75rem; color: var(--muted); }
.fs-legend span { display: inline-flex; align-items: center; gap: 6px; }
.fs-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); }
.fs-stats > div { min-width: 0; padding: 0 20px; border-left: 1px solid var(--rule); display: flex; flex-direction: column; gap: 4px; }
.fs-stats > div:first-child { padding-left: 0; border-left: none; }
.fs-stats .num { font-size: 1.375rem; font-weight: 800; letter-spacing: -0.02em; }
.fs-stats .num.warn { color: var(--amber-ink); }
.fs-stats .meter > i { background: var(--green); }
.fs-clue-pick { flex: 1; min-width: 0; font-size: 0.8125rem; line-height: 1.55; }
.fs-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 12px; }
.fs-todo { display: flex; flex-direction: column; }
.fs-todo-row { display: grid; grid-template-columns: 104px minmax(0, 1fr) auto; gap: 12px; align-items: center; min-height: 52px; padding: var(--pad-row) 0; border-top: 1px solid var(--rule); }
.fs-todo-row:first-child { border-top: none; }
.fs-todo-row .t { color: var(--text); font-weight: 700; text-decoration: none; }
.fs-todo-row .t:hover { text-decoration: underline; }
.fs-todo-row > div { min-width: 0; display: flex; flex-direction: column; }
.fs-map { display: flex; flex-direction: column; }
.fs-axis, .fs-row { display: grid; grid-template-columns: minmax(0, 220px) minmax(0, 1fr) 136px; gap: 12px; align-items: center; }
.fs-axis { padding-bottom: 6px; border-bottom: 1px solid var(--line); }
.fs-row { min-height: 36px; border-bottom: 1px solid var(--rule); color: var(--text); text-decoration: none; }
.fs-row:last-child { border-bottom: none; }
.fs-row:hover { background: var(--canvas); }
.fs-row .lb { min-width: 0; display: flex; align-items: center; gap: 8px; padding-left: 4px; }
.fs-row .lb .t { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fs-fl { font-size: 0.75rem; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fs-fl.warn { color: var(--amber-ink); font-weight: 700; }
.fs-fl.bad { color: var(--err-ink); font-weight: 700; }
.fs-trk { position: relative; height: 22px; }
.fs-trk .band { position: absolute; top: -7px; bottom: -7px; }
.fs-trk .band.odd { background: var(--bg); }
.fs-trk .bar { position: absolute; top: 9px; height: 4px; border-radius: 2px; background: var(--accent-soft); box-shadow: inset 0 0 0 1px var(--line); }
.fs-trk .bar.done { background: var(--green-soft); }
.fs-trk .now { position: absolute; top: -7px; bottom: -7px; border-left: 1px solid var(--muted); }
.fs-trk .m { position: absolute; top: 6px; transform: translateX(-50%); display: flex; }
.fs-trk .m.due { top: 0; }
.fs-trk .m.plan { top: 5px; }
.fs-scale { position: relative; height: 36px; font-size: 0.6875rem; color: var(--muted); }
.fs-scale.ticks { height: 16px; }
.fs-scale.arcs { height: 20px; }
.fs-scale .arc { position: absolute; top: 0; height: 18px; padding: 0 6px; font-weight: 700; color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; border-left: 1px solid var(--line); }
.fs-scale .tk { position: absolute; top: 20px; transform: translateX(-50%); white-space: nowrap; }
.fs-scale.ticks .tk { top: 0; }
.fs-scale .tk.first { transform: none; }
.fs-scale .tk.last { transform: translateX(-100%); }
.fs-scale .tk.now { color: var(--text); font-weight: 700; }
.fs-flow { display: flex; flex-direction: column; }
.fs-fi { display: grid; grid-template-columns: 64px 20px minmax(0, 1fr); column-gap: 12px; }
.fs-fi .ep { padding-top: 12px; text-align: right; font-weight: 700; font-size: 0.8125rem; }
.fs-fi .rail { position: relative; display: flex; justify-content: center; }
.fs-fi .rail::before { content: ''; position: absolute; top: 0; bottom: 0; left: 9px; border-left: 2px solid var(--line); }
.fs-fi.future .rail::before { border-left-style: dashed; }
.fs-fi:first-child .rail::before { top: 18px; }
.fs-fi:last-child .rail::before { bottom: calc(100% - 18px); }
.fs-fi .rail .fs-sym { position: relative; margin-top: 16px; }
.fs-fi .bd { min-width: 0; padding: 10px 0 14px; display: flex; flex-direction: column; gap: 6px; }
.fs-fi .k { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; font-size: 0.8125rem; }
.fs-fi.now .ep { padding-top: 8px; color: var(--muted); font-weight: 500; }
.fs-fi.now .rail .fs-sym { margin-top: 18px; }
.fs-fi.now .bd { padding: 8px 0; }
.fs-fi.broken .bd { margin: 6px 0 10px; padding: 10px 14px 12px; border-radius: 10px; background: var(--red-soft); }
.fs-fi.broken .k, .fs-fi.late .k { color: var(--err-ink); }
.fs-fi.late .k { color: var(--amber-ink); }
.fs-q { margin: 0; font-family: var(--serif); font-size: 0.9375rem; line-height: 1.75; color: var(--text); }
.fs-q.cut { text-decoration: line-through; color: var(--muted); }
.fs-edit { display: grid; grid-template-columns: minmax(0, 1fr) 140px 120px; gap: 10px; align-items: end; }
/* 카드 열이 좁으면(넓은 화면이라도 사이드바 · 목차를 빼고 760px 이하) 지도 줄은 이름 · 한마디 아래에 축을 둔다 */
@container fscol (max-width: 760px) {
  .fs-axis, .fs-row { grid-template-columns: minmax(0, 1fr) auto; row-gap: 4px; }
  .fs-row { padding: 8px 0; }
  .fs-row .fs-trk, .fs-axis .fs-scale { grid-column: 1 / -1; grid-row: 2; }
  .fs-axis > .lb, .fs-axis > .fs-fl { display: none; }
}
@container outline (max-width: 720px) {
  .fs-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); row-gap: 14px; }
  .fs-stats > div:nth-child(odd) { padding-left: 0; border-left: none; }
  .fs-todo-row { grid-template-columns: minmax(0, 1fr); gap: 6px; }
  .fs-todo-row .btn { justify-self: start; }
  .fs-fi { grid-template-columns: 40px 20px minmax(0, 1fr); column-gap: 8px; }
  .fs-edit { grid-template-columns: minmax(0, 1fr); }
}
.sel-tool.fs-link { flex-direction: column; flex-wrap: nowrap; align-items: stretch; gap: 10px; width: min(400px, calc(100vw - 16px)); max-height: min(80vh, 640px); overflow-y: auto; padding: 12px 14px; }
.fs-link .qq { margin: 0; padding-left: 10px; border-left: 2px solid var(--line-strong); font-family: var(--serif); font-size: 0.8125rem; line-height: 1.6; color: var(--text-2); max-height: 6.4em; overflow: auto; }
.fs-link .seg { align-self: flex-start; }
.fs-pick { display: flex; flex-direction: column; max-height: 264px; overflow-y: auto; border: 1px solid var(--line); border-radius: 8px; }
.fs-pick > * { flex: none; border-top: 1px solid var(--rule); }
.fs-pick > :first-child { border-top: none; }
.fs-pick label { min-height: 44px; padding: 6px 10px; display: grid; grid-template-columns: 20px minmax(0, 1fr) auto; gap: 2px 8px; align-items: center; font-size: 0.8125rem; cursor: pointer; }
.fs-pick label:has(input:checked) { background: var(--sel-bg); }
.fs-pick input { width: 18px; height: 18px; margin: 0; accent-color: var(--accent); }
.fs-pick .dd { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fs-pick .s { grid-column: 2 / 4; font-size: 0.75rem; color: var(--muted); }
.fs-pick .h, .fs-pick .none { padding: 6px 10px; font-size: 0.75rem; color: var(--muted); background: var(--bg); }
.fs-link .grid-2 { grid-template-columns: minmax(0, 1fr) 120px; }
.fs-link .foot { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 8px; }
@media (max-width: 640px) {
  .sel-tool.fs-link { position: fixed; left: 0 !important; right: 0; top: auto !important; bottom: 0; width: auto; max-width: none; max-height: 85vh; padding: 14px 16px 20px; border-radius: 12px 12px 0 0; box-shadow: var(--shadow-dialog); }
  .fs-link .foot .btn { flex: 1; }
}
.fs-q-row { font-family: var(--serif); font-size: 0.8125rem; line-height: 1.7; color: var(--text-2); }`;
  const el = document.createElement('style');
  el.textContent = css;
  document.head.appendChild(el);
}());

async function fsLoad(sel) {
  const prev = S.fsSel;
  S.fsSel = sel || '';  // 라우터가 주소 조각을 이미 풀었다
  if (prev !== S.fsSel && !S.focusTarget) S.focusTarget = '#app main h1';  // 개요 ↔ 복선 하나, 복선끼리 옮길 때도 제목으로 (동작이 정한 칸이 있으면 그 칸)
  if (S.fsOwner !== S.name) { S.fsEdit = ''; S.fsResolving = ''; S.fsScope = ''; S.fsOwner = S.name; }
  S.fs = await api('GET', `/projects/${enc(S.name)}/foreshadows`).catch((e) => ({ error: e.message, items: [] }));
  if (S.fsScope && !(S.fs.items || []).some((x) => x.scope === S.fsScope)) S.fsScope = '';  // 거르기를 풀 버튼이 없는 범위는 푼다
  // 작가가 거르기를 고르기 전이면, 열린 복선이 없을 때 빈 지도 대신 전체를 보인다
  if (S.fsTabPicked !== S.name && S.fsTab === 'open' && !S.fs.error && !S.fs.open && S.fs.total) S.fsTab = 'all';
  if (S.fsEdit && S.fsEdit !== S.fsSel) S.fsEdit = '';
  if (S.fsResolving && S.fsResolving !== S.fsSel) S.fsResolving = '';
}

const fsHref = (id) => `${base()}/foreshadow${id ? `/${encodeURIComponent(id)}` : ''}`;

// ----- 순수 계산 -----

/** 축 위 띠: 장편은 아크, 단편은 기승전결 구간. [{ label, s, e }] */
function fsBands(p) {
  if (p.meta && p.meta.form === 'serial') return (p.story_arcs || []).map((a) => ({ label: `아크 ${a.number} · ${a.title}`, s: a.start_ep, e: a.end_ep }));
  return (p.arc || []).map((a) => ({ label: a.name, s: a.start_ep, e: a.end_ep }));
}

/** n화의 축 위 자리(%) */
const fsAt = (n, last) => `${((Math.max(1, n) - 1) / Math.max(1, last - 1)) * 100}%`;

/** 열린 복선 가운데 작가가 볼 것: 끊어진 연결, 회수 예정 지남, 오래 묵음 */
const fsAttention = (x) => x.status === 'open' ? !!(x.broken || x.overdue || x.stale) : x.broken > 0;

/** 한 줄 위 표시: [{ kind: plant | payoff | broken | due | plan, ep, title }] */
function fsMarks(x) {
  const out = [];
  // 심은 화에 걸린 문장이 없으면 심은 화를 첫 점으로 둔다 (뒤에 건 문장은 다시 떠올림)
  const plants = x.plants.some((c) => c.episode === x.planted_ep) ? x.plants : [{ episode: x.planted_ep }, ...x.plants];
  plants.forEach((c, i) => out.push({ kind: c.broken ? 'broken' : 'plant', ep: c.episode, title: `${c.episode}화 ${c.broken ? '문장이 사라짐' : i ? '다시 떠올림' : '심음'}` }));
  const pays = x.payoffs.length ? x.payoffs : x.payoff_ep ? [{ episode: x.payoff_ep }] : [];
  pays.forEach((c) => out.push({ kind: c.broken ? 'broken' : 'payoff', ep: c.episode, title: `${c.episode}화 ${c.broken ? '문장이 사라짐' : '회수'}` }));
  if (x.status === 'open') {
    if (x.due_ep) out.push({ kind: 'due', ep: x.due_ep, title: `${x.due_ep}화 회수 예정` });
    x.planned.forEach((n) => out.push({ kind: 'plan', ep: n, title: `${n}화 플롯에서 회수` }));
  }
  return out;
}

/** 줄 끝 한마디와 색: [글, '' | 'warn' | 'bad'] */
function fsFlag(x, done) {
  if (x.broken) return [`끊어진 연결 ${x.broken}`, 'bad'];
  if (x.status === 'resolved') return [`${x.payoff_ep}화 회수`, ''];
  if (x.overdue) return [`예정 ${x.due_ep}화 지남`, 'warn'];
  if (x.stale) return [`${done - x.last_seen}화째 묵음`, 'warn'];
  if (x.planned.length) return [`${x.planned[0]}화 플롯에서 회수`, ''];
  if (x.due_ep) return [`예정 ${x.due_ep}화`, ''];
  return [`마지막 등장 ${x.last_seen}화`, ''];
}

/** 목차 꼬리 글: 짧게 */
function fsTail(x) {
  if (x.status === 'resolved') return x.broken ? '끊어짐' : `${x.payoff_ep}화 회수`;
  if (x.broken) return '끊어짐';
  if (x.overdue) return '예정 지남';
  if (x.stale) return '묵음';
  if (x.planned.length) return `${x.planned[0]}화 회수`;
  return `${x.planted_ep}화~`;
}

/** 손볼 것 줄: 끊어진 연결 → 예정 지남 → 오래 묵음 차례. 줄마다 할 일 하나. kind bad | warn */
function fsTodo(c) {
  const rows = [];
  c.items.forEach((x) => {
    const gone = [...x.plants, ...x.payoffs].filter((q) => q.broken).map((q) => q.episode);
    if (gone.length) {
      const eps = [...new Set(gone)].sort((a, b) => a - b);
      rows.push({ order: 0, id: x.id, d: x.description, label: '끊어진 연결', kind: 'bad', why: `${eps.join(', ')}화 본문을 고쳐 걸어 둔 문장이 사라졌어요`, act: `${eps[0]}화에서 다시 걸기`, go: 'write', ep: eps[0] });
    }
  });
  c.items.filter((x) => x.status === 'open' && x.overdue).forEach((x) => rows.push({ order: 1, id: x.id, d: x.description, label: '예정 지남', kind: 'warn',
    why: `${x.due_ep}화에 회수할 예정이었어요. 지금 ${c.done}화까지 반영했어요`, act: '예정 화 바꾸기', go: 'edit' }));
  c.items.filter((x) => x.status === 'open' && x.stale && !x.overdue).forEach((x) => rows.push({ order: 2, id: x.id, d: x.description, label: '오래 묵음', kind: 'warn',
    why: `${x.last_seen}화 뒤로 ${c.done - x.last_seen}화째 다시 나오지 않았어요`, act: '보기', go: 'view' }));
  return rows.sort((a, b) => a.order - b.order);
}

/** 목차 줄. [{ id, d, tail, warn, cur }]. 열린 복선 다음에 회수한 복선(펼쳤을 때만) */
function fsTocRows(c, cur) {
  const row = (x) => ({ id: x.id, d: x.description, tail: fsTail(x), warn: fsAttention(x), cur: x.id === cur, done: x.status === 'resolved' });
  return { open: c.items.filter((x) => x.status === 'open').map(row), resolved: c.items.filter((x) => x.status === 'resolved').map(row) };
}

/** 한 복선의 흐름: 걸린 문장 · 지금 · 앞으로 할 일을 화 차례로. plots 는 { 화: { status, title } }.
    항목: { ep, kind, label, quote?, by?, broken?, future?, now?, late?, plot? } */
function fsFlow(x, done, plots = {}) {
  const out = [];
  const clues = [...x.plants.map((q) => ({ ...q, k: 'plant' })), ...x.payoffs.map((q) => ({ ...q, k: 'payoff' }))]
    .sort((a, b) => a.episode - b.episode || (a.k === 'payoff') - (b.k === 'payoff'));
  const bare = !x.plants.some((q) => q.episode === x.planted_ep);
  let planted = bare;  // 심은 화에 걸린 문장이 없으면 그 화가 '심음'이고, 걸린 문장은 모두 다시 떠올림
  clues.forEach((q) => {
    const first = q.k === 'plant' && !planted;
    if (q.k === 'plant') planted = true;
    out.push({ ep: q.episode, kind: q.broken ? 'broken' : q.k, label: q.broken ? '본문에서 사라진 문장' : q.k === 'payoff' ? '회수' : first ? '심음' : '다시 떠올림', quote: q.quote, by: q.by, broken: q.broken });
  });
  if (bare) out.push({ ep: x.planted_ep, kind: 'plant', label: '심음', bare: true });
  if (x.status === 'resolved' && !x.payoffs.length && x.payoff_ep) out.push({ ep: x.payoff_ep, kind: 'payoff', label: '회수', bare: true });
  if (x.status === 'open') {
    if (done) out.push({ ep: done, kind: 'now', label: `지금 · ${done}화까지 반영했어요`, now: true });
    x.planned.forEach((n) => out.push({ ep: n, kind: 'plan', label: '회수 예정', future: true, plot: plots[n] || null }));
    if (x.due_ep && !x.planned.includes(x.due_ep)) {
      out.push(x.due_ep <= done  // 예정 화까지 반영했는데 회수하지 않았다 (center() 의 overdue 와 같은 규칙)
        ? { ep: x.due_ep, kind: 'due', label: '회수 예정 화가 지났어요', late: true }
        : { ep: x.due_ep, kind: 'due', label: '회수 예정 화', future: true });
    }
  }
  const rank = (e) => (e.now ? 1 : e.future ? 2 : 0);
  return out.sort((a, b) => a.ep - b.ep || rank(a) - rank(b));
}

/** 앞으로 회수할 것: 플롯에 회수 계획이 있는 화, 회수 예정 화인데 플롯에 없는 복선. [{ ep, kind: plot | due, items: [{ id, d }] }] */
function fsAhead(c) {
  const by = new Map();
  const add = (n, kind, x) => {
    const k = `${n}:${kind}`;
    if (!by.has(k)) by.set(k, { ep: n, kind, items: [] });
    by.get(k).items.push({ id: x.id, d: x.description });
  };
  c.items.filter((x) => x.status === 'open').forEach((x) => {
    x.planned.forEach((n) => add(n, 'plot', x));
    if (x.due_ep && x.due_ep > c.done && !x.planned.includes(x.due_ep)) add(x.due_ep, 'due', x);
  });
  return [...by.values()].sort((a, b) => a.ep - b.ep || (a.kind === 'due') - (b.kind === 'due'));
}

/** 축 눈금: 겹치지 않게 가까운 것은 뺀다(지금 화는 남긴다). [{ ep, label, cls }] */
function fsTicks(eps, last, done) {
  const want = [...new Set(eps.filter((n) => n >= 1 && n <= last))].sort((a, b) => a - b);
  const gap = Math.max(1, (last - 1) * 0.07);
  const keep = [];
  want.forEach((n) => {
    const prev = keep[keep.length - 1];
    if (prev !== undefined && n - prev < gap) {
      if (n === done) keep[keep.length - 1] = n;  // 지금 화가 이긴다
      return;
    }
    keep.push(n);
  });
  return keep.map((n, i) => ({ ep: n, label: n === done ? `${n}화 지금` : `${n}화`,
    cls: ['tk', n === done ? 'now' : '', i === 0 && n === 1 ? 'first' : '', n === last && i === keep.length - 1 && i > 0 ? 'last' : ''].filter(Boolean).join(' ') }));
}

/** 걸기 칸 후보: 찾는 말이 있으면 맞는 것 모두(열린 것 먼저), 없으면 n화 가까이 나온 복선 FS_PICK_MAX 개(열린 것 먼저).
    p 는 { foreshadows, foreshadow_clues }. { rows: [{ id, d, open, planted, seen, payoff }], more } */
function fsCandidates(p, n, q = '') {
  const seen = {};
  (p.foreshadow_clues || []).forEach((c) => { if (c.kind === 'plant') seen[c.foreshadow] = Math.max(seen[c.foreshadow] || 0, c.episode); });
  const norm = (s) => String(s || '').toLowerCase().replace(/\s+/g, '');
  const want = norm(q);
  const all = (p.foreshadows || []).map((f) => ({ id: f.id, d: f.description, open: f.status === 'open', planted: f.planted_ep,
    seen: Math.max(f.planted_ep, seen[f.id] || 0), payoff: f.payoff_ep || 0 }));
  const near = (x) => Math.min(Math.abs(x.seen - n), Math.abs(x.planted - n));
  const rows = all.filter((x) => !want || norm(x.d).includes(want))
    .sort((a, b) => (b.open - a.open) || (near(a) - near(b)) || (b.planted - a.planted));
  const cap = want ? rows.length : FS_PICK_MAX;
  return { rows: rows.slice(0, cap), more: Math.max(0, rows.length - cap) };
}

// ----- 그리기 -----

const fsSymHtml = (kind) => `<span class="fs-sym ${kind}" aria-hidden="true"></span>`;

function fsLegend(c) {
  return `<div class="fs-legend"><span>${fsSymHtml('plant')}심거나 다시 떠올린 문장</span><span>${fsSymHtml('payoff')}회수한 문장</span><span>${fsSymHtml('broken')}본문에서 사라진 문장</span>
    <span>${fsSymHtml('due')}회수 예정 화</span><span>${fsSymHtml('plan')}플롯에서 회수</span>${c.done ? `<span>세로선 ${c.done}화 (마지막 반영)</span>` : ''}</div>`;
}

function fsBandSpans(bands, last, cls) {
  return bands.map((b, i) => `<span class="${cls}${cls === 'band' && i % 2 ? ' odd' : ''}" style="left:${fsAt(b.s, last)};width:calc(${fsAt(Math.min(b.e, last), last)} - ${fsAt(b.s, last)})"${cls === 'arc' ? ` title="${esc(b.label)} (${b.s}~${b.e}화)"` : ''}>${cls === 'arc' ? esc(b.label) : ''}</span>`).join('');
}

/** 줄 하나의 축 (지도 줄 · 복선 머리 카드) */
function fsTrack(x, c, bands) {
  const last = c.last_ep;
  const end = x.status === 'resolved' ? (x.payoff_ep || x.last_seen) : Math.max(c.done, x.last_seen);
  const marks = fsMarks(x).map((m) => `<span class="m ${m.kind}" style="left:${fsAt(m.ep, last)}" title="${esc(m.title)}">${fsSymHtml(m.kind)}</span>`).join('');
  return `<span class="fs-trk" aria-hidden="true">${fsBandSpans(bands, last, 'band')}
    <span class="bar${x.status === 'resolved' ? ' done' : ''}" style="left:${fsAt(x.planted_ep, last)};width:calc(${fsAt(end, last)} - ${fsAt(x.planted_ep, last)})"></span>
    ${c.done ? `<span class="now" style="left:${fsAt(c.done, last)}"></span>` : ''}${marks}</span>`;
}

/** 축 머리: 띠 이름(arcs)과 화 눈금(ticks). 둘 다면 띠 이름 아래에 눈금 */
function fsScale(c, bands, eps, mode = 'both') {
  const ticks = mode === 'arcs' ? '' : fsTicks(eps, c.last_ep, c.done).map((t) => `<span class="${t.cls}" style="left:${fsAt(t.ep, c.last_ep)}">${t.label}</span>`).join('');
  return `<span class="fs-scale${mode === 'both' ? '' : ` ${mode}`}" aria-hidden="true">${mode === 'ticks' ? '' : fsBandSpans(bands, c.last_ep, 'arc')}${ticks}</span>`;
}

function fsToc(c) {
  const t = fsTocRows(c, S.fsSel);
  const todo = fsTodo(c).length;
  const doneOpen = S.fsDoneOpen || t.resolved.some((r) => r.cur);  // 회수한 복선을 보는 동안은 그 묶음을 편다
  const item = (r) => `<a class="outline-item" href="${fsHref(r.id)}"${r.cur ? ' aria-current="page"' : ''}><span class="mk">${fsSymHtml(r.warn ? 'warnd' : r.done ? 'okd' : 'opend')}</span><span class="tl">${esc(r.d)}</span><span class="st${r.warn ? ' warn' : ''}">${esc(r.tail)}</span></a>`;
  const body = [
    `<a class="outline-item" href="${fsHref('')}"${S.fsSel ? '' : ' aria-current="page"'}><span class="tl">개요</span></a>`,
    todo ? `<button type="button" class="outline-item warn" data-action="fsGoTodo"><span class="tl">손볼 것</span><span class="st">${todo}</span></button>` : '',
    t.open.length ? `<span class="outline-h">열린 복선 ${t.open.length}</span>${t.open.map(item).join('')}` : '',
    t.resolved.length ? `<div class="outline-sep"></div><button type="button" class="outline-item" data-action="fsDoneToggle" data-outline-keep aria-expanded="${doneOpen}"><span class="mk">${fsSymHtml('okd')}</span><span class="tl">회수한 복선</span><span class="st">${t.resolved.length} ${doneOpen ? '▾' : '▸'}</span></button>${doneOpen ? t.resolved.map(item).join('') : ''}` : '',
  ].join('');
  const cur = c.items.find((x) => x.id === S.fsSel);
  return outlineNav({ id: 'fs-toc', label: '복선 목차', now: cur ? esc(cur.description) : '개요', body });
}

function fsStats(c) {
  const todo = fsTodo(c);
  const n = (k) => todo.filter((r) => r.label === k).length;
  const plan = c.items.filter((x) => x.status === 'open' && x.planned.length).length;
  const parts = [['끊어짐', n('끊어진 연결')], ['예정 지남', n('예정 지남')], ['묵음', n('오래 묵음')]].filter(([, k]) => k).map(([l, k]) => `${l} ${k}`);
  return `<section class="card"><div class="fs-stats">
      <div><span class="small">복선</span><span class="num">${c.total}</span><span class="small">회수 ${c.resolved}</span></div>
      <div><span class="small">열림</span><span class="num">${c.open}</span><span class="small">플롯에 회수 계획 ${plan}</span></div>
      <div><span class="small">회수율</span><span class="num">${c.rate == null ? '-' : `${Math.round(c.rate * 100)}%`}</span><div class="meter" aria-hidden="true"><i style="left:0;width:${(c.rate || 0) * 100}%"></i></div></div>
      <div><span class="small">손볼 것</span><span class="num${todo.length ? ' warn' : ''}">${todo.length}</span><span class="small">${parts.join(' · ') || '없어요'}</span></div>
    </div></section>`;
}

function fsTodoCard(c) {
  const rows = fsTodo(c);
  if (!rows.length) return '';
  const act = (r) => (r.go === 'write'
    ? `<a class="btn small" href="${base()}/write/${r.ep}">${r.act}</a>`
    : r.go === 'edit' ? `<button type="button" class="btn small" data-action="fsDueGo" data-arg="${esc(r.id)}">${r.act}</button>`
      : `<a class="btn small" href="${fsHref(r.id)}">${r.act}</a>`);
  const broken = rows.filter((r) => r.go === 'write').length;
  return `<section class="card" id="fs-todo" tabindex="-1">
    <div class="fs-head"><h2>손볼 것 ${rows.length}</h2>${broken ? `<button type="button" class="btn small" data-action="fsPrune">끊어진 연결 ${c.broken}개 정리</button>` : ''}</div>
    <div class="fs-todo">${rows.map((r) => `<div class="fs-todo-row"><span><span class="chip ${r.kind}">${r.label}</span></span>
      <div><a class="t" href="${fsHref(r.id)}">${esc(r.d)}</a><span class="small">${r.why}</span></div>${act(r)}</div>`).join('')}</div></section>`;
}

function fsMapCard(c, bands) {
  const inTab = (x) => S.fsTab === 'all' || x.status === S.fsTab;
  const items = c.items.filter((x) => inTab(x) && (!S.fsScope || x.scope === S.fsScope));
  const seg = (k, l) => `<button type="button" aria-pressed="${S.fsTab === k}" data-action="fsTab" data-arg="${k}">${l}</button>`;
  const scopes = [...new Set(c.items.map((x) => x.scope))];
  const scopeSeg = scopes.length > 1 ? `<div class="seg" role="group" aria-label="회수 범위"><button type="button" aria-pressed="${!S.fsScope}" data-action="fsScope" data-arg="">모든 범위</button>${Object.entries(FS_SCOPE).filter(([k]) => scopes.includes(k)).map(([k, v]) => `<button type="button" aria-pressed="${S.fsScope === k}" data-action="fsScope" data-arg="${k}">${v}</button>`).join('')}</div>` : '';
  const counts = { open: c.open, resolved: c.resolved, all: c.total };
  const names = { open: '열린', resolved: '회수한', all: '전체' };
  const elsewhere = Object.keys(names).filter((k) => k !== S.fsTab && counts[k])
    .map((k) => `<button type="button" class="link-btn" data-action="fsTab" data-arg="${k}">${names[k]} ${counts[k]}개</button>`);
  const empty = S.fsScope && c.items.some(inTab)
    ? `${FS_SCOPE[S.fsScope]} 범위에는 해당하는 복선이 없어요. 범위를 '모든 범위'로 바꿔 보세요.`
    : `${names[S.fsTab]} 복선이 없어요.${elsewhere.length ? ` 다른 거르기: ${elsewhere.join(' · ')}` : ''}`;
  const rows = items.map((x) => {
    const [fl, cls] = fsFlag(x, c.done);
    return `<a class="fs-row" href="${fsHref(x.id)}"><span class="lb">${fsSymHtml(fsAttention(x) ? 'warnd' : x.status === 'resolved' ? 'okd' : 'opend')}<span class="t">${esc(x.description)}</span></span>
      ${fsTrack(x, c, bands)}<span class="fs-fl${cls ? ` ${cls}` : ''}">${fl}</span></a>`;
  }).join('');
  const ends = [1, c.done, c.last_ep].filter(Boolean);
  return `<section class="card">
    <div class="fs-head"><h2>복선 지도</h2><div class="row"><div class="seg" role="group" aria-label="보이는 복선">${seg('open', `열림 ${c.open}`)}${seg('resolved', `회수 ${c.resolved}`)}${seg('all', `전체 ${c.total}`)}</div>${scopeSeg}</div></div>
    ${fsLegend(c)}
    ${rows ? `<div class="fs-map"><div class="fs-axis"><span class="lb small">심은 차례</span>${fsScale(c, bands, ends)}<span class="fs-fl"></span></div>${rows}</div>` : `<p class="small">${empty}</p>`}</section>`;
}

function fsAheadCard(c) {
  const rows = fsAhead(c);
  if (!rows.length) return '';
  const st = (n) => { const e = P().episodes.find((x) => x.plot.number === n); return e ? statusChip(e.status) : ''; };
  return `<section class="card"><div class="fs-head"><h2>앞으로 회수할 것</h2><span class="small">플롯의 '회수할 복선'과 회수 예정 화</span></div>
    <dl class="pf-dl">${rows.map((r) => `<dt>${r.ep}화 ${r.kind === 'plot' ? '플롯' : '예정'}</dt><dd><span class="row">${r.items.map((x) => `<a href="${fsHref(x.id)}">${esc(x.d)}</a>`).join('<span class="small">·</span>')}
      ${r.kind === 'plot' ? `<a class="small" href="${base()}/arc/${r.ep}">플롯 보기</a>${st(r.ep)}` : '<span class="chip warn">플롯에 아직 없음</span>'}</span></dd>`).join('')}</dl></section>`;
}

function fsAddForm(c) {
  if (!S.fsAdd) return '';
  return `<section class="card pf-sec editing" id="fs-add" tabindex="-1">
    <div class="pf-head"><h2>복선 직접 더하기 <span class="small pf-state">고치는 중</span></h2></div>
    <p class="small">본문 문장 없이 계획만 적어 둘 수도 있어요. 문장을 함께 걸려면 집필 화면에서 문장을 골라 '복선으로'를 누르세요.</p>
    <div class="fs-edit"><div class="field"><label for="fs-new-d">내용</label><input id="fs-new-d" type="text" placeholder="예: 서윤의 목걸이에 새겨진 문양"></div>
      <div class="field"><label for="fs-new-s">회수 범위</label><select id="fs-new-s">${Object.entries(FS_SCOPE).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></div>
      <div class="field"><label for="fs-new-u">회수 예정 화</label><input id="fs-new-u" type="number" min="1" placeholder="미정"></div></div>
    <div class="row"><div class="field"><label for="fs-new-e">심은 화</label><input id="fs-new-e" type="number" min="1" value="${Math.max(c.done, 1)}"></div></div>
    <div class="row"><button type="button" class="btn small" data-action="fsAddToggle">취소</button><button type="button" class="btn small primary" data-action="fsCreate">더하기</button></div></section>`;
}

/** 복선이 놓인 범위의 이름: 이번 아크 · 이번 부는 심은 화가 든 아크 · 부 */
function fsScopeText(x) {
  const p = P();
  const inside = (list) => (list || []).find((a) => a.start_ep <= x.planted_ep && x.planted_ep <= a.end_ep);
  if (x.scope === 'arc' && serial()) { const a = inside(p.story_arcs); if (a) return `${FS_SCOPE.arc} <span class="small">아크 ${a.number} · ${esc(a.title)} · ${a.start_ep}~${a.end_ep}화</span>`; }
  if (x.scope === 'part' && serial()) { const a = inside(p.parts); if (a) return `${FS_SCOPE.part} <span class="small">${esc(a.title)} · ${a.start_ep}~${a.end_ep}화</span>`; }
  return FS_SCOPE[x.scope] || esc(x.scope);
}

function fsPlanCard(x, c) {
  const id = esc(x.id);
  const editing = S.fsEdit === x.id;
  const plans = x.planned.map((n) => { const e = P().episodes.find((y) => y.plot.number === n); return `<a href="${base()}/arc/${n}">${n}화${e && e.plot.title ? ` ${esc(e.plot.title)}` : ''}</a>`; });
  const resolving = S.fsResolving === x.id
    ? `<div class="note plain row" role="group" aria-label="회수로 표시"><div class="field"><label for="fs-r-${id}">회수한 화</label><input id="fs-r-${id}" type="number" min="${x.planted_ep}" value="${Math.max(c.done, x.planted_ep)}"></div>
        <button type="button" class="btn small" data-action="fsResolveCancel">취소</button><button type="button" class="btn small primary" data-action="fsResolve" data-arg="${id}">회수로 표시</button></div>` : '';
  const body = editing
    ? `<div class="fs-edit">
        <div class="field"><label for="fs-d-${id}">내용</label><input id="fs-d-${id}" type="text" value="${esc(x.description)}"></div>
        <div class="field"><label for="fs-s-${id}">회수 범위</label><select id="fs-s-${id}">${Object.entries(FS_SCOPE).map(([k, v]) => `<option value="${k}"${x.scope === k ? ' selected' : ''}>${v}</option>`).join('')}</select></div>
        <div class="field"><label for="fs-u-${id}">회수 예정 화</label><input id="fs-u-${id}" type="number" min="${x.planted_ep}" value="${x.due_ep || ''}" placeholder="미정"></div></div>
      <div class="row"><button type="button" class="btn small" data-action="fsEditGo" data-arg="">취소</button><button type="button" class="btn small primary" data-action="fsSave" data-arg="${id}">저장</button></div>`
    : `<dl class="pf-dl"><dt>내용</dt><dd>${esc(x.description)}</dd><dt>회수 범위</dt><dd>${fsScopeText(x)}</dd>
        <dt>${x.status === 'resolved' ? '회수한 화' : '회수 예정 화'}</dt><dd>${x.status === 'resolved' ? `${x.payoff_ep}화` : x.due_ep ? `${x.due_ep}화${x.overdue ? ' <span class="chip warn">지남</span>' : ''}` : '<span class="small">미정</span>'}</dd>
        ${x.status === 'open' ? `<dt>플롯</dt><dd>${plans.length ? `${plans.join(' · ')} <span class="small">회수할 복선에 들어 있어요</span>` : '<span class="small">아직 어느 화 플롯에도 없어요</span>'}</dd>` : ''}</dl>`;
  return `<section class="card pf-sec${editing ? ' editing' : ''}" id="fs-plan" tabindex="-1">
    <div class="pf-head"><h2>회수 계획${editing ? ' <span class="small pf-state">고치는 중</span>' : ''}</h2>${editing ? '' : `<button type="button" class="btn small" data-action="fsEditGo" data-arg="${id}" aria-expanded="false">고치기</button>`}</div>
    ${resolving}${body}</section>`;
}

function fsFlowCard(x, c) {
  const plots = {};
  P().episodes.forEach((e) => { plots[e.plot.number] = { status: e.status, title: e.plot.title }; });
  const flow = fsFlow(x, c.done, plots);
  const clueN = x.plants.length + x.payoffs.length;
  const drop = (e) => `<button type="button" class="btn small ghost" data-action="fsClueDrop" data-arg="${esc(JSON.stringify({ foreshadow: x.id, episode: e.ep, quote: e.quote }))}">연결 지우기</button>`;
  const row = (e) => {
    const sym = e.kind === 'now' ? 'nowd' : e.kind;
    const by = e.by === 'author' ? '작가가 걸음' : e.by === 'ai' ? `AI가 찾음 · ${e.ep}화 상태 승인` : '';
    let bd;
    if (e.now) bd = `<span class="small">${e.label}</span>`;
    else if (e.kind === 'plan') bd = `<div class="k"><strong>${e.label}</strong>${e.plot ? statusChip(e.plot.status) : ''}<span class="small">${e.ep}화 플롯${e.plot && e.plot.title ? ` '${esc(e.plot.title)}'` : ''}의 회수할 복선에 들어 있어요</span></div>
        <div class="row"><a class="btn small ghost" href="${base()}/arc/${e.ep}">${e.ep}화 플롯 보기</a></div>`;
    else if (e.kind === 'due') bd = `<div class="k"><strong>${e.label}</strong><span class="small">${e.late ? `지금 ${c.done}화까지 반영했어요` : '플롯에는 아직 없어요'}</span></div>`;
    else if (e.bare) bd = `<div class="k"><strong>${e.label}</strong><span class="small">걸린 문장 없이 화만 적혀 있어요</span></div>`;
    else if (e.broken) bd = `<div class="k"><strong>${e.label}</strong><span>${e.ep}화 본문을 고친 뒤로 이 문장을 찾지 못해요.</span></div>
        <p class="fs-q cut">${esc(e.quote)}</p><div class="row"><a class="btn small" href="${base()}/write/${e.ep}">${e.ep}화에서 다시 걸기</a>${drop(e)}</div>`;
    else bd = `<div class="k"><strong>${e.label}</strong><span class="small">${by}</span></div><p class="fs-q">${esc(e.quote)}</p>
        <div class="row"><a class="btn small ghost" href="${base()}/write/${e.ep}">${e.ep}화 본문에서 보기</a>${drop(e)}</div>`;
    return `<div class="fs-fi${e.future ? ' future' : ''}${e.now ? ' now' : ''}${e.broken ? ' broken' : ''}${e.late ? ' late' : ''}"><span class="ep">${e.ep}화</span><span class="rail">${fsSymHtml(sym)}</span><div class="bd">${bd}</div></div>`;
  };
  return `<section class="card"><div class="fs-head"><h2>본문에 걸린 문장 ${clueN}</h2><span class="small">지난 일은 실선, 앞으로 할 일은 점선</span></div>
    <div class="fs-flow">${flow.map(row).join('')}</div>
    <p class="note plain">AI가 찾은 문장은 상태 승인에서 고른 것만 들어와요. 집필 화면에서 문장을 골라 '복선으로'를 누르면 여기에 더해져요.</p></section>`;
}

function fsDetail(x, c, bands) {
  const same = c.items.filter((y) => y.status === x.status);
  const where = `복선 센터 · ${x.status === 'open' ? '열린' : '회수한'} 복선 ${same.indexOf(x) + 1} / ${same.length}`;
  const chips = `<span class="row"><span class="chip${x.status === 'resolved' ? ' ok' : ''}">${x.status === 'resolved' ? '회수' : '열림'}</span><span class="chip">${FS_SCOPE[x.scope] || esc(x.scope)}</span>${x.broken ? `<span class="chip bad">끊어진 연결 ${x.broken}</span>` : ''}${x.overdue ? '<span class="chip warn">예정 지남</span>' : ''}${x.stale ? '<span class="chip warn">오래 묵음</span>' : ''}</span>`;
  const more = menuBtn(`fs-more-${x.id}`, '<span aria-hidden="true">⋯</span>', () => `${x.status === 'resolved' ? '<button type="button" class="pop-item" data-action="fsReopen" data-arg="' + esc(x.id) + '">다시 열기<span class="small">회수 문장도 지워요</span></button>' : ''}
      <button type="button" class="pop-item danger" data-action="fsDelete" data-arg="${esc(x.id)}">복선 지우기<span class="small">걸린 문장도 함께</span></button>`, { aria: '복선 더 보기' });
  const busy = S.fsEdit === x.id || S.fsResolving === x.id;
  const primary = x.status === 'open' && !busy ? `<button type="button" class="btn primary" data-action="fsResolveGo" data-arg="${esc(x.id)}">회수로 표시</button>` : '';
  const when = x.status === 'resolved'
    ? `${x.planted_ep}화에 심음 · ${x.payoff_ep}화 회수`
    : `${x.planted_ep}화에 심음 · 마지막 등장 ${x.last_seen}화${x.planned.length ? ` · ${x.planned.join(', ')}화 플롯에서 회수` : ''}${x.due_ep ? ` · 회수 예정 ${x.due_ep}화` : ''}`;
  const eps = [x.planted_ep, ...fsMarks(x).map((m) => m.ep), c.done].filter(Boolean);
  const head = header(where, x.description, chips, `${more}${primary}`);
  const main = `<div class="fs-col">
    <section class="card"><p class="desc">${when}</p>
      ${fsScale(c, bands, [], 'arcs')}${fsTrack(x, c, bands)}${fsScale(c, bands, eps, 'ticks')}</section>
    ${fsFlowCard(x, c)}${fsPlanCard(x, c)}</div>`;
  return `${head}${outlineDoc(fsToc(c), main, { wide: true, cls: 'fs-wrap' })}`;
}

function viewForeshadow() {
  const addBtn = `<button type="button" class="btn primary" data-action="fsAddToggle" aria-expanded="${S.fsAdd}">+ 복선 더하기</button>`;
  const c = S.fs;
  const head = (right) => header('작품 도구', '복선 센터', '복선마다 본문 어느 문장에 심고 회수했는지 봐요. 지도의 줄을 누르면 그 복선 쪽이 열려요.', right);
  if (!c) return `${head('')}<div class="small">불러오는 중…</div>`;
  if (c.error) return `${head('')}<div class="note err">${esc(c.error)}</div>`;
  if (!c.total) {
    return `${head('')}${S.fsAdd ? fsAddForm(c) : `<section class="card fs-empty"><div class="empty">
      <p>아직 복선이 없어요. 플롯에 적은 '심을 복선'은 상태 승인에서 반영하면 여기에 모여요. 본문 문장을 골라 '복선으로'를 눌러도 돼요.</p>
      <button type="button" class="btn primary" data-action="fsAddToggle">+ 복선 더하기</button></div></section>`}`;
  }
  const bands = fsBands(P());
  const sel = S.fsSel && c.items.find((x) => x.id === S.fsSel);
  if (sel) return fsDetail(sel, c, bands);
  const lost = S.fsSel ? `<div class="note warn" role="status">'${esc(S.fsSel)}' 복선을 찾지 못했어요. 지워졌을 수 있어요.</div>` : '';
  const main = `<div class="fs-col">${lost}${fsAddForm(c)}${fsStats(c)}${fsTodoCard(c)}${fsMapCard(c, bands)}${fsAheadCard(c)}</div>`;
  return `${head(S.fsAdd ? '' : addBtn)}${outlineDoc(fsToc(c), main, { wide: true, cls: 'fs-wrap' })}`;
}

/** 화 상태 칩 (README '화 상태 칩') */
function statusChip(st) {
  const name = { draft: '초안', confirmed: '확정', written: '작성됨', finalized: '반영 완료' }[st];
  return name ? `<span class="chip ${st}">${name}</span>` : '';
}

// ----- 본문에서 고른 문장을 복선에 걸기: 떠 있는 도구(#sel-tool)의 mode 'foreshadow' -----
// S.selTool = { n, start, text, mode: 'foreshadow', read?, rect?, way: 'pick' | 'new', q, fid, kind, desc, scope, due }

function fsPickList(t) {
  const { rows, more } = fsCandidates(P(), t.n, t.q);
  if (!rows.length) return `<div class="none">${t.q ? `'${esc(t.q)}'와 맞는 복선이 없어요. '+ 새 복선'으로 심을 수 있어요.` : '아직 복선이 없어요.'}</div>`;
  const line = (x) => `<label><input type="radio" name="fs-pick" value="${esc(x.id)}"${t.fid === x.id ? ' checked' : ''}><span class="dd">${esc(x.d)}</span><span class="chip${x.open ? '' : ' ok'}">${x.open ? '열림' : '회수'}</span>
      <span class="s">${x.planted}화에 심음 · ${x.open ? `마지막 등장 ${x.seen}화` : `${x.payoff}화 회수`}</span></label>`;
  return `${t.q ? '' : `<div class="h">${t.n}화 가까이 나온 복선</div>`}${rows.map(line).join('')}${more ? `<div class="none">${more}개 더 있어요. 찾기로 좁혀 보세요.</div>` : ''}`;
}

/** 걸기 칸 HTML. 찾는 칸에 칠 때는 목록(#fs-pick-list)만 다시 그린다 */
function fsLinkHtml(t) {
  const pick = t.way === 'pick';
  const seg = (k, l) => `<button type="button" aria-pressed="${t.way === k}" data-action="fsLinkWay" data-arg="${k}">${l}</button>`;
  const kind = (k, l) => `<button type="button" aria-pressed="${t.kind === k}" data-action="fsLinkKind" data-arg="${k}">${l}</button>`;
  return `<div class="between"><strong>${t.n}화 문장을 복선에 걸기</strong><span class="small">바로 저장돼요</span></div>
    <blockquote class="qq">${esc(clip(t.text, 200))}</blockquote>
    <div class="seg" role="group" aria-label="걸 곳">${seg('pick', '이미 있는 복선')}${seg('new', '+ 새 복선')}</div>
    ${pick ? `<div class="field"><label for="fs-find">복선 찾기</label><input id="fs-find" type="search" value="${esc(t.q)}" placeholder="복선 내용으로 찾기" autocomplete="off"></div>
      <div class="fs-pick" id="fs-pick-list" role="radiogroup" aria-label="복선">${fsPickList(t)}</div>
      <div class="seg" role="group" aria-label="이 문장은">${kind('plant', '심음 · 다시 떠올림')}${kind('payoff', '회수')}</div>`
    : `<div class="field"><label for="fs-pick-d">무엇을 암시하나요</label><input id="fs-pick-d" type="text" value="${esc(t.desc)}" placeholder="무엇을 암시하는지 한 줄로"></div>
      <div class="grid-2"><div class="field"><label for="fs-pick-s">회수 범위</label><select id="fs-pick-s">${Object.entries(FS_SCOPE).map(([k, v]) => `<option value="${k}"${t.scope === k ? ' selected' : ''}>${v}</option>`).join('')}</select></div>
        <div class="field"><label for="fs-pick-u">회수 예정 화</label><input id="fs-pick-u" type="number" min="${t.n}" value="${esc(t.due)}" placeholder="미정"></div></div>
      <p class="small">${t.n}화에 심은 복선으로 더해요. 복선 센터에서 언제든 고칠 수 있어요.</p>`}
    <div class="foot"><button type="button" class="btn small" data-action="selCancel">취소</button><button type="button" class="btn small primary" data-action="fsLinkSave">${pick ? '걸기' : '심기'}</button></div>`;
}

/** 걸기 칸을 띄운다. 고치는 본문은 placeTool, 읽기 전용 본문은 고른 자리(rect) 아래에 둔다 */
function fsLinkShow(focus = true) {
  const t = S.selTool;
  const el = toolEl();
  el.classList.remove('finding');
  el.classList.add('edit', 'fs-link');
  el.setAttribute('aria-label', '복선에 걸기');
  el.innerHTML = fsLinkHtml(t);
  el.hidden = false;
  const ta = !t.read && document.querySelector(`textarea[data-draft="${t.n}"]`);
  if (ta) placeTool(ta, t);
  else if (t.rect) {  // t.rect 는 페이지 좌표라 다시 그려도(Seg 를 바꿔도) 같은 자리
    const w = el.offsetWidth || 400;
    const h = el.offsetHeight || 400;
    let y = t.rect.bottom + 8;
    if (y - window.scrollY + h > window.innerHeight && t.rect.top - window.scrollY - h - 8 >= 0) y = t.rect.top - h - 8;
    el.style.left = `${Math.min(Math.max(window.scrollX + 8, t.rect.left), window.scrollX + document.documentElement.clientWidth - w - 8)}px`;
    el.style.top = `${y}px`;
  }
  if (focus) (t.way === 'pick' ? $('#fs-find') : $('#fs-pick-d'))?.focus({ preventScroll: true });
}

/** 걸기 칸을 연다. 복선이 하나도 없으면 새 복선으로 */
function fsLinkOpen(sel) {
  const p = P();
  const way = p.foreshadows.length ? 'pick' : 'new';
  const first = fsCandidates(p, sel.n).rows[0];
  const r = sel.rect;
  const rect = r ? { left: r.left + window.scrollX, top: r.top + window.scrollY, bottom: r.bottom + window.scrollY } : null;
  S.selTool = { n: sel.n, start: sel.start, text: sel.text, mode: 'foreshadow', read: !!sel.read, rect,
    way, q: '', fid: first ? first.id : '', kind: 'plant', desc: '', scope: 'arc', due: '' };
  fsLinkShow();
}

// 떠 있는 도구: mode 'foreshadow' 면 걸기 칸, 고치는 본문의 메뉴(mode 'menu')에는 끝에 '복선으로'
const fsShowTool = showTool;
showTool = function showToolWithForeshadow() {
  const t = S.selTool;
  if (t && t.mode === 'foreshadow') return fsLinkShow();
  document.getElementById('sel-tool')?.classList.remove('fs-link');
  fsShowTool();
  const el = document.getElementById('sel-tool');
  const ta = t && document.querySelector(`textarea[data-draft="${t.n}"]`);
  if (!ta || !el || el.hidden || t.mode !== 'menu') return;
  el.insertAdjacentHTML('beforeend', '<button type="button" class="btn small" data-action="selForeshadow" title="이 문장을 복선을 심거나 회수한 자리로 걸어요">복선으로 걸기</button>');
  placeTool(ta, t);
};

// 닫으면 걸기 칸 모양을 뗀다 (다음에 뜨는 메뉴 도구가 넓게 뜨지 않게)
const fsHideTool = hideTool;
hideTool = function hideToolWithForeshadow() {
  fsHideTool();
  document.getElementById('sel-tool')?.classList.remove('fs-link');
};

// 읽기 전용 본문 도구(illust.js ilTool)에도 '복선으로'. 도구를 만들 때 붙여 마우스 · 터치 · Shift+방향키 어느 길로 떠도 있다.
// illust.js 는 index.html 에서 이 파일보다 먼저 읽는다. ilTool() 다음에 너비를 재므로 자리 잡기도 버튼을 센다
if (typeof ilTool === 'function') {
  const fsIlTool = ilTool;
  ilTool = function ilToolWithForeshadow() {
    const el = fsIlTool();
    if (!el.querySelector('[data-action="fsFromRead"]')) el.insertAdjacentHTML('beforeend', '<button type="button" class="btn small" data-action="fsFromRead">복선으로 걸기</button>');
    return el;
  };
}

document.addEventListener('input', (e) => {
  const t = S.selTool;
  if (!t || t.mode !== 'foreshadow') return;
  if (e.target.id === 'fs-find') {
    t.q = e.target.value;
    const { rows } = fsCandidates(P(), t.n, t.q);
    if (!rows.some((x) => x.id === t.fid)) t.fid = rows[0] ? rows[0].id : '';
    const list = $('#fs-pick-list');
    if (list) list.innerHTML = fsPickList(t);
  }
  if (e.target.id === 'fs-pick-d') t.desc = e.target.value;
  if (e.target.id === 'fs-pick-u') t.due = e.target.value;
});

document.addEventListener('change', (e) => {
  const t = S.selTool;
  if (!t || t.mode !== 'foreshadow') return;
  if (e.target.name === 'fs-pick') t.fid = e.target.value;
  if (e.target.id === 'fs-pick-s') t.scope = e.target.value;
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.isComposing && S.selTool && S.selTool.mode === 'foreshadow' && (e.target.id === 'fs-pick-d' || e.target.id === 'fs-find')) {
    e.preventDefault();
    actions.fsLinkSave();
  }
});

async function fsLinkSave() {
  const t = S.selTool;
  if (!t || t.mode !== 'foreshadow') return;
  const pick = t.way === 'pick';
  if (pick && !t.fid) return toast('걸 복선을 골라 주세요', true);
  if (!pick && !t.desc.trim()) return toast('새 복선 내용을 적어 주세요', true);
  const body = { episode: t.n, quote: t.text, foreshadow: pick ? t.fid : '', description: pick ? '' : t.desc.trim(),
    kind: pick ? t.kind : 'plant', scope: t.scope, due_ep: !pick && Number(t.due) ? Number(t.due) : null };
  await run('복선에 거는 중', async () => {
    await saveIfDirty();
    if (typeof flushText === 'function' && !t.read) await flushText(body.episode);
    S.project = await api('POST', `/projects/${enc(S.name)}/foreshadows/clues`, body);
    hideTool();  // 저장한 뒤에 닫는다. 서버가 막으면 칸과 쓰던 글이 남는다
    if (S.fs) await fsLoad(S.fsSel);
    toast(body.kind === 'payoff' ? '회수한 문장으로 걸었어요' : '복선에 걸었어요. 복선 센터에서 볼 수 있어요');
  });
}

async function fsCall(label, method, path, body) {
  await run(label, async () => {
    await saveIfDirty();
    S.project = await api(method, `/projects/${enc(S.name)}/foreshadows${path}`, body);
    await fsLoad(S.fsSel);
  });
}

Object.assign(actions, {
  selForeshadow() {
    const t = S.selTool;
    if (!t) return;
    fsLinkOpen({ n: t.n, start: t.start, text: t.text });
  },
  fsFromRead() {
    const s = S.illPending;
    if (typeof hideIlTool === 'function') hideIlTool();
    window.getSelection()?.removeAllRanges();
    if (!s) return;
    fsLinkOpen({ n: s.n, start: s.start, text: s.text, read: true, rect: s.rect });
  },
  fsLinkWay(w) {
    const t = S.selTool;
    if (!t || t.mode !== 'foreshadow') return;
    t.way = w;
    fsLinkShow();
  },
  fsLinkKind(k) {
    const t = S.selTool;
    if (!t || t.mode !== 'foreshadow') return;
    t.kind = k;
    fsLinkShow(false);
    $(`#sel-tool [data-action="fsLinkKind"][data-arg="${k}"]`)?.focus();
  },
  fsLinkSave() { fsLinkSave(); },
  fsTab(k) { S.fsTab = k; S.fsTabPicked = S.name; render(); },
  fsScope(k) { S.fsScope = k; render(); },
  fsDoneToggle() { S.fsDoneOpen = !S.fsDoneOpen; render(); },
  fsGoTodo() {
    S.focusTarget = '#fs-todo';
    if (S.fsSel) location.hash = fsHref('');
    else render();
  },
  fsAddToggle() {
    S.fsAdd = !S.fsAdd;
    if (S.fsAdd) S.focusTarget = '#fs-new-d';
    render();
  },
  fsEditGo(id, field = 'd') {
    const prev = S.fsEdit;
    S.fsEdit = id;
    S.fsResolving = '';
    if (id) S.focusTarget = `#fs-${field}-${CSS.escape(id)}`;
    else if (prev) S.focusTarget = `#fs-plan [data-action="fsEditGo"][data-arg="${CSS.escape(prev)}"]`;  // 취소하면 '고치기'로
    if (id && S.fsSel !== id) location.hash = fsHref(id);
    else render();
  },
  fsResolveGo(id) {
    S.fsResolving = id;
    S.fsEdit = '';
    S.focusTarget = `#fs-r-${CSS.escape(id)}`;
    render();
  },
  fsDueGo(id) { actions.fsEditGo(id, 'u'); },  // 손볼 것의 '예정 화 바꾸기': 예정 화 칸으로
  fsResolveCancel() {
    const prev = S.fsResolving;
    S.fsResolving = '';
    if (prev) S.focusTarget = `#app [data-action="fsResolveGo"][data-arg="${CSS.escape(prev)}"]`;
    render();
  },
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
    const body = { description: $(`#fs-d-${CSS.escape(id)}`).value.trim(), scope: $(`#fs-s-${CSS.escape(id)}`).value, due_ep: due || null, clear_due: !due };
    S.fsEdit = '';
    fsCall('저장하는 중', 'PUT', `/${enc(id)}`, body);
  },
  fsResolve(id) {
    const n = Number($(`#fs-r-${CSS.escape(id)}`).value);
    S.fsResolving = '';
    fsCall('회수로 표시하는 중', 'POST', `/${enc(id)}/resolve`, { episode: n });
  },
  fsReopen(id) { fsCall('다시 여는 중', 'POST', `/${enc(id)}/reopen`); },
  fsDelete(id) {
    if (!confirm('이 복선과 걸어 둔 문장을 모두 지울까요? 플롯의 회수 계획에서도 빠져요.')) return;
    if (S.fsSel === id) location.hash = fsHref('');
    fsCall('지우는 중', 'DELETE', `/${enc(id)}`);
  },
  fsClueDrop(raw) { fsCall('연결 지우는 중', 'POST', '/clues/remove', JSON.parse(raw)); },
  fsPrune() { fsCall('끊어진 연결 정리하는 중', 'POST', '/prune'); },
});

// ----- 상태 승인 화면 -----

/** AI 가 본문에서 찾은 복선 문장. 고른 것만 반영한다(q 항목). 이번 화에 심거나 회수하는 복선이면 그 항목을 같이 골라야 남는다. */
function fsClueRows(d, box, n) {
  const p = P();
  const label = (fid) => {
    const f = p.foreshadows.find((x) => x.id === fid) || d.foreshadow_planted.find((x) => x.id === fid);
    return f ? f.description : fid;
  };
  return (d.foreshadow_clues || []).map((c, i) => {
    const fresh = d.foreshadow_planted.some((x) => x.id === c.foreshadow);
    const note = c.kind === 'payoff' ? '회수한 문장' : fresh ? '심은 문장' : '다시 떠올린 문장';
    return `<div class="change">${box('q' + i)}<label for="pk-q${i}" class="fs-clue-pick"><span class="chip${c.kind === 'payoff' ? ' ok' : ''}">${note}</span> ${esc(label(c.foreshadow))}
      <div class="fs-q-row">“${esc(c.quote)}”</div></label>${n ? rvQuoteBtn(n, c.quote, `${note} · ${label(c.foreshadow)}`) : ''}</div>`;
  }).join('');
}

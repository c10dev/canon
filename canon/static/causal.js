/* 인과율 화면. app.js 의 S, actions, api, render, menuBtn 과 outline.js 의 공용 목차 틀, chat.js 의 plotDiff 를 쓴다.
   작가가 요소, 특징, 설정, 사건을 언제든 더하고(화면 아래 저장 띠의 작품 저장으로 저장), 요소마다
   관련 화 지도(AI 없이, 서버 elements.links)와 영향 분석(백그라운드 작업 'impact')을 본다.
   화면은 공용 목차 틀이다: 왼쪽 목차(개요 · 손볼 것 · 종류별 요소), 오른쪽은 개요(주소 causal) 또는 요소 하나(causal/<id>).
   요소 하나: 요소 내용(읽기 카드, '고치기'로 그 카드만) → 관련 화(30화씩 칸 줄 + 나눔 버튼으로 거른 줄 목록) → 영향 분석(화별로 묶은 변경안).
   영향 분석의 변경안은 고른 것만 반영한다.
   elBasis 는 서버 elements.basis 와 같은 모양이라 함께 고친다(tests/test_causal_js.py). causalStatus · causalCells 는 순수 함수. */
'use strict';

const EL_KINDS = ['세계 규칙', '장소', '물건', '세력', '인물 특징', '과거 사건', '예정 사건', '기타'];
const EL_KIND_HINT = {
  '세계 규칙': '마법은 해가 진 뒤에만 쓸 수 있다',
  '장소': '폐쇄된 등대의 지하 창고',
  '물건': '녹슨 등대 열쇠',
  '세력': '항구를 쥔 선주 조합',
  '인물 특징': '주인공은 왼손잡이고 피를 보면 손이 떨린다',
  '과거 사건': '10년 전 겨울, 등대지기가 실종됐다',
  '예정 사건': '12화에 마을에 태풍이 온다',
  '기타': '',
};
const FIX_CLASS = { '본문 수정': 'written', '플롯 수정': 'confirmed', '설명 추가': 'ai', '시점 변경': 'draft', '그대로 둠': 'draft' };
const EL_CTX = [['auto', '관련 있을 때'], ['always', '항상'], ['off', '넣지 않음']];
const CZ_CHUNK = 30;  // 관련 화 칸 한 줄의 화 수

Object.assign(S, {
  causalSel: '',      // 주소의 요소 id. 비면 개요
  causalEdit: '',     // 내용을 고치는 요소 id
  causalLinks: {},    // 요소 id → 관련 화 지도
  causalPicks: {},    // '요소:분석시각:ep:3' 같은 키 → 반영할지
  causalLinkTab: 'bad', // 관련 화 줄 목록: bad(어긋남 · 고칠 화) | rel(이름이 나옴 · 나올 화) | char(관련 인물만)
});

(function causalStyle() {
  const css = `
.cz-col { display: flex; flex-direction: column; gap: var(--gap-stack); min-width: 0; }
.cz-col > .card { scroll-margin-top: calc(var(--band, 0px) + 16px); }
.cz-desc { font-family: var(--serif); font-size: 0.9375rem; line-height: 1.8; white-space: pre-wrap; }
.cz-chunks { display: flex; flex-wrap: wrap; gap: 10px 24px; }
.cz-chunk { flex: 1 1 300px; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.cz-cells { display: grid; grid-template-columns: repeat(${CZ_CHUNK}, minmax(0, 1fr)); gap: 2px; }
.cz-cells i { height: 22px; border-radius: 3px; border: 1px solid var(--line); background: var(--surface); cursor: pointer; }
.cz-cells i.tx { border-bottom: 3px solid var(--text-2); }
.cz-cells i.rel { background: var(--accent-soft); border-color: var(--accent); }
.cz-cells i.weak { border-style: dashed; border-color: var(--accent); }
.cz-cells i.bad { background: var(--red-soft); border-color: var(--red); }
.cz-cells i.plot { background: var(--amber-soft); border-color: var(--amber); }
.cz-cells i.done { background: var(--green-soft); border-color: var(--green); }
.cz-cells i.before { opacity: .45; }
.cz-cells i.since { box-shadow: inset 3px 0 0 var(--accent); }
.cz-cells i.reveal { outline: 2px dashed var(--accent); outline-offset: 1px; }
.cz-cells i.none { background: transparent; border-color: var(--rule); cursor: default; }
.cz-ticks { display: grid; grid-template-columns: repeat(${CZ_CHUNK}, minmax(0, 1fr)); font-size: 0.625rem; color: var(--muted); }
.cz-ticks span { white-space: nowrap; }
.cz-rows { display: flex; flex-direction: column; }
.cz-row { min-height: 52px; padding: 8px 0; border-top: 1px solid var(--rule); display: grid; grid-template-columns: 64px minmax(0, 1fr) auto; gap: 10px; align-items: center; }
.cz-row > .btn { white-space: nowrap; padding: 0 8px; }
.cz-row:first-child { border-top: none; }
.cz-row .s { font-size: 0.75rem; color: var(--muted); }
.cz-row .q { font-family: var(--serif); line-height: 1.7; }
.cz-row .t { font-weight: 700; }
.cz-list .cz-row { grid-template-columns: auto minmax(0, 1fr) auto auto; }
@container outline (max-width: 560px) {
  .cz-list .cz-row { grid-template-columns: minmax(0, 1fr) auto; }
  .cz-list .cz-row > .chip:first-child { grid-column: 1 / -1; justify-self: start; }
}
.cz-item { padding: 14px 16px; border: 1px solid var(--line); border-radius: 10px; display: flex; flex-direction: column; gap: 10px; scroll-margin-top: calc(var(--band, 0px) + 16px); }
.cz-item.hot { border-color: var(--sel-line); background: var(--sel-bg); }
.cz-item-h { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.cz-item .conflict { background: var(--bg); }
.cz-item .prop-part { background: transparent; border: none; padding: 0; }
.cz-ctx { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }`;
  const el = document.createElement('style');
  el.textContent = css;
  document.head.appendChild(el);
}());

async function causalLoad() {
  S.causalLinks = await api('GET', `/projects/${enc(S.name)}/elements/links`).catch(() => ({}));
}

/** 라우터가 부른다: causal 은 개요, causal/<id> 는 그 요소 쪽 */
function causalPick(sel) {
  const prev = S.causalSel;
  S.causalSel = sel || '';
  if (prev !== S.causalSel && !S.focusTarget) S.focusTarget = '#app main h1';
  if (S.causalEdit && S.causalEdit !== S.causalSel) S.causalEdit = '';
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
  if (el.found_in) parts.push(`${el.found_ep}화 ${el.found_in}에 처음 나옴`);
  return parts.join(' · ');
}

/** 분석이 건드리는 화. 모순 · 플롯 고치기 · 본문 고치기가 같은 화면 한 번만 센다 */
function impactEpisodes(r) {
  return new Set([...r.conflicts.map((c) => c.episode), ...r.episodes.map((e) => e.number), ...r.patches.map((t) => t.episode)].filter(Boolean));
}

/** 요소의 분석 상태: { key, label(칩 글), short(목차 꼬리), cls(칩 클래스), todo(손볼 것인지) } */
function causalStatus(el) {
  const imp = el.impact;
  if (!imp && el.found_in) return { key: 'found', label: `${el.found_ep}화 ${el.found_in}에서`, short: `${el.found_ep}화 ${el.found_in}`, cls: '', todo: false };
  if (!imp) return el.added_after ? { key: 'new', label: '분석 전', short: '분석 전', cls: 'warn', todo: true } : { key: 'none', label: '', short: '', cls: '', todo: false };
  if (causalStale(el)) return { key: 'stale', label: '다시 분석 필요', short: '다시 분석', cls: 'warn', todo: true };
  if (imp.outcome === 'applied') return { key: 'applied', label: '적용함', short: '적용함', cls: 'ok', todo: false };
  if (imp.outcome === 'dismissed') return { key: 'dismissed', label: '분석 봄', short: '분석 봄', cls: '', todo: false };
  const r = imp.report;
  const n = impactEpisodes(r).size;
  if (n) return { key: 'review', label: `검토할 것 · ${n}개 화`, short: `검토 ${n}`, cls: 'warn', todo: true };
  if (r.conflicts.length || r.new_facts.length) return { key: 'review', label: '검토할 것', short: '검토', cls: 'warn', todo: true };
  return { key: 'clean', label: '영향 없음', short: '영향 없음', cls: 'ok', todo: false };
}

/** 관련 화 칸: 1~total 화마다 { n, cls, tag, group }. group 은 줄 목록 거르기(bad · rel · char) 이름, 관계가 없으면 ''.
    반영한 뒤에는 분석 때의 '모순 · 고침'이 지금 일이 아니다. 반영한 화는 따로 두고 남은 것만 모순 · 고칠 화로 둔다 */
function causalCells(el, links, total, eps) {
  const byLink = new Map((links || []).map((l) => [l.episode, l]));
  const r = el.impact && el.impact.outcome !== 'dismissed' ? el.impact.report : null;
  const bad = new Set(r ? r.conflicts.filter((c) => c.episode).map((c) => c.episode) : []);
  const plot = new Set(r ? [...r.episodes.map((e) => e.number), ...r.patches.map((t) => t.episode)] : []);
  const done = new Set();
  if (r && el.impact.outcome === 'applied') {
    (el.impact.applied || []).forEach((x) => {
      const [k, v] = x.split(':');
      if (k === 'ep') done.add(Number(v));
      if (k === 'patch' && r.patches[Number(v)]) done.add(r.patches[Number(v)].episode);
    });
    done.forEach((n) => { bad.delete(n); plot.delete(n); });
  }
  const byEp = new Map((eps || []).map((e) => [e.n, e]));
  return Array.from({ length: total }, (_, k) => {
    const n = k + 1;
    const l = byLink.get(n);
    const e = byEp.get(n);
    let cls; let tag; let group;
    if (bad.has(n)) [cls, tag, group] = ['bad', '모순', 'bad'];
    else if (plot.has(n)) [cls, tag, group] = ['plot', '고칠 화', 'bad'];
    else if (done.has(n)) [cls, tag, group] = ['done', '적용함', 'bad'];
    else if (l && (l.where.length || l.planned)) [cls, tag, group] = ['rel', l.where.length ? '이름이 나옴' : '나올 화', 'rel'];
    else if (l) [cls, tag, group] = ['rel weak', '인물만', 'char'];
    else [cls, tag, group] = [e ? '' : 'none', '', ''];
    const marks = (el.since_ep > 0 && n === el.since_ep ? ' since' : '') + (el.reveal_ep === n ? ' reveal' : '') + (e && e.text ? ' tx' : '') + (el.since_ep > n ? ' before' : '');
    return { n, cls: `${cls}${marks}`.trim(), tag, group };
  });
}

// ----- 목차 -----

const causalHref = (id) => `${base()}/causal${id ? `/${enc(id)}` : ''}`;

function causalToc() {
  const els = P().elements || [];
  const todo = els.filter((x) => causalStatus(x).todo).length;
  const item = (x) => {
    const st = causalStatus(x);
    return `<button type="button" class="outline-item" data-action="causalShow" data-arg="${esc(x.id)}"${S.causalSel === x.id ? ' aria-current="page"' : ''}><span class="tl">${esc(x.name || '이름 없음')}</span><span class="st${st.todo ? ' warn' : ''}">${esc(st.short || (x.since_ep > 0 ? `${x.since_ep}화부터` : ''))}</span></button>`;
  };
  const groups = EL_KINDS.map((k) => [k, els.filter((x) => x.kind === k)]).filter(([, xs]) => xs.length);
  const body = [
    `<button type="button" class="outline-item" data-action="causalShow" data-arg=""${S.causalSel ? '' : ' aria-current="page"'}><span class="tl">개요</span><span class="st">요소 ${els.length}</span></button>`,
    todo ? `<button type="button" class="outline-item warn" data-action="causalGoTodo"><span class="tl">손볼 것</span><span class="st">${todo}</span></button>` : '',
    ...groups.map(([k, xs]) => `<span class="outline-h">${esc(k)}</span>${xs.map(item).join('')}`),
  ].join('');
  const cur = causalEl();
  return outlineNav({ id: 'cz-toc', label: '인과율 목차', now: cur ? esc(cur.name || '이름 없음') : '개요', body });
}

// ----- 개요 -----

function causalTodoCard() {
  const els = (P().elements || []).filter((x) => causalStatus(x).todo);
  if (!els.length) return '';
  const rows = els.map((x) => {
    const st = causalStatus(x);
    const btn = st.key === 'review' ? '분석 보기' : st.key === 'stale' ? '다시 분석' : '영향 분석';
    return `<div class="cz-row"><span class="chip">${esc(x.kind)}</span><div><div class="t">${esc(x.name || '이름 없음')}</div><div class="s">${esc(st.key === 'stale' ? '분석한 뒤 요소를 고쳤어요' : st.key === 'new' ? `${x.added_after}화까지 쓴 뒤에 더했어요. 이미 쓴 화와 부딪치는지 봐요` : st.label)}</div></div>
      <button type="button" class="btn small" data-action="causalShow" data-arg="${esc(x.id)}">${btn}</button></div>`;
  }).join('');
  return `<section class="card" id="cz-todo"><h2>손볼 것</h2><div class="cz-rows">${rows}</div></section>`;
}

function causalListCard() {
  const els = P().elements || [];
  const rows = EL_KINDS.flatMap((k) => els.filter((x) => x.kind === k)).map((x) => {
    const st = causalStatus(x);
    return `<div class="cz-row"><span class="chip">${esc(x.kind)}</span><div><a class="t" href="${causalHref(x.id)}" data-action="causalShow" data-arg="${esc(x.id)}">${esc(x.name || '이름 없음')}</a>
      <div class="s">${esc(timingText(x))}${x.characters.length ? ` · ${esc(x.characters.map(charName).join(', '))}` : ''}</div></div>${st.label ? `<span class="chip${st.cls ? ` ${st.cls}` : ''}">${esc(st.label)}</span>` : '<span></span>'}</div>`;
  }).join('');
  return `<section class="card" id="cz-all"><h2>모든 요소 ${els.length}</h2><div class="cz-rows cz-list">${rows}</div></section>`;
}

// ----- 요소 하나 -----

function causalInfoCard(el) {
  const open = S.causalEdit === el.id;
  const btn = `<button type="button" class="btn small" data-action="causalEditToggle" data-arg="${esc(el.id)}" aria-expanded="${open}">${open ? '다 고쳤어요' : '고치기'}</button>`;
  const head = `<div class="pf-head"><h2>요소 내용${open ? ' <span class="small pf-state">고치는 중</span>' : ''}</h2>${btn}</div>`;
  const found = el.found_in ? `<div class="note plain">${el.found_ep}화 ${esc(el.found_in)}에 처음 나와 ${el.found_in === '본문' ? '상태 승인 때' : '화를 확정할 때'} 등록한 장소예요. 이름이나 설명을 고쳐도 돼요.${el.found_in === '본문' ? ` ${el.found_ep}화부터 반영을 취소하면 빠져요 (시점이나 관련 인물을 더했으면 남아요).` : ''}</div>` : '';
  if (!open) {
    const none = '<span class="muted">비어 있음</span>';
    return `<section class="card pf-sec" id="cz-info">${head}${found}
      ${el.description ? `<p class="cz-desc">${esc(el.description)}</p>` : `<p class="small">설명이 비어 있어요. 지켜야 할 내용을 적어야 영향 분석을 할 수 있어요.</p>`}
      <dl class="pf-dl">
        <dt>언제부터</dt><dd>${el.since_ep > 0 ? `${el.since_ep}화부터 생겨요<div class="small">${el.since_ep}화 전 본문은 이 요소가 없던 때라 모순으로 보지 않아요.</div>` : '처음부터 사실이었어요<div class="small">이미 쓴 화도 이 설정과 맞아야 해서, 영향 분석이 본문까지 검사해요.</div>'}</dd>
        <dt>나올 화</dt><dd>${el.episodes.length ? `${esc(el.episodes.join(', '))}화` : none}</dd>
        <dt>드러나는 화</dt><dd>${el.reveal_ep ? `${el.reveal_ep}화<div class="small">그 전에는 암시만 해요.</div>` : '숨기지 않음'}</dd>
        <dt>관련 인물</dt><dd>${el.characters.length ? esc(el.characters.map(charName).join(', ')) : none}</dd>
        <dt>다른 이름</dt><dd>${el.aliases.length ? esc(el.aliases.join(', ')) : none}</dd>
        <dt>AI에 넣기</dt><dd>${esc((EL_CTX.find(([k]) => k === el.context) || EL_CTX[0])[1])}${el.context === 'auto' ? '<div class="small">그 화에 관련 인물이 나오거나, 플롯에 이름이 있거나, 나올 화일 때만 넣어요.</div>' : ''}</dd>
      </dl></section>`;
  }
  const i = causalIndex(el.id);
  const b = `elements.${i}`;
  const chars = P().characters.map((c) => `<label class="row" style="font-size:0.8125rem;gap:6px;min-height:36px"><input type="checkbox" data-el-char="${esc(c.id)}"${el.characters.includes(c.id) ? ' checked' : ''}>${esc(c.name || c.id)}</label>`).join('');
  const fromStart = el.since_ep <= 0;
  return `<section class="card pf-sec editing" id="cz-info">${head}${found}
    <div class="grid-2">
      <div class="field"><label for="el-kind">종류</label><select id="el-kind" data-el-kind>${EL_KINDS.map((k) => `<option${k === el.kind ? ' selected' : ''}>${k}</option>`).join('')}</select>
        ${el.kind === '예정 사건' ? `<span class="small">그 화에 꼭 일어날 사건은 여기에, 날짜가 정해진 약속은 <a href="${base()}/timeline">작품 속 시간</a>의 기한, 복선 회수는 <a href="${base()}/foreshadow">복선 센터</a>에 적어요.</span>` : ''}</div>
      ${input('이름', b + '.name', { placeholder: '본문과 플롯에서 찾을 이름' })}
    </div>
    ${input('설명', b + '.description', { rows: 3, autogrow: true, placeholder: EL_KIND_HINT[el.kind] || '', hint: '지켜야 할 내용을 구체적으로' })}
    ${input('다른 이름', b + '.aliases', { kind: 'list', rows: 2, hint: '본문에서 다르게 부르는 말. 두 글자 이상' })}
    <div class="field"><span class="label">관련 인물</span><div class="row">${chars || '<span class="small">인물이 아직 없어요.</span>'}</div></div>
    <div class="field"><span class="label">언제부터 사실인가요?</span>
      <div class="cz-ctx"><div class="seg" role="group" aria-label="사실이 되는 화">
        <button type="button" aria-pressed="${fromStart}" data-action="causalSince" data-arg="start">처음부터 사실이었다</button>
        <button type="button" aria-pressed="${!fromStart}" data-action="causalSince" data-arg="from">어느 화부터 생긴다</button></div>
        ${fromStart ? '' : `<label class="row" style="gap:6px"><input type="number" id="el-since" min="1" style="width:90px" value="${el.since_ep}" data-bind="${b}.since_ep" data-kind="int">화부터</label>`}</div></div>
    <div class="grid-2">
      <div class="field"><label for="el-eps">나올 화 <span class="hint">일어나거나 꼭 나와야 하는 화. 쉼표로</span></label><input id="el-eps" type="text" value="${esc(el.episodes.join(', '))}" data-el-eps placeholder="예: 7, 12"></div>
      ${input('독자에게 드러나는 화', b + '.reveal_ep', { type: 'number', min: 0, zeroBlank: true, placeholder: '숨기지 않음', hint: '비우면 숨기지 않음. 그 전에는 암시만' })}
    </div>
    <div class="field"><span class="label">본문을 쓸 때 AI에 넣기</span><div class="seg" role="group" aria-label="AI에 넣기">${EL_CTX.map(([k, l]) => `<button type="button" aria-pressed="${el.context === k}" data-action="causalContext" data-arg="${k}">${l}</button>`).join('')}</div>
      <span class="small">관련 있을 때: 그 화에 관련 인물이 나오거나, 플롯에 이름이 있거나, 나올 화일 때만 넣어요.</span></div>
    <p class="small">고친 내용은 화면 아래 저장 띠로 저장해요.</p></section>`;
}

function causalLinksCard(el) {
  const total = Math.max(P().meta.target_episodes, ...P().episodes.map((e) => e.plot.number), 1);
  const links = S.causalLinks[el.id] || [];
  const eps = P().episodes.map((e) => ({ n: e.plot.number, text: !!e.text }));
  const cells = causalCells(el, links, total, eps);
  const chunks = [];
  for (let a = 0; a < total; a += CZ_CHUNK) {
    const part = cells.slice(a, a + CZ_CHUNK);
    const ticks = part.map((c) => `<span>${c.n === 1 || c.n % 10 === 0 ? c.n : ''}</span>`).join('');
    chunks.push(`<div class="cz-chunk"><span class="small">${a + 1}~${a + part.length}화</span>
      <div class="cz-cells">${part.map((c) => `<i class="${c.cls}" data-action="causalCell" data-arg="${c.n}" title="${esc(`${c.n}화${c.tag ? ` · ${c.tag}` : ''}`)}"></i>`).join('')}</div>
      <div class="cz-ticks">${ticks}</div></div>`);
  }
  const groups = { bad: cells.filter((c) => c.group === 'bad'), rel: cells.filter((c) => c.group === 'rel'), char: cells.filter((c) => c.group === 'char') };
  const tab = S.causalLinkTab;
  const seg = `<div class="seg" role="group" aria-label="관련 화 거르기">${[['bad', '어긋남 · 고칠 화'], ['rel', '이름이 나옴'], ['char', '인물만']].map(([k, l]) => `<button type="button" aria-pressed="${tab === k}" data-action="causalLinkTab" data-arg="${k}">${l} ${groups[k].length}</button>`).join('')}</div>`;
  const byLink = new Map(links.map((l) => [l.episode, l]));
  const r = el.impact && el.impact.outcome !== 'dismissed' ? el.impact.report : null;
  const shown = groups[tab].slice(0, 12);
  const rows = shown.map((c) => {
    const e = ep(c.n);
    const l = byLink.get(c.n);
    const cf = r && r.conflicts.find((x) => x.episode === c.n);
    const quote = cf ? cf.quote : l && l.snippet ? l.snippet : l && l.characters.length ? `인물: ${l.characters.map(charName).join(', ')}` : '';
    const where = [l && l.where.length ? l.where.join(' · ') : '', e ? STATUS[e.status] : '플롯 없음'].filter(Boolean).join(' · ');
    const cls = { bad: 'bad', plot: 'warn', done: 'ok' }[c.cls.split(' ')[0]] || '';
    return `<div class="cz-row"><button type="button" class="btn small ghost" data-action="causalCell" data-arg="${c.n}">${c.n}화</button>
      <div><div class="s">${esc(where)}</div>${quote ? `<div class="q">“${esc(quote)}”</div>` : ''}</div><span class="chip${cls ? ` ${cls}` : ''}">${esc(c.tag)}</span></div>`;
  }).join('');
  const more = groups[tab].length > shown.length ? `<p class="small">${groups[tab].length - shown.length}개 더 있어요. 칸을 눌러 그 화로 가요.</p>` : '';
  const legend = `<div class="legend"><span><i style="background:var(--red-soft);border:1px solid var(--red)"></i>모순</span><span><i style="background:var(--amber-soft);border:1px solid var(--amber)"></i>고칠 화</span><span><i style="background:var(--green-soft);border:1px solid var(--green)"></i>적용함</span><span><i style="background:var(--accent-soft);border:1px solid var(--accent)"></i>이름이 나옴 · 나올 화</span><span><i style="border:1px dashed var(--accent)"></i>관련 인물만</span><span><i style="border-bottom:3px solid var(--text-2)"></i>본문 있음</span>${el.since_ep > 0 ? '<span><i style="border-left:3px solid var(--accent)"></i>생기는 화</span>' : ''}${el.reveal_ep ? '<span><i style="outline:2px dashed var(--accent)"></i>드러나는 화</span>' : ''}</div>`;
  return `<section class="card" id="cz-links"><div class="pf-head"><h2>관련 화</h2><span class="small">이름 · 다른 이름 · 관련 인물로 찾았어요 (AI 없이)</span></div>
    <div class="cz-chunks" aria-hidden="true">${chunks.join('')}</div>${legend}${seg}
    ${rows ? `<div class="cz-rows">${rows}</div>${more}` : `<p class="small">${tab === 'bad' ? (r ? '어긋나거나 고칠 화가 없어요.' : '영향 분석을 하면 어긋나는 화가 여기에 나와요.') : '해당하는 화가 없어요.'}</p>`}</section>`;
}

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

/** 분석 내용을 화별로 묶는다: 그 화의 어긋나는 곳과 고칠 것(본문 · 플롯)을 한 칸에. 화가 없는 어긋남과 더할 사실은 뒤에 */
function causalImpactBody(el, open) {
  const r = el.impact.report;
  const box = (part, disabled) => open ? `<input type="checkbox" data-causal-pick="${esc(pickId(el, part))}"${S.causalPicks[pickId(el, part)] && !disabled ? ' checked' : ''}${disabled ? ' disabled' : ''}>` : '';
  const conflict = (c) => `<div class="conflict"><div class="row" style="gap:6px"><span class="chip">${esc(c.target)}</span><span class="chip ${FIX_CLASS[c.fix] || ''}">${esc(c.fix)}</span></div>
    <blockquote>${esc(c.quote)}</blockquote><div>${esc(c.problem)}</div></div>`;
  const epNums = [...new Set([...r.conflicts.map((c) => c.episode).filter(Boolean), ...r.patches.map((t) => t.episode), ...r.episodes.map((e) => e.number)])].sort((a, b) => a - b);
  const blocks = epNums.map((n) => {
    const cur = ep(n);
    const parts = [];
    r.patches.forEach((t, i) => {
      if (t.episode !== n) return;
      const fin = cur && cur.status === 'finalized';
      parts.push(`<div class="prop-part"><label class="prop-head">${box('patch:' + i)}<strong>본문 고치기</strong></label>
        ${fin && open ? '<div class="note warn">상태 반영까지 끝난 화예요. 본문만 고치고 요약과 인물 상태는 그대로 둬요.</div>' : ''}
        <div class="diff"><div class="diff-row"><del>${esc(t.quote)}</del><ins>${esc(t.replacement)}</ins></div>${t.reason ? `<div class="small">${esc(t.reason)}</div>` : ''}</div></div>`);
    });
    r.episodes.forEach((e) => {
      if (e.number !== n) return;
      const locked = cur && LOCKED_STATUS.includes(cur.status);
      const note = locked ? '<div class="note plain">본문이 생겨서 이제는 바꿀 수 없어요.</div>'
        : cur && cur.status === 'confirmed' && open ? '<div class="note warn">확정한 화예요. 적용하면 초안으로 돌아가 다시 확정해야 해요.</div>' : '';
      parts.push(`<div class="prop-part"><label class="prop-head">${box('ep:' + e.number, locked)}<strong>플롯 고치기</strong> ${esc(e.title)}</label>${note}<div class="diff">${plotDiff(e)}</div></div>`);
    });
    const cfs = r.conflicts.filter((c) => c.episode === n).map(conflict).join('');
    return `<div class="cz-item" id="cz-ep-${n}"><div class="cz-item-h"><strong>${n}화</strong>${cur ? `<span class="chip ${cur.status}">${esc(STATUS[cur.status])}</span>` : '<span class="chip">플롯 없음</span>'}</div>${cfs}${parts.join('')}</div>`;
  });
  const loose = r.conflicts.filter((c) => !c.episode);
  if (loose.length) blocks.push(`<div class="cz-item"><div class="cz-item-h"><strong>설정 · 확정 사실</strong></div>${loose.map(conflict).join('')}</div>`);
  if (r.new_facts.length) blocks.push(`<div class="cz-item"><div class="cz-item-h"><strong>설명으로 덮기</strong></div>${r.new_facts.map((f, i) => `<div class="prop-part"><label class="prop-head">${box('fact:' + i)}<strong>확정 사실 더하기</strong></label><div class="diff"><div class="fact-add">${esc(f)}</div></div></div>`).join('')}</div>`);
  return blocks.join('');
}

function causalImpact(el) {
  const job = jobFor('impact');
  const btn = job ? '<button class="btn small" aria-disabled="true" aria-busy="true">영향을 분석하는 중…</button>'
    : `<button class="btn${el.impact ? ' small' : ' primary'}" data-action="causalAnalyze">${el.impact ? '다시 분석' : '영향 분석'}</button>`;
  const lw = lastWritten();
  if (!el.impact) {
    const why = lw ? `${lw}화까지 쓴 작품이에요. 이 요소가 이미 쓴 화, 확정한 플롯과 부딪치는지 AI가 근거를 인용해 찾고 고칠 방법을 제안해요.`
      : '정해 둔 플롯이 이 요소와 맞는지, 어느 화에 심고 드러내면 좋을지 AI가 제안해요.';
    return `<section class="card" id="cz-impact"><div class="pf-head"><h2>영향 분석</h2>${btn}</div><div class="note info">${why} 적용은 고른 것만 해요.</div></section>`;
  }
  const imp = el.impact;
  const r = imp.report;
  const open = !imp.outcome;
  if (open) initCausalPicks(el);
  const st = causalStatus(el);
  const done = imp.outcome === 'applied' ? `<span class="chip ok">적용함 · ${imp.applied.map((x) => appliedLabel(x, r)).join(', ')}</span>`
    : imp.outcome === 'dismissed' ? '<span class="chip">버림</span>' : st.todo ? `<span class="chip warn">${esc(st.label)}</span>` : '';
  const has = r.episodes.length || r.patches.length || r.new_facts.length;
  const timingTip = open && r.conflicts.some((c) => c.fix === '시점 변경') ? '<div class="note info">시점 변경을 권한 곳이 있어요. 요소 내용의 \'언제부터\'를 늦추고 저장한 뒤 다시 분석하면 앞 본문은 모순이 아니게 돼요.</div>' : '';
  const body = causalImpactBody(el, open);
  return `<section class="card" id="cz-impact"><div class="pf-head"><div><h2>영향 분석</h2><div class="small">${fmtDate(imp.at)} 분석 ${done}</div></div>${btn}</div>
    <div id="causal-stale">${staleNote(el)}</div>
    <div class="msg-text" style="white-space:pre-wrap">${esc(r.summary)}</div>${timingTip}
    ${open ? `${body}${has ? proposalActions(['causalDismiss'], ['causalApply']) : ''}` : `<details class="proposal done"><summary>분석 내용 다시 보기</summary>${body}${imp.outcome === 'dismissed' ? '<div class="row proposal-actions"><button type="button" class="btn small" data-action="causalReopen">다시 검토</button></div>' : ''}</details>`}
  </section>`;
}

function staleNote(el) {
  return causalStale(el) ? '<div class="note warn">분석한 뒤 요소를 고쳤어요. 다시 분석하면 지금 내용으로 봐요.</div>' : '';
}

function appliedLabel(x, report) {
  const [k, v] = x.split(':');
  const t = report && report.patches[Number(v)];
  return { ep: `${v}화 플롯`, patch: t ? `${t.episode}화 본문 수정` : `본문 수정 ${Number(v) + 1}`, fact: `사실 ${Number(v) + 1}` }[k] || x;
}

function causalDetail(el) {
  const st = causalStatus(el);
  const more = menuBtn(`cz-more-${el.id}`, '<span aria-hidden="true">⋯</span>', () => `<button type="button" class="pop-item danger" data-action="causalDelete" data-arg="${esc(el.id)}">요소 지우기<span class="small">반영한 플롯과 본문은 그대로예요</span></button>`, { cls: 'btn icon-btn', aria: '요소 더 보기' });
  const head = header(`인과율 · ${esc(el.kind)}`, el.name || '이름 없음', `${esc(timingText(el))}${st.label ? ` <span class="chip${st.cls ? ` ${st.cls}` : ''}">${esc(st.label)}</span>` : ''}`, more);
  const main = `<div class="cz-col">${causalInfoCard(el)}${causalLinksCard(el)}${causalImpact(el)}</div>`;
  return `${head}${outlineDoc(causalToc(), main, { cls: 'cz-wrap' })}`;
}

// ----- 화면 -----

function viewCausal() {
  const els = P().elements || [];
  const add = '<button type="button" class="btn primary" data-action="causalNew">+ 요소 더하기</button>';
  const head = (right) => header('요소 · 특징 · 설정 · 사건', '인과율', '언제든 요소를 더하세요. 이미 쓴 화와 정해 둔 플롯 중 어디가 흔들리는지 보여 주고, 고칠 방법을 변경안으로 내요. 적용은 고른 것만 해요.', right);
  const gone = S.causalGone ? `<div class="note info between"><span>'${esc(S.causalGone.name || '이름 없음')}' 요소를 지웠어요.</span><button type="button" class="btn small" data-action="causalRestore">되살리기</button></div>` : '';
  if (!els.length) {
    return `${head('')}${gone}<section class="card csh-empty"><div class="empty"><p>아직 더한 요소가 없어요. 지켜야 할 설정 하나를 더하면, 쓴 화와 플롯 중 어디가 흔들리는지 보여 줘요.</p>
      <p class="small">예: "${esc(exName(0))}의 친아버지는 따로 있다"(과거 사건, 처음부터 사실), "7화부터 마을에 통금이 생긴다"(세계 규칙, 7화부터)</p>${add}</div></section>`;
  }
  const el = S.causalSel && causalEl();
  if (el) return `${gone}${causalDetail(el)}`;
  const lost = S.causalSel ? `<div class="note warn" role="status">'${esc(S.causalSel)}' 요소를 찾지 못했어요. 지워졌을 수 있어요.</div>` : '';
  const main = `<div class="cz-col">${lost}${gone}${causalTodoCard()}${causalListCard()}</div>`;
  return `${head(add)}${outlineDoc(causalToc(), main, { cls: 'cz-wrap' })}`;
}

// ----- 동작 -----

function touchEl() {
  markDirty();
}

/** 개요 · 요소 쪽을 바꾼다. 저장하지 않은 고침이 있어도 묻지 않게 해시 이동 대신 주소만 바꾼다(lines.js lineGoTo 와 같다) */
function causalGoTo(id, focus = '#app main h1') {
  causalPick(id);
  S.focusTarget = focus;
  render();
  try {
    history.replaceState(history.state, '', causalHref(id));
    lastHash = location.hash;
  } catch (e) { /* 주소를 못 고쳐도 화면은 그대로 */ }
  if (!focus || focus === '#app main h1') window.scrollTo(0, 0);
}

Object.assign(actions, {
  causalShow(id) {
    causalGoTo(id ? String(id) : '');
  },
  causalGoTodo() {
    if (S.causalSel) causalGoTo('', '#cz-todo');
    else actions.jumpTo('cz-todo');
  },
  causalEditToggle(id) {
    S.causalEdit = S.causalEdit === id ? '' : String(id);
    S.focusTarget = '#cz-info [data-action="causalEditToggle"]';
    render();
  },
  causalLinkTab(k) {
    S.causalLinkTab = k;
    render();
  },
  /** 관련 화 칸 · 줄: 분석에 그 화가 있으면 그 칸으로, 없으면 그 화로 간다 (본문이 있으면 집필, 플롯만 있으면 플롯, 없으면 보드) */
  causalCell(n) {
    const box = document.getElementById(`cz-ep-${n}`);
    if (box) {
      const d = box.closest('details');
      if (d) d.open = true;
      box.scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
      box.classList.add('hot');
      setTimeout(() => box.classList.remove('hot'), 1600);
      return;
    }
    const e = ep(n);
    if (e && e.text) location.hash = `${base()}/write/${n}`;
    else if (e) actions.lineEp(n);
    else location.hash = `${base()}/arc`;
  },
  causalNew() {
    const id = newElementId();
    P().elements.push({ id, kind: '기타', name: '', aliases: [], description: '', characters: [], since_ep: 0, episodes: [], reveal_ep: 0, context: 'auto', created_at: '', added_after: 0, impact: null });
    S.causalEdit = id;
    // 바로 저장하지 않는다 (줄기 추가와 같다). 아무것도 적지 않고 떠나면 버릴지 물어 빈 요소가 쌓이지 않는다
    markDirty();
    causalGoTo(id, `#f-elements-${causalIndex(id)}-name`);
  },
  async causalDelete(id) {
    const el = causalEl(id || S.causalSel);
    // 지우기는 바로 저장한다. 다른 화면에서 고친 저장 안 한 변경도 함께 저장되므로 그 사실을 알린다
    if (!el || !confirm(`'${el.name || '이름 없음'}' 요소를 지울까요? 이미 반영한 플롯과 본문은 그대로예요.${S.dirty ? ' 저장하지 않은 다른 변경도 함께 저장해요.' : ''} 지운 뒤 이 화면에서 바로 되살릴 수 있어요.`)) return;
    const gone = structuredClone(el);
    P().elements = P().elements.filter((x) => x.id !== el.id);
    if (await run('지우는 중', async () => { await save(); await causalLoad(); })) S.causalGone = gone;
    causalGoTo('');
  },
  async causalRestore() {
    const el = S.causalGone;
    if (!el) return;
    P().elements.push(el);
    S.causalGone = null;
    await run('되살리는 중', async () => { await save(); await causalLoad(); toast(`'${el.name || '이름 없음'}' 요소를 되살렸어요`); });
    causalGoTo(el.id);
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
    if (!el.name.trim() || !el.description.trim()) {
      S.causalEdit = el.id;
      S.focusTarget = el.name.trim() ? `#f-elements-${causalIndex(el.id)}-description` : `#f-elements-${causalIndex(el.id)}-name`;
      render();
      return toast('이름과 설명을 먼저 적으세요', true);
    }
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
    if (!body.episodes.length && !body.patches.length && !body.facts.length) return toast('적용할 부분을 고르세요', true);
    await run('적용하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/elements/${enc(el.id)}/impact/apply`, body);
      await causalLoad();
      const imp = causalEl().impact;
      toast(`적용했어요: ${imp.applied.map((x) => appliedLabel(x, imp.report)).join(', ')}`);
    });
  },
  async causalReopen() {
    const el = causalEl();
    await run('다시 여는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/elements/${enc(el.id)}/impact/reopen`);
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
    if ((t.dataset.bind || '').startsWith('elements.')) {
      touchEl();
      syncStale(el);
    }
    return;
  }
  touchEl();
  render();
});

/** 글 칸을 고치는 동안 '지난 분석' 경고와 목차 꼬리만 바로 고친다 (칸을 다시 그리지 않아 커서를 잃지 않는다) */
function syncStale(el) {
  const box = document.getElementById('causal-stale');
  if (box) box.innerHTML = staleNote(el);
  outlineRefresh('cz-toc', causalToc());
}

document.addEventListener('input', (e) => {
  if (S.route[2] !== 'causal' || !(e.target.dataset && (e.target.dataset.bind || '').startsWith('elements.'))) return;
  const el = causalEl();
  if (el) syncStale(el);
});

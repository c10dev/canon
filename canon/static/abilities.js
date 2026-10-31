/* 스킬 도감 화면. app.js 의 S, actions, api, run, render, header, esc, P, base, enc, toast, saveIfDirty, showDialog 와 outline.js 의 공용 목차 틀을 쓴다.
   상태창 목록 항목(스킬 · 특성 · 칭호)의 조각마다 설명 · 효과 · 대가 · 등급별 효과를 적는다(Project.abilities).
   정의는 인물 사이에 하나이고, 가진 인물 · 등급 · 얻은 화 · 바뀐 기록 · AI 에게 보이는 줄은 서버가 계산한다(canon/abilities.py, /abilities).
   화면은 공용 목차 + 카드 한 열이다. 목차: 찾기 · 개요 · 도감에 없는 조각 · 상태창 항목별 도감 항목.
   주소는 abilities(개요) · abilities/_missing(도감에 없는 조각) · abilities/_new(새 항목) · abilities/<항목 id>.
   항목 쪽 카드는 읽는 모양이 기본이고 '고치기'로 그 카드만 편다(설명 · 효과 · 대가 / 등급별 효과).
   상태창 칩(abChip, 인물 화면 cast.js 와 상태창 수치 statwin.js)을 누르면 뜨는 도감 카드는 abShow(공통 대화상자). */
'use strict';

Object.assign(S, {
  ab: null,          // 서버 값 { abilities: [{ ability, owners, line }], unlinked, lists }
  abSel: '',         // 지금 쪽: '' 개요 | '_missing' 도감에 없는 조각 | '_new' 새 항목 | 항목 id
  abEdit: null,      // 고치는 카드 { card: 'base' | 'grades' | 'new', a: Ability 사본 }
  abQuery: '',       // 목차 찾기
  abMissStat: '',    // 도감에 없는 조각 거르기(상태창 항목 이름). 빈 값이면 모두
  abOwner: '',       // 화면 상태를 가진 작품
});

// 이름만 봐도 목록인 상태창 항목. abilities.LIST_NAMES 와 같다 (tests/test_statwin_js.py)
const AB_LIST_NAMES = ['스킬', '특성', '칭호', '능력', '특기', '기술', '무공', '절기', '마법', '축복', '권능', '재능'];
const abListName = (name) => AB_LIST_NAMES.some((w) => String(name).includes(w));
const abWho = (id) => (P().characters.find((c) => c.id === id) || {}).name || id;
const abWhen = (ep) => (ep === null || ep === undefined ? '' : ep === 0 ? '시작 때 얻음' : `${ep}화에 얻음`);
const AB_CONTEXT = { auto: '관련 있을 때', always: '늘', off: '넣지 않음' };
const AB_CONTEXT_WHY = {
  auto: '그 화에 나오는 인물이 가졌거나 플롯에 이름이 나올 때 넣어요.',
  always: '그 화에 누가 나오든 넣어요.',
  off: 'AI에게 보이지 않아요.',
};
const AB_PAGES = { _missing: '도감에 없는 조각', _new: '새 도감 항목' };
const abBlank = (name = '', stat = '') => ({ id: '', name, aliases: [], stat, description: '', effect: '', cost: '', grades: [], context: 'auto', source: 'author', created_ep: 0 });

/** abilities.split 과 같다: 조각 → [이름, 등급 꼬리]. '화염구 Lv4' → ['화염구', 'Lv4'] */
function abSplit(item) {
  let base = String(item).trim();
  let tail = '';
  for (;;) {
    const m = base.match(SW_GRADE);
    if (!m || !base.slice(0, m.index).trim()) return [base, tail.trim()];
    tail = `${base.slice(m.index).trim()} ${tail}`.trim();
    base = base.slice(0, m.index).trim();
  }
}

/** abilities.key 와 같다: 등급 꼬리와 빈칸을 뗀 소문자 이름 */
const abKey = (name) => abSplit(name)[0].replace(/\s+/g, '').toLowerCase();

/** abilities.find 와 같다: 상태창 조각에 이어진 도감 항목(작품 값으로). 도감 항목의 stat 이 정해져 있으면 그 상태창 항목의 조각만 */
function abFindLocal(item, stat = '') {
  const k = abKey(item);
  return (P().abilities || []).find((a) => [a.name, ...(a.aliases || [])].filter((x) => x.trim()).some((x) => abKey(x) === k) && (!a.stat || !stat || a.stat === stat)) || null;
}

/** 도감에 설명이 아직 없는 조각: 도감에 없거나, 있어도 설명 · 효과 · 대가가 모두 비었다 */
function abNoDoc(item, stat) {
  const a = abFindLocal(item, stat);
  return !a || !(a.description || a.effect || a.cost);
}

async function abLoad(sel) {
  if (S.abOwner && S.abOwner !== S.name) Object.assign(S, { abEdit: null, abQuery: '', abMissStat: '' });  // 다른 작품으로 가면 고치던 칸과 거르기를 푼다
  S.abOwner = S.name;
  const prev = S.abSel;
  S.abSel = sel || '';
  if (S.abSel === '_new' && !(S.abEdit && S.abEdit.card === 'new')) S.abSel = '';  // 새 항목 칸은 '+ 항목 더하기'로만 연다
  S.ab = await api('GET', `/projects/${enc(S.name)}/abilities`).catch((e) => ({ error: e.message, abilities: [], unlinked: [], lists: [] }));
  const rows = S.ab.abilities || [];
  if (S.abSel && !AB_PAGES[S.abSel] && !rows.some((r) => r.ability.id === S.abSel)) S.abSel = '';  // 지운 항목 링크는 개요로
  if (S.abEdit && S.abEdit.card !== 'new' && S.abEdit.a.id !== S.abSel) S.abEdit = null;  // 다른 쪽으로 가면 고치던 카드를 닫는다
  if (S.abEdit && S.abEdit.card === 'new' && S.abSel !== '_new') S.abEdit = null;
  let opened = S.abSel === '_new' && prev !== '_new';
  if (S.abOpenId) {  // 도감 카드의 '도감에서 고치기'
    const r = rows.find((x) => x.ability.id === S.abOpenId);
    if (r) { S.abEdit = { card: 'base', a: JSON.parse(JSON.stringify(r.ability)) }; opened = true; }
    S.abOpenId = null;
  }
  // 고치는 칸을 열고 들어오면(도감 카드의 '도감에서 고치기', '도감에 만들기') 라우터가 정한 제목 대신 이름 칸으로
  if (opened) S.focusTarget = '#ab-name';
  else if (prev !== S.abSel && !S.focusTarget) S.focusTarget = '#app main h1';
}

function abHref(k) { return `${base()}/abilities${k ? `/${enc(k)}` : ''}`; }

// ----- 목차 -----

/** 목차 묶음: 상태창 항목별. 항목을 정하지 않은 것은 가진 인물의 상태창 항목으로, 그것도 없으면 '목록 지정 없음' */
function abGroups(rows) {
  const groupOf = (r) => r.ability.stat || (r.owners[0] || {}).stat || '목록 지정 없음';
  const groups = [...new Set([...S.ab.lists, ...rows.map(groupOf)])].filter((g) => rows.some((r) => groupOf(r) === g));
  return groups.map((g) => [g, rows.filter((r) => groupOf(r) === g)]);
}

/** 목차 줄 끝 글: 설명 없음(손볼 것) · AI에 안 넣음 · 늘 넣음 · 가진 사람 수 */
function abTail(r) {
  if (!r.line) return ['설명 없음', true];
  if (r.ability.context === 'off') return ['AI에 안 넣음', false];
  if (r.ability.context === 'always') return ['늘 넣음', false];
  return [r.owners.length ? `${r.owners.length}명` : '가진 인물 없음', false];
}

function abTocBody() {
  const q = S.abQuery.trim().toLowerCase();
  const all = S.ab.abilities;
  const rows = all.filter(({ ability: a }) => !q || [a.name, ...a.aliases].some((x) => x.toLowerCase().includes(q)));
  const item = (k, inner, warn = false) => `<a class="outline-item${warn ? ' warn' : ''}" href="${abHref(k)}"${S.abSel === k ? ' aria-current="page"' : ''}>${inner}</a>`;
  const miss = S.ab.unlinked.length;
  const out = [
    item('', `<span class="tl">개요</span><span class="st">${all.length}항목</span>`),
    miss ? item('_missing', `<span class="tl">도감에 없는 조각</span><span class="st">${miss}</span>`, true) : '',
  ];
  abGroups(rows).forEach(([g, list]) => {
    out.push(`<div class="outline-h">${esc(g)} ${list.length}</div>`);
    out.push(...list.map((r) => {
      const [st, warn] = abTail(r);
      return item(r.ability.id, `<span class="tl">${esc(r.ability.name)}</span><span class="st">${esc(st)}</span>`, warn);
    }));
  });
  if (q && !rows.length) out.push('<div class="outline-note small">맞는 항목이 없어요.</div>');
  return out.join('');
}

function abToc() {
  const r = S.ab.abilities.find((x) => x.ability.id === S.abSel);
  const now = r ? esc(r.ability.name) : AB_PAGES[S.abSel] || '개요';
  const find = `<input id="ab-q" class="ab-find" type="search" value="${esc(S.abQuery)}" placeholder="이름 찾기" aria-label="도감 항목 찾기" data-ab-query="1">`;
  return outlineNav({ id: 'ab-toc', label: '도감 목차', now, body: `${find}<div id="ab-toc-rows" class="outline-list ab-toc-rows">${abTocBody()}</div>` });
}

// ----- 개요 · 도감에 없는 조각 -----

function abWhoRow(ids) {
  return ids.map((id) => {
    const c = P().characters.find((x) => x.id === id);
    return c ? `<span class="ab-who">${castAva(c, 's')}${esc(c.name || c.id)}</span>` : `<span class="ab-who">${esc(id)}</span>`;
  }).join('');
}

function abMissRow(m) {
  return `<li><div class="ab-miss-main"><span class="row"><strong>${esc(m.name)}</strong><span class="chip">${esc(m.stat)}</span>${m.items.some((x) => x !== m.name) ? `<span class="small">${esc(m.items.join(', '))}</span>` : ''}</span>
      <span class="row">${abWhoRow(m.characters)}</span></div>
    <button type="button" class="btn small" data-action="abNew" data-arg="${esc(`${m.stat}|${m.name}`)}">도감에 만들기</button></li>`;
}

function abOverview() {
  const d = S.ab;
  const empty = d.abilities.filter((r) => !r.line);
  const owners = new Set(d.abilities.flatMap((r) => r.owners.map((o) => o.character_id)));
  if (!d.abilities.length) {
    return `<section class="card csh-empty"><div class="empty"><p>상태창 조각 ${d.unlinked.length}개가 도감에 아직 없어요. 설명 · 효과 · 대가를 적어 두면 AI가 스킬을 일관되게 써요.</p>
      <a class="btn primary" href="${abHref('_missing')}">도감에 없는 조각 보기</a></div></section>`;
  }
  const tiles = `<div class="ab-tiles">
      <div class="ab-tile"><span class="small">도감 항목</span><b>${d.abilities.length}</b></div>
      <div class="ab-tile"><span class="small">가진 인물</span><b>${owners.size}명</b></div>
      ${empty.length ? `<a class="ab-tile warn" href="#ab-todo"><span class="small">설명이 빈 항목</span><b>${empty.length}</b></a>` : '<div class="ab-tile"><span class="small">설명이 빈 항목</span><b>0</b></div>'}
      ${d.unlinked.length ? `<a class="ab-tile warn" href="${abHref('_missing')}"><span class="small">도감에 없는 조각</span><b>${d.unlinked.length}</b></a>` : '<div class="ab-tile"><span class="small">도감에 없는 조각</span><b>0</b></div>'}</div>`;
  const todo = empty.length ? `<section class="card" id="ab-todo"><div class="between"><h2>손볼 것</h2><span class="small">AI에게 보일 줄이 없는 항목</span></div>
      <ul class="ab-list">${empty.map((r) => `<li><div class="ab-miss-main"><span class="row"><a href="${abHref(r.ability.id)}"><strong>${esc(r.ability.name)}</strong></a>${r.ability.stat ? `<span class="chip">${esc(r.ability.stat)}</span>` : ''}</span>
        <span class="small">${r.owners.length ? `${esc(r.owners.map((o) => `${abWho(o.character_id)} ${o.item}`).join(', '))} · ` : ''}설명 · 효과 · 대가가 비어 있어요</span></div>
        <button type="button" class="btn small" data-action="abEditOpen" data-arg="${esc(`${r.ability.id}|base`)}">설명 적기</button></li>`).join('')}</ul></section>` : '';
  const miss = d.unlinked.length ? `<section class="card"><div class="between"><div class="row"><h2>도감에 없는 조각</h2><span class="small">${d.unlinked.length}개 · 상태창에는 있지만 설명이 없어요</span></div></div>
      <ul class="ab-list">${d.unlinked.slice(0, 5).map(abMissRow).join('')}</ul>
      ${d.unlinked.length > 5 ? `<div><a class="btn small ghost" href="${abHref('_missing')}">${d.unlinked.length}개 모두 보기</a></div>` : ''}</section>` : '';
  return tiles + todo + miss;
}

function abMissingPage() {
  const d = S.ab;
  if (!d.unlinked.length) return '<section class="card csh-empty"><div class="empty"><p>상태창의 조각이 모두 도감에 있어요.</p><a class="btn primary" href="' + abHref('') + '">개요로 가기</a></div></section>';
  const stats = [...new Set(d.unlinked.map((m) => m.stat))];
  const pick = stats.includes(S.abMissStat) ? S.abMissStat : '';
  const seg = stats.length > 1 ? `<div class="seg" role="group" aria-label="상태창 항목 거르기"><button type="button" data-action="abMissStat" data-arg="" aria-pressed="${!pick}">모두 ${d.unlinked.length}</button>${stats.map((s) => `<button type="button" data-action="abMissStat" data-arg="${esc(s)}" aria-pressed="${pick === s}">${esc(s)} ${d.unlinked.filter((m) => m.stat === s).length}</button>`).join('')}</div>` : '';
  const rows = d.unlinked.filter((m) => !pick || m.stat === pick);
  return `<section class="card" id="ab-missing"><div class="between"><div class="row"><h2>도감에 없는 조각</h2><span class="small">${d.unlinked.length}개 · 상태창에는 있지만 설명이 없어요</span></div></div>
    ${seg}<ul class="ab-list">${rows.map(abMissRow).join('')}</ul>
    <span class="small">'도감에 만들기'는 그 이름으로 새 항목을 열어요. 같은 이름(등급 꼬리를 뗀 이름)이면 모든 인물에 한 설명을 써요.</span></section>`;
}

// ----- 항목 쪽 -----

/** 설명 · 효과 · 대가 · 등급별 효과(도감 카드). 빈 칸은 뺀다. here 는 강조할 등급 */
function abFields(a, here = '') {
  const row = (k, v) => (v ? `<dt>${k}</dt><dd>${esc(v)}</dd>` : '');
  const gs = (a.grades || []).map((g) => `<dt${g.grade === here ? ' class="hot"' : ''}>${esc(g.grade)}</dt><dd>${esc(g.effect)}</dd>`).join('');
  const all = row('설명', a.description) + row('효과', a.effect) + row('대가', a.cost) + gs;
  return all ? `<dl class="pf-dl">${all}</dl>` : '<div class="small">설명 · 효과 · 대가가 비어 있어요.</div>';
}

/** 얻고 · 등급이 바뀌고 · 잃은 걸음: '시작 Lv1 → 5화 Lv2 → 12화 Lv3' */
function abSteps(history) {
  if (!history.length) return '';
  const label = (h) => (h.kind === '잃음' ? '잃음' : abSplit(h.item)[1] || h.item);
  return `<span class="ab-steps">${history.map((h) => `<span>${h.episode ? `${h.episode}화` : '시작'} ${esc(label(h))}</span>`).join('<span class="arr" aria-hidden="true">→</span>')}</span>`;
}

function abHead(r) {
  const a = r.ability;
  const more = menuBtn(`ab-more-${a.id}`, '<span aria-hidden="true">⋯</span>', () => `<button type="button" class="pop-item danger" data-action="abDelete" data-arg="${esc(a.id)}">도감 항목 지우기<span class="small">상태창 값은 그대로예요</span></button>`, { cls: 'btn small icon-btn', aria: '더 보기' });
  return `<section class="card ab-head"><div class="between"><div class="row"><h2>${esc(a.name)}</h2>${a.aliases.length ? `<span class="small">다른 이름 ${esc(a.aliases.join(', '))}</span>` : ''}</div>${more}</div>
    <div class="row">${a.stat ? `<span class="chip">${esc(a.stat)}</span>` : '<span class="chip">어느 목록이든</span>'}<span class="chip confirmed">AI에 ${AB_CONTEXT[a.context] || a.context}${a.context === 'off' ? '' : ' 넣음'}</span>${a.grades.length ? `<span class="chip">등급 ${a.grades.length}</span>` : ''}${a.source === 'ai' ? `<span class="small">${a.created_ep ? `${a.created_ep}화 상태 변경안에서 생김` : 'AI가 만듦'}</span>` : ''}</div></section>`;
}

/** 읽기 카드 머리: 제목과 '고치기'. 고치는 중이면 '고치는 중' 글 */
function abCardHead(title, card, id) {
  const open = S.abEdit && S.abEdit.card === card;
  return `<div class="pf-head"><h2>${title}${open ? ' <span class="small pf-state">고치는 중</span>' : ''}</h2>${open ? '' : `<button type="button" class="btn small" data-action="abEditOpen" data-arg="${esc(`${id}|${card}`)}" aria-expanded="false">고치기</button>`}</div>`;
}

function abSaveRow(cancel = 'abCancel', label = '저장') {
  return `<div class="row ab-save"><button type="button" class="btn small ghost" data-action="${cancel}">취소</button><button type="button" class="btn small primary" data-action="abSave">${label}</button></div>`;
}

function abBaseFields(a) {
  const lists = (S.ab && S.ab.lists) || [];
  const opts = ['', ...new Set([...lists, ...(a.stat ? [a.stat] : [])])].map((x) => `<option value="${esc(x)}"${x === a.stat ? ' selected' : ''}>${x ? esc(x) : '어느 목록이든'}</option>`).join('');
  const f = (k, label, hint, rows) => `<div class="field"><label for="ab-${k}">${label}${hint ? ` <span class="hint">${hint}</span>` : ''}</label>${rows
    ? `<textarea id="ab-${k}" data-ab-field="${k}" rows="${rows}">${esc(a[k])}</textarea>` : `<input id="ab-${k}" type="text" data-ab-field="${k}" value="${esc(a[k])}">`}</div>`;
  return `<div class="grid-2">${f('name', '이름', '등급 꼬리 없이 (예: 화염구)')}<div class="field"><label for="ab-stat">상태창 항목</label><select id="ab-stat" data-ab-field="stat">${opts}</select></div></div>
    <div class="field"><label for="ab-aliases">다른 이름 <span class="hint">쉼표로. 상태창이나 본문에서 이 이름도 같은 것으로 봐요</span></label><input id="ab-aliases" type="text" data-ab-field="aliases" value="${esc(a.aliases.join(', '))}"></div>
    ${f('description', '설명', '', 2)}${f('effect', '효과', 'AI에게 보이는 줄에 들어가요', 2)}${f('cost', '대가 · 제약', '쿨타임, 마력 소모, 수명 같은 것', 2)}`;
}

function abBaseCard(r) {
  const a = r.ability;
  const open = S.abEdit && S.abEdit.card === 'base';
  const none = '<span class="small">비어 있음</span>';
  const body = open ? `${abBaseFields(S.abEdit.a)}${abSaveRow()}`
    : `<dl class="pf-dl"><dt>설명</dt><dd>${a.description ? esc(a.description) : none}</dd><dt>효과</dt><dd>${a.effect ? esc(a.effect) : none}</dd><dt>대가</dt><dd>${a.cost ? esc(a.cost) : none}</dd></dl>`;
  return `<section class="card pf-sec${open ? ' editing' : ''}" id="ab-base" tabindex="-1">${abCardHead('설명 · 효과 · 대가', 'base', a.id)}${body}</section>`;
}

function abGradesCard(r) {
  const a = r.ability;
  const open = S.abEdit && S.abEdit.card === 'grades';
  let body;
  if (open) {
    const gs = S.abEdit.a.grades.map((g, i) => `<div class="ab-grade"><input type="text" data-ab-grade="${i}" data-ab-gkey="grade" value="${esc(g.grade)}" placeholder="등급 (예: Lv3)" aria-label="등급 ${i + 1}">
        <input type="text" data-ab-grade="${i}" data-ab-gkey="effect" value="${esc(g.effect)}" placeholder="이 등급의 효과" aria-label="등급 ${i + 1} 효과">
        <button type="button" class="btn icon-btn ghost" data-action="abGradeDel" data-arg="${i}" aria-label="등급 ${i + 1} 지우기">✕</button></div>`).join('');
    body = `<span class="small">상태창 조각의 꼬리와 같게 적으면(Lv3) 가진 인물의 등급 효과로 보여요.</span>
      <div class="ab-grades">${gs}</div><div class="between"><button type="button" class="btn small" data-action="abGradeAdd">+ 등급 더하기</button>${abSaveRow()}</div>`;
  } else if (a.grades.length) {
    const who = (g) => r.owners.filter((o) => o.grade && o.grade.replace(/\s+/g, '').toLowerCase() === g.grade.replace(/\s+/g, '').toLowerCase()).map((o) => `<span class="chip csh-own">${esc(abWho(o.character_id))}</span>`).join('');
    body = `<dl class="pf-dl">${a.grades.map((g) => `<dt>${esc(g.grade)}</dt><dd>${esc(g.effect) || '<span class="small">비어 있음</span>'} ${who(g)}</dd>`).join('')}</dl>`;
  } else body = '<span class="small">등급별 효과가 없어요. 등급(Lv3 · B급)마다 효과가 다르면 적어요.</span>';
  return `<section class="card pf-sec${open ? ' editing' : ''}" id="ab-grades" tabindex="-1">${abCardHead('등급별 효과', 'grades', a.id)}${body}</section>`;
}

function abOwnersCard(r) {
  const rows = r.owners.map((o) => {
    const c = P().characters.find((x) => x.id === o.character_id) || { id: o.character_id, name: o.character_id };
    return `<li>${castAva(c)}<div class="ab-own-main"><span class="row"><a href="${base()}/cast/c:${enc(c.id)}"><strong>${esc(c.name || c.id)}</strong></a><span class="chip confirmed">${esc(o.item)}</span><span class="small">${esc(o.stat)}${o.acquired !== null ? ` · ${abWhen(o.acquired)}` : ''}</span></span>
        ${o.history.length > 1 ? abSteps(o.history) : ''}
        ${o.grade_effect ? `<span class="small"><strong>${esc(o.grade)}</strong> ${esc(o.grade_effect)}</span>` : ''}</div>
      <a class="btn small ghost" href="${base()}/statwin/${enc(c.id)}">상태창 보기</a></li>`;
  }).join('');
  return `<section class="card"><div class="row"><h2>가진 인물</h2><span class="small">${r.owners.length}명</span></div>
    ${rows ? `<ul class="ab-list ab-owners">${rows}</ul>` : '<div class="small">지금 이 항목을 가진 인물이 없어요. 상태창 목록에 이 이름이 있으면 여기에 보여요.</div>'}</section>`;
}

function abLineCard(r) {
  const a = r.ability;
  const seg = `<div class="seg" role="group" aria-label="쓰기 프롬프트에 넣기">${Object.entries(AB_CONTEXT).map(([k, v]) => `<button type="button" data-action="abContext" data-arg="${k}" aria-pressed="${a.context === k}">${v}</button>`).join('')}</div>`;
  const mode = (P().stat_window || {}).prompt || 'json';
  const note = mode === 'lines' ? '' : `<div class="note warn">이 줄은 지금 쓰기 프롬프트에 들어가지 않아요. 이 작품은 상태창 수치를 ${mode === 'none' ? '쓰기 프롬프트에 넣지 않아요' : '인물 상태 안에 그대로(JSON) 넣어요'}. 연구 · 모델 실험의 상태창 시험에서 넣는 방식을 '줄'로 바꾸면 들어가요.</div>`;
  return `<section class="card" id="ab-line"><div class="between"><h2>AI에게 보이는 줄</h2>${r.line ? '<button type="button" class="btn small" data-action="abCopyLine">복사</button>' : ''}</div>
    ${r.line ? `<pre class="ab-line" id="ab-line-text">${esc(r.line)}</pre>` : '<div class="small">설명 · 효과 · 대가가 비어 있어 AI에게 보일 줄이 없어요.</div>'}
    <div class="field"><span class="label">쓰기 프롬프트에 넣기</span>${seg}<span class="small">${AB_CONTEXT_WHY[a.context] || ''} 다음 화를 쓸 때(지금 상태창) 기준이에요.</span></div>
    ${note}</section>`;
}

function abItemPage(r) {
  return abHead(r) + abBaseCard(r) + abGradesCard(r) + abOwnersCard(r) + abLineCard(r);
}

function abNewPage() {
  return `<section class="card pf-sec editing" id="ab-base" tabindex="-1"><div class="pf-head"><h2>새 도감 항목 <span class="small pf-state">고치는 중</span></h2></div>
    ${abBaseFields(S.abEdit.a)}${abSaveRow('abCancel', '만들기')}</section>`;
}

function viewAbilities() {
  const head = header('작품 도구', '스킬 도감', '상태창의 스킬 · 특성 · 칭호마다 설명 · 효과 · 대가를 적어요. 같은 이름(Lv3 · B급 같은 등급 꼬리를 뗀 이름)이면 모든 인물에 한 설명을 써요. 가진 인물과 얻은 화는 상태창 기록에서 계산해요.',
    '<button type="button" class="btn" data-action="abNew" data-arg="">+ 항목 더하기</button>');
  const d = S.ab;
  if (!d) return `${head}<div class="small">불러오는 중…</div>`;
  if (d.error) return `${head}<div class="note err">${esc(d.error)}</div>`;
  if (!d.abilities.length && !d.unlinked.length && !S.abEdit) {
    return `${head}<section class="card csh-empty"><div class="empty"><p>상태창에 스킬 · 특성 · 칭호 목록이 아직 없어요. 상태창에 '스킬' 같은 항목을 만들면 그 조각이 여기에 모여요.</p>
      <a class="btn primary" href="${base()}/statwin">상태창 수치로 가기</a></div></section>`;
  }
  const r = d.abilities.find((x) => x.ability.id === S.abSel);
  const main = S.abSel === '_new' && S.abEdit ? abNewPage() : S.abSel === '_missing' ? abMissingPage() : r ? abItemPage(r) : abOverview();
  return `${head}${outlineDoc(abToc(), `<div class="ab-col">${main}</div>`, { cls: 'ab-wrap' })}`;
}

// ----- 상태창 칩과 도감 카드 -----

/** 상태창 칩: 누르면 도감 카드. 목록 항목 조각에만 쓴다 (cast.js · statwin.js swStatsBody). 도감에 설명이 없으면 주황 점 */
function abChip(cid, stat, item, cls) {
  const no = abNoDoc(item, stat);
  return `<button type="button" class="${cls} ab-chip${no ? ' nodoc' : ''}" data-action="abShow" data-arg="${esc([cid, stat, item].map(encodeURIComponent).join('|'))}" aria-haspopup="dialog">${esc(item)}${no ? '<span class="sr-only"> (도감에 설명 없음)</span>' : ''}</button>`;
}

document.addEventListener('input', (e) => {
  const d = e.target.dataset || {};
  if (d.abQuery) {
    S.abQuery = e.target.value;
    const rows = document.getElementById('ab-toc-rows');
    if (rows) rows.innerHTML = abTocBody();  // 목록 줄만 다시 그려 찾기 칸 포커스를 지킨다
    return;
  }
  if (!S.abEdit) return;
  if (d.abField) S.abEdit.a[d.abField] = d.abField === 'aliases' ? e.target.value.split(/\s*,\s*/).filter(Boolean) : e.target.value;
  if (d.abGrade !== undefined) S.abEdit.a.grades[Number(d.abGrade)][d.abGkey] = e.target.value;
});
document.addEventListener('change', (e) => {
  const d = e.target.dataset || {};
  if (S.abEdit && d.abField === 'stat') S.abEdit.a.stat = e.target.value;
});

async function abReload(sel) {
  S.ab = await api('GET', `/projects/${enc(S.name)}/abilities`);
  if (sel !== undefined) S.abSel = sel;
}

/** 지금 쪽 주소로 바꾼다(다시 읽지 않는다) */
function abSyncUrl() {
  const h = abHref(S.abSel);
  if (location.hash === h) return;
  try {
    history.replaceState(history.state, '', h);
    lastHash = location.hash;
  } catch (e) { /* 주소를 못 고쳐도 화면은 그대로 */ }
}

Object.assign(actions, {
  abNew(arg) {
    const [stat, ...rest] = String(arg || '').split('|');
    S.abEdit = { card: 'new', a: abBlank(rest.join('|'), arg ? stat : '') };
    S.abOwner = S.name;
    S.focusTarget = '#ab-name';
    if (location.hash.split('/')[3] !== 'abilities') { location.hash = abHref('_new'); return; }
    S.abSel = '_new';
    abSyncUrl();
    render();
  },
  /** 'id|card': 그 항목의 카드 하나를 고치는 칸으로 편다 */
  abEditOpen(arg) {
    const [id, card] = String(arg).split('|');
    const row = ((S.ab || {}).abilities || []).find((x) => x.ability.id === id);
    if (!row) return;
    S.abEdit = { card: card || 'base', a: JSON.parse(JSON.stringify(row.ability)) };
    S.focusTarget = card === 'grades' ? '#app [data-ab-grade="0"], #app [data-action="abGradeAdd"]' : '#ab-name';
    if (S.abSel !== id) { S.abSel = id; abSyncUrl(); }
    render();
  },
  abCancel() {
    const e = S.abEdit;
    S.abEdit = null;
    if (e && e.card === 'new') { S.abSel = ''; abSyncUrl(); S.focusTarget = '#app main h1'; } else if (e) S.focusTarget = `#ab-${e.card} [data-action="abEditOpen"]`;
    render();
  },
  abGradeAdd() {
    S.abEdit.a.grades.push({ grade: '', effect: '' });
    S.focusTarget = `#app [data-ab-grade="${S.abEdit.a.grades.length - 1}"]`;
    render();
  },
  abGradeDel(i) { S.abEdit.a.grades.splice(Number(i), 1); S.focusTarget = '#app [data-action="abGradeAdd"]'; render(); },
  abMissStat(s) { S.abMissStat = s; render(); },
  async abSave() {
    const e = S.abEdit;
    const a = e.a;
    if (!a.name.trim()) { toast('이름을 적어 주세요', true); return; }
    await run('도감 저장하는 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/abilities`, a);
      const saved = a.id || (S.project.abilities[S.project.abilities.length - 1] || {}).id;
      S.abEdit = null;
      await abReload(saved);
      abSyncUrl();
      S.focusTarget = e.card === 'new' ? '#app main h1' : `#ab-${e.card} [data-action="abEditOpen"]`;
      toast(`'${a.name.trim()}' 도감 항목을 저장했어요`);
    });
  },
  /** 쓰기 프롬프트에 넣는 방식(Ability.context)은 고르면 바로 저장한다 */
  async abContext(k) {
    const r = S.ab.abilities.find((x) => x.ability.id === S.abSel);
    if (!r || r.ability.context === k) return;
    S.focusTarget = `#app [data-action="abContext"][data-arg="${k}"]`;
    await run('도감 저장하는 중', async () => {
      S.project = await api('PUT', `/projects/${enc(S.name)}/abilities`, { ...r.ability, context: k });
      await abReload();
      toast(`쓰기 프롬프트에 넣기를 바꿨어요: ${AB_CONTEXT[k]}`);
    });
  },
  async abDelete(id) {
    const r = S.ab.abilities.find((x) => x.ability.id === id);
    if (!r || !confirm(`'${r.ability.name}' 도감 항목을 지울까요? 상태창 값은 그대로예요.`)) return;
    await run('도감 항목 지우는 중', async () => {
      S.project = await api('DELETE', `/projects/${enc(S.name)}/abilities/${enc(id)}`);
      S.abEdit = null;
      await abReload('');
      abSyncUrl();
      S.focusTarget = '#app main h1';
      toast('도감 항목을 지웠어요');
    });
  },
  async abCopyLine() {
    const text = (document.getElementById('ab-line-text') || {}).textContent || '';
    try {
      await navigator.clipboard.writeText(text);
      toast('AI에게 보이는 줄을 복사했어요');
    } catch (e) {
      toast('복사하지 못했어요. 줄을 직접 골라 복사하세요', true);
    }
  },
  /** 도감 카드: 공통 대화상자(showDialog). 칩을 누른 인물의 등급 효과 · 얻은 화 · 바뀐 기록을 함께 보인다 */
  async abShow(arg) {
    const [cid, stat, item] = String(arg).split('|').map(decodeURIComponent);
    const close = '<button type="button" class="btn icon-btn ghost" data-action="closeDialog" data-arg="ab-pop" aria-label="닫기">✕</button>';
    showDialog('ab-pop', `<div class="ab-pop"><div class="between"><h2 id="ab-pop-title">${esc(abSplit(item)[0])}</h2>${close}</div><div class="small" role="status">불러오는 중…</div></div>`);
    let r;
    try {
      r = await api('GET', `/projects/${enc(S.name)}/abilities/lookup?item=${encodeURIComponent(item)}&cid=${encodeURIComponent(cid)}&stat=${encodeURIComponent(stat)}`);
    } catch (e) {
      showDialog('ab-pop', `<div class="ab-pop"><div class="between"><h2 id="ab-pop-title">${esc(item)}</h2>${close}</div><div class="note err">${esc(e.message)}</div></div>`);
      return;
    }
    const title = `<div class="between"><h2 id="ab-pop-title">${esc(r.name)}${r.grade ? ` <span class="chip confirmed">${esc(r.grade)}</span>` : ''}</h2>${close}</div>`;
    const who = [abWho(cid), stat, r.ability ? abWhen(r.acquired) : ''].filter(Boolean).map(esc).join(' · ');
    if (!r.ability) {
      showDialog('ab-pop', `<div class="ab-pop">${title}<div class="small">${who}</div>
        <p>도감에 아직 없는 조각이에요. 설명 · 효과 · 대가를 적어 두면 여기에서 바로 보고, AI도 같은 설명을 따라요.</p>
        <div class="row dlg-foot"><button type="button" class="btn ghost" data-action="closeDialog" data-arg="ab-pop">닫기</button><button type="button" class="btn primary" data-action="abFromPop" data-arg="${esc(`${encodeURIComponent(stat)}|${encodeURIComponent(r.name)}`)}">도감에 만들기</button></div></div>`);
      return;
    }
    showDialog('ab-pop', `<div class="ab-pop">${title}<div class="small">${who}</div>
      ${r.grade_effect ? `<div class="note info"><strong>${esc(r.grade)}</strong> ${esc(r.grade_effect)}</div>` : ''}
      ${abFields(r.ability, r.grade)}
      ${(r.history || []).length > 1 ? `<div class="row"><span class="small">바뀐 기록</span>${abSteps(r.history)}</div>` : ''}
      <div class="row dlg-foot"><button type="button" class="btn ghost" data-action="abGoView" data-arg="${esc(r.ability.id)}">도감에서 보기</button><button type="button" class="btn" data-action="abGoEdit" data-arg="${esc(r.ability.id)}">도감에서 고치기</button></div></div>`);
  },
  abClose() { actions.closeDialog('ab-pop'); },
  abGoView(id) {
    actions.abClose();
    location.hash = abHref(id);
  },
  abGoEdit(id) {
    actions.abClose();
    S.abOpenId = id;  // abLoad 가 도감을 받은 뒤 설명 카드를 고치는 칸으로 연다
    location.hash = abHref(id);
  },
  abFromPop(arg) {
    const [stat, name] = String(arg).split('|').map(decodeURIComponent);
    actions.abClose();
    S.abEdit = { card: 'new', a: abBlank(name, stat) };
    S.abOwner = S.name;
    S.focusTarget = '#ab-name';
    location.hash = abHref('_new');
  },
});

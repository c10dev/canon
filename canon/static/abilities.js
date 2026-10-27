/* 스킬 도감 화면. app.js 의 S, actions, api, run, render, header, esc, P, base, enc, toast, saveIfDirty 를 쓴다.
   상태창 목록 항목(스킬 · 특성 · 칭호)의 조각마다 설명 · 효과 · 대가 · 등급별 효과를 적는다(Project.abilities).
   정의는 인물 사이에 하나이고, 가진 인물 · 등급 · 얻은 화 · 바뀐 기록 · AI 에게 보이는 줄은 서버가 계산한다(canon/abilities.py, /abilities).
   화면은 왼쪽 목록(상태창 항목별로 묶음, 찾기, 설명 없음만) + 오른쪽 상세(또는 고치는 칸). 주소는 abilities/<항목 id>.
   상태창 칩(인물 카드 · cast.js)을 누르면 뜨는 도감 카드는 abShow. */
'use strict';

Object.assign(S, {
  ab: null,          // 서버 값 { abilities: [{ ability, owners, line }], unlinked, lists }
  abSel: '',         // 고른 항목 id
  abEdit: null,      // 고치는 중인 항목 (Ability 모양). 새 항목은 id ''
  abQuery: '',       // 목록 찾기
  abMissOnly: false, // AI 에게 보일 줄이 없는(설명 · 효과 · 대가가 빈) 항목만
});

(function abStyle() {
  const css = `
.ab { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 20px; align-items: start; }
@media (max-width: 860px) { .ab { grid-template-columns: 1fr; } }
.ab-nav { display: flex; flex-direction: column; gap: 2px; }
.ab-nav .ab-grp { padding: 10px 10px 2px; font-size: 12px; color: var(--text-2); letter-spacing: 0.04em; }
.ab-nav a { display: flex; justify-content: space-between; gap: 8px; padding: 9px 12px; border-radius: 8px; color: var(--text); text-decoration: none; font-size: 14px; }
.ab-nav a[aria-current="page"] { background: var(--accent-soft); color: var(--accent-ink); font-weight: 700; }
.ab-nav a:hover { background: var(--bg); }
.ab-nav .ab-empty-dot { color: var(--amber-ink); }
.ab-pill { font-size: 12px; padding: 2px 9px; border-radius: 999px; background: var(--accent-soft); color: var(--accent-ink); white-space: nowrap; }
.ab-item { padding: 12px 14px; border: 1px solid var(--line); border-radius: 8px; display: flex; flex-direction: column; gap: 10px; }
.ab-kv, .ab-pop dl { margin: 0; display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 4px 14px; font-size: 14px; }
.ab-kv dt, .ab-pop dt { color: var(--text-2); font-size: 13px; }
.ab-kv dd, .ab-pop dd { margin: 0; overflow-wrap: anywhere; }
.ab-own { display: flex; flex-direction: column; gap: 8px; }
.ab-own > div { padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; display: flex; flex-direction: column; gap: 4px; }
.ab-hist { margin: 0; padding-left: 16px; font-size: 13px; color: var(--text-2); }
.ab-line { margin: 0; padding: 12px 14px; border-radius: 8px; background: var(--bg); font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 13px; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; }
.ab-grade { display: grid; grid-template-columns: 120px minmax(0, 1fr) auto; gap: 8px; align-items: center; }
@media (max-width: 520px) { .ab-grade { grid-template-columns: 1fr; } }
button.ab-chip { font: inherit; cursor: pointer; background: transparent; color: inherit; }
button.ab-chip:hover, button.ab-chip:focus-visible { text-decoration: underline; }
dialog.ab-pop { width: min(440px, calc(100vw - 32px)); border: 1px solid var(--line); border-radius: 10px; padding: 18px 20px; background: var(--surface); color: var(--text); }
dialog.ab-pop::backdrop { background: rgba(0, 0, 0, 0.35); }
.ab-pop .ab-body { display: flex; flex-direction: column; gap: 10px; }`;
  const el = document.createElement('style');
  el.textContent = css;
  document.head.appendChild(el);
}());

// 이름만 봐도 목록인 상태창 항목. abilities.LIST_NAMES 와 같다 (tests/test_statwin_js.py)
const AB_LIST_NAMES = ['스킬', '특성', '칭호', '능력', '특기', '기술', '무공', '절기', '마법', '축복', '권능', '재능'];
const abListName = (name) => AB_LIST_NAMES.some((w) => String(name).includes(w));
const abWho = (id) => (P().characters.find((c) => c.id === id) || {}).name || id;
const abWhen = (ep) => (ep === null || ep === undefined ? '' : ep === 0 ? '시작 때 얻음' : `${ep}화에 얻음`);
const AB_CONTEXT = { auto: '관련 있을 때', always: '항상', off: '넣지 않음' };
const abBlank = (name = '', stat = '') => ({ id: '', name, aliases: [], stat, description: '', effect: '', cost: '', grades: [], context: 'auto', source: 'author', created_ep: 0 });

async function abLoad(sel) {
  S.ab = await api('GET', `/projects/${enc(S.name)}/abilities`).catch((e) => ({ error: e.message }));
  const rows = (S.ab && S.ab.abilities) || [];
  if (sel && S.abEdit && S.abEdit.id !== sel && !S.abOpenId) S.abEdit = null;  // 목록에서 다른 항목을 고르면 고치던 칸을 닫는다
  if (sel) S.abSel = sel;
  if (!rows.some((r) => r.ability.id === S.abSel)) S.abSel = (rows[0] || { ability: {} }).ability.id || '';
  if (S.abOpenId) {  // 도감 카드의 '도감에서 고치기'
    const r = rows.find((x) => x.ability.id === S.abOpenId);
    if (r) S.abEdit = JSON.parse(JSON.stringify(r.ability));
    S.abOpenId = null;
  }
}

function viewAbilities() {
  const head = header('도구', '스킬 도감', '상태창의 스킬 · 특성 · 칭호마다 설명 · 효과 · 대가를 적어요. 같은 이름(Lv3 · B급 같은 등급 꼬리를 뗀 이름)이면 모든 인물에 한 설명을 써요. 가진 인물과 얻은 화는 상태창 기록에서 계산해요.',
    '<button type="button" class="btn primary" data-action="abNew" data-arg="">+ 항목</button>');
  const d = S.ab;
  if (!d) return `${head}<div class="small">불러오는 중…</div>`;
  if (d.error) return `${head}<div class="note err">${esc(d.error)}</div>`;
  if (!d.abilities.length && !d.unlinked.length && !S.abEdit) {
    return `${head}<div class="card empty"><p>상태창에 스킬 · 특성 · 칭호 목록이 아직 없어요. 인물 상태창에 '스킬' 같은 항목을 만들면 그 조각이 여기에 모여요.</p>
      <div class="row"><a class="btn primary" href="${base()}/statwin">상태창 수치로</a><button type="button" class="btn" data-action="abNew" data-arg="">빈 항목 만들기</button></div></div>`;
  }
  const empty = d.abilities.filter((r) => !r.line).length;
  const miss = d.unlinked.map((m) => `<button type="button" class="btn small" data-action="abNew" data-arg="${esc(`${m.stat}|${m.name}`)}" title="${esc(m.items.join(', '))} · ${esc(m.characters.map(abWho).join(', '))}">+ ${esc(m.name)} <span class="small">${esc(m.stat)}</span></button>`).join('');
  return `${head}
    <div class="row small"><span>${d.abilities.length}개 항목</span>${empty ? `<span>· AI에게 보일 줄이 없는 항목 ${empty}개</span>` : ''}${d.unlinked.length ? `<span>· 도감에 없는 조각 ${d.unlinked.length}개</span>` : ''}</div>
    ${miss ? `<section class="card tight"><div class="field"><span class="label">도감에 없는 항목 <span class="hint">누르면 그 이름으로 만들어요</span></span><div class="row" style="flex-wrap:wrap;gap:6px">${miss}</div></div></section>` : ''}
    <div class="ab">${abList()}<div style="display:flex;flex-direction:column;gap:16px;min-width:0">${S.abEdit ? abForm() : abDetail()}</div></div>`;
}

/** 왼쪽 목록: 상태창 항목별로 묶는다. 항목을 정하지 않은 것은 가진 인물의 상태창 항목으로, 그것도 없으면 '목록 지정 없음' */
function abList() {
  const q = S.abQuery.trim().toLowerCase();
  const rows = S.ab.abilities.filter(({ ability: a, line }) => (!S.abMissOnly || !line)
    && (!q || [a.name, ...a.aliases].some((x) => x.toLowerCase().includes(q))));
  const groupOf = (r) => r.ability.stat || (r.owners[0] || {}).stat || '목록 지정 없음';
  const groups = [...new Set([...S.ab.lists, ...rows.map(groupOf)])].filter((g) => rows.some((r) => groupOf(r) === g));
  const items = groups.map((g) => `<div class="ab-grp">${esc(g)}</div>` + rows.filter((r) => groupOf(r) === g).map((r) => {
    const a = r.ability;
    return `<a href="${base()}/abilities/${enc(a.id)}"${a.id === S.abSel && !S.abEdit ? ' aria-current="page"' : ''}><span>${esc(a.name)}${r.line ? '' : ' <span class="ab-empty-dot" title="AI에게 보일 줄이 없어요">·</span>'}</span><span class="small">${r.owners.length ? `${r.owners.length}명` : ''}</span></a>`;
  }).join('')).join('');
  return `<nav class="card tight ab-nav" aria-label="도감 항목">
    <input id="ab-q" type="search" value="${esc(S.abQuery)}" placeholder="이름 찾기" aria-label="도감 항목 찾기" data-ab-query="1">
    <label class="row small" style="gap:6px;padding:6px 4px"><input type="checkbox" id="ab-miss" data-ab-miss="1"${S.abMissOnly ? ' checked' : ''}>AI에게 보일 줄이 없는 것만</label>
    ${items || '<div class="small" style="padding:8px">맞는 항목이 없어요.</div>'}</nav>`;
}

/** 설명 · 효과 · 대가 · 등급별 효과. 빈 칸은 뺀다. here 는 강조할 등급 */
function abFields(a, here = '') {
  const row = (k, v) => (v ? `<dt>${k}</dt><dd>${esc(v)}</dd>` : '');
  const gs = (a.grades || []).map((g) => `<dt>${esc(g.grade)}</dt><dd>${g.grade === here ? `<strong>${esc(g.effect)}</strong>` : esc(g.effect)}</dd>`).join('');
  const all = row('설명', a.description) + row('효과', a.effect) + row('대가', a.cost) + gs;
  return all ? `<dl class="ab-kv">${all}</dl>` : '<div class="small">설명 · 효과 · 대가가 비어 있어요.</div>';
}

function abDetail() {
  const r = S.ab.abilities.find((x) => x.ability.id === S.abSel);
  if (!r) return '<section class="card"><div class="small">왼쪽에서 항목을 고르거나, 도감에 없는 항목을 눌러 만드세요.</div></section>';
  const a = r.ability;
  const own = r.owners.map((o) => `<div><div class="between"><span><a href="${base()}/cast/c:${enc(o.character_id)}?tab=sheet">${esc(abWho(o.character_id))}</a> · ${esc(o.item)}</span><span class="small">${esc(o.stat)}${o.acquired !== null ? ` · ${abWhen(o.acquired)}` : ''}</span></div>
      ${o.grade_effect ? `<span class="small"><strong>${esc(o.grade)}</strong> ${esc(o.grade_effect)}</span>` : ''}
      ${o.history.length > 1 ? `<details><summary class="small">바뀐 기록 ${o.history.length}</summary><ul class="ab-hist">${o.history.map((h) => `<li>${h.episode ? `${h.episode}화` : '시작 때'} · ${h.kind === '얻음' ? `얻음 ${esc(h.item)}` : h.kind === '잃음' ? `잃음 ${esc(h.before)}` : `${esc(h.before)} → ${esc(h.item)}`}</li>`).join('')}</ul></details>` : ''}</div>`).join('');
  const why = a.context === 'off' ? "'넣지 않음'으로 두어 AI에게 보이지 않아요."
    : !r.line ? '설명 · 효과 · 대가가 비어 있어 AI에게 보일 줄이 없어요.'
      : a.context === 'always' ? "'항상'으로 두면 그 화에 누가 나오든 넣어요."
        : '그 화에 나오는 인물이 가졌거나 플롯에 이름이 나올 때 넣어요.';
  return `<section class="card">
      <div class="between"><h2>${esc(a.name)}${a.aliases.length ? ` <span class="small">(${esc(a.aliases.join(', '))})</span>` : ''}</h2>
        <span class="row" style="gap:6px">${a.stat ? `<span class="ab-pill">${esc(a.stat)}</span>` : ''}<span class="ab-pill">AI: ${AB_CONTEXT[a.context] || a.context}</span><button type="button" class="btn small" data-action="abEditOpen" data-arg="${esc(a.id)}">고치기</button></span></div>
      ${abFields(a)}
    </section>
    <section class="card"><h2>가진 인물 <span class="small">${r.owners.length}명</span></h2>
      ${own ? `<div class="ab-own">${own}</div>` : '<div class="small">지금 이 항목을 가진 인물이 없어요. 상태창 목록에 이 이름이 있으면 여기에 보여요.</div>'}</section>
    <section class="card"><div class="between"><h2>AI에게 보이는 줄</h2>${r.line ? '<button type="button" class="btn small" data-action="abCopyLine">복사</button>' : ''}</div>
      ${r.line ? `<pre class="ab-line" id="ab-line">${esc(r.line)}</pre>` : ''}
      <div class="small">${why} 다음 화를 쓸 때(지금 상태창) 기준이에요. 이 줄은 다음 업데이트부터 쓰기 · 검수 프롬프트에 들어가요. 지금은 미리 보기예요.</div></section>`;
}

function abForm() {
  const a = S.abEdit;
  const lists = (S.ab && S.ab.lists) || [];
  const opts = ['', ...new Set([...lists, ...(a.stat ? [a.stat] : [])])].map((x) => `<option value="${esc(x)}"${x === a.stat ? ' selected' : ''}>${x ? esc(x) : '어느 목록이든'}</option>`).join('');
  const ctx = Object.entries(AB_CONTEXT).map(([k, v]) => `<option value="${k}"${k === a.context ? ' selected' : ''}>${v}</option>`).join('');
  const grades = a.grades.map((g, i) => `<div class="ab-grade"><input type="text" data-ab-grade="${i}" data-ab-gkey="grade" value="${esc(g.grade)}" placeholder="등급 (예: Lv3)" aria-label="등급 ${i + 1}">
      <input type="text" data-ab-grade="${i}" data-ab-gkey="effect" value="${esc(g.effect)}" placeholder="이 등급의 효과" aria-label="등급 ${i + 1} 효과">
      <button type="button" class="btn small ghost" data-action="abGradeDel" data-arg="${i}" aria-label="등급 ${i + 1} 지우기">지우기</button></div>`).join('');
  const f = (k, label, hint, rows) => `<div class="field"><label for="ab-${k}">${label}${hint ? ` <span class="hint">${hint}</span>` : ''}</label>${rows
    ? `<textarea id="ab-${k}" data-ab-field="${k}" rows="${rows}">${esc(a[k])}</textarea>` : `<input id="ab-${k}" type="text" data-ab-field="${k}" value="${esc(a[k])}">`}</div>`;
  return `<section class="card"><h2>${a.id ? `${esc(a.name)} 고치기` : '새 도감 항목'}</h2>
    <div class="grid-2">${f('name', '이름', '등급 꼬리 없이 (예: 화염구)')}<div class="field"><label for="ab-stat">상태창 항목</label><select id="ab-stat" data-ab-field="stat">${opts}</select></div></div>
    <div class="field"><label for="ab-aliases">다른 이름 <span class="hint">쉼표로. 상태창이나 본문에서 이 이름도 같은 것으로 봐요</span></label><input id="ab-aliases" type="text" data-ab-field="aliases" value="${esc(a.aliases.join(', '))}"></div>
    ${f('description', '설명', '', 2)}${f('effect', '효과', 'AI에게 보이는 줄에 들어가요', 2)}${f('cost', '대가 · 제약', '쿨타임, 마력 소모, 수명 같은 것', 2)}
    <div class="field"><span class="label">등급별 효과 <span class="hint">상태창 조각의 꼬리와 같게 적으면 가진 인물의 등급 효과로 보여요</span></span>${grades}<div><button type="button" class="btn small" data-action="abGradeAdd">+ 등급</button></div></div>
    <div class="field"><label for="ab-context">AI 프롬프트에 넣기</label><select id="ab-context" data-ab-field="context" style="width:auto">${ctx}</select></div>
    <div class="between">${a.id ? '<button type="button" class="btn small danger" data-action="abDelete">삭제</button>' : '<span></span>'}
      <span class="row" style="gap:6px"><button type="button" class="btn small ghost" data-action="abCancel">취소</button><button type="button" class="btn small primary" data-action="abSave">저장</button></span></div>
  </section>`;
}

/** 상태창 칩: 누르면 도감 카드. 목록 항목 조각에만 쓴다 (cast.js) */
function abChip(cid, stat, item, cls) {
  return `<button type="button" class="${cls} ab-chip" data-action="abShow" data-arg="${esc([cid, stat, item].map(encodeURIComponent).join('|'))}" aria-haspopup="dialog">${esc(item)}</button>`;
}

function abDialog() {
  let el = document.getElementById('ab-pop');
  if (!el) {
    el = document.createElement('dialog');
    el.id = 'ab-pop';
    el.className = 'ab-pop';
    el.setAttribute('aria-labelledby', 'ab-pop-title');
    el.addEventListener('click', (e) => { if (e.target === el) el.close(); });  // 바깥(배경)을 누르면 닫는다
    document.body.appendChild(el);
  }
  return el;
}

document.addEventListener('input', (e) => {
  const d = e.target.dataset || {};
  if (d.abQuery) {
    S.abQuery = e.target.value;
    const nav = document.querySelector('.ab-nav');
    if (nav) {  // 목록만 다시 그리고 찾기 칸 포커스를 지킨다
      const pos = e.target.selectionStart;
      nav.outerHTML = abList();
      const q = document.getElementById('ab-q');
      if (q) { q.focus(); q.setSelectionRange(pos, pos); }
    }
    return;
  }
  if (!S.abEdit) return;
  if (d.abField) S.abEdit[d.abField] = d.abField === 'aliases' ? e.target.value.split(/\s*,\s*/).filter(Boolean) : e.target.value;
  if (d.abGrade !== undefined) S.abEdit.grades[Number(d.abGrade)][d.abGkey] = e.target.value;
});
document.addEventListener('change', (e) => {
  const d = e.target.dataset || {};
  if (d.abMiss) { S.abMissOnly = e.target.checked; render(); return; }
  if (S.abEdit && (d.abField === 'stat' || d.abField === 'context')) S.abEdit[d.abField] = e.target.value;
});

async function abReload(sel) {
  S.ab = await api('GET', `/projects/${enc(S.name)}/abilities`);
  if (sel) S.abSel = sel;
}

Object.assign(actions, {
  abNew(arg) {
    const [stat, ...rest] = String(arg || '').split('|');
    S.abEdit = abBlank(rest.join('|'), arg ? stat : '');
    if (location.hash.split('/')[3] !== 'abilities') { location.hash = `${base()}/abilities`; return; }
    render();
    setTimeout(() => { const el = document.getElementById('ab-name'); if (el) el.focus(); }, 0);
  },
  abEditOpen(id) {
    const row = ((S.ab || {}).abilities || []).find((x) => x.ability.id === id);
    if (!row) return;
    S.abEdit = JSON.parse(JSON.stringify(row.ability));
    render();
    setTimeout(() => { const el = document.getElementById('ab-name'); if (el) el.focus(); }, 0);
  },
  abCancel() { S.abEdit = null; render(); },
  abGradeAdd() { S.abEdit.grades.push({ grade: '', effect: '' }); render(); },
  abGradeDel(i) { S.abEdit.grades.splice(Number(i), 1); render(); },
  async abSave() {
    const a = S.abEdit;
    if (!a.name.trim()) { toast('이름을 적어 주세요', true); return; }
    await run('도감 저장 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/abilities`, a);
      const saved = a.id || (S.project.abilities[S.project.abilities.length - 1] || {}).id;
      S.abEdit = null;
      await abReload(saved);
      toast(`'${a.name.trim()}' 도감 항목을 저장했어요`);
      const here = `${base()}/abilities/${enc(saved)}`;
      if (location.hash !== here) history.replaceState(null, '', here);  // 주소도 저장한 항목으로 (다시 읽지 않는다)
    });
  },
  async abDelete() {
    const a = S.abEdit;
    if (!a || !a.id || !confirm(`'${a.name}' 도감 항목을 지울까요? 상태창 값은 그대로예요.`)) return;
    await run('도감 항목 지우는 중', async () => {
      S.project = await api('DELETE', `/projects/${enc(S.name)}/abilities/${enc(a.id)}`);
      S.abEdit = null;
      S.abSel = '';
      await abLoad();
      toast('도감 항목을 지웠어요');
      history.replaceState(null, '', `${base()}/abilities${S.abSel ? `/${enc(S.abSel)}` : ''}`);
    });
  },
  async abCopyLine() {
    const text = (document.getElementById('ab-line') || {}).textContent || '';
    try {
      await navigator.clipboard.writeText(text);
      toast('AI에게 보이는 줄을 복사했어요');
    } catch (e) {
      toast('복사하지 못했어요. 줄을 직접 골라 복사하세요', true);
    }
  },
  async abShow(arg) {
    const [cid, stat, item] = String(arg).split('|').map(decodeURIComponent);
    const el = abDialog();
    const back = document.activeElement;
    el.innerHTML = '<div class="small" role="status">불러오는 중…</div>';
    if (!el.open) el.showModal();
    el.onclose = () => { if (back && back.focus) back.focus(); };
    let r;
    try {
      r = await api('GET', `/projects/${enc(S.name)}/abilities/lookup?item=${encodeURIComponent(item)}&cid=${encodeURIComponent(cid)}&stat=${encodeURIComponent(stat)}`);
    } catch (e) {
      el.innerHTML = `<div class="note err">${esc(e.message)}</div><button type="button" class="btn small" data-action="abClose">닫기</button>`;
      return;
    }
    const head = `<div class="between"><strong id="ab-pop-title">${esc(r.name)}${r.grade ? ` <span class="small">${esc(r.grade)}</span>` : ''}</strong><button type="button" class="btn small" data-action="abClose">닫기</button></div>
      <div class="small">${esc(abWho(cid))} · ${esc(stat)}</div>`;
    if (!r.ability) {
      el.innerHTML = `<div class="ab-body">${head}<div class="small">도감에 없는 항목이에요. 설명 · 효과 · 대가를 적어 두면 화면에서 바로 볼 수 있어요.</div>
        <div><button type="button" class="btn small primary" data-action="abFromPop" data-arg="${esc(`${encodeURIComponent(stat)}|${encodeURIComponent(r.name)}`)}">도감에 만들기</button></div></div>`;
      return;
    }
    const hist = (r.history || []).map((h) => `<li>${h.episode ? `${h.episode}화` : '시작 때'} · ${h.kind === '얻음' ? `얻음 ${esc(h.item)}` : h.kind === '잃음' ? `잃음 ${esc(h.before)}` : `${esc(h.before)} → ${esc(h.item)}`}</li>`).join('');
    el.innerHTML = `<div class="ab-body">${head}
      ${r.grade_effect ? `<div class="note plain"><strong>${esc(r.grade)}</strong> ${esc(r.grade_effect)}</div>` : ''}
      ${abFields(r.ability, r.grade)}
      ${r.acquired !== null && r.acquired !== undefined ? `<div class="small">${abWhen(r.acquired)}</div>` : ''}
      ${hist ? `<details><summary class="small">바뀐 기록 ${r.history.length}</summary><ul class="ab-hist">${hist}</ul></details>` : ''}
      <div class="row" style="gap:6px"><button type="button" class="btn small" data-action="abGoView" data-arg="${esc(r.ability.id)}">도감에서 보기</button><button type="button" class="btn small" data-action="abGoEdit" data-arg="${esc(r.ability.id)}">고치기</button></div></div>`;
  },
  abClose() { const el = document.getElementById('ab-pop'); if (el && el.open) el.close(); },
  abGoView(id) {
    actions.abClose();
    location.hash = `${base()}/abilities/${enc(id)}`;
  },
  abGoEdit(id) {
    actions.abClose();
    S.abOpenId = id;  // abLoad 가 도감을 받은 뒤 고치기 칸을 연다
    location.hash = `${base()}/abilities/${enc(id)}`;
  },
  abFromPop(arg) {
    const [stat, name] = String(arg).split('|').map(decodeURIComponent);
    actions.abClose();
    S.abEdit = abBlank(name, stat);
    location.hash = `${base()}/abilities`;
  },
});

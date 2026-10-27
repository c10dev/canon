/* 상태창 수치. app.js 의 S, actions, api, run, render, header, esc, P 를 쓴다.
   게임 판타지 · 헌터물처럼 레벨, 능력치, 스킬 · 특성 · 칭호 목록, 돈, 인벤토리가 나오는 작품에서 인물별 상태창(CharacterState.stats)을 정하고,
   화마다 바뀐 기록(Project.stat_log)으로 비교표를 그린다. 본문에 넣을 상태창 글을 복사한다.
   설정 화면의 상태창 카드(swSetupCard): 1화 전에 작품 틀과 인물별 처음 수치를 표로 정하고, AI 처음 수치 제안을 인물마다 골라 넣는다.
   스킬 · 특성 도감(swDex): 목록 항목 조각마다 설명 · 효과 · 대가 · 등급별 효과를 둔다. 정의는 인물 사이에 하나, 얻은 화는 서버가 기록에서 계산한다
   (canon/abilities.py, /abilities). 상태창 칩을 누르면 뜨는 도감 카드는 abShow.
   꾸미기: 작품 설정에 맞춘 본문 서식 · 창 이름 · 작품 틀 · 화면 스킨 안을 AI 에게 받아 고른 안만 적용한다(swDecor).
   서버는 canon/statwin.py (/statwin/<인물 id>, /statwin-suggest). AI 가 적은 바뀐 값은 상태 승인 화면에서 고른 뒤에만 반영된다(swDeltaRows). */
'use strict';

Object.assign(S, {
  sw: null,          // 서버 값 { names, columns, current, text, presets }
  swCid: '',         // 보고 있는 인물
  swRows: [],        // 고치는 중인 항목 [{name, value}]
  swDirty: false,
  swTpl: false,      // 서식 고치기 칸 열림
  swSug: null,       // AI 꾸미기 안 { options } (저장하지 않음)
  swPrev: null,      // 마지막으로 적용한 꾸미기 안 앞의 서식 (적용 취소용)
  swInit: null,      // 설정 화면 처음 수치 표의 고치는 중인 값 { 인물 id: { 항목: 값 } }. null 이면 작품에서 다시 읽는다
  swInitDirty: false,
  swInitSug: null,   // AI 처음 수치 제안 { names, characters } (저장하지 않음)
  swInitAll: false,  // 단역도 표에 보이기
  ab: null,          // 도감 서버 값 { abilities: [{ ability, owners }], unlinked, lists }
  abEdit: null,      // 고치는 중인 도감 항목 (Ability 모양). 새 항목은 id ''
});

// 상태창 틀. statwin.PRESETS 와 같다 (tests/test_statwin_js.py)
const SW_PRESETS = {
  game: ['레벨', 'HP', 'MP', '힘', '민첩', '체력', '지능', '스킬'],
  hunter: ['등급', '레벨', '마력', '스킬', '칭호'],
  simple: ['레벨', '스킬'],
  growth: ['레벨', '스킬', '특성', '칭호', '골드', '인벤토리'],
};
const SW_PRESET_LABELS = { game: '게임 판타지', hunter: '헌터물', simple: '레벨 · 스킬', growth: '스킬 · 특성 · 돈' };

// 화면 스킨 이름. statwin.SKINS 와 같은 키
const SW_SKINS = { system: '시스템 창', parchment: '양피지', scroll: '두루마리', neon: '네온', plain: '담백한 서류' };
const swWin = () => P().stat_window || {};
const swSkin = () => (SW_SKINS[swWin().skin] ? swWin().skin : 'system');
const swTitle = () => (swWin().title || '').trim() || '상태창';

(function swStyle() {
  const css = `
.sw { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 20px; align-items: start; }
@media (max-width: 860px) { .sw { grid-template-columns: 1fr; } }
.sw-who { display: flex; flex-direction: column; gap: 4px; }
.sw-who a { display: flex; justify-content: space-between; gap: 8px; padding: 10px 12px; border-radius: 8px; color: var(--text); text-decoration: none; font-size: 14px; }
.sw-who a[aria-current="page"] { background: var(--accent-soft); color: var(--accent-ink); font-weight: 700; }
.sw-who a:hover { background: var(--bg); }
.sw-rows { display: flex; flex-direction: column; gap: 8px; }
.sw-row { display: grid; grid-template-columns: 160px minmax(0, 1fr) auto; gap: 8px; align-items: center; }
.sw-text { margin: 0; padding: 14px 16px; border-radius: 8px; background: var(--bg); font-family: var(--serif); font-size: 14px; line-height: 1.7; white-space: pre-wrap; }
.sw-table-wrap { overflow-x: auto; }
.sw-table { border-collapse: collapse; font-size: 13px; min-width: 100%; }
.sw-table th, .sw-table td { padding: 8px 10px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }
.sw-table th { font-weight: 700; color: var(--text-2); background: var(--surface); }
.sw-table th:first-child { position: sticky; left: 0; }
.sw-table td.ch { background: var(--accent-soft); color: var(--accent-ink); font-weight: 700; }
.sw-table td.ch.author { background: var(--amber-soft); color: var(--amber-ink); }
.sw-table td.gone { color: var(--muted); text-decoration: line-through; }
.sw-diff { font-size: 12px; font-weight: 400; }
.sw-skins { display: flex; flex-wrap: wrap; gap: 6px; }
.sw-skins button[aria-pressed="true"] { background: var(--accent-soft); border-color: var(--accent); color: var(--accent-ink); font-weight: 700; }
.sw-opts { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.sw-opt { padding: 14px; border: 1px solid var(--line); border-radius: 8px; display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.sw-opt h3 { margin: 0; font-size: 15px; }
.sw-opt .sw-text { font-size: 13px; overflow-x: auto; }
.sw-opt .sw-sys { padding: 12px 14px; gap: 8px; font-size: 13px; }
.ab-list { display: flex; flex-direction: column; gap: 10px; }
.ab-item { padding: 12px 14px; border: 1px solid var(--line); border-radius: 8px; display: flex; flex-direction: column; gap: 6px; }
.ab-item dl, .ab-pop dl { margin: 0; display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 4px 12px; font-size: 14px; }
.ab-item dt, .ab-pop dt { color: var(--text-2); font-size: 13px; }
.ab-item dd, .ab-pop dd { margin: 0; overflow-wrap: anywhere; }
.ab-grade { display: grid; grid-template-columns: 120px minmax(0, 1fr) auto; gap: 8px; align-items: center; }
button.ab-chip { font: inherit; cursor: pointer; background: transparent; color: inherit; }
button.ab-chip:hover, button.ab-chip:focus-visible { text-decoration: underline; }
dialog.ab-pop { width: min(440px, calc(100vw - 32px)); border: 1px solid var(--line); border-radius: 10px; padding: 18px 20px; background: var(--surface); color: var(--text); }
dialog.ab-pop::backdrop { background: rgba(0, 0, 0, 0.35); }
.ab-pop .ab-body { display: flex; flex-direction: column; gap: 10px; }`;
  const el = document.createElement('style');
  el.textContent = css;
  document.head.appendChild(el);
}());

async function swLoad(cid) {
  S.ab = await api('GET', `/projects/${enc(S.name)}/abilities`).catch((e) => ({ error: e.message }));
  const open = S.abOpenId && ((S.ab || {}).abilities || []).find((x) => x.ability.id === S.abOpenId);
  if (open) S.abEdit = JSON.parse(JSON.stringify(open.ability));
  S.abOpenId = null;
  const chars = P().characters;
  const has = (id) => (P().states.find((s) => s.character_id === id) || {}).stats?.length;
  if (cid) S.swCid = cid;
  if (!chars.some((c) => c.id === S.swCid)) S.swCid = (chars.find((c) => has(c.id)) || chars.find((c) => c.tier === 'main') || chars[0] || {}).id || '';
  if (!S.swCid) { S.sw = null; return; }
  S.sw = await api('GET', `/projects/${enc(S.name)}/statwin/${enc(S.swCid)}`).catch((e) => ({ error: e.message }));
  S.swRows = (S.sw.current || []).map((s) => ({ ...s }));
  S.swDirty = false;
}

// statwin.py 의 _AMOUNT · _DELTA · _SPLIT · _GRADE 와 같다
const SW_AMOUNT = /^([^\d\s,+-]{0,4})(\s?)(-?\d[\d,]*(?:\.\d+)?)(\s?)([^\d\s,]{0,6})$/;
const SW_DELTA = /^([+-])\s?([^\d\s,+-]{0,4})\s?(\d[\d,]*(?:\.\d+)?)\s?([^\d\s,]{0,6})$/;
const SW_SPLIT = /\s*(?:,|、| · )\s*/;
const SW_GRADE = /\s*(?:\([^()]*\)|\[[^[\]]*\]|lv\.?\s*\d+|\+\d+|\d+\s*(?:레벨|단계|성|강|개))$/i;

function swFmt(x, commas) {
  let s = x.toFixed(2);
  if (commas) {
    const [i, f] = s.split('.');
    s = `${i.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${f}`;
  }
  s = s.replace(/0+$/, '').replace(/\.$/, '');
  return s === '-0' || s === '' ? '0' : s;
}

function swItems(text) { return String(text || '').trim().split(SW_SPLIT).filter(Boolean); }

function swKey(item) {
  let k = item.trim();
  for (;;) {
    const k2 = k.replace(SW_GRADE, '').trim();
    if (k2 === k || !k2) return k.toLowerCase();
    k = k2;
  }
}

/** statwin.resolve 와 같은 규칙: 수치는 +3 · +300 을 단위와 쉼표를 지켜 계산하고, 목록은 +이름 붙이기 · -이름 빼기. 그 밖에는 적은 그대로. */
function swResolve(before, value) {
  const v = String(value).trim();
  const b = String(before || '').trim();
  const d = v.match(SW_DELTA);
  const a = b.match(SW_AMOUNT);
  if (d && a && (!d[2] || d[2] === a[1]) && (!d[4] || d[4] === a[5])) {
    const x = Number(a[3].replace(/,/g, '')) + (d[1] === '+' ? 1 : -1) * Number(d[3].replace(/,/g, ''));
    return `${a[1]}${a[2]}${swFmt(x, a[3].includes(','))}${a[4]}${a[5]}`;
  }
  const ops = [];
  for (const part of swItems(v)) {
    const name = part.slice(1).trim();
    if (!'+-'.includes(part[0]) || !name || /^\d/.test(name)) return v;
    ops.push([part[0], name]);
  }
  if (!ops.length || a) return v;
  const cur = swItems(b);
  for (const [op, name] of ops) {
    let at = cur.indexOf(name);
    if (at < 0) at = cur.findIndex((x) => swKey(x) === swKey(name));
    if (op === '-') { if (at >= 0) cur.splice(at, 1); } else if (at < 0) cur.push(name); else cur[at] = name;
  }
  const m = b.match(SW_SPLIT);
  const sep = m ? ({ '、': '、', '·': ' · ' }[m[0].trim()] || ', ') : ', ';
  return cur.join(sep);
}

/** statwin.render 와 같은 규칙: 값이 빈 항목은 빼고 {name} · {rows} 를 채운다 */
function swRender(tpl, row, name, rows) {
  const lines = rows.filter((s) => String(s.value || '').trim()).map((s) => row.split('{key}').join(s.name).split('{value}').join(s.value)).join('\n');
  return tpl.split('{name}').join(name).split('{rows}').join(lines).trim();
}

/** 화면 스킨으로 그린 상태창. 인물 카드(cast.js castSheetStats)와 같은 칸 모양 */
function swBox(skin, title, name, rows) {
  const dd = (v) => {
    const list = String(v).match(SW_AMOUNT) ? [] : swItems(v);
    return list.length > 1 ? list.map((x) => `<span class="sw-sys-tag">${esc(x)}</span>`).join('') : `<span>${esc(v || '—')}</span>`;
  };
  return `<div class="sw-sys sw-skin-${esc(skin)}" role="group" aria-label="${esc(SW_SKINS[skin] || skin)} 미리 보기"><div class="sw-sys-title">【 ${esc(title)} 】</div>
    <dl><dt>이름</dt><dd>${esc(name)}</dd>${rows.map((s) => `<dt>${esc(s.name)}</dt><dd>${dd(s.value)}</dd>`).join('')}</dl></div>`;
}

/** 미리 보기에 쓸 항목: 보고 있는 인물의 값, 없으면 이름만 */
function swSample(names) {
  const rows = S.swRows.filter((r) => r.name.trim() && r.value.trim());
  return rows.length ? rows : (names || []).map((name) => ({ name, value: '—' }));
}

function swDecor() {
  const c = P().characters.find((x) => x.id === S.swCid) || {};
  const who = c.name || c.id || '이름';
  const skins = Object.entries(SW_SKINS).map(([k, label]) => `<button type="button" class="btn small" data-action="swSkinPick" data-arg="${k}" aria-pressed="${k === swSkin()}">${label}</button>`).join('');
  const opts = ((S.swSug || {}).options || []).map((o, i) => `<div class="sw-opt">
      <div class="between"><h3>${esc(o.label)}</h3><span class="small">${esc(SW_SKINS[o.skin] || o.skin)}</span></div>
      ${o.why ? `<div class="small">${esc(o.why)}</div>` : ''}
      <pre class="sw-text">${esc(swRender(o.template, o.row, who, swSample(o.names)))}</pre>
      ${swBox(o.skin, o.title, who, swSample(o.names))}
      ${o.names.length ? `<div class="small">작품 틀: ${esc(o.names.join(', '))}</div>` : ''}
      <button type="button" class="btn small primary" data-action="swUseOpt" data-arg="${i}">이 안 적용</button></div>`).join('');
  return `<section class="card"><div class="between"><h2>꾸미기</h2>${S.swPrev ? '<button type="button" class="btn small ghost" data-action="swUndoOpt">적용 취소</button>' : ''}</div>
    <div class="field"><label for="sw-title">창 이름 <span class="hint">화면 상태창 머리에 보여요 (예: 상태창, 무공록)</span></label>
      <div class="row"><input id="sw-title" type="text" value="${esc(swTitle())}"><button type="button" class="btn small" data-action="swTitleSave">저장</button></div></div>
    <div class="field"><span class="label">화면 스킨 <span class="hint">인물 카드와 여기에서 상태창을 그리는 모양이에요. 본문 글에는 들어가지 않아요</span></span><div class="sw-skins" role="group" aria-label="화면 스킨">${skins}</div></div>
    ${swBox(swSkin(), swTitle(), who, swSample(swWin().names))}
    <div class="field"><label for="sw-req">설정에 맞게 꾸미기 <span class="hint">AI가 장르 · 배경 · 세계관 규칙을 읽고 본문 서식, 창 이름, 항목 틀, 스킨을 한 벌씩 제안해요</span></label>
      <div class="row"><input id="sw-req" type="text" placeholder="요청 (비워도 돼요. 예: 더 어둡게, 마법 학교 느낌)"><button type="button" class="btn small primary" data-action="swSuggest">AI 제안 받기</button></div></div>
    ${opts ? `<div class="sw-opts">${opts}</div><div class="small">적용하면 본문 서식 · 창 이름 · 스킨 · 작품 틀이 함께 바뀌어요. 인물의 항목 이름과 값은 그대로예요. 작품 틀은 '지금 상태창'의 '작품 틀' 버튼으로 더해요.</div>` : ''}
  </section>`;
}

function swEditor() {
  const rows = S.swRows.map((r, i) => `<div class="sw-row">
      <input type="text" data-sw-name="${i}" value="${esc(r.name)}" aria-label="항목 이름" placeholder="항목 (예: 레벨)">
      <input type="text" data-sw-value="${i}" value="${esc(r.value)}" aria-label="${esc(r.name || '항목')} 값" placeholder="값 (+3은 더하기, 목록은 +독 내성 · -은신)">
      <button type="button" class="btn small ghost" data-action="swDel" data-arg="${i}" aria-label="${esc(r.name || '항목')} 지우기">지우기</button></div>`).join('');
  const work = (swWin().names || []).filter((x) => !S.swRows.some((r) => r.name === x));
  const workBtn = work.length ? `<button type="button" class="btn small" data-action="swPreset" data-arg="_work" title="${esc(work.join(', '))}">작품 틀</button>` : '';
  const presets = Object.entries((S.sw && S.sw.presets) || {}).map(([k, names]) => `<button type="button" class="btn small" data-action="swPreset" data-arg="${k}" title="${esc(names.join(', '))}">${SW_PRESET_LABELS[k] || k}</button>`).join('');
  return `<section class="card"><div class="between"><h2>지금 상태창</h2><span class="small">${S.sw.columns.length ? `${S.sw.columns[S.sw.columns.length - 1].episode}화까지 기록` : '기록 없음'}</span></div>
    <div class="sw-rows">${rows || '<div class="small">항목이 없어요. 아래에서 항목을 더하거나 틀을 고르세요.</div>'}</div>
    <div class="row"><button type="button" class="btn small" data-action="swAdd">+ 항목</button>${S.swRows.length ? workBtn : `<span class="small">틀:</span>${workBtn}${presets}`}</div>
    <div class="between"><span class="small">저장하면 마지막으로 반영한 화의 작가 기록으로 남아요. 값을 비운 항목은 틀만 남고, 지운 항목은 '지움'으로 기록돼요.</span>
      <button type="button" class="btn primary small" data-action="swSave"${S.swDirty ? '' : ' disabled'}>저장</button></div></section>`;
}

function swPreview() {
  const w = P().stat_window || { template: '', row: '' };
  return `<section class="card"><div class="between"><h2>본문에 넣을 상태창</h2>
      <span class="row" style="gap:6px"><button type="button" class="btn small" data-action="swTplToggle">${S.swTpl ? '서식 닫기' : '서식 고치기'}</button><button type="button" class="btn small primary" data-action="swCopy">복사</button></span></div>
    <pre class="sw-text">${esc(S.sw.text || '(값이 있는 항목이 없어요)')}</pre>
    ${S.swTpl ? `<div class="field"><label for="sw-tpl">상태창 서식 <span class="hint">{name} 인물 이름, {rows} 항목 줄</span></label><textarea id="sw-tpl" rows="4">${esc(w.template)}</textarea></div>
      <div class="field"><label for="sw-row">항목 한 줄 <span class="hint">{key} 항목, {value} 값</span></label><input id="sw-row" type="text" value="${esc(w.row)}"></div>
      <div class="row"><button type="button" class="btn small primary" data-action="swTplSave">서식 저장</button><span class="small">AI가 본문에 상태창을 쓸 때도 이 서식을 따라요.</span></div>` : ''}
  </section>`;
}

function swTimeline() {
  const t = S.sw;
  if (!t.columns.length) return '<section class="card"><h2>화별 변화</h2><div class="small">아직 기록이 없어요. 상태 승인 화면에서 AI가 적은 수치를 반영하거나, 위에서 값을 저장하면 쌓여요.</div></section>';
  const cols = t.columns;
  const head = `<tr><th scope="col">항목</th>${cols.map((c) => `<th scope="col">${c.episode ? `<a href="${base()}/review/${c.episode}">${c.episode}화</a>` : '시작'}</th>`).join('')}</tr>`;
  const body = t.names.map((name) => `<tr><th scope="row">${esc(name)}</th>${cols.map((c) => {
    const ch = c.changed[name];
    const v = c.values[name];
    if (!ch) return `<td>${esc(v || '')}</td>`;
    const src = ch.source === 'ai' ? '' : ' author';
    const tip = `${ch.before || '없음'} → ${v || '지움'}${{ ai: '', author: ' (작가)', both: ' (승인 뒤 작가가 고침)' }[ch.source] || ''}`;
    const lst = [...(ch.added || []).map((x) => `+${x}`), ...(ch.removed || []).map((x) => `−${x}`)];
    const sub = lst.length ? `<div class="sw-diff">${esc(lst.join(' '))}</div>` : '';
    return v ? `<td class="ch${src}" title="${esc(tip)}">${esc(v)}${sub}</td>` : `<td class="gone" title="${esc(tip)}">${esc(ch.before)}</td>`;
  }).join('')}</tr>`).join('');
  return `<section class="card"><div class="between"><h2>화별 변화</h2><div class="legend"><span><i style="background:var(--accent-soft);border:1px solid var(--accent)"></i>AI 변경안으로 바뀜</span><span><i style="background:var(--amber-soft);border:1px solid var(--amber)"></i>작가가 고침</span></div></div>
    <div class="sw-table-wrap"><table class="sw-table">${head}${body}</table></div>
    <div class="small">칸에 마우스를 올리면 이전 값과 바뀐 값을 봐요. 화를 누르면 그 화 반영 기록으로 가요.</div></section>`;
}

function viewStatwin() {
  const p = P();
  const head = header('상태창', '상태창 수치', '레벨, 능력치, 스킬, 특성, 칭호, 돈, 인벤토리처럼 본문 상태창에 나오는 값을 인물마다 화별로 기록해요. 항목을 하나라도 정하면 AI가 본문을 쓸 때 이 값을 따르고, 바뀐 값만 상태 변경안에 적어요. 반영은 승인한 뒤에만 돼요.');
  if (!p.characters.length) return `${head}<div class="card empty"><p>아직 인물이 없어요.</p><a class="btn primary" href="${base()}/setup">설정 도우미에서 인물 만들기</a></div>`;
  const who = p.characters.map((c) => {
    const n = ((p.states.find((s) => s.character_id === c.id) || {}).stats || []).length;
    return `<a href="${base()}/statwin/${enc(c.id)}"${c.id === S.swCid ? ' aria-current="page"' : ''}><span>${esc(c.name)}</span><span class="small">${n ? `${n}항목` : ''}</span></a>`;
  }).join('');
  let main;
  if (!S.sw) main = '<div class="small">불러오는 중…</div>';
  else if (S.sw.error) main = `<div class="note err">${esc(S.sw.error)}</div>`;
  else main = swEditor() + swDex() + swDecor() + swPreview() + swTimeline();
  return `${head}<div class="sw"><nav class="card tight sw-who" aria-label="인물">${who}</nav><div style="display:flex;flex-direction:column;gap:16px;min-width:0">${main}</div></div>`;
}

document.addEventListener('input', (e) => {
  const d = e.target.dataset || {};
  if (d.swName !== undefined) { S.swRows[Number(d.swName)].name = e.target.value; swTouch(); }
  if (d.swValue !== undefined) { S.swRows[Number(d.swValue)].value = e.target.value; swTouch(); }
});

function swTouch() {
  if (S.swDirty) return;
  S.swDirty = true;
  const b = document.querySelector('[data-action="swSave"]');
  if (b) b.disabled = false;
}

Object.assign(actions, {
  swAdd() { S.swRows.push({ name: '', value: '' }); S.swDirty = true; render(); },
  swDel(i) { S.swRows.splice(Number(i), 1); S.swDirty = true; render(); },
  swPreset(k) {
    const have = new Set(S.swRows.map((r) => r.name));
    const names = k === '_work' ? (swWin().names || []) : (S.sw.presets[k] || []);
    S.swRows.push(...names.filter((x) => !have.has(x)).map((name) => ({ name, value: '' })));
    S.swDirty = true;
    render();
  },
  async swSave() {
    const before = Object.fromEntries((S.sw.current || []).map((s) => [s.name, s.value]));
    const stats = S.swRows.filter((r) => r.name.trim()).map((r) => ({ name: r.name.trim(), value: swResolve(before[r.name.trim()], r.value) }));
    await run('상태창 저장 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/statwin/${enc(S.swCid)}`, { stats });
      await swLoad();
      toast('상태창을 저장했어요');
    });
  },
  async swCopy() {
    const text = (S.sw && S.sw.text) || '';
    try {
      if (typeof copyPlain === 'function') await copyPlain(text);
      else await navigator.clipboard.writeText(text);
      toast('상태창을 복사했어요');
    } catch (e) {
      toast('복사하지 못했어요. 글을 직접 골라 복사하세요', true);
    }
  },
  swTplToggle() { S.swTpl = !S.swTpl; render(); },
  async swTplSave() {
    await swPut({ template: $('#sw-tpl').value, row: $('#sw-row').value || '{key}: {value}' }, '서식을 저장했어요');
  },
  async swTitleSave() { await swPut({ title: $('#sw-title').value }, '창 이름을 저장했어요'); },
  async swSkinPick(k) { if (k !== swSkin()) await swPut({ skin: k }, `${SW_SKINS[k]} 스킨으로 바꿨어요`); },
  async swSuggest() {
    const request = ($('#sw-req') || {}).value || '';
    await run('꾸미기 안 만드는 중', async () => {
      await saveIfDirty();  // AI는 저장된 설정을 읽는다
      S.swSug = await api('POST', `/projects/${enc(S.name)}/statwin-suggest`, { request: request.trim() });
      if (!S.swSug.options.length) toast('쓸 만한 안이 오지 않았어요. 다시 받아 보세요', true);
    });
  },
  async swUseOpt(i) {
    const o = ((S.swSug || {}).options || [])[Number(i)];
    if (!o) return;
    const w = swWin();
    const prev = { template: w.template, row: w.row, title: w.title, skin: w.skin, names: w.names || [] };
    if (await swPut({ template: o.template, row: o.row, title: o.title, skin: o.skin, names: o.names }, `'${o.label}' 안을 적용했어요`)) S.swPrev = prev;
    render();
  },
  async swUndoOpt() {
    if (!S.swPrev) return;
    if (await swPut(S.swPrev, '적용을 취소했어요')) S.swPrev = null;
    render();
  },
});

/** 서식 · 창 이름 · 스킨 · 작품 틀 저장. 빠진 칸은 지금 값. 고치던 인물 항목은 그대로 둔다. 저장하면 true */
async function swPut(patch, msg) {
  const w = swWin();
  const body = { template: w.template, row: w.row, ...patch };
  const rows = S.swRows;
  const dirty = S.swDirty;
  return run('저장 중', async () => {
    await saveIfDirty();
    S.project = await api('PUT', `/projects/${enc(S.name)}/statwin-template`, body);
    await swLoad();
    if (dirty) { S.swRows = rows; S.swDirty = true; }
    toast(msg);
  });
}

// ----- 스킬 · 특성 도감 -----

// 이름만 봐도 목록인 상태창 항목. abilities.LIST_NAMES 와 같다 (tests/test_statwin_js.py)
const AB_LIST_NAMES = ['스킬', '특성', '칭호', '능력', '특기', '기술', '무공', '절기', '마법', '축복', '권능', '재능'];
const abListName = (name) => AB_LIST_NAMES.some((w) => String(name).includes(w));
const abWho = (id) => (P().characters.find((c) => c.id === id) || {}).name || id;
const abWhen = (ep) => (ep === null || ep === undefined ? '' : ep === 0 ? '시작 때 얻음' : `${ep}화에 얻음`);

function swDex() {
  const d = S.ab;
  if (!d) return '';
  if (d.error) return `<section class="card"><h2>스킬 · 특성 도감</h2><div class="note err">${esc(d.error)}</div></section>`;
  if (!d.lists.length && !d.abilities.length && !S.abEdit) return '';
  const miss = d.unlinked.map((m) => `<button type="button" class="btn small" data-action="abNew" data-arg="${esc(`${m.stat}|${m.name}`)}" title="${esc(m.items.join(', '))} · ${esc(m.characters.map(abWho).join(', '))}">+ ${esc(m.name)} <span class="small">${esc(m.stat)}</span></button>`).join('');
  const rows = d.abilities.map(({ ability: a, owners }) => `<div class="ab-item">
      <div class="between"><strong>${esc(a.name)}${a.aliases.length ? ` <span class="small">(${esc(a.aliases.join(', '))})</span>` : ''}</strong>
        <span class="row" style="gap:6px">${a.stat ? `<span class="small">${esc(a.stat)}</span>` : ''}<button type="button" class="btn small" data-action="abEditOpen" data-arg="${esc(a.id)}">고치기</button></span></div>
      ${abFields(a)}
      ${owners.length ? `<div class="small">${owners.map((o) => `${esc(abWho(o.character_id))} ${esc(o.item)}${o.acquired !== null ? ` · ${abWhen(o.acquired)}` : ''}${o.grade_effect ? ` · ${esc(o.grade)}: ${esc(o.grade_effect)}` : ''}`).join(' / ')}</div>` : '<div class="small">지금 가진 인물이 없어요.</div>'}
    </div>`).join('');
  return `<section class="card" id="sw-dex"><div class="between"><h2>스킬 · 특성 도감</h2><button type="button" class="btn small" data-action="abNew" data-arg="">+ 항목</button></div>
    <div class="small">상태창 ${d.lists.length ? esc(d.lists.join(' · ')) : '목록'} 조각마다 설명 · 효과 · 대가를 적어요. 등급 꼬리(Lv3, B급, 3성)를 뗀 이름이 같으면 모든 인물에 같은 설명을 써요. 얻은 화는 상태창 기록에서 계산해요.</div>
    ${S.abEdit ? abForm() : ''}
    ${miss ? `<div class="field"><span class="label">도감에 없는 항목 ${d.unlinked.length}개 <span class="hint">누르면 그 이름으로 만들어요</span></span><div class="row" style="flex-wrap:wrap;gap:6px">${miss}</div></div>` : ''}
    ${rows ? `<div class="ab-list">${rows}</div>` : '<div class="small">아직 도감 항목이 없어요.</div>'}
  </section>`;
}

/** 설명 · 효과 · 대가 · 등급별 효과. 빈 칸은 뺀다. here 는 강조할 등급 */
function abFields(a, here = '') {
  const row = (k, v) => (v ? `<dt>${k}</dt><dd>${esc(v)}</dd>` : '');
  const gs = (a.grades || []).map((g) => `<dt>${esc(g.grade)}</dt><dd>${g.grade === here ? `<strong>${esc(g.effect)}</strong>` : esc(g.effect)}</dd>`).join('');
  const all = row('설명', a.description) + row('효과', a.effect) + row('대가', a.cost) + gs;
  return all ? `<dl>${all}</dl>` : '<div class="small">설명이 비어 있어요.</div>';
}

function abForm() {
  const a = S.abEdit;
  const lists = (S.ab && S.ab.lists) || [];
  const opts = ['', ...new Set([...lists, ...(a.stat ? [a.stat] : [])])].map((x) => `<option value="${esc(x)}"${x === a.stat ? ' selected' : ''}>${x ? esc(x) : '어느 목록이든'}</option>`).join('');
  const grades = a.grades.map((g, i) => `<div class="ab-grade"><input type="text" data-ab-grade="${i}" data-ab-gkey="grade" value="${esc(g.grade)}" placeholder="등급 (예: Lv3)" aria-label="등급 ${i + 1}">
      <input type="text" data-ab-grade="${i}" data-ab-gkey="effect" value="${esc(g.effect)}" placeholder="이 등급의 효과" aria-label="등급 ${i + 1} 효과">
      <button type="button" class="btn small ghost" data-action="abGradeDel" data-arg="${i}" aria-label="등급 ${i + 1} 지우기">지우기</button></div>`).join('');
  const f = (k, label, hint, rows) => `<div class="field"><label for="ab-${k}">${label}${hint ? ` <span class="hint">${hint}</span>` : ''}</label>${rows
    ? `<textarea id="ab-${k}" data-ab-field="${k}" rows="${rows}">${esc(a[k])}</textarea>` : `<input id="ab-${k}" type="text" data-ab-field="${k}" value="${esc(a[k])}">`}</div>`;
  return `<div class="ab-item" style="border-color:var(--accent)">
    <div class="grid-2">${f('name', '이름', '등급 꼬리 없이 (예: 화염구)')}<div class="field"><label for="ab-stat">상태창 항목</label><select id="ab-stat" data-ab-field="stat">${opts}</select></div></div>
    <div class="field"><label for="ab-aliases">다른 이름 <span class="hint">쉼표로. 상태창이나 본문에서 이 이름도 같은 것으로 봐요</span></label><input id="ab-aliases" type="text" data-ab-field="aliases" value="${esc(a.aliases.join(', '))}"></div>
    ${f('description', '설명', '', 2)}${f('effect', '효과', '', 2)}${f('cost', '대가 · 제약', '쿨타임, 마력 소모, 수명 같은 것', 2)}
    <div class="field"><span class="label">등급별 효과 <span class="hint">상태창 조각의 꼬리와 같게 적으면 그 등급 효과를 함께 보여요</span></span>${grades}<div><button type="button" class="btn small" data-action="abGradeAdd">+ 등급</button></div></div>
    <div class="between">${a.id ? '<button type="button" class="btn small danger" data-action="abDelete">삭제</button>' : '<span></span>'}
      <span class="row" style="gap:6px"><button type="button" class="btn small ghost" data-action="abCancel">취소</button><button type="button" class="btn small primary" data-action="abSave">저장</button></span></div>
  </div>`;
}

const abBlank = (name = '', stat = '') => ({ id: '', name, aliases: [], stat, description: '', effect: '', cost: '', grades: [], context: 'auto', source: 'author', created_ep: 0 });

/** 상태창 칩: 누르면 도감 카드. 목록 항목 조각에만 쓴다 */
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
  if (!S.abEdit) return;
  if (d.abField) S.abEdit[d.abField] = d.abField === 'aliases' ? e.target.value.split(/\s*,\s*/).filter(Boolean) : e.target.value;
  if (d.abGrade !== undefined) S.abEdit.grades[Number(d.abGrade)][d.abGkey] = e.target.value;
});
document.addEventListener('change', (e) => {
  if (S.abEdit && e.target.dataset && e.target.dataset.abField === 'stat') S.abEdit.stat = e.target.value;
});

Object.assign(actions, {
  abNew(arg) {
    const [stat, ...rest] = String(arg || '').split('|');
    S.abEdit = abBlank(rest.join('|'), arg ? stat : '');
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
      S.abEdit = null;
      S.ab = await api('GET', `/projects/${enc(S.name)}/abilities`);
      toast(`'${a.name.trim()}' 도감 항목을 저장했어요`);
    });
  },
  async abDelete() {
    const a = S.abEdit;
    if (!a || !a.id || !confirm(`'${a.name}' 도감 항목을 지울까요? 상태창 값은 그대로예요.`)) return;
    await run('도감 항목 지우는 중', async () => {
      S.project = await api('DELETE', `/projects/${enc(S.name)}/abilities/${enc(a.id)}`);
      S.abEdit = null;
      S.ab = await api('GET', `/projects/${enc(S.name)}/abilities`);
      toast('도감 항목을 지웠어요');
    });
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
        <div><button type="button" class="btn small primary" data-action="abFromPop" data-arg="${esc(`${encodeURIComponent(cid)}|${encodeURIComponent(stat)}|${encodeURIComponent(r.name)}`)}">도감에 만들기</button></div></div>`;
      return;
    }
    const hist = (r.history || []).map((h) => `<li>${h.episode ? `${h.episode}화` : '시작 때'} · ${h.kind === '얻음' ? `얻음 ${esc(h.item)}` : h.kind === '잃음' ? `잃음 ${esc(h.before)}` : `${esc(h.before)} → ${esc(h.item)}`}</li>`).join('');
    el.innerHTML = `<div class="ab-body">${head}
      ${r.grade_effect ? `<div class="note plain"><strong>${esc(r.grade)}</strong> ${esc(r.grade_effect)}</div>` : ''}
      ${abFields(r.ability, r.grade)}
      ${r.acquired !== null && r.acquired !== undefined ? `<div class="small">${abWhen(r.acquired)}</div>` : ''}
      ${hist ? `<details><summary class="small">바뀐 기록 ${r.history.length}</summary><ul class="small" style="padding-left:18px;margin:6px 0 0">${hist}</ul></details>` : ''}
      <div><button type="button" class="btn small" data-action="abGoEdit" data-arg="${esc(`${encodeURIComponent(cid)}|${r.ability.id}`)}">도감에서 고치기</button></div></div>`;
  },
  abGoEdit(arg) {
    const [cid, id] = String(arg).split('|').map(decodeURIComponent);
    actions.abClose();
    S.abOpenId = id;  // swLoad 가 도감을 받은 뒤 고치기 칸을 연다
    location.hash = `${base()}/statwin/${enc(cid)}`;
  },
  abClose() { const el = document.getElementById('ab-pop'); if (el && el.open) el.close(); },
  abFromPop(arg) {
    const [cid, stat, name] = String(arg).split('|').map(decodeURIComponent);
    actions.abClose();
    S.abEdit = abBlank(name, stat);
    location.hash = `${base()}/statwin/${enc(cid)}`;
  },
});

// ----- 설정 화면: 작품 틀과 처음 수치 -----

/** 1화를 반영했으면 처음 수치는 더 고치지 않는다 (그 뒤 고친 값은 상태창 수치 화면에서 작가 기록으로) */
const swLocked = () => P().episodes.some((e) => e.status === 'finalized');

/** 상태창을 자주 쓰는 작품인지: 현대 판타지 장르, 또는 설정 글에 상태창 · 레벨업 · 시스템 창 */
function swWanted(p) {
  const text = [p.meta.genre, p.meta.logline, p.meta.notes, p.world.setting, ...(p.world.rules || [])].join(' ');
  return (p.meta.genres || []).includes('modern_fantasy') || /상태창|상태 창|레벨\s?업|시스템 창/.test(text);
}

/** 고치는 중이 아니면 늘 작품에서 다시 읽는다 (상태창 수치 화면에서 고친 값도 따라오게) */
function swInitDraft() {
  if (!S.swInit || !S.swInitDirty) {
    S.swInit = Object.fromEntries(P().states.filter((s) => (s.stats || []).length)
      .map((s) => [s.character_id, Object.fromEntries(s.stats.map((x) => [x.name, x.value]))]));
    S.swInitDirty = false;
  }
  return S.swInit;
}

/** 표의 열: 작품 틀, 그다음 인물들이 가진 항목 */
function swInitCols() {
  const cols = [...(swWin().names || [])];
  for (const row of Object.values(swInitDraft())) for (const k of Object.keys(row)) if (!cols.includes(k)) cols.push(k);
  return cols;
}

function swInitRows() {
  const order = { main: 0, support: 1, minor: 2 };
  const d = swInitDraft();
  const filled = (c) => Object.values(d[c.id] || {}).some((v) => String(v).trim());
  return [...P().characters].sort((a, b) => (order[a.tier] ?? 1) - (order[b.tier] ?? 1))
    .filter((c) => S.swInitAll || c.tier !== 'minor' || filled(c));
}

function swSetupCard() {
  const p = P();
  const has = p.states.some((s) => (s.stats || []).length);
  const names = swWin().names || [];
  const open = has || names.length || swWanted(p) || S.swInitSug;
  const locked = swLocked();
  const cols = swInitCols();
  const d = swInitDraft();
  const chips = names.map((x, i) => `<span class="csh-know">${esc(x)} <button type="button" class="btn small ghost" data-action="swNameDel" data-arg="${i}" aria-label="${esc(x)} 빼기"${locked ? ' disabled' : ''}>×</button></span>`).join('');
  const presets = Object.entries(SW_PRESETS).map(([k, xs]) => `<button type="button" class="btn small" data-action="swNamePreset" data-arg="${k}" title="${esc(xs.join(', '))}"${locked ? ' disabled' : ''}>${SW_PRESET_LABELS[k]}</button>`).join('');
  const rows = swInitRows();
  const minor = p.characters.some((c) => c.tier === 'minor');
  const table = cols.length && rows.length ? `<div class="sw-table-wrap"><table class="sw-table"><thead><tr><th scope="col">인물</th>${cols.map((k) => `<th scope="col">${esc(k)}</th>`).join('')}</tr></thead><tbody>
      ${rows.map((c) => `<tr><th scope="row">${esc(c.name || c.id)}</th>${cols.map((k) => `<td><input type="text" data-swi-cid="${esc(c.id)}" data-swi-key="${esc(k)}" value="${esc((d[c.id] || {})[k] || '')}" aria-label="${esc(c.name || c.id)} ${esc(k)}" style="min-width:90px"${locked ? ' readonly' : ''}></td>`).join('')}</tr>`).join('')}
    </tbody></table></div>` : '';
  const body = locked
    ? `<div class="note plain">1화를 반영한 뒤라 처음 수치는 고치지 않아요. 지금 수치는 <a href="${base()}/statwin">상태창 수치</a>에서 고쳐요(그 화의 작가 기록으로 남아요).</div>${table}`
    : `<div class="field"><span class="label">작품 틀 <span class="hint">모든 인물 상태창에 쓰는 항목이에요. 표의 열이 돼요</span></span>
        <div class="row" style="flex-wrap:wrap;gap:6px">${chips || '<span class="small">아직 없어요.</span>'}</div>
        <div class="row"><input id="swi-name" type="text" placeholder="항목 이름 (예: 레벨, 내공)" aria-label="작품 틀에 더할 항목" style="max-width:220px"><button type="button" class="btn small" data-action="swNameAdd">더하기</button><span class="small">틀:</span>${presets}</div></div>
      ${table || (cols.length ? '' : '<div class="small">작품 틀을 정하거나 AI 제안을 받으면 인물마다 처음 수치를 적는 표가 생겨요.</div>')}
      ${minor ? `<button type="button" class="btn small ghost" data-action="swInitAllToggle">${S.swInitAll ? '단역 숨기기' : '단역도 보기'}</button>` : ''}
      <div class="field"><label for="swi-req">AI 처음 수치 제안 <span class="hint">로그라인 · 배경 · 인물 설정을 읽고 1화 시작 값을 인물마다 제안해요. 이미 적은 값은 그대로 둬요</span></label>
        <div class="row"><input id="swi-req" type="text" placeholder="요청 (비워도 돼요. 예: 주인공은 F급에서 시작)"><button type="button" class="btn small" data-action="swInitAI">AI 제안 받기</button></div></div>
      ${swInitSugBox()}
      <div class="between"><span class="small">저장하면 1화 시작 값(상태창 수치 화면의 '시작' 열)으로 남아요. 값을 모두 비운 인물은 상태창이 없어져요.</span>
        <button type="button" class="btn primary small" data-action="swInitSave"${S.swInitDirty ? '' : ' disabled'}>처음 수치 저장</button></div>`;
  return `<section class="card" id="setup-stats"><details${open ? ' open' : ''}><summary><h2 style="display:inline;margin-right:8px">상태창</h2><span class="small">레벨 · 스킬처럼 본문 상태창에 나오는 값${has ? ` · ${p.states.filter((s) => (s.stats || []).length).length}명` : ''}</span></summary>
    <div style="display:flex;flex-direction:column;gap:12px;padding-top:10px">
    ${!has && !names.length && swWanted(p) ? '<div class="note">이 작품은 상태창을 쓰는 장르예요. 1화 전에 처음 수치를 정해 두면 AI가 본문을 쓸 때 이 값을 따라요.</div>' : ''}
    ${body}</div></details></section>`;
}

function swInitSugBox() {
  const s = S.swInitSug;
  if (!s) return '';
  const who = (id) => (P().characters.find((c) => c.id === id) || {}).name || id;
  const d = swInitDraft();
  const rows = s.characters.map((c) => {
    const cur = d[c.character_id] || {};
    const empty = !Object.values(cur).some((v) => String(v).trim());
    const cells = c.stats.map((x) => {
      const now = String(cur[x.name] || '').trim();
      return `<span class="small">${esc(x.name)}</span> ${now && now !== x.value ? `<span class="before">${esc(now)}</span> → ` : ''}<strong>${esc(x.value)}</strong>`;
    }).join(' · ');
    return `<li><label class="row" style="align-items:flex-start;gap:8px"><input type="checkbox" data-swi-pick="${esc(c.character_id)}"${empty ? ' checked' : ''}>
      <span><strong>${esc(who(c.character_id))}</strong>${empty ? '' : ' <span class="small">(이미 값이 있어 기본으로 고르지 않았어요)</span>'}<br>${cells}${c.note ? `<br><span class="small">${esc(c.note)}</span>` : ''}</span></label></li>`;
  }).join('');
  return `<div class="note plain"><strong>AI 처음 수치 제안</strong>${rows ? `<ul style="list-style:none;padding:0;margin:8px 0;display:flex;flex-direction:column;gap:8px">${rows}</ul>
      <div class="row"><button type="button" class="btn small primary" data-action="swInitUse">고른 인물에 적용</button><button type="button" class="btn small ghost" data-action="swInitDrop">닫기</button><span class="small">표에 넣기만 해요. 저장해야 남아요.</span></div>`
    : '<div class="small">상태창이 있는 인물을 찾지 못했어요. 요청에 누가 상태창을 보는지 적어 다시 받아 보세요.</div>'}</div>`;
}

/** 작품 틀만 저장 (서식 · 창 이름 · 스킨은 그대로) */
async function swNamesPut(names, msg) {
  const w = swWin();
  return run('저장 중', async () => {
    await saveIfDirty();
    S.project = await api('PUT', `/projects/${enc(S.name)}/statwin-template`, { template: w.template, row: w.row, names });
    toast(msg);
  });
}

document.addEventListener('input', (e) => {
  const d = e.target.dataset || {};
  if (d.swiCid === undefined) return;
  const draft = swInitDraft();
  (draft[d.swiCid] = draft[d.swiCid] || {})[d.swiKey] = e.target.value;
  if (!S.swInitDirty) {
    S.swInitDirty = true;  // 이제부터 swInitDraft 가 작품에서 다시 읽지 않는다
    const b = document.querySelector('[data-action="swInitSave"]');
    if (b) b.disabled = false;
  }
});

Object.assign(actions, {
  async swNameAdd() {
    const x = ($('#swi-name') || {}).value || '';
    const names = swWin().names || [];
    if (!x.trim() || names.includes(x.trim())) return;
    await swNamesPut([...names, x.trim()], `'${x.trim()}' 항목을 더했어요`);
  },
  async swNameDel(i) {
    const names = [...(swWin().names || [])];
    const [x] = names.splice(Number(i), 1);
    await swNamesPut(names, `'${x}' 항목을 틀에서 뺐어요. 인물에게 적은 값은 남아 있어요`);
  },
  async swNamePreset(k) {
    const names = swWin().names || [];
    await swNamesPut([...names, ...SW_PRESETS[k].filter((x) => !names.includes(x))], `${SW_PRESET_LABELS[k]} 틀을 더했어요`);
  },
  swInitAllToggle() { S.swInitAll = !S.swInitAll; render(); },
  async swInitAI() {
    const request = (($('#swi-req') || {}).value || '').trim();
    await run('처음 수치 제안 만드는 중', async () => {
      await saveIfDirty();  // AI는 저장된 인물 설정을 읽는다
      S.swInitSug = await api('POST', `/projects/${enc(S.name)}/statwin-init`, { request });
    });
  },
  swInitUse() {
    const s = S.swInitSug;
    if (!s) return;
    const picked = new Set([...document.querySelectorAll('[data-swi-pick]:checked')].map((x) => x.dataset.swiPick));
    if (!picked.size) { toast('적용할 인물을 고르세요', true); return; }
    const d = swInitDraft();
    for (const c of s.characters.filter((x) => picked.has(x.character_id))) {
      d[c.character_id] = { ...(d[c.character_id] || {}), ...Object.fromEntries(c.stats.map((x) => [x.name, x.value])) };
    }
    S.swInitSug = null;
    S.swInitDirty = true;
    render();
    toast('표에 넣었어요. 처음 수치 저장을 눌러야 남아요');
  },
  swInitDrop() { S.swInitSug = null; render(); },
  async swInitSave() {
    const d = swInitDraft();
    const cols = swInitCols();
    const now = Object.fromEntries(P().states.map((s) => [s.character_id, Object.fromEntries((s.stats || []).map((x) => [x.name, x.value]))]));
    const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
    const jobs = Object.entries(d).map(([cid, row]) => {
      const stats = cols.filter((k) => String(row[k] || '').trim()).map((k) => ({ name: k, value: String(row[k]).trim() }));
      return [cid, stats];
    }).filter(([cid, stats]) => P().characters.some((c) => c.id === cid) && !same(Object.fromEntries(stats.map((x) => [x.name, x.value])), Object.fromEntries(Object.entries(now[cid] || {}).filter(([, v]) => String(v).trim()))));
    const names = swWin().names || [];
    const extra = cols.filter((k) => !names.includes(k));
    await run('처음 수치 저장 중', async () => {
      await saveIfDirty();
      if (!names.length && extra.length) {  // AI 제안으로 생긴 항목을 작품 틀로
        const w = swWin();
        S.project = await api('PUT', `/projects/${enc(S.name)}/statwin-template`, { template: w.template, row: w.row, names: extra });
      }
      for (const [cid, stats] of jobs) S.project = await api('PUT', `/projects/${enc(S.name)}/statwin/${enc(cid)}`, { stats });
      S.swInit = null;
      toast(jobs.length ? `${jobs.length}명의 처음 수치를 저장했어요` : '바뀐 값이 없어요');
    });
  },
});

// ----- 상태 승인 화면 -----

/** 인물 상태 변경안의 상태창 줄. 이전 값 → 반영하면 될 값 (+3 은 계산해서 보여 준다). */
function swDeltaRows(u, cur) {
  const stats = (u.stats || []).filter((s) => s.name && s.name.trim());
  if (!stats.length) return '';
  const now = Object.fromEntries((cur.stats || []).map((s) => [s.name, s.value]));
  const cells = stats.map((s) => {
    const b = now[s.name.trim()] || '';
    const a = s.value.trim() ? swResolve(b, s.value) : '';
    const rel = s.value.trim() !== a && s.value.trim() ? ` <span class="small">(${esc(s.value.trim())})</span>` : '';
    return `<div class="row" style="gap:6px"><span class="small" style="min-width:60px">${esc(s.name)}</span>${b ? `<span class="before">${esc(b)}</span><span class="small">→</span>` : ''}${a ? `<span class="after">${esc(a)}</span>${rel}` : '<span class="small">지움</span>'}</div>`;
  }).join('');
  return `<div class="small">상태창</div>${cells}`;
}

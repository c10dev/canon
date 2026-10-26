/* 상태창 수치. app.js 의 S, actions, api, run, render, header, esc, P 를 쓴다.
   게임 판타지 · 헌터물처럼 레벨, 능력치, 스킬 · 특성 · 칭호 목록, 돈, 인벤토리가 나오는 작품에서 인물별 상태창(CharacterState.stats)을 정하고,
   화마다 바뀐 기록(Project.stat_log)으로 비교표를 그린다. 본문에 넣을 상태창 글을 복사한다.
   서버는 canon/statwin.py (/statwin/<인물 id>). AI 가 적은 바뀐 값은 상태 승인 화면에서 고른 뒤에만 반영된다(swDeltaRows). */
'use strict';

Object.assign(S, {
  sw: null,          // 서버 값 { names, columns, current, text, presets }
  swCid: '',         // 보고 있는 인물
  swRows: [],        // 고치는 중인 항목 [{name, value}]
  swDirty: false,
  swTpl: false,      // 서식 고치기 칸 열림
});

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
.sw-diff { font-size: 12px; font-weight: 400; }`;
  const el = document.createElement('style');
  el.textContent = css;
  document.head.appendChild(el);
}());

async function swLoad(cid) {
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

function swEditor() {
  const rows = S.swRows.map((r, i) => `<div class="sw-row">
      <input type="text" data-sw-name="${i}" value="${esc(r.name)}" aria-label="항목 이름" placeholder="항목 (예: 레벨)">
      <input type="text" data-sw-value="${i}" value="${esc(r.value)}" aria-label="${esc(r.name || '항목')} 값" placeholder="값 (+3 은 더하기, 목록은 +독 내성 · -은신)">
      <button type="button" class="btn small ghost" data-action="swDel" data-arg="${i}" aria-label="${esc(r.name || '항목')} 지우기">지우기</button></div>`).join('');
  const presets = Object.entries((S.sw && S.sw.presets) || {}).map(([k, names]) => `<button type="button" class="btn small" data-action="swPreset" data-arg="${k}" title="${esc(names.join(', '))}">${{ game: '게임 판타지', hunter: '헌터물', simple: '레벨 · 스킬', growth: '스킬 · 특성 · 돈' }[k] || k}</button>`).join('');
  return `<section class="card"><div class="between"><h2>지금 상태창</h2><span class="small">${S.sw.columns.length ? `${S.sw.columns[S.sw.columns.length - 1].episode}화까지 기록` : '기록 없음'}</span></div>
    <div class="sw-rows">${rows || '<div class="small">항목이 없어요. 아래에서 항목을 더하거나 틀을 고르세요.</div>'}</div>
    <div class="row"><button type="button" class="btn small" data-action="swAdd">+ 항목</button>${S.swRows.length ? '' : `<span class="small">틀:</span>${presets}`}</div>
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
      <div class="row"><button type="button" class="btn small primary" data-action="swTplSave">서식 저장</button><span class="small">AI 가 본문에 상태창을 쓸 때도 이 서식을 따릅니다.</span></div>` : ''}
  </section>`;
}

function swTimeline() {
  const t = S.sw;
  if (!t.columns.length) return '<section class="card"><h2>화별 변화</h2><div class="small">아직 기록이 없어요. 상태 승인 화면에서 AI 가 적은 수치를 반영하거나, 위에서 값을 저장하면 쌓여요.</div></section>';
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
  const head = header('상태창', '상태창 수치', '레벨, 능력치, 스킬, 특성, 칭호, 돈, 인벤토리처럼 본문 상태창에 나오는 값을 인물마다 화별로 기록해요. 항목을 하나라도 정하면 AI 가 본문을 쓸 때 이 값을 따르고, 바뀐 값만 상태 변경안에 적어요. 반영은 승인한 뒤에만 돼요.');
  if (!p.characters.length) return `${head}<div class="card empty"><p>아직 인물이 없어요.</p><a class="btn primary" href="${base()}/setup">설정 도우미에서 인물 만들기</a></div>`;
  const who = p.characters.map((c) => {
    const n = ((p.states.find((s) => s.character_id === c.id) || {}).stats || []).length;
    return `<a href="${base()}/statwin/${enc(c.id)}"${c.id === S.swCid ? ' aria-current="page"' : ''}><span>${esc(c.name)}</span><span class="small">${n ? `${n}항목` : ''}</span></a>`;
  }).join('');
  let main;
  if (!S.sw) main = '<div class="small">불러오는 중…</div>';
  else if (S.sw.error) main = `<div class="note err">${esc(S.sw.error)}</div>`;
  else main = swEditor() + swPreview() + swTimeline();
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
    S.swRows.push(...(S.sw.presets[k] || []).filter((x) => !have.has(x)).map((name) => ({ name, value: '' })));
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
    const body = { template: $('#sw-tpl').value, row: $('#sw-row').value || '{key}: {value}' };
    await run('서식 저장 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/statwin-template`, body);
      await swLoad();
      toast('서식을 저장했어요');
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

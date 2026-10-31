/* 상태창 수치. app.js 의 S, actions, api, run, render, header, esc, P 와 outline.js 의 공용 목차 틀을 쓴다.
   게임 판타지 · 헌터물처럼 레벨, 능력치, 스킬 · 특성 · 칭호 목록, 돈, 인벤토리가 나오는 작품에서 인물별 상태창(CharacterState.stats)을 정하고,
   화마다 바뀐 기록(Project.stat_log)으로 변화를 보인다. 본문에 넣을 상태창 글을 복사한다.
   화면은 공용 목차 + 카드 한 열이다. 목차: 작품 틀 · 처음 수치 / 꾸미기 / 비중별 인물 / 스킬 도감. 주소는 statwin/<인물 id> · statwin/_frame · statwin/_decor.
   인물 쪽(swPersonPage): 머리 → 지금 상태창(읽기 카드, '고치기'로 이 카드만) → 본문에 넣을 상태창 → 화별 변화(바뀐 화 | 표).
   작품 틀 · 처음 수치 쪽(swFramePage): 1화 전에 작품 틀과 인물별 처음 수치를 표로 정하고, AI 처음 수치 제안을 인물마다 골라 넣는다.
   꾸미기 쪽(swDecorPage): 창 이름 · 본문 서식(읽기 카드), 화면 스킨, AI 꾸미기 안 고르기와 적용 취소.
   스킬 · 특성 도감은 도구 화면 static/abilities.js 에 있고, 상태창 칩(abChip)을 누르면 도감 카드가 뜬다.
   서버는 canon/statwin.py (/statwin/<인물 id>, /statwin-suggest). AI 가 적은 바뀐 값은 상태 승인 화면에서 고른 뒤에만 반영된다(swDeltaRows). */
'use strict';

Object.assign(S, {
  sw: null,          // 서버 값 { names, columns, current, text, presets }
  swCid: '',         // 보고 있는 인물
  swPage: '',        // '' 인물 쪽 | '_frame' 작품 틀 · 처음 수치 | '_decor' 꾸미기
  swOwner: '',       // 화면 상태를 가진 작품. 다른 작품으로 가면 고치던 칸을 닫는다
  swRows: [],        // 고치는 중인 항목 [{name, value}]
  swDirty: false,
  swEdit: false,     // 지금 상태창 카드를 고치는 중
  swTpl: false,      // 창 이름 · 본문 서식 카드를 고치는 중
  swLog: 'list',     // 화별 변화 보기: list 바뀐 화 | table 표
  swLogAll: false,   // 바뀐 화를 모두 보기
  swNoneOpen: false, // 목차의 '상태창 없는 인물'을 펼침
  swSug: null,       // AI 꾸미기 안 { options } (저장하지 않음)
  swPrev: null,      // 마지막으로 적용한 꾸미기 안 앞의 서식 (적용 취소용)
  swInit: null,      // 처음 수치 표의 고치는 중인 값 { 인물 id: { 항목: 값 } }. null 이면 작품에서 다시 읽는다
  swInitDirty: false,
  swInitSug: null,   // AI 처음 수치 제안 { names, characters } (저장하지 않음)
  swInitAll: false,  // 단역도 표에 보이기
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
const SW_PAGES = { _frame: '작품 틀 · 처음 수치', _decor: '꾸미기' };
const SW_SOURCE = { ai: 'AI 변경안', author: '작가가 고침', both: '승인 뒤 작가가 고침' };
const SW_LOG_FIRST = 5;  // 화별 변화 목록이 처음에 보이는 화 수

async function swLoad(arg) {
  const p = P();
  if (S.swOwner !== S.name) {
    Object.assign(S, { swOwner: S.name, swCid: '', swPage: '', swEdit: false, swTpl: false, swSug: null, swPrev: null, swInit: null, swInitDirty: false, swInitSug: null, swLogAll: false, swNoneOpen: false });
    try { S.castTheme = localStorage.getItem('canon-cast-theme:' + S.name) || ''; } catch (e) { S.castTheme = ''; }  // 인물 화면과 같은 '카드 | 스킨' 고르기
  }
  const prevKey = swKey2();
  const chars = p.characters;
  const has = (id) => swStatsOf(id).length;
  if (arg && SW_PAGES[arg]) S.swPage = arg;
  else if (arg) { S.swPage = ''; S.swCid = arg; } else if (!S.swCid) S.swPage = chars.some((c) => has(c.id)) ? '' : '_frame';  // 상태창이 아무에게도 없으면 작품 틀부터
  if (!chars.some((c) => c.id === S.swCid)) S.swCid = (chars.find((c) => has(c.id)) || chars.find((c) => c.tier === 'main') || chars[0] || {}).id || '';
  if (swKey2() !== prevKey) {
    S.swEdit = false;
    S.swLogAll = false;
    if (prevKey && !S.focusTarget) S.focusTarget = '#app main h1';  // 쪽을 옮기면 제목으로 (foreshadow.js 와 같다)
  }
  if (!S.swCid) { S.sw = null; return; }
  S.sw = await api('GET', `/projects/${enc(S.name)}/statwin/${enc(S.swCid)}`).catch((e) => ({ error: e.message }));
  if (!S.swEdit) {
    S.swRows = (S.sw.current || []).map((s) => ({ ...s }));
    S.swDirty = false;
  }
}

/** 지금 쪽의 열쇠: 인물 id 또는 '_frame' · '_decor'. 목차의 지금 줄과 주소가 같은 값을 쓴다 */
function swKey2() { return S.swPage || S.swCid; }
function swHref(k) { return `${base()}/statwin/${enc(k)}`; }
function swStatsOf(cid) { return ((P().states.find((s) => s.character_id === cid) || {}).stats || []).filter((s) => s.name); }

/** 인물의 마지막 기록 화. 기록이 처음 값(0화)뿐이면 0, 없으면 null */
function swLastEp(cid) {
  const eps = (P().stat_log || []).filter((r) => r.character_id === cid).map((r) => r.episode);
  return eps.length ? Math.max(...eps) : null;
}

// statwin.py 의 _AMOUNT · _DELTA · _SPLIT · _GRADE 와 같다
const SW_AMOUNT = /^([^\d\s,+-]{0,4})(\s?)(-?\d[\d,]*(?:\.\d+)?)(\s?)([^\d\s,]{0,6})$/;
const SW_DELTA = /^([+-])\s?([^\d\s,+-]{0,4})\s?(\d[\d,]*(?:\.\d+)?)\s?([^\d\s,]{0,6})$/;
/** 지금 값 / 한도 ('80/100', '4.3/60L'). 바뀐 양은 앞 수에만 더하고 한도 뒤 단위는 그대로 둔다 (statwin._FRACTION) */
const SW_OF_MAX = /^(-?\d[\d,]*(?:\.\d+)?)(\s*\/\s*(\d[\d,]*(?:\.\d+)?))(\s?)([^\d\s,/]{0,6})$/;
const SW_SPLIT = /\s*(?:,|、| · )\s*/;
const SW_GRADE = /\s*(?:\([^()]*\)|\[[^[\]]*\]|lv\.?\s*\d+|\+\d+|\d+\s*(?:레벨|단계|성|강|개))$/i;

/** statwin._fmt 와 같다: places 를 주면 소수 자리를 그만큼 지킨다 */
function swFmt(x, commas, places) {
  if (places != null) {
    let s = x.toFixed(places);
    if (commas) {
      const [i, f] = s.split('.');
      s = i.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (f ? `.${f}` : '');
    }
    return Number(s.replace(/,/g, '')) === 0 ? s.replace(/^-/, '') : s;
  }
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
  const f = b.match(SW_OF_MAX);
  if (d && f && !d[2] && (!d[4] || d[4] === f[5])) {
    const x = Number(f[1].replace(/,/g, '')) + (d[1] === '+' ? 1 : -1) * Number(d[3].replace(/,/g, ''));
    const places = Math.max((f[1].split('.')[1] || '').length, (d[3].split('.')[1] || '').length);
    return `${swFmt(x, f[1].includes(','), places)}${f[2]}${f[4]}${f[5]}`;
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

/** 화별 변화 한 칸을 글 조각으로: 목록은 같은 이름(등급 꼬리를 뗀 이름)끼리 짝지어 '감정 Lv2 → 감정 Lv3', 남은 것은 더함 · 뺌.
    목록이 아니면 이전 값 → 새 값(처음 정함 · 지움 포함). [{ kind: set | add | del | grade, before, after }] */
function swChangeParts(ch, after) {
  const added = [...(ch.added || [])];
  const removed = [...(ch.removed || [])];
  if (!added.length && !removed.length) return [{ kind: 'set', before: ch.before || '', after: after || '' }];
  const out = [];
  for (const x of added) {
    const i = removed.findIndex((y) => swKey(y) === swKey(x));
    if (i >= 0) out.push({ kind: 'grade', before: removed.splice(i, 1)[0], after: x });
    else out.push({ kind: 'add', before: '', after: x });
  }
  return out.concat(removed.map((y) => ({ kind: 'del', before: y, after: '' })));
}

function swChangeHtml(name, ch, after) {
  const parts = swChangeParts(ch, after).map((x) => {
    if (x.kind === 'add') return `<span class="after">+ ${esc(x.after)}</span>`;
    if (x.kind === 'del') return `<span class="before">${esc(x.before)}</span> 뺌`;
    if (!x.before) return `<span class="after">${esc(x.after)}</span> <span class="small">처음 정함</span>`;
    if (!x.after) return `<span class="before">${esc(x.before)}</span> 지움`;
    return `<span class="before">${esc(x.before)}</span> → <span class="after">${esc(x.after)}</span>`;
  });
  return `<span class="sw-ch"><span class="k">${esc(name)}</span> ${parts.join(', ')}</span>`;
}

/** 화면 스킨으로 그린 상태창 견본(꾸미기 쪽 · AI 안). 칩은 누를 수 없는 글이다 */
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

/** 상태창 칸 모양. 인물 화면(cast.js castSheetStats)과 상태창 수치 인물 쪽이 함께 쓴다.
    stats: [{name, value}], before: 앞 시점 값 { 이름: 값 } (없으면 바뀐 표시 없음), when: 바뀐 표시 글('12화'), src: 이름 → 바뀐 출처 글.
    system 이면 작품 스킨 창, 아니면 카드 칸. 목록 조각은 abChip(누르면 도감 카드) */
function swStatsBody(cid, name, stats, { before = null, when = '', src = () => '', system = false, foot = '' } = {}) {
  const items = stats.map((s) => {
    const delta = before ? castStatDelta(before[s.name], s.value) : '';
    const frac = s.value.match(SW_FRACTION);
    const list = s.value.match(SW_AMOUNT) ? [] : swItems(s.value);  // 3,000원 같은 금액은 쉼표가 있어도 목록이 아니다
    const num = (x) => Number(x.replace(/,/g, ''));
    const pct = frac && num(frac[2]) > 0 ? Math.max(0, Math.min(100, Math.round((num(frac[1]) / num(frac[2])) * 100))) : null;
    return { name: s.name, value: s.value, delta, from: delta ? src(s.name) : '', pct, list: list.length > 1 || (list.length && abListName(s.name)) ? list : null };
  }).sort((x, y) => !!x.list - !!y.list);  // 한 줄을 다 쓰는 목록 항목은 뒤로 모은다
  // 다 지운 항목은 이 시점 값에 없으니 앞 시점에서 찾아 '지움'으로 보인다
  const gone = before ? Object.keys(before).filter((k) => before[k] && !stats.some((s) => s.name === k)) : [];
  const fresh = (x, v) => (x.delta && before && !swItems(before[x.name]).includes(v) ? ' new' : '');  // 이번에 생기거나 등급이 바뀐 조각
  const tag = (x) => (x.delta ? `<span class="csh-delta" title="${esc(`${when}에 바뀜${x.from ? ' · ' + x.from : ''}`)}">${esc(x.delta)}</span>` : '');
  if (system) {
    return `<div class="sw-sys sw-skin-${swSkin()}" role="group" aria-label="${esc(name)} ${esc(swTitle())}"><div class="sw-sys-title">【 ${esc(swTitle())} 】</div>
      <dl><dt>이름</dt><dd>${esc(name)}</dd>${items.map((x) => `<dt>${esc(x.name)}</dt><dd>${x.pct !== null ? `<span class="sw-sys-bar" aria-hidden="true"><i style="width:${x.pct}%"></i></span>` : ''}${x.list ? x.list.map((v) => abChip(cid, x.name, v, `sw-sys-tag${fresh(x, v)}`)).join('') : `<span>${esc(x.value || '—')}</span>`}${tag(x)}</dd>`).join('')}
      ${gone.map((k) => `<dt>${esc(k)}</dt><dd><s>${esc(before[k])}</s><span class="csh-delta">지움</span></dd>`).join('')}</dl>
      ${foot ? `<div class="sw-sys-foot">${foot}</div>` : ''}</div>`;
  }
  return `<div class="csh-stats">${items.map((x) => `<div class="csh-stat${x.list ? ' wide' : ''}${x.delta ? ' moved' : ''}"><div class="between"><span class="small">${esc(x.name)}</span>${tag(x)}</div>
      ${x.list ? `<div class="csh-chips">${x.list.map((v) => abChip(cid, x.name, v, `csh-know${fresh(x, v)}`)).join('')}</div>` : `<strong>${esc(x.value || '—')}</strong>`}
      ${x.pct !== null ? `<div class="csh-bar" aria-hidden="true"><i style="width:${x.pct}%"></i></div>` : ''}</div>`).join('')}
      ${gone.map((k) => `<div class="csh-stat moved"><div class="between"><span class="small">${esc(k)}</span><span class="csh-delta">지움</span></div><s class="small">${esc(before[k])}</s></div>`).join('')}</div>`;
}

/** 카드 | 작품 스킨 고르기 (인물 화면과 같은 값, cast.js castTheme) */
function swViewSeg() {
  const system = S.castTheme === 'system';
  return `<div class="seg" role="group" aria-label="상태창 보기"><button type="button" data-action="castTheme" data-arg="" aria-pressed="${!system}">카드</button><button type="button" data-action="castTheme" data-arg="system" aria-pressed="${system}">${esc(SW_SKINS[swSkin()])}</button></div>`;
}

// ----- 목차 -----

function swToc() {
  const p = P();
  const key = swKey2();
  const names = swWin().names || [];
  const item = (k, inner, cls = '') => `<a class="outline-item${cls}" href="${swHref(k)}"${key === k ? ' aria-current="page"' : ''}>${inner}</a>`;
  const person = (c) => {
    const n = swLastEp(c.id);
    const st = !swStatsOf(c.id).length ? '없음' : n ? `${n}화 바뀜` : '시작 값';
    return item(c.id, `${castAva(c, 's')}<span class="tl">${esc(c.name || c.id)}</span><span class="st">${st}</span>`);
  };
  const want = !names.length && !p.states.some((s) => (s.stats || []).length) && swWanted(p);
  const out = [
    item('_frame', `<span class="tl">작품 틀 · 처음 수치</span><span class="st">${names.length ? `${names.length}항목` : '없음'}</span>`, want ? ' warn' : ''),
    item('_decor', `<span class="tl">꾸미기</span><span class="st">${esc(swTitle())}</span>`),
  ];
  const withStats = p.characters.filter((c) => swStatsOf(c.id).length);
  const none = p.characters.filter((c) => !swStatsOf(c.id).length);
  ['main', 'support', 'minor'].forEach((tier) => {
    const list = withStats.filter((c) => (c.tier || 'main') === tier);
    if (list.length) out.push(`<div class="outline-h">${TIER_NAME[tier]} ${list.length}</div>`, ...list.map(person));
  });
  if (none.length) {
    const open = S.swNoneOpen || none.some((c) => key === c.id);
    out.push('<div class="outline-sep"></div>', `<button type="button" class="outline-item" data-action="swNoneToggle" data-outline-keep aria-expanded="${open}"><span class="tl">상태창 없는 인물</span><span class="st">${none.length} ${open ? '▾' : '▸'}</span></button>`);
    if (open) out.push(...none.map(person));
  }
  const empty = (p.abilities || []).filter((a) => !(a.description || a.effect || a.cost)).length;
  if ((p.abilities || []).length || withStats.some((c) => swStatsOf(c.id).some((s) => abListName(s.name)))) {
    out.push('<div class="outline-sep"></div>', `<a class="outline-item${empty ? ' warn' : ''}" href="${base()}/abilities" data-outline-close><span class="tl">스킬 도감</span><span class="st">${empty ? `설명 없음 ${empty}` : `${(p.abilities || []).length}항목`}</span></a>`);
  }
  const c = p.characters.find((x) => x.id === S.swCid);
  const now = S.swPage ? SW_PAGES[S.swPage] : c ? `${castAva(c, 's')} ${esc(c.name || c.id)} · ${TIER_NAME[c.tier || 'main']}` : '';
  return outlineNav({ id: 'sw-toc', label: '상태창 목차', now, body: out.join('') });
}

// ----- 인물 쪽 -----

function swHead(c) {
  const t = S.sw;
  const stats = swStatsOf(c.id);
  const cols = t.columns || [];
  const changes = cols.filter((x) => x.episode > 0).length;
  const last = cols[cols.length - 1];
  const lastN = last ? Object.keys(last.changed).length : 0;
  const srcs = last ? [...new Set(Object.values(last.changed).map((x) => x.source))] : [];
  const facts = !stats.length ? '상태창이 없어요'
    : [cols.some((x) => x.episode === 0) ? '시작 값' : '', changes ? `${changes}번 바뀜` : '바뀐 기록 없음',
      last && last.episode ? `마지막으로 ${last.episode}화에 ${lastN}항목 바뀜(${srcs.map((s) => SW_SOURCE[s]).join(' · ')})` : ''].filter(Boolean).join(' · ');
  const brief = stats.filter((s) => !swItems(s.value).slice(1).length && s.value).slice(0, 2).map((s) => `${s.name} ${s.value}`).join(' · ');
  return `<section class="card cast-head">${castAva(c, 'l')}
    <div class="cast-head-id">
      <div class="between"><h2>${esc(c.name || c.id)}</h2><a class="btn small ghost" href="${base()}/cast/c:${enc(c.id)}">인물 쪽에서 보기</a></div>
      <div class="row" style="gap:6px"><span class="chip">${TIER_NAME[c.tier || 'main']}</span>${brief ? `<span class="chip confirmed">${esc(brief)}</span>` : ''}</div>
      <div class="small">${esc(facts)}</div></div></section>`;
}

/** 지금 상태창: 읽는 모양이 기본, '고치기'로 이 카드만 편다(Card '읽기 카드와 고치기 카드') */
function swNowCard(c) {
  if (S.swEdit) return swEditor(c);
  const t = S.sw;
  const stats = (t.current || []).filter((s) => s.name);
  const done = (P().episodes.filter((e) => e.status === 'finalized').pop() || { plot: {} }).plot.number;
  const when = done ? `${done}화 반영 뒤` : '1화 전';
  if (!stats.length) {
    return `<section class="card csh-empty" id="sw-now" tabindex="-1"><div class="empty">
      <p>${esc(c.name || c.id)}에게는 아직 상태창이 없어요. 레벨 · 스킬처럼 본문 상태창에 나오는 값이 있으면 만들어요.</p>
      <button type="button" class="btn primary" data-action="swEditGo">상태창 만들기</button></div></section>`;
  }
  const cols = t.columns || [];
  const last = cols[cols.length - 1];
  const prev = cols[cols.length - 2];
  const before = last && last.episode && prev ? prev.values : null;  // 마지막으로 바뀐 화의 바뀐 칸을 표시한다
  const src = (name) => (last && last.changed[name] ? SW_SOURCE[last.changed[name].source] : '');
  const lastN = last ? Object.keys(last.changed).length : 0;
  const foot = `<span>${esc(when)}</span><span>${before ? `${last.episode}화에 ${lastN}항목 바뀜` : ''}</span>`;
  const body = swStatsBody(c.id, c.name || c.id, stats, { before, when: before ? `${last.episode}화` : '', src, system: S.castTheme === 'system', foot });
  const nodoc = stats.some((s) => abListName(s.name) && swItems(s.value).some((x) => abNoDoc(x, s.name)));
  return `<section class="card" id="sw-now" tabindex="-1">
    <div class="between"><div class="row"><h2>지금 상태창</h2><span class="small">${esc(when)}${before ? ` · ${last.episode}화에 바뀐 칸 표시` : ''}</span></div>
      <div class="row">${swViewSeg()}<button type="button" class="btn small" data-action="swEditGo" aria-expanded="false">고치기</button></div></div>
    ${body}
    <span class="small">스킬 · 특성 · 칭호 조각을 누르면 도감 카드가 떠요.${nodoc ? ' 주황 점은 도감에 설명이 아직 없는 조각이에요.' : ''}</span></section>`;
}

/** 지금 상태창 고치는 칸. 값에 +3 · -500 · +독 내성 을 적으면 옆에 계산한 값을 보인다(swResolve) */
function swEditor(c) {
  const now = Object.fromEntries((S.sw.current || []).map((s) => [s.name, s.value]));
  const tool = (i, d, label, text, off) => `<button type="button" class="btn icon-btn ghost" data-action="swMove" data-arg="${i}:${d}" aria-label="${esc(S.swRows[i].name || '항목')} ${label}"${off ? ' disabled' : ''}>${text}</button>`;
  const rows = S.swRows.map((r, i) => `<div class="sw-row">
      <input type="text" data-sw-name="${i}" value="${esc(r.name)}" aria-label="항목 이름" placeholder="항목 (예: 레벨)">
      <span class="sw-val"><input type="text" data-sw-value="${i}" value="${esc(r.value)}" aria-label="${esc(r.name || '항목')} 값" placeholder="값" aria-describedby="sw-calc-${i}"><span class="sw-calc" id="sw-calc-${i}" aria-live="polite">${esc(swCalc(now[r.name.trim()], r.value))}</span></span>
      <span class="sw-tools">${tool(i, -1, '위로', '↑', i === 0)}${tool(i, 1, '아래로', '↓', i === S.swRows.length - 1)}<button type="button" class="btn icon-btn ghost" data-action="swDel" data-arg="${i}" aria-label="${esc(r.name || '항목')} 지우기">✕</button></span></div>`).join('');
  const work = (swWin().names || []).filter((x) => !S.swRows.some((r) => r.name === x));
  const workBtn = work.length ? `<button type="button" class="btn small" data-action="swPreset" data-arg="_work" title="${esc(work.join(', '))}">작품 틀 넣기</button>` : '';
  const presets = !S.swRows.length && !work.length ? menuBtn('sw-preset', `틀 고르기 ${CHEVRON}`, () => Object.entries((S.sw && S.sw.presets) || {}).map(([k, names]) => `<button type="button" class="pop-item" data-action="swPreset" data-arg="${k}">${SW_PRESET_LABELS[k] || k}<span class="small">${esc(names.join(', '))}</span></button>`).join(''), { cls: 'btn small', align: 'left' }) : '';
  const n = (P().episodes.filter((e) => e.status === 'finalized').pop() || { plot: {} }).plot.number;
  return `<section class="card pf-sec editing" id="sw-now" tabindex="-1">
    <div class="pf-head"><h2>지금 상태창 <span class="small pf-state">고치는 중</span></h2></div>
    <div class="note info">값에 +3, -500처럼 바뀐 양만 적으면 지금 값에 더해요. 목록은 +독 내성, -은신처럼 붙이고 빼요.</div>
    <div class="sw-rows">${rows || '<div class="small">항목이 없어요. 항목을 더하거나 틀을 고르세요.</div>'}</div>
    <div class="row"><button type="button" class="btn small" data-action="swAdd">+ 항목 더하기</button>${workBtn}${presets}</div>
    <div class="between sw-foot"><span class="small">저장하면 ${n ? `${n}화의` : '1화 시작 값(처음 수치)인'} 작가 기록으로 남아요. 값을 비운 항목은 틀만 남고, 지운 항목은 '지움'으로 기록돼요.</span>
      <span class="row"><button type="button" class="btn small ghost" data-action="swEditCancel">취소</button><button type="button" class="btn small primary" data-action="swSave"${S.swDirty ? '' : ' disabled'}>저장</button></span></div></section>`;
}

/** 고치는 칸 옆 계산 값: 바뀐 양(+3, +독 내성)이면 '→ 새 값', 그 밖에는 빈 글 */
function swCalc(before, value) {
  const v = String(value || '').trim();
  if (!v || !/^[+-]/.test(v)) return '';
  const r = swResolve(before, v);
  if (r === v) return '';
  const list = r.match(SW_AMOUNT) ? [] : swItems(r);
  return list.length > 1 ? `→ ${list.length}개` : `→ ${r}`;  // 목록은 길어서 조각 수만
}

function swTextCard() {
  return `<section class="card" id="sw-text"><div class="between"><h2>본문에 넣을 상태창</h2>
      <span class="row"><a class="btn small ghost" href="${swHref('_decor')}">서식 고치기</a><button type="button" class="btn small" data-action="swCopy">복사</button></span></div>
    <pre class="sw-text">${esc(S.sw.text || '(값이 있는 항목이 없어요)')}</pre>
    <span class="small">AI가 본문에 상태창을 쓸 때도 이 서식을 따라요. 서식은 꾸미기에서 모든 인물에 함께 바꿔요.</span></section>`;
}

/** 화별 변화: 바뀐 화 목록(새 화가 위, 이전 값 → 새 값을 글로) | 표(바뀐 화만 열) */
function swLogCard() {
  const t = S.sw;
  const cols = t.columns || [];
  const seg = `<div class="seg" role="group" aria-label="변화 보기"><button type="button" data-action="swLogView" data-arg="list" aria-pressed="${S.swLog !== 'table'}">바뀐 화</button><button type="button" data-action="swLogView" data-arg="table" aria-pressed="${S.swLog === 'table'}">표</button></div>`;
  const changes = cols.filter((c) => c.episode > 0).length;
  const head = `<div class="between"><div class="row"><h2>화별 변화</h2><span class="small">${[cols.some((c) => c.episode === 0) ? '시작 값' : '', changes ? `${changes}번 바뀜` : ''].filter(Boolean).join(' · ')}</span></div>${cols.length ? seg : ''}</div>`;
  if (!cols.length) return `<section class="card" id="sw-log">${head}<div class="small">아직 기록이 없어요. 상태 승인 화면에서 AI가 적은 수치를 반영하거나, 위에서 값을 저장하면 쌓여요.</div></section>`;
  if (S.swLog === 'table') return `<section class="card" id="sw-log">${head}${swLogTable()}</section>`;
  const rows = [...cols].reverse();
  const shown = S.swLogAll ? rows : rows.slice(0, SW_LOG_FIRST);
  const srcChip = (c) => {
    const s = [...new Set(Object.values(c.changed).map((x) => x.source))];
    return s.map((k) => `<span class="chip ${k === 'ai' ? 'confirmed' : 'written'}">${SW_SOURCE[k]}</span>`).join('');
  };
  const list = shown.map((c) => `<li><span class="ep">${c.episode ? `<a href="${base()}/review/${c.episode}">${c.episode}화</a>` : '시작'}</span>
      <span class="sw-chs">${Object.entries(c.changed).map(([name, ch]) => swChangeHtml(name, ch, c.values[name])).join('')}</span><span class="sw-src">${srcChip(c)}</span></li>`).join('');
  const rest = rows.length - shown.length;
  return `<section class="card" id="sw-log">${head}<ul class="sw-log">${list}</ul>
    ${rest ? `<div><button type="button" class="btn small ghost" data-action="swLogMore">${rest}화 더 보기</button></div>` : ''}
    <span class="small">화를 누르면 그 화 상태 승인 기록으로 가요.</span></section>`;
}

function swLogTable() {
  const t = S.sw;
  const cols = t.columns;
  const head = `<tr><th scope="col">항목</th>${cols.map((c) => `<th scope="col">${c.episode ? `<a href="${base()}/review/${c.episode}">${c.episode}화</a>` : '시작'}</th>`).join('')}</tr>`;
  const body = t.names.map((name) => `<tr><th scope="row">${esc(name)}</th>${cols.map((c) => {
    const ch = c.changed[name];
    const v = c.values[name];
    if (!ch) return `<td>${esc(v || '')}</td>`;
    const src = ch.source === 'ai' ? '' : ' author';
    const was = c.episode && ch.before ? `<small>${esc(ch.before)}에서</small>` : '';
    return v ? `<td class="ch${src}">${esc(v)}${was}</td>` : `<td class="gone">${esc(ch.before)}<small>지움</small></td>`;
  }).join('')}</tr>`).join('');
  return `<div class="row small"><span class="chip confirmed">${SW_SOURCE.ai}</span><span class="chip written">${SW_SOURCE.author}</span><span>바뀐 칸 아래에 이전 값을 적어요.</span></div>
    <div class="sw-table-wrap"><table class="sw-table"><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
}

function swPersonPage() {
  const c = P().characters.find((x) => x.id === S.swCid);
  if (!c) return '<section class="card"><div class="small">목차에서 인물을 고르세요.</div></section>';
  if (!S.sw) return '<div class="small">불러오는 중…</div>';
  if (S.sw.error) return `<div class="note err">${esc(S.sw.error)}</div>`;
  const has = (S.sw.current || []).length || S.swEdit;
  return swHead(c) + swNowCard(c) + (has ? swTextCard() : '') + ((S.sw.columns || []).length ? swLogCard() : '');
}

// ----- 꾸미기 쪽 -----

function swDecorPage() {
  const c = P().characters.find((x) => x.id === S.swCid) || {};
  const who = c.name || c.id || '이름';
  const w = P().stat_window || { template: '', row: '' };
  const skins = Object.entries(SW_SKINS).map(([k, label]) => `<button type="button" class="sw-skin" aria-pressed="${k === swSkin()}" aria-label="${label}" data-action="swSkinPick" data-arg="${k}">
      ${swBox(k, swTitle(), who, swSample(swWin().names).slice(0, 3))}<span class="row"><strong>${label}</strong>${k === swSkin() ? '<span class="chip confirmed">고름</span>' : ''}</span></button>`).join('');
  const tplBtn = `<button type="button" class="btn small" data-action="swTplToggle" aria-expanded="${S.swTpl}">고치기</button>`;
  const tpl = S.swTpl
    ? `<section class="card pf-sec editing" id="sw-tpl-card" tabindex="-1"><div class="pf-head"><h2>창 이름과 본문 서식 <span class="small pf-state">고치는 중</span></h2></div>
        <div class="field"><label for="sw-title">창 이름 <span class="hint">화면 상태창 머리에 보여요 (예: 상태창, 무공록)</span></label><input id="sw-title" type="text" value="${esc(swTitle())}"></div>
        <div class="field"><label for="sw-tpl">본문 서식 <span class="hint">{name} 인물 이름, {rows} 항목 줄</span></label><textarea id="sw-tpl" rows="4">${esc(w.template)}</textarea></div>
        <div class="field"><label for="sw-row">항목 한 줄 <span class="hint">{key} 항목, {value} 값</span></label><input id="sw-row" type="text" value="${esc(w.row)}"></div>
        <div class="between"><span class="small">AI가 본문에 상태창을 쓸 때도 이 서식을 따라요.</span>
          <span class="row"><button type="button" class="btn small ghost" data-action="swTplToggle">취소</button><button type="button" class="btn small primary" data-action="swTplSave">저장</button></span></div></section>`
    : `<section class="card pf-sec" id="sw-tpl-card" tabindex="-1"><div class="pf-head"><h2>창 이름과 본문 서식</h2>${tplBtn}</div>
        <dl class="pf-dl"><dt>창 이름</dt><dd>${esc(swTitle())}</dd><dt>본문 서식</dt><dd><pre class="sw-code">${esc(w.template)}</pre></dd><dt>항목 한 줄</dt><dd><code>${esc(w.row)}</code></dd></dl></section>`;
  const opts = ((S.swSug || {}).options || []).map((o, i) => `<div class="sw-opt">
      <div class="between"><h3>${esc(o.label)}</h3><span class="small">${esc(SW_SKINS[o.skin] || o.skin)}</span></div>
      ${o.why ? `<div class="small">${esc(o.why)}</div>` : ''}
      <pre class="sw-text">${esc(swRender(o.template, o.row, who, swSample(o.names)))}</pre>
      ${swBox(o.skin, o.title, who, swSample(o.names))}
      ${o.names.length ? `<div class="small">작품 틀: ${esc(o.names.join(', '))}</div>` : ''}
      <button type="button" class="btn small" data-action="swUseOpt" data-arg="${i}">이 안 적용</button></div>`).join('');
  return `${tpl}
    <section class="card" id="sw-skins"><div class="between"><h2>화면 스킨</h2><span class="small">인물 화면과 여기에서 상태창을 그리는 모양이에요. 본문 글에는 들어가지 않아요</span></div>
      <div class="sw-skins" role="group" aria-label="화면 스킨">${skins}</div></section>
    <section class="card" id="sw-ai"><div class="between"><h2>설정에 맞게 꾸미기</h2>${S.swPrev ? '<button type="button" class="btn small ghost" data-action="swUndoOpt">적용 취소</button>' : ''}</div>
      <div class="field"><label for="sw-req">요청 <span class="hint">AI가 장르 · 배경 · 세계관 규칙을 읽고 본문 서식, 창 이름, 항목 틀, 스킨을 한 벌씩 제안해요</span></label>
        <div class="row sw-ask"><input id="sw-req" type="text" placeholder="비워도 돼요. 예: 더 어둡게, 마법 학교 느낌"><button type="button" class="btn small" data-action="swSuggest">AI 제안 받기</button></div></div>
      ${opts ? `<div class="sw-opts">${opts}</div><div class="small">적용하면 본문 서식 · 창 이름 · 스킨 · 작품 틀이 함께 바뀌어요. 인물의 항목 이름과 값은 그대로예요.</div>` : ''}
    </section>`;
}

// ----- 화면 -----

function viewStatwin() {
  const p = P();
  const head = header('작품 도구', '상태창 수치', '본문 상태창에 나오는 레벨 · 능력치 · 스킬 · 돈을 인물마다 화별로 기록해요. 항목을 하나라도 정하면 AI가 본문을 쓸 때 이 값을 따르고, 바뀐 값만 상태 변경안에 적어요. 반영은 승인한 뒤에만 돼요.');
  if (!p.characters.length) {
    return `${head}<section class="card csh-empty"><div class="empty"><p>아직 인물이 없어요. 상태창은 인물마다 적어요.</p><a class="btn primary" href="${base()}/setup">설정 도우미에서 인물 만들기</a></div></section>`;
  }
  const main = S.swPage === '_frame' ? swFramePage() : S.swPage === '_decor' ? swDecorPage() : swPersonPage();
  return `${head}${outlineDoc(swToc(), `<div class="sw-col">${main}</div>`, { cls: 'sw-wrap' })}`;
}

document.addEventListener('input', (e) => {
  const d = e.target.dataset || {};
  if (d.swName !== undefined) { S.swRows[Number(d.swName)].name = e.target.value; swTouch(); }
  if (d.swValue !== undefined) {
    const i = Number(d.swValue);
    S.swRows[i].value = e.target.value;
    const now = Object.fromEntries(((S.sw || {}).current || []).map((s) => [s.name, s.value]));
    const out = document.getElementById(`sw-calc-${i}`);
    if (out) out.textContent = swCalc(now[S.swRows[i].name.trim()], e.target.value);
    swTouch();
  }
});

function swTouch() {
  if (S.swDirty) return;
  S.swDirty = true;
  const b = document.querySelector('[data-action="swSave"]');
  if (b) b.disabled = false;
}

Object.assign(actions, {
  swEditGo() {
    S.swRows = (S.sw.current || []).map((s) => ({ ...s }));
    if (!S.swRows.length) S.swRows = (swWin().names || []).map((name) => ({ name, value: '' }));  // 처음 만들면 작품 틀부터
    S.swDirty = false;
    S.swEdit = true;
    S.focusTarget = '#app [data-sw-value="0"], #app [data-action="swAdd"]';
    render();
  },
  swEditCancel() {
    S.swEdit = false;
    S.swRows = (S.sw.current || []).map((s) => ({ ...s }));
    S.swDirty = false;
    S.focusTarget = '#app #sw-now [data-action="swEditGo"]';
    render();
  },
  swAdd() {
    S.swRows.push({ name: '', value: '' });
    S.swDirty = true;
    S.focusTarget = `#app [data-sw-name="${S.swRows.length - 1}"]`;
    render();
  },
  swDel(i) {
    S.swRows.splice(Number(i), 1);
    S.swDirty = true;
    S.focusTarget = '#app [data-action="swAdd"]';
    render();
  },
  /** 'i:d' 항목을 d(-1 위, 1 아래)만큼 옮긴다 */
  swMove(arg) {
    const [i, d] = String(arg).split(':').map(Number);
    const j = i + d;
    if (j < 0 || j >= S.swRows.length) return;
    [S.swRows[i], S.swRows[j]] = [S.swRows[j], S.swRows[i]];
    S.swDirty = true;
    S.focusTarget = `#app [data-action="swMove"][data-arg="${j}:${d}"]`;
    render();
  },
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
    await run('상태창 저장하는 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/statwin/${enc(S.swCid)}`, { stats });
      S.swEdit = false;
      await swLoad();
      S.focusTarget = '#app #sw-now [data-action="swEditGo"]';
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
  swLogView(v) { S.swLog = v === 'table' ? 'table' : 'list'; render(); },
  swLogMore() { S.swLogAll = true; render(); },
  swNoneToggle() {
    S.swNoneOpen = !S.swNoneOpen;
    outlineRefresh('sw-toc', swToc());
  },
  swTplToggle() {
    S.swTpl = !S.swTpl;
    S.focusTarget = S.swTpl ? '#sw-title' : '#app #sw-tpl-card [data-action="swTplToggle"]';
    render();
  },
  async swTplSave() {
    if (await swPut({ title: $('#sw-title').value, template: $('#sw-tpl').value, row: $('#sw-row').value || '{key}: {value}' }, '창 이름과 서식을 저장했어요')) {
      S.swTpl = false;
      S.focusTarget = '#app #sw-tpl-card [data-action="swTplToggle"]';
    }
    render();
  },
  async swSkinPick(k) {
    if (k === swSkin()) return;
    S.focusTarget = `#app [data-action="swSkinPick"][data-arg="${k}"]`;
    await swPut({ skin: k }, `${SW_SKINS[k]} 스킨으로 바꿨어요`);
  },
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
  return run('저장하는 중', async () => {
    await saveIfDirty();
    S.project = await api('PUT', `/projects/${enc(S.name)}/statwin-template`, body);
    await swLoad();
    if (dirty) { S.swRows = rows; S.swDirty = true; }
    toast(msg);
  });
}

// ----- 작품 틀 · 처음 수치 쪽 -----

/** 1화를 반영했으면 처음 수치는 더 고치지 않는다 (그 뒤 고친 값은 인물 쪽에서 작가 기록으로) */
const swLocked = () => P().episodes.some((e) => e.status === 'finalized');

/** 상태창을 자주 쓰는 작품인지: 현대 판타지 장르, 또는 설정 글에 상태창 · 레벨업 · 시스템 창 */
function swWanted(p) {
  const text = [p.meta.genre, p.meta.logline, p.meta.notes, p.world.setting, ...(p.world.rules || [])].join(' ');
  return (p.meta.genres || []).includes('modern_fantasy') || /상태창|상태 창|레벨\s?업|시스템 창/.test(text);
}

/** 고치는 중이 아니면 늘 작품에서 다시 읽는다 (인물 쪽에서 고친 값도 따라오게) */
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

function swFramePage() {
  const p = P();
  const has = p.states.some((s) => (s.stats || []).length);
  const names = swWin().names || [];
  const locked = swLocked();
  const chips = names.map((x, i) => `<span class="sw-name">${esc(x)}${locked ? '' : `<button type="button" class="btn icon-btn ghost" data-action="swNameDel" data-arg="${i}" aria-label="${esc(x)} 빼기">✕</button>`}</span>`).join('');
  const presets = menuBtn('sw-frame-preset', `틀 고르기 ${CHEVRON}`, () => Object.entries(SW_PRESETS).map(([k, xs]) => `<button type="button" class="pop-item" data-action="swNamePreset" data-arg="${k}">${SW_PRESET_LABELS[k]}<span class="small">${esc(xs.join(', '))}</span></button>`).join(''), { cls: 'btn small', align: 'left' });
  const want = !has && !names.length && swWanted(p) ? '<div class="note info">이 작품은 상태창을 쓰는 장르예요. 1화 전에 처음 수치를 정해 두면 AI가 본문을 쓸 때 이 값을 따라요.</div>' : '';
  const frame = `<section class="card" id="sw-frame"><div class="between"><h2>작품 틀</h2><span class="small">모든 인물 상태창의 항목 · 처음 수치 표의 열</span></div>
    ${chips ? `<div class="row sw-names">${chips}</div>` : `<div class="small">아직 없어요. ${locked ? '' : '항목을 더하거나 틀을 고르세요.'}</div>`}
    ${locked ? '<div class="note plain">1화를 반영한 뒤라 작품 틀과 처음 수치는 잠겼어요. 지금 수치는 인물 쪽에서 고쳐요(그 화의 작가 기록으로 남아요).</div>'
    : `<div class="row sw-ask"><input id="swi-name" type="text" placeholder="항목 이름 (예: 레벨, 내공)" aria-label="작품 틀에 더할 항목"><button type="button" class="btn small" data-action="swNameAdd">더하기</button>${presets}</div>`}</section>`;
  return want + frame + swInitCard();
}

/** 1화 시작 값: 0화 기록(처음 수치)에서 인물 · 항목마다 마지막 값. { 인물 id: { 항목: 값 } } */
function swStartValues() {
  const out = {};
  for (const r of (P().stat_log || []).filter((x) => x.episode === 0)) (out[r.character_id] = out[r.character_id] || {})[r.name] = r.value;
  return out;
}

function swInitCard() {
  const p = P();
  const locked = swLocked();
  // 1화 반영 뒤에는 고칠 수 없어 기록에 남은 시작 값을 읽기로 보인다. 그 전에는 지금 값(=처음 수치)을 고친다
  const d = locked ? swStartValues() : swInitDraft();
  const cols = locked ? [...new Set([...(swWin().names || []), ...Object.values(d).flatMap((x) => Object.keys(x))])] : swInitCols();
  const rows = locked ? p.characters.filter((c) => d[c.id] && (S.swInitAll || c.tier !== 'minor')) : swInitRows();
  const minor = p.characters.some((c) => c.tier === 'minor');
  const n = p.states.filter((s) => (s.stats || []).length).length;
  const table = cols.length && rows.length ? `<div class="sw-table-wrap"><table class="sw-table sw-init"><thead><tr><th scope="col">인물</th>${cols.map((k) => `<th scope="col">${esc(k)}</th>`).join('')}</tr></thead><tbody>
      ${rows.map((c) => `<tr><th scope="row">${esc(c.name || c.id)}</th>${cols.map((k) => locked ? `<td>${esc((d[c.id] || {})[k] || '')}</td>`
        : `<td><input type="text" data-swi-cid="${esc(c.id)}" data-swi-key="${esc(k)}" value="${esc((d[c.id] || {})[k] || '')}" aria-label="${esc(c.name || c.id)} ${esc(k)}"></td>`).join('')}</tr>`).join('')}
    </tbody></table></div>` : `<div class="small">${cols.length ? '인물이 없어요.' : '작품 틀을 정하거나 AI 제안을 받으면 인물마다 처음 수치를 적는 표가 생겨요.'}</div>`;
  const ai = locked ? '' : `<div class="field"><label for="swi-req">AI 처음 수치 제안 <span class="hint">로그라인 · 배경 · 인물 설정을 읽고 1화 시작 값을 인물마다 제안해요. 이미 적은 값은 그대로 둬요</span></label>
      <div class="row sw-ask"><input id="swi-req" type="text" placeholder="비워도 돼요. 예: 주인공은 F급에서 시작"><button type="button" class="btn small" data-action="swInitAI">AI 제안 받기</button></div></div>
    ${swInitSugBox()}`;
  const foot = locked ? '' : `<div class="between sw-foot"><span class="small">저장하면 1화 시작 값으로 남아요. 값을 모두 비운 인물은 상태창이 없어져요.</span>
      <button type="button" class="btn primary" data-action="swInitSave"${S.swInitDirty ? '' : ' disabled'}>처음 수치 저장</button></div>`;
  return `<section class="card" id="sw-start"><div class="between"><div class="row"><h2>처음 수치</h2><span class="small">1화 시작 값${n ? ` · ${n}명` : ''}${locked ? ' · 잠김' : ''}</span></div>
      ${minor ? `<button type="button" class="btn small ghost" data-action="swInitAllToggle" aria-pressed="${S.swInitAll}">${S.swInitAll ? '단역 숨기기' : '단역도 보기'}</button>` : ''}</div>
    ${table}${ai}${foot}</section>`;
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
    return `<li><label class="sw-pick"><input type="checkbox" data-swi-pick="${esc(c.character_id)}"${empty ? ' checked' : ''}>
      <span><strong>${esc(who(c.character_id))}</strong>${empty ? '' : ' <span class="small">이미 값이 있어 기본으로 고르지 않았어요</span>'}<br>${cells}${c.note ? `<br><span class="small">${esc(c.note)}</span>` : ''}</span></label></li>`;
  }).join('');
  return `<div class="note plain sw-sug"><div class="between"><strong>AI 처음 수치 제안</strong><span class="small">표에 넣기만 해요. 저장해야 남아요</span></div>${rows ? `<ul class="sw-picks">${rows}</ul>
      <div class="row"><button type="button" class="btn small" data-action="swInitUse">고른 인물 표에 넣기</button><button type="button" class="btn small ghost" data-action="swInitDrop">닫기</button></div>`
    : '<div class="small">상태창이 있는 인물을 찾지 못했어요. 요청에 누가 상태창을 보는지 적어 다시 받아 보세요.</div>'}</div>`;
}

/** 작품 틀만 저장 (서식 · 창 이름 · 스킨은 그대로) */
async function swNamesPut(names, msg) {
  const w = swWin();
  return run('저장하는 중', async () => {
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
    S.focusTarget = '#swi-name';
    await swNamesPut([...names, x.trim()], `'${x.trim()}' 항목을 더했어요`);
  },
  async swNameDel(i) {
    const names = [...(swWin().names || [])];
    const [x] = names.splice(Number(i), 1);
    S.focusTarget = '#swi-name';
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
    if (!picked.size) { toast('넣을 인물을 고르세요', true); return; }
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
    await run('처음 수치 저장하는 중', async () => {
      await saveIfDirty();
      if (!names.length && extra.length) {  // AI 제안으로 생긴 항목을 작품 틀로
        const w = swWin();
        S.project = await api('PUT', `/projects/${enc(S.name)}/statwin-template`, { template: w.template, row: w.row, names: extra });
      }
      for (const [cid, stats] of jobs) S.project = await api('PUT', `/projects/${enc(S.name)}/statwin/${enc(cid)}`, { stats });
      S.swInit = null;
      // 인물 쪽 '지금 상태창'도 새 값으로. 고치던 항목은 그대로 둔다 (swPut 과 같다)
      const rows = S.swRows;
      const dirty = S.swDirty;
      await swLoad();
      if (dirty) { S.swRows = rows; S.swDirty = true; }
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

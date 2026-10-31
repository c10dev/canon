/* 2단계 문체 레퍼런스와 문체 라이브러리. app.js 의 S, actions, api, render, input, header 를 그대로 쓴다. */
'use strict';

// ----- 2. 문체 -----

function emptyProfile() {
  return {
    narration_pov: '', tense: '', sentence_rhythm: '', description_density: '', dialogue_ratio: '', dialogue_style: '',
    inner_monologue: '', pacing: '', scene_transition: '', vocabulary: '', dos: [], donts: [], banned_phrases: [], markers: [], devices: [], sample_passages: [],
  };
}

// 프로필 카드: id, 이름. 화면은 왼쪽 목차 + 오른쪽 카드 한 열이고, 카드는 읽는 모양이 기본이며 '고치기'로 그 카드만 고치는 칸을 편다.
// 작품 화면(base 'style')과 라이브러리 항목(base 'profile', root 'lib')이 같은 카드를 쓴다
const STYLE_CARDS = [['narr', '서술'], ['rules', '지킬 · 피할 것'], ['markers', '문체 표지'], ['devices', '가끔 쓰는 장치'], ['passages', '대표 문단']];
const NARR_KEYS = ['narration_pov', 'tense', 'sentence_rhythm', 'description_density', 'dialogue_ratio', 'dialogue_style',
  'inner_monologue', 'pacing', 'scene_transition', 'vocabulary'];

/** 카드에 든 프로필 칸 (목차 수 · 빈 카드 · 대화 변경안 표시). */
const styleCardKeys = (id) => (id === 'narr' ? NARR_KEYS
  : { rules: ['dos', 'donts', 'banned_phrases'], markers: ['markers'], devices: ['devices'], passages: ['sample_passages'] }[id] || []);

/** 카드가 비었다. 빈 카드는 읽는 모양 없이 바로 고치는 칸을 보인다. */
function styleCardEmpty(id, st) {
  return !styleCardKeys(id).some((k) => (Array.isArray(st[k]) ? st[k].length > 0 : String(st[k] || '').trim() !== ''));
}

/** 목차에 보일 수: 서술은 채운 칸/10, 나머지는 항목 수. */
function styleCount(id, st) {
  if (id === 'narr') return `${NARR_KEYS.filter((k) => String(st[k] || '').trim()).length}/10`;
  return String(styleCardKeys(id).reduce((s, k) => s + (st[k] || []).length, 0));
}

/** 작품 문체 화면의 목차 줄 [id, 이름, 오른쪽 글, 표시]. 표시는 'warn'(확인할 것) · 'hot'(대화 변경안이 바꿀 카드) · ''.
    id '-' 는 묶음 이름 줄이다. todo 는 고르지 않은 규칙 후보 수, link 는 라이브러리 상태 글 */
function styleTocItems(st, { hot = new Set(), todo = 0, example = '', link = '', learn = '' } = {}) {
  const rows = [];
  if (todo) rows.push(['todo', '확인할 것', String(todo), 'warn']);
  rows.push(['example', '이 문체로 쓴 예시', example, example === '바뀜' ? 'warn' : '']);
  STYLE_CARDS.forEach(([id, label]) => rows.push([id, label, styleCount(id, st), styleCardKeys(id).some((k) => hot.has(k)) ? 'hot' : '']));
  rows.push(['-', '재료', '', '']);
  rows.push(['status', '라이브러리 · 기준 지표', link, link === '다름' ? 'warn' : '']);
  rows.push(['source', '원문 · 다시 분석', '', '']);
  rows.push(['learn', '내 수정에서 배우기', learn, '']);
  return rows;
}

// ----- 목차 (공용 목차 틀 outline.js: 왼쪽, 좁은 칸에서는 위에 붙는 '지금 카드 ▾' 버튼) -----

let styleTocCur = '';    // 지금 보는 카드 id. 스크롤로 바뀐다
let styleTocRows = [];   // 마지막으로 그린 목차 줄 (스크롤 때 목차만 다시 그린다)

let styleTocHash = '';   // 목차를 그린 화면 주소. 다른 화면으로 오면 지금 카드를 잊는다

function styleToc(rows = styleTocRows, label = '문체 목차') {
  styleTocRows = rows;
  if (styleTocHash !== location.hash) { styleTocHash = location.hash; styleTocCur = ''; }
  const items = rows.filter(([id]) => id !== '-');
  const cur = items.find(([id]) => id === styleTocCur) || items[0];
  const list = rows.map(([id, l, right, mark]) => (id === '-'
    ? `<span class="outline-h">${esc(l)}</span>`
    : `<button type="button" class="outline-item${mark ? ` ${mark}` : ''}" data-action="styleGo" data-arg="${id}"${id === cur[0] ? ' aria-current="true"' : ''}><span class="tl">${esc(l)}</span>${mark === 'hot' ? '<span class="chip hot">변경안</span>' : ''}<span class="st">${esc(right || '')}</span></button>`)).join('');
  return outlineNav({ id: 'sty-toc', label, now: `${esc(cur[1])} <span class="small">${esc(cur[2] || '')}</span>`, body: list });
}

// 지금 카드: 화면 위에서 120px 아래를 지난 마지막 카드(맨 아래면 마지막 카드). 바뀌면 목차만 다시 그린다.
// 목차 순서와 카드 순서가 다르다(라이브러리 · 기준 지표 카드는 맨 위, 목차는 재료 묶음). outlinePick 이 화면 위치로 고른다
outlineSpy('sty-toc', {
  targets: () => styleTocRows.filter(([id]) => id !== '-').map(([id]) => [id, document.getElementById(`pf-${id}`)]),
  set(cur) {
    if (cur === styleTocCur) return;
    styleTocCur = cur;
    outlineRefresh('sty-toc', styleToc());
  },
});

// ----- 프로필 카드 -----

/** 카드를 고치는 중인지 기억하는 열쇠: 작품마다, 라이브러리 항목마다 따로 */
const pfKey = (root, id) => (root ? `lib:${(S.lib && S.lib.id) || 'new'}:${id}` : `${S.name}:${id}`);
const pfOpen = (root, id) => !!(S.styleOpen || {})[pfKey(root, id)];

/** 대화 패널이 열려 있고 아직 고르지 않은 문체 변경안이 있으면 그 변경안이 바꿀 칸 (카드에 표시한다). */
function styleChatKeys() {
  if (!S.chatOpen || typeof chatMessages !== 'function') return new Set();
  const msgs = chatMessages('style');
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = msgs[i];
    if (m.style) return new Set(m.outcome ? [] : m.style.edits.map((e) => e.key));
  }
  return new Set();
}

/** 이름 없이 aria-label 만 단 입력칸 (표지 표처럼 칸 이름이 표 머리에 있을 때). app.js 의 input 과 같은 바인딩 */
function bareInput(path, label, { root = '', kind = 'text', cls = '', placeholder = '' } = {}) {
  return `<input id="f-${path.replace(/\./g, '-')}" type="text" class="${cls}" value="${esc(bindValue(path, kind, root))}" data-bind="${path}" data-kind="${kind}"${root ? ` data-root="${root}"` : ''} aria-label="${esc(label)}" placeholder="${esc(placeholder)}">`;
}

/** 카드 하나. editing 이면 고치는 칸, 아니면 읽는 모양. 빈 카드는 바로 고치는 칸이고 '고치기' 버튼이 없다 */
function pfCard(id, label, base, root, hot) {
  const prof = getPath(bindRoot(root), base);
  const empty = styleCardEmpty(id, prof);
  const editing = empty || pfOpen(root, id);
  const isHot = styleCardKeys(id).some((k) => hot.has(k));
  const add = editing ? { markers: ['addMarker', '+ 표지'], devices: ['deviceAdd', '+ 장치'], passages: ['addPassage', '+ 문단'] }[id] : null;
  const btns = [
    add ? `<button type="button" class="btn small" data-action="${add[0]}" data-arg="${root}">${add[1]}</button>` : '',
    empty && !pfOpen(root, id) ? '' : `<button type="button" class="btn small" data-action="styleEdit" data-arg="${root}|${id}" aria-expanded="${editing}">${editing ? '다 고쳤어요' : '고치기'}</button>`,
  ].join('');
  const sub = { markers: '어미 · 조사 · 말버릇과 원문 빈도. 넘치거나 빠지면 경고해요', devices: '특정 상황에만, 몇 화에 한 번 쓰는 장면 장치', passages: '본문 생성 때 원문 그대로 보여 줘요, 2~4개' }[id];
  const body = editing ? pfEdit(id, base, root, hot) : pfRead(id, prof, root, hot);
  return `<section class="card pf-sec${editing ? ' editing' : ''}" id="pf-${id}" tabindex="-1"${empty ? ` data-pf-key="${esc(pfKey(root, id))}"` : ''}>
      <div class="pf-head"><h2>${label}${isHot ? ' <span class="chip hot">대화 변경안</span>' : ''}${editing && !empty ? ' <span class="small pf-state">고치는 중</span>' : ''}</h2><div class="row">${btns}</div></div>
      ${sub ? `<p class="small pf-sub">${sub}</p>` : ''}${body}</section>`;
}

function profileCards(base, root = '', hot = new Set()) {
  return STYLE_CARDS.map(([id, label]) => pfCard(id, label, base, root, hot)).join('');
}

const pfNone = '<span class="muted">비어 있음</span>';

/** 카드의 읽는 모양 */
function pfRead(id, prof, root, hot) {
  const list = (xs) => (xs || []).length ? `<ul class="pf-list">${xs.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : `<div class="small">${pfNone}</div>`;
  if (id === 'narr') {
    return `<dl class="pf-dl">${STYLE_KEYS.slice(0, 10).map(([k, l]) => `<dt${hot.has(k) ? ' class="hot"' : ''}>${l}${hot.has(k) ? ' <span class="chip hot">변경안</span>' : ''}</dt><dd>${String(prof[k] || '').trim() ? esc(prof[k]) : pfNone}</dd>`).join('')}</dl>`;
  }
  if (id === 'rules') {
    const tag = (k) => (hot.has(k) ? ' <span class="chip hot">변경안</span>' : '');
    return `<div class="grid-2">
        <div><div class="pf-lbl"><i class="sw ok" aria-hidden="true"></i>지킬 것 ${(prof.dos || []).length}${tag('dos')}</div>${list(prof.dos)}</div>
        <div><div class="pf-lbl"><i class="sw no" aria-hidden="true"></i>피할 것 ${(prof.donts || []).length}${tag('donts')}</div>${list(prof.donts)}</div>
      </div>
      <div><div class="pf-lbl">금지 표현 ${(prof.banned_phrases || []).length}${tag('banned_phrases')} <span class="small">본문에 나오면 경고해요</span></div>
        ${(prof.banned_phrases || []).length ? `<div class="row">${prof.banned_phrases.map((x) => `<span class="chip pf-quote">${esc(x)}</span>`).join('')}</div>` : `<div class="small">${pfNone}</div>`}</div>`;
  }
  if (id === 'markers') {
    return `<table class="pf-table"><thead><tr><th scope="col">표지</th><th scope="col">쓰임</th><th scope="col" class="num">1,000자당</th></tr></thead>
      <tbody>${prof.markers.map((m) => `<tr><td class="pf-quote">${esc(m.text) || pfNone}</td><td>${esc(m.note)}</td><td class="num">${Number(m.per_1k || 0).toFixed(1)}</td></tr>`).join('')}</tbody></table>`;
  }
  if (id === 'devices') {
    // 마지막으로 쓴 화는 집필 화면 배지와 같은 규칙 (marks.js deviceLast, metrics.device_last)
    const counted = !root && typeof deviceLast === 'function' && P().episodes.some((e) => (e.text || '').trim());
    return `<div class="pf-devs">${prof.devices.map((d) => {
      const cues = (d.cues || []).filter((c) => String(c).trim());
      const last = counted && cues.length ? deviceLast(cues, Infinity) : 0;
      return `<div class="pf-dev"><div class="pf-dev-main"><strong>${esc(d.name) || pfNone}</strong>${d.when ? ` <span class="small">· ${esc(d.when)}</span>` : ''}
          ${cues.length ? `<div class="small">알아보는 글자 <span class="pf-quote">${cues.map((c) => `'${esc(c)}'`).join(' ')}</span></div>` : ''}</div>
        <div class="pf-dev-side"><span class="chip">${d.every ? `${d.every}화에 한 번` : '상황이 올 때만'}</span>${counted && cues.length ? `<span class="small">${last ? `마지막으로 쓴 화 ${last}화` : '아직 안 씀'}</span>` : ''}</div></div>`;
    }).join('')}</div>`;
  }
  return `<ol class="pf-pass">${prof.sample_passages.map((x) => `<li><p class="prose-quote pf-clamp">${esc(x)}</p></li>`).join('')}</ol>`;
}

/** 카드의 고치는 칸. 칸은 글 길이만큼 늘어난다. 대화 변경안이 바꿀 칸은 테두리로 표시한다 */
function pfEdit(id, base, root, hot) {
  const o = (x = {}) => (root ? { ...x, root } : x);
  const prof = getPath(bindRoot(root), base);
  const f = (label, key, x = {}) => input(hot.has(key) ? `${label} · 대화 변경안` : label, `${base}.${key}`,
    o({ rows: 1, autogrow: true, ...x, cls: hot.has(key) ? 'chat-target' : '' }));
  if (id === 'narr') return `<div class="grid-2">${STYLE_KEYS.slice(0, 10).map(([key, label]) => f(label, key)).join('')}</div>`;
  if (id === 'rules') {
    return `<div class="grid-2">
        <div class="note ok">${f('지킬 것', 'dos', { kind: 'list', rows: 3 })}</div>
        <div class="note err">${f('피할 것', 'donts', { kind: 'list', rows: 3 })}</div>
      </div>
      ${f('금지 표현', 'banned_phrases', { kind: 'list', rows: 2, placeholder: '본문에 나오면 경고할 표현, 한 줄에 하나씩' })}`;
  }
  if (id === 'markers') {
    prof.markers = prof.markers || [];
    const rows = prof.markers.map((_, i) => `<div class="mk-row">
        <div class="mk-text">${bareInput(`${base}.markers.${i}.text`, `표지 ${i + 1}`, { root, cls: 'pf-quote', placeholder: '원문에 적힌 그대로, 예: 것이었다' })}</div>
        <div class="mk-note">${bareInput(`${base}.markers.${i}.note`, `표지 ${i + 1} 쓰임`, { root, placeholder: '어디에 어떻게 쓰는지' })}</div>
        <div class="mk-rate">${bareInput(`${base}.markers.${i}.per_1k`, `표지 ${i + 1} 1,000자당`, { root, kind: 'float' })}</div>
        <button type="button" class="btn icon-btn danger mk-del" data-action="removeMarker" data-arg="${root}|${i}" aria-label="표지 ${i + 1} 삭제">✕</button></div>`).join('');
    return rows ? `<div class="mk-grid"><div class="mk-row mk-th" aria-hidden="true"><span class="mk-text">표지 (원문 그대로)</span><span class="mk-note">쓰임</span><span class="mk-rate">1,000자당</span><span class="mk-del"></span></div>${rows}</div>
        <p class="small">빈도는 저장할 때 원문에서 다시 세요.</p>`
      : '<div class="small">아직 없어요. 문체 분석을 하면 원문에서 골라 빈도를 세어요.</div>';
  }
  if (id === 'devices') return deviceFields(base, root);
  return passageFields(base, root);
}

/** 대표 문단 칸. 본문 생성 때 원문 그대로 들어가니 본문 글꼴로 보이고, 글 길이만큼 늘어난다. */
function passageFields(base, root) {
  const o = (x = {}) => (root ? { ...x, root } : x);
  const prof = getPath(bindRoot(root), base);
  const passages = prof.sample_passages.map((_, i) => `<div class="field-row">
      <div class="fr-grow">${input(`대표 문단 ${i + 1}`, `${base}.sample_passages.${i}`, o({ rows: 3, autogrow: true, cls: 'passage' }))}</div>
      <button class="btn icon-btn danger" data-action="removePassage" data-arg="${root}|${i}" aria-label="대표 문단 ${i + 1} 삭제">✕</button></div>`).join('');
  return passages || '<div class="small">아직 없어요. 문체 분석을 하면 원문에서 골라 넣어요.</div>';
}

// 빈 카드에 쓰기 시작하면 그 카드를 '고치는 중'으로 기억한다 (다시 그려도 읽는 모양으로 바뀌지 않게)
document.addEventListener('input', (e) => {
  const sec = e.target.closest && e.target.closest('.pf-sec[data-pf-key]');
  if (sec) S.styleOpen = { ...S.styleOpen, [sec.dataset.pfKey]: true };
});

// ----- 작품 문체 화면 -----

/** 라이브러리와 다를 때 어느 쪽이 바뀌었는지 (library.link_state 의 mine · theirs). */
function styleChangeWho(l) {
  const mine = (l.mine || []).length > 0;
  const theirs = (l.theirs || []).length > 0;
  if (!l.base_known) return l.applied && l.version > l.applied ? `이 작품은 ${l.applied}번 버전, 라이브러리는 ${l.version}번 버전이에요` : '이 작품에서 고쳤거나 라이브러리가 바뀌었어요';
  if (mine && theirs) return `이 작품도 고쳤고, 라이브러리도 ${l.applied}번 → ${l.version}번 버전으로 바뀌었어요`;
  if (theirs) return `라이브러리가 ${l.applied}번 → ${l.version}번 버전으로 바뀌었어요. 이 작품은 그대로예요`;
  return '이 작품에서 고쳤어요. 라이브러리는 가져온 버전 그대로예요';
}

/** 목차의 라이브러리 상태 글 */
const styleLinkWord = (l) => ({ same: '같음', changed: '다름', missing: '지워짐' }[(l || {}).state] || '');

/** 라이브러리 줄: 상태와 올리기 · 가져오기, 다른 문체 적용과 새로 저장은 ⋯ 메뉴 */
function styleLibraryRow() {
  const libs = S.libs || [];
  const l = S.styleLink || { state: 'none' };
  const blank = styleBlank(P().style);
  const status = {
    none: `<span class="small">${blank ? '아직 문체가 없어요. 카드를 채우거나 라이브러리에서 고르세요.' : '이 작품에서 직접 만든 문체예요. 라이브러리에 없어요.'}</span>`,
    missing: '<span class="small">가져온 라이브러리 항목이 지워졌어요. 작품에 복사된 문체는 그대로 써요.</span>',
    same: `<span class="chip finalized">라이브러리와 같음</span> <a href="#/styles/${esc(l.id)}">${esc(l.name)}</a> <span class="small">${l.version}번 버전</span>`,
    changed: `<span class="chip written">라이브러리와 다름</span> <a href="#/styles/${esc(l.id)}">${esc(l.name)}</a> <span class="small">${styleChangeWho(l)}</span>`,
  }[l.state] || '';
  const fields = (list) => list.map((c) => esc(c.label)).join(', ');
  const detail = l.state === 'changed' && ((l.mine || []).length || (l.theirs || []).length)
    ? `<details><summary class="small">어느 칸이 다른지</summary><div class="small" style="padding-top:6px">${(l.mine || []).length ? `<div>이 작품에서 고친 칸: ${fields(l.mine)}</div>` : ''}${(l.theirs || []).length ? `<div>라이브러리 ${l.version}번 버전에서 바뀐 칸: ${fields(l.theirs)}</div>` : ''}<div>올리기는 작품 쪽을 라이브러리 새 버전으로, 가져오기 · 되돌리기는 라이브러리 쪽을 작품에 가져와요.</div></div></details>` : '';
  // 라이브러리가 더 새 버전이면 '가져오기', 작품만 고쳤으면 '되돌리기'
  const newer = (l.theirs || []).length > 0 || (!l.base_known && l.applied && l.version > l.applied);
  const linkBtns = l.state === 'changed'
    ? `<button class="btn small" data-action="pushStyle">라이브러리에 올리기</button><button class="btn small" data-action="pullStyle">${newer ? '최신 버전 가져오기' : '라이브러리 버전으로 되돌리기'}</button>`
    : '';
  // 빈 문체는 저장하지 않는다 (web.keep_style 도 막는다). 프로필 칸을 채우면 아래 input 처리가 버튼을 켠다
  const menu = () => `<div class="sty-libmenu">
      ${libs.length
        ? `<label class="small" for="style-pick">다른 문체 적용</label><div class="row" style="flex-wrap:nowrap"><select id="style-pick" style="flex:1;min-width:0"><option value="">라이브러리에서 고르기</option>${libs.map((x) => `<option value="${esc(x.id)}"${x.id === l.id ? ' selected' : ''}>${esc(x.name)}${x.source ? ` · ${esc(x.source)}` : ''}</option>`).join('')}</select><button class="btn small" style="flex:none" data-action="useLibStyle">적용</button></div>`
        : '<span class="small">라이브러리가 비어 있어요. 이 작품의 문체를 저장해 두면 다른 작품에서 다시 쓸 수 있어요.</span>'}
      <button class="btn small" data-action="keepStyle"${blank ? ' disabled aria-describedby="keep-off"' : ''}>이 문체를 라이브러리에 새로 저장</button><span class="small" id="keep-off"${blank ? '' : ' hidden'}>카드를 채운 뒤 저장할 수 있어요</span>
      <a class="small" href="#/styles">라이브러리 열기</a></div>`;
  return `<div class="sty-row"><span class="sty-status">${status}</span>
      <span class="row sty-acts">${linkBtns}${menuBtn('style-lib', '⋯', menu, { cls: 'btn small', aria: '다른 문체 적용 · 라이브러리에 새로 저장' })}</span></div>${detail}`;
}

/** 맨 위 카드: 라이브러리 줄 + 기준 지표 칩 한 줄 */
function styleStatus() {
  const b = P().style_baseline;
  return `<section class="card tight pf-sec sty-top" id="pf-status" tabindex="-1" aria-label="라이브러리와 기준 지표">
      ${styleLibraryRow()}
      <div class="sty-row">${b ? `<span class="metric-chips">${baselineItems(b).map(([k, v, why]) => `<span title="${esc(why)}">${k} <strong>${v}</strong></span>`).join('')}</span>`
        : '<span class="small">원문을 분석하면 문장 길이, 대사 비율 같은 기준 지표를 재요</span>'}
        ${b ? `<span class="sty-acts">${menuBtn('style-metrics', '지표 풀이', () => baselineRows(b), { cls: 'btn small ghost' })}</span>` : ''}</div>
    </section>`;
}

// 작품 문체 칸을 채우거나 비우면 '라이브러리에 새로 저장' 버튼을 켜고 끈다 (다시 그리지 않고)
document.addEventListener('input', (e) => {
  if (S.route[2] !== 'style' || !(e.target.dataset.bind || '').startsWith('style.')) return;
  const btn = $('[data-action="keepStyle"]');
  if (!btn) return;
  btn.disabled = styleBlank(P().style);
  const why = $('#keep-off');
  if (why) why.hidden = !btn.disabled;
});

/** 스타일 프로필 칸이 모두 비었다 (library.blank 와 같은 규칙) */
const styleBlank = (st) => !Object.values(st || {}).some((v) => (typeof v === 'string' ? v.trim() : Array.isArray(v) ? v.length : v));

/** 예시 원문 칸과 '문체 분석'. 빈 작품은 이 버튼이 화면의 주 버튼이다 */
function styleSampleBox(blank) {
  return `<textarea id="sample" class="sty-sample" rows="${blank ? 14 : 10}" data-local="styleSample" aria-describedby="sample-why" oninput="document.getElementById('sample-count').textContent=this.value.length.toLocaleString()" placeholder="닮고 싶은 소설 본문을 붙여 넣으세요. 대사와 서술이 섞인 장면이 좋아요.">${esc(S.styleSample)}</textarea>
      <div class="sty-row"><span class="small" id="sample-why">원문은 작품에 저장되지 않고 고른 대표 문단만 남아요. 내용과 인물은 가져오지 않아요. 이 칸에 원문이 남아 있을 때 라이브러리에 저장하면 원문도 함께 보관해요.</span>
        <span class="sty-acts"><button class="btn${blank ? ' primary' : ''}" data-action="analyzeStyle">문체 분석</button></span></div>`;
}

const sampleCount = () => `<span class="small"><span id="sample-count">${S.styleSample.length.toLocaleString()}</span>자 · 2,000자 이상 권장</span>`;

/** 재료 카드: 원문을 다시 붙여 넣어 분석. 원문 칸은 열 때만 */
function styleSourceCard() {
  const open = S.styleSampleOpen || S.styleSample.trim();
  return `<section class="card pf-sec" id="pf-source" tabindex="-1">
      <div class="pf-head"><h2><label for="sample">원문 · 다시 분석</label></h2><div class="row">${open ? sampleCount() : ''}<button type="button" class="btn small" data-action="toggleStyleSample" aria-expanded="${!!open}">${open ? '접기' : '원문 붙여 넣기'}</button></div></div>
      ${open ? styleSampleBox(false) : '<p class="small pf-sub">원문을 다시 분석하면 지금 카드를 분석 결과로 바꿔요. 저장하기 전에는 되돌릴 수 있어요.</p>'}
    </section>`;
}

/** 빈 작품: 라이브러리 항목을 한 줄씩, 줄마다 '적용' */
function stylePickCard() {
  const libs = S.libs || [];
  const chips = (x) => [x.narration_pov, x.tense].filter(Boolean).map((v) => `<span class="chip">${esc(v)}</span>`).join('')
    + [['대표 문단', x.passages], ['지킬 · 피할 것', x.rules], ['표지', x.markers], ['장치', x.devices]].filter(([, v]) => v).map(([k, v]) => `<span class="chip">${k} ${v}</span>`).join('');
  const rows = libs.map((x) => `<div class="sty-lib-item"><div class="sty-lib-main"><strong>${esc(x.name)}</strong>${x.source ? ` <span class="small">· ${esc(x.source)}</span>` : ''}
        <div class="row">${chips(x)}<span class="small">${x.used_by.length ? `쓰는 작품 ${x.used_by.length}` : '쓰는 작품 없음'}</span></div></div>
      <button type="button" class="btn small" data-action="useLibStyle" data-arg="${esc(x.id)}" aria-label="${esc(x.name)} 적용">적용</button></div>`).join('');
  return `<section class="card pf-sec" id="pf-pick" tabindex="-1">
      <div class="pf-head"><h2>라이브러리에서 고르기</h2><a class="small" href="#/styles">라이브러리 열기</a></div>
      ${rows ? `<div class="sty-lib-list">${rows}</div>` : '<p class="small pf-sub">라이브러리가 비어 있어요. 문체를 만든 뒤 저장해 두면 다른 작품에서 다시 쓸 수 있어요.</p>'}
    </section>`;
}

function viewStyle() {
  styleSeen = { name: S.name, title: P().meta.title || S.name };
  const st = P().style;
  const next = stepLabel('arc');
  const go = (primary) => `${chatButton('style')}<a class="btn${primary ? ' primary' : ''}" href="${base()}/arc">${next}${josa(next, '으로', '로')}</a>`;
  // 문체가 비었으면 시작하는 세 갈래(원문 · 라이브러리 · 직접 채우기)만 보인다. '문체 분석'이 주 버튼이다
  if (styleBlank(st) && !(S.styleManual || {})[S.name]) {
    const rows = [['source', '원문 붙여 넣기', '', ''], ['pick', '라이브러리에서 고르기', String((S.libs || []).length), ''], ['manual', '직접 채우기', '', '']];
    return `${header('2단계', stepLabel('style'), '닮고 싶은 소설 문단을 붙여 넣으면 문체 규칙을 뽑아요. 규칙과 대표 문단이 매 화 본문 생성에 함께 들어가요.', go(false))}
    <div class="outline-wrap style-page"><div class="outline-doc">${styleToc(rows, '문체 시작하기')}<div class="sty-secs">
      <section class="card pf-sec" id="pf-source" tabindex="-1"><div class="pf-head"><h2><label for="sample">예시 원문</label></h2>${sampleCount()}</div>${styleSampleBox(true)}</section>
      ${stylePickCard()}
      <section class="card tight pf-sec" id="pf-manual" tabindex="-1"><div class="sty-row"><div><h3>직접 채우기</h3><p class="small pf-sub">원문 없이 시점 · 시제부터 카드를 하나씩 채워요. 대화로 다듬기에서 말로 시작해도 돼요.</p></div>
        <span class="sty-acts"><button type="button" class="btn small" data-action="styleManual">빈 카드 열기</button></span></div></section>
    </div></div></div>${chatPanel('style')}`;
  }
  const hot = styleChatKeys();
  const r = P().style_learning;
  const todo = r ? r.suggestions.filter((s) => !s.applied).length : 0;
  const ex = P().style_example;
  const rows = styleTocItems(st, { hot, todo, example: ex ? (exampleStale(ex) ? '바뀜' : '있음') : '', link: styleLinkWord(S.styleLink), learn: S.editStats ? `${S.editStats.usable}건` : '' });
  return `${header('2단계', stepLabel('style'), '이 규칙과 대표 문단이 매 화 본문 생성에 함께 들어가요. 카드의 \'고치기\'로 그 카드만 고쳐요.', go(true))}
    <div class="outline-wrap style-page"><div class="outline-doc">${styleToc(rows)}<div class="sty-secs">
      ${styleStatus()}${todo ? learnTodoCard() : ''}${styleExampleCard()}${profileCards('style', '', hot)}${styleSourceCard()}${learnCard()}
    </div></div></div>${chatPanel('style')}`;
}

// ----- 문체 라이브러리 -----

/** 날짜 'YYYY.MM.DD' 와 날짜 시각 'YYYY.MM.DD HH:mm'. 서버는 UTC 로 적으므로 이 기기의 시간대로 바꿔 보인다. */
function fmtDate(iso) {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) return iso || '';
  const p2 = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}.${p2(d.getMonth() + 1)}.${p2(d.getDate())}`;
}

function fmtDateTime(iso) {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) return iso || '';
  const p2 = (x) => String(x).padStart(2, '0');
  return `${fmtDate(iso)} ${p2(d.getHours())}:${p2(d.getMinutes())}`;
}

/** 예시 문구에 넣을 인물 이름: 이 작품의 i번째 인물. 없으면 '주인공', '조연' (특정 작품의 이름을 박아 두지 않는다) */
const exName = (i = 0) => (P() && P().characters[i] && P().characters[i].name) || ['주인공', '조연', '악역'][i] || '인물';

/** 화 범위 'a~b화' (한 화면 'a화'). 범위 기호는 물결표 하나로 쓴다. */
const epRange = (a, b) => (a === b ? `${a}화` : `${a}~${b}화`);

// ----- 라이브러리에서 들어온 작품으로 돌아가기 -----
// 작품 문체 화면에서 라이브러리(#/styles)로 오면 그 작품을 기억한다. 라이브러리 밖으로 나가면 잊는다.
// 라이브러리 화면은 S.name 을 비우므로 작품 이름은 이동 전 주소(oldURL)에서 읽고, 제목은 문체 화면을 그릴 때 적어 둔다
let libFrom = (() => { try { return JSON.parse(sessionStorage.getItem('canon.libFrom') || 'null'); } catch { return null; } })();
let styleSeen = null;  // 마지막으로 그린 작품 문체 화면 { name, title }

function setLibFrom(v) {
  libFrom = v;
  try { if (v) sessionStorage.setItem('canon.libFrom', JSON.stringify(v)); else sessionStorage.removeItem('canon.libFrom'); } catch { /* 저장 못 해도 이번 화면에서는 돌아갈 수 있다 */ }
}

window.addEventListener('hashchange', (e) => {
  const hashOf = (url) => { const i = String(url || '').indexOf('#'); return i < 0 ? '' : String(url).slice(i); };
  if (!/^#\/styles(\/|$)/.test(location.hash)) return setLibFrom(null);
  const m = /^#\/p\/([^/]+)\/style$/.exec(hashOf(e.oldURL));
  if (!m) return;
  const name = decodeURIComponent(m[1]);
  setLibFrom({ name, title: styleSeen && styleSeen.name === name ? styleSeen.title : name });
});

/** 들어온 작품의 문체 화면으로 가는 버튼. 작품 문체 화면에서 오지 않았으면 빈 글 */
function libBackBtn() {
  return libFrom ? `<a class="btn" href="#/p/${enc(libFrom.name)}/style">‘${esc(libFrom.title)}’ 문체로 돌아가기</a>` : '';
}

function viewLibrary() {
  const list = S.libs || [];
  const cards = list.map((x) => `<article class="card tight">
      <div class="between"><h3><a href="#/styles/${esc(x.id)}" style="color:inherit;text-decoration:none">${esc(x.name)}</a></h3><span class="small">${fmtDate(x.updated_at)}</span></div>
      ${x.source ? `<div class="small">${esc(x.source)}</div>` : ''}
      <div class="row">
        ${x.narration_pov ? `<span class="chip">${esc(x.narration_pov)}</span>` : ''}${x.tense ? `<span class="chip">${esc(x.tense)}</span>` : ''}
        <span class="chip">대표 문단 ${x.passages}</span><span class="chip">지킬·피할 것 ${x.rules}</span>${[['금지 표현', x.banned], ['표지', x.markers], ['장치', x.devices]].filter(([, v]) => v).map(([k, v]) => `<span class="chip">${k} ${v}</span>`).join('')}
        ${x.sample_chars ? `<span class="chip">원문 ${x.sample_chars.toLocaleString()}자</span>` : ''}
      </div>
      ${x.notes ? `<div class="small" style="white-space:pre-line">${esc(x.notes)}</div>` : ''}
      <div class="small">${x.used_by.length ? `쓰는 작품: ${x.used_by.map((n) => `<a href="#/p/${enc(n)}/style">${esc(n)}</a>`).join(', ')}` : '아직 쓰는 작품이 없어요'}</div>
      <div class="row"><a class="btn small" href="#/styles/${esc(x.id)}">열기</a><button class="btn small" data-action="libDuplicate" data-arg="${esc(x.id)}">복제</button><button class="btn small danger" data-action="libDelete" data-arg="${esc(x.id)}">삭제</button></div>
    </article>`).join('');
  // 비었을 때는 빈 카드의 버튼 하나만 주 버튼으로 둔다
  return `${header('Canon', '문체 라이브러리', '붙여 넣은 원문에서 뽑은 문체를 작품과 따로 모아 둬요. 작품에 적용하면 그 시점의 문체가 작품에 복사되고, 라이브러리를 고쳐도 쓰고 있는 작품은 다시 적용하기 전까지 그대로예요.', `${libBackBtn()}<a class="btn" href="#/">작품 목록</a>${list.length ? '<a class="btn primary" href="#/styles/new">+ 새 문체</a>' : ''}`)}
    ${list.length ? `<div class="grid-auto">${cards}</div>` : `<div class="card empty"><div>아직 저장한 문체가 없어요.</div><div class="small">새 문체를 만들거나, 작품의 문체 레퍼런스 화면에서 '이 문체를 라이브러리에 새로 저장'을 누르세요.</div><a class="btn primary" href="#/styles/new">+ 새 문체</a></div>`}`;
}

/** 기준 지표 표. 지표마다 무엇을 쟀는지 한 줄 풀이를 붙인다 (metrics.measure 의 계산과 같게 쓴다).
    when 은 비었을 때 언제 재는지: 작품은 '문체 분석을 하면', 라이브러리는 원문을 넣고 저장할 때 잰다 (library.create · update). */
function baselineRows(b, when = '문체 분석을 하면') {
  if (!b) return `<div class="small">${when} 문장 길이, 대사 비율 같은 기준 지표를 재요. 본문을 쓴 뒤 문체가 얼마나 벗어났는지 비교하는 기준이 돼요.</div>`;
  return `<dl class="metric-list">${baselineItems(b, true).map(([k, v, why]) => `<dt title="${esc(why)}">${k}</dt><dd>${v}<span class="small" style="display:block;font-weight:400">${esc(why)}</span></dd>`).join('')}</dl>`;
}

/** 기준 지표 [이름, 값, 풀이]. long 이면 표의 긴 이름, 아니면 띠 칩의 짧은 이름. */
function baselineItems(b, long = false) {
  const pct = (v) => (v == null ? '–' : `${Math.round(v * 100)}%`);
  const rows = [
    ['문장 평균 길이', `${b.sentence_len_mean.toFixed(1)}자`, '문장 하나의 평균 글자 수예요. 띄어쓰기도 세요.'],
    ['문장 길이 변화폭', b.sentence_len_cv.toFixed(2), '문장 길이의 표준편차를 평균으로 나눈 값이에요. 0에 가까울수록 문장 길이가 고르고 리듬이 단조로워요. 클수록 짧은 문장과 긴 문장이 많이 섞여요.'],
    ['문단 평균 길이', `${Math.round(b.paragraph_len_mean)}자`, '빈 줄로 나뉜 문단 하나의 평균 글자 수예요.'],
    ['대사 비율', pct(b.dialogue_ratio), '전체 글자 중 따옴표("…", “…”, 「…」, 『…』) 안 글자의 비율이에요.'],
    ['과거형 비율', pct(b.past_tense_ratio), "'~다'로 끝나는 서술 문장 중 '~했다', '~었다'처럼 과거형으로 끝나는 비율이에요. 그런 문장이 없으면 –로 보여요."],
    ['어휘 다양도', b.mattr == null ? '–' : b.mattr.toFixed(2), '어절 100개씩 창을 옮기며 잰 서로 다른 어절의 비율이에요(0~1). 높을수록 같은 말을 덜 되풀이해요. 100어절보다 짧으면 재지 않아요.'],
    ['쉼표 문장 비율', pct(b.comma_sentence_ratio), '대사를 뺀 서술 문장 중 쉼표가 들어간 문장의 비율이에요. AI가 쓴 한국어 글은 사람 글보다 높은 편이에요.'],
  ];
  const short = ['문장 평균', '길이 변화폭', '문단 평균', '대사', '과거형', '어휘 다양도', '쉼표 문장'];
  return long ? rows : rows.map(([, v, why], i) => [short[i], v, why]);
}

function viewLibEntry() {
  const e = S.lib;
  const isNew = !e.id;
  const used = e.used_by || [];
  const others = (S.projects || []).filter((x) => !used.includes(x.name));
  const right = `${libBackBtn()}<a class="btn" href="#/styles">목록으로</a>${isNew ? '' : `<button class="btn" data-action="libDuplicate" data-arg="${esc(e.id)}">복제</button><button class="btn danger" data-action="libDelete" data-arg="${esc(e.id)}">삭제</button><button class="btn" data-action="libRevert"${S.libDirty ? '' : ' disabled'}>저장 전으로</button>`}<button class="btn primary" data-action="libSave">저장</button>`;
  const prof = e.profile;
  const rows = [['info', '이름 · 출처', '', ''], ['source', '원문 · 기준 지표', e.sample ? `${e.sample.length.toLocaleString()}자` : '', ''],
    ['-', '스타일 프로필', '', ''], ...STYLE_CARDS.map(([id, label]) => [id, label, styleCount(id, prof), '']),
    ...(isNew ? [] : [['-', '쓰임', '', ''], ['apply', '작품에 적용', String(used.length), ''], ['versions', '버전', String((S.libVersions || []).length), '']])];
  const b = e.baseline;
  const apply = isNew ? '' : `<section class="card tight pf-sec" id="pf-apply" tabindex="-1">
      <h2>작품에 적용</h2>
      <div class="small">${used.length ? `쓰는 작품: ${used.map((n) => `<a href="#/p/${enc(n)}/style">${esc(n)}</a>`).join(', ')}` : '아직 쓰는 작품이 없어요.'}</div>
      ${used.length ? '<div class="small">여기서 고친 내용은 작품의 문체 화면에서 \'최신 버전 가져오기\'를 눌러야 그 작품에 들어가요.</div>' : ''}
      ${(S.projects || []).length ? `<div class="row" style="flex-wrap:nowrap"><select id="lib-target" aria-label="적용할 작품" style="flex:1;min-width:0"><option value="">작품 고르기</option>${[...others, ...(S.projects || []).filter((x) => used.includes(x.name))].map((x) => `<option value="${esc(x.name)}">${esc(x.title || x.name)}${used.includes(x.name) ? ' (다시 적용)' : ''}</option>`).join('')}</select><button class="btn small" style="flex:none" data-action="libApplyTo">적용</button></div>` : ''}
    </section>`;
  return `${header('문체 라이브러리', isNew ? '새 문체' : e.name || '이름 없음', isNew ? '원문을 붙여 넣고 분석하거나, 카드를 직접 채운 뒤 저장하세요.' : `만든 날 ${fmtDate(e.created_at)} · 고친 날 ${fmtDate(e.updated_at)}`, right)}
    <div class="outline-wrap lib-page"><div class="outline-doc">${styleToc(rows, '문체 목차')}<div class="sty-secs">
      <section class="card pf-sec" id="pf-info" tabindex="-1">
        <div class="grid-2">${input('이름', 'name', { root: 'lib', placeholder: '예: 건조한 1인칭 하드보일드' })}
          ${input('출처', 'source', { root: 'lib', hint: '작가, 작품 등 메모', placeholder: '예: 직접 쓴 단편 「등대」' })}</div>
        ${input('메모', 'notes', { root: 'lib', rows: 1, autogrow: true, placeholder: '어떤 작품에 어울리는지 등' })}
      </section>
      <section class="card pf-sec" id="pf-source" tabindex="-1">
        <div class="pf-head"><h2>원문 · 기준 지표</h2><span class="small"><span id="lib-sample-count">${(e.sample || '').length.toLocaleString()}</span>자 · 2,000자 이상 권장</span></div>
        ${input('분석할 소설 본문', 'sample', { root: 'lib', rows: 10, style: 'font-family:var(--serif);font-size:0.9375rem;line-height:1.9', hint: '이 컴퓨터의 라이브러리 폴더에만 저장돼요' })}
        <div class="sty-row">${b ? `<span class="metric-chips">${baselineItems(b).map(([k, v, why]) => `<span title="${esc(why)}">${k} <strong>${v}</strong></span>`).join('')}</span>` : '<span class="small">원문을 넣고 저장하면 문장 길이, 대사 비율 같은 기준 지표를 재요.</span>'}
          <span class="sty-acts">${b ? menuBtn('lib-metrics', '지표 풀이', () => baselineRows(b), { cls: 'btn small ghost' }) : ''}<button class="btn small" data-action="libAnalyze">문체 분석</button></span></div>
      </section>
      ${profileCards('profile', 'lib')}
      ${apply}
      ${isNew ? '' : versionsCard()}
    </div></div></div>`;
}


/** 카드 동작이 고칠 프로필: 작품 문체 또는 라이브러리 항목. 바꿨다고 표시한다 */
function styleProf(root) {
  if (root === 'lib') { S.libDirty = true; renderSavebar(); return S.lib.profile; }
  markDirty();
  return P().style;
}

/** 항목을 더하거나 지운 카드는 비어도 '고치는 중'으로 둔다 */
function styleKeepOpen(root, id) {
  S.styleOpen = { ...S.styleOpen, [pfKey(root, id)]: true };
}

/** 분석 · 적용으로 문체가 통째로 바뀌면 이 작품의 고치던 카드를 닫는다 (새 값을 읽는 모양으로 보이게) */
function styleCloseCards() {
  S.styleOpen = Object.fromEntries(Object.entries(S.styleOpen || {}).filter(([k]) => !k.startsWith(`${S.name}:`)));
}
Object.assign(actions, {
  // 문체
  /** 목차에서 카드로 간다. 좁은 칸에서 펼친 목차는 공용 목차 틀이 닫는다 */
  styleGo(id) {
    const el = document.getElementById(`pf-${id}`);
    if (!el) return;
    styleTocCur = id;
    el.scrollIntoView({ block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    el.focus({ preventScroll: true });
  },
  /** 카드 하나를 고치는 칸 ↔ 읽는 모양. 펼치면 그 카드의 첫 칸으로 간다 */
  styleEdit(arg) {
    const [root, id] = arg.split('|');
    const k = pfKey(root, id);
    const on = !(S.styleOpen || {})[k];
    S.styleOpen = { ...S.styleOpen, [k]: on };
    render();
    const sec = document.getElementById(`pf-${id}`);
    if (on) focusEl(sec && sec.querySelector('textarea, input'));
    else $(`#pf-${id} [data-action="styleEdit"]`)?.focus();
  },
  /** 빈 작품의 '직접 채우기': 빈 카드를 모두 연다 */
  styleManual() {
    S.styleManual = { ...S.styleManual, [S.name]: true };
    render();
    focusEl($('#pf-narr textarea'));
  },
  toggleStyleSample() {
    S.styleSampleOpen = !S.styleSampleOpen;
    render();
    if (S.styleSampleOpen) focusEl($('#sample'));
  },
  async analyzeStyle() {
    if (S.styleSample.trim().length < 200) { focusEl($('#sample')); return toast('예시 원문을 200자 이상 넣어 주세요', true); }  // 서버(web.analyze_style)와 같은 기준
    const has = P().style.narration_pov || P().style.sample_passages.length;
    const l = S.styleLink || {};
    const unlink = ['same', 'changed'].includes(l.state) ? `\n라이브러리 '${l.name}' 연결도 끊겨요. 라이브러리 항목은 그대로예요.` : '';
    if ((has || unlink) && !confirm(`분석 결과로 지금 스타일 프로필을 바꿀까요? 저장하기 전에는 '변경 모두 버리기'로 되돌릴 수 있어요.${unlink}`)) return;
    await run('문체를 분석하는 중… (최대 1분)', async () => {
      await saveIfDirty();
      const prof = await api('POST', `/projects/${enc(S.name)}/style`, { text: S.styleSample });
      P().style = prof;
      styleCloseCards();
      P().style_baseline = await api('POST', '/metrics', { text: S.styleSample });  // stats 가 원문 전체와 비교하도록
      P().style_id = '';  // 새로 분석한 문체는 라이브러리 항목과 연결을 끊는다
      P().style_version = 0;
      S.styleLink = { state: 'none' };  // 저장하면 서버도 같은 상태가 된다. 그 전에도 카드가 끊긴 연결을 그대로 보이지 않게
      S.dirty = true;
      toast('분석 결과를 불러왔어요. 확인하고 저장하세요.');
    });
  },
  addPassage(root) {
    styleProf(root).sample_passages.push('');
    styleKeepOpen(root, 'passages');
    render();
    focusEl($(`#pf-passages .field-row:last-child textarea`));
  },
  removePassage(arg) {
    const [root, i] = arg.split('|');
    if (!root) rememberRemoved(`대표 문단 ${Number(i) + 1}`, ['style.sample_passages']);
    styleProf(root).sample_passages.splice(Number(i), 1);
    styleKeepOpen(root, 'passages');
    render();
  },
  addMarker(root) {
    styleProf(root).markers.push({ text: '', note: '', per_1k: 0 });
    styleKeepOpen(root, 'markers');
    render();
    focusEl($('#pf-markers .mk-row:last-child input'));
  },
  removeMarker(arg) {
    const [root, i] = arg.split('|');
    if (!root) rememberRemoved('문체 표지', ['style.markers']);
    styleProf(root).markers.splice(Number(i), 1);
    styleKeepOpen(root, 'markers');
    render();
  },
  async useLibStyle(arg) {
    const id = arg || ($('#style-pick') || {}).value;
    if (!id) return toast('적용할 문체를 고르세요', true);
    const e = (S.libs || []).find((x) => x.id === id);
    const l = S.styleLink || { state: 'none' };
    const lost = l.state === 'same' ? '' : '\n지금 문체는 라이브러리에 없어서 되돌릴 수 없어요. 남겨 두려면 취소하고 \'이 문체를 라이브러리에 새로 저장\'을 먼저 누르세요.';
    if (!confirm(`'${e ? e.name : id}' 문체를 이 작품에 적용할까요? 지금 작품의 스타일 프로필은 바뀌어요.${lost}`)) return;
    await run('적용하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/style/apply`, { style_id: id });
      styleCloseCards();
      await loadStyleLink();
      toast('라이브러리 문체를 적용했어요');
    });
  },
  async keepStyle() {
    const bare = S.styleSample.trim() ? '' : '\n(이 화면에 붙여 넣은 원문이 없어 원문 없이 저장돼요)';
    const l = S.styleLink || {};
    const moved = ['same', 'changed'].includes(l.state) ? `\n이 작품은 새 항목에 연결되고, 지금 연결된 '${l.name}' 연결은 끊겨요. '${l.name}' 항목은 그대로 남아요.` : '';
    const name = prompt(`라이브러리에 저장할 문체 이름${bare}${moved}`, `${P().meta.title || S.name} 문체`);
    if (name === null) return;
    await run('라이브러리에 저장하는 중', async () => {
      await saveIfDirty();
      const r = await api('POST', `/projects/${enc(S.name)}/style/library`, { name: name.trim(), sample: S.styleSample });
      S.project = r.project;
      S.libs = await api('GET', '/styles');
      await loadStyleLink();
      toast(`라이브러리에 '${r.entry.name}' 로 저장했어요`);
    });
  },
  async pushStyle() {
    const l = S.styleLink || {};
    const users = ((S.libs || []).find((x) => x.id === l.id) || {}).used_by || [];
    const others = users.filter((n) => n !== S.name);
    const warn = (others.length ? `\n다른 작품(${others.join(', ')})은 다시 적용하기 전까지 바뀌지 않아요.` : '')
      + ((l.theirs || []).length ? `\n라이브러리 ${l.version}번 버전에서 바뀐 칸(${l.theirs.map((c) => c.label).join(', ')})은 이 작품 값으로 덮여요.` : '');
    const note = prompt(`이 작품의 문체를 라이브러리 '${l.name}' 의 새 버전으로 올려요. 예전 버전은 남아 있어 되돌릴 수 있어요.${warn}\n\n버전 메모 (비워도 돼요)`, '');
    if (note === null) return;
    await run('라이브러리에 올리는 중', async () => {
      await saveIfDirty();
      const r = await api('POST', `/projects/${enc(S.name)}/style/library`, { update: true, note: note.trim() });
      S.project = r.project;
      S.libs = await api('GET', '/styles');
      await loadStyleLink();
      toast(`라이브러리 '${r.entry.name}' 을 ${r.entry.version}번 버전으로 올렸어요`);
    });
  },
  async pullStyle() {
    const l = S.styleLink || {};
    const lost = (l.mine || []).length || !l.base_known ? ' 작품에서 고친 내용은 사라져요.' : '';
    if (!confirm(`이 작품의 문체를 라이브러리 '${l.name}' ${l.version}번 버전으로 바꿀까요?${lost}`)) return;
    await run('적용하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/style/apply`, { style_id: l.id });
      styleCloseCards();
      await loadStyleLink();
      toast(`라이브러리 '${l.name}' ${l.version}번 버전을 가져왔어요`);
    });
  },

  // 문체 라이브러리
  async libAnalyze() {
    if ((S.lib.sample || '').trim().length < 200) return toast('원문을 200자 이상 넣어 주세요', true);
    const has = S.lib.profile.narration_pov || S.lib.profile.sample_passages.length;
    if (has && !confirm('분석 결과로 지금 프로필을 바꿀까요? 저장 전까지는 되돌릴 수 있어요.')) return;
    await run('문체를 분석하는 중… (최대 1분)', async () => {
      S.lib.profile = await api('POST', '/styles/analyze', { text: S.lib.sample });
      S.libDirty = true;
      toast('분석 결과를 불러왔어요. 확인하고 저장하세요.');
    });
  },
  async libSave() {
    if (!S.lib.name.trim()) return toast('문체 이름을 입력하세요', true);
    const body = { name: S.lib.name, source: S.lib.source, notes: S.lib.notes, sample: S.lib.sample, profile: S.lib.profile, note: S.libNote || '' };
    await run('저장 중', async () => {
      const isNew = !S.lib.id;
      S.lib = isNew ? await api('POST', '/styles', body) : await api('PUT', `/styles/${S.lib.id}`, body);
      S.lib.used_by = S.lib.used_by || [];
      S.libDirty = false;
      S.libNote = '';
      await libVersionsLoad();
      toast(isNew ? '라이브러리에 저장했어요' : `저장했어요 (지금 ${S.lib.version}번 버전)`);
      if (isNew) location.hash = `#/styles/${S.lib.id}`;
    });
  },
  async libRevert() {
    if (!S.libDirty) return;
    if (!confirm(S.lib.id ? '저장하지 않은 변경을 버리고 저장된 문체로 되돌릴까요?' : '적은 내용을 모두 지우고 빈 문체로 돌아갈까요?')) return;
    if (!S.lib.id) {  // 아직 저장하지 않은 새 문체: 돌아갈 저장본이 없다
      S.lib = { name: '', source: '', notes: '', sample: '', profile: emptyProfile(), used_by: [] };
      S.libDirty = false;
      render();
      return;
    }
    await run('불러오는 중', async () => {
      S.lib = await api('GET', `/styles/${S.lib.id}`);
      S.libDirty = false;
    });
  },
  async libDuplicate(id) {
    if (S.libDirty && !confirm('저장하지 않은 변경이 있어요. 저장한 뒤 그 버전으로 복제할까요?')) return;
    if (S.libDirty) {
      await actions.libSave();
      if (S.libDirty) return;  // 저장하지 못했다 (토스트가 이유를 알린다)
    }
    await run('복제하는 중', async () => {
      const e = await api('POST', `/styles/${id}/duplicate`);
      S.libDirty = false;
      toast(`'${e.name}' 을 만들었어요. 구별하기 쉽게 이름을 바꿔 보세요`);
      location.hash = `#/styles/${e.id}`;
      // 새 항목 화면이 그려지면 이름 칸을 골라 둔다 (화면 이동은 제목으로 포커스를 옮기므로 그 뒤에)
      const until = Date.now() + 5000;
      const pick = () => {
        const el = $('#f-name');
        if (el && el.value === e.name) { el.focus(); el.select(); } else if (Date.now() < until) setTimeout(pick, 100);
      };
      setTimeout(pick, 100);
    });
  },
  async libDelete(id) {
    const e = (S.libs || []).find((x) => x.id === id) || S.lib || {};
    const used = e.used_by || [];
    const note = used.length ? `\n이 문체를 쓰는 작품(${used.join(', ')})은 복사해 둔 문체를 그대로 써요.` : '';
    if (!confirm(`'${e.name}' 문체를 라이브러리에서 지울까요? 되돌릴 수 없어요.${note}`)) return;
    await run('지우는 중', async () => {
      await api('DELETE', `/styles/${id}`);
      S.libDirty = false;
      S.libs = await api('GET', '/styles');
      toast('지웠어요');
      if (S.route[0] === 'styles' && S.route[1]) location.hash = '#/styles';
    });
  },
  async libApplyTo() {
    const name = $('#lib-target').value;
    if (!name) return toast('적용할 작품을 고르세요', true);
    if (S.libDirty) return toast('먼저 저장하세요. 저장된 문체가 작품에 복사돼요.', true);
    if (!confirm(`'${S.lib.name}' 문체를 '${name}' 작품에 적용할까요? 그 작품의 스타일 프로필은 바뀌어요.\n그 작품의 지금 문체를 라이브러리에 저장해 두지 않았다면 되돌릴 수 없어요.`)) return;
    await run('적용하는 중', async () => {
      await api('POST', `/projects/${enc(name)}/style/apply`, { style_id: S.lib.id });
      S.lib = await api('GET', `/styles/${S.lib.id}`);
      toast(`'${name}' 에 적용했어요`);
    });
  },
});

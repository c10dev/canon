/* 설계도 화면 (docs/blueprint/specs/03-journey.md). app.js 의 S, actions, api, run, render, header, esc, P, base, enc, toast, askConfirm 과
   outline.js 의 공용 목차 틀을 쓴다. 작가가 먼저 정하는 계획 층(Project.blueprint): 관계 이정표(방향마다), 접촉 사다리(쌍마다), 능력 일정(인물마다 여러 줄).
   주소는 blueprint(개요) · blueprint/<쌍 키> · blueprint/@ability(능력 일정). 쌍 키는 두 인물 id 를 정렬해 '~' 로 이은 것이다.
   카드는 읽는 모양이 기본이다. 줄 끝 ✎ 는 그 줄만, 카드 머리 '고치기'는 그 카드 전체를 편다. 저장은 설계도 전체를 PUT …/blueprint 로 보낸다(서버가 blueprint.check 로 검사).
   줄 지우기 · AI 제안 더하기 · 여정 비우기는 바로 저장하고 되돌리기(S.bpUndo)를 남긴다.
   AI 제안은 쌍 쪽이 S.bpDraft(하나), 능력 일정 쪽이 S.bpAbDrafts(인물 · 뽑기/짜기마다 하나), 개요의 작품 전체 짜기가 S.bpWhole(하나)이다. 둘 다 app.js 의 PER_PROJECT 가 작품마다 따로 둔다.
   경고는 서버가 계산한다(blueprint.warning_rows). 막지 않는다.
   개요의 전체 띠는 서버가 고른 처음 닿는 줄(blueprint.firsts)만 쌍마다 한 줄에 그린다. 쌍끼리 몰림은 테두리로만 보인다(docs/blueprint/specs/11-whole.md). */
'use strict';

Object.assign(S, {
  bp: null,        // 서버 값 { blueprint, warnings: [{source, target, text}], firsts: [{pair, axis, value, from_ep, to_ep, id, source, target, crowd}], plans: [{id, got, state, linked}], ability_warnings: [{character, text}], parts: [{id, label}], acts, last }
  bpSel: '',       // 지금 쪽: '' 개요 | 쌍 키 | '@ability' 능력 일정
  bpEdit: null,    // 고치는 카드 { card: 'ms' | 'ladder' | 'note' | 'ap', key, data: Blueprint 사본, orig, row: 누른 줄만 열면 그 줄의 길('milestones.3') }
  bpUndo: null,    // 방금 한 지우기 · 더하기 · 비우기 { name, key, before, after: 설계도 JSON, msg, abIds: 같이 만든 도감 항목 id }. 되돌리기는 지금 값이 after 일 때만 before 를 다시 저장하고 abIds 를 지운다
  bpAbMade: null,  // 능력 일정 제안을 더하며 막 만든 도감 항목 id (bpWrite 가 bpUndo.abIds 로 옮기고 비운다)
  bpOwner: '',     // 화면 상태를 가진 작품
  bpPickOpen: '',  // 펴 둔 칩 묶음의 길 (칩을 눌러 다시 그려도 펴 둔다)
  bpWide: false,   // 계획 띠를 작품 전체 화수로 (기본은 기획한 화까지)
  bpWholeOpen: false,  // 개요 '관계' 카드의 'AI로 전체 짜기' 칸을 폈는가
});

const BP_LAYERS = ['', '옷 위', '옷 안', '맨살'];
const BP_STAGES = ['', '낯섦', '경계', '호감', '신뢰', '균열', '적대', '화해'];  // schema.RelStage (tests/test_blueprint_js.py)
const bpWho = (id) => (P().characters.find((c) => c.id === id) || {}).name || id;
const bpKey = (a, b) => [a, b].sort().join('~');
const bpPair = (key) => String(key).split('~');
const bpHref = (k) => `${base()}/blueprint${k ? `/${enc(k)}` : ''}`;
const bpRange = (x) => (x.from_ep > 0 ? (x.from_ep === x.to_ep ? `${x.from_ep}화` : `${x.from_ep}~${x.to_ep}화`) : '화 정하지 않음');
const bpEmpty = () => ({ milestones: [], ladders: [], ability_plans: [], note: '' });
const BP_AB = '@ability';  // 능력 일정 쪽의 주소 키. 쌍 키('a~b')와 겹치지 않는다
const bpPlans = (bp) => bp.ability_plans || [];
const bpAbWarns = () => S.bp.ability_warnings || [];
const bpAbText = (x) => `${x.ability} ${x.grade || ''}`.trim();

/** 쌍 목록: 관계 설정의 쌍 + 설계도에만 있는 쌍. [[키, a, b]] (관계 차례, 그 뒤 설계도 차례). a · b 는 관계 설정의 차례 */
function bpPairs(p, bp) {
  const out = [];
  const add = (a, b) => { if (a && b && a !== b && !out.some((x) => x[0] === bpKey(a, b))) out.push([bpKey(a, b), a, b]); };
  (p.relationships || []).forEach((r) => add(r.a, r.b));
  (bp.milestones || []).forEach((m) => add(m.source, m.target));
  (bp.ladders || []).forEach((l) => add(l.a, l.b));
  return out;
}

/** 쌍의 이정표 · 사다리 · 경고 */
function bpOfPair(bp, warns, a, b) {
  const inPair = (s, t) => (s === a && t === b) || (s === b && t === a);
  return {
    ms: (bp.milestones || []).filter((m) => inPair(m.source, m.target)),
    ladder: (bp.ladders || []).find((l) => inPair(l.a, l.b)) || null,
    warns: (warns || []).filter((w) => inPair(w.source, w.target)),
  };
}

async function bpLoad(sel) {
  if (S.bpOwner && S.bpOwner !== S.name) S.bpEdit = S.bpUndo = null;  // 다른 작품으로 가면 고치던 칸과 되돌리기를 닫는다
  S.bpOwner = S.name;
  const prev = S.bpSel;
  S.bpSel = sel || '';
  S.bp = await api('GET', `/projects/${enc(S.name)}/blueprint`).catch((e) => ({ error: e.message, blueprint: bpEmpty(), warnings: [], firsts: [], plans: [], ability_warnings: [], parts: [], acts: [], last: 0 }));
  if (S.bpEdit && S.bpEdit.key !== S.bpSel) S.bpEdit = null;
  if (prev !== S.bpSel && !S.focusTarget) S.focusTarget = '#app main h1';
}

// ----- 목차 -----

function bpToc() {
  const d = S.bp;
  const pairs = bpPairs(P(), d.blueprint);
  const item = (k, inner, warn = false) => `<a class="outline-item${warn ? ' warn' : ''}" href="${bpHref(k)}"${S.bpSel === k ? ' aria-current="page"' : ''}>${inner}</a>`;
  const warned = d.warnings.length + bpAbWarns().length;
  const rows = [item('', `<span class="tl">개요</span><span class="st">${warned ? `경고 ${warned}` : ''}</span>`, warned > 0)];
  if (pairs.length) rows.push('<div class="outline-h">관계</div>');
  pairs.forEach(([k, a, b]) => {
    const x = bpOfPair(d.blueprint, d.warnings, a, b);
    const n = x.ms.length + (x.ladder ? x.ladder.rungs.length : 0);
    rows.push(item(k, `<span class="tl">${esc(bpWho(a))} ↔ ${esc(bpWho(b))}</span><span class="st">${x.warns.length ? `경고 ${x.warns.length}` : n ? `${n}줄` : '비어 있음'}</span>`, x.warns.length > 0));
  });
  const plans = bpPlans(d.blueprint).length;
  rows.push('<div class="outline-h">성장</div>');
  rows.push(item(BP_AB, `<span class="tl">능력 일정</span><span class="st">${bpAbWarns().length ? `경고 ${bpAbWarns().length}` : plans ? `${plans}줄` : '비어 있음'}</span>`, bpAbWarns().length > 0));
  const cur = pairs.find(([k]) => k === S.bpSel);
  const now = cur ? `${esc(bpWho(cur[1]))} ↔ ${esc(bpWho(cur[2]))}` : S.bpSel === BP_AB ? '능력 일정' : '개요';
  return outlineNav({ id: 'bp-toc', label: '설계도 목차', now, body: `<div class="outline-list">${rows.join('')}</div>` });
}

// ----- 계획 띠 -----

/** 화 범위 막대들 한 줄. items: [{from_ep, to_ep, text, cls, tip}]. tip 은 막대에 다 못 쓰는 말(없으면 text)을 끌어올림 글로 */
function bpLane(label, items, total) {
  const bars = items.filter((x) => x.from_ep > 0).map((x) => {
    const left = ((x.from_ep - 1) / total) * 100;
    const width = Math.max(((x.to_ep - x.from_ep + 1) / total) * 100, 0.6);
    return `<span class="bp-bar${x.cls ? ` ${x.cls}` : ''}" style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%" title="${esc(`${bpRange(x)} · ${x.tip || x.text}`)}"><span class="bp-bar-t">${esc(x.text)}</span></span>`;
  }).join('');
  return `<div class="bp-lane"><span class="bp-lane-h">${esc(label)}</span><div class="bp-track">${bars}</div></div>`;
}

/** 계획 띠가 기본으로 보이는 화 수: 기획한 화와 이 쌍 설계도의 끝 화 가운데 큰 것 */
function bpSpan(p, x) {
  return bpPlannedSpan([...x.ms.map((m) => m.to_ep), ...(x.ladder ? x.ladder.rungs.map((r) => r.to_ep) : [])]);
}

/** 쌍의 계획 띠: 두 방향 이정표, 접촉 사다리. 아크(장편) · 구간(단편) 경계와 마지막 반영 화를 겹친다 */
function bpBand(a, b, x) {
  const f = bpBandFrame(bpSpan(P(), x));
  const total = f.total;
  const dir = (s, t) => x.ms.filter((m) => m.source === s && m.target === t).map((m) => ({ ...m, text: m.stage || m.label || '이정표', cls: 'bp-is-ms' }));
  const rungs = x.ladder ? x.ladder.rungs.map((r, i) => ({ ...r, text: `${i + 1}. ${r.label || '칸'}`, cls: 'bp-is-rung' })) : [];
  const got = x.ladder ? bpReached(x.ladder) : {};
  const hits = x.ladder ? x.ladder.rungs.map((r, i) => [r, i]).filter(([r]) => r.id in got).map(([r, i]) => ({ from_ep: got[r.id], to_ep: got[r.id], text: `${i + 1}`, cls: 'bp-is-hit' })) : [];
  const desc = `1~${total}화 계획 띠: ${bpWho(a)} → ${bpWho(b)} 이정표 ${dir(a, b).length}개, ${bpWho(b)} → ${bpWho(a)} 이정표 ${dir(b, a).length}개, 접촉 사다리 ${rungs.length}칸`;
  const clear = x.ms.length || rungs.length ? `<button type="button" class="btn small ghost danger" data-action="bpClear" data-arg="${esc(bpKey(a, b))}">여정 비우기</button>` : '';
  return `<section class="card" id="bp-band"><div class="between"><h2>계획 띠</h2><div class="row">${f.seg}${f.range}${clear}</div></div>
    <div class="bp-band" role="img" aria-label="${esc(desc)}">${f.ticks}${f.last}
      ${bpLane(`${bpWho(a)} → ${bpWho(b)}`, dir(a, b), total)}${bpLane(`${bpWho(b)} → ${bpWho(a)}`, dir(b, a), total)}${bpLane('접촉 사다리', rungs, total)}${hits.length ? bpLane('본문에서 닿음', hits, total) : ''}</div></section>`;
}

// ----- 카드 -----

function bpCardHead(title, card) {
  const open = S.bpEdit && S.bpEdit.card === card;
  return `<div class="pf-head"><h2>${title}${open ? ' <span class="small pf-state">고치는 중</span>' : ''}</h2>${open ? '' : `<button type="button" class="btn small" data-action="bpEditOpen" data-arg="${card}" aria-expanded="false">고치기</button>`}</div>`;
}

function bpSaveRow() {
  return '<div class="row ab-save"><button type="button" class="btn small ghost" data-action="bpCancel">취소</button><button type="button" class="btn small primary" data-action="bpSave">저장</button></div>';
}

function bpNum(path, v, label) {
  return `<input type="number" min="0" inputmode="numeric" class="bp-num" data-bp="${path}" value="${v || ''}" placeholder="화" aria-label="${esc(label)}">`;
}

/** 여러 줄 글 칸 (라벨 · 계기 · 조건 · 메모). AI 가 쓴 긴 문장도 잘리지 않게 줄을 바꿔 보인다 */
function bpText(path, v, label, placeholder = '') {
  return `<textarea class="bp-text" rows="2" data-bp="${path}" placeholder="${esc(placeholder)}" aria-label="${esc(label)}">${esc(v || '')}</textarea>`;
}

/** 화 차례 (보는 화면 · 고치는 목록이 같게): 처음 화, 정하지 않은 줄은 뒤. [[줄, 차례]] 를 받는다 */
const bpByEp = (rows) => rows.sort(([p], [q]) => (p.from_ep || 1e9) - (q.from_ep || 1e9) || (p.to_ep || 1e9) - (q.to_ep || 1e9));

/** 줄 끝의 고치기 · 지우기 (보는 화면). path 는 설계도 안 길 'milestones.3' · 'ladders.0.rungs.2' · 'ability_plans.1' */
function bpRowActs(path, what) {
  if (S.bpEdit && S.bpEdit.row && S.bpEdit.row.split('.')[0] === path.split('.')[0]) return '';  // 같은 카드에서 한 줄을 고치는 동안은 숨긴다 (칸 차례를 옮겼을 수 있다)
  return `<span class="bp-row-acts"><button type="button" class="btn icon-btn ghost" data-action="bpRowEdit" data-arg="${path}" aria-label="${esc(`${what} 고치기`)}" title="고치기">✎</button>
    <button type="button" class="btn icon-btn ghost" data-action="bpRowDel" data-arg="${path}" aria-label="${esc(`${what} 지우기`)}" title="지우기">✕</button></span>`;
}

/** 고치는 카드의 모양: '' 읽기 | 'row' 누른 줄만 | 'card' 카드 전체 */
const bpMode = (card) => (S.bpEdit && S.bpEdit.card === card ? (S.bpEdit.row ? 'row' : 'card') : '');

/** 이정표 한 줄의 고치는 칸 */
function bpMsEdit(m, i) {
  const stage = BP_STAGES.map((w) => `<option value="${w}"${w === m.stage ? ' selected' : ''}>${w || '단계 없음'}</option>`).join('');
  return `<div class="bp-ms-row">${bpNum(`milestones.${i}.from_ep`, m.from_ep, '처음 화')}<span aria-hidden="true">~</span>${bpNum(`milestones.${i}.to_ep`, m.to_ep, '끝 화')}
    <select data-bp="milestones.${i}.stage" aria-label="관계 단계">${stage}</select>
    ${S.bpEdit.row ? '' : `<button type="button" class="btn icon-btn ghost bp-del" data-action="bpMsDel" data-arg="${i}" aria-label="이정표 지우기">✕</button>`}
    ${bpText(`milestones.${i}.label`, m.label, '라벨', '라벨 (예: 처음으로 먼저 손을 잡는다)')}
    ${bpText(`milestones.${i}.trigger`, m.trigger, '계기', '계기')}</div>`;
}

/** 관계 이정표 카드 (두 방향). 줄은 화 차례로 보인다(고치는 목록도 같다) */
function bpMsCard(a, b, x) {
  const mode = bpMode('ms');
  const dirs = [[a, b], [b, a]];
  const src = mode ? S.bpEdit.data : S.bp.blueprint;
  const mine = (s, t) => bpByEp(src.milestones.map((m, i) => [m, i]).filter(([m]) => m.source === s && m.target === t));
  let body;
  if (mode === 'card') {
    body = dirs.map(([s, t]) => `<div class="bp-dir"><h3>${esc(bpWho(s))} → ${esc(bpWho(t))}</h3>${mine(s, t).map(([m, i]) => bpMsEdit(m, i)).join('')}
        <button type="button" class="btn small" data-action="bpMsAdd" data-arg="${esc(`${s}|${t}`)}">+ 이정표 더하기</button></div>`).join('') + bpSaveRow();
  } else {
    body = dirs.map(([s, t]) => {
      const rows = mine(s, t).map(([m, i]) => (mode === 'row' && S.bpEdit.row === `milestones.${i}`
        ? `<li class="bp-row-edit">${bpMsEdit(m, i)}${bpSaveRow()}</li>`
        : `<li><span class="chip">${esc(bpRange(m))}</span>${m.stage ? `<span class="chip confirmed">${esc(m.stage)}</span>` : ''}<span class="bp-row-t">${esc(m.label)}${m.trigger ? ` <span class="small">계기: ${esc(m.trigger)}</span>` : ''}</span>${bpRowActs(`milestones.${i}`, `${bpRange(m)} 이정표`)}</li>`)).join('');
      return `<div class="bp-dir"><h3>${esc(bpWho(s))} → ${esc(bpWho(t))}</h3>${rows ? `<ul class="bp-list">${rows}</ul>` : '<span class="small">이정표가 없어요</span>'}</div>`;
    }).join('');
  }
  return `<section class="card pf-sec${mode ? ' editing' : ''}" id="bp-ms" tabindex="-1">${bpCardHead('관계 이정표', 'ms')}${body}</section>`;
}

/** 칩 고르기 묶음 (부위 · 동작 · 장소). 접어 두고 고른 수를 보인다 */
function bpChips(path, picks, chosen, label) {
  const chips = picks.map((x) => `<button type="button" aria-pressed="${chosen.includes(x.id)}" data-action="bpToggle" data-arg="${esc(`${path}|${x.id}`)}">${esc(x.label)}</button>`).join('');
  const names = picks.filter((x) => chosen.includes(x.id)).map((x) => x.label);
  return `<details class="bp-pick"${S.bpPickOpen === path ? ' open' : ''} data-bp-pick="${esc(path)}"><summary>${esc(label)} <span class="small">${names.length ? esc(names.join(', ')) : '고르지 않음'}</span></summary>
    <div class="genre-opts" role="group" aria-label="${esc(label)}">${chips || '<span class="small">고를 것이 없어요</span>'}</div></details>`;
}

const bpPlaces = () => (P().elements || []).filter((el) => el.kind === '장소').map((el) => ({ id: el.id, label: el.name }));

/** 접촉 사다리 카드 (쌍마다 하나, 칸 차례가 단계 차례) */
function bpLadderCard(a, b, x) {
  const mode = bpMode('ladder');
  const label = (ids, picks) => ids.map((id) => (picks.find((p) => p.id === id) || { label: id }).label).join(', ');
  const src = mode ? S.bpEdit.data : S.bp.blueprint;
  const li = src.ladders.findIndex((l) => bpKey(l.a, l.b) === bpKey(a, b));
  const rungs = li >= 0 ? src.ladders[li].rungs : [];
  const edit = (r, i) => {
    const at = `ladders.${li}.rungs.${i}`;
    const lead = ['', a, b].map((id) => `<option value="${esc(id)}"${id === r.lead ? ' selected' : ''}>${id ? esc(bpWho(id)) : '주도 정하지 않음'}</option>`).join('');
    const layer = `<div class="seg" role="group" aria-label="겹">${BP_LAYERS.map((w) => `<button type="button" data-action="bpLayer" data-arg="${esc(`${at}|${w}`)}" aria-pressed="${r.layer === w}">${w || '정하지 않음'}</button>`).join('')}</div>`;
    return `<div class="bp-rung"><div class="bp-rung-top"><strong>${i + 1}</strong>
        ${bpText(`${at}.label`, r.label, `${i + 1}번째 칸 이름`, '칸 이름')}
        ${bpNum(`${at}.from_ep`, r.from_ep, `${i + 1}번째 칸 처음 닿는 화`)}<span aria-hidden="true">~</span>${bpNum(`${at}.to_ep`, r.to_ep, `${i + 1}번째 칸 끝 화`)}
        <button type="button" class="btn icon-btn ghost" data-action="bpRungMove" data-arg="${i}|-1" aria-label="${i + 1}번째 칸 위로"${i ? '' : ' disabled'}>↑</button>
        <button type="button" class="btn icon-btn ghost" data-action="bpRungMove" data-arg="${i}|1" aria-label="${i + 1}번째 칸 아래로"${i < rungs.length - 1 ? '' : ' disabled'}>↓</button>
        ${mode === 'row' ? '' : `<button type="button" class="btn icon-btn ghost" data-action="bpRungDel" data-arg="${i}" aria-label="${i + 1}번째 칸 지우기">✕</button>`}</div>
      <div class="row">${layer}<select data-bp="${at}.lead" aria-label="주도하는 인물">${lead}</select></div>
      ${bpChips(`${at}.parts`, S.bp.parts, r.parts, '부위')}${bpChips(`${at}.acts`, S.bp.acts, r.acts, '동작')}${bpChips(`${at}.places`, bpPlaces(), r.places, '장소')}
      ${bpText(`${at}.note`, r.note, `${i + 1}번째 칸 메모`, '메모')}</div>`;
  };
  let body;
  if (mode === 'card') {
    body = rungs.map(edit).join('') + `<div class="between"><button type="button" class="btn small" data-action="bpRungAdd">+ 칸 더하기</button>${bpSaveRow()}</div>`;
  } else if (rungs.length) {
    const got = bpReached(src.ladders[li]);
    body = `<ol class="bp-list">${rungs.map((r, i) => (mode === 'row' && S.bpEdit.row === `ladders.${li}.rungs.${i}`
      ? `<li class="bp-row-edit">${edit(r, i)}${bpSaveRow()}</li>`
      : `<li><span class="chip">${esc(bpRange(r))}</span><span class="bp-row-t"><strong>${esc(r.label || '이름 없는 칸')}</strong>
        ${r.id in got ? `<span class="chip finalized">${got[r.id]}화에 닿음</span>` : ''}
        <span class="small">${esc([r.layer, label(r.parts, S.bp.parts), label(r.acts, S.bp.acts), label(r.places, bpPlaces()), r.lead ? `${bpWho(r.lead)} 주도` : '', r.note].filter(Boolean).join(' · '))}</span></span>${bpRowActs(`ladders.${li}.rungs.${i}`, `${i + 1}번째 칸`)}</li>`)).join('')}</ol>`;
  } else body = '<span class="small">칸이 없어요. 낮은 칸부터 차례로 더해요.</span>';
  return `<section class="card pf-sec${mode ? ' editing' : ''}" id="bp-ladder" tabindex="-1">${bpCardHead('접촉 사다리', 'ladder')}${body}</section>`;
}

/** 본문에서 닿은 칸 id → 처음 닿은 화 (blueprint.reached 와 같다, Project.contact_log) */
function bpReached(lad) {
  const ids = new Set(lad.rungs.map((r) => r.id));
  const out = {};
  (P().contact_log || []).forEach((x) => {
    if (ids.has(x.rung) && [x.a, x.b].sort().join('~') === bpKey(lad.a, lad.b)) out[x.rung] = Math.min(out[x.rung] || x.episode, x.episode);
  });
  return out;
}

/** 사다리 칸 찾기: 칸 id → [사다리, 칸, 차례] */
function bpRungOf(id) {
  for (const lad of ((P().blueprint || {}).ladders || [])) {
    const i = lad.rungs.findIndex((r) => r.id === id);
    if (i >= 0) return [lad, lad.rungs[i], i];
  }
  return [null, null, -1];
}

const bpRungLabel = (id) => {
  const [, r, i] = bpRungOf(id);
  return r ? `${i + 1}. ${r.label || '이름 없는 칸'}` : `지워진 칸 ${id}`;
};

/** 자동 집필이 남겨 둔 닿은 칸 제안 (Project.contact_held). 하나씩 기록하거나 버린다 */
function bpHeldCard() {
  const held = P().contact_held || [];
  if (!held.length) return '';
  const rows = held.map((x, i) => `<li><span class="chip">${x.episode}화</span><strong>${esc(bpWho(x.a))} ↔ ${esc(bpWho(x.b))}</strong><span>${esc(bpRungLabel(x.rung))}</span>
      ${x.quote ? `<span class="small">「${esc(x.quote)}」</span>` : ''}
      <span class="row"><button type="button" class="btn small ghost" data-action="bpHeld" data-arg="${i}|drop">버리기</button><button type="button" class="btn small" data-action="bpHeld" data-arg="${i}|take">기록하기</button></span></li>`).join('');
  return `<section class="card" id="bp-held"><h2>남겨 둔 닿은 칸 <span class="small">${held.length}</span></h2>
    <span class="small">자동 집필이 반영하지 않고 남겨 둔 제안이에요.</span><ul class="bp-list">${rows}</ul></section>`;
}

/** 상태 승인 화면의 '직접 정할 것' 줄 (review.js 가 부른다): 이번 화 본문에서 처음 닿은 사다리 칸. 기본으로 고르지 않는다 */
function contactDeltaRows(n, d, box) {
  return (d.contacts || []).map((x, i) => {
    const who = `${charName(x.a)} ↔ ${charName(x.b)}`;
    return `<div class="change">${box('u' + i)}<div class="body"><div class="rv-row-head"><label for="pk-u${i}" class="rv-name">${esc(who)}</label><span class="chip">설계도 칸</span><span class="small">기본으로 고르지 않았어요</span>${x.quote && typeof rvQuoteBtn === 'function' ? rvQuoteBtn(n, x.quote, `${who} 닿은 칸`) : ''}</div>
      <div>${esc(bpRungLabel(x.rung))}</div>${x.quote ? `<div class="rv-quote">${typeof quoted === 'function' ? quoted(x.quote) : esc(x.quote)}</div>` : ''}</div></div>`;
  }).join('');
}

function bpWarnCard(warns) {
  if (!warns.length) return '';
  return `<section class="card" id="bp-warn"><h2>경고 <span class="small">${warns.length}</span></h2><ul class="bp-list">${warns.map((w) => `<li class="note warn">${esc(w.text)}</li>`).join('')}</ul></section>`;
}

function bpNoteCard() {
  const open = S.bpEdit && S.bpEdit.card === 'note';
  const note = S.bp.blueprint.note;
  const body = open ? `<textarea id="bp-note" data-bp="note" rows="2" aria-label="설계 원칙">${esc(S.bpEdit.data.note)}</textarea>${bpSaveRow()}`
    : note ? `<p>${esc(note)}</p>` : '<span class="small">비어 있음</span>';
  return `<section class="card pf-sec${open ? ' editing' : ''}" id="bp-note-card" tabindex="-1">${bpCardHead('설계 원칙', 'note')}${body}</section>`;
}

function bpOverview() {
  const d = S.bp;
  const pairs = bpPairs(P(), d.blueprint);
  const plans = bpPlans(d.blueprint);
  const growth = `<section class="card" id="bp-growth"><h2>성장</h2><ul class="bp-list"><li><a href="${bpHref(BP_AB)}"><strong>능력 일정</strong></a>
    <span class="small">${plans.length}줄${bpAbWarns().length ? ` · 경고 ${bpAbWarns().length}` : ''}</span></li></ul></section>`;
  if (!pairs.length) return `<section class="card csh-empty"><div class="empty"><p>관계가 아직 없어요. 설정에서 관계를 더하면 그 두 인물의 여정을 여기서 짜요.</p></div></section>${bpWarnCard(bpAbWarns())}${growth}`;
  const rungs = d.blueprint.ladders.reduce((n, l) => n + l.rungs.length, 0);
  const warned = d.warnings.length + bpAbWarns().length;
  const tiles = `<div class="ab-tiles"><div class="ab-tile"><span class="small">관계 이정표</span><b>${d.blueprint.milestones.length}</b></div>
    <div class="ab-tile"><span class="small">사다리 칸</span><b>${rungs}</b></div>
    <div class="ab-tile"><span class="small">능력 일정</span><b>${plans.length}</b></div>
    <div class="ab-tile${warned ? ' warn' : ''}"><span class="small">경고</span><b>${warned}</b></div></div>`;
  const head = `<div class="between"><h2>관계</h2><button type="button" class="btn small" data-action="bpWholeToggle" aria-expanded="${S.bpWholeOpen}" aria-controls="bp-whole-ai">AI로 전체 짜기</button></div>`;
  const list = `<section class="card" id="bp-pairs">${head}${S.bpWholeOpen ? bpWholeAiCard(pairs) : ''}<ul class="bp-list">${pairs.map(([k, a, b]) => {
    const x = bpOfPair(d.blueprint, d.warnings, a, b);
    return `<li><a class="bp-pair" href="${bpHref(k)}">${esc(bpWho(a))} ↔ ${esc(bpWho(b))}</a><span class="small">이정표 ${x.ms.length} · 사다리 ${x.ladder ? x.ladder.rungs.length : 0}칸${x.warns.length ? ` · 경고 ${x.warns.length}` : ''}</span></li>`;
  }).join('')}</ul></section>`;
  return tiles + bpWarnCard([...d.warnings, ...bpAbWarns()]) + bpHeldCard() + bpWholeDraftCard(pairs) + bpWholeBand(pairs, d.firsts || [], plans) + bpNoteCard() + list + growth;
}

// ----- 작품 전체 짜기 (docs/blueprint/specs/11-whole.md 의 11b, 작업 blueprint_whole) -----

/** '관계' 카드 안에서 펴는 칸: 짜기 메모, 장편은 부 고르기, 쌍 체크(기본 모두), 'AI로 짜기'. 결과는 개요의 제안 카드(bpWholeDraftCard)로 온다 */
function bpWholeAiCard(pairs) {
  const parts = serial() ? P().parts || [] : [];
  const partPick = parts.length ? `<select id="bp-whole-part" aria-label="짤 부">${parts.map((x) => `<option value="${x.number}">${x.number}부 · ${x.start_ep}~${x.end_ep}화</option>`).join('')}</select>` : '';
  const boxes = pairs.map(([k, a, b]) => `<label class="pop-check"><input type="checkbox" class="bp-whole-pair" value="${esc(k)}" checked> ${esc(bpWho(a))} ↔ ${esc(bpWho(b))}</label>`).join('');
  return `<div class="field" id="bp-whole-ai"><label for="bp-whole-note">AI로 전체 짜기 <span class="hint">고른 쌍과 능력 일정을 함께 보고 엇갈려 짜요</span></label>
    <textarea id="bp-whole-note" rows="2" placeholder="예: 1부는 윤서 먼저, 수빈은 아크 2부터. MT에서 둘을 함께"></textarea>
    <div class="row" role="group" aria-label="짤 쌍">${boxes}</div>
    <div class="row">${partPick}<button type="button" class="btn small" data-action="bpWholeAI">AI로 짜기</button></div></div>`;
}

/** 제안의 쌍 묶음 기본 체크: 이미 있는 줄과 겹치는 줄은 고르지 않는다 (bpOverlaps, 08 의 제안 카드와 같다) */
function bpWholePicks(d) {
  if (d.pick) return d.pick;
  d.pick = {};
  d.pairs.forEach((x) => {
    const ov = bpOverlaps(S.bp.blueprint, x);
    d.pick[bpKey(x.a, x.b)] = { ms: x.milestones.map((_, i) => !ov.ms[i]), rungs: x.rungs.map((_, i) => !ov.rungs[i]) };
  });
  d.abPicks = bpAbPicks(S.bp.blueprint, d.abilities);
  d.codexPicks = (d.codex || []).map(() => true);
  return d.pick;
}

/** 작품 전체 짜기 제안 카드: 편성 · 몰림 · 맞물림 경고 · 이미 적은 줄과 제안 줄을 겹친 전체 띠 · 쌍마다 묶음 · 능력 묶음. 주 버튼은 '고른 줄 더하기' 하나 */
function bpWholeDraftCard(pairs) {
  const d = S.bpWhole;
  if (!d) return '';
  const pick = bpWholePicks(d);
  const label = (ids, picks) => ids.map((id) => (picks.find((x) => x.id === id) || { label: id }).label).join(', ');
  const box = (arg, on, text) => `<input type="checkbox" data-action="bpWholePick" data-arg="${esc(arg)}"${on ? ' checked' : ''} aria-label="${esc(text)}">`;
  const groups = d.pairs.map((x) => {
    const k = bpKey(x.a, x.b);
    const pk = pick[k];
    const ov = bpOverlaps(S.bp.blueprint, x);
    const who = `${bpWho(x.a)} ↔ ${bpWho(x.b)}`;
    const all = [...pk.ms, ...pk.rungs];
    const ms = x.milestones.map((m, i) => `<li>${box(`${k}|ms|${i}`, pk.ms[i], `${who} 이정표 ${i + 1} 고르기`)}<span class="chip">${esc(bpRange(m))}</span>
      <span>${esc(bpWho(m.source))} → ${esc(bpWho(m.target))}</span>${m.stage ? `<span class="chip confirmed">${esc(m.stage)}</span>` : ''}<span>${esc(m.label)}</span>
      ${ov.ms[i] ? '<span class="chip warn">이미 있음</span>' : ''}${(m.evidence || []).length ? `<span class="small">${esc(bpEvidence(m.evidence))}</span>` : ''}</li>`).join('');
    const rungs = x.rungs.map((r, i) => `<li>${box(`${k}|rung|${i}`, pk.rungs[i], `${who} 사다리 칸 ${i + 1} 고르기`)}<span class="chip">${esc(bpRange(r))}</span><strong>${esc(r.label)}</strong>
      <span class="small">${esc([r.layer, label(r.parts, S.bp.parts), label(r.acts, S.bp.acts), r.lead ? `${bpWho(r.lead)} 주도` : ''].filter(Boolean).join(' · '))}</span>
      ${ov.rungs[i] ? '<span class="chip warn">이미 있음</span>' : ''}</li>`).join('');
    const n = all.length;
    return `<details class="bp-pick bp-dir" open><summary><span>${esc(who)}</span><span class="small">이정표 ${x.milestones.length} · 칸 ${x.rungs.length} · 고름 ${all.filter(Boolean).length}</span></summary>
      ${n ? `<label class="small"><input type="checkbox" data-action="bpWholePick" data-arg="${esc(k)}|all"${all.every(Boolean) ? ' checked' : ''}> 이 쌍 모두 고르기</label>` : '<span class="small">새 줄이 없어요.</span>'}
      ${ms ? `<ul class="bp-list">${ms}</ul>` : ''}${rungs ? `<ul class="bp-list">${rungs}</ul>` : ''}</details>`;
  }).join('');
  const spots = (d.spotlight || []).map((sp) => `<li><span class="chip">${esc(bpRange(sp))}</span><span>${esc(sp.focus.map((c) => bpPair(c).map(bpWho).join(' ↔ ')).join(', ') || '나아가는 쌍 없음')}</span>${sp.note ? `<span class="small">${esc(sp.note)}</span>` : ''}</li>`).join('');
  const warns = [...(d.crowd || []), ...(d.mesh || [])];
  const shown = pairs.filter(([k]) => (d.picked || []).includes(k));
  const plans = [...bpPlans(S.bp.blueprint), ...d.abilities.map((x) => ({ ...x, new: true }))];
  const none = !d.pairs.some((x) => x.milestones.length || x.rungs.length) && !d.abilities.length;
  return `<section class="card" id="bp-whole-draft"><div class="between"><h2>AI가 짠 전체 설계도 <span class="small">${d.start}~${d.end}화</span></h2>
      <span class="row"><button type="button" class="btn small" data-action="bpWholeDrop">버리기</button>${none ? '' : '<button type="button" class="btn small primary" data-action="bpWholeUse">고른 줄 더하기</button>'}</span></div>
    ${d.reply ? `<p class="small">${esc(d.reply)}</p>` : ''}
    ${warns.length ? `<ul class="bp-list">${warns.map((w) => `<li class="note warn">${esc(w.text)}</li>`).join('')}</ul>` : ''}
    ${spots ? `<h3>편성</h3><ul class="bp-list">${spots}</ul>` : ''}
    ${bpWholeBand(shown, d.firsts || [], plans, 'bp-whole-draft-band', '제안을 겹친 띠')}
    ${groups}
    ${d.abilities.length ? `<div class="bp-dir"><h3>능력 일정</h3>${bpAbDraftRows(d.abilities, d.abPicks, 'whole', true, 'bpWholeAbPick')}${bpAbCodexRows(d.codex || [], d.codexPicks, 'whole', 'bpWholeCodexPick')}</div>` : ''}
    ${none ? '<span class="small">짠 줄이 없어요.</span>' : ''}</section>`;
}

// ----- 능력 일정 (docs/blueprint/specs/10-ability.md) -----

/** 일정 줄의 계획 대 실제 (서버 blueprint.ability_states): { got, state, linked } */
const bpPlanState = (id) => (S.bp.plans || []).find((x) => x.id === id) || { got: null, state: '', linked: true };

/** 일정이 있는 인물 id (인물 목록 차례, 그 뒤 일정에만 있는 id) */
function bpPlanCast(plans) {
  const ids = P().characters.map((c) => c.id).filter((id) => plans.some((x) => x.character === id));
  plans.forEach((x) => { if (!ids.includes(x.character)) ids.push(x.character); });
  return ids;
}

/** 띠의 공용 틀: 아크(장편) · 구간(단편) 경계 눈금, 마지막 반영 화 선, '기획한 화 / 작품 전체' 나눔 버튼. span 은 기본으로 보이는 화 수 */
function bpBandFrame(span) {
  const p = P();
  const full = Math.max(p.meta.target_episodes || 1, 1);
  const total = S.bpWide ? full : span;
  const marks = (serial() ? (p.story_arcs || []).map((s) => s.start_ep) : (p.arc || []).map((s) => s.start_ep)).filter((n) => n > 1);
  const ticks = marks.map((n) => `<span class="bp-tick" style="--at:${((n - 1) / total).toFixed(4)}" aria-hidden="true"></span>`).join('');
  const last = S.bp.last ? `<span class="bp-now" style="--at:${(S.bp.last / total).toFixed(4)}" title="${S.bp.last}화까지 반영" aria-hidden="true"></span>` : '';
  const seg = full > span ? `<div class="seg" role="group" aria-label="계획 띠 범위"><button type="button" data-action="bpWide" data-arg="" aria-pressed="${!S.bpWide}">기획한 화</button><button type="button" data-action="bpWide" data-arg="1" aria-pressed="${S.bpWide}">작품 전체</button></div>` : '';
  const range = `<span class="small">1~${total}화${S.bp.last ? ` · ${S.bp.last}화까지 반영` : ''}</span>`;
  return { total, ticks, last, seg, range };
}

/** 기획한 화(아크 · 구간 · 플롯 끝)와 더 받은 끝 화 가운데 큰 것. 작품 화수를 넘지 않는다 */
function bpPlannedSpan(more) {
  const p = P();
  const ends = [...(p.story_arcs || []).map((s) => s.end_ep), ...(p.arc || []).map((s) => s.end_ep), ...p.episodes.map((e) => e.plot.number), ...more];
  return Math.max(1, Math.min(Math.max(...ends, 1), p.meta.target_episodes || Infinity));
}

/** 능력 일정 줄들: 인물마다 한 줄. 얻은 화(상태창 기록에서 계산)를 같은 줄에 겹친다. 능력 일정 띠와 개요의 전체 띠가 함께 쓴다 */
function bpAbLanes(plans, total) {
  return bpPlanCast(plans).map((id) => {
    const mine = plans.filter((x) => x.character === id);
    const bars = mine.map((x) => ({ ...x, text: bpAbText(x), cls: x.new ? 'bp-is-rung bp-new' : 'bp-is-rung' }));
    const hits = mine.map((x) => [x, bpPlanState(x.id).got]).filter(([, got]) => got > 0).map(([x, got]) => ({ from_ep: got, to_ep: got, text: `${bpAbText(x)} 얻음`, cls: 'bp-is-hit' }));
    return bpLane(bpWho(id), [...bars, ...hits], total);
  }).join('');
}

/** 능력 일정의 계획 띠: 인물마다 한 줄 */
function bpAbilityBand(plans) {
  const f = bpBandFrame(bpPlannedSpan(plans.map((x) => x.to_ep)));
  const desc = `1~${f.total}화 능력 일정 띠: ${bpPlanCast(plans).map((id) => `${bpWho(id)} ${plans.filter((x) => x.character === id).length}줄`).join(', ')}`;
  return `<section class="card" id="bp-band"><div class="between"><h2>계획 띠</h2><div class="row">${f.seg}${f.range}</div></div>
    <div class="bp-band" role="img" aria-label="${esc(desc)}">${f.ticks}${f.last}${bpAbLanes(plans, f.total)}</div></section>`;
}

/** 전체 띠 (docs/blueprint/specs/11-whole.md): 쌍마다 한 줄에 처음 닿는 줄(단계 · 겹)만, 그 아래 능력 일정(인물마다 한 줄).
    개요는 서버 값 S.bp.firsts 를, 작품 전체 짜기 제안 카드는 이미 적은 줄과 제안 줄을 함께 본 결과의 firsts 를 준다(제안 줄은 new, 점선 테두리 .bp-new).
    다른 쌍과 같은 단계 · 겹에 겹치는 화 범위로 처음 닿는 막대는 경고 색 테두리만 바꾼다(글 경고 · 경고 수에는 넣지 않는다) */
function bpWholeBand(pairs, firsts, plans, id = 'bp-whole', title = '전체 띠') {
  plans = plans.filter((x) => x.from_ep > 0);
  if (!firsts.length && !plans.length) return '';
  const f = bpBandFrame(bpPlannedSpan([...firsts.map((x) => x.to_ep), ...plans.map((x) => x.to_ep)]));
  const lanes = pairs.map(([k, a, b]) => {
    const mine = firsts.filter((x) => x.pair === k).map((x) => {
      const who = x.axis === '단계' ? `${bpWho(x.source)} → ${bpWho(x.target)}` : '접촉';
      const crowd = (x.crowd || []).map((c) => bpPair(c).map(bpWho).join(' ↔ '));
      return { ...x, text: x.value, tip: `${x.new ? '제안 · ' : ''}${who} ${x.value}${crowd.length ? ` · ${crowd.join(', ')}와 겹침` : ''}`,
        cls: `${x.axis === '단계' ? 'bp-is-ms' : 'bp-is-rung'}${crowd.length ? ' bp-crowd' : ''}${x.new ? ' bp-new' : ''}` };
    });
    return bpLane(`${bpWho(a)} ↔ ${bpWho(b)}`, mine, f.total);
  }).join('');
  const desc = `1~${f.total}화 ${title}: ${pairs.map(([k, a, b]) => `${bpWho(a)} ↔ ${bpWho(b)} 처음 닿는 줄 ${firsts.filter((x) => x.pair === k).length}개`).join(', ')}${plans.length ? `, 능력 일정 ${plans.length}줄` : ''}`;
  return `<section class="card" id="${id}"><div class="between"><h2>${title}</h2><div class="row">${f.seg}${f.range}</div></div>
    <div class="bp-band" role="img" aria-label="${esc(desc)}">${f.ticks}${f.last}${lanes}${bpAbLanes(plans, f.total)}</div></section>`;
}

/** 일정 줄의 실제 표시: '3화에 얻음', '시작 때부터 있음', '지남' */
function bpPlanChip(st) {
  if (st.got !== null && st.got !== undefined) {
    const when = st.got === 0 ? '시작 때부터 있음' : `${st.got}화에 얻음`;
    return `<span class="chip${st.state === '얻음' ? ' finalized' : ''}">${when}${st.state === '앞섬' ? ' · 계획보다 먼저' : st.state === '늦음' ? ' · 계획보다 늦게' : ''}</span>`;
  }
  if (st.state === '모름') return '<span class="small">상태창이 없어 실제를 셀 수 없어요</span>';
  return st.state === '지남' ? '<span class="chip">아직 얻지 못함</span>' : '';
}

/** 능력 일정 카드: 인물마다 [화 범위, 능력, 등급, 얻는 조건]. 능력은 스킬 도감 항목의 이름으로 잇는다 */
function bpAbilityCard(plans) {
  const mode = bpMode('ap');
  const src = mode ? bpPlans(S.bpEdit.data) : plans;
  const edit = (x, i) => {
    const who = P().characters.map((c) => `<option value="${esc(c.id)}"${c.id === x.character ? ' selected' : ''}>${esc(c.name || c.id)}</option>`).join('')
      + (P().characters.some((c) => c.id === x.character) ? '' : `<option value="${esc(x.character)}" selected>${esc(x.character)}</option>`);
    const at = `ability_plans.${i}`;
    return `<div class="bp-ap-row"><select data-bp="${at}.character" aria-label="${i + 1}번째 줄 인물">${who}</select>
      <input type="text" data-bp="${at}.ability" value="${esc(x.ability)}" list="bp-ab-names" placeholder="능력 (도감 항목 이름)" aria-label="${i + 1}번째 줄 능력">
      <input type="text" data-bp="${at}.grade" value="${esc(x.grade)}" placeholder="등급" aria-label="${i + 1}번째 줄 등급">
      ${bpNum(`${at}.from_ep`, x.from_ep, `${i + 1}번째 줄 처음 화`)}<span aria-hidden="true">~</span>${bpNum(`${at}.to_ep`, x.to_ep, `${i + 1}번째 줄 끝 화`)}
      ${mode === 'row' ? '' : `<button type="button" class="btn icon-btn ghost bp-del" data-action="bpApDel" data-arg="${i}" aria-label="${i + 1}번째 줄 지우기">✕</button>`}
      ${bpText(`${at}.condition`, x.condition, `${i + 1}번째 줄 얻는 조건`, '얻는 조건')}</div>`;
  };
  const names = () => `<datalist id="bp-ab-names">${[...new Set((P().abilities || []).flatMap((a) => [a.name, ...(a.aliases || [])]))].map((n) => `<option value="${esc(n)}"></option>`).join('')}</datalist>`;
  // 고치는 목록도 보는 화면과 같은 차례: 인물(인물 목록 차례), 그 안에서 화 차례. 새로 더한 빈 줄은 정하지 않은 화라 그 인물 끝에 온다
  const cast = bpPlanCast(src);
  const ordered = cast.flatMap((id) => bpByEp(src.map((x, i) => [x, i]).filter(([x]) => x.character === id)));
  let body;
  if (mode === 'card') {
    body = `${ordered.map(([x, i]) => edit(x, i)).join('')}${names()}
      <div class="between"><button type="button" class="btn small" data-action="bpApAdd"${P().characters.length ? '' : ' disabled'}>+ 줄 더하기</button>${bpSaveRow()}</div>`;
  } else if (src.length) {
    body = cast.map((id) => {
      const rows = ordered.filter(([x]) => x.character === id).map(([x, i]) => {
        if (mode === 'row' && S.bpEdit.row === `ability_plans.${i}`) return `<li class="bp-row-edit">${edit(x, i)}${names()}${bpSaveRow()}</li>`;
        const st = bpPlanState(x.id);
        return `<li><span class="chip">${esc(bpRange(x))}</span><span class="bp-row-t"><strong>${esc(bpAbText(x))}</strong>${bpPlanChip(st)}
          ${x.condition ? `<span class="small">조건: ${esc(x.condition)}</span>` : ''}${st.linked ? '' : `<span class="small">도감에 없음</span><button type="button" class="link-btn small" data-action="abNew" data-arg="${esc(`|${x.ability}`)}">도감에 만들기</button>`}</span>${bpRowActs(`ability_plans.${i}`, `${bpWho(x.character)}의 ${bpAbText(x) || '능력'} 줄`)}</li>`;
      }).join('');
      return `<div class="bp-dir"><h3>${esc(bpWho(id))}</h3><ul class="bp-list">${rows}</ul></div>`;
    }).join('');
  } else body = '<span class="small">줄이 없어요. 인물이 어느 능력을 몇 화쯤 얻는지 더해요.</span>';
  return `<section class="card pf-sec${mode ? ' editing' : ''}" id="bp-ap" tabindex="-1">${bpCardHead('능력 일정', 'ap')}${body}</section>`;
}

/** 방금 한 지우기 · 더하기 · 비우기를 되돌리는 줄 (S.bpUndo). 그 쪽에서만, 다른 저장을 하면 사라진다 */
function bpUndoNote() {
  const u = S.bpUndo;
  if (!u || u.name !== S.name || u.key !== S.bpSel) return '';
  return `<div class="note bp-undo" role="status"><span>${esc(u.msg)}</span><button type="button" class="btn small" data-action="bpUndo">되돌리기</button></div>`;
}

function bpAbilityPage() {
  const plans = bpPlans(S.bp.blueprint);
  return bpUndoNote() + (plans.some((x) => x.from_ep > 0) ? bpAbilityBand(plans) : '') + bpWarnCard(bpAbWarns()) + bpAbDraftCard() + bpAbilityCard(plans) + bpAbAiCard();
}

// ----- 능력 일정을 AI 로 짜기 · 거꾸로 뽑기 (docs/blueprint/specs/12-ability-ai.md, 작업 blueprint_ability_draft · blueprint_ability) -----

/** 받을 인물 · 메모 · 범위를 고르는 칸. 결과는 능력 일정 쪽 제안 카드(bpAbDraftCard)로 온다. 쌍 쪽의 bpExtractCard 와 같은 틀이다.
    이 쪽은 머리 설명 두 문장과 경고가 있어 안내 문장을 더하지 않는다 (docs/design/README.md 덜기: 세 문장 이하). 짜는 재료는 메모 칸의 예시 글이 보인다 */
function bpAbAiCard() {
  const p = P();
  if (!p.characters.length) return '';
  const has = (s) => p.episodes.some((e) => e.plot.number >= s.start_ep && e.plot.number <= s.end_ep);
  const arcs = serial() ? (p.story_arcs || []).filter(has) : [];
  const parts = serial() ? p.parts || [] : [];
  const who = `<select id="bp-ab-who" aria-label="능력 일정을 받을 인물">${p.characters.map((c) => `<option value="${esc(c.id)}">${esc(c.name || c.id)}</option>`).join('')}</select>`;
  const partPick = parts.length ? `<select id="bp-ab-part" aria-label="짤 부">${parts.map((x) => `<option value="${x.number}">${x.number}부 · ${x.start_ep}~${x.end_ep}화</option>`).join('')}</select>` : '';
  const draft = `<div class="field"><label for="bp-ab-note">AI로 짜기 메모</label>
      <textarea id="bp-ab-note" rows="2" placeholder="예: 1부 끝에 빙결이 중급에 오른다. 새 특성은 부마다 하나"></textarea>
      <div class="row">${who}${partPick}<button type="button" class="btn small" data-action="bpAbDraftAI">AI로 짜기</button></div></div>`;
  const showExtract = !serial() ? p.episodes.length > 0 : arcs.length > 0;
  const extract = showExtract ? `<div class="row"><span class="label-text">지금 플롯에서 뽑기</span>${serial() ? `<select id="bp-ab-arc" aria-label="뽑을 아크">${arcs.map((s) => `<option value="${s.number}">아크 ${s.number} · ${s.start_ep}~${s.end_ep}화</option>`).join('')}</select>` : ''}
      <button type="button" class="btn small" data-action="bpAbExtract">AI로 뽑기</button></div>` : '';
  return `<section class="card" id="bp-ab-ai"><h2>AI로 능력 일정 받기</h2>${draft}${extract}</section>`;
}

/** 견주는 능력 이름 · 등급: 띄어쓰기 · 괄호를 뺀 소문자 (서버 abilities.key · blueprint._grade_key 와 같은 뜻) */
const bpAbNorm = (s) => String(s || '').toLowerCase().replace(/[\s()[\]（）]+/g, '');

/** 스킬 도감에 그 이름(다른 이름 포함)의 항목이 있는가 */
const bpAbKnown = (name) => (P().abilities || []).some((a) => [a.name, ...(a.aliases || [])].some((n) => bpAbNorm(n) === bpAbNorm(name)));

/** 제안 줄과 같은 인물 · 능력 · 등급인 이미 적은 줄 (서버 check 가 '두 줄'로 거절하는 줄). 없으면 undefined */
const bpAbSame = (bp, x) => bpPlans(bp).find((e) => e.character === x.character && bpAbNorm(e.ability) === bpAbNorm(x.ability) && bpAbNorm(e.grade) === bpAbNorm(x.grade));

/** 고른 줄 가운데 같은 인물 · 능력 · 등급은 앞의 것 하나만 남긴다 (뽑은 묶음과 짠 묶음이 같은 줄을 낼 수 있다. 둘 다 보내면 서버 check 가 '두 줄'로 거절한다) */
function bpAbUnique(rows) {
  const seen = new Set();
  return rows.filter((x) => {
    const k = [x.character, bpAbNorm(x.ability), bpAbNorm(x.grade)].join('|');
    return !seen.has(k) && !!seen.add(k);
  });
}

/** 제안의 능력 줄 기본 체크: 이미 적은 같은 줄만 고르지 않는다 */
const bpAbPicks = (bp, rows) => rows.map((x) => !bpAbSame(bp, x));

/** 제안 카드의 능력 묶음: 줄마다 고르기 · 화 범위 · 능력 · 조건 · 근거, 도감에 없는 이름과 이미 적은 줄 표시.
    rows 는 AbilityDraft 목록, picks 는 같은 길이의 체크, arg 는 줄 번호 앞에 붙는 data-arg 머리('머리|번호'), action 은 체크를 받는 동작 이름.
    작품 전체 짜기(11b)의 제안 카드도 이 묶음을 쓴다 (자기 동작 이름을 준다) */
function bpAbDraftRows(rows, picks, arg, withWho = false, action = 'bpAbDraftPick') {
  return `<ul class="bp-list">${rows.map((x, i) => {
    const same = bpAbSame(S.bp.blueprint, x);
    return `<li><input type="checkbox" data-action="${action}" data-arg="${esc(arg)}|${i}"${picks[i] ? ' checked' : ''} aria-label="${esc(`${bpWho(x.character)}의 ${bpAbText(x)} 줄 고르기`)}">
      <span class="chip">${esc(bpRange(x))}</span>${withWho ? `<span>${esc(bpWho(x.character))}</span>` : ''}<strong>${esc(bpAbText(x))}</strong>
      ${x.condition ? `<span class="small">조건: ${esc(x.condition)}</span>` : ''}
      ${same ? `<span class="chip warn">이미 있음</span><span class="small">${esc(bpRange(same))}</span>` : ''}
      ${bpAbKnown(x.ability) ? '' : '<span class="chip warn">도감에 없음</span>'}
      ${(x.evidence || []).length ? `<span class="small">${esc(bpEvidence(x.evidence))}</span>` : ''}</li>`;
  }).join('')}</ul>`;
}

/** 제안의 도감 초안 묶음: 초안마다 고르기 · 이름 · 상태창 항목 · 효과 · 대가 · 등급 수. 그새 도감에 생긴 이름은 보이지 않는다(보내지도 않는다).
    codex 는 AbilityCodexDraft 목록, picks 는 같은 길이의 체크, arg 는 data-arg 머리 (docs/blueprint/specs/13-ability-codex.md) */
function bpAbCodexRows(codex, picks, arg, action = 'bpAbCodexPick') {
  const rows = codex.map((c, i) => [c, i]).filter(([c]) => !bpAbKnown(c.name));
  if (!rows.length) return '';
  return `<h4>도감 초안</h4><ul class="bp-list">${rows.map(([c, i]) => `<li><input type="checkbox" data-action="${action}" data-arg="${esc(arg)}|${i}"${picks[i] ? ' checked' : ''} aria-label="${esc(`${c.name} 도감 초안 고르기`)}">
      <strong>${esc(c.name)}</strong>${c.stat ? `<span class="chip">${esc(c.stat)}</span>` : ''}
      ${c.effect || c.description ? `<span class="small">효과: ${esc(c.effect || c.description)}</span>` : ''}${c.cost ? `<span class="small">대가: ${esc(c.cost)}</span>` : ''}
      ${(c.grades || []).length ? `<span class="small">등급 ${c.grades.length}</span>` : ''}</li>`).join('')}</ul>`;
}

/** 고른 도감 초안 (그새 도감에 생긴 이름은 빼고, 같은 이름은 앞의 것 하나만) */
function bpAbCodexPicked(drafts) {
  const seen = new Set();
  return drafts.flatMap((d) => (d.codex || []).filter((c, i) => d.codexPicks[i] && !bpAbKnown(c.name)))
    .filter((c) => !seen.has(bpAbNorm(c.name)) && !!seen.add(bpAbNorm(c.name)));
}

/** 제안 자리의 열쇠: 인물 id 와 뽑기 · 짜기. 같은 인물의 뽑은 제안과 짠 제안은 따로 남는다 */
const bpAbDraftKey = (d) => `${d.character}|${d.mode === 'draft' ? 'draft' : 'extract'}`;

/** 그 고르기를 기다리는 결과가 아직 카드로 남아 있는가 (app.js pendingShown). 같은 자리에 새 제안이 오면 옛 결과는 서버에서도 지운다.
    작업이 막 끝났을 때의 기록에는 result 가 없다(app.js 가 { key, id, kind, ep } 만 넣는다). 그래서 작업 id 로 찾는다 */
function bpAbDraftShown(r) {
  const drafts = S.bpAbDrafts || {};
  return r.id ? Object.values(drafts).some((d) => d.job === r.id) : !!drafts[bpAbDraftKey(r.result || {})];
}

/** 능력 일정 제안 카드: 인물마다 한 묶음(뽑은 것 · 짠 것), 주 버튼은 '고른 줄 더하기' 하나. POST …/blueprint/apply-abilities */
function bpAbDraftCard() {
  const drafts = Object.values(S.bpAbDrafts || {});
  if (!drafts.length) return '';
  let n = 0;
  let unknown = 0;
  let drafted = 0;
  const groups = drafts.map((d) => {
    d.picks ||= bpAbPicks(S.bp.blueprint, d.abilities);
    d.codexPicks ||= (d.codex || []).map(() => true);
    n += d.abilities.length;
    drafted += (d.codex || []).filter((c) => !bpAbKnown(c.name)).length;
    unknown += d.abilities.filter((x) => !bpAbKnown(x.ability)).length;
    return `<div class="bp-dir"><div class="between"><h3>${esc(bpWho(d.character))} <span class="small">${d.mode === 'draft' ? 'AI가 짠 줄' : 'AI가 뽑은 줄'} · ${d.start}~${d.end}화</span></h3>
        <button type="button" class="btn small" data-action="bpAbDraftDrop" data-arg="${esc(bpAbDraftKey(d))}">버리기</button></div>
      ${d.reply ? `<p class="small">${esc(d.reply)}</p>` : ''}
      ${d.abilities.length ? bpAbDraftRows(d.abilities, d.picks, bpAbDraftKey(d)) : '<span class="small">제안한 줄이 없어요.</span>'}
      ${bpAbCodexRows(d.codex || [], d.codexPicks, bpAbDraftKey(d))}</div>`;
  }).join('');
  return `<section class="card" id="bp-ab-draft"><div class="between"><h2>AI가 제안한 능력 일정</h2>
      ${n ? '<button type="button" class="btn small primary" data-action="bpAbDraftUse">고른 줄 더하기</button>' : ''}</div>
    ${unknown ? `<p class="small">스킬 도감에 없는 이름이 ${unknown}줄 있어요. ${drafted ? '고른 도감 초안은 줄과 함께 도감에 만들어요.' : '더해도 되고, 도감에 항목을 만들면 효과 · 대가가 프롬프트에 들어가요.'}</p>` : ''}${groups}</section>`;
}

function bpPairPage(key) {
  const [, a, b] = bpPairs(P(), S.bp.blueprint).find(([k]) => k === key);
  const x = bpOfPair(S.bp.blueprint, S.bp.warnings, a, b);
  return bpUndoNote() + bpBand(a, b, x) + bpWarnCard(x.warns) + bpHeldCard() + bpDraftCard(key, a, b) + bpMsCard(a, b, x) + bpLadderCard(a, b, x) + bpExtractCard(key);
}

// ----- 지금 플롯에서 거꾸로 뽑기 (docs/blueprint/specs/05-extract.md, 작업 blueprint) -----

/** 뽑을 범위를 고르는 칸: 장편은 플롯이 있는 아크, 단편은 작품 전체. 결과는 카드 안 제안(bpDraftCard)으로 온다 */
function bpExtractCard(key) {
  const p = P();
  const has = (s) => p.episodes.some((e) => e.plot.number >= s.start_ep && e.plot.number <= s.end_ep);
  const arcs = serial() ? (p.story_arcs || []).filter(has) : [];
  const parts = serial() ? p.parts || [] : [];
  const partPick = parts.length ? `<select id="bp-part" aria-label="짤 부">${parts.map((x) => `<option value="${x.number}">${x.number}부 · ${x.start_ep}~${x.end_ep}화</option>`).join('')}</select>` : '';
  const draft = `<div class="field"><label for="bp-note-ai">AI로 짜기 <span class="hint">설정 · 부 구성 · 이 메모로 이정표와 사다리 칸을 제안받아요</span></label>
      <textarea id="bp-note-ai" rows="2" placeholder="예: 1부 끝에 스스로 단추를 푼다. 2부부터 공범이 된다"></textarea>
      <div class="row">${partPick}<button type="button" class="btn small" data-action="bpDraftAI" data-arg="${esc(key)}">AI로 짜기</button></div></div>`;
  const showExtract = !serial() ? p.episodes.length > 0 : arcs.length > 0;
  const extract = showExtract ? `<div class="row"><span class="label-text">지금 플롯에서 뽑기</span>${serial() ? `<select id="bp-arc" aria-label="뽑을 아크">${arcs.map((s) => `<option value="${s.number}">아크 ${s.number} · ${s.start_ep}~${s.end_ep}화</option>`).join('')}</select>` : ''}
      <button type="button" class="btn small" data-action="bpExtract" data-arg="${esc(key)}">AI로 뽑기</button></div>` : '';
  return `<section class="card" id="bp-extract"><h2>AI로 설계도 받기</h2>${draft}${extract}</section>`;
}

/** 근거 줄: '12화 「…」' */
const bpEvidence = (ev) => (ev || []).map((e) => `${e.episode}화 「${e.quote}」`).join(' · ');

/** 비교용 라벨: 띄어쓰기 · 문장부호를 뺀 소문자 */
const bpNorm = (s) => String(s || '').toLowerCase().replace(/[\s.,·!?~'"「」『』()[\]-]+/g, '');

/** 두 라벨이 비슷한가: 같거나 한쪽이 다른 쪽을 품는다(두 글자 이상) */
function bpSimilar(p, q) {
  const [x, y] = [bpNorm(p), bpNorm(q)];
  return !!x && !!y && (x === y || (Math.min(x.length, y.length) >= 2 && (x.includes(y) || y.includes(x))));
}

/** 두 화 범위가 겹치는가 (끝 화 포함: 30~35 와 35~40 은 겹친다). 정하지 않은 범위는 겹치지 않는다 */
function bpRangesMeet(p, q) {
  if (!(p.from_ep > 0) || !(q.from_ep > 0)) return false;
  return p.from_ep <= (q.to_ep || q.from_ep) && q.from_ep <= (p.to_ep || p.from_ep);
}

/** AI 제안 줄과 이미 있는 줄의 겹침. { ms: [겹친 이정표 | null], rungs: [[겹친 칸, 차례] | null] }
    이정표: 같은 방향이고 화 범위가 겹치거나, 같은 단계에 라벨이 비슷하다. 사다리 칸: 라벨이 비슷하거나, 범위가 겹치고 겹이 같다 */
function bpOverlaps(bp, d) {
  const ms = (bp.milestones || []);
  const lad = (bp.ladders || []).find((l) => bpKey(l.a, l.b) === bpKey(d.a, d.b));
  return {
    ms: d.milestones.map((m) => ms.find((e) => e.source === m.source && e.target === m.target
      && (bpRangesMeet(e, m) || ((!m.stage || e.stage === m.stage) && bpSimilar(e.label, m.label)))) || null),
    rungs: d.rungs.map((r) => {
      const i = lad ? lad.rungs.findIndex((e) => bpSimilar(e.label, r.label) || (bpRangesMeet(e, r) && e.layer === r.layer)) : -1;
      return i >= 0 ? [lad.rungs[i], i] : null;
    }),
  };
}

/** AI 제안 카드: 줄마다 고르기와 근거. 이미 있는 줄과 겹치는 줄은 표시하고 기본으로 고르지 않는다. '고른 줄 더하기'는 POST …/blueprint/apply */
function bpDraftCard(key, a, b) {
  const d = S.bpDraft;
  if (!d || bpKey(d.a, d.b) !== key) return '';
  const ov = bpOverlaps(S.bp.blueprint, d);
  d.pickMs ||= d.milestones.map((_, i) => !ov.ms[i]);
  d.pickRungs ||= d.rungs.map((_, i) => !ov.rungs[i]);
  const box = (kind, i, on, label) => `<input type="checkbox" data-action="bpDraftPick" data-arg="${kind}|${i}"${on ? ' checked' : ''} aria-label="${esc(label)}">`;
  const same = (text) => `<span class="chip warn">이미 있음</span><span class="small">${esc(text)}</span>`;
  const ms = d.milestones.map((m, i) => `<li>${box('ms', i, d.pickMs[i], `이정표 ${i + 1} 고르기`)}<span class="chip">${esc(bpRange(m))}</span>
      <span>${esc(bpWho(m.source))} → ${esc(bpWho(m.target))}</span>${m.stage ? `<span class="chip confirmed">${esc(m.stage)}</span>` : ''}<span>${esc(m.label)}</span>
      ${ov.ms[i] ? same(`${bpRange(ov.ms[i])} ${ov.ms[i].stage || ''} ${ov.ms[i].label}`.replace(/\s+/g, ' ')) : ''}
      ${m.evidence.length ? `<span class="small">${esc(bpEvidence(m.evidence))}</span>` : ''}</li>`).join('');
  const label = (ids, picks) => ids.map((id) => (picks.find((x) => x.id === id) || { label: id }).label).join(', ');
  const rungs = d.rungs.map((r, i) => `<li>${box('rung', i, d.pickRungs[i], `사다리 칸 ${i + 1} 고르기`)}<span class="chip">${esc(bpRange(r))}</span><strong>${esc(r.label)}</strong>
      <span class="small">${esc([r.layer, label(r.parts, S.bp.parts), label(r.acts, S.bp.acts), label(r.places, bpPlaces()), r.lead ? `${bpWho(r.lead)} 주도` : ''].filter(Boolean).join(' · '))}</span>
      ${ov.rungs[i] ? same(`${ov.rungs[i][1] + 1}. ${bpRange(ov.rungs[i][0])} ${ov.rungs[i][0].label}`) : ''}
      ${r.evidence.length ? `<span class="small">${esc(bpEvidence(r.evidence))}</span>` : ''}</li>`).join('');
  const none = !d.milestones.length && !d.rungs.length;
  return `<section class="card" id="bp-draft"><div class="between"><h2>${d.mode === 'draft' ? 'AI가 짠 설계도' : 'AI가 뽑은 설계도'} <span class="small">${d.start}~${d.end}화</span></h2>
      <span class="row"><button type="button" class="btn small" data-action="bpDraftDrop">버리기</button>${none ? '' : '<button type="button" class="btn small primary" data-action="bpDraftUse">고른 줄 더하기</button>'}</span></div>
    ${d.reply ? `<p class="small">${esc(d.reply)}</p>` : ''}
    ${ms ? `<h3>관계 이정표</h3><ul class="bp-list">${ms}</ul>` : ''}${rungs ? `<h3>접촉 사다리</h3><ul class="bp-list">${rungs}</ul>` : ''}
    ${none ? '<span class="small">뽑은 줄이 없어요.</span>' : ''}</section>`;
}

JOB_PAGES.blueprint = ['blueprint'];
JOB_LINK.blueprint = (j) => `#/p/${enc(j.project)}/blueprint/${enc(j.target || '')}`;
JOB_DONE_MSG.blueprint = '설계도 제안이 도착했어요. 더할 줄을 골라 주세요.';
JOB_PAGES.blueprint_draft = ['blueprint'];
JOB_PAGES.blueprint_whole = ['blueprint'];
JOB_LINK.blueprint_whole = (j) => `#/p/${enc(j.project)}/blueprint`;  // 제안 카드는 개요에 있다
JOB_DONE_MSG.blueprint_whole = '작품 전체 설계도 제안이 도착했어요. 더할 줄을 골라 주세요.';
JOB_LINK.blueprint_draft = JOB_LINK.blueprint;
JOB_DONE_MSG.blueprint_draft = JOB_DONE_MSG.blueprint;
['blueprint_ability', 'blueprint_ability_draft'].forEach((k) => {
  JOB_PAGES[k] = ['blueprint'];
  JOB_LINK[k] = (j) => `#/p/${enc(j.project)}/blueprint/${enc(BP_AB)}`;  // 대상은 인물 id 라 쌍 쪽이 아니라 능력 일정 쪽으로 간다
  JOB_DONE_MSG[k] = '능력 일정 제안이 도착했어요. 더할 줄을 골라 주세요.';
});

function viewBlueprint() {
  bpDraftMark();
  const head = header('작품 도구', '설계도', '관계가 몇 화쯤 어디에 닿는지, 두 인물의 접촉이 몇 화쯤 어디까지 가는지, 능력을 몇 화쯤 얻는지 먼저 정해요. 플롯 점검이 이 계획과 견줘 알려요.');
  const d = S.bp;
  if (!d) return `${head}<div class="small">불러오는 중…</div>`;
  if (d.error) return `${head}<div class="note err">${esc(d.error)}</div>`;
  const known = bpPairs(P(), d.blueprint).some(([k]) => k === S.bpSel);
  const main = S.bpSel === BP_AB ? bpAbilityPage() : S.bpSel && known ? bpPairPage(S.bpSel) : bpOverview();
  return `${head}${outlineDoc(bpToc(), `<div class="ab-col">${main}</div>`, { cls: 'ab-wrap' })}`;
}

// ----- 고치기 -----

const bpDirty = () => !!(S.bpEdit && JSON.stringify(S.bpEdit.data) !== S.bpEdit.orig);
function bpDraftMark() { (S.editDrafts ||= {}).bp = bpDirty(); }
if (typeof onEditDiscard === 'function') onEditDiscard('bp', () => { S.bpEdit = null; });
const bpDropOk = () => askConfirm('고치던 설계도 칸의 글을 저장하지 않고 닫을까요?', { ok: '닫고 열기', danger: true });

/** 'milestones.0.label' 같은 길의 값 바꾸기 (숫자 칸은 정수로) */
function bpSet(path, value) {
  const keys = path.split('.');
  let o = S.bpEdit.data;
  keys.slice(0, -1).forEach((k) => { o = o[k]; });
  const last = keys[keys.length - 1];
  // 글 칸은 여러 줄로 보이지만 한 줄로 저장한다 (프롬프트의 설계도 줄 plan_lines · rung_text 가 한 줄이다)
  o[last] = /_ep$/.test(last) ? Math.max(0, parseInt(value, 10) || 0) : typeof value === 'string' ? value.replace(/\s*\n\s*/g, ' ') : value;
}

function bpGet(path) {
  return path.split('.').reduce((o, k) => o[k], S.bpEdit.data);
}

document.addEventListener('input', (e) => {
  const path = e.target.dataset && e.target.dataset.bp;
  if (!path || !S.bpEdit) return;
  bpSet(path, e.target.value);
  bpDraftMark();
});
document.addEventListener('toggle', (e) => {
  const path = e.target.dataset && e.target.dataset.bpPick;
  if (path !== undefined) S.bpPickOpen = e.target.open ? path : (S.bpPickOpen === path ? '' : S.bpPickOpen);
}, true);
document.addEventListener('change', (e) => {
  const path = e.target.dataset && e.target.dataset.bp;
  if (!path || !S.bpEdit || e.target.tagName !== 'SELECT') return;
  bpSet(path, e.target.value);
  bpDraftMark();
});

/** 저장할 설계도: 서버 값에 고친 카드의 몫만 바꿔 넣는다 */
function bpMerged(edit, server) {
  const out = JSON.parse(JSON.stringify(server));
  const [a, b] = bpPair(edit.key);
  const inPair = (s, t) => (s === a && t === b) || (s === b && t === a);
  if (edit.card === 'note') out.note = edit.data.note;
  if (edit.card === 'ap') out.ability_plans = edit.data.ability_plans.filter((x) => x.ability.trim());  // 능력 이름을 비운 줄은 뺀다
  if (edit.card === 'ms') out.milestones = [...out.milestones.filter((m) => !inPair(m.source, m.target)), ...edit.data.milestones.filter((m) => inPair(m.source, m.target))];
  if (edit.card === 'ladder') {
    const mine = edit.data.ladders.find((l) => inPair(l.a, l.b));
    out.ladders = out.ladders.filter((l) => !inPair(l.a, l.b));
    if (mine && mine.rungs.length) out.ladders.push(mine);
  }
  return out;
}

/** 고치기를 닫은 뒤 포커스를 둘 곳: 누른 줄의 고치기 버튼, 카드면 카드 머리 '고치기' */
function bpBackFocus(e) {
  if (e.row) {
    // 사다리 칸은 차례로 옮겼을 수 있어 그 칸의 id 로 다시 찾지 않고 같은 길을 쓴다
    return `[data-action="bpRowEdit"][data-arg="${e.row}"], #bp-${e.card === 'ladder' ? 'ladder' : e.card}`;
  }
  return `[data-action="bpEditOpen"][data-arg="${e.card}"]`;
}

/** 서버에 바로 쓰는 줄 지우기 · 제안 더하기 · 여정 비우기. 고치던 칸은 닫고(저장하지 않은 글은 묻는다), 쓴 뒤 되돌리기 알림을 띄운다.
    send 는 저장한 작품을 돌려준다. 되돌리기는 S.bpUndo 로 쪽 위 줄(bpUndoNote)에도 남는다 */
async function bpWrite(label, msg, send) {
  if (bpDirty() && !(await bpDropOk())) return;
  S.bpEdit = null;
  const before = JSON.stringify(S.bp.blueprint);
  const name = S.name;
  const key = S.bpSel;
  await run(label, async () => {
    S.project = await send();
    S.bp = await api('GET', `/projects/${enc(name)}/blueprint`);
    S.bpUndo = { name, key, before, after: JSON.stringify(S.bp.blueprint), msg, abIds: S.bpAbMade || [] };
    S.bpAbMade = null;
    toast(msg, false, { actions: [{ label: '되돌리기', run: () => actions.bpUndo() }] });
  });
}

Object.assign(actions, {
  bpWholeToggle() {
    S.bpWholeOpen = !S.bpWholeOpen;
    if (S.bpWholeOpen) S.focusTarget = '#bp-whole-note';
    render();
  },
  async bpWholeAI() {
    const sel = document.getElementById('bp-whole-part');
    const note = (document.getElementById('bp-whole-note') || {}).value || '';
    const pairs = [...document.querySelectorAll('.bp-whole-pair')].filter((x) => x.checked).map((x) => x.value);
    if (!pairs.length) { toast('짤 쌍을 골라 주세요', true); return; }
    await startJob('blueprint_whole', sel ? Number(sel.value) : null, { target: '@whole', note, pairs });  // 도착하면 개요의 제안 카드 (bpWholeDraftCard)
  },
  bpWholePick(arg) {
    const [k, kind, i] = String(arg).split('|');
    const pk = (S.bpWhole && S.bpWhole.pick || {})[k];
    if (!pk) return;
    if (kind === 'all') {
      const on = ![...pk.ms, ...pk.rungs].every(Boolean);
      pk.ms = pk.ms.map(() => on);
      pk.rungs = pk.rungs.map(() => on);
      render();
      return;
    }
    const list = kind === 'ms' ? pk.ms : pk.rungs;
    list[Number(i)] = !list[Number(i)];
    render();
  },
  bpWholeCodexPick(arg) {
    const i = Number(String(arg).split('|').pop());
    if (S.bpWhole) S.bpWhole.codexPicks[i] = !S.bpWhole.codexPicks[i];
  },
  bpWholeAbPick(arg) {
    const i = Number(String(arg).split('|').pop());
    if (S.bpWhole) S.bpWhole.abPicks[i] = !S.bpWhole.abPicks[i];
  },
  async bpWholeDrop() {
    if (!(await confirmDrop('AI 전체 설계도 제안'))) return;
    S.bpWhole = null;
    render();
  },
  async bpWholeUse() {
    const d = S.bpWhole;
    const pick = bpWholePicks(d);
    const pairs = d.pairs.map((x) => {
      const pk = pick[bpKey(x.a, x.b)];
      return { a: x.a, b: x.b, milestones: x.milestones.filter((_, i) => pk.ms[i]), rungs: x.rungs.filter((_, i) => pk.rungs[i]) };
    }).filter((x) => x.milestones.length || x.rungs.length);
    const abilities = bpAbUnique(d.abilities.filter((_, i) => d.abPicks[i]));
    const codex = bpAbCodexPicked([d]);
    if (!pairs.length && !abilities.length) { toast('더할 줄을 골라 주세요', true); return; }
    const had = new Set((P().abilities || []).map((a) => a.id));
    const ms = pairs.reduce((n, x) => n + x.milestones.length, 0);
    const rungs = pairs.reduce((n, x) => n + x.rungs.length, 0);
    await bpWrite('설계도에 더하는 중', `쌍 ${pairs.length}개에 이정표 ${ms}줄 · 사다리 ${rungs}칸, 능력 일정 ${abilities.length}줄을 더했어요`, async () => {
      const out = await api('POST', `/projects/${enc(S.name)}/blueprint/apply-set`, { pairs, abilities, codex });
      S.bpWhole = null;
      S.bpAbMade = (out.abilities || []).map((a) => a.id).filter((id) => !had.has(id));  // bpWrite 가 되돌리기(S.bpUndo.abIds)에 옮긴다
      return out;
    });
  },
  async bpDraftAI(key) {
    const sel = document.getElementById('bp-part');
    const note = (document.getElementById('bp-note-ai') || {}).value || '';
    await startJob('blueprint_draft', sel ? Number(sel.value) : null, { target: key, note });  // 도착하면 쌍 쪽 카드 안 제안 (bpDraftCard)
  },
  async bpExtract(key) {
    const sel = document.getElementById('bp-arc');
    await startJob('blueprint', sel ? Number(sel.value) : null, { target: key, note: '' });  // 도착하면 쌍 쪽 카드 안 제안 (bpDraftCard)
  },
  async bpAbDraftAI() {
    const cid = (document.getElementById('bp-ab-who') || {}).value || '';
    const sel = document.getElementById('bp-ab-part');
    const note = (document.getElementById('bp-ab-note') || {}).value || '';
    await startJob('blueprint_ability_draft', sel ? Number(sel.value) : null, { target: cid, note });  // 도착하면 능력 일정 쪽 제안 카드 (bpAbDraftCard)
  },
  async bpAbExtract() {
    const cid = (document.getElementById('bp-ab-who') || {}).value || '';
    const sel = document.getElementById('bp-ab-arc');
    await startJob('blueprint_ability', sel ? Number(sel.value) : null, { target: cid, note: '' });
  },
  bpAbDraftPick(arg) {
    const at = String(arg).lastIndexOf('|');
    const d = (S.bpAbDrafts || {})[String(arg).slice(0, at)];
    const i = Number(String(arg).slice(at + 1));
    if (d) d.picks[i] = !d.picks[i];
  },
  bpAbCodexPick(arg) {
    const at = String(arg).lastIndexOf('|');
    const d = (S.bpAbDrafts || {})[String(arg).slice(0, at)];
    const i = Number(String(arg).slice(at + 1));
    if (d) d.codexPicks[i] = !d.codexPicks[i];
  },
  async bpAbDraftDrop(key) {
    if (!(await confirmDrop('AI 능력 일정 제안'))) return;
    delete (S.bpAbDrafts || {})[key];
    render();
  },
  async bpAbDraftUse() {
    const drafts = Object.values(S.bpAbDrafts || {});
    const rows = bpAbUnique(drafts.flatMap((d) => d.abilities.filter((_, i) => d.picks[i])));
    const codex = bpAbCodexPicked(drafts);
    if (!rows.length && !codex.length) { toast('더할 줄을 골라 주세요', true); return; }
    const had = new Set((P().abilities || []).map((a) => a.id));
    const msg = [rows.length ? `능력 일정 ${rows.length}줄` : '', codex.length ? `도감 항목 ${codex.length}개` : ''].filter(Boolean).join('과 ');
    await bpWrite('능력 일정에 더하는 중', `${msg}${codex.length ? '를' : '을'} 더했어요`, async () => {
      const out = await api('POST', `/projects/${enc(S.name)}/blueprint/apply-abilities`, { abilities: rows, codex });
      S.bpAbDrafts = {};
      S.bpAbMade = (out.abilities || []).map((a) => a.id).filter((id) => !had.has(id));  // bpWrite 가 되돌리기(S.bpUndo.abIds)에 옮긴다
      return out;
    });
  },
  bpDraftPick(arg) {
    const [kind, i] = String(arg).split('|');
    const list = kind === 'ms' ? S.bpDraft.pickMs : S.bpDraft.pickRungs;
    list[Number(i)] = !list[Number(i)];
  },
  async bpDraftDrop() {
    if (!(await confirmDrop('AI 설계도 제안'))) return;
    S.bpDraft = null;
    render();
  },
  async bpDraftUse() {
    const d = S.bpDraft;
    const body = { a: d.a, b: d.b, milestones: d.milestones.filter((_, i) => d.pickMs[i]), rungs: d.rungs.filter((_, i) => d.pickRungs[i]) };
    if (!body.milestones.length && !body.rungs.length) { toast('더할 줄을 골라 주세요', true); return; }
    await bpWrite('설계도에 더하는 중', `이정표 ${body.milestones.length}줄 · 사다리 ${body.rungs.length}칸을 더했어요`, async () => {
      const out = await api('POST', `/projects/${enc(S.name)}/blueprint/apply`, body);
      S.bpDraft = null;
      return out;
    });
  },
  async bpRowEdit(path) {
    if (bpDirty() && !(await bpDropOk())) return;
    const card = { milestones: 'ms', ladders: 'ladder', ability_plans: 'ap' }[String(path).split('.')[0]];
    const data = JSON.parse(JSON.stringify(S.bp.blueprint));
    data.ability_plans ||= [];
    S.bpEdit = { card, key: S.bpSel, data, orig: JSON.stringify(data), row: String(path) };
    S.focusTarget = `.bp-row-edit [data-bp^="${path}."]`;
    render();
  },
  async bpRowDel(path) {
    const next = JSON.parse(JSON.stringify(S.bp.blueprint));
    const keys = String(path).split('.');
    const list = keys.slice(0, -1).reduce((o, k) => o[k], next);
    list.splice(Number(keys[keys.length - 1]), 1);
    next.ladders = next.ladders.filter((l) => l.rungs.length);  // 칸을 다 지운 사다리는 뺀다 (bpMerged 와 같다)
    const what = { milestones: '이정표 한 줄을', ladders: '사다리 칸 하나를', ability_plans: '능력 일정 한 줄을' }[keys[0]];
    await bpWrite('지우는 중', `${what} 지웠어요`, () => api('PUT', `/projects/${enc(S.name)}/blueprint`, next));
  },
  async bpClear(key) {
    const [a, b] = bpPair(key);
    const x = bpOfPair(S.bp.blueprint, [], a, b);
    const n = x.ms.length;
    const m = x.ladder ? x.ladder.rungs.length : 0;
    const who = `${bpWho(a)} ↔ ${bpWho(b)}`;
    if (!(await askConfirm(`${who}의 이정표 ${n}줄과 사다리 ${m}칸을 모두 지울까요? 바로 뒤에는 되돌릴 수 있어요.`, { ok: '여정 비우기', danger: true }))) return;
    const next = JSON.parse(JSON.stringify(S.bp.blueprint));
    const inPair = (s, t) => bpKey(s, t) === bpKey(a, b);
    next.milestones = next.milestones.filter((ms) => !inPair(ms.source, ms.target));
    next.ladders = next.ladders.filter((l) => !inPair(l.a, l.b));
    await bpWrite('여정을 비우는 중', `${who}의 여정을 비웠어요`, () => api('PUT', `/projects/${enc(S.name)}/blueprint`, next));
  },
  async bpUndo() {
    const u = S.bpUndo;
    if (!u || u.name !== S.name) { toast('되돌릴 것이 없어요', true); return; }
    if (bpDirty() && !(await bpDropOk())) return;
    await run('되돌리는 중', async () => {
      const now = await api('GET', `/projects/${enc(S.name)}/blueprint`);
      S.bpUndo = null;
      S.bpEdit = null;
      if (JSON.stringify(now.blueprint) !== u.after) {  // 그 뒤에 다른 곳에서 설계도를 바꿨다. 덮지 않는다
        S.bp = now;
        toast('그 뒤에 설계도가 바뀌어서 되돌리지 않았어요', true);
        return;
      }
      S.project = await api('PUT', `/projects/${enc(S.name)}/blueprint`, JSON.parse(u.before));
      for (const id of u.abIds || []) {  // 같이 만든 도감 항목도 지운다 (그새 작가가 지웠으면 건너뛴다)
        if ((S.project.abilities || []).some((a) => a.id === id)) S.project = await api('DELETE', `/projects/${enc(S.name)}/abilities/${enc(id)}`);
      }
      S.bp = await api('GET', `/projects/${enc(S.name)}/blueprint`);
      toast('되돌렸어요');
    });
  },
  async bpEditOpen(card) {
    if (bpDirty() && !(await bpDropOk())) return;
    const data = JSON.parse(JSON.stringify(S.bp.blueprint));
    data.ability_plans ||= [];
    if (card === 'ladder' && !data.ladders.some((l) => bpKey(l.a, l.b) === S.bpSel)) {
      const [a, b] = bpPair(S.bpSel);
      data.ladders.push({ a, b, rungs: [] });
    }
    S.bpEdit = { card, key: S.bpSel, data, orig: JSON.stringify(data) };
    S.focusTarget = `#bp-${card === 'note' ? 'note' : card} input, #bp-${card} button`;
    render();
  },
  bpCancel() {
    const e = S.bpEdit;
    S.bpEdit = null;
    if (e) S.focusTarget = bpBackFocus(e);
    render();
  },
  bpMsAdd(arg) {
    const [source, target] = String(arg).split('|');
    S.bpEdit.data.milestones.push({ id: '', source, target, from_ep: 0, to_ep: 0, stage: '', label: '', trigger: '' });
    S.focusTarget = `[data-bp="milestones.${S.bpEdit.data.milestones.length - 1}.from_ep"]`;
    render();
  },
  bpWide(on) { S.bpWide = !!on; render(); },
  async bpHeld(arg) {
    const [i, act] = String(arg).split('|');
    await run(act === 'take' ? '기록하는 중' : '버리는 중', async () => {
      S.project = await api('POST', `/projects/${enc(S.name)}/blueprint/held/${Number(i)}/${act}`);
      toast(act === 'take' ? '닿은 칸을 기록했어요' : '남겨 둔 제안을 버렸어요');
    });
  },
  bpMsDel(i) { S.bpEdit.data.milestones.splice(Number(i), 1); render(); },
  bpApAdd() {
    const rows = S.bpEdit.data.ability_plans;
    const who = rows.length ? rows[rows.length - 1].character : P().characters[0].id;  // 앞줄과 같은 인물로 시작한다
    rows.push({ id: '', character: who, ability: '', grade: '', condition: '', from_ep: 0, to_ep: 0 });
    S.focusTarget = `[data-bp="ability_plans.${rows.length - 1}.ability"]`;
    render();
  },
  bpApDel(i) { S.bpEdit.data.ability_plans.splice(Number(i), 1); render(); },
  bpRungAdd() {
    const l = S.bpEdit.data.ladders.find((x) => bpKey(x.a, x.b) === S.bpEdit.key);
    l.rungs.push({ id: '', label: '', parts: [], acts: [], layer: '', places: [], lead: '', note: '', from_ep: 0, to_ep: 0 });
    S.focusTarget = `[aria-label="${l.rungs.length}번째 칸 이름"]`;
    render();
  },
  bpRungDel(i) {
    const l = S.bpEdit.data.ladders.find((x) => bpKey(x.a, x.b) === S.bpEdit.key);
    l.rungs.splice(Number(i), 1);
    render();
  },
  bpRungMove(arg) {
    const [i, d] = String(arg).split('|').map(Number);
    const l = S.bpEdit.data.ladders.find((x) => bpKey(x.a, x.b) === S.bpEdit.key);
    const j = i + d;
    if (j < 0 || j >= l.rungs.length) return;
    [l.rungs[i], l.rungs[j]] = [l.rungs[j], l.rungs[i]];
    if (S.bpEdit.row) S.bpEdit.row = S.bpEdit.row.replace(/\.\d+$/, `.${j}`);  // 누른 줄만 열었으면 그 줄을 따라간다
    S.focusTarget = `[data-action="bpRungMove"][data-arg="${j}|${d}"]`;
    render();
  },
  bpLayer(arg) {
    const [path, w] = String(arg).split('|');
    bpSet(`${path}.layer`, w);
    render();
  },
  bpToggle(arg) {
    const [path, id] = String(arg).split('|');
    const list = bpGet(path);
    const k = list.indexOf(id);
    if (k >= 0) list.splice(k, 1); else list.push(id);
    S.bpPickOpen = path;  // 다시 그려도 이 묶음은 펴 둔다
    S.focusTarget = `[data-action="bpToggle"][data-arg="${CSS.escape(String(arg))}"]`;
    render();
  },
  async bpSave() {
    const e = S.bpEdit;
    await run('설계도 저장하는 중', async () => {
      S.project = await api('PUT', `/projects/${enc(S.name)}/blueprint`, bpMerged(e, S.bp.blueprint));
      S.bpEdit = null;
      S.bpUndo = null;  // 저장한 뒤에는 앞의 되돌리기가 이 저장을 덮으므로 닫는다
      S.bp = await api('GET', `/projects/${enc(S.name)}/blueprint`);
      S.focusTarget = bpBackFocus(e);
      toast('설계도를 저장했어요');
    });
  },
});

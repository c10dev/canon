/* 갈래: 같은 작품에서 n화부터 다른 전개를 쓰는 사본 (서버 canon/branches.py, 갈래 정보는 작품 폴더의 branch.json).
   작품 머리 띠(branchStrip), 갈래 만들기 칸(branchFormCard), 작품 목록의 갈래 묶기(branchGroups).
   app.js 의 S, actions, api, render, run 을 그대로 쓴다. */
'use strict';

/** 지금 작품의 갈래 집안 (web.branch_family). 작품을 바꿨거나 작품 홈에 올 때 다시 읽는다. */
async function branchLoad(pre) {
  const name = S.name;
  const fam = await (pre || api('GET', `/projects/${enc(name)}/branches`)).catch(() => null);
  S.branchFam = fam && { ...fam, name };
}

const branchFam = () => (S.branchFam && S.branchFam.name === S.name ? S.branchFam : null);
const branchMe = (fam) => fam && fam.members.find((m) => m.name === S.name);
// 이름 없는 갈래는 제목이 본편과 같아 폴더 이름으로 부른다
const branchName = (m) => m.info.label || (m.info.parent ? m.name : m.title) || m.name;
/** 마지막으로 반영한 화. 갈래는 1~(이 화+1)화부터 만들 수 있다 (branches.check_fork) */
const lastFinal = () => Math.max(0, ...P().episodes.filter((e) => e.status === 'finalized').map((e) => e.plot.number));

/** 작품 머리 띠: 갈래 작품이면 어느 화면에서든 갈래 이름과 갈라진 곳을 한 줄로 보인다 (다른 갈래를 고치는 줄 헷갈리지 않게).
    본편은 작품 홈에서만 갈래 수를 보인다. 갈래 비교 화면은 화면이 같은 말을 하니 띠를 두지 않고 경고만 남긴다.
    함께 쓰는 앞 화를 한쪽에서 고쳤다는 경고와 '남겨 두고' 만든 갈래의 이어 가기 안내는 띠 아래 Note 로 따로 둔다 */
function branchStrip(page) {
  const fam = branchFam();
  const me = branchMe(fam);
  if (!me || fam.members.length < 2) return '';
  const others = fam.members.filter((m) => m.name !== S.name);
  if (!me.info.parent) {
    if (page) return '';
    return `<div class="note info branch-strip" role="note"><strong>본편</strong><span>갈래 ${others.length}개</span><a href="${base()}/branches">갈래 비교</a></div>`;
  }
  const shared = me.info.from_ep > 1 ? `${me.info.from_ep > 2 ? `1~${me.info.from_ep - 1}` : '1'}화` : '';
  const parent = fam.members.find((m) => m.name === me.parent_name);
  const main = fam.members.find((m) => m.name === fam.main);
  const warn = [
    me.shared_edited && shared ? `갈라진 뒤 이 갈래에서 ${shared}를 고쳤어요. 다른 갈래에는 들어가지 않아요.` : '',
    me.parent_edited && shared && parent ? `갈라진 뒤 '${esc(branchName(parent))}'에서 ${shared}를 고쳤어요. 이 갈래에는 들어가지 않아요.` : '',
  ].filter(Boolean);
  // '남겨 두고' 만든 갈래: 갈라진 화부터 본문은 있고 상태 반영이 없는 화. 화마다 승인하거나 자동 집필로 이어서 다시 승인한다
  const left = P().episodes.filter((e) => e.plot.number >= me.info.from_ep && e.status === 'written').map((e) => e.plot.number).sort((a, b) => a - b);
  const resume = left.length && page !== 'review' && page !== 'auto' ? `<div class="note warn" role="note"><div>${rangeText(left)}화 본문이 남아 있어요. 화마다 상태 승인을 하거나, 자동 집필로 ${left[left.length - 1]}화까지 이어서 다시 승인해요.</div>
    <div class="row" style="margin-top:8px"><a class="btn small" href="${base()}/review/${left[0]}">${left[0]}화 상태 승인</a>${left.length > 1 ? `<button type="button" class="btn small" data-action="branchResume" data-arg="${left[left.length - 1]}">자동 집필로 이어 가기</button>` : ''}</div></div>` : '';
  const notes = `${warn.map((w) => `<div class="note warn" role="note">${w}</div>`).join('')}${resume}`;
  if (page === 'branches') return notes;
  const more = menuBtn('br-strip', '⋯', () => `${parent ? `<a class="pop-item" href="#/p/${enc(parent.name)}">갈라져 나온 작품 열기 · ${esc(branchName(parent))}</a>` : ''}${main && main !== parent ? `<a class="pop-item" href="#/p/${enc(main.name)}">본편 열기 · ${esc(branchName(main))}</a>` : ''}${others.length > 1 ? `<div class="pop-sep"></div><div class="pop-legend">집안</div>${others.filter((m) => m !== parent && m !== main).map((m) => `<a class="pop-item" href="#/p/${enc(m.name)}">${esc(branchName(m))}<span class="small">${m.info.parent ? `${m.info.from_ep}화부터` : '본편'}</span></a>`).join('')}` : ''}`, { cls: 'btn small ghost', aria: '갈래 집안 열기' });
  return `<div class="note info branch-strip" role="note"><strong>갈래 · ${esc(me.info.label || S.name)}</strong><span>${me.info.from_ep}화부터 ${parent ? `'${esc(branchName(parent))}'${josa(branchName(parent), '과', '와')} 달라요` : '갈라졌어요'}${shared ? ` · ${shared}는 함께 써요` : ''}</span><span class="fill"></span><a href="${base()}/branches">비교</a>${more}</div>${notes}`;
}

/** 화면에 갈래 띠와 갈래 만들기 칸을 넣는다: 화면 머리(.page-head) 바로 아래. 머리로 시작하지 않는 화면은 맨 위.
    갈래 만들기 칸을 펴면 그 칸의 만들기 버튼이 주 버튼이라, 화면의 다른 주 버튼(머리 · 다시 맞추기 카드 등)은 보조 버튼으로 낮춘다 (주 버튼은 한 화면에 하나) */
function branchPlace(page, body) {
  const form = branchFormCard();
  const add = branchStrip(page) + form;
  if (!add) return body;
  const rest = form ? body.replace(/(class="[^"]*?)\s+primary\b/g, '$1') : body;
  const lead = rest.match(/^\s*<header class="page-head[\s\S]*?<\/header>/);
  return lead ? `${lead[0]}${add}${rest.slice(lead[0].length)}` : add + rest;
}

/** 사이드바 작품 카드의 갈래 줄. 갈래는 본편과 제목이 같아 이 줄로 가른다. */
function branchSideTag() {
  const me = branchMe(branchFam());
  return me && me.info.parent ? `<div class="work-branch"><span class="tf" aria-hidden="true">🌿</span>갈래 · ${esc(me.info.label || S.name)} (${me.info.from_ep}화부터)</div>` : '';
}

/** 갈래 만들기 칸. S.branchForm 이 있으면 그 화면 머리 아래에 그린다 (갈래 비교 · 상태 승인 화면 · 작품 홈 버튼이 연다). */
function branchFormCard() {
  const f = S.branchForm;
  if (!f || f.name !== S.name) return '';
  const last = lastFinal();
  const n = Number(f.from) || 1;
  const undo = P().episodes.filter((e) => e.status === 'finalized' && e.plot.number >= n).map((e) => e.plot.number);
  const texts = P().episodes.filter((e) => e.plot.number >= n && e.text).map((e) => e.plot.number);
  const err = f.err || {};
  const errOf = (k) => (err.field === k ? `<div class="small field-err" id="br-${k}-err" role="alert">${esc(err.msg)}</div>` : '');
  const bad = (k) => (err.field === k ? ` aria-invalid="true" aria-describedby="br-${k}-err"` : '');
  const total = P().meta.target_episodes;
  // 화 칸 띠: 함께 쓰는 앞 화 · 갈래가 시작하는 화 · 그 뒤 (칸이 많으면 시작 화 둘레 40칸)
  const from = total > 40 ? Math.max(1, Math.min(n - 19, total - 39)) : 1;
  const cells = [];
  for (let k = from; k <= Math.min(total, from + 39); k += 1) {
    const e = ep(k);
    cells.push(`<li class="${e ? e.status : ''}${k === n ? ' cur' : ''}${k < n ? ' shared' : ''}"><span aria-hidden="true">${k}</span></li>`);
  }
  const shared = n > 1 ? `${n > 2 ? `1~${n - 1}` : '1'}화` : '';
  const mode = (v, title, hint) => `<label class="check-row${(f.mode === 'keep') === (v === 'keep') ? ' on' : ''}"><input type="radio" name="br-mode" value="${v}"${(f.mode === 'keep') === (v === 'keep') ? ' checked' : ''}><span><strong>${title}</strong><br><span class="small">${hint}</span></span></label>`;
  return `<form class="card br-form" id="br-form" aria-labelledby="br-head" novalidate>
    <div class="between"><h2 id="br-head">갈래 만들기</h2><button type="button" class="btn small ghost" data-action="branchClose">닫기</button></div>
    <p class="desc">이 작품을 복사해 다른 전개를 써 봐요. ${shared ? `${shared}는 그대로 복사하고, ` : ''}${n}화부터는 갈래에서만 바뀌어요. 지금 작품은 그대로예요.</p>
    <div class="grid-2">
      <div class="field"><label for="br-label">갈래 이름</label><input id="br-label" type="text" placeholder="예: B안 - 세린이 떠난다" value="${esc(f.label)}"></div>
      <div class="field"><label for="br-from">몇 화부터 다르게 쓸까요 <span class="hint">1~${last + 1}화</span></label><input id="br-from" type="number" min="1" max="${last + 1}" value="${esc(f.from)}"${bad('from')}>${errOf('from')}</div>
    </div>
    <div class="br-cells-wrap"><ol class="br-cells" style="--n:${cells.length}" aria-hidden="true">${cells.join('')}</ol>
      <div class="small">${shared ? `${shared} 함께 · ` : ''}${n}화부터 갈래${undo.length ? ` · ${rangeText(undo)}화 반영을 되돌려 ${n - 1 ? `${n - 1}화 반영 직후` : '1화 시작 전'} 상태로 시작해요` : ''}</div></div>
    <fieldset class="field br-mode"><legend class="label">${n}화부터의 본문${texts.length ? ` · ${rangeText(texts)}화에 본문이 있어요` : ''}</legend>
      ${mode('clear', '비우고 다시 쓰기', '지금 본문은 그 화의 이전 판으로 남아요')}
      ${mode('keep', '남겨 두고 상태 승인부터 다시', '본문을 고쳐 쓰면서 이어 가요')}
    </fieldset>
    <details class="br-folder"${err.field === 'to' ? ' open' : ''}><summary class="small">폴더 이름 · ${esc(f.to)}</summary>
      <div class="field"><label for="br-to">폴더 이름 <span class="hint">주소에 쓰여요</span></label><input id="br-to" type="text" value="${esc(f.to)}"${bad('to')}>${errOf('to')}</div></details>
    <div class="row br-foot"><button type="button" class="btn" data-action="branchClose">취소</button><button type="submit" class="btn primary">${n}화부터 갈래 만들기</button></div>
  </form>`;
}

/** 갈래 이름에서 폴더 이름 기본값: '<지금 폴더>-<갈래 이름>' (home.js folderOf 와 같은 규칙) */
function branchFolder(label) {
  const tail = folderOf(label);
  return folderOf(`${S.name}-${tail || '갈래'}`);
}

function syncBranchForm(el, type) {
  const f = S.branchForm;
  if (!f) return;
  const v = (id) => ($(id) || {}).value || '';
  const mode = $('#br-form input[name="br-mode"]:checked');
  Object.assign(f, { label: v('#br-label'), from: v('#br-from'), mode: mode ? mode.value : 'clear' });
  if (el.id === 'br-to') {
    f.to = v('#br-to');
    f.edited = !!f.to.trim();
  }
  if (el.id === 'br-label' && !f.edited) {
    f.to = branchFolder(f.label);
    $('#br-to').value = f.to;
  }
  const sum = $('#br-form .br-folder summary');
  if (sum) sum.textContent = `폴더 이름 · ${f.to}`;
  if (f.err && el.getAttribute('aria-invalid')) {  // 고치기 시작하면 그 칸의 오류 표시를 걷는다
    el.removeAttribute('aria-invalid');
    const m = $(`#${el.id}-err`);
    if (m) m.remove();
    f.err = null;
  }
  // 안내 글(되돌리는 화 · 비우는 화)을 바꾼다. 치는 동안 다시 그리면 칸이 흔들려서 칸을 떠날 때(change)만 그린다
  if (type === 'change' && (el.name === 'br-mode' || el.id === 'br-from')) render();
}
['input', 'change'].forEach((t) => document.addEventListener(t, (e) => { if (e.target.closest && e.target.closest('#br-form')) syncBranchForm(e.target, t); }));
document.addEventListener('submit', (e) => {
  if (e.target.id !== 'br-form') return;
  e.preventDefault();
  actions.branchCreate();
});

// ----- 작품 목록: 같은 집안을 본편 카드 하나로 묶는다 -----

/** 작품 목록 카드를 집안별로 묶는다. [{card, branches: [{card, depth}]}], 목록 순서(최근에 고친 작품부터)는
    집안에서 가장 최근에 고친 작품 자리를 따른다. 본편을 찾지 못한 갈래는 따로 선 카드로 보인다. */
function branchGroups(list) {
  const fams = {};
  list.forEach((x) => { if (x.branch) (fams[x.branch.family] ||= []).push(x); });
  const out = [];
  const used = new Set();
  list.forEach((x) => {
    if (used.has(x.name)) return;
    const fam = x.branch && fams[x.branch.family];
    const main = fam && fam.find((y) => !y.branch.parent);
    if (!main || fam.length < 2) { used.add(x.name); out.push({ card: x, branches: [] }); return; }
    const kids = (id) => fam.filter((y) => y.branch.parent === id).sort((a, b) => a.branch.from_ep - b.branch.from_ep || a.name.localeCompare(b.name));
    const branches = [];
    const walk = (y, depth) => kids(y.branch.id).forEach((k) => { if (!used.has(k.name)) { used.add(k.name); branches.push({ card: k, depth }); walk(k, depth + 1); } });
    used.add(main.name);
    walk(main, 0);
    out.push({ card: main, branches });
  });
  return out;
}

Object.assign(actions, {
  /** 자동 집필 화면을 목표 화 n 으로 연다. 시작은 그 화면에서 작가가 누른다 (남은 '쓴 화'는 상태 변경안부터 이어 간다, autorun._review) */
  branchResume(n) {
    S.autoForm = { ...autoDefaults(), project: S.name, target: Number(n) };
    location.hash = `${base()}/auto`;
  },
  /** 갈래 만들기 칸을 연다. n 을 주지 않으면 마지막으로 반영한 화부터 (그 화를 다르게 다시 쓰는 흐름) */
  branchOpen(n) {
    const last = lastFinal();
    const from = Number(n) || Math.max(1, last);
    S.branchForm = { name: S.name, from: String(from), label: '', to: branchFolder(''), edited: false, mode: 'clear', err: null };
    S.focusTarget = '#br-label';
    render();
    const f = $('#br-form');
    if (f) f.scrollIntoView({ block: 'start' });
  },
  branchClose() {
    S.branchForm = null;
    S.focusTarget = '#app main [data-action="branchOpen"]';
    render();
  },
  async branchCreate() {
    const f = S.branchForm;
    if (!f) return;
    const fail = (field, msg) => { f.err = { field, msg }; S.focusTarget = `#br-${field}`; render(); };
    const to = (f.to || '').trim();
    const from = Number(f.from);
    const last = lastFinal();
    if (!Number.isInteger(from) || from < 1 || from > last + 1) return fail('from', `시작 화는 1~${last + 1}화 중에 골라 주세요. ${last ? `${last}화까지 반영했어요.` : '아직 반영한 화가 없어요.'}`);
    if (!to) return fail('to', '폴더 이름을 적어 주세요.');
    if (FOLDER_BAD.test(to)) return fail('to', '폴더 이름에 / \\ : * ? " < > | 는 쓸 수 없고, . 으로 시작할 수 없어요.');
    f.err = null;
    let taken = false;
    await run('갈래를 만드는 중', async () => {
      await saveIfDirty();  // 지금 고친 것까지 갈래로 옮긴다
      try {
        await api('POST', `/projects/${enc(S.name)}/branch`, { to, from_ep: from, mode: f.mode, label: f.label.trim() });
      } catch (e) {
        if (e.status !== 409) throw e;
        taken = true;
        return;
      }
      S.branchForm = null;
      toast(`'${f.label.trim() || to}' 갈래를 만들었어요. 지금은 갈래 작품을 보고 있어요`);
      location.hash = `#/p/${enc(to)}/${f.mode === 'keep' ? 'review' : 'write'}/${from}`;
    });
    if (taken) fail('to', '이미 있는 폴더 이름이에요. 다른 이름을 적어 주세요.');  // run 이 포커스를 되돌린 뒤에 칸으로 옮긴다
  },
});

// ----- 갈래 지도: 화 축 위에 집안의 작품마다 한 줄 (작품 홈 갈래 카드 · 갈래 비교 화면이 함께 쓴다) -----

/** 집안 한 줄의 ⋯ 메뉴: 열기 · 본편으로 올리기 · 끊기 */
function branchRowMenu(m, me) {
  const items = [
    me ? '' : `<a class="pop-item" href="#/p/${enc(m.name)}">작품 열기</a>`,
    m.info.parent ? `<button type="button" class="pop-item" data-action="branchPromote" data-arg="${esc(m.name)}">본편으로 올리기</button><button type="button" class="pop-item danger" data-action="branchDetach" data-arg="${esc(m.name)}">갈래 끊기</button>` : '',
  ].join('');
  return items ? menuBtn(`bm-${m.name}`, '⋯', () => items, { cls: 'btn small ghost', aria: `${branchName(m)} 더 보기` }) : '';
}

/** 갈래 지도 줄들. at 은 지금 견주는 화(세로 막대), act(m, me) 는 줄 오른쪽 버튼 */
function branchMapRows(fam, { at = 0, act = () => '' } = {}) {
  const total = Math.max(1, ...fam.members.map((m) => Math.max(m.episodes, m.planned)));
  const pos = (e) => ((e - 1) / total) * 100;  // e화가 시작하는 자리 (%)
  return fam.members.map((m) => {
    const start = m.info.parent ? m.info.from_ep : 1;
    const me = m.name === S.name;
    const name = branchName(m);
    const bars = `${start > 1 ? `<i class="bm-shared" style="width:${pos(start)}%"></i>` : ''}<i class="bm-line" style="left:${pos(start)}%;width:${100 - pos(start)}%"></i>${m.finalized >= start ? `<i class="bm-done" style="left:${pos(start)}%;width:${pos(m.finalized + 1) - pos(start)}%"></i>` : ''}${at ? `<b class="bm-at" style="left:${pos(at) + 50 / total}%"></b>` : ''}`;
    return `<li class="bm-row${me ? ' me' : ''}" style="--depth:${m.depth}">
      <div class="bm-name"><strong>${esc(name)}</strong><span class="small">${m.info.parent ? `${m.info.from_ep}화부터` : '본편'} · ${m.finalized} / ${m.episodes}화 반영</span></div>
      <div class="bm-track" role="img" aria-label="${esc(`${name}: ${start > 1 ? `1~${start - 1}화는 함께 쓰고 ` : ''}${start}화부터 따로, ${m.finalized}화까지 반영`)}">${bars}</div>
      <div class="row bm-acts">${act(m, me)}${branchRowMenu(m, me)}</div></li>`;
  }).join('');
}

const BM_LEGEND = '<div class="bm-legend small" aria-hidden="true"><span><i class="done"></i>반영한 화</span><span><i class="line"></i>쓰는 중 · 계획</span><span><i class="shared"></i>갈라지기 전 함께 쓰는 화</span></div>';

function branchHomeCard() {
  const fam = branchFam();
  if (!fam || fam.members.length < 2) return '';
  const rows = branchMapRows(fam, { act: (m, me) => (me ? '<span class="chip confirmed">지금 작품</span>' : `<a class="btn small" href="${base()}/branches/${enc(m.name)}">비교</a>`) });
  return `<section class="card" aria-labelledby="bm-head">
    <div class="between"><h2 id="bm-head">갈래</h2><a class="small" href="${base()}/branches">갈래 비교</a></div>
    <ul class="bm-list">${rows}</ul>${BM_LEGEND}
    <div class="small">⋯ 에서 본편으로 올리거나 끊어요. 작품 내용과 폴더 이름은 그대로예요.</div>
  </section>`;
}

// ----- 갈래 비교 화면 (#/p/<작품>/branches/<견줄 작품>/<화>) -----

/** 견줄 작품을 고르고 비교를 불러온다. 고르지 않았으면 갈라져 나온 작품, 본편이면 첫 갈래와 견준다. */
async function branchCompareLoad(other, n) {
  S.branchDiff = null;
  const fam = branchFam();
  if (!fam || fam.members.length < 2) return;
  const rest = fam.members.filter((m) => m.name !== S.name);
  const me = branchMe(fam);
  const pick = rest.some((m) => m.name === other) ? other : (rest.find((m) => m.name === me.parent_name) || rest[0]).name;
  const d = await api('GET', `/projects/${enc(S.name)}/compare/${enc(pick)}${n ? `?ep=${n}` : ''}`).catch((e) => ({ error: e.message }));
  S.branchDiff = { ...d, with: pick };
}

const BC_KIND = { character: '인물', tie: '관계', fact: '사실', foreshadow: '복선', time: '시간', setting: '설정' };

const bcParas = (text) => (text || '').split(/\n{2,}/).map((x) => x.trim()).filter(Boolean);

/** 두 본문을 문단으로 맞춘다 (가장 긴 공통 문단 차례). [{ a, b, same }] — 한쪽에만 있는 문단은 반대쪽이 null.
    같은 자리에서 양쪽이 다르면 한 줄에 나란히 둔다 */
function bcParaDiff(ta, tb) {
  const A = bcParas(ta);
  const B = bcParas(tb);
  const L = Array.from({ length: A.length + 1 }, () => new Array(B.length + 1).fill(0));
  for (let i = A.length - 1; i >= 0; i -= 1) for (let j = B.length - 1; j >= 0; j -= 1) L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out = [];
  let i = 0;
  let j = 0;
  let onlyA = [];
  let onlyB = [];
  const flush = () => {
    for (let k = 0; k < Math.max(onlyA.length, onlyB.length); k += 1) out.push({ a: onlyA[k] ?? null, b: onlyB[k] ?? null, same: false });
    onlyA = [];
    onlyB = [];
  };
  while (i < A.length || j < B.length) {
    if (i < A.length && j < B.length && A[i] === B[j]) { flush(); out.push({ a: A[i], b: B[j], same: true }); i += 1; j += 1; } else if (j >= B.length || (i < A.length && L[i + 1][j] >= L[i][j + 1])) { onlyA.push(A[i]); i += 1; } else { onlyB.push(B[j]); j += 1; }
  }
  flush();
  return out;
}

let bcTocCur = null;
let bcTocLast = { fam: null, d: null };

function bcToc(fam = bcTocLast.fam, d = bcTocLast.d) {
  bcTocLast = { fam, d };
  const n = d.episode;
  const secs = [['map', '갈라진 길', ''], ['eps', '화별 줄거리', ''], ['text', `${n}화 본문`, ''], ['state', `${n}화 반영 뒤 상태`, d.ready_a && d.ready_b ? (d.rows.length ? `다름 ${d.rows.length}` : '같음') : '못 견줌', d.rows.length > 0]];
  const cur = secs.find(([k]) => k === bcTocCur) || secs[0];
  const member = (m) => {
    const me = m.name === S.name;
    const tail = m.info.parent ? `${m.info.from_ep}화~` : '본편';
    const pad = ` style="--depth:${m.depth}"`;
    return me
      ? `<div class="outline-item bc-me"${pad}><span class="tl">${esc(branchName(m))}</span><span class="st"><span class="chip confirmed">지금 작품</span></span></div>`
      : `<a class="outline-item bc-mem" href="${base()}/branches/${enc(m.name)}"${pad}${m.name === d.with ? ' aria-current="true"' : ''}><span class="tl">${esc(branchName(m))}</span><span class="st">${tail}</span></a>`;
  };
  const body = `<span class="outline-h">견줄 작품</span>${fam.members.map(member).join('')}<div class="outline-sep"></div><span class="outline-h">이 비교</span>${secs.map(([k, l, st, warn]) => `<button type="button" class="outline-item${warn ? ' warn' : ''}" data-action="bcGo" data-arg="${k}"${k === cur[0] ? ' aria-current="true"' : ''}><span class="tl">${esc(l)}</span><span class="st${warn ? ' warn' : ''}">${esc(st)}</span></button>`).join('')}`;
  const other = fam.members.find((m) => m.name === d.with);
  return outlineNav({ id: 'bc-toc', label: '갈래 비교 목차', now: `${esc(branchName(other))}${josa(branchName(other), '과', '와')} · ${esc(cur[1])}`, body });
}

outlineSpy('bc-toc', {
  targets: () => ['map', 'eps', 'text', 'state'].map((k) => [k, document.getElementById(`bc-${k}`)]),
  set(cur) {
    if (cur === bcTocCur || !bcTocLast.d) return;
    bcTocCur = cur;
    outlineRefresh('bc-toc', bcToc());
  },
});

function viewBranches() {
  const fam = branchFam();
  const formOpen = !!(S.branchForm && S.branchForm.name === S.name);
  const make = lastFinal() ? `<button type="button" class="btn${formOpen ? ' on' : ''}" data-action="${formOpen ? 'branchClose' : 'branchOpen'}" aria-expanded="${formOpen}">갈래 만들기</button>` : '';
  const head = (desc) => header('작품 도구', '갈래 비교', desc, make);
  if (!fam || fam.members.length < 2) {
    const last = lastFinal();
    const first = P().episodes.find((e) => e.status === 'written');
    const go = last
      ? (formOpen ? '' : `<div><button type="button" class="btn primary" data-action="branchOpen">갈래 만들기</button></div>`)
      : first ? `<div><a class="btn primary" href="${base()}/review/${first.plot.number}">${first.plot.number}화 상태 승인하러 가기</a></div>` : '';
    return head('같은 작품을 복사해 n화부터 다른 전개를 쓰는 사본을 갈래라고 해요.')
      + `<div class="card empty"><p>${last ? `아직 갈래가 없어요. ${last}화까지 반영했으니 1~${last + 1}화 중 한 화부터 다르게 써 볼 수 있어요.` : '아직 갈래가 없어요. 1화를 반영해야 갈래를 만들 수 있어요.'}</p>${go}</div>`;
  }
  const d = S.branchDiff;
  if (!d) return head('') + '<div class="card empty"><p>불러오는 중이에요.</p></div>';
  if (d.error) return head('') + `<div class="note err" role="alert">${esc(d.error)}</div>`;
  const other = fam.members.find((m) => m.name === d.with);
  const A = branchName(branchMe(fam));
  const B = branchName(other);
  const n = d.episode;
  const shared = d.from_ep > 1 ? ` ${d.from_ep > 2 ? `1~${d.from_ep - 1}` : '1'}화는 함께 써요.` : '';

  // 갈라진 길: 집안 지도, 지금 견주는 화에 세로 막대
  const map = `<section class="card" id="bc-map" aria-labelledby="bc-map-h"><div class="between"><h2 id="bc-map-h" tabindex="-1">갈라진 길</h2><span class="small">세로 막대는 지금 견주는 ${n}화</span></div>
    <ul class="bm-list">${branchMapRows(fam, { at: n, act: (m, me) => (me ? '<span class="chip confirmed">지금 작품</span>' : m.name === d.with ? '<span class="chip">견주는 중</span>' : `<a class="btn small" href="${base()}/branches/${enc(m.name)}">견주기</a>`) })}</ul>${BM_LEGEND}</section>`;

  // 화별 줄거리: 같은 폭 두 칸. 양쪽 모두 플롯 초안인 화는 줄로 늘어놓지 않는다 (장편은 수백 화)
  const side = (s) => (s ? `<div class="row bc-t"><strong>${esc(s.title || '제목 없음')}</strong><span class="chip ${s.status}">${STATUS[s.status]}</span></div>${s.summary ? `<div class="small bc-sum">${esc(s.summary)}</div>` : ''}` : '<span class="small">없음</span>');
  const started = (e) => [e.a, e.b].some((x) => x && x.status !== 'draft') || e.number === n;
  const idle = d.episodes.filter((e) => !started(e)).map((e) => e.number);
  const epRows = d.episodes.filter(started).map((e) => `<a class="bc-row${e.number === n ? ' on' : ''}" href="${base()}/branches/${enc(d.with)}/${e.number}"${e.number === n ? ' aria-current="true"' : ''}><strong class="bc-n">${e.number}화</strong><div>${side(e.a)}</div><div>${side(e.b)}</div></a>`).join('');
  const eps = `<section class="card" id="bc-eps" aria-labelledby="bc-eps-h"><h2 id="bc-eps-h" tabindex="-1">화별 줄거리</h2>
    <div class="bc-rows"><div class="bc-row head" aria-hidden="true"><span>화</span><span>${esc(A)} · 지금 작품</span><span>${esc(B)}</span></div>${epRows}</div>
    <div class="small">${idle.length ? `${rangeText(idle)}화는 양쪽 모두 플롯 초안이라 뺐어요. ` : ''}줄을 누르면 아래 본문과 상태가 그 화로 바뀌어요.</div></section>`;

  // n화 본문: 문단을 맞춰 나란히. 기본은 다른 문단만
  const nums = d.episodes.map((e) => e.number);
  const prev = nums.filter((x) => x < n).pop();
  const next = nums.find((x) => x > n);
  const stepBtn = (to, label) => (to ? `<a class="btn small" href="${base()}/branches/${enc(d.with)}/${to}">${label}</a>` : '');
  const all = S.bcAll;
  let textBody;
  if (!d.text_a || !d.text_b) {
    const miss = [!d.text_a && [A, S.name], !d.text_b && [B, d.with]].filter(Boolean);
    textBody = `<div class="note plain">${miss.map(([who, name]) => `'${esc(who)}'에 ${n}화 본문이 없어요. <a href="#/p/${enc(name)}/write/${n}">${n}화 집필로</a>`).join('<br>')}</div>`;
  } else {
    const rows = bcParaDiff(d.text_a, d.text_b);
    const same = rows.filter((r) => r.same).length;
    const shown = all ? rows : rows.filter((r) => !r.same);
    // 좁은 칸은 한 줄로 쌓이니 문단마다 어느 쪽인지 적는다 (.bc-who 는 넓은 칸에서 숨긴다)
    const para = (t, cls, who) => (t == null ? '<div class="bc-p none"></div>' : `<p class="bc-p${cls}">${cls ? `<span class="bc-who">${esc(who)}</span>` : ''}${esc(t).replace(/\n/g, '<br>')}</p>`);
    textBody = shown.length
      ? `<div class="bc-pairs"><div class="bc-pair head" aria-hidden="true"><span>${esc(A)} · <a href="${base()}/write/${n}">집필 화면</a></span><span>${esc(B)} · <a href="#/p/${enc(d.with)}/write/${n}">집필 화면</a></span></div>${shown.map((r) => `<div class="bc-pair${r.same ? ' same' : ''}">${para(r.a, r.same ? '' : ' only-a', A)}${para(r.b, r.same ? '' : ' only-b', B)}</div>`).join('')}</div>
        ${!all && same ? `<div class="small">같은 문단 ${same}개를 접었어요. '모두 나란히'로 보면 옅게 보여요.</div>` : ''}`
      : `<div class="note ok">${n}화 본문이 양쪽 모두 같아요.</div>`;
  }
  const seg = `<div class="seg" role="group" aria-label="본문 보기"><button type="button" aria-pressed="${!all}" data-action="bcAll" data-arg="">다른 문단만</button><button type="button" aria-pressed="${!!all}" data-action="bcAll" data-arg="1">모두 나란히</button></div>`;
  const text = `<section class="card" id="bc-text" aria-labelledby="bc-text-h"><div class="between"><h2 id="bc-text-h" tabindex="-1">${n}화 본문</h2><div class="row">${seg}${stepBtn(prev, `‹ ${prev}화`)}${stepBtn(next, `${next}화 ›`)}</div></div>
    ${textBody}<div class="bm-legend small" aria-hidden="true"><span><i class="only-a"></i>${esc(A)}에만 있는 문단</span><span><i class="only-b"></i>${esc(B)}에만 있는 문단</span></div></section>`;

  // n화 반영 뒤 상태: 다른 칸만
  const notReady = [!d.ready_a && A, !d.ready_b && B].filter(Boolean);
  const diffRows = d.rows.map((r) => `<tr><td>${BC_KIND[r.kind]}</td><td>${esc([r.who, r.field].filter(Boolean).join(' · '))}</td><td>${r.a ? esc(r.a) : '<span class="small">없음</span>'}</td><td>${r.b ? esc(r.b) : '<span class="small">없음</span>'}</td></tr>`).join('');
  const stateBody = notReady.length
    ? `<div class="note plain">${notReady.map((x) => `'${esc(x)}'`).join(', ')}에서 ${n}화를 아직 반영하지 않아 상태는 견줄 수 없어요.</div>`
    : d.rows.length
      ? `<div class="rs-scroll"><table class="rs-table bc-table"><thead><tr><th scope="col">구분</th><th scope="col">항목</th><th scope="col">${esc(A)}</th><th scope="col">${esc(B)}</th></tr></thead><tbody>${diffRows}</tbody></table></div>`
      : `<div class="note ok">${n}화 반영 직후 상태가 같아요.</div>`;
  const state = `<section class="card" id="bc-state" aria-labelledby="bc-state-h"><div class="between"><h2 id="bc-state-h" tabindex="-1">${n}화 반영 뒤 상태</h2>${d.rows.length && !notReady.length ? `<span class="small">다른 칸 ${d.rows.length} · 같은 칸은 뺐어요</span>` : ''}</div>${stateBody}</section>`;

  return `${head(`'${esc(A)}'${josa(A, '과', '와')} '${esc(B)}'${josa(B, '은', '는')} ${d.from_ep}화부터 달라요.${shared}`)}
    ${outlineDoc(bcToc(fam, d), `<div class="bc-col">${map}${eps}${text}${state}</div>`, { wide: true, cls: 'bc-wrap' })}`;
}

Object.assign(actions, {
  bcAll(v) {
    S.bcAll = !!v;
    render();
  },
  /** 목차 줄: 그 카드로 옮기고 제목에 포커스 */
  bcGo(k) {
    const el = document.getElementById(`bc-${k}`);
    if (!el) return;
    bcTocCur = k;
    outlineRefresh('bc-toc', bcToc());
    el.scrollIntoView({ block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    document.getElementById(`bc-${k}-h`)?.focus({ preventScroll: true });
  },
  async branchPromote(name) {
    const m = (branchFam() || { members: [] }).members.find((x) => x.name === name);
    if (!m) return;
    const nm = branchName(m);
    if (!(await askConfirm(`'${nm}'${josa(nm, '을', '를')} 본편으로 올릴까요? 갈래 정보만 바뀌고 작품 내용과 폴더 이름은 그대로예요.`, { ok: '본편으로 올리기' }))) return;
    let ok = false;
    await run('본편으로 올리는 중', async () => {
      await api('POST', `/projects/${enc(name)}/promote`);
      ok = true;
      toast(`'${nm}'${josa(nm, '이', '가')} 본편이 됐어요`);
    });
    if (ok) await route();
  },
  async branchDetach(name) {
    const fam = branchFam() || { members: [] };
    const m = fam.members.find((x) => x.name === name);
    if (!m) return;
    const nm = branchName(m);
    const kids = fam.members.filter((x) => x.parent_name === name).map(branchName);
    const up = fam.members.find((x) => x.name === m.parent_name);
    const moved = kids.length && up ? ` 이 갈래에서 갈라진 ${kids.map((k) => `'${k}'`).join(', ')}${josa(kids[kids.length - 1], '은', '는')} '${branchName(up)}'에 다시 이어요.` : '';
    if (!(await askConfirm(`'${nm}' 갈래를 끊을까요? 따로 선 작품이 되고 작품 내용은 그대로예요.${moved}`, { ok: '끊기', danger: true }))) return;
    let ok = false;
    await run('갈래를 끊는 중', async () => {
      await api('POST', `/projects/${enc(name)}/detach`);
      ok = true;
      toast(`'${nm}' 갈래를 끊었어요`);
    });
    if (ok) await route();
  },
});

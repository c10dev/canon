/* 갈래: 같은 작품에서 n화부터 다른 전개를 쓰는 사본 (서버 canon/branches.py, 갈래 정보는 작품 폴더의 branch.json).
   작품 머리 띠(branchStrip), 갈래 만들기 칸(branchFormCard), 작품 목록의 갈래 묶기(branchGroups).
   app.js 의 S, actions, api, render, run 을 그대로 쓴다. */
'use strict';

/** 지금 작품의 갈래 집안 (web.branch_family). 작품을 바꿨거나 작품 홈에 올 때 다시 읽는다. */
async function branchLoad() {
  const name = S.name;
  const fam = await api('GET', `/projects/${enc(name)}/branches`).catch(() => null);
  S.branchFam = fam && { ...fam, name };
}

const branchFam = () => (S.branchFam && S.branchFam.name === S.name ? S.branchFam : null);
const branchMe = (fam) => fam && fam.members.find((m) => m.name === S.name);
// 이름 없는 갈래는 제목이 본편과 같아 폴더 이름으로 부른다
const branchName = (m) => m.info.label || (m.info.parent ? m.name : m.title) || m.name;
/** 마지막으로 반영한 화. 갈래는 1~(이 화+1)화부터 만들 수 있다 (branches.check_fork) */
const lastFinal = () => Math.max(0, ...P().episodes.filter((e) => e.status === 'finalized').map((e) => e.plot.number));

/** 작품 머리 띠: 갈래 작품이면 어느 화면에서든 갈래 이름과 갈라진 곳을 보인다 (다른 갈래를 고치는 줄 헷갈리지 않게).
    본편은 작품 홈에서만 갈래 목록을 보인다. 갈래 만들기 칸도 여기 그린다. */
function branchStrip(page) {
  const fam = branchFam();
  const me = branchMe(fam);
  const form = branchFormCard();
  if (!me || fam.members.length < 2) return form;
  const others = fam.members.filter((m) => m.name !== S.name);
  const link = (m) => `<a href="#/p/${enc(m.name)}">${esc(branchName(m))}</a>${m.info.from_ep ? ` <span class="small">${m.info.from_ep}화부터</span>` : ' <span class="small">본편</span>'}`;
  if (!me.info.parent) {
    if (page) return form;
    return `<div class="note plain branch-strip" role="note"><div><strong>본편</strong> · 갈래 ${others.length}개: ${others.map(link).join(' · ')}</div></div>${form}`;
  }
  const shared = me.info.from_ep > 1 ? `${me.info.from_ep > 2 ? `1~${me.info.from_ep - 1}` : '1'}화` : '';
  const parent = fam.members.find((m) => m.name === me.parent_name);
  const main = fam.members.find((m) => m.name === fam.main);
  const warn = [
    me.shared_edited && shared ? `갈라진 뒤 이 갈래에서 ${shared}를 고쳤어요. 다른 갈래에는 들어가지 않아요.` : '',
    me.parent_edited && shared && parent ? `갈라진 뒤 '${esc(branchName(parent))}'에서 ${shared}를 고쳤어요. 이 갈래에는 들어가지 않아요.` : '',
  ].filter(Boolean);
  return `<div class="note info branch-strip" role="note"><div><strong>갈래 · ${esc(me.info.label || S.name)}</strong> · ${me.info.from_ep}화부터 ${parent ? `'${esc(branchName(parent))}'${josa(branchName(parent), '과', '와')} 달라요` : '갈라졌어요'}${shared ? ` (${shared}는 함께 써요)` : ''}</div>
    <div class="row small">${parent ? `<a href="#/p/${enc(parent.name)}">갈라져 나온 작품 열기</a>` : ''}${main && main !== parent ? `<a href="#/p/${enc(main.name)}">본편 열기</a>` : ''}${others.length > 1 ? `<span>집안: ${others.map(link).join(' · ')}</span>` : ''}</div>
    ${warn.map((w) => `<div>${w}</div>`).join('')}</div>${form}`;
}

/** 사이드바 작품 카드의 갈래 줄. 갈래는 본편과 제목이 같아 이 줄로 가른다. */
function branchSideTag() {
  const me = branchMe(branchFam());
  return me && me.info.parent ? `<div class="small">갈래 · ${esc(me.info.label || S.name)} (${me.info.from_ep}화부터)</div>` : '';
}

/** 갈래 만들기 칸. S.branchForm 이 있으면 그린다 (상태 승인 화면 · 작품 홈 버튼이 연다). */
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
  return `<form class="card" id="br-form" aria-labelledby="br-head" novalidate>
    <div class="between"><h2 id="br-head">갈래 만들기</h2><button type="button" class="btn small ghost" data-action="branchClose">닫기</button></div>
    <p class="desc">이 작품을 복사해 다른 전개를 써 봐요. ${n > 1 ? `${n > 2 ? `1~${n - 1}` : '1'}화는 그대로 복사하고, ` : ''}${n}화부터는 갈래에서만 바뀌어요. 지금 작품은 그대로예요.</p>
    <div class="grid-2">
      <div class="field"><label for="br-label">갈래 이름</label><input id="br-label" type="text" placeholder="예: B안 - 세린이 떠난다" value="${esc(f.label)}"></div>
      <div class="field"><label for="br-from">시작 화 <span class="hint">1~${last + 1}화</span></label><input id="br-from" type="number" min="1" max="${last + 1}" value="${esc(f.from)}"${bad('from')}>${errOf('from')}</div>
      <div class="field"><label for="br-to">폴더 이름 <span class="hint">주소</span></label><input id="br-to" type="text" value="${esc(f.to)}"${bad('to')}>${errOf('to')}</div>
    </div>
    <fieldset class="field"><legend>${n}화부터의 본문</legend>
      <label class="row"><input type="radio" name="br-mode" value="clear"${f.mode === 'keep' ? '' : ' checked'}><span><strong>비우고 다시 쓰기</strong> <span class="small">지금 본문은 그 화의 이전 판으로 남아요</span></span></label>
      <label class="row"><input type="radio" name="br-mode" value="keep"${f.mode === 'keep' ? ' checked' : ''}><span><strong>남겨 두고 상태 승인부터 다시</strong> <span class="small">본문을 고쳐 쓰면서 이어 가요</span></span></label>
    </fieldset>
    ${undo.length || texts.length ? `<div class="note plain">갈래에서는 ${undo.length ? `${rangeText(undo)}화의 상태 반영을 취소해 ${n - 1 ? `${n - 1}화 반영 직후` : '1화 시작 전'} 상태로 돌아가요.` : ''}${texts.length && f.mode !== 'keep' ? ` ${rangeText(texts)}화 본문은 비워요.` : ''}</div>` : ''}
    <div class="row"><button type="submit" class="btn primary">갈래 만들기</button></div>
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

// ----- 작품 홈의 갈래 카드: 화 축 위에 집안의 작품마다 한 줄, 본편으로 · 끊기 -----

function branchHomeCard() {
  const fam = branchFam();
  if (!fam || fam.members.length < 2) return '';
  const total = Math.max(1, ...fam.members.map((m) => Math.max(m.episodes, m.planned)));
  const at = (e) => ((e - 1) / total) * 100;  // e화가 시작하는 자리 (%)
  const rows = fam.members.map((m) => {
    const start = m.info.parent ? m.info.from_ep : 1;
    const me = m.name === S.name;
    const name = branchName(m);
    const bars = `${start > 1 ? `<i class="bm-shared" style="width:${at(start)}%"></i>` : ''}<i class="bm-line" style="left:${at(start)}%;width:${100 - at(start)}%"></i>${m.finalized >= start ? `<i class="bm-done" style="left:${at(start)}%;width:${at(m.finalized + 1) - at(start)}%"></i>` : ''}`;
    const acts = [
      me ? '<span class="chip">지금 작품</span>' : `<a class="btn small" href="#/p/${enc(m.name)}">열기</a><a class="btn small" href="${base()}/branches/${enc(m.name)}">비교</a>`,
      m.info.parent ? `<button type="button" class="btn small" data-action="branchPromote" data-arg="${esc(m.name)}">본편으로</button><button type="button" class="btn small danger" data-action="branchDetach" data-arg="${esc(m.name)}">끊기</button>` : '',
    ].join('');
    return `<li class="bm-row${me ? ' me' : ''}" style="--depth:${m.depth}">
      <div class="bm-name"><strong>${esc(name)}</strong><span class="small">${m.info.parent ? `${m.info.from_ep}화부터` : '본편'} · ${m.finalized} / ${m.episodes}화 반영</span></div>
      <div class="bm-track" role="img" aria-label="${esc(`${name}: ${start > 1 ? `1~${start - 1}화는 함께 쓰고 ` : ''}${start}화부터 따로, ${m.finalized}화까지 반영`)}">${bars}</div>
      <div class="row bm-acts">${acts}</div></li>`;
  }).join('');
  return `<section class="card" aria-labelledby="bm-head">
    <div class="between"><h2 id="bm-head">갈래</h2><a class="small" href="${base()}/branches">갈래 비교</a></div>
    <ul class="bm-list">${rows}</ul>
    <div class="small">진한 칸은 반영한 화, 점선은 갈라지기 전에 함께 쓰는 화예요. 본편으로 올리거나 끊어도 작품 내용과 폴더 이름은 그대로예요.</div>
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

function bcParas(text) {
  return text.split(/\n{2,}/).map((x) => `<p>${esc(x).replace(/\n/g, '<br>')}</p>`).join('');
}

function viewBranches() {
  const fam = branchFam();
  const head = (desc) => header('작품 도구', '갈래 비교', desc, `<a class="btn" href="${base()}">작품 홈</a>${lastFinal() ? '<button type="button" class="btn" data-action="branchOpen">갈래 만들기</button>' : ''}`);
  if (!fam || fam.members.length < 2) {
    return head('같은 작품을 복사해 n화부터 다른 전개를 쓰는 사본을 갈래라고 해요.')
      + `<div class="card empty"><p>아직 갈래가 없어요. ${lastFinal() ? '위의 \'갈래 만들기\'나 상태 승인 화면에서 만들 수 있어요.' : '1화를 반영한 뒤에 만들 수 있어요.'}</p></div>`;
  }
  const d = S.branchDiff;
  if (!d) return head('') + '<div class="card empty"><p>불러오는 중이에요.</p></div>';
  if (d.error) return head('') + `<div class="note err" role="alert">${esc(d.error)}</div>`;
  const other = fam.members.find((m) => m.name === d.with);
  const A = branchName(branchMe(fam));
  const B = branchName(other);
  const n = d.episode;
  const shared = d.from_ep > 1 ? ` ${d.from_ep > 2 ? `1~${d.from_ep - 1}` : '1'}화는 함께 써요.` : '';
  const picker = `<div class="field" style="max-width:360px"><label for="bc-with">견줄 작품</label><select id="bc-with">${fam.members.filter((m) => m.name !== S.name).map((m) => `<option value="${esc(m.name)}"${m.name === d.with ? ' selected' : ''}>${esc(branchName(m))} (${m.info.parent ? `${m.info.from_ep}화부터` : '본편'})</option>`).join('')}</select></div>`;

  const side = (s) => (s ? `<div><strong>${esc(s.title || '제목 없음')}</strong> <span class="chip ${s.status}">${STATUS[s.status]}</span></div>${s.summary ? `<div class="small bc-sum">${esc(s.summary)}</div>` : ''}` : '<span class="small">없음</span>');
  // 양쪽 모두 플롯 초안인 화는 줄로 늘어놓지 않는다 (장편은 수백 화)
  const started = (e) => [e.a, e.b].some((s) => s && s.status !== 'draft') || e.number === n;
  const idle = d.episodes.filter((e) => !started(e)).map((e) => e.number);
  const epRows = d.episodes.filter(started).map((e) => `<tr${e.number === n ? ' class="on" aria-current="true"' : ''}>
      <th scope="row"><a href="${base()}/branches/${enc(d.with)}/${e.number}">${e.number}화</a></th><td>${side(e.a)}</td><td>${side(e.b)}</td></tr>`).join('');

  const text = (who, name, t) => `<section class="bc-col" aria-label="${esc(`${who} ${n}화 본문`)}"><h3>${esc(who)} · ${n}화</h3>${t ? `<div class="bc-text">${bcParas(t)}</div>` : `<div class="small">본문이 없어요. <a href="#/p/${enc(name)}/write/${n}">${n}화 집필로</a></div>`}</section>`;

  const notReady = [!d.ready_a && A, !d.ready_b && B].filter(Boolean);
  const diffRows = d.rows.map((r) => `<tr><td>${BC_KIND[r.kind]}</td><td>${esc([r.who, r.field].filter(Boolean).join(' · '))}</td><td>${r.a ? esc(r.a) : '<span class="small">없음</span>'}</td><td>${r.b ? esc(r.b) : '<span class="small">없음</span>'}</td></tr>`).join('');
  const state = notReady.length
    ? `<div class="note plain">${notReady.map((x) => `'${esc(x)}'`).join(', ')}에서 ${n}화를 아직 반영하지 않아 상태는 견줄 수 없어요.</div>`
    : d.rows.length
      ? `<div class="rs-scroll"><table class="rs-table bc-table"><thead><tr><th scope="col">구분</th><th scope="col">항목</th><th scope="col">${esc(A)}</th><th scope="col">${esc(B)}</th></tr></thead><tbody>${diffRows}</tbody></table></div>`
      : `<div class="note ok">${n}화 반영 직후 상태가 같아요.</div>`;

  return `${head(`'${esc(A)}'${josa(A, '과', '와')} '${esc(B)}'${josa(B, '은', '는')} ${d.from_ep}화부터 달라요.${shared}`)}
    ${picker}
    <section class="card"><h2>화별 줄거리</h2><div class="rs-scroll"><table class="rs-table bc-table bc-eps"><thead><tr><th scope="col">화</th><th scope="col">${esc(A)}</th><th scope="col">${esc(B)}</th></tr></thead><tbody>${epRows}</tbody></table></div>
      <div class="small">${idle.length ? `${rangeText(idle)}화는 양쪽 모두 플롯 초안이라 빼고 보여요. ` : ''}화를 누르면 아래에 그 화 본문과 상태가 나와요.</div></section>
    <section class="card"><h2>${n}화 본문</h2><div class="grid-2 bc-texts">${text(A, S.name, d.text_a)}${text(B, d.with, d.text_b)}</div></section>
    <section class="card"><h2>${n}화 반영 직후 상태</h2>${state}</section>`;
}

document.addEventListener('change', (e) => {
  if (e.target.id !== 'bc-with') return;
  location.hash = `${base()}/branches/${enc(e.target.value)}${S.branchDiff ? `/${S.branchDiff.episode}` : ''}`;
});

Object.assign(actions, {
  async branchPromote(name) {
    const m = (branchFam() || { members: [] }).members.find((x) => x.name === name);
    if (!m) return;
    const nm = branchName(m);
    if (!confirm(`'${nm}'${josa(nm, '을', '를')} 본편으로 올릴까요? 갈래 정보만 바뀌고 작품 내용과 폴더 이름은 그대로예요.`)) return;
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
    if (!confirm(`'${nm}' 갈래를 끊을까요? 따로 선 작품이 되고 작품 내용은 그대로예요.${moved}`)) return;
    let ok = false;
    await run('갈래를 끊는 중', async () => {
      await api('POST', `/projects/${enc(name)}/detach`);
      ok = true;
      toast(`'${nm}' 갈래를 끊었어요`);
    });
    if (ok) await route();
  },
});

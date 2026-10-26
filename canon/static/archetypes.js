/* 원형 도감. app.js 의 S, actions, api, run, render, esc, P, enc, base, markDirty, toast 를 쓴다.
   설정 화면 인물 카드의 '도감에서 고르기'(dexField: 원형 카드 고르기 → 비틀기 · 상처 · 말투 틀 고르기 → 빈 칸에 넣기)와
   인물 칸 머리의 '도감 주사위'(dexRollBox: 원형 + 상처 + 말투 + 비틀기 + 이름을 섞은 3안 → 새 인물로 추가).
   빈 칸 채우기는 서버 archetypes.fill 이 한다 (POST /api/archetypes/fill). 장르로 거르는 dexMatch 는 archetypes.match 와,
   고른 원형 기록 dexRemember 는 archetypes.remember 와 같은 규칙이라 함께 고친다. */
'use strict';

/** 도감 목록 (한 번만 받는다). */
async function dexLoad() {
  if (!S.dex) S.dex = await api('GET', '/archetypes').catch(() => null);
}

const dexById = (id) => ((S.dex && S.dex.archetypes) || []).find((a) => a.id === id);
const dexPickOf = (cid) => (P().cast_archetypes || []).find((x) => x.character_id === cid);

/** 작품 장르에 맞는 원형: 장르가 겹치는 것 먼저, 모든 장르용은 뒤에. 장르를 고르지 않았거나 '모든 장르'면 전부 (archetypes.match). */
function dexMatch(all) {
  const list = (S.dex && S.dex.archetypes) || [];
  const gs = P().meta.genres || [];
  if (all || !gs.length) return list;
  return [...list.filter((a) => a.genres.length && a.genres.some((g) => gs.includes(g))), ...list.filter((a) => !a.genres.length)];
}

/** 인물마다 원형 하나. 원형을 바꾸면 전 비틀기는 지우고, 비틀기를 새로 고르지 않았으면 전 것을 둔다 (archetypes.remember). */
function dexRemember(cid, aid, twist) {
  const p = P();
  p.cast_archetypes = p.cast_archetypes || [];
  const old = dexPickOf(cid);
  if (!old) { p.cast_archetypes.push({ character_id: cid, archetype: aid, twist: twist || '' }); return; }
  if (old.archetype !== aid) old.twist = '';
  old.archetype = aid;
  old.twist = twist || old.twist;
}

// ----- 인물 카드 -----

/** 고른 원형 칩 + 도감 버튼, 열려 있으면 고르는 칸. */
function dexField(c) {
  const pick = dexPickOf(c.id);
  const a = pick && dexById(pick.archetype);
  const open = S.dexOpen && S.dexOpen.cid === c.id;
  const chip = a ? `<span class="chip" title="${esc(a.summary)}">원형 · ${esc(a.name)}</span>` : '';
  return `<div class="row" data-dex-row="${esc(c.id)}">${chip}<button type="button" class="btn small${open ? ' ghost' : ''}" data-action="dexToggle" data-arg="${esc(c.id)}" aria-expanded="${open}">${open ? '도감 닫기' : a ? '도감에서 다시 고르기' : '도감에서 고르기'}</button>
    ${a && pick.twist ? `<span class="small">비틀기: ${esc(pick.twist)}</span>` : ''}</div>
    ${open ? dexPanel(c) : ''}`;
}

function dexPanel(c) {
  if (!S.dex) return '<div class="note warn">도감을 불러오지 못했어요. 화면을 새로 고쳐 보세요.</div>';
  const o = S.dexOpen;
  const list = dexMatch(o.all);
  const groups = S.dex.groups.map((g) => [g, list.filter((a) => a.group === g)]).filter(([, l]) => l.length);
  const cards = groups.map(([g, l]) => `<div class="small" style="font-weight:700">${esc(g)}</div>
    <div class="name-picks">${l.map((a) => `<button type="button" class="name-pick dex-pick" data-action="dexPick" data-arg="${esc(a.id)}" aria-pressed="${o.aid === a.id}">${esc(a.name)}<small>${esc(a.summary)}</small></button>`).join('')}</div>`).join('');
  const gs = P().meta.genres || [];
  const filter = gs.length ? `<label class="row small" style="gap:6px"><input type="checkbox" data-dex-all${o.all ? ' checked' : ''}>모든 장르의 원형 보기</label>` : '<span class="small">장르를 고르면 맞는 원형을 먼저 보여 줘요</span>';
  return `<div class="name-picks-box dex-box">
    <div class="between"><span class="small">원형을 고르면 <strong>빈 칸에만</strong> 예시를 넣어요. 쓴 칸은 그대로 둬요.</span>${filter}</div>
    ${cards}
    ${o.aid ? dexDetail(c, dexById(o.aid)) : ''}
  </div>`;
}

/** 고른 원형 카드: 예시 칸, 흔들리는 상황, 피할 것, 시작 관계, 꼭 채울 것 + 비틀기 · 상처 · 말투 고르기. */
function dexDetail(c, a) {
  if (!a) return '';
  const o = S.dexOpen;
  const row = (label, v) => (v ? `<dt>${label}</dt><dd>${esc(v)}</dd>` : '');
  const list = (label, vs) => (vs.length ? `<dt>${label}</dt><dd><ul>${vs.map((v) => `<li>${esc(v)}</li>`).join('')}</ul></dd>` : '');
  const views = a.views.map((v) => `이 인물 → ${esc(v.toward)}: ${esc(v.words.join(', '))}${v.back.length ? ` / ${esc(v.toward)} → 이 인물: ${esc(v.back.join(', '))}` : ''}`);
  const twists = ['', ...a.twists].map((t, i) => `<label class="row small" style="gap:6px;align-items:flex-start"><input type="radio" name="dex-twist" value="${i}"${(o.twist || '') === t ? ' checked' : ''} data-dex-twist="${esc(t)}">${t ? esc(t) : '고르지 않음'}</label>`).join('');
  const gs = P().meta.genres || [];
  const kits = S.dex.speech.filter((s) => !s.genres.length || !gs.length || s.genres.some((g) => gs.includes(g)));
  const wounds = `<option value="">원형 예시 그대로</option>${S.dex.wounds.map((w) => `<option value="${esc(w.id)}"${o.wound === w.id ? ' selected' : ''}>${esc(w.name)} · '${esc(w.belief)}'</option>`).join('')}`;
  const speech = `<option value="">원형 예시 그대로</option>${kits.map((s) => `<option value="${esc(s.id)}"${o.speech === s.id ? ' selected' : ''}>${esc(s.name)} · ${esc(s.sample)}</option>`).join('')}`;
  // 비어 있고 넣을 값이 있는 칸 (archetypes.fill 과 같은 규칙). 비틀기는 아크 칸이 차 있어도 붙는다
  const has = { role: a.role, gender: a.gender, personality: a.personality, goal: a.goal, wound: a.wound || o.wound, speech_style: a.speech || o.speech, secrets: a.secret, arc: a.arc || o.wound };
  const empty = Object.keys(S.dex.fill_labels).filter((k) => has[k] && (k === 'secrets' ? !(c.secrets || []).length : !String(c[k] || '').trim()));
  return `<div class="dex-detail">
    <div class="row"><strong style="font-size:1rem">${esc(a.name)}</strong>${a.aliases.map((x) => `<span class="chip">${esc(x)}</span>`).join('')}</div>
    <div style="font-family:var(--serif)">${esc(a.summary)}</div>
    <dl>${row('원하는 것', a.goal)}${row('결핍', a.wound)}${row('성격', a.personality)}${row('말투', a.speech)}${row('숨기는 것', a.secret)}${row('아크', a.arc)}
      ${list('흔들리는 상황', a.pressure)}${list('피할 것', a.avoid)}${views.length ? `<dt>시작 관계</dt><dd>${views.join('<br>')}<div class="small">관계 칸의 '보는 방식'으로 고르면 돼요</div></dd>` : ''}</dl>
    ${a.must.length ? `<div class="note info">${a.must.map(esc).join('<br>')}</div>` : ''}
    <fieldset class="dex-twists"><legend class="small" style="font-weight:700">비틀어 보기 <span class="hint">고르면 아크 칸 끝에 한 줄로 붙어요</span></legend>${twists}</fieldset>
    <div class="grid-2"><div class="field"><label for="dex-wound">상처 <span class="hint">두려운 것 · 약점 칸</span></label><select id="dex-wound" data-dex-sel="wound">${wounds}</select></div>
      <div class="field"><label for="dex-speech">말투 틀 <span class="hint">말투 칸</span></label><select id="dex-speech" data-dex-sel="speech">${speech}</select></div></div>
    <div class="between"><span class="small">${empty.length ? `채울 빈 칸: ${empty.map((k) => esc(S.dex.fill_labels[k])).join(', ')}` : '채울 빈 칸이 없어요. 원형과 비틀기만 남겨요.'}</span>
      <button type="button" class="btn small primary" data-action="dexUse" data-arg="${esc(c.id)}">빈 칸에 넣기</button></div>
  </div>`;
}

document.addEventListener('change', (e) => {
  const el = e.target;
  if (!S.dexOpen || !el.dataset) return;
  if (el.dataset.dexAll != null) { S.dexOpen.all = el.checked; render(); return; }
  if (el.dataset.dexTwist != null) { S.dexOpen.twist = el.dataset.dexTwist; return; }
  if (el.dataset.dexSel) S.dexOpen[el.dataset.dexSel] = el.value;
});

// ----- 도감 주사위 -----

function dexRollBox() {
  const r = S.dexRolls;
  if (!r || !S.dex) return '';
  const cards = r.list.map((x, i) => {
    const a = dexById(x.archetype) || { name: x.archetype, summary: '' };
    const w = S.dex.wounds.find((y) => y.id === x.wound);
    const s = S.dex.speech.find((y) => y.id === x.speech);
    return `<div class="dex-roll">
      <div class="row"><strong>${esc(x.name || '이름 없음')}</strong><span class="chip">${esc(a.name)}</span></div>
      <div class="small">${esc(a.summary)}</div>
      <div class="small">상처: ${esc(w ? w.name : x.wound)} · 말투: ${esc(s ? `${s.name} "${s.sample}"` : x.speech)}</div>
      ${x.twist ? `<div class="small">비틀기: ${esc(x.twist)}</div>` : ''}
      <div class="row"><button type="button" class="btn small primary" data-action="dexAdd" data-arg="${i}">새 인물로 추가</button>
        <button type="button" class="btn small ghost" data-action="dexReroll" data-arg="${esc(x.archetype)}">이 원형으로 다시</button></div></div>`;
  }).join('');
  return `<div class="name-picks-box">
    <div class="between"><span class="small">원형 · 상처 · 말투 · 비틀기 · 이름을 무작위로 섞었어요${r.archetype ? ` (원형은 ${esc((dexById(r.archetype) || {}).name || r.archetype)} 그대로)` : ''}</span>
      <div class="row"><button type="button" class="btn small" data-action="dexRoll">다시 굴리기</button><button type="button" class="btn small ghost" data-action="dexRollClose">닫기</button></div></div>
    <div class="dex-rolls">${cards}</div></div>`;
}

async function dexRollLoad(archetype) {
  await run('굴리는 중', async () => {
    await dexLoad();
    const list = await api('POST', `/projects/${enc(S.name)}/archetypes/roll`, { n: 3, archetype: archetype || '', meta: P().meta, world: P().world, characters: P().characters });
    S.dexRolls = { list, archetype: archetype || '' };
  });
}

/** 서버가 빈 칸을 채운 인물로 바꾸고 고른 원형을 남긴다. */
async function dexFill(c, req) {
  const r = await api('POST', '/archetypes/fill', { character: c, ...req });
  Object.assign(c, r.character);
  if (req.archetype) dexRemember(c.id, req.archetype, req.twist);
  markDirty();
  return r.filled;
}

const dexFilledText = (filled) => filled.map((k) => S.dex.fill_labels[k] || k).join(', ');

Object.assign(actions, {
  async dexToggle(cid) {
    if (S.dexOpen && S.dexOpen.cid === cid) { S.dexOpen = null; render(); return; }
    await dexLoad();
    const pick = dexPickOf(cid);
    S.dexOpen = { cid, aid: pick ? pick.archetype : '', twist: pick ? pick.twist : '', wound: '', speech: '', all: false };
    render();
  },
  dexPick(aid) {
    if (!S.dexOpen) return;
    const keep = aid === S.dexOpen.aid;
    Object.assign(S.dexOpen, { aid, twist: keep ? S.dexOpen.twist : '' });
    render();
  },
  async dexUse(cid) {
    const c = P().characters.find((x) => x.id === cid);
    const o = S.dexOpen;
    if (!c || !o || !o.aid) return;
    await run('도감에서 채우는 중', async () => {
      const filled = await dexFill(c, { archetype: o.aid, wound: o.wound || '', speech: o.speech || '', twist: o.twist || '' });
      S.dexOpen = null;
      toast(filled.length ? `${dexFilledText(filled)} 칸을 채웠어요` : '채울 빈 칸이 없어 원형만 남겼어요');
    });
  },
  async dexRoll() { await dexRollLoad(S.dexRolls ? S.dexRolls.archetype : ''); },
  async dexReroll(aid) { await dexRollLoad(aid); },
  dexRollClose() { S.dexRolls = null; render(); },
  async dexAdd(i) {
    const x = S.dexRolls && S.dexRolls.list[+i];
    const a = x && dexById(x.archetype);
    if (!a) return;
    actions.addCharacter();
    const c = P().characters[P().characters.length - 1];
    Object.assign(c, { name: x.name || '', role: '', tier: a.tier });
    await run('새 인물을 만드는 중', async () => {
      await dexFill(c, { archetype: x.archetype, wound: x.wound, speech: x.speech, twist: x.twist });
      S.dexRolls.list.splice(+i, 1);
      if (!S.dexRolls.list.length) S.dexRolls = null;
      toast(`새 인물을 넣었어요: ${c.name || c.id}. 칸을 확인해 보세요`);
    });
    if (typeof checkNames === 'function') checkNames();
  },
});

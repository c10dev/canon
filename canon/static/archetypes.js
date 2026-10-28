/* 원형 도감. app.js 의 S, actions, api, run, render, esc, P, enc, base, markDirty, toast 를 쓴다.
   설정 도우미 인물 칸 머리의 '도감 주사위'(dexRollBox: 원형 + 상처 + 말투 + 비틀기 + 이름을 섞은 3안 → 새 인물로 추가).
   빈 칸 채우기는 서버 archetypes.fill 이 한다 (POST /api/archetypes/fill).
   고른 원형 기록 dexRemember 는 archetypes.remember 와 같은 규칙이라 함께 고친다. */
'use strict';

/** 도감 목록 (한 번만 받는다). */
async function dexLoad() {
  if (!S.dex) S.dex = await api('GET', '/archetypes').catch(() => null);
}

const dexById = (id) => ((S.dex && S.dex.archetypes) || []).find((a) => a.id === id);
const dexPickOf = (cid) => (P().cast_archetypes || []).find((x) => x.character_id === cid);

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

Object.assign(actions, {
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

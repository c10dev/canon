/* 반영 뒤 고친 화 (집필 · 상태 승인 화면). app.js 의 S, P, ep, actions, api, render, run, startJob, jobBtn, saveIfDirty, rangeText 와
   passage.js 의 textNow 를 그대로 쓴다.
   반영이 끝난 화도 본문을 고칠 수 있다. 반영된 요약 · 인물 상태 · 관계 · 복선은 그대로 두고(뒤 화가 그 위에 쌓였다),
   서버가 처음 고치기 전 본문을 Episode.final_text 에 남긴다. 작가는 '그대로 두기'를 고르거나, 고친 본문에서 변경안을 다시 뽑아
   요약 · 새 사실 · 새 복선만 골라 반영한다 (pipeline.apply_restate). 인물 상태 · 관계까지 바꾸려면 그 화부터 반영을 취소한다. */
'use strict';

Object.assign(S, {
  rsPick: {},  // 화 → { sum, f0, p0, ... } 다시 맞출 항목 체크
  rsFor: {},   // 화 → 체크를 만든 변경안 (변경안이 바뀌면 체크를 다시 만든다)
});

/** 반영이 끝난 뒤 저장된 본문을 고쳤다 (서버 pipeline.edited_after_final 과 같은 규칙). */
const editedAfterFinal = (e) => !!e && e.status === 'finalized' && !!e.final_text && e.final_text !== e.text;

/** n화 뒤에 본문이 있는 화. 고치기 전 n화를 이어 쓴 화들이다. */
const laterWritten = (n) => P().episodes.filter((x) => x.plot.number > n && x.text).map((x) => x.plot.number).sort((a, b) => a - b);

/** 고친 본문에서 다시 뽑은 변경안 중 이미 있는 것을 뺀 새 사실 · 새 복선. */
function rsItems(n) {
  const d = S.deltas[n];
  const facts = new Set(P().facts);
  const fs = new Set(P().foreshadows.map((f) => f.id));
  return {
    facts: d.new_facts.map((f, i) => ({ f, i })).filter((x) => x.f.trim() && !facts.has(x.f)),
    plants: d.foreshadow_planted.map((f, i) => ({ f, i })).filter((x) => !fs.has(x.f.id)),
  };
}

function rsPicks(n) {
  if (S.rsFor[n] !== S.deltas[n]) {
    const it = rsItems(n);
    S.rsPick[n] = { sum: true, ...Object.fromEntries(it.facts.map((x) => ['f' + x.i, true])), ...Object.fromEntries(it.plants.map((x) => ['p' + x.i, true])) };
    S.rsFor[n] = S.deltas[n];
  }
  return S.rsPick[n];
}

/** 집필 화면 위 안내: 반영 뒤 고쳤으면 다시 맞추기 · 그대로 두기, 뒤 화가 있으면 검수 권유. */
function restateNote(n) {
  const e = ep(n);
  if (!e || e.status !== 'finalized') return '';
  const later = laterWritten(n);
  const next = later.length ? ` 뒤 화(${rangeText(later)}화)는 고치기 전 본문을 이어 썼어요. 이어지는 장면이 걸리면 <a href="${base()}/write/${later[0]}">${later[0]}화</a>를 검수해 보세요.` : '';
  if (!editedAfterFinal(e)) {
    return `<div class="note plain">상태 반영이 끝난 화예요. 본문을 고쳐도 반영된 요약 · 인물 상태 · 복선은 그대로 남아요. 고친 뒤 요약과 새 사실만 다시 맞출 수 있어요.</div>`;
  }
  return `<div class="note warn">반영한 뒤 본문을 고쳤어요. 요약 · 인물 상태 · 복선은 고치기 전 본문으로 반영한 거예요.${next}
    <div class="row" style="margin-top:6px"><a class="btn small primary" href="${base()}/review/${n}">상태 다시 맞추기</a><button type="button" class="btn small" data-action="keepState" data-arg="${n}"${autoOn() ? ' disabled' : ''}>그대로 두기</button></div></div>`;
}

/** 상태 승인 화면(반영 완료 화) 위 카드. 변경안이 없으면 다시 뽑기, 있으면 요약 · 새 사실 · 새 복선을 골라 반영. */
function restateCard(n) {
  const e = ep(n);
  if (!editedAfterFinal(e)) return '';
  const d = S.deltas[n];
  const later = laterWritten(n);
  const intro = `<p class="desc">${n}화는 반영한 뒤 본문을 고쳤어요. 인물 상태 · 관계 · 비밀은 ${later.length ? `뒤 화(${rangeText(later)}화)가 그 위에 쌓아서 ` : ''}여기서 바꾸지 않아요. 고친 본문에서 변경안을 다시 뽑아 요약 · 새 사실 · 새 복선만 골라 반영할 수 있어요. 인물 상태까지 바꿔야 하면 아래 '${n}화부터 반영 취소'를 쓰세요.</p>`;
  if (!d) {
    return `<section class="card"><h2>고친 본문으로 다시 맞추기</h2>${intro}
      <div class="row">${((b) => `<button class="btn primary" data-action="restateEp" data-arg="${n}"${b.attr}>${b.label}</button>`)(jobBtn('state', n, '고친 본문에서 다시 뽑기'))}
      <button type="button" class="btn" data-action="keepState" data-arg="${n}"${autoOn() ? ' disabled' : ''}>그대로 두기 (오타 · 문장만 고침)</button></div></section>`;
  }
  const pk = rsPicks(n);
  const it = rsItems(n);
  const box = (k, label) => `<div class="change"><input type="checkbox" id="rs-${n}-${k}" data-rs-pick="${n}:${k}"${pk[k] ? ' checked' : ''}><label for="rs-${n}-${k}" style="font-size:0.8125rem;line-height:1.55">${label}</label></div>`;
  const skipped = [['인물 상태', d.character_updates], ['관계 사건', d.events], ['관계 유형', d.relationship_updates], ['새 비밀', d.secrets_added], ['복선 회수', d.foreshadow_resolved], ['새 인물', d.new_characters || []]]
    .filter(([, l]) => l.length).map(([k, l]) => `${k} ${l.length}건`);
  return `<section class="card"><h2>고친 본문으로 다시 맞추기</h2>${intro}
    <div class="field"><span class="small">요약</span>
      ${e.summary && e.summary !== d.summary ? `<div class="small">지금: ${esc(e.summary)}</div>` : ''}
      <div class="change"><input type="checkbox" id="rs-${n}-sum" data-rs-pick="${n}:sum"${pk.sum ? ' checked' : ''}><label for="rs-${n}-sum" class="small">새 요약으로 바꾸기</label></div>
      <textarea rows="4" data-rs-summary="${n}" aria-label="${n}화 새 요약">${esc(d.summary)}</textarea></div>
    <div class="field"><span class="small">새 사실 ${it.facts.length}</span>${it.facts.length ? it.facts.map((x) => box('f' + x.i, esc(x.f))).join('') : '<div class="small">새로 나온 사실이 없어요.</div>'}</div>
    <div class="field"><span class="small">새 복선 ${it.plants.length}</span>${it.plants.length ? it.plants.map((x) => box('p' + x.i, `심음: ${esc(x.f.description)}`)).join('') : '<div class="small">새로 심은 복선이 없어요.</div>'}</div>
    ${skipped.length ? `<div class="note plain">반영하지 않는 항목: ${skipped.join(', ')}. 뒤 화가 이미 그 상태로 쓰였어요.</div>` : ''}
    ${(d.warnings || []).length ? `<div class="note warn">${d.warnings.map(esc).join('<br>')}</div>` : ''}
    <div class="row">${((b) => `<button class="btn" data-action="restateEp" data-arg="${n}"${b.attr}>${b.label}</button>`)(jobBtn('state', n, '다시 뽑기'))}<button class="btn" data-action="dropDelta" data-arg="${n}">버리기</button></div>
    <div class="apply-bar"><span class="small">고른 것만 반영하고 반영 뒤 고침 표시를 지워요</span>
      <button class="btn primary" data-action="applyRestate" data-arg="${n}"${autoOn() ? ' disabled' : ''}>선택한 항목 반영</button></div></section>`;
}

document.addEventListener('change', (e) => {
  const t = e.target;
  if (!t.dataset || !t.dataset.rsPick) return;
  const [n, k] = t.dataset.rsPick.split(':');
  rsPicks(Number(n))[k] = t.checked;
});

document.addEventListener('input', (e) => {
  const t = e.target;
  if (!t.dataset || t.dataset.rsSummary === undefined) return;
  const d = S.deltas[Number(t.dataset.rsSummary)];
  if (d) d.summary = t.value;
});

Object.assign(actions, {
  async restateEp(n) {
    n = Number(n);
    await saveIfDirty();
    await startJob('state', n);
  },
  async applyRestate(n) {
    n = Number(n);
    const d = S.deltas[n];
    if (!d) return;
    const pk = rsPicks(n);
    const body = {
      ...d,
      summary: pk.sum ? d.summary : '',
      new_facts: d.new_facts.filter((_, i) => pk['f' + i]),
      foreshadow_planted: d.foreshadow_planted.filter((_, i) => pk['p' + i]),
    };
    return run('반영하는 중', async () => {
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/restate`, body);
      delete S.deltas[n];
      delete S.deltaBase[n];
      const what = [pk.sum && d.summary.trim() ? '요약' : '', body.new_facts.length ? `새 사실 ${body.new_facts.length}건` : '', body.foreshadow_planted.length ? `새 복선 ${body.foreshadow_planted.length}건` : ''].filter(Boolean);
      toast(what.length ? `${n}화 ${what.join(', ')}을 반영했어요` : `${n}화 반영 뒤 고침 표시를 지웠어요`);
    });
  },
  async keepState(n) {
    n = Number(n);
    return run('저장하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/keep-state`);
      delete S.deltas[n];
      toast(`${n}화 상태는 그대로 둘게요`);
    });
  },
});

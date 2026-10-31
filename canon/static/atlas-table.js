/* 어디에 있었나 표와 장소와 맞지 않은 위치 (atlas.js 에서 뗐다). app.js 의 S, actions, api, run, render, esc 와
   atlas.js 의 atlasChars · atlasRow · atlasPlace · atlasKnown · atlasSwatch · atlasToggles · atlasLoad 를 쓴다.
   위치 글 잇기의 AI 제안은 서버 pipeline.sort_places, 적용은 atlas.apply_sort. */
'use strict';

// ----- 어디에 있었나 표 -----

function atlasTable() {
  const all = S.atlas.frames.map((f, i) => [f, i]);
  // 시작(1화 전) 칸은 그때 위치가 적힌 인물이 있을 때만 보인다
  const fs = all.filter(([f]) => f.episode || f.rows.some((r) => r.location));
  const chars = atlasChars();
  if (!chars.length) return '<div class="card empty"><p>위치가 기록된 인물이 아직 없어요.</p><div class="small">상태 승인에서 인물 위치(location)를 반영하면 화별로 쌓여요.</div></div>';
  const head = `<tr><th scope="col">인물</th>${fs.map(([f, i]) => `<th scope="col"${i === S.atlasFrame ? ' class="cur"' : ''}><button type="button" class="linkish" data-action="atlasGo" data-arg="${i}" title="${esc(frameLabel(f))} 지도로">${f.episode ? f.episode + '화' : '시작'}</button></th>`).join('')}</tr>`;
  const body = chars.map((c) => {
    let last = null;
    const cells = fs.map(([f, i]) => {
      const r = atlasRow(f, c.id);
      const pl = r && r.place ? atlasPlace(r.place) : null;
      const text = pl ? pl.name : r && r.location ? r.location : '';
      const fog = pl && S.atlasFog && !atlasKnown(pl, f);
      const shown = fog ? '?' : text;
      const same = text && text === last;
      last = text || last;
      const cls = [i === S.atlasFrame ? 'cur' : '', same ? 'same' : text ? 'moved' : '', pl ? '' : 'raw'].filter(Boolean).join(' ');
      return `<td class="${cls}" title="${esc(r && r.location ? r.location : '')}">${esc(shown.length > 10 ? shown.slice(0, 10) + '…' : shown)}</td>`;
    }).join('');
    return `<tr><th scope="row">${atlasSwatch(c.id)}${esc(c.name || c.id)}</th>${cells}</tr>`;
  }).join('');
  return `<section class="card"><div class="between"><h2>어디에 있었나</h2>${atlasToggles(false)}</div>
    <div class="small">반영한 화마다 인물이 있던 곳이에요. 진한 칸은 장소가 바뀐 화, 흐린 칸은 앞 화와 같은 곳, 기울인 글은 장소와 맞지 않은 위치 글이에요. 화를 누르면 그 시점 지도로 가요.</div>
    <div class="at-table-wrap"><table class="at-table">${head}${body}</table></div></section>`;
}

// ----- 장소와 맞지 않은 위치: 골라서 한 번에 잇기, AI 제안 -----

/** 위치 글마다 고른 값. v: 장소 키 | '-'(그리지 않음) | 'new:이름'(AI가 제안한 새 장소), on: 적용할 글 */
function atlasDraft(text) {
  S.atlasDraft = S.atlasDraft || {};
  return S.atlasDraft[text] || (S.atlasDraft[text] = { v: '', on: false });
}

function atlasPicked() {
  const list = S.atlas.unmatched || [];
  return list.filter((u) => { const d = atlasDraft(u.text); return d.on && d.v; });
}

function atlasUnmatched() {
  const list = S.atlas.unmatched || [];
  const links = S.atlas.links || [];
  if (!list.length && !links.length) return '';
  const fresh = (S.atlasNew || []).filter((x) => list.some((u) => atlasDraft(u.text).v === 'new:' + x.name));
  const opts = (sel) => `<option value="">장소 고르기</option>${(S.atlas.places || []).map((pl) => `<option value="${esc(pl.key)}"${sel === pl.key ? ' selected' : ''}>${esc(pl.name)}</option>`).join('')}`
    + fresh.map((x) => `<option value="${esc('new:' + x.name)}"${sel === 'new:' + x.name ? ' selected' : ''}>새 장소: ${esc(x.name)}</option>`).join('')
    + `<option value="-"${sel === '-' ? ' selected' : ''}>지도에 그리지 않음</option>`;
  const rows = list.map((u, i) => {
    const d = atlasDraft(u.text);
    return `<div class="at-um${d.on ? ' on' : ''}">
      <input type="checkbox" data-at-on="${i}" aria-label="${esc(u.text)} 고르기"${d.on ? ' checked' : ''}>
      <div class="at-um-text"><strong>${esc(u.text)}</strong><div class="small">${u.characters.map((c) => esc(charName(c))).join(', ')} · ${u.episodes.map((n) => (n ? n + '화' : '시작')).join(', ')}</div>
        ${d.note ? `<div class="small at-um-note">AI: ${esc(d.note)}</div>` : ''}</div>
      <select data-at-um="${i}" aria-label="${esc(u.text)} 장소">${opts(d.v)}</select></div>`;
  }).join('');
  const done = links.map((ln, i) => `<li>${esc(ln.text)} → ${ln.place ? esc((atlasPlace(ln.place) || { name: ln.place }).name) : '지도에 그리지 않음'} <button type="button" class="btn small ghost" data-action="atlasUnlink" data-arg="${i}">풀기</button></li>`).join('');
  const picked = atlasPicked().length;
  const all = list.length && list.every((u) => atlasDraft(u.text).on);
  const newBox = fresh.length ? `<div class="at-box"><h3>함께 등록할 새 장소 (${fresh.length})</h3>
      <div class="small">고른 위치 글이 이 장소를 쓰면 적용할 때 인과율 '장소'로 등록해요. 이름이나 설명은 인과율에서 고칠 수 있어요.</div>
      <ul class="at-list">${fresh.map((x) => `<li><strong>${esc(x.name)}</strong>${x.kind ? ` · ${esc(x.kind)}` : ''}${x.description ? ` · ${esc(x.description)}` : ''} <span class="small">(${x.first_ep ? x.first_ep + '화부터' : '처음부터'})</span></li>`).join('')}</ul></div>` : '';
  return `<section class="card" id="at-unmatched"><h2>장소와 맞지 않은 위치 (${list.length})</h2>
    <div class="small">상태 변경안이 적은 인물 위치에 장소 이름이 없으면 지도에 그리지 못해요. 장소에 이어 두면 같은 글은 다음부터 그 장소로 그려요.</div>
    ${list.length ? `<div class="row"><button type="button" class="btn primary" data-action="atlasSort">AI로 한 번에 정리</button>
      <span class="small">AI가 화별 요약을 보고 위치 글마다 장소를 골라 채워요. 없는 장소는 새 장소로 제안해요. 확인하고 고른 것만 적용해요.</span></div>
    ${newBox}
    <div class="at-um-bar">
      <label><input type="checkbox" data-at-all${all ? ' checked' : ''}> 모두 고르기</label>
      <span class="row">고른 글의 장소를 <select id="at-um-bulk" aria-label="고른 위치 글을 이을 장소">${opts('')}</select><button type="button" class="btn small" data-action="atlasBulk">바꾸기</button></span>
      <button type="button" class="btn primary" data-action="atlasApply" id="at-um-apply"${picked ? '' : ' disabled'}>고른 ${picked}개 적용</button>
    </div>
    <div class="at-um-list">${rows}</div>` : ''}
    ${links.length ? `<details><summary class="small">이어 둔 위치 글 (${links.length})</summary><ul class="at-list">${done}</ul></details>` : ''}</section>`;
}

/** 고른 수만 다시 쓴다 (목록을 다시 그리면 굴린 자리를 잃는다) */
function atlasPickCount() {
  const b = $('#at-um-apply');
  if (!b) return;
  const n = atlasPicked().length;
  b.textContent = `고른 ${n}개 적용`;
  b.disabled = !n;
}

function atlasRerenderUnmatched() {
  const el = $('#at-unmatched');
  if (!el) { render(); return; }
  const list = el.querySelector('.at-um-list');
  const top = list ? list.scrollTop : 0;
  el.outerHTML = atlasUnmatched();
  const again = document.querySelector('#at-unmatched .at-um-list');
  if (again) again.scrollTop = top;
}

Object.assign(actions, {
  async atlasSort() {
    const list = S.atlas.unmatched || [];
    await run(`AI가 위치 글 ${list.length}개를 정리하는 중`, async () => {
      await saveIfDirty();
      const r = await api('POST', `/projects/${enc(S.name)}/atlas/sort`, {});
      S.atlasNew = r.new_places || [];
      let filled = 0;
      for (const row of r.rows || []) {
        const v = row.place || (row.new_place ? 'new:' + row.new_place : row.skip ? '-' : '');
        const d = atlasDraft(row.text);
        d.note = row.note || '';
        if (!v || d.v) continue;  // 작가가 이미 고른 글은 덮지 않는다
        d.v = v;
        d.on = true;
        filled++;
      }
      const empty = list.filter((u) => !atlasDraft(u.text).v).length;
      toast(filled ? `${filled}개를 채웠어요. 확인하고 '적용'을 누르세요${empty ? `. ${empty}개는 AI가 정하지 못했어요` : ''}` : 'AI가 새로 채운 위치 글이 없어요', !filled);
    });
  },
  atlasBulk() {
    const v = $('#at-um-bulk').value;
    if (!v) { toast('바꿀 장소를 고르세요', true); return; }
    const sel = (S.atlas.unmatched || []).filter((u) => atlasDraft(u.text).on);
    if (!sel.length) { toast('먼저 위치 글을 고르세요', true); return; }
    sel.forEach((u) => { atlasDraft(u.text).v = v; });
    atlasRerenderUnmatched();
  },
  async atlasApply() {
    const picks = atlasPicked().map((u) => {
      const v = atlasDraft(u.text).v;
      return { text: u.text, place: v === '-' || v.startsWith('new:') ? '' : v, new_place: v.startsWith('new:') ? v.slice(4) : '' };
    });
    if (!picks.length) return;
    const used = new Set(picks.map((x) => x.new_place).filter(Boolean));
    const fresh = (S.atlasNew || []).filter((x) => used.has(x.name));
    await run('잇는 중', async () => {
      await saveIfDirty();
      const r = await api('POST', `/projects/${enc(S.name)}/atlas/sort/apply`, { picks, new_places: fresh });
      S.project = r.project;
      picks.forEach((x) => { delete S.atlasDraft[x.text]; });
      S.atlasNew = (S.atlasNew || []).filter((x) => !used.has(x.name));
      await atlasLoad();
      toast(`${r.linked}개를 이었어요${r.added.length ? ` · 새 장소 ${r.added.length}곳을 등록했어요 (지도에 놓아 주세요)` : ''}`);
    });
  },
  async atlasUnlink(i) {
    const ln = S.atlas.links[Number(i)];
    if (!ln) return;
    await run('푸는 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/atlas/links`, { text: ln.text, place: null });
      await atlasLoad();
      toast('잇기를 풀었어요');
    });
  },
});

document.addEventListener('change', (e) => {
  const t = e.target;
  if (t.matches('[data-at-um]')) {
    const u = S.atlas.unmatched[Number(t.dataset.atUm)];
    const d = atlasDraft(u.text);
    d.v = t.value;
    d.on = !!t.value;
    const box = t.closest('.at-um');
    box.classList.toggle('on', d.on);
    box.querySelector('[data-at-on]').checked = d.on;
    atlasPickCount();
    return;
  }
  if (t.matches('[data-at-on]')) {
    const d = atlasDraft(S.atlas.unmatched[Number(t.dataset.atOn)].text);
    d.on = t.checked;
    t.closest('.at-um').classList.toggle('on', d.on);
    atlasPickCount();
    return;
  }
  if (t.matches('[data-at-all]')) {
    (S.atlas.unmatched || []).forEach((u) => { atlasDraft(u.text).on = t.checked; });
    atlasRerenderUnmatched();
    return;
  }
});

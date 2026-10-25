/* 지도. app.js 의 S, actions, api, run, render, header, esc, P 와 cast.js 의 frameLabel 을 쓴다.
   장소(설정의 장소 칸, 인과율 '장소' 요소)를 지도 위에 놓고, 화별 인물 자리를 관계도처럼 슬라이더로 재생한다.
   계산값은 서버 canon/atlas.py 의 /atlas 한 번으로 받는다 (places, frames: 화별 인물 자리, unmatched: 장소와 맞지 않은 위치 글).
   장소 자리는 0~1 비율 좌표로 작품에 저장한다 (Project.atlas.pins). 배경 그림은 작품 폴더 map/ 에 파일로 둔다. */
'use strict';

Object.assign(S, {
  atlas: null,       // 서버 계산값
  atlasFrame: 0,     // frames 의 몇 번째 시점
  atlasTab: 'map',   // map | table
  atlasFog: false,   // 독자 시점: 아직 드러나지 않은 장소와 그곳 인물을 가린다
  atlasTrail: true,  // 지나온 길
  atlasMinor: false, // 단역도 보기
  atlasPick: '',     // 지도에 놓으려고 고른 장소 키
  atlasSel: '',      // 자세히 보는 장소 키
  atlasFocus: '',    // 길을 굵게 볼 인물 id
});

const ATLAS_W = 1000;
// 인물 색. 밝은 바탕 · 어두운 바탕 모두에서 흰 글자가 읽히는 중간 밝기
const ATLAS_COLORS = ['#2A63C9', '#C2410C', '#7C3AED', '#0F766E', '#BE185D', '#4D7C0F', '#A16207', '#475569', '#0E7490', '#9F1239'];
let atlasTimer = null;
let atlasDrag = null;
let atlasDragged = false;
let atlasKeyTimer = null;

async function atlasLoad() {
  atlasStop();
  const same = S.atlas && S.atlas.name === S.name;
  const wasLast = same && S.atlasFrame === S.atlas.frames.length - 1;
  S.atlas = await api('GET', `/projects/${enc(S.name)}/atlas`).catch((e) => ({ error: e.message, frames: [], places: [], unmatched: [] }));
  S.atlas.name = S.name;
  if (!same || wasLast || S.atlasFrame >= S.atlas.frames.length) S.atlasFrame = Math.max(0, S.atlas.frames.length - 1);
  if (!same) { S.atlasPick = ''; S.atlasSel = ''; S.atlasFocus = ''; }
}

function atlasStop() {
  if (atlasTimer) clearInterval(atlasTimer);
  atlasTimer = null;
}
window.addEventListener('hashchange', atlasStop);

const atlasH = () => Math.round(ATLAS_W / ((S.atlas && S.atlas.aspect) || 1.5));
const atlasPlace = (key) => (S.atlas.places || []).find((pl) => pl.key === key);
const atlasFrameNow = () => S.atlas.frames[Math.min(S.atlasFrame, S.atlas.frames.length - 1)] || { episode: 0, rows: [], mentioned: [] };
const atlasImageUrl = () => `/api/projects/${enc(S.name)}/atlas/image?v=${enc(S.atlas.image)}`;

/** 이 시점에 독자가 아는 장소인가 (생긴 화, 처음 나온 화, 드러나는 화 중 가장 늦은 화부터) */
function atlasKnown(pl, f) {
  return !pl.known_from || pl.known_from <= f.episode;
}

function atlasChars() {
  const order = ['main', 'support', 'minor'];
  const seen = new Set(S.atlas.frames.flatMap((f) => f.rows.map((r) => r.cid)));
  return P().characters.filter((c) => seen.has(c.id) && (S.atlasMinor || c.tier !== 'minor' || S.atlasFocus === c.id))
    .sort((a, b) => order.indexOf(a.tier) - order.indexOf(b.tier));
}

function atlasColor(cid) {
  const i = P().characters.findIndex((c) => c.id === cid);
  return ATLAS_COLORS[(i < 0 ? 0 : i) % ATLAS_COLORS.length];
}

function atlasRow(f, cid) {
  return f.rows.find((r) => r.cid === cid);
}

// ----- 지도 그림 -----

function atlasSvg() {
  const W = ATLAS_W;
  const H = atlasH();
  const f = atlasFrameNow();
  const out = [];
  if (S.atlas.image) out.push(`<image href="${esc(atlasImageUrl())}" x="0" y="0" width="${W}" height="${H}" preserveAspectRatio="none"></image>`);
  else {
    out.push(`<rect class="at-ground" x="0" y="0" width="${W}" height="${H}"></rect>`);
    for (let x = 100; x < W; x += 100) out.push(`<line class="at-grid" x1="${x}" y1="0" x2="${x}" y2="${H}"></line>`);
    for (let y = 100; y < H; y += 100) out.push(`<line class="at-grid" x1="0" y1="${y}" x2="${W}" y2="${y}"></line>`);
  }
  const xy = (pl) => [pl.pin[0] * W, pl.pin[1] * H];
  const hidden = (pl) => S.atlasFog && !atlasKnown(pl, f);
  const chars = atlasChars();

  // 지나온 길: 시작부터 지금 시점까지 놓인 장소를 차례로 잇는다 (거쳐 온 곳 포함)
  if (S.atlasTrail) {
    chars.forEach((c, ci) => {
      const pts = [];
      S.atlas.frames.slice(0, S.atlasFrame + 1).forEach((fr) => {
        const r = atlasRow(fr, c.id);
        if (!r || !r.place) return;
        [...r.via, r.place].forEach((k) => {
          const pl = atlasPlace(k);
          if (!pl || !pl.pin || hidden(pl)) return;
          if (pts.length && pts[pts.length - 1] === k) return;
          pts.push(k);
        });
      });
      if (pts.length < 2) return;
      const off = ((ci % 5) - 2) * 3;
      const focus = S.atlasFocus === c.id;
      const dim = S.atlasFocus && !focus;
      out.push(`<polyline class="at-trail${dim ? ' dim' : ''}" points="${pts.map((k) => xy(atlasPlace(k)).map((v) => (v + off).toFixed(1)).join(',')).join(' ')}" stroke="${atlasColor(c.id)}" stroke-width="${focus ? 5 : 3}"><title>${esc(c.name || c.id)}: ${esc(pts.map((k) => atlasPlace(k).name).join(' → '))}</title></polyline>`);
    });
  }

  // 장소
  (S.atlas.places || []).filter((pl) => pl.pin && !hidden(pl)).forEach((pl) => {
    const [x, y] = xy(pl);
    const later = !atlasKnown(pl, f);
    const hot = f.episode && f.mentioned.includes(pl.key);
    const sel = S.atlasSel === pl.key;
    const tip = `${pl.name}${pl.description ? ' · ' + pl.description : ''}${later ? `\n${pl.known_from}화부터 독자가 알아요` : ''}${hot ? `\n${f.episode}화에 나와요` : ''}`;
    out.push(`<g class="at-pin${later ? ' later' : ''}${sel ? ' sel' : ''}" data-atlas-pin="${esc(pl.key)}" tabindex="0" role="button" aria-label="${esc(pl.name + ' 자세히 보기. 화살표로 옮겨요')}"><title>${esc(tip)}</title>
      <circle class="at-hit" cx="${x}" cy="${y}" r="20"></circle>
      ${hot ? `<circle class="at-hot" cx="${x}" cy="${y}" r="16"></circle>` : ''}
      <circle class="at-dot" cx="${x}" cy="${y}" r="${sel ? 9 : 7}"></circle>
      <text class="at-name" x="${x}" y="${y - 14}" text-anchor="middle">${esc(pl.name)}</text></g>`);
  });

  // 인물: 같은 장소에 모이면 둘레에 나눠 놓는다
  const groups = {};
  chars.forEach((c) => {
    const r = atlasRow(f, c.id);
    const pl = r && r.place && atlasPlace(r.place);
    if (!pl || !pl.pin || hidden(pl)) return;
    (groups[pl.key] = groups[pl.key] || []).push(c);
  });
  Object.entries(groups).forEach(([k, list]) => {
    const [px, py] = xy(atlasPlace(k));
    list.forEach((c, j) => {
      const a = (j / list.length) * Math.PI * 2 + Math.PI / 4;
      const rr = list.length > 1 ? 18 + list.length * 2 : 0;
      const x = px + 16 + Math.cos(a) * rr;
      const y = py + 16 + Math.sin(a) * rr;
      const dim = S.atlasFocus && S.atlasFocus !== c.id;
      out.push(`<g class="at-tok${dim ? ' dim' : ''}" data-action="atlasFocus" data-arg="${esc(c.id)}"><title>${esc((c.name || c.id) + ': ' + atlasRow(f, c.id).location)}</title>
        <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="12" fill="${atlasColor(c.id)}"></circle>
        <text x="${x.toFixed(1)}" y="${(y + 4.5).toFixed(1)}" text-anchor="middle">${esc([...(c.name || c.id)][0])}</text></g>`);
    });
  });
  return `<svg class="at-map${S.atlasPick ? ' picking' : ''}" viewBox="0 0 ${W} ${H}" role="group" aria-label="${esc(frameLabel(f))} 지도">${out.join('')}</svg>`;
}

// ----- 옆 칸 -----

function atlasWho() {
  const f = atlasFrameNow();
  const prev = S.atlas.frames[S.atlasFrame - 1];
  const items = atlasChars().map((c) => {
    const r = atlasRow(f, c.id);
    let where;
    if (!r || !r.location) where = '<span class="small">위치 기록 없음</span>';
    else if (!r.place) where = `<span class="small" title="장소와 맞지 않은 위치 글이에요. 아래에서 장소에 이을 수 있어요">${esc(r.location)}</span>`;
    else {
      const pl = atlasPlace(r.place);
      where = S.atlasFog && !atlasKnown(pl, f) ? '<span class="small">독자가 아직 모르는 곳</span>' : `<strong>${esc(pl.name)}</strong>${pl.pin ? '' : ' <span class="small">(지도에 안 놓음)</span>'}`;
      const before = prev && atlasRow(prev, c.id);
      const from = r.moved && before && before.place ? atlasPlace(before.place) : null;
      if (from && !(S.atlasFog && !atlasKnown(from, f))) where += ` <span class="small">← ${esc(from.name)}에서 옮김</span>`;
    }
    const on = S.atlasFocus === c.id;
    return `<li><button type="button" class="at-who${on ? ' on' : ''}" data-action="atlasFocus" data-arg="${esc(c.id)}" aria-pressed="${on}"><i style="background:${atlasColor(c.id)}"></i>${esc(c.name || c.id)}</button> ${where}</li>`;
  });
  const hot = f.episode ? f.mentioned.map(atlasPlace).filter((pl) => pl && !(S.atlasFog && !atlasKnown(pl, f))) : [];
  return `<div class="at-box"><h3>${esc(frameLabel(f))}</h3>
      ${items.length ? `<ul class="at-list">${items.join('')}</ul>` : '<div class="small">위치가 기록된 인물이 아직 없어요. 상태 승인에서 인물 위치를 반영하면 쌓여요.</div>'}
      ${hot.length ? `<div class="small">이 화에 나온 장소: ${hot.map((pl) => esc(pl.name)).join(', ')}</div>` : ''}</div>`;
}

function atlasPlaceBox() {
  const pl = S.atlasSel && atlasPlace(S.atlasSel);
  if (!pl) return '';
  const f = atlasFrameNow();
  const here = atlasChars().filter((c) => (atlasRow(f, c.id) || {}).place === pl.key).map((c) => esc(c.name || c.id));
  const when = pl.known_from ? `${pl.known_from}화부터 독자가 알아요` : '처음부터 알려진 곳';
  const src = pl.source === '요소' ? `<a href="${base()}/causal/${enc(pl.key)}">인과율에서 고치기</a>` : `<a href="${base()}/setup">설정의 장소 칸</a>`;
  return `<div class="at-box"><div class="between"><h3>${esc(pl.name)}</h3><button type="button" class="btn small ghost" data-action="atlasSelect" data-arg="">닫기</button></div>
    ${pl.description ? `<p class="small" style="margin:0">${esc(pl.description)}</p>` : ''}
    <div class="small">${esc(when)}${pl.aliases.length ? ` · 다른 이름: ${pl.aliases.map(esc).join(', ')}` : ''}</div>
    ${here.length ? `<div class="small">지금 여기: ${here.join(', ')}</div>` : ''}
    <div class="row">${src}<button type="button" class="btn small ghost" data-action="atlasUnpin" data-arg="${esc(pl.key)}">지도에서 빼기</button></div></div>`;
}

function atlasLoose() {
  const loose = (S.atlas.places || []).filter((pl) => !pl.pin);
  if (!loose.length) return '';
  const picking = S.atlasPick && atlasPlace(S.atlasPick);
  return `<div class="at-box"><h3>아직 안 놓은 장소 (${loose.length})</h3>
    ${picking ? `<div class="note" role="status">지도에서 '${esc(picking.name)}'을(를) 놓을 자리를 누르세요. <button type="button" class="btn small ghost" data-action="atlasPick" data-arg="">그만두기</button></div>` : '<div class="small">장소를 고른 뒤 지도에서 자리를 누르면 놓여요.</div>'}
    <div class="at-chips">${loose.map((pl) => `<button type="button" class="btn small${S.atlasPick === pl.key ? ' primary' : ''}" data-action="atlasPick" data-arg="${esc(pl.key)}" aria-pressed="${S.atlasPick === pl.key}">${esc(pl.name)}</button>`).join('')}</div></div>`;
}

function atlasBackground() {
  return `<div class="at-box"><h3>배경 그림</h3>
    <div class="small">직접 그리거나 다른 도구(Azgaar, Inkarnate 등)로 만든 지도 그림을 올리면 그 위에 장소를 놓아요. PNG · JPG · WEBP, 15MB까지.</div>
    <div class="row"><label class="btn small" for="at-image">${S.atlas.image ? '그림 바꾸기' : '그림 올리기'}</label><input id="at-image" type="file" accept="image/png,image/jpeg,image/webp,image/gif" data-atlas-image hidden>
      ${S.atlas.image ? '<button type="button" class="btn small ghost" data-action="atlasDropImage">그림 지우기</button>' : ''}</div></div>`;
}

function atlasUnmatched() {
  const list = S.atlas.unmatched || [];
  const links = S.atlas.links || [];
  if (!list.length && !links.length) return '';
  const opts = (sel) => `<option value="">장소 고르기</option>${(S.atlas.places || []).map((pl) => `<option value="${esc(pl.key)}"${sel === pl.key ? ' selected' : ''}>${esc(pl.name)}</option>`).join('')}<option value="-">지도에 그리지 않음</option>`;
  const rows = list.map((u, i) => `<div class="at-um">
      <div><strong>${esc(u.text)}</strong><div class="small">${u.characters.map((c) => esc(charName(c))).join(', ')} · ${u.episodes.map((n) => (n ? n + '화' : '시작')).join(', ')}</div></div>
      <div class="row"><select id="at-um-${i}" aria-label="${esc(u.text)} 장소">${opts('')}</select><button type="button" class="btn small" data-action="atlasLink" data-arg="${i}">잇기</button></div></div>`).join('');
  const done = links.map((ln, i) => `<li>${esc(ln.text)} → ${ln.place ? esc((atlasPlace(ln.place) || { name: ln.place }).name) : '지도에 그리지 않음'} <button type="button" class="btn small ghost" data-action="atlasUnlink" data-arg="${i}">풀기</button></li>`).join('');
  return `<section class="card"><h2>장소와 맞지 않은 위치 (${list.length})</h2>
    <div class="small">상태 변경안이 적은 인물 위치에 장소 이름이 없으면 지도에 그리지 못해요. 장소에 이어 두면 같은 글은 다음부터 그 장소로 그려요. 새 장소라면 인과율에서 '장소'로 더하세요.</div>
    ${rows}
    ${links.length ? `<details><summary class="small">이어 둔 위치 글 (${links.length})</summary><ul class="at-list">${done}</ul></details>` : ''}</section>`;
}

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
    return `<tr><th scope="row"><i style="background:${atlasColor(c.id)}"></i>${esc(c.name || c.id)}</th>${cells}</tr>`;
  }).join('');
  return `<section class="card"><div class="between"><h2>어디에 있었나</h2>${atlasToggles(false)}</div>
    <div class="small">반영한 화마다 인물이 있던 곳이에요. 진한 칸은 장소가 바뀐 화, 흐린 칸은 앞 화와 같은 곳, 기울인 글은 장소와 맞지 않은 위치 글이에요. 화를 누르면 그 시점 지도로 가요.</div>
    <div class="at-table-wrap"><table class="at-table">${head}${body}</table></div></section>`;
}

function atlasToggles(map = true) {
  const minors = P().characters.some((c) => c.tier === 'minor');
  return `<div class="row at-toggles">
    ${map ? `<label><input type="checkbox" data-atlas-opt="atlasTrail"${S.atlasTrail ? ' checked' : ''}>지나온 길</label>` : ''}
    <label title="아직 독자에게 드러나지 않은 장소와 그곳에 있는 인물을 가려요"><input type="checkbox" data-atlas-opt="atlasFog"${S.atlasFog ? ' checked' : ''}>독자 시점</label>
    ${minors ? `<label><input type="checkbox" data-atlas-opt="atlasMinor"${S.atlasMinor ? ' checked' : ''}>단역도 보기</label>` : ''}</div>`;
}

function atlasSlider() {
  const fs = S.atlas.frames;
  if (fs.length < 2) return '<div class="small">1화를 반영하면 화별로 인물이 어디로 옮겨 갔는지 재생할 수 있어요.</div>';
  return `<div class="cast-slider">
    <button type="button" class="btn small icon-btn" data-action="atlasStep" data-arg="-1" aria-label="이전 시점">◀</button>
    <input type="range" min="0" max="${fs.length - 1}" value="${S.atlasFrame}" data-atlas-frame aria-label="지도 시점" aria-valuetext="${esc(frameLabel(atlasFrameNow()))}">
    <button type="button" class="btn small icon-btn" data-action="atlasStep" data-arg="1" aria-label="다음 시점">▶</button>
    <button type="button" class="btn small" data-action="atlasPlay" id="atlas-play">${atlasTimer ? '멈춤' : S.atlasFrame >= fs.length - 1 ? '처음부터 재생' : '여기서 재생'}</button>
    <strong id="atlas-frame-label">${esc(frameLabel(atlasFrameNow()))}</strong></div>`;
}

function atlasStage() {
  return `<div class="at-map-wrap">${atlasSvg()}</div>`;
}

function atlasSide() {
  return atlasPlaceBox() + atlasWho() + atlasLoose() + atlasBackground();
}

/** 시점 · 선택만 바뀌면 슬라이더는 두고 지도와 옆 칸만 다시 그린다 (끄는 중인 슬라이더를 지우지 않게) */
function atlasRefresh() {
  const stage = document.getElementById('atlas-stage');
  if (!stage) return render();
  stage.innerHTML = atlasStage();
  const side = document.getElementById('atlas-side');
  if (side) side.innerHTML = atlasSide();
  const label = document.getElementById('atlas-frame-label');
  if (label) label.textContent = frameLabel(atlasFrameNow());
  const range = document.querySelector('[data-atlas-frame]');
  if (range) {
    if (Number(range.value) !== S.atlasFrame) range.value = S.atlasFrame;
    range.setAttribute('aria-valuetext', frameLabel(atlasFrameNow()));
  }
  const play = document.getElementById('atlas-play');
  if (play) play.textContent = atlasTimer ? '멈춤' : S.atlasFrame >= S.atlas.frames.length - 1 ? '처음부터 재생' : '여기서 재생';
}

function viewAtlas() {
  const desc = '장소를 지도에 놓고, 반영한 화마다 인물이 어디에 있었는지 재생해요. 인물 위치는 상태 승인에서 반영한 위치 글을 장소 이름과 맞춘 것이에요.';
  const head = header('지도', '지도', desc, `<a class="btn" href="${base()}/causal">장소 더하기 (인과율)</a>`);
  if (!S.atlas) return `${head}<div class="small">불러오는 중…</div>`;
  if (S.atlas.error) {
    return `${head}<div class="card empty" role="alert"><p>지도를 계산하지 못했어요.</p><div class="note err">${esc(S.atlas.error)}</div>
      <button type="button" class="btn primary" data-action="atlasRetry">다시 불러오기</button></div>`;
  }
  if (!S.atlas.places.length) {
    return `${head}<div class="card empty"><p>장소가 아직 없어요.</p>
      <div class="small">설정 도우미의 장소 칸이나 인과율에서 '장소'를 더하면 지도에 놓을 수 있어요. 본문에 처음 나온 장소는 상태 승인에서 고르면 등록돼요.</div>
      <div class="row"><a class="btn primary" href="${base()}/causal">인과율에서 장소 더하기</a><a class="btn" href="${base()}/setup">설정 도우미</a></div></div>${S.atlas.frames.length > 1 ? atlasTable() : ''}`;
  }
  const tabs = `<div class="tabs" role="tablist" aria-label="지도 화면">
    <button type="button" role="tab" aria-selected="${S.atlasTab === 'map'}" data-action="atlasTab" data-arg="map">지도</button>
    <button type="button" role="tab" aria-selected="${S.atlasTab === 'table'}" data-action="atlasTab" data-arg="table">어디에 있었나</button></div>`;
  if (S.atlasTab === 'table') return `${head}${tabs}${atlasTable()}${atlasUnmatched()}`;
  return `${head}${tabs}
    <div class="at">
      <section class="card at-main">
        ${atlasSlider()}
        <div class="between">${atlasToggles()}<span class="small">장소를 끌어 옮기고, 누르면 자세히 봐요. 인물을 누르면 그 인물의 길만 굵게 봐요.</span></div>
        <div id="atlas-stage">${atlasStage()}</div>
      </section>
      <div id="atlas-side" class="at-side">${atlasSide()}</div>
    </div>${atlasUnmatched()}`;
}

// ----- 저장 -----

async function atlasSavePins(pins, msg) {
  try {
    await saveIfDirty();
    S.project = await api('PUT', `/projects/${enc(S.name)}/atlas/pins`, { pins });
    await atlasLoad();
    atlasRefresh();
    if (msg) toast(msg);
  } catch (e) {
    toast(e.message, true);
    await atlasLoad();
    atlasRefresh();
  }
}

function atlasPins() {
  return (S.atlas.places || []).filter((pl) => pl.pin).map((pl) => ({ place: pl.key, x: pl.pin[0], y: pl.pin[1] }));
}

/** 화면 좌표 → 0~1 지도 좌표 */
function atlasPoint(e) {
  const svg = document.querySelector('.at-map');
  if (!svg) return null;
  const box = svg.getBoundingClientRect();
  const x = (e.clientX - box.left) / box.width;
  const y = (e.clientY - box.top) / box.height;
  return [Math.min(1, Math.max(0, x)), Math.min(1, Math.max(0, y))];
}

// ----- 동작 -----

Object.assign(actions, {
  atlasTab(v) {
    S.atlasTab = v;
    atlasStop();
    render();
  },
  async atlasRetry() {
    S.atlas = null;
    render();
    await atlasLoad();
    render();
  },
  atlasStep(d) {
    atlasStop();
    S.atlasFrame = Math.min(S.atlas.frames.length - 1, Math.max(0, S.atlasFrame + Number(d)));
    atlasRefresh();
  },
  atlasGo(i) {
    atlasStop();
    S.atlasFrame = Number(i);
    S.atlasTab = 'map';
    render();
  },
  atlasPlay() {
    if (atlasTimer) { atlasStop(); atlasRefresh(); return; }
    if (S.atlasFrame >= S.atlas.frames.length - 1) S.atlasFrame = 0;
    atlasTimer = setInterval(() => {
      if (!document.getElementById('atlas-stage') || S.atlasFrame >= S.atlas.frames.length - 1) { atlasStop(); atlasRefresh(); return; }
      S.atlasFrame++;
      atlasRefresh();
    }, 1000);
    atlasRefresh();
  },
  atlasFocus(cid) {
    if (atlasDragged) return;
    S.atlasFocus = S.atlasFocus === cid ? '' : cid;
    atlasRefresh();
  },
  atlasPick(key) {
    S.atlasPick = S.atlasPick === key ? '' : key;
    atlasRefresh();
  },
  atlasSelect(key) {
    S.atlasSel = key || '';
    atlasRefresh();
  },
  async atlasUnpin(key) {
    S.atlasSel = '';
    const pl = atlasPlace(key);
    await atlasSavePins(atlasPins().filter((x) => x.place !== key), `'${pl ? pl.name : key}'을(를) 지도에서 뺐어요`);
  },
  async atlasLink(i) {
    const u = S.atlas.unmatched[Number(i)];
    const v = $(`#at-um-${i}`).value;
    if (!u || !v) { toast('이을 장소를 고르세요', true); return; }
    await run('잇는 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/atlas/links`, { text: u.text, place: v === '-' ? '' : v });
      await atlasLoad();
      toast(v === '-' ? '지도에 그리지 않을 위치로 뒀어요' : '장소에 이었어요');
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
  async atlasDropImage() {
    if (!confirm('배경 그림을 지울까요? 장소 자리는 그대로 남아요.')) return;
    await run('지우는 중', async () => {
      await saveIfDirty();
      S.project = await api('DELETE', `/projects/${enc(S.name)}/atlas/image`);
      await atlasLoad();
      toast('배경 그림을 지웠어요');
    });
  },
});

document.addEventListener('input', (e) => {
  if (!e.target.matches('[data-atlas-frame]')) return;
  atlasStop();
  S.atlasFrame = Number(e.target.value);
  atlasRefresh();
});

document.addEventListener('change', async (e) => {
  const t = e.target;
  if (t.matches('[data-atlas-opt]')) {
    S[t.dataset.atlasOpt] = t.checked;
    if (S.atlasTab === 'table') render(); else atlasRefresh();
    return;
  }
  if (!t.matches('[data-atlas-image]') || !t.files || !t.files[0]) return;
  const file = t.files[0];
  t.value = '';
  if (file.size > 15 * 1024 * 1024) { toast('그림이 너무 커요. 15MB 이하로 올리세요', true); return; }
  await run('그림 올리는 중', async () => {
    const data = await new Promise((ok, bad) => {
      const r = new FileReader();
      r.onload = () => ok(r.result);
      r.onerror = () => bad(new Error('그림을 읽지 못했어요'));
      r.readAsDataURL(file);
    });
    const aspect = await new Promise((ok, bad) => {
      const img = new Image();
      img.onload = () => ok(img.naturalWidth / img.naturalHeight);
      img.onerror = () => bad(new Error('그림을 열지 못했어요. PNG, JPG, WEBP 그림인지 확인하세요'));
      img.src = data;
    });
    await saveIfDirty();
    S.project = await api('PUT', `/projects/${enc(S.name)}/atlas/image`, { data, aspect });
    await atlasLoad();
    toast('배경 그림을 올렸어요');
  });
});

// 장소 끌어 옮기기 · 놓기. 조금이라도 움직였으면 누르기(자세히 보기)로 치지 않는다
document.addEventListener('pointerdown', (e) => {
  const g = e.target.closest && e.target.closest('[data-atlas-pin]');
  if (!g || e.button !== 0) return;
  atlasDrag = { key: g.dataset.atlasPin, x: e.clientX, y: e.clientY, moved: false };
});

document.addEventListener('pointermove', (e) => {
  if (!atlasDrag) return;
  if (!atlasDrag.moved && Math.hypot(e.clientX - atlasDrag.x, e.clientY - atlasDrag.y) < 4) return;
  const pt = atlasPoint(e);
  const pl = atlasPlace(atlasDrag.key);
  if (!pt || !pl) return;
  atlasDrag.moved = true;
  e.preventDefault();
  pl.pin = pt;
  const stage = document.getElementById('atlas-stage');
  if (stage) stage.innerHTML = atlasStage();
});

document.addEventListener('pointerup', async () => {
  if (!atlasDrag) return;
  const d = atlasDrag;
  atlasDrag = null;
  if (!d.moved) return;
  atlasDragged = true;
  setTimeout(() => { atlasDragged = false; }, 0);
  await atlasSavePins(atlasPins());
});

document.addEventListener('click', async (e) => {
  if (!e.target.closest || !e.target.closest('.at-map')) return;
  if (atlasDragged) return;
  const g = e.target.closest('[data-atlas-pin]');
  if (g) {
    S.atlasSel = S.atlasSel === g.dataset.atlasPin ? '' : g.dataset.atlasPin;
    atlasRefresh();
    return;
  }
  if (!S.atlasPick || e.target.closest('[data-action]')) return;
  const pt = atlasPoint(e);
  const pl = atlasPlace(S.atlasPick);
  if (!pt || !pl) return;
  S.atlasPick = '';
  S.atlasSel = pl.key;
  pl.pin = pt;
  await atlasSavePins(atlasPins(), `'${pl.name}'을(를) 지도에 놓았어요`);
});

// 키보드: 장소에서 Enter 는 자세히 보기, 화살표는 1% (Shift 5%) 옮기기
document.addEventListener('keydown', (e) => {
  const g = e.target.closest && e.target.closest('[data-atlas-pin]');
  if (!g) return;
  const pl = atlasPlace(g.dataset.atlasPin);
  if (!pl) return;
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    S.atlasSel = pl.key;
    atlasRefresh();
    return;
  }
  const step = e.shiftKey ? 0.05 : 0.01;
  const mv = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
  if (!mv) return;
  e.preventDefault();
  pl.pin = [Math.min(1, Math.max(0, pl.pin[0] + mv[0])), Math.min(1, Math.max(0, pl.pin[1] + mv[1]))];
  const stage = document.getElementById('atlas-stage');
  if (stage) stage.innerHTML = atlasStage();
  const again = document.querySelector(`[data-atlas-pin="${CSS.escape(pl.key)}"]`);
  if (again) again.focus();
  clearTimeout(atlasKeyTimer);
  atlasKeyTimer = setTimeout(async () => {
    try {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/atlas/pins`, { pins: atlasPins() });
    } catch (err) {
      toast(err.message, true);
    }
  }, 600);
});

(function atlasStyle() {
  const css = `
.at { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 20px; align-items: start; }
@media (max-width: 1000px) { .at { grid-template-columns: 1fr; } }
.at-main { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.at-side { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.at-box { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 14px; display: flex; flex-direction: column; gap: 8px; }
.at-box h3 { margin: 0; font-size: 0.9375rem; }
.at-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; font-size: 0.8125rem; }
.at-who { border: none; background: none; padding: 0; font: inherit; color: var(--text); cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
.at-who.on { font-weight: 700; text-decoration: underline; }
.at-who i, .at-table th i { width: 10px; height: 10px; border-radius: 50%; display: inline-block; flex: none; margin-right: 4px; }
.at-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.at-toggles { gap: 14px; font-size: 0.8125rem; }
.at-toggles label { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }
.at-map-wrap { border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: var(--canvas); }
.at-map { display: block; width: 100%; height: auto; user-select: none; font-family: var(--sans); }
.at-map.picking { cursor: crosshair; }
/* 좁은 폭은 줄이지 않고 가로로 굴려 본다 (인물 관계도와 같다). 장소 이름이 읽히는 크기로 남는다 */
@media (max-width: 600px) { .at-map-wrap { overflow-x: auto; } .at-map { min-width: 640px; } }
.at-map .at-ground { fill: var(--canvas); }
.at-map .at-grid { stroke: var(--rule); stroke-width: 1; }
.at-map .at-trail { fill: none; stroke-linecap: round; stroke-linejoin: round; opacity: .6; }
.at-map .dim { opacity: .18; }
.at-map .at-pin { cursor: grab; touch-action: none; }
.at-map .at-pin:focus { outline: none; }
.at-map .at-pin:focus-visible .at-dot { stroke: var(--accent); stroke-width: 4; }
.at-map .at-hit { fill: transparent; }
.at-map .at-dot { fill: var(--text); stroke: var(--surface); stroke-width: 2.5; }
.at-map .at-pin.sel .at-dot { fill: var(--accent); }
.at-map .at-pin.later .at-dot { fill: var(--surface); stroke: var(--muted); stroke-dasharray: 3 2; }
.at-map .at-pin.later .at-name { fill: var(--muted); }
.at-map .at-hot { fill: none; stroke: var(--accent); stroke-width: 3; }
.at-map .at-name { font-size: 15px; font-weight: 700; fill: var(--text); paint-order: stroke; stroke: var(--canvas); stroke-width: 4px; stroke-linejoin: round; pointer-events: none; }
.at-map .at-tok { cursor: pointer; }
.at-map .at-tok circle { stroke: var(--surface); stroke-width: 2.5; }
.at-map .at-tok text { font-size: 12px; font-weight: 700; fill: #fff; pointer-events: none; }
.at-um { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; padding: 10px 0; border-bottom: 1px solid var(--line); }
.at-um .row { flex-wrap: nowrap; }
.at-um select { max-width: 200px; }
.at-table-wrap { overflow-x: auto; }
.at-table { border-collapse: collapse; font-size: 0.75rem; }
.at-table th, .at-table td { padding: 6px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; text-align: left; }
.at-table th:first-child { position: sticky; left: 0; background: var(--surface); }
.at-table td.same { color: var(--muted); }
.at-table td.moved { font-weight: 700; }
.at-table td.raw { font-style: italic; }
.at-table .cur { background: var(--accent-soft); }
.at-table .linkish { border: none; background: none; padding: 0; font: inherit; color: var(--link); cursor: pointer; }`;
  const el = document.createElement('style');
  el.textContent = css;
  document.head.appendChild(el);
}());

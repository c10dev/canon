/* 인물 화면. app.js 의 S, actions, api, render, header, outline.js 의 공용 목차 틀과 review.js 의 relationHeader 를 그대로 쓴다.
   왼쪽 목차(관계도 · 등장표 · 비중별 인물)와 오른쪽 한 열. 열 맨 위의 시점 띠(castBar)는 관계도 · 인물 · 두 사람 쪽이 함께 쓴다.
   쪽: 관계도(방향 관계를 화별로 재생, 인물 · 선을 고르면 위에 요약 줄), 인물(설정 · 지금 상태 · 상태창 수치 · 관계 · 비밀 ·
   남겨 둔 설정 바꾸기 · AI · 서술 · 신체 · 삽화(읽기, '고치기'로 그 카드만 편다) · 화별 타임라인을 보는 시점 기준으로 한 열에),
   두 사람(온기 · 신뢰 · 긴장 추이, 사건, 수치 보정, 호칭), 등장표.
   계산값은 서버 canon/cast.py 의 /cast 한 번으로 받는다 (frames: 화별 관계, appearances, timelines).
   인물 설정 · 플롯 · 사건 원본은 작품(P())에서 직접 읽는다. 관계도 배치는 이 브라우저에만 저장한다.
   주소: cast(관계도) · cast/map · cast/table · cast/c:<인물> · cast/p:<a>|<b>, 끝에 ?f=<시점>. 옛 주소의 ?tab=sheet|table 도 받는다 */
'use strict';

Object.assign(S, {
  cast: null,        // 서버 계산값
  castFrame: 0,      // frames 의 몇 번째 시점을 보는지
  castView: 'map',   // map 관계도 | table 등장표 | char 인물 | pair 두 사람
  castSel: '',       // 'c:<인물 id>' 또는 'p:<a>|<b>'. 관계도에서 고른 것이고, char · pair 쪽은 이것을 보인다
  castTheme: '',     // 인물 카드의 상태창 수치 보기: '' 기본 | 'system' 작품 스킨 창(statwin.js swSkin). 이 브라우저에만 저장
  castMinor: true,   // 단역도 관계도에 그린다
  castAllTies: false,  // 인물이 많아도 모든 선을 그린다 (CAST_DENSE)
  castAllTl: false,  // 타임라인 전체 보기
  castPos: {},       // 끌어서 옮긴 자리 {id: [x, y]}
  castZoom: 0,       // 관계도 크기 단계 (CAST_ZOOM 의 몇 번째). 0 은 칸 폭에 맞춤
  castEdit: '',      // 'AI · 서술 · 신체 · 삽화' 카드를 고치는 중인 인물 id
  castMinorOpen: false,  // 목차의 단역 묶음을 펼쳤는지
});

const CAST_W = 760;
const CAST_H = 540;
// 온기 다섯 구간 (dynamics.warmth_word 와 같은 경계): 빨강 ↔ 회색 ↔ 파랑. Swift 앱 WarmthBand 도 함께 고친다
// 색은 app.css 토큰을 쓴다(라이트 · 다크 값이 따로 있다). SVG 에서는 style 로만 넣는다(stroke="var(..)" 속성은 먹지 않는다)
const WARMTH_BANDS = [[-0.6, 'var(--red)', '적대한다'], [-0.2, 'var(--bad)', '반감이 있다'], [0.2, 'var(--warm-mid)', '무덤덤하다'], [0.6, 'var(--good)', '호감이 있다'], [Infinity, 'var(--warm-deep)', '깊이 아낀다']];
const TENSION_FILL = { '보통': 'var(--tension-mid)', '높음': 'var(--tension-high)', '매우 높음': 'var(--red)' };
const PAIR_COLORS = ['var(--pair-a)', 'var(--pair-b)'];  // 쌍 그래프: 앞 인물 → 뒤 인물, 뒤 → 앞
const TIER_R = { main: 26, support: 20, minor: 15 };
const TIER_NAME = { main: '주역', support: '조연', minor: '단역' };
const CAST_ZOOM = [1, 1.5, 2, 3];  // 관계도 크기. 1 은 칸 폭에 맞추고, 크게 보면 칸 안에서 굴린다
const CAST_MINOR_FOLD = 4;  // 단역이 이보다 많으면 목차에서 접어 둔다
const CAST_TL_NEAR = 3;  // 인물 쪽 타임라인은 보는 시점 앞뒤 이만큼 화만
const CAST_DENSE = 8;  // 관계도에 보이는 인물이 이보다 많으면 고른 인물(두 사람)과 이어진 선만 그린다
let castTimer = null;
let castDrag = null;
let castDragged = false;
let castLayoutCache = null;

/** 주소 끝 'map' · 'table' · '<c:id 또는 p:a|b>' 와 '?f=<시점>' 을 읽는다. 옛 인물 링크(cast/<id>)와 옛 '?tab=sheet|table' 도 받는다 */
function castParse(arg) {
  const [raw, q] = String(arg || '').split('?');
  const qs = new URLSearchParams(q || '');
  let sel = raw;
  let view = null;
  if (sel === 'map' || sel === 'table') { view = sel; sel = ''; } else if (sel) {
    if (!/^[cp]:/.test(sel)) sel = 'c:' + sel;
    view = sel.startsWith('p:') ? 'pair' : 'char';
  }
  if (qs.get('tab') === 'table') view = 'table';
  return { sel, view, frame: qs.has('f') ? Number(qs.get('f')) : null };
}

/** 지금 쪽(관계도 · 등장표 · 인물 · 두 사람)의 열쇠. 목차의 지금 줄과 주소가 같은 값을 쓴다 */
function castKey() {
  return S.castView === 'map' || S.castView === 'table' ? S.castView : S.castSel;
}

/** 쪽과 시점을 주소에 남긴다 (새로고침 · 링크로 다시 열게). 재생 중에는 쓰지 않는다 */
function castSyncUrl() {
  if (S.route[2] !== 'cast' || castTimer || !S.cast) return;
  const fs = S.cast.frames || [];
  const f = S.castView !== 'table' && fs.length && S.castFrame < fs.length - 1 ? `?f=${S.castFrame}` : '';  // 마지막 시점은 적지 않아 새로 반영한 화를 따라간다
  const h = `${base()}/cast/${enc(castKey())}${f}`;
  if (location.hash === h) return;
  try {
    history.replaceState(history.state, '', h);
    lastHash = location.hash;
  } catch (e) { /* 주소를 못 고쳐도 화면은 그대로 */ }
}

async function castLoad(arg) {
  castStop();
  const want = castParse(arg);
  const same = S.cast && S.cast.name === S.name;
  const wasLast = same && S.castFrame === S.cast.frames.length - 1;  // 마지막 시점을 보고 있었으면 새로 반영한 화로 따라간다
  S.cast = await api('GET', `/projects/${enc(S.name)}/cast`).catch((e) => ({ error: e.message, frames: [] }));
  S.cast.name = S.name;
  if (!same || wasLast || S.castFrame >= S.cast.frames.length) S.castFrame = Math.max(0, S.cast.frames.length - 1);
  if (!same && want.frame !== null && want.frame >= 0 && want.frame < S.cast.frames.length) S.castFrame = Math.floor(want.frame);
  if (want.view) S.castView = want.view;
  else if (!same) S.castView = 'map';  // 주소에 쪽이 없으면 관계도다. 같은 작품이면 보던 쪽을 둔다
  if (!same) {
    S.castAllTl = false;
    S.castEdit = '';
    S.castMinorOpen = false;
    try { S.castPos = JSON.parse(localStorage.getItem('canon-cast-pos:' + S.name) || '{}') || {}; } catch (e) { S.castPos = {}; }
    try { S.castTheme = localStorage.getItem('canon-cast-theme:' + S.name) || ''; } catch (e) { S.castTheme = ''; }
  }
  if (want.sel) S.castSel = want.sel;
  const has = (id) => P().characters.some((c) => c.id === id);
  const ok = (s) => (s.startsWith('c:') && has(s.slice(2))) || (s.startsWith('p:') && s.slice(2).split('|').length === 2 && s.slice(2).split('|').every(has));
  if (!S.castSel || !ok(S.castSel)) {
    if (S.castView === 'char' || S.castView === 'pair') S.castView = 'map';  // 없는 인물 · 두 사람 링크는 관계도로
    const first = P().characters.find((c) => c.tier === 'main') || P().characters[0];
    S.castSel = first ? 'c:' + first.id : '';
  }
  if (S.castView === 'char' && !S.castSel.startsWith('c:')) S.castView = 'pair';
  if (S.castView === 'pair' && !S.castSel.startsWith('p:')) S.castView = 'char';
}

function castStop() {
  if (castTimer) clearInterval(castTimer);
  castTimer = null;
}
window.addEventListener('hashchange', castStop);

function castFrameNow() {
  const fs = (S.cast && S.cast.frames) || [];
  return fs[Math.min(S.castFrame, fs.length - 1)] || null;
}

function frameLabel(f) {
  if (!f) return '';
  if (!f.episode) return '1화 시작 전';
  const e = ep(f.episode);
  return `${f.episode}화 반영 뒤${e ? ' · ' + e.plot.title : ''}`;
}

function warmthColor(w) {
  return WARMTH_BANDS.find(([cut]) => w < cut)[1];
}

function castChar(id) {
  return P().characters.find((c) => c.id === id);
}

function tieOf(f, s, t) {
  return f ? f.ties.find((x) => x.source === s && x.target === t) : null;
}

function pairOf(f, a, b) {
  return f ? f.pairs.find((x) => (x.a === a && x.b === b) || (x.a === b && x.b === a)) : null;
}

/** 이 시점에 이미 나온 인물인지. 설정 단계 인물(first_ep 0)은 처음부터 있다 */
function castPresent(c, f) {
  if (!f || !c.first_ep) return true;
  return c.first_ep <= f.episode;
}

/** 관계도 선의 온기 · 신뢰를 글로 (색과 마우스 올리기 없이도 읽게). 지금 보는 시점 기준 */
function castTieList(f) {
  const ties = f ? f.ties : [];
  if (!ties.length) return '';
  return `<details class="cast-tie-list"><summary class="small">관계 목록 보기 (${ties.length}줄)</summary>
    <ul class="rel-lines">${ties.map((t) => `<li>${esc(charName(t.source))} → ${esc(charName(t.target))}: ${tieText(t)}</li>`).join('')}</ul></details>`;
}

function tieText(t) {
  if (!t) return '<span class="small">아직 관계가 없어요</span>';
  if (P().settings.show_numbers) {
    return `온기 ${t.warmth >= 0 ? '+' : ''}${t.warmth.toFixed(2)} · 신뢰 ${t.trust.toFixed(2)} <span title="신뢰를 판단한 근거(겪은 사건)가 쌓인 양이에요. 클수록 신뢰가 쉽게 바뀌지 않아요">(증거 ${t.evidence.toFixed(1)})</span> · 원한 ${t.grievance.toFixed(2)} · <span title="보는 쪽이 느끼는 상대의 위아래예요. +면 상대를 위로, -면 아래로 봐요">서열 ${t.status >= 0 ? '+' : ''}${t.status.toFixed(2)}</span> · 친숙 ${t.familiarity.toFixed(2)} · 단계 <strong>${esc(t.stage)}</strong>`;
  }
  return `${esc(t.warmth_word)}, ${esc(t.trust_word)}${t.grievance >= 0.3 ? ', 풀리지 않은 원한' : ''} · 단계 <strong>${esc(t.stage)}</strong>`;
}

function tensionText(pr) {
  if (!pr) return '';
  return P().settings.show_numbers ? `긴장 ${pr.tension.toFixed(1)}/10` : `긴장 ${esc(pr.tension_word)}`;
}

// ----- 배치 -----

/** 결정적인 힘 배치. 모든 시점의 간선을 합쳐 한 번만 계산해서 재생해도 자리가 흔들리지 않는다 */
function castLayout(chars) {
  const key = chars.map((c) => c.id + ':' + c.tier).join(',') + '#' + ((S.cast && S.cast.frames) || []).length;
  if (!castLayoutCache || castLayoutCache.key !== key) castLayoutCache = { key, pos: castForce(chars) };
  const pos = Object.fromEntries(Object.entries(castLayoutCache.pos).map(([id, xy]) => [id, xy.slice()]));
  Object.entries(S.castPos || {}).forEach(([id, xy]) => { if (id in pos) pos[id] = xy.slice(); });
  return pos;
}

function castForce(chars) {
  const n = chars.length;
  const cx = CAST_W / 2;
  const cy = CAST_H / 2;
  const ring = { main: 0.16, support: 0.32, minor: 0.43 };
  const groups = { main: [], support: [], minor: [] };
  chars.forEach((c) => groups[c.tier || 'main'].push(c));
  const pos = {};
  Object.entries(groups).forEach(([tier, list], gi) => {
    const r = (list.length === 1 && tier === 'main' && !groups.support.length) ? 0 : ring[tier] * Math.min(CAST_W, CAST_H);
    list.forEach((c, i) => {
      const a = (i / Math.max(1, list.length)) * Math.PI * 2 - Math.PI / 2 + gi * 0.4;
      pos[c.id] = [cx + Math.cos(a) * r * 1.35, cy + Math.sin(a) * r];
    });
  });
  const weight = {};
  ((S.cast && S.cast.frames) || []).forEach((f) => f.ties.forEach((t) => {
    if (!(t.source in pos) || !(t.target in pos)) return;
    const k = [t.source, t.target].sort().join('|');
    weight[k] = Math.max(weight[k] || 0, 0.3 + t.familiarity);
  }));
  if (n > 1) {
    const k = Math.sqrt((CAST_W * CAST_H) / n) * 0.9;
    let temp = 40;
    const ids = Object.keys(pos);
    for (let it = 0; it < 260; it++) {
      const disp = Object.fromEntries(ids.map((id) => [id, [0, 0]]));
      for (let i = 0; i < ids.length; i++) {
        for (let j = i + 1; j < ids.length; j++) {
          const [a, b] = [pos[ids[i]], pos[ids[j]]];
          let dx = a[0] - b[0];
          let dy = a[1] - b[1];
          let d = Math.hypot(dx, dy);
          if (d < 0.01) { dx = 0.01 * (i + 1); dy = 0.01; d = Math.hypot(dx, dy); }
          const f = (k * k) / d;
          disp[ids[i]][0] += (dx / d) * f; disp[ids[i]][1] += (dy / d) * f;
          disp[ids[j]][0] -= (dx / d) * f; disp[ids[j]][1] -= (dy / d) * f;
        }
      }
      Object.entries(weight).forEach(([key, w]) => {
        const [s, t] = key.split('|');
        const dx = pos[s][0] - pos[t][0];
        const dy = pos[s][1] - pos[t][1];
        const d = Math.max(0.01, Math.hypot(dx, dy));
        const f = ((d * d) / k) * w * 0.6;
        disp[s][0] -= (dx / d) * f; disp[s][1] -= (dy / d) * f;
        disp[t][0] += (dx / d) * f; disp[t][1] += (dy / d) * f;
      });
      chars.forEach((c) => {  // 주역일수록 가운데로
        const g = { main: 0.04, support: 0.015, minor: 0.005 }[c.tier || 'main'];
        disp[c.id][0] += (cx - pos[c.id][0]) * g * k * 0.05;
        disp[c.id][1] += (cy - pos[c.id][1]) * g * k * 0.05;
      });
      ids.forEach((id) => {
        const [dx, dy] = disp[id];
        const d = Math.max(0.01, Math.hypot(dx, dy));
        pos[id][0] = Math.min(CAST_W - 70, Math.max(70, pos[id][0] + (dx / d) * Math.min(d, temp)));
        pos[id][1] = Math.min(CAST_H - 50, Math.max(40, pos[id][1] + (dy / d) * Math.min(d, temp)));
      });
      temp = Math.max(1.5, temp * 0.985);
    }
  }
  return pos;
}

/** 인물이 많으면(CAST_DENSE 초과) 고른 인물 · 두 사람과 이어진 선만 그린다. 모두 그릴 때는 null */
function castNear(chars) {
  if (S.castAllTies || chars.length <= CAST_DENSE) return null;
  const selC = S.castSel.startsWith('c:') ? S.castSel.slice(2) : '';
  const selP = S.castSel.startsWith('p:') ? S.castSel.slice(2).split('|') : null;
  if (selC) return (s, t) => s === selC || t === selC;
  if (selP) return (s, t) => selP.includes(s) || selP.includes(t);
  return null;
}

function castShown() {
  return P().characters.filter((c) => S.castMinor || c.tier !== 'minor' || S.castSel === 'c:' + c.id);
}

// ----- 관계도 -----

function castGraph() {
  const f = castFrameNow();
  const chars = castShown();
  if (!chars.length) return '<div class="small">인물이 없어요. 설정 도우미에서 인물을 더하세요.</div>';
  const pos = castLayout(P().characters);  // 단역을 숨겨도 자리는 그대로 둔다. 숨김은 그리기에서만 거른다
  const shown = new Set(chars.map((c) => c.id));
  const selC = S.castSel.startsWith('c:') ? S.castSel.slice(2) : '';
  const selP = S.castSel.startsWith('p:') ? S.castSel.slice(2).split('|') : null;
  const hot = (s, t) => (selC ? s === selC || t === selC : selP ? selP.includes(s) && selP.includes(t) : true);
  const near = castNear(chars);
  const R = (id) => TIER_R[(castChar(id) || {}).tier || 'main'];
  const nm = (id) => charName(id);
  const out = [];

  const markers = WARMTH_BANDS.map(([, col], i) => `<marker id="cg-arrow-${i}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" style="fill:${col}"></path></marker>`).join('');

  // 방향 간선: 두 방향이 서로 반대쪽으로 휘어 겹치지 않는다
  (f ? f.ties : []).forEach((t) => {
    if (!shown.has(t.source) || !shown.has(t.target) || (near && !near(t.source, t.target))) return;
    const [x1, y1] = pos[t.source];
    const [x2, y2] = pos[t.target];
    const d = Math.max(1, Math.hypot(x2 - x1, y2 - y1));
    const ux = (x2 - x1) / d;
    const uy = (y2 - y1) / d;
    const nx = -uy;
    const ny = ux;
    const bend = Math.min(26, d * 0.12);
    const sx = x1 + ux * (R(t.source) + 3) + nx * bend * 0.35;
    const sy = y1 + uy * (R(t.source) + 3) + ny * bend * 0.35;
    const ex = x2 - ux * (R(t.target) + 4) + nx * bend * 0.35;
    const ey = y2 - uy * (R(t.target) + 4) + ny * bend * 0.35;
    const qx = (x1 + x2) / 2 + nx * bend;
    const qy = (y1 + y2) / 2 + ny * bend;
    const band = WARMTH_BANDS.findIndex(([cut]) => t.warmth < cut);
    const title = `${nm(t.source)} → ${nm(t.target)}: ${t.warmth_word}, ${t.trust_word} · 단계 ${t.stage}${P().settings.show_numbers ? ` (온기 ${t.warmth.toFixed(2)}, 신뢰 ${t.trust.toFixed(2)}, 친숙 ${t.familiarity.toFixed(2)})` : ''}`;
    const arg = [t.source, t.target].sort().join('|');
    out.push(`<g class="cg-edge${hot(t.source, t.target) ? '' : ' dim'}" data-action="castMapPick" data-arg="${esc('p:' + arg)}"><title>${esc(title)}</title>
      <path class="cg-hit" d="M${sx} ${sy} Q${qx} ${qy} ${ex} ${ey}"></path>
      <path d="M${sx} ${sy} Q${qx} ${qy} ${ex} ${ey}" style="stroke:${WARMTH_BANDS[band][1]}" stroke-width="${(1.5 + 3.5 * t.familiarity).toFixed(2)}" marker-end="url(#cg-arrow-${band})"></path></g>`);
  });

  // 쌍 긴장: 보통 이상이면 두 인물 사이 가운데 점
  (f ? f.pairs : []).forEach((pr) => {
    if (!shown.has(pr.a) || !shown.has(pr.b) || !TENSION_FILL[pr.tension_word] || (near && !near(pr.a, pr.b))) return;
    const [x1, y1] = pos[pr.a];
    const [x2, y2] = pos[pr.b];
    const r = 4 + pr.tension * 0.55;
    const arg = [pr.a, pr.b].sort().join('|');
    out.push(`<g class="cg-tension${hot(pr.a, pr.b) ? '' : ' dim'}" data-action="castMapPick" data-arg="${esc('p:' + arg)}"><title>${esc(`${nm(pr.a)} ↔ ${nm(pr.b)}${pr.type ? ' (' + pr.type + ')' : ''}: 긴장 ${pr.tension_word} (${pr.tension.toFixed(1)}/10)`)}</title>
      <circle cx="${(x1 + x2) / 2}" cy="${(y1 + y2) / 2}" r="${r.toFixed(1)}" style="fill:${TENSION_FILL[pr.tension_word]}"></circle></g>`);
  });

  // 인물
  chars.forEach((c) => {
    const [x, y] = pos[c.id];
    const r = TIER_R[c.tier || 'main'];
    const st = f ? f.states.find((s) => s.character_id === c.id) : null;
    const here = castPresent(c, f);
    const sel = selC === c.id || (selP && selP.includes(c.id));
    const label = c.name || c.id;
    const inside = c.tier !== 'minor' && [...label].length <= 3;  // 짧은 이름은 원 안에, 긴 이름과 단역은 원 아래에
    const title = `${c.name || c.id} · ${TIER_NAME[c.tier || 'main']} · ${c.role || ''}${st && st.emotional_state ? '\n감정: ' + st.emotional_state : ''}${here ? '' : `\n${c.first_ep}화에 처음 나와요`}`;
    out.push(`<g class="cg-node ${c.tier || 'main'}${sel ? ' sel' : ''}${here ? '' : ' absent'}" data-cast-node="${esc(c.id)}" data-action="castMapPick" data-arg="${esc('c:' + c.id)}" tabindex="0" role="button" aria-label="${esc((c.name || c.id) + ' 자세히 보기')}"><title>${esc(title)}</title>
      ${sel ? `<circle class="cg-halo" cx="${x}" cy="${y}" r="${r + 6}"></circle>` : ''}
      <circle class="cg-hitnode" cx="${x}" cy="${y}" r="${Math.max(r, 22)}"></circle>
      <circle class="cg-dot" cx="${x}" cy="${y}" r="${r}"></circle>
      ${inside ? `<text class="cg-init" x="${x}" y="${y + 5}" text-anchor="middle">${esc(label)}</text>` : `<text class="cg-name" x="${x}" y="${y + r + 15}" text-anchor="middle">${esc(label)}</text>`}</g>`);
  });

  return `<svg class="cast-graph" viewBox="0 0 ${CAST_W} ${CAST_H}" role="group" aria-label="${esc(frameLabel(f))} 관계도"><defs>${markers}</defs>${out.join('')}</svg>`;
}

function castLegend() {
  const warm = WARMTH_BANDS.map(([, col, word]) => `<span><i style="background:${col}"></i>${word}</span>`).join('');
  const ten = Object.entries(TENSION_FILL).map(([w, col]) => `<span><i style="background:${col};border-radius:50%"></i>긴장 ${w}</span>`).join('');
  return `<div class="legend"><strong>온기</strong>${warm}</div>
    <div class="legend"><strong>두 사람 긴장</strong>${ten}<span><i style="border:1.5px dashed var(--line-strong);background:var(--surface);border-radius:50%"></i>이 시점엔 아직 안 나온 인물</span></div>
    <div class="small">화살표는 보는 쪽 → 보이는 쪽이에요. 색은 온기, 굵기는 함께 겪은 정도(친숙도)예요.</div>`;
}

function castTriads(f) {
  if (!f || !f.triads.length) return '';
  const items = f.triads.map((tri) => tri.map(charName).map(esc).join(' · ')).join(', ');
  return `<div class="note warn">불안정한 삼각 구도: ${items}. 두 사람은 가깝고 한 쌍은 적대라, 누군가 편을 바꾸거나 화해하거나 관계 하나가 끊어지는 쪽으로 압력이 있어요.</div>`;
}

/** 시점 띠 글: '12화 반영 뒤' 는 굵게, 화 제목은 좁은 칸에서 감춘다 */
function castBarLabel(f) {
  if (!f || !f.episode) return `<strong>${esc(frameLabel(f))}</strong>`;
  const e = ep(f.episode);
  return `<strong>${f.episode}화 반영 뒤</strong>${e && e.plot.title ? `<span class="cast-bar-title"> · ${esc(e.plot.title)}</span>` : ''}`;
}

/** 시점 띠: 관계도 · 인물 · 두 사람 쪽 맨 위에 붙어 있다(좁은 칸은 아래). 시점이 하나뿐이면 안내 한 줄 */
function castBar() {
  const fs = S.cast.frames;
  if (fs.length < 2) return '<div class="cast-bar one"><span class="small">1화를 반영하면 화별로 관계와 상태가 어떻게 바뀌었는지 재생할 수 있어요.</span></div>';
  return `<div class="cast-bar" role="group" aria-label="보는 시점">
    <button type="button" class="btn small icon-btn" data-action="castStep" data-arg="-1" aria-label="이전 시점">◀</button>
    <input type="range" min="0" max="${fs.length - 1}" value="${S.castFrame}" data-cast-frame aria-label="보는 시점" aria-valuetext="${esc(frameLabel(castFrameNow()))}">
    <button type="button" class="btn small icon-btn" data-action="castStep" data-arg="1" aria-label="다음 시점">▶</button>
    <span id="cast-frame-label" class="cast-bar-label">${castBarLabel(castFrameNow())}</span>
    <button type="button" class="btn small" data-action="castPlay" id="cast-play">${castPlayLabel()}</button></div>`;
}

function castPlayLabel() {
  if (castTimer) return '멈춤';
  return S.castFrame >= S.cast.frames.length - 1 ? '처음부터 재생' : '여기서 재생';
}

// ----- 인물 상세 -----

function castStrip(cid, opts = {}) {
  const p = P();
  const total = Math.max(p.meta.target_episodes, ...p.episodes.map((e) => e.plot.number), 1);
  const step = opts.step || (total <= 40 ? 14 : total <= 120 ? 6 : 3);
  const apps = new Map(((S.cast.appearances || {})[cid] || []).map((a) => [a.n, a]));
  const h = 18;
  const cells = [];
  for (let n = 1; n <= total; n++) {
    const a = apps.get(n);
    const x = (n - 1) * step;
    if (!a) { cells.push(`<rect x="${x}" y="6" width="${Math.max(1, step - 1)}" height="6" class="cs-off"></rect>`); continue; }
    const e = ep(n);
    cells.push(`<rect x="${x}" y="1" width="${Math.max(1, step - 1)}" height="${h - 2}" class="cs-on ${a.status}"><title>${esc(`${n}화 ${e ? e.plot.title : ''} · ${STATUS[a.status]}${a.pov ? ' · 시점 인물' : ''}`)}</title></rect>`);
    if (a.pov) cells.push(`<rect x="${x}" y="${h + 1}" width="${Math.max(1, step - 1)}" height="3" class="cs-pov"></rect>`);
  }
  if (opts.mark && opts.mark <= total) cells.push(`<rect x="${(opts.mark - 1) * step - 1}" y="0" width="${step + 1}" height="${h}" class="cs-mark"></rect>`);
  return `<svg class="cast-strip" width="${total * step}" height="${h + 5}" viewBox="0 0 ${total * step} ${h + 5}" role="img" aria-label="${esc(`${charName(cid)} 등장 화: 1~${total}화 중 ${apps.size}화 등장`)}">${cells.join('')}</svg>`;
}

/** 이 인물이 숨긴 비밀과 이 인물만 모르는 비밀. kind 는 숨김 · 모름 */
function castSecrets(c, f) {
  const nm = charName;
  const all = f ? f.secrets : [];
  return [
    ...all.filter((s) => s.owner === c.id).map((s) => ({ kind: '숨김', content: s.content, who: s.hidden_from.length ? `아직 모름: ${s.hidden_from.map(nm).join(', ')}` : '모두 앎' })),
    ...all.filter((s) => s.hidden_from.includes(c.id)).map((s) => ({ kind: '모름', content: s.content, who: `${nm(s.owner)}의 비밀` })),
  ];
}

function castTimeline(c) {
  const rows = (S.cast.timelines || {})[c.id] || [];
  if (!rows.length) return '';
  const f = castFrameNow();
  const LABEL = { emotional_state: '감정', current_goal: '목표', location: '위치', attire: '차림' };
  // 고른 시점 앞뒤 CAST_TL_NEAR 화를 보인다 (시점이 없으면 앞 화부터). 인물 쪽 한 열이 타임라인으로 길어지지 않게
  const shown = S.castAllTl ? rows : f && f.episode ? rows.filter((r) => Math.abs(r.n - f.episode) <= CAST_TL_NEAR) : rows.slice(0, CAST_TL_NEAR * 2 + 1);
  const items = shown.map((r) => {
    const bits = Object.entries(r.changes).filter(([k]) => LABEL[k]).map(([k, v]) => `<div><span class="small">${LABEL[k]}</span> ${esc(v)}</div>`);
    if (r.changes.knows) bits.push(`<div><span class="small">알게 됨</span> ${r.changes.knows.map(esc).join(', ')}</div>`);
    r.secrets.forEach((s) => bits.push(`<div><span class="small">비밀 생김</span> ${esc(s)}</div>`));
    (r.settings || []).forEach((x) => bits.push(`<div><span class="small">${esc(x.label)} 바뀜${x.source === 'author' ? ' (작가)' : ''}</span> ${scArrow(x.before, x.after)}</div>`));
    r.events.forEach((e) => {
      const role = e.actor === c.id ? '' : e.target === c.id ? '' : ' (목격)';
      bits.push(`<div class="cast-ev ${GOOD_EVENTS.includes(e.kind) ? 'good' : 'bad'}">${esc(charName(e.actor))} → ${esc(charName(e.target))} · ${esc(e.kind)} ${INTENSITY[e.intensity] || ''}${role}${e.quote ? `<br><span class="small">“${esc(e.quote)}”</span>` : ''}</div>`);
    });
    const marks = `${r.new ? '<span class="chip ai">첫 등장</span>' : ''}${r.pov ? '<span class="chip">시점</span>' : ''}`;
    return `<li class="${f && f.episode === r.n ? 'now' : ''}"><div class="row"><a href="${base()}/write/${r.n}"><strong>${r.n}화</strong></a><span class="small">${esc(r.title)}</span>${marks}</div>${bits.join('') || '<div class="small">등장</div>'}</li>`;
  }).join('');
  const more = rows.length > shown.length ? `<button type="button" class="btn small ghost" data-action="castAllTl">나머지 ${rows.length - shown.length}화도 보기</button>` : '';
  return `<section class="card"><div class="between"><h2>화별 타임라인</h2><span class="small">반영한 화에서 바뀐 것만${S.castAllTl ? '' : ` · 보는 시점 앞뒤 ${CAST_TL_NEAR}화`}</span></div>${more}<ol class="cast-tl">${items}</ol></section>`;
}

// ----- 인물 카드 -----
// 신체 프로필 칸 (Character.body). 작가가 정하고(AI 제안은 칸별로 골라 적용) 인물 카드에만 보인다. 프롬프트에는 넣지 않는다
const BODY_FIELDS = [['height', '키'], ['weight', '몸무게'], ['build', '체형'], ['measurements', '쓰리사이즈'], ['features', '신체 특징']];

/** 나이 칸으로 미성년인지. cast.is_minor_age 와 같은 규칙이라 함께 고친다 (tests/test_cast_js.py). 19 미만 숫자, 10대, 학생 · 아이 같은 말이면 미성년이다. 모르면 false.
    미성년 인물은 쓰리사이즈 칸을 보이지도 받지도 않는다 */
function isMinorAge(age) {
  const a = String(age || '');
  if (/초등|중학|고등|고교|소년|소녀|어린|아이|미성년|10\s*대/.test(a)) return true;
  const m = a.match(/\d+/);
  return !!m && Number(m[0]) < 19;
}

function bodyRows(c) {
  const b = c.body || {};
  return BODY_FIELDS.filter(([k]) => (b[k] || '').trim() && !(k === 'measurements' && isMinorAge(c.age))).map(([k, label]) => [k, label, b[k].trim()]);
}

// 인물 하나의 설정(고정) · 지금 상태 · 상태창 수치 · 관계 · 비밀 · 기록을 한 장에. 값은 모두 보는 시점(frame)의 것

const SHEET_STATE = [['감정', 'emotional_state'], ['목표', 'current_goal'], ['위치', 'location'], ['차림', 'attire']];
const SHEET_SETTING = ['appearance', 'personality', 'speech_style', 'goal', 'wound', 'arc', 'background'];  // 서술 말투는 'AI · 서술 · 신체 · 삽화' 카드에
const SW_FRACTION = /^\s*(\d[\d,]*(?:\.\d+)?)\s*\/\s*(\d[\d,]*(?:\.\d+)?)\s*$/;

function castStateOf(f, cid) {
  return f ? f.states.find((s) => s.character_id === cid) || null : null;
}

/** 보는 시점 바로 앞 시점. 이번 화에 바뀐 값을 찾는 데 쓴다 */
function castPrevFrame() {
  return S.castFrame > 0 ? S.cast.frames[S.castFrame - 1] : null;
}

/** 상태창 한 줄이 앞 시점보다 어떻게 바뀌었는지: 수치는 +3, 목록은 +이름 · −이름, 그 밖에는 '바뀜'. 같으면 '' */
function castStatDelta(before, after) {
  if (before === undefined) return after ? '새 항목' : '';
  if (before === after) return '';
  if (!after) return '지움';
  const a = String(after).match(SW_AMOUNT);
  const b = String(before).match(SW_AMOUNT);
  if (a && b && a[1] === b[1] && a[5] === b[5]) {
    const d = Number(a[3].replace(/,/g, '')) - Number(b[3].replace(/,/g, ''));
    return `${d > 0 ? '+' : ''}${swFmt(d, a[3].includes(','))}${a[5]}`;
  }
  if (a || b) return '바뀜';
  const was = swItems(before);
  const now = swItems(after);
  if (was.length > 1 || now.length > 1) {
    const has = (list, x) => list.some((y) => swKey(y) === swKey(x));
    const lst = [...now.filter((x) => !has(was, x)).map((x) => `+${x}`), ...was.filter((x) => !has(now, x)).map((x) => `−${x}`)];
    return lst.join(' ') || '바뀜';
  }
  return '바뀜';
}

function castSheetState(c, f) {
  const st = castStateOf(f, c.id);
  const prev = castStateOf(castPrevFrame(), c.id);
  const head = `<div class="between"><h2>지금 상태</h2><span class="small">화마다 바뀌는 값 · ${esc(frameLabel(f))}</span></div>`;
  if (!castPresent(c, f)) return `<section class="card">${head}<div class="note">이 시점에는 아직 나오지 않은 인물이에요. ${c.first_ep}화에 처음 나와요.</div></section>`;
  const rows = SHEET_STATE.map(([label, k]) => {
    const v = st ? st[k] : '';
    const moved = prev && f.episode && v && v !== prev[k];
    const map = k === 'location' && v ? ` · <a href="${base()}/atlas">지도에서 보기</a>` : '';
    return `<div class="csh-row"><span>${label}</span><div class="${v ? '' : 'small'}">${esc(v || '기록 없음')}${map}</div>${moved ? `<span class="csh-delta">${f.episode}화에 바뀜</span>` : ''}</div>`;
  }).join('');
  const knows = st ? st.knows : [];
  const old = new Set(prev ? prev.knows : knows);
  const chips = knows.map((k) => `<span class="csh-know${f.episode && !old.has(k) ? ' new' : ''}">${esc(k)}</span>`).join('');
  return `<section class="card">${head}<div>${rows}
    <div class="csh-row"><span>아는 것${knows.length ? ` ${knows.length}` : ''}</span><div class="csh-chips">${chips || '<span class="small">기록 없음</span>'}</div></div></div></section>`;
}

function castSheetStats(c, f) {
  const st = castStateOf(f, c.id);
  const stats = (st ? st.stats : []).filter((s) => s.name);
  const link = `${base()}/statwin/${enc(c.id)}`;
  if (!stats.length) {
    return `<section class="card csh-empty"><div class="between"><span class="small">이 인물은 ${f && f.episode ? '이 시점에 ' : ''}상태창이 없어요. 레벨 · 스킬처럼 본문 상태창에 나오는 값이 있으면 만들어요.</span><a class="btn small" href="${link}">상태창 만들기</a></div></section>`;
  }
  const prevSt = castStateOf(castPrevFrame(), c.id);
  const before = prevSt && f.episode ? Object.fromEntries(prevSt.stats.map((s) => [s.name, s.value])) : null;
  const logs = (P().stat_log || []).filter((r) => r.character_id === c.id && f && r.episode === f.episode);
  const src = (name) => { const r = logs.filter((x) => x.name === name).pop(); return r ? (r.source === 'author' ? '작가가 고침' : 'AI 변경안') : ''; };
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
  const moved = items.filter((x) => x.delta).length + gone.length;
  const system = S.castTheme === 'system';
  const deltaTag = (x) => (x.delta ? `<span class="csh-delta" title="${esc(`${f.episode}화에 바뀜${x.from ? ' · ' + x.from : ''}`)}">${esc(x.delta)}</span>` : '');
  const body = system
    ? `<div class="sw-sys sw-skin-${swSkin()}" role="group" aria-label="${esc(c.name)} ${esc(swTitle())}"><div class="sw-sys-title">【 ${esc(swTitle())} 】</div>
        <dl><dt>이름</dt><dd>${esc(c.name || c.id)}</dd>${items.map((x) => `<dt>${esc(x.name)}</dt><dd>${x.pct !== null ? `<span class="sw-sys-bar" aria-hidden="true"><i style="width:${x.pct}%"></i></span>` : ''}${x.list ? x.list.map((v) => abChip(c.id, x.name, v, 'sw-sys-tag')).join('') : `<span>${esc(x.value || '—')}</span>`}${deltaTag(x)}</dd>`).join('')}
        ${gone.map((k) => `<dt>${esc(k)}</dt><dd><s>${esc(before[k])}</s><span class="csh-delta">지움</span></dd>`).join('')}</dl>
        <div class="sw-sys-foot"><span>${esc(frameLabel(f))}</span><span>${moved ? `이번 화에 ${moved}항목 바뀜` : ''}</span></div></div>`
    : `<div class="csh-stats">${items.map((x) => `<div class="csh-stat${x.list ? ' wide' : ''}${x.delta ? ' moved' : ''}"><div class="between"><span class="small">${esc(x.name)}</span>${deltaTag(x)}</div>
        ${x.list ? `<div class="csh-chips">${x.list.map((v) => abChip(c.id, x.name, v, 'csh-know')).join('')}</div>` : `<strong>${esc(x.value || '—')}</strong>`}
        ${x.pct !== null ? `<div class="csh-bar" aria-hidden="true"><i style="width:${x.pct}%"></i></div>` : ''}</div>`).join('')}
        ${gone.map((k) => `<div class="csh-stat moved"><div class="between"><span class="small">${esc(k)}</span><span class="csh-delta">지움</span></div><s class="small">${esc(before[k])}</s></div>`).join('')}</div>`;
  const view = `<div class="seg" role="group" aria-label="상태창 보기"><button type="button" data-action="castTheme" data-arg="" aria-pressed="${!system}">카드</button><button type="button" data-action="castTheme" data-arg="system" aria-pressed="${system}">${esc(SW_SKINS[swSkin()])}</button></div>`;
  return `<section class="card"><div class="between"><div class="row"><h2>상태창</h2>${moved ? `<span class="small">이번 화에 ${moved}항목 바뀜</span>` : ''}</div>
      <div class="row">${view}<a class="btn small ghost" href="${link}">수치 고치기</a></div></div>${body}</section>`;
}

/** 방향 하나의 온기 막대: 가운데가 0, 왼쪽이 적대 · 오른쪽이 깊이 아낌. 글은 온기 말(숫자로 보기면 온기 · 신뢰 값) */
function castMeter(arrow, tie) {
  if (!tie) return `<div class="cast-meter"><span aria-hidden="true">${arrow}</span><span class="cast-track"></span><span>아직 없음</span></div>`;
  const w = Math.max(-1, Math.min(1, tie.warmth));
  const left = w >= 0 ? 50 : 50 + w * 50;
  const word = P().settings.show_numbers ? `온기 ${tie.warmth >= 0 ? '+' : ''}${tie.warmth.toFixed(2)} · 신뢰 ${tie.trust.toFixed(2)}` : `${tie.warmth_word}, ${tie.trust_word}`;
  return `<div class="cast-meter"><span aria-hidden="true">${arrow}</span><span class="cast-track" aria-hidden="true"><i style="left:${left.toFixed(1)}%;width:${Math.max(1, Math.abs(w) * 50).toFixed(1)}%;background:${warmthColor(tie.warmth)}"></i></span><span>${esc(word)}</span></div>`;
}

/** 관계: 상대마다 한 줄(인물 원 · 이름 · 관계 유형 · 단계 · 긴장, 두 방향 온기 막대). 줄을 누르면 두 사람 쪽 */
function castSheetRels(c, f) {
  const partners = [...new Set((f ? f.ties : []).filter((t) => t.source === c.id || t.target === c.id).map((t) => (t.source === c.id ? t.target : t.source)))];
  const rows = partners.map((o) => {
    const oc = castChar(o);
    const pr = pairOf(f, c.id, o);
    const to = tieOf(f, c.id, o);
    const from = tieOf(f, o, c.id);
    const stage = [to ? `→ ${to.stage}` : '', from ? `← ${from.stage}` : ''].filter(Boolean).join(' · ');
    const label = `${charName(o)}와 두 사람 보기: ${charName(c.id)} → ${charName(o)} ${to ? to.warmth_word : '관계 없음'}, ${charName(o)} → ${charName(c.id)} ${from ? from.warmth_word : '관계 없음'}`;
    return `<li><button type="button" class="cast-rel" data-action="castShow" data-arg="${esc('p:' + [c.id, o].sort().join('|'))}" aria-label="${esc(label)}">
      ${oc ? castAva(oc) : '<span class="cast-ava" aria-hidden="true">?</span>'}
      <span class="cast-rel-who"><span class="row" style="gap:6px"><strong>${esc(charName(o))}</strong>${pr && pr.type ? `<span class="chip">${esc(pr.type)}</span>` : ''}</span><span class="small">${[stage ? `단계 ${esc(stage)}` : '', tensionText(pr)].filter(Boolean).join(' · ')}</span></span>
      <span class="cast-rel-meters">${castMeter('→', to)}${castMeter('←', from)}</span><span class="cast-rel-go" aria-hidden="true">›</span></button></li>`;
  }).join('');
  return `<section class="card"><div class="between"><h2>관계${partners.length ? ` ${partners.length}` : ''}</h2><span class="small">반영한 화의 사건으로 계산 · 줄을 누르면 두 사람 추이</span></div>
    ${rows ? `<ul class="cast-rels">${rows}</ul>` : '<div class="small">이 시점에 관계가 없어요</div>'}</section>`;
}

function castSheetSecrets(c, f) {
  const list = castSecrets(c, f);
  return `<section class="card"><h2>비밀</h2>${list.length ? `<ul class="csh-list">${list.map((s) => `<li><span class="chip ${s.kind === '숨김' ? 'csh-own' : 'warn'}">${s.kind}</span> ${esc(s.content)}<div class="small">${esc(s.who)}</div></li>`).join('')}</ul>` : '<div class="small">이 시점에 이 인물과 얽힌 비밀이 없어요</div>'}
    ${(c.secrets || []).length ? `<div class="csh-row"><span>설정 비밀</span><div>${c.secrets.map(esc).join('<br>')}</div></div>` : ''}</section>`;
}

/** 설정은 보는 시점의 값(scAt). 남겨 둔 설정 바꾸기 제안은 그 칸 안에서 고른다 (scTake · scDrop 은 setting_held 번호로 찾는다) */
function castSheetSettings(c, f, at) {
  const held = (P().setting_held || []).map((x, i) => [x, i]).filter(([x]) => x.character_id === c.id);
  const heldBox = ([x, i]) => `<div class="csh-held"><div class="small"><strong>${x.episode}화 설정 바꾸기 제안</strong> · 자동 집필이 남겨 둠</div>
    <textarea id="sch-${i}" rows="2" data-autogrow aria-label="${esc(scLabel(x.field))} 바꾼 뒤">${esc(x.value)}</textarea>
    ${x.reason ? `<div class="small">${esc(x.reason)}</div>` : ''}${x.quote ? `<div class="small">“${esc(x.quote)}”</div>` : ''}
    <div class="row"><button type="button" class="btn small primary" data-action="scTake" data-arg="${i}">적용</button><button type="button" class="btn small" data-action="scDrop" data-arg="${i}">버리기</button></div></div>`;
  const fields = [...SHEET_SETTING, ...held.map(([x]) => x.field).filter((fl) => !SHEET_SETTING.includes(fl))];
  const rows = [...new Set(fields)].map((fl) => {
    const v = at.c[fl];
    const mine = held.filter(([x]) => x.field === fl);
    if (!v && !mine.length && !at.changed.has(fl)) return '';
    const now = at.changed.has(fl) ? `<div class="small">지금: ${esc(c[fl] || '(비어 있음)')}</div>` : '';
    return `<div class="csh-row"><span>${esc(scLabel(fl))}</span><div class="csh-val"><div class="${v ? '' : 'small'}">${esc(v || '(비어 있음)')}</div>${now}${mine.map(heldBox).join('')}</div></div>`;
  }).join('');
  return `<section class="card"><div class="between"><h2>설정</h2><span class="small">고정 값${at.changed.size ? ` · 이 시점 뒤에 ${at.changed.size}칸 바뀜` : ''}</span></div>
    <div>${rows || '<div class="small">채운 설정이 없어요</div>'}</div>
    <div class="small">본문에서 바뀐 설정은 작가가 골라야 바뀌어요.</div></section>`;
}

// ----- 인물 카드에서 고치는 칸: 작가 메모와 AI에 넣는 방식. 설정 도우미는 이야기 뼈대만 다룬다 -----

/** 신체 프로필. 미성년 인물은 쓰리사이즈 칸을 두지 않는다 */
function bodyFields(c, b) {
  if (!c.body || typeof c.body !== 'object') c.body = {};  // 예전 화면에서 만든 인물도 칸을 고칠 수 있게
  const minor = isMinorAge(c.age);
  const filled = bodyRows(c).length;
  const open = (S.bodySug || {})[c.id] || (S.bodyOpen || {})[c.id];  // 제안을 받거나 적용한 뒤 다시 그려도 펼친 채로
  return `<details${open ? ' open' : ''}><summary>신체 프로필 <span class="small">${filled ? `· ${filled}칸 채움 ` : ''}· 인물 카드에만 보여요</span></summary><div style="display:flex;flex-direction:column;gap:10px;padding-top:8px">
    <div class="grid-2">${input('키', b + '.body.height', { placeholder: '예: 165cm' })}${input('몸무게', b + '.body.weight', { placeholder: '예: 48kg' })}</div>
    <div class="grid-2">${input('체형', b + '.body.build', { placeholder: '예: 마른 근육형' })}${minor ? '' : input('쓰리사이즈', b + '.body.measurements', { placeholder: '예: 84-58-86' })}</div>
    ${minor ? '<div class="small">나이로 보아 미성년 인물이라 쓰리사이즈 칸은 두지 않아요.</div>' : ''}
    ${input('신체 특징', b + '.body.features', { rows: 2, placeholder: '예: 왼손잡이, 오른쪽 어깨에 화상 자국' })}
    <div class="row"><button type="button" class="btn small" data-action="bodyAI" data-arg="${esc(c.id)}">AI 제안 받기</button><span class="small">설정에 맞춰 칸을 제안해요. 고른 칸만 적용해요${minor ? ' · 쓰리사이즈는 제안하지 않아요' : ''}</span></div>
    ${bodySuggestCard(c)}
    <div class="small">AI 프롬프트에는 넣지 않아요. 본문에 이어지게 할 외모는 설정 도우미의 '외모' 칸에 적어요.</div></div></details>`;
}

/** 신체 프로필 AI 제안: 칸별로 지금 값과 비교해 고른다. 비어 있는 칸만 기본으로 고른다 */
function bodySuggestCard(c) {
  const s = (S.bodySug || {})[c.id];
  if (!s) return '';
  const minor = isMinorAge(c.age);
  const rows = BODY_FIELDS.filter(([k]) => (s[k] || '').trim() && !(k === 'measurements' && minor)).map(([k, label]) => {
    const now = ((c.body || {})[k] || '').trim();
    const same = now === s[k].trim();
    return `<label class="body-sug"><input type="checkbox" data-body-pick="${esc(c.id)}" value="${k}"${now || same ? '' : ' checked'}${same ? ' disabled' : ''}>
      <span><strong>${label}</strong> ${now ? `<span class="before">${esc(now)}</span> → ` : ''}<span class="after">${esc(s[k])}</span>${same ? ' <span class="small">지금과 같아요</span>' : ''}</span></label>`;
  }).join('');
  return `<div class="note info" style="display:flex;flex-direction:column;gap:8px"><strong>AI 제안</strong>${s.note ? `<span>${esc(s.note)}</span>` : ''}
    ${rows || '<span>제안한 칸이 없어요</span>'}
    <div class="row"><button type="button" class="btn small primary" data-action="bodyApply" data-arg="${esc(c.id)}"${rows ? '' : ' disabled'}>고른 칸 적용</button><button type="button" class="btn small" data-action="bodyDismiss" data-arg="${esc(c.id)}">닫기</button></div></div>`;
}

// 인물을 AI에 넣는 방식 (Character.context). 인과율 요소 화면(causal.js)의 'AI에 넣기'와 같은 고르기이고,
// 인물은 '관련 있을 때' 대신 '등장할 때'다. 고르는 규칙은 서버 context.core_ids · off_ids. 설정 도우미 접힌 줄의 표시는 setup.js charCtxMark
const CHAR_CTX = [['auto', '등장할 때'], ['always', '항상'], ['off', '넣지 않음']];
const CHAR_CTX_HINT = {
  auto: '등장할 때: 주역은 매 화, 조연 · 단역은 플롯에 나오는 화에만 넣어요.',
  always: '항상: 비중과 상관없이 매 화 설정을 넣어요. 장편에서 글자 예산을 넘기면 그 화 조연 · 단역 설정을 대신 빼요.',
  off: '넣지 않음: 본문 쓰기, 검수, 상태 정리, 플롯 기획에 설정 · 상태 · 관계를 넣지 않아요. 플롯에 나오면 이름만 넣어요.',
};

/** AI에 넣기 고르기 */
function charContextField(c) {
  const now = c.context || 'auto';
  return `<div class="field"><span class="label">AI에 넣기</span><div class="seg" role="group" aria-label="AI에 넣기">${CHAR_CTX.map(([k, l]) => `<button type="button" aria-pressed="${now === k}" data-action="charContext" data-arg="${esc(`${c.id}|${k}`)}">${l}</button>`).join('')}</div>
    <span class="small">${CHAR_CTX_HINT[now]}</span></div>`;
}

/** 'AI · 서술 · 신체 · 삽화' 카드. 읽는 모양이 기본이고 '고치기'로 이 카드만 편다(Card '읽기 카드와 고치기 카드').
    고치는 칸은 지금 설정(보는 시점과 상관없이)이고 저장 띠로 저장한다 */
function castEditCard(c) {
  const open = S.castEdit === c.id;
  const btn = `<button type="button" class="btn small" data-action="castEditToggle" data-arg="${esc(c.id)}" aria-expanded="${open}">${open ? '다 고쳤어요' : '고치기'}</button>`;
  const head = `<div class="pf-head"><h2>AI · 서술 · 신체 · 삽화${open ? ' <span class="small pf-state">고치는 중</span>' : ''}</h2>${btn}</div>`;
  if (open) {
    const b = `characters.${P().characters.indexOf(c)}`;
    return `<section class="card pf-sec editing" id="csh-edit" tabindex="-1">${head}
      <div class="cast-edit">${charContextField(c)}${voiceField(c, b)}${bodyFields(c, b)}${visualFields(c)}</div></section>`;
  }
  const none = '<span class="muted">비어 있음</span>';
  const ctx = c.context || 'auto';
  const povs = P().episodes.filter((e) => (povChar(e.plot.number).c || {}).id === c.id).length;
  const body = bodyRows(c).map(([, label, v]) => `${label} ${v}`).join(' · ');
  const look = ((ilVisual(c.id) || {}).look || []).join(', ');
  return `<section class="card pf-sec" id="csh-edit" tabindex="-1">${head}
    <dl class="pf-dl">
      <dt>AI에 넣기</dt><dd>${esc(CHAR_CTX.find(([k]) => k === ctx)[1])}<div class="small">${esc(CHAR_CTX_HINT[ctx])}</div></dd>
      <dt>서술 말투</dt><dd>${c.narration_voice ? esc(c.narration_voice) : none}<div class="small">${povs ? `이 인물이 시점 인물인 ${povs}화의 지문에 넣어요` : '이 인물이 시점 인물인 화가 아직 없어요'}</div></dd>
      <dt>신체</dt><dd>${body ? esc(body) : none}<div class="small">인물 카드에만 보여요 · AI에 넣지 않아요</div></dd>
      <dt>삽화 태그</dt><dd>${look ? `<span class="mono">${esc(look)}</span>` : none}</dd>
    </dl></section>`;
}

/** 인물 원. size: '' 목록 줄 36px · 's' 목차 24px · 'l' 인물 머리 64px */
function castAva(c, size = '') {
  return `<span class="cast-ava${size ? ' ' + size : ''} t-${c.tier || 'main'}" aria-hidden="true">${esc((c.name || c.id).slice(0, 1))}</span>`;
}

function castHead(c, f, at) {
  const apps = (S.cast.appearances || {})[c.id] || [];
  const pov = apps.filter((a) => a.pov).length;
  const partners = new Set((f ? f.ties : []).filter((t) => t.source === c.id || t.target === c.id).map((t) => (t.source === c.id ? t.target : t.source)));
  const held = (P().setting_held || []).filter((x) => x.character_id === c.id).length;
  const facts = [
    apps.length ? `등장 ${apps.length}화 (${apps[0].n}~${apps[apps.length - 1].n}화)` : '플롯에 나오는 화가 아직 없어요',
    pov ? `시점 인물 ${pov}화` : '',
    `관계 ${partners.size}명`,
    c.first_ep ? `${c.first_ep}화에 처음 등장` : '',
  ].filter(Boolean).join(' · ');
  return `<section class="card cast-head">
    ${castAva(c, 'l')}
    <div class="cast-head-id">
      <div class="between"><div class="row" style="align-items:baseline"><h2>${esc(c.name || c.id)}</h2><span class="small">${[c.age, c.gender].filter(Boolean).map(esc).join(' · ')}</span></div>
        <a class="btn small" href="${base()}/setup/${enc(c.id)}">설정 도우미에서 고치기</a></div>
      <div class="row" style="gap:6px"><span class="chip confirmed">${TIER_NAME[c.tier || 'main']}</span>${c.role ? `<span class="chip">${esc(c.role)}</span>` : ''}${at.c.arc ? `<span class="chip csh-arc">아크 · ${esc(at.c.arc)}</span>` : ''}${held ? `<span class="chip warn" title="남겨 둔 설정 바꾸기 제안. 아래 설정 카드에서 골라요">제안 ${held}</span>` : ''}</div>
      <div class="small">${facts}</div>
      ${apps.length ? `<div class="cast-strip-wrap">${castStrip(c.id, { mark: f && f.episode })}</div>` : ''}
    </div></section>`;
}

/** 인물 쪽: 보는 시점의 인물 하나를 한 열에. 위에서부터 자주 보는 것 → 고치는 것 → 기록 */
function castCharPage(c) {
  const f = castFrameNow();
  const at = scAt(c, f ? f.episode : Infinity);
  return `${castHead(c, f, at)}${castSheetState(c, f)}${castSheetStats(c, f)}${castSheetRels(c, f)}${castSheetSecrets(c, f)}${castSheetSettings(c, f, at)}${castEditCard(c)}${castTimeline(c)}${scLogCard(c)}${addressHeldCard(c)}`;
}

// ----- 쌍 상세 -----

function castChart(series, lo, hi, opts = {}) {
  // 시점이 40개를 넘으면 고른 시점 앞뒤 30개만 그린다 (칸이 몇 px 로 줄지 않게). '전체' 를 누르면 다 그린다
  const all = S.cast.frames;
  const a0 = all.length > 40 && !S.castChartAll ? Math.max(0, Math.min(S.castFrame - 15, all.length - 31)) : 0;
  const a1 = all.length > 40 && !S.castChartAll ? Math.min(all.length - 1, a0 + 30) : all.length - 1;
  const fs = all.slice(a0, a1 + 1);
  series = series.map((s) => ({ ...s, values: s.values.slice(a0, a1 + 1) }));
  if (opts.notes) opts = { ...opts, notes: opts.notes.slice(a0, a1 + 1) };
  const at = S.castFrame - a0;
  const W = 520;
  const H = opts.h || 120;
  const L = 34;
  const T = 8;
  const B = 22;
  const pw = W - L - 8;
  const ph = H - T - B;
  const X = (i) => L + (fs.length < 2 ? pw / 2 : (i / (fs.length - 1)) * pw);
  const Y = (v) => T + (1 - (v - lo) / (hi - lo)) * ph;
  const out = [];
  (opts.grid || [lo, hi]).forEach((g) => out.push(`<line class="cc-grid${g === 0 && lo < 0 ? ' zero' : ''}" x1="${L}" x2="${L + pw}" y1="${Y(g)}" y2="${Y(g)}"></line><text class="cc-tick" x="${L - 5}" y="${Y(g) + 3}" text-anchor="end">${opts.fmt ? opts.fmt(g) : g}</text>`));
  out.push(`<line class="cc-now" x1="${X(at)}" x2="${X(at)}" y1="${T}" y2="${T + ph}"></line>`);
  series.forEach((s) => {
    const pts = s.values.map((v, i) => (v === null ? null : [X(i), Y(v)]));
    let d = '';
    pts.forEach((pt, i) => { if (pt) d += `${d && pts[i - 1] ? 'L' : 'M'}${pt[0].toFixed(1)} ${pt[1].toFixed(1)} `; });
    if (d) out.push(`<path class="cc-line" d="${d}" style="stroke:${s.color}"></path>`);
    const cur = pts[at];
    if (cur) out.push(`<circle cx="${cur[0]}" cy="${cur[1]}" r="4" style="fill:${s.color}" class="cc-dot"></circle>`);
  });
  const every = Math.max(1, Math.ceil(fs.length / 10));
  fs.forEach((f, i) => {
    if (i % every === 0 || i === fs.length - 1) out.push(`<text class="cc-tick" x="${X(i)}" y="${H - 4}" text-anchor="${i === 0 ? 'start' : i === fs.length - 1 ? 'end' : 'middle'}">${f.episode ? f.episode + '화' : '시작'}</text>`);
  });
  // 시점마다 세로 칸: 올리면 값, 누르면 그 시점으로
  const colW = fs.length < 2 ? pw : pw / (fs.length - 1);
  fs.forEach((f, i) => {
    const tip = `${frameLabel(f)}\n` + series.map((s) => `${s.label}: ${s.values[i] === null ? '-' : (opts.fmt ? opts.fmt(s.values[i]) : s.values[i].toFixed(2))}`).join('\n') + (opts.notes && opts.notes[i] ? '\n' + opts.notes[i] : '');
    out.push(`<rect class="cc-col" x="${X(i) - colW / 2}" y="${T}" width="${colW}" height="${ph}" data-action="castGo" data-arg="${i + a0}"><title>${esc(tip)}</title></rect>`);
  });
  const range = all.length > 40 ? `<div class="small">${S.castChartAll ? `전체 ${all.length}개 시점` : `${frameLabel(fs[0])} ~ ${frameLabel(fs[fs.length - 1])}`} <button type="button" class="link-btn" data-action="castChartAll">${S.castChartAll ? '고른 시점 주변만' : '전체 보기'}</button></div>` : '';
  return `<svg class="cast-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.label || '')}">${out.join('')}</svg>${range}`;
}

/** 관계 수치 직접 보정. AI가 아니라 '수동보정' 사건으로 기록해 재생할 수 있다 (POST /ties/adjust, pipeline.adjust_tie). */
function tieFixForm(a, b, names) {
  const fs = S.cast.frames;
  const last = fs[fs.length - 1];
  const n = Math.max(0, ...P().episodes.filter((e) => e.status === 'finalized').map((e) => e.plot.number));
  const row = (src, dst, label, k) => {
    const t = (last && tieOf(last, src, dst)) || { warmth: 0, trust: 0.5 };
    return `<div class="grid-2" style="align-items:end">
      <div class="field"><label for="tf-w${k}">${esc(label)} 온기 <output id="tf-w${k}o">${Number(t.warmth).toFixed(2)}</output></label><input id="tf-w${k}" type="range" min="-1" max="1" step="0.05" value="${t.warmth}" oninput="document.getElementById('tf-w${k}o').textContent=Number(this.value).toFixed(2)"></div>
      <div class="field"><label for="tf-t${k}">신뢰 <output id="tf-t${k}o">${Number(t.trust).toFixed(2)}</output></label><input id="tf-t${k}" type="range" min="0" max="1" step="0.05" value="${t.trust}" oninput="document.getElementById('tf-t${k}o').textContent=Number(this.value).toFixed(2)"></div>
      <button type="button" class="btn small" data-action="tieFix" data-arg="${esc(`${src}|${dst}|${k}`)}">이 방향 보정하기</button></div>`;
  };
  return `<details class="tie-fix"><summary class="small">수치 직접 보정</summary>
    <div class="small" style="margin:6px 0">AI가 아니라 '수동보정' 사건으로 기록돼요. 마지막 반영 화(${n}화)에 붙고, 반영 취소로 되돌릴 수 있어요.</div>
    ${row(a, b, names[0], 0)}${row(b, a, names[1], 1)}</details>`;
}

function castPairDetail(a, b) {
  const f = castFrameNow();
  const fs = S.cast.frames;
  const pr = pairOf(f, a, b);
  const ab = (x) => fs.map((fr) => { const t = tieOf(fr, a, b); return t ? x(t) : null; });
  const ba = (x) => fs.map((fr) => { const t = tieOf(fr, b, a); return t ? x(t) : null; });
  const evs = (P().events || []).filter((e) => (e.actor === a && e.target === b) || (e.actor === b && e.target === a));
  const notes = fs.map((fr) => evs.filter((e) => e.episode === fr.episode && fr.episode).map((e) => `${charName(e.actor)}→${charName(e.target)} ${e.kind}`).join(', '));
  const names = [`${charName(a)} → ${charName(b)}`, `${charName(b)} → ${charName(a)}`];
  const legend = `<div class="legend">${names.map((n, i) => `<span><i style="background:${PAIR_COLORS[i]};height:3px;width:16px;border-radius:2px"></i>${esc(n)}</span>`).join('')}</div>`;
  const two = (x) => [{ label: names[0], color: PAIR_COLORS[0], values: ab(x) }, { label: names[1], color: PAIR_COLORS[1], values: ba(x) }];
  const tension = fs.map((fr) => { const q = pairOf(fr, a, b); return q ? q.tension : null; });
  const evList = evs.slice().sort((x, y) => x.episode - y.episode).map((e) => `<li class="cast-ev ${GOOD_EVENTS.includes(e.kind) ? 'good' : 'bad'}"><strong>${e.episode}화</strong> ${esc(charName(e.actor))} → ${esc(charName(e.target))} · ${esc(e.kind)} ${INTENSITY[e.intensity] || ''}${e.quote ? `<br><span class="small">“${esc(e.quote)}”</span>` : ''}</li>`).join('');
  const multi = fs.length > 1;
  const who = (id) => { const c = castChar(id); return `<button type="button" class="cast-who" data-action="castShow" data-arg="${esc('c:' + id)}">${c ? castAva(c) : ''}${esc(charName(id))}</button>`; };
  return `<section class="card">
    <div class="between"><div><div class="eyebrow">두 사람</div><h2 class="cast-pair-h">${who(a)}<span aria-hidden="true">↔</span><span class="sr-only">와</span>${who(b)}</h2>
      <div class="row" style="margin-top:6px">${pr && pr.type ? `<span class="chip">${esc(pr.type)}</span>` : '<span class="small">관계 설정 없이 사건으로 생긴 관계</span>'}<span class="small">${tensionText(pr)}</span></div></div>
      <a class="btn small ghost" href="${base()}/setup">관계 설정 고치기</a></div>
    ${pr && pr.description ? `<div class="small">${esc(pr.description)}</div>` : ''}
    <dl class="pf-dl cast-dirs"><dt>${esc(names[0])}</dt><dd>${tieText(tieOf(f, a, b))}</dd><dt>${esc(names[1])}</dt><dd>${tieText(tieOf(f, b, a))}</dd></dl>
    ${tieFixForm(a, b, names)}
    ${addressCard(a, b)}
  </section>
  <section class="card"><div class="between"><h2>추이</h2>${multi ? legend : ''}</div>
    ${multi ? `<h3>온기</h3>${castChart(two((t) => t.warmth), -1, 1, { grid: [-1, 0, 1], notes, label: '온기 추이' })}
    <h3>신뢰</h3>${castChart(two((t) => t.trust), 0, 1, { grid: [0, 0.5, 1], notes, label: '신뢰 추이' })}
    <h3>긴장 <span class="small" style="font-weight:400">0~10, 3 · 5 · 7에서 보통 · 높음 · 매우 높음</span></h3>${castChart([{ label: '긴장', color: 'var(--text-2)', values: tension }], 0, 10, { grid: [0, 3, 5, 7, 10], fmt: (v) => (Number.isInteger(v) ? String(v) : v.toFixed(1)), notes, label: '긴장 추이', h: 110 })}
    <div class="small">칸에 올리면 그 시점 값과 사건, 누르면 보는 시점이 그 화로 가요.</div>` : '<div class="small">1화를 반영하면 화별 추이 그래프가 나와요.</div>'}
  </section>
  <section class="card"><h2>두 사람 사이 관계 사건 <span class="small" style="font-weight:400">${evs.length}개</span></h2>
    ${evList ? `<ul class="cast-ul">${evList}</ul>` : '<div class="small">아직 없어요</div>'}
  </section>`;
}

/** 관계도에서 고른 인물 · 두 사람 한 줄: 무엇을 골랐는지와 그 쪽으로 가는 버튼 */
function castMapSel(f) {
  if (S.castSel.startsWith('p:')) {
    const [a, b] = S.castSel.slice(2).split('|');
    const pr = pairOf(f, a, b);
    return `<div class="cast-pick"><span class="cast-pick-who"><strong>${esc(charName(a))} ↔ ${esc(charName(b))}</strong><span class="small">${[pr && pr.type, tensionText(pr)].filter(Boolean).map(esc).join(' · ') || '고른 두 사람'}</span></span>
      <button type="button" class="btn small" data-action="castShow" data-arg="${esc(S.castSel)}">두 사람 보기</button></div>`;
  }
  const c = castChar(S.castSel.slice(2));
  if (!c) return '';
  const st = castStateOf(f, c.id);
  const bits = [TIER_NAME[c.tier || 'main'], c.role, castPresent(c, f) ? (st && st.emotional_state) : `${c.first_ep}화에 처음 나와요`].filter(Boolean);
  return `<div class="cast-pick">${castAva(c)}<span class="cast-pick-who"><strong>${esc(c.name || c.id)}</strong><span class="small">${bits.map(esc).join(' · ')}</span></span>
    <button type="button" class="btn small" data-action="castShow" data-arg="${esc('c:' + c.id)}">인물 카드 보기</button></div>`;
}

/** 관계도 그림 · 크기 버튼 · 범례 · 목록. 끌어 옮기기와 시점 바꾸기는 이것만 다시 그린다 */
function castStage() {
  const f = castFrameNow();
  const z = CAST_ZOOM[S.castZoom] || 1;
  const zoom = `<div class="cast-zoom" role="group" aria-label="관계도 크기">
    <button type="button" class="btn small icon-btn" data-action="castZoom" data-arg="1" aria-label="크게 보기"${S.castZoom >= CAST_ZOOM.length - 1 ? ' disabled' : ''}>+</button>
    <button type="button" class="btn small icon-btn" data-action="castZoom" data-arg="-1" aria-label="작게 보기"${S.castZoom ? '' : ' disabled'}>−</button></div>`;
  return `${castMapSel(f)}<div class="cast-graph-wrap" style="--cast-zoom:${z}">${castGraph()}</div>
    <div class="between">${castDenseNote(f) || '<span></span>'}${zoom}</div>${castLegend()}${castTieList(f)}${castTriads(f)}`;
}

function castMapPage() {
  const minors = P().characters.some((c) => c.tier === 'minor');
  return `<section class="card cast-map">
    ${relationHeader('관계도')}
    <div class="row">${minors ? `<label class="row" style="gap:6px;font-size:0.8125rem"><input type="checkbox" data-cast-minor${S.castMinor ? ' checked' : ''}>단역도 보기</label>` : ''}
      <button type="button" class="btn small ghost" data-action="castResetPos"${Object.keys(S.castPos || {}).length ? '' : ' disabled'}>배치 처음대로</button>
      <span class="small">인물이나 선을 누르면 골라요. 인물을 끌어 자리를 옮겨요.</span></div>
    <div id="cast-stage">${castStage()}</div>
  </section>`;
}

/** 인물이 많아 선을 덜 그렸으면 몇 개를 뺐는지와 '모든 선 보기'. 인물이 적으면 빈칸 */
function castDenseNote(f) {
  const chars = castShown();
  if (chars.length <= CAST_DENSE) return '';
  const shown = new Set(chars.map((c) => c.id));
  const ties = (f ? f.ties : []).filter((t) => shown.has(t.source) && shown.has(t.target));
  const near = castNear(chars);
  const cut = near ? ties.filter((t) => !near(t.source, t.target)).length : 0;
  const box = `<label class="row" style="gap:6px;font-size:0.8125rem"><input type="checkbox" data-cast-allties${S.castAllTies ? ' checked' : ''}>모든 선 보기</label>`;
  const text = !ties.length ? '' : S.castAllTies ? `선 ${ties.length}개를 모두 그렸어요.`
    : cut ? `인물이 ${chars.length}명이라 고른 인물과 이어진 선만 그렸어요. 선 ${ties.length}개 중 ${cut}개를 뺐어요.` : `고른 인물과 이어진 선만 그려요. 이 시점에는 뺀 선이 없어요.`;
  return `<div class="row" style="gap:10px">${box}<span class="small">${text}</span></div>`;
}

/** 지금 쪽의 내용 */
function castPage() {
  if (S.castView === 'table') return castTable();
  if (S.castView === 'map') return castMapPage();
  if (S.castView === 'pair') {
    const [a, b] = S.castSel.slice(2).split('|');
    return castPairDetail(a, b);
  }
  const c = castChar(S.castSel.slice(2));
  return c ? castCharPage(c) : '<section class="card"><div class="small">목차에서 인물을 고르세요.</div></section>';
}

/** 목차: 관계도 · 등장표, 그리고 비중별 인물. 줄 끝은 남겨 둔 제안 수나 처음 나오는 화 */
function castToc() {
  const p = P();
  const f = castFrameNow();
  const key = castKey();
  const pairIds = S.castView === 'pair' ? S.castSel.slice(2).split('|') : [];
  const item = (k, inner, extra = '') => `<button type="button" class="outline-item${pairIds.includes(k.slice(2)) ? ' in-pair' : ''}" data-action="castShow" data-arg="${esc(k)}"${key === k ? ' aria-current="page"' : ''}${extra}>${inner}</button>`;
  const held = (id) => (p.setting_held || []).filter((x) => x.character_id === id).length;
  const person = (c) => {
    const n = held(c.id);
    const st = n ? `<span class="chip warn">제안 ${n}</span>` : c.first_ep > 1 ? `<span class="st">${c.first_ep}화~</span>` : '';
    return item('c:' + c.id, `${castAva(c, 's')}<span class="tl">${esc(c.name || c.id)}</span>${st}`);
  };
  const ties = f ? f.ties.length : 0;
  const out = [
    item('map', `<span class="cast-ic" aria-hidden="true">◎</span><span class="tl">관계도</span>${ties ? `<span class="st">선 ${ties}</span>` : ''}`),
    item('table', '<span class="cast-ic" aria-hidden="true">▤</span><span class="tl">등장표</span>'),
  ];
  ['main', 'support', 'minor'].forEach((tier) => {
    const list = p.characters.filter((c) => (c.tier || 'main') === tier);
    if (!list.length) return;
    const fold = tier === 'minor' && list.length > CAST_MINOR_FOLD && !S.castMinorOpen && !list.some((c) => key === 'c:' + c.id || pairIds.includes(c.id));
    out.push(`<div class="outline-h">${TIER_NAME[tier]} ${list.length}</div>`);
    if (fold) {
      out.push(`<button type="button" class="outline-item" data-action="castMinorFold" data-outline-keep aria-expanded="false"><span class="cast-ic" aria-hidden="true">▸</span><span class="tl">${list.slice(0, 3).map((c) => esc(c.name || c.id)).join(' · ')}${list.length > 3 ? ' …' : ''}</span><span class="st">펼치기</span></button>`);
    } else out.push(...list.map(person));
  });
  const nowC = S.castView === 'char' ? castChar(S.castSel.slice(2)) : null;
  const now = S.castView === 'table' ? '등장표' : S.castView === 'map' ? '관계도'
    : nowC ? `${castAva(nowC, 's')} ${esc(nowC.name || nowC.id)} · ${TIER_NAME[nowC.tier || 'main']}` : pairIds.map((id) => esc(charName(id))).join(' ↔ ');
  return outlineNav({ id: 'cast-toc', label: '인물 목차', now, body: out.join('') });
}

/** 시점만 바뀌면 시점 띠는 두고 지금 쪽과 목차만 다시 그린다 (끄는 중인 막대를 지우지 않게) */
function castRefresh() {
  const page = document.getElementById('cast-page');
  if (!page) return;
  if (S.castView === 'map' && document.getElementById('cast-stage')) document.getElementById('cast-stage').innerHTML = castStage();
  else page.innerHTML = castPage();
  outlineRefresh('cast-toc', castToc());
  const label = document.getElementById('cast-frame-label');
  if (label) label.innerHTML = castBarLabel(castFrameNow());
  const range = document.querySelector('[data-cast-frame]');
  if (range) {
    if (Number(range.value) !== S.castFrame) range.value = S.castFrame;
    range.setAttribute('aria-valuetext', frameLabel(castFrameNow()));
  }
  const play = document.getElementById('cast-play');
  if (play) play.textContent = castPlayLabel();
  castSyncUrl();
}

// ----- 등장표 -----

function castTable() {
  const p = P();
  const total = Math.max(p.meta.target_episodes, ...p.episodes.map((e) => e.plot.number), 1);
  const step = total <= 40 ? 18 : total <= 120 ? 8 : 6;  // 칸이 6px 보다 좁아지지 않게. 넘치면 가로로 스크롤한다
  const left = 150;
  const top = 34;
  const rowH = 28;
  const order = ['main', 'support', 'minor'];
  const apps = S.cast.appearances || {};
  const chars = p.characters.slice().sort((x, y) => order.indexOf(x.tier) - order.indexOf(y.tier) || ((apps[x.id] || [])[0] || { n: 9999 }).n - ((apps[y.id] || [])[0] || { n: 9999 }).n);
  const width = left + total * step + 70;
  const height = top + chars.length * rowH + 22;
  const out = [];
  const bands = serial() ? (p.story_arcs || []).map((a) => [a.start_ep, a.end_ep, `아크 ${a.number}`, 'act-' + (((a.number - 1) % 4) + 1)])
    : (p.arc || []).map((a) => [a.start_ep, a.end_ep, a.name, actClass(a.name)]);
  bands.forEach(([a, b, label, cls]) => {
    const x = left + (a - 1) * step;
    const w = Math.max(2, (b - a + 1) * step - 2);
    out.push(`<g class="lm-band ${cls}"><rect x="${x + 1}" y="4" width="${w}" height="20" rx="5"></rect>${w > 30 ? `<text x="${x + 6}" y="18">${esc(label)}</text>` : ''}</g>`);
  });
  chars.forEach((c, i) => {
    const y = top + i * rowH;
    const rows = apps[c.id] || [];
    const m = new Map(rows.map((a) => [a.n, a]));
    out.push(`<g class="ct-row" data-action="castOpen" data-arg="${esc(c.id)}" tabindex="0" role="button" aria-label="${esc((c.name || c.id) + ' 인물 카드 보기')}">
      <rect class="ct-hit" x="0" y="${y}" width="${width}" height="${rowH}"></rect>
      <text class="ct-name" x="10" y="${y + 18}">${esc(c.name || c.id)}</text><text class="ct-tier" x="${left - 10}" y="${y + 18}" text-anchor="end">${TIER_NAME[c.tier || 'main']}</text></g>`);
    for (let n = 1; n <= total; n++) {
      const a = m.get(n);
      const x = left + (n - 1) * step;
      if (!a) continue;
      const e = ep(n);
      out.push(`<rect class="cs-on ${a.status}" x="${x + 0.5}" y="${y + 5}" width="${Math.max(1.5, step - 1.5)}" height="${rowH - 10}" rx="${step > 8 ? 3 : 1}"><title>${esc(`${c.name} · ${n}화 ${e ? e.plot.title : ''} · ${STATUS[a.status]}${a.pov ? ' · 시점 인물' : ''}`)}</title></rect>`);
      if (a.pov) out.push(`<circle class="ct-pov" cx="${x + step / 2}" cy="${y + rowH / 2}" r="${Math.max(1.5, Math.min(4, step / 4))}"></circle>`);
    }
    out.push(`<text class="ct-count" x="${left + total * step + 8}" y="${y + 18}">${rows.length}화</text>`);
  });
  const every = step >= 16 ? 1 : step >= 8 ? 5 : 10;
  for (let n = 1; n <= total; n++) {
    if (n === 1 || n % every === 0) out.push(`<text class="lm-tick" x="${left + (n - 0.5) * step}" y="${height - 6}" text-anchor="middle">${n}</text>`);
  }
  const legend = `<div class="legend">${['draft', 'confirmed', 'written', 'finalized'].map((k) => `<span><i class="cs-key ${k}"></i>${STATUS[k]}</span>`).join('')}<span><i style="background:var(--text);border-radius:50%;width:8px;height:8px"></i>시점 인물</span></div>`;
  return `<section class="card">
    <div class="between"><h2>등장표</h2><span class="small">플롯의 등장 인물 기준. 이름을 누르면 인물 카드를 열어요</span></div>
    <div class="line-map-wrap"><svg class="line-map cast-table" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="group" aria-label="인물별 등장 화">${out.join('')}</svg></div>${legend}
  </section>`;
}

// ----- 화면 -----

function viewCast() {
  const p = P();
  const desc = '인물 설정, 화마다 바뀐 상태, 방향 관계와 사건을 한곳에서 봐요. 관계 값은 반영한 화의 관계 사건으로 Canon이 계산해요.';
  const head = header('작품 도구', '인물 · 관계도', desc, `<a class="btn" href="${base()}/setup">인물 · 관계 설정</a>`);
  if (!p.characters.length) return `${head}<div class="card empty"><p>아직 인물이 없어요.</p><a class="btn primary" href="${base()}/setup">설정 도우미에서 인물 만들기</a></div>`;
  if (!S.cast) return `${head}<div class="small">불러오는 중…</div>`;
  if (S.cast.error) {
    return `${head}<div class="card empty" role="alert"><p>인물 화면을 계산하지 못했어요.</p><div class="note err">${esc(S.cast.error)}</div>
      <div class="row"><button type="button" class="btn primary" data-action="castRetry">다시 불러오기</button><a class="btn" href="${base()}/setup">설정 도우미에서 인물 보기</a></div></div>`;
  }
  const main = `<div class="cast-col">${S.castView === 'table' ? '' : castBar()}<div id="cast-page" class="cast-page">${castPage()}</div></div>`;
  return `${head}${outlineDoc(castToc(), main, { wide: S.castView !== 'char', cls: 'cast-wrap' })}`;
}

// ----- 동작 -----

Object.assign(actions, {
  castChartAll() {
    S.castChartAll = !S.castChartAll;
    render();
  },
  async tieFix(arg) {
    const [source, target, k] = String(arg).split('|');
    const warmth = Number($(`#tf-w${k}`).value);
    const trust = Number($(`#tf-t${k}`).value);
    if (!confirm(`${charName(source)} → ${charName(target)} 관계를 온기 ${warmth.toFixed(2)}, 신뢰 ${trust.toFixed(2)} 값으로 보정할까요?`)) return;
    await run('보정하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/ties/adjust`, { source, target, warmth, trust });
      await castLoad();
      toast('관계를 보정했어요. 수동보정 사건으로 남았어요');
    });
  },
  /** 쪽 옮기기: 'map' · 'table' · 'c:<인물>' · 'p:<a>|<b>'. 목차 줄 · 관계 줄 · 고른 줄 버튼이 부른다 */
  castShow(v) {
    castStop();
    if (v === 'map' || v === 'table') S.castView = v;
    else {
      S.castSel = v;
      S.castView = v.startsWith('p:') ? 'pair' : 'char';
      S.castAllTl = false;
    }
    render();
    castSyncUrl();
    window.scrollTo(0, 0);
  },
  /** 관계도에서 인물 · 선 고르기: 쪽은 그대로 두고 고른 줄과 선만 다시 그린다 */
  castMapPick(v) {
    if (castDragged) return;
    S.castSel = v;
    castRefresh();
  },
  castMinorFold() {
    S.castMinorOpen = true;
    outlineRefresh('cast-toc', castToc());
  },
  castZoom(d) {
    S.castZoom = Math.min(CAST_ZOOM.length - 1, Math.max(0, S.castZoom + Number(d)));
    const stage = document.getElementById('cast-stage');
    if (stage) stage.innerHTML = castStage();
  },
  castEditToggle(id) {
    S.castEdit = S.castEdit === id ? '' : id;
    render();
    document.getElementById('csh-edit')?.focus({ preventScroll: true });
  },
  async castRetry() {
    S.cast = null;
    render();
    await castLoad(S.route[3]);
    render();
  },
  // 다른 화면(address.js 남겨 둔 호칭 줄, 등장표 줄)이 부르는 옛 이름
  castPick(v) { actions.castShow(v); },
  castOpen(id) { actions.castShow('c:' + id); },
  castStep(d) {
    castStop();
    S.castFrame = Math.min(S.cast.frames.length - 1, Math.max(0, S.castFrame + Number(d)));
    castRefresh();
  },
  castGo(i) {
    castStop();
    S.castFrame = Number(i);
    castRefresh();
  },
  castPlay() {
    if (castTimer) {
      castStop();
      castRefresh();
      return;
    }
    if (S.castFrame >= S.cast.frames.length - 1) S.castFrame = 0;  // 끝에 있을 때만 처음으로. 아니면 지금 시점부터 이어 간다
    castTimer = setInterval(() => {
      if (!document.getElementById('cast-page') || S.castFrame >= S.cast.frames.length - 1) {
        castStop();
        castRefresh();
        return;
      }
      S.castFrame++;
      castRefresh();
    }, 900);
    castRefresh();
  },
  castSheet(id) { actions.castShow('c:' + id); },
  castPair(arg) { actions.castShow('p:' + arg); },
  charContext(arg) {
    const k = String(arg).slice(String(arg).lastIndexOf('|') + 1);
    const c = castChar(String(arg).slice(0, String(arg).lastIndexOf('|')));
    if (!c) return;
    c.context = k;
    markDirty();
    render();
  },
  castTheme(v) {
    S.castTheme = v === 'system' ? 'system' : '';
    try { localStorage.setItem('canon-cast-theme:' + S.name, S.castTheme); } catch (e) { /* 이 브라우저에서만 쓰는 편의 기능 */ }
    castRefresh();
  },
  castAllTl() {
    S.castAllTl = true;
    castRefresh();
  },
  castResetPos() {
    S.castPos = {};
    try { localStorage.removeItem('canon-cast-pos:' + S.name); } catch (e) { /* 저장소가 막혀도 화면은 그대로 */ }
    render();
  },
});

document.addEventListener('input', (e) => {
  if (!e.target.matches('[data-cast-frame]')) return;
  castStop();
  S.castFrame = Number(e.target.value);
  castRefresh();
});

document.addEventListener('change', (e) => {
  if (e.target.matches('[data-cast-allties]')) {
    S.castAllTies = e.target.checked;
    castRefresh();
    return;
  }
  if (!e.target.matches('[data-cast-minor]')) return;
  S.castMinor = e.target.checked;
  castRefresh();
});

document.addEventListener('keydown', (e) => {
  const g = e.target.closest && e.target.closest('[data-cast-node], .ct-row');
  if (!g || (e.key !== 'Enter' && e.key !== ' ')) return;
  e.preventDefault();
  const fn = actions[g.dataset.action];
  if (fn) fn(g.dataset.arg);
});

// 인물 끌어 옮기기: 끄는 동안 관계도만 다시 그린다. 조금이라도 움직였으면 클릭(자세히 보기)으로 치지 않는다
document.addEventListener('pointerdown', (e) => {
  const g = e.target.closest && e.target.closest('[data-cast-node]');
  if (!g || e.button !== 0) return;
  castDrag = { id: g.dataset.castNode, x: e.clientX, y: e.clientY, moved: false };
});

document.addEventListener('pointermove', (e) => {
  if (!castDrag) return;
  if (!castDrag.moved && Math.hypot(e.clientX - castDrag.x, e.clientY - castDrag.y) < 4) return;
  const svg = document.querySelector('.cast-graph');
  if (!svg) return;
  castDrag.moved = true;
  e.preventDefault();
  const box = svg.getBoundingClientRect();
  const x = ((e.clientX - box.left) / box.width) * CAST_W;
  const y = ((e.clientY - box.top) / box.height) * CAST_H;
  S.castPos[castDrag.id] = [Math.min(CAST_W - 30, Math.max(30, x)), Math.min(CAST_H - 30, Math.max(30, y))];
  const stage = document.getElementById('cast-stage');
  if (stage) stage.querySelector('.cast-graph-wrap').innerHTML = castGraph();
});

document.addEventListener('pointerup', () => {
  if (!castDrag) return;
  if (castDrag.moved) {
    castDragged = true;
    setTimeout(() => { castDragged = false; }, 0);
    try { localStorage.setItem('canon-cast-pos:' + S.name, JSON.stringify(S.castPos)); } catch (e) { /* 이 브라우저에서만 쓰는 편의 기능 */ }
    const reset = document.querySelector('[data-action="castResetPos"]');
    if (reset) reset.disabled = false;
    castRefresh();
  }
  castDrag = null;
});

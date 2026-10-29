/* 지도. app.js 의 S, actions, api, run, render, header, esc, P 와 cast.js 의 frameLabel 을 쓴다.
   장소(설정의 장소 칸, 인과율 '장소' 요소)를 지도 위에 놓고, 화별 인물 자리를 관계도처럼 슬라이더로 재생한다.
   계산값은 서버 canon/atlas.py 의 /atlas 한 번으로 받는다 (places, frames: 화별 인물 자리, unmatched: 장소와 맞지 않은 위치 글).
   장소 자리는 0~1 비율 좌표로 작품에 저장한다 (Project.atlas.pins). 배경 그림은 작품 폴더 map/ 에 파일로 둔다.
   마을 데이터(Watabou 생성기 JSON, /atlas/layout)가 있으면 그림 대신 마을을 그리고, 옮겨 간 인물은 서버가 길 따라 찾은 경로(row.route)로 잇는다.
   이 파일은 지도 그림과 화면 뼈대(상태, 확대 · 이동, 옆 칸, 저장, 되돌리기, 공통 동작)다. 기능은 바로 뒤에 읽는 파일에 있다:
   atlas-gen.js 지도 만들기, atlas-travel.js 이동 시간 검사, atlas-table.js 어디에 있었나 표 · 장소와 맞지 않은 위치, atlas-export.js 내보내기, atlas-find.js 이름으로 자리 찾기. */
'use strict';

/** 마을 겹 설정은 이 브라우저에만 기억한다 (못 읽으면 기본값) */
function atlasLayersLoad() {
  const base = { trees: true, fields: true, shadows: true, numbers: false, deco: true, wards: true, uses: false, streets: true };
  try {
    const got = JSON.parse(localStorage.getItem('canon.atlasLayers') || '{}');
    if (got.deco === undefined && got.title === false) got.deco = false;  // 옛 '이름' 겹은 '장식'에 들어갔다
    delete got.title;
    return { ...base, ...got };
  } catch { return base; }
}
function atlasLayersSave() {
  try { localStorage.setItem('canon.atlasLayers', JSON.stringify(S.atlasLayers)); } catch { /* 저장 못 해도 이번 화면에서는 된다 */ }
}

/** 마을 화풍. 색은 CSS 변수 묶음(.at-map.st-*)으로 바꾸고, lamps(불 켜진 창) · lw(선 굵기 배율)는 그림에 넣는다. 단축키 1~4 */
const ATLAS_STYLES = {
  base: { label: '기본' },
  parchment: { label: '양피지' },
  night: { label: '밤', lamps: true },
  print: { label: '흑백 인쇄', lw: 1.8 },
};
function atlasStyleLoad() {
  try { const v = localStorage.getItem('canon.atlasStyle'); return ATLAS_STYLES[v] ? v : 'base'; } catch { return 'base'; }
}
function atlasStyleSave() {
  try { localStorage.setItem('canon.atlasStyle', S.atlasStyle); } catch { /* 저장 못 해도 이번 화면에서는 된다 */ }
}

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
  atlasDraft: {},    // 맞지 않은 위치 글마다 고른 장소 (atlasDraft())
  atlasNew: [],      // AI가 제안한 새 장소 (적용할 때 고른 글이 쓰는 것만 등록)
  atlasLayout: null, // 마을 데이터 { file, data } (파일 이름이 바뀌면 다시 받는다)
  atlasView: { x: 0, y: 0, z: 1 },  // 확대 · 이동: viewBox 왼쪽 위(지도 단위)와 배율 1~8
  atlasLayers: atlasLayersLoad(),    // 마을 겹 끄고 켜기 { trees, fields, shadows, numbers, deco, ... }
  atlasStyle: atlasStyleLoad(),      // 마을 화풍 (ATLAS_STYLES 키)
  atlasBld: null,    // 누른 건물 { i, at: [0~1 가운데], sx, sy: 지도 칸 안 화면 자리, edit: 고치기 칸 } (건물 메뉴)
  atlasUseHi: '',    // 옆 칸 '건물 쓰임'에서 고른 쓰임 (지도에서 테두리로 강조)
  atlasTitleEdit: false,
  atlasIdeas: null,  // 새 장소 이름 후보 (서버 naming)
  atlasFind: null,  // 이름으로 자리 찾기 { name, spots, pick } (atlasFindNow)
  atlasGen: null,    // 지도 만들기 { name, open, spec, preview, take: {장소 키: 새 자리에 놓기}, touched: 작가가 고친 칸, ai: AI 제안 { reason, notes } } (atlasGenState())
});

const ATLAS_W = 1000;
const ATLAS_LAYERS = { trees: ['나무', 't'], fields: ['밭', 'f'], shadows: ['그림자', 'u'], numbers: ['집 번호', 'm'], deco: ['장식', 'd'], wards: ['구역', 'w'],
  uses: ['쓰임', 's'], streets: ['길 이름', 'k'] };
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
  if (!same) { S.atlasPick = ''; S.atlasSel = ''; S.atlasFocus = ''; S.atlasDraft = {}; S.atlasNew = []; S.atlasView = { x: 0, y: 0, z: 1 }; S.atlasBld = null; S.atlasIdeas = null; S.atlasFind = null; S.atlasTitleEdit = false; S.atlasUseHi = ''; }
  const file = S.atlas.layout && S.atlas.layout.file;
  if (!file) S.atlasLayout = null;
  else if (!S.atlasLayout || S.atlasLayout.file !== file || S.atlasLayout.name !== S.name) {
    const data = await api('GET', `/projects/${enc(S.name)}/atlas/layout`).catch(() => null);
    S.atlasLayout = data && { file, name: S.name, data };
  }
}

function atlasStop() {
  if (atlasTimer) clearInterval(atlasTimer);
  atlasTimer = null;
}
window.addEventListener('hashchange', atlasStop);

/** 지도 만들기 미리보기 중이면 그 결과 ({ layout, pins, missing, blocked, info }) */
const atlasGenPreview = () => (S.atlasGen && S.atlasGen.name === S.name && S.atlasGen.preview) || null;
/** 이름으로 자리 찾기를 열었으면 { spots: 서버 atlas.find_spots, pick: {장소 키: 후보 번호 | -1} } */
const atlasFindNow = () => (S.atlasFind && S.atlasFind.name === S.name ? S.atlasFind : null);
const atlasH = () => {
  const pv = atlasGenPreview();
  return Math.round(ATLAS_W / (pv ? pv.layout.w / pv.layout.h : (S.atlas && S.atlas.aspect) || 1.5));
};
const atlasPlace = (key) => (S.atlas.places || []).find((pl) => pl.key === key);
const atlasFrameNow = () => S.atlas.frames[Math.min(S.atlasFrame, S.atlas.frames.length - 1)] || { episode: 0, rows: [], mentioned: [] };
const atlasImageUrl = () => `/api/projects/${enc(S.name)}/atlas/image?v=${enc(S.atlas.image)}`;
const atlasVillage = () => {
  const pv = atlasGenPreview();
  if (pv) return pv.layout;
  return S.atlas && S.atlas.layout && S.atlasLayout ? S.atlasLayout.data : null;
};

/** 걸은 거리 글: 1km 부터는 km */
function atlasMeters(m) {
  return m >= 1000 ? `${(m / 1000).toFixed(1)}km` : `${m}m`;
}

/** 0~1 좌표 점이 다각형 안인가 (비율 좌표라도 안팎은 같다) */
function atlasInside(q, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if ((yi > q[1]) !== (yj > q[1]) && q[0] < ((xj - xi) * (q[1] - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** 마을이 있으면 건물 안을 누른 자리는 그 건물 가운데로 맞춘다 */
function atlasSnap(pt) {
  const v = atlasVillage();
  const b = v && (v.buildings || []).find((poly) => atlasInside(pt, poly));
  if (!b) return pt;
  const ring = b.length > 3 && b[0][0] === b[b.length - 1][0] && b[0][1] === b[b.length - 1][1] ? b.slice(0, -1) : b;
  return [ring.reduce((n, q) => n + q[0], 0) / ring.length, ring.reduce((n, q) => n + q[1], 0) / ring.length];
}

/** 성 밖 구역 (밭 · 숲은 따로 그리니 구역 색 · 이름을 붙이지 않는다) */
const ATLAS_WARD_OUT = new Set(['farm', 'wood']);

/** 성벽: 폭만큼 굵은 선, 꺾이는 곳과 30m 마다 둥근 탑, 성문은 길 색으로 뚫고 양옆에 탑 (도시 생성기의 walls · gates).
    성문이 성벽 꺾이는 점에 있으면 양쪽 변을 따라 뚫는다. 성문 가까이는 꺾인 곳 탑을 세우지 않는다.
    올린 Watabou 파일의 성벽도 같은 모양으로 그린다 (성문 자리가 없으면 탑만) */
function atlasWalls(v, out, { P, m, k, lw }) {
  const towers = [];
  const tower = (x, y, r) => towers.push(`M${(x - r).toFixed(1)},${y.toFixed(1)}a${r.toFixed(1)},${r.toFixed(1)} 0 1 0 ${(2 * r).toFixed(1)},0a${r.toFixed(1)},${r.toFixed(1)} 0 1 0 ${(-2 * r).toFixed(1)},0`);
  const unit = (a, b) => { const L = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1; return [(b[0] - a[0]) / L, (b[1] - a[1]) / L]; };
  const walls = (v.walls || []).map((r) => ({ q: r.points.map(P), ww: Math.max(2, r.width) * lw }));
  const ring = (q) => q.length > 2 && Math.hypot(q[0][0] - q[q.length - 1][0], q[0][1] - q[q.length - 1][1]) < 0.01;
  const half = 4.5 * k;
  // 성문: 가장 가까운 성벽의 꼭짓점(1.5m 안)이면 앞뒤 변 쪽, 아니면 그 변의 양쪽으로 half 만큼
  const gates = [];
  (v.gates || []).forEach((g) => {
    const p = P(g);
    let best = null;
    walls.forEach(({ q, ww }) => {
      const n = ring(q) ? q.length - 1 : q.length;
      for (let j = 0; j < n; j++) {
        const d = Math.hypot(q[j][0] - p[0], q[j][1] - p[1]);
        const prev = j ? q[j - 1] : ring(q) ? q[n - 1] : null;
        const next = q[j + 1] || (ring(q) ? q[1] : null);
        if (d < 1.5 * k && (!best || d < best.d)) best = { d, ww, dirs: [prev && unit(q[j], prev), next && unit(q[j], next)].filter(Boolean) };
        if (!next) continue;
        const [ux, uy] = unit(q[j], next);
        const L = Math.hypot(next[0] - q[j][0], next[1] - q[j][1]);
        const t = Math.max(0, Math.min(L, (p[0] - q[j][0]) * ux + (p[1] - q[j][1]) * uy));
        const ds = Math.hypot(q[j][0] + ux * t - p[0], q[j][1] + uy * t - p[1]);
        if (!best || ds + 0.01 < best.d) best = { d: ds, ww, dirs: [[-ux, -uy], [ux, uy]] };
      }
    });
    if (best && best.dirs.length) gates.push({ p, ...best, rad: Math.max(2.4, best.ww * 1.05 * k) });
  });
  walls.forEach(({ q, ww }) => {
    const line = q.map((p) => p.map((x) => x.toFixed(1)).join(',')).join(' ');
    out.push(`<polyline class="at-v-wall-edge" points="${line}" stroke-width="${m(ww + 1.6, 3)}"></polyline><polyline class="at-v-wall" points="${line}" stroke-width="${m(ww, 2)}"></polyline>`);
    const rad = Math.max(2, ww * 0.85 * k);
    let run = Infinity;
    q.forEach((p, j) => {
      if (j) run += Math.hypot(p[0] - q[j - 1][0], p[1] - q[j - 1][1]) / k;
      const a = q[j - 1] || (ring(q) ? q[q.length - 2] : null);
      const b = q[j + 1] || (ring(q) ? q[1] : null);
      const turn = a && b ? Math.abs(Math.atan2(b[1] - p[1], b[0] - p[0]) - Math.atan2(p[1] - a[1], p[0] - a[0])) : Math.PI;
      const bend = Math.min(turn, 2 * Math.PI - turn) > 0.35;
      if (!(bend || run >= 30)) return;
      run = 0;
      if (gates.some((gt) => Math.hypot(gt.p[0] - p[0], gt.p[1] - p[1]) < half + gt.rad * 2)) return;
      tower(p[0], p[1], rad);
    });
  });
  gates.forEach(({ p, dirs, ww, rad }) => {
    const ends = (dirs.length === 1 ? [dirs[0], [-dirs[0][0], -dirs[0][1]]] : dirs).map((d) => [d, p[0] + d[0] * half, p[1] + d[1] * half]);
    out.push(`<polyline class="at-v-gate" points="${ends[0][1].toFixed(1)},${ends[0][2].toFixed(1)} ${p[0].toFixed(1)},${p[1].toFixed(1)} ${ends[1][1].toFixed(1)},${ends[1][2].toFixed(1)}" stroke-width="${m(ww + 2.4, 4)}"></polyline>`);
    ends.forEach(([d, x, y]) => tower(x + d[0] * rad * 0.6, y + d[1] * rad * 0.6, rad));
  });
  if (towers.length) out.push(`<path class="at-v-tower" d="${towers.join('')}" stroke-width="${m(0.6, 0.8)}"></path>`);
}

/** 번호 i 로 고르는 0~1 값. 같은 마을이면 건물 · 나무 · 밭이 늘 같은 모양 · 색으로 그려진다 */
const atlasHash = (i, salt = 0) => ((Math.imul(i + 1, 2654435761) ^ Math.imul(salt + 7, 40503)) >>> 0) / 4294967296;

/** 집 번호 글자 크기 (지도 단위). 3.4m(최소 7단위)로 쓰되 보통 집 폭의 0.42 를 넘지 않게 줄이고(도시는 집이 작아 번호가 넘친다),
    화면에서 6px 보다 작으면 0 (그리지 않는다). 보통 집 폭은 번호 붙은 집 넓이의 제곱근 가운데값 (앞 200채). px: 지도 단위 1 의 화면 px */
function atlasNumFont(v, W, z, px) {
  const k = W / v.w;
  const idx = (v.numbers || (v.buildings || []).map((_, i) => i)).slice(0, 200);
  const sizes = idx.map((bi) => {
    const ln = (v.buildings || [])[bi] || [];
    let a = 0;
    ln.forEach((q, j) => { const p = ln[(j + 1) % ln.length]; a += q[0] * p[1] - p[0] * q[1]; });
    return Math.sqrt(Math.abs(a / 2) * v.w * v.h);
  }).filter((x) => x > 0).sort((a, b) => a - b);
  if (!sizes.length) return 0;
  const fs = Math.min(Math.max(3.4 * k, 7), 0.42 * sizes[Math.floor(sizes.length / 2)] * k);
  return fs * z * px >= 6 ? fs : 0;
}

/** 집 번호를 켰는데 지금 배율에서는 작아서 그리지 않으면 알린다 */
function atlasNumHint(layer) {
  const v = atlasVillage();
  if (layer !== 'numbers' || !S.atlasLayers.numbers || !v) return;
  if (!atlasNumFont(v, ATLAS_W, atlasViewNow().z, atlasStageW ? atlasStageW / ATLAS_W : 1)) toast('집 번호는 더 확대하면 보여요');
}

/** 건물 하나의 정보 (canon/bldgs.py 가 만든 blds + 작가가 고친 Atlas.buildings). 곁채는 본채 정보. 미리보기 지도에는 고친 값을 쓰지 않는다 */
function atlasBldInfo(i) {
  const v = atlasVillage();
  const blds = (v && v.blds) || [];
  if (!blds[i]) return null;
  const main = blds[i].of !== undefined ? blds[i].of : i;
  const b = blds[main] || {};
  const mine = atlasGenPreview() ? null : ((P().atlas && P().atlas.buildings) || []).find((x) => x.i === main);
  const use = (mine && mine.use) || b.use || 'home';
  const [label, group] = (S.atlas.gen && S.atlas.gen.uses && S.atlas.gen.uses[use]) || [use, 'home'];
  const st = typeof b.street === 'number' && v.streets && v.streets[b.street];
  return { i, main, annex: main !== i, use, label, group, floors: b.floors || 1, people: b.people || 0, street: st ? st.name : '', no: b.no || 0, addr: b.addr || '', tenants: b.tenants || [],
    name: (mine && mine.name) || b.name || '', note: (mine && mine.note) || '', residents: (mine && mine.residents) || [], edited: !!mine, made: !!b.made };
}

/** 건물마다 쓰임 묶음 (본채 기준, 고친 값 반영). 지도 색칠 · 강조에 쓴다 */
function atlasBldUses(v) {
  const blds = (v && v.blds) || [];
  const mine = atlasGenPreview() ? {} : Object.fromEntries(((P().atlas && P().atlas.buildings) || []).filter((x) => x.use).map((x) => [x.i, x.use]));
  return blds.map((b, i) => {
    const main = b.of !== undefined ? b.of : i;
    return mine[main] || (blds[main] || {}).use || 'home';
  });
}

/** 거리 이름: 거리 가운데 가장 긴 마디 위에 그 방향으로 눕혀 쓴다. 이름 없는 길, 화면에서 이름보다 짧은 거리, 장소 이름표 · 다른 거리 이름과
    겹치는 이름은 뺀다 (taken 은 atlasLabels 가 차지한 상자). 같은 이름은 화면 폭의 1/4 안에 한 번만 (atlasLabelPick, z: 확대 배율) */
function atlasStreetLabels(v, W, H, fs, taken, z = 1) {
  const k = W / v.w;
  const out = [];
  atlasLabelPick(v.streets || [], W, H, W / z / 4, (st) => {
    const w = atlasTextW(st.name, fs) * 1.1;
    if (st.length * k < w * 1.2) return false;  // 거리가 이름보다 짧다
    const cx = st.mid[0] * W;
    const cy = st.mid[1] * H;
    const a = (st.angle * Math.PI) / 180;
    const hw = (Math.abs(Math.cos(a)) * w + Math.abs(Math.sin(a)) * fs) / 2;
    const hh = (Math.abs(Math.sin(a)) * w + Math.abs(Math.cos(a)) * fs) / 2;
    const b = [cx - hw, cy - hh, cx + hw, cy + hh];
    if (taken.some((p) => b[0] < p[2] && b[2] > p[0] && b[1] < p[3] && b[3] > p[1])) return false;
    taken.push(b);
    out.push(`<text x="${cx.toFixed(1)}" y="${cy.toFixed(1)}" transform="rotate(${st.angle} ${cx.toFixed(1)} ${cy.toFixed(1)})" text-anchor="middle" dominant-baseline="central">${esc(st.name)}</text>`);
    return true;
  });
  return out.length ? `<g class="at-v-street-label" font-size="${fs.toFixed(2)}" stroke-width="${(fs * 0.3).toFixed(2)}">${out.join('')}</g>` : '';
}

/** 구역 이름 (도시 생성기의 wards 성안만, 현대 동네는 슈퍼블록 · 학교): 넓이 가운데에 장소 이름표보다 조금 작게. 장소 점 · 이름표 · 다른 구역 이름과
    겹치면 뺀다 (taken: 인물 표 · 장소 이름표가 차지한 상자 [x0, y0, x1, y1], 여기서 놓은 상자도 더한다).
    같은 이름은 화면 폭의 1/4 안에 한 번만, 넓은 구역부터 (atlasWardPick, z: 확대 배율) */
function atlasWardLabels(v, W, H, fs, taken, z = 1) {
  const names = (S.atlas && S.atlas.gen && S.atlas.gen.wards) || {};
  const out = [];
  const wards = (v.wards || []).filter((wd) => !ATLAS_WARD_OUT.has(wd.kind) && names[wd.kind]).map((wd) => ({ name: names[wd.kind], shape: wd.shape }));
  atlasWardPick(wards, W, H, W / z / 4, (wd) => {
    const [cx, cy] = [wd.mid[0] * W, wd.mid[1] * H];
    const w = atlasTextW(wd.name, fs) * 1.2;  // 글자 사이를 띄운 만큼
    const b = [cx - w / 2, cy - fs * 0.6, cx + w / 2, cy + fs * 0.6];
    if (taken.some((p) => b[0] < p[2] && b[2] > p[0] && b[1] < p[3] && b[3] > p[1])) return false;
    taken.push(b);
    out.push(`<text x="${cx.toFixed(1)}" y="${cy.toFixed(1)}" text-anchor="middle" dominant-baseline="central">${esc(wd.name)}</text>`);
    return true;
  });
  return out.length ? `<g class="at-v-ward-label" font-size="${fs.toFixed(2)}" stroke-width="${(fs * 0.3).toFixed(2)}" letter-spacing="${(fs * 0.15).toFixed(2)}">${out.join('')}</g>` : '';
}

/** 마을 바탕: 풀밭 땅, 밭(이랑 무늬) · 풀밭 · 광장, 모래톱과 물결이 있는 물, 강, 테두리 있는 길, 널다리, 성벽,
    두 색 지붕과 그림자가 있는 건물, 그림자 · 수관 · 밝은 점으로 된 나무. 1단위 = 1m 기준 크기 (k: 화면 단위 / m)
    layers: 겹 끄고 켜기와 화풍 그림 옵션 (lamps: 불 켜진 창, lw: 길 테두리 · 성벽 굵기 배율, z: 확대 배율, px: 지도 단위 1 의 화면 px — 집 번호) */
function atlasVillageSvg(v, W, H, layers = {}) {
  const on = (key) => layers[key] !== false;
  const lw = layers.lw || 1;
  const k = W / v.w;
  const circ = (x, y, r) => `M${(x - r).toFixed(1)},${y.toFixed(1)}a${r.toFixed(1)},${r.toFixed(1)} 0 1 0 ${(2 * r).toFixed(1)},0a${r.toFixed(1)},${r.toFixed(1)} 0 1 0 ${(-2 * r).toFixed(1)},0`;
  const P = (q) => [q[0] * W, q[1] * H];
  const pts = (ln) => ln.map((q) => `${(q[0] * W).toFixed(1)},${(q[1] * H).toFixed(1)}`).join(' ');
  const m = (meters, min = 0.6) => Math.max(min, meters * k).toFixed(1);
  const defs = [];
  const out = [`<rect class="at-v-ground" x="0" y="0" width="${W}" height="${H}"></rect>`];
  const stroke = (list, cls, w, min) => (list || []).forEach((r) => out.push(`<polyline class="${cls}" points="${pts(r.points)}" stroke-width="${m(w(r), min)}"></polyline>`));

  // 밭: 긴 변 방향으로 돌린 이랑 무늬 (15° 단위로 묶어 무늬 수를 줄인다), 세 가지 작물 색
  const pats = new Set();
  const under0 = out.length;  // 밭 · 녹지 · 광장 그림의 처음 (바다 속 섬 위에 다시 그린다)
  (on('fields') ? v.fields || [] : []).forEach((ln, i) => {
    let best = 0;
    let deg = 0;
    ln.forEach((q, j) => {
      const [ax, ay] = P(ln[j ? j - 1 : ln.length - 1]);
      const [bx, by] = P(q);
      const len = Math.hypot(bx - ax, by - ay);
      if (len > best) { best = len; deg = (Math.atan2(by - ay, bx - ax) * 180) / Math.PI; }
    });
    const a = ((Math.round(deg / 15) * 15) % 180 + 180) % 180;
    // 작물 색은 자리(60m 칸)로 고른다: 한 밭을 나눈 이랑 띠들이 같은 색이 되게
    const cx = ln.reduce((n, q) => n + q[0], 0) / ln.length * v.w;
    const cy = ln.reduce((n, q) => n + q[1], 0) / ln.length * v.h;
    const tone = Math.floor(atlasHash(Math.floor(cx / 60) * 7919 + Math.floor(cy / 60), 3) * 3);
    const id = `at-fur-${a}-${tone}`;
    if (!pats.has(id)) {
      pats.add(id);
      const sp = m(2.4, 3);
      defs.push(`<pattern id="${id}" patternUnits="userSpaceOnUse" width="${sp}" height="${sp}" patternTransform="rotate(${a})"><rect class="at-v-field t${tone}" width="${sp}" height="${sp}"></rect><line class="at-v-furrow" x1="0" y1="0.5" x2="${sp}" y2="0.5"></line></pattern>`);
    }
    out.push(`<polygon class="at-v-field-edge" points="${pts(ln)}" fill="url(#${id})"></polygon>`);
  });
  (v.greens || []).forEach((ln) => out.push(`<polygon class="at-v-green" points="${pts(ln)}"></polygon>`));
  (v.squares || []).forEach((ln) => out.push(`<polygon class="at-v-square" points="${pts(ln)}"></polygon>`));
  const under = out.slice(under0);
  // 도시 구역: 종류마다 옅은 바탕색과 점선 경계 (길 아래에 깔고, 이름은 건물 위에 따로)
  if (on('wards')) (v.wards || []).forEach((wd) => { if (!ATLAS_WARD_OUT.has(wd.kind)) out.push(`<polygon class="at-v-ward k-${esc(wd.kind)}" points="${pts(wd.shape)}" stroke-width="${m(0.8, 0.6)}"></polygon>`); });


  // 물: 바깥으로 모래톱, 안쪽으로 물가와 나란한 물결 선 두 줄 (물 다각형으로 잘라 안쪽만 보인다)
  // 물가 선: 지도 테두리를 따라가는 변은 물가가 아니라서 뺀다 (바다를 지도 가장자리에서 닫은 변)
  const rim = (q) => q[0] <= 0.001 || q[0] >= 0.999 || q[1] <= 0.001 || q[1] >= 0.999;
  const shoreline = (ln) => {
    const segs = [];
    ln.forEach((q, j) => {
      const prev = ln[j ? j - 1 : ln.length - 1];
      if (!(rim(prev) && rim(q))) segs.push(`M${P(prev).map((x) => x.toFixed(1)).join(',')}L${P(q).map((x) => x.toFixed(1)).join(',')}`);
    });
    return segs.join('');
  };
  (v.water || []).forEach((ln, i) => {
    const p = pts(ln);
    const edge = shoreline(ln);
    defs.push(`<clipPath id="at-wclip-${i}"><polygon points="${p}"></polygon></clipPath>`);
    out.push(`<path class="at-v-sand" d="${edge}" stroke-width="${m(9, 4)}"></path><polygon class="at-v-water" points="${p}"></polygon>`);
    out.push(`<g clip-path="url(#at-wclip-${i})">${[5, 12].map((d) => `<path class="at-v-wave" d="${edge}" stroke-width="${m(2 * d + 1.4, 3)}"></path><path class="at-v-water-line" d="${edge}" stroke-width="${m(2 * d - 1.4, 1.5)}"></path>`).join('')}</g>`);
  });
  // 바다 속 섬(land, OpenStreetMap 해안선): 물결은 바다 쪽에만, 땅 바탕 위에 모래톱과 섬 안의 밭 · 녹지 · 광장을 다시 그린다
  const land = v.land || [];
  if (land.length) {
    const ring = (ln) => `M${ln.map((q) => P(q).map((x) => x.toFixed(1)).join(',')).join('L')}Z`;
    const edge = land.map(ring).join('');
    defs.push(`<clipPath id="at-wclip-all">${(v.water || []).map((ln) => `<polygon points="${pts(ln)}"></polygon>`).join('')}</clipPath>`);
    defs.push(`<clipPath id="at-lclip">${land.map((ln) => `<polygon points="${pts(ln)}"></polygon>`).join('')}</clipPath>`);
    out.push(`<g clip-path="url(#at-wclip-all)">${[5, 12].map((d) => `<path class="at-v-wave" d="${edge}" stroke-width="${m(2 * d + 1.4, 3)}"></path><path class="at-v-water-line" d="${edge}" stroke-width="${m(2 * d - 1.4, 1.5)}"></path>`).join('')}</g>`);
    out.push(`<path class="at-v-ground" d="${edge}"></path>`);
    out.push(`<g clip-path="url(#at-lclip)"><path class="at-v-sand" d="${edge}" stroke-width="${m(9, 4)}"></path>${under.join('')}</g>`);
  }
  stroke(v.rivers, 'at-v-sand', (r) => r.width + 5, 5);
  stroke(v.rivers, 'at-v-river', (r) => r.width, 3);
  stroke(v.rivers, 'at-v-river-line', (r) => r.width * 0.45, 1);

  // 길: 어두운 테두리 위에 길 색. 다리: 널판 색 위에 널판 틈
  const roads = (v.roads || []).filter((r) => r.kind === 'road');
  const bridges = (v.roads || []).filter((r) => r.kind === 'bridge');
  stroke(roads, 'at-v-road-edge', (r) => r.width + 1.6 * lw, 3);
  stroke(roads, 'at-v-road', (r) => r.width, 2);
  stroke(bridges, 'at-v-bridge', (r) => r.width + 1, 3);
  stroke(bridges, 'at-v-planks', (r) => r.width + 1, 3);
  atlasWalls(v, out, { P, m, k, lw });

  // 건물: 그림자 → 지붕 → 어두운 반쪽 → 마루선. 꼭짓점이 넷이 아니면 한 색 지붕.
  // 빈 블록에 지은 건물(parts[i].made, canon/fill.py)은 그림자 · 지붕 없이 흐린 색과 점선 테두리로 (OpenStreetMap에 없는 건물)
  const made = (i) => !!(v.parts && v.parts[i] && v.parts[i].made);
  const shade = (dx, dy) => (v.buildings || []).map((ln, i) => made(i) ? '' : `M${ln.map((q) => `${(q[0] * W + dx).toFixed(1)},${(q[1] * H + dy).toFixed(1)}`).join('L')}Z`).join('');
  if (on('shadows')) out.push(`<path class="at-v-shadow" d="${shade(1.4 * k, 1.8 * k)}"></path>`);
  const roofs = [[], [], [], []];
  const dark = [];
  const ridges = [];
  const flat = v.generator === 'osm' || v.generator === 'canon-modern';  // 실제 지도(OpenStreetMap) · 현대 동네의 건물은 박공 없이 평지붕으로
  const madeD = [];
  (v.buildings || []).forEach((ln, i) => {
    if (made(i)) { madeD.push(`M${ln.map((q) => `${(q[0] * W).toFixed(1)},${(q[1] * H).toFixed(1)}`).join('L')}Z`); return; }
    const ring = ln.length > 4 && ln[0][0] === ln[ln.length - 1][0] && ln[0][1] === ln[ln.length - 1][1] ? ln.slice(0, -1) : ln;
    const q = ring.map(P);
    roofs[Math.floor(atlasHash(i, 1) * 4)].push(`M${q.map((p) => p.map((x) => x.toFixed(1)).join(',')).join('L')}Z`);
    if (flat || q.length !== 4) return;
    const long01 = Math.hypot(q[1][0] - q[0][0], q[1][1] - q[0][1]) >= Math.hypot(q[2][0] - q[1][0], q[2][1] - q[1][1]);
    const [a, b, c, d] = long01 ? q : [q[1], q[2], q[3], q[0]];  // a-b 가 긴 변
    const mid = (u, w) => [(u[0] + w[0]) / 2, (u[1] + w[1]) / 2];
    const r1 = mid(d, a);
    const r2 = mid(b, c);
    const h1 = [a, b, r2, r1];
    const h2 = [r1, r2, c, d];
    const sum = (h) => h.reduce((n, p) => n + p[0] + p[1], 0);
    const low = sum(h1) > sum(h2) ? h1 : h2;  // 빛은 왼쪽 위에서: 오른쪽 아래 반쪽이 어둡다
    dark.push(`M${low.map((p) => p.map((x) => x.toFixed(1)).join(',')).join('L')}Z`);
    ridges.push(`M${r1.map((x) => x.toFixed(1)).join(',')}L${r2.map((x) => x.toFixed(1)).join(',')}`);
  });
  roofs.forEach((d, t) => { if (d.length) out.push(`<path class="at-v-house t${t}" d="${d.join('')}"></path>`); });
  if (dark.length) out.push(`<path class="at-v-roof-dark" d="${dark.join('')}"></path><path class="at-v-ridge" d="${ridges.join('')}"></path>`);
  if (madeD.length) out.push(`<path class="at-v-made" d="${madeD.join('')}" stroke-width="${m(0.8, 1.2)}" stroke-dasharray="${m(2, 3)} ${m(1.5, 2)}"></path>`);

  // 쓰임 색: 집이 아닌 건물에 쓰임 묶음 색을 덧칠한다 (겹 '쓰임'). 고른 쓰임(hi)은 테두리로 강조
  const uses = layers.useOf;
  const groupOf = (u) => ((S.atlas && S.atlas.gen && S.atlas.gen.uses && S.atlas.gen.uses[u]) || [u, 'home'])[1];
  const ring = (ln) => `M${ln.map((q) => `${(q[0] * W).toFixed(1)},${(q[1] * H).toFixed(1)}`).join('L')}Z`;
  if (uses && layers.uses) {
    const by = {};
    (v.buildings || []).forEach((ln, i) => {
      const g = groupOf(uses[i]);
      if (g !== 'home') (by[g] = by[g] || []).push(ring(ln));
    });
    Object.entries(by).forEach(([g, d]) => out.push(`<path class="at-v-use g-${esc(g)}" d="${d.join('')}"></path>`));
  }
  if (uses && layers.hi) {
    const d = (v.buildings || []).map((ln, i) => (uses[i] === layers.hi ? ring(ln) : '')).join('');
    if (d) out.push(`<path class="at-v-hi" d="${d}" stroke-width="${m(1.6, 2.5)}"></path>`);
  }

  // 밤 화풍: 열에 일곱 집쯤 창에 불이 켜진다 (번호로 골라 늘 같은 집). 번진 빛 위에 창 하나
  if (layers.lamps) {
    const glow = [];
    const lamp = [];
    (v.buildings || []).forEach((ln, i) => {
      if (atlasHash(i, 4) < 0.3) return;
      const cx = (ln.reduce((n, q) => n + q[0], 0) / ln.length) * W + (atlasHash(i, 5) - 0.5) * 2 * k;
      const cy = (ln.reduce((n, q) => n + q[1], 0) / ln.length) * H + (atlasHash(i, 6) - 0.5) * 2 * k;
      glow.push(circ(cx, cy, Math.max(2.5, 3.4 * k)));
      lamp.push(circ(cx, cy, Math.max(0.8, 0.8 * k)));
    });
    if (lamp.length) out.push(`<path class="at-v-glow" d="${glow.join('')}"></path><path class="at-v-lamp" d="${lamp.join('')}"></path>`);
  }

  // 나무: 크기가 다른 수관을 겹쳐 덩어리로. 그림자 · 수관 · 밝은 점을 각각 한 path 로 모은다
  const trees = on('trees') ? v.trees || [] : [];
  if (trees.length) {
    const sh = [];
    const cr = [];
    const hi = [];
    trees.forEach((t, i) => {
      const [x, y] = P(t);
      const r = Math.max(1.8, (3.2 + atlasHash(i, 2) * 2) * k);
      sh.push(circ(x + r * 0.35, y + r * 0.45, r));
      cr.push(circ(x, y, r));
      hi.push(circ(x - r * 0.3, y - r * 0.3, r * 0.45));
    });
    out.push(`${on('shadows') ? `<path class="at-v-tree-shadow" d="${sh.join('')}"></path>` : ''}<path class="at-v-tree" d="${cr.join('')}"></path><path class="at-v-tree-hi" d="${hi.join('')}"></path>`);
  }
  // 집 번호: 만든 마을은 필지마다 본채(numbers), 올린 파일은 건물마다. 화면에서 읽을 수 있을 만큼 커졌을 때만 (atlasNumFont)
  const numFs = layers.numbers ? atlasNumFont(v, W, layers.z || 1, layers.px || 1) : 0;
  if (numFs) {
    const idx = v.numbers || (v.buildings || []).map((_, i) => i);
    out.push(`<g class="at-v-num" font-size="${numFs.toFixed(2)}">${idx.map((bi, n) => {
      const ln = (v.buildings || [])[bi];
      if (!ln) return '';
      const cx = (ln.reduce((a, q) => a + q[0], 0) / ln.length) * W;
      const cy = (ln.reduce((a, q) => a + q[1], 0) / ln.length) * H;
      return `<text x="${cx.toFixed(1)}" y="${cy.toFixed(1)}" text-anchor="middle" dominant-baseline="central">${n + 1}</text>`;
    }).join('')}</g>`);
  }
  return (defs.length ? `<defs>${defs.join('')}</defs>` : '') + out.join('');
}

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

// ----- 지도 장식 -----

/** 지도 단위 1 이 몇 m 인가 (축척 막대). 미리보기 · 생성기 지도는 1단위 = 1m, 올린 마을 데이터는 축척 칸,
    배경 그림 · 모눈은 이동 시간 검사의 지도 가로 km. 모르면 0 */
function atlasMpu() {
  const pv = atlasGenPreview();
  if (pv) return pv.layout.w / ATLAS_W;
  const lo = S.atlas.layout;
  if (lo) return lo.width_m / ATLAS_W;
  const t = S.atlas.travel;
  return t && t.scale ? (t.scale[0] * 1000) / ATLAS_W : 0;
}

let atlasMeasure = null;
/** 장식 글자 폭: 틀을 글에 맞추려고 캔버스로 잰다 (못 재면 atlasTextW 어림). bold: 굵은 글자 */
function atlasDecoW(t, fs, bold = false) {
  try {
    atlasMeasure = atlasMeasure || document.createElement('canvas').getContext('2d');
    const fam = getComputedStyle(document.documentElement).getPropertyValue('--sans').trim() || 'sans-serif';
    atlasMeasure.font = `${bold ? 700 : 400} 100px ${fam}`;
    const w = atlasMeasure.measureText(t).width;
    if (w > 0) return (w / 100) * fs * 1.04;  // 내보낸 PNG 는 다른 글꼴로 그릴 수 있어 조금 넉넉히
  } catch { /* 캔버스가 없으면 어림 */ }
  return atlasTextW(t, fs);
}

/** 지도 장식: 왼쪽 위 제목 틀(지도 이름 · 인구), 오른쪽 아래 축척 막대 · 북쪽 화살표(OpenStreetMap 지도만, 북이 위)와 출처 글.
    지금 보는 범위의 모서리에 화면에서 같은 크기로 놓는다 (u: 화면 1px 의 지도 단위). 출처 글은 장식 겹을 꺼도 그린다.
    미리보기 중에는 아래 막대(.at-pv-bar)가 덮으므로 축척 막대를 그리지 않는다.
    돌려주는 값: { svg, boxes: 차지한 상자 [x0, y0, x1, y1] (장소 · 구역 · 길 이름표가 비켜 간다) } */
function atlasDeco(village, view, W, H) {
  const z = view.z;
  const u = atlasExporting || !atlasStageW ? 1 / z : ATLAS_W / (atlasStageW * z);
  const f = (x) => x.toFixed(2);
  const [x0, y0, x1, y1] = [view.x, view.y, view.x + W / z, view.y + H / z];
  const gap = 8 * u;
  const pad = 6 * u;
  const narrow = !atlasExporting && atlasStageW > 0 && atlasStageW < 480;  // 휴대폰 폭에서는 글자를 줄인다 (이름표와 같이)
  const on = S.atlasLayers.deco !== false;
  const pv = atlasGenPreview();
  const out = [];
  const boxes = [];

  // 제목 틀 (이름이 없으면 그리지 않고, 화면에는 이름 정하기 버튼 atlasTitleBox 가 뜬다)
  const t = pv ? pv.title : S.atlas.title;
  if (on && village && t && t.title && !(S.atlasTitleEdit && !pv)) {
    const fn = (narrow ? 14 : 17) * u;
    const pop = `${t.population ? `인구 약 ${t.population.toLocaleString()}명 · ` : ''}${t.unit || '집'} ${t.houses.toLocaleString()}채`;
    const max = Math.max(fn * 4, (x1 - x0) * 0.6 - 2 * pad);  // 오른쪽 위 확대 버튼에 닿지 않게
    const chars = [...t.title];
    let name = t.title;
    while (chars.length > 1 && atlasDecoW(name, fn, true) > max) { chars.pop(); name = chars.join('') + '…'; }
    const fp = Math.min((narrow ? 10 : 11) * u, max / atlasDecoW(pop, 1));
    const w = Math.max(atlasDecoW(name, fn, true), atlasDecoW(pop, fp)) + 2 * pad;
    const h = 2 * pad + fn + 3 * u + fp;
    const [bx, by] = [x0 + gap, y0 + gap];
    const live = !pv && !atlasExporting;
    out.push(`<g class="at-v-title${live ? ' live' : ''}"${live ? ' data-action="atlasTitleEdit" data-arg="1" role="button" tabindex="0" aria-label="지도 이름 바꾸기"' : ''}>${live ? '<title>눌러 이름 바꾸기 (D로 장식 숨기기)</title>' : ''}
      <rect class="at-v-frame" x="${f(bx)}" y="${f(by)}" width="${f(w)}" height="${f(h)}" rx="${f(6 * u)}" stroke-width="${f(u)}"></rect>
      <text class="at-v-title-name" x="${f(bx + pad)}" y="${f(by + pad + fn * 0.85)}" font-size="${f(fn)}">${esc(name)}</text>
      <text class="at-v-title-pop" x="${f(bx + pad)}" y="${f(by + pad + fn + 3 * u + fp * 0.85)}" font-size="${f(fp)}">${esc(pop)}</text></g>`);
    boxes.push([bx, by, bx + w, by + h]);
  } else if (on && village && t && !t.title && !pv && !atlasExporting) {
    boxes.push([x0 + gap, y0 + gap, x0 + gap + 130 * u, y0 + gap + 32 * u]);  // 이름 정하기 버튼 자리
  }

  // 오른쪽 아래: 축척 막대 · 북쪽 화살표 · 출처 글을 한 틀에
  const src = village && village.source;
  const sb = on && !pv ? atlasScaleBar(atlasMpu(), z, W) : null;
  const north = on && !pv && village && village.generator === 'osm';
  let fs = (narrow ? 9 : 10) * u;
  if (src) fs = Math.min(fs, (x1 - x0 - 2 * gap - 2 * pad) / atlasDecoW(src, 1));  // 긴 출처 글(빈 블록을 채운 지도)도 들어가게
  const sw = src ? atlasDecoW(src, fs) : 0;
  if (sb || north) {
    const fl = 10.5 * u;
    const bh = 5 * u;
    const nw = 12 * u;
    const nh = 22 * u;
    const rowH = Math.max(sb ? fl + 3 * u + bh : 0, north ? nh : 0);
    const rowW = (north ? nw : 0) + (north && sb ? 10 * u : 0) + (sb ? Math.max(sb.units, atlasDecoW(sb.label, fl, true)) : 0);
    const pw = Math.max(rowW, sw) + 2 * pad;
    const ph = 2 * pad + rowH + (src ? 4 * u + fs : 0);
    const [px1, py1] = [x1 - gap, y1 - gap];
    const [px0, py0] = [px1 - pw, py1 - ph];
    const right = px1 - pad;
    const top = py0 + pad;
    const parts = [`<rect class="at-v-frame" x="${f(px0)}" y="${f(py0)}" width="${f(pw)}" height="${f(ph)}" rx="${f(6 * u)}" stroke-width="${f(u)}"></rect>`];
    let left = right;
    if (sb) {
      const L = sb.units;
      const bx = right - L;
      const by = top + rowH - bh;
      parts.push(`<rect class="at-v-scale-b" x="${f(bx)}" y="${f(by)}" width="${f(L)}" height="${f(bh)}" stroke-width="${f(u)}"></rect>`,
        `<rect class="at-v-scale-a" x="${f(bx)}" y="${f(by)}" width="${f(L / 2)}" height="${f(bh)}"></rect>`,
        `<text class="at-v-scale-text" x="${f(right - L / 2)}" y="${f(by - 3 * u)}" font-size="${f(fl)}" text-anchor="middle">${esc(sb.label)}</text>`);
      left = Math.min(bx, right - L / 2 - atlasDecoW(sb.label, fl, true) / 2);
    }
    if (north) {
      const cx = (sb ? left - 10 * u : right) - nw / 2;
      const ny = top + (rowH - nh) / 2;
      const tip = ny + 11 * u;
      const foot = ny + nh;
      parts.push(`<text class="at-v-north-n" x="${f(cx)}" y="${f(ny + 8.5 * u)}" font-size="${f(9.5 * u)}" text-anchor="middle">N</text>`,
        `<path class="at-v-north-b" d="M${f(cx)},${f(tip)}L${f(cx + nw / 2)},${f(foot)}L${f(cx)},${f(foot - 4 * u)}Z" stroke-width="${f(u * 0.8)}"></path>`,
        `<path class="at-v-north-a" d="M${f(cx)},${f(tip)}L${f(cx - nw / 2)},${f(foot)}L${f(cx)},${f(foot - 4 * u)}Z" stroke-width="${f(u * 0.8)}"></path>`);
    }
    if (src) parts.push(`<text class="at-v-source" x="${f(right)}" y="${f(py1 - pad - fs * 0.2)}" font-size="${f(fs)}" stroke-width="${f(fs * 0.3)}" text-anchor="end">${esc(src)}</text>`);
    out.push(`<g class="at-v-deco">${parts.join('')}</g>`);
    boxes.push([px0, py0, px1, py1]);
  } else if (src) {
    // 장식을 꺼도 출처 글은 그린다 (README 2026-10-28)
    out.push(`<text class="at-v-source" x="${f(x1 - gap)}" y="${f(y1 - gap)}" font-size="${f(fs)}" stroke-width="${f(fs * 0.3)}" text-anchor="end">${esc(src)}</text>`);
    boxes.push([x1 - gap - sw, y1 - gap - fs, x1 - gap, y1 - gap + fs * 0.25]);
  }
  return { svg: out.join(''), boxes };
}

// ----- 지도 그림 -----

function atlasSvg() {
  const W = ATLAS_W;
  const H = atlasH();
  const f = atlasFrameNow();
  const out = [];
  const village = atlasVillage();
  const style = ATLAS_STYLES[S.atlasStyle] || ATLAS_STYLES.base;
  const fs = atlasLabelFs(atlasViewNow().z);  // 화면 폭을 먼저 잰다 (집 번호 크기에도 쓴다)
  const px = atlasExporting || !atlasStageW ? 1 : atlasStageW / W;
  const useOf = village && village.blds ? atlasBldUses(village) : null;
  if (village) out.push(atlasVillageSvg(village, W, H, { ...S.atlasLayers, lamps: !!style.lamps, lw: style.lw || 1, z: atlasViewNow().z, px, useOf, hi: S.atlasUseHi }));
  if (village && !atlasGenPreview()) out.push(atlasFillSvg(W, H));  // 빈 블록 채우기 미리보기 (atlas-fill.js)
  else if (S.atlas.image) out.push(`<image href="${esc(atlasImageUrl())}" x="0" y="0" width="${W}" height="${H}" preserveAspectRatio="none"></image>`);
  else {
    out.push(`<rect class="at-ground" x="0" y="0" width="${W}" height="${H}"></rect>`);
    for (let x = 100; x < W; x += 100) out.push(`<line class="at-grid" x1="${x}" y1="0" x2="${x}" y2="${H}"></line>`);
    for (let y = 100; y < H; y += 100) out.push(`<line class="at-grid" x1="0" y1="${y}" x2="${W}" y2="${y}"></line>`);
  }
  const xy = (pl) => [pl.pin[0] * W, pl.pin[1] * H];
  const hidden = (pl) => S.atlasFog && !atlasKnown(pl, f);
  const pv = atlasGenPreview();
  const chars = pv ? [] : atlasChars();  // 미리보기 마을에는 인물 · 지나온 길을 그리지 않는다 (경로는 지금 마을 기준)
  const view = atlasViewNow();
  const z = view.z;
  const sc = 1 / z;  // 핀 · 이름표 · 인물은 확대해도 화면에서 같은 크기
  const labels = [];  // { x, y, text, cls, first } 를 모아 마지막에 서로 비켜 놓는다
  const deco = atlasDeco(village, view, W, H);  // 장식은 맨 위에 그리지만 이름표보다 먼저 자리를 잡는다

  // 지도 만들기 미리보기: 생성기가 고른 자리 (놓기로 고른 것만)
  if (pv) {
    pv.pins.filter((s) => S.atlasGen.take[s.place]).forEach((s) => {
      const x = s.x * W;
      const y = s.y * H;
      out.push(`<g class="at-sug"><title>${esc(s.name)}: 새 자리</title><circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(9 * sc).toFixed(2)}" stroke-width="${(2.5 * sc).toFixed(2)}"></circle></g>`);
      labels.push({ x, y, text: s.name, cls: '', first: true });
    });
  }

  // 이름으로 자리 찾기: 고른 후보 자리
  const fd = !pv && atlasFindNow();
  if (fd) {
    fd.spots.forEach((s) => {
      const o = s.options[fd.pick[s.place]];
      if (!o) return;
      const x = o.x * W;
      const y = o.y * H;
      out.push(`<g class="at-sug"><title>${esc(s.name)}: ${esc(o.what)}</title><circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(9 * sc).toFixed(2)}" stroke-width="${(2.5 * sc).toFixed(2)}"></circle></g>`);
      labels.push({ x, y, text: s.name, cls: '', first: true });
    });
  }

  // 지나온 길: 시작부터 지금 시점까지 놓인 장소를 차례로 잇는다 (거쳐 온 곳 포함).
  // 마을 데이터가 있으면 서버가 찾은 길 따라 경로(row.route)로 잇는다
  if (S.atlasTrail && !pv) {
    chars.forEach((c, ci) => {
      const pts = [];
      const names = [];
      let last = '';
      let walked = 0;
      const push = (q) => {
        const e = pts[pts.length - 1];
        if (!e || Math.hypot(e[0] - q[0], e[1] - q[1]) > 0.5) pts.push(q);
      };
      S.atlas.frames.slice(0, S.atlasFrame + 1).forEach((fr) => {
        const r = atlasRow(fr, c.id);
        if (!r || !r.place) return;
        const stops = [...r.via, r.place].map(atlasPlace);
        const start = r.route && [r.route.points[0][0] * W, r.route.points[0][1] * H];
        const end = pts[pts.length - 1];
        if (start && end && Math.hypot(end[0] - start[0], end[1] - start[1]) < 1 && stops.every((pl) => pl && pl.pin && !hidden(pl))) {
          r.route.points.forEach((q) => push([q[0] * W, q[1] * H]));
          stops.forEach((pl) => { if (pl.key !== last) names.push(pl.name); last = pl.key; });
          walked += r.route.meters;
          return;
        }
        stops.forEach((pl) => {
          if (!pl || !pl.pin || hidden(pl) || pl.key === last) return;
          push(xy(pl));
          names.push(pl.name);
          last = pl.key;
        });
      });
      if (pts.length < 2) return;
      const off = ((ci % 5) - 2) * 3;
      const focus = S.atlasFocus === c.id;
      const dim = S.atlasFocus && !focus;
      const tip = `${c.name || c.id}: ${names.join(' → ')}${walked ? `\n길 따라 ${atlasMeters(walked)}` : ''}`;
      out.push(`<polyline class="at-trail${dim ? ' dim' : ''}" points="${pts.map((q) => q.map((v) => (v + off * sc).toFixed(1)).join(',')).join(' ')}" stroke="${atlasColor(c.id)}" stroke-width="${((focus ? 5 : 3) * sc).toFixed(2)}"><title>${esc(tip)}</title></polyline>`);
    });
  }

  // 장소 (미리보기에서 새 자리로 옮길 장소는 새 자리만 그린다)
  (S.atlas.places || []).filter((pl) => pl.pin && !hidden(pl) && !(pv && S.atlasGen.take[pl.key]) && !(fd && fd.pick[pl.key] >= 0)).forEach((pl) => {
    const [x, y] = xy(pl);
    const later = !atlasKnown(pl, f);
    const hot = f.episode && f.mentioned.includes(pl.key);
    const sel = S.atlasSel === pl.key;
    const old = !!pv;  // 미리보기에서 옮기지 않는 장소: 지금(옛 마을) 자리라 흐리게
    const tip = `${pl.name}${old ? ' (지금 자리. 적용해도 그대로예요)' : ''}${pl.description ? ' · ' + pl.description : ''}${later ? `\n${pl.known_from}화부터 독자가 알아요` : ''}${hot ? `\n${f.episode}화에 나와요` : ''}`;
    out.push(`<g class="at-pin${later ? ' later' : ''}${sel ? ' sel' : ''}${old ? ' old' : ''}" data-atlas-pin="${esc(pl.key)}" tabindex="0" role="button" aria-label="${esc(pl.name + ' 자세히 보기. 화살표로 옮겨요')}"><title>${esc(tip)}</title>
      <circle class="at-hit" cx="${x}" cy="${y}" r="${(20 * sc).toFixed(2)}"></circle>
      ${hot ? `<circle class="at-hot" cx="${x}" cy="${y}" r="${(16 * sc).toFixed(2)}" stroke-width="${(3 * sc).toFixed(2)}"></circle>` : ''}
      <circle class="at-dot" cx="${x}" cy="${y}" r="${((sel ? 9 : 7) * sc).toFixed(2)}" stroke-width="${(2.5 * sc).toFixed(2)}"></circle></g>`);
    labels.push({ x, y, text: pl.name + (old ? ' (지금 자리)' : ''), cls: `${later ? ' later' : ''}${old ? ' old' : ''}`, first: sel });
  });
  // 인물 표 자리: 같은 장소에 모이면 둘레에 나눠 놓는다. 표는 움직이지 않는다 (인물 자리가 뜻이 있다)
  const groups = {};
  chars.forEach((c) => {
    const r = atlasRow(f, c.id);
    const pl = r && r.place && atlasPlace(r.place);
    if (!pl || !pl.pin || hidden(pl)) return;
    (groups[pl.key] = groups[pl.key] || []).push(c);
  });
  const toks = [];
  Object.entries(groups).forEach(([k, list]) => {
    const [px, py] = xy(atlasPlace(k));
    list.forEach((c, j) => toks.push({ c, ...atlasTokenAt(px, py, j, list.length, sc) }));
  });

  // 이름표 놓는 차례: 장식 · 인물 표 → 장소 이름표 → 구역 이름 → 길 이름. 앞에 놓은 것이 이기고, 뒤의 것은 taken 을 비켜 가거나 빠진다.
  // 그림 겹은 따로: 구역 · 길 이름이 장소 이름표 아래, 인물 표와 장식이 맨 위
  const taken = deco.boxes.concat(toks.map((t) => t.box));
  const names = atlasLabels(labels, sc, fs, taken);
  if (village && S.atlasLayers.wards !== false) out.push(atlasWardLabels(village, W, H, fs * 0.85, taken, z));
  if (village && S.atlasLayers.streets !== false && village.streets) out.push(atlasStreetLabels(village, W, H, fs * 0.78, taken, z));
  out.push(names);

  // 인물
  toks.forEach(({ c, x, y }) => {
    const dim = S.atlasFocus && S.atlasFocus !== c.id;
    out.push(`<g class="at-tok${dim ? ' dim' : ''}" data-action="atlasFocus" data-arg="${esc(c.id)}"><title>${esc((c.name || c.id) + ': ' + atlasRow(f, c.id).location)}</title>
      <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(12 * sc).toFixed(2)}" stroke-width="${(2.5 * sc).toFixed(2)}" fill="${atlasColor(c.id)}"></circle>
      <text x="${x.toFixed(1)}" y="${(y + 4.5 * sc).toFixed(1)}" font-size="${(12 * sc).toFixed(2)}" text-anchor="middle">${esc([...(c.name || c.id)][0])}</text></g>`);
  });
  out.push(deco.svg);
  // 화풍은 마을 그림에만 (배경 그림 · 모눈 지도는 앱 색 그대로)
  return `<svg class="at-map${village ? ` st-${S.atlasStyle}` : ''}${S.atlasPick ? ' picking' : ''}" viewBox="${atlasViewBox(view)}" role="group" aria-label="${esc(frameLabel(f))} 지도">${out.join('')}</svg>`;
}

// ----- 되돌리기 · 따라가기 계산 (화면을 모른다) -----

/** 그릴 거리 이름 고르기: 이름 있는 거리를 긴 것부터 보고, 이미 그린 같은 이름에서 gap(지도 단위) 안이면 건너뛴다.
    큰길은 폭이 바뀌는 곳마다 거리가 나뉘어(bldgs._streets) 같은 이름이 여러 번 나온다. draw(st) 가 거짓이면(자리 없음) 그리지 않은 것으로 본다.
    W, H: 지도 크기(st.mid 는 0~1). 돌려주는 값: 그린 거리 */
function atlasLabelPick(streets, W, H, gap, draw = () => true) {
  const drawn = {};
  return streets.filter((st) => st.name).sort((a, b) => b.length - a.length).filter((st) => {
    const x = st.mid[0] * W;
    const y = st.mid[1] * H;
    const same = drawn[st.name] || (drawn[st.name] = []);
    if (same.some(([px, py]) => Math.hypot(px - x, py - y) < gap) || !draw(st)) return false;
    same.push([x, y]);
    return true;
  });
}

/** 다각형 넓이 가운데 (0~1 좌표). 넓이가 0 이면 꼭짓점 평균 */
function atlasMid(ln) {
  let a = 0;
  let x = 0;
  let y = 0;
  ln.forEach((q, j) => {
    const p = ln[(j + 1) % ln.length];
    const c = q[0] * p[1] - p[0] * q[1];
    a += c;
    x += (q[0] + p[0]) * c;
    y += (q[1] + p[1]) * c;
  });
  if (Math.abs(a) < 1e-9) return [ln.reduce((n, q) => n + q[0], 0) / ln.length, ln.reduce((n, q) => n + q[1], 0) / ln.length];
  return [x / (3 * a), y / (3 * a)];
}

/** 다각형 넓이 (0~1 좌표를 W × H 로 늘린 지도 단위) */
function atlasArea(ln, W = 1, H = 1) {
  return Math.abs(ln.reduce((n, q, j) => {
    const p = ln[(j + 1) % ln.length];
    return n + q[0] * p[1] - p[0] * q[1];
  }, 0)) / 2 * W * H;
}

/** 그릴 구역 이름 고르기: 길 이름과 같은 규칙(atlasLabelPick)에 넓이를 길이 삼아 넓은 구역부터 본다.
    wards: [{ name, shape }] (shape 는 0~1). draw(wd) 는 wd.mid(0~1 넓이 가운데)를 받는다. 돌려주는 값: 그린 구역 */
function atlasWardPick(wards, W, H, gap, draw = () => true) {
  return atlasLabelPick(wards.map((wd) => ({ ...wd, length: atlasArea(wd.shape, W, H), mid: atlasMid(wd.shape) })), W, H, gap, draw);
}

/** 인물 표 자리: 장소 점(px, py)의 오른쪽 아래, 같은 장소에 n 명이면 둘레에 나눠 놓는다 (j: 차례, sc: 1/확대).
    돌려주는 값: { x, y, box } (box 는 표 동그라미 상자. 이름표보다 먼저 taken 에 넣는다) */
function atlasTokenAt(px, py, j, n, sc) {
  const a = (j / n) * Math.PI * 2 + Math.PI / 4;
  const rr = (n > 1 ? 18 + n * 2 : 0) * sc;
  const x = px + 16 * sc + Math.cos(a) * rr;
  const y = py + 16 * sc + Math.sin(a) * rr;
  const r = 12 * sc;
  return { x, y, box: [x - r, y - r, x + r, y + r] };
}

/** 축척 막대: 보이는 폭의 약 1/6 에 가장 가까운 둥근 값 (1 · 2 · 5 × 10ⁿ m, 10m 부터).
    mpu: 지도 단위 1 이 몇 m, z: 확대 배율, W: 지도 폭(지도 단위). 축척을 모르면 null.
    돌려주는 값: { meters, label: '200m' · '1km', units: 막대 길이(지도 단위) } */
function atlasScaleBar(mpu, z = 1, W = 1000) {
  if (!(mpu > 0) || !Number.isFinite(mpu) || !(z > 0)) return null;
  const want = ((W / z) / 6) * mpu;
  let best = 10;
  for (let p = 10; p <= 1e7; p *= 10) {
    [1, 2, 5].forEach((d) => {
      if (Math.abs(Math.log(d * p / want)) < Math.abs(Math.log(best / want))) best = d * p;
    });
  }
  return { meters: best, label: best >= 1000 ? `${best / 1000}km` : `${best}m`, units: best / mpu };
}

/** 두 장소 자리 표({장소 키: [x, y]}) 사이에 바뀐 것만. { b: 전 자리, a: 뒤 자리 } (없던 자리는 null), 같으면 null */
function atlasPinDiff(before, after) {
  const b = {};
  const a = {};
  new Set([...Object.keys(before), ...Object.keys(after)]).forEach((k) => {
    const x = before[k] || null;
    const y = after[k] || null;
    if (JSON.stringify(x) !== JSON.stringify(y)) { b[k] = x; a[k] = y; }
  });
  return Object.keys(b).length ? { b, a } : null;
}

/** 자리 표에 바뀐 부분(atlasPinDiff 의 b 나 a)을 덮어 저장할 pins 목록으로 */
function atlasPinApply(map, part) {
  const out = { ...map };
  Object.entries(part).forEach(([k, v]) => { if (v) out[k] = v; else delete out[k]; });
  return Object.entries(out).map(([place, [x, y]]) => ({ place, x, y }));
}

/** 이름으로 자리 찾기의 처음 고름 {장소 키: 후보 번호, -1 은 놓지 않기}. 후보가 하나뿐이고 아직 놓지 않은 장소만 고른다 */
function atlasFindDefault(spots) {
  return Object.fromEntries(spots.map((s) => [s.place, s.options.length === 1 && !s.had ? 0 : -1]));
}

/** 지금 자리 표에 고른 후보 자리를 덮은 pins 목록 (고르지 않은 장소는 그대로) */
function atlasFindPins(map, spots, pick) {
  const part = {};
  spots.forEach((s) => {
    const o = s.options[pick[s.place]];
    if (o) part[s.place] = [o.x, o.y];
  });
  return atlasPinApply(map, part);
}

/** 보는 범위 view({x, y, z}, 지도 단위)에 box([x0, y0, x1, y1])가 여백을 두고 들어오게 옮긴 범위.
    이미 들어 있으면 null. 다 안 들어가면 배율을 낮춘다 (1까지) */
function atlasFollowView(view, box, W, H) {
  const vw = W / view.z;
  const vh = H / view.z;
  const pad = Math.min(vw, vh) * 0.12;
  if (box[0] >= view.x + pad && box[2] <= view.x + vw - pad && box[1] >= view.y + pad && box[3] <= view.y + vh - pad) return null;
  const z = Math.max(1, Math.min(view.z, W / (box[2] - box[0] + pad * 2), H / (box[3] - box[1] + pad * 2)));
  const nw = W / z;
  const nh = H / z;
  const clamp = (n, hi) => Math.min(hi, Math.max(0, n));
  return { x: clamp((box[0] + box[2]) / 2 - nw / 2, W - nw), y: clamp((box[1] + box[3]) / 2 - nh / 2, H - nh), z };
}

// ----- 확대 · 이동, 이름표 -----

/** 지금 보는 범위. 지도 비율이 바뀌었으면(새 마을) 범위를 지도 안으로 줄인다 */
function atlasViewNow() {
  const v = S.atlasView;
  const W = ATLAS_W;
  const H = atlasH();
  v.z = Math.min(8, Math.max(1, v.z));
  v.x = Math.min(W - W / v.z, Math.max(0, v.x));
  v.y = Math.min(H - H / v.z, Math.max(0, v.y));
  return v;
}
const atlasViewBox = (v) => `${v.x.toFixed(1)} ${v.y.toFixed(1)} ${(ATLAS_W / v.z).toFixed(1)} ${(atlasH() / v.z).toFixed(1)}`;

/** 화면 자리(clientX, clientY)를 가운데 두고 배율을 z 로 */
function atlasZoomAt(z, clientX, clientY) {
  atlasFollowStop();
  const svg = document.querySelector('.at-map');
  const v = atlasViewNow();
  const W = ATLAS_W;
  const H = atlasH();
  let fx = 0.5;
  let fy = 0.5;
  if (svg && clientX != null) {
    const box = svg.getBoundingClientRect();
    fx = (clientX - box.left) / box.width;
    fy = (clientY - box.top) / box.height;
  }
  const mx = v.x + (fx * W) / v.z;
  const my = v.y + (fy * H) / v.z;
  v.z = Math.min(8, Math.max(1, z));
  v.x = mx - (fx * W) / v.z;
  v.y = my - (fy * H) / v.z;
  atlasViewNow();
  atlasRedraw();
}

let atlasRedrawQueued = false;
/** 확대 · 이동 중에는 지도만 다시 그린다 (한 번의 화면 갱신에 한 번) */
function atlasRedraw() {
  if (atlasRedrawQueued) return;
  atlasRedrawQueued = true;
  const draw = () => {
    atlasRedrawQueued = false;
    const stage = document.getElementById('atlas-stage');
    if (stage) stage.innerHTML = atlasStage();
  };
  if (document.hidden) setTimeout(draw, 0); else requestAnimationFrame(draw);  // 숨은 탭에서는 화면 갱신 콜백이 멈춘다
}

let atlasStageW = 0;        // 마지막으로 잰 지도 화면 폭 (px)
let atlasExporting = false;  // 내보낼 때는 화면 폭과 상관없이 지도 단위 15
let atlasMeasureQueued = false;
/** 이름표 글자 크기(지도 단위): 화면에서 13px(폭 480px 아래는 12px)이 되게 화면 폭과 확대 배율로 정한다.
    지도가 아직 화면에 없으면(처음 그릴 때) 지도 단위 15로 그리고, 붙은 뒤 재서 다시 그린다 */
function atlasLabelFs(z) {
  if (atlasExporting) return 15;
  const svg = document.querySelector('#atlas-stage .at-map');
  const w = svg ? svg.getBoundingClientRect().width : 0;
  if (w) atlasStageW = w;
  else if (!atlasStageW && !atlasMeasureQueued) {
    atlasMeasureQueued = true;
    setTimeout(() => { atlasMeasureQueued = false; if (document.querySelector('#atlas-stage .at-map')) atlasRedraw(); }, 0);
  }
  if (!atlasStageW) return 15 / z;
  return ((atlasStageW < 480 ? 12 : 13) * ATLAS_W) / (atlasStageW * z);
}
window.addEventListener('resize', () => {
  const svg = document.querySelector('#atlas-stage .at-map');
  if (svg && Math.abs(svg.getBoundingClientRect().width - atlasStageW) > 1) atlasRedraw();
});

/** 글자 폭 어림: 한글 · 한자는 1em, 나머지는 0.6em */
const atlasTextW = (t, fs) => [...t].reduce((n, ch) => n + (ch.charCodeAt(0) > 0x2e80 ? 1 : 0.6), 0) * fs;

/** 이름표를 서로 · 다른 점과 겹치지 않게 놓는다. 점 둘레 여덟 자리를 먼저 보고, 다 막히면 점점 먼 고리에서 빈자리를 찾아
    지시선을 긋는다. 끝내 못 찾으면 마지막 자리에 겹쳐 둔다. sc: 핀 크기 배율(1/확대), fs: 글자 크기(지도 단위)
    taken: 먼저 차지한 상자 (지도 장식 · 인물 표). 이것도 비켜 가고, 놓은 이름표 상자를 더해 돌려준다 */
function atlasLabels(list, sc, fs = 15 * sc, taken = []) {
  const g = 14 * sc;
  const dots = list.map((l) => [l.x - 7 * sc, l.y - 7 * sc, l.x + 7 * sc, l.y + 7 * sc]);
  const placed = taken.slice();
  const hit = (b) => placed.some((p) => b[0] < p[2] && b[2] > p[0] && b[1] < p[3] && b[3] > p[1])
    || dots.some((d) => b[0] < d[2] && b[2] > d[0] && b[1] < d[3] && b[3] > d[1]);
  const near = [[0, -g, 'middle'], [0, g + fs * 0.8, 'middle'], [g, fs * 0.35, 'start'], [-g, fs * 0.35, 'end'],
    [g * 0.8, -g * 0.8, 'start'], [-g * 0.8, -g * 0.8, 'end'], [g * 0.8, g + fs * 0.5, 'start'], [-g * 0.8, g + fs * 0.5, 'end']];
  const far = [];
  [2.5, 4, 5.5, 7].forEach((r) => {
    for (let a = 0; a < 8; a++) {
      const t = -Math.PI / 2 + (a * Math.PI) / 4;
      const dx = Math.cos(t) * g * r;
      far.push([dx, Math.sin(t) * g * r + fs * 0.35, Math.abs(dx) < 1 ? 'middle' : dx > 0 ? 'start' : 'end']);
    }
  });
  const spots = near.concat(far);
  const order = list.map((l, i) => i).sort((a, b) => (list[b].first ? 1 : 0) - (list[a].first ? 1 : 0) || list[a].y - list[b].y);
  const out = [];
  order.forEach((i) => {
    const l = list[i];
    const w = atlasTextW(l.text, fs);
    const boxOf = ([dx, dy, a]) => {
      const x0 = a === 'middle' ? l.x + dx - w / 2 : a === 'start' ? l.x + dx : l.x + dx - w;
      return [x0, l.y + dy - fs, x0 + w, l.y + dy + fs * 0.25];
    };
    let k = spots.findIndex((sp) => !hit(boxOf(sp)));
    if (k < 0) k = spots.length - 1;
    const [dx, dy, a] = spots[k];
    placed.push(boxOf(spots[k]));
    out.push(`${k >= near.length ? `<line class="at-leader" x1="${l.x.toFixed(1)}" y1="${l.y.toFixed(1)}" x2="${(l.x + dx).toFixed(1)}" y2="${(l.y + dy - fs * 0.4).toFixed(1)}" stroke-width="${sc.toFixed(2)}"></line>` : ''}<text class="at-name${l.cls}" x="${(l.x + dx).toFixed(1)}" y="${(l.y + dy).toFixed(1)}" text-anchor="${a}" font-size="${fs.toFixed(2)}" stroke-width="${(fs * 0.27).toFixed(2)}">${esc(l.text)}</text>`);
  });
  taken.push(...placed.slice(taken.length), ...dots);  // 뒤에 놓는 구역 · 길 이름이 비켜 가도록
  return `<g class="at-labels">${out.join('')}</g>`;
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
      if (from && !(S.atlasFog && !atlasKnown(from, f))) {
        where += ` <span class="small">← ${esc(from.name)}에서 옮김</span>`;
        if (r.route) where += ` <span class="small at-walk">길 따라 ${atlasMeters(r.route.meters)} · 걸어서 약 ${r.route.minutes}분</span>`;
      }
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

function atlasLayoutBox() {
  const lo = S.atlas.layout;
  const input = '<input id="at-layout" type="file" accept=".json,.geojson,.osm,.xml,application/json,application/geo+json" data-atlas-layout hidden>';
  if (!lo) {
    return `<div class="at-box"><h3>마을 데이터</h3>
      <div class="small">Watabou 마을 · 도시 생성기에서 Menu → Export as → JSON으로 받은 파일을 올리면 건물 · 길 · 물을 그려요. 장소를 건물에 놓으면 인물이 옮겨 간 길을 실제 길을 따라 그리고 거리와 걷는 시간을 보여 줘요.</div>
      <div class="small">실제 동네는 OpenStreetMap에서 받아 올려요. openstreetmap.org에서 '내보내기'로 받은 .osm 파일이나, overpass-turbo에서 '내보내기 → GeoJSON'으로 받은 파일을 올리면 실제 건물 · 길 · 가게 이름 · 주소를 그려요. 한 변 6km까지, 20MB까지예요.</div>
      <div class="row"><label class="btn small" for="at-layout">마을 데이터 올리기</label>${input}</div></div>`;
  }
  const missing = !S.atlasLayout ? '<div class="note err" role="alert">마을 데이터 파일을 읽지 못했어요. 다시 올려 주세요.</div>' : '';
  const word = { 'canon-city': '도시', 'canon-modern': '현대 동네', osm: '실제 지도' }[lo.generator] || '마을';
  const coast = lo.coast_broken ? '<div class="note" role="status">해안선이 끊겨 바다를 그리지 못했어요.</div>' : '';
  const src = lo.source ? `<div class="small">지도 데이터 ${esc(lo.source)} (<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">ODbL</a>). 지도를 내보내 쓸 때도 이 출처를 함께 적어 주세요.</div>` : '';
  return `<div class="at-box"><h3>${word} 데이터</h3>${missing}${coast}${src}
    <div class="small">길 ${lo.roads}개${lo.bridges ? ` · 다리 ${lo.bridges}개` : ''} · 건물 ${lo.buildings}채 · 약 ${atlasMeters(lo.width_m)} × ${atlasMeters(lo.height_m)}</div>
    <label class="at-scale small">1단위 = <input type="number" min="0.01" max="1000" step="0.1" value="${lo.meters}" data-atlas-meters aria-label="마을 데이터 1단위가 몇 m인지"> m</label>
    <div class="small">거리가 어색하면 축척을 바꾸세요. 걷는 시간은 초속 1.3m로 셈해요. 건물 안을 누르면 장소가 그 건물 가운데에 놓여요.</div>
    ${lo.generator === 'osm' ? atlasFillBox(lo) : ''}
    <div class="row"><button type="button" class="btn small" data-action="atlasFindOpen">이름으로 자리 찾기</button>
      <label class="btn small" for="at-layout">다른 파일 올리기</label>${input}
      <button type="button" class="btn small ghost" data-action="atlasDropLayout">${word} 지우기</button></div></div>`;
}

function atlasBackground() {
  if (S.atlas.layout) {
    return S.atlas.image ? '<div class="at-box"><h3>배경 그림</h3><div class="small">마을 데이터가 있는 동안은 배경 그림 대신 마을을 그려요. 마을을 지우면 그림이 다시 보여요.</div></div>' : '';
  }
  return `<div class="at-box"><h3>배경 그림</h3>
    <div class="small">직접 그리거나 다른 도구(Azgaar, Inkarnate 등)로 만든 지도 그림을 올리면 그 위에 장소를 놓아요. PNG · JPG · WEBP, 15MB까지.</div>
    <div class="row"><label class="btn small" for="at-image">${S.atlas.image ? '그림 바꾸기' : '그림 올리기'}</label><input id="at-image" type="file" accept="image/png,image/jpeg,image/webp,image/gif" data-atlas-image hidden>
      ${S.atlas.image ? '<button type="button" class="btn small ghost" data-action="atlasDropImage">그림 지우기</button>' : ''}</div>
    ${atlasMpu() ? '' : `<div class="small at-um-note">지도 크기를 몰라 축척 막대를 그리지 않아요.${S.atlas.travel && S.atlas.travel.enabled ? ' 이동 시간 검사 칸에 지도 가로를 km로 적으면 그려요.' : ' 이동 시간 검사를 켜고 지도 가로를 km로 적으면 그려요.'}</div>`}</div>`;
}

// ----- 화면 조립 -----

function atlasToggles(map = true) {
  const minors = P().characters.some((c) => c.tier === 'minor');
  return `<div class="row at-toggles">
    ${map ? `<label><input type="checkbox" data-atlas-opt="atlasTrail"${S.atlasTrail ? ' checked' : ''}>지나온 길</label>` : ''}
    <label title="아직 독자에게 드러나지 않은 장소와 그곳에 있는 인물을 가려요"><input type="checkbox" data-atlas-opt="atlasFog"${S.atlasFog ? ' checked' : ''}>독자 시점</label>
    ${minors ? `<label><input type="checkbox" data-atlas-opt="atlasMinor"${S.atlasMinor ? ' checked' : ''}>단역도 보기</label>` : ''}</div>
    ${map && atlasVillage() ? atlasLayerToggles() : ''}`;
}

function atlasLayerToggles() {
  const styles = Object.entries(ATLAS_STYLES).map(([k, st], i) => `<option value="${k}"${S.atlasStyle === k ? ' selected' : ''}>${esc(st.label)} (${i + 1})</option>`).join('');
  const v = atlasVillage();
  const has = { wards: v && v.wards && v.wards.length, uses: v && v.blds && v.blds.length, streets: v && v.streets && v.streets.length };
  const layers = Object.entries(ATLAS_LAYERS).filter(([k]) => !(k in has) || has[k]);
  return `<div class="row at-toggles at-layers"><span class="small">지도:</span>
    <label title="화풍 고르기 (1~4)">화풍 <select data-atlas-style aria-label="지도 화풍">${styles}</select></label>${layers.map(([k, [label, key]]) => `<label title="${esc(label)} 끄고 켜기 (${key.toUpperCase()})"><input type="checkbox" data-atlas-layer="${k}"${S.atlasLayers[k] ? ' checked' : ''}>${esc(label)}</label>`).join('')}
    <span class="row at-export"><button type="button" class="btn small ghost" data-action="atlasExport" data-arg="svg">SVG로 저장</button><button type="button" class="btn small ghost" data-action="atlasExport" data-arg="png">PNG로 저장</button></span></div>`;
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
  const z = atlasViewNow().z;
  return `<div class="at-map-wrap${z > 1 ? ' zoomed' : ''}">${atlasSvg()}${atlasTitleBox()}${atlasZoomBox()}${atlasBldMenu()}${atlasGenBar()}</div>`;
}

/** 지도 이름 고치는 칸. 이름이 있으면 제목 틀(atlasDeco, SVG)을 눌러 열고, 없으면 틀 대신 '이름 정하기' 버튼을 띄운다
    (미리보기 중에는 바꿀 수 없음) */
function atlasTitleBox() {
  const pv = atlasGenPreview();
  const t = pv ? pv.title : S.atlas.title;
  if (!t || !atlasVillage() || !S.atlasLayers.deco || pv) return '';
  if (S.atlasTitleEdit) {
    return `<form class="at-title-edit" data-atlas-title-form><input name="title" maxlength="40" value="${esc(t.custom ? t.title : '')}" placeholder="${esc(t.title || `${t.kind || '마을'} 이름`)}" aria-label="${esc(t.kind || '마을')} 이름">
      <button type="submit" class="btn small primary">저장</button><button type="button" class="btn small ghost" data-action="atlasTitleEdit" data-arg="">취소</button></form>`;
  }
  if (t.title) return '';
  return `<button type="button" class="btn small at-title-add" data-action="atlasTitleEdit" data-arg="1" title="지도 이름을 정하면 제목 틀이 생겨요 (D로 장식 숨기기)">${esc(t.kind || '마을')} 이름 정하기</button>`;
}

function atlasZoomBox() {
  const z = atlasViewNow().z;
  return `<div class="at-zoom" role="group" aria-label="확대">
    <button type="button" class="btn small" data-action="atlasZoom" data-arg="in" title="확대 (+)" aria-label="확대">＋</button>
    <button type="button" class="btn small" data-action="atlasZoom" data-arg="out" title="축소 (-)" aria-label="축소"${z <= 1 ? ' disabled' : ''}>－</button>
    <button type="button" class="btn small" data-action="atlasZoom" data-arg="fit" title="전체 보기 (0)" aria-label="전체 보기"${z <= 1 ? ' disabled' : ''}>⤢</button>
    ${atlasUndoBox()}</div>`;
}

/** 누른 건물 메뉴: 이 건물에 장소 놓기, 새 장소로 등록 */
function atlasBldMenu() {
  const b = S.atlasBld;
  if (!b || atlasGenPreview()) return '';
  const v = atlasVillage();
  const num = v && (v.numbers || []).indexOf(b.i);
  const opts = (S.atlas.places || []).map((pl) => `<option value="${esc(pl.key)}">${esc(pl.name)}${pl.pin ? ' (옮기기)' : ''}</option>`).join('');
  const ideas = S.atlasIdeas ? S.atlasIdeas.map((n) => `<button type="button" class="btn small ghost" data-action="atlasBldIdea" data-arg="${esc(n)}">${esc(n)}</button>`).join('') : '<span class="small">이름 후보를 불러오는 중…</span>';
  const pos = b.up ? `bottom:${Math.max(4, b.h - b.sy + 8)}px` : `top:${b.sy + 8}px`;
  const info = atlasBldInfo(b.i);
  const head = info ? `${esc(info.label)}${info.name ? ` · ${esc(info.name)}` : ''}` : (num >= 0 ? `집 ${num + 1}` : '건물');
  if (info && b.edit) return `<div class="at-bld" style="left:${b.sx}px;${pos}" role="dialog" aria-label="건물 고치기">${atlasBldEdit(info)}</div>`;
  const who = info ? info.residents.map((cid) => (P().characters.find((c) => c.id === cid) || { name: cid }).name).filter(Boolean) : [];
  const facts = info ? [info.addr || (info.street ? `${info.street} ${info.no || '길가'}` : ''), `${info.floors}층`, info.people ? `사는 사람 ${info.people}명` : '', info.annex ? '곁채 (본채 정보)' : ''].filter(Boolean) : [];
  return `<div class="at-bld" style="left:${b.sx}px;${pos}" role="dialog" aria-label="건물">
    <div class="between"><strong>${head}</strong><button type="button" class="btn small ghost" data-action="atlasBldClose" aria-label="닫기">✕</button></div>
    ${facts.length ? `<div class="small at-bld-facts">${esc(facts.join(' · '))}${num >= 0 ? ` · 집 ${num + 1}` : ''}</div>` : ''}
    ${info && info.made ? '<div class="small at-um-note">지은 건물 (OpenStreetMap에 없음)</div>' : ''}
    ${who.length ? `<div class="small">사는 인물: ${esc(who.join(', '))}</div>` : ''}
    ${info && info.tenants.length ? `<div class="small at-bld-tenants">입점: ${esc(info.tenants.join(', '))}</div>` : ''}
    ${info && info.note ? `<div class="small at-um-note">${esc(info.note)}</div>` : ''}
    ${info && !atlasGenPreview() ? `<div class="row"><button type="button" class="btn small" data-action="atlasBldEditOpen">고치기</button>${info.edited ? '<span class="small at-um-note">고친 건물</span>' : ''}</div>` : ''}
    ${opts ? `<label class="small">이 건물에 놓기<span class="row"><select data-atlas-bld-place>${opts}</select><button type="button" class="btn small" data-action="atlasBldPut">놓기</button></span></label>` : ''}
    <form class="at-bld-new" data-atlas-bld-form><label class="small">새 장소로 등록<span class="row"><input name="name" maxlength="40" placeholder="이름" aria-label="새 장소 이름" required><button type="submit" class="btn small primary">등록</button></span></label>
      <div class="at-chips">${ideas}</div></form></div>`;
}

/** 건물 고치기 칸: 쓰임(묶음별), 이름 · 간판, 메모, 사는 · 일하는 인물 */
function atlasBldEdit(info) {
  const uses = (S.atlas.gen && S.atlas.gen.uses) || {};
  const v = atlasVillage();
  const modern = new Set((S.atlas.gen && S.atlas.gen.modern) || []);
  const showModern = (v && (v.generator === 'osm' || v.generator === 'canon-modern')) || (S.atlas.gen && S.atlas.gen.modern_style);
  const groups = {};
  Object.entries(uses).forEach(([id, [label, g]]) => {
    if (modern.has(id) && !showModern && id !== info.use) return;
    (groups[g] = groups[g] || []).push([id, label]);
  });
  const GROUP = { home: '집', noble: '저택', shop: '가게', food: '먹거리', craft: '공방', lodging: '여관 · 주점', faith: '신앙', civic: '공공', care: '돌봄', work: '일터', store: '창고 · 곁채' };
  const opts = Object.entries(groups).map(([g, list]) => `<optgroup label="${esc(GROUP[g] || g)}">${list.map(([id, label]) => `<option value="${esc(id)}"${id === info.use ? ' selected' : ''}>${esc(label)}</option>`).join('')}</optgroup>`).join('');
  const people = P().characters.map((c) => `<label class="small"><input type="checkbox" name="who" value="${esc(c.id)}"${info.residents.includes(c.id) ? ' checked' : ''}> ${esc(c.name || c.id)}</label>`).join('');
  return `<form class="at-bld-edit" data-atlas-bld-edit>
    <div class="between"><strong>건물 고치기</strong><button type="button" class="btn small ghost" data-action="atlasBldClose" aria-label="닫기">✕</button></div>
    <label class="small">쓰임<select name="use">${opts}</select></label>
    <label class="small">이름 · 간판<input name="name" maxlength="40" value="${esc(info.name)}" placeholder="비우면 정해진 이름"></label>
    <label class="small">메모<textarea name="note" rows="2" maxlength="500">${esc(info.note)}</textarea></label>
    ${people ? `<fieldset class="at-bld-who"><legend class="small">여기 사는 · 일하는 인물</legend>${people}</fieldset>` : ''}
    <div class="row"><button type="submit" class="btn small primary">저장</button>
      ${info.edited ? '<button type="button" class="btn small ghost" data-action="atlasBldReset">처음 값으로</button>' : ''}
      <button type="button" class="btn small ghost" data-action="atlasBldEditOpen" data-arg="">취소</button></div></form>`;
}

/** 옆 칸 '건물 쓰임': 본채 쓰임별 수. 누르면 지도에서 그 건물들을 테두리로 강조한다 */
function atlasUseBox() {
  const v = atlasVillage();
  if (!v || !v.blds || !v.blds.length || atlasGenPreview()) return '';
  const uses = atlasBldUses(v);
  const count = {};
  v.blds.forEach((b, i) => { if (b.of === undefined) count[uses[i]] = (count[uses[i]] || 0) + 1; });
  const homes = ['home', 'farm', 'tenement', 'building', 'apartment', 'dorm'];  // bldgs.HOMES
  const label = (u) => ((S.atlas.gen && S.atlas.gen.uses && S.atlas.gen.uses[u]) || [u])[0];
  const order = Object.entries(count).sort((a, b) => (homes.includes(a[0]) - homes.includes(b[0])) || b[1] - a[1]);
  const people = v.blds.reduce((n, b) => n + (b.people || 0), 0);
  const chips = order.map(([u, n]) => `<button type="button" class="btn small ${S.atlasUseHi === u ? 'primary' : 'ghost'}" data-action="atlasUseHi" data-arg="${esc(u)}" aria-pressed="${S.atlasUseHi === u}">${esc(label(u))} ${n}</button>`).join('');
  return `<div class="at-box"><h3>건물 쓰임</h3>
    <div class="small">본채 ${Object.values(count).reduce((a, b) => a + b, 0).toLocaleString()}채 · 사는 사람 약 ${people.toLocaleString()}명 · 거리 ${(v.streets || []).length}곳. 누르면 지도에서 그 건물을 강조해요.</div>
    <div class="at-chips">${chips}</div></div>`;
}

function atlasSide() {
  if (atlasGenPreview()) return atlasGenBox();  // 미리보기 중에는 고를 것만 보인다
  return atlasFindBox() + atlasPlaceBox() + atlasWho() + atlasTravelBox() + atlasLoose() + atlasUseBox() + atlasGenBox() + atlasLayoutBox() + atlasBackground();
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

/** 장소 자리를 저장한다. undo { before: 바꾸기 전 자리 표, label } 를 주면 되돌리기 기록에 남긴다. 저장했으면 true */
async function atlasSavePins(pins, msg, undo) {
  try {
    await saveIfDirty();
    S.project = await api('PUT', `/projects/${enc(S.name)}/atlas/pins`, { pins });
    await atlasLoad();
    if (undo) atlasRecord(undo.before, undo.label);
    atlasRefresh();
    if (msg) toast(msg);
    return true;
  } catch (e) {
    toast(e.message, true);
    await atlasLoad();
    atlasRefresh();
    return false;
  }
}

function atlasPins() {
  return (S.atlas.places || []).filter((pl) => pl.pin).map((pl) => ({ place: pl.key, x: pl.pin[0], y: pl.pin[1] }));
}

// ----- 장소 이동 되돌리기: 이 화면에서 최근 20번. 작품이 바뀌면 비운다 -----

const atlasHist = { name: '', back: [], fwd: [] };
let atlasUndoBusy = false;
let atlasKeyBefore = null;  // 화살표로 옮기기 시작할 때 { map: 자리 표, key }
const atlasPinMap = () => Object.fromEntries(atlasPins().map((x) => [x.place, [x.x, x.y]]));

function atlasHistNow() {
  if (atlasHist.name !== S.name) Object.assign(atlasHist, { name: S.name, back: [], fwd: [] });
  return atlasHist;
}

/** 바뀐 자리를 기록한다. label 은 '…기'로 끝난다 ("'주막' 옮기기"). gen: 지도 만들기 적용 (마을 그림은 되돌리지 않는다) */
function atlasRecord(before, label, after = atlasPinMap(), gen = false) {
  const d = atlasPinDiff(before, after);
  if (!d) return;
  const h = atlasHistNow();
  h.back = [...h.back, { ...d, label, gen }].slice(-20);
  h.fwd = [];
  atlasUndoPaint();
}

/** 화살표로 옮기던 자리를 저장하고 기록한다 (멈추고 0.6초 뒤, 또는 되돌리기 전에) */
async function atlasKeySave() {
  clearTimeout(atlasKeyTimer);
  atlasKeyTimer = null;
  const before = atlasKeyBefore;
  if (!before) return;
  atlasKeyBefore = null;
  const pins = atlasPins();
  const after = atlasPinMap();
  try {
    await saveIfDirty();
    S.project = await api('PUT', `/projects/${enc(S.name)}/atlas/pins`, { pins });
    const pl = atlasPlace(before.key);
    atlasRecord(before.map, `'${pl ? pl.name : before.key}' 옮기기`, after);
    toast('저장했어요');
  } catch (err) {
    toast(err.message, true);
  }
}

const atlasMod = () => (/Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl+');

function atlasUndoBox() {
  const h = atlasHistNow();
  if ((!h.back.length && !h.fwd.length) || atlasGenPreview()) return '<div id="at-undo" hidden></div>';
  const last = (list) => list[list.length - 1];
  const mod = atlasMod();
  return `<div id="at-undo" class="at-undo" role="group" aria-label="장소 이동 되돌리기">
    <button type="button" class="btn small" data-action="atlasUndo" data-arg="-1" title="${h.back.length ? esc(last(h.back).label) + ' 되돌리기' : '되돌릴 것 없음'} (${mod}Z)" aria-label="되돌리기"${h.back.length ? '' : ' disabled'}>↶</button>
    <button type="button" class="btn small" data-action="atlasUndo" data-arg="1" title="${h.fwd.length ? esc(last(h.fwd).label) + ' 다시 하기' : '다시 할 것 없음'} (${mod}Shift+Z)" aria-label="다시 하기"${h.fwd.length ? '' : ' disabled'}>↷</button></div>`;
}

function atlasUndoPaint() {
  const el = document.getElementById('at-undo');
  if (el) el.outerHTML = atlasUndoBox();
}

// ----- 재생할 때 따라가기 -----

let atlasFollowAnim = 0;
const atlasFollowStop = () => { cancelAnimationFrame(atlasFollowAnim); atlasFollowAnim = 0; };

/** 확대해 보고 있으면 이 화에 옮겨 간 인물(고른 인물이 있으면 그 인물)의 자리가 보이게 보는 범위를 부드럽게 옮긴다 */
function atlasFollow() {
  if (atlasViewNow().z <= 1 || atlasGenPreview() || !document.getElementById('atlas-stage')) return;
  const W = ATLAS_W;
  const H = atlasH();
  const f = atlasFrameNow();
  const prev = S.atlas.frames[S.atlasFrame - 1];
  const pts = [];
  atlasChars().forEach((c) => {
    if (S.atlasFocus && S.atlasFocus !== c.id) return;
    const r = atlasRow(f, c.id);
    const before = prev && atlasRow(prev, c.id);
    const came = r && r.place && (r.moved || !before || !before.place);  // 옮겨 왔거나 이 화에 처음 자리가 생겼다
    if (!r || !r.place || (!S.atlasFocus && !came)) return;
    const pl = atlasPlace(r.place);
    if (pl && pl.pin && !(S.atlasFog && !atlasKnown(pl, f))) pts.push([pl.pin[0] * W, pl.pin[1] * H]);
  });
  if (!pts.length) return;
  const box = [Math.min(...pts.map((q) => q[0])), Math.min(...pts.map((q) => q[1])), Math.max(...pts.map((q) => q[0])), Math.max(...pts.map((q) => q[1]))];
  const to = atlasFollowView({ ...S.atlasView }, box, W, H);
  if (!to) return;
  atlasFollowStop();
  const from = { ...S.atlasView };
  if (document.hidden || matchMedia('(prefers-reduced-motion: reduce)').matches) {
    Object.assign(S.atlasView, to);
    atlasRedraw();
    return;
  }
  const t0 = performance.now();
  const step = (now) => {
    const t = Math.min(1, (now - t0) / 450);
    const e = 1 - (1 - t) ** 3;
    Object.assign(S.atlasView, { x: from.x + (to.x - from.x) * e, y: from.y + (to.y - from.y) * e, z: from.z + (to.z - from.z) * e });
    const svg = document.querySelector('#atlas-stage .at-map');
    if (to.z !== from.z || !svg) atlasRedraw();  // 배율이 바뀌면 핀 · 이름표 크기도 바뀐다
    else svg.setAttribute('viewBox', atlasViewBox(atlasViewNow()));
    atlasFollowAnim = t < 1 ? requestAnimationFrame(step) : 0;
  };
  atlasFollowAnim = requestAnimationFrame(step);
}

/** 화면 좌표 → 0~1 지도 좌표 */
function atlasPoint(e) {
  const svg = document.querySelector('.at-map');
  if (!svg) return null;
  const box = svg.getBoundingClientRect();
  const v = atlasViewNow();
  const x = (v.x + ((e.clientX - box.left) / box.width) * (ATLAS_W / v.z)) / ATLAS_W;
  const y = (v.y + ((e.clientY - box.top) / box.height) * (atlasH() / v.z)) / atlasH();
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
    atlasFollow();
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
      atlasFollow();
    }, 1000);
    atlasRefresh();
    atlasFollow();
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
    const name = pl ? pl.name : key;
    await atlasSavePins(atlasPins().filter((x) => x.place !== key), `'${name}'을(를) 지도에서 뺐어요`, { before: atlasPinMap(), label: `'${name}' 빼기` });
  },
  async atlasUndo(d) {
    const back = Number(d) < 0;
    if (atlasGenPreview() || atlasDrag || atlasUndoBusy) return;
    atlasUndoBusy = true;
    try {
      await atlasKeySave();  // 화살표로 옮기던 것을 먼저 기록한다
      const h = atlasHistNow();
      const from = back ? h.back : h.fwd;
      const to = back ? h.fwd : h.back;
      if (!from.length) { toast(back ? '되돌릴 장소 이동이 없어요' : '다시 할 장소 이동이 없어요'); return; }
      const e = from.pop();
      to.push(e);
      const ok = await atlasSavePins(atlasPinApply(atlasPinMap(), back ? e.b : e.a),
        `${e.label}를 ${back ? '되돌렸어요' : '다시 했어요'}${e.gen ? ' (마을 그림은 그대로예요)' : ''}`);
      if (!ok) { to.pop(); from.push(e); atlasUndoPaint(); }
    } finally {
      atlasUndoBusy = false;
    }
  },
  atlasZoom(how) {
    const z = atlasViewNow().z;
    if (how === 'fit') { atlasFollowStop(); S.atlasView = { x: 0, y: 0, z: 1 }; atlasRedraw(); return; }
    atlasZoomAt(how === 'in' ? z * 1.5 : z / 1.5);
  },
  atlasTitleEdit(on) {
    S.atlasTitleEdit = !!on;
    atlasRedraw();
    if (on) setTimeout(() => { const i = document.querySelector('[data-atlas-title-form] input'); if (i) i.focus(); }, 30);
  },
  atlasBldClose() {
    S.atlasBld = null;
    atlasRedraw();
  },
  atlasBldEditOpen(on) {
    if (!S.atlasBld) return;
    S.atlasBld.edit = on !== '';
    atlasRedraw();
  },
  async atlasBldReset() {
    const b = S.atlasBld;
    if (!b) return;
    await run('되돌리는 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/atlas/buildings/${b.i}`, {});
      b.edit = false;
      atlasRefresh();
      toast('건물을 처음 값으로 되돌렸어요');
    });
  },
  atlasUseHi(use) {
    S.atlasUseHi = S.atlasUseHi === use ? '' : use;
    atlasRefresh();
  },
  atlasBldIdea(name) {
    const i = document.querySelector('[data-atlas-bld-form] input');
    if (i) { i.value = name; i.focus(); }
  },
  async atlasBldPut() {
    const b = S.atlasBld;
    const key = document.querySelector('[data-atlas-bld-place]').value;
    const pl = atlasPlace(key);
    if (!b || !pl) return;
    S.atlasBld = null;
    S.atlasSel = key;
    await atlasSavePins([...atlasPins().filter((x) => x.place !== key), { place: key, x: b.at[0], y: b.at[1] }], `'${pl.name}'${josa(pl.name, '을', '를')} 고른 건물에 놓았어요`,
      { before: atlasPinMap(), label: `'${pl.name}' ${pl.pin ? '옮기기' : '놓기'}` });
  },
  async atlasDropLayout() {
    if (!confirm('마을 데이터를 지울까요? 장소 자리는 그대로 남아요.')) return;
    await run('지우는 중', async () => {
      await saveIfDirty();
      S.project = await api('DELETE', `/projects/${enc(S.name)}/atlas/layout`);
      await atlasLoad();
      toast('마을 데이터를 지웠어요');
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
  if (t.matches('[data-atlas-style]')) {
    S.atlasStyle = ATLAS_STYLES[t.value] ? t.value : 'base';
    atlasStyleSave();
    atlasRedraw();
    return;
  }
  if (t.matches('[data-atlas-layer]')) {
    S.atlasLayers[t.dataset.atlasLayer] = t.checked;
    atlasLayersSave();
    atlasRedraw();
    atlasNumHint(t.dataset.atlasLayer);
    return;
  }
  if (t.matches('[data-atlas-opt]')) {
    S[t.dataset.atlasOpt] = t.checked;
    if (S.atlasTab === 'table') render(); else atlasRefresh();
    return;
  }
  if (t.matches('[data-atlas-meters]')) {
    const meters = Number(t.value);
    if (!(meters >= 0.01 && meters <= 1000)) { toast('축척은 1단위에 0.01~1000m 사이로 정하세요', true); return; }
    await run('저장하는 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/atlas/meters`, { meters });
      await atlasLoad();
      toast('축척을 바꿨어요');
    });
    return;
  }
  if (t.matches('[data-atlas-layout]') && t.files && t.files[0]) {
    const file = t.files[0];
    t.value = '';
    if (file.size > 20 * 1024 * 1024) { toast('파일이 너무 커요. 20MB 이하로 올리세요', true); return; }  // atlas.LAYOUT_LIMIT
    await run('마을 올리는 중', async () => {
      const data = await file.text();
      const had = (S.atlas.places || []).some((pl) => pl.pin);
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/atlas/layout`, { data });
      await atlasLoad();
      await atlasFindLoad().catch(() => { S.atlasFind = null; });
      const found = S.atlasFind ? S.atlasFind.spots.length : 0;
      if (found) { toast(`마을을 올렸어요. 이름이 같은 건물 · 가게 · 역을 장소 ${found}곳에서 찾았어요. 옆 칸에서 골라 주세요`); return; }
      S.atlasFind = null;
      toast(had ? '마을을 올렸어요. 장소 자리가 마을과 맞지 않으면 건물 위로 옮겨 주세요' : '마을을 올렸어요. 장소를 골라 건물 위에 놓으세요');
    });
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
let atlasPan = null;
const atlasTouch = new Map();  // 화면에 닿은 손가락 (두 손가락 확대)
let atlasPinch = null;

document.addEventListener('pointerdown', (e) => {
  const onMap = e.target.closest && e.target.closest('.at-map');
  if (onMap && e.pointerType === 'touch') {
    atlasTouch.set(e.pointerId, [e.clientX, e.clientY]);
    if (atlasTouch.size === 2) {
      const [a, b] = [...atlasTouch.values()];
      atlasPinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]) || 1, z: atlasViewNow().z };
      atlasDrag = null;
      atlasPan = null;
      return;
    }
  }
  const g = e.target.closest && e.target.closest('[data-atlas-pin]');
  if (g && e.button === 0) {
    atlasDrag = { key: g.dataset.atlasPin, x: e.clientX, y: e.clientY, moved: false, before: atlasPinMap() };
    return;
  }
  if (onMap && e.button === 0 && atlasViewNow().z > 1) {
    atlasFollowStop();
    const v = S.atlasView;
    atlasPan = { x: e.clientX, y: e.clientY, vx: v.x, vy: v.y, moved: false };
  }
});

document.addEventListener('pointermove', (e) => {
  if (atlasPinch && atlasTouch.has(e.pointerId)) {
    atlasTouch.set(e.pointerId, [e.clientX, e.clientY]);
    const [a, b] = [...atlasTouch.values()];
    const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
    atlasZoomAt(atlasPinch.z * (d / atlasPinch.d), (a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
    return;
  }
  if (!atlasPan) return;
  if (!atlasPan.moved && Math.hypot(e.clientX - atlasPan.x, e.clientY - atlasPan.y) < 4) return;
  atlasPan.moved = true;
  const svg = document.querySelector('.at-map');
  if (!svg) return;
  const box = svg.getBoundingClientRect();
  const v = S.atlasView;
  v.x = atlasPan.vx - ((e.clientX - atlasPan.x) / box.width) * (ATLAS_W / v.z);
  v.y = atlasPan.vy - ((e.clientY - atlasPan.y) / box.height) * (atlasH() / v.z);
  svg.setAttribute('viewBox', atlasViewBox(atlasViewNow()));  // 이동은 범위만 바꾼다 (다시 그리지 않음)
});

const atlasTouchEnd = (e) => {
  atlasTouch.delete(e.pointerId);
  if (atlasTouch.size < 2) atlasPinch = null;
  if (atlasPan) {
    if (atlasPan.moved) {
      atlasDragged = true;
      setTimeout(() => { atlasDragged = false; }, 0);
    }
    atlasPan = null;
  }
};
document.addEventListener('pointerup', atlasTouchEnd);
document.addEventListener('pointercancel', atlasTouchEnd);

// 휠: 확대한 지도에서는 휠로, 처음(전체 보기)에는 Ctrl(트랙패드 오므리기)+휠로 확대한다. 그 밖에는 페이지가 내려간다
document.addEventListener('wheel', (e) => {
  const wrap = e.target.closest && e.target.closest('.at-map-wrap');
  if (!wrap || e.target.closest('.at-bld, .at-pv-bar')) return;
  const z = atlasViewNow().z;
  if (z <= 1 && !e.ctrlKey && !e.metaKey) return;
  e.preventDefault();
  atlasZoomAt(z * Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.002)), e.clientX, e.clientY);
}, { passive: false });

// 마을 이름 · 새 장소 등록 칸
document.addEventListener('submit', async (e) => {
  const form = e.target;
  if (form.matches('[data-atlas-title-form]')) {
    e.preventDefault();
    const title = form.elements.title.value;
    await run('저장하는 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/atlas/title`, { title });
      S.atlasTitleEdit = false;
      await atlasLoad();
      atlasRefresh();
      toast(title.trim() ? '지도 이름을 바꿨어요' : '지도 이름을 비웠어요. 가운데 장소 이름을 써요');
    });
    return;
  }
  if (form.matches('[data-atlas-bld-edit]')) {
    e.preventDefault();
    const b = S.atlasBld;
    if (!b) return;
    const body = { use: form.elements.use.value, name: form.elements.name.value.trim(), note: form.elements.note.value.trim(),
      residents: [...form.querySelectorAll('input[name="who"]:checked')].map((x) => x.value) };
    await run('건물 저장하는 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/atlas/buildings/${b.i}`, body);
      b.edit = false;
      atlasRefresh();
      toast('건물을 저장했어요');
    });
    return;
  }
  if (form.matches('[data-atlas-bld-form]')) {
    e.preventDefault();
    const b = S.atlasBld;
    const name = form.elements.name.value.trim();
    if (!b || !name) return;
    await run('장소 등록하는 중', async () => {
      await saveIfDirty();
      const r = await api('POST', `/projects/${enc(S.name)}/atlas/places`, { name, x: b.at[0], y: b.at[1] });
      S.project = r.project;
      S.atlasBld = null;
      S.atlasIdeas = null;
      S.atlasSel = r.key;
      await atlasLoad();
      atlasRefresh();
      toast(`'${name}'을(를) 장소로 등록하고 이 건물에 놓았어요 (인과율 '장소')`);
    });
  }
});

// 되돌리기: Ctrl/⌘+Z, 다시 하기: Ctrl/⌘+Shift+Z (Windows 는 Ctrl+Y 도). 글을 쓰는 칸에서는 브라우저에 맡긴다
document.addEventListener('keydown', (e) => {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || e.isComposing || !document.getElementById('atlas-stage')) return;
  const k = e.key.toLowerCase();
  const redo = (k === 'z' && e.shiftKey) || (k === 'y' && e.ctrlKey && !e.metaKey && !e.shiftKey);
  if (k !== 'z' && !redo) return;
  const t = e.target;
  const typing = t.closest && (t.closest('textarea, [contenteditable="true"]')
    || (t.matches('input') && !['checkbox', 'radio', 'range', 'button', 'submit', 'file', 'color'].includes(t.type)));
  if (typing) return;
  e.preventDefault();
  actions.atlasUndo(redo ? 1 : -1);
});

// 단축키 (입력 칸 밖에서): 미리보기 Enter 다른 시드 · ← → 이전/다음 · Esc 그만두기, + - 0 확대, 1~4 화풍, T F U M N W 지도 겹
document.addEventListener('keydown', (e) => {
  if (!document.getElementById('atlas-stage') || e.ctrlKey || e.metaKey || e.altKey) return;
  const t = e.target;
  if (t.closest && (t.closest('input, select, textarea, [contenteditable="true"], [data-atlas-pin]') || (t.matches('button') && e.key === 'Enter'))) return;
  const st = S.atlasGen;
  const pv = atlasGenPreview();
  const act = (name, arg) => { e.preventDefault(); actions[name](arg); };
  if (pv && e.key === 'Enter') return act('atlasGenSeed');
  if (pv && e.key === 'ArrowLeft') return act('atlasGenHist', -1);
  if (pv && e.key === 'ArrowRight') return act('atlasGenHist', 1);
  if (e.key === 'Escape') {
    if (S.atlasBld || S.atlasTitleEdit) { S.atlasBld = null; S.atlasTitleEdit = false; e.preventDefault(); atlasRedraw(); return; }
    if (pv && st) return act('atlasGenOpen', '');
    return;
  }
  if (e.key === '+' || e.key === '=') return act('atlasZoom', 'in');
  if (e.key === '-') return act('atlasZoom', 'out');
  if (e.key === '0') return act('atlasZoom', 'fit');
  const style = /^[1-9]$/.test(e.key) && Object.keys(ATLAS_STYLES)[Number(e.key) - 1];
  if (style && atlasVillage()) {
    e.preventDefault();
    S.atlasStyle = style;
    atlasStyleSave();
    const sel = document.querySelector('[data-atlas-style]');
    if (sel) sel.value = style;
    atlasRedraw();
    toast(`화풍: ${ATLAS_STYLES[style].label}`);
    return;
  }
  const layer = Object.keys(ATLAS_LAYERS).find((k) => ATLAS_LAYERS[k][1] === e.key.toLowerCase());
  if (layer && atlasVillage()) {
    e.preventDefault();
    S.atlasLayers[layer] = !S.atlasLayers[layer];
    atlasLayersSave();
    const box = document.querySelector(`[data-atlas-layer="${layer}"]`);
    if (box) box.checked = S.atlasLayers[layer];
    atlasRedraw();
    atlasNumHint(layer);
  }
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
  const pl = atlasPlace(d.key);
  if (pl && pl.pin) pl.pin = atlasSnap(pl.pin);
  await atlasSavePins(atlasPins(), '저장했어요', pl && { before: d.before, label: `'${pl.name}' 옮기기` });
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
  if (e.target.closest('[data-action]')) return;
  if (!S.atlasPick) {  // 건물을 누르면 건물 메뉴 (미리보기 중이 아닐 때)
    const v = atlasVillage();
    const pt = atlasPoint(e);
    const i = v && pt && !atlasGenPreview() ? (v.buildings || []).findIndex((poly) => atlasInside(pt, poly)) : -1;
    const wrap = e.target.closest('.at-map-wrap').getBoundingClientRect();
    // 메뉴는 누른 자리 옆에. 아래쪽 절반을 눌렀으면 위로 펼쳐 지도 밖으로 잘리지 않게
    const cy = e.clientY - wrap.top;
    S.atlasBld = i >= 0 ? { i, at: atlasSnap(pt), sx: Math.max(4, Math.min(e.clientX - wrap.left, wrap.width - 260)), sy: cy, up: cy > wrap.height / 2, h: wrap.height } : null;
    atlasRedraw();
    if (S.atlasBld && !S.atlasIdeas) {
      api('GET', `/projects/${enc(S.name)}/atlas/name-ideas`).then((r) => { S.atlasIdeas = r.names; atlasRedraw(); }).catch(() => { S.atlasIdeas = []; atlasRedraw(); });
    }
    return;
  }
  const pt = atlasPoint(e);
  const pl = atlasPlace(S.atlasPick);
  if (!pt || !pl) return;
  S.atlasPick = '';
  S.atlasSel = pl.key;
  const before = atlasPinMap();
  pl.pin = atlasSnap(pt);
  await atlasSavePins(atlasPins(), `'${pl.name}'을(를) 지도에 놓았어요`, { before, label: `'${pl.name}' 놓기` });
});

// 키보드: 장소에서 Enter 는 자세히 보기, 화살표는 1% (Shift 5%) 옮기기
document.addEventListener('keydown', (e) => {
  if (e.target.closest && e.target.closest('.at-v-title[data-action]') && (e.key === 'Enter' || e.key === ' ')) {
    e.preventDefault();
    actions.atlasTitleEdit(1);
    return;
  }
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
  if (atlasKeyBefore && atlasKeyBefore.key !== pl.key) atlasKeySave();  // 다른 장소로 넘어가면 앞 장소 이동을 따로 기록
  if (!atlasKeyBefore) atlasKeyBefore = { map: atlasPinMap(), key: pl.key };
  pl.pin = [Math.min(1, Math.max(0, pl.pin[0] + mv[0])), Math.min(1, Math.max(0, pl.pin[1] + mv[1]))];
  const stage = document.getElementById('atlas-stage');
  if (stage) stage.innerHTML = atlasStage();
  const again = document.querySelector(`[data-atlas-pin="${CSS.escape(pl.key)}"]`);
  if (again) again.focus();
  clearTimeout(atlasKeyTimer);
  atlasKeyTimer = setTimeout(atlasKeySave, 600);
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
.at-toggles label { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; white-space: nowrap; }
.at-map-wrap { position: relative; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: var(--canvas); }
.at-map-wrap .at-map { touch-action: pan-y; }
.at-map-wrap.zoomed .at-map { touch-action: none; cursor: grab; }
.at-map-wrap.zoomed .at-map:active { cursor: grabbing; }
.at-zoom { position: absolute; top: 8px; right: 8px; display: flex; flex-direction: column; gap: 4px; }
.at-zoom .btn { min-width: 34px; padding: 4px 0; background: var(--surface); }
.at-undo { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; }
.at-title-add { position: absolute; top: 8px; left: 8px; background: color-mix(in srgb, var(--surface) 88%, transparent); }
.at-title-edit { position: absolute; top: 8px; left: 8px; display: flex; gap: 6px; padding: 6px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); }
.at-title-edit input { width: 180px; }
.at-bld { position: absolute; width: 250px; display: flex; flex-direction: column; gap: 8px; padding: 10px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); box-shadow: 0 6px 20px color-mix(in srgb, #000 18%, transparent); z-index: 2; }
.at-bld label { display: flex; flex-direction: column; gap: 4px; }
.at-bld .row { flex-wrap: nowrap; gap: 6px; }
.at-bld select, .at-bld input { flex: 1; min-width: 0; }
.at-pv-bar { position: absolute; left: 8px; right: 8px; bottom: 8px; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 6px 10px; padding: 8px 10px; border: 1px solid var(--line); border-radius: 10px; background: color-mix(in srgb, var(--surface) 94%, transparent); }
.at-pv-bar .row { gap: 6px; flex-wrap: wrap; }
.at-layers { margin-top: 4px; }
.at-export { margin-left: auto; gap: 6px; }
.at-map .at-leader { stroke: var(--muted); }
.at-map .at-name.later { fill: var(--muted); }
.at-map .at-name.old { opacity: .35; }
.at-map .at-v-num text { font-weight: 700; fill: #fff; paint-order: stroke; stroke: color-mix(in srgb, #000 70%, transparent); stroke-width: 2px; pointer-events: none; }
.at-map { display: block; width: 100%; height: auto; user-select: none; font-family: var(--sans); }
.at-map.picking { cursor: crosshair; }
/* 좁은 폭은 줄이지 않고 가로로 굴려 본다 (인물 관계도와 같다). 장소 이름이 읽히는 크기로 남는다 */
/* 좁은 폭에서는 ＋ 버튼 · 두 손가락으로 확대해 본다 */
.at-map .at-ground { fill: var(--canvas); }
.at-map .at-grid { stroke: var(--rule); stroke-width: 1; }
/* 마을 색은 화풍마다 바꿔 끼우는 변수 묶음. 기본은 앱 바탕(--canvas)에 섞어 밝은 · 어두운 화면을 따라가고,
   양피지 · 밤 · 흑백 인쇄는 제 종이색을 쓰며 그 위의 이름표 · 핀(--text, --canvas, --surface, --muted)도 함께 바꾼다 */
.at-map {
  color: var(--text);
  --v-ground: color-mix(in srgb, #8DB06A 26%, var(--canvas));
  --v-field0: color-mix(in srgb, #A0805E 42%, var(--canvas));
  --v-field1: color-mix(in srgb, #D2B865 45%, var(--canvas));
  --v-field2: color-mix(in srgb, #8FB25C 45%, var(--canvas));
  --v-furrow: color-mix(in srgb, #5B4630 30%, transparent);
  --v-field-edge: color-mix(in srgb, #5B4630 35%, var(--canvas));
  --v-green: color-mix(in srgb, #6E9F5A 30%, var(--canvas));
  --v-square: color-mix(in srgb, #C9B48E 40%, var(--canvas));
  --v-square-edge: color-mix(in srgb, #8C7A5A 40%, var(--canvas));
  --v-sand: color-mix(in srgb, #D9C28C 70%, var(--canvas));
  --v-water: color-mix(in srgb, #4A86C5 55%, var(--canvas));
  --v-wave: color-mix(in srgb, #FFFFFF 45%, transparent);
  --v-river-line: color-mix(in srgb, #FFFFFF 22%, transparent);
  --v-road-edge: color-mix(in srgb, #7A6040 55%, var(--canvas));
  --v-road: color-mix(in srgb, #E2CFA4 85%, var(--canvas));
  --v-bridge: color-mix(in srgb, #8A6436 85%, var(--canvas));
  --v-planks: color-mix(in srgb, #4A3418 70%, transparent);
  --v-wall: color-mix(in srgb, var(--text) 45%, var(--canvas));
  --v-shadow: color-mix(in srgb, #000000 26%, transparent);
  --v-house-edge: color-mix(in srgb, #2B1D12 70%, var(--canvas));
  --v-house0: color-mix(in srgb, #B5653A 80%, var(--canvas));
  --v-house1: color-mix(in srgb, #9A7448 80%, var(--canvas));
  --v-house2: color-mix(in srgb, #6F7C8A 80%, var(--canvas));
  --v-house3: color-mix(in srgb, #A88A52 80%, var(--canvas));
  --v-roof-dark: color-mix(in srgb, #000000 22%, transparent);
  --v-ridge: color-mix(in srgb, #2B1D12 60%, transparent);
  --v-tree-shadow: color-mix(in srgb, #000000 18%, transparent);
  --v-tree: color-mix(in srgb, #3F6B35 80%, var(--canvas));
  --v-tree-edge: color-mix(in srgb, #20381A 70%, var(--canvas));
  --v-tree-hi: color-mix(in srgb, #8DBA62 45%, transparent);
  --v-lamp: #FFD66E;
  --v-glow: rgba(255, 196, 77, 0.28);
  --v-lw: 1;
  /* 지도 장식(제목 틀 · 축척 막대 · 북쪽 화살표) 색. 화풍마다 바뀌는 바탕 · 글자 변수에서 만든다 */
  --v-frame: color-mix(in srgb, var(--surface) 88%, transparent);
  --v-frame-edge: color-mix(in srgb, var(--text) 35%, transparent);
  --v-frame-ink: var(--text);
  --v-frame-muted: var(--muted);
}
.at-map.st-parchment {
  --canvas: #EFE3C4; --surface: #F7EEDA; --text: #3B2814; --muted: #7D6A4E;
  --v-ground: #E9DAB2; --v-field0: #D9C38F; --v-field1: #E4D29E; --v-field2: #CEC48E;
  --v-furrow: rgba(107, 78, 42, 0.32); --v-field-edge: #8A6B42; --v-green: #D8D0A0;
  --v-square: #DDCBA2; --v-square-edge: #8A6B42; --v-sand: #E4CF9A;
  --v-water: #A9B6A2; --v-wave: rgba(247, 238, 214, 0.6); --v-river-line: rgba(247, 238, 214, 0.4);
  --v-road-edge: #7A5A34; --v-road: #F4E8C8; --v-bridge: #9A774A; --v-planks: rgba(74, 51, 24, 0.6); --v-wall: #4A3420;
  --v-shadow: rgba(90, 62, 30, 0.22); --v-house-edge: #4A3018;
  --v-house0: #C49A68; --v-house1: #B58C5C; --v-house2: #A99474; --v-house3: #CFB080;
  --v-roof-dark: rgba(74, 48, 24, 0.2); --v-ridge: rgba(59, 40, 20, 0.7);
  --v-tree-shadow: rgba(90, 62, 30, 0.2); --v-tree: #9C925A; --v-tree-edge: #4A3A1C; --v-tree-hi: rgba(240, 230, 186, 0.45);
}
.at-map.st-night {
  --canvas: #121926; --surface: #1C2433; --text: #F2EAD3; --muted: #A8B0BE;
  --v-ground: #1B2531; --v-field0: #2A3038; --v-field1: #30343A; --v-field2: #263330;
  --v-furrow: rgba(0, 0, 0, 0.35); --v-field-edge: #0B1018; --v-green: #1E2D2A;
  --v-square: #2A2E36; --v-square-edge: #0E131B; --v-sand: #2E3340;
  --v-water: #0D192C; --v-wave: rgba(140, 170, 220, 0.18); --v-river-line: rgba(140, 170, 220, 0.14);
  --v-road-edge: #0A0E15; --v-road: #3A404B; --v-bridge: #4D4032; --v-planks: rgba(0, 0, 0, 0.5); --v-wall: #66707F;
  --v-shadow: rgba(0, 0, 0, 0.45); --v-house-edge: #05070B;
  --v-house0: #3D3542; --v-house1: #383A41; --v-house2: #313B47; --v-house3: #433C36;
  --v-roof-dark: rgba(0, 0, 0, 0.28); --v-ridge: rgba(0, 0, 0, 0.55);
  --v-tree-shadow: rgba(0, 0, 0, 0.4); --v-tree: #1F3326; --v-tree-edge: #0A140E; --v-tree-hi: rgba(110, 160, 120, 0.2);
}
.at-map.st-print {
  --canvas: #FFFFFF; --surface: #FFFFFF; --text: #000000; --muted: #555555;
  --v-ground: #FFFFFF; --v-field0: #ECECEC; --v-field1: #E0E0E0; --v-field2: #F4F4F4;
  --v-furrow: rgba(0, 0, 0, 0.35); --v-field-edge: #000000; --v-green: #EFEFEF;
  --v-square: #DCDCDC; --v-square-edge: #000000; --v-sand: #E4E4E4;
  --v-water: #C4C4C4; --v-wave: rgba(255, 255, 255, 0.7); --v-river-line: rgba(255, 255, 255, 0.55);
  --v-road-edge: #000000; --v-road: #FFFFFF; --v-bridge: #FFFFFF; --v-planks: rgba(0, 0, 0, 0.7); --v-wall: #000000;
  --v-shadow: rgba(0, 0, 0, 0.16); --v-house-edge: #000000;
  --v-house0: #9E9E9E; --v-house1: #8C8C8C; --v-house2: #B0B0B0; --v-house3: #C2C2C2;
  --v-roof-dark: rgba(0, 0, 0, 0.2); --v-ridge: #000000;
  --v-tree-shadow: rgba(0, 0, 0, 0.14); --v-tree: #D2D2D2; --v-tree-edge: #000000; --v-tree-hi: rgba(255, 255, 255, 0.6);
  --v-lw: 1.8;
  --v-frame: #FFFFFF; --v-frame-edge: #000000;
}
.at-map .at-v-ground { fill: var(--v-ground); }
.at-map .at-v-field.t0 { fill: var(--v-field0); }
.at-map .at-v-field.t1 { fill: var(--v-field1); }
.at-map .at-v-field.t2 { fill: var(--v-field2); }
.at-map .at-v-furrow { stroke: var(--v-furrow); stroke-width: 1; }
.at-map .at-v-field-edge { stroke: var(--v-field-edge); stroke-width: calc(var(--v-lw) * 1px); }
.at-map .at-v-green { fill: var(--v-green); }
.at-map .at-v-square { fill: var(--v-square); stroke: var(--v-square-edge); stroke-width: calc(var(--v-lw) * 1px); }
.at-map .at-v-sand { fill: none; stroke: var(--v-sand); stroke-linejoin: round; stroke-linecap: round; }
.at-map .at-v-water { fill: var(--v-water); }
.at-map .at-v-wave { fill: none; stroke: var(--v-wave); stroke-linejoin: round; stroke-linecap: round; }
.at-map .at-v-water-line { fill: none; stroke: var(--v-water); stroke-linejoin: round; stroke-linecap: round; }
.at-map .at-v-river { fill: none; stroke: var(--v-water); stroke-linecap: round; stroke-linejoin: round; }
.at-map .at-v-river-line { fill: none; stroke: var(--v-river-line); stroke-linecap: round; stroke-linejoin: round; }
.at-map .at-v-road-edge { fill: none; stroke: var(--v-road-edge); stroke-linecap: round; stroke-linejoin: round; }
.at-map .at-v-road { fill: none; stroke: var(--v-road); stroke-linecap: round; stroke-linejoin: round; }
.at-map .at-v-bridge { fill: none; stroke: var(--v-bridge); stroke-linecap: butt; }
.at-map .at-v-planks { fill: none; stroke: var(--v-planks); stroke-linecap: butt; stroke-dasharray: 1 3; }
.at-map .at-v-wall { fill: none; stroke: var(--v-wall); stroke-linejoin: round; }
.at-map .at-v-wall-edge { fill: none; stroke: var(--v-house-edge); stroke-linejoin: round; }
.at-map .at-v-gate { fill: none; stroke: var(--v-road); stroke-linecap: butt; stroke-linejoin: miter; }
.at-map .at-v-tower { fill: var(--v-wall); stroke: var(--v-house-edge); }
.at-map .at-v-ward { fill: none; stroke: var(--v-wall); stroke-opacity: 0.35; stroke-dasharray: 4 3; fill-opacity: 0.3; }
.at-map .at-v-ward.k-plaza, .at-map .at-v-ward.k-market { fill: var(--v-square); fill-opacity: 0.7; }
.at-map .at-v-ward.k-temple { fill: var(--v-house2); }
.at-map .at-v-ward.k-noble, .at-map .at-v-ward.k-park { fill: var(--v-green); fill-opacity: 0.6; }
.at-map .at-v-ward.k-harbor { fill: var(--v-sand); }
.at-map .at-v-ward.k-craft { fill: var(--v-field1); }
.at-map .at-v-ward.k-slum { fill: var(--v-field0); }
.at-map .at-v-ward.k-apartment { fill: var(--v-green); fill-opacity: 0.35; }
.at-map .at-v-ward.k-station, .at-map .at-v-ward.k-school { fill: var(--v-square); fill-opacity: 0.45; }
.at-map .at-v-use { fill-opacity: 0.55; stroke: none; }
.at-map .at-v-use.g-shop { fill: #E0A030; }
.at-map .at-v-use.g-food { fill: #D2691E; }
.at-map .at-v-use.g-craft { fill: #8B5A2B; }
.at-map .at-v-use.g-lodging { fill: #C0392B; }
.at-map .at-v-use.g-faith { fill: #8E44AD; }
.at-map .at-v-use.g-civic { fill: #2E86C1; }
.at-map .at-v-use.g-care { fill: #16A085; }
.at-map .at-v-use.g-noble { fill: #B7950B; }
.at-map .at-v-use.g-work { fill: #5D6D7E; }
.at-map .at-v-source { fill: var(--muted, #555); stroke: var(--canvas, #fff); paint-order: stroke; font-family: inherit; pointer-events: none; }
.at-map .at-v-frame { fill: var(--v-frame); stroke: var(--v-frame-edge); }
.at-map .at-v-deco { pointer-events: none; }
.at-map .at-v-deco .at-v-source { stroke: none; }
.at-map .at-v-title { pointer-events: none; }
.at-map .at-v-title.live { pointer-events: auto; cursor: pointer; }
.at-map .at-v-title.live:focus-visible .at-v-frame { stroke: var(--accent); }
.at-map .at-v-title-name { fill: var(--v-frame-ink); font-weight: 700; font-family: inherit; }
.at-map .at-v-title-pop { fill: var(--v-frame-muted); font-family: inherit; }
.at-map .at-v-scale-a, .at-map .at-v-north-a { fill: var(--v-frame-ink); }
.at-map .at-v-scale-b, .at-map .at-v-north-b { fill: var(--v-frame); stroke: var(--v-frame-ink); }
.at-map .at-v-north-a { stroke: var(--v-frame-ink); }
.at-map .at-v-scale-text, .at-map .at-v-north-n { fill: var(--v-frame-ink); font-family: inherit; font-weight: 600; }
.at-map .at-v-use.g-store { fill: #7F8C8D; fill-opacity: 0.35; }
.at-map .at-v-hi { fill: none; stroke: var(--accent); stroke-linejoin: round; }
.at-map .at-v-street-label { fill: var(--text); fill-opacity: 0.7; stroke: var(--canvas); stroke-opacity: 0.85; paint-order: stroke; stroke-linejoin: round; font-style: italic; pointer-events: none; }
.at-bld-facts { color: var(--muted); }
.at-bld-edit { display: flex; flex-direction: column; gap: 6px; }
.at-bld-edit label { display: flex; flex-direction: column; gap: 2px; }
.at-bld-who { display: flex; flex-wrap: wrap; gap: 4px 10px; border: 1px solid var(--line); border-radius: 6px; padding: 4px 8px; max-height: 120px; overflow: auto; }
.at-map .at-v-ward-label { fill: var(--text); fill-opacity: 0.8; stroke: var(--canvas); stroke-opacity: 0.85; paint-order: stroke; stroke-linejoin: round; font-weight: 600; pointer-events: none; }
.at-map .at-v-shadow { fill: var(--v-shadow); }
.at-map .at-v-made { fill: var(--v-house0); fill-opacity: 0.45; stroke: var(--v-house-edge); stroke-linejoin: round; }
.at-map .at-v-house { stroke: var(--v-house-edge); stroke-width: calc(var(--v-lw) * 1px); stroke-linejoin: round; }
.at-map .at-v-house.t0 { fill: var(--v-house0); }
.at-map .at-v-house.t1 { fill: var(--v-house1); }
.at-map .at-v-house.t2 { fill: var(--v-house2); }
.at-map .at-v-house.t3 { fill: var(--v-house3); }
.at-map .at-v-roof-dark { fill: var(--v-roof-dark); }
.at-map .at-v-ridge { fill: none; stroke: var(--v-ridge); stroke-width: calc(var(--v-lw) * 1px); }
.at-map .at-v-glow { fill: var(--v-glow); pointer-events: none; }
.at-map .at-v-lamp { fill: var(--v-lamp); pointer-events: none; }
.at-map .at-v-tree-shadow { fill: var(--v-tree-shadow); }
.at-map .at-v-tree { fill: var(--v-tree); stroke: var(--v-tree-edge); stroke-width: calc(var(--v-lw) * 0.8px); }
.at-map .at-v-tree-hi { fill: var(--v-tree-hi); }
.at-map .at-pin.old { opacity: .35; }
.at-map .at-sug circle { fill: var(--accent); stroke: var(--surface); }
.at-gen-opts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.at-gen-opt { display: flex; flex-direction: column; gap: 4px; }
.at-gen-opt select, .at-gen-opt input { width: 100%; min-width: 0; }
.at-gen-opt .row { flex-wrap: nowrap; gap: 6px; }
.at-gen-opt .row input { flex: 1; }
.at-gen-opt .row .btn { flex: none; white-space: nowrap; }
.at-gen-places { display: flex; flex-direction: column; gap: 6px; max-height: 40vh; overflow-y: auto; }
.at-gen-place { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 8px; }
.at-gen-place select { max-width: 140px; }
.at-gen-take { display: flex; align-items: baseline; gap: 6px; }
.at-find { border: 0; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.at-find legend { padding: 0; margin-bottom: 2px; }
.at-gen-note { grid-column: 1 / -1; margin-top: -2px; }
.at-scale { display: inline-flex; align-items: center; gap: 6px; }
.at-scale input { width: 80px; }
.at-walk { display: block; padding-left: 16px; }
.at-tv-list li { display: flex; flex-direction: column; align-items: flex-start; gap: 3px; padding-bottom: 6px; border-bottom: 1px solid var(--line); }
.at-tv-list li:last-child { border-bottom: none; padding-bottom: 0; }
.at-tv-list li.at-tv-ok { opacity: .6; }
.at-tv { display: inline-block; font-size: 0.75rem; font-weight: 700; padding: 1px 6px; border-radius: 4px; }
.at-tv.fast { background: var(--red-soft); color: var(--err-ink); }
.at-tv.tight { background: var(--amber-soft); color: var(--amber-ink); }
.at-map .at-trail { fill: none; stroke-linecap: round; stroke-linejoin: round; opacity: .6; }
.at-map .dim { opacity: .18; }
.at-map .at-pin { cursor: grab; touch-action: none; }
.at-map .at-pin:focus { outline: none; }
.at-map .at-pin:focus-visible .at-dot { stroke: var(--accent); stroke-width: 4; }
.at-map .at-hit { fill: transparent; }
.at-map .at-dot { fill: var(--text); stroke: var(--surface); }
.at-map .at-pin.sel .at-dot { fill: var(--accent); }
.at-map .at-pin.later .at-dot { fill: var(--surface); stroke: var(--muted); stroke-dasharray: 3 2; }
.at-map .at-pin.later .at-name { fill: var(--muted); }
.at-map .at-hot { fill: none; stroke: var(--accent); }
.at-map .at-name { font-weight: 700; fill: var(--text); paint-order: stroke; stroke: var(--canvas); stroke-linejoin: round; pointer-events: none; }
.at-map .at-tok { cursor: pointer; }
.at-map .at-tok circle { stroke: var(--surface); }
.at-map .at-tok text { font-weight: 700; fill: #fff; pointer-events: none; }
.at-um-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px; padding: 10px 0; border-bottom: 1px solid var(--line); font-size: 0.8125rem; }
.at-um-bar label { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }
.at-um-bar .row { flex-wrap: nowrap; gap: 6px; white-space: nowrap; }
.at-um-bar .btn { flex: none; white-space: nowrap; }
.at-um-bar select { min-width: 0; }
.at-um-bar #at-um-apply { margin-left: auto; }
.at-um-bar select, .at-um select { max-width: 200px; }
.at-um-list { max-height: 60vh; overflow-y: auto; }
.at-um { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 10px; padding: 10px 4px; border-bottom: 1px solid var(--line); }
.at-um.on { background: var(--accent-soft); }
.at-um-note { color: var(--muted); }
@media (max-width: 600px) { .at-um { grid-template-columns: auto minmax(0, 1fr); } .at-um select { grid-column: 2; max-width: 100%; } .at-um-bar #at-um-apply { margin-left: 0; } }
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

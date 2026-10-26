/* 지도. app.js 의 S, actions, api, run, render, header, esc, P 와 cast.js 의 frameLabel 을 쓴다.
   장소(설정의 장소 칸, 인과율 '장소' 요소)를 지도 위에 놓고, 화별 인물 자리를 관계도처럼 슬라이더로 재생한다.
   계산값은 서버 canon/atlas.py 의 /atlas 한 번으로 받는다 (places, frames: 화별 인물 자리, unmatched: 장소와 맞지 않은 위치 글).
   장소 자리는 0~1 비율 좌표로 작품에 저장한다 (Project.atlas.pins). 배경 그림은 작품 폴더 map/ 에 파일로 둔다.
   마을 데이터(Watabou 생성기 JSON, /atlas/layout)가 있으면 그림 대신 마을을 그리고, 옮겨 간 인물은 서버가 길 따라 찾은 경로(row.route)로 잇는다. */
'use strict';

/** 마을 겹 설정은 이 브라우저에만 기억한다 (못 읽으면 기본값) */
function atlasLayersLoad() {
  const base = { trees: true, fields: true, shadows: true, numbers: false, title: true };
  try { return { ...base, ...JSON.parse(localStorage.getItem('canon.atlasLayers') || '{}') }; } catch { return base; }
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
  atlasLayers: atlasLayersLoad(),    // 마을 겹 끄고 켜기 { trees, fields, shadows, numbers, title }
  atlasStyle: atlasStyleLoad(),      // 마을 화풍 (ATLAS_STYLES 키)
  atlasBld: null,    // 누른 건물 { i, at: [0~1 가운데], sx, sy: 지도 칸 안 화면 자리 } (건물 메뉴)
  atlasTitleEdit: false,
  atlasIdeas: null,  // 새 장소 이름 후보 (서버 naming)
  atlasGen: null,    // 지도 만들기 { name, open, spec, preview, take: {장소 키: 새 자리에 놓기}, touched: 작가가 고친 칸, ai: AI 제안 { reason, notes } } (atlasGenState())
});

const ATLAS_W = 1000;
const ATLAS_LAYERS = { trees: ['나무', 't'], fields: ['밭', 'f'], shadows: ['그림자', 'u'], numbers: ['집 번호', 'm'], title: ['마을 이름', 'n'] };
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
  if (!same) { S.atlasPick = ''; S.atlasSel = ''; S.atlasFocus = ''; S.atlasDraft = {}; S.atlasNew = []; S.atlasView = { x: 0, y: 0, z: 1 }; S.atlasBld = null; S.atlasIdeas = null; S.atlasTitleEdit = false; }
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

/** 번호 i 로 고르는 0~1 값. 같은 마을이면 건물 · 나무 · 밭이 늘 같은 모양 · 색으로 그려진다 */
const atlasHash = (i, salt = 0) => ((Math.imul(i + 1, 2654435761) ^ Math.imul(salt + 7, 40503)) >>> 0) / 4294967296;

/** 마을 바탕: 풀밭 땅, 밭(이랑 무늬) · 풀밭 · 광장, 모래톱과 물결이 있는 물, 강, 테두리 있는 길, 널다리, 성벽,
    두 색 지붕과 그림자가 있는 건물, 그림자 · 수관 · 밝은 점으로 된 나무. 1단위 = 1m 기준 크기 (k: 화면 단위 / m)
    layers: 겹 끄고 켜기와 화풍 그림 옵션 (lamps: 불 켜진 창, lw: 길 테두리 · 성벽 굵기 배율) */
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
  stroke(v.walls, 'at-v-wall', () => 2 * lw, 2);

  // 건물: 그림자 → 지붕 → 어두운 반쪽 → 마루선. 꼭짓점이 넷이 아니면 한 색 지붕
  const shade = (dx, dy) => (v.buildings || []).map((ln) => `M${ln.map((q) => `${(q[0] * W + dx).toFixed(1)},${(q[1] * H + dy).toFixed(1)}`).join('L')}Z`).join('');
  if (on('shadows')) out.push(`<path class="at-v-shadow" d="${shade(1.4 * k, 1.8 * k)}"></path>`);
  const roofs = [[], [], [], []];
  const dark = [];
  const ridges = [];
  (v.buildings || []).forEach((ln, i) => {
    const ring = ln.length > 4 && ln[0][0] === ln[ln.length - 1][0] && ln[0][1] === ln[ln.length - 1][1] ? ln.slice(0, -1) : ln;
    const q = ring.map(P);
    roofs[Math.floor(atlasHash(i, 1) * 4)].push(`M${q.map((p) => p.map((x) => x.toFixed(1)).join(',')).join('L')}Z`);
    if (q.length !== 4) return;
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
  // 집 번호: 만든 마을은 필지마다 본채(numbers), 올린 파일은 건물마다
  if (layers.numbers) {
    const idx = v.numbers || (v.buildings || []).map((_, i) => i);
    out.push(`<g class="at-v-num" font-size="${m(3.4, 7)}">${idx.map((bi, n) => {
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

// ----- 지도 그림 -----

function atlasSvg() {
  const W = ATLAS_W;
  const H = atlasH();
  const f = atlasFrameNow();
  const out = [];
  const village = atlasVillage();
  const style = ATLAS_STYLES[S.atlasStyle] || ATLAS_STYLES.base;
  if (village) out.push(atlasVillageSvg(village, W, H, { ...S.atlasLayers, lamps: !!style.lamps, lw: style.lw || 1 }));
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

  // 지도 만들기 미리보기: 생성기가 고른 자리 (놓기로 고른 것만)
  if (pv) {
    pv.pins.filter((s) => S.atlasGen.take[s.place]).forEach((s) => {
      const x = s.x * W;
      const y = s.y * H;
      out.push(`<g class="at-sug"><title>${esc(s.name)}: 새 자리</title><circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(9 * sc).toFixed(2)}" stroke-width="${(2.5 * sc).toFixed(2)}"></circle></g>`);
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
  (S.atlas.places || []).filter((pl) => pl.pin && !hidden(pl) && !(pv && S.atlasGen.take[pl.key])).forEach((pl) => {
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
  out.push(atlasLabels(labels, sc, atlasLabelFs(z)));

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
      const rr = (list.length > 1 ? 18 + list.length * 2 : 0) * sc;
      const x = px + 16 * sc + Math.cos(a) * rr;
      const y = py + 16 * sc + Math.sin(a) * rr;
      const dim = S.atlasFocus && S.atlasFocus !== c.id;
      out.push(`<g class="at-tok${dim ? ' dim' : ''}" data-action="atlasFocus" data-arg="${esc(c.id)}"><title>${esc((c.name || c.id) + ': ' + atlasRow(f, c.id).location)}</title>
        <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(12 * sc).toFixed(2)}" stroke-width="${(2.5 * sc).toFixed(2)}" fill="${atlasColor(c.id)}"></circle>
        <text x="${x.toFixed(1)}" y="${(y + 4.5 * sc).toFixed(1)}" font-size="${(12 * sc).toFixed(2)}" text-anchor="middle">${esc([...(c.name || c.id)][0])}</text></g>`);
    });
  });
  // 화풍은 마을 그림에만 (배경 그림 · 모눈 지도는 앱 색 그대로)
  return `<svg class="at-map${village ? ` st-${S.atlasStyle}` : ''}${S.atlasPick ? ' picking' : ''}" viewBox="${atlasViewBox(view)}" role="group" aria-label="${esc(frameLabel(f))} 지도">${out.join('')}</svg>`;
}

// ----- 되돌리기 · 따라가기 계산 (화면을 모른다) -----

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
    지시선을 긋는다. 끝내 못 찾으면 마지막 자리에 겹쳐 둔다. sc: 핀 크기 배율(1/확대), fs: 글자 크기(지도 단위) */
function atlasLabels(list, sc, fs = 15 * sc) {
  const g = 14 * sc;
  const dots = list.map((l) => [l.x - 7 * sc, l.y - 7 * sc, l.x + 7 * sc, l.y + 7 * sc]);
  const placed = [];
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
  const input = '<input id="at-layout" type="file" accept=".json,application/json,application/geo+json" data-atlas-layout hidden>';
  if (!lo) {
    return `<div class="at-box"><h3>마을 데이터</h3>
      <div class="small">Watabou 마을 · 도시 생성기에서 Menu → Export as → JSON으로 받은 파일을 올리면 건물 · 길 · 물을 그려요. 장소를 건물에 놓으면 인물이 옮겨 간 길을 실제 길을 따라 그리고 거리와 걷는 시간을 보여 줘요.</div>
      <div class="row"><label class="btn small" for="at-layout">마을 데이터 올리기</label>${input}</div></div>`;
  }
  const missing = !S.atlasLayout ? '<div class="note err" role="alert">마을 데이터 파일을 읽지 못했어요. 다시 올려 주세요.</div>' : '';
  return `<div class="at-box"><h3>마을 데이터</h3>${missing}
    <div class="small">길 ${lo.roads}개${lo.bridges ? ` · 다리 ${lo.bridges}개` : ''} · 건물 ${lo.buildings}채 · 약 ${atlasMeters(lo.width_m)} × ${atlasMeters(lo.height_m)}</div>
    <label class="at-scale small">1단위 = <input type="number" min="0.01" max="1000" step="0.1" value="${lo.meters}" data-atlas-meters aria-label="마을 데이터 1단위가 몇 m인지"> m</label>
    <div class="small">거리가 어색하면 축척을 바꾸세요. 걷는 시간은 초속 1.3m로 셈해요. 건물 안을 누르면 장소가 그 건물 가운데에 놓여요.</div>
    <div class="row"><label class="btn small" for="at-layout">다른 파일 올리기</label>${input}
      <button type="button" class="btn small ghost" data-action="atlasDropLayout">마을 지우기</button></div></div>`;
}

// ----- 지도 만들기 (서버 canon/towngen.py 마을 생성기) -----

/** 지도 만들기 상태. 작품이 바뀌면 서버가 준 입력(gen.spec, 장소 표)으로 새로 시작한다 */
function atlasGenState() {
  const g = S.atlas.gen;
  const rows = () => g.places.map((x) => ({ key: x.key, kind: x.kind, put: x.put }));
  if (!S.atlasGen || S.atlasGen.name !== S.name) {
    const spec = { ...g.spec, places: rows() };
    if (!g.made) spec.seed = atlasNewSeed();
    S.atlasGen = { name: S.name, open: false, spec, preview: null, take: {}, touched: {}, ai: null, hist: [], at: -1 };
  } else if (S.atlasGen.spec.places.map((x) => x.key).join('\n') !== g.places.map((x) => x.key).join('\n')) {
    S.atlasGen.spec.places = rows();  // 장소가 더해지거나 빠졌으면 표를 새로 (설정 · 시드는 그대로)
    S.atlasGen.preview = null;
  }
  return S.atlasGen;
}

const atlasNewSeed = () => 1 + Math.floor(Math.random() * 2147483646);
const atlasGenLabel = (key, id) => String((S.atlas.gen.options[key] || {})[id] || id);
const atlasKindLabel = (id) => ((S.atlas.gen.kinds || []).find((k) => k.id === id) || { label: id }).label;

function atlasGenForm(st) {
  const sel = (key, label) => `<label class="at-gen-opt small">${label}
    <select data-at-gen="${key}">${Object.keys(S.atlas.gen.options[key]).map((id) => `<option value="${esc(id)}"${st.spec[key] === id ? ' selected' : ''}>${esc(atlasGenLabel(key, id))}</option>`).join('')}</select></label>`;
  const notes = (st.ai && st.ai.notes) || {};
  const rows = S.atlas.gen.places.map((pl, i) => {
    const mine = st.spec.places[i];
    return `<div class="at-gen-place"><label class="small"><input type="checkbox" data-at-gen-put="${i}"${mine.put ? ' checked' : ''}> ${esc(pl.name)}</label>
      <select data-at-gen-kind="${i}" aria-label="${esc(pl.name)} 종류">${S.atlas.gen.kinds.map((k) => `<option value="${esc(k.id)}"${mine.kind === k.id ? ' selected' : ''}>${esc(k.label)}</option>`).join('')}</select>
      ${notes[pl.key] ? `<div class="small at-um-note at-gen-note">${esc(notes[pl.key])}</div>` : ''}</div>`;
  }).join('');
  const why = st.ai && st.ai.reason
    ? `<div class="note" role="status">AI 제안: ${esc(st.ai.reason)}</div>`
    : !S.atlas.gen.made && S.atlas.gen.spec.water !== 'none' && !st.touched.water
      ? `<div class="small">물가가 필요한 장소가 있어 물을 '${esc(atlasGenLabel('water', S.atlas.gen.spec.water))}'(으)로 골라 뒀어요.</div>` : '';
  return `<div class="at-gen-opts">${sel('size', '크기')}${sel('roads', '길 모양')}${sel('water', '물')}${sel('fields', '밭')}${sel('forest', '숲')}
      <label class="at-gen-opt small">시드 <span class="row"><input type="number" min="0" max="2147483647" step="1" value="${st.spec.seed}" data-at-gen-seed aria-label="시드">
        <button type="button" class="btn small ghost" data-action="atlasGenSeed">새 시드</button></span></label></div>
    ${why}
    <div class="small">같은 시드와 설정이면 언제나 같은 마을이 나와요. 장소 종류는 이름에서 찾았어요. 틀리면 고르거나 AI 제안을 받아 보세요.</div>
    <div class="at-gen-places">${rows}</div>
    <div class="row"><button type="button" class="btn small primary" data-action="atlasGenPreview">미리보기</button>
      <button type="button" class="btn small" data-action="atlasGenSuggest">AI로 설정 제안</button>
      <button type="button" class="btn small ghost" data-action="atlasGenOpen" data-arg="">닫기</button></div>`;
}

function atlasGenResult(st) {
  const pv = st.preview;
  const i = pv.info;
  const pins = pv.pins.map((s) => `<label class="small at-gen-take"><input type="checkbox" data-at-gen-take="${esc(s.place)}"${st.take[s.place] ? ' checked' : ''}>
      ${esc(s.name)} → ${esc(atlasKindLabel(s.kind))} 자리${s.had ? ' <span class="at-um-note">(지금 자리에서 옮겨요)</span>' : ''}</label>`).join('');
  const miss = pv.missing.map((m) => `<li>${esc(m.name)}: ${esc(m.reason)}</li>`).join('');
  const blocked = pv.blocked.map((b) => esc(b.name)).join(', ');
  return `<div class="small">시드 ${st.spec.seed} · 집 ${i.houses}채 · 길 ${i.roads}개${i.bridges ? ` · 다리 ${i.bridges}개` : ''} · 약 ${atlasMeters(i.width_m)} × ${atlasMeters(i.height_m)}</div>
    ${pins ? `<div class="at-gen-places">${pins}</div>` : '<div class="small">새로 놓을 장소가 없어요.</div>'}
    ${miss ? `<div class="note" role="status">놓지 못한 장소<ul class="at-list">${miss}</ul></div>` : ''}
    ${blocked ? `<div class="note" role="status">${blocked}: 지금 자리가 새 마을의 건물이나 물 위예요. 적용한 뒤 옮겨 주세요.</div>` : ''}
    <div class="small">적용하면 지금 마을 데이터를 바꿔요. 고른 장소만 새 자리로 옮기고, 나머지 장소 자리는 그대로 둬요.</div>
    <div class="row"><button type="button" class="btn small primary" data-action="atlasGenApply">적용</button>
      <button type="button" class="btn small" data-action="atlasGenSeed">다른 시드로</button>
      <button type="button" class="btn small ghost" data-action="atlasGenEdit">설정 고치기</button>
      <button type="button" class="btn small ghost" data-action="atlasGenOpen" data-arg="">그만두기</button></div>`;
}

function atlasGenBox() {
  if (!S.atlas.gen) return '';
  const st = atlasGenState();
  const made = S.atlas.gen.made && S.atlas.layout;
  if (!st.open) {
    return `<div class="at-box"><h3>지도 만들기</h3>
      <div class="small">${made ? `시드 ${S.atlas.gen.spec.seed}로 만든 마을이에요. 설정을 바꿔 다시 만들 수 있어요.` : '마을 생성기로 길 · 집 · 밭 · 물이 있는 마을을 만들어요. 이야기 장소는 종류에 맞는 자리(신전, 주막, 나루 등)에 놓아요.'}</div>
      <div class="row"><button type="button" class="btn small" data-action="atlasGenOpen" data-arg="1">${made ? '다시 만들기' : '마을 만들기'}</button></div></div>`;
  }
  return `<div class="at-box at-gen"><h3>${st.preview ? '마을 미리보기' : '마을 만들기'}</h3>${st.preview ? atlasGenResult(st) : atlasGenForm(st)}</div>`;
}

async function atlasGenRun() {
  const st = atlasGenState();
  await run('마을 만드는 중', async () => {
    const pv = await api('POST', `/projects/${enc(S.name)}/atlas/generate/preview`, st.spec);
    // 미리보기 이력: 지금 자리 뒤는 버리고 새로 붙인다 (최근 20개). ← → 로 다시 부르지 않고 오간다
    st.hist = [...st.hist.slice(0, st.at + 1), { spec: JSON.parse(JSON.stringify(st.spec)), pv }].slice(-20);
    st.at = st.hist.length - 1;
    atlasGenShow(pv);
  });
}

function atlasGenShow(pv) {
  const st = S.atlasGen;
  st.preview = pv;
  st.take = Object.fromEntries(pv.pins.map((s) => [s.place, !s.had]));  // 이미 놓은 장소는 그대로 두는 게 기본
  S.atlasBld = null;
  atlasRefresh();
}

function atlasBackground() {
  if (S.atlas.layout) {
    return S.atlas.image ? '<div class="at-box"><h3>배경 그림</h3><div class="small">마을 데이터가 있는 동안은 배경 그림 대신 마을을 그려요. 마을을 지우면 그림이 다시 보여요.</div></div>' : '';
  }
  return `<div class="at-box"><h3>배경 그림</h3>
    <div class="small">직접 그리거나 다른 도구(Azgaar, Inkarnate 등)로 만든 지도 그림을 올리면 그 위에 장소를 놓아요. PNG · JPG · WEBP, 15MB까지.</div>
    <div class="row"><label class="btn small" for="at-image">${S.atlas.image ? '그림 바꾸기' : '그림 올리기'}</label><input id="at-image" type="file" accept="image/png,image/jpeg,image/webp,image/gif" data-atlas-image hidden>
      ${S.atlas.image ? '<button type="button" class="btn small ghost" data-action="atlasDropImage">그림 지우기</button>' : ''}</div></div>`;
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
    ${minors ? `<label><input type="checkbox" data-atlas-opt="atlasMinor"${S.atlasMinor ? ' checked' : ''}>단역도 보기</label>` : ''}</div>
    ${map && atlasVillage() ? atlasLayerToggles() : ''}`;
}

function atlasLayerToggles() {
  const styles = Object.entries(ATLAS_STYLES).map(([k, st], i) => `<option value="${k}"${S.atlasStyle === k ? ' selected' : ''}>${esc(st.label)} (${i + 1})</option>`).join('');
  return `<div class="row at-toggles at-layers"><span class="small">마을:</span>
    <label title="화풍 고르기 (1~4)">화풍 <select data-atlas-style aria-label="마을 화풍">${styles}</select></label>${Object.entries(ATLAS_LAYERS).map(([k, [label, key]]) => `<label title="${esc(label)} 끄고 켜기 (${key.toUpperCase()})"><input type="checkbox" data-atlas-layer="${k}"${S.atlasLayers[k] ? ' checked' : ''}>${esc(label)}</label>`).join('')}
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

/** 지도 위 마을 이름 · 인구. 누르면 이름을 바꾼다 (미리보기 중에는 미리보기 마을 기준, 바꿀 수 없음) */
function atlasTitleBox() {
  const pv = atlasGenPreview();
  const t = pv ? pv.title : S.atlas.title;
  if (!t || !atlasVillage() || !S.atlasLayers.title) return '';
  if (S.atlasTitleEdit && !pv) {
    return `<form class="at-title-edit" data-atlas-title-form><input name="title" maxlength="40" value="${esc(t.custom ? t.title : '')}" placeholder="${esc(t.title || '마을 이름')}" aria-label="마을 이름">
      <button type="submit" class="btn small primary">저장</button><button type="button" class="btn small ghost" data-action="atlasTitleEdit" data-arg="">취소</button></form>`;
  }
  const name = t.title || '이름 없는 마을';
  return `<button type="button" class="at-title" ${pv ? 'disabled' : 'data-action="atlasTitleEdit" data-arg="1"'} title="${pv ? '' : '눌러 이름 바꾸기 (N 으로 숨기기)'}">
    <span class="at-title-name">${esc(name)}</span><span class="at-title-pop">인구 약 ${t.population.toLocaleString()}명 · 집 ${t.houses}채</span></button>`;
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
  return `<div class="at-bld" style="left:${b.sx}px;${pos}" role="dialog" aria-label="건물">
    <div class="between"><strong>${num >= 0 ? `집 ${num + 1}` : '건물'}</strong><button type="button" class="btn small ghost" data-action="atlasBldClose" aria-label="닫기">✕</button></div>
    ${opts ? `<label class="small">이 건물에 놓기<span class="row"><select data-atlas-bld-place>${opts}</select><button type="button" class="btn small" data-action="atlasBldPut">놓기</button></span></label>` : ''}
    <form class="at-bld-new" data-atlas-bld-form><label class="small">새 장소로 등록<span class="row"><input name="name" maxlength="40" placeholder="이름" aria-label="새 장소 이름" required><button type="submit" class="btn small primary">등록</button></span></label>
      <div class="at-chips">${ideas}</div></form></div>`;
}

/** 미리보기 조작 막대 (지도 아래에 붙는다) */
function atlasGenBar() {
  const st = S.atlasGen;
  const pv = atlasGenPreview();
  if (!pv) return '';
  const at = st.at;
  return `<div class="at-pv-bar" role="toolbar" aria-label="마을 미리보기">
    <span class="small">시드 ${st.spec.seed} · 집 ${pv.info.houses}채${st.hist.length > 1 ? ` · ${at + 1}/${st.hist.length}` : ''}</span>
    <span class="row">
      <button type="button" class="btn small ghost" data-action="atlasGenHist" data-arg="-1" title="이전 미리보기 (←)" aria-label="이전 미리보기"${at <= 0 ? ' disabled' : ''}>◀</button>
      <button type="button" class="btn small" data-action="atlasGenSeed" title="다른 시드로 (Enter)">다른 시드</button>
      <button type="button" class="btn small ghost" data-action="atlasGenHist" data-arg="1" title="다음 미리보기 (→)" aria-label="다음 미리보기"${at >= st.hist.length - 1 ? ' disabled' : ''}>▶</button>
      <button type="button" class="btn small ghost" data-action="atlasGenOpen" data-arg="" title="그만두기 (Esc)">그만두기</button>
      <button type="button" class="btn small primary" data-action="atlasGenApply">적용</button></span></div>`;
}

function atlasSide() {
  if (atlasGenPreview()) return atlasGenBox();  // 미리보기 중에는 고를 것만 보인다
  return atlasPlaceBox() + atlasWho() + atlasLoose() + atlasGenBox() + atlasLayoutBox() + atlasBackground();
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
// ----- 내보내기 -----

/** 내보낼 SVG: 확대와 상관없이 지도 전체를, 화면에 보이는 색을 속성으로 옮겨 적어 페이지 CSS 없이도 같게 보이게 한다 */
function atlasExportSvg() {
  const keep = S.atlasView;
  S.atlasView = { x: 0, y: 0, z: 1 };
  atlasExporting = true;
  const host = document.createElement('div');
  host.style.cssText = `position:fixed;left:-99999px;top:0;width:${ATLAS_W}px`;
  try {
    host.innerHTML = atlasSvg();
  } finally {
    S.atlasView = keep;
    atlasExporting = false;
  }
  document.body.appendChild(host);
  try {
    const svg = host.querySelector('svg');
    const ctx = document.createElement('canvas').getContext('2d');
    // 브라우저는 color-mix 결과를 color(srgb …)로 돌려준다. 다른 프로그램도 읽게 rgb() 와 따로 적은 불투명도로 바꾼다
    const color = (v) => {
      if (!v || v === 'none' || v.startsWith('url')) return [v, 1];
      ctx.fillStyle = '#000';
      ctx.fillStyle = v;
      const c = String(ctx.fillStyle);
      const m = c.match(/^color\(srgb ([-\d.e]+) ([-\d.e]+) ([-\d.e]+)(?: \/ ([-\d.e]+))?\)$/);
      if (m) return [`rgb(${[m[1], m[2], m[3]].map((x) => Math.round(Math.min(1, Math.max(0, Number(x))) * 255)).join(',')})`, m[4] == null ? 1 : Number(m[4])];
      const r = c.match(/^rgba\((\d+), (\d+), (\d+), ([\d.]+)\)$/);
      if (r) return [`rgb(${r[1]},${r[2]},${r[3]})`, Number(r[4])];
      return [c, 1];
    };
    const props = ['fill', 'stroke', 'stroke-width', 'stroke-dasharray', 'stroke-linecap', 'stroke-linejoin', 'opacity', 'font-size', 'font-weight', 'font-family', 'paint-order', 'text-anchor', 'dominant-baseline'];
    svg.querySelectorAll('*').forEach((el) => {
      const cs = getComputedStyle(el);
      el.setAttribute('style', props.map((p) => {
        const v = cs.getPropertyValue(p);
        if (!v) return '';
        if (p !== 'fill' && p !== 'stroke') return `${p}:${v}`;
        const [c, a] = color(v);
        return `${p}:${c}${a < 1 ? `;${p}-opacity:${a}` : ''}`;
      }).filter(Boolean).join(';'));
      el.removeAttribute('class');
      el.removeAttribute('tabindex');
    });
    svg.querySelectorAll('.at-hit, title').forEach((el) => el.remove());
    const t = S.atlas.title;
    if (t && t.title && S.atlasLayers.title && atlasVillage()) {
      // 마을 이름 글자 · 테두리는 고른 화풍의 글자 · 바탕색 (.at-map 의 --text · --canvas)
      const cs = getComputedStyle(svg);
      const ink = color(cs.color)[0];
      const halo = color(cs.getPropertyValue('--canvas').trim() || '#fff')[0];
      svg.insertAdjacentHTML('beforeend', `<text x="24" y="44" style="font-size:30px;font-weight:700;fill:${ink};paint-order:stroke;stroke:${halo};stroke-opacity:.8;stroke-width:5px">${esc(t.title)}</text>
        <text x="24" y="70" style="font-size:15px;fill:${ink};paint-order:stroke;stroke:${halo};stroke-opacity:.8;stroke-width:4px">인구 약 ${t.population.toLocaleString()}명</text>`);
    }
    svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    svg.setAttribute('width', ATLAS_W);
    svg.setAttribute('height', atlasH());
    svg.removeAttribute('class');
    return new XMLSerializer().serializeToString(svg);
  } finally {
    host.remove();
  }
}

function atlasDownload(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

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
  atlasGenOpen(on) {
    const st = atlasGenState();
    st.open = !!on;
    st.preview = null;
    st.hist = [];
    st.at = -1;
    atlasRefresh();
  },
  atlasGenHist(d) {
    const st = atlasGenState();
    const at = st.at + Number(d);
    if (!st.preview || at < 0 || at >= st.hist.length) return;
    st.at = at;
    st.spec = JSON.parse(JSON.stringify(st.hist[at].spec));
    atlasGenShow(st.hist[at].pv);
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
    await atlasSavePins([...atlasPins().filter((x) => x.place !== key), { place: key, x: b.at[0], y: b.at[1] }], `'${pl.name}'을(를) 이 건물에 놓았어요`,
      { before: atlasPinMap(), label: `'${pl.name}' ${pl.pin ? '옮기기' : '놓기'}` });
  },
  async atlasExport(kind) {
    await run(kind === 'png' ? 'PNG 만드는 중' : 'SVG 만드는 중', async () => {
      const svg = atlasExportSvg();
      const base = ((S.atlas.title && S.atlas.title.title) || P().meta.title || S.name).replace(/[\\/:*?"<>|]/g, '_');
      if (kind === 'svg') {
        atlasDownload(new Blob([svg], { type: 'image/svg+xml' }), `${base} 지도.svg`);
        return;
      }
      const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }));
      try {
        const img = await new Promise((ok, bad) => {
          const im = new Image();
          im.onload = () => ok(im);
          im.onerror = () => bad(new Error('지도를 그림으로 바꾸지 못했어요'));
          im.src = url;
        });
        const cv = document.createElement('canvas');
        cv.width = ATLAS_W * 2;
        cv.height = atlasH() * 2;
        cv.getContext('2d').drawImage(img, 0, 0, cv.width, cv.height);
        const blob = await new Promise((ok) => cv.toBlob(ok, 'image/png'));
        if (!blob) throw new Error('PNG를 만들지 못했어요');
        atlasDownload(blob, `${base} 지도.png`);
      } finally {
        URL.revokeObjectURL(url);
      }
    });
  },
  async atlasGenSeed() {
    const st = atlasGenState();
    st.spec.seed = atlasNewSeed();
    if (st.preview) await atlasGenRun(); else atlasRefresh();
  },
  async atlasGenPreview() {
    await atlasGenRun();
  },
  async atlasGenSuggest() {
    const st = atlasGenState();
    await run('AI가 마을 설정을 고르는 중', async () => {
      const r = await api('POST', `/projects/${enc(S.name)}/atlas/generate/suggest`, st.spec);
      let changed = 0;
      Object.keys(S.atlas.gen.options).forEach((k) => {  // 작가가 고른 칸은 덮지 않는다
        if (!st.touched[k] && r[k] && st.spec[k] !== r[k]) { st.spec[k] = r[k]; changed++; }
      });
      const notes = {};
      r.places.forEach((g) => {
        const row = st.spec.places.find((x) => x.key === g.key);
        if (g.note) notes[g.key] = g.note;
        if (!row || st.touched['p:' + g.key] || (row.kind === g.kind && row.put === g.put)) return;
        row.kind = g.kind;
        row.put = g.put;
        changed++;
      });
      st.ai = { reason: r.reason, notes };
      atlasRefresh();
      toast(changed ? `AI 제안으로 ${changed}칸을 바꿨어요. 확인하고 미리보기를 누르세요` : 'AI 제안이 지금 설정과 같아요');
    });
  },
  atlasGenEdit() {
    atlasGenState().preview = null;
    atlasRefresh();
  },
  async atlasGenApply() {
    const st = atlasGenState();
    const pins = Object.keys(st.take).filter((k) => st.take[k]);
    const before = atlasPinMap();
    await run('마을 적용하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/atlas/generate`, { spec: st.spec, pins });
      st.preview = null;
      st.open = false;
      await atlasLoad();
      atlasRecord(before, '마을 적용으로 장소 옮기기', atlasPinMap(), true);
      atlasRefresh();
      toast(`마을을 적용했어요${pins.length ? ` · 장소 ${pins.length}곳을 놓았어요` : ''}`);
    });
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
  if (t.matches('[data-at-gen]')) {
    const st = atlasGenState();
    st.spec[t.dataset.atGen] = t.value;
    st.touched[t.dataset.atGen] = true;
    return;
  }
  if (t.matches('[data-at-gen-seed]')) {
    const seed = Number(t.value);
    if (!Number.isInteger(seed) || seed < 0 || seed > 2147483647) { toast('시드는 0~2147483647 사이 정수로 적으세요', true); return; }
    atlasGenState().spec.seed = seed;
    return;
  }
  if (t.matches('[data-at-gen-kind]')) {
    const st = atlasGenState();
    const row = st.spec.places[Number(t.dataset.atGenKind)];
    row.kind = t.value;
    row.put = t.value !== 'far';  // 마을 밖 장소는 놓지 않는 게 기본
    st.touched['p:' + row.key] = true;
    atlasRefresh();
    return;
  }
  if (t.matches('[data-at-gen-put]')) {
    const st = atlasGenState();
    const row = st.spec.places[Number(t.dataset.atGenPut)];
    row.put = t.checked;
    st.touched['p:' + row.key] = true;
    return;
  }
  if (t.matches('[data-at-gen-take]')) {
    atlasGenState().take[t.dataset.atGenTake] = t.checked;
    const stage = document.getElementById('atlas-stage');
    if (stage) stage.innerHTML = atlasStage();
    return;
  }
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
    if (file.size > 8 * 1024 * 1024) { toast('파일이 너무 커요. 8MB 이하로 올리세요', true); return; }
    await run('마을 올리는 중', async () => {
      const data = await file.text();
      const had = (S.atlas.places || []).some((pl) => pl.pin);
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/atlas/layout`, { data });
      await atlasLoad();
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
      toast(title.trim() ? '마을 이름을 바꿨어요' : '마을 이름을 비웠어요. 마을 가운데 장소 이름을 써요');
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

// 단축키 (입력 칸 밖에서): 미리보기 Enter 다른 시드 · ← → 이전/다음 · Esc 그만두기, + - 0 확대, 1~4 화풍, T F U M N 마을 겹
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
  await atlasSavePins(atlasPins(), '', pl && { before: d.before, label: `'${pl.name}' 옮기기` });
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
.at-title { position: absolute; top: 8px; left: 8px; display: flex; flex-direction: column; align-items: flex-start; gap: 0; padding: 6px 10px; border: 1px solid var(--line); border-radius: 8px; background: color-mix(in srgb, var(--surface) 88%, transparent); color: var(--text); font: inherit; text-align: left; cursor: pointer; }
.at-title:disabled { cursor: default; }
.at-title-name { font-size: 1.125rem; font-weight: 700; }
.at-title-pop { font-size: 0.75rem; color: var(--muted); }
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
.at-map .at-v-shadow { fill: var(--v-shadow); }
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
.at-gen-note { grid-column: 1 / -1; margin-top: -2px; }
.at-scale { display: inline-flex; align-items: center; gap: 6px; }
.at-scale input { width: 80px; }
.at-walk { display: block; padding-left: 16px; }
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

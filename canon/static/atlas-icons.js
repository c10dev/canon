/* 장소 종류 기호와 범례 (docs/map/specs/15-place-icons.md). 서버 canon/atlas.py 의 summary 가 장소마다 kind(지금 지도 시대의 종류 id)와
   kind_label 을 싣는다. 기호는 직접 그린 단순 모양을 채운 path 하나로 만든다(선 없음, 내보낸 그림에도 그대로 나온다).
   핀 그리기는 atlas.js 의 atlasSvg, 범례 자리는 atlas.js 의 atlasDeco 가 이 파일의 함수를 부른다.
   앞 구간(기호 표 ~ 범례 칸 나누기)은 화면을 모르는 계산이라 tests/test_atlas_icons.py 가 node 로 잘라 돌린다. */
'use strict';

// ----- 기호 표 (화면을 모른다) -----

/** 기호 모양: −10~10 칸의 조각 목록. 조각 이름 앞의 '-' 는 구멍(기호 안의 빈 곳, 핀 원 색이 보인다).
    r 사각형(x, y, 폭, 높이), rr 둥근 사각형(… 반지름), c 원(cx, cy, r), p 다각형([[x, y] …]), l 굵은 선(x1, y1, x2, y2, 굵기),
    pl 굵은 꺾은선([[x, y] …], 굵기), arch 아치(가운데 x, 아래 y, 폭, 높이), leaf 잎(끝 x1, y1, 끝 x2, y2, 폭), star 별(cx, cy, 바깥 r, 안 r) */
const ATLAS_GLYPHS = {
  flag: [['r', -6.5, -9.5, 2, 19], ['p', [[-4.5, -9.5], [8.5, -5.25], [-4.5, -1]]]],
  stall: [['p', [[-9.5, -4], [-7, -9.5], [7, -9.5], [9.5, -4]]], ['c', -7.1, -4, 2.4], ['c', -2.4, -4, 2.4], ['c', 2.4, -4, 2.4], ['c', 7.1, -4, 2.4],
    ['r', -8, 0, 16, 9], ['-r', -2.5, 3, 5, 6]],
  well: [['p', [[-9.5, -3], [0, -9.5], [9.5, -3]]], ['r', -7.5, -3.5, 2, 7], ['r', 5.5, -3.5, 2, 7], ['r', -0.6, -3.5, 1.2, 3.5], ['rr', -2.2, -0.5, 4.4, 3, 0.8],
    ['rr', -8.5, 3.5, 17, 6, 1.5]],
  temple: [['p', [[-9.5, -4], [0, -9.5], [9.5, -4]]], ['r', -9.5, -3.5, 19, 2], ['r', -7.5, -0.8, 2.6, 8], ['r', -1.3, -0.8, 2.6, 8], ['r', 4.9, -0.8, 2.6, 8],
    ['r', -9.5, 7.5, 19, 2]],
  steeple: [['p', [[0, -10], [3, -4], [-3, -4]]], ['r', -3, -4.2, 6, 13.7], ['p', [[-9, 1.5], [-3, -2], [-3, 1.5]]], ['r', -9, 1.5, 6.5, 8],
    ['p', [[9, 1.5], [3, -2], [3, 1.5]]], ['r', 2.5, 1.5, 6.5, 8], ['-arch', 0, 9.5, 3, 5]],
  bed: [['rr', -9.5, -7, 3, 16.5, 1], ['rr', -6.8, -1, 16.3, 5, 1], ['rr', -5.8, -4.5, 5, 3, 1.2], ['rr', 2, -3.5, 7.5, 3, 1.2], ['r', 6.5, 4, 3, 5.5]],
  anvil: [['p', [[-10, -5.5], [8.5, -5.5], [8.5, -1], [3.5, -1], [2.5, 3], [6.5, 8], [-6.5, 8], [-2.5, 3], [-3.5, -1], [-6.5, -2.5]]]],
  mill: [['p', [[-3.5, 9.5], [-1.8, -1.5], [1.8, -1.5], [3.5, 9.5]]], ['l', 0, -2.5, -6.6, -8.6, 3.2], ['l', 0, -2.5, 6.6, -8.6, 3.2], ['l', 0, -2.5, -6.8, 3.8, 3.2],
    ['l', 0, -2.5, 6.8, 3.8, 3.2], ['c', 0, -2.5, 2.4], ['-c', 0, -2.5, 0.9]],
  castle: [['r', -8.5, -9.5, 3.5, 3.5], ['r', -1.75, -9.5, 3.5, 3.5], ['r', 5, -9.5, 3.5, 3.5], ['r', -8.5, -6.5, 17, 16], ['-arch', 0, 9.5, 5.5, 7],
    ['-r', -6, -3, 2, 3], ['-r', 4, -3, 2, 3]],
  house: [['p', [[-9.5, -0.5], [0, -9.5], [9.5, -0.5]]], ['r', 4, -8, 2.6, 5], ['r', -6.8, -1, 13.6, 10], ['-r', -1.8, 3.5, 3.6, 5.5]],
  sprout: [['r', -0.9, -3, 1.8, 11.5], ['leaf', 0, -1, -8.5, -6.5, 4.2], ['leaf', 0, -3.5, 8, -9.5, 4.2], ['rr', -7, 7.5, 14, 2, 1]],
  anchor: [['c', 0, -7, 2.6], ['-c', 0, -7, 1.2], ['r', -1.1, -4.6, 2.2, 13], ['rr', -5, -3.2, 10, 2.2, 1],
    ['pl', [-160, -135, -110, -90, -70, -45, -20].map((d) => [7.2 * Math.cos(d * Math.PI / 180), 1.5 - 7.2 * Math.sin(d * Math.PI / 180)]), 2.2],
    ['p', [[-9.6, 0], [-5.3, -1.2], [-6.4, 3.6]]], ['p', [[9.6, 0], [5.3, -1.2], [6.4, 3.6]]]],
  bridge: [['r', -10, -6.5, 20, 2.6], ['r', -10, -3.9, 20, 8.4], ['-arch', 0, 4.5, 14, 7], ['r', -9.2, -9, 1.6, 2.6], ['r', 7.6, -9, 1.6, 2.6],
    ['pl', [...Array(9).keys()].map((i) => [-8 + i * 2, 8 + 1.1 * Math.sin(i * Math.PI / 2)]), 1.7]],
  waves: [['pl', [...Array(13).keys()].map((i) => [-9 + i * 1.5, -3.5 + 1.8 * Math.sin(i * Math.PI / 3)]), 2.4],
    ['pl', [...Array(13).keys()].map((i) => [-9 + i * 1.5, 4 + 1.8 * Math.sin(i * Math.PI / 3)]), 2.4]],
  drop: [['c', 0, 2.5, 6.5], ['p', [[0, -9.8], [5.5, -1], [-5.5, -1]]], ['-leaf', -3.2, 5.6, -4.6, 1.2, 1.4]],
  pine: [['p', [[0, -10], [5, -4], [-5, -4]]], ['p', [[0, -6.5], [7, 1], [-7, 1]]], ['p', [[0, -2.5], [9.5, 6.5], [-9.5, 6.5]]], ['r', -1.6, 6, 3.2, 3.8]],
  mountain: [['p', [[-10, 8.5], [-3, -7], [1, -0.5], [4.5, -4], [10, 8.5]]], ['-p', [[-3, -5], [-1, -1.8], [-2.2, -2.6], [-3, -1.4], [-3.8, -2.6], [-4.6, -2]]]],
  train: [['rr', -7, -9.5, 14, 15.5, 3.2], ['-rr', -5, -7, 10, 5.5, 1], ['-c', -4, 2.4, 1.4], ['-c', 4, 2.4, 1.4],
    ['p', [[-4.8, 6], [-2.6, 6], [-5.8, 10], [-8, 10]]], ['p', [[4.8, 6], [2.6, 6], [5.8, 10], [8, 10]]]],
  bag: [['p', [[-7.2, -3], [7.2, -3], [8.5, 9.5], [-8.5, 9.5]]], ['pl', [180, 150, 120, 90, 60, 30, 0].map((d) => [3.6 * Math.cos(d * Math.PI / 180), -3 - 4.2 * Math.sin(d * Math.PI / 180)]), 2]],
  cup: [['p', [[-8.5, -3.5], [5, -3.5], [4.6, 1], [2.2, 5], [-5.7, 5], [-8.1, 1]]], ['c', 5.5, -0.2, 3.4], ['-c', 5.5, -0.2, 1.7], ['rr', -10, 6.3, 16.5, 2, 1],
    ['rr', -4.6, -9.5, 1.6, 4.5, 0.8], ['rr', -0.6, -9.5, 1.6, 4.5, 0.8]],
  fork: [['r', -8.4, -9.5, 1.3, 5.5], ['r', -6.1, -9.5, 1.3, 5.5], ['r', -3.8, -9.5, 1.3, 5.5], ['rr', -8.4, -4.8, 5.9, 3, 1.4], ['rr', -6.3, -3, 1.7, 12.5, 0.8],
    ['p', [[3.5, -9.5], [7.5, -5.5], [7.5, 0.5], [3.5, 0.5]]], ['rr', 3.5, 0, 2.6, 9.5, 1]],
  cap: [['p', [[-10, -3.5], [0, -8.5], [10, -3.5], [0, 1.5]]], ['p', [[-6, -0.5], [0, 2.5], [6, -0.5], [6, 4.5], [0, 7], [-6, 4.5]]], ['r', 7.9, -3.5, 1.2, 8],
    ['c', 8.5, 5.5, 1.7]],
  book: [['p', [[-10, -6.5], [-1, -4.5], [-1, 8.5], [-10, 6.5]]], ['p', [[1, -4.5], [10, -6.5], [10, 6.5], [1, 8.5]]]],
  plus: [['rr', -2.9, -8.5, 5.8, 17, 1], ['rr', -8.5, -2.9, 17, 5.8, 1]],
  shield: [['p', [[0, -9.5], [8.5, -6.5], [8, 1], [5.5, 5.5], [0, 9.8], [-5.5, 5.5], [-8, 1], [-8.5, -6.5]]], ['-star', 0, -0.6, 4.6, 1.9]],
  case: [['rr', -9.5, -4, 19, 12.5, 2], ['rr', -4, -8.5, 8, 5.5, 1.5], ['-rr', -2.6, -7.1, 5.2, 3.1, 0.6], ['-r', -9.5, 1, 19, 1.3]],
  factory: [['p', [[-10, 9.5], [-10, -1], [-5, -5], [-5, -1], [0, -5], [0, -1], [5, -5], [5, -1], [9.5, -1], [9.5, 9.5]]], ['r', 6, -10, 3.2, 9.5],
    ['-r', -8, 3, 3, 3], ['-r', -3, 3, 3, 3], ['-r', 2, 3, 3, 3]],
  tower: [['r', -5.8, -10, 11.6, 20], ['r', -10, -4, 3.4, 14], ['r', 6.6, -4, 3.4, 14],
    ...[-8, -4, 0, 4].flatMap((y) => [-4.2, -1, 2.2].map((x) => ['-r', x, y, 2, 2.4]))],
  villa: [['r', -10, -7, 20, 1.8], ['r', -8.8, -5.2, 17.6, 14.7],
    ...[-3.3, 1].flatMap((y) => [-6.6, -1.3, 4].map((x) => ['-r', x, y, 2.6, 2.6])), ['-r', -1.5, 5.3, 3, 4.2]],
  tree: [['c', 0, -3.5, 6.2], ['c', -4.5, 0, 4.2], ['c', 4.5, 0, 4.2], ['r', -1.4, 1, 2.8, 9]],
};

/** 종류 id → 기호 (차례는 placekinds.KINDS: 옛 종류, 두 시대 모두, 현대 종류). 비슷한 종류는 기호를 함께 쓴다. 표는 명세서 15 '기호 표' */
const ATLAS_ICON_OF = {
  center: 'flag', market: 'stall', well: 'well', temple: 'temple', inn: 'bed', smith: 'anvil', mill: 'mill', manor: 'castle', home: 'house',
  shore: 'anchor', bridge: 'bridge', river: 'waves', pond: 'drop', forest: 'pine', field: 'sprout', far: 'mountain',
  station: 'train', convenience: 'bag', cafe: 'cup', restaurant: 'fork', mart: 'stall', school: 'cap', academy: 'book', hospital: 'plus',
  police: 'shield', church: 'steeple', company: 'case', factory: 'factory', hotel: 'bed', apartment: 'tower', villa: 'villa', house: 'house', park: 'tree',
};

/** 조각 하나 → 꼭짓점 고리 (구멍이면 시계 반대, 아니면 시계 방향으로 맞춘다. 한 path 를 nonzero 로 칠해 겹친 곳은 합치고 구멍은 뚫는다) */
function atlasGlyphRing(part) {
  const hole = part[0][0] === '-';
  const [k, ...a] = [hole ? part[0].slice(1) : part[0], ...part.slice(1)];
  const arc = (cx, cy, r, a0, a1, n) => [...Array(n + 1).keys()].map((i) => {
    const t = a0 + ((a1 - a0) * i) / n;
    return [cx + r * Math.cos(t), cy + r * Math.sin(t)];
  });
  const thick = (x1, y1, x2, y2, w) => {
    const len = Math.hypot(x2 - x1, y2 - y1) || 1;
    const [nx, ny] = [(-(y2 - y1) / len) * (w / 2), ((x2 - x1) / len) * (w / 2)];
    return [[x1 + nx, y1 + ny], [x2 + nx, y2 + ny], [x2 - nx, y2 - ny], [x1 - nx, y1 - ny]];
  };
  let rings;
  if (k === 'r') rings = [[[a[0], a[1]], [a[0] + a[2], a[1]], [a[0] + a[2], a[1] + a[3]], [a[0], a[1] + a[3]]]];
  else if (k === 'rr') {
    const [x, y, w, h, r] = a;
    const q = Math.PI / 2;
    rings = [[...arc(x + w - r, y + r, r, -q, 0, 4), ...arc(x + w - r, y + h - r, r, 0, q, 4), ...arc(x + r, y + h - r, r, q, 2 * q, 4), ...arc(x + r, y + r, r, 2 * q, 3 * q, 4)]];
  } else if (k === 'c') rings = [arc(a[0], a[1], a[2], 0, 2 * Math.PI, 24).slice(0, -1)];
  else if (k === 'p') rings = [a[0]];
  else if (k === 'l') rings = [thick(...a)];
  else if (k === 'pl') {
    const [pts, w] = a;
    rings = pts.slice(1).map((q, i) => thick(pts[i][0], pts[i][1], q[0], q[1], w)).concat(pts.slice(1, -1).map((q) => arc(q[0], q[1], w / 2, 0, 2 * Math.PI, 12).slice(0, -1)));
  } else if (k === 'arch') {
    const [cx, y, w, h] = a;
    const r = w / 2;
    rings = [[[cx + r, y], ...arc(cx, y - h + r, r, 0, -Math.PI, 10), [cx - r, y]]];
  } else if (k === 'leaf') {
    const [x1, y1, x2, y2, w] = a;
    const len = Math.hypot(x2 - x1, y2 - y1);
    const [nx, ny] = [-(y2 - y1) / len, (x2 - x1) / len];
    const side = (s) => [...Array(9).keys()].map((i) => {
      const t = i / 8;
      const bulge = Math.sin(Math.PI * t) * (w / 2) * s;
      return [x1 + (x2 - x1) * t + nx * bulge, y1 + (y2 - y1) * t + ny * bulge];
    });
    rings = [[...side(1), ...side(-1).reverse().slice(1, -1)]];
  } else if (k === 'star') {
    const [cx, cy, R, r] = a;
    rings = [[...Array(10).keys()].map((i) => {
      const t = -Math.PI / 2 + (i * Math.PI) / 5;
      return [cx + (i % 2 ? r : R) * Math.cos(t), cy + (i % 2 ? r : R) * Math.sin(t)];
    })];
  } else throw new Error(`모르는 기호 조각: ${part[0]}`);
  return rings.map((ring) => {
    const area = ring.reduce((s, q, i) => { const n = ring[(i + 1) % ring.length]; return s + q[0] * n[1] - n[0] * q[1]; }, 0);
    return (area < 0) !== hole ? ring.slice().reverse() : ring;  // 화면 좌표(y 아래)에서 넓이 > 0 이 시계 방향
  });
}

/** 기호 path (−10~10 칸, nonzero) */
function atlasGlyphPath(parts) {
  return parts.flatMap(atlasGlyphRing).map((ring) => `M${ring.map((q) => `${+q[0].toFixed(2)},${+q[1].toFixed(2)}`).join('L')}Z`).join('');
}

const ATLAS_ICONS = Object.fromEntries(Object.entries(ATLAS_GLYPHS).map(([k, parts]) => [k, atlasGlyphPath(parts)]));

/** 종류 id → 기호 이름. 모르는 종류 · 빈 글자는 '' (기호 없이 점) */
function atlasIconFor(kind) {
  return (kind && ATLAS_ICON_OF[kind]) || '';
}

/** 기호 하나: (x, y) 가운데, 지름 size(지도 단위) 칸에. cls 는 path class. 모르는 종류는 빈 글 */
function atlasIconSvg(kind, x, y, size, cls = 'at-ico') {
  const icon = atlasIconFor(kind);
  if (!icon) return '';
  return `<path class="${cls}" d="${ATLAS_ICONS[icon]}" transform="translate(${x.toFixed(2)} ${y.toFixed(2)}) scale(${(size / 20).toFixed(4)})"></path>`;
}

/** 범례 줄: 그린 핀의 종류를 기호 차례(ATLAS_ICON_OF)로 한 번씩. 같은 기호를 쓰는 종류는 한 줄에 이름을 쉼표로 잇는다.
    pins: [{ kind, kind_label }]. 돌려주는 값: [{ icon, kinds: [id], label }] */
function atlasLegendKinds(pins) {
  const have = new Map();
  pins.forEach((p) => { if (atlasIconFor(p.kind) && !have.has(p.kind)) have.set(p.kind, p.kind_label || p.kind); });
  const rows = new Map();
  Object.keys(ATLAS_ICON_OF).filter((k) => have.has(k)).forEach((k) => {
    const icon = ATLAS_ICON_OF[k];
    if (!rows.has(icon)) rows.set(icon, { icon, kinds: [], label: '' });
    const r = rows.get(icon);
    r.kinds.push(k);
    r.label = r.label ? `${r.label}, ${have.get(k)}` : have.get(k);
  });
  return [...rows.values()];
}

/** 범례 칸 나누기: rows(atlasLegendKinds), 줄 높이 rowH, 줄 하나의 폭 widthOf(줄), 쓸 수 있는 폭 maxW · 높이 maxH(제목 · 여백 뺀 줄 칸).
    높이에 다 들어가지 않으면 열을 늘리고, 폭이 모자라면 열을 줄이고 마지막 칸을 '외 n종'으로 바꾼다.
    돌려주는 값: { cols: [[줄]], more: 못 보인 종류 수, w: 열 폭 합(열 사이 gap 포함) } */
function atlasLegendFit(rows, rowH, widthOf, maxW, maxH, gap) {
  const per = Math.max(1, Math.floor(maxH / rowH));
  const need = Math.max(1, Math.ceil(rows.length / per));
  for (let c = need; c >= 1; c--) {
    let shown = rows;
    let more = 0;
    if (rows.length > c * per) {
      shown = rows.slice(0, c * per - 1);
      more = rows.slice(c * per - 1).reduce((n, r) => n + r.kinds.length, 0);
      shown = shown.concat([{ icon: '', kinds: [], label: `외 ${more}종` }]);
    }
    const n = Math.ceil(shown.length / c);
    const cols = [...Array(c).keys()].map((i) => shown.slice(i * n, (i + 1) * n)).filter((x) => x.length);
    const w = cols.reduce((s, col) => s + Math.max(...col.map(widthOf)), 0) + gap * (cols.length - 1);
    if (w <= maxW || c === 1) return { cols, more, w };
  }
  return { cols: [rows], more: 0, w: 0 };
}

// ----- 범례 그리기 -----

/** 범례 '이 지도의 장소': 왼쪽 아래 (x0, y1) 모서리에 화면 크기 고정(u: 화면 1px 의 지도 단위)으로. maxW · maxH: 쓸 수 있는 폭 · 높이,
    textW(글, 크기, 굵게): 글자 폭 재기 (atlas.js 의 atlasDecoW). 돌려주는 값: { svg, box } (줄이 없으면 null) */
function atlasLegend(rows, x0, y1, u, maxW, maxH, textW, narrow = false) {
  if (!rows.length) return null;
  const f = (v) => v.toFixed(2);
  const pad = 6 * u;
  const fs = (narrow ? 9.5 : 10.5) * u;
  const ft = (narrow ? 10 : 11) * u;
  const rowH = (narrow ? 14 : 16) * u;
  const r = (narrow ? 5 : 5.5) * u;
  const gap = 10 * u;
  const title = '이 지도의 장소';
  const head = ft + 5 * u;
  const widthOf = (row) => (row.icon ? 2 * r + 5 * u : 0) + textW(row.label, fs);
  const fit = atlasLegendFit(rows, rowH, widthOf, maxW - 2 * pad, maxH - 2 * pad - head, gap);
  const w = Math.max(fit.w, textW(title, ft, true)) + 2 * pad;
  const h = 2 * pad + head + Math.max(...fit.cols.map((c) => c.length)) * rowH;
  const bx = x0;
  const by = y1 - h;
  const out = [`<rect class="at-v-frame" x="${f(bx)}" y="${f(by)}" width="${f(w)}" height="${f(h)}" rx="${f(6 * u)}" stroke-width="${f(u)}"></rect>`,
    `<text class="at-v-legend-title" x="${f(bx + pad)}" y="${f(by + pad + ft * 0.85)}" font-size="${f(ft)}">${esc(title)}</text>`];
  let cx = bx + pad;
  fit.cols.forEach((col) => {
    col.forEach((row, i) => {
      const cy = by + pad + head + i * rowH + rowH / 2;
      if (row.icon) {
        out.push(`<circle class="at-v-legend-dot" cx="${f(cx + r)}" cy="${f(cy)}" r="${f(r)}"></circle>`,
          atlasIconSvg(row.kinds[0], cx + r, cy, r * 1.5, 'at-v-legend-ico'));
      }
      out.push(`<text class="at-v-legend-text${row.icon ? '' : ' more'}" x="${f(cx + (row.icon ? 2 * r + 5 * u : 0))}" y="${f(cy + fs * 0.36)}" font-size="${f(fs)}">${esc(row.label)}</text>`);
    });
    cx += Math.max(...col.map(widthOf)) + gap;
  });
  return { svg: `<g class="at-v-legend">${out.join('')}</g>`, box: [bx, by, bx + w, by + h] };
}

(function atlasIconStyle() {
  const css = document.createElement('style');
  css.textContent = `
.at-map .at-ico { fill: var(--surface); pointer-events: none; }
.at-map .at-pin.later .at-ico { fill: var(--muted); }
.at-map .at-sug .at-ico { fill: var(--surface); pointer-events: none; }
.at-map .at-v-legend { pointer-events: none; }
.at-map .at-v-legend-title { fill: var(--v-frame-ink); font-weight: 700; font-family: inherit; }
.at-map .at-v-legend-text { fill: var(--v-frame-ink); font-family: inherit; }
.at-map .at-v-legend-text.more { fill: var(--v-frame-muted); }
.at-map .at-v-legend-dot { fill: var(--text); }
.at-map .at-v-legend-ico { fill: var(--surface); }`;
  document.head.appendChild(css);
}());

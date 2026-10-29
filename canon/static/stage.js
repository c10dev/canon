/* 장면 연출 (서버 stage.py, 설계 docs/stage/). app.js 의 S, actions, api, render, header, esc, enc, ep, P, base, toast, charName, isTyping 을 쓴다.
   주소 stage/<화>/<사건 번호(1부터)>. 플롯 사건 하나의 장면을 방 평면도 위에 박자마다 짜고 재생한다.
   고치는 장면은 S.stg.scene · room 에 따로 들고 '저장'으로 PUT 한다(작품 전체 저장과 따로). 고칠 때마다 서버가 저장 없이 판정한다(POST …/check).
   인물 자리는 기준점 + 관계 말이고 좌표는 stageLayout 이 계산하고 stageLayouts 가 박자마다 앞 박자 좌표를 잇는다 (stage.place · layouts 와 같은 규칙, tests/test_stage_js.py).
   한 사건에 계획 장면(role plan)과 본문 장면(role text)이 하나씩 있다. 머리의 '계획 | 본문'으로 바꿔 보고(S.stg.role),
   본문 장면에서는 계획 인물을 흐린 원으로 겹쳐 본다(S.stg.ghost). 계획과 다른 곳(gaps)과 박자 짝(match)은 서버 stage.align 이 잰다.
   stageState · stageLayout · stageLayouts · stageAnchorPoint · stageFacing · stageSnap · stageSexual · stagePlanBeat 은 DOM 없는 순수 함수다. */
'use strict';

Object.assign(S, {
  stg: null,  // { n, ev, view, role, ghost, sid, scene, room, dirty, beat, who, mode, check, form, pick, playing }
});

// ----- 위치 계산: stage.py 와 같은 규칙 -----

const STG_GAP = 0.4;
const STG_BODY = 0.25;
const STG_SPREAD = 0.5;
const STG_ACROSS = 1.2;
const STG_UNKNOWN = '?';
const STG_ROT = { 0: [0, 1], 90: [-1, 0], 180: [0, -1], 270: [1, 0] };
const STG_DIRS = ['n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw'];
const stgRound = (x) => Math.round(x * 1e6) / 1e6;
const STG_FACE = Object.fromEntries(STG_DIRS.map((k, i) => [k, [stgRound(Math.sin(i * Math.PI / 4)), stgRound(-Math.cos(i * Math.PI / 4))]]));

const stgFront = (rot) => STG_ROT[((rot % 360) + 360) % 360] || [0, 1];

/** 기준점 + 관계의 자리 (m). 왼쪽 · 오른쪽은 기준점 앞에서 바라본 쪽. stage._anchor_point 와 같다. */
function stageAnchorPoint(a, rel) {
  const cx = a.x + a.w / 2, cy = a.y + a.h / 2;
  const [fx, fy] = stgFront(a.rot || 0);
  const [rx, ry] = [fy, -fx];
  const out = (vx, vy) => {
    const half = (Math.abs(vx) * a.w + Math.abs(vy) * a.h) / 2;
    return [cx + vx * (half + STG_GAP), cy + vy * (half + STG_GAP)];
  };
  if (rel === 'front') return out(fx, fy);
  if (rel === 'back' || rel === 'across') return out(-fx, -fy);
  if (rel === 'against') {
    const half = (Math.abs(fx) * a.w + Math.abs(fy) * a.h) / 2;
    return [cx + fx * (half + STG_BODY), cy + fy * (half + STG_BODY)];
  }
  if (rel === 'right' || rel === 'beside') return out(rx, ry);
  if (rel === 'left') return out(-rx, -ry);
  return [cx, cy];
}

/** 향한 쪽 단위 벡터. 모르면 null. stage.facing_vec 와 같다. */
function stageFacing(facing, me, room, pos) {
  if (STG_FACE[facing]) return STG_FACE[facing];
  let t = null;
  if ((facing || '').startsWith('@')) t = pos[facing.slice(1)] || null;
  else if ((facing || '').startsWith('#')) {
    const a = room.anchors.find((x) => x.id === facing.slice(1));
    t = a ? [a.x + a.w / 2, a.y + a.h / 2] : null;
  }
  if (!t) return null;
  const dx = t[0] - me[0], dy = t[1] - me[1], d = Math.hypot(dx, dy);
  return d > 1e-6 ? [dx / d, dy / d] : null;
}

function stgPersonPoint(o, facing, rel, room, pos) {
  const [fx, fy] = stageFacing(facing, o, room, pos) || [0, 1];
  const [rx, ry] = [-fy, fx];
  const d = STG_BODY * 2 + 0.05;
  if (rel === 'on' || rel === 'in') return [o[0] + 0.15, o[1]];
  if (rel === 'across') return [o[0] + fx * STG_ACROSS, o[1] + fy * STG_ACROSS];
  if (rel === 'against') return [o[0] + fx * STG_BODY * 2, o[1] + fy * STG_BODY * 2];
  const v = { front: [fx, fy], back: [-fx, -fy], left: [-rx, -ry] }[rel] || [rx, ry];
  return [o[0] + v[0] * d, o[1] + v[1] * d];
}

/** k 번째 박자까지 겹친 상태 (0 은 시작 상태). stage.state_at 과 같다. */
function stageState(scene, k) {
  const out = {};
  const now = (w) => (out[w] = out[w] || { at: null, posture: '', facing: '', left: STG_UNKNOWN, right: STG_UNKNOWN, contacts: {}, at_at: 0, contact_at: {} });
  (scene.cast || []).forEach(now);
  const apply = (b, i) => {
    const s = now(b.who);
    if (b.at) { s.at = b.at; s.at_at = i; }
    if (b.posture) s.posture = b.posture;
    if (b.facing) s.facing = b.facing;
    if (b.left != null) s.left = b.left.trim();
    if (b.right != null) s.right = b.right.trim();
    (b.ends || []).forEach((id) => { delete s.contacts[id]; delete s.contact_at[id]; });
    (b.contacts || []).forEach((c) => { s.contacts[c.id] = c; s.contact_at[c.id] = i; });
  };
  (scene.start || []).forEach((b) => apply(b, 0));
  (scene.beats || []).slice(0, k).forEach((beat, i) => (beat.bodies || []).forEach((b) => apply(b, i + 1)));
  return out;
}

/** 인물마다 평면도 좌표 (m). stage.place 와 같다. prev 는 앞 박자 좌표 (기준 인물이 나를 향하는데 내 자리를 아직 모를 때 쓴다). */
function stageLayout(room, state, order = [], prev = null) {
  const names = order.filter((w) => w in state).concat(Object.keys(state).filter((w) => !order.includes(w)));
  const anchors = Object.fromEntries(room.anchors.map((a) => [a.id, a]));
  const pos = {};
  const groups = new Map();
  names.forEach((w) => {
    const at = state[w].at;
    if (!at || !anchors[at.ref]) return;
    const key = `${at.ref}\u0000${at.rel}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(w);
  });
  groups.forEach((ws, key) => {
    const [ref, rel] = key.split('\u0000');
    const [x, y] = stageAnchorPoint(anchors[ref], rel);
    const [fx, fy] = stgFront(anchors[ref].rot || 0);
    ws.forEach((w, i) => {
      const k = Math.floor((i + 1) / 2) * (i % 2 ? 1 : -1);
      pos[w] = [x + fy * STG_SPREAD * k, y - fx * STG_SPREAD * k];
    });
  });
  const rest = names.filter((w) => !(w in pos) && state[w].at && state[w].at.ref.startsWith('@'));
  while (rest.length) {
    let moved = false;
    for (const w of [...rest]) {
      const ref = state[w].at.ref.slice(1);
      if (ref in pos) {
        const look = prev && prev[w] ? { ...pos, [w]: prev[w] } : pos;
        pos[w] = stgPersonPoint(pos[ref], state[ref].facing, state[w].at.rel, room, look);
        rest.splice(rest.indexOf(w), 1);
        moved = true;
      }
    }
    if (!moved) pos[rest.shift()] = [room.w / 2, room.h / 2];
  }
  const clamp = (v, hi) => Math.min(Math.max(v, STG_BODY), hi - STG_BODY);
  return Object.fromEntries(Object.entries(pos).map(([w, [x, y]]) => [w, [clamp(x, room.w), clamp(y, room.h)]]));
}

/** 박자 0~k 의 좌표 목록. 박자마다 앞 박자 좌표를 넘긴다. stage.layouts 와 같다. */
function stageLayouts(room, scene, k = (scene.beats || []).length) {
  const out = [];
  for (let i = 0; i <= k; i++) out.push(stageLayout(room, stageState(scene, i), scene.cast, i ? out[i - 1] : null));
  return out;
}

/** 평면도에서 끌어 놓은 자리 (m) 에 가장 가까운 기준점 + 관계. 기준점이 없으면 null. */
function stageSnap(room, x, y) {
  let best = null;
  room.anchors.forEach((a) => ['on', 'front', 'back', 'left', 'right', 'against'].forEach((rel) => {
    const [px, py] = stageAnchorPoint(a, rel);
    const d = Math.hypot(px - x, py - y);
    if (!best || d < best.d) best = { ref: a.id, rel, d };
  }));
  return best && { ref: best.ref, rel: best.rel };
}

/** 성적 접촉: 동작이 성적이거나, 친밀한 동작이 성적 부위에 닿는다. stage.is_sexual 과 같다. */
function stageSexual(c, vocab) {
  const act = vocab.acts[c.act], part = vocab.parts[c.part];
  return !!(act && (act.sexual || (act.intimate && part && part.sexual)));
}

/** 본문 박자 k 에 견주는 계획 박자: match(계획 박자마다 견준 본문 박자, stage.align)에서 k 이하인 마지막 계획 박자. */
function stagePlanBeat(match, k) {
  let out = 0;
  (match || []).forEach((t, i) => { if (t <= k) out = i; });
  return out;
}

// ----- 불러오기 · 고치기 -----

async function stgLoad(n, ev) {
  if (!n || !ep(n)) { S.stg = null; return; }
  const view = await api('GET', `/projects/${enc(S.name)}/stage/${n}`);
  const keep = S.stg && S.stg.n === n && S.stg.ev === ev && S.stg.dirty;
  if (keep) { S.stg.view = view; return; }
  S.stgDirty = false;
  const role = S.stg ? S.stg.role : 'plan', ghost = S.stg ? S.stg.ghost : true;
  const jump = S.stgJump && S.stgJump.n === n && S.stgJump.ev === ev ? S.stgJump : null;  // 검수 화면의 '장면 연출에서 보기'
  S.stgJump = null;
  S.stg = { n, ev, view, role: jump ? jump.role : role, ghost, sid: null, scene: null, room: null, dirty: false, beat: jump ? jump.beat : 0, who: '', mode: 'people', check: null,
    form: { by: 'right', to: '', part: '', act: 'hold' }, pick: { room: '', template: 'bedroom', name: '' }, playing: null };
  stgPick();
}

/** 지금 사건 · 역할의 검토를 기다리는 AI 장면 (서버 pending.json, web._stage_view). */
const stgProposal = (g) => (g.view.proposals || []).find((x) => x.event === g.ev - 1 && x.role === g.role) || null;

/** 지금 사건 · 역할의 화면 값 줄 (사건 찾기는 서버가 한 값). */
const stgRow = (g, role) => g.view.scenes.find((x) => x.event === g.ev - 1 && (x.scene.role || 'plan') === role) || null;

/** 지금 사건 · 역할의 장면을 고른다. */
function stgPick() {
  const g = S.stg;
  g.role = g.role || 'plan';
  const row = stgRow(g, g.role);
  g.sid = row ? row.scene.id : null;
  g.scene = row ? structuredClone(row.scene) : null;
  const room = row && g.view.rooms.find((r) => r.id === row.scene.room);
  g.room = room ? structuredClone(room) : null;
  g.check = row ? { event_changed: row.event_changed, stale: row.stale, violations: row.violations, pair: row.pair, gaps: row.gaps || [], match: row.match || [], dropped: 0 } : null;
  g.beat = Math.min(g.beat, g.scene ? g.scene.beats.length : 0);
  if (g.scene && !g.scene.cast.includes(g.who)) g.who = g.scene.cast[0] || '';
}

/** 서버가 돌려준 화면 값을 받는다: 작품의 장면 · 방도 맞춘다 (사이드바 도구 표시). */
function stgTake(view) {
  const g = S.stg;
  g.view = view;
  const e = ep(g.n);
  if (e) e.stage = view.scenes.map((x) => x.scene);
  P().rooms = view.rooms;
}

let stgTimer = null;
function stgTouch() {
  const g = S.stg;
  g.dirty = true;
  S.stgDirty = true;
  clearTimeout(stgTimer);
  stgTimer = setTimeout(stgCheck, 250);
  render();
}

async function stgCheck() {
  const g = S.stg;
  if (!g || !g.scene) return;
  try {
    g.check = await api('POST', `/projects/${enc(S.name)}/stage/${g.n}/check`, { scene: g.scene, room: g.room });
    if (!isTyping()) render();
  } catch (err) {
    toast(err.message, true);
  }
}

/** 지금 박자에서 이 인물의 몸 칸 (없으면 만든다). 박자 0 은 시작 상태. */
function stgBody(who, make = true) {
  const g = S.stg;
  const list = g.beat === 0 ? g.scene.start : g.scene.beats[g.beat - 1].bodies;
  let b = list.find((x) => x.who === who);
  if (!b && make) {
    b = { who, at: null, posture: '', facing: '', left: null, right: null, contacts: [], ends: [], memo: '' };
    list.push(b);
  }
  return b || null;
}

/** 박자 칸이 비면 뺀다 (시작 상태는 남긴다). */
function stgPrune() {
  const g = S.stg;
  if (g.beat === 0) return;
  const beat = g.scene.beats[g.beat - 1];
  beat.bodies = beat.bodies.filter((b) => b.at || b.posture || b.facing || b.left != null || b.right != null || b.contacts.length || b.ends.length || b.memo);
}

function stgNewContactId() {
  const ids = new Set();
  [...S.stg.scene.start, ...S.stg.scene.beats.flatMap((x) => x.bodies)].forEach((b) => (b.contacts || []).forEach((c) => ids.add(c.id)));
  let k = 1;
  while (ids.has(`c${k}`)) k++;
  return `c${k}`;
}

// ----- 그리기 -----

const STG_COLORS = ['var(--pair-a)', 'var(--pair-b)', 'var(--ava-support)', 'var(--tension-mid)', 'var(--warm-deep)', 'var(--ava-minor)'];
const stgColor = (who) => STG_COLORS[Math.max(0, S.stg.scene.cast.indexOf(who)) % STG_COLORS.length];
const stgV = () => S.stg.view.vocab;

/** 평면도 비율: 방이 520 x 400 안에 들게. */
function stgScale(room) {
  const s = Math.min(440 / room.w, 320 / room.h);
  return { s, ox: 40, oy: 40, w: room.w * s + 80, h: room.h * s + 80 };
}

function stgPlanSvg(pos, ang, k) {
  const g = S.stg, room = g.room, sc = stgScale(room);
  const px = ([x, y]) => [sc.ox + x * sc.s, sc.oy + y * sc.s];
  const st = stageState(g.scene, k);
  const all = stageLayouts(room, g.scene, k), prev = k > 0 ? all[k - 1] : null, now = all[k];
  const flags = (g.check ? g.check.violations : []).filter((v) => v.beat === k);
  const bad = new Set(flags.map((v) => v.who)), badContact = new Set(flags.map((v) => v.contact).filter(Boolean));
  let out = '<defs><marker id="stg-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="var(--muted)"/></marker></defs>';
  out += `<rect class="stg-wall" x="${sc.ox}" y="${sc.oy}" width="${room.w * sc.s}" height="${room.h * sc.s}" rx="2"/>`;
  room.anchors.forEach((a) => {
    const [x, y] = px([a.x, a.y]);
    const [fx, fy] = stgFront(a.rot || 0);
    const cx = x + a.w * sc.s / 2, cy = y + a.h * sc.s / 2;
    const edit = g.mode === 'room';
    out += `<g class="stg-anchor ${esc(a.kind)}${edit ? ' edit' : ''}" data-stg-anchor="${esc(a.id)}"><rect x="${x}" y="${y}" width="${Math.max(a.w * sc.s, 4)}" height="${Math.max(a.h * sc.s, 4)}" rx="4"/>`;
    if (edit) out += `<path class="stg-front" d="M${cx} ${cy}L${cx + fx * 16} ${cy + fy * 16}"/>`;
    const thin = a.w * sc.s < 40 || a.h * sc.s < 18;
    // 문 · 창처럼 얇은 기준점은 이름을 벽 바깥(뒤쪽)에 쓴다
    out += `<text x="${thin ? cx - fx * 18 : cx}" y="${(thin ? cy - fy * 18 : cy) + 4}" text-anchor="middle">${esc(a.name)}</text></g>`;
  });
  Object.keys(st).forEach((w) => Object.values(st[w].contacts).forEach((c) => {
    if (!pos[w] || !pos[c.to]) return;
    const [x1, y1] = px(pos[w]), [x2, y2] = px(pos[c.to]);
    out += `<path class="stg-contact${badContact.has(c.id) ? ' bad' : ''}" d="M${x1} ${y1}L${x2} ${y2}" stroke="${stgColor(w)}"/>`;
  }));
  if (prev) Object.keys(now).forEach((w) => {
    if (!prev[w] || Math.hypot(prev[w][0] - now[w][0], prev[w][1] - now[w][1]) < 0.05) return;
    const [x1, y1] = px(prev[w]), [x2, y2] = px(now[w]);
    const d = Math.hypot(x2 - x1, y2 - y1), ux = (x2 - x1) / d, uy = (y2 - y1) / d;
    if (d > 44) out += `<path class="stg-move" d="M${x1 + ux * 20} ${y1 + uy * 20}L${x2 - ux * 22} ${y2 - uy * 22}"/>`;
  });
  out += stgGhostSvg(k, px);
  Object.keys(pos).forEach((w) => {
    const [x, y] = px(pos[w]);
    const name = charName(w);
    const post = stgV().postures[st[w].posture];
    let face = '';
    if (ang[w] != null) {
      const a = ang[w], p = (r, d) => `${x + Math.cos(a + r) * d} ${y + Math.sin(a + r) * d}`;
      face = `<path class="face" d="M${p(0, 26)}L${p(2.3, 13)}L${p(-2.3, 13)}Z" fill="${stgColor(w)}"/>`;
    }
    out += `<g class="stg-person${bad.has(w) ? ' bad' : ''}${w === g.who ? ' cur' : ''}" data-stg-who="${esc(w)}" tabindex="-1">${face}
      <circle class="body" cx="${x}" cy="${y}" r="16" fill="${stgColor(w)}"/><text class="ini" x="${x}" y="${y}">${esc(name.slice(0, 1))}</text>
      <text class="label" x="${x}" y="${y + 32}" text-anchor="middle">${esc(name)}${post ? ` · ${esc(post.label)}` : ''}</text></g>`;
  });
  return out;
}

/** 겹쳐 보기: 본문 장면 위에 이 박자에 견주는 계획 박자의 인물을 흐린 원으로. 계획 장면이 없으면 빈 글. */
function stgGhostSvg(k, px) {
  const g = S.stg;
  if (g.role !== 'text' || !g.ghost) return '';
  const row = stgRow(g, 'plan');
  const room = row && g.view.rooms.find((r) => r.id === row.scene.room);
  if (!room) return '';
  const pk = stagePlanBeat(g.check && g.check.match, k);
  const pos = stageLayouts(room, row.scene, pk)[pk];
  return Object.keys(pos).map((w) => {
    const [x, y] = px(pos[w]);
    return `<g class="stg-ghost" data-stg-ghost-who="${esc(w)}"><circle cx="${x}" cy="${y}" r="16" stroke="${stgColor(w)}"/><text x="${x}" y="${y}">${esc(charName(w).slice(0, 1))}</text></g>`;
  }).join('') + `<text class="stg-ghost-note" x="${px([0, 0])[0]}" y="${px([0, 0])[1] - 10}">흐린 원 = 계획 ${pk === 0 ? '시작 상태' : `${pk}박자`}</text>`;
}

function stgTarget(k) {
  const g = S.stg, st = stageState(g.scene, k), pos = stageLayouts(g.room, g.scene, k)[k], ang = {};
  Object.keys(pos).forEach((w) => {
    const v = stageFacing(st[w].facing, pos[w], g.room, pos);
    ang[w] = v ? Math.atan2(v[1], v[0]) : null;
  });
  return { pos, ang };
}

let stgShown = null;
let stgAnim = 0;
/** 평면도만 다시 그린다. from 이 있으면 박자 사이를 0.6초 보간한다 (위치와 향함만). */
function stgDrawPlan(from) {
  const svg = document.getElementById('stg-plan');
  const g = S.stg;
  if (!svg || !g || !g.scene || !g.room) return;
  const to = stgTarget(g.beat);
  cancelAnimationFrame(stgAnim);
  if (!from || matchMedia('(prefers-reduced-motion: reduce)').matches) {
    svg.innerHTML = stgPlanSvg(to.pos, to.ang, g.beat);
    stgShown = to;
    return;
  }
  const t0 = performance.now();
  const step = (t) => {
    const u = Math.min(1, (t - t0) / 600), e = u < 0.5 ? 2 * u * u : 1 - (-2 * u + 2) ** 2 / 2;
    const pos = {}, ang = {};
    Object.keys(to.pos).forEach((w) => {
      const a = from.pos[w] || to.pos[w];
      pos[w] = [a[0] + (to.pos[w][0] - a[0]) * e, a[1] + (to.pos[w][1] - a[1]) * e];
      if (to.ang[w] == null || from.ang[w] == null) ang[w] = to.ang[w];
      else {
        const d = Math.atan2(Math.sin(to.ang[w] - from.ang[w]), Math.cos(to.ang[w] - from.ang[w]));
        ang[w] = from.ang[w] + d * e;
      }
    });
    svg.innerHTML = stgPlanSvg(pos, ang, g.beat);
    stgShown = { pos, ang };
    if (u < 1) stgAnim = requestAnimationFrame(step);
  };
  stgAnim = requestAnimationFrame(step);
}

const STG_POSE_SVG = {
  stand: '<circle cx="17" cy="6" r="3.5"/><path d="M17 10v14M17 14l-6 6M17 14l6 6M17 24l-4 12M17 24l4 12"/>',
  walk: '<circle cx="18" cy="6" r="3.5"/><path d="M17 10l-1 14M16 14l-6 4M16 14l7 5M16 24l-6 11M16 24l6 10"/>',
  run: '<circle cx="21" cy="6" r="3.5"/><path d="M19 10l-4 13M18 14l-8 2M18 14l7 6M15 23l-9 7M15 23l8 4l-2 7"/>',
  lean: '<path d="M30 4v34"/><circle cx="22" cy="7" r="3.5"/><path d="M23 11l-3 13M22 15l6 3M22 15l-6 5M20 24l-5 12M20 24l1 12"/>',
  chair: '<circle cx="14" cy="8" r="3.5"/><path d="M14 12v12M14 16l7 4M14 24h10v12M8 22v14"/>',
  floor: '<circle cx="12" cy="12" r="3.5"/><path d="M12 16v14M12 20l7 5M12 30h12l4 4"/>',
  squat: '<circle cx="16" cy="10" r="3.5"/><path d="M16 14l-2 11M15 18l8 3M14 25l8-2l-1 13M14 25l-3 11"/>',
  kneel: '<circle cx="16" cy="6" r="3.5"/><path d="M16 10v14M16 14l-6 6M16 14l6 6M16 24v10h10M16 34l-6 2"/>',
  lie: '<circle cx="5" cy="30" r="3.5"/><path d="M9 30h14M13 30l4-5M13 30l4 5M23 30l9-2M23 30l9 3"/>',
  side: '<circle cx="5" cy="28" r="3.5"/><path d="M9 29h13M13 29l2-6M22 29l5 4l5-2M22 29l9 1"/>',
  prone: '<circle cx="5" cy="31" r="3.5"/><path d="M9 32h14M12 32l-2 4M14 32l2 4M23 32l9 1M23 32l9 3"/>',
  held: '<circle cx="10" cy="14" r="3.5"/><path d="M13 16l10 4M18 18l-2 8M23 20l6-6M23 20l7 6M27 4v32"/>',
};

// 부위 도식의 점 (56 x 118 실루엣). 화면에서 누르면 접촉 부위로 고른다. 도식에 없는 부위는 목록에서 고른다
const STG_DOTS = {
  front: { head: [28, 9], forehead: [28, 7], cheek_l: [33, 14], cheek_r: [23, 14], lips: [28, 18], neck: [28, 25], shoulder_l: [40, 31], shoulder_r: [16, 31],
    chest: [28, 38], belly: [28, 54], upper_arm_l: [44, 42], upper_arm_r: [12, 42], wrist_l: [47, 62], wrist_r: [9, 62], hand_l: [48, 70], hand_r: [8, 70],
    groin: [28, 72], thigh_l: [33, 82], thigh_r: [23, 82], knee_l: [33, 96], knee_r: [23, 96], foot_l: [34, 114], foot_r: [22, 114] },
  back: { hair: [28, 8], nape: [28, 24], back: [28, 40], waist: [28, 56], buttocks: [28, 68], calf_l: [23, 104], calf_r: [33, 104] },
};
const STG_SIL = '<path class="sil" d="M28 1a9 9 0 1 1 0 18a9 9 0 1 1 0-18M18 22h20l6 6l5 36h-6l-4-28v28l2 50h-9l-2-38h-4l-2 38h-9l2-50v-28l-4 28h-6l5-36z"/>';

function stgBodyMap(on, by, minor) {
  const parts = stgV().parts;
  const dots = (side) => Object.entries(STG_DOTS[side]).filter(([id]) => !(minor && parts[id].sexual)).map(([id, [x, y]]) =>
    `<circle class="dot${on.includes(id) ? ' on' : ''}${by.includes(id) ? ' by' : ''}" cx="${x}" cy="${y}" r="4" data-action="stgPart" data-arg="${id}" role="button" aria-label="${esc(parts[id].label)}"><title>${esc(parts[id].label)}</title></circle>`).join('');
  return `<div class="stg-bodymap"><figure><svg viewBox="0 0 56 120">${STG_SIL}${dots('front')}</svg><figcaption>앞</figcaption></figure>
    <figure><svg viewBox="0 0 56 120">${STG_SIL}${dots('back')}</svg><figcaption>뒤</figcaption></figure></div>`;
}

const stgOpt = (v, label, cur) => `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(label)}</option>`;

/** 자리 · 향함 고르기에 쓰는 이름. */
function stgSpotLabel(at) {
  if (!at) return '모름';
  const g = S.stg, rel = stgV().rels[at.rel] || at.rel;
  if (at.ref.startsWith('@')) return `${charName(at.ref.slice(1))} · ${rel}`;
  const a = g.room.anchors.find((x) => x.id === at.ref);
  return `${a ? a.name : at.ref} · ${rel}`;
}

function stgFacingLabel(f) {
  if (!f) return '모름';
  if (f.startsWith('@')) return `${charName(f.slice(1))} 쪽`;
  if (f.startsWith('#')) { const a = S.stg.room.anchors.find((x) => x.id === f.slice(1)); return `${a ? a.name : f} 쪽`; }
  return stgV().facings[f] || f;
}

function stgPersonCard() {
  const g = S.stg, w = g.who;
  if (!w) return '<section class="card tight"><p class="small">출연진을 더하면 인물 칸이 보여요.</p></section>';
  const v = stgV();
  const st = stageState(g.scene, g.beat)[w];
  const own = stgBody(w, false);
  const mark = (field) => (g.beat === 0 ? '' : own && own[field] != null && own[field] !== '' ? `<button type="button" class="btn small ghost stg-keep" data-action="stgKeep" data-arg="${field}" title="이 박자에서 바꾼 것을 지우고 앞 박자 그대로 둬요">앞 그대로로</button>` : '<span class="small">앞 그대로</span>');
  const others = g.scene.cast.filter((x) => x !== w);
  const at = st.at;
  const spotOpts = [stgOpt('', '모름', at ? null : '')]
    .concat(g.room.anchors.map((a) => `<optgroup label="${esc(a.name)}">${Object.entries(v.rels).map(([r, l]) => stgOpt(`${a.id}|${r}`, `${a.name} · ${l}`, at && `${at.ref}|${at.rel}`)).join('')}</optgroup>`))
    .concat(others.map((o) => `<optgroup label="${esc(charName(o))}">${['front', 'back', 'left', 'right', 'across', 'against', 'on'].map((r) => stgOpt(`@${o}|${r}`, `${charName(o)} · ${v.rels[r]}`, at && `${at.ref}|${at.rel}`)).join('')}</optgroup>`)).join('');
  const faceOpts = [stgOpt('', '모름', st.facing)].concat(others.map((o) => stgOpt(`@${o}`, `${charName(o)} 쪽`, st.facing)))
    .concat(g.room.anchors.map((a) => stgOpt(`#${a.id}`, `${a.name} 쪽`, st.facing)))
    .concat(Object.entries(v.facings).map(([k, l]) => stgOpt(k, `방 ${l}`, st.facing))).join('');
  const hand = (side) => {
    const val = st[side] === STG_UNKNOWN ? '' : st[side];
    return `<input id="stg-${side}" data-stg-field="${side}" value="${esc(val)}" placeholder="${st[side] === STG_UNKNOWN ? '모름 (비우면 빈손)' : '빈손'}" aria-label="${side === 'left' ? '왼손' : '오른손'}에 쥔 것">`;
  };
  const minors = new Set(g.view.minors);
  const actives = [];
  Object.entries(stageState(g.scene, g.beat)).forEach(([who, s]) => Object.values(s.contacts).forEach((c) => {
    if (who === w || c.to === w) actives.push({ who, c, at: s.contact_at[c.id] });
  }));
  const byLabel = (c) => v.hands[c.by] || (v.parts[c.by] ? v.parts[c.by].label : c.by);
  const contactRows = actives.map(({ who, c, at: k }) => `<li class="between"><span><b>${esc(charName(who))}</b> ${esc(byLabel(c))} → <b>${esc(charName(c.to))}</b> ${esc((v.parts[c.part] || {}).label || c.part)} · ${esc((v.acts[c.act] || {}).label || c.act)}
      <span class="small">${k === g.beat ? '이 박자에 시작' : k === 0 ? '시작 상태부터' : `${k}박자부터`}</span></span>
      ${who === w ? `<button type="button" class="btn small ghost" data-action="stgEnd" data-arg="${esc(c.id)}">${k === g.beat ? '빼기' : '끝내기'}</button>` : ''}</li>`).join('');
  const f = g.form;
  const to = f.to && others.includes(f.to) ? f.to : others[0] || '';
  const minor = minors.has(w) || minors.has(to);
  const parts = Object.entries(v.parts).filter(([, p]) => !(minor && p.sexual));
  const actsShown = Object.entries(v.acts).filter(([, a]) => !(minor && a.sexual));
  const on = actives.filter((x) => x.c.to === w).map((x) => x.c.part);
  const by = actives.filter((x) => x.who === w).map((x) => x.c.by);
  const form = others.length ? `<div class="stg-add">
      <label><span class="small">무엇으로</span><select data-stg-form="by">${Object.entries(v.hands).map(([k, l]) => stgOpt(k, l, f.by)).join('')}${['lips', 'forehead', 'head', 'shoulder_l', 'shoulder_r', 'chest', 'back'].map((k) => stgOpt(k, v.parts[k].label, f.by)).join('')}</select></label>
      <label><span class="small">누구에게</span><select data-stg-form="to">${others.map((o) => stgOpt(o, charName(o), to)).join('')}</select></label>
      <label><span class="small">어디를</span><select data-stg-form="part">${stgOpt('', '부위 고르기', f.part)}${parts.map(([k, p]) => stgOpt(k, p.label, f.part)).join('')}</select></label>
      <label><span class="small">어떻게</span><select data-stg-form="act">${actsShown.map(([k, a]) => stgOpt(k, a.label, f.act)).join('')}</select></label>
      <button type="button" class="btn small" data-action="stgAddContact"${f.part ? '' : ' disabled'}>+ 접촉 더하기</button></div>
      ${minor ? '<p class="small">미성년 인물이 있어 성적인 부위 · 동작은 고를 수 없어요.</p>' : ''}` : '<p class="small">다른 인물이 있어야 접촉을 더할 수 있어요.</p>';
  return `<section class="card stg-pcard" aria-label="${esc(charName(w))} 상태">
    <div class="between"><h2 style="color:${stgColor(w)}">${esc(charName(w))}</h2><span class="small">${g.beat === 0 ? '시작 상태' : `${g.beat}박자`}</span></div>
    <div class="between"><span class="small">자세</span>${mark('posture')}</div>
    <div class="stg-poses" role="group" aria-label="자세">${Object.entries(v.postures).map(([id, p]) => `<button type="button" aria-pressed="${st.posture === id}" data-action="stgPosture" data-arg="${id}"><svg viewBox="0 0 34 40" aria-hidden="true">${STG_POSE_SVG[id] || ''}</svg>${esc(p.label)}</button>`).join('')}</div>
    <div class="stg-fields">
      <label for="stg-at">자리</label><span class="row"><select id="stg-at" data-stg-field="at">${spotOpts}</select>${mark('at')}</span>
      <label for="stg-facing">향함</label><span class="row"><select id="stg-facing" data-stg-field="facing">${faceOpts}</select>${mark('facing')}</span>
      <label for="stg-left">왼손</label><span class="row">${hand('left')}${mark('left')}</span>
      <label for="stg-right">오른손</label><span class="row">${hand('right')}${mark('right')}</span>
    </div>
    <div class="stg-touch">${stgBodyMap(on.concat(f.part ? [f.part] : []), by, minor)}
      <div class="stg-stack"><h3>접촉</h3>${contactRows ? `<ul class="stg-contacts">${contactRows}</ul>` : '<p class="small">지금 닿아 있는 곳이 없어요. 부위 점을 누르거나 아래에서 골라 더해요.</p>'}${form}</div></div>
    <label class="stg-stack" style="gap:4px"><span class="small">메모 (목록 밖의 것)</span><input data-stg-field="memo" value="${esc(own ? own.memo : '')}" placeholder="예: 손에 힘을 주지 못함"></label>
  </section>`;
}

function stgBeats() {
  const g = S.stg, sc = g.scene;
  const viol = g.check ? g.check.violations : [];
  const stale = new Set(g.check ? g.check.stale : []);
  const differ = new Set(stgGaps().map((x) => x.k));
  const row = (k) => {
    const b = k === 0 ? null : sc.beats[k - 1];
    const who = k === 0 ? sc.cast : [...new Set(b.bodies.map((x) => x.who))];
    const text = k === 0 ? '시작 상태' : b.quote || b.note || '(빈 박자)';
    const flags = viol.filter((x) => x.beat === k);
    return `<li><button type="button" aria-current="${k === g.beat}" data-action="stgBeat" data-arg="${k}">
      <span class="no">${k === 0 ? '○' : k}</span><span class="q${b && !b.quote ? ' note' : ''}">${esc(text)}</span>
      <span class="who">${who.map((w) => `<span class="chip" style="color:${stgColor(w)}">${esc(charName(w))}</span>`).join('')}${flags.length ? `<span class="flag">⚠ ${flags.length}</span>` : ''}${stale.has(k) ? '<span class="flag amber">본문과 달라요</span>' : ''}${differ.has(k) ? '<span class="flag plan">계획과 달라요</span>' : ''}</span></button></li>`;
  };
  const cur = g.beat > 0 ? sc.beats[g.beat - 1] : null;
  const edit = cur ? `<div class="stg-beat-edit">
      <label class="stg-stack" style="gap:4px"><span class="small">본문 문장 (쓴 뒤에 이어요)</span><input data-stg-beat="quote" value="${esc(cur.quote)}" placeholder="본문에서 이 박자에 해당하는 문장 하나"></label>
      <label class="stg-stack" style="gap:4px"><span class="small">한 줄 설명</span><input data-stg-beat="note" value="${esc(cur.note)}" placeholder="예: 도윤이 문을 열고 들어온다"></label>
      <div class="row"><button type="button" class="btn small ghost" data-action="stgBeatMove" data-arg="-1"${g.beat > 1 ? '' : ' disabled'}>↑ 위로</button><button type="button" class="btn small ghost" data-action="stgBeatMove" data-arg="1"${g.beat < sc.beats.length ? '' : ' disabled'}>↓ 아래로</button><button type="button" class="btn small ghost danger" data-action="stgBeatDrop">박자 지우기</button></div></div>` : '';
  return `<section class="card tight"><div class="between"><h2>박자</h2><button type="button" class="btn small" data-action="stgBeatAdd">+ 박자</button></div>
    <ol class="stg-beats">${[0, ...sc.beats.map((_, i) => i + 1)].map(row).join('')}</ol>${edit}
    <div class="stg-cast"><span class="small">출연진</span>${sc.cast.map((w) => `<span class="chip stg-who${w === g.who ? ' cur' : ''}"><button type="button" class="linkish" data-action="stgWho" data-arg="${esc(w)}" aria-pressed="${w === g.who}" style="color:${stgColor(w)}">${esc(charName(w))}</button><button type="button" class="linkish" data-action="stgCastDrop" data-arg="${esc(w)}" aria-label="${esc(charName(w))} 빼기">✕</button></span>`).join('')}
      ${(() => { const rest = P().characters.filter((c) => !sc.cast.includes(c.id)); return rest.length ? `<select data-stg-cast aria-label="출연진 더하기"><option value="">+ 인물 더하기</option>${rest.map((c) => stgOpt(c.id, c.name, '')).join('')}</select>` : ''; })()}</div>
  </section>`;
}

/** 계획과 다른 곳을 지금 역할의 박자 번호(k)와 함께. */
function stgGaps() {
  const g = S.stg;
  return (g.check && g.check.gaps || []).map((x) => ({ ...x, k: g.role === 'text' ? x.text_beat : x.plan_beat }));
}

function stgRoomPanel() {
  const g = S.stg, r = g.room;
  const kinds = { bed: '침대', door: '문', window: '창', desk: '책상', chair: '의자', sofa: '소파', table: '탁자', wall: '벽', seat: '자리', other: '기타' };
  const used = g.view.scenes.filter((x) => x.scene.room === r.id && x.scene.id !== g.sid).length;
  return `<section class="card tight"><div class="between"><h2>방 고치기</h2><span class="small">${used ? `이 방을 쓰는 다른 장면 ${used}개도 바뀌어요` : ''}</span></div>
    <div class="stg-fields">
      <label for="stg-rname">이름</label><input id="stg-rname" data-stg-room="name" value="${esc(r.name)}">
      <label for="stg-rplace">장소</label><input id="stg-rplace" data-stg-room="place" value="${esc(r.place)}" list="stg-places" placeholder="지도 장소에 묶으면 다른 장면에서도 골라요">
      <label for="stg-rw">크기 (m)</label><span class="row"><input id="stg-rw" type="number" min="1" max="40" step="0.1" data-stg-room="w" value="${r.w}" aria-label="가로" style="width:80px"> × <input type="number" min="1" max="40" step="0.1" data-stg-room="h" value="${r.h}" aria-label="세로" style="width:80px"></span>
    </div>
    <datalist id="stg-places">${stgPlaces().map((x) => `<option value="${esc(x)}">`).join('')}</datalist>
    <p class="small">평면도에서 기준점을 끌어 옮겨요. 짧은 선이 기준점의 앞쪽이에요.</p>
    <ul class="stg-anchors">${r.anchors.map((a) => `<li class="row"><input data-stg-anchor-name="${esc(a.id)}" value="${esc(a.name)}" aria-label="기준점 이름" style="width:120px">
      <select data-stg-anchor-kind="${esc(a.id)}" aria-label="종류">${Object.entries(kinds).map(([k, l]) => stgOpt(k, l, a.kind)).join('')}</select>
      <button type="button" class="btn small ghost" data-action="stgRotate" data-arg="${esc(a.id)}" title="앞쪽을 90도 돌려요">↻ 돌리기</button>
      <button type="button" class="btn small ghost danger" data-action="stgAnchorDrop" data-arg="${esc(a.id)}">빼기</button></li>`).join('')}</ul>
    <button type="button" class="btn small" data-action="stgAnchorAdd">+ 기준점</button></section>`;
}

function stgPlaces() {
  const p = P();
  const names = (p.elements || []).filter((el) => el.kind === '장소').map((el) => el.name);
  (p.world.locations || []).forEach((x) => names.push(String(x).split(/[:：\-–—,(]/)[0].trim()));
  return [...new Set(names.filter(Boolean))];
}

function stgNewCard() {
  const g = S.stg, k = g.pick;
  const rooms = g.view.rooms;
  const tpl = Object.entries(g.view.vocab.rooms);
  return `<section class="card"><h2>이 사건에는 아직 연출이 없어요</h2>
    <p class="desc">방을 고르면 이 화 플롯의 등장 인물이 문 앞에 선 채로 시작해요. 같은 장소의 방은 다른 장면에서도 다시 써요.</p>
    <fieldset class="stg-pick"><legend class="small">방</legend>
      ${rooms.map((r) => `<label class="row"><input type="radio" name="stg-room" value="${esc(r.id)}" data-stg-pick="room"${k.room === r.id ? ' checked' : ''}> ${esc(r.name)}${r.place ? ` <span class="chip confirmed">${esc(r.place)}</span>` : ''}</label>`).join('')}
      <label class="row"><input type="radio" name="stg-room" value="" data-stg-pick="room"${k.room ? '' : ' checked'}> 새 방:
        <select data-stg-pick="template" aria-label="방 틀">${tpl.map(([t, l]) => stgOpt(t, l, k.template)).join('')}</select>
        <input data-stg-pick="name" value="${esc(k.name)}" placeholder="방 이름 (비우면 틀 이름)" aria-label="새 방 이름"></label>
    </fieldset>
    <div class="row"><button type="button" class="btn primary" data-action="stgCreate">장면 만들기</button></div></section>`;
}

// ----- AI 장면: 플롯에서 초안 · 본문에서 뽑기, 비교 · 적용 · 적용 취소 -----

/** 작은 평면도: 장면이 끝난 상태 (비교 보기). 인물 원과 이름, 접촉 선만. */
function stgMiniSvg(room, scene) {
  if (!room) return '<p class="small">방을 찾지 못했어요.</p>';
  const sc = stgScale(room), k = scene.beats.length;
  const px = ([x, y]) => [sc.ox + x * sc.s, sc.oy + y * sc.s];
  const st = stageState(scene, k), pos = stageLayouts(room, scene, k)[k];
  const color = (w) => STG_COLORS[Math.max(0, scene.cast.indexOf(w)) % STG_COLORS.length];
  let out = `<rect class="stg-wall" x="${sc.ox}" y="${sc.oy}" width="${room.w * sc.s}" height="${room.h * sc.s}" rx="2"/>`;
  room.anchors.forEach((a) => {
    const [x, y] = px([a.x, a.y]);
    out += `<g class="stg-anchor ${esc(a.kind)}"><rect x="${x}" y="${y}" width="${Math.max(a.w * sc.s, 4)}" height="${Math.max(a.h * sc.s, 4)}" rx="4"/><text x="${x + a.w * sc.s / 2}" y="${y + a.h * sc.s / 2 + 4}" text-anchor="middle">${esc(a.name)}</text></g>`;
  });
  Object.keys(st).forEach((w) => Object.values(st[w].contacts).forEach((c) => {
    if (!pos[w] || !pos[c.to]) return;
    const [x1, y1] = px(pos[w]), [x2, y2] = px(pos[c.to]);
    out += `<path class="stg-contact" d="M${x1} ${y1}L${x2} ${y2}" stroke="${color(w)}"/>`;
  }));
  Object.keys(pos).forEach((w) => {
    const [x, y] = px(pos[w]);
    out += `<g class="stg-person"><circle class="body" cx="${x}" cy="${y}" r="16" fill="${color(w)}"/><text class="ini" x="${x}" y="${y}">${esc(charName(w).slice(0, 1))}</text><text class="label" x="${x}" y="${y + 32}" text-anchor="middle">${esc(charName(w))}</text></g>`;
  });
  return `<svg viewBox="0 0 ${sc.w} ${sc.h}" role="img" aria-label="${esc(room.name)} 평면도, 끝난 상태">${out}</svg>`;
}

/** 박자 글 목록. other 에 없는 글은 표시한다 (박자 목록 차이). */
function stgBeatList(scene, other) {
  const text = (b) => b.quote || b.note || '(빈 박자)';
  const have = new Set((other ? other.beats : []).map(text));
  return `<ol class="stg-cmp-beats">${scene.beats.map((b) => `<li${other && !have.has(text(b)) ? ' class="new"' : ''}>${esc(text(b))}</li>`).join('') || '<li class="small">박자가 없어요</li>'}</ol>`;
}

/** 검토를 기다리는 AI 장면을 지금 장면과 나란히 (통째로 적용하거나 버린다). */
function stgCompare(prop) {
  const g = S.stg;
  const cur = g.scene;
  const room = prop.room || g.view.rooms.find((r) => r.id === prop.scene.room) || null;
  const from = prop.role === 'text' ? '본문에서 뽑은 장면' : '플롯에서 받은 초안';
  const notes = [];
  if (prop.dropped) notes.push(`미성년 인물이 낀 성적 접촉 ${prop.dropped}개를 뺐어요.`);
  if (prop.violations.length) notes.push(`규칙 검수 ${prop.violations.length}개: ${prop.violations.slice(0, 3).map((v) => `${v.beat}박자 ${v.text}`).join(' · ')}`);
  if (prop.stale.length) notes.push(`본문에 없는 문장을 가리키는 박자 ${prop.stale.length}개`);
  prop.notes.filter((x) => !/성적 접촉/.test(x)).forEach((x) => notes.push(x));
  return `<section class="card stg-cmp" aria-label="AI 장면 비교"><div class="between"><h2>${from} 비교</h2>
      <div class="row"><button type="button" class="btn small primary" data-action="stgApply">${cur ? '이 장면으로 바꾸기' : '적용'}</button><button type="button" class="btn small ghost" data-action="stgDiscard">버리기</button></div></div>
    <p class="small">장면을 통째로 바꿔요. 바꾼 뒤에도 '적용 취소'로 한 번 되돌릴 수 있어요.${prop.room ? ` 새 방 '${esc(prop.room.name)}'도 만들어요.` : ''}</p>
    ${notes.length ? `<ul class="stg-viol small">${notes.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
    <div class="stg-cmp-grid"><div><h3>지금 장면</h3>${cur ? stgMiniSvg(g.room, cur) + stgBeatList(cur, prop.scene) : '<p class="small">아직 없어요</p>'}</div>
      <div><h3>AI 장면</h3>${stgMiniSvg(room, prop.scene)}${stgBeatList(prop.scene, cur)}</div></div></section>`;
}

/** 머리의 AI 버튼: 계획이면 플롯에서 초안, 본문이면 본문에서 뽑기. */
function stgAiBtn() {
  const g = S.stg, e = ep(g.n);
  if (g.role === 'text') {
    const b = jobBtn('stage_extract', g.n, '✦ 본문에서 뽑기');
    return e && e.text ? `<button type="button" class="btn small" data-action="stgAi"${b.attr}>${b.label}</button>` : '<span class="small">본문을 쓴 뒤 뽑아요</span>';
  }
  const b = jobBtn('stage_draft', g.n, '✦ 플롯에서 초안');
  return `<button type="button" class="btn small" data-action="stgAi"${b.attr}>${b.label}</button>`;
}

/** 작업이 끝나면 장면 연출 화면을 다시 받는다 (app.js applyJobResult). 검수도 본문 장면을 넣었을 수 있다. */
function stageJobResult(j) {
  if (S.stg && S.stg.n === j.ep && S.route[2] === 'stage') stgLoad(j.ep, S.stg.ev).then(() => render());
}

Object.assign(JOB_DONE_MSG, {
  stage_draft: (j) => `${j.ep}화 사건 ${(j.result ? j.result.event : 0) + 1} 연출 초안이 왔어요. 장면 연출에서 비교해 보세요`,
  stage_extract: (j) => `${j.ep}화 사건 ${(j.result ? j.result.event : 0) + 1} 본문 연출을 뽑았어요. 장면 연출에서 비교해 보세요`,
});
Object.assign(JOB_PAGES, { stage_draft: ['stage'], stage_extract: ['stage'] });
Object.assign(JOB_LINK, {
  stage_draft: (j) => `#/p/${enc(j.project)}/stage/${j.ep}/${(j.result ? j.result.event : 0) + 1}`,
  stage_extract: (j) => `#/p/${enc(j.project)}/stage/${j.ep}/${(j.result ? j.result.event : 0) + 1}`,
});

function stgCss() {
  if (document.getElementById('stg-css')) return;
  const st = document.createElement('style');
  st.id = 'stg-css';
  st.textContent = `
.stg-cmp { gap: 10px; }
.stg-cmp-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; }
@media (max-width: 700px) { .stg-cmp-grid { grid-template-columns: minmax(0, 1fr); } }
.stg-cmp-grid h3 { margin: 0 0 6px; font-size: 14px; }
.stg-cmp-grid svg { width: 100%; height: auto; display: block; background: var(--canvas); border-radius: 8px; }
.stg-cmp-beats { margin: 8px 0 0; padding-left: 20px; font-size: 13px; }
.stg-cmp-beats li.new { background: var(--warm-soft, rgba(255, 200, 0, .12)); }
.stg-wrap { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(320px, 1fr); gap: 20px; align-items: start; }
@media (max-width: 1100px) { .stg-wrap { grid-template-columns: minmax(0, 1fr); } }
.stg-planc { padding: 16px; gap: 12px; }
.stg-planc svg { width: 100%; height: auto; display: block; background: var(--canvas); border-radius: 8px; touch-action: none; user-select: none; }
.stg-wall { fill: none; stroke: var(--text-2); stroke-width: 4; }
.stg-anchor rect { fill: var(--chip); stroke: var(--line-strong); stroke-width: 1; }
.stg-anchor.door rect, .stg-anchor.window rect { fill: var(--accent-soft); }
.stg-anchor.edit { cursor: grab; }
.stg-anchor text { font-size: 12px; fill: var(--text-2); font-family: var(--sans); pointer-events: none; }
.stg-front { stroke: var(--accent); stroke-width: 2.5; }
.stg-person { cursor: grab; }
.stg-person circle.body { stroke: var(--surface); stroke-width: 2.5; }
.stg-person.cur circle.body { stroke: var(--text); }
.stg-person.bad circle.body { stroke: var(--red); stroke-width: 3; }
.stg-person .ini { font-size: 13px; font-weight: 700; fill: var(--on-accent); font-family: var(--sans); text-anchor: middle; dominant-baseline: central; pointer-events: none; }
.stg-person .label { fill: var(--text); font-size: 12px; font-weight: 700; font-family: var(--sans); pointer-events: none; }
.stg-person .face { opacity: 0.85; }
.stg-contact { stroke-width: 2.5; stroke-dasharray: 5 4; fill: none; }
.stg-contact.bad { stroke: var(--red); }
.stg-move { stroke: var(--muted); stroke-width: 1.5; fill: none; marker-end: url(#stg-arrow); }
.stg-play { display: flex; align-items: center; gap: 12px; }
.stg-play input[type=range] { flex: 1; accent-color: var(--accent); }
.stg-beats { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 4px; max-height: 360px; overflow-y: auto; }
.stg-beats button { width: 100%; text-align: left; min-height: 48px; padding: 8px 10px; border: 1px solid transparent; border-radius: 8px; background: transparent; color: var(--text); font: inherit; cursor: pointer; display: grid; grid-template-columns: 28px 1fr; gap: 2px 8px; }
.stg-beats button:hover { background: var(--bg); }
.stg-beats button[aria-current="true"] { background: var(--sel-bg); border-color: var(--sel-line); }
.stg-beats .no { grid-row: span 2; width: 24px; height: 24px; border-radius: 6px; background: var(--chip); display: flex; align-items: center; justify-content: center; font-size: 0.75rem; font-weight: 700; }
.stg-beats .q { font-family: var(--serif); line-height: 1.5; }
.stg-beats .q.note { font-family: var(--sans); color: var(--text-2); }
.stg-beats .who { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.stg-beats .flag { color: var(--red); font-weight: 700; font-size: 0.75rem; }
.stg-beats .flag.amber { color: var(--amber-ink); }
.stg-beats .flag.plan { color: var(--accent-ink); }
.stg-ghost circle { fill: none; stroke-width: 2; stroke-dasharray: 3 3; opacity: 0.55; }
.stg-ghost text { font-size: 12px; font-weight: 700; fill: var(--muted); font-family: var(--sans); text-anchor: middle; dominant-baseline: central; opacity: 0.8; }
.stg-ghost-note { font-size: 11px; fill: var(--muted); font-family: var(--sans); }
.stg-head { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; justify-content: space-between; }
.stg-beat-edit, .stg-stack { display: flex; flex-direction: column; gap: 8px; }
.stg-beat-edit { padding-top: 8px; border-top: 1px solid var(--line); }
.stg-cast { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding-top: 8px; border-top: 1px solid var(--line); }
.stg-who { gap: 6px; }
.stg-who.cur { background: var(--accent-soft); }
.linkish { border: 0; background: none; padding: 0; font: inherit; cursor: pointer; color: inherit; }
.stg-pcard { padding: 14px 16px; gap: 12px; }
.stg-poses { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 4px; }
.stg-poses button { padding: 4px 2px 2px; border: 1px solid transparent; border-radius: 8px; background: var(--bg); color: var(--text-2); font: inherit; font-size: 0.6875rem; cursor: pointer; display: flex; flex-direction: column; align-items: center; gap: 2px; min-height: 58px; }
.stg-poses button[aria-pressed="true"] { border-color: var(--accent); background: var(--accent-soft); color: var(--accent-ink); font-weight: 700; }
.stg-poses svg { width: 34px; height: 40px; }
.stg-poses svg * { stroke: currentColor; stroke-width: 2.4; stroke-linecap: round; fill: none; }
.stg-fields { display: grid; grid-template-columns: 64px 1fr; gap: 6px 10px; align-items: center; font-size: 0.8125rem; }
.stg-fields > label { color: var(--muted); }
.stg-fields select, .stg-fields input:not([type=number]) { min-width: 0; flex: 1; }
.stg-touch { display: grid; grid-template-columns: 124px 1fr; gap: 12px; align-items: start; }
@media (max-width: 480px) { .stg-touch { grid-template-columns: 1fr; } .stg-poses { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
.stg-bodymap { display: flex; gap: 6px; }
.stg-bodymap figure { margin: 0; }
.stg-bodymap svg { width: 56px; height: 120px; }
.stg-bodymap .sil { fill: var(--chip); stroke: var(--line-strong); stroke-width: 1; }
.stg-bodymap .dot { fill: var(--surface); stroke: var(--line-strong); stroke-width: 1; cursor: pointer; }
.stg-bodymap .dot.on { fill: var(--pair-b); stroke: var(--pair-b); }
.stg-bodymap .dot.by { fill: var(--pair-a); stroke: var(--pair-a); }
.stg-bodymap figcaption { font-size: 0.6875rem; color: var(--muted); text-align: center; }
.stg-contacts { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; font-size: 0.8125rem; }
.stg-add { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
.stg-add label { display: flex; flex-direction: column; gap: 2px; }
.stg-add button { grid-column: 1 / -1; }
.stg-anchors { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
.stg-events { display: flex; flex-wrap: wrap; gap: 6px; }
.stg-events a { text-decoration: none; }
.stg-events a[aria-current="page"] .chip { background: var(--accent); color: var(--on-accent); }
.stg-pick { border: 0; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 8px; }
.stg-legend { display: flex; flex-wrap: wrap; gap: 12px; font-size: 0.75rem; color: var(--muted); }
.stg-tabs { display: none; }
@media (max-width: 900px) { .stg-tabs { display: flex; } .stg-pane[data-hide] { display: none; } }
`;
  document.head.appendChild(st);
}

function viewStage(n) {
  stgCss();
  const g = S.stg;
  const e = ep(n);
  const head = (desc, right = '') => header(`작품 도구 · ${n}화${g ? ` · 사건 ${g.ev} / ${(e && e.plot.events.length) || 0}` : ''}`, '장면 연출', desc, right);
  const eps = P().episodes.filter((x) => x.plot.events.length);
  const epPick = `<label class="row small">화 <select data-stg-ep aria-label="화 고르기">${eps.map((x) => stgOpt(String(x.plot.number), `${x.plot.number}화 ${x.plot.title}`, String(n))).join('')}</select></label>`;
  if (!e || !g) return `${head('방 하나 안에서 인물의 자리 · 자세 · 접촉을 박자마다 짜고 재생해요.')}<section class="card">${eps.length ? epPick : ''}<p class="small">${eps.length ? '사건이 있는 화를 고르세요.' : '플롯에 사건이 있는 화가 아직 없어요. 기승전결 · 플롯에서 사건을 적으면 사건마다 연출을 짤 수 있어요.'}</p></section>`;
  const has = new Set(g.view.scenes.map((x) => x.event));
  const events = `<nav class="stg-events" aria-label="사건">${e.plot.events.map((x, k) => `<a href="${base()}/stage/${n}/${k + 1}"${k + 1 === g.ev ? ' aria-current="page"' : ''} title="${esc(x)}"><span class="chip">${k + 1}${has.has(k) ? ' ●' : ''}</span></a>`).join('')}</nav>`;
  const evText = e.plot.events[g.ev - 1] || '';
  const has2 = (role) => !!stgRow(g, role);
  const roles = `<div class="seg" role="group" aria-label="장면 역할">${[['plan', '계획'], ['text', '본문']].map(([r, l]) => `<button type="button" aria-pressed="${g.role === r}" data-action="stgRole" data-arg="${r}" title="${r === 'plan' ? '쓰기 전에 짠 장면' : '본문에서 뽑은 장면'}">${l}${has2(r) ? ' ●' : ''}</button>`).join('')}</div>`;
  const pickBar = `<section class="card tight"><div class="stg-head">${epPick}${events}${roles}</div></section>`;
  if (!evText) return `${head('')}<section class="card">${epPick}${events}<p class="small">${g.ev}번째 사건이 없어요.</p></section>`;
  const prop = stgProposal(g);
  const cmp = prop ? stgCompare(prop) : '';
  if (!g.scene && g.role === 'text') return `${head(esc(evText), stgAiBtn())}${pickBar}${cmp}<section class="card"><h2>본문에서 뽑기 전이에요</h2>
    <p class="desc">본문 장면은 본문에서 자리 · 자세 · 접촉을 뽑은 결과예요. 뽑으면 여기서 규칙으로 판정하고 계획 장면과 견줘요. 검수할 때도 함께 뽑아요(검수 화면의 '검수 때 함께 뽑기').${has2('plan') ? '' : ' 이 사건에는 계획 장면도 아직 없어요.'}</p></section>`;
  if (!g.scene) return `${head(esc(evText), stgAiBtn())}${pickBar}${cmp}${stgNewCard()}`;
  const ck = g.check || { violations: [], stale: [], event_changed: false };
  const save = `<button type="button" class="btn small primary" data-action="stgSave"${g.dirty ? '' : ' disabled'}>${g.dirty ? '저장' : '저장됨'}</button>`;
  const undo = g.scene.prev ? `<button type="button" class="btn small ghost" data-action="stgUndo" title="마지막 AI 적용 전으로 되돌려요">적용 취소</button>` : '';
  const right = `${stgAiBtn()}${undo}${save}<button type="button" class="btn small ghost danger" data-action="stgDelete">장면 지우기</button>`;
  const notes = [];
  if (ck.event_changed) notes.push(`<div class="note warn" role="status">플롯 사건이 바뀌었어요. 이 장면은 "${esc(g.scene.event_text)}" 사건으로 짠 것이에요.</div>`);
  if (ck.violations.length) notes.push(`<div class="note warn" role="status"><b>규칙 검수 ${ck.violations.length}개</b><ul class="stg-viol">${ck.violations.map((x) => `<li><a href="#" data-action="stgBeat" data-arg="${x.beat}">${x.beat}박자</a> ${esc(x.text)}</li>`).join('')}</ul></div>`);
  const gaps = stgGaps();
  if (g.role === 'text') notes.push(`<div class="note plain">본문에서 뽑은 추출 결과예요. 고쳐도 계획 장면은 바뀌지 않아요.${ck.pair ? '' : ' 이 사건에는 견줄 계획 장면이 없어요.'}</div>`);
  if (gaps.length) notes.push(`<div class="note plain" role="status"><b>계획과 다른 곳 ${gaps.length}개</b> <span class="small">사소한 차이예요. 본문 쪽 연출이 더 나을 수도 있어요.</span><ul class="stg-viol">${gaps.map((x) => `<li><a href="#" data-action="stgBeat" data-arg="${x.k}">${x.k === 0 ? '시작 상태' : `${x.k}박자`}</a> ${esc(x.text)}</li>`).join('')}</ul></div>`);
  if (ck.stale.length) notes.push(`<div class="note plain">본문에 없는 문장을 가리키는 박자가 ${ck.stale.length}개 있어요: ${ck.stale.map((k) => `<a href="#" data-action="stgBeat" data-arg="${k}">${k}박자</a>`).join(', ')}</div>`);
  if (ck.dropped) notes.push(`<div class="note warn">미성년 인물이 낀 성적 접촉 ${ck.dropped}개는 저장할 때 빠져요.</div>`);
  const max = g.scene.beats.length;
  const plan = `<section class="card stg-planc stg-pane" data-pane="plan"${S.stgPane === 'side' ? ' data-hide' : ''} aria-label="평면도">
      <div class="between"><h2>${esc(g.room ? g.room.name : '방')}${g.role === 'text' ? ' <span class="chip">추출 결과</span>' : ''}</h2>${typeof s3Toggle === 'function' ? s3Toggle() : ''}<div class="seg" role="group" aria-label="평면도 모드"><button type="button" aria-pressed="${g.mode === 'people'}" data-action="stgMode" data-arg="people">인물</button><button type="button" aria-pressed="${g.mode === 'room'}" data-action="stgMode" data-arg="room">방 고치기</button></div></div>
      ${S.stgView === '3d' && g.room && typeof s3Pane === 'function' ? s3Pane() : g.room ? `<svg id="stg-plan" viewBox="0 0 ${stgScale(g.room).w} ${stgScale(g.room).h}" role="img" aria-label="${esc(g.room.name)} 평면도, ${g.beat === 0 ? '시작 상태' : `${g.beat}박자`}"></svg>` : '<p class="small">방을 찾지 못했어요.</p>'}
      <div class="stg-play"><button type="button" class="btn small" data-action="stgPlay"${max ? '' : ' disabled'}>${g.playing ? '❚❚ 멈춤' : '▶ 재생'}</button>
        <input type="range" min="0" max="${max}" step="1" value="${g.beat}" data-stg-slider aria-label="박자" aria-valuetext="${g.beat === 0 ? '시작 상태' : `${g.beat}박자`}"><span class="small">${g.beat} / ${max}</span></div>
      <div class="stg-legend"${S.stgView === '3d' ? ' style="display:none"' : ''}><span>쐐기 = 향한 쪽</span><span>점선 = 접촉</span><span>화살표 = 이번 박자 이동</span><span>${g.mode === 'room' ? '기준점을 끌어 옮겨요' : '인물을 끌어 놓으면 가까운 기준점에 붙어요'}</span></div>
      ${g.role === 'text' ? (ck.pair ? `<label class="row small"><input type="checkbox" data-stg-ghost${g.ghost ? ' checked' : ''}> 겹쳐 보기 (계획 인물을 흐린 원으로)</label>` : '')
    : `<label class="row small"><input type="checkbox" data-stg-prompt${g.scene.prompt ? ' checked' : ''}> 쓰기 프롬프트에 넣기</label>`}
    </section>`;
  const side = `<div class="col stg-pane" data-pane="side"${S.stgPane !== 'side' ? ' data-hide' : ''}>${g.mode === 'room' ? stgRoomPanel() : stgBeats() + stgPersonCard()}</div>`;
  const tabs = `<div class="tabs stg-tabs" role="tablist"><button type="button" role="tab" aria-selected="${S.stgPane !== 'side'}" data-action="stgPane" data-arg="plan">평면도</button><button type="button" role="tab" aria-selected="${S.stgPane === 'side'}" data-action="stgPane" data-arg="side">${g.mode === 'room' ? '방' : '박자 · 인물'}</button></div>`;
  return `${head(esc(evText), right)}${pickBar}${cmp}${notes.join('')}${tabs}<div class="stg-wrap">${plan}${side}</div>`;
}

/** render 뒤 평면도를 그린다 (app.js render 가 부른다). */
function syncStage() {
  if (!S.stg || S.route[2] !== 'stage') return;
  if (S.stgView === '3d' && typeof s3Mount === 'function') s3Mount(); else stgDrawPlan(null);
}

// ----- 동작 -----

function stgSet(field, value) {
  const b = stgBody(S.stg.who);
  b[field] = value;
  stgPrune();
  stgTouch();
}

Object.assign(actions, {
  stgAi() {
    const g = S.stg;
    if (g.dirty && !confirm('저장하지 않은 장면 변경이 있어요. AI 결과는 저장된 장면과 비교해요. 그래도 받을까요?')) return;
    startJob(g.role === 'text' ? 'stage_extract' : 'stage_draft', g.n, { event: g.ev - 1 });
  },
  async stgApply() {
    const g = S.stg;
    if (g.dirty && !confirm('저장하지 않은 변경이 사라져요. AI 장면으로 바꿀까요?')) return;
    try {
      const view = await api('POST', `/projects/${enc(S.name)}/stage/${g.n}/apply`, { event: g.ev - 1, role: g.role });
      stgTake(view);
      g.dirty = false;
      S.stgDirty = false;
      g.beat = 0;
      stgPick();
      toast('AI 장면을 적용했어요. 적용 취소로 되돌릴 수 있어요');
      render();
    } catch (err) { showError(err); }
  },
  async stgDiscard() {
    const g = S.stg;
    try {
      stgTake(await api('DELETE', `/projects/${enc(S.name)}/stage/${g.n}/proposal/${g.ev - 1}/${g.role}`));
      render();
    } catch (err) { showError(err); }
  },
  async stgUndo() {
    const g = S.stg;
    if (g.dirty && !confirm('저장하지 않은 변경이 사라져요. 적용 전으로 되돌릴까요?')) return;
    try {
      stgTake(await api('POST', `/projects/${enc(S.name)}/stage/${g.n}/${enc(g.sid)}/undo`));
      g.dirty = false;
      S.stgDirty = false;
      g.beat = 0;
      stgPick();
      toast('적용 전으로 되돌렸어요');
      render();
    } catch (err) { showError(err); }
  },
  stgBeat(k) {
    const g = S.stg;
    const from = stgShown;
    g.beat = Math.max(0, Math.min(Number(k), g.scene.beats.length));
    const b = g.beat > 0 ? g.scene.beats[g.beat - 1].bodies[0] : null;
    if (b) g.who = b.who;
    render();
    stgDrawPlan(from);
  },
  stgWho(w) { S.stg.who = w; render(); },
  stgRole(r) {
    const g = S.stg;
    if (g.role === r) return;
    if (g.dirty && !confirm('저장하지 않은 변경이 사라져요. 바꿀까요?')) return;
    g.role = r;
    g.dirty = false;
    S.stgDirty = false;
    stgPick();
    render();
  },
  stgMode(m) { S.stg.mode = m; render(); },
  stgPane(k) { S.stgPane = k; render(); },
  stgPosture(id) { stgSet('posture', id); },
  stgKeep(field) {
    const b = stgBody(S.stg.who, false);
    if (!b) return;
    b[field] = field === 'at' || field === 'left' || field === 'right' ? null : '';
    stgPrune();
    stgTouch();
  },
  stgPart(id) {
    S.stg.form.part = id;
    render();
  },
  stgAddContact() {
    const g = S.stg, f = g.form;
    const others = g.scene.cast.filter((x) => x !== g.who);
    const to = f.to && others.includes(f.to) ? f.to : others[0];
    if (!to || !f.part) return;
    const c = { id: stgNewContactId(), by: f.by, to, part: f.part, act: f.act };
    const minor = g.view.minors.includes(g.who) || g.view.minors.includes(to);
    if (minor && stageSexual(c, stgV())) return toast('미성년 인물이 있어 이 접촉은 고를 수 없어요', true);
    stgBody(g.who).contacts.push(c);
    f.part = '';
    stgTouch();
  },
  stgEnd(id) {
    const g = S.stg, b = stgBody(g.who);
    const i = b.contacts.findIndex((c) => c.id === id);
    if (i >= 0) b.contacts.splice(i, 1);  // 이 박자에 시작한 접촉은 뺀다
    else b.ends.push(id);
    stgPrune();
    stgTouch();
  },
  stgBeatAdd() {
    const g = S.stg;
    g.scene.beats.splice(g.beat, 0, { quote: '', note: '', bodies: [] });
    g.beat += 1;
    stgTouch();
  },
  stgBeatDrop() {
    const g = S.stg;
    if (!g.beat) return;
    const b = g.scene.beats[g.beat - 1];
    if (b.bodies.length && !confirm(`${g.beat}박자를 지울까요? 이 박자에서 바꾼 것도 사라져요.`)) return;
    g.scene.beats.splice(g.beat - 1, 1);
    g.beat -= 1;
    stgTouch();
  },
  stgBeatMove(d) {
    const g = S.stg, i = g.beat - 1, j = i + Number(d);
    if (i < 0 || j < 0 || j >= g.scene.beats.length) return;
    [g.scene.beats[i], g.scene.beats[j]] = [g.scene.beats[j], g.scene.beats[i]];
    g.beat = j + 1;
    stgTouch();
  },
  stgCastDrop(w) {
    const g = S.stg;
    if (!confirm(`${charName(w)}을(를) 출연진에서 뺄까요? 이 인물의 자리 · 자세 · 접촉도 모두 사라져요.`)) return;
    g.scene.cast = g.scene.cast.filter((x) => x !== w);
    const strip = (list) => list.filter((b) => b.who !== w).map((b) => ({ ...b, contacts: b.contacts.filter((c) => c.to !== w) }));
    g.scene.start = strip(g.scene.start);
    g.scene.beats.forEach((b) => { b.bodies = strip(b.bodies); });
    if (g.who === w) g.who = g.scene.cast[0] || '';
    stgTouch();
  },
  stgPlay() {
    const g = S.stg;
    if (g.playing) { clearInterval(g.playing); g.playing = null; render(); return; }
    if (g.beat >= g.scene.beats.length) g.beat = 0;
    g.playing = setInterval(() => {
      if (!S.stg || S.route[2] !== 'stage' || g.beat >= g.scene.beats.length) { clearInterval(g.playing); g.playing = null; if (S.stg) render(); return; }
      actions.stgBeat(g.beat + 1);
    }, 1100);
    render();
  },
  stgRotate(id) {
    const a = S.stg.room.anchors.find((x) => x.id === id);
    if (!a) return;
    a.rot = ((a.rot || 0) + 90) % 360;
    stgTouch();
  },
  stgAnchorDrop(id) {
    const g = S.stg;
    const used = [...g.scene.start, ...g.scene.beats.flatMap((b) => b.bodies)].some((b) => b.at && b.at.ref === id);
    if (used && !confirm('이 기준점에 선 인물이 있어요. 빼면 그 인물의 자리는 모름이 돼요. 뺄까요?')) return;
    g.room.anchors = g.room.anchors.filter((a) => a.id !== id);
    stgTouch();
  },
  stgAnchorAdd() {
    const r = S.stg.room;
    let k = 1;
    while (r.anchors.some((a) => a.id === `a${k}`)) k++;
    r.anchors.push({ id: `a${k}`, name: '새 기준점', kind: 'other', x: Math.max(0, r.w / 2 - 0.25), y: Math.max(0, r.h / 2 - 0.25), w: 0.5, h: 0.5, rot: 0, sit: false, lie: false });
    stgTouch();
  },
  async stgCreate() {
    const g = S.stg, k = g.pick;
    try {
      const v = await api('POST', `/projects/${enc(S.name)}/stage/${g.n}`, { event: g.ev - 1, room: k.room, template: k.template, room_name: k.name });
      stgTake(v);
      stgPick();
      toast('장면을 만들었어요');
      render();
    } catch (err) {
      toast(err.message, true);
    }
  },
  async stgSave() {
    const g = S.stg;
    if (!g.scene) return;
    try {
      const v = await api('PUT', `/projects/${enc(S.name)}/stage/${g.n}/${enc(g.scene.id)}`, { scene: g.scene, room: g.room });
      stgTake(v);
      g.dirty = false;
      S.stgDirty = false;
      stgPick();
      toast(v.dropped ? `저장했어요. 미성년 인물이 낀 성적 접촉 ${v.dropped}개는 뺐어요` : '저장했어요');
      render();
    } catch (err) {
      toast(err.message, true);
    }
  },
  async stgDelete() {
    const g = S.stg;
    if (!g.scene || !confirm('이 장면을 지울까요? 박자와 접촉이 모두 사라져요. 방은 남아요.')) return;
    try {
      stgTake(await api('DELETE', `/projects/${enc(S.name)}/stage/${g.n}/${enc(g.scene.id)}`));
      g.dirty = false;
      S.stgDirty = false;
      stgPick();
      toast('장면을 지웠어요');
      render();
    } catch (err) {
      toast(err.message, true);
    }
  },
});

// 칸 바꾸기: 자리 · 향함 · 손 · 메모, 박자 글, 방 칸, 접촉 고르기, 새 장면 고르기, 화 · 출연진 · 슬라이더
document.addEventListener('change', (e) => {
  const t = e.target, d = t.dataset || {};
  const g = S.stg;
  if (!g || S.route[2] !== 'stage') return;
  if (d.stgEp !== undefined) { location.hash = `${base()}/stage/${t.value}/1`; return; }
  if (d.stgPick) { g.pick[d.stgPick] = t.value; if (d.stgPick !== 'room' && d.stgPick !== 'name') g.pick.room = ''; render(); return; }
  if (!g.scene) return;
  if (d.stgField) {
    const f = d.stgField;
    if (f === 'at') {
      const [ref, rel] = t.value.split('|');
      stgSet('at', ref ? { ref, rel } : null);
    } else if (f === 'left' || f === 'right') stgSet(f, t.value.trim());
    else stgSet(f, t.value);
  } else if (d.stgBeat) {
    g.scene.beats[g.beat - 1][d.stgBeat] = t.value;
    stgTouch();
  } else if (d.stgRoom) {
    g.room[d.stgRoom] = d.stgRoom === 'w' || d.stgRoom === 'h' ? Math.max(1, Math.min(40, Number(t.value) || 1)) : t.value;
    stgTouch();
  } else if (d.stgAnchorName !== undefined || d.stgAnchorKind !== undefined) {
    const a = g.room.anchors.find((x) => x.id === (d.stgAnchorName || d.stgAnchorKind));
    if (!a) return;
    if (d.stgAnchorName !== undefined) a.name = t.value.trim() || a.name;
    else a.kind = t.value;
    stgTouch();
  } else if (d.stgForm) {
    g.form[d.stgForm] = t.value;
    render();
  } else if (d.stgCast !== undefined && t.value) {
    g.scene.cast.push(t.value);
    const door = g.room.anchors.find((a) => a.kind === 'door');
    g.scene.start.push({ who: t.value, at: door ? { ref: door.id, rel: 'front' } : null, posture: 'stand', facing: '', left: '', right: '', contacts: [], ends: [], memo: '' });
    g.who = t.value;
    stgTouch();
  } else if (d.stgGhost !== undefined) {
    g.ghost = t.checked;
    render();
  } else if (d.stgPrompt !== undefined) {
    g.scene.prompt = t.checked;
    stgTouch();
  }
});

document.addEventListener('input', (e) => {
  if (e.target.dataset && e.target.dataset.stgSlider !== undefined) actions.stgBeat(Number(e.target.value));
});

// 끌어 옮기기: 인물은 가까운 기준점 + 관계로, 기준점(방 고치기)은 자리를 옮긴다
let stgDrag = null;
function stgMeters(svg, ev) {
  const pt = svg.createSVGPoint();
  pt.x = ev.clientX;
  pt.y = ev.clientY;
  const p = pt.matrixTransform(svg.getScreenCTM().inverse());
  const sc = stgScale(S.stg.room);
  return [(p.x - sc.ox) / sc.s, (p.y - sc.oy) / sc.s];
}
document.addEventListener('pointerdown', (e) => {
  const svg = e.target.closest && e.target.closest('#stg-plan');
  if (!svg || !S.stg || !S.stg.scene) return;
  const g = S.stg;
  const who = e.target.closest('[data-stg-who]');
  const anc = e.target.closest('[data-stg-anchor]');
  if (g.mode === 'people' && who) {
    stgDrag = { kind: 'who', id: who.dataset.stgWho, svg, moved: false };
    g.who = stgDrag.id;
  } else if (g.mode === 'room' && anc) {
    const a = g.room.anchors.find((x) => x.id === anc.dataset.stgAnchor);
    const [mx, my] = stgMeters(svg, e);
    stgDrag = { kind: 'anchor', a, svg, dx: mx - a.x, dy: my - a.y, moved: false };
  } else return;
  svg.setPointerCapture(e.pointerId);
  e.preventDefault();
});
document.addEventListener('pointermove', (e) => {
  if (!stgDrag) return;
  const g = S.stg;
  const [mx, my] = stgMeters(stgDrag.svg, e);
  stgDrag.moved = true;
  if (stgDrag.kind === 'anchor') {
    const a = stgDrag.a;
    a.x = Math.round(Math.min(Math.max(mx - stgDrag.dx, 0), g.room.w - a.w) * 20) / 20;
    a.y = Math.round(Math.min(Math.max(my - stgDrag.dy, 0), g.room.h - a.h) * 20) / 20;
    stgDrawPlan(null);
  } else {
    const t = stgTarget(g.beat);
    t.pos[stgDrag.id] = [mx, my];
    stgDrag.svg.innerHTML = stgPlanSvg(t.pos, t.ang, g.beat);
  }
});
document.addEventListener('pointerup', (e) => {
  if (!stgDrag) return;
  const d = stgDrag;
  stgDrag = null;
  if (!d.moved) { render(); return; }
  if (d.kind === 'anchor') { stgTouch(); return; }
  const [mx, my] = stgMeters(d.svg, e);
  const at = stageSnap(S.stg.room, mx, my);
  if (at) stgSet('at', at);
  else render();
});

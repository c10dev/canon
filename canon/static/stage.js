/* 장면 연출 (서버 stage.py, 설계 docs/stage/). app.js 의 S, actions, api, render, header, esc, enc, ep, P, base, toast, charName, isTyping 을 쓴다.
   주소 stage/<화>/<사건 번호(1부터)>. 플롯 사건 하나의 장면을 방 평면도 위에 박자마다 짜고 재생한다.
   고치는 장면은 S.stg.scene · room 에 따로 들고 '저장'으로 PUT 한다(작품 전체 저장과 따로). 고칠 때마다 서버가 저장 없이 판정한다(POST …/check).
   인물 자리는 기준점 + 관계 말이고 좌표는 stageLayout 이 계산하고 stageLayouts 가 박자마다 앞 박자 좌표를 잇는다 (stage.place · layouts 와 같은 규칙, tests/test_stage_js.py).
   한 사건에 계획 장면(role plan)과 본문 장면(role text)이 하나씩 있다. 머리의 '계획 | 본문'으로 바꿔 보고(S.stg.role),
   본문 장면에서는 계획 인물을 흐린 원으로 겹쳐 본다(S.stg.ghost). 계획과 다른 곳(gaps)과 박자 짝(match)은 서버 stage.align 이 잰다.
   화별 스토리보드(view.board, 서버 stage.board_view)는 읽기만 한다: 사건 칩을 스토리보드 장면별로 묶고(stgEventGroups),
   새 장면 카드의 방 목록에서 스토리보드 장소에 맞는 방을 앞에 둔다(stgRoomOrder).
   stageResolve · stageToLocal · stageChildren · stageState · stageLayout · stageLayouts · stageAnchorPoint · stageFacing · stageSnap · stageSexual · stagePlanBeat ·
   stgEventGroups · stgRoomOrder 는 DOM 없는 순수 함수다. */
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

// ----- 붙은 기준점: stage.resolve 와 같은 규칙 (docs/stage/specs/09-attach.md) -----

const STG_FACES = { inside: '안', top: '위', front: '앞면', back: '뒷면', left: '왼쪽 면', right: '오른쪽 면' };  // stage.FACES
const STG_WALLS = { n: '위 벽', e: '오른쪽 벽', s: '아래 벽', w: '왼쪽 벽' };  // stage.WALLS
const STG_ATTACH = ['door', 'window', 'wall'];  // stage.ATTACH
const STG_WORLD = new WeakSet();  // stageResolve 로 푼 방. 저장하지 않는다
const stgR4 = (x) => Math.round(x * 1e4) / 1e4;

/** [앞 f, 오른쪽 r]. stage._frame 과 같다. */
function stgFrame(rot) {
  const [fx, fy] = stgFront(rot || 0);
  return [[fx, fy], [fy, -fx]];
}

/** 세계 가로 · 세로 ↔ (r 쪽, f 쪽) 크기. stage._extent 와 같다. */
const stgExtent = (w, h, r) => (r[0] !== 0 ? [w, h] : [h, w]);

/** 붙은 자식의 지역 가운데를 면에 맞춘다. stage._local_xy 와 같다. */
function stgLocalXY(p, c) {
  const [, r] = stgFrame(p.rot);
  const [pr, pf] = stgExtent(p.w, p.h, r);
  const clamp = (v, lim) => (lim > 0 ? Math.max(-lim, Math.min(lim, v)) : 0);
  const inner = STG_ATTACH.includes(c.kind);
  let x = c.x, y = c.y;
  if (c.face === 'front' || c.face === 'back') {
    y = (inner ? pf / 2 - c.h / 2 : pf / 2 + c.h / 2) * (c.face === 'front' ? 1 : -1);
    x = clamp(x, (pr - c.w) / 2);
  } else if (c.face === 'left' || c.face === 'right') {
    x = (inner ? pr / 2 - c.w / 2 : pr / 2 + c.w / 2) * (c.face === 'right' ? 1 : -1);
    y = clamp(y, (pf - c.h) / 2);
  } else {
    x = clamp(x, (pr - c.w) / 2);
    y = clamp(y, (pf - c.h) / 2);
  }
  return [x, y];
}

function stgToWorld(p, c) {
  const [f, r] = stgFrame(p.rot);
  const [x, y] = stgLocalXY(p, c);
  const cx = p.x + p.w / 2 + x * r[0] + y * f[0], cy = p.y + p.h / 2 + x * r[1] + y * f[1];
  const [w, h] = stgExtent(c.w, c.h, r);
  return { ...c, x: stgR4(cx - w / 2), y: stgR4(cy - h / 2), w, h, rot: ((p.rot || 0) + (c.rot || 0)) % 360 };
}

/** 세계 좌표 자식 c 를 세계 좌표 부모 p 의 face 에 붙인 저장 꼴. stage.to_local 과 같다. */
function stageToLocal(p, c, face) {
  const [f, r] = stgFrame(p.rot);
  const dx = c.x + c.w / 2 - (p.x + p.w / 2), dy = c.y + c.h / 2 - (p.y + p.h / 2);
  const [w, h] = stgExtent(c.w, c.h, r);
  const r3 = (v) => Math.round(v * 1e3) / 1e3;
  return { ...c, parent: p.id, face, x: r3(dx * r[0] + dy * r[1]), y: r3(dx * f[0] + dy * f[1]), w, h, rot: (((c.rot || 0) - (p.rot || 0)) % 360 + 360) % 360 };
}

function stgWallWorld(room, c) {
  let x = c.x, y = c.y;
  if (c.face === 'n' || c.face === 's') {
    x = Math.min(Math.max(x, 0), Math.max(room.w - c.w, 0));
    y = c.face === 'n' ? 0 : room.h - c.h;
  } else {
    y = Math.min(Math.max(y, 0), Math.max(room.h - c.h, 0));
    x = c.face === 'w' ? 0 : room.w - c.w;
  }
  return { ...c, x, y };
}

/** 세계 좌표로 푼 사본. 이미 푼 방은 그대로. stage.resolve 와 같다. */
function stageResolve(room) {
  if (!room || STG_WORLD.has(room)) return room;
  const by = Object.fromEntries(room.anchors.map((a) => [a.id, a]));
  const out = {};
  const world = (a, seen) => {
    if (out[a.id]) return out[a.id];
    let w;
    if (a.parent === 'room' && STG_WALLS[a.face]) w = stgWallWorld(room, a);
    else if (a.parent && by[a.parent] && !seen.has(a.parent) && STG_FACES[a.face]) w = stgToWorld(world(by[a.parent], new Set([...seen, a.parent])), a);
    else w = { ...a };
    out[a.id] = w;
    return w;
  };
  const r = { ...room, anchors: room.anchors.map((a) => world(a, new Set([a.id]))) };
  STG_WORLD.add(r);
  return r;
}

/** aid 에 붙은 기준점과 그 자식들. stage.children 과 같다. */
function stageChildren(room, aid) {
  const out = [], todo = [aid];
  while (todo.length) {
    const cur = todo.shift();
    room.anchors.forEach((a) => { if (a.parent === cur && a.id !== aid && !out.includes(a)) { out.push(a); todo.push(a.id); } });
  }
  return out;
}

/** ↻: 상자를 90도 돌린다(가로 · 세로가 바뀌고 가운데는 그대로). 붙은 자식은 부모 기준이라 함께 돈다.
    뿌리 · 벽 자식은 왼쪽 위 모서리, 기준점 자식은 가운데를 저장하므로 뿌리만 모서리를 옮긴다. */
function stageTurn(a) {
  if (!a.parent || a.parent === 'room') {
    a.x = Math.round((a.x + (a.w - a.h) / 2) * 1000) / 1000;
    a.y = Math.round((a.y + (a.h - a.w) / 2) * 1000) / 1000;
  }
  [a.w, a.h] = [a.h, a.w];
  a.rot = ((a.rot || 0) + 90) % 360;
}

/** '붙은 곳' 고르기의 후보: [[값, 이름]]. 자기 자신과 자기 자식은 뺀다. 값은 '' · 'room|n' · '<id>|<면>'. */
function stageAttachOptions(room, aid) {
  const skip = new Set([aid, ...stageChildren(room, aid).map((a) => a.id)]);
  const out = [['', '없음']].concat(Object.entries(STG_WALLS).map(([k, l]) => [`room|${k}`, l]));
  room.anchors.filter((a) => !skip.has(a.id)).forEach((a) => Object.entries(STG_FACES).forEach(([k, l]) => out.push([`${a.id}|${k}`, `${a.name} ${l}`])));
  return out;
}

/** aid 를 value('' 떼기 · 'room|벽' · '<부모 id>|<면>')에 붙인 저장 꼴. 지금 세계 자리에서 가장 가까운 자리로 붙는다. */
function stageAttach(room, aid, value) {
  const w = stageResolve(room), wa = w.anchors.find((a) => a.id === aid);
  const [pid, face] = (value || '').split('|');
  if (!pid) return { ...wa, parent: '', face: '' };
  if (pid === 'room') return { ...wa, parent: 'room', face };
  const pw = w.anchors.find((a) => a.id === pid);
  if (!pw) return { ...wa, parent: '', face: '' };
  const loc = stageToLocal(pw, wa, face);
  const [x, y] = stgLocalXY(pw, loc);
  return { ...loc, x: Math.round(x * 1000) / 1000, y: Math.round(y * 1000) / 1000 };
}

/** 끌기: 세계 왼쪽 위 (tx, ty) 로 옮긴 저장 값 {x, y}. 뿌리는 방 안에서, 벽 자식은 벽을 따라서, 기준점 자식은 붙은 면을 따라서 · 부모 안에서만.
    0.05m 칸에 맞춘다. 부모를 끌면 자식은 값이 그대로라 따라간다. */
function stageDragTo(room, aid, tx, ty) {
  const w = stageResolve(room), wa = w.anchors.find((a) => a.id === aid), a = room.anchors.find((x) => x.id === aid);
  const snap = (v) => Math.round(v * 20) / 20;
  const pw = a.parent && a.parent !== 'room' ? w.anchors.find((x) => x.id === a.parent) : null;
  if (!pw) return { x: snap(Math.min(Math.max(tx, 0), room.w - wa.w)), y: snap(Math.min(Math.max(ty, 0), room.h - wa.h)) };
  const loc = stageToLocal(pw, { ...wa, x: tx, y: ty }, a.face);
  const [x, y] = stgLocalXY(pw, { ...a, x: snap(loc.x), y: snap(loc.y) });
  return { x: Math.round(x * 1000) / 1000, y: Math.round(y * 1000) / 1000 };
}

/** 방을 왼쪽 · 위로 넓힐 때 뿌리와 벽 자식만 옮긴다. stage.shift_room 과 같다. */
function stageShiftRoom(room, dx, dy) {
  room.anchors.forEach((a) => {
    if (a.parent && a.parent !== 'room') return;
    a.x = Math.round((a.x + dx) * 100) / 100;
    a.y = Math.round((a.y + dy) * 100) / 100;
  });
}

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
  room = stageResolve(room);
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

function stgPersonPoint(o, facing, rel, room, pos, me = '') {
  const [fx, fy] = stageFacing(facing, o, room, pos) || [0, 1];
  const [rx, ry] = [-fy, fx];
  const d = STG_BODY * 2 + 0.05;
  if (rel === 'on' || rel === 'in') return [o[0] + 0.15, o[1]];
  if (rel === 'across') return [o[0] + fx * STG_ACROSS, o[1] + fy * STG_ACROSS];
  if (rel === 'against') return [o[0] + fx * STG_BODY * 2, o[1] + fy * STG_BODY * 2];
  // 기준 인물이 나를 향하고 앞 박자의 내 자리를 알면 그 쪽에 선다 (관계 말을 따르면 박자마다 돈다, stage._person_point)
  if (me && facing === `@${me}` && pos[me]) return [o[0] + fx * d, o[1] + fy * d];
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
  room = stageResolve(room);
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
        pos[w] = stgPersonPoint(pos[ref], state[ref].facing, state[w].at.rel, room, look, w);
        rest.splice(rest.indexOf(w), 1);
        moved = true;
      }
    }
    if (!moved) pos[rest.shift()] = [room.w / 2, room.h / 2];
  }
  const clamp = (v, hi) => Math.min(Math.max(v, STG_BODY), hi - STG_BODY);
  return Object.fromEntries(Object.entries(pos).map(([w, [x, y]]) => [w, [clamp(x, room.w), clamp(y, room.h)]]));
}

/** 박자 사이 돌아가는 이동 (서버 stagepath.paths, check 응답의 paths). a → b 로 옮기는 인물 w 의 꺾은선 [[x, y], ...]:
   k 박자로 가는 경로, 없으면 k + 1 박자 경로를 거꾸로(뒤로 넘길 때). 끝점이 a · b 와 0.05m 넘게 다르면(고친 뒤 판정 전) null. */
function stagePathFor(paths, k, w, a, b) {
  const near = (p, q) => p && q && Math.hypot(p[0] - q[0], p[1] - q[1]) <= 0.05;
  const fwd = paths && paths[k] && paths[k][w], back = paths && paths[k + 1] && paths[k + 1][w];
  if (fwd && fwd.via.length > 2 && near(fwd.via[0], a) && near(fwd.via[fwd.via.length - 1], b)) return fwd.via;
  if (back && back.via.length > 2 && near(back.via[0], b) && near(back.via[back.via.length - 1], a)) return [...back.via].reverse();
  return null;
}

/** 꺾은선 via 위에서 길이 비율 e (0~1) 만큼 간 점. */
function stagePathAt(via, e) {
  const lens = via.slice(1).map((p, i) => Math.hypot(p[0] - via[i][0], p[1] - via[i][1]));
  let left = lens.reduce((s, x) => s + x, 0) * Math.max(0, Math.min(1, e));
  for (let i = 0; i < lens.length; i++) {
    if (left <= lens[i] || i === lens.length - 1) {
      const t = lens[i] ? Math.min(1, left / lens[i]) : 1;
      return [via[i][0] + (via[i + 1][0] - via[i][0]) * t, via[i][1] + (via[i + 1][1] - via[i][1]) * t];
    }
    left -= lens[i];
  }
  return via[via.length - 1];
}

/** 글자 폭 어림 (px): 한글 · 한자는 1em, 나머지는 0.6em (지도 atlasTextW 와 같은 어림). */
const stageTextW = (t, fs) => [...t].reduce((n, ch) => n + (ch.charCodeAt(0) > 0x2e80 ? 1 : 0.6), 0) * fs;

/** 이름표 놓기 (docs/stage/specs/11-labels.md). 평면도 · 3D 가 함께 쓰는 화면 좌표 계산이다.
   items: [{id, x, y, text, short?, fs, kind, r?, w?, h?}] 를 놓는 차례대로 (앞이 우선). kind 는
   'ring'(평면도 인물: 반지름 r 인 원 둘레 여덟 자리 → 먼 고리 + 지시선), 'tag'(3D 인물: 그 점 → 둘레 → 먼 고리),
   'pin'(기준점 이름: 그 점과 위 · 아래만, 막히면 숨김). w · h 를 주면 어림 대신 그 크기(3D 는 잰 값)를 쓴다.
   opts: {taken: 먼저 차지한 상자 [[x0, y0, x1, y1]], bounds: [x0, y0, x1, y1], prev: {id: {k, short}} (앞 프레임 자리, 고쳐 돌려준다)}.
   자리가 없으면 short(자세를 뗀 이름)로 다시 찾고, 그래도 없으면 인물은 첫 자리에 겹쳐 두고 기준점 이름은 숨긴다.
   돌려주는 값: {id: {cx, cy, w, h, text, leader, hidden}} (cx · cy 는 이름표 가운데). */
function stageLabelPlace(items, opts = {}) {
  const placed = (opts.taken || []).slice(), bounds = opts.bounds, prev = opts.prev || {}, out = {};
  const hit = (b) => (bounds && (b[0] < bounds[0] || b[1] < bounds[1] || b[2] > bounds[2] || b[3] > bounds[3]))
    || placed.some((p) => b[0] < p[2] && b[2] > p[0] && b[1] < p[3] && b[3] > p[1]);
  const spots = (it, w, h) => {
    const r = it.r || 0, g = 4, hx = w / 2, hy = h / 2, d = r * 0.7 + g;
    const ring = [[0, r + g + hy], [0, -(r + g + hy)], [r + g + hx, 0], [-(r + g + hx), 0],
      [d + hx, d + hy], [-(d + hx), d + hy], [d + hx, -(d + hy)], [-(d + hx), -(d + hy)]];
    if (it.kind === 'pin') return [[0, 0], [0, -h], [0, h]];
    const near = it.kind === 'tag' ? [[0, 0], ...ring] : ring;
    const far = [];
    [2, 3, 4].forEach((m) => {
      for (let a = 0; a < 8; a++) {
        const t = Math.PI / 2 - (a * Math.PI) / 4, c = Math.cos(t), sn = Math.sin(t), R = (r + g + h) * m;
        far.push([c * R + c * hx, sn * R + sn * hy, true]);
      }
    });
    return near.concat(far);
  };
  items.forEach((it) => {
    const tries = [[it.text, false]].concat(it.short && it.short !== it.text ? [[it.short, true]] : []);
    const before = prev[it.id];
    if (before && before.short && tries.length > 1) tries.reverse();  // 앞 프레임에 줄였으면 줄인 글부터 (흔들림 줄이기)
    let got = null;
    for (const [text, short] of tries) {
      const w = it.w && !short ? it.w : stageTextW(text, it.fs) + (it.pad || 0), h = it.h || it.fs * 1.25;
      const list = spots(it, w, h);
      const order = list.map((_, k) => k);
      if (before && before.short === short && before.k < list.length) order.unshift(before.k);
      const k = order.find((i) => !hit([it.x + list[i][0] - w / 2, it.y + list[i][1] - h / 2, it.x + list[i][0] + w / 2, it.y + list[i][1] + h / 2]));
      if (k !== undefined) { got = { k, text, short, w, h, sp: list[k] }; break; }
    }
    if (!got && it.kind === 'pin') { out[it.id] = { hidden: true, text: it.text }; delete prev[it.id]; return; }
    if (!got) {
      const text = tries[tries.length - 1][0], short = tries.length > 1, w = stageTextW(text, it.fs) + (it.pad || 0), h = it.h || it.fs * 1.25;
      got = { k: 0, text, short, w, h, sp: spots(it, w, h)[0] };
    }
    const cx = it.x + got.sp[0], cy = it.y + got.sp[1];
    placed.push([cx - got.w / 2, cy - got.h / 2, cx + got.w / 2, cy + got.h / 2]);
    prev[it.id] = { k: got.k, short: got.short };
    out[it.id] = { cx, cy, w: got.w, h: got.h, text: got.text, leader: !!got.sp[2], hidden: false };
  });
  return out;
}

/** 박자 0~k 의 좌표 목록. 박자마다 앞 박자 좌표를 넘긴다. stage.layouts 와 같다. */
function stageLayouts(room, scene, k = (scene.beats || []).length) {
  room = stageResolve(room);
  const out = [];
  for (let i = 0; i <= k; i++) out.push(stageLayout(room, stageState(scene, i), scene.cast, i ? out[i - 1] : null));
  return out;
}

/** 평면도에서 끌어 놓은 자리 (m) 에 가장 가까운 기준점 + 관계. 기준점이 없으면 null. */
function stageSnap(room, x, y) {
  room = stageResolve(room);
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

/** 사건 칩 묶음: 이어진 사건이 같은 스토리보드 장면이면 한 묶음. board 는 사건마다 {no, place, spot} 또는 null (stage.board_view 의 events).
    [{no(없으면 null), place, spot, events: [사건 번호(1부터)]}]. 스토리보드가 없으면 모든 사건이 한 묶음(no null). */
function stgEventGroups(count, board) {
  const out = [];
  for (let k = 0; k < count; k++) {
    const b = (board || [])[k] || null;
    const no = b ? b.no : null;
    const last = out[out.length - 1];
    if (last && last.no === no) last.events.push(k + 1);
    else out.push({ no, place: b ? b.place : '', spot: b ? b.spot : '', events: [k + 1] });
  }
  return out;
}

/** 새 장면 카드의 방 순서: hints(스토리보드 장소에 맞는 방 id, stage.room_hints 순서) 먼저, 나머지는 원래 순서. */
function stgRoomOrder(rooms, hints) {
  const h = hints || [];
  const rank = (r) => (h.includes(r.id) ? h.indexOf(r.id) : h.length);
  return rooms.map((r, i) => [r, i]).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map(([r]) => r);
}

/** 지금 사건을 맡은 스토리보드 장면 (없으면 null). */
const stgBoardOf = (g) => ((g.view.board && g.view.board.events) || [])[g.ev - 1] || null;

async function stgLoad(n, ev) {
  if (!n || !ep(n)) { S.stg = null; return; }
  const view = await api('GET', `/projects/${enc(S.name)}/stage/${n}`);
  const keep = S.stg && S.stg.n === n && S.stg.ev === ev && S.stg.dirty;
  if (keep) { S.stg.view = view; return; }
  S.stgDirty = false;
  const role = S.stg ? S.stg.role : 'plan', ghost = S.stg ? S.stg.ghost : true;
  const jump = S.stgJump && S.stgJump.n === n && S.stgJump.ev === ev ? S.stgJump : null;  // 검수 화면의 '장면 연출에서 보기'
  S.stgJump = null;
  S.stg = { n, ev, view, role: jump ? jump.role : role, ghost, sid: null, scene: null, room: null, dirty: false, beat: jump ? jump.beat : 0, who: '', open: '', beatEdit: false, mode: 'people', check: null,
    form: { by: 'right', to: '', part: '', act: 'hold' }, pick: { room: '', template: 'bedroom', name: '' }, playing: null };
  const bs = stgBoardOf(S.stg);  // 스토리보드 장소에 맞는 방을 먼저 고르고, 없으면 새 방 이름을 자리 · 장소로
  if (bs) S.stg.pick = { ...S.stg.pick, room: bs.hints[0] || '', name: bs.hints.length ? '' : bs.spot || bs.place };
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
  g.check = row ? { event_changed: row.event_changed, stale: row.stale, violations: row.violations, moves: row.moves || [], paths: row.paths || [], pair: row.pair, gaps: row.gaps || [], match: row.match || [], dropped: 0 } : null;
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

/** 인물 색: 장면 연출 토큰 stage-1~6 (app.css · docs/design/tokens.json). 빨강은 지적에만 쓴다. 원 안 첫 글자는 on-stage */
const STG_COLORS = ['var(--stage-1)', 'var(--stage-2)', 'var(--stage-3)', 'var(--stage-4)', 'var(--stage-5)', 'var(--stage-6)'];
const stgColor = (who) => STG_COLORS[Math.max(0, S.stg.scene.cast.indexOf(who)) % STG_COLORS.length];
/** 인물 색 점. 이름 글자는 --text 로 두고 인물 색은 이 점으로 보인다 */
const stgDot = (who) => `<i class="stg-dot" style="background:${stgColor(who)}" aria-hidden="true"></i>`;
const stgV = () => S.stg.view.vocab;
/** 지적 앞 규칙 이름. 3D 규칙(높이 · 몸 겹침 · 가구 · 받침 · 천장)은 '3D' 를 붙인다 (stage.vocab 의 rules · rules3d). */
function stgRuleTag(rule) {
  const v = (S.stg && S.stg.view && S.stg.view.vocab) || {}, name = (v.rules || {})[rule];
  if (!name) return '';
  return `<span class="chip">${(v.rules3d || []).includes(rule) ? '3D · ' : ''}${esc(name)}</span> `;
}

/** 평면도 비율: 방이 520 x 400 안에 들게. */
function stgScale(room) {
  const s = Math.min(440 / room.w, 320 / room.h);
  return { s, ox: 40, oy: 40, w: room.w * s + 80, h: room.h * s + 80 };
}

/** 평면도 한 화면 px 이 몇 그림 단위인지. stgDrawPlan 이 그리기 전에 잰다. 글자 · 인물 원을 화면에서 같은 크기로 그리는 데 쓴다 */
let stgU = 1;

function stgPlanSvg(pos, ang, k) {
  const g = S.stg, room = stageResolve(g.room), sc = stgScale(room), u = stgU;
  const R = 16 * u, fs = 12 * u, narrow = u > 1.3;  // 좁은 칸(휴대폰)은 이름표에 자세를 빼고 이름만
  const px = ([x, y]) => [sc.ox + x * sc.s, sc.oy + y * sc.s];
  const st = stageState(g.scene, k);
  const all = stageLayouts(room, g.scene, k), prev = k > 0 ? all[k - 1] : null, now = all[k];
  const flags = (g.check ? g.check.violations : []).filter((v) => v.beat === k);
  const bad = new Set(flags.map((v) => v.who)), badContact = new Set(flags.map((v) => v.contact).filter(Boolean));
  let out = '<defs><marker id="stg-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="var(--muted)"/></marker></defs>';
  out += `<rect class="stg-wall" x="${sc.ox}" y="${sc.oy}" width="${room.w * sc.s}" height="${room.h * sc.s}" rx="2"/>`;
  const pins = [];
  room.anchors.forEach((a) => {
    const [x, y] = px([a.x, a.y]);
    const [fx, fy] = stgFront(a.rot || 0);
    const cx = x + a.w * sc.s / 2, cy = y + a.h * sc.s / 2;
    const edit = g.mode === 'room';
    out += `<g class="stg-anchor ${esc(a.kind)}${edit ? ' edit' : ''}" data-stg-anchor="${esc(a.id)}"><rect x="${x}" y="${y}" width="${Math.max(a.w * sc.s, 4)}" height="${Math.max(a.h * sc.s, 4)}" rx="4"/>`;
    if (edit) out += `<path class="stg-front" d="M${cx} ${cy}L${cx + fx * 16 * u} ${cy + fy * 16 * u}"/>`;
    const thin = a.w * sc.s < 40 || a.h * sc.s < 18;
    // 문 · 창처럼 얇은 기준점은 이름을 벽 바깥(뒤쪽)에 쓴다. 이름은 인물 이름표 뒤에 놓는다 (stageLabelPlace)
    pins.push({ id: 'a:' + a.id, x: thin ? cx - fx * 18 * u : cx, y: thin ? cy - fy * 18 * u : cy, text: a.name, fs, kind: 'pin' });
    out += `<title>${esc(a.name)}</title><!--stg-pin:${esc(a.id)}--></g>`;
  });
  Object.keys(st).forEach((w) => Object.values(st[w].contacts).forEach((c) => {
    if (!pos[w] || !pos[c.to]) return;
    const [x1, y1] = px(pos[w]), [x2, y2] = px(pos[c.to]);
    out += `<path class="stg-contact${badContact.has(c.id) ? ' bad' : ''}" d="M${x1} ${y1}L${x2} ${y2}" stroke="${stgColor(w)}"/>`;
  }));
  const paths = (g.check && g.check.paths) || [];
  if (prev) Object.keys(now).forEach((w) => {
    if (!prev[w] || Math.hypot(prev[w][0] - now[w][0], prev[w][1] - now[w][1]) < 0.05) return;
    const row = paths[k] && paths[k][w];
    const blocked = !!(row && row.blocked);
    // 가구를 돌아가는 이동은 꺾은선으로, 막힌 이동은 곧은 빨간 점선으로 (docs/stage/specs/10-path.md)
    const pts = (stagePathFor(paths, k, w, prev[w], now[w]) || [prev[w], now[w]]).map(px);
    const cut = (p, q, by) => { const d = Math.hypot(q[0] - p[0], q[1] - p[1]) || 1; return [p[0] + (q[0] - p[0]) * by / d, p[1] + (q[1] - p[1]) * by / d]; };
    const span = pts.slice(1).reduce((s, p, i) => s + Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]), 0);
    if (span <= 44 * u) return;
    pts[0] = cut(pts[0], pts[1], 20 * u);
    pts[pts.length - 1] = cut(pts[pts.length - 1], pts[pts.length - 2], 22 * u);
    out += `<path class="stg-move${blocked ? ' blocked' : ''}" d="M${pts.map((p) => `${p[0]} ${p[1]}`).join('L')}"><title>${blocked ? '가구에 막혀 돌아갈 길이 없어요' : '가구를 돌아가는 길'}</title></path>`;
  });
  out += stgGhostSvg(k, px);
  // 이름표: 고른 인물 → 출연진 순 → 기준점 이름. 인물 원(반지름 16px, 향함 삼각형까지 18px)은 먼저 차지한다
  const who = Object.keys(pos).sort((a, b) => (b === g.who) - (a === g.who));
  const people = who.map((w) => {
    const [x, y] = px(pos[w]), post = stgV().postures[st[w].posture], name = charName(w);
    return { id: 'p:' + w, x, y, text: post && !narrow ? `${name} · ${post.label}` : name, short: name, fs, kind: 'ring', r: 18 * u };
  });
  const tags = stageLabelPlace(people.concat(pins), {
    taken: people.map((p) => [p.x - p.r, p.y - p.r, p.x + p.r, p.y + p.r]), bounds: [0, 0, sc.w, sc.h], prev: stgLabelMem,
  });
  pins.forEach((p) => {
    const t = tags[p.id];
    out = out.replace(`<!--stg-pin:${esc(p.id.slice(2))}-->`, t.hidden ? '' : `<text x="${t.cx}" y="${t.cy + 4 * u}" text-anchor="middle">${esc(t.text)}</text>`);
  });
  Object.keys(pos).forEach((w) => {
    const [x, y] = px(pos[w]);
    const name = charName(w), tag = tags['p:' + w];
    let face = '';
    if (ang[w] != null) {
      const a = ang[w], p = (r, d) => `${x + Math.cos(a + r) * d} ${y + Math.sin(a + r) * d}`;
      face = `<path class="face" d="M${p(0, 26 * u)}L${p(2.3, 13 * u)}L${p(-2.3, 13 * u)}Z" fill="${stgColor(w)}"/>`;
    }
    out += `<g class="stg-person${bad.has(w) ? ' bad' : ''}${w === g.who ? ' cur' : ''}" data-stg-who="${esc(w)}" tabindex="-1">${face}
      <circle class="body" cx="${x}" cy="${y}" r="${R}" fill="${stgColor(w)}"/><text class="ini" x="${x}" y="${y}">${esc(name.slice(0, 1))}</text>
      ${tag.leader ? stgLeader(x, y, 18 * u, tag) : ''}<text class="label" x="${tag.cx}" y="${tag.cy + 4 * u}" text-anchor="middle">${esc(tag.text)}</text></g>`;
  });
  return out;
}

/** 지시선: 원 가장자리(반지름 r)에서 이름표 상자의 가장 가까운 점까지. */
function stgLeader(x, y, r, t) {
  const ex = Math.min(Math.max(x, t.cx - t.w / 2), t.cx + t.w / 2), ey = Math.min(Math.max(y, t.cy - t.h / 2), t.cy + t.h / 2);
  const d = Math.hypot(ex - x, ey - y) || 1;
  return `<path class="stg-leader" d="M${x + (ex - x) * r / d} ${y + (ey - y) * r / d}L${ex} ${ey}"/>`;
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
    return `<g class="stg-ghost" data-stg-ghost-who="${esc(w)}"><circle cx="${x}" cy="${y}" r="${16 * stgU}" stroke="${stgColor(w)}"/><text x="${x}" y="${y}">${esc(charName(w).slice(0, 1))}</text></g>`;
  }).join('') + `<text class="stg-ghost-note" x="${px([0, 0])[0]}" y="${px([0, 0])[1] - 10 * stgU}">흐린 원 = 계획 ${pk === 0 ? '시작 상태' : `${pk}박자`}</text>`;
}

function stgTarget(k) {
  const g = S.stg, st = stageState(g.scene, k), pos = stageLayouts(g.room, g.scene, k)[k], ang = {};
  Object.keys(pos).forEach((w) => {
    const v = stageFacing(st[w].facing, pos[w], g.room, pos);
    ang[w] = v ? Math.atan2(v[1], v[0]) : null;
  });
  return { pos, ang };
}

const stgLabelMem = {};  // 이름표마다 앞 프레임 자리 (stageLabelPlace 의 prev)
let stgShown = null;
let stgAnim = 0;
/** 평면도만 다시 그린다. from 이 있으면 박자 사이를 0.6초 보간한다 (위치와 향함만). */
function stgDrawPlan(from) {
  const svg = document.getElementById('stg-plan');
  const g = S.stg;
  if (!svg || !g || !g.scene || !g.room) return;
  // 화면 1px 이 그림 몇 단위인지 잰다: 글자 12px · 인물 원 16px 을 칸 폭과 상관없이 같게 (휴대폰에서 7px 로 줄지 않게)
  const ctm = svg.getScreenCTM();
  stgU = ctm && ctm.a ? Math.min(2.4, Math.max(0.6, 1 / ctm.a)) : 1;
  svg.style.setProperty('--u', stgU);
  const to = stgTarget(g.beat);
  cancelAnimationFrame(stgAnim);
  if (!from || matchMedia('(prefers-reduced-motion: reduce)').matches) {
    svg.innerHTML = stgPlanSvg(to.pos, to.ang, g.beat);
    stgShown = to;
    return;
  }
  const all = (g.check && g.check.paths) || [], paths = {};
  Object.keys(to.pos).forEach((w) => { if (from.pos[w]) paths[w] = stagePathFor(all, g.beat, w, from.pos[w], to.pos[w]); });
  const t0 = performance.now();
  const step = (t) => {
    const u = Math.min(1, (t - t0) / 600), e = u < 0.5 ? 2 * u * u : 1 - (-2 * u + 2) ** 2 / 2;
    const pos = {}, ang = {};
    Object.keys(to.pos).forEach((w) => {
      const a = from.pos[w] || to.pos[w], via = paths[w];
      pos[w] = via ? stagePathAt(via, e) : [a[0] + (to.pos[w][0] - a[0]) * e, a[1] + (to.pos[w][1] - a[1]) * e];
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

/** 박자 이름: 0 은 시작 상태. */
const stgBeatName = (k) => (k === 0 ? '시작 상태' : `${k}박자`);
/** 계획과 다른 곳을 지금 역할의 박자 번호(k)와 함께. */
function stgGaps() {
  const g = S.stg;
  return (g.check && g.check.gaps || []).map((x) => ({ ...x, k: g.role === 'text' ? x.text_beat : x.plan_beat }));
}

/** 접촉의 '무엇으로' 이름 (손 · 부위). */
const stgByLabel = (by) => stgV().hands[by] || (stgV().parts[by] ? stgV().parts[by].label : by);
/** 접촉 한 줄: '오른손 → 서윤 왼 어깨 · 짚다'. */
const stgContactText = (c) => `${stgByLabel(c.by)} → ${charName(c.to)} ${(stgV().parts[c.part] || {}).label || c.part} · ${(stgV().acts[c.act] || {}).label || c.act}`;

/** 쥔 것: 빈칸은 빈손, '?' 는 모름. */
function stgHands(l, r) {
  const one = (side, x) => (x === STG_UNKNOWN ? `${side} 모름` : x ? `${side} ${x}` : '');
  const out = [one('왼손', l), one('오른손', r)].filter(Boolean);
  return out.length ? out.join(' · ') : '빈손';
}

/** 인물 한 줄 요약(읽는 모양): 자세 · 자리 · 향함 · 손 · 접촉. */
function stgSummary(w, k) {
  const g = S.stg, all = stageState(g.scene, k), st = all[w];
  if (!st) return '';
  const post = stgV().postures[st.posture];
  const bits = [post ? post.label : '자세 모름', st.at ? stgSpotLabel(st.at) : '자리 모름'];
  if (st.facing) bits.push(`${stgFacingLabel(st.facing)} 향함`);
  bits.push(stgHands(st.left, st.right));
  Object.values(st.contacts).forEach((c) => bits.push(stgContactText(c)));
  Object.entries(all).forEach(([who, s]) => Object.values(s.contacts).forEach((c) => {
    if (c.to === w) bits.push(`${charName(who)} ${stgByLabel(c.by)}이 닿음`);
  }));
  return bits.join(' · ');
}

/** 한 박자에서 바뀐 칸 (이 박자 칸 줄). */
function stgChange(b) {
  const v = stgV(), bits = [];
  if (b.at) bits.push(stgSpotLabel(b.at));
  if (b.posture) bits.push((v.postures[b.posture] || {}).label || b.posture);
  if (b.facing) bits.push(`${stgFacingLabel(b.facing)} 향함`);
  if (b.left != null) bits.push(b.left === STG_UNKNOWN ? '왼손 모름' : `왼손 ${b.left || '빈손'}`);
  if (b.right != null) bits.push(b.right === STG_UNKNOWN ? '오른손 모름' : `오른손 ${b.right || '빈손'}`);
  (b.contacts || []).forEach((c) => bits.push(stgContactText(c)));
  if ((b.ends || []).length) bits.push(`접촉 ${b.ends.length}개 끝`);
  if (b.memo) bits.push(b.memo);
  return bits.join(' · ');
}

/** 고치는 인물 칸 (인물 줄을 편 자리): 자세 · 자리 · 향함 · 손 · 접촉 · 부위 도식 · 메모. g.who 를 고친다. */
function stgPersonCard() {
  const g = S.stg, w = g.who;
  if (!w) return '<p class="small">출연진을 더하면 인물 칸이 보여요.</p>';
  const v = stgV();
  const st = stageState(g.scene, g.beat)[w];
  const own = stgBody(w, false);
  const mark = (field) => (g.beat === 0 ? '' : own && own[field] != null && own[field] !== '' ? `<button type="button" class="btn small ghost stg-keep" data-action="stgKeep" data-arg="${field}" title="이 박자에서 바꾼 것을 지우고 앞 박자 그대로 둬요">앞 박자 값으로 되돌리기</button>` : '<span class="small">앞 그대로</span>');
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
  const contactRows = actives.map(({ who, c, at: k }) => `<li class="between"><span><b>${esc(charName(who))}</b> ${esc(stgByLabel(c.by))} → <b>${esc(charName(c.to))}</b> ${esc((v.parts[c.part] || {}).label || c.part)} · ${esc((v.acts[c.act] || {}).label || c.act)}
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
  return `<div class="between"><span class="small">자세</span>${mark('posture')}</div>
    <div class="stg-poses" role="group" aria-label="자세">${Object.entries(v.postures).map(([id, p]) => `<button type="button" aria-pressed="${st.posture === id}" data-action="stgPosture" data-arg="${id}"><svg viewBox="0 0 34 40" aria-hidden="true">${STG_POSE_SVG[id] || ''}</svg>${esc(p.label)}</button>`).join('')}</div>
    <div class="stg-fields">
      <label for="stg-at">자리</label><span class="row"><select id="stg-at" data-stg-field="at">${spotOpts}</select>${mark('at')}</span>
      <label for="stg-facing">향함</label><span class="row"><select id="stg-facing" data-stg-field="facing">${faceOpts}</select>${mark('facing')}</span>
      <label for="stg-left">왼손</label><span class="row">${hand('left')}${mark('left')}</span>
      <label for="stg-right">오른손</label><span class="row">${hand('right')}${mark('right')}</span>
    </div>
    <div class="stg-touch">${stgBodyMap(on.concat(f.part ? [f.part] : []), by, minor)}
      <div class="stg-stack"><h3>접촉</h3>${contactRows ? `<ul class="stg-contacts">${contactRows}</ul>` : '<p class="small">지금 닿아 있는 곳이 없어요. 부위 점을 누르거나 아래에서 골라 더해요.</p>'}${form}</div></div>
    <label class="stg-stack stg-memo"><span class="small">메모 (목록 밖의 것)</span><input data-stg-field="memo" value="${esc(own ? own.memo : '')}" placeholder="예: 손에 힘을 주지 못함"></label>
    <div class="row"><button type="button" class="btn small ghost danger" data-action="stgCastDrop" data-arg="${esc(w)}">${esc(charName(w))} 출연진에서 빼기</button></div>`;
}

/** 인물 카드: 지금 박자의 인물마다 한 줄(읽기), '고치기'로 그 줄만 편다. 3D 에서는 읽기만. */
function stgPeople() {
  const g = S.stg, k = g.beat, sc = g.scene, three = S.stgView === '3d';
  const flags = (g.check ? g.check.violations : []).filter((x) => x.beat === k);
  const rest = P().characters.filter((c) => !sc.cast.includes(c.id));
  const add = !three && rest.length ? `<select class="stg-add-cast" data-stg-cast aria-label="출연진 더하기"><option value="">+ 인물 더하기</option>${rest.map((c) => stgOpt(c.id, c.name, '')).join('')}</select>` : '';
  const rows = sc.cast.map((w) => {
    const n = flags.filter((x) => x.who === w).length;
    const own = k > 0 && (sc.beats[k - 1].bodies || []).some((b) => b.who === w);
    const open = !three && g.open === w;
    return `<li class="stg-prow${open ? ' open' : ''}">
      <span class="nm">${stgDot(w)}<b>${esc(charName(w))}</b>${n ? ` <span class="chip bad">지적 ${n}</span>` : ''}${own ? ' <span class="chip confirmed">이 박자에 바뀜</span>' : ''}</span>
      ${three ? '' : `<button type="button" class="btn small" data-action="stgOpen" data-arg="${esc(w)}" aria-expanded="${open}">${open ? '다 고쳤어요' : '고치기'}</button>`}
      <span class="sum">${esc(stgSummary(w, k))}</span>
      ${open ? `<div class="stg-pbody" aria-label="${esc(charName(w))} 상태">${stgPersonCard()}</div>` : ''}</li>`;
  }).join('');
  return `<section class="card stg-people" aria-label="인물"><div class="between"><h2>인물 · ${stgBeatName(k)}</h2>${three ? '<span class="small">3D에서는 읽기만 해요</span>' : add}</div>
    ${sc.cast.length ? `<ul class="stg-plist">${rows}</ul>` : '<p class="small">출연진을 더하면 인물 칸이 보여요.</p>'}</section>`;
}

/** 무대 카드 옆 '이 박자' 칸: 박자 글, 이 박자에 바뀐 것, 그 박자의 지적 · 안내. */
function stgNow() {
  const g = S.stg, k = g.beat, ck = g.check || {}, b = k ? g.scene.beats[k - 1] : null, three = S.stgView === '3d';
  const flags = (ck.violations || []).filter((x) => x.beat === k);
  const moves = (ck.moves || []).filter((x) => x.beat === k);
  const stuck = Object.entries(((ck.paths || [])[k]) || {}).filter(([, r]) => r.blocked).map(([w]) => w);
  const gaps = stgGaps().filter((x) => x.k === k);
  const stale = (ck.stale || []).includes(k);
  let text;
  if (!b) text = '<p class="stg-now-t">시작 상태</p><p class="small">장면이 시작할 때 모두의 자리 · 자세 · 손이에요.</p>';
  else if (g.beatEdit && !three) text = `<div class="stg-stack">
      <label class="stg-stack"><span class="small">한 줄 설명</span><input data-stg-beat="note" value="${esc(b.note)}" placeholder="예: 도윤이 문을 열고 들어온다"></label>
      <label class="stg-stack"><span class="small">본문 문장 (쓴 뒤에 이어요)</span><input data-stg-beat="quote" value="${esc(b.quote)}" placeholder="본문에서 이 박자에 해당하는 문장 하나"></label>
      <div class="row"><button type="button" class="btn small ghost" data-action="stgBeatMove" data-arg="-1"${k > 1 ? '' : ' disabled'}>위로</button><button type="button" class="btn small ghost" data-action="stgBeatMove" data-arg="1"${k < g.scene.beats.length ? '' : ' disabled'}>아래로</button><button type="button" class="btn small ghost danger" data-action="stgBeatDrop">박자 지우기</button></div></div>`;
  else text = `${b.note ? `<p class="stg-now-t">${esc(b.note)}</p>` : ''}${b.quote ? `<p class="stg-quote">${esc(b.quote)}</p>` : `<p class="small">${b.note ? (g.role === 'text' ? '본문 문장이 없는 박자예요.' : '본문 문장은 쓴 뒤에 이어요.') : '(빈 박자)'}</p>`}`;
  const changes = b && b.bodies.length ? `<div class="stg-stack stg-tight"><span class="small stg-h">이 박자에 바뀐 것</span>${b.bodies.map((x) => `<span class="stg-chg">${stgDot(x.who)}<span><b>${esc(charName(x.who))}</b> ${esc(stgChange(x)) || '(바뀐 칸 없음)'}</span></span>`).join('')}</div>` : '';
  const items = [];
  flags.forEach((x) => items.push(`<div class="stg-flag">${stgRuleTag(x.rule)}<span>${esc(x.text)}</span></div>`));
  moves.forEach((x) => items.push(`<div class="stg-flag amber"><span class="chip">빠진 이동</span><span>${esc(x.text)}</span></div>`));
  if (stale) items.push('<div class="stg-flag amber"><span class="chip">본문과 다름</span><span>이 박자의 문장이 본문에 없어요.</span></div>');
  stuck.forEach((w) => items.push(`<div class="stg-flag plain"><span class="chip">막힌 이동</span><span>${esc(charName(w))}: 가구에 막혀 돌아갈 길이 없어 곧게 그렸어요. 자리를 바꾸거나 가구를 옮겨 보세요.</span></div>`));
  gaps.forEach((x) => items.push(`<div class="stg-flag plain"><span class="chip">계획과 다름</span><span>${esc(x.text)}</span></div>`));
  const list = items.length ? `<div class="stg-stack stg-tight">${flags.length ? `<span class="small stg-h">규칙 검수 ${flags.length}</span>` : ''}${items.join('')}</div>` : '';
  const btns = b && !three ? `<div class="row"><button type="button" class="btn small" data-action="stgBeatEdit" aria-expanded="${!!g.beatEdit}">${g.beatEdit ? '다 고쳤어요' : '박자 글 고치기'}</button></div>` : '';
  return `<span class="eyebrow">${stgBeatName(k)}</span>${text}${changes}${list}${btns}`;
}

/** 목차: 화 고르기 · 사건(스토리보드가 있으면 장면별로 묶음) · 지금 사건의 박자. 좁은 칸은 '지금 구역 ▾' 버튼. */
function stgToc() {
  const g = S.stg, n = g.n, e = ep(n);
  const eps = P().episodes.filter((x) => x.plot.events.length);
  const epPick = `<label class="stg-ep"><span class="small">화</span><select data-stg-ep aria-label="화 고르기">${eps.map((x) => stgOpt(String(x.plot.number), `${x.plot.number}화 ${x.plot.title}`, String(n))).join('')}</select></label>`;
  const roles = (k) => ['plan', 'text'].filter((r) => g.view.scenes.some((x) => x.event === k - 1 && (x.scene.role || 'plan') === r)).map((r) => (r === 'plan' ? '계획' : '본문')).join(' · ') || '없음';
  const evs = (e && e.plot.events) || [];
  const evItem = (k) => `<a class="outline-item stg-ev" href="${base()}/stage/${n}/${k}"${k === g.ev ? ' aria-current="page"' : ''} title="${esc(evs[k - 1])}"><span class="n">${k}</span><span class="tl">${esc(evs[k - 1])}</span><span class="st">${roles(k)}</span></a>`;
  const bd = g.view.board || { events: [], stale: false };
  const grouped = bd.events.length > 0;
  const events = grouped
    ? `${bd.stale ? '<p class="outline-note warn-text">스토리보드가 낡았어요</p>' : ''}${stgEventGroups(evs.length, bd.events).map((x) => `<div class="outline-h">${x.no ? `장면 ${x.no}${x.spot || x.place ? ` · ${esc(x.spot || x.place)}` : ''}` : '맡은 장면 없음'}</div>${x.events.map(evItem).join('')}`).join('')}`
    : `<div class="outline-h">사건</div>${evs.map((_, i) => evItem(i + 1)).join('')}`;
  let beats = '';
  const viol = g.check ? g.check.violations : [];
  if (g.scene) {
    const sc = g.scene, stale = new Set(g.check ? g.check.stale : []), differ = new Set(stgGaps().map((x) => x.k));
    const row = (k) => {
      const b = k ? sc.beats[k - 1] : null, nf = viol.filter((x) => x.beat === k).length;
      const text = b ? b.quote || b.note || '(빈 박자)' : '시작 상태';
      const st = [nf ? `<span class="st bad">지적 ${nf}</span>` : '', stale.has(k) ? '<span class="st warn">본문과 달라요</span>' : '', differ.has(k) ? '<span class="st">계획과 달라요</span>' : ''].join('');
      return `<button type="button" class="outline-item stg-bt" data-action="stgBeat" data-arg="${k}"${k === g.beat ? ' aria-current="step"' : ''}><span class="n">${k ? k : '○'}</span><span class="tl${b && b.quote ? ' q' : ''}">${esc(text)}</span>${st}</button>`;
    };
    const add = S.stgView === '3d' ? '' : '<button type="button" class="btn small ghost" data-action="stgBeatAdd">+ 박자 더하기</button>';
    beats = `<div class="outline-sep"></div><div class="outline-h stg-beat-h"><span>사건 ${g.ev} 박자</span>${add}</div>${[0, ...sc.beats.map((_, i) => i + 1)].map(row).join('')}
      ${sc.beats.some((b) => b.quote) ? '<p class="outline-note small">명조 글은 본문 문장, 고딕 글은 작가 설명이에요.</p>' : ''}`;
  }
  const nf = g.scene ? viol.filter((x) => x.beat === g.beat).length : 0;
  const now = `사건 ${g.ev}${g.scene ? ` · ${stgBeatName(g.beat)}` : ''}${nf ? ` <span class="chip bad">지적 ${nf}</span>` : ''}`;
  return outlineNav({ id: 'stg-toc', label: '사건과 박자', now, body: `${eps.length > 1 ? epPick : ''}${events}${beats}` });
}

/** 박자 줄: 재생 · 박자 눈금(지적이 있는 박자에 빨간 점). 좁은 칸에서는 아래에 붙고 앞뒤 버튼과 'k / N박자'로 바뀐다. */
function stgBar() {
  const g = S.stg, max = g.scene.beats.length, k = g.beat;
  const viol = g.check ? g.check.violations : [];
  const cnt = (i) => viol.filter((x) => x.beat === i).length;
  const ticks = [...Array(max + 1).keys()].map((i) => {
    const n = cnt(i);
    return `<button type="button" class="stg-tick" data-action="stgBeat" data-arg="${i}"${i === k ? ' aria-current="step"' : ''} aria-label="${stgBeatName(i)}${n ? `, 지적 ${n}` : ''}">${i === 0 ? '시작' : i}${n ? '<i class="fl" aria-hidden="true"></i>' : ''}</button>`;
  }).join('');
  const n = cnt(k);
  return `<div class="stg-bar" role="group" aria-label="박자 옮기기">
    <button type="button" class="btn icon-btn stg-step" data-action="stgStep" data-arg="-1" aria-label="앞 박자"${k > 0 ? '' : ' disabled'}>◀</button>
    <button type="button" class="btn" data-action="stgPlay"${max ? '' : ' disabled'}>${g.playing ? '❚❚ 멈춤' : '▶ 재생'}</button>
    <div class="stg-ticks">${ticks}</div>
    <span class="stg-bar-now"><b>${k === 0 ? `시작 · ${max}박자` : `${k} / ${max}박자`}</b>${n ? `<span class="bad">지적 ${n}</span>` : ''}</span>
    <button type="button" class="btn icon-btn stg-step" data-action="stgStep" data-arg="1" aria-label="다음 박자"${k < max ? '' : ' disabled'}>▶</button></div>`;
}

/** 방 카드: 읽는 모양이 기본이고 '방 고치기'로 이 카드에서 기준점을 고친다(평면도도 기준점 끌기로 바뀐다). */
function stgRoomCard() {
  const g = S.stg, r = g.room, three = S.stgView === '3d', edit = g.mode === 'room' && !three;
  if (!r) return '';
  const used = g.view.scenes.filter((x) => x.scene.room === r.id && x.scene.id !== g.sid).length;
  const btn = three ? '' : `<button type="button" class="btn small" data-action="stgMode" data-arg="${edit ? 'people' : 'room'}" aria-expanded="${edit}">${edit ? '다 고쳤어요' : '방 고치기'}</button>`;
  const sum = `${esc(r.name)} · ${r.w} × ${r.h}m · ${r.place ? `지도 장소 ${esc(r.place)}` : '지도 장소에 묶이지 않음'}${used ? ` · 이 방을 쓰는 다른 장면 ${used}개` : ''}`;
  return `<section class="card tight stg-room${edit ? ' editing' : ''}" aria-label="방"><div class="between"><h2>${edit ? '방 고치기' : '방'}</h2>${btn}</div>
    ${edit ? stgRoomPanel() : `<p class="stg-room-sum">${sum}</p><div class="row">${r.anchors.map((a) => `<span class="chip">${esc(a.name)}</span>`).join('')}</div>`}</section>`;
}

function stgRoomPanel() {
  const g = S.stg, r = g.room;
  const kinds = { bed: '침대', door: '문', window: '창', desk: '책상', chair: '의자', sofa: '소파', table: '탁자', wall: '벽', seat: '자리', vehicle: '차', landmark: '표지', ground: '길 · 땅', other: '기타' };  // stage.ANCHOR_KINDS
  const used = g.view.scenes.filter((x) => x.scene.room === r.id && x.scene.id !== g.sid).length;
  return `${used ? `<p class="small warn-text">이 방을 쓰는 다른 장면 ${used}개도 바뀌어요.</p>` : ''}
    <div class="stg-fields">
      <label for="stg-rname">이름</label><input id="stg-rname" data-stg-room="name" value="${esc(r.name)}">
      <label for="stg-rplace">장소</label><input id="stg-rplace" data-stg-room="place" value="${esc(r.place)}" list="stg-places" placeholder="지도 장소에 묶으면 다른 장면에서도 골라요">
      <label for="stg-rw">크기 (m)</label><span class="row"><input id="stg-rw" class="stg-num" type="number" min="1" max="40" step="0.1" data-stg-room="w" value="${r.w}" aria-label="가로"> × <input class="stg-num" type="number" min="1" max="40" step="0.1" data-stg-room="h" value="${r.h}" aria-label="세로"></span>
    </div>
    <datalist id="stg-places">${stgPlaces().map((x) => `<option value="${esc(x)}">`).join('')}</datalist>
    <p class="small">평면도에서 기준점을 끌어 옮겨요. 짧은 선이 기준점의 앞쪽이에요. 붙은 기준점은 부모를 따라 움직이고, 붙은 면을 따라서만 끌려요.</p>
    <ul class="stg-anchors">${r.anchors.map((a) => `<li class="row"><input class="stg-aname" data-stg-anchor-name="${esc(a.id)}" value="${esc(a.name)}" aria-label="기준점 이름">
      <select data-stg-anchor-kind="${esc(a.id)}" aria-label="종류">${Object.entries(kinds).map(([k, l]) => stgOpt(k, l, a.kind)).join('')}</select>
      <select data-stg-anchor-on="${esc(a.id)}" aria-label="붙은 곳" title="붙은 곳: 부모를 옮기거나 돌리면 함께 움직여요">${stageAttachOptions(r, a.id).map(([k, l]) => stgOpt(k, k ? `붙음: ${l}` : '붙지 않음', a.parent ? `${a.parent}|${a.face}` : '')).join('')}</select>
      <button type="button" class="btn small ghost" data-action="stgRotate" data-arg="${esc(a.id)}" title="상자를 90도 돌려요. 붙은 기준점도 함께 돌아요">↻ 돌리기</button>
      <button type="button" class="btn small ghost danger" data-action="stgAnchorDrop" data-arg="${esc(a.id)}">빼기</button>${stgDropNote(r, a.id)}</li>`).join('')}</ul>
    <div class="row"><button type="button" class="btn small" data-action="stgAnchorAdd">+ 기준점 더하기</button></div>`;
}

/** 빼기 옆에 함께 빠지는 기준점 이름. 없으면 빈 글. */
function stgDropNote(room, aid) {
  const kids = stageChildren(room, aid);
  if (!kids.length) return '';
  return ` <span class="small">${esc(kids.map((x) => x.name).join(' · '))}도 함께 빠져요</span>`;
}

function stgPlaces() {
  const p = P();
  const names = (p.elements || []).filter((el) => el.kind === '장소').map((el) => el.name);
  (p.world.locations || []).forEach((x) => names.push(String(x).split(/[:：\-–—,(]/)[0].trim()));
  return [...new Set(names.filter(Boolean))];
}

/** 방 고르기 칸의 작은 그림: 벽과 기준점 상자만. shape = { w, h, anchors: [[x, y, w, h]] } (stage.vocab 의 room_shapes, 또는 이미 있는 방) */
function stgThumb(shape) {
  if (!shape) return '';
  const s = Math.min(88 / shape.w, 52 / shape.h), ox = (100 - shape.w * s) / 2, oy = (64 - shape.h * s) / 2;
  const box = ([x, y, w, h]) => `<rect class="a" x="${ox + x * s}" y="${oy + y * s}" width="${Math.max(w * s, 1.5)}" height="${Math.max(h * s, 1.5)}"/>`;
  return `<svg viewBox="0 0 100 64" aria-hidden="true"><rect class="w" x="${ox}" y="${oy}" width="${shape.w * s}" height="${shape.h * s}"/>${shape.anchors.map(box).join('')}</svg>`;
}

function stgNewCard() {
  const g = S.stg, k = g.pick;
  const bs = stgBoardOf(g);
  const hints = bs ? bs.hints : [];
  const rooms = stgRoomOrder(g.view.rooms, hints);
  const shapes = g.view.vocab.room_shapes || {};
  const tpl = Object.entries(g.view.vocab.rooms);
  const where = bs ? [bs.place, bs.spot].filter(Boolean).join(' · ') : '';
  // 스토리보드 자리에 맞는 방이 없으면 빈 방 + 플롯 초안을 먼저 권한다: AI 가 장소에 필요한 기준점을 더하자고 한다 (2026-10-29 15화 사건 1)
  const draft = bs && !hints.length ? (() => {
    const b = jobBtn('stage_draft', g.n, '빈 방에서 플롯 초안 받기');
    return `<section class="card stg-fresh"><h2>맞는 방이 없어요</h2>
    <p class="desc">스토리보드 자리${where ? `(${esc(where)})` : ''}와 같은 방이 없어요. 빈 방에서 시작하면 AI가 박자에 나오는 장소(차 · 창 · 가구)를 기준점으로 더하자고 해요. 받은 초안은 비교한 뒤 적용해요.</p>
    <div class="row"><button type="button" class="btn primary" data-action="stgAiFresh"${b.attr}>${b.label}</button></div></section>`;
  })() : '';
  const own = (r) => { const w = stageResolve(r); return { w: w.w, h: w.h, anchors: w.anchors.map((a) => [a.x, a.y, a.w, a.h]) }; };
  const cast = ((ep(g.n) || {}).plot || {}).characters || [];
  return `${draft}<section class="card stg-empty" aria-label="새 장면"><h2>${draft ? '직접 방을 골라 시작하기' : '이 사건에는 아직 연출이 없어요'}</h2>
    <p class="desc">${bs ? `스토리보드 장면 ${bs.no}${where ? `(${esc(where)})` : ''}의 인물이 문 앞에 선 채로 시작해요.` : `방을 고르면 이 화 플롯의 등장 인물${cast.length ? ` ${cast.length}명` : ''}이 문 앞에 선 채로 시작해요.`} AI가 먼저 짜게 하려면 위의 '플롯에서 초안'을 눌러요.</p>
    ${rooms.length ? `<fieldset class="stg-pick"><legend class="small">이 작품의 방</legend><div class="stg-rooms">
      ${rooms.map((r) => `<label class="stg-room-opt"><input type="radio" name="stg-room" value="${esc(r.id)}" data-stg-pick="room"${k.room === r.id ? ' checked' : ''}>${stgThumb(own(r))}<b>${esc(r.name)}</b><span class="small">${r.w} × ${r.h}m</span>${r.place ? `<span class="chip confirmed">${esc(r.place)}</span>` : ''}${hints.includes(r.id) ? '<span class="chip">스토리보드 장소</span>' : ''}</label>`).join('')}</div></fieldset>` : ''}
    <fieldset class="stg-pick"><legend class="small">틀에서 새 방</legend><div class="stg-rooms">
      ${tpl.map(([t, l]) => `<label class="stg-room-opt"><input type="radio" name="stg-room" value="${esc(t)}" data-stg-pick="template"${!k.room && k.template === t ? ' checked' : ''}>${stgThumb(shapes[t])}<b>${esc(l)}</b>${shapes[t] ? `<span class="small">${shapes[t].w} × ${shapes[t].h}m</span>` : ''}</label>`).join('')}</div></fieldset>
    <div class="stg-new-foot"><label class="stg-stack stg-new-name"><span class="small">새 방 이름</span><input data-stg-pick="name" value="${esc(k.name)}" placeholder="비우면 틀 이름" aria-label="새 방 이름"${k.room ? ' disabled' : ''}></label>
      <button type="button" class="btn${draft ? '' : ' primary'}" data-action="stgCreate">장면 만들기</button></div></section>`;
}

// ----- AI 장면: 플롯에서 초안 · 본문에서 뽑기, 비교 · 적용 · 적용 취소 -----

/** 작은 평면도: 장면이 끝난 상태 (비교 보기). 인물 원과 이름, 접촉 선만. */
function stgMiniSvg(room, scene, fresh = []) {
  if (!room) return '<p class="small">방을 찾지 못했어요.</p>';
  room = stageResolve(room);
  const sc = stgScale(room), k = scene.beats.length;
  const px = ([x, y]) => [sc.ox + x * sc.s, sc.oy + y * sc.s];
  const st = stageState(scene, k), pos = stageLayouts(room, scene, k)[k];
  const color = (w) => STG_COLORS[Math.max(0, scene.cast.indexOf(w)) % STG_COLORS.length];
  let out = `<rect class="stg-wall" x="${sc.ox}" y="${sc.oy}" width="${room.w * sc.s}" height="${room.h * sc.s}" rx="2"/>`;
  room.anchors.forEach((a) => {
    const [x, y] = px([a.x, a.y]);
    out += `<g class="stg-anchor ${esc(a.kind)}${fresh.includes(a.id) ? ' added' : ''}"><rect x="${x}" y="${y}" width="${Math.max(a.w * sc.s, 4)}" height="${Math.max(a.h * sc.s, 4)}" rx="4"/><text x="${x + a.w * sc.s / 2}" y="${y + a.h * sc.s / 2 + 4}" text-anchor="middle">${esc(a.name)}</text></g>`;
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
  const room = prop.room || prop.grown || g.view.rooms.find((r) => r.id === prop.scene.room) || null;
  const fresh = (prop.adds || []).map((x) => x.anchor.id);
  const from = prop.role === 'text' ? '본문에서 뽑은 장면' : '플롯에서 받은 초안';
  const notes = [];
  if (prop.dropped) notes.push(`미성년 인물이 낀 성적 접촉 ${prop.dropped}개를 뺐어요.`);
  if (prop.violations.length) notes.push(`규칙 검수 ${prop.violations.length}개: ${prop.violations.slice(0, 3).map((v) => `${v.beat}박자 ${v.text}`).join(' · ')}`);
  if (prop.stale.length) notes.push(`본문에 없는 문장을 가리키는 박자 ${prop.stale.length}개`);
  (prop.moves || []).forEach((m) => notes.push(`${m.beat}박자 빠진 이동: ${m.text}`));
  prop.notes.filter((x) => !/성적 접촉/.test(x)).forEach((x) => notes.push(x));
  return `<section class="card stg-cmp" aria-label="AI 장면 비교"><div class="between"><h2>${from} 비교</h2>
      <div class="row"><button type="button" class="btn small primary" data-action="stgApply">${cur ? '이 장면으로 바꾸기' : '적용'}</button><button type="button" class="btn small ghost" data-action="stgDiscard">버리기</button></div></div>
    <p class="small">장면을 통째로 바꿔요. 바꾼 뒤에도 '적용 취소'로 한 번 되돌릴 수 있어요.${prop.room ? ` 새 방 '${esc(prop.room.name)}'도 만들어요.` : ''}</p>
    ${stgAddList(prop)}
    ${notes.length ? `<ul class="stg-viol small">${notes.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
    <div class="stg-cmp-grid"><div><h3>지금 장면</h3>${cur ? stgMiniSvg(g.room, cur) + stgBeatList(cur, prop.scene) : '<p class="small">아직 없어요</p>'}</div>
      <div><h3>AI 장면</h3>${stgMiniSvg(room, prop.scene, fresh)}${stgBeatList(prop.scene, cur)}</div></div></section>`;
}

/** AI 가 더하자는 기준점 목록. 공용 방이면 복사한 장면 전용 방에 더하는 것이 기본이고, 공용 방에 바로 더하기를 고를 수 있다. */
function stgAddList(prop) {
  const adds = prop.adds || [];
  if (!adds.length) return '';
  const g = S.stg, kinds = g.view.vocab.kinds || {};
  const base = prop.grown ? g.view.rooms.find((r) => r.id === prop.grown.id) : null;
  const target = prop.room ? `새 방 '${esc(prop.room.name)}'` : base && prop.room_shared && !g.shared ? `'${esc(base.name)}' 방을 복사한 장면 전용 방` : base ? `'${esc(base.name)}'` : '새 방';
  return `<div class="stg-adds"><b>더할 기준점 ${adds.length}개</b> <span class="small">${target}에 더해요. 자리는 코드가 정했어요. 적용한 뒤 '방 고치기'에서 끌어 옮겨요.</span>
    <ul>${adds.map((x) => `<li><span class="chip">${esc(kinds[x.anchor.kind] || x.anchor.kind)}</span> ${esc(x.anchor.name)} <span class="small">${esc(x.where)}</span></li>`).join('')}</ul>
    ${prop.room_shared && base ? `<label class="row small"><input type="checkbox" data-stg-shared${g.shared ? ' checked' : ''}> 공용 방 '${esc(base.name)}'에 바로 더하기 (이 방을 쓰는 다른 장면에도 생겨요)</label>` : ''}</div>`;
}

/** 머리의 AI 버튼: 계획이면 플롯에서 초안, 본문이면 본문에서 뽑기. */
function stgAiBtn() {
  const g = S.stg, e = ep(g.n);
  if (g.role === 'text') {
    const b = jobBtn('stage_extract', g.n, '본문에서 뽑기');
    return e && e.text ? `<button type="button" class="btn" data-action="stgAi"${b.attr}>${b.label}</button>` : '<span class="small">본문을 쓴 뒤 뽑아요</span>';
  }
  const b = jobBtn('stage_draft', g.n, '플롯에서 초안');
  return `<button type="button" class="btn" data-action="stgAi"${b.attr}>${b.label}</button>`;
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
  // 공용 목차 틀(.outline-wrap.stg-wrap) 위의 화면. 칸 폭 규칙은 창이 아니라 @container outline · stgcol 로 건다 (docs/design/layout.md)
  st.textContent = `
.stg-col { container: stgcol / inline-size; display: flex; flex-direction: column; gap: var(--gap-stack); min-width: 0; }
.stg-col > .card, .stg-col > .note { margin: 0; }
.stg-ep { display: flex; flex-direction: column; gap: 6px; padding: 0 4px 6px; }
.stg-ep select { width: 100%; }
.stg-wrap .outline-list { padding-bottom: 8px; }
.stg-wrap .outline-item .tl { flex: 1 1 auto; }
.stg-wrap .outline-item .tl.q { font-family: var(--serif); }
.stg-wrap .outline-item .st { flex: none; }
.stg-wrap .outline-item .st + .st { margin-left: 0; }
.stg-wrap .outline-item .st.bad { color: var(--red); font-weight: 700; }
.stg-wrap .outline-item.stg-ev[aria-current] { background: var(--surface); border-color: var(--line); color: var(--text); }
.stg-beat-h { display: flex; align-items: center; justify-content: space-between; gap: 6px; padding-right: 0; }
.stg-beat-h .btn { min-height: 32px; padding: 0 8px; }
@media (pointer: coarse), (max-width: 640px) { .stg-beat-h .btn { min-height: var(--touch-min); } }
.stg-stage { gap: 14px; }
.stg-title { gap: 4px 10px; }
.stg-title h2 { margin: 0; }
.stg-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px 20px; align-items: start; }
@container stgcol (min-width: 760px) { .stg-grid { grid-template-columns: minmax(0, 1fr) 300px; } }
.stg-pic { min-width: 0; }
.stg-plan { width: 100%; height: auto; max-height: min(72vh, 680px); display: block; background: var(--canvas); border-radius: 8px; touch-action: none; user-select: none; }
.stg-now { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.stg-now p { margin: 0; }
.stg-now-t { font-weight: 700; line-height: 1.5; }
.stg-quote { font-family: var(--serif); font-size: 0.9375rem; line-height: 1.7; }
.stg-h { font-weight: 700; }
.stg-stack { display: flex; flex-direction: column; gap: 8px; }
.stg-stack.stg-tight { gap: 6px; }
.stg-chg { display: flex; gap: 6px; align-items: baseline; font-size: 0.8125rem; line-height: 1.55; }
.stg-flag { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: flex-start; padding: 8px 10px; border-radius: 8px; background: var(--red-soft); color: var(--err-ink); font-size: 0.8125rem; line-height: 1.55; }
.stg-flag .chip { flex: none; background: var(--surface); color: inherit; }
.stg-flag > span:last-child { flex: 1 1 160px; min-width: 0; }
.stg-flag.amber { background: var(--amber-soft); color: var(--amber-ink); }
.stg-flag.plain { background: var(--bg); color: var(--text-2); }
.stg-foot { align-items: flex-start; }
.stg-legend { display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: center; font-size: 0.75rem; color: var(--muted); }
.stg-legend svg { vertical-align: middle; margin-right: 4px; }
.stg-bar { display: flex; align-items: center; gap: 8px; padding: 6px; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; }
.stg-ticks { flex: 1 1 auto; min-width: 0; display: flex; gap: 4px; overflow-x: auto; }
.stg-tick { position: relative; flex: 1 0 44px; min-height: var(--touch-min); padding: 0 6px; border: 1px solid transparent; border-radius: 8px; background: var(--bg); color: var(--text-2); font: inherit; font-size: 0.8125rem; font-weight: 700; cursor: pointer; }
.stg-tick:hover { background: var(--btn); color: var(--text); }
.stg-tick[aria-current] { background: var(--accent); color: var(--on-accent); }
.stg-tick .fl { position: absolute; top: 5px; right: 6px; width: 8px; height: 8px; border-radius: 50%; background: var(--red); }
.stg-tick[aria-current] .fl { box-shadow: 0 0 0 2px var(--surface); }
.stg-step, .stg-bar-now { display: none; }
.stg-bar-now { flex: 1 1 auto; flex-direction: column; align-items: center; line-height: 1.3; font-size: 0.875rem; }
.stg-bar-now .bad { color: var(--red); font-size: 0.75rem; font-weight: 700; }
.stg-plist { list-style: none; margin: 0; padding: 0; }
.stg-prow { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 4px 12px; align-items: center; padding: 10px 0; border-top: 1px solid var(--rule); }
.stg-prow:first-child { border-top: 0; padding-top: 0; }
.stg-prow .nm { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.stg-prow .nm .stg-dot { width: 12px; height: 12px; margin: 0; }
.stg-prow .sum { grid-column: 1 / -1; font-size: 0.8125rem; color: var(--text-2); line-height: 1.55; }
.stg-pbody { grid-column: 1 / -1; margin-top: 6px; padding: 16px; border: 1px solid var(--sel-line); border-radius: 10px; background: var(--sel-bg); display: flex; flex-direction: column; gap: 12px; }
.stg-room.editing { border-color: var(--sel-line); }
.stg-room-sum { margin: 0; font-size: 0.8125rem; color: var(--text-2); }
.stg-num { width: 80px; }
.stg-aname { width: 120px; }
.stg-empty { border-style: dashed; }
.stg-pick { border: 0; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.stg-pick legend { padding: 0; margin-bottom: 8px; font-weight: 700; }
.stg-rooms { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.stg-room-opt { position: relative; display: flex; flex-direction: column; gap: 4px; padding: 10px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); font-size: 0.8125rem; cursor: pointer; }
.stg-room-opt input { position: absolute; top: 14px; right: 14px; margin: 0; accent-color: var(--accent); }
.stg-room-opt:has(input:checked) { border-color: var(--sel-line); background: var(--sel-bg); box-shadow: inset 0 0 0 1px var(--sel-line); }
.stg-room-opt svg { width: 100%; height: 56px; display: block; background: var(--canvas); border-radius: 6px; }
.stg-room-opt svg .w { fill: none; stroke: var(--text-2); stroke-width: 1.5; }
.stg-room-opt svg .a { fill: var(--chip); stroke: var(--line-strong); stroke-width: 0.6; }
.stg-room-opt .chip { align-self: flex-start; }
.stg-new-foot { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; justify-content: space-between; }
.stg-new-name { flex: 0 1 320px; gap: 6px; }
@container outline (max-width: 720px) {
  .stg-bar { order: 9; position: sticky; bottom: calc(8px + var(--sb, 0px)); z-index: var(--z-sticky); box-shadow: var(--shadow-bar); }
  .stg-ticks { display: none; }
  .stg-step { display: inline-flex; }
  .stg-bar-now { display: flex; }
  .stg-beat-h .btn { min-height: var(--touch-min); }
  .stg-rooms { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .stg-new-foot .btn { width: 100%; }
  .stg-prow .btn.small { min-height: var(--touch-min); }
}
@media (forced-colors: active) { .stg-tick[aria-current], .stg-room-opt:has(input:checked) { outline: 2px solid Highlight; } }
.stg-cmp { gap: 10px; }
.stg-cmp-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; }
@container stgcol (max-width: 640px) { .stg-cmp-grid { grid-template-columns: minmax(0, 1fr); } }
.stg-cmp-grid h3 { margin: 0 0 6px; font-size: 0.875rem; }
.stg-cmp-grid svg { width: 100%; height: auto; display: block; background: var(--canvas); border-radius: 8px; }
.stg-cmp-beats { margin: 8px 0 0; padding-left: 20px; font-size: 0.8125rem; }
.stg-cmp-beats li.new { background: var(--amber-soft); }
.stg-wall { fill: none; stroke: var(--text-2); stroke-width: 4; }
.stg-anchor rect { fill: var(--chip); stroke: var(--line-strong); stroke-width: 1; }
.stg-anchor.door rect, .stg-anchor.window rect { fill: var(--accent-soft); }
.stg-anchor.added rect { stroke: var(--accent); stroke-width: 2; stroke-dasharray: 4 3; }
.stg-adds { margin: 8px 0; }
.stg-adds ul { list-style: none; padding: 0; margin: 6px 0; display: flex; flex-direction: column; gap: 4px; }
.stg-anchor.edit { cursor: grab; }
.stg-anchor text { font-size: calc(12px * var(--u, 1)); fill: var(--text-2); font-family: var(--sans); pointer-events: none; }
.stg-front { stroke: var(--accent); stroke-width: 2.5; }
.stg-person { cursor: grab; }
.stg-person circle.body { stroke: var(--surface); stroke-width: 2.5; }
.stg-person.cur circle.body { stroke: var(--text); }
.stg-person.bad circle.body { stroke: var(--red); stroke-width: 3; }
.stg-person .ini { font-size: calc(13px * var(--u, 1)); font-weight: 700; fill: var(--on-stage); font-family: var(--sans); text-anchor: middle; dominant-baseline: central; pointer-events: none; }
.stg-person .label { fill: var(--text); font-size: calc(12px * var(--u, 1)); font-weight: 700; font-family: var(--sans); pointer-events: none; paint-order: stroke; stroke: var(--canvas); stroke-width: calc(4px * var(--u, 1)); stroke-linejoin: round; }
.stg-leader { stroke: var(--muted); stroke-width: 1; fill: none; pointer-events: none; }
.stg-person .face { opacity: 0.85; }
.stg-contact { stroke-width: 2.5; stroke-dasharray: 5 4; fill: none; }
.stg-contact.bad { stroke: var(--red); }
.stg-move { stroke: var(--muted); stroke-width: 1.5; fill: none; marker-end: url(#stg-arrow); }
.stg-move.blocked { stroke: var(--red); stroke-dasharray: 5 4; }
.stg-ghost circle { fill: none; stroke-width: 2; stroke-dasharray: 3 3; opacity: 0.55; }
.stg-ghost text { font-size: calc(12px * var(--u, 1)); font-weight: 700; fill: var(--muted); font-family: var(--sans); text-anchor: middle; dominant-baseline: central; opacity: 0.8; }
.stg-ghost-note { font-size: calc(11px * var(--u, 1)); fill: var(--muted); font-family: var(--sans); }
.stg-dot { display: inline-block; width: 10px; height: 10px; margin-right: 6px; border-radius: 50%; vertical-align: 0; flex: none; forced-color-adjust: none; }
.stg-poses { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 4px; }
.stg-poses button { padding: 4px 2px 2px; border: 1px solid transparent; border-radius: 8px; background: var(--surface); color: var(--text-2); font: inherit; font-size: 0.6875rem; cursor: pointer; display: flex; flex-direction: column; align-items: center; gap: 2px; min-height: 58px; }
.stg-poses button[aria-pressed="true"] { border-color: var(--accent); background: var(--accent-soft); color: var(--accent-ink); font-weight: 700; }
.stg-poses svg { width: 34px; height: 40px; }
.stg-poses svg * { stroke: currentColor; stroke-width: 2.4; stroke-linecap: round; fill: none; }
.stg-fields { display: grid; grid-template-columns: 64px minmax(0, 1fr); gap: 6px 10px; align-items: center; font-size: 0.8125rem; }
.stg-fields > label { color: var(--muted); }
.stg-fields select, .stg-fields input:not([type=number]) { min-width: 0; flex: 1; }
.stg-touch { display: grid; grid-template-columns: 124px minmax(0, 1fr); gap: 12px; align-items: start; }
@container stgcol (max-width: 480px) { .stg-touch { grid-template-columns: minmax(0, 1fr); } .stg-poses { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
.stg-bodymap { display: flex; gap: 6px; }
.stg-bodymap figure { margin: 0; }
.stg-bodymap svg { width: 56px; height: 120px; }
.stg-bodymap .sil { fill: var(--chip); stroke: var(--line-strong); stroke-width: 1; }
.stg-bodymap .dot { fill: var(--surface); stroke: var(--line-strong); stroke-width: 1; cursor: pointer; }
.stg-bodymap .dot.on { fill: var(--stage-2); stroke: var(--stage-2); }
.stg-bodymap .dot.by { fill: var(--stage-1); stroke: var(--stage-1); }
.stg-bodymap figcaption { font-size: 0.6875rem; color: var(--muted); text-align: center; }
.stg-contacts { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; font-size: 0.8125rem; }
.stg-add { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
.stg-add label { display: flex; flex-direction: column; gap: 2px; }
.stg-add button { grid-column: 1 / -1; }
.stg-memo { gap: 4px; }
.stg-anchors { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
`;
  document.head.appendChild(st);
}

/** 평면도 범례: 기호 + 낱말. */
function stgLegend() {
  const line = (w, dash) => `<svg width="22" height="6" aria-hidden="true"><line x1="0" y1="3" x2="22" y2="3" stroke="var(--muted)" stroke-width="${w}" stroke-dasharray="${dash}"/></svg>`;
  const g = S.stg;
  return `<div class="stg-legend"><span><svg width="12" height="12" aria-hidden="true"><path d="M1 11L11 11L6 1Z" fill="var(--muted)"/></svg>향한 쪽</span><span>${line(2.5, '5 4')}접촉</span><span>${line(1.5, '0')}이번 박자 이동</span>
    <span><svg width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="5.5" fill="none" stroke="var(--red)" stroke-width="2.5"/></svg>지적</span>
    <span>${g.mode === 'room' ? '기준점을 끌어 옮겨요' : '인물을 끌어 놓으면 가까운 기준점에 붙어요'}</span></div>`;
}

function viewStage(n) {
  stgCss();
  const g = S.stg;
  const e = ep(n);
  const head = (desc, right = '') => header(`작품 도구 · ${n}화${e ? ` ${esc(e.plot.title)}` : ''}${g ? ` · 사건 ${g.ev} / ${(e && e.plot.events.length) || 0}` : ''}`, '장면 연출', desc, right);
  const eps = P().episodes.filter((x) => x.plot.events.length);
  const epPick = `<label class="row small">화 <select data-stg-ep aria-label="화 고르기">${eps.map((x) => stgOpt(String(x.plot.number), `${x.plot.number}화 ${x.plot.title}`, String(n))).join('')}</select></label>`;
  if (!e || !g) return `${head('방 하나 안에서 인물의 자리 · 자세 · 접촉을 박자마다 짜고 재생해요.')}<section class="card"><div class="empty">${eps.length ? `<p>사건이 있는 화를 고르세요.</p>${epPick}` : `<p>플롯에 사건이 있는 화가 아직 없어요. ${esc(stepLabel('arc'))}에서 사건을 적으면 사건마다 연출을 짤 수 있어요.</p><a class="btn primary" href="${base()}/arc">${esc(stepLabel('arc'))}으로</a>`}</div></section>`;
  const evText = e.plot.events[g.ev - 1] || '';
  if (!evText) return `${head('')}<section class="card"><div class="empty"><p>${g.ev}번째 사건이 없어요.</p>${epPick}</div></section>`;
  const has2 = (role) => !!stgRow(g, role);
  const roles = `<div class="seg" role="group" aria-label="장면 역할">${[['plan', '계획'], ['text', '본문']].map(([r, l]) => `<button type="button" aria-pressed="${g.role === r}" data-action="stgRole" data-arg="${r}" title="${r === 'plan' ? '쓰기 전에 짠 장면' : '본문에서 뽑은 장면'}">${l}${has2(r) ? ' ●' : ''}</button>`).join('')}</div>`;
  const prop = stgProposal(g);
  const cmp = prop ? stgCompare(prop) : '';
  const wrap = (main) => outlineDoc(stgToc(), `<div class="stg-col">${main}</div>`, { wide: true, cls: 'stg-wrap' });
  if (!g.scene && g.role === 'text') return `${head(esc(evText), roles + stgAiBtn())}${wrap(`${cmp}<section class="card stg-empty"><h2>본문에서 뽑기 전이에요</h2>
    <p class="desc">본문 장면은 본문에서 자리 · 자세 · 접촉을 뽑은 결과예요. 뽑으면 여기서 규칙으로 판정하고 계획 장면과 견줘요. 검수할 때도 함께 뽑아요(검수 화면의 '검수 때 함께 뽑기').${has2('plan') ? '' : ' 이 사건에는 계획 장면도 아직 없어요.'}</p></section>`)}`;
  if (!g.scene) return `${head(esc(evText), roles + stgAiBtn())}${wrap(cmp + stgNewCard())}`;
  const ck = g.check || { violations: [], stale: [], event_changed: false };
  const three = S.stgView === '3d' && typeof s3Pane === 'function';
  const more = menuBtn('stg-more', '<span aria-hidden="true">⋯</span>', () => `${g.scene.prev ? '<button type="button" class="pop-item" data-action="stgUndo">적용 취소<span class="small">마지막 AI 적용 전으로</span></button>' : ''}<button type="button" class="pop-item danger" data-action="stgDelete">장면 지우기<span class="small">방은 남아요</span></button>`, { cls: 'btn icon-btn', aria: '더 보기: 적용 취소 · 장면 지우기' });
  const save = `<button type="button" class="btn primary" data-action="stgSave"${g.dirty ? '' : ' disabled'}>${g.dirty ? '저장' : '저장됨'}</button>`;
  const notes = [];
  if (ck.event_changed) notes.push(`<div class="note warn" role="status">플롯 사건이 바뀌었어요. 이 장면은 "${esc(g.scene.event_text)}" 사건으로 짠 것이에요.</div>`);
  if (g.role === 'text') notes.push(`<div class="note plain">본문에서 뽑은 추출 결과예요. 고쳐도 계획 장면은 바뀌지 않아요.${ck.pair ? '' : ' 이 사건에는 견줄 계획 장면이 없어요.'}</div>`);
  const gaps = stgGaps();
  if (gaps.length) notes.push(`<div class="note plain" role="status"><b>계획과 다른 곳 ${gaps.length}개</b> 사소한 차이예요. 본문 쪽 연출이 더 나을 수도 있어요. 목차의 '계획과 달라요' 박자에서 봐요.</div>`);
  if (ck.dropped) notes.push(`<div class="note warn">미성년 인물이 낀 성적 접촉 ${ck.dropped}개는 저장할 때 빠져요.</div>`);
  const r = g.room;
  const pic = three && r ? s3Pane() : r ? `<svg id="stg-plan" class="stg-plan" viewBox="0 0 ${stgScale(r).w} ${stgScale(r).h}" role="img" aria-label="${esc(r.name)} 평면도, ${stgBeatName(g.beat)}"></svg>` : '<p class="small">방을 찾지 못했어요.</p>';
  const foot = g.role === 'text' ? (ck.pair ? `<label class="row small"><input type="checkbox" data-stg-ghost${g.ghost ? ' checked' : ''}> 겹쳐 보기 (계획 인물을 흐린 원으로)</label>` : '')
    : three ? '' : `<label class="row small"><input type="checkbox" data-stg-prompt${g.scene.prompt ? ' checked' : ''}> 쓰기 프롬프트에 넣기</label>`;
  const stageCard = `<section class="card stg-stage" aria-label="무대">
      <div class="between"><div class="row stg-title"><h2>${esc(r ? r.name : '방')}</h2>${g.role === 'text' ? '<span class="chip">추출 결과</span>' : ''}<span class="small">${r ? `${r.w} × ${r.h}m · ` : ''}${stgBeatName(g.beat)}</span></div>${typeof s3Toggle === 'function' ? s3Toggle() : ''}</div>
      <div class="stg-grid"><div class="stg-pic">${pic}</div><aside class="stg-now" aria-label="${stgBeatName(g.beat)}">${stgNow()}</aside></div>
      <div class="between stg-foot">${three ? '<span></span>' : stgLegend()}${foot}</div></section>`;
  const cards = g.mode === 'room' && !three ? stgRoomCard() + stgPeople() : stgPeople() + stgRoomCard();
  return `${head(esc(evText), roles + stgAiBtn() + more + save)}${wrap(`${cmp}${notes.join('')}${stageCard}${stgBar()}${cards}`)}`;
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
  stgAiFresh() {
    const g = S.stg;
    startJob('stage_draft', g.n, { event: g.ev - 1, stage_room: 'empty' });
  },
  async stgApply() {
    const g = S.stg;
    if (g.dirty && !confirm('저장하지 않은 변경이 사라져요. AI 장면으로 바꿀까요?')) return;
    try {
      const view = await api('POST', `/projects/${enc(S.name)}/stage/${g.n}/apply`, { event: g.ev - 1, role: g.role, shared: !!g.shared });
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
  /** 인물 줄 펴기 · 접기: 편 인물이 평면도에서 고른 인물이 된다 */
  stgOpen(w) {
    const g = S.stg;
    g.open = g.open === w ? '' : w;
    if (g.open) g.who = w;
    render();
  },
  stgStep(d) { actions.stgBeat(S.stg.beat + Number(d)); },
  stgBeatEdit() { S.stg.beatEdit = !S.stg.beatEdit; render(); },
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
  stgMode(m) { S.stg.mode = m === 'room' ? 'room' : 'people'; render(); },
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
    if (g.open === w) g.open = '';
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
    stageTurn(a);
    stgTouch();
  },
  stgAnchorDrop(id) {
    const g = S.stg;
    const gone = new Set([id, ...stageChildren(g.room, id).map((a) => a.id)]);
    const used = [...g.scene.start, ...g.scene.beats.flatMap((b) => b.bodies)].some((b) => b.at && gone.has(b.at.ref));
    if (used && !confirm('이 기준점(함께 빠지는 기준점 포함)에 선 인물이 있어요. 빼면 그 인물의 자리는 모름이 돼요. 뺄까요?')) return;
    g.room.anchors = g.room.anchors.filter((a) => !gone.has(a.id));
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
      const bs = stgBoardOf(g);  // 새 방은 스토리보드 장소가 지도 장소이면 그 장소에 묶는다 (다른 장면의 방 후보가 된다)
      const place = !k.room && bs && stgPlaces().includes(bs.place) ? bs.place : '';
      const v = await api('POST', `/projects/${enc(S.name)}/stage/${g.n}`, { event: g.ev - 1, room: k.room, template: k.template, room_name: k.name, place });
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
  if (d.stgShared !== undefined) { g.shared = t.checked; render(); return; }
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
  } else if (d.stgAnchorOn !== undefined) {
    const a = g.room.anchors.find((x) => x.id === d.stgAnchorOn);
    if (!a) return;
    Object.assign(a, stageAttach(g.room, a.id, t.value));
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
    g.open = t.value;
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
    const wa = stageResolve(g.room).anchors.find((x) => x.id === a.id);
    const [mx, my] = stgMeters(svg, e);
    stgDrag = { kind: 'anchor', a, svg, dx: mx - wa.x, dy: my - wa.y, moved: false };
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
    Object.assign(stgDrag.a, stageDragTo(g.room, stgDrag.a.id, mx - stgDrag.dx, my - stgDrag.dy));
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
  if (!d.moved) { if (d.kind === 'who') S.stg.open = d.id; render(); return; }  // 인물을 누르면 그 인물 줄을 편다
  if (d.kind === 'anchor') { stgTouch(); return; }
  const [mx, my] = stgMeters(d.svg, e);
  const at = stageSnap(S.stg.room, mx, my);
  if (at) stgSet('at', at);
  else render();
});

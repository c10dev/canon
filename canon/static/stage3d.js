/* 장면 연출 3D 보기 (설계 docs/stage/3d/specs/05-render.md). stage.js · stage3d-load.js 와 app.js 의 S, actions, api, render, esc, enc, charName 을 쓴다.
   읽기 전용이다: 고치기는 평면도에서만 한다. 서버(GET …/stage/{화}/{장면}/frames, stage3d.frames)가 낸 관절 좌표를 그리기만 하고,
   박자 슬라이더 · 재생은 평면도와 같은 S.stg.beat 를 쓴다. three.js 는 '3D' 를 처음 누를 때 load3d() 로 읽는다.
   그림에서만 하는 것: 안다 · 끌어안다 두 사람을 0.34 · 0.30m 로 붙인다(판정은 평면도 좌표 그대로, docs/stage/3d/README.md 정할 것 8).
   좌표: 서버 (x, y, z) = 평면도 x · y + 높이 z → three.js (x, z, y).
   s3Frame · s3Mix · s3Pull · s3Flags · s3Cams · s3Summary 는 DOM 없는 순수 함수다 (tests/test_stage3d_js.py). */
'use strict';

Object.assign(S, {
  stgView: 'plan',  // plan · 3d
});

// ----- 순수 함수 -----

// 마네킹 마디: [이름, 시작 관절, 끝 관절, 반지름 m]. 머리는 시작 = 끝(구)
const S3_SEGS = [
  ['torso', 'pelvis', 'neck', 0.12], ['neck', 'neck', 'head', 0.045], ['head', 'head', 'head', 0.11],
  ['shoulders', 'shoulder_l', 'shoulder_r', 0.055], ['hips', 'hip_l', 'hip_r', 0.08],
  ...['l', 'r'].flatMap((s) => [
    ['upper_arm_' + s, 'shoulder_' + s, 'elbow_' + s, 0.045], ['forearm_' + s, 'elbow_' + s, 'wrist_' + s, 0.04],
    ['hand_' + s, 'wrist_' + s, 'hand_' + s, 0.035], ['thigh_' + s, 'hip_' + s, 'knee_' + s, 0.065],
    ['shin_' + s, 'knee_' + s, 'ankle_' + s, 0.05], ['foot_' + s, 'ankle_' + s, 'toe_' + s, 0.04],
  ]),
];
const S3_CLOSE = { hug: 0.34, embrace: 0.3 };  // 안기 그림에서 두 골반 사이 (시안 값)
const S3_GAP = 0.05;  // 이보다 먼 손 → 부위 틈은 회색 점선

/** 관절 좌표 → 캡슐 목록 [{seg, a, b, r}] (서버 좌표). 관절이 빠진 마디는 건너뛴다. */
function s3Frame(joints) {
  if (!joints) return [];
  return S3_SEGS.filter(([, a, b]) => joints[a] && joints[b]).map(([seg, a, b, r]) => ({ seg, a: joints[a], b: joints[b], r }));
}

const s3Lerp = (a, b, e) => a.map((v, i) => v + (b[i] - v) * e);

/** 두 박자 사이를 섞는다 (e 0 → A, 1 → B). 관절이 둘 다 있는 인물만 섞고, 접촉은 B 의 것을 둘 다 있으면 섞는다. */
function s3Mix(A, B, e) {
  const bodies = {};
  Object.entries(B.bodies).forEach(([w, b]) => {
    const a = A.bodies[w];
    if (!a || !a.joints || !b.joints || e >= 1) { bodies[w] = b; return; }
    bodies[w] = { ...b, joints: Object.fromEntries(Object.entries(b.joints).map(([j, v]) => [j, a.joints[j] ? s3Lerp(a.joints[j], v, e) : v])) };
  });
  const old = Object.fromEntries((A.contacts || []).map((c) => [c.id, c]));
  const contacts = (B.contacts || []).map((c) => {
    const a = old[c.id];
    if (e >= 1 || !a || a.points.length !== c.points.length) return c;
    return { ...c, points: c.points.map((p, i) => s3Lerp(a.points[i], p, e)) };
  });
  return { ...B, bodies, contacts };
}

/** 안기 그림: 안다 · 끌어안다 두 사람을 S3_CLOSE 까지 붙인다. acts 는 접촉 id → 동작 id.
    몸은 반씩 다가가고, 감는 손 · 손목은 안긴 사람과 함께, 팔꿈치는 그 사이만큼 옮긴다. { beat, pulled } */
function s3Pull(beat, acts) {
  const pairs = {};
  (beat.contacts || []).forEach((c) => {
    const close = S3_CLOSE[acts[c.id]];
    const a = beat.bodies[c.who], b = beat.bodies[c.to];
    if (!close || !a || !b || !a.joints || !b.joints) return;
    const key = [c.who, c.to].sort().join('|');
    pairs[key] = Math.min(pairs[key] || Infinity, close);
  });
  const shift = {};
  Object.entries(pairs).forEach(([key, close]) => {
    const [w1, w2] = key.split('|');
    const p = beat.bodies[w1].joints.pelvis, q = beat.bodies[w2].joints.pelvis;
    const dx = q[0] - p[0], dy = q[1] - p[1], d = Math.hypot(dx, dy);
    if (d <= close + 1e-6) return;
    const m = (d - close) / 2 / d;
    const add = (w, sx, sy) => { const s = shift[w] || [0, 0]; shift[w] = [s[0] + sx, s[1] + sy]; };
    add(w1, dx * m, dy * m);
    add(w2, -dx * m, -dy * m);
  });
  if (!Object.keys(shift).length) return { beat, pulled: false };
  const move = (v, s) => [v[0] + s[0], v[1] + s[1], v[2]];
  const bodies = Object.fromEntries(Object.entries(beat.bodies).map(([w, b]) => {
    const s = shift[w];
    return [w, s && b.joints ? { ...b, joints: Object.fromEntries(Object.entries(b.joints).map(([j, v]) => [j, move(v, s)])) } : b];
  }));
  const contacts = (beat.contacts || []).map((c) => {
    const own = shift[c.who] || [0, 0], to = shift[c.to] || [0, 0];
    if (bodies[c.who].joints && S3_CLOSE[acts[c.id]]) {
      const j = bodies[c.who].joints, half = [(to[0] - own[0]) / 2, (to[1] - own[1]) / 2];
      c.hands.forEach((h) => {
        j['hand_' + h] = move(beat.bodies[c.who].joints['hand_' + h], to);
        j['wrist_' + h] = move(beat.bodies[c.who].joints['wrist_' + h], to);
        j['elbow_' + h] = move(j['elbow_' + h], half);
      });
    }
    return { ...c, points: c.points.map((p) => move(p, to)) };
  });
  return { beat: { ...beat, bodies, contacts }, pulled: true };
}

/** 판정 → 빨간 표시: 이 박자에 짚힌 인물(이름표)과 접촉 선. 지적에 contact 가 있으면 그 선만, 없으면 그 인물의 선. */
function s3Flags(violations, k, contacts) {
  const here = (violations || []).filter((v) => v.beat === k);
  const who = [...new Set(here.map((v) => v.who))];
  const lines = new Set();
  here.forEach((v) => {
    if (v.contact) lines.add(v.contact);
    else (contacts || []).filter((c) => c.who === v.who).forEach((c) => lines.add(c.id));
  });
  return { who, contacts: [...lines] };
}

/** 카메라 셋 (three.js 좌표): 비스듬히 · 위에서 · 문에서. 문이 없으면 앞(평면도 아래)에서. */
function s3Cams(room) {
  const W = room.w, H = room.h, big = Math.max(W, H);
  const door = (stageResolve(room).anchors || []).find((a) => a.kind === 'door');
  let from = [W / 2, 1.6, H + 1.2];
  if (door) {
    const [fx, fy] = stgFront(door.rot || 0), cx = door.x + door.w / 2, cy = door.y + door.h / 2;
    from = [cx - fx * 0.6, 1.6, cy - fy * 0.6];
  }
  return {
    iso: { pos: [W + big * 0.45, big * 0.85 + 0.8, H + big * 0.7], at: [W / 2, 0.6, H / 2] },
    top: { pos: [W / 2, big * 1.8 + 1, H / 2 + 0.01], at: [W / 2, 0, H / 2] },
    door: { pos: from, at: [W / 2, 0.9, H / 2] },
  };
}

/** 화면 읽기 프로그램용 한 줄: 박자, 인물마다 자세, 접촉 수. */
function s3Summary(beat, k, name, posture) {
  const who = Object.entries(beat.bodies).map(([w, b]) => `${name(w)} ${posture(b.posture)}${b.missing ? '(3D 없음)' : ''}`);
  const n = (beat.contacts || []).length;
  return `${k === 0 ? '시작 상태' : `${k}박자`}: ${who.join(', ')}${n ? `, 접촉 ${n}개` : ''}`;
}

// ----- 화면 -----

const s3 = {
  key: '', data: null, loading: false, error: '', snap: '', scene: null, room: null, cam: 'iso',
  three: null, host: null, gl: null, view: null, labels: null, world: null, camera: null, controls: null, mats: {}, people: {}, lines: null,
  shown: null, shownK: -1, restK: null, anim: 0, said: '',
};
const s3Css3 = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim() || '#888';
const s3ColorVar = (w) => { const c = STG_COLORS[Math.max(0, s3.scene.cast.indexOf(w)) % STG_COLORS.length]; return c.slice(4, -1); };
const s3Posture = (id) => (stgV().postures[id] || {}).label || id || '서기';
const s3Snap = () => JSON.stringify({ scene: S.stg.scene, room: S.stg.room });

function s3Toggle() {
  const v = S.stgView === '3d' ? '3d' : 'plan';
  return `<div class="seg" role="group" aria-label="보기"><button type="button" aria-pressed="${v === 'plan'}" data-action="stgView" data-arg="plan">평면도</button><button type="button" aria-pressed="${v === '3d'}" data-action="stgView" data-arg="3d">3D</button></div>`;
}

/** 평면도 자리에 들어갈 3D 칸. 캔버스 자체는 s3Mount 가 render 뒤에 옮겨 붙인다(다시 그려도 WebGL을 새로 만들지 않게). */
function s3Pane() {
  s3CssOnce();
  const g = S.stg, d = s3.key === `${g.n}/${g.sid}` ? s3.data : null;
  const notes = [];
  if (s3.error) notes.push(`<div class="note warn" role="status">${esc(s3.error)} <button type="button" class="btn small ghost" data-action="s3Redraw">다시 시도</button></div>`);
  else if (d && s3.snap !== s3Snap()) notes.push(`<div class="note plain s3-band" role="status">바뀐 것이 있어요. <button type="button" class="btn small" data-action="s3Redraw">다시 그리기</button></div>`);
  if (d) {
    const beat = d.frames.beats[Math.min(g.beat, d.frames.beats.length - 1)];
    const miss = [...new Set(Object.values(beat.bodies).filter((b) => b.missing).map((b) => s3Posture(b.missing)))];
    if (miss.length) notes.push(`<p class="small">${miss.map(esc).join(' · ')} 자세는 아직 3D가 없어 회색 기둥으로 그렸어요.</p>`);
    if (s3.room && d.missing.rooms.includes(s3.room.template)) notes.push('<p class="small">이 방 틀은 아직 3D 모양이 없어 가구를 종류 기본값 상자로 그렸어요.</p>');
    if (s3Pull(beat, s3Acts(beat.k)).pulled) notes.push('<p class="small">안는 두 사람은 그림에서만 더 붙였어요. 규칙 검수는 평면도 거리로 해요.</p>');
  }
  const cams = [['iso', '비스듬히'], ['top', '위에서'], ['door', '문에서']];
  return `<div class="s3-view">
      <div id="stg-3d" class="s3-slot">${s3.loading ? '<p class="s3-wait small">3D를 불러오는 중이에요…</p>' : ''}</div>
      <div class="between"><div class="seg" role="group" aria-label="카메라">${cams.map(([k, t]) => `<button type="button" aria-pressed="${s3.cam === k}" data-action="s3Cam" data-arg="${k}">${t}</button>`).join('')}</div>
        <span class="small">끌어서 돌리고 휠로 확대해요. 고치기는 평면도에서 해요</span></div>
      <p class="sr-only" id="s3-live" aria-live="polite">${esc(s3.said || '')}</p>
      ${notes.join('')}
      <div class="stg-legend"><span>점선 = 접촉(손 → 부위)</span><span>회색 점선 = 손이 닿지 않은 틈</span><span>빨강 = 지적</span></div>
    </div>`;
}

/** 접촉 id → 동작 id. 서버 frames 의 접촉이 act 를 실으면 그것을, 없으면(옛 응답) 평면도 상태에서 찾는다. */
function s3Acts(k) {
  const out = {};
  if (s3.scene) Object.values(stageState(s3.scene, k)).forEach((st) => Object.values(st.contacts).forEach((c) => { out[c.id] = c.act; }));
  const beat = s3.data && s3.data.frames && s3.data.frames.beats[k];
  ((beat && beat.contacts) || []).forEach((c) => { if (c.act) out[c.id] = c.act; });
  return out;
}

async function s3Fetch() {
  const g = S.stg;
  if (!g || !g.sid) return;
  const key = `${g.n}/${g.sid}`, path = `/projects/${enc(S.name)}/stage/${g.n}/${enc(g.sid)}/frames`;
  const snap = s3Snap(), scene = structuredClone(g.scene), room = structuredClone(g.room);
  Object.assign(s3, { key, loading: true, error: '' });
  render();
  try {
    const [three, data] = await Promise.all([load3d(), g.dirty ? api('POST', path, { scene, room }) : api('GET', path)]);
    if (s3.key !== key) return;
    Object.assign(s3, { three, data, snap, scene, room, loading: false, shown: null, shownK: -1, restK: null });
  } catch (err) {
    if (s3.key !== key) return;
    Object.assign(s3, { loading: false, error: err.message });
  }
  if (S.stg && S.route[2] === 'stage') render();
}

/** render 뒤 3D 칸을 붙이고 지금 박자를 그린다 (stage.js 의 syncStage 가 부른다). */
function s3Mount() {
  const g = S.stg, el = document.getElementById('stg-3d');
  if (!el || !g || !g.sid) return;
  if (s3.key !== `${g.n}/${g.sid}`) { Object.assign(s3, { key: `${g.n}/${g.sid}`, data: null, error: '' }); setTimeout(s3Fetch); return; }
  if (s3.error || !s3.data || !s3.three) return;
  if (!s3.host && !s3Build()) { setTimeout(render); return; }  // render 안에서 다시 render 하지 않는다
  const moved = s3.host.parentNode !== el;
  if (moved) el.replaceChildren(s3.host);
  if (s3.built !== s3.data) s3Room();
  if (moved) s3Resize();
  s3Show(Math.min(g.beat, s3.data.frames.beats.length - 1));
}

function s3Build() {
  const { THREE, OrbitControls, CSS2DRenderer } = s3.three;
  let gl = null;
  try { gl = new THREE.WebGLRenderer({ antialias: true }); } catch (e) { console.warn(e); }
  if (!gl || !gl.getContext()) { s3.error = '이 브라우저에서는 3D를 그릴 수 없어요(WebGL을 쓸 수 없어요). 평면도로 보세요.'; return false; }
  const host = document.createElement('div');
  host.className = 's3-stage';
  gl.setPixelRatio(Math.min(2, devicePixelRatio));
  gl.domElement.tabIndex = 0;
  gl.domElement.setAttribute('role', 'img');
  const labels = new CSS2DRenderer();
  labels.domElement.className = 's3-labels';
  const leaders = document.createElementNS('http://www.w3.org/2000/svg', 'svg');  // 이름표 지시선 (s3PlaceTags)
  leaders.setAttribute('class', 's3-leaders');
  leaders.setAttribute('aria-hidden', 'true');
  host.append(gl.domElement, leaders, labels.domElement);
  const view = new THREE.Scene();
  view.add(new THREE.HemisphereLight(0xffffff, 0x777777, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4);
  sun.position.set(-3, 6, 4);
  view.add(sun);
  const camera = new THREE.PerspectiveCamera(42, 4 / 3, 0.05, 80);
  const controls = new OrbitControls(camera, gl.domElement);
  controls.maxPolarAngle = Math.PI / 2 - 0.05;  // 바닥 아래로 내려가지 않게
  controls.minDistance = 1.2;
  controls.maxDistance = 30;
  controls.listenToKeyEvents(gl.domElement);  // 캔버스에 초점이 있으면 방향키로 옮긴다
  controls.addEventListener('change', s3Draw);
  const world = new THREE.Group(), lines = new THREE.Group();
  view.add(world, lines);
  Object.assign(s3, { host, gl, labels, leaders, view, camera, controls, world, lines, people: {}, pins: [], mats: {} });
  new ResizeObserver(s3Resize).observe(host);
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', s3Recolor);
  return true;
}

// 재질은 CSS 변수 이름을 기억해 다크 모드로 바뀌면 다시 칠한다
function s3Mat(key, Make, opts = {}, v = key) {
  if (!s3.mats[key]) {
    s3.mats[key] = new Make({ color: s3Css3(v), ...opts });
    s3.mats[key].userData.v = v;
  }
  return s3.mats[key];
}

function s3Recolor() {
  if (!s3.view) return;
  Object.values(s3.mats).forEach((m) => m.color.set(s3Css3(m.userData.v)));
  s3.view.background = new s3.three.THREE.Color(s3Css3('--canvas'));
  s3Draw();
}

/** 이름표: 바깥 div 는 CSS2DRenderer 가 transform 으로 옮기고, 안쪽 span 은 겹침을 피해 s3PlaceTags 가 옮긴다. */
function s3Tag(text, cls) {
  const el = document.createElement('div'), inner = document.createElement('span');
  el.className = 's3-tag ' + (cls || '');
  inner.textContent = text;
  el.append(inner);
  return new s3.three.CSS2DObject(el);
}

/** 이름표 겹침 (docs/stage/specs/11-labels.md): 화면에 비친 자리에서 stageLabelPlace 로 놓는다. 인물이 먼저, 기준점 이름이 뒤.
   인물 이름표는 자리가 없으면 이름만 남기고 멀리 놓으면 지시선을 긋는다. 기준점 이름은 막히면 숨긴다. 카메라를 움직일 때마다 다시 놓는다. */
function s3PlaceTags() {
  const { THREE } = s3.three, W = s3.host.clientWidth, H = s3.host.clientHeight, v = new THREE.Vector3();
  const screen = (o) => {
    o.getWorldPosition(v).project(s3.camera);
    return v.z > 1 || Math.abs(v.x) > 1.2 || Math.abs(v.y) > 1.2 ? null : [(v.x + 1) / 2 * W, (1 - v.y) / 2 * H];
  };
  const items = [], by = {};
  Object.entries(s3.people).forEach(([w, p]) => {
    const at = p.grp.visible && screen(p.tag);
    if (!at) return;
    items.push({ id: 'p:' + w, x: at[0], y: at[1], text: p.full || '', short: charName(w), fs: 12, pad: 12, h: 18, kind: 'tag' });
    by['p:' + w] = p.tag;
  });
  s3.pins.forEach(({ id, tag }) => {
    const at = screen(tag);
    if (!at) return;
    items.push({ id: 'a:' + id, x: at[0], y: at[1], text: tag.element.firstChild.textContent, fs: 12, pad: 12, h: 18, kind: 'pin' });
    by['a:' + id] = tag;
  });
  const placed = stageLabelPlace(items, { bounds: [0, 0, W, H], prev: s3.tagMem || (s3.tagMem = {}) });
  let lines = '';
  items.forEach((it) => {
    const t = placed[it.id], span = by[it.id].element.firstChild;
    span.style.visibility = t.hidden ? 'hidden' : '';
    if (t.hidden) return;
    span.textContent = t.text;
    span.style.transform = `translate(${(t.cx - it.x).toFixed(1)}px, ${(t.cy - it.y).toFixed(1)}px)`;
    if (t.leader) {
      const ex = Math.min(Math.max(it.x, t.cx - t.w / 2), t.cx + t.w / 2), ey = Math.min(Math.max(it.y, t.cy - t.h / 2), t.cy + t.h / 2);
      lines += `<path d="M${it.x.toFixed(1)} ${it.y.toFixed(1)}L${ex.toFixed(1)} ${ey.toFixed(1)}"/>`;
    }
  });
  s3.leaders.innerHTML = lines;
}

const s3V = (p) => new s3.three.THREE.Vector3(p[0], p[2], p[1]);

/** 방: 바닥, 뒤 · 왼 벽(앞 · 오른은 낮게), 가구 상자와 기준점 이름표. 사람 마네킹은 인물마다 한 번 만든다. */
function s3Room() {
  const { THREE } = s3.three, room = stageResolve(s3.room), fr = s3.data.frames;  // 붙은 기준점은 세계 좌표로 (stage.js stageResolve)
  s3.world.traverse((o) => { if (o.isCSS2DObject) o.element.remove(); });  // 안에 든 이름표는 clear 가 DOM 에서 떼지 않는다
  s3.world.clear();
  s3.people = {};
  const lam = (v, o) => s3Mat(v + (o ? ':t' : ''), THREE.MeshLambertMaterial, o || {}, v);
  const edge = s3Mat('--line-strong', THREE.LineBasicMaterial);
  const box = (sx, sy, sz, m, solid = true) => {
    const grp = new THREE.Group(), geo = new THREE.BoxGeometry(sx, sy, sz);
    if (solid) grp.add(new THREE.Mesh(geo, m));
    grp.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo), edge));
    return grp;
  };
  const W = room.w, H = room.h;
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(W, H), lam('--surface'));
  floor.rotation.x = -Math.PI / 2;
  floor.position.set(W / 2, 0, H / 2);
  s3.world.add(floor);
  const wall = (sx, sy, sz, x, y, z) => { const m = box(sx, sy, sz, lam('--chip')); m.position.set(x, y, z); s3.world.add(m); };
  const back = fr.open ? 0.12 : fr.ceiling;  // 야외 틀은 벽 없이 땅 테두리만
  wall(W, back, 0.08, W / 2, back / 2, -0.04);
  wall(0.08, back, H, -0.04, back / 2, H / 2);
  wall(W, 0.12, 0.08, W / 2, 0.06, H + 0.04);
  wall(0.08, 0.12, H, W + 0.04, 0.06, H / 2);
  const tops = {};
  fr.solids.forEach((s) => {
    const [x0, y0, z0, x1, y1, z1] = s.box;
    const m = box(Math.max(x1 - x0, 0.01), Math.max(z1 - z0, 0.01), Math.max(y1 - y0, 0.01), s.solid ? lam('--btn') : lam('--accent-soft'), s.solid);
    m.position.set((x0 + x1) / 2, (z0 + z1) / 2, (y0 + y1) / 2);
    s3.world.add(m);
    tops[s.anchor] = Math.max(tops[s.anchor] || 0, z1);
  });
  s3.pins = [];
  room.anchors.forEach((a) => {
    const t = s3Tag(a.name, 'anchor');
    t.position.set(a.x + a.w / 2, (tops[a.id] ?? 0.5) + 0.08, a.y + a.h / 2);
    s3.world.add(t);
    s3.pins.push({ id: a.id, tag: t });
  });
  const cyl = new THREE.CylinderGeometry(1, 1, 1, 12, 1, true), ball = new THREE.SphereGeometry(1, 14, 10);
  s3.scene.cast.forEach((w) => {
    const grp = new THREE.Group(), m = lam(s3ColorVar(w));
    const parts = S3_SEGS.map(() => ({ c: new THREE.Mesh(cyl, m), a: new THREE.Mesh(ball, m), b: new THREE.Mesh(ball, m) }));
    parts.forEach((p) => grp.add(p.c, p.a, p.b));
    const ghost = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.2, 1.6, 16), lam('--muted', { transparent: true, opacity: 0.45 }));
    const tag = s3Tag(charName(w));
    grp.add(ghost, tag);
    s3.world.add(grp);
    s3.people[w] = { grp, parts, ghost, tag, full: '' };  // 가까이 선 사람의 이름표는 s3PlaceTags 가 비켜 놓는다
  });
  s3.built = s3.data;
  s3Recolor();
  s3SetCam(s3.cam);
}

function s3Resize() {
  if (!s3.gl || !s3.host.isConnected) return;
  const w = s3.host.clientWidth, h = s3.host.clientHeight;
  if (!w || !h) return;
  s3.gl.setSize(w, h, false);
  s3.labels.setSize(w, h);
  s3.camera.aspect = w / h;
  s3.camera.fov = w < 480 ? 55 : 42;
  s3.camera.updateProjectionMatrix();
  s3Draw();
}

function s3SetCam(id) {
  const c = s3Cams(s3.room)[id] || s3Cams(s3.room).iso;
  s3.cam = id;
  s3.camera.position.set(...c.pos);
  s3.controls.target.set(...c.at);
  s3.controls.update();
  s3Draw();
}

function s3Draw() {
  if (s3.gl && s3.host && s3.host.isConnected) { s3.gl.render(s3.view, s3.camera); s3PlaceTags(); s3.labels.render(s3.view, s3.camera); }
}

/** 박자 사이 돌아가는 이동 (stage.js stagePathFor): 섞은 몸을 곧은 보간 대신 꺾은선 위로 평면 이동만큼 옮긴다.
   via 는 인물 id → 꺾은선, e 는 섞는 비율. 자세 · 관절은 s3Mix 그대로다. */
function s3Detour(beat, via, e) {
  if (!Object.keys(via).length || e >= 1) return beat;
  const bodies = { ...beat.bodies };
  Object.entries(via).forEach(([w, line]) => {
    const b = bodies[w];
    if (!b || !b.joints) return;
    const p = stagePathAt(line, e), a = line[0], z = line[line.length - 1];
    const dx = p[0] - (a[0] + (z[0] - a[0]) * e), dy = p[1] - (a[1] + (z[1] - a[1]) * e);
    bodies[w] = { ...b, joints: Object.fromEntries(Object.entries(b.joints).map(([j, v]) => [j, [v[0] + dx, v[1] + dy, v[2]]])) };
  });
  return { ...beat, bodies };
}

/** 박자 k 를 그린다. 앞에 그린 박자가 있으면 0.6초 동안 관절 좌표를 섞는다.
   다 그려 멈춘 박자(restK)에서 한 박자 옮길 때만 가구를 돌아가는 꺾은선을 따른다 (평면도와 같은 frames 의 paths). */
function s3Show(k) {
  if (k === s3.shownK && s3.shown) { s3Draw(); return; }
  const target = s3Pull(s3.data.frames.beats[k], s3Acts(k)).beat, from = s3.shown, fk = s3.restK;
  cancelAnimationFrame(s3.anim);
  s3.shownK = k;
  s3.restK = null;
  s3Aria(target, k);
  if (!from || matchMedia('(prefers-reduced-motion: reduce)').matches || document.hidden) { s3Pose(target, k); s3.shown = target; s3.restK = k; return; }
  const beats = s3.data.frames.beats, via = {};
  if (fk === k - 1 || fk === k + 1) {
    const paths = beats.map((b) => b.paths || {}), step = paths[Math.max(fk, k)] || {};
    Object.entries(step).forEach(([w, r]) => { if (r.via.length > 2) via[w] = fk < k ? r.via : [...r.via].reverse(); });
  }
  const t0 = performance.now();
  const step = (now) => {
    const u = Math.min(1, (now - t0) / 600), e = u < 0.5 ? 2 * u * u : 1 - (-2 * u + 2) ** 2 / 2;
    s3.shown = s3Mix(from, target, e);
    s3Pose(s3Detour(s3.shown, via, e), k);
    if (u < 1) s3.anim = requestAnimationFrame(step);
    else s3.restK = k;
  };
  s3.anim = requestAnimationFrame(step);
}

function s3Aria(beat, k) {
  const said = s3Summary(beat, k, charName, s3Posture);
  s3.said = said;
  s3.gl.domElement.setAttribute('aria-label', `${s3.room.name} 3D 보기. ${said}`);
  const live = document.getElementById('s3-live');
  if (live) live.textContent = said;
}

/** 한 박자의 마네킹 · 회색 기둥 · 이름표 · 접촉 선. */
function s3Pose(beat, k) {
  const { THREE } = s3.three, up = new THREE.Vector3(0, 1, 0);
  const viol = [...((S.stg && S.stg.check && S.stg.check.violations) || []), ...(s3.data.violations3d || [])];
  const flags = s3Flags(viol, k, beat.contacts), bad = new Set(flags.who), badLine = new Set(flags.contacts);
  const pos = stageLayout(s3.room, stageState(s3.scene, k), s3.scene.cast);
  Object.entries(s3.people).forEach(([w, p]) => {
    const b = beat.bodies[w];
    p.grp.visible = !!b;
    if (!b) return;
    const caps = s3Frame(b.joints), byName = Object.fromEntries(caps.map((c) => [c.seg, c]));
    S3_SEGS.forEach(([seg], i) => {
      const c = byName[seg], m = p.parts[i];
      [m.c, m.a, m.b].forEach((x) => { x.visible = !!c; });
      if (!c) return;
      const a = s3V(c.a), bb = s3V(c.b), len = a.distanceTo(bb);
      m.a.position.copy(a); m.a.scale.setScalar(c.r);
      m.b.position.copy(bb); m.b.scale.setScalar(c.r);
      m.c.visible = len > 1e-4;
      if (len > 1e-4) {
        m.c.position.copy(a).add(bb).multiplyScalar(0.5);
        m.c.scale.set(c.r, len, c.r);
        m.c.quaternion.setFromUnitVectors(up, bb.clone().sub(a).normalize());
      }
    });
    const xy = pos[w] || [0, 0];
    p.ghost.visible = !b.joints;
    p.ghost.position.set(xy[0], 0.8, xy[1]);
    const head = b.joints ? b.joints.head : [xy[0], xy[1], 1.6];
    p.tag.position.set(head[0], head[2] + 0.25, head[1]);
    p.full = `${charName(w)} · ${b.joints ? s3Posture(b.posture) : `${s3Posture(b.posture)} · 이 자세는 아직 3D가 없어요`}`;
    p.tag.element.firstChild.textContent = p.full;
    p.tag.element.classList.toggle('bad', bad.has(w));
    p.tag.element.classList.toggle('ghost', !b.joints);
  });
  s3.lines.children.forEach((x) => x.geometry.dispose());
  s3.lines.clear();
  const dash = { dashSize: 0.05, gapSize: 0.035, depthTest: false };  // 접촉 선 · 점은 몸에 가려도 보이게
  (beat.contacts || []).forEach((c) => {
    const red = badLine.has(c.id), far = c.gap > S3_GAP;
    const v = red ? '--red' : far ? '--muted' : '--text';
    const lm = s3Mat('line' + v, THREE.LineDashedMaterial, dash, v), dm = s3Mat('dot' + v, THREE.MeshBasicMaterial, { depthTest: false }, v);
    for (let i = 0; i + 1 < c.points.length; i += 2) {
      const a = s3V(c.points[i]), b = s3V(c.points[i + 1]);
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b]), lm);
      line.computeLineDistances();
      line.renderOrder = 10;
      const dot = new THREE.Mesh(new THREE.SphereGeometry(0.025, 10, 8), dm);
      dot.position.copy(b);
      dot.renderOrder = 11;
      s3.lines.add(line, dot);
    }
  });
  s3Draw();
}

function s3CssOnce() {
  if (document.getElementById('s3-css')) return;
  const st = document.createElement('style');
  st.id = 's3-css';
  st.textContent = `
.s3-view { display: flex; flex-direction: column; gap: 10px; }
.s3-slot { position: relative; width: 100%; aspect-ratio: 4 / 3; max-height: 70vh; border-radius: 8px; overflow: hidden; background: var(--canvas); border: 1px solid var(--line); }
.s3-wait { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; margin: 0; }
.s3-stage { position: absolute; inset: 0; touch-action: none; }
.s3-stage canvas { display: block; width: 100%; height: 100%; outline: none; }
.s3-stage canvas:focus-visible { box-shadow: inset 0 0 0 2px var(--accent); }
.s3-labels { position: absolute; inset: 0; pointer-events: none; }
.s3-leaders { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; stroke: var(--muted); stroke-width: 1; fill: none; }
.s3-tag span { display: inline-block; padding: 1px 6px; border-radius: 6px; background: var(--glass); }
.s3-tag { font-family: var(--sans); font-size: 12px; font-weight: 700; color: var(--text); white-space: nowrap; }
.s3-tag.anchor { font-weight: 500; color: var(--text-2); }
.s3-tag.anchor span { background: transparent; }
.s3-tag.ghost { color: var(--muted); }
.s3-tag.bad { color: var(--red); }
.s3-band { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
@container stgcol (max-width: 480px) { .s3-slot { aspect-ratio: 1 / 1; } }
`;
  document.head.appendChild(st);
}

Object.assign(actions, {
  stgView(v) {
    S.stgView = v === '3d' ? '3d' : 'plan';
    if (S.stgView === '3d' && S.stg) Object.assign(S.stg, { mode: 'people', open: '', beatEdit: false });  // 3D 는 읽기만: 방 고치기 · 인물 고치기를 닫는다
    render();
  },
  s3Cam(id) {
    s3.cam = id;
    if (s3.camera) s3SetCam(id);
    render();
  },
  s3Redraw() {
    s3.error = '';
    s3.data = null;
    s3Fetch();
  },
});

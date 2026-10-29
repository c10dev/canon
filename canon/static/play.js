/* 플레이 모드 화면 (DESIGN.md 10장, 시안 안 A 읽기형): 새 플레이(#/play/new, #/play/new/<세계>), 플레이(#/play/<폴더>),
   지난 일 · 되감기(/past), 생애 기록(/life). 작품 홈 카드(playHomeCard)도 여기 있다. 작품 목록의 플레이 줄은 home.js plGroupRows.
   시계는 화면에 있다. 써 둔 구간의 흘러간 일을 한 줄씩 보이고, 새 구간의 첫 줄이 보이면 서버에 닿았다고 알린다(see).
   서버는 닿은 구간보다 한 구간 넘게 앞서 쓰지 않는다 (web._play_continue). 시계 규칙(playItems · playGap · playPhase ·
   playTick · playClock)은 DOM 없는 순수 함수라 tests/test_play_js.py 가 node 로 맞춰 본다. */
'use strict';

// ---------- 시계 규칙 (순수 함수) ----------

const PLAY_UNIT_MS = 20000;  // 1× 에서 시간 단위 한 칸 [추정: 시안 제안값, 실제 Gemini 속도로 재지 않음]
const PLAY_AUTO_MS = 8000;   // 자동 결정 전에 기다리는 시간 [추정: 시안 제안값]
const PLAY_SPEEDS = [1, 2, 4, 8];
const PLAY_GAP_MAX = 3;      // 줄 사이가 아무리 멀어도 시간 칸은 이만큼까지만 기다린다
const PLAY_UNIT_DAYS = { hour: 1 / 24, day: 1, month: 30, year: 365 };
const PLAY_UNITS = { hour: '한 시간', day: '하루', month: '한 달', year: '한 해' };
const PLAY_PERSONS = { first: '나 시점', second: '당신 시점', third: '3인칭' };
const PLAY_KINDS = { choice: '고른 것', free: '직접 해 봄', auto: '자동 결정', skip: '건너뜀' };
const PLAY_FOCUS = ['일', '사람', '수련', '비밀 캐기', '몸', '마음', '균형'];

/** 시계가 한 줄씩 보일 항목. 구간마다 흘러간 일 줄, 결정 장면이 있으면 그 뒤에 결정 항목 하나. 결정 장면만 있는 구간은 결정 항목만.
    행동(고름 · 직접 · 자동 결정)으로 시작한 구간의 첫 줄은 acted 를 단다 (그 결과는 기다리지 않고 바로 보인다). */
function playItems(turns) {
  const out = [];
  for (const t of turns || []) {
    const acted = !!t.action && ['choice', 'free', 'auto', 'skip'].includes(t.kind);
    (t.beats || []).forEach((b, i) => out.push({ n: t.number, kind: 'beat', i, day: b.day || 0, when: b.when || '', text: b.text, ...(acted && !i ? { acted: true } : {}) }));
    if ((t.choices || []).length || (t.scene && !(t.beats || []).length)) out.push({ n: t.number, kind: 'decision' });
  }
  return out;
}

/** 앞 항목에서 이 항목까지 기다릴 시간 칸 (0~PLAY_GAP_MAX). 첫 항목, 결정 바로 뒤나 행동의 결과(acted), 결정 항목은 기다리지 않는다.
    날수를 아는 두 줄은 날수 차이를 시간 단위로 셈하고, 모르면 한 칸. */
function playGap(prev, item, unit) {
  if (!item || item.kind === 'decision' || item.acted || !prev || prev.kind === 'decision') return 0;
  if (!prev.day || !item.day) return 1;
  const units = (item.day - prev.day) / (PLAY_UNIT_DAYS[unit] || 1);
  return Math.min(PLAY_GAP_MAX, Math.max(1, Math.round(units)));
}

/** 시계 처음 값. 화면이 이미 닿은 구간(seen)까지는 다 보인 채로 연다 (다시 열어도 같은 줄을 또 흘리지 않는다). */
function playClockStart(items, seen, run = false, speed = 1) {
  return { pos: (items || []).filter((x) => x.n <= seen).length, run, speed, acc: 0, rush: false, auto: null, held: null, acted: null, news: 0 };
}

/** 지금 상태. v: { items, last: { number, state, choices } | null, seen, ended, busy, jobError, autoDecide, unit }.
    decide 결정 대기 · ended 끝남 · failed 반영 실패 · error 쓰기 실패 · paused 멈춤 · writing 앞날을 쓰는 중 · flowing 흐르는 중 */
function playPhase(c, v) {
  const items = v.items || [];
  const atEnd = c.pos >= items.length;
  const acted = c.acted != null && (!v.last || v.last.number <= c.acted);  // 행동을 보냈고 새 구간이 아직 오지 않았다
  const shown = items[c.pos - 1];
  if (!acted && shown && shown.kind === 'decision' && v.last && shown.n === v.last.number && !v.ended) return 'decide';
  if (atEnd && v.ended && !acted) return 'ended';
  if (atEnd && v.last && v.last.state === 'failed' && !v.busy) return 'failed';
  if ((atEnd || acted) && v.jobError && !v.busy) return 'error';
  if (!c.run) return 'paused';
  return atEnd || acted ? 'writing' : 'flowing';
}

/** 시계를 dt(밀리초)만큼 돌린다. 돌려주는 값: { c: 새 시계, see: 새로 닿은 구간 번호 | null, want: 'auto' | null }.
    흐르는 중에는 배속만큼 시간을 쌓아 줄 사이 시간 칸(playGap × PLAY_UNIT_MS)을 넘을 때마다 한 줄씩 보인다. '다음 결정까지'(rush)면 기다리지 않는다.
    결정 항목이 보이면 멈춘다. 자동 결정이 켜져 있고 흐르는 중이면 PLAY_AUTO_MS 를 센 뒤 want 'auto' 를 낸다 (배속과 상관없다). */
function playTick(c, v, dt) {
  c = { ...c };
  let see = null;
  let want = null;
  const items = v.items || [];
  const ph = playPhase(c, v);
  if (ph === 'decide') {
    c.rush = false;
    if (v.autoDecide && c.run && c.held !== v.last.number) {
      c.auto = (c.auto == null ? PLAY_AUTO_MS : c.auto) - dt;
      if (c.auto <= 0) {
        c.auto = null;
        c.held = v.last.number;  // 같은 결정에서 두 번 내지 않는다
        want = 'auto';
      }
    } else c.auto = null;
    return { c, see, want };
  }
  c.auto = null;
  if (!c.run || ph !== 'flowing') return { c, see, want };
  c.acc += dt * c.speed;
  while (c.pos < items.length) {
    const need = c.rush ? 0 : playGap(items[c.pos - 1], items[c.pos], v.unit) * PLAY_UNIT_MS;
    if (c.acc < need) break;
    c.acc -= need;
    const it = items[c.pos];
    c.pos += 1;
    c.news += 1;
    if (it.n > v.seen && (see == null || it.n > see)) see = it.n;
    if (it.kind === 'decision') { c.acc = 0; break; }
  }
  if (c.pos >= items.length) c.acc = Math.min(c.acc, PLAY_UNIT_MS);  // 앞날을 기다리는 동안 쌓인 시간은 한 칸까지만 (도착하면 첫 줄이 바로)
  return { c, see, want };
}

/** 시계 사건. ev.type: toggle 흐르기 · 멈추기, pause 멈춤(창을 가림 · 다른 화면 · 적기 시작), resume, speed(ev.speed), faster, slower,
    rush 다음 결정까지, hold 자동 결정 기다리기(아무 키), act 행동을 보냄(닿은 구간의 남은 줄을 다 보이고 다시 흐른다),
    sync 서버 값이 바뀜(새 구간이 오면 act 표시를 지운다), seen 알렸던 줄 수를 0 으로 (멈춤 알림 뒤). */
function playClock(c, ev, v) {
  c = { ...c };
  const items = (v && v.items) || [];
  const step = (d) => PLAY_SPEEDS[Math.min(PLAY_SPEEDS.length - 1, Math.max(0, PLAY_SPEEDS.indexOf(c.speed) + d))];
  switch (ev.type) {
    case 'toggle': c.run = !c.run; if (!c.run) c.rush = false; break;
    case 'pause': c.run = false; c.rush = false; c.auto = null; break;
    case 'resume': c.run = true; break;
    case 'speed': c.speed = PLAY_SPEEDS.includes(ev.speed) ? ev.speed : c.speed; break;
    case 'faster': c.speed = step(1); break;
    case 'slower': c.speed = step(-1); break;
    case 'rush': c.rush = true; c.run = true; break;
    case 'hold': c.auto = null; if (v && v.last) c.held = v.last.number; break;
    case 'act':
      c.pos = Math.max(c.pos, items.filter((x) => x.n <= v.seen).length);
      c.acted = v.seen;
      c.run = true; c.rush = false; c.auto = null; c.acc = 0;
      break;
    case 'sync':
      c.pos = Math.min(c.pos, items.length);
      if (c.acted != null && v.last && v.last.number > c.acted) c.acted = null;
      if (c.acted != null && v.jobError && !v.busy) c.acted = null;  // 쓰기에 실패했다. 다시 시도는 화면이 보낸다
      break;
    case 'seen': c.news = 0; break;
    default: break;
  }
  return c;
}

/** '다시 시도'가 보낼 것. 반영 실패면 빈 값(반영만 다시). 보낸 행동(lastAct: { body, at: 보낼 때 닿은 구간 })이 아직 구간이 되지 않았으면
    그 행동을 다시, 이미 구간이 됐으면 빈 값(흐름). 지난 결정의 선택지 번호를 다시 보내면 서버가 막는다. */
function playRetryBody(last, lastAct) {
  if (last && last.state === 'failed') return {};
  if (lastAct && (!last || last.number <= lastAct.at)) return lastAct.body;
  return {};
}

/** 지금 보이는 시점 글: 마지막으로 보인 흘러간 일의 시점, 없으면 서버가 준 마지막 반영 시점. */
function playNow(items, pos, fallback) {
  for (let k = Math.min(pos, items.length) - 1; k >= 0; k--) if (items[k].when) return items[k].when;
  return fallback || '';
}

// ---------- 상태와 서버 ----------

let playTimer = null;
let playPollTimer = null;
let playLast = 0;
let playSaid = '';
let playKicked = 0;  // 멈춘 흐름을 마지막으로 다시 청한 때 (playStep)

function playV() {
  const p = S.play;
  const last = p && p.turns.length ? p.turns[p.turns.length - 1] : null;
  return {
    items: S.playItems || [], last: last && { number: last.number, state: last.state, choices: last.choices.length > 0 },
    seen: p ? p.seen : 0, ended: !!(p && p.ending), busy: !!(p && p.job && p.job.status === 'running'),
    jobError: !!(p && p.job && p.job.status === 'error'), autoDecide: !!(p && p.auto_decide), unit: p ? p.unit : 'day',
  };
}

function playSpeedSaved() {
  try { return Number(localStorage.getItem('canon.playSpeed')) || 1; } catch { return 1; }
}

/** 서버 값을 받는다. 처음이면 시계를 연다. */
function playSet(view, fresh = false) {
  // 보낸 see 가 아직 저장 전일 수 있어 큰 값을 둔다. 되감기처럼 새로 여는 값(fresh)은 서버 것 그대로
  const seen = !fresh && S.play && S.play.name === view.name ? Math.max(S.play.seen, view.seen) : view.seen;
  S.play = { ...view, seen };
  S.playItems = playItems(view.turns);
  if (fresh || !S.playClock) S.playClock = playClockStart(S.playItems, seen, !!S.playAutoRun, playSpeedSaved());
  else S.playClock = playClock(S.playClock, { type: 'sync' }, playV());
  S.playAutoRun = false;
}

/** 라우팅 (app.js routeNow): #/play/new[/세계], #/play/<폴더>[/past | /life]. */
async function playLoad(parts) {
  playStop();
  S.playLife = null;
  if (parts[1] === 'new' || !parts[1]) {
    S.playName = null;
    S.projects = await api('GET', '/projects');
    const world = parts[2] || '';
    const f = S.playNew && S.playNew.world === world ? S.playNew : playNewForm(world);
    S.playNew = f;
    S.playWorld = world ? await api('GET', `/projects/${enc(world)}/play/world`) : null;
    if (world && f.mode === 'random' && !f.card) await playRoll();
    return;
  }
  const name = parts[1];
  const fresh = S.playName !== name;
  S.playName = name;
  playSet(await api('GET', `/projects/${enc(name)}/play`), fresh);
  if (parts[2] === 'life') S.playLife = await api('GET', `/projects/${enc(name)}/play/life`);
  if (!parts[2]) playStart();
  if (playNeedsPoll()) playPoll();
}

function playStart() {
  clearInterval(playTimer);
  playLast = performance.now();
  playTimer = setInterval(playStep, 250);
}

/** 플레이 화면을 떠나면 시계를 멈춘다 (다시 오면 멈춘 채로 연다). */
function playStop() {
  clearInterval(playTimer);
  clearTimeout(playPollTimer);
  playTimer = null;
  if (S.playClock) S.playClock = playClock(S.playClock, { type: 'pause' });
}

function playNeedsPoll() {
  if (!S.play) return false;
  const v = playV();
  const ph = playPhase(S.playClock || playClockStart(S.playItems, S.play.seen), v);
  return v.busy || ph === 'writing' || (S.playClock && S.playClock.acted != null);
}

function playPoll(soon = false) {
  clearTimeout(playPollTimer);
  playPollTimer = setTimeout(playRefresh, soon ? 500 : 1500);
}

async function playRefresh() {
  const name = S.playName;
  if (S.route[0] !== 'play' || S.route[1] !== name) return;
  let view;
  try {
    view = await api('GET', `/projects/${enc(name)}/play`);
  } catch {
    clearTimeout(playPollTimer);
    playPollTimer = setTimeout(playRefresh, 4000);  // 서버가 꺼졌거나 다시 시작하는 중: 작업 목록처럼 천천히 다시 묻는다
    return;
  }
  if (S.playName !== name) return;
  const before = JSON.stringify(S.play);
  const ph = playPhase(S.playClock, playV());
  playSet(view);
  if (JSON.stringify(S.play) !== before || playPhase(S.playClock, playV()) !== ph) playDraw();
  if (playNeedsPoll()) playPoll();
}

/** 시계 한 걸음 (0.25초마다). 줄이 새로 보이거나 상태가 바뀌면 다시 그리고, 아니면 남은 초 · 막대만 고친다. */
function playStep() {
  const now = performance.now();
  const dt = Math.min(now - playLast, 2000);  // 탭이 잠들었다 깨어도 한꺼번에 흘리지 않는다
  playLast = now;
  if (S.route[0] !== 'play' || !S.play || S.route[2] || !S.playClock) return;
  const v = playV();
  const before = playPhase(S.playClock, v);
  const pos = S.playClock.pos;
  const r = playTick(S.playClock, v, dt);
  S.playClock = r.c;
  if (r.see != null) playSee(r.see);
  const after = playPhase(S.playClock, playV());
  if (r.want === 'auto') { playAct({ kind: 'auto' }); return; }
  // 써 둔 줄 끝에서 흐르는데 도는 작업이 없다 (서버가 다시 시작돼 작업이 사라졌거나, 실패한 작업이 목록에서 빠졌다). 5초마다 한 번 흐름을 청한다
  if (after === 'writing' && !playV().busy && !playV().jobError && S.playClock.acted == null && now - playKicked > 5000) {
    playKicked = now;
    api('POST', `/projects/${enc(S.playName)}/play/advance`, {}).then(() => playPoll(true)).catch(() => {});
  }
  if (S.playClock.pos !== pos || after !== before) {
    if (after === 'decide' && before !== 'decide') S.focusTarget = '#play-dec-h';
    playDraw();
  } else playPaintLive();
}

function playSee(n) {
  S.play.seen = Math.max(S.play.seen, n);
  api('POST', `/projects/${enc(S.playName)}/play/see`, { n }).then(() => playPoll(true)).catch(() => playPoll());
}

/** 행동을 보낸다: { choice } · { action } · { kind: 'auto' } · {} (흐름 · 반영 다시 시도). 행동이면 아직 닿지 않은 구간을 화면에서도 버린다. */
async function playAct(body) {
  const p = S.play;
  const acting = !!(body.choice || body.action || body.kind === 'auto');
  if (acting && S.playClock && S.playClock.acted != null) return;  // 앞서 보낸 행동의 구간을 기다리는 중 (두 번 누름)
  if (acting) {
    p.turns = p.turns.filter((t) => t.number <= p.seen);
    S.playItems = playItems(p.turns);
    S.playClock = playClock(S.playClock, { type: 'act' }, playV());
  }
  S.playLastAct = { body, at: p.seen };
  try {
    p.job = await api('POST', `/projects/${enc(S.playName)}/play/advance`, body);
    if (acting) S.playDraft = '';
  } catch (e) {
    if (S.playClock) S.playClock.acted = null;
    showError(e);
    return playRefresh();
  }
  playDraw();
  playPoll(true);
}

/** 그린 뒤: 확인 칸(<dialog>)을 열고, 남은 초 · 막대 · 낭독 알림을 맞춘다 (app.js drawApp). */
function playAfterDraw() {
  const dlg = $('#play-dlg');
  if (dlg && !dlg.open) {
    dlg.showModal();
    const first = dlg.querySelector('input, [data-action="playDlgClose"]');  // 지우는 단추가 아니라 취소에서 시작한다
    if (first) first.focus();
  }
  if (S.play && S.route[1] !== 'new' && !S.route[2]) playPaintLive();
}

// 확인 칸을 Esc 로 닫으면 상태도 지운다 (close 는 거품이 일지 않아 잡는 단계에서 받는다)
document.addEventListener('close', (e) => {
  if (e.target && e.target.id === 'play-dlg' && S.playDlg) { S.playDlg = null; render(); }
}, true);

/** 화면을 다시 그린다. 입력 중이면 미루고(app.js render 가 입력을 마친 뒤 그린다) 남은 초만 고친다. */
function playDraw() {
  if (isTyping() && S.route[0] === 'play' && !S.focusTarget) { S.renderPending = true; playPaintLive(); return; }
  render();
}

/** 다시 그리지 않고 고치는 칸: 자동 결정 남은 초, 흐름 막대, 낭독 알림. */
function playPaintLive() {
  const c = S.playClock;
  if (!c) return;
  const v = playV();
  const ph = playPhase(c, v);
  const state = $('.pstate');  // 입력 중이라 다시 그리기를 미룬 동안에도 상태 글과 흐르기 단추는 맞춘다
  if (state && ph !== 'flowing') state.textContent = playStatusText(ph);
  const btn = $('.pplay');
  if (btn && ph === 'paused' && btn.getAttribute('aria-pressed') === 'true') {
    btn.setAttribute('aria-pressed', 'false');
    btn.setAttribute('aria-label', '흐르게 하기 (스페이스)');
    btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><path d="M5 3l10 6-10 6z" fill="currentColor"></path></svg>';
  }
  const left = $('#play-auto-left');
  if (left) left.textContent = c.auto != null ? `${Math.ceil(c.auto / 1000)}초 뒤 AI가 골라요` : '';
  const bar = $('#play-track');
  if (bar) {
    const items = v.items;
    const need = playGap(items[c.pos - 1], items[c.pos], v.unit) * PLAY_UNIT_MS;
    const pct = ph === 'decide' ? (c.auto != null ? Math.round(((PLAY_AUTO_MS - c.auto) / PLAY_AUTO_MS) * 100) : 100)
      : ph === 'flowing' && need ? Math.min(100, Math.round((c.acc / need) * 100)) : ph === 'paused' ? Number(bar.dataset.pct || 0) : 0;
    bar.style.width = `${pct}%`;
    bar.dataset.pct = pct;
  }
  playAnnounce(ph);
}

/** 낭독기 알림 (#play-live, role=status). 흐르는 중에는 줄마다 읽지 않고, 상태가 바뀔 때만 한 번. 멈추면 그동안 나온 새 줄 수. */
function playAnnounce(ph) {
  let box = $('#play-live');
  if (!box) {
    box = document.createElement('div');
    box.id = 'play-live';
    box.className = 'sr-only';
    box.setAttribute('role', 'status');
    document.body.appendChild(box);
  }
  if (S.route[0] !== 'play') { box.textContent = ''; playSaid = ''; return; }
  const c = S.playClock;
  let msg = playStatusText(ph);
  if (ph === 'paused' && c.news) { msg += ` · 새 일 ${c.news}줄`; }
  if (ph === playSaid.split('|')[0]) return;
  playSaid = `${ph}|${msg}`;
  if (ph === 'paused') S.playClock = playClock(c, { type: 'seen' });
  box.textContent = msg;
}

function playStatusText(ph) {
  const p = S.play;
  const last = p.turns[p.turns.length - 1];
  return {
    decide: '결정을 기다리고 있어요', ended: '이야기가 끝났어요', failed: `${last ? last.number : ''}구간 상태를 반영하지 못했어요`,
    error: '앞날을 쓰지 못했어요', paused: '멈췄어요 · 스페이스로 다시', writing: p.turns.length ? '앞날을 쓰는 중이에요' : '첫 구간을 쓰는 중이에요',
    flowing: `흐르는 중 · ${S.playClock.speed}×`,
  }[ph] || '';
}

// ---------- 그리기: 공통 ----------

function playTitleOf(x) {
  return x.title || '플레이';
}

function playSidebar(active) {
  const p = S.play;
  const href = `#/play/${enc(p.name)}`;
  const link = (id, to, mark, label) => navLink([id, to, mark, label], active);
  const meta = [p.days ? `${p.days}일 지남` : '', `결정 ${p.decisions}번`].filter(Boolean).join(' · ');
  const card = `<div class="work-card">
      <div class="small">플레이 · ${esc(p.world_title)}</div>
      <div class="work-head"><a class="work-title" href="${href}" title="${esc(playTitleOf(p))}">${esc(playTitleOf(p))}</a></div>
      <div class="small work-meta">${esc(meta)}${p.ending ? ' · 끝남' : ''}</div>
    </div>`;
  return `<nav class="side${S.menuOpen ? ' open' : ''}" aria-label="플레이 메뉴">
    ${sideTop({ hub: false, search: false })}
    ${card}
    <div class="side-menu" id="side-menu">
      ${drawerHead()}
      <div class="drawer-work">${card}</div>
      <div class="nav">${link('now', href, '🎲', '지금')}${link('past', href + '/past', '📜', '지난 일 · 되감기')}${link('life', href + '/life', '📔', '생애 기록')}</div>
      <div class="nav nav-extra"><span class="small">살펴보기 · 플레이 사본</span>
        ${link('cast', `#/p/${enc(p.name)}/cast`, '👥', '인물 · 관계도')}${link('atlas', `#/p/${enc(p.name)}/atlas`, '🗺️', '지도')}${link('timeline', `#/p/${enc(p.name)}/timeline`, '⏳', '작품 속 시간')}
        ${p.world_exists ? link('world', `#/p/${enc(p.world)}`, '🌐', `세계 작품 「${esc(p.world_title)}」로`) : ''}</div>
      ${p.world_exists ? '' : `<p class="small side-warn">세계 작품 「${esc(p.world)}」을 찾지 못했어요</p>`}
      ${sideFoot([['#/', '작품 목록']])}
    </div>
    ${S.menuOpen ? '<div class="side-scrim" data-action="toggleMenu" aria-hidden="true"></div>' : ''}
  </nav>`;
}

/** 플레이 화면들 (app.js drawApp). */
function viewPlayRoute() {
  const [, name, sub] = S.route;
  if (name === 'new' || !name) return S.playNew ? `<div class="shell"><main class="main play-new">${viewPlayNew()}</main></div>` : '';  // 시작한 뒤 플레이 화면으로 옮기는 사이
  if (!S.play) return '';
  const body = sub === 'past' ? viewPlayPast() : sub === 'life' ? viewPlayLife() : viewPlay();
  return `<div class="shell">${playSidebar(sub || 'now')}<main class="main play-main">${body}</main></div>${playDialog()}`;
}

// ---------- 그리기: 플레이 (안 A) ----------

function playParas(text) {
  return String(text || '').split(/\n+/).map((x) => x.trim()).filter(Boolean).map((x) => `<p>${esc(x)}</p>`).join('');
}

function viewPlay() {
  const p = S.play;
  const c = S.playClock;
  const v = playV();
  const ph = playPhase(c, v);
  const items = v.items;
  const shown = items.slice(0, c.pos);
  const eyebrow = [p.world_title, p.origin === 'random' ? '무작위 출생' : '세계 인물', PLAY_PERSONS[p.person] || '', `${PLAY_UNITS[p.unit] || p.unit} 단위`].filter(Boolean).join(' · ');
  const right = p.ending ? `<a class="btn primary" href="#/play/${enc(p.name)}/life">생애 기록</a>` : '<button type="button" class="btn" data-action="playEnd">끝내기</button>';
  return `${header(esc(eyebrow), playTitleOf(p), '', right)}
    ${playClockBar(ph)}
    <div class="play-cols">
      <section class="play-flow-col" aria-label="흘러간 일">
        ${playFlow(shown, ph)}
        ${playStage(ph)}
      </section>
      <aside class="play-aside" aria-label="내 인물과 주변">${playAside(ph)}</aside>
    </div>`;
}

function playClockBar(ph) {
  const p = S.play;
  const c = S.playClock;
  const now = playNow(S.playItems, c.pos, p.now) || '시작 전';
  const playing = c.run && ph !== 'decide';
  const blocked = ph === 'decide' || ph === 'ended';
  const icon = playing ? '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><rect x="4" y="3" width="3.5" height="12" fill="currentColor"></rect><rect x="10.5" y="3" width="3.5" height="12" fill="currentColor"></rect></svg>'
    : '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><path d="M5 3l10 6-10 6z" fill="currentColor"></path></svg>';
  const label = ph === 'decide' ? '결정 뒤에 흘러요' : ph === 'ended' ? '이야기가 끝났어요' : playing ? '멈추기 (스페이스)' : '흐르게 하기 (스페이스)';
  const tone = { decide: 'amber', failed: 'bad', error: 'bad', writing: 'busy' }[ph] || '';
  return `<div class="pclock${ph === 'decide' ? ' waiting' : ''}" role="group" aria-label="시간 흐름">
      <button type="button" class="pplay" data-action="playToggle" aria-pressed="${playing}" aria-label="${label}" aria-keyshortcuts="Space"${blocked ? ' aria-disabled="true"' : ''}>${ph === 'writing' && c.run ? '<span class="spinner" aria-hidden="true"></span>' : icon}</button>
      <div class="pnow"><strong>${esc(now)}</strong><span class="pstate ${tone}">${esc(playStatusText(ph))}${ph === 'flowing' && c.rush ? ' · 다음 결정까지' : ''}</span></div>
      <fieldset class="pspeed" aria-keyshortcuts="- +"><legend class="sr-only">배속 (−, + 키)</legend>${PLAY_SPEEDS.map((s) => `<label><input type="radio" name="play-speed" value="${s}"${c.speed === s ? ' checked' : ''}><span>${s}×</span></label>`).join('')}</fieldset>
      <span class="small">1× = ${PLAY_UNITS[p.unit] || '한 칸'} ${PLAY_UNIT_MS / 1000}초</span>
      <button type="button" class="btn small" data-action="playRush" aria-keyshortcuts="N"${blocked ? ' aria-disabled="true"' : ''}>다음 결정까지 »</button>
      <label class="pswitch"><input type="checkbox" id="play-auto"${p.auto_decide ? ' checked' : ''}${p.ending ? ' disabled' : ''}>자동 결정</label>
      <div class="ptrack" aria-hidden="true"><span id="play-track" class="${tone}"></span></div>
    </div>`;
}

/** 흘러간 일 목록. 요약으로 접은 장의 구간은 장 하나로 접어 둔다. 지난 결정 장면은 펼쳐 볼 수 있게. */
function playFlow(shown, ph) {
  const p = S.play;
  const byN = new Map(p.turns.map((t) => [t.number, t]));
  const closed = p.chapters.filter((a) => a.summary);
  const inClosed = (n) => closed.find((a) => a.start_ep <= n && n <= a.end_ep);
  const out = [];
  const folded = new Set();
  let lastN = null;
  for (const it of shown) {
    const t = byN.get(it.n);
    const ch = inClosed(it.n);
    if (ch) {
      if (!folded.has(ch.number)) {
        folded.add(ch.number);
        out.push(`<li class="pchap"><details><summary class="small"><strong>${esc(ch.title)}</strong>${ch.span ? ` · ${esc(ch.span)}` : ''} · 접힌 장</summary><p class="pbeat">${esc(ch.summary)}</p></details></li>`);
      }
      continue;
    }
    if (it.n !== lastN && t && t.action && PLAY_KINDS[t.kind]) out.push(`<li class="pact"><span class="pwhen">${PLAY_KINDS[t.kind]}</span><p>${esc(t.action)}</p></li>`);
    lastN = it.n;
    if (it.kind === 'beat') out.push(`<li><span class="pwhen">${esc(it.when)}</span><p class="pbeat">${esc(it.text)}</p></li>`);
    else if (t && !(ph === 'decide' && t.number === p.turns[p.turns.length - 1].number)) {
      out.push(`<li class="ppast"><span class="pwhen">결정</span><details><summary class="small">결정 장면 보기</summary><div class="pscene">${playParas(t.scene)}</div></details></li>`);
    }
  }
  if (!out.length) return `<p class="small pempty">${p.turns.length || ph === 'writing' ? '시간이 흐르면 여기에 한 줄씩 쌓여요.' : '아직 흘러간 일이 없어요.'}</p>`;
  return `<ol class="pflow" aria-live="off">${out.join('')}</ol>`;
}

/** 흐름 목록 아래: 결정 장면 · 쓰는 중 · 실패 · 끝 · 끼어들기 칸. */
function playStage(ph) {
  const p = S.play;
  const c = S.playClock;
  const last = p.turns[p.turns.length - 1];
  if (ph === 'decide') {
    const when = playNow(S.playItems, c.pos, p.now);
    const auto = p.auto_decide && c.held !== last.number;
    return `<article class="pdecide" aria-labelledby="play-dec-h">
      <div class="row"><h2 id="play-dec-h" tabindex="-1">${esc(when || '지금')}</h2><span class="chip warn">결정</span></div>
      <div class="pscene">${playParas(last.scene)}</div>
      ${auto ? `<div class="note warn row" style="justify-content:space-between"><span><strong>자동 결정</strong> <span id="play-auto-left">${c.auto != null ? `${Math.ceil(c.auto / 1000)}초 뒤 AI가 골라요` : '시간이 흐르면 AI가 골라요'}</span> · 아무 키나 누르면 기다려요</span><button type="button" class="btn small" data-action="playHold">기다리기</button></div>` : ''}
      <section aria-labelledby="play-act-h" class="pchoices">
        <h3 id="play-act-h">어떻게 할까요?</h3>
        <ol aria-label="선택지">${last.choices.map((x, i) => `<li><button type="button" class="pchoice" data-action="playChoose" data-arg="${i + 1}" aria-keyshortcuts="${i + 1}"><span class="kbd" aria-hidden="true">${i + 1}</span>${esc(x)}</button></li>`).join('')}</ol>
        ${playFreeBox('직접 해 보기', '세계 규칙에 어긋나면 실패하거나 대가를 치러요', `고르면 시간이 다시 흘러요 · 숫자 키 1~${last.choices.length}, 입력칸에서는 Ctrl+Enter`)}
      </section>
    </article>`;
  }
  if (ph === 'ended') {
    return `<div class="pend"><span class="small">${p.days ? `작품 속 ${p.days}일 · ` : ''}결정 ${p.decisions}번</span><strong>${esc(p.me.name)}의 이야기가 끝났어요</strong><span>${esc(p.ending)}</span>
      <div class="row"><a class="btn primary" href="#/play/${enc(p.name)}/life">생애 기록 보기</a><a class="btn" href="#/play/${enc(p.name)}/past">되감아 이어 가기</a></div></div>`;
  }
  if (ph === 'failed') {
    const back = p.turns.filter((t) => t.state === 'applied').slice(-1)[0];
    return `<div class="note err" role="alert"><strong>${last.number}구간 상태를 반영하지 못했어요.</strong> ${esc(last.error || '')} 본 날들은 그대로 둬요.</div>
      <div class="row"><button type="button" class="btn primary" data-action="playRetry">다시 시도</button><a class="btn" href="#/play/${enc(p.name)}/past">${back ? `${back.number}구간으로 되감기` : '되감기'}</a></div>`;
  }
  if (ph === 'error') {
    return `<div class="note err" role="alert"><strong>앞날을 쓰지 못했어요.</strong> ${esc(p.job ? p.job.error : '')}</div>
      <div class="row"><button type="button" class="btn primary" data-action="playRetry">다시 시도</button></div>`;
  }
  const writing = ph === 'writing' || (ph === 'paused' && c.pos >= S.playItems.length && (p.job && p.job.status === 'running'));
  const since = p.job && p.job.status === 'running' ? Math.max(0, Math.round(Date.now() / 1000 - p.job.started)) : 0;
  return `${writing ? `<div class="pwriting"><span class="spinner small" aria-hidden="true"></span><span>앞날을 쓰는 중이에요${since ? ` · ${since}초` : ''}</span><span class="psk" aria-hidden="true"></span></div>` : ''}
    ${p.ending ? '' : `<details class="pinterrupt"${S.playDraft ? ' open' : ''}><summary class="btn small" aria-keyshortcuts="I">끼어들기 · 직접 해 보기</summary>
      ${playFreeBox('지금 하고 싶은 일', '적기 시작하면 시간이 멈춰요. 지금 구간이 끝나는 자리에서 해 봐요', '입력칸에서는 Ctrl+Enter')}</details>`}`;
}

function playFreeBox(label, hint, foot) {
  return `<div class="field pfree"><label for="play-free">${label} <span class="hint">${hint}</span></label>
      <textarea id="play-free" rows="2" placeholder="예: 경매 종을 한 번 더 쳐서 사람들의 눈을 돌린다">${esc(S.playDraft || '')}</textarea></div>
    <div class="between"><span class="small">${foot}</span><button type="button" class="btn primary" data-action="playFree">해 보기</button></div>`;
}

function playAside() {
  const p = S.play;
  const me = p.me;
  const custom = p.focus && !PLAY_FOCUS.includes(p.focus);
  const dl = [['감정', me.emotion], ['목표', me.goal], ['장소', me.location], ['차림', me.attire]].filter(([, x]) => x);
  return `<section class="card tight" aria-labelledby="play-focus-h">
      <h2 id="play-focus-h">요즘의 초점</h2>
      <div class="pfocus" role="group" aria-label="초점">${PLAY_FOCUS.map((f) => `<button type="button" aria-pressed="${p.focus === f}" data-action="playFocus" data-arg="${esc(f)}">${esc(f)}</button>`).join('')}${custom ? `<button type="button" aria-pressed="true" data-action="playFocus" data-arg="">${esc(p.focus)}</button>` : ''}</div>
      <span class="small">결정 사이에 흘러가는 날들이 이 초점을 따라가요. 다시 누르면 AI가 정해요. 다음 구간부터 따라요.</span>
    </section>
    <section class="card tight" aria-labelledby="play-me-h">
      <div class="between"><h2 id="play-me-h">${esc(me.name)}</h2><span class="small">${esc([me.gender, me.age, p.origin === 'random' ? '무작위 출생' : me.role].filter(Boolean).join(' · '))}</span></div>
      ${dl.length ? `<dl class="pdl">${dl.map(([k, x]) => `<dt>${k}</dt><dd>${esc(x)}</dd>`).join('')}</dl>` : '<span class="small">아직 상태가 없어요. 첫 구간을 반영하면 채워져요.</span>'}
      ${p.stats.length ? `<div class="pstat" role="group" aria-label="${esc(me.name)} ${esc(p.stat_title)}"><div class="pstat-t">【 ${esc(p.stat_title)} 】</div>${p.stats.map((x) => `<div class="pstat-r"><span>${esc(x.name)}</span><span>${esc(x.value)}</span></div>`).join('')}</div>` : ''}
    </section>
    ${p.deadlines.length ? `<section class="card tight" aria-labelledby="play-dl-h"><h2 id="play-dl-h">열린 기한</h2><ul class="plist">${p.deadlines.map((d) => `<li><span>${esc(d.what)}</span>${d.left ? `<span class="chip${/남음/.test(d.left) && parseInt(d.left, 10) <= 2 || d.left === '오늘' ? ' warn' : ''}">${esc(d.left)}</span>` : ''}</li>`).join('')}</ul></section>` : ''}
    ${p.near.length ? `<section class="card tight" aria-labelledby="play-near-h"><h2 id="play-near-h">가까운 사람</h2><ul class="pnear">${p.near.map((x) => `<li>
        <div class="between"><strong>${esc(x.name)}</strong><span class="small${x.tension_value >= 5 ? ' hot' : ''}">긴장 ${esc(x.tension)}</span></div>
        <div class="small">${esc(me.name)}에게 ${esc(x.warmth)} · ${esc(x.trust)}</div>
        <div class="pbar" aria-hidden="true"><span style="width:${Math.round(((x.warmth_value + 1) / 2) * 100)}%"></span></div></li>`).join('')}</ul></section>` : ''}`;
}

// ---------- 그리기: 지난 일 · 되감기 ----------

function viewPlayPast() {
  const p = S.play;
  const turns = p.turns;
  const chapters = p.chapters.length ? p.chapters : [{ number: 0, title: '플레이', start_ep: p.world_ep + 1, end_ep: 1e9, summary: '', span: '' }];
  const lastN = turns.length ? turns[turns.length - 1].number : p.world_ep;
  const row = (t) => {
    const first = t.beats[0];
    const decided = turns.find((x) => x.number === t.number + 1);
    const can = t.state === 'applied' && t.number !== lastN;
    const what = t.choices.length
      ? (decided ? `<span class="pdone">${decided.kind === 'auto' ? '자동 결정' : '결정'} · ${esc(decided.action)}</span>` : '<span class="chip warn">결정을 기다리고 있어요</span>')
      : '<span class="small">결정 없이 흘렀어요</span>';
    return `<li class="prow${t.number === lastN ? ' cur' : ''}"${t.number === lastN ? ' aria-current="true"' : ''}>
        <span class="small pwhen">${esc(t.when || (first && first.when) || `${t.number}구간`)}</span>
        <div class="pcol"><span>${esc(t.summary && t.kind !== 'flow' ? t.summary : first ? first.text : t.scene.slice(0, 80))}</span>${what}
          <span class="small">${t.state === 'applied' ? '상태 반영함' : t.state === 'failed' ? '반영 실패' : '반영 중'} · 흘러간 일 ${t.beats.length}줄</span></div>
        <div class="row">${can ? `<button type="button" class="btn small" data-action="playAskRewind" data-arg="${t.number}">여기로 되감기</button><button type="button" class="btn small" data-action="playAskFork" data-arg="${t.number}">여기서 다르게 해 보기</button>` : ''}</div>
      </li>`;
  };
  const groups = chapters.map((a) => {
    const mine = turns.filter((t) => a.start_ep <= t.number && t.number <= a.end_ep);
    if (!mine.length) return '';
    const open = !a.summary;
    return `<details class="card tight pchapter"${open ? ' open' : ''}><summary><span class="pcol"><strong>${esc(a.title)}</strong><span class="small">${esc(a.span || `${mine.length}구간`)} · 결정 ${mine.filter((t) => PLAY_KINDS[t.kind]).length}번</span></span><span class="chip${open ? ' finalized' : ''}">${open ? '지금' : '접힘'}</span></summary>
      ${a.summary ? `<p class="small" style="line-height:1.6">${esc(a.summary)}</p>` : ''}<ol class="prows" aria-label="${esc(a.title)} 구간">${mine.map(row).join('')}</ol></details>`;
  }).join('');
  return `${header(esc(playTitleOf(p)), '지난 일 · 되감기', '결정한 순간마다 되감을 수 있어요. 지우지 않고 다른 길을 가 보려면 \'여기서 다르게 해 보기\'로 이 플레이를 남긴 채 사본을 만드세요.')}
    ${turns.length ? groups : '<p class="small">아직 지난 일이 없어요.</p>'}
    ${turns.length ? `<div class="row"><button type="button" class="btn small" data-action="playAskRewind" data-arg="${p.world_ep}">처음으로 되감기</button><span class="small">세계 작품 ${p.world_ep}화 직후, 첫 구간 전으로 돌아가요</span></div>` : ''}`;
}

/** 되감기 · 다르게 해 보기 확인 칸 (<dialog>). S.playDlg = { kind: 'rewind' | 'fork', n } */
function playDialog() {
  const d = S.playDlg;
  if (!d) return '';
  const p = S.play;
  const t = p.turns.find((x) => x.number === d.n);
  const at = d.n === p.world_ep ? '첫 구간 전' : `${t && t.when ? t.when : `${d.n}구간`} 직후`;
  if (d.kind === 'fork') {
    return `<dialog id="play-dlg" class="pdlg" aria-labelledby="play-dlg-h">
      <form method="dialog" class="pcol" data-play-fork>
        <h2 id="play-dlg-h">${esc(at)}에서 다르게 해 볼까요?</h2>
        <p class="desc">이 플레이는 그대로 두고, 사본을 만들어 그때로 되감아요. 사본은 같은 세계 카드 안에 묶여요.</p>
        <div class="field"><label for="play-fork-title">사본 이름</label><input id="play-fork-title" type="text" value="${esc(d.title || '')}"></div>
        <div class="field"><label for="play-fork-to">폴더 이름</label><input id="play-fork-to" type="text" value="${esc(d.to || '')}" required></div>
        ${d.err ? `<div class="small field-err" role="alert">${esc(d.err)}</div>` : ''}
        <div class="row" style="justify-content:flex-end"><button type="button" class="btn" data-action="playDlgClose">취소</button><button type="submit" class="btn primary">사본 만들기</button></div>
      </form></dialog>`;
  }
  return `<dialog id="play-dlg" class="pdlg" aria-labelledby="play-dlg-h">
    <div class="pcol">
      <h2 id="play-dlg-h">${esc(at)}로 되감을까요?</h2>
      <p class="desc">그 뒤에 흘러간 일과 장면이 지워지고, 인물 상태도 그때로 돌아가요. 시간은 멈춘 채로 돌아가고, 같은 결정으로 다시 흘려도 앞날은 새로 써요.</p>
      <p class="small">지우고 싶지 않으면 '여기서 다르게 해 보기'로 이 플레이를 남긴 채 사본을 만들 수 있어요.</p>
      <div class="row" style="justify-content:flex-end"><button type="button" class="btn" data-action="playDlgClose">취소</button>${d.n !== p.world_ep ? `<button type="button" class="btn" data-action="playAskFork" data-arg="${d.n}">여기서 다르게 해 보기</button>` : ''}<button type="button" class="btn danger" data-action="playRewind">되감기</button></div>
    </div></dialog>`;
}

// ---------- 그리기: 생애 기록 ----------

function playLifeText(l) {
  const lines = [`${l.player} · ${l.world_title}`, [l.gender, l.age, l.place && `${l.place}에서 태어남`].filter(Boolean).join(' · '), l.ending ? `끝: ${l.ending}` : '아직 이어지는 중',
    `작품 속 ${l.days}일 · 결정 ${l.decisions}번 · 직접 해 본 일 ${l.free}번`, ''];
  if (l.background) lines.push(l.background, '');
  l.chapters.forEach((a) => lines.push(`${a.title}${a.span ? ` (${a.span})` : ''}`, a.summary || '아직 접지 않은 장', ''));
  if (l.relations.length) lines.push('관계 변화', ...l.relations.map((r) => `- ${r.name}: ${r.before || '모르는 사이'} → ${r.after} · ${r.trust}`), '');
  if (l.last_text) lines.push(`마지막 장면${l.last_when ? ` · ${l.last_when}` : ''}`, l.last_text);
  return lines.join('\n');
}

function viewPlayLife() {
  const l = S.playLife;
  if (!l) return '<p class="small">불러오는 중이에요</p>';
  const p = S.play;
  const chips = [l.archetype && `원형 · ${l.archetype}`, l.wound && `상처 · ${l.wound}`, l.speech && `말투 · ${l.speech}`, l.twist && `비틀기 · ${l.twist}`].filter(Boolean);
  return `<article class="plife" aria-labelledby="play-life-h">
    <header class="pcol">
      <span class="small" style="font-weight:700">생애 기록 · ${esc(l.world_title)}</span>
      <h1 id="play-life-h">${esc(l.player)}</h1>
      <div class="small" style="font-size:0.875rem">${esc([l.gender, l.age, l.place && `${l.place}에서 태어남`, l.origin === 'random' ? `시드 ${l.seed}` : '세계 인물'].filter(Boolean).join(' · '))}</div>
      <div class="row">${l.ending ? `<span class="chip finalized">끝남</span><span class="chip">${esc(l.ending)}</span>` : '<span class="chip">아직 이어지는 중</span>'}</div>
    </header>
    <div class="plife-stats">
      <div><span class="small">작품 속 시간</span><b>${l.days}일</b></div><div><span class="small">결정</span><b>${l.decisions}번</b></div>
      <div><span class="small">직접 해 본 일</span><b>${l.free}번</b></div><div><span class="small">장</span><b>${l.chapters.length}장</b></div>
    </div>
    ${l.origin === 'random' || l.background ? `<section aria-labelledby="pl-birth-h"><h2 id="pl-birth-h">${l.origin === 'random' ? '출생 카드' : '인물'}</h2>${chips.length ? `<div class="row">${chips.map((x) => `<span class="chip">${esc(x)}</span>`).join('')}</div>` : ''}${l.background ? `<p>${esc(l.background)}</p>` : ''}</section>` : ''}
    <section aria-labelledby="pl-ch-h"><h2 id="pl-ch-h">장별 요약</h2>
      <ol class="plife-ch">${l.chapters.map((a) => `<li><span><strong>${esc(a.title)}</strong><br><span class="small">${esc(a.span || `${a.start_ep - p.world_ep}~${a.end_ep - p.world_ep}구간`)}</span></span><span>${esc(a.summary || '아직 접지 않은 장이에요. 장이 끝나면 요약이 생겨요.')}</span></li>`).join('')}</ol></section>
    ${l.relations.length ? `<section aria-labelledby="pl-rel-h"><h2 id="pl-rel-h">관계 변화 · 처음 → 끝</h2>
      <ul class="plife-rel">${l.relations.map((r) => `<li><strong>${esc(r.name)}</strong><span class="row"><span class="chip">${esc(r.before || '모르는 사이')}</span><span aria-label="에서">→</span><span class="chip">${esc(r.after)}</span><span class="small">${esc(r.trust)}</span></span></li>`).join('')}</ul></section>` : ''}
    ${l.last_text ? `<section aria-labelledby="pl-last-h"><h2 id="pl-last-h">마지막 장면${l.last_when ? ` · ${esc(l.last_when)}` : ''}</h2><blockquote class="pscene">${playParas(l.last_text)}</blockquote></section>` : ''}
    <div class="row">
      <a class="btn primary" href="#/play/${enc(p.name)}/past">되감아 이어 가기</a>
      ${p.world_exists ? `<a class="btn" href="#/play/new/${enc(p.world)}">같은 세계로 새 플레이</a>` : ''}
      <button type="button" class="btn" data-action="playCopyLife">글로 복사</button>
    </div>
    <p class="small">생애 기록은 이 컴퓨터의 플레이 폴더에만 있어요. 되감아 이어 가면 끝난 표시가 지워지고, 이 기록은 새 끝에 맞춰 다시 만들어져요.</p>
  </article>`;
}

// ---------- 그리기: 새 플레이 ----------

function playNewForm(world) {
  return { world, mode: 'random', char: '', card: null, seed: '', gender: '', age: '', sketch: null, sketchJob: null, sketchErr: '',
    person: 'second', unit: 'auto', until: 'none', days: '60', decisions: '50', auto: false, focus: '', title: '', to: '', toEdited: false,
    newWorld: false, nwName: '', nwLine: '', nwGenres: [], nwAdult: false, nwJob: null, nwErr: '', err: '' };
}

/** 플레이 폴더 이름: '<세계>-<플레이 이름>', 이미 있으면 -2, -3 … (home.js folderOf 와 같은 규칙) */
function playFolder(world, title, taken) {
  const head = folderOf(`${world}-${title || 'play'}`) || 'play';
  let name = head;
  for (let k = 2; taken.has(name); k++) name = `${head.slice(0, 60)}-${k}`;
  return name;
}

function playWho(f) {
  if (f.mode === 'random') return f.card ? f.card.birth.name : '';
  const c = S.playWorld && S.playWorld.characters.find((x) => x.id === f.char);
  return c ? c.name : '';
}

function viewPlayNew() {
  const f = S.playNew;
  const w = S.playWorld;
  const worlds = (S.projects || []).filter((x) => !x.play);
  const taken = new Set((S.projects || []).map((x) => x.name));
  const who = playWho(f);
  const title = f.title || (who ? `${who}의 삶` : '');
  const to = f.toEdited ? f.to : playFolder(f.world, title, taken);
  const step = (n, label) => `<h2 class="pstep"><b aria-hidden="true">${n}</b>${label}</h2>`;
  const worldOpts = worlds.map((x) => `<label class="popt${f.world === x.name && !f.newWorld ? ' on' : ''}"><input type="radio" name="play-world" value="${esc(x.name)}"${f.world === x.name && !f.newWorld ? ' checked' : ''}><span class="pcol"><strong>${esc(x.title || x.name)}</strong><span class="small">${x.form === 'serial' ? '장편' : '단편'} · ${x.finalized}화 반영 · ${esc(x.genre || '장르 미정')}</span></span></label>`).join('');
  const nw = f.newWorld ? `<div class="card tight pnewworld">
      <div class="field"><span class="label">장르</span><div class="pfocus" role="group" aria-label="장르">${(S.genres || []).filter((g) => g.kind === '장르').map((g) => `<button type="button" aria-pressed="${f.nwGenres.includes(g.id)}" data-action="playNwGenre" data-arg="${esc(g.id)}">${esc(g.name)}</button>`).join('')}</div></div>
      <div class="field"><label for="pn-line">한 줄 <span class="hint">어떤 세계인지</span></label><input id="pn-line" type="text" value="${esc(f.nwLine)}" placeholder="예: 안개가 걷히지 않는 항구 도시에서 사람들이 하나씩 사라진다"></div>
      <div class="field"><label for="pn-name">폴더 이름</label><input id="pn-name" type="text" value="${esc(f.nwName)}" placeholder="fog-harbor"></div>
      <label class="row"><input type="checkbox" id="pn-adult"${f.nwAdult ? ' checked' : ''}> 성인 작품</label>
      ${f.nwJob ? `<div class="row" role="status"><span class="spinner small" aria-hidden="true"></span>세계 설정을 제안하는 중이에요. 보통 1분쯤 걸려요. 다른 화면에 가도 계속돼요.</div>` : `<div class="row"><button type="button" class="btn primary" data-action="playMakeWorld">세계 만들기</button><span class="small">끝나면 일반 작품으로 저장하고 2단계로 넘어가요.</span></div>`}
      ${f.nwErr ? `<div class="note err" role="alert">${esc(f.nwErr)}</div>` : ''}
    </div>` : '';
  const lock = !w;
  const chars = w ? w.characters.map((c) => `<label class="popt${f.char === c.id ? ' on' : ''}"><input type="radio" name="play-char" value="${esc(c.id)}"${f.char === c.id ? ' checked' : ''}><span class="pcol"><strong>${esc(c.name)}</strong> <span class="small">${esc([c.role, c.age].filter(Boolean).join(' · '))}</span><span class="small">${esc(c.summary)}${c.goal || c.emotion ? ` 지금: ${esc([c.goal, c.emotion].filter(Boolean).join(' · '))}` : ''}</span></span></label>`).join('') : '';
  const b = f.card && f.card.birth;
  const sk = f.sketch;
  const birthCard = b ? `<div class="pbirth" aria-labelledby="pb-name">
      <div class="between"><span class="small">출생 카드</span><span class="small">시드 ${b.seed}</span></div>
      <h3 id="pb-name" class="pbirth-name">${esc(b.name || '이름 없음')}</h3>
      <div class="small" style="font-size:0.875rem">${esc([b.gender, b.age, b.place && `${b.place}에서 태어남`].filter(Boolean).join(' · '))}</div>
      <div class="row">${[`원형 · ${f.card.archetype}`, `상처 · ${f.card.wound}`, `말투 · ${f.card.speech}`, b.twist && `비틀기 · ${b.twist}`].filter(Boolean).map((x) => `<span class="chip">${esc(x)}</span>`).join('')}</div>
      ${sk ? `<dl class="pdl wide"><dt>배경</dt><dd>${esc(sk.background)}</dd><dt>목표</dt><dd>${esc(sk.goal)}</dd><dt>첫 장면</dt><dd>${esc(sk.opening)}</dd></dl>`
        : f.sketchJob ? '<div class="row" role="status"><span class="spinner small" aria-hidden="true"></span>AI가 배경을 쓰는 중이에요</div>'
          : `<div class="row"><button type="button" class="btn small" data-action="playSketch">배경 채우기</button>${f.sketchErr ? `<span class="small bad" role="alert">${esc(f.sketchErr)}</span>` : ''}</div>`}
      <span class="small">이름 · 원형 · 상처 · 말투 · 태어난 곳은 코드가 굴렸어요. AI는 배경 · 목표 · 첫 장면만 채워요.</span>
      <div class="row"><button type="button" class="btn small" data-action="playRoll" data-arg="new">다시 굴리기</button>${sk ? '<button type="button" class="btn small" data-action="playSketch">배경만 다시 쓰기</button>' : ''}</div>
      <details><summary class="small">시드 · 고정할 값</summary><div class="grid-2" style="padding-top:8px">
        <div class="field"><label for="pb-seed">시드</label><input id="pb-seed" type="number" value="${esc(f.seed)}" placeholder="${b.seed}"></div>
        <div class="field"><label for="pb-gender">성별</label><select id="pb-gender"><option value="">굴리기</option><option value="여"${f.gender === '여' ? ' selected' : ''}>여</option><option value="남"${f.gender === '남' ? ' selected' : ''}>남</option></select></div>
        <div class="field"><label for="pb-age">나이</label><input id="pb-age" type="text" value="${esc(f.age)}" placeholder="굴리기 (예: 20세)"></div>
        <div class="field" style="justify-content:flex-end"><button type="button" class="btn small" data-action="playRoll">이 값으로 굴리기</button></div>
      </div><span class="small">같은 시드면 같은 출생이에요.</span></details>
    </div>` : '';
  const name = who || '그 인물';
  const ready = w && (f.mode === 'char' ? !!f.char : !!(b && sk));
  return `<div class="small"><a href="#/">작품 목록</a> › 새 플레이</div>
    ${header('플레이 모드', '새 플레이', '세계를 고르고, 그 세계에서 누가 될지 정해요. 플레이는 세계 작품을 복사해 따로 두니 세계 작품은 바뀌지 않아요.')}
    ${aiNote()}
    <section class="card" aria-labelledby="pn-1">${step(1, '<span id="pn-1">세계</span>')}
      <div class="pgrid">${worldOpts}<label class="popt${f.newWorld ? ' on' : ''}"><input type="radio" name="play-world" value=""${f.newWorld ? ' checked' : ''}><span class="pcol"><strong>새 세계</strong><span class="small">장르와 한 줄로 세계를 만들어요. 일반 작품으로 남아요</span></span></label></div>
      ${nw}
    </section>
    <section class="card${lock ? ' plock' : ''}" aria-labelledby="pn-2">${step(2, '<span id="pn-2">누가 될까요?</span>')}
      ${lock ? '<p class="small">세계를 고르면 열려요.</p>' : `<div class="pseg" role="radiogroup" aria-label="누가 될까요">
        <label class="${f.mode === 'char' ? 'on' : ''}"><input type="radio" name="play-mode" value="char"${f.mode === 'char' ? ' checked' : ''}>세계의 인물이 되기</label>
        <label class="${f.mode === 'random' ? 'on' : ''}"><input type="radio" name="play-mode" value="random"${f.mode === 'random' ? ' checked' : ''}>무작위로 태어나기</label></div>
      ${f.mode === 'char' ? `<div class="pgrid">${chars || '<p class="small">이 세계에는 아직 인물이 없어요.</p>'}</div><span class="small">${w.world_ep}화 반영 직후의 상태로 그 인물이 돼요.</span>` : birthCard}`}
    </section>
    <section class="card${lock ? ' plock' : ''}" aria-labelledby="pn-3">${step(3, '<span id="pn-3">서술 시점</span>')}
      ${lock ? '' : `<div class="pgrid three">${[['first', '1인칭 · 나', '나는'], ['second', '2인칭 · 당신', '당신은'], ['third', '3인칭', `${name}${josa(name, '은', '는')}`]].map(([k, l, s]) => `<label class="popt${f.person === k ? ' on' : ''}"><input type="radio" name="play-person" value="${k}"${f.person === k ? ' checked' : ''}><span class="pcol"><strong>${l}</strong><span class="small">${esc(s)} 문을 밀었다.</span></span></label>`).join('')}</div>`}
    </section>
    <section class="card${lock ? ' plock' : ''}" aria-labelledby="pn-4">${step(4, '<span id="pn-4">시간</span>')}
      ${lock ? '' : `<div class="grid-2">
        <div class="field"><label for="pn-unit">시간 단위 · 흐름 한 칸</label><select id="pn-unit">${[['auto', `자동 · ${PLAY_UNITS[w.unit]}`], ...Object.entries(PLAY_UNITS)].map(([k, l]) => `<option value="${k}"${f.unit === k ? ' selected' : ''}>${l}</option>`).join('')}</select>
          <span class="small">자동은 세계 작품의 화 사이 시간 간격을 보고 골라요. 1×에서 한 칸이 ${PLAY_UNIT_MS / 1000}초에 흘러요.</span></div>
        <fieldset class="puntil"><legend class="label">언제까지</legend>
          <label class="row"><input type="radio" name="play-until" value="none"${f.until === 'none' ? ' checked' : ''}>이야기가 끝날 때까지</label>
          <label class="row"><input type="radio" name="play-until" value="days"${f.until === 'days' ? ' checked' : ''}>작품 속 <input id="pn-days" type="number" min="1" class="pnum" value="${esc(f.days)}" aria-label="날수">일</label>
          <label class="row"><input type="radio" name="play-until" value="decisions"${f.until === 'decisions' ? ' checked' : ''}>결정 <input id="pn-dec" type="number" min="1" class="pnum" value="${esc(f.decisions)}" aria-label="결정 수">번</label>
        </fieldset></div>
        <label class="row"><input type="checkbox" id="pn-auto"${f.auto ? ' checked' : ''}><span><strong>자동 결정으로 시작</strong> <span class="small">결정 장면에서 ${PLAY_AUTO_MS / 1000}초 뒤 AI가 골라요. 플레이 중에도 바꿀 수 있어요</span></span></label>
        <div class="grid-2"><div class="field"><label for="pn-title">플레이 이름</label><input id="pn-title" type="text" value="${esc(title)}" placeholder="${esc(who ? `${who}의 삶` : '')}"></div>
          <div class="field"><label for="pn-to">폴더 이름</label><input id="pn-to" type="text" value="${esc(to)}"></div></div>`}
    </section>
    ${f.err ? `<div class="note err" role="alert">${esc(f.err)}</div>` : ''}
    <div class="row"><button type="button" class="btn primary" data-action="playBegin"${ready ? '' : ' aria-disabled="true"'}>플레이 시작</button>
      <span class="small">${ready ? '첫 구간을 쓰는 데 30초쯤 걸려요. 다 쓰면 시간이 흐르기 시작해요' : f.mode === 'char' ? '될 인물을 고르세요' : '출생 카드의 배경을 채우면 시작할 수 있어요'}</span></div>`;
}

// ---------- 작품 홈 (home.js 가 부른다). 작품 목록의 플레이 줄은 home.js plGroupRows ----------

/** 작품 홈을 열 때 그 작품이 플레이 사본인지 알아 둔다 (app.js routeNow). 사본이면 플레이 정보, 아니면 null. */
async function playHomeLoad() {
  S.homePlay = null;
  const name = S.name;
  try {
    const v = await api('GET', `/projects/${enc(name)}/play`);
    if (S.name === name) S.homePlay = v;
  } catch { /* 플레이 사본이 아니다 */ }
}

/** 작품 홈의 '이 세계로 플레이' 카드. 플레이 사본이면 플레이로 돌아가는 카드. */
function playHomeCard() {
  const q = S.homePlay;
  if (q && q.name === S.name) {
    return `<section class="card tight note-card"><div class="between"><h2>플레이 사본이에요</h2><a class="btn small primary" href="#/play/${enc(q.name)}">플레이로 돌아가기</a></div>
      <p class="small" style="line-height:1.6">「${esc(q.world_title)}」 세계의 플레이 '${esc(q.title)}'예요. 여기서 고친 것은 이 플레이에만 들어가요. 구간은 플레이 화면에서 이어 가세요.</p></section>`;
  }
  const fin = P().episodes.filter((e) => e.status === 'finalized').length;
  return `<section class="card tight"><div class="between"><h2>이 세계로 플레이</h2><a class="btn small" href="#/play/new/${enc(S.name)}">새 플레이</a></div>
    <p class="small" style="line-height:1.6">이 세계 속 인물이 되거나 무작위로 태어나서, 시간이 흐르는 동안 갈림길마다 결정해요. ${fin ? `${fin}화를 반영한 직후의 세계에서 시작하고` : '반영한 화가 없으면 이야기 시작 전에서 시작하고'}, 세계 작품은 바뀌지 않아요.</p></section>`;
}

// ---------- 동작 ----------

async function playRoll(fresh) {
  const f = S.playNew;
  const seed = fresh === 'new' ? null : (f.seed !== '' ? Number(f.seed) : (f.card ? f.card.birth.seed : null));
  if (fresh === 'new') f.seed = '';
  try {
    f.card = await api('POST', `/projects/${enc(f.world)}/play/roll`, { seed, gender: f.gender, age: f.age });
    f.sketch = null;
    f.sketchErr = '';
    f.err = '';
  } catch (e) {
    f.err = e.message;
    return;
  }
  playSketchStart();
}

async function playSketchStart() {
  const f = S.playNew;
  if (!f.card) return;
  f.sketch = null;
  f.sketchErr = '';
  try {
    const j = await api('POST', `/projects/${enc(f.world)}/play/sketch`, { birth: f.card.birth });
    f.sketchJob = j.id;
  } catch (e) {
    f.sketchErr = e.message;
    if (S.route[0] === 'play') render();
    return;
  }
  if (S.route[0] === 'play') render();
  playWatchJob(j => j.id === f.sketchJob, (j) => {
    if (S.playNew !== f || f.sketchJob !== j.id) return;
    f.sketchJob = null;
    if (j.status === 'done') f.sketch = j.result;
    else f.sketchErr = j.status === 'error' ? `배경을 쓰지 못했어요: ${j.error}` : '';
    if (S.route[0] === 'play' && S.route[1] === 'new') render();
  }, f.sketchJob);
}

/** 작업 하나가 끝날 때까지 1초마다 묻는다 (새 플레이 화면의 배경 · 새 세계). */
function playWatchJob(_match, done, jid) {
  const tick = async () => {
    let j;
    try { j = await api('GET', `/jobs/${enc(jid)}`); } catch (e) { done({ id: jid, status: 'error', error: e.message }); return; }
    if (j.status === 'running') { setTimeout(tick, 1000); return; }
    done(j);
  };
  setTimeout(tick, 800);
}

function playReadNew() {
  const f = S.playNew;
  const v = (id) => ($(id) || {}).value;
  if ($('#pn-line')) { f.nwLine = v('#pn-line'); f.nwName = v('#pn-name'); f.nwAdult = !!$('#pn-adult').checked; }
  if ($('#pb-seed')) { f.seed = v('#pb-seed'); f.gender = v('#pb-gender'); f.age = v('#pb-age'); }
  if ($('#pn-unit')) {
    f.unit = v('#pn-unit'); f.days = v('#pn-days'); f.decisions = v('#pn-dec'); f.auto = !!$('#pn-auto').checked;
    const t = v('#pn-title');
    const who = playWho(f);
    f.title = t === (who ? `${who}의 삶` : '') ? '' : t;
    const taken = new Set((S.projects || []).map((x) => x.name));
    const to = v('#pn-to');
    f.toEdited = to !== playFolder(f.world, f.title || (who ? `${who}의 삶` : ''), taken);
    f.to = to;
  }
}

Object.assign(actions, {
  playToggle() {
    S.playClock = playClock(S.playClock, { type: 'toggle' });
    playDraw();
  },
  playRush() {
    S.playClock = playClock(S.playClock, { type: 'rush' });
    playDraw();
  },
  playHold() {
    S.playClock = playClock(S.playClock, { type: 'hold' }, playV());
    playDraw();
  },
  playChoose(i) {
    playAct({ choice: Number(i) });
  },
  playFree() {
    const box = $('#play-free');
    const text = (box ? box.value : S.playDraft || '').trim();
    if (!text) { toast('해 볼 일을 적어 주세요', true); if (box) box.focus(); return; }
    S.playDraft = text;
    playAct({ action: text });
  },
  playRetry() {
    const p = S.play;
    playAct(playRetryBody(p.turns[p.turns.length - 1], S.playLastAct));
  },
  async playFocus(f) {
    const p = S.play;
    const focus = p.focus === f ? '' : (f || '');
    try { playSet(await api('PUT', `/projects/${enc(p.name)}/play/settings`, { focus })); } catch (e) { return showError(e); }
    toast(focus ? `초점을 '${focus}'(으)로 바꿨어요. 다음 구간부터 따라요` : '초점을 AI가 정하게 했어요');
    playDraw();
  },
  playEnd() {
    if (!confirm('플레이를 끝낼까요? 도는 쓰기는 멈춰요. 되감으면 다시 이어 갈 수 있어요')) return;
    run('끝내는 중', async () => {
      playSet(await api('POST', `/projects/${enc(S.playName)}/play/end`, { reason: '' }));
      location.hash = `#/play/${enc(S.playName)}/life`;
    });
  },
  playAskRewind(n) {
    S.playDlg = { kind: 'rewind', n: Number(n) };
    render();
  },
  playAskFork(n) {
    const p = S.play;
    const taken = new Set((S.projects || []).map((x) => x.name));
    taken.add(p.name);
    const title = `${playTitleOf(p)} · 다른 길`;
    S.playDlg = { kind: 'fork', n: Number(n), title, to: playFolder(p.world, title, taken), err: '' };
    render();
  },
  playDlgClose() {
    S.playDlg = null;
    render();
  },
  async playRewind() {
    const d = S.playDlg;
    S.playDlg = null;
    await run('되감는 중', async () => {
      const v = await api('POST', `/projects/${enc(S.playName)}/play/rewind`, { n: d.n });
      playSet(v, true);
      toast(d.n === v.world_ep ? '첫 구간 전으로 되감았어요' : `${d.n}구간 직후로 되감았어요. 시간은 멈춰 있어요`);
      location.hash = `#/play/${enc(S.playName)}`;
    });
  },
  async playCopyLife() {
    try {
      await navigator.clipboard.writeText(playLifeText(S.playLife));
      toast('생애 기록을 글로 복사했어요');
    } catch {
      toast('복사하지 못했어요. 브라우저가 클립보드를 막았어요', true);
    }
  },
  playNwGenre(id) {
    playReadNew();
    const g = S.playNew.nwGenres;
    S.playNew.nwGenres = g.includes(id) ? g.filter((x) => x !== id) : [...g, id];
    render();
  },
  async playMakeWorld() {
    playReadNew();
    const f = S.playNew;
    f.nwErr = '';
    const name = (f.nwName || folderOf(f.nwLine.slice(0, 20))).trim();
    try {
      const j = await api('POST', '/play/worlds', { name, genres: f.nwGenres, logline: f.nwLine, adult: f.nwAdult });
      f.nwJob = j.id;
    } catch (e) {
      f.nwErr = e.message;
      return render();
    }
    render();
    playWatchJob(null, (j) => {
      f.nwJob = null;
      if (j.status !== 'done') { f.nwErr = j.status === 'error' ? `세계를 만들지 못했어요: ${j.error}` : ''; if (S.route[1] === 'new') render(); return; }
      f.newWorld = false;
      S.playNew = { ...playNewForm(name) };
      if (S.route[0] === 'play' && S.route[1] === 'new') location.hash = `#/play/new/${enc(name)}`;
    }, f.nwJob);
  },
  playRoll(arg) {
    playReadNew();
    playRoll(arg).then(() => render());
  },
  playSketch() {
    playReadNew();
    playSketchStart();
  },
  async playBegin() {
    playReadNew();
    const f = S.playNew;
    const who = playWho(f);
    const body = { to: f.toEdited ? f.to : playFolder(f.world, f.title || `${who}의 삶`, new Set((S.projects || []).map((x) => x.name))),
      title: f.title || (who ? `${who}의 삶` : ''), person: f.person, unit: f.unit, auto_decide: f.auto,
      end_days: f.until === 'days' ? Number(f.days) || 0 : 0, end_decisions: f.until === 'decisions' ? Number(f.decisions) || 0 : 0 };
    if (f.mode === 'char') body.player = f.char;
    else { body.birth = f.card.birth; body.sketch = f.sketch; }
    f.err = '';
    await run('플레이를 여는 중', async () => {
      try {
        const r = await api('POST', `/projects/${enc(f.world)}/play/start`, body);
        S.playAutoRun = true;
        S.playNew = null;
        location.hash = `#/play/${enc(r.name)}`;
      } catch (e) {
        f.err = e.message;
        render();
      }
    });
  },
});

// 새 플레이 폼: 라디오 · 칸을 고르면 그 값으로 다시 그린다 (세계를 바꾸면 그 세계 주소로)
document.addEventListener('change', (e) => {
  if (S.route[0] !== 'play') return;
  const el = e.target;
  if (el.id === 'play-auto') {
    const on = el.checked;
    api('PUT', `/projects/${enc(S.playName)}/play/settings`, { auto_decide: on }).then((v) => { playSet(v); playDraw(); }).catch(showError);
    return;
  }
  if (el.name === 'play-speed') {
    S.playClock = playClock(S.playClock, { type: 'speed', speed: Number(el.value) });
    try { localStorage.setItem('canon.playSpeed', String(S.playClock.speed)); } catch { /* 저장 못 하면 이번 화면에서만 */ }
    playDraw();
    return;
  }
  const f = S.playNew;
  if (!f || S.route[1] !== 'new') return;
  playReadNew();
  if (el.name === 'play-world') {
    if (!el.value) { f.newWorld = true; render(); return; }
    location.hash = `#/play/new/${enc(el.value)}`;
    return;
  }
  if (el.name === 'play-mode') {
    f.mode = el.value;
    if (f.mode === 'random' && !f.card) { playRoll().then(() => render()); return; }
  }
  if (el.name === 'play-char') f.char = el.value;
  if (el.name === 'play-person') f.person = el.value;
  if (el.name === 'play-until') f.until = el.value;
  render();
});

// 끼어들기 칸에 적기 시작하면 시간이 멈춘다. 적던 글은 다시 그려도 남는다
document.addEventListener('input', (e) => {
  if (S.route[0] !== 'play' || e.target.id !== 'play-free') return;
  S.playDraft = e.target.value;
  if (S.playClock && S.playClock.run && playPhase(S.playClock, playV()) !== 'decide') {
    S.playClock = playClock(S.playClock, { type: 'pause' });
    playPaintLive();
  }
});

// 끼어들기 칸을 펼치면 멈추고 입력칸으로
document.addEventListener('toggle', (e) => {
  if (S.route[0] !== 'play' || !e.target.classList || !e.target.classList.contains('pinterrupt') || !e.target.open) return;
  S.playClock = playClock(S.playClock, { type: 'pause' });
  const box = $('#play-free');
  if (box) box.focus();
  playPaintLive();
}, true);

// 다르게 해 보기 칸의 '사본 만들기'
document.addEventListener('submit', async (e) => {
  if (!e.target.matches || !e.target.matches('[data-play-fork]')) return;
  e.preventDefault();
  const d = S.playDlg;
  const to = $('#play-fork-to').value.trim();
  const title = $('#play-fork-title').value.trim();
  try {
    const r = await api('POST', `/projects/${enc(S.playName)}/play/fork`, { n: d.n, to, title });
    S.playDlg = null;
    toast(`'${title || r.name}' 사본을 만들었어요. 그 사본으로 옮겨요`);
    S.playName = null;
    location.hash = `#/play/${enc(r.name)}`;
  } catch (err) {
    S.playDlg = { ...d, to, title, err: err.message };
    render();
  }
});

// 창을 가리거나 다른 탭으로 가면 멈춘다
document.addEventListener('visibilitychange', () => {
  if (document.hidden && S.route[0] === 'play' && S.playClock && S.playClock.run) {
    S.playClock = playClock(S.playClock, { type: 'pause' });
    playDraw();
  }
});

// 키: 스페이스 흐르기 · 멈추기, 1~9 선택지(결정 대기 중), − + 배속, N 다음 결정까지, I 끼어들기. 자동 결정을 세는 중이면 아무 키나 기다리기
document.addEventListener('keydown', (e) => {
  if (S.route[0] !== 'play' || !S.play || S.route[2] || S.route[1] === 'new' || !S.playClock || e.defaultPrevented) return;
  if (document.querySelector('dialog[open]')) return;
  if (isTyping()) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && e.target.id === 'play-free') { e.preventDefault(); actions.playFree(); }
    return;
  }
  if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
  const v = playV();
  const ph = playPhase(S.playClock, v);
  const digit = /^(Digit|Numpad)([1-9])$/.exec(e.code);
  if (ph === 'decide' && digit) {
    const i = Number(digit[2]);
    if (S.play.turns[S.play.turns.length - 1].choices.length >= i) { e.preventDefault(); actions.playChoose(i); }
    return;
  }
  if (S.playClock.auto != null) {  // 자동 결정을 세는 중: 아무 키나 누르면 기다린다 (숫자 키는 위에서 그 선택지를 고른다)
    if (e.code === 'Space') e.preventDefault();
    S.playClock = playClock(S.playClock, { type: 'hold' }, v);
    playDraw();
    return;
  }
  const onControl = e.target.closest && e.target.closest('button, a, summary, input, select, textarea, [role="radio"]');
  if (e.code === 'Space' && !onControl) { e.preventDefault(); actions.playToggle(); return; }
  if (onControl && e.code === 'Space') return;
  if (e.code === 'Minus' || e.code === 'NumpadSubtract') { S.playClock = playClock(S.playClock, { type: 'slower' }); playDraw(); return; }
  if (e.code === 'Equal' || e.code === 'NumpadAdd') { S.playClock = playClock(S.playClock, { type: 'faster' }); playDraw(); return; }
  if (e.code === 'KeyN' && ph !== 'decide') { actions.playRush(); return; }
  if (e.code === 'KeyI' && !S.play.ending) {
    e.preventDefault();
    S.playClock = playClock(S.playClock, { type: 'pause' });
    const d = $('.pinterrupt');
    if (d) d.open = true;
    const box = $('#play-free');
    if (box) box.focus();
    playPaintLive();
  }
});

/* Canon 웹 UI. 빌드 없이 쓰는 단일 파일 SPA.
   화면은 문자열 템플릿으로 그리고, 입력은 data-bind 경로로 S.project 에 바로 반영한다.
   AI 호출이나 저장이 끝나면 화면 전체를 다시 그린다. */
'use strict';

const S = {
  config: null,
  name: null,        // 현재 프로젝트 폴더 이름
  project: null,
  dirty: false,
  route: [],
  suggestion: null,  // 설정 도우미 제안 (반영 전)
  styleSample: '',
  libs: null,        // 문체 라이브러리 목록
  lib: null,         // 라이브러리에서 보고 있는 항목 (편집 중)
  libDirty: false,
  styleLink: null,   // 작품 문체와 라이브러리 항목의 관계
  selEp: null,       // 플롯 보드에서 고른 화
  deltas: {},        // 화별 상태 변경안 (반영 전)
  deltaBase: {},     // 변경안을 만들 때의 본문. 그 뒤에 본문을 고치면 다시 만들라고 알린다
  picks: {},         // 변경안 항목 선택 여부
  textDraft: {},     // 화별 본문 편집 중인 값
  context: null,
  promptText: null,
  briefTab: 'episode',
  briefText: null,
  mode: localStorage.getItem('canon.mode') || 'api',
  jobs: [],          // 서버에서 돌고 있거나 막 끝난 AI 작업
  jobsSeen: null,    // 화면을 연 시점에 이미 끝나 있던 작업 id (결과를 다시 적용하지 않는다)
  jobsOpen: false,   // 작업 목록 펼침
  selArc: null,      // 장편: 플롯 보드에서 고른 아크 번호 ('next' 는 다음 아크 기획)
  editArc: false,    // 장편: 아크 고치기 서랍
  selPart: null,     // 장편: 고치는 부 번호
  seriesDraft: null, // 장편: 부 구성 제안 (반영 전)
  arcDraft: null,    // 장편: 다음 아크 제안 (반영 전)
  arcForm: { length: 0, note: '' },  // 장편: 다음 아크 요청
  recapDraft: null,  // 장편: 아크·부 요약 제안 { kind, number, summary }
  namingStyles: null, // 이름 스타일 목록 (서버 naming.STYLES)
  names: {},         // 이름·지명 후보. 'c:<인물 id>' 또는 'place' → { candidates, options, ai }
  nameCheck: null,   // 출연진 이름 점검 { warnings, style, detected }
  placeKind: '',     // 지명 후보의 종류 (산, 마을, 문파…)
};

const STATUS = { draft: '플롯 초안', confirmed: '플롯 확정', written: '본문 작성됨', finalized: '반영 완료' };
const ACTS = ['기', '승', '전', '결'];

// ---------- 공통 ----------

const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const enc = encodeURIComponent;
const P = () => S.project;
const base = () => `#/p/${enc(S.name)}`;

function fmtErr(data, status) {
  const d = data && data.detail;
  if (Array.isArray(d)) return d.map((x) => `${(x.loc || []).slice(1).join('.')}: ${x.msg}`).join('\n');
  return d || `요청 실패 (${status})`;
}

async function api(method, path, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
  const r = await fetch('/api' + path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(fmtErr(data, r.status));
  return data;
}

function toast(msg, err = false) {
  const el = document.createElement('div');
  el.className = 't' + (err ? ' err' : '');
  el.textContent = msg;
  $('#toast').appendChild(el);
  while ($('#toast').children.length > 3) $('#toast').firstChild.remove();
  setTimeout(() => el.remove(), err ? 8000 : 3500);
}

// ---------- 백그라운드 AI 작업 ----------
// 오래 걸리는 AI 호출은 서버가 백그라운드로 돌리고, 화면은 1.5초마다 상태만 묻는다.
// 그동안 다른 화면으로 옮겨 다니며 계속 작업할 수 있다.

const JOB_DONE_MSG = {
  suggest: '설정 제안이 도착했습니다. 설정 도우미에서 확인하세요.',
  arc: '기승전결 구조 제안이 도착했습니다. 확인하고 저장하세요.',
  plots: '화별 플롯 초안을 만들었습니다. 확정된 화는 그대로입니다.',
  write: (j) => `${j.ep}화 본문을 저장했습니다.`,
  state: (j) => `${j.ep}화 상태 변경안이 도착했습니다.`,
  series: '부 구성 제안이 도착했습니다. 확인하고 반영하세요.',
  nextarc: '다음 아크 제안이 도착했습니다. 고친 뒤 반영하세요.',
  recap_arc: (j) => `아크 ${j.ep} 요약 제안이 도착했습니다.`,
  recap_part: (j) => `${j.ep}부 요약 제안이 도착했습니다.`,
  impact: (j) => `${j.label.replace(/^인과율: /, '')}이 끝났습니다. 인과율에서 확인하세요.`,
  storyline: '이야기 줄기 제안이 도착했습니다. 고른 화와 함께 반영하세요.',
  auto: (j) => `자동 집필: ${j.note || '멈췄습니다'}`,
};
let jobTimer = null;

function jobFor(kind, ep = null, name = S.name) {
  return S.jobs.find((j) => j.status === 'running' && j.project === name && j.kind === kind && (ep == null || j.ep === ep));
}

// 작업이 도는 동안 버튼은 진행 상황을 보여 주고 눌리지 않게 한다
function jobBtn(kind, ep, idle) {
  const j = jobFor(kind, ep);
  if (!j) return { label: idle, attr: '' };
  return { label: `${j.label} 만드는 중…${j.total > 1 ? ` ${j.done}/${j.total}` : ''}`, attr: ' disabled aria-busy="true"' };
}

function jobOwns(n) {
  const j = jobFor('plots');
  return !!j && P() && (!ep(n) || ep(n).status === 'draft');
}

async function startJob(kind, ep = null, extra = {}) {
  try {
    await saveIfDirty();
    const j = await api('POST', `/projects/${enc(S.name)}/jobs`, { kind, ep, ...extra });
    if (j.already) toast(`이미 진행 중이에요: ${j.label}`);
    else toast(`${j.label}을(를) 시작했어요. 끝나면 알려 드릴게요. 그동안 다른 작업을 해도 됩니다.`);
    S.jobs = S.jobs.filter((x) => x.id !== j.id).concat(j);
    renderJobs();
    render();
    pollJobs(true);
  } catch (e) {
    toast(e.message, true);
  }
}

async function pollJobs(soon = false) {
  clearTimeout(jobTimer);
  if (soon) { jobTimer = setTimeout(() => pollJobs(), 800); return; }
  let list;
  try { list = await api('GET', '/jobs'); } catch { list = S.jobs; }
  if (S.jobsSeen === null) S.jobsSeen = new Set(list.filter((j) => j.status !== 'running').map((j) => j.id));
  const before = new Map(S.jobs.map((j) => [j.id, j]));
  // 화면이 목록에서 지운(닫은) 작업은 다시 보이지 않게 한다
  S.jobs = list.filter((j) => !S.jobsSeen.has(j.id) || j.status === 'running');
  let redraw = false;
  for (const j of S.jobs) {
    const old = before.get(j.id);
    const progressed = !old || old.done !== j.done || old.status !== j.status;
    if (!progressed || j.project !== S.name) continue;
    if (j.kind === 'plots') await mergeEpisodes((e) => e.status === 'draft');
    if (j.kind === 'write' && j.status !== 'running') await mergeEpisodes((e) => e.plot.number === j.ep);
    if (j.kind === 'impact' && j.status === 'done') await mergeImpacts();
    if (j.kind === 'auto') await mergeEpisodes((e) => e.status !== 'draft');
    if (j.status !== 'running' && !(old && old.status !== 'running')) await finishJob(j);
    if (JOB_PAGES[j.kind].includes(S.route[2] || 'home')) redraw = true;
  }
  renderJobs();
  // 입력 중이면 화면을 다시 그리지 않는다 (글자와 커서를 잃지 않게). 데이터는 이미 반영돼 있다.
  const typing = document.activeElement && document.activeElement.matches('#app input, #app textarea, #app select');
  if (redraw && !typing) render();
  if (S.jobs.some((j) => j.status === 'running')) jobTimer = setTimeout(() => pollJobs(), 1500);
}

// 작업 결과가 보이는 화면
const JOB_PAGES = { suggest: ['setup'], arc: ['arc'], plots: ['arc', 'home', 'causal'], write: ['write', 'home', 'causal'], state: ['review'], auto: ['auto', 'home', 'write', 'causal'], impact: ['causal'], series: ['arc'], nextarc: ['arc'], recap_arc: ['arc'], recap_part: ['arc'], storyline: ['lines'] };

// 작업이 project.json 에 쓴 화만 받아 온다 (mine 이 true 인 화와 새로 생긴 화). 저장하지 않은 다른 입력은 그대로 둔다.
async function mergeEpisodes(mine) {
  if (!S.name || !P()) return;
  try {
    const fresh = await api('GET', `/projects/${enc(S.name)}`);
    if (!S.dirty) { S.project = fresh; return; }
    const local = new Map(P().episodes.map((e) => [e.plot.number, e]));
    for (const e of fresh.episodes) {
      const cur = local.get(e.plot.number);
      if (!cur || mine(cur)) local.set(e.plot.number, e);
    }
    P().episodes = [...local.keys()].sort((a, b) => a - b).map((k) => local.get(k));
  } catch { /* 다음 확인 때 다시 */ }
}

async function finishJob(j) {
  const here = j.project === S.name && P();
  if (j.status === 'error') {
    toast(`${j.label} 실패: ${j.error}`, true);
    return;
  }
  const msg = JOB_DONE_MSG[j.kind];
  toast(typeof msg === 'function' ? msg(j) : msg);
  setTimeout(() => {  // 끝난 작업은 잠시 뒤 목록에서 내린다 (실패는 직접 닫을 때까지 남긴다)
    S.jobsSeen.add(j.id);
    S.jobs = S.jobs.filter((x) => x.id !== j.id || x.status === 'running');
    renderJobs();
  }, 20000);
  if (!here) return;  // 다른 작품을 보고 있으면 결과는 작업 목록에서 열어 볼 수 있다
  applyJobResult(j);
}

function applyJobResult(j) {
  if (j.kind === 'suggest' && j.result) {
    S.suggestion = j.result;
    S.suggestion.characters.forEach((c, i) => { S.picks['sc' + i] = !P().characters.some((x) => x.id === c.id); });
    S.suggestion.relationships.forEach((r, i) => { S.picks['sr' + i] = true; });
  } else if (j.kind === 'arc' && j.result) {
    P().arc = j.result.acts;
    S.dirty = true;
  } else if (j.kind === 'write') {
    delete S.textDraft[j.ep];
    delete S.deltas[j.ep];
  } else if (j.kind === 'state' && j.result) {
    setDelta(j.ep, j.result);
  } else if (j.kind === 'series' && j.result) {
    S.seriesDraft = j.result;
  } else if (j.kind === 'nextarc' && j.result) {
    S.arcDraft = j.result;
    S.selArc = 'next';
  } else if (j.kind.startsWith('recap_') && j.result) {
    const kind = j.kind.slice(6);
    S.recapDraft = { kind, number: j.ep, summary: j.result.summary };
    if (kind === 'arc') S.selArc = j.ep;
    else S.selPart = j.ep;
  } else if (['convert', 'rebuild', 'rework'].includes(j.kind) && j.result) {
    convertResult(j);
  } else if (j.kind === 'storyline' && j.result) {
    S.lineDraft = { ...j.result, picks: {} };
  } else if (['hook', 'openings', 'opening_drafts'].includes(j.kind)) {
    openingJobResult(j);
  }
  j.applied = true;
}

const JOB_LINK = {
  suggest: (j) => `#/p/${enc(j.project)}/setup`,
  arc: (j) => `#/p/${enc(j.project)}/arc`,
  plots: (j) => `#/p/${enc(j.project)}/arc`,
  write: (j) => `#/p/${enc(j.project)}/write/${j.ep}`,
  state: (j) => `#/p/${enc(j.project)}/review/${j.ep}`,
  series: (j) => `#/p/${enc(j.project)}/arc`,
  nextarc: (j) => `#/p/${enc(j.project)}/arc`,
  recap_arc: (j) => `#/p/${enc(j.project)}/arc`,
  recap_part: (j) => `#/p/${enc(j.project)}/arc`,
  impact: (j) => `#/p/${enc(j.project)}/causal${j.result ? '/' + enc(j.result.element) : ''}`,
  storyline: (j) => `#/p/${enc(j.project)}/lines`,
  auto: (j) => `#/p/${enc(j.project)}/auto`,
};

function renderJobs() {
  let box = $('#jobs');
  if (!box) {
    box = document.createElement('div');
    box.id = 'jobs';
    box.setAttribute('role', 'status');
    box.setAttribute('aria-live', 'polite');
    document.body.appendChild(box);
  }
  if (!S.jobs.length) { box.innerHTML = ''; box.hidden = true; return; }
  box.hidden = false;
  const running = S.jobs.filter((j) => j.status === 'running');
  const head = running.length ? `AI 작업 ${running.length}개 진행 중` : 'AI 작업 끝남';
  const items = S.jobs.map((j) => {
    const pct = j.total > 1 ? ` ${j.done}/${j.total}` : '';
    const state = j.status === 'running' ? `<span class="spinner sm" aria-hidden="true"></span>` : j.status === 'done' ? '<span class="ok">완료</span>' : '<span class="bad">실패</span>';
    const other = j.project !== S.name ? ` <span class="small">· ${esc(j.project)}</span>` : '';
    const sub = j.status === 'error' ? j.error : j.note;
    const open = j.status !== 'running' && j.kind in JOB_LINK ? `<a href="${JOB_LINK[j.kind](j)}" data-job-open="${j.id}">열기</a>` : '';
    return `<li>${state}<div class="jl"><strong>${esc(j.label)}${pct}</strong>${other}${sub ? `<div class="small">${esc(sub)}</div>` : ''}</div>${open}${j.status !== 'running' ? `<button type="button" class="x" data-job-dismiss="${j.id}" aria-label="목록에서 지우기">✕</button>` : ''}</li>`;
  }).join('');
  box.innerHTML = `<button type="button" class="jobs-head" aria-expanded="${S.jobsOpen || !running.length}" data-jobs-toggle>${running.length ? '<span class="spinner sm" aria-hidden="true"></span>' : ''}${head}</button>${S.jobsOpen || !running.length ? `<ul>${items}</ul>` : ''}`;
}

document.addEventListener('click', (e) => {
  const t = e.target.closest('[data-jobs-toggle], [data-job-dismiss], [data-job-open]');
  if (!t) return;
  if (t.dataset.jobsToggle !== undefined) {
    S.jobsOpen = !S.jobsOpen;
  } else if (t.dataset.jobDismiss) {
    S.jobsSeen.add(t.dataset.jobDismiss);
    S.jobs = S.jobs.filter((j) => j.id !== t.dataset.jobDismiss);
  } else if (t.dataset.jobOpen) {
    // 다른 작품에서 끝난 결과는 그 작품을 연 뒤에 적용한다
    const j = S.jobs.find((x) => x.id === t.dataset.jobOpen);
    if (j) S.pendingJob = j;
  }
  renderJobs();
});

/** 버튼 동작 공통 처리: 진행 표시, 오류 알림, 다시 그리기 */
async function run(label, fn) {
  $('#busy-text').textContent = label;
  $('#busy').hidden = false;
  try {
    await fn();
  } catch (e) {
    toast(e.message, true);
  } finally {
    $('#busy').hidden = true;
    render();
  }
}

function getPath(obj, path) {
  return path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

function setPath(obj, path, value) {
  const keys = path.split('.');
  const last = keys.pop();
  const target = keys.reduce((o, k) => o[k], obj);
  target[last] = value;
}

function epIndex(n) {
  return P().episodes.findIndex((e) => e.plot.number === n);
}

function ep(n) {
  return P().episodes.find((e) => e.plot.number === n);
}

function charName(id) {
  const c = P().characters.find((x) => x.id === id);
  return c ? c.name : id;
}

/** 지금 작업해야 할 화: 반영이 끝나지 않은 첫 화 */
function currentEp() {
  const eps = P().episodes;
  if (!eps.length) return 1;
  const open = eps.find((e) => e.status !== 'finalized');
  return open ? open.plot.number : eps[eps.length - 1].plot.number;
}

const serial = () => P().meta.form === 'serial';

/** 화마다 소속 구간을 정하는 기승전결 목록. 단편은 작품 전체 구조, 장편은 기획한 아크들의 구간 (schema.Project.beats 와 같음) */
function beats() {
  const p = P();
  if (!serial()) return p.arc;
  return [...p.story_arcs].sort((a, b) => a.start_ep - b.start_ep).flatMap((s) => s.acts);
}

/** 화를 함께 쓰는 구간(4화보다 짧은 작품)을 한 묶음으로. web._plot_ranges 와 같은 규칙 */
function actGroups(acts) {
  const out = [];
  for (const a of acts) {
    const g = out[out.length - 1];
    if (g && a.start_ep <= g.end) { g.names.push(a.name); g.end = Math.max(g.end, a.end_ep); }
    else out.push({ names: [a.name], start: a.start_ep, end: a.end_ep });
  }
  return out;
}

function actOf(n) {
  return beats().find((a) => a.start_ep <= n && n <= a.end_ep);
}

function arcOf(n) {
  return P().story_arcs.find((a) => a.start_ep <= n && n <= a.end_ep);
}

function plannedUntil() {
  return Math.max(0, ...P().story_arcs.map((a) => a.end_ep));
}

function actClass(name) {
  return 'act-' + (ACTS.indexOf(name) + 1);
}

// ---------- 입력 바인딩 ----------
// data-bind="meta.title" data-kind="text|int|list|bool"

// 반영 전 AI 제안도 같은 방식으로 고친다. 이 값들은 작품 저장(dirty)과 상관없다.
const DRAFT_ROOTS = { arcDraft: () => S.arcDraft, seriesDraft: () => S.seriesDraft, recap: () => S.recapDraft, arcForm: () => S.arcForm };

function bindRoot(name) {
  if (DRAFT_ROOTS[name]) return DRAFT_ROOTS[name]();
  return name === 'lib' ? S.lib : P();
}

function bindValue(path, kind, root) {
  const v = getPath(bindRoot(root), path);
  if (kind === 'list') return (v || []).join('\n');
  if (kind === 'tags') return (v || []).join(', ');
  return v ?? '';
}

function input(label, path, opt = {}) {
  const id = 'f-' + path.replace(/\./g, '-');
  const kind = opt.kind || (opt.type === 'number' ? 'int' : 'text');
  const val = esc(bindValue(path, kind, opt.root));
  const rootAttr = opt.root ? ` data-root="${opt.root}"` : '';
  const hint = opt.hint ? ` <span class="hint">${esc(opt.hint)}</span>` : '';
  const ro = opt.readonly ? ' readonly' : '';
  const ctrl = opt.rows || kind === 'list'
    ? `<textarea id="${id}" rows="${opt.rows || 3}" data-bind="${path}" data-kind="${kind}"${rootAttr}${ro}${opt.style ? ` style="${opt.style}"` : ''} placeholder="${esc(opt.placeholder || (kind === 'list' ? '한 줄에 하나씩' : ''))}">${val}</textarea>`
    : `<input id="${id}" type="${opt.type || 'text'}" value="${val}" data-bind="${path}" data-kind="${kind}"${rootAttr}${ro}${opt.min != null ? ` min="${opt.min}"` : ''}${opt.max != null ? ` max="${opt.max}"` : ''}${opt.list ? ` list="${opt.list}"` : ''} placeholder="${esc(opt.placeholder || '')}">`;
  return `<div class="field${opt.cls ? ' ' + opt.cls : ''}"><label for="${id}">${esc(label)}${hint}</label>${ctrl}</div>`;
}

document.addEventListener('input', (e) => {
  const el = e.target;
  const root = el.dataset.bind && bindRoot(el.dataset.root);
  if (root) {
    const kind = el.dataset.kind;
    let v = el.value;
    if (kind === 'int') v = v === '' ? 0 : parseInt(v, 10) || 0;
    if (kind === 'float') v = parseFloat(v) || 0;
    if (kind === 'list') v = v.split('\n').map((s) => s.trim()).filter(Boolean);
    if (kind === 'tags') v = splitTags(v);
    if (kind === 'bool') v = el.checked;
    setPath(root, el.dataset.bind, v);
    if (el.dataset.root === 'lib') S.libDirty = true;
    else if (!DRAFT_ROOTS[el.dataset.root]) markDirty();
    if (el.dataset.root === 'arcDraft' && el.dataset.bind === 'arc.end_ep') {  // 아크 끝 화를 바꾸면 결 구간 끝도 따라간다
      const acts = S.arcDraft.arc.acts;
      const last = acts[acts.length - 1];
      if (last && v >= last.start_ep) last.end_ep = v;
    }
    const cnt = el.id === 'f-sample' && $('#lib-sample-count');
    if (cnt) cnt.textContent = v.length.toLocaleString();
    const out = el.dataset.out && document.getElementById(el.dataset.out);
    if (out) out.textContent = v;
    if (el.dataset.bind.startsWith('meta.logline_parts.')) updateLogline();
    const rel = el.dataset.bind.match(/^relationships\.(\d+)\.(a|b)$/);
    if (rel) refreshRel(Number(rel[1]));
  }
  if (el.dataset.draft) {
    S.textDraft[el.dataset.draft] = el.value;
    const c = $('#char-count');
    if (c) c.textContent = el.value.length.toLocaleString();
    const sb = $('#save-text');
    if (sb) sb.disabled = false;
  }
  if (el.dataset.local) S[el.dataset.local] = el.value;
  if (el.dataset.deltaSummary) S.deltas[el.dataset.deltaSummary].summary = el.value;
});

document.addEventListener('change', (e) => {
  const el = e.target;
  if (el.dataset.pick) {
    S.picks[el.dataset.pick] = el.checked;
    const c = $('#pick-count');
    if (c) c.textContent = Object.values(S.picks).filter(Boolean).length;
    if (S.route[2] === 'review' && /^[ers]\d/.test(el.dataset.pick)) refreshPreview(Number(S.route[3]));
  }
  if (el.name === 'np-form') {  // 형식을 바꾸면 총 화수 기본값도 바꾼다
    const eps = $('#np-eps');
    if (eps) eps.value = el.value === 'serial' ? 300 : 12;
  }
  if (el.dataset.castEp) {
    const plot = ep(Number(el.dataset.castEp)).plot;
    const id = el.value;
    plot.characters = el.checked ? [...new Set([...plot.characters, id])] : plot.characters.filter((x) => x !== id);
    markDirty();
  }
});

// 내용 길이에 맞춰 늘어나는 입력칸
function autosize(el) {
  el.style.height = 'auto';
  el.style.height = el.scrollHeight + 2 + 'px';
}
document.addEventListener('input', (e) => {
  if (e.target.matches && e.target.matches('textarea[data-autogrow]')) autosize(e.target);
});
// 구간 범위나 목표를 고치면 보드도 다시 그린다 (입력이 끝났을 때만)
document.addEventListener('change', (e) => {
  const bind = e.target.dataset && e.target.dataset.bind;
  if (bind && /^(arc|story_arcs|parts)\./.test(bind) && S.route[2] === 'arc') render();
  if (S.route[2] !== 'setup' || !bind) return;
  if (bind === 'world.name_style') {  // 스타일을 바꾸면 이전 후보는 버리고 다시 점검한다
    S.names = {};
    S.placeKind = '';
    checkNames().then(render);
  } else if (/^characters\.\d+\.(name|age|gender)$/.test(bind) || bind === 'world.era' || bind === 'world.setting') {
    checkNames();
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && (S.selEp || S.selAct != null || S.editArc || S.selPart != null) && S.route[2] === 'arc' && !e.isComposing) {
    actions.closePanel();
    return;
  }
  if (e.key === 'Enter' && e.target.id === 'genre-custom' && !e.isComposing) {
    e.preventDefault();
    actions.addCustomGenre();
  }
});

function markDirty() {
  if (!S.dirty) {
    S.dirty = true;
    renderSavebar();
  }
}

function renderSavebar() {
  let bar = $('#savebar');
  if (!S.dirty) {
    if (bar) bar.remove();
    return;
  }
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'savebar';
    bar.className = 'savebar';
    bar.innerHTML = '<span>저장하지 않은 변경이 있어요</span><button class="btn small" data-action="revert">되돌리기</button><button class="btn small primary" data-action="save">저장</button>';
    document.body.appendChild(bar);
  }
}

async function save() {
  // 끝난 작업 중 결과를 이미 받아 온 것을 알려야 서버가 그 화를 덮어써도 된다고 안다
  const merged = [...S.jobs.filter((j) => j.status !== 'running').map((j) => j.id), ...(S.jobsSeen || [])].join(',');
  S.project = await api('PUT', `/projects/${enc(S.name)}?merged=${enc(merged)}`, P());
  S.dirty = false;
  if (S.route[2] === 'style') { await loadStyleLink(); await learnLoad(); }
  if (S.route[2] === 'causal') await causalLoad();
}

async function loadStyleLink() {
  S.styleLink = await api('GET', `/projects/${enc(S.name)}/style/link`).catch(() => null);
}

async function saveIfDirty() {
  if (S.dirty) await save();
}

// ---------- 동작 ----------

const actions = {
  async save() {
    await run('저장 중', async () => { await save(); toast('저장했습니다'); });
  },
  async revert() {
    await run('불러오는 중', async () => { await loadProject(S.name); });
  },
  async createProject() {
    const name = $('#np-name').value.trim();
    if (!name) return toast('프로젝트 이름을 입력하세요', true);
    const meta = {
      title: $('#np-title').value.trim() || name,
      genres: [...S.newMeta.genres],
      target_episodes: parseInt($('#np-eps').value, 10) || 16,
      adult: $('#np-adult').checked,
      form: $('#np-serial').checked ? 'serial' : 'short',
    };
    const styleId = $('#np-style') ? $('#np-style').value : '';
    await run('만드는 중', async () => {
      await api('POST', '/projects', { name, meta, style_id: styleId });
      S.newMeta = null;
      location.hash = `#/p/${enc(name)}/setup`;
    });
  },

  // 설정 도우미
  async suggest() {
    await startJob('suggest');
  },
  dropSuggestion() {
    S.suggestion = null;
    render();
  },
  async applySuggestion() {
    const s = structuredClone(S.suggestion);
    s.characters = s.characters.filter((_, i) => S.picks['sc' + i]);
    s.relationships = s.relationships.filter((_, i) => S.picks['sr' + i]);
    await run('반영하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/suggest/apply`, s);
      S.suggestion = null;
      toast('빈칸을 채웠습니다. 기존 입력은 그대로입니다.');
    });
  },
  toggleGenre(id) {
    const m = genreTarget();
    m.genres = m.genres.includes(id) ? m.genres.filter((g) => g !== id) : [...m.genres, id];
    syncGenre();
  },
  addCustomGenre() {
    const el = $('#genre-custom');
    const v = el.value.trim();
    if (!v) return;
    const hit = (S.genres || []).find((g) => g.name === v || g.id === v);
    const id = hit ? hit.id : v;
    if (!genreTarget().genres.includes(id)) genreTarget().genres.push(id);
    syncGenre();
    $('#genre-custom').focus();
  },
  // 이름 · 지명 후보 (코드가 무작위로 뽑고, AI 추천은 '이름·지명' 단계 모델이 그중에서 고른다)
  async nameCandidates(id) { await loadNames('c:' + id, { character: id }, false); },
  async nameAI(id) { await loadNames('c:' + id, { character: id }, true); },
  async placeCandidates() { await loadNames('place', { place_kind: S.placeKind || '' }, false); },
  async placeAI() { await loadNames('place', { place_kind: S.placeKind || '' }, true); },
  useName(arg) {
    const [id, ...rest] = arg.split('|');
    const c = P().characters.find((x) => x.id === id);
    if (!c) return;
    c.name = rest.join('|');
    delete S.names['c:' + id];
    markDirty();
    render();
    checkNames();
  },
  addPlace(name) {
    const w = P().world;
    if (!w.locations.includes(name)) w.locations.push(name);
    S.names.place.candidates = (S.names.place.candidates || []).filter((x) => x.name !== name);
    S.names.place.options = (S.names.place.options || []).filter((x) => x.name !== name);
    markDirty();
    render();
  },
  closeNames(key) {
    delete S.names[key];
    render();
  },
  async checkNames() { await checkNames(true); },

  addCharacter() {
    // id 는 관계와 플롯이 인물을 찾는 열쇠라 자동으로 짓고 화면에서는 접어 둔다
    const cs = P().characters;
    const ids = new Set(cs.map((c) => c.id));
    let id = ids.has('hero') ? '' : 'hero';
    for (let n = cs.length + 1; !id; n++) if (!ids.has('char' + n)) id = 'char' + n;
    cs.push({ id, name: '', role: id === 'hero' ? '주인공' : '조연', age: '', gender: '', appearance: '', personality: '', background: '', goal: '', wound: '', speech_style: '', secrets: [], arc: '' });
    markDirty();
    render();
  },
  removeCharacter(i) {
    const c = P().characters[i];
    if (!confirm(`${c.name || c.id} 인물을 지울까요? 관계도 함께 지워집니다.`)) return;
    P().characters.splice(i, 1);
    P().relationships = P().relationships.filter((r) => r.a !== c.id && r.b !== c.id);
    P().states = P().states.filter((s) => s.character_id !== c.id);
    markDirty();
    render();
  },
  addRelationship() {
    const cs = P().characters;
    if (cs.length < 2) return toast('인물이 두 명 이상 있어야 합니다', true);
    P().relationships.push({ a: cs[0].id, b: cs[1].id, type: '', description: '', affinity: 0, tension: 0, goal_conflict: 0, a_view: [], b_view: [] });
    markDirty();
    render();
  },
  removeRelationship(i) {
    P().relationships.splice(i, 1);
    markDirty();
    render();
  },
  fillSlot(arg) {
    const [k, ...rest] = arg.split('|');
    P().meta.logline_parts[k] = rest.join('|');
    const el = $(`#f-meta-logline_parts-${k}`);
    if (el) el.value = P().meta.logline_parts[k];
    markDirty();
    updateLogline();
  },
  useExample(i) {
    const parts = P().meta.logline_parts;
    if (Object.values(parts).some((v) => v.trim()) && !confirm('지금 쓴 다섯 칸을 이 예시로 바꿀까요?')) return;
    Object.assign(parts, loglineExamples()[i]);
    LOGLINE_SLOTS.forEach(([k]) => { const el = $(`#f-meta-logline_parts-${k}`); if (el) el.value = parts[k]; });
    markDirty();
    updateLogline();
  },
  setDial(arg) {
    const [k, v] = arg.split('|');
    const m = P().meta;
    m.tone_dials[k] = m.tone_dials[k] === Number(v) ? 0 : Number(v);
    m.tone = toneText(m.tone_dials);
    markDirty();
    $('#tone-box').outerHTML = toneBox();
  },
  setRelType(arg) {
    const [i, type] = arg.split('|');
    P().relationships[i].type = type;
    markDirty();
    refreshRel(Number(i));
  },
  toggleView(arg) {
    const [i, side, word] = arg.split('|');
    const r = P().relationships[i];
    r[side] = r[side].includes(word) ? r[side].filter((w) => w !== word) : [...r[side], word];
    markDirty();
    refreshRel(Number(i));
  },
  setConflict(arg) {
    const [i, v] = arg.split('|');
    P().relationships[i].goal_conflict = Number(v);
    markDirty();
    refreshRel(Number(i));
  },

  // 문체
  async analyzeStyle() {
    await run('문체를 분석하는 중… (최대 1분)', async () => {
      await saveIfDirty();
      const prof = await api('POST', `/projects/${enc(S.name)}/style`, { text: S.styleSample });
      P().style = prof;
      P().style_baseline = await api('POST', '/metrics', { text: S.styleSample });  // stats 가 원문 전체와 비교하도록
      P().style_id = '';  // 새로 분석한 문체는 라이브러리 항목과 연결을 끊는다
      P().style_version = 0;
      S.dirty = true;
      toast('분석 결과를 불러왔습니다. 확인하고 저장하세요.');
    });
  },
  addPassage() {
    P().style.sample_passages.push('');
    markDirty();
    render();
  },
  removePassage(i) {
    P().style.sample_passages.splice(i, 1);
    markDirty();
    render();
  },
  addMarker() {
    P().style.markers.push({ text: '', note: '', per_1k: 0 });
    markDirty();
    render();
  },
  removeMarker(i) {
    P().style.markers.splice(i, 1);
    markDirty();
    render();
  },
  async useLibStyle() {
    const id = $('#style-pick').value;
    if (!id) return toast('적용할 문체를 고르세요', true);
    const e = (S.libs || []).find((x) => x.id === id);
    if (!confirm(`'${e ? e.name : id}' 문체를 이 작품에 적용할까요? 지금 작품의 스타일 프로필은 바뀝니다.`)) return;
    await run('적용하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/style/apply`, { style_id: id });
      await loadStyleLink();
      toast('라이브러리 문체를 적용했습니다');
    });
  },
  async keepStyle() {
    const name = prompt('라이브러리에 저장할 문체 이름', `${P().meta.title || S.name} 문체`);
    if (name === null) return;
    await run('라이브러리에 저장하는 중', async () => {
      await saveIfDirty();
      const r = await api('POST', `/projects/${enc(S.name)}/style/library`, { name: name.trim(), sample: S.styleSample });
      S.project = r.project;
      S.libs = await api('GET', '/styles');
      await loadStyleLink();
      toast(`라이브러리에 '${r.entry.name}' 로 저장했습니다`);
    });
  },
  async pushStyle() {
    const l = S.styleLink || {};
    const users = ((S.libs || []).find((x) => x.id === l.id) || {}).used_by || [];
    const others = users.filter((n) => n !== S.name);
    const warn = others.length ? `\n다른 작품(${others.join(', ')})은 다시 적용하기 전까지 바뀌지 않습니다.` : '';
    const note = prompt(`이 작품의 문체를 라이브러리 '${l.name}' 의 새 버전으로 올립니다. 예전 버전은 남아 있어 되돌릴 수 있어요.${warn}\n\n버전 메모 (비워도 됩니다)`, '');
    if (note === null) return;
    await run('라이브러리에 올리는 중', async () => {
      await saveIfDirty();
      const r = await api('POST', `/projects/${enc(S.name)}/style/library`, { update: true, note: note.trim() });
      S.project = r.project;
      S.libs = await api('GET', '/styles');
      await loadStyleLink();
      toast(`라이브러리 '${r.entry.name}' 을 ${r.entry.version}번 버전으로 올렸습니다`);
    });
  },
  async pullStyle() {
    const l = S.styleLink || {};
    if (!confirm(`이 작품의 문체를 라이브러리의 '${l.name}' 으로 되돌릴까요? 작품에서 고친 내용은 사라집니다.`)) return;
    await run('적용하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/style/apply`, { style_id: l.id });
      await loadStyleLink();
    });
  },

  // 문체 라이브러리
  async libAnalyze() {
    if ((S.lib.sample || '').trim().length < 200) return toast('원문을 200자 이상 넣어 주세요', true);
    const has = S.lib.profile.narration_pov || S.lib.profile.sample_passages.length;
    if (has && !confirm('분석 결과로 지금 프로필을 바꿀까요? 저장 전까지는 되돌릴 수 있어요.')) return;
    await run('문체를 분석하는 중… (최대 1분)', async () => {
      S.lib.profile = await api('POST', '/styles/analyze', { text: S.lib.sample });
      S.libDirty = true;
      toast('분석 결과를 불러왔습니다. 확인하고 저장하세요.');
    });
  },
  async libSave() {
    if (!S.lib.name.trim()) return toast('문체 이름을 입력하세요', true);
    const body = { name: S.lib.name, source: S.lib.source, notes: S.lib.notes, sample: S.lib.sample, profile: S.lib.profile, note: S.libNote || '' };
    await run('저장 중', async () => {
      const isNew = !S.lib.id;
      S.lib = isNew ? await api('POST', '/styles', body) : await api('PUT', `/styles/${S.lib.id}`, body);
      S.lib.used_by = S.lib.used_by || [];
      S.libDirty = false;
      S.libNote = '';
      await libVersionsLoad();
      toast(isNew ? '라이브러리에 저장했습니다' : `저장했습니다 (지금 ${S.lib.version}번 버전)`);
      if (isNew) location.hash = `#/styles/${S.lib.id}`;
    });
  },
  async libRevert() {
    await run('불러오는 중', async () => {
      S.lib = await api('GET', `/styles/${S.lib.id}`);
      S.libDirty = false;
    });
  },
  async libDuplicate(id) {
    if (S.libDirty && !confirm('저장하지 않은 변경은 사본에 들어가지 않아요. 계속할까요?')) return;
    await run('복제하는 중', async () => {
      const e = await api('POST', `/styles/${id}/duplicate`);
      S.libDirty = false;
      toast(`'${e.name}' 을 만들었습니다`);
      location.hash = `#/styles/${e.id}`;
    });
  },
  async libDelete(id) {
    const e = (S.libs || []).find((x) => x.id === id) || S.lib || {};
    const used = e.used_by || [];
    const note = used.length ? `\n이 문체를 쓰는 작품(${used.join(', ')})은 복사해 둔 문체를 그대로 씁니다.` : '';
    if (!confirm(`'${e.name}' 문체를 라이브러리에서 지울까요? 되돌릴 수 없어요.${note}`)) return;
    await run('지우는 중', async () => {
      await api('DELETE', `/styles/${id}`);
      S.libDirty = false;
      S.libs = await api('GET', '/styles');
      toast('지웠습니다');
      if (S.route[0] === 'styles' && S.route[1]) location.hash = '#/styles';
    });
  },
  async libApplyTo() {
    const name = $('#lib-target').value;
    if (!name) return toast('적용할 작품을 고르세요', true);
    if (S.libDirty) return toast('먼저 저장하세요. 저장된 문체가 작품에 복사됩니다.', true);
    if (!confirm(`'${S.lib.name}' 문체를 '${name}' 작품에 적용할까요? 그 작품의 스타일 프로필은 바뀝니다.`)) return;
    await run('적용하는 중', async () => {
      await api('POST', `/projects/${enc(name)}/style/apply`, { style_id: S.lib.id });
      S.lib = await api('GET', `/styles/${S.lib.id}`);
      toast(`'${name}' 에 적용했습니다`);
    });
  },
  libAddPassage() {
    S.lib.profile.sample_passages.push('');
    S.libDirty = true;
    render();
  },
  libRemovePassage(i) {
    S.lib.profile.sample_passages.splice(i, 1);
    S.libDirty = true;
    render();
  },
  libAddMarker() {
    S.lib.profile.markers.push({ text: '', note: '', per_1k: 0 });
    S.libDirty = true;
    render();
  },
  libRemoveMarker(i) {
    S.lib.profile.markers.splice(i, 1);
    S.libDirty = true;
    render();
  },

  // 구조와 플롯
  async planArc() {
    if (P().arc.length && !confirm('지금 구조를 AI 제안으로 바꿀까요? 저장 전까지는 되돌릴 수 있어요.')) return;
    await startJob('arc');
  },
  async draftPlots() {
    await startJob('plots');
  },
  selectEp(n) {
    S.selEp = Number(n);
    S.selAct = null;
    S.editArc = false;
    S.selPart = null;
    render();
  },
  selectAct(i) {
    S.selAct = Number(i);
    S.selEp = null;
    S.editArc = false;
    S.selPart = null;
    render();
  },
  closePanel() {
    S.selEp = null;
    S.selAct = null;
    S.editArc = false;
    S.selPart = null;
    render();
  },
  async confirmEp(n) {
    await run('확정하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/confirm`);
    });
  },
  async unconfirmEp(n) {
    await run('되돌리는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/unconfirm`);
    });
  },
  async confirmAll(arc) {
    const a = arc ? P().story_arcs.find((x) => x.number === Number(arc)) : null;
    const drafts = P().episodes.filter((e) => e.status === 'draft' && (!a || (e.plot.number >= a.start_ep && e.plot.number <= a.end_ep)));
    if (!drafts.length) return toast('확정할 초안이 없습니다');
    if (!confirm(`초안 ${drafts.length}화를 모두 확정할까요?`)) return;
    await run('확정하는 중', async () => {
      await saveIfDirty();
      for (const e of drafts) S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${e.plot.number}/confirm`);
    });
  },

  // 장편: 부 · 아크
  async planSeries() {
    if (P().parts.length && !confirm('지금 부 구성을 AI 제안으로 바꿀까요? 반영 전에 확인할 수 있어요.')) return;
    await startJob('series');
  },
  dropSeries() {
    S.seriesDraft = null;
    render();
  },
  async applySeries() {
    await run('반영하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/series/apply`, S.seriesDraft);
      S.seriesDraft = null;
      toast('부 구성을 반영했어요. 이제 첫 아크를 기획하세요.');
    });
  },
  selectArc(n) {
    S.selArc = n === 'next' ? 'next' : Number(n);
    S.selEp = null;
    S.selAct = null;
    S.editArc = false;
    S.selPart = null;
    render();
  },
  editArc() {
    S.editArc = true;
    S.selEp = null;
    S.selAct = null;
    S.selPart = null;
    render();
  },
  selectPart(n) {
    S.selPart = Number(n);
    S.selEp = null;
    S.selAct = null;
    S.editArc = false;
    render();
  },
  async planNextArc() {
    await startJob('nextarc', null, { length: Number(S.arcForm.length) || 0, note: S.arcForm.note || '' });
  },
  dropArc() {
    S.arcDraft = null;
    render();
  },
  async applyArc() {
    await run('반영하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/arcs/apply`, S.arcDraft);
      S.selArc = S.arcDraft.arc.number;
      S.arcDraft = null;
      S.arcForm = { length: 0, note: '' };
      toast('아크를 반영했어요. 화별 플롯 초안을 만드세요.');
    });
  },
  async removeLastArc() {
    if (!confirm('마지막 아크와 그 아크의 플롯 초안을 지울까요? 다시 기획할 수 있어요.')) return;
    await run('지우는 중', async () => {
      await saveIfDirty();
      S.project = await api('DELETE', `/projects/${enc(S.name)}/arcs/last`);
      S.selArc = 'next';
    });
  },
  async draftArcPlots(n) {
    await startJob('plots', Number(n));
  },
  async recapArc(n) {
    await startJob('recap_arc', Number(n));
  },
  async recapPart(n) {
    await startJob('recap_part', Number(n));
  },
  dropRecap() {
    S.recapDraft = null;
    render();
  },
  async applyRecap() {
    const r = S.recapDraft;
    await run('저장하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/recap/${r.kind}/${r.number}`, { summary: r.summary });
      S.recapDraft = null;
      toast('요약을 저장했어요. 앞으로 이 구간 대신 요약이 프롬프트에 들어갑니다.');
    });
  },

  // 집필
  setMode(m) {
    S.mode = m;
    localStorage.setItem('canon.mode', m);
    render();
  },
  async writeEp(n) {
    if (ep(n).text && !confirm(`${n}화 본문을 새로 생성할까요? 지금 본문은 사라집니다.`)) return;
    await startJob('write', n);
  },
  async saveText(n) {
    await run('본문 저장 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/episodes/${n}/text`, { text: S.textDraft[n] ?? ep(n).text });
      delete S.textDraft[n];  // 만들어 둔 상태 변경안은 남기고, 본문이 바뀌었다고 알린다 (passageNotes)
      toast('본문을 저장했습니다');
    });
  },
  startManual(n) {
    S.textDraft[n] = '';
    render();
  },
  gotoPlot(n) {
    S.selEp = Number(n);
    location.hash = `${base()}/arc`;
  },
  async togglePrompt(n) {
    if (S.promptText) {
      S.promptText = null;
      return render();
    }
    await run('불러오는 중', async () => {
      const r = await api('GET', `/projects/${enc(S.name)}/episodes/${n}/prompt`);
      S.promptText = `[시스템]\n${r.system}\n\n[프롬프트]\n${r.prompt}`;
    });
  },

  // 상태 변경안
  async extractState(n) {
    if (S.textDraft[n] !== undefined) {
      try {
        S.project = await api('PUT', `/projects/${enc(S.name)}/episodes/${n}/text`, { text: S.textDraft[n] });
        delete S.textDraft[n];
      } catch (e) {
        return toast(e.message, true);
      }
    }
    await startJob('state', n);
  },
  async applyDelta(n) {
    const out = pickedDelta(n);
    await run('반영하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/apply`, out);
      delete S.deltas[n];
      toast(`${n}화를 마쳤습니다`);
      const r = S.auto && S.auto.run;
      // 자동 집필이 이 화에서 검토를 기다리고 있었으면 자동 집필 화면으로 돌아가 이어 가게 한다
      location.hash = r && r.status === 'review' && r.ep === n ? `${base()}/auto` : base();
    });
  },
  async toggleNumbers(v) {
    const show = v === 'numbers';
    P().settings.show_numbers = show;
    render();
    try {
      S.project = await api('PUT', `/projects/${enc(S.name)}/view`, { show_numbers: show });
    } catch (e) {
      toast(e.message, true);
    }
  },
  dropDelta(n) {
    if (!confirm('이 변경안을 버릴까요?')) return;
    delete S.deltas[n];
    render();
  },

  // 설정
  async saveSettings() {
    const key = $('#set-key').value.trim();
    const body = {
      provider: $('#set-provider').value, model: $('#set-model').value.trim(),
      local_url: $('#set-local-url').value.trim(), local_model: $('#set-local-model').value.trim(),
      stages: Object.fromEntries(STAGES.map(([s]) => [s, $(`#set-stage-${s}`).value])),
      stage_models: Object.fromEntries(STAGES.map(([s]) => [s, $(`#set-stage-model-${s}`).value.trim()])),
    };
    if (key) body.api_key = key;
    const lkey = $('#set-local-key').value.trim();
    if (lkey) body.local_key = lkey;
    await run('저장 중', async () => {
      S.config = await api('PUT', '/config', body);
      toast('설정을 저장했습니다');
    });
  },
  async clearKey() {
    if (!confirm('저장된 API 키를 지울까요?')) return;
    await run('지우는 중', async () => {
      S.config = await api('PUT', '/config', { clear_key: true });
      toast('키를 지웠습니다');
    });
  },
  async loadModels() {
    await loadModelList(true);
  },
  async testSettings() {
    await run('연결 확인 중', async () => {
      const r = await api('POST', '/config/test');
      toast(r.message);
    });
  },

  // 작업지시서
  openStateBrief(n) {
    S.briefTab = 'state';
    location.hash = `${base()}/brief/${n}`;
  },
  setBriefTab(t) {
    S.briefTab = t;
    S.briefText = null;
    render();
  },
  async copyBrief() {
    try {
      await navigator.clipboard.writeText(S.briefText || '');
      toast('복사했습니다. 채팅 앱에 붙여 넣으세요.');
    } catch {
      toast('복사하지 못했습니다. 내용을 직접 선택해 복사하세요.', true);
    }
  },
  downloadBrief(n) {
    const blob = new Blob([S.briefText || ''], { type: 'text/markdown' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${S.name}-${String(n).padStart(2, '0')}-${S.briefTab}.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  },
  async importText(n) {
    const text = $('#imp-body').value.trim();
    if (!text) return toast('본문을 붙여 넣으세요', true);
    if (ep(n).text && !confirm(`${n}화의 지금 본문을 바꿀까요?`)) return;
    await run('가져오는 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/episodes/${n}/text`, { text });
      delete S.textDraft[n];
      delete S.deltas[n];
      toast(`${n}화 본문으로 저장했습니다`);
      location.hash = `${base()}/write/${n}`;
    });
  },
  async importJson(n) {
    const raw = $('#imp-json').value;
    if (!raw.trim()) return toast('JSON 을 붙여 넣으세요', true);
    await run('확인하는 중', async () => {
      setDelta(n, await api('POST', `/projects/${enc(S.name)}/episodes/${n}/state/parse`, { raw }));
      location.hash = `${base()}/review/${n}`;
    });
  },
};

/** 체크한 항목만 남긴 변경안. 반영과 관계 미리 보기에 같이 쓴다. */
function pickedDelta(n) {
  const d = S.deltas[n];
  const pick = (prefix, list) => list.filter((_, i) => S.picks[prefix + i]);
  return {
    ...d,
    character_updates: pick('c', d.character_updates),
    events: pick('e', d.events),
    secrets_added: pick('s', d.secrets_added),
    relationship_updates: pick('r', d.relationship_updates),
    new_facts: pick('f', d.new_facts),
    foreshadow_planted: pick('p', d.foreshadow_planted),
    foreshadow_resolved: pick('x', d.foreshadow_resolved),
    new_characters: pick('n', d.new_characters || []),
  };
}

let previewTimer = null;
/** 고른 변경안으로 관계를 다시 계산해 미리 보기만 바꾼다 (저장 안 함). */
function refreshPreview(n) {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    if (!S.deltas[n]) return;
    try {
      S.preview = { n, ...(await api('POST', `/projects/${enc(S.name)}/episodes/${n}/preview`, pickedDelta(n))) };
    } catch (e) {
      S.preview = { n, error: e.message };
    }
    const box = $('#rel-preview');
    if (box) box.innerHTML = relationLines(S.preview);
  }, 250);
}

function setDelta(n, d) {
  S.deltas[n] = d;
  S.deltaBase[n] = ep(n) ? ep(n).text : '';
  S.picks = {};
  S.preview = null;
  d.character_updates.forEach((_, i) => { S.picks['c' + i] = true; });
  d.events.forEach((_, i) => { S.picks['e' + i] = true; });
  d.secrets_added.forEach((_, i) => { S.picks['s' + i] = true; });
  d.relationship_updates.forEach((_, i) => { S.picks['r' + i] = true; });
  d.new_facts.forEach((_, i) => { S.picks['f' + i] = true; });
  d.foreshadow_planted.forEach((_, i) => { S.picks['p' + i] = true; });
  d.foreshadow_resolved.forEach((_, i) => { S.picks['x' + i] = true; });
  (d.new_characters || []).forEach((_, i) => { S.picks['n' + i] = true; });
}

document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  e.preventDefault();
  const fn = actions[el.dataset.action];
  const arg = el.dataset.arg;
  if (fn) fn(arg !== undefined && /^\d+$/.test(arg) ? Number(arg) : arg);
});

// ---------- 라우팅 ----------

async function loadProject(name) {
  S.project = await api('GET', `/projects/${enc(name)}`);
  S.name = name;
  S.dirty = false;
}

let lastHash = location.hash;
window.addEventListener('hashchange', async () => {
  if ((S.dirty || S.libDirty) && !confirm('저장하지 않은 변경이 있어요. 버리고 이동할까요?')) {
    history.replaceState(null, '', lastHash);
    return;
  }
  lastHash = location.hash;
  S.libDirty = false;
  await route();
});

async function route() {
  const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
  S.route = parts;
  S.context = null;
  S.promptText = null;
  S.briefText = null;
  S.relations = null;
  try {
    if (!S.config) S.config = await api('GET', '/config');
    if (!S.genres) S.genres = await api('GET', '/genres').catch(() => []);
    if (!S.namingStyles) S.namingStyles = await api('GET', '/naming/styles').catch(() => []);
    if (parts[0] === 'settings') {
      S.config = await api('GET', '/config');
      loadModelList();  // 기다리지 않는다. 목록이 오면 입력칸 추천만 채운다
      await pricesLoad().catch((e) => toast(e.message, true));
    } else if (parts[0] === 'usage') {
      S.name = null;
      S.project = null;
      await usageLoad(parts[1] || '');
    } else if (parts[0] === 'styles') {
      S.name = null;
      S.project = null;
      S.libs = await api('GET', '/styles');
      if (parts[1] === 'new') {
        S.lib = { name: '', source: '', notes: '', sample: '', profile: emptyProfile(), used_by: [] };
      } else if (parts[1]) {
        S.lib = await api('GET', `/styles/${enc(parts[1])}`);
        S.projects = await api('GET', '/projects');
        await libVersionsLoad();
      }
      S.libDirty = false;
    } else if (parts[0] === 'p' && parts[1]) {
      if (S.name !== parts[1] || S.dirty) await loadProject(parts[1]);
      else S.project = await api('GET', `/projects/${enc(parts[1])}`);
      if (S.pendingJob && S.pendingJob.project === S.name && !S.pendingJob.applied) applyJobResult(S.pendingJob);
      S.pendingJob = null;
      S.dirty = false;
      const n = Number(parts[3]);
      if (!parts[2] && S.project.relationships.length) {
        S.relations = await api('GET', `/projects/${enc(S.name)}/relations`).catch((e) => ({ error: e.message }));
      }
      if (parts[2] === 'setup') {
        S.names = {};
        S.nameCheck = await api('POST', `/projects/${enc(S.name)}/names/check`, P()).catch(() => null);
      }
      if (parts[2] === 'style') {
        S.libs = await api('GET', '/styles').catch(() => []);
        await loadStyleLink();
        await learnLoad();
      }
      if (parts[2] === 'write' && n && ep(n) && ep(n).status !== 'draft') {
        S.context = await api('GET', `/projects/${enc(S.name)}/episodes/${n}/context`).catch(() => null);
        if (!S.presets) S.presets = await api('GET', '/passage/presets').catch(() => []);
        if (!S.copyFormats) S.copyFormats = await api('GET', '/publish/formats').catch(() => []);
      }
      if ((parts[2] === 'write' || parts[2] === 'setup') && !S.illModels) S.illModels = await api('GET', '/illust/models').catch(() => []);
      if (parts[2] === 'write' || parts[2] === 'arc') await openingLoad(parts[2] === 'write' ? (n || currentEp()) : 0);
      if (parts[2] === 'research') await rsLoad();
      if (parts[2] === 'usage') await usageLoad(S.name);
      if (parts[2] === 'convert') await convertLoad();
      if (parts[2] === 'causal') {
        if (parts[3]) S.causalSel = parts[3];
        await causalLoad();
      }
      if (typeof autoLoad === 'function') await autoLoad(parts[2] === 'auto');
      if (parts[2] === 'brief' && n && ep(n)) {
        S.briefText = await api('GET', `/projects/${enc(S.name)}/episodes/${n}/brief?kind=${S.briefTab}`).then((r) => r.text).catch((e) => '※ ' + e.message);
      }
    } else {
      S.name = null;
      S.project = null;
      S.projects = await api('GET', '/projects');
      S.libs = await api('GET', '/styles').catch(() => []);
    }
  } catch (e) {
    toast(e.message, true);
    S.name = null;
    S.project = null;
    S.projects = [];
  }
  render();
  window.scrollTo(0, 0);
}

// ---------- 그리기 ----------

function render() {
  renderSavebar();
  document.body.classList.remove('chat-open');
  const [p, , page, arg] = S.route;
  if (p === 'settings') {
    $('#app').innerHTML = `<div class="shell"><main class="main" style="max-width:820px;margin:0 auto">${viewSettings()}</main></div>`;
    return;
  }
  if (p === 'usage') {
    $('#app').innerHTML = `<div class="shell"><main class="main" style="max-width:1180px;margin:0 auto">${viewUsage()}</main></div>`;
    return;
  }
  if (p === 'styles') {
    const body = S.route[1] && S.lib ? viewLibEntry() : viewLibrary();
    $('#app').innerHTML = `<div class="shell"><main class="main" style="max-width:1180px;margin:0 auto">${body}</main></div>`;
    return;
  }
  if (p !== 'p' || !P()) {
    $('#app').innerHTML = `<div class="shell"><main class="main" style="max-width:1080px;margin:0 auto">${viewProjects()}</main></div>`;
    return;
  }
  const n = Number(arg) || currentEp();
  const views = { setup: viewSetup, style: viewStyle, arc: () => (serial() ? viewSerial() : viewArc()), write: viewWrite, review: viewReview, brief: viewBrief, research: viewResearch, usage: viewUsage, auto: viewAuto, causal: viewCausal, lines: viewLines, convert: viewConvert };
  const body = (views[page] || viewHome)(n);
  $('#app').innerHTML = `<div class="shell">${sidebar(page || 'home')}<main class="main">${body}</main></div>`;
  syncChat();
  if (typeof syncPassage === 'function') syncPassage();
  if (typeof syncIllust === 'function') syncIllust();
  document.querySelectorAll('textarea[data-autogrow]').forEach(autosize);
  // 상태 정리 지시서 탭이 바뀌면 다시 불러온다
  if (page === 'brief' && S.briefText === null && ep(n)) {
    api('GET', `/projects/${enc(S.name)}/episodes/${n}/brief?kind=${S.briefTab}`)
      .then((r) => r.text).catch((e) => '※ ' + e.message)
      .then((t) => { S.briefText = t; render(); });
  }
}

function sidebar(active) {
  const p = P();
  const done = p.episodes.filter((e) => e.status === 'finalized').length;
  const total = p.meta.target_episodes;
  const cur = currentEp();
  const items = [
    ['home', base(), 'H', '작품 홈'],
    ['setup', base() + '/setup', '1', '설정 도우미'],
    ['style', base() + '/style', '2', '문체 레퍼런스'],
    ['arc', base() + '/arc', '3', serial() ? '부 · 아크 · 플롯' : '기승전결 · 플롯'],
    ['lines', base() + '/lines', '⑂', '이야기 줄기'],
    ['causal', base() + '/causal', '∴', '인과율'],
    ['write', `${base()}/write/${cur}`, '4', '집필'],
    ['review', `${base()}/review/${cur}`, '5', '상태 승인'],
    ['brief', `${base()}/brief/${cur}`, '6', '작업지시서'],
    ['auto', base() + '/auto', 'A', S.auto && S.auto.active ? '자동 집필 · 진행 중' : '자동 집필'],
  ];
  const cfg = S.config || {};
  return `<nav class="side" aria-label="작품 메뉴">
    <a class="brand" href="#/">Canon</a>
    <div class="work-card">
      <div class="small">현재 작품</div>
      <div style="font-size:16px;font-weight:700">${esc(p.meta.title || S.name)}</div>
      <div class="small">${esc(p.meta.genre || '장르 미정')} · ${total}화</div>
      <div class="meter" aria-hidden="true"><i style="left:0;width:${Math.round((done / Math.max(total, 1)) * 100)}%;background:var(--green)"></i></div>
      <div class="small">${done} / ${total}화 반영 완료</div>
    </div>
    <div class="nav">${items.map(([id, href, num, label]) => `<a href="${href}"${id === active ? ' aria-current="page"' : ''}><span class="num">${num}</span>${label}</a>`).join('')}</div>
    <div class="nav nav-extra"><span class="small">본편과 분리</span><a href="${base()}/research"${active === 'research' ? ' aria-current="page"' : ''}><span class="num">R</span>연구 · 모델 실험</a><a href="${base()}/usage"${active === 'usage' ? ' aria-current="page"' : ''}><span class="num">$</span>사용량 · 비용</a></div>
    <div class="side-foot">
      <span class="small">본문 모델</span>
      <strong style="font-size:13px">${esc(cfg.stages ? cfg.stages.write.model : cfg.model || '')}</strong>
      ${cfg.has_key ? '' : '<span style="color:var(--red)">API 키가 없습니다. 설정에서 넣거나 작업지시서를 쓰세요.</span>'}
      <a href="#/settings">모델 · API 키 설정</a>
      <a href="#/usage">모든 작품 사용량 · 비용</a>
      <a href="#/styles">문체 라이브러리</a>
      <a href="#/">작품 목록</a>
    </div>
  </nav>`;
}

function header(eyebrow, title, desc, right = '') {
  return `<header class="page-head"><div class="lead"><div class="eyebrow">${eyebrow}</div><h1>${esc(title)}</h1>${desc ? `<p class="desc">${desc}</p>` : ''}</div><div class="row">${right}</div></header>`;
}

// ----- 설정 -----

const STAGES = [['plan', '계획 (설정 제안, 문체 분석, 기승전결, 화별 플롯)'], ['write', '본문 쓰기'], ['check', '검수'], ['state', '상태 변경안'],
  ['name', '이름·지명 AI 추천 (정하지 않으면 계획 단계를 따름)'], ['revise', '본문 부분 수정 (정하지 않으면 본문 쓰기 단계를 따름)'],
  ['illustration', '삽화 프롬프트 (정하지 않으면 계획 단계를 따름)']];
const STAGE_PARENT_LABEL = { name: '계획 단계를 따름', revise: '본문 쓰기 단계를 따름' };

function providerOptions(cur) {
  return [['gemini', 'Gemini API'], ['local', '로컬 서버 (OpenAI 호환)'], ['mock', 'mock (AI 호출 없이 화면 확인용)']]
    .map(([v, l]) => `<option value="${v}"${cur === v ? ' selected' : ''}>${l}</option>`).join('');
}

function viewSettings() {
  const c = S.config || {};
  const src = { env: '환경 변수', file: '설정 파일', default: '기본값', none: '없음' };
  const envNote = (s, name) => s === 'env' ? `<div class="small">환경 변수 ${name} 가 설정돼 있어 그 값이 우선합니다.</div>` : '';
  const keyState = c.key_source === 'none'
    ? '<span class="chip" style="background:var(--red-soft);color:var(--red)">없음</span>'
    : `<span class="chip finalized">${esc(c.key_hint)}</span> <span class="small">${src[c.key_source]}</span>`;
  return `${header('Canon', '모델 · API 키 설정', '여기서 저장한 값은 이 컴퓨터의 설정 파일에만 들어갑니다. 작품 폴더나 저장소에는 들어가지 않아요.', '<a class="btn" href="javascript:history.back()">돌아가기</a>')}
    <section class="card">
      <div class="field"><label for="set-provider">생성 방식</label>
        <select id="set-provider">
          ${providerOptions(c.provider)}
        </select>${envNote(c.provider_source, 'CANON_LLM')}
        <div class="small">단계별로 다르게 쓰려면 아래 '단계별 백엔드'에서 고르세요.</div></div>
      <div class="field"><label for="set-key">Gemini API 키 <span class="hint">지금: </span>${keyState}</label>
        <input id="set-key" type="password" autocomplete="off" placeholder="${c.key_source === 'none' ? 'AIza… 로 시작하는 키' : '바꿀 때만 입력'}">
        <div class="small"><a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">Google AI Studio</a>에서 무료로 발급받을 수 있어요. 저장한 키는 화면에 다시 보여주지 않습니다.</div>
        ${envNote(c.key_source, 'GEMINI_API_KEY')}</div>
      <div class="field"><label for="set-model">모델</label>
        <input id="set-model" type="text" list="model-options" value="${esc(c.model_setting || '')}">
        ${modelDatalist()}
        <div class="small">모든 단계의 기본 Gemini 모델입니다. gemini-4-argon 이 기본이고, 단계마다 바꾸려면 아래 '단계별 백엔드와 모델'에서 고르세요.</div>${envNote(c.model_source, 'CANON_MODEL')}</div>
      <h2 style="margin-top:18px">로컬 서버</h2>
      <p class="desc">Ollama, llama.cpp, vLLM, LM Studio 처럼 OpenAI 호환 API 를 여는 서버입니다. 주소는 /v1 까지 적습니다.</p>
      <div class="field"><label for="set-local-url">서버 주소</label>
        <input id="set-local-url" type="text" value="${esc(c.local_url || '')}" placeholder="http://localhost:11434/v1">
        <div class="small">Ollama :11434/v1 · llama.cpp :8080/v1 · vLLM :8000/v1 · LM Studio :1234/v1</div>${envNote(c.local_url_source, 'CANON_LOCAL_URL')}</div>
      <div class="field"><label for="set-local-model">모델 이름</label>
        <input id="set-local-model" type="text" list="model-options" value="${esc(c.local_model || '')}" placeholder="비우면 서버에 하나뿐인 모델">${envNote(c.local_model_source, 'CANON_LOCAL_MODEL')}</div>
      <div class="field"><label for="set-local-key">서버 키 <span class="hint">지금: ${c.has_local_key ? '있음' : '없음'}</span></label>
        <input id="set-local-key" type="password" autocomplete="off" placeholder="서버가 키를 요구할 때만"></div>
      <h2 style="margin-top:18px">단계별 백엔드와 모델</h2>
      <p class="desc">예: 계획과 검수는 gemini-4-argon, 상태 변경안과 이름 추천은 빠르고 싼 gemini-3.8-flash, 본문은 로컬 모델. 모델 칸을 비우면 그 백엔드의 기본 모델(위 '모델' 또는 로컬 '모델 이름')을 씁니다.</p>
      ${STAGES.map(([s, label]) => {
        const st = (c.stages || {})[s] || {};
        const base = st.provider === 'local' ? (c.local_model || '서버에 하나뿐인 모델') : c.model_setting;
        return `<div class="field"><label for="set-stage-${s}">${label} <span class="hint">지금: ${esc(st.model || '')}</span></label>
          <div class="stage-row">
            <select id="set-stage-${s}" aria-label="${esc(label)} 백엔드"><option value="">${STAGE_PARENT_LABEL[s] || '위 생성 방식을 따름'}</option>${providerOptions((c.stage_settings || {})[s])}</select>
            <input id="set-stage-model-${s}" type="text" list="model-options" aria-label="${esc(label)} 모델" value="${esc((c.stage_model_settings || {})[s] || '')}" placeholder="모델: ${esc(base || '기본')}">
          </div>
          ${st.source === 'env' ? `<div class="small">환경 변수 CANON_LLM_${s.toUpperCase()} 가 우선합니다.</div>` : ''}
          ${st.model_source === 'env' ? `<div class="small">환경 변수 CANON_MODEL_${s.toUpperCase()} 가 우선합니다.</div>` : ''}</div>`;
      }).join('')}
      <div class="small" id="model-status">${modelStatus()}</div>
      <div class="row">
        <button class="btn primary" data-action="saveSettings">저장</button>
        <button class="btn" data-action="testSettings">연결 확인</button>
        ${c.key_source === 'file' ? '<button class="btn danger" data-action="clearKey">저장된 키 지우기</button>' : ''}
      </div>
      <div class="small">설정 파일: ${esc(c.path)}</div>
    </section>
    <section class="card" id="price-box">${viewPrices()}</section>
    <div class="small">쓴 비용은 <a href="#/usage">사용량 · 비용</a> 화면에서 봅니다.</div>`;
}

// 모델 칸 추천 목록: Gemini API 와 로컬 서버에 실제로 있는 모델. 없으면 직접 적는다.
const KNOWN_MODELS = ['gemini-4-argon', 'gemini-3.8-flash'];

function modelDatalist() {
  const m = S.models || {};
  const opts = [
    ...(((m.gemini || {}).models || []).length ? m.gemini.models : KNOWN_MODELS).map((x) => [x, 'Gemini']),
    ...((m.local || {}).models || []).map((x) => [x, '로컬 서버']),
  ];
  return `<datalist id="model-options">${opts.map(([v, l]) => `<option value="${esc(v)}" label="${l}"></option>`).join('')}</datalist>`;
}

function modelStatus() {
  const m = S.models;
  if (!m) return '모델 목록을 불러오는 중…';
  const part = (name, r) => r.error ? `${name}: 목록을 못 불러옴 (${esc(r.error.slice(0, 120))})` : `${name} ${r.models.length}개`;
  return `모델 칸을 누르면 고를 수 있어요. ${part('Gemini', m.gemini)} · ${part('로컬 서버', m.local)}. 목록에 없으면 이름을 직접 적어도 됩니다. <a href="javascript:void 0" data-action="loadModels">다시 불러오기</a>`;
}

async function loadModelList(force) {
  if (S.models && !force) return;
  if (force) S.models = null;
  const st = $('#model-status');
  if (st) st.innerHTML = modelStatus();
  try {
    S.models = await api('GET', '/config/models');
  } catch (e) {
    S.models = { gemini: { models: [], error: e.message }, local: { models: [], error: e.message } };
  }
  // 다시 그리면 저장 전 입력이 사라지므로 목록과 안내만 바꾼다
  const dl = $('#model-options');
  if (dl) dl.outerHTML = modelDatalist();
  const st2 = $('#model-status');
  if (st2) st2.innerHTML = modelStatus();
}

// ----- 작품 목록 -----

function viewProjects() {
  const list = S.projects || [];
  const cards = list.map((x) => `<a class="card tight" href="#/p/${enc(x.name)}" style="text-decoration:none;color:inherit">
      <div class="between"><h3>${esc(x.title || x.name)}</h3><span class="small">${x.finalized} / ${x.episodes}화</span></div>
      <div class="small">${esc(x.genre || '장르 미정')} · 폴더 ${esc(x.name)}</div>
    </a>`).join('');
  const cfg = S.config || {};
  return `${header('Canon', '작품', '인물, 관계, 문체, 복선을 데이터로 관리하면서 10~20화 단편부터 300화 장편 연재까지 씁니다.', `<a class="btn" href="#/styles">문체 라이브러리</a><a class="btn" href="#/usage">사용량 · 비용</a><a class="btn" href="#/settings">모델 · API 키 설정</a>`)}
    ${cfg.has_key ? '' : '<div class="note warn">Gemini API 키가 없어요. <a href="#/settings" style="color:inherit;font-weight:700">설정</a>에서 넣으면 AI 생성을 쓸 수 있습니다. 키 없이도 채팅 앱 작업지시서로 쓸 수 있어요.</div>'}
    ${list.length ? `<div class="grid-auto">${cards}</div>` : '<div class="note plain">아직 작품이 없어요. 아래에서 새 작품을 만드세요.</div>'}
    <section class="card" style="max-width:720px">
      <h2>새 작품</h2>
      <div class="grid-2">
        <div class="field"><label for="np-name">폴더 이름 <span class="hint">projects/ 아래에 저장</span></label><input id="np-name" type="text" placeholder="lighthouse"></div>
        <div class="field"><label for="np-title">제목</label><input id="np-title" type="text" placeholder="등대"></div>
        <div class="field"><label for="np-eps">총 화수 <span class="hint">단편 10~20, 장편 100~300</span></label><input id="np-eps" type="number" min="4" max="1000" value="12"></div>
      </div>
      <fieldset class="field form-pick"><legend class="label">형식</legend>
        <label class="row"><input type="radio" name="np-form" id="np-short" value="short" checked><span><strong>단편</strong> <span class="small">작품 전체를 기승전결 하나로 짜고 모든 화의 플롯을 한 번에 만들어요</span></span></label>
        <label class="row"><input type="radio" name="np-form" id="np-serial" value="serial"><span><strong>장편 연재</strong> <span class="small">부 → 아크(5~30화) → 화로 나눠, 다음 아크의 플롯만 그때그때 만들어요. 200~300화 웹소설용</span></span></label>
      </fieldset>
      ${genrePicker()}
      ${adultCheck('id="np-adult"')}
      ${(S.libs || []).length ? `<div class="field"><label for="np-style">문체 <span class="hint">라이브러리에서 고르면 문체 단계를 건너뛸 수 있어요. 나중에 바꿔도 됩니다</span></label>
        <select id="np-style"><option value="">나중에 정하기</option>${S.libs.map((x) => `<option value="${esc(x.id)}">${esc(x.name)}${x.source ? ` · ${esc(x.source)}` : ''}</option>`).join('')}</select></div>` : ''}
      <div class="row"><button class="btn primary" data-action="createProject">만들고 설정 시작</button><span class="small">로그라인은 다음 화면에서 칸을 채우며 만들어요.</span></div>
    </section>`;
}

// ----- 작품 홈 -----

function nextStep() {
  const p = P();
  if (!p.characters.length) return ['설정 시작', base() + '/setup'];
  if (serial()) {
    const open = p.episodes.find((e) => e.status !== 'finalized');
    if (!open && plannedUntil() < p.meta.target_episodes) return [`다음 아크 기획 (${plannedUntil() + 1}화부터)`, base() + '/arc'];
    if (!p.episodes.length) return ['부 · 아크 기획', base() + '/arc'];
  }
  if (!beats().length || !p.episodes.length) return ['기승전결 · 플롯 만들기', base() + '/arc'];
  const e = ep(currentEp());
  if (e.status === 'draft') return [`${e.plot.number}화 플롯 확정`, base() + '/arc'];
  if (e.status === 'confirmed') return [`${e.plot.number}화 쓰기`, `${base()}/write/${e.plot.number}`];
  if (e.status === 'written') return [`${e.plot.number}화 상태 승인`, `${base()}/review/${e.plot.number}`];
  return ['완결 원고 보기', `${base()}/write/${e.plot.number}`];
}

function viewHome() {
  const p = P();
  const m = p.meta;
  const eps = p.episodes;
  const count = (st) => eps.filter((e) => e.status === st).length;
  const confirmed = eps.length - count('draft');
  const written = count('written') + count('finalized');
  const fin = count('finalized');
  const hasStyle = !!(p.style.narration_pov || p.style.sample_passages.length);
  const stage = (cls, st, title, sub, href) => `<a class="stage ${cls}" href="${href}"><div class="bar"></div><div class="st">${st}</div><div style="font-size:14px;font-weight:700">${title}</div><div class="small">${sub}</div></a>`;
  const state = (ok, partial) => (ok ? ['done', '완료'] : partial ? ['doing', '진행 중'] : ['', '시작 전']);
  const [s1c, s1t] = state(p.characters.length > 0);
  const [s2c, s2t] = state(hasStyle);
  const [s3c, s3t] = serial() ? state(plannedUntil() >= m.target_episodes, p.story_arcs.length > 0) : state(p.arc.length === 4);
  const [s4c, s4t] = state(eps.length && confirmed === m.target_episodes, confirmed > 0);
  const [s5c, s5t] = state(written === m.target_episodes, written > 0);
  const [s6c, s6t] = state(fin === m.target_episodes, fin > 0);
  const cur = currentEp();
  const [nextLabel, nextHref] = nextStep();

  const actBand = p.arc.length && !serial() ? `<div class="act-band" style="display:grid;grid-template-columns:repeat(${m.target_episodes},minmax(0,1fr));gap:6px">${actGroups(p.arc).map((g) => `<div class="act-head ${actClass(g.names[0])}" style="grid-column:span ${g.end - g.start + 1};padding:4px 8px;font-size:12px;font-weight:700">${g.names.join('·')} ${g.start}–${g.end}화</div>`).join('')}</div>` : '';
  // 장편은 지금 쓰는 부(없으면 지금 아크 근처 60화)만 칸으로 보인다
  const curPart = serial() ? p.parts.find((x) => x.start_ep <= cur && cur <= x.end_ep) : null;
  const shown = !serial() ? eps : curPart ? eps.filter((e) => e.plot.number >= curPart.start_ep && e.plot.number <= curPart.end_ep)
    : eps.filter((e) => Math.abs(e.plot.number - cur) <= 30);
  const arcBand = serial() && p.story_arcs.length ? `<div class="arc-rail">${p.story_arcs.filter((a) => shown.some((e) => e.plot.number >= a.start_ep && e.plot.number <= a.end_ep)).map((a) => `<a class="arc-chip" href="${base()}/arc"><strong>아크 ${a.number}</strong> <span>${a.start_ep}–${a.end_ep}화 ${esc(a.title)}</span></a>`).join('')}</div>` : '';
  const cells = shown.map((e) => {
    const n = e.plot.number;
    const href = e.status === 'draft' ? base() + '/arc' : e.status === 'written' ? `${base()}/review/${n}` : `${base()}/write/${n}`;
    return `<a class="ep-cell ${e.status}${n === cur && e.status !== 'finalized' ? ' current' : ''}" href="${href}" title="${esc(e.plot.title)}"><strong>${n}</strong><span>${e.auto ? '자동 반영' : STATUS[e.status].replace('플롯 ', '').replace('본문 ', '')}</span></a>`;
  }).join('');

  const states = p.characters.map((c) => {
    const s = p.states.find((x) => x.character_id === c.id) || {};
    const lines = [['감정', s.emotional_state], ['목표', s.current_goal], ['위치', s.location]].filter(([, v]) => v);
    return `<div class="kv"><div style="font-size:14px;font-weight:700">${esc(c.name)} <span class="small" style="font-weight:400">${esc(c.role)}</span></div>${lines.map(([k, v]) => `<div class="line">${k}: ${esc(v)}</div>`).join('') || '<div class="line small">아직 변화 없음</div>'}</div>`;
  }).join('');
  const openFs = p.foreshadows.filter((f) => f.status === 'open');
  const lastWarn = p.history.length ? p.history[p.history.length - 1].warnings : [];

  return `${header(`${esc(m.genre || '장르 미정')}${m.adult ? ' · 성인' : ''} · 전 ${m.target_episodes}화 · 화당 ${Number(m.words_per_episode).toLocaleString()}자`, m.title || S.name, esc(m.logline), `${!serial() && fin && fin === m.target_episodes ? `<a class="btn" href="${base()}/convert">장편으로 늘리기</a>` : ''}<a class="btn" href="${base()}/arc">플롯 보드</a><a class="btn primary" href="${nextHref}">${esc(nextLabel)}</a>`)}
    <section class="card" aria-label="진행 단계"><div class="stages">
      ${stage(s1c, s1t, '1 설정', `인물 ${p.characters.length} · 관계 ${p.relationships.length}`, base() + '/setup')}
      ${stage(s2c, s2t, '2 문체', hasStyle ? `대표 문단 ${p.style.sample_passages.length}개` : '선택 사항', base() + '/style')}
      ${serial() ? stage(s3c, s3t, '3 부 · 아크', p.story_arcs.length ? `아크 ${p.story_arcs.length}개 · ${plannedUntil()}화까지` : '없음', base() + '/arc') : stage(s3c, s3t, '3 기승전결', p.arc.length ? '4구간' : '없음', base() + '/arc')}
      ${stage(s4c, s4t, '플롯 확정', `${confirmed} / ${m.target_episodes}화`, base() + '/arc')}
      ${stage(s5c, s5t, '4 집필', `${written} / ${m.target_episodes}화`, `${base()}/write/${cur}`)}
      ${stage(s6c, s6t, '5 상태 반영', `${fin} / ${m.target_episodes}화`, `${base()}/review/${cur}`)}
    </div></section>
    <section class="card">
      <div class="between"><h2>회차 진행</h2><div class="legend">
        <span><i style="background:var(--chip);border:1px solid var(--line-strong)"></i>플롯 초안</span>
        <span><i style="background:var(--accent)"></i>플롯 확정</span>
        <span><i style="background:var(--amber)"></i>본문 작성됨</span>
        <span><i style="background:var(--green)"></i>반영 완료</span></div></div>
      ${eps.length ? `${actBand}${arcBand}<div class="ep-grid"${serial() ? '' : ` style="grid-template-columns:repeat(${m.target_episodes},minmax(0,1fr))"`}>${cells}</div>${curPart ? `<div class="small">${curPart.number}부 ${esc(curPart.title)} (${curPart.start_ep}–${curPart.end_ep}화)만 보여요. 전체는 <a href="${base()}/arc">부 · 아크</a>에서 보세요.</div>` : ''}` : `<div class="note plain">아직 화별 플롯이 없어요. <a href="${base()}/arc">기승전결 · 플롯</a>에서 만드세요.</div>`}
      ${eps.some((e) => e.status === 'written') ? `<div class="note warn">${cur}화 본문이 작성됐습니다. 상태 변경안을 승인해야 다음 화를 쓸 수 있어요. <a href="${base()}/review/${cur}" style="color:inherit;font-weight:700">${cur}화 변경안 검토</a></div>` : ''}
    </section>
    <div class="grid-auto">
      <section class="card"><div class="between"><h2>인물 현재 상태</h2><span class="small">${fin ? fin + '화 기준' : '시작 시점'}</span></div>${states || '<div class="small">인물이 없습니다</div>'}<a href="${base()}/setup" style="font-size:13px">인물 · 관계 전체 보기</a></section>
      <section class="card">${relationHeader('관계')}${p.relationships.length ? relationLines(S.relations) : '<div class="small">관계가 없어요. 설정 도우미에서 관계를 추가하세요.</div>'}</section>
      <section class="card"><div class="between"><h2>열린 복선</h2><span class="small">${openFs.length}개</span></div>
        ${openFs.map((f) => `<div class="row" style="align-items:flex-start;flex-wrap:nowrap"><span class="chip">${f.planted_ep}화</span><div style="font-size:13px;line-height:1.5">${esc(f.description)}<br><span class="small">${esc(f.id)}</span></div></div>`).join('') || '<div class="small">없음</div>'}
      </section>
      <section class="card"><div class="between"><h2>확정 사실</h2><span class="small">${p.facts.length}개</span></div>
        ${p.facts.length ? `<ul style="padding-left:18px;display:flex;flex-direction:column;gap:8px;font-size:13px;line-height:1.5;color:var(--text-2)">${p.facts.slice(-8).map((f) => `<li>${esc(f)}</li>`).join('')}</ul>` : '<div class="small">없음</div>'}
        ${lastWarn.length ? `<div class="note warn">최근 경고: ${lastWarn.map(esc).join(' / ')}</div>` : ''}
      </section>
    </div>`;
}

// ----- 장르 -----

function genreById(id) {
  return (S.genres || []).find((g) => g.id === id);
}

function genreLabel(m) {
  return m.genres.map((id) => (genreById(id) ? genreById(id).name : id)).join(' · ') || m.genre || '';
}

// 설정 화면에서는 작품의 meta, 작품 목록의 새 작품 폼에서는 아직 저장하지 않은 S.newMeta
function genreTarget() {
  if (S.route[0] === 'p' && P()) return P().meta;
  if (!S.newMeta) S.newMeta = { genres: [], genre: '' };
  return S.newMeta;
}

// 다른 입력칸을 지우지 않도록 장르 고르기 부분만 다시 그린다
function syncGenre() {
  const m = genreTarget();
  m.genre = genreLabel(m);
  if (m !== S.newMeta) markDirty();
  const box = $('#genre-picker');
  if (box) box.outerHTML = genrePicker();
  else render();
}

function genreGuide(g) {
  const row = (k, v) => (v && v.length ? `<div class="g-row"><span class="g-k">${k}</span><span>${esc(Array.isArray(v) ? v.join(', ') : v)}</span></div>` : '');
  return `<details class="genre-guide"><summary><strong>${esc(g.name)}</strong><div class="small">${esc(g.summary)}</div></summary>
    ${row('독자가 기대하는 것', g.reader_expects)}${row('관습', g.conventions)}${row('자주 쓰는 소재', g.tropes)}${row('전개 속도', g.pacing)}${row('피할 것', g.avoid)}</details>`;
}

function genrePicker() {
  const m = genreTarget();
  const cat = S.genres || [];
  const opts = (kind) => cat.filter((g) => g.kind === kind).map((g) => `<button type="button" aria-pressed="${m.genres.includes(g.id)}" data-action="toggleGenre" data-arg="${esc(g.id)}" title="${esc(g.summary)}">${esc(g.name)}</button>`).join('');
  const custom = m.genres.filter((id) => !genreById(id));
  const picked = m.genres.map(genreById).filter(Boolean);
  return `<div id="genre-picker" class="genre-picker"><div class="field"><span class="label-text">장르 <span class="hint">여러 개 고를 수 있어요. 고른 장르의 안내가 AI 프롬프트에 들어갑니다</span></span>
      <div class="genre-opts" role="group" aria-label="장르">${opts('장르')}</div>
      <div class="small" style="margin-top:4px">요소</div>
      <div class="genre-opts" role="group" aria-label="요소">${opts('요소')}${custom.map((c) => `<button type="button" aria-pressed="true" data-action="toggleGenre" data-arg="${esc(c)}" title="직접 적은 장르, 누르면 빠집니다">${esc(c)} ✕</button>`).join('')}</div>
      <div class="row" style="flex-wrap:nowrap"><input id="genre-custom" type="text" aria-label="직접 적는 장르" placeholder="목록에 없으면 직접 적기 (예: 오컬트)"><button type="button" class="btn small" style="white-space:nowrap;flex:none" data-action="addCustomGenre">추가</button></div>
    </div>
    ${picked.length ? `<div class="genre-guides">${picked.map(genreGuide).join('')}</div>` : ''}</div>`;
}

function adultCheck(attrs) {
  return `<label class="check-row"><input type="checkbox" ${attrs}><span><strong>성인물</strong> <span class="small">성인 독자 대상. 끄면 노골적인 성적 묘사와 과도한 잔혹 묘사를 피하도록 지시합니다</span></span></label>`;
}

// ----- 1. 설정 도우미 -----

// 로그라인 다섯 칸과 톤 다이얼. canon/logline.py 와 같은 규칙이라 함께 고친다.
const LOGLINE_SLOTS = [
  ['who', '누가', '이름보다 특징이 먼저 보이게'],
  ['why', '무엇 때문에', '이야기를 시작하게 만드는 일'],
  ['goal', '무엇을 하려 하나', "눈에 보이는 행동, '~한다'로 끝내기"],
  ['block', '무엇이 막나', '사람이나 힘'],
  ['stake', '무엇이 걸렸나', '선택, 비워도 돼요'],
];

function josa(word, withFinal, withoutFinal) {
  const w = word.trim();
  if (!w) return '';
  const code = w.charCodeAt(w.length - 1);
  if (code < 0xAC00 || code > 0xD7A3) return `${withFinal}(${withoutFinal})`;
  return (code - 0xAC00) % 28 ? withFinal : withoutFinal;
}

function composeLogline(p) {
  const [who, why, goal, block, stake] = LOGLINE_SLOTS.map(([k]) => (p[k] || '').trim().replace(/\.+$/, ''));
  let out = '';
  if (who) out += who + josa(who, '이', '가') + ' ';
  if (why) out += why + ' ';
  if (goal) out += goal + '.';
  if (block) out += (out ? ' 하지만 ' : '') + block + '.';
  if (stake) out += ' ' + stake + '.';
  return out.trim();
}

function loglineChecks(p) {
  const n = composeLogline(p).length;
  return [
    [p.who.trim().split(/\s+/).length > 1, '주인공에게 이름 말고 특징이 있다'],
    [!!p.why.trim(), '이야기를 시작하게 만드는 일이 있다'],
    [p.goal.trim().endsWith('다'), "목표가 눈에 보이는 행동이다 ('~한다'로 끝남)"],
    [!!p.block.trim(), '목표를 막는 사람이나 힘이 있다'],
    [n >= 40 && n <= 150, '길이가 40~150자 사이다'],
  ];
}

const TONE_DIALS = [['dark', '밝다', '어둡다'], ['serious', '가볍다', '진지하다'], ['slow', '빠르다', '느리다']];
const TONE_WORDS = {
  dark: [['밝고', '밝다'], ['조금 밝고', '조금 밝다'], ['조금 어둡고', '조금 어둡다'], ['어둡고', '어둡다']],
  serious: [['가볍고', '가볍다'], ['조금 가볍고', '조금 가볍다'], ['조금 진지하고', '조금 진지하다'], ['진지하고', '진지하다']],
  slow: [['호흡이 빠르다', '호흡이 빠르다'], ['호흡이 조금 빠르다', '호흡이 조금 빠르다'], ['호흡이 조금 느리다', '호흡이 조금 느리다'], ['호흡이 느리다', '호흡이 느리다']],
};

function toneText(d) {
  const words = TONE_DIALS.map(([k]) => (d[k] >= 1 && d[k] <= 4 ? TONE_WORDS[k][d[k] - 1] : null)).filter(Boolean);
  return words.map((w, i) => (i === words.length - 1 ? w[1] : w[0])).join(' ');
}

/** 고른 장르의 로그라인 예시. 장르를 안 골랐으면 미스터리와 현대 드라마 예시 */
function loglineExamples() {
  const ids = P().meta.genres.filter(genreById);
  return (ids.length ? ids : ['mystery', 'drama']).flatMap((id) => (genreById(id) || {}).logline || []);
}

function loglineBuilder() {
  const m = P().meta;
  const parts = m.logline_parts;
  const exs = loglineExamples();
  const legacy = !Object.values(parts).some((v) => v.trim()) && m.logline.trim();
  const slots = LOGLINE_SLOTS.map(([k, label, hint]) => {
    const chips = [...new Set(exs.map((e) => e[k]).filter(Boolean))].slice(0, 3)
      .map((v) => `<button type="button" data-action="fillSlot" data-arg="${esc(k + '|' + v)}">${esc(v)}</button>`).join('');
    return `<div class="slot">${input(label, 'meta.logline_parts.' + k, { hint })}${chips ? `<div class="genre-opts ex-opts" role="group" aria-label="${esc(label)} 예시">${chips}</div>` : ''}</div>`;
  }).join('');
  return `<div class="logline-box"><span class="label-text">로그라인 <span class="hint">다섯 칸을 채우면 한 문장으로 합쳐요. 점선 예시를 누르면 칸에 들어갑니다</span></span>
    ${legacy ? '<div class="note plain">지금 로그라인은 한 문장으로만 저장되어 있어요. 칸을 채우면 칸 내용으로 바뀝니다.</div>' : ''}
    ${slots}
    <div class="logline-out"><p id="logline-preview" class="logline-preview" aria-live="polite">${esc(m.logline || LOGLINE_EMPTY)}</p><ul id="logline-checks" class="logline-checks">${loglineChecksHtml(m)}</ul></div>
    ${exs.length ? `<details><summary>예시 로그라인 ${exs.length}개 보기</summary><div class="ex-list">${exs.map((e, i) => `<div class="ex-item"><span>${esc(composeLogline(e))}</span><button type="button" class="btn small" data-action="useExample" data-arg="${i}">이 예시로 채우기</button></div>`).join('')}</div></details>` : ''}
    <details${legacy ? ' open' : ''}><summary>한 문장으로 직접 고쳐 쓰기</summary>${input('로그라인 문장', 'meta.logline', { rows: 3, hint: '칸을 다시 고치면 칸 내용으로 바뀝니다' })}</details>
  </div>`;
}

const LOGLINE_EMPTY = '칸을 채우면 여기에 로그라인이 만들어져요.';

function loglineChecksHtml(m) {
  const parts = m.logline_parts;
  if (!Object.values(parts).some((v) => v.trim())) return '';
  return loglineChecks(parts).map(([ok, t]) => `<li class="${ok ? 'ok' : ''}">${esc(t)}</li>`).join('') + `<li class="len">${m.logline.length}자 · 점검은 참고용이에요</li>`;
}

/** 로그라인 칸이 바뀌면 합친 문장, 점검, 직접 쓰기 칸만 다시 그린다 (입력 중인 칸의 포커스 유지) */
function updateLogline() {
  const m = P().meta;
  const parts = m.logline_parts;
  const empty = !Object.values(parts).some((v) => v.trim());
  if (!empty) {
    m.logline = composeLogline(parts);
    const raw = $('#f-meta-logline');
    if (raw) raw.value = m.logline;
  }
  const pv = $('#logline-preview');
  if (pv) pv.textContent = m.logline || LOGLINE_EMPTY;
  const ck = $('#logline-checks');
  if (ck) ck.innerHTML = loglineChecksHtml(m);
}

function toneBox() {
  const d = P().meta.tone_dials;
  const rows = TONE_DIALS.map(([k, l, r]) => `<div class="dial" role="group" aria-label="${l}, ${r}"><span>${l}</span>${[1, 2, 3, 4].map((v) => `<button type="button" aria-pressed="${d[k] === v}" aria-label="${l}에서 ${r} 사이 ${v}단계" data-action="setDial" data-arg="${k}|${v}"></button>`).join('')}<span>${r}</span></div>`).join('');
  return `<div id="tone-box" class="field"><span class="label-text">톤 <span class="hint">양 끝 중 어디에 가까운가. 고르면 아래 문장이 바뀌고, 문장은 직접 고쳐도 돼요</span></span>${rows}${input('톤 문장', 'meta.tone', { placeholder: '예: 조금 어둡고 진지하고 호흡이 느리다' })}</div>`;
}

// 관계를 말로 고르기. VIEWS 는 canon/dynamics.py 의 VIEWS 와 같은 목록이다.
const VIEWS = ['믿는다', '좋아한다', '경계한다', '미워한다', '빚졌다', '얕본다', '잘 모른다'];
const REL_TYPES = ['가족', '친구', '동료', '연인', '옛 연인', '라이벌', '사제', '상사와 부하'];
const CONFLICTS = [['아니다', 0], ['조금', 0.4], ['정면으로', 0.8]];

function conflictWord(v) {
  return v >= 0.6 ? '정면으로' : v > 0 ? '조금' : '아니다';
}

function relRow(r, i) {
  const p = P();
  const b = `relationships.${i}`;
  const opts = (sel) => p.characters.map((c) => `<option value="${esc(c.id)}"${c.id === sel ? ' selected' : ''}>${esc(c.name || c.id)}</option>`).join('');
  const started = p.snapshots.length > 0; // 첫 상태 반영 뒤에는 관계 사건으로 계산한다
  const chips = (vals, on, act) => vals.map(([label, arg]) => `<button type="button" aria-pressed="${on(label)}" data-action="${act}" data-arg="${esc(`${i}|${arg}`)}">${esc(label)}</button>`).join('');
  const view = (side, from, to) => `<div class="rel-line"><span class="label-text">${esc(charName(from) || from)} → ${esc(charName(to) || to)}</span>
      <div class="genre-opts" role="group" aria-label="${esc(charName(from) || from)}이(가) ${esc(charName(to) || to)}을(를) 보는 방식">${chips(VIEWS.map((w) => [w, `${side}|${w}`]), (w) => (r[side] || []).includes(w), 'toggleView')}</div></div>`;
  return `<div class="rel-card" id="rel-${i}">
    <div class="rel-top">
      <div class="field"><label for="ra${i}">인물 A</label><select id="ra${i}" data-bind="${b}.a">${opts(r.a)}</select></div>
      <div class="field"><label for="rb${i}">인물 B</label><select id="rb${i}" data-bind="${b}.b">${opts(r.b)}</select></div>
      ${input('어떤 사이', b + '.type', { placeholder: '오빠의 친구, 남매…' })}
      <button class="btn icon-btn danger" data-action="removeRelationship" data-arg="${i}" aria-label="관계 삭제">✕</button>
    </div>
    <div class="genre-opts ex-opts" role="group" aria-label="어떤 사이 예시">${chips(REL_TYPES.map((t) => [t, t]), (t) => r.type === t, 'setRelType')}</div>
    ${started ? `<div class="small">지금 호감 ${r.affinity} · 긴장 ${r.tension}. 첫 반영 뒤에는 본문의 관계 사건으로 바뀝니다.</div>` : `${view('a_view', r.a, r.b)}${view('b_view', r.b, r.a)}`}
    <div class="rel-line"><span class="label-text">원하는 게 부딪치나</span><div class="genre-opts" role="group" aria-label="목표 충돌">${chips(CONFLICTS, (w) => conflictWord(r.goal_conflict || 0) === w, 'setConflict')}</div></div>
    ${started ? '' : `<details><summary>숫자로 직접 정하기</summary><div class="grid-2" style="padding-top:8px">
      <div class="field"><label for="raf${i}">시작 호감 <output id="raf${i}o">${r.affinity}</output> <span class="hint">보는 방식을 고른 방향은 고른 말이 우선</span></label><input id="raf${i}" type="range" min="-5" max="5" value="${r.affinity}" data-bind="${b}.affinity" data-kind="int" data-out="raf${i}o"></div>
      <div class="field"><label for="rg${i}">목표 충돌 <output id="rg${i}o">${r.goal_conflict || 0}</output></label><input id="rg${i}" type="range" min="0" max="1" step="0.1" value="${r.goal_conflict || 0}" data-bind="${b}.goal_conflict" data-kind="float" data-out="rg${i}o"></div>
    </div></details>`}
  </div>`;
}

function refreshRel(i) {
  const el = $(`#rel-${i}`);
  if (el) el.outerHTML = relRow(P().relationships[i], i);
}

async function loadNames(key, req, ai) {
  await run(ai ? 'AI 가 고르는 중' : '후보 뽑는 중', async () => {
    const r = await api('POST', `/projects/${enc(S.name)}/names`, { ...req, ai, n: 8, project: P() });
    S.names[key] = { ...r, ai };
    if (S.nameCheck) Object.assign(S.nameCheck, { style: r.style, detected: r.detected });
  });
}

async function checkNames(show = false) {
  const r = await api('POST', `/projects/${enc(S.name)}/names/check`, P()).catch(() => null);
  if (!r) return;
  S.nameCheck = r;
  const box = $('#name-check');
  if (box) box.outerHTML = nameCheckBox();
  const auto = $('#name-style-auto');
  if (auto) auto.textContent = `자동 (지금: ${styleLabel(r.detected)})`;
  if (show) toast(r.warnings.length ? `이름 점검: ${r.warnings.length}건` : '이름 점검: 문제 없음');
}

function styleLabel(id) {
  const st = (S.namingStyles || []).find((x) => x.id === id);
  return st ? st.label : id || '';
}

function nameCheckBox() {
  const w = (S.nameCheck || {}).warnings || [];
  if (!w.length) return '<div id="name-check"></div>';
  return `<div id="name-check" class="note warn"><strong>이름 점검</strong><ul style="margin:4px 0 0;padding-left:18px">${w.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div>`;
}

// 후보 칩. AI 추천이면 이유를, 코드 후보면 시대·종류 메모를 같이 보여 준다
function namePicks(key, action, argOf) {
  const r = S.names[key];
  if (!r) return '';
  const items = r.ai ? (r.options || []).map((o) => ({ name: o.name, note: o.reason }))
    : (r.candidates || []).map((c) => ({ name: c.name, note: [c.kind, c.note].filter(Boolean).join(' · ') }));
  const chips = items.map((x) => `<button type="button" class="name-pick" data-action="${action}" data-arg="${esc(argOf(x.name))}" title="${esc(x.note)}">${esc(x.name)}${x.note ? `<small>${esc(x.note)}</small>` : ''}</button>`).join('');
  return `<div class="name-picks-box">
    <div class="between"><span class="small">${r.ai ? 'AI 추천' : '무작위 후보'} · ${esc(r.style_label)} · 눌러서 ${key === 'place' ? '장소에 추가' : '이름으로 쓰기'}</span>
      <button type="button" class="btn small ghost" data-action="closeNames" data-arg="${esc(key)}">닫기</button></div>
    <div class="name-picks">${chips || '<span class="small">후보가 없어요</span>'}</div></div>`;
}

function nameStyleField() {
  const w = P().world;
  const det = (S.nameCheck || {}).detected;
  const opts = (S.namingStyles || []).map((st) => `<option value="${esc(st.id)}"${w.name_style === st.id ? ' selected' : ''}>${esc(st.label)}</option>`).join('');
  const cur = (S.namingStyles || []).find((st) => st.id === (w.name_style || det));
  return `<div class="field"><label for="f-name-style">이름 스타일 <span class="hint">이름과 지명 후보를 뽑는 기준</span></label>
    <select id="f-name-style" data-bind="world.name_style" data-kind="text"><option value="" id="name-style-auto">자동 (지금: ${esc(styleLabel(det))})</option>${opts}</select>
    ${cur ? `<div class="small">${esc(cur.summary)}</div>` : ''}</div>`;
}

function placeKindOptions() {
  const sid = P().world.name_style || (S.nameCheck || {}).style;
  const st = (S.namingStyles || []).find((x) => x.id === sid);
  return ['<option value="">종류 무관</option>', ...((st && st.place_kinds) || []).map((k) => `<option value="${esc(k)}"${S.placeKind === k ? ' selected' : ''}>${esc(k)}</option>`)].join('');
}

function viewSetup() {
  const p = P();
  const chars = p.characters.map((c, i) => {
    const b = `characters.${i}`;
    return `<article class="char-card">
      <div class="between"><strong style="font-size:16px">${esc(c.name || '이름 없음')}</strong><button class="btn small danger" data-action="removeCharacter" data-arg="${i}" aria-label="${esc(c.name || c.id)} 삭제">삭제</button></div>
      <div class="grid-2">${input('이름', b + '.name')}${input('역할', b + '.role', { placeholder: '주인공, 상대역, 조력자…' })}</div>
      <div class="grid-2">${input('나이', b + '.age', { placeholder: '예: 17세, 40대 초반' })}${input('성별', b + '.gender', { placeholder: '남 / 여' })}</div>
      ${serial() ? `<div class="field"><label for="tier-${i}">비중 <span class="hint">주역은 매 화 설정 전체가 들어가고, 조연 · 단역은 나오는 화에만 들어가요${c.first_ep ? ` · ${c.first_ep}화에 처음 나옴` : ''}</span></label>
        <select id="tier-${i}" data-bind="${b}.tier">${[['main', '주역'], ['support', '조연'], ['minor', '단역']].map(([v, l]) => `<option value="${v}"${(c.tier || 'main') === v ? ' selected' : ''}>${l}</option>`).join('')}</select></div>` : ''}
      <div class="row"><button type="button" class="btn small" data-action="nameCandidates" data-arg="${esc(c.id)}">이름 후보 뽑기</button><button type="button" class="btn small" data-action="nameAI" data-arg="${esc(c.id)}">AI 이름 추천</button></div>
      ${namePicks('c:' + c.id, 'useName', (n) => `${c.id}|${n}`)}
      ${input('원하는 것', b + '.goal', { hint: '작품 전체에서' })}
      ${input('두려운 것 · 약점', b + '.wound')}
      ${input('숨기는 것', b + '.secrets', { kind: 'list', rows: 2 })}
      ${input('말투', b + '.speech_style', { rows: 2, hint: '어미, 호칭, 대사 한 줄' })}
      <details><summary>더 자세히: 성격, 배경, 외모, 아크</summary><div style="display:flex;flex-direction:column;gap:10px;padding-top:8px">
        ${input('성격', b + '.personality', { rows: 2 })}${input('배경', b + '.background', { rows: 2 })}${input('외모', b + '.appearance')}
        ${input('아크', b + '.arc', { hint: '시작 → 결말' })}${input('id', b + '.id', { hint: '관계와 플롯이 인물을 찾는 값. 보통 바꿀 필요 없어요' })}
      </div></details>
      ${visualFields(c)}
    </article>`;
  }).join('');

  const rels = p.relationships.map(relRow).join('');

  return `${header('1단계', '설정 도우미', '채운 칸은 그대로 두고, 빈칸만 AI 가 제안합니다. 제안에서 원하는 인물과 관계만 골라 반영하세요.', `${((b) => `<button class="btn" data-action="suggest"${b.attr}>${b.label}</button>`)(jobBtn('suggest', null, '빈칸 AI 제안받기'))}<a class="btn primary" href="${base()}/style">문체로</a>`)}
    ${S.suggestion ? viewSuggestion() : ''}
    <div class="cols">
      <div class="col">
        <section class="card">
          <h2>기본 정보</h2>
          ${input('제목', 'meta.title')}
          ${genrePicker()}
          ${adultCheck(`data-bind="meta.adult" data-kind="bool"${P().meta.adult ? ' checked' : ''}`)}
          ${input('총 화수 (10~20)', 'meta.target_episodes', { type: 'number', min: 1, max: 40 })}
          ${loglineBuilder()}
          ${input('주제', 'meta.theme', { hint: '이 이야기가 끝까지 묻는 질문 하나', placeholder: '예: 떠난 사람을 이해하면 용서할 수 있나?' })}
          ${toneBox()}
          ${input('화당 분량', 'meta.words_per_episode', { type: 'number', hint: '공백 포함 글자 수' })}
          ${input('메모', 'meta.notes', { rows: 2 })}
        </section>
        <section class="card">
          <h2>세계관</h2>
          ${input('배경', 'world.setting', { rows: 2 })}${input('시대', 'world.era')}
          ${input('깨면 안 되는 규칙', 'world.rules', { kind: 'list' })}${input('장소', 'world.locations', { kind: 'list' })}
          <div class="row"><select id="place-kind" aria-label="지명 종류" data-local="placeKind" style="width:auto;min-width:120px">${placeKindOptions()}</select>
            <button type="button" class="btn small" data-action="placeCandidates">지명 후보 뽑기</button><button type="button" class="btn small" data-action="placeAI">AI 지명 추천</button></div>
          ${namePicks('place', 'addPlace', (n) => n)}
          ${nameStyleField()}
          ${input('이름 규칙', 'world.name_rules', { kind: 'list', rows: 2, placeholder: "예: 북부 귀족은 성 앞에 '폰'을 붙인다" })}
        </section>
      </div>
      <div class="col wide">
        <section class="card">
          <div class="between"><h2>인물 <span class="small">${p.characters.length}명</span></h2><button class="btn small" data-action="addCharacter">+ 인물 추가</button></div>
          <p class="small">이름, 말투, 성격은 고정 설정입니다. 회차가 지나며 바뀌는 감정과 목표는 상태 승인 화면에서 관리합니다.</p>
          <div class="row"><button type="button" class="btn small ghost" data-action="checkNames">이름 점검</button><span class="small">글자가 겹치는 이름, 나이와 안 맞는 이름, AI 가 자주 짓는 이름을 찾아요</span></div>
          ${nameCheckBox()}
          ${chars ? `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px">${chars}</div>` : '<div class="note plain">인물이 없어요. 직접 추가하거나 AI 제안을 받으세요.</div>'}
        </section>
        <section class="card">
          <div class="between"><h2>관계</h2><div class="row"><span class="small">${P().snapshots.length ? '첫 반영 뒤에는 관계 사건으로 계산됩니다' : '서로 어떻게 보는지 고르면 시작 관계를 계산해요. 긴장은 자동 계산'}</span><button class="btn small" data-action="addRelationship">+ 관계 추가</button></div></div>
          ${rels || '<div class="small">관계가 없어요.</div>'}
        </section>
      </div>
    </div>`;
}

function viewSuggestion() {
  const s = S.suggestion;
  const exists = (id) => P().characters.some((c) => c.id === id);
  return `<section class="card" style="border:2px solid var(--accent)">
    <div class="between"><h2>AI 제안 <span class="chip ai">반영 전</span></h2><div class="row"><button class="btn small" data-action="dropSuggestion">버리기</button><button class="btn small primary" data-action="applySuggestion">선택 항목 반영</button></div></div>
    <p class="small">주제, 톤, 세계관은 비어 있는 칸에만 들어갑니다. 이미 있는 인물 id 는 건너뜁니다.</p>
    <div class="grid-2"><div class="note plain"><strong>주제</strong> ${esc(s.theme)}<br><strong>톤</strong> ${esc(s.tone)}</div><div class="note plain"><strong>배경</strong> ${esc(s.world.setting)} ${esc(s.world.era)}<br><strong>규칙</strong> ${s.world.rules.map(esc).join(', ')}</div></div>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px">
      ${s.characters.map((c, i) => `<label class="char-card suggested" style="cursor:pointer"><span class="row"><input type="checkbox" data-pick="sc${i}"${S.picks['sc' + i] ? ' checked' : ''}${exists(c.id) ? ' disabled' : ''}><strong>${esc(c.name)}</strong><span class="small">${esc(c.role)} · ${esc(c.id)}${exists(c.id) ? ' · 이미 있음' : ''}</span></span>
        <span style="font-size:13px;line-height:1.5">목표: ${esc(c.goal)}<br>말투: ${esc(c.speech_style)}</span></label>`).join('')}
    </div>
    ${s.relationships.map((r, i) => `<label class="row" style="font-size:13px"><input type="checkbox" data-pick="sr${i}"${S.picks['sr' + i] ? ' checked' : ''}>${esc(r.a)} ↔ ${esc(r.b)} · ${esc(r.type)} · ${(r.a_view || []).length || (r.b_view || []).length ? `${esc(r.a)}→${esc(r.b)} ${esc((r.a_view || []).join(', ') || '-')} · ${esc(r.b)}→${esc(r.a)} ${esc((r.b_view || []).join(', ') || '-')}` : `호감 ${r.affinity} · 긴장 ${r.tension}`}</label>`).join('')}
  </section>`;
}

// ----- 2. 문체 -----

function emptyProfile() {
  return {
    narration_pov: '', tense: '', sentence_rhythm: '', description_density: '', dialogue_ratio: '', dialogue_style: '',
    inner_monologue: '', pacing: '', scene_transition: '', vocabulary: '', dos: [], donts: [], banned_phrases: [], markers: [], devices: [], sample_passages: [],
  };
}

/** 스타일 프로필 편집 칸. 작품 화면(base='style')과 라이브러리 화면(base='profile', root='lib')이 같이 쓴다. */
function profileFields(base, root) {
  const o = (x = {}) => (root ? { ...x, root } : x);
  const prof = getPath(bindRoot(root), base);
  const act = root ? 'libRemovePassage' : 'removePassage';
  const passages = prof.sample_passages.map((_, i) => `<div class="row" style="align-items:flex-start;flex-wrap:nowrap">
      <div style="flex:1">${input(`대표 문단 ${i + 1}`, `${base}.sample_passages.${i}`, o({ rows: 3 }))}</div>
      <button class="btn icon-btn danger" style="margin-top:26px" data-action="${act}" data-arg="${i}" aria-label="대표 문단 ${i + 1} 삭제">✕</button></div>`).join('');
  prof.markers = prof.markers || [];
  const markers = prof.markers.map((_, i) => `<div class="row" style="align-items:flex-start;flex-wrap:nowrap">
      <div style="flex:1">${input(`표지 ${i + 1}`, `${base}.markers.${i}.text`, o({ placeholder: '원문에 적힌 그대로, 예: 것이었다' }))}</div>
      <div style="flex:2">${input('쓰임', `${base}.markers.${i}.note`, o())}</div>
      <div style="width:110px">${input('1,000자당', `${base}.markers.${i}.per_1k`, o({ kind: 'float' }))}</div>
      <button class="btn icon-btn danger" style="margin-top:26px" data-action="${root ? 'libRemoveMarker' : 'removeMarker'}" data-arg="${i}" aria-label="표지 ${i + 1} 삭제">✕</button></div>`).join('');
  const f = (label, key, x) => input(label, `${base}.${key}`, o(x));
  return `<div class="grid-2">
      ${f('시점', 'narration_pov')}${f('시제', 'tense')}
      ${f('문장 리듬', 'sentence_rhythm', { rows: 2 })}${f('묘사 밀도', 'description_density', { rows: 2 })}
      ${f('대사 비율', 'dialogue_ratio')}${f('대사 방식', 'dialogue_style')}
      ${f('내면 독백', 'inner_monologue')}${f('전개 속도', 'pacing')}
      ${f('장면 전환', 'scene_transition')}${f('어휘', 'vocabulary')}
    </div>
    <div class="grid-2">
      <div class="note ok">${f('지킬 것', 'dos', { kind: 'list', rows: 4 })}</div>
      <div class="note err">${f('피할 것', 'donts', { kind: 'list', rows: 4 })}</div>
    </div>
    ${f('금지 표현', 'banned_phrases', { kind: 'list', rows: 2, placeholder: '본문에 나오면 경고할 표현, 한 줄에 하나씩' })}
    <div class="between"><h3>문체 표지 <span class="small" style="font-weight:400">어미, 조사, 말버릇과 원문 빈도. 넘치거나 빠지면 경고</span></h3><button class="btn small" data-action="${root ? 'libAddMarker' : 'addMarker'}">+ 표지</button></div>
    ${markers || '<div class="small">아직 없어요. 문체 분석을 하면 원문에서 골라 빈도를 셉니다.</div>'}
    ${deviceFields(base, root)}
    <div class="between"><h3>대표 문단 <span class="small" style="font-weight:400">본문 생성 때 그대로 보여줄 원문 예시, 2~4개</span></h3><button class="btn small" data-action="${root ? 'libAddPassage' : 'addPassage'}">+ 문단</button></div>
    ${passages || '<div class="small">아직 없어요. 문체 분석을 하면 원문에서 골라 넣습니다.</div>'}`;
}

/** 작품 문체 화면 위쪽: 라이브러리에서 가져오기, 라이브러리에 저장하기 */
function styleLibraryCard() {
  const libs = S.libs || [];
  const l = S.styleLink || { state: 'none' };
  const opts = libs.map((x) => `<option value="${esc(x.id)}"${x.id === l.id ? ' selected' : ''}>${esc(x.name)}${x.source ? ` · ${esc(x.source)}` : ''}</option>`).join('');
  const status = {
    none: '<span class="small">이 작품에서 직접 만든 문체예요.</span>',
    missing: '<span class="small">가져온 라이브러리 항목이 지워졌어요. 작품에 복사된 문체는 그대로 씁니다.</span>',
    same: `<span class="chip finalized">라이브러리와 같음</span> <a href="#/styles/${esc(l.id)}">${esc(l.name)}</a> <span class="small">${l.version}번 버전</span>`,
    changed: `<span class="chip written">라이브러리와 다름</span> <a href="#/styles/${esc(l.id)}">${esc(l.name)}</a> <span class="small">${l.applied && l.version > l.applied ? `이 작품은 ${l.applied}번 버전, 라이브러리는 ${l.version}번 버전이에요` : '이 작품에서 고쳤거나 라이브러리가 바뀌었어요'}</span>`,
  }[l.state] || '';
  const linkBtns = l.state === 'changed'
    ? '<button class="btn small" data-action="pushStyle">라이브러리 새 버전으로 올리기</button><button class="btn small" data-action="pullStyle">라이브러리 버전으로 되돌리기</button>'
    : '';
  return `<section class="card tight">
      <div class="between"><h2>문체 라이브러리</h2><a class="small" href="#/styles">라이브러리 열기</a></div>
      <div class="row">${status}</div>
      <div class="row" style="flex-wrap:nowrap">
        ${libs.length
          ? `<select id="style-pick" aria-label="라이브러리 문체" style="flex:1"><option value="">라이브러리에서 고르기</option>${opts}</select><button class="btn small" style="flex:none" data-action="useLibStyle">적용</button>`
          : '<span class="small" style="flex:1">라이브러리가 비어 있어요. 이 작품의 문체를 저장해 두면 다른 작품에서 다시 쓸 수 있어요.</span>'}
      </div>
      <div class="row">${linkBtns}<button class="btn small" data-action="keepStyle">이 문체를 라이브러리에 새로 저장</button></div>
    </section>`;
}

function viewStyle() {
  return `${header('2단계', '문체 레퍼런스', '닮고 싶은 소설 문단을 붙여 넣으면 문체 규칙을 뽑습니다. 규칙과 원문 예시가 매 화 본문 생성에 함께 들어갑니다. 라이브러리에 저장한 문체를 그대로 가져올 수도 있어요.', `<a class="btn primary" href="${base()}/arc">기승전결로</a>`)}
    <div class="cols">
      <div class="col">
        ${styleLibraryCard()}
        ${learnCard()}
        <section class="card">
          <div class="between"><h2>예시 원문</h2><span class="small"><span id="sample-count">${S.styleSample.length.toLocaleString()}</span>자 · 2,000자 이상 권장</span></div>
          <label for="sample" class="small">소설 본문을 붙여 넣으세요. 원문은 작품에 저장되지 않고 고른 대표 문단만 남습니다. 라이브러리에 저장하면 원문도 라이브러리에 함께 보관합니다.</label>
          <textarea id="sample" rows="16" data-local="styleSample" oninput="document.getElementById('sample-count').textContent=this.value.length.toLocaleString()" style="font-family:var(--serif);font-size:15px;line-height:1.9">${esc(S.styleSample)}</textarea>
          <div><button class="btn dark" data-action="analyzeStyle">문체 분석</button></div>
          <div class="note plain">원문은 문체 분석과 예시 문단으로만 쓰입니다. 내용이나 인물은 작품에 가져오지 않습니다.</div>
        </section>
      </div>
      <section class="card col wide">
        <div class="between"><h2>스타일 프로필</h2><span class="small">모든 칸은 직접 고칠 수 있어요</span></div>
        ${profileFields('style')}
      </section>
    </div>`;
}

// ----- 문체 라이브러리 -----

function fmtDate(iso) {
  return iso ? iso.slice(0, 10).replace(/-/g, '.') : '';
}

function viewLibrary() {
  const list = S.libs || [];
  const cards = list.map((x) => `<article class="card tight">
      <div class="between"><h3><a href="#/styles/${esc(x.id)}" style="color:inherit;text-decoration:none">${esc(x.name)}</a></h3><span class="small">${fmtDate(x.updated_at)}</span></div>
      ${x.source ? `<div class="small">${esc(x.source)}</div>` : ''}
      <div class="row">
        ${x.narration_pov ? `<span class="chip">${esc(x.narration_pov)}</span>` : ''}${x.tense ? `<span class="chip">${esc(x.tense)}</span>` : ''}
        <span class="chip">대표 문단 ${x.passages}</span><span class="chip">규칙 ${x.rules}</span>
        ${x.sample_chars ? `<span class="chip">원문 ${x.sample_chars.toLocaleString()}자</span>` : ''}
      </div>
      ${x.notes ? `<div class="small" style="white-space:pre-line">${esc(x.notes)}</div>` : ''}
      <div class="small">${x.used_by.length ? `쓰는 작품: ${x.used_by.map((n) => `<a href="#/p/${enc(n)}/style">${esc(n)}</a>`).join(', ')}` : '아직 쓰는 작품이 없어요'}</div>
      <div class="row"><a class="btn small" href="#/styles/${esc(x.id)}">열기</a><button class="btn small" data-action="libDuplicate" data-arg="${esc(x.id)}">복제</button><button class="btn small danger" data-action="libDelete" data-arg="${esc(x.id)}">삭제</button></div>
    </article>`).join('');
  return `${header('Canon', '문체 라이브러리', '붙여 넣은 원문에서 뽑은 문체를 작품과 따로 모아 둡니다. 작품에 적용하면 그 시점의 문체가 작품에 복사되고, 라이브러리를 고쳐도 쓰고 있는 작품은 다시 적용하기 전까지 그대로예요.', '<a class="btn" href="#/">작품 목록</a><a class="btn primary" href="#/styles/new">+ 새 문체</a>')}
    ${list.length ? `<div class="grid-auto">${cards}</div>` : `<div class="card empty"><div>아직 저장한 문체가 없어요.</div><div class="small">새 문체를 만들거나, 작품의 문체 레퍼런스 화면에서 '라이브러리에 새로 저장'을 누르세요.</div><a class="btn primary" href="#/styles/new">+ 새 문체</a></div>`}`;
}

function baselineRows(b) {
  if (!b) return '<div class="small">원문을 넣고 저장하면 문장 길이, 대사 비율 같은 기준 지표를 잽니다. 본문을 쓴 뒤 문체가 얼마나 벗어났는지 비교하는 기준이 됩니다.</div>';
  const pct = (v) => (v == null ? '–' : `${Math.round(v * 100)}%`);
  const rows = [
    ['문장 평균 길이', `${b.sentence_len_mean.toFixed(1)}자`],
    ['문장 길이 변화폭', b.sentence_len_cv.toFixed(2)],
    ['문단 평균 길이', `${Math.round(b.paragraph_len_mean)}자`],
    ['대사 비율', pct(b.dialogue_ratio)],
    ['과거형 비율', pct(b.past_tense_ratio)],
    ['어휘 다양도', b.mattr == null ? '–' : b.mattr.toFixed(2)],
    ['쉼표 문장 비율', pct(b.comma_sentence_ratio)],
  ];
  return `<dl class="metric-list">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>`;
}

function viewLibEntry() {
  const e = S.lib;
  const isNew = !e.id;
  const used = e.used_by || [];
  const others = (S.projects || []).filter((x) => !used.includes(x.name));
  const right = `<a class="btn" href="#/styles">목록으로</a>${isNew ? '' : `<button class="btn" data-action="libDuplicate" data-arg="${esc(e.id)}">복제</button><button class="btn danger" data-action="libDelete" data-arg="${esc(e.id)}">삭제</button><button class="btn" data-action="libRevert">저장 전으로</button>`}<button class="btn primary" data-action="libSave">저장</button>`;
  const apply = isNew ? '' : `<section class="card tight">
      <h2>작품에 적용</h2>
      <div class="small">${used.length ? `쓰는 작품: ${used.map((n) => `<a href="#/p/${enc(n)}/style">${esc(n)}</a>`).join(', ')}` : '아직 쓰는 작품이 없어요.'}</div>
      ${used.length ? '<div class="small">여기서 고친 내용은 작품의 문체 화면에서 \'라이브러리 버전으로 되돌리기\'를 눌러야 그 작품에 들어갑니다.</div>' : ''}
      ${(S.projects || []).length ? `<div class="row" style="flex-wrap:nowrap"><select id="lib-target" aria-label="적용할 작품" style="flex:1"><option value="">작품 고르기</option>${[...others, ...(S.projects || []).filter((x) => used.includes(x.name))].map((x) => `<option value="${esc(x.name)}">${esc(x.title || x.name)}${used.includes(x.name) ? ' (다시 적용)' : ''}</option>`).join('')}</select><button class="btn small" style="flex:none" data-action="libApplyTo">적용</button></div>` : ''}
    </section>`;
  return `${header('문체 라이브러리', isNew ? '새 문체' : e.name || '이름 없음', isNew ? '원문을 붙여 넣고 분석하거나, 프로필을 직접 채운 뒤 저장하세요.' : `만든 날 ${fmtDate(e.created_at)} · 고친 날 ${fmtDate(e.updated_at)}`, right)}
    <div class="cols">
      <div class="col">
        <section class="card">
          ${input('이름', 'name', { root: 'lib', placeholder: '예: 건조한 1인칭 하드보일드' })}
          ${input('출처', 'source', { root: 'lib', hint: '작가, 작품 등 메모', placeholder: '예: 직접 쓴 단편 「등대」' })}
          ${input('메모', 'notes', { root: 'lib', rows: 2, placeholder: '어떤 작품에 어울리는지 등' })}
        </section>
        <section class="card">
          <div class="between"><h2>원문</h2><span class="small"><span id="lib-sample-count">${(e.sample || '').length.toLocaleString()}</span>자 · 2,000자 이상 권장</span></div>
          ${input('분석할 소설 본문', 'sample', { root: 'lib', rows: 14, style: 'font-family:var(--serif);font-size:15px;line-height:1.9', hint: '이 컴퓨터의 라이브러리 폴더에만 저장됩니다' })}
          <div><button class="btn dark" data-action="libAnalyze">문체 분석</button></div>
        </section>
        <section class="card tight"><h2>기준 지표</h2>${baselineRows(e.baseline)}</section>
        ${apply}
        ${isNew ? '' : versionsCard()}
      </div>
      <section class="card col wide">
        <div class="between"><h2>스타일 프로필</h2><span class="small">모든 칸은 직접 고칠 수 있어요</span></div>
        ${profileFields('profile', 'lib')}
      </section>
    </div>`;
}

// ----- 3. 기승전결 · 플롯 -----

// ----- 서술 시점: 화 플롯 → 구간 → 아크 순서로 찾고, 비면 작품 기본 (prompts.pov_of 와 같은 규칙) -----

const POV_MODES = ['1인칭', '3인칭 제한', '3인칭 전지'];

function povText(n) {
  const e = ep(n);
  if (e && (e.plot.pov || e.plot.pov_mode)) {
    return [e.plot.pov ? charName(e.plot.pov) : '', e.plot.pov_mode || ''].filter(Boolean).join(' · ');
  }
  const act = actOf(n);
  if (act && (act.pov || '').trim()) return act.pov.trim();
  const arc = serial() ? arcOf(n) : null;
  return arc && (arc.pov || '').trim() ? arc.pov.trim() : '';
}

function povBadge(e) {
  if (!e.plot.pov && !e.plot.pov_mode) return '';
  return `<span class="line-badge pov-badge" style="--lc:var(--text-2)"><i aria-hidden="true"></i>시점 · ${esc(povText(e.plot.number))}</span>`;
}

/** 플롯 편집기의 시점 칸. 비우면 구간 · 아크 시점, 그것도 없으면 작품 기본 시점 */
function povField(e, locked) {
  const n = e.plot.number;
  const b = `episodes.${epIndex(n)}.plot`;
  const plan = (() => { const act = actOf(n); const arc = serial() ? arcOf(n) : null; return (act && act.pov) || (arc && arc.pov) || ''; })();
  const fallback = plan ? `구간 시점 (${plan})` : `작품 기본 (${P().style.narration_pov || '정하지 않음'})`;
  const opts = [['', fallback], ...P().characters.map((c) => [c.id, c.name || c.id])]
    .map(([v, l]) => `<option value="${esc(v)}"${(e.plot.pov || '') === v ? ' selected' : ''}>${esc(l)}</option>`).join('');
  return `<div class="grid-2">
      <div class="field"><label for="pov-ep-${n}">시점 인물 <span class="hint">이 화를 누구 눈으로</span></label>
        <select id="pov-ep-${n}" data-bind="${b}.pov" data-kind="text"${locked ? ' disabled' : ''}>${opts}</select></div>
      ${input('서술 방식', b + '.pov_mode', { readonly: locked, list: 'pov-modes', placeholder: e.plot.pov ? (P().style.narration_pov || '1인칭') : '비우면 그대로' })}
    </div><datalist id="pov-modes">${POV_MODES.map((m) => `<option value="${m}"></option>`).join('')}</datalist>`;
}

document.addEventListener('change', (e) => {  // 시점 인물을 바꾸면 화 카드 표시도 바로 바꾼다
  if (e.target.id && e.target.id.startsWith('pov-ep-')) render();
});

function epCard(e, sel) {
  return `<button type="button" class="ep-card ${e.status}${sel && sel.plot.number === e.plot.number ? ' sel' : ''}" data-action="selectEp" data-arg="${e.plot.number}" aria-label="${e.plot.number}화 ${esc(e.plot.title)} 플롯 열기">
      <span class="ep-top"><strong>${e.plot.number}화</strong><span class="chip ${e.status}">${STATUS[e.status]}</span></span>
      <span class="t">${esc(e.plot.title) || '제목 없음'}</span>${lineBadge(e)}${povBadge(e)}<span class="s">${esc(e.plot.summary)}</span></button>`;
}

/** 기승전결 네 칸 보드. 단편은 작품 전체 구조, 장편은 고른 아크의 구조를 그린다 */
function actBoard(acts, eps, sel) {
  const slot = (n) => `<div class="ep-slot" aria-hidden="true">${n}화</div>`;
  // 4화보다 짧은 작품은 이웃 구간이 한 화를 함께 쓴다. 그 화 카드는 앞 구간에만 두고 뒤 구간에는 안내만 둔다
  const owner = (n) => acts.findIndex((x) => x.start_ep <= n && n <= x.end_ep);
  const cols = acts.map((a, i) => {
    const count = Math.max(0, a.end_ep - a.start_ep + 1);
    const all = Array.from({ length: Math.min(count, 60) }, (_, k) => a.start_ep + k);
    const nums = all.filter((n) => owner(n) === i);
    const shared = all.filter((n) => owner(n) !== i);
    const inAct = eps.filter((e) => nums.includes(e.plot.number));
    const share = shared.length ? `<div class="ep-slot shared">${shared.map((n) => `${n}화`).join(', ')}는 ${acts[owner(shared[0])].name} 구간과 한 화에 함께 들어가요</div>` : '';
    const block = (label, text) => `<div class="act-block"><span class="act-label">${label}</span><p class="${text ? '' : 'empty-text'}">${esc(text) || '비어 있음'}</p></div>`;
    return `<section class="act-col" aria-label="${a.name} 구간">
        <div class="act-head ${actClass(a.name)}${S.selAct === i ? ' sel' : ''}">
          <div class="between"><strong>${a.name}</strong><span class="act-meta">${a.start_ep}–${a.end_ep}화 · ${count}화</span></div>
          ${block('구간 목표', a.goal)}${block('전환점', a.key_turn)}${a.pov ? block('서술 시점', a.pov) : ''}
          <button type="button" class="btn small act-edit" data-action="selectAct" data-arg="${i}">구간 고치기</button>
        </div>
        <div class="act-eps"><span class="act-label">화별 플롯 ${inAct.length ? `${inAct.length}화` : ''}</span>
          ${share}${inAct.length ? inAct.map((e) => epCard(e, sel)).join('') : nums.map(slot).join('')}</div>
      </section>`;
  }).join('');
  return `<div class="board">${cols}</div>`;
}

function drawerHtml(panel) {
  return panel ? `<aside class="drawer card" role="dialog" aria-label="편집">
      <button type="button" class="btn icon-btn drawer-close" data-action="closePanel" aria-label="닫기">✕</button>${panel}</aside>` : '';
}

function viewArc() {
  const p = P();
  const eps = p.episodes;
  if (S.selEp && !ep(S.selEp)) S.selEp = null;
  if (S.selAct != null && !p.arc[S.selAct]) S.selAct = null;
  const sel = S.selEp ? ep(S.selEp) : null;

  let board;
  if (!p.arc.length) {
    board = `<div class="card empty"><p>아직 기승전결 구조가 없어요.</p>${((b) => `<button class="btn primary" data-action="planArc"${b.attr}>${b.label}</button>`)(jobBtn('arc', null, 'AI 로 구조 만들기'))}</div>`;
  } else {
    board = `<div class="board-wrap">${eps.length ? '' : '<div class="note info">구간을 확인한 뒤 <strong>화별 플롯 초안 만들기</strong>를 누르면 각 구간에 화 카드가 채워집니다.</div>'}${actBoard(p.arc, eps, sel)}</div>`;
  }

  let panel = '';
  if (sel) panel = plotEditor(sel);
  else if (S.selAct != null) panel = actEditor(S.selAct);
  const drawer = drawerHtml(panel);

  const drafts = eps.filter((e) => e.status === 'draft').length;
  const right = p.arc.length
    ? `${((b) => `<button class="btn" data-action="planArc"${b.attr}>${b.label}</button>`)(jobBtn('arc', null, '구조 다시 제안'))}${((b) => `<button class="btn" data-action="draftPlots"${b.attr}>${b.label}</button>`)(jobBtn('plots', null, eps.length ? '초안 다시 만들기 (확정 화 제외)' : '화별 플롯 초안 만들기'))}${drafts ? `<button class="btn primary" data-action="confirmAll">초안 ${drafts}화 모두 확정</button>` : ''}`
    : '';
  const tools = chatButton() + right + `<a class="btn" href="${base()}/convert">장편으로 전환</a>`;
  return `${header('3단계', '기승전결 · 화별 플롯', '구간 목표를 확인하고, 화 카드를 눌러 플롯을 다듬은 뒤 확정하세요. 확정된 화만 본문을 쓸 수 있고, 초안을 다시 만들어도 확정된 화는 그대로입니다.', tools)}
    ${board}${drawer}${chatPanel('plot')}`;
}

function actEditor(i) {
  const k = serial() ? P().story_arcs.findIndex((x) => x.number === S.selArc) : -1;
  const a = k >= 0 ? P().story_arcs[k].acts[i] : P().arc[i];
  if (!a) return '';
  const b = k >= 0 ? `story_arcs.${k}.acts.${i}` : `arc.${i}`;
  const inAct = P().episodes.filter((e) => e.plot.number >= a.start_ep && e.plot.number <= a.end_ep);
  return `<div class="between"><h2>${k >= 0 ? `아크 ${S.selArc} · ` : ''}${a.name} 구간</h2><span class="chip ${actClass(a.name)}">${a.start_ep}–${a.end_ep}화</span></div>
    <div class="grid-2">${input('시작 화', b + '.start_ep', { type: 'number', min: 1 })}${input('끝 화', b + '.end_ep', { type: 'number', min: 1 })}</div>
    <div class="small">${k >= 0 ? '아크 안 기승전결 네 구간이 아크 첫 화부터 끝 화까지 빈틈없이 이어져야 저장됩니다.' : '기승전결 네 구간이 1화부터 마지막 화까지 빈틈없이 이어져야 저장됩니다.'}</div>
    ${input('구간 목표', b + '.goal', { rows: 5, autogrow: true, hint: '이 구간이 끝날 때 이야기가 어디까지 와 있어야 하나' })}
    ${input('전환점', b + '.key_turn', { rows: 4, autogrow: true, hint: '이 구간을 다음으로 넘기는 사건' })}
    ${input('서술 시점', b + '.pov', { placeholder: `비우면 작품 기본 (${P().style.narration_pov || '정하지 않음'})`, hint: '예: 도현 1인칭. 화별 플롯을 만들 때 AI 가 이 시점을 화마다 채워요' })}
    ${inAct.length ? `<div class="field"><span class="label">이 구간의 화</span><div class="row">${inAct.map((e) => `<button type="button" class="btn small" data-action="selectEp" data-arg="${e.plot.number}">${e.plot.number}화</button>`).join('')}</div></div>` : ''}`;
}

function plotEditor(e) {
  const n = e.plot.number;
  const i = epIndex(n);
  const b = `episodes.${i}.plot`;
  const busy = jobOwns(n);
  const locked = e.status === 'written' || e.status === 'finalized' || busy;
  const ro = { readonly: locked };
  const cast = P().characters.map((c) => `<label class="row" style="font-size:13px;gap:6px"><input type="checkbox" value="${esc(c.id)}" data-cast-ep="${n}"${e.plot.characters.includes(c.id) ? ' checked' : ''}${locked ? ' disabled' : ''}>${esc(c.name || c.id)}</label>`).join('');
  const act = actOf(n);
  const arc = serial() ? arcOf(n) : null;
  return `<div class="between"><h2>${n}화 플롯</h2><span class="chip ${e.status}">${STATUS[e.status]}</span></div>
    ${arc ? `<div class="note plain"><strong>아크 ${arc.number} ${esc(arc.title)}</strong> · ${esc(arc.goal)}</div>` : ''}
    ${act ? `<div class="note info"><strong>${act.name} 구간 목표</strong> · ${esc(act.goal)}</div>` : ''}
    ${busy ? '<div class="note warn">AI 가 이 구간의 초안을 새로 만드는 중이라 끝날 때까지 고칠 수 없어요.</div>' : locked ? '<div class="note plain">본문이 있는 화라 플롯을 고칠 수 없어요.</div>' : ''}
    ${input('제목', b + '.title', ro)}
    ${input('요약', b + '.summary', { ...ro, rows: 3, autogrow: true })}
    ${input('사건 순서', b + '.events', { ...ro, kind: 'list', rows: 5, autogrow: true })}
    <div class="field"><span class="label">등장 인물</span><div class="row">${cast}</div></div>
    ${lineField(e)}
    ${povField(e, locked)}
    ${n <= 3 || e.plot.opening ? input('여는 장면', b + '.opening', { ...ro, hint: n <= 3 ? '초반 화는 첫 장면이 독자를 붙잡습니다' : '' }) : ''}
    ${input('감정 변화', b + '.emotional_shift', ro)}
    ${input('엔딩 훅', b + '.ending_hook', ro)}
    ${n <= 3 || e.plot.reader_question ? input('독자가 들고 갈 질문', b + '.reader_question', { ...ro, hint: n <= 3 ? '이 화를 읽고 다음 화를 누르게 하는 질문' : '' }) : ''}
    <div class="grid-2">${input('심을 복선', b + '.foreshadow_plant', { ...ro, kind: 'list', rows: 2 })}${input('회수할 복선 id', b + '.foreshadow_payoff', { ...ro, kind: 'list', rows: 2 })}</div>
    <div class="row drawer-actions">
      ${e.status === 'draft' ? `<button class="btn primary" style="flex:1" data-action="confirmEp" data-arg="${n}"${busy ? ' disabled' : ''}>${n}화 확정</button>` : ''}
      ${e.status === 'confirmed' ? `<button class="btn" style="flex:1" data-action="unconfirmEp" data-arg="${n}">초안으로 되돌리기</button><a class="btn primary" style="flex:1" href="${base()}/write/${n}">${n}화 쓰기</a>` : ''}
      ${locked ? `<a class="btn" style="flex:1" href="${base()}/write/${n}">본문 보기</a>` : ''}
    </div>
    ${openingPlotBlock(e)}`;
}

// ----- 3'. 장편 연재: 부 → 아크 → 화 -----

function arcFinished(a) {
  for (let n = a.start_ep; n <= a.end_ep; n++) if (!ep(n) || ep(n).status !== 'finalized') return false;
  return true;
}

function arcProgress(a) {
  const nums = a.end_ep - a.start_ep + 1;
  const inArc = P().episodes.filter((e) => e.plot.number >= a.start_ep && e.plot.number <= a.end_ep);
  return { nums, plotted: inArc.length, done: inArc.filter((e) => e.status === 'finalized').length, drafts: inArc.filter((e) => e.status === 'draft').length };
}

function viewSerial() {
  const p = P();
  const arcs = [...p.story_arcs].sort((a, b) => a.start_ep - b.start_ep);
  if (S.selEp && !ep(S.selEp)) S.selEp = null;
  if (S.selArc == null || (S.selArc !== 'next' && !arcs.some((a) => a.number === S.selArc))) {
    const cur = arcOf(currentEp());
    S.selArc = cur ? cur.number : arcs.length ? arcs[arcs.length - 1].number : 'next';
  }
  const arc = arcs.find((a) => a.number === S.selArc);
  if (S.selAct != null && !(arc && arc.acts[S.selAct])) S.selAct = null;
  const sel = S.selEp ? ep(S.selEp) : null;
  const planned = plannedUntil();
  const nextStart = planned + 1;

  // 부 구성
  const partCard = (x) => {
    const inPart = arcs.filter((a) => a.start_ep >= x.start_ep && a.start_ep <= x.end_ep);
    const done = p.episodes.filter((e) => e.status === 'finalized' && e.plot.number >= x.start_ep && e.plot.number <= x.end_ep).length;
    const finished = done === x.end_ep - x.start_ep + 1;
    const here = nextStart >= x.start_ep && nextStart <= x.end_ep;
    return `<button type="button" class="part-card${S.selPart === x.number ? ' sel' : ''}${here ? ' here' : ''}" data-action="selectPart" data-arg="${x.number}">
      <span class="between"><strong>${x.number}부 ${esc(x.title)}</strong><span class="small">${x.start_ep}–${x.end_ep}화</span></span>
      <span class="s">${esc(x.goal)}</span>
      <span class="row"><span class="chip">아크 ${inPart.length}개</span><span class="chip ${done ? 'finalized' : ''}">반영 ${done}/${x.end_ep - x.start_ep + 1}</span>${finished ? (x.summary ? '<span class="chip finalized">요약 있음</span>' : '<span class="chip written">요약 필요</span>') : ''}</span>
    </button>`;
  };
  const seriesDraft = S.seriesDraft ? `<div class="card proposal">
      <div class="between"><h3>AI 부 구성 제안 <span class="chip ai">반영 전</span></h3><div class="row"><button class="btn small" data-action="dropSeries">버리기</button><button class="btn small primary" data-action="applySeries">이 부 구성 반영</button></div></div>
      ${S.seriesDraft.parts.map((x, i) => `<div class="part-draft">
        <div class="grid-2">${input(`${x.number}부 제목`, `parts.${i}.title`, { root: 'seriesDraft' })}<div class="grid-2">${input('시작 화', `parts.${i}.start_ep`, { root: 'seriesDraft', type: 'number' })}${input('끝 화', `parts.${i}.end_ep`, { root: 'seriesDraft', type: 'number' })}</div></div>
        ${input('부 목표', `parts.${i}.goal`, { root: 'seriesDraft', rows: 2, autogrow: true })}
        ${input('아크 후보', `parts.${i}.arc_ideas`, { root: 'seriesDraft', kind: 'list', rows: 3, autogrow: true })}
      </div>`).join('')}
      <div class="small">부는 1화부터 ${p.meta.target_episodes}화까지 빈틈없이 이어져야 반영됩니다. 이미 기획한 아크가 새 부 경계를 넘으면 반영하지 않아요.</div>
    </div>` : '';
  const seriesBtn = ((b) => `<button class="btn small" data-action="planSeries"${b.attr}>${b.label}</button>`)(jobBtn('series', null, p.parts.length ? '부 구성 다시 제안' : 'AI 로 부 구성 만들기'));
  const series = `<section class="card">
      <div class="between"><h2>부 구성 <span class="small" style="font-weight:400">총 ${p.meta.target_episodes}화 · ${planned}화까지 아크 기획</span></h2>${seriesBtn}</div>
      ${p.parts.length ? `<div class="part-strip">${p.parts.map(partCard).join('')}</div>` : '<div class="small">무대와 판이 바뀌는 큰 단위(50~150화)예요. 없어도 아크를 이어 갈 수 있지만, 있으면 아크 기획이 부 목표를 따라갑니다.</div>'}
      ${seriesDraft}
    </section>`;

  // 아크 목록
  const pending = arcs.filter((a) => !a.summary && arcFinished(a));
  const arcChip = (a) => {
    const g = arcProgress(a);
    const state = g.done === g.nums ? (a.summary ? 'finalized' : 'written') : g.plotted === 0 ? '' : g.drafts ? 'draft' : 'confirmed';
    return `<button type="button" class="arc-chip${S.selArc === a.number ? ' sel' : ''}" data-action="selectArc" data-arg="${a.number}" aria-pressed="${S.selArc === a.number}">
      <strong>아크 ${a.number}</strong> <span>${a.start_ep}–${a.end_ep}화</span> <span class="chip ${state}">${g.done === g.nums ? (a.summary ? '완료' : '요약 필요') : g.plotted ? `반영 ${g.done}/${g.nums}` : '플롯 전'}</span></button>`;
  };
  const rail = `<section class="card">
      <div class="between"><h2>아크</h2><span class="small">아크 하나는 5~30화짜리 작은 이야기예요. 다음 아크의 플롯만 그때그때 만듭니다.</span></div>
      <div class="arc-rail">${arcs.map(arcChip).join('')}${planned < p.meta.target_episodes ? `<button type="button" class="arc-chip next${S.selArc === 'next' ? ' sel' : ''}" data-action="selectArc" data-arg="next">+ 다음 아크 <span>${nextStart}화부터</span></button>` : ''}</div>
      ${pending.length ? `<div class="note warn">끝난 아크의 요약이 필요해요: ${pending.map((a) => `<a href="#" data-action="selectArc" data-arg="${a.number}" style="color:inherit;font-weight:700">아크 ${a.number}</a>`).join(', ')}. 요약이 있어야 오래된 줄거리를 짧게 접어 넣을 수 있어요.</div>` : ''}
    </section>`;

  let body;
  if (S.selArc === 'next' || !arc) body = nextArcPanel(nextStart);
  else body = arcPanel(arc, sel);

  let panel = '';
  if (sel) panel = plotEditor(sel);
  else if (S.selAct != null) panel = actEditor(S.selAct);
  else if (S.editArc && arc) panel = arcEditor(arc);
  else if (S.selPart != null) panel = partEditor(S.selPart);

  const tools = chatButton() + (p.conversion ? `<a class="btn" href="${base()}/convert">단편에서 전환 · 되돌리기</a>` : '');
  return `${header('3단계', '부 · 아크 · 화별 플롯', '장편은 작품을 부와 아크로 나누고, 다음 아크 하나씩 기획해 그 아크의 플롯만 만듭니다. 끝난 아크는 요약으로 접혀서 몇백 화를 써도 프롬프트 크기가 일정해요.', tools)}
    ${series}${rail}${body}${drawerHtml(panel)}${chatPanel('plot')}`;
}

function nextArcPanel(start) {
  const p = P();
  if (start > p.meta.target_episodes) return `<div class="card empty"><p>총 ${p.meta.target_episodes}화까지 아크가 모두 있어요.</p><span class="small">더 쓰려면 작품 홈이나 설정에서 총 화수를 늘리고 부 구성을 고치세요.</span></div>`;
  const part = p.parts.find((x) => x.start_ep <= start && start <= x.end_ep);
  const old = p.foreshadows.filter((f) => f.status === 'open' && start - f.planted_ep > 50);
  const d = S.arcDraft;
  if (d) {
    const a = d.arc;
    return `<section class="card proposal">
      <div class="between"><h2>아크 ${a.number} 제안 <span class="chip ai">반영 전</span></h2><div class="row"><button class="btn small" data-action="dropArc">버리기</button><button class="btn small primary" data-action="applyArc">이 아크 반영</button></div></div>
      ${d.reply ? `<div class="note info">${esc(d.reply).replace(/\n/g, '<br>')}</div>` : ''}
      <div class="grid-2">${input('아크 제목', 'arc.title', { root: 'arcDraft' })}<div class="grid-2">${input('시작 화', 'arc.start_ep', { root: 'arcDraft', type: 'number', readonly: true })}${input('끝 화', 'arc.end_ep', { root: 'arcDraft', type: 'number' })}</div></div>
      ${input('아크 목표', 'arc.goal', { root: 'arcDraft', rows: 2, autogrow: true, hint: '아크가 끝날 때 바뀌어 있어야 하는 것' })}
      <div class="grid-2">${input('갈등', 'arc.conflict', { root: 'arcDraft', rows: 2, autogrow: true, hint: '주인공을 막는 문제나 상대' })}${input('보상 (사이다)', 'arc.payoff', { root: 'arcDraft', rows: 2, autogrow: true, hint: '클라이맥스에서 독자가 받는 것' })}</div>
      <div class="act-strip">${a.acts.map((x, i) => `<div class="act-head ${actClass(x.name)}"><div class="between"><strong>${x.name}</strong><span class="act-meta">${x.start_ep}–${x.end_ep}화</span></div>${input('구간 목표', `arc.acts.${i}.goal`, { root: 'arcDraft', rows: 3, autogrow: true })}</div>`).join('')}</div>
      ${input('서술 시점', 'arc.pov', { root: 'arcDraft', placeholder: `비우면 작품 기본 (${P().style.narration_pov || '정하지 않음'})` })}
      <div class="grid-2">${input('주요 인물 id', 'arc.cast', { root: 'arcDraft', kind: 'list', rows: 3 })}${input('회수할 복선 id', 'arc.payoffs', { root: 'arcDraft', kind: 'list', rows: 3 })}</div>
      ${d.new_characters.length ? `<div class="field"><span class="label">새 인물 (조연으로 들어와요. 주역으로 올리려면 설정 도우미에서 비중을 바꾸세요)</span>${d.new_characters.map((c) => `<div class="note plain"><strong>${esc(c.name)}</strong> <span class="small">${esc(c.id)} · ${esc(c.role)}</span><br>${esc(c.personality || c.goal)}<br><span class="small">말투: ${esc(c.speech_style)}</span></div>`).join('')}</div>` : ''}
      <div class="small">끝 화를 바꾸면 결 구간이 따라 늘거나 줄어요. 다른 구간 범위는 반영한 뒤 구간 고치기에서 바꿀 수 있어요.</div>
    </section>`;
  }
  const btn = jobBtn('nextarc', null, 'AI 로 다음 아크 제안');
  return `<section class="card">
    <div class="between"><h2>다음 아크 기획 <span class="small" style="font-weight:400">${start}화부터${part ? ` · ${part.number}부 ${esc(part.title)} (${part.end_ep}화까지)` : ''}</span></h2></div>
    ${part ? `<div class="note plain"><strong>${part.number}부 목표</strong> · ${esc(part.goal)}${part.arc_ideas.length ? `<br><span class="small">아크 후보: ${part.arc_ideas.map(esc).join(' / ')}</span>` : ''}</div>` : ''}
    ${old.length ? `<div class="note warn">50화 넘게 열린 복선이 ${old.length}개 있어요. 이번 아크에서 회수하거나 다시 떠올리도록 AI 에게 함께 보여 줍니다.</div>` : ''}
    <div class="grid-2">${input('아크 길이 (화)', 'length', { root: 'arcForm', type: 'number', min: 0, hint: '0 이면 AI 가 내용에 맞게 (보통 10~25화)' })}<div></div></div>
    ${input('이번 아크에 바라는 것 (선택)', 'note', { root: 'arcForm', rows: 3, autogrow: true, placeholder: '예: 학교 밖으로 무대를 넓히고, 라이벌과 처음 손잡게' })}
    <div class="row"><button class="btn primary" data-action="planNextArc"${btn.attr}>${btn.label}</button><span class="small">지금까지 실제로 쓴 줄거리(요약), 부 목표, 열린 복선을 보고 아크 하나를 제안해요. 반영 전에 고칠 수 있어요.</span></div>
  </section>`;
}

function arcPanel(a, sel) {
  const p = P();
  const k = p.story_arcs.indexOf(a);
  const g = arcProgress(a);
  const eps = p.episodes.filter((e) => e.plot.number >= a.start_ep && e.plot.number <= a.end_ep);
  const last = Math.max(...p.story_arcs.map((x) => x.start_ep)) === a.start_ep;
  const finished = arcFinished(a);
  const plotsBtn = jobBtn('plots', a.number, g.plotted ? '초안 다시 만들기 (확정 화 제외)' : '화별 플롯 초안 만들기');
  const names = (ids) => ids.map((id) => esc(charName(id))).join(', ');
  const r = S.recapDraft && S.recapDraft.kind === 'arc' && S.recapDraft.number === a.number ? S.recapDraft : null;
  let recap = '';
  if (finished) {
    const rb = jobBtn('recap_arc', a.number, a.summary ? 'AI 로 요약 다시 제안' : 'AI 로 요약 제안');
    recap = `<div class="recap">
      <div class="between"><h3>아크 요약 ${a.summary ? '<span class="chip finalized">있음</span>' : '<span class="chip written">필요</span>'}</h3><button class="btn small" data-action="recapArc" data-arg="${a.number}"${rb.attr}>${rb.label}</button></div>
      ${r ? `${input('AI 요약 제안 (고친 뒤 저장)', 'summary', { root: 'recap', rows: 6, autogrow: true })}<div class="row"><button class="btn small" data-action="dropRecap">버리기</button><button class="btn small primary" data-action="applyRecap">이 요약 저장</button></div>` : ''}
      ${input('저장된 요약', `story_arcs.${k}.summary`, { rows: 4, autogrow: true, hint: '앞으로 이 아크의 화별 요약 대신 프롬프트에 들어가요' })}
    </div>`;
  }
  const right = `<div class="row">
      <button class="btn small" data-action="editArc">아크 고치기</button>
      <button class="btn small" data-action="draftArcPlots" data-arg="${a.number}"${plotsBtn.attr}>${plotsBtn.label}</button>
      ${g.drafts ? `<button class="btn small primary" data-action="confirmAll" data-arg="${a.number}">초안 ${g.drafts}화 모두 확정</button>` : ''}
      ${last && !eps.some((e) => e.status !== 'draft') ? '<button class="btn small danger" data-action="removeLastArc">지우고 다시 기획</button>' : ''}
    </div>`;
  return `<section class="card">
      <div class="between"><h2>아크 ${a.number} ${esc(a.title)} <span class="small" style="font-weight:400">${a.start_ep}–${a.end_ep}화 · ${g.nums}화 · 반영 ${g.done}/${g.nums}</span></h2>${right}</div>
      <div class="arc-facts">
        <div><span class="act-label">아크 목표</span><p>${esc(a.goal) || '<span class="small">비어 있음</span>'}</p></div>
        <div><span class="act-label">갈등</span><p>${esc(a.conflict) || '<span class="small">비어 있음</span>'}</p></div>
        <div><span class="act-label">보상 (사이다)</span><p>${esc(a.payoff) || '<span class="small">비어 있음</span>'}</p></div>
      </div>
      <div class="small">${a.cast.length ? `주요 인물: ${names(a.cast)}` : ''}${a.payoffs.length ? ` · 회수할 복선: ${a.payoffs.map(esc).join(', ')}` : ''}</div>
      ${recap}
    </section>
    <div class="board-wrap">${g.plotted ? '' : '<div class="note info">구간을 확인한 뒤 <strong>화별 플롯 초안 만들기</strong>를 누르면 이 아크의 화 카드가 채워집니다.</div>'}${actBoard(a.acts, eps, sel)}</div>`;
}

function arcEditor(a) {
  const k = P().story_arcs.indexOf(a);
  const b = `story_arcs.${k}`;
  return `<div class="between"><h2>아크 ${a.number} 고치기</h2><span class="chip">${a.start_ep}–${a.end_ep}화</span></div>
    ${input('제목', b + '.title')}
    <div class="grid-2">${input('시작 화', b + '.start_ep', { type: 'number', readonly: true })}${input('끝 화', b + '.end_ep', { type: 'number', min: a.start_ep })}</div>
    <div class="small">끝 화를 바꾸면 결 구간의 끝 화와 다음 아크의 시작 화도 맞춰야 저장됩니다. 길이를 크게 바꾸려면 마지막 아크를 지우고 다시 기획하는 편이 쉬워요.</div>
    ${input('아크 목표', b + '.goal', { rows: 3, autogrow: true })}
    ${input('갈등', b + '.conflict', { rows: 2, autogrow: true })}
    ${input('보상 (사이다)', b + '.payoff', { rows: 2, autogrow: true })}
    ${input('서술 시점', b + '.pov', { placeholder: `비우면 작품 기본 (${P().style.narration_pov || '정하지 않음'})`, hint: '이 아크를 누구 시점으로 쓸지. 구간마다 다르면 구간 고치기에서' })}
    ${input('주요 인물 id', b + '.cast', { kind: 'list', rows: 3 })}
    ${input('회수할 복선 id', b + '.payoffs', { kind: 'list', rows: 2 })}`;
}

function partEditor(number) {
  const p = P();
  const i = p.parts.findIndex((x) => x.number === number);
  if (i < 0) return '';
  const x = p.parts[i];
  const b = `parts.${i}`;
  const done = p.episodes.filter((e) => e.status === 'finalized' && e.plot.number >= x.start_ep && e.plot.number <= x.end_ep).length;
  const finished = done === x.end_ep - x.start_ep + 1;
  const r = S.recapDraft && S.recapDraft.kind === 'part' && S.recapDraft.number === number ? S.recapDraft : null;
  const rb = jobBtn('recap_part', number, x.summary ? 'AI 로 요약 다시 제안' : 'AI 로 요약 제안');
  return `<div class="between"><h2>${x.number}부 고치기</h2><span class="chip">${x.start_ep}–${x.end_ep}화</span></div>
    ${input('제목', b + '.title')}
    <div class="grid-2">${input('시작 화', b + '.start_ep', { type: 'number' })}${input('끝 화', b + '.end_ep', { type: 'number' })}</div>
    <div class="small">부는 1화부터 마지막 화까지 빈틈없이 이어져야 저장됩니다.</div>
    ${input('부 목표', b + '.goal', { rows: 3, autogrow: true })}
    ${input('전환점', b + '.key_turn', { rows: 2, autogrow: true })}
    ${input('아크 후보', b + '.arc_ideas', { kind: 'list', rows: 5, autogrow: true, hint: '다음 아크를 기획할 때 참고해요' })}
    ${finished ? `<div class="between"><span class="label">부 요약</span><button class="btn small" data-action="recapPart" data-arg="${number}"${rb.attr}>${rb.label}</button></div>
      ${r ? `${input('AI 요약 제안 (고친 뒤 저장)', 'summary', { root: 'recap', rows: 6, autogrow: true })}<div class="row"><button class="btn small" data-action="dropRecap">버리기</button><button class="btn small primary" data-action="applyRecap">이 요약 저장</button></div>` : ''}` : '<div class="small">부의 모든 화가 반영되면 요약을 만들 수 있어요.</div>'}
    ${input('저장된 요약', b + '.summary', { rows: 4, autogrow: true })}`;
}

// ----- 4. 집필 -----

function epNav(page, n) {
  const nums = P().episodes.map((e) => e.plot.number);
  const prev = nums.filter((x) => x < n).pop();
  const next = nums.find((x) => x > n);
  const arrow = (to, label, d) => to ? `<a class="btn icon-btn" href="${base()}/${page}/${to}" aria-label="${label}"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="${d}"></path></svg></a>` : `<span class="btn icon-btn" aria-hidden="true" style="opacity:.35">·</span>`;
  return `<nav class="row" aria-label="회차 이동" style="gap:4px">${arrow(prev, '이전 화', 'M10 3 5 8l5 5')}${arrow(next, '다음 화', 'm6 3 5 5-5 5')}</nav>`;
}

function noEpisode() {
  return `<div class="card empty"><p>아직 화별 플롯이 없어요.</p><a class="btn primary" href="${base()}/arc">기승전결 · 플롯 만들기</a></div>`;
}

function viewWrite(n) {
  const e = ep(n);
  if (!e) return header('4단계', '집필', '') + noEpisode();
  const act = actOf(n);
  const blocked = P().episodes.filter((x) => x.plot.number < n && x.status !== 'finalized').map((x) => x.plot.number);
  const draft = S.textDraft[n];
  const text = draft ?? e.text;
  const editable = e.status === 'confirmed' || e.status === 'written';
  const isApi = S.mode === 'api';

  let center;
  if (e.status === 'draft') {
    center = `<div class="empty"><p>${n}화 플롯이 아직 초안이에요. 확정해야 쓸 수 있습니다.</p><a class="btn primary" href="${base()}/arc">플롯 확정하러 가기</a></div>`;
  } else if (!e.text && draft === undefined) {
    center = `<div class="empty">
      ${blocked.length ? `<div class="note warn">이전 화(${blocked.join(', ')}화)의 상태 반영이 끝나야 쓸 수 있어요. 인물 상태가 꼬이지 않게 하는 규칙입니다.</div>` : ''}
      ${isApi ? `<p>확정된 플롯과 지금까지의 데이터로 ${n}화를 씁니다.</p>${((b) => `<button class="btn primary" data-action="writeEp" data-arg="${n}"${blocked.length ? ' disabled' : b.attr}>${b.label}</button>`)(jobBtn('write', n, `${n}화 본문 생성`))}${jobFor('write', n) ? '<div class="small">다른 화면으로 옮겨 가도 계속 씁니다. 끝나면 알려 드려요.</div>' : ''}`
        : `<p>작업지시서를 채팅 앱에 붙여 넣고, 받은 본문을 가져오세요.</p><a class="btn primary" href="${base()}/brief/${n}">작업지시서 열기</a>`}
      <button class="btn" data-action="startManual" data-arg="${n}">직접 쓰기</button>
    </div>`;
  } else {
    center = `<div class="prose">${editable
      ? `<textarea aria-label="${n}화 본문" data-draft="${n}" placeholder="여기에 본문을 쓰세요">${esc(text)}</textarea>`
      : `<div class="read" data-read="${n}">${esc(text)}</div>`}</div>`;
  }

  const ctx = S.context ? `<ol class="panel-list">${S.context.map((c) => `<li><span>${esc(c.title)}</span><span class="small">${c.chars.toLocaleString()}자</span></li>`).join('')}</ol>
      <div class="small">합계 ${S.context.reduce((s, c) => s + c.chars, 0).toLocaleString()}자. 이전 본문 전체 대신 이 데이터만 매번 같은 순서로 넣습니다.</div>` : '<div class="small">플롯을 확정하면 보입니다.</div>';

  const right = `${e.status !== 'finalized' ? `<div class="seg" role="group" aria-label="생성 방식"><button type="button" aria-pressed="${isApi}" data-action="setMode" data-arg="api">Gemini API</button><button type="button" aria-pressed="${!isApi}" data-action="setMode" data-arg="brief">채팅 앱 작업지시서</button></div>` : ''}
    ${e.text && editable ? chatButton(`text:${n}`) : ''}
    ${e.text && editable && isApi ? `${((b) => `<button class="btn" data-action="writeEp" data-arg="${n}"${b.attr}>${b.label}</button>`)(jobBtn('write', n, '다시 생성'))}` : ''}
    ${editable && !isApi ? `<a class="btn" href="${base()}/brief/${n}">작업지시서</a>` : ''}
    ${e.status === 'written' ? `<a class="btn primary" href="${base()}/review/${n}">상태 정리로</a>` : ''}`;

  return `<header class="page-head"><div class="row" style="gap:12px">${epNav('write', n)}<div class="lead" style="gap:2px"><div class="eyebrow">${act ? act.name + ' 구간 · ' : ''}${n} / ${P().meta.target_episodes}화</div><h1 style="font-size:24px">${n}화 ${esc(e.plot.title)}</h1></div><span class="chip ${e.status}">${STATUS[e.status]}</span>${e.auto ? '<span class="chip ai">자동 반영</span>' : ''}</div><div class="row">${right}</div></header>
    ${e.auto ? `<div class="note info">이 화는 자동 집필이 검토 없이 반영했어요. 읽어 보고 문제가 있으면 <a href="${base()}/auto">자동 집필</a>에서 이 화부터 되돌릴 수 있어요.</div>` : ''}
    ${rebuildNote(n)}
    <div class="cols" style="gap:16px">
      <aside class="card tight" style="flex:1 1 260px;min-width:0" aria-label="이번 화 플롯">
        <h3>이번 화 플롯</h3>
        ${act ? `<div class="note info"><strong>구간 목표</strong> · ${esc(act.goal)}</div>` : ''}
        <p style="font-size:13px;line-height:1.6;color:var(--text-2)">${esc(e.plot.summary)}</p>
        <div class="field"><span class="small">사건</span><ol style="padding-left:20px;display:flex;flex-direction:column;gap:6px;font-size:13px;line-height:1.5">${e.plot.events.map((x) => `<li>${esc(x)}</li>`).join('')}</ol></div>
        <div class="field"><span class="small">등장 인물</span><div style="font-size:13px">${e.plot.characters.map(charName).map(esc).join(', ')}</div></div>
        ${povText(n) ? `<div class="field"><span class="small">서술 시점</span><div style="font-size:13px">${esc(povText(n))}${povText(n) !== povText(n - 1) && n > 1 ? ' <span class="chip ai">시점 바뀜</span>' : ''}</div></div>` : ''}
        <div class="field"><span class="small">감정 변화</span><div style="font-size:13px">${esc(e.plot.emotional_shift)}</div></div>
        ${e.plot.opening ? `<div class="field"><span class="small">여는 장면</span><div style="font-size:13px">${esc(e.plot.opening)}</div></div>` : ''}
        <div class="field"><span class="small">엔딩 훅</span><div style="font-size:13px">${esc(e.plot.ending_hook)}</div></div>
        ${e.plot.reader_question ? `<div class="field"><span class="small">독자가 들고 갈 질문</span><div style="font-size:13px">${esc(e.plot.reader_question)}</div></div>` : ''}
        ${e.summary ? `<div class="field"><span class="small">승인된 요약</span><div style="font-size:13px;line-height:1.6">${esc(e.summary)}</div></div>` : ''}
        ${issuesBlock(e)}
        <a href="${base()}/arc" data-action="gotoPlot" data-arg="${n}" style="font-size:13px">플롯 보기</a>
      </aside>
      <section class="card" style="flex:3 1 520px;min-width:0;padding:0;gap:0" aria-label="본문">
        <div class="between" style="padding:10px 16px;border-bottom:1px solid var(--line);font-size:12px;color:var(--muted)">
          <span>${e.status === 'finalized' ? '상태 반영까지 끝난 화는 읽기 전용이에요. 드래그하면 삽화 프롬프트를 만들 수 있어요' : e.text ? '고칠 부분을 드래그하면 직접 고치거나 AI 에게 맡기거나 삽화 프롬프트를 만들 수 있어요' : '본문을 직접 고친 뒤 저장할 수 있어요'}</span>
          <span class="row"><span><strong id="char-count" style="color:var(--text)">${(text || '').length.toLocaleString()}</strong> / ${Number(P().meta.words_per_episode).toLocaleString()}자</span>
          ${text ? `<button class="btn small" data-action="copyEp" data-arg="${n}" title="고른 줄바꿈 형식으로 복사 (오른쪽 '복사 · 내보내기'에서 바꿈)">복사</button>` : ''}
          ${editable && (e.text || draft !== undefined) ? `<button class="btn small" id="save-text" data-action="saveText" data-arg="${n}"${draft === undefined ? ' disabled' : ''}>본문 저장</button>` : ''}</span>
        </div>
        ${e.text ? passageNotes(n) ? `<div style="padding:12px 16px 0;display:flex;flex-direction:column;gap:8px">${passageNotes(n)}</div>` : '' : ''}
        ${center}
      </section>
      <aside class="card tight" style="flex:1 1 260px;min-width:0" aria-label="복사 · 내보내기와 AI 에게 보내는 컨텍스트">
        ${exportCard(n)}
        <h3>AI 에게 보내는 컨텍스트</h3>
        ${ctx}
        ${S.context ? `<button class="btn small" data-action="togglePrompt" data-arg="${n}">${S.promptText ? '프롬프트 닫기' : '프롬프트 원문 보기'}</button>` : ''}
        ${S.promptText ? `<pre class="brief mono" style="max-height:420px">${esc(S.promptText)}</pre>` : ''}
      </aside>
    </div>
    ${editHistory(e)}
    ${e.text ? illustPanel(n) : ''}
    ${openingPanel(n)}
    ${e.text && editable ? chatPanel(`text:${n}`) : ''}`;
}

// ----- 5. 상태 승인 -----

function viewReview(n) {
  const e = ep(n);
  if (!e) return header('5단계', '상태 변경안 승인', '') + noEpisode();
  const top = (desc, right = '') => `<header class="page-head"><div class="row" style="gap:12px">${epNav('review', n)}<div class="lead" style="gap:2px"><div class="eyebrow">${n}화 ${esc(e.plot.title)}</div><h1 style="font-size:24px">상태 변경안 승인</h1></div><span class="chip ${e.status}">${STATUS[e.status]}</span></div><div class="row">${right}</div></header>${desc ? `<p class="desc">${desc}</p>` : ''}`;

  if (e.status === 'finalized') {
    const h = [...P().history].reverse().find((d) => d.episode === n);
    return top('이 화는 상태 반영이 끝났어요. 반영된 내용입니다.') + (h ? historyView(h) : '<div class="note plain">반영 기록이 없습니다.</div>');
  }
  if (e.status !== 'written') {
    return top('') + `<div class="card empty"><p>${n}화 본문이 아직 없어요. 본문을 쓴 뒤 상태를 정리합니다.</p><a class="btn primary" href="${base()}/write/${n}">${n}화 집필로</a></div>`;
  }
  const d = S.deltas[n];
  if (!d) {
    return top('AI 가 본문에서 인물 상태, 관계, 확정 사실, 복선을 뽑아 변경안을 만듭니다. 승인한 항목만 데이터에 반영됩니다.') +
      `<div class="cols"><section class="card col"><h2>AI 로 뽑기</h2><p class="desc">${esc(S.config && S.config.stages ? S.config.stages.state.model : '')} 로 ${n}화 본문을 읽고 변경안을 만듭니다.</p><div>${((b) => `<button class="btn primary" data-action="extractState" data-arg="${n}"${b.attr}>${b.label}</button>`)(jobBtn('state', n, '변경안 만들기'))}</div></section>
       <section class="card col"><h2>채팅 앱에서 받은 JSON</h2><p class="desc">상태 정리 지시서를 채팅 앱에 붙여 넣고 받은 JSON 을 가져옵니다.</p><div><a class="btn" href="${base()}/brief/${n}" data-action="openStateBrief" data-arg="${n}">상태 정리 지시서 열기</a></div></section></div>`;
  }

  const p = P();
  const stale = S.deltaBase[n] !== undefined && S.deltaBase[n] !== e.text
    ? `<section class="note warn" role="alert">이 변경안을 만든 뒤 본문을 고쳤어요. 고친 내용이 상태에 영향을 준다면 다시 추출하세요. ${((b) => `<button class="btn small" data-action="extractState" data-arg="${n}"${b.attr}>${b.label}</button>`)(jobBtn('state', n, '다시 추출'))}</section>` : '';
  const total = d.character_updates.length + d.events.length + d.secrets_added.length + d.relationship_updates.length + d.new_facts.length + d.foreshadow_planted.length + d.foreshadow_resolved.length + (d.new_characters || []).length;
  if (!S.preview || S.preview.n !== n) refreshPreview(n);
  const picked = Object.values(S.picks).filter(Boolean).length;
  const box = (key) => `<input type="checkbox" id="pk-${key}" data-pick="${key}"${S.picks[key] ? ' checked' : ''}>`;
  const diff = (before, after) => before && before !== after
    ? `<div class="row"><span class="before">${esc(before)}</span><span class="small">→</span><span class="after">${esc(after)}</span></div>`
    : `<div class="row"><span class="after">${esc(after)}</span></div>`;

  const chars = d.character_updates.map((u, i) => {
    const cur = p.states.find((s) => s.character_id === u.character_id) || {};
    const rows = [['감정', 'emotional_state'], ['목표', 'current_goal'], ['위치', 'location'], ['메모', 'notes']]
      .filter(([, f]) => u[f]).map(([k, f]) => `<div class="small">${k}</div>${diff(cur[f], u[f])}`).join('');
    const knows = u.knows.filter((k) => !(cur.knows || []).includes(k)).map((k) => `<span class="after">+ ${esc(k)}</span>`).join(' ');
    return `<div class="change">${box('c' + i)}<div class="body"><label for="pk-c${i}" style="font-size:14px;font-weight:700">${esc(charName(u.character_id))}</label>${rows}${knows ? `<div class="small">알게 된 정보</div><div class="row">${knows}</div>` : ''}</div></div>`;
  }).join('');

  const events = d.events.map((ev, i) => {
    const good = GOOD_EVENTS.includes(ev.kind);
    const wit = ev.witnesses.length ? ` · 목격: ${ev.witnesses.map(charName).map(esc).join(', ')}` : '';
    const sec = ev.reveals_secret ? ` · 드러난 비밀: ${esc(secretLabel(ev.reveals_secret, d))}` : '';
    return `<div class="change">${box('e' + i)}<div class="body"><label for="pk-e${i}" style="font-size:14px;font-weight:700">${esc(charName(ev.actor))} → ${esc(charName(ev.target))}
        <span class="chip" style="background:${good ? 'var(--green-soft)' : 'var(--red-soft)'};color:${good ? 'var(--green)' : 'var(--red)'}">${esc(ev.kind)}</span> <span class="small" style="font-weight:400">${INTENSITY[ev.intensity] || ev.intensity}${wit}${sec}</span></label>
      ${ev.quote ? `<div style="font-family:var(--serif);font-size:13px;line-height:1.7;color:var(--text-2)">“${esc(ev.quote)}”</div>` : ''}</div></div>`;
  }).join('');
  const newChars = (d.new_characters || []).map((c, i) => `<div class="change">${box('n' + i)}<label for="pk-n${i}" style="font-size:13px;line-height:1.55"><strong>${esc(c.name)}</strong> <span class="small">${esc(c.id)} · ${esc(c.role)} · ${c.tier === 'minor' ? '단역' : '조연'}으로 추가</span><br>${esc(c.personality || c.appearance || c.goal)}${c.speech_style ? `<br><span class="small">말투: ${esc(c.speech_style)}</span>` : ''}</label></div>`).join('');
  const secrets = d.secrets_added.map((x, i) => `<div class="change">${box('s' + i)}<label for="pk-s${i}" style="font-size:13px;line-height:1.55"><strong>${esc(charName(x.owner))}</strong> ${esc(x.content)}<br><span class="small">모르는 인물: ${x.hidden_from.map(charName).map(esc).join(', ') || '없음'}</span></label></div>`).join('');
  const rels = d.relationship_updates.map((r, i) => {
    const cur = p.relationships.find((x) => (x.a === r.a && x.b === r.b) || (x.a === r.b && x.b === r.a));
    return `<div class="change">${box('r' + i)}<div class="body"><label for="pk-r${i}" style="font-size:14px;font-weight:700">${esc(charName(r.a))} ↔ ${esc(charName(r.b))}</label>
      ${diff(cur && cur.type, r.type)}${r.description ? diff(cur && cur.description, r.description) : ''}</div></div>`;
  }).join('');

  const facts = d.new_facts.map((f, i) => `<div class="change">${box('f' + i)}<label for="pk-f${i}" style="font-size:13px;line-height:1.55">${esc(f)}</label></div>`).join('');
  const fs = [
    ...d.foreshadow_planted.map((f, i) => `<div class="change">${box('p' + i)}<label for="pk-p${i}" style="font-size:13px;line-height:1.55"><span class="chip confirmed">심음</span> ${esc(f.description)} <span class="small">${esc(f.id)}</span></label></div>`),
    ...d.foreshadow_resolved.map((id, i) => {
      const f = p.foreshadows.find((x) => x.id === id);
      return `<div class="change">${box('x' + i)}<label for="pk-x${i}" style="font-size:13px;line-height:1.55"><span class="chip finalized">회수</span> ${esc(f ? f.description : id)} ${f ? `<span class="small">${f.planted_ep}화에 심음</span>` : '<span class="small">알 수 없는 id</span>'}</label></div>`;
    }),
  ].join('');
  const section = (title, body) => `<section class="card"><h2>${title}</h2>${body || '<div class="small">변경 없음</div>'}</section>`;

  return top('AI 가 본문에서 뽑은 변경안입니다. 체크한 항목만 데이터에 반영되고, 반영해야 다음 화를 쓸 수 있어요.', `<span class="small">${total}건 중 <strong id="pick-count" style="color:var(--text)">${picked}</strong>건 선택</span>`) + stale +
    (d.warnings.length ? `<section class="note warn" role="alert"><strong>경고 ${d.warnings.length}건 · 본문을 고칠지 확인하세요</strong><ul style="padding-left:18px;margin-top:6px">${d.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul><a href="${base()}/write/${n}" style="color:inherit;font-weight:700">본문으로</a></section>` : '') +
    section('인물 상태', chars) +
    (newChars ? section('새로 나온 인물', newChars) : '') +
    `<div class="cols">
      <section class="card col"><div class="between"><h2>관계 사건</h2><span class="small">AI 는 사건만 적고, 관계 수치는 Canon 이 계산합니다</span></div>${events || '<div class="small">이번 화에 관계 사건이 없어요</div>'}
        ${secrets ? `<h3 style="margin-top:6px">새로 생긴 비밀</h3>${secrets}` : ''}
        ${rels ? `<h3 style="margin-top:6px">관계 유형 · 설명 변경</h3>${rels}` : ''}</section>
      <section class="card col">${relationHeader('반영하면 이렇게 계산됩니다')}<div id="rel-preview">${relationLines(S.preview && S.preview.n === n ? S.preview : null)}</div>
        <div class="small">체크를 바꾸면 바로 다시 계산합니다. 저장은 반영할 때만 됩니다.</div></section>
    </div>` +
    `<div class="grid-auto">${section('확정 사실', facts)}${section('복선', fs)}</div>` +
    `<section class="card"><div class="between"><label for="dsum" style="font-size:16px;font-weight:700">${n}화 요약</label><span class="small">다음 화 생성에 이 요약이 들어갑니다</span></div>
      <textarea id="dsum" rows="4" data-delta-summary="${n}">${esc(d.summary)}</textarea></section>
    <div class="between"><div class="row">${((b) => `<button class="btn" data-action="extractState" data-arg="${n}"${b.attr}>${b.label}</button>`)(jobBtn('state', n, '다시 추출'))}<button class="btn" data-action="dropDelta" data-arg="${n}">버리기</button><a class="btn" href="${base()}/write/${n}">본문으로</a></div>
      <button class="btn primary" data-action="applyDelta" data-arg="${n}">선택한 항목 반영하고 ${n}화 완료</button></div>`;
}

function historyView(h) {
  const li = (arr) => arr.length ? `<ul style="padding-left:18px;display:flex;flex-direction:column;gap:6px;font-size:13px;line-height:1.5">${arr.map((x) => `<li>${x}</li>`).join('')}</ul>` : '<div class="small">없음</div>';
  return `<section class="card"><h2>요약</h2><p style="font-size:14px;line-height:1.7">${esc(h.summary)}</p></section>
    <div class="grid-auto">
      <section class="card"><h2>인물 상태</h2>${li(h.character_updates.map((u) => `<strong>${esc(charName(u.character_id))}</strong> ${esc([u.emotional_state, u.current_goal, u.location].filter(Boolean).join(' / '))}${u.knows.length ? ` · 앎: ${esc(u.knows.join(', '))}` : ''}`))}</section>
      <section class="card"><h2>관계 사건</h2>${li((h.events || []).map((ev) => `${esc(charName(ev.actor))} → ${esc(charName(ev.target))} · ${esc(ev.kind)} ${INTENSITY[ev.intensity] || ''}${ev.quote ? `<br><span class="small">“${esc(ev.quote)}”</span>` : ''}`))}</section>
      <section class="card"><h2>사실과 복선</h2>${li([...h.new_facts.map(esc), ...h.foreshadow_planted.map((f) => '심음: ' + esc(f.description)), ...h.foreshadow_resolved.map((id) => '회수: ' + esc(id))])}</section>
    </div>`;
}

// ----- 관계 표시 (숫자/말) -----

const GOOD_EVENTS = ['도움', '희생', '약속이행', '칭찬', '진심고백', '사과', '공동경험'];
const INTENSITY = { 1: '가벼움', 2: '보통', 3: '결정적' };

function secretLabel(id, d) {
  const x = [...P().secrets, ...((d && d.secrets_added) || [])].find((s) => s.id === id);
  return x ? x.content : id;
}

function relationHeader(title) {
  const num = !!P().settings.show_numbers;
  return `<div class="between"><h2>${title}</h2><div class="seg" role="group" aria-label="관계 보기 방식">
    <button type="button" aria-pressed="${!num}" data-action="toggleNumbers" data-arg="words">말로</button>
    <button type="button" aria-pressed="${num}" data-action="toggleNumbers" data-arg="numbers">숫자로</button></div></div>`;
}

function relationLines(rel) {
  if (!rel) return '<div class="small">계산하는 중…</div>';
  if (rel.error) return `<div class="note err">${esc(rel.error)}</div>`;
  const text = P().settings.show_numbers ? rel.numbers : rel.words;
  if (!text) return '<div class="small">관계가 없어요. 설정 도우미에서 관계를 추가하세요.</div>';
  return `<ul class="rel-lines">${text.split('\n').map((l) => `<li>${esc(l)}</li>`).join('')}</ul>`;
}

// ----- 6. 작업지시서 -----

function viewBrief(n) {
  const e = ep(n);
  if (!e) return header('6단계', '채팅 앱 작업지시서', '') + noEpisode();
  const body = S.briefTab === 'episode';
  const stateBlocked = !body && !e.text;
  return `<header class="page-head"><div class="row" style="gap:12px">${epNav('brief', n)}<div class="lead" style="gap:2px"><div class="eyebrow">${n}화 ${esc(e.plot.title)} · API 없이 쓰기</div><h1 style="font-size:24px">채팅 앱 작업지시서</h1></div><span class="chip ${e.status}">${STATUS[e.status]}</span></div></header>
    <p class="desc">Claude, Gemini, ChatGPT 구독 앱에 붙여 넣을 지시서입니다. API 생성과 똑같은 컨텍스트를 씁니다.</p>
    <div class="tabs" role="tablist" aria-label="지시서 종류">
      <button type="button" role="tab" aria-selected="${body}" data-action="setBriefTab" data-arg="episode">1 본문 작성 지시서</button>
      <button type="button" role="tab" aria-selected="${!body}" data-action="setBriefTab" data-arg="state">2 상태 정리 지시서</button>
    </div>
    <div class="cols">
      <section class="card" style="flex:1.3 1 480px;min-width:0">
        <div class="between"><h2><span class="small" style="font-weight:400">① </span>복사해서 채팅 앱에 붙여 넣기</h2>
          <div class="row"><button class="btn small" data-action="downloadBrief" data-arg="${n}"${stateBlocked ? ' disabled' : ''}>.md 내려받기</button><button class="btn small dark" data-action="copyBrief"${stateBlocked ? ' disabled' : ''}>복사</button></div></div>
        ${e.status === 'draft' && body ? '<div class="note warn">플롯이 아직 초안이에요. 확정 전 내용으로 지시서가 만들어집니다.</div>' : ''}
        <pre class="brief mono">${esc(S.briefText ?? '불러오는 중…')}</pre>
        ${S.briefText ? `<div class="small">${S.briefText.length.toLocaleString()}자</div>` : ''}
      </section>
      <section class="card" style="flex:1 1 380px;min-width:0">
        ${body ? `<h2><span class="small" style="font-weight:400">② </span>받은 본문 가져오기</h2>
          <label for="imp-body" class="small">채팅 앱이 쓴 본문을 그대로 붙여 넣으세요.</label>
          <textarea id="imp-body" rows="12" style="font-family:var(--serif);line-height:1.8"${e.status === 'draft' || e.status === 'finalized' ? ' disabled' : ''}></textarea>
          ${e.status === 'draft' ? '<div class="small">플롯을 확정해야 본문을 저장할 수 있어요.</div>' : ''}${e.status === 'finalized' ? '<div class="small">이미 끝난 화입니다.</div>' : ''}
          <div style="align-self:flex-end"><button class="btn primary" data-action="importText" data-arg="${n}"${e.status === 'draft' || e.status === 'finalized' ? ' disabled' : ''}>${n}화 본문으로 저장</button></div>`
        : `<h2><span class="small" style="font-weight:400">② </span>받은 JSON 가져오기</h2>
          <label for="imp-json" class="small">채팅 앱의 JSON 답변을 붙여 넣으세요. 코드 블록 표시는 자동으로 지웁니다.</label>
          <textarea id="imp-json" rows="12" class="mono"${e.status !== 'written' ? ' disabled' : ''}></textarea>
          ${e.status !== 'written' ? '<div class="small">본문이 작성된 화에서만 쓸 수 있어요.</div>' : ''}
          <div style="align-self:flex-end"><button class="btn primary" data-action="importJson" data-arg="${n}"${e.status !== 'written' ? ' disabled' : ''}>확인하고 변경안 검토로</button></div>`}
        <div style="padding-top:12px;border-top:1px solid var(--line);display:flex;flex-direction:column;gap:8px">
          <strong style="font-size:13px">순서</strong>
          <ol style="padding-left:20px;display:flex;flex-direction:column;gap:4px;font-size:13px;line-height:1.55;color:var(--text-2)">
            <li>본문 작성 지시서 → 받은 본문 저장</li><li>상태 정리 지시서 → 받은 JSON 가져오기</li><li>상태 변경안 승인 화면에서 반영</li></ol>
        </div>
      </section>
    </div>`;
}

// ---------- 연구 (모델 실험) ----------
// 본편 데이터와 분리된 실험실. 결과는 projects/<이름>/research/log.jsonl 에 남고,
// 블라인드 비교에서 채택할 때만 작품 본문이 바뀐다.

const RS_TABS = [['probe', '서버 점검'], ['sample', '샘플 생성'], ['stage', '단계 시험'], ['budget', '컨텍스트 크기'], ['compare', '블라인드 비교'], ['log', '기록']];
const RS_KIND = { sample: '샘플 생성', stage: '단계 시험', budget: '컨텍스트 크기', compare: '블라인드 비교', pick: '비교 고르기' };

function rsInit(name) {
  const c = S.config || {};
  const backend = () => ({ provider: c.provider === 'mock' ? 'mock' : 'local', model: c.local_model || '', url: '' });
  S.rs = {
    name, tab: 'probe', log: [], stages: {}, probe: null, probeUrl: c.local_url || '',
    runs: [backend()], system: '너는 한국어 소설가다.', prompt: '', temperature: '', sample: null,
    stageBackend: backend(), stage: 'style', stageText: '', stageResult: null,
    budgetBackend: backend(), budget: null,
    compareEp: null, compareA: { provider: 'gemini', model: '', url: '' }, compareB: backend(), compare: null, adopt: true, pickResult: null,
  };
}

async function rsLoadLog() {
  const r = await api('GET', `/projects/${enc(S.name)}/research`);
  S.rs.log = r.log;
  S.rs.stages = r.stages;
}

async function rsLoad() {
  if (!S.rs || S.rs.name !== S.name) rsInit(S.name);
  await rsLoadLog();
  if (S.rs.compareEp == null) S.rs.compareEp = currentEp();
  S.rs.compare = (await api('GET', `/projects/${enc(S.name)}/research/compare/${S.rs.compareEp}`)).compare;
}

document.addEventListener('input', (e) => {
  const el = e.target;
  if (!el.dataset.rs || !S.rs) return;
  setPath(S.rs, el.dataset.rs, el.type === 'checkbox' ? el.checked : el.value);
});

const rsBackend = (b) => ({ provider: b.provider, model: b.model.trim(), url: b.url.trim() });
const rsLabel = (b) => (b.model ? `${b.provider}:${b.model}` : b.provider);
const rsNum = (v, d = 0) => (v == null ? '-' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));

Object.assign(actions, {
  rsTab(tab) {
    S.rs.tab = tab;
    render();
  },
  async rsProbe() {
    await run('서버를 확인하는 중', async () => {
      S.rs.probe = await api('POST', '/research/probe', { url: S.rs.probeUrl.trim() });
    });
  },
  rsUseModel(id) {
    S.rs.runs.push({ provider: 'local', model: id, url: S.rs.probeUrl.trim() === (S.config.local_url || '') ? '' : S.rs.probeUrl.trim() });
    S.rs.tab = 'sample';
    toast(`${id} 를 샘플 생성에 넣었습니다`);
    render();
  },
  rsAddRun() {
    S.rs.runs.push({ provider: 'local', model: '', url: '' });
    render();
  },
  rsRemoveRun(i) {
    S.rs.runs.splice(i, 1);
    render();
  },
  async rsSample() {
    if (!S.rs.prompt.trim()) return toast('요청 문장을 넣으세요', true);
    if (!S.rs.runs.length) return toast('백엔드를 하나 이상 넣으세요', true);
    const t = S.rs.temperature === '' ? null : Number(S.rs.temperature);
    await run(`${S.rs.runs.length}개 백엔드로 생성하는 중… (백엔드마다 차례로)`, async () => {
      S.rs.sample = await api('POST', `/projects/${enc(S.name)}/research/sample`,
        { runs: S.rs.runs.map(rsBackend), system: S.rs.system, prompt: S.rs.prompt, temperature: t });
      S.rs.log.unshift(S.rs.sample);
    });
  },
  async rsStage() {
    await run(`${S.rs.stages[S.rs.stage] || S.rs.stage} 시험 중… (저장하지 않음)`, async () => {
      S.rs.stageResult = await api('POST', `/projects/${enc(S.name)}/research/stage`,
        { backend: rsBackend(S.rs.stageBackend), stage: S.rs.stage, sample: S.rs.stageText });
      S.rs.log.unshift(S.rs.stageResult);
    });
  },
  async rsBudget() {
    await run('화별 프롬프트를 재는 중', async () => {
      S.rs.budget = await api('POST', `/projects/${enc(S.name)}/research/budget`, rsBackend(S.rs.budgetBackend));
      S.rs.log.unshift(S.rs.budget);
    });
  },
  async rsCompareEp() {
    S.rs.compareEp = Number($('#rs-cmp-ep').value);
    S.rs.pickResult = null;
    await run('불러오는 중', async () => {
      S.rs.compare = (await api('GET', `/projects/${enc(S.name)}/research/compare/${S.rs.compareEp}`)).compare;
    });
  },
  async rsCompare() {
    const n = S.rs.compareEp;
    if (S.rs.compare && !S.rs.compare.picked && !confirm(`${n}화의 고르지 않은 비교본을 새로 쓴 것으로 바꿀까요?`)) return;
    await run(`${n}화를 두 백엔드로 쓰는 중… (몇 분 걸릴 수 있어요)`, async () => {
      S.rs.compare = (await api('POST', `/projects/${enc(S.name)}/research/compare/${n}`,
        { a: rsBackend(S.rs.compareA), b: rsBackend(S.rs.compareB) })).compare;
      S.rs.pickResult = null;
      await rsLoadLog();
    });
  },
  async rsPick(k) {
    const n = S.rs.compareEp;
    if (S.rs.adopt && ep(n).text && !confirm(`${k}번을 ${n}화 본문으로 바꿀까요?`)) return;
    await run('공개하는 중', async () => {
      await saveIfDirty();
      const r = await api('POST', `/projects/${enc(S.name)}/research/compare/${n}/pick`, { k, adopt: S.rs.adopt });
      S.rs.compare = r.compare;
      S.rs.pickResult = r.result;
      S.project = r.project;
      await rsLoadLog();
      delete S.textDraft[n];
      delete S.deltas[n];
      toast(`${k}번은 ${r.result.picked} 였습니다${r.result.adopted ? `. ${n}화 본문으로 저장했습니다` : ''}`);
    });
  },
});

function rsBackendFields(path, b) {
  const id = 'rs-' + path.replace(/\W/g, '-');
  const opts = [['local', '로컬 서버'], ['gemini', 'Gemini'], ['mock', 'mock']]
    .map(([v, l]) => `<option value="${v}"${b.provider === v ? ' selected' : ''}>${l}</option>`).join('');
  return `<div class="rs-backend">
    <div class="field"><label for="${id}-p">백엔드</label><select id="${id}-p" data-rs="${path}.provider">${opts}</select></div>
    <div class="field"><label for="${id}-m">모델 <span class="hint">비우면 설정값</span></label><input id="${id}-m" type="text" list="rs-models" value="${esc(b.model)}" data-rs="${path}.model"></div>
    <div class="field"><label for="${id}-u">서버 주소 <span class="hint">로컬만, 비우면 설정값</span></label><input id="${id}-u" type="text" value="${esc(b.url)}" data-rs="${path}.url" placeholder="${esc((S.config || {}).local_url || '')}"></div>
  </div>`;
}

function rsModelList() {
  const ids = ((S.rs.probe || {}).models || []).map((m) => m.id);
  if ((S.config || {}).local_model) ids.push(S.config.local_model);
  if ((S.config || {}).model_setting) ids.push(S.config.model_setting);
  return `<datalist id="rs-models">${[...new Set(ids)].map((x) => `<option value="${esc(x)}"></option>`).join('')}</datalist>`;
}

function rsUsage(u, seconds) {
  if (!u) return '';
  const out = u.completion_tokens;
  return `입력 ${rsNum(u.prompt_tokens)} · 출력 ${rsNum(out)} 토큰${out && seconds ? ` · ${rsNum(out / seconds, 1)} 토큰/초` : ''}`;
}

function rsProbeView() {
  const r = S.rs.probe;
  const rows = r ? r.models.map((m) => `<tr><td class="mono">${esc(m.id)}</td><td>${esc(m.parent || '')}</td><td>${m.max_model_len ? rsNum(m.max_model_len) : (m.parent ? '부모와 같음' : '-')}</td><td>${esc(m.owned_by)}</td>
      <td><button class="btn small" data-action="rsUseModel" data-arg="${esc(m.id)}">샘플 생성에 넣기</button></td></tr>`).join('') : '';
  return `<section class="card">
      <p class="desc">OpenAI 호환 서버(vLLM, Ollama, llama.cpp, LM Studio)의 모델 목록과 컨텍스트 길이를 봅니다. 생성 호출은 하지 않습니다.</p>
      <div class="row" style="align-items:flex-end;flex-wrap:nowrap">
        <div class="field" style="flex:1"><label for="rs-probe-url">서버 주소 <span class="hint">/v1 까지</span></label><input id="rs-probe-url" type="text" value="${esc(S.rs.probeUrl)}" data-rs="probeUrl" placeholder="http://nhn-b200:8001/v1"></div>
        <button class="btn dark" data-action="rsProbe">점검</button>
      </div>
      ${r ? `<div class="note ok">${esc(r.url)} · 서버 ${esc(r.server)}${r.version ? ' ' + esc(r.version) : ''} · 모델 ${r.models.length}개 · ${r.seconds}초</div>
        <div class="rs-scroll"><table class="rs-table"><thead><tr><th>모델</th><th>부모 (LoRA)</th><th>최대 컨텍스트</th><th>제공</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
        <div class="small">컨텍스트가 작은 모델은 '컨텍스트 크기' 탭에서 몇 화부터 넘치는지 확인하세요. 서버 주소와 모델을 고정하려면 <a href="#/settings">설정</a>에 저장하세요.</div>` : ''}
    </section>`;
}

function rsSampleView() {
  const runs = S.rs.runs.map((b, i) => `<div class="row" style="align-items:flex-end;flex-wrap:nowrap"><div style="flex:1">${rsBackendFields(`runs.${i}`, b)}</div>
      <button class="btn icon-btn danger" data-action="rsRemoveRun" data-arg="${i}" aria-label="백엔드 ${i + 1} 빼기">✕</button></div>`).join('');
  const res = S.rs.sample;
  const cards = res ? res.rows.map((r) => `<section class="card tight">
      <div class="between"><h3>${esc(r.backend)}</h3><span class="small">${r.seconds}초</span></div>
      ${r.ok ? `<div class="small">${esc(r.model)} · ${rsNum(r.chars)}자 · 문장 평균 ${rsNum(r.sentence_len_mean, 1)} · 대사 ${rsNum(r.dialogue_ratio, 2)} · 어휘 ${rsNum(r.mattr, 3)}</div>
        <div class="small">${rsUsage(r.usage, r.seconds)}</div>
        <div class="rs-prose">${esc(r.text)}</div>` : `<div class="note err">${esc(r.error)}</div>`}
    </section>`).join('') : '';
  return `<section class="card">
      <p class="desc">같은 요청을 여러 백엔드에 차례로 보내 시간, 토큰, 문체 지표를 나란히 봅니다. 작품 데이터는 쓰지 않습니다.</p>
      ${runs || '<div class="small">백엔드를 넣으세요.</div>'}
      <div><button class="btn small ghost" data-action="rsAddRun">+ 백엔드</button></div>
      <div class="field"><label for="rs-system">시스템 지시</label><textarea id="rs-system" rows="2" data-rs="system">${esc(S.rs.system)}</textarea></div>
      <div class="field"><label for="rs-prompt">요청</label><textarea id="rs-prompt" rows="4" data-rs="prompt" placeholder="비 오는 바닷가 소도시 등대 앞, 오빠를 찾는 서윤의 장면을 600자로 써라.">${esc(S.rs.prompt)}</textarea></div>
      <div class="row" style="align-items:flex-end">
        <div class="field" style="width:160px"><label for="rs-temp">온도 <span class="hint">로컬만</span></label><input id="rs-temp" type="number" step="0.1" min="0" max="2" value="${esc(S.rs.temperature)}" data-rs="temperature" placeholder="설정값"></div>
        <button class="btn dark" data-action="rsSample">생성</button>
      </div>
    </section>
    ${cards ? `<div class="grid-auto">${cards}</div>` : ''}`;
}

function rsStageView() {
  const r = S.rs.stageResult;
  const stages = Object.entries(S.rs.stages).map(([k, l]) => `<option value="${k}"${S.rs.stage === k ? ' selected' : ''}>${l}</option>`).join('');
  let out = '';
  if (r && !r.ok) out = `<div class="note err">${esc(r.error)} · ${r.seconds}초</div>`;
  if (r && r.ok) {
    const filled = r.fields - r.empty.length;
    out = `<section class="card">
      <div class="between"><h2>${esc(S.rs.stages[r.stage] || r.stage)} · ${esc(r.backend)}</h2><span class="small">${r.seconds}초 · 시도 ${r.attempts}회 · ${rsUsage(r.usage, r.seconds)}</span></div>
      <div class="note ${r.empty.length ? 'warn' : 'ok'}">필드 ${r.fields}개 중 ${filled}개 채움${r.empty.length ? `, 빈 필드 ${r.empty.length}개` : ''}</div>
      ${r.empty.length ? `<div class="small mono">${r.empty.map(esc).join(' · ')}</div>` : ''}
      ${r.out_of_range.length ? `<div class="note err">범위를 벗어난 값 ${r.out_of_range.length}개 (스키마 설명의 범위 기준)<br><span class="mono">${r.out_of_range.map(esc).join('<br>')}</span></div>` : ''}
      ${r.attempts > 1 ? '<div class="note warn">첫 응답이 스키마 검증에 실패해 한 번 더 물었습니다.</div>' : ''}
      <details><summary>응답 JSON 보기</summary><pre class="brief mono">${esc(JSON.stringify(r.result, null, 2))}</pre></details>
    </section>`;
  }
  return `<section class="card">
      <p class="desc">설정 제안, 문체 분석, 기승전결을 저장하지 않고 돌려 봅니다. 모델이 건너뛴 필드, 범위를 벗어난 숫자, 재시도 횟수를 확인합니다.</p>
      ${rsBackendFields('stageBackend', S.rs.stageBackend)}
      <div class="field" style="max-width:240px"><label for="rs-stage">단계</label><select id="rs-stage" data-rs="stage">${stages}</select></div>
      <div class="field"><label for="rs-stage-text">문체 분석 원문 <span class="hint">문체 분석에만 씀. 비우면 문체 레퍼런스의 대표 문단</span></label><textarea id="rs-stage-text" rows="5" data-rs="stageText" style="font-family:var(--serif)">${esc(S.rs.stageText)}</textarea></div>
      <div><button class="btn dark" data-action="rsStage">시험</button></div>
    </section>${out}`;
}

function rsBudgetView() {
  const r = S.rs.budget;
  let out = '';
  if (r) {
    const cell = (c) => `<td class="${c.over ? 'over' : c.tight ? 'tight' : ''}">${c.exact ? '' : '~'}${rsNum(c.tokens)}<span class="small"> / ${rsNum(c.total)}</span></td>`;
    const rows = r.rows.map((x) => `<tr><td>${x.episode}화</td><td><span class="chip ${x.status}">${STATUS[x.status]}</span>${x.measured ? '' : ' <span class="small">가정</span>'}</td>${cell(x.write)}${cell(x.check)}${cell(x.state)}</tr>`).join('');
    out = `<section class="card">
      <div class="between"><h2>${esc(r.backend)} · ${esc(r.model)}</h2><span class="small">최대 컨텍스트 ${r.limit ? rsNum(r.limit) + ' 토큰' : '알 수 없음'}</span></div>
      ${r.first_over ? `<div class="note err">${r.first_over}화부터 입력만으로 한도를 넘어 서버가 요청을 거절합니다. 검수(check)는 앞선 본문 전체를 넣어 화가 갈수록 커집니다. 서버의 컨텍스트를 늘리거나, 설정의 단계별 백엔드에서 넘치는 단계를 Gemini 로 돌리세요.</div>` : ''}
      ${r.first_tight && r.first_tight !== r.first_over ? `<div class="note warn">${r.first_tight}화부터 출력 여유까지 더하면 한도를 넘습니다. 응답이 중간에 잘릴 수 있어요.</div>` : ''}
      ${!r.limit ? '<div class="note plain">이 백엔드는 한도를 알려 주지 않아 넘침은 판단하지 않았습니다.</div>' : (!r.first_tight ? '<div class="note ok">플롯이 있는 화는 모두 한도 안에 들어갑니다.</div>' : '')}
      <div class="rs-scroll"><table class="rs-table"><thead><tr><th>화</th><th>상태</th><th>본문 쓰기</th><th>검수</th><th>상태 추출</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="small">칸마다 '입력 / 입력+출력 여유' 토큰입니다. 출력 여유는 본문 ${rsNum(r.write_reserve)}, 검수·상태 ${rsNum(r.json_reserve)} 토큰으로 잡았습니다. ${r.tokenizer ? '서버 토크나이저로 셌습니다.' : '~ 표시는 글자 수로 어림한 값입니다.'} '가정'인 화는 앞선 화가 모두 목표 분량으로 쓰였다고 보고 쟀습니다. 플롯이 있는 화만 잽니다.</div>
    </section>`;
  }
  return `<section class="card">
      <p class="desc">화마다 본문 쓰기, 검수, 상태 추출에 들어가는 프롬프트 크기를 모델의 컨텍스트 한도와 비교합니다. 생성 호출은 하지 않습니다.</p>
      ${rsBackendFields('budgetBackend', S.rs.budgetBackend)}
      <div><button class="btn dark" data-action="rsBudget">재기</button></div>
    </section>${out}`;
}

function rsCompareView() {
  const eps = P().episodes.filter((e) => e.status !== 'draft');
  const c = S.rs.compare;
  const n = S.rs.compareEp;
  const e = ep(n);
  const reveal = c && c.order;
  const drafts = c ? c.drafts.map((d) => `<section class="card tight${c.picked === d.n ? ' rs-picked' : ''}">
      <div class="between"><h3>${d.n}번${reveal ? ` <span class="chip ai">${esc(c.order[d.n - 1])}</span>` : ''}</h3>
        ${c.picked ? (c.picked === d.n ? '<span class="chip finalized">고름</span>' : '') : `<button class="btn small primary" data-action="rsPick" data-arg="${d.n}">이걸 고르기</button>`}</div>
      <div class="small">${rsNum(d.chars)}자 · 문장 평균 ${rsNum(d.sentence_len_mean, 1)} · 대사 ${rsNum(d.dialogue_ratio, 2)} · 어휘 ${rsNum(d.mattr, 3)}</div>
      ${d.warnings.length ? `<div class="note warn">${d.warnings.map(esc).join('<br>')}</div>` : ''}
      <div class="rs-prose">${esc(d.text)}</div>
    </section>`).join('') : '';
  const wins = S.rs.pickResult ? Object.entries(S.rs.pickResult.wins).map(([k, v]) => `${esc(k)} ${v}`).join(', ') : '';
  return `<section class="card">
      <p class="desc">같은 화를 두 백엔드로 쓰고 1, 2번으로 가립니다. 읽고 고르면 어느 쪽이었는지 공개합니다. 프롬프트는 집필 화면과 같습니다.</p>
      <div class="field" style="max-width:320px"><label for="rs-cmp-ep">화</label>
        <select id="rs-cmp-ep" onchange="actions.rsCompareEp()">${eps.map((x) => `<option value="${x.plot.number}"${x.plot.number === n ? ' selected' : ''}>${x.plot.number}화 ${esc(x.plot.title)} · ${STATUS[x.status]}</option>`).join('') || '<option>확정된 화가 없습니다</option>'}</select></div>
      <div class="grid-2"><div><h3>A</h3>${rsBackendFields('compareA', S.rs.compareA)}</div><div><h3>B</h3>${rsBackendFields('compareB', S.rs.compareB)}</div></div>
      <label class="check-row"><input type="checkbox" data-rs="adopt"${S.rs.adopt ? ' checked' : ''}><span><strong>고른 쪽을 본문으로 채택</strong> <span class="small">끄면 고른 기록만 남기고 작품은 그대로 둡니다. 반영이 끝난 화는 채택할 수 없어요.</span></span></label>
      <div><button class="btn dark" data-action="rsCompare"${eps.length && e && e.status !== 'draft' ? '' : ' disabled'}>${n}화 비교본 쓰기</button></div>
      ${e && e.status === 'finalized' ? '<div class="small">이 화는 반영이 끝났습니다. 비교본을 쓰려면 이전 화들이 반영 완료여야 하고, 채택은 끈 채로 고르세요.</div>' : ''}
    </section>
    ${S.rs.pickResult ? `<div class="note ok">${esc(S.rs.pickResult.picked)} 를 골랐습니다. 지금까지 고른 횟수: ${wins}</div>` : ''}
    ${c ? `<div class="small">${esc((c.created || '').replace('T', ' '))} 에 쓴 비교본${c.picked ? '' : ' · 고르기 전까지 백엔드를 가립니다'}</div><div class="rs-compare">${drafts}</div>` : ''}`;
}

function rsLogView() {
  const items = S.rs.log.map((x) => {
    let line = '';
    if (x.kind === 'sample') line = x.rows.map((r) => `${r.backend} ${r.ok ? `${rsNum(r.chars)}자 ${r.seconds}초` : '실패'}`).join(' · ');
    if (x.kind === 'stage') line = `${S.rs.stages[x.stage] || x.stage} · ${x.backend} · ${x.ok ? `빈 필드 ${x.empty.length}/${x.fields}, 범위 밖 ${x.out_of_range.length}, 시도 ${x.attempts}` : '실패'} · ${x.seconds}초`;
    if (x.kind === 'budget') line = `${x.backend} · 한도 ${x.limit ? rsNum(x.limit) : '알 수 없음'} · ${x.first_over ? `${x.first_over}화부터 넘침` : x.first_tight ? `${x.first_tight}화부터 빠듯함` : '넘침 없음'}`;
    if (x.kind === 'compare') line = `${x.episode}화 · ${x.backends.join(' vs ')}`;
    if (x.kind === 'pick') line = `${x.episode}화 · ${x.picked} 고름${x.adopted ? ' (본문 채택)' : ''}`;
    return `<li><div class="between"><span><span class="chip">${RS_KIND[x.kind] || x.kind}</span> ${esc(line)}</span><span class="small">${esc(x.time.replace('T', ' '))}</span></div>
      <details><summary>자세히</summary><pre class="brief mono">${esc(JSON.stringify(x, null, 2))}</pre></details></li>`;
  }).join('');
  return `<section class="card">
      <p class="desc">최근 30개 실험입니다. 전체 기록은 작품 폴더의 research/log.jsonl 에 있습니다.</p>
      ${items ? `<ul class="rs-log">${items}</ul>` : '<div class="small">아직 기록이 없어요.</div>'}
    </section>`;
}

function viewResearch() {
  if (!S.rs) return header('연구', '모델 실험', '') + '<div class="note plain">불러오는 중…</div>';
  const views = { probe: rsProbeView, sample: rsSampleView, stage: rsStageView, budget: rsBudgetView, compare: rsCompareView, log: rsLogView };
  return `${header('연구 · 본편과 분리', '모델 실험', '모델 서버를 점검하고, 같은 요청을 여러 모델로 돌려 비교합니다. 여기서 돌린 결과는 작품 데이터에 들어가지 않고 실험 기록으로만 남습니다. 블라인드 비교에서 채택할 때만 본문이 바뀝니다.')}
    <div class="tabs" role="tablist" aria-label="실험 종류">${RS_TABS.map(([k, l]) => `<button type="button" role="tab" aria-selected="${S.rs.tab === k}" data-action="rsTab" data-arg="${k}">${l}</button>`).join('')}</div>
    ${rsModelList()}
    ${views[S.rs.tab]()}`;
}

route();
pollJobs();

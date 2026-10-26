/* Canon 웹 UI. 빌드 없이 쓰는 단일 파일 SPA.
   화면은 문자열 템플릿으로 그리고, 입력은 data-bind 경로로 S.project 에 바로 반영한다.
   AI 호출이나 저장이 끝나면 화면 전체를 다시 그린다. */
'use strict';

const S = {
  config: null,
  name: null,        // 현재 프로젝트 폴더 이름
  project: null,
  dirty: false,
  gen: 0,            // 화면 작품이 바뀔 때마다(받기 · 저장 · 입력) 오른다. 늦게 온 작품 GET 이 더 새 값을 덮지 않게 비교한다
  conflict: false,   // 다른 탭 · 기기가 먼저 저장해 이 화면의 저장이 막혔다 (409)
  pending: { name: null, results: {}, failures: {} },
  jobArgs: {},       // 작업 id → 시작한 인자 { kind, ep, extra } (실패한 작업 '다시 시도')
  jobsOffline: false, // 작업 목록을 묻지 못했다 (서버가 꺼졌거나 다시 시작하는 중)  // 서버 pending.json: 검토를 기다리는 AI 결과와 실패한 작업 (새로고침에도 남는다)
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
  deltaOrig: {},     // 변경안을 받았을 때의 요약. 다시 만들기 전에 고친 요약을 버리는지 묻는다
  picks: {},         // 변경안 항목 선택 여부
  textDraft: {},     // 화별 본문 편집 중인 값
  context: null,
  promptText: null,
  briefTab: 'episode',
  briefText: null,
  mode: localStorage.getItem('canon.mode') || 'api',
  jobs: [],          // 서버에서 돌고 있거나 막 끝난 AI 작업
  jobsSeen: null,    // 화면을 연 시점에 이미 끝나 있던 작업 id (결과를 다시 적용하지 않는다)
  jobsApplied: new Set(),  // 결과를 이미 화면에 적용한 작업 id. 폴링이 작업 객체를 새로 받아 오므로 id 로 기억한다
  jobsMerged: {},    // 도는 플롯 작업 id → 화면이 결과를 받아 온 단계 수
  jobsOpen: null,    // 작업 목록 펼침. null 이면 넓은 화면은 펼치고 휴대폰은 접는다
  jobsFailed: new Set(),  // 작업 목록이 이미 본 실패 작업 id. 새 실패가 생기면 목록을 펼친다
  starting: new Set(),    // 시작 요청을 보내고 답을 기다리는 작업 '<kind>:<ep>'
  briefDraft: {},    // 작업지시서 ② 칸에 붙여 넣은 글. '<작품>:<화>:<episode|state>' → 글
  settingsDirty: false,  // 모델 · API 키 설정 화면에서 저장하지 않은 입력이 있다
  selArc: null,      // 장편: 플롯 보드에서 고른 아크 번호 ('next' 는 다음 아크 기획)
  editArc: false,    // 장편: 아크 고치기 서랍
  selPart: null,     // 장편: 고치는 부 번호
  seriesDraft: null, // 장편: 부 구성 제안 (반영 전)
  arcDraft: null,    // 장편: 다음 아크 제안 (반영 전)
  planNote: '',      // 구조 다시 제안 · 플롯 초안 · 부 구성 제안에 함께 보낼 작가 요청
  arcForm: { length: 0, note: '' },  // 장편: 다음 아크 요청
  recapDrafts: {},   // 장편: 아크·부 요약 제안. 'arc1', 'part2' 같은 키 → { kind, number, summary }. 여러 개를 함께 고친다
  namingStyles: null, // 이름 스타일 목록 (서버 naming.STYLES)
  names: {},         // 이름·지명 후보. 'c:<인물 id>' 또는 'place' → { candidates, options, ai }
  nameCheck: null,   // 출연진 이름 점검 { warnings, style, detected }
  placeKind: '',     // 지명 후보의 종류 (산, 마을, 문파…)
};

// 서버에서 받은 작품의 관계와 화별 플롯. 저장할 때 화면이 실제로 고친 칸만 가려 '서버 것으로 두었어요'를 알린다 (save)
let projectBase = null;
const baseOf = (p) => p && { rels: JSON.stringify(p.relationships), plots: new Map(p.episodes.map((e) => [e.plot.number, JSON.stringify(e.plot)])) };
let projectNow = S.project;
delete S.project;
Object.defineProperty(S, 'project', { enumerable: true, get: () => projectNow, set: (v) => { projectNow = v; projectBase = baseOf(v); S.gen++; S.lastRemoved = null; } });

/** 저장하기 전 목록에서 지운 것을 하나 되살릴 수 있게, 지우기 직전 그 칸들을 둔다. 저장 띠에 '되살리기'가 뜬다. */
function rememberRemoved(label, paths) {
  S.lastRemoved = { label, saved: paths.map((k) => [k, structuredClone(getPath(P(), k))]) };
}

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
  if (Array.isArray(d)) return d.map((x) => { const at = (x.loc || []).slice(1).join('.'); return `입력 형식이 맞지 않아요${at ? ` (칸: ${at})` : ''}: ${x.msg}`; }).join('\n');
  return d || `요청 실패 (${status})`;
}

// 이 탭의 id. 서버는 작품을 저장한 화면을 기억해, 다른 탭 · 기기가 먼저 저장했으면 오래된 화면의 저장을 409 로 막는다
const CLIENT = Math.random().toString(36).slice(2, 10) + Date.now().toString(36);

// 마지막으로 받은 작품 JSON과 그 판(ETag). 같은 판이면 서버가 304 로 본문 없이 답하고 이것을 복사해 쓴다 (장편은 수 MB)
let projectCache = null;  // { path, tag, data }

/** meta 를 넘기면 응답 헤더를 meta.headers 에 담는다. 실패하면 Error 의 status 에 HTTP 상태를 담는다. */
async function api(method, path, body, meta) {
  const opt = { method, headers: { 'X-Canon-Client': CLIENT } };
  const whole = method === 'GET' && /^\/projects\/[^/?]+$/.test(path);  // 작품 전체 GET
  if (whole) {
    opt.cache = 'no-store';  // 브라우저 캐시 대신 아래 projectCache 로 판을 맞춘다
    if (projectCache && projectCache.path === path) opt.headers['If-None-Match'] = projectCache.tag;
  }
  if (body !== undefined) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
  let r;
  if (runAbort && method !== 'GET') opt.signal = runAbort.signal;  // run() 이 기다리는 요청만 '기다리지 않기'로 끊는다
  try {
    r = await fetch('/api' + path, opt);
  } catch (e) {
    if (e.name === 'AbortError') throw Object.assign(new Error('기다리지 않기로 했어요. 서버에서는 요청이 끝까지 돌 수 있으니, 잠시 뒤 결과를 확인하세요'), { status: 0, code: 'aborted' });
    // 서버가 꺼졌거나 네트워크가 끊겼다 (브라우저마다 다른 영어 문구 대신)
    throw Object.assign(new Error('서버에 연결하지 못했어요. 서버가 켜져 있는지, 네트워크가 연결됐는지 확인하세요'), { status: 0 });
  }
  if (whole && r.status === 304 && projectCache && projectCache.path === path) return structuredClone(projectCache.data);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(fmtErr(data, r.status)), { status: r.status, code: data && data.code });
  if (meta) meta.headers = r.headers;
  if (whole && r.headers.get('ETag')) {
    projectCache = { path, tag: r.headers.get('ETag'), data };
    return structuredClone(data);  // 화면은 받은 작품을 고쳐 쓰므로 보관한 것과 나눈다
  }
  return data;
}

function toast(msg, err = false) {
  const el = document.createElement('div');
  el.className = 't' + (err ? ' err' : '');
  if (err) {
    // 오류는 읽을 때까지 남긴다. 닫기 버튼으로 지운다
    const t = document.createElement('span');
    t.textContent = msg;
    const x = document.createElement('button');
    x.type = 'button';
    x.className = 'x';
    x.setAttribute('aria-label', '닫기');
    x.textContent = '✕';
    x.addEventListener('click', () => el.remove());
    el.append(t, x);
  } else {
    el.textContent = msg;
  }
  $('#toast').appendChild(el);
  // 많이 쌓이면 오래된 알림부터 내린다. 오류는 알림이 밀어내지 않고, 오류가 다섯 개를 넘으면 오래된 오류를 내린다
  const box = $('#toast');
  while (box.children.length > 3 && box.querySelector('.t:not(.err)')) box.querySelector('.t:not(.err)').remove();
  while (box.querySelectorAll('.t.err').length > 5) box.querySelector('.t.err').remove();
  if (!err) setTimeout(() => el.remove(), 3500);
}

// ---------- 백그라운드 AI 작업 ----------
// 오래 걸리는 AI 호출은 서버가 백그라운드로 돌리고, 화면은 1.5초마다 상태만 묻는다.
// 그동안 다른 화면으로 옮겨 다니며 계속 작업할 수 있다.

const JOB_DONE_MSG = {
  suggest: '설정 제안이 도착했어요. 설정 도우미에서 확인하세요.',
  arc: '기승전결 구조 제안이 도착했어요. 확인하고 저장하세요.',
  plots: '화별 플롯 초안을 만들었어요. 확정된 화는 그대로예요.',
  plot_one: (j) => (j.result && j.result.realign ? `${j.ep}화 플롯을 요약대로 채웠어요. ${j.result.realign}화와 어긋난 점은 ${j.result.realign}화에 '다시 맞추기'로 표시했어요.` : `${j.ep}화 플롯을 채웠어요. 다듬은 뒤 확정하세요.`),
  write: (j) => `${j.ep}화 본문을 저장했어요.`,
  state: (j) => `${j.ep}화 상태 변경안이 도착했어요.`,
  series: '부 구성 제안이 도착했어요. 확인하고 반영하세요.',
  nextarc: '다음 아크 제안이 도착했어요. 고친 뒤 반영하세요.',
  recap_arc: (j) => `아크 ${j.ep} 요약 제안이 도착했어요.`,
  recap_part: (j) => `${j.ep}부 요약 제안이 도착했어요.`,
  impact: (j) => `${j.label.replace(/^인과율: /, '')}이 끝났어요. 인과율에서 확인하세요.`,
  storyline: '이야기 줄기 제안이 도착했어요. 고른 화와 함께 반영하세요.',
  // 멈춤 · 검토 대기도 작업으로는 '끝남'이다. 사람을 기다리는지 상태별로 말한다 (autorun._launch 결과)
  auto: (j) => `자동 집필${{ review: ' · 검토가 필요해요', paused: ' · 일시정지했어요', error: ' · 오류로 멈췄어요' }[j.result && j.result.status] || ''}: ${j.note || '멈췄어요'}`,
};
let jobTimer = null;

function jobFor(kind, ep = null, name = S.name) {
  return S.jobs.find((j) => j.status === 'running' && j.project === name && j.kind === kind && (ep == null || j.ep === ep));
}

// 작업이 도는 동안 버튼은 진행 상황을 보여 주고 눌리지 않게 한다
function jobBtn(kind, ep, idle) {
  const j = jobFor(kind, ep);
  if (!j && S.starting.has(`${kind}:${ep ?? ''}`)) return { label: `${idle} · 시작하는 중…`, attr: ' aria-disabled="true" aria-busy="true"' };
  if (!j) return { label: idle, attr: '' };
  // disabled 는 포커스를 잃게 해서 키보드 사용자가 문서 처음으로 돌아간다. aria-disabled 로 막고 포커스는 남긴다
  return { label: `${j.label} 만드는 중…${j.total > 1 ? ` ${j.done}/${j.total}` : ''}`, attr: ' aria-disabled="true" aria-busy="true"' };
}

/** 플롯 초안 작업이 아직 만들지 않은 화. 끝난 구간의 화는 작업이 도는 중에도 고치고 확정할 수 있다 (서버 job.pending). */
function jobOwns(n) {
  if (jobFor('plot_one', n)) return true;
  const j = jobFor('plots');
  if (!j || !P()) return false;
  if (Array.isArray(j.pending)) return j.pending.includes(n);
  return !ep(n) || ep(n).status === 'draft';  // 목록을 보내지 않는 옛 서버
}

/** 자동 집필이 이 작품을 고치는 중이다 (S.auto 는 작품을 열 때와 자동 집필 폴링 때 받는다). */
const autoOn = () => !!(S.auto && S.auto.active);
/** 자동 집필이 지금 쓰는 화. 서버는 그 화의 플롯과 관계 같은 진행 칸을 화면 저장에서 지킨다 (autorun.protected). */
const autoEp = () => (autoOn() && S.auto.run ? S.auto.run.ep : null);

/** AI 제안 카드의 버튼 줄. 모든 제안 카드가 같은 순서([버리기] [반영], 오른쪽)와 같은 말을 쓴다. 각 버튼은 [action, arg]. */
function proposalActions(drop, apply, label = '고른 것 적용') {
  const b = ([action, arg], cls, text) => `<button type="button" class="btn small${cls}" data-action="${action}"${arg != null ? ` data-arg="${esc(String(arg))}"` : ''}>${text}</button>`;
  return `<div class="row proposal-actions">${b(drop, '', '버리기')}${b(apply, ' primary', label)}</div>`;
}

/** AI 제안을 버리기 전에 묻는다. 버린 제안은 되살릴 수 없고 다시 받으려면 AI를 다시 불러야 한다. */
function confirmDrop(what) {
  return confirm(`${what}을 버릴까요? 되살릴 수 없어서, 다시 보려면 AI에게 다시 받아야 해요.`);  // 부르는 곳은 모두 받침 있는 말(제안, 계획)
}

/** 초안 다시 만들기 전에 묻는다: 확정하지 않은 초안 화는 AI 새 초안으로 바뀐다. 바뀔 초안이 없으면 묻지 않는다. */
function confirmRedraft(eps) {
  const nums = eps.filter((e) => e.status === 'draft').map((e) => e.plot.number);
  if (!nums.length) return true;
  return confirm(`초안 ${nums.length}화(${rangeText(nums)}화)를 AI 새 초안으로 바꿔요. 손본 내용도 사라져요. 지키려면 먼저 그 화를 확정하세요. 계속할까요?`);
}

/** [1,2,3,5,7,8] → '1~3, 5, 7~8' */
// 아크 끝 화를 다 고치면(포커스를 옮기면) 다시 나눈 구간 범위를 화면에 보인다. 입력 중에는 다시 그리지 않는다
document.addEventListener('change', (e) => {
  const b = e.target.dataset && e.target.dataset.bind;
  if (b && (b === 'arc.end_ep' || /^(story_arcs\.\d+\.(acts\.\d+\.)?|arc\.\d+\.)(start_ep|end_ep)$/.test(b))) render();
});

/** pipeline.act_ranges 와 같은 규칙: start~total 화를 weights 비율로 기승전결 네 구간에 나눈다. 함께 고친다. */
function actRanges(total, start, weights) {
  const size = total - start + 1;
  if (size < 1) return null;
  if (size < 4) return { 1: [0, 0, 0, 0], 2: [0, 0, 1, 1], 3: [0, 1, 2, 2] }[size].map((k) => [start + k, start + k]);
  const w = (weights || [0.18, 0.38, 0.26, 0.18]).map((x) => Math.max(x, 0.01));
  const sum = w.reduce((a, b) => a + b, 0);
  const raw = w.map((x) => (x / sum) * size);
  const lens = raw.map((r) => Math.max(1, Math.floor(r)));
  const argmax = (f) => [0, 1, 2, 3].reduce((b, i) => (f(i) > f(b) ? i : b), 0);
  while (lens.reduce((a, b) => a + b, 0) < size) lens[argmax((i) => raw[i] - lens[i])] += 1;
  while (lens.reduce((a, b) => a + b, 0) > size) lens[argmax((i) => lens[i])] -= 1;
  let a = start;
  return lens.map((n) => { const r = [a, a + n - 1]; a += n; return r; });
}

/** 아크 끝 화가 바뀌었다. 결 구간만 늘이거나 줄여 맞으면 그렇게 하고, 결이 시작 화보다 앞으로 오면 구간 길이 비율대로 다시 나눈다. */
function fitActs(arc, end) {
  const acts = [...arc.acts].sort((x, y) => '기승전결'.indexOf(x.name) - '기승전결'.indexOf(y.name));
  const last = acts[acts.length - 1];
  if (!last || !(end >= arc.start_ep)) return;
  if (end >= last.start_ep) { last.end_ep = end; return; }
  const r = actRanges(end, arc.start_ep, acts.map((x) => Math.max(1, x.end_ep - x.start_ep + 1)));
  if (r) acts.forEach((x, i) => { [x.start_ep, x.end_ep] = r[i]; });
}

function rangeText(nums) {
  const out = [];
  for (let i = 0; i < nums.length; i++) {
    let j = i;
    while (j + 1 < nums.length && nums[j + 1] === nums[j] + 1) j++;
    out.push(i === j ? `${nums[i]}` : `${nums[i]}~${nums[j]}`);
    i = j;
  }
  return out.join(', ');
}

async function startJob(kind, ep = null, extra = {}) {
  // 작업은 저장된 작품을 읽는다. 저장하지 않은 변경(검토 중인 AI 제안 포함)을 말없이 저장하지 않고 먼저 묻는다
  if (S.dirty && !confirm('저장하지 않은 변경이 있어요. 저장하고 작업을 시작할까요?')) return;
  // 응답이 오기 전에 또 누르면 같은 요청을 다시 보내지 않는다 (jobBtn 이 그동안 버튼을 막는다)
  const key = `${kind}:${ep ?? ''}`;
  if (S.starting.has(key)) return;
  S.starting.add(key);
  render();
  try {
    await saveIfDirty();
    const j = await api('POST', `/projects/${enc(S.name)}/jobs`, { kind, ep, ...extra });
    S.starting.delete(key);
    // 이미 도는 작업이면 버튼이 진행 상황을 보여 주므로 따로 알리지 않는다
    if (!j.already) toast(`${j.label}${josa(j.label, '을', '를')} 시작했어요. 끝나면 알려 드릴게요. 그동안 다른 작업을 해도 돼요.`);
    S.jobs = S.jobs.filter((x) => x.id !== j.id).concat(j);
    S.jobArgs[j.id] = { kind, ep, extra };  // 실패하면 작업 목록의 '다시 시도'가 같은 작업을 다시 시작한다
    renderJobs();
    render();
    pollJobs(true);
  } catch (e) {
    showError(e);
  } finally {
    if (S.starting.delete(key)) render();
  }
}

async function pollJobs(soon = false) {
  clearTimeout(jobTimer);
  if (soon) { jobTimer = setTimeout(() => pollJobs(), 800); return; }
  let list;
  try {
    list = await api('GET', '/jobs');
    if (S.jobsOffline) {
      // 다시 연결됐다. 그 사이 서버가 다시 시작돼 사라진 작업은 끝나지 못했다
      S.jobsOffline = false;
      const ids = new Set(list.map((j) => j.id));
      const lost = S.jobs.filter((j) => j.status === 'running' && !ids.has(j.id));
      if (lost.length) {
        toast(`서버가 다시 시작돼 작업이 끝나지 못했어요: ${lost.map((j) => j.label).join(', ')}. 다시 시작하세요`, true);
        if (S.route[0] === 'p') setTimeout(() => { if (!isTyping()) render(); });  // 잠겨 있던 버튼을 푼다
      }
    }
  } catch {
    S.jobsOffline = true;  // 작업 목록 머리에 '연결 끊김'을 보이고, 진행 중이던 작업이 있으면 계속 다시 묻는다
    list = S.jobs;
  }
  if (S.jobsSeen === null) S.jobsSeen = new Set(list.filter((j) => j.status !== 'running').map((j) => j.id));
  const before = new Map(S.jobs.map((j) => [j.id, j]));
  // 화면이 목록에서 지운(닫은) 작업은 다시 보이지 않게 한다
  S.jobs = list.filter((j) => !S.jobsSeen.has(j.id) || j.status === 'running');
  let redraw = false;
  let resultFocus = null;
  for (const j of S.jobs) {
    const old = before.get(j.id);
    const progressed = !old || old.done !== j.done || old.status !== j.status;
    if (progressed && j.project !== S.name && old && old.status === 'running' && j.status !== 'running') {
      // 다른 작품을 보는 동안 끝났다. 결과는 그 작품을 열면 다시 놓인다 (pending.json)
      toast(j.status === 'error' ? `${j.project} · ${j.label} 실패: ${j.error}` : `${j.project} · ${j.label}${josa(j.label, '이', '가')} 끝났어요. 그 작품을 열면 결과가 보여요`, j.status === 'error');
    }
    if (!progressed || j.project !== S.name) continue;
    if (j.kind === 'plots') {
      // 이번에 끝난 구간(지난번에 아직 만들던 화)과 새로 생긴 화만 받아 온다. 먼저 끝난 구간에서 고치던 초안은 그대로 둔다
      const was = old && Array.isArray(old.pending) ? new Set(old.pending) : null;
      await mergeEpisodes((cur, e) => cur.status === 'draft' && (!was || was.has(e.plot.number)));
      S.jobsMerged[j.id] = j.done;  // 저장할 때 이 단계까지 받아 왔다고 알린다 (save)
    }
    if (j.kind === 'write' && j.status !== 'running') await mergeEpisodes((e) => e.plot.number === j.ep);
    if (j.kind === 'plot_one' && j.status !== 'running') {
      await mergeEpisodes((e) => e.plot.number === j.ep);
      const r = j.result && j.result.realign && ep(j.result.realign);  // 뒤 화에 남긴 표시는 고치던 그 화 플롯을 덮지 않고 표시만 받는다
      if (r) r.realign = j.result.gap;
    }
    if (j.kind === 'impact' && j.status === 'done') await mergeImpacts();
    if (j.kind === 'check' && j.status === 'done') await mergeEpisodes((e) => e.plot.number === j.ep);  // 검수 결과는 그 화에 붙었다
    if (j.kind === 'auto') {
      // 다른 탭이나 명령줄에서 시작했어도 잠금(autoOn)이 걸리고, 끝나면 풀리게 실행 상태를 받아 온다. autoPoll 이 이어서 지켜본다
      if ((j.status === 'running') !== autoOn() && typeof autoLoad === 'function') await autoLoad(false);
      // 자동 집필이 실제로 바꾼 화(상태나 본문)만 받아 온다. 저장하지 않은 다른 화 플롯 수정은 그대로 둔다
      const dirty = S.dirty;
      const changed = await mergeEpisodes((cur, e) => cur.status !== e.status || cur.text !== e.text || !!cur.auto !== !!e.auto);
      if (dirty && changed.includes(S.selEp)) toast(`자동 집필이 ${S.selEp}화를 바꿨어요. 열린 플롯은 서버에 있는 것으로 바뀌어요`, true);
    }
    if (j.status !== 'running' && !(old && old.status !== 'running')) await finishJob(j);
    // 설정 · 사용량 · 문체 라이브러리처럼 작품 밖 화면은 S.name 이 남아 있어도 다시 그리지 않는다
    if (S.route[0] === 'p' && JOB_PAGES[j.kind].includes(S.route[2] || 'home')) {
      redraw = true;
      if (j.status === 'done') resultFocus = RESULT_FOCUS[j.kind] || '#app .proposal button, #app .proposal input';
    }
  }
  renderJobs();
  // 입력 중이거나 본문 글자를 고르고 있으면 화면을 다시 그리지 않는다 (글자 · 커서 · 선택을 잃지 않게). 데이터는 이미 반영돼 있고, 입력이나 선택을 마치면 그린다
  if (redraw && (isTyping() || selecting())) S.renderPending = true;
  else if (redraw) {
    // 포커스가 갈 곳 없이 BODY 나 작업 버튼에 있으면 도착한 결과로 옮긴다
    const a = document.activeElement;
    if (resultFocus && (!a || a === document.body || a.getAttribute('aria-busy') === 'true')) S.focusTarget = resultFocus;
    render();
  }
  if (S.jobs.some((j) => j.status === 'running')) jobTimer = setTimeout(() => pollJobs(), S.jobsOffline ? 4000 : 1500);
}

/** 입력칸에 포커스가 있다. #app 밖 떠 있는 본문 부분 수정 칸(#sel-tool)도 센다. 읽기 전용 칸은 빼서 결과를 바로 그린다. */
function isTyping() {
  const el = document.activeElement;
  return !!el && el.matches('input:not([readonly]), textarea:not([readonly]), select');
}

// 작업이 끝나 결과를 그린 뒤 포커스를 옮길 곳 (없으면 제안 카드의 첫 버튼)
const RESULT_FOCUS = { state: '#app [data-pick], #app [data-action="applyDelta"]', write: '#app textarea[data-draft], #app .rw-compare button',
  recap_part: '#app .drawer textarea[data-root="recaps"]', recap_arc: '#app textarea[data-root="recaps"]' };  // 요약 제안 칸은 서랍 · 카드 아래쪽이라 그리로 데려간다

/** #app 안에서 글자를 고르고 있다 (본문 부분 수정 · 삽화 도구를 띄우려고 드래그한 선택). */
function selecting() {
  const sel = document.getSelection();
  return !!sel && sel.rangeCount > 0 && !sel.isCollapsed && !!$('#app') && $('#app').contains(sel.anchorNode);
}

// 입력을 마치면(다른 입력칸이 아닌 곳으로 포커스가 가면) 입력 중이라 미뤄 둔 다시 그리기를 한다
document.addEventListener('focusout', () => setTimeout(() => { if (S.renderPending && !isTyping() && !selecting()) render(); }));
// 글자 선택을 풀면 선택 중이라 미뤄 둔 다시 그리기를 한다
document.addEventListener('selectionchange', () => setTimeout(() => { if (S.renderPending && !isTyping() && !selecting()) render(); }));  // 누른 버튼의 동작이 먼저 돈다

// 작업 결과가 보이는 화면
JOB_DONE_MSG.check = (j) => `${j.ep}화 검수가 끝났어요: 어긋난 곳 ${j.result ? j.result.issues : 0}개`;
const JOB_PAGES = { check: ['write'], suggest: ['setup'], arc: ['arc'], plots: ['arc', 'home', 'causal'], plot_one: ['arc', 'lines'], write: ['write', 'home', 'causal'], state: ['review'], auto: ['auto', 'home', 'write', 'causal', 'arc', 'setup'], impact: ['causal'], series: ['arc'], nextarc: ['arc'], recap_arc: ['arc'], recap_part: ['arc'], storyline: ['lines'] };

// 작업이 project.json 에 쓴 화만 받아 온다 (mine(화면 화, 서버 화) 이 true 인 화와 새로 생긴 화). 저장하지 않은 다른 입력은 그대로 둔다.
// 저장하지 않은 입력이 있을 때 서버 것으로 바꾼 화 번호를 돌려준다.
async function mergeEpisodes(mine) {
  if (!S.name || !P()) return [];
  try {
    const gen = S.gen;
    const fresh = await api('GET', `/projects/${enc(S.name)}`);
    // 받는 사이 저장 · 반영 응답이나 입력이 있었으면 이 응답이 더 오래됐을 수 있다. 통째로 바꾸지 않고 작업이 쓴 화만 맞춘다
    if (!S.dirty && gen === S.gen) { S.project = fresh; return []; }
    const local = new Map(P().episodes.map((e) => [e.plot.number, e]));
    const changed = [];
    for (const e of fresh.episodes) {
      const cur = local.get(e.plot.number);
      if (cur && !mine(cur, e)) continue;
      local.set(e.plot.number, e);
      if (projectBase) projectBase.plots.set(e.plot.number, JSON.stringify(e.plot));
      if (cur) changed.push(e.plot.number);
    }
    P().episodes = [...local.keys()].sort((a, b) => a - b).map((k) => local.get(k));
    return changed;
  } catch { return []; /* 다음 확인 때 다시 */ }
}

async function finishJob(j) {
  const here = j.project === S.name && P();
  const key = `${j.kind}:${j.ep ?? ''}`;
  if (j.status === 'cancelled') return;  // 멈춘 작업은 결과가 없다 (멈추기를 누를 때 알렸다)
  if (j.status === 'error') {
    toast(`${j.label} 실패: ${j.error}`, true);
    if (here) S.pending.failures[key] = { key, kind: j.kind, ep: j.ep, label: j.label, error: j.error };
    return;
  }
  if (here) {  // 서버가 pending.json 에 남긴 결과를 화면도 알아 둔다. 반영하거나 버리면 syncPending 이 지운다
    delete S.pending.failures[key];
    if (PENDING_KINDS.includes(j.kind) && j.result) S.pending.results[key] = { key, id: j.id, kind: j.kind, ep: j.ep };
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

// ---------- 검토를 기다리는 결과 · 실패 (서버 pending.json, web.PENDING_KINDS 와 같은 목록) ----------
const PENDING_KINDS = ['arc', 'suggest', 'series', 'nextarc', 'convert', 'rebuild', 'rework', 'storyline', 'recap_arc', 'recap_part', 'state', 'openings'];

/** 그 결과가 아직 화면에 제안으로 남아 있다. 반영하거나 버리면 false 가 된다. */
function pendingShown(r) {
  switch (r.kind) {
    case 'state': return S.deltas[r.ep] !== undefined;
    case 'arc': return !!S.arcProposal;
    case 'suggest': return !!S.suggestion;
    case 'series': return !!S.seriesDraft;
    case 'nextarc': return !!S.arcDraft;
    case 'recap_arc': return !!S.recapDrafts['arc' + r.ep];
    case 'recap_part': return !!S.recapDrafts['part' + r.ep];
    case 'storyline': return !!S.lineDraft;
    case 'convert': return !!S.convDraft;
    case 'rebuild': return !!S.rbDraft;
    case 'rework': return !!S.reworks[r.ep];
    case 'openings': return !!S.openingPlots[r.ep];
    default: return false;
  }
}

/** 작품을 열 때: 다른 탭 · 새로고침 전에 받은 결과를 다시 제안으로 놓고, 실패한 작업을 알 수 있게 받아 둔다. */
async function loadPending() {
  const d = await api('GET', `/projects/${enc(S.name)}/pending`).catch(() => null);
  if (!d) return;
  S.pending = { name: S.name, results: d.results, failures: d.failures };
  const keep = { selEp: S.selEp, selArc: S.selArc, selPart: S.selPart };  // 되살리면서 열린 화나 아크를 옮기지 않는다
  for (const r of Object.values(d.results)) {
    if (pendingShown(r) || S.jobsApplied.has(r.id)) continue;
    applyJobResult({ id: r.id, kind: r.kind, ep: r.ep, label: r.label, status: 'done', result: r.result, project: S.name });
    if (r.kind === 'state' && r.base != null) S.deltaBase[r.ep] = r.base;  // 변경안을 만든 본문. 그 뒤 고쳤으면 승인 화면이 알린다
  }
  Object.assign(S, keep);
}

/** 그린 뒤에 부른다: 화면에서 반영하거나 버린 결과는 서버에서도 지운다. */
function syncPending() {
  if (S.pending.name !== S.name || !P()) return;
  for (const r of Object.values(S.pending.results)) {
    if (pendingShown(r)) continue;
    delete S.pending.results[r.key];
    api('DELETE', `/projects/${enc(S.name)}/pending/${enc(r.key)}`).catch(() => { /* 다음에 다시 */ });
  }
}

/** 이 화면에서 볼 만한 지난 실패. 같은 작업이 성공하거나 닫으면 사라진다. */
function failStrip(page, n) {
  if (S.pending.name !== S.name) return '';
  const list = Object.values(S.pending.failures).filter((f) => (JOB_PAGES[f.kind] || []).includes(page || 'home') && (f.ep == null || !['write', 'review', 'brief'].includes(page) || f.ep === n));
  return list.map((f) => `<div class="note warn between" role="status"><span><strong>지난 시도 실패</strong> · ${esc(f.label)}: ${esc(f.error)}${/API 키|연결/.test(f.error) ? ' <a href="#/settings">모델 · API 키 설정</a>' : ''}</span><button type="button" class="btn small" data-action="dismissFail" data-arg="${esc(f.key)}">닫기</button></div>`).join('');
}

function applyJobResult(j) {
  S.jobsApplied.add(j.id);
  if (j.status !== 'done') return;  // 실패한 작업은 아무것도 바꾸지 않았다. 열어 봐도 초안과 변경안을 그대로 둔다
  if (j.kind === 'suggest' && j.result) {
    S.suggestion = j.result;
    S.suggestion.characters.forEach((c, i) => { S.picks['sc' + i] = !sameChar(c); });
    S.suggestion.relationships.forEach((r, i) => { S.picks['sr' + i] = true; });
  } else if (j.kind === 'arc' && j.result) {
    S.arcProposal = j.result.acts;  // 바로 바꾸지 않고 지금 구조와 비교해 고르게 한다 (arcProposalCard)
  } else if (j.kind === 'write' && !(j.result && j.result.candidate)) {
    // AI가 본문을 새로 썼다 (새 판 candidate 는 본문을 덮지 않으니 쓰던 초안과 변경안을 그대로 둔다).
    // 그 화 칸에 쓰던 글이 있으면(다른 탭에서 시작한 작업 등) 버리지 않고 칸에 남긴다. 저장하면 수정 기록에 남아 되돌릴 수 있다
    const d = S.textDraft[j.ep];
    if (d && d.trim() && ep(j.ep) && d !== ep(j.ep).text) toast(`${j.ep}화 본문을 AI가 새로 썼어요. 쓰던 글은 칸에 남겨 두었어요. 저장하면 AI 본문 대신 그 글이 들어가요`, true);
    else delete S.textDraft[j.ep];
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
    S.recapDrafts[kind + j.ep] = { kind, number: j.ep, summary: j.result.summary };
    if (kind === 'arc') S.selArc = j.ep;
    else S.selPart = j.ep;
  } else if (['convert', 'rebuild', 'rework'].includes(j.kind) && j.result) {
    convertResult(j);
  } else if (j.kind === 'storyline' && j.result) {
    S.lineDraft = { ...j.result, picks: {} };
  } else if (['hook', 'openings', 'opening_drafts'].includes(j.kind)) {
    openingJobResult(j);
  }
}

const JOB_LINK = {
  suggest: (j) => `#/p/${enc(j.project)}/setup`,
  arc: (j) => `#/p/${enc(j.project)}/arc`,
  plots: (j) => `#/p/${enc(j.project)}/arc`,
  plot_one: (j) => `#/p/${enc(j.project)}/arc`,
  write: (j) => `#/p/${enc(j.project)}/write/${j.ep}`,
  check: (j) => `#/p/${enc(j.project)}/write/${j.ep}`,
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
    // 알림 영역으로 두지 않는다. 경과 시간 때문에 자주 다시 그려 화면 낭독기가 목록을 되풀이해 읽는다. 시작 · 끝 · 실패는 토스트(#toast)가 알린다
    box = document.createElement('section');
    box.id = 'jobs';
    box.setAttribute('aria-label', 'AI 작업');
    document.body.appendChild(box);
  }
  if (!S.jobs.length) { box.innerHTML = ''; box.dataset.html = ''; box.hidden = true; return; }
  box.hidden = false;
  const running = S.jobs.filter((j) => j.status === 'running');
  const failed = S.jobs.filter((j) => j.status === 'error');
  // 접힌 머리에도 하나뿐인 작업의 이름 · 진행률과 실패 수를 보인다
  const one = running.length === 1 ? `${running[0].label}${running[0].total > 1 ? ` ${running[0].done}/${running[0].total}` : ''}` : '';
  const head = S.jobsOffline ? '서버 연결이 끊겼어요. 다시 연결하는 중…'
    : running.length ? `${one ? `AI 작업 진행 중 · ${one}` : `AI 작업 ${running.length}개 진행 중`}${failed.length ? ` · ${failed.length}개 실패` : ''}`
      : `AI 작업 끝남${failed.length ? ` · ${failed.length}개 실패` : ''}`;
  // 새 실패가 생기면 접혀 있어도 펼쳐 알린다. 그 뒤 접고 펴기는 사용자가 정한다
  const fresh = failed.filter((j) => !S.jobsFailed.has(j.id));
  if (fresh.length) { fresh.forEach((j) => S.jobsFailed.add(j.id)); S.jobsOpen = true; }
  const items = S.jobs.map((j) => {
    const pct = j.total > 1 ? ` ${j.done}/${j.total}` : '';
    const wait = j.kind === 'auto' && j.status === 'done' && j.result && { review: '검토 필요', paused: '멈춤', error: '오류' }[j.result.status];
    const state = j.status === 'running' ? `<span class="spinner sm" aria-hidden="true"></span>` : wait ? `<span class="wait">${wait}</span>` : j.status === 'done' ? '<span class="ok">완료</span>' : j.status === 'cancelled' ? '<span class="small">멈춤</span>' : '<span class="bad">실패</span>';
    const other = j.project !== S.name ? ` <span class="small">· ${esc(j.project)}</span>` : '';
    const sub = j.status === 'error' ? j.error : j.status === 'running' ? [j.note, `경과 ${elapsed(j)}`].filter(Boolean).join(' · ') : j.note;
    const open = j.status === 'done' && j.kind in JOB_LINK ? `<a href="${JOB_LINK[j.kind](j)}" data-job-open="${j.id}">열기</a>` : '';
    const retry = j.status === 'error' && S.jobArgs[j.id] ? `<button type="button" class="btn small" data-job-retry="${j.id}">다시 시도</button>` : '';
    const keyHelp = j.status === 'error' && /API 키|연결/.test(j.error || '') ? '<a href="#/settings">설정</a>' : '';
    const stop = j.status === 'running' && j.kind !== 'auto' ? `<button type="button" class="btn small" data-job-stop="${j.id}">멈추기</button>` : '';
    return `<li>${state}<div class="jl"><strong>${esc(j.label)}${pct}</strong>${other}${sub ? `<div class="small">${esc(sub)}</div>` : ''}</div>${open}${retry}${keyHelp}${stop}${j.status !== 'running' ? `<button type="button" class="x" data-job-dismiss="${j.id}" aria-label="목록에서 지우기">✕</button>` : ''}</li>`;
  }).join('');
  // 넓은 화면은 펼쳐 경과 시간과 '멈추기'를 보인다. 휴대폰은 접어 둔다 (저장 띠와 버튼을 가리지 않게). 머리를 누르면 바꾼다
  const open = S.jobsOpen === null ? !narrowScreen() : S.jobsOpen;
  const html = `<button type="button" class="jobs-head${failed.length ? ' bad' : ''}" aria-expanded="${open}" data-jobs-toggle>${running.length ? '<span class="spinner sm" aria-hidden="true"></span>' : ''}${head}</button>${open ? `<ul>${items}</ul>` : ''}`;
  if (box.dataset.html === html) return;
  // 목록 안 버튼(멈추기 · 다시 시도)에 있던 포커스를 다시 그린 뒤 같은 버튼에 돌려준다
  const f = box.contains(document.activeElement) ? document.activeElement : null;
  const key = f && ['data-job-stop', 'data-job-retry', 'data-job-dismiss', 'data-job-open', 'data-jobs-toggle'].find((a) => f.hasAttribute(a));
  const val = key ? f.getAttribute(key) : null;
  box.dataset.html = html;
  box.innerHTML = html;
  if (key) {
    const back = box.querySelector(key === 'data-jobs-toggle' ? '[data-jobs-toggle]' : `[${key}="${CSS.escape(val)}"]`) || box.querySelector('[data-jobs-toggle]');
    if (back) back.focus();
  }
  stackBottom();
}

/** 작업이 시작된 뒤 지난 시간 'm:ss' (서버 시각 기준이라 몇 초 어긋날 수 있다). */
function elapsed(j) {
  const s = Math.max(0, Math.round(Date.now() / 1000 - j.started));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

const narrowScreen = () => window.matchMedia('(max-width: 640px)').matches;

/** 화면 아래 고정 층(저장 띠, 작업 목록, 알림)이 서로와 본문 버튼을 가리지 않게 높이를 CSS 변수로 둔다.
    --sb: 저장 띠 높이, --jb: 작업 목록 높이(좁은 폭에서 저장 띠 위에 쌓을 때). */
function stackBottom() {
  const h = (el) => (el && !el.hidden ? el.getBoundingClientRect().height + 12 : 0);
  const st = document.body.style;
  st.setProperty('--sb', `${h($('#savebar'))}px`);
  st.setProperty('--jb', `${narrowScreen() ? h($('#jobs')) : 0}px`);
}
window.addEventListener('resize', () => stackBottom());

document.addEventListener('click', (e) => {
  const t = e.target.closest('[data-jobs-toggle], [data-job-dismiss], [data-job-open], [data-job-stop], [data-job-retry]');
  if (!t) return;
  if (t.dataset.jobsToggle !== undefined) {
    S.jobsOpen = !(S.jobsOpen === null ? !narrowScreen() : S.jobsOpen);
  } else if (t.dataset.jobDismiss) {
    S.jobsSeen.add(t.dataset.jobDismiss);
    S.jobs = S.jobs.filter((j) => j.id !== t.dataset.jobDismiss);
  } else if (t.dataset.jobOpen) {
    // 다른 작품에서 끝난 결과는 그 작품을 연 뒤에 적용한다
    const j = S.jobs.find((x) => x.id === t.dataset.jobOpen);
    if (j && j.status === 'done') S.pendingJob = j;
  } else if (t.dataset.jobStop) {
    const j = S.jobs.find((x) => x.id === t.dataset.jobStop);
    if (!j || !confirm(`${j.label}${josa(j.label, '을', '를')} 멈출까요? 이미 보낸 AI 호출의 응답은 버려요 (비용은 들 수 있어요).`)) return;
    api('POST', `/jobs/${j.id}/stop`).then((x) => {
      Object.assign(j, x);
      toast(`${j.label}${josa(j.label, '을', '를')} 멈췄어요`);
      renderJobs();
      if (S.route[0] === 'p' && !isTyping()) render();  // 잠겨 있던 버튼을 푼다
    }).catch((err) => toast(err.message, true));
    return;
  } else if (t.dataset.jobRetry) {
    const a = S.jobArgs[t.dataset.jobRetry];
    S.jobsSeen.add(t.dataset.jobRetry);
    S.jobs = S.jobs.filter((j) => j.id !== t.dataset.jobRetry);
    if (a) startJob(a.kind, a.ep, a.extra);
  }
  renderJobs();
});

/** 버튼 동작 공통 처리: 진행 표시, 오류 알림, 다시 그리기. 성공하면 true.
    opt.render: 'always'(기본) | 'success'(실패하면 다시 그리지 않아 화면에만 있는 입력을 남긴다) | 'never' */
/** 실패를 알린다. API 키가 없으면(첫 실행에 흔하다) 설정 화면으로 갈지 묻는다. */
function showError(e) {
  if (e.code === 'no_key') {
    if (confirm(`${e.message}\n\n설정 화면으로 갈까요?`)) location.hash = '#/settings';
    return;
  }
  toast(e.message, true);
}

// run() 이 기다리는 요청. 5초가 넘으면 화면 가운데 상자에 경과 시간과 '기다리지 않기'를 보인다 (api 가 이 신호를 쓴다)
let runAbort = null;

async function run(label, fn, opt = {}) {
  const when = opt.render || 'always';
  let ok = false;
  const t0 = Date.now();
  runAbort = new AbortController();
  $('#busy-text').textContent = label;
  $('#busy-stop').hidden = true;
  $('#busy').hidden = false;
  // 기다리는 동안 뒤 화면을 키보드로도 못 건드리게 막고 포커스를 상자로 옮긴다. 끝나면 누른 버튼으로 돌려준다
  const back = document.activeElement;
  const walls = ['#app', '#jobs', '#savebar'].map((q) => $(q)).filter(Boolean);
  walls.forEach((el) => { el.inert = true; });
  $('#busy .busy-box').focus();
  const tick = setInterval(() => {
    const s = Math.round((Date.now() - t0) / 1000);
    $('#busy-text').textContent = `${label} · ${s}초`;
    if (s >= 5) $('#busy-stop').hidden = false;
  }, 1000);
  try {
    await fn();
    ok = true;
  } catch (e) {
    showError(e);
  } finally {
    clearInterval(tick);
    runAbort = null;
    // 그리는 사이 새로 생긴 저장 띠 · 작업 목록도 함께 푼다
    [...walls, ...['#app', '#jobs', '#savebar'].map((q) => $(q)).filter(Boolean)].forEach((el) => { el.inert = false; });
    $('#busy').hidden = true;
    if (back && back.isConnected && back !== document.body) back.focus({ preventScroll: true });  // 다시 그리기가 이 자리를 기억한다
    if (when === 'always' || (when === 'success' && ok)) render();
  }
  return ok;
}

/** '기다리지 않기': 화면 잠금을 풀고 응답을 버린다. 서버에 이미 간 요청은 끝까지 돌 수 있다. */
document.addEventListener('click', (e) => {
  if (e.target.id === 'busy-stop' && runAbort) runAbort.abort();
});

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
  const c = P().characters.find((x) => x.id === id) || (P().cast_candidates || []).find((x) => x.id === id);
  return c ? c.name || id : id;
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
const DRAFT_ROOTS = { arcDraft: () => S.arcDraft, seriesDraft: () => S.seriesDraft, recaps: () => S.recapDrafts, arcForm: () => S.arcForm };

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
  // 0 이 '정하지 않음'인 화 번호 칸은 0 대신 빈칸과 안내 글을 보인다 (지우면 0 으로 저장된다)
  const raw = bindValue(path, kind, opt.root);
  const val = esc(opt.zeroBlank && Number(raw) === 0 ? '' : raw);
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
    const loglinePrev = el.dataset.bind.startsWith('meta.logline_parts.') ? composeLogline(P().meta.logline_parts) : undefined;
    setPath(root, el.dataset.bind, v);
    if (el.dataset.root === 'lib') { S.libDirty = true; renderSavebar(); }
    else if (!DRAFT_ROOTS[el.dataset.root]) markDirty();
    const arcEnd = el.dataset.root === 'arcDraft' && el.dataset.bind === 'arc.end_ep' ? S.arcDraft.arc
      : (el.dataset.bind.match(/^story_arcs\.(\d+)\.end_ep$/) && !el.dataset.root) ? P().story_arcs[Number(el.dataset.bind.split('.')[1])] : null;
    if (arcEnd) fitActs(arcEnd, v);  // 아크 끝 화를 바꾸면 구간도 따라간다 (서버 clean_arc · fit_arc 와 같은 결과)
    const cnt = el.id === 'f-sample' && $('#lib-sample-count');
    if (cnt) cnt.textContent = v.length.toLocaleString();
    const out = el.dataset.out && document.getElementById(el.dataset.out);
    if (out) out.textContent = v;
    if (el.dataset.bind.startsWith('meta.logline_parts.')) updateLogline(loglinePrev);
    if (el.dataset.bind === 'meta.logline') { const mn = $('#logline-manual'); if (mn) mn.innerHTML = loglineManualHtml(P().meta); }
    const rel = el.dataset.bind.match(/^relationships\.(\d+)\.(a|b)$/);
    if (rel) refreshRel(Number(rel[1]));
  }
  if (el.dataset.draft) {
    S.textDraft[el.dataset.draft] = el.value;
    const c = $('#char-count');
    if (c) c.textContent = el.value.length.toLocaleString();
    const sb = $('#save-text');
    if (sb) {
      sb.disabled = autoOn();  // 자동 집필 중에는 서버가 본문 저장을 받지 않는다
      sb.classList.toggle('primary', textUnsaved(el.dataset.draft));  // 저장하지 않은 고침이 있으면 눈에 띄게
      if (!autoOn()) sb.removeAttribute('title');
    }
    renderSavebar();
  }
  if (el.dataset.brief) S.briefDraft[`${S.name}:${el.dataset.brief}`] = el.value;
  if (el.id === 'imp-body' && $('#imp-count')) $('#imp-count').innerHTML = importCount(el.value);
  if (S.route[0] === 'settings' && el.id && el.id.startsWith('set-')) S.settingsDirty = true;
  if (el.dataset.local) S[el.dataset.local] = el.value;
  if (el.dataset.deltaSummary) {
    S.deltas[el.dataset.deltaSummary].summary = el.value;
    const c = $('#dsum-count');
    if (c) c.textContent = el.value.length.toLocaleString();
  }
  if (el.dataset.attire != null) {  // 상태 승인 화면에서 고친 지금 차림 (반영 때 변경안 그대로 보낸다)
    const d = S.deltas[el.dataset.attireEp];
    const u = d && d.character_updates[+el.dataset.attire];
    if (u) u.attire = el.value;
  }
});

document.addEventListener('change', (e) => {
  const el = e.target;
  if (el.dataset.pick) {
    S.picks[el.dataset.pick] = el.checked;
    document.querySelectorAll('#app .pick-count').forEach((c) => { c.textContent = deltaPicked(); });
    if (S.route[2] === 'review' && /^[ers]\d/.test(el.dataset.pick)) refreshPreview(Number(S.route[3]));
    if (S.route[2] === 'setup' && /^sc\d/.test(el.dataset.pick)) render();  // 고른 인물에 따라 넣을 수 있는 관계가 바뀐다
  }
  if (el.name === 'np-form') {  // 형식을 바꾸면 총 화수 기본값도 바꾼다
    const eps = $('#np-eps');
    if (eps && ['', '12', '300'].includes(eps.value.trim())) eps.value = el.value === 'serial' ? 300 : 12;  // 직접 적은 화수는 그대로 둔다
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
  // 플롯 서랍에서 새 인물 이름을 정해도 점검한다 (장편은 인물이 주로 플롯에서 는다)
  if (S.route[2] === 'arc' && /^characters\.\d+\.name$/.test(bind || '')) { checkNames(); return; }
  if (S.route[2] !== 'setup' || !bind) return;
  if (bind === 'world.name_style') {  // 스타일을 바꾸면 이전 후보는 버리고 다시 점검한다
    S.names = {};
    S.placeKind = '';
    checkNames().then(render);
  } else if (/^characters\.\d+\.(name|age|gender)$/.test(bind) || /^world\.(era|setting|rules|locations)$/.test(bind) || /^meta\.(logline|notes|logline_parts\.\w+)$/.test(bind)) {
    checkNames();  // naming.detect_style 이 보는 칸: 자동 이름 스타일과 경고가 바뀔 수 있다
  }
});

// 이름을 고치면 그 인물 카드 머리 이름도 바로 바꾼다 (경고 글과 카드 이름을 맞춰 보게)
document.addEventListener('input', (e) => {
  const m = S.route[2] === 'setup' && (e.target.dataset.bind || '').match(/^characters\.(\d+)\.name$/);
  const head = m && document.querySelector(`[data-char-head="${m[1]}"]`);
  if (head) head.textContent = e.target.value.trim() || '이름 없음';
});

// 탭에서 ← → Home End 로 다른 탭을 고른다. 고른 탭은 다시 그린 뒤에도 포커스를 받는다
document.addEventListener('keydown', (e) => {
  const tab = e.target.closest && e.target.closest('[role="tab"]');
  if (!tab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
  const tabs = [...tab.closest('[role="tablist"]').querySelectorAll('[role="tab"]')];
  const i = tabs.indexOf(tab);
  const next = tabs[e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : (i + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
  e.preventDefault();
  const sel = `#app [role="tab"][data-action="${CSS.escape(next.dataset.action || '')}"]${next.dataset.arg !== undefined ? `[data-arg="${CSS.escape(next.dataset.arg)}"]` : ''}`;
  S.focusTarget = sel;
  next.click();
  if (document.querySelector(sel)) document.querySelector(sel).focus();  // 다시 그리지 않는 탭(같은 화면 안 전환)도 포커스를 옮긴다
});

// Ctrl+S (macOS 는 Cmd+S): 집필 화면에서 고친 본문이 있으면 본문을, 아니면 작품 변경을 저장한다. 브라우저의 '페이지 저장'은 막는다
document.addEventListener('keydown', (e) => {
  if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== 's' || e.isComposing) return;
  e.preventDefault();
  const [p, , page, arg] = S.route;
  const n = p === 'p' && page === 'write' && P() ? Number(arg) || currentEp() : null;
  if (n !== null && textUnsaved(n) && editableEp(ep(n))) actions.saveText(n);
  else if (S.dirty) actions.save();
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
  S.gen++;
  if (!S.dirty) {
    S.dirty = true;
    renderSavebar();
  }
}

/** 본문 초안이 저장한 본문과 다르다. '직접 쓰기'로 빈 칸만 연 것은 세지 않는다. */
function textUnsaved(n) {
  const d = S.textDraft[n];
  if (d === undefined) return false;
  const e = P() && ep(Number(n));
  return e ? d.trim() !== (e.text || '').trim() : d.trim() !== '';  // 서버는 앞뒤 공백을 지워 저장한다
}

/** 저장 띠를 만든다. 처음 뜰 때 화면 낭독기에 한 번 알린다 (띠는 문서 끝에 붙어 Tab 으로는 늦게 닿으니 Ctrl+S 도 알린다). */
function newSavebar(shortcut = true) {
  const bar = document.createElement('div');
  bar.id = 'savebar';
  bar.className = 'savebar';
  bar.setAttribute('role', 'region');
  bar.setAttribute('aria-label', '저장하지 않은 변경');
  document.body.appendChild(bar);
  const live = $('#sr-live');
  if (live) live.textContent = `저장하지 않은 변경이 있어요.${shortcut ? ' Ctrl+S 로 저장할 수 있어요.' : ''}`;
  return bar;
}

function renderSavebar() {
  // 본문 초안은 따로 '본문 저장'으로 저장한다. 그 화를 보고 있을 때만 알린다 (다른 화면으로 가도 초안은 메모리에 남는다)
  const [p, , page, arg] = S.route;
  const n = p === 'p' && page === 'write' && P() ? Number(arg) || currentEp() : null;
  const text = n !== null && textUnsaved(n) && editableEp(ep(n)) ? n : null;  // 반영이 끝난 화의 남은 초고는 집필 화면이 따로 꺼내 보인다
  const lib = S.route[0] === 'styles' && !!S.route[1] && S.libDirty;  // 라이브러리 항목은 작품과 따로 저장한다
  const rb = $('[data-action="libRevert"]');
  if (rb) rb.disabled = !S.libDirty;
  let bar = $('#savebar');
  if (lib) {
    if (!bar) bar = newSavebar(false);  // 라이브러리 항목은 Ctrl+S 가 저장하지 않는다
    if (bar.dataset.sig !== 'lib') {
      bar.dataset.sig = 'lib';
      bar.innerHTML = '<span>문체를 저장하지 않았어요</span><button class="btn small" data-action="libRevert">저장 전으로</button><button class="btn small primary" data-action="libSave">저장</button>';
    }
    stackBottom();
    return;
  }
  if ((!S.dirty || !P()) && text === null) {
    if (bar) bar.remove();
    stackBottom();
    return;
  }
  const sig = `${S.dirty}:${text}:${autoOn()}:${S.conflict}:${S.lastRemoved ? S.lastRemoved.label : ''}`;
  if (bar && bar.dataset.sig === sig) return;
  if (!bar) bar = newSavebar();
  bar.dataset.sig = sig;
  bar.innerHTML = (S.dirty && S.conflict ? '<span>다른 탭이나 기기에서 먼저 저장해 이 변경을 저장하지 못했어요</span><button class="btn small" data-action="revert">다시 불러오기 (이 변경 버림)</button><button class="btn small danger" data-action="saveForce">내 변경으로 덮기</button>'
    : S.dirty ? `<span>저장하지 않은 변경이 있어요</span>${S.lastRemoved ? `<button class="btn small" data-action="restoreRemoved">방금 지운 ${esc(S.lastRemoved.label)} 되살리기</button>` : ''}<button class="btn small" data-action="revert">변경 모두 버리기</button><button class="btn small primary" data-action="save" title="저장 (Ctrl+S)">저장</button>` : '')
    + (text !== null ? `<span>${text}화 본문을 저장하지 않았어요</span><button class="btn small primary" data-action="saveText" data-arg="${text}"${autoOn() ? ' disabled title="자동 집필이 도는 동안은 본문을 저장할 수 없어요"' : ' title="본문 저장 (Ctrl+S)"'}>본문 저장</button>` : '');
  stackBottom();
}

/** 지시서 ② 칸 글을 아직 쓸 수 있다. 본문 칸은 확정 · 작성 화, JSON 칸은 작성 화에서만 열린다. 다른 경로로 그 화를 끝냈으면 세지 않는다. */
function briefPending(key, v) {
  if (!v.trim()) return false;
  const [name, n, tab] = key.split(':');
  if (name !== S.name || !P()) return true;
  const e = ep(Number(n));
  return !!e && (tab === 'state' ? e.status === 'written' : e.status === 'confirmed' || e.status === 'written');
}

/** 반영하지 않은 상태 변경안. 변경안은 본문이 작성된 화에만 반영하므로 이미 반영이 끝난 화의 것은 세지 않는다. */
const deltaPending = (n) => { const e = P() && ep(Number(n)); return !e || e.status === 'written'; };

/** 페이지를 떠나면 사라지는 입력: 저장하지 않은 작품 · 문체 · 설정 변경, 본문 초안, 붙여 넣은 지시서 결과, 반영하지 않은 상태 변경안 */
function hasUnsaved() {
  return S.dirty || S.libDirty || S.settingsDirty
    || Object.keys(S.textDraft).some(textUnsaved)
    || Object.entries(S.briefDraft).some(([k, v]) => briefPending(k, v))
    || Object.keys(S.deltas).some(deltaPending)
    || Object.values(stash).some((s) => Object.keys(s.textDraft).length > 0 || Object.keys(s.deltas).length > 0);  // 보관할 때 정리했다
}

// 다른 탭 · 기기에서 시작한 작업은 이 탭이 묻기 전에는 모른다. 탭으로 돌아오면 한 번 묻는다
window.addEventListener('focus', () => pollJobs());
document.addEventListener('visibilitychange', () => { if (!document.hidden) pollJobs(); });

// 새로고침 · 탭 닫기 · 주소 직접 입력은 hashchange 확인을 거치지 않는다. 브라우저가 묻게 한다
window.addEventListener('beforeunload', (e) => {
  if (!hasUnsaved()) return;
  e.preventDefault();
  e.returnValue = '';
});

async function save(force = false) {
  // 끝난 작업 중 결과를 이미 받아 온 것을 알려야 서버가 그 화를 덮어써도 된다고 안다
  // 도는 플롯 작업은 받아 온 단계까지 '<id>:<done>' 으로 알린다. 서버가 그 단계에서 끝난 화를 화면 저장으로 받는다
  const steps = S.jobs.filter((j) => j.status === 'running' && S.jobsMerged[j.id]).map((j) => `${j.id}:${S.jobsMerged[j.id]}`);
  const merged = [...S.jobs.filter((j) => j.status !== 'running').map((j) => j.id), ...(S.jobsSeen || []), ...steps].join(',');
  const meta = {};
  const sent = P();
  const base = projectBase;
  const edited = (k) => !base || (k.field === 'relationships' ? JSON.stringify(sent.relationships) !== base.rels
    : JSON.stringify((sent.episodes.find((e) => e.plot.number === k.ep) || {}).plot) !== base.plots.get(k.ep));
  try {
    S.project = await api('PUT', `/projects/${enc(S.name)}?merged=${enc(merged)}${force ? '&force=true' : ''}`, sent, meta);
  } catch (e) {
    if (e.status === 409) {  // 다른 화면이 먼저 저장했다. 저장 띠에서 다시 불러오기와 덮어쓰기 중에 고른다
      S.conflict = true;
      renderSavebar();
    }
    throw e;
  }
  S.dirty = false;
  S.conflict = false;
  // 서버가 작업 · 자동 집필 · 다른 곳의 반영을 지키느라 화면 값 대신 서버 것을 둔 칸. 화면이 고친 칸이면 성공 토스트만으로는 버린 줄 모른다
  const head = meta.headers && meta.headers.get('X-Canon-Kept');
  const kept = head ? JSON.parse(decodeURIComponent(head)) : [];
  const dropped = kept.filter((k) => k.field !== 'character' && edited(k)).map((k) => (k.field === 'relationships' ? '관계' : `${k.ep}화 플롯`));
  const kin = kept.filter((k) => k.field === 'character').map((k) => k.name);
  if (dropped.length) toast(`작업이나 반영된 진행과 겹쳐 이 부분은 저장하지 않고 서버에 있는 것으로 두었어요: ${dropped.join(', ')}`, true);
  if (kin.length) toast(`이 화면이 모르는 사이 반영으로 더해진 인물(${kin.join(', ')})은 지우지 않고 남겼어요`);
  if (S.route[2] === 'style') { await loadStyleLink(); await learnLoad(); }
  if (S.route[2] === 'causal') await causalLoad();
  return !dropped.length;
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
    await run('저장 중', async () => { if (await save() !== false) toast('저장했어요'); });
  },
  async revert() {
    if (S.dirty && !confirm('저장하지 않은 변경을 모두 버리고 저장된 작품을 다시 불러올까요? 되돌릴 수 없어요.')) return;
    await run('불러오는 중', async () => { await loadProject(S.name); if (S.route[2] === 'style') await loadStyleLink(); });
  },
  /** n화부터 상태 반영을 취소한다 (n-1화 반영 직후로). 본문은 남고, n화 변경안은 다시 골라 반영할 수 있게 채워 둔다. */
  async revertFrom(n) {
    n = Number(n);
    const fin = P().episodes.filter((e) => e.status === 'finalized' && e.plot.number >= n).map((e) => e.plot.number);
    const h = [...P().history].reverse().find((d) => d.episode === n);
    const added = P().history.filter((d) => d.episode >= n).flatMap((d) => d.new_characters || []).map((c) => c.name || c.id);
    const places = (P().elements || []).filter((el) => el.found_in === '본문' && el.found_ep >= n).map((el) => el.name);
    if (!confirm(`${rangeText(fin)}화의 상태 반영을 취소할까요? ${n - 1 ? `${n - 1}화 반영 직후` : '1화 시작 전'} 상태로 돌아가고, 본문은 남아 상태 승인을 다시 하게 돼요.${added.length ? ` 그 반영이 더한 인물(${added.join(', ')})도 빠져요.` : ''}${places.length ? ` 본문에서 등록한 장소(${places.join(', ')})도 빠져요. 아직 안 쓴 화 플롯에 나오거나 직접 고친 장소는 남아요.` : ''}`)) return false;
    return run('반영을 취소하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/revert/${n - 1}`);
      if (h) setDelta(n, structuredClone(h));  // 반영했던 변경안을 다시 고를 수 있게 둔다
      toast(`${rangeText(fin)}화의 반영을 취소했어요. ${n}화 변경안을 다시 골라 적용하세요`);
    });
  },
  railAll() {
    S.railAll = true;
    render();
  },
  focusName(i) {
    const el = document.getElementById(`f-characters-${i}-name`);
    if (el) { el.scrollIntoView({ block: 'center' }); el.focus(); }
  },
  toggleMenu() {
    S.menuOpen = !S.menuOpen;  // 좁은 폭에서만 보이는 버튼. 메뉴를 고르면 화면 이동 때 닫힌다
    render();
  },
  async dupProject(name) {
    const to = prompt(`'${name}' 의 사본 폴더 이름`, `${name}-사본`);
    if (!to) return;
    await run('복제하는 중', async () => {
      await api('POST', `/projects/${enc(name)}/duplicate`, { name: to.trim() });
      S.projects = await api('GET', '/projects');
      toast(`'${to.trim()}' 로 복제했어요`);
    });
  },
  async renameProject(name) {
    const to = prompt(`'${name}' 의 새 폴더 이름 (주소가 바뀌어요. 작품 제목은 설정 도우미에서 바꿔요)`, name);
    if (!to || to.trim() === name) return;
    await run('이름을 바꾸는 중', async () => {
      await api('POST', `/projects/${enc(name)}/rename`, { name: to.trim() });
      S.projects = await api('GET', '/projects');
      toast(`폴더 이름을 '${to.trim()}' 로 바꿨어요`);
    });
  },
  async deleteProject(name) {
    const x = (S.projects || []).find((y) => y.name === name) || { title: name };
    const typed = prompt(`'${x.title || name}' 작품을 지울까요? 서버의 projects/.trash 로 옮겨 두지만 화면에서는 되살릴 수 없어요.\n지우려면 작품 제목을 그대로 적으세요.`);
    if (typed === null) return;
    if (typed.trim() !== (x.title || name)) return toast('제목이 달라 지우지 않았어요', true);
    await run('지우는 중', async () => {
      await api('DELETE', `/projects/${enc(name)}`);
      S.projects = await api('GET', '/projects');
      toast('작품을 지웠어요. 서버의 projects/.trash 에 남아 있어요');
    });
  },
  async checkEp(n) {
    await startJob('check', Number(n));
  },
  /** 긴 화면의 구역으로 간다. 해시를 바꾸면 화면 이동이 되므로 스크롤과 포커스만 옮긴다. */
  jumpTo(id) {
    const sec = document.getElementById(id);
    if (!sec) return;
    sec.scrollIntoView({ block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    const h = sec.querySelector('h2');
    if (h) { h.setAttribute('tabindex', '-1'); h.focus({ preventScroll: true }); }
  },
  async retryRoute() {
    await route();
  },
  async dismissFail(key) {
    delete S.pending.failures[key];
    render();
    await api('DELETE', `/projects/${enc(S.name)}/pending/${enc(key)}?failure=true`).catch(() => {});
  },
  restoreRemoved() {
    const r = S.lastRemoved;
    if (!r) return;
    for (const [k, v] of r.saved) {
      const parts = k.split('.');
      const last = parts.pop();
      parts.reduce((o, x) => o[x], P())[last] = v;
    }
    S.lastRemoved = null;
    markDirty();
    render();
    toast(`${r.label}을(를) 되살렸어요`);
  },
  async saveForce() {
    if (!confirm('다른 탭이나 기기에서 저장한 변경을 이 화면의 작품으로 덮어쓸까요? 그쪽에서 바꾼 설정 · 플롯은 사라져요.')) return;
    await run('저장 중', async () => { if (await save(true) !== false) toast('저장했어요'); });
  },
  async copyOrphan(n) {
    const t = S.textDraft[n] || '';
    try {
      await navigator.clipboard.writeText(t);
    } catch {  // 보안 연결이 아니면 clipboard API 가 없다. 칸을 펼쳐 골라 복사한다
      const ta = $(`#orphan-${n}`);
      if (ta) { ta.closest('details').open = true; ta.select(); }
      if (!ta || !document.execCommand('copy')) return toast('브라우저가 복사를 막았어요. 펼친 칸에서 직접 골라 복사하세요', true);
    }
    toast(`${n}화 남은 초고를 복사했어요 (${t.length.toLocaleString()}자)`);
  },
  dropOrphan(n) {
    if (!confirm(`${n}화 남은 초고를 버릴까요? 되돌릴 수 없어요.`)) return;
    delete S.textDraft[n];
    render();
  },
  async createProject() {
    const f = newForm();
    const title = $('#np-title').value.trim();
    const typed = $('#np-name').value.trim();
    const name = typed || folderOf(title);
    // 오류는 그 칸 아래에 적고 칸으로 포커스를 옮긴다
    const fail = (field, msg) => { S.newErr = { field, msg }; S.focusTarget = `#np-${field}`; render(); };
    if (!name) return fail('title', '제목을 적어 주세요. 폴더 이름도 제목으로 만들어요.');
    if (FOLDER_BAD.test(name)) return fail('name', '폴더 이름에 / \\ : * ? " < > | 는 쓸 수 없고, . 으로 시작할 수 없어요.');
    const raw = $('#np-eps').value.trim();
    const total = Number(raw);
    if (!/^\d+$/.test(raw) || total < 4 || total > 1000) return fail('eps', '총 화수는 4~1000 사이의 정수로 적어 주세요. 기승전결이 4구간이라 4화보다 짧게는 못 써요.');
    S.newErr = null;
    const meta = {
      title: title || name,
      genres: [...f.genres],
      target_episodes: total,
      adult: $('#np-adult').checked,
      form: $('#np-serial').checked ? 'serial' : 'short',
    };
    const styleId = $('#np-style') ? $('#np-style').value : '';
    await run('만드는 중', async () => {
      await api('POST', '/projects', { name, meta, style_id: styleId });
      S.newMeta = null;
      location.hash = `#/p/${enc(name)}/setup`;
    }, { render: 'success' });  // 실패하면 다시 그리지 않아 적은 이름 · 제목 · 화수가 칸에 남는다
  },
  clearNewForm() {
    S.newMeta = null;
    S.newErr = null;
    render();
  },

  // 설정 도우미
  async suggest() {
    await startJob('suggest');
  },
  dropSuggestion() {
    if (!confirmDrop('AI 설정 제안')) return;
    S.suggestion = null;
    render();
  },
  async applySuggestion() {
    const s = structuredClone(S.suggestion);
    // 고르지 않은 칸은 비워 보낸다. 서버는 빈 칸을 건너뛴다
    SUG_FIELDS.forEach(([k]) => {
      if (S.picks['sf:' + k] !== false) return;
      if (k.startsWith('world.')) s.world[k.slice(6)] = Array.isArray(s.world[k.slice(6)]) ? [] : '';
      else s[k] = '';
    });
    s.characters = s.characters.filter((_, i) => S.picks['sc' + i]);
    s.relationships = s.relationships.filter((r, i) => S.picks['sr' + i] && sugEnd(r.a) && sugEnd(r.b));
    await run('적용하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/suggest/apply`, s);
      S.suggestion = null;
      toast('빈칸을 채웠어요. 기존 입력은 그대로예요.');
    });
    checkNames();  // 더한 인물 이름도 점검한다
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
    // 플롯 · 반영 기록에 남은 id 는 지우지 않는다. 지우면 그 화의 등장 인물과 관계 사건이 id 로만 보인다
    const inPlots = P().episodes.filter((e) => e.plot.characters.includes(c.id)).map((e) => e.plot.number);
    const inHistory = [...new Set(P().history.filter((h) => (h.events || []).some((ev) => ev.actor === c.id || ev.target === c.id) || h.character_updates.some((u) => u.character_id === c.id)).map((h) => h.episode))];
    const used = [inPlots.length ? `${rangeText(inPlots)}화 플롯의 등장 인물` : '', inHistory.length ? `${rangeText(inHistory)}화 반영 기록` : ''].filter(Boolean);
    const warn = used.length ? `\n이 인물은 ${used.join('과 ')}에 남아 있어요. 그곳에는 이름 대신 id(${c.id})로 보여요.${inHistory.length ? ' 이미 반영한 화에 나온 인물이면 지우기보다 비중을 단역으로 낮추는 편이 안전해요.' : ''}` : '';
    if (!confirm(`${c.name || c.id} 인물을 삭제할까요? 관계와 지금 상태도 함께 삭제돼요. 저장하기 전에는 아래 띠에서 되살릴 수 있어요.${warn}`)) return;
    rememberRemoved(`인물 ${c.name || c.id}`, ['characters', 'relationships', 'states']);
    P().characters.splice(i, 1);
    P().relationships = P().relationships.filter((r) => r.a !== c.id && r.b !== c.id);
    P().states = P().states.filter((s) => s.character_id !== c.id);
    markDirty();
    render();
    checkNames();  // 지운 인물과 겹친다던 경고를 걷어 낸다
  },
  // 플롯 편집기의 등장 인물: 새 인물 만들기, AI 후보 등록, 설정 없는 id 를 인물로, 이 화에서 빼기
  newCast(n) {
    const id = newCastId();
    P().characters.push({ id, name: '', role: '', age: '', gender: '', appearance: '', personality: '', background: '', goal: '', wound: '', speech_style: '', secrets: [], arc: '', tier: 'minor', first_ep: Number(n) });
    const plot = ep(Number(n)).plot;
    plot.characters = [...plot.characters, id];
    S.castEdit = id;
    markDirty();
    render();
  },
  registerCast(arg) {
    const id = arg.split('|')[1];
    const list = P().cast_candidates || [];
    const c = list.find((x) => x.id === id);
    if (!c) return;
    P().cast_candidates = list.filter((x) => x.id !== id);
    P().characters.push({ ...c, tier: c.tier === 'main' ? 'support' : c.tier, first_ep: castFirstEp(id) });
    markDirty();
    render();
    toast(`${c.name || id}${josa(c.name || id, '을', '를')} ${c.tier === 'minor' ? '단역' : '조연'}으로 등록했어요. 저장하면 반영돼요`);
    checkNames();
  },
  makeCast(arg) {
    const id = arg.split('|')[1];
    if (P().characters.some((c) => c.id === id)) return;
    P().characters.push({ id, name: '', role: '', age: '', gender: '', appearance: '', personality: '', background: '', goal: '', wound: '', speech_style: '', secrets: [], arc: '', tier: 'minor', first_ep: castFirstEp(id) });
    S.castEdit = id;
    markDirty();
    render();
  },
  dropCast(arg) {
    const [n, id] = arg.split('|');
    const plot = ep(Number(n)).plot;
    plot.characters = plot.characters.filter((x) => x !== id);
    markDirty();
    render();
  },
  closeCastEdit() {
    // 이름을 정하지 않고 접으면 'char4' 같은 id 만 남는다. 지울지 묻는다
    const c = P().characters.find((x) => x.id === S.castEdit);
    if (c && !c.name.trim() && confirm('이름 없는 인물을 지울까요? 남기려면 취소를 누르고, 나중에 등장 인물의 고치기로 다시 열어요.')) return actions.dropNewCast(c.id, true);
    S.castEdit = '';
    render();
  },
  editCast(id) {
    S.castEdit = id;
    S.focusTarget = '#app .drawer .note.plain input';
    render();
  },
  /** 서랍에서 만든 인물을 지운다. 이 인물을 넣은 화의 등장 인물에서도 빼서 '설정 없는 인물'로 남지 않게 한다. 다른 곳에 쓰였으면 설정 화면의 삭제로 보낸다. */
  dropNewCast(id, asked = false) {
    const i = P().characters.findIndex((x) => x.id === id);
    if (i < 0) return;
    const c = P().characters[i];
    const used = P().relationships.some((r) => r.a === id || r.b === id) || P().history.some((h) => h.character_updates.some((u) => u.character_id === id) || (h.events || []).some((ev) => ev.actor === id || ev.target === id));
    if (used) return toast(`${c.name || id}${josa(c.name || id, '은', '는')} 관계나 반영 기록에 쓰여서 여기서 지울 수 없어요. 설정 도우미에서 지우세요`, true);
    const eps = P().episodes.filter((e) => e.plot.characters.includes(id)).map((e) => e.plot.number);
    if (!asked && !confirm(`${c.name || id} 인물을 지울까요? ${eps.length ? `${rangeText(eps)}화 등장 인물에서도 빠져요. ` : ''}저장하기 전에는 아래 띠에서 인물을 되살릴 수 있어요.`)) return;
    rememberRemoved(`인물 ${c.name || id}`, ['characters', 'states']);
    P().characters.splice(i, 1);
    P().states = P().states.filter((x) => x.character_id !== id);
    P().episodes.forEach((e) => { e.plot.characters = e.plot.characters.filter((x) => x !== id); });
    S.castEdit = '';
    markDirty();
    render();
  },
  addRelationship() {
    const cs = P().characters;
    if (cs.length < 2) return toast('인물이 두 명 이상 있어야 해요', true);
    const has = new Set(P().relationships.map((r) => [r.a, r.b].sort().join('|')));
    const pair = cs.flatMap((x, i) => cs.slice(i + 1).map((y) => [x.id, y.id])).find(([a, b]) => !has.has([a, b].sort().join('|')));
    if (!pair) return toast('모든 인물 쌍에 관계가 이미 있어요', true);
    P().relationships.push({ a: pair[0], b: pair[1], type: '', description: '', affinity: 0, tension: 0, goal_conflict: 0, a_view: [], b_view: [] });
    markDirty();
    render();
  },
  removeRelationship(i) {
    const r = P().relationships[i];
    rememberRemoved(`관계 ${charName(r.a) || r.a} ↔ ${charName(r.b) || r.b}`, ['relationships']);
    P().relationships.splice(i, 1);
    markDirty();
    render();
  },
  fillSlot(arg) {
    const [k, ...rest] = arg.split('|');
    const prev = composeLogline(P().meta.logline_parts);
    P().meta.logline_parts[k] = rest.join('|');
    const el = $(`#f-meta-logline_parts-${k}`);
    if (el) el.value = P().meta.logline_parts[k];
    markDirty();
    updateLogline(prev);
  },
  rebuildLogline() {
    const m = P().meta;
    m.logline = composeLogline(m.logline_parts);
    const raw = $('#f-meta-logline');
    if (raw) raw.value = m.logline;
    markDirty();
    updateLogline();
    toast('칸 내용으로 로그라인을 다시 만들었어요');
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
    const prev = toneText(m.tone_dials);
    m.tone_dials[k] = m.tone_dials[k] === Number(v) ? 0 : Number(v);
    // 직접 쓴 톤 문장은 덮지 않는다. 다이얼 문장이 다르면 칸 아래 '다이얼 문장으로 바꾸기'로 권한다
    if (!m.tone.trim() || m.tone === prev) m.tone = toneText(m.tone_dials);
    markDirty();
    $('#tone-box').outerHTML = toneBox();
  },
  useToneText() {
    const m = P().meta;
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
    if (S.styleSample.trim().length < 200) { focusEl($('#sample')); return toast('예시 원문을 200자 이상 넣어 주세요', true); }  // 서버(web.analyze_style)와 같은 기준
    const has = P().style.narration_pov || P().style.sample_passages.length;
    const l = S.styleLink || {};
    const unlink = ['same', 'changed'].includes(l.state) ? `\n라이브러리 '${l.name}' 연결도 끊겨요. 라이브러리 항목은 그대로예요.` : '';
    if ((has || unlink) && !confirm(`분석 결과로 지금 스타일 프로필을 바꿀까요? 저장하기 전에는 '변경 모두 버리기'로 되돌릴 수 있어요.${unlink}`)) return;
    await run('문체를 분석하는 중… (최대 1분)', async () => {
      await saveIfDirty();
      const prof = await api('POST', `/projects/${enc(S.name)}/style`, { text: S.styleSample });
      P().style = prof;
      P().style_baseline = await api('POST', '/metrics', { text: S.styleSample });  // stats 가 원문 전체와 비교하도록
      P().style_id = '';  // 새로 분석한 문체는 라이브러리 항목과 연결을 끊는다
      P().style_version = 0;
      S.styleLink = { state: 'none' };  // 저장하면 서버도 같은 상태가 된다. 그 전에도 카드가 끊긴 연결을 그대로 보이지 않게
      S.dirty = true;
      toast('분석 결과를 불러왔어요. 확인하고 저장하세요.');
    });
  },
  addPassage() {
    P().style.sample_passages.push('');
    markDirty();
    render();
  },
  removePassage(i) {
    rememberRemoved(`예시 문단 ${Number(i) + 1}`, ['style.sample_passages']);
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
    rememberRemoved('문체 표지', ['style.markers']);
    P().style.markers.splice(i, 1);
    markDirty();
    render();
  },
  async useLibStyle() {
    const id = $('#style-pick').value;
    if (!id) return toast('적용할 문체를 고르세요', true);
    const e = (S.libs || []).find((x) => x.id === id);
    const l = S.styleLink || { state: 'none' };
    const lost = l.state === 'same' ? '' : '\n지금 문체는 라이브러리에 없어서 되돌릴 수 없어요. 남겨 두려면 취소하고 \'이 문체를 라이브러리에 새로 저장\'을 먼저 누르세요.';
    if (!confirm(`'${e ? e.name : id}' 문체를 이 작품에 적용할까요? 지금 작품의 스타일 프로필은 바뀌어요.${lost}`)) return;
    await run('적용하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/style/apply`, { style_id: id });
      await loadStyleLink();
      toast('라이브러리 문체를 적용했어요');
    });
  },
  async keepStyle() {
    const bare = S.styleSample.trim() ? '' : '\n(이 화면에 붙여 넣은 원문이 없어 원문 없이 저장돼요)';
    const l = S.styleLink || {};
    const moved = ['same', 'changed'].includes(l.state) ? `\n이 작품은 새 항목에 연결되고, 지금 연결된 '${l.name}' 연결은 끊겨요. '${l.name}' 항목은 그대로 남아요.` : '';
    const name = prompt(`라이브러리에 저장할 문체 이름${bare}${moved}`, `${P().meta.title || S.name} 문체`);
    if (name === null) return;
    await run('라이브러리에 저장하는 중', async () => {
      await saveIfDirty();
      const r = await api('POST', `/projects/${enc(S.name)}/style/library`, { name: name.trim(), sample: S.styleSample });
      S.project = r.project;
      S.libs = await api('GET', '/styles');
      await loadStyleLink();
      toast(`라이브러리에 '${r.entry.name}' 로 저장했어요`);
    });
  },
  async pushStyle() {
    const l = S.styleLink || {};
    const users = ((S.libs || []).find((x) => x.id === l.id) || {}).used_by || [];
    const others = users.filter((n) => n !== S.name);
    const warn = (others.length ? `\n다른 작품(${others.join(', ')})은 다시 적용하기 전까지 바뀌지 않아요.` : '')
      + ((l.theirs || []).length ? `\n라이브러리 ${l.version}번 버전에서 바뀐 칸(${l.theirs.map((c) => c.label).join(', ')})은 이 작품 값으로 덮여요.` : '');
    const note = prompt(`이 작품의 문체를 라이브러리 '${l.name}' 의 새 버전으로 올려요. 예전 버전은 남아 있어 되돌릴 수 있어요.${warn}\n\n버전 메모 (비워도 돼요)`, '');
    if (note === null) return;
    await run('라이브러리에 올리는 중', async () => {
      await saveIfDirty();
      const r = await api('POST', `/projects/${enc(S.name)}/style/library`, { update: true, note: note.trim() });
      S.project = r.project;
      S.libs = await api('GET', '/styles');
      await loadStyleLink();
      toast(`라이브러리 '${r.entry.name}' 을 ${r.entry.version}번 버전으로 올렸어요`);
    });
  },
  async pullStyle() {
    const l = S.styleLink || {};
    const lost = (l.mine || []).length || !l.base_known ? ' 작품에서 고친 내용은 사라져요.' : '';
    if (!confirm(`이 작품의 문체를 라이브러리 '${l.name}' ${l.version}번 버전으로 바꿀까요?${lost}`)) return;
    await run('적용하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/style/apply`, { style_id: l.id });
      await loadStyleLink();
      toast(`라이브러리 '${l.name}' ${l.version}번 버전을 가져왔어요`);
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
      toast('분석 결과를 불러왔어요. 확인하고 저장하세요.');
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
      toast(isNew ? '라이브러리에 저장했어요' : `저장했어요 (지금 ${S.lib.version}번 버전)`);
      if (isNew) location.hash = `#/styles/${S.lib.id}`;
    });
  },
  async libRevert() {
    if (!S.libDirty) return;
    if (!confirm(S.lib.id ? '저장하지 않은 변경을 버리고 저장된 문체로 되돌릴까요?' : '적은 내용을 모두 지우고 빈 문체로 돌아갈까요?')) return;
    if (!S.lib.id) {  // 아직 저장하지 않은 새 문체: 돌아갈 저장본이 없다
      S.lib = { name: '', source: '', notes: '', sample: '', profile: emptyProfile(), used_by: [] };
      S.libDirty = false;
      render();
      return;
    }
    await run('불러오는 중', async () => {
      S.lib = await api('GET', `/styles/${S.lib.id}`);
      S.libDirty = false;
    });
  },
  async libDuplicate(id) {
    if (S.libDirty && !confirm('저장하지 않은 변경이 있어요. 저장한 뒤 그 버전으로 복제할까요?')) return;
    if (S.libDirty) {
      await actions.libSave();
      if (S.libDirty) return;  // 저장하지 못했다 (토스트가 이유를 알린다)
    }
    await run('복제하는 중', async () => {
      const e = await api('POST', `/styles/${id}/duplicate`);
      S.libDirty = false;
      toast(`'${e.name}' 을 만들었어요. 구별하기 쉽게 이름을 바꿔 보세요`);
      location.hash = `#/styles/${e.id}`;
      // 새 항목 화면이 그려지면 이름 칸을 골라 둔다 (화면 이동은 제목으로 포커스를 옮기므로 그 뒤에)
      const until = Date.now() + 5000;
      const pick = () => {
        const el = $('#f-name');
        if (el && el.value === e.name) { el.focus(); el.select(); } else if (Date.now() < until) setTimeout(pick, 100);
      };
      setTimeout(pick, 100);
    });
  },
  async libDelete(id) {
    const e = (S.libs || []).find((x) => x.id === id) || S.lib || {};
    const used = e.used_by || [];
    const note = used.length ? `\n이 문체를 쓰는 작품(${used.join(', ')})은 복사해 둔 문체를 그대로 써요.` : '';
    if (!confirm(`'${e.name}' 문체를 라이브러리에서 지울까요? 되돌릴 수 없어요.${note}`)) return;
    await run('지우는 중', async () => {
      await api('DELETE', `/styles/${id}`);
      S.libDirty = false;
      S.libs = await api('GET', '/styles');
      toast('지웠어요');
      if (S.route[0] === 'styles' && S.route[1]) location.hash = '#/styles';
    });
  },
  async libApplyTo() {
    const name = $('#lib-target').value;
    if (!name) return toast('적용할 작품을 고르세요', true);
    if (S.libDirty) return toast('먼저 저장하세요. 저장된 문체가 작품에 복사돼요.', true);
    if (!confirm(`'${S.lib.name}' 문체를 '${name}' 작품에 적용할까요? 그 작품의 스타일 프로필은 바뀌어요.\n그 작품의 지금 문체를 라이브러리에 저장해 두지 않았다면 되돌릴 수 없어요.`)) return;
    await run('적용하는 중', async () => {
      await api('POST', `/projects/${enc(name)}/style/apply`, { style_id: S.lib.id });
      S.lib = await api('GET', `/styles/${S.lib.id}`);
      toast(`'${name}' 에 적용했어요`);
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
    await startJob('arc', null, { note: S.planNote || '' });  // 도착하면 지금 구조와 비교하는 제안 카드로 보인다. 고르기 전에는 바뀌지 않는다
  },
  splitArc() {
    // AI 없이 총 화수를 기승전결 네 구간으로 나눈다 (pipeline.act_ranges 와 같은 비율). 목표는 구간 고치기에서 적는다
    const r = actRanges(P().meta.target_episodes, 1);
    if (!r) return toast('총 화수를 먼저 정하세요', true);
    P().arc = ACTS.map((name, i) => ({ name, start_ep: r[i][0], end_ep: r[i][1], goal: '', key_turn: '', pov: '' }));
    S.selAct = 0;
    S.focusTarget = '#app .drawer h2';
    markDirty();
    render();
    toast('네 구간으로 나눴어요. 구간마다 목표를 적고 저장하세요');
  },
  useArcProposal() {
    P().arc = S.arcProposal;
    S.arcProposal = null;
    markDirty();
    render();
    toast('구조를 바꿨어요. 저장하면 반영돼요');
  },
  dropArcProposal() {
    if (!confirmDrop('AI 구조 제안')) return;
    S.arcProposal = null;
    render();
  },
  async draftPlots() {
    if (!confirmRedraft(P().episodes)) return;
    await startJob('plots', null, { note: S.planNote || '' });
  },
  selectEp(n) {
    S.focusTarget = '#app .drawer h2';  // 서랍을 열면 제목으로 들어가 몇 화 서랍인지 읽게 한다
    S.selEp = Number(n);
    S.selAct = null;
    S.editArc = false;
    S.selPart = null;
    render();
  },
  selectAct(i) {
    S.focusTarget = '#app .drawer h2';
    S.selAct = Number(i);
    S.selEp = null;
    S.editArc = false;
    S.selPart = null;
    render();
  },
  closePanel() {
    // 닫으면 연 카드로 포커스를 돌린다
    S.focusTarget = S.selEp ? `#app .ep-card[data-arg="${S.selEp}"]` : S.selAct != null ? `#app [data-action="selectAct"][data-arg="${S.selAct}"]` : null;
    S.selEp = null;
    S.selAct = null;
    S.editArc = false;
    S.selPart = null;
    render();
  },
  async confirmEp(n) {
    await run('확정하는 중', async () => {
      await saveIfDirty();
      const before = P().characters.length;
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/confirm`);
      castAddedToast(before);
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
    if (!drafts.length) return toast('확정할 초안이 없어요');
    if (jobFor('plots')) return toast('플롯 초안을 만드는 중이에요. 끝난 뒤에 확정하세요', true);
    if (!confirm(`초안 ${drafts.length}화를 모두 확정할까요?`)) return;
    await run('확정하는 중', async () => {
      await saveIfDirty();
      const before = P().characters.length;
      for (const e of drafts) S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${e.plot.number}/confirm`);
      castAddedToast(before);
      S.focusTarget = '#app [data-write-next]';  // 다음 할 일(그 화 쓰기)로 바로 간다
    });
  },

  // 장편: 부 · 아크
  async planSeries() {
    if (P().parts.length && !confirm('지금 부 구성을 AI 제안으로 바꿀까요? 적용 전에 확인할 수 있어요.')) return;
    await startJob('series', null, { note: S.planNote || '' });
  },
  dropSeries() {
    if (!confirmDrop('AI 부 구성 제안')) return;
    S.seriesDraft = null;
    render();
  },
  async applySeries() {
    const lost = lostPartSummaries();
    if (lost.length && !confirm(`범위가 바뀌어 저장된 ${lost.map((x) => `${x.number}부`).join(', ')} 요약이 사라져요. 반영할까요?`)) return;
    await run('적용하는 중', async () => {
      await saveIfDirty();
      const had = P().story_arcs.length > 0;
      S.project = await api('POST', `/projects/${enc(S.name)}/series/apply`, S.seriesDraft);
      S.seriesDraft = null;
      toast(had ? '부 구성을 바꿨어요. 아크와 반영한 화는 그대로예요.' : '부 구성을 적용했어요. 이제 첫 아크를 기획하세요.');
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
    if (!confirmDrop('AI 다음 아크 제안')) return;
    S.arcDraft = null;
    render();
  },
  async applyArc() {
    await run('적용하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/arcs/apply`, S.arcDraft);
      S.selArc = S.arcDraft.arc.number;
      S.arcDraft = null;
      S.arcForm = { length: 0, note: '' };
      toast('아크를 적용했어요. 화별 플롯 초안을 만드세요.');
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
    const a = P().story_arcs.find((x) => x.number === Number(n));
    if (a && !confirmRedraft(P().episodes.filter((e) => e.plot.number >= a.start_ep && e.plot.number <= a.end_ep))) return;
    await startJob('plots', Number(n), { note: S.planNote || '' });
  },
  async recapArc(n) {
    if (S.recapDrafts['arc' + n] && !confirm(`아크 ${n} 요약 제안이 아직 있어요. 고친 내용을 버리고 새로 받을까요?`)) return;
    await startJob('recap_arc', Number(n));
  },
  async recapPart(n) {
    if (S.recapDrafts['part' + n] && !confirm(`${n}부 요약 제안이 아직 있어요. 고친 내용을 버리고 새로 받을까요?`)) return;
    await startJob('recap_part', Number(n));
  },
  dropRecap(key) {
    if (!confirmDrop('AI 요약 제안')) return;
    delete S.recapDrafts[key];
    render();
  },
  async applyRecap(key) {
    const r = S.recapDrafts[key];
    await run('저장하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/recap/${r.kind}/${r.number}`, { summary: r.summary });
      delete S.recapDrafts[key];
      toast('요약을 저장했어요. 앞으로 이 구간 대신 요약이 프롬프트에 들어가요.');
    });
  },

  // 집필
  setMode(m) {
    S.mode = m;
    localStorage.setItem('canon.mode', m);
    render();
  },
  async writeEp(n) {
    if (ep(n).text && !confirm(`${n}화 본문을 새로 생성할까요? 지금 본문은 사라져요.`)) return;
    await startJob('write', n);
  },
  async saveText(n) {
    await run('본문 저장 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/episodes/${n}/text`, { text: S.textDraft[n] ?? ep(n).text });
      delete S.textDraft[n];  // 만들어 둔 상태 변경안은 남기고, 본문이 바뀌었다고 알린다 (passageNotes)
      toast('본문을 저장했어요');
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
    const d = S.deltas[n];
    const o = S.deltaOrig[n];
    // S.picks 는 설정 제안 화면과 같이 쓴다. 변경안을 받을 때 있던 칸만 비교한다
    const edited = d && o && (d.summary !== o.summary || Object.entries(o.picks).some(([k, v]) => S.picks[k] !== v));
    if (edited && !confirm('고친 요약과 체크를 버리고 변경안을 다시 만들까요?')) return;
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
    // 평소에는 바로 반영한다. 고른 항목이 없거나, 경고가 남았거나, 변경안을 만든 뒤 본문을 고쳤으면 한 번 묻는다
    const lists = ['character_updates', 'events', 'secrets_added', 'relationship_updates', 'new_facts', 'foreshadow_planted', 'foreshadow_resolved', 'new_characters', 'new_places', 'deadlines_added', 'deadlines_done', 'setting_changes'];
    const count = lists.reduce((s, k) => s + (out[k] || []).length, 0);
    const why = [
      count ? '' : '고른 항목이 0건이에요. 요약만 저장하고',
      (out.warnings || []).length ? `경고 ${out.warnings.length}건이 남아 있어요.` : '',
      S.deltaBase[n] !== undefined && ep(n) && S.deltaBase[n] !== ep(n).text ? '변경안을 만든 뒤 본문을 고쳤어요.' : '',
    ].filter(Boolean);
    if (why.length && !confirm(`${why.join(' ')} ${n}화를 마칠까요? 반영하면 반영 취소로만 돌아갈 수 있어요.`)) return;
    await run('반영하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/apply`, out);
      delete S.deltas[n];
      toast(ep(n + 1) && ep(n + 1).status === 'confirmed' ? `${n}화를 마쳤어요. ${n + 1}화 집필로 왔어요` : `${n}화를 마쳤어요`);
      const r = S.auto && S.auto.run;
      // 자동 집필이 이 화에서 검토를 기다리고 있었으면 자동 집필 화면으로 돌아가 이어 가게 한다.
      // 아니면 다음 할 일로 바로 간다: 다음 화가 확정이면 그 화 집필, 초안이면 플롯, 없으면 홈 (nextStep)
      const next = ep(n + 1);
      location.hash = r && r.status === 'review' && r.ep === n ? `${base()}/auto` : next && ['confirmed', 'draft'].includes(next.status) ? nextStep()[1] : base();
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
    const c = S.config || {};
    const body = {
      stages: Object.fromEntries(STAGES.map(([s]) => [s, $(`#set-stage-${s}`).value])),
      stage_models: Object.fromEntries(STAGES.map(([s]) => [s, $(`#set-stage-model-${s}`).value.trim()])),
    };
    // 환경 변수나 기본값을 보여 주기만 한 칸은 보내지 않는다. 보내면 설정 파일에 굳어 환경 변수를 바꿔도 따라가지 않는다
    [['provider', '#set-provider', c.provider], ['model', '#set-model', c.model_setting], ['local_url', '#set-local-url', c.local_url], ['local_model', '#set-local-model', c.local_model]]
      .forEach(([k, sel, shown]) => {
        const v = $(sel).value.trim();
        if (['env', 'default'].includes(c[`${k}_source`]) && v === (shown || '')) return;
        body[k] = v;
      });
    if (key) body.api_key = key;
    const lkey = $('#set-local-key').value.trim();
    if (lkey) body.local_key = lkey;
    Object.assign(body, claudeSettingsBody(), geminiAuthBody(c));
    const ok = await run('저장 중', async () => {
      S.config = await api('PUT', '/config', body);
      S.health = await api('GET', '/config/health').catch(() => null);
      S.settingsDirty = false;
      settingsSavedAt = { what: '저장했어요', at: new Date().toISOString() };
      toast('설정을 저장했어요');
    }, { render: 'success' });  // 실패하면 다시 그리지 않아 적은 키와 모델이 칸에 남는다
    if (ok) $('[data-action="saveSettings"]')?.focus();  // 다시 그리면 초점이 페이지 처음으로 가므로 돌려준다
    return ok;
  },
  async clearKey() {
    if (!confirm('저장된 API 키를 지울까요?')) return;
    const ok = await run('지우는 중', async () => {
      S.config = await api('PUT', '/config', { clear_key: true });
      settingsSavedAt = { what: '키를 지웠어요', at: new Date().toISOString() };
      toast('키를 지웠어요');
    });
    if (ok) $('#set-key')?.focus();
  },
  settingsBack() {
    if (settingsNavs > 0) history.back();
    else location.hash = S.name ? base() : '#/';
  },
  async loadModels() {
    await loadModelList(true);
  },
  async testSettings() {
    // 서버는 저장된 설정으로 시험한다. 적기만 한 값이 있으면 먼저 저장해야 그 값의 결과가 나온다
    if (S.settingsDirty) {
      if (!confirm('입력한 설정을 아직 저장하지 않았어요. 저장한 뒤 연결을 확인할까요?')) return;
      await actions.saveSettings();
      if (S.settingsDirty) return;  // 저장하지 못했다
    }
    await run('연결 확인 중', async () => {
      const r = await api('POST', '/config/test');
      toast(r.message);
    }, { render: 'never' });
  },

  // 작업지시서
  openStateBrief(n) {
    BRIEF_TABS[`${S.name}:${n}`] = 'state';
    location.hash = `${base()}/brief/${n}`;
  },
  setBriefTab(t) {
    BRIEF_TABS[`${S.name}:${S.route[3]}`] = t;
    S.briefTab = t;
    S.briefText = null;
    briefImportError = null;
    render();
  },
  async copyBrief() {
    try {
      await navigator.clipboard.writeText(S.briefText || '');
      toast('복사했어요. 채팅 앱에 붙여 넣으세요.');
    } catch {
      toast('복사하지 못했어요. 내용을 직접 선택해 복사하세요.', true);
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
      delete S.briefDraft[`${S.name}:${n}:episode`];
      toast(`${n}화 본문으로 저장했어요`);
      location.hash = `${base()}/write/${n}`;
    });
  },
  async importJson(n) {
    const raw = $('#imp-json').value;
    if (!raw.trim()) return toast('JSON을 붙여 넣으세요', true);
    if (S.deltas[n] && !confirm(`${n}화에 검토 중인 변경안이 있어요. 골라 둔 체크와 함께 가져온 JSON으로 바꿀까요?`)) return;
    await run('확인하는 중', async () => {
      let d;
      try {
        d = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/state/parse`, { raw });
      } catch (e) {
        if (e.status !== 400) throw e;
        briefImportError = { key: `${S.name}:${n}`, msg: e.message };  // 토스트는 사라지니 ② 칸 아래에 남긴다
        return;
      }
      briefImportError = null;
      setDelta(n, d, 'chat');
      delete S.briefDraft[`${S.name}:${n}:state`];
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
    new_places: pick('l', d.new_places || []),
    foreshadow_clues: pick('q', d.foreshadow_clues || []),
    deadlines_added: pick('k', d.deadlines_added || []),
    deadlines_done: pick('o', d.deadlines_done || []),
    setting_changes: pick('t', d.setting_changes || []),
  };
}

/** 화 플롯 글 (서버 elements.plot_text 와 같은 칸). */
const plotText = (pl) => [pl.title, pl.summary, ...pl.events, pl.emotional_shift, pl.ending_hook, ...(pl.foreshadow_plant || [])].join('\n');

/** 이 화 플롯에 나오는 장소 후보 (AI 플롯이 지은 새 장소). 확정하면 인과율 장소로 등록된다 (pipeline.confirm_plot). */
function placeCandNotes(e) {
  const text = plotText(e.plot);
  const cands = (P().place_candidates || []).filter((x) => [x.name, ...(x.aliases || [])].some((t) => t && text.includes(t)));
  return cands.length ? `<div class="field"><span class="label">새 장소</span>${cands.map((x) => `<div class="note info"><strong>새 장소 제안 · ${esc(x.name)}</strong>${x.kind ? ` <span class="small">${esc(x.kind)}</span>` : ''}${x.description ? `<br>${esc(x.description)}` : ''}
    <br><span class="small">AI 플롯이 지은 장소예요. 이 화를 확정하면 인과율에 장소로 등록돼요. 빼려면 플롯에서 이름을 지우세요.</span></div>`).join('')}</div>` : '';
}

/** 새 장소 한 줄: 이름, 종류, 다른 이름, 설명. 상태 승인 · 다시 맞추기 화면이 같이 쓴다. */
const placeLabel = (x) => `<strong>${esc(x.name)}</strong>${x.kind ? ` <span class="small">${esc(x.kind)}</span>` : ''}${(x.aliases || []).length ? ` <span class="small">다른 이름: ${x.aliases.map(esc).join(', ')}</span>` : ''}${x.description ? `<br>${esc(x.description)}` : ''}`;

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

/** 상태 변경안 항목 체크 키 ('c0', 'e1' …). 설정 제안 키('sc0', 'sf:logline')와 섞이지 않게 센다. */
const DELTA_PICK = /^[cesrfpxnqlkot]\d+$/;
const deltaPicked = () => Object.entries(S.picks).filter(([k, v]) => v && DELTA_PICK.test(k)).length;

/** source: 변경안을 어디서 받았나 ('chat' 이면 채팅 앱에서 가져온 JSON). 상태 승인 화면 설명에 쓴다 */
function setDelta(n, d, source = 'ai') {
  S.deltas[n] = d;
  S.deltaBase[n] = ep(n) ? ep(n).text : '';
  // S.picks 는 설정 제안(sc · sr · sf: 키)과 같이 쓴다. 변경안 키만 지워 설정 화면의 체크를 남긴다
  for (const k of Object.keys(S.picks)) if (DELTA_PICK.test(k)) delete S.picks[k];
  S.preview = null;
  // 설정에도 이번 새 인물에도 없는 id 의 상태는 기본으로 빼 둔다. 반영하면 누구의 것도 아닌 상태가 남는다
  const known = new Set([...P().characters.map((c) => c.id), ...(d.new_characters || []).map((c) => c.id)]);
  d.character_updates.forEach((u, i) => { S.picks['c' + i] = known.has(u.character_id); });
  d.events.forEach((_, i) => { S.picks['e' + i] = true; });
  d.secrets_added.forEach((_, i) => { S.picks['s' + i] = true; });
  d.relationship_updates.forEach((_, i) => { S.picks['r' + i] = true; });
  d.new_facts.forEach((_, i) => { S.picks['f' + i] = true; });
  d.foreshadow_planted.forEach((_, i) => { S.picks['p' + i] = true; });
  d.foreshadow_resolved.forEach((id, i) => { S.picks['x' + i] = P().foreshadows.some((f) => f.id === id); });
  (d.new_characters || []).forEach((_, i) => { S.picks['n' + i] = true; });
  (d.new_places || []).forEach((_, i) => { S.picks['l' + i] = true; });
  (d.foreshadow_clues || []).forEach((_, i) => { S.picks['q' + i] = true; });
  (d.deadlines_added || []).forEach((_, i) => { S.picks['k' + i] = true; });
  (d.deadlines_done || []).forEach((id, i) => { S.picks['o' + i] = P().timeline.deadlines.some((x) => x.id === id) || (d.deadlines_added || []).some((x) => x.id === id); });
  (d.setting_changes || []).forEach((_, i) => { S.picks['t' + i] = false; });  // 인물 설정은 작가가 직접 골라야 바뀐다
  // 받은 그대로의 요약과 체크. 다시 만들 때 고친 것을 버리는지 묻는다 (기본으로 뺀 항목은 고친 것이 아니다)
  S.deltaOrig[n] = { summary: d.summary, picks: Object.fromEntries(Object.entries(S.picks).filter(([k]) => DELTA_PICK.test(k))), source };
}

document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  e.preventDefault();
  if (el.getAttribute('aria-disabled') === 'true') return;  // 작업 중인 버튼: 포커스는 남기고 누르지는 못한다 (jobBtn)
  const fn = actions[el.dataset.action];
  const arg = el.dataset.arg;
  if (fn) fn(arg !== undefined && /^\d+$/.test(arg) ? Number(arg) : arg);
});

// ---------- 라우팅 ----------

// 화 번호로 키를 잡는 화면 상태는 작품마다 따로 둔다. 다른 작품으로 가면 지금 것을 보관하고 그 작품 것을 꺼낸다
// (그러지 않으면 한 작품의 본문 초안이 다른 작품의 같은 화에 보이고 저장된다)
// 작품마다 따로 두는 화면 상태와 빈 값. 화 번호로 잡거나 반영 전 AI 제안이라, 다른 작품에 보이거나 반영되면 안 된다
const PER_PROJECT = {
  textDraft: () => ({}), deltas: () => ({}), deltaBase: () => ({}), deltaOrig: () => ({}),
  suggestion: () => null, picks: () => ({}), seriesDraft: () => null, arcDraft: () => null, arcProposal: () => null, recapDrafts: () => ({}),
  lineDraft: () => null, convDraft: () => null, rbDraft: () => null, reworks: () => ({}),
  openingData: () => ({}), openingPlots: () => ({}), openingUsed: () => ({}), openingPrev: () => ({}), rw: () => ({}), rwInfo: () => ({}), looks: () => ({}),
  causalLinks: () => ({}), causalPicks: () => ({}), causalGone: () => null, chatPicks: () => ({}),
};
const stash = {};       // 작품 이름 → PER_PROJECT 의 값들
let stateOwner = null;  // 지금 S.textDraft 등이 속한 작품

/** 지금 작품을 떠나기 전에 부른다: 저장 본문과 같아진 초안, 이미 반영이 끝난 화의 변경안, 더 쓸 수 없는 지시서 칸 글을 버린다.
    떠난 뒤에는 그 작품 데이터가 없어 남은 것을 '저장 안 한 입력'으로만 센다. */
function pruneProjectState() {
  if (!P() || !S.name) return;
  Object.keys(S.textDraft).forEach((n) => { if (!textUnsaved(n)) delete S.textDraft[n]; });
  Object.keys(S.deltas).forEach((n) => {  // 반영이 끝났거나 없어진 화의 변경안만 버린다 (반영 뒤 고친 화의 다시 맞추기 변경안은 둔다)
    const e = ep(Number(n));
    if (!e || (e.status === 'finalized' && !editedAfterFinal(e))) { delete S.deltas[n]; delete S.deltaBase[n]; }
  });
  Object.entries(S.briefDraft).forEach(([k, v]) => { if (k.startsWith(`${S.name}:`) && !briefPending(k, v)) delete S.briefDraft[k]; });
}

function useProjectState(name) {
  if (stateOwner === name) return;
  pruneProjectState();
  if (stateOwner) stash[stateOwner] = Object.fromEntries(Object.keys(PER_PROJECT).map((k) => [k, S[k]]));
  const kept = stash[name] || {};
  Object.entries(PER_PROJECT).forEach(([k, empty]) => { S[k] = k in kept ? kept[k] : empty(); });
  delete stash[name];
  stateOwner = name;
}

async function loadProject(name) {
  const fresh = await api('GET', `/projects/${enc(name)}`);
  useProjectState(name);  // 떠나는 작품 데이터로 정리한 뒤 보관하므로 S.project 를 바꾸기 전에 부른다
  S.project = fresh;
  S.name = name;
  S.dirty = false;
  S.conflict = false;
}

let lastHash = location.hash;
// 화면 머리의 다음 단계 버튼('기승전결로' 같은)은 저장하고 넘어간다. 고친 것을 들고 다음 단계로 가는 흐름이라 버릴지 묻지 않는다
document.addEventListener('click', async (e) => {
  const a = e.target.closest('.page-head a.btn.primary[href^="#/"]');
  if (!a || !S.dirty || S.conflict || e.defaultPrevented) return;
  e.preventDefault();
  try {
    if (await save() === false) return;  // 서버가 일부를 지켰다. 토스트를 읽게 이 화면에 남는다
  } catch (err) {
    return showError(err);
  }
  location.hash = a.getAttribute('href');
});

const navScroll = { idx: 0, max: 0, at: new Map(), restore: null };
try { history.replaceState({ idx: 0 }, '', location.hash || '#/'); } catch { /* 기록을 못 고치면 위치 되살리기만 빠진다 */ }

window.addEventListener('hashchange', async () => {
  if ((S.dirty || S.libDirty || S.settingsDirty) && !confirm('저장하지 않은 변경이 있어요. 저장하지 않고 이동하면 그 변경은 사라져요. 이동할까요?')) {
    history.replaceState({ idx: navScroll.idx }, '', lastHash);
    return;
  }
  // 기록 칸마다 번호를 붙여 둔다. 번호가 이미 있으면 뒤로 · 앞으로 가기다 (링크로 온 새 칸은 번호가 없다)
  navScroll.at.set(navScroll.idx, window.scrollY);
  const st = history.state;
  if (st && typeof st.idx === 'number') {
    navScroll.restore = navScroll.at.get(st.idx) || 0;
  } else {
    history.replaceState({ idx: ++navScroll.max }, '', location.hash);
    navScroll.restore = null;
  }
  navScroll.idx = history.state.idx;
  lastHash = location.hash;
  S.libDirty = false;
  S.settingsDirty = false;
  await route();
});

/** 부 구성 제안을 반영하면 사라질 부 요약: 요약이 있는데 같은 범위의 부가 제안에 없다 (pipeline.apply_series 와 같은 규칙). */
function lostPartSummaries() {
  const keep = new Set((S.seriesDraft ? S.seriesDraft.parts : []).map((x) => `${x.start_ep}-${x.end_ep}`));
  return P().parts.filter((x) => x.summary && !keep.has(`${x.start_ep}-${x.end_ep}`));
}

/** 장편 아크 줄: 끝났고 요약도 있는 앞쪽 아크가 많으면 한 칩으로 접는다 (고른 아크는 늘 보인다). */
function railChips(arcs, chip) {
  const done = (a) => a.summary && arcFinished(a);
  let k = 0;
  while (k < arcs.length && done(arcs[k])) k++;
  if (S.railAll || k <= 3) return arcs.map(chip).join('');
  const folded = arcs.slice(0, k).filter((a) => a.number !== S.selArc);
  const keep = arcs.slice(0, k).filter((a) => a.number === S.selArc);
  return `<button type="button" class="arc-chip" data-action="railAll" aria-expanded="false"><strong>아크 ${arcs[0].number}~${arcs[k - 1].number}</strong> <span>완료 ${folded.length}개 · 펼치기</span></button>${keep.map(chip).join('')}${arcs.slice(k).map(chip).join('')}`;
}

// 화면 이동은 하나씩 차례로 처리한다. 늦게 끝난 앞 이동이 지금 화면의 데이터(지시서, 컨텍스트 등)를 덮지 않게 하고,
// 기다리는 사이 또 옮겼으면 중간 화면은 건너뛴다
let routeQueue = Promise.resolve();
let routeWanted = 0;
function route() {
  const my = ++routeWanted;
  routeQueue = routeQueue.then(() => (my === routeWanted ? routeNow() : undefined)).catch((e) => toast(e.message, true));
  return routeQueue;
}

let lastRoute = '';
async function routeNow() {
  S.loadError = null;
  S.loadMissing = false;
  // 느린 이동에서 이전 화면이 그대로 남아 멈춘 것처럼 보이지 않게, 0.3초 넘으면 위쪽 막대와 aria-busy 로 알린다
  const busy = setTimeout(() => { document.body.classList.add('routing'); const m = $('#app main'); if (m) m.setAttribute('aria-busy', 'true'); }, 300);
  document.querySelectorAll('.nav a[aria-current]').forEach((a) => a.removeAttribute('aria-current'));
  const goingTo = [...document.querySelectorAll('.nav a')].find((a) => a.getAttribute('href') === location.hash);
  if (goingTo) goingTo.setAttribute('aria-current', 'page');
  S.menuOpen = false;
  // 다른 화면으로 옮기면 제목으로 포커스를 옮겨 스크린리더가 새 화면을 읽고, 다음 Tab 이 본문에서 시작하게 한다
  const here = location.hash.split('/').slice(0, 4).join('/');
  if (here !== lastRoute) S.focusTarget = '#app main h1';
  lastRoute = here;
  const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
  S.route = parts;
  S.context = null;
  S.promptText = null;
  S.briefText = null;
  S.relations = null;
  if (parts[0] !== 'p') pruneProjectState();  // 작품 밖 화면으로 간다. 작품 데이터가 있을 때 끝난 초안을 정리한다
  try {
    if (!S.config) S.config = await api('GET', '/config');
    if (S.health === undefined) {  // 키 없음 · 로컬 서버 꺼짐 · mock 안내. 로컬 서버를 묻느라 첫 화면을 막지 않게 기다리지 않는다
      S.health = null;
      api('GET', '/config/health').then((h) => { S.health = h; if (!isTyping()) render(); }).catch(() => {});
    }
    if (!S.genres) S.genres = await api('GET', '/genres').catch(() => []);
    if (!S.namingStyles) S.namingStyles = await api('GET', '/naming/styles').catch(() => []);
    if (parts[0] === 'settings') {
      S.settingsDirty = false;
      S.config = await api('GET', '/config');
      loadModelList();  // 기다리지 않는다. 목록이 오면 입력칸 추천만 채운다
      claudeStatusLoad();  // Claude Code 로그인 상태도 기다리지 않는다 (claude.js)
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
      if (S.pendingJob && S.pendingJob.project === S.name && !S.jobsApplied.has(S.pendingJob.id)) applyJobResult(S.pendingJob);
      S.pendingJob = null;
      await loadPending();
      S.dirty = false;
      const n = Number(parts[3]);
      if (!parts[2] && S.project.relationships.length) {
        S.relations = await api('GET', `/projects/${enc(S.name)}/relations`).catch((e) => ({ error: e.message }));
      }
      if (parts[2] === 'setup') S.names = {};
      if (parts[2] === 'setup' || parts[2] === 'arc') {  // 플롯 서랍의 새 인물 칸도 이름 점검을 보인다
        S.nameCheck = await api('POST', `/projects/${enc(S.name)}/names/check`, nameCheckBody()).catch(() => null);
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
        if (ep(n).text && (S.rwOpen === n || ep(n).candidate || (ep(n).versions || []).length)) await rwLoad(n);  // 빠른 요청 이름과 재료
        if (S.rwOpen !== n) S.rwOpen = null;
      }
      if ((parts[2] === 'write' || parts[2] === 'setup') && !S.illModels) S.illModels = await api('GET', '/illust/models').catch(() => []);
      if (parts[2] === 'arc' && parts[3]) {  // 홈의 아크 칩(arc/a3) · 초안 칸(arc/12)이 고른 아크나 화를 연다
        const a = /^a\d+$/.test(parts[3]) ? Number(parts[3].slice(1)) : null;
        if (a) { S.selArc = a; S.selEp = null; S.selAct = null; }
        else if (n && ep(n)) {
          S.selEp = n;
          S.selAct = null;
          const arc = serial() && S.project.story_arcs.find((x) => x.start_ep <= n && n <= x.end_ep);
          if (arc) S.selArc = arc.number;
        }
      }
      if (parts[2] === 'write' || parts[2] === 'arc') await openingLoad(parts[2] === 'write' ? (n || currentEp()) : 0);
      if (parts[2] === 'research') await rsLoad();
      if (parts[2] === 'usage') await usageLoad(S.name);
      if (parts[2] === 'convert') await convertLoad();
      if (parts[2] === 'cast') await castLoad(parts[3]);
      if (parts[2] === 'atlas') await atlasLoad();
      if (parts[2] === 'foreshadow') await fsLoad();
      if (parts[2] === 'statwin') await swLoad(parts[3]);
      if (parts[2] === 'setup' && parts[3]) {  // 인물 화면의 '설정에서 고치기'(setup/<인물 id>)는 그 인물 카드로 간다
        const i = S.project.characters.findIndex((c) => c.id === parts[3]);
        if (i >= 0) S.focusTarget = S.jumpTo = `#f-characters-${i}-name`;
      }
      if (parts[2] === 'causal') {
        if (parts[3]) S.causalSel = parts[3];
        await causalLoad();
      }
      if (typeof autoLoad === 'function') await autoLoad(parts[2] === 'auto');
      if (parts[2] === 'brief' && n && ep(n)) {
        S.briefTab = briefTabFor(n);
        S.briefText = await api('GET', `/projects/${enc(S.name)}/episodes/${n}/brief?kind=${S.briefTab}`).then((r) => r.text).catch((e) => '※ ' + e.message);
      }
    } else {
      S.name = null;
      S.project = null;
      S.projects = await api('GET', '/projects');
      S.libs = await api('GET', '/styles').catch(() => []);
    }
  } catch (e) {
    // 연결 실패를 '작품 없음'과 같은 화면으로 보이지 않는다. 오류 카드와 다시 시도를 그린다
    S.loadError = e.message;
    S.loadMissing = e.status === 404 && parts[0] === 'p';  // 없는 작품: 다시 시도해도 같다
    S.name = null;
    S.project = null;
    S.dirty = false;  // 대상 작품이 없으니 저장 띠도 내린다
  }
  clearTimeout(busy);
  document.body.classList.remove('routing');
  render();
  window.scrollTo(0, navScroll.restore || 0);  // 뒤로 · 앞으로 가기는 읽던 위치로
  navScroll.restore = null;
  const card = S.jumpTo && document.querySelector(S.jumpTo)?.closest('.char-card');  // 맨 위로 간 뒤 고른 카드로 내려가 잠시 테두리를 보인다
  S.jumpTo = null;
  if (card) {
    card.classList.add('jump');
    card.scrollIntoView({ block: 'start' });
    setTimeout(() => card.classList.remove('jump'), 2000);
  }
  pollJobs();  // 다른 탭 · 기기에서 시작한 작업도 알아챈다
}

// ---------- 그리기 ----------

// ---------- 다시 그리기와 포커스 ----------
// 화면은 #app 전체를 다시 그린다. 그때 포커스가 BODY 로 가지 않게, 그리기 전 포커스를 기억했다가 새 화면의 같은 칸 · 버튼으로 돌린다.
// S.focusTarget 을 정하면(화면 이동, 서랍 열기 · 닫기, 작업 결과) 그 요소로 옮긴다.
let renderQueued = false;

function render() {
  // 칸을 고치고 Tab · 클릭으로 다음 칸에 갈 때 change 가 먼저 온다. 바로 그리면 막 들어간 다음 칸이 사라지므로 포커스가 옮겨진 뒤 그린다
  if (window.event && window.event.type === 'change') {
    if (!renderQueued) {
      renderQueued = true;
      setTimeout(() => { renderQueued = false; render(); });
    }
    return;
  }
  S.renderPending = false;
  const f = focusMark();
  drawApp();
  afterDraw(f);
}

/** 지금 포커스가 있는 #app 안 요소를 다시 찾을 수 있는 표시. */
function focusMark() {
  const el = document.activeElement;
  if (!el || el === document.body || !el.closest('#app')) return null;
  const d = el.dataset || {};
  return { id: el.id, action: d.action, arg: d.arg, bind: d.bind, draft: d.draft,
    start: el.selectionStart, end: el.selectionEnd, scroll: el.scrollTop };
}

function findMark(f) {
  const q = (sel) => document.querySelector(`#app ${sel}`);
  const v = (x) => CSS.escape(String(x));
  return (f.id && document.getElementById(f.id) && document.getElementById(f.id).closest('#app') && document.getElementById(f.id))
    || (f.action && q(`[data-action="${v(f.action)}"]${f.arg !== undefined ? `[data-arg="${v(f.arg)}"]` : ''}`))
    || (f.bind && q(`[data-bind="${v(f.bind)}"]`))
    || (f.draft && q(`[data-draft="${v(f.draft)}"]`));
}

function focusEl(el) {
  if (!el) return false;
  if (!el.matches('a, button, input, select, textarea, [tabindex]')) el.setAttribute('tabindex', '-1');
  el.focus({ preventScroll: el.matches('h1') });
  return document.activeElement === el;
}

function afterDraw(f) {
  const main = $('#app main');
  if (main) { main.id = 'main'; main.tabIndex = -1; }
  // 서랍은 제목으로 이름을 단다 ('7화 플롯'). 스크린리더가 몇 화 서랍인지 읽는다
  const d = $('#app .drawer');
  const h = d && d.querySelector('h2');
  if (h) { h.id = 'drawer-title'; d.setAttribute('aria-labelledby', 'drawer-title'); d.removeAttribute('aria-label'); }
  document.title = pageTitle();
  // 탭 묶음: 고른 탭만 Tab 으로 들어가고 나머지는 화살표로 옮긴다 (아래 keydown)
  document.querySelectorAll('#app [role="tablist"]').forEach((list) => {
    const tabs = [...list.querySelectorAll('[role="tab"]')];
    const sel = tabs.find((t) => t.getAttribute('aria-selected') === 'true') || tabs[0];
    tabs.forEach((t) => { t.tabIndex = t === sel ? 0 : -1; });
  });
  const want = S.focusTarget;
  S.focusTarget = null;
  if (want && focusEl(document.querySelector(want))) return;
  if (!f) return;
  const el = findMark(f);
  if (!el || !focusEl(el)) return;
  if (f.start != null && typeof el.setSelectionRange === 'function') {
    try { el.setSelectionRange(f.start, f.end); } catch { /* 고를 수 없는 칸 */ }
  }
  if (f.scroll) el.scrollTop = f.scroll;
}

/** 브라우저 탭과 방문 기록의 이름: '<화면> · <작품> · Canon'. */
function pageTitle() {
  const h1 = $('#app main h1');
  const name = h1 ? h1.textContent.trim().replace(/\s+/g, ' ') : '';
  const work = P() && S.route[0] === 'p' ? P().meta.title : '';
  return [name, work !== name ? work : '', 'Canon'].filter(Boolean).join(' · ');
}

function drawApp() {
  renderSavebar();
  document.body.classList.remove('chat-open', 'drawer-open');
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
  if (S.loadError) {
    $('#app').innerHTML = `<div class="shell"><main class="main" style="max-width:720px;margin:0 auto"><div class="card empty" role="alert">${S.loadMissing
      ? `<h2>'${esc(S.route[1] || '')}' 작품을 찾지 못했어요</h2><p>주소가 틀렸거나 지운 작품이에요. 작품 목록에서 고르세요.</p><div class="row"><a class="btn primary" href="#/">작품 목록</a></div>`
      : `<h2>화면을 불러오지 못했어요</h2><p>${esc(S.loadError)}</p><div class="row"><button class="btn primary" data-action="retryRoute">다시 시도</button><a class="btn" href="#/">작품 목록</a></div>`}</div></main></div>`;
    return;
  }
  if (p !== 'p' || !P()) {
    $('#app').innerHTML = `<div class="shell"><main class="main" style="max-width:1080px;margin:0 auto">${viewProjects()}</main></div>`;
    return;
  }
  const n = Number(arg) || currentEp();
  const views = { setup: viewSetup, style: viewStyle, arc: () => (serial() ? viewSerial() : viewArc()), write: viewWrite, review: viewReview, brief: viewBrief, research: viewResearch, usage: viewUsage, auto: viewAuto, causal: viewCausal, lines: viewLines, cast: viewCast, atlas: viewAtlas, convert: viewConvert, foreshadow: viewForeshadow, statwin: viewStatwin, timeline: viewTimeline };
  const body = (views[page] || viewHome)(n);
  $('#app').innerHTML = `<div class="shell">${sidebar(page || 'home')}<main class="main">${failStrip(page, n)}${body}</main></div>`;
  document.body.classList.toggle('drawer-open', !!$('#app .drawer'));  // 넓은 화면은 보드를 서랍 폭만큼 비켜 둔다 (app.css)
  syncPending();
  syncChat();
  if (typeof syncPassage === 'function') syncPassage();
  if (typeof syncIllust === 'function') syncIllust();
  if (typeof syncMarks === 'function') syncMarks();
  if (typeof syncLines === 'function') syncLines();
  document.querySelectorAll('textarea[data-autogrow]').forEach(autosize);
  // 상태 승인 지시서 탭이 바뀌면 다시 불러온다
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
  // 번호는 작업 순서(1~5)에만 붙인다. 도구는 어느 단계에서든 쓰므로 번호 없이 아래 묶음에 둔다
  const items = [
    ['home', base(), 'H', '작품 홈'],
    ['setup', base() + '/setup', '1', '설정 도우미'],
    ['style', base() + '/style', '2', '문체 레퍼런스'],
    ['arc', base() + '/arc', '3', serial() ? '부 · 아크 · 플롯' : '기승전결 · 플롯'],
    ['write', `${base()}/write/${cur}`, '4', '집필'],
    ['review', `${base()}/review/${cur}`, '5', '상태 승인'],
  ];
  const tools = [
    ['cast', base() + '/cast', '人', '인물 · 관계도'],
    ['atlas', base() + '/atlas', '地', '지도'],
    ['foreshadow', base() + '/foreshadow', '伏', '복선 센터'],
    ['statwin', base() + '/statwin', '#', '상태창 수치'],
    ['timeline', base() + '/timeline', '時', '작품 속 시간'],
    ['lines', base() + '/lines', '⑂', '이야기 줄기'],
    ['causal', base() + '/causal', '∴', '인과율 · 설정 추가'],
    ['brief', `${base()}/brief/${cur}`, '✎', '작업지시서 (API 없이)'],
    ['auto', base() + '/auto', 'A', autoMenuLabel()],
  ];
  const cfg = S.config || {};
  return `<nav class="side${S.menuOpen ? ' open' : ''}" aria-label="작품 메뉴">
    <a class="brand" href="#/">Canon</a>
    <button type="button" class="btn small menu-toggle" data-action="toggleMenu" aria-expanded="${!!S.menuOpen}" aria-controls="side-menu">메뉴</button>
    <div class="work-card">
      <div class="small">현재 작품</div>
      <div style="font-size:1rem;font-weight:700">${esc(p.meta.title || S.name)}</div>
      <div class="small">${esc(p.meta.genre || '장르 미정')} · ${total}화</div>
      <div class="meter" aria-hidden="true"><i style="left:0;width:${Math.round((done / Math.max(total, 1)) * 100)}%;background:var(--green)"></i></div>
      <div class="small">${done} / ${total}화 반영 완료</div>
    </div>
    <div class="side-menu" id="side-menu">
    <div class="nav">${items.map(([id, href, num, label]) => `<a href="${href}"${id === active ? ' aria-current="page"' : ''}><span class="num" aria-hidden="true">${num}</span>${label}${/\d/.test(num) ? `<span class="sr-only"> (단계 ${num})</span>` : ''}</a>`).join('')}</div>
    <div class="nav nav-extra"><span class="small">작품 도구</span>${tools.map(([id, href, num, label]) => `<a href="${href}"${id === active ? ' aria-current="page"' : ''}><span class="num" aria-hidden="true">${num}</span>${label}</a>`).join('')}</div>
    <div class="nav nav-extra"><span class="small">본편과 분리</span><a href="${base()}/research"${active === 'research' ? ' aria-current="page"' : ''}><span class="num" aria-hidden="true">R</span>연구 · 모델 실험</a><a href="${base()}/usage"${active === 'usage' ? ' aria-current="page"' : ''}><span class="num" aria-hidden="true">$</span>사용량 · 비용</a></div>
    <div class="side-foot">
      <span class="small">본문 모델</span>
      <strong style="font-size:0.8125rem">${esc(cfg.stages ? cfg.stages.write.model : cfg.model || '')}</strong>
      ${aiWarning() ? `<span style="color:var(--red)">${esc(aiWarning())}</span>` : ''}
      <a href="#/settings">모델 · API 키 설정</a>
      <a href="#/usage">모든 작품 사용량 · 비용</a>
      <a href="#/styles">문체 라이브러리</a>
      <a href="#/">작품 목록</a>
    </div>
    </div>
  </nav>`;
}

function header(eyebrow, title, desc, right = '') {
  return `<header class="page-head"><div class="lead"><div class="eyebrow">${eyebrow}</div><h1>${esc(title)}</h1>${desc ? `<p class="desc">${desc}</p>` : ''}</div><div class="row">${right}</div></header>`;
}

// ----- 설정 -----

const STAGES = [['plan', '계획 (설정 제안, 문체 분석, 기승전결, 화별 플롯)'], ['write', '본문 쓰기'], ['check', '검수'], ['state', '상태 변경안'],
  ['name', '이름·지명 AI 추천'], ['revise', '본문 부분 수정'], ['illustration', '삽화 프롬프트']];
// 백엔드를 비우면 따르는 단계 (settings.STAGE_PARENT 와 같다)
const STAGE_PARENT = { name: 'plan', revise: 'write', illustration: 'plan' };
const STAGE_PARENT_LABEL = { name: '계획 단계를 따름', revise: '본문 쓰기 단계를 따름', illustration: '계획 단계를 따름' };

// 단계 줄의 모델 칸 안내: 지금 고른 백엔드(비우면 부모 단계, 그다음 위 생성 방식)의 기본 모델. 저장 전에도 선택을 따라간다
function stageModelHint(s) {
  const c = S.config || {};
  const val = (sel, saved) => { const el = $(sel); return el ? el.value : saved; };
  const top = c.provider_source === 'env' ? c.provider : val('#set-provider', c.provider);
  const prov = (x) => {
    const st = (c.stages || {})[x] || {};
    if (st.env === `CANON_LLM_${x.toUpperCase()}`) return st.provider;  // 단계 환경 변수가 이긴다
    const own = val(`#set-stage-${x}`, (c.stage_settings || {})[x] || '');
    if (own) return own;
    return STAGE_PARENT[x] ? prov(STAGE_PARENT[x]) : top;
  };
  const p = top === 'mock' ? 'mock' : prov(s);  // 생성 방식이 mock 이면 모든 단계가 mock
  if (p === 'mock') return '모델: mock';
  if (p === 'local') return `모델: ${val('#set-local-model', c.local_model) || '서버에 하나뿐인 모델'}`;
  if (String(p).startsWith('claude')) return `모델: ${val('#set-claude-model', c.claude_model) || 'Claude 기본'}`;
  return `모델: ${val('#set-model', c.model_setting) || '기본'}`;
}

document.addEventListener('change', (e) => {
  if (S.route[0] !== 'settings' || !/^set-(stage-|provider$|model$|local-model$|claude-model$)/.test(e.target.id || '')) return;
  STAGES.forEach(([s]) => {
    const el = $(`#set-stage-model-${s}`);
    if (el) el.placeholder = stageModelHint(s);
  });
});

// 설정 화면 '돌아가기': 앱 안에서 넘어왔으면 뒤로, 주소로 바로 열었으면 앱 첫 화면(작품 안이면 그 작품)으로
let settingsNavs = 0;
window.addEventListener('hashchange', () => { settingsNavs += 1; });
let settingsSavedAt = null;  // 저장 버튼 옆에 남기는 마지막 저장 시각

function providerOptions(cur) {
  return [['gemini', 'Gemini API'], ['local', '로컬 서버 (OpenAI 호환)'], ['claude', 'Claude 구독 로그인 (Claude Code)'], ['claude-api', 'Claude API 키'],
    ['mock', 'mock (AI 호출 없이 화면 확인용)']]
    .map(([v, l]) => `<option value="${v}"${cur === v ? ' selected' : ''}>${l}</option>`).join('');
}

function viewSettings() {
  const c = S.config || {};
  const src = { env: '환경 변수', file: '설정 파일', default: '기본값', none: '없음' };
  const envNote = (s, name) => s === 'env' ? `<div class="small">환경 변수 ${name} 가 설정돼 있어 그 값이 우선해요.</div>` : '';
  // 처음 쓰는 사람은 생성 방식 · 키 · 모델만 보면 된다. 로컬 서버와 단계별 칸은 쓰고 있을 때만 펼친다
  const localOpen = c.provider === 'local' || (!!c.local_url && !['default', 'none'].includes(c.local_url_source)) || Object.values(c.stage_settings || {}).includes('local');
  const stageOpen = Object.values(c.stage_settings || {}).some(Boolean) || Object.values(c.stage_model_settings || {}).some(Boolean);
  const keyState = c.key_source === 'none'
    ? '<span class="chip" style="background:var(--red-soft);color:var(--red)">없음</span>'
    : `<span class="chip finalized">${esc(c.key_hint)}</span> <span class="small">${src[c.key_source]}</span>`;
  return `${header('Canon', '모델 · API 키 설정', '여기서 저장한 값은 이 컴퓨터의 설정 파일에만 들어가요. 작품 폴더나 저장소에는 들어가지 않아요.', '<button type="button" class="btn" data-action="settingsBack">돌아가기</button>')}
    <section class="card">
      <div class="field"><label for="set-provider">생성 방식</label>
        <select id="set-provider">
          ${providerOptions(c.provider)}
        </select>${envNote(c.provider_source, 'CANON_LLM')}
        <div class="small">단계별로 다르게 쓰려면 아래 '단계별 백엔드'에서 고르세요.</div></div>
      ${geminiAuthSettings(c, `<div class="field"><label for="set-key">Gemini API 키 <span class="hint">지금: </span>${keyState}</label>
        <input id="set-key" type="password" autocomplete="off" placeholder="${c.key_source === 'none' ? 'AIza… 로 시작하는 키' : '바꿀 때만 입력'}">
        <div class="small"><a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">Google AI Studio</a>에서 무료로 발급받을 수 있어요. 저장한 키는 화면에 다시 보여주지 않아요.</div>
        ${envNote(c.key_source, 'GEMINI_API_KEY')}</div>`)}
      <div class="field"><label for="set-model">모델</label>
        <input id="set-model" type="text" list="model-options" value="${esc(c.model_setting || '')}">
        ${modelDatalist()}
        <div class="small">모든 단계의 기본 Gemini 모델이에요. gemini-4-argon 이 기본이고, 단계마다 바꾸려면 아래 '단계별 백엔드와 모델'에서 고르세요.</div>${envNote(c.model_source, 'CANON_MODEL')}</div>
      <div class="small" id="model-status">${modelStatus()}</div>
      <details class="set-more"${localOpen ? ' open' : ''}><summary><h2>로컬 서버</h2> <span class="small">Ollama · llama.cpp 같은 내 컴퓨터의 모델을 쓸 때</span></summary>
      <p class="desc">Ollama, llama.cpp, vLLM, LM Studio 처럼 OpenAI 호환 API 를 여는 서버예요. 주소는 /v1 까지 적어요.</p>
      <div class="field"><label for="set-local-url">서버 주소</label>
        <input id="set-local-url" type="text" value="${esc(c.local_url || '')}" placeholder="http://localhost:11434/v1">
        <div class="small">Ollama :11434/v1 · llama.cpp :8080/v1 · vLLM :8000/v1 · LM Studio :1234/v1</div>${envNote(c.local_url_source, 'CANON_LOCAL_URL')}</div>
      <div class="field"><label for="set-local-model">모델 이름</label>
        <input id="set-local-model" type="text" list="model-options" value="${esc(c.local_model || '')}" placeholder="비우면 서버에 하나뿐인 모델">${envNote(c.local_model_source, 'CANON_LOCAL_MODEL')}</div>
      <div class="field"><label for="set-local-key">서버 키 <span class="hint">지금: ${c.has_local_key ? '있음' : '없음'}</span></label>
        <input id="set-local-key" type="password" autocomplete="off" placeholder="서버가 키를 요구할 때만"></div>
      </details>
      ${claudeSettings(c)}
      <details class="set-more"${stageOpen ? ' open' : ''}><summary><h2>단계별 백엔드와 모델</h2> <span class="small">계획 · 본문 · 검수마다 다른 모델을 쓸 때</span></summary>
      <p class="desc">예: 계획과 검수는 gemini-4-argon, 상태 변경안과 이름 추천은 빠르고 싼 gemini-3.8-flash, 본문은 로컬 모델. 모델 칸을 비우면 그 백엔드의 기본 모델(위 '모델' 또는 로컬 '모델 이름')을 써요.</p>
      ${STAGES.map(([s, label]) => {
        const st = (c.stages || {})[s] || {};
        // 단계 자체의 환경 변수는 선택보다 우선하고, 물려받은 환경 변수(CANON_LLM, 부모 단계)는 비워 둘 때만 따른다
        const envLine = (name, own, what) => !name ? '' : name === own
          ? `<div class="small">환경 변수 ${name} 가 우선해요.</div>`
          : `<div class="small">비워 두면 환경 변수 ${name} 의 ${what} 따라요.</div>`;
        return `<div class="field"><label for="set-stage-${s}">${label} <span class="hint">지금: ${esc(st.model || '')}</span></label>
          <div class="stage-row">
            <select id="set-stage-${s}" aria-label="${esc(label)} 백엔드"><option value="">${STAGE_PARENT_LABEL[s] || '위 생성 방식을 따름'}</option>${providerOptions((c.stage_settings || {})[s])}</select>
            <input id="set-stage-model-${s}" type="text" list="model-options" aria-label="${esc(label)} 모델" value="${esc((c.stage_model_settings || {})[s] || '')}" placeholder="${esc(stageModelHint(s))}">
          </div>
          ${envLine(st.env, `CANON_LLM_${s.toUpperCase()}`, '백엔드를')}
          ${envLine(st.model_env, `CANON_MODEL_${s.toUpperCase()}`, '모델을')}</div>`;
      }).join('')}
      </details>
      <div class="row">
        <button class="btn primary" data-action="saveSettings">저장</button>
        <button class="btn" data-action="testSettings">연결 확인</button>
        ${c.key_source === 'file' ? '<button class="btn danger" data-action="clearKey">저장된 키 지우기</button>' : ''}
        <span class="small" role="status">${settingsSavedAt ? `${esc(settingsSavedAt.what)} · ${fmtDateTime(settingsSavedAt.at)}` : ''}</span>
      </div>
      <div class="small">설정 파일: ${esc(c.path)}</div>
    </section>
    <details class="card set-more" id="price-more"><summary><strong>가격표 펼치기</strong> <span class="small">추정 비용 계산에 쓰는 값. 사용량 · 비용 화면에서도 고칠 수 있어요</span></summary><div id="price-box">${viewPrices()}</div></details>
    <div class="small">쓴 비용은 <a href="#/usage">사용량 · 비용</a> 화면에서 봐요.</div>`;
}

// 모델 칸 추천 목록: Gemini API 와 로컬 서버에 실제로 있는 모델. 없으면 직접 적는다.
const KNOWN_MODELS = ['gemini-4-argon', 'gemini-3.8-flash'];

function modelDatalist() {
  const m = S.models || {};
  const opts = [
    ...(((m.gemini || {}).models || []).length ? m.gemini.models : KNOWN_MODELS).map((x) => [x, 'Gemini']),
    ...((m.local || {}).models || []).map((x) => [x, '로컬 서버']),
    ...[...new Set([...((m.claude || {}).models || []), ...((m['claude-api'] || {}).models || [])])].map((x) => [x, 'Claude']),
  ];
  return `<datalist id="model-options">${opts.map(([v, l]) => `<option value="${esc(v)}" label="${l}"></option>`).join('')}</datalist>`;
}

function modelStatus() {
  const m = S.models;
  if (!m) return '모델 목록을 불러오는 중…';
  // 단계에서 쓰는 백엔드만 알린다 (Gemini 만 쓰면 꺼진 로컬 서버 오류는 보이지 않는다)
  const c = S.config || {};
  const used = new Set([c.provider, ...Object.values(c.stages || {}).map((x) => x.provider)]);
  const why = (r) => ({ no_key: c.gemini_auth === 'vertex' ? '서비스 계정 키 파일과 프로젝트 ID를 넣고 저장하면 목록을 불러와요' : 'API 키를 넣고 저장하면 목록을 불러와요', unreachable: '로컬 서버가 응답하지 않아요. 주소를 확인하세요' }[r.reason] || `목록을 못 불러왔어요 (${esc((r.error || '').slice(0, 120))})`);
  const part = (name, r) => (r.error ? `${name}: ${why(r)}` : `${name} ${r.models.length}개`);
  const parts = [['gemini', 'Gemini'], ['local', '로컬 서버']].filter(([k]) => used.has(k) && m[k]).map(([k, name]) => part(name, m[k]));
  return `모델 칸을 누르면 고를 수 있어요. ${parts.length ? parts.join(' · ') + '. ' : ''}목록에 없으면 이름을 직접 적어도 돼요. <button type="button" class="link-btn" data-action="loadModels">다시 불러오기</button>`;
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

/** AI를 쓸 수 있는지 한 줄로 (작품 목록 · 사이드바). 쓸 수 있으면 빈 글. */
function aiWarning() {
  const h = S.health;
  const cfg = S.config || {};
  if (h && h.local === false) return `AI 연결 안 됨: 로컬 모델 서버가 응답하지 않아요 (${h.local_error || '주소를 확인하세요'}).`;
  if (h && h.mock) return 'mock 모드: AI를 부르지 않고 가짜 결과를 내요. 실제로 쓰려면 설정에서 Gemini 나 로컬을 고르세요.';
  if (!cfg.has_key && cfg.gemini_auth === 'vertex') return 'Vertex AI 설정이 덜 됐어요. 설정에서 서비스 계정 키 파일 경로와 프로젝트 ID를 확인하세요.';
  if (!cfg.has_key) return 'Gemini API 키가 없어요. 키 없이는 인물 · 설정을 직접 적을 수 있고, 플롯이 생긴 화부터는 채팅 앱 작업지시서로 쓸 수 있어요.';
  return '';
}

/** 작품 카드의 다음 할 일 한 줄: '3화 상태 승인 대기', '완결', '플롯 없음' (web.list_projects 의 open_ep · open_status) */
function projectNext(x) {
  if (!x.open_ep) return x.planned && x.finalized >= x.episodes ? '완결' : x.planned ? `${x.planned + 1}화부터 플롯 만들기` : '플롯 없음';
  return `${x.open_ep}화 ${{ draft: '플롯 확정 대기', confirmed: '쓰기 대기', written: '상태 승인 대기' }[x.open_status] || ''}`;
}

// 새 작품 폼: 다른 화면에 다녀와도 모든 칸을 함께 남기고, 만들면 함께 비운다 (장르는 genreTarget 이 같은 S.newMeta 에 둔다)
const NEW_FORM = { title: '', name: '', eps: '12', form: 'short', adult: false, style: '', nameEdited: false };
const newForm = () => { const m = genreTarget(); Object.keys(NEW_FORM).forEach((k) => { if (!(k in m)) m[k] = NEW_FORM[k]; }); return m; };
const newFormUsed = (m) => !!(m.title || m.name || m.genres.length || m.eps !== NEW_FORM.eps || m.form !== 'short' || m.adult || m.style);

/** 제목으로 폴더 이름 만들기: 폴더에 못 쓰는 글자를 빼고 빈칸은 - 로 (web.NAME_RE) */
const folderOf = (t) => t.trim().replace(/[/\\:*?"<>|]/g, '').replace(/^\.+/, '').replace(/\s+/g, '-').slice(0, 64);
const FOLDER_BAD = /^\.|[/\\:*?"<>|]/;

/** 작품 홈 · 설정 도우미 머리 아래의 AI 연결 안내 (작품 목록과 같은 글, 설정 화면 링크) */
function aiNote() {
  return aiWarning() ? `<div class="note warn" role="status">${esc(aiWarning())} <a href="#/settings" style="color:inherit;font-weight:700">모델 · API 키 설정</a></div>` : '';
}

function viewProjects() {
  const list = S.projects || [];
  const cards = list.map((x) => `<div class="card tight proj-card">
      <a href="#/p/${enc(x.name)}" style="text-decoration:none;color:inherit;display:flex;flex-direction:column;gap:6px">
      <div class="between"><h3>${esc(x.title || x.name)}</h3><span class="small">${x.finalized} / ${x.episodes}화</span></div>
      <div class="small">${x.form === 'serial' ? '장편' : '단편'} · ${esc(projectNext(x))}</div>
      <div class="small">${esc(x.genre || '장르 미정')} · 폴더 ${esc(x.name)}${x.updated_at ? ` · 고친 때 ${fmtDateTime(x.updated_at)}` : ''}</div></a>
      <details class="proj-more"><summary class="small">관리</summary><div class="row" style="padding-top:6px">
        <button type="button" class="btn small" data-action="dupProject" data-arg="${esc(x.name)}">복제</button>
        <button type="button" class="btn small" data-action="renameProject" data-arg="${esc(x.name)}">폴더 이름 바꾸기</button>
        <button type="button" class="btn small danger" data-action="deleteProject" data-arg="${esc(x.name)}">삭제</button></div></details>
    </div>`).join('');
  const f = newForm();
  const err = S.newErr || {};
  const errOf = (k) => (err.field === k ? `<div class="small field-err" id="np-${k}-err" role="alert">${esc(err.msg)}</div>` : '');
  const bad = (k) => (err.field === k ? ` aria-invalid="true" aria-describedby="np-${k}-err"` : '');
  return `${header('Canon', '작품', '인물, 관계, 문체, 복선을 데이터로 관리하면서 10~20화 단편부터 300화 장편 연재까지 써요. 최근에 고친 작품부터 보여요.', `<a class="btn" href="#/styles">문체 라이브러리</a><a class="btn" href="#/usage">사용량 · 비용</a><a class="btn" href="#/settings">모델 · API 키 설정</a>`)}
    ${aiWarning() ? `<div class="note warn">${esc(aiWarning())} <a href="#/settings" style="color:inherit;font-weight:700">설정</a></div>` : ''}
    ${list.length ? `<div class="grid-auto">${cards}</div>` : '<div class="note plain">아직 작품이 없어요. 아래에서 새 작품을 만드세요.</div>'}
    <form class="card" id="np-form" style="max-width:720px" novalidate>
      <div class="between"><h2>새 작품</h2>${newFormUsed(f) ? '<span class="row"><span class="small">이전에 적던 내용을 이어서 보여요</span><button type="button" class="btn small ghost" data-action="clearNewForm">비우기</button></span>' : ''}</div>
      <div class="grid-2">
        <div class="field"><label for="np-title">제목 <span class="hint">필수</span></label><input id="np-title" type="text" placeholder="등대" required value="${esc(f.title)}"${bad('title')}>${errOf('title')}</div>
        <div class="field"><label for="np-eps">총 화수 <span class="hint">단편 10~20, 장편 100~300</span></label><input id="np-eps" type="number" min="4" max="1000" value="${esc(f.eps)}"${bad('eps')}>${errOf('eps')}</div>
      </div>
      <details${err.field === 'name' || f.nameEdited ? ' open' : ''}><summary class="small">폴더 이름 (주소): ${esc(f.name || folderOf(f.title) || '제목에서 만들어요')}</summary>
        <div class="field" style="padding-top:8px"><label for="np-name">폴더 이름 <span class="hint">projects/ 아래 폴더와 화면 주소에 쓰여요. 비우면 제목으로 만들고, 나중에 작품 카드의 '관리'에서 바꿀 수 있어요</span></label>
          <input id="np-name" type="text" placeholder="${esc(folderOf(f.title) || 'lighthouse')}" value="${esc(f.name)}"${bad('name')}>${errOf('name')}</div></details>
      <fieldset class="field form-pick"><legend class="label">형식</legend>
        <label class="row"><input type="radio" name="np-form" id="np-short" value="short"${f.form === 'serial' ? '' : ' checked'}><span><strong>단편</strong> <span class="small">작품 전체를 기승전결 하나로 짜고 모든 화의 플롯을 한 번에 만들어요</span></span></label>
        <label class="row"><input type="radio" name="np-form" id="np-serial" value="serial"${f.form === 'serial' ? ' checked' : ''}><span><strong>장편 연재</strong> <span class="small">부 → 아크(5~30화) → 화로 나눠, 다음 아크의 플롯만 그때그때 만들어요. 200~300화 웹소설용</span></span></label>
      </fieldset>
      ${genrePicker()}
      ${adultCheck(`id="np-adult"${f.adult ? ' checked' : ''}`)}
      ${(S.libs || []).length ? `<div class="field"><label for="np-style">문체 <span class="hint">라이브러리에서 고르면 문체 단계를 건너뛸 수 있어요. 나중에 바꿔도 돼요</span></label>
        <select id="np-style"><option value="">나중에 정하기</option>${S.libs.map((x) => `<option value="${esc(x.id)}"${f.style === x.id ? ' selected' : ''}>${esc(x.name)}${x.source ? ` · ${esc(x.source)}` : ''}</option>`).join('')}</select></div>` : ''}
      <div class="row"><button type="submit" class="btn primary">만들고 설정 시작</button><span class="small">로그라인은 다음 화면에서 칸을 채우며 만들어요.</span></div>
    </form>`;
}

// 새 작품 폼: 칸을 고칠 때마다 S.newMeta 에 남기고, 제목을 적으면 손대지 않은 폴더 이름도 따라간다. Enter 는 만들기
function syncNewForm(el) {
  const f = newForm();
  const v = (id) => ($(id) || {}).value || '';
  Object.assign(f, { title: v('#np-title'), name: v('#np-name'), eps: v('#np-eps'), style: v('#np-style'),
    adult: !!($('#np-adult') || {}).checked, form: ($('#np-serial') || {}).checked ? 'serial' : 'short' });
  if (el.id === 'np-name') f.nameEdited = !!f.name.trim();
  if (el.id === 'np-title') {
    const sum = $('#np-form details > summary');
    if (sum && !f.name) sum.textContent = `폴더 이름 (주소): ${folderOf(f.title) || '제목에서 만들어요'}`;
    $('#np-name').placeholder = folderOf(f.title) || 'lighthouse';
  }
  if (S.newErr && el.getAttribute('aria-invalid')) {  // 고치기 시작하면 그 칸의 오류 표시를 걷는다
    el.removeAttribute('aria-invalid');
    const m = $(`#${el.id}-err`);
    if (m) m.remove();
    S.newErr = null;
  }
}
// change 는 형식을 바꿀 때 총 화수 기본값을 바꾼 뒤에도 온다 (위 np-form 처리)
['input', 'change'].forEach((t) => document.addEventListener(t, (e) => { if (e.target.closest && e.target.closest('#np-form')) syncNewForm(e.target); }));
document.addEventListener('submit', (e) => {
  if (e.target.id !== 'np-form') return;
  e.preventDefault();
  actions.createProject();
});

// ----- 작품 홈 -----

/** 사이드바 자동 집필 메뉴: 진행 중이거나 사람을 기다리면 다른 화면에서도 보이게 상태를 붙인다. */
function autoMenuLabel() {
  const r = S.auto && S.auto.run;
  if (S.auto && S.auto.active) return '자동 집필 · 진행 중';
  const wait = r && { review: '검토 대기', paused: '일시정지', error: '오류로 멈춤' }[r.status];
  return wait ? `자동 집필 · ${wait}` : '자동 집필';
}

function nextStep() {
  const p = P();
  const r = S.auto && S.auto.run;
  if (r && r.status === 'review' && r.pending && !S.deltas[r.ep]) return [`${r.ep}화 자동 집필 변경안 검토`, base() + '/auto'];
  if (autoOn()) return [`자동 집필 진행 중${autoEp() ? ` (${autoEp()}화)` : ''}`, base() + '/auto'];
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
  const stage = (cls, st, title, sub, href) => `<a class="stage ${cls}" href="${href}"><div class="bar"></div><div class="st">${st}</div><div style="font-size:0.875rem;font-weight:700">${title}</div><div class="small">${sub}</div></a>`;
  const state = (ok, partial) => (ok ? ['done', '완료'] : partial ? ['doing', '진행 중'] : ['', '시작 전']);
  const [s1c, s1t] = state(p.characters.length > 0);
  const [s2c, s2t] = state(hasStyle);
  const [s3c, s3t] = serial() ? state(plannedUntil() >= m.target_episodes, p.story_arcs.length > 0) : state(p.arc.length === 4);
  const [s4c, s4t] = state(eps.length && confirmed === m.target_episodes, confirmed > 0);
  const [s5c, s5t] = state(written === m.target_episodes, written > 0);
  const [s6c, s6t] = state(fin === m.target_episodes, fin > 0);
  const cur = currentEp();
  const [nextLabel, nextHref] = nextStep();
  // 장편: 끝났는데 요약이 없는 아크 · 부 (부 · 아크 화면 경고 줄, pipeline.pending_recaps 와 같은 규칙). 요약이 없으면 줄거리가 접히지 않는다
  const summed = serial() ? p.parts.filter((x) => x.summary) : [];
  const recapArcs = serial() ? [...p.story_arcs].sort((a, b) => a.start_ep - b.start_ep).filter((a) => !a.summary && arcFinished(a) && !summed.some((x) => x.start_ep <= a.start_ep && a.start_ep <= x.end_ep)) : [];
  const recapParts = serial() ? p.parts.filter((x) => !x.summary && arcFinished(x)) : [];
  const recapN = recapArcs.length + recapParts.length;
  const recapBtn = recapArcs.length ? `<a class="btn" href="${base()}/arc/a${recapArcs[0].number}">아크 ${recapArcs[0].number} 요약</a>`
    : recapParts.length ? `<a class="btn" href="${base()}/arc">${recapParts[0].number}부 요약</a>` : '';

  // 단편 기승전결: 칸 폭을 지키려고 칸은 장편처럼 줄을 바꿔 놓고, 구간은 칸 위 띠 대신 칸 아래 테두리 색과 이 머리 줄로 보인다
  const actBand = p.arc.length && !serial() ? `<div class="act-rail">${actGroups(p.arc).map((g) => `<span class="act-chip ${actClass(g.names[0])}">${g.names.join('·')} ${epRange(g.start, g.end)}</span>`).join('')}</div>` : '';
  // 장편은 지금 쓰는 부(없으면 지금 아크 근처 60화)만 칸으로 보인다
  const curPart = serial() ? p.parts.find((x) => x.start_ep <= cur && cur <= x.end_ep) : null;
  const shown = !serial() ? eps : curPart ? eps.filter((e) => e.plot.number >= curPart.start_ep && e.plot.number <= curPart.end_ep)
    : eps.filter((e) => Math.abs(e.plot.number - cur) <= 30);
  const arcBand = serial() && p.story_arcs.length ? `<div class="arc-rail">${p.story_arcs.filter((a) => shown.some((e) => e.plot.number >= a.start_ep && e.plot.number <= a.end_ep)).map((a) => `<a class="arc-chip" href="${base()}/arc/a${a.number}"><strong>아크 ${a.number}</strong> <span>${a.start_ep}~${a.end_ep}화 ${esc(a.title)}</span></a>`).join('')}</div>` : '';
  const cells = shown.map((e) => {
    const n = e.plot.number;
    const href = e.status === 'draft' ? `${base()}/arc/${n}` : e.status === 'written' ? `${base()}/review/${n}` : `${base()}/write/${n}`;
    const act = !serial() && actOf(n);
    const st = e.auto ? '자동 반영' : STATUS[e.status].replace('플롯 ', '').replace('본문 ', '');
    const now = n === cur && e.status !== 'finalized';
    // 좁은 폭에서는 상태 글자를 눈으로만 감춘다. 이름은 aria-label 로 늘 '3화 작성됨 · 제목'
    return `<a class="ep-cell ${e.status}${now ? ' current' : ''}${act ? ' ' + actClass(act.name) + '-edge' : ''}" href="${href}" title="${esc(e.plot.title)}" aria-label="${esc(`${n}화 ${st}${now ? ' · 지금 화' : ''}${e.plot.title ? ' · ' + e.plot.title : ''}`)}"><strong>${n}</strong><span>${st}</span></a>`;
  }).join('');

  const states = p.characters.map((c) => {
    const s = p.states.find((x) => x.character_id === c.id) || {};
    const lines = [['감정', s.emotional_state], ['목표', s.current_goal], ['위치', s.location], ['차림', s.attire]].filter(([, v]) => v);
    return `<div class="kv"><div style="font-size:0.875rem;font-weight:700">${esc(c.name)} <span class="small" style="font-weight:400">${esc(c.role)}</span></div>${lines.map(([k, v]) => `<div class="line">${k}: ${esc(v)}</div>`).join('') || '<div class="line small">아직 변화 없음</div>'}</div>`;
  }).join('');
  const openFs = p.foreshadows.filter((f) => f.status === 'open');
  const last = p.history.length ? p.history[p.history.length - 1] : null;
  const lastWarn = last ? last.warnings : [];

  return `${header(`${esc(m.genre || '장르 미정')}${m.adult ? ' · 성인' : ''} · 전 ${m.target_episodes}화 · 화당 ${Number(m.words_per_episode).toLocaleString()}자`, m.title || S.name, esc(m.logline), `${!serial() && fin && fin === m.target_episodes ? `<a class="btn" href="${base()}/convert">장편으로 늘리기</a>` : ''}<a class="btn" href="${base()}/arc">${serial() ? '부 · 아크 · 플롯' : '기승전결 · 플롯'}</a>${recapBtn}<a class="btn primary" href="${nextHref}">${esc(nextLabel)}</a>`)}
    ${autoLockNote()}
    ${aiNote()}
    <section class="card" aria-label="진행 단계"><div class="stages">
      ${stage(s1c, s1t, '1 설정', `인물 ${p.characters.length} · 관계 ${p.relationships.length}`, base() + '/setup')}
      ${stage(s2c, s2t, '2 문체', hasStyle ? `대표 문단 ${p.style.sample_passages.length}개` : '선택 사항', base() + '/style')}
      ${serial() ? stage(s3c, s3t, '3 부 · 아크', p.story_arcs.length ? `아크 ${p.story_arcs.length}개 · ${plannedUntil()}화까지${recapN ? ` · 요약 필요 ${recapN}개` : ''}` : '없음', base() + '/arc') : stage(s3c, s3t, '3 기승전결', p.arc.length ? '4구간' : '없음', base() + '/arc')}
      ${stage(s4c, s4t, '3 플롯 확정', `${confirmed} / ${m.target_episodes}화`, base() + '/arc')}
      ${stage(s5c, s5t, '4 집필', `${written} / ${m.target_episodes}화`, `${base()}/write/${cur}`)}
      ${stage(s6c, s6t, '5 상태 승인', `${fin} / ${m.target_episodes}화`, `${base()}/review/${cur}`)}
    </div></section>
    <section class="card">
      <div class="between"><h2>화별 진행</h2><div class="legend">
        <span><i style="background:var(--chip);border:1px solid var(--line-strong)"></i>플롯 초안</span>
        <span><i style="background:var(--accent)"></i>플롯 확정</span>
        <span><i style="background:var(--amber)"></i>본문 작성됨</span>
        <span><i style="background:var(--green)"></i>반영 완료</span></div></div>
      ${eps.length ? `${actBand}${arcBand}<div class="ep-grid">${cells}</div>${curPart ? `<div class="small">${curPart.number}부 ${esc(curPart.title)} (${curPart.start_ep}~${curPart.end_ep}화)만 보여요. 전체는 <a href="${base()}/arc">부 · 아크</a>에서 보세요.</div>` : ''}` : `<div class="note plain">아직 화별 플롯이 없어요. 다음 할 일: <a href="${nextHref}">${esc(nextLabel)}</a></div>`}
      ${lastWarn.length ? `<div class="note warn">${last.episode}화 반영 때 검수 경고: ${lastWarn.map(esc).join(' / ')} <a href="${base()}/write/${last.episode}" style="color:inherit;font-weight:700">${last.episode}화 보기</a></div>` : ''}
      ${eps.some((e) => e.status === 'written') ? `<div class="note warn">${cur}화 본문이 작성됐어요. 상태 변경안을 승인해야 다음 화를 쓸 수 있어요. <a href="${base()}/review/${cur}" style="color:inherit;font-weight:700">${cur}화 상태 승인</a></div>` : ''}
    </section>
    <div class="grid-auto">
      <section class="card"><div class="between"><h2>인물 현재 상태</h2><span class="small">${fin ? fin + '화 기준' : '시작 시점'}</span></div>${states || '<div class="small">인물이 없어요</div>'}<a href="${base()}/setup" style="font-size:0.8125rem">인물 · 관계 전체 보기</a></section>
      <section class="card">${relationHeader('관계')}${p.relationships.length ? relationLines(S.relations) : `<div class="small">관계가 없어요. <a href="${base()}/setup">설정 도우미</a>에서 관계를 추가하세요.</div>`}</section>
      <section class="card"><div class="between"><h2>열린 복선</h2><a class="small" href="${base()}/foreshadow">${openFs.length}개 · 복선 센터</a></div>
        ${openFs.map((f) => `<div class="row" style="align-items:flex-start;flex-wrap:nowrap"><span class="chip">${f.planted_ep}화</span><div style="font-size:0.8125rem;line-height:1.5">${esc(f.description)}<br><span class="small">${esc(f.id)}</span></div></div>`).join('') || '<div class="small">없음</div>'}
      </section>
      <section class="card"><div class="between"><h2>확정 사실</h2><span class="small">${p.facts.length}개</span></div>
        ${p.facts.length ? `<ul style="padding-left:18px;display:flex;flex-direction:column;gap:8px;font-size:0.8125rem;line-height:1.5;color:var(--text-2)">${p.facts.slice(-8).map((f) => `<li>${esc(f)}</li>`).join('')}</ul>` : '<div class="small">없음</div>'}
        ${p.facts.length > 8 ? `<details><summary class="small">전체 ${p.facts.length}개 보기</summary><ol style="padding-left:22px;display:flex;flex-direction:column;gap:6px;font-size:0.8125rem;line-height:1.5;color:var(--text-2);margin-top:8px">${p.facts.map((f) => `<li>${esc(f)}</li>`).join('')}</ol></details>` : ''}
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
  if (m !== S.newMeta) { markDirty(); checkNames(); }  // 장르도 자동 이름 스타일을 정한다 (naming.detect_style)
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
  return `<div id="genre-picker" class="genre-picker"><div class="field"><span class="label-text">장르 <span class="hint">여러 개 고를 수 있어요. 고른 장르의 안내가 AI 프롬프트에 들어가요</span></span>
      <div class="genre-opts" role="group" aria-label="장르">${opts('장르')}</div>
      <div class="small" style="margin-top:4px">요소</div>
      <div class="genre-opts" role="group" aria-label="요소">${opts('요소')}${custom.map((c) => `<button type="button" aria-pressed="true" data-action="toggleGenre" data-arg="${esc(c)}" title="직접 적은 장르, 누르면 빠져요">${esc(c)} ✕</button>`).join('')}</div>
      <div class="row" style="flex-wrap:nowrap"><input id="genre-custom" type="text" aria-label="직접 적는 장르" placeholder="목록에 없으면 직접 적기 (예: 오컬트)"><button type="button" class="btn small" style="white-space:nowrap;flex:none" data-action="addCustomGenre">추가</button></div>
    </div>
    ${picked.length ? `<div class="genre-guides">${picked.map(genreGuide).join('')}</div>` : ''}</div>`;
}

function adultCheck(attrs) {
  return `<label class="check-row"><input type="checkbox" ${attrs}><span><strong>성인물</strong> <span class="small">성인 독자 대상. 끄면 노골적인 성적 묘사와 과도한 잔혹 묘사를 피하도록 지시해요</span></span></label>`;
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

// 숫자는 한국어로 읽은 받침이 있나: 영 일 이 삼 사 오 육 칠 팔 구 (logline.DIGIT_FINAL)
const DIGIT_FINAL = '1101001110';

function josa(word, withFinal, withoutFinal) {
  const w = word.trim();
  if (!w) return '';
  const digit = DIGIT_FINAL['0123456789'.indexOf(w[w.length - 1])];
  if (digit) return digit === '1' ? withFinal : withoutFinal;
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
  return `<div class="logline-box"><span class="label-text">로그라인 <span class="hint">다섯 칸을 채우면 한 문장으로 합쳐요. 점선 예시를 누르면 칸에 들어가요</span></span>
    ${legacy ? '<div class="note plain">지금 로그라인은 한 문장으로만 저장되어 있어요. 칸을 채우면 칸 내용으로 바뀌어요.</div>' : ''}
    ${slots}
    <div class="logline-out"><p id="logline-preview" class="logline-preview" aria-live="polite">${esc(m.logline || LOGLINE_EMPTY)}</p><ul id="logline-checks" class="logline-checks">${loglineChecksHtml(m)}</ul></div>
    ${exs.length ? `<details><summary>예시 로그라인 ${exs.length}개 보기</summary><div class="ex-list">${exs.map((e, i) => `<div class="ex-item"><span>${esc(composeLogline(e))}</span><button type="button" class="btn small" data-action="useExample" data-arg="${i}">이 예시로 채우기</button></div>`).join('')}</div></details>` : ''}
    <div id="logline-manual">${loglineManualHtml(m)}</div>
    <details${legacy || loglineManual(m) ? ' open' : ''}><summary>한 문장으로 직접 고쳐 쓰기</summary>${input('로그라인 문장', 'meta.logline', { rows: 3, hint: '직접 고친 문장은 칸을 고쳐도 그대로 둬요' })}</details>
  </div>`;
}

/** 직접 고친 문장을 쓰는 중: 칸 내용과 다르다. 옛 작품처럼 칸이 모두 비었으면 칸을 채울 때 칸 내용으로 바꾼다 */
function loglineManual(m) {
  const parts = m.logline_parts;
  return Object.values(parts).some((v) => v.trim()) && !!m.logline.trim() && m.logline !== composeLogline(parts);
}

function loglineManualHtml(m) {
  return loglineManual(m) ? '<div class="note info row" role="status"><span>직접 고친 문장을 쓰고 있어요. 칸을 고쳐도 이 문장은 바뀌지 않아요.</span><button type="button" class="btn small" data-action="rebuildLogline">칸 내용으로 다시 만들기</button></div>' : '';
}

const LOGLINE_EMPTY = '칸을 채우면 여기에 로그라인이 만들어져요.';

function loglineChecksHtml(m) {
  const parts = m.logline_parts;
  if (!Object.values(parts).some((v) => v.trim())) return '';
  return loglineChecks(parts).map(([ok, t]) => `<li class="${ok ? 'ok' : ''}">${esc(t)}</li>`).join('') + `<li class="len">${m.logline.length}자 · 점검은 참고용이에요</li>`;
}

/** 로그라인 칸이 바뀌면 합친 문장, 점검, 직접 쓰기 칸만 다시 그린다 (입력 중인 칸의 포커스 유지).
    prev 는 바뀌기 전 칸으로 합친 문장: 지금 문장이 그것과 같거나 비었을 때만 새 칸 내용으로 바꾼다 (직접 고친 문장은 남긴다) */
function updateLogline(prev) {
  const m = P().meta;
  const parts = m.logline_parts;
  const empty = !Object.values(parts).some((v) => v.trim());
  if (!empty && (prev === undefined || !m.logline.trim() || m.logline === prev)) {
    m.logline = composeLogline(parts);
    const raw = $('#f-meta-logline');
    if (raw) raw.value = m.logline;
  }
  const pv = $('#logline-preview');
  if (pv) pv.textContent = m.logline || LOGLINE_EMPTY;
  const ck = $('#logline-checks');
  if (ck) ck.innerHTML = loglineChecksHtml(m);
  const mn = $('#logline-manual');
  if (mn) mn.innerHTML = loglineManualHtml(m);
}

function toneBox() {
  const m = P().meta;
  const d = m.tone_dials;
  const rows = TONE_DIALS.map(([k, l, r]) => `<div class="dial" role="group" aria-label="${l}, ${r}"><span>${l}</span>${[1, 2, 3, 4].map((v) => `<button type="button" aria-pressed="${d[k] === v}" aria-label="${l}에서 ${r} 사이 ${v}단계: ${TONE_WORDS[k][v - 1][1]}" title="${TONE_WORDS[k][v - 1][1]}" data-action="setDial" data-arg="${k}|${v}"></button>`).join('')}<span>${r}</span><span class="dial-now">${d[k] >= 1 && d[k] <= 4 ? TONE_WORDS[k][d[k] - 1][1] : ''}</span></div>`).join('');
  const dialText = toneText(d);
  const offer = dialText && m.tone.trim() && m.tone !== dialText
    ? `<div class="row"><span class="small">다이얼 문장: ${esc(dialText)}</span><button type="button" class="btn small" data-action="useToneText">다이얼 문장으로 바꾸기</button></div>` : '';
  return `<div id="tone-box" class="field"><span class="label-text">톤 <span class="hint">양 끝 중 어디에 가까운가. 왼쪽부터 1~4단계이고, 고른 단계를 다시 누르면 꺼져요. 문장은 직접 고쳐도 되고, 직접 쓴 문장은 다이얼이 덮지 않아요</span></span>${rows}${input('톤 문장', 'meta.tone', { placeholder: '예: 조금 어둡고 진지하고 호흡이 느리다' })}${offer}</div>`;
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
  // 없는 인물을 가리키면 첫 인물이 고른 것처럼 보이지 않게 그 id 를 따로 보인다
  const opts = (sel) => (p.characters.some((c) => c.id === sel) ? '' : `<option value="${esc(sel)}" selected>(없는 인물: ${esc(sel)})</option>`)
    + p.characters.map((c) => `<option value="${esc(c.id)}"${c.id === sel ? ' selected' : ''}>${esc(c.name || c.id)}</option>`).join('');
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
    </div>${relProblem(r, i)}
    <div class="genre-opts ex-opts" role="group" aria-label="어떤 사이 예시">${chips(REL_TYPES.map((t) => [t, t]), (t) => r.type === t, 'setRelType')}</div>
    ${started ? `<div class="small">지금 호감 ${r.affinity} · 긴장 ${r.tension}. 첫 반영 뒤에는 본문의 관계 사건으로 바뀌어요.</div>` : `${view('a_view', r.a, r.b)}${view('b_view', r.b, r.a)}`}
    <div class="rel-line"><span class="label-text">원하는 게 부딪치나</span><div class="genre-opts" role="group" aria-label="목표 충돌">${chips(CONFLICTS, (w) => conflictWord(r.goal_conflict || 0) === w, 'setConflict')}</div></div>
    ${started ? '' : `<details><summary>숫자로 직접 정하기</summary><div class="grid-2" style="padding-top:8px">
      <div class="field"><label for="raf${i}">시작 호감 <output id="raf${i}o">${r.affinity}</output> <span class="hint">보는 방식을 고른 방향은 고른 말이 우선</span></label><input id="raf${i}" type="range" min="-5" max="5" value="${r.affinity}" data-bind="${b}.affinity" data-kind="int" data-out="raf${i}o"></div>
      <div class="field"><label for="rg${i}">목표 충돌 <output id="rg${i}o">${r.goal_conflict || 0}</output></label><input id="rg${i}" type="range" min="0" max="1" step="0.1" value="${r.goal_conflict || 0}" data-bind="${b}.goal_conflict" data-kind="float" data-out="rg${i}o"></div>
    </div></details>`}
  </div>`;
}

/** 같은 인물끼리이거나 앞선 관계와 같은 쌍이면 알린다. 서버는 이런 관계를 저장하지 않는다 (pipeline.validate_relationships). */
function relProblem(r, i) {
  if (r.a === r.b) return '<div class="note warn" role="status">같은 인물끼리는 관계를 만들 수 없어요. 인물 B를 바꾸세요.</div>';
  const j = P().relationships.findIndex((x, k) => k !== i && [x.a, x.b].sort().join('|') === [r.a, r.b].sort().join('|'));
  return j >= 0 ? `<div class="note warn" role="status">이 두 인물의 관계가 ${j + 1}번째에도 있어요. 하나만 남기세요.</div>` : '';
}

function refreshRel(i) {
  // 인물을 바꾸면 다른 관계와 겹치는지도 바뀐다. 바꾼 줄은 다시 그리고, 다른 줄은 알림만 고친다
  P().relationships.forEach((r, k) => {
    const el = $(`#rel-${k}`);
    if (!el) return;
    if (k === i) { el.outerHTML = relRow(r, k); return; }
    const old = el.querySelector(':scope > .note.warn');
    if (old) old.remove();
    const note = relProblem(r, k);
    if (note) el.querySelector('.rel-top').insertAdjacentHTML('afterend', note);
  });
}

async function loadNames(key, req, ai) {
  await run(ai ? 'AI가 고르는 중' : '후보 뽑는 중', async () => {
    const r = await api('POST', `/projects/${enc(S.name)}/names`, { ...req, ai, n: 8, project: P() });
    S.names[key] = { ...r, ai };
    if (S.nameCheck) Object.assign(S.nameCheck, { style: r.style, detected: r.detected });
  });
}

/** 이름 점검에 필요한 칸만 (작품 전체를 보내지 않는다, web.NameCheckIn). */
const nameCheckBody = () => ({ meta: P().meta, world: P().world, characters: P().characters, cast_candidates: P().cast_candidates });

let nameSeq = 0;
async function checkNames(show = false) {
  const my = ++nameSeq;
  const busy = $('#name-check');
  if (show && busy) busy.innerHTML = '<span class="small">이름을 점검하는 중…</span>';
  const r = await api('POST', `/projects/${enc(S.name)}/names/check`, nameCheckBody()).catch(() => null);
  if (my !== nameSeq) return;  // 더 나중에 보낸 점검이 있으면 그 결과를 쓴다
  if (!r) {  // 실패: 이전 경고를 그대로 두지 않고 못 했다고 알린다
    S.nameCheck = { failed: true, detected: (S.nameCheck || {}).detected };
    const box = $('#name-check');
    if (box) box.outerHTML = nameCheckBox();
    if (show) toast('이름 점검을 못 했어요. 잠시 뒤 다시 해 보세요', true);
    return;
  }
  S.nameCheck = r;
  const box = $('#name-check');
  if (box) box.outerHTML = nameCheckBox();
  document.querySelectorAll('[data-name-issues]').forEach((el) => { el.outerHTML = nameIssuesFor(el.dataset.nameIssues); });
  const auto = $('#name-style-auto');
  if (auto) auto.textContent = `자동 (지금: ${styleLabel(r.detected)})`;
  if (show) toast(r.warnings.length ? `이름 점검: ${r.warnings.length}건` : '이름 점검: 문제 없음');
}

function styleLabel(id) {
  const st = (S.namingStyles || []).find((x) => x.id === id);
  return st ? st.label : id || '';
}

/** 이름 점검 묶음: 종류별 소제목, 같은 이름 · 같은 성 뺀 이름만 경고 색, 나머지는 안내 색. 줄마다 그 인물 이름 칸으로 가는 버튼. */
function nameCheckBox() {
  const nc = S.nameCheck || {};
  const issues = nc.issues || (nc.warnings || []).map((text) => ({ kind: 'other', level: 'warn', text, ids: [] }));
  const live = 'role="status" aria-live="polite"';
  if (nc.failed) return `<div id="name-check" class="note warn" ${live}>이름 점검을 못 했어요. <button type="button" class="link-btn small" data-action="checkNames">다시 시도</button></div>`;
  if (!issues.length) return `<div id="name-check" ${live}>${S.nameCheck ? '<span class="small">이름 점검: 문제 없음</span>' : ''}</div>`;
  const kinds = nc.kinds || {};
  const order = ['same', 'given', 'confusable', 'era', 'style', 'overused', 'other'];
  const warn = issues.some((i) => i.level === 'warn');
  const groups = order.map((k) => [k, issues.filter((i) => i.kind === k)]).filter(([, l]) => l.length);
  const body = groups.map(([k, list]) => `<div class="small" style="margin-top:6px;font-weight:700">${esc(kinds[k] || '기타')}</div>
    <ul style="margin:2px 0 0;padding-left:18px">${list.map((i) => `<li>${esc(i.text)} ${nameJump(i.ids)}</li>`).join('')}</ul>`).join('');
  const head = `이름 점검 ${issues.length}건${warn ? ` · 같은 이름 ${issues.filter((i) => i.level === 'warn').length}건` : ''}`;
  return `<div id="name-check" class="note ${warn ? 'warn' : 'info'}" ${live}>${issues.length > 3
    ? `<details${warn ? ' open' : ''}><summary><strong>${head}</strong></summary>${body}</details>` : `<strong>${head}</strong>${body}`}</div>`;
}

/** 경고 줄의 인물 이름 버튼: 누르면 그 인물 카드의 이름 칸으로 간다 (후보 인물은 카드가 없어 이름만 보인다). */
function nameJump(ids) {
  return (ids || []).map((id) => {
    const i = P().characters.findIndex((c) => c.id === id);
    return i < 0 ? '' : `<button type="button" class="link-btn small" data-action="focusName" data-arg="${i}" aria-label="${i + 1}번 인물 ${esc(P().characters[i].name || id)} 이름 칸으로">${i + 1}번 ${esc(P().characters[i].name || id)}</button>`;
  }).join(' ');
}

/** 인물 카드 · 플롯 서랍의 새 인물 칸 아래: 그 인물에 해당하는 이름 점검만 작게 (위 묶음이 화면 밖이어도 보이게). */
function nameIssuesFor(id) {
  const list = ((S.nameCheck || {}).issues || []).filter((i) => (i.ids || []).includes(id));
  return `<div data-name-issues="${esc(id)}">${list.map((i) => `<div class="small" style="color:${i.level === 'warn' ? 'var(--amber-ink)' : 'var(--muted)'}">${esc(i.text)}</div>`).join('')}</div>`;
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
      <div class="between"><strong style="font-size:1rem" data-char-head="${i}">${esc(c.name || '이름 없음')}</strong><button class="btn small danger" data-action="removeCharacter" data-arg="${i}" aria-label="${esc(c.name || c.id)} 삭제">삭제</button></div>
      <div class="grid-2">${input('이름', b + '.name')}${input('역할', b + '.role', { placeholder: '주인공, 상대역, 조력자…' })}</div>
      ${nameIssuesFor(c.id)}
      <div class="grid-2">${input('나이', b + '.age', { placeholder: '예: 17세, 40대 초반' })}${input('성별', b + '.gender', { placeholder: '남 / 여' })}</div>
      ${tierSelect(c, b, 'tier-' + i)}
      <div class="row"><button type="button" class="btn small" data-action="nameCandidates" data-arg="${esc(c.id)}">이름 후보 뽑기</button><button type="button" class="btn small" data-action="nameAI" data-arg="${esc(c.id)}">AI 이름 추천</button></div>
      ${namePicks('c:' + c.id, 'useName', (n) => `${c.id}|${n}`)}
      ${input('원하는 것', b + '.goal', { hint: '작품 전체에서' })}
      ${input('두려운 것 · 약점', b + '.wound')}
      ${input('숨기는 것', b + '.secrets', { kind: 'list', rows: 2 })}
      ${input('말투 (대사)', b + '.speech_style', { rows: 2, hint: '어미, 호칭, 대사 한 줄' })}
      ${voiceField(c, b)}
      <details><summary>더 자세히: 성격, 배경, 외모, 아크</summary><div style="display:flex;flex-direction:column;gap:10px;padding-top:8px">
        ${input('성격', b + '.personality', { rows: 2 })}${input('배경', b + '.background', { rows: 2 })}${input('외모', b + '.appearance')}
        ${input('아크', b + '.arc', { hint: '시작 → 결말' })}${input('id', b + '.id', { hint: '관계와 플롯이 인물을 찾는 값. 보통 바꿀 필요 없어요' })}
      </div></details>
      ${visualFields(c)}
    </article>`;
  }).join('');

  const rels = p.relationships.map(relRow).join('');

  // 인물이 없으면 첫 할 일은 AI 제안이다. 인물이 생기면 다음 단계(문체)를 앞세운다
  const first = !p.characters.length;
  return `${header('1단계', '설정 도우미', '채운 칸은 그대로 두고, 빈칸만 AI가 제안해요. 제안에서 원하는 인물과 관계만 골라 적용하세요. 말로 고쳐 가려면 대화로 다듬기를 여세요.', `${((b) => `<button class="btn${first ? ' primary' : ''}" data-action="suggest"${b.attr}>${b.label}</button>`)(jobBtn('suggest', null, '빈칸 AI 제안받기'))}${chatButton('setup')}<a class="btn${first ? '' : ' primary'}" href="${base()}/style">문체로</a>`)}
    ${aiNote()}
    ${S.suggestion ? viewSuggestion() : ''}
    <nav class="jump-nav" aria-label="설정 구역">${[['setup-basic', '기본 정보'], ['setup-world', '세계관'], ['setup-chars', `인물 ${p.characters.length}`], ['setup-rels', `관계 ${p.relationships.length}`]]
      .map(([id, l]) => `<button type="button" class="btn small ghost" data-action="jumpTo" data-arg="${id}">${l}</button>`).join('')}</nav>
    <div class="cols">
      <div class="col">
        <section class="card" id="setup-basic">
          <h2>기본 정보</h2>
          ${input('제목', 'meta.title')}
          ${genrePicker()}
          ${adultCheck(`data-bind="meta.adult" data-kind="bool"${P().meta.adult ? ' checked' : ''}`)}
          ${serial() ? input('총 화수', 'meta.target_episodes', { type: 'number', min: 1, max: 1000, hint: '늘리거나 줄이면 마지막 부 끝 화가 따라가요' }) : input('총 화수', 'meta.target_episodes', { type: 'number', min: 4, max: 40, hint: '단편은 10~20화를 권해요 · 4~40화' })}
          ${loglineBuilder()}
          ${input('주제', 'meta.theme', { hint: '이 이야기가 끝까지 묻는 질문 하나', placeholder: '예: 떠난 사람을 이해하면 용서할 수 있나?' })}
          ${toneBox()}
          ${input('화당 분량', 'meta.words_per_episode', { type: 'number', hint: '공백 포함 글자 수' })}
          ${input('메모', 'meta.notes', { rows: 2 })}
        </section>
        <section class="card" id="setup-world">
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
        <section class="card" id="setup-chars">
          <div class="between"><h2>인물 <span class="small">${p.characters.length}명</span></h2><button class="btn small" data-action="addCharacter">+ 인물 추가</button></div>
          <p class="small">이름, 말투, 성격은 고정 설정이에요. 회차가 지나며 바뀌는 감정과 목표는 상태 승인 화면에서 관리해요.</p>
          <div class="row"><button type="button" class="btn small ghost" data-action="checkNames">이름 점검</button><span class="small">글자가 겹치는 이름, 나이와 안 맞는 이름, AI가 자주 짓는 이름을 찾아요</span></div>
          ${nameCheckBox()}
          ${chars ? `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px">${chars}</div>` : '<div class="note plain">인물이 없어요. 직접 추가하거나 AI 제안을 받으세요.</div>'}
        </section>
        <section class="card" id="setup-rels">
          <div class="between"><h2>관계</h2><div class="row"><span class="small">${P().snapshots.length ? '첫 반영 뒤에는 관계 사건으로 계산돼요' : '서로 어떻게 보는지 고르면 시작 관계를 계산해요. 긴장은 자동 계산'}</span><button class="btn small" data-action="addRelationship"${autoOn() ? ' disabled' : ''}>+ 관계 추가</button></div></div>
          ${autoOn() ? `<div class="note warn" id="rel-lock">자동 집필이 도는 동안은 관계를 고칠 수 없어요. 반영하는 관계와 겹치지 않게 서버가 받지 않아요. 고치려면 <a href="${base()}/auto">자동 집필</a>을 일시정지하세요.</div>` : ''}
          ${rels ? (autoOn() ? `<fieldset disabled class="lockset" aria-describedby="rel-lock">${rels}</fieldset>` : rels) : '<div class="small">관계가 없어요.</div>'}
        </section>
      </div>
    </div>${chatPanel('setup')}`;
}

/** 제안 인물이 이미 있는 인물과 같은 사람이다: id 가 같고 이름도 같다 (이름이 다르면 서버가 새 id 로 넣는다, pipeline.apply_setup). */
function sameChar(c) {
  const old = P().characters.find((x) => x.id === c.id);
  return !!old && (!(c.name || '').trim() || (old.name || '').trim() === c.name.trim());
}

/** 제안 관계의 한쪽 인물. 고른 제안 인물이면 그 인물, 아니면 이미 있는 인물. 고르지 않은 제안 인물이면 null (관계를 넣지 않는다). */
function sugEnd(id) {
  const s = S.suggestion;
  const i = s.characters.findIndex((c) => c.id === id);
  if (i >= 0 && !sameChar(s.characters[i])) return S.picks['sc' + i] ? s.characters[i] : null;
  return P().characters.find((c) => c.id === id) || null;
}

// 설정 제안에서 칸마다 고르는 기본 정보 · 세계관 (pipeline.apply_setup 은 빈 칸만 채운다)
const SUG_FIELDS = [['theme', '주제'], ['tone', '톤'], ['world.setting', '배경'], ['world.era', '시대'], ['world.rules', '규칙'], ['world.locations', '장소'], ['world.name_style', '이름 스타일'], ['world.name_rules', '이름 규칙']];
/** 제안(SetupSuggestion)이나 작품(Project)의 그 칸 글. 작품의 주제 · 톤은 meta 에 있다. */
function sugValue(o, k) {
  const v = k.startsWith('world.') ? o.world[k.slice(6)] : (o.meta ? o.meta[k] : o[k]);
  return Array.isArray(v) ? v.join(', ') : String(v || '');
}

function viewSuggestion() {
  const s = S.suggestion;
  const exists = (c) => sameChar(c);
  const clash = (c) => !sameChar(c) && P().characters.some((x) => x.id === c.id);
  return `<section class="card" style="border:2px solid var(--accent)">
    <div class="between"><h2>AI 제안 <span class="chip ai">적용 전</span></h2>${proposalActions(['dropSuggestion'], ['applySuggestion'])}</div>
    <p class="small">주제, 톤, 세계관은 비어 있는 칸에만 들어가요. 이미 있는 인물 id 는 건너뛰어요.</p>
    <div class="sug-fields">${SUG_FIELDS.map(([k, label]) => {
    const v = sugValue(s, k);
    if (!v.length) return '';
    const have = sugValue(P(), k).length > 0;
    return `<label class="row sug-field${have ? ' skip' : ''}"><input type="checkbox" data-pick="sf:${k}"${!have && S.picks['sf:' + k] !== false ? ' checked' : ''}${have ? ' disabled' : ''}><strong>${label}</strong> <span>${esc(v)}</span>${have ? ' <span class="small">이미 있음 · 건너뜀</span>' : ''}</label>`;
  }).join('')}</div>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px">
      ${s.characters.map((c, i) => `<label class="char-card suggested" style="cursor:pointer"><span class="row"><input type="checkbox" data-pick="sc${i}"${S.picks['sc' + i] ? ' checked' : ''}${exists(c) ? ' disabled' : ''}><strong>${esc(c.name)}</strong><span class="small">${esc(c.role)} · ${esc(c.id)}${exists(c) ? ' · 이미 있음' : clash(c) ? ' · 같은 id 의 다른 인물이 있어 새 id 로 넣어요' : ''}</span></span>
        <span style="font-size:0.8125rem;line-height:1.5">목표: ${esc(c.goal)}<br>말투: ${esc(c.speech_style)}</span></label>`).join('')}
    </div>
    ${s.relationships.map((r, i) => {
    const a = sugEnd(r.a);
    const b = sugEnd(r.b);
    const nm = (c, id) => esc(c ? c.name || c.id : id);
    const off = !a || !b;
    return `<label class="row" style="font-size:0.8125rem"><input type="checkbox" data-pick="sr${i}"${S.picks['sr' + i] && !off ? ' checked' : ''}${off ? ' disabled' : ''}>${nm(a, r.a)} ↔ ${nm(b, r.b)} · ${esc(r.type)} · ${(r.a_view || []).length || (r.b_view || []).length ? `${nm(a, r.a)}→${nm(b, r.b)} ${esc((r.a_view || []).join(', ') || '-')} · ${nm(b, r.b)}→${nm(a, r.a)} ${esc((r.b_view || []).join(', ') || '-')}` : `호감 ${r.affinity} · 긴장 ${r.tension}`}${off ? ' <span class="small">(고르지 않은 인물이라 넣지 않아요)</span>' : ''}</label>`;
  }).join('')}
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
  const passages = prof.sample_passages.map((_, i) => `<div class="field-row">
      <div class="fr-grow">${input(`대표 문단 ${i + 1}`, `${base}.sample_passages.${i}`, o({ rows: 3 }))}</div>
      <button class="btn icon-btn danger" data-action="${act}" data-arg="${i}" aria-label="대표 문단 ${i + 1} 삭제">✕</button></div>`).join('');
  prof.markers = prof.markers || [];
  // 좁은 폭에서는 표지 · 쓰임을 한 줄씩 펼친다 (한 줄에 넷을 두면 표지 칸이 40px 남짓으로 눌린다)
  const markers = prof.markers.map((_, i) => `<div class="field-row mk-row">
      <div class="mk-text">${input(`표지 ${i + 1}`, `${base}.markers.${i}.text`, o({ placeholder: '원문에 적힌 그대로, 예: 것이었다' }))}</div>
      <div class="mk-note">${input('쓰임', `${base}.markers.${i}.note`, o())}</div>
      <div class="mk-rate">${input('1,000자당', `${base}.markers.${i}.per_1k`, o({ kind: 'float' }))}</div>
      <button class="btn icon-btn danger" data-action="${root ? 'libRemoveMarker' : 'removeMarker'}" data-arg="${i}" aria-label="표지 ${i + 1} 삭제">✕</button></div>`).join('');
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
    ${markers || '<div class="small">아직 없어요. 문체 분석을 하면 원문에서 골라 빈도를 세어요.</div>'}
    ${deviceFields(base, root)}
    <div class="between"><h3>대표 문단 <span class="small" style="font-weight:400">본문 생성 때 그대로 보여줄 원문 예시, 2~4개</span></h3><button class="btn small" data-action="${root ? 'libAddPassage' : 'addPassage'}">+ 문단</button></div>
    ${passages || '<div class="small">아직 없어요. 문체 분석을 하면 원문에서 골라 넣어요.</div>'}`;
}

/** 작품 문체 화면 위쪽: 라이브러리에서 가져오기, 라이브러리에 저장하기 */
/** 라이브러리와 다를 때 어느 쪽이 바뀌었는지 (library.link_state 의 mine · theirs). */
function styleChangeWho(l) {
  const mine = (l.mine || []).length > 0;
  const theirs = (l.theirs || []).length > 0;
  if (!l.base_known) return l.applied && l.version > l.applied ? `이 작품은 ${l.applied}번 버전, 라이브러리는 ${l.version}번 버전이에요` : '이 작품에서 고쳤거나 라이브러리가 바뀌었어요';
  if (mine && theirs) return `이 작품도 고쳤고, 라이브러리도 ${l.applied}번 → ${l.version}번 버전으로 바뀌었어요`;
  if (theirs) return `라이브러리가 ${l.applied}번 → ${l.version}번 버전으로 바뀌었어요. 이 작품은 그대로예요`;
  return '이 작품에서 고쳤어요. 라이브러리는 가져온 버전 그대로예요';
}

function styleLibraryCard() {
  const libs = S.libs || [];
  const l = S.styleLink || { state: 'none' };
  const opts = libs.map((x) => `<option value="${esc(x.id)}"${x.id === l.id ? ' selected' : ''}>${esc(x.name)}${x.source ? ` · ${esc(x.source)}` : ''}</option>`).join('');
  const blank = styleBlank(P().style);
  const status = {
    none: blank ? '<span class="small">아직 문체가 없어요. 아래에 원문을 붙여 넣어 분석하거나 라이브러리에서 고르세요.</span>' : '<span class="small">이 작품에서 직접 만든 문체예요.</span>',
    missing: '<span class="small">가져온 라이브러리 항목이 지워졌어요. 작품에 복사된 문체는 그대로 써요.</span>',
    same: `<span class="chip finalized">라이브러리와 같음</span> <a href="#/styles/${esc(l.id)}">${esc(l.name)}</a> <span class="small">${l.version}번 버전</span>`,
    changed: `<span class="chip written">라이브러리와 다름</span> <a href="#/styles/${esc(l.id)}">${esc(l.name)}</a> <span class="small">${styleChangeWho(l)}</span>`,
  }[l.state] || '';
  const fields = (list) => list.map((c) => esc(c.label)).join(', ');
  const detail = l.state === 'changed' && ((l.mine || []).length || (l.theirs || []).length)
    ? `<details><summary class="small">어느 칸이 다른지</summary><div class="small" style="padding-top:6px">${(l.mine || []).length ? `<div>이 작품에서 고친 칸: ${fields(l.mine)}</div>` : ''}${(l.theirs || []).length ? `<div>라이브러리 ${l.version}번 버전에서 바뀐 칸: ${fields(l.theirs)}</div>` : ''}<div>올리기는 작품 쪽을 라이브러리 새 버전으로, 가져오기 · 되돌리기는 라이브러리 쪽을 작품에 가져와요.</div></div></details>` : '';
  // 라이브러리가 더 새 버전이면 '가져오기', 작품만 고쳤으면 '되돌리기'
  const newer = (l.theirs || []).length > 0 || (!l.base_known && l.applied && l.version > l.applied);
  const linkBtns = l.state === 'changed'
    ? `<button class="btn small" data-action="pushStyle">라이브러리 새 버전으로 올리기</button><button class="btn small" data-action="pullStyle">${newer ? '라이브러리 최신 버전 가져오기' : '라이브러리 버전으로 되돌리기'}</button>`
    : '';
  // 빈 문체는 저장하지 않는다 (web.keep_style 도 막는다). 프로필 칸을 채우면 아래 input 처리가 버튼을 켠다
  const keepOff = blank;
  return `<section class="card tight">
      <div class="between"><h2>문체 라이브러리</h2><a class="small" href="#/styles">라이브러리 열기</a></div>
      <div class="row">${status}</div>${detail}
      <div class="row" style="flex-wrap:nowrap">
        ${libs.length
          ? `<select id="style-pick" aria-label="라이브러리 문체" style="flex:1"><option value="">라이브러리에서 고르기</option>${opts}</select><button class="btn small" style="flex:none" data-action="useLibStyle">적용</button>`
          : `<span class="small" style="flex:1">라이브러리가 비어 있어요. ${blank ? '문체를 만든 뒤 저장해 두면' : '이 작품의 문체를 저장해 두면'} 다른 작품에서 다시 쓸 수 있어요.</span>`}
      </div>
      <div class="row">${linkBtns}<button class="btn small" data-action="keepStyle"${keepOff ? ' disabled aria-describedby="keep-off"' : ''}>이 문체를 라이브러리에 새로 저장</button><span class="small" id="keep-off"${keepOff ? '' : ' hidden'}>문체 분석이나 프로필을 채운 뒤 저장할 수 있어요</span></div>
    </section>`;
}

// 작품 문체 칸을 채우거나 비우면 '라이브러리에 새로 저장' 버튼을 켜고 끈다 (다시 그리지 않고)
document.addEventListener('input', (e) => {
  if (S.route[2] !== 'style' || !(e.target.dataset.bind || '').startsWith('style.')) return;
  const btn = $('[data-action="keepStyle"]');
  if (!btn) return;
  btn.disabled = styleBlank(P().style);
  const why = $('#keep-off');
  if (why) why.hidden = !btn.disabled;
});

/** 스타일 프로필 칸이 모두 비었다 (library.blank 와 같은 규칙) */
const styleBlank = (st) => !Object.values(st || {}).some((v) => (typeof v === 'string' ? v.trim() : Array.isArray(v) ? v.length : v));

function viewStyle() {
  return `${header('2단계', '문체 레퍼런스', '닮고 싶은 소설 문단을 붙여 넣으면 문체 규칙을 뽑아요. 규칙과 원문 예시가 매 화 본문 생성에 함께 들어가요. 라이브러리에 저장한 문체를 그대로 가져올 수도 있고, 대화로 다듬어 갈 수도 있어요.', `${chatButton('style')}<a class="btn primary" href="${base()}/arc">기승전결로</a>`)}
    <div class="cols">
      <div class="col">
        ${styleLibraryCard()}
        ${learnCard()}
        <section class="card">
          <div class="between"><h2>예시 원문</h2><span class="small"><span id="sample-count">${S.styleSample.length.toLocaleString()}</span>자 · 2,000자 이상 권장</span></div>
          <label for="sample" class="small">소설 본문을 붙여 넣으세요. 원문은 작품에 저장되지 않고 고른 대표 문단만 남아요. 이 칸에 원문이 남아 있을 때 라이브러리에 저장하면 원문도 함께 보관해요. 새로고침하면 이 칸은 비어요.</label>
          <textarea id="sample" rows="16" data-local="styleSample" oninput="document.getElementById('sample-count').textContent=this.value.length.toLocaleString()" style="font-family:var(--serif);font-size:0.9375rem;line-height:1.9">${esc(S.styleSample)}</textarea>
          <div><button class="btn dark" data-action="analyzeStyle">문체 분석</button></div>
          <div class="note plain">원문은 문체 분석과 예시 문단으로만 쓰여요. 내용이나 인물은 작품에 가져오지 않아요.</div>
        </section>
        <section class="card tight"><h2>기준 지표</h2><div class="small">본문 문체 경고는 이 값과 비교해요.</div>${baselineRows(P().style_baseline)}</section>
      </div>
      <div class="col wide">
        ${styleExampleCard()}
        <section class="card">
          <div class="between"><h2>스타일 프로필</h2><span class="small">모든 칸은 직접 고칠 수 있어요</span></div>
          ${profileFields('style')}
        </section>
      </div>
    </div>${chatPanel('style')}`;
}

// ----- 문체 라이브러리 -----

/** 날짜 'YYYY.MM.DD' 와 날짜 시각 'YYYY.MM.DD HH:mm'. 서버는 UTC 로 적으므로 이 기기의 시간대로 바꿔 보인다. */
function fmtDate(iso) {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) return iso || '';
  const p2 = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}.${p2(d.getMonth() + 1)}.${p2(d.getDate())}`;
}

function fmtDateTime(iso) {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) return iso || '';
  const p2 = (x) => String(x).padStart(2, '0');
  return `${fmtDate(iso)} ${p2(d.getHours())}:${p2(d.getMinutes())}`;
}

/** 예시 문구에 넣을 인물 이름: 이 작품의 i번째 인물. 없으면 '주인공', '조연' (특정 작품의 이름을 박아 두지 않는다) */
const exName = (i = 0) => (P() && P().characters[i] && P().characters[i].name) || ['주인공', '조연', '악역'][i] || '인물';

/** 화 범위 'a~b화' (한 화면 'a화'). 범위 기호는 물결표 하나로 쓴다. */
const epRange = (a, b) => (a === b ? `${a}화` : `${a}~${b}화`);

function viewLibrary() {
  const list = S.libs || [];
  const cards = list.map((x) => `<article class="card tight">
      <div class="between"><h3><a href="#/styles/${esc(x.id)}" style="color:inherit;text-decoration:none">${esc(x.name)}</a></h3><span class="small">${fmtDate(x.updated_at)}</span></div>
      ${x.source ? `<div class="small">${esc(x.source)}</div>` : ''}
      <div class="row">
        ${x.narration_pov ? `<span class="chip">${esc(x.narration_pov)}</span>` : ''}${x.tense ? `<span class="chip">${esc(x.tense)}</span>` : ''}
        <span class="chip">대표 문단 ${x.passages}</span><span class="chip">지킬·피할 것 ${x.rules}</span>${[['금지 표현', x.banned], ['표지', x.markers], ['장치', x.devices]].filter(([, v]) => v).map(([k, v]) => `<span class="chip">${k} ${v}</span>`).join('')}
        ${x.sample_chars ? `<span class="chip">원문 ${x.sample_chars.toLocaleString()}자</span>` : ''}
      </div>
      ${x.notes ? `<div class="small" style="white-space:pre-line">${esc(x.notes)}</div>` : ''}
      <div class="small">${x.used_by.length ? `쓰는 작품: ${x.used_by.map((n) => `<a href="#/p/${enc(n)}/style">${esc(n)}</a>`).join(', ')}` : '아직 쓰는 작품이 없어요'}</div>
      <div class="row"><a class="btn small" href="#/styles/${esc(x.id)}">열기</a><button class="btn small" data-action="libDuplicate" data-arg="${esc(x.id)}">복제</button><button class="btn small danger" data-action="libDelete" data-arg="${esc(x.id)}">삭제</button></div>
    </article>`).join('');
  // 비었을 때는 빈 카드의 버튼 하나만 주 버튼으로 둔다
  return `${header('Canon', '문체 라이브러리', '붙여 넣은 원문에서 뽑은 문체를 작품과 따로 모아 둬요. 작품에 적용하면 그 시점의 문체가 작품에 복사되고, 라이브러리를 고쳐도 쓰고 있는 작품은 다시 적용하기 전까지 그대로예요.', `<a class="btn" href="#/">작품 목록</a>${list.length ? '<a class="btn primary" href="#/styles/new">+ 새 문체</a>' : ''}`)}
    ${list.length ? `<div class="grid-auto">${cards}</div>` : `<div class="card empty"><div>아직 저장한 문체가 없어요.</div><div class="small">새 문체를 만들거나, 작품의 문체 레퍼런스 화면에서 '이 문체를 라이브러리에 새로 저장'을 누르세요.</div><a class="btn primary" href="#/styles/new">+ 새 문체</a></div>`}`;
}

function baselineRows(b) {
  if (!b) return '<div class="small">원문을 넣고 저장하면 문장 길이, 대사 비율 같은 기준 지표를 재요. 본문을 쓴 뒤 문체가 얼마나 벗어났는지 비교하는 기준이 돼요.</div>';
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
  const right = `<a class="btn" href="#/styles">목록으로</a>${isNew ? '' : `<button class="btn" data-action="libDuplicate" data-arg="${esc(e.id)}">복제</button><button class="btn danger" data-action="libDelete" data-arg="${esc(e.id)}">삭제</button><button class="btn" data-action="libRevert"${S.libDirty ? '' : ' disabled'}>저장 전으로</button>`}<button class="btn primary" data-action="libSave">저장</button>`;
  const apply = isNew ? '' : `<section class="card tight">
      <h2>작품에 적용</h2>
      <div class="small">${used.length ? `쓰는 작품: ${used.map((n) => `<a href="#/p/${enc(n)}/style">${esc(n)}</a>`).join(', ')}` : '아직 쓰는 작품이 없어요.'}</div>
      ${used.length ? '<div class="small">여기서 고친 내용은 작품의 문체 화면에서 \'라이브러리 최신 버전 가져오기\'를 눌러야 그 작품에 들어가요.</div>' : ''}
      ${(S.projects || []).length ? `<div class="row" style="flex-wrap:nowrap"><select id="lib-target" aria-label="적용할 작품" style="flex:1"><option value="">작품 고르기</option>${[...others, ...(S.projects || []).filter((x) => used.includes(x.name))].map((x) => `<option value="${esc(x.name)}">${esc(x.title || x.name)}${used.includes(x.name) ? ' (다시 적용)' : ''}</option>`).join('')}</select><button class="btn small" style="flex:none" data-action="libApplyTo">적용</button></div>` : ''}
    </section>`;
  return `${header('문체 라이브러리', isNew ? '새 문체' : e.name || '이름 없음', isNew ? '원문을 붙여 넣고 분석하거나, 프로필을 직접 채운 뒤 저장하세요.' : `만든 날 ${fmtDate(e.created_at)} · 고친 날 ${fmtDate(e.updated_at)}`, right)}
    <div class="cols lib-cols">
      <div class="col lib-left">
        <section class="card lib-o1">
          ${input('이름', 'name', { root: 'lib', placeholder: '예: 건조한 1인칭 하드보일드' })}
          ${input('출처', 'source', { root: 'lib', hint: '작가, 작품 등 메모', placeholder: '예: 직접 쓴 단편 「등대」' })}
          ${input('메모', 'notes', { root: 'lib', rows: 2, placeholder: '어떤 작품에 어울리는지 등' })}
        </section>
        <section class="card lib-o2">
          <div class="between"><h2>원문</h2><span class="small"><span id="lib-sample-count">${(e.sample || '').length.toLocaleString()}</span>자 · 2,000자 이상 권장</span></div>
          ${input('분석할 소설 본문', 'sample', { root: 'lib', rows: 14, style: 'font-family:var(--serif);font-size:0.9375rem;line-height:1.9', hint: '이 컴퓨터의 라이브러리 폴더에만 저장돼요' })}
          <div><button class="btn dark" data-action="libAnalyze">문체 분석</button></div>
        </section>
        <section class="card tight"><h2>기준 지표</h2>${baselineRows(e.baseline)}</section>
        ${apply}
        ${isNew ? '' : versionsCard()}
      </div>
      <section class="card col wide lib-o3">
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

/** 글 속 이름으로 인물 찾기. 긴 이름부터 봐서 '서윤'이 '윤'보다 먼저 맞는다 */
/** 글 속 이름(또는 id)으로 인물 찾기. 먼저 나온 인물, 같은 자리면 긴 이름 (prompts.char_in_text 와 같은 규칙) */
function charInText(text) {
  if (!text) return null;
  let best = null;
  P().characters.forEach((c) => [c.name, c.id].forEach((k) => {
    const i = k ? text.indexOf(k) : -1;
    if (i >= 0 && (!best || i < best.i || (i === best.i && k.length > best.len))) best = { i, len: k.length, c };
  }));
  return best ? best.c : null;
}

/** 시점 글 속 서술 방식 (prompts.mode_in 과 같은 규칙) */
const modeIn = (t) => (t.includes('전지') ? '3인칭 전지' : t.includes('3인칭') ? '3인칭 제한' : t.includes('1인칭') ? '1인칭' : '');

/** n화를 누구 시점으로 쓰는지: 화에 정한 인물 → 구간 · 아크 시점 글 속 인물 → 작품 기본 시점 (주인공이면 역할이 주인공인 인물) */
function povChar(n) {
  const e = ep(n);
  if (e && e.plot.pov) return { c: P().characters.find((c) => c.id === e.plot.pov) || null, omni: false, from: '화' };
  if (e && e.plot.pov_mode) {  // 서술 방식만 적었으면 시점 인물은 물려받는다
    const omni = e.plot.pov_mode.includes('전지');
    return { c: omni ? null : inheritedPov(n).c, omni, from: '화' };
  }
  return inheritedPov(n);
}

/** 화에 적지 않았을 때의 시점: 구간 · 아크 시점 글 → 작품 기본 */
function inheritedPov(n) {
  const act = actOf(n);
  const arc = serial() ? arcOf(n) : null;
  const plan = ((act && act.pov) || (arc && arc.pov) || '').trim();
  if (plan) return { c: charInText(plan), omni: plan.includes('전지'), from: act && act.pov ? '구간' : '아크' };
  const base = P().style.narration_pov || '';
  if (base.includes('전지')) return { c: null, omni: true, from: '작품 기본' };
  const lead = base.includes('주인공') ? P().characters.find((c) => (c.role || '').includes('주인공')) : null;
  return { c: charInText(base) || lead || null, omni: false, from: '작품 기본' };
}

/** 성별은 설정 칸, 비었으면 역할 글(여주 · 남주)로 본다 */
function charGender(c) {
  const role = c.role || '';
  return c.gender || (role.includes('여주') ? '여' : role.includes('남주') ? '남' : '');
}

/** 화 카드 위 시점 배지. 여주인공 핑크, 남주인공 파랑, 그 밖의 인물은 보라, 전지 시점은 회색. 화에 직접 정하지 않고 물려받은 시점은 점선 */
function povBadge(n) {
  const v = povChar(n);
  if (!v.c && !v.omni) return '';
  const kind = v.c ? ((v.c.tier || 'main') === 'main' ? { 여: 'her', 남: 'him' }[charGender(v.c)] || 'other' : 'other') : 'omni';
  const label = v.c ? (v.c.name || v.c.id) : '전지';
  const e = ep(n);
  // 화에 정했으면 '도현 · 1인칭 시점 (이 화에 정함)', 물려받았으면 구간 · 아크 시점 글이 이름과 다를 때만 덧붙인다
  const plan = povText(n);
  const tip = v.from === '화' ? `${[label, e && e.plot.pov_mode].filter(Boolean).join(' · ')} 시점 (${povSource(v.from)})`
    : `${label} 시점 (${povSource(v.from)})${plan && plan !== label ? ' · ' + plan : ''}`;
  return `<span class="pov-chip ${kind}${v.from === '화' ? '' : ' inherit'}" title="${esc(tip)}">${esc(label)}</span>`;
}

/** 시점을 어디서 정했나: 화 · 구간 · 아크 · 작품 기본 */
const povSource = (from) => (from === '화' ? '이 화에 정함' : from === '작품 기본' ? '작품 기본 시점' : `${from}에서 물려받음`);

/** 화 카드 이름에 넣을 시점: '도현 시점(구간에서 물려받음)'. 배지가 없으면 빈 글 */
function povSummary(n) {
  const v = povChar(n);
  if (!v.c && !v.omni) return '';
  return `${v.c ? v.c.name || v.c.id : '전지'} 시점(${povSource(v.from)})`;
}

/** 플롯 보드 위 배지 범례 (색과 점선의 뜻) */
const POV_LEGEND = '<div class="small pov-legend">시점 배지: 실선은 이 화에 정함, 점선은 구간 · 아크 · 작품 기본에서 물려받음. 분홍 여주인공, 파랑 남주인공, 보라 그 밖의 인물, 회색 전지 시점</div>';

/** 인물 카드의 시점 서술 말투. 이 인물이 시점 인물인 화에만 본문 지시에 들어간다 (prompts.voice_line).
    값도 없고 이 인물 시점인 화도 없으면 접어 둔다 (단역 카드가 길어지지 않게) */
function voiceField(c, b) {
  const note = (S.voices || {})[c.id];
  const eps = P().episodes.map((e) => e.plot.number).filter((n) => (povChar(n).c || {}).id === c.id);
  const body = `${input('서술 말투 (이 인물 시점 화의 지문)', b + '.narration_voice', { rows: 3, autogrow: true, hint: `${c.name || '이 인물'} 시점 화의 지문 · 내면 독백`, placeholder: '예: 서술 어미는 ~했어요, ~인 걸까요? 처럼 부드럽게. 비우면 작품 문체 그대로' })}
    ${note ? `<div class="note info">${esc(note)}</div>` : ''}
    ${eps.length ? `<div class="small">이 말투가 들어가는 화: ${rangeText(eps)}화</div>`
      : (c.narration_voice || '').trim() ? `<div class="note warn">아직 ${esc(c.name || '이 인물')} 시점인 화가 없어서 이 말투는 어느 화에도 들어가지 않아요. <a href="${base()}/arc">플롯</a>에서 시점 인물을 정하세요.</div>` : ''}
    <div class="small">대사는 위의 말투(대사)를 따라요. 이 말투로 쓴 화는 어미 관련 문체 경고(과거형 비율, 문체 거리, 표지)를 빼요.</div>
    <div class="row" style="flex-wrap:nowrap"><input type="text" id="voice-req-${esc(c.id)}" aria-label="${esc(c.name || '이 인물')} 서술 말투 AI 요청" placeholder="AI에게 바랄 점 (예: 더 냉소적으로, 문장을 짧게)" style="flex:1">
      <button type="button" class="btn small" style="flex:none" data-action="voiceAI" data-arg="${esc(c.id)}">설정에서 AI로 초안</button></div>`;
  return eps.length || (c.narration_voice || '').trim() || note ? body
    : `<details class="voice-more"><summary>서술 말투 (이 인물 시점 화의 지문) <span class="small">이 인물 시점 화가 생기면 써요</span></summary><div style="display:flex;flex-direction:column;gap:10px;padding-top:8px">${body}</div></details>`;
}

/** 플롯 편집기의 시점 칸. 비우면 구간 · 아크 시점, 그것도 없으면 작품 기본 시점 */
function povField(e, locked) {
  const n = e.plot.number;
  const b = `episodes.${epIndex(n)}.plot`;
  const plan = (() => { const act = actOf(n); const arc = serial() ? arcOf(n) : null; return (act && act.pov) || (arc && arc.pov) || ''; })();
  const from = inheritedPov(n).from;  // 구간 · 아크 · 작품 기본 중 어디서 물려받나
  const fallback = plan ? `${from} 시점 (${plan})` : `작품 기본 (${P().style.narration_pov || '정하지 않음'})`;
  const opts = [['', fallback], ...P().characters.map((c) => [c.id, c.name || c.id])]
    .map(([v, l]) => `<option value="${esc(v)}"${(e.plot.pov || '') === v ? ' selected' : ''}>${esc(l)}</option>`).join('');
  return `<div class="grid-2">
      <div class="field"><label for="pov-ep-${n}">시점 인물 <span class="hint">이 화를 누구 눈으로</span></label>
        <select id="pov-ep-${n}" data-bind="${b}.pov" data-kind="text"${locked ? ' disabled' : ''}>${opts}</select></div>
      ${input('서술 방식', b + '.pov_mode', { readonly: locked, list: 'pov-modes', placeholder: `비우면 ${modeIn(plan) || P().style.narration_pov || '1인칭'}` })}
    </div><datalist id="pov-modes">${POV_MODES.map((m) => `<option value="${m}"></option>`).join('')}</datalist>`;
}

document.addEventListener('change', (e) => {  // 시점 인물을 바꾸면 화 카드 표시도 바로 바꾼다
  if (e.target.id && e.target.id.startsWith('pov-ep-')) render();
});

function epCard(e, sel) {
  return `<button type="button" class="ep-card ${e.status}${sel && sel.plot.number === e.plot.number ? ' sel' : ''}" data-action="selectEp" data-arg="${e.plot.number}" aria-label="${e.plot.number}화 ${esc(e.plot.title)}${povSummary(e.plot.number) ? ' · ' + esc(povSummary(e.plot.number)) : ''} 플롯 열기">
      <span class="ep-top"><strong>${e.plot.number}화</strong><span class="ep-chips">${povBadge(e.plot.number)}${e.realign ? `<span class="chip written" title="${esc(e.realign)}">다시 맞추기</span>` : ''}${jobOwns(e.plot.number) ? '<span class="chip ai"><span class="spinner sm" aria-hidden="true"></span>새로 만드는 중</span>' : ''}<span class="chip ${e.status}">${STATUS[e.status]}</span></span></span>
      <span class="t">${esc(e.plot.title) || '제목 없음'}</span>${lineBadge(e)}<span class="s">${esc(e.plot.summary)}</span></button>`;
}

/** 기승전결 네 칸 보드. 단편은 작품 전체 구조, 장편은 고른 아크의 구조를 그린다 */
function actBoard(acts, eps, sel) {
  const slot = (n) => `<div class="ep-slot" aria-hidden="true">${jobOwns(n) ? '<span class="spinner sm"></span> ' : ''}${n}화${jobOwns(n) ? ' 만드는 중' : ''}</div>`;
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
          <div class="between"><strong>${a.name}</strong><span class="act-meta">${a.start_ep}~${a.end_ep}화 · ${count}화</span></div>
          ${block('구간 목표', a.goal)}${block('전환점', a.key_turn)}${a.pov ? block('서술 시점', a.pov) : ''}
          <button type="button" class="btn small act-edit" data-action="selectAct" data-arg="${i}">구간 고치기</button>
        </div>
        <div class="act-eps"><span class="act-label">화별 플롯 ${inAct.length ? `${inAct.length}화` : ''}</span>
          ${share}${inAct.length ? inAct.map((e) => epCard(e, sel)).join('') : nums.map(slot).join('')}</div>
      </section>`;
  }).join('');
  // 구간 범위에 빈틈이 생기면 그 화 카드가 어느 열에도 들지 않는다. 사라지지 않게 따로 모아 보인다
  const loose = eps.filter((e) => owner(e.plot.number) < 0);
  const out = loose.length ? `<section class="act-col" aria-label="구간 밖"><div class="act-head"><div class="between"><strong>구간 밖</strong><span class="act-meta">${loose.length}화</span></div>
      <div class="note warn">어느 구간에도 들지 않는 화예요. 구간 범위를 고치면 제자리로 가요.</div></div>
      <div class="act-eps">${loose.map((e) => epCard(e, sel)).join('')}</div></section>` : '';
  return `${eps.some((e) => povBadge(e.plot.number)) ? POV_LEGEND : ''}<div class="board${out ? ' has-loose' : ''}">${cols}${out}</div>`;
}

/** 구간 범위가 start~end 화를 빈틈 · 겹침 없이 덮는지. 문제가 있으면 고칠 곳을 문장으로 돌려준다 (서버 validate_arc 가 저장을 막는 경우). */
function actCoverage(acts, start, end) {
  const out = [];
  const short = end - start + 1 < 4;  // 4화보다 짧으면 이웃 구간이 한 화를 함께 써도 된다
  const hits = new Map();
  acts.forEach((a) => { for (let n = a.start_ep; n <= a.end_ep && n - a.start_ep < 2000; n++) hits.set(n, (hits.get(n) || 0) + 1); });
  const gap = [];
  const twice = [];
  for (let n = start; n <= end; n++) {
    if (!hits.get(n)) gap.push(n);
    else if (hits.get(n) > 1 && !short) twice.push(n);
  }
  const beyond = [...hits.keys()].filter((n) => n < start || n > end);
  if (gap.length) out.push(`어느 구간에도 들지 않는 화: ${rangeText(gap)}화`);
  if (twice.length) out.push(`두 구간에 겹친 화: ${rangeText(twice)}화`);
  if (beyond.length) out.push(`범위(${start}~${end}화) 밖: ${rangeText(beyond.sort((a, b) => a - b))}화`);
  return out;
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
  if (S.arcProposal) {
    board = arcProposalCard();
  } else if (!p.arc.length) {
    // AI 없이도 시작할 수 있게 직접 나누기를 둔다. 설정이 비어 있으면 AI 구조가 막연해지니 먼저 알린다
    const thin = !p.meta.logline.trim() || !p.characters.length;
    board = `<div class="card empty"><p>아직 기승전결 구조가 없어요.</p>
      ${thin ? `<div class="note warn"><a href="${base()}/setup">설정 도우미</a>에서 로그라인과 인물을 먼저 채우면 AI가 더 맞는 구조를 만들어요.</div>` : ''}
      <div class="row">${((b) => `<button class="btn primary" data-action="planArc"${b.attr}>${b.label}</button>`)(jobBtn('arc', null, 'AI로 구조 만들기'))}<button class="btn" data-action="splitArc">직접 나누기</button></div>
      <span class="small">직접 나누면 ${p.meta.target_episodes}화를 기 · 승 · 전 · 결 네 구간으로 나눠요. 구간 목표는 구간 고치기에서 적어요. <strong>대화로 다듬기</strong>에서 말로 함께 짤 수도 있어요.</span></div>`;
  } else {
    const pj = jobFor('plots');
    const note = pj ? `<div class="note info">구간마다 초안을 만드는 중이에요${pj.note ? ` (${esc(pj.note)})` : ''}. 끝난 구간부터 카드가 채워지고, 채워진 화는 바로 고칠 수 있어요.</div>`
      : eps.length ? '' : '<div class="note info">구간을 확인한 뒤 <strong>화별 플롯 초안 만들기</strong>를 누르면 각 구간에 화 카드가 채워져요.</div>';
    board = `<div class="board-wrap">${note}${actBoard(p.arc, eps, sel)}</div>`;
  }

  let panel = '';
  if (sel) panel = plotEditor(sel);
  else if (S.selAct != null) panel = actEditor(S.selAct);
  const drawer = drawerHtml(panel);

  const drafts = eps.filter((e) => e.status === 'draft').length;
  const end = p.arc.length ? Math.max(...p.arc.map((a) => a.end_ep)) : 0;
  const right = p.arc.length
    ? `${((b) => `<button class="btn" data-action="planArc"${b.attr}>${b.label}</button>`)(jobBtn('arc', null, '구조 다시 제안'))}${needsDraft(1, end) || jobFor('plots') ? ((b) => `<button class="btn" data-action="draftPlots"${b.attr}>${b.label}</button>`)(jobBtn('plots', null, eps.length ? '초안 다시 만들기 (확정 화 제외)' : '화별 플롯 초안 만들기')) : ''}${drafts ? `<button class="btn primary" data-action="confirmAll"${jobFor('plots') ? ' aria-disabled="true" title="플롯 초안을 만드는 중이에요"' : ''}>초안 ${drafts}화 모두 확정</button>` : writeNextBtn()}`
    : '';
  // 장편으로 늘리기는 모든 화를 반영한 뒤에 쓸 수 있다 (작품 홈과 같은 이름)
  const fin = eps.length && eps.every((e) => e.status === 'finalized') && eps.length === p.meta.target_episodes;
  const tools = chatButton() + right + (fin ? `<a class="btn" href="${base()}/convert">장편으로 늘리기</a>` : '');
  return `${header('3단계', '기승전결 · 화별 플롯', '구간 목표를 확인하고, 화 카드를 눌러 플롯을 다듬은 뒤 확정하세요. 확정된 화만 본문을 쓸 수 있고, 초안을 다시 만들어도 확정된 화는 그대로예요.', tools)}
    ${p.arc.length && !S.arcProposal ? planNoteField('구조 다시 제안 · 초안 만들기') : ''}${board}${drawer}${chatPanel('plot')}`;
}

/** AI 로 구조 · 부 구성 · 플롯 초안을 다시 받을 때 함께 보낼 한 줄 요청. 비우면 AI 가 정한다 (prompts.request_block). */
function planNoteField(what) {
  return `<label class="plan-note"><span class="small">${what}에 함께 보낼 요청 (선택)</span>
    <input type="text" data-local="planNote" value="${esc(S.planNote || '')}" placeholder="예: 3화 안에 첫 반전, 로맨스 비중은 줄이기"></label>`;
}

/** start~end 화 중 플롯 초안 작업이 새로 만들 화가 있다 (없는 화나 초안). 없으면 서버도 '새로 만들 초안이 없어요'로 막는다 (web._plot_ranges). */
function needsDraft(start, end) {
  for (let n = start; n <= end; n++) if (!ep(n) || ep(n).status === 'draft') return true;
  return false;
}

/** 확정해 둔 다음 쓸 화가 있으면 그 화 쓰기 버튼. 모두 확정한 뒤 플롯 화면에서 바로 집필로 간다. 장편은 arc 안의 화일 때만. */
function writeNextBtn(arc) {
  const e = ep(currentEp());
  if (!e || e.status !== 'confirmed' || (arc && (e.plot.number < arc.start_ep || e.plot.number > arc.end_ep))) return '';
  return `<a class="btn primary${arc ? ' small' : ''}" data-write-next href="${base()}/write/${e.plot.number}">${e.plot.number}화 쓰기</a>`;
}

/** 구조 제안: 구간마다 지금 값과 바꿀 값을 나란히 보인다 (대화 변경안과 같은 비교, chat.js actsDiff). */
function arcProposalCard() {
  const has = P().arc.length > 0;
  const diff = has ? actsDiff({ acts: S.arcProposal, total_episodes: 0 }) : '';
  const rows = has ? (diff || '<div class="small">지금 구조와 같아요.</div>')
    : S.arcProposal.map((a) => `<div class="diff-act"><span class="chip ${actClass(a.name)}">${a.name}</span><div class="diff-row"><span class="act-label">범위</span><ins>${a.start_ep}~${a.end_ep}화</ins></div>${ACT_FIELDS.map(([k, l]) => diffField(l, k, '', a[k])).join('')}</div>`).join('');
  return `<section class="card proposal" aria-label="AI 구조 제안">
    <div class="between"><h2>AI 구조 제안 <span class="chip ai">적용 전</span></h2>${proposalActions(['dropArcProposal'], ['useArcProposal'], has ? '이 구조로 바꾸기' : '이 구조로 시작')}</div>
    <p class="small">${has ? '지우는 것은 빨강, 새로 넣는 것은 초록이에요. 바꿔도 저장하기 전에는 작품에 들어가지 않아요.' : '고르면 구조가 생기고, 저장하면 작품에 들어가요.'}</p>
    <div class="diff">${rows}</div></section>`;
}

function actEditor(i) {
  const k = serial() ? P().story_arcs.findIndex((x) => x.number === S.selArc) : -1;
  const a = k >= 0 ? P().story_arcs[k].acts[i] : P().arc[i];
  if (!a) return '';
  const b = k >= 0 ? `story_arcs.${k}.acts.${i}` : `arc.${i}`;
  const inAct = P().episodes.filter((e) => e.plot.number >= a.start_ep && e.plot.number <= a.end_ep);
  return `<div class="between"><h2>${k >= 0 ? `아크 ${S.selArc} · ` : ''}${a.name} 구간</h2><span class="chip ${actClass(a.name)}">${a.start_ep}~${a.end_ep}화</span></div>
    <div class="grid-2">${input('시작 화', b + '.start_ep', { type: 'number', min: 1 })}${input('끝 화', b + '.end_ep', { type: 'number', min: 1 })}</div>
    <div class="small">${k >= 0 ? '아크 안 기승전결 네 구간이 아크 첫 화부터 끝 화까지 빈틈없이 이어져야 저장돼요.' : '기승전결 네 구간이 1화부터 마지막 화까지 빈틈없이 이어져야 저장돼요.'}</div>
    ${((w) => (w.length ? `<div class="note warn" role="status">${w.map(esc).join('<br>')}</div>` : ''))(k >= 0
      ? actCoverage(P().story_arcs[k].acts, P().story_arcs[k].start_ep, P().story_arcs[k].end_ep)
      : actCoverage(P().arc, 1, P().meta.target_episodes))}
    ${input('구간 목표', b + '.goal', { rows: 5, autogrow: true, hint: '이 구간이 끝날 때 이야기가 어디까지 와 있어야 하나' })}
    ${input('전환점', b + '.key_turn', { rows: 4, autogrow: true, hint: '이 구간을 다음으로 넘기는 사건' })}
    ${input('서술 시점', b + '.pov', { placeholder: `비우면 작품 기본 (${P().style.narration_pov || '정하지 않음'})`, hint: `예: ${exName(1)} 1인칭. 화별 플롯을 만들 때 AI가 이 시점을 화마다 채워요` })}
    ${inAct.length ? `<div class="field"><span class="label">이 구간의 화</span><div class="row">${inAct.map((e) => `<button type="button" class="btn small" data-action="selectEp" data-arg="${e.plot.number}">${e.plot.number}화</button>`).join('')}</div></div>` : ''}`;
}

/** 회수할 복선 고르기: 열린 복선을 설명과 함께 체크로 보인다. id 를 손으로 치다 틀리면 회수가 말없이 끊긴다. */
function payoffPicker(label, path, locked) {
  const p = P();
  const cur = getPath(p, path) || [];
  const open = p.foreshadows.filter((f) => f.status === 'open');
  const extra = cur.filter((id) => !open.some((f) => f.id === id));
  const box = (id, text, on) => `<label class="check-row"><input type="checkbox" data-payoff="${esc(path)}" value="${esc(id)}"${on ? ' checked' : ''}${locked ? ' disabled' : ''}><span>${text}</span></label>`;
  const rows = [
    ...open.map((f) => box(f.id, `${esc(f.description)} <span class="small">${f.planted_ep}화에 심음${f.due_ep ? ` · ${f.due_ep}화 회수 예정` : ''}</span>`, cur.includes(f.id))),
    ...extra.map((id) => { const f = p.foreshadows.find((x) => x.id === id); return box(id, `${esc(f ? f.description : id)} <span class="small">${f ? '이미 회수함' : '없는 복선 id'}</span>`, true); }),
  ];
  return `<fieldset class="field"><legend class="label">${label}</legend>${rows.length ? `<div class="payoff-list">${rows.join('')}</div>` : '<div class="small">회수할 수 있는 열린 복선이 없어요. 복선은 상태 승인에서 심으면 생겨요.</div>'}</fieldset>`;
}

document.addEventListener('change', (e) => {
  const el = e.target;
  if (!el.dataset || !el.dataset.payoff) return;
  const list = getPath(P(), el.dataset.payoff) || [];
  setPath(P(), el.dataset.payoff, el.checked ? [...new Set([...list, el.value])] : list.filter((x) => x !== el.value));
  markDirty();
});

function plotEditor(e) {
  const n = e.plot.number;
  const i = epIndex(n);
  const b = `episodes.${i}.plot`;
  const busy = jobOwns(n);
  const autoBusy = autoEp() === n;
  const locked = e.status === 'written' || e.status === 'finalized' || busy || autoBusy;
  const ro = { readonly: locked };
  const act = actOf(n);
  const arc = serial() ? arcOf(n) : null;
  // 서랍을 닫지 않고 이웃 화로 옮겨 간다 (장편은 지금 아크 안에서)
  const nums = P().episodes.map((x) => x.plot.number).filter((x) => !arc || (x >= arc.start_ep && x <= arc.end_ep));
  const prev = nums.filter((x) => x < n).pop();
  const next = nums.find((x) => x > n);
  const navBtn = (to, label) => to ? `<button type="button" class="btn small" data-action="selectEp" data-arg="${to}" aria-label="${label} ${to}화 플롯">${label === '이전' ? `◀ ${to}화` : `${to}화 ▶`}</button>` : '';
  const pj = jobFor('plots');
  return `<div class="between"><h2>${n}화 플롯</h2><span class="row"><span class="drawer-nav">${navBtn(prev, '이전')}${navBtn(next, '다음')}</span><span class="chip ${e.status}">${STATUS[e.status]}</span></span></div>
    ${arc ? `<div class="note plain"><strong>아크 ${arc.number} ${esc(arc.title)}</strong> · ${esc(arc.goal)}</div>` : ''}
    ${act ? `<div class="note info"><strong>${act.name} 구간 목표</strong> · ${esc(act.goal)}</div>` : ''}
    ${busy ? `<div class="note warn">AI가 이 화의 초안을 새로 만드는 중이라 끝날 때까지 고칠 수 없어요${pj && pj.note ? ` (${esc(pj.note)})` : ''}. 먼저 끝난 구간의 화는 지금 고칠 수 있어요.</div>` : autoBusy ? `<div class="note warn">자동 집필이 ${n}화를 쓰는 중이라 고칠 수 없어요. 고치려면 <a href="${base()}/auto">자동 집필</a>을 일시정지하세요.</div>` : locked ? '<div class="note plain">본문이 있는 화라 플롯을 고칠 수 없어요.</div>' : ''}
    ${realignNote(e)}
    ${input('제목', b + '.title', ro)}
    ${input('요약', b + '.summary', { ...ro, rows: 3, autogrow: true })}
    ${input('사건 순서', b + '.events', { ...ro, kind: 'list', rows: 5, autogrow: true })}
    ${castField(e, locked)}
    ${placeCandNotes(e)}
    ${lineField(e)}
    ${povField(e, locked)}
    ${tlOn() || e.plot.time ? input('작품 속 시점', b + '.time', { ...ro, hint: '직전 화에서 얼마나 지났는지. 바로 이어지면 비워요', placeholder: '예: 다음 날 아침, 사흘 뒤 밤' }) : ''}
    ${n <= 3 || e.plot.opening ? input('여는 장면', b + '.opening', { ...ro, hint: n <= 3 ? '초반 화는 첫 장면이 독자를 붙잡아요' : '' }) : ''}
    ${input('감정 변화', b + '.emotional_shift', ro)}
    ${input('엔딩 훅', b + '.ending_hook', ro)}
    ${n <= 3 || e.plot.reader_question ? input('독자가 들고 갈 질문', b + '.reader_question', { ...ro, hint: n <= 3 ? '이 화를 읽고 다음 화를 누르게 하는 질문' : '' }) : ''}
    <div class="grid-2">${input('심을 복선', b + '.foreshadow_plant', { ...ro, kind: 'list', rows: 2 })}${payoffPicker('회수할 복선', b + '.foreshadow_payoff', locked)}</div>
    ${insertBlock(e)}
    ${fitNextField(e)}
    <div class="row drawer-actions">
      ${draftOneBtn(e)}
      ${e.status === 'draft' ? `<button class="btn primary" style="flex:1" data-action="confirmEp" data-arg="${n}"${busy ? ' disabled' : ''}>${n}화 확정</button>` : ''}
      ${e.status === 'confirmed' ? `<button class="btn" style="flex:1" data-action="unconfirmEp" data-arg="${n}">초안으로 되돌리기</button><a class="btn primary" style="flex:1" href="${base()}/write/${n}">${n}화 쓰기</a>` : ''}
      ${locked ? `<a class="btn" style="flex:1" href="${base()}/write/${n}">본문 보기</a>` : ''}
    </div>
    ${openingPlotBlock(e)}`;
}

// 등장 인물: 비중별로 묶고, AI 플롯이 데려온 새 인물 후보와 설정 없는 id 를 따로 보여 준다
const TIERS = [['main', '주역'], ['support', '조연'], ['minor', '단역']];

function castField(e, locked) {
  const n = e.plot.number;
  const cs = P().characters;
  // 이름이 비었거나 이 화에서 처음 나오는 조연 · 단역은 서랍에서 다시 열어 고친다 (접은 뒤에도)
  const reopen = (c) => !locked && c.id !== S.castEdit && (!c.name || (c.tier !== 'main' && c.first_ep === n))
    ? `<button type="button" class="btn small ghost" data-action="editCast" data-arg="${esc(c.id)}" aria-label="${esc(c.name || c.id)} 고치기">고치기</button>` : '';
  const box = (c) => `<label class="row" style="font-size:0.8125rem;gap:6px"><input type="checkbox" value="${esc(c.id)}" data-cast-ep="${n}"${e.plot.characters.includes(c.id) ? ' checked' : ''}${locked ? ' disabled' : ''}>${esc(c.name || `${c.id} (이름 없음)`)}</label>${reopen(c)}`;
  const groups = TIERS.map(([t, l]) => [l, cs.filter((c) => (c.tier || 'main') === t)]).filter(([, g]) => g.length);
  const boxes = groups.length > 1
    ? groups.map(([l, g]) => `<div class="row cast-boxes"><span class="small" style="min-width:32px">${l}</span>${g.map(box).join('')}</div>`).join('')
    : `<div class="row cast-boxes">${cs.map(box).join('')}</div>`;
  const cands = (P().cast_candidates || []).filter((c) => e.plot.characters.includes(c.id));
  const unknown = e.plot.characters.filter((id) => !cs.some((c) => c.id === id) && !cands.some((c) => c.id === id));
  const btns = (pairs) => locked ? '' : `<div class="row" style="margin-top:6px">${pairs.map(([a, l, cls]) => `<button type="button" class="btn small${cls ? ' ' + cls : ''}" data-action="${a}" data-arg="${esc(n + '|' + l[1])}">${l[0]}</button>`).join('')}</div>`;
  const candNotes = cands.map((c) => `<div class="note info"><strong>새 인물 제안 · ${esc(c.name || c.id)}</strong> <span class="small">${esc(c.role)} · ${c.tier === 'minor' ? '단역' : '조연'}</span>
    ${c.personality || c.goal ? `<br>${esc(c.personality || c.goal)}` : ''}${c.speech_style ? `<br><span class="small">말투: ${esc(c.speech_style)}</span>` : ''}
    <br><span class="small">AI 플롯이 데려온 인물이에요. 지금 등록하거나, 이 화를 확정하면 함께 등록돼요.</span>
    ${btns([['registerCast', ['인물로 등록', c.id], 'primary'], ['dropCast', ['이 화에서 빼기', c.id]]])}</div>`).join('');
  const unknownNotes = unknown.map((id) => `<div class="note warn"><strong>설정 없는 인물 · ${esc(id)}</strong><br><span class="small">플롯에 이름만 있고 인물 설정이 없어 본문을 쓸 때 이 인물 정보가 들어가지 않아요.</span>
    ${btns([['makeCast', ['인물로 만들기', id], 'primary'], ['dropCast', ['이 화에서 빼기', id]]])}</div>`).join('');
  const edit = cs.findIndex((c) => c.id === S.castEdit);
  return `<div class="field"><div class="between"><span class="label">등장 인물</span>${locked ? '' : `<button type="button" class="btn small" data-action="newCast" data-arg="${n}">+ 새 인물</button>`}</div>
    ${boxes}${candNotes}${unknownNotes}${edit >= 0 && !locked ? castQuickEdit(edit) : ''}</div>`;
}

// 플롯 편집기에서 바로 만드는 조연 · 단역. 나머지 칸은 설정 화면에서 채운다
function castQuickEdit(i) {
  const c = P().characters[i];
  const b = `characters.${i}`;
  return `<div class="note plain"><div class="between"><strong>${esc(c.name || '새 인물')}</strong><span class="row"><button type="button" class="btn small danger" data-action="dropNewCast" data-arg="${esc(c.id)}">이 인물 지우기</button><button type="button" class="btn small ghost" data-action="closeCastEdit">접기</button></span></div>
    <div class="grid-2">${input('이름', b + '.name')}${input('역할', b + '.role', { placeholder: '여관 주인, 동료 기사…' })}</div>
    ${nameIssuesFor(c.id)}
    <div class="row"><button type="button" class="btn small" data-action="nameCandidates" data-arg="${esc(c.id)}">이름 후보 뽑기</button><button type="button" class="btn small" data-action="nameAI" data-arg="${esc(c.id)}">AI 이름 추천</button></div>
    ${namePicks('c:' + c.id, 'useName', (x) => `${c.id}|${x}`)}
    <div class="grid-2">${tierSelect(c, b, 'cast-tier-' + i)}${input('성별', b + '.gender', { placeholder: '남 / 여' })}</div>
    ${input('성격 · 하는 일', b + '.personality', { rows: 2 })}
    ${input('말투', b + '.speech_style', { rows: 2, hint: '어미, 호칭, 대사 한 줄' })}
    <div class="small">${c.first_ep ? `${c.first_ep}화에 처음 나와요. ` : ''}나이, 원하는 것, 배경은 설정 화면에서 채울 수 있어요.</div></div>`;
}

function tierSelect(c, b, id) {
  return `<div class="field"><label for="${id}">비중 <span class="hint">주역은 매 화 설정 전체가 들어가고, 조연 · 단역은 나오는 화에만 들어가요${c.first_ep ? ` · ${c.first_ep}화에 처음 나옴` : ''}</span></label>
    <select id="${id}" data-bind="${b}.tier">${TIERS.map(([v, l]) => `<option value="${v}"${(c.tier || 'main') === v ? ' selected' : ''}>${l}</option>`).join('')}</select></div>`;
}

// 화를 확정하면 그 화에 나오는 새 인물 후보도 등록된다
function castAddedToast(before) {
  const added = P().characters.slice(before);
  if (added.length) toast(`새 인물도 등록했어요: ${added.map((c) => c.name || c.id).join(', ')}`);
}

function castFirstEp(id) {
  const eps = P().episodes.filter((e) => e.plot.characters.includes(id)).map((e) => e.plot.number);
  return eps.length ? Math.min(...eps) : 0;
}

function newCastId() {
  const ids = new Set([...P().characters, ...(P().cast_candidates || [])].map((c) => c.id));
  for (let k = P().characters.length + 1; ; k++) if (!ids.has('char' + k)) return 'char' + k;
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
    return `<button type="button" class="part-card${S.selPart === x.number ? ' sel' : ''}${here ? ' here' : ''}" data-action="selectPart" data-arg="${x.number}" aria-pressed="${S.selPart === x.number}">
      <span class="between"><strong>${x.number}부 ${esc(x.title)}</strong><span class="small">${x.start_ep}~${x.end_ep}화</span></span>
      <span class="s">${esc(x.goal)}</span>
      <span class="row">${here ? '<span class="chip confirmed">지금 쓰는 부</span>' : ''}<span class="chip">아크 ${inPart.length}개</span><span class="chip ${done ? 'finalized' : ''}">반영 ${done}/${x.end_ep - x.start_ep + 1}</span>${finished ? (x.summary ? '<span class="chip finalized">요약 있음</span>' : '<span class="chip written">요약 필요</span>') : ''}</span>
    </button>`;
  };
  const lost = S.seriesDraft ? lostPartSummaries() : [];
  const seriesDraft = S.seriesDraft ? `<div class="card proposal">
      <div class="between"><h3>AI 부 구성 제안 <span class="chip ai">적용 전</span></h3><div class="row"><button class="btn small" data-action="dropSeries">버리기</button><button class="btn small primary" data-action="applySeries">이 부 구성 적용</button></div></div>
      ${S.seriesDraft.parts.map((x, i) => `<div class="part-draft">
        <div class="grid-2">${input(`${x.number}부 제목`, `parts.${i}.title`, { root: 'seriesDraft' })}<div class="grid-2">${input('시작 화', `parts.${i}.start_ep`, { root: 'seriesDraft', type: 'number' })}${input('끝 화', `parts.${i}.end_ep`, { root: 'seriesDraft', type: 'number' })}</div></div>
        ${input('부 목표', `parts.${i}.goal`, { root: 'seriesDraft', rows: 2, autogrow: true })}
        ${input('전환점', `parts.${i}.key_turn`, { root: 'seriesDraft', rows: 2, autogrow: true, hint: '부를 마무리하는 큰 사건이나 드러나는 비밀' })}
        ${input('아크 후보', `parts.${i}.arc_ideas`, { root: 'seriesDraft', kind: 'list', rows: 3, autogrow: true })}
      </div>`).join('')}
      <div class="small">부는 1화부터 ${p.meta.target_episodes}화까지 빈틈없이 이어져야 반영돼요. 이미 기획한 아크가 새 부 경계를 넘으면 반영하지 않아요.</div>
      ${lost.length ? `<div class="note warn">이 구성으로 반영하면 범위가 바뀌어 저장된 ${lost.map((x) => `${x.number}부(${x.start_ep}~${x.end_ep}화)`).join(', ')} 요약이 사라져요. 지키려면 그 부의 시작 화와 끝 화를 지금과 같게 두세요.</div>` : ''}
    </div>` : '';
  const seriesBtn = ((b) => `<button class="btn small" data-action="planSeries"${b.attr}>${b.label}</button>`)(jobBtn('series', null, p.parts.length ? '부 구성 다시 제안' : 'AI로 부 구성 만들기'));
  const series = `<section class="card">
      <div class="between"><h2>부 구성 <span class="small" style="font-weight:400">총 ${p.meta.target_episodes}화 · ${planned}화까지 아크 기획</span></h2>${seriesBtn}</div>
      ${p.parts.length ? `<div class="part-strip">${p.parts.map(partCard).join('')}</div>` : '<div class="small">무대와 판이 바뀌는 큰 단위(50~150화)예요. 없어도 아크를 이어 갈 수 있지만, 있으면 아크 기획이 부 목표를 따라가요.</div>'}
      ${seriesDraft}
    </section>`;

  // 아크 목록. 요약이 있는 부의 아크는 부 요약이 대신 들어가 따로 요약할 필요가 없다 (pipeline.pending_recaps 와 같은 규칙)
  const inSummed = (a) => p.parts.some((x) => x.summary && x.start_ep <= a.start_ep && a.start_ep <= x.end_ep);
  const pending = arcs.filter((a) => !a.summary && arcFinished(a) && !inSummed(a));
  const partsPending = p.parts.filter((x) => !x.summary && arcFinished(x));
  const arcChip = (a) => {
    const g = arcProgress(a);
    const folded = g.done === g.nums && !a.summary && inSummed(a);
    const state = g.done === g.nums ? (a.summary || folded ? 'finalized' : 'written') : g.plotted === 0 ? '' : g.drafts ? 'draft' : 'confirmed';
    return `<button type="button" class="arc-chip${S.selArc === a.number ? ' sel' : ''}" data-action="selectArc" data-arg="${a.number}" aria-pressed="${S.selArc === a.number}">
      <strong>아크 ${a.number}</strong> <span>${a.start_ep}~${a.end_ep}화</span> <span class="chip ${state}">${g.done === g.nums ? (a.summary ? '완료' : folded ? '부 요약에 포함' : '요약 필요') : g.plotted ? `반영 ${g.done}/${g.nums}` : '플롯 전'}</span></button>`;
  };
  const rail = `<section class="card">
      <div class="between"><h2>아크</h2><span class="small">아크 하나는 5~30화짜리 작은 이야기예요. 다음 아크의 플롯만 그때그때 만들어요.</span></div>
      <div class="arc-rail">${railChips(arcs, arcChip)}${planned < p.meta.target_episodes ? `<button type="button" class="arc-chip next${S.selArc === 'next' ? ' sel' : ''}" data-action="selectArc" data-arg="next">+ 다음 아크 <span>${nextStart}화부터</span></button>` : ''}</div>
      ${pending.length ? `<div class="note warn between"><span>요약이 필요한 끝난 아크 ${pending.length}개 · 가장 오래된 <a href="#" data-action="selectArc" data-arg="${pending[0].number}" style="color:inherit;font-weight:700">아크 ${pending[0].number}</a>부터 받으세요. 요약이 있어야 오래된 줄거리를 짧게 접어 넣을 수 있어요.</span>${((b) => `<button class="btn small" data-action="recapArc" data-arg="${pending[0].number}"${b.attr}>${b.label}</button>`)(jobBtn('recap_arc', pending[0].number, `아크 ${pending[0].number} 요약 받기`))}</div>` : ''}
      ${partsPending.length ? `<div class="note warn between"><span>요약이 필요한 끝난 부 ${partsPending.length}개 · ${partsPending.map((x) => `<a href="#" data-action="selectPart" data-arg="${x.number}" style="color:inherit;font-weight:700">${x.number}부</a>`).join(', ')}. 부 요약은 그 부의 아크를 한 덩어리로 접어 프롬프트를 더 줄여요.${pending.some((a) => partsPending.some((x) => x.start_ep <= a.start_ep && a.start_ep <= x.end_ep)) ? ' 그 부의 아크 요약을 먼저 받으면 부 요약에 쓰여요.' : ''}</span>${((b) => `<button class="btn small" data-action="recapPart" data-arg="${partsPending[0].number}"${b.attr}>${b.label}</button>`)(jobBtn('recap_part', partsPending[0].number, `${partsPending[0].number}부 요약 받기`))}</div>` : ''}
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
  const note = planNoteField(arc && S.selArc !== 'next' ? '부 구성 제안 · 이 아크 초안 만들기' : '부 구성 제안');
  return `${header('3단계', '부 · 아크 · 화별 플롯', '장편은 작품을 부와 아크로 나누고, 다음 아크 하나씩 기획해 그 아크의 플롯만 만들어요. 끝난 아크는 요약으로 접혀서 몇백 화를 써도 프롬프트 크기가 일정해요.', tools)}
    ${note}${series}${rail}${body}${drawerHtml(panel)}${chatPanel('plot')}`;
}

function nextArcPanel(start) {
  const p = P();
  if (start > p.meta.target_episodes) return `<div class="card empty"><p>총 ${p.meta.target_episodes}화까지 아크가 모두 있어요.</p><span class="small">더 쓰려면 <a href="${base()}/setup">설정 도우미</a>에서 총 화수를 늘리세요. 마지막 부 끝 화가 따라 늘어나요.</span></div>`;
  const part = p.parts.find((x) => x.start_ep <= start && start <= x.end_ep);
  const old = p.foreshadows.filter((f) => f.status === 'open' && start - f.planted_ep > 50);
  const d = S.arcDraft;
  if (d) {
    const a = d.arc;
    return `<section class="card proposal">
      <div class="between"><h2>아크 ${a.number} 제안 <span class="chip ai">적용 전</span></h2><div class="row"><button class="btn small" data-action="dropArc">버리기</button><button class="btn small primary" data-action="applyArc">이 아크 적용</button></div></div>
      ${d.reply ? `<div class="note info">${esc(d.reply).replace(/\n/g, '<br>')}</div>` : ''}
      <div class="grid-2">${input('아크 제목', 'arc.title', { root: 'arcDraft' })}<div class="grid-2">${input('시작 화', 'arc.start_ep', { root: 'arcDraft', type: 'number', readonly: true })}${input('끝 화', 'arc.end_ep', { root: 'arcDraft', type: 'number' })}</div></div>
      ${input('아크 목표', 'arc.goal', { root: 'arcDraft', rows: 2, autogrow: true, hint: '아크가 끝날 때 바뀌어 있어야 하는 것' })}
      <div class="grid-2">${input('갈등', 'arc.conflict', { root: 'arcDraft', rows: 2, autogrow: true, hint: '주인공을 막는 문제나 상대' })}${input('보상 (사이다)', 'arc.payoff', { root: 'arcDraft', rows: 2, autogrow: true, hint: '클라이맥스에서 독자가 받는 것' })}</div>
      <div class="act-strip">${a.acts.map((x, i) => `<div class="act-head ${actClass(x.name)}"><div class="between"><strong>${x.name}</strong><span class="act-meta">${x.start_ep}~${x.end_ep}화</span></div>${input('구간 목표', `arc.acts.${i}.goal`, { root: 'arcDraft', rows: 3, autogrow: true })}</div>`).join('')}</div>
      ${input('서술 시점', 'arc.pov', { root: 'arcDraft', placeholder: `비우면 작품 기본 (${P().style.narration_pov || '정하지 않음'})` })}
      <div class="grid-2">${input('주요 인물 id', 'arc.cast', { root: 'arcDraft', kind: 'list', rows: 3 })}${input('회수할 복선 id', 'arc.payoffs', { root: 'arcDraft', kind: 'list', rows: 3 })}</div>
      ${d.new_characters.length ? `<div class="field"><span class="label">새 인물 (조연으로 들어와요. 주역으로 올리려면 설정 도우미에서 비중을 바꾸세요)</span>${d.new_characters.map((c) => `<div class="note plain"><strong>${esc(c.name)}</strong> <span class="small">${esc(c.id)} · ${esc(c.role)}</span><br>${esc(c.personality || c.goal)}<br><span class="small">말투: ${esc(c.speech_style)}</span></div>`).join('')}</div>` : ''}
      <div class="small">끝 화를 바꾸면 결 구간이 따라 늘거나 줄어요. 다른 구간 범위는 반영한 뒤 구간 고치기에서 바꿀 수 있어요.</div>
    </section>`;
  }
  const btn = jobBtn('nextarc', null, 'AI로 다음 아크 제안');
  return `<section class="card">
    <div class="between"><h2>다음 아크 기획 <span class="small" style="font-weight:400">${start}화부터${part ? ` · ${part.number}부 ${esc(part.title)} (${part.end_ep}화까지)` : ''}</span></h2></div>
    ${part ? `<div class="note plain"><strong>${part.number}부 목표</strong> · ${esc(part.goal)}${part.arc_ideas.length ? `<br><span class="small">아크 후보: ${part.arc_ideas.map(esc).join(' / ')}</span>` : ''}</div>` : ''}
    ${old.length ? `<div class="note warn">50화 넘게 열린 복선이 ${old.length}개 있어요. 이번 아크에서 회수하거나 다시 떠올리도록 AI에게 함께 보여 줘요.</div>` : ''}
    <div class="grid-2">${input('아크 길이 (화)', 'length', { root: 'arcForm', type: 'number', min: 0, zeroBlank: true, placeholder: 'AI가 정함', hint: '비우면 AI가 내용에 맞게 (보통 10~25화)' })}<div></div></div>
    ${input('이번 아크에 바라는 것 (선택)', 'note', { root: 'arcForm', rows: 3, autogrow: true, placeholder: '예: 학교 밖으로 무대를 넓히고, 라이벌과 처음 손잡게' })}
    <div class="row"><button class="btn primary" data-action="planNextArc"${btn.attr}>${btn.label}</button><span class="small">지금까지 실제로 쓴 줄거리(요약), 부 목표, 열린 복선을 보고 아크 하나를 제안해요. 적용 전에 고칠 수 있어요.</span></div>
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
  const rk = 'arc' + a.number;
  const r = S.recapDrafts[rk];
  let recap = '';
  if (finished) {
    const rb = jobBtn('recap_arc', a.number, a.summary ? 'AI로 요약 다시 제안' : 'AI로 요약 제안');
    recap = `<div class="recap">
      <div class="between"><h3>아크 요약 ${a.summary ? '<span class="chip finalized">있음</span>' : '<span class="chip written">필요</span>'}</h3><button class="btn small" data-action="recapArc" data-arg="${a.number}"${rb.attr}>${rb.label}</button></div>
      ${r ? `${input('AI 요약 제안 (고친 뒤 저장)', `${rk}.summary`, { root: 'recaps', rows: 6, autogrow: true })}<div class="row"><button class="btn small" data-action="dropRecap" data-arg="${rk}">버리기</button><button class="btn small primary" data-action="applyRecap" data-arg="${rk}">이 요약 저장</button></div>` : ''}
      ${input('저장된 요약', `story_arcs.${k}.summary`, { rows: 4, autogrow: true, hint: '앞으로 이 아크의 화별 요약 대신 프롬프트에 들어가요. 요약이 없으면 화마다 첫 문장만 들어가 앞 이야기가 흐려져요' })}
    </div>`;
  }
  const right = `<div class="row">
      <button class="btn small" data-action="editArc">아크 고치기</button>
      ${needsDraft(a.start_ep, a.end_ep) || jobFor('plots', a.number) ? `<button class="btn small" data-action="draftArcPlots" data-arg="${a.number}"${plotsBtn.attr}>${plotsBtn.label}</button>` : ''}
      ${g.drafts ? `<button class="btn small primary" data-action="confirmAll" data-arg="${a.number}"${jobFor('plots') ? ' aria-disabled="true" title="플롯 초안을 만드는 중이에요"' : ''}>초안 ${g.drafts}화 모두 확정</button>` : writeNextBtn(a)}
      ${last && !eps.some((e) => e.status !== 'draft') ? '<button class="btn small danger" data-action="removeLastArc">지우고 다시 기획</button>' : ''}
    </div>`;
  return `<section class="card">
      <div class="between"><h2>아크 ${a.number} ${esc(a.title)} <span class="small" style="font-weight:400">${a.start_ep}~${a.end_ep}화 · ${g.nums}화 · 반영 ${g.done}/${g.nums}</span></h2>${right}</div>
      <div class="arc-facts">
        <div><span class="act-label">아크 목표</span><p>${esc(a.goal) || '<span class="small">비어 있음</span>'}</p></div>
        <div><span class="act-label">갈등</span><p>${esc(a.conflict) || '<span class="small">비어 있음</span>'}</p></div>
        <div><span class="act-label">보상 (사이다)</span><p>${esc(a.payoff) || '<span class="small">비어 있음</span>'}</p></div>
      </div>
      <div class="small">${a.cast.length ? `주요 인물: ${names(a.cast)}` : ''}${a.payoffs.length ? ` · 회수할 복선: ${a.payoffs.map(esc).join(', ')}` : ''}</div>
      ${recap}
    </section>
    <div class="board-wrap">${((pj) => pj ? `<div class="note info">구간마다 초안을 만드는 중이에요${pj.note ? ` (${esc(pj.note)})` : ''}. 끝난 구간부터 카드가 채워지고, 채워진 화는 바로 고칠 수 있어요.</div>` : '')(jobFor('plots', a.number))}${g.plotted || jobFor('plots', a.number) ? '' : '<div class="note info">구간을 확인한 뒤 <strong>화별 플롯 초안 만들기</strong>를 누르면 이 아크의 화 카드가 채워져요.</div>'}${actBoard(a.acts, eps, sel)}</div>`;
}

function arcEditor(a) {
  const k = P().story_arcs.indexOf(a);
  const b = `story_arcs.${k}`;
  return `<div class="between"><h2>아크 ${a.number} 고치기</h2><span class="chip">${a.start_ep}~${a.end_ep}화</span></div>
    ${input('제목', b + '.title')}
    <div class="grid-2">${input('시작 화', b + '.start_ep', { type: 'number', readonly: true })}${input('끝 화', b + '.end_ep', { type: 'number', min: a.start_ep, readonly: k !== P().story_arcs.length - 1 })}</div>
    <div class="small">${k === P().story_arcs.length - 1 ? '끝 화를 바꾸면 구간도 따라 바뀌어요. 길이를 크게 바꾸려면 이 아크를 지우고 다시 기획하는 편이 쉬워요.' : '마지막 아크만 길이를 바꿀 수 있어요. 뒤 아크가 이 아크 다음 화부터 시작해요.'}</div>
    ${input('아크 목표', b + '.goal', { rows: 3, autogrow: true })}
    ${input('갈등', b + '.conflict', { rows: 2, autogrow: true })}
    ${input('보상 (사이다)', b + '.payoff', { rows: 2, autogrow: true })}
    ${input('서술 시점', b + '.pov', { placeholder: `비우면 작품 기본 (${P().style.narration_pov || '정하지 않음'})`, hint: '이 아크를 누구 시점으로 쓸지. 구간마다 다르면 구간 고치기에서' })}
    ${input('주요 인물 id', b + '.cast', { kind: 'list', rows: 3 })}
    ${payoffPicker('회수할 복선', b + '.payoffs', false)}`;
}

function partEditor(number) {
  const p = P();
  const i = p.parts.findIndex((x) => x.number === number);
  if (i < 0) return '';
  const x = p.parts[i];
  const b = `parts.${i}`;
  const done = p.episodes.filter((e) => e.status === 'finalized' && e.plot.number >= x.start_ep && e.plot.number <= x.end_ep).length;
  const finished = done === x.end_ep - x.start_ep + 1;
  const rk = 'part' + number;
  const r = S.recapDrafts[rk];
  const rb = jobBtn('recap_part', number, x.summary ? 'AI로 요약 다시 제안' : 'AI로 요약 제안');
  return `<div class="between"><h2>${x.number}부 고치기</h2><span class="chip">${x.start_ep}~${x.end_ep}화</span></div>
    ${input('제목', b + '.title')}
    <div class="grid-2">${input('시작 화', b + '.start_ep', { type: 'number' })}${input('끝 화', b + '.end_ep', { type: 'number' })}</div>
    <div class="small">부는 1화부터 마지막 화까지 빈틈없이 이어져야 저장돼요.</div>
    ${input('부 목표', b + '.goal', { rows: 3, autogrow: true })}
    ${input('전환점', b + '.key_turn', { rows: 2, autogrow: true })}
    ${input('아크 후보', b + '.arc_ideas', { kind: 'list', rows: 5, autogrow: true, hint: '다음 아크를 기획할 때 참고해요' })}
    ${finished ? `<div class="between"><span class="label">부 요약</span><button class="btn small" data-action="recapPart" data-arg="${number}"${rb.attr}>${rb.label}</button></div>
      ${r ? `${input('AI 요약 제안 (고친 뒤 저장)', `${rk}.summary`, { root: 'recaps', rows: 6, autogrow: true })}<div class="row"><button class="btn small" data-action="dropRecap" data-arg="${rk}">버리기</button><button class="btn small primary" data-action="applyRecap" data-arg="${rk}">이 요약 저장</button></div>` : ''}` : '<div class="small">부의 모든 화가 반영되면 요약을 만들 수 있어요.</div>'}
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

/** n화보다 앞인데 상태 반영이 끝나지 않은 화. 있으면 n화 본문을 저장하거나 반영할 수 없다 (서버 pipeline.require_previous). */
const blockedBefore = (n) => P().episodes.filter((x) => x.plot.number < n && x.status !== 'finalized').map((x) => x.plot.number);

function orderNote(blocked) {
  if (!blocked.length) return '';
  const first = ep(blocked[0]);
  return `<div class="note warn">이전 화(${blocked.join(', ')}화)의 상태 반영이 끝나야 쓸 수 있어요. 인물 상태가 꼬이지 않게 하는 규칙이에요. <a href="${base()}/${first.status === 'written' ? 'review' : 'write'}/${blocked[0]}">${blocked[0]}화 ${first.status === 'written' ? '상태 승인으로' : '집필로'}</a></div>`;
}

function viewWrite(n) {
  const e = ep(n);
  if (!e) return header('4단계', '집필', '') + noEpisode();
  const act = actOf(n);
  const blocked = blockedBefore(n);
  const editable = editableEp(e);  // 반영이 끝난 화도 고친다 (restate.js 가 반영 뒤 고침을 알린다)
  // 고칠 수 없는 화(플롯 초안)는 저장된 본문을 보인다. 그 화에 남은 초안이 있으면 따로 꺼내 보인다
  const draft = editable ? S.textDraft[n] : undefined;
  const orphan = !editable && textUnsaved(n);
  const text = draft ?? e.text;
  const isApi = S.mode === 'api';
  const writing = !!jobFor('write', n);
  const locked = writing && !e.text;  // AI가 본문을 처음 쓰는 중: 끝나면 칸이 AI 본문으로 바뀌므로 그동안 쓴 글은 남지 않는다

  let center;
  if (e.status === 'draft') {
    center = `<div class="empty"><p>${n}화 플롯이 아직 초안이에요. 확정해야 쓸 수 있어요.</p><a class="btn primary" href="${base()}/arc" data-action="gotoPlot" data-arg="${n}">${n}화 플롯 확정하러 가기</a></div>`;
  } else if (!e.text && draft === undefined) {
    center = `<div class="empty">
      ${autoLockNote() || orderNote(blocked)}
      ${isApi ? `<p>확정된 플롯과 지금까지의 데이터로 ${n}화를 써요.</p>${((b) => `<button class="btn primary" data-action="writeEp" data-arg="${n}"${blocked.length || autoOn() ? ' disabled' : b.attr}>${b.label}</button>`)(jobBtn('write', n, `${n}화 본문 생성`))}${jobFor('write', n) ? '<div class="small">다른 화면으로 옮겨 가도 계속 써요. 끝나면 알려 드려요.</div>' : ''}`
        : `<p>작업지시서를 채팅 앱에 붙여 넣고, 받은 본문을 가져오세요.</p><a class="btn primary" href="${base()}/brief/${n}">작업지시서 열기</a>`}
      <button class="btn" data-action="startManual" data-arg="${n}"${writing || blocked.length || autoOn() ? ' disabled' : ''}>직접 쓰기</button>
    </div>`;
  } else {
    center = `<div class="prose">${editable
      ? (locked ? `<div class="note info" id="draft-lock" style="margin:12px 16px 0">${n}화 본문을 만드는 중이에요. 끝나면 이 칸이 AI 본문으로 바뀌니 그때 고치세요.</div>` : '') + draftBox(n, text)
      : `<div class="read" data-read="${n}">${readHtml(n, text)}</div>`}</div>`;
  }

  const ctx = S.context ? `<details data-ctx-toggle${S.ctxOpen ? ' open' : ''}><summary>${S.context.length}개 블록 · 합계 ${S.context.reduce((s, c) => s + c.chars, 0).toLocaleString()}자</summary><ol class="panel-list">${S.context.map((c) => `<li><span>${esc(c.title)}</span><span class="small">${c.chars.toLocaleString()}자</span></li>`).join('')}</ol></details>
      <div class="small">이전 본문 전체 대신 이 데이터만 매번 같은 순서로 넣어요.</div>` : '<div class="small">플롯을 확정하면 보여요.</div>';

  // 생성 방식 토글은 설정의 본문 단계 백엔드 이름을 보인다 (설정을 아직 받지 않았으면 이름 없이)
  const wst = ((S.config || {}).stages || {}).write;
  const wname = wst ? ({ gemini: 'Gemini', local: '로컬', mock: 'mock' }[wst.provider] || wst.provider) : '';
  const right = `${e.status !== 'finalized' ? `<div class="seg" role="group" aria-label="생성 방식"><button type="button" aria-pressed="${isApi}" data-action="setMode" data-arg="api" title="${wst ? `본문 모델 ${esc(wst.model || '')} · 설정에서 바꿔요` : '설정에서 바꿔요'}">AI로 쓰기${wname ? ` · ${esc(wname)}` : ''}</button><button type="button" aria-pressed="${!isApi}" data-action="setMode" data-arg="brief">채팅 앱 작업지시서</button></div>` : ''}
    ${e.text && editable ? chatButton(`text:${n}`) : ''}
    ${e.text && editable && (isApi || e.status === 'finalized') ? `${((b) => `<button class="btn${S.rwOpen === n ? ' on' : ''}" data-action="rwOpen" data-arg="${n}" aria-expanded="${S.rwOpen === n}"${b.attr}>${b.label}</button>`)(jobBtn('write', n, '다시 생성'))}` : ''}
    ${editable && !isApi && e.status !== 'finalized' ? `<a class="btn" href="${base()}/brief/${n}">작업지시서</a>` : ''}
    ${e.status === 'written' ? `<a class="btn primary" href="${base()}/review/${n}">상태 승인으로</a>` : ''}`;

  return `<header class="page-head"><div class="row" style="gap:12px">${epNav('write', n)}<div class="lead" style="gap:2px"><div class="eyebrow">${act ? act.name + ' 구간 · ' : ''}${n} / ${P().meta.target_episodes}화</div><h1 style="font-size:1.5rem">${n}화 ${esc(e.plot.title)}</h1></div>${povBadge(n)}<span class="chip ${e.status}">${STATUS[e.status]}</span>${e.auto ? '<span class="chip ai">자동 반영</span>' : ''}</div><div class="row">${right}</div></header>
    ${e.auto ? `<div class="note info">이 화는 자동 집필이 검토 없이 반영했어요. 읽어 보고 문제가 있으면 <a href="${base()}/auto">자동 집필</a>에서 이 화부터 되돌릴 수 있어요.</div>` : ''}
    ${rebuildNote(n)}
    ${e.text ? restateNote(n) : ''}
    ${orphan ? `<div class="note warn">저장하지 않은 ${n}화 초고가 남아 있어요. 이 화는 상태 반영이 끝나 본문으로 저장할 수 없어서, 아래에는 반영된 본문을 보여요.
      <details><summary>남은 초고 보기 (${S.textDraft[n].length.toLocaleString()}자)</summary><textarea readonly id="orphan-${n}" aria-label="${n}화 남은 초고" style="width:100%;min-height:160px;margin-top:6px">${esc(S.textDraft[n])}</textarea></details>
      <div class="row" style="margin-top:6px"><button class="btn small" data-action="copyOrphan" data-arg="${n}">초고 복사</button><button class="btn small danger" data-action="dropOrphan" data-arg="${n}">초고 버리기</button></div></div>` : ''}
    ${editable && autoOn() ? `<div class="note warn">자동 집필이 도는 동안은 본문을 저장할 수 없어요. 쓰던 글은 이 화면에 남아 있어요. 저장하려면 <a href="${base()}/auto">자동 집필</a>을 일시정지하세요.</div>` : ''}
    ${e.text && editable ? rewritePanel(n) + candidateCard(n) : ''}
    <div class="cols write-cols" style="gap:16px">
      <aside class="card tight w-plot" style="flex:1 1 260px;min-width:0" aria-label="이번 화 플롯">
        <h3>이번 화 플롯</h3>
        ${act ? `<div class="note info"><strong>구간 목표</strong> · ${esc(act.goal)}</div>` : ''}
        <p style="font-size:0.8125rem;line-height:1.6;color:var(--text-2)">${esc(e.plot.summary)}</p>
        <div class="field"><span class="small">사건</span><ol style="padding-left:20px;display:flex;flex-direction:column;gap:6px;font-size:0.8125rem;line-height:1.5">${e.plot.events.map((x) => `<li>${esc(x)}</li>`).join('')}</ol></div>
        <div class="field"><span class="small">등장 인물</span><div style="font-size:0.8125rem">${e.plot.characters.map(charName).map(esc).join(', ')}</div></div>
        ${povText(n) ? `<div class="field"><span class="small">서술 시점</span><div style="font-size:0.8125rem">${esc(povText(n))}${povText(n) !== povText(n - 1) && n > 1 ? ' <span class="chip ai">시점 바뀜</span>' : ''}</div></div>` : ''}
        ${tlAside(n)}
        <div class="field"><span class="small">감정 변화</span><div style="font-size:0.8125rem">${esc(e.plot.emotional_shift)}</div></div>
        ${e.plot.opening ? `<div class="field"><span class="small">여는 장면</span><div style="font-size:0.8125rem">${esc(e.plot.opening)}</div></div>` : ''}
        <div class="field"><span class="small">엔딩 훅</span><div style="font-size:0.8125rem">${esc(e.plot.ending_hook)}</div></div>
        ${e.plot.reader_question ? `<div class="field"><span class="small">독자가 들고 갈 질문</span><div style="font-size:0.8125rem">${esc(e.plot.reader_question)}</div></div>` : ''}
        ${e.summary ? `<div class="field"><span class="small">승인된 요약</span><div style="font-size:0.8125rem;line-height:1.6">${esc(e.summary)}</div></div>` : ''}
        ${issuesBlock(e)}
        ${e.text && !autoOn() ? ((b) => `<button class="btn small" data-action="checkEp" data-arg="${n}"${b.attr}>${b.label}</button>`)(jobBtn('check', n, e.issues.length ? '다시 검수' : '검수하기')) : ''}
        ${deviceBadges(n)}
        <a href="${base()}/arc" data-action="gotoPlot" data-arg="${n}" style="font-size:0.8125rem">플롯 보기</a>
      </aside>
      <section class="card w-body" style="flex:3 1 520px;min-width:0;padding:0;gap:0" aria-label="본문">
        <div class="between" style="padding:10px 16px;border-bottom:1px solid var(--line);font-size:0.75rem;color:var(--muted)">
          <span>${e.status === 'draft' ? '플롯을 확정하면 본문을 쓸 수 있어요' : e.text ? '고칠 부분을 드래그하면 직접 고치거나 AI에게 맡기거나 삽화 프롬프트를 만들 수 있어요' : '본문을 직접 고친 뒤 저장할 수 있어요'}</span>
          ${e.status === 'draft' ? '' : `<span class="row">${(e.edits || []).length ? `<button type="button" class="btn small" data-action="openEdits" title="수정 기록을 펼쳐요">수정 기록 ${e.edits.length}</button>` : ''}<span><strong id="char-count" style="color:var(--text)">${(text || '').length.toLocaleString()}</strong> / ${Number(P().meta.words_per_episode).toLocaleString()}자</span>
          ${text ? `<button class="btn small" data-action="copyEp" data-arg="${n}" title="고른 줄바꿈 형식으로 복사 (오른쪽 '복사 · 내보내기'에서 바꿈)">복사</button>` : ''}
          ${editable && (e.text || draft !== undefined) ? `<button class="btn small${textUnsaved(n) && !autoOn() ? ' primary' : ''}" id="save-text" data-action="saveText" data-arg="${n}"${draft === undefined || autoOn() ? ` disabled title="${autoOn() ? '자동 집필이 도는 동안은 저장할 수 없어요' : '고친 내용이 없어요'}"` : ''}>본문 저장</button>` : ''}</span>`}
        </div>
        ${e.text ? passageNotes(n) ? `<div style="padding:12px 16px 0;display:flex;flex-direction:column;gap:8px">${passageNotes(n)}</div>` : '' : ''}
        ${center}
      </section>
      <aside class="card tight w-side" style="flex:1 1 260px;min-width:0" aria-label="복사 · 내보내기와 AI에게 보내는 컨텍스트">
        ${exportCard(n)}
        <h3>AI에게 보내는 컨텍스트</h3>
        ${ctx}
        ${S.context ? `<button class="btn small" data-action="togglePrompt" data-arg="${n}">${S.promptText ? '프롬프트 닫기' : '프롬프트 원문 보기'}</button>` : ''}
        ${S.promptText ? `<pre class="brief mono" style="max-height:420px">${esc(S.promptText)}</pre>` : ''}
      </aside>
    </div>
    ${editHistory(e)}
    ${versionsPanel(e)}
    ${e.text ? illustPanel(n) : ''}
    ${openingPanel(n)}
    ${e.text && editable ? chatPanel(`text:${n}`) : ''}`;
}

// ----- 5. 상태 승인 -----

function viewReview(n) {
  const e = ep(n);
  if (!e) return header('5단계', '상태 승인', '') + noEpisode();
  const top = (desc, right = '') => `<header class="page-head"><div class="row" style="gap:12px">${epNav('review', n)}<div class="lead" style="gap:2px"><div class="eyebrow">${n}화 ${esc(e.plot.title)}</div><h1 style="font-size:1.5rem">상태 승인</h1></div><span class="chip ${e.status}">${STATUS[e.status]}</span></div><div class="row">${right}</div></header>${autoLockNote()}${desc ? `<p class="desc">${desc}</p>` : ''}`;

  if (e.status === 'finalized') {
    const h = [...P().history].reverse().find((d) => d.episode === n);
    const canRevert = P().snapshots.some((s) => s.episode === n - 1);
    return top('이 화는 상태 반영이 끝났어요. 반영된 내용이에요.', canRevert ? `<button class="btn" data-action="revertFrom" data-arg="${n}">${n}화부터 반영 취소</button>` : '') + restateCard(n) + (h ? historyView(h) : '<div class="note plain">반영 기록이 없어요.</div>');
  }
  if (e.status !== 'written') {
    return top('') + `<div class="card empty"><p>${n}화 본문이 아직 없어요. 본문을 쓴 뒤 상태를 정리해요.</p><a class="btn primary" href="${base()}/write/${n}">${n}화 집필로</a></div>`;
  }
  const d = S.deltas[n];
  const ar = S.auto && S.auto.run;
  if (!d && ar && ar.status === 'review' && ar.ep === n && ar.pending) {
    // 자동 집필이 이미 만든 변경안이 있다. 다시 만들면 AI 비용이 또 든다
    return top('자동 집필이 이 화에서 멈추고 만든 변경안이 있어요. 불러와 고른 항목만 반영한 뒤 자동 집필에서 이어 가세요.') +
      `<div class="card"><div class="row"><button class="btn primary" data-action="autoOpenReview">자동 집필 변경안 불러오기</button><a class="btn" href="${base()}/auto">자동 집필로</a></div></div>`;
  }
  if (!d) {
    return top('AI가 본문에서 인물 상태, 관계, 확정 사실, 복선을 뽑아 변경안을 만들어요. 승인한 항목만 데이터에 반영돼요.') +
      `${ep(n + 1) ? `<div class="note info">${n}화 상태를 반영해야 ${n + 1}화를 쓸 수 있어요.</div>` : ''}<div class="cols"><section class="card col"><h2>AI로 만들기</h2><p class="desc">${n}화 본문을 읽고 변경안을 만들어요.${S.config && S.config.stages ? ` <span class="small">모델: ${esc(S.config.stages.state.model)}</span>` : ''}</p><div>${((b) => `<button class="btn primary" data-action="extractState" data-arg="${n}"${b.attr}>${b.label}</button>`)(jobBtn('state', n, '변경안 만들기'))}</div></section>
       <section class="card col"><h2>채팅 앱에서 받은 JSON</h2><p class="desc">상태 승인 지시서를 채팅 앱에 붙여 넣고 받은 JSON을 가져와요.</p><div><a class="btn" href="${base()}/brief/${n}" data-action="openStateBrief" data-arg="${n}">상태 승인 지시서 열기</a></div></section></div>`;
  }

  const p = P();
  const remake = ((b) => `<button class="btn small" data-action="extractState" data-arg="${n}"${b.attr}>${b.label}</button>`)(jobBtn('state', n, '변경안 다시 만들기'));
  const stale = textUnsaved(n)
    ? `<section class="note warn">${n}화 본문에 저장하지 않은 수정이 있어요. 반영해도 그 수정은 저장되지 않아요. 변경안을 다시 만들면 본문을 먼저 저장해요. ${remake} <a href="${base()}/write/${n}">본문으로</a></section>`
    : S.deltaBase[n] !== undefined && S.deltaBase[n] !== e.text
      ? `<section class="note warn">이 변경안을 만든 뒤 본문을 고쳤어요. 고친 내용이 상태에 영향을 준다면 변경안을 다시 만드세요. ${remake}</section>` : '';
  // 검수 지적이 남아 있으면 반영 전에 본문을 고칠지 볼 수 있게 알린다 (검수 뒤 본문을 고쳤으면 지난 결과라고 밝힌다)
  const issues = (e.issues || []).length
    ? `<section class="note warn">검수 지적 ${e.issues.length}건이 남아 있어요${(e.edits || []).some((x) => x.at > (e.checked_at || '')) ? ' (검수 뒤 본문을 고쳤어요)' : ''}. <a href="${base()}/write/${n}">집필 화면에서 보기</a></section>` : '';
  const total = d.character_updates.length + d.events.length + d.secrets_added.length + d.relationship_updates.length + d.new_facts.length + d.foreshadow_planted.length + d.foreshadow_resolved.length + (d.new_characters || []).length + (d.new_places || []).length + (d.foreshadow_clues || []).length + (d.deadlines_added || []).length + (d.deadlines_done || []).length + (d.setting_changes || []).length;
  if (!S.preview || S.preview.n !== n) refreshPreview(n);
  const picked = deltaPicked();
  const box = (key) => `<input type="checkbox" id="pk-${key}" data-pick="${key}"${S.picks[key] ? ' checked' : ''}>`;
  const diff = (before, after) => before && before !== after
    ? `<div class="row"><span class="before">${esc(before)}</span><span class="small">→</span><span class="after">${esc(after)}</span></div>`
    : `<div class="row"><span class="after">${esc(after)}</span></div>`;

  const chars = d.character_updates.map((u, i) => {
    const cur = p.states.find((s) => s.character_id === u.character_id) || {};
    const rows = [['감정', 'emotional_state'], ['목표', 'current_goal'], ['위치', 'location'], ['메모', 'notes']]
      .filter(([, f]) => u[f]).map(([k, f]) => `<div class="small">${k}</div>${diff(cur[f], u[f])}`).join('');
    const knows = u.knows.filter((k) => !(cur.knows || []).includes(k)).map((k) => `<span class="after">+ ${esc(k)}</span>`).join(' ');
    // 지금 차림은 AI 가 틀리게 적었으면 여기서 고쳐 반영한다 (data-attire 입력이 변경안을 바로 고친다)
    const attire = u.attire ? `<div class="small"><label for="at-${i}">차림</label></div>${cur.attire && cur.attire !== u.attire ? `<div class="row"><span class="before">${esc(cur.attire)}</span><span class="small">→</span></div>` : ''}<input id="at-${i}" data-attire="${i}" data-attire-ep="${n}" value="${esc(u.attire)}">` : '';
    const unknown = !p.characters.some((c) => c.id === u.character_id) && !(d.new_characters || []).some((c) => c.id === u.character_id);
    return `<div class="change">${box('c' + i)}<div class="body"><label for="pk-c${i}" style="font-size:0.875rem;font-weight:700">${esc(charName(u.character_id))}${unknown ? ' <span class="chip draft">설정에 없는 인물</span>' : ''}</label>${rows}${attire}${swDeltaRows(u, cur)}${knows ? `<div class="small">알게 된 정보</div><div class="row">${knows}</div>` : ''}</div></div>`;
  }).join('');

  const events = d.events.map((ev, i) => {
    const good = GOOD_EVENTS.includes(ev.kind);
    const wit = ev.witnesses.length ? ` · 목격: ${ev.witnesses.map(charName).map(esc).join(', ')}` : '';
    const sec = ev.reveals_secret ? ` · 드러난 비밀: ${esc(secretLabel(ev.reveals_secret, d))}` : '';
    return `<div class="change">${box('e' + i)}<div class="body"><label for="pk-e${i}" style="font-size:0.875rem;font-weight:700">${esc(charName(ev.actor))} → ${esc(charName(ev.target))}
        <span class="chip" style="background:${good ? 'var(--green-soft)' : 'var(--red-soft)'};color:${good ? 'var(--green)' : 'var(--red)'}">${esc(ev.kind)}</span> <span class="small" style="font-weight:400">${INTENSITY[ev.intensity] || ev.intensity}${wit}${sec}</span></label>
      ${ev.quote ? `<div style="font-family:var(--serif);font-size:0.8125rem;line-height:1.7;color:var(--text-2)">“${esc(ev.quote)}”</div>` : ''}</div></div>`;
  }).join('');
  const newChars = (d.new_characters || []).map((c, i) => `<div class="change">${box('n' + i)}<label for="pk-n${i}" style="font-size:0.8125rem;line-height:1.55"><strong>${esc(c.name)}</strong> <span class="small">${esc(c.id)} · ${esc(c.role)} · ${c.tier === 'minor' ? '단역' : '조연'}으로 추가</span><br>${esc(c.personality || c.appearance || c.goal)}${c.speech_style ? `<br><span class="small">말투: ${esc(c.speech_style)}</span>` : ''}</label></div>`).join('');
  const newPlaces = (d.new_places || []).map((x, i) => `<div class="change">${box('l' + i)}<label for="pk-l${i}" style="font-size:0.8125rem;line-height:1.55">${placeLabel(x)}</label></div>`).join('');
  const secrets = d.secrets_added.map((x, i) => `<div class="change">${box('s' + i)}<label for="pk-s${i}" style="font-size:0.8125rem;line-height:1.55"><strong>${esc(charName(x.owner))}</strong> ${esc(x.content)}<br><span class="small">모르는 인물: ${x.hidden_from.map(charName).map(esc).join(', ') || '없음'}</span></label></div>`).join('');
  const rels = d.relationship_updates.map((r, i) => {
    const cur = p.relationships.find((x) => (x.a === r.a && x.b === r.b) || (x.a === r.b && x.b === r.a));
    return `<div class="change">${box('r' + i)}<div class="body"><label for="pk-r${i}" style="font-size:0.875rem;font-weight:700">${esc(charName(r.a))} ↔ ${esc(charName(r.b))}</label>
      ${diff(cur && cur.type, r.type)}${r.description ? diff(cur && cur.description, r.description) : ''}</div></div>`;
  }).join('');

  const facts = d.new_facts.map((f, i) => `<div class="change">${box('f' + i)}<label for="pk-f${i}" style="font-size:0.8125rem;line-height:1.55">${esc(f)}</label></div>`).join('');
  const fs = [
    ...d.foreshadow_planted.map((f, i) => `<div class="change">${box('p' + i)}<label for="pk-p${i}" style="font-size:0.8125rem;line-height:1.55"><span class="chip confirmed">심음</span> ${esc(f.description)} <span class="small">${esc(f.id)}</span></label></div>`),
    ...d.foreshadow_resolved.map((id, i) => {
      const f = p.foreshadows.find((x) => x.id === id);
      return `<div class="change">${box('x' + i)}<label for="pk-x${i}" style="font-size:0.8125rem;line-height:1.55"><span class="chip finalized">회수</span> ${esc(f ? f.description : id)} ${f ? `<span class="small">${f.planted_ep}화에 심음</span>` : '<span class="small">알 수 없는 id</span>'}</label></div>`;
    }),
    fsClueRows(d, box),
  ].join('');
  const section = (title, body) => `<section class="card"><h2>${title}</h2>${body || '<div class="small">변경 없음</div>'}</section>`;

  return top(`${(S.deltaOrig[n] || {}).source === 'chat' ? '채팅 앱에서 가져온' : 'AI가 본문에서 뽑은'} 변경안이에요. 체크한 항목만 데이터에 반영되고, 반영해야 다음 화를 쓸 수 있어요.`, `<span class="small">${total}건 중 <strong class="pick-count" style="color:var(--text)">${picked}</strong>건 선택</span>`) + stale + issues +
    (d.warnings.length ? `<section class="note warn"><strong>경고 ${d.warnings.length}건 · 본문을 고칠지 확인하세요</strong><ul style="padding-left:18px;margin-top:6px">${d.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul><a href="${base()}/write/${n}" style="color:inherit;font-weight:700">본문으로</a></section>` : '') +
    section('인물 상태', chars) + scDeltaCard(n, d, box) +
    (newChars ? section('새로 나온 인물', newChars) : '') +
    (newPlaces ? section('새로 나온 장소', `<div class="small">반영하면 인과율에 장소로 등록돼요. 그 뒤로는 이 장소가 나오는 화를 쓸 때 설명이 함께 들어가요.</div>${newPlaces}`) : '') +
    `<div class="cols">
      <section class="card col"><div class="between"><h2>관계 사건</h2><span class="small">AI는 사건만 적고, 관계 수치는 Canon 이 계산해요</span></div>${events || '<div class="small">이번 화에 관계 사건이 없어요</div>'}
        ${secrets ? `<h3 style="margin-top:6px">새로 생긴 비밀</h3>${secrets}` : ''}
        ${rels ? `<h3 style="margin-top:6px">관계 유형 · 설명 변경</h3>${rels}` : ''}</section>
      <section class="card col">${relationHeader('반영하면 이렇게 계산돼요')}<div id="rel-preview">${relationLines(S.preview && S.preview.n === n ? S.preview : null)}</div>
        <div class="small">체크를 바꾸면 바로 다시 계산해요. 저장은 반영할 때만 돼요.</div></section>
    </div>` +
    `<div class="grid-auto">${section('확정 사실', facts)}${section('복선', fs)}</div>` + tlDeltaCard(n, d, box) +
    `<section class="card"><div class="between"><label for="dsum" style="font-size:1rem;font-weight:700">${n}화 요약</label><span class="small"><span id="dsum-count">${d.summary.length.toLocaleString()}</span>자 · 다음 화 생성에 이 요약이 들어가요</span></div>
      <textarea id="dsum" rows="4" data-autogrow data-delta-summary="${n}">${esc(d.summary)}</textarea></section>
    <div class="row">${((b) => `<button class="btn" data-action="extractState" data-arg="${n}"${b.attr}>${b.label}</button>`)(jobBtn('state', n, '변경안 다시 만들기'))}<button class="btn" data-action="dropDelta" data-arg="${n}">버리기</button><a class="btn" href="${base()}/write/${n}">본문으로</a></div>
    <div class="apply-bar"><span class="small">${total}건 중 <strong class="pick-count" style="color:var(--text)">${picked}</strong>건 선택</span>
      <button class="btn primary" data-action="applyDelta" data-arg="${n}"${autoOn() ? ' disabled' : ''}>선택한 항목 반영하고 ${n}화 완료</button></div>`;
}

function historyView(h) {
  const li = (arr) => arr.length ? `<ul style="padding-left:18px;display:flex;flex-direction:column;gap:6px;font-size:0.8125rem;line-height:1.5">${arr.map((x) => `<li>${x}</li>`).join('')}</ul>` : '<div class="small">없음</div>';
  return `<section class="card"><h2>요약</h2><p style="font-size:0.875rem;line-height:1.7">${esc(h.summary)}</p></section>
    <div class="grid-auto">
      <section class="card"><h2>인물 상태</h2>${li(h.character_updates.map((u) => `<strong>${esc(charName(u.character_id))}</strong> ${esc([u.emotional_state, u.current_goal, u.location].filter(Boolean).join(' / '))}${u.attire ? ` · 차림: ${esc(u.attire)}` : ''}${u.knows.length ? ` · 앎: ${esc(u.knows.join(', '))}` : ''}`))}</section>
      <section class="card"><h2>관계 사건</h2>${li((h.events || []).map((ev) => `${esc(charName(ev.actor))} → ${esc(charName(ev.target))} · ${esc(ev.kind)} ${INTENSITY[ev.intensity] || ''}${ev.witnesses && ev.witnesses.length ? ` · 목격: ${ev.witnesses.map(charName).map(esc).join(', ')}` : ''}${ev.reveals_secret ? ` · 드러난 비밀: ${esc(secretLabel(ev.reveals_secret, h))}` : ''}${ev.quote ? `<br><span class="small">“${esc(ev.quote)}”</span>` : ''}`))}</section>
      <section class="card"><h2>사실과 복선</h2>${li([...h.new_facts.map(esc), ...h.foreshadow_planted.map((f) => '심음: ' + esc(f.description)), ...h.foreshadow_resolved.map((id) => { const f = P().foreshadows.find((x) => x.id === id); return '회수: ' + esc(f ? f.description : id); })])}</section>
      ${(h.new_characters || []).length ? `<section class="card"><h2>새로 나온 인물</h2>${li(h.new_characters.map((c) => `<strong>${esc(c.name || c.id)}</strong> <span class="small">${esc(c.role || '')}</span>`))}</section>` : ''}
      ${(h.new_places || []).length ? `<section class="card"><h2>새로 나온 장소</h2>${li(h.new_places.map(placeLabel))}</section>` : ''}
      ${tlHistory(h)}${scHistory(h)}
      ${(h.secrets_added || []).length ? `<section class="card"><h2>새로 생긴 비밀</h2>${li(h.secrets_added.map((x) => `<strong>${esc(charName(x.owner))}</strong> ${esc(x.content)}`))}</section>` : ''}
      ${(h.relationship_updates || []).length ? `<section class="card"><h2>관계 유형 · 설명 변경</h2>${li(h.relationship_updates.map((r) => `${esc(charName(r.a))} ↔ ${esc(charName(r.b))} · ${esc(r.type)}${r.description ? ` · ${esc(r.description)}` : ''}`))}</section>` : ''}
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
  const key = P().settings.show_numbers ? 'numbers' : 'words';
  const text = rel[key];
  if (!text) return '<div class="small">관계가 없어요. 설정 도우미에서 관계를 추가하세요.</div>';
  if (!rel.before) return `<ul class="rel-lines">${text.split('\n').map((l) => `<li>${esc(l)}</li>`).join('')}</ul>`;
  // 미리보기: 줄마다 지금 값과 비교한다. 줄 앞 '도현 → 서윤' 같은 쌍으로 맞춘다
  const pair = (l) => l.split(':')[0].split(' (')[0].split(' 서로')[0].trim();
  const now = new Map((rel.before[key] || '').split('\n').filter(Boolean).map((l) => [pair(l), l]));
  const lines = text.split('\n').filter(Boolean);
  const changed = lines.filter((l) => now.get(pair(l)) !== l).length;
  return `<div class="small">${changed ? `반영하면 ${changed}줄이 바뀌어요. 바뀌는 줄 아래에 지금 값을 함께 보여요.` : '반영해도 관계는 그대로예요.'}</div>
    <ul class="rel-lines">${lines.map((l) => {
    const was = now.get(pair(l));
    return was === l ? `<li class="same">${esc(l)}</li>` : `<li class="changed"><ins>${esc(l)}</ins>${was ? `<div class="small">지금: ${esc(was)}</div>` : '<div class="small">새 관계</div>'}</li>`;
  }).join('')}</ul>`;
}

// ----- 6. 작업지시서 -----

// 화마다 고른 지시서 탭 ('작품:화' → 'episode' | 'state'). 고른 적 없는 화는 상태로 정한다: 본문이 있으면 상태 승인 지시서
const BRIEF_TABS = {};
const briefTabFor = (n) => BRIEF_TABS[`${S.name}:${n}`] || (ep(n).status === 'written' ? 'state' : 'episode');
let briefImportError = null;  // 받은 JSON 가져오기에서 서버가 거절한 이유 { key: '작품:화', msg }

/** 붙여 넣은 본문 글자 수와 목표 분량. 목표의 70%보다 짧으면 채팅 앱 답이 잘렸는지 보라고 한다. */
function importCount(v) {
  const len = v.trim().length;
  const goal = Number(P().meta.words_per_episode) || 0;
  const short = len && goal && len < goal * 0.7;
  return `<strong>${len.toLocaleString()}</strong> / ${goal.toLocaleString()}자${short ? ' <span class="chip written">목표보다 많이 짧아요. 본문이 잘렸는지 확인하세요</span>' : ''}`;
}

function viewBrief(n) {
  const e = ep(n);
  if (!e) return header('작품 도구', '채팅 앱 작업지시서', '') + noEpisode();
  const body = S.briefTab === 'episode';
  const stateBlocked = !body && !e.text;
  // 앞 화 반영이 끝나지 않았으면 받은 본문 저장(처음 쓰는 화)과 변경안 반영을 서버가 막는다. 붙여 넣은 글은 칸에 남는다
  const order = (body ? e.status === 'confirmed' : e.status === 'written') ? blockedBefore(n) : [];
  return `<header class="page-head"><div class="row" style="gap:12px">${epNav('brief', n)}<div class="lead" style="gap:2px"><div class="eyebrow">${n}화 ${esc(e.plot.title)} · API 없이 쓰기</div><h1 style="font-size:1.5rem">채팅 앱 작업지시서</h1></div><span class="chip ${e.status}">${STATUS[e.status]}</span></div></header>
    <p class="desc">Claude, Gemini, ChatGPT 구독 앱에 붙여 넣을 지시서예요. API 생성과 똑같은 컨텍스트를 써요.</p>
    <div class="tabs" role="tablist" aria-label="지시서 종류">
      <button type="button" role="tab" aria-selected="${body}" aria-controls="brief-panel" data-action="setBriefTab" data-arg="episode">1 본문 작성 지시서</button>
      <button type="button" role="tab" aria-selected="${!body}" aria-controls="brief-panel" data-action="setBriefTab" data-arg="state">2 상태 승인 지시서</button>
    </div>
    <div class="cols" role="tabpanel" id="brief-panel" aria-label="${body ? '1 본문 작성 지시서' : '2 상태 승인 지시서'}">
      <section class="card" style="flex:1.3 1 480px;min-width:0">
        <div class="between"><h2><span class="small" style="font-weight:400">① </span>복사해서 채팅 앱에 붙여 넣기</h2>
          <div class="row"><button class="btn small" data-action="downloadBrief" data-arg="${n}"${stateBlocked ? ' disabled' : ''}>.md 내려받기</button><button class="btn small dark" data-action="copyBrief"${stateBlocked ? ' disabled' : ''}>복사</button></div></div>
        ${e.status === 'draft' && body ? '<div class="note warn">플롯이 아직 초안이에요. 확정 전 내용으로 지시서가 만들어져요.</div>' : ''}
        ${stateBlocked
          ? `<div class="note plain">${n}화 본문이 아직 없어 상태 승인 지시서를 만들 수 없어요. 본문을 먼저 저장하세요. <button class="btn small" data-action="setBriefTab" data-arg="episode">본문 작성 지시서로</button></div>`
          : `<pre class="brief mono">${esc(S.briefText ?? '불러오는 중…')}</pre>
        ${S.briefText ? `<div class="small">${S.briefText.length.toLocaleString()}자</div>` : ''}`}
      </section>
      <section class="card" style="flex:1 1 380px;min-width:0">
        ${body ? `<h2><span class="small" style="font-weight:400">② </span>받은 본문 가져오기</h2>
          <label for="imp-body" class="small">채팅 앱이 쓴 본문을 그대로 붙여 넣으세요.</label>
          <textarea id="imp-body" rows="12" data-brief="${n}:episode" style="font-family:var(--serif);line-height:1.8"${e.status === 'draft' || e.status === 'finalized' ? ' disabled' : ''}>${esc(S.briefDraft[`${S.name}:${n}:episode`] || '')}</textarea>
          <div class="small" id="imp-count">${importCount(S.briefDraft[`${S.name}:${n}:episode`] || '')}</div>
          ${e.status === 'draft' ? '<div class="small">플롯을 확정해야 본문을 저장할 수 있어요.</div>' : ''}${e.status === 'finalized' ? '<div class="small">이미 끝난 화예요.</div>' : ''}
          ${orderNote(order)}
          <div style="align-self:flex-end"><button class="btn primary" data-action="importText" data-arg="${n}"${e.status === 'draft' || e.status === 'finalized' || order.length ? ' disabled' : ''}>${n}화 본문으로 저장</button></div>`
        : `<h2><span class="small" style="font-weight:400">② </span>받은 JSON 가져오기</h2>
          <label for="imp-json" class="small">채팅 앱의 JSON 답변을 붙여 넣으세요. 코드 블록 표시는 자동으로 지워요.</label>
          <textarea id="imp-json" rows="12" data-brief="${n}:state" class="mono"${e.status !== 'written' ? ' disabled' : ''}>${esc(S.briefDraft[`${S.name}:${n}:state`] || '')}</textarea>
          ${e.status !== 'written' ? '<div class="small">본문이 작성된 화에서만 쓸 수 있어요.</div>' : ''}
          ${briefImportError && briefImportError.key === `${S.name}:${n}` ? `<div class="note err" role="alert">${esc(briefImportError.msg)}</div>` : ''}
          ${orderNote(order)}
          <div style="align-self:flex-end"><button class="btn primary" data-action="importJson" data-arg="${n}"${e.status !== 'written' || order.length ? ' disabled' : ''}>확인하고 변경안 검토로</button></div>`}
        <div style="padding-top:12px;border-top:1px solid var(--line);display:flex;flex-direction:column;gap:8px">
          <strong style="font-size:0.8125rem">순서</strong>
          <ol style="padding-left:20px;display:flex;flex-direction:column;gap:4px;font-size:0.8125rem;line-height:1.55;color:var(--text-2)">
            <li>본문 작성 지시서 → 받은 본문 저장</li><li>상태 승인 지시서 → 받은 JSON 가져오기</li><li>상태 승인 화면에서 반영</li></ol>
        </div>
      </section>
    </div>`;
}

// ---------- 연구 (모델 실험) ----------
// 본편 데이터와 분리된 실험실. 결과는 projects/<이름>/research/log.jsonl 에 남고,
// 블라인드 비교에서 채택할 때만 작품 본문이 바뀐다.

const RS_TABS = [['probe', '서버 점검'], ['sample', '샘플 생성'], ['stage', '단계 시험'], ['budget', '컨텍스트 크기'], ['check', '검수 시험'], ['compare', '블라인드 비교'], ['log', '기록']];
const RS_KIND = { sample: '샘플 생성', stage: '단계 시험', budget: '컨텍스트 크기', check: '검수 시험', compare: '블라인드 비교', pick: '비교 고르기' };

function rsInit(name) {
  const c = S.config || {};
  const backend = () => ({ provider: c.provider === 'mock' ? 'mock' : 'local', model: c.local_model || '', url: '' });
  // 비교 A 는 설정의 본문 쓰기 백엔드, B 는 그와 다른 백엔드 (같으면 서버가 거절한다)
  const writeProv = ((c.stages || {}).write || {}).provider || c.provider || 'gemini';
  const cmpA = { provider: writeProv, model: '', url: '' };
  const cmpB = { provider: writeProv === 'local' ? 'gemini' : 'local', model: '', url: '' };
  S.rs = {
    name, tab: 'probe', log: [], stages: {}, probe: null, probeUrl: c.local_url || '',
    runs: [backend()], system: '너는 한국어 소설가다.', prompt: '', temperature: '', sample: null,
    stageBackend: backend(), stage: 'style', stageText: '', stageResult: null,
    budgetBackend: backend(), budget: null,
    checkBackend: backend(), checkEp: null, checkPlants: '3', check: null, checkModes: {},
    checkJudge: backend(), checkTwoStep: false,
    compareEp: null, compareA: cmpA, compareB: cmpB, compare: null, adopt: true, pickResult: null, probeError: null,
  };
}

async function rsLoadLog() {
  const r = await api('GET', `/projects/${enc(S.name)}/research`);
  S.rs.log = r.log;
  S.rs.stages = r.stages;
  S.rs.checkModes = r.check_modes || {};
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
  async voiceAI(cid) {
    const c = P().characters.find((x) => x.id === cid);
    if (!c) return;
    if ((c.narration_voice || '').trim() && !confirm('지금 적힌 서술 말투를 AI 초안으로 바꿀까요? 저장하기 전에는 되돌릴 수 있어요')) return;
    await run('서술 말투 초안 만드는 중', async () => {
      await saveIfDirty();  // AI는 저장된 인물 설정을 읽는다. 방금 고친 설정이나 새 인물도 보게 먼저 저장한다
      const req = document.getElementById(`voice-req-${cid}`);
      const s = await api('POST', `/projects/${enc(S.name)}/characters/${enc(cid)}/voice`, { request: req ? req.value.trim() : '' });
      c.narration_voice = s.voice;
      S.voices = { ...(S.voices || {}), [cid]: s.note || '' };
      markDirty();
      toast('초안을 칸에 넣었어요. 고친 뒤 저장하세요');
    });
  },
  rsTab(tab) {
    S.rs.tab = tab;
    render();
  },
  async rsProbe() {
    await run('서버를 확인하는 중', async () => {
      try {
        S.rs.probe = await api('POST', '/research/probe', { url: S.rs.probeUrl.trim() });
        S.rs.probeError = null;
      } catch (e) {
        if (e.status !== 400) throw e;
        S.rs.probe = null;
        S.rs.probeError = e.message;  // 토스트는 사라지니 카드 안에 남긴다
      }
    });
  },
  rsUseModel(id) {
    S.rs.runs.push({ provider: 'local', model: id, url: S.rs.probeUrl.trim() === (S.config.local_url || '') ? '' : S.rs.probeUrl.trim() });
    S.rs.tab = 'sample';
    toast(`${id} 를 샘플 생성에 넣었어요`);
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
  async rsCheck() {
    const n = Number(S.rs.checkEp || ($('#rs-check-ep') || {}).value);
    if (!n) return toast('본문이 있는 화를 고르세요', true);
    await run(`${n}화에 모순을 심고 검수 방식마다 검수하는 중… (저장하지 않음)`, async () => {
      S.rs.check = await api('POST', `/projects/${enc(S.name)}/research/check`,
        { backend: rsBackend(S.rs.checkBackend), episode: n, plants: Number(S.rs.checkPlants) || 3,
          ...(S.rs.checkTwoStep ? { judge: rsBackend(S.rs.checkJudge) } : {}) });
      S.rs.log.unshift(S.rs.check);
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
    const adopt = S.rs.adopt && ep(n).status !== 'finalized';  // 반영이 끝난 화는 고른 기록만 남긴다
    if (adopt && ep(n).text && !confirm(`${k}번을 ${n}화 본문으로 바꿀까요?`)) return;
    await run('공개하는 중', async () => {
      await saveIfDirty();
      const r = await api('POST', `/projects/${enc(S.name)}/research/compare/${n}/pick`, { k, adopt });
      S.rs.compare = r.compare;
      S.rs.pickResult = r.result;
      S.project = r.project;
      await rsLoadLog();
      delete S.textDraft[n];
      delete S.deltas[n];
      toast(`${k}번은 ${r.result.picked} 였어요${r.result.adopted ? `. ${n}화 본문으로 저장했어요` : ''}`);
    });
  },
});

function rsBackendFields(path, b, kinds = [['local', '로컬 서버'], ['gemini', 'Gemini'], ['mock', 'mock']]) {
  const id = 'rs-' + path.replace(/\W/g, '-');
  const opts = kinds
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
      <p class="desc">OpenAI 호환 서버(vLLM, Ollama, llama.cpp, LM Studio)의 모델 목록과 컨텍스트 길이를 봐요. 생성 호출은 하지 않아요.</p>
      <div class="row" style="align-items:flex-end;flex-wrap:nowrap">
        <div class="field" style="flex:1"><label for="rs-probe-url">서버 주소 <span class="hint">/v1 까지</span></label><input id="rs-probe-url" type="text" value="${esc(S.rs.probeUrl)}" data-rs="probeUrl" placeholder="http://nhn-b200:8001/v1"></div>
        <button class="btn dark" data-action="rsProbe">점검</button>
      </div>
      ${S.rs.probeError ? `<div class="note err" role="alert">${esc(S.rs.probeError)}</div>` : ''}
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
      <p class="desc">같은 요청을 여러 백엔드에 차례로 보내 시간, 토큰, 문체 지표를 나란히 봐요. 작품 데이터는 쓰지 않아요.</p>
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
      ${r.attempts > 1 ? '<div class="note warn">첫 응답이 스키마 검증에 실패해 한 번 더 물었어요.</div>' : ''}
      <details><summary>응답 JSON 보기</summary><pre class="brief mono">${esc(JSON.stringify(r.result, null, 2))}</pre></details>
    </section>`;
  }
  return `<section class="card">
      <p class="desc">설정 제안, 문체 분석, 기승전결을 저장하지 않고 돌려 봐요. 모델이 건너뛴 필드, 범위를 벗어난 숫자, 재시도 횟수를 확인해요.</p>
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
    const parts = (c) => (c.blocks || []).map(([k, v]) => `${k} ${Math.round((v / c.chars) * 100)}%`).join(' · ');
    const cell = (c) => `<td class="${c.over ? 'over' : c.tight ? 'tight' : ''}" title="${esc(parts(c))}">${c.exact ? '' : '~'}${rsNum(c.tokens)}<span class="small"> / ${rsNum(c.total)}</span></td>`;
    const rows = r.rows.map((x) => `<tr><td>${x.episode}화</td><td><span class="chip ${x.status}">${STATUS[x.status]}</span>${x.measured ? '' : ' <span class="small">가정</span>'}</td>${cell(x.write)}${cell(x.check)}${cell(x.state)}</tr>`).join('');
    out = `<section class="card">
      <div class="between"><h2>${esc(r.backend)} · ${esc(r.model)}</h2><span class="small">최대 컨텍스트 ${r.limit ? rsNum(r.limit) + ' 토큰' : '알 수 없음'}</span></div>
      ${r.first_over ? `<div class="note err">${r.first_over}화부터 입력만으로 한도를 넘어 서버가 요청을 거절해요. 단편의 검수(check)는 앞선 본문 전체를 넣어 화가 갈수록 커져요. 서버의 컨텍스트를 늘리거나, 설정의 단계별 백엔드에서 넘치는 단계를 Gemini 로 돌리세요.</div>` : ''}
      ${r.first_tight && r.first_tight !== r.first_over ? `<div class="note warn">${r.first_tight}화부터 출력 여유까지 더하면 한도를 넘어요. 응답이 중간에 잘릴 수 있어요.</div>` : ''}
      ${!r.limit ? '<div class="note plain">이 백엔드는 한도를 알려 주지 않아 넘침은 판단하지 않았어요.</div>' : (!r.first_tight ? '<div class="note ok">플롯이 있는 화는 모두 한도 안에 들어가요.</div>' : '')}
      <div class="rs-scroll"><table class="rs-table"><thead><tr><th>화</th><th>상태</th><th>본문 쓰기</th><th>검수</th><th>상태 변경안</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="small">칸마다 '입력 / 입력+출력 여유' 토큰이에요. 출력 여유는 본문 ${rsNum(r.write_reserve)}, 검수·상태 ${rsNum(r.json_reserve)} 토큰으로 잡았어요. ${r.tokenizer ? '서버 토크나이저로 셌어요.' : '~ 표시는 글자 수로 어림한 값이에요.'} '가정'인 화는 앞선 화가 모두 목표 분량으로 쓰였다고 보고 쟀어요. 플롯이 있는 화만 재요. 칸에 올리면 큰 블록 비중이 보여요.</div>
    </section>`;
  }
  return `<section class="card">
      <p class="desc">화마다 본문 쓰기, 검수, 상태 변경안에 들어가는 프롬프트 크기를 모델의 컨텍스트 한도와 비교해요. 생성 호출은 하지 않아요.</p>
      ${rsBackendFields('budgetBackend', S.rs.budgetBackend)}
      <div><button class="btn dark" data-action="rsBudget">재기</button></div>
    </section>${out}`;
}

function rsCheckView() {
  const eps = P().episodes.filter((e) => e.text);
  const r = S.rs.check;
  let out = '';
  if (r) {
    const modes = r.runs.map((x) => `<th>${esc(x.mode)}<div class="small">${x.tokens == null ? '' : `~${rsNum(x.tokens)} 토큰`}</div>${x.mode === 'twostep' && x.ok ? `<div class="small">판단기 ~${rsNum(x.judge_tokens)} 토큰 · 진술 ${x.claims}개 중 ${x.flagged}개 의심</div>` : ''}</th>`).join('');
    const rows = r.planted.map((x, i) => `<tr><td><div class="small">${esc(x.type)} · 근거: ${x.source_episode ? `${x.source_episode}화 (${x.distance}화 전)` : '설정이나 확정 사실'}</div>
        <div class="rs-prose small"><del>${esc(x.quote)}</del><br><ins>${esc(x.replacement)}</ins></div></td>
        ${r.runs.map((m) => `<td>${!m.ok ? '<span class="chip usage-fail">실패</span>' : m.hits[i] ? '<span class="chip finalized">찾음</span>' : '<span class="chip written">놓침</span>'}${m.ok && m.raised && !m.hits[i] ? `<div class="small">${m.raised[i] ? '판단기는 올림' : '판단기가 놓침'}</div>` : ''}</td>`).join('')}</tr>`).join('');
    const sum = r.runs.map((m) => `<td><strong>${m.ok ? `${m.found}/${r.planted.length}` : esc(m.error)}</strong>${m.ok ? `<div class="small">다른 지적 ${m.other.length}개 · ${m.seconds}초</div>` : ''}</td>`).join('');
    out = `<section class="card">
      <div class="between"><h2>${r.episode}화 · ${esc(r.backend)}</h2><span class="small">심은 모순 ${r.planted.length}개${r.skipped.length ? ` (원문을 못 찾아 ${r.skipped.length}개 뺌)` : ''} · ${r.seconds}초</span></div>
      <div class="rs-scroll"><table class="rs-table"><thead><tr><th>심은 모순</th>${modes}</tr></thead><tbody>${rows}<tr><td>찾은 수</td>${sum}</tr></tbody></table></div>
      ${r.runs.filter((m) => m.ok && m.other.length).map((m) => `<details><summary>${esc(m.mode)}의 다른 지적 ${m.other.length}개</summary><ul>${m.other.map((i) => `<li class="small">${esc(i.type)}: ${esc(i.description)}</li>`).join('')}</ul></details>`).join('')}
      ${r.runs.filter((m) => m.mode === 'twostep' && m.ok && m.judged.length).map((m) => `<details><summary>판단기가 본 진술 ${m.judged.length}개 (${esc(m.judge)})</summary><ul>${m.judged.map((j) => `<li class="small">${j.flagged ? '<span class="chip written">의심</span> ' : ''}어긋남 ${Math.round((j.probs[1] || 0) * 100)}% · ${esc(j.claim)}${j.mass < 0.5 ? ' <span class="hint">선택지 밖 답이 많았어요</span>' : ''}</li>`).join('')}</ul></details>`).join('')}
      <div class="small">한 번으로는 우연이 커요. 여러 화에서 몇 번 돌려 기록 탭에서 찾은 비율을 견주세요. 모순을 심는 것도 같은 모델이 해요.</div>
    </section>`;
  }
  const modes = Object.entries(S.rs.checkModes).map(([k, v]) => `<li><strong>${esc(k)}</strong>: ${esc(v)}</li>`).join('');
  return `<section class="card">
      <p class="desc">본문이 있는 화에 모순을 몇 개 심고, 검수 방식마다 그걸 찾는지 봐요. 장편 검수는 입력을 줄인 방식이 기본이라 줄여서 놓치는 게 없는지 확인하는 용도예요. 작품에는 저장하지 않고, 호출은 심기 1번 + 방식마다 1번이에요.</p>
      ${modes ? `<ul class="small">${modes}</ul>` : ''}
      ${rsBackendFields('checkBackend', S.rs.checkBackend)}
      <label class="check-row"><input type="checkbox" data-rs="checkTwoStep" onchange="render()"${S.rs.checkTwoStep ? ' checked' : ''}><span><strong>두 걸음 검수도 시험</strong> <span class="small">위 백엔드가 진술을 뽑고 의심만 판정해요. 그 사이에 판단기가 진술마다 선택지 확률만 내요(로컬 서버는 logprobs 지원 필요). 검수 모델 호출 2번 + 판단기 호출 진술 수만큼 늘어요.</span></span></label>
      ${S.rs.checkTwoStep ? `<h3>판단기</h3>${rsBackendFields('checkJudge', S.rs.checkJudge, [['local', '로컬 서버'], ['mock', 'mock']])}` : ''}
      <div class="row">
        <div class="field" style="max-width:320px"><label for="rs-check-ep">화</label>
          <select id="rs-check-ep" data-rs="checkEp">${eps.map((x) => `<option value="${x.plot.number}"${String(x.plot.number) === String(S.rs.checkEp) ? ' selected' : ''}>${x.plot.number}화 ${esc(x.plot.title)}</option>`).join('') || '<option value="">본문이 있는 화가 없어요</option>'}</select></div>
        <div class="field" style="max-width:140px"><label for="rs-check-n">심을 모순</label><input id="rs-check-n" type="number" min="1" max="5" value="${esc(S.rs.checkPlants)}" data-rs="checkPlants"></div>
      </div>
      <div><button class="btn dark" data-action="rsCheck">시험</button></div>
    </section>${out}`;
}

function rsCompareView() {
  const eps = P().episodes.filter((e) => e.status !== 'draft');
  const c = S.rs.compare;
  const n = S.rs.compareEp;
  const e = ep(n);
  // 비교본은 집필과 같은 규칙으로 쓴다: 앞 화가 모두 반영돼야 쓸 수 있다
  const need = (num) => { const b = blockedBefore(num); return b.length ? ` (${b.length > 3 ? `${b[0]}화 등 ${b.length}개 화` : `${b.join(', ')}화`} 반영 필요)` : ''; };
  const blocked = e ? blockedBefore(n) : [];
  const fin = e && e.status === 'finalized';
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
      <p class="desc">같은 화를 두 백엔드로 쓰고 1, 2번으로 가려요. 읽고 고르면 어느 쪽이었는지 공개해요. 프롬프트는 집필 화면과 같아요.</p>
      <div class="field" style="max-width:320px"><label for="rs-cmp-ep">화</label>
        <select id="rs-cmp-ep" onchange="actions.rsCompareEp()">${eps.map((x) => `<option value="${x.plot.number}"${x.plot.number === n ? ' selected' : ''}>${x.plot.number}화 ${esc(x.plot.title)} · ${STATUS[x.status]}${need(x.plot.number)}</option>`).join('') || '<option>확정된 화가 없어요</option>'}</select></div>
      <div class="grid-2"><div><h3>A</h3>${rsBackendFields('compareA', S.rs.compareA)}</div><div><h3>B</h3>${rsBackendFields('compareB', S.rs.compareB)}</div></div>
      <label class="check-row"><input type="checkbox" data-rs="adopt"${S.rs.adopt && !fin ? ' checked' : ''}${fin ? ' disabled' : ''}><span><strong>고른 쪽을 본문으로 채택</strong> <span class="small">끄면 고른 기록만 남기고 작품은 그대로 둬요. 반영이 끝난 화는 채택할 수 없어요.</span></span></label>
      <div><button class="btn dark" data-action="rsCompare"${eps.length && e && e.status !== 'draft' && !blocked.length ? '' : ' disabled'}>${n}화 비교본 쓰기</button></div>
      ${blocked.length ? orderNote(blocked) : fin ? '<div class="note plain">이 화는 반영이 끝난 화라 골라도 본문은 바뀌지 않고 고른 기록만 남아요.</div>' : ''}
    </section>
    ${S.rs.pickResult ? `<div class="note ok">${esc(S.rs.pickResult.picked)} 를 골랐어요. 지금까지 고른 횟수: ${wins}</div>` : ''}
    ${c ? `<div class="small">${esc(fmtDateTime(c.created))}에 쓴 비교본${c.picked ? '' : ' · 고르기 전까지 백엔드를 가려요'}</div><div class="rs-compare">${drafts}</div>` : ''}`;
}

function rsLogView() {
  const items = S.rs.log.map((x) => {
    let line = '';
    if (x.kind === 'sample') line = x.rows.map((r) => `${r.backend} ${r.ok ? `${rsNum(r.chars)}자 ${r.seconds}초` : '실패'}`).join(' · ');
    if (x.kind === 'stage') line = `${S.rs.stages[x.stage] || x.stage} · ${x.backend} · ${x.ok ? `빈 필드 ${x.empty.length}/${x.fields}, 범위 밖 ${x.out_of_range.length}, 시도 ${x.attempts}` : '실패'} · ${x.seconds}초`;
    if (x.kind === 'budget') line = `${x.backend} · 한도 ${x.limit ? rsNum(x.limit) : '알 수 없음'} · ${x.first_over ? `${x.first_over}화부터 넘침` : x.first_tight ? `${x.first_tight}화부터 빠듯함` : '넘침 없음'}`;
    if (x.kind === 'compare') line = `${x.episode}화 · ${x.backends.join(' vs ')}`;
    if (x.kind === 'check') line = `${x.episode}화 · ${x.backend} · ${x.runs.map((m) => `${m.mode} ${m.ok ? `${m.found}/${x.planted.length}` : '실패'}`).join(', ')}`;
    if (x.kind === 'pick') line = `${x.episode}화 · ${x.picked} 고름${x.adopted ? ' (본문 채택)' : ''}`;
    return `<li><div class="between"><span><span class="chip">${RS_KIND[x.kind] || x.kind}</span> ${esc(line)}</span><span class="small">${esc(fmtDateTime(x.time))}</span></div>
      <details><summary>자세히</summary><pre class="brief mono">${esc(JSON.stringify(x, null, 2))}</pre></details></li>`;
  }).join('');
  return `<section class="card">
      <p class="desc">최근 30개 실험이에요. 전체 기록은 작품 폴더의 research/log.jsonl 에 있어요.</p>
      ${items ? `<ul class="rs-log">${items}</ul>` : '<div class="small">아직 기록이 없어요.</div>'}
    </section>`;
}

function viewResearch() {
  if (!S.rs) return header('연구', '모델 실험', '') + '<div class="note plain">불러오는 중…</div>';
  const views = { probe: rsProbeView, sample: rsSampleView, stage: rsStageView, budget: rsBudgetView, check: rsCheckView, compare: rsCompareView, log: rsLogView };
  return `${header('연구 · 본편과 분리', '모델 실험', '모델 서버를 점검하고, 같은 요청을 여러 모델로 돌려 비교해요. 여기서 돌린 결과는 작품 데이터에 들어가지 않고 실험 기록으로만 남아요. 블라인드 비교에서 채택할 때만 본문이 바뀌어요.')}
    <div class="tabs" role="tablist" aria-label="실험 종류">${RS_TABS.map(([k, l]) => `<button type="button" role="tab" aria-selected="${S.rs.tab === k}" aria-controls="rs-panel" data-action="rsTab" data-arg="${k}">${l}</button>`).join('')}</div>
    <div role="tabpanel" id="rs-panel" aria-label="${esc((RS_TABS.find(([k]) => k === S.rs.tab) || [, ''])[1])}">
    ${rsModelList()}
    ${views[S.rs.tab]()}</div>`;
}

route();
pollJobs();

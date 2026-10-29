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
  styleSampleDirty: false,  // 문체 화면에 붙여 넣은 원문을 아직 분석하거나 라이브러리에 저장하지 않았다
  draftFound: {},    // 다시 열 때 브라우저에서 찾은, 서버 본문과 다른 본문 초안. 화 → { text, at }
  libs: null,       // 문체 라이브러리 목록
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
  popMenu: null,     // 열린 펼침 메뉴 id (menuBtn). 다시 그려도 열려 있고, 화면을 옮기면 닫는다
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
  ideas: {},         // 설정 칸 하나의 AI 후보 (ideas.js). 칸 경로 → { options: [{ text, reason }] }
  nameCheck: null,   // 출연진 이름 점검 { warnings, style, detected }
  placeKind: '',     // 지명 후보의 종류 (산, 마을, 문파…)
  dex: null,         // 원형 도감 목록 (서버 archetypes, archetypes.js)
  dexRolls: null,    // 도감 주사위 결과 { list, archetype }
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
  // 문체를 분석했거나 라이브러리에 저장했으면 붙여 넣은 원문은 더 잃을 것이 없다 (hasUnsaved)
  if (method === 'POST' && /^\/projects\/[^/]+\/style(\/library)?$/.test(path)) S.styleSampleDirty = false;
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
// 작업 목록 · 알림에 넣지 않는 작업: 플레이 화면이 시계와 출생 카드에 따로 보인다 (play.js)
const QUIET_JOBS = new Set(['play_turn', 'play_sketch']);
JOB_DONE_MSG.play_world = (j) => `새 세계 ${j.project}${josa(j.project, '을', '를')} 만들었어요. 새 플레이에서 고르세요.`;
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
  S.jobs = list.filter((j) => (!S.jobsSeen.has(j.id) || j.status === 'running') && !QUIET_JOBS.has(j.kind));
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
    if (j.kind === 'agent' && typeof agentJobUpdate === 'function') await agentJobUpdate(j, old);  // 대화 에이전트 턴 (agent.js)
    if (j.kind === 'plots') {
      // 이번에 끝난 구간(지난번에 아직 만들던 화)과 새로 생긴 화만 받아 온다. 먼저 끝난 구간에서 고치던 초안은 그대로 둔다
      const was = old && Array.isArray(old.pending) ? new Set(old.pending) : null;
      await mergeEpisodes((cur, e) => cur.status === 'draft' && (!was || was.has(e.plot.number)));
      S.jobsMerged[j.id] = j.done;  // 저장할 때 이 단계까지 받아 왔다고 알린다 (save)
    }
    if (j.kind === 'write' && j.status !== 'running') await mergeEpisodes((e) => e.plot.number === j.ep);
    if (j.kind === 'board' && j.status !== 'running') await mergeEpisodes((e) => e.plot.number === j.ep);  // 스토리보드는 그 화에 붙었다 (board.js)
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
    if (S.route[0] === 'p' && (JOB_PAGES[j.kind] || []).includes(S.route[2] || 'home')) {
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
  recap_part: '#app .part-edit textarea[data-root="recaps"]', recap_arc: '#app textarea[data-root="recaps"]' };  // 요약 제안 칸은 서랍 · 카드 아래쪽이라 그리로 데려간다

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
JOB_DONE_MSG.check = (j) => `${j.ep}화 검수가 끝났어요${j.result && j.result.round ? ` (${j.result.round}회차)` : ''}: 짚은 곳 ${j.result ? j.result.issues : 0}개${j.result && j.result.round > 1 ? `, 새 지적 ${j.result.added}개` : ''}`;
const JOB_PAGES = { check: ['check', 'write', 'review'], suggest: ['setup'], arc: ['arc'], plots: ['arc', 'home', 'causal'], plot_one: ['arc', 'lines'], write: ['write', 'home', 'causal'], state: ['review'], auto: ['auto', 'home', 'write', 'causal', 'arc', 'setup'], impact: ['causal'], series: ['arc'], nextarc: ['arc'], recap_arc: ['arc'], recap_part: ['arc'], storyline: ['lines'] };

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
  if (j.kind === 'agent' && here && $('.chat-panel')) return;  // 열린 대화 패널이 결과를 보여 준다 (agent.js)
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
  const list = Object.values(S.pending.failures).filter((f) => (JOB_PAGES[f.kind] || []).includes(page || 'home') && (f.ep == null || !['write', 'check', 'review', 'brief'].includes(page) || f.ep === n));
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
  play_world: (j) => `#/play/new/${enc(j.project)}`,
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
  const one = running.length === 1 ? [`${running[0].label}${running[0].total > 1 ? ` ${running[0].done}/${running[0].total}` : ''}`, jobLeft(running[0], Date.now() / 1000)].filter(Boolean).join(' · ') : '';
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
    const sub = j.status === 'error' ? j.error : j.status === 'running' ? [j.note, `경과 ${elapsed(j)}`, jobLeft(j, Date.now() / 1000)].filter(Boolean).join(' · ') : j.note;
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

/** 작업 목록의 남은 시간: 지금까지 한 단계 평균으로 남은 단계를 어림한다. 단계가 하나뿐이거나 아직 하나도 끝나지 않았으면 ''.
    now 는 초 단위 시각. 1분보다 적게 남았으면 '곧 끝나요'. */
function jobLeft(j, now) {
  if (!(j.total > 1 && j.done >= 1)) return '';
  const per = Math.max(0, now - j.started) / j.done;
  const left = per * Math.max(0, j.total - j.done);
  return left < 60 ? '곧 끝나요' : `약 ${Math.round(left / 60)}분 남음`;
}

/** 작업이 시작된 뒤 지난 시간 'm:ss' (서버 시각 기준이라 몇 초 어긋날 수 있다). */
function elapsed(j) {
  const s = Math.max(0, Math.round(Date.now() / 1000 - j.started));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

const narrowScreen = () => window.matchMedia('(max-width: 640px)').matches;

/** 화면 아래 고정 층(저장 띠, 작업 목록, 알림)이 서로와 본문 버튼을 가리지 않게 높이를 CSS 변수로 둔다.
    아래부터 저장 띠 → 반영 줄(상태 승인 화면 .apply-bar) → 작업 목록 → 알림 순서로 쌓는다.
    --sb: 저장 띠 높이, --ab: 반영 줄 높이(있을 때), --jb: 작업 목록 높이(좁은 폭에서 알림 아래에 쌓을 때),
    --jh: 반영 줄 · 버튼 줄이 있거나 상태 승인 화면일 때 작업 목록 높이(넓은 폭에서도 맨 끝 줄이 작업 목록 아래에 갇히지 않게 본문 아래를 띄운다). */
function stackBottom() {
  const h = (el) => (el && !el.hidden ? el.getBoundingClientRect().height + 12 : 0);
  const st = document.body.style;
  const ab = h($('#app .apply-bar'));
  const pa = $('#app .page-actions');  // 화 플롯 페이지의 버튼 줄: 작업 목록 위로 올린다
  const rv = $('#app .rv-grid');  // 상태 승인 화면: 세 칸이면 작업 목록이 오른쪽 열 위로, 두 칸이면 목차 칸 위로 간다 (app.css)
  const rvRight = rv && window.innerWidth >= 1200;
  st.setProperty('--sb', `${h($('#savebar:not(.inline)'))}px`);
  st.setProperty('--ab', `${ab}px`);
  // 대화 패널이 열리거나 상태 승인 화면이면 알림이 작업 목록과 같은 자리(오른쪽)로 오므로 넓은 폭에서도 작업 목록 위에 쌓는다
  st.setProperty('--jb', `${narrowScreen() || rv || document.body.classList.contains('chat-open') ? h($('#jobs')) : 0}px`);
  st.setProperty('--jh', `${ab || pa || rv ? h($('#jobs')) : 0}px`);
  const jh = h($('#jobs'));
  st.setProperty('--jo', `${narrowScreen() ? 0 : jh}px`);  // 넓은 폭: 화면에 붙인 칸(상태 승인 오른쪽 열)이 작업 목록 위에서 끝나게
  st.setProperty('--jp', `${pa && jh ? jh + 20 : 0}px`);  // 버튼 줄 아래 여백(20px)까지 작업 목록 위로
  // 상태 승인 두 칸: 작업 목록 · 알림을 목차 칸 위에 그 폭으로 쌓고, 목차 칸은 그 위에서 끝낸다 (review.js rvRailFit)
  const rail = rv && !rvRight && !narrowScreen() ? $('#app .rv-rail').getBoundingClientRect() : null;
  const toasts = $('#toast');
  st.setProperty('--rv-jx', `${rail ? Math.round(rail.left) : 16}px`);
  st.setProperty('--rv-jw', `${rail ? Math.round(rail.width) : 200}px`);
  st.setProperty('--rvj', `${rail ? jh + (toasts && toasts.children.length ? toasts.getBoundingClientRect().height + 12 : 0) : 0}px`);
  if (typeof rvRailFit === 'function') rvRailFit();
}
window.addEventListener('resize', () => stackBottom());
// 상태 승인 두 칸에서는 알림도 목차 칸 위에 쌓으므로, 알림이 뜨고 질 때 높이를 다시 잰다
if (typeof MutationObserver !== 'undefined' && $('#toast')) new MutationObserver(() => { if ($('#app .rv-grid')) stackBottom(); }).observe($('#toast'), { childList: true });

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
    ? `<textarea id="${id}" rows="${opt.rows || 3}" data-bind="${path}" data-kind="${kind}"${rootAttr}${ro}${opt.autogrow ? ' data-autogrow' : ''}${opt.style ? ` style="${opt.style}"` : ''} placeholder="${esc(opt.placeholder || (kind === 'list' ? '한 줄에 하나씩' : ''))}">${val}</textarea>`
    : `<input id="${id}" type="${opt.type || 'text'}" value="${val}" data-bind="${path}" data-kind="${kind}"${rootAttr}${ro}${opt.min != null ? ` min="${opt.min}"` : ''}${opt.max != null ? ` max="${opt.max}"` : ''}${opt.list ? ` list="${opt.list}"` : ''} placeholder="${esc(opt.placeholder || '')}">`;
  // aside 는 이름 줄 오른쪽, beside 는 칸 바로 옆, after 는 칸 바로 아래 (칸 하나 AI 후보 ✦ 버튼과 후보, ideas.js)
  const lab = `<label for="${id}">${esc(label)}${hint}</label>`;
  const head = opt.aside ? `<div class="lab-row">${lab}${opt.aside}</div>` : lab;
  const body = opt.beside ? `<div class="in-ai">${ctrl}${opt.beside}</div>` : ctrl;
  return `<div class="field${opt.cls ? ' ' + opt.cls : ''}">${head}${body}${opt.after || ''}</div>`;
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
  if (el.dataset.local === 'styleSample') S.styleSampleDirty = true;
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
  // 접힌 칸(닫힌 details 안)은 높이를 잴 수 없다. 2px 로 줄지 않게 두고, 펼칠 때 잰다 (아래 toggle)
  if (!el.offsetParent) return;
  el.style.height = 'auto';
  el.style.height = el.scrollHeight + 2 + 'px';
}
document.addEventListener('input', (e) => {
  if (e.target.matches && e.target.matches('textarea[data-autogrow]')) autosize(e.target);
});
document.addEventListener('toggle', (e) => {
  if (e.target.open) e.target.querySelectorAll('textarea[data-autogrow]').forEach(autosize);
}, true);
// 칸 폭이 바뀌거나(창 크기) 웹 글꼴이 늦게 들어오면 줄바꿈이 달라진다. 그때 높이를 다시 잰다
const autosizeAll = () => document.querySelectorAll('textarea[data-autogrow]').forEach(autosize);
let autosizeWidth = window.innerWidth;
window.addEventListener('resize', () => {
  if (window.innerWidth === autosizeWidth) return;  // 휴대폰 주소창이 접힐 때(높이만 바뀜)는 그대로
  autosizeWidth = window.innerWidth;
  requestAnimationFrame(autosizeAll);
});
if (document.fonts) document.fonts.addEventListener('loadingdone', () => requestAnimationFrame(autosizeAll));
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

/** 집필 화면에서 고친 본문이 있으면 본문을, 아니면 작품 변경을 저장한다. 저장할 것이 없으면 false (Ctrl+S, 명령 팔레트 '저장').
    dry 이면 저장하지 않고 저장할 것이 있는지만 답한다. */
function saveShortcut(dry = false) {
  const [p, , page, arg] = S.route;
  const n = p === 'p' && page === 'write' && P() ? Number(arg) || currentEp() : null;
  const text = n !== null && textUnsaved(n) && editableEp(ep(n));
  if (!text && !S.dirty) return false;
  if (!dry) { if (text) actions.saveText(n); else actions.save(); }
  return true;
}

// Ctrl+S (macOS 는 Cmd+S): saveShortcut. 브라우저의 '페이지 저장'은 막는다
document.addEventListener('keydown', (e) => {
  if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== 's' || e.isComposing) return;
  e.preventDefault();
  saveShortcut();
});

document.addEventListener('keydown', (e) => {
  // Esc: 대화 패널이 먼저 닫히고(chat.js 가 capture 로 받아 defaultPrevented), 그다음 화 플롯 페이지나 그 자리에서 편 구간 · 아크 · 부 고치기가 닫힌다
  if (e.key === 'Escape' && !e.isComposing && !e.defaultPrevented && S.route[2] === 'arc') {
    if (plotPageN()) { actions.closePlot(); return; }
    if (S.selAct != null || S.editArc || S.selPart != null) { actions.closePanel(); return; }
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

// ---------- 본문 초안 임시 보관 ----------
// 저장하지 않은 본문 초안을 화마다 이 브라우저(localStorage)에 몇 초 간격으로 둔다. 탭이 죽거나 새로고침해도 다시 열면 되살린다.
// 키 'canon.draft.<작품>.<화>', 값 { text, at, client }. 초안이 서버 본문과 같아지거나 사라지면(저장 · 버림 · AI 본문) 지운다.
const DRAFT_PREFIX = (name) => `canon.draft.${name}.`;
const draftStore = {
  get(k) { try { return JSON.parse(localStorage.getItem(k) || 'null'); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch { return false; } },
  del(k) { try { localStorage.removeItem(k); } catch { /* 저장소를 막은 브라우저 */ } },
  keys(prefix) { try { return Object.keys(localStorage).filter((k) => k.startsWith(prefix)); } catch { return []; } },
};
const draftKept = new Map();  // 이 탭이 둔 키 → 마지막으로 둔 값. 다른 탭이 둔 초안은 지우지 않는다
let draftBlocked = false;     // 브라우저가 저장을 막았다 (사생활 보호 창, 용량 초과)

/** 지금 작품의 저장하지 않은 초안을 두고, 더는 저장하지 않은 초안이 아닌 것은 지운다. */
function keepDrafts() {
  if (!S.name || !P() || stateOwner !== S.name) return;
  const pre = DRAFT_PREFIX(S.name);
  for (const [n, text] of Object.entries(S.textDraft)) {
    if (!textUnsaved(n)) continue;
    const k = pre + n;
    if (draftKept.has(k) && draftKept.get(k).text === text) continue;
    const v = { text, at: Date.now(), client: CLIENT };
    draftBlocked = !draftStore.set(k, v);
    if (!draftBlocked) draftKept.set(k, v);
  }
  for (const k of [...draftKept.keys()]) {
    if (!k.startsWith(pre)) continue;  // 보관해 둔 다른 작품 초안은 그 작품으로 돌아가면 본다
    const n = k.slice(pre.length);
    if (S.textDraft[n] === undefined || !textUnsaved(n)) { draftStore.del(k); draftKept.delete(k); }
  }
}

// 열려 있는 탭은 몇 초마다 'canon.tab.<탭 id>' 에 시각을 남기고, 닫히거나 새로고침되면 지운다.
// 다른 탭이 지금 쓰는 초안을 되살릴 후보로 내놓지 않으려고 본다
const TAB_KEY = (id) => `canon.tab.${id}`;
const tabAlive = (id) => Date.now() - Number(draftStore.get(TAB_KEY(id)) || 0) < 8000;

/** 작품을 열 때: 이 브라우저에 남은 그 작품 초안 중 서버 본문과 다른 것을 되살릴 후보로 둔다. */
function scanDrafts() {
  S.draftFound = {};
  draftStore.keys('canon.tab.').forEach((k) => { if (Date.now() - Number(draftStore.get(k) || 0) > 60000) draftStore.del(k); });
  const pre = DRAFT_PREFIX(S.name);
  for (const k of draftStore.keys(pre)) {
    const n = Number(k.slice(pre.length));
    const v = draftStore.get(k);
    if (!n || !v || typeof v.text !== 'string') { draftStore.del(k); continue; }
    if (draftKept.has(k) || S.textDraft[n] !== undefined) continue;  // 이 탭이 지금 쓰는 초안
    const e = ep(n);
    if (e ? v.text.trim() === (e.text || '').trim() : !v.text.trim()) { draftStore.del(k); continue; }  // 이미 서버에 들어간 글
    if (v.client !== CLIENT && tabAlive(v.client)) continue;  // 열려 있는 다른 탭이 쓰는 초안
    S.draftFound[n] = v;
  }
}

/** '12초 전' 같은 지난 시간. */
function agoText(at) {
  const s = Math.max(0, Math.round((Date.now() - at) / 1000));
  if (s < 60) return `${s}초 전`;
  if (s < 3600) return `${Math.floor(s / 60)}분 전`;
  return fmtDateTime(new Date(at).toISOString());
}

/** 저장 띠에 붙이는 임시 보관 상태. */
function draftStamp(n) {
  if (draftBlocked) return '브라우저가 막아 임시 보관하지 못했어요';
  const v = draftKept.get(DRAFT_PREFIX(S.name) + n);
  return v ? `${agoText(v.at)} 임시 보관` : '곧 임시 보관해요';
}

setInterval(() => {
  draftStore.set(TAB_KEY(CLIENT), Date.now());
  keepDrafts();
  const st = $('#draft-stamp');
  if (st) st.textContent = draftStamp(st.dataset.ep);
}, 2000);
// 탭을 닫거나 숨길 때는 기다리지 않고 바로 둔다
window.addEventListener('pagehide', () => { keepDrafts(); draftStore.del(TAB_KEY(CLIENT)); });
document.addEventListener('visibilitychange', () => { if (document.hidden) keepDrafts(); });

/** 되살릴 초안 안내. 그 화 집필 화면에는 되살리기 · 복사 · 버리기를, 작품 홈과 다른 화 집필 화면에는 그 화로 가는 줄을 보인다. */
function draftStrip(page, n) {
  const found = Object.entries(S.draftFound || {}).filter(([k]) => ep(Number(k)));
  if (!found.length || !['write', undefined].includes(page)) return '';
  return found.map(([k, v]) => {
    const m = Number(k);
    if (page !== 'write' || m !== n) return `<div class="note warn" role="status">이 브라우저에 저장하지 않은 ${m}화 본문 초안이 남아 있어요 (${agoText(v.at)}). <a href="${base()}/write/${m}">${m}화 집필에서 확인하기</a></div>`;
    return `<div class="note warn" role="status"><strong>저장하지 않은 ${m}화 본문 초안을 찾았어요</strong> · 이 브라우저에 ${agoText(v.at)} 임시 보관한 ${v.text.length.toLocaleString()}자예요. 서버 본문과 달라요.
      <details><summary>임시 보관한 초안 보기</summary><textarea readonly id="found-${m}" aria-label="${m}화 임시 보관한 초안" style="width:100%;min-height:160px;margin-top:6px">${esc(v.text)}</textarea></details>
      <div class="row" style="margin-top:6px"><button class="btn small primary" data-action="restoreDraft" data-arg="${m}">초안 되살리기</button><button class="btn small" data-action="copyFoundDraft" data-arg="${m}">초안 복사</button><button class="btn small danger" data-action="dropFoundDraft" data-arg="${m}">초안 버리기</button></div></div>`;
  }).join('');
}

/** 저장 띠를 만든다. 처음 뜰 때 화면 낭독기에 한 번 알린다 (띠는 문서 끝에 붙어 Tab 으로는 늦게 닿으니 Ctrl+S 도 알린다). */
function newSavebar(shortcut = true) {
  const bar = document.createElement('div');
  bar.id = 'savebar';
  bar.className = 'savebar';
  bar.setAttribute('role', 'region');
  bar.setAttribute('aria-label', '저장하지 않은 변경');
  // 화면이 저장 칸을 두면(화 플롯 페이지의 버튼 줄) 그 안에 넣는다. 떠 있는 띠가 확정 버튼을 가리지 않게 한다
  const slot = $('#app .savebar-slot');
  if (slot) bar.classList.add('inline');
  (slot || document.body).appendChild(bar);
  const live = $('#sr-live');
  if (live) live.textContent = `저장하지 않은 변경이 있어요.${shortcut ? ' Ctrl+S로 저장할 수 있어요.' : ''}`;
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
  // 저장 칸이 있으면 띠를 그 안으로, 없으면 화면 아래로 옮긴다 (새로 만들지 않아 낭독 안내를 되풀이하지 않는다)
  const slot = $('#app .savebar-slot');
  if (bar && slot && bar.parentElement !== slot) { slot.appendChild(bar); bar.classList.add('inline'); }
  else if (bar && !slot && bar.classList.contains('inline')) { document.body.appendChild(bar); bar.classList.remove('inline'); }
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
    + (text !== null ? `<span>${text}화 본문을 저장하지 않았어요 · <span id="draft-stamp" data-ep="${text}">${esc(draftStamp(text))}</span></span><button class="btn small primary" data-action="saveText" data-arg="${text}"${autoOn() ? ' disabled title="자동 집필이 도는 동안은 본문을 저장할 수 없어요"' : ' title="본문 저장 (Ctrl+S)"'}>본문 저장</button>` : '');
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

/** 페이지를 떠나면 사라지는 입력: 저장하지 않은 작품 · 문체 · 설정 변경, 본문 초안, 붙여 넣은 지시서 결과, 반영하지 않은 상태 변경안,
    분석 전 문체 예시 원문. 본문 초안은 브라우저에도 임시 보관하지만, 막힌 브라우저가 있어 여기서도 묻는다 */
function hasUnsaved() {
  return S.dirty || S.libDirty || S.settingsDirty
    || (S.styleSampleDirty && S.styleSample.trim() !== '')
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
      toast(`${rangeText(fin)}화의 반영을 취소했어요. ${n}화 변경안을 다시 골라 반영하세요`);
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
    const typed = prompt(`'${x.title || name}' 작품을 지울까요? 서버의 projects/.trash로 옮겨 두지만 화면에서는 되살릴 수 없어요.\n지우려면 작품 제목을 그대로 적으세요.`);
    if (typed === null) return;
    if (typed.trim() !== (x.title || name)) return toast('제목이 달라 지우지 않았어요', true);
    await run('지우는 중', async () => {
      await api('DELETE', `/projects/${enc(name)}`);
      S.projects = await api('GET', '/projects');
      toast('작품을 지웠어요. 서버의 projects/.trash에 남아 있어요');
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
  /** 브라우저에 임시 보관한 초안을 본문 칸에 되살린다. 저장은 '본문 저장'으로 한다. */
  restoreDraft(n) {
    const v = S.draftFound[n];
    if (!v) return;
    if (textUnsaved(n) && !confirm(`${n}화 칸에 쓰던 글이 있어요. 임시 보관한 초안으로 바꿀까요?`)) return;
    S.textDraft[n] = v.text;
    delete S.draftFound[n];
    draftKept.delete(DRAFT_PREFIX(S.name) + n);  // 이 탭이 이어 맡는다. 다음 보관 때 이 탭 것으로 다시 쓴다
    S.focusTarget = '#app textarea[data-draft]';
    render();
    toast(`${n}화 초안을 되살렸어요. 확인한 뒤 본문 저장을 누르세요`);
  },
  async copyFoundDraft(n) {
    const t = (S.draftFound[n] || {}).text || '';
    try {
      await navigator.clipboard.writeText(t);
    } catch {  // 보안 연결이 아니면 clipboard API 가 없다. 칸을 펼쳐 골라 복사한다
      const ta = $(`#found-${n}`);
      if (ta) { ta.closest('details').open = true; ta.select(); }
      if (!ta || !document.execCommand('copy')) return toast('브라우저가 복사를 막았어요. 펼친 칸에서 직접 골라 복사하세요', true);
    }
    toast(`${n}화 임시 보관한 초안을 복사했어요 (${t.length.toLocaleString()}자)`);
  },
  dropFoundDraft(n) {
    if (!confirm(`${n}화 임시 보관한 초안을 버릴까요? 되돌릴 수 없어요.`)) return;
    draftStore.del(DRAFT_PREFIX(S.name) + n);
    delete S.draftFound[n];
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

};
document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  e.preventDefault();
  if (el.getAttribute('aria-disabled') === 'true') return;  // 작업 중인 버튼: 포커스는 남기고 누르지는 못한다 (jobBtn)
  const fn = actions[el.dataset.action];
  const arg = el.dataset.arg;
  if (fn) fn(arg !== undefined && /^\d+$/.test(arg) ? Number(arg) : arg);
});

// ---------- 펼침 메뉴 · 대화상자 ----------

const CHEVRON = '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m3 4.5 3 3 3-3"></path></svg>';  // 메뉴 버튼의 ▾

/** 버튼 + 펼침 창(디자인 시스템 '펼침 버튼 + 패널'). 열린 메뉴는 S.popMenu 에 두어 화면을 다시 그려도 열려 있다.
    body 는 열렸을 때만 부르는 함수. 창 안 [data-action] 을 누르면 닫히고, 라디오 · 체크박스는 열어 둔다.
    role="menu" 는 쓰지 않는다: 창 안에 라디오 · 체크박스 · 나눔 버튼이 섞인다 */
function menuBtn(id, label, body, { cls = 'btn', aria = '', title = '', align = '' } = {}) {
  const open = S.popMenu === id;
  return `<div class="menu" data-menu="${id}"><button type="button" class="${cls}" aria-expanded="${open}" aria-controls="pop-${id}" data-action="menuToggle" data-arg="${id}"${aria ? ` aria-label="${esc(aria)}"` : ''}${title ? ` title="${esc(title)}"` : ''}>${label}</button>${open ? `<div class="pop-panel${align ? ` ${align}` : ''}" id="pop-${id}">${body()}</div>` : ''}</div>`;
}

function closeMenu(focus = false) {
  if (!S.popMenu) return;
  if (focus) S.focusTarget = `#app [data-action="menuToggle"][data-arg="${CSS.escape(S.popMenu)}"]`;
  S.popMenu = null;
  render();
}

// 바깥을 누르거나 창 안 동작을 누르면 닫는다. 동작보다 먼저 닫아 동작이 그리는 화면에 창이 남지 않게 capture 로 듣는다
document.addEventListener('click', (e) => {
  if (!S.popMenu || !e.target.closest) return;
  const mn = e.target.closest('[data-menu]');
  if (mn && mn.dataset.menu === S.popMenu && !e.target.closest('.pop-panel [data-action]')) return;
  if (e.target.closest('[data-action="menuToggle"]')) return;  // 다른 메뉴 버튼: menuToggle 이 바꾼다
  S.popMenu = null;
  setTimeout(render);
}, true);

// Esc 는 열린 메뉴를 먼저 닫고 메뉴 버튼으로 포커스를 돌린다. 대화 패널(chat.js)의 Esc 보다 먼저 받는다
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || e.isComposing || !S.popMenu) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  closeMenu(true);
}, true);

/** #app 밖의 <dialog>. 화면을 다시 그려도 열려 있다. 닫으면 열기 전 포커스로 돌아간다 (abilities.js abDialog 와 같은 방식).
    연 요소가 그사이 사라졌으면(메뉴 항목) back 선택자로 찾은 곳으로 */
function showDialog(id, html, back = '') {
  let el = document.getElementById(id);
  if (!el) {
    el = document.createElement('dialog');
    el.id = id;
    el.className = 'w-dialog';
    el.setAttribute('aria-labelledby', `${id}-title`);
    el.addEventListener('click', (e) => { if (e.target === el) el.close(); });  // 바깥(배경)을 누르면 닫는다
    document.body.appendChild(el);
  }
  const f = document.activeElement;
  const fid = el.contains(f) && f.id;  // 다시 채워도 고치던 칸에 포커스를 남긴다
  el.innerHTML = html;
  if (fid && document.getElementById(fid)) document.getElementById(fid).focus();
  if (!el.open) {
    const from = document.activeElement;
    el.onclose = () => {
      const to = from && from.isConnected ? from : back && document.querySelector(`#app ${back}`);
      if (to && to.focus) to.focus();
    };
    el.showModal();
  }
  return el;
}

Object.assign(actions, {
  menuToggle(id) {
    S.popMenu = S.popMenu === id ? null : id;
    render();
  },
  closeDialog(id) {
    const el = document.getElementById(id);
    if (el && el.open) el.close();
  },
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
  S.popMenu = null;
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
  if (parts[0] !== 'play' && typeof playStop === 'function') playStop();  // 플레이 화면을 떠나면 시계를 멈춘다
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
      if (!branchFam() || !parts[2] || parts[2] === 'branches') await branchLoad();
      if (!parts[2]) await playHomeLoad();  // 플레이 사본이면 작품 홈에 플레이로 돌아가는 카드 (play.js)  // 갈래 머리 띠 (branches.js). 작품을 바꿨거나 작품 홈 · 갈래 비교에 오면 다시 읽는다
      if (parts[2] === 'branches') await branchCompareLoad(parts[3], Number(parts[4]) || 0);
      scanDrafts();
      S.dirty = false;
      const n = Number(parts[3]);
      if (!parts[2] && S.project.relationships.length) {
        S.relations = await api('GET', `/projects/${enc(S.name)}/relations`).catch((e) => ({ error: e.message }));
      }
      if (parts[2] === 'setup') {
        S.names = {};
        S.ideas = {};
        S.dexRolls = null;
      }
      if (parts[2] === 'setup' || parts[2] === 'arc') {  // 화 플롯 페이지의 새 인물 칸도 이름 점검을 보인다
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
      if (parts[2] === 'arc' && parts[3]) {  // 홈의 아크 칩(arc/a3)은 그 아크를 고르고, 화 번호(arc/12)는 화 플롯 페이지를 연다
        const a = /^a\d+$/.test(parts[3]) ? Number(parts[3].slice(1)) : null;
        if (a) { S.selArc = a; S.selEp = null; S.selAct = null; }
        else if (n && ep(n)) {
          S.selEp = n;  // 대화 패널이 이 화를 대상으로 삼는다 (chat.js plotScope)
          S.selAct = null;
          S.editArc = false;
          S.selPart = null;
          const arc = serial() && S.project.story_arcs.find((x) => x.start_ep <= n && n <= x.end_ep);
          if (arc) S.selArc = arc.number;
        }
      } else if (parts[2] === 'arc') S.selEp = null;  // 보드로 돌아오면 대화 대상도 고른 아크로 돌아간다
      if (parts[2] === 'write' || parts[2] === 'arc' || parts[2] === 'check') await openingLoad(parts[2] === 'arc' ? 0 : (n || currentEp()));
      if (parts[2] === 'check') await checkLoad(n || currentEp());
      if (parts[2] === 'research') await rsLoad();
      if (parts[2] === 'usage') await usageLoad(S.name);
      if (parts[2] === 'convert') await convertLoad();
      if (parts[2] === 'cast') await castLoad(parts[3]);
      if (parts[2] === 'atlas') await atlasLoad();
      if (parts[2] === 'foreshadow') await fsLoad();
      if (parts[2] === 'statwin') await swLoad(parts[3]);
      if (parts[2] === 'abilities') await abLoad(parts[3]);
      if (parts[2] === 'setup' && parts[3]) {  // 인물 화면의 '기본 설정 고치기'(setup/<인물 id>)는 그 인물 카드로 간다
        const i = S.project.characters.findIndex((c) => c.id === parts[3]);
        if (i >= 0) S.focusTarget = S.jumpTo = `#f-characters-${i}-name`;
      } else if (parts[2] === 'setup' && S.jumpTo) S.focusTarget = S.jumpTo;  // 명령 팔레트에서 고른 설정 칸 (palette.js)
      if (parts[2] === 'causal') {
        if (parts[3]) S.causalSel = parts[3];
        await causalLoad();
      }
      if (typeof autoLoad === 'function') await autoLoad(parts[2] === 'auto');
      if (parts[2] === 'brief' && n && ep(n)) {
        S.briefTab = briefTabFor(n);
        S.briefText = await api('GET', `/projects/${enc(S.name)}/episodes/${n}/brief?kind=${S.briefTab}`).then((r) => r.text).catch((e) => '※ ' + e.message);
      }
    } else if (parts[0] === 'play') {  // 플레이 모드 (play.js): 플레이 사본은 작품 화면과 따로 그린다
      S.name = null;
      S.project = null;
      await playLoad(parts);
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
  const jumped = S.jumpTo && document.querySelector(S.jumpTo);
  const card = jumped && jumped.closest('.char-card');  // 맨 위로 간 뒤 고른 카드로 내려가 잠시 테두리를 보인다
  S.jumpTo = null;
  if (card) {
    card.classList.add('jump');
    card.scrollIntoView({ block: 'start' });
    setTimeout(() => card.classList.remove('jump'), 2000);
  } else if (jumped) jumped.scrollIntoView({ block: 'center' });  // 카드 밖 설정 칸: 맨 위로 간 화면을 그 칸으로 내린다
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
  renderSavebar();  // 저장 칸이 생기거나 사라졌을 수 있다
  stackBottom();  // 반영 줄(.apply-bar)이 생기거나 사라졌을 수 있다
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
  document.title = pageTitle();
  // 탭 묶음: 고른 탭만 Tab 으로 들어가고 나머지는 화살표로 옮긴다 (아래 keydown)
  document.querySelectorAll('#app [role="tablist"]').forEach((list) => {
    const tabs = [...list.querySelectorAll('[role="tab"]')];
    const sel = tabs.find((t) => t.getAttribute('aria-selected') === 'true') || tabs[0];
    tabs.forEach((t) => { t.tabIndex = t === sel ? 0 : -1; });
  });
  const want = S.focusTarget;
  S.focusTarget = null;
  const target = want && document.querySelector(want);
  // 정한 대상이 접힌 칸(details) 안에 있으면 펴고 옮긴다 (명령 팔레트의 설정 칸, 인물 카드의 '더 자세히')
  for (let d = target && target.parentElement && target.parentElement.closest('details'); d; d = d.parentElement && d.parentElement.closest('details')) d.open = true;
  if (target && focusEl(target)) return;
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
  // 버튼 줄 안의 저장 칸(.savebar-slot)에 든 띠는 다시 그리면 함께 사라진다. 잠시 밖으로 빼 두었다가 그린 뒤 새 칸으로 옮긴다 (render)
  const inline = $('#savebar.inline');
  if (inline) document.body.appendChild(inline);
  document.body.classList.remove('chat-open');
  const [p, , page, arg] = S.route;
  if (p === 'settings') {
    $('#app').innerHTML = `<div class="shell"><main class="main" style="max-width:820px;margin:0 auto">${viewSettings()}</main></div>`;
    syncProviderGroups();  // 쓰지 않는 백엔드의 칸 묶음을 숨긴다 (settings.js)
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
  if (p === 'play') {
    $('#app').innerHTML = viewPlayRoute();
    playAfterDraw();
    return;
  }
  if (p !== 'p' || !P()) {
    $('#app').innerHTML = `<div class="shell"><main class="main" style="max-width:1080px;margin:0 auto">${viewProjects()}</main></div>`;
    return;
  }
  const n = Number(arg) || currentEp();
  const views = { setup: viewSetup, style: viewStyle, arc: () => (plotPageN() ? viewPlotPage(plotPageN()) : serial() ? viewSerial() : viewArc()), write: viewWrite, check: viewCheck, review: viewReview, brief: viewBrief, research: viewResearch, usage: viewUsage, auto: viewAuto, causal: viewCausal, lines: viewLines, cast: viewCast, atlas: viewAtlas, convert: viewConvert, foreshadow: viewForeshadow, tofix: viewToFix, statwin: viewStatwin, abilities: viewAbilities, timeline: viewTimeline, branches: viewBranches };
  const body = (views[page] || viewHome)(n);
  $('#app').innerHTML = `<div class="shell">${sidebar(page || 'home')}<main class="main">${branchStrip(page)}${failStrip(page, n)}${draftStrip(page, n)}${body}</main></div>`;
  syncPending();
  keepDrafts();  // 저장 · 버리기 · AI 본문으로 초안이 사라졌으면 임시본도 바로 지운다
  syncChat();
  if (typeof syncPassage === 'function') syncPassage();
  if (typeof syncIllust === 'function') syncIllust();
  if (typeof syncMarks === 'function') syncMarks();
  if (typeof syncWriteTop === 'function') syncWriteTop();
  if (typeof syncLines === 'function') syncLines();
  document.querySelectorAll('textarea[data-autogrow]').forEach(autosize);
  // 상태 승인 지시서 탭이 바뀌면 다시 불러온다
  if (page === 'brief' && S.briefText === null && ep(n)) {
    api('GET', `/projects/${enc(S.name)}/episodes/${n}/brief?kind=${S.briefTab}`)
      .then((r) => r.text).catch((e) => '※ ' + e.message)
      .then((t) => { S.briefText = t; render(); });
  }
}

/** 작업 단계 1~6 의 이름. 사이드바 · 작품 홈 진행 카드 · 단계 화면 제목이 이 이름을 쓴다 (장편은 3단계 이름이 다르다) */
function stepLabel(id) {
  return { setup: '설정 도우미', style: '문체 레퍼런스', arc: serial() ? '부 · 아크 · 플롯' : '기승전결 · 플롯', write: '집필', check: '검수', review: '상태 승인' }[id];
}

/** 사이드바 '더 보기' 펼침. 화면을 다시 그려도 남게 브라우저에 둔다. */
function navMoreOpen() {
  try { return localStorage.getItem('canon.navMore') === '1'; } catch { return false; }
}
// 사람이 머리를 눌러 바꾼 것만 기억한다 (지금 보는 도구라 펼쳐 그린 것은 기억하지 않는다). 펼침은 클릭 기본 동작 뒤에 읽는다
document.addEventListener('click', (e) => {
  const d = e.target.closest && e.target.closest('[data-nav-more] > summary') && e.target.closest('[data-nav-more]');
  if (!d) return;
  setTimeout(() => {
    try { localStorage.setItem('canon.navMore', d.open ? '1' : '0'); } catch { /* 저장소를 막은 브라우저: 이번 화면에서만 펼친다 */ }
  });
});

/** 사이드바 항목. palette.js 의 명령 팔레트도 같은 이름 · 주소를 쓴다.
    steps: 작품 홈과 단계 [id, 주소, 기호, 이름], auto: 자동 집필, tools: 작품 도구 [..., 데이터가 있는지],
    apart: 본편과 분리한 화면, foot: 사이드바 아래 링크 [주소, 이름]. */
function navItems() {
  const p = P();
  const cur = currentEp();
  // 번호는 작업 순서(1~6)에만 붙인다. 도구는 어느 단계에서든 쓰므로 번호 없이 아래 묶음에 둔다
  // 기호는 단계 번호이거나 토스페이스 이모지 아이콘이다 (navMark 가 그린다)
  const steps = [
    ['home', base(), '🏠', '작품 홈'],
    ['setup', base() + '/setup', '1', stepLabel('setup')],
    ['style', base() + '/style', '2', stepLabel('style')],
    ['arc', base() + '/arc', '3', stepLabel('arc')],
    ['write', `${base()}/write/${cur}`, '4', stepLabel('write')],
    ['check', `${base()}/check/${cur}`, '5', stepLabel('check')],
    ['review', `${base()}/review/${cur}`, '6', stepLabel('review')],
  ];
  // 도구마다 [id, 주소, 기호, 이름, 데이터가 있는지]. 데이터가 없는 도구는 '더 보기'로 접는다 (지금 보는 도구는 펼쳐 둔다)
  const has = (xs) => (xs || []).length > 0;
  const tools = [
    ['cast', base() + '/cast', '👥', '인물 · 관계도', has(p.characters)],
    ['atlas', base() + '/atlas', '🗺️', '지도', has(p.world.locations) || (p.elements || []).some((el) => el.kind === '장소')],
    ['foreshadow', base() + '/foreshadow', '🪝', '복선 센터', has(p.foreshadows)],
    ['tofix', base() + '/tofix', '📌', '고칠 곳', p.episodes.some((e) => has(e.to_fix))],
    ['statwin', base() + '/statwin', '📊', '상태창 수치', (p.states || []).some((s) => has(s.stats)) || has((p.stat_window || {}).names)],
    ['abilities', base() + '/abilities', '📖', '스킬 도감', has(p.abilities)],
    ['timeline', base() + '/timeline', '⏳', '작품 속 시간', has((p.timeline || {}).deadlines) || p.episodes.some((e) => e.time && (e.time.day > 0 || e.time.part || e.time.label))],
    ['lines', base() + '/lines', '🔀', '이야기 줄기', has(p.storylines)],
    ['causal', base() + '/causal', '🔗', '인과율', has(p.elements)],
    ['branches', base() + '/branches', '🌿', '갈래 비교', (branchFam() || { members: [] }).members.length > 1],
    ['brief', `${base()}/brief/${cur}`, '📝', '작업지시서 (API 없이)', true],
  ];
  return {
    steps,
    auto: ['auto', base() + '/auto', '🤖', autoMenuLabel()],
    tools,
    apart: [['research', base() + '/research', '🔬', '연구 · 모델 실험'], ['usage', base() + '/usage', '💰', '사용량 · 비용']],
    foot: [['#/settings', '모델 · API 키 설정'], ['#/usage', '모든 작품 사용량 · 비용'], ['#/styles', '문체 라이브러리'], ['#/', '작품 목록']],
  };
}

/** 사이드바 앞 기호: 단계 번호는 글자 칸, 그 밖은 토스페이스 이모지 아이콘 (원본 그대로, 낭독은 이름으로 충분해 숨긴다) */
function navMark(mark) {
  return /\p{Extended_Pictographic}/u.test(mark) ? `<span class="num tf" aria-hidden="true">${mark}</span>` : `<span class="num" aria-hidden="true">${mark}</span>`;
}

/** 화 칸 띠에 그릴 수 있는 가장 많은 화. 넘으면 칸이 너무 얇아 막대로 그린다 */
const WORK_STRIP_MAX = 40;

/** 사이드바 작품 칸: 제목(작품 홈) · 작품 목록, 장르, 갈래, 장편은 지금 부 · 아크, 화마다 한 칸인 띠(장편은 지금 아크만),
    반영한 화 수, 다음 할 일(home.js nextStep). 900px 이하와 대화 패널을 연 때는 app.css 가 위쪽 띠 한 줄로 줄인다. */
function workCard() {
  const p = P();
  const done = p.episodes.filter((e) => e.status === 'finalized').length;
  const total = p.meta.target_episodes;
  const cur = currentEp();
  const part = serial() ? p.parts.find((x) => x.start_ep <= cur && cur <= x.end_ep) : null;
  const arc = serial() ? arcOf(cur) : null;
  const [lo, hi] = arc ? [arc.start_ep, arc.end_ep] : [1, total];
  const n = hi - lo + 1;
  const cell = (k) => {
    const e = ep(k);
    return `<i class="${e ? e.status : 'none'}${k === cur ? ' cur' : ''}" title="${k}화 · ${e ? STATUS[e.status] : '플롯 없음'}"></i>`;
  };
  const cells = n > 0 && n <= WORK_STRIP_MAX && (!!arc || !serial());
  const strip = cells
    ? `<div class="work-strip" style="--n:${n}" aria-hidden="true">${Array.from({ length: n }, (_, i) => cell(lo + i)).join('')}</div>`
    : `<div class="meter" aria-hidden="true"><i style="left:0;width:${Math.round((done / Math.max(total, 1)) * 100)}%;background:var(--green)"></i></div>`;
  const where = [part && `<b>${part.number}부</b> ${esc(part.title)}`, arc && `<b>아크 ${arc.number}</b> ${esc(arc.title)}`].filter(Boolean).join(' · ');
  const whereFull = [part && `${part.number}부 ${part.title}`, arc && `아크 ${arc.number} ${arc.title}`].filter(Boolean).join(' · ');  // 두 줄로 자른 부 · 아크 줄의 전체 글
  const [nextLabel, nextHref] = nextStep();
  return `<div class="work-card">
      <div class="work-head"><a class="work-title" href="${base()}">${esc(p.meta.title || S.name)}</a><a class="work-switch" href="#/" title="작품 목록" aria-label="다른 작품 고르기 (작품 목록)">⌄</a></div>
      <div class="small work-meta">${esc(p.meta.genre || '장르 미정')} · ${serial() ? '장편' : '단편'} ${total}화</div>${branchSideTag()}
      ${where ? `<div class="work-where" title="${esc(whereFull)}">${where}</div>` : ''}
      ${strip}
      <div class="small work-count" aria-hidden="true">${done}/${total}화</div>
      <div class="small work-scale"><span aria-hidden="true">${cells ? `${lo}화` : ''}</span><span>${done} / ${total}화 반영</span><span aria-hidden="true">${cells ? `${hi}화` : ''}</span></div>
      <a class="work-next" href="${nextHref}"><span class="sr-only">다음 할 일: </span>${esc(nextLabel)}<span aria-hidden="true">→</span></a>
    </div>`;
}

function sidebar(active) {
  const { steps, auto, tools, apart, foot } = navItems();
  const link = ([id, href, num, label]) => `<a href="${href}"${id === active ? ' aria-current="page"' : ''}>${navMark(num)}${label}</a>`;
  const shown = tools.filter((t) => t[4]);
  const folded = tools.filter((t) => !t[4]);
  const moreOpen = folded.some((t) => t[0] === active) || navMoreOpen();
  const cfg = S.config || {};
  return `<nav class="side${S.menuOpen ? ' open' : ''}" aria-label="작품 메뉴">
    <a class="brand" href="#/">Canon<span class="brand-dot" aria-hidden="true">.</span></a>
    <button type="button" class="btn small menu-toggle pal-open" data-action="openPalette" aria-haspopup="dialog">찾기</button>
    <button type="button" class="btn small menu-toggle" data-action="toggleMenu" aria-expanded="${!!S.menuOpen}" aria-controls="side-menu">메뉴</button>
    ${workCard()}
    <div class="side-menu" id="side-menu">
    <div class="nav">${steps.map(([id, href, num, label]) => `<a href="${href}"${id === active ? ' aria-current="page"' : ''}>${navMark(num)}${label}${/\d/.test(num) ? `<span class="sr-only"> (단계 ${num})</span>` : ''}</a>`).join('')}</div>
    <div class="nav nav-auto">${link(auto)}</div>
    <div class="nav nav-extra"><span class="small">작품 도구</span>${shown.map(link).join('')}
      ${folded.length ? `<details class="nav-more" data-nav-more${moreOpen ? ' open' : ''}><summary>더 보기 <span class="small">아직 데이터가 없는 도구 ${folded.length}개</span></summary>${folded.map(link).join('')}</details>` : ''}</div>
    <div class="nav nav-extra"><span class="small">본편과 분리</span>${apart.map(link).join('')}</div>
    <div class="side-foot">
      <span class="small">본문 모델</span>
      <strong style="font-size:0.8125rem">${esc(cfg.stages ? cfg.stages.write.model : cfg.model || '')}</strong>
      ${aiWarning() ? `<span style="color:var(--red)">${esc(aiWarning())}</span>` : ''}
      ${foot.map(([href, label]) => `<a href="${href}">${label}</a>`).join('\n      ')}
      <span class="tf-credit">이 페이지에는 토스팀에서 제공한 <a href="https://toss.im/tossface" target="_blank" rel="noopener">토스페이스</a>가 적용되어 있어요.</span>
    </div>
    </div>
  </nav>`;
}

function header(eyebrow, title, desc, right = '') {
  return `<header class="page-head"><div class="lead"><div class="eyebrow">${eyebrow}</div><h1>${esc(title)}</h1>${desc ? `<p class="desc">${desc}</p>` : ''}</div><div class="row">${right}</div></header>`;
}

// 화면 파일(setup.js 등)이 모두 실행된 뒤 첫 화면을 그린다
document.addEventListener('DOMContentLoaded', () => {
  route();
  pollJobs();
});

/* 연구 · 모델 실험 화면. app.js 의 S, actions, api, render, input, header 와 outline.js 의 목차 틀을 쓴다. */
'use strict';

// ---------- 연구 (모델 실험) ----------
// 본편 데이터와 분리된 실험실. 결과는 projects/<이름>/research/log.jsonl 에 남고,
// 블라인드 비교에서 채택할 때만 작품 본문이 바뀐다.
// 화면은 왼쪽 목차(개요 · 실험마다 한 쪽 · 기록) + 오른쪽 카드 한 열이다. 주소는 #/p/<이름>/research[/<쪽>].
// 실험 쪽은 설정 카드 · 결과 카드 · 지난 기록이고, 지난 기록을 열면 그 결과를 같은 카드에 다시 그린다.

// 실험 쪽: 열쇠, 이름, 묶음, 개요 카드의 묻는 말, 머리 설명
const RS_SECS = [
  { k: 'probe', label: '서버 점검', group: '준비', q: '로컬 서버에 어떤 모델이 있고 컨텍스트가 얼마인지 봐요',
    desc: 'OpenAI 호환 서버(vLLM, Ollama, llama.cpp, LM Studio)의 모델 목록과 컨텍스트 길이를 봐요. 생성 호출은 하지 않아요.' },
  { k: 'sample', label: '샘플 생성', group: '실험', q: '같은 요청을 모델마다 어떻게 쓰는지 봐요',
    desc: '같은 요청을 여러 백엔드에 차례로 보내 시간, 토큰, 문체 지표를 나란히 봐요. 작품 데이터는 쓰지 않아요.' },
  { k: 'stage', label: '단계 시험', group: '실험', q: '모델이 설정 · 문체 · 기승전결 형식을 지키는지 봐요',
    desc: '설정 제안, 문체 분석, 기승전결을 저장하지 않고 돌려 봐요. 건너뛴 칸, 범위를 벗어난 숫자, 다시 물은 횟수를 확인해요.' },
  { k: 'budget', label: '컨텍스트 크기', group: '실험', q: '몇 화부터 프롬프트가 모델 한도를 넘는지 봐요',
    desc: '화마다 본문 쓰기, 검수, 상태 변경안 프롬프트 크기를 모델의 컨텍스트 한도와 견줘요. 생성 호출은 하지 않아요.' },
  { k: 'check', label: '검수 시험', group: '실험', q: '검수가 심어 둔 모순을 찾는지 봐요',
    desc: '본문이 있는 화에 모순을 심고, 검수 방식마다 그걸 찾는지 봐요. 작품에는 저장하지 않아요.' },
  { k: 'compare', label: '블라인드 비교', group: '실험', q: '가려 놓고 읽으면 어느 모델 글이 나은지 봐요',
    desc: '같은 화를 두 백엔드로 쓰고 1, 2번으로 가려요. 읽고 고르면 어느 쪽이었는지 공개해요. 프롬프트는 집필 화면과 같아요.' },
  { k: 'stattrial', label: '상태창 시험', group: '실험', q: '상태창 수치를 어떤 방식으로 넣어야 덜 틀리는지 봐요',
    desc: '같은 화를 상태창 수치를 넣는 방식만 바꿔 다시 써서 견줘요. 화마다 그 화를 쓰기 직전 사본에서 쓰고, 작품은 바꾸지 않아요.' },
];
const RS_SEC = Object.fromEntries(RS_SECS.map((s) => [s.k, s]));
const RS_KIND = { sample: '샘플 생성', stage: '단계 시험', budget: '컨텍스트 크기', check: '검수 시험', compare: '블라인드 비교', pick: '비교 고르기', cue: '큐 시트 실험', statwin: '상태창 시험' };
// 기록 갈래(kind) → 그 결과를 여는 실험 쪽. 큐 시트 실험은 그 화면이 따로 있다
const RS_OF = { sample: 'sample', stage: 'stage', budget: 'budget', check: 'check', compare: 'compare', pick: 'compare', statwin: 'stattrial' };

function rsInit(name) {
  const c = S.config || {};
  const backend = () => ({ provider: c.provider === 'mock' ? 'mock' : 'local', model: '', url: '' });  // 모델 · 주소가 비면 설정값 (칩 '설정값'과 같다)
  // 비교 A 는 설정의 본문 쓰기 백엔드, B 는 그와 다른 백엔드 (같으면 서버가 거절한다)
  const writeProv = ((c.stages || {}).write || {}).provider || c.provider || 'gemini';
  const cmpA = { provider: ['gemini', 'local', 'mock'].includes(writeProv) ? writeProv : 'gemini', model: '', url: '' };
  const cmpB = { provider: cmpA.provider === 'local' ? 'gemini' : 'local', model: '', url: '' };
  S.rs = {
    name, tab: 'home', log: [], latest: {}, openCmp: [], stages: {}, probe: null, probeUrl: c.local_url || '',
    runs: [backend()], system: '너는 한국어 소설가다.', prompt: '', temperature: '',
    stageBackend: backend(), stage: 'style', stageText: '',
    budgetBackend: backend(),
    checkBackend: backend(), checkEp: null, checkPlants: 3, checkModes: {},
    checkJudge: backend(), checkTwoStep: false, checkStage: false,
    compareEp: null, compareA: cmpA, compareB: cmpB, compare: null, adopt: true, pickResult: null, probeError: null,
    cur: {},     // 쪽마다 이 화면에서 방금 돌린 결과 (컨텍스트 크기는 기록보다 자세하다)
    open: {},    // 쪽마다 지난 기록에서 연 결과 id
    custom: {},  // 백엔드 칸을 직접 적는 중인 자리
  };
}

async function rsLoadLog() {
  const r = await api('GET', `/projects/${enc(S.name)}/research`);
  S.rs.log = r.log;
  S.rs.latest = r.latest || {};
  S.rs.openCmp = r.open_compares || [];
  S.rs.stages = r.stages;
  S.rs.checkModes = r.check_modes || {};
  S.rs.checkTotals = r.check_totals || [];
}

/** 주소의 쪽(sec)을 연다. 비우거나 모르는 쪽이면 개요 */
async function rsLoad(sec) {
  if (!S.rs || S.rs.name !== S.name) rsInit(S.name);
  S.rs.tab = RS_SEC[sec] || sec === 'log' ? sec : 'home';
  await rsLoadLog();
  if (S.rs.compareEp == null) S.rs.compareEp = (S.rs.openCmp[0] || {}).episode || currentEp();
  S.rs.compare = (await api('GET', `/projects/${enc(S.name)}/research/compare/${S.rs.compareEp}`)).compare;
  if (S.rs.tab === 'stattrial') await stLoad();  // static/stattrial.js
}

document.addEventListener('input', (e) => {
  const el = e.target;
  if (!el.dataset.rs || !S.rs) return;
  setPath(S.rs, el.dataset.rs, el.type === 'checkbox' ? el.checked : el.value);
});

const rsUrl = (sec) => `${base()}/research${sec && sec !== 'home' ? `/${sec}` : ''}`;
const rsBackend = (b) => ({ provider: b.provider, model: (b.model || '').trim(), url: (b.url || '').trim() });
const rsLabel = (b) => (b.model ? `${b.provider}:${b.model}` : b.provider);
const rsKey = (b) => `${b.provider}|${(b.model || '').trim()}|${(b.url || '').trim()}`;
const rsNum = (v, d = 0) => (v == null ? '-' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
const RS_PROV = { gemini: 'Gemini', local: '로컬', mock: 'mock' };

/** 기록의 백엔드 이름('local:qwen3-32b', 'gemini')을 백엔드로 */
function rsParse(label) {
  const s = String(label || '');
  const i = s.indexOf(':');
  const provider = i < 0 ? s : s.slice(0, i);
  return RS_PROV[provider] ? { provider, model: i < 0 ? '' : s.slice(i + 1), url: '' } : null;
}

/** 고를 수 있는 백엔드 칩: 설정값 · 서버 점검에서 본 모델 · 기록에 남은 백엔드. 같은 것은 한 번만. 순수 함수(tests/test_research_js.py) */
function rsCands({ config = {}, probe = null, probeUrl = '', log = [], kinds = ['gemini', 'local', 'mock'] } = {}) {
  const out = [];
  const add = (b, sub) => {
    if (!b || !kinds.includes(b.provider) || out.some((x) => rsKey(x.b) === rsKey(b))) return;
    out.push({ b: { provider: b.provider, model: b.model || '', url: b.url || '' }, sub });
  };
  if (config.provider === 'mock') add({ provider: 'mock' }, 'mock · 가짜 응답');
  add({ provider: 'gemini' }, `Gemini · 설정값${config.model_setting ? ` ${config.model_setting}` : ''}`);
  add({ provider: 'local' }, `로컬 · 설정값${config.local_model ? ` ${config.local_model}` : ''}`);
  const url = probeUrl.trim() === (config.local_url || '') ? '' : probeUrl.trim();
  ((probe || {}).models || []).forEach((m) => add({ provider: 'local', model: m.id, url }, '로컬 · 서버 점검에서'));
  log.forEach((x) => {
    const labels = [x.backend, ...(x.backends || []), ...((x.rows || []).map((r) => r.backend))];
    labels.forEach((l) => add(rsParse(l), '기록에서'));
  });
  return out;
}

const rsCandsNow = (path) => rsCands({ config: S.config || {}, probe: S.rs.probe, probeUrl: S.rs.probeUrl, log: S.rs.log,
  kinds: path === 'checkJudge' ? ['local', 'mock'] : undefined });

/** 칩 글: 모델 이름, 설정값이면 설정의 모델 이름 */
function rsName(b) {
  const c = S.config || {};
  if (b.model) return b.model;
  if (b.provider === 'gemini') return c.model_setting || 'Gemini';
  if (b.provider === 'local') return c.local_model || '로컬 서버';
  return 'mock';
}

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

/** 백엔드 고르기: 칩 하나를 고르고, 칩에 없는 백엔드는 '+ 다른 백엔드 적기'로 칸을 편다 */
function rsPicker(path, label, hint = '') {
  const cands = rsCandsNow(path);
  const cur = getPath(S.rs, path);
  const hit = cands.some((c) => rsKey(c.b) === rsKey(cur));
  const custom = !!S.rs.custom[path] || !hit;
  const chips = cands.map((c, i) => `<button type="button" class="rs-pick" aria-pressed="${!custom && rsKey(c.b) === rsKey(cur)}" data-action="rsPick" data-arg="${path}|${i}"><span class="tl">${esc(rsName(c.b))}</span><span class="s">${esc(c.sub)}</span></button>`).join('');
  const kinds = path === 'checkJudge' ? [['local', '로컬 서버'], ['mock', 'mock']] : undefined;
  return `<div class="field"><span class="label" id="${path}-lb">${label}${hint ? ` <span class="hint">${hint}</span>` : ''}</span>
    <div class="rs-picks" role="group" aria-labelledby="${path}-lb">${chips}<button type="button" class="rs-pick add" aria-pressed="${custom}" data-action="rsCustom" data-arg="${path}">+ 다른 백엔드 적기</button></div>
    ${custom ? rsBackendFields(path, cur, kinds) : ''}</div>`;
}

/** 샘플 생성의 백엔드 여럿: 칩을 켜고 끄고, 칩에 없는 백엔드는 줄마다 칸 */
function rsMultiPicker() {
  const cands = rsCandsNow('runs');
  const on = (b) => S.rs.runs.some((x) => !x.own && rsKey(x) === rsKey(b));
  const chips = cands.map((c, i) => `<button type="button" class="rs-pick" aria-pressed="${on(c.b)}" data-action="rsToggleRun" data-arg="${i}"><span class="tl">${esc(rsName(c.b))}</span><span class="s">${esc(c.sub)}</span></button>`).join('');
  // 직접 적는 줄(own)과 칩에 없는 백엔드는 줄마다 칸을 둔다
  const extra = S.rs.runs.map((b, i) => [b, i]).filter(([b]) => b.own || !cands.some((c) => rsKey(c.b) === rsKey(b)));
  return `<div class="field"><span class="label" id="rs-runs-lb">백엔드 <span class="hint">${S.rs.runs.length}개 골랐어요 · 차례로 보내요</span></span>
    <div class="rs-picks" role="group" aria-labelledby="rs-runs-lb">${chips}<button type="button" class="rs-pick add" data-action="rsAddRun">+ 백엔드 더하기</button></div>
    ${extra.map(([b, i]) => `<div class="rs-extra">${rsBackendFields(`runs.${i}`, b)}<button type="button" class="btn icon-btn" data-action="rsRemoveRun" data-arg="${i}" aria-label="백엔드 ${i + 1} 빼기">✕</button></div>`).join('')}</div>`;
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

// ----- 기록 한 줄과 마지막 결과 -----

/** 기록 한 줄 요약 */
function rsLogLine(x, stages = {}) {
  if (x.kind === 'sample') return (x.rows || []).map((r) => `${r.backend} ${r.ok ? `${rsNum(r.chars)}자 ${r.seconds}초` : '실패'}`).join(' · ');
  if (x.kind === 'stage') return `${stages[x.stage] || x.stage} · ${x.backend} · ${x.ok ? `빈 칸 ${x.empty.length}/${x.fields}, 범위 밖 ${x.out_of_range.length}, 시도 ${x.attempts}번` : '실패'} · ${x.seconds}초`;
  if (x.kind === 'budget') return `${x.backend} · 한도 ${x.limit ? rsNum(x.limit) : '알 수 없음'} · ${x.first_over ? `${x.first_over}화부터 넘침` : x.first_tight ? `${x.first_tight}화부터 빠듯함` : '넘침 없음'}`;
  if (x.kind === 'compare') return `${x.episode}화 · ${(x.backends || []).join(' · ')}`;
  if (x.kind === 'check') return `${x.episode}화 · ${x.backend} · ${(x.runs || []).map((m) => `${m.mode} ${m.ok ? `${m.found}/${(x.planted || []).length}` : '실패'}`).join(' · ')}`;
  if (x.kind === 'cue') return `${x.episode}화 · 큐 ${x.cues}개 · ${(x.summary || []).map((s) => `${s.label} ${rsNum(s.chars)}자`).join(' · ')}`;
  if (x.kind === 'pick') return `${x.episode}화 · ${x.picked} 고름${x.adopted ? ' (본문 채택)' : ''}`;
  if (x.kind === 'statwin') return `${(x.episodes || []).join(' · ')}화 × ${(x.summary || []).length}방식 · 틀린 값 ${(x.summary || []).map((s) => (s.error_rate == null ? '-' : `${Math.round(s.error_rate * 100)}%`)).join(' · ')}`;
  return '';
}

/** 쪽마다 마지막 결과의 짧은 말: { st: 목차 꼬리, chip: [클래스, 글], line: 개요 카드 줄, warn }. 순수 함수(tests/test_research_js.py) */
function rsBrief(k, { latest = {}, openCmp = [], probe = null, probeError = null, stages = {}, when = (t) => t } = {}) {
  const x = latest[k];
  if (k === 'probe') {
    if (probeError) return { st: '연결 안 됨', chip: ['bad', '연결 안 됨'], line: probeError, warn: true };
    if (probe) return { st: '연결됨', chip: ['ok', '연결됨'], line: `${probe.server || '서버'} · 모델 ${probe.models.length}개`, warn: false };
    return { st: '', chip: null, line: '점검 결과는 이 화면을 연 동안만 남아요', warn: false };
  }
  if (k === 'compare' && openCmp.length) {
    return { st: '고르기', chip: ['warn', '고르기 대기'], line: `${openCmp.map((c) => c.episode).join(' · ')}화 비교본을 아직 고르지 않았어요`, warn: true };
  }
  const y = k === 'compare' ? [latest.compare, latest.pick].filter(Boolean).sort((a, b) => (a.time < b.time ? 1 : -1))[0]
    : k === 'stattrial' ? latest.statwin : x;
  if (!y) return { st: '', chip: null, line: '아직 없어요', warn: false };
  const at = when(y.time);
  const day = String(at).replace(/ \d\d:\d\d$/, '');  // 목차 꼬리는 날만: '오늘' · '10.28'
  if (k === 'budget') {
    if (y.first_over) return { st: `${y.first_over}화 넘침`, chip: ['bad', `${y.first_over}화부터 넘침`], line: `${at} · ${y.backend}`, warn: true };
    if (y.first_tight) return { st: `${y.first_tight}화 빠듯`, chip: ['warn', `${y.first_tight}화부터 빠듯함`], line: `${at} · ${y.backend}`, warn: false };
    return { st: day, chip: ['ok', y.limit ? '넘침 없음' : '한도 모름'], line: `${at} · ${y.backend}`, warn: false };
  }
  if (k === 'check') {
    const runs = (y.runs || []).filter((m) => m.ok);
    const n = (y.planted || []).length * runs.length;
    const found = runs.reduce((a, m) => a + m.found, 0);
    return { st: `${found}/${n}`, chip: [found === n ? 'ok' : 'warn', `${found}/${n} 찾음`], line: `${at} · ${y.episode}화 · ${runs.map((m) => m.mode).join(' · ')}`, warn: false };
  }
  if (k === 'sample') {
    const fail = (y.rows || []).filter((r) => !r.ok).length;
    return { st: day, chip: fail ? ['bad', `실패 ${fail}`] : null, line: `${at} · 백엔드 ${(y.rows || []).length}개`, warn: false };
  }
  if (k === 'stage') {
    const chip = !y.ok ? ['bad', '실패'] : y.empty.length ? ['warn', `빈 칸 ${y.empty.length}`] : ['ok', '모두 채움'];
    return { st: day, chip, line: `${at} · ${stages[y.stage] || y.stage} · 시도 ${y.attempts || 1}번`, warn: false };
  }
  if (k === 'compare') return { st: day, chip: null, line: `${at} · ${rsLogLine(y)}`, warn: false };
  if (k === 'stattrial') return { st: day, chip: null, line: `${at} · ${rsLogLine(y)}`, warn: false };
  return { st: day, chip: null, line: at, warn: false };
}

const rsBriefNow = (k) => rsBrief(k, { latest: S.rs.latest, openCmp: S.rs.openCmp, probe: S.rs.probe, probeError: S.rs.probeError, stages: S.rs.stages, when: fmtWhen });

/** 쪽에 보일 결과: 지난 기록에서 연 것 → 이 화면에서 방금 돌린 것 → 그 갈래의 마지막 기록 */
function rsEntry(sec) {
  const id = S.rs.open[sec];
  const pool = [...S.rs.log, ...Object.values(S.rs.latest)];
  if (id) {
    const x = (S.rs.cur[sec] && S.rs.cur[sec].id === id) ? S.rs.cur[sec] : pool.find((e) => e.id === id);
    if (x) return x;
  }
  if (S.rs.cur[sec]) return S.rs.cur[sec];
  return S.rs.latest[sec] || null;
}

/** 쪽의 지난 기록 목록 (최근 30개 기록 + 갈래마다 마지막 기록) */
function rsPast(sec, kinds = [sec]) {
  const seen = new Set();
  const all = [...S.rs.log, ...kinds.map((k) => S.rs.latest[k]).filter(Boolean)]
    .filter((x) => kinds.includes(x.kind) && !seen.has(x.id) && seen.add(x.id))
    .sort((a, b) => (a.time < b.time ? 1 : -1)).slice(0, 8);
  if (!all.length) return '';
  const shown = sec === 'compare' ? S.rs.open.compare : (rsEntry(sec) || {}).id;  // 비교는 화마다 비교본이 따로 있어 연 기록만 표시한다
  const rows = all.map((x) => `<div class="rs-row"><span class="when">${esc(fmtWhen(x.time))}</span><span class="tl">${esc(rsLogLine(x, S.rs.stages))}</span>
    ${x.id === shown ? '<span class="chip ai">보는 중</span>' : `<button type="button" class="btn small ghost" data-action="rsOpen" data-arg="${sec}|${esc(x.id)}">열기</button>`}</div>`).join('');
  return `<section class="card" aria-labelledby="rs-past-h"><h2 id="rs-past-h">지난 ${RS_SEC[sec].label}</h2><div class="rs-rows">${rows}</div></section>`;
}

// ----- 쪽마다 설정 · 결과 -----

function rsProbeView() {
  const r = S.rs.probe;
  const rows = r ? r.models.map((m) => `<tr><td class="mono">${esc(m.id)}</td><td>${esc(m.parent || '')}</td><td>${m.max_model_len ? rsNum(m.max_model_len) : (m.parent ? '부모와 같음' : '-')}</td><td>${esc(m.owned_by)}</td>
      <td><button class="btn small" data-action="rsUseModel" data-arg="${esc(m.id)}">샘플 생성에 넣기</button></td></tr>`).join('') : '';
  return `<section class="card" aria-labelledby="rs-set-h"><h2 id="rs-set-h">어느 서버를 볼까요</h2>
      <div class="field"><label for="rs-probe-url">서버 주소 <span class="hint">/v1까지</span></label><input id="rs-probe-url" type="text" value="${esc(S.rs.probeUrl)}" data-rs="probeUrl" placeholder="http://nhn-b200:8001/v1"></div>
    </section>
    ${S.rs.probeError ? `<div class="note err" role="alert">${esc(S.rs.probeError)}</div>` : ''}
    ${r ? `<section class="card" aria-labelledby="rs-res-h"><div><h2 id="rs-res-h">결과 · ${esc(r.server)}${r.version ? ' ' + esc(r.version) : ''}</h2><span class="small">${esc(r.url)} · 모델 ${r.models.length}개 · ${r.seconds}초</span></div>
        <div class="rs-scroll"><table class="rs-table"><thead><tr><th>모델</th><th>부모 (LoRA)</th><th>최대 컨텍스트</th><th>제공</th><th><span class="sr-only">동작</span></th></tr></thead><tbody>${rows}</tbody></table></div>
        <div class="small">컨텍스트가 작은 모델은 <a href="${rsUrl('budget')}">컨텍스트 크기</a>에서 몇 화부터 넘치는지 봐요. 서버 주소와 모델을 고정하려면 <a href="#/settings">설정</a>에 저장해요.</div></section>` : ''}`;
}

function rsSampleOut(x) {
  if (!x) return '';
  const cards = (x.rows || []).map((r) => `<section class="card tight">
      <div class="between"><h3>${esc(r.backend)}</h3><span class="small">${r.seconds}초</span></div>
      ${r.ok ? `<div class="small">${esc(r.model)} · ${rsNum(r.chars)}자 · 문장 평균 ${rsNum(r.sentence_len_mean, 1)} · 대사 ${rsNum(r.dialogue_ratio, 2)} · 어휘 ${rsNum(r.mattr, 3)}</div>
        <div class="small">${rsUsage(r.usage, r.seconds)}</div>
        <div class="rs-prose">${esc(r.text)}</div>` : `<div class="note err">${esc(r.error)}</div>`}
    </section>`).join('');
  return `<section class="card" aria-labelledby="rs-res-h"><div><h2 id="rs-res-h">결과 · 백엔드 ${(x.rows || []).length}개</h2><span class="small">${esc(fmtWhen(x.time))} · ${esc((x.prompt || '').slice(0, 60))}</span></div>
    <div class="grid-auto">${cards}</div></section>`;
}

function rsSampleView() {
  return `<section class="card" aria-labelledby="rs-set-h"><h2 id="rs-set-h">무엇을 견줄까요</h2>
      ${rsMultiPicker()}
      <div class="field"><label for="rs-prompt">요청</label><textarea id="rs-prompt" rows="4" data-rs="prompt" placeholder="비 오는 바닷가 소도시 등대 앞, 오빠를 찾는 서윤의 장면을 600자로 써라.">${esc(S.rs.prompt)}</textarea></div>
      <details class="rs-more"><summary>시스템 지시 · 온도</summary>
        <div class="field"><label for="rs-system">시스템 지시</label><textarea id="rs-system" rows="2" data-rs="system">${esc(S.rs.system)}</textarea></div>
        <div class="field" style="max-width:160px"><label for="rs-temp">온도 <span class="hint">로컬만</span></label><input id="rs-temp" type="number" step="0.1" min="0" max="2" value="${esc(S.rs.temperature)}" data-rs="temperature" placeholder="설정값"></div>
      </details>
    </section>${rsSampleOut(rsEntry('sample'))}${rsPast('sample')}`;
}

function rsStageOut(r) {
  if (!r) return '';
  if (!r.ok) return `<div class="note err">${esc(r.error)} · ${r.seconds}초</div>`;
  const filled = r.fields - r.empty.length;
  return `<section class="card" aria-labelledby="rs-res-h">
      <div><h2 id="rs-res-h">결과 · ${esc(S.rs.stages[r.stage] || r.stage)} · ${esc(r.backend)}</h2><span class="small">${esc(fmtWhen(r.time))} · ${r.seconds}초 · 시도 ${r.attempts}번${r.usage ? ` · ${rsUsage(r.usage, r.seconds)}` : ''}</span></div>
      <div class="rs-stats"><div class="rs-stat"><span class="k">채운 칸</span><span class="v">${filled}/${r.fields}</span></div>
        <div class="rs-stat"><span class="k">범위 밖 값</span><span class="v">${r.out_of_range.length}</span></div>
        <div class="rs-stat"><span class="k">다시 물음</span><span class="v">${r.attempts - 1}번</span></div></div>
      ${r.empty.length ? `<div class="note warn">빈 칸 ${r.empty.length}개: <span class="mono">${r.empty.map(esc).join(' · ')}</span></div>` : ''}
      ${r.out_of_range.length ? `<div class="note err">범위를 벗어난 값 ${r.out_of_range.length}개 (스키마 설명의 범위 기준)<br><span class="mono">${r.out_of_range.map(esc).join('<br>')}</span></div>` : ''}
      ${r.attempts > 1 ? '<div class="note plain">첫 응답이 스키마 검증을 통과하지 못해 한 번 더 물었어요.</div>' : ''}
      ${r.result ? `<details><summary>응답 JSON 보기</summary><pre class="brief mono">${esc(JSON.stringify(r.result, null, 2))}</pre></details>` : ''}
    </section>`;
}

function rsStageView() {
  const stages = Object.entries(S.rs.stages).map(([k, l]) => `<option value="${k}"${S.rs.stage === k ? ' selected' : ''}>${l}</option>`).join('');
  return `<section class="card" aria-labelledby="rs-set-h"><h2 id="rs-set-h">무엇으로 시험할까요</h2>
      ${rsPicker('stageBackend', '백엔드')}
      <div class="field" style="max-width:240px"><label for="rs-stage">단계</label><select id="rs-stage" data-rs="stage" onchange="render()">${stages}</select></div>
      ${S.rs.stage === 'style' ? `<div class="field"><label for="rs-stage-text">문체 분석 원문 <span class="hint">비우면 문체 레퍼런스의 대표 문단</span></label><textarea id="rs-stage-text" rows="5" data-rs="stageText" style="font-family:var(--serif)">${esc(S.rs.stageText)}</textarea></div>` : ''}
    </section>${rsStageOut(rsEntry('stage'))}${rsPast('stage')}`;
}

function rsBudgetOut(r) {
  if (!r) return '';
  const head = `<div><h2 id="rs-res-h">결과 · ${esc(r.backend)} · ${esc(r.model)}</h2><span class="small">${esc(fmtWhen(r.time))} · 최대 컨텍스트 ${r.limit ? rsNum(r.limit) + ' 토큰' : '알 수 없음'}</span></div>`;
  const notes = `${r.first_over ? `<div class="note err">${r.first_over}화부터 입력만으로 한도를 넘어 서버가 요청을 거절해요. 단편의 검수는 앞선 본문 전체를 넣어 화가 갈수록 커져요. 서버의 컨텍스트를 늘리거나, 설정의 '단계별 백엔드와 모델'에서 넘치는 단계를 Gemini로 돌려요.</div>` : ''}
      ${r.first_tight && r.first_tight !== r.first_over ? `<div class="note warn">${r.first_tight}화부터 출력 여유까지 더하면 한도를 넘어요. 응답이 중간에 잘릴 수 있어요.</div>` : ''}
      ${!r.limit ? '<div class="note plain">이 백엔드는 한도를 알려 주지 않아 넘침은 판단하지 않았어요.</div>' : (!r.first_tight ? '<div class="note ok">플롯이 있는 화는 모두 한도 안에 들어가요.</div>' : '')}`;
  if (!r.rows) return `<section class="card" aria-labelledby="rs-res-h">${head}${notes}<div class="small">화별 표는 기록에 남지 않아요. 다시 재면 보여요.</div></section>`;
  const parts = (c) => (c.blocks || []).map(([k, v]) => `${k} ${Math.round((v / c.chars) * 100)}%`).join(' · ');
  const cell = (c) => `<td class="${c.over ? 'over' : c.tight ? 'tight' : ''}" title="${esc(parts(c))}">${c.exact ? '' : '~'}${rsNum(c.tokens)}<span class="small"> / ${rsNum(c.total)}</span></td>`;
  const rows = r.rows.map((x) => `<tr><td>${x.episode}화</td><td><span class="chip ${x.status}">${STATUS[x.status]}</span>${x.measured ? '' : ' <span class="small">가정</span>'}</td>${cell(x.write)}${cell(x.check)}${cell(x.state)}</tr>`).join('');
  return `<section class="card" aria-labelledby="rs-res-h">${head}${notes}
      <div class="rs-scroll"><table class="rs-table"><thead><tr><th>화</th><th>상태</th><th>본문 쓰기</th><th>검수</th><th>상태 변경안</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="small">칸마다 '입력 / 입력+출력 여유' 토큰이에요. 출력 여유는 본문 ${rsNum(r.write_reserve)}, 검수 · 상태 ${rsNum(r.json_reserve)} 토큰으로 잡았어요. ${r.tokenizer ? '서버 토크나이저로 셌어요.' : '~ 표시는 글자 수로 어림한 값이에요.'} '가정'인 화는 앞선 화가 모두 목표 분량으로 쓰였다고 보고 쟀어요. 칸에 올리면 큰 블록 비중이 보여요.</div>
    </section>`;
}

function rsBudgetView() {
  return `<section class="card" aria-labelledby="rs-set-h"><h2 id="rs-set-h">어느 모델로 잴까요</h2>${rsPicker('budgetBackend', '백엔드', '한도는 서버가 알려 준 값')}</section>
    ${rsBudgetOut(rsEntry('budget'))}${rsPast('budget')}`;
}

// 기록에 남은 검수 시험 전부를 갈래(행) × 검수 방식(열)로 더한 표. 서버 research.check_totals 가 센다
function rsCheckTotals() {
  const t = S.rs.checkTotals || [];
  if (!t.length) return '';
  const modes = [...new Set(t.map((x) => x.mode))];
  const kinds = [...new Set(t.map((x) => x.kind))];
  const cell = (k, m) => {
    const x = t.find((y) => y.kind === k && y.mode === m);
    if (!x) return `<td data-label="${esc(m)}" class="small">-</td>`;
    const pct = Math.round(x.found / x.planted * 100);
    return `<td data-label="${esc(m)}"><div class="rs-meter"><span>${x.found}/${x.planted} · ${pct}%</span><span class="small">${x.trials}번</span><i><b style="width:${pct}%"></b></i></div></td>`;
  };
  return `<section class="card" aria-labelledby="rs-tot-h">
      <div class="between"><h2 id="rs-tot-h">지금까지 찾은 비율</h2><span class="small">이 작품의 검수 시험 기록을 모두 더했어요</span></div>
      <table class="rs-table rs-stack"><thead><tr><th>심은 갈래</th>${modes.map((m) => `<th>${esc(m)}</th>`).join('')}</tr></thead>
      <tbody>${kinds.map((k) => `<tr><td class="rs-k">${esc(k)}</td>${modes.map((m) => cell(k, m)).join('')}</tr>`).join('')}</tbody></table>
      <div class="small">칸마다 '찾은 수/심은 수', 그 갈래를 심은 시험 횟수예요. 동선은 몸 · 접촉 · 물건으로 나눠 셌어요. twostep은 같은 화 안의 동선을 보지 않아요. 한 번으로는 우연이 커요. 여러 화에서 몇 번 돌려 견줘요.</div>
    </section>`;
}

function rsCheckOut(r) {
  if (!r) return '';
  const n = (r.planted || []).length;
  const stats = r.runs.map((m) => `<div class="rs-stat"><span class="k">${esc(m.mode)}</span><span class="v">${m.ok ? `${m.found}/${n}` : '실패'}</span>
      <span class="k">${m.ok ? `다른 지적 ${m.other.length}개 · ${m.seconds}초` : esc(m.error)}</span></div>`).join('');
  const head = r.runs.map((x) => `<th>${esc(x.mode)}${x.tokens == null ? '' : `<div class="small">~${rsNum(x.tokens)} 토큰</div>`}</th>`).join('');
  const rows = r.planted.map((x, i) => `<tr><td class="rs-k"><div class="row" style="gap:6px"><span class="chip">${esc(x.kind || x.type)}</span><span class="small">근거: ${!x.source_episode ? '설정이나 확정 사실' : x.distance ? `${x.source_episode}화 (${x.distance}화 전)` : '같은 화 앞 문장'}</span></div>
        <div class="rs-quote"><del>${esc(x.quote)}</del><br><ins>${esc(x.replacement)}</ins></div></td>
        ${r.runs.map((m) => `<td data-label="${esc(m.mode)}">${!m.ok ? '<span class="chip bad">실패</span>' : m.hits[i] ? '<span class="chip ok">찾음</span>' : '<span class="chip bad">놓침</span>'}${m.ok && m.raised && !m.hits[i] ? `<div class="small">${m.mode === 'widen' ? (m.raised[i] ? '다시 물었지만 놓침' : '넓혀 찾지 못함') : m.raised[i] ? '판단기는 올림' : '판단기가 놓침'}</div>` : ''}${m.ok && m.first_found && m.hits[i] && !m.first_found[i] ? '<div class="small">넓혀 찾아서 찾음</div>' : ''}</td>`).join('')}</tr>`).join('');
  const extra = (m) => [
    m.mode === 'twostep' && m.ok ? `판단기 ~${rsNum(m.judge_tokens)} 토큰 · 진술 ${m.claims}개 중 ${m.flagged}개 의심` : '',
    m.mode === 'widen' && m.ok ? `진술 ${m.claims}개 중 ${m.widened}개 다시 물음 · 더한 지적 ${m.added}개` : '',
    m.mode === 'stage' && m.ok ? `장면 ${m.scenes.length}개 · 박자 ${m.scenes.reduce((a, s) => a + s.beats.length, 0)}개 · 동선만 봄` : '',
  ].filter(Boolean);
  const notes = r.runs.flatMap((m) => extra(m).map((t) => `<div class="small">${esc(m.mode)}: ${esc(t)}</div>`)).join('');
  return `<section class="card" aria-labelledby="rs-res-h">
      <div><h2 id="rs-res-h">결과 · ${r.episode}화 · ${esc(r.backend)}</h2><span class="small">${esc(fmtWhen(r.time))} · 심은 모순 ${n}개${r.skipped.length ? ` (원문을 못 찾아 ${r.skipped.length}개 뺌)` : ''} · ${r.seconds}초</span></div>
      <div class="rs-stats">${stats}</div>${notes}
      <table class="rs-table rs-stack"><thead><tr><th>심은 모순</th>${head}</tr></thead><tbody>${rows}</tbody></table>
      ${r.runs.filter((m) => m.ok && m.other.length).map((m) => `<details><summary>${esc(m.mode)}의 다른 지적 ${m.other.length}개</summary><ul>${m.other.map((i) => `<li class="small">${esc(i.type)}: ${esc(i.description)}</li>`).join('')}</ul></details>`).join('')}
      ${r.runs.filter((m) => m.mode === 'stage' && m.ok && m.scenes.length).map((m) => `<details><summary>모델이 뽑은 장면 ${m.scenes.length}개</summary><ol>${m.scenes.map((x) => `<li class="small">사건 ${x.event + 1} · 박자 ${x.beats.length}개${x.dropped ? ` · 막은 접촉 ${x.dropped}개` : ''}${x.beats.map((b) => `<div class="rs-prose">${esc(b)}</div>`).join('')}</li>`).join('')}</ol></details>`).join('')}
      ${r.runs.filter((m) => m.mode === 'twostep' && m.ok && m.judged.length).map((m) => `<details><summary>판단기가 본 진술 ${m.judged.length}개 (${esc(m.judge)})</summary><ul>${m.judged.map((j) => `<li class="small">${j.flagged ? '<span class="chip warn">의심</span> ' : ''}어긋남 ${Math.round((j.probs[1] || 0) * 100)}% · ${esc(j.claim)}${j.mass < 0.5 ? ' <span class="hint">선택지 밖 답이 많았어요</span>' : ''}</li>`).join('')}</ul></details>`).join('')}
    </section>`;
}

/** 검수 시험 호출 수: 심기 1번 + full · budget, 장편은 widen 3번, 두 걸음은 검수 2번. 판단기 · 장면 연출은 진술 · 사건 수만큼 더한다 */
function rsCheckCalls(serial, twoStep, stage) {
  return { n: 1 + 2 + (serial ? 3 : 0) + (twoStep ? 2 : 0), more: !!(twoStep || stage) };
}

function rsCheckView() {
  const eps = P().episodes.filter((e) => e.text);
  const modes = Object.entries(S.rs.checkModes).map(([k, v]) => `<li><strong>${esc(k)}</strong>: ${esc(v)}</li>`).join('');
  const opt = (path, title, cost, about) => `<label class="rs-opt${S.rs[path] ? ' on' : ''}"><input type="checkbox" data-rs="${path}" onchange="render()"${S.rs[path] ? ' checked' : ''}><span><strong>${title}</strong></span><span class="c">${cost}</span><span class="s">${about}</span></label>`;
  return `<section class="card" aria-labelledby="rs-set-h"><h2 id="rs-set-h">무엇으로 시험할까요</h2>
      ${rsPicker('checkBackend', '백엔드', '모순 심기와 검수를 같은 백엔드가 해요')}
      <div class="rs-form-row">
        <div class="field" style="flex:1 1 280px"><label for="rs-check-ep">화 <span class="hint">본문이 있는 화</span></label>
          <select id="rs-check-ep" data-rs="checkEp">${eps.map((x) => `<option value="${x.plot.number}"${String(x.plot.number) === String(S.rs.checkEp) ? ' selected' : ''}>${x.plot.number}화 ${esc(x.plot.title)} · ${STATUS[x.status]}</option>`).join('') || '<option value="">본문이 있는 화가 없어요</option>'}</select></div>
        <div class="field"><span class="label" id="rs-plants-lb">심을 모순</span><div class="seg" role="group" aria-labelledby="rs-plants-lb">${[1, 2, 3, 4, 5].map((k) => `<button type="button" aria-pressed="${Number(S.rs.checkPlants) === k}" data-action="rsPlants" data-arg="${k}">${k}</button>`).join('')}</div></div>
      </div>
      <div class="field"><span class="label">함께 시험할 방식 <span class="hint">늘 시험하는 방식: ${esc(Object.keys(S.rs.checkModes).filter((k) => k === 'full' || k === 'budget' || (k === 'widen' && serial())).join(' · '))}</span></span>
        ${opt('checkTwoStep', '두 걸음 검수', '+ 판단기 호출 진술 수만큼', '위 백엔드가 진술을 뽑고 의심만 판정해요. 그 사이에 판단기가 진술마다 선택지 확률만 내요(로컬 서버는 logprobs 지원 필요).')}
        ${opt('checkStage', '장면 연출 규칙 검수', '+ 사건 수만큼', '사건마다 본문에서 장면 연출(자리 · 자세 · 향한 쪽 · 손 · 접촉)을 뽑고, 규칙 판정이 동선만 짚어요.')}</div>
      ${S.rs.checkTwoStep ? rsPicker('checkJudge', '판단기') : ''}
      ${modes ? `<details class="rs-more"><summary>검수 방식 설명</summary><ul class="small">${modes}</ul></details>` : ''}
    </section>${rsCheckOut(rsEntry('check'))}${rsCheckTotals()}${rsPast('check')}`;
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
  const others = S.rs.openCmp.filter((x) => x.episode !== n);
  const card = (d, open) => `<section class="card tight${c.picked === d.n ? ' rs-picked' : ''}">
      <div class="between"><h3>${d.n}번${reveal ? ` <span class="chip ai">${esc(c.order[d.n - 1])}</span>` : ''}</h3>
        ${c.picked ? (c.picked === d.n ? '<span class="chip ok">고름</span>' : '') : `<button class="btn small" data-action="rsPick" data-arg="cmp|${d.n}">${d.n}번 고르기</button>`}</div>
      ${blindProse(c, d)}
      ${blindMetrics(open, `<div class="small">${rsNum(d.chars)}자 · 문장 평균 ${rsNum(d.sentence_len_mean, 1)} · 대사 ${rsNum(d.dialogue_ratio, 2)} · 어휘 ${rsNum(d.mattr, 3)}</div>
        ${d.warnings.length ? `<div class="note warn">${d.warnings.map(esc).join('<br>')}</div>` : ''}`)}
    </section>`;
  const wins = S.rs.pickResult ? Object.entries(S.rs.pickResult.wins).map(([k, v]) => `${esc(k)} ${v}`).join(', ') : '';
  return `<section class="card" aria-labelledby="rs-set-h"><h2 id="rs-set-h">무엇을 견줄까요</h2>
      <div class="field" style="max-width:360px"><label for="rs-cmp-ep">화</label>
        <select id="rs-cmp-ep" onchange="actions.rsCompareEp()">${eps.map((x) => `<option value="${x.plot.number}"${x.plot.number === n ? ' selected' : ''}>${x.plot.number}화 ${esc(x.plot.title)} · ${STATUS[x.status]}${need(x.plot.number)}</option>`).join('') || '<option>확정된 화가 없어요</option>'}</select></div>
      <div class="grid-2">${rsPicker('compareA', 'A')}${rsPicker('compareB', 'B')}</div>
      <label class="rs-opt${S.rs.adopt && !fin ? ' on' : ''}"><input type="checkbox" data-rs="adopt"${S.rs.adopt && !fin ? ' checked' : ''}${fin ? ' disabled' : ''}><span><strong>고른 쪽을 본문으로 채택</strong></span><span class="c"></span><span class="s">끄면 고른 기록만 남기고 작품은 그대로 둬요. 반영이 끝난 화는 채택할 수 없어요.</span></label>
      ${blocked.length ? orderNote(blocked) : fin ? '<div class="note plain">이 화는 반영이 끝난 화라 골라도 본문은 바뀌지 않고 고른 기록만 남아요.</div>' : ''}
      ${others.length ? `<div class="note info">아직 고르지 않은 비교본이 더 있어요: ${others.map((x) => `<button type="button" class="btn small" data-action="rsGoCompare" data-arg="${x.episode}">${x.episode}화</button>`).join(' ')}</div>` : ''}
    </section>
    ${S.rs.pickResult ? `<div class="note ok" role="status">고른 쪽: ${esc(S.rs.pickResult.picked)}. 지금까지 고른 횟수: ${wins}</div>` : ''}
    ${c ? `<section class="card" aria-labelledby="rs-res-h"><div><h2 id="rs-res-h">${n}화 비교본 ${c.drafts.length}개</h2><span class="small">${esc(fmtWhen(c.created))}에 썼어요${c.picked ? '' : ' · 고르기 전까지 백엔드를 가려요'}</span></div>
      ${blindDeck(c, card)}</section>` : ''}
    ${rsPast('compare', ['compare', 'pick'])}`;
}

// ---------- 가려 읽기: 비교본을 한 번에 한 안씩 ----------
// 블라인드 비교와 여는 방식 비교(opening.js)가 함께 쓴다. 안을 나란히 두면 훑어 견주게 되므로 탭으로 하나만 보인다.
// 비교본마다 지금 보는 안, 끝까지 내린 안, 안마다 읽던 자리를 기억한다. 저장하지 않는다 (새로고침하면 1번부터)

S.blind = {};

const blindId = (c) => `${c.episode}:${c.created}`;

function blindState(c) {
  const id = blindId(c);
  return S.blind[id] || (S.blind[id] = { show: 1, seen: [], top: {} });
}

/** 끝까지 읽지 않은 안 번호 (1~count). 고르려는 안 k 는 뺀다. */
function blindUnread(count, seen, k) {
  const out = [];
  for (let i = 1; i <= count; i++) if (i !== k && !seen.includes(i)) out.push(i);
  return out;
}

/** 고르기 전에 다른 안을 끝까지 읽었는지 확인한다. 다 읽었거나 이미 골랐으면 묻지 않는다. */
async function blindPickOk(c, k) {
  if (!c || c.picked) return true;
  const left = blindUnread(c.drafts.length, blindState(c).seen, k);
  return !left.length || askConfirm(`${left.join(', ')}번을 아직 끝까지 읽지 않았어요. ${k}번을 고를까요?`, { ok: '고르기' });
}

/** 비교본 탭과 고른 안 하나. card(d, open): 안 카드, open 은 지표를 펼쳐 둘지 (그 안을 다 읽었거나 고른 뒤). */
function blindDeck(c, card) {
  const st = blindState(c);
  const show = Math.min(st.show, c.drafts.length);
  const id = blindId(c);
  const tabs = c.drafts.map((d) => {
    const who = c.order ? ` · ${esc(c.order[d.n - 1])}` : '';
    const mark = c.picked === d.n ? ' · 고름' : st.seen.includes(d.n) ? ' · 읽음' : '';
    return `<button type="button" role="tab" id="blind-tab-${d.n}" aria-selected="${d.n === show}" aria-controls="blind-panel" data-action="blindShow" data-arg="${esc(id)}|${d.n}">${d.n}번${who}${mark}</button>`;
  }).join('');
  const d = c.drafts[show - 1];
  const left = blindUnread(c.drafts.length, st.seen, 0).length;
  return `<div class="blind">
      <div class="between"><div class="tabs" role="tablist" aria-label="비교본">${tabs}</div>
        ${c.picked ? '' : `<span class="small">${left ? `${left}개 안을 아직 끝까지 읽지 않았어요` : '모두 읽었어요. 고르세요'}</span>`}</div>
      <div id="blind-panel" role="tabpanel" aria-labelledby="blind-tab-${show}">${card(d, !!c.picked || st.seen.includes(d.n))}</div>
    </div>`;
}

/** 비교본 본문 칸. 끝까지 내리면 읽음으로 센다 (아래 scroll). */
function blindProse(c, d) {
  return `<div class="rs-prose blind-prose" tabindex="0" aria-label="${d.n}번 본문" data-blind="${esc(blindId(c))}|${d.n}">${esc(d.text)}</div>`;
}

/** 지표 · 경고 · 판정은 본문 아래에 둔다. 읽기 전에 숫자가 판단을 기울지 않게 그 안을 다 읽기 전까지 접는다. */
function blindMetrics(open, html) {
  return `<details${open ? ' open' : ''}><summary class="small">지표 · 경고${open ? '' : ' (끝까지 읽으면 펼쳐져요)'}</summary><div style="display:flex;flex-direction:column;gap:8px;margin-top:8px">${html}</div></details>`;
}

function blindTrack(el) {
  const [id, k] = el.dataset.blind.split(/\|(?=\d+$)/);
  const st = S.blind[id];
  if (!st || !el.clientHeight) return;  // 보이지 않는 칸은 높이가 0이라 다 읽은 것처럼 보인다
  st.top[k] = el.scrollTop;
  if (st.seen.includes(Number(k)) || el.scrollTop + el.clientHeight < el.scrollHeight - 24) return;
  st.seen.push(Number(k));
  setTimeout(render);  // 그리는 중(syncBlind)에 불릴 수 있어 그리기가 끝난 뒤 다시 그린다
}

/** 다시 그린 뒤 읽던 자리로 돌린다. 내릴 것 없이 짧은 안은 바로 읽음으로 센다. */
function syncBlind() {
  document.querySelectorAll('#app .blind-prose').forEach((el) => {
    const [id, k] = el.dataset.blind.split(/\|(?=\d+$)/);
    const st = S.blind[id];
    if (st && st.top[k]) el.scrollTop = st.top[k];
    blindTrack(el);
  });
}

document.addEventListener('scroll', (e) => {
  if (e.target.matches && e.target.matches('.blind-prose')) blindTrack(e.target);
}, true);

Object.assign(actions, {
  blindShow(arg) {
    const [id, k] = String(arg).split(/\|(?=\d+$)/);
    if (!S.blind[id]) return;
    S.blind[id].show = Number(k);
    render();
  },
});

function rsLogView() {
  const items = S.rs.log.map((x) => {
    const sec = RS_OF[x.kind];
    return `<li><div class="rs-row"><span class="when">${esc(fmtWhen(x.time))}</span><span class="tl"><span class="chip">${RS_KIND[x.kind] || esc(x.kind)}</span> ${esc(rsLogLine(x, S.rs.stages))}</span>
      ${sec ? `<button type="button" class="btn small ghost" data-action="rsOpen" data-arg="${sec}|${esc(x.id)}">결과 보기</button>` : ''}</div>
      <details><summary>기록 그대로 보기</summary><pre class="brief mono">${esc(JSON.stringify(x, null, 2))}</pre></details></li>`;
  }).join('');
  return `<section class="card">${items ? `<ul class="rs-log">${items}</ul>` : '<div class="empty"><p>아직 돌린 실험이 없어요.</p></div>'}</section>`;
}

// ----- 개요 -----

function rsHome() {
  const L = S.rs.latest;
  const todo = [
    // 고르지 않은 비교본: 둘까지는 화마다 한 줄, 더 많으면 한 줄에 화 버튼을 모은다 (상태창 시험은 화마다 비교본을 만든다)
    ...(S.rs.openCmp.length > 2
      ? [`<div class="rs-todo warn"><span><strong>${S.rs.openCmp.map((x) => x.episode).join(' · ')}화 블라인드 비교본</strong>을 아직 고르지 않았어요. 고르면 어느 쪽이었는지 공개해요.</span><span class="row">${S.rs.openCmp.map((x) => `<button type="button" class="btn small" data-action="rsGoCompare" data-arg="${x.episode}">${x.episode}화</button>`).join('')}</span></div>`]
      : S.rs.openCmp.map((x) => `<div class="rs-todo warn"><span><strong>${x.episode}화 블라인드 비교본 ${x.drafts}개</strong>를 아직 고르지 않았어요. 고르면 어느 쪽이었는지 공개해요.</span><button type="button" class="btn small" data-action="rsGoCompare" data-arg="${x.episode}">읽고 고르기</button></div>`)),
    ...(L.budget && L.budget.first_over ? [`<div class="rs-todo info"><span><strong>${esc(L.budget.backend)}</strong>는 ${L.budget.first_over}화부터 입력만으로 컨텍스트 한도(${rsNum(L.budget.limit)})를 넘어요.</span><a class="btn small" href="${rsUrl('budget')}">자세히</a></div>`] : []),
  ];
  const cards = RS_SECS.map((s) => {
    const b = rsBriefNow(s.k);
    return `<a class="rs-x${b.warn ? ' warn' : ''}" href="${rsUrl(s.k)}"><h3>${s.label}</h3><span class="q">${s.q}</span>
      <span class="last">${b.chip ? `<span class="chip ${b.chip[0]}">${esc(b.chip[1])}</span>` : ''}${esc(b.line)}</span></a>`;
  }).join('');
  const recent = S.rs.log.slice(0, 5).map((x) => {
    const sec = RS_OF[x.kind];
    return `<div class="rs-row"><span class="chip">${RS_KIND[x.kind] || esc(x.kind)}</span><span class="tl">${esc(rsLogLine(x, S.rs.stages))}</span><span class="when">${esc(fmtWhen(x.time))}</span>
      ${sec ? `<button type="button" class="btn small ghost" data-action="rsOpen" data-arg="${sec}|${esc(x.id)}">결과 보기</button>` : '<span></span>'}</div>`;
  }).join('');
  const empty = !S.rs.log.length && !S.rs.probe;
  const first = S.config && S.config.local_url ? ['probe', '서버 점검하기'] : ['sample', '샘플 생성하기'];
  return `${todo.length ? `<section class="card" aria-labelledby="rs-todo-h"><h2 id="rs-todo-h">이어서 볼 것</h2>${todo.join('')}</section>` : ''}
    ${empty ? `<section class="card"><div class="empty"><h2>아직 돌린 실험이 없어요</h2><p>로컬 모델 서버가 있으면 서버 점검부터, 없으면 샘플 생성으로 모델 둘을 견줘 봐요.</p><a class="btn primary" href="${rsUrl(first[0])}">${first[1]}</a></div></section>` : ''}
    <section class="card" aria-labelledby="rs-xs-h"><div class="between"><h2 id="rs-xs-h">실험</h2><span class="small">알고 싶은 것을 골라요. 카드마다 마지막 결과예요.</span></div>
      <div class="rs-xs">${cards}</div></section>
    ${recent ? `<section class="card" aria-labelledby="rs-recent-h"><div class="between"><h2 id="rs-recent-h">최근 기록</h2><a class="btn small ghost" href="${rsUrl('log')}">기록 모두 보기</a></div><div class="rs-rows">${recent}</div></section>` : ''}`;
}

// ----- 머리 주 버튼 · 목차 · 화면 -----

/** 쪽마다 머리 주 버튼 (한 화면에 하나) */
function rsPrimary(t) {
  const btn = (action, label, off = false) => `<button type="button" class="btn primary" data-action="${action}"${off ? ' disabled' : ''}>${label}</button>`;
  if (t === 'home') return S.rs.openCmp.length ? `<button type="button" class="btn primary" data-action="rsGoCompare" data-arg="${S.rs.openCmp[0].episode}">${S.rs.openCmp[0].episode}화 비교본 고르기</button>` : '';
  if (t === 'probe') return btn('rsProbe', '점검하기');
  if (t === 'sample') return btn('rsSample', `생성하기 · 백엔드 ${S.rs.runs.length}개`, !S.rs.runs.length);
  if (t === 'stage') return btn('rsStage', '시험하기');
  if (t === 'budget') return btn('rsBudget', '재기');
  if (t === 'check') {
    const k = rsCheckCalls(serial(), S.rs.checkTwoStep, S.rs.checkStage);
    return btn('rsCheck', `시험하기 · 호출 ${k.n}번${k.more ? ' 넘게' : ''}`, !P().episodes.some((e) => e.text));
  }
  if (t === 'compare') {
    const c = S.rs.compare;
    const e = ep(S.rs.compareEp);
    const ok = e && e.status !== 'draft' && !blockedBefore(S.rs.compareEp).length;
    // 고르지 않은 비교본이 있으면 고르기가 할 일이라 다시 쓰기는 보조 버튼이다
    return c && !c.picked ? `<button type="button" class="btn" data-action="rsCompare"${ok ? '' : ' disabled'}>새로 쓰기</button>` : btn('rsCompare', `${S.rs.compareEp}화 비교본 쓰기`, !ok);
  }
  if (t === 'stattrial') return stHeadBtn();  // static/stattrial.js
  return '';
}

function rsToc() {
  const cur = S.rs.tab;
  const item = (k, label, st = '', warn = false) => `<a class="outline-item${warn ? ' warn' : ''}" href="${rsUrl(k)}"${cur === k ? ' aria-current="page"' : ''}><span class="tl">${label}</span>${st ? `<span class="st">${esc(st)}</span>` : ''}</a>`;
  const groups = ['준비', '실험'].map((g) => `<div class="outline-h">${g}</div>${RS_SECS.filter((s) => s.group === g).map((s) => {
    const b = rsBriefNow(s.k);
    return item(s.k, s.label, b.st, b.warn);
  }).join('')}`).join('');
  const now = cur === 'home' ? '개요' : cur === 'log' ? '기록' : RS_SEC[cur].label;
  return outlineNav({ id: 'rs-toc', label: '연구 목차', now: esc(now), body: `${item('home', '개요')}${groups}<div class="outline-sep"></div>${item('log', '기록')}` });
}

function viewResearch() {
  if (!S.rs) return header('본편과 분리', '연구 · 모델 실험', '') + '<div class="note plain">불러오는 중…</div>';
  const t = S.rs.tab;
  const views = { home: rsHome, probe: rsProbeView, sample: rsSampleView, stage: rsStageView, budget: rsBudgetView, check: rsCheckView, compare: rsCompareView, stattrial: stView, log: rsLogView };
  const title = t === 'home' ? '연구 · 모델 실험' : t === 'log' ? '실험 기록' : RS_SEC[t].label;
  const eyebrow = t === 'home' ? `${esc(P().meta.title || S.name)} · 실험 · 본편과 분리` : '연구 · 모델 실험';
  const desc = t === 'home' ? '모델을 점검하고 같은 일을 여러 모델로 돌려 견줘요. 결과는 실험 기록에만 남고, 블라인드 비교에서 채택할 때만 본문이 바뀌어요.'
    : t === 'log' ? '최근 30개 실험이에요. 전체 기록은 작품 폴더의 research/log.jsonl에 있어요.' : RS_SEC[t].desc;
  const back = t === 'home' ? '' : `<a class="btn" href="${rsUrl('home')}">‹ 개요</a>`;
  return `${header(eyebrow, title, desc, back + rsPrimary(t))}${rsModelList()}
    ${outlineDoc(rsToc(), `<div class="rs-col">${views[t]()}</div>`, { wide: true, cls: 'rs-wrap' })}`;
}

// ----- 동작 -----

/** 결과를 받은 쪽: 방금 돌린 결과를 보이고 연 기록은 닫는다 */
function rsGot(sec, x) {
  S.rs.cur[sec] = x;
  delete S.rs.open[sec];
}

Object.assign(actions, {
  async bodyAI(cid) {
    if (!P().characters.some((x) => x.id === cid)) return;
    await run('신체 프로필 제안 만드는 중', async () => {
      await saveIfDirty();  // AI는 저장된 인물 설정을 읽는다. 방금 고친 나이 · 외모도 보게 먼저 저장한다
      const s = await api('POST', `/projects/${enc(S.name)}/characters/${enc(cid)}/body`);
      S.bodySug = { ...(S.bodySug || {}), [cid]: s };
      S.bodyOpen = { ...(S.bodyOpen || {}), [cid]: true };
    });
  },
  bodyApply(cid) {
    const c = P().characters.find((x) => x.id === cid);
    const s = (S.bodySug || {})[cid];
    if (!c || !s) return;
    const picked = [...document.querySelectorAll(`[data-body-pick="${CSS.escape(cid)}"]:checked`)].map((x) => x.value)
      .filter((k) => !(k === 'measurements' && isMinorAge(c.age)));
    if (!picked.length) { toast('적용할 칸을 고르세요', true); return; }
    c.body = { ...(c.body || {}) };
    picked.forEach((k) => { c.body[k] = s[k]; });
    delete S.bodySug[cid];
    markDirty();
    render();
    toast(`${picked.length}칸을 적용했어요. 저장하면 남아요`);
  },
  bodyDismiss(cid) {
    if (S.bodySug) delete S.bodySug[cid];
    render();
  },
  async voiceAI(cid) {
    const c = P().characters.find((x) => x.id === cid);
    if (!c) return;
    if ((c.narration_voice || '').trim() && !(await askConfirm('지금 적힌 서술 말투를 AI 초안으로 바꿀까요? 저장하기 전에는 되돌릴 수 있어요', { ok: '바꾸기' }))) return;
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
  /** 백엔드 칩 고르기(경로|칩 번호). 블라인드 비교의 'cmp|번호'는 비교본 고르기 */
  async rsPick(arg) {
    const [path, i] = String(arg).split('|');
    if (path === 'cmp') return actions.rsPickDraft(Number(i));
    const c = rsCandsNow(path)[Number(i)];
    if (!c) return;
    setPath(S.rs, path, { ...c.b });
    delete S.rs.custom[path];
    render();
  },
  rsCustom(path) {
    S.rs.custom[path] = true;
    render();
    document.getElementById(`rs-${path.replace(/\W/g, '-')}-m`)?.focus();
  },
  rsToggleRun(i) {
    const c = rsCandsNow('runs')[Number(i)];
    if (!c) return;
    const at = S.rs.runs.findIndex((x) => !x.own && rsKey(x) === rsKey(c.b));
    if (at >= 0) S.rs.runs.splice(at, 1); else S.rs.runs.push({ ...c.b });
    render();
  },
  rsAddRun() {
    S.rs.runs.push({ provider: 'local', model: '', url: '', own: true });  // own: 칩과 같아도 직접 적는 칸으로 둔다
    render();
    document.getElementById(`rs-runs-${S.rs.runs.length - 1}-m`)?.focus();
  },
  rsRemoveRun(i) {
    S.rs.runs.splice(Number(i), 1);
    render();
  },
  rsPlants(k) {
    S.rs.checkPlants = Number(k);
    render();
  },
  /** 지난 기록 열기(쪽|id): 그 쪽으로 가서 결과 카드에 그 기록을 그린다 */
  rsOpen(arg) {
    const [sec, id] = String(arg).split('|');
    S.rs.open[sec] = id;
    const x = [...S.rs.log, ...Object.values(S.rs.latest)].find((e) => e.id === id);
    if (sec === 'compare' && x && x.episode) {
      S.rs.compareEp = x.episode;
      S.rs.pickResult = null;
    }
    if (S.rs.tab === sec) {
      if (sec === 'compare') return actions.rsCompareEp(S.rs.compareEp);
      render();
      document.getElementById('rs-res-h')?.scrollIntoView({ block: 'start' });
    } else location.hash = rsUrl(sec);
  },
  rsGoCompare(n) {
    S.rs.compareEp = Number(n);
    S.rs.pickResult = null;
    if (S.rs.tab === 'compare') return actions.rsCompareEp(S.rs.compareEp);
    location.hash = rsUrl('compare');
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
    const b = { provider: 'local', model: id, url: S.rs.probeUrl.trim() === (S.config.local_url || '') ? '' : S.rs.probeUrl.trim() };
    if (!S.rs.runs.some((x) => rsKey(x) === rsKey(b))) S.rs.runs.push(b);
    toast(`샘플 생성에 ${id} 모델을 넣었어요`);
    location.hash = rsUrl('sample');
  },
  async rsSample() {
    if (!S.rs.prompt.trim()) return toast('요청 문장을 넣어요', true);
    if (!S.rs.runs.length) return toast('백엔드를 하나 이상 골라요', true);
    const t = S.rs.temperature === '' ? null : Number(S.rs.temperature);
    await run(`${S.rs.runs.length}개 백엔드로 생성하는 중… (백엔드마다 차례로)`, async () => {
      const x = await api('POST', `/projects/${enc(S.name)}/research/sample`,
        { runs: S.rs.runs.map(rsBackend), system: S.rs.system, prompt: S.rs.prompt, temperature: t });
      rsGot('sample', x);
      await rsLoadLog();
    });
  },
  async rsStage() {
    await run(`${S.rs.stages[S.rs.stage] || S.rs.stage} 시험하는 중… (저장하지 않음)`, async () => {
      const x = await api('POST', `/projects/${enc(S.name)}/research/stage`,
        { backend: rsBackend(S.rs.stageBackend), stage: S.rs.stage, sample: S.rs.stageText });
      rsGot('stage', x);
      await rsLoadLog();
    });
  },
  async rsCheck() {
    const n = Number(S.rs.checkEp || ($('#rs-check-ep') || {}).value);
    if (!n) return toast('본문이 있는 화를 골라요', true);
    await run(`${n}화에 모순을 심고 검수 방식마다 검수하는 중… (저장하지 않음)`, async () => {
      const x = await api('POST', `/projects/${enc(S.name)}/research/check`,
        { backend: rsBackend(S.rs.checkBackend), episode: n, plants: Number(S.rs.checkPlants) || 3,
          ...(S.rs.checkTwoStep ? { judge: rsBackend(S.rs.checkJudge) } : {}), stage: !!S.rs.checkStage });
      rsGot('check', x);
      await rsLoadLog();  // 기록과 갈래별 합계를 함께 새로
    });
  },
  async rsBudget() {
    await run('화별 프롬프트를 재는 중', async () => {
      const x = await api('POST', `/projects/${enc(S.name)}/research/budget`, rsBackend(S.rs.budgetBackend));
      rsGot('budget', x);
      await rsLoadLog();
    });
  },
  async rsCompareEp(n) {
    S.rs.compareEp = Number(n || $('#rs-cmp-ep').value);
    S.rs.pickResult = null;
    await run('불러오는 중', async () => {
      S.rs.compare = (await api('GET', `/projects/${enc(S.name)}/research/compare/${S.rs.compareEp}`)).compare;
    });
  },
  async rsCompare() {
    const n = S.rs.compareEp;
    if (S.rs.compare && !S.rs.compare.picked && !(await askConfirm(`${n}화의 고르지 않은 비교본을 새로 쓴 것으로 바꿀까요?`, { ok: '바꾸기', danger: true }))) return;
    await run(`${n}화를 두 백엔드로 쓰는 중… (몇 분 걸릴 수 있어요)`, async () => {
      S.rs.compare = (await api('POST', `/projects/${enc(S.name)}/research/compare/${n}`,
        { a: rsBackend(S.rs.compareA), b: rsBackend(S.rs.compareB) })).compare;
      S.rs.pickResult = null;
      await rsLoadLog();
    });
  },
  async rsPickDraft(k) {
    const n = S.rs.compareEp;
    const adopt = S.rs.adopt && ep(n).status !== 'finalized';  // 반영이 끝난 화는 고른 기록만 남긴다
    if (!(await blindPickOk(S.rs.compare, k))) return;
    if (adopt && ep(n).text && !(await askConfirm(`${k}번을 ${n}화 본문으로 바꿀까요?`, { ok: '바꾸기' }))) return;
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

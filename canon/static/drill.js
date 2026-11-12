/* 지시 연습 (작품 밖 화면 #/drill[/<판 id>], docs/drill). 서버는 canon/drill.py · routes/drill.py, 엔드포인트는 /api/drill.
   레퍼런스 원고의 한 대목을 가려 두고 작가가 지시(사실 · 일어나는 일 · 쓰는 방식)를 적는다. AI가 지시 있는 판과 쓰는 방식을 비운 판을 쓰고,
   두 판을 원문과 나란히 놓은 뒤 줄마다 층과 결과를 되짚는다. 작품에는 넣지 않는다.
   지시는 S.drForm 에 고치고, 칸을 벗어날 때(change) 조용히 저장한다. 사이드바에는 없고 찾기 팔레트에서 연다 (palette.js PAL_TOOLS). */

DRAFT_ROOTS.drForm = () => S.drForm;
DRAFT_ROOTS.drNew = () => S.drNew;

// AI 호출 셋(사실 뽑기 · 두 판 쓰기 · 되짚기)은 백그라운드 작업으로 돈다 (routes/drill.drill_job). 작업 목록의 project 자리는 DR_JOBS, 대상은 판 id 다
const DR_JOBS = '.drill';
const DR_KINDS = { facts: '사실 뽑기', write: '두 판 쓰기', review: '되짚기' };
const DR_STAGE = { facts: '사실 뽑기 전', brief: '지시 적는 중', written: '두 판을 씀', reviewed: '되짚음' };
const DR_RESULT_CLS = { applied: 'ok', overdone: 'warn', ignored: 'bad', unsure: '' };
const drBtn = (kind, idle) => jobBtn(`dr_${kind}`, null, idle, DR_JOBS, S.dr.id);

/** 지시 연습 작업 시작 (studio.js stuStartJob 과 같은 꼴). 고친 지시를 먼저 저장한다. 실패하면 '다시 시도'가 같은 요청을 보낸다 */
async function drStartJob(kind) {
  const id = S.dr.id;
  const key = jobKey(`dr_${kind}`, null, id);
  if (S.starting.has(key)) return;
  S.starting.add(key);
  render();
  try {
    if (S.drDirty) drSet(await api('PUT', `/drill/${enc(id)}`, S.drForm));
    const j = await api('POST', `/drill/${enc(id)}/jobs`, { kind });
    if (!j.already) toast(`${j.label}${josa(j.label, '을', '를')} 시작했어요. 끝나면 알려 드릴게요.`);
    S.jobs = S.jobs.filter((x) => x.id !== j.id).concat(j);
    S.jobArgs[j.id] = { retry: () => (S.dr && S.dr.id === id ? drStartJob(kind) : toast('그 판을 연 뒤 다시 해 주세요', true)) };
    renderHub();
    pollJobs(true);
  } catch (e) {
    showError(e);
  } finally {
    S.starting.delete(key);
    render();
  }
}

/** 작업이 끝났다: 그 판을 보고 있으면 다시 받는다. 고치던 지시(S.drDirty)는 서버 것으로 바꾸지 않고 남긴다 */
function drJobDone(j) {
  if (j.status !== 'done' || !S.dr || S.dr.id !== j.target) return;
  const id = j.target;
  api('GET', `/drill/${enc(id)}`).then((r) => {
    if (!S.dr || S.dr.id !== id) return;
    if (S.drDirty) S.dr = { ...r, brief: S.dr.brief };
    else drSet(r);
    if (S.route[0] !== 'drill') return;
    if (isTyping() || selecting()) S.renderPending = true;
    else render();
  }).catch(() => {});
}
for (const kind of Object.keys(DR_KINDS)) JOB_LINK[`dr_${kind}`] = (j) => `#/drill/${enc(j.target)}`;
JOB_DONE_MSG.dr_facts = (j) => { drJobDone(j); return `사실과 일어나는 일 ${(j.result || {}).events || 0}줄을 뽑았어요. 고친 뒤 쓰는 방식을 적어 보세요.`; };
JOB_DONE_MSG.dr_write = (j) => { drJobDone(j); return (j.result || {}).reviewed ? '두 판을 쓰고 줄마다 되짚었어요.' : '두 판을 썼어요. 되짚기는 실패했어요. 다시 해 보세요.'; };
JOB_DONE_MSG.dr_review = (j) => { drJobDone(j); return '지시를 줄마다 되짚었어요.'; };

async function drLoad(id) {
  S.drHome = await api('GET', '/drill');
  if (!id) {
    S.dr = null;
    S.drForm = null;
    const src = S.drHome.sources;
    if (!S.drNew || !src.some((x) => x.id === S.drNew.ref_id)) S.drNew = { ref_id: src.length ? src[0].id : '', order: 0, part: 0, kind: '', tension: 0, style_id: (S.drNew || {}).style_id || '' };
    await drLoadEps();
    return;
  }
  drSet(await api('GET', `/drill/${enc(id)}`));
}

/** 고른 원고의 화 목록 (화와 대목 번호를 직접 고를 때 쓴다. 원문은 받지 않는다) */
async function drLoadEps() {
  const rid = S.drNew && S.drNew.ref_id;
  if (!rid) { S.drEps = []; return; }
  if (S.drEpsOf === rid && S.drEps) return;
  S.drEps = (await api('GET', `/drill/sources/${enc(rid)}`).catch(() => ({ episodes: [] }))).episodes;
  S.drEpsOf = rid;
}

/** 서버가 돌려준 판을 받는다. 고치던 지시가 있으면 서버 것으로 바꾼다 (저장 뒤에만 부른다) */
function drSet(r) {
  S.dr = r;
  S.drForm = { brief: JSON.parse(JSON.stringify(r.brief)) };
  S.drDirty = false;
}

function viewDrill() {
  return S.dr ? drRound() : drHomeView();
}

// ----- 처음 화면: 새 판 만들기 + 지난 판 -----

function drHomeView() {
  const h = S.drHome || { rounds: [], sources: [], kinds: [] };
  const head = header('작품 밖 도구', '지시 연습', 'AI에게 장면을 시키는 말을 연습해요. 가려 둔 원고 대목에 지시를 적으면 AI가 쓴 두 판을 원문과 견주고, 줄마다 글을 어떻게 바꿨는지 되짚어요.',
    h.sources.length ? `<button type="button" class="btn primary" data-action="drNew">새 판 시작</button>` : '');
  if (!h.sources.length) {
    return `${head}<section class="card empty"><h2>문제를 낼 원고가 없어요</h2><p class="small">레퍼런스 원고를 넣으면 그 원고의 한 대목으로 연습해요.</p>
      <div class="row"><a class="btn" href="#/refs">레퍼런스 원고 열기</a></div></section>`;
  }
  const list = h.rounds.map((x) => {
    const res = Object.entries(x.results || {}).filter(([, n]) => n).map(([k, n]) => `<span class="chip ${DR_RESULT_CLS[k]}">${esc(h.results[k])} ${n}</span>`).join('');
    return `<a class="card" href="#/drill/${enc(x.id)}"><h3>${esc(x.title)}</h3><div class="row"><span class="chip">${DR_STAGE[x.stage] || ''}</span>${res}</div>
      <div class="small">${esc([x.style_name ? `문체 ${x.style_name}` : '', fmtDateTime(x.created_at)].filter(Boolean).join(' · '))}</div></a>`;
  }).join('');
  return `${head}${drNewForm(h)}${list ? `<h2>지난 판</h2><div class="grid-auto">${list}</div>` : ''}`;
}

function drNewForm(h) {
  const f = S.drNew;
  const eps = S.drEps || [];
  const ep = eps.find((e) => e.order === Number(f.order));
  const sel = (id, label, path, opts, kind = 'text') => `<div class="field"><label for="${id}">${label}</label><select id="${id}" data-root="drNew" data-bind="${path}" data-kind="${kind}">${opts}</select></div>`;
  const opt = (v, t, cur) => `<option value="${esc(v)}"${String(v) === String(cur) ? ' selected' : ''}>${esc(t)}</option>`;
  const cards = eps.some((e) => e.kind);
  const pickEp = sel('dr-ep', '화', 'order', opt(0, '도구가 고르기', f.order) + eps.map((e) => opt(e.order, `${e.label || `${e.order}번째`}${e.kind ? ` · ${e.kind} · 긴장 ${e.tension}` : ''}`, f.order)).join(''), 'int');
  const more = ep
    ? sel('dr-part', '대목', 'part', opt(0, '도구가 고르기', f.part) + Array.from({ length: ep.parts }, (_, i) => opt(i + 1, `${i + 1}/${ep.parts}`, f.part)).join(''), 'int')
    : (cards ? sel('dr-kind', '화의 성격', 'kind', opt('', '아무거나', f.kind) + h.kinds.map((k) => opt(k, k, f.kind)).join(''))
      + sel('dr-tension', '긴장', 'tension', [0, 2, 3, 4, 5].map((t) => opt(t, t ? `${t} 이상` : '아무거나', f.tension)).join(''), 'int') : '');
  const libs = S.libs || [];
  return `<section class="card" id="dr-new"><h2>새 판</h2>
      <div class="grid-auto">${sel('dr-ref', '원고', 'ref_id', h.sources.map((x) => opt(x.id, `${x.name} (${x.eps}화)`, f.ref_id)).join(''))}${pickEp}${more}
      ${sel('dr-style', '문체', 'style_id', opt('', '고르지 않음 (기본 문체 규칙)', f.style_id) + libs.map((l) => opt(l.id, l.name, f.style_id)).join(''))}</div>
      <p class="small">원문은 두 판을 쓴 뒤에 보여요.${cards || ep ? '' : ' 화 카드를 읽힌 원고는 화의 성격 · 긴장으로 고를 수 있어요.'}</p></section>`;
}

// ----- 판 화면 -----

function drRound() {
  const r = S.dr;
  const b = { facts: () => drBtn('facts', '사실 뽑기'), brief: () => drBtn('write', '두 판 쓰기'), written: () => drBtn('review', '되짚기') }[r.stage];
  const act = { facts: 'drFacts', brief: 'drWrite', written: 'drReview' }[r.stage];
  const main = b ? `<button type="button" class="btn primary" data-action="${act}"${b().attr}>${b().label}</button>` : '<a class="btn primary" href="#/drill">새 판 시작</a>';
  const right = `<a class="btn" href="#/drill">목록으로</a><button type="button" class="btn danger" data-action="drDelete">지우기</button>${main}`;
  const head = header('지시 연습', r.title, r.style_name ? `문체: ${esc(r.style_name)}` : '문체를 고르지 않았어요. 기본 문체 규칙으로 써요.', right);
  if (r.stage === 'facts') {
    const busy = jobFor('dr_facts', null, DR_JOBS, r.id);
    return `${head}<section class="card empty"><h2>${busy ? '원문에서 사실과 일어나는 일을 뽑고 있어요' : '아직 사실을 뽑지 않았어요'}</h2>
      <p class="small">AI가 가려 둔 대목(${r.source_chars.toLocaleString()}자)을 읽고 누가 · 어디서 · 직전 상황과 일어나는 일만 적어 줘요.</p></section>`;
  }
  if (r.stage === 'brief') return `${head}<div class="cols"><div class="col wide">${drBriefForm()}</div><div class="col">${drHidden()}${drLayerHelp()}</div></div>`;
  return `${head}${drCompare()}${drReviewCard()}${drBriefShown()}`;
}

function drHidden() {
  const r = S.dr;
  return `<section class="card"><div class="between"><h2>원문</h2><span class="chip">가려 둠</span></div>
      <p class="small">${esc(r.ref_name)} ${esc(r.ep_label)} · 대목 ${r.part}/${r.parts} · ${r.source_chars.toLocaleString()}자</p></section>`;
}

function drLayerHelp() {
  const rows = ((S.drHome || {}).layers || []).map((x) => `<dt>${esc(x.label)}</dt><dd>${esc(x.rule)}</dd>`).join('');
  return `<details class="card"><summary>되짚을 때 붙이는 층</summary><dl class="dr-kv">${rows}</dl></details>`;
}

const drMethodCount = (b) => ['change', 'avoid', 'manner'].reduce((n, k) => n + String(b[k] || '').split('\n').filter((x) => x.trim()).length, 0);

/** 지시 칸: 사실 · 일어나는 일 · 쓰는 방식. 사실과 일어나는 일은 AI가 뽑은 것을 고친다. 쓰는 방식은 물음 셋에 합쳐 다섯 줄까지 */
function drBriefForm() {
  const o = { root: 'drForm' };
  const max = (S.drHome || {}).method_max || 5;
  const n = drMethodCount(S.drForm.brief);
  return `<section class="card"><div class="between"><h2>사실</h2><span class="small" id="dr-saved">${S.drDirty ? '저장하지 않은 고침이 있어요' : 'AI가 뽑은 것이에요. 틀린 곳은 고치세요'}</span></div>
      ${input('인물', 'brief.people', { ...o, rows: 3, placeholder: '한 줄에 한 사람, 이름: 처지' })}
      <div class="grid-2">${input('시점 인물', 'brief.pov', o)}${input('장소', 'brief.place', o)}</div>
      ${input('때 · 날씨', 'brief.time', o)}
      ${input('직전 상황', 'brief.before', { ...o, rows: 2 })}</section>
    <section class="card"><h2>일어나는 일</h2>${input('일어나는 일', 'brief.events', { ...o, rows: 6, placeholder: '한 줄에 하나, 일어나는 차례대로' })}</section>
    <section class="card"><div class="between"><h2>쓰는 방식</h2><span class="chip${n > max ? ' bad' : ''}" id="dr-count">${n}/${max}줄</span></div>
      ${input('바뀌는 것', 'brief.change', { ...o, rows: 2, placeholder: '무엇에서 무엇으로 바뀌나요, 누가 무엇을 알게 되나요' })}
      ${input('하지 않는 것', 'brief.avoid', { ...o, rows: 2, placeholder: '예: 손대기, 목소리 높이기' })}
      ${input('방식', 'brief.manner', { ...o, rows: 2, placeholder: '말투 · 속도, 예: 존댓말을 지키고 짧게 끊는다' })}
      <p class="small">세 물음을 합쳐 ${max}줄까지 적어요. AI는 이 칸이 있는 판과 없는 판을 함께 써요.</p></section>`;
}

/** 지시를 저장한다 (칸을 벗어날 때). 줄 수 상한을 넘으면 서버가 막고 그 말을 알린다 */
async function drSaveBrief() {
  if (!S.dr || !S.drDirty) return true;
  const id = S.dr.id;
  try {
    const r = await api('PUT', `/drill/${enc(id)}`, JSON.parse(JSON.stringify(S.drForm)));
    if (S.dr && S.dr.id === id) { S.dr = r; S.drDirty = false; }
    const el = $('#dr-saved');
    if (el) el.textContent = '저장했어요';
    return true;
  } catch (e) {
    toast(e.message, true);
    return false;
  }
}

document.addEventListener('input', (e) => {
  if (!e.target.dataset || e.target.dataset.root !== 'drForm') return;
  S.drDirty = true;
  const el = $('#dr-saved');
  if (el) el.textContent = '저장하지 않은 고침이 있어요';
  const c = $('#dr-count');
  const max = (S.drHome || {}).method_max || 5;
  if (c) { const n = drMethodCount(S.drForm.brief); c.textContent = `${n}/${max}줄`; c.classList.toggle('bad', n > max); }
});
document.addEventListener('change', async (e) => {
  const el = e.target;
  if (!el.dataset || S.route[0] !== 'drill') return;
  if (el.dataset.root === 'drForm') { drSaveBrief(); return; }
  if (el.dataset.root !== 'drNew') return;
  if (el.dataset.bind === 'ref_id') { S.drNew.order = 0; S.drNew.part = 0; await drLoadEps(); }
  if (el.dataset.bind === 'order') S.drNew.part = 0;
  render();
});

// ----- 견주기: 두 판과 원문 -----

/** 글을 문단(<p>)으로 나누고 인용을 표시한다. marks 는 [인용, 클래스]. 본문에 글자 그대로 있는 인용만 표시한다 */
function drText(text, marks = []) {
  const spans = [];
  for (const [q, cls] of marks) {
    const at = q && !q.includes('\n') ? text.indexOf(q) : -1;
    if (at >= 0 && !spans.some(([a, b]) => at < b && at + q.length > a)) spans.push([at, at + q.length, cls]);
  }
  spans.sort((a, b) => a[0] - b[0]);
  let html = '';
  let pos = 0;
  const plain = (t) => esc(t).replace(/\n/g, '</p><p>');
  for (const [a, b, cls] of spans) {
    html += `${plain(text.slice(pos, a))}<mark class="hl ${cls}">${esc(text.slice(a, b))}</mark>`;
    pos = b;
  }
  return `<p>${html}${plain(text.slice(pos))}</p>`;
}

function drMeasure(m) {
  return m ? `<div class="small">${m.chars.toLocaleString()}자 · ${m.sentences}문장 · 대사 ${m.dialogue_pct}%${m.hits.length ? ` · 걸린 곳 ${m.hits.length}` : ''}</div>` : '';
}

function drCompare() {
  const r = S.dr;
  const a = r.attempts[r.attempts.length - 1];
  const m = r.measures[String(a.no)] || {};
  const inv = (side) => a.invented.filter((x) => x.side === side).map((x) => [x.quote, 'banned']);
  const col = (title, note, text, measure, marks) => `<section class="card"><div class="between"><h2>${title}</h2><span class="small">${note}</span></div>${drMeasure(measure)}
      <div class="rw-text dr-text">${drText(text, marks)}</div></section>`;
  return `<div class="dr-three">
      ${col('지시 있는 판', '쓰는 방식 있음', a.with_text, m.with, [...a.verdicts.map((v) => [v.quote, 'device']), ...inv('with')])}
      ${col('지시 없는 판', '쓰는 방식 없음', a.bare_text, m.bare, [...a.verdicts.map((v) => [v.bare_quote, 'rest']), ...inv('bare')])}
      ${col('원문', `${esc(r.ref_name)} ${esc(r.ep_label)}`, r.source, r.source_measure, a.gaps.map((g) => [g.quote, 'rest']))}</div>`;
}

// ----- 되짚기: 줄마다 층과 결과 -----

function drReviewCard() {
  const r = S.dr;
  const h = S.drHome || { layers: [], results: {}, boxes: {} };
  const a = r.attempts[r.attempts.length - 1];
  if (!a.reviewed_at) {
    const busy = jobFor('dr_review', null, DR_JOBS, r.id) || jobFor('dr_write', null, DR_JOBS, r.id);
    return `<section class="card empty"><h2>${busy ? '줄마다 되짚고 있어요' : '아직 되짚지 않았어요'}</h2><p class="small">AI가 지시의 줄마다 층과 결과를 붙이고 본문에서 근거 문장을 찾아요.</p></section>`;
  }
  const layer = (id) => (h.layers.find((x) => x.id === id) || { label: id }).label;
  const rows = a.verdicts.map((v) => {
    const why = [v.why, v.same_as ? `${v.same_as}번 줄과 같은 말이에요` : ''].filter(Boolean).join(' · ');
    const proof = [v.quote ? `«${esc(v.quote)}»` : '', v.bare_quote ? `<span class="small">지시 없는 판: «${esc(v.bare_quote)}»</span>` : ''].filter(Boolean).join('<br>');
    return `<tr><td class="small">${v.no}</td><td>${esc(v.text)}<br><span class="small">${esc(h.boxes[v.box] || v.box)}</span></td>
      <td>${v.result === 'unsure' ? '' : `<span class="chip">${esc(layer(v.layer))}</span>`}</td>
      <td><span class="chip ${DR_RESULT_CLS[v.result]}">${esc(h.results[v.result] || v.result)}</span>${v.in_bare && v.result !== 'unsure' ? '<br><span class="small">지시 없는 판도 같아요</span>' : ''}</td>
      <td>${proof}${proof && why ? '<br>' : ''}<span class="small">${esc(why)}</span></td></tr>`;
  }).join('');
  const inv = a.invented.map((x) => `<li><span class="chip">${x.side === 'with' ? '지시 있는 판' : '지시 없는 판'}</span> «${esc(x.quote)}» <span class="small">${esc(x.what)}</span></li>`).join('');
  const gaps = a.gaps.map((g) => `<li>${esc(g.what)} <span class="small">원문: «${esc(g.quote)}»</span></li>`).join('');
  const again = drBtn('review', '다시 되짚기');
  return `<section class="card" id="dr-review"><div class="between"><h2>되짚기</h2><button type="button" class="btn small" data-action="drReview"${again.attr}>${again.label}</button></div>
      <div class="rs-scroll"><table class="rs-table"><thead><tr><th>#</th><th>내가 쓴 줄</th><th>층</th><th>결과</th><th>근거</th></tr></thead><tbody>${rows}</tbody></table></div>
      ${inv ? `<h3>지어낸 사실</h3><ul class="dr-list">${inv}</ul>` : ''}${gaps ? `<h3>원문에는 있고 두 판에 없는 것</h3><ul class="dr-list">${gaps}</ul>` : ''}
      ${a.dropped ? `<p class="small">본문에 없는 인용 ${a.dropped}개는 버렸어요.</p>` : ''}</section>`;
}

/** 쓴 지시를 읽기만 하게 보인다 (접어 둔다) */
function drBriefShown() {
  const h = S.drHome || { boxes: {} };
  const a = S.dr.attempts[S.dr.attempts.length - 1];
  const rows = Object.keys(h.boxes).filter((k) => a.brief[k]).map((k) => `<dt>${esc(h.boxes[k])}</dt><dd>${esc(a.brief[k]).replace(/\n/g, '<br>')}</dd>`).join('');
  return `<details class="card"><summary>이 판에 준 지시</summary><dl class="dr-kv">${rows}</dl></details>`;
}

const DR_CSS = `.dr-three { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--gap-stack); align-items: start; margin-bottom: var(--gap-stack); }
.dr-text { white-space: normal; }
.dr-text p { margin: 0; white-space: pre-wrap; }
.dr-kv { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: var(--space-4) var(--space-12); margin: var(--space-10) 0 0; font-size: 0.8125rem; }
.dr-kv dt { color: var(--muted); }
.dr-kv dd { margin: 0; }
.dr-list { margin: 0; padding-left: var(--space-20); display: grid; gap: var(--space-4); }
@media (max-width: 1100px) { .dr-three { grid-template-columns: minmax(0, 1fr); } }`;
(() => { const st = document.createElement('style'); st.textContent = DR_CSS; document.head.appendChild(st); })();

Object.assign(actions, {
  async drNew() {
    await run('문제를 내는 중', async () => {
      const f = S.drNew;
      const r = await api('POST', '/drill', { ref_id: f.ref_id, order: Number(f.order) || 0, part: Number(f.part) || 0, kind: f.order ? '' : f.kind, tension: f.order ? 0 : Number(f.tension) || 0, style_id: f.style_id });
      drSet(r);
      location.hash = `#/drill/${enc(r.id)}`;
    }, { render: 'never' });
    if (S.dr && S.dr.stage === 'facts') await drStartJob('facts');
  },
  async drFacts() {
    await drStartJob('facts');
  },
  async drWrite() {
    await drStartJob('write');
  },
  async drReview() {
    await drStartJob('review');
  },
  async drDelete() {
    if (!(await askConfirm(`'${S.dr.title}' 판을 지울까요? 쓴 글과 되짚기가 함께 사라져요.`, { ok: '지우기', danger: true }))) return;
    await run('판을 지우는 중', async () => {
      await api('DELETE', `/drill/${enc(S.dr.id)}`);
      S.dr = null;
      location.hash = '#/drill';
    }, { render: 'never' });
  },
});

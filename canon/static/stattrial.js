/* 연구 화면 '상태창 시험' 쪽(#/p/<이름>/research/stattrial). app.js 의 S, actions, api, render, esc, enc, toast, startJob, jobBtn, JOB_DONE_MSG 를 쓴다.
   같은 화를 상태창 수치를 넣는 방식(stat_window.prompt: none · json · lines)만 바꿔 써서 견준다. 서버는 canon/stattrial.py.
   방식 · 화 · 반복을 고르면 비용을 바로 추정해(AI 없음) 머리 주 버튼 글에 적고, 시작은 작가가 누른다.
   작품에는 저장하지 않고, 결과는 실험 기록(research/log.jsonl, kind statwin)과 블라인드 비교본(compare/<화>)으로 남는다. */
'use strict';

Object.assign(S, {
  st: null,          // 서버 값 { conditions, candidates, pick, runs }
  stSel: null,       // 고른 화 Set
  stRepeats: 1,
  stConds: null,     // 고른 방식 Set
  stEsts: {},        // 비용 추정 { 열쇠(stEstKey): 값 | null(묻는 중) | { error } }
  stOpen: '',        // 틀린 곳을 펼친 기록 id
});

async function stLoad() {
  S.st = await api('GET', `/projects/${enc(S.name)}/stattrial`).catch((e) => ({ error: e.message }));
  if (!S.st.error) {
    if (!S.stSel) S.stSel = new Set(S.st.pick);
    if (!S.stConds) S.stConds = new Set(S.st.conditions.map((c) => c.key));
  }
  S.stEsts = {};
}

const stPlan = () => ({ episodes: [...S.stSel].sort((a, b) => a - b), repeats: S.stRepeats, conditions: [...S.stConds].sort() });
const stWrites = (p) => p.episodes.length * p.repeats * p.conditions.length;
const stUsd = (x) => (x === null || x === undefined ? '가격 모름' : `약 ${x < 1 ? x.toFixed(2) : x.toFixed(1)}달러`);
const stEstKey = (p) => `${p.episodes.join(',')}|${p.repeats}|${p.conditions.join(',')}`;

/** 비용 추정 (AI 없음). 처음 부르면 서버에 묻고 null, 받으면 다시 그린다 (revlab.js revEst 와 같은 틀) */
function stEst(p = stPlan()) {
  if (!stWrites(p)) return null;
  const key = stEstKey(p);
  const v = S.stEsts[key];
  if (v === undefined) {
    S.stEsts[key] = null;
    const name = S.name;
    api('POST', `/projects/${enc(name)}/stattrial/estimate`, p)
      .then((d) => { if (S.name === name) S.stEsts[key] = d; })
      .catch((err) => { if (S.name === name) S.stEsts[key] = { error: err.message }; })
      .finally(() => { if (!revTyping()) render(); });
  }
  return v && !v.error ? v : null;
}

/** 머리 주 버튼: '시작 · 본문 12개 · 약 0.43달러'. 추정을 받기 전에는 '비용 재는 중' */
function stHeadBtn() {
  const d = S.st;
  if (!d || d.error || !d.candidates.length) return '';
  const p = stPlan();
  const n = stWrites(p);
  if (!n) return '<button type="button" class="btn primary" disabled>시작 · 화와 방식을 골라요</button>';
  const est = stEst(p);
  const err = (S.stEsts[stEstKey(p)] || {}).error;
  const b = jobBtn('stattrial', null, `시작 · 본문 ${n}개 · ${est ? stUsd(est.usd) : err ? '비용 모름' : '비용 재는 중'}`);
  return `<button type="button" class="btn primary" data-action="stStart"${b.attr || (est || err ? '' : ' aria-disabled="true"')}>${esc(b.label)}</button>`;
}

function stView() {
  const d = S.st;
  if (!d) return '<section class="card"><div class="small">불러오는 중…</div></section>';
  if (d.error) return `<section class="card"><div class="note err">${esc(d.error)}</div></section>`;
  const conds = `<section class="card" aria-labelledby="st-c-h">
    <div class="between"><h2 id="st-c-h">견줄 방식</h2>
      <div class="st-rep"><span class="label" id="st-rep-lb">방식마다 같은 화를</span><div class="seg" role="group" aria-labelledby="st-rep-lb">${[1, 2, 3].map((k) => `<button type="button" aria-pressed="${k === S.stRepeats}" data-action="stRepeat" data-arg="${k}">${k}번</button>`).join('')}</div></div></div>
    <div class="st-conds">${d.conditions.map((c) => `<label class="rs-opt${S.stConds.has(c.key) ? ' on' : ''}"><input type="checkbox" data-st-cond="${c.key}"${S.stConds.has(c.key) ? ' checked' : ''}><span><strong>${esc(c.label)}</strong></span><span class="c"></span><span class="s">${esc(c.about)}</span></label>`).join('')}</div>
    <p class="small">채점은 AI 없이 해요. 원래 반영 기록과 견줘 틀린 수치, 기록에 없는 항목, 플롯에 없던 상태창 수를 세요.</p></section>`;
  if (!d.candidates.length) {
    return `<section class="card"><div class="empty"><h2>시험할 화가 없어요</h2><p>상태창 수치가 있고 상태 승인까지 끝난 화가 있어야 해요.</p><a class="btn primary" href="${base()}/statwin">상태창 수치로 가기</a></div></section>${conds}${stRuns()}`;
  }
  const p = stPlan();
  const eps = d.candidates.map((c) => `<label class="st-ep${S.stSel.has(c.episode) ? ' on' : ''}"><input type="checkbox" data-st-ep="${c.episode}"${S.stSel.has(c.episode) ? ' checked' : ''}>
      <span><strong>${c.episode}화</strong> ${esc(c.title || '')}</span><span class="tags">${c.changed ? '<span class="chip ai">수치 바뀜</span>' : '<span class="chip">수치 그대로</span>'}${c.wants ? '<span class="chip">상태창 장면</span>' : ''}</span></label>`).join('');
  const est = stEst(p);
  const estHtml = est ? `<details class="rs-more"><summary>비용 자세히 · ${esc(est.model)} 가격표 기준</summary><div class="rs-scroll"><table class="rs-table"><thead><tr><th>방식</th><th>쓰기</th><th>입력 토큰</th><th>출력 토큰</th><th>비용</th></tr></thead><tbody>
      ${est.rows.map((r) => `<tr><td>${esc(r.label)}</td><td>${r.writes}</td><td>${r.input_tokens.toLocaleString()}</td><td>${r.output_tokens.toLocaleString()}</td><td>${stUsd(r.usd)}</td></tr>`).join('')}
      <tr><th>합</th><td>${est.writes}</td><td></td><td></td><th>${stUsd(est.usd)}</th></tr></tbody></table></div>
      <div class="small">${esc(est.note)}</div></details>` : '';
  const err = (S.stEsts[stEstKey(p)] || {}).error;
  return `${conds}
    <section class="card" aria-labelledby="st-e-h"><div class="between"><div><h2 id="st-e-h">시험할 화</h2><span class="small">반영이 끝난 ${d.candidates.length}화 중 ${p.episodes.length}화 골랐어요 · 본문 ${stWrites(p)}개를 써요</span></div>
      <button type="button" class="btn small ghost" data-action="stPickDefault">추천대로 고르기</button></div>
      <div class="st-eps">${eps}</div>
      <p class="small">추천: 수치가 바뀐 화와 그대로인 화를 반씩, 상태창 장면이 있는 화를 먼저 골라요.</p>
      <div class="note warn">시작하면 실제 AI를 불러요. 고른 화마다 블라인드 비교본이 새로 생기고, 그 화의 이전 비교본은 지워져요.</div>
      ${err ? `<div class="note err">비용을 추정하지 못했어요: ${esc(err)}</div>` : ''}${estHtml}</section>
    ${stRuns()}`;
}

/** 틀린 비율 막대(한 계열). 가장 큰 값이 칸을 채운다. 순수 함수(tests/test_research_js.py) */
function stBars(summary) {
  const max = Math.max(...summary.map((s) => s.error_rate || 0), 0);
  return summary.map((s) => ({ label: s.label, pct: s.error_rate == null ? null : Math.round(s.error_rate * 100),
    width: s.error_rate == null || !max ? 0 : Math.round((s.error_rate / max) * 100), detail: `보인 값 ${s.shown}개 중 ${s.wrong}개 틀림` }));
}

function stRun(r) {
  const open = S.stOpen === r.id;
  const bars = stBars(r.summary).map((b) => `<div class="st-bar" title="${esc(`${b.label} · ${b.detail}`)}"><span class="label">${esc(b.label)}</span><span class="bar"><b style="width:${b.width}%"></b></span><span class="v">${b.pct == null ? '-' : `${b.pct}%`}</span></div>`).join('');
  const cols = [['본문', (s) => s.drafts], ['보인 값', (s) => s.shown], ['틀린 값', (s) => s.wrong], ['없던 항목', (s) => s.invented],
    ['플롯에 없던 상태창', (s) => `${s.windows} (${s.unwanted_windows})`], ['요청 토큰', (s) => s.prompt_tokens.toLocaleString()], ['본문 글자', (s) => s.chars.toLocaleString()]];
  // 좁은 칸에서는 방식마다 칸을 쌓는다 (.rs-stack, 칸 이름은 data-label)
  const table = `<table class="rs-table rs-stack"><thead><tr><th>방식</th>${cols.map(([l]) => `<th>${l}</th>`).join('')}</tr></thead><tbody>
      ${r.summary.map((s) => `<tr><td class="rs-k">${esc(s.label)}</td>${cols.map(([l, f]) => `<td data-label="${l}">${f(s)}</td>`).join('')}</tr>`).join('')}
      </tbody></table>`;
  const detail = open ? `<ul class="small st-wrong">${r.drafts.filter((x) => x.samples.length || x.invented.length).map((x) => `<li>${x.episode}화 · ${esc((S.st.conditions.find((c) => c.key === x.condition) || {}).label || x.condition)} ${x.repeat}번: ${[...x.samples, ...x.invented.map((k) => `없던 항목 '${k}'`)].map(esc).join(' / ')}</li>`).join('') || '<li>틀린 값과 없던 항목이 없어요.</li>'}</ul>` : '';
  return `<section class="card" aria-labelledby="st-r-${esc(r.id)}"><div class="between"><div><h2 id="st-r-${esc(r.id)}">지난 시험 · ${esc(fmtWhen(r.time))}</h2><span class="small">${r.episodes.join(' · ')}화 × ${r.summary.length}방식 × ${r.repeats}번 · 본문 ${r.drafts.length}개</span></div>
      <div class="row"><button type="button" class="btn small" data-action="stToggle" data-arg="${esc(r.id)}" aria-expanded="${open}">${open ? '틀린 곳 접기' : '틀린 곳 보기'}</button><a class="btn small" href="${rsUrl('compare')}">블라인드 비교에서 고르기</a></div></div>
      <div class="st-bars" role="img" aria-label="본문에 보인 수치 중 틀린 비율: ${stBars(r.summary).map((b) => `${b.label} ${b.pct == null ? '보인 값 없음' : `${b.pct}%`}`).join(', ')}">
        <span class="small st-cap">본문에 보인 수치 중 틀린 비율</span>${bars}</div>
      ${table}${detail}</section>`;
}

/** 지난 시험: 연 기록(기록 쪽 · 개요에서 연 것)이나 마지막 시험 하나를 자세히, 나머지는 한 줄씩 */
function stRuns() {
  const runs = (S.st && S.st.runs) || [];
  if (!runs.length) return '';
  const shown = runs.find((r) => r.id === S.rs.open.stattrial) || runs[0];
  const rest = runs.filter((r) => r !== shown);
  return `${stRun(shown)}${rest.length ? `<section class="card" aria-labelledby="st-old-h"><h2 id="st-old-h">그 전 시험</h2><div class="rs-rows">${rest.map((r) => `<div class="rs-row"><span class="when">${esc(fmtWhen(r.time))}</span><span class="tl">${esc(rsLogLine(r))}</span><button type="button" class="btn small ghost" data-action="rsOpen" data-arg="stattrial|${esc(r.id)}">열기</button></div>`).join('')}</div></section>` : ''}`;
}

document.addEventListener('change', (e) => {
  const d = e.target.dataset || {};
  if (d.stEp !== undefined) { S.stSel[e.target.checked ? 'add' : 'delete'](Number(d.stEp)); render(); }
  if (d.stCond !== undefined) { S.stConds[e.target.checked ? 'add' : 'delete'](d.stCond); render(); }
});

JOB_PAGES.stattrial = ['research'];  // 진행 · 끝을 연구 화면에서 다시 그린다
JOB_DONE_MSG.stattrial = (j) => {
  stLoad().then(() => { if (S.rs) delete S.rs.open.stattrial; render(); });  // 끝난 시험을 지난 시험 칸에 바로 보인다
  return `상태창 시험이 끝났어요: 본문 ${j.result ? j.result.drafts : 0}개. 연구 화면 '상태창 시험'에서 봐요.`;
};

Object.assign(actions, {
  stPickDefault() { S.stSel = new Set(S.st.pick); render(); },
  stRepeat(k) { S.stRepeats = Number(k); render(); },
  stToggle(id) { S.stOpen = S.stOpen === id ? '' : id; render(); },
  stStart() {
    const p = stPlan();
    if (!stWrites(p) || jobFor('stattrial', null)) return;
    startJob('stattrial', null, p);
  },
});

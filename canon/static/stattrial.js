/* 연구 화면 '상태창 시험' 탭. app.js 의 S, actions, api, run, render, esc, enc, toast, startJob, JOB_DONE_MSG 를 쓴다.
   같은 화를 상태창 수치를 넣는 방식(stat_window.prompt: none · json · lines)만 바꿔 써서 견준다. 서버는 canon/stattrial.py.
   시험할 화(반영이 끝난 화)와 반복 수 · 조건을 고르면 비용을 먼저 추정해 보여 주고, 시작은 작가가 누른다.
   작품에는 저장하지 않고, 결과는 실험 기록(research/log.jsonl, kind statwin)과 블라인드 비교본(compare/<화>)으로 남는다. */
'use strict';

Object.assign(S, {
  st: null,          // 서버 값 { conditions, candidates, pick, runs }
  stSel: null,       // 고른 화 Set
  stRepeats: 1,
  stConds: null,     // 고른 조건 Set
  stEst: null,       // 비용 추정
  stOpen: '',        // 펼친 기록 id
});

async function stLoad() {
  S.st = await api('GET', `/projects/${enc(S.name)}/stattrial`).catch((e) => ({ error: e.message }));
  if (!S.st.error) {
    if (!S.stSel) S.stSel = new Set(S.st.pick);
    if (!S.stConds) S.stConds = new Set(S.st.conditions.map((c) => c.key));
    S.stEst = null;
  }
}

const stPlan = () => ({ episodes: [...S.stSel].sort((a, b) => a - b), repeats: S.stRepeats, conditions: [...S.stConds] });
const stUsd = (x) => (x === null || x === undefined ? '가격 모름' : `약 ${x < 1 ? x.toFixed(2) : x.toFixed(1)}달러`);

function stView() {
  const d = S.st;
  if (!d) return '<section class="card"><div class="small">불러오는 중…</div></section>';
  if (d.error) return `<section class="card"><div class="note err">${esc(d.error)}</div></section>`;
  const intro = `<section class="card"><h2>상태창 넣기 시험</h2>
    <p class="small">같은 화를 세 방식으로 다시 써서 견줘요. 화마다 그 화를 쓰기 직전 상태로 되돌린 사본에서 쓰고, 작품은 바꾸지 않아요.</p>
    <dl class="ab-kv">${d.conditions.map((c) => `<dt>${esc(c.label)}</dt><dd class="small">${esc(c.about)}</dd>`).join('')}</dl>
    <p class="small">채점은 AI 없이 해요. 원래 반영 기록과 견줘 본문에 나온 수치가 틀린 수, 기록에 없는 항목, 플롯에 없던 상태창 수를 세요. 조건마다 첫 안은 블라인드 비교 탭에서 번호를 가려 고를 수 있어요.</p></section>`;
  if (!d.candidates.length) {
    return `${intro}<section class="card"><div class="note plain">시험할 화가 없어요. 상태창 수치가 있고 상태 반영이 끝난 화가 있는 작품에서 시험해요.</div></section>${stRuns()}`;
  }
  const eps = d.candidates.map((c) => `<label class="row small" style="gap:6px"><input type="checkbox" data-st-ep="${c.episode}"${S.stSel.has(c.episode) ? ' checked' : ''}>
      ${c.episode}화 ${esc(c.title || '')}${c.changed ? ' <span class="ab-pill">수치 바뀜</span>' : ''}${c.wants ? ' <span class="ab-pill">상태창 장면</span>' : ''}</label>`).join('');
  const conds = d.conditions.map((c) => `<label class="row small" style="gap:6px"><input type="checkbox" data-st-cond="${c.key}"${S.stConds.has(c.key) ? ' checked' : ''}>${esc(c.label)}</label>`).join('');
  const p = stPlan();
  const writes = p.episodes.length * p.repeats * p.conditions.length;
  const est = S.stEst;
  const estHtml = est ? `<div class="tablewrap" style="overflow-x:auto"><table class="sw-table"><thead><tr><th>조건</th><th>쓰기</th><th>입력 토큰</th><th>출력 토큰</th><th>비용</th></tr></thead><tbody>
      ${est.rows.map((r) => `<tr><td>${esc(r.label)}</td><td>${r.writes}</td><td>${r.input_tokens.toLocaleString()}</td><td>${r.output_tokens.toLocaleString()}</td><td>${stUsd(r.usd)}</td></tr>`).join('')}
      <tr><th>합</th><td>${est.writes}</td><td></td><td></td><th>${stUsd(est.usd)}</th></tr></tbody></table></div>
      <div class="small">${esc(est.model)} 가격표 기준 · ${esc(est.note)}</div>` : '';
  return `${intro}
    <section class="card"><h2>시험할 화 <span class="small">${p.episodes.length}화 골랐어요</span></h2>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:6px">${eps}</div>
      <div class="row small"><button type="button" class="btn small ghost" data-action="stPickDefault">추천대로 고르기</button><span>수치가 바뀐 화와 안 바뀐 화를 반씩, 상태창 장면이 있는 화를 먼저 골라요.</span></div></section>
    <section class="card"><h2>조건과 반복</h2>
      <div class="row" style="gap:16px">${conds}</div>
      <div class="field"><label for="st-rep">조건마다 같은 화를 몇 번 쓸까요</label><select id="st-rep" data-st-rep="1" style="width:auto">${[1, 2, 3].map((k) => `<option value="${k}"${k === S.stRepeats ? ' selected' : ''}>${k}번</option>`).join('')}</select></div>
      <div class="between"><span class="small">본문 ${writes}개를 써요.</span><button type="button" class="btn small" data-action="stEstimate"${writes ? '' : ' disabled'}>비용 추정</button></div>
      ${estHtml}
      <div class="note warn">시작하면 실제 AI를 불러 본문 ${writes}개를 써요. 비용이 들어요. 화마다 블라인드 비교본이 새로 만들어져 그 화의 이전 비교본은 지워져요.</div>
      <div class="row"><button type="button" class="btn primary" data-action="stStart"${writes && est ? '' : ' disabled'}>시험 시작</button>${est ? '' : '<span class="small">비용 추정을 먼저 보세요.</span>'}</div></section>
    ${stRuns()}`;
}

function stRuns() {
  const runs = (S.st && S.st.runs) || [];
  if (!runs.length) return '<section class="card"><h2>지난 시험</h2><div class="small">아직 없어요.</div></section>';
  const rows = runs.map((r) => {
    const open = S.stOpen === r.id;
    const table = `<div style="overflow-x:auto"><table class="sw-table"><thead><tr><th>조건</th><th>본문</th><th>보인 값</th><th>틀린 값</th><th>없던 항목</th><th>상태창 (플롯에 없던 것)</th><th>요청 토큰</th><th>본문 글자</th></tr></thead><tbody>
      ${r.summary.map((s) => `<tr><td>${esc(s.label)}</td><td>${s.drafts}</td><td>${s.shown}</td><td>${s.wrong}${s.error_rate !== null ? ` (${Math.round(s.error_rate * 100)}%)` : ''}</td><td>${s.invented}</td><td>${s.windows} (${s.unwanted_windows})</td><td>${s.prompt_tokens.toLocaleString()}</td><td>${s.chars.toLocaleString()}</td></tr>`).join('')}
      </tbody></table></div>`;
    const detail = open ? `<ul class="small" style="padding-left:18px;margin:6px 0 0">${r.drafts.filter((x) => x.samples.length || x.invented.length).map((x) => `<li>${x.episode}화 · ${esc((S.st.conditions.find((c) => c.key === x.condition) || {}).label || x.condition)} ${x.repeat}번: ${[...x.samples, ...x.invented.map((k) => `없던 항목 '${k}'`)].map(esc).join(' / ')}</li>`).join('') || '<li>틀린 값과 없던 항목이 없어요.</li>'}</ul>` : '';
    return `<div class="ab-item"><div class="between"><span><strong>${esc(fmtDateTime(r.time))}</strong> <span class="small">${r.episodes.length}화 · ${r.repeats}번 · ${r.drafts.length}개</span></span>
      <span class="row" style="gap:6px"><button type="button" class="btn small ghost" data-action="stToggle" data-arg="${esc(r.id)}">${open ? '틀린 곳 접기' : '틀린 곳 보기'}</button><button type="button" class="btn small" data-action="rsTab" data-arg="compare">블라인드 비교로</button></span></div>${table}${detail}</div>`;
  }).join('');
  return `<section class="card"><h2>지난 시험</h2><div class="ab-list" style="display:flex;flex-direction:column;gap:10px">${rows}</div></section>`;
}

document.addEventListener('change', (e) => {
  const d = e.target.dataset || {};
  if (d.stEp !== undefined) { S.stSel[e.target.checked ? 'add' : 'delete'](Number(d.stEp)); S.stEst = null; render(); }
  if (d.stCond !== undefined) { S.stConds[e.target.checked ? 'add' : 'delete'](d.stCond); S.stEst = null; render(); }
  if (d.stRep) { S.stRepeats = Number(e.target.value); S.stEst = null; render(); }
});

JOB_PAGES.stattrial = ['research'];  // 진행 · 끝을 연구 화면에서 다시 그린다
JOB_DONE_MSG.stattrial = (j) => {
  stLoad().then(render);  // 끝난 시험을 기록 칸에 바로 보인다
  return `상태창 시험이 끝났어요: 본문 ${j.result ? j.result.drafts : 0}개. 연구 화면 '상태창 시험'에서 봐요.`;
};

Object.assign(actions, {
  stPickDefault() { S.stSel = new Set(S.st.pick); S.stEst = null; render(); },
  stToggle(id) { S.stOpen = S.stOpen === id ? '' : id; render(); },
  async stEstimate() {
    await run('비용 추정 중', async () => {
      S.stEst = await api('POST', `/projects/${enc(S.name)}/stattrial/estimate`, stPlan());
    });
  },
  stStart() {
    const p = stPlan();
    startJob('stattrial', null, p);
  },
});

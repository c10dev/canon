/* 사용량 · 비용 화면과 AI 요금 가격표. app.js 의 S, actions, api, render 를 그대로 쓴다. 서버 로직은 canon/usage.py.
   모든 AI 호출(웹, 백그라운드 작업, 자동 집필, 배치, 연구, 명령줄)의 토큰을 기록해 두고, 볼 때마다 가격표로 비용을 계산한다.
   작품 안에서 열면(#/p/<이름>/usage) 그 작품만, 밖에서 열면(#/usage) 모든 작품을 본다.
   화면은 기간 · 작품 거르기 → 비용 타일 → 날짜별 막대 → '어디에 썼나' 막대 목록 → 호출 목록 → 접힌 가격표(고치기로 폄) 순서다. */
'use strict';

Object.assign(S, {
  usage: null,      // GET /usage 결과
  usageDays: 30,    // 0 이면 전체 기간
  usageProject: '', // '' 이면 모든 작품
  usageList: 'recent',
  usageMore: false, // 호출 목록을 20건 넘게 펼침
  usageLimit: 60,   // 서버에서 받는 최근 호출 수 ('더 불러오기'로 늘린다)
  usageBar: null,   // 차트에서 고른 막대 (날짜 키)
  usageMetric: 'cost', // 막대 값: cost 비용 | calls 호출 수 (축은 하나만)
  usageTable: false,   // 막대 아래 날짜별 표를 폄
  usageBy: 'stage',    // '어디에 썼나' 나누는 기준: stage · model · project(작품을 고르면 화) · source
  usageByAll: false,   // 그 목록을 8줄 넘게 폄
  priceOpen: false,    // 가격표를 고치는 칸으로 폄
  prices: null,     // GET /usage/prices 결과
  priceRows: null,  // 고치는 중인 가격표 줄
  priceDirty: false,
});

const USAGE_DAYS = [[1, '오늘'], [7, '7일'], [30, '30일'], [90, '90일'], [0, '전체']];
const USAGE_STAGE = { plan: '계획', write: '본문', check: '검수', state: '상태 변경안', name: '이름 추천', revise: '부분 수정', illustration: '삽화 프롬프트', research: '연구 · 모델 실험' };
const USAGE_SOURCE = { web: '화면에서 직접', autorun: '자동 집필', research: '연구 화면', cli: '명령줄' };
const USAGE_TASK = {
  suggest: '설정 제안', arc: '기승전결 구조', series: '부 구성', nextarc: '다음 아크', convert: '장편 전환', rebuild: '장편 재구성 계획', rework: '재구성 다듬기', storyline: '이야기 줄기',
  recap_arc: '아크 요약', recap_part: '부 요약', fold_knows: '아는 정보 접기', plots: '화별 플롯', write: '본문', state: '상태 변경안', impact: '인과율 영향 분석',
  hook: '흡입력 판정', openings: '여는 방식 안', opening_drafts: '여러 안으로 쓰기',
  names: '이름 추천', style: '문체 분석', chat: 'AI 대화', edits: '부분 수정', auto: '자동 집필', sample: '샘플 비교',
  stage: '단계 시험', compare: '가려 비교', budget: '컨텍스트 크기', probe: '서버 점검', check: '검수', update: '상태 변경안', run: '연속 실행', fix: '부분 수정',
};

async function usageLoad(project) {
  if (project !== undefined) S.usageProject = project || '';
  const q = `days=${S.usageDays}&limit=${S.usageLimit}${S.usageProject ? `&project=${enc(S.usageProject)}` : ''}`;
  // 작품 고르기에 제목을 쓰고 기록이 없는 작품도 넣으려고 작품 목록도 받는다
  const [u, pr, list] = await Promise.all([api('GET', `/usage?${q}`), S.prices ? null : api('GET', '/usage/prices'),
    api('GET', '/projects').catch(() => null)]);
  S.usage = u;
  S.usageBar = null;
  if (list) usageTitles = Object.fromEntries(list.map((x) => [x.name, (x.title || '').trim()]));
  if (pr) pricesSet(pr);
}

async function pricesLoad() {
  if (S.priceDirty && S.prices) return;
  pricesSet(await api('GET', '/usage/prices'));
}

function pricesSet(pr) {
  S.prices = pr;
  S.priceRows = pr.rows.map((r) => ({ ...r }));
  S.priceDirty = false;
}

// 금액: 1달러 미만은 소수 넷째 자리까지 (한 번 호출은 대개 몇 센트도 안 된다)
function usd(c) {
  if (c == null) return '가격 모름';
  if (c === 0) return '$0';
  if (Math.abs(c) < 0.0001) return '$0.0001 미만';
  return Math.abs(c) < 1 ? `$${c.toFixed(4)}` : `$${c.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function tok(n) {
  if (n >= 1e6) return `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M`;
  if (n >= 1e4) return `${Math.round(n / 1e3)}K`;
  return Number(n || 0).toLocaleString();
}

let usageTitles = {};  // 폴더 이름 → 작품 제목
const usageName = (p) => (usageTitles[p] && usageTitles[p] !== p ? `${usageTitles[p]} (${p})` : p);

// 모델별 표의 백엔드 이름 (usage.backend_of 의 이름). Swift 앱 UsageText.backendLabel 과 같다
const USAGE_BACKEND = { local: '로컬 · 0원', claude: 'Claude 구독', 'claude-api': 'Claude API' };

function viewUsage() {
  const u = S.usage;
  const inProject = S.route[0] === 'p';
  const head = header(inProject ? `${esc(P().meta.title || S.name)} · 실험 · 본편과 분리` : 'Canon · 작품 밖', '사용량 · 비용',
    'AI를 부를 때마다 토큰을 기록하고 가격표로 비용을 계산해요. <strong>추정치</strong>라 청구 금액과 다를 수 있어요.',
    `<a class="btn" href="${(u && u.billing_url) || 'https://aistudio.google.com/usage'}" target="_blank" rel="noopener">AI Studio 실제 사용량 ↗</a>`);
  if (!u) return `${head}<div class="small">불러오는 중…</div>`;
  const t = u.total;
  const projects = [...new Set([...Object.keys(usageTitles), ...(u.projects || []), ...(S.usageProject ? [S.usageProject] : [])])].sort();
  const filters = `<div class="usage-filters">
      <div class="seg" role="group" aria-label="기간">${USAGE_DAYS.map(([d, l]) => `<button type="button" data-action="usageDays" data-arg="${d}" aria-pressed="${S.usageDays === d}">${l}</button>`).join('')}</div>
      <label class="usage-proj"><span class="label">작품</span>
        <select data-usage="project">
          <option value=""${S.usageProject ? '' : ' selected'}>모든 작품</option>
          ${projects.map((p) => `<option value="${esc(p)}"${p === S.usageProject ? ' selected' : ''}>${esc(usageName(p))}</option>`).join('')}
        </select></label>
    </div>`;
  if (!t.calls) {
    const span = USAGE_DAYS.find(([d]) => d === S.usageDays)[1];
    const where = S.usageProject ? `${esc(usageName(S.usageProject))}에서 ` : '';
    return `${head}<div class="usage-wrap">${filters}
      <section class="card"><div class="empty"><h2>${S.usageDays ? `${span} 동안 ` : ''}${where}AI 호출 기록이 없어요</h2>
        <p>이 화면이 생긴 뒤의 호출부터 기록해요. mock 호출은 기록하지 않아요.</p>
        ${S.usageDays ? '<button type="button" class="btn primary" data-action="usageDays" data-arg="0">전체 기간 보기</button>' : ''}</div></section>
      ${usagePriceSection()}</div>`;
  }
  const span = S.usageDays ? `${USAGE_DAYS.find(([d]) => d === S.usageDays)[1]} ` : '전체 기간 ';
  const tiles = `<div class="usage-tiles">
      <div class="usage-tile hero"><span class="k">${span}추정 비용</span><span class="usage-num">${usd(t.cost)}</span><span class="small">${t.unpriced ? `가격 모르는 호출 ${t.unpriced}번 빠짐` : '가격표 기준'}</span></div>
      <div class="usage-tile"><span class="k">호출</span><span class="usage-num">${t.calls.toLocaleString()}번</span><span class="small">${t.failed ? `실패 ${t.failed}` : '실패 없음'}${t.retries ? ` · 다시 요청 ${t.retries}` : ''}</span></div>
      <div class="usage-tile"><span class="k">토큰 입력 · 출력</span><span class="usage-num">${tok(t.in)} · ${tok(t.out)}</span><span class="small">${t.cached ? `캐시 ${tok(t.cached)} (싸게 매겨짐)` : '캐시 없음'} · 출력은 생각 토큰 포함</span></div>
      <div class="usage-tile"><span class="k">아낀 · 버린 비용</span><span class="usage-num">${usd(t.saved)} · ${usd(t.wasted)}</span><span class="small">${t.batch ? `배치 ${t.batch}번` : '배치 안 씀'} · 실패와 다시 요청</span></div>
    </div>`;
  return `${head}<div class="usage-wrap">${filters}
    ${u.unpriced.length ? `<div class="note warn usage-unpriced"><span>가격표에 없는 모델이 있어요. 이 호출은 비용에서 빠졌어요. 가격을 넣으면 다시 계산해요.</span>
      <span class="row">${u.unpriced.map((m) => `<span class="mono">${esc(m || '(이름 없음)')}</span>${m ? ` <button type="button" class="btn small" data-action="priceAddModel" data-arg="${esc(m)}">가격 넣기</button>` : ''}`).join(' ')}</span></div>` : ''}
    ${tiles}
    <section class="card" aria-labelledby="usage-chart-h">${usageChart(u)}</section>
    ${usageBreakdown(u)}
    ${usageCalls(u)}
    ${usagePriceSection()}</div>`;
}

/** 축 눈금: 0 부터 가장 큰 값을 덮는 깔끔한 간격 셋. 순수 함수(tests/test_research_js.py) */
function usageTicks(max) {
  if (!(max > 0)) return [0, 1, 2, 3];
  const raw = max / 3;
  const p = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw);
  return [0, 1, 2, 3].map((i) => Number((step * i).toPrecision(6)));
}

// 날짜별 막대. 값은 비용 · 호출 수 중 고른 하나(축은 하나만). 비용이 모두 0(로컬만 씀)이면 호출 수로 그린다.
function usageChart(u) {
  let byDay = Object.fromEntries(u.by_day.map((r) => [r.day, r]));
  const key = (x) => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
  // 기간 안의 날을 빈 날까지 모두 채운다 ('전체'는 첫 기록 날부터 오늘까지). 120일이 넘으면 주 단위로 묶는다.
  // 휴대폰 폭에서는 60일이 넘으면 묶는다 (90개 막대는 폭을 넘고 너무 가늘다)
  const today = new Date();
  const from = S.usageDays ? new Date(today.getFullYear(), today.getMonth(), today.getDate() - S.usageDays + 1)
    : u.by_day.length ? new Date(`${u.by_day.map((r) => r.day).sort()[0]}T00:00:00`) : today;
  let days = [];
  for (let x = new Date(from); x <= today; x = new Date(x.getFullYear(), x.getMonth(), x.getDate() + 1)) days.push(key(x));
  const narrow = mq('phone').matches;
  const weekly = days.length > 120 || (narrow && days.length > 60);
  if (weekly) {
    const weeks = {};
    days.forEach((d, i) => {
      const w = days[i - (i % 7)];
      const r = byDay[d];
      if (!weeks[w]) weeks[w] = { day: w, cost: 0, calls: 0, in: 0, out: 0, failed: 0 };
      if (r) ['cost', 'calls', 'in', 'out', 'failed'].forEach((k) => { weeks[w][k] += r[k] || 0; });
    });
    days = Object.keys(weeks);
    byDay = Object.fromEntries(Object.entries(weeks).filter(([, r]) => r.calls));
  }
  const byCost = S.usageMetric !== 'calls' && u.by_day.some((r) => r.cost > 0);
  const val = (r) => (r ? (byCost ? r.cost : r.calls) : 0);
  const ticks = usageTicks(Math.max(...days.map((d) => val(byDay[d])), 0));
  const top = ticks[3];
  const fmt = (v) => (byCost ? (v === 0 ? '$0' : `$${v < 1 ? v.toFixed(v < 0.1 ? 3 : 2) : v.toFixed(v < 10 ? 1 : 0)}`) : v.toLocaleString());
  const tips = {};
  const bars = days.map((d) => {
    const r = byDay[d];
    const h = r && val(r) ? Math.max(2, Math.round((val(r) / top) * 100)) : 0;
    const when = weekly ? `${d.slice(5).replace('-', '.')} 주` : d.slice(5).replace('-', '.');
    tips[d] = r ? `${when} · ${usd(r.cost)} · 호출 ${r.calls}번 · 입력 ${tok(r.in)} / 출력 ${tok(r.out)}${r.failed ? ` · 실패 ${r.failed}` : ''}` : `${when} · 호출 없음`;
    // 터치에는 title 툴팁이 없어 누르면 아래 줄에 값을 적는다. 키보드는 차트 하나에 초점을 두고 ←/→ 로 옮긴다
    return `<div class="usage-bar${S.usageBar === d ? ' on' : ''}" data-bar="${d}" title="${esc(tips[d])}"><i style="height:${h}%"></i></div>`;
  }).join('');
  usageTips = { days, tips };
  const lab = (d) => (d ? `${d.slice(5).replace('-', '.')}` : '');
  const mid = days.length > 8 ? [1, 2, 3].map((q) => days[Math.round((q * (days.length - 1)) / 4)]) : [];
  const picked = S.usageBar && tips[S.usageBar];
  const canCost = u.by_day.some((r) => r.cost > 0);
  return `<div class="between"><h2 id="usage-chart-h">${weekly ? '주별' : '날짜별'} ${byCost ? '추정 비용' : '호출 수'}</h2>
      <div class="row">${canCost ? `<div class="seg" role="group" aria-label="막대 값"><button type="button" data-action="usageMetric" data-arg="cost" aria-pressed="${byCost}">비용</button><button type="button" data-action="usageMetric" data-arg="calls" aria-pressed="${!byCost}">호출 수</button></div>` : ''}
        <button type="button" class="btn small ghost" data-action="usageTable" aria-expanded="${!!S.usageTable}">${S.usageTable ? '표 접기' : '표로 보기'}</button></div></div>
    <div class="usage-plot">
      <div class="usage-y" aria-hidden="true">${ticks.slice().reverse().map((v) => `<span>${fmt(v)}</span>`).join('')}</div>
      <div class="usage-chart" tabindex="0" role="group" aria-label="${weekly ? '주별' : '날짜별'} ${byCost ? '비용' : '호출 수'} 막대. ←/→ 키로 옮겨 값을 봐요" aria-describedby="usage-pick">${bars}</div>
      <div class="usage-x" aria-hidden="true">${[days[0], ...mid, days[days.length - 1]].map((d) => `<span>${lab(d)}</span>`).join('')}</div>
    </div>
    <div class="small usage-pick" id="usage-pick" aria-live="polite">${picked ? esc(picked) : '막대를 누르거나, 차트에 초점을 두고 ←/→ 키로 날짜별 값을 봐요.'}</div>
    ${S.usageTable ? `<div class="rs-scroll"><table class="rs-table"><thead><tr><th>${weekly ? '주' : '날'}</th><th>추정 비용</th><th>호출</th><th>입력</th><th>출력</th><th>실패</th></tr></thead><tbody>
      ${days.filter((d) => byDay[d]).reverse().map((d) => { const r = byDay[d]; return `<tr><td>${lab(d)}</td><td>${usd(r.cost)}</td><td>${r.calls}</td><td>${tok(r.in)}</td><td>${tok(r.out)}</td><td>${r.failed || ''}</td></tr>`; }).join('')}</tbody></table></div>` : ''}`;
}

let usageTips = { days: [], tips: {} };  // 마지막으로 그린 차트의 막대 목록과 설명

function usagePick(d) {
  if (!d || !usageTips.tips[d]) return;
  S.usageBar = d;
  document.querySelectorAll('.usage-bar.on').forEach((x) => x.classList.remove('on'));
  const bar = document.querySelector(`.usage-bar[data-bar="${d}"]`);
  if (bar) bar.classList.add('on');
  const line = $('#usage-pick');
  if (line) line.textContent = usageTips.tips[d];
}

document.addEventListener('click', (e) => {
  const bar = e.target.closest && e.target.closest('.usage-bar[data-bar]');
  if (bar) usagePick(bar.dataset.bar);
});

// 휴대폰: 차트를 누른 채 옆으로 밀면 손가락 아래 막대를 고른다 (막대가 44px 보다 가늘어서)
document.addEventListener('pointermove', (e) => {
  if (e.pointerType !== 'touch' || !e.target.closest || !e.target.closest('.usage-chart')) return;
  const el = document.elementFromPoint(e.clientX, e.clientY);
  const bar = el && el.closest && el.closest('.usage-bar[data-bar]');
  if (bar && bar.dataset.bar !== S.usageBar) usagePick(bar.dataset.bar);
});

document.addEventListener('keydown', (e) => {
  if (!e.target.classList || !e.target.classList.contains('usage-chart')) return;
  const { days } = usageTips;
  if (!days.length) return;
  const i = days.indexOf(S.usageBar);
  const at = { ArrowLeft: i < 0 ? days.length - 1 : i - 1, ArrowRight: i < 0 ? 0 : i + 1, Home: 0, End: days.length - 1 }[e.key];
  if (at === undefined) return;
  e.preventDefault();
  usagePick(days[Math.max(0, Math.min(days.length - 1, at))]);
});

/** '어디에 썼나': 나누는 기준 하나를 골라 막대 목록(한 계열)으로. 작품을 고르면 작품 대신 화 */
function usageBreakdown(u) {
  const one = !!S.usageProject;
  const by = S.usageBy === 'project' && one ? 'episode' : S.usageBy;
  const opts = [['stage', '단계'], ['model', '모델'], one ? ['episode', '화'] : ['project', '작품'], ['source', '어디서']];
  const rows = { stage: u.by_stage, model: u.by_model, project: u.by_project, episode: u.by_episode, source: u.by_source }[by] || [];
  const label = {
    stage: (r) => esc(USAGE_STAGE[r.stage] || r.stage || '기타'),
    model: (r) => `${esc(r.model || '(이름 없음)')} <span class="small">${USAGE_BACKEND[r.backend] || 'Gemini'}</span>`,
    project: (r) => (r.project ? `<a href="#/p/${enc(r.project)}/usage">${esc(usageName(r.project))}</a>` : '<span class="small">작품 밖 (연구 서버 점검 등)</span>'),
    episode: (r) => `<a href="#/p/${enc(r.project)}/write/${r.episode}">${r.episode}화</a>`,
    source: (r) => esc(USAGE_SOURCE[r.source] || r.source || '기타'),
  }[by];
  const byCost = rows.some((r) => r.cost > 0);
  const max = Math.max(...rows.map((r) => (byCost ? r.cost : r.calls)), 0) || 1;
  const shown = S.usageByAll ? rows : rows.slice(0, 8);
  const list = shown.map((r) => `<div class="usage-br"><span class="lb">${label(r)}${r.failed ? ` <span class="chip usage-fail">실패 ${r.failed}</span>` : ''}${r.batch ? ` <span class="chip">배치 ${r.batch}</span>` : ''}</span>
      <span class="bar" aria-hidden="true"><b style="width:${Math.round(((byCost ? r.cost : r.calls) / max) * 100)}%"></b></span>
      <span class="v">${r.unpriced && !r.cost ? '가격 모름' : usd(r.cost)}</span><span class="m">${r.calls.toLocaleString()}번</span><span class="m">${tok(r.in)} · ${tok(r.out)}</span></div>`).join('');
  return `<section class="card" aria-labelledby="usage-by-h">
    <div class="between"><h2 id="usage-by-h">어디에 썼나</h2>
      <div class="seg" role="group" aria-label="나누는 기준">${opts.map(([k, l]) => `<button type="button" data-action="usageBy" data-arg="${k === 'episode' ? 'project' : k}" aria-pressed="${by === k}">${l}</button>`).join('')}</div></div>
    ${rows.length ? `<div class="usage-bars"><div class="usage-br hd" aria-hidden="true"><span>${opts.find(([k]) => k === by)[1]}</span><span>${byCost ? '비용 비중' : '호출 비중'}</span><span class="v">추정 비용</span><span class="m">호출</span><span class="m">입력 · 출력</span></div>${list}</div>
      ${rows.length > shown.length ? `<div><button type="button" class="btn small ghost" data-action="usageByAll">${rows.length - shown.length}개 더 보기</button></div>` : ''}`
      : `<div class="small">${by === 'episode' ? '화가 정해지지 않은 호출(설정, 기획 등)은 빠져요.' : '기록 없음'}</div>`}
  </section>`;
}

// 입력 구성: 기록에 블록 크기가 있으면 가장 큰 두 블록과 전체 목록(펼치기). 크기는 글자 수
function usageBlocks(r) {
  if (!r.blocks || !r.blocks.length || !r.chars) return '';
  const pct = (v) => `${Math.round((v / r.chars) * 100)}%`;
  const top = r.blocks.slice(0, 2).map(([k, v]) => `${esc(k)} ${pct(v)}`).join(' · ');
  const all = r.blocks.map(([k, v]) => `<li>${esc(k)} <span class="small">${v.toLocaleString()}자 · ${pct(v)}</span></li>`).join('');
  return `<details class="small usage-blocks"><summary>${top}</summary><div>프롬프트 ${r.chars.toLocaleString()}자</div><ul>${all}</ul></details>`;
}

function usageCalls(u) {
  const all = S.usageList === 'trouble' ? u.trouble : u.recent;
  const list = S.usageMore ? all : all.slice(0, 20);
  const tabs = [['recent', '최근 호출'], ['trouble', `실패 · 다시 요청${u.trouble.length ? ` ${u.trouble.length}` : ''}`]];
  const rows = list.map((r) => {
    // 긴 오류는 앞부분만 보이고 눌러서 펼친다
    const err = (r.error || '').length > 60
      ? `<details class="usage-err"><summary>${esc(r.error.slice(0, 60))}…</summary>${esc(r.error)}</details>` : `<span class="small usage-err">${esc(r.error || '')}</span>`;
    const state = !r.ok ? `<span class="chip usage-fail">실패</span> ${err}`
      : (r.attempt > 1 ? '<span class="chip warn">다시 요청</span>' : '<span class="chip ok">성공</span>');
    const where = [r.project ? usageName(r.project) : '', r.episode != null ? `${r.episode}화` : ''].filter(Boolean).join(' · ');
    return `<div class="usage-call">
      <span class="when">${esc(fmtWhen(r.at))}</span>
      <span class="where">${esc(where || '-')}</span>
      <span class="task">${esc(USAGE_TASK[r.task] || USAGE_STAGE[r.stage] || r.task || '-')}<span class="s2">${esc(USAGE_STAGE[r.stage] || r.stage || '')} · ${esc(USAGE_SOURCE[r.source] || r.source || '')}</span></span>
      <span class="model">${esc(r.model)}${r.batch ? ' <span class="chip">배치</span>' : ''}</span>
      <span class="r tokens">${tok(r.in)} → ${tok(r.out + (r.thought || 0))}${r.cached ? `<span class="s2">캐시 ${tok(r.cached)}</span>` : ''}${r.thought ? `<span class="s2">생각 ${tok(r.thought)}</span>` : ''}${usageBlocks(r)}</span>
      <span class="r secs">${r.seconds != null ? `${r.seconds.toFixed(1)}초` : '-'}</span>
      <span class="r cost"><strong>${usd(r.cost)}</strong>${r.saved ? `<span class="s2">아낌 ${usd(r.saved)}</span>` : ''}</span>
      <span class="state">${state}</span></div>`;
  }).join('');
  return `<section class="card" aria-label="호출 목록">
    <div class="tabs" role="tablist" aria-label="호출 목록">${tabs.map(([k, l]) => `<button type="button" role="tab" aria-selected="${S.usageList === k}" aria-controls="usage-panel" data-action="usageList" data-arg="${k}">${l}</button>`).join('')}</div>
    <div role="tabpanel" id="usage-panel" aria-label="${esc((tabs.find(([k]) => k === S.usageList) || [, ''])[1])}">
    ${list.length ? `<div class="usage-calls"><div class="usage-call hd" aria-hidden="true"><span>시각</span><span>작품 · 화</span><span>작업</span><span>모델</span><span class="r">입력 → 출력</span><span class="r">걸린 시간</span><span class="r">추정 비용</span><span>결과</span></div>${rows}</div>
      <div class="row small">${usageMoreLine(u, all, list)} 형식이 어긋난 응답도 토큰은 쓴 것이라 비용에 들어가요.</div>`
      : '<div class="small">실패하거나 다시 요청한 호출이 없어요.</div>'}
    </div>
  </section>`;
}

// 목록 아래 줄: 몇 건을 보여 주는지와 펼치기 · 더 불러오기. 서버는 최근 S.usageLimit 건만 준다
function usageMoreLine(u, all, list) {
  const total = S.usageList === 'trouble' ? (u.trouble_total ?? all.length) : u.total.calls;
  const of = total > list.length ? ` (기간 전체 ${total.toLocaleString()}건 중)` : '';
  if (all.length > list.length) return `<button class="btn small" data-action="usageMore">최근 ${all.length}건 보기${of}</button>`;
  if (total > all.length && S.usageLimit < 1000) return `최근 ${list.length}건을 보여요${of}. <button class="btn small" data-action="usageLoadMore">더 불러오기</button>`;
  return `최근 ${list.length}건을 보여요${of}.`;
}

// ----- AI 요금 가격표 (사용량 · 비용 화면) -----

const PRICE_COLS = [['input', '입력'], ['output', '출력'], ['cached', '캐시 입력'], ['batch_input', '배치 입력'], ['batch_output', '배치 출력']];

/** 가격표 카드: 읽는 모양은 한 줄 요약과 '고치기', 고치는 동안은 표 (Card '읽기 카드와 고치기 카드') */
function usagePriceSection() {
  const pr = S.prices;
  if (S.priceOpen || S.priceDirty) return `<section class="card editing" id="price-box">${viewPrices()}</section>`;
  const mine = pr ? pr.rows.filter((r) => r.custom).length : 0;
  return `<section class="card tight" id="price-box"><div class="between"><div><h2>AI 요금 가격표</h2>
      <span class="small">${pr ? `${pr.rows.length}줄 · ${mine ? `내가 고친 줄 ${mine}개` : '고친 줄 없음'} · 기본값은 ${esc(pr.checked)}에 옮겼어요 · USD / 100만 토큰` : '불러오는 중…'}</span></div>
    <button type="button" class="btn small" data-action="priceToggle" aria-expanded="false">고치기</button></div></section>`;
}

function priceRedraw() {
  render();
}

async function priceSend(label, fn, done) {
  $('#busy-label').textContent = label;
  $('#busy-sec').textContent = '';
  $('#busy').hidden = false;
  try {
    pricesSet(await fn());
    if (S.usage) await usageLoad();
    toast(done);
  } catch (e) {
    toast(e.message, true);
  } finally {
    $('#busy').hidden = true;
    priceRedraw();
  }
}

function viewPrices() {
  const pr = S.prices;
  if (!pr || !S.priceRows) return '<h2>AI 요금 가격표</h2><div class="small">불러오는 중…</div>';
  const rows = S.priceRows.map((r, i) => {
    const st = r.custom ? '<span class="chip confirmed">고침</span>' : r.upcoming ? '<span class="chip written">예고</span>' : r.current ? '<span class="chip finalized">지금</span>' : '';
    const num = (k) => `<input type="number" min="0" step="0.001" inputmode="decimal" data-price="${i}.${k}" value="${r[k] == null ? '' : r[k]}" placeholder="${k === 'cached' ? r.input : k.startsWith('batch') ? (k === 'batch_input' ? r.input / 2 : r.output / 2) : ''}" aria-label="${esc(r.model)} ${PRICE_COLS.find(([c]) => c === k)[1]}">`;
    // 기본 줄은 지워도 저장하면 되살아난다 (기본값과 다른 줄만 설정에 남는다). 지우기 대신 고쳐 덮어쓰게 한다
    const fixed = r.custom === false;
    return `<tr><td class="price-model" data-label="모델"><input type="text" data-price="${i}.model" value="${esc(r.model)}" title="${esc(r.model)}" aria-label="모델 이름">${st || r.note ? `<div class="small">${st}${r.note ? ` ${esc(r.note)}` : ''}</div>` : ''}</td>
      <td data-label="적용 시작일"><input type="text" data-price="${i}.since" value="${esc(r.since)}" placeholder="처음부터" aria-label="적용 시작일" class="price-since"></td>
      ${PRICE_COLS.map(([k, l]) => `<td data-label="${l}">${num(k)}</td>`).join('')}
      <td class="price-act">${fixed ? '<span class="small" title="기본 줄은 지울 수 없어요. 값을 고치면 내 값으로 대신해요">기본 줄</span>'
        : `<button class="btn small" data-action="priceRemove" data-arg="${i}" aria-label="${esc(r.model || `${i + 1}번째`)} 줄 지우기">지우기</button>`}</td></tr>`;
  }).join('');
  return `<div class="between"><h2>AI 요금 가격표 <span class="small">고치는 중 · USD / 100만 토큰</span></h2><button type="button" class="btn small" data-action="priceToggle" aria-expanded="true">다 고쳤어요</button></div>
    <p class="desc">기본값은 ${esc(pr.checked)}에 <a href="${pr.url}" target="_blank" rel="noopener">Google Gemini API 가격표</a>(유료 등급 표준 요금)에서 옮긴 값이에요. 가격이 바뀌면 여기서 고치세요. 적용 시작일을 적은 줄은 그날부터의 호출에 쓰고(예고된 인상), 고치면 지난 기록과 자동 집필 예상 비용도 이 표로 다시 계산해요. 생각 토큰은 출력 요금, 배치 칸을 비우면 절반으로 쳐요. 로컬 모델은 0원이고, 표에 없는 Gemini 모델은 '가격 모름'으로 빠져요.</p>
    <div class="rs-scroll price-scroll"><table class="rs-table price-table">
      <thead><tr><th>모델</th><th>적용 시작일</th>${PRICE_COLS.map(([, l]) => `<th>${l}</th>`).join('')}<th><span class="sr-only">줄 조작</span></th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <div class="row">
      <button class="btn" data-action="priceAdd">줄 추가</button>
      <button class="btn primary" data-action="priceSave"${S.priceDirty ? '' : ' disabled'}>가격표 저장</button>
      ${S.priceDirty ? '<button class="btn" data-action="priceCancel">고친 것 버리기</button>' : ''}
      ${S.prices.rows.some((r) => r.custom) ? '<button class="btn danger" data-action="priceReset">기본값으로 되돌리기</button>' : ''}
    </div>
    <div class="small">모델 이름은 정확히 같거나 그 이름으로 시작하는 모델에 써요 (예: gemini-4-argon은 gemini-4-argon-001 에도). 기본 모델을 고치면 그 모델의 예고 줄까지 내 줄로 대신해요. 기본 줄은 지울 수 없고, 값을 고치면 내 값으로 대신해요.</div>`;
}

document.addEventListener('input', (e) => {
  const el = e.target;
  if (!el.dataset.price || !S.priceRows) return;
  const [i, k] = el.dataset.price.split('.');
  const row = S.priceRows[Number(i)];
  if (k === 'model' || k === 'since') row[k] = el.value;
  else row[k] = el.value === '' ? (['input', 'output'].includes(k) ? 0 : null) : Number(el.value);
  if (!S.priceDirty) {
    S.priceDirty = true;
    const save = document.querySelector('[data-action="priceSave"]');
    if (save) save.disabled = false;
  }
});

document.addEventListener('change', async (e) => {
  const el = e.target;
  if (el.dataset.usage !== 'project') return;
  if (S.route[0] === 'p' && el.value !== S.name) {
    location.hash = el.value ? `#/p/${enc(el.value)}/usage` : '#/usage';
    return;
  }
  await run('불러오는 중', () => usageLoad(el.value));
});

Object.assign(actions, {
  async usageDays(d) {
    S.usageDays = Number(d);
    await run('불러오는 중', () => usageLoad());
  },
  usageMetric(k) {
    S.usageMetric = k === 'calls' ? 'calls' : 'cost';
    render();
  },
  usageTable() {
    S.usageTable = !S.usageTable;
    render();
  },
  usageBy(k) {
    S.usageBy = k;
    S.usageByAll = false;
    render();
  },
  usageByAll() {
    S.usageByAll = true;
    render();
  },
  priceToggle() {
    if (S.priceOpen && S.priceDirty) return toast('고친 가격표를 저장하거나 버려요', true);
    S.priceOpen = !S.priceOpen;
    render();
    document.querySelector('#price-box [data-action="priceToggle"]')?.focus();
  },
  usageList(k) {
    S.usageList = k;
    render();
  },
  usageMore() {
    S.usageMore = true;
    render();
  },
  async usageLoadMore() {
    S.usageLimit = Math.min(1000, S.usageLimit + 200);
    S.usageMore = true;
    await run('불러오는 중', () => usageLoad());
  },
  priceAdd() {
    S.priceRows.push({ model: '', since: '', input: 0, output: 0, cached: null, batch_input: null, batch_output: null, note: '' });
    S.priceDirty = true;
    priceRedraw();
  },
  // 사용량 화면의 '가격 없는 모델' 경고에서: 그 이름으로 줄을 더하고 가격 칸으로 옮긴다
  priceAddModel(model) {
    S.priceOpen = true;
    let i = S.priceRows.findIndex((r) => r.model.trim() === model);
    if (i < 0) {
      S.priceRows.push({ model, since: '', input: 0, output: 0, cached: null, batch_input: null, batch_output: null, note: '' });
      i = S.priceRows.length - 1;
      S.priceDirty = true;
    }
    priceRedraw();
    const el = document.querySelector(`[data-price="${i}.input"]`);
    if (el) {
      el.scrollIntoView({ block: 'center' });
      el.focus();
    }
  },
  priceRemove(i) {
    S.priceRows.splice(i, 1);
    S.priceDirty = true;
    priceRedraw();
  },
  priceCancel() {
    pricesSet(S.prices);
    priceRedraw();
  },
  async priceSave() {
    const nameless = S.priceRows.findIndex((r) => !r.model.trim() && (r.input || r.output || r.cached || r.batch_input || r.batch_output || (r.since || '').trim()));
    if (nameless >= 0) {
      toast(`${nameless + 1}번째 줄에 모델 이름을 적으세요. 이름이 없으면 그 줄은 저장되지 않아요`, true);
      const el = document.querySelector(`[data-price="${nameless}.model"]`);
      if (el) el.focus();
      return;
    }
    const free = S.priceRows.filter((r) => r.model.trim() && (!(r.input > 0) || !(r.output > 0))).map((r) => r.model.trim());
    if (free.length && !confirm(`${free.join(', ')}의 입력이나 출력 가격이 0원이에요. 비용이 0원으로 계산돼요. 이대로 저장할까요?`)) return;
    const rows = S.priceRows.filter((r) => r.model.trim()).map(({ custom, current, upcoming, ...r }) => r);
    await priceSend('가격표 저장하는 중', () => api('PUT', '/usage/prices', { rows }), '가격표를 저장했어요. 비용을 다시 계산했어요');
  },
  async priceReset() {
    if (!confirm('고친 가격을 모두 지우고 기본 가격표로 되돌릴까요?')) return;
    await priceSend('되돌리는 중', () => api('DELETE', '/usage/prices'), '기본 가격표로 되돌렸어요');
  },
});

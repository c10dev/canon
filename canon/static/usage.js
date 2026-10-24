/* 사용량 · 비용 화면과 AI 요금 가격표. app.js 의 S, actions, api, render 를 그대로 쓴다. 서버 로직은 canon/usage.py.
   모든 AI 호출(웹, 백그라운드 작업, 자동 집필, 배치, 연구, 명령줄)의 토큰을 기록해 두고, 볼 때마다 가격표로 비용을 계산한다.
   작품 안에서 열면(#/p/<이름>/usage) 그 작품만, 밖에서 열면(#/usage) 모든 작품을 본다. 가격표는 설정 화면과 이 화면에서 고친다. */
'use strict';

Object.assign(S, {
  usage: null,      // GET /usage 결과
  usageDays: 30,    // 0 이면 전체 기간
  usageProject: '', // '' 이면 모든 작품
  usageList: 'recent',
  usageMore: false, // 호출 목록을 20건 넘게 펼침
  usageLimit: 60,   // 서버에서 받는 최근 호출 수 ('더 불러오기'로 늘린다)
  usageBar: null,   // 차트에서 고른 막대 (날짜 키)
  prices: null,     // GET /usage/prices 결과
  priceRows: null,  // 고치는 중인 가격표 줄
  priceDirty: false,
});

const USAGE_DAYS = [[1, '오늘'], [7, '7일'], [30, '30일'], [90, '90일'], [0, '전체']];
const USAGE_STAGE = { plan: '계획', write: '본문', check: '검수', state: '상태 변경안', name: '이름 추천', revise: '부분 수정', illustration: '삽화 프롬프트', research: '연구 · 모델 실험' };
const USAGE_SOURCE = { web: '화면에서 직접', autorun: '자동 집필', research: '연구 화면', cli: '명령줄' };
const USAGE_TASK = {
  suggest: '설정 제안', arc: '기승전결 구조', series: '부 구성', nextarc: '다음 아크', convert: '장편 전환', rebuild: '장편 재구성 계획', rework: '재구성 다듬기', storyline: '이야기 줄기',
  recap_arc: '아크 요약', recap_part: '부 요약', plots: '화별 플롯', write: '본문', state: '상태 변경안', impact: '인과율 영향 분석',
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

const usageWhen = (iso) => fmtDateTime(iso);  // 날짜 형식은 app.js fmtDateTime 하나로

let usageTitles = {};  // 폴더 이름 → 작품 제목
const usageName = (p) => (usageTitles[p] && usageTitles[p] !== p ? `${usageTitles[p]} (${p})` : p);

function viewUsage() {
  const u = S.usage;
  const inProject = S.route[0] === 'p';
  const head = header(inProject ? esc(P().meta.title || S.name) : 'Canon', '사용량 · 비용',
    'AI를 부를 때마다 토큰 수를 기록하고 가격표로 비용을 계산해요. <strong>추정치</strong>라 Google 청구 금액과 다를 수 있어요.',
    `<a class="btn" href="${(u && u.billing_url) || 'https://aistudio.google.com/usage'}" target="_blank" rel="noopener">AI Studio 실제 사용량 ↗</a>`);
  if (!u) return `${head}<div class="small">불러오는 중…</div>`;
  const t = u.total;
  const projects = [...new Set([...Object.keys(usageTitles), ...(u.projects || []), ...(S.usageProject ? [S.usageProject] : [])])].sort();
  const filters = `<div class="between usage-filters">
      <div class="row" role="group" aria-label="기간">${USAGE_DAYS.map(([d, l]) => `<button class="btn${S.usageDays === d ? ' primary' : ''}" data-action="usageDays" data-arg="${d}" aria-pressed="${S.usageDays === d}">${l}</button>`).join('')}</div>
      <label class="row small">작품
        <select data-usage="project" aria-label="작품">
          <option value=""${S.usageProject ? '' : ' selected'}>모든 작품</option>
          ${projects.map((p) => `<option value="${esc(p)}"${p === S.usageProject ? ' selected' : ''}>${esc(usageName(p))}</option>`).join('')}
        </select></label>
    </div>`;
  if (!t.calls) {
    return `${head}${filters}<div class="note plain">이 기간${S.usageProject ? `에 ${esc(usageName(S.usageProject))}` : ''}의 AI 호출 기록이 없어요. 이 화면이 생긴 뒤의 호출부터 기록해요 (mock 은 기록하지 않음).</div>
      ${usagePriceSection()}`;
  }
  const tiles = [
    ['추정 비용', usd(t.cost), `${t.unpriced ? `가격 모르는 호출 ${t.unpriced}번 제외` : '가격표 기준'}`],
    ['호출', `${t.calls.toLocaleString()}번`, `${t.failed ? `실패 ${t.failed}` : '실패 없음'}${t.retries ? ` · 다시 요청 ${t.retries}` : ''}`],
    ['입력 토큰', tok(t.in), t.cached ? `캐시 ${tok(t.cached)} (싸게 매겨짐)` : '캐시 없음'],
    ['출력 토큰', tok(t.out), '생각(thinking) 토큰 포함'],
    ['배치로 아낀 비용', usd(t.saved), t.batch ? `배치 ${t.batch}번` : '배치 안 씀'],
    ['실패 · 재시도 비용', usd(t.wasted), '형식 오류로 다시 받은 것 포함'],
  ];
  return `${head}${filters}
    ${u.unpriced.length ? `<div class="note warn">가격표에 없는 모델이 있어요. 이 호출은 비용에서 빠졌어요. 가격을 넣으면 다시 계산해요.
      <div class="row">${u.unpriced.map((m) => `<span class="mono">${esc(m || '(이름 없음)')}</span>${m ? ` <button class="btn small" data-action="priceAddModel" data-arg="${esc(m)}">가격 넣기</button>` : ''}`).join(' ')}</div></div>` : ''}
    <div class="usage-tiles">${tiles.map(([k, v, s]) => `<div class="usage-tile"><div class="small">${k}</div><div class="usage-num">${v}</div><div class="small">${s}</div></div>`).join('')}</div>
    <section class="card">${usageChart(u)}</section>
    <div class="cols">
      <div class="col">${usageTable('단계별', u.by_stage, (r) => esc(USAGE_STAGE[r.stage] || r.stage || '기타'))}
        ${usageTable('모델별', u.by_model, (r) => `${esc(r.model || '(이름 없음)')} <span class="small">${r.backend === 'local' ? '로컬 · 0원' : 'Gemini'}</span>`)}</div>
      <div class="col">${S.usageProject
        ? usageTable('화별', u.by_episode, (r) => `<a href="#/p/${enc(r.project)}/write/${r.episode}">${r.episode}화</a>`, '화가 정해지지 않은 호출(설정, 기획 등)은 빠져요')
        : usageTable('작품별', u.by_project, (r) => r.project ? `<a href="#/p/${enc(r.project)}/usage">${esc(usageName(r.project))}</a>` : '<span class="small">작품 밖 (연구 서버 점검 등)</span>')}
        ${usageTable('어디서 불렀나', u.by_source, (r) => esc(USAGE_SOURCE[r.source] || r.source || '기타'))}</div>
    </div>
    ${usageCalls(u)}
    ${usagePriceSection()}`;
}

// 날짜별 비용 막대. 비용이 모두 0(로컬만 씀)이면 호출 수로 그린다.
function usageChart(u) {
  let byDay = Object.fromEntries(u.by_day.map((r) => [r.day, r]));
  const key = (x) => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
  // 기간 안의 날을 빈 날까지 모두 채운다 ('전체'는 첫 기록 날부터 오늘까지). 120일이 넘으면 주 단위로 묶는다.
  // 휴대폰 폭에서는 60일이 넘으면 묶는다 (90개 막대는 폭을 넘고 너무 가늘어 누를 수 없다)
  const today = new Date();
  const from = S.usageDays ? new Date(today.getFullYear(), today.getMonth(), today.getDate() - S.usageDays + 1)
    : u.by_day.length ? new Date(`${u.by_day.map((r) => r.day).sort()[0]}T00:00:00`) : today;
  let days = [];
  for (let x = new Date(from); x <= today; x = new Date(x.getFullYear(), x.getMonth(), x.getDate() + 1)) days.push(key(x));
  const narrow = window.matchMedia('(max-width: 640px)').matches;
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
  const byCost = u.by_day.some((r) => r.cost > 0);
  const val = (r) => (r ? (byCost ? r.cost : r.calls) : 0);
  const max = Math.max(...days.map((d) => val(byDay[d])), 0) || 1;
  const tips = {};
  const bars = days.map((d) => {
    const r = byDay[d];
    const h = r ? Math.max(2, Math.round((val(r) / max) * 100)) : 0;
    const when = weekly ? `${d} 주` : d;
    tips[d] = r ? `${when}: ${usd(r.cost)} · 호출 ${r.calls}번 · 입력 ${tok(r.in)} / 출력 ${tok(r.out)}${r.failed ? ` · 실패 ${r.failed}` : ''}` : `${when}: 호출 없음`;
    // 터치에는 title 툴팁이 없어 누르면 아래 줄에 값을 적는다. 키보드는 차트 하나에 초점을 두고 ←/→ 로 옮긴다
    return `<div class="usage-bar${S.usageBar === d ? ' on' : ''}" data-bar="${d}" title="${esc(tips[d])}"><i style="height:${h}%"></i></div>`;
  }).join('');
  usageTips = { days, tips };
  const first = days[0] || '';
  const last = days[days.length - 1] || '';
  const picked = S.usageBar && tips[S.usageBar];
  return `<div class="between"><h2>${weekly ? '주별' : '날짜별'} ${byCost ? '추정 비용' : '호출 수'}</h2><span class="small">가장 많은 ${weekly ? '주' : '날'} ${byCost ? usd(max) : `${max}번`} · 막대를 누르면 자세히</span></div>
    <div class="usage-chart" tabindex="0" role="group" aria-label="${weekly ? '주별' : '날짜별'} ${byCost ? '비용' : '호출 수'} 막대. ←/→ 키로 옮겨 값을 봐요" aria-describedby="usage-pick">${bars}</div>
    <div class="between small"><span>${first.slice(5)}</span><span>${last.slice(5)}</span></div>
    <div class="small usage-pick" id="usage-pick" aria-live="polite">${picked ? esc(picked) : '막대를 누르거나, 차트에 초점을 두고 ←/→ 키로 날짜별 값을 봐요.'}</div>`;
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

function usageTable(title, rows, label, note = '') {
  if (!rows.length) return `<section class="card"><h2>${title}</h2><div class="small">${note || '기록 없음'}</div></section>`;
  const total = rows.reduce((a, r) => a + r.cost, 0) || 1;
  return `<section class="card"><h2>${title}</h2>
    <div class="rs-scroll"><table class="rs-table usage-table">
      <thead><tr><th>${title.replace(/별$/, '')}</th><th>호출</th><th>입력</th><th>출력</th><th>추정 비용</th><th aria-label="비중"></th></tr></thead>
      <tbody>${rows.map((r) => `<tr><td>${label(r)}${r.failed ? ` <span class="chip usage-fail">실패 ${r.failed}</span>` : ''}${r.batch ? ` <span class="chip">배치 ${r.batch}</span>` : ''}</td>
        <td>${r.calls.toLocaleString()}</td><td>${tok(r.in)}</td><td>${tok(r.out)}</td><td><strong>${r.unpriced && !r.cost ? '가격 모름' : usd(r.cost)}</strong></td>
        <td class="usage-share"><i style="width:${Math.round((r.cost / total) * 100)}%"></i></td></tr>`).join('')}</tbody>
    </table></div>${note ? `<div class="small">${note}</div>` : ''}</section>`;
}

function usageCalls(u) {
  const all = S.usageList === 'trouble' ? u.trouble : u.recent;
  const list = S.usageMore ? all : all.slice(0, 20);
  const tabs = [['recent', `최근 호출`], ['trouble', `실패 · 재시도${u.trouble.length ? ` ${u.trouble.length}` : ''}`]];
  const rows = list.map((r) => {
    // 긴 오류는 앞부분만 보이고 눌러서 펼친다 (전문을 칸에 넣으면 표가 두 배로 넓어진다)
    const err = (r.error || '').length > 60
      ? `<details class="usage-err"><summary>${esc(r.error.slice(0, 60))}…</summary>${esc(r.error)}</details>` : `<span class="small usage-err">${esc(r.error || '')}</span>`;
    const state = !r.ok ? `<span class="chip usage-fail">실패</span> ${err}`
      : (r.attempt > 1 ? '<span class="chip written">다시 요청</span>' : '<span class="chip finalized">성공</span>');
    const where = [r.project, r.episode != null ? `${r.episode}화` : ''].filter(Boolean).join(' ');
    return `<tr><td>${usageWhen(r.at)}</td><td>${esc(where || '-')}</td>
      <td>${esc(USAGE_TASK[r.task] || USAGE_STAGE[r.stage] || r.task || '-')}<div class="small">${esc(USAGE_STAGE[r.stage] || r.stage || '')} · ${esc(USAGE_SOURCE[r.source] || r.source || '')}</div></td>
      <td>${esc(r.model)}${r.batch ? ' <span class="chip">배치</span>' : ''}</td>
      <td>${tok(r.in)}${r.cached ? `<div class="small">캐시 ${tok(r.cached)}</div>` : ''}</td><td>${tok(r.out + (r.thought || 0))}${r.thought ? `<div class="small">생각 ${tok(r.thought)}</div>` : ''}</td>
      <td>${r.seconds != null ? `${r.seconds.toFixed(1)}초` : '-'}</td><td><strong>${usd(r.cost)}</strong>${r.saved ? `<div class="small">아낌 ${usd(r.saved)}</div>` : ''}</td><td>${state}</td></tr>`;
  }).join('');
  return `<section class="card">
    <div class="tabs" role="tablist" aria-label="호출 목록">${tabs.map(([k, l]) => `<button type="button" role="tab" aria-selected="${S.usageList === k}" aria-controls="usage-panel" data-action="usageList" data-arg="${k}">${l}</button>`).join('')}</div>
    <div role="tabpanel" id="usage-panel" aria-label="${esc((tabs.find(([k]) => k === S.usageList) || [, ''])[1])}">
    ${list.length ? `<div class="rs-scroll"><table class="rs-table">
      <thead><tr><th>시각</th><th>작품</th><th>작업</th><th>모델</th><th>입력</th><th>출력</th><th>걸린 시간</th><th>추정 비용</th><th>결과</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
      <div class="row small">${usageMoreLine(u, all, list)} 형식이 어긋난 응답도 토큰은 쓴 것이라 비용에 들어가요.</div>`
      : '<div class="small">실패하거나 다시 요청한 호출이 없어요.</div>'}
    </div>
  </section>`;
}

// 목록 아래 줄: 몇 건을 보여 주는지와 펼치기 · 더 불러오기. 서버는 최근 S.usageLimit 건만 준다
function usageMoreLine(u, all, list) {
  const total = S.usageList === 'trouble' ? (u.trouble_total ?? all.length) : u.total.calls;
  const of = total > list.length ? ` (기간 전체 ${total.toLocaleString()}건 중)` : '';
  if (all.length > list.length) return `<button class="btn" data-action="usageMore">최근 ${all.length}건 보기${of}</button>`;
  if (total > all.length && S.usageLimit < 1000) return `최근 ${list.length}건을 보여요${of}. <button class="btn" data-action="usageLoadMore">더 불러오기</button>`;
  return `최근 ${list.length}건을 보여요${of}.`;
}

// ----- AI 요금 가격표 (설정 화면과 사용량 화면에서 같이 쓴다) -----

const PRICE_COLS = [['input', '입력'], ['output', '출력'], ['cached', '캐시 입력'], ['batch_input', '배치 입력'], ['batch_output', '배치 출력']];

function usagePriceSection() {
  return `<section class="card" id="price-box">${viewPrices()}</section>`;
}

// 설정 화면에서는 아직 저장하지 않은 설정 입력이 사라지지 않게 가격표 상자만 다시 그린다
function priceRedraw() {
  const box = $('#price-box');
  if (box && S.route[0] === 'settings') box.innerHTML = viewPrices();
  else render();
}

async function priceSend(label, fn, done) {
  $('#busy-text').textContent = label;
  $('#busy').hidden = false;
  try {
    pricesSet(await fn());
    if (S.usage && S.route[0] !== 'settings') await usageLoad();
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
  return `<div class="between"><h2>AI 요금 가격표</h2><span class="small">USD / 100만 토큰</span></div>
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
    <div class="small">모델 이름은 정확히 같거나 그 이름으로 시작하는 모델에 써요 (예: gemini-4-argon 은 gemini-4-argon-001 에도). 기본 모델을 고치면 그 모델의 예고 줄까지 내 줄로 대신해요. 기본 줄은 지울 수 없고, 값을 고치면 내 값으로 대신해요.</div>`;
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
    await priceSend('가격표 저장 중', () => api('PUT', '/usage/prices', { rows }), '가격표를 저장했어요. 비용을 다시 계산했어요');
  },
  async priceReset() {
    if (!confirm('고친 가격을 모두 지우고 기본 가격표로 되돌릴까요?')) return;
    await priceSend('되돌리는 중', () => api('DELETE', '/usage/prices'), '기본 가격표로 되돌렸어요');
  },
});

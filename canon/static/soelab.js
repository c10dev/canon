/* 쇠맛 실험실 화면(서버 soelab.py, 작품 밖 화면 #/soelab[/corpus | judge | redo | metrics[/<지표 id>] | patterns[/check] | log]).
   쇠맛 지표가 사람 글과 AI 글을 가르는지, 이 작가의 판정과 같은 쪽을 가리키는지 맞춰 본다. AI 를 부르지 않는다.
   저장은 작품 밖 <CANON_HOME>/.soelab/ 이고 작품 데이터(project.json)는 바꾸지 않는다.
   가려 읽기: 서버가 가린 조각(판정 대기 · 다시 읽기 예정 · 끝나지 않은 '이번 10개')의 출처 · 원천 · 묶음 · 모델 · 지표 값 · 정규식 밑줄을
   어느 응답에도 싣지 않는다. 화면도 판정하는 동안 목차의 지표 · 패턴 · 기록 줄을 접는다. 정답은 '이번 10개'를 마치면 한꺼번에 보인다.
   배치는 공용 목차 틀(outline.js)의 왼쪽 목차 + 오른쪽 칸(.soe-main, container soe: 760 · 560px). 문장 고르기 방식은 폭이 아니라
   (pointer: coarse) 로 정한다(손가락 기기는 '문장 누르기'가 기본, ⋯ 메뉴에서 바꾼다).
   app.js 의 S, actions, api, run, render, header, esc, toast, showError, menuBtn, isTyping, fmtDate 를 쓴다.
   soeVerdict(labstats.verdict 와 같은 규칙) · soeSentences · soeSentenceAt(metrics.sentence_spans 와 같은 경계) · soeRedoDue(soelab.redo_open 과
   같은 날) · soeNext · soeSteps · soeRound · soeMarkMerge 는 DOM 없는 순수 함수 (tests/test_soelab_js.py). CSS 는 JS 에서 주입한다. */
'use strict';

Object.assign(S, {
  soe: null,        // 화면 값 (GET /soelab, soelab.screen)
  soePane: 'overview',
  soeArg: '',       // 지표 id
  soeSrc: null,     // 모으기 원천 후보 (GET /soelab/sources)
  soeCol: null,     // 모으기 카드 { open, sel: {열쇠: {...}}, preview, err }
  soePieces: null,  // 조각 목록
  soeJ: null,       // 판정 { mode: judge | redo, piece, sents, verdict, spans, clean, sel: [a, b] | null, memo, menu, t0 }
  soeBatch: null,   // 끝난 '이번 10개' 정답 (GET /soelab/batch/<번호>)
  soeBatchOpen: -1, // 펼친 줄
  soeMetric: null,  // 지표 하나
  soePat: null,     // 패턴 혼동표
  soePatOpen: '',   // 펼친 패턴
  soeOthersAll: false, // '기타' 문장 모두 보기
  soeCheck: null,   // 패턴 확인
  soeCheckKind: '', // 고른 패턴 (비우면 차례대로)
  soeCheckHist: [], // 매긴 차례 (← 앞 문장 다시 매기기)
  soeLog: null,
  soeOpen: new Set(), // 모델별 줄을 편 지표
  soeAll: false,
  soeTap: null,     // 문장 누르기 (null 이면 pointer: coarse 를 따른다)
  soeRead: null,    // 읽기 전용으로 연 조각
});

/* ----- 순수 함수 (tests/test_soelab_js.py) ----- */

const SOE_FIRST = 40;
const SOE_GOAL = 90;
const SOE_REDO_DAYS = 7;
const SOE_STRONG = 0.7;

/** 판정 칩 id: 동시 구간 [lo, hi] 와 값으로. labstats.verdict 와 같은 규칙 */
function soeVerdict(lo, hi, value) {
  if (lo > 0.5) return value >= SOE_STRONG ? 'yes' : 'weak';
  if (hi < 0.5) return 'reverse';
  return 'none';
}

/** 칩 id → [글자, 클래스]. na 는 칩 없이 '–' */
const SOE_CHIPS = {
  yes: ['맞아요', 'v-yes'], weak: ['약해요', 'v-weak'], none: ['근거 없음', 'v-none'], reverse: ['반대 방향', 'v-rev'],
  few: ['표본 부족', 'v-few'], tbd: ['아직 모름', 'v-none v-tbd'], na: ['–', ''],
};

/** 문장 경계 [시작, 끝] (metrics.sentence_spans 와 같은 경계: 문장 끝 기호 뒤 빈칸이나 줄바꿈에서 나누고 앞뒤 빈칸은 뺀다) */
function soeSentences(text) {
  const re = /(?<=[.!?…])\s+|(?<=[.!?…]["'”’」』)])\s+|\n+/g;
  const out = [];
  let at = 0;
  const push = (end) => {
    const piece = text.slice(at, end);
    const body = piece.trim();
    if (body) {
      const lead = piece.length - piece.trimStart().length;
      out.push([at + lead, at + lead + body.length]);
    }
  };
  let m;
  while ((m = re.exec(text))) {
    push(m.index);
    at = m.index + m[0].length;
  }
  push(text.length);
  return out;
}

/** 글자 자리 at 이 든 문장 번호 (없으면 -1). soelab._sent_of 와 같다 */
function soeSentenceAt(spans, at) {
  return spans.findIndex(([a, b]) => a <= at && at < b);
}

/** 다시 읽을 수 있는 날: 첫 판정 날짜(그 시각의 날짜) + 7일. today(YYYY-MM-DD) 가 그날이거나 뒤면 open */
function soeRedoDue(firstAt, today, days = SOE_REDO_DAYS) {
  const [y, m, d] = String(firstAt).slice(0, 10).split('-').map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + days));
  const date = t.toISOString().slice(0, 10);
  return { date, open: String(today).slice(0, 10) >= date };
}

/** 판정 진행 글: 1차 동안 '34/40 · 1차', 그 뒤 '41/90' */
function soeRound(judged, goal) {
  return goal <= SOE_FIRST && judged <= SOE_FIRST ? `${judged}/${SOE_FIRST} · 1차` : `${judged}/${SOE_GOAL}`;
}

/** 머리 주 버튼(다음 할 일 하나). st: { pieces, judged, goal, stopped, inBatch, queueLeft, redoDue, held, spareReady, stale, checkLeft }.
    차례: 다시 읽기 → 판정 일관성 보류면 예비 열기 → 판정(1차 · 60 · 90) → 1차 · 60 끝 카드가 주 버튼(null) → 다시 채점하기 → 패턴 확인 → 조각 모으기 */
function soeNext(st) {
  if (st.redoDue > 0) return { kind: 'redo', label: `다시 읽기 ${st.redoDue}개` };
  if (st.held && st.spareReady > 0) return { kind: 'spare', label: `다시 읽기 ${st.spareReady}개 더` };
  if (st.pieces > 0 && !st.stopped && st.queueLeft > 0 && st.judged < SOE_GOAL) {
    const verb = st.inBatch > 0 ? '판정 이어 하기' : '판정 10개 하기';
    if (st.judged < SOE_FIRST) return { kind: 'judge', label: `${verb} (1차 ${SOE_FIRST - st.judged}개 남음)` };
    if (st.judged >= st.goal && st.inBatch === 0) return null;  // 1차 · 60개 끝 카드의 '계속 읽기'가 주 버튼
    return { kind: 'judge', label: `${verb} (${st.goal}개까지 ${st.goal - st.judged}개 남음)` };
  }
  if (st.stale) return { kind: 'rescore', label: '다시 채점하기 · AI 없음' };
  if (st.checkLeft > 0) return { kind: 'check', label: `패턴 확인 이어 하기 (${st.checkLeft}개 남음)` };
  return { kind: 'collect', label: '+ 조각 모으기' };
}

/** 목차 단계 넷. sc 는 화면 값(soelab.screen). state: ok(끝남) · now(지금 할 단계) · todo · warn(열린 다시 읽기) */
function soeSteps(sc) {
  const o = sc.by_origin || {};
  const rs = sc.redo_state || {};
  const date = (iso) => fmtDate(`${iso}T00:00:00`);
  const corpus = sc.pieces ? { right: `사람 ${o.human || 0} · AI ${o.ai || 0}`, state: 'ok' } : { right: '비었어요', state: 'now' };
  const jr = soeRound(sc.judged, sc.goal) + (sc.stopped ? ' · 멈춤' : '');
  const judge = { right: jr, state: sc.judged >= SOE_GOAL ? 'ok' : sc.pieces && !sc.stopped && sc.queue_left ? 'now' : 'todo' };
  let redo;
  if (rs.due) redo = { right: `${rs.done}/${rs.target} · ${rs.due}개 열림`, state: 'warn' };
  else if (rs.target && rs.done >= rs.target) redo = { right: `${rs.done}/${rs.target}`, state: 'ok' };
  else if (rs.opens) redo = { right: `${date(rs.opens)}부터`, state: 'todo' };
  else redo = { right: `${rs.done || 0}/${rs.target || 0}`, state: 'todo' };
  const rep = sc.report;
  const metrics = { right: rep ? `보고서 ${fmtDate(rep.made)}` : sc.pieces ? '채점 전' : '–', state: 'todo' };
  return [
    { id: 'corpus', label: '말뭉치', ...corpus },
    { id: 'judge', label: '판정', ...judge },
    { id: 'redo', label: '다시 읽기', ...redo },
    { id: 'metrics', label: '지표 대조', ...metrics },
  ];
}

/** 문장 표시 합치기: 새 표시와 겹치는 표시를 지우고 넣는다(시작 자리 차례) */
function soeMarkMerge(spans, add) {
  return [...spans.filter((s) => s.end <= add.start || s.start >= add.end), add].sort((a, b) => a.start - b.start);
}

/* ----- 불러오기 ----- */

const SOE_PANES = { corpus: '말뭉치', judge: '가려 읽기', redo: '다시 읽기', metrics: '지표 대조', patterns: '패턴 혼동표', log: '기록' };
const soeTapOn = () => (S.soeTap === null ? matchMedia('(pointer: coarse)').matches === true : S.soeTap);
const soeKind = (k) => ((S.soe && S.soe.kinds) || []).find(([id]) => id === k)?.[1] || k;

async function soeLoad(part, arg) {
  S.soePane = !part ? 'overview' : part === 'patterns' && arg === 'check' ? 'check' : part === 'metrics' && arg ? 'metric' : part in SOE_PANES ? part : 'overview';
  S.soeArg = arg || '';
  S.soeRead = null;
  try {
    S.soe = await api('GET', '/soelab');
    if (!S.soe.pieces || S.soePane === 'corpus') S.soeSrc = await api('GET', '/soelab/sources');
    if (!S.soe.pieces && !S.soeCol) S.soeCol = { open: true, sel: {}, preview: null, err: '' };
    if (S.soePane === 'corpus') S.soePieces = await api('GET', '/soelab/pieces');
    if (S.soePane === 'judge') await soeJudgeLoad();
    if (S.soePane === 'redo') await soeRedoLoad();
    if (S.soePane === 'metric') S.soeMetric = await api('GET', `/soelab/metrics/${encodeURIComponent(S.soeArg)}`);
    if (S.soePane === 'patterns') S.soePat = await api('GET', '/soelab/patterns');
    if (S.soePane === 'check') { S.soeCheck = await api('GET', `/soelab/check?kind=${encodeURIComponent(S.soeCheckKind)}`); S.soeCheckHist = []; }
    if (S.soePane === 'log') S.soeLog = await api('GET', '/soelab/reports');
  } catch (e) {
    S.soe = S.soe || { error: e.message };
    if (S.soe.error === undefined) toast(e.message, true);
  }
}

function soeTake(v, mode) {
  S.soe = v.screen;
  const p = v.piece;
  if (!p) { S.soeJ = null; return; }
  if (S.soeJ && S.soeJ.piece.id === p.id && S.soeJ.mode === mode) return;  // 고치던 판정은 그대로 둔다
  S.soeJ = { mode, piece: p, sents: soeSentences(p.text), verdict: '', spans: [], clean: false, sel: null, memo: '', menu: -1, t0: Date.now() };
}

async function soeJudgeLoad() {
  soeTake(await api('GET', '/soelab/judge'), 'judge');
  S.soeBatch = null;
  if (!S.soeJ && S.soe.ended) S.soeBatch = await api('GET', `/soelab/batch/${S.soe.ended}`);
}

async function soeRedoLoad() {
  soeTake(await api('GET', '/soelab/redo'), 'redo');
}

function soeGo(part) {
  const to = `#/soelab${part ? `/${part}` : ''}`;
  if (location.hash === to) soeLoad(...(part || '').split('/')).then(render);
  else location.hash = to;
}

/* ----- 틀: 머리 · 목차 ----- */

function viewSoe() {
  const sc = S.soe;
  if (!sc) return `${header('실험 · 본편과 분리', '쇠맛 실험실', '')}<div class="note plain">불러오는 중…</div>`;
  if (sc.error) return `${header('실험 · 본편과 분리', '쇠맛 실험실', '')}<div class="note err">${esc(sc.error)}</div>`;
  setTimeout(soePlace);
  const main = {
    overview: soeOverview, corpus: soeCorpus, judge: soeJudgePane, redo: soeRedoPane, metrics: soeMetricsPane, metric: soeMetricOne,
    patterns: soePatterns, check: soeCheckPane, log: soeLogPane,
  }[S.soePane]();
  return `${soeHead()}${outlineDoc(soeToc(), `<div class="soe-main${['judge', 'redo'].includes(S.soePane) && S.soeJ ? ' narrow' : ''}">${S.soeRead ? soeReadCard() : ''}${main}</div>`, { wide: true, cls: 'soe-wrap' })}`;
}

function soeNextState() {
  const sc = S.soe;
  return { pieces: sc.pieces, judged: sc.judged, goal: sc.goal, stopped: sc.stopped, inBatch: sc.in_batch, queueLeft: sc.queue_left,
    redoDue: (sc.redo_state || {}).due || 0, held: sc.held, spareReady: (sc.spare || {}).ready || 0, stale: sc.pieces > 0 && ['corpus', 'none'].includes(sc.stale), checkLeft: (sc.check.total || 0) - (sc.check.done || 0) };
}

const SOE_NEXT_GO = { redo: 'redo', judge: 'judge', check: 'patterns/check', collect: 'corpus' };

/** 머리 주 버튼. 판정 · 다시 읽기 화면은 판정 띠의 '저장하고 다음'이 주 버튼이라 감춘다. 빈 개요는 모으기 카드의 버튼이 주 버튼 */
function soeGoBtn() {
  const sc = S.soe;
  const pane = S.soePane;
  if (pane === 'judge' && !S.soeJ && S.soeBatch) {
    if (soeMilestone()) return '';
    const left = soeNext({ ...soeNextState(), inBatch: 0, redoDue: 0 });
    return `<button type="button" class="btn" data-action="soeSeen" data-arg="home">오늘은 여기까지</button>
      <button type="button" class="btn primary" data-action="soeSeen" data-arg="next">${left && left.kind === 'judge' ? esc(left.label.replace('판정 10개 하기', '다음 10개 시작')) : '다음 10개 시작'}</button>`;
  }
  if (['judge', 'redo', 'check', 'metric', 'log'].includes(pane)) return pane === 'metric' ? '<a class="btn" href="#/soelab/metrics">지표 대조로</a>' : '';
  if (!sc.pieces || (pane === 'corpus' && S.soeCol && S.soeCol.open)) return '';
  if (pane === 'patterns') {
    const left = (sc.check.total || 0) - (sc.check.done || 0);
    return left ? `<a class="btn primary" href="#/soelab/patterns/check">패턴 확인 이어 하기 (${left}개 남음)</a>` : '';
  }
  if (pane === 'corpus') return '<button type="button" class="btn primary" data-action="soeCollectOpen">+ 조각 모으기</button>';
  const nx = soeNext(soeNextState());
  if (!nx) return '';
  if (nx.kind === 'spare') return `<button type="button" class="btn primary" data-action="soeSpareOpen">${esc(nx.label)}</button>`;
  if (nx.kind === 'rescore') return `<button type="button" class="btn primary" data-action="soeRescore">${esc(nx.label)}</button>`;
  if (nx.kind === 'collect') return `<button type="button" class="btn primary" data-action="soeCollectOpen">${esc(nx.label)}</button>`;
  return `<a class="btn primary" href="#/soelab/${SOE_NEXT_GO[nx.kind]}">${esc(nx.label)}</a>`;
}

const SOE_DESC = {
  overview: '쇠맛 지표가 사람 글과 AI 글을 가르는지, 이 작가의 판단과 같은 쪽을 가리키는지 맞춰 봐요. AI를 부르지 않아요.',
  corpus: '사람 글과 AI 글 조각을 모아요. 조각은 2,000자 안팎으로 자르고, 원천이 티 나지 않게 같은 규칙으로 다듬어요.',
  judge: '어디서 온 글인지 가려 두었어요. 읽고 AI 티가 나는지 판정해 주세요. 티가 나는 문장은 골라 갈래를 붙여 주세요.',
  redo: '7일 전에 판정한 조각을 다시 읽어요. 처음 판정과 얼마나 같은지로 판정 일관성을 셈해요.',
  metrics: '지표마다 사람 글과 AI 글을 얼마나 가르는지, 작가 판정과 같은 쪽을 가리키는지 보여요. 줄을 누르면 그 지표를 자세히 봐요.',
  patterns: '정규식이 잡은 문장이 정말 글티인지 맞춰 봐요. 정밀도는 패턴 확인에서, 재현율은 가려 읽기의 문장 표시에서 셈해요. 값은 1,000자당이고 한 화 상한은 쓰지 않아요.',
  check: '정규식이 잡은 문장만 빠르게 봐요. 글티가 맞는지 하나씩 매기면 패턴의 정밀도를 셈해요. 가려 읽기와 섞지 않아요.',
  log: '다시 채점할 때마다 보고서를 남겨요. 지표 버전이 다른 보고서끼리는 숫자를 섞지 않아요.',
  metric: '',
};

function soeHead() {
  const pane = S.soePane;
  const crumb = pane === 'overview' ? '실험 · 본편과 분리'
    : pane === 'metric' ? '실험 · 본편과 분리 › <a href="#/soelab">쇠맛 실험실</a> › <a href="#/soelab/metrics">지표 대조</a>'
      : pane === 'check' ? '실험 · 본편과 분리 › <a href="#/soelab">쇠맛 실험실</a> › <a href="#/soelab/patterns">패턴 혼동표</a>'
        : '실험 · 본편과 분리 › <a href="#/soelab">쇠맛 실험실</a>';
  const title = pane === 'overview' ? '쇠맛 실험실' : pane === 'metric' ? (S.soeMetric ? S.soeMetric.label : '지표') : pane === 'check' ? '패턴 확인' : SOE_PANES[pane];
  let desc = SOE_DESC[pane];
  if (pane === 'metric' && S.soeMetric && S.soeMetric.row) {
    const r = S.soeMetric.row;
    desc = `출처 기준 ${soeChip(r.source.chip)}${r.author ? ` · 작가 판정 기준 ${soeChip(r.author.held && S.soe.held ? 'none' : r.author.chip, r.author.held && S.soe.held ? '보류' : '')}` : ''}`;
  } else desc = esc(desc);
  const tap = soeTapOn();
  const menu = () => `<button type="button" class="pop-item" data-action="soeTapToggle">${tap ? '문장 고르기: 끌어 고르기로 바꾸기' : '문장 고르기: 문장 누르기로 바꾸기'}</button>
    ${S.soe.stopped ? '<button type="button" class="pop-item" data-action="soeResume">판정 다시 이어 하기</button>' : ''}
    ${S.soe.pieces ? '<button type="button" class="pop-item" data-action="soeRescore">다시 채점하기 · AI 없음</button>' : ''}
    <a class="pop-item" href="#/soelab/log">기록 · 보고서</a><a class="pop-item" href="#/revlab">역설계 실험</a><a class="pop-item" href="#/">작품 목록</a>`;
  return header(crumb, title, desc, `${menuBtn('soe', '⋯', menu, { cls: 'btn icon-btn', aria: '실험실 메뉴' })}${soeGoBtn()}`);
}

const soeLink = (href, inner, cur = false, cls = '') => `<a class="outline-item${cls ? ` ${cls}` : ''}" href="${href}"${cur ? ' aria-current="page"' : ''}>${inner}</a>`;
const soeChip = (id, text = '') => (id === 'na' ? '<span class="dash">–</span>' : `<span class="chip ${SOE_CHIPS[id][1]}">${esc(text || SOE_CHIPS[id][0])}</span>`);

/** 목차 지표 줄의 기준: 작가 판정이 있고 판정 일관성이 보류가 아니면 작가 판정 기준 */
function soeBasis(rep) {
  if (!rep) return 'source';
  const has = rep.metrics.some((r) => r.author);
  return has && !S.soe.held ? 'author' : 'source';
}

function soeToc() {
  const sc = S.soe;
  const pane = S.soePane;
  const judging = pane === 'judge' || pane === 'redo';
  const steps = soeSteps(sc).map((s, i) => soeLink(`#/soelab/${s.id}`, `<span class="n ${s.state === 'warn' ? '' : s.state}" aria-hidden="true">${s.state === 'ok' ? '✓' : i + 1}</span>
    <span class="tl">${s.label}</span><span class="st${s.state === 'warn' ? ' warn' : ''}">${esc(s.right)}</span><span class="sr-only">${{ ok: '끝남', now: '지금 할 단계', warn: '열림', todo: '' }[s.state]}</span>`,
  pane === s.id || (s.id === 'metrics' && pane === 'metric' && false), s.state === 'warn' ? 'warn' : '')).join('');
  const rep = sc.report;
  let rest;
  if (judging) {
    rest = '<p class="small soe-toc-fold">판정하는 동안에는 지표 · 패턴 · 기록을 접어 둬요. 이번 10개를 마치면 다시 보여요.</p>';
  } else {
    const basis = soeBasis(rep);
    const head = basis === 'author' ? (rep.first_round ? '지표 · 1차 작가 판정 기준' : '지표 · 작가 판정 기준') : '지표 · 출처 기준';
    const rows = (sc.metric_ids || []).map(([id, label]) => {
      const r = rep && rep.metrics.find((x) => x.id === id);
      const cell = r ? (basis === 'author' && r.author ? r.author : r.source) : null;
      const st = cell ? soeChip(cell.chip) : '<span class="dash">–</span>';
      return soeLink(`#/soelab/metrics/${id}`, `<span class="tl">${esc(label)}</span><span class="st">${st}</span>`, pane === 'metric' && S.soeArg === id);
    }).join('');
    const chk = sc.check || {};
    rest = `<span class="outline-h">${head}</span>${rows}<span class="outline-h">전체</span>
      ${soeLink('#/soelab/patterns', '<span class="tl">패턴 혼동표</span><span class="st"></span>', pane === 'patterns')}
      ${soeLink('#/soelab/patterns/check', `<span class="tl">패턴 확인</span><span class="st">${chk.total ? `${chk.done}/${chk.total}` : '–'}</span>`, pane === 'check')}
      ${soeLink('#/soelab/log', `<span class="tl">기록</span><span class="st">${rep ? fmtDate(rep.made) : ''}</span>`, pane === 'log')}`;
  }
  const now = pane === 'overview' ? '개요' : pane === 'metric' ? (S.soeMetric ? S.soeMetric.label : '지표') : pane === 'check' ? '패턴 확인' : SOE_PANES[pane];
  const over = soeLink('#/soelab', `<span class="n${pane === 'overview' ? ' now' : ''}" aria-hidden="true">◎</span><span class="tl">개요</span><span class="st">${sc.pieces ? `조각 ${sc.pieces}` : ''}</span>`, pane === 'overview');
  return outlineNav({ id: 'soe-toc', label: '실험실 목차', now: esc(now), body: `${over}<span class="outline-h">단계</span>${steps}${rest}` });
}

/* ----- 범위 막대 · 칸 ----- */

const soePct = (x) => `${Math.max(0, Math.min(100, x * 100)).toFixed(1)}%`;
const soeNum = (x) => (x == null ? '–' : Number(x).toFixed(2));

function soeRng(s, dim = false) {
  if (!s || s.value == null || !s.ci95) return '';
  const [lo, hi] = s.ci95;
  return `<span class="rng${dim ? ' dim' : ''}" aria-hidden="true"><span class="h"></span><span class="s"></span><span class="i" style="left:${soePct(lo)};width:${soePct(hi - lo)}"></span><span class="d" style="left:${soePct(s.value)}"></span></span>`;
}

/** 표 한 칸: 범위 막대 · 값 [95% 범위] · 칩. ref 면 칩 대신 '참고'(모델별 줄), held 면 흐리게 칩 대신 '보류' */
function soeCell(s, { ref = false, held = false, split = false, empty = '–', short = false } = {}) {
  if (!s) return `<span class="dash">${esc(empty)}</span>`;
  if (s.value == null) return s.chip === 'few' ? soeChip('few') : '<span class="dash">–</span>';
  const tail = ref ? (s.chip === 'few' ? soeChip('few') : '<span class="ref">참고</span>') : held ? '<span class="held">보류</span>' : soeChip(s.chip);
  const range = `[${soeNum(s.ci95[0])}–${soeNum(s.ci95[1])}]`;  // 넓은 표의 본 줄은 범위 글자를 낭독용으로만 둔다(막대가 보인다). 1280px 창에서 가로 굴림을 줄이려고
  return `<span class="cell${held ? ' dim' : ''}">${soeRng(s, held)}<span class="v">${soeNum(s.value)}</span><span class="r${short ? ' sr-only' : ''}">${range}</span>${tail}${split ? '<span class="chip v-split">모델마다 달라요</span>' : ''}</span>`;
}

const soePairCell = (pr) => (pr && pr.n ? `${pr.agree}/${pr.n}${pr.same_side ? '<br><span class="small">같은 쪽</span>' : ''}` : '<span class="dash">–</span>');

/** 믿을 수 있는 지표 표 (개요 · 지표 대조). 넓은 칸은 표, 560px 아래는 지표마다 펴는 줄 목록 */
function soeTable(rep) {
  const sc = S.soe;
  const held = sc.held;
  const models = rep.metrics.some((r) => r.by_model.length > 1);
  const authorHead = `작가 판정 기준<br>가르는 힘${held ? ' · 보류' : ''}`;
  const rows = rep.metrics.map((r) => {
    const open = S.soeAll || S.soeOpen.has(r.id);
    const tog = models ? `<button type="button" class="btn ghost small mtog" data-action="soeModels" data-arg="${r.id}" aria-expanded="${open}">모델별 ${open ? '▾' : '▸'}</button>` : '';
    const main = `<tr class="link${open && models ? ' open' : ''}"><td><a href="#/soelab/metrics/${r.id}">${esc(r.label)}</a><br><span class="small">${esc(r.where)} · ${esc(r.direction)}</span></td>
      <td>${soeCell(r.source, { split: r.model_split, short: true })}</td><td class="num">${soePairCell(r.pairs)}</td>
      <td>${soeCell(r.author, { held: held && !!r.author, empty: '판정 20개부터', short: true })}</td><td class="num">${esc(r.threshold)}</td><td>${tog}</td></tr>`;
    const sub = open && models ? r.by_model.map((m) => `<tr class="mrow"><td>사람 대 ${esc(soeModelName(m.model))}<br><span class="ref">AI 조각 ${m.ai_pieces || 0} · 묶음 ${m.ai_groups || 0}</span></td>
      <td>${soeCell(m, { ref: true })}${m.chip !== 'few' && m.ci95 && m.ci95[0] != null && m.ci95[0] <= 0.5 && m.ci95[1] >= 0.5 ? '<br><span class="ref">범위가 0.5에 걸쳐요</span>' : ''}</td><td class="num dash">–</td><td class="dash">–</td><td></td><td></td></tr>`).join('') : '';
    return main + sub;
  }).join('');
  const list = rep.metrics.map((r) => `<details class="soe-mline"><summary><span class="tl"><b>${esc(r.label)}</b><span class="small">${esc(r.direction)}</span></span>
      <span class="row">${(soeBasis(rep) === 'author' && r.author ? soeChip(r.author.chip) : soeChip(r.source.chip))}<span aria-hidden="true">›</span></span>${r.model_split ? '<span class="chip v-split">모델마다 달라요</span>' : ''}</summary>
      <div class="soe-mbody"><div class="between"><span class="small">출처 기준</span>${soeCell(r.source)}</div>
      <div class="between"><span class="small">작가 판정 기준</span>${soeCell(r.author, { held: held && !!r.author, empty: '판정 20개부터' })}</div>
      ${models ? `<details class="soe-mref"><summary>모델별 · 참고</summary>${r.by_model.map((m) => `<div class="between"><span class="small">사람 대 ${esc(soeModelName(m.model))} · 조각 ${m.ai_pieces || 0}</span>${soeCell(m, { ref: true })}</div>`).join('')}</details>` : ''}
      <a class="btn small" href="#/soelab/metrics/${r.id}">이 지표 자세히</a></div></details>`).join('');
  const notes = rep.notes.map((n) => `<div class="note warn">${esc(n)}</div>`).join('');
  return `<section class="card" aria-labelledby="soe-tbl-h"><div class="between"><h2 id="soe-tbl-h">믿을 수 있는 지표</h2>
      <div class="legend"><span class="sw"><span class="rng" style="width:40px" aria-hidden="true"><span class="h"></span><span class="i" style="left:55%;width:30%"></span><span class="d" style="left:70%"></span></span>믿을 수 있는 범위와 값</span><span>가운데 금 0.5 · 짧은 금 0.7</span></div></div>
    ${notes}
    <div class="rs-scroll soe-wide"><table class="soe-table"><thead><tr><th scope="col">지표 · 잰 곳 · 방향</th><th scope="col">출처 기준 가르는 힘<br>사람 대 모든 AI</th><th scope="col" class="num">짝 같은<br>방향</th>
      <th scope="col"${held ? ' class="dim"' : ''}>${authorHead}</th><th scope="col" class="num">지금<br>경고 기준</th><th scope="col">${models ? `<button type="button" class="btn ghost small mtog" data-action="soeModelsAll" aria-pressed="${S.soeAll}" aria-label="모델별 줄 모두 ${S.soeAll ? '접기' : '펴기'}">모델별 모두${S.soeAll ? ' ▾' : ' ▸'}</button>` : ''}</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <div class="soe-narrow">${list}</div>
    <p class="small">범위 막대는 95% 범위예요. 숫자 범위는 지표 하나 화면과 모델별 줄에 적어요.</p>${models ? '<p class="small">모델별 줄은 참고 값이에요(95% 범위, 칩 없음). 칩은 사람 대 모든 AI 칸으로만 정해요. 한 모델에서 맞는데 다른 모델에서 못 가르거나 반대이면 칩 옆에 \'모델마다 달라요\'를 붙여요.</p>' : ''}
    <details class="more"><summary>원래 이름과 범위 규칙</summary><p class="small">가르는 힘은 AUROC예요. 표의 범위는 95% 범위예요. 칩은 지표 14개를 함께 보는 99.64% 범위로 정해요: 하한이 0.5를 넘고 값이 0.7 이상이면 맞아요, 0.7 아래면 약해요, 범위가 0.5에 걸치면 근거 없음, 상한이 0.5 아래면 반대 방향이에요. 묶음이 20개 아래면 '맞아요' 대신 '약해요'까지만 달아요. 같은 방향 비율은 역설계 짝(원문과 되쓰기)의 부호 일치예요. 우연일 가능성(Holm 보정 p)은 지표 하나 화면에 있어요.</p></details></section>`;
}

const soeModelName = (m) => {
  const b = String(m || '').split(':')[0];
  return { claude: 'Claude', gemini: 'Gemini', other: '그 밖', unknown: '모름', '': '모름' }[b] || b;
};

/* ----- 개요 ----- */

function soeVerLine(rep) {
  const sc = S.soe;
  return `<p class="ver-line">지표 버전 ${esc(sc.metrics_version)} · 조각 ${sc.pieces} · 묶음 ${sc.groups} · 시드 7${rep ? ` · 보고서 ${fmtDate(rep.made)}` : ''}</p>`;
}

function soeStaleNote() {
  const st = S.soe.stale;
  if (!S.soe.pieces) return '';
  if (st === 'none') return '<div class="note info">아직 채점하지 않았어요. \'다시 채점하기\'를 누르면 AI 없이 바로 셈해요.</div>';
  if (st === 'corpus') return '<div class="note info">보고서 뒤에 말뭉치나 지표 버전이 바뀌었어요. 다시 채점하면 새 보고서가 생기고, 지난 보고서는 기록에 남아요.</div>';
  return '';
}

function soeBar(label, value, share, sub = '', cls = '') {
  return `<div class="bar"><div class="lb"><span>${label}</span><b>${value}</b></div><div class="tr" role="img" aria-label="${esc(label)} ${esc(String(value))}">${cls === 'split' ? share : `<i class="${cls}" style="width:${soePct(share)}"></i>`}</div>${sub ? `<span class="sub">${sub}</span>` : ''}</div>`;
}

function soeProgress() {
  const sc = S.soe;
  const o = sc.by_origin || {};
  const h = o.human || 0;
  const a = o.ai || 0;
  const tot = h + a || 1;
  const rs = sc.redo_state;
  const target = sc.goal;
  const eg = sc.eligible_groups || {};
  return `<section class="card"><div class="between"><h2>진행</h2><span class="small">1차 40 · 두 번째 보고 60 · 목표 90 · 문장 표시 60 · 다시 읽기 30</span></div>
    <div class="bars">
      ${soeBar('말뭉치 균형', `사람 ${h} · AI ${a}`, `<i class="h" style="width:${soePct(h / tot)}"></i><i class="a" style="width:${soePct(a / tot)}"></i>`, `사람 글 ${eg.human || 0}화 · AI 글 ${eg.ai || 0}화 (가려 읽기에 쓸 화)`, 'split')}
      ${soeBar('판정', soeRound(sc.judged, target), sc.judged / Math.max(1, target === SOE_FIRST ? SOE_FIRST : SOE_GOAL), sc.judged ? `오늘 ${sc.judged_today}개 · 10개씩 ${sc.batches}번` : '아직 없어요')}
      ${soeBar('다시 읽기', `${rs.done}/${rs.target}`, rs.target ? rs.done / rs.target : 0, rs.due ? `${rs.due}개 열렸어요` : rs.opens ? `${fmtDate(`${rs.opens}T00:00:00`)}부터 열려요` : '첫 판정 7일 뒤부터')}
      ${soeBar('문장 표시', `${sc.marked}/60`, sc.marked / 60, `표시할 곳 없음 ${sc.clean} 포함`)}
    </div></section>`;
}

function soeConsCard(rep) {
  const c = (rep && rep.consistency) || { pairs: 0 };
  if (!c.pairs) {
    return `<section class="card"><h2>판정 일관성</h2><p class="small">아직 다시 읽은 조각이 없어요. 판정한 조각 가운데 셋에 하나를 7일 뒤에 다시 읽고, 처음 판정과 얼마나 같은지 셈해요. 원래 이름은 Cohen κ예요.</p></section>`;
  }
  const chips = c.preview ? '<span class="row"><span class="chip">미리보기</span><span class="chip v-weak">보류</span></span>' : c.hold ? '<span class="chip v-weak">보류</span>' : '<span class="chip v-yes">믿을 만해요</span>';
  return `<section class="card"><div class="between"><h2>판정 일관성</h2>${chips}</div>
    <div class="soe-big"><span class="num">${soeNum(c.kappa)}</span><span class="small">아래 끝 ${soeNum(c.ci95[0])} · 보류 기준 ${soeNum(c.hold_below)} · 다시 읽기 ${c.pairs}개</span></div>
    <p class="small">${c.preview ? '30개 아래라 결론은 늘 보류예요. 크게 흔들리는지(0.3 아래)만 미리 봐요.' : '같은 조각을 7일 뒤 다시 읽은 판정이 처음 판정과 얼마나 같은지예요.'} 원래 이름은 Cohen κ예요.</p></section>`;
}

function soeHoldCard() {
  const sc = S.soe;
  if (!sc.held) return '';
  const sp = sc.spare || {};
  const more = sp.ready
    ? `<b>재판정을 늘려 주세요. 정답을 숨겨 둔 예비 조각 ${sp.ready}개를 다시 읽으면 판정 일관성을 다시 셈해요.</b> 예비 조각도 첫 판정 7일 뒤에 열려요.`
    : `<b>판정을 더 하면 재판정이 따라 늘어요(남은 조각 ${sc.queue_left || 0}개).</b> 지금 다시 읽기로 열 수 있는 예비 조각은 없어요.`;
  return `<div class="note warn" role="status"><b>판정이 흔들려 결론을 보류해요.</b> 판정 일관성의 아래 끝이 보류 기준 0.30보다 낮아요. 작가 판정 기준 칸을 흐리게 보여요.<br>${more}</div>`;
}

function soeLegendCard() {
  return `<section class="card"><h2>이렇게 읽어요</h2>
    <div class="row">${['yes', 'weak', 'none', 'reverse', 'few'].map((k) => soeChip(k)).join('')}<span class="dash">–</span></div>
    <p class="small">1차(40개) 결과에서는 '근거 없음'을 ${soeChip('tbd')}으로 보여요. 판정이 적어 중간 지표를 아직 못 가려서예요.</p>
    <p class="small">결론은 이 작가의 판단과 사람 원문에 대한 것이에요. 사람 원문이 좋은 글이라는 뜻은 아니에요. '–'는 그 원천에서 잴 수 없는 지표예요.</p></section>`;
}

function soeOverview() {
  const sc = S.soe;
  if (!sc.pieces) {
    return `<section class="card soe-empty"><h2>아직 조각이 없어요</h2><p>역설계 실험이나 작품 화에서 조각을 모으면, AI 없이 바로 어느 지표가 사람 글과 AI 글을 가르는지 보여 드려요.</p></section>${soeCollectCard()}`;
  }
  const rep = sc.report;
  return `${soeVerLine(rep)}${soeStaleNote()}${soeProgress()}${soeHoldCard()}${rep ? soeTable(rep) : ''}<div class="cols2">${soeConsCard(rep)}${soeLegendCard()}</div>`;
}

/* ----- 말뭉치 ----- */

function soeColSel(key) {
  const c = S.soeCol;
  if (!c.sel[key]) c.sel[key] = { on: false, known: false };
  return c.sel[key];
}

function soeColSources() {
  const c = S.soeCol;
  const out = [];
  Object.entries(c.sel).forEach(([key, v]) => {
    if (!v.on) return;
    const [kind, id] = [key.split(':')[0], key.slice(key.indexOf(':') + 1)];
    if (kind === 'lab') out.push({ kind: 'revlab', lab: Number(id), known: v.known });
    if (kind === 'ep') out.push({ kind: 'episode', project: id, first: Number(v.first) || 0, last: Number(v.last) || 0, known: v.known });
    if (kind === 'edit') out.push({ kind: 'edit', project: id });
    if (kind === 'research') out.push({ kind: 'research', path: v.path || '', known: v.known });
    if (kind === 'paste' && v.text && v.text.trim()) out.push({ kind: 'paste', text: v.text, title: v.title || '', origin: v.origin || 'human', model: v.origin === 'ai' ? v.model || '' : '', known: v.known });
  });
  return out;
}

const soeCheck = (key, field, on, label) => `<label class="soe-chk"><input type="checkbox" data-soe-col="${esc(key)}|${field}"${on ? ' checked' : ''}><span>${label}</span></label>`;

function soeCollectCard() {
  if (!S.soeCol) S.soeCol = { open: true, sel: {}, preview: null, err: '' };
  const c = S.soeCol;
  if (!c.open) return '';
  const src = S.soeSrc || { labs: [], projects: [], research: {}, models: [], cap: 20 };
  const row = (key, title, desc, extra = '', known = true) => {
    const v = soeColSel(key);
    return `<div class="src-row"><input type="checkbox" id="soe-c-${esc(key)}" data-soe-col="${esc(key)}|on"${v.on ? ' checked' : ''}>
      <label for="soe-c-${esc(key)}" class="src-t"><b>${title}</b><span class="small">${desc}</span></label>
      <div class="src-x">${extra}</div><div>${known ? soeCheck(key, 'known', v.known, '읽은 적 있는 작품') : ''}</div></div>`;
  };
  const labs = src.labs.map((l) => row(`lab:${l.id}`, `역설계 실험 · ${esc(l.title)}`, `원문은 사람, 되쓰기 ${l.takes}판은 AI · 짝으로 묶어요${l.models.length ? ` · 모델 ${esc(l.models.join(' · '))}(기록)` : ''}`, `<span class="small">${l.episodes}화</span>`)).join('');
  const eps = src.projects.filter((p) => p.written).map((p) => {
    const v = soeColSel(`ep:${p.name}`);
    const range = `<span class="row soe-range"><input type="number" min="1" aria-label="${esc(p.title)} 첫 화" data-soe-col="ep:${esc(p.name)}|first" value="${esc(v.first || '')}" placeholder="${p.first}">~<input type="number" min="1" aria-label="${esc(p.title)} 끝 화" data-soe-col="ep:${esc(p.name)}|last" value="${esc(v.last || '')}" placeholder="${p.last}">화</span>`;
    return row(`ep:${p.name}`, `작품 화 · ${esc(p.title)}`, `AI가 쓴 화 ${p.written}개${p.models.length ? ` · 모델 ${esc(p.models.join(' · '))}(사용량 기록에서 짐작)` : ' · 모델 모름'}`, range);
  }).join('');
  const edits = src.projects.filter((p) => p.edits).map((p) => row(`edit:${p.name}`, `수정 기록 '쇠맛 줄이기' · ${esc(p.title)}`, `전후 ${p.edits}쌍 · 정답으로 쓰지 않고 지표가 못 보는 차이 칸에만 써요`, '', false)).join('');
  const rs = src.research || {};
  const research = rs.exists ? row('research', '연구 말뭉치', `${esc(rs.path)} · 글 ${rs.files}편 · 사람 글(근대 소설)`) : '';
  const pv = soeColSel('paste');
  const human = (pv.origin || 'human') === 'human';
  const paste = `<div class="src-row paste"><input type="checkbox" id="soe-c-paste" data-soe-col="paste|on"${pv.on ? ' checked' : ''}>
    <label for="soe-c-paste" class="src-t"><b>붙여 넣기 · 작가가 가져온 사람 글</b><span class="small">출처를 직접 정해요 · 한 화에서 길게보다 여러 화에서 짧게가 좋아요 · 'n화' 제목 줄이나 <code>===</code> 줄로 화를 나눠요</span></label>
    <div class="src-x row"><label class="sr-only" for="soe-p-origin">출처</label><select id="soe-p-origin" data-soe-col="paste|origin"><option value="human"${human ? ' selected' : ''}>출처: 사람 글</option><option value="ai"${pv.origin === 'ai' ? ' selected' : ''}>출처: AI 글</option><option value="unknown"${pv.origin === 'unknown' ? ' selected' : ''}>출처: 모름</option></select>
      <label class="sr-only" for="soe-p-model">모델</label><select id="soe-p-model" data-soe-col="paste|model"${pv.origin === 'ai' ? '' : ' disabled'}>${pv.origin === 'ai' ? src.models.map(([k, l]) => `<option value="${k}"${(pv.model || '') === k ? ' selected' : ''}>모델: ${l}</option>`).join('') : `<option>모델: ${human ? '사람 글이라 없음' : '모름'}</option>`}</select></div>
    <div>${soeCheck('paste', 'known', pv.known, '읽은 적 있는 작품')}</div>
    ${pv.on ? `<div class="paste-body"><div class="field"><label for="soe-p-title">이름</label><input id="soe-p-title" type="text" data-soe-col="paste|title" value="${esc(pv.title || '')}" placeholder="예: 내가 고른 단편 1~5화"></div>
      <div class="field"><label for="soe-p-text">글</label><textarea id="soe-p-text" rows="8" data-soe-col="paste|text" placeholder="여기에 붙여 넣으세요">${esc(pv.text || '')}</textarea></div></div>` : ''}</div>`;
  const p = c.preview;
  const preview = p ? soePreviewHtml(p) : '<p class="small">원천을 고르고 미리보기를 누르면 사람 · AI 조각 수와 1차에 쓸 화 수를 먼저 보여 드려요.</p>';
  const any = soeColSources().length > 0;
  return `<section class="card" id="soe-collect" aria-labelledby="soe-col-h"><div class="between"><h2 id="soe-col-h">조각 모으기</h2><span class="row"><span class="chip">AI 없음</span>${S.soe.pieces ? '<button type="button" class="btn ghost small" data-action="soeCollectClose">닫기</button>' : ''}</span></div>
    <div class="src-rows">${labs}${eps}${research}${edits}${paste}</div>
    ${!labs && !eps && !research ? '<p class="small">역설계 실험이나 본문을 쓴 작품이 아직 없어요. 붙여 넣기로 사람 글과 AI 글을 넣을 수 있어요.</p>' : ''}
    <p class="small">'읽은 적 있는 작품'에 체크한 원천은 가려 읽기 대기열에 넣지 않아요. 기억으로 출처를 알 수 있어서예요. 출처 판별에는 써요. 원천 하나에서 사람 · AI 쪽마다 ${src.cap}조각까지 받아요.</p>
    <div class="soe-preview" aria-live="polite">${preview}</div>
    ${c.err ? `<div class="note err">${esc(c.err)}</div>` : ''}
    <div class="row soe-col-btns"><button type="button" class="btn${p ? '' : ' primary'}" data-action="soePreview"${any ? '' : ' disabled'}>미리보기</button>${p ? `<button type="button" class="btn primary" data-action="soeCollect"${p.new ? '' : ' disabled'}>모으기</button>` : ''}</div></section>`;
}

function soePreviewHtml(p) {
  const need = p.first_need;
  const g = p.groups || {};
  const models = Object.entries(p.models || {});
  const warn = [];
  if ((g.human || 0) < need || (g.ai || 0) < need) {
    warn.push(`같은 화에서 2조각씩이라 1차 결과가 약할 수 있어요. 사람 글을 ${Math.max(0, need - (g.human || 0))}화, AI 글을 ${Math.max(0, need - (g.ai || 0))}화 더 가져오면 화마다 한 조각으로 맞춰요.`);
  }
  if (models.length === 1) warn.push('모델이 하나뿐이라 결과가 그 모델 글 기준이에요. 다른 모델로 쓴 화를 더하면 모델별로 나눠 볼 수 있어요.');
  if (p.literary_only) warn.push('사람 쪽이 근대 소설뿐이라 시대와 갈래 차이를 재고 있을 수 있어요.');
  const o = p.by_origin || {};
  return `<div class="bars two">${soeBar(`사람 글 · 서로 다른 화 ${need}곳 이상`, `${g.human || 0}/${need}`, (g.human || 0) / need, '작가가 읽은 화는 세지 않아요', 'h')}
      ${soeBar(`AI 글 · 서로 다른 화 ${need}곳 이상`, `${g.ai || 0}/${need}`, (g.ai || 0) / need, (g.ai || 0) >= need ? '채웠어요' : '', 'a')}</div>
    <p class="small">AI 글 · 모델별 화 ${models.length ? models.map(([m, n]) => `${esc(m)} ${n}`).join(' · ') : '없음'} · 모델은 기록 · 사용량 기록 · 작가가 고른 값에서 와요</p>
    ${warn.map((w) => `<p class="warn-text">${esc(w)}</p>`).join('')}
    <div class="between"><b>미리보기 사람 ${o.human || 0} · AI ${o.ai || 0} · 모름 ${o.unknown || 0}${o.edited ? ` · 고친 글 ${o.edited}` : ''}</b>
      <span class="small">새 조각 ${p.new} · 이미 있는 글 ${p.dup}은 건너뛰어요${p.capped ? ` · 상한에 걸린 ${p.capped}개는 빼요` : ''} · 가려 읽기 대기열 +${p.queue}</span></div>`;
}

const SOE_HID = { judge: '판정 뒤에 보여요', redo: '재판정 뒤에 보여요', spare: '나중에 보여요' };

function soeSrcChip(origin) {
  if (origin === 'human') return '<span class="chip src h"><i aria-hidden="true">●</i>사람</span>';
  if (origin === 'ai') return '<span class="chip src a"><i aria-hidden="true">▲</i>AI</span>';
  return `<span class="chip">${origin === 'edited' ? '고친 글' : '모름'}</span>`;
}

function soeCorpus() {
  const v = S.soePieces;
  const col = S.soeCol && S.soeCol.open ? soeCollectCard() : '';
  if (!v) return `${col}<div class="note plain">불러오는 중…</div>`;
  if (!v.rows.length) return col || soeCollectCard();
  const srcRows = v.sources.map((s) => `<div class="between"><span>${esc(s.key.replace(/^(\w+):/, (m, k) => `${{ revlab: '역설계 실험', episode: '작품', research: '연구 말뭉치', paste: '붙여 넣기', edit: '수정 기록', trial: '조건 실험' }[k] || k} `))}</span>
    <span class="row">${s.origin === 'human' || s.origin === 'ai' ? soeSrcChip(s.origin) : `<span class="chip">${s.origin === 'edited' ? '고친 글' : '모름'}</span>`}<b class="num">${s.n}</b>${s.capped ? '<span class="chip v-few">상한</span>' : ''}</span></div>`).join('');
  const rows = v.rows.map((r) => {
    const hid = r.hidden ? `<span class="chip hid">${SOE_HID[r.hidden]}</span>` : '';
    const edit = r.paste && !r.hidden ? `<span class="row">${menuBtn(`soe-p-${r.id}`, '⋯', () => `<button type="button" class="pop-item" data-action="soeOrigin" data-arg="${r.id}|human">출처: 사람 글로</button>
      <button type="button" class="pop-item" data-action="soeOrigin" data-arg="${r.id}|ai">출처: AI 글로</button><button type="button" class="pop-item" data-action="soeOrigin" data-arg="${r.id}|unknown">출처: 모름으로</button>
      ${r.labels ? '' : `<button type="button" class="pop-item danger" data-action="soeRemove" data-arg="${r.id}">조각 빼기</button>`}`, { cls: 'btn icon-btn small', aria: `조각 ${r.id} 메뉴` })}</span>`
      : r.paste && !r.labels ? `<button type="button" class="btn ghost small" data-action="soeRemove" data-arg="${r.id}" aria-label="조각 ${r.id} 빼기">빼기</button>` : '';
    return `<div class="row-sum pc-row"><span class="num">${r.n}</span><button type="button" class="linkish mono" data-action="soeReadOpen" data-arg="${r.id}">${r.id.slice(0, 6)}</button>
      <span>${hid || soeSrcChip(r.origin)}${r.model ? ` <span class="chip">${esc(r.model)}</span>` : ''}${r.known ? ' <span class="chip">읽은 작품</span>' : ''}</span>
      <span class="small">${r.hidden ? '' : esc(r.source)}</span><span class="small mono">${r.hidden ? '' : esc(r.group)}</span>
      <span class="num small">${r.chars.toLocaleString()}자</span><span class="num small">판정 ${r.labels}</span><span>${edit}</span></div>`;
  }).join('');
  return `${col}<div class="cols2"><section class="card tight"><h3>묶음별</h3><p class="small">묶음 ${v.group_total} · 사람 ${v.groups.human} · AI ${v.groups.ai}. 범위는 묶음째 다시 뽑아 셈해요.</p>
      ${soeBar('사람 묶음', v.groups.human, v.groups.human / Math.max(1, v.group_total), '', 'h')}${soeBar('AI 묶음', v.groups.ai, v.groups.ai / Math.max(1, v.group_total), '', 'a')}</section>
    <section class="card tight"><h3>원천별 · 상한 ${v.cap}조각</h3>${srcRows}</section></div>
    <section class="card" aria-labelledby="soe-pc-h"><div class="between"><h2 id="soe-pc-h">조각 ${v.rows.length}</h2><span class="small">가린 조각 ${v.hidden}</span></div>
      <p class="small">판정 대기 조각과 다시 읽기 예정 조각은 출처 · 원천 · 묶음을 판정 뒤에 보여요. 서버도 이 값을 보내지 않아요. 출처 고치기와 빼기는 붙여 넣은 글에만 써요.</p>
      <div class="row-sum pc-row head" aria-hidden="true"><span>번호</span><span>조각</span><span>출처</span><span>원천</span><span>묶음</span><span>글자</span><span>판정</span><span></span></div>
      <div class="rows">${rows}</div></section>`;
}

/* ----- 원고 그리기 ----- */

/** 원고 HTML: 문장마다 data-i, 작가 표시는 밑줄 + 꼬리표(누르면 작은 메뉴), 고른 문장은 sel, rx(정규식 적중)는 정답을 볼 때만 */
function soeMs(text, sents, { spans = [], sel = null, rx = null, tags = true, tap = false } = {}) {
  const markOf = (i) => spans.findIndex((s) => s.start < sents[i][1] && s.end > sents[i][0]);
  const lastOf = (k) => { let at = -1; sents.forEach(([a, b], i) => { if (spans[k].start < b && spans[k].end > a) at = i; }); return at; };
  const rxOf = (i) => (rx || []).filter((r) => r.start < sents[i][1] && r.end > sents[i][0]);
  const paras = [];
  let cur = [];
  let prevEnd = 0;
  sents.forEach(([a, b], i) => {
    const gap = text.slice(prevEnd, a);
    if (i && gap.includes('\n')) { paras.push(cur.join('')); cur = []; } else if (i) cur.push(' ');
    const k = markOf(i);
    const hits = rxOf(i);
    const cls = ['s', k >= 0 ? 'mk' : '', sel && i >= sel[0] && i <= sel[1] ? 'sel' : '', hits.length ? 'rx' : ''].filter(Boolean).join(' ');
    let tail = '';
    if (k >= 0 && lastOf(k) === i) {
      tail = tags ? `<button type="button" class="mk-t" data-action="soeMarkMenu" data-arg="${k}" aria-label="표시 ${k + 1}: ${esc(soeKind(spans[k].kind))}. 누르면 갈래 바꾸기 · 메모 · 지우기">${esc(soeKind(spans[k].kind))}</button>` : `<span class="mk-t">${esc(soeKind(spans[k].kind))}</span>`;
    }
    if (hits.length) tail += `<span class="rx-t">${esc([...new Set(hits.map((h) => h.name))].join(' · '))}</span>`;
    cur.push(`<span class="${cls}" data-i="${i}"${tap ? ' role="button" tabindex="0"' : ''}>${esc(text.slice(a, b))}</span>${tail}`);
    prevEnd = b;
  });
  paras.push(cur.join(''));
  return `<div class="ms${tap ? ' tap' : ''}">${paras.map((p) => `<p>${p}</p>`).join('')}</div>`;
}

/* ----- 가려 읽기 · 다시 읽기 ----- */

function soeJudgeProgress(j) {
  const sc = S.soe;
  if (j.mode === 'redo') {
    const rs = sc.redo_state;
    return `<div class="card tight soe-prog">${soeBar('다시 읽기', `${rs.done}/${rs.target}`, rs.target ? rs.done / rs.target : 0)}<span class="chip">열림 ${rs.due}</span>
      <span class="small soe-full">처음 판정과 견줘 판정 일관성을 셈해요. 차례는 섞었어요.</span></div>`;
  }
  const inb = sc.in_batch;
  return `<div class="card tight soe-prog">${soeBar('판정', soeRound(sc.judged, sc.goal), sc.judged / (sc.goal <= SOE_FIRST ? SOE_FIRST : SOE_GOAL))}
    ${soeBar('이번 10개', `${inb}/10`, inb / 10)}<span class="chip">오늘 ${sc.judged_today}/10</span>
    <span class="small soe-full">정답(출처와 정규식 적중)은 이번 10개를 마치면 한꺼번에 보여요.</span></div>`;
}

function soeTool(j) {
  const kinds = (S.soe.kinds || []).map(([k, l]) => `<button type="button" class="btn small" data-action="soeMark" data-arg="${k}">${esc(l)}</button>`).join('');
  if (j.menu >= 0 && j.spans[j.menu]) {
    const sp = j.spans[j.menu];
    return `<div class="sel-tool soe-tool" role="dialog" aria-label="표시 고치기" data-anchor="mk-${j.menu}"><div class="between"><span class="small">표시 ${j.menu + 1} · ${esc(soeKind(sp.kind))}</span>
      <button type="button" class="btn ghost small" data-action="soeToolClose">닫기${soeKbd('Esc')}</button></div>
      <label class="field"><span class="label">메모 <span class="hint">한 줄, 비워도 돼요</span></span><input type="text" data-soe-j="note" value="${esc(sp.note || '')}" maxlength="200"></label>
      <div class="kinds" role="group" aria-label="갈래 바꾸기">${(S.soe.kinds || []).map(([k, l]) => `<button type="button" class="btn small${k === sp.kind ? ' on' : ''}" aria-pressed="${k === sp.kind}" data-action="soeReKind" data-arg="${k}">${esc(l)}</button>`).join('')}</div>
      <button type="button" class="btn small danger" data-action="soeUnmark">표시 지우기</button></div>`;
  }
  if (!j.sel || soeTapOn()) return '';
  return `<div class="sel-tool soe-tool" role="dialog" aria-label="고른 문장에 갈래 붙이기" data-anchor="sel"><div class="between"><span class="small">고른 곳 · ${j.sel[1] - j.sel[0] + 1}문장</span>
    <button type="button" class="btn ghost small" data-action="soeToolClose">취소${soeKbd('Esc')}</button></div>
    <label class="field"><span class="label">메모 <span class="hint">한 줄, 비워도 돼요</span></span><input type="text" data-soe-j="memo" value="${esc(j.memo)}" maxlength="200" placeholder="어디가 걸렸는지"></label>
    <div class="kinds" role="group" aria-label="갈래">${kinds}</div>
    <span class="small">갈래를 누르면 바로 표시해요. 표시한 밑줄의 꼬리표를 누르면 갈래를 바꾸거나 지울 수 있어요.</span></div>`;
}

const soeKbd = (k) => (matchMedia('(pointer: fine)').matches === true ? ` <kbd>${k}</kbd>` : '');

function soeStrip(j) {
  const tap = soeTapOn();
  if (tap && j.sel) {  // 문장 누르기: 아래 칸이 판정 대신 갈래 8 + 메모
    return `<div class="soe-strip dock" role="group" aria-label="고른 문장에 갈래 붙이기"><div class="between soe-full"><span class="small"><b>고른 문장 ${j.sel[1] - j.sel[0] + 1}</b> · 옆 문장을 누르면 이어 골라요</span>
      <button type="button" class="btn ghost small" data-action="soeToolClose">취소</button></div>
      ${j.memoOpen ? `<label class="field soe-full"><span class="label">메모 <span class="hint">한 줄, 비워도 돼요 · 갈래를 누르면 함께 표시해요</span></span><input type="text" data-soe-j="memo" value="${esc(j.memo)}" maxlength="200" placeholder="어디가 걸렸는지"></label>` : ''}
      <div class="kinds soe-full" role="group" aria-label="갈래">${(S.soe.kinds || []).map(([k, l]) => `<button type="button" class="btn" data-action="soeMark" data-arg="${k}">${esc(l)}</button>`).join('')}</div>
      ${j.memoOpen ? '' : '<button type="button" class="btn ghost small" data-action="soeMemoOpen">+ 메모 쓰기</button>'}</div>`;
  }
  const V = [['ai', 'AI 티 나요', '1'], ['human', '사람 글 같아요', '2'], ['unsure', '모르겠어요', '3']];
  const marks = () => (j.spans.length ? j.spans.map((s, k) => `<div class="between soe-mlist"><span class="small">${k + 1}. ${esc(soeKind(s.kind))} · ${esc(j.piece.text.slice(s.start, s.end).slice(0, 28))}…</span>
      <button type="button" class="pop-item danger" data-action="soeUnmarkAt" data-arg="${k}">지우기</button></div>`).join('') : '<p class="small" style="padding:8px">아직 표시한 곳이 없어요</p>');
  return `<div class="soe-strip${tap ? ' dock' : ''}" role="group" aria-label="판정">
    <label class="clean"><input type="checkbox" data-soe-j="clean"${j.clean ? ' checked' : ''}${j.spans.length ? ' disabled' : ''}><span>표시할 곳 없이 다 읽었어요</span></label>
    <div class="verdicts">${V.map(([k, l, n]) => `<button type="button" class="btn${j.verdict === k ? ' on' : ''}" aria-pressed="${j.verdict === k}" data-action="soeVerdict" data-arg="${k}">${l}${soeKbd(n)}</button>`).join('')}</div>
    <div class="end">${menuBtn('soe-marks', `표시 ${j.spans.length} ▾`, marks, { cls: 'btn ghost small', aria: `표시 ${j.spans.length}개 목록`, align: 'up' })}
      <button type="button" class="btn primary" data-action="soeSave"${j.verdict ? '' : ' disabled'}>저장하고 다음${soeKbd('Enter')}</button></div></div>
    ${matchMedia('(pointer: fine)').matches === true ? '<p class="small">단축키: 1 · 2 · 3 판정, Enter 저장하고 다음, Esc 고르기 취소. 단축키 없이도 모두 버튼으로 할 수 있어요.</p>' : ''}`;
}

function soeJudging(j) {
  const tap = soeTapOn();
  return `${soeJudgeProgress(j)}
    <section class="card ms-card" aria-label="가려 읽을 조각"><div class="between ms-head"><span class="small">조각 ${esc(j.piece.id.slice(0, 6))} · ${j.piece.chars.toLocaleString()}자</span>
      <span class="small">${tap ? '문장을 누르면 골라요 · 글 고르기 꺼짐' : '문장을 끌어 고르면 갈래를 붙일 수 있어요'}</span></div>
      ${soeMs(j.piece.text, j.sents, { spans: j.spans, sel: j.sel, tap })}${soeTool(j)}</section>
    ${soeStrip(j)}`;
}

function soeMilestone() {
  const sc = S.soe;
  if (sc.judged === SOE_FIRST && sc.goal === SOE_FIRST && !sc.stopped) return 40;
  if (sc.judged === 60 && sc.goal === 60 && !sc.stopped) return 60;
  if (sc.judged >= SOE_GOAL) return 90;
  return 0;
}

function soeMilestoneCard() {
  const sc = S.soe;
  const m = soeMilestone();
  const rs = sc.redo_state;
  const v = sc.verdicts || {};
  const tot = (v.ai || 0) + (v.human || 0) + (v.unsure || 0);
  const measured = tot ? `<div class="cols3 soe-r1"><div><div class="small">판정 하나 시간</div><b class="num">${Math.round((sc.seconds_mean || 0) / 6) / 10}분</b></div>
      <div><div class="small">'모르겠어요' 비율</div><b class="num">${Math.round(((v.unsure || 0) / tot) * 100)}%</b></div>
      <div><div class="small">AI : 사람 판정</div><b class="num">${v.ai || 0} : ${v.human || 0}</b><div class="tr soe-ratio" role="img" aria-label="AI 판정 ${v.ai || 0}, 사람 판정 ${v.human || 0}"><i class="a" style="width:${soePct((v.ai || 0) / Math.max(1, (v.ai || 0) + (v.human || 0)))}"></i><i class="h" style="width:${soePct((v.human || 0) / Math.max(1, (v.ai || 0) + (v.human || 0)))}"></i></div></div></div>` : '';
  if (m === 40) {
    return `<section class="card soe-state"><span class="chip confirmed">1차 끝</span><h2>1차 40개를 읽었어요. 강하게 가르는 지표를 볼 수 있어요.</h2>
      <p>더 읽으면 중간 정도로 가르는 지표도 가려낼 수 있어요. 결과가 쓸 만하면 이어 가고, 판정이 너무 흔들리거나 시간이 너무 들면 멈추고 방식을 고쳐요.</p>
      <h3>1차에서 잰 것</h3>${measured}
      <div class="row soe-state-btns"><button type="button" class="btn" data-action="soeStop">여기서 멈추기</button><button type="button" class="btn primary" data-action="soeGoal" data-arg="60">계속 읽기 (60개까지)</button></div></section>`;
  }
  if (m === 60) {
    const filled = (sc.spare || {}).filled;
    return `<section class="card soe-state"><span class="chip confirmed">두 번째 보고</span><h2>60개를 읽었어요. 두 번째 지표 대조를 볼 수 있어요.</h2>
      ${filled ? `<p>판정 일관성을 60개에서 보려고 정답을 숨겨 둔 예비 ${filled}개를 다시 읽기에 더했어요. 첫 판정 7일 뒤부터 열려요.</p>` : ''}${measured}
      <div class="row soe-state-btns"><a class="btn" href="#/soelab/metrics">지표 대조 보기</a><button type="button" class="btn primary" data-action="soeGoal" data-arg="90">계속 읽기 (90개까지)</button></div></section>`;
  }
  if (m === 90) {
    return `<section class="card soe-state"><span class="chip confirmed">다 읽음</span><h2>90개를 다 읽었어요. 지표 대조를 볼 수 있어요.</h2>
      <div class="row soe-state-btns">${rs.due ? `<a class="btn" href="#/soelab/metrics">지표 대조 보기</a><a class="btn primary" href="#/soelab/redo">다시 읽기 ${rs.due}개</a>` : '<a class="btn primary" href="#/soelab/metrics">지표 대조 보기</a>'}</div></section>`;
  }
  return '';
}

function soeJudgePane() {
  const sc = S.soe;
  if (!sc.pieces) return '<section class="card soe-empty"><h2>먼저 조각을 모아 주세요</h2><p><a class="btn primary" href="#/soelab/corpus">말뭉치로</a></p></section>';
  if (S.soeJ) return soeJudging(S.soeJ);
  if (S.soeBatch) return `${soeMilestone() ? soeMilestoneCard() : ''}${soeBatchCard(S.soeBatch)}`;
  if (soeMilestone()) return soeMilestoneCard();
  if (sc.stopped) {
    return `<section class="card soe-state"><h2>판정을 여기서 멈췄어요</h2><p>지금까지 판정한 ${sc.judged}개로 지표 대조를 볼 수 있어요. 다시 이어 할 때는 아래 버튼을 눌러요.</p>
      <div class="row soe-state-btns"><a class="btn" href="#/soelab/metrics">지표 대조 보기</a><button type="button" class="btn primary" data-action="soeResume">판정 다시 이어 하기</button></div></section>`;
  }
  return `<section class="card soe-empty"><h2>판정할 조각을 다 읽었어요</h2><p>조각을 더 모으면 이어서 읽어요. 작가가 읽은 작품과 고친 글은 가려 읽기에 넣지 않아요.</p><p><a class="btn primary" href="#/soelab/corpus">말뭉치로</a></p></section>`;
}

const SOE_VERDICT = { ai: 'AI 티 나요', human: '사람 글 같아요', unsure: '모르겠어요' };

function soeBatchCard(b) {
  const sc = S.soe;
  const c = b.counts || {};
  const models = Object.entries(c).filter(([k]) => k.startsWith('model:')).map(([k, n]) => `${k.slice(6)} ${n}`);
  const rows = b.rows.map((r, idx) => {
    const open = S.soeBatchOpen === idx && !r.hidden;
    const origin = r.hidden ? `<span class="chip hid">${SOE_HID[r.why] || SOE_HID.redo}</span>` : `${soeSrcChip(r.origin)}${r.model ? ` <span class="chip">${esc(r.model)}</span>` : ''}`;
    const match = r.hidden || r.match === null ? '<span class="small">–</span>' : r.match ? '<span class="ok">같아요</span>' : '<span class="no">달라요</span>';
    const hits = r.hidden ? (r.why === 'spare' ? '예비로 두어 나중에 보여요 (판정 일관성 결론이 나오거나 판정을 마치면)' : '다시 읽기로 뽑혀 재판정 뒤에 보여요') : `정규식 ${r.hits} · 내 표시 ${r.marked}${r.both ? ` · 같음 ${r.both}` : ''}${r.clean ? ' · 표시할 곳 없음' : ''}`;
    const body = open ? `<div class="row-body"><div class="legend"><span class="sw"><span class="lg-mk" aria-hidden="true"></span>내 표시</span><span class="sw"><span class="lg-rx" aria-hidden="true"></span>정규식 적중</span></div>
      ${soeMs(r.text, soeSentences(r.text), { spans: r.spans, rx: r.rx, tags: false })}
      <p class="small">같음 ${r.both} · 정규식만 ${r.hits - r.both} · 내 표시만 ${r.marked - r.both}. 패턴 혼동표에 모여요.</p></div>` : '';
    const tag = r.hidden ? 'div' : 'button';
    return `<${tag} ${r.hidden ? '' : `type="button" data-action="soeBatchRow" data-arg="${idx}" aria-expanded="${open}" `}class="row-sum be-row${open ? ' open' : ''}">
      <span class="num">${r.i}</span><span class="mono">${esc(r.id.slice(0, 6))}</span><span>${SOE_VERDICT[r.verdict] || ''}</span><span>${origin}</span><span>${match}</span>
      <span class="small">${esc(hits)}</span><span aria-hidden="true">${r.hidden ? '' : open ? '⌄' : '›'}</span></${tag}>${body}`;
  }).join('');
  return `<section class="card soe-end"><div class="between"><h2>10개를 마쳤어요 · 판정 ${soeRound(Math.max(sc.judged, b.k * 10), sc.goal)}</h2><span class="small">${fmtDate(b.at)} · ${Math.round(b.seconds / 60)}분</span></div>
    <div class="cols3"><div><div class="small">출처와 같은 판정</div><div class="soe-big num">${b.same} / ${b.comparable}</div><div class="small">모르겠어요 ${b.unsure}${c.hidden ? ` · 정답을 가린 ${c.hidden}` : ''}은 빼고</div></div>
      <div><div class="small">내 표시와 정규식이 같은 문장</div><div class="soe-big num">${c.both || 0}</div><div class="small">정규식만 ${c.rx_only || 0} · 내 표시만 ${c.mine_only || 0}</div></div>
      <div><div class="small">이번 10개의 출처 · 모델</div><div class="row">${c.human ? `<span class="chip src h"><i aria-hidden="true">●</i>사람 ${c.human}</span>` : ''}${c.ai ? `<span class="chip src a"><i aria-hidden="true">▲</i>AI ${c.ai}</span>` : ''}${c.hidden ? `<span class="chip hid">가림 ${c.hidden}</span>` : ''}</div>
        <div class="small">${c.ai ? `AI ${c.ai} = ${esc(models.join(' · '))}. ` : ''}판정하는 동안에는 모델도 숨겨요.</div></div></div>
    <p class="small">이 숫자는 이번 10개만 본 것이에요. 지표 대조는 판정이 모두 모인 뒤에 믿을 수 있어요.</p>
    <div class="rows"><div class="row-sum be-row head" aria-hidden="true"><span>#</span><span>조각</span><span>내 판정</span><span>출처</span><span>같음</span><span>정규식 적중 · 내 표시</span><span></span></div>${rows}</div></section>`;
}

function soeRedoPane() {
  const sc = S.soe;
  if (S.soeJ) return soeJudging(S.soeJ);
  const rs = sc.redo_state;
  if (rs.target && rs.done >= rs.target) return `<section class="card soe-empty"><h2>다시 읽기를 마쳤어요</h2><p>판정 일관성은 개요와 지표 대조에 있어요.</p><p><a class="btn primary" href="#/soelab">개요로</a></p></section>`;
  if (rs.opens) {
    const left = Math.max(0, Math.round((new Date(`${rs.opens}T00:00:00`) - new Date(`${sc.today}T00:00:00`)) / 86400000));
    return `<section class="card soe-empty"><h2>${fmtDate(`${rs.opens}T00:00:00`)}부터 다시 읽을 수 있어요</h2>
      <p>같은 조각을 너무 일찍 다시 읽으면 처음 판정을 기억해서 일관성이 부풀어요. 첫 판정 7일 뒤에 열어요.</p>
      <div class="bar">${`<div class="lb"><span>7일 중</span><b>${7 - left}일 지남</b></div><div class="tr" role="img" aria-label="7일 중 ${7 - left}일 지남"><i class="w" style="width:${soePct((7 - left) / 7)}"></i></div>`}</div>
      <p class="small">그동안 새 조각 판정은 막지 않아요. 다시 읽을 조각 ${rs.waiting}개가 기다리고 있어요.</p>
      <div class="row"><a class="btn primary" href="#/soelab/metrics">지표 대조 보기</a>${sc.queue_left && !sc.stopped ? '<a class="btn" href="#/soelab/judge">판정 이어 하기</a>' : ''}</div></section>`;
  }
  return '<section class="card soe-empty"><h2>아직 다시 읽을 조각이 없어요</h2><p>판정한 조각 가운데 셋에 하나를 7일 뒤에 다시 읽어요. 어느 조각인지는 모을 때 정해 두고, 재판정을 마칠 때까지 정답을 숨겨요.</p></section>';
}

/** 떠 있는 도구를 고른 문장 · 누른 꼬리표 아래에 둔다 (그린 뒤에 자리를 잰다) */
function soePlace() {
  const dock = document.querySelector('#app .soe-strip.dock');
  const picked = [...document.querySelectorAll('#app .ms.tap .s.sel')].pop();
  if (dock && picked) {  // 문장 누르기: 고른 문장이 아래 칸에 가리면 위로 올린다
    const over = picked.getBoundingClientRect().bottom - dock.getBoundingClientRect().top + 16;
    if (over > 0) window.scrollBy(0, over);
  }
  const tool = document.querySelector('#app .soe-tool');
  if (!tool) return;
  const card = tool.closest('.ms-card');
  const sel = [...card.querySelectorAll('.ms .s.sel')];
  const anchor = tool.dataset.anchor === 'sel' ? sel[sel.length - 1] : card.querySelectorAll('.ms .mk-t')[Number(tool.dataset.anchor.slice(3))];
  if (!anchor) return;
  const cr = card.getBoundingClientRect();
  const ar = anchor.getBoundingClientRect();
  const w = tool.offsetWidth;
  const from = tool.dataset.anchor === 'sel' ? sel[0].getClientRects()[0] || ar : ar;  // 고른 첫 문장의 왼쪽 끝에 맞춘다
  const left = Math.max(8, Math.min(from.left - cr.left, cr.width - w - 8));
  tool.style.left = `${left}px`;
  tool.style.top = `${ar.bottom - cr.top + 8}px`;
  const inp = tool.querySelector('input[data-soe-j]');
  if (inp && S.soeFocusTool) { inp.focus({ preventScroll: true }); S.soeFocusTool = false; }
}

/* ----- 지표 대조 · 지표 하나 ----- */

function soeMetricsPane() {
  const sc = S.soe;
  const rep = sc.report;
  if (!sc.pieces) return '<section class="card soe-empty"><h2>먼저 조각을 모아 주세요</h2><p><a class="btn primary" href="#/soelab/corpus">말뭉치로</a></p></section>';
  if (!rep) return `${soeStaleNote()}`;
  const same = rep.same.length ? rep.same.map((s) => `<div class="row"><span class="chip">${esc(soeMetricName(s.a))}</span><span class="chip">${esc(soeMetricName(s.b))}</span><span class="small">ρ ${soeNum(s.rho)} · 조각 ${s.n}</span></div>`).join('') : '<p class="small">순위 상관이 0.8을 넘는 짝이 없어요.</p>';
  const edits = rep.edits.length ? rep.edits.map((e) => `<div class="between"><span class="small">${esc(e.label)}</span><span class="small num">${e.pairs}쌍 · 줄어듦 ${e.less || 0} · 늘어남 ${e.more || 0} · 같음 ${e.same || 0}</span></div>`).join('')
    : '<p class="small">수정 기록 \'쇠맛 줄이기\' 전후를 모으면, 작가가 고친 곳을 지표가 따라 움직였는지 보여요.</p>';
  return `${soeVerLine(rep)}${soeStaleNote()}${soeHoldCard()}${soeTable(rep)}
    <div class="cols2"><section class="card tight"><h3>같은 것을 재는 지표</h3><p class="small">순위 상관이 0.8을 넘는 짝이에요. 한 짝 안의 경고는 하나로 보세요.</p>${same}</section>
      <section class="card tight"><h3>지표가 못 보는 차이</h3><p class="small">고치기 전보다 고친 뒤에 지표가 사람 쪽으로 움직인 쌍 수예요. 정답으로 쓰지 않아요.</p>${edits}<div class="row"><a class="btn small" href="#/soelab/patterns">'기타' 문장 보기</a></div></section></div>`;
}

const soeMetricName = (id) => ((S.soe.metric_ids || []).find(([k]) => k === id) || [id, id])[1];

/** 큰 범위 막대: 95% 굵은 막대 + 99.64% 가는 선 + 값 점 */
function soeBigRng(s, held = false) {
  if (!s || s.value == null) return `<span class="dash">${s && s.chip === 'few' ? '표본 부족' : '–'}</span>`;
  const [lo, hi] = s.ci95;
  const [wl, wh] = s.ci || s.ci95;
  return `<div class="brng${held ? ' dim' : ''}" aria-hidden="true"><span class="ax"></span><span class="t m" style="left:50%"></span><span class="t" style="left:70%"></span>
    <span class="w" style="left:${soePct(wl)};width:${soePct(wh - wl)}"></span><span class="i" style="left:${soePct(lo)};width:${soePct(hi - lo)}"></span><span class="d" style="left:${soePct(s.value)}"></span></div>
    <div class="axl" aria-hidden="true"><span style="left:0">0</span><span style="left:50%">0.5 · 못 가름</span><span style="left:70%">0.7</span><span style="left:100%">1</span></div>`;
}

const SOE_SHAPES = ['tri', 'dia', 'sq'];

function soeDotPlot(m) {
  const rows = m.rows;
  if (!m.points.length) return '<p class="small">그릴 값이 없어요. 판정 대기 조각은 빼고 그려요.</p>';
  const vals = m.points.map((p) => p.v);
  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  if (m.line != null) { lo = Math.min(lo, m.line); hi = Math.max(hi, m.line); }
  if (hi === lo) { hi += 1; lo -= 1; }
  const W = 640;
  const L = 170;
  const R = 16;
  const RH = 34;
  const H = rows.length * RH + 36;
  const x = (v) => L + ((v - lo) / (hi - lo)) * (W - L - R);
  const aiRows = rows.filter((r) => r.side === 'ai');
  const shape = (r) => (r.side === 'human' ? 'dot' : SOE_SHAPES[Math.min(aiRows.indexOf(r), SOE_SHAPES.length - 1)]);
  const mark = (s, cx, cy) => ({
    dot: `<circle cx="${cx}" cy="${cy}" r="4" fill="var(--soe-human)"></circle>`,
    tri: `<path d="M${cx} ${cy - 5}L${cx + 5} ${cy + 4}L${cx - 5} ${cy + 4}Z" fill="none" stroke="var(--soe-ai)" stroke-width="1.6"></path>`,
    dia: `<path d="M${cx} ${cy - 5}L${cx + 5} ${cy}L${cx} ${cy + 5}L${cx - 5} ${cy}Z" fill="none" stroke="var(--soe-ai)" stroke-width="1.6"></path>`,
    sq: `<rect x="${cx - 4}" y="${cy - 4}" width="8" height="8" fill="none" stroke="var(--soe-ai)" stroke-width="1.6"></rect>`,
  }[s]);
  const glyph = { dot: '●', tri: '△', dia: '◇', sq: '□' };
  const body = rows.map((r, k) => {
    const y = 14 + k * RH + RH / 2;
    const pts = m.points.filter((p) => p.row === r.key).map((p, n) => mark(shape(r), x(p.v).toFixed(1), (y + ((n * 37) % 13) - 6).toFixed(1))).join('');
    return `<text x="0" y="${y + 4}" font-size="12" fill="var(--text-2)">${esc(r.label)} ${glyph[shape(r)]}</text><line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" stroke="var(--rule)"></line>${pts}`;
  }).join('');
  const ticks = [lo, (lo + hi) / 2, hi].map((v) => `<text x="${x(v)}" y="${H - 6}" font-size="11" text-anchor="middle" fill="var(--muted)">${soeTick(v)}</text>`).join('');
  const line = m.line != null ? `<line x1="${x(m.line)}" x2="${x(m.line)}" y1="8" y2="${H - 22}" stroke="var(--text)" stroke-width="1.5" stroke-dasharray="4 3"></line><text x="${x(m.line) + 4}" y="12" font-size="11" fill="var(--text)">지금 기준 ${m.line}</text>` : '';
  const desc = rows.map((r) => `${r.label} ${m.points.filter((p) => p.row === r.key).length}개`).join(', ');
  return `<svg class="plot" viewBox="0 0 ${W} ${H}" role="img" aria-label="값의 분포: ${esc(desc)}">${body}${line}${ticks}</svg>`;
}

const soeTick = (v) => (Math.abs(v) >= 10 ? v.toFixed(0) : Math.abs(v) >= 1 ? v.toFixed(1) : v.toFixed(2));

function soeRoc(m) {
  if (m.roc.length < 2) return '<p class="small">사람 글과 AI 글이 함께 있어야 곡선을 그려요.</p>';
  const S2 = 240;
  const P = 34;
  const pts = m.roc.map(([fx, ty]) => `${(P + fx * S2).toFixed(1)},${(P + (1 - ty) * S2).toFixed(1)}`).join(' ');
  return `<svg class="plot roc" viewBox="0 0 ${S2 + P + 12} ${S2 + P + 30}" role="img" aria-label="가르는 힘 곡선 (보이는 조각 ${m.points.length}개)">
    <rect x="${P}" y="${P}" width="${S2}" height="${S2}" fill="var(--canvas)" stroke="var(--line)"></rect>
    <line x1="${P}" y1="${P + S2}" x2="${P + S2}" y2="${P}" stroke="var(--line-strong)" stroke-dasharray="4 3"></line>
    <polyline points="${pts}" fill="none" stroke="var(--text)" stroke-width="2"></polyline>
    <text x="${P + S2 / 2}" y="${P + S2 + 24}" font-size="11" text-anchor="middle" fill="var(--muted)">사람 글을 잘못 잡은 비율</text>
    <text x="12" y="${P + S2 / 2}" font-size="11" text-anchor="middle" fill="var(--muted)" transform="rotate(-90 12 ${P + S2 / 2})">AI 글을 잡은 비율</text></svg>`;
}

function soeMetricOne() {
  const m = S.soeMetric;
  if (!m) return '<div class="note plain">불러오는 중…</div>';
  const r = m.row;
  const held = S.soe.held;
  const big = (name, sub, s, opt = {}) => `<div class="big"><div><b>${name}</b><div class="small">${sub}</div></div><div>${soeBigRng(s, opt.held)}</div>
    <div>${s && s.value != null ? `<span class="v num">${soeNum(s.value)}</span> <span class="r">[${soeNum(s.ci95[0])}–${soeNum(s.ci95[1])}]</span> ${opt.held ? '<span class="held">보류</span>' : soeChip(s.chip)}` : soeChip(s ? s.chip : 'na')}</div></div>`;
  const ext = (xs, title) => `<div><h3>${title}</h3>${xs.length ? xs.map((x) => `<button type="button" class="row-sum ext" data-action="soeReadOpen" data-arg="${x.id}"><span class="mono">${x.id.slice(0, 6)}</span><span class="small">${esc(x.row)}</span><span class="num">${soeTick(x.v)}</span><span aria-hidden="true">›</span></button>`).join('') : '<p class="small">없어요</p>'}</div>`;
  const models = r && r.by_model.length > 1 ? `<details class="more"><summary>모델별 · 참고</summary>${r.by_model.map((x) => `<div class="between"><span class="small">사람 대 ${esc(soeModelName(x.model))} · AI 조각 ${x.ai_pieces || 0} · 묶음 ${x.ai_groups || 0}</span>${soeCell(x, { ref: true })}</div>`).join('')}
    <p class="small">모델별 줄은 95% 범위의 참고 값이라 칩을 달지 않아요.${r.model_split ? ' 한 모델에서 맞는데 다른 모델에서 못 가르거나 반대라 \'모델마다 달라요\'가 붙었어요.' : ''}</p></details>` : '';
  const pr = r && r.pairs;
  const src = r && r.source;
  return `<p class="ver-line">지표 버전 ${esc(m.metrics_version)} · 보이는 조각 ${m.points.length}${m.left_out ? ` · 판정 대기 조각 ${m.left_out}개는 빼고 그렸어요` : ''}</p>
    <section class="card"><h2>무엇을 재나요</h2><dl class="def"><dt>정의</dt><dd>${esc(m.def)}</dd><dt>잰 곳</dt><dd>${esc(m.where)}</dd><dt>방향</dt><dd>${esc(m.direction)}</dd>
      <dt>지금 기준</dt><dd>${esc(m.threshold)} <span class="small mono">canon/metrics.py</span></dd></dl></section>
    <section class="card"><div class="between"><h2>가르는 힘</h2><span class="small">굵은 막대 95% 범위 · 가는 선 99.64% 범위(칩을 정하는 범위)</span></div>
      ${r ? big('출처 기준', `사람 원문 ${src.human_pieces || 0} · AI ${src.ai_pieces || 0}`, src) : '<p class="small">아직 채점하지 않았어요.</p>'}
      ${r ? big('작가 판정 기준', r.author ? `AI 티 나요 ${r.author.ai_pieces} · 사람 글 같아요 ${r.author.human_pieces}` : '판정 20개부터', r.author, { held: held && !!r.author }) : ''}
      ${pr && pr.n ? `<div class="big"><div><b>역설계 짝</b><div class="small">원문과 되쓰기 ${pr.n}쌍</div></div><div class="small">${pr.n}쌍 가운데 ${pr.agree}쌍에서 되쓰기 쪽이 AI 방향이었어요. 같은 방향 비율 ${soeNum(pr.ratio)} [${soeNum(pr.lo)}–${soeNum(pr.hi)}]</div><div>${pr.same_side ? '<span class="chip v-yes">짝에서도 같은 쪽</span>' : ''}</div></div>` : ''}
      ${models}
      ${src && src.p_holm != null ? `<details class="more"><summary>원래 이름과 우연일 가능성</summary><p class="small">가르는 힘은 AUROC예요. 우연일 가능성(Holm 보정 p) ${src.p_holm}. 가르는 힘 1은 늘 맞게 가르고, 0.5는 동전 던지기와 같고, 0.5 아래는 반대쪽을 가리켜요.</p></details>` : ''}</section>
    <section class="card"><h2>값의 분포</h2>${soeDotPlot(m)}
      <div class="legend"><span class="sw">● 사람 글 · 채운 원</span><span class="sw">△ ◇ □ AI 글 · 빈 모양(모델마다)</span>${m.line == null ? '<span>지금 기준은 작품 기준값에 따라 달라 기준선을 생략했어요</span>' : ''}</div></section>
    <section class="card soe-roc-card"><h2>가르는 힘 곡선</h2><div class="soe-roc">${soeRoc(m)}<p class="small">짝 없는 보이는 조각으로 그렸어요. 표의 값은 판정 대기 조각까지 모은 값이라 조금 다를 수 있어요. 대각선은 동전 던지기예요. 곡선이 왼쪽 위로 붙을수록 잘 갈라요.</p></div></section>
    <section class="card"><h2>끝 조각</h2><p class="small">누르면 읽기 전용으로 열고 정규식 적중을 밑줄로 보여요. 판정 대기 조각과 다시 읽기 예정 조각은 넣지 않아요.</p>
      <div class="cols2">${ext(m.top, 'AI 쪽 끝 5')}${ext(m.bottom, '사람 쪽 끝 5')}</div></section>`;
}

function soeReadCard() {
  const p = S.soeRead;
  const meta = p.hidden ? '<span class="chip hid">판정 뒤에 보여요</span>' : `${soeSrcChip(p.origin)}${p.model ? ` <span class="chip">${esc(p.model)}</span>` : ''} <span class="small">${esc(p.source)} · ${esc(p.group)}</span>`;
  return `<section class="card soe-read" aria-label="조각 ${esc(p.id.slice(0, 6))} 읽기"><div class="between"><span class="row"><b class="mono">${esc(p.id.slice(0, 6))}</b>${meta}<span class="small">${p.chars.toLocaleString()}자</span></span>
    <button type="button" class="btn ghost small" data-action="soeReadClose">닫기</button></div>
    ${!p.hidden ? '<div class="legend"><span class="sw"><span class="lg-rx" aria-hidden="true"></span>정규식 적중</span></div>' : ''}
    <div class="fade-box">${soeMs(p.text, soeSentences(p.text), { rx: p.hidden ? null : p.rx, tags: false })}</div></section>`;
}

/* ----- 패턴 혼동표 · 패턴 확인 ----- */

function soePatterns() {
  const v = S.soePat;
  if (!v) return '<div class="note plain">불러오는 중…</div>';
  const SENT = { same: ['같음', 'same'], fp: ['오탐 후보', 'fp'], miss: ['놓침', 'miss'] };
  const cell = (val, ci, few) => (few || val == null ? soeChip('few') : `<span class="cell">${soeRng({ value: val, ci95: ci })}<span class="v">${soeNum(val)}</span><span class="r">[${soeNum(ci[0])}–${soeNum(ci[1])}]</span></span>`);
  const rows = v.rows.map((r) => {
    const open = S.soePatOpen === r.kind;
    const cnt = Object.fromEntries(Object.keys(SENT).map((k) => [k, r.sentences.filter((s) => s.kind === k).length]));
    const body = open ? `<div class="row-body"><div class="row small">모두 ${r.sentences.length} · 같음 ${cnt.same} · 오탐 후보 ${cnt.fp} · 놓침 ${cnt.miss}</div>
      ${r.sentences.length ? r.sentences.map((s) => `<div class="sent"><span class="chip ${SENT[s.kind][1]}">${SENT[s.kind][0]}</span><span class="qt">${esc(s.text)}${s.note ? `<br><span class="small">메모: ${esc(s.note)}</span>` : ''}</span><span class="mono small">${esc(s.piece.slice(0, 6))}</span></div>`).join('') : '<p class="small">아직 문장이 없어요. 패턴 확인에서 매기거나 가려 읽기에서 이 갈래로 표시하면 모여요.</p>'}</div>` : '';
    return `<button type="button" class="row-sum pt-row${open ? ' open' : ''}" data-action="soePatRow" data-arg="${esc(r.kind)}" aria-expanded="${open}"><b>${esc(r.label)}</b>
      <span class="num">${r.checked}</span><span class="num">${r.yes}</span><span>${cell(r.precision, r.precision_ci, r.few)}</span>
      <span class="num">${r.missed}</span><span>${cell(r.recall, r.recall_ci || [0, 1], r.recall_few)}</span><span aria-hidden="true">${open ? '⌄' : '›'}</span></button>${body}`;
  }).join('');
  const others = v.others.length ? v.others.slice(0, S.soeOthersAll ? undefined : 3).map((o) => `<div class="sent"><span class="chip">기타</span><span class="qt">${esc(o.text)}${o.note ? `<br><span class="small">메모: ${esc(o.note)}</span>` : ''}</span><span class="mono small">${esc(o.piece.slice(0, 6))}</span></div>`).join('')
    + (v.others.length > 3 && !S.soeOthersAll ? `<button type="button" class="btn ghost small" data-action="soeOthersAll">${v.others.length - 3}개 더 보기</button>` : '') : '<p class="small">\'기타\'로 표시한 문장이 아직 없어요.</p>';
  return `<p class="ver-line">지표 버전 ${esc(v.metrics_version)} · 표시를 마친 조각 ${v.marked_pieces}(표시할 곳 없음 ${v.clean}) · 문장 ${v.sentences.toLocaleString()}</p>
    <section class="card"><div class="between"><h2>패턴 여섯</h2><span class="small">정밀도: 정규식이 잡은 문장 가운데 글티가 맞는 몫 · 재현율: 작가가 표시한 문장 가운데 잡은 몫</span></div>
      <div class="rs-scroll"><div class="rows soe-pt"><div class="row-sum pt-row head" aria-hidden="true"><span>패턴</span><span>매긴 적중</span><span>글티 맞아요</span><span>정밀도 [범위]</span><span>놓친 문장</span><span>재현율 [범위]</span><span></span></div>${rows}</div></div>
      <p class="small">적중이 5개 아래인 줄은 '표본 부족'으로 두고 범위를 그리지 않아요. 범위는 Wilson 95% 범위예요.</p></section>
    <section class="card"><div class="between"><h2>'기타'로 표시한 문장 ${v.others.length}</h2><span class="small">새 패턴이나 금지 표현 후보예요. 금지 표현에 넣는 일은 PR4부터 해요.</span></div>${others}</section>`;
}

function soeCheckPane() {
  const v = S.soeCheck;
  if (!v) return '<div class="note plain">불러오는 중…</div>';
  const prog = v.progress.map((p) => `<div class="pp${S.soeCheck.card && S.soeCheck.card.kind === p.kind ? ' now' : ''}"><span>${esc(p.label)}${S.soeCheck.card && S.soeCheck.card.kind === p.kind ? ' · 지금' : ''}</span><span class="n">${p.done}/${p.total}</span>
    <div class="tr" aria-hidden="true"><i style="width:${soePct(p.total ? p.done / p.total : 0)}"></i></div></div>`).join('');
  const side = `<section class="card tight"><div class="between"><h3>패턴별</h3><span class="small num">${v.done}/${v.total}</span></div>${prog}
    <p class="small">패턴마다 20문장까지예요. 적중이 그보다 적으면 있는 만큼만 봐요.</p>
    <div class="seg" role="group" aria-label="패턴 고르는 방식"><button type="button" aria-pressed="${!S.soeCheckKind}" data-action="soeCheckKind" data-arg="">차례대로</button>${v.progress.filter((p) => p.done < p.total).map((p) => `<button type="button" aria-pressed="${S.soeCheckKind === p.kind}" data-action="soeCheckKind" data-arg="${esc(p.kind)}">${esc(p.label)}</button>`).join('')}</div></section>`;
  const c = v.card;
  if (!c) {
    return `<div class="ck-wrap"><section class="card soe-empty"><h2>${v.total ? '패턴 확인을 다 했어요' : '확인할 문장이 아직 없어요'}</h2><p>${v.total ? '정밀도는 패턴 혼동표에 있어요.' : '판정을 마친 조각과 가려 읽기에 넣지 않은 조각에서만 문장을 골라요. 판정 대기 조각은 출처가 드러나지 않게 빼요.'}</p>
      <p><a class="btn primary" href="#/soelab/patterns">패턴 혼동표로</a></p></section>${side}</div>`;
  }
  let hit = '';
  let at = 0;
  c.marks.forEach((mk) => { hit += esc(c.sentence.slice(at, mk.start)) + `<span class="rx">${esc(c.sentence.slice(mk.start, mk.end))}</span>`; at = mk.end; });
  hit += esc(c.sentence.slice(at));
  const kb = (n) => soeKbd(n);
  return `<div class="ck-wrap"><section class="ck-card" aria-label="정규식이 고른 문장 매기기"><div class="ck-band"><span class="chip v-weak">정규식이 고른 문장</span><span>가려 읽기가 아니에요 · 패턴 이름과 적중을 보여 드려요</span></div>
      <div class="ck-body"><div class="row"><span class="rx-t">${esc(c.label)}</span><span class="small">조각 ${esc(c.piece.slice(0, 6))} · ${c.origin === 'ai' ? 'AI 글' : c.origin === 'human' ? '사람 글' : '모름'} · ${esc(c.source)}${c.model ? ` · ${esc(c.model)}` : ''}</span>${c.rated ? `<span class="chip">매긴 값: ${{ yes: '글티 맞아요', no: '아니에요', skip: '모르겠어요' }[c.rated]}</span>` : ''}</div>
        ${c.prev ? `<p class="ck-ctx">${esc(c.prev)}</p>` : ''}<p class="ck-hit">${hit}</p>${c.next ? `<p class="ck-ctx">${esc(c.next)}</p>` : ''}</div>
      <div class="ck-btns"><button type="button" class="btn" data-action="soeRate" data-arg="yes">글티 맞아요${kb('1')}</button><button type="button" class="btn" data-action="soeRate" data-arg="no">아니에요${kb('2')}</button><button type="button" class="btn" data-action="soeRate" data-arg="skip">모르겠어요${kb('3')}</button></div>
      <div class="between ck-foot"><button type="button" class="btn ghost small" data-action="soeCheckBack"${S.soeCheckHist.length ? '' : ' disabled'}>← 앞 문장 다시 매기기</button><span class="small">누르면 바로 다음 문장으로 넘어가요</span></div></section>${side}</div>
    <div class="note plain">여기서 매긴 값은 패턴 혼동표의 정밀도에만 들어가요. 재현율과 지표 대조는 가려 읽기 판정으로만 셈해요. 지표를 보고 고른 문장이라 판단이 끌릴 수 있어서예요.</div>`;
}

function soeLogPane() {
  const v = S.soeLog;
  if (!v) return '<div class="note plain">불러오는 중…</div>';
  if (!v.length) return '<section class="card soe-empty"><h2>아직 보고서가 없어요</h2><p>조각을 모으거나 다시 채점하면 보고서가 생겨요.</p></section>';
  return `<section class="card"><div class="rs-scroll"><table class="soe-table"><thead><tr><th scope="col">날짜</th><th scope="col">지표 버전</th><th scope="col" class="num">조각</th><th scope="col" class="num">묶음</th><th scope="col" class="num">판정</th><th scope="col" class="num">다시 읽기</th><th scope="col" class="num">시험 세트를 연 횟수</th></tr></thead>
    <tbody>${v.map((r) => `<tr><td>${fmtDateTime(r.made)}</td><td class="mono">${esc(r.metrics_version)}</td><td class="num">${r.pieces}</td><td class="num">${r.groups}</td><td class="num">${r.judged}</td><td class="num">${r.redone}</td><td class="num dash">–</td></tr>`).join('')}</tbody></table></div>
    <p class="small">시험 세트는 기준 맞추기(PR4)부터 나눠요. 보고서 파일은 이 컴퓨터의 .soelab/reports 폴더에 있어요.</p></section>`;
}

/* ----- 동작 ----- */

async function soeRefresh() {
  S.soe = await api('GET', '/soelab');
}

Object.assign(actions, {
  soeCollectOpen() {
    S.soeCol = S.soeCol || { open: true, sel: {}, preview: null, err: '' };
    S.soeCol.open = true;
    if (S.soePane !== 'corpus' && S.soe.pieces) { location.hash = '#/soelab/corpus'; return; }
    (S.soeSrc ? Promise.resolve() : api('GET', '/soelab/sources').then((x) => { S.soeSrc = x; })).then(() => { S.focusTarget = '#soe-collect input'; render(); });
  },
  soeCollectClose() { S.soeCol.open = false; render(); },
  async soePreview() {
    S.soeCol.err = '';
    await run('미리 세는 중', async () => {
      try {
        S.soeCol.preview = await api('POST', '/soelab/collect/preview', { sources: soeColSources() });
        S.focusTarget = '#app [data-action="soeCollect"]';
      } catch (e) { S.soeCol.err = e.message; S.soeCol.preview = null; }
    });
  },
  async soeCollect() {
    await run('조각 모으고 채점하는 중', async () => {
      const r = await api('POST', '/soelab/collect', { sources: soeColSources() });
      S.soe = r.screen;
      toast(`조각 ${r.added}개를 모았어요${r.dup ? ` · 이미 있는 글 ${r.dup}개는 건너뛰었어요` : ''}. AI 없이 채점했어요.`);
      S.soeCol = { open: false, sel: {}, preview: null, err: '' };
      S.soePieces = await api('GET', '/soelab/pieces');
      if (S.soePane === 'overview') render();
      else location.hash = '#/soelab';
    });
  },
  async soeRescore() {
    await run('다시 채점하는 중 · AI 없음', async () => {
      S.soe = await api('POST', '/soelab/report');
      toast('다시 채점했어요. 지난 보고서는 기록에 남아요.');
    });
  },
  async soeSpareOpen() {
    await run('예비 조각을 다시 읽기로 옮기는 중', async () => {
      const r = await api('POST', '/soelab/spares/open');
      S.soe = r;
      toast(`예비 조각 ${r.opened}개를 다시 읽기에 넣었어요. 첫 판정 7일 뒤부터 열려요.`);
    });
  },
  soeModels(id) { if (S.soeOpen.has(id)) S.soeOpen.delete(id); else S.soeOpen.add(id); render(); },
  soeModelsAll() { S.soeAll = !S.soeAll; render(); },
  soeTapToggle() { S.soeTap = !soeTapOn(); if (S.soeJ) S.soeJ.sel = null; render(); },
  soeVerdict(k) { S.soeJ.verdict = k; S.focusTarget = `#app [data-action="soeVerdict"][data-arg="${k}"]`; render(); },
  soeMark(kind) {
    const j = S.soeJ;
    if (!j.sel) return;
    const [a, b] = j.sel;
    j.spans = soeMarkMerge(j.spans, { start: j.sents[a][0], end: j.sents[b][1], kind, note: j.memo.trim() });
    j.sel = null; j.memo = ''; j.memoOpen = false; j.clean = false;
    render();
  },
  soeMarkMenu(k) { const j = S.soeJ; if (!j) return; j.menu = j.menu === k ? -1 : k; j.sel = null; S.soeFocusTool = true; render(); },
  soeReKind(kind) { const j = S.soeJ; j.spans[j.menu].kind = kind; j.menu = -1; render(); },
  soeUnmark() { const j = S.soeJ; j.spans.splice(j.menu, 1); j.menu = -1; render(); },
  soeUnmarkAt(k) { S.soeJ.spans.splice(k, 1); render(); },
  soeToolClose() { const j = S.soeJ; j.sel = null; j.menu = -1; j.memo = ''; j.memoOpen = false; render(); },
  soeMemoOpen() { S.soeJ.memoOpen = true; S.focusTarget = '#app .soe-strip input[data-soe-j="memo"]'; render(); },
  async soeSave() {
    const j = S.soeJ;
    if (!j || !j.verdict) return;
    const body = { piece: j.piece.id, verdict: j.verdict, spans: j.spans, clean: j.clean, seconds: Math.round((Date.now() - j.t0) / 1000) };
    await run('저장하는 중', async () => {
      const v = await api('POST', j.mode === 'redo' ? '/soelab/redo' : '/soelab/judge', body);
      S.soeJ = null;
      soeTake(v, j.mode);
      if (j.mode === 'judge' && !S.soeJ && S.soe.ended) S.soeBatch = await api('GET', `/soelab/batch/${S.soe.ended}`);
      S.soeBatchOpen = -1;
      window.scrollTo(0, 0);
      S.focusTarget = '#app main h1';
    });
  },
  soeBatchRow(i) { S.soeBatchOpen = S.soeBatchOpen === i ? -1 : i; render(); },
  async soeSeen(where) {
    const k = S.soeBatch ? S.soeBatch.k : S.soe.ended;
    await run('넘기는 중', async () => {
      S.soe = await api('PUT', '/soelab/state', { seen: k });
      S.soeBatch = null;
      if (where === 'home') { location.hash = '#/soelab'; return; }
      await soeJudgeLoad();
    });
  },
  async soeGoal(n) {
    await run('넘기는 중', async () => {
      S.soe = await api('PUT', '/soelab/state', { goal: Number(n), seen: S.soe.batches, stopped: false });
      S.soeBatch = null;
      if (S.soePane === 'judge') await soeJudgeLoad(); else location.hash = '#/soelab/judge';
    });
  },
  async soeStop() {
    await run('멈추는 중', async () => {
      S.soe = await api('PUT', '/soelab/state', { stopped: true, seen: S.soe.batches });
      S.soeBatch = null;
      toast('판정을 여기서 멈췄어요. ⋯ 메뉴의 \'판정 다시 이어 하기\'로 돌아올 수 있어요.');
      location.hash = '#/soelab/metrics';
    });
  },
  async soeResume() {
    await run('이어 하는 중', async () => {
      S.soe = await api('PUT', '/soelab/state', { stopped: false });
      if (S.soePane === 'judge') await soeJudgeLoad(); else location.hash = '#/soelab/judge';
    });
  },
  async soeReadOpen(id) {
    await run('조각 여는 중', async () => {
      S.soeRead = await api('GET', `/soelab/pieces/${encodeURIComponent(id)}`);
      window.scrollTo(0, 0);
      S.focusTarget = '#app .soe-read button';
    });
  },
  soeReadClose() { S.soeRead = null; render(); },
  async soeOrigin(arg) {
    const [id, origin] = String(arg).split('|');
    await run('출처 고치는 중', async () => {
      S.soePieces = await api('PUT', `/soelab/pieces/${id}/origin`, { origin, model: '' });
      await soeRefresh();
    });
  },
  async soeRemove(id) {
    if (!confirm('이 조각을 말뭉치에서 뺄까요? 붙여 넣은 원문은 다시 붙여 넣으면 돌아와요.')) return;
    await run('조각 빼는 중', async () => {
      S.soePieces = await api('DELETE', `/soelab/pieces/${id}`);
      await soeRefresh();
    });
  },
  soePatRow(k) { S.soePatOpen = S.soePatOpen === k ? '' : k; render(); },
  soeOthersAll() { S.soeOthersAll = true; render(); },
  async soeRate(ok) {
    const c = S.soeCheck && S.soeCheck.card;
    if (!c) return;
    await run('매기는 중', async () => {
      S.soeCheck = await api('POST', `/soelab/check?kind=${encodeURIComponent(S.soeCheckKind)}`, { hit: c.hit, ok });
      S.soeCheckHist.push(c.hit);
      S.soe.check = { done: S.soeCheck.done, total: S.soeCheck.total };
    });
  },
  async soeCheckBack() {
    const hit = S.soeCheckHist.pop();
    if (!hit) return;
    await run('앞 문장 여는 중', async () => { S.soeCheck = await api('GET', `/soelab/check?hit=${encodeURIComponent(hit)}`); });
  },
  async soeCheckKind(k) {
    S.soeCheckKind = k || '';
    await run('패턴 바꾸는 중', async () => { S.soeCheck = await api('GET', `/soelab/check?kind=${encodeURIComponent(S.soeCheckKind)}`); });
  },
});

/* ----- 입력 · 고르기 · 단축키 ----- */

document.addEventListener('input', (e) => {
  const d = e.target.dataset || {};
  if (d.soeCol) {
    const [key, field] = d.soeCol.split('|');
    if (field === 'text' || field === 'title' || field === 'first' || field === 'last') {
      soeColSel(key)[field] = e.target.value;
      S.soeCol.preview = null;
      const box = document.querySelector('#soe-collect .soe-preview');
      if (box) box.innerHTML = '<p class="small">원천을 바꿨어요. 미리보기를 다시 눌러 주세요.</p>';
      const btn = document.querySelector('[data-action="soeCollect"]');
      if (btn) btn.remove();
      const pv = document.querySelector('[data-action="soePreview"]');
      if (pv) { pv.disabled = !soeColSources().length; pv.classList.add('primary'); }
    }
  }
  if (d.soeJ === 'memo' && S.soeJ) S.soeJ.memo = e.target.value;
  if (d.soeJ === 'note' && S.soeJ && S.soeJ.spans[S.soeJ.menu]) S.soeJ.spans[S.soeJ.menu].note = e.target.value;
});

document.addEventListener('change', (e) => {
  const d = e.target.dataset || {};
  if (d.soeCol) {
    const [key, field] = d.soeCol.split('|');
    const v = soeColSel(key);
    if (field === 'on' || field === 'known') v[field] = e.target.checked;
    else if (field === 'origin' || field === 'model') v[field] = e.target.value;
    else return;
    if (key === 'research' && !v.path && S.soeSrc) v.path = S.soeSrc.research.path;
    S.soeCol.preview = null;
    render();
  }
  if (d.soeJ === 'clean' && S.soeJ) { S.soeJ.clean = e.target.checked; render(); }
});

/** 끌어 고르기: 원고에서 글을 고르면 그 문장들을 고르고(문장 단위) 시스템 선택은 지운다 */
document.addEventListener('mouseup', () => {
  if (S.route[0] !== 'soelab' || !S.soeJ || soeTapOn()) return;
  const sel = document.getSelection();
  if (!sel || sel.isCollapsed || !sel.rangeCount) return;
  const ms = document.querySelector('#app .ms-card .ms');
  if (!ms || !ms.contains(sel.anchorNode) || !ms.contains(sel.focusNode)) return;
  const at = (n) => (n.nodeType === 3 ? n.parentElement : n).closest('[data-i]');
  const a = at(sel.anchorNode);
  const b = at(sel.focusNode);
  if (!a || !b) return;
  const i = Number(a.dataset.i);
  const k = Number(b.dataset.i);
  sel.removeAllRanges();
  S.soeJ.sel = [Math.min(i, k), Math.max(i, k)];
  S.soeJ.menu = -1;
  render();
});

/** 문장 누르기: 누른 문장을 고르고, 옆 문장을 누르면 이어 고르고, 고른 문장을 다시 누르면 푼다 */
document.addEventListener('click', (e) => {
  if (S.route[0] !== 'soelab' || !S.soeJ || !soeTapOn()) return;
  const s = e.target.closest && e.target.closest('#app .ms.tap .s[data-i]');
  if (!s) return;
  const i = Number(s.dataset.i);
  const j = S.soeJ;
  if (j.sel && i >= j.sel[0] && i <= j.sel[1]) j.sel = null;
  else if (j.sel && i === j.sel[0] - 1) j.sel = [i, j.sel[1]];
  else if (j.sel && i === j.sel[1] + 1) j.sel = [j.sel[0], i];
  else j.sel = [i, i];
  j.menu = -1;
  render();
});

document.addEventListener('keydown', (e) => {
  if (S.route[0] !== 'soelab' || e.isComposing || e.metaKey || e.ctrlKey || e.altKey || S.popMenu) return;
  const typing = isTyping() && !document.activeElement.matches('[type="checkbox"]');
  if (S.soePane === 'check' && S.soeCheck && S.soeCheck.card && !typing && ['1', '2', '3'].includes(e.key)) {
    e.preventDefault();
    actions.soeRate({ 1: 'yes', 2: 'no', 3: 'skip' }[e.key]);
    return;
  }
  const j = S.soeJ;
  if (!j || !['judge', 'redo'].includes(S.soePane)) return;
  if (e.key === 'Escape' && (j.sel || j.menu >= 0)) { e.preventDefault(); actions.soeToolClose(); return; }
  if (typing) {
    if (e.key === 'Enter' && e.target.dataset.soeJ) { e.preventDefault(); e.target.blur(); }
    return;
  }
  if (e.target.closest && e.target.closest('.ms.tap') && e.key === 'Enter') {  // 문장 누르기: Enter 로 문장 고르기
    e.preventDefault(); e.target.click(); return;
  }
  if (['1', '2', '3'].includes(e.key)) { e.preventDefault(); actions.soeVerdict({ 1: 'ai', 2: 'human', 3: 'unsure' }[e.key]); return; }
  if (e.key === 'Enter' && j.verdict && !(e.target.closest && e.target.closest('button, a'))) { e.preventDefault(); actions.soeSave(); }
});

// 휴대폰 키보드가 올라오면 아래 붙는 판정 띠를 키보드 바로 위로 (visualViewport)
if (window.visualViewport && typeof window.visualViewport.addEventListener === 'function') {
  const fit = () => {
    const vv = window.visualViewport;
    const kb = Math.max(0, innerHeight - vv.height - vv.offsetTop);
    document.documentElement.style.setProperty('--soe-kb', `${Math.round(kb)}px`);
  };
  window.visualViewport.addEventListener('resize', fit);
  window.visualViewport.addEventListener('scroll', fit);
}

(() => {
  const css = `
.soe-wrap { --outline-band: 0px; }
.soe-main { container: soe / inline-size; display: flex; flex-direction: column; gap: var(--gap-stack); min-width: 0; }
.soe-main.narrow { max-width: 860px; }
.soe-main .cols2 { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--gap-stack); }
.soe-main .cols3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--gap-stack); }
.soe-toc-fold { padding: 8px 10px; }
.outline-item .st .chip { font-size: 0.6875rem; padding: 1px 6px; }
.outline-item.warn .tl::before { content: ""; display: inline-block; width: 8px; height: 8px; margin-right: 8px; border-radius: 50%; background: var(--amber); vertical-align: 1px; }
.outline-item .st.warn { color: var(--amber-ink); font-weight: 700; }
.ver-line { margin: 0; font-size: 0.75rem; color: var(--muted); font-variant-numeric: tabular-nums; }
.soe-main .num { font-variant-numeric: tabular-nums; }
.soe-main .mono { font-family: var(--mono, ui-monospace, monospace); font-size: 0.75rem; }
.soe-main .dash { color: var(--muted); }
.soe-main .warn-text { margin: 0; color: var(--amber-ink); font-size: 0.8125rem; }
.soe-big { display: flex; gap: 16px; align-items: baseline; flex-wrap: wrap; }
.soe-big .num, div.soe-big.num { font-size: 1.5rem; font-weight: 800; }
.soe-empty p { margin: 0; }
.linkish { border: none; background: none; padding: 0; color: var(--link); cursor: pointer; text-align: left; font: inherit; }
/* 판정 칩 (기존 토큰만) */
.chip.v-yes { background: var(--green-soft); color: var(--green-ink); }
.chip.v-weak { background: var(--amber-soft); color: var(--amber-ink); }
.chip.v-none { background: var(--chip); color: var(--text-2); }
.chip.v-rev { background: var(--red-soft); color: var(--err-ink); }
.chip.v-tbd { outline: 1px dashed var(--line-strong); outline-offset: -1px; }
.chip.v-few { background: transparent; color: var(--muted); box-shadow: inset 0 0 0 1px var(--line-strong); font-weight: 500; }
.chip.v-split { background: transparent; color: var(--amber-ink); box-shadow: inset 0 0 0 1px var(--amber); }
.chip.src { gap: 5px; }
.chip.src i { font-style: normal; font-size: 0.6875rem; line-height: 1; }
.chip.src.h i { color: var(--soe-human); }
.chip.src.a i { color: var(--soe-ai); }
.chip.hid { background: transparent; color: var(--muted); box-shadow: inset 0 0 0 1px var(--line); font-weight: 500; }
.chip.same { background: var(--green-soft); color: var(--green-ink); }
.chip.fp { background: var(--amber-soft); color: var(--amber-ink); }
.chip.miss { background: var(--red-soft); color: var(--err-ink); }
/* 표 */
.soe-table { width: 100%; border-collapse: collapse; font-size: 0.8125rem; }
.soe-table th { padding: 0 8px 8px 0; font-size: 0.75rem; font-weight: 500; color: var(--muted); text-align: left; vertical-align: bottom; line-height: 1.35; }
.soe-table td { padding: 9px 8px 9px 0; border-top: 1px solid var(--rule); vertical-align: middle; white-space: nowrap; }
.soe-table td.num, .soe-table th.num { text-align: right; }
.soe-table tr.link td:first-child { font-weight: 700; line-height: 1.35; }
.soe-table tr.link td:first-child a { color: inherit; text-decoration: none; }
.soe-table tr.link td:first-child a:hover { text-decoration: underline; }
.soe-table td .small { font-weight: 500; }
.soe-table tr.link:hover td { background: var(--canvas); }
.soe-table .dim, .soe-table th.dim { color: var(--muted); }
.soe-table tr.link.open td { background: var(--sel-bg); }
.soe-table tr.mrow td { padding-top: 6px; padding-bottom: 6px; border-top: 1px dashed var(--rule); background: var(--canvas); font-size: 0.75rem; }
.soe-table tr.mrow td:first-child { padding-left: 16px; font-weight: 500; color: var(--text-2); }
.soe-main .ref { color: var(--muted); font-size: 0.6875rem; font-weight: 500; }
.soe-main .held { color: var(--muted); font-size: 0.75rem; font-weight: 500; }
.soe-table tr.mrow .cell .v { font-weight: 500; }
.mtog { white-space: nowrap; }
.cell { display: inline-flex; align-items: center; gap: 8px; }
.cell .v { font-weight: 700; font-variant-numeric: tabular-nums; min-width: 34px; }
.cell.dim .v { font-weight: 500; color: var(--muted); }
.cell .r { color: var(--muted); font-variant-numeric: tabular-nums; font-size: 0.75rem; }
.soe-narrow { display: none; }
/* 범위 막대 */
.rng { position: relative; display: inline-block; width: 84px; height: 14px; flex: none; }
.soe-table tr.link .rng { width: 64px; }  /* 1280px 창에서 표가 칸 안에 들게 본 줄 막대만 줄인다 */
.rng::before { content: ""; position: absolute; left: 0; right: 0; top: 6px; height: 2px; border-radius: 1px; background: var(--chip); }
.rng .h { position: absolute; top: 0; bottom: 0; left: 50%; width: 1px; background: var(--line-strong); }
.rng .s { position: absolute; top: 3px; bottom: 3px; left: 70%; width: 1px; background: var(--line-strong); }
.rng .i { position: absolute; top: 5px; height: 4px; border-radius: 2px; background: var(--text-2); }
.rng .d { position: absolute; top: 3px; width: 8px; height: 8px; margin-left: -4px; border-radius: 50%; background: var(--text); box-shadow: 0 0 0 2px var(--surface); }
.rng.dim .i { background: var(--line-strong); }
.rng.dim .d { background: var(--muted); }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 0.75rem; color: var(--text-2); align-items: center; }
.legend .sw { display: inline-flex; align-items: center; gap: 6px; }
.lg-mk { display: inline-block; width: 28px; border-bottom: 2px solid var(--accent); }
.lg-rx { display: inline-block; width: 28px; height: 12px; background: var(--amber-soft); box-shadow: inset 0 -2px 0 var(--amber); }
/* 진행 막대 */
.bars { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }
.bars.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.bar { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.bar .lb { display: flex; justify-content: space-between; gap: 8px; font-size: 0.8125rem; }
.bar .lb b { font-variant-numeric: tabular-nums; white-space: nowrap; }
.bar .tr, .soe-ratio { height: 6px; border-radius: 3px; background: var(--chip); overflow: hidden; display: flex; }
.bar .tr i, .soe-ratio i { display: block; height: 100%; background: var(--accent); }
.bar .tr i.h, .soe-ratio i.h { background: var(--soe-human); }
.bar .tr i.a, .soe-ratio i.a { background-color: var(--soe-ai); background-image: repeating-linear-gradient(135deg, transparent 0 3px, rgba(255,255,255,0.45) 3px 5px); }
.bar .tr i.w { background: var(--amber); }
.bar .sub { font-size: 0.75rem; color: var(--muted); }
.soe-prog { flex-direction: row; flex-wrap: wrap; align-items: center; gap: 12px 24px; }
.soe-prog .bar { flex: 1 1 200px; }
.soe-full { flex-basis: 100%; }
/* 말뭉치 */
.src-rows { display: flex; flex-direction: column; }
.src-row { display: grid; grid-template-columns: 24px minmax(0, 1fr) auto auto; gap: 12px; align-items: center; min-height: 52px; border-top: 1px solid var(--rule); font-size: 0.8125rem; padding: 6px 0; }
.src-row:first-child { border-top: none; }
.src-row input[type="checkbox"] { width: 18px; height: 18px; }
.src-t { display: flex; flex-direction: column; gap: 2px; cursor: pointer; min-width: 0; }
.src-x select, .soe-range input { min-height: 36px; }
.soe-range input { width: 64px; }
.soe-chk { display: inline-flex; align-items: center; gap: 6px; min-height: 36px; font-size: 0.8125rem; color: var(--text-2); white-space: nowrap; }
.paste-body { grid-column: 2 / -1; display: flex; flex-direction: column; gap: 8px; }
.paste-body textarea { width: 100%; min-height: 160px; }
.soe-col-btns { justify-content: flex-end; }
.soe-preview { display: flex; flex-direction: column; gap: 10px; padding: 12px 14px; border-radius: 10px; background: var(--bg); }
.rows { display: flex; flex-direction: column; }
.row-sum { min-height: 52px; display: grid; align-items: center; gap: 12px; padding: 0 12px; border: none; border-top: 1px solid var(--rule); background: transparent; color: inherit; font: inherit; font-size: 0.8125rem; text-align: left; width: 100%; }
button.row-sum { cursor: pointer; }
.row-sum:first-child { border-top: none; }
.row-sum.head { min-height: 32px; color: var(--muted); font-size: 0.75rem; }
button.row-sum:hover { background: var(--canvas); }
.row-sum.open { background: var(--sel-bg); }
.row-body { border: 1px solid var(--sel-line); background: var(--sel-bg); border-radius: 10px; padding: 16px; display: flex; flex-direction: column; gap: 10px; margin: 0 0 8px; }
.pc-row { grid-template-columns: 40px 72px minmax(0, 1.4fr) minmax(0, 1fr) minmax(0, 1fr) 64px 52px 64px; }
.pc-row > :last-child { justify-self: end; white-space: nowrap; }
.be-row { grid-template-columns: 28px 64px 112px minmax(0, 176px) 56px minmax(0, 1fr) 20px; }
.be-row .ok { color: var(--green-ink); font-weight: 700; }
.be-row .no { color: var(--err-ink); font-weight: 700; }
.pt-row { grid-template-columns: minmax(120px, 1.3fr) 72px 72px 190px 72px 190px 20px; min-width: 760px; }
.ext { grid-template-columns: 64px minmax(0, 1fr) 64px 20px; }
.sent { display: grid; grid-template-columns: 84px minmax(0, 1fr) 64px; gap: 12px; align-items: start; padding: 8px 0; border-top: 1px solid var(--rule); }
.sent:first-of-type { border-top: none; }
.qt { font-family: var(--serif); font-size: 0.875rem; line-height: 1.8; }
/* 원고 */
.ms-card { padding: 36px clamp(20px, 6%, 64px); position: relative; }
.ms-head { max-width: 760px; margin: 0 auto 8px; width: 100%; }
.ms { font-family: var(--serif); font-size: 1rem; line-height: 2; color: var(--text); max-width: 760px; margin: 0 auto; width: 100%; }
.ms p { margin: 0 0 1em; text-indent: 1em; }
.ms.tap { user-select: none; -webkit-user-select: none; -webkit-touch-callout: none; }
.ms.tap .s { cursor: pointer; }
.ms .mk { text-decoration: underline; text-decoration-color: var(--accent); text-decoration-thickness: 2px; text-underline-offset: 5px; }
.ms .mk-t, .rx-t { display: inline-flex; vertical-align: 2px; margin-left: 4px; padding: 0 6px; border: none; border-radius: 6px; background: var(--accent-soft); color: var(--accent-ink); font-family: var(--sans, inherit); font-size: 0.6875rem; font-weight: 700; line-height: 18px; text-indent: 0; }
button.mk-t { cursor: pointer; min-height: 24px; align-items: center; }
.rx-t { background: var(--amber-soft); color: var(--amber-ink); }
.ms .sel { background: var(--sel-bg); box-shadow: 0 0 0 2px var(--sel-line); border-radius: 2px; }
.ms .rx, .ck-hit .rx { background: var(--amber-soft); border-radius: 2px; box-shadow: inset 0 -2px 0 var(--amber); }
.fade-box { max-height: 480px; overflow: auto; }
.soe-tool { width: min(452px, calc(100% - 16px)); flex-direction: column; align-items: stretch; flex-wrap: nowrap; gap: 8px; padding: 10px 12px; font-family: var(--sans, inherit); font-size: 0.8125rem; line-height: 1.4; text-indent: 0; }
.kinds { display: flex; flex-wrap: wrap; gap: 6px; }
.kinds .btn.small { min-height: 36px; padding: 0 10px; }
.soe-main kbd { display: inline-flex; align-items: center; justify-content: center; min-width: 20px; height: 20px; padding: 0 5px; margin-left: 4px; border-radius: 4px; background: var(--chip); color: var(--text-2); font-family: var(--mono, monospace); font-size: 0.6875rem; font-weight: 700; box-shadow: inset 0 -1px 0 var(--line); }
.btn.primary kbd { background: transparent; color: inherit; box-shadow: inset 0 0 0 1px currentColor; }
/* 판정 띠: 아래에 붙는 버튼 줄 (화 플롯 페이지의 page-actions 줄과 같은 모양) */
.soe-strip { position: sticky; bottom: calc(12px + var(--soe-kb, 0px) + env(safe-area-inset-bottom, 0px)); z-index: 6; display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; padding: 12px 16px; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; box-shadow: 0 6px 24px rgba(0,0,0,0.12); }
.soe-strip .verdicts { display: flex; flex-wrap: wrap; gap: 8px; }
.soe-strip .clean { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; font-size: 0.8125rem; color: var(--text-2); }
.soe-strip .end { margin-left: auto; display: flex; gap: 8px; align-items: center; }
.soe-strip .kinds .btn { min-height: 44px; }
.pop-panel.up { bottom: calc(100% + 6px); top: auto; }
.soe-mlist { gap: 8px; padding: 0 8px; }
.soe-state { border-color: var(--sel-line); }
.soe-state h2 { margin: 0; }
.soe-state-btns { justify-content: flex-end; }
.soe-r1 b { font-size: 1.25rem; }
/* 지표 하나 */
.def { margin: 0; display: grid; grid-template-columns: 96px minmax(0, 1fr); column-gap: 16px; font-size: 0.8125rem; }
.def dt, .def dd { margin: 0; padding: 8px 0; border-top: 1px solid var(--rule); }
.def dt { color: var(--muted); }
.def dt:first-of-type, .def dd:first-of-type { border-top: none; padding-top: 0; }
.big { display: grid; grid-template-columns: 150px minmax(0, 1fr) 220px; gap: 16px; align-items: center; padding: 10px 0; border-top: 1px solid var(--rule); }
.big:first-of-type { border-top: none; }
.big .v { font-weight: 700; }
.big .r { color: var(--muted); font-size: 0.75rem; }
.brng { position: relative; height: 28px; }
.brng .ax { position: absolute; left: 0; right: 0; top: 13px; height: 2px; background: var(--chip); }
.brng .t { position: absolute; top: 6px; bottom: 6px; width: 1px; background: var(--line-strong); }
.brng .t.m { top: 2px; bottom: 2px; }
.brng .w { position: absolute; top: 13px; height: 2px; background: var(--text-2); }
.brng .i { position: absolute; top: 9px; height: 10px; border-radius: 5px; background: var(--text-2); }
.brng .d { position: absolute; top: 7px; width: 14px; height: 14px; margin-left: -7px; border-radius: 50%; background: var(--text); box-shadow: 0 0 0 2px var(--surface); }
.brng.dim .i, .brng.dim .w { background: var(--line-strong); }
.brng.dim .d { background: var(--muted); }
.axl { position: relative; height: 16px; font-size: 0.6875rem; color: var(--muted); font-variant-numeric: tabular-nums; }
.axl span { position: absolute; transform: translateX(-50%); white-space: nowrap; }
.plot { display: block; width: 100%; height: auto; }
.plot.roc { max-width: 300px; flex: none; }
.soe-roc { display: flex; flex-wrap: wrap; gap: 16px 24px; align-items: center; }
.soe-roc p { flex: 1 1 220px; margin: 0; }
.plot text { font-family: var(--sans, inherit); }
details.more > summary { cursor: pointer; color: var(--link); font-size: 0.8125rem; min-height: 36px; display: flex; align-items: center; }
/* 패턴 확인 */
.ck-wrap { display: grid; grid-template-columns: minmax(0, 1fr) 260px; gap: 14px; align-items: start; }
.ck-card { border: 1px solid var(--warn-line); border-radius: 12px; background: var(--surface); overflow: hidden; }
.ck-band { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; padding: 10px 20px; background: var(--amber-soft); color: var(--amber-ink); font-size: 0.8125rem; }
.ck-body { padding: 28px 32px 20px; display: flex; flex-direction: column; gap: 14px; }
.ck-ctx { margin: 0; font-family: var(--serif); font-size: 0.9375rem; line-height: 1.9; color: var(--muted); }
.ck-hit { margin: 0; font-family: var(--serif); font-size: 1.25rem; line-height: 1.8; color: var(--text); }
.ck-btns { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; padding: 16px 32px 12px; border-top: 1px solid var(--rule); }
.ck-btns .btn { min-height: 52px; font-size: 0.9375rem; }
.ck-foot { padding: 0 32px 16px; }
.pp { display: grid; grid-template-columns: minmax(0, 1fr) 54px; gap: 4px 8px; align-items: center; padding: 8px 0; border-top: 1px solid var(--rule); font-size: 0.8125rem; }
.pp .tr { grid-column: 1 / -1; height: 4px; border-radius: 2px; background: var(--chip); overflow: hidden; }
.pp .tr i { display: block; height: 100%; background: var(--amber); }
.pp.now { font-weight: 700; }
.pp .n { text-align: right; font-variant-numeric: tabular-nums; color: var(--text-2); }
.soe-main .seg { flex-wrap: wrap; }
/* 끊는 폭: @container soe */
@container soe (max-width: 760px) {
  .soe-main .cols2, .soe-main .cols3 { grid-template-columns: minmax(0, 1fr); }
  .bars { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .big { grid-template-columns: minmax(0, 1fr); gap: 6px; }
  .ck-wrap { grid-template-columns: minmax(0, 1fr); }
  .pc-row { grid-template-columns: 32px 64px minmax(0, 1fr) 64px 64px; }
  .pc-row > :nth-child(4), .pc-row > :nth-child(5), .pc-row > :nth-child(7) { display: none; }
}
@container soe (max-width: 560px) {
  .soe-wide { display: none; }
  .soe-narrow { display: flex; flex-direction: column; }
  .soe-mline { border-top: 1px solid var(--rule); }
  .soe-mline > summary { min-height: 52px; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 4px 8px; align-items: center; cursor: pointer; list-style: none; }
  .soe-mline > summary::-webkit-details-marker { display: none; }
  .soe-mline > summary .tl { display: flex; flex-direction: column; }
  .soe-mline > summary .v-split { grid-column: 1 / -1; justify-self: start; }
  .soe-mbody { display: flex; flex-direction: column; gap: 8px; padding: 4px 0 12px; }
  .soe-mref { border: 1px dashed var(--line-strong); border-radius: 8px; padding: 0 10px; }
  .soe-mref > summary { min-height: 44px; display: flex; align-items: center; cursor: pointer; }
  .soe-strip .verdicts { width: 100%; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .soe-strip .verdicts .btn { padding: 0 6px; min-height: 44px; font-size: 0.8125rem; }
  .soe-strip.dock .kinds .btn { padding: 0 10px; font-size: 0.8125rem; }
  .soe-strip .end { width: 100%; margin-left: 0; justify-content: space-between; }
  .ms-card { padding: 20px 16px; }
  .be-row { grid-template-columns: 24px 56px minmax(0, 1fr) 20px; }
  .be-row > :nth-child(5), .be-row > :nth-child(6), .be-row.head > :nth-child(4) { display: none; }
  .ck-body { padding: 20px 16px; }
  .ck-btns .btn { padding: 0 6px; font-size: 0.875rem; white-space: nowrap; }
  .ck-btns { padding: 12px 16px; position: sticky; bottom: env(safe-area-inset-bottom, 0px); background: var(--surface); }
  .ck-foot { padding: 0 16px 12px; }
  .ck-hit { font-size: 1.1875rem; }
  .src-row { grid-template-columns: 24px minmax(0, 1fr); }
  .src-row > .src-x, .src-row > div:last-child { grid-column: 2 / -1; }
  .src-row.paste > .paste-body { grid-column: 1 / -1; }
  .def { grid-template-columns: 72px minmax(0, 1fr); }
}
/* 손가락 기기: 갈래 · 판정 버튼은 44px */
@media (pointer: coarse) { .kinds .btn.small, .soe-strip .btn, button.mk-t { min-height: 44px; } }
@media (forced-colors: active) { .ms .sel, .ms .mk, .ms .rx { outline: 2px solid Highlight; } .bar .tr i { forced-color-adjust: none; } }
`;
  const el = document.createElement('style');
  el.textContent = css;
  document.head.appendChild(el);
})();

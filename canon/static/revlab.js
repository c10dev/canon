/* 역설계 실험 화면(서버 revlab.py, 작품 밖 화면 #/revlab[/<실험 번호>[/<화 | cast | style | lines | metrics>]], 작품 목록 · 사이드바 ⋯ 메뉴 · 작품 사이드바 실험 묶음에서 들어온다).
   작가가 넣은 소설을 거꾸로 화별 플롯 · 스토리보드 · 큐 시트 · 이야기 줄기로 풀고, 그 큐 시트로 같은 화를 다시 써서(되돌려 쓰기) 원문과 견준다.
   실험은 작품 밖(<CANON_HOME>/.revlab)에 두고 작품을 열지 않고 쓴다. AI 작업은 POST /revlab/<번호>/jobs (작업 rev_parse · rev_write · rev_style,
   ep 가 실험 번호, project 는 REV_JOBS). 사용량은 작품 없이 잡히고 모델은 실험이 고른 AI(목차 'AI 모델', revAICard), 고르지 않으면 전체 단계 설정을 쓴다.
   배치는 다른 단계 화면(설정 도우미 · 문체)과 같은 공용 목차 틀(outline.js)의 왼쪽 목차 + 오른쪽 칸이다. 목차는 단계 다섯(revSteps) · 화(revTocEps) · 실험 전체
   (인물 · 문체 · 줄기 · 지표), 오른쪽은 도는 작업 카드(revRunCard)와 고른 화의 탭 셋(원문 · 큐 / 플롯 · 스토리보드 / 되돌려 쓰기).
   머리 주 버튼은 다음 할 일 하나(revNext)이고 추정 비용을 함께 적는다(revEst, AI 없음). 폭은 창이 아니라 공용 목차 틀(outline.js, @container outline)의 폭으로 바꾼다.
   app.js 의 S, actions, api, run, render, header, esc, toast, josa, showError, pollJobs, jobFor, jobLeft, elapsed, menuBtn, isTyping,
   JOB_PAGES, JOB_DONE_MSG, fmtDateTime, hub.js 의 renderHub 와 cue.js 의 cueBind · cueEd · cueScore · cueEditor · cueLabel · cueUsd · cuePct · cueYes 를 쓴다
   (큐 시트 열쇠는 'rev:<화>'). 화 이어 붙이기의 '레퍼런스 원고에서' 는 refs.js 의 refRange · refEpName 을 쓴다. revGuessFirst · revSegments · revPreview · revEpTitle · revSteps · revNext · revTocEps · revRunRows ·
   revMetricRows · revAiText · revAiMade · revEpRange · revTakePicks · revRefPreview · revRefNext 는 DOM 없는 순수 함수 (tests/test_revlab.py). 글 나누기는 서버(POST /api/revlab/split, refs.split)에 묻는다 (revSplitOf). */
'use strict';

Object.assign(S, {
  rev: null,       // 서버 값 { labs, splits, max_chars, min_chars, … 큐 칸 이름 }
  revLab: null,    // 고른 실험 (revlab.view)
  revEp: null,     // 보는 화 번호
  revPane: null,   // 화 대신 보는 칸: overview(개요, 주소에 화가 없을 때) 또는 REV_PANES 의 열쇠
  revTab: 'text',  // 화 탭 (REV_TABS)
  revDraft: { title: '', text: '', first: '' },  // 새 실험 칸 (first 가 비면 짐작한 번호)
  revPick: null,   // 역설계할 화 Set
  revRedo: false,  // 역설계한 화도 다시 고르는 개요 표를 열었는지
  revRunHide: new Set(), // 닫은 작업 카드의 작업 id. 작업은 계속 돌고, 새 작업이 시작되면 카드가 다시 보인다
  revBlindRead: {}, // 가려 읽기마다(실험:화:판) 보는 쪽 show, 끝까지 내린 쪽 seen, 쪽마다 읽던 자리 top. 저장하지 않는다
  revNew: false,   // 처음 화면의 새 실험 카드를 열었는지 (실험이 없거나 붙여 넣은 글이 있으면 늘 열림)
  revEsts: {},     // 비용 추정 { 열쇠(revEstKey): 값 | null(묻는 중) | { error } }
  revSel: 0,       // 원문에서 밝힌 큐 번호 (1부터)
  revEdit: false,  // 실험 글 고치기 칸을 열었는지
  revAdd: null,    // 화 이어 붙이기 칸에 붙여 넣은 글 (null 이면 닫힘)
  revAddFrom: 'text', // 이어 붙일 곳: text(붙여 넣기) · ref(레퍼런스 원고에서)
  revRefs: null,   // 레퍼런스 원고 목록 (GET /refs, 처음 열 때 받는다)
  revRefBook: null, // 고른 원고 (GET /refs/<id>: episodes 에 차례 · 이름 · 제목 · 종류 · 글자 수)
  revRefPick: new Set(), // 고른 원고 화 차례
  revEpEdit: null, // 고치는 화 { n, head, text } (null 이면 닫힘)
  revStyle: false, // 되돌려 쓰기에 문체 프로필을 넣을지
  revPace: null, // 구조 · 호흡 칸의 값 { id, rows, summary } (GET /revlab/<번호>/pace)
  revStyleDiff: null, // 펼친 문체 프로필 견주기 { id, changes } (GET /revlab/<번호>/styles/<id>)
  revRead: { a: 'original', b: 0 }, // 나란히 읽기 왼쪽 · 오른쪽 ('original' 또는 판 번호, 0 이면 최근 판)
});

const REV_HEAD = /^\s*(?:#{1,6}\s*)?(?:제\s*)?(\d{1,4})\s*화(?:\s*[.:：\-—)]\s*|\s+|$)(.*)$/;  // 제목 줄에서 제목만 뗀다 (revlab.HEAD_RE)
const REV_SPLITS = { heading: '화 표시 줄', mark: '기호 줄', blank: '빈 줄 세 개 넘게', one: '한 화' };  // revlab.SPLITS
const REV_SPLIT = new Map();  // 글 → 서버가 나눈 값 { how, first, preface, episodes: [{ head, chars }] } (나누기 규칙은 refs.split 한 곳)
let revSplitTimer = null;

/** 글을 나눈 값. 아직 받지 않았으면 null 을 돌려주고 서버에 묻는다(잠깐 기다려 한 번만). 받으면 미리보기 칸을 다시 그린다 (revSplitDone). */
function revSplitOf(text) {
  const t = String(text || '');
  if (REV_SPLIT.has(t)) return REV_SPLIT.get(t);
  if (!t.trim()) return { how: 'one', first: 1, preface: '', episodes: [] };
  clearTimeout(revSplitTimer);
  revSplitTimer = setTimeout(() => {
    api('POST', '/revlab/split', { text: t }).then((v) => {
      if (REV_SPLIT.size > 20) REV_SPLIT.clear();
      REV_SPLIT.set(t, v);
      revSplitDone();
    }).catch(() => {});
  }, 250);
  return null;
}

/** 첫 화 번호 짐작 (revlab.guess_first): 글에 화 표시 줄이 있으면 그 번호, 없으면 실험 이름의 'n화', 그것도 없으면 1. s 는 서버가 나눈 값 */
function revGuessFirst(title, text, s = revSplitOf(text)) {
  if (s && s.how === 'heading') return s.first;
  const m = String(title || '').match(/(\d{1,4})\s*화/);
  return m ? Number(m[1]) || 1 : 1;
}

/** 나누기 미리보기 값: 화마다 번호 · 제목 · 글자 수 · 짧음, 막는 까닭(errs)과 알릴 것(notes). lim 은 서버 이름표 (max_chars 등).
    s 는 서버가 나눈 값(revSplitOf). 아직 없으면 pending 이다 */
function revPreview(text, lim, first = null, s0 = revSplitOf(text)) {
  if (!s0) return { pending: true, how: '', label: '', eps: [], errs: [], notes: [] };
  const s = { ...s0 };
  if (first) s.first = first;
  const errs = []; const notes = [];
  const len = String(text || '').length;
  if (!s.episodes.length) errs.push('글이 비었어요. 소설 본문을 붙여 넣으세요.');
  if (len > lim.max_chars) errs.push(`글이 너무 길어요 (${len.toLocaleString()}자). ${lim.max_chars.toLocaleString()}자까지 넣을 수 있어요.`);
  const eps = s.episodes.map((e, i) => ({ n: s.first + i, head: e.head, chars: e.chars, short: e.chars < lim.min_chars }));
  if (eps.some((e) => e.short)) notes.push(`${lim.min_chars}자보다 짧은 화는 역설계하지 않아요.`);
  if (s.preface) notes.push(`첫 제목 줄 앞의 짧은 글(${s.preface.length}자)은 작품 제목 · 작가 줄로 보고 역설계하지 않아요.`);
  if (s.first <= 3 && s.episodes.length) notes.push('1~3화로 잡히면 되돌려 쓰기에 초반 규칙(첫 화 쓰는 법)이 붙어요. 소설 중간이면 첫 화 번호를 적으세요.');
  return { how: s.how, label: REV_SPLITS[s.how], eps, errs, notes };
}

/** 이어 붙일 글의 나누기 미리보기 (revlab.append_text 와 같은 규칙): 새 화는 제목 줄 번호와 상관없이 마지막 화 + 1(have.next)부터 세고,
    글자 수 한도는 실험 전체(have.chars)로 본다 (화 수는 막지 않는다). 첫 제목 줄 앞의 짧은 글은 넣지 않는다. 값 모양은 revPreview 와 같다. */
function revAppendPreview(text, lim, have, s = revSplitOf(text)) {
  if (!s) return { pending: true, how: '', label: '', eps: [], errs: [], notes: [] };
  const errs = []; const notes = [];
  const len = String(text || '').length;
  if (!s.episodes.length) errs.push('글이 비었어요. 이어 붙일 화를 붙여 넣으세요.');
  if (have.chars + len > lim.max_chars) errs.push(`이으면 ${(have.chars + len).toLocaleString()}자예요. 한 실험에 ${lim.max_chars.toLocaleString()}자까지 넣을 수 있어요.`);
  const eps = s.episodes.map((e, i) => ({ n: have.next + i, head: e.head, chars: e.chars, short: e.chars < lim.min_chars }));
  if (eps.some((e) => e.short)) notes.push(`${lim.min_chars}자보다 짧은 화는 역설계하지 않아요.`);
  if (s.preface) notes.push(`첫 제목 줄 앞의 짧은 글(${s.preface.length}자)은 작품 제목 · 작가 줄로 보고 넣지 않아요.`);
  if (s.how === 'heading' && s.episodes.length && s.first !== have.next) notes.push(`제목 줄은 ${s.first}화부터지만 마지막 화 다음인 ${have.next}화부터 이어요.`);
  return { how: s.how, label: REV_SPLITS[s.how], eps, errs, notes };
}

/** 원문 조각: 경계(bounds)대로 [{ cue (1부터, 경계 밖이면 0), start, end }]. 찾지 못한 큐(found 거짓)와 빈 구간은 건너뛴다. */
function revSegments(text, bounds) {
  const out = [];
  let at = 0;
  (bounds || []).forEach((b, i) => {
    if (!b.found || b.end <= b.start) return;
    if (b.start > at) out.push({ cue: 0, start: at, end: b.start });
    out.push({ cue: i + 1, start: b.start, end: b.end });
    at = b.end;
  });
  if (at < String(text || '').length) out.push({ cue: 0, start: at, end: text.length });
  return out;
}

const REV_JOBS = '.revlab';  // 작업 목록의 project 자리 (revlab.JOBS)

/** 역설계 작업 시작 (startJob 의 작품 밖 판): kind parse · write · style. 실패하면 작업 목록의 '다시 시도'가 같은 요청을 다시 보낸다. */
async function revStartJob(kind, extra = {}) {
  const id = S.revLab.id;
  const key = `rev_${kind}:${id}`;
  if (S.starting.has(key)) return;
  S.starting.add(key);
  render();
  try {
    const j = await api('POST', `/revlab/${id}/jobs`, { kind, ...extra });
    if (!j.already) toast(`${j.label}${josa(j.label, '을', '를')} 시작했어요. 끝나면 알려 드릴게요. 그동안 다른 화면을 봐도 돼요.`);
    S.jobs = S.jobs.filter((x) => x.id !== j.id).concat(j);
    S.jobArgs[j.id] = { retry: () => { S.revLab = S.revLab && S.revLab.id === id ? S.revLab : { id }; return revStartJob(kind, extra); } };
    renderHub();
    pollJobs(true);
  } catch (e) {
    showError(e);
  } finally {
    S.starting.delete(key);
    render();
  }
}

const revItem = (n) => ((S.revLab && S.revLab.items) || []).find((e) => e.number === n) || null;
const revCueKey = (n) => `rev:${n}`;

async function revLoad(id, n) {
  S.rev = await api('GET', '/revlab').catch((e) => ({ error: e.message }));
  // 큐 시트 편집기(cue.js)가 쓰는 칸 이름. 큐 시트 실험 화면을 아직 열지 않았으면 여기 것을 쓴다 (그 화면이 다시 받는다)
  if (!S.rev.error && (!S.cue || !S.cue.functions)) {
    const { conditions, functions, tempos, voices, cadences, max_cues, max_lines } = S.rev;
    S.cue = { conditions, functions, tempos, voices, cadences, max_cues, max_lines };
  }
  const k = Number(id) || null;
  if (!k) { S.revLab = null; return; }
  if (!S.revLab || S.revLab.id !== k || !(S.cueEdits[revCueKey(S.revEp)] || {}).dirty) await revFetch(k);
  S.revPane = !n ? 'overview' : n in REV_PANES ? n : null;
  if (S.revPane === 'shape') await revPaceLoad();
  const want = Number(n) || null;
  if (S.revLab && !S.revLab.error) {
    const nums = S.revLab.items.map((e) => e.number);
    const was = S.revEp;
    if (want && nums.includes(want)) S.revEp = want;
    else if (!nums.includes(S.revEp)) S.revEp = nums[0];
    if (S.revEp !== was) S.revSel = 0;
  }
}

/** 실험을 다시 받는다. 저장하지 않은 큐 시트 고침은 그 화의 시트가 그대로일 때(역설계를 다시 하지 않았을 때) 남긴다. */
async function revFetch(id) {
  const old = S.revLab && !S.revLab.error ? S.revLab : null;
  const made = new Map(old && old.id === id ? old.items.map((e) => [e.number, e.sheet && e.sheet.made_at]) : []);
  S.revLab = await api('GET', `/revlab/${id}`).catch((e) => ({ error: e.message, id }));
  if (S.revLab.error) return;
  if (S.revPane === 'shape') await revPaceLoad();
  for (const e of S.revLab.items) {
    const key = revCueKey(e.number);
    if ((S.cueEdits[key] || {}).dirty && made.has(e.number) && made.get(e.number) === (e.sheet && e.sheet.made_at)) continue;
    S.cueEdits[key] = { draft: e.sheet ? structuredClone(e.sheet) : null, dirty: false };
  }
  if (!old || old.id !== id) {
    S.revPick = new Set(S.revLab.items.filter((e) => !e.sheet && e.chars >= S.rev.min_chars).map((e) => e.number));
    S.revSel = 0; S.revEdit = false; S.revAdd = null; S.revEpEdit = null; S.revRedo = false; S.revTab = 'text'; S.revEp = null;
  } else if (S.revPick && !S.revRedo) {
    for (const e of S.revLab.items) if (e.sheet) S.revPick.delete(e.number);  // 다 푼 화는 다음 역설계에서 뺀다
    if (!S.revPick.size) S.revPick = new Set(S.revLab.items.filter((e) => !e.sheet && e.chars >= S.rev.min_chars).map((e) => e.number));
  }
  S.revEsts = {};
}

/* ----- 단계 · 다음 할 일 · 진행 줄 · 지표 줄: DOM 없는 순수 함수 (tests/test_revlab.py) ----- */

const REV_PANES = { cast: '인물 · 관계 · 배경', style: '문체 프로필', lines: '이야기 줄기', shape: '구조 · 호흡', metrics: '지표 모아 보기', ai: 'AI 모델' };
const REV_TABS = [['text', '원문 · 큐'], ['plot', '플롯 · 스토리보드'], ['write', '되돌려 쓰기']];
const REV_KINDS = ['rev_parse', 'rev_write', 'rev_style'];

/** 화 제목 줄에서 'n화'를 뗀 이름 ('12화 젖은 필름' → '젖은 필름'). 제목 줄이 없으면 빈 글. */
function revEpTitle(e) {
  const h = String((e && e.head) || '').trim();
  const m = h.match(REV_HEAD);
  return m ? m[2].trim() : h;
}

/** 실험의 단계 다섯: [{ id, label, state, right }]. state 는 ok(끝남) · now(지금 할 단계) · todo · run(그 단계 작업이 도는 중).
    문체 프로필은 고르는 단계라 '지금'이 되지 않는다. minChars 보다 짧은 화는 역설계 대상에서 뺀다. kinds 는 도는 작업 종류. */
/** 화의 판마다 가려 읽기 셈: { original, rewrite, skip, wait, first: { original, rewrite } }. first 는 원문을 처음 본 가려 읽기(seen 0)만. */
function revTakePicks(e) {
  const c = { original: 0, rewrite: 0, skip: 0, wait: 0, first: { original: 0, rewrite: 0 } };
  for (const t of (e && e.takes) || []) {
    const b = t.blind || {};
    if (b.state === 'wait') c.wait += 1;
    else if (b.picked in c) {
      c[b.picked] += 1;
      if (!b.seen && b.picked in c.first) c.first[b.picked] += 1;
    }
  }
  return c;
}

function revSteps(L, minChars, kinds = []) {
  const items = L.items || [];
  const can = items.filter((e) => e.chars >= minChars);
  const parsed = can.filter((e) => e.sheet);
  const wrote = items.filter((e) => (e.takes || []).length);
  const picked = wrote.filter((e) => !revTakePicks(e).wait);
  const rows = [
    { id: 'split', label: '나누기', ok: items.length > 0, right: `${items.length}화` },
    { id: 'parse', label: '역설계', ok: can.length > 0 && parsed.length === can.length, right: `${parsed.length}/${can.length}`, kind: 'rev_parse' },
    { id: 'style', label: '문체 프로필', ok: !!L.style, right: L.style ? '있음' : '고르면', kind: 'rev_style', optional: true },
    { id: 'write', label: '되돌려 쓰기', ok: parsed.length > 0 && wrote.length >= parsed.length, right: `${wrote.length}/${parsed.length}`, kind: 'rev_write' },
    { id: 'pick', label: '가려 읽기', ok: wrote.length > 0 && picked.length === wrote.length, right: `${picked.length}/${wrote.length}` },
  ];
  let now = false;
  return rows.map((r) => {
    let state = r.ok ? 'ok' : 'todo';
    if (r.kind && kinds.includes(r.kind)) state = 'run';
    else if (!r.ok && !r.optional && !now) { state = 'now'; now = true; }
    return { id: r.id, label: r.label, state, right: r.right };
  });
}

/** 단계 막대 비율 (0~1): 고르는 단계(문체 프로필)를 뺀 네 단계 가운데 끝난 수. */
const revStepShare = (steps) => steps.filter((s) => s.id !== 'style' && s.state === 'ok').length / 4;

/** 머리 주 버튼이 할 일: { kind: parse, eps } · { kind: pick | write, n } 이거나 null.
    역설계하지 않은 화가 있으면 역설계, 그다음 지금 화의 가려 읽기 · 되돌려 쓰기, 그다음 다른 화의 가려 읽기, 지금 화 뒤(돌아서 앞)의 되돌려 쓰지 않은 화. */
function revNext(L, n, minChars) {
  const items = L.items || [];
  const raw = items.filter((e) => e.chars >= minChars && !e.sheet).map((e) => e.number);
  if (raw.length) return { kind: 'parse', eps: raw };
  const cur = items.find((e) => e.number === n);
  if (cur && (cur.blind_texts || []).length) return { kind: 'pick', n };
  if (cur && cur.sheet && !(cur.takes || []).length) return { kind: 'write', n };
  const blind = items.find((e) => (e.blind_texts || []).length);
  if (blind) return { kind: 'pick', n: blind.number };
  const i = Math.max(0, items.indexOf(cur));
  const rest = [...items.slice(i + 1), ...items.slice(0, i)].find((e) => e.sheet && !(e.takes || []).length);
  return rest ? { kind: 'write', n: rest.number } : null;
}

/** 목차의 화 줄: [{ n, title, state, right }]. state 는 wrote(되돌려 씀) · parsed(역설계함) · raw(역설계 전) · short(짧아 풀지 않음). */
function revTocEps(items, minChars) {
  return (items || []).map((e) => {
    const state = e.chars < minChars ? 'short' : (e.takes || []).length ? 'wrote' : e.sheet ? 'parsed' : 'raw';
    const right = { short: '짧음', wrote: (e.blind_texts || []).length ? '가려 읽기' : `${(e.takes || []).length}판`, parsed: `큐 ${e.sheet ? e.sheet.cues.length : 0}`, raw: `${e.chars.toLocaleString()}자` }[state];
    return { n: e.number, title: revEpTitle(e), state, right };
  });
}

/** 역설계 작업의 화별 줄: [{ n, title, state: done · run · wait }]. 모든 화를 풀면 묻는 이야기 줄기는 n 0 인 줄.
    job.pending 은 작업이 맡은 화 (web.rev_job), job.done 은 끝낸 요청 수. */
function revRunRows(job, items) {
  const nums = job.pending || [];
  const st = (i) => (i < job.done ? 'done' : i === job.done ? 'run' : 'wait');
  const rows = nums.map((n, i) => ({ n, title: revEpTitle((items || []).find((e) => e.number === n)), state: st(i) }));
  if (job.total > nums.length) rows.push({ n: 0, title: '이야기 줄기', state: st(nums.length) });
  return rows;
}

const REV_METRICS = [  // [이름, 값, 원문과 크게 다르면 표시할지 ('any' 는 하나라도 있으면), 보이는 꼴]
  ['글자', (s) => s.chars, true, (v) => v.toLocaleString()],
  ['핵심 대사 들어감', (s) => (s.lines_total ? `${s.lines_hit}/${s.lines_total}` : null), false],
  ['대사 비율', (s) => s.dialogue_ratio, true, (v) => cuePct(v)],
  ['문장 길이', (s) => s.sentence_len, true],
  ['어휘 다양도', (s) => s.mattr, false],
  ['짧은 끝 문장', (s) => s.short_endings, false, (v) => cuePct(v)],
  ['되풀이 문장', (s) => (s.repeats || []).length, true],
  ['쇠맛 경고', (s) => s.ai_patterns, true],
  ['문체 거리 (원문 다른 화 1.0)', (s) => s.style_distance, true],
  ['쉼표 문장', (s) => s.comma_ratio, true, (v) => cuePct(v)],
  ['표지 빈도 경고', (s) => (s.marker_warns ? s.marker_warns.length : null), true],
  ['원문 옮김', (s) => (s.copied ? s.copied.length : null), 'any'],
  ['장치 예시 옮김', (s) => (s.copied_examples ? s.copied_examples.length : null), 'any'],
  ['템포 (원문 큐 경계)', (s) => ((s.rows || []).length ? cueYes(s.tempo_order) : null), false],
];
const REV_FAR = 0.4;  // 원문 값과 이 비율보다 더 다르면 표시한다

/** 지표 표를 지표마다 한 줄로: { heads: [{ label, stale }], rows: [{ label, cells: [{ text, far }] }], notes: [] }. 열은 scores 차례 (원문이 먼저).
    notes 는 표 밑에 둘 문체 측정 안내: 문체 거리를 재지 않은 이유, 표지 빈도 경고, 옮긴 문장. */
function revMetricRows(scores) {
  const orig = scores.find((s) => s.condition === 'original');
  const far = (v, o) => typeof v === 'number' && typeof o === 'number' && (o ? Math.abs(v - o) / Math.abs(o) > REV_FAR : v > 0);
  return {
    heads: scores.map((s) => ({ label: s.label, stale: !!s.stale })),
    rows: REV_METRICS.map(([label, get, mark, fmt]) => ({
      label,
      cells: scores.map((s) => {
        const v = get(s);
        const hit = mark === 'any' ? typeof v === 'number' && v > 0 : mark && s !== orig && !!orig && far(v, get(orig));
        return { text: v === null || v === undefined ? '-' : fmt ? fmt(v) : String(v), far: hit };
      }),
    })),
    notes: [
      ...[...new Set(scores.map((s) => s.style_note).filter(Boolean))],
      ...scores.filter((s) => (s.marker_warns || []).length).map((s) => `${s.label} 표지: ${s.marker_warns.join(', ')}`),
      ...scores.filter((s) => (s.copied || []).length + (s.copied_examples || []).length)
        .map((s) => `${s.label} 옮긴 문장: ${[...(s.copied || []), ...(s.copied_examples || [])].map((x) => `“${x}”`).join(' ')}`),
    ],
  };
}

/** 목록 값(revlab.summary 의 steps)을 revSteps · revNext 가 읽는 실험 모양으로. */
function revLabLite(x) {
  return {
    style: x.has_style ? {} : null,
    items: (x.steps || []).map((e) => ({ number: e.number, head: e.head, chars: e.chars, sheet: e.sheet ? { cues: [] } : null,
      takes: Array.from({ length: e.takes || 0 }, (_, i) => ({ blind: { state: i < (e.blind || 0) ? 'wait' : 'done' } })),
      blind_texts: e.blind ? ['', ''] : [], picks: e.picks || {} })),
  };
}

const REV_NEXT_LABEL = { parse: (x) => `${x.eps.length}화 역설계`, pick: (x) => `${x.n}화 가려 읽기`, write: (x) => `${x.n}화 되돌려 쓰기` };

/** 처음 화면의 실험 카드 값: { chip: { text, cls }, next, states, share, picks }. 목록 값(revlab.summary) 하나로 센다. */
function revHomeCard(x, minChars) {
  const L = revLabLite(x);
  const steps = revSteps(L, minChars);
  const now = steps.find((s) => s.state === 'now');
  const nx = L.items.length ? revNext(L, L.items[0].number, minChars) : null;
  const picks = { original: 0, rewrite: 0, skip: 0 };
  L.items.forEach((e) => { for (const k of Object.keys(picks)) picks[k] += (e.picks || {})[k] || 0; });
  const chip = !x.done ? { text: '역설계 전', cls: '' } : !now ? { text: '다 견줌', cls: 'ok' } : { text: `${now.label} ${now.right}`, cls: '' };
  return { chip, next: nx ? REV_NEXT_LABEL[nx.kind](nx) : '', states: steps.map((s) => s.state), share: revStepShare(steps), picks };
}

/** 개요의 화별 진행 줄: 큐 · 장면 수, 못 찾은 큐, 판 수 · 모델 수, 판마다 가려 읽기 셈, 최근 판의 핵심 대사,
    대사 비율 원문 → 판들(하나면 그 값, 여럿이면 최소~최대. 원문과 크게 다른 판이 있으면 far). */
function revOverviewRow(e, minChars) {
  const scores = e.scores || [];
  const orig = scores.find((x) => x.condition === 'original');
  const ts = scores.filter((x) => x.condition !== 'original');
  const take = ts[ts.length - 1];
  const o = orig ? orig.dialogue_ratio : null;
  const ds = ts.map((x) => x.dialogue_ratio).filter((v) => typeof v === 'number');
  const lo = Math.min(...ds);
  const hi = Math.max(...ds);
  const isFar = (v) => (o ? Math.abs(v - o) / Math.abs(o) > REV_FAR : v > 0);
  return {
    n: e.number, title: revEpTitle(e),
    state: e.chars < minChars ? 'short' : e.sheet ? 'parsed' : 'raw',
    cues: e.sheet ? e.sheet.cues.length : 0, scenes: e.storyboard ? e.storyboard.scenes.length : 0, missing: (e.missing || []).length,
    takes: (e.takes || []).length, models: new Set((e.takes || []).map((t) => t.model)).size,
    picks: revTakePicks(e),
    lines: take && take.lines_total ? `${take.lines_hit}/${take.lines_total}` : '',
    dlg: o !== null && ds.length ? [cuePct(o), ds.length > 1 && lo !== hi ? `${cuePct(lo)}~${cuePct(hi)}` : cuePct(ds[ds.length - 1])] : null,
    far: o !== null && ds.some(isFar),
  };
}

/* ----- 화면 ----- */

const revRunning = () => (S.revLab ? REV_KINDS.map((k) => jobFor(k, S.revLab.id, REV_JOBS)).find(Boolean) || null : null);
/** 이 실험에 도는 작업 모두. 역설계가 도는 중에도 끝난 화는 되돌려 쓸 수 있어 둘이 함께 돌 수 있다. */
const revRunJobs = () => (S.revLab ? REV_KINDS.map((k) => jobFor(k, S.revLab.id, REV_JOBS)).filter(Boolean) : []);
/** 도는 역설계가 아직 저장하지 않은 화 (지금 푸는 화 포함). 서버 web._rev_parsing 과 같은 셈. */
function revParsing() {
  const j = S.revLab && jobFor('rev_parse', S.revLab.id, REV_JOBS);
  return j ? (j.pending || []).slice(j.done) : [];
}
/** 이 실험의 kind 작업 가운데 멈췄지만 아직 AI 응답을 기다리는 것. 서버 jobs.lingering 과 같은 셈 (다시 시작하면 409). */
const revLingering = (kind) => S.revLab && S.jobs.find((j) => j.waiting && j.project === REV_JOBS && j.kind === kind && j.ep === S.revLab.id);
/** n 화 되돌려 쓰기를 지금 못 하는 까닭 (빈 값이면 쓸 수 있다). 서버도 같은 경우를 409 로 막는다. */
function revWriteBlock(n) {
  if (jobFor('rev_write', S.revLab.id, REV_JOBS)) return '되돌려 쓰는 중이에요. 끝난 뒤에 새 판을 쓸 수 있어요.';
  if (revLingering('rev_write')) return '멈춘 되돌려 쓰기가 아직 AI 응답을 기다려요. 응답이 오면 판으로 남기고, 그 뒤에 새 판을 쓸 수 있어요.';
  if (revParsing().includes(n)) return '이 화는 역설계가 끝난 뒤에 되돌려 쓸 수 있어요.';
  return '';
}

const revEstKey = (kind, eps) => `${kind}:${[...eps].sort((a, b) => a - b).join(',')}`;  // kind: parse · write · write-style · style

/** 글을 치는 중 (체크박스 · 라디오는 빼서, 고르자마자 받은 비용을 바로 그린다). */
const revTyping = () => isTyping() && !document.activeElement.matches('[type="checkbox"], [type="radio"]');

/** 비용 추정 (AI 없음). 처음 부르면 서버에 묻고 null, 받으면 다시 그린다. 버튼은 추정을 받은 뒤에만 눌린다. */
function revEst(kind, eps, style = false) {
  const key = revEstKey(kind === 'write' && style ? 'write-style' : kind, eps);
  const v = S.revEsts[key];
  if (v === undefined) {
    S.revEsts[key] = null;
    const id = S.revLab.id;
    api('POST', `/revlab/${id}/estimate`, { kind, episodes: eps, style })
      .then((d) => { if (S.revLab && S.revLab.id === id) S.revEsts[key] = d; })
      .catch((err) => { if (S.revLab && S.revLab.id === id) S.revEsts[key] = { error: err.message }; })
      .finally(() => { if (!revTyping()) render(); });
  }
  return v && !v.error ? v : null;
}
const revEstErr = (kind, eps, style = false) => ((S.revEsts[revEstKey(kind === 'write' && style ? 'write-style' : kind, eps)] || {}).error || '');

/** 버튼 글: '13화 되돌려 쓰기 · 약 0.04달러'. 추정을 받기 전에는 '비용 재는 중'. */
const revCost = (label, est) => `${esc(label)} <span class="cost">· ${est ? esc(cueUsd(est.usd)) : '비용 재는 중'}</span>`;

/** 비용 자세히 (접은 표, cue.js 실험 카드와 같은 모양). */
function revEstHtml(est) {
  if (!est) return '';
  return `<details class="rev-est"><summary class="small">비용 자세히 · 요청 ${est.calls}번</summary><div class="rev-scroll"><table class="sw-table"><thead><tr><th>요청</th><th>입력 토큰</th><th>출력 토큰</th><th>비용</th></tr></thead><tbody>
    ${est.rows.map((r) => `<tr><td>${esc(r.label)}</td><td>${r.input_tokens.toLocaleString()}</td><td>${r.output_tokens.toLocaleString()}</td><td>${cueUsd(r.usd)}</td></tr>`).join('')}
    <tr><th>합</th><td></td><td></td><th>${cueUsd(est.usd)}</th></tr></tbody></table></div>
    <div class="small">${esc(est.model)} 가격표 기준 · ${esc(est.note)}</div></details>`;
}

function viewRev() {
  const d = S.rev;
  const home = (body) => `${header('실험 · 본편과 분리', '역설계 실험',
    '사람이 쓴 소설을 화별 플롯 · 스토리보드 · 큐 시트로 거꾸로 풀고, 그 큐 시트로 같은 화를 다시 써서 원문과 견줘요. 작품 데이터는 바꾸지 않아요.', revBackBtns())}${body}`;
  if (!d) return home('<div class="note plain">불러오는 중…</div>');
  if (d.error) return home(`<div class="note err">${esc(d.error)}</div>`);
  if (!S.revLab) return revHome();
  if (S.revLab.error) return home(`<div class="note err">${esc(S.revLab.error)}</div><p><a href="#/revlab">실험 목록으로</a></p>`);
  return `${revLabHead()}${revLayout(revLabToc(), revMain())}`;
}

/** 작품에서 들어왔으면 머리 버튼 줄 앞에 그 작품으로 가는 버튼을 둔다 (S.revFrom, app.js routeNow). 작품 목록은 작품 밖 사이드바에 있다 */
function revBackBtns() {
  const f = S.revFrom;
  return f ? `<a class="btn" href="#/p/${enc(f.name)}">‹ ${esc(f.title)}</a>` : '';
}

/** 공용 목차 틀(outline.js): 넓은 칸은 왼쪽 목록, 좁은 칸(틀 720px 이하)은 위에 붙는 '지금 줄 ▾' 버튼. 오른쪽 칸은 남은 폭을 다 쓴다 */
const revLayout = (toc, main) => outlineDoc(toc, `<div class="rev-main">${main}</div>`, { wide: true, cls: 'rev-wrap' });
const revToc = (label, now, list) => outlineNav({ id: 'rev-toc', label, now, body: list });
const revTocLink = (href, inner, cur = false) => `<a class="outline-item" href="${href}"${cur ? ' aria-current="page"' : ''}>${inner}</a>`;

/** 처음 화면: 이어 하기 카드(최근에 고친 차례) + 새 실험 카드(머리 '+ 새 실험'으로 편다, 실험이 없거나 붙여 넣은 글이 있으면 펴 둔다). */
function revHome() {
  const labs = S.rev.labs || [];
  const open = S.revNew || !labs.length || !!S.revDraft.text;
  const btn = labs.length ? `<button type="button" class="btn${open ? ' on' : ' primary'}" data-action="revNewToggle" aria-expanded="${open}" aria-controls="rev-new">+ 새 실험 만들기</button>` : '';
  const head = header('실험 · 본편과 분리', '역설계 실험',
    '사람이 쓴 소설을 화별 플롯 · 스토리보드 · 큐 시트로 거꾸로 풀고, 그 큐 시트로 같은 화를 다시 써서 원문과 견줘요. 작품 데이터는 바꾸지 않아요.', `${revBackBtns()}${btn}`);
  const cards = labs.map((x) => {
    const c = revHomeCard(x, S.rev.min_chars);
    const meta = [`${x.first}~${x.first + x.episodes - 1}화`, `${x.chars.toLocaleString()}자`, x.cast_count ? `인물 ${x.cast_count}명` : '', fmtDateTime(x.updated)].filter(Boolean).join(' · ');
    const done = c.picks.original + c.picks.rewrite + c.picks.skip;
    const tail = c.next ? `다음: ${c.next}` : done ? `가려 읽기 원문 ${c.picks.original} · 판 ${c.picks.rewrite}` : '';
    return `<a class="card rev-lab" href="#/revlab/${x.id}"><div class="between"><h3>${esc(x.title || `실험 ${x.id}`)}</h3><span class="chip${c.chip.cls ? ` ${c.chip.cls}` : ''}">${esc(c.chip.text)}</span></div>
      <div class="small">${esc(meta)}</div>
      <div class="row rev-lab-steps"><span class="rev-steps" aria-hidden="true">${c.states.map((st, i) => `<span class="rev-step ${st}">${st === 'ok' ? '✓' : i + 1}</span>`).join('')}</span>
        <span class="sr-only">단계 ${Math.round(c.share * 4)}/4 끝남.</span>${tail ? `<span class="small">${esc(tail)}</span>` : ''}</div>
      <div class="rev-meter big${c.share === 1 ? ' full' : ''}" aria-hidden="true"><i style="width:${Math.round(c.share * 100)}%"></i></div></a>`;
  }).join('');
  const list = labs.length ? `<section class="rev-home-sec" aria-labelledby="rev-labs-h"><div class="between"><h2 id="rev-labs-h">이어 하기</h2><span class="small">최근에 고친 차례 · ${labs.length}개</span></div>
    <div class="rev-labs">${cards}</div></section>` : '';
  return `${head}<div class="rev-home">${open ? revNewCard(labs.length > 0) : ''}${list}</div>`;
}

const revDraftFirst = () => Number(S.revDraft.first) || revGuessFirst(S.revDraft.title, S.revDraft.text);

function revPreviewHtml() {
  if (!S.revDraft.text.trim()) return '<div class="small">붙여 넣으면 어떻게 나뉘는지 여기 보여요. 직접 나누려면 화 사이에 <code>===</code> 한 줄을 넣으세요.</div>';
  const v = revPreview(S.revDraft.text, S.rev, revDraftFirst());
  if (v.pending) return '<div class="small">나누는 중이에요…</div>';
  const eps = v.eps.map((e) => `<li><span>${e.head ? esc(e.head) : `${e.n}화`}${e.short ? ' <span class="chip warn">짧음</span>' : ''}</span><span class="small">${e.chars.toLocaleString()}자</span></li>`).join('');
  return `<div class="between"><strong>${v.eps.length}화로 나눠요</strong><span class="chip">${esc(v.label)}</span></div>
    <ol class="rev-prev">${eps}</ol>
    ${v.errs.map((x) => `<div class="note err small">${esc(x)}</div>`).join('')}${v.notes.map((x) => `<div class="small">${esc(x)}</div>`).join('')}`;
}

function revNewCard(closable = false) {
  const pv = revPreview(S.revDraft.text, S.rev);
  const ok = !pv.errs.length && !pv.pending;
  const n = S.revDraft.text.length;
  return `<section class="card" id="rev-new"><div class="between"><h2>새 실험</h2>${closable ? '<button type="button" class="btn small ghost" data-action="revNewToggle">닫기</button>' : ''}</div>
    <ol class="rev-how"><li><span class="rev-step now" aria-hidden="true">1</span>붙여 넣고 나누기 <span class="small">AI 없음</span></li>
      <li><span class="rev-step" aria-hidden="true">2</span>역설계 <span class="small">플롯 · 스토리보드 · 큐 시트 · 인물</span></li>
      <li><span class="rev-step" aria-hidden="true">3</span>되돌려 쓰기 · 가려 읽기</li></ol>
    <div class="rev-fields">
      <div class="field rev-f-title"><label for="rev-title">이름</label><input id="rev-title" type="text" data-rev-new="title" value="${esc(S.revDraft.title)}" placeholder="예: 등대지기 1~3화"></div>
      <div class="field rev-f-first"><label for="rev-first">첫 화 번호</label><input id="rev-first" type="number" min="1" max="9999" data-rev-new="first" value="${esc(S.revDraft.first)}" placeholder="${revDraftFirst()}" aria-describedby="rev-first-hint"><span class="small" id="rev-first-hint">비우면 제목 줄이나 이름의 'n화'에서 짐작해요</span></div>
    </div>
    <div class="rev-paste">
      <div class="field"><label for="rev-text">소설 글 <span class="small" id="rev-count">${n ? `· ${n.toLocaleString()}자` : ''}</span></label><textarea id="rev-text" rows="16" data-rev-new="text" placeholder="여기에 붙여 넣으세요">${esc(S.revDraft.text)}</textarea></div>
      <div class="rev-preview" id="rev-preview" aria-live="polite">${revPreviewHtml()}</div>
    </div>
    <div class="between"><span class="small">넣은 글은 이 컴퓨터의 실험 폴더(.revlab)에만 저장해요. 역설계와 되돌려 쓰기는 실제 AI를 불러 비용이 들어요. 버튼에 추정 비용을 함께 보여 드려요.</span>
      <button type="button" class="btn primary" data-action="revCreate"${ok ? '' : ' disabled'}>실험 만들기</button></div></section>`;
}

function revLabHead() {
  const L = S.revLab;
  const desc = [`${L.first}~${L.first + L.episodes - 1}화`, `${L.chars.toLocaleString()}자`, `${L.split_label}로 나눔`,
    L.cast.length ? `인물 ${L.cast.length}명` : '', L.lines.length ? `이야기 줄기 ${L.lines.length}개` : ''].filter(Boolean).join(' · ');
  const menu = () => `<button type="button" class="pop-item" data-action="revEditToggle">글 · 이름 고치기</button>
    ${L.done ? '<button type="button" class="pop-item" data-action="revRedo">다시 역설계할 화 고르기</button>' : ''}
    <a class="pop-item" href="#/revlab">실험 목록 · 새 실험</a>
    <button type="button" class="pop-item danger" data-action="revDelete">실험 지우기</button>`;
  return header('실험 · 본편과 분리 › <a href="#/revlab">역설계 실험</a>', L.title || `실험 ${L.id}`, esc(desc),
    `${revBackBtns()}${menuBtn('rev-lab', '⋯', menu, { aria: '실험 메뉴: 글 · 이름 고치기 · 다시 역설계 · 지우기' })}${revGoBtn()}`);
}

/** 머리 주 버튼 (다음 할 일 하나). 작업이 도는 동안에는 진행 카드의 멈추기만, 글 · 이름을 고치는 동안에는 그 카드의 저장만 둔다. */
function revGoBtn() {
  const L = S.revLab;
  if (revRunning() || S.revEdit || S.revAdd !== null || S.revEpEdit || S.revRedo) return '';  // 다시 역설계를 고르는 동안에는 개요 카드의 버튼이 주 버튼  // 주 버튼은 한 화면에 하나: 글 · 이름 고치기 카드의 '저장'이 주 버튼이다
  const nx = revNext(L, S.revEp, S.rev.min_chars);
  if (!nx) return '';
  if (nx.kind === 'parse') {
    const eps = [...(S.revPick || [])].sort((a, b) => a - b);
    const est = eps.length ? revEst('parse', eps) : null;
    return `<button type="button" class="btn primary" data-action="revParse"${eps.length && est ? '' : ' disabled'}>${eps.length ? revCost(`고른 ${eps.length}화 역설계`, est) : '역설계할 화를 고르세요'}</button>`;
  }
  if (nx.kind === 'pick') return `<button type="button" class="btn primary" data-action="revGo" data-arg="${nx.n}|write">${nx.n}화 가려 읽기</button>`;
  const style = !!(S.revStyle && L.style);
  const est = revEst('write', [nx.n], style);
  return `<button type="button" class="btn primary" data-action="revWrite" data-arg="${nx.n}"${est ? '' : ' disabled'}>${revCost(`${nx.n}화 되돌려 쓰기${style ? ' (문체 넣고)' : ''}`, est)}</button>`;
}

const REV_STEP_GO = { split: 'edit', parse: 'parse', style: 'style', write: 'write', pick: 'pick' };

function revLabToc() {
  const L = S.revLab;
  const runs = revRunJobs();
  const run = runs[0] || null;
  const steps = revSteps(L, S.rev.min_chars, runs.map((j) => j.kind));
  const eps = revTocEps(L.items, S.rev.min_chars);
  const pane = S.revPane;
  const stepRows = steps.map((s, i) => `<button type="button" class="outline-item" data-action="revStep" data-arg="${REV_STEP_GO[s.id]}">
      <span class="n ${s.state}" aria-hidden="true">${s.state === 'ok' ? '✓' : i + 1}</span><span class="tl">${esc(s.label)}</span>
      <span class="st">${s.state === 'run' ? '하는 중' : esc(s.right)}</span><span class="sr-only">${{ ok: '끝남', now: '지금 할 단계', todo: '', run: '하는 중' }[s.state]}</span></button>`).join('');
  const parse = runs.find((j) => j.kind === 'rev_parse');
  const busy = parse ? revRunRows(parse, L.items) : [];
  const epRows = eps.map((x) => {
    const r = busy.find((b) => b.n === x.n);
    const st = r && r.state === 'run' ? '<span class="st">푸는 중</span>' : `<span class="st">${esc(x.right)}</span>`;
    const link = revTocLink(`#/revlab/${L.id}/${x.n}`, `<span class="rev-dot ${r && r.state === 'run' ? 'run' : x.state}" aria-hidden="true"></span><span class="tl">${x.n}화${x.title ? ` ${esc(x.title)}` : ''}</span>${st}`, !pane && x.n === S.revEp);
    return `<div class="rev-toc-ep${S.popMenu === `rev-ep-${x.n}` ? ' open' : ''}">${link}${menuBtn(`rev-ep-${x.n}`, SIDE_ICON.more, () => revEpMenu(x.n, !!run), { cls: 'btn icon-btn rev-toc-btn', aria: `${x.n}화 더보기: 글 고치기 · 지우기` })}</div>`;
  }).join('');
  const panes = Object.entries(REV_PANES).map(([k, label]) => {
    const right = { cast: L.cast.length ? `${L.cast.length}명` : '', style: (L.style_list || []).length ? `${L.style_id ? `${L.style_id}번 · ` : ''}${L.style_list.length}개` : '', lines: L.lines_at ? `${L.lines.length}개` : '', metrics: '', ai: L.ai && L.ai.custom ? '이 실험만' : '' }[k];
    return revTocLink(`#/revlab/${L.id}/${k}`, `<span class="tl">${label}</span><span class="st">${right}</span>`, pane === k);
  }).join('');
  const cur = pane === 'overview' ? `개요 · ${steps[1].label} ${steps[1].right}` : pane ? REV_PANES[pane] : (() => { const e = revItem(S.revEp); return e ? `${e.number}화${revEpTitle(e) ? ` ${esc(revEpTitle(e))}` : ''} · ${(REV_TABS.find(([k]) => k === S.revTab) || REV_TABS[0])[1]}` : '목차'; })();
  const over = revTocLink(`#/revlab/${L.id}`, `<span class="n${pane === 'overview' ? ' now' : ''}" aria-hidden="true">◎</span><span class="tl">개요</span><span class="st">${L.episodes}화</span>`, pane === 'overview');
  return revToc('실험 목차', cur, `${over}<span class="outline-h">단계</span>${stepRows}<div class="rev-meter" role="img" aria-label="단계 ${Math.round(revStepShare(steps) * 4)}/4 끝남"><i style="width:${Math.round(revStepShare(steps) * 100)}%"></i></div>
    <span class="outline-h rev-ep-h">화<button type="button" class="btn icon-btn rev-toc-btn${S.revAdd !== null ? ' on' : ''}" data-action="revAddToggle" data-outline-close aria-label="화 이어 붙이기" title="화 이어 붙이기" aria-pressed="${S.revAdd !== null}">${REV_PLUS}</button></span>${epRows}<span class="outline-h">실험 전체</span>${panes}`);
}

const REV_PLUS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';

/** 목차 화 줄의 ⋯ 메뉴. 지우기는 위험한 묶음으로 한 번 더 접는다 (docs/design Menu). 작업이 도는 동안은 끈다 (서버도 막는다). */
function revEpMenu(n, busy) {
  const off = busy ? ' disabled title="작업이 끝난 뒤에 할 수 있어요"' : '';
  return `<button type="button" class="pop-item" data-action="revEpEdit" data-outline-close data-arg="${n}"${off}>글 고치기</button>
    <div class="pop-sep" role="separator"></div>
    <div class="pop-sec pop-danger"><details><summary class="small">이 화 지우기</summary>
      <div class="small rev-drop-note">원문과 역설계 결과를 지우고 뒤 화 번호를 하나씩 당겨요.</div>
      <button type="button" class="pop-item danger" data-action="revEpDrop" data-arg="${n}"${off}>${n}화 지우기</button></details></div>`;
}

function revMain() {
  const parts = [revRunJobs().filter((j) => !S.revRunHide.has(j.id)).map(revRunCard).join(''), S.revEdit ? revEditCard() : '', S.revAdd !== null ? revAddCard() : '', S.revEpEdit ? revEpEditCard() : ''];
  if (S.revPane === 'overview') parts.push(revOverview());
  else if (S.revPane === 'cast') parts.push(revContextCard());
  else if (S.revPane === 'style') parts.push(revStyleCard());
  else if (S.revPane === 'lines') parts.push(revLinesCard());
  else if (S.revPane === 'shape') parts.push(revPaceCard());
  else if (S.revPane === 'metrics') parts.push(revMetricsAll());
  else if (S.revPane === 'ai') parts.push(revAICard());
  else parts.push(revEpisode());
  return parts.join('');
}

function revEditCard() {
  const L = S.revLab;
  return `<section class="card"><div class="between"><h2>글 · 이름 고치기</h2><button type="button" class="btn small ghost" data-action="revEditToggle">닫기</button></div>
    <div class="rev-fields">
      <div class="field rev-f-title"><label for="rev-etitle">이름</label><input id="rev-etitle" type="text" data-rev-edit="title" value="${esc(L.title)}"></div>
      <div class="field rev-f-first"><label for="rev-efirst">첫 화 번호</label><input id="rev-efirst" type="number" min="1" max="9999" data-rev-edit="first" value="${L.first}"></div>
    </div>
    ${L.first <= 3 ? '<div class="note warn small">1~3화로 잡혀 되돌려 쓰기에 초반 규칙(첫 화 쓰는 법)이 붙어요. 소설 중간이면 첫 화 번호를 바꾸세요.</div>' : ''}
    ${L.preface ? `<div class="small">앞머리(역설계하지 않음): ${esc(L.preface.slice(0, 120))}</div>` : ''}
    <div class="field"><label for="rev-etext">글 <span class="small">(비우면 글은 그대로 두고 이름 · 번호만 바꿔요)</span></label><textarea id="rev-etext" rows="8" data-rev-edit="text" placeholder="새 글을 붙여 넣으면 다시 나누고 역설계 결과를 모두 지워요"></textarea></div>
    <div class="row"><button type="button" class="btn primary" data-action="revSaveEdit">저장</button></div></section>`;
}

/** 이어 붙일 화 수 · 글자 수를 셀 실험 값: 다음 화 번호 · 화 수 · 글자 수. */
const revHave = (L) => ({ next: L.items.length ? L.items[L.items.length - 1].number + 1 : L.first, episodes: L.items.length, chars: L.chars });

function revAddPreviewHtml() {
  if (!S.revAdd.trim()) return `<div class="small">붙여 넣으면 어떻게 나뉘는지 여기 보여요. 새 화는 ${revHave(S.revLab).next}화부터 이어요. 직접 나누려면 화 사이에 <code>===</code> 한 줄을 넣으세요.</div>`;
  const v = revAppendPreview(S.revAdd, S.rev, revHave(S.revLab));
  if (v.pending) return '<div class="small">나누는 중이에요…</div>';
  const eps = v.eps.map((e) => `<li><span>${e.n}화${e.head ? ` <span class="small">${esc(e.head)}</span>` : ''}${e.short ? ' <span class="chip warn">짧음</span>' : ''}</span><span class="small">${e.chars.toLocaleString()}자</span></li>`).join('');
  return `<div class="between"><strong>${revAddRange(v)}를 이어요</strong><span class="chip">${esc(v.label)}</span></div>
    <ol class="rev-prev">${eps}</ol>
    ${v.errs.map((x) => `<div class="note err small">${esc(x)}</div>`).join('')}${v.notes.map((x) => `<div class="small">${esc(x)}</div>`).join('')}`;
}

/** 이을 화 범위 글 ('5화', '5~7화'). 화가 없으면 빈 글. */
const revAddRange = (v) => (!v.eps.length ? '' : v.eps.length > 1 ? `${v.eps[0].n}~${v.eps[v.eps.length - 1].n}화` : `${v.eps[0].n}화`);
const revAddLabel = (v) => (v.eps.length && !v.errs.length ? `${revAddRange(v)} 이어 붙이기` : '이어 붙이기');

/** 실험에 이미 있는 이 원고 화의 차례. */
const revRefTaken = (book, L) => new Set(L.items.filter((x) => x.source && x.source.ref === book.id).map((x) => x.source.order));
const revRefUsable = (e) => e.kind !== 'skip' && e.chars > 0;

/** 레퍼런스 원고에서 고른 화의 미리보기 (revlab.append_episodes 와 같은 규칙). book: GET /refs/<id> 값, pick: 고른 차례,
 * L: 실험 { items, chars }, lim: { max_chars } (화 수는 막지 않는다). 이미 실험에 있는 화는 빼고(skipped), 새 화 번호는 마지막 화 + 1 부터 센다.
 * missing 은 고른 화와 이미 넣은 화 사이에서 빠진 원고 화 이름 (제외 화는 셈하지 않는다). */
function revRefPreview(book, pick, L, lim) {
  const taken = revRefTaken(book, L);
  const want = new Set(pick);
  const chosen = book.episodes.filter((e) => want.has(e.order) && revRefUsable(e));
  const fresh = chosen.filter((e) => !taken.has(e.order));
  const next = L.items.length ? L.items[L.items.length - 1].number + 1 : 1;
  const eps = fresh.map((e, i) => ({ n: next + i, order: e.order, label: e.label, title: e.title, chars: e.chars }));
  const chars = eps.reduce((k, e) => k + e.chars, 0);
  const errs = [];
  if (L.chars + chars > lim.max_chars) errs.push(`이으면 ${(L.chars + chars).toLocaleString()}자예요. 한 실험에 ${lim.max_chars.toLocaleString()}자까지 넣을 수 있어요`);
  const have = [...taken, ...fresh.map((e) => e.order)];
  const lo = Math.min(...have);
  const hi = Math.max(...have);
  const missing = fresh.length ? book.episodes.filter((e) => revRefUsable(e) && e.order > lo && e.order < hi && !have.includes(e.order)).map((e) => e.label || `${e.order}번째`) : [];
  return { eps, skipped: chosen.length - fresh.length, chars, errs, missing, next };
}

/** '이어서 다음 k화': 실험에 넣은 이 원고의 마지막 차례 뒤로, 아직 넣지 않은 쓸 수 있는 화 k개의 차례. */
function revRefNext(book, L, k = 5) {
  const taken = revRefTaken(book, L);
  const last = taken.size ? Math.max(...taken) : 0;
  return book.episodes.filter((e) => revRefUsable(e) && e.order > last && !taken.has(e.order)).slice(0, k).map((e) => e.order);
}

const revRefLabel = (v) => (!v.eps.length ? '이어 붙이기' : `${v.eps.length > 1 ? `${v.eps[0].n}~${v.eps[v.eps.length - 1].n}화` : `${v.eps[0].n}화`}로 이어 붙이기`);

/** 화 이어 붙이기의 '레퍼런스 원고에서' 칸: 원고 고르기, 화 표, 미리보기. */
function revRefAddHtml() {
  if (!S.revRefs) return '<div class="small">레퍼런스 원고를 불러오는 중이에요…</div>';
  if (S.revRefs.error) return `<div class="note err small">${esc(S.revRefs.error)}</div>`;
  if (!S.revRefs.refs.length) return '<p class="small">레퍼런스 원고가 없어요. <a href="#/refs/new">레퍼런스 원고</a>에서 원고 txt를 먼저 넣으세요.</p>';
  const b = S.revRefBook;
  const opts = S.revRefs.refs.map((r) => `<option value="${esc(r.id)}"${b && b.id === r.id ? ' selected' : ''}>${esc(r.name)} · ${r.episodes}화</option>`).join('');
  const sel = `<div class="row"><label class="small" for="rev-ref">원고</label><select id="rev-ref" data-rev-ref="1"><option value="">원고 고르기</option>${opts}</select>
    ${b ? `<a class="small" href="#/refs/${enc(b.id)}">원고 화면 ›</a>` : ''}</div>`;
  if (!b) return sel;
  if (b.error) return `${sel}<div class="note err small">${esc(b.error)}</div>`;
  const L = S.revLab;
  const taken = revRefTaken(b, L);
  const v = revRefPreview(b, S.revRefPick, L, S.rev);
  const rows = b.episodes.map((e) => {
    const has = taken.has(e.order);
    const off = !revRefUsable(e) || has;
    const note = has ? '<span class="chip">이미 있음</span>' : e.kind === 'skip' ? '<span class="small">제외</span>' : '';
    return `<tr class="${off ? 'off' : ''}"><td><input type="checkbox" data-rev-ref-pick="${e.order}"${S.revRefPick.has(e.order) && !off ? ' checked' : ''}${off ? ' disabled' : ''} aria-label="${esc(refEpName(e))} 고르기"></td>
      <td>${esc(e.label || `${e.order}번째`)}</td><td>${esc(e.title || '')} ${note}</td><td class="num">${e.chars.toLocaleString()}</td></tr>`;
  }).join('');
  const prev = v.eps.length
    ? `<div class="between"><strong>${v.eps.length}화를 이어요 → ${v.eps.length > 1 ? `${v.eps[0].n}~${v.eps[v.eps.length - 1].n}화` : `${v.eps[0].n}화`}</strong><span class="small">${v.chars.toLocaleString()}자</span></div>
      <div class="small">원고 ${esc(v.eps.map((e) => e.label || `${e.order}번째`).join(', '))}${v.skipped ? ` · 이미 있는 ${v.skipped}화는 빼요` : ''}</div>`
    : `<div class="small">표에서 이을 화를 고르세요. 새 화는 ${v.next}화부터 이어요.</div>`;
  const notes = [...v.errs.map((x) => `<div class="note err small">${esc(x)}</div>`),
    v.missing.length ? `<div class="note warn small">원고 ${esc(v.missing.slice(0, 5).join(', '))}${v.missing.length > 5 ? ` 외 ${v.missing.length - 5}화` : ''}가 빠져요.</div>` : ''].join('');
  return `${sel}
    <div class="row"><button type="button" class="btn small" data-action="revRefNext">이어서 다음 5화</button>
      <label class="small" for="rev-ref-range">범위</label><input id="rev-ref-range" type="text" data-rev-ref-range="1" placeholder="예: 16~20" size="12">
      <button type="button" class="btn small" data-action="revRefRange">고르기</button>
      <button type="button" class="btn small" data-action="revRefNone"${S.revRefPick.size ? '' : ' disabled'}>모두 풀기</button></div>
    <div class="rev-ref-table"><table class="tbl"><thead><tr><th scope="col"><span class="sr-only">고르기</span></th><th scope="col">번호</th><th scope="col">제목</th><th scope="col" class="num">글자</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="rev-preview" aria-live="polite">${prev}${notes}</div>`;
}

/** 화 이어 붙이기 칸: 붙여 넣은 글을 나눠, 또는 레퍼런스 원고에서 고른 화를 마지막 화 뒤에 잇는다. 앞 화의 역설계 결과는 그대로 둔다
 * (revlab.append_text · append_episodes). */
function revAddCard() {
  const from = `<div class="seg" role="group" aria-label="이어 붙일 곳">${[['text', '글 붙여 넣기'], ['ref', '레퍼런스 원고에서']].map(([k, l]) => `<button type="button" aria-pressed="${S.revAddFrom === k}" data-action="revAddFrom" data-arg="${k}">${l}</button>`).join('')}</div>`;
  const shut = '<button type="button" class="btn small ghost" data-action="revAddToggle">닫기</button>';
  if (S.revAddFrom === 'ref') {
    const b = S.revRefBook;
    const v = b && !b.error ? revRefPreview(b, S.revRefPick, S.revLab, S.rev) : { eps: [], errs: [] };
    const ok = v.eps.length && !v.errs.length && !revRunning();
    return `<section class="card"><div class="between"><h2>화 이어 붙이기</h2>${shut}</div>${from}
      <p class="small">원고에서 나눈 화를 그대로 마지막 화 뒤에 넣어요. 이미 이 실험에 있는 화는 빼요. 화 번호는 원고 번호와 상관없이 이어서 세고, 원고 번호는 화 머리에 출처로 보여요.</p>
      ${revRefAddHtml()}
      ${revRunning() ? '<div class="note warn small">작업이 끝난 뒤에 이을 수 있어요.</div>' : ''}
      <div class="row"><button type="button" class="btn primary" data-action="revAppendRef"${ok ? '' : ' disabled'}>${revRefLabel(v)}</button></div></section>`;
  }
  const v = revAppendPreview(S.revAdd, S.rev, revHave(S.revLab));
  const ok = !v.errs.length && !v.pending && !revRunning();
  return `<section class="card"><div class="between"><h2>화 이어 붙이기</h2>${shut}</div>${from}
    <p class="small">마지막 화 뒤에 새 화를 넣어요. 앞 화의 역설계 결과 · 인물 · 문체 프로필은 그대로 두고, 새 화를 역설계할 때 앞 화의 인물 · 줄거리가 들어가요. 이야기 줄기는 새 화까지 역설계하면 다시 물어요.</p>
    <div class="rev-paste">
      <div class="field"><label for="rev-atext">이어 붙일 글 <span class="small" id="rev-acount">${S.revAdd ? `· ${S.revAdd.length.toLocaleString()}자` : ''}</span></label><textarea id="rev-atext" rows="12" data-rev-add="1" placeholder="여기에 붙여 넣으세요">${esc(S.revAdd)}</textarea></div>
      <div class="rev-preview" id="rev-apreview" aria-live="polite">${revAddPreviewHtml()}</div>
    </div>
    ${revRunning() ? '<div class="note warn small">작업이 끝난 뒤에 이을 수 있어요.</div>' : ''}
    <div class="row"><button type="button" class="btn primary" data-action="revAppend"${ok ? '' : ' disabled'}>${revAddLabel(v)}</button></div></section>`;
}

/** 화 하나 고치기 칸: 제목 줄과 글. 글을 바꾸면 그 화의 역설계 결과를 지운다 (revlab.edit_episode). */
function revEpEditCard() {
  const d = S.revEpEdit;
  const e = revItem(d.n);
  if (!e) return '';
  const done = !!(e.sheet || (e.takes || []).length);
  return `<section class="card"><div class="between"><h2>${d.n}화 글 고치기</h2><button type="button" class="btn small ghost" data-action="revEpEditClose">닫기</button></div>
    ${done ? '<div class="note warn small">글을 바꾸면 이 화의 역설계 결과(플롯 · 스토리보드 · 큐 시트)와 되돌려 쓴 판을 지워요. 제목 줄만 바꾸면 그대로 둬요. 다른 화 · 인물 · 이야기 줄기는 그대로예요.</div>' : ''}
    <div class="field"><label for="rev-ephead">제목 줄</label><input id="rev-ephead" type="text" maxlength="${S.rev.head_max}" data-rev-ep="head" value="${esc(d.head)}" placeholder="비우면 '${d.n}화'로 보여요"></div>
    <div class="field"><label for="rev-eptext">글 <span class="small" id="rev-epcount">· ${d.text.length.toLocaleString()}자</span></label><textarea id="rev-eptext" rows="16" data-rev-ep="text">${esc(d.text)}</textarea></div>
    <div class="row"><button type="button" class="btn primary" data-action="revEpSave"${revRunning() ? ' disabled' : ''}>저장</button></div></section>`;
}

/** 도는 작업 카드: 역설계는 화마다 한 줄(끝난 화는 바로 열기), 되돌려 쓰기 · 문체는 한 줄. 멈추기는 알림 창과 같은 동작.
    닫으면 그 작업 동안만 감춘다 (진행은 알림 창에 남는다). 역설계와 되돌려 쓰기가 함께 돌면 카드가 둘이다. */
function revRunCard(j) {
  const L = S.revLab;
  const pct = Math.round((100 * j.done) / Math.max(1, j.total));
  const what = { rev_parse: '역설계하는 중', rev_write: '되돌려 쓰는 중', rev_style: '문체를 역설계하는 중' }[j.kind];
  const rows = j.kind === 'rev_parse' ? revRunRows(j, L.items).map((r) => `<li class="rev-run-row ${r.state}">
      <span class="rev-dot ${r.state === 'done' ? 'wrote' : r.state}" aria-hidden="true"></span>
      <span class="tl">${r.n ? `<strong>${r.n}화</strong>${r.title ? ` ${esc(r.title)}` : ''}` : `<strong>${esc(r.title)}</strong> <span class="small">모든 화를 푼 뒤 한 번</span>`}</span>
      <span class="small">${{ done: '끝', run: '푸는 중', wait: '기다림' }[r.state]}</span>
      ${r.state === 'done' && r.n ? `<a class="btn small" href="#/revlab/${L.id}/${r.n}">열기</a>` : '<span></span>'}</li>`).join('') : '';
  const left = jobLeft(j, Date.now() / 1000);
  return `<section class="card rev-run" aria-live="polite"><div class="between"><h2>${what}</h2><span class="row" style="gap:6px"><button type="button" class="btn small" data-job-stop="${j.id}">멈추기</button><button type="button" class="btn small ghost" data-action="revRunClose" data-arg="j${j.id}" title="작업은 계속 돌아요">닫기</button></span></div>
    <div class="small"><span data-elapsed="${j.id}" aria-hidden="true">경과 ${elapsed(j)}</span>${j.total > 1 ? ` · 요청 ${j.total}번 중 ${Math.min(j.done + 1, j.total)}번째` : ''}${left ? ` · ${left}` : ''}</div>
    <div class="rev-meter big" role="progressbar" aria-valuemin="0" aria-valuemax="${j.total}" aria-valuenow="${j.done}" aria-label="${what}"><i style="width:${pct}%"></i></div>
    ${rows ? `<ol class="rev-run-rows">${rows}</ol>` : ''}
    <div class="note plain">${j.kind === 'rev_parse' ? '화마다 끝나는 대로 저장해요. 끝난 화는 지금 열어 되돌려 써도 되고, 다른 화면으로 가도 돼요. ' : ''}다 끝나면 위쪽 알림 버튼으로 알려 드려요.</div></section>`;
}

/** 개요: 역설계 전(또는 다시 역설계를 고를 때)은 풀 화 표와 화마다 받는 것, 역설계 뒤는 화별 진행 표와 실험 전체 카드. */
function revOverview() {
  const L = S.revLab;
  const raw = L.items.some((e) => e.chars >= S.rev.min_chars && !e.sheet);
  if ((raw || S.revRedo) && !jobFor('rev_parse', L.id, REV_JOBS)) return `${revPickCard()}${raw && !L.done ? revGetCard() : revProgressCard()}`;
  return `${revProgressCard()}${revLabCards()}`;
}

/** 풀 화 표: 고르기 · 제목 · 글자 · 첫 문장 · 화별 비용(모든 화를 한 번에 잰 값). 합계와 시작은 머리 주 버튼, 다시 역설계할 때는 이 카드의 버튼. */
function revPickCard() {
  const L = S.revLab;
  const min = S.rev.min_chars;
  const can = L.items.filter((e) => e.chars >= min).map((e) => e.number);
  const each = can.length ? revEst('parse', can) : null;
  const pick = S.revPick || new Set();
  const eps = [...pick].sort((a, b) => a - b);
  const est = eps.length ? revEst('parse', eps) : null;
  const err = eps.length ? revEstErr('parse', eps) : '';
  const cost = (label) => { const r = each && each.rows.find((x) => x.label === label); return r ? cueUsd(r.usd) : '…'; };
  const first = (t) => { const x = String(t || '').replace(/\s+/g, ' ').trim(); return x.length > 40 ? `${x.slice(0, 40)}…` : x; };
  const all = can.length > 0 && can.every((n) => pick.has(n));
  const rows = L.items.map((e) => {
    const off = e.chars < min;
    return `<tr><td><input type="checkbox" data-rev-pick="${e.number}" aria-label="${e.number}화 고르기"${pick.has(e.number) && !off ? ' checked' : ''}${off ? ' disabled' : ''}></td>
      <td class="rev-l"><strong>${e.number}화</strong>${revEpTitle(e) ? ` ${esc(revEpTitle(e))}` : ''}${e.sheet ? ' <span class="chip">풀었음</span>' : ''}${off ? ' <span class="chip">짧음</span>' : ''}</td>
      <td>${e.chars.toLocaleString()}</td><td class="rev-l rev-first">${esc(first(e.text))}</td><td>${off ? '-' : esc(cost(`${e.number}화`))}</td></tr>`;
  }).join('');
  const lines = est && est.rows.find((r) => r.label === '이야기 줄기');
  const redo = eps.some((n) => (revItem(n) || {}).sheet);
  const busy = !!revRunning();
  return `<section class="card"><div class="between"><h2>${S.revRedo ? '다시 역설계할 화' : '역설계할 화'}</h2>
      <span class="row"><label class="check-row small"><input type="checkbox" data-rev-all="1"${all ? ' checked' : ''}><span>모두 고르기</span></label>${S.revRedo ? '<button type="button" class="btn small ghost" data-action="revRedo">닫기</button>' : ''}</span></div>
    <div class="rev-scroll"><table class="sw-table rev-pick-table"><thead><tr><th><span class="sr-only">고르기</span></th><th class="rev-l">화</th><th>글자</th><th class="rev-l">첫 문장</th><th>비용</th></tr></thead>
      <tbody>${rows}${lines ? `<tr class="rev-muted"><td></td><td class="rev-l">이야기 줄기</td><td></td><td class="rev-l">모든 화를 푼 뒤 한 번</td><td>${esc(cueUsd(lines.usd))}</td></tr>` : ''}</tbody></table></div>
    <p class="small">앞 화부터 차례로 풀어요. 앞 화의 인물 · 줄거리 · 끝 부분이 다음 화 요청에 들어가서, 중간 화만 고르면 앞 이야기를 모르고 풀어요.</p>
    ${revAiLine('plan')}
    ${redo ? '<div class="note warn small">이미 역설계한 화를 다시 풀면 그 화의 큐 시트 고침이 사라져요. 되돌려 쓴 판은 남고 \'시트 바뀜\'으로 보여요.</div>' : ''}
    ${err ? `<div class="note err small">비용을 재지 못했어요: ${esc(err)}</div>` : ''}
    ${S.revRedo ? `<div class="row"><button type="button" class="btn primary" data-action="revParse"${eps.length && est && !busy ? '' : ' disabled'}>${eps.length ? revCost(`고른 ${eps.length}화 다시 역설계`, est) : '화를 고르세요'}</button></div>` : ''}
    ${revEstHtml(est)}</section>`;
}

/** 화마다 받는 것 (역설계 전 개요). */
function revGetCard() {
  const tile = (t, d) => `<div class="rev-get"><strong>${t}</strong><span class="small">${d}</span></div>`;
  return `<section class="card"><h2>화마다 받는 것</h2><div class="rev-gets">
    ${tile('화 플롯', '요약 · 사건 · 등장 인물 · 감정 변화 · 엔딩 훅')}
    ${tile('스토리보드', '장면마다 장소 · 시간 · 있는 사람 · 맡은 사건')}
    ${tile('큐 시트', '기능 · 긴장 · 템포 · 핵심 대사. 경계는 원문 문장을 그대로 인용해 정해요')}
    ${tile('인물 · 관계 · 배경', '되돌려 쓸 때 작품 설정으로 들어가요')}</div></section>`;
}

/** 화별 진행 표 (개요). 줄의 '열기'로 그 화의 작업대로 간다. */
function revProgressCard() {
  const L = S.revLab;
  const min = S.rev.min_chars;
  const rows = L.items.map((e) => {
    const r = revOverviewRow(e, min);
    const bars = e.sheet ? `<span class="rev-mini" aria-hidden="true">${cueBars(e.sheet).map((b) => `<i style="flex:${b.w} 1 0;height:${b.h}%;background:${CUE_COLORS[b.fn] || 'var(--chip)'}"></i>`).join('')}</span>` : '';
    const parse = r.state === 'short' ? '짧아 풀지 않음' : r.state === 'raw' ? '<span class="chip">역설계 전</span>'
      : `큐 ${r.cues}${r.scenes ? ` · 장면 ${r.scenes}` : ''}${r.missing ? ` <span class="chip warn">${r.missing}곳 못 찾음</span>` : ''}`;
    const pk = r.picks;
    const pick = `${pk.original || pk.rewrite || pk.skip ? `원문 ${pk.original} · 판 ${pk.rewrite}` : '-'}${pk.wait ? ` <span class="chip warn">${pk.wait} 남음</span>` : ''}`;
    const dlg = r.dlg ? `${r.dlg[0]} → ${r.far ? `<strong class="rev-far">${r.dlg[1]}</strong>` : r.dlg[1]}` : '-';
    return `<tr${e.number === S.revEp ? ' class="rev-cur"' : ''}><td class="rev-l"><strong>${e.number}화</strong>${r.title ? ` ${esc(r.title)}` : ''}</td><td class="rev-l">${bars}</td><td class="rev-l">${parse}</td>
      <td>${r.takes ? `<span class="chip ok">${r.takes}판</span>${r.models > 1 ? ` <span class="small">모델 ${r.models}</span>` : ''}` : r.state === 'parsed' ? '아직' : '-'}</td><td>${pick}</td><td>${esc(r.lines || '-')}</td><td>${dlg}</td>
      <td><a class="btn small ghost" href="#/revlab/${L.id}/${e.number}" aria-label="${e.number}화 열기">열기 ›</a></td></tr>`;
  }).join('');
  return `<section class="card"><div class="between"><h2>화별 진행</h2><span class="small">'열기'로 그 화의 원문 · 큐 · 되돌려 쓰기를 봐요</span></div>
    <div class="rev-scroll"><table class="sw-table rev-prog-table"><thead><tr><th class="rev-l">화</th><th class="rev-l">진행 (큐)</th><th class="rev-l">역설계</th><th>되돌려 쓰기</th><th>가려 읽기</th><th>핵심 대사 (최근 판)</th><th>대사 비율 원문 → 판들</th><th><span class="sr-only">열기</span></th></tr></thead>
    <tbody>${rows}</tbody></table></div></section>`;
}

/** 실험 전체 카드 셋 (개요): 인물 · 문체 프로필 · 이야기 줄기 한 줄 요약과 그 칸으로 가는 링크. */
function revLabCards() {
  const L = S.revLab;
  const c = (L.context || [])[0] || {};
  const st = L.style;
  const card = (k, title, right, body) => `<a class="card tight rev-tile" href="#/revlab/${L.id}/${k}"><div class="between"><h3>${title}</h3><span class="small">${right}</span></div><p class="small">${body}</p></a>`;
  return `<div class="rev-tiles">
    ${card('cast', '인물 · 관계 · 배경', L.cast.length ? `${L.cast.length}명` : '', L.cast.length ? `${esc(L.cast.slice(0, 4).map((x) => x.name).join(' · '))}${c.setting ? `. ${esc(c.setting.slice(0, 40))}` : ''}` : '역설계하면 모아요.')}
    ${card('style', '문체 프로필', st ? `${L.style_id}번 · 표지 ${(st.markers || []).length}` : '', st ? esc([st.narration_pov, st.tense, st.sentence_rhythm].filter(Boolean).join(' · ').slice(0, 80)) : '만들면 되돌려 쓰기에 넣을 수 있어요.')}
    ${card('lines', '이야기 줄기', L.lines_at ? `${L.lines.length}개` : '', L.lines_at ? `메인: ${esc((L.main || '정하지 않음').slice(0, 60))}` : '모든 화를 역설계하면 찾아요.')}
    ${card('shape', '구조 · 호흡', '', '화마다 긴장 흐름 · 끝맺음 · 분량을 이어 봐요.')}
    ${card('ai', 'AI 모델', L.ai.custom ? '이 실험만' : '설정을 따름', L.ai.stages.map((x) => `${x.stage === 'plan' ? '역설계' : '되돌려 쓰기'} ${esc(revAiText(x.use))}`).join(' · '))}</div>`;
}

/** 인물 · 관계 · 배경: 되돌려 쓰기 사본의 작품 설정이 되는 것 (revlab.world). 마지막으로 역설계한 화까지 읽은 값. */
function revContextCard() {
  const L = S.revLab;
  if (!L.cast.length) return '<section class="card empty"><h2>인물 · 관계 · 배경</h2><p>역설계하면 화마다 나온 인물 · 관계 · 호칭 · 배경을 모아요. 되돌려 쓸 때 작품 설정으로 들어가요.</p></section>';
  const c = (L.context || [])[0] || { setting: '', facts: [], ties: [], addresses: [] };
  const li = (xs) => `<ul class="rev-ul small">${xs.join('')}</ul>`;
  const cast = L.cast.map((x) => `<li><strong>${esc(x.name)}</strong>${x.role ? ` · ${esc(x.role)}` : ''}${x.personality ? `<br>성격: ${esc(x.personality)}` : ''}${x.speech ? `<br>말투: ${esc(x.speech)}` : ''}</li>`);
  return `<section class="card"><h2>인물 · 관계 · 배경 <span class="small">되돌려 쓸 때 작품 설정으로 들어가요</span></h2>
    ${c.setting ? `<div class="small"><strong>배경</strong> — ${esc(c.setting)}</div>` : ''}
    <h3>인물</h3>${li(cast)}
    ${c.ties.length ? `<h3>관계</h3>${li(c.ties.map((t) => `<li>${esc(t.a)} · ${esc(t.b)} (${esc(t.type)})${t.description ? ` — ${esc(t.description)}` : ''}</li>`))}` : ''}
    ${c.addresses.length ? `<h3>호칭 · 말씨</h3>${li(c.addresses.map((a) => `<li>${esc(a.speaker)} → ${esc(a.listener)}: ${a.calls ? `'${esc(a.calls)}'` : '부르는 말 없음'}${a.speech ? ` · ${esc(a.speech)}` : ''}</li>`))}` : ''}
    ${c.facts.length ? `<h3>앞 이야기 · 사실</h3>${li(c.facts.map((f) => `<li>${esc(f)}</li>`))}` : ''}</section>`;
}

/** 문체 프로필: 원문 앞부분으로 역설계한다 (예시 문단은 비움). 다시 만들면 기록에 남고 새 프로필을 지금 프로필로 고른다.
    기록에서 다른 프로필을 고르거나(revStyleUse) 지금 프로필과 칸별로 견주거나(revStyleDiff, changeLines) 지운다. */
function revStyleCard() {
  const L = S.revLab;
  if (!L.done) return '<section class="card empty"><h2>문체 프로필</h2><p>화를 하나 넘게 역설계한 뒤에 만들 수 있어요.</p></section>';
  const st = L.style;
  const list = L.style_list || [];
  const cur = list.find((x) => x.current);
  const est = revEst('style', []);
  const busy = !!revRunning();
  const kv = (k, v) => (v ? `<dt>${k}</dt><dd>${esc(v)}</dd>` : '');
  const body = st ? `<dl class="rev-kv">${kv('시점', st.narration_pov)}${kv('시제', st.tense)}${kv('문장 리듬', st.sentence_rhythm)}${kv('묘사 밀도', st.description_density)}
      ${kv('대사 비중', st.dialogue_ratio)}${kv('대사 방식', st.dialogue_style)}${kv('속생각', st.inner_monologue)}${kv('속도', st.pacing)}${kv('장면 전환', st.scene_transition)}${kv('어휘', st.vocabulary)}</dl>
      ${(st.markers || []).length ? `<div class="small">표지: ${st.markers.map((m) => `«${esc(m.text)}»`).join(' · ')}</div>` : ''}
      <div class="small">${esc(L.style_model)} · ${esc(fmtDateTime(L.style_at))}${cur && !cur.basis_ok ? ' <span class="chip">원문 앞부분이 바뀌었어요</span>' : ''}</div>`
    : list.length ? '<p class="small">지금 고른 프로필이 없어요. 아래 기록에서 고르거나 새로 만드세요.</p>'
      : '<p class="small">원문 앞부분으로 문체 프로필(시점 · 문장 리듬 · 대사 방식 · 표지)을 만들어요. 원문을 베끼지 않게 예시 문단은 넣지 않아요. 되돌려 쓰기에서 문체를 넣은 판과 넣지 않은 판을 견주면 차이가 구조에서 오는지 문체에서 오는지 갈라 볼 수 있어요.</p>';
  const rows = list.map((x) => {
    const open = S.revStyleDiff && S.revStyleDiff.id === x.id;
    const chips = `${x.current ? ' <span class="chip finalized">지금</span>' : ''}${x.basis_ok ? '' : ' <span class="chip">다른 원문</span>'}`;
    const diff = open ? (S.revStyleDiff.changes == null ? '<div class="small">견줄 지금 프로필이 없어요.</div>'
      : S.revStyleDiff.changes.length ? S.revStyleDiff.changes.map(changeLines).join('') : '<div class="small">지금 프로필과 같아요.</div>') : '';
    return `<li class="version-row">
        <div class="between"><span><strong>${x.id}번</strong> <span class="small">${esc(fmtDateTime(x.at))}${x.model ? ` · ${esc(x.model)}` : ''} · 표지 ${x.markers}${x.takes ? ` · 쓴 판 ${x.takes}` : ''}</span>${chips}</span>
          <span class="row">${x.current ? '' : `<button type="button" class="btn small" data-action="revStyleUse" data-arg="${x.id}"${busy ? ' disabled' : ''}>이 프로필 쓰기</button>
            <button type="button" class="btn small ghost" data-action="revStyleDiff" data-arg="${x.id}" aria-expanded="${open}">${open ? '견주기 닫기' : '지금과 견주기'}</button>`}
            ${x.library ? `<a class="btn small ghost" href="#/styles/${enc(x.library)}">라이브러리에서 보기</a>` : `<button type="button" class="btn small ghost" data-action="revStyleToLib" data-arg="${x.id}">라이브러리에 저장</button>`}
            <button type="button" class="btn small ghost" data-action="revStyleNote" data-arg="${x.id}">메모</button>
            <button type="button" class="btn small ghost" data-action="revStyleDrop" data-arg="${x.id}"${busy || (x.current && list.length > 1) ? ' disabled' : ''}>지우기</button></span></div>
        ${x.head ? `<div class="small">${esc(x.head)}</div>` : ''}${x.note ? `<div class="small">메모: ${esc(x.note)}</div>` : ''}${diff}
      </li>`;
  }).join('');
  return `<section class="card"><h2>문체 프로필${cur ? ` · ${cur.id}번` : ''}</h2>${body}
    ${revAiLine('plan')}
    <div class="row"><button type="button" class="btn" data-action="revStyleRun"${est && !busy ? '' : ' disabled'}>${revCost(list.length ? '문체 다시 역설계' : '문체 역설계 시작', est)}</button></div>
    ${list.length ? `<p class="small">새로 만들면 기록에 남고 새 프로필을 지금 프로필로 골라요. 작품에 쓰려면 기록에서 '라이브러리에 저장'을 누른 뒤 작품의 ${stepLabel('style')}에서 '라이브러리에서 고르기'로 적용하세요.</p>` : ''}
    ${revEstHtml(est)}</section>
    ${list.length ? `<section class="card tight"><div class="between"><h3>기록</h3><span class="small">최근 ${S.rev.style_keep || 20}개까지 남겨요</span></div><ul class="version-list">${rows}</ul></section>` : ''}`;
}

/** 문체를 넣고 쓴 판이 지금 프로필과 다른 프로필로 썼으면 그 이름 ('2번 프로필' · '지운 프로필'), 아니면 빈 글. */
function revStyleTag(t) {
  if (!t || !t.style_old) return '';
  return t.style_gone || !t.style_id ? '지운 프로필' : `${t.style_id}번 프로필`;
}

/** 판의 문체 한 줄: '문체 넣음 · 2번' (지금 프로필과 다르면 '· 2번 프로필' 칩으로). */
const revTakeStyle = (t) => (t.style ? `문체 넣음${t.style_id ? ` · ${t.style_id}번` : ''}` : '문체 없이');

/* ----- AI 모델: 이 실험의 AI 호출만 바꾼다 (서버 revlab.ai_choice · set_ai, 고르지 않으면 설정 화면의 단계 칸) ----- */

const REV_AI_PROVIDERS = ['gemini', 'claude', 'claude-api', 'local'];  // revlab.AI_PROVIDERS 와 같은 차례

/** 쓸 AI 한 줄: 'claude-opus-5-5 · Claude 구독'. 모델 칸이 비면 그 백엔드의 기본 모델(default), 그것도 없으면 백엔드 이름. */
function revAiText(u) {
  if (!u || !u.provider) return '';
  if (u.provider === 'mock') return 'mock';
  return writerLabel(`${u.provider}:${u.model || u.default || 'default'}`);
}

/** 화 번호 목록 → '1~3 · 5화' (화 범위는 'a~b화'). */
function revEpRange(nums) {
  const xs = [...new Set(nums)].sort((a, b) => a - b);
  const out = [];
  for (let i = 0; i < xs.length; i++) {
    let j = i;
    while (j + 1 < xs.length && xs[j + 1] === xs[j] + 1) j++;
    out.push(i === j ? `${xs[i]}` : `${xs[i]}~${xs[j]}`);
    i = j;
  }
  return out.length ? `${out.join(' · ')}화` : '';
}

/** 이미 만든 결과의 모델. plan: [{ what, model }] (역설계는 같은 모델끼리 화를 묶는다).
    write: 백엔드 · 모델마다 [{ provider, model, eps, n, style, picks: revTakePicks 모양 }] (쓴 차례). 모델을 모르면 뺀다. */
function revAiMade(items, styleModel) {
  const byModel = new Map();
  for (const e of items || []) if (e.sheet && e.model) byModel.set(e.model, [...(byModel.get(e.model) || []), e.number]);
  const plan = [...byModel].map(([model, nums]) => ({ what: `${revEpRange(nums)} 역설계`, model }));
  if (styleModel) plan.push({ what: '문체 프로필', model: styleModel });
  const byTake = new Map();
  for (const e of items || []) {
    for (const t of e.takes || []) {
      if (!t.model) continue;
      const k = `${t.provider || ''}:${t.model}`;
      const x = byTake.get(k) || { provider: t.provider || '', model: t.model, eps: [], n: 0, style: 0, takes: [] };
      if (!x.eps.includes(e.number)) x.eps.push(e.number);
      x.n += 1;
      x.style += t.style ? 1 : 0;
      x.takes.push(t);
      byTake.set(k, x);
    }
  }
  const write = [...byTake.values()].map(({ takes, ...x }) => ({ ...x, picks: revTakePicks({ takes }) }));
  return { plan, write };
}

const revAiStage = (stage) => ((S.revLab && S.revLab.ai && S.revLab.ai.stages) || []).find((x) => x.stage === stage) || null;

/** 실행 칸 아래 한 줄: 이 작업이 쓸 AI와 바꾸러 가는 링크. */
function revAiLine(stage) {
  const x = revAiStage(stage);
  if (!x) return '';
  return `<div class="small rev-ai-line">쓸 AI: ${esc(revAiText(x.use))}${x.use.source === 'lab' || x.use.source === 'preset' ? ' · 이 실험만' : ''} · <a href="#/revlab/${S.revLab.id}/ai">바꾸기</a></div>`;
}

function revAICard() {
  const L = S.revLab;
  if (!S.models) loadModelList().then(() => { if (S.revPane === 'ai') render(); });  // 모델 칸 추천 목록 (settings.js)
  const made = revAiMade(L.items, L.style_model);
  const mock = L.ai.stages.some((x) => x.use.source === 'mock');
  const rows = L.ai.stages.map((x) => {
    const id = `rev-ai-${x.stage}`;
    const gone = x.use.source === 'gone';
    const val = x.preset ? (gone ? 'gone' : `preset:${x.preset}`) : x.provider ? 'direct' : '';
    const opts = `<option value=""${val === '' ? ' selected' : ''}>설정을 따름 · 지금 ${esc(revAiText(x.follow))}</option>
      ${gone ? '<option value="gone" selected>지워진 프리셋 (설정을 따름)</option>' : ''}
      ${L.ai.presets.length ? `<optgroup label="프리셋">${L.ai.presets.map((p) => `<option value="preset:${esc(p.id)}"${val === `preset:${p.id}` ? ' selected' : ''}>${esc(p.name)}</option>`).join('')}</optgroup>` : ''}
      <option value="direct"${val === 'direct' ? ' selected' : ''}>직접 고르기</option>`;
    const now = x.use.model || x.use.default;
    const list = x.stage === 'plan' ? made.plan.map((m) => `<li>${esc(m.what)} · ${esc(m.model)}${now && x.use.provider !== 'mock' && m.model !== now ? ' <span class="chip warn" title="지금 고른 모델과 다른 모델로 만든 결과예요">다름</span>' : ''}</li>`).join('') : '';
    const table = x.stage === 'write' && made.write.length ? `<div class="small">만든 결과 · 모델마다</div><div class="rev-scroll"><table class="sw-table rev-made"><thead><tr><th class="rev-l">AI 모델</th><th>화</th><th>판</th><th>가려 읽기</th><th>첫 읽기만</th></tr></thead><tbody>
      ${made.write.map((m) => `<tr><td class="rev-l">${revTakeWho(m)}${m.provider ? '' : ' <span class="small" title="백엔드를 적기 전에 쓴 판이에요">· 백엔드 모름</span>'}${x.use.provider !== 'mock' && m.model === now && (!m.provider || m.provider === x.use.provider) ? ' <span class="chip">지금 고름</span>' : ''}</td>
        <td>${revEpRange(m.eps)}</td><td>${m.n}판${m.style ? ` <span class="small">(문체 ${m.style})</span>` : ''}</td>
        <td>원문 ${m.picks.original} · 판 ${m.picks.rewrite}${m.picks.wait ? ` <span class="chip warn">${m.picks.wait} 남음</span>` : ''}</td>
        <td>${m.picks.first.original + m.picks.first.rewrite ? `원문 ${m.picks.first.original} · 판 ${m.picks.first.rewrite}` : '-'}</td></tr>`).join('')}</tbody></table></div>
      <p class="small">'첫 읽기만'은 그 화의 원문을 처음 본 가려 읽기만 센 값이에요. 모델을 견줄 때는 이 칸이 덜 치우쳐요.</p>` : '';
    const direct = val === 'direct' ? `<div class="seg" role="group" aria-label="${esc(x.label)} 백엔드">${REV_AI_PROVIDERS.map((k) => `<button type="button" aria-pressed="${x.provider === k}" data-action="revAiProv" data-arg="${x.stage}:${k}">${esc(WRITER_BACKEND[k])}</button>`).join('')}</div>
        <div class="field"><label for="${id}-model">모델 <span class="hint">비우면 그 백엔드의 기본 모델${x.use.default ? ` (${esc(x.use.default)})` : ''}</span></label>
          <input id="${id}-model" type="text" list="model-options" value="${esc(x.model)}" data-rev-ai-model="${x.stage}" placeholder="${esc(x.use.default || '기본 모델')}"></div>
        ${x.provider === 'claude' ? '<div class="note info small">Claude 구독은 Canon 서버에 설치한 Claude Code로 불러요. 비용 추정은 API 가격표로 계산해요.</div>' : ''}` : '';
    return `<div class="rev-ai-row"><div><h3>${esc(x.label)}</h3><p class="small">${x.stage === 'plan' ? '계획 단계 일이에요. 역설계는 화마다 한 번, 이야기 줄기와 문체 프로필은 실험에 한 번 불러요.' : '본문 단계 일이에요. 같은 화를 다른 모델로 써 보려면 여기서 바꾸고 새 판을 써요. 앞 모델의 판과 가려 읽기 결과는 남아요.'}</p></div>
      <div class="rev-ai-pick"><div class="field"><label for="${id}">쓸 AI</label><select id="${id}" data-rev-ai="${x.stage}">${opts}</select></div>
        ${direct}
        <div class="small">지금 쓰는 AI: ${esc(revAiText(x.use))}</div>
        ${list ? `<div class="small">만든 결과</div><ul class="rev-ul small">${list}</ul>` : ''}${table}</div></div>`;
  }).join('');
  return `<section class="card"><h2>AI 모델 <span class="small">이 실험의 AI 호출만 바꿔요</span></h2>
    <p class="small">실험은 작품 밖이라 작품의 AI 프리셋을 쓰지 않아요. 고르지 않으면 설정 화면의 단계 칸을 따라요. 바꾸면 다음 작업부터 쓰고, 이미 만든 결과는 그대로 둬요.</p>
    ${mock ? '<div class="note info small">설정의 AI가 mock이라 지금은 모든 작업이 mock으로 돌아요. 여기서 고른 값은 mock을 끄면 써요.</div>' : ''}
    ${rows}${modelDatalist()}</section>`;
}

/** AI 고르기를 서버에 저장하고 실험을 다시 받는다. 비용 추정은 모델이 바뀌었으니 새로 잰다. */
async function revAiSave(stage, body) {
  const id = S.revLab.id;
  try {
    S.revLab = await api('PUT', `/revlab/${id}/ai`, { stage, ...body });
    S.revEsts = {};
    const x = revAiStage(stage);
    toast(`${x ? x.label : ''} AI를 ${revAiText(x && x.use)}${josa(revAiText(x && x.use), '으로', '로')} 바꿨어요.`);
  } catch (e) {
    showError(e);
  }
  render();
}

function revLinesCard() {
  const L = S.revLab;
  if (!L.lines_at) return `<section class="card empty"><h2>이야기 줄기</h2><p>${L.items.length < 2 ? '화가 둘 넘게 있어야 줄기를 찾아요.' : '모든 화를 역설계하면 메인 줄기와 서브 줄기를 찾아요.'}</p></section>`;
  const span = (x) => (x.branch_ep ? `${x.branch_ep}${x.join_ep ? `~${x.join_ep}` : '~'}화` : '화 없음');
  const on = (id) => L.items.filter((e) => e.plot && (e.plot.storyline === id || e.plot.threads.includes(id))).map((e) => `${e.number}${e.plot.storyline === id ? '' : '(끼어듦)'}`);
  return `<section class="card"><h2>이야기 줄기 <span class="small">${esc(fmtDateTime(L.lines_at))}</span></h2>
    <div class="small"><strong>메인</strong> — ${esc(L.main || '정하지 않음')}</div>
    ${L.lines.length ? `<ul class="rev-ul small">${L.lines.map((x) => `<li><strong>${esc(x.title || x.id)}</strong> · ${esc(x.kind)} · ${span(x)}${x.focus.length ? ` · ${esc(x.focus.join(', '))}` : ''}
      ${x.goal ? `<br>${esc(x.goal)}` : ''}${on(x.id).length ? `<br>화: ${on(x.id).join(', ')}` : ''}${x.rejoin ? `<br>합류하며 남긴 것: ${esc(x.rejoin)}` : ''}</li>`).join('')}</ul>` : '<div class="small">메인 밖 줄기는 찾지 못했어요.</div>'}</section>`;
}

/** 지표 모아 보기: 화마다 원문과 되돌려 쓴 판의 지표. 가려 읽기 전인 판은 서버가 빼서 보낸다. */
/** 구조 · 호흡 (GET /revlab/<번호>/pace, revlab.pace). 칸을 열 때와 실험을 다시 받을 때 받는다. */
async function revPaceLoad() {
  const id = S.revLab && S.revLab.id;
  if (!id || S.revLab.error) return;
  S.revPace = await api('GET', `/revlab/${id}/pace`).then((d) => ({ id, ...d })).catch((e) => ({ id, error: e.message }));
}

const REV_PACE_H = 5;  // 긴장도 최고값 (막대 높이의 기준)
const revPaceTone = (t) => (t >= 4 ? 'high' : t >= 3 ? 'mid' : 'low');

/** 화 안의 긴장 흐름: 큐마다 글자 수만큼 넓은 계단. [{x, w, t}] (x · w 는 0~1). 순수 함수 (tests/test_revlab.py). */
function revPaceSteps(tension, weights) {
  const total = weights.reduce((a, b) => a + b, 0) || 1;
  let x = 0;
  return tension.map((t, i) => {
    const step = { x: x / total, w: weights[i] / total, t };
    x += weights[i];
    return step;
  });
}

function revPaceSpark(r) {
  const W = 96, H = 22;
  const rects = revPaceSteps(r.tension, r.weights).map((c) => {
    const h = Math.max(2, (c.t / REV_PACE_H) * H);
    return `<rect class="rev-pace-${revPaceTone(c.t)}" x="${(c.x * W).toFixed(1)}" y="${(H - h).toFixed(1)}" width="${Math.max(c.w * W - 0.6, 0.6).toFixed(1)}" height="${h.toFixed(1)}"></rect>`;
  }).join('');
  return `<svg class="rev-spark" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="큐 긴장 ${r.tension.join(' · ')}">${rects}</svg>`;
}

/** 화를 따라가는 띠 그래프: 막대는 최고 긴장, 점은 평균 긴장, 막대 위 표시는 끝맺음. 막대를 누르면 그 화로 간다. */
function revPaceStrip(rows) {
  const L = S.revLab;
  const col = 16, H = 90, top = 14;
  const mark = { half: '▲', deceptive: '◆' };
  const cols = rows.map((r, i) => {
    const x = i * col;
    if (!r.parsed) return `<g><title>${r.number}화 · 역설계 전</title><rect class="rev-pace-none" x="${x + 3}" y="${top + H - 4}" width="${col - 6}" height="4"></rect></g>`;
    const h = (r.peak / REV_PACE_H) * H;
    const avg = top + H - (r.avg / REV_PACE_H) * H;
    const tip = `${r.number}화${r.title ? ` ${r.title}` : ''} · 최고 ${r.peak} · 평균 ${r.avg} · 끝 ${r.end} · ${cueLabel('cadences', r.cadence).label} · ${r.chars.toLocaleString()}자`;
    return `<a href="#/revlab/${L.id}/${r.number}"><title>${esc(tip)}</title>
      <rect class="rev-pace-${revPaceTone(r.peak)}" x="${x + 3}" y="${(top + H - h).toFixed(1)}" width="${col - 6}" height="${h.toFixed(1)}" rx="2"></rect>
      <circle class="rev-pace-avg" cx="${x + col / 2}" cy="${avg.toFixed(1)}" r="2.2"></circle>
      ${mark[r.cadence] ? `<text class="rev-pace-mark" x="${x + col / 2}" y="${(top + H - h - 3).toFixed(1)}" text-anchor="middle">${mark[r.cadence]}</text>` : ''}</a>`;
  }).join('');
  const every = rows.length > 60 ? 10 : 5;
  const ticks = rows.map((r, i) => (i === 0 || r.number % every === 0 ? `<text class="rev-pace-tick" x="${i * col + col / 2}" y="${top + H + 14}" text-anchor="middle">${r.number}</text>` : '')).join('');
  const w = Math.max(rows.length * col, 1);
  return `<div class="rev-scroll"><svg class="rev-pace-strip" viewBox="0 0 ${w} ${top + H + 20}" width="${w}" height="${top + H + 20}" role="img" aria-label="화별 최고 긴장과 평균 긴장">${cols}${ticks}</svg></div>`;
}

function revPaceCard() {
  const D = S.revPace;
  if (!D || D.id !== S.revLab.id) return '<section class="card"><p class="small">불러오는 중이에요.</p></section>';
  if (D.error) return `<section class="card"><p class="err">${esc(D.error)}</p></section>`;
  const m = D.summary;
  if (!m) return '<section class="card empty"><h2>구조 · 호흡</h2><p>화를 역설계하면 화마다 긴장 흐름 · 끝맺음 · 분량을 이어 보여 드려요. AI를 따로 부르지 않아요.</p></section>';
  const pct = (x) => `${Math.round(x * 100)}%`;
  const cad = Object.entries(m.cadence).map(([k, n]) => `${esc(cueLabel('cadences', k).label)} ${n}`).join(' · ');
  const list = (xs) => (xs.length > 12 ? `${xs.slice(0, 12).join(', ')} 외 ${xs.length - 12}개` : xs.join(', '));
  const facts = [
    ['역설계한 화', `${m.parsed}화${m.parsed < D.rows.length ? ` (전체 ${D.rows.length}화)` : ''}`],
    ['끝맺음', cad],
    ['끝 긴장 4 이상', `${m.end_high}화`],
    ['최고 긴장', `화의 평균 ${pct(m.peak_at)} 지점`],
    [`긴장 ${REV_PACE_H}인 화`, m.tops.length ? `${m.tops.length}화${m.top_gap ? ` · 평균 ${m.top_gap}화마다` : ''}` : '없음'],
    ['숨 고르기 화', m.rest.length ? `${m.rest.length}화 (최고 긴장 2 이하): ${list(m.rest)}화` : '없음 (최고 긴장 2 이하인 화)'],
    ['분량', `평균 ${m.chars_mean.toLocaleString()}자 · 변동 ${pct(m.chars_cv)}`],
  ].map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');
  const rows = D.rows.map((r) => (r.parsed
    ? `<tr><td class="rev-l"><a href="#/revlab/${S.revLab.id}/${r.number}">${r.number}화</a></td><td class="rev-l">${esc(r.title)}</td><td>${revPaceSpark(r)}</td>
        <td>${r.avg}</td><td>${r.peak} <span class="small">(${pct(r.peak_at)})</span></td><td>${r.end}</td><td>${esc(cueLabel('cadences', r.cadence).label)}</td>
        <td>${pct(r.d_share)}</td><td>${pct(r.fast_share)}</td><td>${pct(r.dialogue)}</td><td>${r.sentence_len}</td><td>${r.chars.toLocaleString()}</td></tr>`
    : `<tr class="rev-pace-off"><td class="rev-l"><a href="#/revlab/${S.revLab.id}/${r.number}">${r.number}화</a></td><td class="rev-l">${esc(r.title)}</td><td colspan="9" class="rev-l small">역설계 전</td><td>${r.chars.toLocaleString()}</td></tr>`)).join('');
  return `<section class="card"><div class="between"><h2>구조 · 호흡</h2><span class="small">AI를 부르지 않고 큐 시트와 원문으로 계산해요</span></div>
    ${revPaceStrip(D.rows)}
    <p class="small">막대는 화의 최고 긴장, 점은 평균 긴장이에요. ▲ 반종지(가장 높은 곳에서 끊음) · ◆ 기만 종지(뒤집으며 끝냄). 긴장도는 AI가 화마다 그 화 안에서 매긴 값이라, 다른 화의 같은 숫자가 같은 세기라는 뜻은 아니에요. 대사 비율 · 문장 길이 · 분량은 원문에서 잰 값이에요.</p>
    <dl class="rev-kv">${facts}</dl></section>
    <section class="card"><h3>화별 호흡</h3><div class="rev-scroll"><table class="sw-table rev-pace-table">
      <thead><tr><th class="rev-l">화</th><th class="rev-l">제목</th><th>큐 긴장 흐름</th><th>평균</th><th>최고 (자리)</th><th>끝</th><th>끝맺음</th><th>D 큐</th><th>빠른 템포</th><th>대사</th><th>문장 길이</th><th>분량</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
      <p class="small">D 큐 · 빠른 템포는 글자 수 비율, 문장 길이는 문장 하나의 평균 글자 수예요.</p></section>`;
}

function revMetricsAll() {
  const L = S.revLab;
  const eps = L.items.filter((e) => (e.scores || []).length > 1);
  if (!eps.length) return '<section class="card empty"><h2>지표 모아 보기</h2><p>되돌려 쓰고 가려 읽기를 마친 판이 생기면 원문과 판마다의 지표를 나란히 모아 보여 드려요.</p></section>';
  const body = eps.map((e) => {
    const m = revMetricRows(e.scores);
    const c = revTakePicks(e);
    const pick = `${e.takes.length}판 · 가려 읽기 원문 ${c.original} · 판 ${c.rewrite}${c.wait ? ` · ${c.wait} 남음` : ''}`;
    return `<tr class="rev-mx-ep"><th colspan="${m.heads.length + 1}"><button type="button" class="btn small ghost" data-action="revGo" data-arg="${e.number}|write">${e.number}화${revEpTitle(e) ? ` ${esc(revEpTitle(e))}` : ''}</button> <span class="small">${pick}</span></th></tr>
      <tr><td></td>${e.scores.map(revScoreHead(e)).join('')}</tr>
      ${m.rows.map((r) => `<tr><td>${esc(r.label)}</td>${r.cells.map((c) => `<td${c.far ? ' class="rev-far"' : ''}>${esc(c.text)}</td>`).join('')}</tr>`).join('')}`;
  }).join('');
  return `<section class="card"><div class="between"><h2>지표 모아 보기</h2><span class="small">원문과 ${Math.round(REV_FAR * 100)}% 넘게 다른 값은 굵게 보여요</span></div>
    <div class="rev-scroll"><table class="sw-table rev-mx">${body}</table></div></section>`;
}

function revEpisode() {
  const e = revItem(S.revEp);
  if (!e) return '';
  const L = S.revLab;
  const i = L.items.indexOf(e);
  const prev = L.items[i - 1];
  const next = L.items[i + 1];
  const nav = `<div class="row">${prev ? `<a class="btn small ghost" href="#/revlab/${L.id}/${prev.number}">‹ ${prev.number}화</a>` : ''}${next ? `<a class="btn small ghost" href="#/revlab/${L.id}/${next.number}">${next.number}화 ›</a>` : ''}</div>`;
  const short = e.chars < S.rev.min_chars;
  const chip = short ? '<span class="chip">짧아 풀지 않음</span>'
    : !e.sheet ? '<span class="chip">역설계 전</span>'
      : (e.blind_texts || []).length ? '<span class="chip warn">가려 읽기 남음</span>'
        : (e.takes || []).length ? `<span class="chip ok">되돌려 씀 ${e.takes.length}판</span>` : '<span class="chip">역설계 완료</span>';
  const facts = [`${e.chars.toLocaleString()}자`];
  if (e.sheet) {
    facts.push(`큐 ${e.sheet.cues.length}`);
    if (e.storyboard) facts.push(`장면 ${e.storyboard.scenes.length}`);
    if (e.plot) facts.push(`사건 ${e.plot.events.length}`);
  }
  const src = e.source ? `<a class="chip" href="#/refs/${enc(e.source.ref)}/${e.source.order}" title="이 화가 온 레퍼런스 원고">원고${(L.ref_names || {})[e.source.ref] ? ` 《${esc(L.ref_names[e.source.ref])}》` : ''} ${esc(e.source.label ? (/^\d+$/.test(e.source.label) ? `${e.source.label}화` : e.source.label) : `${e.source.order}번째`)}</a>`
    + ({ changed: ' <span class="chip warn" title="원고 경계를 고쳐 그 화 글이 넣을 때와 달라요">원고가 바뀌었어요</span>', gone: ' <span class="chip warn">원고에 없어요</span>' }[e.source_state] || '') : '';
  const head = `<div class="between rev-ep-head"><div class="row"><h2>${e.number}화${revEpTitle(e) ? ` ${esc(revEpTitle(e))}` : ''}</h2>${chip}${src}<span class="small">${facts.join(' · ')}</span></div>${nav}</div>`;
  if (!e.sheet) {
    const go = short ? `${S.rev.min_chars}자보다 짧아 역설계하지 않아요.` : jobFor('rev_parse', L.id, REV_JOBS) ? '역설계하는 중이에요. 끝나면 이 화가 바로 열려요.' : '역설계 전이에요. 풀 화는 개요에서 고르고 비용을 봐요.';
    return `${head}<div class="note plain between"><span>${go}</span>${short ? '' : `<a class="btn small" href="#/revlab/${L.id}">개요로</a>`}</div><section class="card"><h3>원문</h3><div class="cue-text rev-raw">${esc(e.text)}</div></section>`;
  }
  cueBind(revCueKey(e.number), e.sheet);
  const tab = REV_TABS.some(([k]) => k === S.revTab) ? S.revTab : 'text';
  const badge = { write: (e.blind_texts || []).length ? '<span class="chip warn">가려 읽기</span>' : (e.takes || []).length ? `<span class="chip ok">${e.takes.length}판</span>` : '<span class="chip">아직</span>' };
  const tabs = `<div class="tabs" role="tablist" aria-label="${e.number}화 보기">${REV_TABS.map(([k, label]) => `<button type="button" role="tab" id="rev-tab-${k}" aria-controls="rev-panel" aria-selected="${k === tab}"${k === tab ? '' : ' tabindex="-1"'} data-action="revTab" data-arg="${k}">${label}${badge[k] ? ` ${badge[k]}` : ''}</button>`).join('')}</div>`;
  const body = tab === 'plot' ? `<div class="rev-two">${revPlotCard(e)}${revBoardCard(e)}</div>` : tab === 'write' ? revWriteTab(e) : revTextTab(e);
  return `${head}${tabs}<div role="tabpanel" id="rev-panel" aria-labelledby="rev-tab-${tab}" class="rev-panel">${body}</div>`;
}

/** 원문 · 큐 탭: 원문을 큐 경계로 나눈 칸 + 옆에 진행 막대와 큐 목록. */
function revTextTab(e) {
  const orig = (e.scores || []).find((s) => s.condition === 'original');
  const notes = [];
  if (e.missing.length) notes.push(`${e.missing.join(', ')}번 큐는 시작 문장을 원문에서 못 찾았어요. 앞 큐에 붙여 쟀어요.`);
  if (e.dropped.length) notes.push(`원문에 없어 뺀 핵심 대사: ${e.dropped.map((x) => `«${esc(x)}»`).join(' · ')}`);
  if (orig && orig.tempo_order === false) notes.push('빠른 큐의 문장이 느린 큐보다 길어요. 템포 표시가 원문과 어긋나요.');
  return `${notes.map((x) => `<div class="note warn small">${x}</div>`).join('')}
    <div class="rev-cols"><section class="card rev-src" aria-label="${e.number}화 원문"><div class="between"><h3>원문</h3><span class="small">위쪽 띠를 누르면 그 큐를 열어요</span></div>${revText(e)}</section>
    <aside class="rev-side"><section class="card tight">${cueScore(cueEd().draft, false)}</section>${revCueCard(e, orig)}</aside></div>`;
}

/** 원문을 큐 경계로 나눠 그린다. 고른 큐(S.revSel)는 밝힌다. 경계가 큐 수와 맞지 않으면(작가가 큐를 더하거나 뺐다) 원문만. */
function revText(e) {
  if (!e.bounds_ok) return `<div class="note warn small">큐 수가 바뀌어 원문 경계를 지웠어요. 다시 역설계하면 새로 재요.</div><div class="cue-text rev-raw">${esc(e.text)}</div>`;
  return `<div class="rev-text">${revSegments(e.text, e.bounds).map((s) => {
    const c = s.cue ? e.sheet.cues[s.cue - 1] : null;
    const body = `<div class="cue-text">${esc(e.text.slice(s.start, s.end).replace(/^\n+|\n+$/g, ''))}</div>`;
    if (!c) return `<div class="rev-seg free">${body}</div>`;
    const on = S.revSel === s.cue;
    return `<div class="rev-seg${on ? ' sel' : ''}" id="rev-cue-${s.cue}"><button type="button" class="rev-gut fn-${esc(c.function)}" data-action="revCueGo" data-arg="${s.cue}" aria-pressed="${on}" aria-label="${s.cue}번 큐 ${on ? '닫기' : '열기'}">
      <span class="rev-fn ${esc(c.function)}">${esc(c.function)}</span><span class="small">${s.cue}<span class="rev-gut-t"> · 긴장 ${c.tension}</span></span></button>${body}</div>`;
  }).join('')}</div>`;
}

function revPlotCard(e) {
  const p = e.plot;
  const kv = (k, v) => (v ? `<dt>${k}</dt><dd>${esc(v)}</dd>` : '');
  return `<section class="card"><h3>화 플롯${p.title ? ` · ${esc(p.title)}` : ''}</h3>
    <p>${esc(p.summary)}</p>
    <ol class="rev-ul">${p.events.map((x) => `<li>${esc(x)}</li>`).join('')}</ol>
    <dl class="rev-kv">${kv('등장', p.characters.join(', '))}${kv('감정 변화', p.emotional_shift)}${kv('엔딩 훅', p.ending_hook)}${kv('여는 장면', p.opening)}${kv('시점', p.time)}${kv('줄기', e.threads.join(', '))}</dl>
    <div class="small">${esc(e.model)} · ${esc(fmtDateTime(e.made_at))}</div></section>`;
}

function revBoardCard(e) {
  const b = e.storyboard;
  if (!b) return '';
  const t = b.time;
  const time = [t.after > 0 ? `직전 화 ${t.after}일 뒤` : t.after < 0 ? '메인 시간 밖' : '', t.part && `${t.part} 시작`, t.days > 1 ? `${t.days}일에 걸침` : '', t.end_part && `${t.end_part} 끝`].filter(Boolean).join(' · ');
  return `<section class="card"><h3>스토리보드 <span class="small">장면 ${b.scenes.length}개</span></h3>
    ${time ? `<div class="small">시간: ${esc(time)}</div>` : ''}
    ${b.handover.length ? `<div class="small">직전 화에서 이어받은 것: ${b.handover.map((h) => `${h.kind ? `[${esc(h.kind)}] ` : ''}${esc(h.text)}`).join(' · ')}</div>` : ''}
    <ol class="rev-ul">${b.scenes.map((s) => `<li><strong>${esc([s.place, s.spot].filter(Boolean).join(' · ') || '장소 모름')}</strong>${s.time ? ` · ${esc(s.time)}` : ''}${s.present.length ? ` · ${esc(s.present.join(', '))}` : ''}
      ${s.events.length ? ` · 사건 ${s.events.join(', ')}` : ''}<br><span class="small">${esc([s.goal && `목표: ${s.goal}`, s.turn && `전환: ${s.turn}`, s.end_state && `끝: ${s.end_state}`].filter(Boolean).join(' / '))}</span></li>`).join('')}</ol></section>`;
}

/** 큐 목록: 한 줄에 큐 하나, 고른 큐만 펼쳐 템포 · 편성 · 핵심 대사 · 끝 상태 · 원문에서 잰 값. 아래에 큐 시트 고치기. */
function revCueCard(e, orig) {
  const rows = orig ? orig.rows : [];
  const scenes = (e.storyboard && e.storyboard.scenes) || [];
  const list = e.sheet.cues.map((c, i) => {
    const k = i + 1;
    const r = rows[i];
    const miss = e.missing.includes(k);
    const on = S.revSel === k;
    const sc = c.scene && scenes[c.scene - 1];
    const meta = `${esc(cueLabel('tempos', c.tempo).label)} · ${esc(cueLabel('voices', c.voice).label)} · ${(c.length || 0).toLocaleString()}자`;
    const more = on ? `<div class="rev-cue-more"><dl class="rev-kv">
        <dt>긴장</dt><dd>${c.tension} / 5</dd>
        ${sc ? `<dt>장면</dt><dd>${c.scene} · ${esc([sc.place, sc.spot].filter(Boolean).join(' · ') || '장소 모름')}${sc.events.length ? ` · 사건 ${sc.events.join(', ')}` : ''}</dd>` : ''}
        ${c.lines.length ? `<dt>핵심 대사</dt><dd>${c.lines.map((x) => `${esc(x.speaker || '?')} «${esc(x.text)}»`).join('<br>')}</dd>` : ''}
        ${c.exit ? `<dt>끝 상태</dt><dd>${esc(c.exit)}</dd>` : ''}
        ${r ? `<dt>원문 재기</dt><dd>대사 ${cuePct(r.dialogue_ratio)} · 문장 ${r.sentence_len}${r.voice_ok === false ? ' · <strong class="warn-text">편성과 다름</strong>' : r.voice_ok ? ' · 편성 맞음' : ''}</dd>` : ''}
      </dl></div>` : '';
    return `<li class="rev-cue${on ? ' sel' : ''}"><button type="button" class="rev-cue-btn" data-action="revCueGo" data-arg="${k}" aria-expanded="${on}"${e.bounds_ok && !miss ? '' : ''}>
      <span class="rev-fn ${esc(c.function)}">${esc(c.function)}</span><span class="small">${k}</span><span class="tl">${esc(c.beat || '(일 없음)')}${miss ? ' <span class="chip warn">시작 문장 못 찾음</span>' : ''}</span><span class="meta">${meta}</span></button>${more}</li>`;
  }).join('');
  const { dirty } = cueEd();
  return `<section class="card tight"><div class="between"><h3>큐 ${e.sheet.cues.length}개</h3><span class="small">글자 수는 원문에서 잰 값</span></div>
    <ol class="rev-cues">${list}</ol>
    <details class="cue-edit"${dirty ? ' open' : ''}><summary>큐 시트 고치기${dirty ? ' · 저장하지 않은 고침' : ''}</summary>${cueEditor(false)}</details></section>`;
}

/** 되돌려 쓰기 탭: 가려 읽기 → (고른 뒤) 지표 견주기 · 나란히 읽기 → 다시 쓰기. */
/** 지표 표 머리 칸: 원문, 또는 '판 N' 과 모델 · 문체 두 줄 (시트가 바뀐 판은 칩). */
const revScoreHead = (e) => (sc) => {
  if (sc.condition === 'original') return '<th>원문</th>';
  const t = (e.takes || []).find((x) => x.no === sc.take) || {};
  return `<th class="rev-th2"><span>${esc(sc.label)}</span><span class="small">${esc(t.model || '')}${t.style ? ` · 문체${t.style_id ? ` ${t.style_id}번` : ''}` : ''}</span>${sc.stale ? '<span class="chip">시트 바뀜</span>' : ''}${revStyleTag(t) ? `<span class="chip">${esc(revStyleTag(t))}</span>` : ''}</th>`;
};

const REV_TAKE_PICK = { original: '원문 고름', rewrite: '이 판 고름', skip: '고르지 않음' };

/** 판 목록의 가려 읽기 칸. 원문을 처음 본 가려 읽기면 '첫 읽기', 앞서 원문을 본 뒤면 '원문 본 뒤'. */
function revTakePickHtml(b) {
  if (b.state === 'wait') return '<span class="chip warn">가려 읽기 남음</span>';
  if (b.state !== 'done') return '-';
  const what = b.picked === 'rewrite' ? '<strong>이 판 고름</strong>' : esc(REV_TAKE_PICK[b.picked] || '-');
  return `${what}${b.seen ? ' <span class="small" title="이 화의 원문을 앞선 가려 읽기에서 본 뒤에 고른 결과예요">· 원문 본 뒤</span>' : b.picked !== 'skip' ? ' <span class="chip ok">첫 읽기</span>' : ''}`;
}

// 판을 쓴 뒤 이야기 줄기가 생기거나 바뀜 (revlab.lines_note): [칩, 설명]
const REV_LINES_NOTE = { before: ['줄기 전', '이야기 줄기를 만들기 전에 썼어요'], changed: ['줄기 바뀜', '쓴 뒤 이야기 줄기를 다시 만들었어요'] };
const revLinesChip = (t) => (t.lines ? ` <span class="chip" title="${REV_LINES_NOTE[t.lines][1]}">${REV_LINES_NOTE[t.lines][0]}</span>` : '');

// ---------- 가려 읽기: 한 번에 한 쪽씩 ----------
// 두 쪽을 나란히 두면 읽지 않고 훑어 견주게 되므로 탭으로 한 쪽만 보인다. 끝까지 내린 쪽은 '읽음'으로 세고,
// 다른 쪽을 끝까지 읽기 전에 고르면 한 번 묻는다 (막지는 않는다). 판마다 따로 기억하고 저장하지 않는다.

const revBlindKey = (e) => `${S.revLab.id}:${e.number}:${e.blind_no}`;

function revBlindState(e) {
  const k = revBlindKey(e);
  return S.revBlindRead[k] || (S.revBlindRead[k] = { show: 1, seen: [], top: {} });
}

/** 끝까지 읽지 않은 쪽 번호 (1~count). 고르려는 쪽 k 는 뺀다. */
function revBlindUnread(count, seen, k) {
  const out = [];
  for (let i = 1; i <= count; i++) if (i !== k && !seen.includes(i)) out.push(i);
  return out;
}

/** 쪽 탭과 고른 쪽 글 하나, 그 쪽을 고르는 버튼. */
function revBlindDeck(e) {
  const st = revBlindState(e);
  const n = e.blind_texts.length;
  const show = Math.min(st.show, n);
  const tabs = e.blind_texts.map((_, i) => `<button type="button" role="tab" id="rev-blind-tab-${i + 1}" aria-selected="${i + 1 === show}" aria-controls="rev-blind-panel"
      data-action="revBlindShow" data-arg="${i + 1}">${i + 1}번${st.seen.includes(i + 1) ? ' · 읽음' : ''}</button>`).join('');
  const left = revBlindUnread(n, st.seen, 0);
  return `<div class="between"><div class="tabs" role="tablist" aria-label="가려 읽기">${tabs}</div>
      <span class="small">${left.length ? `${left.join(', ')}번을 아직 끝까지 읽지 않았어요` : '모두 읽었어요. 더 읽고 싶은 쪽을 고르세요'}</span></div>
    <div id="rev-blind-panel" role="tabpanel" aria-labelledby="rev-blind-tab-${show}" class="rev-blind-col">
      <div class="cue-text rev-read rev-blind-read" tabindex="0" aria-label="${show}번 글" data-rev-blind="${show}">${esc(e.blind_texts[show - 1])}</div>
      <div><button type="button" class="btn" data-action="revPick" data-arg="${show}">${show}번이 더 읽고 싶어요</button></div></div>`;
}

/** 쪽 글 칸의 스크롤: 읽던 자리를 남기고, 끝까지 내리면 읽음으로 센다. 보이지 않는 칸(높이 0)은 세지 않는다. */
function revBlindTrack(el) {
  const e = S.revLab && revItem(S.revEp);
  if (!e || !e.blind_no || !el.clientHeight) return;
  const st = revBlindState(e);
  const k = Number(el.dataset.revBlind);
  st.top[k] = el.scrollTop;
  if (st.seen.includes(k) || el.scrollTop + el.clientHeight < el.scrollHeight - 24) return;
  st.seen.push(k);
  setTimeout(render);  // 그리는 중(syncRevBlind)에 불릴 수 있어 그리기가 끝난 뒤 다시 그린다
}

/** 다시 그린 뒤 읽던 자리로 돌린다. 내릴 것 없이 짧은 쪽은 바로 읽음으로 센다 (app.js drawApp 이 부른다). */
function syncRevBlind() {
  const el = document.querySelector('#app .rev-blind-read');
  const e = el && S.revLab && revItem(S.revEp);
  if (!e || !e.blind_no) return;
  const top = revBlindState(e).top[Number(el.dataset.revBlind)];
  if (top) el.scrollTop = top;
  revBlindTrack(el);
}

document.addEventListener('scroll', (ev) => {
  if (ev.target.matches && ev.target.matches('.rev-blind-read')) revBlindTrack(ev.target);
}, true);

const revTakeWho = (t) => `${esc(t.model || '모델 모름')}${t.provider && t.provider !== 'mock' ? ` <span class="small">· ${esc(WRITER_BACKEND[t.provider] || t.provider)}</span>` : ''}`;

function revWriteTab(e) {
  const L = S.revLab;
  const takes = e.takes || [];
  const parts = [];
  const wait = takes.find((t) => t.no === e.blind_no);
  const c = revTakePicks(e);
  if (wait) {
    parts.push(`<section class="card"><div class="between"><h3>가려 읽기 · 판 ${wait.no}</h3><span class="small">${c.wait > 1 ? `이 화에 ${c.wait}판 남음 · ` : ''}고르면 어느 쪽인지와 지표를 보여 드려요</span></div>
      <div class="note info">어느 쪽이 원문인지 숨겼어요. 한 쪽씩 끝까지 읽고 더 이어 읽고 싶은 쪽을 고르세요.</div>
      ${c.original + c.rewrite + c.skip ? `<div class="note warn small">이 화의 원문을 앞선 가려 읽기 ${c.original + c.rewrite + c.skip}번에서 이미 봤어요. 이번 결과는 '원문 본 뒤'로 따로 세요.</div>` : ''}
      ${revBlindDeck(e)}
      <div class="row"><button type="button" class="btn ghost" data-action="revPick" data-arg="0">고르지 않고 결과 보기</button></div></section>`);
  }
  const busy = !!revRunning();
  if (takes.length) {
    const rows = [...takes].reverse().map((t) => `<tr${t.blind.state === 'wait' ? ' class="rev-muted"' : ''}>
        <td class="rev-l"><strong>판 ${t.no}</strong>${t.stopped ? ' <span class="chip" title="작업을 멈춘 뒤 도착한 응답이에요. 필요 없으면 지우세요">멈춘 뒤 받은 판</span>' : ''}${t.stale ? ' <span class="chip" title="쓴 뒤 큐 시트가 바뀌었어요">시트 바뀜</span>' : ''}${revLinesChip(t)}</td>
        <td class="rev-l rev-take-who">${revTakeWho(t)} <span class="chip">${revTakeStyle(t)}</span>${revStyleTag(t) ? ` <span class="chip" title="지금 프로필과 다른 프로필로 썼어요">${esc(revStyleTag(t))}</span>` : ''}</td>
        <td>${esc(fmtDateTime(t.at))}</td><td>${t.chars.toLocaleString()}</td><td class="rev-l rev-take-pick">${revTakePickHtml(t.blind)}</td>
        <td class="rev-l"><span class="row rev-take-acts">${t.text ? `<button type="button" class="btn small ghost" data-action="revReadTake" data-arg="${t.no}">읽기</button>` : '<span class="small">가려 읽은 뒤</span>'}
          <button type="button" class="btn small ghost" data-action="revTakeDrop" data-arg="${t.no}" aria-label="판 ${t.no} 지우기"${busy ? ' disabled' : ''}>지우기</button></span></td></tr>`).join('');
    const models = new Set(takes.map((t) => t.model)).size;
    parts.push(`<section class="card"><div class="between"><h3>되돌려 쓴 판 <span class="small">${takes.length} / ${e.limit}판${models > 1 ? ` · 모델 ${models}개` : ''}</span></h3>
        <span class="small">다시 써도 앞 판은 남아요</span></div>
      <div class="rev-scroll"><table class="sw-table rev-takes"><thead><tr><th class="rev-l">판</th><th class="rev-l">AI 모델 · 문체</th><th>쓴 때</th><th>글자</th><th class="rev-l">가려 읽기</th><th><span class="sr-only">동작</span></th></tr></thead>
      <tbody>${rows}</tbody></table></div>
      <p class="small">'첫 읽기'는 이 화의 원문을 처음 본 가려 읽기예요. 그 뒤의 고르기는 원문을 알아볼 수 있어 '원문 본 뒤'로 따로 세요.</p></section>`);
  }
  if ((e.scores || []).length > 1) {
    const m = revMetricRows(e.scores);
    parts.push(`<section class="card"><div class="between"><h3>지표 견주기</h3><span class="small">원문과 ${Math.round(REV_FAR * 100)}% 넘게 다른 값은 굵게 보여요</span></div>
      ${c.wait ? `<div class="note plain small">가려 읽기가 남은 판은 고른 뒤에 표에 들어가요.</div>` : ''}
      <div class="rev-scroll"><table class="sw-table rev-mx rev-mx-wide"><thead><tr><th></th>${e.scores.map(revScoreHead(e)).join('')}</tr></thead>
      <tbody>${m.rows.map((r) => `<tr><td>${esc(r.label)}</td>${r.cells.map((x) => `<td${x.far ? ' class="rev-far"' : ''}>${esc(x.text)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
      <p class="small">핵심 대사는 큐 시트의 대사가 글자 그대로 들어간 수예요. 템포는 원문만 큐 경계로 나눠 재요 (빠른 큐의 문장이 느린 큐보다 짧은지). 문체 거리는 이 화를 뺀 원문으로 만든 기준까지 어미 분포 거리예요. 1.0 이면 원문의 다른 대목만큼 가까워요. 옮김은 원문 · 장치 예시와 공백 빼고 12자 이상 똑같이 이어지는 문장 수예요. 판이 많으면 표를 옆으로 밀어 봐요.</p>
      ${m.notes.map((x) => `<p class="small">${esc(x)}</p>`).join('')}</section>`);
  }
  const shown = takes.filter((t) => t.text);
  if (shown.length) {
    const side = (v) => (v === 'original' ? 'original' : shown.find((t) => t.no === Number(v)) ? Number(v) : null);
    const a = side(S.revRead.a) ?? 'original';
    const b = side(S.revRead.b) ?? shown[shown.length - 1].no;
    const opt = (sel) => `<option value="original"${sel === 'original' ? ' selected' : ''}>원문</option>${shown.map((t) => `<option value="${t.no}"${sel === t.no ? ' selected' : ''}>판 ${t.no} · ${esc(t.model)}${t.style ? ` · ${revTakeStyle(t)}` : ''}</option>`).join('')}`;
    const col = (v) => {
      if (v === 'original') return `<div class="rev-blind-col"><div class="small"><strong>원문</strong> · ${e.chars.toLocaleString()}자</div><div class="cue-text rev-read">${esc(e.text)}</div></div>`;
      const t = shown.find((x) => x.no === v);
      return `<div class="rev-blind-col"><div class="small"><strong>판 ${t.no}</strong> · ${t.text.length.toLocaleString()}자 · ${revTakeWho(t)} · ${esc(fmtDateTime(t.at))}${t.stale ? ' · 쓴 뒤 큐 시트가 바뀌었어요' : ''}${t.lines ? ` · ${REV_LINES_NOTE[t.lines][1]}` : ''}${t.style ? ` · ${revTakeStyle(t)}` : ''}${revStyleTag(t) ? ` (지금은 ${S.revLab.style_id ? `${S.revLab.style_id}번` : '고른 프로필 없음'})` : ''}</div><div class="cue-text rev-read">${esc(t.text)}</div></div>`;
    };
    parts.push(`<section class="card" id="rev-side"><div class="between"><h3>나란히 읽기</h3>
        <span class="row rev-read-picks"><label class="small" for="rev-read-a">왼쪽</label><select id="rev-read-a" data-rev-read="a">${opt(a)}</select>
          <label class="small" for="rev-read-b">오른쪽</label><select id="rev-read-b" data-rev-read="b">${opt(b)}</select></span></div>
      <div class="rev-blind">${col(a)}${col(b)}</div></section>`);
  }
  const style = !!(S.revStyle && L.style);
  const full = takes.length >= e.limit;
  const est = full ? null : revEst('write', [e.number], style);
  const block = revWriteBlock(e.number);
  const parse = jobFor('rev_parse', L.id, REV_JOBS);
  const early = !block && parse && parse.total > (parse.pending || []).length;  // 역설계가 끝나면 이야기 줄기를 만든다
  parts.push(`<section class="card${takes.length ? ' tight' : ''}"><h3>${takes.length ? '새 판 쓰기' : '되돌려 쓰기'}</h3>
    <p class="small">역설계한 플롯 · 스토리보드 · 큐 시트와 인물 · 관계 · 호칭 · 배경만 주고(이 화 원문 문장은 주지 않음) 같은 화를 써요. 앞 화는 원문을 반영한 화로 둬요. 새 판은 목록에 더하고 앞 판은 그대로 두며, 원문과 가려 읽기를 따로 해요.</p>
    ${revAiLine('write')}
    ${cueEd().dirty ? '<div class="note warn small">저장하지 않은 큐 시트 고침이 있어요. 되돌려 쓰기는 저장한 큐 시트로 해요.</div>' : ''}
    ${block ? `<div class="note plain small">${block}</div>` : early ? '<div class="note plain small">역설계가 끝나면 이야기 줄기를 만들어요. 지금 쓰면 줄기 없이 써서 판에 \'줄기 전\'이 붙어요.</div>' : ''}
    ${full ? `<div class="note warn small">이 화에 판이 ${e.limit}개예요. 새로 쓰려면 위 판 목록에서 지울 판을 고르세요.</div>` : ''}
    <div class="row"><label class="check-row small"><input type="checkbox" data-rev-style="1"${style ? ' checked' : ''}${L.style ? '' : ' disabled'}><span>문체 프로필${L.style ? `(${L.style_id}번)` : ''} 넣기${L.style ? '' : (L.style_list || []).length ? ' (문체 프로필을 먼저 고르세요)' : ' (문체 프로필을 먼저 만드세요)'}</span></label>
      <button type="button" class="btn" data-action="revWrite" data-arg="${e.number}"${est && !block && !full ? '' : ' disabled'}>${full ? `판 ${e.next_take} 쓰기` : revCost(`판 ${e.next_take} 쓰기${style ? ' (문체 넣고)' : ''}`, est)}</button></div>
    ${!full && revEstErr('write', [e.number], style) ? `<div class="note err small">비용을 재지 못했어요: ${esc(revEstErr('write', [e.number], style))}</div>` : ''}
    ${revEstHtml(est)}</section>`);
  return parts.join('');
}

document.addEventListener('input', (e) => {
  const d = e.target.dataset || {};
  if (d.revNew) {
    S.revDraft[d.revNew] = e.target.value;
    revNewRefresh();
  }
  if (d.revEp && S.revEpEdit) {
    S.revEpEdit[d.revEp] = e.target.value;
    const count = document.getElementById('rev-epcount');
    if (count && d.revEp === 'text') count.textContent = `· ${e.target.value.length.toLocaleString()}자`;
  }
  if (d.revAdd) {
    S.revAdd = e.target.value;
    revAddRefresh();
  }
});

/** 새 실험 칸의 미리보기 · 글자 수 · 첫 화 번호 · 만들기 버튼만 다시 그린다 (입력 중에는 화면 전체를 그리지 않는다). */
function revNewRefresh() {
  const box = document.getElementById('rev-preview');
  if (box) box.innerHTML = revPreviewHtml();
  const count = document.getElementById('rev-count');
  if (count) count.textContent = S.revDraft.text ? `· ${S.revDraft.text.length.toLocaleString()}자` : '';
  const num = document.getElementById('rev-first');
  if (num) num.placeholder = revGuessFirst(S.revDraft.title, S.revDraft.text);
  const btn = document.querySelector('[data-action="revCreate"]');
  const v = revPreview(S.revDraft.text, S.rev);
  if (btn) btn.disabled = !!v.errs.length || !!v.pending;
}

/** 레퍼런스 원고 목록을 받는다. 이 실험의 화가 온 원고가 있으면 그 원고를 먼저 연다. */
async function revRefLoad() {
  if (S.revRefs && !S.revRefs.error) return;
  S.revRefs = await api('GET', '/refs').catch((e) => ({ error: e.message, refs: [] }));
  const from = (S.revLab && S.revLab.items || []).map((x) => x.source && x.source.ref).filter(Boolean).pop();
  if (from && S.revRefs.refs.some((r) => r.id === from)) await revRefOpen(from);
  else render();
}

/** 원고 하나의 화 목록을 받는다 (GET /refs/<id>). 빈 값이면 고르기를 푼다. */
async function revRefOpen(rid) {
  S.revRefPick = new Set();
  S.revRefBook = rid ? await api('GET', `/refs/${enc(rid)}`).catch((e) => ({ error: e.message, id: rid })) : null;
  render();
}

function revAddRefresh() {
  if (S.revAdd === null) return;
  const box = document.getElementById('rev-apreview');
  if (box) box.innerHTML = revAddPreviewHtml();
  const count = document.getElementById('rev-acount');
  if (count) count.textContent = S.revAdd ? `· ${S.revAdd.length.toLocaleString()}자` : '';
  const v = revAppendPreview(S.revAdd, S.rev, revHave(S.revLab));
  const btn = document.querySelector('[data-action="revAppend"]');
  if (btn) {
    btn.disabled = !!v.errs.length || !!v.pending || !!revRunning();
    btn.textContent = revAddLabel(v);
  }
}

/** 서버가 나눈 값이 오면 보이는 미리보기를 다시 그린다. */
function revSplitDone() {
  if (S.route[0] !== 'revlab') return;
  if (document.getElementById('rev-preview')) revNewRefresh();
  if (document.getElementById('rev-apreview')) revAddRefresh();
}

document.addEventListener('change', (e) => {
  const d = e.target.dataset || {};
  if (d.revStyle !== undefined) { S.revStyle = e.target.checked; render(); return; }
  if (d.revRef) { revRefOpen(e.target.value); return; }
  if (d.revRefPick !== undefined) {
    const o = Number(d.revRefPick);
    if (e.target.checked) S.revRefPick.add(o); else S.revRefPick.delete(o);
    render();
    return;
  }
  if (d.revRead) { S.revRead = { ...S.revRead, [d.revRead]: e.target.value === 'original' ? 'original' : Number(e.target.value) }; render(); return; }
  if (d.revAi) {
    const v = e.target.value;
    const x = revAiStage(d.revAi);
    if (v === 'gone') return;
    if (v === 'direct') revAiSave(d.revAi, { provider: (x && (x.provider || (x.follow.provider !== 'mock' && x.follow.provider))) || 'gemini' });
    else revAiSave(d.revAi, v.startsWith('preset:') ? { preset: v.slice(7) } : {});
    return;
  }
  if (d.revAiModel) {
    const x = revAiStage(d.revAiModel);
    if (x && x.provider) revAiSave(d.revAiModel, { provider: x.provider, model: e.target.value });
    return;
  }
  if (d.revAll !== undefined) {
    const can = S.revLab.items.filter((x) => x.chars >= S.rev.min_chars).map((x) => x.number);
    S.revPick = new Set(e.target.checked ? can : []);
    render();
    return;
  }
  if (d.revPick !== undefined) {
    S.revPick[e.target.checked ? 'add' : 'delete'](Number(d.revPick));
    render();
  }
});

JOB_PAGES.rev_parse = ['rev'];
JOB_PAGES.rev_write = ['rev'];
JOB_PAGES.rev_style = ['rev'];
/** 작업이 끝나면 그 실험을 보고 있을 때 다시 받는다. 고치던 큐 시트는 그 화를 다시 역설계하지 않았으면 남는다 (revFetch). */
function revJobDone(j) {
  if (j.status === 'done' && S.revLab && S.revLab.id === j.ep) revFetch(j.ep).then(render);
}
/** 역설계가 한 화를 끝낼 때마다(작업 done 이 늘 때) 그 실험을 보고 있으면 다시 받아 끝난 화를 바로 연다 (app.js pollJobs 가 부른다). */
async function revJobStep(j, old) {
  if (j.kind !== 'rev_parse' || j.status !== 'running' || !old || old.done === j.done) return;
  if (S.route[0] === 'revlab' && S.revLab && S.revLab.id === j.ep) await revFetch(j.ep);
}
JOB_DONE_MSG.rev_parse = (j) => {
  revJobDone(j);
  const r = j.result || {};
  return `역설계가 끝났어요: ${r.episodes || 0}화 · 큐 ${r.cues || 0}개${r.lines != null ? ` · 줄기 ${r.lines}개` : ''}.`;
};
JOB_DONE_MSG.rev_write = (j) => {
  revJobDone(j);
  const r = j.result || {};
  return `${r.episode || ''}화 판 ${r.take || ''}${r.style ? '(문체 넣음)' : ''}을 썼어요. 가려 읽고 골라 보세요.`;
};
JOB_STOP_NOTE.rev_write = '이미 보낸 AI 호출은 끊을 수 없어요. 응답이 오면 버리지 않고 \'멈춘 뒤 받은 판\'으로 남겨요 (비용은 들어요). 그동안 새 판은 쓸 수 없어요.';
/** 멈춘 되돌려 쓰기의 응답이 왔다. 판으로 남았으면(result) 알리고, 그 실험을 보고 있으면 다시 받는다. */
JOB_LATE.rev_write = async (j) => {
  const r = j.result;
  if (r) toast(`멈춘 ${r.episode}화 되돌려 쓰기의 응답이 와서 판 ${r.take}로 남겼어요. 필요 없으면 판 목록에서 지우세요.`);
  if (!(S.route[0] === 'revlab' && S.revLab && S.revLab.id === j.ep)) return false;
  await revFetch(j.ep);
  return true;
};
JOB_DONE_MSG.rev_style = (j) => {
  revJobDone(j);
  return `${(j.result || {}).id ? `${j.result.id}번 ` : ''}문체 프로필을 지금 프로필로 골랐어요. 되돌려 쓰기에서 문체 프로필 넣기를 고를 수 있어요.`;
};

/** 실험 안에서 옮긴다: 같은 화면이면 다시 그리고, 다른 화 · 칸이면 주소를 바꾼다 (route 가 revLoad 를 부른다). */
function revNav(part) {
  const to = `#/revlab/${S.revLab.id}${part === '' || part == null ? '' : `/${part}`}`;
  if (location.hash === to) render();
  else location.hash = to;
}

Object.assign(actions, {
  async revCreate() {
    await run('실험 만드는 중', async () => {
      const v = await api('POST', '/revlab', { title: S.revDraft.title, text: S.revDraft.text, first: Number(S.revDraft.first) || null });
      S.revDraft = { title: '', text: '', first: '' };
      S.revLab = null;
      location.hash = `#/revlab/${v.id}`;
    });
  },
  revEditToggle() { S.revEdit = !S.revEdit; render(); },
  async revSaveEdit() {
    const title = (document.querySelector('[data-rev-edit="title"]') || {}).value || '';
    const text = (document.querySelector('[data-rev-edit="text"]') || {}).value || '';
    const first = Number((document.querySelector('[data-rev-edit="first"]') || {}).value) || null;
    if (text.trim() && S.revLab.done && !(await askConfirm('글을 바꾸면 다시 나누고 역설계 결과를 모두 지워요. 바꿀까요?', { ok: '바꾸기', danger: true }))) return;
    const id = S.revLab.id;
    await run('저장하는 중', async () => {
      await api('PUT', `/revlab/${id}`, { title, text: text.trim() ? text : null, first });
      S.revLab = null;
      await revLoad(id, null);
      S.revEdit = false;
    });
  },
  async revAddToggle() {
    if (S.revAdd && S.revAdd.trim() && !(await askConfirm('붙여 넣은 글을 버리고 닫을까요?', { ok: '버리기', danger: true }))) return;
    S.revAdd = S.revAdd === null ? '' : null;
    S.revRefPick = new Set();
    if (S.revAdd === null) { S.revRefs = null; S.revRefBook = null; }  // 다시 열면 원고 목록을 새로 받는다
    if (S.revAdd !== null && S.revAddFrom === 'ref') revRefLoad();
    else if (S.revAdd !== null) S.focusTarget = '#rev-atext';
    render();
  },
  revAddFrom(k) {
    S.revAddFrom = k === 'ref' ? 'ref' : 'text';
    if (S.revAddFrom === 'ref') revRefLoad();
    render();
  },
  revRefNext() {
    if (!S.revRefBook || S.revRefBook.error) return;
    revRefNext(S.revRefBook, S.revLab).forEach((o) => S.revRefPick.add(o));
    render();
  },
  revRefRange() {
    const b = S.revRefBook;
    const box = document.getElementById('rev-ref-range');
    if (!b || b.error || !box) return;
    const taken = revRefTaken(b, S.revLab);
    const got = refRange(box.value, b.episodes.filter((e) => revRefUsable(e) && !taken.has(e.order)));
    if (!got.length) { toast('그 범위에 고를 수 있는 화가 없어요'); return; }
    got.forEach((o) => S.revRefPick.add(o));
    render();
  },
  revRefNone() { S.revRefPick = new Set(); render(); },
  /** 고른 원고 화를 마지막 화 뒤에 잇는다 (POST /revlab/<번호>/episodes { ref, eps }). 이은 화는 역설계할 화로 골라 둔다. */
  async revAppendRef() {
    const id = S.revLab.id;
    const b = S.revRefBook;
    await run('이어 붙이는 중', async () => {
      const v = await api('POST', `/revlab/${id}/episodes`, { ref: b.id, eps: [...S.revRefPick].sort((x, y) => x - y) });
      const added = v.added || [];
      S.revLab = null;
      S.revAdd = null;
      S.revRefPick = new Set();
      if (location.hash === `#/revlab/${id}`) await revLoad(id, null);
      else location.hash = `#/revlab/${id}`;
      const span = added.length > 1 ? `${added[0]}~${added[added.length - 1]}화` : `${added[0]}화`;
      toast(`${span}를 이었어요.${v.skipped ? ` 이미 있던 ${v.skipped}화는 뺐어요.` : ''} 역설계할 화로 골라 뒀어요.`);
    });
  },
  /** 붙여 넣은 글을 마지막 화 뒤에 잇고 개요로 간다. 이은 화는 역설계할 화로 골라 둔다 (revFetch 가 새 실험처럼 고른다). */
  async revAppend() {
    const id = S.revLab.id;
    const before = new Set(S.revLab.items.map((e) => e.number));
    await run('이어 붙이는 중', async () => {
      const v = await api('POST', `/revlab/${id}/episodes`, { text: S.revAdd });
      const added = v.items.map((e) => e.number).filter((n) => !before.has(n));
      S.revLab = null;
      S.revAdd = null;
      if (location.hash === `#/revlab/${id}`) await revLoad(id, null);
      else location.hash = `#/revlab/${id}`;
      toast(`${added.length > 1 ? `${added[0]}~${added[added.length - 1]}화` : `${added[0]}화`}를 이었어요. 역설계할 화로 골라 뒀어요.`);
    });
  },
  /** 목차 ⋯ 메뉴의 글 고치기: 그 화를 열고 위에 고치기 칸을 편다. */
  revEpEdit(n) {
    const e = revItem(Number(n));
    if (!e) return;
    S.revEpEdit = { n: e.number, head: e.head, text: e.text };
    S.focusTarget = '#rev-eptext';
    if (!S.revPane && S.revEp === e.number) render(); else revNav(e.number);
  },
  revRunClose(arg) {
    S.revRunHide.add(String(arg).slice(1));  // 'j' 를 붙여 받는다 (숫자만 된 id 를 숫자로 바꾸지 않게)
    render();
    toast('작업은 계속 돌아요. 진행은 위쪽 알림 버튼에서 볼 수 있어요');
  },
  async revEpEditClose() {
    const d = S.revEpEdit;
    const e = d && revItem(d.n);
    if (e && (d.text !== e.text || d.head !== e.head) && !(await askConfirm('고친 글을 버리고 닫을까요?', { ok: '버리기', danger: true }))) return;
    S.revEpEdit = null;
    render();
  },
  async revEpSave() {
    const d = S.revEpEdit;
    const e = revItem(d.n);
    const done = !!(e && (e.sheet || (e.takes || []).length));
    if (done && d.text.trim() !== e.text && !(await askConfirm(`${d.n}화 글을 바꾸면 이 화의 역설계 결과와 되돌려 쓴 판을 지워요. 저장할까요?`, { ok: '저장하기', danger: true }))) return;
    const id = S.revLab.id;
    await run('저장하는 중', async () => {
      await api('PUT', `/revlab/${id}/episodes/${d.n}`, { head: d.head, text: d.text });
      S.revLab = null;
      S.revEpEdit = null;
      await revLoad(id, String(d.n));
      toast(`${d.n}화를 고쳤어요.`);
    });
  },
  /** 목차 ⋯ 메뉴의 지우기: 화를 빼고 뒤 화 번호를 당긴다. 개요로 간다. */
  async revEpDrop(n) {
    const k = Number(n);
    const e = revItem(k);
    if (!e) return;
    const L = S.revLab;
    const later = L.items.length && L.items[L.items.length - 1].number > k;
    const what = ['원문', e.sheet ? '역설계 결과' : '', (e.takes || []).length ? '되돌려 쓴 판' : ''].filter(Boolean).join(' · ');
    if (!(await askConfirm(`${k}화를 지울까요? ${what}${josa(what, '이', '가')} 사라져요.${later ? ' 뒤 화 번호가 하나씩 당겨져요.' : ''}`, { ok: '지우기', danger: true }))) return;
    const id = L.id;
    await run('지우는 중', async () => {
      await api('DELETE', `/revlab/${id}/episodes/${k}`);
      S.revLab = null;
      S.revEpEdit = null;
      if (location.hash === `#/revlab/${id}`) await revLoad(id, null);
      else location.hash = `#/revlab/${id}`;
      toast(`${k}화를 지웠어요.`);
    });
  },
  async revDelete() {
    if (!(await askConfirm(`'${S.revLab.title || `실험 ${S.revLab.id}`}' 실험을 지울까요? 넣은 글과 역설계 결과가 모두 사라져요.`, { ok: '지우기', danger: true }))) return;
    await run('지우는 중', async () => {
      await api('DELETE', `/revlab/${S.revLab.id}`);
      S.revLab = null;
      location.hash = `#/revlab`;
    });
  },
  /** 역설계한 화도 고를 수 있는 역설계 카드를 열고 닫는다. 열면 지금 화를 고른다. */
  /** 역설계한 화도 고르는 개요 표를 열고 닫는다. 열면 지금 화를 고른다. */
  revRedo() {
    S.revRedo = !S.revRedo;
    if (S.revRedo) { S.revPick = new Set([S.revEp]); S.focusTarget = '#app .rev-pick-table input:not(:disabled)'; }
    if (S.revPane === 'overview') render(); else revNav('');
  },
  revNewToggle() {
    S.revNew = !(S.revNew || !!S.revDraft.text);
    if (!S.revNew) S.revDraft = { title: '', text: '', first: '' };
    else S.focusTarget = '#rev-title';
    render();
  },
  revAiProv(arg) {
    const [stage, provider] = String(arg).split(':');
    const x = revAiStage(stage);
    if (x && x.provider === provider) return;
    revAiSave(stage, { provider });  // 백엔드를 바꾸면 모델 칸은 비워 그 백엔드의 기본 모델을 쓴다
  },
  revStyleRun() {
    S.revStyleDiff = null;
    revStartJob('style');
  },
  async revStyleUse(id) {
    const ok = await run('고르는 중', async () => {
      S.revLab = await api('POST', `/revlab/${S.revLab.id}/styles/${id}/select`);
      S.revStyleDiff = null;
    });
    if (ok) toast(`${id}번 프로필을 써요. 다음 '문체 넣고' 되돌려 쓰기부터 이 프로필이 들어가요.`);
  },
  async revStyleDiff(id) {
    const k = Number(id);
    if (S.revStyleDiff && S.revStyleDiff.id === k) { S.revStyleDiff = null; render(); return; }
    await run('견주는 중', async () => {
      const x = await api('GET', `/revlab/${S.revLab.id}/styles/${k}`);
      S.revStyleDiff = { id: k, changes: x.changes };
    });
  },
  async revStyleToLib(id) {
    const L = S.revLab;
    const name = await askText(`${id}번 프로필을 문체 라이브러리에 저장`, { value: `${L.title || `실험 ${L.id}`} 문체 ${id}번`, placeholder: '라이브러리에 보일 이름', ok: '저장하기' });
    if (name === null) return;
    let saved = null;
    const ok = await run('저장하는 중', async () => {
      const r = await api('POST', `/revlab/${L.id}/styles/${id}/library`, { name });
      saved = r.saved;
      S.revLab = r;
    });
    if (ok && saved) toast(`문체 라이브러리에 '${saved.name}' 항목을 저장했어요. 원문과 원문에서 고른 대표 문단도 함께 넣었어요. 작품의 ${stepLabel('style')}에서 '라이브러리에서 고르기'로 적용하세요.`);
  },
  async revStyleNote(id) {
    const x = (S.revLab.style_list || []).find((s) => s.id === Number(id));
    const note = await askText(`${id}번 프로필 메모`, { value: (x && x.note) || '', placeholder: '예: 모델을 바꿔 다시 만듦', ok: '저장하기' });
    if (note === null) return;
    await run('저장하는 중', async () => { S.revLab = await api('PUT', `/revlab/${S.revLab.id}/styles/${id}`, { note }); });
  },
  async revStyleDrop(id) {
    const x = (S.revLab.style_list || []).find((s) => s.id === Number(id)) || {};
    const tail = x.takes ? ` 이 프로필로 쓴 판 ${x.takes}개는 남지만 '지운 프로필'로 보여요.` : '';
    if (!(await askConfirm(`${id}번 프로필을 지울까요?${tail}`, { ok: '지우기', danger: true }))) return;
    await run('지우는 중', async () => {
      S.revLab = await api('DELETE', `/revlab/${S.revLab.id}/styles/${id}`);
      if (S.revStyleDiff && S.revStyleDiff.id === Number(id)) S.revStyleDiff = null;
    });
  },
  revParse() {
    S.revRedo = false;
    revStartJob('parse', { episodes: [...S.revPick].sort((a, b) => a - b) });
  },
  async revWrite(n) {
    const k = Number(n) || S.revEp;
    if ((S.cueEdits[revCueKey(k)] || {}).dirty && !(await askConfirm('저장하지 않은 큐 시트 고침이 있어요. 저장한 큐 시트로 되돌려 쓸까요?', { ok: '되돌려 쓰기', danger: true }))) return;
    revStartJob('write', { episodes: [k], style: !!(S.revStyle && S.revLab.style) });
  },
  revBlindShow(k) {
    const e = revItem(S.revEp);
    if (!e || !e.blind_no) return;
    revBlindState(e).show = Number(k);
    render();
  },
  async revPick(k) {
    const e = revItem(S.revEp);
    const left = Number(k) && e && e.blind_no ? revBlindUnread(e.blind_texts.length, revBlindState(e).seen, Number(k)) : [];
    if (left.length && !(await askConfirm(`${left.join(', ')}번을 아직 끝까지 읽지 않았어요. ${k}번을 고를까요?`, { ok: '고르기' }))) return;
    await run('고르는 중', async () => {
      S.revLab = await api('POST', `/revlab/${S.revLab.id}/episodes/${S.revEp}/pick`, { choice: Number(k), take: e ? e.blind_no : null });
    });
  },
  /** 판 목록의 '읽기': 나란히 읽기 오른쪽에 그 판을 놓고 그 칸으로 내려간다 */
  revReadTake(no) {
    S.revRead = { ...S.revRead, b: Number(no) };
    render();
    const box = document.getElementById('rev-side');
    if (box) box.scrollIntoView({ behavior: 'smooth', block: 'start' });
  },
  async revTakeDrop(no) {
    const n = S.revEp;
    if (!(await askConfirm(`${n}화의 판 ${no}을 지울까요? 본문과 가려 읽기 결과가 함께 사라지고 되돌릴 수 없어요.`, { ok: '판 지우기', danger: true }))) return;
    await run('지우는 중', async () => {
      S.revLab = await api('DELETE', `/revlab/${S.revLab.id}/episodes/${n}/takes/${no}`);
      S.revEsts = {};
    });
  },
  revTab(k) { S.revTab = k; render(); },
  /** 'n|탭': 그 화의 그 탭으로 */
  revGo(arg) {
    const [n, tab] = String(arg).split('|');
    S.revTab = tab || 'text';
    revNav(n);
  },
  /** 목차의 단계 줄: 그 단계를 할 자리로 옮긴다 */
  revStep(id) {
    const L = S.revLab;
    const items = L.items;
    const min = S.rev.min_chars;
    if (id === 'edit') { S.revEdit = true; S.focusTarget = '#rev-etitle'; render(); return; }
    if (id === 'style') { revNav('style'); return; }
    if (id === 'parse' && items.some((e) => e.chars >= min && !e.sheet)) { revNav(''); return; }
    const find = {
      parse: () => items.find((e) => e.chars >= min && !e.sheet),
      write: () => items.find((e) => e.sheet && !(e.takes || []).length),
      pick: () => items.find((e) => (e.blind_texts || []).length),
    }[id];
    const e = (find && find()) || revItem(S.revEp);
    if (!e) return;
    S.revTab = id === 'parse' ? 'text' : 'write';
    revNav(e.number);
  },
  revCueGo(k) {
    S.revSel = S.revSel === k ? 0 : k;
    render();
    const el = document.getElementById(`rev-cue-${k}`);
    if (el && S.revSel) el.scrollIntoView({ block: 'nearest', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  },
});

(() => {
  const css = `
/* 목차 틀은 공용(app.css .outline-*): 목차의 화 이름은 한 줄로 자르고, 900px 이하는 위쪽 띠 아래에 붙는다.
   화 줄의 ⋯ 메뉴 창이 목록 밖으로 나가야 해서 넓은 폭 목록도 굴리지 않는다 */
.rev-wrap .outline-list { max-height: none; overflow: visible; }
/* 목차 화 줄: 오른쪽 ⋯ 메뉴는 줄에 올리거나 포커스가 들어오거나 메뉴가 열리면 보이고, 그동안 글자 수를 가린다 (터치 화면은 늘 보임) */
.rev-toc-ep { position: relative; }
.rev-toc-ep.open { z-index: var(--z-raise); }  /* 열린 메뉴 창이 아래 줄 위에 오게 */
.rev-toc-ep > .menu { position: absolute; right: 4px; top: 50%; transform: translateY(-50%); opacity: 0; }
.rev-toc-ep:hover > .menu, .rev-toc-ep:focus-within > .menu, .rev-toc-ep.open > .menu { opacity: 1; }
.rev-toc-ep:hover .st, .rev-toc-ep:focus-within .st, .rev-toc-ep.open .st { visibility: hidden; }
@media (hover: none) {
  .rev-toc-ep > .menu { opacity: 1; }
  .rev-toc-ep .outline-item { padding-right: 52px; }
}
/* 목차 버튼(＋ · ⋯)은 둘 다 같은 크기: 마우스는 작은 버튼 높이 36px 정사각형, 손가락 기기는 touch-min 44px (docs/design Outline) */
.btn.icon-btn.rev-toc-btn { width: 36px; min-height: 36px; }
.rev-toc-btn svg { width: 18px; height: 18px; }
@media (pointer: coarse) {
  .btn.icon-btn.rev-toc-btn { width: var(--touch-min); min-height: var(--touch-min); }
  .rev-toc-ep .outline-item { min-height: var(--touch-min); }
}
.rev-drop-note { margin: 6px 10px; }
.rev-ep-h { display: flex; align-items: center; justify-content: space-between; padding-top: 8px; padding-bottom: 0; }
.rev-main { display: flex; flex-direction: column; gap: var(--gap-stack); min-width: 0; }
.rev-step { width: 20px; height: 20px; border-radius: 6px; background: var(--chip); color: var(--text-2); display: inline-flex; align-items: center; justify-content: center; font-size: 0.6875rem; font-weight: 700; flex: none; }
.rev-step.ok { background: var(--green-soft); color: var(--green); }
.rev-step.now { background: var(--accent); color: var(--on-accent); }
.rev-step.run { background: var(--accent-soft); color: var(--accent-ink); }
.rev-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; background: var(--line-strong); }
.rev-dot.wrote, .rev-dot.done { background: var(--green); }
.rev-dot.parsed { background: var(--accent); }
.rev-dot.short { background: transparent; border: 1px solid var(--line-strong); }
.rev-dot.run { background: transparent; border: 2px solid var(--line-strong); border-top-color: var(--accent); width: 10px; height: 10px; animation: rev-spin 0.9s linear infinite; }
@keyframes rev-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .rev-dot.run { animation: none; border-color: var(--accent); } }
.rev-meter { margin: 6px 10px 0; height: 6px; border-radius: 4px; background: var(--chip); overflow: hidden; }
.rev-meter.big { margin: 0; height: 8px; }
.rev-meter > i { display: block; height: 100%; background: var(--accent); }
.rev-home { display: flex; flex-direction: column; gap: 22px; }
.rev-home-sec { display: flex; flex-direction: column; gap: 12px; }
.rev-labs { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; }
.rev-lab { gap: 12px; color: inherit; text-decoration: none; }
.rev-lab:hover { border-color: var(--sel-line); background: var(--sel-bg); }
.rev-lab h3 { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rev-lab-steps { gap: 8px; }
.rev-steps { display: inline-flex; gap: 4px; }
.rev-meter.full > i { background: var(--green); }
.rev-how { margin: 0; padding: 0; list-style: none; display: flex; flex-wrap: wrap; gap: 8px 20px; font-size: 0.8125rem; color: var(--text-2); }
.rev-how li { display: flex; align-items: center; gap: 8px; }
.rev-l { text-align: left; }
.rev-first { white-space: normal; min-width: 200px; color: var(--text-2); }
.rev-muted td { color: var(--muted); }
.rev-cur td { background: var(--sel-bg); }
.rev-gets { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
.rev-get { padding: 14px 16px; border-radius: 10px; background: var(--bg); display: flex; flex-direction: column; gap: 4px; }
.rev-mini { display: inline-flex; align-items: flex-end; gap: 2px; width: 110px; height: 22px; vertical-align: middle; }
.rev-mini > i { display: block; border-radius: 2px 2px 0 0; }
.rev-pace-strip { display: block; }
.rev-pace-high { fill: var(--tension-high); }
.rev-pace-mid { fill: var(--tension-mid); }
.rev-pace-low { fill: var(--warm-mid); }
.rev-pace-none { fill: var(--rule); }
.rev-pace-avg { fill: var(--text); }
.rev-pace-mark { font-size: 9px; fill: var(--text); }
.rev-pace-tick { font-size: 10px; fill: var(--text-2); }
.rev-pace-strip a:hover rect { opacity: 0.75; }
.rev-spark { display: block; }
.rev-pace-off td { color: var(--text-2); }
.rev-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; }
.rev-tile { color: inherit; text-decoration: none; }
.rev-tile:hover { border-color: var(--sel-line); background: var(--sel-bg); }
.rev-tile p { color: var(--text-2); }
.rev-takes td, .rev-takes th { white-space: nowrap; }
.rev-takes td.rev-take-pick { white-space: normal; min-width: 120px; }
.rev-takes td.rev-take-who { white-space: normal; min-width: 120px; }
.rev-takes tr.rev-muted td { color: var(--text-2); }
.rev-take-acts { gap: 4px; flex-wrap: wrap; }
.rev-takes td:last-child { white-space: normal; }
.rev-th2 { vertical-align: bottom; }
.rev-th2 > span { display: block; }
.rev-mx-wide td:first-child { position: sticky; left: 0; background: var(--surface); }
.rev-read-picks { gap: 6px; flex-wrap: wrap; }
.rev-read-picks select { max-width: 260px; }
.rev-made td, .rev-made th { white-space: nowrap; }
.rev-ai-row { display: grid; grid-template-columns: minmax(180px, 220px) 1fr; gap: 16px; padding-top: 16px; border-top: 1px solid var(--line); }
.rev-ai-row h3 { margin: 0 0 4px; }
.rev-ai-pick { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.rev-ai-pick .seg { flex-wrap: wrap; align-self: flex-start; max-width: 100%; }
.rev-ai-pick .seg button { white-space: nowrap; }
@container outline (max-width: 720px) { .rev-ai-row { grid-template-columns: 1fr; } }
.btn .cost { font-weight: 400; opacity: 0.85; }
.rev-fields { display: flex; flex-wrap: wrap; gap: 12px; }
.rev-f-title { flex: 3 1 260px; }
.rev-f-first { flex: 1 1 160px; }
.rev-paste { display: flex; flex-wrap: wrap; gap: 16px; align-items: stretch; }
.rev-paste > .field { flex: 999 1 420px; }
.rev-paste textarea { min-height: 360px; font-family: var(--serif); }
.rev-preview { flex: 1 1 240px; padding: 14px; border-radius: 10px; background: var(--bg); display: flex; flex-direction: column; gap: 10px; align-self: flex-start; }
.rev-prev { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 6px; font-size: 0.8125rem; }
.rev-prev li { display: flex; justify-content: space-between; gap: 8px; }
.rev-panel { display: flex; flex-direction: column; gap: 16px; }
.rev-cols { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; }
.rev-src { flex: 999 1 440px; min-width: 0; gap: 6px; }
.rev-side { flex: 1 1 320px; min-width: 0; display: flex; flex-direction: column; gap: 16px; position: sticky; top: 16px; max-height: calc(100vh - 32px); overflow-y: auto; }
.rev-raw { max-height: 70vh; overflow-y: auto; }
.rev-seg { display: flex; flex-direction: column; gap: 6px; padding: 4px 8px 8px; border: 1px solid transparent; border-radius: 8px; scroll-margin-top: 80px; }
.rev-seg.sel { background: var(--sel-bg); border-color: var(--sel-line); }
.rev-seg .cue-text { line-height: 1.9; }
/* 큐 띠는 구간 위에 가로로 놓는다: 기능 · 큐 번호 · 긴장. 본문이 칸 폭을 다 쓴다 */
.rev-gut { align-self: stretch; min-height: var(--touch-min); display: flex; flex-direction: row; align-items: center; gap: 8px; padding: 6px 8px 2px; border: none; border-top: 4px solid var(--line-strong); border-radius: 0; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.rev-gut:hover { background: var(--bg); }
.rev-gut.fn-T { border-top-color: var(--act-1-ink); }
.rev-gut.fn-S { border-top-color: var(--act-2-ink); }
.rev-gut.fn-D { border-top-color: var(--act-4-ink); }
.rev-fn { display: inline-flex; align-items: center; justify-content: center; min-width: 24px; height: 22px; padding: 0 4px; border-radius: 6px; background: var(--chip); font-size: 0.75rem; font-weight: 800; }
.rev-fn.T { background: var(--act-1); color: var(--act-1-ink); }
.rev-fn.S { background: var(--act-2); color: var(--act-2-ink); }
.rev-fn.D { background: var(--act-4); color: var(--act-4-ink); }
.rev-side .cue-bars { height: 72px; }
.rev-cues { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.rev-cue { border: 1px solid transparent; border-radius: 8px; }
.rev-cue.sel { background: var(--sel-bg); border-color: var(--sel-line); }
.rev-cue-btn { width: 100%; min-height: var(--touch-min); display: grid; grid-template-columns: 28px 20px minmax(0, 1fr); gap: 4px 8px; align-items: center; padding: 6px 8px; border: none; border-radius: 8px; background: transparent; color: inherit; font: inherit; font-size: 0.8125rem; text-align: left; cursor: pointer; }
.rev-cue-btn:hover { background: var(--bg); }
.rev-cue-btn .meta { grid-column: 3; font-size: 0.75rem; color: var(--muted); }
.rev-cue-more { padding: 0 10px 10px 32px; }
.rev-kv { display: grid; grid-template-columns: 72px minmax(0, 1fr); gap: 4px 12px; margin: 0; font-size: 0.8125rem; }
.rev-kv dt { color: var(--muted); }
.rev-kv dd { margin: 0; }
.rev-ul { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 4px; }
.rev-two { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; align-items: start; }
.rev-blind { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; }
.rev-blind-read { max-height: 70vh; }  /* 가려 읽기는 한 쪽씩이라 길게 */
.rev-blind-col { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.rev-read { max-height: 60vh; overflow-y: auto; padding: 12px 14px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg); }
.rev-scroll { overflow-x: auto; }
.rev-mx td, .rev-mx th { white-space: nowrap; }
.rev-mx .rev-far { color: var(--amber-ink); font-weight: 700; }
.rev-mx-ep th { padding-top: 14px; text-align: left; }
.rev-est summary { cursor: pointer; min-height: var(--touch-min); display: flex; align-items: center; }
.rev-run-rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.rev-run-row { min-height: var(--touch-min); display: grid; grid-template-columns: 14px minmax(0, 1fr) auto auto; gap: 10px; align-items: center; padding: 0 8px; border-radius: 8px; }
.rev-run-row.run { background: var(--sel-bg); }
.rev-run-row.wait .tl { color: var(--muted); }
@container outline (max-width: 1040px) {
  .rev-side { position: static; max-height: none; overflow: visible; }
}
@container outline (max-width: 720px) {
  .rev-blind { grid-template-columns: minmax(0, 1fr); }
  .rev-cue-more { padding-left: 10px; }
  .rev-paste textarea { min-height: 240px; }
}
@media (forced-colors: active) { .rev-seg.sel, .rev-cue.sel, .rev-cur td { outline: 2px solid Highlight; } }
`;
  const el = document.createElement('style');
  el.textContent = css;
  document.head.appendChild(el);
})();

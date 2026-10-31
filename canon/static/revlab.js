/* 역설계 실험 화면(서버 revlab.py, 작품 밖 화면 #/revlab[/<실험 번호>[/<화 | cast | style | lines | metrics>]], 작품 목록 · 사이드바 ⋯ 메뉴 · 작품 사이드바 실험 묶음에서 들어온다).
   작가가 넣은 소설을 거꾸로 화별 플롯 · 스토리보드 · 큐 시트 · 이야기 줄기로 풀고, 그 큐 시트로 같은 화를 다시 써서(되돌려 쓰기) 원문과 견준다.
   실험은 작품 밖(<CANON_HOME>/.revlab)에 두고 작품을 열지 않고 쓴다. AI 작업은 POST /revlab/<번호>/jobs (작업 rev_parse · rev_write · rev_style,
   ep 가 실험 번호, project 는 REV_JOBS). 사용량은 작품 없이 잡히고 모델은 전체 단계 설정을 쓴다.
   배치는 다른 단계 화면(설정 도우미 · 문체 · 플롯)과 같은 왼쪽 목차 + 오른쪽 칸이다. 목차는 단계 다섯(revSteps) · 화(revTocEps) · 실험 전체
   (인물 · 문체 · 줄기 · 지표), 오른쪽은 도는 작업 카드(revRunCard)와 고른 화의 탭 셋(원문 · 큐 / 플롯 · 스토리보드 / 되돌려 쓰기).
   머리 주 버튼은 다음 할 일 하나(revNext)이고 추정 비용을 함께 적는다(revEst, AI 없음). 폭은 창이 아니라 .rev-wrap 폭(@container rev)으로 바꾼다.
   app.js 의 S, actions, api, run, render, header, esc, toast, josa, showError, renderJobs, pollJobs, jobFor, jobLeft, elapsed, menuBtn, isTyping,
   JOB_PAGES, JOB_DONE_MSG, fmtDateTime 과 cue.js 의 cueBind · cueEd · cueScore · cueEditor · cueLabel · cueUsd · cuePct · cueYes 를 쓴다
   (큐 시트 열쇠는 'rev:<화>'). revSplit · revGuessFirst · revSegments · revPreview · revEpTitle · revSteps · revNext · revTocEps · revRunRows ·
   revMetricRows 는 DOM 없는 순수 함수 (revSplit · revGuessFirst 는 revlab.split · guess_first 와 같은 규칙, tests/test_revlab.py). */
'use strict';

Object.assign(S, {
  rev: null,       // 서버 값 { labs, splits, max_episodes, max_chars, min_chars, … 큐 칸 이름 }
  revLab: null,    // 고른 실험 (revlab.view)
  revEp: null,     // 보는 화 번호
  revPane: null,   // 화 대신 보는 실험 전체 칸 (REV_PANES 의 열쇠)
  revTab: 'text',  // 화 탭 (REV_TABS)
  revDraft: { title: '', text: '', first: '' },  // 새 실험 칸 (first 가 비면 짐작한 번호)
  revPick: null,   // 역설계할 화 Set
  revRedo: false,  // 역설계한 화도 다시 고르는 역설계 카드를 열었는지
  revEsts: {},     // 비용 추정 { 열쇠(revEstKey): 값 | null(묻는 중) | { error } }
  revSel: 0,       // 원문에서 밝힌 큐 번호 (1부터)
  revEdit: false,  // 실험 글 고치기 칸을 열었는지
  revStyle: false, // 되돌려 쓰기에 문체 프로필을 넣을지
  revRead: 'plain', // 나란히 읽기 오른쪽 판 (plain · style)
});

const REV_HEAD = /^\s*(?:#{1,6}\s*)?(?:제\s*)?(\d{1,4})\s*화(?:\s*[.:：\-—)]\s*|\s+|$)(.*)$/;
const REV_MARK = /^\s*={3,}\s*$/;
const REV_BLANK = /\n(?:[ \t]*\n){3,}/;
const REV_SPLITS = { heading: "'n화' 제목 줄", mark: "'===' 줄", blank: '빈 줄 세 개 넘게', one: '한 화' };

/** 글 → 화 (revlab.split 과 같은 규칙): { how, first, preface, episodes: [{ head, text }] }. 제목 줄 → '===' 줄 → 빈 줄 셋 넘게 → 한 화.
    제목 줄 앞 글이 preMin 자보다 짧으면 preface(역설계하지 않음), 길면 화 하나. */
function revSplit(text, headMax = 60, preMin = 200) {
  const t = String(text || '').replace(/﻿/g, '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const lines = t.split('\n');
  const heads = lines.map((l, i) => (l.length <= headMax && REV_HEAD.test(l) ? i : -1)).filter((i) => i >= 0);
  let how; let eps; let preface = ''; let first = 1;
  if (heads.length) {
    how = 'heading';
    first = Number(lines[heads[0]].match(REV_HEAD)[1]) || 1;
    const before = lines.slice(0, heads[0]).join('\n').trim();
    eps = heads.map((h, k) => ({ head: lines[h].trim(), text: lines.slice(h + 1, k + 1 < heads.length ? heads[k + 1] : lines.length).join('\n').trim() }));
    if (before.length >= preMin) { eps.unshift({ head: '', text: before }); first = Math.max(first - 1, 1); } else preface = before;
  } else if (lines.some((l) => REV_MARK.test(l))) {
    how = 'mark'; eps = [];
    let cur = [];
    for (const l of [...lines, '===']) {
      if (REV_MARK.test(l)) { eps.push({ head: '', text: cur.join('\n').trim() }); cur = []; } else cur.push(l);
    }
  } else if (REV_BLANK.test(t)) {
    how = 'blank'; eps = t.split(REV_BLANK).map((x) => ({ head: '', text: x.trim() }));
  } else {
    how = 'one'; eps = [{ head: '', text: t.trim() }];
  }
  return { how, first, preface, episodes: eps.filter((e) => e.text) };
}

/** 첫 화 번호 짐작 (revlab.guess_first): 글에 'n화' 제목 줄이 있으면 그 번호, 없으면 실험 이름의 'n화', 그것도 없으면 1. */
function revGuessFirst(title, text) {
  const s = revSplit(text);
  if (s.how === 'heading') return s.first;
  const m = String(title || '').match(/(\d{1,4})\s*화/);
  return m ? Number(m[1]) || 1 : 1;
}

/** 나누기 미리보기 값: 화마다 번호 · 제목 · 글자 수 · 짧음, 막는 까닭(errs)과 알릴 것(notes). lim 은 서버 이름표 (max_chars 등). */
function revPreview(text, lim, first = null) {
  const s = revSplit(text, lim.head_max, lim.preface_min);
  if (first) s.first = first;
  const errs = []; const notes = [];
  const len = String(text || '').length;
  if (!s.episodes.length) errs.push('글이 비었어요. 소설 본문을 붙여 넣으세요.');
  if (len > lim.max_chars) errs.push(`글이 너무 길어요 (${len.toLocaleString()}자). ${lim.max_chars.toLocaleString()}자까지 넣을 수 있어요.`);
  if (s.episodes.length > lim.max_episodes) errs.push(`${s.episodes.length}화로 나뉘었어요. 한 실험에 ${lim.max_episodes}화까지 넣을 수 있어요.`);
  const eps = s.episodes.map((e, i) => ({ n: s.first + i, head: e.head, chars: e.text.length, short: e.text.length < lim.min_chars }));
  if (eps.some((e) => e.short)) notes.push(`${lim.min_chars}자보다 짧은 화는 역설계하지 않아요.`);
  if (s.preface) notes.push(`첫 제목 줄 앞의 짧은 글(${s.preface.length}자)은 작품 제목 · 작가 줄로 보고 역설계하지 않아요.`);
  if (s.first <= 3 && s.episodes.length) notes.push('1~3화로 잡히면 되돌려 쓰기에 초반 규칙(첫 화 쓰는 법)이 붙어요. 소설 중간이면 첫 화 번호를 적으세요.');
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
    renderJobs();
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
  S.revPane = n in REV_PANES ? n : null;
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
  for (const e of S.revLab.items) {
    const key = revCueKey(e.number);
    if ((S.cueEdits[key] || {}).dirty && made.has(e.number) && made.get(e.number) === (e.sheet && e.sheet.made_at)) continue;
    S.cueEdits[key] = { draft: e.sheet ? structuredClone(e.sheet) : null, dirty: false };
  }
  if (!old || old.id !== id) {
    S.revPick = new Set(S.revLab.items.filter((e) => !e.sheet && e.chars >= S.rev.min_chars).map((e) => e.number));
    S.revSel = 0; S.revEdit = false; S.revRedo = false; S.revTab = 'text'; S.revEp = null;
  } else if (S.revPick && !S.revRedo) {
    for (const e of S.revLab.items) if (e.sheet) S.revPick.delete(e.number);  // 다 푼 화는 다음 역설계에서 뺀다
    if (!S.revPick.size) S.revPick = new Set(S.revLab.items.filter((e) => !e.sheet && e.chars >= S.rev.min_chars).map((e) => e.number));
  }
  S.revEsts = {};
}

/* ----- 단계 · 다음 할 일 · 진행 줄 · 지표 줄: DOM 없는 순수 함수 (tests/test_revlab.py) ----- */

const REV_PANES = { cast: '인물 · 관계 · 배경', style: '문체 프로필', lines: '이야기 줄기', metrics: '지표 모아 보기' };
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
function revSteps(L, minChars, kinds = []) {
  const items = L.items || [];
  const can = items.filter((e) => e.chars >= minChars);
  const parsed = can.filter((e) => e.sheet);
  const wrote = items.filter((e) => (e.takes || []).length);
  const picked = wrote.filter((e) => e.picked);
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
    const right = { short: '짧음', wrote: (e.blind_texts || []).length ? '가려 읽기' : '씀', parsed: `큐 ${e.sheet ? e.sheet.cues.length : 0}`, raw: `${e.chars.toLocaleString()}자` }[state];
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

const REV_METRICS = [  // [이름, 값, 원문과 크게 다르면 표시할지]
  ['글자', (s) => s.chars, true, (v) => v.toLocaleString()],
  ['핵심 대사 들어감', (s) => (s.lines_total ? `${s.lines_hit}/${s.lines_total}` : null), false],
  ['대사 비율', (s) => s.dialogue_ratio, true, (v) => cuePct(v)],
  ['문장 길이', (s) => s.sentence_len, true],
  ['어휘 다양도', (s) => s.mattr, false],
  ['짧은 끝 문장', (s) => s.short_endings, false, (v) => cuePct(v)],
  ['되풀이 문장', (s) => (s.repeats || []).length, true],
  ['쇠맛 경고', (s) => s.ai_patterns, true],
  ['템포 (원문 큐 경계)', (s) => ((s.rows || []).length ? cueYes(s.tempo_order) : null), false],
];
const REV_FAR = 0.4;  // 원문 값과 이 비율보다 더 다르면 표시한다

/** 지표 표를 지표마다 한 줄로: { heads: [{ label, stale }], rows: [{ label, cells: [{ text, far }] }] }. 열은 scores 차례 (원문이 먼저). */
function revMetricRows(scores) {
  const orig = scores.find((s) => s.condition === 'original');
  const far = (v, o) => typeof v === 'number' && typeof o === 'number' && (o ? Math.abs(v - o) / Math.abs(o) > REV_FAR : v > 0);
  return {
    heads: scores.map((s) => ({ label: s.label, stale: !!s.stale })),
    rows: REV_METRICS.map(([label, get, mark, fmt]) => ({
      label,
      cells: scores.map((s) => {
        const v = get(s);
        return { text: v === null || v === undefined ? '-' : fmt ? fmt(v) : String(v), far: mark && s !== orig && !!orig && far(v, get(orig)) };
      }),
    })),
  };
}

/* ----- 화면 ----- */

const revRunning = () => (S.revLab ? REV_KINDS.map((k) => jobFor(k, S.revLab.id, REV_JOBS)).find(Boolean) || null : null);

const revEstKey = (kind, eps) => `${kind}:${[...eps].sort((a, b) => a - b).join(',')}`;  // kind: parse · write · write-style · style

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
      .finally(() => { if (!isTyping()) render(); });
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
    '사람이 쓴 소설을 화별 플롯 · 스토리보드 · 큐 시트로 거꾸로 풀고, 그 큐 시트로 같은 화를 다시 써서 원문과 견줘요. 작품 데이터는 바꾸지 않아요.')}${body}`;
  if (!d) return home('<div class="note plain">불러오는 중…</div>');
  if (d.error) return home(`<div class="note err">${esc(d.error)}</div>`);
  if (!S.revLab) return home(revLayout(revHomeToc(), revNewCard()));
  if (S.revLab.error) return home(`<div class="note err">${esc(S.revLab.error)}</div><p><a href="#/revlab">실험 목록으로</a></p>`);
  return `${revLabHead()}${revLayout(revLabToc(), revMain())}`;
}

const revLayout = (toc, main) => `<div class="rev-wrap"><div class="rev-doc">${toc}<div class="rev-main">${main}</div></div></div>`;

/** 목차 틀: 넓은 칸은 왼쪽 목록, 좁은 칸(720px 이하)은 위에 붙는 '지금 줄 ▾' 버튼. */
function revToc(label, now, list) {
  return `<nav class="rev-toc" id="rev-toc" aria-label="${label}">
    <button type="button" class="btn rev-toc-now" data-action="revTocToggle" aria-expanded="false" aria-controls="rev-toc-list"><span>${now}</span><span aria-hidden="true">▾</span></button>
    <div class="rev-toc-list" id="rev-toc-list">${list}</div></nav>`;
}
const revTocLink = (href, inner, cur = false) => `<a class="rev-toc-item" href="${href}"${cur ? ' aria-current="page"' : ''}>${inner}</a>`;

function revHomeToc() {
  const labs = S.rev.labs || [];
  const dot = (x) => (x.rewrites ? 'wrote' : x.done ? 'parsed' : 'raw');
  const list = `${revTocLink('#/revlab', '<span class="rev-step now" aria-hidden="true">+</span><span class="tl">새 실험</span>', true)}
    ${labs.length ? `<span class="rev-toc-h">지난 실험</span>${labs.map((x) => revTocLink(`#/revlab/${x.id}`,
    `<span class="rev-dot ${dot(x)}" aria-hidden="true"></span><span class="tl">${esc(x.title || `실험 ${x.id}`)}</span><span class="st">${x.rewrites ? `씀 ${x.rewrites}` : `${x.done}/${x.episodes}`}</span>`)).join('')}` : ''}
    <span class="rev-toc-h">어떻게 하나요</span>
    <ol class="rev-how small"><li>붙여 넣고 화로 나눠요. AI를 부르지 않아요.</li><li>역설계: AI가 화마다 플롯 · 스토리보드 · 큐 시트를 적어요.</li><li>되돌려 쓰기: 그 큐 시트로 같은 화를 다시 써서 원문과 가려 읽고 지표를 견줘요.</li></ol>
    <p class="small rev-how-note">역설계와 되돌려 쓰기는 실제 AI를 불러 비용이 들어요. 버튼에 추정 비용을 함께 보여 드려요.</p>`;
  return revToc('실험 목록', '새 실험', list);
}

const revDraftFirst = () => Number(S.revDraft.first) || revGuessFirst(S.revDraft.title, S.revDraft.text);

function revPreviewHtml() {
  if (!S.revDraft.text.trim()) return '<div class="small">붙여 넣으면 어떻게 나뉘는지 여기 보여요. 직접 나누려면 화 사이에 <code>===</code> 한 줄을 넣으세요.</div>';
  const v = revPreview(S.revDraft.text, S.rev, revDraftFirst());
  const eps = v.eps.map((e) => `<li><span>${e.head ? esc(e.head) : `${e.n}화`}${e.short ? ' <span class="chip warn">짧음</span>' : ''}</span><span class="small">${e.chars.toLocaleString()}자</span></li>`).join('');
  return `<div class="between"><strong>${v.eps.length}화로 나눠요</strong><span class="chip">${esc(v.label)}</span></div>
    <ol class="rev-prev">${eps}</ol>
    ${v.errs.map((x) => `<div class="note err small">${esc(x)}</div>`).join('')}${v.notes.map((x) => `<div class="small">${esc(x)}</div>`).join('')}`;
}

function revNewCard() {
  const ok = !revPreview(S.revDraft.text, S.rev).errs.length;
  const n = S.revDraft.text.length;
  return `<section class="card"><h2>새 실험</h2>
    <div class="rev-fields">
      <div class="field rev-f-title"><label for="rev-title">이름</label><input id="rev-title" type="text" data-rev-new="title" value="${esc(S.revDraft.title)}" placeholder="예: 등대지기 1~3화"></div>
      <div class="field rev-f-first"><label for="rev-first">첫 화 번호</label><input id="rev-first" type="number" min="1" max="9999" data-rev-new="first" value="${esc(S.revDraft.first)}" placeholder="${revDraftFirst()}" aria-describedby="rev-first-hint"><span class="small" id="rev-first-hint">비우면 제목 줄이나 이름의 'n화'에서 짐작해요</span></div>
    </div>
    <div class="rev-paste">
      <div class="field"><label for="rev-text">소설 글 <span class="small" id="rev-count">${n ? `· ${n.toLocaleString()}자` : ''}</span></label><textarea id="rev-text" rows="16" data-rev-new="text" placeholder="여기에 붙여 넣으세요">${esc(S.revDraft.text)}</textarea></div>
      <div class="rev-preview" id="rev-preview" aria-live="polite">${revPreviewHtml()}</div>
    </div>
    <div class="between"><span class="small">넣은 글은 이 컴퓨터의 실험 폴더(.revlab)에만 저장해요. 만들기는 AI를 부르지 않아요.</span>
      <button type="button" class="btn primary" data-action="revCreate"${ok ? '' : ' disabled'}>실험 만들기</button></div></section>`;
}

function revLabHead() {
  const L = S.revLab;
  const desc = [`${L.first}~${L.first + L.episodes - 1}화`, `${L.chars.toLocaleString()}자`, `${L.split_label}로 나눔`,
    L.cast.length ? `인물 ${L.cast.length}명` : '', L.lines.length ? `이야기 줄기 ${L.lines.length}개` : ''].filter(Boolean).join(' · ');
  const menu = () => `<button type="button" class="pop-item" data-action="revEditToggle">글 · 이름 고치기</button>
    ${L.done ? '<button type="button" class="pop-item" data-action="revRedo">다시 역설계할 화 고르기</button>' : ''}
    <a class="pop-item" href="#/revlab">새 실험 · 지난 실험</a>
    <button type="button" class="pop-item danger" data-action="revDelete">실험 지우기</button>`;
  return header('실험 · 본편과 분리 › <a href="#/revlab">역설계 실험</a>', L.title || `실험 ${L.id}`, esc(desc),
    `${menuBtn('rev-lab', '⋯', menu, { aria: '실험 메뉴: 글 · 이름 고치기 · 다시 역설계 · 지우기' })}${revGoBtn()}`);
}

/** 머리 주 버튼 (다음 할 일 하나). 작업이 도는 동안에는 진행 카드의 멈추기만 둔다. */
function revGoBtn() {
  const L = S.revLab;
  if (revRunning()) return '';
  const nx = revNext(L, S.revEp, S.rev.min_chars);
  if (!nx) return '';
  if (nx.kind === 'parse') {
    const eps = [...(S.revPick || [])].sort((a, b) => a - b);
    const est = eps.length ? revEst('parse', eps) : null;
    return `<button type="button" class="btn primary" data-action="revParse"${eps.length && est ? '' : ' disabled'}>${eps.length ? revCost(`${eps.length}화 역설계`, est) : '역설계할 화를 고르세요'}</button>`;
  }
  if (nx.kind === 'pick') return `<button type="button" class="btn primary" data-action="revGo" data-arg="${nx.n}|write">${nx.n}화 가려 읽기</button>`;
  const style = !!(S.revStyle && L.style);
  const est = revEst('write', [nx.n], style);
  return `<button type="button" class="btn primary" data-action="revWrite" data-arg="${nx.n}"${est ? '' : ' disabled'}>${revCost(`${nx.n}화 되돌려 쓰기${style ? ' (문체 넣고)' : ''}`, est)}</button>`;
}

const REV_STEP_GO = { split: 'edit', parse: 'parse', style: 'style', write: 'write', pick: 'pick' };

function revLabToc() {
  const L = S.revLab;
  const run = revRunning();
  const steps = revSteps(L, S.rev.min_chars, run ? [run.kind] : []);
  const eps = revTocEps(L.items, S.rev.min_chars);
  const pane = S.revPane;
  const stepRows = steps.map((s, i) => `<button type="button" class="rev-toc-item" data-action="revStep" data-arg="${REV_STEP_GO[s.id]}">
      <span class="rev-step ${s.state}" aria-hidden="true">${s.state === 'ok' ? '✓' : i + 1}</span><span class="tl">${esc(s.label)}</span>
      <span class="st">${s.state === 'run' ? '하는 중' : esc(s.right)}</span><span class="sr-only">${{ ok: '끝남', now: '지금 할 단계', todo: '', run: '하는 중' }[s.state]}</span></button>`).join('');
  const busy = run && run.kind === 'rev_parse' ? revRunRows(run, L.items) : [];
  const epRows = eps.map((x) => {
    const r = busy.find((b) => b.n === x.n);
    const st = r && r.state === 'run' ? '<span class="st">푸는 중</span>' : `<span class="st">${esc(x.right)}</span>`;
    return revTocLink(`#/revlab/${L.id}/${x.n}`, `<span class="rev-dot ${r && r.state === 'run' ? 'run' : x.state}" aria-hidden="true"></span><span class="tl">${x.n}화${x.title ? ` ${esc(x.title)}` : ''}</span>${st}`, !pane && x.n === S.revEp);
  }).join('');
  const panes = Object.entries(REV_PANES).map(([k, label]) => {
    const right = { cast: L.cast.length ? `${L.cast.length}명` : '', style: L.style ? '있음' : '', lines: L.lines_at ? `${L.lines.length}개` : '', metrics: '' }[k];
    return revTocLink(`#/revlab/${L.id}/${k}`, `<span class="tl">${label}</span><span class="st">${right}</span>`, pane === k);
  }).join('');
  const cur = pane ? REV_PANES[pane] : (() => { const e = revItem(S.revEp); return e ? `${e.number}화${revEpTitle(e) ? ` ${esc(revEpTitle(e))}` : ''} · ${(REV_TABS.find(([k]) => k === S.revTab) || REV_TABS[0])[1]}` : '목차'; })();
  return revToc('실험 목차', cur, `<span class="rev-toc-h">단계</span>${stepRows}<div class="rev-meter" role="img" aria-label="단계 ${Math.round(revStepShare(steps) * 4)}/4 끝남"><i style="width:${Math.round(revStepShare(steps) * 100)}%"></i></div>
    <span class="rev-toc-h">화</span>${epRows}<span class="rev-toc-h">실험 전체</span>${panes}`);
}

function revMain() {
  const parts = [revRunCard(), S.revEdit ? revEditCard() : ''];
  if (S.revPane === 'cast') parts.push(revContextCard());
  else if (S.revPane === 'style') parts.push(revStyleCard());
  else if (S.revPane === 'lines') parts.push(revLinesCard());
  else if (S.revPane === 'metrics') parts.push(revMetricsAll());
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

/** 도는 작업 카드: 역설계는 화마다 한 줄(끝난 화는 바로 열기), 되돌려 쓰기 · 문체는 한 줄. 멈추기는 알림 창과 같은 동작. */
function revRunCard() {
  const j = revRunning();
  if (!j) return '';
  const L = S.revLab;
  const pct = Math.round((100 * j.done) / Math.max(1, j.total));
  const what = { rev_parse: '역설계하는 중', rev_write: '되돌려 쓰는 중', rev_style: '문체를 역설계하는 중' }[j.kind];
  const rows = j.kind === 'rev_parse' ? revRunRows(j, L.items).map((r) => `<li class="rev-run-row ${r.state}">
      <span class="rev-dot ${r.state === 'done' ? 'wrote' : r.state}" aria-hidden="true"></span>
      <span class="tl">${r.n ? `<strong>${r.n}화</strong>${r.title ? ` ${esc(r.title)}` : ''}` : `<strong>${esc(r.title)}</strong> <span class="small">모든 화를 푼 뒤 한 번</span>`}</span>
      <span class="small">${{ done: '끝', run: '푸는 중', wait: '기다림' }[r.state]}</span>
      ${r.state === 'done' && r.n ? `<a class="btn small" href="#/revlab/${L.id}/${r.n}">열기</a>` : '<span></span>'}</li>`).join('') : '';
  const left = jobLeft(j, Date.now() / 1000);
  return `<section class="card rev-run" aria-live="polite"><div class="between"><h2>${what}</h2><button type="button" class="btn small" data-job-stop="${j.id}">멈추기</button></div>
    <div class="small"><span data-elapsed="${j.id}">경과 ${elapsed(j)}</span>${j.total > 1 ? ` · 요청 ${j.total}번 중 ${Math.min(j.done + 1, j.total)}번째` : ''}${left ? ` · ${left}` : ''}</div>
    <div class="rev-meter big" role="progressbar" aria-valuemin="0" aria-valuemax="${j.total}" aria-valuenow="${j.done}" aria-label="${what}"><i style="width:${pct}%"></i></div>
    ${rows ? `<ol class="rev-run-rows">${rows}</ol>` : ''}
    <div class="note plain">${j.kind === 'rev_parse' ? '화마다 끝나는 대로 저장해요. 끝난 화는 지금 열어 봐도 되고, 다른 화면으로 가도 돼요. ' : ''}다 끝나면 위쪽 알림 버튼으로 알려 드려요.</div></section>`;
}

/** 역설계 카드: 풀 화 고르기 · 비용 · 시작. 역설계하지 않은 화를 보거나 '다시 역설계할 화 고르기'를 열면 보인다. */
function revParseCard() {
  const L = S.revLab;
  const pick = S.revPick || new Set();
  const boxes = L.items.map((e) => {
    const off = e.chars < S.rev.min_chars;
    return `<label class="check-row small rev-pick"><input type="checkbox" data-rev-pick="${e.number}"${pick.has(e.number) && !off ? ' checked' : ''}${off ? ' disabled' : ''}><span>${e.number}화${e.sheet ? ' · 풀었음' : ''}${off ? ' · 짧음' : ''}</span></label>`;
  }).join('');
  const eps = [...pick].sort((a, b) => a - b);
  const est = eps.length ? revEst('parse', eps) : null;
  const err = eps.length ? revEstErr('parse', eps) : '';
  const redo = eps.some((n) => (revItem(n) || {}).sheet);
  const busy = !!revRunning();
  return `<section class="card"><div class="between"><h2>역설계</h2>${S.revRedo ? '<button type="button" class="btn small ghost" data-action="revRedo">닫기</button>' : ''}</div>
    <div class="row rev-picks">${boxes}</div>
    <p class="small">고른 화를 앞에서부터 차례로 풀어요. 앞 화 결과(인물 · 줄거리 · 끝 부분)가 다음 화 요청에 들어가요. 모든 화를 풀면 이야기 줄기를 한 번 더 물어요.</p>
    ${redo ? '<div class="note warn small">이미 역설계한 화를 다시 풀면 그 화의 큐 시트 고침과 되돌려 쓴 글이 사라져요.</div>' : ''}
    ${err ? `<div class="note err small">비용을 재지 못했어요: ${esc(err)}</div>` : ''}
    <div class="row"><button type="button" class="btn" data-action="revParse"${eps.length && est && !busy ? '' : ' disabled'}>${eps.length ? revCost(`고른 ${eps.length}화 역설계`, est) : '화를 고르세요'}</button></div>
    ${revEstHtml(est)}</section>`;
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

/** 문체 프로필: 원문 앞부분으로 한 번 역설계한다 (예시 문단은 비움). 되돌려 쓰기에서 넣을지 고른다. */
function revStyleCard() {
  const L = S.revLab;
  if (!L.done) return '<section class="card empty"><h2>문체 프로필</h2><p>화를 하나 넘게 역설계한 뒤에 만들 수 있어요.</p></section>';
  const st = L.style;
  const est = revEst('style', []);
  const busy = !!revRunning();
  const kv = (k, v) => (v ? `<dt>${k}</dt><dd>${esc(v)}</dd>` : '');
  const body = st ? `<dl class="rev-kv">${kv('시점', st.narration_pov)}${kv('시제', st.tense)}${kv('문장 리듬', st.sentence_rhythm)}${kv('묘사 밀도', st.description_density)}
      ${kv('대사 비중', st.dialogue_ratio)}${kv('대사 방식', st.dialogue_style)}${kv('속생각', st.inner_monologue)}${kv('속도', st.pacing)}${kv('장면 전환', st.scene_transition)}${kv('어휘', st.vocabulary)}</dl>
      ${(st.markers || []).length ? `<div class="small">표지: ${st.markers.map((m) => `«${esc(m.text)}»`).join(' · ')}</div>` : ''}
      <div class="small">${esc(L.style_model)} · ${esc(fmtDateTime(L.style_at))}</div>`
    : '<p class="small">원문 앞부분으로 문체 프로필(시점 · 문장 리듬 · 대사 방식 · 표지)을 만들어요. 원문을 베끼지 않게 예시 문단은 넣지 않아요. 되돌려 쓰기에서 문체를 넣은 판과 넣지 않은 판을 견주면 차이가 구조에서 오는지 문체에서 오는지 갈라 볼 수 있어요.</p>';
  return `<section class="card"><h2>문체 프로필</h2>${body}
    <div class="row"><button type="button" class="btn" data-action="revStyleRun"${est && !busy ? '' : ' disabled'}>${revCost(st ? '문체 다시 역설계' : '문체 역설계 시작', est)}</button></div>
    ${revEstHtml(est)}</section>`;
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
function revMetricsAll() {
  const L = S.revLab;
  const eps = L.items.filter((e) => (e.scores || []).length > 1);
  if (!eps.length) return '<section class="card empty"><h2>지표 모아 보기</h2><p>되돌려 쓰고 가려 읽기를 마친 화가 생기면 원문과 지표를 나란히 모아 보여 드려요.</p></section>';
  const body = eps.map((e) => {
    const m = revMetricRows(e.scores);
    const pick = e.picked ? (e.picked === 'skip' ? '고르지 않음' : e.picked === 'original' ? '원문을 고름' : '되돌려 쓴 글을 고름') : '';
    return `<tr class="rev-mx-ep"><th colspan="${m.heads.length + 1}"><button type="button" class="btn small ghost" data-action="revGo" data-arg="${e.number}|write">${e.number}화${revEpTitle(e) ? ` ${esc(revEpTitle(e))}` : ''}</button> <span class="small">${pick}</span></th></tr>
      <tr><td></td>${m.heads.map((h) => `<th>${esc(h.label)}</th>`).join('')}</tr>
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
        : (e.takes || []).length ? `<span class="chip finalized">되돌려 씀 ${e.takes.length}판</span>` : '<span class="chip confirmed">역설계 완료</span>';
  const facts = [`${e.chars.toLocaleString()}자`];
  if (e.sheet) {
    facts.push(`큐 ${e.sheet.cues.length}`);
    if (e.storyboard) facts.push(`장면 ${e.storyboard.scenes.length}`);
    if (e.plot) facts.push(`사건 ${e.plot.events.length}`);
  }
  const head = `<div class="between rev-ep-head"><div class="row"><h2>${e.number}화${revEpTitle(e) ? ` ${esc(revEpTitle(e))}` : ''}</h2>${chip}<span class="small">${facts.join(' · ')}</span></div>${nav}</div>`;
  const redo = S.revRedo ? revParseCard() : '';
  if (!e.sheet) {
    return `${redo}${head}${short || S.revRedo || jobFor('rev_parse', L.id, REV_JOBS) ? '' : revParseCard()}<section class="card"><h3>원문</h3><div class="cue-text rev-raw">${esc(e.text)}</div></section>`;
  }
  cueBind(revCueKey(e.number), e.sheet);
  const tab = REV_TABS.some(([k]) => k === S.revTab) ? S.revTab : 'text';
  const badge = { write: (e.blind_texts || []).length ? '<span class="chip warn">가려 읽기</span>' : (e.takes || []).length ? `<span class="chip finalized">${e.takes.length}판</span>` : '<span class="chip">아직</span>' };
  const tabs = `<div class="tabs" role="tablist" aria-label="${e.number}화 보기">${REV_TABS.map(([k, label]) => `<button type="button" role="tab" id="rev-tab-${k}" aria-controls="rev-panel" aria-selected="${k === tab}"${k === tab ? '' : ' tabindex="-1"'} data-action="revTab" data-arg="${k}">${label}${badge[k] ? ` ${badge[k]}` : ''}</button>`).join('')}</div>`;
  const body = tab === 'plot' ? `<div class="rev-two">${revPlotCard(e)}${revBoardCard(e)}</div>` : tab === 'write' ? revWriteTab(e) : revTextTab(e);
  return `${redo}${head}${tabs}<div role="tabpanel" id="rev-panel" aria-labelledby="rev-tab-${tab}" class="rev-panel">${body}</div>`;
}

/** 원문 · 큐 탭: 원문을 큐 경계로 나눈 칸 + 옆에 진행 막대와 큐 목록. */
function revTextTab(e) {
  const orig = (e.scores || []).find((s) => s.condition === 'original');
  const notes = [];
  if (e.missing.length) notes.push(`${e.missing.join(', ')}번 큐는 시작 문장을 원문에서 못 찾았어요. 앞 큐에 붙여 쟀어요.`);
  if (e.dropped.length) notes.push(`원문에 없어 뺀 핵심 대사: ${e.dropped.map((x) => `«${esc(x)}»`).join(' · ')}`);
  if (orig && orig.tempo_order === false) notes.push('빠른 큐의 문장이 느린 큐보다 길어요. 템포 표시가 원문과 어긋나요.');
  return `${notes.map((x) => `<div class="note warn small">${x}</div>`).join('')}
    <div class="rev-cols"><section class="card rev-src" aria-label="${e.number}화 원문"><div class="between"><h3>원문</h3><span class="small">왼쪽 띠를 누르면 그 큐를 열어요</span></div>${revText(e)}</section>
    <aside class="rev-side"><section class="card tight">${cueScore(cueEd().draft, false)}</section>${revCueCard(e, orig)}</aside></div>`;
}

/** 원문을 큐 경계로 나눠 그린다. 고른 큐(S.revSel)는 밝힌다. 경계가 큐 수와 맞지 않으면(작가가 큐를 더하거나 뺐다) 원문만. */
function revText(e) {
  if (!e.bounds_ok) return `<div class="note warn small">큐 수가 바뀌어 원문 경계를 지웠어요. 다시 역설계하면 새로 재요.</div><div class="cue-text rev-raw">${esc(e.text)}</div>`;
  return `<div class="rev-text">${revSegments(e.text, e.bounds).map((s) => {
    const c = s.cue ? e.sheet.cues[s.cue - 1] : null;
    const body = `<div class="cue-text">${esc(e.text.slice(s.start, s.end).replace(/^\n+|\n+$/g, ''))}</div>`;
    if (!c) return `<div class="rev-seg free"><span></span>${body}</div>`;
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
function revWriteTab(e) {
  const L = S.revLab;
  const takes = e.takes || [];
  const parts = [];
  if (e.blind_texts.length) {
    parts.push(`<section class="card"><h3>가려 읽기</h3><div class="note info">어느 쪽이 원문인지 숨겼어요. 둘 다 읽고 더 이어 읽고 싶은 쪽을 고르세요. 고르면 어느 쪽인지와 지표를 보여 드려요.</div>
      <div class="rev-blind">${e.blind_texts.map((x, i) => `<div class="rev-blind-col"><h4>${i + 1}번</h4><div class="cue-text rev-read">${esc(x)}</div>
        <button type="button" class="btn" data-action="revPick" data-arg="${i + 1}">${i + 1}번이 더 읽고 싶어요</button></div>`).join('')}</div>
      <div class="row"><button type="button" class="btn ghost" data-action="revPick" data-arg="0">고르지 않고 결과 보기</button></div></section>`);
  } else if (e.picked) {
    const what = (x) => (x === 'original' ? '원문' : (takes.find((t) => t.mode === e.blind_take) || { label: '되돌려 쓴 글' }).label);
    parts.push(`<div class="note ok">가려 읽기: ${e.picked === 'skip' ? '고르지 않았어요.' : `<strong>${esc(what(e.picked))}</strong>을 골랐어요. ${e.blind.map((x, i) => `${i + 1}번은 ${esc(what(x))}`).join(', ')}이었어요.`}</div>`);
  }
  if (!e.blind_texts.length && (e.scores || []).length > 1) {  // 가려 읽는 동안에는 지표(글자 수)를 숨긴다
    const m = revMetricRows(e.scores);
    parts.push(`<section class="card"><div class="between"><h3>지표 견주기</h3><span class="small">원문과 ${Math.round(REV_FAR * 100)}% 넘게 다른 값은 굵게 보여요</span></div>
      <div class="rev-scroll"><table class="sw-table rev-mx"><thead><tr><th></th>${m.heads.map((h) => `<th>${esc(h.label)}${h.stale ? ' <span class="chip">시트 바뀜</span>' : ''}</th>`).join('')}</tr></thead>
      <tbody>${m.rows.map((r) => `<tr><td>${esc(r.label)}</td>${r.cells.map((c) => `<td${c.far ? ' class="rev-far"' : ''}>${esc(c.text)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
      <p class="small">핵심 대사는 큐 시트의 대사가 글자 그대로 들어간 수예요. 템포는 원문만 큐 경계로 나눠 재요 (빠른 큐의 문장이 느린 큐보다 짧은지).</p></section>`);
  }
  const shown = takes.filter((t) => t.text);
  if (!e.blind_texts.length && shown.length) {
    const t = shown.find((x) => x.mode === S.revRead) || shown[0];
    const seg = shown.length > 1 ? `<div class="seg" role="group" aria-label="오른쪽에 둘 판">${shown.map((x) => `<button type="button" aria-pressed="${x === t}" data-action="revRead" data-arg="${x.mode}">${x.mode === 'style' ? '문체 넣고' : '문체 없이'}</button>`).join('')}</div>` : '';
    parts.push(`<section class="card"><div class="between"><h3>나란히 읽기</h3>${seg}</div>
      <div class="rev-blind"><div class="rev-blind-col"><div class="small"><strong>원문</strong> · ${e.chars.toLocaleString()}자</div><div class="cue-text rev-read">${esc(e.text)}</div></div>
        <div class="rev-blind-col"><div class="small"><strong>${esc(t.label)}</strong> · ${t.text.length.toLocaleString()}자 · ${esc(t.model)} · ${esc(fmtDateTime(t.at))}${t.stale ? ' · 그 뒤 큐 시트를 고쳤어요' : ''}</div><div class="cue-text rev-read">${esc(t.text)}</div></div></div></section>`);
  }
  const style = !!(S.revStyle && L.style);
  const est = revEst('write', [e.number], style);
  const busy = !!revRunning();
  const again = takes.some((x) => x.mode === (style ? 'style' : 'plain'));
  parts.push(`<section class="card${takes.length ? ' tight' : ''}"><h3>${takes.length ? '다시 쓰기' : '되돌려 쓰기'}</h3>
    <p class="small">역설계한 플롯 · 스토리보드 · 큐 시트와 인물 · 관계 · 호칭 · 배경만 주고(이 화 원문 문장은 주지 않음) 같은 화를 써요. 앞 화는 원문을 반영한 화로 둬요. 문체를 넣은 판과 넣지 않은 판을 하나씩 남기고, 같은 판을 다시 쓰면 바꾸고 가려 읽기를 새로 해요.</p>
    ${cueEd().dirty ? '<div class="note warn small">저장하지 않은 큐 시트 고침이 있어요. 되돌려 쓰기는 저장한 큐 시트로 해요.</div>' : ''}
    <div class="row"><label class="check-row small"><input type="checkbox" data-rev-style="1"${style ? ' checked' : ''}${L.style ? '' : ' disabled'}><span>문체 프로필 넣기${L.style ? '' : ' (문체 프로필을 먼저 만드세요)'}</span></label>
      <button type="button" class="btn" data-action="revWrite" data-arg="${e.number}"${est && !busy ? '' : ' disabled'}>${revCost(`${again ? '다시 쓰기' : '되돌려 쓰기 시작'}${style ? ' (문체 넣고)' : ''}`, est)}</button></div>
    ${revEstErr('write', [e.number], style) ? `<div class="note err small">비용을 재지 못했어요: ${esc(revEstErr('write', [e.number], style))}</div>` : ''}
    ${revEstHtml(est)}</section>`);
  return parts.join('');
}

document.addEventListener('input', (e) => {
  const d = e.target.dataset || {};
  if (d.revNew) {
    S.revDraft[d.revNew] = e.target.value;
    const box = document.getElementById('rev-preview');
    if (box) box.innerHTML = revPreviewHtml();
    const count = document.getElementById('rev-count');
    if (count) count.textContent = S.revDraft.text ? `· ${S.revDraft.text.length.toLocaleString()}자` : '';
    const num = document.getElementById('rev-first');
    if (num) num.placeholder = revGuessFirst(S.revDraft.title, S.revDraft.text);
    const btn = document.querySelector('[data-action="revCreate"]');
    if (btn) btn.disabled = !!revPreview(S.revDraft.text, S.rev).errs.length;
  }
});

document.addEventListener('change', (e) => {
  const d = e.target.dataset || {};
  if (d.revStyle !== undefined) { S.revStyle = e.target.checked; render(); return; }
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
  return `${(j.result || {}).episode || ''}화 되돌려 쓰기${(j.result || {}).style ? '(문체 넣음)' : ''}가 끝났어요. 가려 읽고 골라 보세요.`;
};
JOB_DONE_MSG.rev_style = (j) => {
  revJobDone(j);
  return '문체 프로필을 역설계했어요. 되돌려 쓰기에서 문체 프로필 넣기를 고를 수 있어요.';
};

/** 실험 안에서 옮긴다: 같은 화면이면 다시 그리고, 다른 화 · 칸이면 주소를 바꾼다 (route 가 revLoad 를 부른다). */
function revNav(part) {
  const to = `#/revlab/${S.revLab.id}/${part}`;
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
    if (text.trim() && S.revLab.done && !confirm('글을 바꾸면 다시 나누고 역설계 결과를 모두 지워요. 바꿀까요?')) return;
    const id = S.revLab.id;
    await run('저장하는 중', async () => {
      await api('PUT', `/revlab/${id}`, { title, text: text.trim() ? text : null, first });
      S.revLab = null;
      await revLoad(id, null);
      S.revEdit = false;
    });
  },
  async revDelete() {
    if (!confirm(`'${S.revLab.title || `실험 ${S.revLab.id}`}' 실험을 지울까요? 넣은 글과 역설계 결과가 모두 사라져요.`)) return;
    await run('지우는 중', async () => {
      await api('DELETE', `/revlab/${S.revLab.id}`);
      S.revLab = null;
      location.hash = `#/revlab`;
    });
  },
  /** 역설계한 화도 고를 수 있는 역설계 카드를 열고 닫는다. 열면 지금 화를 고른다. */
  revRedo() {
    S.revRedo = !S.revRedo;
    if (S.revRedo) { S.revPick = new Set([S.revEp]); S.revPane = null; S.focusTarget = '#app .rev-picks input'; }
    if (S.revPane) revNav(S.revEp); else render();
  },
  revStyleRun() {
    if (S.revLab.style && !confirm('지금 문체 프로필을 새로 만든 것으로 바꿀까요?')) return;
    revStartJob('style');
  },
  revParse() {
    S.revRedo = false;
    revStartJob('parse', { episodes: [...S.revPick].sort((a, b) => a - b) });
  },
  revWrite(n) {
    const k = Number(n) || S.revEp;
    if ((S.cueEdits[revCueKey(k)] || {}).dirty && !confirm('저장하지 않은 큐 시트 고침이 있어요. 저장한 큐 시트로 되돌려 쓸까요?')) return;
    revStartJob('write', { episodes: [k], style: !!(S.revStyle && S.revLab.style) });
  },
  async revPick(k) {
    await run('고르는 중', async () => {
      S.revLab = await api('POST', `/revlab/${S.revLab.id}/episodes/${S.revEp}/pick`, { choice: Number(k) });
    });
  },
  revTab(k) { S.revTab = k; render(); },
  revRead(k) { S.revRead = k; render(); },
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
  revTocToggle() {
    const t = document.getElementById('rev-toc');
    if (!t) return;
    const on = t.classList.toggle('open');
    t.querySelector('.rev-toc-now').setAttribute('aria-expanded', String(on));
  },
  revCueGo(k) {
    S.revSel = S.revSel === k ? 0 : k;
    render();
    const el = document.getElementById(`rev-cue-${k}`);
    if (el && S.revSel) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  },
});

// 좁은 칸의 목차 창은 바깥을 누르거나 Esc 로 닫는다
document.addEventListener('click', (e) => {
  const t = document.getElementById('rev-toc');
  if (t && t.classList.contains('open') && !t.contains(e.target)) actions.revTocToggle();
});
document.addEventListener('keydown', (e) => {
  const t = document.getElementById('rev-toc');
  if (e.key === 'Escape' && t && t.classList.contains('open')) { actions.revTocToggle(); t.querySelector('.rev-toc-now').focus(); }
});

(() => {
  const css = `
.rev-wrap { container: rev / inline-size; }
.rev-doc { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 28px; align-items: start; }
.rev-main { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.rev-toc { position: sticky; top: 16px; z-index: 4; }
.rev-toc-now { display: none; }
.rev-toc-list { display: flex; flex-direction: column; gap: 2px; }
.rev-toc-h { padding: 14px 10px 4px; font-size: 0.75rem; color: var(--muted); }
.rev-toc-h:first-child { padding-top: 0; }
.rev-toc-item { min-height: 38px; padding: 0 10px; border: 1px solid transparent; border-radius: 8px; background: transparent; color: var(--text-2); font: inherit; font-weight: 500; text-align: left; text-decoration: none; display: flex; align-items: center; gap: 8px; cursor: pointer; }
.rev-toc-item:hover { background: var(--surface); color: var(--text); }
.rev-toc-item .tl { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rev-toc-item .st { margin-left: auto; padding-left: 6px; font-size: 0.75rem; color: var(--muted); font-weight: 500; white-space: nowrap; }
.rev-toc-item[aria-current] { background: var(--accent-soft); color: var(--accent-ink); font-weight: 700; }
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
.rev-meter { margin: 6px 10px 0; height: 6px; border-radius: 3px; background: var(--chip); overflow: hidden; }
.rev-meter.big { margin: 0; height: 8px; }
.rev-meter > i { display: block; height: 100%; background: var(--accent); }
.rev-how { margin: 0; padding: 0 10px 0 28px; display: flex; flex-direction: column; gap: 6px; color: var(--text-2); }
.rev-how-note { margin: 8px 0 0; padding: 0 10px; }
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
.rev-picks { gap: 4px 14px; }
.rev-pick { padding: 0; border: none; }
.rev-ep-head h2 { font-size: 1.125rem; }
.rev-panel { display: flex; flex-direction: column; gap: 16px; }
.rev-cols { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; }
.rev-src { flex: 999 1 440px; min-width: 0; gap: 6px; }
.rev-side { flex: 1 1 320px; min-width: 0; display: flex; flex-direction: column; gap: 16px; position: sticky; top: 16px; max-height: calc(100vh - 32px); overflow-y: auto; }
.rev-raw { max-height: 70vh; overflow-y: auto; }
.rev-seg { display: grid; grid-template-columns: 84px minmax(0, 1fr); gap: 12px; padding: 4px 8px 4px 0; border: 1px solid transparent; border-radius: 8px; scroll-margin-top: 80px; }
.rev-seg.sel { background: var(--sel-bg); border-color: var(--sel-line); }
.rev-seg .cue-text { line-height: 1.9; }
.rev-gut { align-self: stretch; min-height: 44px; display: flex; flex-direction: column; align-items: flex-start; gap: 4px; padding: 2px 0 2px 8px; border: none; border-left: 4px solid var(--line-strong); border-radius: 0; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.rev-gut:hover { background: var(--bg); }
.rev-gut.fn-T { border-left-color: var(--act-1-ink); }
.rev-gut.fn-S { border-left-color: var(--act-2-ink); }
.rev-gut.fn-D { border-left-color: var(--act-4-ink); }
.rev-fn { display: inline-flex; align-items: center; justify-content: center; min-width: 24px; height: 22px; padding: 0 4px; border-radius: 6px; background: var(--chip); font-size: 0.75rem; font-weight: 800; }
.rev-fn.T { background: var(--act-1); color: var(--act-1-ink); }
.rev-fn.S { background: var(--act-2); color: var(--act-2-ink); }
.rev-fn.D { background: var(--act-4); color: var(--act-4-ink); }
.rev-side .cue-bars { height: 72px; }
.rev-cues { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.rev-cue { border: 1px solid transparent; border-radius: 8px; }
.rev-cue.sel { background: var(--sel-bg); border-color: var(--sel-line); }
.rev-cue-btn { width: 100%; min-height: 44px; display: grid; grid-template-columns: 28px 20px minmax(0, 1fr); gap: 4px 8px; align-items: center; padding: 6px 8px; border: none; border-radius: 8px; background: transparent; color: inherit; font: inherit; font-size: 0.8125rem; text-align: left; cursor: pointer; }
.rev-cue-btn:hover { background: var(--bg); }
.rev-cue-btn .meta { grid-column: 3; font-size: 0.75rem; color: var(--muted); }
.rev-cue-more { padding: 0 10px 10px 36px; }
.rev-kv { display: grid; grid-template-columns: 72px minmax(0, 1fr); gap: 4px 12px; margin: 0; font-size: 0.8125rem; }
.rev-kv dt { color: var(--muted); }
.rev-kv dd { margin: 0; }
.rev-ul { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 4px; }
.rev-two { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; align-items: start; }
.rev-blind { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; }
.rev-blind-col { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.rev-read { max-height: 60vh; overflow-y: auto; padding: 12px 14px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg); }
.rev-scroll { overflow-x: auto; }
.rev-mx td, .rev-mx th { white-space: nowrap; }
.rev-mx .rev-far { color: var(--amber-ink); font-weight: 700; }
.rev-mx-ep th { padding-top: 14px; text-align: left; }
.rev-est summary { cursor: pointer; min-height: 32px; display: flex; align-items: center; }
.rev-run h2 { font-size: 1rem; }
.rev-run-rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.rev-run-row { min-height: 44px; display: grid; grid-template-columns: 14px minmax(0, 1fr) auto auto; gap: 10px; align-items: center; padding: 0 8px; border-radius: 8px; }
.rev-run-row.run { background: var(--sel-bg); }
.rev-run-row.wait .tl { color: var(--muted); }
@container rev (max-width: 1040px) {
  .rev-side { position: static; max-height: none; overflow: visible; }
}
@container rev (max-width: 720px) {
  .rev-doc { grid-template-columns: minmax(0, 1fr); gap: 12px; }
  .rev-toc { top: 0; margin: 0 -2px; padding: 8px 2px; background: var(--bg); }
  .rev-toc-now { display: flex; width: 100%; justify-content: space-between; }
  .rev-toc-list { display: none; position: absolute; left: 0; right: 0; top: calc(100% - 4px); padding: 8px; border-radius: 12px; background: var(--surface); box-shadow: 0 8px 28px rgba(0,0,0,0.18); max-height: 70vh; overflow-y: auto; }
  .rev-toc.open .rev-toc-list { display: flex; }
  .rev-toc-item { min-height: 44px; }
  .rev-blind { grid-template-columns: minmax(0, 1fr); }
  .rev-seg { grid-template-columns: 52px minmax(0, 1fr); gap: 8px; }
  .rev-gut-t { display: none; }
  .rev-cue-more { padding-left: 10px; }
  .rev-paste textarea { min-height: 240px; }
}
@media (forced-colors: active) { .rev-toc-item[aria-current], .rev-seg.sel, .rev-cue.sel { outline: 2px solid Highlight; } }
`;
  const el = document.createElement('style');
  el.textContent = css;
  document.head.appendChild(el);
})();

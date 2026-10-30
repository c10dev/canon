/* 역설계 실험 화면(서버 revlab.py, 작품 밖 화면 #/revlab[/<실험 번호>[/<화>]], 작품 목록 · 사이드바 ⋯ 메뉴 · 작품 사이드바 실험 묶음에서 들어온다).
   작가가 넣은 소설을 거꾸로 화별 플롯 · 스토리보드 · 큐 시트 · 이야기 줄기로 풀고, 그 큐 시트로 같은 화를 다시 써서(되돌려 쓰기) 원문과 견준다.
   실험은 작품 밖(<CANON_HOME>/.revlab)에 두고 작품을 열지 않고 쓴다. AI 작업은 POST /revlab/<번호>/jobs (작업 rev_parse · rev_write · rev_style,
   ep 가 실험 번호, project 는 REV_JOBS). 사용량은 작품 없이 잡히고 모델은 전체 단계 설정을 쓴다.
   app.js 의 S, actions, api, run, render, header, esc, toast, josa, showError, renderJobs, pollJobs, jobBtn, jobFor, JOB_PAGES, JOB_DONE_MSG, fmtDateTime 과
   cue.js 의 cueBind · cueEd · cueScore · cueEditor · cueLabel · cueUsd · cuePct · cueYes · CUE_COLORS 를 쓴다 (큐 시트 열쇠는 'rev:<화>').
   revSplit · revGuessFirst · revSegments · revPreview 는 DOM 없는 순수 함수 (revSplit · revGuessFirst 는 revlab.split · guess_first 와 같은 규칙,
   tests/test_revlab.py). */
'use strict';

Object.assign(S, {
  rev: null,       // 서버 값 { labs, splits, max_episodes, max_chars, min_chars, … 큐 칸 이름 }
  revLab: null,    // 고른 실험 (revlab.view)
  revEp: null,     // 보는 화 번호
  revDraft: { title: '', text: '', first: '' },  // 새 실험 칸 (first 가 비면 짐작한 번호)
  revPick: null,   // 역설계할 화 Set
  revEst: null,    // { key, data } 비용 추정 (key 가 지금 고른 것과 다르면 다시 추정)
  revSel: 0,       // 원문에서 밝힌 큐 번호 (1부터)
  revEdit: false,  // 실험 글 고치기 칸을 열었는지
  revStyle: false, // 되돌려 쓰기에 문체 프로필을 넣을지
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
  const want = Number(n) || null;
  if (S.revLab && !S.revLab.error) {
    const nums = S.revLab.items.map((e) => e.number);
    if (want && nums.includes(want)) S.revEp = want;
    else if (!nums.includes(S.revEp)) S.revEp = nums[0];
  }
}

async function revFetch(id) {
  const old = S.revLab && S.revLab.id;
  S.revLab = await api('GET', `/revlab/${id}`).catch((e) => ({ error: e.message, id }));
  if (S.revLab.error) return;
  for (const e of S.revLab.items) S.cueEdits[revCueKey(e.number)] = { draft: e.sheet ? structuredClone(e.sheet) : null, dirty: false };
  if (old !== id) {
    S.revPick = new Set(S.revLab.items.filter((e) => !e.sheet && e.chars >= S.rev.min_chars).map((e) => e.number));
    S.revSel = 0; S.revEdit = false;
  }
  S.revEst = null;
}

function viewRev() {
  const head = header('본편과 분리', '역설계 실험',
    '내가 넣은 소설을 거꾸로 화별 플롯 · 이야기 줄기 · 스토리보드 · 큐 시트로 풀어 봐요. 그 큐 시트로 같은 화를 다시 써서 Canon의 표현이 사람 글의 구조를 얼마나 담는지 견줘요. 작품 데이터는 바꾸지 않아요.');
  const d = S.rev;
  if (!d) return `${head}<div class="note plain">불러오는 중…</div>`;
  if (d.error) return `${head}<div class="note err">${esc(d.error)}</div>`;
  if (!S.revLab) return `${head}${revIntro()}${revNewCard()}${revList()}`;
  if (S.revLab.error) return `${head}<div class="note err">${esc(S.revLab.error)}</div><p><a href="#/revlab">실험 목록으로</a></p>`;
  return `${head}${revLabHead()}${revParseCard()}${revContextCard()}${revStyleCard()}${revLinesCard()}${revEpisode()}`;
}

function revIntro() {
  return `<section class="card"><h2>어떻게 하나요</h2>
    <ol class="small" style="padding-left:18px">
      <li>소설 글을 붙여 넣어요. 'n화' 제목 줄이 있으면 화로 나누고, 없으면 '===' 줄이나 빈 줄 세 개로 나눠요. 직접 나누려면 화 사이에 <code>===</code> 한 줄을 넣으세요.</li>
      <li>역설계: AI가 화마다 플롯 · 스토리보드 · 큐 시트를 적어요. 큐 경계는 원문 문장을 그대로 인용해 정하고, 큐 글자 수는 Canon이 원문에서 재요. 핵심 대사는 원문에 글자 그대로 있는 것만 남겨요.</li>
      <li>되돌려 쓰기: 역설계한 큐 시트로 같은 화를 다시 써서, 원문과 가려 읽고 지표를 견줘요.</li>
    </ol>
    <p class="small">넣은 글은 이 컴퓨터의 실험 폴더(.revlab)에만 저장해요. 역설계와 되돌려 쓰기는 실제 AI를 불러 비용이 들어요. 누르기 전에 비용 추정을 보여 드려요.</p></section>`;
}

const revDraftFirst = () => Number(S.revDraft.first) || revGuessFirst(S.revDraft.title, S.revDraft.text);

function revPreviewHtml() {
  const v = revPreview(S.revDraft.text, S.rev, revDraftFirst());
  if (!S.revDraft.text.trim()) return '<div class="small">붙여 넣으면 어떻게 나뉘는지 여기 보여요.</div>';
  const eps = v.eps.map((e) => `<li>${e.head ? esc(e.head) : `${e.n}화`} · ${e.chars.toLocaleString()}자${e.short ? ' <span class="ab-pill">짧음</span>' : ''}</li>`).join('');
  return `<div class="small"><strong>${v.eps.length}화</strong>로 나뉘어요 (규칙: ${esc(v.label)})</div>
    <ol class="small rev-prev">${eps}</ol>
    ${v.errs.map((x) => `<div class="note err small">${esc(x)}</div>`).join('')}${v.notes.map((x) => `<div class="small">${esc(x)}</div>`).join('')}`;
}

function revNewCard() {
  const ok = !revPreview(S.revDraft.text, S.rev).errs.length;
  return `<section class="card"><h2>새 실험</h2>
    <div class="field"><label for="rev-title">이름</label><input id="rev-title" data-rev-new="title" value="${esc(S.revDraft.title)}" placeholder="예: 등대지기 1~3화"></div>
    <div class="field"><label for="rev-first">첫 화 번호 <span class="small">(비우면 제목 줄이나 이름의 'n화'에서 짐작해요)</span></label>
      <input id="rev-first" type="number" min="1" max="9999" style="width:120px" data-rev-new="first" value="${esc(S.revDraft.first)}" placeholder="${revDraftFirst()}"></div>
    <div class="field"><label for="rev-text">소설 글</label><textarea id="rev-text" rows="14" data-rev-new="text" placeholder="여기에 붙여 넣으세요">${esc(S.revDraft.text)}</textarea></div>
    <div id="rev-preview">${revPreviewHtml()}</div>
    <div class="row"><button type="button" class="btn primary" data-action="revCreate"${ok ? '' : ' disabled'}>실험 만들기 (나누기만, AI 없이)</button></div></section>`;
}

function revList() {
  const labs = S.rev.labs || [];
  if (!labs.length) return '';
  return `<section class="card"><h2>지난 실험</h2><ul class="small rev-labs">${labs.map((x) => `<li><a href="#/revlab/${x.id}">${esc(x.title || `실험 ${x.id}`)}</a>
    · ${x.episodes}화 · ${x.chars.toLocaleString()}자 · 역설계 ${x.done}/${x.episodes}${x.rewrites ? ` · 되돌려 쓴 화 ${x.rewrites}` : ''} · ${esc(fmtDateTime(x.created))}</li>`).join('')}</ul></section>`;
}

function revLabHead() {
  const L = S.revLab;
  const edit = S.revEdit ? `<div class="field"><label for="rev-etitle">이름</label><input id="rev-etitle" data-rev-edit="title" value="${esc(L.title)}"></div>
      <div class="field"><label for="rev-efirst">첫 화 번호</label><input id="rev-efirst" type="number" min="1" max="9999" style="width:120px" data-rev-edit="first" value="${L.first}"></div>
      <div class="field"><label for="rev-etext">글 <span class="small">(비우면 글은 그대로 두고 이름만 바꿔요)</span></label><textarea id="rev-etext" rows="8" data-rev-edit="text" placeholder="새 글을 붙여 넣으면 다시 나누고 역설계 결과를 모두 지워요"></textarea></div>
      <div class="row"><button type="button" class="btn small primary" data-action="revSaveEdit">저장</button><button type="button" class="btn small ghost" data-action="revEditToggle">닫기</button></div>` : '';
  return `<section class="card"><div class="between"><h2>${esc(L.title || `실험 ${L.id}`)} <span class="small">${L.first}~${L.first + L.episodes - 1}화 · ${L.chars.toLocaleString()}자 · 나눈 규칙: ${esc(L.split_label)}</span></h2>
      <span class="row" style="gap:6px"><a class="btn small ghost" href="#/revlab">목록</a><button type="button" class="btn small" data-action="revEditToggle">글 · 이름 고치기</button>
      <button type="button" class="btn small ghost" data-action="revDelete">지우기</button></span></div>
    ${L.preface ? `<div class="small">앞머리(역설계하지 않음): ${esc(L.preface.slice(0, 120))}</div>` : ''}
    ${L.first <= 3 ? '<div class="note warn small">1~3화로 잡혀 되돌려 쓰기에 초반 규칙이 붙어요. 소설 중간이면 \'글 · 이름 고치기\'에서 첫 화 번호를 바꾸세요.</div>' : ''}
    ${edit}</section>`;
}

/** 비용 추정 표 (cue.js 실험 카드와 같은 모양). */
function revEstHtml(est) {
  if (!est) return '';
  return `<div style="overflow-x:auto"><table class="sw-table"><thead><tr><th>요청</th><th>입력 토큰</th><th>출력 토큰</th><th>비용</th></tr></thead><tbody>
    ${est.rows.map((r) => `<tr><td>${esc(r.label)}</td><td>${r.input_tokens.toLocaleString()}</td><td>${r.output_tokens.toLocaleString()}</td><td>${cueUsd(r.usd)}</td></tr>`).join('')}
    <tr><th>합 (요청 ${est.calls}번)</th><td></td><td></td><th>${cueUsd(est.usd)}</th></tr></tbody></table></div>
    <div class="small">${esc(est.model)} 가격표 기준 · ${esc(est.note)}</div>`;
}

const revEstKey = (kind, eps) => `${kind}:${[...eps].sort((a, b) => a - b).join(',')}`;  // kind: parse · write · write-style · style
const revEstFor = (kind, eps) => (S.revEst && S.revEst.key === revEstKey(kind, eps) ? S.revEst.data : null);

function revParseCard() {
  const L = S.revLab;
  const pick = S.revPick || new Set();
  const boxes = L.items.map((e) => {
    const off = e.chars < S.rev.min_chars;
    return `<label class="row small" style="gap:6px"><input type="checkbox" data-rev-pick="${e.number}"${pick.has(e.number) && !off ? ' checked' : ''}${off ? ' disabled' : ''}>${e.number}화${e.sheet ? ' ✓' : ''}${off ? ' (짧음)' : ''}</label>`;
  }).join('');
  const eps = [...pick];
  const est = revEstFor('parse', eps);
  const go = jobBtn('rev_parse', L.id, '역설계 시작', REV_JOBS);
  const redo = eps.some((n) => (revItem(n) || {}).sheet);
  return `<section class="card"><h2>역설계</h2>
    <div class="row" style="gap:14px;flex-wrap:wrap">${boxes}</div>
    <p class="small">고른 화를 앞에서부터 차례로 풀어요. 앞 화 결과(인물 · 줄거리 · 끝 부분)가 다음 화 요청에 들어가요. 모든 화를 풀면 이야기 줄기를 한 번 더 물어요.</p>
    ${redo ? '<div class="note warn small">이미 역설계한 화를 다시 풀면 그 화의 큐 시트 고침과 되돌려 쓴 글이 사라져요.</div>' : ''}
    <div class="row"><button type="button" class="btn small" data-action="revEstimate" data-arg="parse"${eps.length ? '' : ' disabled'}>비용 추정</button></div>
    ${revEstHtml(est)}
    <div class="row"><button type="button" class="btn primary" data-action="revParse"${eps.length && est ? '' : ' disabled'}${go.attr}>${go.label}</button>${est ? '' : '<span class="small">비용 추정을 먼저 보세요.</span>'}</div></section>`;
}

/** 인물 · 관계 · 배경: 되돌려 쓰기 사본의 작품 설정이 되는 것 (revlab.world). 마지막으로 역설계한 화까지 읽은 값. */
function revContextCard() {
  const L = S.revLab;
  if (!L.cast.length) return '';
  const c = (L.context || [])[0] || { setting: '', facts: [], ties: [], addresses: [] };
  const li = (xs) => `<ul class="small" style="padding-left:18px;margin:4px 0">${xs.join('')}</ul>`;
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
  if (!L.done) return '';
  const st = L.style;
  const est = revEstFor('style', []);
  const go = jobBtn('rev_style', L.id, st ? '문체 다시 역설계' : '문체 역설계 시작', REV_JOBS);
  const kv = (k, v) => (v ? `<dt>${k}</dt><dd>${esc(v)}</dd>` : '');
  const body = st ? `<dl class="ab-kv small">${kv('시점', st.narration_pov)}${kv('시제', st.tense)}${kv('문장 리듬', st.sentence_rhythm)}${kv('묘사 밀도', st.description_density)}
      ${kv('대사 비중', st.dialogue_ratio)}${kv('대사 방식', st.dialogue_style)}${kv('속생각', st.inner_monologue)}${kv('속도', st.pacing)}${kv('장면 전환', st.scene_transition)}${kv('어휘', st.vocabulary)}</dl>
      ${(st.markers || []).length ? `<div class="small">표지: ${st.markers.map((m) => `«${esc(m.text)}»`).join(' · ')}</div>` : ''}
      <div class="small">${esc(L.style_model)} · ${esc(fmtDateTime(L.style_at))}</div>`
    : '<p class="small">원문 앞부분으로 문체 프로필(시점 · 문장 리듬 · 대사 방식 · 표지)을 만들어요. 원문을 베끼지 않게 예시 문단은 넣지 않아요. 되돌려 쓰기에서 문체를 넣은 판과 넣지 않은 판을 견주면 차이가 구조에서 오는지 문체에서 오는지 갈라 볼 수 있어요.</p>';
  return `<section class="card"><h2>문체 프로필</h2>${body}
    <div class="row"><button type="button" class="btn small" data-action="revEstimate" data-arg="style">비용 추정</button>
      <button type="button" class="btn small${st ? '' : ' primary'}" data-action="revStyleRun"${est ? '' : ' disabled'}${go.attr}>${go.label}</button>${est ? '' : '<span class="small">비용 추정을 먼저 보세요.</span>'}</div>
    ${revEstHtml(est)}</section>`;
}

function revLinesCard() {
  const L = S.revLab;
  if (L.items.length < 2) return '';
  if (!L.lines_at) return `<section class="card"><h2>이야기 줄기</h2><div class="small">모든 화를 역설계하면 메인 줄기와 서브 줄기를 찾아요.</div></section>`;
  const span = (x) => (x.branch_ep ? `${x.branch_ep}${x.join_ep ? `~${x.join_ep}` : '~'}화` : '화 없음');
  const on = (id) => L.items.filter((e) => e.plot && (e.plot.storyline === id || e.plot.threads.includes(id))).map((e) => `${e.number}${e.plot.storyline === id ? '' : '(끼어듦)'}`);
  return `<section class="card"><h2>이야기 줄기 <span class="small">${esc(fmtDateTime(L.lines_at))}</span></h2>
    <div class="small"><strong>메인</strong> — ${esc(L.main || '정하지 않음')}</div>
    ${L.lines.length ? `<ul class="small" style="padding-left:18px">${L.lines.map((x) => `<li><strong>${esc(x.title || x.id)}</strong> · ${esc(x.kind)} · ${span(x)}${x.focus.length ? ` · ${esc(x.focus.join(', '))}` : ''}
      ${x.goal ? `<br>${esc(x.goal)}` : ''}${on(x.id).length ? `<br>화: ${on(x.id).join(', ')}` : ''}${x.rejoin ? `<br>합류하며 남긴 것: ${esc(x.rejoin)}` : ''}</li>`).join('')}</ul>` : '<div class="small">메인 밖 줄기는 찾지 못했어요.</div>'}</section>`;
}

function revTabs() {
  const tabs = S.revLab.items.map((e) => `<a role="tab" class="btn small${e.number === S.revEp ? ' on' : ' ghost'}" aria-selected="${e.number === S.revEp}" href="#/revlab/${S.revLab.id}/${e.number}">${e.number}화${e.sheet ? ' ✓' : ''}</a>`).join('');
  return `<div class="row rev-tabs" role="tablist" aria-label="화">${tabs}</div>`;
}

function revEpisode() {
  const e = revItem(S.revEp);
  if (!e) return '';
  if (!e.sheet) {
    return `${revTabs()}<section class="card"><h2>${e.number}화${e.head ? ` · ${esc(e.head)}` : ''} <span class="small">${e.chars.toLocaleString()}자 · 역설계 전</span></h2>
      <div class="cue-text rev-text">${esc(e.text)}</div></section>`;
  }
  cueBind(revCueKey(e.number), e.sheet);
  return `${revTabs()}<div class="rev-grid">
      <section class="card rev-left"><h2>${e.number}화 원문 <span class="small">${e.chars.toLocaleString()}자 · 큐 ${e.sheet.cues.length}개</span></h2>${revText(e)}</section>
      <div class="rev-right">${revPlotCard(e)}${revBoardCard(e)}${revCueCard(e)}</div>
    </div>${revWriteCard(e)}`;
}

/** 원문을 큐 경계로 나눠 그린다. 고른 큐(S.revSel)는 밝힌다. 경계가 큐 수와 맞지 않으면(작가가 큐를 더하거나 뺐다) 원문만. */
function revText(e) {
  if (!e.bounds_ok) return `<div class="note warn small">큐 수가 바뀌어 원문 경계를 지웠어요. 다시 역설계하면 새로 재요.</div><div class="cue-text rev-text">${esc(e.text)}</div>`;
  const segs = revSegments(e.text, e.bounds).map((s) => {
    const c = s.cue ? e.sheet.cues[s.cue - 1] : null;
    const body = esc(e.text.slice(s.start, s.end));
    if (!c) return `<div class="cue-text">${body}</div>`;
    return `<div class="rev-seg${S.revSel === s.cue ? ' sel' : ''}" id="rev-cue-${s.cue}" style="border-color:${CUE_COLORS[c.function] || 'var(--line-strong)'}">
      <div class="small rev-seg-head">${s.cue}번 큐 · ${esc(c.function)} · 긴장 ${c.tension} · ${(s.end - s.start).toLocaleString()}자</div><div class="cue-text">${body}</div></div>`;
  }).join('');
  return `<div class="rev-text">${segs}</div>`;
}

function revPlotCard(e) {
  const p = e.plot;
  const kv = (k, v) => (v ? `<dt>${k}</dt><dd>${esc(v)}</dd>` : '');
  return `<section class="card"><h2>화 플롯${p.title ? ` · ${esc(p.title)}` : ''}</h2>
    <p class="small">${esc(p.summary)}</p>
    <ol class="small" style="padding-left:18px">${p.events.map((x) => `<li>${esc(x)}</li>`).join('')}</ol>
    <dl class="ab-kv small">${kv('등장', p.characters.join(', '))}${kv('감정 변화', p.emotional_shift)}${kv('엔딩 훅', p.ending_hook)}${kv('여는 장면', p.opening)}${kv('시점', p.time)}${kv('줄기', e.threads.join(', '))}</dl>
    <div class="small">${esc(e.model)} · ${esc(fmtDateTime(e.made_at))}</div></section>`;
}

function revBoardCard(e) {
  const b = e.storyboard;
  if (!b) return '';
  const t = b.time;
  const time = [t.after > 0 ? `직전 화 ${t.after}일 뒤` : t.after < 0 ? '메인 시간 밖' : '', t.part && `${t.part} 시작`, t.days > 1 ? `${t.days}일에 걸침` : '', t.end_part && `${t.end_part} 끝`].filter(Boolean).join(' · ');
  return `<section class="card"><h2>스토리보드 <span class="small">장면 ${b.scenes.length}개</span></h2>
    ${time ? `<div class="small">시간: ${esc(time)}</div>` : ''}
    ${b.handover.length ? `<div class="small">직전 화에서 이어받은 것: ${b.handover.map((h) => `${h.kind ? `[${esc(h.kind)}] ` : ''}${esc(h.text)}`).join(' · ')}</div>` : ''}
    <ol class="small cue-sum">${b.scenes.map((s) => `<li><strong>${esc([s.place, s.spot].filter(Boolean).join(' · ') || '장소 모름')}</strong>${s.time ? ` · ${esc(s.time)}` : ''}${s.present.length ? ` · ${esc(s.present.join(', '))}` : ''}
      ${s.events.length ? ` · 사건 ${s.events.join(', ')}` : ''}<br>${esc([s.goal && `목표: ${s.goal}`, s.turn && `전환: ${s.turn}`, s.end_state && `끝: ${s.end_state}`].filter(Boolean).join(' / '))}</li>`).join('')}</ol></section>`;
}

function revCueCard(e) {
  const orig = (e.scores || []).find((s) => s.condition === 'original');
  const rows = orig ? orig.rows : [];
  const chips = e.sheet.cues.map((c, i) => {
    const r = rows[i];
    const miss = e.missing.includes(i + 1);
    return `<li><button type="button" class="btn small ghost rev-chip${S.revSel === i + 1 ? ' on' : ''}" data-action="revCueGo" data-arg="${i + 1}"${e.bounds_ok && !miss ? '' : ' disabled'}>
      <span class="rev-fn" style="background:${CUE_COLORS[c.function] || 'var(--chip)'}">${esc(c.function)}</span> ${i + 1}번 · 긴장 ${c.tension} · ${esc(cueLabel('tempos', c.tempo).label)} · ${esc(cueLabel('voices', c.voice).label)} · ${(c.length || 0).toLocaleString()}자</button>
      <div class="small">${esc(c.beat)}${r ? ` — 대사 ${cuePct(r.dialogue_ratio)} · 문장 ${r.sentence_len}${r.voice_ok === false ? ' · <strong>편성과 다름</strong>' : ''}` : ''}${miss ? ' — <strong>시작 문장을 원문에서 못 찾았어요</strong>' : ''}</div>
      ${c.lines.length ? `<div class="small">${c.lines.map((x) => `${esc(x.speaker || '?')}: «${esc(x.text)}»`).join(' · ')}</div>` : ''}</li>`;
  }).join('');
  const notes = [];
  if (e.missing.length) notes.push(`${e.missing.join(', ')}번 큐는 시작 문장을 원문에서 찾지 못해 앞 큐에 붙여 쟀어요.`);
  if (e.dropped.length) notes.push(`원문에 없어 뺀 핵심 대사: ${e.dropped.map((x) => `«${esc(x)}»`).join(' · ')}`);
  if (orig && orig.tempo_order === false) notes.push('빠른 큐의 문장이 느린 큐보다 길어요. 템포 표시가 원문과 어긋나요.');
  const { dirty } = cueEd();
  return `${cueScore(cueEd().draft)}<section class="card"><h2>큐 <span class="small">글자 수는 원문에서 잰 값 · 누르면 원문 구간</span></h2>
    ${notes.map((x) => `<div class="note warn small">${x}</div>`).join('')}
    <ol class="rev-chips">${chips}</ol>
    <details class="cue-edit"${dirty ? ' open' : ''}><summary>큐 시트 고치기${dirty ? ' · 저장하지 않은 고침' : ''}</summary>${cueEditor(false)}</details></section>`;
}

function revScoreTable(scores) {
  if (!scores.length) return '';
  const rows = scores.map((s) => `<tr><td>${esc(s.label)}${s.stale ? ' <span class="ab-pill">시트 바뀜</span>' : ''}</td><td>${s.chars.toLocaleString()}</td>
    <td>${s.lines_total ? `${s.lines_hit}/${s.lines_total}` : '-'}</td><td>${s.repeats.length}</td><td>${cuePct(s.dialogue_ratio)}</td><td>${s.sentence_len}</td>
    <td>${s.mattr ?? '-'}</td><td>${cuePct(s.short_endings)}</td><td>${s.ai_patterns}</td><td>${s.rows.length ? cueYes(s.tempo_order) : '-'}</td></tr>`).join('');
  return `<div style="overflow-x:auto"><table class="sw-table"><thead><tr><th></th><th>글자</th><th>핵심 대사</th><th>되풀이 문장</th><th>대사 비율</th><th>문장 길이</th><th>어휘 다양도</th><th>짧은 끝 문장</th><th>쇠맛 경고</th><th>템포</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="small">핵심 대사는 큐 시트의 대사가 글자 그대로 들어간 수예요. 템포는 원문만 큐 경계로 나눠 재요 (빠른 큐의 문장이 느린 큐보다 짧은지).</p>`;
}

function revWriteCard(e) {
  const L = S.revLab;
  const style = !!(S.revStyle && L.style);
  const est = revEstFor(style ? 'write-style' : 'write', [e.number]);
  const go = jobBtn('rev_write', L.id, style ? '문체 넣고 되돌려 쓰기' : '되돌려 쓰기 시작', REV_JOBS);
  const busy = !!jobFor('rev_write', L.id, REV_JOBS);
  const takes = e.takes || [];
  let blind = '';
  if (e.blind_texts.length) {
    blind = `<h3>가려 읽기</h3><p class="small">어느 쪽이 원문인지 숨겼어요. 다 읽고 더 계속 읽고 싶은 쪽을 고르면 어느 쪽인지와 지표를 보여 드려요.</p>
      <div class="rev-blind">${e.blind_texts.map((x, i) => `<div><h4>${i + 1}번</h4><div class="cue-text rev-text">${esc(x)}</div>
        <button type="button" class="btn small" data-action="revPick" data-arg="${i + 1}">${i + 1}번이 더 읽고 싶어요</button></div>`).join('')}</div>
      <div class="row"><button type="button" class="btn small ghost" data-action="revPick" data-arg="0">고르지 않고 결과 보기</button></div>`;
  } else if (e.picked) {
    const what = (x) => (x === 'original' ? '원문' : (takes.find((t) => t.mode === e.blind_take) || { label: '되돌려 쓴 글' }).label);
    blind = `<div class="small">가려 읽기: ${e.picked === 'skip' ? '고르지 않았어요.' : `${esc(what(e.picked))}을 골랐어요. ${e.blind.map((x, i) => `${i + 1}번은 ${esc(what(x))}`).join(', ')}이었어요.`}</div>`;
  }
  const reads = takes.filter((t) => t.text).map((t) => `<details><summary>${esc(t.label)} 읽기 <span class="small">${esc(t.model)} · ${esc(fmtDateTime(t.at))}${t.stale ? ' · 그 뒤 큐 시트를 고쳤어요' : ''}</span></summary>
      <div class="cue-text rev-text">${esc(t.text)}</div></details>`).join('');
  return `<section class="card"><h2>되돌려 쓰기 <span class="small">${e.number}화</span></h2>
    <p class="small">역설계한 플롯 · 스토리보드 · 큐 시트와 인물 · 관계 · 호칭 · 배경만 주고(이 화 원문 문장은 주지 않음) 큐 시트 실험의 '큐 시트를 주고 한 번에' 방식으로 같은 화를 써요. 앞 화는 원문을 반영한 화로 둬요.</p>
    ${cueEd().dirty ? '<div class="note warn small">저장하지 않은 큐 시트 고침이 있어요. 되돌려 쓰기는 저장한 큐 시트로 해요.</div>' : ''}
    <label class="check-row small"><input type="checkbox" data-rev-style="1"${style ? ' checked' : ''}${L.style ? '' : ' disabled'}><span>문체 프로필 넣기${L.style ? '' : ' (문체를 먼저 역설계하세요)'}</span></label>
    <div class="row"><button type="button" class="btn small" data-action="revEstimate" data-arg="write"${busy ? ' disabled' : ''}>비용 추정</button></div>
    ${revEstHtml(est)}
    <div class="row"><button type="button" class="btn primary" data-action="revWrite"${est ? '' : ' disabled'}${go.attr}>${go.label}</button>${est ? '' : '<span class="small">비용 추정을 먼저 보세요.</span>'}</div>
    ${takes.length ? '<div class="small">문체를 넣은 판과 넣지 않은 판을 하나씩 남겨요. 같은 쪽을 다시 쓰면 그 판을 바꾸고, 가려 읽기는 방금 쓴 판으로 새로 해요.</div>' : ''}
    ${blind}${e.blind_texts.length ? '' : revScoreTable(e.scores || [])}${reads}</section>`;  // 가려 읽는 동안에는 지표(글자 수)를 숨긴다
}

document.addEventListener('input', (e) => {
  const d = e.target.dataset || {};
  if (d.revNew) {
    S.revDraft[d.revNew] = e.target.value;
    const box = document.getElementById('rev-preview');
    if (box) box.innerHTML = revPreviewHtml();
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
/** 작업이 끝나면 그 실험을 보고 있을 때 다시 받는다. 고치던 큐 시트(저장하지 않은 것)는 다시 받으며 사라진다. */
function revJobDone(j) {
  if (j.status === 'done' && S.revLab && S.revLab.id === j.ep) revFetch(j.ep).then(render);
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
  async revEstimate(kind) {
    const eps = { parse: [...S.revPick], write: [S.revEp], style: [] }[kind];
    const style = kind === 'write' && !!(S.revStyle && S.revLab.style);
    await run('비용 추정 중', async () => {
      S.revEst = { key: revEstKey(style ? 'write-style' : kind, eps), data: await api('POST', `/revlab/${S.revLab.id}/estimate`, { kind, episodes: eps, style }) };
    });
  },
  revStyleRun() {
    if (S.revLab.style && !confirm('지금 문체 프로필을 새로 만든 것으로 바꿀까요?')) return;
    revStartJob('style');
  },
  revParse() { revStartJob('parse', { episodes: [...S.revPick].sort((a, b) => a - b) }); },
  revWrite() {
    if (cueEd().dirty && !confirm('저장하지 않은 큐 시트 고침이 있어요. 저장한 큐 시트로 되돌려 쓸까요?')) return;
    revStartJob('write', { episodes: [S.revEp], style: !!(S.revStyle && S.revLab.style) });
  },
  async revPick(k) {
    await run('고르는 중', async () => {
      S.revLab = await api('POST', `/revlab/${S.revLab.id}/episodes/${S.revEp}/pick`, { choice: Number(k) });
    });
  },
  revCueGo(k) {
    S.revSel = S.revSel === k ? 0 : k;
    render();
    const el = document.getElementById(`rev-cue-${k}`);
    if (el && S.revSel) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  },
});

(() => {
  const css = `
.rev-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; align-items: start; }
.rev-left { position: sticky; top: 12px; max-height: calc(100vh - 24px); overflow: auto; }
.rev-right { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
@media (max-width: 900px) { .rev-grid { grid-template-columns: minmax(0, 1fr); } .rev-left { position: static; max-height: 70vh; } }
.rev-text { white-space: pre-wrap; font-family: var(--serif); line-height: 1.8; }
.rev-seg { border-left: 3px solid var(--line-strong); padding: 2px 0 2px 10px; margin: 8px 0; border-radius: 2px; }
.rev-seg.sel { background: var(--chip); }
.rev-seg-head { margin-bottom: 2px; }
.rev-tabs { flex-wrap: wrap; gap: 6px; margin: 4px 0 12px; }
.rev-chips { list-style: none; padding: 0; margin: 8px 0; display: flex; flex-direction: column; gap: 8px; }
.rev-chip { text-align: left; white-space: normal; }
.rev-chip.on { background: var(--chip); }
.rev-fn { display: inline-block; min-width: 1.4em; text-align: center; border-radius: 4px; font-weight: 700; }
.rev-blind { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; }
.rev-blind .rev-text { max-height: 60vh; overflow: auto; border: 1px solid var(--line); border-radius: 8px; padding: 10px; margin-bottom: 8px; }
@media (max-width: 720px) { .rev-blind { grid-template-columns: minmax(0, 1fr); } }
.rev-prev, .rev-labs { padding-left: 18px; margin: 4px 0; }
`;
  const el = document.createElement('style');
  el.textContent = css;
  document.head.appendChild(el);
})();

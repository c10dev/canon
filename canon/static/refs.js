/* 레퍼런스 원고: 다른 소설 원고 txt를 화 표시로 나눠 작품 밖에 두고, 고른 화로 문체를 만들거나 역설계 실험을 연다 (canon/refs.py).
   주소 #/refs · #/refs/new · #/refs/<id> · #/refs/<id>/<차례> · #/refs/<id>/cuts. app.js 라우팅이 refLoad 를 부르고 viewRefs 를 그린다.
   화 표시 인식은 서버(POST /api/refs/split) 한 곳이고, 이 화면은 켠 경계로 화를 자르고 글자 수를 다시 센다(refAssemble, refs.assemble 과 같은 규칙).
   refDecode · refAssemble · refRange · refEpRows 는 DOM 없는 순수 함수 (tests/test_refs.py). 설계는 docs/refs/README.md. CSS 는 JS 에서 주입 */
'use strict';

Object.assign(S, {
  refList: null,   // 목록 요약 (사이드바 수에도 쓴다)
  refLabels: null, // 서버 이름표 (규칙 · 종류 · 표시)
  ref: null,       // 연 원고 (GET /refs/<id>)
  refPane: '',     // '' 개요 · 'cuts' 경계 고치기 · 숫자는 화 읽기
  refEp: null,     // 읽는 화 { order, text }
  refPick: new Set(),  // 개요 표에서 고른 화 차례
  refSort: '',     // 표 정렬 칸 ('' 차례)
  refCmp: null,    // 내 작품과 견주기 { project, data }
  refEditInfo: null, // 이름 · 출처 고치기 칸
  refDraft: null,  // 넣기 · 경계 고치기 상태 (refBlank)
  refInbox: null,  // newto 로 가져온 받은 화 (GET /refs/inbox, 넣기 화면에서 읽는다)
  refNewtoOk: false,  // 서버에 newto 폴더가 있다 (refs.newto_dir)
  refNewtoWork: '',  // 가져올 작품 번호 칸
  refDigest: null,  // 연 원고의 화 카드 (GET /refs/<id>/digest: 읽힌 정도 · 화마다 카드 · 읽힐 AI)
  refDigestAsk: null,  // 전체 읽히기 확인 칸을 열었을 때의 비용 추정 (GET …/digest/estimate)
  refPace: null,  // 화 카드로 본 구조 (GET /refs/<id>/digest/pace: 구간 긴장 · 정점 화 · 인물 · 아크)
  refFilter: { kind: '', tension: 0 },  // 화 표 거르기 (성격 · 긴장 아래 한도)
});

const REF_JOBS = '.refs';  // newto 가져오기 작업의 project 자리 (routes/refs.REF_JOBS)
const REF_BYTES = [];  // 고른 파일의 바이트 (인코딩을 바꿔 다시 풀 때 쓴다). 화면 상태에 넣지 않는다
const REF_MAX_BYTES = 30 * 1024 * 1024;
const REF_ENCODINGS = [['utf-8', 'UTF-8'], ['euc-kr', 'CP949 (EUC-KR)'], ['utf-16le', 'UTF-16']];
const REF_TAIL = /^[\s[【〈<(\-=*]*(?:작가의\s*말|작가\s*후기|공지|author'?s\s*note)\s*[\]】〉>)]*\s*[:：]?\s*$/i;  // refs.TAIL_RE
const REF_TAIL_FROM = 0.6;
const REF_SHORT = 300;
const REF_WARN = new Set(['gap', 'dup', 'back', 'mention', 'short', 'long', 'restart']);

const refBlank = (edit = '') => ({ edit, files: [], clips: [], text: '', encoding: 'utf-8', bad: 0, name: '', source: '', notes: '', rights: !!edit,
  rule: '', unit: '', example: '', strip: true, repeats: null, found: [], preview: null, cuts: [], sel: -1, at: -1, filter: 'all', undo: [], dirty: false });

// ---------- 순수 함수 ----------

/** 바이트 → 글. enc 를 비우면 BOM → UTF-8(엄격) → CP949 차례로 고른다. bad 는 1,000자당 대체 문자(U+FFFD) 수. */
function refDecode(bytes, enc = '') {
  const u = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let pick = enc;
  let skip = 0;
  if (!pick) {
    if (u[0] === 0xEF && u[1] === 0xBB && u[2] === 0xBF) { pick = 'utf-8'; skip = 3; } else if (u[0] === 0xFF && u[1] === 0xFE) { pick = 'utf-16le'; skip = 2; } else if (u[0] === 0xFE && u[1] === 0xFF) { pick = 'utf-16be'; skip = 2; }
  }
  let text = null;
  if (!pick) {
    try { text = new TextDecoder('utf-8', { fatal: true }).decode(u); pick = 'utf-8'; } catch { pick = 'euc-kr'; }
  }
  if (text === null) text = new TextDecoder(pick).decode(skip ? u.subarray(skip) : u);
  text = text.replace(/^﻿/, '').replace(/\r\n?/g, '\n');
  const bad = text.length ? ((text.match(/�/g) || []).length * 1000) / text.length : 0;
  return { text, encoding: pick, bad: Math.round(bad * 10) / 10 };
}

/** 화 끝 작가의 말이 시작하는 자리 (refs._tail). */
function refTail(body) {
  const total = body.reduce((k, x) => k + x.length + 1, 0);
  let at = 0;
  for (let i = 0; i < body.length; i += 1) {
    if (at >= total * REF_TAIL_FROM && REF_TAIL.test(body[i])) return i;
    at += body[i].length + 1;
  }
  return body.length;
}

/** 되풀이 줄을 뺀다 (refs._drop_repeats). 뺀 줄 뒤의 빈 줄은 앞이 빈 줄이거나 화 첫머리면 함께 뺀다. */
function refDropRepeats(body, rep) {
  const out = [];
  let dropped = false;
  for (const ln of body) {
    if (rep.has(ln.trim())) { dropped = true; continue; }
    if (dropped && !ln.trim() && (!out.length || !out[out.length - 1].trim())) continue;
    dropped = false;
    out.push(ln);
  }
  return out;
}

/** 켠 경계로 화를 자른다 (refs.assemble): [{ cut, chars, tail, rep }]. cut 은 cuts 의 자리. repeats 의 줄은 빼고 작가의 말은 그 뒤에 뗀다. */
function refAssemble(lines, cuts, strip = true, repeats = []) {
  const rep = new Set(repeats || []);
  const on = cuts.map((c, i) => [i, c]).filter(([, c]) => c.on !== false).sort((a, b) => a[1].line - b[1].line);
  return on.map(([i, c], k) => {
    const end = k + 1 < on.length ? on[k + 1][1].line : lines.length;
    const body = lines.slice(Math.max(c.body, c.line), end);
    const kept = rep.size ? refDropRepeats(body, rep) : body;
    const cut = strip ? refTail(kept) : kept.length;
    const cutRep = rep.size ? body.reduce((n, x) => n + (rep.has(x.trim()) ? x.trim().length : 0), 0) : 0;
    return { cut: i, chars: kept.slice(0, cut).join('\n').trim().length, tail: kept.slice(cut).join('\n').trim().length, rep: cutRep };
  });
}

/** '1~10' · '3, 5, 7~9' → 그 번호의 본편 화 차례. 숫자가 아닌 이름('외전 1')은 이름 그대로 맞춘다. */
function refRange(q, eps) {
  const out = new Set();
  String(q || '').split(/[,，]/).map((x) => x.trim()).filter(Boolean).forEach((part) => {
    const m = part.match(/^(\d+)\s*(?:화)?\s*[~\-–]\s*(\d+)\s*(?:화)?$/);
    const one = part.match(/^(\d+)\s*화?$/);
    eps.forEach((e) => {
      const n = /^\d+/.test(e.label) ? parseInt(e.label, 10) : NaN;
      if (m && e.kind === 'main' && n >= Number(m[1]) && n <= Number(m[2])) out.add(e.order);
      else if (one && e.kind === 'main' && n === Number(one[1])) out.add(e.order);
      else if (!m && !one && e.label === part) out.add(e.order);
    });
  });
  return [...out].sort((a, b) => a - b);
}

/** 경계 목록 줄 값: 켠 경계만 화 차례 · 글자 수가 있고, 짧음 · 김은 지금 글자 수로 다시 센다. filter: all · warn · off */
function refEpRows(d, lines) {
  const eps = refAssemble(lines, d.cuts, d.strip, d.repeats || []);
  const by = new Map(eps.map((e, k) => [e.cut, { ...e, order: k + 1 }]));
  const lens = eps.filter((e) => d.cuts[e.cut].kind !== 'skip').map((e) => e.chars);
  const avg = lens.length ? lens.reduce((a, b) => a + b, 0) / lens.length : 0;
  const rows = d.cuts.map((c, i) => {
    const e = by.get(i);
    const flags = (c.flags || []).filter((f) => f !== 'short' && f !== 'long');
    if (e && c.kind !== 'skip' && e.chars < REF_SHORT) flags.push('short');
    else if (e && lens.length > 3 && e.chars > avg * 3) flags.push('long');
    return { i, line: c.line, on: c.on !== false, order: e ? e.order : 0, chars: e ? e.chars : 0, tail: e ? e.tail : 0, flags,
      warn: c.on !== false && flags.some((f) => REF_WARN.has(f)), label: c.label, title: c.title, kind: c.kind, head: c.head };
  });
  const counts = { on: eps.length, warn: rows.filter((r) => r.warn).length, off: rows.filter((r) => !r.on).length };
  const show = rows.filter((r) => (d.filter === 'warn' ? r.warn : d.filter === 'off' ? !r.on : true));
  return { rows: show, counts, kinds: eps.reduce((o, e) => ({ ...o, [d.cuts[e.cut].kind]: (o[d.cuts[e.cut].kind] || 0) + 1 }), {}) };
}

const refKind = (k) => ((S.refLabels && S.refLabels.kinds) || []).find((x) => x.key === k)?.label || k;
const refFlag = (f) => (S.refLabels && S.refLabels.flags && S.refLabels.flags[f]) || f;
/** 가져온 화 하나를 넣기 원고 끝에 잇는다. 화 이름('001화')을 첫 줄로 둬 화 표시 후보가 되게 한다. */
function refClipAppend(text, clip) {
  const part = [clip.title ? clip.title.trim() : '', clip.text.replace(/\r\n?/g, '\n').trim()].filter(Boolean).join('\n\n');
  return text.trim() ? `${text.replace(/\s+$/, '')}\n\n\n${part}\n` : `${part}\n`;
}

async function refInboxRead() {
  const r = await api('GET', '/refs/inbox');
  S.refInbox = r.items;
  S.refNewtoOk = !!r.newto;
}

/** newto 가져오기 작업이 끝났다(멈춤 · 실패 포함). 서버가 그때까지 받은 화를 대기열에 넣었으니 다시 읽는다 (app.js pollJobs) */
async function refNewtoDone(j) {
  if (S.route[0] === 'refs') await refInboxRead().catch(() => {});
  if (j.status === 'cancelled' && j.result) toast(`멈췄어요. 그때까지 받은 ${j.result.added}화를 받은 화에 넣었어요`);
}

const refEpName = (e) => [e.label || `${e.order}번째`, e.title].filter(Boolean).join(' ');

// ---------- 불러오기 ----------

async function refLoad(id, sub) {
  const home = await api('GET', '/refs');
  S.refList = home.refs;
  S.refLabels = home.labels;
  if (!id) { S.ref = null; return; }
  if (id === 'new') {
    S.ref = null;
    if (!S.refDraft || S.refDraft.edit) S.refDraft = refBlank();
    await refInboxRead().catch(() => { S.refInbox = null; });
    return;
  }
  if (!S.ref || S.ref.id !== id) { S.refPick = new Set(); S.refCmp = null; S.refEditInfo = null; S.refDigest = null; S.refDigestAsk = null; S.refPace = null; S.refFilter = { kind: '', tension: 0 }; }
  S.ref = await api('GET', `/refs/${enc(id)}`);
  S.refDigest = await api('GET', `/refs/${enc(id)}/digest`).catch(() => null);
  await refPaceLoad(id);
  S.refPane = sub === 'cuts' ? 'cuts' : /^\d+$/.test(sub || '') ? Number(sub) : '';
  S.refEp = null;
  if (typeof S.refPane === 'number') S.refEp = await api('GET', `/refs/${enc(id)}/eps/${S.refPane}`);
  if (S.refPane === 'cuts' && !(S.refDraft && S.refDraft.edit === id)) {
    const src = await api('GET', `/refs/${enc(id)}/source`);
    const b = S.ref;
    const d = { ...refBlank(id), text: src.text, name: b.name, encoding: b.encoding, rule: b.rule, unit: b.unit, example: b.rule_example, strip: b.strip_tails, repeats: b.strip_repeats || [] };
    d.preview = await api('POST', '/refs/split', { text: d.text, rule: b.rule, unit: b.unit, example: b.rule_example, strip_tails: b.strip_tails, files: b.files.map((f) => f.line), repeats: d.repeats });
    d.found = d.preview.repeats_found || [];
    // 저장한 경계를 켜고, 서버가 찾은 후보 가운데 저장하지 않은 줄은 꺼 둔다 (작가가 다시 켤 수 있다)
    const saved = new Map(b.cuts.map((c) => [c.line, c]));
    const cuts = d.preview.cuts.map((c) => (saved.has(c.line) ? { ...c, ...saved.get(c.line), on: true } : { ...c, on: false }));
    b.cuts.forEach((c) => { if (!cuts.some((x) => x.line === c.line)) cuts.push({ ...c, on: true, flags: [] }); });
    d.cuts = cuts.sort((a, b2) => a.line - b2.line);
    S.refDraft = d;
  }
  if (S.refPane === 'cuts' && S.refGoto != null) {  // 화 읽기의 '이 화 경계 고치기'로 왔으면 그 경계를 고른다
    S.refDraft.sel = S.refDraft.cuts.findIndex((c) => c.line === S.refGoto);
    S.refGoto = null;
  }
}

// ---------- 화면 ----------

function viewRefs() {
  if (S.route[1] === 'new' || (S.refPane === 'cuts' && S.ref)) return refDraftView();
  if (S.ref) return refBookView();
  return refHome();
}

function refHome() {
  const list = S.refList || [];
  const head = header('작품 밖 도구', '레퍼런스 원고', '다른 소설 원고 txt를 넣으면 화 표시로 화를 나눠요. 고른 화로 문체를 만들거나 역설계 실험을 열 수 있어요. 원고는 이 컴퓨터에만 저장하고, AI에는 고른 화와 전체 읽히기를 누른 원고만 보내요.',
    list.length ? '<a class="btn primary" href="#/refs/new">+ 원고 넣기</a>' : '');
  if (!list.length) {
    return `${head}<section class="card ref-empty"><h2>아직 넣은 원고가 없어요</h2><p class="small">'1화' · '제1화' · '[1화]' · 'EP.1' 같은 화 표시를 찾아 화마다 나눠요. 화 표시가 없으면 '===' 줄이나 빈 줄로 나눠요.</p>
      <div class="row"><a class="btn primary" href="#/refs/new">원고 넣기</a></div></section>`;
  }
  const cards = list.map((r) => {
    const k = r.kinds || {};
    const parts = [`본편 ${k.main || 0}화`, k.side ? `외전 ${k.side}` : '', k.prologue ? `프롤로그 ${k.prologue}` : '', k.epilogue ? `에필로그 ${k.epilogue}` : ''].filter(Boolean).join(' · ');
    const meta = [`${r.chars.toLocaleString()}자`, r.made ? `만든 것 ${r.made}개` : '', r.created_at ? `넣은 날 ${fmtDateTime(r.created_at)}` : ''].filter(Boolean).join(' · ');
    return `<a class="card ref-card" href="#/refs/${r.id}"><h3>${esc(r.name)}</h3>${r.source ? `<div class="small">${esc(r.source)}</div>` : ''}
      <div>${esc(parts)}</div><div class="small">${esc(meta)}</div></a>`;
  }).join('');
  return `${head}<div class="ref-cards">${cards}</div>`;
}

// ----- 넣기 · 경계 고치기 -----

/** 손가락 기기: 파일을 끌어 놓기 어려우니 '파일 고르기'만 안내한다 */
const REF_TOUCH = () => matchMedia('(pointer: coarse)').matches;

function refDraftView() {
  const d = S.refDraft || (S.refDraft = refBlank());
  const back = d.edit ? `<a class="btn" href="#/refs/${d.edit}">원고로</a>` : '<a class="btn" href="#/refs">목록으로</a>';
  if (!d.preview) {
    return `${header('레퍼런스 원고', '원고 넣기', `txt 파일을 고르${REF_TOUCH() ? '세요' : '거나 끌어 놓으세요'}. 여러 파일은 이름 차례로 이어요.`, back)}${refFileCard(d)}`;
  }
  const title = d.edit ? `경계 고치기 · ${d.name}` : '화 나누기 확인';
  const v = refEpRows(d, refLines());
  const desc = `${v.counts.on}화로 나눠요. 체크를 풀면 앞 화와 합치고, 오른쪽 원문에서 줄을 눌러 그 줄에서 나눌 수 있어요.`;
  return `${header('레퍼런스 원고', title, desc, `${back}${d.edit ? '' : '<button type="button" class="btn" data-action="refBackToFile">파일 다시 고르기</button>'}`)}
    ${refRuleBar(d, v)}
    <div class="ref-split">${refCutList(d, v)}${refTextPane(d)}</div>
    ${refSaveRow(d, v)}`;
}

let refLinesCache = { text: null, lines: [] };
function refLines() {
  const t = S.refDraft ? S.refDraft.text : '';
  if (refLinesCache.text !== t) refLinesCache = { text: t, lines: t.split('\n') };
  return refLinesCache.lines;
}

function refFileCard(d) {
  const files = d.files.length ? `<ul class="ref-files">${d.files.map((f) => `<li>${esc(f.name)} <span class="small">${f.size.toLocaleString()}바이트</span></li>`).join('')}</ul>` : '';
  const head = d.text ? `<div class="ref-peek" aria-label="풀어 낸 앞부분">${esc(d.text.slice(0, 300))}</div>` : '';
  const enc2 = d.files.length ? `<div class="field ref-enc"><label for="ref-enc">글자 인코딩</label><select id="ref-enc" data-ref-enc="1">${REF_ENCODINGS.map(([k, l]) => `<option value="${k}"${d.encoding === k ? ' selected' : ''}>${l}</option>`).join('')}</select>
    <span class="small">${d.bad > 1 ? `<span class="ref-bad">깨진 글자가 많아요 (1,000자당 ${d.bad}개). 다른 인코딩을 골라 보세요.</span>` : `${esc((REF_ENCODINGS.find(([k]) => k === d.encoding) || [0, d.encoding])[1])}로 읽었어요. 글자가 깨져 보이면 바꾸세요.`}</span></div>` : '';
  const ok = d.text.trim() && d.name.trim() && d.rights;
  return `<section class="card ref-file">
    <div class="ref-drop" data-ref-drop="1"><p>${REF_TOUCH() ? '아래 버튼으로 txt 파일을 고르세요' : 'txt 파일을 여기에 끌어 놓으세요'}</p><label class="btn" for="ref-file-in">파일 고르기</label>
      <input id="ref-file-in" type="file" accept=".txt,text/plain" multiple hidden data-ref-file="1"></div>
    ${files}${enc2}${head}
    ${refClipCard(d)}
    <details class="ref-paste"${!d.files.length && d.text ? ' open' : ''}><summary class="small">파일 대신 붙여 넣기</summary>
      <textarea rows="8" data-ref-paste="1" placeholder="원고를 붙여 넣으세요">${d.files.length ? '' : esc(d.text)}</textarea></details>
    <div class="field"><label for="ref-name">이름</label><input id="ref-name" type="text" data-ref-f="name" value="${esc(d.name)}" placeholder="예: 등대지기의 밤"></div>
    <div class="field"><label for="ref-src">출처 <span class="small">(작가 · 작품 등, 고르지 않아도 돼요)</span></label><input id="ref-src" type="text" data-ref-f="source" value="${esc(d.source)}"></div>
    <label class="check-row"><input type="checkbox" data-ref-f="rights"${d.rights ? ' checked' : ''}><span>내가 쓸 권리가 있는 원고예요 (내 원고, 허락받은 원고, 개인 공부용)</span></label>
    <p class="small">원고는 이 컴퓨터의 작업 폴더에만 저장해요. AI에는 문체 만들기 · 역설계 실험에서 고른 화와, 전체 읽히기를 누른 원고만 보내요.</p>
    <div class="row"><button type="button" class="btn primary" data-action="refDetect"${ok ? '' : ' disabled'}>화 나누기</button>
      ${d.text ? `<span class="small">${d.text.length.toLocaleString()}자</span>` : ''}</div></section>`;
}

/** 사이트에서 가져오기: 서버의 newto(`npm run verify -- --headless --work <번호> --wait-on-limit`)로 작품을 받고, 받은 화를 원고로 가져온다 */
function refClipCard(d) {
  const inbox = S.refInbox || [];
  const clips = d.clips || [];
  const j = jobFor('ref_newto', null, REF_JOBS);
  const got = inbox.length ? `<div class="ref-inbox"><div class="between"><strong>받은 화 ${inbox.length}개</strong><span class="small">${inbox.reduce((k, x) => k + x.text.length, 0).toLocaleString()}자</span></div>
      <ol class="ref-clips small">${inbox.map((x) => `<li>${esc([x.book, x.title].filter(Boolean).join(' · ') || x.url || '제목 없음')} <span>${x.text.length.toLocaleString()}자</span></li>`).join('')}</ol>
      <div class="row"><button type="button" class="btn primary" data-action="refInboxTake">원고로 가져오기</button><button type="button" class="btn" data-action="refInboxClear">비우기</button></div></div>`
    : '<p class="small">아직 받은 화가 없어요.</p>';
  const taken = clips.length ? `<p class="small">원고에 넣은 화 ${clips.length}개</p>` : '';
  const run = j ? `<div class="ref-newto-run" aria-live="polite"><div class="between"><strong>${esc(j.label)}${j.total > 1 ? ` · ${j.done}/${j.total}` : ''}</strong>
      <button type="button" class="btn small" data-job-stop="${j.id}">멈추기</button></div>${j.note ? `<p class="small">${esc(j.note)}</p>` : ''}</div>` : '';
  const form = !S.refNewtoOk
    ? '<p class="small">서버에서 newto 폴더를 찾지 못했어요. CANON_NEWTO에 newto 폴더 경로를 넣고 Canon을 다시 시작하세요.</p>'
    : `<p class="small">작품 번호를 넣으면 서버의 newto가 화를 차례로 받아요. 요청 한도에 걸리면 기다렸다가 다시 받아요. 이미 받은 화는 건너뛰어요.</p>
      <div class="row"><label class="sr-only" for="ref-newto-work">작품 번호</label><input id="ref-newto-work" type="text" inputmode="numeric" data-ref-newto="1" value="${esc(S.refNewtoWork)}" placeholder="작품 번호 (예: 34323)"${j ? ' disabled' : ''}>
        <button type="button" class="btn" data-action="refNewtoStart"${j ? ' aria-disabled="true" aria-busy="true"' : ''}>${j ? '받는 중…' : '가져오기'}</button>
        <button type="button" class="btn" data-action="refInboxLoad">새로고침</button></div>`;
  return `<details class="ref-clip"${inbox.length || clips.length || j ? ' open' : ''}><summary class="small">사이트에서 가져오기 (newto)${inbox.length ? ` · 받은 화 ${inbox.length}` : ''}</summary>
    ${form}${run}${got}${taken}</details>`;
}

function refRuleBar(d, v) {
  const p = d.preview;
  const rule = (S.refLabels.rules.find((r) => r.key === p.rule) || {}).label || p.rule;
  const chips = [`<span class="chip on" title="고른 규칙">${esc(rule)}${p.unit && p.unit !== 'custom' ? ` · '${esc(p.unit)}'` : ''}</span>`]
    .concat((p.alts || []).map((a) => `<button type="button" class="btn small" data-action="refUnit" data-arg="${esc(a.unit)}">'${esc(a.unit)}' 로 나누기 (${a.count}줄)</button>`));
  const other = S.refLabels.rules.filter((r) => r.key !== p.rule && r.key !== 'custom').map((r) => `<option value="${r.key}">${esc(r.label)}</option>`).join('');
  const k = v.kinds;
  const sum = [`본편 ${k.main || 0}화`, k.prologue ? `프롤로그 ${k.prologue}` : '', k.side ? `외전 ${k.side}` : '', k.epilogue ? `에필로그 ${k.epilogue}` : '', k.skip ? `제외 ${k.skip}` : ''].filter(Boolean).join(' · ');
  return `<section class="card ref-rule"><div class="between"><div><strong>${esc(sum)}</strong>${v.counts.warn ? ` · <span class="ref-warn">확인할 것 ${v.counts.warn}</span>` : ''}
      ${p.common_head ? `<div class="small">화 표시 앞에 늘 붙은 '${esc(p.common_head)}' 는 떼고 읽었어요.</div>` : ''}
      ${p.parts ? `<div class="small">같은 번호가 여러 화에 되풀이돼서 그 번호를 부 번호로 보고, 화 번호는 1화부터 차례대로 매겼어요 (부 ${p.parts}개).</div>` : ''}
      ${p.preface_chars ? `<div class="small">첫 화 앞 글 ${p.preface_chars.toLocaleString()}자(작품 제목 · 소개 · 목차)는 머리 글로 보고 화에 넣지 않아요.</div>` : ''}</div>
      <div class="row">${chips.join('')}</div></div>
    <div class="row ref-rule-more">
      <label class="small" for="ref-rule">다른 규칙</label><select id="ref-rule" data-ref-rule="1"><option value="">고르기</option>${other}</select>
      <label class="small" for="ref-ex">직접 패턴</label><input id="ref-ex" type="text" data-ref-f="example" value="${esc(d.example)}" placeholder="예: [제12화] 제목">
      <button type="button" class="btn small" data-action="refCustom">이 꼴로 나누기</button>
      <label class="check-row small"><input type="checkbox" data-ref-strip="1"${d.strip ? ' checked' : ''}><span>화 끝 작가의 말 떼기</span></label>
      <button type="button" class="btn small" data-action="refUndo"${d.undo.length ? '' : ' disabled'}>되돌리기</button></div>${refRepeatBox(d)}</section>`;
}

/** 여러 화에 똑같이 나오는 줄(화마다 붙은 고지문 · 공지). 체크한 줄은 화 글에서 뺀다 (refs.find_repeats, 원문은 그대로) */
function refRepeatBox(d) {
  const found = d.found || [];
  if (!found.length) return '';
  const on = new Set(d.repeats || []);
  const n = found.filter((x) => on.has(x.text)).length;
  const rows = found.map((x, k) => `<li><label class="check-row small"><input type="checkbox" data-ref-rep="${k}"${on.has(x.text) ? ' checked' : ''}>
    <span><span class="ref-rep-text">${esc(x.text.length > 120 ? `${x.text.slice(0, 120)}…` : x.text)}</span> <span class="ref-rep-n">${x.eps}화에 나옴</span></span></label></li>`).join('');
  return `<details class="ref-rep"${n ? '' : ' open'}><summary class="small">화마다 되풀이되는 줄 ${found.length}개${n ? ` · ${n}개 뗌` : ''}</summary>
    <p class="small">고지문 · 공지처럼 여러 화의 첫머리나 끝에 똑같이 나오는 줄이에요. 체크한 줄은 화 글에서 빼요. 원문은 그대로 둬요.</p>
    <ul class="ref-rep-list">${rows}</ul></details>`;
}

function refCutList(d, v) {
  const tabs = [['all', '모두'], ['warn', `확인할 것 ${v.counts.warn}`], ['off', `끈 줄 ${v.counts.off}`]].map(([k, l]) => `<button type="button" class="btn small${d.filter === k ? ' on' : ''}" data-action="refFilter" data-arg="${k}" aria-pressed="${d.filter === k}">${l}</button>`).join('');
  const rows = v.rows.map((r) => {
    const flags = r.flags.filter((f) => f !== 'toc' || !r.on).map((f) => `<span class="chip${REF_WARN.has(f) ? ' written' : ''}">${esc(refFlag(f))}${f === 'gap' && d.cuts[r.i].gap ? ` ${d.cuts[r.i].gap[0]}${d.cuts[r.i].gap[1] !== d.cuts[r.i].gap[0] ? `~${d.cuts[r.i].gap[1]}` : ''}화` : ''}</span>`).join('');
    const name = r.label ? (/^\d/.test(r.label) ? `${r.label}화` : r.label) : '번호 없음';
    return `<div class="ref-row${r.on ? '' : ' off'}${d.sel === r.i ? ' sel' : ''}">
      <input type="checkbox" data-ref-on="${r.i}"${r.on ? ' checked' : ''} aria-label="${esc(name)} 경계 켜기">
      <button type="button" class="ref-row-btn" data-action="refSel" data-arg="${r.i}"><span class="ref-ln">${r.line + 1}</span>
        <span class="ref-nm">${esc(name)}${r.kind !== 'main' ? ` <span class="small">${esc(refKind(r.kind))}</span>` : ''}</span>
        <span class="ref-hd">${esc(r.title || r.head || '(나눈 줄)')}</span><span class="ref-ch small">${r.on ? `${r.chars.toLocaleString()}자` : ''}</span></button>
      <span class="ref-fl">${flags}</span></div>`;
  }).join('');
  return `<section class="card ref-list" aria-label="경계 목록"><div class="row">${tabs}</div><div class="ref-rows">${rows || '<p class="small">여기에 보일 줄이 없어요.</p>'}</div></section>`;
}

function refTextPane(d) {
  const lines = refLines();
  const c = d.cuts[d.sel];
  const center = d.at >= 0 ? d.at : c ? c.line : 0;
  const from = Math.max(0, center - 4);  // 고른 경계가 칸 위쪽에 보이게
  const to = Math.min(lines.length, from + 60);
  const cutAt = new Set(d.cuts.filter((x) => x.on !== false).map((x) => x.line));
  const body = lines.slice(from, to).map((ln, k) => {
    const i = from + k;
    return `<button type="button" class="ref-tl${cutAt.has(i) ? ' cut' : ''}${d.at === i ? ' at' : ''}" data-action="refAt" data-arg="${i}"><span class="ref-ln">${i + 1}</span><span>${esc(ln) || ' '}</span></button>`;
  }).join('');
  const edit = c ? refCutEditor(d, c) : '<p class="small">왼쪽에서 줄을 고르면 그 경계를 고칠 수 있어요.</p>';
  const at = d.at >= 0 && !cutAt.has(d.at) ? `<div class="row"><span class="small">${d.at + 1}번째 줄</span><button type="button" class="btn small primary" data-action="refSplitAt" data-arg="${d.at}">여기서 나누기</button></div>` : '';
  return `<section class="card ref-pane" aria-label="원문 보기">${edit}${at}
    <div class="row"><button type="button" class="btn small" data-action="refScroll" data-arg="-50"${from ? '' : ' disabled'}>위로</button><span class="small">${from + 1}~${to}번째 줄 / ${lines.length.toLocaleString()}줄</span>
      <button type="button" class="btn small" data-action="refScroll" data-arg="50"${to < lines.length ? '' : ' disabled'}>아래로</button></div>
    <div class="ref-text">${body}</div></section>`;
}

function refCutEditor(d, c) {
  const i = d.sel;
  const kinds = S.refLabels.kinds.map((k) => `<option value="${k.key}"${c.kind === k.key ? ' selected' : ''}>${esc(k.label)}</option>`).join('');
  return `<div class="ref-edit"><div class="small">${c.line + 1}번째 줄 · ${esc(c.head || '(나눈 줄)')}</div>
    <div class="row"><div class="field"><label for="ref-c-label">번호</label><input id="ref-c-label" type="text" data-ref-c="label" value="${esc(c.label)}" size="6"></div>
      <div class="field"><label for="ref-c-title">제목</label><input id="ref-c-title" type="text" data-ref-c="title" value="${esc(c.title)}"></div>
      <div class="field"><label for="ref-c-kind">종류</label><select id="ref-c-kind" data-ref-c="kind">${kinds}</select></div></div>
    <div class="row"><button type="button" class="btn small" data-action="refRenumber" data-arg="${i}"${/^\d+$/.test(c.label) ? '' : ' disabled'}>여기부터 번호 다시 매기기</button>
      <button type="button" class="btn small" data-action="refToggle" data-arg="${i}">${c.on !== false ? '앞 화와 합치기' : '다시 나누기'}</button></div></div>`;
}

function refSaveRow(d, v) {
  return `<div class="ref-save row">${v.counts.warn ? `<span class="small">확인할 것 ${v.counts.warn}개가 남았어요. 그대로 저장해도 돼요.</span>` : ''}
    <button type="button" class="btn primary" data-action="refSave"${v.counts.on ? '' : ' disabled'}>${d.edit ? '경계 저장하기' : `저장하기 (${v.counts.on}화)`}</button></div>`;
}

// ----- 원고 개요 · 화 읽기 -----

function refToc(b) {
  const groups = {};
  b.episodes.forEach((e) => { (groups[e.kind] = groups[e.kind] || []).push(e); });
  const link = (href, inner, cur) => `<a class="outline-item" href="${href}"${cur ? ' aria-current="page"' : ''}>${inner}</a>`;
  const body = [link(`#/refs/${b.id}`, `<span class="tl">개요</span><span class="st">${b.episodes.length}화</span>`, S.refPane === '')]
    .concat(Object.keys(S.refLabels.kinds.reduce((o, k) => ({ ...o, [k.key]: 1 }), {})).filter((k) => groups[k]).map((k) => `<span class="outline-h">${esc(refKind(k))}</span>${groups[k].map((e) => link(`#/refs/${b.id}/${e.order}`, `<span class="tl">${esc(refEpName(e))}</span><span class="st">${e.chars.toLocaleString()}</span>`, S.refPane === e.order)).join('')}`)).join('');
  const cur = S.refPane === '' ? '개요' : (b.episodes.find((e) => e.order === S.refPane) ? refEpName(b.episodes.find((e) => e.order === S.refPane)) : '목차');
  return outlineNav({ id: 'ref-toc', label: '원고 목차', now: esc(cur), body, cls: 'ref-toc' });
}

function refBookView() {
  const b = S.ref;
  const menu = menuBtn('ref-more', '⋯', () => `<button type="button" class="pop-item" data-action="refInfoEdit">이름 · 출처 고치기</button>
    <button type="button" class="pop-item" data-action="refCutsGo">경계 다시 고치기</button>
    <button type="button" class="pop-item" data-action="refExport">원문 txt로 내보내기</button>
    <div class="pop-sep" role="separator"></div>
    <div class="pop-sec pop-danger"><details><summary class="small">이 원고 지우기</summary>
      <div class="small">원문과 경계를 지워요. 이 원고로 만든 문체 · 역설계 실험은 남아요.</div>
      <button type="button" class="pop-item danger" data-action="refDelete">지우기</button></details></div>`, { aria: '원고 더보기' });
  const meta = [b.source, `${b.chars.toLocaleString()}자`, `${b.episodes.length}화`].filter(Boolean).join(' · ');
  const head = header('레퍼런스 원고', b.name, esc(meta), `<a class="btn" href="#/refs">목록으로</a>${menu}`);
  const main = typeof S.refPane === 'number' ? refReader(b) : refOverview(b);
  return `${head}${outlineDoc(refToc(b), `<div class="ref-main">${S.refEditInfo ? refInfoCard() : ''}${main}</div>`, { wide: true, cls: 'ref-wrap' })}`;
}

function refInfoCard() {
  const x = S.refEditInfo;
  return `<section class="card"><h2>이름 · 출처 고치기</h2>
    <div class="field"><label for="ref-i-name">이름</label><input id="ref-i-name" type="text" data-ref-i="name" value="${esc(x.name)}"></div>
    <div class="field"><label for="ref-i-src">출처</label><input id="ref-i-src" type="text" data-ref-i="source" value="${esc(x.source)}"></div>
    <div class="field"><label for="ref-i-notes">메모</label><textarea id="ref-i-notes" rows="3" data-ref-i="notes">${esc(x.notes)}</textarea></div>
    <div class="row"><button type="button" class="btn primary" data-action="refInfoSave">저장</button><button type="button" class="btn" data-action="refInfoEdit">닫기</button></div></section>`;
}

const REF_COLS = [['order', '차례'], ['label', '번호'], ['title', '제목'], ['chars', '글자 수'], ['dialogue', '대사 비율'], ['sentence_len', '문장 평균'], ['paragraph_len', '문단 평균']];

const REF_DIGEST_COLS = [['d_kind', '성격'], ['tension', '긴장'], ['hook', '끝맺음']];
const REF_AI_NAMES = { gemini: 'Gemini', claude: 'Claude 구독', 'claude-api': 'Claude API', coralbricks: 'CoralBricks', local: '로컬 서버', mock: 'mock' };
const REF_CORAL_VALUE = 'deepseek-v4.1-flash-value';  // 화 카드에 권하는 싼 모델 (docs/refs/README.md 9장)

const REF_PART = { all: '전체', head: '첫머리', talk: '대사 덩어리', narr: '서술 덩어리', tail: '끝' };  // refsample.PART_NAMES

/** 흩어 뽑은 표본 알림. 순수 함수 */
function refSpreadMsg(s) {
  return `고른 화가 ${s.chars.toLocaleString()}자라 앞 · 가운데 · 뒤 ${s.episodes}화에서 ${s.pieces.length}조각을 고루 뽑아 ${s.text.length.toLocaleString()}자를 넣었어요. 표지 빈도는 고른 화 전체에서 세요.`;
}

/** 뽑은 조각 목록 한 줄씩 ('23화 첫머리 812자'). 순수 함수 */
function refPieceLines(pieces) {
  return pieces.map((p) => `${p.label || `${p.order}번째`} ${REF_PART[p.part] || p.part} ${p.chars.toLocaleString()}자`);
}

/** 이 원고의 전체 읽히기 작업 (돌고 있을 때만) */
const refDigestJob = (id) => S.jobs.find((j) => j.status === 'running' && j.kind === 'ref_digest' && (j.target || '') === id);

/** 작업 끝 알림 글 (app.js JOB_DONE_MSG). 순수 함수 */
function refDigestDoneMsg(j) {
  const r = j.result || {};
  const fail = (r.failed || []).length;
  return `${r.read || 0}화를 읽혔어요.${fail ? ` ${fail}화는 읽지 못했어요${r.error ? ` (${r.error})` : ''}.${r.stopped ? ' 연달아 실패해 멈췄어요.' : ''} 다시 읽히면 남은 화만 보내요.` : ''}`;
}

/** 작업이 한 걸음 나아갔다: 읽힌 화를 다시 받는다 (app.js pollJobs) */
async function refDigestStep(j) {
  if (S.route[0] !== 'refs' || !S.ref || S.ref.id !== (j.target || '')) return;
  S.refDigest = await api('GET', `/refs/${enc(S.ref.id)}/digest`).catch(() => S.refDigest);
  if (j.status !== 'running') { S.refDigestAsk = null; await refPaceLoad(S.ref.id); }
}

/** 읽히기 버튼 이름: 처음 · 글이 바뀐 화만 남음 · 읽다 만 화가 남음. 순수 함수 */
function refDigestLabel(d) {
  if (!d.read) return '전체 읽히기';
  return d.stale === d.todo ? '바뀐 화만 다시 읽히기' : '남은 화 읽히기';
}

/** 비용 추정 한 줄. 순수 함수 */
function refDigestCost(est) {
  const free = ['local', 'claude', 'mock'].includes(est.provider);
  const usd = est.usd == null ? '가격을 모르는 모델이에요' : est.usd === 0 ? (free ? '토큰 요금 없음' : '추정 $0.01 아래') : `추정 $${est.usd}`;
  return `${est.calls}화 · 입력 약 ${est.input_tokens.toLocaleString()}토큰 · ${usd} · ${est.workers}화씩 함께 보내요${est.long ? ` · 아주 긴 ${est.long}화는 가운데를 줄여 보내요` : ''}`;
}

function refDigestCard(b) {
  const d = S.refDigest;
  if (!d || !d.total) return '';
  const j = refDigestJob(b.id);
  const line = `읽힌 화 ${d.read} / ${d.total}${d.stale ? ` · 글이 바뀐 화 ${d.stale}` : ''}${d.at ? ` · 마지막 ${fmtDateTime(d.at)}` : ''}`;
  const running = j ? `<div class="ref-newto-run" aria-live="polite"><div class="between"><strong>읽히는 중 · ${j.done}/${j.total}</strong>
      <button type="button" class="btn small" data-job-stop="${j.id}">멈추기</button></div>${j.note ? `<p class="small">${esc(j.note)}</p>` : ''}</div>` : '';
  const est = S.refDigestAsk;
  // 이 화면의 주 버튼은 '문체 만들기' 하나라 여기 버튼은 보통 버튼이다 (docs/design/README.md '덜기')
  const btn = !j && d.todo ? `<button type="button" class="btn" data-action="refDigestAsk" aria-expanded="${!!est}">${refDigestLabel(d)}</button>` : '';
  const ai = d.ai;
  const opts = [['', `설정을 따름 (${REF_AI_NAMES[ai.follow.provider] || ai.follow.provider}${ai.follow.name ? ` · ${ai.follow.name}` : ''})`], ...ai.providers.map((p) => [p, REF_AI_NAMES[p] || p])]
    .map(([v, l]) => `<option value="${v}"${ai.provider === v ? ' selected' : ''}>${esc(l)}</option>`).join('');
  const coral = ai.coral && !(ai.use.provider === 'coralbricks' && ai.use.name === REF_CORAL_VALUE) && ai.use.provider !== 'mock'
    ? `<button type="button" class="btn small" data-action="refDigestCoral">CoralBricks 싼 모델로 (${REF_CORAL_VALUE})</button>` : '';
  const ask = est && !j ? `<div class="ref-digest-ask">
      <div class="row"><div class="field"><label for="ref-d-ai">읽힐 AI</label><select id="ref-d-ai" data-ref-digest-ai="provider">${opts}</select></div>
        ${ai.provider ? `<div class="field"><label for="ref-d-model">모델</label><input id="ref-d-model" type="text" data-ref-digest-ai="model" value="${esc(ai.model)}" placeholder="${esc(ai.use.name || '백엔드 기본 모델')}" autocapitalize="off" spellcheck="false"></div>` : ''}${coral}</div>
      <p class="small">${esc(refDigestCost(est))}</p>
      <p class="small">화마다 원문을 ${esc(REF_AI_NAMES[est.provider] || est.provider)}${est.model ? ` (${esc(est.model)})` : ''}에 보내 사건 · 인물 · 끝맺음을 정리해요. 정리한 것은 이 컴퓨터의 원고 폴더에만 두고 작품에는 넣지 않아요.${est.provider === 'coralbricks' ? ' CoralBricks는 기본으로 원문을 30일 보관해요. 남기지 않으려면 CoralBricks의 Data & Privacy에서 Zero Data Retention을 켜세요.' : ''}</p>
      <div class="row"><button type="button" class="btn" data-action="refDigestStart"${est.calls ? '' : ' disabled'}>읽히기 시작</button><button type="button" class="btn" data-action="refDigestAsk">닫기</button></div></div>` : '';
  return `<section class="card ref-digest"><div class="between"><div><h2>전체 읽히기</h2><span class="small">${line}</span></div>${btn}</div>${running}${ask}</section>`;
}

/** 화 읽기 화면의 화 카드 */
function refDigestEp(order) {
  const c = S.refDigest && S.refDigest.cards[order];
  if (!c) return '';
  const meta = [c.kind, c.tension ? `긴장 ${c.tension}` : '', c.hook && c.hook !== '없음' ? `끝맺음 ${c.hook}` : '', c.place].filter(Boolean).join(' · ');
  return `<details class="ref-digest-ep" open><summary class="small">AI가 정리한 이 화 · ${esc(meta)}</summary>
    <ol>${c.events.map((x) => `<li>${esc(x)}</li>`).join('')}</ol>
    <p class="small">끝: ${esc(c.ending)}${c.cast.length ? ` · 인물: ${esc(c.cast.join(', '))}` : ''}${c.cut ? ` · 가운데 ${c.cut.toLocaleString()}자를 줄여 읽혔어요` : ''}</p></details>`;
}

/** 화 카드로 본 구조(GET …/digest/pace)를 다시 받는다. 지금 연 원고일 때만 */
async function refPaceLoad(id) {
  if (S.route[0] !== 'refs' || !S.ref || S.ref.id !== id) return;
  S.refPace = S.refDigest && S.refDigest.read ? await api('GET', `/refs/${enc(id)}/digest/pace`).catch(() => null) : null;
}

/** 표를 거른 뒤 남는 화인지 (성격 · 긴장 아래 한도). 순수 함수 */
function refFilterKeep(e, f) {
  return (!f.kind || e.d_kind === f.kind) && (!f.tension || e.tension >= f.tension);
}

/** 아크 한 줄의 화 범위 ('12화~31화'). labels 는 차례 → 화 이름. 순수 함수 */
function refArcSpan(a, labels) {
  const name = (n) => labels[n] || `${n}번째`;
  return a.start_ep === a.end_ep ? name(a.start_ep) : `${name(a.start_ep)}~${name(a.end_ep)}`;
}

function refArcsBlock(b, p) {
  const v = p.arcs || {};
  const j = S.jobs.find((x) => x.status === 'running' && x.kind === 'ref_arcs' && (x.target || '') === b.id);
  if (j) return '<p class="small" aria-live="polite">아크를 나누는 중이에요. 끝나면 여기에 보여요.</p>';
  if (!v.plan) {
    const left = S.refDigest ? S.refDigest.todo : 0;
    return `<div class="between"><span class="small">${left ? `읽히지 않은 화가 ${left}개 있어 아직 아크를 나눌 수 없어요.` : '화 카드를 접어 AI에 한 번 보내 아크 · 부로 나눠요.'}</span>
      <button type="button" class="btn small" data-action="refArcsAsk"${left ? ' disabled' : ''}>아크 나누기</button></div>`;
  }
  const L = v.labels || {};
  const parts = v.plan.parts.length ? `<p class="small">부: ${v.plan.parts.map((x) => `${esc(x.title)} (${esc(refArcSpan(x, L))})`).join(' · ')}</p>` : '';
  const arcs = v.plan.arcs.map((a) => `<li><strong>${esc(a.title)}</strong> <span class="small">${esc(refArcSpan(a, L))} · ${a.end_ep - a.start_ep + 1}화${a.climax_ep ? ` · 정점 ${esc(L[a.climax_ep] || a.climax_ep)}` : ''}</span>
      <div class="small">${esc([a.goal, a.conflict && `막는 것: ${a.conflict}`, a.payoff && `보상: ${a.payoff}`].filter(Boolean).join(' · '))}</div></li>`).join('');
  return `${v.stale ? '<p class="small">아크를 나눈 뒤 화 카드가 바뀌었어요. 다시 나누면 지금 카드로 맞춰요.</p>' : ''}${parts}<ol class="ref-arcs">${arcs}</ol>
    ${v.plan.reply ? `<p class="small">${esc(v.plan.reply)}</p>` : ''}
    <div class="row"><button type="button" class="btn small" data-action="refArcsAsk">다시 나누기</button><button type="button" class="btn small ghost" data-action="refArcsClear">아크 지우기</button>
      <span class="small">${esc(v.plan.model)} · ${fmtDateTime(v.plan.at)}</span></div>`;
}

/** 원고 개요의 구조 카드: 구간별 긴장 막대 · 성격으로 표 거르기 · 정점 화 · 인물이 처음 나온 화 · 아크 */
function refStructureCard(b) {
  const p = S.refPace;
  if (!p || !p.episodes) return '';
  const f = S.refFilter;
  // 구간 평균은 3 안팎에 몰려 있어, 가장 낮은 구간과 높은 구간 사이로 막대 높이를 편다 (값은 풀이에 그대로 적는다)
  const lo = Math.min(...p.blocks.map((x) => x.tension));
  const hi = Math.max(...p.blocks.map((x) => x.tension));
  const tall = (t) => 14 + Math.round(((t - lo) / ((hi - lo) || 1)) * 46);
  const bars = p.blocks.map((x) => {
    const tip = `${x.from}~${x.to} · 평균 긴장 ${x.tension} · 긴장 5인 화 ${x.peaks}개 · ${x.kinds.map(([k, n]) => `${k} ${n}`).join(', ')}`;
    return `<a class="ref-pace-bar${x.peaks ? ' peak' : ''}" href="#/refs/${b.id}/${x.start}" style="height:${tall(x.tension)}px" title="${esc(tip)}"><span class="sr-only">${esc(tip)}</span></a>`;
  }).join('');
  const chips = p.kinds.map(([k, n]) => `<button type="button" class="btn small${f.kind === k ? '' : ' ghost'}" data-action="refFilterKind" data-arg="${esc(k)}" aria-pressed="${f.kind === k}">${esc(k)} ${n}</button>`).join('');
  const tens = [[0, '긴장 모두'], [3, '긴장 3 이상'], [4, '긴장 4 이상'], [5, '긴장 5']].map(([v, l]) => `<option value="${v}"${f.tension === v ? ' selected' : ''}>${l}</option>`).join('');
  const peaks = p.peaks.slice(0, 14).map((x) => `<a href="#/refs/${b.id}/${x.order}">${esc(x.label || `${x.order}번째`)}</a>`).join(', ');
  const label = (n) => { const e = b.episodes.find((x) => x.order === n); return e ? e.label || `${n}번째` : `${n}번째`; };
  const cast = p.cast.slice(0, 8).map((c) => `${esc(c.name)} <span class="small">${esc(label(c.first))}부터 · ${c.episodes}화</span>`).join(' · ');
  return `<section class="card ref-structure"><div class="between"><h2>구조</h2><span class="small">화 카드 ${p.episodes}화 · 막대 하나가 ${p.block_size}화의 평균 긴장이에요 (${lo}~${hi})</span></div>
    <div class="ref-pace" aria-label="구간별 평균 긴장">${bars}</div>
    <div class="row ref-filter">${chips}<label class="sr-only" for="ref-f-tension">긴장으로 거르기</label><select id="ref-f-tension" data-ref-filter="tension">${tens}</select>
      ${f.kind || f.tension ? '<button type="button" class="btn small ghost" data-action="refFilterClear">거르기 풀기</button>' : ''}</div>
    ${peaks ? `<p class="small">긴장 5인 화 ${p.peaks.length}개: ${peaks}${p.peaks.length > 14 ? ` 외 ${p.peaks.length - 14}화` : ''}</p>` : ''}
    ${cast ? `<p>${cast}</p>` : ''}
    <h3>아크</h3>${refArcsBlock(b, p)}</section>`;
}

function refOverview(b) {
  const cards = (S.refDigest && S.refDigest.cards) || {};
  const hasCards = Object.keys(cards).length > 0;
  const all = b.episodes.map((e) => { const c = cards[e.order] || {}; return { ...e, d_kind: c.kind || '', tension: c.tension || 0, hook: c.hook || '' }; });
  const filtering = hasCards && (S.refFilter.kind || S.refFilter.tension);
  const eps = filtering ? all.filter((e) => refFilterKeep(e, S.refFilter)) : all;
  if (S.refSort) eps.sort((x, y) => (typeof x[S.refSort] === 'number' ? y[S.refSort] - x[S.refSort] : String(x[S.refSort]).localeCompare(String(y[S.refSort]))));
  const pick = S.refPick;
  const usable = b.episodes.filter((e) => e.kind !== 'skip' && e.chars);
  const max = Math.max(1, ...usable.map((e) => e.chars));
  const mean = usable.length ? Math.round(usable.reduce((k, e) => k + e.chars, 0) / usable.length) : 0;
  const bars = b.episodes.map((e) => `<a href="#/refs/${b.id}/${e.order}" class="ref-bar${e.kind === 'main' ? '' : ` k-${e.kind}`}${pick.has(e.order) ? ' on' : ''}" style="height:${Math.max(4, Math.round((e.chars / max) * 64))}px" title="${esc(refEpName(e))} · ${e.chars.toLocaleString()}자"><span class="sr-only">${esc(refEpName(e))} ${e.chars}자</span></a>`).join('');
  const th = [...REF_COLS, ...(hasCards ? REF_DIGEST_COLS : [])].map(([k, l]) => `<th scope="col"><button type="button" class="ref-sort${S.refSort === k || (!S.refSort && k === 'order') ? ' on' : ''}" data-action="refSortBy" data-arg="${k}">${l}</button></th>`).join('');
  const rows = eps.map((e) => `<tr class="${e.kind === 'skip' ? 'off' : ''}"><td><input type="checkbox" data-ref-pick="${e.order}"${pick.has(e.order) ? ' checked' : ''}${e.kind === 'skip' ? ' disabled' : ''} aria-label="${esc(refEpName(e))} 고르기"></td>
    <td>${e.order}</td><td>${esc(e.label)}${e.kind !== 'main' ? ` <span class="small">${esc(refKind(e.kind))}</span>` : ''}</td><td><a href="#/refs/${b.id}/${e.order}">${esc(e.title || '(제목 없음)')}</a></td>
    <td class="num">${e.chars.toLocaleString()}</td><td class="num">${Math.round(e.dialogue * 100)}%</td><td class="num">${e.sentence_len}</td><td class="num">${e.paragraph_len}</td>${hasCards ? `<td>${esc(e.d_kind)}</td><td class="num">${e.tension || ''}</td><td>${esc(e.hook)}</td>` : ''}</tr>`).join('');
  const n = pick.size;
  const picked = b.episodes.reduce((k, e) => k + (pick.has(e.order) ? e.chars : 0), 0);
  const revMax = S.refLabels.revlab_max_chars || 0;
  const tooMany = revMax > 0 && picked > revMax;
  const act = `<section class="card ref-act"><div class="between"><h2>고른 화로 하기</h2><span class="small">${n ? `${n}화 골랐어요` : '표에서 화를 고르세요'}</span></div>
    <div class="row"><label class="small" for="ref-range">범위</label><input id="ref-range" type="text" data-ref-range="1" placeholder="예: 1~10, 15" size="14">
      <button type="button" class="btn small" data-action="refPickRange">고르기</button><button type="button" class="btn small" data-action="refPickNone"${n ? '' : ' disabled'}>모두 풀기</button></div>
    <div class="row"><button type="button" class="btn primary" data-action="refToStyle"${n ? '' : ' disabled'}>문체 만들기</button>
      <button type="button" class="btn" data-action="refToRevlab"${n && !tooMany ? '' : ' disabled'}>역설계 실험 만들기</button></div>
    <p class="small">문체 만들기는 고른 화를 이어 문체 라이브러리 새 항목의 원문 칸에 넣어요. ${(S.refLabels.sample_max || 30000).toLocaleString()}자를 넘으면 앞 · 가운데 · 뒤에서 고루 뽑아요. 분석은 그 화면에서 눌러야 해요. 역설계 실험은 화 수와 상관없이 모두 합쳐 ${revMax.toLocaleString()}자까지 넣을 수 있어요${tooMany ? ` (지금 ${picked.toLocaleString()}자라 너무 많이 골랐어요)` : ''}.</p></section>`;
  const made = b.made.length ? `<section class="card"><h2>이 원고로 만든 것</h2><ul class="ref-made">${b.made.map((m) => `<li><a href="#/${m.kind === 'style' ? 'styles' : 'revlab'}/${enc(m.id)}">${m.kind === 'style' ? '문체 라이브러리 항목' : `역설계 실험 ${esc(m.id)}`}</a> <span class="small">${esc(m.eps)} · ${fmtDateTime(m.at)}</span></li>`).join('')}</ul></section>` : '';
  return `${refDigestCard(b)}${refStructureCard(b)}${act}<section class="card"><div class="between"><h2>분량</h2><span class="small">한 화 평균 ${mean.toLocaleString()}자 · 막대를 누르면 그 화를 열어요</span></div><div class="ref-bars" aria-label="화별 글자 수">${bars}</div></section>
    ${refCompareCard()}
    <section class="card"><div class="between"><h2>화 표</h2>${filtering ? `<span class="small">거른 ${eps.length}화 / ${all.length}화</span>` : ''}</div><div class="ref-table-wrap"><table class="ref-table"><thead><tr><th scope="col"><span class="sr-only">고르기</span></th>${th}</tr></thead><tbody>${rows}</tbody></table></div></section>${made}`;
}

function refCompareCard() {
  const works = (S.projects || []).filter((x) => !x.play);
  const opts = works.map((w) => `<option value="${esc(w.name)}"${S.refCmp && S.refCmp.project === w.name ? ' selected' : ''}>${esc(w.title || w.name)}</option>`).join('');
  let table = '';
  const c = S.refCmp && S.refCmp.data;
  if (c) {
    const fmt = (k, v) => (v == null ? '–' : k === 'dialogue' ? `${Math.round(v * 100)}%` : k === 'chars' ? Math.round(v).toLocaleString() : (Math.round(v * 10) / 10).toString());
    const row = (k, l) => { const a = c.ref[k]; const p = c.project[k]; return `<tr><th scope="row">${l}</th><td class="num">${a ? `${fmt(k, a.mean)} <span class="small">(${fmt(k, a.min)}~${fmt(k, a.max)})</span>` : '–'}</td><td class="num">${p ? `${fmt(k, p.mean)} <span class="small">(${fmt(k, p.min)}~${fmt(k, p.max)})</span>` : '–'}</td></tr>`; };
    table = c.project_eps ? `<table class="ref-table"><thead><tr><th scope="col">지표 (한 화 평균)</th><th scope="col">이 원고</th><th scope="col">내 작품 (${c.project_eps}화)</th></tr></thead><tbody>
      ${row('chars', '글자 수')}${row('dialogue', '대사 비율')}${row('sentence_len', '문장 평균 글자')}${row('paragraph_len', '문단 평균 글자')}</tbody></table>` : '<p class="small">그 작품에는 본문을 쓴 화가 아직 없어요.</p>';
  }
  return `<section class="card"><div class="between"><h2>내 작품과 견주기</h2><span class="small">작품에는 아무것도 저장하지 않아요</span></div>
    <div class="row"><label class="small" for="ref-cmp">작품</label><select id="ref-cmp" data-ref-cmp="1"><option value="">고르기</option>${opts}</select></div>${table}</section>`;
}

function refReader(b) {
  const e = b.episodes.find((x) => x.order === S.refPane);
  if (!e || !S.refEp) return '<section class="card"><p>이 화를 찾지 못했어요.</p></section>';
  const prev = b.episodes.find((x) => x.order === e.order - 1);
  const next = b.episodes.find((x) => x.order === e.order + 1);
  const nav = `<div class="row">${prev ? `<a class="btn small" href="#/refs/${b.id}/${prev.order}">‹ ${esc(refEpName(prev))}</a>` : ''}${next ? `<a class="btn small" href="#/refs/${b.id}/${next.order}">${esc(refEpName(next))} ›</a>` : ''}</div>`;
  const paras = S.refEp.text.split(/\n\s*\n/).map((p) => `<p>${esc(p).replace(/\n/g, '<br>')}</p>`).join('');
  const m = `${e.chars.toLocaleString()}자 · 대사 ${Math.round(e.dialogue * 100)}% · 문장 평균 ${e.sentence_len}자${e.tail_cut ? ` · 작가의 말 ${e.tail_cut.toLocaleString()}자 뗌` : ''}${e.repeat_cut ? ` · 되풀이 줄 ${e.repeat_cut.toLocaleString()}자 뗌` : ''}`;
  return `<section class="card ref-read"><div class="between"><div><h2>${esc(refEpName(e))}</h2><div class="small">${esc(refKind(e.kind))} · ${m}</div></div>${nav}</div>
    ${refDigestEp(e.order)}<div class="ref-body">${paras}</div>
    <div class="between">${nav}<a class="btn small" href="#/refs/${b.id}/cuts" data-ref-goto="${e.line}">이 화 경계 고치기</a></div></section>`;
}

// ---------- 동작 ----------

async function refReadFiles(list) {
  const files = [...list].sort((a, b) => a.name.localeCompare(b.name, 'ko', { numeric: true }));
  if (!files.length) return;
  const total = files.reduce((k, f) => k + f.size, 0);
  if (total > REF_MAX_BYTES) return toast(`파일이 너무 커요 (${Math.round(total / 1024 / 1024)}MB). 30MB까지 넣을 수 있어요`, true);
  REF_BYTES.length = 0;
  for (const f of files) REF_BYTES.push({ name: f.name, size: f.size, bytes: new Uint8Array(await f.arrayBuffer()) });
  const d = S.refDraft;
  d.files = REF_BYTES.map(({ name, size }) => ({ name, size }));
  refDecodeAll(d, '');
  if (!d.name) d.name = files[0].name.replace(/\.txt$/i, '').replace(/[\s_\-]*(?:\d+\s*권|vol\.?\s*\d+|\d+)$/i, '').trim() || files[0].name;
  render();
}

/** 고른 파일을 모두 풀어 잇는다. 파일마다 시작 줄을 남긴다(번호가 1부터 다시 시작하는 권 경계). */
function refDecodeAll(d, enc0) {
  let text = '';
  let bad = 0;
  let pick = enc0;
  d.fileLines = [];
  REF_BYTES.forEach((f, k) => {
    const r = refDecode(f.bytes, enc0);
    if (!k) pick = r.encoding;
    bad = Math.max(bad, r.bad);
    d.fileLines.push(text ? text.split('\n').length : 0);
    text += (text && !text.endsWith('\n') ? '\n' : '') + r.text;
  });
  d.text = text;
  d.encoding = pick;
  d.bad = bad;
  d.preview = null;
}

async function refDetect(extra = {}) {
  const d = S.refDraft;
  await run('화 표시를 찾는 중', async () => {
    const body = { text: d.text, rule: d.rule, unit: d.unit, example: d.example, strip_tails: d.strip, files: d.fileLines || [], repeats: d.repeats, ...extra };
    const p = await api('POST', '/refs/split', body);
    Object.assign(d, { rule: p.rule, unit: p.unit, preview: p, found: p.repeats_found || [], repeats: p.repeats || [], cuts: p.cuts.map((c) => ({ ...c })), sel: -1, at: -1, undo: [], dirty: true });
    if (body.example !== undefined) d.example = body.example;
  });
}

function refPush(d) {
  d.undo.push(JSON.stringify(d.cuts));
  if (d.undo.length > 50) d.undo.shift();
  d.dirty = true;
}

Object.assign(actions, {
  refInboxLoad() {
    return run('받은 화를 읽는 중', refInboxRead);
  },
  async refNewtoStart() {
    const work = (S.refNewtoWork || '').trim();
    if (!/^\d+$/.test(work)) return toast('작품 번호는 숫자만 넣어 주세요', true);
    if (jobFor('ref_newto', null, REF_JOBS)) return;
    try {
      const j = await api('POST', '/refs/newto', { work });
      toast(j.already ? '이미 받는 중인 작품이 있어요' : 'newto로 받기 시작했어요. 끝나면 받은 화에 들어와요. 그동안 다른 작업을 해도 돼요.');
      S.jobs = S.jobs.filter((x) => x.id !== j.id).concat(j);
      renderHub();
      render();
      pollJobs(true);
    } catch (e) { showError(e); }
  },
  refInboxTake() {
    const d = S.refDraft;
    const items = S.refInbox || [];
    if (!d || !items.length) return;
    return run('원고로 가져오는 중', async () => {
      if (d.files.length) { REF_BYTES.length = 0; d.files = []; d.fileLines = []; d.text = ''; d.clips = []; }
      for (const x of items) d.text = refClipAppend(d.text, x);
      d.encoding = 'utf-8';
      d.preview = null;
      d.clips = [...(d.clips || []), ...items.map((x) => ({ title: x.title, url: x.url, chars: x.text.length }))];
      const book = (items.find((x) => x.book) || {}).book;
      if (!d.name.trim() && book) d.name = book;
      await api('DELETE', '/refs/inbox', { ids: items.map((x) => x.id) });
      await refInboxRead();
      toast(`받은 화 ${items.length}개를 원고에 넣었어요`);
    });
  },
  async refInboxClear() {
    if (!(await askConfirm(`받은 화 ${(S.refInbox || []).length}개를 비울까요? 되돌릴 수 없어요.`, { ok: '비우기', danger: true }))) return;
    return run('비우는 중', async () => { await api('DELETE', '/refs/inbox'); S.refInbox = []; });
  },
  refBackToFile() { S.refDraft.preview = null; render(); },
  refDetect() { return refDetect(); },
  refUnit(u) { return refDetect({ rule: 'heading', unit: String(u) }); },
  refCustom() {
    const d = S.refDraft;
    if (!d.example.trim()) return toast('예시 줄을 적어 주세요. 예: [제12화] 제목', true);
    return refDetect({ rule: 'custom', example: d.example });
  },
  refFilter(k) { S.refDraft.filter = k; render(); },
  refSel(i) { const d = S.refDraft; d.sel = i; d.at = -1; render(); },
  refAt(i) { S.refDraft.at = i; render(); },
  refScroll(n) {
    const d = S.refDraft;
    const c = d.cuts[d.sel];
    const center = d.at >= 0 ? d.at : c ? c.line : 0;
    d.at = Math.max(0, Math.min(refLines().length - 1, center + Number(n)));
    render();
  },
  refToggle(i) {
    const d = S.refDraft;
    refPush(d);
    d.cuts[i].on = d.cuts[i].on === false;
    render();
  },
  refSplitAt(line) {
    const d = S.refDraft;
    refPush(d);
    const prev = [...d.cuts].filter((c) => c.on !== false && c.line < line).pop();
    const next = prev && /^\d+$/.test(prev.label) ? String(Number(prev.label) + 1) : '';
    d.cuts.push({ line, body: line, head: '', label: next, title: '', kind: prev ? prev.kind : 'main', on: true, flags: [] });
    d.cuts.sort((a, b) => a.line - b.line);
    d.sel = d.cuts.findIndex((c) => c.line === line);
    d.at = -1;
    render();
  },
  refRenumber(i) {
    const d = S.refDraft;
    refPush(d);
    let n = Number(d.cuts[i].label);
    const kind = d.cuts[i].kind;
    d.cuts.forEach((c, k) => { if (k > i && c.on !== false && c.kind === kind && /^\d+(-\S+)?$/.test(c.label)) { n += 1; c.label = String(n); } });
    toast('뒤 번호를 다시 매겼어요');
    render();
  },
  refUndo() {
    const d = S.refDraft;
    if (!d.undo.length) return;
    d.cuts = JSON.parse(d.undo.pop());
    render();
  },
  async refSave() {
    const d = S.refDraft;
    const cuts = d.cuts.filter((c) => c.on !== false).map(({ line, body, head, label, title, kind }) => ({ line, body, head, label, title, kind }));
    await run('저장하는 중', async () => {
      if (d.edit) {
        await api('PUT', `/refs/${enc(d.edit)}`, { cuts, strip_tails: d.strip, strip_repeats: d.repeats || [], rule: d.rule, unit: d.unit, example: d.example });
        const id = d.edit;
        S.refDraft = null;
        toast('경계를 저장했어요');
        location.hash = `#/refs/${id}`;
        return;
      }
      const b = await api('POST', '/refs', { name: d.name, source: d.source, notes: d.notes, rights: d.rights, encoding: d.encoding, text: d.text, rule: d.rule,
        example: d.example, unit: d.unit, common_head: d.preview.common_head || '', strip_tails: d.strip, strip_repeats: d.repeats || [], cuts,
        files: (d.files || []).map((f, k) => ({ name: f.name, line: (d.fileLines || [])[k] || 0 })) });
      S.refDraft = null;
      REF_BYTES.length = 0;
      S.refList = null;
      toast(`'${b.name}' 원고를 저장했어요 (${b.episodes.length}화)`);
      location.hash = `#/refs/${b.id}`;
    }, { render: 'never' });  // 주소가 바뀌면 원고 화면을 그린다 (빈 넣기 칸이 잠깐 보이지 않게)
  },
  refCutsGo() { location.hash = `#/refs/${S.ref.id}/cuts`; },
  refSortBy(k) { S.refSort = k === 'order' ? '' : k; render(); },
  refPickRange() {
    const q = ($('#ref-range') || {}).value || '';
    const got = refRange(q, S.ref.episodes.filter((e) => e.kind !== 'skip'));
    if (!got.length) return toast('그 범위에 맞는 화가 없어요', true);
    got.forEach((o) => S.refPick.add(o));
    render();
  },
  refPickNone() { S.refPick = new Set(); render(); },
  refFilterKind(kind) { S.refFilter = { ...S.refFilter, kind: S.refFilter.kind === kind ? '' : kind }; render(); },
  refFilterClear() { S.refFilter = { kind: '', tension: 0 }; render(); },
  async refArcsAsk() {
    const id = S.ref.id;
    let est;
    try { est = await api('GET', `/refs/${enc(id)}/digest/arcs/estimate`); } catch (e) { return showError(e); }
    const cost = est.usd == null ? '가격을 모르는 모델이에요' : est.usd === 0 ? '토큰 요금이 거의 없어요' : `추정 $${est.usd}`;
    const again = S.refPace && S.refPace.arcs && S.refPace.arcs.plan ? ' 지금 아크는 새 것으로 바뀌어요.' : '';
    if (!(await askConfirm(`화 카드 ${est.episodes}화를 ${est.model || est.provider}에 한 번 보내 아크로 나눠요 (${cost}). 원문은 보내지 않아요.${again}`, { ok: '나누기' }))) return;
    try {
      const j = await api('POST', `/refs/${enc(id)}/digest/arcs`);
      toast(j.already ? '이미 나누는 중이에요' : '아크를 나누기 시작했어요. 끝나면 알려 드릴게요.');
      S.jobs = S.jobs.filter((x) => x.id !== j.id).concat(j);
      renderHub();
      render();
      pollJobs(true);
    } catch (e) { showError(e); }
  },
  async refArcsClear() {
    if (!(await askConfirm('나눈 아크를 지울까요? 화 카드는 그대로 있어요.', { ok: '지우기', danger: true }))) return;
    await run('아크를 지우는 중', async () => { await api('DELETE', `/refs/${enc(S.ref.id)}/digest/arcs`); await refPaceLoad(S.ref.id); });
  },
  async refDigestAsk() {
    if (S.refDigestAsk) { S.refDigestAsk = null; render(); return; }
    await run('읽힐 화를 세는 중', async () => { S.refDigestAsk = await api('GET', `/refs/${enc(S.ref.id)}/digest/estimate`); });
  },
  async refDigestCoral() {
    await refDigestSetAI('coralbricks', REF_CORAL_VALUE);
  },
  async refDigestStart() {
    const id = S.ref.id;
    if (refDigestJob(id)) return;
    try {
      const j = await api('POST', `/refs/${enc(id)}/digest`);
      toast(j.already ? '이미 읽히는 중이에요' : '읽히기 시작했어요. 화마다 저장하니 그동안 다른 작업을 해도 돼요.');
      S.refDigestAsk = null;
      S.jobs = S.jobs.filter((x) => x.id !== j.id).concat(j);
      renderHub();
      render();
      pollJobs(true);
    } catch (e) { showError(e); }
  },
  async refToStyle() {
    const b = S.ref;
    await run('원문을 모으는 중', async () => {
      const s = await api('POST', `/refs/${enc(b.id)}/sample`, { eps: [...S.refPick].sort((x, y) => x - y) });
      const orders = [...S.refPick].sort((x, y) => x - y);
      S.libFromRef = { name: `${b.name} 문체`, source: s.source, text: s.text, ref: b.id, eps: s.source.replace(`${b.name} `, ''), orders, pieces: s.spread ? s.pieces : [] };
      if (s.spread) toast(refSpreadMsg(s));
      else if (s.cut) toast(`고른 화가 ${s.chars.toLocaleString()}자라 앞 ${s.text.length.toLocaleString()}자만 넣었어요`);
      location.hash = '#/styles/new';
    });
  },
  async refToRevlab() {
    const b = S.ref;
    await run('역설계 실험을 만드는 중', async () => {
      const r = await api('POST', `/refs/${enc(b.id)}/revlab`, { eps: [...S.refPick].sort((x, y) => x - y) });
      toast('역설계 실험을 만들었어요. 비용을 확인하고 역설계를 시작하세요');
      location.hash = `#/revlab/${r.id}`;
    });
  },
  refInfoEdit() {
    const b = S.ref;
    S.refEditInfo = S.refEditInfo ? null : { name: b.name, source: b.source, notes: b.notes };
    if (S.refEditInfo) S.focusTarget = '#ref-i-name';
    render();
  },
  async refInfoSave() {
    const x = S.refEditInfo;
    await run('저장하는 중', async () => {
      S.ref = await api('PUT', `/refs/${enc(S.ref.id)}`, x);
      S.refEditInfo = null;
      S.refList = null;
      toast('저장했어요');
    });
  },
  async refExport() {
    const b = S.ref;
    await run('원문을 받는 중', async () => {
      const src = await api('GET', `/refs/${enc(b.id)}/source`);
      const url = URL.createObjectURL(new Blob([src.text], { type: 'text/plain;charset=utf-8' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `${b.name}.txt`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }, { render: 'never' });
  },
  async refDelete() {
    const b = S.ref;
    if (!(await askConfirm(`'${b.name}' 원고를 지울까요? 원문과 경계가 사라지고 되돌릴 수 없어요. 이 원고로 만든 문체 · 역설계 실험은 남아요.`, { ok: '지우기', danger: true }))) return;
    await run('지우는 중', async () => {
      await api('DELETE', `/refs/${enc(b.id)}`);
      S.ref = null;
      S.refList = null;
      toast('원고를 지웠어요');
      location.hash = '#/refs';
    });
  },
});

document.addEventListener('input', (e) => {
  const d = e.target.dataset || {};
  const dr = S.refDraft;
  if (d.refF && dr) {
    dr[d.refF] = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
    const btn = document.querySelector('[data-action="refDetect"]');
    if (btn) btn.disabled = !(dr.text.trim() && dr.name.trim() && dr.rights);
  }
  if (d.refPaste && dr) {
    REF_BYTES.length = 0;
    dr.files = [];
    dr.fileLines = [];
    dr.text = e.target.value.replace(/\r\n?/g, '\n');
    dr.encoding = 'utf-8';
    const btn = document.querySelector('[data-action="refDetect"]');
    if (btn) btn.disabled = !(dr.text.trim() && dr.name.trim() && dr.rights);
  }
  if (d.refC && dr && dr.cuts[dr.sel] && e.target.tagName === 'INPUT') {
    dr.cuts[dr.sel][d.refC] = e.target.value;
    dr.dirty = true;
  }
  if (d.refI && S.refEditInfo) S.refEditInfo[d.refI] = e.target.value;
  if (d.refNewto) S.refNewtoWork = e.target.value;
});

/** 읽힐 AI 를 저장하고 비용 추정을 다시 받는다 */
async function refDigestSetAI(provider, model) {
  const id = S.ref.id;
  await run('읽힐 AI를 바꾸는 중', async () => {
    S.refDigest.ai = await api('PUT', `/refs/${enc(id)}/digest/ai`, { provider, model });
    S.refDigestAsk = await api('GET', `/refs/${enc(id)}/digest/estimate`);
  });
}

document.addEventListener('change', (e) => {
  const d = e.target.dataset || {};
  const dr = S.refDraft;
  if (d.refFilter === 'tension') { S.refFilter = { ...S.refFilter, tension: Number(e.target.value) || 0 }; render(); }
  if (d.refDigestAi && S.ref && S.refDigest) {
    if (d.refDigestAi === 'provider') refDigestSetAI(e.target.value, '');
    else refDigestSetAI(S.refDigest.ai.provider, e.target.value.trim());
  }
  if (d.refFile) refReadFiles(e.target.files).catch(showError);
  if (d.refEnc && dr) { refDecodeAll(dr, e.target.value); render(); }
  if (d.refRule && dr && e.target.value) refDetect({ rule: e.target.value, unit: '' });
  if (d.refStrip && dr) { dr.strip = e.target.checked; render(); }
  if (d.refRep !== undefined && dr && dr.found[Number(d.refRep)]) {
    const t = dr.found[Number(d.refRep)].text;
    const set = new Set(dr.repeats || []);
    if (e.target.checked) set.add(t); else set.delete(t);
    dr.repeats = dr.found.map((x) => x.text).filter((x) => set.has(x)).concat([...set].filter((x) => !dr.found.some((f) => f.text === x)));
    dr.dirty = true;
    render();
  }
  if (d.refOn !== undefined && dr) {
    refPush(dr);
    dr.cuts[Number(d.refOn)].on = e.target.checked;
    render();
  }
  if (d.refC === 'kind' && dr && dr.cuts[dr.sel]) { refPush(dr); dr.cuts[dr.sel].kind = e.target.value; render(); }
  if (d.refPick !== undefined && S.ref) {
    const o = Number(d.refPick);
    if (e.target.checked) S.refPick.add(o); else S.refPick.delete(o);
    render();
  }
  if (d.refCmp !== undefined && S.ref) {
    const name = e.target.value;
    if (!name) { S.refCmp = null; render(); return; }
    run('지표를 재는 중', async () => { S.refCmp = { project: name, data: await api('GET', `/refs/${enc(S.ref.id)}/compare?project=${enc(name)}`) }; });
  }
});

document.addEventListener('click', (e) => {
  const a = e.target.closest('[data-ref-goto]');
  if (a) S.refGoto = Number(a.dataset.refGoto);  // 경계 고치기 화면이 열리면 그 줄을 고른다 (refLoad)
});

['dragover', 'drop'].forEach((t) => document.addEventListener(t, (e) => {
  const zone = e.target.closest && e.target.closest('[data-ref-drop]');
  if (!zone) return;
  e.preventDefault();
  zone.classList.toggle('over', t === 'dragover');
  if (t === 'drop' && e.dataTransfer && e.dataTransfer.files.length) refReadFiles(e.dataTransfer.files).catch(showError);
}));
document.addEventListener('dragleave', (e) => { const z = e.target.closest && e.target.closest('[data-ref-drop]'); if (z) z.classList.remove('over'); });

(() => {
  const css = `
.ref-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(260px, 100%), 1fr)); gap: var(--space-16); }
.ref-card { color: inherit; text-decoration: none; gap: var(--space-6); }
.ref-card:hover { border-color: var(--line-strong); }
.ref-card h3 { margin: 0; }
.ref-drop { border: 2px dashed var(--line-strong); border-radius: var(--radius-12); padding: var(--space-24); display: flex; flex-direction: column; align-items: center; gap: var(--space-8); text-align: center; }
.ref-drop.over { border-color: var(--accent); background: var(--accent-soft); }
.ref-drop p { margin: 0; color: var(--muted); }
.ref-clip p { margin: var(--space-8) 0; }
.ref-steps { margin: var(--space-8) 0; padding-left: var(--space-20); }
.ref-newto-run { margin-top: var(--space-12); }
.ref-newto-run p { margin: var(--space-4) 0 0; overflow-wrap: anywhere; }
.ref-digest-ask { margin-top: var(--space-12); display: grid; gap: var(--space-8); }
.ref-pace { display: flex; align-items: flex-end; gap: var(--space-2); height: 64px; margin: var(--space-12) 0; border-bottom: 1px solid var(--line); }
.ref-pace-bar { flex: 1; min-width: 4px; background: var(--chip); border-radius: var(--radius-6) var(--radius-6) 0 0; }
.ref-pace-bar.peak { background: var(--accent-soft); }
.ref-pace-bar:hover { background: var(--accent); }
.ref-filter { flex-wrap: wrap; align-items: center; }
.ref-filter select { width: auto; }
.ref-structure h3 { margin: var(--space-16) 0 var(--space-8); }
.ref-arcs { margin: var(--space-8) 0; padding-left: var(--space-20); display: grid; gap: var(--space-8); }
.ref-digest-ask p { margin: 0; }
.ref-digest-ask .row { align-items: flex-end; flex-wrap: wrap; }
.ref-digest-ep { margin: var(--space-12) 0; padding: var(--space-12); border: 1px solid var(--line); border-radius: var(--radius-8); }
.ref-digest-ep ol { margin: var(--space-8) 0; padding-left: var(--space-20); }
.ref-digest-ep p { margin: 0; }
.ref-rep { margin-top: var(--space-12); }
.ref-rep-list { list-style: none; margin: var(--space-8) 0 0; padding: 0; display: grid; gap: var(--space-4); }
.ref-rep-text { overflow-wrap: anywhere; }
.ref-rep-n { color: var(--muted); white-space: nowrap; }
.ref-inbox { margin-top: var(--space-12); padding-top: var(--space-12); border-top: 1px solid var(--line); }
.ref-clips { margin: var(--space-8) 0 0; padding-left: var(--space-20); }
.ref-clips span { color: var(--muted); }
.ref-files { margin: 0; padding-left: var(--space-20); }
.ref-peek { font-family: var(--serif); white-space: pre-wrap; max-height: 160px; overflow: auto; padding: var(--space-12); border: 1px solid var(--line); border-radius: var(--radius-6); background: var(--bg); font-size: 0.875rem; }
.ref-bad, .ref-warn { color: var(--amber-ink); font-weight: 700; }
.ref-rule-more { gap: var(--space-8); }
.ref-rule-more input[type="text"] { width: 180px; }
.ref-split { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 440px), 1fr)); gap: var(--space-16); margin-top: var(--space-16); align-items: start; }
.ref-rows { display: flex; flex-direction: column; max-height: 68vh; overflow: auto; }
.ref-row { display: grid; grid-template-columns: 28px minmax(0, 1fr); align-items: center; border-bottom: 1px solid var(--line); }
.ref-row.off .ref-row-btn { color: var(--muted); }
.ref-row.sel { background: var(--sel-bg); }
.ref-row-btn { display: grid; grid-template-columns: 48px 72px minmax(0, 1fr) 72px; gap: var(--space-8); align-items: center; text-align: left; background: none; border: 0; padding: var(--space-6) 0; color: inherit; font: inherit; cursor: pointer; min-height: 36px; }
.ref-ln { color: var(--muted); font-size: 0.75rem; font-variant-numeric: tabular-nums; }
.ref-nm { font-weight: 700; }
.ref-hd { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ref-ch { text-align: right; font-variant-numeric: tabular-nums; }
.ref-fl { grid-column: 2; display: flex; flex-wrap: wrap; gap: var(--space-4); padding-bottom: var(--space-4); }
.ref-fl:empty { display: none; }
.ref-pane { position: sticky; top: var(--space-16); }
.ref-text { display: flex; flex-direction: column; max-height: 56vh; overflow: auto; font-family: var(--serif); font-size: 0.875rem; }
.ref-tl { display: grid; grid-template-columns: 48px minmax(0, 1fr); gap: var(--space-8); text-align: left; background: none; border: 0; border-top: 1px solid transparent; padding: 2px 0; color: inherit; font: inherit; cursor: pointer; }
.ref-tl span:last-child { white-space: pre-wrap; word-break: break-all; }
.ref-tl.cut { border-top-color: var(--accent); font-weight: 700; }
.ref-tl.at { background: var(--sel-bg); }
.ref-edit { display: flex; flex-direction: column; gap: var(--space-8); padding-bottom: var(--space-12); border-bottom: 1px solid var(--line); }
.ref-save { position: sticky; bottom: 0; justify-content: flex-end; padding: var(--space-12) 0; background: var(--bg); }
.ref-main { display: flex; flex-direction: column; gap: var(--space-16); }
.ref-bars { position: relative; display: flex; align-items: flex-end; gap: 1px; height: 68px; overflow-x: auto; }  /* relative: 막대 안 sr-only(absolute)가 스크롤 칸 밖으로 나가 문서 폭을 늘리지 않게 */
.ref-bar { flex: 1 0 3px; min-width: 3px; max-width: 14px; background: var(--accent); border-radius: 1px; }
.ref-bar.k-side, .ref-bar.k-prologue, .ref-bar.k-epilogue { background: var(--amber); }  /* k- 접두사: 종류 이름 side · skip 이 사이드바 .side · 건너뛰기 링크 .skip 과 겹치지 않게 */
.ref-bar.k-skip { background: var(--line-strong); }
.ref-bar.on { outline: 2px solid var(--text); }
.ref-table-wrap { overflow-x: auto; max-height: 70vh; }
.ref-table-wrap thead th { position: sticky; top: 0; z-index: var(--z-raise); background: var(--surface); }  /* 안에서 굴려도 머리 줄이 보인다 */
@media (max-width: 640px) { .ref-table-wrap { max-height: none; } }  /* 휴대폰: 안쪽 스크롤에 갇히지 않고 페이지와 함께 구른다 */
.ref-table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
.ref-table th, .ref-table td { padding: var(--space-6) var(--space-8); border-bottom: 1px solid var(--line); text-align: left; }
.ref-table td.num { text-align: right; font-variant-numeric: tabular-nums; }
.ref-table tr.off td { color: var(--muted); }
.ref-sort { background: none; border: 0; font: inherit; font-weight: 700; color: var(--text-2); cursor: pointer; padding: 0; }
@media (pointer: coarse) { .ref-sort { min-height: var(--touch-min); } }  /* 정렬 머리 버튼 누름 영역 */
.ref-sort.on { color: var(--text); text-decoration: underline; }
.ref-made { margin: 0; padding-left: var(--space-20); }
.ref-body { font-family: var(--serif); line-height: 1.9; max-width: 720px; }
.ref-body p { margin: 0 0 1em; }
@media (max-width: 900px) {
  .ref-pane { position: static; }
  .ref-row-btn { grid-template-columns: 40px 60px minmax(0, 1fr) 60px; min-height: var(--touch-min); }
}
`;
  const el = document.createElement('style');
  el.textContent = css;
  document.head.appendChild(el);
})();

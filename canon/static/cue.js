/* 큐 시트: 집필 실험 화면(서버 cue.py, 사이드바 '본편과 분리', 주소 cue · cue/<화>)과 집필 화면의 큐 시트 카드(cueCard · cuePanel).
   app.js 의 S, actions, api, run, render, header, esc, enc, base, toast, startJob, jobBtn, JOB_PAGES, JOB_DONE_MSG, fmtDateTime 과
   research.js 의 rsInit 을 쓴다.
   한 화를 악보처럼 큐로 나눠 화성 기능(T 안정 · S 쌓기 · D 긴장) · 긴장도 · 템포 · 편성 · 핵심 대사를 먼저 정한다.
   실험 화면은 같은 화를 세 조건(지금 방식 한 번에 · 큐 시트를 주고 한 번에 · 큐마다 이어 쓰기)으로 써서 견주고 작품에는 저장하지 않는다.
   집필 화면은 화에 붙인 큐 시트(Episode.cue_sheet)를 만들고 고친다. 쓰기는 그 시트를 프롬프트 끝에 넣어 한 번에 쓴다.
   고치는 큐 시트는 열쇠('lab:<화>' 실험 · 'ep:<화>' 집필)마다 따로 둔다(S.cueEdits, cueBind). 편집기 · 막대는 둘이 함께 쓴다.
   cueLinesParse · cueLinesText · cueBars · cueCurveOk · cueVoiceGaps 는 DOM 없는 순수 함수 (tests/test_cue.py). */
'use strict';

Object.assign(S, {
  cue: null,       // 서버 값 { candidates, labs, runs, conditions, functions, tempos, voices, cadences, max_cues, max_lines }
  cueLab: null,    // 고른 화 { episode, title, board, sheet, takes, model, run_at }
  cueEdits: {},    // 열쇠마다 고치는 큐 시트 { draft, dirty } (저장 전)
  cueKey: '',      // 지금 화면이 고치는 열쇠
  cueSkip: {},     // 집필: 화마다 '이번 화는 큐 시트 없이 쓰기'
  cueConds: null,  // 고른 조건 Set
  cueEst: null,
  cueTab: '',      // 읽는 본문의 조건
});

const CUE_COLORS = { T: 'var(--act-1)', S: 'var(--act-2)', D: 'var(--act-4)' };

/** 핵심 대사 칸 글('인물 id: 대사' 한 줄에 하나) → [{speaker, text}]. 콜론이 없으면 말하는 인물을 비운다. */
function cueLinesParse(text, max = 3) {
  return String(text || '').split('\n').map((l) => l.trim()).filter(Boolean).map((l) => {
    const m = l.match(/^([^:：«"“]{1,30})[:：]\s*(.+)$/);
    const body = (m ? m[2] : l).trim().replace(/^[«"“「『]+|[»"”」』]+$/g, '').trim();
    return { speaker: m ? m[1].trim() : '', text: body };
  }).filter((x) => x.text).slice(0, max);
}

/** [{speaker, text}] → 핵심 대사 칸 글. */
function cueLinesText(lines) {
  return (lines || []).map((x) => (x.speaker ? `${x.speaker}: ${x.text}` : x.text)).join('\n');
}

/** 진행 막대: 큐마다 너비(목표 글자 수 비율, %)와 높이(긴장도 비율, %). 글자 수가 없으면 같은 너비. */
function cueBars(sheet) {
  const cues = (sheet && sheet.cues) || [];
  const total = cues.reduce((a, c) => a + (c.length || 0), 0);
  return cues.map((c, i) => ({
    i: i + 1, fn: c.function, tension: c.tension,
    w: total ? Math.round(((c.length || 0) / total) * 1000) / 10 : Math.round(1000 / cues.length) / 10,
    h: Math.max(1, Math.min(5, c.tension || 1)) * 20,
  }));
}

/** 진행 점검: 가장 높은 긴장이 뒤쪽 3분의 1 안에 있는지, 같은 기능이 셋 넘게 이어지지 않는지. cue_sheet_prompt 의 규칙과 같다. */
function cueCurveOk(sheet) {
  const cues = (sheet && sheet.cues) || [];
  if (!cues.length) return [];
  const out = [];
  const top = Math.max(...cues.map((c) => c.tension || 0));
  const at = cues.findIndex((c) => (c.tension || 0) === top);
  if (cues.length >= 3 && at < Math.floor((cues.length * 2) / 3)) out.push(`가장 높은 긴장(${top})이 ${at + 1}번 큐로 앞쪽에 있어요. 화 뒤쪽 3분의 1에 두면 끝까지 끌고 가요.`);
  let run = 1;
  for (let i = 1; i < cues.length; i++) {
    run = cues[i].function === cues[i - 1].function ? run + 1 : 1;
    if (run === 4) out.push(`${i - 2}~${i + 1}번 큐가 모두 ${cues[i].function}예요. 같은 기능이 넷 이어지면 진행이 멈춘 것처럼 읽혀요.`);
  }
  if (new Set(cues.map((c) => c.tension)).size === 1) out.push('모든 큐의 긴장도가 같아요. 오르내림이 없으면 화가 평평하게 읽혀요.');
  return out;
}

/** 핵심 대사를 맡았는데 말투(speech_style)가 빈 인물: [{ id, name, cues: [큐 번호] }], 처음 나온 차례.
    핵심 대사는 본문에 글자 그대로 들어가서, 말투가 비면 그 말이 인물답게 지어졌는지 견줄 기준이 없다. 모르는 id 는 뺀다 */
function cueVoiceGaps(sheet, chars) {
  const by = new Map((chars || []).map((c) => [c.id, c]));
  const out = new Map();
  ((sheet && sheet.cues) || []).forEach((c, i) => (c.lines || []).forEach((x) => {
    const ch = by.get(x.speaker);
    if (!ch || (ch.speech_style || '').trim()) return;
    if (!out.has(ch.id)) out.set(ch.id, { id: ch.id, name: ch.name || ch.id, cues: [] });
    const g = out.get(ch.id);
    if (!g.cues.includes(i + 1)) g.cues.push(i + 1);
  }));
  return [...out.values()];
}

/** 이 작품이 화마다 큐 시트를 쓰는지 (cue.on: 작가가 정하지 않았으면 장편 켬 · 단편 끔, 스토리보드와 같은 규칙). */
function cueOn() {
  const v = P().settings && P().settings.cue_sheet;
  return v ?? P().meta.form === 'serial';
}

/** 지금 고치는 큐 시트 { draft, dirty }. */
const cueEd = () => S.cueEdits[S.cueKey] || { draft: null, dirty: false };

/** 화면이 고칠 큐 시트를 고른다. 고치지 않았으면 저장된 시트로 맞추고, 고치던 것이 있으면 그대로 둔다 (화면을 옮겨도 남는다). */
function cueBind(key, saved) {
  S.cueKey = key;
  const cur = S.cueEdits[key];
  if (!cur || !cur.dirty) S.cueEdits[key] = { draft: saved ? structuredClone(saved) : null, dirty: false };
  return S.cueEdits[key];
}

/** 지금 열쇠의 큐 시트가 어디 것인지: 실험(lab) · 집필(ep) · 역설계 실험(rev, revlab.js), 저장된 시트, 스토리보드가 있는지, 만들기 작업.
    noTools 면 편집기에 만들기 버튼 줄을 그리지 않는다 (역설계 시트는 역설계로만 만든다). */
function cueCtx() {
  const [kind, num] = S.cueKey.split(':');
  const n = Number(num);
  if (kind === 'rev') {
    const it = revItem(n);
    return { kind, n, saved: (it && it.sheet) || null, board: false, job: 'rev_parse', noTools: true };
  }
  if (kind === 'ep') {
    const e = ep(n);
    return { kind, n, saved: (e && e.cue_sheet) || null, board: !!(e && e.storyboard), job: 'cues' };
  }
  return { kind, n, saved: (S.cueLab && S.cueLab.sheet) || null, board: !!(S.cueLab && S.cueLab.board), job: 'cue_sheet' };
}

/** 큐 시트 이름표(기능 · 템포 · 편성 · 종지)와 실험할 화 목록. 집필 화면도 이름표를 쓴다. */
async function cueHome() {
  S.cue = await api('GET', `/projects/${enc(S.name)}/cue`).catch((e) => ({ error: e.message }));
  S.cue.name = S.name;
}

async function cueLoad(n) {
  await cueHome();
  if (!S.cueConds) S.cueConds = new Set(['oneshot', 'score', 'cues']);
  const k = Number(n) || null;
  if (!k) { S.cueLab = null; return; }
  if (!S.cueLab || S.cueLab.episode !== k || !(S.cueEdits[`lab:${k}`] || {}).dirty) await cueFetch(k);
}

async function cueFetch(n) {
  S.cueLab = await api('GET', `/projects/${enc(S.name)}/cue/${n}`).catch((e) => ({ error: e.message, episode: n }));
  S.cueEdits[`lab:${n}`] = { draft: S.cueLab.sheet ? structuredClone(S.cueLab.sheet) : null, dirty: false };
  S.cueEst = null;
  if (!S.cueTab && S.cueLab.takes && S.cueLab.takes.length) S.cueTab = S.cueLab.takes[0].condition;
}

const cueLabel = (list, key) => ((S.cue && S.cue[list]) || []).find((x) => x.key === key) || { label: key, about: '' };
const cueUsd = (x) => (x === null || x === undefined ? '가격 모름' : `약 ${x < 1 ? x.toFixed(2) : x.toFixed(1)}달러`);
const cueName = (id) => ((P().characters || []).find((c) => c.id === id) || {}).name || id;

function viewCue() {
  const head = header('본편과 분리', '큐 시트 집필 실험',
    '한 화를 악보처럼 큐로 나눠 진행(안정 · 쌓기 · 긴장), 긴장도, 템포, 편성, 핵심 대사를 먼저 정하고, 같은 화를 세 방식으로 써서 견줘요. 작품 데이터는 바꾸지 않아요.');
  const d = S.cue;
  if (!d) return `${head}<div class="note plain">불러오는 중…</div>`;
  if (d.error) return `${head}<div class="note err">${esc(d.error)}</div>`;
  const n = S.cueLab && S.cueLab.episode;
  const opts = d.candidates.map((c) => `<option value="${c.episode}"${c.episode === n ? ' selected' : ''}>${c.episode}화 ${esc(c.title || '')}${c.written ? ' · 쓴 화' : ''}${d.labs.includes(c.episode) ? ' · 실험 있음' : ''}</option>`).join('');
  const pick = `<section class="card"><div class="field"><label for="cue-ep">실험할 화</label>
    ${d.candidates.length ? `<select id="cue-ep" data-cue-ep="1"><option value="">화를 고르세요</option>${opts}</select>` : '<div class="small">플롯을 확정하고 앞 화를 반영한 화가 없어요. 3단계에서 플롯을 확정하세요.</div>'}</div>
    <p class="small">반영이 끝난 화는 그 화를 쓰기 직전 상태로 되돌린 사본에서 써요. 원래 본문과 견줄 수 있어요.</p></section>`;
  if (!n) return `${head}${cueIntro()}${pick}${cueRuns()}`;
  if (S.cueLab.error) return `${head}${pick}<div class="note err">${esc(S.cueLab.error)}</div>`;
  cueBind(`lab:${n}`, S.cueLab.sheet);
  return `${head}${pick}${cueScore()}${cueEditor()}${cueRunCard()}${cueResults()}${cueRuns()}`;
}

function cueIntro() {
  const d = S.cue;
  const li = (list) => d[list].map((x) => `<dt>${esc(x.key)} ${esc(x.label)}</dt><dd class="small">${esc(x.about)}</dd>`).join('');
  return `<section class="card"><h2>큐 시트란</h2>
    <p class="small">화성악이 곡을 코드 진행으로 미리 짜듯, 한 화를 큐(연주 단위) 4~10개로 나눠 큐마다 할 일과 핵심 대사를 먼저 정해요. 본문을 쓰는 AI는 이 악보를 받아 연주해요.</p>
    <dl class="ab-kv">${li('functions')}</dl><dl class="ab-kv">${li('cadences')}</dl>
    <h3>견주는 조건</h3><dl class="ab-kv">${d.conditions.map((c) => `<dt>${esc(c.label)}</dt><dd class="small">${esc(c.about)}</dd>`).join('')}</dl>
    <p class="small">둘째 조건은 설계(악보)만의 효과, 셋째 조건은 나눠 쓰기의 효과를 봐요. 채점은 AI 없이 핵심 대사가 들어갔는지, 같은 문장 되풀이, 큐 이음매, 큐마다 분량 · 템포 · 편성을 세요.</p></section>`;
}

/** 진행 막대와 점검. wrap 을 끄면 카드 없이 (집필 화면의 큐 시트 카드 안에 넣는다). */
function cueScore(sh = cueEd().draft, wrap = true) {
  if (!sh || !sh.cues.length) return '';
  const bars = cueBars(sh).map((b) => `<div class="cue-bar" style="flex:${b.w} 1 0;height:${b.h}%;background:${CUE_COLORS[b.fn] || 'var(--chip)'}" title="${b.i}번 큐 · ${esc(cueLabel('functions', b.fn).label)} · 긴장 ${b.tension}"><span>${b.fn}</span></div>`).join('');
  const warn = cueCurveOk(sh);
  const body = `<div class="between"><${wrap ? 'h2' : 'h3'}>진행</${wrap ? 'h2' : 'h3'}><span class="small">조성 ${esc(sh.key || '정하지 않음')} · 끝 ${esc(cueLabel('cadences', sh.cadence).label)}</span></div>
    <div class="cue-bars" role="img" aria-label="큐마다 긴장도 막대">${bars}</div>
    <div class="small">막대 너비는 목표 글자 수, 높이는 긴장도예요. 색은 기능(T 안정 · S 쌓기 · D 긴장)이에요.</div>
    ${warn.length ? `<ul class="small" style="padding-left:18px;margin:6px 0 0">${warn.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>` : ''}`;
  return wrap ? `<section class="card">${body}</section>` : `<div class="cue-score">${body}</div>`;
}

function cueSelect(list, path, val) {
  // 기능만 글자(T · S · D)를 함께 보인다. 진행 막대와 본문 머리가 그 글자로 부른다
  return `<select data-cue="${path}">${S.cue[list].map((x) => `<option value="${x.key}"${x.key === val ? ' selected' : ''}>${esc(list === 'functions' ? `${x.key} ${x.label}` : x.label)}</option>`).join('')}</select>`;
}

/** 큐 시트 편집기 (지금 열쇠 cueCtx). wrap 을 끄면 카드 없이 (집필 화면의 큐 시트 카드 안에 넣는다). off 면 만들기 · 저장을 막는다. */
function cueEditor(wrap = true, off = false) {
  const c = cueCtx();
  const { draft: sh, dirty } = cueEd();
  const ai = jobBtn(c.job, c.n, c.saved ? 'AI로 다시 만들기' : 'AI로 큐 시트 만들기');
  const dis = off ? ' disabled' : '';
  const tools = c.noTools ? '' : `<div class="row"><button type="button" class="btn small${c.saved ? '' : ' primary'}" data-action="cueMake"${off ? dis : ai.attr}>${ai.label}</button>
    <button type="button" class="btn small" data-action="cueFromBoard"${dis}>${c.board ? '스토리보드' : '플롯 사건'}에서 뼈대 만들기 (AI 없이)</button></div>`;
  const card = (inner) => (wrap ? `<section class="card">${inner}</section>` : inner);
  if (!sh) return card(wrap ? `<h2>큐 시트</h2><div class="small">아직 없어요. AI에게 만들게 하거나 ${c.board ? '스토리보드 장면' : '플롯 사건'}마다 큐 하나인 뼈대에서 시작하세요.</div>${tools}` : tools);
  const tens = [1, 2, 3, 4, 5];
  const rows = sh.cues.map((c, i) => `<div class="cue-row">
      <div class="between"><strong>${i + 1}번 큐${c.scene ? ` <span class="small">장면 ${c.scene}</span>` : ''}</strong>
        <span class="row" style="gap:4px"><button type="button" class="btn small ghost" data-action="cueMove" data-arg="${i}:-1"${i ? '' : ' disabled'} aria-label="${i + 1}번 큐 위로">↑</button>
        <button type="button" class="btn small ghost" data-action="cueMove" data-arg="${i}:1"${i < sh.cues.length - 1 ? '' : ' disabled'} aria-label="${i + 1}번 큐 아래로">↓</button>
        <button type="button" class="btn small ghost" data-action="cueDrop" data-arg="${i}">빼기</button></span></div>
      <div class="cue-knobs">
        <label class="small">기능 ${cueSelect('functions', `cues.${i}.function`, c.function)}</label>
        <label class="small">긴장 <select data-cue="cues.${i}.tension" data-num="1">${tens.map((t) => `<option${t === c.tension ? ' selected' : ''}>${t}</option>`).join('')}</select></label>
        <label class="small">템포 ${cueSelect('tempos', `cues.${i}.tempo`, c.tempo)}</label>
        <label class="small">편성 ${cueSelect('voices', `cues.${i}.voice`, c.voice)}</label>
        <label class="small">글자 <input type="number" min="0" step="100" style="width:90px" data-cue="cues.${i}.length" data-num="1" value="${c.length || 0}"></label>
      </div>
      <label class="small">일어나는 일<input data-cue="cues.${i}.beat" value="${esc(c.beat)}"></label>
      <label class="small">핵심 대사 <span class="small">(한 줄에 하나, '인물 id: 대사', ${S.cue.max_lines}개까지. 본문에 글자 그대로 들어가요)</span>
        <textarea rows="2" data-cue-lines="${i}">${esc(cueLinesText(c.lines))}</textarea></label>
      ${c.lines.length ? `<div class="small">${c.lines.map((x) => `${esc(cueName(x.speaker) || '?')}: «${esc(x.text)}»`).join(' · ')}</div>` : ''}
      <label class="small">끝 상태<input data-cue="cues.${i}.exit" value="${esc(c.exit)}"></label>
    </div>`).join('');
  const total = sh.cues.reduce((a, c) => a + (c.length || 0), 0);
  const gaps = cueVoiceGaps(sh, P().characters);
  const gapNote = gaps.length ? `<div class="note warn"><strong>말투가 빈 인물이 핵심 대사를 맡았어요</strong>
      <ul>${gaps.map((g) => `<li><a href="${base()}/cast/${enc(g.id)}">${esc(g.name)}</a> · ${g.cues.join(', ')}번 큐</li>`).join('')}</ul>
      <span class="small">핵심 대사는 본문에 글자 그대로 들어가요. 인물 카드에서 말투를 채우면 큐 시트를 만들 때와 쓸 때 그 말투를 따라요.</span></div>` : '';
  const H = wrap ? 'h2' : 'h3';
  return card(`<div class="between"><${H}>큐 시트 <span class="small">큐 ${sh.cues.length}개 · 약 ${total.toLocaleString()}자 · ${esc(CUE_BY[c.saved ? c.saved.made_by : 'author'] || '')}</span></${H}>
      <span class="row" style="gap:6px"><button type="button" class="btn small" data-action="cueSave"${dirty && !off ? '' : ' disabled'}>저장</button>${dirty ? '<button type="button" class="btn small ghost" data-action="cueReset">되돌리기</button>' : ''}</span></div>
    ${tools}
    ${gapNote}
    <div class="cue-knobs"><label class="small">조성 (정서의 기준선)<input data-cue="key" value="${esc(sh.key)}"></label>
      <label class="small">화 끝 종지 ${cueSelect('cadences', 'cadence', sh.cadence)}</label></div>
    <div class="cue-list">${rows}</div>
    <button type="button" class="btn small" data-action="cueAdd"${sh.cues.length >= S.cue.max_cues ? ' disabled' : ''}>큐 더하기</button>
    ${dirty ? `<div class="note warn">저장하지 않은 고침이 있어요. ${{ ep: '쓰기', rev: '되돌려 쓰기' }[c.kind] || '실험'}는 저장한 큐 시트로 해요.</div>` : ''}`);
}

const CUE_BY = { ai: 'AI', board: '뼈대', author: '작가', both: 'AI + 작가' };

const cuePlan = () => ({ conditions: [...S.cueConds] });

function cueRunCard() {
  const n = S.cueLab.episode;
  const has = !!S.cueLab.sheet;
  const conds = S.cue.conditions.map((c) => {
    const off = c.key !== 'oneshot' && !has;
    return `<label class="row small" style="gap:6px"><input type="checkbox" data-cue-cond="${c.key}"${S.cueConds.has(c.key) && !off ? ' checked' : ''}${off ? ' disabled' : ''}>${esc(c.label)}</label>`;
  }).join('');
  const ready = [...S.cueConds].filter((k) => k === 'oneshot' || has).length > 0 && !cueEd().dirty;
  const est = S.cueEst;
  const estHtml = est ? `<div style="overflow-x:auto"><table class="sw-table"><thead><tr><th>조건</th><th>요청</th><th>입력 토큰</th><th>출력 토큰</th><th>비용</th></tr></thead><tbody>
      ${est.rows.map((r) => `<tr><td>${esc(r.label)}</td><td>${r.calls}</td><td>${r.input_tokens.toLocaleString()}</td><td>${r.output_tokens.toLocaleString()}</td><td>${cueUsd(r.usd)}</td></tr>`).join('')}
      <tr><th>합</th><td>${est.calls}</td><td></td><td></td><th>${cueUsd(est.usd)}</th></tr></tbody></table></div>
      <div class="small">${esc(est.model)} 가격표 기준 · ${esc(est.note)} 큐마다 이어 쓰기는 요청마다 앞 요청과 응답을 통째로 품어서, 캐시가 맞으면 입력 비용이 크게 줄어요.</div>` : '';
  const go = jobBtn('cue_run', n, '실험 시작');
  return `<section class="card"><h2>실험</h2>
    <div class="row" style="gap:16px">${conds}</div>
    ${has ? '' : '<div class="small">큐 시트가 있어야 둘째 · 셋째 조건을 쓸 수 있어요.</div>'}
    <div class="row"><button type="button" class="btn small" data-action="cueEstimate"${ready ? '' : ' disabled'}>비용 추정</button></div>
    ${estHtml}
    <div class="note warn">시작하면 실제 AI를 불러 본문을 써요. 비용이 들어요. 조건을 둘 넘게 고르면 이 화의 블라인드 비교본을 새로 만들어 이전 비교본은 지워져요.</div>
    <div class="row"><button type="button" class="btn primary" data-action="cueStart"${ready && est ? '' : ' disabled'}${go.attr}>${go.label}</button>${est ? '' : '<span class="small">비용 추정을 먼저 보세요.</span>'}</div></section>`;
}

const cuePct = (x) => (x === null || x === undefined ? '-' : `${Math.round(x * 100)}%`);
const cueYes = (x) => (x === null || x === undefined ? '-' : x ? '맞음' : '어긋남');

function cueResults() {
  const takes = S.cueLab.takes || [];
  if (!takes.length) return '';
  const rows = takes.map(({ score: s }) => `<tr><td>${esc(s.label)}${s.stale ? ' <span class="ab-pill">시트 바뀜</span>' : ''}</td><td>${s.chars.toLocaleString()}</td><td>${s.calls}</td><td>${s.prompt_tokens.toLocaleString()}</td>
      <td>${s.lines_total ? `${s.lines_hit}/${s.lines_total}` : '-'}</td><td>${s.repeats.length}</td>
      <td>${s.seams.length ? `${s.seams.filter((x) => x.repeat).length}/${s.seams.length}` : '-'}</td><td>${s.rows.length ? s.closing.length : '-'}</td><td>${s.rows.length ? `${s.still.length}/${s.rows.length - 1}` : '-'}</td><td>${s.rows.length ? `${s.cut.length}/${s.rows.length - 1}` : '-'}</td><td>${cueYes(s.tempo_order)}</td>
      <td>${cuePct(s.dialogue_ratio)}</td><td>${s.sentence_len}</td><td>${s.ai_patterns}</td></tr>`).join('');
  const cur = takes.find((t) => t.condition === S.cueTab) || takes[0];
  const tabs = takes.map((t) => `<button type="button" role="tab" aria-selected="${t === cur}" data-action="cueTabSet" data-arg="${t.condition}">${esc(t.score.label)}</button>`).join('');
  return `<section class="card"><div class="between"><h2>결과 <span class="small">${esc(S.cueLab.model)} · ${esc(fmtDateTime(S.cueLab.run_at))}</span></h2>
      ${takes.length > 1 ? `<button type="button" class="btn small" data-action="cueCompare">블라인드 비교로</button>` : ''}</div>
    <div style="overflow-x:auto"><table class="sw-table"><thead><tr><th>조건</th><th>글자</th><th>요청</th><th>요청 토큰</th><th>핵심 대사</th><th>되풀이 문장</th><th>이음매 되풀이</th><th>여운으로 닫힌 큐</th><th>정지 장면 끝</th><th>줄표로 자른 끝</th><th>템포</th><th>대사 비율</th><th>문장 길이</th><th>쇠맛 경고</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="small">핵심 대사는 큐 시트의 대사가 글자 그대로 들어간 수예요. 이음매 되풀이는 다음 큐 첫 문장이 앞 큐 끝을 다시 말한 곳, 여운으로 닫힌 큐는 마지막이 아닌데 짧은 끝 문장으로 맺은 큐, 정지 장면 끝은 인물이 서 있거나 바라보는 한 줄로 맺은 큐, 줄표로 자른 끝은 문장을 '——'나 말줄임으로 자르고 넘긴 큐예요. 템포는 빠른 큐의 문장이 느린 큐보다 짧은지예요.</p>
    <div class="tabs" role="tablist" aria-label="조건별 본문">${tabs}</div>
    ${cueTake(cur)}</section>`;
}

function cueTake(t) {
  const s = t.score;
  const notes = [];
  if (s.missed.length) notes.push(`빠진 핵심 대사: ${s.missed.map((x) => `«${esc(x)}»`).join(' · ')}`);
  if (s.repeats.length) notes.push(`되풀이 문장: ${s.repeats.slice(0, 3).map((x) => `«${esc(x)}»`).join(' · ')}`);
  const head = notes.length ? `<ul class="small" style="padding-left:18px">${notes.map((x) => `<li>${x}</li>`).join('')}</ul>` : '';
  if (!t.parts.length || !s.rows.length) return `${head}<div class="cue-text">${esc(t.text)}</div>`;
  const seam = Object.fromEntries(s.seams.map((x) => [x.after, x]));
  return head + t.parts.map((part, i) => {
    const r = s.rows[i];
    const sm = seam[i];
    return `${sm && sm.repeat ? `<div class="note warn small">이음매: 앞 큐 끝을 다시 말해요 (겹침 ${cuePct(sm.overlap)})</div>` : ''}
      <div class="cue-part"><div class="small cue-part-head">${i + 1}번 큐 · ${esc(r.function)} · 긴장 ${r.tension} · ${esc(cueLabel('tempos', r.tempo).label)} · ${esc(cueLabel('voices', r.voice).label)}
        — ${r.chars.toLocaleString()}/${(r.target || 0).toLocaleString()}자 · 문장 ${r.sentence_len} · 대사 ${cuePct(r.dialogue_ratio)}${r.voice_ok === false ? ' · 편성 어긋남' : ''}${s.closing.includes(i + 1) ? ' · 여운으로 닫음' : ''}${s.still.includes(i + 1) ? ' · 정지 장면으로 끝' : ''}${s.cut.includes(i + 1) ? ' · 줄표로 자름' : ''}</div>
      <div class="cue-text">${esc(part)}</div></div>`;
  }).join('');
}

function cueRuns() {
  const runs = (S.cue && S.cue.runs) || [];
  if (!runs.length) return '';
  return `<section class="card"><h2>지난 실험</h2><ul class="small" style="padding-left:18px">${runs.map((r) => `<li>${esc(fmtDateTime(r.time))} · <a href="${base()}/cue/${r.episode}">${r.episode}화</a> · ${esc(r.model || '')} · 큐 ${r.cues}개 —
    ${r.summary.map((s) => `${esc(s.label)} ${s.chars.toLocaleString()}자${s.lines_total ? ` 대사 ${s.lines_hit}/${s.lines_total}` : ''}`).join(' / ')}</li>`).join('')}</ul></section>`;
}

// ----- 집필 화면: 화에 붙인 큐 시트 (Episode.cue_sheet) -----
// write.js 의 viewWrite 가 본문이 없는 화에는 cueCard, 쓴 화에는 cuePanel 을 부른다.
// 쓰기를 누르면 서버가 큐 시트가 없을 때 먼저 만들고(작업 write 의 cues), 쓰기 프롬프트 끝에 넣어 한 번에 쓴다.

/** 서버가 센 값이 지금 작품과 맞는지 가르는 열쇠: 큐 시트, 스토리보드, 직전 화 본문, 플롯, 본문 (cue.ep_basis 의 입력). */
function cueSig(n) {
  const e = ep(n);
  const prev = ep(n - 1);
  return `${S.name}:${n}:${JSON.stringify(e && e.cue_sheet)}:${JSON.stringify(e && e.storyboard)}:${prev ? prev.text.length : 0}:${JSON.stringify(e && e.plot)}:${e ? e.text.length : 0}`;
}

/** GET …/cue-sheet 결과 (낡음, 핵심 대사가 들어간 수). 열쇠가 바뀌면 다시 받아 그린다. 받는 동안은 null. 이름표도 함께 받는다. */
function cueView(n) {
  if (!S.cue || S.cue.name !== S.name) {
    if (!S.cueHomeLoading) {
      S.cueHomeLoading = true;
      cueHome().then(render).finally(() => { S.cueHomeLoading = false; });
    }
  }
  const sig = cueSig(n);
  if (S.cueViewSig === sig) return S.cueViewData;
  S.cueViewSig = sig;
  S.cueViewData = null;
  api('GET', `/projects/${enc(S.name)}/episodes/${n}/cue-sheet`).then((v) => {
    if (S.cueViewSig === sig) { S.cueViewData = v; render(); }
  }).catch(() => { /* 받지 못하면 계산 값 없이 그린다 */ });
  return null;
}

/** 큐 시트 켜기 · 끄기 (Settings.cue_sheet). 집필 화면의 쓰기 시작 칸(writeStart) 아래 줄에 둔다. */
function cueToggle() {
  const on = cueOn();
  return `<div class="field"><span class="small">화별 큐 시트</span><button type="button" class="btn small${on ? ' on' : ''}" aria-pressed="${on}" data-action="cueToggle" title="쓰기 전에 큐마다 긴장 · 템포 · 편성 · 핵심 대사 · 분량을 정하고 쓰기 요청 끝에 넣어요. 화당 AI 호출이 하나 늘어요">큐 시트 ${on ? '켜짐' : '꺼짐'}</button></div>`;
}

/** 쓰기 작업에 붙이는 값: 이 화를 큐 시트 없이 쓰기로 골랐으면 cues: none. */
const cueWriteArg = (n) => (S.cueSkip[n] ? { cues: 'none' } : {});

/** 본문이 없는 화의 큐 시트 카드. 큐 시트를 쓰는 작품이거나 이 화에 큐 시트가 있으면 보인다. */
function cueCard(n, blocked) {
  const e = ep(n);
  if (!e || e.text || e.status !== 'confirmed' || (!cueOn() && !e.cue_sheet)) return '';
  const v = cueView(n);
  if (!S.cue || S.cue.error || !S.cue.functions) return '';
  cueBind(`ep:${n}`, e.cue_sheet);
  const busy = jobFor('cues', n) || jobFor('write', n) || jobFor('board', n);
  const off = !!(blocked.length || autoOn() || busy);
  const skip = !!S.cueSkip[n];
  const s = e.cue_sheet;
  const { dirty } = cueEd();
  const head = `<div class="between"><h2>큐 시트 <span class="small">${s ? `큐 ${s.cues.length}개 · ${esc(CUE_BY[s.made_by] || '')}` : '아직 없음'}</span></h2>
      ${s ? `<button type="button" class="btn small ghost" data-action="cueClear" data-arg="${n}"${off ? ' disabled' : ''}>지우기</button>` : ''}</div>`;
  const lead = s ? (v && v.stale ? `<div class="note warn">큐 시트를 만든 뒤 직전 화 본문, 플롯, 인물 상태, 스토리보드 중 하나가 바뀌었어요. 다시 만들거나, 그대로 쓰려면 내용을 확인하세요.</div>` : '')
    : `<p class="small">${skip ? '이번 화는 큐 시트 없이 써요.' : `쓰기를 누르면 AI가 ${e.storyboard ? '스토리보드 장면 순서를 받아 ' : ''}큐 시트를 먼저 만들고 그 위에 써요. 먼저 보고 고치려면 아래에서 만드세요.`}</p>`;
  const body = s ? `${cueScore(cueEd().draft, false)}<details class="cue-edit"${dirty ? ' open' : ''}><summary>큐 시트 고치기${dirty ? ' · 저장하지 않은 고침' : ''}</summary>${cueEditor(false, off)}</details>`
    : cueEditor(false, off);
  return `<section class="card cue-card" aria-label="${n}화 큐 시트">${head}${lead}${skip ? '' : body}
    <label class="check-row small"><input type="checkbox" data-cue-skip="${n}"${skip ? ' checked' : ''}${off ? ' disabled' : ''}><span>이번 화는 큐 시트 없이 쓰기</span></label></section>`;
}

/** 본문을 쓴 화: 쓸 때 쓴 큐 시트와 핵심 대사가 들어간 수를 접어 둔다 (다시 생성도 이 큐 시트를 그대로 쓴다). */
function cuePanel(n) {
  const e = ep(n);
  if (!e || !e.text || !e.cue_sheet) return '';
  const v = cueView(n);
  if (!S.cue || S.cue.error || !S.cue.functions) return '';
  const hits = v && v.total ? ` · 핵심 대사 ${v.hit}/${v.total}` : '';
  const missed = v && v.missed.length ? `<div class="note warn small">본문에 없는 핵심 대사: ${v.missed.map((x) => `«${esc(x)}»`).join(' · ')}</div>` : '';
  const lines = e.cue_sheet.cues.map((c) => `<li>${esc(c.function)} · 긴장 ${c.tension} · ${esc(cueLabel('voices', c.voice).label)} — ${esc(c.beat)}${c.lines.length ? `<br>${c.lines.map((x) => `${esc(cueName(x.speaker) || '?')}: «${esc(x.text)}»`).join(' · ')}` : ''}</li>`).join('');
  return `<details class="card cue-card cue-done"><summary>이 화를 쓴 큐 시트 · 큐 ${e.cue_sheet.cues.length}개${hits}</summary>
    ${missed}${cueScore(e.cue_sheet, false)}<ol class="small cue-sum">${lines}</ol>
    <p class="small">다시 생성은 이 큐 시트를 그대로 써요.</p></details>`;
}

/** 'cues.2.tension' 같은 경로에 값을 넣는다. */
function cueSet(path, val) {
  const ed = cueEd();
  const keys = path.split('.');
  let o = ed.draft;
  for (const k of keys.slice(0, -1)) o = o[k];
  o[keys[keys.length - 1]] = val;
  ed.dirty = true;
}

document.addEventListener('input', (e) => {
  const d = e.target.dataset || {};
  const ed = cueEd();
  if (!ed.draft) return;
  if (d.cue && e.target.tagName !== 'SELECT') { cueSet(d.cue, d.num ? Number(e.target.value) || 0 : e.target.value); return; }
  if (d.cueLines !== undefined) { ed.draft.cues[Number(d.cueLines)].lines = cueLinesParse(e.target.value, S.cue.max_lines); ed.dirty = true; }
});

document.addEventListener('change', (e) => {
  const d = e.target.dataset || {};
  if (d.cueEp) { if (e.target.value) location.hash = `${base()}/cue/${e.target.value}`; return; }
  if (d.cueCond !== undefined) { S.cueConds[e.target.checked ? 'add' : 'delete'](d.cueCond); S.cueEst = null; render(); return; }
  if (d.cueSkip !== undefined) { S.cueSkip[d.cueSkip] = e.target.checked; render(); return; }
  const ed = cueEd();
  if (d.cue && ed.draft) { cueSet(d.cue, d.num ? Number(e.target.value) || 0 : e.target.value); S.cueEst = null; render(); return; }
  if ((d.cue !== undefined || d.cueLines !== undefined) && ed.draft) render();  // 막대 · 대사 미리보기 · 저장 버튼
});

JOB_PAGES.cue_sheet = ['cue'];
JOB_PAGES.cue_run = ['cue'];
JOB_PAGES.cues = ['write'];
JOB_DONE_MSG.cues = (j) => `${j.ep}화 큐 시트를 만들었어요: 큐 ${j.result ? j.result.cues : 0}개.`;
JOB_DONE_MSG.cue_sheet = (j) => {
  if (S.cueLab && S.cueLab.episode === j.ep) cueFetch(j.ep).then(render);
  return `${j.ep}화 큐 시트를 만들었어요: 큐 ${j.result ? j.result.cues : 0}개.`;
};
JOB_DONE_MSG.cue_run = (j) => {
  cueLoad(j.ep).then(() => (S.cueLab && S.cueLab.episode === j.ep ? cueFetch(j.ep) : null)).then(render);
  return `${j.ep}화 큐 시트 실험이 끝났어요: 본문 ${j.result ? j.result.takes : 0}개.`;
};

/** 저장한 뒤 지금 열쇠의 고침을 저장된 시트로 맞춘다. */
function cueSynced() {
  const c = cueCtx();
  S.cueEdits[S.cueKey] = { draft: c.saved ? structuredClone(c.saved) : null, dirty: false };
  S.cueEst = null;
}

Object.assign(actions, {
  cueMake() {
    const c = cueCtx();
    if (c.saved && !confirm(c.saved.made_by === 'ai' ? '지금 큐 시트를 AI가 만든 새 시트로 바꿀까요?' : '고친 큐 시트예요. 새로 만들면 고친 내용이 사라져요. 바꿀까요?')) return;
    startJob(c.job, c.n);
  },
  async cueFromBoard() {
    const c = cueCtx();
    if (c.saved && !confirm('지금 큐 시트를 뼈대로 바꿀까요?')) return;
    await run('뼈대 만드는 중', async () => {
      if (c.kind === 'ep') {
        await saveIfDirty();
        S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${c.n}/cue-sheet/board`);
      } else S.cueLab = await api('POST', `/projects/${enc(S.name)}/cue/${c.n}/sheet/board`);
      cueSynced();
    });
  },
  async cueSave() {
    const c = cueCtx();
    await run('큐 시트 저장 중', async () => {
      if (c.kind === 'ep') {
        await saveIfDirty();
        S.project = await api('PUT', `/projects/${enc(S.name)}/episodes/${c.n}/cue-sheet`, cueEd().draft);
      } else if (c.kind === 'rev') S.revLab = await api('PUT', `/revlab/${S.revLab.id}/episodes/${c.n}/sheet`, cueEd().draft);
      else S.cueLab = await api('PUT', `/projects/${enc(S.name)}/cue/${c.n}/sheet`, cueEd().draft);
      cueSynced();
    });
    toast('큐 시트를 저장했어요');
  },
  cueReset() { cueSynced(); render(); },
  async cueClear(n) {
    if (!confirm(`${n}화 큐 시트를 지울까요? 지우면 큐 시트를 쓰는 작품은 쓰기를 누를 때 새로 만들어요.`)) return;
    await run('큐 시트 지우는 중', async () => {
      await saveIfDirty();
      S.project = await api('DELETE', `/projects/${enc(S.name)}/episodes/${n}/cue-sheet`);
      S.cueEdits[`ep:${n}`] = { draft: null, dirty: false };
    });
  },
  async cueToggle() {
    const on = !cueOn();
    await run('설정 바꾸는 중', async () => {
      S.project = await api('PUT', `/projects/${enc(S.name)}/cue-setting`, { on });
    });
  },
  cueAdd() {
    const ed = cueEd();
    const last = ed.draft.cues[ed.draft.cues.length - 1];
    ed.draft.cues.push({ scene: last ? last.scene : 0, function: 'S', tension: 3, tempo: 'mid', voice: 'action', beat: '', lines: [], exit: '', length: last ? last.length : 1000 });
    ed.dirty = true; render();
  },
  cueDrop(i) { const ed = cueEd(); ed.draft.cues.splice(Number(i), 1); ed.dirty = true; render(); },
  cueMove(arg) {
    const [i, dir] = arg.split(':').map(Number);
    const ed = cueEd();
    const xs = ed.draft.cues;
    [xs[i], xs[i + dir]] = [xs[i + dir], xs[i]];
    ed.dirty = true; render();
  },
  async cueEstimate() {
    await run('비용 추정 중', async () => {
      S.cueEst = await api('POST', `/projects/${enc(S.name)}/cue/${S.cueLab.episode}/estimate`, cuePlan());
    });
  },
  cueStart() { startJob('cue_run', S.cueLab.episode, cuePlan()); },
  cueTabSet(k) { S.cueTab = k; render(); },
  cueCompare() {
    if (!S.rs || S.rs.name !== S.name) rsInit(S.name);
    S.rs.compareEp = S.cueLab.episode;
    S.rs.tab = 'compare';
    location.hash = `${base()}/research`;
  },
});

(() => {
  const css = `
.cue-bars { display: flex; align-items: flex-end; gap: 3px; height: 120px; margin: 8px 0; padding: 0 2px; border-bottom: 1px solid var(--line); }
.cue-bar { min-width: 14px; border-radius: 4px 4px 0 0; display: flex; align-items: flex-start; justify-content: center; }
.cue-bar span { font-size: 0.6875rem; font-weight: 700; color: var(--text); padding-top: 2px; }
.cue-list { display: flex; flex-direction: column; gap: 10px; margin: 10px 0; }
.cue-row { border: 1px solid var(--line); border-radius: 10px; padding: 10px; display: flex; flex-direction: column; gap: 6px; }
.cue-row input, .cue-row textarea { width: 100%; }
.cue-knobs { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: flex-end; }
.cue-knobs select { width: auto; }
.cue-part { border-left: 3px solid var(--line-strong); padding-left: 10px; margin: 10px 0; }
.cue-part-head { margin-bottom: 4px; }
.cue-text { white-space: pre-wrap; font-family: var(--serif); line-height: 1.8; }
.cue-card { display: flex; flex-direction: column; gap: 8px; }
.cue-card .cue-bars { height: 80px; }
.cue-edit > summary, .cue-done > summary { cursor: pointer; font-weight: 600; }
.cue-sum { padding-left: 18px; display: flex; flex-direction: column; gap: 4px; }
`;
  const el = document.createElement('style');
  el.textContent = css;
  document.head.appendChild(el);
})();

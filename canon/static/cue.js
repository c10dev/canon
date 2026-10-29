/* 큐 시트 집필 실험 (서버 cue.py, 사이드바 '본편과 분리', 주소 cue · cue/<화>).
   app.js 의 S, actions, api, run, render, header, esc, enc, base, toast, startJob, jobBtn, JOB_PAGES, JOB_DONE_MSG, fmtDateTime 과
   research.js 의 rsInit 을 쓴다.
   한 화를 악보처럼 큐로 나눠 화성 기능(T 안정 · S 쌓기 · D 긴장) · 긴장도 · 템포 · 편성 · 핵심 대사를 먼저 정하고,
   같은 화를 세 조건(지금 방식 한 번에 · 큐 시트를 주고 한 번에 · 큐마다 이어 쓰기)으로 써서 견준다. 작품에는 저장하지 않는다.
   cueLinesParse · cueLinesText · cueBars · cueCurveOk · cueVoiceGaps 는 DOM 없는 순수 함수 (tests/test_cue.py). */
'use strict';

Object.assign(S, {
  cue: null,       // 서버 값 { candidates, labs, runs, conditions, functions, tempos, voices, cadences, max_cues, max_lines }
  cueLab: null,    // 고른 화 { episode, title, board, sheet, takes, model, run_at }
  cueDraft: null,  // 고치는 큐 시트 (저장 전)
  cueDirty: false,
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

async function cueLoad(n) {
  S.cue = await api('GET', `/projects/${enc(S.name)}/cue`).catch((e) => ({ error: e.message }));
  if (!S.cueConds) S.cueConds = new Set(['oneshot', 'score', 'cues']);
  const k = Number(n) || null;
  if (!k) { S.cueLab = null; S.cueDraft = null; return; }
  if (!S.cueLab || S.cueLab.episode !== k || !S.cueDirty) await cueFetch(k);
}

async function cueFetch(n) {
  S.cueLab = await api('GET', `/projects/${enc(S.name)}/cue/${n}`).catch((e) => ({ error: e.message, episode: n }));
  S.cueDraft = S.cueLab.sheet ? structuredClone(S.cueLab.sheet) : null;
  S.cueDirty = false;
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

function cueScore() {
  const sh = S.cueDraft;
  if (!sh || !sh.cues.length) return '';
  const bars = cueBars(sh).map((b) => `<div class="cue-bar" style="flex:${b.w} 1 0;height:${b.h}%;background:${CUE_COLORS[b.fn] || 'var(--chip)'}" title="${b.i}번 큐 · ${esc(cueLabel('functions', b.fn).label)} · 긴장 ${b.tension}"><span>${b.fn}</span></div>`).join('');
  const warn = cueCurveOk(sh);
  return `<section class="card"><div class="between"><h2>진행</h2><span class="small">조성 ${esc(sh.key || '정하지 않음')} · 끝 ${esc(cueLabel('cadences', sh.cadence).label)}</span></div>
    <div class="cue-bars" role="img" aria-label="큐마다 긴장도 막대">${bars}</div>
    <div class="small">막대 너비는 목표 글자 수, 높이는 긴장도예요. 색은 기능(T 안정 · S 쌓기 · D 긴장)이에요.</div>
    ${warn.length ? `<ul class="small" style="padding-left:18px;margin:6px 0 0">${warn.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>` : ''}</section>`;
}

function cueSelect(list, path, val) {
  // 기능만 글자(T · S · D)를 함께 보인다. 진행 막대와 본문 머리가 그 글자로 부른다
  return `<select data-cue="${path}">${S.cue[list].map((x) => `<option value="${x.key}"${x.key === val ? ' selected' : ''}>${esc(list === 'functions' ? `${x.key} ${x.label}` : x.label)}</option>`).join('')}</select>`;
}

function cueEditor() {
  const n = S.cueLab.episode;
  const sh = S.cueDraft;
  const ai = jobBtn('cue_sheet', n, 'AI로 큐 시트 만들기');
  const tools = `<div class="row"><button type="button" class="btn small primary" data-action="cueMake"${ai.attr}>${ai.label}</button>
    <button type="button" class="btn small" data-action="cueFromBoard">${S.cueLab.board ? '스토리보드' : '플롯 사건'}에서 뼈대 만들기 (AI 없이)</button></div>`;
  if (!sh) return `<section class="card"><h2>큐 시트</h2><div class="small">아직 없어요. AI에게 만들게 하거나 ${S.cueLab.board ? '스토리보드 장면' : '플롯 사건'}마다 큐 하나인 뼈대에서 시작하세요.</div>${tools}</section>`;
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
  return `<section class="card"><div class="between"><h2>큐 시트 <span class="small">큐 ${sh.cues.length}개 · 약 ${total.toLocaleString()}자 · ${esc({ ai: 'AI', board: '뼈대', author: '작가', both: 'AI + 작가' }[S.cueLab.sheet ? S.cueLab.sheet.made_by : 'author'] || '')}</span></h2>
      <span class="row" style="gap:6px"><button type="button" class="btn small" data-action="cueSave"${S.cueDirty ? '' : ' disabled'}>저장</button>${S.cueDirty ? '<button type="button" class="btn small ghost" data-action="cueReset">되돌리기</button>' : ''}</span></div>
    ${tools}
    ${gapNote}
    <div class="cue-knobs"><label class="small">조성 (정서의 기준선)<input data-cue="key" value="${esc(sh.key)}"></label>
      <label class="small">화 끝 종지 ${cueSelect('cadences', 'cadence', sh.cadence)}</label></div>
    <div class="cue-list">${rows}</div>
    <button type="button" class="btn small" data-action="cueAdd"${sh.cues.length >= S.cue.max_cues ? ' disabled' : ''}>큐 더하기</button>
    ${S.cueDirty ? '<div class="note warn">저장하지 않은 고침이 있어요. 실험은 저장한 큐 시트로 써요.</div>' : ''}</section>`;
}

const cuePlan = () => ({ conditions: [...S.cueConds] });

function cueRunCard() {
  const n = S.cueLab.episode;
  const has = !!S.cueLab.sheet;
  const conds = S.cue.conditions.map((c) => {
    const off = c.key !== 'oneshot' && !has;
    return `<label class="row small" style="gap:6px"><input type="checkbox" data-cue-cond="${c.key}"${S.cueConds.has(c.key) && !off ? ' checked' : ''}${off ? ' disabled' : ''}>${esc(c.label)}</label>`;
  }).join('');
  const ready = [...S.cueConds].filter((k) => k === 'oneshot' || has).length > 0 && !S.cueDirty;
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

/** 'cues.2.tension' 같은 경로에 값을 넣는다. */
function cueSet(path, val) {
  const keys = path.split('.');
  let o = S.cueDraft;
  for (const k of keys.slice(0, -1)) o = o[k];
  o[keys[keys.length - 1]] = val;
  S.cueDirty = true;
}

document.addEventListener('input', (e) => {
  const d = e.target.dataset || {};
  if (!S.cueDraft) return;
  if (d.cue && e.target.tagName !== 'SELECT') { cueSet(d.cue, d.num ? Number(e.target.value) || 0 : e.target.value); return; }
  if (d.cueLines !== undefined) { S.cueDraft.cues[Number(d.cueLines)].lines = cueLinesParse(e.target.value, S.cue.max_lines); S.cueDirty = true; }
});

document.addEventListener('change', (e) => {
  const d = e.target.dataset || {};
  if (d.cueEp) { if (e.target.value) location.hash = `${base()}/cue/${e.target.value}`; return; }
  if (d.cueCond !== undefined) { S.cueConds[e.target.checked ? 'add' : 'delete'](d.cueCond); S.cueEst = null; render(); return; }
  if (d.cue && S.cueDraft) { cueSet(d.cue, d.num ? Number(e.target.value) || 0 : e.target.value); S.cueEst = null; render(); return; }
  if ((d.cue !== undefined || d.cueLines !== undefined) && S.cueDraft) render();  // 막대 · 대사 미리보기 · 저장 버튼
});

JOB_PAGES.cue_sheet = ['cue'];
JOB_PAGES.cue_run = ['cue'];
JOB_DONE_MSG.cue_sheet = (j) => {
  if (S.cueLab && S.cueLab.episode === j.ep) cueFetch(j.ep).then(render);
  return `${j.ep}화 큐 시트를 만들었어요: 큐 ${j.result ? j.result.cues : 0}개.`;
};
JOB_DONE_MSG.cue_run = (j) => {
  cueLoad(j.ep).then(() => (S.cueLab && S.cueLab.episode === j.ep ? cueFetch(j.ep) : null)).then(render);
  return `${j.ep}화 큐 시트 실험이 끝났어요: 본문 ${j.result ? j.result.takes : 0}개.`;
};

Object.assign(actions, {
  cueMake() {
    if (S.cueLab.sheet && !confirm('지금 큐 시트를 AI가 만든 새 시트로 바꿀까요?')) return;
    startJob('cue_sheet', S.cueLab.episode);
  },
  async cueFromBoard() {
    if (S.cueLab.sheet && !confirm('지금 큐 시트를 뼈대로 바꿀까요?')) return;
    await run('뼈대 만드는 중', async () => {
      S.cueLab = await api('POST', `/projects/${enc(S.name)}/cue/${S.cueLab.episode}/sheet/board`);
      S.cueDraft = structuredClone(S.cueLab.sheet);
      S.cueDirty = false; S.cueEst = null;
    });
  },
  async cueSave() {
    await run('큐 시트 저장 중', async () => {
      S.cueLab = await api('PUT', `/projects/${enc(S.name)}/cue/${S.cueLab.episode}/sheet`, S.cueDraft);
      S.cueDraft = structuredClone(S.cueLab.sheet);
      S.cueDirty = false; S.cueEst = null;
    });
    toast('큐 시트를 저장했어요');
  },
  cueReset() { S.cueDraft = structuredClone(S.cueLab.sheet); S.cueDirty = false; render(); },
  cueAdd() {
    const last = S.cueDraft.cues[S.cueDraft.cues.length - 1];
    S.cueDraft.cues.push({ scene: last ? last.scene : 0, function: 'S', tension: 3, tempo: 'mid', voice: 'action', beat: '', lines: [], exit: '', length: last ? last.length : 1000 });
    S.cueDirty = true; render();
  },
  cueDrop(i) { S.cueDraft.cues.splice(Number(i), 1); S.cueDirty = true; render(); },
  cueMove(arg) {
    const [i, dir] = arg.split(':').map(Number);
    const xs = S.cueDraft.cues;
    [xs[i], xs[i + dir]] = [xs[i + dir], xs[i]];
    S.cueDirty = true; render();
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
`;
  const el = document.createElement('style');
  el.textContent = css;
  document.head.appendChild(el);
})();

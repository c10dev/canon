/* 문단 연습장 (작품 밖 화면 #/studio[/<세션 id>]). 서버는 canon/studio.py · pipeline.draft_paragraph, 엔드포인트는 /api/studio.
   상황 카드(SceneCard)로 AI 안을 여러 개 받거나 작가가 직접 써 보고, 문단 지표(studio.measure)로 견준다. 작품에는 넣지 않는다.
   카드는 S.stuForm 에 고치고, 칸을 벗어날 때(change) 조용히 저장한다. AI 안 쓰기 · 시도 저장 전에도 먼저 저장한다. */

DRAFT_ROOTS.stuForm = () => S.stuForm;

// AI 호출 넷(AI 안 쓰기 · 박자 짚기 · 다른 상황 · 독자로 읽기)은 백그라운드 작업으로 돈다 (routes/studio.studio_job, UX 02c).
// 작품 밖이라 작업 목록의 project 자리는 STU_JOBS, 대상(target)은 세션 id, 독자로 읽기는 화(ep) 자리에 시도 번호다.
// 버튼은 jobBtn(…, STU_JOBS, 세션 id)로 그린다 (lockJobBtns 는 지금 작품의 작업만 본다). 끝나면 그 세션을 보고 있을 때 다시 받는다 (stuJobDone)
const STU_JOBS = '.studio';  // 작업 목록의 project 자리 (routes/studio.STU_JOBS)
const STU_KINDS = { draft: 'AI 안', anatomy: '구조 뜯어보기', variants: '다른 상황', reader: '독자 질문' };
/** 이 세션의 그 작업 버튼 모양 { label, attr }. no 는 독자로 읽기의 시도 번호 */
const stuBtn = (kind, idle, no = null) => jobBtn(`stu_${kind}`, no, idle, STU_JOBS, S.stu.id);

/** 문단 연습장 작업 시작 (startJob 의 작품 밖 판, revlab.js revStartJob 과 같은 꼴). 고친 카드를 먼저 저장한다. 실패하면 '다시 시도'가 같은 요청을 보낸다 */
async function stuStartJob(kind, extra = {}) {
  const id = S.stu.id;
  const key = jobKey(`stu_${kind}`, kind === 'reader' ? extra.no : null, id);
  if (S.starting.has(key)) return;
  S.starting.add(key);
  render();
  try {
    if (S.stuDirty) stuSet(await api('PUT', `/studio/${enc(id)}`, S.stuForm));
    const j = await api('POST', `/studio/${enc(id)}/jobs`, { kind, ...extra });
    if (!j.already) toast(`${j.label}${josa(j.label, '을', '를')} 시작했어요. 끝나면 알려 드릴게요. 그동안 카드를 고치거나 직접 써 봐도 돼요.`);
    S.jobs = S.jobs.filter((x) => x.id !== j.id).concat(j);
    S.jobArgs[j.id] = { retry: () => (S.stu && S.stu.id === id ? stuStartJob(kind, extra) : toast('그 연습을 연 뒤 다시 해 주세요', true)) };
    renderHub();
    pollJobs(true);
  } catch (e) {
    showError(e);
  } finally {
    S.starting.delete(key);
    render();
  }
}

/** 작업이 끝났다: 그 세션을 보고 있으면 다시 받는다. 고치던 카드(S.stuDirty)는 서버 것으로 바꾸지 않고 남긴다.
    시도 고쳐 쓰기 · 직접 쓰기 칸(S.stuEditText · S.stuWrite)은 세션과 따로라 그대로다. 입력 중이면 다시 그리기를 미룬다 */
function stuJobDone(j) {
  if (j.status !== 'done' || !S.stu || S.stu.id !== j.target) return;
  const id = j.target;
  api('GET', `/studio/${enc(id)}`).then((s) => {
    if (!S.stu || S.stu.id !== id) return;
    if (S.stuDirty) S.stu = s;
    else stuSet(s);
    if (S.route[0] !== 'studio') return;
    if (isTyping() || selecting()) S.renderPending = true;
    else render();
  }).catch(() => {});
}
for (const kind of Object.keys(STU_KINDS)) {
  JOB_LINK[`stu_${kind}`] = (j) => `#/studio/${enc(j.target)}`;
}
JOB_DONE_MSG.stu_draft = (j) => { stuJobDone(j); return `AI 안 ${(j.result || {}).added || 0}개를 남겼어요.`; };
JOB_DONE_MSG.stu_anatomy = (j) => { stuJobDone(j); return '본보기 문장마다 박자를 짚었어요.'; };
JOB_DONE_MSG.stu_variants = (j) => { stuJobDone(j); return `같은 구조로 쓸 다른 상황 ${(j.result || {}).variants || 0}개를 받았어요.`; };
JOB_DONE_MSG.stu_reader = (j) => { stuJobDone(j); return `${j.ep}번 시도를 처음 읽는 독자로 읽었어요.`; };

async function stuLoad(id) {
  const home = await api('GET', '/studio');
  S.stuList = home.sessions;
  S.stuDrills = home.drills;
  S.stuBeats = home.beats;
  S.stuVarRange = home.variants;
  S.stuLength = home.length;
  S.stuMax = home.max_tries;
  if (!id) { S.stu = null; S.stuForm = null; return; }
  if (!S.stu || S.stu.id !== id) { S.stuWrite = ''; S.stuBase = 0; S.stuEdit = 0; S.stuEditText = ''; }
  stuSet(await api('GET', `/studio/${enc(id)}`));
}

/** 서버가 돌려준 세션을 받는다. 고치던 카드가 있으면 서버 것으로 바꾼다 (저장 뒤에만 부르므로 잃는 고침은 없다). */
function stuSet(s) {
  S.stu = s;
  S.stuForm = { title: s.title, card: JSON.parse(JSON.stringify(s.card)) };
  S.stuDirty = false;
}

/** 고치는 시도 칸의 글이 저장한 글과 다르다 (S.stuEditText 는 data-local 로 묶인다) */
function stuEditDirty() {
  const t = S.stu && S.stuEdit ? S.stu.tries.find((x) => x.no === S.stuEdit) : null;
  return !!t && (S.stuEditText ?? t.text) !== t.text;
}

// 페이지를 떠나면 직접 쓰기 칸과 고치는 시도 칸의 글이 사라진다. 새로고침 · 탭 닫기에서 묻는다 (app.js onKeptDraft)
if (typeof onKeptDraft === 'function') onKeptDraft(() => !!(S.stuWrite || '').trim() || stuEditDirty());

function viewStudio() {
  return S.stu ? stuSession() : stuHome();
}

function stuHome() {
  const list = S.stuList || [];
  const head = header('작품 밖 도구', '문단 연습장', '상황 카드 하나로 한 문단짜리 장면을 AI에게 여러 안 쓰게 하거나 직접 써 보고, 감정 이름 · 쇠맛 · 길이 같은 문단 지표로 견줘요. 작품에는 들어가지 않아요.',
    '<button type="button" class="btn primary" data-action="stuNew">+ 새 연습</button>');
  if (!list.length) {
    return `${head}<section class="card empty"><h2>아직 연습이 없어요</h2><p class="small">누가, 어디서, 무슨 일을 하는지 적고 '감정 이름 없이' 같은 연습을 고르면 AI가 서로 다른 안을 써요. 같은 카드로 직접 써 보거나 AI 안을 고쳐 쓸 수도 있어요.</p>
      <div class="row"><button type="button" class="btn primary" data-action="stuNew">새 연습 만들기</button></div></section>`;
  }
  const drill = (id) => (S.stuDrills || []).find((d) => d.id === id);
  const cards = list.map((x) => {
    const meta = [`시도 ${x.tries}개`, x.authored ? `직접 쓴 글 ${x.authored}개` : '', x.starred ? `고른 것 ${x.starred}개` : '', x.style_name ? `문체 ${x.style_name}` : '', fmtDateTime(x.updated_at)].filter(Boolean).join(' · ');
    const chips = x.drills.map((d) => (drill(d) ? `<span class="chip">${esc(drill(d).label)}</span>` : '')).join('');
    return `<a class="card" href="#/studio/${enc(x.id)}"><h3>${esc(x.title)}</h3>${chips ? `<div class="row">${chips}</div>` : ''}<div class="small">${esc(meta)}</div></a>`;
  }).join('');
  return `${head}<div class="grid-auto">${cards}</div>`;
}

function stuSession() {
  const s = S.stu;
  const full = s.tries.length >= (S.stuMax || 40);
  const n = Number(S.stuN) || 3;
  const right = `<a class="btn" href="#/studio">목록으로</a>
    <button type="button" class="btn" data-action="stuDuplicate">카드 복제</button>
    <button type="button" class="btn danger" data-action="stuDelete">지우기</button>
    ${(() => { const b = stuBtn('draft', `AI 안 ${n}개 쓰기`); return `<button type="button" class="btn primary" data-action="stuDraft"${b.attr}${full ? ' disabled title="시도가 꽉 찼어요. 지울 시도를 고르세요"' : ''}>${b.label}</button>`; })()}`;
  const head = header('문단 연습장', s.title, s.style_name ? `문체: ${esc(s.style_name)}` : '문체를 고르지 않았어요. 기본 문체 규칙으로 써요.', right);
  const v = stuView();
  return `${head}<div class="cols stu-read" style="--stu-lh:${v.lh};--stu-gap:${v.gap}"><div class="col">${stuCardForm()}</div><div class="col wide">${stuViewBar(v)}${stuModelCard()}${stuVariantCard()}${stuWriteCard()}${stuTries()}</div></div>`;
}

// ----- 글 보기: 줄 간격 · 문단 간격 (이 브라우저에만 기억한다) -----

const STU_LH = [['1.5', '좁게'], ['1.85', '보통'], ['2.2', '넓게'], ['2.6', '아주 넓게']];
const STU_GAP = [['0', '없음'], ['0.5', '반 줄'], ['1', '한 줄']];
const STU_VIEW_KEY = 'canon.studioView';

/** 저장한 보기 값을 고른다. 목록에 없는 값은 기본값(보통 · 없음)으로 둔다. */
function stuViewPick(raw) {
  const r = raw && typeof raw === 'object' ? raw : {};
  const ok = (list, x, d) => (list.some(([k]) => k === String(x)) ? String(x) : d);
  return { lh: ok(STU_LH, r.lh, '1.85'), gap: ok(STU_GAP, r.gap, '0') };
}

function stuView() {
  if (!S.stuView) {
    let raw = null;
    try { raw = JSON.parse(localStorage.getItem(STU_VIEW_KEY) || 'null'); } catch { raw = null; }
    S.stuView = stuViewPick(raw);
  }
  return S.stuView;
}

function stuViewBar(v) {
  const sel = (key, list, label) => `<label class="small stu-k">${label} <select data-stu-view="${key}" aria-label="${label}">${list.map(([k, t]) => `<option value="${k}"${k === v[key] ? ' selected' : ''}>${t}</option>`).join('')}</select></label>`;
  return `<div class="row stu-view">${sel('lh', STU_LH, '줄 간격')}${sel('gap', STU_GAP, '문단 간격')}</div>`;
}

/** 글을 줄 바꿈마다 문단(<p>)으로 나눈다. 문단 간격은 CSS(--stu-gap)가 정한다. 빈 줄은 빈 문단으로 남긴다. */
function stuParas(text) {
  return String(text || '').split('\n').map((x) => `<p>${x ? esc(x) : '<br>'}</p>`).join('');
}

/** 본보기 문단 (역설계 실험 원문에서 가져옴, revlab.paragraph_card). 시도와 같은 지표로 재서 맨 위에 둔다. 프롬프트에는 넣지 않는다. */
function stuModelCard() {
  const c = S.stu.card;
  if (!c.model) return '';
  const m = S.stu.model_measure;
  return `<section class="card stu-model" id="stu-model">
      <div class="between"><div class="row"><span class="chip">본보기</span>${c.ref ? `<span class="small">${esc(c.ref)}</span>` : ''}</div>
        <span class="small">AI에게는 보내지 않아요</span></div>
      <div class="rw-text stu-text">${stuParas(c.model)}</div>${m ? stuChecks(m) : ''}
      <div class="row">${(() => { const b = stuBtn('anatomy', S.stu.anatomy ? '다시 뜯어보기' : '구조 뜯어보기'); return `<button type="button" class="btn small${S.stu.anatomy ? '' : ' primary'}" data-action="stuAnatomy"${b.attr}>${b.label}</button>`; })()}
        <button type="button" class="btn small" data-action="stuModelSource"${c.source === c.model ? ' disabled title="이미 출발 글이에요"' : ''}>출발 글로 넣기</button>
        <button type="button" class="btn small" data-action="stuModelCopy">복사</button></div>${stuAnatomyHtml()}</section>`;
}

const stuBeatLabel = (id) => ((S.stuBeats || []).find((b) => b.id === id) || { label: id }).label;

/** 뜯어보기 결과: 문장마다 박자 · 하는 일, 가린 것 · 감각 전환 · 독자가 채우는 것. '카드에 적용'은 차례 · 가릴 것 · 감각 전환을 카드로. */
function stuAnatomyHtml() {
  const a = S.stu.anatomy;
  if (!a) return '';
  const c = S.stu.card;
  const same = !S.stu.anatomy_stale && a.lines.map((x) => x.beat).join() === c.beats.join() && (!a.withhold || a.withhold === c.withhold) && (!a.sense || a.sense === c.sense);
  const rows = a.lines.map((x, i) => `<tr><td class="small">${i + 1}</td><td><span class="chip">${esc(stuBeatLabel(x.beat))}</span></td><td>«${esc(x.quote)}…»<br><span class="small">${esc(x.note)}</span></td></tr>`).join('');
  const kv = (k, v) => (v ? `<dt>${k}</dt><dd>${esc(v)}</dd>` : '');
  return `<div class="stu-anatomy"><div class="between"><h3>구조</h3>${S.stu.anatomy_stale ? '<span class="chip warn">본보기가 바뀌었어요</span>' : ''}</div>
      <div class="rs-scroll"><table class="rs-table"><thead><tr><th>#</th><th>박자</th><th>문장 · 하는 일</th></tr></thead><tbody>${rows}</tbody></table></div>
      <dl class="stu-kv">${kv('가린 것', a.withhold)}${kv('감각 전환', a.sense)}${kv('독자가 채우는 것', a.reader)}</dl>
      <div class="row"><button type="button" class="btn small${same ? '' : ' primary'}" data-action="stuAnatomyApply"${same ? ' disabled title="카드와 같아요"' : ''}>카드에 적용</button>
        <span class="small">문장 차례 · 가릴 것 · 감각 전환을 카드로 옮겨요</span></div></div>`;
}

/** 상황 바꿔 보기: 같은 구조로 쓸 다른 상황 후보. 고르면 구조 · 연습 · 문체를 그대로 둔 새 연습이 열린다. */
function stuVariantCard() {
  const c = S.stu.card;
  if (!(c.beats.length || c.model || c.action)) return '';
  const vs = S.stu.variants || [];
  const k = Number(S.stuK) || 4;
  const [lo, hi] = S.stuVarRange || [2, 5];
  const list = vs.map((v, i) => `<li class="stu-var"><div><strong>${esc(v.action)}</strong><div class="small">${esc([v.place, v.time].filter(Boolean).join(' · '))}${v.people.length ? ` · ${esc(v.people.map((p) => p.name + (p.name === v.pov ? '(시점)' : '')).join(', '))}` : ''}</div>
      ${v.why ? `<div class="small">${esc(v.why)}</div>` : ''}</div><button type="button" class="btn small" data-action="stuFromVariant" data-arg="${i}">이 상황으로 새 연습</button></li>`).join('');
  return `<section class="card" id="stu-variants"><div class="between"><h2>상황 바꿔 보기</h2>
      <div class="row"><label class="small stu-k">한 번에 <select data-local="stuK" aria-label="받을 상황 수">${Array.from({ length: hi - lo + 1 }, (_, j) => lo + j).map((x) => `<option${x === k ? ' selected' : ''}>${x}</option>`).join('')}</select>개</label>
      ${(() => { const b = stuBtn('variants', vs.length ? '다시 받기' : '다른 상황 받기'); return `<button type="button" class="btn small" data-action="stuVariants"${b.attr}>${b.label}</button>`; })()}</div></div>
      <p class="small">${c.beats.length ? `문장 차례(${esc(c.beats.map(stuBeatLabel).join(' → '))})` : '카드의 구조'}는 그대로 두고 장소 · 인물 · 일만 바꾼 상황을 AI가 내요. 고르면 새 연습이 열리고 이 연습은 그대로 남아요.</p>
      ${list ? `<ul class="stu-vars">${list}</ul>` : ''}</section>`;
}

const STU_CSS = `.stu-anatomy { display: grid; gap: var(--gap-row); border-top: 1px solid var(--line); padding-top: var(--space-10); }
.stu-kv { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: 4px 12px; margin: 0; font-size: 0.8125rem; }
.stu-kv dt { color: var(--muted); }
.stu-kv dd { margin: 0; }
.stu-vars { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-8); }
.stu-var { display: flex; justify-content: space-between; align-items: center; gap: var(--space-10); padding: var(--space-8) 0; border-top: 1px solid var(--line); }
.stu-var:first-child { border-top: 0; }
.stu-beat { display: flex; gap: var(--space-6); align-items: center; }
.stu-beat select { flex: 1; min-width: 0; }
.stu-k { display: inline-flex; align-items: center; gap: var(--space-4); white-space: nowrap; }
.stu-k select { width: auto; }
.stu-read .stu-text { line-height: var(--stu-lh); white-space: normal; }
.stu-text p { margin: 0 0 calc(var(--stu-gap) * var(--stu-lh) * 1em); white-space: pre-wrap; }
.stu-text p:last-child { margin-bottom: 0; }
.stu-read .stu-input { line-height: var(--stu-lh); }
.stu-view { justify-content: flex-end; }
.stu-gaps { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-4); }
@media (max-width: 600px) { .stu-var { flex-direction: column; align-items: stretch; } }`;
(() => { const st = document.createElement('style'); st.textContent = STU_CSS; document.head.appendChild(st); })();

// ----- 상황 카드 -----

function stuCardForm() {
  const f = S.stuForm;
  const c = f.card;
  const o = { root: 'stuForm' };
  const people = c.people.map((x, i) => `<div class="card" style="padding:var(--pad-card-tight)">
      <div class="grid-2">${input('이름', `card.people.${i}.name`, o)}${input('말투', `card.people.${i}.speech`, { ...o, placeholder: '예: 짧은 반말' })}</div>
      ${input('성격 · 처지', `card.people.${i}.note`, { ...o, placeholder: '한두 줄' })}
      <div class="row"><button type="button" class="btn small" data-action="stuPersonDrop" data-arg="${i}">인물 빼기</button></div></div>`).join('');
  const drills = (S.stuDrills || []).map((d) => `<label class="check-row"><input type="checkbox" data-stu-drill="${esc(d.id)}"${c.drills.includes(d.id) ? ' checked' : ''}>
      <span><strong>${esc(d.label)}</strong>${d.auto ? '' : ' <span class="small">· 읽고 판단</span>'}<br><span class="small">${esc(d.rule)}</span></span></label>`).join('');
  const libs = S.libs || [];
  const styleSel = `<div class="field"><label for="stu-style">문체</label><select id="stu-style" data-root="stuForm" data-bind="card.style_id">
      <option value="">고르지 않음 (기본 문체 규칙)</option>${libs.map((l) => `<option value="${esc(l.id)}"${l.id === c.style_id ? ' selected' : ''}>${esc(l.name)}</option>`).join('')}
      ${c.style_id && !libs.some((l) => l.id === c.style_id) ? `<option value="${esc(c.style_id)}" selected>찾지 못한 문체</option>` : ''}</select></div>`;
  const [lo, hi] = S.stuLength || [100, 1200];
  return `<section class="card">
      <div class="between"><h2>상황 카드</h2><span class="small" id="stu-saved">${S.stuDirty ? '저장하지 않은 고침이 있어요' : '빈 칸은 AI가 정해요'}</span></div>
      ${input('제목', 'title', { ...o, placeholder: '비우면 무슨 일로 지어요' })}
      ${input('무슨 일', 'card.action', { ...o, rows: 2, placeholder: '예: 비 오는 정류장에서 우산을 건넨다' })}
      ${input('독자에게 남길 것', 'card.aim', { ...o, placeholder: '감정 이름 대신 보여 줄 것, 예: 말하지 못한 미안함' })}
      <div class="grid-2">${input('장소', 'card.place', o)}${input('때 · 날씨', 'card.time', o)}</div>
      <div class="grid-2">${input('시점 인물', 'card.pov', { ...o, placeholder: '이름, 비우면 AI가' })}${input('목표 글자 수', 'card.length', { ...o, type: 'number', min: lo, max: hi })}</div>
      <h3>인물</h3>${people || '<p class="small">아직 인물이 없어요.</p>'}
      <div class="row"><button type="button" class="btn small" data-action="stuPersonAdd">+ 인물</button></div>
      <h3>연습</h3><div style="display:grid;gap:var(--gap-row)">${drills}</div>
      ${stuStructureForm(c, o)}
      ${input('더 지킬 것', 'card.extra', { ...o, rows: 2, placeholder: '예: 마지막 문장은 대사로' })}
      ${styleSel}
      <details${c.source ? ' open' : ''}><summary>고쳐 쓸 출발 글</summary>${input('출발 글', 'card.source', { ...o, rows: 5, placeholder: '다른 글의 한 문단을 넣으면 같은 상황을 고쳐 써요' })}</details>
      <div class="row"><button type="button" class="btn small${S.stuDirty ? ' primary' : ''}" data-action="stuSaveCard">카드 저장</button>
        <label class="small">한 번에 <select data-local="stuN" aria-label="AI 안 수">${[1, 2, 3, 4].map((k) => `<option${k === (Number(S.stuN) || 3) ? ' selected' : ''}>${k}</option>`).join('')}</select>개</label></div>
    </section>`;
}

/** 카드의 구조 칸: 문장 차례(박자 고르기 · 옮기기 · 빼기) · 가릴 것 · 감각 전환 · 본보기를 AI에게 보이기. */
function stuStructureForm(c, o) {
  const opts = (sel) => (S.stuBeats || []).map((b) => `<option value="${esc(b.id)}"${b.id === sel ? ' selected' : ''}>${esc(b.label)}</option>`).join('');
  const rows = c.beats.map((b, i) => `<div class="stu-beat"><span class="small">${i + 1}</span>
      <select data-stu-beat="${i}" aria-label="${i + 1}번째 박자">${opts(b)}</select>
      <button type="button" class="btn small ghost" data-action="stuBeatMove" data-arg="${i}:-1"${i ? '' : ' disabled'} aria-label="${i + 1}번째 박자 위로">↑</button>
      <button type="button" class="btn small ghost" data-action="stuBeatMove" data-arg="${i}:1"${i < c.beats.length - 1 ? '' : ' disabled'} aria-label="${i + 1}번째 박자 아래로">↓</button>
      <button type="button" class="btn small ghost" data-action="stuBeatDrop" data-arg="${i}" aria-label="${i + 1}번째 박자 빼기">✕</button></div>`).join('');
  const rule = (S.stuBeats || []).map((b) => `<strong>${esc(b.label)}</strong> ${esc(b.rule)}`).join('<br>');
  return `<h3>구조</h3>
      <div style="display:grid;gap:var(--space-6)">${rows || '<p class="small">문장 차례가 없으면 AI가 정해요.</p>'}</div>
      <div class="row"><button type="button" class="btn small" data-action="stuBeatAdd">+ 박자</button>
        <details class="small"><summary>박자 뜻</summary><p>${rule}</p></details></div>
      ${input('가릴 것', 'card.withhold', { ...o, placeholder: '글자로 쓰지 않고 독자가 짐작하게 둘 것, 예: 인물의 속마음' })}
      ${input('감각 전환', 'card.sense', { ...o, placeholder: '예: 보는 것 → 촉감' })}
      ${c.model ? `<label class="check-row"><input type="checkbox" data-root="stuForm" data-bind="card.show_model" data-kind="bool"${c.show_model ? ' checked' : ''}>
        <span><strong>본보기를 AI에게 보이기</strong><br><span class="small">구조와 호흡만 참고하고 문장은 옮기지 말라고 함께 적어요. 옮긴 문장은 시도마다 알려요.</span></span></label>` : ''}`;
}

/** 카드를 저장한다. quiet 면 덮개 없이 (칸을 벗어날 때). 실패하면 알린다. */
async function stuSaveCard(quiet = false) {
  if (!S.stu || !S.stuDirty) return true;
  const id = S.stu.id;
  const body = JSON.parse(JSON.stringify(S.stuForm));
  // 칸을 벗어나며 다른 화면으로 옮겼으면 받은 세션을 놓지 않는다 (옮긴 화면이 제 것을 읽는다)
  const save = async () => { const s = await api('PUT', `/studio/${enc(id)}`, body); if (S.stu && S.stu.id === id) stuSet(s); };
  if (!quiet) return run('카드를 저장하는 중', save);
  try {
    await save();
    const el = $('#stu-saved');
    if (el) el.textContent = '저장했어요';
    return true;
  } catch (e) {
    toast(e.message, true);
    return false;
  }
}

document.addEventListener('input', (e) => {
  if (e.target.dataset && e.target.dataset.root === 'stuForm') {
    S.stuDirty = true;
    const el = $('#stu-saved');
    if (el) el.textContent = '저장하지 않은 고침이 있어요';
  }
});
document.addEventListener('change', (e) => {
  const el = e.target;
  if (!el.dataset || S.route[0] !== 'studio' || !S.stuForm) return;
  if (el.dataset.stuBeat != null) {
    S.stuForm.card.beats[Number(el.dataset.stuBeat)] = el.value;
    S.stuDirty = true;
    stuSaveCard(true);
    return;
  }
  if (el.dataset.local === 'stuK') { render(); return; }
  if (el.dataset.stuView) {
    S.stuView = stuViewPick({ ...stuView(), [el.dataset.stuView]: el.value });
    try { localStorage.setItem(STU_VIEW_KEY, JSON.stringify(S.stuView)); } catch { /* 저장소를 막은 브라우저: 이번 화면에서만 바꾼다 */ }
    render();
    return;
  }
  if (el.dataset.stuDrill) {
    const ds = S.stuForm.card.drills.filter((d) => d !== el.dataset.stuDrill);
    S.stuForm.card.drills = el.checked ? [...ds, el.dataset.stuDrill] : ds;
    S.stuDirty = true;
  }
  if (el.dataset.root === 'stuForm' || el.dataset.stuDrill) stuSaveCard(true);
  if (el.dataset.local === 'stuN') render();  // 머리 버튼 글자(AI 안 n개)
});

// ----- 직접 쓰기 -----

function stuWriteCard() {
  const base = S.stuBase ? S.stu.tries.find((t) => t.no === S.stuBase) : null;
  const what = base ? `${base.no}번 ${base.by === 'ai' ? 'AI 안' : '글'}을 고쳐 써요` : '같은 카드로 직접 써요';
  return `<section class="card" id="stu-write">
      <div class="between"><h2>직접 쓰기</h2><span class="small">${esc(what)}</span></div>
      <div class="field"><label for="stu-text" class="sr-only">쓸 글</label><textarea id="stu-text" class="stu-input" rows="6" data-local="stuWrite" data-autogrow placeholder="카드의 상황을 문단 하나로 써 보세요">${esc(S.stuWrite || '')}</textarea></div>
      <div class="row"><button type="button" class="btn primary small" data-action="stuAddTry">시도로 남기기</button>
        ${base || S.stuWrite ? '<button type="button" class="btn small" data-action="stuWriteClear">비우기</button>' : ''}</div>
    </section>`;
}

// ----- 시도 목록 -----

function stuChecks(m) {
  const chip = (c) => `<span class="chip${c.ok === true ? ' ok' : c.ok === false ? ' bad' : ''}" title="${esc(c.why)}">${c.ok === true ? '✓' : c.ok === false ? '✕' : '?'} ${esc(c.label)}</span>`;
  const facts = [`${m.chars.toLocaleString()}자`, `${m.sentences}문장`, `문장 평균 ${m.sentence_len_mean}자`, m.sentence_len_cv != null ? `길이 변화폭 ${m.sentence_len_cv}` : '', `대사 ${m.dialogue_pct}%`].filter(Boolean).join(' · ');
  const why = m.checks.filter((c) => c.ok === false).map((c) => `${c.label}: ${c.why}`);
  const hits = m.hits.map((h) => `«${esc(h.quote)}» ${esc(h.kind === 'cliche' ? '상투 표현' : h.name)}`);
  const marks = m.markers.filter((x) => x.count).map((x) => `'${esc(x.text)}' ${x.count}회`);
  return `${m.checks.length ? `<div class="row">${m.checks.map(chip).join('')}</div>` : ''}
    <div class="small">${esc(facts)}</div>
    ${why.length ? `<div class="small">${why.map(esc).join('<br>')}</div>` : ''}
    ${hits.length ? `<div class="small">걸린 곳: ${hits.join(' · ')}</div>` : ''}
    ${marks.length ? `<div class="small">문체 버릇: ${marks.join(' · ')}</div>` : ''}
    ${(m.copied || []).length ? `<div class="small warn-text">본보기에서 옮긴 문장: ${m.copied.map((x) => `«${esc(x)}»`).join(' · ')}</div>` : ''}`;
}

function stuTryCard(t) {
  const m = S.stu.measures[String(t.no)];
  const who = t.by === 'ai' ? `<span class="chip ai">AI ${t.no}번</span>` : `<span class="chip">직접 ${t.no}번</span>`;
  const base = t.base ? `<span class="small">${t.base}번을 고쳐 씀</span>` : '';
  const editing = S.stuEdit === t.no;
  const body = editing
    ? `<div class="field"><label for="stu-edit-${t.no}" class="sr-only">${t.no}번 고치기</label><textarea id="stu-edit-${t.no}" class="stu-input" rows="6" data-autogrow data-local="stuEditText">${esc(S.stuEditText ?? t.text)}</textarea></div>
       <div class="row"><button type="button" class="btn small primary" data-action="stuEditSave" data-arg="${t.no}">저장</button><button type="button" class="btn small" data-action="stuEditCancel">그만두기</button></div>`
    : `<div class="rw-text stu-text">${stuParas(t.text)}</div>`;
  const btns = editing ? '' : `<div class="row">
      <button type="button" class="btn small${t.star ? ' primary' : ''}" data-action="stuStar" data-arg="${t.no}" aria-pressed="${t.star}">${t.star ? '★ 고름' : '☆ 고르기'}</button>
      <button type="button" class="btn small" data-action="stuRewrite" data-arg="${t.no}">고쳐 쓰기</button>
      ${t.by === 'author' ? `<button type="button" class="btn small" data-action="stuEditOpen" data-arg="${t.no}">고치기</button>` : ''}
      ${(() => { const b = stuBtn('reader', t.reader ? '독자 질문 다시' : '독자 질문', t.no); return `<button type="button" class="btn small" data-action="stuReader" data-arg="${t.no}"${b.attr}>${b.label}</button>`; })()}
      <button type="button" class="btn small" data-action="stuCopy" data-arg="${t.no}">복사</button>
      <button type="button" class="btn small danger" data-action="stuDrop" data-arg="${t.no}">지우기</button></div>`;
  return `<section class="card" id="stu-try-${t.no}">
      <div class="between"><div class="row">${who}${base}${t.note ? `<span class="small">${esc(t.note)}</span>` : ''}</div><span class="small">${esc(fmtDateTime(t.at))}</span></div>
      ${body}${m ? stuChecks(m) : ''}${editing ? '' : stuReaderHtml(t)}${btns}</section>`;
}

/** 독자 질문 결과: 독자가 채울 것마다 '독자 몫'(본문에 없음) 또는 '적혀 있음'(인용). 적힌 것이 많으면 빈칸이 적은 글이다. */
function stuReaderHtml(t) {
  const r = t.reader;
  if (!r) return '';
  const open = r.gaps.filter((g) => !g.written).length;
  const rows = r.gaps.map((g) => `<li>${g.written ? '<span class="chip">적혀 있음</span>' : '<span class="chip ok">독자 몫</span>'} ${esc(g.imagined)}${g.quote ? ` <span class="small">«${esc(g.quote)}»</span>` : ''}</li>`).join('');
  return `<details class="small"${S.stuReaderOpen === t.no ? ' open' : ''}><summary>독자 질문: 독자 몫 ${open}개 · 적혀 있음 ${r.gaps.length - open}개</summary><ul class="stu-gaps">${rows}</ul></details>`;
}

function stuTries() {
  const ts = [...S.stu.tries].reverse();
  if (!ts.length) return '<section class="card empty"><h2>아직 시도가 없어요</h2><p class="small">카드를 채우고 머리의 \'AI 안 쓰기\'를 누르거나 위 칸에 직접 써 보세요.</p></section>';
  const star = ts.filter((t) => t.star);
  return [...star, ...ts.filter((t) => !t.star)].map(stuTryCard).join('');
}

// ----- 동작 -----

/** 카드를 먼저 저장하고(고친 것이 있으면) AI 호출을 보낸다. */
async function stuCall(label, path, body) {
  await run(label, async () => {
    if (S.stuDirty) stuSet(await api('PUT', `/studio/${enc(S.stu.id)}`, S.stuForm));
    stuSet(await api('POST', `/studio/${enc(S.stu.id)}${path}`, body));
  });
}

Object.assign(actions, {
  async stuAnatomy() {
    await stuStartJob('anatomy');
  },
  async stuAnatomyApply() {
    const c = S.stu.card;
    if ((c.beats.length || c.withhold || c.sense) && !(await askConfirm('카드의 문장 차례 · 가릴 것 · 감각 전환을 뜯어본 값으로 바꿀까요?', { ok: '바꾸기' }))) return;
    await stuCall('카드에 적용하는 중', '/anatomy/apply');
    toast('구조를 카드에 적용했어요. AI 안이 이 문장 차례를 따라요');
  },
  async stuVariants() {
    await stuStartJob('variants', { k: Number(S.stuK) || 4 });
  },
  async stuFromVariant(i) {
    await run('새 연습을 만드는 중', async () => {
      if (S.stuDirty) stuSet(await api('PUT', `/studio/${enc(S.stu.id)}`, S.stuForm));
      const s = await api('POST', `/studio/${enc(S.stu.id)}/variants/${Number(i)}`);
      location.hash = `#/studio/${enc(s.id)}`;
      toast('고른 상황으로 새 연습을 만들었어요. 구조 · 연습 · 문체는 그대로예요');
    }, { render: 'never' });
  },
  async stuReader(no) {
    S.stuReaderOpen = Number(no);
    await stuStartJob('reader', { no: Number(no) });
  },
  stuBeatAdd() {
    const c = S.stuForm.card;
    const order = (S.stuBeats || []).map((b) => b.id);
    const last = c.beats[c.beats.length - 1];
    c.beats.push(order[Math.min(order.indexOf(last) + 1, order.length - 1)] || order[0]);
    S.stuDirty = true;
    stuSaveCard(true);
    render();
  },
  stuBeatMove(arg) {
    const [i, d] = String(arg).split(':').map(Number);
    const b = S.stuForm.card.beats;
    [b[i], b[i + d]] = [b[i + d], b[i]];
    S.stuDirty = true;
    stuSaveCard(true);
    render();
  },
  stuBeatDrop(i) {
    S.stuForm.card.beats.splice(Number(i), 1);
    S.stuDirty = true;
    stuSaveCard(true);
    render();
  },
  async stuModelSource() {
    const f = S.stuForm.card;
    if (f.source && f.source !== f.model && !(await askConfirm('고쳐 쓸 출발 글을 본보기 문단으로 바꿀까요? 지금 출발 글은 사라져요.', { ok: '바꾸기', danger: true }))) return;
    f.source = f.model;
    S.stuDirty = true;
    if (await stuSaveCard()) toast('본보기 문단을 출발 글로 넣었어요. AI 안은 같은 상황을 고쳐 써요');
  },
  async stuModelCopy() {
    try {
      await copyPlain(S.stu.card.model);
      toast('복사했어요');
    } catch (e) {
      toast(e.message, true);
    }
  },
  async stuNew() {
    await run('새 연습을 만드는 중', async () => {
      const s = await api('POST', '/studio', { title: '', card: {} });
      location.hash = `#/studio/${enc(s.id)}`;
    }, { render: 'never' });
  },
  async stuSaveCard() {
    if (!S.stuDirty) return toast('바뀐 칸이 없어요');
    if (await stuSaveCard()) toast('카드를 저장했어요');
  },
  stuPersonAdd() {
    S.stuForm.card.people.push({ name: '', note: '', speech: '' });
    S.stuDirty = true;
    S.focusTarget = `#f-card-people-${S.stuForm.card.people.length - 1}-name`;
    render();
  },
  async stuPersonDrop(i) {
    S.stuForm.card.people.splice(Number(i), 1);
    S.stuDirty = true;
    await stuSaveCard(true);
    render();
  },
  async stuDraft() {
    await stuStartJob('draft', { n: Number(S.stuN) || 3 });
  },
  async stuAddTry() {
    const text = (S.stuWrite || '').trim();
    if (!text) return toast('쓸 글을 적으세요', true);
    await run('시도로 남기는 중', async () => {
      if (S.stuDirty) stuSet(await api('PUT', `/studio/${enc(S.stu.id)}`, S.stuForm));
      stuSet(await api('POST', `/studio/${enc(S.stu.id)}/tries`, { text, base: S.stuBase || 0 }));
      S.stuWrite = '';
      S.stuBase = 0;
      toast('남겼어요');
    });
  },
  stuWriteClear() {
    S.stuWrite = '';
    S.stuBase = 0;
    render();
  },
  async stuRewrite(no) {
    const t = S.stu.tries.find((x) => x.no === no);
    if ((S.stuWrite || '').trim() && S.stuBase !== no && !(await askConfirm('직접 쓰기 칸의 글을 이 시도로 바꿀까요? 쓰던 글은 사라져요.', { ok: '바꾸기', danger: true }))) return;
    S.stuWrite = t.text;
    S.stuBase = no;
    S.focusTarget = '#stu-text';
    render();
  },
  async stuEditOpen(no) {
    if (S.stuEdit !== no && stuEditDirty() && !(await askConfirm(`고치던 ${S.stuEdit}번 글을 버리고 ${no}번을 고칠까요?`, { ok: '버리고 열기', danger: true }))) return;
    S.stuEdit = no;
    S.stuEditText = S.stu.tries.find((x) => x.no === no).text;  // 칸의 글을 S 에 둔다. 다른 버튼으로 다시 그려도 고친 글이 남는다
    S.focusTarget = `#stu-edit-${no}`;
    render();
  },
  async stuEditCancel() {
    if (stuEditDirty() && !(await askConfirm('고친 글을 버리고 그만둘까요?', { ok: '버리기', danger: true }))) return;
    S.stuEdit = 0;
    S.stuEditText = '';
    render();
  },
  async stuEditSave(no) {
    const text = S.stuEdit === no ? S.stuEditText : '';
    await run('고친 글을 저장하는 중', async () => {
      stuSet(await api('PUT', `/studio/${enc(S.stu.id)}/tries/${no}`, { text }));
      S.stuEdit = 0;
      S.stuEditText = '';
    });
  },
  async stuStar(no) {
    const t = S.stu.tries.find((x) => x.no === no);
    await run('고르는 중', async () => {
      if (S.stuDirty) stuSet(await api('PUT', `/studio/${enc(S.stu.id)}`, S.stuForm));
      stuSet(await api('PUT', `/studio/${enc(S.stu.id)}/tries/${no}`, { star: !t.star }));
    });
  },
  async stuCopy(no) {
    const t = S.stu.tries.find((x) => x.no === no);
    try {
      await copyPlain(t.text);
      toast('복사했어요');
    } catch (e) {
      toast(e.message, true);
    }
  },
  async stuDrop(no) {
    if (!(await askConfirm(`${no}번 시도를 지울까요? 되돌릴 수 없어요.`, { ok: '지우기', danger: true }))) return;
    await run('지우는 중', async () => {
      if (S.stuDirty) stuSet(await api('PUT', `/studio/${enc(S.stu.id)}`, S.stuForm));
      stuSet(await api('DELETE', `/studio/${enc(S.stu.id)}/tries/${no}`));
      if (S.stuBase === no) S.stuBase = 0;
    });
  },
  async stuDuplicate() {
    await run('카드를 복제하는 중', async () => {
      if (S.stuDirty) stuSet(await api('PUT', `/studio/${enc(S.stu.id)}`, S.stuForm));
      const s = await api('POST', `/studio/${enc(S.stu.id)}/duplicate`);
      location.hash = `#/studio/${enc(s.id)}`;
      toast('카드를 복제했어요. 한 칸만 바꿔 다시 써 보세요');
    }, { render: 'never' });
  },
  async stuDelete() {
    if (!(await askConfirm(`'${S.stu.title}' 연습을 지울까요? 시도 ${S.stu.tries.length}개도 함께 지워요. 되돌릴 수 없어요.`, { ok: '지우기', danger: true }))) return;
    await run('지우는 중', async () => {
      await api('DELETE', `/studio/${enc(S.stu.id)}`);
      S.stu = null;
      location.hash = '#/studio';
    }, { render: 'never' });
  },
});

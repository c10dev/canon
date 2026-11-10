/* 프롬프트 놀이터 (작품 밖 화면 #/promptlab[/<세션 id>]). 서버는 canon/promptlab.py · research.sample, 엔드포인트는 /api/promptlab.
   시스템 · 요청 프롬프트를 직접 써서 고른 백엔드(Gemini · 로컬 · Claude · mock)로 돌리고, 결과 · 시간 · 토큰 · 어림 비용을 시도로 남겨 견준다.
   프롬프트 칸은 S.pgForm 에 고치고, 칸을 벗어날 때(change) 조용히 저장한다. 돌리기는 고친 칸을 함께 보내 서버가 먼저 저장한다.
   '불러오기'는 Canon 프롬프트(작업지시서와 같은 조립, prompts.brief_parts)를 예시 작품이나 고른 작품으로 조립해 칸에 채운다. 고르기 칸은 S.pgSrc. */
'use strict';

DRAFT_ROOTS.pgForm = () => S.pgForm;

async function pgLoad(id) {
  const home = await api('GET', '/promptlab');
  S.pgList = home.sessions;
  S.pgLimits = { providers: home.providers, maxBackends: home.max_backends, maxTrials: home.max_trials, temperature: home.temperature,
    policyNote: home.policy_note || '' };
  if (!id) { S.pg = null; S.pgForm = null; return; }
  pgSet(await api('GET', `/promptlab/${enc(id)}`));
  if (!S.pgSrc) await pgSources('').catch(() => {});  // 불러오기 칸을 못 읽어도 세션은 연다
}

/** 불러오기 고르기 칸의 재료(갈래 · 화 목록)를 읽는다. project 가 비면 예시 작품. 갈래는 그대로 두고 화는 그 갈래의 기본 화로 */
async function pgSources(project) {
  const info = await api('GET', `/promptlab/sources${project ? `?project=${enc(project)}` : ''}`);
  const want = (S.pgSrc && S.pgSrc.kind) || 'episode';
  const kind = info.kinds.some((k) => k.id === want) ? want : 'episode';  // 단편으로 바꾸면 장편에만 있는 갈래(부 구성)는 없다
  S.pgSrc = { project, kind, n: info.defaults[kind] || 0, info };
}

/** 갈래에 맞는 '화' 고르기 칸 (순수 함수, tests/test_promptlab_js.py). scope work 는 칸이 없고(null), act 는 플롯 초안 구간,
    episode 는 그 갈래의 조건(본문 · 확정 · 초안)에 맞는 화만. 옛 응답(needs_text 만 있음)도 읽는다 */
function pgSrcChoices(info, kind) {
  const scope = kind.scope || 'episode';
  if (scope === 'work') return null;
  if (scope === 'act') return { label: '구간', options: (info.groups || []).map((g) => ({ n: g.n, label: g.label })), empty: '기승전결 구조가 없어요' };
  const need = kind.need ?? (kind.needs_text ? 'text' : '');
  const ok = (e) => (need === 'text' ? e.has_text : need === 'confirmed' ? e.confirmed : need === 'draft' ? !e.confirmed : true);
  const empty = { text: '본문이 있는 화가 없어요', confirmed: '플롯을 확정한 화가 없어요', draft: '플롯이 초안인 화가 없어요' }[need] || '플롯이 있는 화가 없어요';
  return { label: '화', options: info.episodes.filter(ok).map((e) => ({ n: e.n, label: `${e.n}화${e.title ? ` · ${e.title}` : ''}${e.has_text ? '' : ' (본문 없음)'}` })), empty };
}

/** 서버가 돌려준 세션을 받는다. 고치던 칸이 있으면 서버 것으로 바꾼다 (저장 뒤에만 부르므로 잃는 고침은 없다). */
function pgSet(s) {
  S.pg = s;
  S.pgForm = { title: s.title, system: s.system, prompt: s.prompt, temp: s.temperature == null ? '' : String(s.temperature),
    backends: s.backends.map((b) => ({ ...b })) };
  S.pgDirty = false;
}

/** 화면 칸(S.pgForm)을 서버가 받는 모양으로. 온도 칸이 비었거나 숫자가 아니면 설정 값(null)을 쓴다 (순수 함수, tests/test_promptlab_js.py) */
function pgBody(f) {
  const t = String(f.temp ?? '').trim();
  const n = t === '' ? null : Number(t);
  return { title: f.title || '', system: f.system || '', prompt: f.prompt || '', temperature: n == null || Number.isNaN(n) ? null : n,
    backends: (f.backends || []).map((b) => ({ provider: b.provider, model: (b.model || '').trim(), url: b.provider === 'local' ? (b.url || '').trim() : '' })) };
}

/** 시도들을 고른 것 먼저, 그다음 최근 것 차례로 (순수 함수) */
function pgOrder(trials) {
  return [...(trials || [])].sort((a, b) => (Number(b.star) - Number(a.star)) || (b.no - a.no));
}

/** 시도의 프롬프트가 지금 칸과 같은지: 'same' 같음, 'system' 시스템만 다름, 'prompt' 요청만 다름, 'both' 둘 다 다름 (순수 함수) */
function pgDiff(t, f) {
  const sys = (t.system || '') !== (f.system || '');
  const req = (t.prompt || '') !== (f.prompt || '');
  return sys && req ? 'both' : sys ? 'system' : req ? 'prompt' : 'same';
}

const PG_DIFF = { same: '지금 프롬프트와 같아요', system: '시스템 프롬프트가 지금과 달라요', prompt: '요청 프롬프트가 지금과 달라요', both: '두 프롬프트 모두 지금과 달라요' };
/** 불러온 출처 한 줄: '검수 · 예시 작품 2화', 고쳤으면 ' (고침)' (순수 함수) */
/** 불러온 갈래대로 돌리는 방식 한 줄 (순수 함수, tests/test_promptlab_js.py). 불러온 출처가 없으면 빈 글 */
function pgSpecLine(spec) {
  if (!spec || !spec.stage) return '';
  const parts = [`${spec.stage_label} 단계의 모델 · 추론 강도`];
  if (spec.schema) parts.push(`응답 형식 ${spec.schema}(구조화 출력, 가짜 응답은 글)`);
  if (spec.out_tokens) parts.push(`출력 한도 ${spec.out_tokens.toLocaleString()}토큰`);
  return `실제 호출처럼 돌려요: ${parts.join(' · ')}.`;
}

/** 모델 칸 안내: 불러온 갈래가 있으면 그 단계에서 쓸 모델 · 추론 강도, 없으면 그 백엔드의 기본 모델(defaultModelName).
 *  spec.backends 는 저장된 백엔드(saved) 차례라서, 칸에서 백엔드를 바꾼 줄은 단계 값을 쓰지 않는다 (순수 함수) */
function pgModelHint(spec, i, b, saved = [], config = {}) {
  const use = spec && spec.backends && spec.backends[i];
  const same = use && (!saved[i] || saved[i].provider === b.provider);
  const effort = same && use.effort ? `, 추론 강도 ${use.effort}` : '';
  if (same && use.model) return `비우면 ${spec.stage_label} 단계 모델(${use.model}${effort})`;
  return `비우면 ${defaultModelName(b.provider, config)}${effort}`;
}

function pgSourceLabel(src, edited) {
  return src ? `${src.label}${edited ? ' (고침)' : ''}` : '';
}

const PG_PROV = { gemini: 'Gemini', local: '로컬', claude: 'Claude 구독', 'claude-api': 'Claude API', mock: '가짜 응답(mock)' };

function viewPromptLab() {
  return S.pg ? pgSession() : pgHome();
}

function pgHome() {
  const list = S.pgList || [];
  const head = header('작품 밖 도구', '프롬프트 놀이터', '시스템 프롬프트와 요청을 직접 써서 여러 모델로 돌려 보고, 결과 · 시간 · 토큰 · 어림 비용을 시도마다 남겨 견줘요. 작품과는 상관없어요.',
    '<button type="button" class="btn primary" data-action="pgNew">+ 새 세션</button>');
  if (!list.length) {
    return `${head}<section class="card empty"><h2>아직 세션이 없어요</h2><p class="small">프롬프트를 적고 Gemini · 로컬 모델을 골라 돌리면, 같은 요청을 모델마다 어떻게 쓰는지 나란히 볼 수 있어요. 프롬프트를 고칠 때마다 시도로 남아 앞 판과 견줄 수 있어요.</p>
      <div class="row"><button type="button" class="btn primary" data-action="pgNew">새 세션 만들기</button></div></section>`;
  }
  const cards = list.map((x) => {
    const meta = [`시도 ${x.trials}개`, x.stars ? `고른 것 ${x.stars}개` : '', x.cost ? `어림 비용 ${usd(x.cost)}` : '', fmtDateTime(x.updated_at)].filter(Boolean).join(' · ');
    const chips = x.backends.map((b) => `<span class="chip">${esc(b)}</span>`).join('');
    return `<a class="card" href="#/promptlab/${enc(x.id)}"><h3>${esc(x.title)}</h3>${chips ? `<div class="row">${chips}</div>` : ''}<div class="small">${esc(meta)}</div></a>`;
  }).join('');
  return `${head}<div class="grid-auto">${cards}</div>`;
}

function pgSession() {
  const s = S.pg;
  const full = s.trials.length >= ((S.pgLimits || {}).maxTrials || 40);
  const n = (S.pgForm.backends || []).length;
  const right = `<a class="btn" href="#/promptlab">목록으로</a>
    <button type="button" class="btn" data-action="pgDuplicate">세션 복제</button>
    <button type="button" class="btn danger" data-action="pgDelete">지우기</button>
    <button type="button" class="btn primary" data-action="pgRun"${full ? ' disabled title="시도가 꽉 찼어요. 지울 시도를 고르세요"' : !n ? ' disabled title="백엔드를 골라 주세요"' : ''}>돌리기${n > 1 ? ` (${n}곳)` : ''}</button>`;
  const total = s.summary && s.summary.cost ? ` · 지금까지 어림 비용 ${usd(s.summary.cost)}` : '';
  const head = header('프롬프트 놀이터', s.title, `시도 ${s.trials.length}개${total}`, right);
  const trials = pgOrder(s.trials);
  return `${head}<div class="cols"><div class="col">${pgForm()}</div><div class="col wide">${trials.length ? trials.map(pgTrialCard).join('')
    : '<section class="card empty"><h2>아직 시도가 없어요</h2><p class="small">프롬프트를 적고 머리의 \'돌리기\'를 누르면 고른 백엔드에 동시에 보내 결과를 여기에 남겨요.</p></section>'}</div></div>`;
}

// ----- 프롬프트 칸 -----

function pgForm() {
  const f = S.pgForm;
  const o = { root: 'pgForm' };
  const lim = S.pgLimits || {};
  const [lo, hi] = lim.temperature || [0, 2];
  const provs = lim.providers || ['gemini', 'local', 'mock'];
  const rows = f.backends.map((b, i) => `<div class="card" style="padding:var(--pad-card-tight)">
      <div class="grid-2"><div class="field"><label for="pg-prov-${i}">백엔드</label><select id="pg-prov-${i}" data-pg-prov="${i}">${provs.map((p) => backendOption(p, PG_PROV[p] || p, b.provider)).join('')}</select></div>
        ${b.provider === 'mock' ? '' : input('모델', `backends.${i}.model`, { ...o, placeholder: pgModelHint(S.pg.spec, i, b, S.pg.backends, S.config || {}) })}</div>
      ${b.provider === 'local' ? input('서버 주소', `backends.${i}.url`, { ...o, placeholder: '비우면 설정 값, 예: http://localhost:11434/v1' }) : ''}
      <div class="row"><button type="button" class="btn small" data-action="pgBackendDrop" data-arg="${i}">빼기</button></div></div>`).join('');
  const more = f.backends.length < (lim.maxBackends || 4);
  return `${pgLoadCard()}<section class="card">
      <div class="between"><h2>프롬프트</h2><span class="small" id="pg-saved">${S.pgDirty ? '저장하지 않은 고침이 있어요' : '칸을 벗어나면 저장해요'}</span></div>
      ${S.pg.source ? `<div class="row"><span class="chip">불러옴</span><span class="small">${esc(pgSourceLabel(S.pg.source, S.pg.source_edited))}</span></div>` : ''}
      ${S.pg.base ? '<div class="row"><span class="chip warn">원래 판과 블라인드</span><span class="small">돌릴 때마다 원래 판도 같은 백엔드로 돌려 가려 읽어요. 비용이 두 배예요.</span></div>' : ''}
      ${pgSpecLine(S.pg.spec) ? `<p class="small">${esc(pgSpecLine(S.pg.spec))}</p>` : ''}
      ${input('제목', 'title', { ...o, placeholder: '비우면 요청 첫 줄로 지어요' })}
      ${input('시스템 프롬프트', 'system', { ...o, rows: 5, autogrow: true, placeholder: '모델의 역할 · 규칙. 비워도 돼요' })}
      ${input('요청 프롬프트', 'prompt', { ...o, rows: 8, autogrow: true, placeholder: '모델에게 보낼 요청' })}
      ${lim.policyNote ? `<p class="small">Gemini · 로컬은 보낼 때 요청 끝에 이 한 줄을 붙여요. Canon의 모든 AI 요청에 붙는 줄이라 칸에는 넣지 않아요: <code>${esc(lim.policyNote)}</code></p>` : ''}
      <div class="small">시스템 ${(f.system || '').length.toLocaleString()}자 · 요청 ${(f.prompt || '').length.toLocaleString()}자 (한국어는 대략 1.7자에 1토큰)</div>
      ${input('온도', 'temp', { ...o, type: 'number', kind: 'text', placeholder: '비우면 설정 값', hint: `${lo}~${hi}, Gemini · 로컬만` })}
      <h3>돌릴 백엔드</h3>${rows || '<p class="small">아직 백엔드가 없어요.</p>'}
      <div class="row"><button type="button" class="btn small" data-action="pgBackendAdd"${more ? '' : ' disabled title="더 넣을 수 없어요"'}>+ 백엔드</button>
        <button type="button" class="btn small${S.pgDirty ? ' primary' : ''}" data-action="pgSave">저장</button></div>
      <p class="small">백엔드는 동시에 불러요. 사용량 · 비용에는 '프롬프트 놀이터'로 잡혀요.</p>
    </section>`;
}

/** Canon 프롬프트 불러오기 카드: 갈래 · 작품(예시 작품 또는 내 작품) · 화를 고르고 '불러오기'. */
function pgLoadCard() {
  const src = S.pgSrc;
  if (!src) return '';
  const info = src.info;
  const works = (S.projects || []).filter((x) => !x.play);
  const kind = info.kinds.find((k) => k.id === src.kind) || info.kinds[0];
  const pick = pgSrcChoices(info, kind);
  const opt = (v, label, on) => `<option value="${esc(String(v))}"${on ? ' selected' : ''}>${esc(label)}</option>`;
  return `<section class="card" id="pg-load">
      <div class="between"><h2>Canon 프롬프트 불러오기</h2></div>
      <p class="small">구조 · 플롯 · 스토리보드 · 큐 시트 · 집필 · 검수 · 대화로 다듬기 같은 Canon 프롬프트를 실제로 보내는 글과 같게 조립해 시스템 · 요청 칸에 채워요. 작가의 요청 칸은 비워요. 대화로 다듬기는 작가의 말 자리에 '(작가의 말)'를 넣으니 그 줄을 바꿔 돌려요. 작품은 읽기만 해요.</p>
      <div class="grid-2"><div class="field"><label for="pg-src-kind">프롬프트</label><select id="pg-src-kind" data-pg-src="kind">${info.kinds.map((k) => opt(k.id, k.label, k.id === src.kind)).join('')}</select></div>
        <div class="field"><label for="pg-src-project">작품</label><select id="pg-src-project" data-pg-src="project">${opt('', '예시 작품 (mock으로 만든 6화 단편)', !src.project)}${works.map((w) => opt(w.name, w.title || w.name, w.name === src.project)).join('')}</select></div></div>
      ${pick ? `<div class="field"><label for="pg-src-n">${pick.label}</label><select id="pg-src-n" data-pg-src="n">${pick.options.length ? pick.options.map((x) => opt(x.n, x.label, x.n === src.n)).join('') : opt(0, pick.empty, true)}</select></div>` : '<p class="small">작품 하나를 짜는 프롬프트라 화를 고르지 않아요.</p>'}
      <div class="row"><button type="button" class="btn small primary" data-action="pgLoadPrompt"${!pick || pick.options.some((x) => x.n === src.n) ? '' : ` disabled title="고를 수 있는 항목이 없어요"`}>불러오기</button></div>
    </section>`;
}

/** 칸을 저장한다. quiet 면 덮개 없이 (칸을 벗어날 때). 실패하면 알린다. */
async function pgSave(quiet = false) {
  if (!S.pg || !S.pgDirty) return true;
  const id = S.pg.id;
  const body = pgBody(S.pgForm);
  const save = async () => { const s = await api('PUT', `/promptlab/${enc(id)}`, body); if (S.pg && S.pg.id === id) pgSet(s); };
  if (!quiet) return run('프롬프트를 저장하는 중', save);
  try {
    await save();
    const el = $('#pg-saved');
    if (el) el.textContent = '저장했어요';
    return true;
  } catch (e) {
    toast(e.message, true);
    return false;
  }
}

document.addEventListener('input', (e) => {
  if (e.target.dataset && e.target.dataset.root === 'pgForm') {
    S.pgDirty = true;
    const el = $('#pg-saved');
    if (el) el.textContent = '저장하지 않은 고침이 있어요';
  }
});
document.addEventListener('change', (e) => {
  const el = e.target;
  if (!el.dataset || S.route[0] !== 'promptlab' || !S.pgForm) return;
  if (el.dataset.pgProv != null) {
    const b = S.pgForm.backends[Number(el.dataset.pgProv)];
    b.provider = el.value;
    b.model = '';
    b.url = '';
    S.pgDirty = true;
    pgSave(true).then(() => render());
    return;
  }
  if (el.dataset.pgSrc) {
    const key = el.dataset.pgSrc;
    if (key === 'project') { run('작품을 읽는 중', () => pgSources(el.value)); return; }
    if (key === 'kind') { S.pgSrc.kind = el.value; S.pgSrc.n = S.pgSrc.info.defaults[el.value] || 0; }
    if (key === 'n') S.pgSrc.n = Number(el.value);
    render();
    return;
  }
  if (el.dataset.pgNote != null) { actions.pgNote(Number(el.dataset.pgNote), el.value); return; }
  if (el.dataset.root === 'pgForm') pgSave(true);
});

// ----- 시도 -----

function pgRunCard(r) {
  const how = [r.schema_name ? `${r.schema_name} 형식` : '', r.effort ? `추론 강도 ${r.effort}` : '', r.out_tokens ? `한도 ${tok(r.out_tokens)}` : ''];
  const facts = r.ok ? [`${r.seconds}초`, `${Number(r.chars || 0).toLocaleString()}자`, r.tokens_in || r.tokens_out ? `토큰 ${tok(r.tokens_in)} → ${tok(r.tokens_out)}` : '', usd(r.cost), ...how].filter(Boolean).join(' · ')
    : `${r.seconds}초`;
  const body = r.ok ? `<div class="rw-text">${esc(r.text)}</div>` : `<p class="small warn-text" role="alert">${esc(r.error || '실패했어요')}</p>`;
  return `<div class="card" style="padding:var(--pad-card-tight)"><div class="between"><div class="row"><span class="chip${r.ok ? '' : ' bad'}">${esc(r.backend)}</span>${r.model && r.model !== r.backend ? `<span class="small">${esc(r.model)}</span>` : ''}</div></div>
      <div class="small">${esc(facts)}</div>${pgCheckHtml(r)}${body}${pgRawHtml(r)}</div>`;
}

/** 구조화 출력 결과의 검사: Canon 정리(notes)와 빈 칸 수. 펼치면 빈 칸 경로 (tests/test_promptlab_js.py) */
function pgCheckHtml(r) {
  if (!r.ok || !r.schema_name) return '';
  const notes = (r.notes || []).map((x) => `<li>${esc(x)}</li>`).join('');
  const more = r.empty_count > (r.empty || []).length ? ` 외 ${r.empty_count - r.empty.length}곳` : '';
  const empty = r.empty_count ? `<details><summary class="small">빈 칸 ${r.empty_count}곳</summary><p class="small">${esc((r.empty || []).join(', '))}${more}</p></details>` : '<p class="small">빈 칸 없음</p>';
  return `${notes ? `<ul class="small warn-text">${notes}</ul>` : '<p class="small">Canon이 그대로 받는 응답이에요</p>'}${empty}`;
}

/** 실패한 결과의 받은 원문 (형식이 어긋난 응답을 본다). 끝난 이유가 MAX_TOKENS 면 출력 한도에 걸린 것 */
function pgRawHtml(r) {
  if (r.ok || !(r.raw || r.finish)) return '';
  const why = r.finish ? ` · 끝난 이유 ${r.finish}${r.finish === 'MAX_TOKENS' ? '(출력 한도)' : ''}` : '';
  return `<details><summary class="small">받은 원문 ${Number((r.raw || '').length).toLocaleString()}자${esc(why)}</summary><div class="rw-text">${esc(r.raw || '')}</div></details>`;
}

function pgTrialCard(t) {
  const diff = pgDiff(t, S.pgForm);
  const prompt = `<details><summary class="small">이 시도의 프롬프트</summary>
      ${t.system ? `<h3>시스템</h3><div class="rw-text">${esc(t.system)}</div>` : '<p class="small">시스템 프롬프트 없음</p>'}
      <h3>요청</h3><div class="rw-text">${esc(t.prompt)}</div></details>`;
  return `<section class="card" id="pg-trial-${t.no}">
      <div class="between"><div class="row"><span class="chip">${t.no}번</span>${t.source ? `<span class="chip" title="불러온 Canon 프롬프트">${esc(pgSourceLabel(t.source, t.source_edited))}</span>` : ''}${t.temperature != null ? `<span class="small">온도 ${t.temperature}</span>` : ''}<span class="small">${esc(PG_DIFF[diff])}</span></div>
        <span class="small">${esc(fmtDateTime(t.at))}</span></div>
      ${prompt}
      ${(t.blinds || []).length ? pgBlindHtml(t) : `<div class="grid-auto">${t.runs.map(pgRunCard).join('')}</div>`}
      <div class="field"><label for="pg-note-${t.no}" class="sr-only">${t.no}번 메모</label><input id="pg-note-${t.no}" type="text" data-pg-note="${t.no}" value="${esc(t.note || '')}" placeholder="메모: 무엇을 바꿨고 어땠는지"></div>
      <div class="row">
        <button type="button" class="btn small${t.star ? ' primary' : ''}" data-action="pgStar" data-arg="${t.no}" aria-pressed="${t.star}">${t.star ? '★ 고름' : '☆ 고르기'}</button>
        <button type="button" class="btn small" data-action="pgRestore" data-arg="${t.no}"${diff === 'same' ? ' disabled title="지금 프롬프트와 같아요"' : ''}>이 프롬프트로 되돌리기</button>
        <button type="button" class="btn small" data-action="pgCopy" data-arg="${t.no}">결과 복사</button>
        <button type="button" class="btn small danger" data-action="pgDrop" data-arg="${t.no}">지우기</button></div></section>`;
}

const PG_SIDE = { original: '원래 판', set: '실험 판', skip: '건너뜀' };
/** 원래 판 대 실험 판 가려 읽기 (서버 promptlab.blind_view). 고르기 전에는 '가' · '나' 차례로만 보이고 어느 쪽이 원래 판인지 알리지 않는다 */
function pgBlindHtml(t) {
  return t.blinds.map((b) => {
    const tag = ['가', '나'];
    const cols = b.shown.map((r, i) => `<div><div class="row"><span class="chip">${tag[i]}</span>${b.state === 'done' ? `<span class="small">${PG_SIDE[b.order[i]]}</span>` : ''}</div>${pgRunCard(r)}</div>`).join('');
    const foot = b.state === 'done'
      ? `<p class="small">고른 쪽: ${PG_SIDE[b.picked]}</p>`
      : `<div class="row"><button type="button" class="btn small" data-action="pgPick" data-arg="${t.no}:${b.k}:1">가 고르기</button><button type="button" class="btn small" data-action="pgPick" data-arg="${t.no}:${b.k}:2">나 고르기</button><button type="button" class="btn small ghost" data-action="pgPick" data-arg="${t.no}:${b.k}:0">건너뛰기</button></div>`;
    return `<div class="pg-blind"><h3>블라인드 · ${esc((b.shown[0] || {}).backend || '')}</h3><div class="grid-2">${cols}</div>${foot}</div>`;
  }).join('');
}

const pgTrial = (no) => S.pg.trials.find((x) => x.no === Number(no));

Object.assign(actions, {
  async pgNew() {
    await run('새 세션을 만드는 중', async () => {
      const s = await api('POST', '/promptlab', {});
      location.hash = `#/promptlab/${enc(s.id)}`;
    }, { render: 'never' });
  },
  async pgLoadPrompt() {
    const src = S.pgSrc;
    const f = S.pgForm;
    if (((f.system || '').trim() || (f.prompt || '').trim()) && !(await askConfirm('지금 시스템 · 요청 칸을 불러온 프롬프트로 바꿀까요? 지금 칸의 글은 사라져요. 지난 시도에 남은 프롬프트는 그대로예요.', { ok: '바꾸기', danger: true }))) return;
    await run('프롬프트를 조립하는 중', async () => {
      if (S.pgDirty) await pgSave(true);
      pgSet(await api('POST', `/promptlab/${enc(S.pg.id)}/load`, { kind: src.kind, project: src.project, n: src.n }));
      toast(`${S.pg.source.label} 프롬프트를 불러왔어요`);
    });
  },
  async pgSave() {
    if (!S.pgDirty) return toast('바뀐 칸이 없어요');
    if (await pgSave()) toast('프롬프트를 저장했어요');
  },
  async pgBackendAdd() {
    const used = S.pgForm.backends.map((b) => b.provider);
    const next = ['gemini', 'local', 'mock'].find((p) => !used.includes(p)) || 'gemini';
    S.pgForm.backends.push({ provider: next, model: '', url: '' });
    S.pgDirty = true;
    await pgSave(true);
    render();
  },
  async pgBackendDrop(i) {
    S.pgForm.backends.splice(Number(i), 1);
    S.pgDirty = true;
    await pgSave(true);
    render();
  },
  async pgRun() {
    const n = S.pgForm.backends.length;
    await run(n > 1 ? `백엔드 ${n}곳에 동시에 보내는 중…` : '돌리는 중…', async () => {
      pgSet(await api('POST', `/promptlab/${enc(S.pg.id)}/run`, pgBody(S.pgForm)));
      const t = S.pg.trials[S.pg.trials.length - 1];
      const bad = t ? t.runs.filter((r) => !r.ok).length : 0;
      toast(bad ? `${t.no}번 시도를 남겼어요. ${bad}곳은 실패했어요` : `${t.no}번 시도를 남겼어요`, !!bad);
    });
  },
  async pgPick(arg) {
    const [no, k, choice] = String(arg).split(':').map(Number);
    await run('고르는 중', async () => {
      if (S.pgDirty) await pgSave(true);
      pgSet(await api('POST', `/promptlab/${enc(S.pg.id)}/trials/${no}/pick`, { k, choice }));
    });
  },
  async pgStar(no) {
    const t = pgTrial(no);
    await run('고르는 중', async () => {
      if (S.pgDirty) await pgSave(true);
      pgSet(await api('PUT', `/promptlab/${enc(S.pg.id)}/trials/${t.no}`, { star: !t.star }));
    });
  },
  async pgNote(no, note) {
    try {
      if (S.pgDirty) await pgSave(true);
      pgSet(await api('PUT', `/promptlab/${enc(S.pg.id)}/trials/${no}`, { note }));
    } catch (e) {
      toast(e.message, true);
    }
  },
  async pgRestore(no) {
    if (S.pgDirty && !(await askConfirm(`저장하지 않은 고침을 버리고 ${no}번 시도의 프롬프트로 되돌릴까요?`, { ok: '되돌리기', danger: true }))) return;
    await run('되돌리는 중', async () => {
      pgSet(await api('POST', `/promptlab/${enc(S.pg.id)}/trials/${no}/restore`));
      toast(`${no}번 시도의 프롬프트로 되돌렸어요`);
    });
  },
  async pgCopy(no) {
    const t = pgTrial(no);
    const text = t.runs.map((r) => `[${r.backend}${r.model && r.model !== r.backend ? ` · ${r.model}` : ''}]\n${r.ok ? r.text : r.error}`).join('\n\n');
    try {
      await copyPlain(text);
      toast('복사했어요');
    } catch (e) {
      toast(e.message, true);
    }
  },
  async pgDrop(no) {
    if (!(await askConfirm(`${no}번 시도를 지울까요? 되돌릴 수 없어요.`, { ok: '지우기', danger: true }))) return;
    await run('지우는 중', async () => {
      if (S.pgDirty) await pgSave(true);
      pgSet(await api('DELETE', `/promptlab/${enc(S.pg.id)}/trials/${no}`));
    });
  },
  async pgDuplicate() {
    await run('세션을 복제하는 중', async () => {
      if (S.pgDirty) await pgSave(true);
      const s = await api('POST', `/promptlab/${enc(S.pg.id)}/duplicate`);
      location.hash = `#/promptlab/${enc(s.id)}`;
      toast('세션을 복제했어요. 프롬프트를 고쳐 따로 실험해 보세요');
    }, { render: 'never' });
  },
  async pgDelete() {
    if (!(await askConfirm(`'${S.pg.title}' 세션을 지울까요? 시도 ${S.pg.trials.length}개도 함께 지워요. 되돌릴 수 없어요.`, { ok: '지우기', danger: true }))) return;
    await run('지우는 중', async () => {
      await api('DELETE', `/promptlab/${enc(S.pg.id)}`);
      S.pg = null;
      location.hash = '#/promptlab';
    }, { render: 'never' });
  },
});

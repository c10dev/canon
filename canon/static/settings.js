/* 모델 · API 키 설정 화면 (#/settings). app.js 의 S, actions, api, render, input, header 를 그대로 쓴다. */
'use strict';

// ----- 설정 -----

const STAGES = [['plan', '계획 (설정 제안, 문체 분석, 기승전결, 화별 플롯)'], ['write', '본문 쓰기'], ['check', '검수'], ['state', '상태 변경안'],
  ['name', '이름·지명 AI 추천'], ['revise', '본문 부분 수정'], ['illustration', '삽화 프롬프트']];
// 백엔드를 비우면 따르는 단계 (settings.STAGE_PARENT 와 같다)
const STAGE_PARENT = { name: 'plan', revise: 'write', illustration: 'plan' };
const STAGE_PARENT_LABEL = { name: '계획 단계를 따름', revise: '본문 쓰기 단계를 따름', illustration: '계획 단계를 따름' };

// 단계 줄의 모델 칸 안내: 지금 고른 백엔드(비우면 부모 단계, 그다음 위 생성 방식)의 기본 모델. 저장 전에도 선택을 따라간다
function stageModelHint(s) {
  const c = S.config || {};
  const val = (sel, saved) => { const el = $(sel); return el ? el.value : saved; };
  const top = c.provider_source === 'env' ? c.provider : val('#set-provider', c.provider);
  const prov = (x) => {
    const st = (c.stages || {})[x] || {};
    if (st.env === `CANON_LLM_${x.toUpperCase()}`) return st.provider;  // 단계 환경 변수가 이긴다
    const own = val(`#set-stage-${x}`, (c.stage_settings || {})[x] || '');
    if (own) return own;
    return STAGE_PARENT[x] ? prov(STAGE_PARENT[x]) : top;
  };
  const p = top === 'mock' ? 'mock' : prov(s);  // 생성 방식이 mock 이면 모든 단계가 mock
  if (p === 'mock') return '모델: mock';
  if (p === 'local') return `모델: ${val('#set-local-model', c.local_model) || '서버에 하나뿐인 모델'}`;
  if (String(p).startsWith('claude')) return `모델: ${val('#set-claude-model', c.claude_model) || 'Claude 기본'}`;
  return `모델: ${val('#set-model', c.model_setting) || '기본'}`;
}

/** 단계 칸 안내, 보일 백엔드 칸 묶음, 프리셋 안내를 지금 칸 값에 맞춘다 (다시 그리면 저장 전 입력이 사라지므로 이 부분만 고친다). */
function refreshStageFields() {
  STAGES.forEach(([s]) => {
    const el = $(`#set-stage-model-${s}`);
    if (el) el.placeholder = stageModelHint(s);
  });
  syncProviderGroups();
  refreshPresetUi();
}

document.addEventListener('change', (e) => {
  if (S.route[0] !== 'settings') return;
  if (e.target.id === 'preset-pick') refreshPresetUi();
  else if (e.target.id === 'proj-preset') actions.setProjectPreset(e.target.value);
  else if (/^set-(stage-|provider$|model$|local-model$|claude-model$)/.test(e.target.id || '')) refreshStageFields();
});

// ----- 작품 프리셋 (Settings.model_preset: 이 작품의 AI 호출만 고른 단계 프리셋을 쓴다, settings.project_preset) -----

/** 작품이 고른 단계 프리셋. 고르지 않았으면 null, 프리셋이 지워졌으면 { id, missing: true } */
function projectPreset(p = S.project, c = S.config || {}) {
  const id = p && p.settings && p.settings.model_preset;
  if (!id) return null;
  return (c.stage_presets || []).find((x) => x.id === id) || { id, missing: true };
}

/** 이 작품에서 단계 s 가 쓰는 백엔드와 모델 이름 (settings.stage_view 와 같은 규칙). 단계 환경 변수가 프리셋보다 이기고,
 * 프리셋에 없는 단계는 부모 단계, 그다음 생성 방식을 따른다. 프리셋이 없거나 지워졌거나 생성 방식이 mock 이면 전체 설정 값 */
function projectStage(s, p = S.project, c = S.config || {}) {
  const st = (c.stages || {})[s];
  const pre = projectPreset(p, c);
  if (!st || !pre || pre.missing || c.provider === 'mock') return st;
  const own = (x, kind) => ((c.stages || {})[x] || {})[kind === 'LLM' ? 'env' : 'model_env'] === `CANON_${kind}_${x.toUpperCase()}`;
  const prov = (x) => (own(x, 'LLM') ? c.stages[x].provider : (pre.stages || {})[x] || (STAGE_PARENT[x] ? prov(STAGE_PARENT[x]) : c.provider));
  const model = (x) => {
    if (own(x, 'MODEL')) return c.stages[x].model;
    const m = (pre.stage_models || {})[x] || '';
    return !m && STAGE_PARENT[x] && prov(x) === prov(STAGE_PARENT[x]) ? model(STAGE_PARENT[x]) : m;
  };
  const pv = prov(s);
  const label = model(s) || { gemini: c.model_setting, local: c.local_model || '로컬 서버 모델',
    claude: c.claude_model || 'Claude Code 기본 모델', 'claude-api': c.claude_model || 'claude-opus-5-5' }[pv] || pv;
  return { ...st, provider: pv, model: label, source: own(s, 'LLM') ? st.source : 'project' };
}

/** 설정 화면 맨 위 '이 작품의 프리셋' 칸. 작품을 열고 들어왔을 때만 보인다 */
function projectPresetCard(c) {
  if (!S.name || !S.project) return '';
  const pre = projectPreset();
  const opts = '<option value="">전체 설정을 따름</option>'
    + (pre && pre.missing ? `<option value="${esc(pre.id)}" selected>지워진 프리셋 (전체 설정을 따름)</option>` : '')
    + (c.stage_presets || []).map((x) => `<option value="${esc(x.id)}"${pre && x.id === pre.id ? ' selected' : ''}>${esc(x.name)}</option>`).join('');
  const uses = pre && !pre.missing
    ? `<div class="small">${STAGES.slice(0, 4).map(([s, label]) => `${esc(label.replace(/ \(.*\)$/, ''))} ${esc((projectStage(s) || {}).model || '')}`).join(' · ')}</div>` : '';
  return `<section class="card" id="proj-preset-card"><h2>이 작품의 프리셋</h2>
      <div class="field"><label for="proj-preset">'${esc(P().meta.title || S.name)}'에서 쓸 프리셋</label>
        <select id="proj-preset">${opts}</select>
        <div class="small">고르면 이 작품의 AI 호출만 그 프리셋의 단계별 백엔드와 모델을 써요. 다른 작품은 아래 전체 설정을 따라요. 이 칸은 작품에 바로 저장해요.</div>
        ${pre && pre.missing ? '<div class="note warn">고른 프리셋이 지워져서 전체 설정을 따르고 있어요. 다른 프리셋을 고르거나 \'전체 설정을 따름\'으로 바꾸세요.</div>' : ''}
        ${c.provider === 'mock' ? '<div class="small">생성 방식이 mock이라 지금은 모든 단계가 mock으로 돌아요.</div>' : uses}</div>
    </section>`;
}

// ----- 단계 프리셋 (settings.presets: 기본 묶음 + 설정 파일 stage_presets) -----

/** 지금 단계 칸 값. 칸이 없으면(화면 밖) 저장된 설정. */
function stageFieldValues() {
  const c = S.config || {};
  const val = (sel, saved) => { const el = $(sel); return el ? el.value.trim() : saved || ''; };
  return {
    stages: Object.fromEntries(STAGES.map(([s]) => [s, val(`#set-stage-${s}`, (c.stage_settings || {})[s])])),
    stage_models: Object.fromEntries(STAGES.map(([s]) => [s, val(`#set-stage-model-${s}`, (c.stage_model_settings || {})[s])])),
  };
}

/** 단계 칸 값과 똑같은 프리셋 (빈 칸은 빈 칸끼리 같다). 없으면 null. */
function presetOf(list, cur) {
  const same = (a, b) => STAGES.every(([s]) => ((a || {})[s] || '') === ((b || {})[s] || ''));
  return (list || []).find((p) => same(p.stages, cur.stages) && same(p.stage_models, cur.stage_models)) || null;
}

function presetOptions(list, cur) {
  const opt = (p) => `<option value="${esc(p.id)}"${p.id === cur ? ' selected' : ''}>${esc(p.name)}</option>`;
  const mine = list.filter((p) => !p.builtin);
  return `<option value="">프리셋 고르기</option><optgroup label="기본">${list.filter((p) => p.builtin).map(opt).join('')}</optgroup>`
    + (mine.length ? `<optgroup label="내 프리셋">${mine.map(opt).join('')}</optgroup>` : '');
}

function presetStatus(cur = stageFieldValues()) {
  const p = presetOf((S.config || {}).stage_presets, cur);
  return p ? `지금 단계 칸은 '${esc(p.name)}' 프리셋과 같아요.` : '지금 단계 칸은 어느 프리셋과도 달라요. 섞은 조합은 이름을 붙여 저장해 두세요.';
}

function refreshPresetUi() {
  const st = $('#preset-status');
  if (st) st.innerHTML = presetStatus();
  const pick = $('#preset-pick');
  const del = $('#preset-del');
  if (pick && del) del.hidden = !((S.config || {}).stage_presets || []).some((p) => p.id === pick.value && !p.builtin);
}

function presetBox(c) {
  const list = c.stage_presets || [];
  const saved = { stages: c.stage_settings || {}, stage_models: c.stage_model_settings || {} };  // 그리는 중에는 칸이 아직 없다
  const cur = presetOf(list, saved);
  return `<div class="field"><label for="preset-pick">프리셋</label>
      <div class="stage-row">
        <select id="preset-pick">${presetOptions(list, cur && cur.id)}</select>
        <div class="row"><button type="button" class="btn" data-action="applyPreset">칸 채우기</button>
          <button type="button" class="btn danger" id="preset-del" data-action="deletePreset"${cur && !cur.builtin ? '' : ' hidden'}>지우기</button></div>
      </div>
      <div class="small" id="preset-status" role="status">${presetStatus(saved)}</div></div>
    <div class="field"><label for="preset-name">지금 단계 칸을 내 프리셋으로</label>
      <div class="stage-row">
        <input id="preset-name" type="text" placeholder="예: 계획은 Claude, 본문은 Gemini">
        <div class="row"><button type="button" class="btn" data-action="savePreset">프리셋으로 저장</button></div>
      </div>
      <div class="small">같은 이름이면 덮어써요. 프리셋 저장은 단계 설정을 바꾸지 않아요. 쓰려면 아래 '저장'을 누르세요.</div></div>`;
}

/** 지금 고른 생성 방식과 단계별 백엔드가 실제로 쓰는 백엔드 (stage_provider 와 같은 규칙: 생성 방식이 mock 이면 모두 mock). */
function usedProviders() {
  const c = S.config || {};
  const top = $('#set-provider') ? $('#set-provider').value : c.provider;
  if (top === 'mock') return new Set(['mock']);
  const own = (x) => {
    const st = (c.stages || {})[x] || {};
    if (st.env === `CANON_LLM_${x.toUpperCase()}`) return st.provider;
    const el = $(`#set-stage-${x}`);
    return el ? el.value : (c.stage_settings || {})[x] || '';
  };
  const prov = (x) => own(x) || (STAGE_PARENT[x] ? prov(STAGE_PARENT[x]) : top);
  return new Set([top, ...STAGES.map(([x]) => prov(x))]);
}

let settingsShowAll = false;  // '모든 방식의 칸 보기'를 눌렀다

/** 쓰지 않는 백엔드의 칸 묶음(Gemini · 로컬 서버 · Claude)은 숨긴다. 새로 쓰게 된 묶음은 펼친다. 숨긴 칸도 값은 그대로 저장한다. */
function syncProviderGroups() {
  const used = usedProviders();
  document.querySelectorAll('#app [data-prov]').forEach((g) => {
    const on = settingsShowAll || g.dataset.prov.split(' ').some((x) => used.has(x));
    const d = g.matches('details') ? g : g.querySelector('details');
    if (on && g.hidden && d) d.open = true;
    g.hidden = !on;
  });
  const m = $('#prov-mock');
  if (m) m.hidden = !used.has('mock');
  const all = $('#prov-all');
  if (all) all.hidden = settingsShowAll || [...document.querySelectorAll('#app [data-prov]')].every((g) => !g.hidden);
}

// 설정 화면 '돌아가기': 앱 안에서 넘어왔으면 뒤로, 주소로 바로 열었으면 앱 첫 화면(작품 안이면 그 작품)으로
let settingsNavs = 0;
window.addEventListener('hashchange', () => { settingsNavs += 1; });
let settingsSavedAt = null;  // 저장 버튼 옆에 남기는 마지막 저장 시각

function providerOptions(cur) {
  return [['gemini', 'Gemini API'], ['local', '로컬 서버 (OpenAI 호환)'], ['claude', 'Claude 구독 로그인 (Claude Code)'], ['claude-api', 'Claude API 키'],
    ['mock', 'mock (AI 호출 없이 화면 확인용)']]
    .map(([v, l]) => `<option value="${v}"${cur === v ? ' selected' : ''}>${l}</option>`).join('');
}

/** 단계를 비워 두면 따르는 환경 변수(CANON_LLM, CANON_MODEL, 부모 단계 변수) 안내. 단계마다 되풀이하지 않고 같은 안내끼리 묶어 한 번씩 적는다. */
function inheritedEnvNotes(c) {
  const groups = new Map();
  STAGES.forEach(([s, label]) => {
    const st = (c.stages || {})[s] || {};
    [[st.env, `CANON_LLM_${s.toUpperCase()}`, '백엔드를'], [st.model_env, `CANON_MODEL_${s.toUpperCase()}`, '모델을']].forEach(([name, own, what]) => {
      if (!name || name === own) return;
      const k = `${name}의 ${what}`;
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(label.replace(/ \(.*\)$/, ''));
    });
  });
  return [...groups].map(([k, labels]) => `<div class="small">${labels.length === STAGES.length ? '단계' : esc(labels.join(', '))} 칸을 비워 두면 환경 변수 ${esc(k)} 따라요.</div>`).join('');
}

function viewSettings() {
  const c = S.config || {};
  const src = { env: '환경 변수', file: '설정 파일', default: '기본값', none: '없음' };
  const envNote = (s, name) => s === 'env' ? `<div class="small">환경 변수 ${name}에 값이 있어 그 값이 우선해요.</div>` : '';
  // 처음 쓰는 사람은 생성 방식 · 키 · 모델만 보면 된다. 로컬 서버와 단계별 칸은 쓰고 있을 때만 펼친다
  const localOpen = c.provider === 'local' || (!!c.local_url && !['default', 'none'].includes(c.local_url_source)) || Object.values(c.stage_settings || {}).includes('local');
  const stageOpen = Object.values(c.stage_settings || {}).some(Boolean) || Object.values(c.stage_model_settings || {}).some(Boolean);
  const envLocked = c.provider_source === 'env';
  const envMock = envLocked && c.provider === 'mock';  // stage_provider: 생성 방식이 mock 이면 단계 선택과 상관없이 모두 mock
  const inheritedNotes = inheritedEnvNotes(c);
  const keyState = c.key_source === 'none'
    ? '<span class="chip" style="background:var(--red-soft);color:var(--red)">없음</span>'
    : `<span class="chip finalized">${esc(c.key_hint)}</span> <span class="small">${src[c.key_source]}</span>`;
  return `${header('Canon', '모델 · API 키 설정', '여기서 저장한 값은 이 컴퓨터의 설정 파일에만 들어가요. 작품 폴더나 저장소에는 들어가지 않아요.', '<button type="button" class="btn" data-action="settingsBack">돌아가기</button>')}
    ${projectPresetCard(c)}
    <section class="card">
      <div class="field"><label for="set-provider">생성 방식</label>
        <select id="set-provider"${envLocked ? ' disabled aria-describedby="set-provider-env"' : ''}>
          ${providerOptions(c.provider)}
        </select>${envLocked ? `<div class="small" id="set-provider-env">환경 변수 CANON_LLM(${esc(c.provider)})이 우선해서 여기서는 바꿀 수 없어요. 바꾸려면 CANON_LLM 없이 서버를 다시 켜세요.</div>` : ''}
        ${envMock ? '' : '<div class="small">단계별로 다르게 쓰려면 아래 \'단계별 백엔드와 모델\'에서 고르세요.</div>'}</div>
      <div class="note plain" id="prov-mock" hidden>mock은 AI를 부르지 않아서 키와 모델 칸이 필요 없어요.</div>
      <div class="prov-group" data-prov="gemini">
      ${geminiAuthSettings(c, `<div class="field"><label for="set-key">Gemini API 키 <span class="hint">지금: </span>${keyState}</label>
        <input id="set-key" type="password" autocomplete="off" placeholder="${c.key_source === 'none' ? 'AIza… 로 시작하는 키' : '바꿀 때만 입력'}">
        <div class="small"><a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">Google AI Studio</a>에서 무료로 발급받을 수 있어요. 저장한 키는 화면에 다시 보여주지 않아요.</div>
        ${envNote(c.key_source, 'GEMINI_API_KEY')}</div>`)}
      <div class="field"><label for="set-model">모델</label>
        <input id="set-model" type="text" list="model-options" value="${esc(c.model_setting || '')}">
        ${modelDatalist()}
        <div class="small">모든 단계의 기본 Gemini 모델이에요. gemini-4-argon이 기본이고, 단계마다 바꾸려면 아래 '단계별 백엔드와 모델'에서 고르세요.</div>${envNote(c.model_source, 'CANON_MODEL')}</div>
      <div class="small" id="model-status">${modelStatus()}</div>
      </div>
      <details class="set-more prov-group" data-prov="local"${localOpen ? ' open' : ''}><summary><h2>로컬 서버</h2> <span class="small">Ollama · llama.cpp 같은 내 컴퓨터의 모델을 쓸 때</span></summary>
      <p class="desc">Ollama, llama.cpp, vLLM, LM Studio처럼 OpenAI 호환 API를 여는 서버예요. 주소는 /v1까지 적어요.</p>
      <div class="field"><label for="set-local-url">서버 주소</label>
        <input id="set-local-url" type="text" value="${esc(c.local_url || '')}" placeholder="http://localhost:11434/v1">
        <div class="small">Ollama :11434/v1 · llama.cpp :8080/v1 · vLLM :8000/v1 · LM Studio :1234/v1</div>${envNote(c.local_url_source, 'CANON_LOCAL_URL')}</div>
      <div class="field"><label for="set-local-model">모델 이름</label>
        <input id="set-local-model" type="text" list="model-options" value="${esc(c.local_model || '')}" placeholder="비우면 서버에 하나뿐인 모델">${envNote(c.local_model_source, 'CANON_LOCAL_MODEL')}</div>
      <div class="field"><label for="set-local-key">서버 키 <span class="hint">지금: ${c.has_local_key ? '있음' : '없음'}</span></label>
        <input id="set-local-key" type="password" autocomplete="off" placeholder="서버가 키를 요구할 때만"></div>
      </details>
      <div class="prov-group" data-prov="claude claude-api">${claudeSettings(c)}</div>
      <div class="row" id="prov-all" hidden><button type="button" class="link-btn" data-action="settingsShowAll">다른 생성 방식의 칸도 보기</button></div>
      <details class="set-more"${stageOpen ? ' open' : ''}><summary><h2>단계별 백엔드와 모델</h2> <span class="small">계획 · 본문 · 검수마다 다른 모델을 쓸 때</span></summary>
      <p class="desc">예: 계획과 검수는 gemini-4-argon, 상태 변경안과 이름 추천은 빠르고 싼 gemini-3.8-flash, 본문은 로컬 모델. 모델 칸을 비우면 그 백엔드의 기본 모델(위 '모델' 또는 로컬 '모델 이름')을 써요.</p>
      ${envMock ? '<div class="note plain">환경 변수 CANON_LLM이 mock이라 모든 단계가 mock으로 돌아요. 그래서 단계 백엔드를 고를 수 없어요.</div>' : inheritedNotes + presetBox(c)}
      ${STAGES.map(([s, label]) => {
        const st = (c.stages || {})[s] || {};
        // 단계 자체의 환경 변수는 선택보다 우선한다. 물려받은 환경 변수(CANON_LLM, 부모 단계) 안내는 위에 한 번만 둔다 (inheritedNotes)
        const ownEnv = (name, own, what) => name && name === own ? `<div class="small" id="set-stage-${s}-${what}-env">환경 변수 ${name} 값이 우선해서 여기서는 바꿀 수 없어요.</div>` : '';
        const locked = envMock || st.env === `CANON_LLM_${s.toUpperCase()}`;
        return `<div class="field"><label for="set-stage-${s}">${label} <span class="hint">지금: ${esc(st.model || '')}</span></label>
          <div class="stage-row">
            <select id="set-stage-${s}" aria-label="${esc(label)} 백엔드"${locked ? ' disabled' : ''}${st.env === `CANON_LLM_${s.toUpperCase()}` ? ` aria-describedby="set-stage-${s}-llm-env"` : ''}><option value="">${STAGE_PARENT_LABEL[s] || '위 생성 방식을 따름'}</option>${providerOptions((c.stage_settings || {})[s])}</select>
            <input id="set-stage-model-${s}" type="text" list="model-options" aria-label="${esc(label)} 모델" value="${esc((c.stage_model_settings || {})[s] || '')}" placeholder="${esc(stageModelHint(s))}">
          </div>
          ${ownEnv(st.env, `CANON_LLM_${s.toUpperCase()}`, 'llm')}
          ${ownEnv(st.model_env, `CANON_MODEL_${s.toUpperCase()}`, 'model')}</div>`;
      }).join('')}
      </details>
      <div class="row">
        <button class="btn primary" data-action="saveSettings">저장</button>
        <button class="btn" data-action="testSettings">연결 확인</button>
        ${c.key_source === 'file' ? '<button class="btn danger" data-action="clearKey">저장된 키 지우기</button>' : ''}
        <span class="small" role="status">${settingsSavedAt ? `${esc(settingsSavedAt.what)} · ${fmtDateTime(settingsSavedAt.at)}` : ''}</span>
      </div>
      <div class="small">설정 파일: ${esc(c.path)}</div>
    </section>
    <details class="card set-more" id="price-more"><summary><strong>가격표 펼치기</strong> <span class="small">추정 비용 계산에 쓰는 값. 사용량 · 비용 화면에서도 고칠 수 있어요</span></summary><div id="price-box">${viewPrices()}</div></details>
    <div class="small">쓴 비용은 <a href="#/usage">사용량 · 비용</a> 화면에서 봐요.</div>`;
}

// 모델 칸 추천 목록: Gemini API 와 로컬 서버에 실제로 있는 모델. 없으면 직접 적는다.
const KNOWN_MODELS = ['gemini-4-argon', 'gemini-3.8-flash'];

function modelDatalist() {
  const m = S.models || {};
  const opts = [
    ...(((m.gemini || {}).models || []).length ? m.gemini.models : KNOWN_MODELS).map((x) => [x, 'Gemini']),
    ...((m.local || {}).models || []).map((x) => [x, '로컬 서버']),
    ...[...new Set([...((m.claude || {}).models || []), ...((m['claude-api'] || {}).models || [])])].map((x) => [x, 'Claude']),
  ];
  return `<datalist id="model-options">${opts.map(([v, l]) => `<option value="${esc(v)}" label="${l}"></option>`).join('')}</datalist>`;
}

function modelStatus() {
  const m = S.models;
  if (!m) return '모델 목록을 불러오는 중…';
  // 단계에서 쓰는 백엔드만 알린다 (Gemini 만 쓰면 꺼진 로컬 서버 오류는 보이지 않는다)
  const c = S.config || {};
  const used = new Set([c.provider, ...Object.values(c.stages || {}).map((x) => x.provider)]);
  const why = (r) => ({ no_key: c.gemini_auth === 'vertex' ? '서비스 계정 키 파일과 프로젝트 ID를 넣고 저장하면 목록을 불러와요' : 'API 키를 넣고 저장하면 목록을 불러와요', unreachable: '로컬 서버가 응답하지 않아요. 주소를 확인하세요' }[r.reason] || `목록을 못 불러왔어요 (${esc((r.error || '').slice(0, 120))})`);
  const part = (name, r) => (r.error ? `${name}: ${why(r)}` : `${name} ${r.models.length}개`);
  const parts = [['gemini', 'Gemini'], ['local', '로컬 서버']].filter(([k]) => used.has(k) && m[k]).map(([k, name]) => part(name, m[k]));
  return `모델 칸을 누르면 고를 수 있어요. ${parts.length ? parts.join(' · ') + '. ' : ''}목록에 없으면 이름을 직접 적어도 돼요. <button type="button" class="link-btn" data-action="loadModels">다시 불러오기</button>`;
}

async function loadModelList(force) {
  if (S.models && !force) return;
  if (force) S.models = null;
  const st = $('#model-status');
  if (st) st.innerHTML = modelStatus();
  try {
    S.models = await api('GET', '/config/models');
  } catch (e) {
    S.models = { gemini: { models: [], error: e.message }, local: { models: [], error: e.message } };
  }
  // 다시 그리면 저장 전 입력이 사라지므로 목록과 안내만 바꾼다
  const dl = $('#model-options');
  if (dl) dl.outerHTML = modelDatalist();
  const st2 = $('#model-status');
  if (st2) st2.innerHTML = modelStatus();
}


Object.assign(actions, {
  // 설정
  async saveSettings() {
    const key = $('#set-key').value.trim();
    const c = S.config || {};
    const body = {
      stages: Object.fromEntries(STAGES.map(([s]) => [s, $(`#set-stage-${s}`).value])),
      stage_models: Object.fromEntries(STAGES.map(([s]) => [s, $(`#set-stage-model-${s}`).value.trim()])),
    };
    // 환경 변수나 기본값을 보여 주기만 한 칸은 보내지 않는다. 보내면 설정 파일에 굳어 환경 변수를 바꿔도 따라가지 않는다
    [['provider', '#set-provider', c.provider], ['model', '#set-model', c.model_setting], ['local_url', '#set-local-url', c.local_url], ['local_model', '#set-local-model', c.local_model]]
      .forEach(([k, sel, shown]) => {
        const v = $(sel).value.trim();
        if (['env', 'default'].includes(c[`${k}_source`]) && v === (shown || '')) return;
        body[k] = v;
      });
    if (key) body.api_key = key;
    const lkey = $('#set-local-key').value.trim();
    if (lkey) body.local_key = lkey;
    Object.assign(body, claudeSettingsBody(), geminiAuthBody(c));
    const ok = await run('저장 중', async () => {
      S.config = await api('PUT', '/config', body);
      S.health = await api('GET', '/config/health').catch(() => null);
      S.settingsDirty = false;
      settingsSavedAt = { what: '저장했어요', at: new Date().toISOString() };
      toast('설정을 저장했어요');
    }, { render: 'success' });  // 실패하면 다시 그리지 않아 적은 키와 모델이 칸에 남는다
    if (ok) $('[data-action="saveSettings"]')?.focus();  // 다시 그리면 초점이 페이지 처음으로 가므로 돌려준다
    return ok;
  },
  async clearKey() {
    if (!confirm('저장된 API 키를 지울까요?')) return;
    const ok = await run('지우는 중', async () => {
      S.config = await api('PUT', '/config', { clear_key: true });
      settingsSavedAt = { what: '키를 지웠어요', at: new Date().toISOString() };
      toast('키를 지웠어요');
    });
    if (ok) $('#set-key')?.focus();
  },
  applyPreset() {
    const c = S.config || {};
    const p = (c.stage_presets || []).find((x) => x.id === $('#preset-pick').value);
    if (!p) { toast('프리셋을 먼저 고르세요'); $('#preset-pick').focus(); return; }
    const kept = [];
    STAGES.forEach(([s, label]) => {
      const sel = $(`#set-stage-${s}`);
      if (sel.disabled) { if ((p.stages[s] || '') !== sel.value) kept.push(label.replace(/ \(.*\)$/, '')); }  // 환경 변수로 잠긴 칸
      else sel.value = p.stages[s] || '';
      $(`#set-stage-model-${s}`).value = p.stage_models[s] || '';
    });
    S.settingsDirty = true;
    refreshStageFields();
    const used = new Set(Object.values(p.stages));
    const noKey = used.has('claude-api') && c.anthropic_key_source === 'none' ? ' Claude API 키를 넣어야 써요.'
      : used.has('gemini') && c.key_source === 'none' && c.gemini_auth !== 'vertex' ? ' Gemini API 키를 넣어야 써요.' : '';
    toast(`'${p.name}' 프리셋으로 칸을 채웠어요. 저장을 눌러야 바뀌어요.${kept.length ? ` 환경 변수로 정한 ${kept.join(', ')} 칸은 그대로예요.` : ''}${noKey}`);
  },
  async savePreset() {
    const name = $('#preset-name').value.trim();
    if (!name) { toast('프리셋 이름을 적어 주세요'); $('#preset-name').focus(); return; }
    if ((S.config.stage_presets || []).some((p) => !p.builtin && p.name === name) && !confirm(`'${name}' 프리셋을 지금 단계 칸으로 바꿀까요?`)) return;
    await run('프리셋 저장 중', async () => {
      const c = await api('POST', '/config/presets', { name, ...stageFieldValues() });
      S.config.stage_presets = c.stage_presets;  // 다시 그리면 저장 전 칸이 사라지므로 프리셋 목록만 바꾼다
      const saved = c.stage_presets.find((p) => !p.builtin && p.name === name);
      $('#preset-pick').innerHTML = presetOptions(c.stage_presets, saved && saved.id);
      $('#preset-name').value = '';
      refreshPresetUi();
      toast(`'${name}' 프리셋을 저장했어요`);
    }, { render: 'never' });
  },
  async deletePreset() {
    const p = (S.config.stage_presets || []).find((x) => x.id === $('#preset-pick').value);
    if (!p || p.builtin) return;
    if (!confirm(`'${p.name}' 프리셋을 지울까요? 지금 단계 설정은 그대로예요.`)) return;
    await run('지우는 중', async () => {
      const c = await api('DELETE', `/config/presets/${encodeURIComponent(p.id)}`);
      S.config.stage_presets = c.stage_presets;
      $('#preset-pick').innerHTML = presetOptions(c.stage_presets, '');
      refreshPresetUi();
      toast('프리셋을 지웠어요');
    }, { render: 'never' });
    $('#preset-pick')?.focus();
  },
  /** 이 작품의 프리셋을 바로 저장한다. 설정 화면의 저장 전 칸이 사라지지 않게 작품 프리셋 칸만 다시 그린다 */
  async setProjectPreset(id) {
    const redraw = () => {
      const card = $('#proj-preset-card');
      if (card) card.outerHTML = projectPresetCard(S.config || {});
      $('#proj-preset')?.focus();
    };
    if (S.dirty) {
      toast('저장하지 않은 작품 수정이 있어요. 작품을 먼저 저장하세요', true);
      redraw();
      return;
    }
    const ok = await run('저장하는 중', async () => {
      S.project = await api('PUT', `/projects/${enc(S.name)}/model-preset`, { preset: id });
    }, { render: 'never' });
    redraw();
    if (ok) {
      const pre = projectPreset();
      toast(pre && !pre.missing ? `이 작품은 이제 '${pre.name}' 프리셋을 써요` : '이 작품은 이제 전체 설정을 따라요');
    }
  },
  settingsShowAll() {
    settingsShowAll = true;
    syncProviderGroups();
  },
  settingsBack() {
    if (settingsNavs > 0) history.back();
    else location.hash = S.name ? base() : '#/';
  },
  async loadModels() {
    await loadModelList(true);
  },
  async testSettings() {
    // 서버는 저장된 설정으로 시험한다. 적기만 한 값이 있으면 먼저 저장해야 그 값의 결과가 나온다
    if (S.settingsDirty) {
      if (!confirm('입력한 설정을 아직 저장하지 않았어요. 저장한 뒤 연결을 확인할까요?')) return;
      await actions.saveSettings();
      if (S.settingsDirty) return;  // 저장하지 못했다
    }
    await run('연결 확인 중', async () => {
      const r = await api('POST', '/config/test');
      toast(r.message);
    }, { render: 'never' });
  },
});

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

document.addEventListener('change', (e) => {
  if (S.route[0] !== 'settings' || !/^set-(stage-|provider$|model$|local-model$|claude-model$)/.test(e.target.id || '')) return;
  STAGES.forEach(([s]) => {
    const el = $(`#set-stage-model-${s}`);
    if (el) el.placeholder = stageModelHint(s);
  });
});

// 설정 화면 '돌아가기': 앱 안에서 넘어왔으면 뒤로, 주소로 바로 열었으면 앱 첫 화면(작품 안이면 그 작품)으로
let settingsNavs = 0;
window.addEventListener('hashchange', () => { settingsNavs += 1; });
let settingsSavedAt = null;  // 저장 버튼 옆에 남기는 마지막 저장 시각

function providerOptions(cur) {
  return [['gemini', 'Gemini API'], ['local', '로컬 서버 (OpenAI 호환)'], ['claude', 'Claude 구독 로그인 (Claude Code)'], ['claude-api', 'Claude API 키'],
    ['mock', 'mock (AI 호출 없이 화면 확인용)']]
    .map(([v, l]) => `<option value="${v}"${cur === v ? ' selected' : ''}>${l}</option>`).join('');
}

function viewSettings() {
  const c = S.config || {};
  const src = { env: '환경 변수', file: '설정 파일', default: '기본값', none: '없음' };
  const envNote = (s, name) => s === 'env' ? `<div class="small">환경 변수 ${name}에 값이 있어 그 값이 우선해요.</div>` : '';
  // 처음 쓰는 사람은 생성 방식 · 키 · 모델만 보면 된다. 로컬 서버와 단계별 칸은 쓰고 있을 때만 펼친다
  const localOpen = c.provider === 'local' || (!!c.local_url && !['default', 'none'].includes(c.local_url_source)) || Object.values(c.stage_settings || {}).includes('local');
  const stageOpen = Object.values(c.stage_settings || {}).some(Boolean) || Object.values(c.stage_model_settings || {}).some(Boolean);
  const keyState = c.key_source === 'none'
    ? '<span class="chip" style="background:var(--red-soft);color:var(--red)">없음</span>'
    : `<span class="chip finalized">${esc(c.key_hint)}</span> <span class="small">${src[c.key_source]}</span>`;
  return `${header('Canon', '모델 · API 키 설정', '여기서 저장한 값은 이 컴퓨터의 설정 파일에만 들어가요. 작품 폴더나 저장소에는 들어가지 않아요.', '<button type="button" class="btn" data-action="settingsBack">돌아가기</button>')}
    <section class="card">
      <div class="field"><label for="set-provider">생성 방식</label>
        <select id="set-provider">
          ${providerOptions(c.provider)}
        </select>${envNote(c.provider_source, 'CANON_LLM')}
        <div class="small">단계별로 다르게 쓰려면 아래 '단계별 백엔드'에서 고르세요.</div></div>
      ${geminiAuthSettings(c, `<div class="field"><label for="set-key">Gemini API 키 <span class="hint">지금: </span>${keyState}</label>
        <input id="set-key" type="password" autocomplete="off" placeholder="${c.key_source === 'none' ? 'AIza… 로 시작하는 키' : '바꿀 때만 입력'}">
        <div class="small"><a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">Google AI Studio</a>에서 무료로 발급받을 수 있어요. 저장한 키는 화면에 다시 보여주지 않아요.</div>
        ${envNote(c.key_source, 'GEMINI_API_KEY')}</div>`)}
      <div class="field"><label for="set-model">모델</label>
        <input id="set-model" type="text" list="model-options" value="${esc(c.model_setting || '')}">
        ${modelDatalist()}
        <div class="small">모든 단계의 기본 Gemini 모델이에요. gemini-4-argon이 기본이고, 단계마다 바꾸려면 아래 '단계별 백엔드와 모델'에서 고르세요.</div>${envNote(c.model_source, 'CANON_MODEL')}</div>
      <div class="small" id="model-status">${modelStatus()}</div>
      <details class="set-more"${localOpen ? ' open' : ''}><summary><h2>로컬 서버</h2> <span class="small">Ollama · llama.cpp 같은 내 컴퓨터의 모델을 쓸 때</span></summary>
      <p class="desc">Ollama, llama.cpp, vLLM, LM Studio처럼 OpenAI 호환 API를 여는 서버예요. 주소는 /v1까지 적어요.</p>
      <div class="field"><label for="set-local-url">서버 주소</label>
        <input id="set-local-url" type="text" value="${esc(c.local_url || '')}" placeholder="http://localhost:11434/v1">
        <div class="small">Ollama :11434/v1 · llama.cpp :8080/v1 · vLLM :8000/v1 · LM Studio :1234/v1</div>${envNote(c.local_url_source, 'CANON_LOCAL_URL')}</div>
      <div class="field"><label for="set-local-model">모델 이름</label>
        <input id="set-local-model" type="text" list="model-options" value="${esc(c.local_model || '')}" placeholder="비우면 서버에 하나뿐인 모델">${envNote(c.local_model_source, 'CANON_LOCAL_MODEL')}</div>
      <div class="field"><label for="set-local-key">서버 키 <span class="hint">지금: ${c.has_local_key ? '있음' : '없음'}</span></label>
        <input id="set-local-key" type="password" autocomplete="off" placeholder="서버가 키를 요구할 때만"></div>
      </details>
      ${claudeSettings(c)}
      <details class="set-more"${stageOpen ? ' open' : ''}><summary><h2>단계별 백엔드와 모델</h2> <span class="small">계획 · 본문 · 검수마다 다른 모델을 쓸 때</span></summary>
      <p class="desc">예: 계획과 검수는 gemini-4-argon, 상태 변경안과 이름 추천은 빠르고 싼 gemini-3.8-flash, 본문은 로컬 모델. 모델 칸을 비우면 그 백엔드의 기본 모델(위 '모델' 또는 로컬 '모델 이름')을 써요.</p>
      ${STAGES.map(([s, label]) => {
        const st = (c.stages || {})[s] || {};
        // 단계 자체의 환경 변수는 선택보다 우선하고, 물려받은 환경 변수(CANON_LLM, 부모 단계)는 비워 둘 때만 따른다
        const envLine = (name, own, what) => !name ? '' : name === own
          ? `<div class="small">환경 변수 ${name} 값이 우선해요.</div>`
          : `<div class="small">비워 두면 환경 변수 ${name}의 ${what} 따라요.</div>`;
        return `<div class="field"><label for="set-stage-${s}">${label} <span class="hint">지금: ${esc(st.model || '')}</span></label>
          <div class="stage-row">
            <select id="set-stage-${s}" aria-label="${esc(label)} 백엔드"><option value="">${STAGE_PARENT_LABEL[s] || '위 생성 방식을 따름'}</option>${providerOptions((c.stage_settings || {})[s])}</select>
            <input id="set-stage-model-${s}" type="text" list="model-options" aria-label="${esc(label)} 모델" value="${esc((c.stage_model_settings || {})[s] || '')}" placeholder="${esc(stageModelHint(s))}">
          </div>
          ${envLine(st.env, `CANON_LLM_${s.toUpperCase()}`, '백엔드를')}
          ${envLine(st.model_env, `CANON_MODEL_${s.toUpperCase()}`, '모델을')}</div>`;
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

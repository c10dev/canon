/* 설정 대화상자: 지금 화면 위에 뜬다. 왼쪽은 찾기와 갈래(이 컴퓨터 · 이 작품 · 이 브라우저), 오른쪽은 줄마다 이름 · 설명 · 칸.
   고르면 바로 저장한다(저장 띠 없음). 키 칸만 줄 안의 '키 저장'으로 저장한다. 주소 #/settings[/갈래] 는 대화상자를 연다(openSettings).
   app.js 의 S, actions, api, esc, toast 를 그대로 쓴다. Claude 줄은 claude.js, Vertex 줄은 vertex.js. */
'use strict';

// ----- 단계 (settings.STAGES 와 같은 순서) -----

const STAGES = [['plan', '계획', '설정 제안 · 문체 분석 · 기승전결 · 화별 플롯'], ['write', '본문 쓰기', '화 본문'], ['check', '검수', '모순 찾기'],
  ['state', '상태 변경안', '본문에서 바뀐 상태 뽑기'], ['name', '이름 · 지명 추천', ''], ['revise', '본문 부분 수정', ''],
  ['illustration', '삽화 프롬프트', ''], ['play', '플레이 장면', '플레이 모드']];
// 백엔드를 비우면 따르는 단계 (settings.STAGE_PARENT 와 같다)
const STAGE_PARENT = { name: 'plan', revise: 'write', illustration: 'plan', play: 'write' };
const stageName = (s) => (STAGES.find(([x]) => x === s) || [s, s])[1];
const PROVIDERS = [['gemini', 'Gemini API'], ['claude', 'Claude 구독 로그인'], ['claude-api', 'Claude API 키'], ['local', '로컬 서버'],
  ['mock', 'mock (AI 없이 화면 확인)']];
const provName = (v) => (PROVIDERS.find(([x]) => x === v) || [v, v])[1];

// ----- 작품 프리셋 (Settings.model_preset: 이 작품의 AI 호출만 고른 단계 프리셋을 쓴다, settings.project_preset) -----

/** 작품이 고른 단계 프리셋. 고르지 않았으면 null, 프리셋이 지워졌으면 { id, missing: true } */
function projectPreset(p = S.project, c = S.config || {}) {
  const id = p && p.settings && p.settings.model_preset;
  if (!id) return null;
  return (c.stage_presets || []).find((x) => x.id === id) || { id, missing: true };
}

/** 이 작품에서 단계 s 가 쓰는 백엔드와 모델 이름 (settings.stage_view 와 같은 규칙). 단계 환경 변수가 프리셋보다 이기고,
 * 프리셋에 없는 단계는 부모 단계, 그다음 기본 AI 를 따른다. 프리셋이 없거나 지워졌거나 기본 AI 가 mock 이면 전체 설정 값 */
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

/** 단계 칸 값과 똑같은 프리셋 (빈 칸은 빈 칸끼리 같다). 없으면 null. */
function presetOf(list, cur) {
  const same = (a, b) => STAGES.every(([s]) => ((a || {})[s] || '') === ((b || {})[s] || ''));
  return (list || []).find((p) => same(p.stages, cur.stages) && same(p.stage_models, cur.stage_models)) || null;
}

// ----- 줄 목록과 찾기 -----

const SET_GROUPS = [['pc', '이 컴퓨터'], ['project', '이 작품'], ['browser', '이 브라우저']];
const SET_CATS = [['ai', 'AI 연결', 'pc', '이 컴퓨터의 모든 작품에 적용돼요. 고르면 바로 저장해요.'],
  ['stages', '단계별 모델', 'pc', '단계마다 다른 AI · 모델을 쓸 때 정해요. 비운 칸은 기본 AI를 따라요.'],
  ['advanced', '고급', 'pc', '환경 변수와 설정 파일이 정한 값이에요. 여기서는 보기만 해요.'],
  ['preset', 'AI 프리셋', 'project', '이 작품의 AI 호출만 바꿔요. 고르면 바로 작품에 저장해요.'],
  ['writing', '집필 · 검수', 'project', '이 작품에만 적용돼요. 자동 집필도 이 값을 따라요. 바꾸면 바로 저장해요.'],
  ['screen', '화면', 'browser', '이 브라우저에만 기억해요. 다른 기기에는 따라가지 않아요.']];
const setCat = (id) => SET_CATS.find((x) => x[0] === id);

/** 찾기 색인: 줄마다 갈래 · 묶음 · 이름 · 찾을 말. 화면에 그리는 글은 setRowHtml 이 만든다 */
const SET_ROWS = [
  { id: 'provider', cat: 'ai', sec: '기본 AI', label: '기본 AI', words: '생성 방식 백엔드 provider gemini claude 로컬 mock 모델' },
  { id: 'test', cat: 'ai', sec: '기본 AI', label: '연결 확인', words: '연결 테스트 키 확인' },
  { id: 'gemini-auth', cat: 'ai', sec: 'Gemini', label: 'Gemini 연결 방식', words: 'api 키 서비스 계정 vertex google cloud' },
  { id: 'gemini-key', cat: 'ai', sec: 'Gemini', label: 'Gemini API 키', words: '키 key AI Studio AIza' },
  { id: 'vertex-cred', cat: 'ai', sec: 'Gemini', label: '서비스 계정 키 파일', words: 'vertex json 키 파일 경로 google cloud' },
  { id: 'vertex-project', cat: 'ai', sec: 'Gemini', label: 'Google Cloud 프로젝트 ID', words: 'vertex project' },
  { id: 'vertex-location', cat: 'ai', sec: 'Gemini', label: 'Vertex AI 리전', words: 'vertex location global us-central1' },
  { id: 'gemini-model', cat: 'ai', sec: 'Gemini', label: 'Gemini 모델', words: '모델 gemini-4-argon flash' },
  { id: 'claude-login', cat: 'ai', sec: 'Claude', label: 'Claude 구독 로그인', words: 'claude code pro max 로그인 구독' },
  { id: 'anthropic-key', cat: 'ai', sec: 'Claude', label: 'Anthropic API 키', words: '키 key claude console sk-ant' },
  { id: 'claude-model', cat: 'ai', sec: 'Claude', label: 'Claude 모델', words: '모델 opus sonnet haiku' },
  { id: 'claude-bin', cat: 'ai', sec: 'Claude', label: 'claude 실행 파일', words: 'path 경로 bin' },
  { id: 'local-url', cat: 'ai', sec: '로컬 서버', label: '로컬 서버 주소', words: 'ollama llama.cpp vllm lm studio openai url' },
  { id: 'local-model', cat: 'ai', sec: '로컬 서버', label: '로컬 모델 이름', words: '모델 ollama' },
  { id: 'local-key', cat: 'ai', sec: '로컬 서버', label: '로컬 서버 키', words: '키 key' },
  { id: 'preset-pick', cat: 'stages', sec: '프리셋', label: '프리셋으로 채우기', words: '프리셋 묶음 gemini anthropic' },
  { id: 'preset-save', cat: 'stages', sec: '프리셋', label: '내 프리셋으로 저장', words: '프리셋 저장 이름' },
  ...STAGES.map(([s, label, desc]) => ({ id: `stage-${s}`, cat: 'stages', sec: '단계', label, words: `단계 모델 백엔드 ${desc}` })),
  { id: 'env', cat: 'advanced', sec: '고급', label: '환경 변수가 정한 값', words: '환경 변수 CANON_LLM CANON_MODEL GEMINI_API_KEY ANTHROPIC_API_KEY 키' },
  { id: 'sampling', cat: 'advanced', sec: '고급', label: '로컬 샘플링', words: 'temperature top_p min_p 로컬' },
  { id: 'path', cat: 'advanced', sec: '고급', label: '설정 파일', words: '경로 config.json' },
  { id: 'project-preset', cat: 'preset', sec: '이 작품', label: '이 작품의 프리셋', words: '프리셋 작품 모델 단계' },
  { id: 'storyboard', cat: 'writing', sec: '집필', label: '화별 스토리보드', words: '스토리보드 장면 순서 직전 화' },
  { id: 'timeline', cat: 'writing', sec: '집필', label: '작품 속 시간 기록', words: '시간 날짜 기한 타임라인' },
  { id: 'travel', cat: 'writing', sec: '집필', label: '이동 시간 검사', words: '지도 이동 거리 탈것' },
  { id: 'stat-prompt', cat: 'writing', sec: '집필', label: '상태창 수치 넣기', words: '상태창 수치 프롬프트 json lines' },
  { id: 'widen', cat: 'writing', sec: '검수', label: '넓혀 찾기', words: '검수 넓히기 옛 화 장편' },
  { id: 'numbers', cat: 'writing', sec: '보기 · 보관', label: '관계를 숫자로 보기', words: '관계 숫자 말' },
  { id: 'snapshots', cat: 'writing', sec: '보기 · 보관', label: '스냅샷 모두 남기기', words: '스냅샷 되돌리기 장편 보관' },
  { id: 'elsewhere', cat: 'writing', sec: '다른 화면에서 정해요', label: '작품 정보 · 연재 일정 · 자동 집필', words: '제목 장르 화수 분량 연재 일정 자동 집필 멈춤 정책' },
  { id: 'write-mode', cat: 'screen', sec: '집필 화면', label: '집필 생성 방식', words: 'AI로 쓰기 채팅 앱 작업지시서 생성 방식' },
  { id: 'marks', cat: 'screen', sec: '집필 화면', label: '문체 밑줄', words: '밑줄 문체 장치 금지 표현' },
  { id: 'mentions', cat: 'screen', sec: '집필 화면', label: '이름 표시', words: '이름 밑줄 인물 장소' },
  { id: 'copy-fmt', cat: 'screen', sec: '복사', label: '복사 줄바꿈 형식', words: '복사 내보내기 줄바꿈 형식' },
  { id: 'copy-title', cat: 'screen', sec: '복사', label: '복사할 때 제목 줄 넣기', words: '복사 제목 줄' },
];

const setNorm = (s) => String(s || '').toLowerCase().replace(/\s+/g, '');

/** 찾기: 검색어의 낱말이 모두 이름 · 묶음 · 갈래 이름 · 찾을 말 어딘가에 있는 줄. 이름에 든 줄을 앞에 두고, 같으면 목록 순서. 빈 검색어는 빈 목록 */
function settingsMatch(rows, q) {
  const terms = String(q || '').trim().split(/\s+/).filter(Boolean).map(setNorm);
  if (!terms.length) return [];
  const scored = [];
  rows.forEach((r, i) => {
    const label = setNorm(r.label);
    const all = label + setNorm(r.sec) + setNorm((setCat(r.cat) || [])[1]) + setNorm(r.words);
    if (!terms.every((t) => all.includes(t))) return;
    scored.push([terms.every((t) => label.includes(t)) ? 0 : 1, i, r]);
  });
  return scored.sort((a, b) => a[0] - b[0] || a[1] - b[1]).map((x) => x[2]);
}

/** 주소의 설정 갈래: '#/settings' 는 '', '#/settings/ai' 는 'ai', 설정 주소가 아니면 null. 모르는 갈래는 '' */
function settingsCat(hash) {
  const m = String(hash || '').match(/^#\/settings(?:\/([\w-]*))?\/?$/);
  if (!m) return null;
  return setCat(m[1] || '') ? m[1] : '';
}

// ----- 대화상자 상태 -----

const SET = { cat: 'ai', view: 'detail', q: '', note: {}, open: {}, test: null };

/** 줄 아래 한 줄 알림: 저장 중 · 저장했어요 · 오류 */
function setNote(id, text, kind = '') {
  SET.note[id] = { text, kind };
  const el = document.getElementById(`rs-${id}`);
  if (el) { el.textContent = text; el.className = `set-note${kind ? ` ${kind}` : ''}`; }
}

const inProject = () => !!(S.name && S.project && S.route[0] === 'p');
const serialOn = () => inProject() && P().meta.form === 'serial';

/** 지금 쓰는 백엔드: 기본 AI 와 단계마다 실제로 쓰는 백엔드 (서버가 푼 stages 값) */
function usedProviders(c = S.config || {}) {
  if (c.provider === 'mock') return new Set(['mock']);
  return new Set([c.provider, ...Object.values(c.stages || {}).map((x) => x.provider)]);
}

// ----- 줄 그리기 -----

const SW = (key, on, label) => `<button type="button" class="set-sw" role="switch" aria-checked="${on}" aria-label="${esc(label)}" data-action="setToggle" data-arg="${key}"></button>`;
const SET_CHIP = (text, kind = '') => `<span class="chip${kind ? ` ${kind}` : ''}">${esc(text)}</span>`;
const envLine = (src, name) => (src === 'env' ? `환경 변수 ${name}이 정했어요. 바꾸려면 서버를 그 변수 없이 다시 켜세요.` : '');

/** 줄 하나: 이름 · 설명 · 알림 칸(왼쪽)과 고르는 칸(오른쪽). wide 면 좁은 폭에서 칸을 아래로 내린다 */
function setRow(id, name, desc, control, { wide = true } = {}) {
  const n = SET.note[id] || {};
  return `<div class="set-row${wide ? '' : ' tight'}" id="row-${id}"><div class="set-rt"><span class="set-name" id="rn-${id}">${name}</span>${desc ? `<span class="set-desc">${desc}</span>` : ''}<span class="set-note${n.kind ? ` ${n.kind}` : ''}" id="rs-${id}" role="status">${esc(n.text || '')}</span></div><div class="set-rc">${control}</div></div>`;
}

const keyChip = (hint, src) => (src === 'none' ? SET_CHIP('없음', 'bad') : `${SET_CHIP(hint, 'finalized')}`);
const srcWord = (src) => ({ env: '환경 변수', file: '설정 파일', default: '기본값' }[src] || '');

function keyRow(id, kind, name, hint, src, placeholder, help) {
  const locked = src === 'env';
  const clear = src === 'file' && kind !== 'local' ? `<button type="button" class="btn ghost" data-action="setKeyClear" data-arg="${kind}">지우기</button>` : '';
  return setRow(id, `${name} ${hint === null ? '' : keyChip(hint, src)}`,
    `${src !== 'none' && src ? `${srcWord(src)}에 있어요. ` : ''}${help}${locked ? ` ${envLine(src, { gemini: 'GEMINI_API_KEY', anthropic: 'ANTHROPIC_API_KEY', local: 'CANON_LOCAL_KEY' }[kind])}` : ''}`,
    locked ? '' : `<input class="set-inp" id="set-key-${kind}" type="password" autocomplete="off" data-keep aria-labelledby="rn-${id}" placeholder="${esc(src === 'none' ? placeholder : '바꿀 때만 붙여 넣기')}">
      <button type="button" class="btn" data-action="setKeySave" data-arg="${kind}">키 저장</button>${clear}`);
}

/** 글 칸: 칸을 떠나거나 Enter 를 누르면 저장한다 (change). 환경 변수가 정했으면 읽기만 */
function textRow(id, field, name, desc, value, src, envName, { placeholder = '', list = '', mono = false } = {}) {
  const locked = src === 'env';
  return setRow(id, name, `${desc}${locked ? ` ${envLine(src, envName)}` : ''}`,
    `<input class="set-inp${mono ? ' mono' : ''}" type="text" data-setfield="${field}" aria-labelledby="rn-${id}" value="${esc(value || '')}"${placeholder ? ` placeholder="${esc(placeholder)}"` : ''}${list ? ` list="${list}"` : ''}${locked ? ' readonly' : ''}>`);
}

/** 모델 칸 추천 목록: Gemini API 와 로컬 서버 · Claude 에 실제로 있는 모델. 없으면 직접 적는다 */
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

/** 모델 목록 한 줄: 개수, 또는 못 불러온 이유 */
function modelCount(prov) {
  const m = S.models;
  if (!m) return '모델 목록을 불러오는 중이에요.';
  const r = m[prov];
  if (!r) return '';
  if (!r.error) return `쓸 수 있는 모델 ${r.models.length}개`;
  const c = S.config || {};
  return { no_key: c.gemini_auth === 'vertex' ? '서비스 계정을 넣으면 목록을 불러와요' : '키를 저장하면 목록을 불러와요',
    unreachable: '서버가 응답하지 않아요. 주소를 확인하세요' }[r.reason] || `목록을 못 불러왔어요 (${(r.error || '').slice(0, 80)})`;
}

async function loadModelList(force) {
  if (S.models && !force) return;
  S.models = null;
  try {
    S.models = await api('GET', '/config/models');
  } catch (e) {
    S.models = { gemini: { models: [], error: e.message }, local: { models: [], error: e.message } };
  }
  setPaint();
}

function stageHint(s, c) {
  const st = (c.stages || {})[s] || {};
  return st.provider === 'mock' ? '지금 mock' : `지금 ${provName(st.provider)} · ${st.model || ''}`;
}

/** 줄 id 로 그 줄 HTML. 지금 보일 수 없는 줄(작품 밖의 작품 줄, 장편 전용 등)은 빈 글 */
function setRowHtml(id) {
  const c = S.config || {};
  const p = inProject() ? P() : null;
  const used = usedProviders(c);
  switch (id) {
    case 'provider': {
      const locked = c.provider_source === 'env';
      return setRow(id, '기본 AI', `모든 단계가 먼저 이 AI를 써요. 단계마다 바꾸려면 '단계별 모델'에서 정해요.${locked ? ` ${envLine('env', 'CANON_LLM')}` : ''}`,
        `<select class="set-inp" data-setfield="provider" aria-labelledby="rn-${id}"${locked ? ' disabled' : ''}>${PROVIDERS.map(([v, l]) => `<option value="${v}"${c.provider === v ? ' selected' : ''}>${l}</option>`).join('')}</select>`);
    }
    case 'test': {
      const t = SET.test;
      const desc = c.provider === 'mock' ? 'mock은 AI를 부르지 않아 확인할 것이 없어요.'
        : t ? `${fmtDateTime(t.at)} · ${esc(t.message)}` : '쓰는 AI마다 연결을 확인해요. 본문을 만들지 않아요.';
      return setRow(id, '연결 확인', desc, '<button type="button" class="btn" data-action="setTest">연결 확인</button>', { wide: false });
    }
    case 'gemini-auth': {
      const v = c.gemini_auth || 'key';
      const locked = c.gemini_auth_source === 'env';
      return setRow(id, '연결 방식', `AIza… 로 시작하는 키면 API 키, Google Cloud .json 키 파일이면 서비스 계정이에요.${locked ? ` ${envLine('env', 'CANON_GEMINI_AUTH')}` : ''}`,
        `<div class="seg" role="group" aria-labelledby="rn-${id}">${[['key', 'API 키'], ['vertex', '서비스 계정']].map(([k, l]) => `<button type="button" aria-pressed="${v === k}" data-action="setSeg" data-arg="gemini_auth:${k}"${locked ? ' disabled' : ''}>${l}</button>`).join('')}</div>`);
    }
    case 'gemini-key':
      if ((c.gemini_auth || 'key') === 'vertex') return '';
      return keyRow(id, 'gemini', 'API 키', c.key_hint, c.key_source, 'AIza… 로 시작하는 키',
        '<a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">Google AI Studio</a>에서 무료로 받아요. 저장한 키는 다시 보여주지 않아요.');
    case 'vertex-cred': case 'vertex-project': case 'vertex-location':
      return (c.gemini_auth || 'key') === 'vertex' ? vertexRow(id, c) : '';
    case 'gemini-model':
      return textRow(id, 'model', '모델', `목록에서 고르거나 이름을 적어요. 칸을 떠나면 저장해요. ${modelCount('gemini')}`, c.model_setting, c.model_source, 'CANON_MODEL', { list: 'model-options' });
    case 'claude-login':
      return claudeLoginRow(id);
    case 'anthropic-key':
      return keyRow(id, 'anthropic', 'Anthropic API 키', c.anthropic_key_hint, c.anthropic_key_source, 'sk-ant- 로 시작하는 키',
        "'Claude API 키' 방식에서만 써요. <a href=\"https://platform.claude.com/settings/keys\" target=\"_blank\" rel=\"noopener\">Claude Console</a>에서 받아요. 구독 로그인 토큰이 아니에요.");
    case 'claude-model':
      return textRow(id, 'claude_model', 'Claude 모델', '비우면 구독은 Claude Code 기본 모델, API 키는 claude-opus-5-5예요. 구독은 opus · sonnet · haiku도 받아요.',
        c.claude_model, c.claude_model_source, 'CANON_CLAUDE_MODEL', { list: 'model-options', placeholder: 'opus · sonnet · haiku' });
    case 'claude-bin':
      return textRow(id, 'claude_bin', 'claude 실행 파일', 'PATH에서 못 찾을 때만 적어요.', c.claude_bin, c.claude_bin_source, 'CANON_CLAUDE_BIN', { placeholder: '~/.local/bin/claude', mono: true });
    case 'local-url':
      return textRow(id, 'local_url', '서버 주소', `OpenAI 호환 API 주소를 /v1까지 적어요. Ollama :11434/v1 · llama.cpp :8080/v1 · vLLM :8000/v1 · LM Studio :1234/v1.${used.has('local') ? ` ${modelCount('local')}` : ''}`,
        c.local_url, c.local_url_source, 'CANON_LOCAL_URL', { placeholder: 'http://localhost:11434/v1', mono: true });
    case 'local-model':
      return textRow(id, 'local_model', '모델 이름', '비우면 서버에 하나뿐인 모델을 써요.', c.local_model, c.local_model_source, 'CANON_LOCAL_MODEL', { list: 'model-options' });
    case 'local-key':
      return keyRow(id, 'local', '서버 키', null, c.has_local_key ? 'file' : 'none', '서버가 키를 요구할 때만',
        `서버가 키를 요구할 때만 넣어요. 지금 ${c.has_local_key ? '있어요' : '없어요'}.`);
    case 'preset-pick': {
      const list = c.stage_presets || [];
      const cur = presetOf(list, { stages: c.stage_settings, stage_models: c.stage_model_settings });
      const opt = (x) => `<option value="${esc(x.id)}"${cur && cur.id === x.id ? ' selected' : ''}>${esc(x.name)}</option>`;
      const mine = list.filter((x) => !x.builtin);
      return setRow(id, '프리셋으로 채우기', cur ? `지금 칸은 '${esc(cur.name)}' 프리셋과 같아요. 고르면 아래 칸을 바꾸고 바로 저장해요.` : '지금 칸은 어느 프리셋과도 달라요. 고르면 아래 칸을 바꾸고 바로 저장해요.',
        `<select class="set-inp" data-setfield="preset" aria-labelledby="rn-${id}">${cur ? '' : '<option value="" selected>직접 고른 조합</option>'}<optgroup label="기본">${list.filter((x) => x.builtin).map(opt).join('')}</optgroup>${mine.length ? `<optgroup label="내 프리셋">${mine.map(opt).join('')}</optgroup>` : ''}</select>`);
    }
    case 'preset-save': {
      const mine = (c.stage_presets || []).filter((x) => !x.builtin);
      const rows = mine.map((x) => `<li class="set-sub"><span>${esc(x.name)} <span class="set-desc">${esc(STAGES.slice(0, 4).map(([s, l]) => `${l} ${(x.stage_models || {})[s] || provName((x.stages || {})[s] || '') || '기본'}`).join(' · '))}</span></span><button type="button" class="btn ghost" data-action="setPresetDelete" data-arg="${esc(x.id)}" aria-label="${esc(x.name)} 프리셋 지우기">지우기</button></li>`).join('');
      return `${setRow(id, '내 프리셋으로 저장', "지금 단계 칸을 이름 붙여 남겨요. 같은 이름이면 덮어써요. 작품마다 'AI 프리셋'에서 고를 수 있어요.",
        `<input class="set-inp" id="set-preset-name" type="text" data-keep aria-labelledby="rn-${id}" placeholder="예: 검수만 Claude"><button type="button" class="btn" data-action="setPresetSave">저장</button>`)}${rows ? `<ul class="set-subs" aria-label="내 프리셋">${rows}</ul>` : ''}`;
    }
    case 'env': {
      const envs = setEnvList(c);
      return setRow(id, '환경 변수가 정한 값', envs.length ? `서버를 켤 때 넣은 값이 설정 파일보다 앞서요.<ul class="set-env">${envs.map(([k, v]) => `<li><code>${esc(k)}</code> ${esc(v)}</li>`).join('')}</ul>` : '없어요. 모든 값을 여기서 정해요.', '', { wide: false });
    }
    case 'sampling': {
      const sm = c.local_sampling || {};
      return setRow(id, '로컬 샘플링', `로컬 서버로 본문을 쓸 때만 써요. 설정 파일의 local_sampling으로 바꿔요. 지금 ${Object.entries(sm).map(([k, v]) => `${esc(k)} ${v}`).join(' · ') || '기본값'}`, '', { wide: false });
    }
    case 'path':
      return setRow(id, '설정 파일', `<code class="set-path">${esc(c.path || '')}</code> 작품 폴더나 저장소에는 들어가지 않아요.`, '', { wide: false });
    case 'project-preset': {
      if (!p) return '';
      const pre = projectPreset();
      const opts = '<option value="">전체 설정을 따름</option>'
        + (pre && pre.missing ? `<option value="${esc(pre.id)}" selected>지워진 프리셋 (전체 설정을 따름)</option>` : '')
        + (c.stage_presets || []).map((x) => `<option value="${esc(x.id)}"${pre && x.id === pre.id ? ' selected' : ''}>${esc(x.name)}</option>`).join('');
      const uses = c.provider === 'mock' ? '기본 AI가 mock이라 지금은 모든 단계가 mock으로 돌아요.'
        : STAGES.slice(0, 4).map(([s, label]) => `${label} ${esc((projectStage(s) || {}).model || '')}`).join(' · ');
      const gone = pre && pre.missing ? "고른 프리셋이 지워져서 전체 설정을 따르고 있어요. 다른 프리셋을 고르거나 '전체 설정을 따름'으로 바꾸세요. " : '';
      return setRow(id, `'${esc(p.meta.title || S.name)}'의 프리셋`, `${gone}고르면 이 작품의 AI 호출만 그 프리셋의 단계별 AI와 모델을 써요. 지금 ${uses}`,
        `<select class="set-inp" data-setfield="project_preset" aria-labelledby="rn-${id}">${opts}</select>`);
    }
    case 'storyboard':
      return p ? setRow(id, '화별 스토리보드', `쓰기 전에 장면 순서와 이번 화 확정 값(시간 · 상태창 수치 · 차림)을 정해요. 화당 AI 호출이 하나 늘어요.${p.settings.storyboard == null ? ` 정하지 않아 ${p.meta.form === 'serial' ? '장편이라 켜져' : '단편이라 꺼져'} 있어요.` : ''}`,
        SW(id, boardOn(), '화별 스토리보드'), { wide: false }) : '';
    case 'timeline':
      return p ? setRow(id, '작품 속 시간 기록', '끄면 상태 변경안에 시점을 적지 않고, 쓰기 · 검수에 시간 블록을 넣지 않아요.',
        SW(id, !!(p.timeline || {}).enabled, '작품 속 시간 기록'), { wide: false }) : '';
    case 'travel':
      return p ? setRow(id, '이동 시간 검사', `지도 거리와 작품 속 시간으로 너무 빠른 이동을 찾아요. 가장 빠른 탈것은 <a href="${base()}/atlas">지도</a>에서 정해요.`,
        SW(id, !!((p.atlas || {}).travel || {}).enabled, '이동 시간 검사'), { wide: false }) : '';
    case 'stat-prompt': {
      if (!p || !p.states.some((s) => (s.stats || []).length)) return '';
      const v = (p.stat_window || {}).prompt || 'json';
      return setRow(id, '상태창 수치 넣기', '본문 쓰기 프롬프트에 인물 상태창 수치를 넣는 방식이에요. 연구 화면의 상태창 시험에서 셋을 견줘 볼 수 있어요.',
        `<select class="set-inp" data-setfield="stat_prompt" aria-labelledby="rn-${id}">${[['json', '인물 상태에 그대로 (기본)'], ['lines', '이번 화 인물만 줄로'], ['none', '넣지 않음']].map(([k, l]) => `<option value="${k}"${v === k ? ' selected' : ''}>${l}</option>`).join('')}</select>`);
    }
    case 'widen':
      return serialOn() ? setRow(id, `넓혀 찾기 ${SET_CHIP('장편')}`, '검수 뒤 이번 화 진술마다 옛 화를 더 찾아, 처음 검수에 넣지 못한 근거가 나온 진술만 다시 물어요. 검수 호출이 2번 늘어요.',
        SW(id, !!p.settings.check_widen, '넓혀 찾기'), { wide: false }) : '';
    case 'numbers':
      return p ? setRow(id, '관계를 숫자로 보기', '상태 승인 · 인물 화면의 관계를 말 대신 숫자로 보여요.', SW(id, !!p.settings.show_numbers, '관계를 숫자로 보기'), { wide: false }) : '';
    case 'snapshots':
      return serialOn() ? setRow(id, `스냅샷 모두 남기기 ${SET_CHIP('장편')}`, `지금 ${p.snapshots.length}개 · ${p.settings.keep_snapshots ? '모두 남겨요. 끄면 다음 반영 때 0화 · 아크 끝 · 최근 20화만 남기고 지워요.' : '0화 · 아크 끝 · 최근 20화만 남겨요. 지운 화는 되살리지 못해요.'}`,
        SW(id, !!p.settings.keep_snapshots, '스냅샷 모두 남기기'), { wide: false }) : '';
    case 'elsewhere':
      return p ? setRow(id, '다른 화면에서 정해요', '작품 정보(제목 · 장르 · 총 화수 · 화당 분량), 연재 일정, 자동 집필 멈춤 조건은 그 화면에 있어요.',
        `<a class="btn" href="${base()}/setup">설정 도우미</a><a class="btn" href="${base()}">작품 홈</a><a class="btn" href="${base()}/auto">자동 집필</a>`) : '';
    case 'write-mode':
      return setRow(id, '집필 생성 방식', "집필 화면 ⋯ 메뉴의 생성 방식과 같아요. 본문이 없는 화는 늘 AI로 써요.",
        `<div class="seg" role="group" aria-labelledby="rn-${id}">${[['api', 'AI로 쓰기'], ['brief', '채팅 앱 작업지시서']].map(([k, l]) => `<button type="button" aria-pressed="${S.mode === k}" data-action="setSeg" data-arg="mode:${k}">${l}</button>`).join('')}</div>`);
    case 'marks':
      return setRow(id, '문체 밑줄', '집필 화면 본문의 문체 장치 글자와 금지 표현에 밑줄을 그어요.', SW(id, marksOn, '문체 밑줄'), { wide: false });
    case 'mentions':
      return setRow(id, '이름 표시', '집필 화면 본문 속 인물 · 장소 이름에 밑줄을 긋고, 누르면 이름 카드를 보여요.', SW(id, mentionsOn, '이름 표시'), { wide: false });
    case 'copy-fmt': {
      const fmts = S.copyFormats || [];
      if (!fmts.length) return setRow(id, '복사 줄바꿈 형식', '형식 목록을 불러오는 중이에요.', '');
      const cur = fmts.find((f) => f.id === S.copyFmt);
      return setRow(id, '복사 줄바꿈 형식', `집필 화면 '복사'가 붙여 넣을 곳에 맞춰 줄바꿈을 다듬어요.${cur && cur.hint ? ` ${esc(cur.hint)}` : ''}`,
        `<select class="set-inp" data-setfield="copy_fmt" aria-labelledby="rn-${id}">${fmts.map((f) => `<option value="${esc(f.id)}"${f.id === S.copyFmt ? ' selected' : ''}>${esc(f.label)}</option>`).join('')}</select>`);
    }
    case 'copy-title':
      return setRow(id, '복사할 때 제목 줄 넣기', "맨 위에 'N화. 제목' 줄을 넣어요.", SW(id, !!S.copyTitle, '복사할 때 제목 줄 넣기'), { wide: false });
    default:
      return STAGES.some(([s]) => id === `stage-${s}`) ? stageRow(id.slice(6), c) : '';
  }
}

function stageRow(s, c) {
  const id = `stage-${s}`;
  const st = (c.stages || {})[s] || {};
  const [, label, desc] = STAGES.find(([x]) => x === s);
  const envMock = c.provider === 'mock' && c.provider_source === 'env';  // 환경 변수 CANON_LLM=mock 이면 단계 선택과 상관없이 모두 mock
  const lockLLM = envMock || st.env === `CANON_LLM_${s.toUpperCase()}`;
  const lockModel = st.model_env === `CANON_MODEL_${s.toUpperCase()}`;
  const follow = STAGE_PARENT[s] ? `${stageName(STAGE_PARENT[s])}을 따름` : '기본 AI를 따름';
  const notes = [desc, stageHint(s, c), lockLLM && !envMock ? `AI는 환경 변수 CANON_LLM_${s.toUpperCase()}이 정했어요` : '',
    lockModel ? `모델은 환경 변수 CANON_MODEL_${s.toUpperCase()}이 정했어요` : ''].filter(Boolean).map(esc).join(' · ');
  const own = (c.stage_settings || {})[s] || '';
  return setRow(id, label, notes,
    `<select class="set-inp half" data-setstage="${s}" aria-label="${esc(label)} AI"${lockLLM ? ' disabled' : ''}><option value="">${follow}</option>${PROVIDERS.map(([v, l]) => `<option value="${v}"${own === v ? ' selected' : ''}>${l}</option>`).join('')}</select>
     <input class="set-inp half" type="text" data-setstagemodel="${s}" aria-label="${esc(label)} 모델" list="model-options" value="${esc((c.stage_model_settings || {})[s] || '')}" placeholder="모델: ${esc(st.model || '기본')}"${lockModel ? ' readonly' : ''}>`);
}

/** 고급 줄의 환경 변수 목록: [변수 이름, 값 한 줄] (키는 끝 네 글자만) */
function setEnvList(c) {
  const out = [];
  const add = (src, name, val) => { if (src === 'env') out.push([name, val]); };
  add(c.provider_source, 'CANON_LLM', provName(c.provider));
  add(c.model_source, 'CANON_MODEL', c.model_setting);
  add(c.key_source, 'GEMINI_API_KEY', c.key_hint);
  add(c.gemini_auth_source, 'CANON_GEMINI_AUTH', c.gemini_auth);
  add(c.vertex_credentials_source, 'CANON_VERTEX_CREDENTIALS', c.vertex_credentials);
  add(c.vertex_project_source, 'GOOGLE_CLOUD_PROJECT', c.vertex_project);
  add(c.vertex_location_source, 'GOOGLE_CLOUD_LOCATION', c.vertex_location);
  add(c.local_url_source, 'CANON_LOCAL_URL', c.local_url);
  add(c.local_model_source, 'CANON_LOCAL_MODEL', c.local_model);
  add(c.claude_model_source, 'CANON_CLAUDE_MODEL', c.claude_model);
  add(c.claude_bin_source, 'CANON_CLAUDE_BIN', c.claude_bin);
  add(c.anthropic_key_source, 'ANTHROPIC_API_KEY', c.anthropic_key_hint);
  STAGES.forEach(([s]) => {
    const st = (c.stages || {})[s] || {};
    if (st.env === `CANON_LLM_${s.toUpperCase()}`) out.push([st.env, provName(st.provider)]);
    if (st.model_env === `CANON_MODEL_${s.toUpperCase()}`) out.push([st.model_env, st.model]);
  });
  return out;
}

// 쓰지 않는 연결(Gemini · Claude · 로컬 서버)은 한 줄로 접어 둔다. 펼치면 칸이 보인다 (SET.open)
const SET_PROV_SECS = { Gemini: ['gemini'], Claude: ['claude', 'claude-api'], '로컬 서버': ['local'] };

function setSection(sec, rows, searching, title = esc(sec)) {
  const html = rows.map((r) => setRowHtml(r.id)).join('');
  if (!html) return '';
  const provs = SET_PROV_SECS[sec];
  const used = provs && provs.some((x) => usedProviders().has(x));
  const chip = used ? ` ${SET_CHIP('쓰는 중', 'confirmed')}` : '';
  const id = `sec-${setNorm(sec).replace(/[^\w가-힣]/g, '')}`;
  if (provs && !used && !searching && !SET.open[sec]) {
    const why = { Gemini: 'Google AI Studio 키 또는 Google Cloud 서비스 계정', Claude: 'Claude Code 구독 로그인 또는 Anthropic API 키', '로컬 서버': 'Ollama · llama.cpp · vLLM · LM Studio' }[sec];
    return `<section class="set-sec" aria-labelledby="${id}"><h3 id="${id}">${esc(sec)}</h3><div class="set-rows">${setRow(`open-${id}`, `${esc(sec)} ${SET_CHIP('쓰지 않음')}`, why,
      `<button type="button" class="btn" data-action="setOpenSec" data-arg="${esc(sec)}" aria-expanded="false">펼치기</button>`, { wide: false })}</div></section>`;
  }
  return `<section class="set-sec" aria-labelledby="${id}"><h3 id="${id}">${title}${chip}</h3><div class="set-rows">${html}</div></section>`;
}

/** 지금 보일 수 있는 갈래: 작품 갈래는 작품 안에서만 */
const setCats = () => SET_CATS.filter(([, , g]) => g !== 'project' || inProject());
/** 찾기에 쓰는 줄: 지금 보일 수 있는 갈래의 줄 */
const setRowsNow = () => { const ok = new Set(setCats().map(([id]) => id)); return SET_ROWS.filter((r) => ok.has(r.cat)); };

function setBodyHtml() {
  const back = '<button type="button" class="set-back link-btn" data-action="setBack">‹ 설정</button>';
  if (SET.q.trim()) {
    const hits = settingsMatch(setRowsNow(), SET.q);
    const groups = [];
    hits.forEach((r) => {
      const k = `${r.cat}:${r.sec}`;
      let g = groups.find((x) => x.k === k);
      if (!g) groups.push(g = { k, cat: r.cat, sec: r.sec, rows: [] });
      g.rows.push(r);
    });
    const shown = groups.map((g) => {
      const [, cl, gid] = setCat(g.cat);
      const head = [(SET_GROUPS.find(([x]) => x === gid) || [])[1], cl, g.sec !== cl ? g.sec : ''].filter(Boolean).map(esc).join(' · ');
      return setSection(g.sec, g.rows, true, head);
    }).filter(Boolean);
    return `<header class="set-head"><h2 id="set-cat-title">'${esc(SET.q.trim())}' 찾은 설정 ${shown.length ? hits.filter((r) => setRowHtml(r.id)).length : 0}개</h2>
      <p class="set-desc">이름 · 설명 · 찾을 말에서 찾아요. 줄에서 바로 고쳐도 돼요.</p></header>
      ${shown.join('') || '<p class="empty">맞는 설정이 없어요. 다른 말로 찾아 보세요.</p>'}`;
  }
  const [cat, label, gid, desc] = setCat(SET.cat) || SET_CATS[0];
  const rows = SET_ROWS.filter((r) => r.cat === cat);
  const secs = [...new Set(rows.map((r) => r.sec))];
  const groupName = (SET_GROUPS.find(([x]) => x === gid) || [])[1];
  const sub = gid === 'project' ? `${groupName} · ${esc(P().meta.title || S.name)}` : groupName;
  const mock = cat === 'stages' && (S.config || {}).provider === 'mock'
    ? `<div class="note info">기본 AI가 mock이라 지금은 모든 단계가 mock으로 돌아요. 여기서 고른 값은 기본 AI를 바꾸면 써요.</div>` : '';
  return `${back}<header class="set-head"><span class="set-desc">${sub}</span><h2 id="set-cat-title">${esc(label)}</h2><p class="set-desc">${desc}</p></header>
    ${mock}${secs.map((sec) => setSection(sec, rows.filter((r) => r.sec === sec), false)).join('')}`;
}

function setNavHtml() {
  const q = SET.q.trim();
  const hits = q ? settingsMatch(setRowsNow(), q) : [];
  const groups = SET_GROUPS.map(([gid, gname]) => {
    const cats = setCats().filter(([, , g]) => g === gid);
    if (!cats.length) return '';
    const head = gid === 'project' ? `${gname} · ${esc(P().meta.title || S.name)}` : gname;
    return `<div class="set-navh">${head}</div>${cats.map(([id, label]) => {
      const n = hits.filter((r) => r.cat === id).length;
      return `<button type="button" class="set-nav-item" data-action="setGo" data-arg="${id}"${!q && SET.cat === id ? ' aria-current="page"' : ''}><span>${esc(label)}</span>${q && n ? `<span class="set-count">${n}</span>` : ''}<span class="set-chev" aria-hidden="true">›</span></button>`;
    }).join('')}`;
  }).join('');
  return `${groups}<div class="set-out"><a href="#/usage">사용량 · 비용 <span class="set-desc">가격표</span></a><a href="#/styles">문체 라이브러리</a></div>`;
}

/** 대화상자 안을 다시 그린다. 찾기 칸과 저장하지 않은 키 칸(data-keep)의 값, 포커스는 지킨다 */
function setPaint() {
  const dlg = document.getElementById('set-dlg');
  if (!dlg || !dlg.open) return;
  const keep = Object.fromEntries([...dlg.querySelectorAll('[data-keep]')].map((el) => [el.id, el.value]));
  const f = document.activeElement;
  const attr = (k) => f.getAttribute(k) && `[${k}="${CSS.escape(f.getAttribute(k))}"]`;
  // 다시 그린 뒤 같은 칸을 찾을 선택자: id, 아니면 동작 · 칸 이름 속성
  const sel = dlg.contains(f) && f !== dlg ? (f.id ? `#${CSS.escape(f.id)}`
    : ['data-setfield', 'data-setstage', 'data-setstagemodel'].map(attr).find(Boolean)
      || (f.dataset.action ? `[data-action="${f.dataset.action}"]${attr('data-arg') || ''}` : '')) : '';
  const body = dlg.querySelector('#set-body');
  const top = body.scrollTop;
  dlg.querySelector('#set-navlist').innerHTML = setNavHtml();
  body.innerHTML = setBodyHtml() + modelDatalist();
  body.scrollTop = top;
  dlg.querySelector('.set-shell').dataset.view = SET.q.trim() ? 'search' : SET.view;
  Object.entries(keep).forEach(([id, v]) => { const el = document.getElementById(id); if (el) el.value = v; });
  const el = sel && dlg.querySelector(sel);
  if (el && el !== document.activeElement) el.focus({ preventScroll: true });
}

/** 설정 대화상자를 연다. cat 이 없으면 넓은 화면은 AI 연결, 휴대폰 폭은 갈래 목록부터 */
async function openSettings(cat) {
  let dlg = document.getElementById('set-dlg');
  SET.q = '';
  SET.note = {};
  SET.cat = cat && setCats().some(([id]) => id === cat) ? cat : SET.cat && setCats().some(([id]) => id === SET.cat) ? SET.cat : 'ai';
  SET.view = cat || !narrowScreen() ? 'detail' : 'list';
  if (!dlg) {
    dlg = document.createElement('dialog');
    dlg.id = 'set-dlg';
    dlg.className = 'set-dlg';
    dlg.setAttribute('aria-labelledby', 'set-dlg-title');
    dlg.innerHTML = `<div class="set-shell">
        <nav class="set-nav" aria-label="설정 갈래">
          <h2 id="set-dlg-title">설정</h2>
          <input id="set-q" class="set-inp" type="search" placeholder="설정 찾기" aria-label="설정 찾기" autocomplete="off" spellcheck="false">
          <div id="set-navlist"></div>
        </nav>
        <div class="set-main" id="set-body"></div>
      </div>
      <button type="button" class="btn set-close" data-action="setClose">닫기</button>`;
    dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });  // 바깥(배경)을 누르면 닫는다
    dlg.addEventListener('close', () => {
      if (S.route[0] === 'p' && !isTyping()) render();  // 바꾼 작품 설정 · 화면 설정을 뒤 화면에 맞춘다
      // 다시 그리면 연 버튼이 새로 생긴다. 같은 링크를 찾아 포커스를 돌려준다
      const href = setOpener && setOpener.getAttribute && setOpener.getAttribute('href');
      const to = setOpener && setOpener.isConnected ? setOpener : href ? document.querySelector(`a[href="${CSS.escape(href)}"]`) : null;
      if (to) to.focus({ preventScroll: true });
    });
    dlg.querySelector('#set-q').addEventListener('input', (e) => { SET.q = e.target.value; setPaint(); });
    dlg.querySelector('#set-q').addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && SET.q && !e.isComposing) { e.preventDefault(); SET.q = ''; e.target.value = ''; setPaint(); }
    });
    dlg.addEventListener('change', setChange);
    dlg.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && e.target.id && e.target.id.startsWith('set-key-')) { e.preventDefault(); actions.setKeySave(e.target.id.slice(8)); }
      if (e.key === 'Enter' && e.target.id === 'set-preset-name') { e.preventDefault(); actions.setPresetSave(); }
    });
    // 다른 화면으로 가는 링크를 누르면 닫는다 (사용량 · 비용, 지도 등). 새 탭으로 여는 바깥 링크는 그대로
    dlg.addEventListener('click', (e) => { const a = e.target.closest('a[href^="#"]'); if (a) dlg.close(); });
    document.body.appendChild(dlg);
  }
  dlg.querySelector('#set-q').value = '';
  if (!dlg.open) {
    setOpener = document.activeElement;
    dlg.showModal();
  }
  setPaint();
  const cur = dlg.querySelector(SET.view === 'list' ? '.set-nav-item' : '.set-nav-item[aria-current="page"]');
  if (cur) cur.focus({ preventScroll: true });
  // 설정 · 모델 목록 · Claude 로그인 상태 · 복사 형식은 기다리지 않고 받는 대로 다시 그린다
  api('GET', '/config').then((c) => { S.config = c; setPaint(); }).catch((e) => toast(e.message, true));
  loadModelList();
  claudeStatusLoad();
  if (!S.copyFormats) api('GET', '/publish/formats').then((f) => { S.copyFormats = f; setPaint(); }).catch(() => {});
}
let setOpener = null;

// ----- 저장 -----

/** 설정 파일에 칸 하나를 저장한다 (PUT /config 는 보낸 칸만 바꾼다) */
async function setSave(row, body, done = '저장했어요') {
  setNote(row, '저장하는 중…');
  try {
    S.config = await api('PUT', '/config', body);
    SET.note[row] = { text: done, kind: 'ok' };
    api('GET', '/config/health').then((h) => { S.health = h; }).catch(() => {});
  } catch (e) {
    SET.note[row] = { text: e.message, kind: 'err' };
  }
  setPaint();
}

/** 작품 설정 하나를 저장한다. 화면에 저장하지 않은 작품 수정이 있으면 받은 작품으로 덮지 않고 고친 칸만 둔다 */
async function setProjectSave(row, path, body, local) {
  local(P());
  setPaint();
  setNote(row, '저장하는 중…');
  try {
    const p = await api('PUT', `/projects/${enc(S.name)}/${path}`, body);
    if (!S.dirty) S.project = p;
    SET.note[row] = { text: '저장했어요', kind: 'ok' };
  } catch (e) {
    SET.note[row] = { text: e.message, kind: 'err' };
    try { S.project = await api('GET', `/projects/${enc(S.name)}`); } catch { /* 다시 읽지 못하면 다음 이동 때 맞춘다 */ }
  }
  setPaint();
}

const lsKeep = (k, v) => { try { localStorage.setItem(k, v); } catch { /* 이 화면에서만 */ } };

async function setChange(e) {
  const el = e.target;
  const v = (el.value || '').trim();
  const row = (el.closest('.set-row') || { id: '' }).id.replace(/^row-/, '');
  if (el.dataset.setstage) return setSave(row, { stages: { [el.dataset.setstage]: v } });
  if (el.dataset.setstagemodel) return setSave(row, { stage_models: { [el.dataset.setstagemodel]: v } });
  const f = el.dataset.setfield;
  if (!f || el.readOnly) return;
  if (['provider', 'model', 'local_url', 'local_model', 'claude_model', 'claude_bin', 'vertex_credentials', 'vertex_project', 'vertex_location'].includes(f)) {
    if (f === 'vertex_credentials' && v.startsWith('{')) return setNote(row, '키 파일 내용 말고 파일 경로를 적어 주세요', 'err');
    return setSave(row, { [f]: v });
  }
  if (f === 'preset') {
    const c = S.config || {};
    const pre = (c.stage_presets || []).find((x) => x.id === el.value);
    if (!pre) return;
    const kept = STAGES.filter(([s]) => ((c.stages || {})[s] || {}).env === `CANON_LLM_${s.toUpperCase()}`).map(([, l]) => l);
    const all = (m) => Object.fromEntries(STAGES.map(([s]) => [s, (m || {})[s] || '']));
    await setSave(row, { stages: all(pre.stages), stage_models: all(pre.stage_models) },
      `'${pre.name}' 프리셋으로 채웠어요${kept.length ? `. 환경 변수로 정한 ${kept.join(', ')} 칸은 그대로예요` : ''}`);
    const used = new Set(Object.values(pre.stages || {}));
    const c2 = S.config || {};
    if (used.has('claude-api') && c2.anthropic_key_source === 'none') setNote(row, `${SET.note[row].text}. Anthropic API 키를 넣어야 써요`, 'ok');
    else if (used.has('gemini') && c2.key_source === 'none' && c2.gemini_auth !== 'vertex') setNote(row, `${SET.note[row].text}. Gemini API 키를 넣어야 써요`, 'ok');
    return;
  }
  if (f === 'project_preset') {
    if (S.dirty) { setNote(row, '저장하지 않은 작품 수정이 있어요. 작품을 먼저 저장하세요', 'err'); setPaint(); return; }
    return setProjectSave(row, 'model-preset', { preset: el.value }, (p) => { p.settings.model_preset = el.value; });
  }
  if (f === 'stat_prompt') return setProjectSave(row, 'stat-prompt', { mode: el.value }, (p) => { p.stat_window.prompt = el.value; });
  if (f === 'copy_fmt') {
    S.copyFmt = el.value;
    lsKeep('canon.copyFmt', el.value);
    setNote(row, '저장했어요', 'ok');
    setPaint();
  }
}

Object.assign(actions, {
  setGo(cat) {
    SET.cat = cat;
    SET.view = 'detail';
    SET.q = '';
    SET.note = {};
    const q = $('#set-q');
    if (q) q.value = '';
    setPaint();
    const b = $('#set-body');
    if (b) b.scrollTop = 0;
    $('#set-cat-title')?.setAttribute('tabindex', '-1');
    if (narrowScreen()) $('#set-cat-title')?.focus();
  },
  setBack() {
    SET.view = 'list';
    setPaint();
    $(`.set-nav-item[data-arg="${SET.cat}"]`)?.focus();
  },
  setClose() {
    $('#set-dlg')?.close();
  },
  setOpenSec(sec) {
    SET.open[sec] = true;
    setPaint();
  },
  async setTest() {
    setNote('test', '확인하는 중…');
    try {
      const r = await api('POST', '/config/test');
      SET.test = { at: new Date().toISOString(), message: r.message };
      SET.note.test = { text: '', kind: '' };
    } catch (e) {
      SET.test = { at: new Date().toISOString(), message: e.message };
      SET.note.test = { text: '연결하지 못했어요', kind: 'err' };
    }
    setPaint();
  },
  async setKeySave(kind) {
    const el = $(`#set-key-${kind}`);
    const key = el ? el.value.trim() : '';
    const row = { gemini: 'gemini-key', anthropic: 'anthropic-key', local: 'local-key' }[kind];
    if (!key) { setNote(row, '키를 붙여 넣고 저장하세요', 'err'); el?.focus(); return; }
    await setSave(row, { [{ gemini: 'api_key', anthropic: 'anthropic_api_key', local: 'local_key' }[kind]]: key }, '키를 저장했어요');
    if (SET.note[row].kind !== 'ok') return;
    const box = $(`#set-key-${kind}`);
    if (box) box.value = '';
    if (kind !== 'local') loadModelList(true);
    if ((S.config || {}).provider === 'mock') return;
    // 저장한 키로 바로 연결을 확인한다 (본문을 만들지 않는다)
    setNote(row, '키를 저장했어요. 연결을 확인하는 중…', 'ok');
    try {
      const r = await api('POST', '/config/test');
      SET.test = { at: new Date().toISOString(), message: r.message };
      SET.note[row] = { text: `키를 저장했어요. ${r.message}`, kind: 'ok' };
    } catch (e) {
      SET.test = { at: new Date().toISOString(), message: e.message };
      SET.note[row] = { text: `키를 저장했지만 연결하지 못했어요: ${e.message}`, kind: 'err' };
    }
    setPaint();
  },
  async setKeyClear(kind) {
    const name = { gemini: 'Gemini API 키', anthropic: 'Anthropic API 키' }[kind];
    if (!name || !(await askConfirm(`저장된 ${name}를 지울까요?`, { ok: '지우기', danger: true }))) return;
    await setSave(kind === 'gemini' ? 'gemini-key' : 'anthropic-key', kind === 'gemini' ? { clear_key: true } : { clear_anthropic_key: true }, '키를 지웠어요');
  },
  async setSeg(arg) {
    const [k, v] = String(arg).split(':');
    if (k === 'gemini_auth') return setSave('gemini-auth', { gemini_auth: v });
    if (k === 'mode') {
      S.mode = v;
      lsKeep('canon.mode', v);
      setNote('write-mode', '저장했어요', 'ok');
      setPaint();
    }
  },
  async setToggle(key) {
    const p = inProject() ? P() : null;
    const flip = {
      storyboard: () => setProjectSave(key, 'storyboard-setting', { on: !boardOn() }, (x) => { x.settings.storyboard = !boardOn(); }),
      timeline: () => { const on = !p.timeline.enabled; return setProjectSave(key, 'timeline-setting', { on }, (x) => { x.timeline.enabled = on; }); },
      travel: () => {
        const t = p.atlas.travel;
        const on = !t.enabled;
        return setProjectSave(key, 'atlas/travel', { enabled: on, mode: t.mode, kmh: t.kmh, day_km: t.day_km, span_km: p.atlas.span_km }, (x) => { x.atlas.travel.enabled = on; });
      },
      widen: () => { const on = !p.settings.check_widen; return setProjectSave(key, 'check-widen', { on }, (x) => { x.settings.check_widen = on; }); },
      numbers: () => { const on = !p.settings.show_numbers; return setProjectSave(key, 'view', { show_numbers: on }, (x) => { x.settings.show_numbers = on; }); },
      snapshots: () => { const on = !p.settings.keep_snapshots; return setProjectSave(key, 'keep-snapshots', { on }, (x) => { x.settings.keep_snapshots = on; }); },
      marks: () => { marksOn = !marksOn; lsKeep('canon.marks', marksOn ? '1' : '0'); },
      mentions: () => { mentionsOn = !mentionsOn; lsKeep('canon.mentions', mentionsOn ? '1' : '0'); },
      'copy-title': () => { S.copyTitle = !S.copyTitle; lsKeep('canon.copyTitle', S.copyTitle ? '1' : '0'); },
    }[key];
    if (!flip) return;
    if (['marks', 'mentions', 'copy-title'].includes(key)) {
      flip();
      SET.note[key] = { text: '저장했어요', kind: 'ok' };
      setPaint();
      return;
    }
    if (p) await flip();
  },
  async setPresetSave() {
    const el = $('#set-preset-name');
    const name = el ? el.value.trim() : '';
    if (!name) { setNote('preset-save', '프리셋 이름을 적어 주세요', 'err'); el?.focus(); return; }
    const c = S.config || {};
    if ((c.stage_presets || []).some((x) => !x.builtin && x.name === name) && !(await askConfirm(`'${name}' 프리셋을 지금 단계 칸으로 바꿀까요?`, { ok: '바꾸기', danger: true }))) return;
    setNote('preset-save', '저장하는 중…');
    try {
      const r = await api('POST', '/config/presets', { name, stages: c.stage_settings || {}, stage_models: c.stage_model_settings || {} });
      S.config.stage_presets = r.stage_presets;
      SET.note['preset-save'] = { text: `'${name}' 프리셋을 저장했어요`, kind: 'ok' };
      if (el) el.value = '';
    } catch (e) {
      SET.note['preset-save'] = { text: e.message, kind: 'err' };
    }
    setPaint();
  },
  async setPresetDelete(id) {
    const pre = ((S.config || {}).stage_presets || []).find((x) => x.id === String(id));
    if (!pre || pre.builtin || !(await askConfirm(`'${pre.name}' 프리셋을 지울까요? 지금 단계 설정은 그대로예요. 이 프리셋을 고른 작품은 전체 설정을 따라요.`, { ok: '지우기', danger: true }))) return;
    try {
      const r = await api('DELETE', `/config/presets/${encodeURIComponent(pre.id)}`);
      S.config.stage_presets = r.stage_presets;
      SET.note['preset-save'] = { text: `'${pre.name}' 프리셋을 지웠어요`, kind: 'ok' };
    } catch (e) {
      SET.note['preset-save'] = { text: e.message, kind: 'err' };
    }
    setPaint();
  },
});

// 설정 주소로 오는 링크 (#/settings, #/settings/ai): 화면을 옮기지 않고 대화상자를 연다. 주소를 직접 바꾼 경우는 app.js 의 hashchange 가 연다
document.addEventListener('click', (e) => {
  const a = e.target.closest && e.target.closest('a[href^="#/settings"]');
  if (!a || e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey) return;
  const cat = settingsCat(a.getAttribute('href'));
  if (cat === null) return;
  e.preventDefault();
  openSettings(cat);
}, true);

/* 설정 화면의 Gemini 연결 방식: AI Studio API 키 또는 Google Cloud 서비스 계정(Vertex AI). app.js 의 S, $, esc 를 그대로 쓴다.
   서비스 계정은 JSON 키 파일 내용을 받지 않고 이 컴퓨터의 파일 경로만 저장한다. 서버는 canon/settings.py 의 vertex_* 와 llm._vertex_client. */
'use strict';

const VERTEX_SRC = { env: '환경 변수', file: '설정 파일', key_file: '키 파일의 project_id', default: '기본값', none: '없음' };

function geminiAuthSettings(c, keyField) {
  const auth = c.gemini_auth || 'key';
  const env = (s, name) => s === 'env' ? `<div class="small">환경 변수 ${name}에 값이 있어 그 값이 우선해요.</div>` : '';
  const cred = c.vertex_credentials || '';
  const credState = !cred
    ? '<span class="small">비우면 gcloud 기본 자격 증명</span>'
    : c.vertex_credentials_found
      ? '<span class="chip finalized">파일 있음</span>'
      : '<span class="chip" style="background:var(--red-soft);color:var(--red)">파일 없음</span>';
  return `<div class="field"><label for="set-gemini-auth">Gemini 연결 방식</label>
      <select id="set-gemini-auth">
        <option value="key"${auth === 'key' ? ' selected' : ''}>API 키 (Google AI Studio)</option>
        <option value="vertex"${auth === 'vertex' ? ' selected' : ''}>서비스 계정 (Google Cloud Vertex AI)</option>
      </select>${env(c.gemini_auth_source, 'CANON_GEMINI_AUTH 또는 GOOGLE_GENAI_USE_VERTEXAI')}
      <div class="small">Google Cloud에서 받은 <code>.json</code> 키 파일이 있으면 서비스 계정을 고르세요. AIza… 로 시작하는 키라면 API 키예요.</div></div>
    <div id="gemini-key-box"${auth === 'vertex' ? ' hidden' : ''}>${keyField}</div>
    <div id="vertex-box"${auth === 'vertex' ? '' : ' hidden'}>
      <div class="field"><label for="set-vertex-cred">서비스 계정 키 파일 경로 <span class="hint">지금: </span>${credState}</label>
        <input id="set-vertex-cred" type="text" autocomplete="off" value="${esc(cred)}" placeholder="예: ~/.canon/vertex-key.json">
        <div class="small">Canon을 실행하는 컴퓨터의 파일 경로를 적어요. 파일 내용은 붙여 넣지 마세요. 키 파일은 canon 폴더(저장소) 밖, 예를 들어 <code>~/.canon/</code> 에 두고 다른 사람과 나누지 마세요.</div>
        ${env(c.vertex_credentials_source, 'CANON_VERTEX_CREDENTIALS 또는 GOOGLE_APPLICATION_CREDENTIALS')}</div>
      <div class="field"><label for="set-vertex-project">프로젝트 ID <span class="hint">지금: ${c.vertex_project ? esc(VERTEX_SRC[c.vertex_project_source] || '') : '없음'}</span></label>
        <input id="set-vertex-project" type="text" value="${esc(c.vertex_project || '')}" placeholder="비우면 키 파일의 project_id">
        ${env(c.vertex_project_source, 'GOOGLE_CLOUD_PROJECT')}</div>
      <div class="field"><label for="set-vertex-location">리전</label>
        <input id="set-vertex-location" type="text" value="${esc(c.vertex_location || '')}" placeholder="global">
        <div class="small">새 Gemini 모델은 global에 먼저 나와요. 특정 리전(예: us-central1)에서만 쓰는 모델이면 바꾸세요.</div>
        ${env(c.vertex_location_source, 'GOOGLE_CLOUD_LOCATION')}</div>
      <div class="small" style="margin-bottom:12px">Google Cloud 콘솔에서 이 프로젝트의 Vertex AI API를 켜고, 서비스 계정에 'Vertex AI 사용자' 역할을 줘야 해요.
        요금은 그 프로젝트의 결제 계정으로 나가요. Vertex AI는 배치를 Cloud Storage 로만 받아서, 자동 집필의 배치는 일반 호출로 진행해요.</div>
    </div>`;
}

// saveSettings 가 보낼 값에 더한다. 환경 변수나 기본값을 보여 주기만 한 칸은 보내지 않는다 (설정 파일에 굳지 않게)
function geminiAuthBody(c) {
  const body = {};
  [['gemini_auth', '#set-gemini-auth', c.gemini_auth || 'key'], ['vertex_credentials', '#set-vertex-cred', c.vertex_credentials],
    ['vertex_project', '#set-vertex-project', c.vertex_project], ['vertex_location', '#set-vertex-location', c.vertex_location]]
    .forEach(([k, sel, shown]) => {
      const el = $(sel);
      if (!el) return;
      const v = el.value.trim();
      if (['env', 'default', 'key_file', 'none'].includes(c[`${k}_source`]) && v === (shown || '')) return;
      body[k] = v;
    });
  return body;
}

document.addEventListener('change', (e) => {
  if (e.target.id !== 'set-gemini-auth') return;
  const vertex = e.target.value === 'vertex';
  $('#gemini-key-box').hidden = vertex;
  $('#vertex-box').hidden = !vertex;
});

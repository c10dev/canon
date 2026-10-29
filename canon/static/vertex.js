/* 설정 대화상자의 Gemini 서비스 계정(Vertex AI) 줄: 키 파일 경로, 프로젝트 ID, 리전. settings.js 의 setRow · textRow 를 쓴다.
   서비스 계정은 JSON 키 파일 내용을 받지 않고 이 컴퓨터의 파일 경로만 저장한다. 서버는 canon/settings.py 의 vertex_* 와 llm._vertex_client. */
'use strict';

const VERTEX_SRC = { env: '환경 변수', file: '설정 파일', key_file: '키 파일의 project_id', default: '기본값', none: '없음' };

function vertexRow(id, c) {
  if (id === 'vertex-cred') {
    const cred = c.vertex_credentials || '';
    const chip = !cred ? '' : c.vertex_credentials_found ? SET_CHIP('파일 있음', 'finalized') : SET_CHIP('파일 없음', 'bad');
    return textRow(id, 'vertex_credentials', `서비스 계정 키 파일 ${chip}`,
      'Canon을 실행하는 컴퓨터의 .json 키 파일 경로예요. 파일 내용은 붙여 넣지 마세요. 키 파일은 저장소 밖, 예를 들어 ~/.canon/ 에 두세요. 비우면 gcloud 기본 자격 증명을 써요.',
      cred, c.vertex_credentials_source, 'CANON_VERTEX_CREDENTIALS', { placeholder: '~/.canon/vertex-key.json', mono: true });
  }
  if (id === 'vertex-project') {
    return textRow(id, 'vertex_project', '프로젝트 ID',
      `비우면 키 파일의 project_id를 써요. 지금 ${c.vertex_project ? esc(VERTEX_SRC[c.vertex_project_source] || '') : '없음'}. 이 프로젝트의 Vertex AI API를 켜고 서비스 계정에 'Vertex AI 사용자' 역할을 줘야 해요. 요금은 그 프로젝트의 결제 계정으로 나가요.`,
      c.vertex_project, c.vertex_project_source, 'GOOGLE_CLOUD_PROJECT');
  }
  return textRow(id, 'vertex_location', '리전',
    '새 Gemini 모델은 global에 먼저 나와요. 특정 리전에서만 쓰는 모델이면 바꾸세요. Vertex AI는 배치를 Cloud Storage로만 받아서, 자동 집필의 배치는 일반 호출로 진행해요.',
    c.vertex_location, c.vertex_location_source, 'GOOGLE_CLOUD_LOCATION', { placeholder: 'global' });
}

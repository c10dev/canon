/* 작업이 끝나면 알리기. app.js 의 pollJobs 가 작업 목록을 받을 때마다 notifyJobs 를 부른다.
   탭이 뒤에 있거나 창이 다른 창 뒤에 있으면 브라우저 알림(Notification API)을 보내고 탭 제목 앞에 끝난 수를 붙인다.
   탭을 보고 있으면 화면 안 알림 말풍선(toast)이 이미 알리므로 따로 보내지 않는다. 자동 집필의 화별 반영만 말풍선이 없어 여기서 띄운다.
   켜기 · 끄기와 알릴 작업은 이 브라우저(localStorage 'canon.notify')에만 기억한다. 권한은 설정에서 켤 때만 묻는다 (settings.js). */
'use strict';

const NOTIFY_KEY = 'canon.notify';
// 알릴 작업 묶음: [id, 이름, 설명, 기본으로 켬]
const NOTIFY_GROUPS = [
  ['write', '본문 쓰기', 'AI가 화 본문을 다 쓰면', true],
  ['rewrite', '다시 생성', '새 판이나 다듬은 판이 오면', true],
  ['check', '검수', '검수와 고침안 받기가 끝나면', true],
  ['state', '상태 변경안', '상태 변경안이 오면', true],
  ['auto', '자동 집필', '화 하나를 반영하거나 멈추면', true],
  ['other', '그 밖의 AI 작업', '플롯 초안 · 설정 제안 · 대화 등', false],
];
const NOTIFY_KIND = { write: 'write', check: 'check', fixes: 'check', state: 'state', auto: 'auto' };

/** 저장한 값을 읽어 빈 칸을 기본값으로 채운다. 망가진 값은 기본값 */
function notifyPrefs(raw) {
  let v = {};
  try { v = typeof raw === 'string' ? JSON.parse(raw) || {} : raw || {}; } catch { v = {}; }
  const kinds = Object.fromEntries(NOTIFY_GROUPS.map(([id, , , on]) => [id, typeof (v.kinds || {})[id] === 'boolean' ? v.kinds[id] : on]));
  return { on: v.on === true, kinds };
}

/** 작업이 어느 묶음인지. 다시 생성은 같은 'write' 작업이라 결과(candidate)나 이름(새 판 · 서술 다듬기)으로 가른다 */
function notifyGroup(j) {
  if (j.kind === 'write' && ((j.result && j.result.candidate) || /새 판$|서술 다듬기$/.test(j.label || ''))) return 'rewrite';
  return NOTIFY_KIND[j.kind] || 'other';
}

/** 끝난 작업의 알림 글. 화면 말풍선 글(JOB_DONE_MSG)을 쓰고, 본문 쓰기 · 다시 생성은 기다리던 것을 바로 말한다 */
function notifyDoneText(j) {
  if (notifyGroup(j) === 'rewrite') return `${j.ep}화 ${/다듬기/.test(j.label || '') ? '다듬은 판' : '새 판'}이 왔어요. 비교하고 골라 주세요.`;
  if (j.kind === 'write') return `${j.ep}화 본문을 다 썼어요.`;
  const msg = typeof JOB_DONE_MSG !== 'undefined' ? JOB_DONE_MSG[j.kind] : null;
  if (typeof msg === 'function') return msg(j);
  if (msg) return msg;
  return `${j.label}${josa(j.label, '이', '가')} 끝났어요.`;
}

/** 이번에 받은 작업 j 에서 알릴 일. old 는 지난번에 본 같은 작업(처음 보면 없음). 알릴 것이 없으면 null.
    { group, title, body, href, tag, err, toast } — toast 는 탭을 보고 있어도 말풍선을 띄울 일(다른 곳에서 알리지 않는 일) */
function notifyEvent(j, old) {
  if (!j || (typeof QUIET_JOBS !== 'undefined' && QUIET_JOBS.has(j.kind))) return null;
  const href = (typeof JOB_LINK !== 'undefined' && JOB_LINK[j.kind] ? JOB_LINK[j.kind](j) : `#/p/${enc(j.project)}`);
  const base = { group: notifyGroup(j), title: j.project, href, err: false, toast: false };
  const ended = ['done', 'error'].includes(j.status) && (!old || old.status === 'running');
  // 자동 집필이 화 하나를 반영했다 (서버 Job.step_ep). 처음 본 작업은 이미 지난 일이라 알리지 않는다.
  // 마지막 화 반영과 실행 끝이 한 번에 보이면 끝 알림 하나로 알린다 (끝 글이 '모두 반영했어요'를 말한다)
  if (!ended && j.kind === 'auto' && j.status === 'running' && old && j.step_ep != null && j.step_ep !== old.step_ep) {
    return { ...base, body: `자동 집필이 ${j.step_ep}화를 반영했어요.`, tag: `${j.id}:${j.step_ep}`, toast: true };
  }
  if (!ended) return null;
  if (j.status === 'error') return { ...base, body: `${j.label}${josa(j.label, '을', '를')} 끝내지 못했어요: ${j.error}`, tag: j.id, err: true };
  return { ...base, body: notifyDoneText(j), tag: j.id };
}

/** 알릴 길. env: { visible(탭을 보고 있고 창에 포커스), permission('granted' | 'denied' | 'default' | 'unsupported') }.
    돌려주는 목록: 'toast'(화면 말풍선) · 'system'(브라우저 알림) · 'title'(탭 제목에 수 붙이기) */
function notifyWays(ev, pref, env) {
  if (!ev || !pref.on || !pref.kinds[ev.group]) return [];
  if (env.visible) return ev.toast ? ['toast'] : [];
  return env.permission === 'granted' ? ['system', 'title'] : ['title'];
}

/** 탭 제목: 안 본 알림 수를 앞에 붙인다 */
function notifyTitle(title, n) {
  return n > 0 ? `(${n}) ${title}` : title;
}

// ----- 브라우저 쪽 -----

let notifyPref = notifyPrefs((() => { try { return localStorage.getItem(NOTIFY_KEY); } catch { return null; } })());
let notifyUnseen = 0;  // 탭이 뒤에 있는 동안 알린 수 (탭 제목)

/** 이 브라우저가 알림을 보낼 수 있는지: 'granted' · 'denied' · 'default' · 'unsupported'(https 가 아닌 주소 등) */
function notifyPermission() {
  if (typeof window === 'undefined' || !window.Notification || !window.isSecureContext) return 'unsupported';
  return Notification.permission;
}

function notifySave(pref) {
  notifyPref = notifyPrefs(pref);
  try { localStorage.setItem(NOTIFY_KEY, JSON.stringify(notifyPref)); } catch { /* 이 화면에서만 */ }
}

const notifyVisible = () => document.visibilityState === 'visible' && document.hasFocus();

/** 브라우저 알림 하나. 누르면 이 탭으로 와서 결과 화면을 연다 */
function notifySystem(title, body, href, tag) {
  try {
    const n = new Notification(title, { body, tag: tag ? `canon:${tag}` : undefined, lang: 'ko' });
    n.onclick = () => {
      window.focus();
      if (href && location.hash !== href) location.hash = href;
      n.close();
    };
    return true;
  } catch { return false; }  // 일부 휴대폰 브라우저는 페이지에서 바로 만들지 못한다
}

function notifyMarkTitle() {
  if (typeof pageTitle === 'function') document.title = notifyTitle(pageTitle(), notifyUnseen);
}

/** pollJobs 가 받은 작업 목록과 지난번 목록(id → 작업)으로 알린다 */
function notifyJobs(list, before) {
  if (!notifyPref.on) return;
  const env = { visible: notifyVisible(), permission: notifyPermission() };
  for (const j of list) {
    const ev = notifyEvent(j, before.get(j.id));
    const ways = notifyWays(ev, notifyPref, env);
    if (ways.includes('toast')) toast(ev.body, ev.err);
    if (ways.includes('system')) notifySystem(`Canon · ${ev.title}`, ev.body, ev.href, ev.tag);
    if (ways.includes('title')) { notifyUnseen += 1; notifyMarkTitle(); }
  }
}

/** 탭으로 돌아오면 제목의 수를 지운다 */
function notifySeen() {
  if (!notifyUnseen || document.visibilityState !== 'visible') return;
  notifyUnseen = 0;
  notifyMarkTitle();
}
document.addEventListener('visibilitychange', notifySeen);
window.addEventListener('focus', notifySeen);

// 알림을 켜 두면 도는 작업이 없어도 30초마다 작업 목록을 묻는다. 다른 탭 · 기기 · 명령줄에서 시작한 작업도 끝나면 알린다
setInterval(() => {
  if (notifyPref.on && typeof pollJobs === 'function' && !S.jobs.some((j) => j.status === 'running')) pollJobs();
}, 30000);

/** 설정의 '켜기': 권한을 아직 묻지 않았으면 이때 묻는다. 돌려주는 값은 줄 아래 알림 글 */
async function notifyTurnOn() {
  notifySave({ ...notifyPref, on: true });
  let perm = notifyPermission();
  if (perm === 'default') {
    try { perm = await Notification.requestPermission(); } catch { perm = notifyPermission(); }
  }
  if (perm === 'granted') return { text: '켰어요. 탭이 뒤에 있을 때 브라우저 알림을 보내요', kind: 'ok' };
  if (perm === 'denied') return { text: '켰지만 브라우저가 알림을 막았어요. 주소창의 사이트 설정에서 알림을 허용하세요. 그동안 탭 제목에만 표시해요', kind: 'err' };
  if (perm === 'unsupported') return { text: '켰어요. 이 주소에서는 브라우저 알림을 쓸 수 없어 탭 제목에만 표시해요', kind: 'ok' };
  return { text: '켰어요. 알림 허용을 고르지 않아 탭 제목에만 표시해요', kind: 'ok' };
}

/** 설정의 '시험 알림': 탭을 보고 있어도 지금 하나 보낸다 */
async function notifyTest() {
  const perm = notifyPermission();
  if (perm !== 'granted') return { text: perm === 'unsupported' ? '이 주소에서는 브라우저 알림을 쓸 수 없어요' : '먼저 알림을 켜고 브라우저에서 허용하세요', kind: 'err' };
  return notifySystem('Canon', '알림이 이렇게 와요. 작업이 끝나면 다시 알려 드릴게요.', '', 'test')
    ? { text: '시험 알림을 보냈어요. 안 보이면 운영체제의 알림 설정을 확인하세요', kind: 'ok' }
    : { text: '이 브라우저는 페이지에서 알림을 만들지 못해요', kind: 'err' };
}

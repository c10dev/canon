/* 5단계 검수: 한 화의 검수 세션. 회차 띠(누르면 그 회차가 바꾼 지적만, 새 판 구분선) · 처리 상태 거르기,
   왼쪽 지적 목록(탭: 모순 지적 · 초반 점검 · 문체 지표, 심각도 순, 딸린 지적은 부모 아래), 가운데 본문(지적 문장 밑줄, 부분 수정 도구),
   오른쪽 지적 상세(근거 · 심각도 · 처리 상태 · 메모 · 처리 기록). 지적을 누르면 본문이 그 문장으로 옮겨 가고 문장에서 고치는 창이 뜬다
   (passage.js 의 떠 있는 도구, mode 'finding'): AI 고침안 비교와 적용(딸린 곳 포함), 묶음 되돌리기, 이 지적만 다시 검수, 다른 처리 길.
   지적과 회차는 서버 findings.merge 가 만든다 (Episode.findings · rounds). 상태 · 심각도 바꾸기는 PUT …/findings/{id},
   고침안 받기(작업 'fix_one') · 넣기 POST …/fixes/{k}/apply, 되돌리기 POST …/fix-groups/{묶음}/undo,
   이 지적만 다시 검수(작업 'recheck_one', 장면 연출 규칙 · 정규식 지적은 AI 없이 POST …/findings/{id}/recheck),
   고친 곳만 다시 보기(작업 'recheck', 지난 검수 뒤 고침안을 넣은 열린 지적이 있을 때 머리의 주 버튼, home.js 의 fixRecheckTargets),
   한꺼번에: 열린 지적 모두 고침안 받기(작업 'fixes') → 고침안 한꺼번에 검토(지적마다 고르고 고른 것만 POST …/fixes/apply),
   문체 지표는 GET …/style. app.js 의 S, P, actions, api, render, run, home.js 의 checkState, write.js 의 epNav · nextStepBtn,
   marks.js 의 draftBox · readHtml, passage.js 의 textNow · editableEp · passageNotes · editTime · wordDiff · flushText · focusText · showTool,
   opening.js 의 openingChecks 를 그대로 쓴다. */
'use strict';

Object.assign(S, {
  chkSel: {},          // 화 → 고른 지적 id
  chkFilter: 'open',   // 지적 목록 거르기: open · fixed · kept · wrong · all
  chkSev: '',          // 지적 목록 더 거르기: 심각도(crit · mid · low). 비면 모두
  chkType: '',         // 지적 목록 더 거르기: 종류(ConsistencyIssue.type). 비면 모두
  chkChanged: false,   // 지적 목록 더 거르기: 문장이 바뀐(본문에 인용이 없는) 열린 지적만
  chkRound: {},        // 화 → 고른 회차 번호 (그 회차가 바꾼 지적만 본다). 비면 처리 상태로 거른다
  chkTab: 'issues',    // 왼쪽 칸 탭: issues · opening · style
  chkStyle: {},        // 화 → 문체 지표 { metrics, warnings } 또는 { error }
  chkNotes: {},        // '화:id' → 저장 전 메모 초안 (저장한 메모와 다를 때만 둔다)
  chkNotesOf: '',      // chkNotes 가 어느 작품의 초안인지
  fixSkip: {},         // '화:id:고침안 번호' → 빼고 넣을 딸린 곳 번호 목록
  fbOpen: 0,           // 고침안 한꺼번에 검토를 연 화 (0 이면 닫힘)
  fbOn: {},            // '화:id' → 작가가 넣기로 고른 지적 (보이는 고침안을 넣는다)
  fbOpt: {},           // '화:id' → 보이는 고침안 번호
  fbNote: {},          // '화:id' → 고침안을 받지 못했거나 넣지 못한 까닭
});

JOB_DONE_MSG.fixes = (j) => {
  const r = j.result || {};
  const failed = (r.failed || []).length;
  return `${j.ep}화 지적 ${r.done || 0}개의 고침안이 도착했어요${failed ? ` (${failed}개는 받지 못했어요)` : ''}. 검수 화면의 '고침안 한꺼번에 검토'에서 넣을 것만 고르세요.`;
};
JOB_PAGES.fixes = ['check'];
JOB_LINK.fixes = (j) => `#/p/${enc(j.project)}/check/${j.ep}`;
JOB_DONE_MSG.recheck = (j) => {
  const r = j.result || {};
  const miss = (r.missing || []).length;
  return `${j.ep}화 고친 곳만 다시 봤어요: 지적 ${r.asked || 0}개 중 ${r.resolved || 0}개가 풀렸어요${r.open ? `, ${r.open}개는 아직 어긋나요` : ''}${r.added ? `, 고친 문장 때문에 새로 어긋난 곳 ${r.added}개` : ''}${miss ? ` (${miss}개는 AI가 답하지 않았어요)` : ''}`;
};
JOB_PAGES.recheck = ['check'];
JOB_LINK.recheck = (j) => `#/p/${enc(j.project)}/check/${j.ep}`;

// 지적 하나의 AI 고침안 받기 · 이 지적만 다시 검수는 백그라운드 작업으로 돈다 (web._job_finding_ai). 기다리는 동안 다른 지적을 읽고 고칠 수 있다.
// 대상은 지적 id 이고 화마다 새로 매기므로 버튼 잠금(JOB_BTNS)에 화를 함께 준다. 같은 화의 검수 · 고침안 한꺼번에 받기 · 고친 곳만 다시 보기와는
// 함께 돌지 않는다 (web._finding_clash). 장면 연출 규칙 · 정규식 지적의 '판정 다시 보기'는 AI를 부르지 않아 그대로 바로 한다
JOB_PAGES.fix_one = ['check'];
JOB_PAGES.recheck_one = ['check'];
JOB_LINK.fix_one = (j) => `#/p/${enc(j.project)}/check/${j.ep}`;
JOB_LINK.recheck_one = (j) => `#/p/${enc(j.project)}/check/${j.ep}`;
JOB_DONE_MSG.fix_one = (j) => `${j.ep}화 지적 ${j.target}의 고침안 ${(j.result || {}).fixes || 0}개가 도착했어요.`;
JOB_DONE_MSG.recheck_one = (j) => `${j.ep}화 지적 ${j.target}${josa(j.target, '을', '를')} 다시 검수했어요.`;
// 버튼은 jobBtn 으로 그린다 (fixPanel · recheckBtn). 고치는 창(#sel-tool)이 #app 밖이라 lockJobBtns(JOB_BTNS)가 닿지 않는다
/** 끝난 지적 작업(fix_one · recheck_one)의 지적을 지금 보고 있다: 그 화 검수 칸에서 그 지적을 골라 두었다 */
const onFinding = (n, fid) => S.route[2] === 'check' && Number(S.route[3]) === n && S.chkSel[n] === fid;
/** 지적 작업의 알림 버튼 '보기': 그 화 검수 칸에서 그 지적을 고르고 고치는 창을 연다 */
const findingGo = (n, fid) => ({ label: '보기', run: () => {
  S.chkSel[n] = fid;
  const there = S.route[2] === 'check' && Number(S.route[3]) === n;
  if (ep(n)) afterFix(n, fid, S.project);
  if (there) render(); else location.hash = `${base()}/check/${n}`;
} });
/** 고침안이 왔다: 작가가 그 지적을 보고 있고 칸을 고치는 중이 아니면 옛 동작처럼 고치는 창을 그 지적으로 연다. 아니면 알림의 '보기'로 연다 */
JOB_RESULT.fix_one = (j) => {
  const n = j.ep;
  const fid = j.target;
  if (!ep(n) || !(ep(n).findings || []).some((f) => f.id === fid)) return null;
  if (onFinding(n, fid) && !isTyping()) { afterFix(n, fid, S.project); return null; }
  return { actions: [findingGo(n, fid)] };
};
/** 이 지적만 다시 검수 결과: 옛 동작과 같은 알림. 새로 생긴 딸린 지적이 있고 작가가 그 지적을 보고 있으면 고치는 창을 딸린 지적으로 옮긴다 */
JOB_RESULT.recheck_one = (j) => {
  const n = j.ep;
  const r = j.result || {};
  const f = ep(n) && (ep(n).findings || []).find((x) => x.id === j.target);
  if (!f) return null;
  const kids = (r.kids || []).filter((id) => (ep(n).findings || []).some((x) => x.id === id));
  const head = `${n}화 지적 ${f.id}: `;
  if (kids.length) {
    if (onFinding(n, f.id) && !isTyping()) {
      S.chkSel[n] = kids[0];
      S.chkFilter = 'open';
      afterFix(n, kids[0], S.project);  // 고치는 창을 새로 생긴 딸린 지적으로 옮긴다
      return { msg: `${head}${r.resolved ? '풀렸어요. ' : ''}고친 문장 때문에 새로 어긋난 곳 ${kids.length}개를 딸린 지적으로 더했어요` };
    }
    return { msg: `${head}${r.resolved ? '풀렸어요. ' : ''}고친 문장 때문에 새로 어긋난 곳 ${kids.length}개를 딸린 지적으로 더했어요`, actions: [findingGo(n, kids[0])] };
  }
  if (r.resolved) return { msg: `${head}풀렸어요. 고침으로 닫았어요` };
  // 다시 검수의 보통 결과라 오류로 띄우지 않는다. 그 지적의 처리 기록으로 가는 버튼을 붙인다
  const log = onFinding(n, f.id) ? { label: '처리 기록 보기', run: showFindingLog } : findingGo(n, f.id);
  return { msg: `${head}아직 어긋나요. 처리 기록에 까닭을 남겼어요`, actions: [log] };
};

// 서버 schema.FINDING_STATUS · SEVERITY 와 같은 이름
const FINDING_STATUS = { open: '열림', fixed: '고침', kept: '그대로 둠', wrong: '잘못 짚음' };
const SEVERITY = { crit: '치명', mid: '보통', low: '사소' };
const SEV_RANK = { crit: 0, mid: 1, low: 2 };
// 칩 색: 열린 지적만 '사람이 볼 것'(.chip.warn). 화 상태 칩(draft · confirmed · written · finalized)은 빌려 쓰지 않는다 (디자인 시스템 Chip)
const FINDING_CHIP = { open: 'warn', fixed: '', kept: '', wrong: '' };
const SEV_CHIP = { crit: 'crit', mid: 'warn', low: '' };
const FINDING_FLAG = { changed: '문장 바뀜', miss: '이번 회차에서 안 짚음', gone: '다시 검수에서 사라짐', again: '다시 나옴 · 결정 그대로', one: '이 지적만 다시 검수로 닫음' };
const ROUND_CHANGE = { new: '새로 나옴', again: '다시 나옴', gone: '사라짐' };

/** 지적 옆 표시. findings.merge · settle 이 남긴 칸(first · last · closed_by)과 지금 본문(저장 전 글 포함)으로 센다. */
/** 장면 연출 규칙 판정(origin rule)이나 정규식 경고 규칙(origin regex, regexrules.hits)이 낸 지적의 표시 (schema.ConsistencyIssue.origin).
    정규식 지적의 description 은 규칙 이름이고, 이름이 없으면 서버가 '정규식 규칙에 걸렸어요' 를 넣는다 */
const REGEX_NONAME = '정규식 규칙에 걸렸어요';
const regexName = (f) => (f.description && f.description !== REGEX_NONAME ? f.description : '');
const ruleChip = (f) => (f.origin === 'rule' ? '<span class="chip" title="장면 연출 규칙 판정이 짚었어요 (AI 검수가 아니에요)">규칙</span>'
  : f.origin === 'regex' ? `<span class="chip" title="작품에 켠 정규식 경고 규칙이 짚었어요 (AI 검수가 아니에요)">정규식${regexName(f) ? ` · ${esc(regexName(f))}` : ''}</span>` : '');
/** 지적 목록 줄의 근거 글: 정규식 지적은 근거 쪽이 없다 */
const srcLine = (n, f) => (f.origin === 'regex' ? '정규식 규칙' : `근거 · ${srcLabel(n, f)}`);
/** '판정 다시 보기'(AI 없이 다시 판정) 버튼 글과 풀이. 정규식 지적은 지금 본문에 그 규칙만 다시 건다 */
const RECHECK_LOCAL = { rule: ['판정 다시 보기', 'AI를 부르지 않고 지금 본문 장면으로 판정만 다시 해요'], regex: ['판정 다시 보기', 'AI를 부르지 않고 지금 본문에 이 경고 규칙만 다시 걸어 봐요'] };
const recheckBtn = (f, busy = false) => {
  const [label, why] = RECHECK_LOCAL[f.origin] || ['이 지적만 다시 검수', ''];
  // AI 검수 지적은 작업 recheck_one 이 도는 동안 '만드는 중'으로 잠근다. 고치는 창(#sel-tool)은 #app 밖이라 lockJobBtns 가 닿지 않아 여기서 그린다
  const b = why ? { label, attr: '' } : jobBtn('recheck_one', chkEp(), label, S.name, f.id);
  return `<button type="button" class="btn small" data-action="chkRecheck" data-arg="${esc(f.id)}"${why ? ` title="${why}"` : ''}${b.attr}${busy ? ' disabled' : ''}>${b.label}</button>`;
};

/** 규칙 지적의 '장면 연출에서 보기': 그 사건 본문 장면의 그 박자로 (stage.js 의 S.stgJump). */
function stageLink(n, f) {
  if (f.origin !== 'rule' || f.stage_event == null || f.stage_event < 0) return '';
  const ev = f.stage_event + 1;
  return `<div class="row"><a class="btn small ghost" href="${base()}/stage/${n}/${ev}" data-action="stgGo" data-arg="${n}:${ev}:${f.stage_beat || 0}">장면 연출에서 보기 · 사건 ${ev}${f.stage_beat ? ` · ${f.stage_beat}박자` : ''}</a></div>`;
}

/** 검수 머리의 '검수 옵션' 메뉴: 넓혀 찾기(장편) · 동선 따로 보기 · 연출 함께 뽑기를 체크 줄로 모은다.
    머리 줄에는 지금 할 일(검수 · 상태 승인)만 남기고, 켜고 끄는 설명은 title 대신 줄 아래 글로 보인다.
    체크는 같은 이름의 토글 동작을 부른다(data-check-opt). 고른 뒤에도 메뉴는 열려 있다 (디자인 시스템 Menu) */
function checkOptsMenu() {
  const s = P().settings;
  const opts = [
    serial() && ['toggleWiden', !!s.check_widen, '넓혀 찾기', '검수 뒤 이번 화 진술마다 옛 화를 더 찾아, 처음 검수에 넣지 못한 근거가 나온 진술만 다시 물어요. 검수 호출이 2번 늘어요'],
    ['toggleCheckAfterWrite', !!s.check_after_write, '쓴 뒤 바로 검수', '집필 화면에서 본문을 처음 쓰면 같은 작업에서 바로 검수해요. 본문은 먼저 받아 읽고 고칠 수 있고, 검수하는 동안 고친 곳은 검수 뒤 고침으로 남아요. 새 판(다시 생성)은 검수하지 않고, 화마다 검수 호출이 늘어요'],
    ['toggleCheckScope', s.check_scope !== false, '바뀐 곳만 새로 짚기', '다시 검수할 때 지난 검수 뒤 고친 문단과 앞뒤 문단에서 나온 새 지적만 넣어요. 바뀌지 않은 문단은 지난 검수가 이미 봐서, 고칠 때마다 새 지적이 또 나오는 일을 줄여요. 치명 지적은 어디서 나와도 넣어요'],
    ['toggleCheckMotion', s.check_motion !== false, '동선 따로 보기', '이번 화 본문만 넣고 인물의 자리 · 향한 쪽 · 손 · 물건이 어긋난 곳을 한 번 더 찾아요. 본 검수와 동시에 불러 기다리는 시간은 그대로고, 검수 호출이 1번 늘어요'],
    ['toggleStageExtract', s.stage_extract !== false, '연출 함께 뽑기', '계획 장면이 있는 사건마다 본문에서 장면 연출을 뽑아 규칙으로 판정해요. 본문이 바뀐 사건만 뽑고, 그런 사건마다 검수 호출이 1번 늘어요'],
  ].filter(Boolean);
  const on = opts.filter((o) => o[1]).length;
  const body = () => `<div class="pop-sec"><div class="pop-legend">검수할 때 함께 할 것 · 작품 설정이라 자동 집필도 따라요</div>
    ${opts.map(([act, v, name, desc]) => `<label class="pop-check"><input type="checkbox" id="co-${act}" data-check-opt="${act}"${v ? ' checked' : ''}><span>${name}<span class="small">${desc}</span></span></label>`).join('')}</div>`;
  return menuBtn('check-opts', `검수 옵션 ${on}/${opts.length} <span aria-hidden="true">▾</span>`, body, { title: '검수할 때 함께 할 것을 켜고 꺼요' });
}

// 버리고 이동을 고르면 메모 초안도 버린다 (app.js onEditDiscard)
if (typeof onEditDiscard === 'function') onEditDiscard('chkNote', () => { S.chkNotes = {}; });

/** 메모 초안이 하나라도 남았는지 S.editDrafts.chkNote 에 알린다 */
function syncNoteDraft() {
  S.editDrafts = S.editDrafts || {};
  if (Object.keys(S.chkNotes).length) S.editDrafts.chkNote = true;
  else delete S.editDrafts.chkNote;
}

/** 메모 칸 입력: 지적마다 초안을 따로 두어 다른 지적을 골라도 잃지 않는다. 저장한 메모와 같아지면 초안을 지운다 */
document.addEventListener('input', (e) => {
  const key = e.target && e.target.dataset && e.target.dataset.chkNote;
  if (!key) return;
  const [n, id] = key.split(':');
  const f = ((ep(+n) || {}).findings || []).find((x) => x.id === id);
  if (f && e.target.value === (f.note || '')) delete S.chkNotes[key];
  else S.chkNotes[key] = e.target.value;
  syncNoteDraft();
});

document.addEventListener('change', (e) => {
  const act = e.target && e.target.dataset && e.target.dataset.checkOpt;
  if (act && actions[act]) actions[act]();
});

function findingFlag(e, f, text) {
  const rounds = e.rounds || [];
  const last = rounds.length ? rounds[rounds.length - 1].no : f.last;
  const quote = (f.current_quote || '').trim();
  if (f.status === 'open') {
    if (quote && !text.includes(quote)) return 'changed';
    return f.last < last && !f.parent ? 'miss' : '';
  }
  if (f.status === 'fixed') return f.closed_by === 'recheck' ? 'gone' : f.closed_by === 'one' ? 'one' : '';
  return f.last === last && f.first < last ? 'again' : '';
}

const findingNum = (f) => Number(String(f.id).slice(1)) || 0;

/** 목록 순서: 심각도(치명 → 보통 → 사소) → 번호. 딸린 지적은 목록에 부모가 있으면 부모 바로 아래에 둔다. */
function findingOrder(list) {
  const ids = new Set(list.map((f) => f.id));
  const rank = (f) => SEV_RANK[f.severity] ?? 1;
  const top = list.filter((f) => !f.parent || !ids.has(f.parent)).sort((a, b) => rank(a) - rank(b) || findingNum(a) - findingNum(b));
  const out = [];
  const walk = (f) => {
    out.push(f);
    list.filter((c) => c.parent === f.id).sort((a, b) => findingNum(a) - findingNum(b)).forEach(walk);
  };
  top.forEach(walk);
  return out;
}

/** 회차 no 가 바꾼 지적: id → 'new' | 'again' | 'gone' (CheckRound.added_ids · again_ids · gone_ids). id 를 남기지 않은 옛 회차는 빈 것. */
function roundChanges(e, no) {
  const r = (e.rounds || []).find((x) => x.no === no);
  const out = {};
  if (!r) return out;
  (r.added_ids || []).forEach((id) => { out[id] = 'new'; });
  (r.again_ids || []).forEach((id) => { out[id] = 'again'; });
  (r.gone_ids || []).forEach((id) => { out[id] = 'gone'; });
  return out;
}

/** 한글 3글자 조각 (서버 context.grams 와 같다: 띄어쓰기 · 문장 부호를 무시한다). */
function hangulGrams(s) {
  const h = (s.match(/[가-힣]+/g) || []).join('');
  const g = new Set();
  for (let i = 0; i + 3 <= h.length; i++) g.add(h.slice(i, i + 3));
  return g;
}

/** 지적 문장을 그대로 찾을 수 없을 때 본문에서 가장 비슷한 문장. 짧은 쪽 조각의 절반 이상이 겹칠 때만 (findings.same_quote 와 같은 기준).
    { a, b } 또는 null. */
function nearQuote(text, quote) {
  const gq = hangulGrams(quote);
  if (!gq.size) return null;
  let best = null;
  const re = /[^.!?\n]+[.!?…]*["”’]?/g;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    const s = m[0];
    const gs = hangulGrams(s);
    const small = Math.min(gs.size, gq.size);
    if (!small) continue;
    let hit = 0;
    gs.forEach((x) => { if (gq.has(x)) hit++; });
    const score = hit / small;
    if (score >= 0.5 && (!best || score > best.score)) {
      const lead = s.length - s.trimStart().length;
      best = { a: m.index + lead, b: m.index + s.trimEnd().length, score };
    }
  }
  return best && { a: best.a, b: best.b };
}

/** 본문에서 지적 문장이 있는 곳: 그대로 있으면 그 자리(near false), 바뀌었으면 비슷한 문장(near true), 없으면 null. */
function findingSpot(text, f) {
  const q = (f.current_quote || '').trim();
  if (!q) return null;
  const a = text.indexOf(q);
  if (a !== -1) return { a, b: a + q.length, near: false };
  const x = nearQuote(text, q);
  return x && { ...x, near: true };
}

/** 본문 밑줄 칠 지적 문장: 열린 지적과 고른 지적. 문장마다 처음 나온 곳 하나. 고른 지적의 문장이 바뀌었으면 비슷한 문장에 친다.
    kind 는 mark 의 class 가 된다. */
function findingMarks(e, text, sel) {
  const out = [];
  for (const f of e.findings || []) {
    const q = (f.current_quote || '').trim();
    if (!q || (f.status !== 'open' && f.id !== sel)) continue;
    const spot = f.id === sel ? findingSpot(text, f) : text.indexOf(q) === -1 ? null : { a: text.indexOf(q), b: text.indexOf(q) + q.length };
    if (spot) out.push({ a: spot.a, b: spot.b, kind: f.id === sel ? `issue sel${spot.near ? ' near' : ''}` : 'issue', key: `i:${f.id}`, title: `${SEVERITY[f.severity] || '보통'} · ${f.type} · ${f.description}` });
  }
  return out;
}

/** 고침안을 지금 본문에 넣을 수 있는지: 고칠 문장(지적 문장과 고른 딸린 곳) 가운데 본문에 없는 것. 비면 넣을 수 있다. */
function fixMissing(text, f, opt, skip) {
  const quotes = [f.current_quote, ...(opt.extra || []).filter((_, i) => !(skip || []).includes(i)).map((x) => x.quote)];
  return quotes.map((q) => (q || '').trim()).filter((q) => q && !text.includes(q));
}

/** 이 지적의 고침안 묶음이 아직 본문에 들어가 있는지 (되돌리지 않은 수정이 하나라도 있는지). */
function fixApplied(e, f) {
  return !!f.fix_group && (e.edits || []).some((x) => x.group === f.fix_group && !x.undone);
}

/** 지금 고른 지적: 고른 적이 있으면 그것, 없으면 목록 순서로 첫 열린 지적, 그도 없으면 첫 지적. */
function chkSelected(n) {
  const e = ep(n);
  const list = findingOrder((e && e.findings) || []);
  const id = S.chkSel[n];
  if (id && list.some((f) => f.id === id)) return id;
  return (list.find((f) => f.status === 'open') || list[0] || {}).id || '';
}

/** marks.js 가 본문 밑줄에 더한다. 검수 화면에서만. */
function findingRanges(n, text) {
  if (S.route[2] !== 'check' || !ep(n)) return [];
  return findingMarks(ep(n), text, chkSelected(n));
}

const srcLabel = (n, f) => (!f.source_episode ? '설정 · 확정 사실' : f.source_episode === n ? '이번 화 앞 문장' : `${f.source_episode}화`);
const findingShort = (f) => (f.description.length > 40 ? `${f.description.slice(0, 40)}…` : f.description);

async function checkLoad(n) {
  const e = ep(n);
  if (!e || !e.text) return;
  if (!S.presets) S.presets = await api('GET', '/passage/presets').catch(() => []);  // 부분 수정 도구의 빠른 요청
  S.chkStyle[n] = await api('GET', `/projects/${enc(S.name)}/episodes/${n}/style`).catch((err) => ({ error: err.message }));
}

/** 서버가 돌려준 작품에서 이 화의 검수 칸만 가져온다. 화면에서 고치던 다른 칸은 그대로 둔다. */
function takeCheck(n, pj) {
  const src = pj.episodes.find((x) => x.plot.number === n);
  if (src) Object.assign(ep(n), { findings: src.findings, rounds: src.rounds, issues: src.issues, checked_at: src.checked_at });
}

function chkStrip(n, e, st, fast = []) {
  const rounds = e.rounds || [];
  if (!rounds.length) return '';
  const last = rounds[rounds.length - 1];
  const picked = S.chkRound[n] || 0;
  const count = (k) => (k === 'all' ? e.findings.length : e.findings.filter((f) => f.status === k).length);
  const filters = [['open', '열림'], ['fixed', '고침'], ['kept', '그대로 둠'], ['wrong', '잘못 짚음'], ['all', '모두']]
    .map(([k, l]) => `<button type="button" aria-pressed="${!picked && S.chkFilter === k}" data-action="chkFilter" data-arg="${k}">${l} ${count(k)}</button>`).join('');
  const from = { chat: ' · 채팅 앱', auto: ' · 자동 집필' };
  const chips = rounds.slice(-4).map((r) => {
    const gone = (r.gone_ids || []).length;
    const again = (r.again_ids || []).length;
    const label = `${r.no}회차${r.at ? ` · ${editTime(r.at)}` : ''} · 짚은 ${r.found}${r.no > 1 ? ` · 새로 ${r.added}` : ''}${gone ? ` · 사라짐 ${gone}` : ''}${r.no > 1 && again ? ` · 다시 ${again}` : ''}${r.kept_again ? ` · 결정 그대로 ${r.kept_again}` : ''}${from[r.source] || ''}${r.widen ? ' · 넓혀 찾기' : ''}${r.scoped ? ' · 바뀐 곳만' : ''}`;
    return `<button type="button" class="chk-round${r === last ? ' last' : ''}" aria-pressed="${picked === r.no}" data-action="chkRound" data-arg="${r.no}">${label}</button>${r.superseded ? '<span class="chk-break">새 판</span>' : ''}`;
  }).join('');
  const fresh = last.superseded && !e.checked_at;
  const others = fast.length ? chkOtherEdits(e, fast) : 0;
  const scopeOn = P().settings.check_scope !== false;
  const scopeNote = scopeOn ? ' 다시 검수는 바뀐 문단에서 나온 새 지적만 넣어요.' : '';
  return `<div class="chk-strip"><span class="small">회차</span><div class="row" style="gap:6px">${chips}</div>
      <span class="small chk-strip-hint">회차를 누르면 그 회차에 바뀐 지적만 봐요</span>
      <div class="seg chk-filters" role="group" aria-label="처리 상태로 거르기">${filters}</div></div>
    ${fresh ? `<div class="note">${last.no}회차 뒤에 본문을 새 판으로 바꿨어요. 그대로 둠 · 잘못 짚음으로 정한 지적만 남겼어요. 새 판을 검수하세요.</div>`
    : st.stale && fast.length && others ? `<div class="note warn">${last.no}회차 뒤에 고침안을 넣고 직접 고친 곳도 ${others}곳 있어요. '고친 곳만 다시 보기'로 고침안을 넣은 지적 ${fast.length}개를 먼저 닫고, 직접 고친 곳은 그 뒤 다시 검수로 보세요.${scopeNote}</div>`
    : st.stale && fast.length ? `<div class="note warn">${last.no}회차 뒤에 고침안만 넣었어요. '고친 곳만 다시 보기'는 고친 문장과 앞뒤 문단만 보내 지적 ${fast.length}개를 한 번에 다시 봐요. 고친 곳이 멀리 떨어진 문장과 어긋나는지까지 보려면 다시 검수하세요.</div>`
    : st.stale ? `<div class="note warn">${last.no}회차 뒤에 본문을 고쳤어요. 고친 문장의 지적은 '문장 바뀜'으로 보여요. 고친 곳이 다른 곳과 어긋나지 않는지 보려면 다시 검수하세요.${scopeNote}</div>`
    : last.scoped && last.outside ? `<div class="note">${last.no}회차는 바뀐 문단만 새로 짚었어요. 바뀌지 않은 문단에서 새로 나온 지적 ${last.outside}개는 넣지 않았어요. 모두 보려면 검수 옵션의 '바뀐 곳만 새로 짚기'를 끄고 다시 검수하세요.</div>` : ''}`;
}

/** 마지막 검수 뒤 수정 가운데 고친 곳만 다시 보기 대상(fast)의 고침안 묶음이 아닌 것의 수 (직접 고친 곳 · 다른 AI 수정 · 닫힌 지적의 묶음).
    '이 지적만 다시 검수'로 풀린 묶음은 세지 않는다 (home.js fixRecheckTargets 와 같은 셈) */
function chkOtherEdits(e, fast) {
  const groups = new Set(fast.map((f) => f.fix_group));
  const seen = new Set((e.findings || []).filter((f) => f.closed_by === 'one' && f.fix_group).map((f) => f.fix_group));
  return (e.edits || []).filter((x) => !x.undone && x.at > e.checked_at && !(x.group && (seen.has(x.group) || groups.has(x.group)))).length;
}

function chkStyleBox(n) {
  const d = S.chkStyle[n];
  if (!d) return '<div class="small">재는 중…</div>';
  if (d.error) return `<div class="note err">${esc(d.error)}</div>`;
  return `${d.warnings.length ? `<ul class="issue-list">${d.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>` : '<div class="note ok">기준을 넘은 문체 지표가 없어요.</div>'}
    <div class="small">AI 없이 저장한 본문을 레퍼런스 기준과 견줘요. 계산값이라 처리 상태는 두지 않아요.</div>
    <div class="row"><button type="button" class="btn small" data-action="chkStyleReload" data-arg="${n}">다시 재기</button><a href="${base()}/style" style="font-size:0.8125rem">${stepLabel('style')}로 가기</a></div>`;
}

/** 왼쪽 칸 탭. 초반 점검은 1~3화에만 있다. */
function chkTabs(n, e) {
  return [['issues', `모순 지적 ${(e.findings || []).length}`], ...(isOpening(n) ? [['opening', '초반 점검']] : []),
    ['style', `문체 지표${S.chkStyle[n] && S.chkStyle[n].warnings ? ` ${S.chkStyle[n].warnings.length}` : ''}`]];
}
const chkTabNow = (n, e) => (chkTabs(n, e).some(([k]) => k === S.chkTab) ? S.chkTab : 'issues');

/** 목록에 보일 지적과 회차 변화: 회차를 골랐으면 그 회차가 바꾼 지적, 아니면 처리 상태로 거르고 심각도 · 종류 · 문장 바뀜으로 더 거른 것.
    base 는 처리 상태로만 거른 목록 (더 거르기 칸의 수를 센다) */
function chkShown(n, e, text = '') {
  const no = S.chkRound[n] || 0;
  if (no) {
    const ch = roundChanges(e, no);
    return { list: findingOrder(e.findings.filter((f) => ch[f.id])), changes: ch, no, base: [] };
  }
  const base = e.findings.filter((f) => S.chkFilter === 'all' || f.status === S.chkFilter);
  return { list: findingOrder(base.filter((f) => chkNarrowHit(e, f, text))), changes: {}, no: 0, base };
}

const chkNarrowOn = () => !!(S.chkSev || S.chkType || S.chkChanged);
/** skip: 이 거르기는 빼고 본다 ('sev' · 'type' · 'changed'). 칸마다 다른 칸의 거르기만 적용한 수를 세려는 것 */
function chkNarrowHit(e, f, text, skip = '') {
  if (skip !== 'sev' && S.chkSev && (f.severity || 'mid') !== S.chkSev) return false;
  if (skip !== 'type' && S.chkType && f.type !== S.chkType) return false;
  return skip === 'changed' || !S.chkChanged || findingFlag(e, f, text) === 'changed';
}

/** 더 거르기 칸: 심각도 · 종류 · 문장 바뀜. 고를 거리는 처리 상태로 거른 목록(base)에 있는 것, 수는 다른 칸의 거르기를 적용한 것.
    지적이 셋 미만이고 거르지 않았으면 두지 않는다 */
function chkNarrow(e, text, base) {
  if (base.length < 3 && !chkNarrowOn()) return '';
  const btn = (act, arg, on, label) => `<button type="button" aria-pressed="${on}" data-action="${act}" data-arg="${esc(arg)}">${label}</button>`;
  const but = (skip) => base.filter((f) => chkNarrowHit(e, f, text, skip));
  const bySev = but('sev');
  const sevN = (k) => bySev.filter((f) => (f.severity || 'mid') === k).length;
  const sev = [btn('chkSev', '', !S.chkSev, '모두'), ...Object.entries(SEVERITY).filter(([k]) => base.some((f) => (f.severity || 'mid') === k) || S.chkSev === k).map(([k, l]) => btn('chkSev', k, S.chkSev === k, `${l} ${sevN(k)}`))].join('');
  const types = {};
  for (const f of base) types[f.type] = 0;
  if (S.chkType) types[S.chkType] = 0;
  for (const f of but('type')) types[f.type] += 1;
  const order = Object.keys(types).sort((a, b) => base.filter((f) => f.type === b).length - base.filter((f) => f.type === a).length);
  const type = [btn('chkType', '', !S.chkType, '모두'), ...order.map((k) => btn('chkType', k, S.chkType === k, `${esc(k)} ${types[k]}`))].join('');
  const changed = but('changed').filter((f) => findingFlag(e, f, text) === 'changed').length;
  const flag = changed || S.chkChanged ? `<button type="button" class="btn small${S.chkChanged ? ' primary' : ''}" aria-pressed="${S.chkChanged}" data-action="chkChanged">문장 바뀜 ${changed}</button>` : '';
  return `<div class="chk-narrow"><div class="chk-narrow-g"><span class="small">심각도</span><div class="seg" role="group" aria-label="심각도로 거르기">${sev}</div></div>
    <div class="chk-narrow-g"><span class="small">종류</span><div class="seg" role="group" aria-label="종류로 거르기">${type}</div></div>${flag}
    ${chkNarrowOn() ? '<button type="button" class="btn small ghost" data-action="chkNarrowOff">거르기 끄기</button>' : ''}</div>`;
}

/** 거른 열린 지적을 한꺼번에 그대로 둠 · 잘못 짚음으로 정하는 줄. 열림 목록을 더 걸렀을 때만 (모든 열린 지적을 한 번에 닫지 않게) */
function chkBulk(list) {
  if (S.chkFilter !== 'open' || !chkNarrowOn() || !list.length) return '';
  const off = autoOn() ? ' disabled' : '';
  return `<div class="chk-bulk"><span class="small">거른 지적 ${list.length}개를 한꺼번에</span>
    <button type="button" class="btn small" data-action="chkBulk" data-arg="kept"${off}>그대로 둠</button>
    <button type="button" class="btn small" data-action="chkBulk" data-arg="wrong"${off}>잘못 짚음</button></div>`;
}

function chkList(n, e, text, sel, checkBtn) {
  const tabs = chkTabs(n, e);
  const tab = chkTabNow(n, e);
  const head = `<div class="tabs wrap" role="tablist" aria-label="검수 종류">${tabs.map(([k, l]) => `<button type="button" role="tab" id="chk-tab-${k}" aria-selected="${tab === k}" aria-controls="chk-panel" data-action="chkTab" data-arg="${k}">${l}</button>`).join('')}</div>`;
  let body;
  if (tab === 'opening') body = openingChecks(n);
  else if (tab === 'style') body = chkStyleBox(n);
  else if (!(e.rounds || []).length) {
    body = `<div class="empty" style="padding:16px 8px"><p>아직 검수하지 않았어요.</p><p class="small">앞선 본문 · 설정 · 확정 사실과 어긋나는 곳을 근거 문장과 함께 찾아요.</p>${e.status === 'written' && S.deltas[n] === undefined ? flowStateToggle() : ''}${checkBtn}</div>`;
  } else {
    const { list, changes, no, base } = chkShown(n, e, text);
    const ids = new Set(list.map((f) => f.id));
    const bar = fbBar(n, e, text) + (no ? '' : chkNarrow(e, text, base) + chkBulk(list));
    const caption = no ? `<div class="between"><strong style="font-size:0.8125rem">${no}회차가 바꾼 지적</strong><button type="button" class="btn small ghost" data-action="chkRound" data-arg="${no}">회차 보기 끄기</button></div>` : '';
    body = list.length ? `${caption}${bar}<ul class="chk-list">${list.map((f) => {
      const flag = findingFlag(e, f, text);
      const child = f.parent && ids.has(f.parent);
      return `<li><button type="button" class="chk-item${f.status === 'open' ? '' : ' done'}${child ? ' child' : ''}" aria-current="${f.id === sel}" data-action="chkSel" data-arg="${esc(f.id)}">
        <span class="row" style="gap:4px"><span class="chip ${SEV_CHIP[f.severity] || 'warn'}">${SEVERITY[f.severity] || '보통'}</span><span class="chip">${esc(f.type)}</span>${ruleChip(f)}<span class="chip ${FINDING_CHIP[f.status]}">${FINDING_STATUS[f.status]}</span>${no && changes[f.id] ? `<span class="chip">${ROUND_CHANGE[changes[f.id]]}</span>` : ''}${flag ? `<span class="chip${flag === 'changed' ? ' warn' : ''}">${FINDING_FLAG[flag]}</span>` : ''}${f.parent ? '<span class="chip">고치다 생김</span>' : ''}</span>
        <span class="chk-desc">${esc(f.description)}</span><span class="small">${esc(srcLine(n, f))}</span></button></li>`;
    }).join('')}</ul>`
      : no ? `${caption}<div class="empty" style="padding:16px 8px"><p class="small">${no}회차는 지적 목록을 남기지 않은 예전 회차예요.</p></div>`
      : base.length ? `${bar}<div class="empty" style="padding:16px 8px"><p class="small">거른 조건에 맞는 지적이 없어요.</p><button type="button" class="btn small" data-action="chkNarrowOff">거르기 끄기</button></div>`
      : `<div class="empty" style="padding:16px 8px"><p class="small">${S.chkFilter === 'open' ? '열린 지적이 없어요. 상태 승인으로 넘어가도 돼요.' : '이 상태의 지적이 없어요.'}</p></div>`;
  }
  return `<section class="card tight c-list" aria-label="검수 결과">${head}<div role="tabpanel" id="chk-panel" aria-labelledby="chk-tab-${tab}" class="chk-panel">${body}</div></section>`;
}

function chkDetail(n, e, text, sel) {
  const f = (e.findings || []).find((x) => x.id === sel);
  if (!f || chkTabNow(n, e) !== 'issues') return '';
  const q = (f.current_quote || '').trim();
  const spot = findingSpot(text, f);
  const can = editableEp(e) && !autoOn();
  const key = `${n}:${f.id}`;
  if (S.chkNotesOf !== S.name) { S.chkNotesOf = S.name; S.chkNotes = {}; syncNoteDraft(); }
  const note = key in S.chkNotes ? S.chkNotes[key] : (f.note || '');
  const seg = Object.entries(FINDING_STATUS).map(([k, l]) => `<button type="button" aria-pressed="${f.status === k}" data-action="setFinding" data-arg="${esc(f.id)}:${k}"${autoOn() ? ' disabled' : ''}>${l}</button>`).join('');
  const sev = Object.entries(SEVERITY).map(([k, l]) => `<button type="button" aria-pressed="${(f.severity || 'mid') === k}" data-action="setSeverity" data-arg="${esc(f.id)}:${k}"${autoOn() ? ' disabled' : ''}>${l}</button>`).join('');
  const src = f.source_episode && f.source_episode !== n ? `<a href="${base()}/write/${f.source_episode}">${f.source_episode}화</a>` : esc(srcLabel(n, f));
  const decided = f.status === 'kept' || f.status === 'wrong';
  const parent = f.parent && (e.findings || []).find((x) => x.id === f.parent);
  const kids = (e.findings || []).filter((x) => x.parent === f.id);
  const log = (f.log || []).slice().reverse().map((x) => `<li><span class="when">${x.at ? editTime(x.at) : ''}</span><span>${esc(x.text)}</span></li>`).join('');
  return `<section class="card tight c-detail" aria-label="지적 상세">
    <div class="row" style="gap:4px"><span class="chip ${SEV_CHIP[f.severity] || 'warn'}">${SEVERITY[f.severity] || '보통'}</span><span class="chip">${esc(f.type)}</span>${ruleChip(f)}<span class="chip ${FINDING_CHIP[f.status]}">${FINDING_STATUS[f.status]}</span><span class="small">${f.first}회차부터${f.last !== f.first ? ` · 마지막 ${f.last}회차` : ''}</span></div>
    <h3 class="chk-title">${esc(f.description)}</h3>
    ${parent ? `<div class="small">원래 지적(${esc(findingShort(parent))})을 고친 문장 때문에 새로 어긋났어요. <button type="button" class="btn small ghost" data-action="chkSel" data-arg="${esc(parent.id)}">원래 지적 보기</button></div>` : ''}
    ${q ? `<div class="field"><span class="small">이번 화</span><blockquote class="chk-quote now">${esc(q)}</blockquote>${spot && !spot.near ? '' : `<div class="small">${spot ? '지금 본문에서는 비슷한 문장을 짚어 두었어요. 이미 고쳤을 수 있어요.' : '지금 본문에서 찾을 수 없어요. 이미 고쳤을 수 있어요.'}</div>`}</div>` : ''}
    ${f.origin === 'regex' ? `<div class="field"><span class="small">정규식${regexName(f) ? ` · ${esc(regexName(f))}` : ''}</span><code class="chk-pattern">${esc(f.source_quote || '')}</code></div>`
    : f.source_quote ? `<div class="field"><span class="small">근거 · ${src}</span><blockquote class="chk-quote">${esc(f.source_quote)}</blockquote></div>` : ''}
    ${f.suggestion ? `<div class="field"><span class="small">고칠 방향</span><div style="font-size:0.8125rem;line-height:1.55">→ ${esc(f.suggestion)}</div></div>` : ''}
    ${spot && can ? `<div class="row"><button type="button" class="btn small" data-action="chkOpen" data-arg="${esc(f.id)}">문장에서 고치기</button>${f.status === 'open' ? recheckBtn(f) : ''}</div>` : ''}
    ${stageLink(n, f)}
    <div class="field"><span class="small">심각도 · AI가 정하고 작가가 바꿔요</span><div class="seg chk-seg3" role="group" aria-label="심각도">${sev}</div></div>
    <div class="field"><span class="small">처리</span><div class="seg chk-seg" role="group" aria-label="처리 상태">${seg}</div></div>
    ${decided ? `<div class="field"><label class="small" for="chk-note">왜 ${FINDING_STATUS[f.status]}인지 적어 두면 다시 나와도 바로 알아볼 수 있어요</label>
      <textarea id="chk-note" rows="2" data-chk-note="${esc(key)}">${esc(note)}</textarea>
      <div><button type="button" class="btn small" data-action="saveFindingNote" data-arg="${esc(f.id)}">메모 저장</button></div></div>` : ''}
    ${f.status === 'fixed' && f.closed_by === 'recheck' ? '<div class="small">다시 검수에서 문장이 사라져 고침으로 바꿨어요.</div>' : ''}
    ${f.status === 'fixed' && f.closed_by === 'one' ? '<div class="small">이 지적만 다시 검수해 풀려서 고침으로 바꿨어요. 아니라고 보면 열림으로 되돌리세요.</div>' : ''}
    ${kids.length ? `<div class="field"><span class="small">이 지적을 고치다 생긴 지적 ${kids.length}</span><div class="row" style="gap:6px">${kids.map((k) => `<button type="button" class="btn small" data-action="chkSel" data-arg="${esc(k.id)}">${esc(findingShort(k))}</button>`).join('')}</div></div>` : ''}
    ${log ? `<div class="field"><span class="small">처리 기록</span><ul class="chk-log">${log}</ul></div>` : ''}
  </section>`;
}

// ----- 문장에서 뜨는 고치는 창 (passage.js 떠 있는 도구의 mode 'finding') -----

/** 고침안 하나: 지적 문장과 딸린 곳의 바뀐 곳, 딸린 곳 체크 칸, 적용 버튼. */
function fixOptionHtml(n, e, f, opt, k, text, busy) {
  const skip = S.fixSkip[`${n}:${f.id}:${k}`] || [];
  const missing = fixMissing(text, f, opt, skip);
  const extra = opt.extra || [];
  const count = 1 + extra.length - skip.length;
  const rows = extra.map((x, i) => `<label class="fix-extra"><input type="checkbox" data-action="fixSkip" data-arg="${esc(f.id)}:${k}:${i}"${skip.includes(i) ? '' : ' checked'}${busy ? ' disabled' : ''}>
      <span><span class="pdiff small-diff">${wordDiff(x.quote, x.replacement)}</span>${x.reason ? `<span class="small">${esc(x.reason)}</span>` : ''}</span></label>`).join('');
  return `<li class="fix-opt">
    <div class="between"><strong style="font-size:0.8125rem">${esc(opt.label)}</strong><button type="button" class="btn small" data-action="fixApply" data-arg="${esc(f.id)}:${k}"${busy || missing.length ? ' disabled' : ''}>${count > 1 ? `${count}곳 적용` : '적용'}</button></div>
    <div class="pdiff small-diff">${wordDiff(f.current_quote.trim(), opt.text)}</div>
    ${opt.note ? `<span class="small">${esc(opt.note)}</span>` : ''}
    ${extra.length ? `<div class="fix-extras"><span class="small" style="font-weight:700">이 화의 딸린 곳 ${extra.length} · 함께 고쳐요</span>${rows}</div>` : ''}
    ${missing.length ? `<span class="small" style="color:var(--amber-ink)">고침안을 받은 뒤 본문이 바뀌어 «${esc(missing[0].slice(0, 30))}»을 찾을 수 없어요. 고침안을 다시 받으세요.</span>` : ''}
  </li>`;
}

/** 지적 하나의 고치는 창. 열린 지적이 아니면 다시 열기만 둔다. */
function fixPanel(n, fid) {
  const e = ep(n);
  const f = e && (e.findings || []).find((x) => x.id === fid);
  if (!f) return '';
  const text = textNow(n);
  const busy = autoOn();
  const head = `<div class="between"><span class="row" style="gap:4px"><span class="chip ${SEV_CHIP[f.severity] || 'warn'}">${SEVERITY[f.severity] || '보통'}</span><span class="chip">${esc(f.type)}</span><strong class="fix-title">${esc(findingShort(f))}</strong></span>
    <button type="button" class="btn small ghost" data-action="selCancel">닫기</button></div>`;
  if (f.status !== 'open') {
    const why = f.closed_by === 'one' ? '이 지적만 다시 검수해 풀려서 고침으로 닫았어요.' : f.closed_by === 'recheck' ? '다시 검수에서 문장이 사라져 고침으로 닫았어요.' : `작가가 ${FINDING_STATUS[f.status]}으로 정했어요.`;
    return `${head}<div class="small">${why}</div>
      <div class="row"><button type="button" class="btn small" data-action="setFinding" data-arg="${esc(f.id)}:open"${busy ? ' disabled' : ''}>다시 열기</button></div>`;
  }
  const applied = fixApplied(e, f);
  const fixes = f.fixes || [];
  const regex = f.origin === 'regex';  // 정규식 지적은 근거 쪽이 없다 (정할 것 18)
  const ways = `<div class="fix-ways">
      ${regex ? '' : `<div class="fix-way"><strong>근거 쪽이 틀렸어요</strong><span class="small">근거(${esc(srcLabel(n, f))})를 고치는 게 맞으면 그곳으로 가요</span>${f.source_episode && f.source_episode !== n ? `<a class="btn small" href="${base()}/write/${f.source_episode}">${f.source_episode}화 본문 열기</a>` : f.source_episode === n ? '<span class="small">같은 화 앞 문장이에요. 본문에서 바로 고치세요</span>' : `<a class="btn small" href="${base()}/setup">설정 열기</a>`}</div>`}
      <div class="fix-way"><strong>일부러 그렇게 썼어요</strong><span class="small">그대로 둠으로 두고 이유를 남겨요. 다시 나와도 결정이 지켜져요</span><button type="button" class="btn small" data-action="setFinding" data-arg="${esc(f.id)}:kept"${busy ? ' disabled' : ''}>그대로 둠</button></div>
      <div class="fix-way"><strong>${regex ? '규칙이 잘못 짚었어요' : 'AI가 잘못 짚었어요'}</strong><span class="small">${regex ? '이 문장은 이 규칙에 해당하지 않아요' : '모순이 아니에요'}. 다시 나와도 결정이 지켜져요</span><button type="button" class="btn small" data-action="setFinding" data-arg="${esc(f.id)}:wrong"${busy ? ' disabled' : ''}>잘못 짚음</button></div>
    </div>`;
  const fb = jobBtn('fix_one', n, fixes.length ? '고침안 다시 받기' : 'AI 고침안 받기', S.name, f.id);  // 고치는 창은 #app 밖이라 작업 상태를 여기서 그린다
  const tools = `<div class="row"><button type="button" class="btn small" data-action="fixGet" data-arg="${esc(f.id)}"${fb.attr}${busy ? ' disabled' : ''}>${fb.label}</button>
      <button type="button" class="btn small" data-action="selManual">직접 고치기</button>${f.suggestion ? `<button type="button" class="btn small" data-action="issueAsk" data-arg="${esc(f.id)}">대화로 고치기</button>` : ''}</div>`;
  const done = applied ? `<div class="note info fix-done"><span>고침안을 넣었어요. 고친 문장이 다른 곳과 어긋나지 않는지 이 지적만 다시 물어볼 수 있어요.</span>
      <span class="row" style="gap:6px"><button type="button" class="btn small" data-action="fixUndo" data-arg="${esc(f.fix_group)}"${busy ? ' disabled' : ''}>한 번에 되돌리기</button>${recheckBtn(f, busy)}</span></div>` : '';
  const list = fixes.length && !applied
    ? `<span class="small">본문을 고칠게요 · AI 고침안 ${fixes.length}개</span><ol class="fix-list">${fixes.map((o, k) => fixOptionHtml(n, e, f, o, k, text, busy)).join('')}</ol>` : '';
  return `${head}${done}${list}${applied ? '' : tools}${ways}`;
}

// ----- 고침안 한꺼번에: 열린 지적마다 AI 고침안을 받고(작업 'fixes'), 작가가 지적마다 고른 것만 넣는다 -----

/** 고침안을 받을 지적: 열린 지적 가운데 문장이 지금 본문에 있고 넣을 수 있는 고침안이 없는 것 (서버 pipeline.fix_targets 와 같은 셈). */
function fbNeed(e, text) {
  return (e.findings || []).filter((f) => {
    const q = (f.current_quote || '').trim();
    return f.status === 'open' && q && text.includes(q) && !(f.fixes || []).some((o) => !fixMissing(text, f, o, []).length);
  });
}

/** 지적의 넣을 수 있는 고침안 번호 (고른 딸린 곳을 뺀 뒤 모든 문장이 본문에 있는 것). 이미 넣은 지적은 없다. */
function fbUsable(n, e, f, text) {
  if (f.status !== 'open' || fixApplied(e, f)) return [];
  return (f.fixes || []).map((o, k) => k).filter((k) => !fixMissing(text, f, f.fixes[k], S.fixSkip[`${n}:${f.id}:${k}`] || []).length);
}

/** 보이는 고침안 번호: 고른 적이 있고 넣을 수 있으면 그것, 아니면 넣을 수 있는 첫 안. */
function fbShown(n, e, f, text) {
  const ok = fbUsable(n, e, f, text);
  const k = S.fbOpt[`${n}:${f.id}`];
  return ok.includes(k) ? k : ok.length ? ok[0] : -1;
}

/** 고침안이 바꿀 본문 자리들 [시작, 끝]. 같은 자리를 바꾸는 두 안을 함께 고르면 뒤 것은 들어가지 않는다. */
function fbSpans(text, f, opt, skip) {
  const quotes = [f.current_quote, ...(opt.extra || []).filter((_, i) => !skip.includes(i)).map((x) => x.quote)];
  return quotes.map((q) => (q || '').trim()).filter(Boolean).map((q) => { const a = text.indexOf(q); return [a, a + q.length]; }).filter(([a]) => a >= 0);
}

/** 고른 지적 가운데 앞에서 고른 지적과 같은 자리를 바꾸는 것: id → 앞 지적. 넣는 차례(목록 차례)로 센다. */
function fbClash(n, e, text, list) {
  const taken = [];
  const out = {};
  for (const f of list) {
    const k = fbShown(n, e, f, text);
    if (!S.fbOn[`${n}:${f.id}`] || k < 0) continue;
    const spans = fbSpans(text, f, f.fixes[k], S.fixSkip[`${n}:${f.id}:${k}`] || []);
    const hit = taken.find((t) => t.spans.some(([a, b]) => spans.some(([c, d]) => a < d && c < b)));
    if (hit) out[f.id] = hit.f;
    else taken.push({ f, spans });
  }
  return out;
}

/** 지적 목록 위 띠: 열린 지적 모두 고침안 받기 · 한꺼번에 검토. 고칠 수 있는 화이고 자동 집필이 돌지 않을 때만. */
function fbBar(n, e, text) {
  if (!editableEp(e) || autoOn()) return '';
  const open = (e.findings || []).filter((f) => f.status === 'open');
  if (!open.length) return '';
  const need = fbNeed(e, text).length;
  const ready = open.filter((f) => fbUsable(n, e, f, text).length).length;
  const b = jobBtn('fixes', n, `열린 지적 ${need}개 고침안 받기`);
  return `<div class="fb-bar"><span class="small">AI가 열린 지적마다 고침안을 내면, 지적마다 보고 고른 것만 본문에 넣어요</span>
    <div class="row" style="gap:6px">${need ? `<button type="button" class="btn small" data-action="fixAll" data-arg="${n}"${b.attr}>${b.label}</button>` : ''}
    ${ready ? `<button type="button" class="btn small${need ? '' : ' primary'}" data-action="fbOpen" data-arg="${n}">한꺼번에 검토 · ${ready}</button>` : ''}</div></div>`;
}

/** 한꺼번에 검토: 열린 지적마다 고침안 하나를 보고 고른다. 고르지 않은 지적은 그대로 남는다. */
function fbView(n, e, text) {
  const list = findingOrder((e.findings || []).filter((f) => f.status === 'open'));
  const clash = fbClash(n, e, text, list);
  const need = fbNeed(e, text).length;
  const b = jobBtn('fixes', n, `남은 ${need}개 고침안 받기`);
  let picked = 0;
  let pickable = 0;
  const rows = list.map((f) => {
    const key = `${n}:${f.id}`;
    const chips = `<span class="chip ${SEV_CHIP[f.severity] || 'warn'}">${SEVERITY[f.severity] || '보통'}</span><span class="chip">${esc(f.type)}</span>`;
    const note = S.fbNote[key] ? `<span class="small" style="color:var(--amber-ink)">${esc(S.fbNote[key])}</span>` : '';
    if (fixApplied(e, f)) {
      return `<li class="fb-row done"><div class="between"><span class="row" style="gap:4px">${chips}<span class="chip">넣음</span><strong class="fb-desc">${esc(f.description)}</strong></span>
        <button type="button" class="btn small" data-action="fbUndo" data-arg="${esc(f.fix_group)}">되돌리기</button></div></li>`;
    }
    const k = fbShown(n, e, f, text);
    if (k < 0) {
      const q = (f.current_quote || '').trim();
      const why = !q || !text.includes(q) ? '지적한 문장을 지금 본문에서 찾을 수 없어요. 이미 고쳤으면 다시 검수하세요'
        : (f.fixes || []).length ? '고침안을 받은 뒤 본문이 바뀌었어요. 고침안을 다시 받으세요' : '아직 고침안이 없어요';
      return `<li class="fb-row off"><div class="row" style="gap:4px">${chips}<strong class="fb-desc">${esc(f.description)}</strong></div>
        <span class="small">${esc(why)}</span>${note}</li>`;
    }
    pickable++;
    const on = !!S.fbOn[key];
    if (on) picked++;
    const opt = f.fixes[k];
    const skip = S.fixSkip[`${n}:${f.id}:${k}`] || [];
    const ok = fbUsable(n, e, f, text);
    const seg = ok.length > 1 ? `<div class="seg" role="group" aria-label="고침안">${ok.map((i) => `<button type="button" aria-pressed="${i === k}" data-action="fbOpt" data-arg="${esc(f.id)}:${i}">${esc(f.fixes[i].label)}</button>`).join('')}</div>`
      : `<strong style="font-size:0.8125rem">${esc(opt.label)}</strong>`;
    const extras = (opt.extra || []).map((x, i) => `<label class="fix-extra"><input type="checkbox" data-action="fbSkip" data-arg="${esc(f.id)}:${k}:${i}"${skip.includes(i) ? '' : ' checked'}>
        <span><span class="pdiff small-diff">${wordDiff(x.quote, x.replacement)}</span>${x.reason ? `<span class="small">${esc(x.reason)}</span>` : ''}</span></label>`).join('');
    const hit = clash[f.id];
    return `<li class="fb-row${on ? ' on' : ''}">
      <label class="fb-pick"><input type="checkbox" data-action="fbPick" data-arg="${esc(f.id)}"${on ? ' checked' : ''}><span class="row" style="gap:4px">${chips}<strong class="fb-desc">${esc(f.description)}</strong></span></label>
      ${f.suggestion ? `<span class="small">고칠 방향 → ${esc(f.suggestion)}</span>` : ''}
      ${seg}
      <div class="pdiff small-diff">${wordDiff(f.current_quote.trim(), opt.text)}</div>
      ${opt.note ? `<span class="small">${esc(opt.note)}</span>` : ''}
      ${extras ? `<div class="fix-extras"><span class="small" style="font-weight:700">이 화의 딸린 곳 ${opt.extra.length} · 함께 고쳐요</span>${extras}</div>` : ''}
      ${hit ? `<span class="small" style="color:var(--amber-ink)">앞에서 고른 지적(${esc(findingShort(hit))})과 같은 문장을 바꿔요. 함께 넣으면 이 안은 들어가지 않아요.</span>` : ''}
      ${note}
    </li>`;
  }).join('');
  return `<section class="card fb" aria-label="고침안 한꺼번에 검토">
    <div class="between"><div class="lead" style="gap:2px"><h2>고침안 한꺼번에 검토</h2>
      <span class="small">지적마다 고침안을 보고 넣을 것만 고르세요. 고른 것만 본문에 들어가고, 지적마다 한 묶음이라 하나씩 되돌릴 수 있어요.</span></div>
      <div class="row" style="gap:6px">${need ? `<button type="button" class="btn small" data-action="fixAll" data-arg="${n}"${b.attr}>${b.label}</button>` : ''}<button type="button" class="btn small ghost" data-action="fbClose">닫기</button></div></div>
    <ol class="fb-list">${rows}</ol>
    <div class="between fb-foot"><span class="small">고른 ${picked}개 / 넣을 수 있는 ${pickable}개 · 넣은 뒤 고친 곳만 다시 보기로 풀렸는지 바로 확인해요</span>
      <div class="row" style="gap:6px"><button type="button" class="btn small" data-action="fbAll" data-arg="1"${pickable ? '' : ' disabled'}>모두 고르기</button><button type="button" class="btn small" data-action="fbAll" data-arg="0"${picked ? '' : ' disabled'}>모두 풀기</button>
        <button type="button" class="btn primary" data-action="fbApply"${picked ? '' : ' disabled'}>고른 ${picked}개 넣고 다시 보기</button></div></div>
  </section>`;
}

/** 작업 'fixes' 가 끝났다: 받지 못한 지적의 까닭을 남기고 그 화의 한꺼번에 검토를 연다. */
function fixesJobResult(j) {
  const n = j.ep;
  for (const x of (j.result && j.result.failed) || []) S.fbNote[`${n}:${x.id}`] = `고침안을 받지 못했어요: ${x.error}`;
  S.fbOpen = n;
}

/** 검수 단계 (한 화 화면의 검수 칸). 화면 틀은 write.js viewEpisode 가 그린다 */
const viewCheck = (n) => viewEpisode(n, 'check');

/** 한 화 화면의 검수 칸 (write.js viewEpisode 가 부른다). 본문이 있는 화에만 부른다.
    buttons: 머리 보조 버튼, primary: 머리 주 버튼, top: 칸 위 띠, side: 오른쪽 칸, full: 본문 · 칸 대신 그릴 것 (한꺼번에 검토) */
function checkPanel(n) {
  const e = ep(n);
  const st = checkState(e);
  const rounds = e.rounds || [];
  const last = rounds[rounds.length - 1];
  const b = jobBtn('check', n, last ? `다시 검수 · ${last.no + 1}회차` : '검수하기');
  // 지난 검수 뒤 고침안만 넣었으면 '고친 곳만 다시 보기'가 주 버튼이다 (findings.fix_recheck_targets). 다시 검수는 옆에 그대로 둔다
  const fast = last && editableEp(e) && !autoOn() ? fixRecheckTargets(e) : [];
  // 주 버튼은 한 화면에 하나, 머리 줄 오른쪽 끝에 둔다 (디자인 시스템 Button). 검수 전에는 빈 목록의 '검수하기'가 주 버튼이라 머리에 두지 않는다
  const checkPrimary = !fast.length && (!last || st.stale || !st.checked);
  const reviewPrimary = !fast.length && !checkPrimary;
  const fb = jobBtn('recheck', n, `고친 곳만 다시 보기 · 지적 ${fast.length}`);
  const fastBtn = fast.length ? `<button class="btn primary" data-action="fixRecheck" data-arg="${n}"${fb.attr}>${fb.label}</button>` : '';
  // 첫 검수는 flow.js flowCheck: 상태 변경안도 함께 만든다 (켰을 때). 다시 검수는 검수만
  const checkBtn = `<button class="btn${checkPrimary ? ' primary' : ''}" data-action="${last ? 'checkEp' : 'flowCheck'}" data-arg="${n}"${!autoOn() ? b.attr : ' disabled'}>${b.label}</button>`;
  const toReview = e.status === 'written'
    ? `<a class="btn${reviewPrimary ? ' primary' : ''}" href="${base()}/review/${n}">상태 승인으로${st.open ? ` · 열린 지적 ${st.open}` : ''}</a>`
    : e.status === 'finalized' && reviewPrimary ? nextStepBtn() : '';  // 반영 끝난 화도 검수가 지금 할 일이면 다음 할 일 버튼은 두지 않는다
  const lead = `${checkOptsMenu()}${S.mode === 'brief' ? `<a class="btn" href="${base()}/brief/${n}" data-action="openCheckBrief" data-arg="${n}">검수 지시서</a>` : ''}`;
  const [buttons, primary] = !last ? [lead + toReview, ''] : fast.length ? [lead + toReview + checkBtn, fastBtn]
    : checkPrimary ? [lead + toReview, checkBtn] : [lead + checkBtn, toReview];
  const text = textNow(n);
  const top = chkStrip(n, e, st, fast);
  if (S.fbOpen === n && editableEp(e) && !autoOn() && rounds.length) return { buttons, primary, top, full: fbView(n, e, text) };
  const sel = chkSelected(n);
  // 좁은 폭은 목록 → 상세 → 본문 순서 (viewEpisode 가 칸을 본문 앞에 둔다)
  return { buttons, primary, top, side: `<div class="c-side">${chkList(n, e, text, sel, checkBtn)}
      ${chkDetail(n, e, text, sel)}</div>`,
    hint: editableEp(e) ? '지적을 고르면 본문이 그 문장으로 옮겨 가고, 문장에서 고치는 창이 떠요' : '' };
}

// 읽기 전용 본문의 지적 밑줄을 누르면 그 지적을 고른다 (고치는 본문은 marks.js 가 고치는 창까지 띄운다)
document.addEventListener('click', (ev) => {
  const m = ev.target.closest && ev.target.closest('.read mark.hl.issue');
  if (!m || S.route[2] !== 'check') return;
  S.chkSel[Number(S.route[3])] = m.dataset.hl.slice(2);
  render();
});

/** 지금 화 번호 (검수 화면 주소의 화). */
const chkEp = () => Number(S.route[3]) || currentEp();

/** 고치는 창이 가리킬 자리: 지적 문장이 그대로면 그 자리, 고침안을 넣었으면 지적 문장을 대신한 글, 아니면 비슷한 문장. */
function findingAnchor(n, f) {
  const text = textNow(n);
  const q = (f.current_quote || '').trim();
  const exact = q ? text.indexOf(q) : -1;
  if (exact !== -1) return { a: exact, b: exact + q.length, near: false };
  const main = (ep(n).edits || []).find((x) => f.fix_group && x.group === f.fix_group && !x.undone && x.before.trim() === q && x.after);
  const at = main ? text.indexOf(main.after) : -1;
  if (at !== -1) return { a: at, b: at + main.after.length, near: true };
  return findingSpot(text, f);
}

/** 지적 하나를 고친다. 실패하면 오류를 알리고 false 를 돌려준다 */
async function chkPut(n, id, body) {
  try {
    takeCheck(n, await api('PUT', `/projects/${enc(S.name)}/episodes/${n}/findings/${enc(id)}`, body));
    return true;
  } catch (err) {
    toast(err.message, true);
    return false;
  }
}

/** 본문을 바꾸는 요청 뒤: 서버 작품을 받고, 고치는 창이 열려 있으면 그 지적의 새 자리로 옮긴다. */
function afterFix(n, fid, pj) {
  S.project = pj;
  const f = (ep(n).findings || []).find((x) => x.id === fid);
  const spot = f && findingAnchor(n, f);
  if (spot) {
    S.selFocus = { n, start: spot.a, end: spot.b };
    S.selTool = { n, start: spot.a, text: textNow(n).slice(spot.a, spot.b), mode: 'finding', fid };
  }
}

/** 지적 상세의 처리 기록으로 화면을 옮긴다 */
function showFindingLog() {
  const el = document.querySelector('.c-detail .chk-log');
  if (el) el.scrollIntoView({ block: 'nearest' });
}

Object.assign(actions, {
  async toggleCheckAfterWrite() {
    const on = !P().settings.check_after_write;
    P().settings.check_after_write = on;
    render();
    try {
      S.project = await api('PUT', `/projects/${enc(S.name)}/check-after-write`, { on });
    } catch (err) {
      toast(err.message, true);
    }
  },
  async toggleCheckScope() {
    const on = P().settings.check_scope === false;
    P().settings.check_scope = on;
    render();
    try {
      S.project = await api('PUT', `/projects/${enc(S.name)}/check-scope`, { on });
    } catch (err) {
      toast(err.message, true);
    }
  },
  async toggleCheckMotion() {
    const on = P().settings.check_motion === false;
    P().settings.check_motion = on;
    render();
    try {
      S.project = await api('PUT', `/projects/${enc(S.name)}/check-motion`, { on });
    } catch (err) {
      toast(err.message, true);
    }
  },
  async toggleStageExtract() {
    const on = P().settings.stage_extract === false;
    P().settings.stage_extract = on;
    render();
    try {
      S.project = await api('PUT', `/projects/${enc(S.name)}/stage-extract`, { on });
    } catch (err) {
      toast(err.message, true);
    }
  },
  stgGo(arg) {
    const [n, ev, beat] = String(arg).split(':').map(Number);
    S.stgJump = { n, ev, role: 'text', beat };
    location.hash = `${base()}/stage/${n}/${ev}`;
  },
  chkSel(id) {
    actions.chkOpen(id);
  },
  /** 지적을 고르고 본문을 그 문장으로 옮긴다. 고칠 수 있는 본문이면 문장에서 고치는 창을 띄운다. */
  chkOpen(id) {
    const n = chkEp();
    const e = ep(n);
    const f = e && (e.findings || []).find((x) => x.id === id);
    if (!f) return;
    S.chkSel[n] = id;
    const spot = findingAnchor(n, f);
    if (spot && editableEp(e) && !autoOn() && S.chkTab === 'issues') {
      S.selFocus = { n, start: spot.a, end: spot.b };
      S.selTool = { n, start: spot.a, text: textNow(n).slice(spot.a, spot.b), mode: 'finding', fid: id };
      render();
      return;
    }
    if (S.selTool && S.selTool.mode === 'finding') hideTool();
    render();
    const m = document.querySelector('.read mark.hl.issue.sel');
    if (m) m.scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  },
  chkFilter(k) {
    S.chkFilter = k;
    S.chkRound[chkEp()] = 0;
    render();
  },
  chkSev(k) {
    S.chkSev = k || '';
    render();
  },
  chkType(k) {
    S.chkType = k || '';
    render();
  },
  chkChanged() {
    S.chkChanged = !S.chkChanged;
    render();
  },
  chkNarrowOff() {
    S.chkSev = S.chkType = '';
    S.chkChanged = false;
    render();
  },
  /** 거른 열린 지적을 한꺼번에 그대로 둠 · 잘못 짚음으로. 묻고, 한 번에 저장한다 (web.set_findings) */
  async chkBulk(status) {
    const n = chkEp();
    const e = ep(n);
    const { list } = chkShown(n, e, textNow(n));
    if (!list.length || S.chkFilter !== 'open' || !chkNarrowOn()) return;
    const what = status === 'wrong' ? '잘못 짚음' : '그대로 둠';
    const ok = await askConfirm(`거른 열린 지적 ${list.length}개를 '${what}'으로 정해요. 다시 검수에서 같은 지적이 나와도 이 결정을 지켜요. 하나씩 '열림'으로 되돌릴 수 있어요.`, { title: `${list.length}개를 ${what}으로`, ok: `${what}으로 정하기` });
    if (!ok) return;
    try {
      takeCheck(n, await api('PUT', `/projects/${enc(S.name)}/episodes/${n}/findings`, { ids: list.map((f) => f.id), status }));
      toast(`지적 ${list.length}개를 '${what}'으로 정했어요`);
    } catch (err) {
      toast(err.message, true);
    }
    render();
  },
  chkRound(no) {
    const n = chkEp();
    S.chkRound[n] = S.chkRound[n] === Number(no) ? 0 : Number(no);
    render();
  },
  chkTab(k) {
    S.chkTab = k;
    if (S.selTool && S.selTool.mode === 'finding') hideTool();
    render();
  },
  async chkStyleReload(n) {
    n = Number(n);
    S.chkStyle[n] = null;
    render();
    await checkLoad(n);
    render();
  },
  /** 집필 화면 '여는 방식 비교'에서: 검수 화면의 초반 점검 탭으로 */
  chkOpening(n) {
    S.chkTab = 'opening';
    location.hash = `${base()}/check/${n}`;
  },
  openCheckBrief(n) {
    BRIEF_TABS[`${S.name}:${n}`] = 'check';
    location.hash = `${base()}/brief/${n}`;
  },
  async setFinding(arg) {
    const n = chkEp();
    const [id, status] = String(arg).split(':');
    const f = ep(n).findings.find((x) => x.id === id);
    if (!f || f.status === status) return;
    // 고침으로 닫으면 다음 열린 지적으로 넘어간다. 그대로 둠 · 잘못 짚음은 메모를 적을 수 있게 남는다
    const next = status === 'fixed' ? findingOrder(ep(n).findings).find((x) => x.status === 'open' && x.id !== id) : null;
    const ok = await chkPut(n, id, { status });
    if (ok && next) S.chkSel[n] = next.id;
    if (S.selTool && S.selTool.mode === 'finding' && S.selTool.fid === id && status !== 'open') hideTool();
    render();
  },
  async setSeverity(arg) {
    const n = chkEp();
    const [id, severity] = String(arg).split(':');
    const f = ep(n).findings.find((x) => x.id === id);
    if (!f || f.severity === severity) return;
    await chkPut(n, id, { severity });
    render();
  },
  async saveFindingNote(id) {
    const n = chkEp();
    const f = ep(n).findings.find((x) => x.id === id);
    if (!f) return;
    const key = `${n}:${id}`;
    const note = key in S.chkNotes ? S.chkNotes[key] : (f.note || '');
    if (!await chkPut(n, id, { note })) return;  // 실패하면 초안을 그대로 둔다
    delete S.chkNotes[key];
    syncNoteDraft();
    toast('메모를 저장했어요');
    render();
  },
  /** 고침안의 딸린 곳 체크 칸: 끄면 그곳은 빼고 넣는다 */
  fixSkip(arg) {
    const [id, k, i] = String(arg).split(':');
    const key = `${chkEp()}:${id}:${k}`;
    const skip = new Set(S.fixSkip[key] || []);
    if (skip.has(Number(i))) skip.delete(Number(i));
    else skip.add(Number(i));
    S.fixSkip[key] = [...skip].sort((a, b) => a - b);
    showTool();
  },
  /** AI 고침안 받기 (작업 'fix_one'). 옛 동작처럼 묻지 않고 저장하고, 본문도 먼저 저장한다 (AI는 저장된 본문을 읽는다) */
  async fixGet(id) {
    const n = chkEp();
    try {
      await saveIfDirty();
      await flushText(n);
    } catch (err) {
      showError(err);
      return;
    }
    Object.keys(S.fixSkip).filter((k) => k.startsWith(`${n}:${id}:`)).forEach((k) => delete S.fixSkip[k]);
    await startJob('fix_one', n, { target: id }, { quiet: true });
  },
  async fixApply(arg) {
    const n = chkEp();
    const [id, k] = String(arg).split(':');
    const skip = S.fixSkip[`${n}:${id}:${k}`] || [];
    const url = `/projects/${enc(S.name)}/episodes/${n}/findings/${enc(id)}/fixes/${k}/apply`;
    await run('고침안을 넣는 중', async () => {
      await saveIfDirty();
      await flushText(n);
      let pj;
      try {
        pj = await api('POST', url, { skip });
      } catch (err) {
        // 그대로 둠 · 잘못 짚음 지적의 문장을 건드리는 고침안: 서버가 막은 까닭을 보이고 작가가 확인하면 넣는다
        if (!/그대로 두기로 정한 지적/.test(err.message) || !(await askConfirm(err.message.replace(/ 그래도 적용하려면.*$/, ' 그래도 넣을까요?'), { ok: '넣기' }))) throw err;
        pj = await api('POST', url, { skip, confirm: true });
      }
      afterFix(n, id, pj);
    });
  },
  /** 열린 지적 모두 고침안 받기 (작업 'fixes'). 저장하지 않은 본문을 먼저 저장한다 */
  async fixAll(n) {
    n = Number(n);
    try {
      await saveIfDirty();
      await flushText(n);
    } catch (err) {
      showError(err);
      return;
    }
    await startJob('fixes', n);
  },
  /** 고친 곳만 다시 보기 (작업 'recheck'). 검수하기와 같이 저장하지 않은 작품 변경은 묻고, 본문은 먼저 저장한다 (app.js checkReady).
      직접 고친 곳이 생기면 서버가 다시 검수하라고 알린다 */
  async fixRecheck(n) {
    n = Number(n);
    if (!(await checkReady(n))) return;
    await startJob('recheck', n);
  },
  fbOpen(n) {
    S.fbOpen = Number(n);
    hideTool();
    render();
  },
  fbClose() {
    S.fbOpen = 0;
    render();
  },
  fbPick(id) {
    const key = `${chkEp()}:${id}`;
    if (S.fbOn[key]) delete S.fbOn[key];
    else S.fbOn[key] = true;
    render();
  },
  fbOpt(arg) {
    const [id, k] = String(arg).split(':');
    S.fbOpt[`${chkEp()}:${id}`] = Number(k);
    render();
  },
  fbSkip(arg) {
    const [id, k, i] = String(arg).split(':');
    const key = `${chkEp()}:${id}:${k}`;
    const skip = new Set(S.fixSkip[key] || []);
    if (skip.has(Number(i))) skip.delete(Number(i));
    else skip.add(Number(i));
    S.fixSkip[key] = [...skip].sort((a, b) => a - b);
    render();
  },
  /** 모두 고르기 (1) · 모두 풀기 (0): 넣을 수 있는 열린 지적만 */
  fbAll(v) {
    const n = chkEp();
    const e = ep(n);
    const text = textNow(n);
    for (const f of (e.findings || []).filter((x) => x.status === 'open')) {
      const key = `${n}:${f.id}`;
      if (v === '1' && fbShown(n, e, f, text) >= 0) S.fbOn[key] = true;
      else delete S.fbOn[key];
    }
    render();
  },
  /** 고른 고침안을 목록 차례(심각도 순)로 넣는다. 그대로 두기로 정한 지적의 문장을 건드리는 안은 확인한 뒤 다시 넣는다.
      하나라도 넣었고 모두 넣었으면 검토 화면을 닫고 고친 곳만 다시 보기(작업 'recheck')를 바로 시작한다.
      넣지 못한 안이 있으면 그 까닭을 볼 수 있게 화면을 남기고 다시 보기는 시작하지 않는다 */
  async fbApply() {
    const n = chkEp();
    const e = ep(n);
    const text = textNow(n);
    const items = findingOrder((e.findings || []).filter((f) => f.status === 'open' && S.fbOn[`${n}:${f.id}`]))
      .map((f) => ({ f, k: fbShown(n, e, f, text) })).filter((x) => x.k >= 0)
      .map(({ f, k }) => ({ fid: f.id, k, skip: S.fixSkip[`${n}:${f.id}:${k}`] || [] }));
    if (!items.length) return;
    const url = `/projects/${enc(S.name)}/episodes/${n}/fixes/apply`;
    let recheck = false;
    await run('고른 고침안을 넣는 중', async () => {
      await saveIfDirty();
      await flushText(n);
      let res = await api('POST', url, { items });
      let applied = res.applied;
      const decided = res.failed.filter((x) => /그대로 두기로 정한 지적/.test(x.error));
      if (decided.length && await askConfirm(`고른 고침안 ${decided.length}개는 그대로 두기로 정한 지적의 문장도 바꿔요. 그래도 넣을까요?`, { ok: '넣기' })) {
        S.project = res.project;
        const again = await api('POST', url, { items: items.filter((x) => decided.some((d) => d.fid === x.fid)), confirm: true });
        res = { project: again.project, failed: [...res.failed.filter((x) => !decided.includes(x)), ...again.failed] };
        applied = [...applied, ...again.applied];
      }
      S.project = res.project;
      for (const id of applied) { delete S.fbOn[`${n}:${id}`]; delete S.fbNote[`${n}:${id}`]; }
      for (const x of res.failed) S.fbNote[`${n}:${x.fid}`] = `넣지 못했어요: ${x.error}`;
      recheck = !!applied.length && !res.failed.length;
      toast(res.failed.length ? `${applied.length}개를 넣었어요. ${res.failed.length}개는 넣지 못해 까닭을 남겼어요` : `${applied.length}개를 넣었어요. 고친 곳만 다시 보기로 풀렸는지 확인할게요`, !!res.failed.length);
    });
    if (recheck && fixRecheckTargets(ep(n)).length) {
      S.fbOpen = 0;
      await startJob('recheck', n);
    }
  },
  async fbUndo(group) {
    const n = chkEp();
    await run('되돌리는 중', async () => {
      await saveIfDirty();
      await flushText(n);
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/fix-groups/${enc(group)}/undo`);
      toast('고침안을 되돌렸어요');
    });
  },
  async fixUndo(group) {
    const n = chkEp();
    const fid = (S.selTool && S.selTool.fid) || chkSelected(n);
    await run('되돌리는 중', async () => {
      await saveIfDirty();
      await flushText(n);
      const before = (ep(n).edits || []).filter((x) => x.group === group && !x.undone).length;
      afterFix(n, fid, await api('POST', `/projects/${enc(S.name)}/episodes/${n}/fix-groups/${enc(group)}/undo`));
      const left = (ep(n).edits || []).filter((x) => x.group === group && !x.undone).length;
      toast(left ? `${before - left}곳을 되돌렸어요. ${left}곳은 그 뒤에 또 고쳐 남겼어요` : '고침안을 되돌렸어요');
    });
  },
  /** 이 지적만 다시 검수. AI 검수 지적은 작업 'recheck_one' 으로 돌고(결과는 JOB_RESULT.recheck_one), 장면 연출 규칙 · 정규식 지적은 AI 없이 바로 판정한다 */
  async chkRecheck(id) {
    const n = chkEp();
    const had = new Set((ep(n).findings || []).map((f) => f.id));
    const origin = ((ep(n).findings || []).find((x) => x.id === id) || {}).origin;
    const regex = origin === 'regex';
    if (origin !== 'rule' && !regex) {
      try {
        await saveIfDirty();
        await flushText(n);
      } catch (err) {
        showError(err);
        return;
      }
      await startJob('recheck_one', n, { target: id }, { quiet: true });
      return;
    }
    await run('판정 다시 보는 중', async () => {
      await saveIfDirty();
      await flushText(n);
      afterFix(n, id, await api('POST', `/projects/${enc(S.name)}/episodes/${n}/findings/${enc(id)}/recheck`));
      const f = ep(n).findings.find((x) => x.id === id);
      const kids = ep(n).findings.filter((x) => !had.has(x.id));
      if (kids.length) {
        S.chkSel[n] = kids[0].id;
        S.chkFilter = 'open';
        afterFix(n, kids[0].id, S.project);  // 고치는 창을 새로 생긴 딸린 지적으로 옮긴다
        toast(`${f.status === 'fixed' ? '풀렸어요. ' : ''}고친 문장 때문에 새로 어긋난 곳 ${kids.length}개를 딸린 지적으로 더했어요`);
      } else if (f.status === 'fixed') {
        toast(regex ? '이 규칙에 더 걸리지 않아요. 고침으로 닫았어요' : '풀렸어요. 고침으로 닫았어요');
      } else if (regex) {
        toast('아직 이 규칙에 걸려요. 처리 기록에 남겼어요', false, { actions: [{ label: '처리 기록 보기', run: showFindingLog }] });
      } else {
        // 다시 검수의 보통 결과라 오류로 띄우지 않는다. 처리 기록으로 가는 버튼을 붙인다
        toast('아직 어긋나요. 처리 기록에 까닭을 남겼어요', false, { actions: [{ label: '처리 기록 보기', run: showFindingLog }] });
      }
    });
  },
});

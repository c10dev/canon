/* 5단계 검수: 한 화의 검수 세션. 회차 띠(누르면 그 회차가 바꾼 지적만, 새 판 구분선) · 처리 상태 거르기,
   왼쪽 지적 목록(탭: 모순 지적 · 초반 점검 · 문체 지표, 심각도 순, 딸린 지적은 부모 아래), 가운데 본문(지적 문장 밑줄, 부분 수정 도구),
   오른쪽 지적 상세(근거 · 심각도 · 처리 상태 · 메모 · 처리 기록). 지적을 누르면 본문이 그 문장으로 옮겨 가고 문장에서 고치는 창이 뜬다
   (passage.js 의 떠 있는 도구, mode 'finding'): AI 고침안 비교와 적용(딸린 곳 포함), 묶음 되돌리기, 이 지적만 다시 검수, 다른 처리 길.
   지적과 회차는 서버 findings.merge 가 만든다 (Episode.findings · rounds). 상태 · 심각도 바꾸기는 PUT …/findings/{id},
   고침안 POST …/findings/{id}/fixes · …/fixes/{k}/apply, 되돌리기 POST …/fix-groups/{묶음}/undo, 다시 검수 POST …/findings/{id}/recheck,
   문체 지표는 GET …/style. app.js 의 S, P, actions, api, render, run, home.js 의 checkState, write.js 의 epNav · widenToggle · nextStepBtn,
   marks.js 의 draftBox · readHtml, passage.js 의 textNow · editableEp · passageNotes · editTime · wordDiff · flushText · focusText · showTool,
   opening.js 의 openingChecks 를 그대로 쓴다. */
'use strict';

Object.assign(S, {
  chkSel: {},          // 화 → 고른 지적 id
  chkFilter: 'open',   // 지적 목록 거르기: open · fixed · kept · wrong · all
  chkRound: {},        // 화 → 고른 회차 번호 (그 회차가 바꾼 지적만 본다). 비면 처리 상태로 거른다
  chkTab: 'issues',    // 왼쪽 칸 탭: issues · opening · style
  chkStyle: {},        // 화 → 문체 지표 { metrics, warnings } 또는 { error }
  chkNote: '',         // 고른 지적의 메모 칸 (저장 전)
  chkNoteFor: '',      // chkNote 가 어느 지적('화:id')의 메모인지
  fixSkip: {},         // '화:id:고침안 번호' → 빼고 넣을 딸린 곳 번호 목록
});

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
/** 장면 연출 규칙 판정이 낸 지적 (schema.ConsistencyIssue.origin). */
const ruleChip = (f) => f.origin === 'rule' ? '<span class="chip" title="장면 연출 규칙 판정이 짚었어요 (AI 검수가 아니에요)">규칙</span>' : '';

/** 규칙 지적의 '장면 연출에서 보기': 그 사건 본문 장면의 그 박자로 (stage.js 의 S.stgJump). */
function stageLink(n, f) {
  if (f.origin !== 'rule' || f.stage_event == null || f.stage_event < 0) return '';
  const ev = f.stage_event + 1;
  return `<div class="row"><a class="btn small ghost" href="${base()}/stage/${n}/${ev}" data-action="stgGo" data-arg="${n}:${ev}:${f.stage_beat || 0}">장면 연출에서 보기 · 사건 ${ev}${f.stage_beat ? ` · ${f.stage_beat}박자` : ''}</a></div>`;
}

/** 검수 때 함께 뽑기 켜기 · 끄기 (Settings.stage_extract, 기본 켬). 작품 설정이라 자동 집필 검수도 따른다. */
function stageToggle() {
  const on = P().settings.stage_extract !== false;
  return `<button type="button" class="btn${on ? ' on' : ''}" aria-pressed="${on}" data-action="toggleStageExtract" title="검수할 때 사건마다 본문에서 장면 연출(자리 · 자세 · 손 · 접촉)을 뽑아 규칙으로 판정해요. 본문이 바뀐 사건만 뽑고, 사건마다 검수 호출이 1번 늘어요">연출 함께 뽑기 ${on ? '켜짐' : '꺼짐'}</button>`;
}

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

function chkStrip(n, e, st) {
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
    const label = `${r.no}회차${r.at ? ` · ${editTime(r.at)}` : ''} · 짚은 ${r.found}${r.no > 1 ? ` · 새로 ${r.added}` : ''}${gone ? ` · 사라짐 ${gone}` : ''}${r.no > 1 && again ? ` · 다시 ${again}` : ''}${r.kept_again ? ` · 결정 그대로 ${r.kept_again}` : ''}${from[r.source] || ''}${r.widen ? ' · 넓혀 찾기' : ''}`;
    return `<button type="button" class="chk-round${r === last ? ' last' : ''}" aria-pressed="${picked === r.no}" data-action="chkRound" data-arg="${r.no}">${label}</button>${r.superseded ? '<span class="chk-break">새 판</span>' : ''}`;
  }).join('');
  const fresh = last.superseded && !e.checked_at;
  return `<div class="chk-strip"><span class="small">회차</span><div class="row" style="gap:6px">${chips}</div>
      <span class="small chk-strip-hint">회차를 누르면 그 회차에 바뀐 지적만 봐요</span>
      <div class="seg chk-filters" role="group" aria-label="처리 상태로 거르기">${filters}</div></div>
    ${fresh ? `<div class="note">${last.no}회차 뒤에 본문을 새 판으로 바꿨어요. 그대로 둠 · 잘못 짚음으로 정한 지적만 남겼어요. 새 판을 검수하세요.</div>`
    : st.stale ? `<div class="note warn">${last.no}회차 뒤에 본문을 고쳤어요. 고친 문장의 지적은 '문장 바뀜'으로 보여요. 고친 곳이 다른 곳과 어긋나지 않는지 보려면 다시 검수하세요.</div>` : ''}`;
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

/** 목록에 보일 지적과 회차 변화: 회차를 골랐으면 그 회차가 바꾼 지적, 아니면 처리 상태로 거른 것. */
function chkShown(n, e) {
  const no = S.chkRound[n] || 0;
  if (no) {
    const ch = roundChanges(e, no);
    return { list: findingOrder(e.findings.filter((f) => ch[f.id])), changes: ch, no };
  }
  return { list: findingOrder(e.findings.filter((f) => S.chkFilter === 'all' || f.status === S.chkFilter)), changes: {}, no: 0 };
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
    const { list, changes, no } = chkShown(n, e);
    const ids = new Set(list.map((f) => f.id));
    const caption = no ? `<div class="between"><strong style="font-size:0.8125rem">${no}회차가 바꾼 지적</strong><button type="button" class="btn small ghost" data-action="chkRound" data-arg="${no}">회차 보기 끄기</button></div>` : '';
    body = list.length ? `${caption}<ul class="chk-list">${list.map((f) => {
      const flag = findingFlag(e, f, text);
      const child = f.parent && ids.has(f.parent);
      return `<li><button type="button" class="chk-item${f.status === 'open' ? '' : ' done'}${child ? ' child' : ''}" aria-current="${f.id === sel}" data-action="chkSel" data-arg="${esc(f.id)}">
        <span class="row" style="gap:4px"><span class="chip ${SEV_CHIP[f.severity] || 'warn'}">${SEVERITY[f.severity] || '보통'}</span><span class="chip">${esc(f.type)}</span>${ruleChip(f)}<span class="chip ${FINDING_CHIP[f.status]}">${FINDING_STATUS[f.status]}</span>${no && changes[f.id] ? `<span class="chip">${ROUND_CHANGE[changes[f.id]]}</span>` : ''}${flag ? `<span class="chip${flag === 'changed' ? ' warn' : ''}">${FINDING_FLAG[flag]}</span>` : ''}${f.parent ? '<span class="chip">고치다 생김</span>' : ''}</span>
        <span class="chk-desc">${esc(f.description)}</span><span class="small">근거 · ${esc(srcLabel(n, f))}</span></button></li>`;
    }).join('')}</ul>`
      : `${caption}<div class="empty" style="padding:16px 8px"><p class="small">${no ? `${no}회차는 지적 목록을 남기지 않은 예전 회차예요.` : S.chkFilter === 'open' ? '열린 지적이 없어요. 상태 승인으로 넘어가도 돼요.' : '이 상태의 지적이 없어요.'}</p></div>`;
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
  if (S.chkNoteFor !== key) { S.chkNoteFor = key; S.chkNote = f.note || ''; }
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
    ${f.source_quote ? `<div class="field"><span class="small">근거 · ${src}</span><blockquote class="chk-quote">${esc(f.source_quote)}</blockquote></div>` : ''}
    ${f.suggestion ? `<div class="field"><span class="small">고칠 방향</span><div style="font-size:0.8125rem;line-height:1.55">→ ${esc(f.suggestion)}</div></div>` : ''}
    ${spot && can ? `<div class="row"><button type="button" class="btn small" data-action="chkOpen" data-arg="${esc(f.id)}">문장에서 고치기</button>${f.status === 'open' ? `<button type="button" class="btn small" data-action="chkRecheck" data-arg="${esc(f.id)}"${f.origin === 'rule' ? ' title="AI를 부르지 않고 지금 본문 장면으로 판정만 다시 해요"' : ''}>${f.origin === 'rule' ? '판정 다시 보기' : '이 지적만 다시 검수'}</button>` : ''}</div>` : ''}
    ${stageLink(n, f)}
    <div class="field"><span class="small">심각도 · AI가 정하고 작가가 바꿔요</span><div class="seg chk-seg3" role="group" aria-label="심각도">${sev}</div></div>
    <div class="field"><span class="small">처리</span><div class="seg chk-seg" role="group" aria-label="처리 상태">${seg}</div></div>
    ${decided ? `<div class="field"><label class="small" for="chk-note">왜 ${FINDING_STATUS[f.status]}인지 적어 두면 다시 나와도 바로 알아볼 수 있어요</label>
      <textarea id="chk-note" rows="2" data-local="chkNote">${esc(S.chkNote)}</textarea>
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
  const ways = `<div class="fix-ways">
      <div class="fix-way"><strong>근거 쪽이 틀렸어요</strong><span class="small">근거(${esc(srcLabel(n, f))})를 고치는 게 맞으면 그곳으로 가요</span>${f.source_episode && f.source_episode !== n ? `<a class="btn small" href="${base()}/write/${f.source_episode}">${f.source_episode}화 본문 열기</a>` : f.source_episode === n ? '<span class="small">같은 화 앞 문장이에요. 본문에서 바로 고치세요</span>' : `<a class="btn small" href="${base()}/setup">설정 열기</a>`}</div>
      <div class="fix-way"><strong>일부러 그렇게 썼어요</strong><span class="small">그대로 둠으로 두고 이유를 남겨요. 다시 나와도 결정이 지켜져요</span><button type="button" class="btn small" data-action="setFinding" data-arg="${esc(f.id)}:kept"${busy ? ' disabled' : ''}>그대로 둠</button></div>
      <div class="fix-way"><strong>AI가 잘못 짚었어요</strong><span class="small">모순이 아니에요. 다시 나와도 결정이 지켜져요</span><button type="button" class="btn small" data-action="setFinding" data-arg="${esc(f.id)}:wrong"${busy ? ' disabled' : ''}>잘못 짚음</button></div>
    </div>`;
  const tools = `<div class="row"><button type="button" class="btn small" data-action="fixGet" data-arg="${esc(f.id)}"${busy ? ' disabled' : ''}>${fixes.length ? '고침안 다시 받기' : 'AI 고침안 받기'}</button>
      <button type="button" class="btn small" data-action="selManual">직접 고치기</button>${f.suggestion ? `<button type="button" class="btn small" data-action="issueAsk" data-arg="${esc(f.id)}">대화로 고치기</button>` : ''}</div>`;
  const done = applied ? `<div class="note info fix-done"><span>고침안을 넣었어요. 고친 문장이 다른 곳과 어긋나지 않는지 이 지적만 다시 물어볼 수 있어요.</span>
      <span class="row" style="gap:6px"><button type="button" class="btn small" data-action="fixUndo" data-arg="${esc(f.fix_group)}"${busy ? ' disabled' : ''}>한 번에 되돌리기</button><button type="button" class="btn small" data-action="chkRecheck" data-arg="${esc(f.id)}"${busy ? ' disabled' : ''}>이 지적만 다시 검수</button></span></div>` : '';
  const list = fixes.length && !applied
    ? `<span class="small">본문을 고칠게요 · AI 고침안 ${fixes.length}개</span><ol class="fix-list">${fixes.map((o, k) => fixOptionHtml(n, e, f, o, k, text, busy)).join('')}</ol>` : '';
  return `${head}${done}${list}${applied ? '' : tools}${ways}`;
}

function viewCheck(n) {
  const e = ep(n);
  if (!e) return header('5단계', stepLabel('check'), '') + noEpisode();
  const st = checkState(e);
  const rounds = e.rounds || [];
  const last = rounds[rounds.length - 1];
  const b = jobBtn('check', n, last ? `다시 검수 · ${last.no + 1}회차` : '검수하기');
  // 주 버튼은 한 화면에 하나, 머리 줄 오른쪽 끝에 둔다 (디자인 시스템 Button). 검수 전에는 빈 목록의 '검수하기'가 주 버튼이라 머리에 두지 않는다
  const checkPrimary = !last || st.stale || !st.checked;
  // 첫 검수는 flow.js flowCheck: 상태 변경안도 함께 만든다 (켰을 때). 다시 검수는 검수만
  const checkBtn = `<button class="btn${checkPrimary ? ' primary' : ''}" data-action="${last ? 'checkEp' : 'flowCheck'}" data-arg="${n}"${e.text && !autoOn() ? b.attr : ' disabled'}>${b.label}</button>`;
  const toReview = e.status === 'written'
    ? `<a class="btn${checkPrimary ? '' : ' primary'}" href="${base()}/review/${n}">상태 승인으로${st.open ? ` · 열린 지적 ${st.open}` : ''}</a>`
    : e.status === 'finalized' && !checkPrimary ? nextStepBtn() : '';  // 반영 끝난 화도 검수가 지금 할 일이면 다음 할 일 버튼은 두지 않는다
  const lead = `${serial() ? widenToggle(false) : ''}${stageToggle()}${S.mode === 'brief' ? `<a class="btn" href="${base()}/brief/${n}" data-action="openCheckBrief" data-arg="${n}">검수 지시서</a>` : ''}`;
  const right = !e.text ? '' : !last ? lead + toReview : checkPrimary ? lead + toReview + checkBtn : lead + checkBtn + toReview;
  const head = `<header class="page-head"><div class="row" style="gap:12px">${epNav('check', n)}<div class="lead" style="gap:2px"><div class="eyebrow">${flowEyebrow(n)}</div><h1 style="font-size:1.5rem">${n}화 ${esc(e.plot.title)}</h1></div><span class="chip ${e.status}">${STATUS[e.status]}</span></div><div class="row">${right}</div></header>
    ${flowBar(n, 'check')}${autoLockNote()}`;
  if (!e.text) {
    return head + `<div class="card empty"><p>${n}화 본문이 아직 없어요. 본문을 쓴 뒤 검수해요.</p><a class="btn primary" href="${base()}/write/${n}">${n}화 집필로</a></div>`;
  }
  const text = textNow(n);
  const sel = chkSelected(n);
  const editable = editableEp(e);
  const center = editable ? draftBox(n, text) : `<div class="read" data-read="${n}">${readHtml(n, text)}</div>`;
  const notes = passageNotes(n);
  // 본문이 왼쪽 넓은 칸, 지적 목록과 상세는 오른쪽 칸에 쌓는다 (집필 · 상태 승인 단계와 같은 자리). 좁은 폭은 목록 → 상세 → 본문 순서
  return head + chkStrip(n, e, st) + `<div class="check-cols">
      <div class="c-side">${chkList(n, e, text, sel, checkBtn)}
      ${chkDetail(n, e, text, sel)}</div>
      <section class="card w-body c-body" style="padding:0;gap:0" aria-label="본문">
        <div class="w-bar"><span class="w-count"><strong style="color:var(--text)">${text.length.toLocaleString()}</strong> / ${Number(P().meta.words_per_episode).toLocaleString()}자</span>
          ${editable ? '<div class="savebar-slot"></div>' : '<span class="w-fill"></span>'}
          <p class="small w-hint">${editable ? '지적을 고르면 본문이 그 문장으로 옮겨 가고, 문장에서 고치는 창이 떠요' : '읽기 전용 본문이에요'}</p></div>
        ${notes ? `<div style="padding:12px 16px 0;display:flex;flex-direction:column;gap:8px">${notes}</div>` : ''}
        <div class="prose">${center}</div>
      </section>
    </div>
    ${editable ? chatPanel(`text:${n}`) : ''}`;
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

async function chkPut(n, id, body) {
  try {
    takeCheck(n, await api('PUT', `/projects/${enc(S.name)}/episodes/${n}/findings/${enc(id)}`, body));
  } catch (err) {
    toast(err.message, true);
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

Object.assign(actions, {
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
    await chkPut(n, id, { status });
    if (next) S.chkSel[n] = next.id;
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
    await chkPut(n, id, { note: S.chkNote });
    S.chkNoteFor = '';
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
  async fixGet(id) {
    const n = chkEp();
    await run('고침안을 받는 중', async () => {
      await saveIfDirty();
      await flushText(n);
      Object.keys(S.fixSkip).filter((k) => k.startsWith(`${n}:${id}:`)).forEach((k) => delete S.fixSkip[k]);
      afterFix(n, id, await api('POST', `/projects/${enc(S.name)}/episodes/${n}/findings/${enc(id)}/fixes`));
    });
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
        if (!/그대로 두기로 정한 지적/.test(err.message) || !confirm(err.message.replace(/ 그래도 적용하려면.*$/, ' 그래도 넣을까요?'))) throw err;
        pj = await api('POST', url, { skip, confirm: true });
      }
      afterFix(n, id, pj);
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
  async chkRecheck(id) {
    const n = chkEp();
    const had = new Set((ep(n).findings || []).map((f) => f.id));
    await run('이 지적만 다시 검수하는 중', async () => {
      await saveIfDirty();
      await flushText(n);
      afterFix(n, id, await api('POST', `/projects/${enc(S.name)}/episodes/${n}/findings/${enc(id)}/recheck`));
      const f = ep(n).findings.find((x) => x.id === id);
      const kids = ep(n).findings.filter((x) => !had.has(x.id));
      if (kids.length) {
        S.chkSel[n] = kids[0].id;
        S.chkFilter = 'open';
        afterFix(n, kids[0].id, S.project);  // 고치는 창을 새로 생긴 딸린 지적으로 옮긴다
        toast(`${f.status === 'fixed' ? '풀렸어요. ' : ''}고친 문장 때문에 새로 어긋난 곳 ${kids.length}개를 딸린 지적으로 더했어요`, true);
      } else {
        toast(f.status === 'fixed' ? '풀렸어요. 고침으로 닫았어요' : '아직 어긋나요. 처리 기록에서 까닭을 보세요', f.status !== 'fixed');
      }
    });
  },
});

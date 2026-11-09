/* 규칙 묶음: 작품 밖 화면 #/rules[/new|/<묶음 id>] 와 작품 화면의 '규칙으로 N곳 고쳤어요' 알림 · 되돌리기.
   서버는 canon/regexrules.py, 라우트는 canon/routes/regexrules.py (/api/rules, …/rule-bundles, …/rule-runs).
   묶음 편집은 S.ruleB 에 고치고 '저장'을 눌러야 서버에 간다(S.ruleDirty, app.js leaveUnsaved 가 떠날 때 묻는다).
   규칙의 찾을 정규식은 서버와 같은 JSON 키 in 을 쓴다. PUT 은 규칙마다 id 를 그대로 돌려보낸다 (버전 비교가 id 로 규칙을 맞춘다).
   작품에서 켤 묶음은 설정 대화상자(settings.js '정규식 규칙')가 PUT …/rule-bundles 로 바꾼다. */
'use strict';

Object.assign(S, {
  ruleList: null,      // GET /rules 의 묶음 요약 (작품 밖 사이드바 수도 이것)
  ruleB: null,         // 고치는 묶음 { id?, name, notes, rules, used_by, notices, version }
  ruleDirty: false,    // 저장하지 않은 묶음 변경
  ruleVersions: null,  // GET /rules/{id}/versions
  ruleNote: '',        // 다음 저장의 버전 메모 (data-local)
  ruleErr: '',         // 저장을 막은 서버 검사 문구 (줄마다 규칙 이름 · 이유)
  ruleTestText: '',    // 시험 칸에 붙여 넣은 글 (data-local)
  ruleTestProj: '',    // 시험할 작품 (data-local)
  ruleTestEp: '',      // 시험할 화 (data-local)
  ruleTest: null,      // 시험 결과 { text, changes, hits, exported, skipped } 또는 { error }
  ruleRunOpen: '',     // 집필 화면에서 바뀐 곳을 되돌린 걸기 '작품:화:걸기 id' (다시 그려도 편 채로)
});

DRAFT_ROOTS.ruleB = () => S.ruleB;

// 규칙 걸기 한 번의 종류 (schema.RuleRunKind)
const RULE_KIND = { write: '쓰기', rewrite: '새 판', polish: '서술 다듬기', passage: '부분 수정', import: '붙여 넣기', auto: '자동 집필', adopt: '비교 채택', rework: '재구성 다듬기' };

// ---------- 작품 화면에서 쓰는 순수 함수 (tests/test_regexrules_js.py) ----------

/** 시간 한도로 건너뛴 걸기의 알림 글 */
function ruleSkipSay(name) {
  return `규칙 묶음 ${name}${josa(name, '을', '를')} 거는 데 너무 오래 걸려서 건너뛰었어요`;
}

/** 걸기 한 번(RuleRun)을 알림 한 문장으로: 고친 곳 수, 건너뛴 묶음. 없으면 빈 글 */
function ruleRunSay(run) {
  if (!run) return '';
  const n = (run.changes || []).length;
  return [n ? `규칙으로 ${n}곳 고쳤어요.` : '', run.skipped ? `${ruleSkipSay(run.skipped)}.` : ''].filter(Boolean).join(' ');
}

/** 규칙이 바꾼 곳들(RuleChange[], 부분 수정 후보 · 재구성 다듬기 제안의 ruled)을 한 줄로: 곳 수와 규칙 이름 */
function ruledLine(ruled) {
  const list = ruled || [];
  if (!list.length) return '';
  const names = [...new Set(list.map((c) => c.name || '이름 없는 규칙'))];
  return `규칙으로 ${list.length}곳 고쳤어요 · ${names.join(', ')}`;
}

/** 바뀐 글 한 조각을 보이게: 줄바꿈은 ↵, 빈 글은 (지움) */
function ruleBit(t) {
  return t ? esc(t).replace(/\n/g, '↵') : '<span class="muted">(지움)</span>';
}

/** 바뀐 곳 하나: 규칙 이름 · 전 → 뒤 */
function ruleChangeHtml(c) {
  return `<span class="rx-name">${esc(c.name || '이름 없는 규칙')}</span><span class="rx-diff"><del>${ruleBit(c.before)}</del> → <ins>${ruleBit(c.after)}</ins></span>`;
}

/** 집필 화면 알림: 걸기마다 접은 '규칙으로 N곳 고쳤어요'(최근 것 먼저), 펴면 바뀐 곳마다 되돌리기와 모두 되돌리기.
    가장 최근 걸기를 시간 한도로 건너뛰었으면 경고 한 줄. can 이 거짓이면(자동 집필 중 · 고칠 수 없는 화) 보기만 */
function ruleRunsNote(n, can) {
  const e = ep(n);
  const runs = (e && e.rule_runs) || [];
  if (!runs.length) return '';
  const last = runs[runs.length - 1];
  const skip = last.skipped ? `<div class="note warn" role="status">${esc(ruleSkipSay(last.skipped))}. 이번 본문은 규칙을 걸기 전 그대로예요.</div>` : '';
  const live = runs.filter((r) => (r.changes || []).some((c) => !c.undone)).reverse();
  const notes = live.map((r) => {
    const left = r.changes.filter((c) => !c.undone).length;
    const rows = r.changes.map((c, k) => `<li class="rx-change${c.undone ? ' undone' : ''}">${ruleChangeHtml(c)}
      ${c.undone ? '<span class="chip">되돌림</span>' : can ? `<button type="button" class="btn small" data-action="ruleUndo" data-arg="${n}:${esc(r.id)}:${k}">되돌리기</button>` : ''}</li>`).join('');
    const back = r.changes.length - left;
    const open = S.ruleRunOpen === `${S.name}:${n}:${r.id}` ? ' open' : '';  // 되돌린 뒤 다시 그려도 편 채로 둔다
    return `<details class="note plain rx-run"${open}><summary><span>규칙으로 ${r.changes.length}곳 고쳤어요<span class="small"> · ${esc(RULE_KIND[r.kind] || r.kind)}${r.at ? ` · ${fmtDateTime(r.at)}` : ''}${back ? ` · ${back}곳 되돌림` : ''}</span></span></summary>
      <ul class="rx-changes">${rows}</ul>
      ${can && left > 1 ? `<div class="row"><button type="button" class="btn small" data-action="ruleUndoAll" data-arg="${n}:${esc(r.id)}">모두 되돌리기</button></div>` : ''}</details>`;
  }).join('');
  return skip + notes;
}

// ---------- 규칙 묶음 화면 ----------

/** 새 규칙. id 는 화면에서 정해 두고 저장할 때 그대로 보낸다 */
function ruleBlank() {
  const id = Array.from({ length: 8 }, () => '0123456789abcdef'[Math.floor(Math.random() * 16)]).join('');
  return { id, comment: '', in: '', out: '', type: 'output', flag: 'g', action: 'warn', enabled: true };
}

/** 저장 요청 몸통 (POST · PUT /rules) */
function ruleBody(b, note = '') {
  return { name: b.name, notes: b.notes || '', rules: b.rules.map((r) => ({ ...r })), note };
}

/** 목록 칩 글자: 경고 · 고침 · 내보내기 수 (요약의 fix 에는 내보내기 규칙도 든다) */
function ruleCounts(x) {
  const out = [`경고 ${x.warn}`, `고침 ${x.fix - x.export}`];
  if (x.export) out.push(`내보내기 ${x.export}`);
  return out;
}

async function ruleLoad(id) {
  S.ruleList = await api('GET', '/rules');
  S.ruleErr = '';
  const was = S.ruleB && (S.ruleB.id || 'new');
  if (!id) {
    S.ruleB = null;
    S.ruleVersions = null;
    S.ruleDirty = false;
    return;
  }
  if (id === 'new') {
    S.ruleB = { name: '', notes: '', rules: [ruleBlank()], used_by: [], notices: [] };
    S.ruleVersions = null;
  } else {
    S.ruleB = await api('GET', `/rules/${enc(id)}`);
    S.ruleVersions = await api('GET', `/rules/${enc(id)}/versions`).catch(() => null);
  }
  if (!S.projects) S.projects = await api('GET', '/projects').catch(() => null);
  S.ruleDirty = false;
  if (was !== id) { S.ruleTest = null; S.ruleNote = ''; }
}

function viewRuleList() {
  const list = S.ruleList || [];
  const cards = list.map((x) => `<article class="card tight">
      <div class="between"><h3><a href="#/rules/${esc(x.id)}" style="color:inherit;text-decoration:none">${esc(x.name)}</a></h3><span class="small">${fmtDate(x.updated_at)}</span></div>
      <div class="row">${ruleCounts(x).map((t) => `<span class="chip">${t}</span>`).join('')}<span class="chip">켠 작품 ${x.used_by}</span></div>
      ${x.notes ? `<div class="small" style="white-space:pre-line">${esc(x.notes)}</div>` : ''}
      <div class="row"><a class="btn small" href="#/rules/${esc(x.id)}">열기</a><button type="button" class="btn small danger" data-action="ruleDelete" data-arg="${esc(x.id)}">지우기</button></div>
    </article>`).join('');
  return `${header('Canon', '규칙 묶음', '정규식 규칙을 묶음으로 모아 두고 작품마다 켤 묶음을 골라요. 고침 규칙은 AI가 쓴 본문을 작가가 보기 전에 바꾸고, 바꾼 곳은 모두 남아 집필 화면에서 되돌릴 수 있어요. 경고 규칙은 본문을 바꾸지 않고 검수 결과에 걸린 곳을 더해요. 켜기는 작품 설정의 집필 · 검수 갈래에서 해요.', list.length ? '<a class="btn primary" href="#/rules/new">+ 새 묶음 만들기</a>' : '')}
    ${list.length ? `<div class="grid-auto">${cards}</div>` : '<div class="card empty"><div>아직 만든 규칙 묶음이 없어요.</div><div class="small">말줄임표 표기 통일, 영어 따옴표 바꾸기처럼 늘 같은 고침을 규칙으로 적어 두세요.</div><a class="btn primary" href="#/rules/new">+ 새 묶음 만들기</a></div>'}`;
}

/** 규칙 하나의 편집 칸 */
function ruleCard(r, i, total) {
  const o = { root: 'ruleB' };
  const b = `rules.${i}`;
  const seg = (field, opts, label) => `<div class="seg" role="group" aria-label="${i + 1}번 규칙 ${label}">${opts.map(([v, l, off]) => `<button type="button" aria-pressed="${r[field] === v}" data-action="ruleSet" data-arg="${i}:${field}:${v}"${off ? ' disabled title="내보내기 규칙은 고침만 돼요"' : ''}>${l}</button>`).join('')}</div>`;
  const fix = r.action === 'fix';
  return `<li class="card tight rx-rule${r.enabled ? '' : ' off'}" id="rx-rule-${i}">
    <div class="between"><strong id="rx-rule-title-${i}">${i + 1}. ${esc(r.comment || '이름 없는 규칙')}</strong>
      <span class="row" style="gap:6px">
        <button type="button" class="btn small icon-btn" data-action="ruleMove" data-arg="${i}:-1"${i === 0 ? ' disabled' : ''} aria-label="${i + 1}번 규칙 위로">↑</button>
        <button type="button" class="btn small icon-btn" data-action="ruleMove" data-arg="${i}:1"${i === total - 1 ? ' disabled' : ''} aria-label="${i + 1}번 규칙 아래로">↓</button>
        <button type="button" class="btn small icon-btn danger" data-action="ruleRemove" data-arg="${i}" aria-label="${i + 1}번 규칙 지우기">✕</button></span></div>
    <div class="grid-2">${input('이름', `${b}.comment`, { ...o, placeholder: '예: 말줄임표 통일' })}
      ${input('플래그', `${b}.flag`, { ...o, cls: 'rx-mono', hint: 'g 모두 · i 대소문자 · m 줄마다 · s 줄바꿈 포함', placeholder: 'g' })}</div>
    ${input('찾을 정규식', `${b}.in`, { ...o, cls: 'rx-mono', hint: '500자까지 · 한글은 [가-힣]', placeholder: '예: \\.{3}' })}
    ${fix ? input('바꿀 글', `${b}.out`, { ...o, cls: 'rx-mono', hint: '$1 · $& 로 찾은 글을 넣어요 · 비우면 지워요', placeholder: '예: …' }) : ''}
    <div class="row rx-opts">
      ${seg('action', [['warn', '경고', r.type === 'export'], ['fix', '고침']], '동작')}
      ${seg('type', [['output', '쓴 본문'], ['export', '내보내기']], '거는 곳')}
      <label class="rx-on"><input type="checkbox" data-rule-on="${i}"${r.enabled ? ' checked' : ''}> 켬</label>
    </div>
    <div class="small">${r.type === 'export' ? '내보낼 때만 걸고 저장한 본문은 바꾸지 않아요.' : fix ? 'AI가 쓴 본문을 저장하기 전에 바꾸고 바꾼 곳을 남겨요.' : '본문은 그대로 두고 검수 결과에 걸린 문장을 더해요.'}</div>
  </li>`;
}

/** 시험 칸: 붙여 넣은 글이나 작품의 한 화에 지금 칸의 규칙을 걸어 본다 (저장하지 않음) */
function ruleTestCard() {
  const projs = (S.projects || []).filter((x) => !x.play);
  const t = S.ruleTest;
  let out = '';
  if (t && t.error) out = `<div class="note warn" role="alert" style="white-space:pre-line">${esc(t.error)}</div>`;
  else if (t) {
    const ch = t.changes.length ? `<ul class="rx-changes">${t.changes.map((c) => `<li class="rx-change">${ruleChangeHtml(c)}</li>`).join('')}</ul>` : '<div class="small">고친 곳이 없어요.</div>';
    const hits = t.hits.length ? `<ul class="rx-changes">${t.hits.map((h) => `<li class="rx-change"><span class="rx-name">${esc(h.description)}</span><span class="rx-diff">${esc(h.current_quote)}</span></li>`).join('')}</ul>` : '<div class="small">걸린 곳이 없어요.</div>';
    out = `<div class="rx-result" role="status" tabindex="-1">
      ${t.skipped ? `<div class="note warn">${esc(ruleSkipSay(t.skipped))}.</div>` : ''}
      <div class="field"><span class="small">고침 · ${t.changes.length}곳</span>${ch}</div>
      <div class="field"><span class="small">경고 · ${t.hits.length}곳</span>${hits}</div>
      <details><summary class="small">고친 글 보기</summary><div class="rw-text">${esc(t.text)}</div></details>
      ${t.exported !== t.text ? `<details><summary class="small">내보내기 규칙까지 건 글 보기</summary><div class="rw-text">${esc(t.exported)}</div></details>` : ''}
    </div>`;
  }
  return `<section class="card tight" id="rx-test" aria-labelledby="rx-test-h">
    <div class="between"><h2 id="rx-test-h">시험</h2><span class="small">지금 칸의 규칙을 걸어 봐요. 저장하지 않아요</span></div>
    <div class="field"><label for="rx-test-text">걸어 볼 글</label><textarea id="rx-test-text" rows="5" data-local="ruleTestText" placeholder="글을 붙여 넣거나, 비우고 아래에서 작품의 한 화를 고르세요">${esc(S.ruleTestText || '')}</textarea></div>
    ${projs.length ? `<div class="row" style="flex-wrap:nowrap"><select id="rx-test-proj" data-local="ruleTestProj" aria-label="시험할 작품" style="flex:1;min-width:0"><option value="">작품 고르기</option>${projs.map((x) => `<option value="${esc(x.name)}"${S.ruleTestProj === x.name ? ' selected' : ''}>${esc(x.title || x.name)}</option>`).join('')}</select>
      <input id="rx-test-ep" type="number" min="1" data-local="ruleTestEp" value="${esc(S.ruleTestEp || '')}" aria-label="시험할 화" placeholder="화" style="width:88px;flex:none"></div>` : ''}
    <div class="row"><button type="button" class="btn" data-action="ruleTry">걸어 보기</button></div>
    ${out}
  </section>`;
}

function ruleVersionsCard() {
  const vs = S.ruleVersions || [];
  const names = (label, list, del = false) => (list.length ? `<div class="small"><strong>${label}</strong> ${list.map((x) => (del ? `<del>${esc(x)}</del>` : esc(x))).join(', ')}</div>` : '');
  const rows = vs.map((v) => `<li class="version-row">
      <div class="between"><span><strong>${v.number}번</strong> <span class="small">${fmtDate(v.at)} · 규칙 ${v.rules}개</span>${v.current ? ' <span class="chip finalized">지금</span>' : ''}</span>
        ${v.current ? '' : `<button type="button" class="btn small" data-action="ruleRestore" data-arg="${v.number}">이 버전으로 되돌리기</button>`}</div>
      <div class="small">${esc(v.note)}</div>
      ${names('더함', v.added)}${names('뺌', v.removed, true)}${names('고침', v.changed)}
    </li>`).join('');
  return `<section class="card tight" id="rx-versions">
    <div class="between"><h2>버전</h2><span class="small">규칙이 바뀔 때마다 남겨요 (최근 30개)</span></div>
    <div class="field"><label for="rx-note">다음 저장의 버전 메모 <span class="hint">비우면 더한 · 뺀 · 고친 규칙 이름을 적어요</span></label>
      <input id="rx-note" type="text" data-local="ruleNote" value="${esc(S.ruleNote || '')}" placeholder="예: 따옴표 규칙을 내보내기로 옮김"></div>
    ${rows ? `<ul class="version-list">${rows}</ul>` : '<div class="small">아직 버전이 없어요.</div>'}
  </section>`;
}

function viewRuleBundle() {
  const b = S.ruleB;
  const isNew = !b.id;
  const used = b.used_by || [];
  const right = `<a class="btn" href="#/rules">목록으로</a>${isNew ? '' : `<button type="button" class="btn danger" data-action="ruleDelete" data-arg="${esc(b.id)}">지우기</button><button type="button" class="btn" data-action="ruleRevert"${S.ruleDirty ? '' : ' disabled'}>저장 전으로 되돌리기</button>`}<button type="button" class="btn primary" data-action="ruleSave">저장</button>`;
  const err = S.ruleErr ? `<div class="note warn" role="alert" style="white-space:pre-line">${esc(S.ruleErr)}</div>` : '';
  const notices = (b.notices || []).length ? `<div class="note info">${b.notices.map((x) => `<div>${esc(x)}</div>`).join('')}</div>` : '';
  return `${header('규칙 묶음', isNew ? '새 묶음' : b.name || '이름 없음', isNew ? '규칙을 적고 저장하세요. 저장한 뒤 작품 설정에서 켜요.' : `만든 날 ${fmtDate(b.created_at)} · 고친 날 ${fmtDate(b.updated_at)} · ${b.version}번 버전`, right)}
    <div class="rx-page">
      <p class="small" id="rx-dirty" role="status">${S.ruleDirty ? '저장하지 않은 변경이 있어요' : ''}</p>
      ${err}${notices}
      <section class="card tight">
        ${input('묶음 이름', 'name', { root: 'ruleB', placeholder: '예: 표기 통일' })}
        ${input('메모', 'notes', { root: 'ruleB', rows: 1, autogrow: true, placeholder: '어떤 규칙을 모았는지 등' })}
        ${isNew ? '' : `<div class="small">${used.length ? `켠 작품: ${used.map((n) => `<a href="#/p/${enc(n)}">${esc(n)}</a>`).join(', ')}. 저장하면 다음 쓰기부터 그 작품들에 걸려요.` : '아직 켠 작품이 없어요. 작품 설정의 집필 · 검수 갈래에서 켜요.'}</div>`}
      </section>
      <section aria-labelledby="rx-rules-h">
        <div class="between"><h2 id="rx-rules-h">규칙 ${b.rules.length}개</h2><span class="small">위에서부터 차례로 걸고, 앞 규칙이 고친 글에 뒤 규칙이 걸려요</span></div>
        <ol class="rx-rules">${b.rules.map((r, i) => ruleCard(r, i, b.rules.length)).join('')}</ol>
        <div class="row"><button type="button" class="btn" data-action="ruleAdd">+ 규칙 더하기</button></div>
      </section>
      ${ruleTestCard()}
      ${isNew ? '' : ruleVersionsCard()}
    </div>`;
}

/** 저장하지 않은 변경 표시만 고친다 (글자를 칠 때마다 다시 그리지 않는다) */
function ruleDirtyMark() {
  const el = $('#rx-dirty');
  if (el) el.textContent = S.ruleDirty ? '저장하지 않은 변경이 있어요' : '';
  const rb = $('[data-action="ruleRevert"]');
  if (rb) rb.disabled = !S.ruleDirty;
}

function ruleChanged() {
  S.ruleDirty = true;
  render();
}

document.addEventListener('input', (e) => {
  const el = e.target;
  if (S.route[0] !== 'rules' || !S.ruleB || !el.dataset || el.dataset.root !== 'ruleB') return;
  S.ruleDirty = true;  // 값은 app.js 의 입력 바인딩이 DRAFT_ROOTS.ruleB 에 적었다
  ruleDirtyMark();
  const m = (el.dataset.bind || '').match(/^rules\.(\d+)\.comment$/);
  const title = m && document.getElementById(`rx-rule-title-${m[1]}`);  // 규칙 카드 제목 줄만 고친다
  if (title) title.textContent = `${Number(m[1]) + 1}. ${el.value || '이름 없는 규칙'}`;
});
document.addEventListener('change', (e) => {
  const el = e.target;
  if (S.route[0] !== 'rules' || !S.ruleB || !el.dataset) return;
  if (el.dataset.ruleOn != null) {
    const r = S.ruleB.rules[Number(el.dataset.ruleOn)];
    if (r) { r.enabled = el.checked; ruleChanged(); }
  }
});

Object.assign(actions, {
  ruleAdd() {
    S.ruleB.rules.push(ruleBlank());
    ruleChanged();
    focusEl($(`#f-rules-${S.ruleB.rules.length - 1}-comment`));
  },
  async ruleRemove(i) {
    const r = S.ruleB.rules[Number(i)];
    if (!r) return;
    const name = r.comment || `${Number(i) + 1}번 규칙`;
    const back = S.ruleB.id ? " 저장하기 전에는 '저장 전으로 되돌리기'로 되살릴 수 있어요." : '';
    if ((r.in || r.comment) && !(await askConfirm(`'${name}'${josa(name, '을', '를')} 지울까요?${back}`, { ok: '지우기', danger: true }))) return;
    S.ruleB.rules.splice(Number(i), 1);
    ruleChanged();
  },
  ruleMove(arg) {
    const [i, d] = arg.split(':').map(Number);
    const rs = S.ruleB.rules;
    const j = i + d;
    if (j < 0 || j >= rs.length) return;
    [rs[i], rs[j]] = [rs[j], rs[i]];
    ruleChanged();
    focusEl($(`[data-action="ruleMove"][data-arg="${j}:${d}"]`) || $(`#rx-rule-${j} button`));
  },
  ruleSet(arg) {
    const [i, field, v] = arg.split(':');
    const r = S.ruleB.rules[Number(i)];
    if (!r || r[field] === v) return;
    if (field === 'action' && v === 'warn' && r.type === 'export') return;  // 내보내기 규칙은 경고로 바꿀 수 없다 (화면에서도 막는다)
    r[field] = v;
    if (field === 'type' && v === 'export') r.action = 'fix';  // 내보내기 규칙은 고침만 된다 (서버 검사와 같다)
    ruleChanged();
  },
  async ruleSave() {
    const b = S.ruleB;
    if (!b.name.trim()) return toast('묶음 이름을 입력하세요', true);
    const isNew = !b.id;
    let res;
    const ok = await run('저장하는 중', async () => {
      try {
        res = isNew ? await api('POST', '/rules', ruleBody(b, S.ruleNote)) : await api('PUT', `/rules/${enc(b.id)}`, ruleBody(b, S.ruleNote));
      } catch (e) {
        if (e.status !== 400) throw e;
        S.ruleErr = e.message;  // 규칙 검사에 걸렸다: 이유를 화면 위에 그대로 둔다
        return;
      }
      S.ruleErr = '';
      S.ruleB = res;
      S.ruleDirty = false;
      S.ruleNote = '';
      S.ruleVersions = await api('GET', `/rules/${enc(res.id)}/versions`).catch(() => null);
      S.ruleList = await api('GET', '/rules').catch(() => S.ruleList);
    });
    if (!ok) return;
    if (!res) {
      toast('저장하지 못했어요. 화면 위의 이유를 보고 고치세요', true);
      window.scrollTo(0, 0);
      return;
    }
    toast(isNew ? '규칙 묶음을 만들었어요' : `저장했어요 (지금 ${res.version}번 버전)`);
    if (isNew) location.hash = `#/rules/${res.id}`;
  },
  async ruleRevert() {
    if (!S.ruleDirty || !S.ruleB.id) return;
    if (!(await askConfirm('저장하지 않은 변경을 버리고 저장된 묶음으로 되돌릴까요?', { ok: '되돌리기', danger: true }))) return;
    await run('불러오는 중', async () => {
      S.ruleB = await api('GET', `/rules/${enc(S.ruleB.id)}`);
      S.ruleDirty = false;
      S.ruleErr = '';
    });
  },
  async ruleDelete(id) {
    const b = (S.ruleList || []).find((x) => x.id === id) || S.ruleB || {};
    const used = S.ruleB && S.ruleB.id === id ? (S.ruleB.used_by || []).length : b.used_by || 0;
    const note = used ? `\n켠 작품 ${used}곳에는 '찾을 수 없는 묶음'으로 남고 규칙은 더 걸리지 않아요. 이미 고친 본문과 기록은 그대로예요.` : '';
    if (!(await askConfirm(`'${b.name}' 규칙 묶음을 지울까요? 되돌릴 수 없어요.${note}`, { ok: '지우기', danger: true }))) return;
    await run('지우는 중', async () => {
      await api('DELETE', `/rules/${enc(id)}`);
      S.ruleDirty = false;
      S.ruleList = await api('GET', '/rules');
      toast('지웠어요');
      if (S.route[0] === 'rules' && S.route[1]) location.hash = '#/rules';
    });
  },
  async ruleRestore(n) {
    const msg = S.ruleDirty ? '\n저장하지 않은 변경은 사라져요.' : '';
    if (!(await askConfirm(`${n}번 버전으로 되돌릴까요? 지금 규칙도 버전으로 남아 있어 다시 돌아올 수 있어요.${msg}`, { ok: '되돌리기' }))) return;
    await run('되돌리는 중', async () => {
      S.ruleB = await api('POST', `/rules/${enc(S.ruleB.id)}/versions/${n}/restore`);
      S.ruleDirty = false;
      S.ruleErr = '';
      S.ruleVersions = await api('GET', `/rules/${enc(S.ruleB.id)}/versions`).catch(() => null);
      toast(`${n}번 버전으로 되돌렸어요 (지금 ${S.ruleB.version}번 버전)`);
    });
  },
  async ruleTry() {
    const text = S.ruleTestText || '';
    const body = { rules: ruleBody(S.ruleB).rules, bundle: S.ruleB.id || '', text };
    if (!text.trim()) {
      if (!S.ruleTestProj || !Number(S.ruleTestEp)) return toast('걸어 볼 글을 붙여 넣거나 작품과 화를 고르세요', true);
      Object.assign(body, { project: S.ruleTestProj, episode: Number(S.ruleTestEp) });
    }
    await run('규칙을 걸어 보는 중', async () => {
      try {
        S.ruleTest = await api('POST', '/rules/test', body);
      } catch (e) {
        if (e.status !== 400 && e.status !== 404) throw e;
        S.ruleTest = { error: e.message };
      }
    });
    focusEl($('#rx-test .rx-result, #rx-test [role="alert"]'));
  },
  /** 집필 화면: 규칙이 바꾼 곳 하나를 되돌린다 */
  async ruleUndo(arg) {
    const [n, rid, k] = arg.split(':');
    S.ruleRunOpen = `${S.name}:${n}:${rid}`;
    await ruleUndoRun(Number(n), '되돌리는 중', async () => {
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/rule-runs/${enc(rid)}/changes/${k}/undo`);
      toast('규칙이 고친 곳을 되돌렸어요');
    });
  },
  /** 집필 화면: 규칙 걸기 한 번을 모두 되돌린다. 그 뒤에 또 고친 곳은 남는다 */
  async ruleUndoAll(arg) {
    const [n, rid] = arg.split(':');
    const r = ((ep(Number(n)) || {}).rule_runs || []).find((x) => x.id === rid);
    const left = r ? r.changes.filter((c) => !c.undone).length : 0;
    if (!(await askConfirm(`규칙이 고친 ${left}곳을 모두 되돌릴까요? 되돌린 뒤 다시 걸려면 그 화를 다시 써야 해요.`, { ok: '모두 되돌리기' }))) return;
    await ruleUndoRun(Number(n), '되돌리는 중', async () => {
      const out = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/rule-runs/${enc(rid)}/undo`);
      S.project = out.project;
      toast(out.left ? `${out.undone}곳을 되돌렸어요. ${out.left}곳은 그 뒤에 또 고쳐 남겼어요` : `${out.undone}곳을 모두 되돌렸어요`);
    });
  },
});

/** 되돌리기 앞뒤: 저장하지 않은 본문 수정이 있으면 묻고 먼저 저장한다 (서버는 저장된 본문을 되돌린다) */
async function ruleUndoRun(n, label, fn) {
  if (textUnsaved(n) && !(await askConfirm('저장하지 않은 본문 수정이 있어요. 먼저 저장하고 되돌릴까요?', { ok: '저장하고 되돌리기' }))) return;
  await run(label, async () => {
    await saveIfDirty();
    await flushText(n);
    await fn();
  });
}

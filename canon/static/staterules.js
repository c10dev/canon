/* 상태 조건과 상태 규칙 (docs/context/specs/07-rules.md). app.js 의 S, actions, esc, render, markDirty, api, run, askConfirm 을 쓴다.
   상태 규칙 쪽(인과율 화면의 causal/_rules)은 causal.js 의 causalToc · outlineDoc 위에 선다. 규칙은 /state-rules 엔드포인트로 바로 저장한다.
   조건 한 줄(Condition)은 서버 schema.Condition 과 같은 모양이고 판정은 서버 context.holds 한 곳에서 한다. 이 파일은 고치기와 보이기만 맡는다.
   조건 목록을 가진 화면은 COND_OWNERS 에 '주인 종류 → (id) => 조건 목록' 을 등록한다. 지금은 인과율 요소(el, causal.js)만이다.
   condSummary · condMissing 은 순수 함수(tests/test_staterules_js.py). */
'use strict';

const COND_KINDS = [['stat', '상태창 값'], ['tie', '관계 수치'], ['episode', '화 범위'], ['foreshadow', '복선 상태'], ['in_plot', '이번 화 플롯에 나옴']];
const COND_OPS = [['ge', '이상'], ['le', '이하'], ['gt', '초과'], ['lt', '미만'], ['eq', '같음'], ['ne', '다름'], ['has', '가짐']];
const COND_TIES = [['warmth', '온기'], ['trust', '신뢰'], ['status', '서열'], ['familiarity', '친밀'], ['grievance', '원한']];
const COND_STATUS = [['open', '열림'], ['resolved', '회수됨']];
/** 주인 종류 → (id) => 조건 목록(바꿀 수 있는 배열). 화면 파일이 등록한다 */
const COND_OWNERS = {};
/** 고쳐도 작품 저장 띠를 띄우지 않는 주인 종류 (상태 규칙 초안 sr 은 엔드포인트로 따로 저장한다) */
const COND_QUIET = new Set(['sr']);
const condTouch = (owner) => { if (!COND_QUIET.has(String(owner).split(':')[0])) markDirty(); };

/** 새 조건 한 줄. 서버 Condition 의 기본값과 같다 */
function condBlank(p) {
  const first = (p.characters || [])[0];
  return { kind: 'stat', character: first ? first.id : '', target: '', name: '', op: 'ge', value: '', from_ep: 0, to_ep: 0, foreshadow: '', status: 'open' };
}

function condLabel(list, k) {
  return (list.find(([x]) => x === k) || [k, k])[1];
}

function condWho(p, id) {
  const c = (p.characters || []).find((x) => x.id === id);
  return c ? (c.name || c.id) : (id || '?');
}

function condFs(p, id) {
  const f = (p.foreshadows || []).find((x) => x.id === id);
  if (!f) return id || '?';
  const d = (f.description || f.id).trim();
  return d.length > 24 ? `${d.slice(0, 24)}…` : d;
}

/** 조건 한 줄의 요약: '주인공 마력 0 이하' · '주인공 → 지훈 신뢰 0.7 이상' · '3~10화' · '복선 「…」 열림' · '이번 화 플롯에 나옴: 주인공' */
function condSummary(c, p) {
  const op = condLabel(COND_OPS, c.op);
  if (c.kind === 'stat') {
    const who = `${condWho(p, c.character)} ${c.name || '?'}`;
    if (c.op === 'has') return `${who}에 ${c.value || '?'} 있음`;
    if (c.op === 'eq') return `${who}: ${c.value}`;
    if (c.op === 'ne') return `${who}: ${c.value} 아님`;
    return `${who} ${c.value || '?'} ${op}`;
  }
  if (c.kind === 'tie') return `${condWho(p, c.character)} → ${condWho(p, c.target)} ${condLabel(COND_TIES, c.name)} ${c.value || '?'} ${op}`;
  if (c.kind === 'episode') {
    if (c.from_ep && c.to_ep) return `${c.from_ep}~${c.to_ep}화`;
    if (c.from_ep) return `${c.from_ep}화부터`;
    if (c.to_ep) return `${c.to_ep}화까지`;
    return '모든 화';
  }
  if (c.kind === 'foreshadow') return `복선 「${condFs(p, c.foreshadow)}」 ${condLabel(COND_STATUS, c.status)}`;
  if (c.kind === 'in_plot') return `이번 화 플롯에 나옴: ${condWho(p, c.character)}`;
  return c.kind;
}

/** 없는 대상을 가리키면 그 까닭, 아니면 빈 글. 서버 판정은 이런 조건을 맞지 않는 것으로 본다(context.holds) */
function condMissing(c, p) {
  const has = (id) => (p.characters || []).some((x) => x.id === id);
  if (['stat', 'tie', 'in_plot'].includes(c.kind) && !has(c.character)) return '없는 인물이에요';
  if (c.kind === 'tie' && !has(c.target)) return '없는 인물이에요';
  if (c.kind === 'tie' && !COND_TIES.some(([k]) => k === c.name)) return '관계 수치를 고르세요';
  if (c.kind === 'stat') {
    const st = (p.states || []).find((s) => s.character_id === c.character);
    if (!st || !(st.stats || []).some((x) => x.name === c.name)) return '없는 스탯이에요';
  }
  if (c.kind === 'foreshadow' && !(p.foreshadows || []).some((x) => x.id === c.foreshadow)) return '없는 복선이에요';
  return '';
}

/** 읽기 카드에 보이는 조건 요약. 없는 대상은 경고 글을 붙인다 */
function condListHtml(conds, p) {
  return conds.map((c) => {
    const miss = condMissing(c, p);
    return `<div>${esc(condSummary(c, p))}${miss ? ` <span class="cond-miss">${esc(miss)}</span>` : ''}</div>`;
  }).join('');
}

function condSelect(owner, i, field, list, value, label) {
  return `<select data-cond="${esc(owner)}" data-cond-i="${i}" data-cond-f="${field}" aria-label="${esc(label)}">${list.map(([k, l]) => `<option value="${esc(k)}"${k === value ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
}

function condInput(owner, i, field, value, label, attrs = '') {
  return `<input data-cond="${esc(owner)}" data-cond-i="${i}" data-cond-f="${field}" aria-label="${esc(label)}" value="${esc(String(value ?? ''))}" ${attrs}>`;
}

function condRow(owner, c, i, p) {
  const chars = [['', '인물 고르기'], ...(p.characters || []).map((x) => [x.id, x.name || x.id])];
  const parts = [condSelect(owner, i, 'kind', COND_KINDS, c.kind, '조건 종류')];
  if (c.kind === 'stat') {
    const st = (p.states || []).find((s) => s.character_id === c.character);
    const names = [...new Set(((st && st.stats) || []).map((x) => x.name))];
    const list = `cond-stats-${esc(owner)}-${i}`;
    parts.push(condSelect(owner, i, 'character', chars, c.character, '인물'),
      condInput(owner, i, 'name', c.name, '상태창 항목', `list="${list}" placeholder="항목 이름" size="8"`) + `<datalist id="${list}">${names.map((x) => `<option value="${esc(x)}">`).join('')}</datalist>`,
      condInput(owner, i, 'value', c.value, '견줄 값', 'placeholder="값" size="6"'),
      condSelect(owner, i, 'op', COND_OPS, c.op, '견주기'));
  } else if (c.kind === 'tie') {
    parts.push(condSelect(owner, i, 'character', chars, c.character, '인물'), '<span>→</span>',
      condSelect(owner, i, 'target', [['', '상대 고르기'], ...chars.slice(1)], c.target, '상대 인물'),
      condSelect(owner, i, 'name', [['', '수치 고르기'], ...COND_TIES], c.name, '관계 수치'),
      condInput(owner, i, 'value', c.value, '견줄 값', 'placeholder="0.7" size="5" inputmode="decimal"'),
      condSelect(owner, i, 'op', COND_OPS.filter(([k]) => k !== 'has'), c.op, '견주기'));
  } else if (c.kind === 'episode') {
    parts.push(condInput(owner, i, 'from_ep', c.from_ep || '', '시작 화', 'type="number" min="0" placeholder="처음" style="width:80px"'), '<span>~</span>',
      condInput(owner, i, 'to_ep', c.to_ep || '', '끝 화', 'type="number" min="0" placeholder="끝" style="width:80px"'), '<span>화</span>');
  } else if (c.kind === 'foreshadow') {
    const fs = [['', '복선 고르기'], ...(p.foreshadows || []).map((x) => [x.id, condFs(p, x.id)])];
    parts.push(condSelect(owner, i, 'foreshadow', fs, c.foreshadow, '복선'), condSelect(owner, i, 'status', COND_STATUS, c.status, '복선 상태'));
  } else if (c.kind === 'in_plot') {
    parts.push(condSelect(owner, i, 'character', chars, c.character, '인물'));
  }
  const miss = condMissing(c, p);
  parts.push(`<button type="button" class="btn small ghost" data-action="condDel" data-arg="${esc(`${owner}|${i}`)}">지우기</button>`);
  if (miss) parts.push(`<span class="cond-miss">${esc(miss)}</span>`);
  return `<div class="cond-row">${parts.join('')}</div>`;
}

/** 조건 고치기 칸. owner 는 'el:<요소 id>' 꼴 */
function condEditor(owner, conds, p) {
  return `<div class="cond-box">${conds.map((c, i) => condRow(owner, c, i, p)).join('')}
    <div><button type="button" class="btn small" data-action="condAdd" data-arg="${esc(owner)}">조건 더하기</button></div></div>`;
}

function condList(owner) {
  const at = owner.indexOf(':');
  const get = COND_OWNERS[owner.slice(0, at)];
  return get ? get(owner.slice(at + 1)) : null;
}

Object.assign(actions, {
  condAdd(owner) {
    const list = condList(String(owner));
    if (!list) return;
    list.push(condBlank(P()));
    condTouch(owner);
    render();
  },
  condDel(arg) {
    const s = String(arg);
    const cut = s.lastIndexOf('|');
    const list = condList(s.slice(0, cut));
    if (!list) return;
    list.splice(Number(s.slice(cut + 1)), 1);
    condTouch(s);
    render();
  },
});

/** 조건 칸 하나가 바뀌었을 때 (change). 시험이 바로 부른다 */
function condChange(t) {
  if (!t.dataset || !t.dataset.cond) return;
  const list = condList(t.dataset.cond);
  const c = list && list[Number(t.dataset.condI)];
  if (!c) return;
  const f = t.dataset.condF;
  if (f === 'kind') {
    // 종류를 바꾸면 인물만 두고 나머지 칸을 비운다. 앞 종류의 항목 이름 · 값이 남으면 늘 맞지 않는 조건이 된다
    list[Number(t.dataset.condI)] = { ...condBlank(P()), kind: t.value, character: c.character };
    condTouch(t.dataset.cond);
    render();
    return;
  }
  c[f] = f === 'from_ep' || f === 'to_ep' ? Math.max(0, parseInt(t.value, 10) || 0) : t.value;
  condTouch(t.dataset.cond);
  // 글 칸(값 · 항목 이름)은 다시 그리지 않는다: 다른 칸을 누를 때 change 가 나서 다시 그리면 커서를 잃는다
  if (t.tagName === 'SELECT') render();
}

document.addEventListener('change', (e) => condChange(e.target));

(function condStyle() {
  const css = `
.cond-box { display: flex; flex-direction: column; gap: 8px; }
.cond-row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding: 8px 10px; border: 1px solid var(--line); border-radius: 8px; }
.cond-row select, .cond-row input { width: auto; max-width: 100%; flex: 0 1 auto; min-height: var(--control-small); }
.cond-row input[size] { min-width: 4em; }
@media (pointer: coarse), (max-width: 640px) { .cond-row select, .cond-row input { min-height: var(--touch-min); } }
.cond-miss { color: var(--red); font-size: 0.75rem; }`;
  const el = document.createElement('style');
  el.textContent = css;
  document.head.appendChild(el);
}());

// ---------- 상태 규칙 쪽 (인과율 › 상태 규칙, 주소 causal/_rules) ----------
// 규칙 하나: 조건(when, 모두 맞아야 함)과 제안할 변경(changes: 상태창 값 바꾸기 · 복선 회수). 규칙은 상태를 바로 쓰지 않고 상태 승인 화면에 '규칙' 제안으로 올린다.
// 고치는 중인 규칙은 S.srEdit 의 초안이다. 저장(srSave)은 POST · PUT, 켜고 끄기 · 지우기는 바로 저장한다.

const SR_PAGE = '_rules';
const SPEC_KINDS = [['stat', '상태창 값 바꾸기'], ['resolve', '복선 회수']];
Object.assign(S, { srEdit: null });  // { id: 규칙 id(새 규칙이면 ''), rule: 초안 }

function specBlank(p) {
  const st = (p.states || []).find((s) => (s.stats || []).length) || (p.states || [])[0];
  return { kind: 'stat', character_id: st ? st.character_id : '', stat: '', value: '', foreshadow_id: '' };
}

/** 변경 한 줄의 요약: '서윤 상태를 기절로 바꾸자고 제안해요' · '서윤 마력 +3 바꾸자고 제안해요' · '복선 「…」 회수를 제안해요' */
function specSummary(c, p) {
  if (c.kind === 'resolve') return `복선 「${condFs(p, c.foreshadow_id)}」 회수를 제안해요`;
  const who = `${condWho(p, c.character_id)} ${c.stat || '?'}`;
  const v = (c.value || '').trim();
  if (!v) return `${who}${josa(who, '을', '를')} 지우자고 제안해요`;
  if (/^[+-]/.test(v)) return `${who} ${v} 바꾸자고 제안해요`;
  return `${who}${josa(who, '을', '를')} ${v}${josa(v, '으로', '로')} 바꾸자고 제안해요`;
}

/** 변경 한 줄이 가리키는 대상이 없으면 그 까닭. 상태가 없는 인물의 상태창은 바꿀 수 없다 (statwin.merge 는 인물 상태를 받는다) */
function specMissing(c, p) {
  if (c.kind === 'resolve') return (p.foreshadows || []).some((x) => x.id === c.foreshadow_id) ? '' : '없는 복선이에요';
  if (!(p.characters || []).some((x) => x.id === c.character_id)) return '없는 인물이에요';
  if (!(p.states || []).some((s) => s.character_id === c.character_id)) return '상태가 없는 인물이에요';
  return c.stat.trim() ? '' : '항목 이름을 적으세요';
}

function specRow(c, i, p) {
  const sel = (f, list, v, label) => `<select data-spec-i="${i}" data-spec-f="${f}" aria-label="${esc(label)}">${list.map(([k, l]) => `<option value="${esc(k)}"${k === v ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
  const inp = (f, v, label, attrs) => `<input data-spec-i="${i}" data-spec-f="${f}" aria-label="${esc(label)}" value="${esc(v || '')}" ${attrs}>`;
  const parts = [sel('kind', SPEC_KINDS, c.kind, '바꿀 것')];
  if (c.kind === 'stat') {
    const st = (p.states || []).find((s) => s.character_id === c.character_id);
    const list = `spec-stats-${i}`;
    parts.push(sel('character_id', [['', '인물 고르기'], ...(p.characters || []).map((x) => [x.id, x.name || x.id])], c.character_id, '인물'),
      inp('stat', c.stat, '상태창 항목', `list="${list}" placeholder="항목 이름" size="8"`) + `<datalist id="${list}">${((st && st.stats) || []).map((x) => `<option value="${esc(x.name)}">`).join('')}</datalist>`,
      inp('value', c.value, '새 값', 'placeholder="기절 · +3 · +독 내성" size="10"'));
  } else {
    parts.push(sel('foreshadow_id', [['', '복선 고르기'], ...(p.foreshadows || []).filter((x) => x.status === 'open' || x.id === c.foreshadow_id).map((x) => [x.id, condFs(p, x.id)])], c.foreshadow_id, '복선'));
  }
  const miss = specMissing(c, p);
  parts.push(`<button type="button" class="btn small ghost" data-action="specDel" data-arg="${i}">지우기</button>`);
  if (miss) parts.push(`<span class="cond-miss">${esc(miss)}</span>`);
  return `<div class="cond-row">${parts.join('')}</div>`;
}

function srEditor() {
  const p = P();
  const r = S.srEdit.rule;
  return `<section class="card pf-sec editing" id="sr-edit"><h2>${S.srEdit.id ? '규칙 고치기' : '새 규칙'}</h2>
    <div class="grid-2"><div class="field"><label for="sr-name">이름</label><input id="sr-name" data-sr-f="name" value="${esc(r.name)}" placeholder="예: 기절"></div>
      <div class="field"><label for="sr-note">메모</label><input id="sr-note" data-sr-f="note" value="${esc(r.note)}" placeholder="작가만 봐요"></div></div>
    <div class="field"><span class="label">조건 <span class="hint">모두 맞으면 제안해요. 그 화를 반영한 뒤의 값으로 봐요</span></span>${condEditor('sr:draft', r.when, p)}</div>
    <div class="field"><span class="label">제안할 변경 <span class="hint">상태 승인 화면에 '규칙' 표시로 체크된 채 와요</span></span>
      <div class="cond-box">${r.changes.map((c, i) => specRow(c, i, p)).join('')}<div><button type="button" class="btn small" data-action="specAdd">변경 더하기</button></div></div></div>
    <div class="row"><button type="button" class="btn primary" data-action="srSave">저장</button><button type="button" class="btn" data-action="srCancel">취소</button></div></section>`;
}

function srRow(r, p) {
  const sw = `<button type="button" class="set-sw" role="switch" aria-checked="${r.on}" aria-label="${esc(r.name || r.id)} 켜기" data-action="srToggle" data-arg="${esc(r.id)}"></button>`;
  const conds = r.when.length ? condListHtml(r.when, p) : '<div class="small">조건 없음: 늘 맞아요</div>';
  const effects = r.changes.map((c) => { const miss = specMissing(c, p); return `<div>${esc(specSummary(c, p))}${miss ? ` <span class="cond-miss">${esc(miss)}</span>` : ''}</div>`; }).join('') || '<div class="small">제안할 변경이 없어요</div>';
  return `<div class="sr-row${r.on ? '' : ' off'}"><div class="sr-h">${sw}<strong>${esc(r.name || '이름 없음')}</strong>${r.note ? `<span class="small">${esc(r.note)}</span>` : ''}
      <span class="sr-act"><button type="button" class="btn small" data-action="srEdit" data-arg="${esc(r.id)}">고치기</button><button type="button" class="btn small ghost" data-action="srDelete" data-arg="${esc(r.id)}">지우기</button></span></div>
    <div class="sr-b"><div><span class="label">조건</span>${conds}</div><div><span class="label">효과</span>${effects}</div></div></div>`;
}

/** 인과율 › 상태 규칙 쪽. causal.js 의 viewCausal 이 부른다 */
function srPage() {
  const p = P();
  const rules = p.state_rules || [];
  const add = S.srEdit ? '' : '<button type="button" class="btn primary" data-action="srNew">+ 규칙 더하기</button>';
  const head = header('인과율', '상태 규칙', '조건이 맞으면 상태 변경을 제안해요. 규칙은 상태를 바로 바꾸지 않고, 상태 승인 화면에서 반영해야 들어가요.', add);
  const list = rules.length ? `<div class="sr-list">${rules.map((r) => srRow(r, p)).join('')}</div>` : '<p class="small">아직 규칙이 없어요. 조건과 효과를 골라 규칙을 만들어 보세요.</p>';
  const els = (p.elements || []).filter((el) => ((el.activation || {}).conditions || []).length);
  const ins = els.length ? `<section class="card"><h2>조건이 맞으면 넣는 요소 ${els.length}</h2><div class="sr-list">${els.map((el) => `<div class="sr-row"><div class="sr-h"><a href="${base()}/causal/${enc(el.id)}" data-action="causalShow" data-arg="${esc(el.id)}">이 항목을 넣어요: ${esc(el.name || '이름 없음')}</a></div>
      <div class="sr-b"><div><span class="label">조건</span>${condListHtml(el.activation.conditions, p)}</div></div></div>`).join('')}</div></section>` : '';
  const main = `<div class="cz-col">${S.srEdit ? srEditor() : ''}<section class="card" id="sr-all"><h2>상태 규칙 ${rules.length}</h2>${list}</section>${ins}</div>`;
  return `${head}${outlineDoc(causalToc(), main, { cls: 'cz-wrap' })}`;
}

if (typeof COND_OWNERS !== 'undefined') COND_OWNERS.sr = () => (S.srEdit ? S.srEdit.rule.when : null);

/** 저장 응답(규칙 목록)으로 작품의 규칙을 바꾼다. 받은 판에도 적어(takeField) 다음 작품 저장이 이 칸을 다시 보내지 않게 한다. 저장 띠의 다른 고침은 그대로 둔다 */
function srTake(rules) {
  takeField('state_rules', rules);
}

Object.assign(actions, {
  srNew() {
    S.srEdit = { id: '', rule: { id: '', name: '', note: '', on: true, when: [], changes: [specBlank(P())] } };
    S.focusTarget = '#sr-name';
    render();
  },
  srEdit(id) {
    const r = (P().state_rules || []).find((x) => x.id === id);
    if (!r) return;
    S.srEdit = { id, rule: structuredClone(r) };
    S.focusTarget = '#sr-name';
    render();
  },
  srCancel() {
    S.srEdit = null;
    render();
  },
  specAdd() {
    S.srEdit.rule.changes.push(specBlank(P()));
    render();
  },
  specDel(i) {
    S.srEdit.rule.changes.splice(Number(i), 1);
    render();
  },
  async srSave() {
    const { id, rule } = S.srEdit;
    if (!rule.changes.length) return toast('제안할 변경을 하나 이상 더하세요', true);
    await run('저장하는 중', async () => {
      srTake(await api(id ? 'PUT' : 'POST', `/projects/${enc(S.name)}/state-rules${id ? `/${enc(id)}` : ''}`, rule));
      S.srEdit = null;
      toast('상태 규칙을 저장했어요');
    });
  },
  async srToggle(id) {
    const r = (P().state_rules || []).find((x) => x.id === id);
    if (!r) return;
    await run('저장하는 중', async () => { srTake(await api('PUT', `/projects/${enc(S.name)}/state-rules/${enc(id)}`, { ...r, on: !r.on })); });
  },
  async srDelete(id) {
    const r = (P().state_rules || []).find((x) => x.id === id);
    if (!r || !(await askConfirm(`'${r.name || '이름 없음'}' 규칙을 지울까요? 이미 반영한 제안은 그대로예요.`, { ok: '지우기', danger: true }))) return;
    await run('지우는 중', async () => { srTake(await api('DELETE', `/projects/${enc(S.name)}/state-rules/${enc(id)}`)); });
  },
});

document.addEventListener('change', (e) => {
  const t = e.target;
  if (!t.dataset || !S.srEdit) return;
  const r = S.srEdit.rule;
  if (t.dataset.srF) { r[t.dataset.srF] = t.value; return; }
  if (t.dataset.specF === undefined) return;
  const i = Number(t.dataset.specI);
  if (t.dataset.specF === 'kind') {
    r.changes[i] = { ...specBlank(P()), kind: t.value };
    render();
    return;
  }
  r.changes[i][t.dataset.specF] = t.value;
  if (t.tagName === 'SELECT') render();
});

(function srStyle() {
  const css = `
.sr-list { display: flex; flex-direction: column; }
.sr-row { padding: 12px 0; border-top: 1px solid var(--rule); display: flex; flex-direction: column; gap: 6px; }
.sr-row:first-child { border-top: none; }
.sr-row.off .sr-b { opacity: .55; }
.sr-h { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.sr-act { margin-left: auto; display: flex; gap: 6px; }
.sr-b { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 6px 16px; font-size: 0.875rem; }
.sr-b .label { display: block; font-size: 0.75rem; color: var(--muted); }`;
  const el = document.createElement('style');
  el.textContent = css;
  document.head.appendChild(el);
}());

/* 상태 조건 (docs/context/specs/07-rules.md). app.js 의 S, actions, esc, render, markDirty 를 쓴다.
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
    markDirty();
    render();
  },
  condDel(arg) {
    const s = String(arg);
    const cut = s.lastIndexOf('|');
    const list = condList(s.slice(0, cut));
    if (!list) return;
    list.splice(Number(s.slice(cut + 1)), 1);
    markDirty();
    render();
  },
});

document.addEventListener('change', (e) => {
  const t = e.target;
  if (!t.dataset || !t.dataset.cond) return;
  const list = condList(t.dataset.cond);
  const c = list && list[Number(t.dataset.condI)];
  if (!c) return;
  const f = t.dataset.condF;
  c[f] = f === 'from_ep' || f === 'to_ep' ? Math.max(0, parseInt(t.value, 10) || 0) : t.value;
  if (f === 'kind' && c.kind === 'tie' && c.op === 'has') c.op = 'ge';
  markDirty();
  // 글 칸(값 · 항목 이름)은 다시 그리지 않는다: 다른 칸을 누를 때 change 가 나서 다시 그리면 커서를 잃는다
  if (t.tagName === 'SELECT') render();
});

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

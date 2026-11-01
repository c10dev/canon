// ----- 4. 집필: 화별 스토리보드 카드 -----
// 쓰기 직전의 장면 순서와 이번 화 확정 값 (Episode.storyboard, 서버 board.py · pipeline.make_storyboard).
// 본문이 없는 화의 집필 화면에서 만들기 · 고치기 · 다시 만들기 · 이대로 쓰기를 둔다. 상태 승인 대상이 아니라 저장하면 바로 들어간다.
// Canon 이 센 값(시간 한 줄, 상태창 단계, 경고)은 GET …/storyboard 로 받는다 (boardView). write.js 의 viewWrite 가 부른다.

const BOARD_WARN = { plot_vs_state: '플롯 · 상태', plot_vs_text: '플롯 · 앞 화 본문', time: '시간', setting: '설정', next_plot: '다음 화 플롯' };
const BOARD_STOP = ['plot_vs_state', 'plot_vs_text', 'time'];  // board.STOP_KINDS: 자동 집필이 멈추는 경고
const BOARD_BY = { ai: 'AI 제안', author: '작가가 만듦', both: 'AI 제안 · 작가가 고침' };
const BOARD_KINDS = ['장면', '시간', '몸', '물건', '인물', '숨긴 것', '숫자', '질문'];

/** 스토리보드 장면 줄의 '장면 연출' 링크: 그 장면이 맡은 첫 사건의 장면 연출 화면 (주소 stage/<화>/<사건 번호>). */
function boardStageLink(n, s) {
  const first = Math.min(...s.events.filter((k) => k > 0));
  return Number.isFinite(first) ? `<a class="small" href="${base()}/stage/${n}/${first}" title="이 장면의 자리 · 몸을 장면 연출에서 짜요">장면 연출</a>` : '';
}

/** 이 작품이 스토리보드를 쓰는지 (board.on: 작가가 정하지 않았으면 장편 켬 · 단편 끔). */
function boardOn() {
  const v = P().settings && P().settings.storyboard;
  return v ?? P().meta.form === 'serial';
}

/** 서버가 센 값이 지금 작품과 맞는지 가르는 열쇠: 스토리보드, 직전 화 본문, 이번 화 · 다음 화 플롯 (board.basis 의 입력). */
function boardSig(n) {
  const e = ep(n);
  const prev = ep(n - 1);
  const next = ep(n + 1);
  return `${S.name}:${n}:${JSON.stringify(e && e.storyboard)}:${prev ? prev.text.length : 0}:${JSON.stringify(e && e.plot)}:${JSON.stringify(next && next.plot)}`;
}

/** GET …/storyboard 결과. 열쇠가 바뀌면 다시 받아 그린다. 받는 동안은 null. */
function boardView(n) {
  const sig = boardSig(n);
  if (S.boardSig === sig) return S.boardView;
  S.boardSig = sig;
  S.boardView = null;
  api('GET', `/projects/${enc(S.name)}/episodes/${n}/storyboard`).then((v) => {
    if (S.boardSig === sig) { S.boardView = v; render(); }
  }).catch(() => { /* 받지 못하면 계산 값 없이 그린다 */ });
  return null;
}

/** 만든 스토리보드가 있고 본문이 없는 화의 카드. 만들기 전의 고르기는 write.js writeStart 가 한다. */
function boardStart(n, blocked) {
  const e = ep(n);
  if (!e.storyboard) return '';
  const off = blocked.length || autoOn();
  const busy = jobFor('board', n) || jobFor('write', n);
  return boardCard(n, off || busy);
}

/** 본문을 쓴 화: 쓸 때 쓴 스토리보드를 접어 둔다 (다시 생성도 이 스토리보드를 그대로 쓴다). */
function boardPanel(n) {
  const e = ep(n);
  if (!e || !e.text || !e.storyboard) return '';
  return `<details class="card bd-card bd-done"><summary>이 화를 쓴 스토리보드 · 장면 ${e.storyboard.scenes.length}개</summary>${boardBody(n, e.storyboard, boardView(n))}
    <p class="small">다시 생성은 이 스토리보드를 그대로 써요.</p></details>`;
}

function boardCard(n, off) {
  const e = ep(n);
  const b = e.storyboard;
  const v = boardView(n);
  const edit = S.boardEdit && S.boardEdit.key === `${S.name}:${n}` ? S.boardEdit : null;
  const stale = v && v.stale;
  const mk = jobBtn('board', n, '다시 만들기');
  const wr = jobBtn('write', n, `이대로 ${n}화 쓰기`);
  const head = `<div class="row bd-head"><h2 class="bd-title">이번 화 스토리보드</h2><span class="chip ai">${BOARD_BY[b.made_by] || 'AI 제안'}</span>
    ${b.made_at ? `<span class="small">${fmtDateTime(b.made_at)}</span>` : ''}
    ${v ? (stale ? '<span class="chip warn">입력이 바뀌었어요</span>' : '<span class="chip ok">입력과 맞아요</span>') : ''}</div>
    <p class="small">장면 순서와 확정 값만 정했어요. 대사와 문장은 정하지 않았어요. 쓰기 재료라서 상태 승인 대상이 아니에요.</p>
    ${stale ? '<div class="note warn">스토리보드를 만든 뒤 직전 화 본문, 이번 화 · 다음 화 플롯, 인물 상태 중 하나가 바뀌었어요. 다시 만들거나, 그대로 쓰려면 아래 내용을 확인하세요.</div>' : ''}`;
  if (edit) {
    return `<section class="card bd-card" aria-label="${n}화 스토리보드 고치기">${head}${boardForm(n, edit.draft)}
      <div class="row bd-actions"><button class="btn" data-action="boardCancel">취소</button><button class="btn danger" data-action="boardDrop" data-arg="${n}">스토리보드 지우기</button>
        <span class="bd-fill"></span><button class="btn primary" data-action="boardSave" data-arg="${n}">고친 스토리보드 저장</button></div></section>`;
  }
  return `<section class="card bd-card" aria-label="${n}화 스토리보드">${head}${boardBody(n, b, v)}
    <div class="row bd-actions"><button class="btn" data-action="boardEdit" data-arg="${n}"${off ? ' disabled' : ''}>고치기</button>
      <button class="btn${stale ? ' primary' : ''}" data-action="boardMake" data-arg="${n}"${off ? ' disabled' : mk.attr}>${mk.label}</button>
      <span class="bd-fill"></span>
      <button class="btn" data-action="boardWrite" data-arg="${n}:"${off ? ' disabled' : wr.attr}>${wr.label}</button></div></section>`;
}

/** 읽기용 몸통: 어긋남 → 확정 값 → 넘겨받을 것 → 깨지 않을 것 → 장면. */
function boardBody(n, b, v) {
  const name = (id) => charName(id) || id;
  const li = (x) => `<li>${x}</li>`;
  const mine = b.warnings.filter((w) => w.target === 'this' && w.kind !== 'setting');
  const next = b.warnings.filter((w) => w.target === 'next');
  const other = b.warnings.filter((w) => w.target === 'this' && w.kind === 'setting');
  const warn = (w) => `<li><strong>${esc(BOARD_WARN[w.kind] || w.kind)}${w.field ? ` · ${esc(w.field)}` : ''}</strong> ${esc(w.text)}${w.resolution ? `<br><span class="small">처리 · ${esc(w.resolution)}</span>` : ''}</li>`;
  const checks = v ? v.checks : (b.checks || []);
  const parts = [];
  if (mine.length) parts.push(`<div class="note warn"><strong>이번 화 플롯과 어긋남 ${mine.length}</strong>${mine.some((w) => BOARD_STOP.includes(w.kind)) ? ' · 자동 집필이면 여기서 멈춰요' : ''}<ul>${mine.map(warn).join('')}</ul></div>`);
  if (next.length) parts.push(`<div class="note plain"><strong>다음 화(${n + 1}화) 플롯과 어긋남 ${next.length}</strong><ul>${next.map(warn).join('')}</ul>
    ${ep(n + 1) ? `<a class="btn small" href="${base()}/arc/${n + 1}">${n + 1}화 플롯 고치러 가기</a>` : ''}</div>`);
  if (other.length) parts.push(`<div class="note plain"><strong>설정에 없는 점</strong><ul>${other.map(warn).join('')}</ul></div>`);
  if (checks.length) parts.push(`<div class="note warn"><strong>Canon이 센 경고</strong><ul>${checks.map((c) => li(esc(c))).join('')}</ul></div>`);

  const vals = [];
  vals.push(`<div class="bd-row"><span class="bd-k">시간 · Canon이 셈</span><span>${v ? esc(v.time) : '세는 중…'}</span></div>`);
  if (v && v.deadlines.length) vals.push(`<div class="bd-row"><span class="bd-k">열린 기한</span><span>${v.deadlines.map((d) => esc(d.replace(/^- /, ''))).join('<br>')}</span></div>`);
  vals.push(`<div class="bd-row"><span class="bd-k">이동</span><span>${b.moves.length ? b.moves.map((m) => `${esc(name(m.character_id))} · ${m.scene ? `${m.scene}장면에서 ` : ''}${esc(m.to)}(으)로`).join('<br>') : '없음'}</span></div>`);
  if (b.attire.length) vals.push(`<div class="bd-row"><span class="bd-k">차림 (화 끝)</span><span>${b.attire.map((a) => `<strong>${esc(name(a.character_id))}</strong> · ${esc(a.end)}${a.why ? ` <span class="small">(${esc(a.why)})</span>` : ''}`).join('<br>')}</span></div>`);
  const steps = v ? v.steps : [];
  if (steps.length) {
    const rows = steps.flatMap((s) => s.rows.map((r, i) => `<tr>${i === 0 ? `<td rowspan="${s.rows.length}">${s.window ? `상태창 ${s.window}` : '창 없음'}</td><td rowspan="${s.rows.length}">${s.scene || '끝'}</td><td rowspan="${s.rows.length}">${esc(s.who)}</td>` : ''}
      <td>${esc(r.name)}</td><td>${esc(r.before || '(없음)')} → <strong>${esc(r.after || '(없앰)')}</strong></td></tr>`)).join('');
    const notes = steps.filter((s) => s.notice).map((s) => `<div class="small">상태창 ${s.window} 알림 · ${esc(s.notice)}</div>`).join('');
    const preview = steps.filter((s) => s.text).map((s) => `<pre class="bd-win">${esc(s.text)}</pre>`).join('');
    vals.push(`<div class="bd-k">상태창 (값은 Canon이 셈)</div><table class="bd-table"><thead><tr><th>창</th><th>장면</th><th>인물</th><th>항목</th><th>값</th></tr></thead><tbody>${rows}</tbody></table>${notes}
      ${b.stat_basis.length || preview ? `<details><summary>근거와 창 미리 보기</summary>${b.stat_basis.length ? `<ul>${b.stat_basis.map((x) => li(esc(x))).join('')}</ul>` : ''}${preview}</details>` : ''}`);
  }
  parts.push(`<div class="bd-sec"><h3 class="bd-h">이번 화 확정 값</h3>${vals.join('')}</div>`);
  if (b.handover.length) parts.push(`<div class="bd-sec"><h3 class="bd-h">${n > 1 ? `${n - 1}화에서 ` : ''}넘겨받을 것</h3><ul class="bd-list">${b.handover.map((h) => `<li>${h.kind ? `<span class="chip">${esc(h.kind)}</span> ` : ''}${esc(h.text)}</li>`).join('')}</ul></div>`);
  if (b.protect.length) parts.push(`<div class="bd-sec"><h3 class="bd-h">이번 화에서 깨지 않을 것 <span class="small">다음 화 플롯이 전제해요</span></h3><ul class="bd-list">${b.protect.map((x) => li(esc(x))).join('')}</ul></div>`);
  const events = ep(n).plot.events.length;
  const covered = new Set(b.scenes.flatMap((s) => s.events));
  const missing = Array.from({ length: events }, (_, i) => i + 1).filter((k) => !covered.has(k));
  parts.push(`<div class="bd-sec"><h3 class="bd-h">장면 ${b.scenes.length} <span class="small">${missing.length ? `사건 ${missing.join(', ')}번을 맡은 장면이 없어요` : events ? `사건 1~${events}을 모두 나눠 맡았어요` : ''}</span></h3>
    <ol class="bd-scenes">${b.scenes.map((s) => `<li><div><strong>${esc([s.place, s.spot].filter(Boolean).join(' · '))}</strong>${s.time ? ` · ${esc(s.time)}` : ''}${s.present.length ? ` · ${esc(s.present.map(name).join(', '))}` : ''}${s.events.length ? ` <span class="chip">사건 ${s.events.join(', ')}</span> ${boardStageLink(n, s)}` : ''}</div>
      ${s.goal ? `<div class="small">목표 · ${esc(s.goal)}</div>` : ''}${s.turn ? `<div class="small">전환 · ${esc(s.turn)}</div>` : ''}${s.end_state ? `<div class="small">끝 · ${esc(s.end_state)}</div>` : ''}</li>`).join('')}</ol></div>`);
  return parts.join('');
}

// ----- 고치기 -----
// 칸은 data-bd="경로" 로 S.boardEdit.draft 에 묶는다. data-bd-type: ids(쉼표로 나눈 id) · nums(쉼표로 나눈 번호) · lines(한 줄에 하나) · int · bool

function boardForm(n, d) {
  const inp = (path, val, label, type = '') => `<label class="field"><span class="small">${label}</span><input data-bd="${path}"${type ? ` data-bd-type="${type}"` : ''} value="${esc(val)}"></label>`;
  const area = (path, val, label, type = '') => `<label class="field"><span class="small">${label}</span><textarea data-bd="${path}"${type ? ` data-bd-type="${type}"` : ''} rows="3">${esc(val)}</textarea></label>`;
  const t = d.time;
  const scenes = d.scenes.map((s, i) => `<fieldset class="bd-fs"><legend>장면 ${i + 1} <button class="link-btn" data-action="boardScene" data-arg="del:${i}">빼기</button></legend>
    <div class="grid-2">${inp(`scenes.${i}.place`, s.place, '장소')}${inp(`scenes.${i}.spot`, s.spot, '자리')}</div>
    <div class="grid-2">${inp(`scenes.${i}.time`, s.time, '시각')}${inp(`scenes.${i}.present`, s.present.join(', '), '함께 있는 인물 id (쉼표)', 'ids')}</div>
    ${inp(`scenes.${i}.events`, s.events.join(', '), '맡은 사건 번호 (쉼표)', 'nums')}
    ${area(`scenes.${i}.goal`, s.goal, '목표')}${area(`scenes.${i}.turn`, s.turn, '전환점')}${area(`scenes.${i}.end_state`, s.end_state, '장면 끝 상태')}</fieldset>`).join('');
  const stats = d.stats.map((s, i) => `<fieldset class="bd-fs"><legend>상태창 단계 ${i + 1} · ${esc(charName(s.character_id) || s.character_id)}</legend>
    <div class="grid-2">${inp(`stats.${i}.scene`, s.scene, '장면 번호 (0 이면 화 끝)', 'int')}<label class="check-row"><input type="checkbox" data-bd="stats.${i}.window" data-bd-type="bool"${s.window ? ' checked' : ''}><span>본문에 상태창이 떠요</span></label></div>
    ${s.changes.map((c, k) => `<div class="grid-2">${inp(`stats.${i}.changes.${k}.name`, c.name, '항목')}${inp(`stats.${i}.changes.${k}.value`, c.value, '바뀐 양 (예: -0.7, +1, +독 내성)')}</div>`).join('')}
    ${inp(`stats.${i}.notice`, s.notice, '함께 뜨는 알림')}</fieldset>`).join('');
  return `<div class="bd-form">
    <h3 class="bd-h">시간</h3>
    <div class="grid-2">${inp('time.after', t.after, '직전 화 끝에서 며칠 뒤 (같은 날 0, 메인 시간 밖 -1)', 'int')}${inp('time.days', t.days, '걸치는 날 수', 'int')}</div>
    <div class="grid-2">${inp('time.part', t.part, '시작 시간대')}${inp('time.end_part', t.end_part, '끝 시간대')}</div>
    <h3 class="bd-h">장면</h3>${scenes}<button class="btn small" data-action="boardScene" data-arg="add">장면 더하기</button>
    ${stats ? `<h3 class="bd-h">상태창</h3>${stats}` : ''}
    <h3 class="bd-h">넘겨받을 것 <span class="small">한 줄에 하나, '종류: 내용' (종류는 ${BOARD_KINDS.join(' · ')})</span></h3>
    <textarea data-bd="handover" data-bd-type="handover" rows="5" aria-label="넘겨받을 것">${esc(d.handover.map((h) => (h.kind ? `${h.kind}: ` : '') + h.text).join('\n'))}</textarea>
    <h3 class="bd-h">끝 차림 <span class="small">한 줄에 하나, '인물 id = 차림'</span></h3>
    <textarea data-bd="attire" data-bd-type="attire" rows="3" aria-label="끝 차림">${esc(d.attire.map((a) => `${a.character_id} = ${a.end}`).join('\n'))}</textarea>
    <h3 class="bd-h">이번 화에서 깨지 않을 것 <span class="small">한 줄에 하나</span></h3>
    <textarea data-bd="protect" data-bd-type="lines" rows="3" aria-label="이번 화에서 깨지 않을 것">${esc(d.protect.join('\n'))}</textarea>
  </div>`;
}

/** 칸 글을 스토리보드 값으로 (boardForm 의 data-bd-type). 차림은 옛 까닭을 이어 둔다. */
function boardParse(type, raw, old) {
  const split = (s) => s.split(/[,，]/).map((x) => x.trim()).filter(Boolean);
  const lines = (s) => s.split('\n').map((x) => x.trim()).filter(Boolean);
  if (type === 'ids') return split(raw);
  if (type === 'nums') return split(raw).map(Number).filter((x) => Number.isInteger(x) && x > 0);
  if (type === 'int') return Number.parseInt(raw, 10) || 0;
  if (type === 'lines') return lines(raw);
  if (type === 'handover') {
    return lines(raw).map((x) => {
      const m = x.match(/^([^:：]{1,6})\s*[:：]\s*(.+)$/);
      return m && BOARD_KINDS.includes(m[1].trim()) ? { kind: m[1].trim(), text: m[2].trim() } : { kind: '', text: x };
    });
  }
  if (type === 'attire') {
    return lines(raw).map((x) => {
      const i = x.indexOf('=');
      const id = i > 0 ? x.slice(0, i).trim() : '';
      const prev = (old || []).find((a) => a.character_id === id);
      return { character_id: id, end: (i > 0 ? x.slice(i + 1) : x).trim(), why: prev ? prev.why : '' };
    }).filter((a) => a.character_id);
  }
  return raw;
}

function boardSet(d, path, val) {
  const keys = path.split('.');
  let o = d;
  for (const k of keys.slice(0, -1)) o = o[k];
  o[keys[keys.length - 1]] = val;
}

document.addEventListener('input', (e) => {
  const path = e.target.dataset && e.target.dataset.bd;
  if (!path || !S.boardEdit) return;
  const type = e.target.dataset.bdType || '';
  const raw = type === 'bool' ? e.target.checked : e.target.value;
  const old = path === 'attire' ? S.boardEdit.draft.attire : null;
  boardSet(S.boardEdit.draft, path, type === 'bool' ? raw : boardParse(type, raw, old));
});
document.addEventListener('change', (e) => {
  if (e.target.dataset && e.target.dataset.bdType === 'bool' && S.boardEdit) boardSet(S.boardEdit.draft, e.target.dataset.bd, e.target.checked);
});

/** 스토리보드 켜기 · 끄기 (Settings.storyboard). 집필 화면의 쓰기 시작 칸(writeStart) 아래 줄에 둔다. */
function boardToggle() {
  const on = boardOn();
  return `<div class="field"><span class="small">화별 스토리보드</span><button type="button" class="btn small${on ? ' on' : ''}" aria-pressed="${on}" data-action="boardToggle" title="쓰기 전에 장면 순서와 이번 화 확정 값을 정하고, 쓰기에 직전 화 본문 전체를 넣어요. 화당 AI 호출이 하나 늘어요">스토리보드 ${on ? '켜짐' : '꺼짐'}</button></div>`;
}

Object.assign(actions, {
  async boardMake(n) {
    const e = ep(n);
    if (e.storyboard && e.storyboard.made_by !== 'ai' && !(await askConfirm('작가가 고친 스토리보드예요. 새로 만들면 고친 내용이 사라져요. 다시 만들까요?', { ok: '다시 만들기', danger: true }))) return;
    S.boardEdit = null;
    await startJob('board', Number(n));
  },
  async boardToggle() {
    const on = !boardOn();
    await run('설정 바꾸는 중', async () => {
      S.project = await api('PUT', `/projects/${enc(S.name)}/storyboard-setting`, { on });
    });
  },
  async boardWrite(arg) {
    const [n, mode] = String(arg).split(':');
    await startJob('write', Number(n), { ...(mode ? { board: mode } : {}), ...cueWriteArg(Number(n)) });
  },
  boardEdit(n) {
    S.boardEdit = { key: `${S.name}:${n}`, draft: JSON.parse(JSON.stringify(ep(n).storyboard)) };
    render();
  },
  boardCancel() {
    S.boardEdit = null;
    render();
  },
  boardScene(arg) {
    const d = S.boardEdit && S.boardEdit.draft;
    if (!d) return;
    if (arg === 'add') d.scenes.push({ place: '', spot: '', time: '', present: [], events: [], goal: '', turn: '', end_state: '' });
    else d.scenes.splice(Number(String(arg).split(':')[1]), 1);
    render();
  },
  async boardSave(n) {
    await run('스토리보드 저장하는 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/episodes/${n}/storyboard`, S.boardEdit.draft);
      S.boardEdit = null;
      toast('스토리보드를 저장했어요');
    });
  },
  async boardDrop(n) {
    if (!(await askConfirm(`${n}화 스토리보드를 지울까요?`, { ok: '지우기', danger: true }))) return;
    await run('스토리보드 지우는 중', async () => {
      await saveIfDirty();
      S.project = await api('DELETE', `/projects/${enc(S.name)}/episodes/${n}/storyboard`);
      S.boardEdit = null;
      toast('스토리보드를 지웠어요');
    });
  },
});

(() => {
  const css = document.createElement('style');
  css.textContent = `
.w-board { display: flex; flex-direction: column; gap: 12px; }
.bd-card { gap: 12px; }
.bd-head { gap: 8px; align-items: center; flex-wrap: wrap; }
.bd-title { font-size: 1.0625rem; margin: 0; }
.bd-h { font-size: 0.9375rem; margin: 4px 0; }
.bd-sec { display: flex; flex-direction: column; gap: 6px; }
.bd-row { display: grid; grid-template-columns: 9em 1fr; gap: 8px; }
.bd-k { color: var(--text-2); font-size: 0.8125rem; font-weight: 700; }
.bd-list, .bd-scenes { margin: 0; padding-left: 1.25em; display: flex; flex-direction: column; gap: 6px; }
.bd-table { border-collapse: collapse; font-size: 0.8125rem; width: 100%; }
.bd-table th, .bd-table td { border-bottom: 1px solid var(--rule); padding: 4px 6px; text-align: left; vertical-align: top; }
.bd-table thead th { font-size: 0.75rem; font-weight: 500; color: var(--muted); border-bottom-color: var(--line); }
.bd-win { white-space: pre-wrap; font-size: 0.8125rem; background: var(--bg); padding: 8px; border-radius: 8px; }
.bd-fs { border: 1px solid var(--line); border-radius: 8px; padding: 8px 12px; display: flex; flex-direction: column; gap: 6px; }
.bd-form textarea { width: 100%; }
.bd-actions { flex-wrap: wrap; }
.bd-fill { flex: 1 1 auto; }
.bd-done > summary { cursor: pointer; font-weight: 700; }
@media (max-width: 640px) { .bd-row { grid-template-columns: 1fr; } }`;
  document.head.appendChild(css);
})();

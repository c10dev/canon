/* 나만의 문체: 스타일 프로필의 '가끔 쓰는 장치' 칸, 작품 문체 화면의 '내 수정에서 배우기' 카드, 라이브러리 항목의 버전 목록.
   app.js 의 S, actions, api, run, render, input, markDirty, saveIfDirty, loadStyleLink 를 그대로 쓴다.
   서버는 web.py 의 '2-1. 내 수정에서 배우기' 와 /api/styles/{id}/versions. */
'use strict';

Object.assign(S, {
  editStats: null,   // GET /style/edits: 수정 기록 수, 배울 수 있는 수
  learnPicks: {},    // 후보 번호 → 체크 여부 (없으면 넣지 않은 후보는 체크)
  libVersions: null, // 라이브러리 항목의 버전 목록
  libNote: '',       // 다음 저장의 버전 메모
});

const RULE_KINDS = { do: '지킬 것', dont: '피할 것', banned: '금지 표현', marker: '문체 표지', device: '가끔 쓰는 장치' };

async function learnLoad() {
  S.editStats = await api('GET', `/projects/${enc(S.name)}/style/edits`).catch(() => null);
}

async function libVersionsLoad() {
  S.libVersions = S.lib && S.lib.id ? await api('GET', `/styles/${S.lib.id}/versions`).catch(() => null) : null;
}

// ----- 가끔 쓰는 장치 (profileFields 가 부른다) -----

function deviceFields(base, root) {
  const prof = getPath(bindRoot(root), base);
  prof.devices = prof.devices || [];
  const o = (x = {}) => (root ? { ...x, root } : x);
  const rows = prof.devices.map((_, i) => {
    const b = `${base}.devices.${i}`;
    return `<div class="device-row">
      <div class="grid-2">
        ${input('장치 이름', b + '.name', o({ placeholder: '예: 자문자답 망상' }))}
        ${input('쓰는 상황', b + '.when', o({ placeholder: '예: 상대의 작은 반응에 혼자 설렐 때' }))}
        ${input('알아보는 글자', b + '.cues', o({ kind: 'list', rows: 2, hint: '한 화에 합쳐 두 번 이상 나오면 쓴 화로 쳐요', placeholder: '예: 다는 건\n거지?' }))}
        ${input('몇 화에 한 번까지', b + '.every', o({ type: 'number', min: 0, hint: '0 이면 간격 없이 상황이 올 때만' }))}
      </div>
      <div class="row" style="align-items:flex-start;flex-wrap:nowrap">
        <div style="flex:1">${input('예시 (써도 되는 화에만 보여 줘요)', b + '.example', o({ rows: 2 }))}</div>
        <button class="btn icon-btn danger" style="margin-top:26px" data-action="deviceRemove" data-arg="${root || ''}|${i}" aria-label="장치 ${i + 1} 삭제">✕</button>
      </div></div>`;
  }).join('');
  return `<div class="between"><h3>가끔 쓰는 장치 <span class="small" style="font-weight:400">특정 상황에만, 몇 화에 한 번 쓰는 장면 장치. 최근 화에서 쓴 화를 세어 이번 화에 쓸지 정해 줘요</span></h3><button class="btn small" data-action="deviceAdd" data-arg="${root || ''}">+ 장치</button></div>
    ${rows || '<div class="small">아직 없어요. 레퍼런스의 버릇이 매 화 반복되면 규칙이나 대표 문단에서 빼고 여기에 적으세요.</div>'}`;
}

// ----- 내 수정에서 배우기 (작품 문체 화면) -----

function learnPicked(i, s) {
  return s.applied ? false : S.learnPicks[i] !== false;
}

function suggestionRow(s, i) {
  const n = (ref) => ref.split(':')[0];
  const detail = s.kind === 'device'
    ? `<div class="small">${s.note ? `상황: ${esc(s.note)} · ` : ''}${s.cues.length ? `알아보는 글자: ${s.cues.map((c) => `'${esc(c)}'`).join(', ')} · ` : ''}${s.every ? `${s.every}화에 한 번까지` : '간격 없음'}</div>`
    : s.kind === 'marker' && s.note ? `<div class="small">${esc(s.note)}</div>` : '';
  const pairs = s.pairs.map((x) => `<div class="learn-pair"><a class="small" href="${base()}/write/${n(x.ref)}">${esc(n(x.ref))}화</a>
      <div><del>${esc(x.before)}</del></div><div><ins>${esc(x.after)}</ins></div></div>`).join('');
  return `<label class="check-row${s.applied ? ' done' : ''}">
      <input type="checkbox" data-learn-pick="${i}"${learnPicked(i, s) ? ' checked' : ''}${s.applied ? ' disabled' : ''}>
      <span style="flex:1;min-width:0">
        <span class="chip">${RULE_KINDS[s.kind] || esc(s.kind)}</span>${s.applied ? ' <span class="chip finalized">넣음</span>' : ''}
        <strong>${esc(s.text)}</strong>
        ${detail}
        ${s.replaces ? `<div class="small">바꿀 규칙: <del>${esc(s.replaces)}</del></div>` : ''}
        ${s.reason ? `<div class="small">${esc(s.reason)}</div>` : ''}
        <details><summary class="small">근거 수정 ${s.evidence.length}개</summary>${pairs}</details>
      </span></label>`;
}

function learnCard() {
  const st = S.editStats;
  const r = P().style_learning;
  const linked = S.styleLink && ['same', 'changed'].includes(S.styleLink.state);
  const short = st && st.usable < st.min;
  const count = st
    ? `본문을 고친 기록 ${st.total}건 중 배울 수 있는 것 ${st.usable}건${short ? ` · ${st.min}건부터 찾을 수 있어요` : ''}`
    : '';
  // 고친 기록이 기준보다 적고 지난 후보도 없으면 찾을 수 없으니 한 줄로 줄인다
  if ((short || !st) && !r) {
    return `<section class="card tight"><div class="between"><h2>내 수정에서 배우기</h2><span class="small">${st ? `배울 수 있는 수정 ${st.usable}건 · ${st.min}건부터 되풀이되는 고침을 찾아요` : ''}</span></div></section>`;
  }
  const open = r && r.suggestions.some((s) => !s.applied);
  const list = r ? `<div class="note plain">${esc(r.summary || '')}<div class="small">${fmtDate(r.at)} · 수정 ${r.edits_used}건을 봤어요</div></div>
      ${r.suggestions.length ? r.suggestions.map(suggestionRow).join('') : '<div class="small">두 번 이상 되풀이된 고침을 찾지 못했어요. 본문을 더 고친 뒤 다시 찾아 보세요.</div>'}
      ${open && linked ? `<label class="check-row"><input type="checkbox" id="learn-push"${S.styleLink.state === 'same' && !(S.styleLink.theirs || []).length ? ' checked' : ''}><span>라이브러리 '${esc(S.styleLink.name)}' 에도 새 버전으로 올리기<br><span class="small">다른 작품은 다시 적용하기 전까지 그대로예요${(S.styleLink.theirs || []).length ? `. 라이브러리가 ${S.styleLink.version}번 버전으로 더 새로워서, 올리면 그쪽에서 바뀐 칸(${S.styleLink.theirs.map((c) => esc(c.label)).join(', ')})이 덮여요` : ''}</span></span></label>` : ''}
      <div class="row">${open ? '<button class="btn primary small" data-action="learnApply">고른 규칙 적용</button>' : ''}<button class="btn small" data-action="learnDismiss">후보 지우기</button></div>` : '';
  return `<section class="card tight">
      <div class="between"><h2>내 수정에서 배우기</h2><span class="small">${count}</span></div>
      <div class="small">AI 본문을 고친 기록에서 되풀이되는 고침을 찾아 규칙 후보로 보여 줘요. 근거가 두 번 이상인 것만 내고, 고른 것만 이 작품 문체에 넣어요. 되돌린 수정, 동선 맞추기, 새로 써 넣기만 한 것은 보지 않아요.</div>
      <div><button class="btn dark small" data-action="learnRun"${short || !st ? ' disabled' : ''}>${r ? '다시 찾기' : '수정 기록에서 규칙 찾기'}</button></div>
      ${list}
    </section>`;
}

// ----- 라이브러리 항목의 버전 -----

function changeLines(c) {
  if (c.added || c.removed) {
    const items = [...(c.added || []).map((x) => `<div class="small">+ ${esc(x)}</div>`), ...(c.removed || []).map((x) => `<div class="small"><del>− ${esc(x)}</del></div>`)];
    return `<div><strong class="small">${esc(c.label)}</strong>${items.join('') || '<div class="small">순서나 빈도만 바뀜</div>'}</div>`;
  }
  return `<div><strong class="small">${esc(c.label)}</strong><div class="small"><del>${esc(c.before || '(비어 있음)')}</del> → ${esc(c.after || '(비어 있음)')}</div></div>`;
}

function versionsCard() {
  const vs = S.libVersions || [];
  const rows = vs.map((v) => {
    const changes = [...v.changes.map(changeLines), v.baseline_changed ? '<div class="small"><strong>기준 지표</strong> 다시 잼</div>' : ''].join('');
    return `<li class="version-row">
        <div class="between"><span><strong>${v.number}번</strong> <span class="small">${fmtDate(v.at)}</span>${v.current ? ' <span class="chip finalized">지금</span>' : ''}</span>
          ${v.current ? '' : `<button class="btn small" data-action="libRestore" data-arg="${v.number}">이 버전으로 복원</button>`}</div>
        <div class="small">${esc(v.note)}</div>
        ${changes ? `<details><summary class="small">바뀐 칸 (앞 버전과 비교)</summary>${changes}</details>` : ''}
      </li>`;
  }).join('');
  return `<section class="card tight">
      <div class="between"><h2>버전</h2><span class="small">프로필이나 기준 지표가 바뀔 때마다 남겨요 (최근 30개)</span></div>
      <div class="field"><label for="lib-note">다음 저장의 버전 메모 <span class="hint">비우면 바뀐 칸 이름을 적어요</span></label>
        <input id="lib-note" type="text" data-local="libNote" value="${esc(S.libNote || '')}" placeholder="예: 망상 장면을 가끔 쓰는 장치로 옮김"></div>
      ${rows ? `<ul class="version-list">${rows}</ul>` : '<div class="small">아직 버전이 없어요.</div>'}
    </section>`;
}

Object.assign(actions, {
  deviceAdd(root) {
    const prof = root === 'lib' ? S.lib.profile : P().style;
    (prof.devices = prof.devices || []).push({ name: '', when: '', cues: [], every: 5, example: '' });
    if (root === 'lib') { S.libDirty = true; renderSavebar(); }
    else markDirty();
    render();
  },
  deviceRemove(arg) {
    const [root, i] = arg.split('|');
    const prof = root === 'lib' ? S.lib.profile : P().style;
    prof.devices.splice(Number(i), 1);
    if (root === 'lib') { S.libDirty = true; renderSavebar(); }
    else markDirty();
    render();
  },
  async learnRun() {
    await run('수정 기록에서 규칙을 찾는 중… (최대 1분)', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/style/learn`);
      S.learnPicks = {};
      const k = P().style_learning.suggestions.length;
      toast(k ? `규칙 후보 ${k}개를 찾았어요. 고른 것만 넣어요.` : '되풀이된 고침을 찾지 못했어요');
    });
  },
  async learnApply() {
    const r = P().style_learning;
    const picks = r.suggestions.map((s, i) => (learnPicked(i, s) ? i : -1)).filter((i) => i >= 0);
    if (!picks.length) return toast('넣을 후보를 고르세요', true);
    const push = !!($('#learn-push') && $('#learn-push').checked);
    await run('규칙을 넣는 중', async () => {
      await saveIfDirty();
      const res = await api('POST', `/projects/${enc(S.name)}/style/learn/apply`, { picks, push });
      S.project = res.project;
      S.learnPicks = {};
      if (res.entry) S.libs = await api('GET', '/styles').catch(() => S.libs);
      await loadStyleLink();
      toast(`규칙 ${res.applied}개를 이 작품 문체에 넣었어요${res.entry ? ` · 라이브러리 ${res.entry.version}번 버전` : ''}${res.notes.length ? '. ' + res.notes.join(' ') : ''}`, !!res.notes.length);
    });
  },
  async learnDismiss() {
    if (!confirm(`찾은 규칙 후보를 지울까요? 이미 넣은 규칙은 그대로예요.${S.dirty ? ' 저장하지 않은 다른 변경도 함께 저장해요.' : ''}`)) return;
    await run('지우는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/style/learn/dismiss`);
    });
  },
  async libRestore(n) {
    const msg = S.libDirty ? '\n저장하지 않은 변경은 사라져요.' : '';
    const used = (S.lib.used_by || []).length ? `\n이 문체를 쓰는 작품(${S.lib.used_by.join(', ')})은 다시 적용해야 바뀌어요.` : '';
    if (!confirm(`${n}번 버전으로 되돌릴까요? 지금 상태도 버전으로 남아 있어 다시 돌아올 수 있어요.${msg}${used}`)) return;
    await run('되돌리는 중', async () => {
      S.lib = await api('POST', `/styles/${S.lib.id}/versions/${n}/restore`);
      S.libDirty = false;
      await libVersionsLoad();
      toast(`${n}번 버전으로 되돌렸어요 (지금 ${S.lib.version}번 버전)`);
    });
  },
});

document.addEventListener('change', (e) => {
  const t = e.target;
  if (t.dataset && t.dataset.learnPick !== undefined) S.learnPicks[t.dataset.learnPick] = t.checked;
});

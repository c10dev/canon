/* 문단 연습장 (작품 밖 화면 #/studio[/<세션 id>]). 서버는 canon/studio.py · pipeline.draft_paragraph, 엔드포인트는 /api/studio.
   상황 카드(SceneCard)로 AI 안을 여러 개 받거나 작가가 직접 써 보고, 문단 지표(studio.measure)로 견준다. 작품에는 넣지 않는다.
   카드는 S.stuForm 에 고치고, 칸을 벗어날 때(change) 조용히 저장한다. AI 안 쓰기 · 시도 저장 전에도 먼저 저장한다. */

DRAFT_ROOTS.stuForm = () => S.stuForm;

async function stuLoad(id) {
  const home = await api('GET', '/studio');
  S.stuList = home.sessions;
  S.stuDrills = home.drills;
  S.stuLength = home.length;
  S.stuMax = home.max_tries;
  if (!id) { S.stu = null; S.stuForm = null; return; }
  if (!S.stu || S.stu.id !== id) { S.stuWrite = ''; S.stuBase = 0; S.stuEdit = 0; }
  stuSet(await api('GET', `/studio/${enc(id)}`));
}

/** 서버가 돌려준 세션을 받는다. 고치던 카드가 있으면 서버 것으로 바꾼다 (저장 뒤에만 부르므로 잃는 고침은 없다). */
function stuSet(s) {
  S.stu = s;
  S.stuForm = { title: s.title, card: JSON.parse(JSON.stringify(s.card)) };
  S.stuDirty = false;
}

function viewStudio() {
  return S.stu ? stuSession() : stuHome();
}

function stuHome() {
  const list = S.stuList || [];
  const head = header('작품 밖 도구', '문단 연습장', '상황 카드 하나로 한 문단짜리 장면을 AI에게 여러 안 쓰게 하거나 직접 써 보고, 감정 이름 · 쇠맛 · 길이 같은 문단 지표로 견줘요. 작품에는 들어가지 않아요.',
    '<button type="button" class="btn primary" data-action="stuNew">+ 새 연습</button>');
  if (!list.length) {
    return `${head}<section class="card empty"><h2>아직 연습이 없어요</h2><p class="small">누가, 어디서, 무슨 일을 하는지 적고 '감정 이름 없이' 같은 연습을 고르면 AI가 서로 다른 안을 써요. 같은 카드로 직접 써 보거나 AI 안을 고쳐 쓸 수도 있어요.</p>
      <div class="row"><button type="button" class="btn primary" data-action="stuNew">새 연습 만들기</button></div></section>`;
  }
  const drill = (id) => (S.stuDrills || []).find((d) => d.id === id);
  const cards = list.map((x) => {
    const meta = [`시도 ${x.tries}개`, x.authored ? `직접 쓴 글 ${x.authored}개` : '', x.starred ? `고른 것 ${x.starred}개` : '', x.style_name ? `문체 ${x.style_name}` : '', fmtDateTime(x.updated_at)].filter(Boolean).join(' · ');
    const chips = x.drills.map((d) => (drill(d) ? `<span class="chip">${esc(drill(d).label)}</span>` : '')).join('');
    return `<a class="card" href="#/studio/${enc(x.id)}"><h3>${esc(x.title)}</h3>${chips ? `<div class="row">${chips}</div>` : ''}<div class="small">${esc(meta)}</div></a>`;
  }).join('');
  return `${head}<div class="grid-auto">${cards}</div>`;
}

function stuSession() {
  const s = S.stu;
  const full = s.tries.length >= (S.stuMax || 40);
  const n = Number(S.stuN) || 3;
  const right = `<a class="btn" href="#/studio">목록으로</a>
    <button type="button" class="btn" data-action="stuDuplicate">카드 복제</button>
    <button type="button" class="btn danger" data-action="stuDelete">지우기</button>
    <button type="button" class="btn primary" data-action="stuDraft"${full ? ' disabled title="시도가 꽉 찼어요. 지울 시도를 고르세요"' : ''}>AI 안 ${n}개 쓰기</button>`;
  const head = header('문단 연습장', s.title, s.style_name ? `문체: ${esc(s.style_name)}` : '문체를 고르지 않았어요. 기본 문체 규칙으로 써요.', right);
  return `${head}<div class="cols"><div class="col">${stuCardForm()}</div><div class="col wide">${stuWriteCard()}${stuTries()}</div></div>`;
}

// ----- 상황 카드 -----

function stuCardForm() {
  const f = S.stuForm;
  const c = f.card;
  const o = { root: 'stuForm' };
  const people = c.people.map((x, i) => `<div class="card" style="padding:var(--pad-card-tight)">
      <div class="grid-2">${input('이름', `card.people.${i}.name`, o)}${input('말투', `card.people.${i}.speech`, { ...o, placeholder: '예: 짧은 반말' })}</div>
      ${input('성격 · 처지', `card.people.${i}.note`, { ...o, placeholder: '한두 줄' })}
      <div class="row"><button type="button" class="btn small" data-action="stuPersonDrop" data-arg="${i}">인물 빼기</button></div></div>`).join('');
  const drills = (S.stuDrills || []).map((d) => `<label class="check-row"><input type="checkbox" data-stu-drill="${esc(d.id)}"${c.drills.includes(d.id) ? ' checked' : ''}>
      <span><strong>${esc(d.label)}</strong>${d.auto ? '' : ' <span class="small">· 읽고 판단</span>'}<br><span class="small">${esc(d.rule)}</span></span></label>`).join('');
  const libs = S.libs || [];
  const styleSel = `<div class="field"><label for="stu-style">문체</label><select id="stu-style" data-root="stuForm" data-bind="card.style_id">
      <option value="">고르지 않음 (기본 문체 규칙)</option>${libs.map((l) => `<option value="${esc(l.id)}"${l.id === c.style_id ? ' selected' : ''}>${esc(l.name)}</option>`).join('')}
      ${c.style_id && !libs.some((l) => l.id === c.style_id) ? `<option value="${esc(c.style_id)}" selected>찾지 못한 문체</option>` : ''}</select></div>`;
  const [lo, hi] = S.stuLength || [100, 1200];
  return `<section class="card">
      <div class="between"><h2>상황 카드</h2><span class="small" id="stu-saved">${S.stuDirty ? '저장하지 않은 고침이 있어요' : '빈 칸은 AI가 정해요'}</span></div>
      ${input('제목', 'title', { ...o, placeholder: '비우면 무슨 일로 지어요' })}
      ${input('무슨 일', 'card.action', { ...o, rows: 2, placeholder: '예: 비 오는 정류장에서 우산을 건넨다' })}
      ${input('독자에게 남길 것', 'card.aim', { ...o, placeholder: '감정 이름 대신 보여 줄 것, 예: 말하지 못한 미안함' })}
      <div class="grid-2">${input('장소', 'card.place', o)}${input('때 · 날씨', 'card.time', o)}</div>
      <div class="grid-2">${input('시점 인물', 'card.pov', { ...o, placeholder: '이름, 비우면 AI가' })}${input('목표 글자 수', 'card.length', { ...o, type: 'number', min: lo, max: hi })}</div>
      <h3>인물</h3>${people || '<p class="small">아직 인물이 없어요.</p>'}
      <div class="row"><button type="button" class="btn small" data-action="stuPersonAdd">+ 인물</button></div>
      <h3>연습</h3><div style="display:grid;gap:var(--gap-row)">${drills}</div>
      ${input('더 지킬 것', 'card.extra', { ...o, rows: 2, placeholder: '예: 마지막 문장은 대사로' })}
      ${styleSel}
      <details${c.source ? ' open' : ''}><summary>고쳐 쓸 출발 글</summary>${input('출발 글', 'card.source', { ...o, rows: 5, placeholder: '다른 글의 한 문단을 넣으면 같은 상황을 고쳐 써요' })}</details>
      <div class="row"><button type="button" class="btn small${S.stuDirty ? ' primary' : ''}" data-action="stuSaveCard">카드 저장</button>
        <label class="small">한 번에 <select data-local="stuN" aria-label="AI 안 수">${[1, 2, 3, 4].map((k) => `<option${k === (Number(S.stuN) || 3) ? ' selected' : ''}>${k}</option>`).join('')}</select>개</label></div>
    </section>`;
}

/** 카드를 저장한다. quiet 면 덮개 없이 (칸을 벗어날 때). 실패하면 알린다. */
async function stuSaveCard(quiet = false) {
  if (!S.stu || !S.stuDirty) return true;
  const id = S.stu.id;
  const body = JSON.parse(JSON.stringify(S.stuForm));
  // 칸을 벗어나며 다른 화면으로 옮겼으면 받은 세션을 놓지 않는다 (옮긴 화면이 제 것을 읽는다)
  const save = async () => { const s = await api('PUT', `/studio/${enc(id)}`, body); if (S.stu && S.stu.id === id) stuSet(s); };
  if (!quiet) return run('카드를 저장하는 중', save);
  try {
    await save();
    const el = $('#stu-saved');
    if (el) el.textContent = '저장했어요';
    return true;
  } catch (e) {
    toast(e.message, true);
    return false;
  }
}

document.addEventListener('input', (e) => {
  if (e.target.dataset && e.target.dataset.root === 'stuForm') {
    S.stuDirty = true;
    const el = $('#stu-saved');
    if (el) el.textContent = '저장하지 않은 고침이 있어요';
  }
});
document.addEventListener('change', (e) => {
  const el = e.target;
  if (!el.dataset || S.route[0] !== 'studio' || !S.stuForm) return;
  if (el.dataset.stuDrill) {
    const ds = S.stuForm.card.drills.filter((d) => d !== el.dataset.stuDrill);
    S.stuForm.card.drills = el.checked ? [...ds, el.dataset.stuDrill] : ds;
    S.stuDirty = true;
  }
  if (el.dataset.root === 'stuForm' || el.dataset.stuDrill) stuSaveCard(true);
  if (el.dataset.local === 'stuN') render();  // 머리 버튼 글자(AI 안 n개)
});

// ----- 직접 쓰기 -----

function stuWriteCard() {
  const base = S.stuBase ? S.stu.tries.find((t) => t.no === S.stuBase) : null;
  const what = base ? `${base.no}번 ${base.by === 'ai' ? 'AI 안' : '글'}을 고쳐 써요` : '같은 카드로 직접 써요';
  return `<section class="card" id="stu-write">
      <div class="between"><h2>직접 쓰기</h2><span class="small">${esc(what)}</span></div>
      <div class="field"><label for="stu-text" class="sr-only">쓸 글</label><textarea id="stu-text" rows="6" data-local="stuWrite" data-autogrow placeholder="카드의 상황을 문단 하나로 써 보세요">${esc(S.stuWrite || '')}</textarea></div>
      <div class="row"><button type="button" class="btn primary small" data-action="stuAddTry">시도로 남기기</button>
        ${base || S.stuWrite ? '<button type="button" class="btn small" data-action="stuWriteClear">비우기</button>' : ''}</div>
    </section>`;
}

// ----- 시도 목록 -----

function stuChecks(m) {
  const chip = (c) => `<span class="chip${c.ok === true ? ' ok' : c.ok === false ? ' bad' : ''}" title="${esc(c.why)}">${c.ok === true ? '✓' : c.ok === false ? '✕' : '?'} ${esc(c.label)}</span>`;
  const facts = [`${m.chars.toLocaleString()}자`, `${m.sentences}문장`, `문장 평균 ${m.sentence_len_mean}자`, m.sentence_len_cv != null ? `길이 변화폭 ${m.sentence_len_cv}` : '', `대사 ${m.dialogue_pct}%`].filter(Boolean).join(' · ');
  const why = m.checks.filter((c) => c.ok === false).map((c) => `${c.label}: ${c.why}`);
  const hits = m.hits.map((h) => `«${esc(h.quote)}» ${esc(h.kind === 'cliche' ? '상투 표현' : h.name)}`);
  const marks = m.markers.filter((x) => x.count).map((x) => `'${esc(x.text)}' ${x.count}회`);
  return `${m.checks.length ? `<div class="row">${m.checks.map(chip).join('')}</div>` : ''}
    <div class="small">${esc(facts)}</div>
    ${why.length ? `<div class="small">${why.map(esc).join('<br>')}</div>` : ''}
    ${hits.length ? `<div class="small">걸린 곳: ${hits.join(' · ')}</div>` : ''}
    ${marks.length ? `<div class="small">문체 표지: ${marks.join(' · ')}</div>` : ''}`;
}

function stuTryCard(t) {
  const m = S.stu.measures[String(t.no)];
  const who = t.by === 'ai' ? `<span class="chip ai">AI ${t.no}번</span>` : `<span class="chip">직접 ${t.no}번</span>`;
  const base = t.base ? `<span class="small">${t.base}번을 고쳐 씀</span>` : '';
  const editing = S.stuEdit === t.no;
  const body = editing
    ? `<div class="field"><label for="stu-edit-${t.no}" class="sr-only">${t.no}번 고치기</label><textarea id="stu-edit-${t.no}" rows="6" data-autogrow>${esc(t.text)}</textarea></div>
       <div class="row"><button type="button" class="btn small primary" data-action="stuEditSave" data-arg="${t.no}">저장</button><button type="button" class="btn small" data-action="stuEditCancel">그만두기</button></div>`
    : `<div class="rw-text">${esc(t.text)}</div>`;
  const btns = editing ? '' : `<div class="row">
      <button type="button" class="btn small${t.star ? ' primary' : ''}" data-action="stuStar" data-arg="${t.no}" aria-pressed="${t.star}">${t.star ? '★ 고름' : '☆ 고르기'}</button>
      <button type="button" class="btn small" data-action="stuRewrite" data-arg="${t.no}">고쳐 쓰기</button>
      ${t.by === 'author' ? `<button type="button" class="btn small" data-action="stuEditOpen" data-arg="${t.no}">고치기</button>` : ''}
      <button type="button" class="btn small" data-action="stuCopy" data-arg="${t.no}">복사</button>
      <button type="button" class="btn small danger" data-action="stuDrop" data-arg="${t.no}">지우기</button></div>`;
  return `<section class="card" id="stu-try-${t.no}">
      <div class="between"><div class="row">${who}${base}${t.note ? `<span class="small">${esc(t.note)}</span>` : ''}</div><span class="small">${esc(fmtDateTime(t.at))}</span></div>
      ${body}${m ? stuChecks(m) : ''}${btns}</section>`;
}

function stuTries() {
  const ts = [...S.stu.tries].reverse();
  if (!ts.length) return '<section class="card empty"><h2>아직 시도가 없어요</h2><p class="small">카드를 채우고 머리의 \'AI 안 쓰기\'를 누르거나 위 칸에 직접 써 보세요.</p></section>';
  const star = ts.filter((t) => t.star);
  return [...star, ...ts.filter((t) => !t.star)].map(stuTryCard).join('');
}

// ----- 동작 -----

Object.assign(actions, {
  async stuNew() {
    await run('새 연습을 만드는 중', async () => {
      const s = await api('POST', '/studio', { title: '', card: {} });
      location.hash = `#/studio/${enc(s.id)}`;
    }, { render: 'never' });
  },
  async stuSaveCard() {
    if (!S.stuDirty) return toast('바뀐 칸이 없어요');
    if (await stuSaveCard()) toast('카드를 저장했어요');
  },
  stuPersonAdd() {
    S.stuForm.card.people.push({ name: '', note: '', speech: '' });
    S.stuDirty = true;
    S.focusTarget = `#f-card-people-${S.stuForm.card.people.length - 1}-name`;
    render();
  },
  async stuPersonDrop(i) {
    S.stuForm.card.people.splice(Number(i), 1);
    S.stuDirty = true;
    await stuSaveCard(true);
    render();
  },
  async stuDraft() {
    const n = Number(S.stuN) || 3;
    await run(`AI 안 ${n}개를 쓰는 중… (최대 1분)`, async () => {
      if (S.stuDirty) stuSet(await api('PUT', `/studio/${enc(S.stu.id)}`, S.stuForm));
      const before = S.stu.tries.length;
      stuSet(await api('POST', `/studio/${enc(S.stu.id)}/draft`, { n }));
      toast(`AI 안 ${S.stu.tries.length - before}개를 남겼어요`);
    });
  },
  async stuAddTry() {
    const text = (S.stuWrite || '').trim();
    if (!text) return toast('쓸 글을 적으세요', true);
    await run('시도로 남기는 중', async () => {
      if (S.stuDirty) stuSet(await api('PUT', `/studio/${enc(S.stu.id)}`, S.stuForm));
      stuSet(await api('POST', `/studio/${enc(S.stu.id)}/tries`, { text, base: S.stuBase || 0 }));
      S.stuWrite = '';
      S.stuBase = 0;
      toast('남겼어요');
    });
  },
  stuWriteClear() {
    S.stuWrite = '';
    S.stuBase = 0;
    render();
  },
  async stuRewrite(no) {
    const t = S.stu.tries.find((x) => x.no === no);
    if ((S.stuWrite || '').trim() && S.stuBase !== no && !(await askConfirm('직접 쓰기 칸의 글을 이 시도로 바꿀까요? 쓰던 글은 사라져요.', { ok: '바꾸기', danger: true }))) return;
    S.stuWrite = t.text;
    S.stuBase = no;
    S.focusTarget = '#stu-text';
    render();
  },
  stuEditOpen(no) {
    S.stuEdit = no;
    S.focusTarget = `#stu-edit-${no}`;
    render();
  },
  stuEditCancel() {
    S.stuEdit = 0;
    render();
  },
  async stuEditSave(no) {
    const el = $(`#stu-edit-${no}`);
    await run('고친 글을 저장하는 중', async () => {
      stuSet(await api('PUT', `/studio/${enc(S.stu.id)}/tries/${no}`, { text: el ? el.value : '' }));
      S.stuEdit = 0;
    });
  },
  async stuStar(no) {
    const t = S.stu.tries.find((x) => x.no === no);
    await run('고르는 중', async () => {
      if (S.stuDirty) stuSet(await api('PUT', `/studio/${enc(S.stu.id)}`, S.stuForm));
      stuSet(await api('PUT', `/studio/${enc(S.stu.id)}/tries/${no}`, { star: !t.star }));
    });
  },
  async stuCopy(no) {
    const t = S.stu.tries.find((x) => x.no === no);
    try {
      await copyPlain(t.text);
      toast('복사했어요');
    } catch (e) {
      toast(e.message, true);
    }
  },
  async stuDrop(no) {
    if (!(await askConfirm(`${no}번 시도를 지울까요? 되돌릴 수 없어요.`, { ok: '지우기', danger: true }))) return;
    await run('지우는 중', async () => {
      if (S.stuDirty) stuSet(await api('PUT', `/studio/${enc(S.stu.id)}`, S.stuForm));
      stuSet(await api('DELETE', `/studio/${enc(S.stu.id)}/tries/${no}`));
      if (S.stuBase === no) S.stuBase = 0;
    });
  },
  async stuDuplicate() {
    await run('카드를 복제하는 중', async () => {
      if (S.stuDirty) stuSet(await api('PUT', `/studio/${enc(S.stu.id)}`, S.stuForm));
      const s = await api('POST', `/studio/${enc(S.stu.id)}/duplicate`);
      location.hash = `#/studio/${enc(s.id)}`;
      toast('카드를 복제했어요. 한 칸만 바꿔 다시 써 보세요');
    }, { render: 'never' });
  },
  async stuDelete() {
    if (!(await askConfirm(`'${S.stu.title}' 연습을 지울까요? 시도 ${S.stu.tries.length}개도 함께 지워요. 되돌릴 수 없어요.`, { ok: '지우기', danger: true }))) return;
    await run('지우는 중', async () => {
      await api('DELETE', `/studio/${enc(S.stu.id)}`);
      S.stu = null;
      location.hash = '#/studio';
    }, { render: 'never' });
  },
});

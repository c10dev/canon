/* 화 끼워 넣기 · 빼기 · 마지막 화 지우기. app.js 의 S, actions, api, render, input 을 그대로 쓴다.
   아직 안 쓴 화 앞(또는 마지막 화 뒤)에 외전이나 중간 이야기를 넣으면 뒤 화가 플롯과 확정 상태를 그대로 둔 채 한 칸씩 밀리고,
   구간 · 아크 · 부 범위, 총 화수, 복선 · 인과율 요소 · 이야기 줄기의 화 번호도 함께 옮겨진다.
   서버는 pipeline.insert_episode / remove_episode, 새 화 AI 초안은 백그라운드 작업 'plot_one' (pipeline.draft_episode).
   본문이 있거나 반영한 마지막 화는 '이 화 지우기'(pipeline.delete_last: 반영 취소 → 본문 비우기 → 화 빼기)로 지운다.
   넣을 수 있는 자리는 pipeline.insert_range · renumber.last_fixed 와 같은 규칙이라 함께 고친다. */
'use strict';

Object.assign(S, {
  insForm: null,  // { at, title, summary, storyline, ai } 새 화 넣기 양식
  fitNext: false,  // 플롯 편집기의 'AI 로 이 화 채우기'가 뒤 화에 맞출지 (끼워 넣은 새 화는 늘 맞춘다)
});
DRAFT_ROOTS.insForm = () => S.insForm;

/** 번호를 옮길 수 없는 마지막 화: 본문이 있거나 상태를 반영한 화 (renumber.last_fixed 와 같은 규칙) */
function lastFixed() {
  const p = P();
  let n = 0;
  for (const e of p.episodes) {
    if (e.text || e.status === 'written' || e.status === 'finalized' || e.candidate) n = Math.max(n, e.plot.number);
  }
  for (const x of [...(p.history || []), ...(p.snapshots || []), ...(p.events || [])]) n = Math.max(n, x.episode);
  return n;
}

function lastPlotted() {
  return P().episodes.reduce((m, e) => Math.max(m, e.plot.number), 0);
}

function projectBusy() {
  return S.jobs.some((j) => j.status === 'running' && j.project === S.name);
}

/** 플롯 편집기의 '화 끼워 넣기' 칸. 안 쓴 화는 앞에 넣기 · 빼기, 마지막 화는 뒤에 넣기 */
function insertBlock(e) {
  const n = e.plot.number;
  const free = lastFixed() + 1;
  const before = n >= free;
  const after = n === lastPlotted() && n + 1 >= free;
  if (!before && !after) return '';
  const f = S.insForm;
  if (f && (f.at === n || (after && f.at === n + 1))) return insertForm(f);
  const dis = projectBusy() ? ' disabled title="AI 작업이 끝난 뒤에 할 수 있어요"' : '';
  return `<div class="field insert-tools"><span class="label">화 끼워 넣기 <span class="hint">외전이나 중간 이야기를 넣으면 뒤 화가 한 칸씩 밀려요</span></span>
      <div class="row">
        ${before ? `<button type="button" class="btn small" data-action="insOpen" data-arg="${n}"${dis}>${n}화 앞에 새 화 넣기</button>` : ''}
        ${after ? `<button type="button" class="btn small" data-action="insOpen" data-arg="${n + 1}"${dis}>${n}화 뒤에 새 화 넣기</button>` : ''}
        ${before ? `<button type="button" class="btn small danger" data-action="insRemove" data-arg="${n}"${dis}>${n}화 빼기</button>` : ''}
      </div></div>`;
}

/** 본문이 있거나 반영한 마지막 화 지우기 (pipeline.delete_last): 반영 취소 → 본문 비우기 → 화 빼기. 중간 화는 지우지 않는다 */
function deleteBlock(e) {
  const n = e.plot.number;
  if (n !== lastFixed() || !(e.text || e.status === 'written' || e.status === 'finalized' || e.candidate)) return '';
  const p = P();
  const applied = e.status === 'finalized' || [...(p.history || []), ...(p.snapshots || []), ...(p.events || [])].some((x) => x.episode >= n);
  const why = projectBusy() ? 'AI 작업이 끝난 뒤에 할 수 있어요'
    : autoOn() ? '자동 집필을 일시정지한 뒤에 할 수 있어요'
      : applied && !(p.snapshots || []).some((s) => s.episode === n - 1) ? `${n - 1}화 스냅샷이 없어 반영을 취소할 수 없어요` : '';
  const dis = why ? ` disabled title="${why}"` : '';
  return `<details class="field delete-tools"><summary class="small">이 화 지우기</summary>
      <div class="small" style="margin:6px 0">마지막으로 쓴 화만 지울 수 있어요. ${applied ? '상태 반영을 취소하고 ' : ''}본문 · 수정 기록 · 이전 판 · 삽화 프롬프트를 지워요. 지우기 전 작품 전체는 백업 파일로 남겨요.</div>
      <div class="row">
        <button type="button" class="btn small danger" data-action="delLast" data-arg="${n}"${dis}>${n}화 지우기</button>
        <button type="button" class="btn small" data-action="delLastText" data-arg="${n}"${dis}>본문만 지우고 플롯 남기기</button>
      </div></details>`;
}

function insertForm(f) {
  const lines = P().storylines || [];
  const opts = [['', '메인 줄기'], ...lines.map((s) => [s.id, `${s.kind} · ${s.title || s.id}`])]
    .map(([id, l]) => `<option value="${esc(id)}"${f.storyline === id ? ' selected' : ''}>${esc(l)}</option>`).join('');
  const moved = P().episodes.map((e) => e.plot.number).filter((k) => k >= f.at);
  const what = moved.length
    ? `지금 ${moved[0]}~${moved[moved.length - 1]}화가 ${moved[0] + 1}~${moved[moved.length - 1] + 1}화로 밀려요. 플롯과 확정 상태는 그대로이고, 구간 · 아크 범위와 복선 · 인과율 요소 · 이야기 줄기의 화 번호도 함께 옮겨요.`
    : '마지막 화 뒤에 붙여요. 마지막 구간이 한 화 늘어나요.';
  return `<div class="card insert-form">
      <div class="between"><h3>${f.at}화 자리에 새 화</h3><button type="button" class="btn small ghost" data-action="insCancel">취소</button></div>
      <div class="note info">${what} 총 화수가 1 늘어요.</div>
      ${input('제목', 'title', { root: 'insForm', placeholder: '예: 외전 · 등대지기의 겨울' })}
      ${input('어떤 화인지', 'summary', { root: 'insForm', rows: 3, placeholder: '무슨 일이 일어나는 화인지 한두 문장. AI가 앞뒤 화에 맞춰 나머지를 채워요' })}
      <div class="field"><label for="ins-line">이야기 줄기 <span class="hint">외전 · 과거 회상이면 그 줄기를 고르세요</span></label>
        <select id="ins-line" data-ins-line="1">${opts}</select></div>
      ${lines.length ? '' : `<div class="small">외전이나 과거 회상 줄기는 <a href="${base()}/lines">이야기 줄기</a> 화면에서 만들 수 있어요.</div>`}
      <label class="row" style="font-size:13px;gap:6px"><input type="checkbox" data-ins-ai="1"${f.ai ? ' checked' : ''}>넣은 뒤 AI가 앞뒤 화에 맞춰 플롯 채우기</label>
      <div class="row" style="margin-top:12px"><button type="button" class="btn primary" style="flex:1" data-action="insSubmit">${f.at}화에 넣기</button></div>
    </div>`;
}

/** 초안 화 하나를 앞뒤 화에 맞춰 AI 로 채우는 버튼 (작가가 적은 제목 · 요약 · 줄기는 살린다) */
function draftOneBtn(e) {
  if (e.status !== 'draft') return '';
  const b = jobBtn('plot_one', e.plot.number, 'AI로 이 화 채우기');
  return `<button type="button" class="btn" style="flex:1" data-action="insDraft" data-arg="${e.plot.number}"${b.attr}>${b.label}</button>`;
}

/** 'AI 로 이 화 채우기'가 뒤 화를 바꾸지 않는 화로 보고 맞출지. 끄면(기본) 작가가 적은 요약대로 마무리하고 뒤 화에 어긋난 점을 남긴다 */
function fitNextField(e) {
  const n = e.plot.number;
  if (e.status !== 'draft' || !ep(n + 1)) return '';
  return `<label class="small row" style="gap:6px;margin-top:8px"><input type="checkbox" data-fit-next${S.fitNext ? ' checked' : ''}> AI로 채울 때 ${n + 1}화에 맞추기</label>
    <div class="small">${S.fitNext ? `${n + 1}화를 바꾸지 않는 화로 보고, 그 시작으로 이어지게 채워요. ${n + 1}화에서 일어날 일은 이 화에서 일으키지 않아요.` : `적어 둔 요약대로 이 화를 마무리해요. ${n + 1}화와 어긋나게 된 점은 ${n + 1}화에 '다시 맞추기'로 표시해요.`}</div>`;
}

/** 앞 화를 뒤 화에 맞추지 않고 다시 짜며 남긴 표시. 이 화 플롯을 AI 로 다시 짜면 서버가 지우고, 확인했어요로도 지운다 */
function realignNote(e) {
  if (!e.realign) return '';
  const n = e.plot.number;
  const how = e.status === 'draft' ? `'AI로 이 화 채우기'를 누르면 바뀐 ${n - 1}화에 이어지게 다시 짜요. 직접 고치거나 대화로 다듬기에서 고쳐도 돼요.`
    : e.status === 'confirmed' ? `직접 고치거나, 초안으로 되돌린 뒤 'AI로 이 화 채우기'로 다시 짜요. 대화로 다듬기에서 고쳐도 돼요.`
      : '본문이 있는 화라 플롯은 그대로예요. 집필 화면의 다시 생성으로 본문을 맞추세요.';
  return `<div class="note warn"><strong>${n - 1}화를 다시 짜며 이 화와 어긋난 점</strong> · ${esc(e.realign)}
    <div class="between" style="margin-top:6px;gap:8px"><span class="small">${how}</span><button type="button" class="btn small" data-action="clearRealign" data-arg="${n}">확인했어요</button></div></div>`;
}

async function delLast(n, keepPlot) {
  const p = P();
  const e = ep(n);
  const parts = [];
  if (e.status === 'finalized') {
    parts.push(`${n}화 상태 반영을 취소해요 (${n > 1 ? `${n - 1}화 반영 직후` : '1화 시작 전'}로).`);
    const added = (p.history || []).filter((d) => d.episode >= n).flatMap((d) => d.new_characters || []).map((c) => c.name || c.id);
    const places = (p.elements || []).filter((el) => el.found_in === '본문' && el.found_ep >= n).map((el) => el.name);
    if (added.length) parts.push(`그 반영이 더한 인물(${added.join(', ')})도 빠져요.`);
    if (places.length) parts.push(`본문에서 등록한 장소(${places.join(', ')})도 빠져요.`);
  }
  if (e.text) parts.push(`본문 ${e.text.length.toLocaleString()}자와 수정 기록 · 이전 판 · 삽화 프롬프트를 지워요.`);
  parts.push(keepPlot ? '플롯은 확정된 채로 남아 다시 쓸 수 있어요.' : `플롯도 빼고${ep(n + 1) ? ' 뒤 화를 한 칸씩 당기고' : ''} 총 화수가 1 줄어요.`);
  if (!(await askConfirm(`${n}화 '${e.plot.title || '제목 없음'}'을(를) 지울까요?\n\n${parts.join('\n')}\n\n지우기 전 작품은 백업 파일로 남지만 화면에서 되돌릴 수는 없어요.`, { ok: '지우기', danger: true }))) return;
  await run('화를 지우는 중', async () => {
    await saveIfDirty();
    const r = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/delete`, { keep_plot: keepPlot });
    S.project = r.project;
    delete S.textDraft[n];
    delete S.deltas[n];
    delete S.deltaOrig[n];
    if (!keepPlot) S.selEp = null;
    toast(r.notes.join(' '));
    if (!keepPlot && ['write', 'review'].includes(S.route[2])) location.hash = `${base()}/arc`;
    else if (!keepPlot && S.route[2] === 'arc' && Number(S.route[3]) === n) location.replace(`${base()}/arc`);  // 그 화의 플롯 페이지: 화가 없어졌다
  });
}

document.addEventListener('change', (e) => {
  if (!e.target.dataset || e.target.dataset.fitNext === undefined) return;
  S.fitNext = e.target.checked;
  render();
});

document.addEventListener('change', (e) => {
  const t = e.target;
  if (!S.insForm || !t.dataset) return;
  if (t.dataset.insLine) S.insForm.storyline = t.value;
  if (t.dataset.insAi) S.insForm.ai = t.checked;
});

Object.assign(actions, {
  insOpen(at) {
    S.insForm = { at: Number(at), title: '', summary: '', storyline: '', ai: true };
    render();
  },
  insCancel() {
    S.insForm = null;
    render();
  },
  async insSubmit() {
    const f = S.insForm;
    if (!f) return;
    let added = false;
    await run('새 화를 넣는 중', async () => {
      await saveIfDirty();
      const r = await api('POST', `/projects/${enc(S.name)}/episodes/insert`,
        { at: f.at, title: f.title, summary: f.summary, storyline: f.storyline });
      S.project = r.project;
      S.insForm = null;
      S.selEp = f.at;
      S.selAct = null;
      added = true;
      toast(r.notes.join(' '));
    });
    if (added && plotPageN()) location.replace(`${base()}/arc/${f.at}`);  // 화 플롯 페이지: 새 화로 옮긴다 (뒤 화 번호가 밀렸다)
    if (added && f.ai) await startJob('plot_one', f.at);
  },
  async insRemove(n) {
    n = Number(n);
    const e = ep(n);
    // 넣기 양식처럼 옮겨지는 범위를 보여 준다 (pipeline.remove_episode 가 돌려주는 안내와 같은 범위)
    const moved = P().episodes.map((x) => x.plot.number).filter((k) => k > n);
    const lines = [`${n}화 '${(e && e.plot.title) || '제목 없음'}' 플롯을 뺄까요?`];
    if (e && e.status === 'confirmed') lines.push('이 화는 확정한 화예요. 확정한 플롯도 함께 사라져요.');
    lines.push(moved.length ? `뒤 화가 한 칸씩 당겨져 ${moved[0]}~${moved[moved.length - 1]}화가 ${moved[0] - 1}~${moved[moved.length - 1] - 1}화가 돼요. 구간 · 아크 범위와 복선 · 인과율 요소 · 이야기 줄기의 화 번호도 함께 옮겨요.`
      : '마지막 화라 당겨지는 화는 없어요.');
    lines.push('뺀 화의 플롯은 되돌릴 수 없어요.');
    if (!(await askConfirm(lines.join('\n'), { ok: '빼기', danger: true }))) return;
    const ok = await run('화를 빼는 중', async () => {
      await saveIfDirty();
      const r = await api('DELETE', `/projects/${enc(S.name)}/episodes/${n}`);
      S.project = r.project;
      S.selEp = null;
      toast(r.notes.join(' '));
    });
    if (ok && S.route[2] === 'arc' && Number(S.route[3]) === n) location.replace(`${base()}/arc`);  // 그 화의 플롯 페이지에서 뺐으면 보드로
  },
  delLast(n) {
    return delLast(Number(n), false);
  },
  delLastText(n) {
    return delLast(Number(n), true);
  },
  async insDraft(n) {
    await startJob('plot_one', Number(n), { fit_next: !!S.fitNext });
  },
  async clearRealign(n) {
    await run('표시를 지우는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/episodes/${n}/realign/clear`);
    });
  },
});

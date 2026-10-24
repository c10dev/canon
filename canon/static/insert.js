/* 화 끼워 넣기 · 빼기. app.js 의 S, actions, api, render, input 을 그대로 쓴다.
   아직 안 쓴 화 앞(또는 마지막 화 뒤)에 외전이나 중간 이야기를 넣으면 뒤 화가 플롯과 확정 상태를 그대로 둔 채 한 칸씩 밀리고,
   구간 · 아크 · 부 범위, 총 화수, 복선 · 인과율 요소 · 이야기 줄기의 화 번호도 함께 옮겨진다.
   서버는 pipeline.insert_episode / remove_episode, 새 화 AI 초안은 백그라운드 작업 'plot_one' (pipeline.draft_episode).
   넣을 수 있는 자리는 pipeline.insert_range · renumber.last_fixed 와 같은 규칙이라 함께 고친다. */
'use strict';

Object.assign(S, {
  insForm: null,  // { at, title, summary, storyline, ai } 새 화 넣기 양식
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
      ${input('어떤 화인지', 'summary', { root: 'insForm', rows: 3, placeholder: '무슨 일이 일어나는 화인지 한두 문장. AI 가 앞뒤 화에 맞춰 나머지를 채워요' })}
      <div class="field"><label for="ins-line">이야기 줄기 <span class="hint">외전 · 과거 회상이면 그 줄기를 고르세요</span></label>
        <select id="ins-line" data-ins-line="1">${opts}</select></div>
      ${lines.length ? '' : `<div class="small">외전이나 과거 회상 줄기는 <a href="${base()}/lines">이야기 줄기</a> 화면에서 만들 수 있어요.</div>`}
      <label class="row" style="font-size:13px;gap:6px"><input type="checkbox" data-ins-ai="1"${f.ai ? ' checked' : ''}>넣은 뒤 AI 가 앞뒤 화에 맞춰 플롯 채우기</label>
      <div class="row" style="margin-top:12px"><button type="button" class="btn primary" style="flex:1" data-action="insSubmit">${f.at}화에 넣기</button></div>
    </div>`;
}

/** 초안 화 하나를 앞뒤 화에 맞춰 AI 로 채우는 버튼 (작가가 적은 제목 · 요약 · 줄기는 살린다) */
function draftOneBtn(e) {
  if (e.status !== 'draft') return '';
  const b = jobBtn('plot_one', e.plot.number, 'AI 로 이 화 채우기');
  return `<button type="button" class="btn" style="flex:1" data-action="insDraft" data-arg="${e.plot.number}"${b.attr}>${b.label}</button>`;
}

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
    if (added && f.ai) await startJob('plot_one', f.at);
  },
  async insRemove(n) {
    n = Number(n);
    const e = ep(n);
    if (!confirm(`${n}화 '${(e && e.plot.title) || '제목 없음'}' 플롯을 빼고 뒤 화를 한 칸씩 당길까요? 뺀 화의 플롯은 되돌릴 수 없어요.`)) return;
    await run('화를 빼는 중', async () => {
      await saveIfDirty();
      const r = await api('DELETE', `/projects/${enc(S.name)}/episodes/${n}`);
      S.project = r.project;
      S.selEp = null;
      toast(r.notes.join(' '));
    });
  },
  async insDraft(n) {
    await startJob('plot_one', Number(n));
  },
});

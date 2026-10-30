/* 아는 정보 접기 (canon/knows.py): 아크 요약 칸 아래(plot.js 가 부른다) 접기 제안 받기 · 인물마다 고르고 고치기 · 적용 · 되돌리기.
   제안은 작업 fold_knows 의 결과로 S.foldDrafts[아크 번호] 에 놓인다 (app.js applyJobResult). app.js 의 S, actions, api, run, toast, esc, P, charName 을 쓴다. */
'use strict';

/** 장편 프롬프트에 인물마다 넣는 아는 정보 수. context.KNOWS_KEEP 과 같다 (tests/test_knows.py 가 맞춰 본다) */
const KNOWS_KEEP = 20;

/** 아크 요약 칸 아래 접기 칸. 요약이 없는 아크는 그리지 않는다 (요약으로 줄거리를 접은 뒤에 아는 정보도 접는다) */
function knowsFoldBox(a) {
  const p = P();
  if (!a.summary) return '';
  const done = (p.knows_folds || []).filter((r) => r.arc === a.number);
  const many = (p.states || []).filter((s) => (s.knows || []).length > KNOWS_KEEP);
  const draft = S.foldDrafts[a.number];
  if (!done.length && !draft && !many.length) return '';
  const b = jobBtn('fold_knows', a.number, done.length ? 'AI로 다시 접기 제안' : 'AI로 접기 제안');
  const doneList = done.map((r) => `<li><strong>${esc(charName(r.character_id))}</strong> <span class="small">${r.removed.length}개 → ${r.after.length}줄</span><br><span class="small">${r.after.map(esc).join(' · ')}</span></li>`).join('');
  const rows = draft ? draft.folds.map((f, i) => {
    const s = (p.states || []).find((x) => x.character_id === f.character_id) || { knows: [] };
    return `<div class="change"><input type="checkbox" id="kfo-${a.number}-${i}" data-kf="${a.number}" data-kf-i="${i}" data-kf-on="1"${f.on ? ' checked' : ''}>
      <div class="body"><label for="kfo-${a.number}-${i}" class="rv-name">${esc(charName(f.character_id))}</label> <span class="small">지금 아는 정보 ${s.knows.length}개 · 오래된 것을 아래 줄로 접어요</span>
      <textarea rows="${Math.max(3, f.lines.length)}" data-autogrow data-kf="${a.number}" data-kf-i="${i}" aria-label="${esc(charName(f.character_id))} 접은 줄 (한 줄에 하나)">${esc(f.lines.join('\n'))}</textarea></div></div>`;
  }).join('') : '';
  return `<div class="knows-fold">
    <div class="between"><h3>아는 정보 접기 ${done.length ? `<span class="chip finalized">${done.length}명 접음</span>` : ''}</h3>${draft ? '' : `<button class="btn small" data-action="foldKnows" data-arg="${a.number}"${b.attr}>${b.label}</button>`}</div>
    <div class="small">아는 정보가 ${KNOWS_KEEP}개를 넘으면 쓰기 프롬프트에는 이번 화와 관련된 ${KNOWS_KEEP}개만 들어가요. 이 아크까지 알게 된 오래된 정보를 인물마다 몇 줄로 접어 두면 그 줄은 늘 들어가요.</div>
    ${doneList ? `<ul class="cast-ul">${doneList}</ul><div class="row"><button class="btn small" data-action="undoFold" data-arg="${a.number}">접기 되돌리기</button></div>` : ''}
    ${draft ? `${rows || '<div class="small">접을 인물이 없어요</div>'}<div class="row"><button class="btn small" data-action="dropFold" data-arg="${a.number}">버리기</button><button class="btn small primary" data-action="applyFold" data-arg="${a.number}">고른 인물 접기</button></div>` : ''}
  </div>`;
}

document.addEventListener('input', (e) => {
  const el = e.target;
  if (!el.dataset || el.dataset.kf == null) return;
  const d = S.foldDrafts[el.dataset.kf];
  const f = d && d.folds[+el.dataset.kfI];
  if (!f) return;
  if (el.dataset.kfOn) f.on = el.checked;
  else f.lines = el.value.split('\n');
});
document.addEventListener('change', (e) => {
  const el = e.target;
  if (el.dataset && el.dataset.kfOn) {
    const d = S.foldDrafts[el.dataset.kf];
    if (d && d.folds[+el.dataset.kfI]) d.folds[+el.dataset.kfI].on = el.checked;
  }
});

/** 보낼 접기: 고른 인물만, 빈 줄은 뺀다 */
function knowsFoldPicked(draft) {
  return { folds: draft.folds.filter((f) => f.on).map((f) => ({ character_id: f.character_id, lines: f.lines.map((x) => x.trim()).filter(Boolean) })).filter((f) => f.lines.length) };
}

Object.assign(actions, {
  async foldKnows(n) {
    if (S.foldDrafts[n] && !confirm(`아크 ${n} 접기 제안이 아직 있어요. 고친 내용을 버리고 새로 받을까요?`)) return;
    await startJob('fold_knows', Number(n));
  },
  dropFold(n) {
    if (!confirmDrop('아는 정보 접기 제안')) return;
    delete S.foldDrafts[n];
    render();
  },
  async applyFold(n) {
    const body = knowsFoldPicked(S.foldDrafts[n]);
    if (!body.folds.length) { toast('접을 인물을 고르세요'); return; }
    await run('접는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/knows-fold/${n}`, body);
      delete S.foldDrafts[n];
      toast(`${body.folds.length}명의 아는 정보를 접었어요. 다음 화부터 접은 줄이 들어가요.`);
    });
  },
  async undoFold(n) {
    if (!confirm(`아크 ${n}에서 접은 아는 정보를 되돌릴까요? 접기 전 줄로 돌아가요.`)) return;
    await run('되돌리는 중', async () => {
      await saveIfDirty();
      S.project = await api('DELETE', `/projects/${enc(S.name)}/knows-fold/${n}`);
      toast('아는 정보 접기를 되돌렸어요');
    });
  },
});

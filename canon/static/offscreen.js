/* 화면 밖 근황 (canon/offscreen.py): 다음 아크 기획 칸(plot.js nextArcPanel 이 부른다)에서 근황 제안 받기 · 인물마다 고르고 고치기 · 저장 · 지우기.
   제안은 작업 offscreen 의 결과로 S.offscreenDraft 에 놓인다 (app.js applyJobResult). app.js 의 S, actions, api, run, toast, esc, P, charName 을 쓴다. */
'use strict';

/** 이만큼 화를 건너뛴 인물의 근황을 묻는다. context.RETURN_GAP 과 같다 (tests/test_offscreen.py 가 맞춰 본다) */
const RETURN_GAP = 10;
const OFFSCREEN_KIND = { daily: '일상', change: '변화', hook: '복귀 고리' };

/** 다음 아크 기획 칸 안의 근황 칸. 다음 아크가 RETURN_GAP 화 뒤에 시작하거나, 저장한 근황 · 제안이 있을 때만 그린다 */
function offscreenBox(start) {
  const p = P();
  const live = new Set((p.characters || []).filter((c) => c.context !== 'off').map((c) => c.id));  // offscreen.listed 와 같게 '넣지 않음' · 지운 인물은 뺀다
  const saved = (p.states || []).filter((s) => s.offscreen && live.has(s.character_id)).sort((a, b) => b.offscreen_ep - a.offscreen_ep);
  const draft = S.offscreenDraft;
  if (start <= RETURN_GAP && !saved.length && !draft) return '';
  const b = jobBtn('offscreen', null, saved.length ? 'AI로 근황 다시 제안' : 'AI로 근황 제안');
  const savedList = saved.map((s) => `<li><strong>${esc(charName(s.character_id))}</strong> <span class="small">${s.offscreen_ep}화 끝 시점</span>
      <button class="btn small ghost" data-action="clearOffscreen" data-arg="${esc(s.character_id)}" aria-label="${esc(charName(s.character_id))} 근황 지우기">지우기</button><br><span class="small">${esc(s.offscreen)}</span></li>`).join('');
  const rows = draft ? draft.lines.map((x, i) => `<div class="change"><input type="checkbox" id="ofs-${i}" data-ofs="${i}" data-ofs-on="1"${x.on ? ' checked' : ''}>
      <div class="body"><label for="ofs-${i}" class="rv-name">${esc(charName(x.character_id))}</label> <span class="chip">${esc(OFFSCREEN_KIND[x.kind] || x.kind)}</span>
      <textarea rows="2" data-autogrow data-ofs="${i}" aria-label="${esc(charName(x.character_id))} 화면 밖 근황">${esc(x.text)}</textarea></div></div>`).join('') : '';
  return `<div class="knows-fold">
    <div class="between"><h3>화면 밖 근황 ${saved.length ? `<span class="chip finalized">${saved.length}명 저장</span>` : ''}</h3>${draft ? '' : `<button class="btn small" data-action="planOffscreen"${b.attr}>${b.label}</button>`}</div>
    <div class="small">${RETURN_GAP}화 넘게 나오지 않은 인물이 그동안 어떻게 지냈는지 정해 두면 다음 아크 제안과, 그 인물이 다시 나오는 화의 쓰기에 들어가요. 그 인물이 등장 인물로 나온 화를 반영하면 근황은 지워져요.</div>
    ${savedList ? `<ul class="cast-ul">${savedList}</ul>` : ''}
    ${draft ? `${rows || '<div class="small">근황을 받은 인물이 없어요</div>'}<div class="row"><button class="btn small" data-action="dropOffscreen">버리기</button><button class="btn small primary" data-action="applyOffscreen">고른 근황 저장</button></div>` : ''}
  </div>`;
}

document.addEventListener('input', (e) => {
  const el = e.target;
  if (!el.dataset || el.dataset.ofs == null || !S.offscreenDraft) return;
  const x = S.offscreenDraft.lines[+el.dataset.ofs];
  if (!x) return;
  if (el.dataset.ofsOn) x.on = el.checked;
  else x.text = el.value;
});
document.addEventListener('change', (e) => {
  const el = e.target;
  if (el.dataset && el.dataset.ofsOn && S.offscreenDraft) {
    const x = S.offscreenDraft.lines[+el.dataset.ofs];
    if (x) x.on = el.checked;
  }
});

/** 보낼 근황: 고른 인물만, 빈 근황은 뺀다 */
function offscreenPicked(draft) {
  return { at: draft.at || 0, lines: draft.lines.filter((x) => x.on && x.text.trim()).map((x) => ({ character_id: x.character_id, text: x.text.trim(), kind: x.kind })) };
}

Object.assign(actions, {
  async planOffscreen() {
    await startJob('offscreen', null);
  },
  async dropOffscreen() {
    if (!(await confirmDrop('화면 밖 근황 제안'))) return;
    S.offscreenDraft = null;
    render();
  },
  async applyOffscreen() {
    const body = offscreenPicked(S.offscreenDraft);
    if (!body.lines.length) { toast('저장할 인물을 고르세요'); return; }
    await run('저장하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/offscreen`, body);
      S.offscreenDraft = null;
      toast(`${body.lines.length}명의 화면 밖 근황을 저장했어요. 다음 아크 제안부터 들어가요.`);
    });
  },
  async clearOffscreen(cid) {
    if (!(await askConfirm(`${charName(cid)}의 화면 밖 근황을 지울까요?`, { ok: '지우기', danger: true }))) return;
    await run('지우는 중', async () => {
      await saveIfDirty();
      S.project = await api('DELETE', `/projects/${enc(S.name)}/offscreen/${enc(cid)}`);
      toast('화면 밖 근황을 지웠어요');
    });
  },
});

// 다른 이름 채우기 (서버 canon/aliases.py, 작업 web._job_aliases). 인물 카드(setup.js) · 요소 카드(causal.js)의 '다른 이름 제안'과
// 목록 머리의 '빈 다른 이름 제안'이 작업 aliases 를 띄운다. 결과는 화면 고르기 카드에만 놓이고(S.aliasSug, 열쇠는 작업 대상),
// 작가가 고른 말만 칸(Character.aliases · StoryElement.aliases)에 넣는다. 저장은 저장 띠로 한다. 기본으로 체크하지 않는다.
// 작업 대상: 'c:<인물 id>' · 'e:<요소 id>' 는 그 항목 하나, 'c:' · 'e:' 는 다른 이름이 빈 인물 · 요소 여러 개

JOB_PAGES.aliases = (j) => (String(j.target || '').startsWith('e:') ? ['causal'] : ['setup']);  // 결과 카드가 그려지는 화면만 (app.js jobPages)
JOB_LINK.aliases = (j) => (String(j.target || '').startsWith('e:')
  ? `#/p/${enc(j.project)}/causal${j.target.length > 2 ? `/${enc(j.target.slice(2))}` : ''}` : `#/p/${enc(j.project)}/setup`);
JOB_DONE_MSG.aliases = (j) => `${j.label}${josa(j.label, '이', '가')} 도착했어요. 고른 말만 넣어요.`;
SCREEN_ONLY_JOBS.add('aliases');
JOB_BTNS.aliasAI = (key) => ['aliases', key];
JOB_RESULT.aliases = (j) => {
  if (!j.result) return null;
  const items = (j.result.items || []).filter((x) => aliasOwner(x.target));
  const notes = (j.result.notices || []).join(' · ');
  if (!items.length) return { msg: `새로 넣을 다른 이름이 없었어요.${notes ? ` ${notes}` : ''}` };
  S.aliasSug = { ...(S.aliasSug || {}), [j.target || '']: { ...j.result, items } };
  return { msg: `다른 이름을 제안받았어요.${notes ? ` ${notes}` : ''}` };
};

/** 열쇠('c:<id>' · 'e:<id>')가 가리키는 인물이나 요소. 없으면 null */
function aliasOwner(key) {
  const [kind, id] = [String(key).slice(0, 1), String(key).slice(2)];
  if (kind === 'c') return P().characters.find((c) => c.id === id) || null;
  if (kind === 'e') return (P().elements || []).find((x) => x.id === id) || null;
  return null;
}

/** 칩 아래 화 수 한 줄: '최근 30화 중 12화에서 나와요 · 이름 없이 5화' */
function aliasHitText(h, recent) {
  if (!recent) return '쓴 화가 없어 세지 못했어요';
  if (!h || !h.episodes.length) return `최근 ${recent}화에서는 나오지 않아요`;
  return `최근 ${recent}화 중 ${h.episodes.length}화에서 나와요${h.only.length ? ` · 이름 없이 ${h.only.length}화` : ''}`;
}

/** 다른 이름 고르기 카드. scope 는 작업 대상(S.aliasSug 열쇠). 받은 제안이 없으면 빈 글. 칩은 기본으로 체크하지 않는다 */
function aliasCard(scope) {
  const s = (S.aliasSug || {})[scope];
  if (!s) return '';
  const many = !String(scope).slice(2);
  const rows = s.items.map((x) => {
    const o = aliasOwner(x.target);
    if (!o) return '';
    const hits = Object.fromEntries((x.hits || []).map((h) => [h.alias, h]));
    const chips = x.aliases.map((a) => {
      const have = (o.aliases || []).includes(a);
      const h = hits[a];
      const clash = h && h.clash ? ` <span class="chip warn">‹${esc(h.clash)}›${josa(h.clash, '과', '와')} 겹쳐요</span>` : '';
      return `<label class="body-sug"><input type="checkbox" data-alias-pick="${esc(scope)}" value="${esc(`${x.target}\t${a}`)}"${have ? ' disabled' : ''}>
        <span><strong>${esc(a)}</strong>${have ? ' <span class="small">이미 있어요</span>' : ''}${clash}<br><span class="small">${esc(aliasHitText(h, s.recent))}</span></span></label>`;
    }).join('');
    return `${many ? `<strong>${esc(o.name || o.id)}</strong>` : ''}${x.reason ? `<span class="small">${esc(x.reason)}</span>` : ''}${chips}`;
  }).join('');
  return `<div class="proposal" aria-label="AI 다른 이름 제안"><strong>AI 다른 이름 제안</strong>
    ${rows || '<span>제안한 다른 이름이 없어요</span>'}
    ${(s.notices || []).map((x) => `<span class="small">${esc(x)}</span>`).join('')}
    <span class="small">화 수는 지금 본문에서 센 값이에요.</span>
    ${proposalActions(['aliasDismiss', scope], ['aliasApply', scope], '고른 다른 이름 적용', !rows)}</div>`;
}

Object.assign(actions, {
  async aliasAI(key) {
    if (String(key).slice(2) && !aliasOwner(key)) return;
    await startJob('aliases', null, { target: key }, { quiet: true });
  },
  aliasApply(scope) {
    const picked = [...document.querySelectorAll(`[data-alias-pick="${CSS.escape(scope)}"]:checked`)].map((x) => x.value.split('\t'));
    if (!picked.length) { toast('넣을 다른 이름을 고르세요', true); return; }
    let n = 0;
    picked.forEach(([key, a]) => {
      const o = aliasOwner(key);
      if (!o) return;
      if (!Array.isArray(o.aliases)) o.aliases = [];
      if (!o.aliases.includes(a)) { o.aliases.push(a); n += 1; }
    });
    delete S.aliasSug[scope];
    markDirty();
    render();
    toast(n ? '고른 다른 이름을 넣었어요. 저장하면 들어가요' : '고른 말은 이미 있어요');
  },
  aliasDismiss(scope) {
    if (S.aliasSug) delete S.aliasSug[scope];
    render();
  },
});

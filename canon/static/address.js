/* 호칭 · 말씨 (canon/address.py): 인물 · 관계도 두 사람 상세의 칸(addressCard), 인물 카드의 남겨 둔 제안(addressHeldCard),
   상태 승인 화면의 바뀜 카드(addressDeltaCard, 체크 키 h, 기본으로 체크하지 않음)와 반영한 화 보기(addressHistory).
   app.js 의 S, actions, api, run, toast, esc, P, charName 을 쓴다. */
'use strict';

/** 자주 쓰는 말씨. address.SPEECH_LEVELS 와 같다 (tests/test_address.py 가 맞춰 본다). 칸은 자유 글이다 */
const ADDRESS_LEVELS = ['하십시오체', '해요체', '하오체', '하게체', '해체(반말)', '해라체'];
const ADDRESS_FIELDS = { calls: '부르는 말', speech: '말씨' };

/** speaker → listener 방향의 정해 둔 호칭 · 말씨 (없으면 빈 칸) */
function addressOf(p, speaker, listener) {
  return (p.address_forms || []).find((f) => f.speaker === speaker && f.listener === listener) || { speaker, listener, calls: '', speech: '' };
}

/** 한 방향 줄: '서윤 → 도현' 머리, 부르는 말 · 말씨 칸, 저장 */
function addressRow(a, b, k) {
  const f = addressOf(P(), a, b);
  return `<div class="field"><div class="small" style="font-weight:700">${esc(charName(a))} → ${esc(charName(b))}</div>
    <div class="grid-2" style="align-items:end">
      <div class="field"><label for="ad-c${k}" class="small">부르는 말</label><input id="ad-c${k}" value="${esc(f.calls)}" placeholder="예: ${esc(charName(b))} 씨, 선배님"></div>
      <div class="field"><label for="ad-s${k}" class="small">말씨</label><input id="ad-s${k}" list="ad-levels" value="${esc(f.speech)}" placeholder="예: 해요체"></div>
    </div>
    <button type="button" class="btn small" data-action="addrSave" data-arg="${esc(`${a}|${b}|${k}`)}">이 방향 저장</button></div>`;
}

/** 남겨 둔 제안 한 줄 (자동 집필이 반영하지 않은 바뀜) */
function addressHeldRow(x, i) {
  const cur = addressOf(P(), x.speaker, x.listener);
  const bits = Object.entries(ADDRESS_FIELDS).filter(([k]) => x[k]).map(([k, label]) => `${label} ${esc(cur[k] || '(비어 있음)')} → <strong>${esc(x[k])}</strong>`);
  return `<div class="change"><div class="body"><div style="font-size:0.875rem;font-weight:700">${x.episode}화 · ${esc(charName(x.speaker))} → ${esc(charName(x.listener))}</div>
    <div class="small">${bits.join(' · ')}</div>${x.reason ? `<div class="small">${esc(x.reason)}</div>` : ''}${x.quote ? `<div class="small">“${esc(x.quote)}”</div>` : ''}
    <div class="row"><button type="button" class="btn small primary" data-action="addrTake" data-arg="${i}">적용</button><button type="button" class="btn small" data-action="addrDrop" data-arg="${i}">버리기</button></div></div></div>`;
}

/** 두 사람 상세의 호칭 · 말씨 카드: 두 방향 칸, 이 쌍의 남겨 둔 제안, 바뀐 기록 */
function addressCard(a, b) {
  const p = P();
  const pair = (x) => (x.speaker === a && x.listener === b) || (x.speaker === b && x.listener === a);
  const held = (p.address_held || []).map((x, i) => [x, i]).filter(([x]) => pair(x));
  const log = (p.address_log || []).filter(pair);
  const logList = log.map((r) => `<li><strong>${r.episode ? `${r.episode}화` : '1화 전'}</strong> ${esc(charName(r.speaker))} → ${esc(charName(r.listener))} ${ADDRESS_FIELDS[r.field]}: ${esc(r.before || '(비어 있음)')} → ${esc(r.after || '(비움)')} ${r.source === 'author' ? '<span class="chip">작가가 고침</span>' : '<span class="chip ai">본문에서</span>'}${r.quote ? `<br><span class="small">“${esc(r.quote)}”</span>` : ''}</li>`).join('');
  return `<h3>호칭 · 말씨</h3>
    <div class="small">누가 누구를 무엇이라 부르고 어떤 말씨(존댓말 · 반말)를 쓰는지 방향마다 적어요. 본문 쓰기와 검수에 이번 화 인물끼리의 줄이 들어가요. 본문에서 바뀌면 상태 승인 화면에 제안이 와요.</div>
    <datalist id="ad-levels">${ADDRESS_LEVELS.map((x) => `<option value="${esc(x)}">`).join('')}</datalist>
    ${addressRow(a, b, 0)}${addressRow(b, a, 1)}
    ${held.length ? `<h3>남겨 둔 호칭 · 말씨 바뀜 <span class="small" style="font-weight:400">${held.length}개 · 자동 집필은 반영하지 않아요</span></h3>${held.map(([x, i]) => addressHeldRow(x, i)).join('')}` : ''}
    ${logList ? `<h3>호칭 · 말씨 기록</h3><ul class="cast-ul">${logList}</ul>` : ''}`;
}

/** 인물 카드: 이 인물이 든 남겨 둔 바뀜 제안 (두 사람 상세로 가는 링크) */
function addressHeldCard(c) {
  const held = (P().address_held || []).filter((x) => x.speaker === c.id || x.listener === c.id);
  if (!held.length) return '';
  const rows = held.map((x) => `<li><button type="button" class="link-btn" data-action="castPick" data-arg="${esc('p:' + [x.speaker, x.listener].sort().join('|'))}">${x.episode}화 · ${esc(charName(x.speaker))} → ${esc(charName(x.listener))}</button> <span class="small">${esc([x.calls, x.speech].filter(Boolean).join(' · '))}</span></li>`).join('');
  return `<section class="card"><div class="between"><h2>남겨 둔 호칭 · 말씨</h2><span class="small">${held.length}개</span></div>
    <div class="small">자동 집필은 호칭 · 말씨를 바꾸지 않아요. 두 사람 상세에서 적용하거나 버려요.</div><ul class="cast-ul">${rows}</ul></section>`;
}

/** 상태 승인 화면의 바뀜 카드. 설정 바꾸기처럼 작가가 직접 골라야 반영한다 (setDelta 가 h 키를 false 로 둔다) */
function addressDeltaCard(n, d, box) {
  const list = d.address_changes || [];
  if (!list.length) return '';
  const name = (id) => charName(id) || ((d.new_characters || []).find((c) => c.id === id) || {}).name || id;
  const rows = list.map((x, i) => {
    const cur = addressOf(P(), x.speaker, x.listener);
    const bits = Object.entries(ADDRESS_FIELDS).filter(([k]) => x[k]).map(([k, label]) => `<div class="row"><span class="small">${label}</span><span class="before">${esc(cur[k] || '(비어 있음)')}</span><span class="small">→</span><span class="after">${esc(x[k])}</span></div>`).join('');
    return `<div class="change">${box('h' + i)}<div class="body"><label for="pk-h${i}" class="rv-name">${esc(name(x.speaker))} → ${esc(name(x.listener))}</label>${bits}
      ${x.reason ? `<div class="small">${esc(x.reason)}</div>` : ''}${x.quote ? `<div class="rv-quote">“${esc(x.quote)}”</div>` : ''}</div></div>`;
  }).join('');
  return `<section class="card rv-card"><div class="rv-card-head"><h2>호칭 · 말씨 바뀜</h2><span class="small">본문에서 부르는 말이나 말씨가 바뀐 방향이에요. 기본으로 체크하지 않아요. 골라야 다음 화부터 바뀐 대로 써요</span></div>${rows}</section>`;
}

/** 반영한 화 보기의 호칭 · 말씨 기록 */
function addressHistory(h) {
  const list = h.address_changes || [];
  if (!list.length) return '';
  const rows = list.map((x) => `<li><strong>${esc(charName(x.speaker))} → ${esc(charName(x.listener))}</strong> ${esc([x.calls && `부르는 말 ${x.calls}`, x.speech && `말씨 ${x.speech}`].filter(Boolean).join(' · '))}</li>`).join('');
  return `<section class="card"><h2>호칭 · 말씨 바뀜</h2><ul style="padding-left:18px;display:flex;flex-direction:column;gap:6px;font-size:0.8125rem;line-height:1.5">${rows}</ul></section>`;
}

Object.assign(actions, {
  async addrSave(arg) {
    const [speaker, listener, k] = String(arg).split('|');
    const val = (id) => { const el = document.getElementById(id); return el ? el.value : ''; };
    await run('저장하는 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/address`, { speaker, listener, calls: val(`ad-c${k}`), speech: val(`ad-s${k}`) });
      toast('호칭 · 말씨를 저장했어요');
    });
  },
  async addrTake(i) {
    await run('적용하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/address-held/${i}`);
      toast('호칭 · 말씨를 바꿨어요');
    });
  },
  async addrDrop(i) {
    const x = (P().address_held || [])[i];
    if (x && !confirm(`${charName(x.speaker)} → ${charName(x.listener)} 호칭 · 말씨 바뀜 제안을 버릴까요?`)) return;
    await run('버리는 중', async () => {
      await saveIfDirty();
      S.project = await api('DELETE', `/projects/${enc(S.name)}/address-held/${i}`);
      toast('제안을 버렸어요');
    });
  },
});

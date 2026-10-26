/* 인물 설정 변경. app.js 의 S, actions, api, run, render, esc, P, enc, charName, saveIfDirty, toast 를 쓴다.
   상태 승인 화면의 설정 바꾸기 제안(scDeltaCard, 키 t, 기본으로 체크하지 않음)과 반영 기록(scHistory),
   인물 화면의 남겨 둔 제안(scHeldCard: 자동 집필이 반영하지 않은 것)과 설정 변경 기록(scLogCard), 그때 설정(scAt).
   서버는 canon/charlog.py. 칸 이름(SC_LABELS)은 charlog.LOG_FIELDS 와 같아 함께 고친다. */
'use strict';

const SC_LABELS = {
  name: '이름', gender: '성별', age: '나이', role: '역할', appearance: '외모', personality: '성격', speech_style: '말투',
  background: '배경', goal: '원하는 것', wound: '두려운 것 · 약점', arc: '아크', narration_voice: '서술 말투',
};
const scLabel = (f) => SC_LABELS[f] || f;

/** 인물 설정을 n화가 끝났을 때 값으로 (그 뒤 기록을 거꾸로 되돌린다). changed 는 n화 뒤에 바뀐 칸. */
function scAt(c, n) {
  const out = { ...c };
  const changed = new Set();
  const log = (P().setting_log || []).filter((r) => r.character_id === c.id);
  for (let i = log.length - 1; i >= 0; i--) {
    if (log[i].episode > n) {
      out[log[i].field] = log[i].before;
      changed.add(log[i].field);
    }
  }
  return { c: out, changed };
}

/** 지금 값 → 바꾼 뒤 값 (바꾼 뒤 값은 고칠 수 있다). */
function scBeforeAfter(before, input) {
  return `${before ? `<div class="row"><span class="before">${esc(before)}</span><span class="small">→</span></div>` : '<div class="small">지금은 비어 있어요</div>'}${input}`;
}

/** 기록 한 줄의 전후. 비어 있던 칸은 지운 줄 대신 '새로 채움'. */
function scArrow(before, after) {
  return `${before ? `<span class="before">${esc(before)}</span><span class="small">→</span>` : '<span class="small">새로 채움</span>'}<span class="after">${esc(after || '(비움)')}</span>`;
}

// ----- 상태 승인 화면 -----

function scDeltaCard(n, d, box) {
  const list = d.setting_changes || [];
  if (!list.length) return '';
  const rows = list.map((x, i) => {
    const c = P().characters.find((y) => y.id === x.character_id) || {};
    const input = `<textarea id="sc-${i}" rows="2" data-autogrow data-sc="${i}" data-sc-ep="${n}" aria-label="${esc(charName(x.character_id))} ${scLabel(x.field)} 바꾼 뒤">${esc(x.value)}</textarea>`;
    return `<div class="change">${box('t' + i)}<div class="body"><label for="pk-t${i}" style="font-size:0.875rem;font-weight:700">${esc(charName(x.character_id))} · ${scLabel(x.field)}</label>
      ${scBeforeAfter(c[x.field], input)}
      ${x.reason ? `<div class="small">${esc(x.reason)}</div>` : ''}
      ${x.quote ? `<div style="font-family:var(--serif);font-size:0.8125rem;line-height:1.7;color:var(--text-2)">“${esc(x.quote)}”</div>` : ''}</div></div>`;
  }).join('');
  return `<section class="card"><div class="between"><h2>인물 설정 바꾸기</h2><span class="small">기본으로 고르지 않았어요</span></div>
    <div class="small">본문에서 뒤 화까지 이어지게 바뀐 설정이에요. 고르면 인물 설정이 바뀌고 다음 화부터 바뀐 설정으로 써요. 바뀐 기록은 인물 · 관계도 화면에 남고, 반영을 취소하면 되돌아가요.</div>
    ${rows}</section>`;
}

document.addEventListener('input', (e) => {
  const el = e.target;
  if (!el.dataset || el.dataset.sc == null) return;
  const d = S.deltas[el.dataset.scEp];
  const x = d && (d.setting_changes || [])[+el.dataset.sc];
  if (x) x.value = el.value;
});

/** 반영 기록의 설정 바꾸기 (없으면 빈칸). 그때 바뀐 값은 설정 변경 기록에서 찾는다. */
function scHistory(h) {
  const recs = (P().setting_log || []).filter((r) => r.episode === h.episode && r.source === 'ai');
  if (!recs.length) return '';
  return `<section class="card"><h2>인물 설정 바꾸기</h2><ul style="padding-left:18px;display:flex;flex-direction:column;gap:6px;font-size:0.8125rem;line-height:1.5">${recs.map((r) => `<li><strong>${esc(charName(r.character_id))}</strong> ${scLabel(r.field)}: ${esc(r.before || '(비어 있음)')} → ${esc(r.after)}</li>`).join('')}</ul></section>`;
}

// ----- 인물 화면 -----

/** 자동 집필 · 명령줄 -y 가 반영하지 않고 남겨 둔 제안. 적용하면 그 화의 기록으로 남는다. */
function scHeldCard(c) {
  const held = (P().setting_held || []).map((x, i) => [x, i]).filter(([x]) => x.character_id === c.id);
  if (!held.length) return '';
  const rows = held.map(([x, i]) => `<div class="change"><div class="body"><div style="font-size:0.875rem;font-weight:700">${x.episode}화 · ${scLabel(x.field)}</div>
      ${scBeforeAfter(c[x.field], `<textarea id="sch-${i}" rows="2" data-autogrow aria-label="${scLabel(x.field)} 바꾼 뒤">${esc(x.value)}</textarea>`)}
      ${x.reason ? `<div class="small">${esc(x.reason)}</div>` : ''}${x.quote ? `<div class="small">“${esc(x.quote)}”</div>` : ''}
      <div class="row"><button type="button" class="btn small primary" data-action="scTake" data-arg="${i}">적용</button><button type="button" class="btn small" data-action="scDrop" data-arg="${i}">버리기</button></div></div></div>`).join('');
  return `<section class="card"><div class="between"><h2>남겨 둔 설정 바꾸기</h2><span class="small">${held.length}개</span></div>
    <div class="small">자동 집필은 인물 설정을 바꾸지 않아요. AI가 본문에서 찾은 설정 변화를 여기 남겨 뒀어요. 적용하면 다음 화부터 바뀐 설정으로 써요.</div>${rows}</section>`;
}

function scLogCard(c) {
  const recs = (P().setting_log || []).filter((r) => r.character_id === c.id);
  if (!recs.length) return '';
  const items = recs.map((r) => `<li><div class="row"><strong>${r.episode ? `${r.episode}화` : '1화 전'}</strong><span class="small">${scLabel(r.field)}</span>${r.source === 'author' ? '<span class="chip">작가가 고침</span>' : '<span class="chip ai">본문에서</span>'}</div>
      <div class="row">${scArrow(r.before, r.after)}</div>
      ${r.reason ? `<div class="small">${esc(r.reason)}</div>` : ''}${r.quote ? `<div class="small">“${esc(r.quote)}”</div>` : ''}</li>`).join('');
  return `<section class="card"><div class="between"><h2>설정 변경 기록</h2><span class="small">처음 설정과 비교</span></div><ol class="cast-tl">${items}</ol></section>`;
}

Object.assign(actions, {
  async scTake(i) {
    const el = document.getElementById(`sch-${i}`);
    await run('적용하는 중', async () => {
      await saveIfDirty();
      S.project = await api('POST', `/projects/${enc(S.name)}/setting-held/${i}`, { value: el ? el.value : null });
      if (typeof castLoad === 'function') await castLoad();
      toast('인물 설정을 바꿨어요');
    });
  },
  async scDrop(i) {
    const x = (P().setting_held || [])[i];
    if (x && !confirm(`${charName(x.character_id)}의 ${scLabel(x.field)} 바꾸기 제안을 버릴까요?`)) return;
    await run('버리는 중', async () => {
      await saveIfDirty();
      S.project = await api('DELETE', `/projects/${enc(S.name)}/setting-held/${i}`);
      toast('제안을 버렸어요');
    });
  },
});

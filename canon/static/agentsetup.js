/* 대화 에이전트의 설정 도구 카드 (서버 canon/agent_setup.py, UX 04c). agent.js 의 agentApproval · agentItemDiff · agentDecide 가 부른다.
   칸마다 지금 값과 나란히 보이는 비교는 setupchat.js 의 setupKeyValue · setupRelDiff · setupNewCard · setupLabel 과 chat.js 의 diffField 를 그대로 쓴다.
   처음 체크는 서버가 정한 Approval.defaults 다(이미 채운 칸 · 인물 칸은 꺼 둠). 권한 모드와 상관없이 늘 묻고 '이 세션에서 묻지 않기'는 없다.
   고르지 않은 새 인물과 이어진 관계는 고를 수 없다(setupchat.apply_revision 과 같은 규칙). 부분 id 는 setupchat.part_ids 와 같다. */
'use strict';

/** 설정 대상의 빈 세션 안내 (agent.js agentLog) */
function agentSetupIntro() {
  return `<div class="note info">설정을 말로 고쳐요. AI가 로그라인, 주제, 톤, 세계관, 인물, 관계에서 바꿀 칸만 지금 값과 나란히 보여 주고, 권한 모드와 상관없이 칸마다 물어봐요. 이미 채운 칸과 인물 칸은 꺼 둬요. 플롯은 고칠 수 있지만 늘 먼저 물어봐요.</div>
    ${agentExampleRow('setup')}`;
}

/** 카드의 한 부분이 체크돼 있는지. 처음 그릴 때 서버 defaults 로 채운다. */
function agentSetupPicked(i, a, pid) {
  const k = `${i}:${pid}`;
  if (S.agentPicks[k] === undefined) S.agentPicks[k] = a.defaults.includes(pid);
  return S.agentPicks[k];
}

/** 관계가 고르지 않은 새 인물과 이어져 있으면 그 인물 id 들 */
function agentSetupBlocked(i, a, r) {
  return [r.a, r.b].filter((id) => a.setup.new_characters.some((c) => c.id === id) && !agentSetupPicked(i, a, `new:${id}`));
}

/** 승인할 부분: 체크했고 막히지 않은 것 (agent.js agentDecide) */
function agentSetupPicks(i, a) {
  return a.keys.filter((pid) => {
    if (!agentSetupPicked(i, a, pid)) return false;
    const r = pid.startsWith('r:') ? a.setup.relationships.find((x) => setupRelId(x) === pid) : null;
    return !(r && agentSetupBlocked(i, a, r).length);
  });
}

/** 한 부분의 비교. base 는 묻는 동안은 지금 작품, 쓴 뒤에는 쓰기 전 설정(WriteRecord.setup_before)이다. */
function agentSetupDiff(rev, base, pid) {
  const e = rev.edits.find((x) => x.key === pid);
  if (e) return `<div class="diff">${diffField(SETUP_KEY_LABEL[e.key] || e.key, e.key, setupKeyValue(base, e.key), setupEditValue(e))}</div>`;
  const x = rev.characters.find((y) => `c:${y.id}:${y.field}` === pid);
  if (x) {
    const c = base.characters.find((y) => y.id === x.id);
    return `<div class="diff">${diffField(SETUP_CHAR_LABEL[x.field] || x.field, x.field, c ? c[x.field] : '', setupCharValue(x))}</div>`;
  }
  const n = rev.new_characters.find((y) => `new:${y.id}` === pid);
  if (n) return setupNewCard(n);
  const r = rev.relationships.find((y) => setupRelId(y) === pid);
  if (r) return `<div class="diff">${setupRelDiff(r, setupPair(base.relationships, r.a, r.b), rev, base) || '<div class="small">지금 관계와 같아요.</div>'}</div>`;
  return '';
}

/** 쓴 것 한 부분의 바뀐 칸 ('이번 턴에 바꾼 것', agent.js agentItemDiff) */
function agentSetupItemDiff(w, item) {
  return w.setup && w.setup_before ? agentSetupDiff(w.setup, w.setup_before, item.key) : '';
}

/** 칸마다 무엇이 바뀌는지 알리는 칩 */
function agentSetupChip(rev, base, pid) {
  const e = rev.edits.find((x) => x.key === pid);
  if (e) return setupFilled(setupKeyValue(base, e.key)) ? ' <span class="chip written">채운 칸 바꿈</span>' : '';
  if (pid.startsWith('c:')) return ' <span class="chip written">인물 설정 바꿈</span>';
  if (pid.startsWith('new:')) return ' <span class="chip ai">새 인물</span>';
  const r = rev.relationships.find((y) => setupRelId(y) === pid);
  return r && setupPair(base.relationships, r.a, r.b) ? ' <span class="chip written">있는 관계 바꿈</span>' : ' <span class="chip ai">새 관계</span>';
}

/** 설정 변경안 승인 카드. 고른 칸만 적용하고 같은 턴을 이어 간다 */
function agentSetupApproval(t, i, last) {
  const a = t.approval;
  const rev = a.setup;
  const wait = a.state === 'wait' && t.end === 'wait' && last;
  const base = P();
  const head = { wait: '<span class="chip warn">승인 기다림</span>', approved: '<span class="chip ok">적용함</span>', denied: '<span class="chip">거절함</span>' }[a.state];
  const why = (pid) => {
    const x = rev.edits.find((y) => y.key === pid) || rev.characters.find((y) => `c:${y.id}:${y.field}` === pid);
    return x && x.why ? `<div class="small">${esc(x.why)}</div>` : '';
  };
  const part = (pid) => {
    const name = esc(setupLabel(rev, base, pid));
    // 답한 뒤에는 지금 값이 이미 바뀌었을 수 있어 비교를 감춘다 (쓴 것은 '이번 턴에 바꾼 것'이 쓰기 전 · 뒤로 보인다)
    if (!wait) return `<div class="prop-part"><span class="prop-head"><strong>${name}</strong>${a.picked.includes(pid) ? '<span class="chip ok">적용함</span>' : ''}</span></div>`;
    const r = pid.startsWith('r:') ? rev.relationships.find((y) => setupRelId(y) === pid) : null;
    const blocked = r ? agentSetupBlocked(i, a, r) : [];
    const on = agentSetupPicked(i, a, pid) && !blocked.length;
    const box = `<input type="checkbox" data-agent-pick="${i}:${pid}"${on ? ' checked' : ''}${blocked.length ? ' disabled' : ''}>`;
    const tail = blocked.length ? setupName(rev, base, blocked[blocked.length - 1]) : '';
    const note = blocked.length ? `<div class="note plain">새 인물 ${blocked.map((id) => esc(setupName(rev, base, id))).join(', ')}${josa(tail, '을', '를')} 함께 골라야 넣을 수 있어요.</div>` : '';
    return `<div class="prop-part"><label class="prop-head">${box}<strong>${name}</strong>${agentSetupChip(rev, base, pid)}</label>${why(pid)}${note}${agentSetupDiff(rev, base, pid)}</div>`;
  };
  const notes = wait ? [
    base.episodes.some((e) => e.status === 'finalized') ? '이미 쓴 화의 본문은 바뀌지 않아요. 인물 칸을 바꾸면 인물 설정 변경 기록에 작가가 고친 것으로 남아요.' : '',
    rev.relationships.length && base.snapshots.length ? '첫 반영 뒤라 관계는 사이와 설명만 바뀌어요. 지금 호감과 긴장은 본문의 관계 사건으로 계산돼요.' : '',
  ].filter(Boolean).map((x) => `<div class="note info">${x}</div>`).join('') : '';
  const many = wait && a.keys.length > 3 ? `<span class="row"><button type="button" class="btn small" data-action="agentSetupPickAll" data-arg="${i}|1">모두 고르기</button><button type="button" class="btn small" data-action="agentSetupPickAll" data-arg="${i}|0">모두 빼기</button></span>` : '';
  return `<div class="approval${wait ? '' : ' settled'}">
    <div class="between"><span class="row">${head}<strong>설정 ${a.keys.length}곳 바꾸기</strong></span>${many}</div>
    ${wait ? `<span class="small">설정은 권한 모드와 상관없이 칸마다 물어봐요. 이미 채운 칸과 인물 칸은 꺼 두었어요. 바꾸려면 체크하세요.</span>${notes}` : ''}
    ${a.keys.map(part).join('')}
    ${wait ? `<div class="row proposal-actions"><button type="button" class="btn small" data-action="agentDecide" data-arg="${i}|0">거절</button>
        <button type="button" class="btn small primary" data-action="agentDecide" data-arg="${i}|1">고른 칸 적용하고 이어 하기</button></div>` : ''}
  </div>`;
}

Object.assign(actions, {
  agentSetupPickAll(arg) {
    const [i, on] = String(arg).split('|');
    const a = agentSession().turns[Number(i)].approval;
    a.keys.forEach((pid) => { S.agentPicks[`${i}:${pid}`] = on === '1'; });
    redrawChat();
  },
});

// 새 인물을 고르거나 빼면 그 인물과 이어진 관계를 고를 수 있는지가 바뀐다 (agent.js 의 change 가 먼저 체크 상태를 적는다)
document.addEventListener('change', (e) => {
  const k = e.target.dataset && e.target.dataset.agentPick;
  if (!k || !/^\d+:new:/.test(k)) return;
  S.agentPicks[k] = e.target.checked;
  redrawChat();
});

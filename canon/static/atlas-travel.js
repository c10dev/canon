/* 이동 시간 검사 칸 (atlas.js 에서 뗐다). 서버 canon/travel.py 가 거리 · 걸리는 시간 · 판정을 셈하고 글로 보낸다 (/atlas 의 travel).
   app.js 의 S, actions, api, run, esc 와 atlas.js 의 atlasLoad 를 쓴다. */
'use strict';

// ----- 이동 시간 검사 (서버 canon/travel.py: 거리 · 걸리는 시간 · 판정은 서버가 셈하고 글로 보낸다) -----

function atlasTravelBox() {
  const t = S.atlas.travel;
  if (!t) return '';
  const on = `<label class="small"><input type="checkbox" data-atlas-travel="enabled"${t.enabled ? ' checked' : ''}> 지도 거리와 작품 속 시간으로 너무 빠른 이동 찾기</label>`;
  if (!t.enabled) return `<div class="at-box"><h3>이동 시간 검사</h3>${on}</div>`;
  const modes = t.modes.map((m) => `<option value="${esc(m.id)}"${m.id === t.mode ? ' selected' : ''}>${esc(m.label)} (시속 ${m.kmh}km · 하루 ${m.day_km}km)</option>`).join('');
  const size = t.from_layout
    ? `<div class="small">마을 데이터 축척으로 지도 크기를 약 ${esc(t.scale_text)}로 셈해요.</div>`
    : `<label class="at-scale small">지도 가로 <input type="number" min="0" max="100000" step="1" value="${t.span_km || ''}" placeholder="모름" data-atlas-travel="span_km" aria-label="지도 가로가 몇 km인지"> km</label>`;
  const own = `<details class="small"><summary>빠르기 직접 정하기</summary>
      <label class="at-scale">시속 <input type="number" min="0" max="2000" step="0.5" value="${t.kmh || ''}" placeholder="${t.speed[1]}" data-atlas-travel="kmh" aria-label="이동 빠르기 km/시"> km</label>
      <label class="at-scale">하루 <input type="number" min="0" max="20000" step="1" value="${t.day_km || ''}" placeholder="${t.speed[2]}" data-atlas-travel="day_km" aria-label="하루 이동 거리 km"> km</label>
      <div>비우면 탈것의 기본값이에요. 서두르면 하루 ${t.speed[3]}km까지 간다고 봐요.</div></details>`;
  let body;
  if (!t.scale) body = '<div class="note">지도 가로가 몇 km인지 적으면 장소 사이 거리를 셀 수 있어요.</div>';
  else if (!t.moves.length) {
    body = `<div class="small">걸린 이동이 없어요${t.checked ? ` (본 이동 ${t.checked}개)` : ''}.${t.unknown ? ` 작품 속 시간 기록이 없어 못 본 이동이 ${t.unknown}개 있어요.` : ''}</div>`;
  } else {
    const items = t.moves.map((m) => {
      const tag = m.level === 'fast' ? '<span class="at-tv fast">너무 빨라요</span>' : '<span class="at-tv tight">빠듯해요</span>';
      const btn = m.accepted
        ? `<button type="button" class="btn small ghost" data-action="atlasTravelOk" data-arg="${esc(m.cid)}:${m.episode}:0">다시 보기</button>`
        : `<button type="button" class="btn small ghost" data-action="atlasTravelOk" data-arg="${esc(m.cid)}:${m.episode}:1" title="순간 이동이나 기록 밖의 탈것처럼 까닭이 있는 이동이면 경고에서 빼요">괜찮아요</button>`;
      return `<li class="${m.accepted ? 'at-tv-ok' : ''}"><div>${tag} <strong>${esc(m.who)}</strong> <span class="small">${m.since}~${m.episode}화</span></div>
        <div class="small">${esc(m.text)}</div>${btn}</li>`;
    });
    body = `<ul class="at-list at-tv-list">${items.join('')}</ul>
      <div class="small">시간은 화가 끝난 시점을 가장 넉넉하게 읽고, 거리는 곧은 거리에 길 굽음을 더한 어림이에요.${t.unknown ? ` 시간 기록이 없어 못 본 이동 ${t.unknown}개.` : ''}</div>`;
  }
  return `<div class="at-box"><h3>이동 시간 검사</h3>${on}
    <label class="small">가장 빠른 탈것 <select data-atlas-travel="mode" aria-label="이 세계에서 가장 빠른 탈것">${modes}</select></label>
    ${size}${own}${body}</div>`;
}

Object.assign(actions, {
  async atlasTravelOk(arg) {
    const [cid, ep, ok] = String(arg).split(':');
    await run('저장하는 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/atlas/travel/ok`, { cid, episode: Number(ep), ok: ok === '1' });
      await atlasLoad();
      toast(ok === '1' ? '이 이동을 괜찮다고 뒀어요' : '이 이동을 다시 봐요');
    });
  },
});

document.addEventListener('change', async (e) => {
  const t = e.target;
  if (t.matches('[data-atlas-travel]')) {
    const cur = S.atlas.travel;
    const key = t.dataset.atlasTravel;
    const body = { enabled: cur.enabled, mode: cur.mode, kmh: cur.kmh, day_km: cur.day_km, span_km: cur.span_km };
    body[key] = key === 'enabled' ? t.checked : key === 'mode' ? t.value : Number(t.value || 0);
    if (key !== 'enabled' && key !== 'mode' && !(body[key] >= 0)) { toast('0 이상의 수를 적어 주세요', true); return; }
    await run('저장하는 중', async () => {
      await saveIfDirty();
      S.project = await api('PUT', `/projects/${enc(S.name)}/atlas/travel`, body);
      await atlasLoad();
      toast('이동 시간 검사 설정을 바꿨어요');
    });
    return;
  }
});

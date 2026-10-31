/* 이동 시간 검사 칸 (살펴보기 '이동 검사' 칸, atlas.js 에서 뗐다). 서버 canon/travel.py 가 거리 · 걸리는 시간 · 판정을 셈하고 글로 보낸다 (/atlas 의 travel).
   app.js 의 S, actions, api, run, esc 와 atlas.js 의 atlasLoad 를 쓴다. */
'use strict';

// ----- 이동 시간 검사 (서버 canon/travel.py: 거리 · 걸리는 시간 · 판정은 서버가 셈하고 글로 보낸다) -----

function atlasTravelBox() {
  const t = S.atlas.travel;
  if (!t) return '';
  const on = `<label class="pop-check"><input type="checkbox" data-atlas-travel="enabled"${t.enabled ? ' checked' : ''}> 지도 거리와 작품 속 시간으로 너무 빠른 이동 찾기</label>`;
  if (!t.enabled) return `<section class="at-sec"><h3>이동 시간 검사</h3>${on}<p class="small">순간 이동이 흔한 작품이면 꺼 두세요. 끄면 상태 변경안 경고와 프롬프트의 이동 거리도 빠져요.</p></section>`;
  const mode = t.modes.find((m) => m.id === t.mode) || { label: t.mode };
  const sum = `${esc(mode.label)}${t.mode === 'transit' ? '' : ` · 하루 ${t.speed[2]}km`} · ${t.scale ? `지도 ${esc(t.scale_text)}` : '지도 크기 모름'}`;
  const editing = S.atlasTvEdit || !t.scale;
  const modes = t.modes.map((m) => `<option value="${esc(m.id)}"${m.id === t.mode ? ' selected' : ''}>${esc(m.label)} (${m.id === 'transit' ? '걸어서 + 지하철' : `시속 ${m.kmh}km · 하루 ${m.day_km}km`})</option>`).join('');
  const size = t.from_layout
    ? `<p class="small">지도 데이터 축척으로 지도 크기를 약 ${esc(t.scale_text)}로 셈해요.</p>`
    : `<label class="at-scale">지도 가로 <input type="number" min="0" max="100000" step="1" value="${t.span_km || ''}" placeholder="모름" data-atlas-travel="span_km" aria-label="지도 가로가 몇 km인지"> km</label>`;
  const own = `<details class="small"><summary>빠르기 직접 정하기</summary>
      <label class="at-scale">시속 <input type="number" min="0" max="2000" step="0.5" value="${t.kmh || ''}" placeholder="${t.speed[1]}" data-atlas-travel="kmh" aria-label="이동 빠르기 km/시"> km</label>
      <label class="at-scale">하루 <input type="number" min="0" max="20000" step="1" value="${t.day_km || ''}" placeholder="${t.speed[2]}" data-atlas-travel="day_km" aria-label="하루 이동 거리 km"> km</label>
      <p>비우면 탈것의 기본값이에요. 서두르면 하루 ${t.speed[3]}km까지 간다고 봐요.</p></details>`;
  const setting = editing ? `<div class="at-sec at-tv-set">${on}
      <div class="field"><label for="at-tv-mode">가장 빠른 탈것</label><select id="at-tv-mode" data-atlas-travel="mode">${modes}</select></div>
      ${size}${own}${t.mode === 'transit' ? atlasTransitNote(t) : ''}</div>` : '';
  let body;
  if (!t.scale) body = '<div class="note">지도 가로가 몇 km인지 적으면 장소 사이 거리를 셀 수 있어요.</div>';
  else if (!t.moves.length) {
    body = `<p class="small">걸린 이동이 없어요${t.checked ? ` (본 이동 ${t.checked}개)` : ''}.${t.unknown ? ` 작품 속 시간 기록이 없어 못 본 이동이 ${t.unknown}개 있어요.` : ''}</p>`;
  } else {
    const items = t.moves.map((m) => {
      const tag = m.level === 'fast' ? '<span class="chip bad">너무 빨라요</span>' : '<span class="chip warn">빠듯해요</span>';
      const ok = m.accepted
        ? `<button type="button" class="btn small ghost" data-action="atlasTravelOk" data-arg="${esc(m.cid)}:${m.episode}:0">다시 보기</button>`
        : `<button type="button" class="btn small ghost" data-action="atlasTravelOk" data-arg="${esc(m.cid)}:${m.episode}:1" title="순간 이동이나 기록 밖의 탈것처럼 까닭이 있는 이동이면 경고에서 빼요">괜찮아요</button>`;
      const sel = S.atlasFocus === m.cid && atlasFrameNow().episode === m.episode;
      return `<li class="at-tv-row${m.accepted ? ' ok' : ''}${sel ? ' sel' : ''}"><div class="row">${m.accepted ? '<span class="chip">괜찮아요</span>' : tag}<b>${esc(m.who)}</b><span class="small">${m.since}~${m.episode}화</span></div>
        <span>${esc(m.text)}</span>
        <div class="row"><button type="button" class="btn small" data-action="atlasTravelShow" data-arg="${esc(m.cid)}:${m.episode}">지도에서 보기</button>${ok}</div></li>`;
    });
    body = `<ul class="at-tv-list">${items.join('')}</ul>
      <p class="small">시간은 화가 끝난 시점을 가장 넉넉하게 읽고, 거리는 곧은 거리에 길 굽음을 더한 어림이에요.${t.unknown ? ` 시간 기록이 없어 못 본 이동 ${t.unknown}개.` : ''}</p>`;
  }
  return `<div class="between"><span class="at-t2">${sum}</span>${t.scale ? `<button type="button" class="btn small ghost" data-action="atlasTvEdit" aria-expanded="${editing}">${editing ? '기준 접기' : '기준 고치기'}</button>` : ''}</div>
    ${setting}${body}`;
}

/** 대중교통일 때: 지하철 데이터가 있는지, 지하철로 센 이동 (서버 travel.view 의 transit · rail) */
function atlasTransitNote(t) {
  if (!t.transit || !t.transit.lines.length) {
    return '<div class="note">이 지도에는 지하철 노선이 없어 걸어서만 셈해요. 지하철 노선이 든 OpenStreetMap .osm 파일을 올리면 함께 셈해요.</div>';
  }
  const head = `<div class="small">지하철 역 ${t.transit.stations}곳 · 노선 ${t.transit.lines.length}개(${esc(t.transit.lines.join(', '))})로 걸어서보다 빠른 길을 함께 셈해요.</div>`;
  if (!t.rail.length) return head;
  const items = t.rail.map((m) => `<li><div><strong>${esc(m.who)}</strong> <span class="small">${m.since}~${m.episode}화</span></div><div class="small">${esc(m.text)}</div></li>`).join('');
  return `${head}<details class="small at-tv-rail"><summary>지하철로 센 이동 ${t.rail.length}개</summary><ul class="at-list">${items}</ul></details>`;
}

Object.assign(actions, {
  atlasTvEdit() {
    S.atlasTvEdit = !S.atlasTvEdit;
    atlasRefresh();
  },
  /** 경고 하나를 지도에서 본다: 닿은 화 시점으로 가고 그 인물의 길을 굵게 */
  atlasTravelShow(arg) {
    const [cid, ep] = String(arg).split(':');
    const i = S.atlas.frames.findIndex((f) => f.episode === Number(ep));
    if (i < 0) return;
    atlasStop();
    S.atlasFrame = i;
    S.atlasFocus = cid;
    S.atlasTvMarks = true;
    if (S.atlasTab !== 'map') { S.atlasTab = 'map'; S.atlasPane = 'travel'; render(); return; }
    atlasRefresh();
    atlasFollow();
  },
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

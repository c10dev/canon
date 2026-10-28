/* 이름으로 자리 찾기 (atlas.js 에서 뗐다). 서버 atlas.find_spots 가 장소 이름과 같은 이름의 건물 · 가게 · 역을 찾는다.
   app.js 의 S, actions, api, run, esc 와 atlas.js 의 atlasFindNow · atlasFindDefault · atlasFindPins · atlasPinMap · atlasSavePins · atlasStage · atlasRefresh 를 쓴다.
   처음 고름(atlasFindDefault)과 고른 자리 덮기(atlasFindPins)는 화면을 모르는 계산이라 atlas.js 에 있다 (tests/test_atlas_js.py). */
'use strict';

// ----- 이름으로 자리 찾기 (서버 atlas.find_spots: 장소 이름과 같은 이름의 건물 · 가게 · 역) -----

/** 이름으로 자리 찾기 후보를 받아 연다 */
async function atlasFindLoad() {
  const r = await api('GET', `/projects/${enc(S.name)}/atlas/find-spots`);
  S.atlasFind = { name: S.name, spots: r.spots, pick: atlasFindDefault(r.spots) };
}

function atlasFindBox() {
  const fd = atlasFindNow();
  if (!fd) return '';
  const close = '<button type="button" class="btn small ghost" data-action="atlasFindClose">닫기</button>';
  if (!fd.spots.length) {
    return `<div class="at-box"><div class="between"><h3>이름으로 자리 찾기</h3>${close}</div>
      <div class="small">장소 이름과 같은 이름의 건물 · 가게 · 역을 찾지 못했어요. 장소를 고른 뒤 지도에서 자리를 누르세요.</div></div>`;
  }
  const rows = fd.spots.map((s) => {
    const opts = [[-1, s.had ? '지금 자리 그대로' : '놓지 않기'], ...s.options.map((o, j) => [j, o.what + (o.near ? ` · ${o.near}` : '')])];
    return `<fieldset class="at-find"><legend class="small"><b>${esc(s.name)}</b>${s.had ? ' <span class="at-um-note">(이미 놓은 장소예요)</span>' : ''}</legend>
      ${opts.map(([v, label]) => `<label class="small at-gen-take"><input type="radio" name="at-find-${esc(s.place)}" value="${v}" data-at-find="${esc(s.place)}"${fd.pick[s.place] === v ? ' checked' : ''}> ${esc(label)}</label>`).join('')}
      ${s.more ? `<div class="small at-um-note">같은 이름이 ${s.more}곳 더 있어요. 여기 없는 곳이면 지도에서 직접 놓아 주세요.</div>` : ''}</fieldset>`;
  }).join('');
  return `<div class="at-box at-gen"><div class="between"><h3>이름으로 자리 찾기</h3>${close}</div>
    <div class="small">장소 이름과 같은 이름의 건물 · 가게 · 역을 찾았어요. 고른 자리는 지도에 동그라미로 보여요. 같은 이름이 여러 곳이면 골라 주세요.</div>
    <div class="at-gen-places">${rows}</div>
    <div class="row">${atlasFindButton(fd)}</div></div>`;
}

function atlasFindButton(fd) {
  const n = fd.spots.filter((s) => fd.pick[s.place] >= 0).length;
  return `<button type="button" class="btn small primary" data-action="atlasFindApply" data-at-find-go${n ? '' : ' disabled'}>${n ? `${n}곳 놓기` : '고른 자리가 없어요'}</button>`;
}

Object.assign(actions, {
  async atlasFindOpen() {
    await run('자리 찾는 중', async () => {
      await atlasFindLoad();
      if (!S.atlasFind.spots.length) toast('장소 이름과 같은 이름의 건물 · 가게 · 역이 없어요');
    });
  },
  atlasFindClose() {
    S.atlasFind = null;
    atlasRefresh();
  },
  async atlasFindApply() {
    const fd = atlasFindNow();
    if (!fd) return;
    const before = atlasPinMap();
    const n = fd.spots.filter((s) => fd.pick[s.place] >= 0).length;
    const pins = atlasFindPins(before, fd.spots, fd.pick);
    if (await atlasSavePins(pins, `장소 ${n}곳을 놓았어요`, { before, label: '이름으로 자리 놓기' })) S.atlasFind = null;
    atlasRefresh();
  },
});

document.addEventListener('change', (e) => {
  const t = e.target;
  if (t.matches('[data-at-find]')) {
    const fd = atlasFindNow();
    if (!fd) return;
    fd.pick[t.dataset.atFind] = Number(t.value);
    const stage = document.getElementById('atlas-stage');
    if (stage) stage.innerHTML = atlasStage();
    const go = document.querySelector('[data-at-find-go]');
    if (go) go.outerHTML = atlasFindButton(fd);
    return;
  }
});

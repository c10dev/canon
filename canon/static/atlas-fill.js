/* 빈 블록 채우기 (OpenStreetMap 지도). 서버 canon/fill.py 가 건물이 덜 그려진 블록을 찾아 빌라촌 규칙으로 건물을 짓는다.
   지도 데이터 칸의 버튼으로 미리 보고 적용하고, 다시 누르면 지은 건물을 지운다. 지은 건물 그리기는 atlas.js 의 건물 그리기에 있다.
   app.js 의 S, actions, api, run, esc, toast, saveIfDirty 와 atlas.js 의 atlasLoad · atlasRefresh 를 쓴다. */
'use strict';

S.atlasFill = null;  // 빈 블록 채우기 미리보기 { name, preview: 서버 atlas.fill_preview } (atlasFillNow)

const atlasFillNow = () => (S.atlasFill && S.atlasFill.name === S.name ? S.atlasFill.preview : null);

/** 지도 데이터 칸 안: 채우기 버튼, 미리보기 안내, 지은 건물 지우기 */
function atlasFillBox(lo) {
  const pv = atlasFillNow();
  if (pv) {
    const msg = pv.buildings
      ? `빈 블록 ${pv.blocks}곳에 건물 ${pv.buildings.toLocaleString()}채를 지어요. OpenStreetMap에 없는 건물이에요. 지도에 점선으로 보여요.`
      : (pv.empty ? `빈 블록 ${pv.empty}곳을 찾았지만 건물이 들어갈 자리가 없어요.` : '채울 빈 블록이 없어요.');
    const swap = pv.had ? `<div class="small at-um-note">지금 지은 건물 ${pv.had.toLocaleString()}채는 지우고 새로 지어요.</div>` : '';
    return `<div class="at-fill" role="status"><div class="small"><b>빈 블록 채우기 미리보기</b> · ${msg}</div>${swap}
      <div class="row">${pv.buildings ? '<button type="button" class="btn small primary" data-action="atlasFillApply">적용</button><button type="button" class="btn small" data-action="atlasFillPreview">다른 모양 보기</button>' : ''}
        <button type="button" class="btn small ghost" data-action="atlasFillClose">닫기</button></div></div>`;
  }
  if (lo.made) {
    return `<div class="at-fill"><div class="small">빈 블록에 지은 건물 ${lo.made.toLocaleString()}채가 있어요. OpenStreetMap에 없는 건물이라 흐린 색 · 점선으로 그려요.</div>
      <div class="row"><button type="button" class="btn small ghost" data-action="atlasFillClear">지은 건물 지우기</button></div></div>`;
  }
  return `<div class="at-fill"><div class="small">건물이 덜 그려진 블록은 빌라촌 규칙으로 채울 수 있어요. 이름 · 주소 · 가게는 짓지 않아요.</div>
    <div class="row"><button type="button" class="btn small" data-action="atlasFillPreview">빈 블록 채우기</button></div></div>`;
}

/** 미리보기: 채울 블록은 옅게 칠하고 지을 건물은 점선으로 */
function atlasFillSvg(W, H) {
  const pv = atlasFillNow();
  if (!pv) return '';
  const d = (list) => list.map((ln) => `M${ln.map((q) => `${(q[0] * W).toFixed(1)},${(q[1] * H).toFixed(1)}`).join('L')}Z`).join('');
  return `<path class="at-fill-area" d="${d(pv.areas)}"></path><path class="at-fill-new" d="${d(pv.added)}"></path>`;
}

const atlasFillSeed = () => 1 + Math.floor(Math.random() * 2147483646);

Object.assign(actions, {
  async atlasFillPreview() {
    const seed = atlasFillSeed();  // 누를 때마다 새 모양 (적용하면 Atlas.fill.seed 에 남는다)
    await run('빈 블록 찾는 중', async () => {
      const preview = await api('POST', `/projects/${enc(S.name)}/atlas/layout/fill`, { mode: 'preview', seed });
      S.atlasFill = { name: S.name, preview };
    });
  },
  atlasFillClose() {
    S.atlasFill = null;
    atlasRefresh();
  },
  async atlasFillApply() {
    const pv = atlasFillNow();
    if (!pv) return;
    await run('건물 짓는 중', async () => {
      await saveIfDirty();
      const r = await api('POST', `/projects/${enc(S.name)}/atlas/layout/fill`, { mode: 'apply', seed: pv.seed });
      S.project = r.project;
      S.atlasFill = null;
      S.atlasLayout = null;  // 파일 이름은 그대로라 다시 받는다
      await atlasLoad();
      toast(`빈 블록 ${r.blocks}곳에 건물 ${r.buildings.toLocaleString()}채를 지어 채웠어요. OpenStreetMap에 없는 건물이에요.`);
    });
  },
  async atlasFillClear() {
    if (!confirm('빈 블록에 지은 건물을 지울까요? 그 건물에 놓은 장소 자리는 그대로 남아요.')) return;
    await run('지우는 중', async () => {
      await saveIfDirty();
      const r = await api('POST', `/projects/${enc(S.name)}/atlas/layout/fill`, { mode: 'clear' });
      S.project = r.project;
      S.atlasFill = null;
      S.atlasLayout = null;
      await atlasLoad();
      toast(`지은 건물 ${r.removed.toLocaleString()}채를 지웠어요`);
    });
  },
});

(() => {
  const css = document.createElement('style');
  css.textContent = `
.at-fill { margin-top: var(--space-6); display: grid; gap: var(--space-8); }
.at-map .at-fill-area { fill: var(--accent); fill-opacity: 0.08; stroke: var(--accent); stroke-opacity: 0.35; stroke-width: 0.8; stroke-dasharray: 4 3; }
.at-map .at-fill-new { fill: var(--accent); fill-opacity: 0.25; stroke: var(--accent); stroke-width: 0.8; stroke-dasharray: 2 1.5; }
`;
  document.head.appendChild(css);
})();

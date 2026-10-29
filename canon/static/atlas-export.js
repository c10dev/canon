/* 지도 내보내기 (atlas.js 에서 뗐다): 확대와 상관없이 지도 전체를 SVG 나 PNG 로 내려받는다.
   제목 틀 · 축척 막대 · 출처 글은 atlasSvg 의 장식(atlasDeco)이 함께 그린다.
   app.js 의 S, actions, run, P 와 atlas.js 의 atlasSvg · atlasH · ATLAS_W · atlasExporting 을 쓴다. */
'use strict';

// ----- 내보내기 -----

/** 내보낼 SVG: 확대와 상관없이 지도 전체를, 화면에 보이는 색을 속성으로 옮겨 적어 페이지 CSS 없이도 같게 보이게 한다 */
function atlasExportSvg() {
  const keep = S.atlasView;
  S.atlasView = { x: 0, y: 0, z: 1 };
  atlasExporting = true;
  const host = document.createElement('div');
  host.style.cssText = `position:fixed;left:-99999px;top:0;width:${ATLAS_W}px`;
  try {
    host.innerHTML = atlasSvg();
  } finally {
    S.atlasView = keep;
    atlasExporting = false;
  }
  document.body.appendChild(host);
  try {
    const svg = host.querySelector('svg');
    const ctx = document.createElement('canvas').getContext('2d');
    // 브라우저는 color-mix 결과를 color(srgb …)로 돌려준다. 다른 프로그램도 읽게 rgb() 와 따로 적은 불투명도로 바꾼다
    const color = (v) => {
      if (!v || v === 'none' || v.startsWith('url')) return [v, 1];
      ctx.fillStyle = '#000';
      ctx.fillStyle = v;
      const c = String(ctx.fillStyle);
      const m = c.match(/^color\(srgb ([-\d.e]+) ([-\d.e]+) ([-\d.e]+)(?: \/ ([-\d.e]+))?\)$/);
      if (m) return [`rgb(${[m[1], m[2], m[3]].map((x) => Math.round(Math.min(1, Math.max(0, Number(x))) * 255)).join(',')})`, m[4] == null ? 1 : Number(m[4])];
      const r = c.match(/^rgba\((\d+), (\d+), (\d+), ([\d.]+)\)$/);
      if (r) return [`rgb(${r[1]},${r[2]},${r[3]})`, Number(r[4])];
      return [c, 1];
    };
    const props = ['fill', 'stroke', 'stroke-width', 'stroke-dasharray', 'stroke-linecap', 'stroke-linejoin', 'opacity', 'font-size', 'font-weight', 'font-family', 'paint-order', 'text-anchor', 'dominant-baseline'];
    // 모두 먼저 읽고 나서 적는다. 읽으며 class 를 지우면 '.at-tok text' 처럼 부모 class 로 고르는 규칙이 자식에서 빠진다
    const all = [...svg.querySelectorAll('*')];
    all.map((el) => {
      const cs = getComputedStyle(el);
      return props.map((p) => {
        const v = cs.getPropertyValue(p);
        if (!v) return '';
        if (p !== 'fill' && p !== 'stroke') return `${p}:${v}`;
        const [c, a] = color(v);
        // CSS 의 fill-opacity · stroke-opacity(지은 건물 · 쓰임 색 · 구역)는 색의 불투명도와 곱해 적는다
        const raw = cs.getPropertyValue(`${p}-opacity`);
        const o = a * (raw === '' ? 1 : Number(raw));
        return `${p}:${c}${o < 1 ? `;${p}-opacity:${Number(o.toFixed(3))}` : ''}`;
      }).filter(Boolean).join(';');
    }).forEach((st, i) => {
      all[i].setAttribute('style', st);
      all[i].removeAttribute('class');
      all[i].removeAttribute('tabindex');
    });
    svg.querySelectorAll('.at-hit, title').forEach((el) => el.remove());
    svg.querySelectorAll('[data-action]').forEach((el) => { el.removeAttribute('data-action'); el.removeAttribute('data-arg'); });
    svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    svg.setAttribute('width', ATLAS_W);
    svg.setAttribute('height', atlasH());
    svg.removeAttribute('class');
    return new XMLSerializer().serializeToString(svg);
  } finally {
    host.remove();
  }
}

function atlasDownload(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

Object.assign(actions, {
  async atlasExport(kind) {
    await run(kind === 'png' ? 'PNG 만드는 중' : 'SVG 만드는 중', async () => {
      const svg = atlasExportSvg();
      const base = ((S.atlas.title && S.atlas.title.title) || P().meta.title || S.name).replace(/[\\/:*?"<>|]/g, '_');
      if (kind === 'svg') {
        atlasDownload(new Blob([svg], { type: 'image/svg+xml' }), `${base} 지도.svg`);
        return;
      }
      const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }));
      try {
        const img = await new Promise((ok, bad) => {
          const im = new Image();
          im.onload = () => ok(im);
          im.onerror = () => bad(new Error('지도를 그림으로 바꾸지 못했어요'));
          im.src = url;
        });
        const cv = document.createElement('canvas');
        cv.width = ATLAS_W * 2;
        cv.height = atlasH() * 2;
        cv.getContext('2d').drawImage(img, 0, 0, cv.width, cv.height);
        const blob = await new Promise((ok) => cv.toBlob(ok, 'image/png'));
        if (!blob) throw new Error('PNG를 만들지 못했어요');
        atlasDownload(blob, `${base} 지도.png`);
      } finally {
        URL.revokeObjectURL(url);
      }
    });
  },
});

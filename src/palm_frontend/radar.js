// Radar chart of a line's five trait scores (0–100), shared by the result screen (SVG) and the share image (canvas).

export function validScores(line) {
  const scores = line?.scores;
  if (line?.visibility !== 'visible' || !Array.isArray(scores) || scores.length < 3 || scores.length > 8) return [];
  return scores.every(s => s && typeof s.trait === 'string' && s.trait && Number.isInteger(s.score) && s.score >= 0 && s.score <= 100)
    ? scores : [];
}

// Axis i points up first, then clockwise; `value` 0–100 maps to 0–radius.
export function radarPoint(i, count, value, radius, cx = 0, cy = 0) {
  const angle = -Math.PI / 2 + i * 2 * Math.PI / count;
  const r = radius * Math.max(0, Math.min(100, value)) / 100;
  return [cx + Math.cos(angle) * r, cy + Math.sin(angle) * r];
}

const svgNode = (tag, attributes = {}) => {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  return node;
};
const pts = list => list.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');

export function renderRadar(name, scores) {
  const size = 260, c = size / 2, R = 84, n = scores.length;
  const svg = svgNode('svg', {viewBox: `0 0 ${size} ${size}`, class: `radar trace-${name}`, role: 'img',
    'aria-label': scores.map(s => `${s.trait} ${s.score}%`).join(', ')});
  for (const ring of [25, 50, 75, 100]) {
    svg.append(svgNode('polygon', {class: ring === 100 ? 'radar-ring outer' : 'radar-ring',
      points: pts(scores.map((_, i) => radarPoint(i, n, ring, R, c, c)))}));
  }
  scores.forEach((_, i) => {
    const [x, y] = radarPoint(i, n, 100, R, c, c);
    svg.append(svgNode('line', {class: 'radar-axis', x1: c, y1: c, x2: x.toFixed(1), y2: y.toFixed(1)}));
  });
  svg.append(svgNode('polygon', {class: 'radar-shape', points: pts(scores.map((s, i) => radarPoint(i, n, s.score, R, c, c)))}));
  scores.forEach((s, i) => {
    const [x, y] = radarPoint(i, n, s.score, R, c, c);
    svg.append(svgNode('circle', {class: 'radar-dot', cx: x.toFixed(1), cy: y.toFixed(1), r: 3.2}));
    const [lx, ly] = radarPoint(i, n, 100, R + 26, c, c);
    const anchor = Math.abs(lx - c) < 8 ? 'middle' : lx > c ? 'start' : 'end';
    const label = svgNode('text', {class: 'radar-label', x: lx.toFixed(1), y: (ly - 2).toFixed(1), 'text-anchor': anchor});
    label.textContent = s.trait;
    const value = svgNode('text', {class: 'radar-value', x: lx.toFixed(1), y: (ly + 13).toFixed(1), 'text-anchor': anchor});
    value.textContent = `${s.score}%`;
    svg.append(label, value);
  });
  return svg;
}

// Same chart on a 2D canvas, for the share/print image.
export function drawRadar(ctx, scores, cx, cy, R, color, fonts) {
  const n = scores.length;
  const path = values => {
    ctx.beginPath();
    values.forEach((v, i) => { const [x, y] = radarPoint(i, n, v, R, cx, cy); ctx[i ? 'lineTo' : 'moveTo'](x, y); });
    ctx.closePath();
  };
  ctx.lineWidth = 1;
  for (const ring of [25, 50, 75, 100]) { path(scores.map(() => ring)); ctx.strokeStyle = ring === 100 ? '#ead7ae55' : '#ead7ae22'; ctx.stroke(); }
  scores.forEach((_, i) => {
    const [x, y] = radarPoint(i, n, 100, R, cx, cy);
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x, y); ctx.strokeStyle = '#ead7ae22'; ctx.stroke();
  });
  path(scores.map(s => s.score));
  ctx.globalAlpha = .3; ctx.fillStyle = color; ctx.fill(); ctx.globalAlpha = 1;
  ctx.lineWidth = 3; ctx.strokeStyle = color; ctx.shadowColor = color; ctx.shadowBlur = 10; ctx.stroke(); ctx.shadowBlur = 0;
  scores.forEach((s, i) => {
    const [lx, ly] = radarPoint(i, n, 100, R + 34, cx, cy);
    ctx.textAlign = Math.abs(lx - cx) < 10 ? 'center' : lx > cx ? 'left' : 'right';
    ctx.font = fonts.label; ctx.fillStyle = '#c1c7b5'; ctx.fillText(s.trait, lx, ly - 2);
    ctx.font = fonts.value; ctx.fillStyle = '#f0e6cf'; ctx.fillText(`${s.score}%`, lx, ly + 24);
  });
  ctx.textAlign = 'left';
}

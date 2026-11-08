import {LINE_MARKS, LINE_NAMES, LINE_ORDER} from './copy.js';

export function tracePoints(line) {
  if (line?.visibility !== 'visible' || !Array.isArray(line.trace) || line.trace.length < 2 || line.trace.length > 24) return [];
  if (!line.trace.every(p => p && Object.keys(p).length === 2 && ['x', 'y'].every(k => typeof p[k] === 'number' && Number.isFinite(p[k]) && p[k] >= 0 && p[k] <= 1))) return [];
  return line.trace.map(p => [p.x * 1000, p.y * 1000]);
}

export const LENGTH_STEPS = ['짧음', '보통', '긺'];
export const BEND_STEPS = ['곧음', '완만', '깊음'];
const step = (value, low, high) => value < low ? 0 : value < high ? 1 : 2;

// Shape of a drawn trace in the 0–1000 map box: length against the box side, bend as the largest
// distance from the chord against the chord. Measures the drawn line only, nothing else.
export function lineShape(line) {
  const points = tracePoints(line);
  if (!points.length) return null;
  let length = 0;
  for (let i = 1; i < points.length; i++) length += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
  const [ax, ay] = points[0], [bx, by] = points[points.length - 1];
  const chord = Math.hypot(bx - ax, by - ay);
  const bend = chord ? Math.max(...points.map(([x, y]) => Math.abs((bx - ax) * (ay - y) - (ax - x) * (by - ay)) / chord)) / chord : 0;
  const lengthStep = step(length / 1000, .35, .6), bendStep = step(bend, .06, .15);
  return {points, length: length / 1000, bend,
    lengthStep, lengthLabel: LENGTH_STEPS[lengthStep], bendStep, bendLabel: BEND_STEPS[bendStep]};
}

// Small silhouette of one trace, scaled to fit, for the per-line panel.
export function renderShapeGlyph(name, points) {
  const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
  const [minX, minY] = [Math.min(...xs), Math.min(...ys)];
  const scale = 80 / Math.max(Math.max(...xs) - minX, Math.max(...ys) - minY, 1);
  const offX = (100 - (Math.max(...xs) - minX) * scale) / 2, offY = (100 - (Math.max(...ys) - minY) * scale) / 2;
  const svg = svgNode('svg', {viewBox: '0 0 100 100', class: `shape-glyph trace-${name}`, 'aria-hidden': 'true'});
  svg.append(svgNode('polyline', {points: points.map(([x, y]) => `${(offX + (x - minX) * scale).toFixed(1)},${(offY + (y - minY) * scale).toFixed(1)}`).join(' ')}));
  return svg;
}

const svgNode =(tag, attributes = {}) => {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  return node;
};

// `mirrored` shows the photo as the selfie preview did; trace x is flipped to match, labels stay readable.
export function renderPalmMap(photoUrl, result, selected, mirrored = false) {
  const figure = document.createElement('figure');
  figure.className = 'palm-map';
  if (!photoUrl) {
    const note = document.createElement('figcaption');
    note.textContent = '이 탭에 촬영 사진이 없어 선 위치를 표시하지 않습니다.';
    figure.append(note);
    return figure;
  }
  const frame = document.createElement('div');
  frame.className = 'palm-map-frame';
  const photo = document.createElement('img');
  photo.src = photoUrl;
  photo.alt = '분석에 사용한 손바닥 원본과 AI 추정선';
  if (mirrored) photo.className = 'mirrored';
  const svg = svgNode('svg', {viewBox: '0 0 1000 1000', preserveAspectRatio: 'none', role: 'img', 'aria-label': '사진 위 손금 추정 위치. 아래 손금 이름과 번호로 구분합니다.'});
  let count = 0;
  for (const name of LINE_ORDER) {
    const line = result.lines.find(item => item.name === name);
    const points = tracePoints(line).map(([x, y]) => [mirrored ? 1000 - x : x, y]);
    if (!points.length) continue;
    count++;
    const group = svgNode('g', {class: `palm-trace trace-${name}${name === selected ? ' selected' : ''}`});
    const title = svgNode('title');
    title.textContent = `${LINE_MARKS[name]} ${LINE_NAMES[name]} · AI 추정 위치`;
    const coordinates = points.map(p => p.join(',')).join(' ');
    group.append(title, svgNode('polyline', {class: 'trace-outline', points: coordinates}), svgNode('polyline', {class: 'trace-color', points: coordinates}));
    const label = svgNode('text', {x: Math.max(20, Math.min(930, points[0][0])), y: Math.max(35, Math.min(960, points[0][1] - 12)), 'aria-hidden': 'true'});
    label.textContent = LINE_MARKS[name];
    group.append(label);
    svg.append(group);
  }
  frame.append(photo, svg);
  figure.append(frame);
  if (!count) {
    const caption = document.createElement('figcaption');
    caption.textContent = '이 사진에서는 표시할 선 좌표를 얻지 못했습니다. 임의의 선은 그리지 않습니다.';
    figure.append(caption);
  }
  return figure;
}

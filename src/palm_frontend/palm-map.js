import {LINE_MARKS, LINE_NAMES, LINE_ORDER} from './copy.js';

export function tracePoints(line) {
  if (line?.visibility !== 'visible' || !Array.isArray(line.trace) || line.trace.length < 2 || line.trace.length > 24) return [];
  if (!line.trace.every(p => p && Object.keys(p).length === 2 && ['x', 'y'].every(k => typeof p[k] === 'number' && Number.isFinite(p[k]) && p[k] >= 0 && p[k] <= 1))) return [];
  return line.trace.map(p => [p.x * 1000, p.y * 1000]);
}

const svgNode = (tag, attributes = {}) => {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  return node;
};

export function renderPalmMap(photoUrl, result, selected) {
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
  const svg = svgNode('svg', {viewBox: '0 0 1000 1000', preserveAspectRatio: 'none', role: 'img', 'aria-label': '사진 위 손금 추정 위치. 아래 손금 이름과 번호로 구분합니다.'});
  let count = 0;
  for (const name of LINE_ORDER) {
    const line = result.lines.find(item => item.name === name);
    const points = tracePoints(line);
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
  const caption = document.createElement('figcaption');
  caption.textContent = count
    ? '색선은 AI가 원본 사진에서 추정한 위치입니다. 불명확한 선은 표시하지 않습니다. 사진은 이 탭에서만 표시됩니다.'
    : '이 사진에서는 표시할 선 좌표를 얻지 못했습니다. 임의의 선은 그리지 않습니다.';
  figure.append(frame, caption);
  return figure;
}

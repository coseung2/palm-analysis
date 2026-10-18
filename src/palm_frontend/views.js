import {ABOUT_FALLBACK, CHAPTERS, LINE_MARKS, LINE_NAMES, LINE_ORDER, VISIBILITY, privacyCopy} from './copy.js';
import {renderPalmMap, tracePoints} from './palm-map.js';

const el = (tag, props = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value == null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === 'hidden') node.hidden = value;
    else node.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat()) if (child != null && child !== false) node.append(child);
  return node;
};

function shell(state, actions, body) {
  return el('main', {class: 'stage'},
    el('header', {class: 'top'},
      el('a', {class: 'brand', href: '/', 'aria-label': '수문 처음으로'}, '수문'),
      el('span', {class: 'header-caption', text: 'A DREAM WRITTEN IN YOUR PALM'}),
      el('div', {class: 'top-actions'},
        el('button', {id: 'sound', class: 'small', type: 'button', 'aria-pressed': String(state.sound), 'aria-label': state.sound ? '소리 끄기' : '소리 켜기', onclick: actions.toggleSound, text: state.sound ? '소리 켜짐' : '소리 꺼짐'}))),
    body,
    el('footer', {class: 'site-footer'},
      el('span', {text: '수문 — A PALM ODYSSEY'}),
      el('button', {id: 'about', type: 'button', class: 'text-button', onclick: actions.openAbout, text: '체험 안내'}),
      el('span', {text: '당신의 다음은, 당신의 것.'})));
}

function welcome(state, actions) {
  return el('section', {id: 'welcome', class: 'screen welcome', 'aria-labelledby': 'welcomeTitle'},
    el('div', {class: 'intro-copy'},
      el('p', {class: 'kicker'}, el('span', {class: 'tiny-star', text: '✦'}), ' A RITUAL BEYOND TIME'),
      el('h1', {id: 'welcomeTitle'}, '손에 새긴 선,', el('br'), '꿈결 같은 ', el('em', {text: '당신.'})),
      el('p', {class: 'lead'}, '지나온 마음, 잊혀진 생, 아직 만나지 않은 길.', el('br'), '손을 펼치면 이야기가 시작됩니다.'),
      el('button', {id: 'start', class: 'cta', disabled: !state.serviceReady || undefined, onclick: actions.begin}, el('span', {text: '내 손금 들여다보기'}), el('span', {'aria-hidden': 'true', text: '↗'})),
      state.serviceReady ? null : el('p', {class: 'entry-note', text: '지금은 이용할 수 없습니다. 잠시 후 다시 찾아 주세요.'}),
      state.serviceReady ? el('p', {class: 'entry-note', text: '손끝에서 시작하는 작은 여행'}) : null),
    el('div', {class: 'orbital-label', 'aria-hidden': 'true'}, el('span', {text: '손금의 꿈'}), el('span', {text: '선과 선 사이, 잠시 머무는 꿈'})),
    el('div', {class: 'journey-index'}, el('span', {class: 'index-label', text: 'THE JOURNEY'}), ...CHAPTERS.map(chapter => el('span', {}, el('i', {text: chapter.numeral}), ` ${chapter.label}`))));
}

function capture(state, actions) {
  const photo = state.photo;
  return el('section', {id: 'capture', class: 'screen capture', 'aria-labelledby': 'captureTitle'},
    el('div', {class: 'capture-copy'},
      el('p', {class: 'kicker', text: '01 / THE THRESHOLD'}),
      el('h2', {id: 'captureTitle'}, '손바닥을 펼쳐', el('br'), el('em', {text: '빛 안에 놓아 주세요.'})),
      el('p', {class: 'lead'}, '웹캠 앞에서 손바닥을 안쪽 박스에 맞춰 주세요.', el('br'), '박스 안쪽만 잘라 분석합니다. 손바닥이 다 들어오게 해 주세요.'),
      el('div', {class: 'capture-tip'}, el('span', {'aria-hidden': 'true', text: '☼'}), el('p', {}, '밝은 곳에서, 손바닥이 선명하게.', el('br'), '한 손이면 충분합니다.'))),
    el('div', {class: 'capture-workspace'},
      el('div', {class: 'finder'},
        el('div', {id: 'cameraSlot', hidden: !state.cameraOn || undefined, 'aria-label': '카메라 미리보기'}),
        photo ? el('img', {id: 'preview', alt: '분석할 영역만 자른 손바닥', src: photo.url}) : null,
        el('div', {id: 'palmGuide', class: 'palm-guide', hidden: Boolean(photo) || undefined, 'aria-label': '손바닥 촬영 영역'},
          el('span', {class: 'palm-guide-label', hidden: !state.cameraOn || undefined, text: '이 박스 안쪽만 촬영'})),
        el('div', {id: 'photoHint', hidden: Boolean(photo || state.cameraOn) || undefined},
          el('svg', {viewBox: '0 0 180 230', fill: 'none', 'aria-hidden': 'true'},
            el('path', {d: 'M62 214c-6-22-24-45-37-64-7-11-2-20 6-17l25 22V70c0-17 16-17 16 0v53-88c0-16 16-16 16 0v85-99c0-17 17-17 17 0v101-85c0-17 16-17 16 0v93-61c0-17 17-17 17 0v82c0 23-12 45-17 63', stroke: 'currentColor', 'stroke-width': '1.2'}),
            el('path', {d: 'M65 156c18-11 35-7 53 1M78 137c3 28 18 45 32 50', stroke: 'currentColor', 'stroke-width': '.8', opacity: '.5'})),
          el('span', {text: '이 안에 손바닥을 담아 주세요'})),
        ...['tl', 'tr', 'bl', 'br'].map(corner => el('span', {class: `frame-corner ${corner}`, 'aria-hidden': 'true'})),
        el('span', {class: 'frame-label', 'aria-hidden': 'true', text: 'PALM / CAPTURE'})),
      el('div', {id: 'cameraControls', class: 'capture-controls'},
        el('button', {id: 'openCamera', class: 'ghost', type: 'button', hidden: state.cameraOn || undefined, onclick: actions.openCamera, text: '카메라 켜기 ↗'}),
        el('button', {id: 'takePhoto', class: 'cta', type: 'button', hidden: !state.cameraOn || undefined, onclick: actions.takePhoto, text: '이 순간 담기'}),
        el('button', {id: 'closeCamera', class: 'text-button', type: 'button', hidden: !state.cameraOn || undefined, onclick: actions.closeCamera, text: '카메라 끄기'})),
      el('label', {for: 'photo', id: 'uploadLabel', class: 'upload-label'}, '사진으로 시작하기 ', el('span', {'aria-hidden': 'true', text: '＋'})),
      el('input', {id: 'photo', class: 'file-input', type: 'file', accept: 'image/jpeg,image/png,image/webp', onchange: actions.choosePhoto}),
      state.photoError ? el('p', {class: 'entry-note', role: 'alert', text: state.photoError}) : null,
      el('label', {class: 'consent'},
        el('input', {id: 'consent', type: 'checkbox', checked: state.consent || undefined, onchange: actions.setConsent}),
        el('span', {}, '사진의 외부 분석에 동의합니다. ', el('button', {id: 'privacy', type: 'button', class: 'inline-button', onclick: event => { event.preventDefault(); actions.openPrivacy(); }, text: '처리 안내'}))),
      el('button', {id: 'analyze', class: 'cta', disabled: !(photo && state.consent && state.serviceReady) || undefined, onclick: actions.analyze}, el('span', {text: '이 손의 이야기 읽기'}), el('span', {'aria-hidden': 'true', text: '→'})),
      el('button', {class: 'text-button', id: 'back', type: 'button', onclick: actions.home, text: '처음으로'})));
}

function scan(state, actions) {
  return el('section', {id: 'scan', class: `screen scan${state.transiting ? ' transiting' : ''}`, 'aria-labelledby': 'scanTitle'},
    el('p', {class: 'kicker', text: '02 / READING THE TRACES'}),
    el('div', {class: 'scan-frame', 'aria-hidden': 'true'},
      state.photo ? el('img', {id: 'scanPhoto', alt: '', src: state.photo.url}) : null,
      el('div', {class: 'scan-grid'}), el('div', {class: 'scan-beam'}), el('span', {class: 'scan-axis', text: '✦'})),
    el('h2', {id: 'scanTitle'}, '빛이 당신의 흔적을', el('br'), '따라가고 있습니다.'),
    el('p', {class: 'lead', id: 'scanText', role: 'status', 'aria-live': 'polite', text: state.scanText}),
    el('span', {class: 'waiting-mark', 'aria-hidden': 'true', text: '· · ·'}),
    el('button', {id: 'cancel', class: 'text-button', type: 'button', onclick: actions.cancel, text: '여행 멈추기'}));
}

function reading(state, actions) {
  const chapter = CHAPTERS.find(item => item.id === state.chapter);
  const lines = LINE_ORDER.map(name => state.result.lines.find(line => line.name === name));
  const line = lines[state.lineIndex];
  return el('section', {id: 'reading', class: 'screen reading', 'aria-labelledby': 'resultTitle'},
    el('div', {class: 'reading-top'}, el('p', {class: 'kicker', text: '03 / BEYOND THE PALM'}), el('span', {id: 'hand', class: 'kicker', text: {left: '왼손', right: '오른손'}[state.result.hand] || ''})),
    el('nav', {class: 'chapter-nav', 'aria-label': '이야기 장'}, ...CHAPTERS.map(item =>
      el('button', {id: `chapter-${item.id}`, type: 'button', 'aria-current': item.id === state.chapter ? 'true' : null, onclick: () => actions.chapter(item.id)}, `${item.numeral} `, el('span', {text: item.label})))),
    el('div', {class: 'story-layout'},
      el('div', {class: 'story-heading'},
        el('p', {id: 'chapterEyebrow', class: 'kicker', text: chapter.eyebrow}),
        el('h2', {id: 'resultTitle'}, chapter.title[0], el('br'), el('em', {text: chapter.title[1]}))),
      el('div', {class: 'story-content', id: 'storyContent', tabindex: '-1'},
        state.chapter === 'present' ? present(state, actions, lines, line) : null,
        state.chapter === 'past' ? past(state, actions) : null,
        state.chapter === 'future' ? future(state) : null)),
    el('div', {class: 'reading-bottom'},
      el('div', {class: 'footer'},
        el('button', {id: 'again', class: 'text-button', type: 'button', onclick: actions.retake, text: '다시 촬영'}),
        state.chapter === 'future' ? null : el('button', {id: 'nextChapter', class: 'ghost', type: 'button', onclick: actions.nextChapter, text: '다음 장으로 →'}),
        state.chapter === 'future' ? el('button', {id: 'done', class: 'ghost', type: 'button', onclick: actions.finish, text: '여행 마치기 ↗'}) : null)));
}

function present(state, actions, lines, line) {
  return [
    el('nav', {id: 'lineTabs', class: 'line-tabs', 'aria-label': '손금 선택'}, ...lines.map((item, index) =>
      el('button', {type: 'button', 'data-reading-line': item.name, 'aria-pressed': String(index === state.lineIndex), onclick: () => actions.line(index)},
        el('span', {class: `line-key trace-${item.name}`, 'aria-hidden': 'true'}), `${LINE_MARKS[item.name]} ${LINE_NAMES[item.name]}`))),
    renderPalmMap(state.photo?.url, state.result, line.name),
    el('p', {class: 'fine', text: tracePoints(line).length ? `${LINE_NAMES[line.name]}의 추정 위치를 강조했습니다.` : `${LINE_NAMES[line.name]}: 위치 표시 보류`}),
    el('div', {id: 'storyLines', 'aria-live': 'polite'},
      el('section', {class: 'story-line', 'data-line': line.name},
        el('div', {class: 'line-header'}, el('span', {class: 'line-symbol', text: LINE_MARKS[line.name]}), el('h3', {text: LINE_NAMES[line.name]}), el('span', {class: 'trait', text: line.trait})),
        el('p', {class: 'line-reading', text: line.reading}),
        el('details', {}, el('summary', {text: '선의 흔적 살펴보기'}), el('p', {text: line.description}), el('p', {class: 'fine', text: VISIBILITY[line.visibility]})))),
    pager('line', state.lineIndex, lines.length, actions.line),
  ];
}

function past(state, actions) {
  const visions = state.result.visions;
  return el('div', {id: 'visionContent'},
    el('p', {id: 'vision', class: 'vision-text', text: visions[state.visionIndex] || ''}),
    pager('vision', state.visionIndex, visions.length, actions.vision));
}

function future(state) {
  const fate = state.result.lines.find(line => line.name === 'fate');
  const head = state.result.lines.find(line => line.name === 'head');
  return el('div', {id: 'futureContent'},
    el('p', {class: 'future-quote', text: fate.reading}),
    head ? el('p', {class: 'future-support', text: head.reading}) : null);
}

function pager(name, index, total, move) {
  const labels = {line: ['이전 손금', '다음 손금'], vision: ['이전 기억', '다음 기억']};
  return el('div', {id: name === 'line' ? 'lineNavigation' : null, class: 'vision-navigation'},
    el('button', {id: `${name}Previous`, class: 'text-button', type: 'button', 'aria-label': labels[name][0], disabled: index === 0 || undefined, onclick: () => move(index - 1), text: '←'}),
    el('span', {id: `${name}Count`, class: 'kicker', text: `${String(index + 1).padStart(2, '0')} / ${String(total).padStart(2, '0')}`}),
    el('button', {id: `${name}Next`, class: 'text-button', type: 'button', 'aria-label': labels[name][1], disabled: index >= total - 1 || undefined, onclick: () => move(index + 1), text: '→'}));
}

function failure(state, actions) {
  return el('section', {id: 'failure', class: 'screen failure', 'aria-labelledby': 'failureTitle'},
    el('p', {class: 'kicker', text: 'A MOMENT OF STILLNESS'}),
    el('h2', {id: 'failureTitle'}, '요청을 완료하지', el('br'), '못했습니다.'),
    el('p', {id: 'errorText', class: 'lead', role: 'alert', text: state.error}),
    el('button', {id: 'retry', class: 'cta', type: 'button', onclick: actions.retake, text: '다시 시도'}),
    el('button', {id: 'exit', class: 'text-button', type: 'button', onclick: actions.home, text: '처음으로'}));
}

const screens = {welcome, capture, scan, reading, failure};

export function renderApp(root, state, actions) {
  const previous = document.body.dataset.stage;
  const focus = document.activeElement?.id;
  root.replaceChildren(shell(state, actions, screens[state.screen](state, actions)));
  document.body.dataset.stage = state.screen;
  const heading = root.querySelector('h1,h2');
  const sameScreen = previous === state.screen;
  const restored = sameScreen && focus ? document.getElementById(focus) : null;
  if (restored && !restored.disabled) restored.focus({preventScroll: true});
  else if (!sameScreen && heading) { heading.tabIndex = -1; heading.focus({preventScroll: true}); }
  if (state.dialog) root.append(openDialog(state, actions));
  actions.mountCamera?.();
  if (!sameScreen) window.scrollTo(0, 0);
}

function openDialog(state, actions) {
  const node = el('dialog', {id: 'info'},
    el('div', {class: 'row'}, el('h2', {id: 'infoTitle', text: state.dialog.title}), el('button', {id: 'closeInfo', type: 'button', 'aria-label': '안내 닫기', onclick: actions.closeDialog, text: '✕'})),
    el('p', {id: 'infoText', class: 'lead', text: state.dialog.text}));
  node.addEventListener('cancel', event => { event.preventDefault(); actions.closeDialog(); });
  queueMicrotask(() => { if (node.isConnected) node.showModal(); });
  return node;
}

export function aboutText(state) {
  return state.result?.disclaimer || ABOUT_FALLBACK;
}

export function privacyText(state) {
  return privacyCopy(state.temporaryPhotoStorage);
}

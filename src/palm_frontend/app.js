import {api} from './api.js';
import {cameraErrorMessage, createCamera} from './camera.js';
import {PHOTO_LIMIT, PHOTO_TYPES, LINE_ORDER} from './copy.js';
import {isServiceReady, requireRealResult} from './contract.js';
import {createSessionClient} from './session.js';
import {aboutText, privacyText, renderApp} from './views.js';
import {printResult, renderResultImage, shareResult, shareToKakao} from './share.js';

const ANALYSIS_LIMIT = 180000;
const SCAN_NOTICE = 20000;
const SCAN_HOLD = 2600;
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
const root = document.getElementById('app');
const sessions = createSessionClient();
const camera = createCamera();
const portalSound = new Audio('/portal.wav');
portalSound.preload = 'none';
portalSound.volume = .35;

const state = {
  screen: 'welcome', serviceReady: false, temporaryPhotoStorage: false,
  sound: false, cameraOn: false, consent: false, photo: null, photoError: '',
  scanText: '손에 남은 흔적을 살피고 있습니다.', transiting: false,
  result: null, lineIndex: 0,
  error: '', dialog: null, busy: false,
};
let generation = 0;

function scene() { return window.PalmScene; }
function draw(stageChanged = false) {
  renderApp(root, state, actions);
  if (stageChanged) scene()?.setStage(state.screen);
}
function go(screen, patch = {}) {
  Object.assign(state, patch, {screen, dialog: null});
  draw(true);
}

function releasePhoto() {
  if (state.photo) URL.revokeObjectURL(state.photo.url);
  state.photo = null;
  state.consent = false;
  state.photoError = '';
}
function stopSound() { portalSound.pause(); portalSound.currentTime = 0; }
function stopCapture() { camera.stop(); state.cameraOn = false; }
function lineName(index = state.lineIndex) { return LINE_ORDER[index]; }

const actions = {
  begin() { if (state.serviceReady) go('capture'); },
  home() { leave('welcome'); },
  retake() { leave('capture'); },
  finish() { leave('welcome'); },
  cancel() { leave('welcome'); },
  toggleSound() {
    state.sound = !state.sound;
    if (state.sound) portalSound.load();
    else stopSound();
    draw();
  },
  async openCamera() {
    if (!state.serviceReady || state.busy) return;
    stopCapture();
    state.cameraOn = true;
    state.photoError = '';
    draw();
    try {
      const live = await camera.open();
      if (!live || state.screen !== 'capture') { stopCapture(); draw(); return; }
    } catch (error) {
      stopCapture();
      state.photoError = cameraErrorMessage(error);
      draw();
    }
  },
  closeCamera() { stopCapture(); draw(); },
  mountCamera() { const slot = document.getElementById('cameraSlot'); if (slot) camera.mount(slot); },
  async takePhoto() {
    const consent = state.consent;
    const file = await camera.capture();
    if (!file || state.screen !== 'capture') return;
    stopCapture();
    releasePhoto();
    // The analysed file stays unmirrored; `mirrored` only flips what is shown, like the live preview.
    state.photo = {file, url: URL.createObjectURL(file), mirrored: true};
    state.consent = consent;
    draw();
    if (consent) actions.analyze();
  },
  choosePhoto(event) {
    stopCapture();
    const selected = event.target.files?.[0];
    if (!selected) return;
    if (!PHOTO_TYPES.includes(selected.type) || selected.size > PHOTO_LIMIT) {
      releasePhoto();
      state.photoError = '5 MiB 이하의 JPEG, PNG, WebP 사진을 선택해 주세요.';
      draw();
      return;
    }
    releasePhoto();
    state.photo = {file: selected, url: URL.createObjectURL(selected)};
    draw();
  },
  setConsent(event) { state.consent = event.target.checked; draw(); },
  openAbout() { state.dialog = {title: '체험 안내', text: aboutText(state)}; draw(); },
  openPrivacy() { state.dialog = {title: '사진 처리 안내', text: privacyText(state)}; draw(); },
  closeDialog() { state.dialog = null; draw(); },
  line(index) {
    state.lineIndex = index;
    draw();
    scene()?.line(lineName());
  },
  analyze() { readPalm(); },
  share() { exportResult('share'); },
  print() { exportResult('print'); },
};

const EXPORT_NOTES = {kakao: '', shared: '', cancelled: '', saved: '결과 이미지를 저장했습니다. 카카오톡에서 사진으로 보내 주세요.'};
async function exportResult(kind) {
  if (state.exporting || !state.result) return;
  state.exporting = kind;
  state.exportNote = '';
  draw();
  try {
    const blob = await renderResultImage(state.photo?.url, state.result, Boolean(state.photo?.mirrored));
    if (kind === 'print') printResult(blob);
    // Without a configured Kakao key, fall back to the system share sheet or a saved image.
    else state.exportNote = EXPORT_NOTES[state.kakaoKey ? await shareToKakao(blob, state.kakaoKey) : await shareResult(blob)];
  } catch (error) {
    state.exportNote = `결과를 내보내지 못했습니다. ${error.message}`;
  } finally {
    state.exporting = null;
    if (state.screen === 'reading') draw();
  }
}

let leaving = null;
function leave(target) {
  if (leaving) return leaving;
  generation += 1;
  scene()?.cancelTransition();
  stopSound();
  stopCapture();
  state.busy = true;
  leaving = sessions.close().then(() => {
    releasePhoto();
    go(target, {result: null, error: '', transiting: false});
  }, error => {
    state.error = `취소를 확인하지 못했습니다. ${error.message} 다시 눌러 주세요.`;
    go('failure');
  }).finally(() => { state.busy = false; leaving = null; });
  return leaving;
}

async function readPalm() {
  if (state.busy || !state.photo || !state.consent) return;
  const image = state.photo.file;
  const run = ++generation;
  const started = Date.now();
  state.busy = true;
  go('scan', {scanText: '손에 남은 흔적을 살피고 있습니다.', transiting: false});
  try {
    const session = await sessions.open(true);
    if (run !== generation) return;
    const upload = {headers: {'Content-Type': image.type}, body: image};
    let view = await api(`/v1/sessions/${session.id}/analysis`, {method: 'POST', ...upload, headers: {...upload.headers, 'Idempotency-Key': crypto.randomUUID()}}, session.access_token);
    const deadline = Date.now() + ANALYSIS_LIMIT;
    while (view.status === 'analyzing' && run === generation) {
      if (Date.now() >= deadline) {
        try { await sessions.close(); }
        catch { throw new Error('오래 기다렸지만 취소를 확인하지 못했습니다. 다시 시도하면 기존 여행의 취소를 먼저 확인합니다.'); }
        throw new Error('대기 시간이 길어져 여행을 멈췄습니다. 다시 촬영해 주세요.');
      }
      if (Date.now() - started > SCAN_NOTICE && state.scanText.startsWith('손')) {
        state.scanText = '조금 더 시간이 필요합니다. 연결을 유지해 주세요.';
        draw();
      }
      await new Promise(resolve => setTimeout(resolve, 1200));
      if (run !== generation) return;
      view = await api(`/v1/sessions/${session.id}`, {}, session.access_token);
    }
    if (run !== generation) return;
    if (view.status !== 'completed' || !view.result) throw new Error(view.error?.message || '이야기를 읽지 못했습니다. 다시 촬영해 주세요.');
    requireRealResult(view.result);
    sessions.remember(view);
    await new Promise(resolve => setTimeout(resolve, Math.max(0, (reducedMotion.matches ? 0 : SCAN_HOLD) - (Date.now() - started))));
    if (run !== generation) return;
    state.scanText = '이제, 시간 너머로.';
    state.transiting = true;
    draw();
    if (state.sound && !document.hidden) portalSound.play().catch(() => {});
    await (scene()?.transit() || Promise.resolve());
    if (run !== generation) return;
    // Keep only the tab-local preview URL for the result overlay; leaving revokes it.
    if (state.photo) state.photo.file = null;
    go('reading', {result: view.result, lineIndex: 0, exportNote: ''});
  } catch (error) {
    if (run !== generation) return;
    releasePhoto();
    go('failure', {error: error.message});
  } finally { if (run === generation) state.busy = false; }
}

async function connect() {
  try {
    const health = await api('/health');
    if (!isServiceReady(health)) throw new Error('unavailable');
    state.temporaryPhotoStorage = health.temporary_photo_storage === true;
    state.kakaoKey = /^[0-9a-f]{32}$/.test(health.kakao_js_key || '') ? health.kakao_js_key : null;
    state.serviceReady = true;
  } catch { state.serviceReady = false; }
  if (state.screen === 'welcome') draw();
}

addEventListener('pagehide', () => { stopCapture(); stopSound(); releasePhoto(); });
addEventListener('visibilitychange', () => { if (document.hidden) { stopCapture(); stopSound(); if (state.screen === 'capture') draw(); } });

draw();
connect();

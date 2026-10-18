const MAX_EDGE = 2048;

export function sourceCrop(width, height, preview, guide) {
  if (![width, height, preview.width, preview.height, guide.width, guide.height].every(v => Number.isFinite(v) && v > 0)) return null;
  const scale = Math.max(preview.width / width, preview.height / height);
  const offsetX = (width * scale - preview.width) / 2;
  const offsetY = (height * scale - preview.height) / 2;
  // CSS mirrors the preview only. Map its guide back to unmirrored source pixels.
  const x = Math.max(0, (preview.width - (guide.left - preview.left) - guide.width + offsetX) / scale);
  const y = Math.max(0, (guide.top - preview.top + offsetY) / scale);
  const cropWidth = Math.min(width - x, guide.width / scale);
  const cropHeight = Math.min(height - y, guide.height / scale);
  if (cropWidth < 1 || cropHeight < 1) return null;
  return {x, y, width: cropWidth, height: cropHeight};
}

export function cameraErrorMessage(error) {
  const code = error?.name && error.name !== 'Error' ? error.name : error?.message;
  if (['NotAllowedError', 'PermissionDeniedError', 'SecurityError'].includes(code)) {
    return '카메라 접근이 차단됐습니다. 주소창의 사이트 설정에서 카메라를 허용해 주세요. 앱 안에서 연 링크라면 Chrome이나 Safari에서 직접 열어 주세요.';
  }
  if (['NotReadableError', 'TrackStartError'].includes(code)) {
    return '카메라를 다른 앱이 사용 중이거나 기기에서 시작하지 못했습니다. 다른 카메라 앱을 닫고 다시 켜 주세요.';
  }
  if (['NotFoundError', 'DevicesNotFoundError'].includes(code)) {
    return '사용 가능한 카메라를 찾지 못했습니다. 기기 연결을 확인하거나 사진으로 시작해 주세요.';
  }
  if (['OverconstrainedError', 'ConstraintNotSatisfiedError'].includes(code)) {
    return '이 기기에서 카메라 설정을 지원하지 않습니다. 사진으로 시작해 주세요.';
  }
  if (code === 'camera_unavailable') {
    return '이 브라우저에서는 카메라를 사용할 수 없습니다. HTTPS 주소를 Chrome이나 Safari에서 직접 열거나 사진으로 시작해 주세요.';
  }
  if (code === 'AbortError') return '카메라 연결이 중단됐습니다. 카메라 켜기를 다시 눌러 주세요.';
  return '카메라 미리보기를 시작하지 못했습니다. 카메라를 다시 켜거나 사진으로 시작해 주세요.';
}

export function createCamera({video = document.createElement('video'), getUserMedia = constraints => {
  if (!globalThis.navigator?.mediaDevices?.getUserMedia) throw new Error('camera_unavailable');
  return navigator.mediaDevices.getUserMedia(constraints);
}} = {}) {
  video.autoplay = true;
  video.playsInline = true;
  video.muted = true;
  video.setAttribute('playsinline', '');
  video.setAttribute('webkit-playsinline', '');
  let stream = null;
  let generation = 0;

  function stop() {
    generation += 1;
    stream?.getTracks().forEach(track => track.stop());
    stream = null;
    video.srcObject = null;
  }

  async function open() {
    stop();
    const run = generation;
    let opened;
    try {
      opened = await getUserMedia({
        video: {width: {ideal: 1920}, height: {ideal: 1080}},
        audio: false,
      });
    } catch (error) {
      if (run !== generation) return false;
      if (!['OverconstrainedError', 'ConstraintNotSatisfiedError', 'NotFoundError'].includes(error?.name)) throw error;
      // Some mobile/webview camera drivers reject even ideal constraints.
      opened = await getUserMedia({video: true, audio: false});
    }
    if (run !== generation) { opened.getTracks().forEach(track => track.stop()); return false; }
    stream = opened;
    video.srcObject = opened;
    try {
      await video.play();
    } catch (error) {
      if (run !== generation) return false;
      stop();
      throw error;
    }
    return run === generation;
  }

  function mount(slot) {
    if (slot && video.parentElement !== slot) {
      slot.replaceChildren(video);
      // Rendering consent or controls replaces the slot; reattach the existing stream.
      if (stream) video.play().catch(() => {});
    }
  }

  async function capture() {
    const run = generation;
    if (!stream || !video.videoWidth || !video.videoHeight) return null;
    const guide = document.getElementById('palmGuide');
    if (!guide || guide.hidden) return null;
    const crop = sourceCrop(video.videoWidth, video.videoHeight, video.getBoundingClientRect(), guide.getBoundingClientRect());
    if (!crop) return null;
    const canvas = document.createElement('canvas');
    const scale = Math.min(1, MAX_EDGE / Math.max(crop.width, crop.height));
    canvas.width = Math.max(1, Math.round(crop.width * scale));
    canvas.height = Math.max(1, Math.round(crop.height * scale));
    canvas.getContext('2d').drawImage(video, crop.x, crop.y, crop.width, crop.height, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', .95));
    if (run !== generation || !blob) return null;
    return new File([blob], 'palm.jpg', {type: 'image/jpeg'});
  }

  return {open, stop, mount, capture, get active() { return Boolean(stream); }};
}

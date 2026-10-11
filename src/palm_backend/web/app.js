'use strict';
const $ = id => document.getElementById(id);
let operatorKey = '', config = null, session = null, file = null, photoUrl = null;
let generation = 0, visionTimer = null, mode = null, busy = false, demoWithoutPhoto = false, publicSessions = false;
let cameraStream = null, cameraGeneration = 0;
function stopCamera() {
  cameraGeneration++;
  cameraStream?.getTracks().forEach(track => track.stop()); cameraStream = null;
  $('camera').srcObject = null; $('camera').hidden = true;
  $('takePhoto').hidden = true; $('closeCamera').hidden = true;
  $('openCamera').hidden = false; $('openCamera').disabled = false;
}
const names = {life:'生 · 생명선',head:'知 · 두뇌선',heart:'情 · 감정선',fate:'路 · 운명선'};
function show(id) {
  if (id !== 'capture') stopCamera();
  clearTimeout(visionTimer);
  document.querySelectorAll('.screen').forEach(el => { el.hidden = el.id !== id; });
  window.scrollTo(0, 0);
}
function message(text) { $('notice').textContent = text; }
async function api(path, options = {}, token = operatorKey) {
  const response = await fetch(path, {...options, signal:options.signal || AbortSignal.timeout(45000), headers: {...options.headers, ...(token ? {Authorization:`Bearer ${token}`} : {})}});
  if (!response.headers.get('Content-Type')?.includes('application/json')) throw new Error('부스 서버의 응답을 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.');
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || '서버 요청을 완료하지 못했습니다.');
  return data;
}
function json(body) { return {headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}; }
function resetPhoto() {
  if (photoUrl) URL.revokeObjectURL(photoUrl);
  photoUrl = null; file = null; $('photo').value = '';
  $('preview').hidden = true; $('preview').removeAttribute('src'); $('photoHint').hidden = false;
  $('consent').checked = false; updateAnalyze();
}
function updateAnalyze() { $('analyze').disabled = busy || (!file && !demoWithoutPhoto) || (!operatorKey && !publicSessions) || (mode !== 'demo' && !$('consent').checked); }
async function cancelSession() {
  generation++; clearTimeout(visionTimer);
  if (session) {
    const old = session;
    await api(`/v1/sessions/${old.id}`, {method:'DELETE'}, old.access_token);
    session = null;
  }
  busy = false; updateAnalyze();
}
async function reset(target) {
  try { await cancelSession(); resetPhoto(); message(''); show(target); }
  catch (error) { message(`취소 확인 실패: ${error.message} 다시 시도해 주세요.`); }
}
$('start').onclick = () => {
  if (!operatorKey && !publicSessions) { $('settings').showModal(); $('operatorKey').focus(); message('부스 운영자가 먼저 연결해 주세요.'); return; }
  show('capture');
};
$('operator').onclick = () => $('settings').showModal();
$('closeSettings').onclick = () => $('settings').close();
$('loginForm').onsubmit = async event => {
  event.preventDefault();
  const candidate = $('operatorKey').value;
  $('operatorKey').value = '';
  try {
    const permission = await api('/v1/operator', {}, candidate);
    if (permission.can_configure !== true && permission.role !== 'admin') throw new Error('설정 변경 권한이 없습니다.');
    config = await api('/v1/config', {}, candidate); operatorKey = candidate;
    $('loginForm').hidden = true; $('configForm').hidden = false;
    fillConfig(); $('settingsStatus').textContent = '운영자 연결 완료'; updateAnalyze(); message('부스 준비 완료');
  } catch (error) { $('settingsStatus').textContent = error.message; }
};
function fillConfig() { $('title').value = config.title; $('theme').value = config.story_theme; $('visionMs').value = config.vision_step_ms; }
$('configForm').onsubmit = async event => {
  event.preventDefault();
  try {
    config = await api('/v1/config', {method:'PUT', ...json({...config,title:$('title').value,story_theme:$('theme').value,vision_step_ms:Number($('visionMs').value)})});
    $('settingsStatus').textContent = '설정 저장 완료 · 다음 체험부터 적용됩니다.';
  } catch (error) { $('settingsStatus').textContent = error.message; }
};
$('logout').onclick = async () => {
  try {
    await cancelSession(); operatorKey = ''; config = null; resetPhoto();
    $('loginForm').hidden = false; $('configForm').hidden = true;
    $('settingsStatus').textContent = '연결 해제 완료'; show('welcome'); message('');
  } catch (error) { $('settingsStatus').textContent = error.message; }
};
$('openCamera').onclick = async () => {
  if (demoWithoutPhoto || busy) return;
  stopCamera(); const run = cameraGeneration;
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('이 기기에서는 사진 선택을 사용해 주세요.');
    $('openCamera').disabled = true; $('closeCamera').hidden = false;
    message('카메라 사용을 허용하고, 손바닥을 화면 안에 보여 주세요.');
    const stream = await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'}},audio:false});
    if (run !== cameraGeneration || $('capture').hidden) { stream.getTracks().forEach(track => track.stop()); return; }
    cameraStream = stream; $('camera').srcObject = stream; $('camera').hidden = false;
    await $('camera').play();
    if (run !== cameraGeneration) return;
    $('takePhoto').hidden = false; $('closeCamera').hidden = false; $('openCamera').hidden = true; message('');
  } catch (error) { if (run === cameraGeneration) { stopCamera(); message('카메라를 사용할 수 없습니다. 권한을 확인하거나 사진을 선택해 주세요.'); } }
};
$('closeCamera').onclick = stopCamera;
$('takePhoto').onclick = async () => {
  const video = $('camera'), run = cameraGeneration;
  if (!cameraStream || !video.videoWidth || !video.videoHeight) return;
  $('takePhoto').disabled = true;
  try {
    const canvas = document.createElement('canvas');
    const scale = Math.min(1, 1600 / Math.max(video.videoWidth, video.videoHeight));
    canvas.width = Math.round(video.videoWidth * scale); canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', .9));
    if (run !== cameraGeneration || $('capture').hidden) return;
    if (!blob) throw new Error('capture_failed');
    resetPhoto(); file = new File([blob], 'palm.jpg', {type:'image/jpeg'});
    photoUrl = URL.createObjectURL(file); $('preview').src = photoUrl;
    $('preview').hidden = false; $('photoHint').hidden = true; stopCamera(); updateAnalyze(); message('');
  } catch { message('사진을 찍지 못했습니다. 다시 촬영하거나 사진을 선택해 주세요.'); }
  finally { $('takePhoto').disabled = false; }
};
addEventListener('pagehide', stopCamera);
addEventListener('visibilitychange', () => { if (document.hidden) stopCamera(); });
$('photo').onchange = () => {
  stopCamera();
  const selected = $('photo').files[0];
  resetPhoto();
  if (!selected) return;
  if (!['image/jpeg','image/png','image/webp'].includes(selected.type) || selected.size > 5 * 1024 * 1024) {
    message('5 MiB 이하의 JPEG, PNG, WebP 사진을 선택해 주세요.'); return;
  }
  file = selected; photoUrl = URL.createObjectURL(file);
  $('preview').src = photoUrl; $('preview').hidden = false; $('photoHint').hidden = true;
  message(''); updateAnalyze();
};
$('consent').onchange = updateAnalyze;
$('analyze').onclick = async () => {
  if (busy || (!file && !demoWithoutPhoto) || (!operatorKey && !publicSessions)) return;
  busy = true; updateAnalyze();
  const image = file, consent = $('consent').checked;
  const run = ++generation;
  show('scan'); $('scanText').textContent = demoWithoutPhoto ? '시연 체험을 준비하고 있습니다.' : '사진을 안전하게 준비하고 있습니다.';
  try {
    if (!session) {
      const created = await api('/v1/sessions', {method:'POST', ...json({external_processing_consent:consent})});
      if (run !== generation) {
        await api(`/v1/sessions/${created.id}`, {method:'DELETE'}, created.access_token); return;
      }
      session = created;
    }
    const current = session;
    $('scanText').textContent = mode === 'demo' ? '연결 확인용 시연 결과를 준비합니다. 실제 손금 검출은 하지 않습니다.' : '사진 속 선을 관찰하고 오락용 이야기를 만들고 있습니다.';
    const upload = demoWithoutPhoto ? {headers:{'Content-Type':'application/json'},body:JSON.stringify({demo:true})} : {headers:{'Content-Type':image.type},body:image};
    let view = await api(`/v1/sessions/${current.id}/analysis`, {method:'POST',...upload,headers:{...upload.headers,'Idempotency-Key':crypto.randomUUID()}}, current.access_token);
    const deadline = Date.now() + 180000;
    while (view.status === 'analyzing' && run === generation) {
      if (Date.now() >= deadline) {
        try {
          await api(`/v1/sessions/${current.id}`, {method:'DELETE'}, current.access_token);
          session = null;
        } catch { throw new Error('대기 시간이 초과됐고 취소를 확인하지 못했습니다. 다시 시도하면 기존 체험 취소를 먼저 확인합니다.'); }
        throw new Error('대기 시간이 초과되어 체험을 취소했습니다. 다시 촬영해 주세요.');
      }
      await new Promise(resolve => setTimeout(resolve, 1000));
      if (run !== generation) return;
      view = await api(`/v1/sessions/${current.id}`, {}, current.access_token);
    }
    if (run !== generation) return;
    if (view.status !== 'completed' || !view.result) throw new Error(view.error?.message || '분석이 중단되었습니다. 다시 촬영해 주세요.');
    session = {...current, ...view}; resetPhoto(); render(view.result); playVisions(view.result.visions, current.config.vision_step_ms);
  } catch (error) {
    if (run !== generation) return;
    $('errorText').textContent = error.message; show('failure');
  } finally { if (run === generation) { busy = false; updateAnalyze(); } }
};
function render(result) {
  $('resultTitle').textContent = session.config.title;
  $('hand').textContent = {left:'왼손',right:'오른손',unknown:'손 방향 미확인'}[result.hand];
  $('resultMode').textContent = result.is_demo ? '시연 예시 · 업로드 사진의 실제 손금 검출 아님' : 'AI 시각 묘사 · 오락용 해석';
  $('disclaimer').textContent = result.disclaimer;
  $('cards').replaceChildren();
  result.lines.forEach(line => {
    const card = document.createElement('article'); card.className = 'card';
    const row = document.createElement('div'); row.className = 'row';
    const heading = document.createElement('h3'); heading.textContent = names[line.name];
    const trait = document.createElement('span'); trait.className = 'trait'; trait.textContent = line.trait;
    row.append(heading, trait); card.append(row);
    [['',line.description],['reading',line.reading],['fine',{visible:'시각 관찰 · 검증된 검출 신뢰도 아님',unclear:'선이 불명확함',not_visible:'선이 보이지 않음'}[line.visibility]]].forEach(([cls,text]) => {
      const p = document.createElement('p'); p.className = cls; p.textContent = text; card.append(p);
    });
    $('cards').append(card);
  });
}
function playVisions(visions, ms) {
  if (!visions.length) { show('reading'); return; }
  show('past'); let i = 0;
  function next() {
    if (i >= visions.length) { show('reading'); return; }
    $('vision').textContent = visions[i]; $('visionCount').textContent = `${++i} / ${visions.length}`;
    visionTimer = setTimeout(next, ms);
  }
  next();
}
$('skip').onclick = () => show('reading');
for (const id of ['back','cancel','done','exit']) $(id).onclick = () => reset('welcome');
for (const id of ['again','retry']) $(id).onclick = () => reset('capture');
api('/health', {}, '').then(health => {
  mode = health.analysis_mode; demoWithoutPhoto = health.demo_without_photo === true;
  publicSessions = health.public_sessions === true;
  if (health.temporary_photo_storage === true) {
    $('consent').parentElement.querySelector('span').textContent = '사진이 Supabase 비공개 임시 저장소와 VM OCX를 통한 외부 AI 서비스로 전달되는 것에 동의합니다. 완료·실패·취소·만료 시 사진 삭제를 요청하고 실패하면 재처리합니다. 결과는 기본 1시간 보관됩니다. 이 체험은 오락용 창작입니다.';
  }
  if (demoWithoutPhoto) {
    $('cameraControls').hidden = true;
    $('photo').hidden = true; $('preview').parentElement.hidden = true;
    $('capture').querySelector('h2').textContent = '시연 이야기를 만나 보세요';
    $('capture').querySelector('.lead').textContent = '현재는 연결 확인용 시연입니다. 사진을 촬영·업로드하거나 실제 손금을 분석하지 않습니다.';
    $('analyze').textContent = '시연 이야기 보기';
    $('capture').querySelector('.kicker').textContent = '01 / 시연 준비';
    $('scan').querySelector('h2').textContent = '시연 이야기를 준비하고 있습니다';
    $('again').textContent = '새 시연'; $('retry').textContent = '다시 시연';
  }
  $('mode').textContent = mode === 'demo' ? 'DEMO · 실제 사진 분석 없이 시연합니다' : 'AI · 사진의 외부 전송 동의가 필요합니다';
  $('consent').parentElement.hidden = mode === 'demo'; updateAnalyze();
}).catch(() => { $('mode').textContent = '서버 연결 실패'; $('start').disabled = true; });
(function stars() {
  const canvas = $('space'), context = canvas.getContext('2d');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const points = Array.from({length:100}, () => ({x:Math.random(),y:Math.random(),r:Math.random()*1.3+.3}));
  let width, height, t = 0;
  function resize() {
    width = innerWidth; height = innerHeight;
    const dpr = Math.min(devicePixelRatio, 2); canvas.width = width*dpr; canvas.height = height*dpr; context.setTransform(dpr,0,0,dpr,0,0);
  }
  function frame() {
    context.fillStyle = '#07060e'; context.fillRect(0,0,width,height);
    const glow = context.createRadialGradient(width/2,height*.42,0,width/2,height*.42,Math.max(width,height)*.7);
    glow.addColorStop(0,'#14102a'); glow.addColorStop(1,'#07060e'); context.fillStyle = glow; context.fillRect(0,0,width,height);
    for (const p of points) { context.beginPath(); context.arc(((p.x+t)%1)*width,p.y*height,p.r,0,Math.PI*2); context.fillStyle = p.r>1 ? '#e7c98a88' : '#efe7d644'; context.fill(); }
    if (!reduced) { t += .00002; requestAnimationFrame(frame); }
  }
  addEventListener('resize', () => { resize(); if (reduced) frame(); }); resize(); frame();
})();

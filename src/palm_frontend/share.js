import {LINE_MARKS, LINE_NAMES, LINE_ORDER} from './copy.js';
import {lineShape} from './palm-map.js';
import {drawRadar, validScores} from './radar.js';

// One portrait image of the result (photo + traces + each line), used for both sharing and printing.
const W = 1080, PAD = 90;
const COLORS = {life: '#3987e5', heart: '#d95926', head: '#199e70', fate: '#c98500'};
const INK = '#f0e6cf', DIM = '#c1c7b5', GOLD = '#e3c797';
const SERIF = "'Gowun Batang', Batang, serif", SANS = "'Noto Sans KR', 'Malgun Gothic', sans-serif";

function wrap(ctx, text, width) {
  const lines = [];
  let current = '';
  for (const word of String(text).split(/\s+/).filter(Boolean)) {
    const next = current ? `${current} ${word}` : word;
    if (ctx.measureText(next).width <= width) { current = next; continue; }
    if (current) lines.push(current);
    current = '';
    for (const char of word) {  // a word wider than the line breaks by character
      if (ctx.measureText(current + char).width > width && current) { lines.push(current); current = ''; }
      current += char;
    }
  }
  if (current) lines.push(current);
  return lines;
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('사진을 불러오지 못했습니다.'));
    image.src = url;
  });
}

function stars(ctx, height) {
  let seed = 7;
  const random = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let i = 0; i < 140; i++) {
    ctx.globalAlpha = .15 + random() * .45;
    ctx.fillStyle = random() > .8 ? GOLD : INK;
    ctx.beginPath();
    ctx.arc(random() * W, random() * height, random() * 1.8 + .3, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}

// Lays out (and, when `draw`, paints) the sheet; returns its height.
function layout(ctx, photo, result, draw, mirrored = false) {
  let y = 120;
  const text = (value, x, font, color, align = 'left') => {
    if (!draw) return;
    ctx.font = font; ctx.fillStyle = color; ctx.textAlign = align; ctx.fillText(value, x, y);
  };
  text('수 문', PAD, `40px ${SERIF}`, INK);
  text('A DREAM WRITTEN IN YOUR PALM', W - PAD, `18px 'IBM Plex Mono', monospace`, DIM, 'right');
  y += 110;
  text('손에 새겨진', PAD, `64px ${SERIF}`, INK);
  y += 86;
  text('당신의 선.', PAD, `64px ${SERIF}`, GOLD);
  y += 60;

  if (photo) {
    const boxW = W - PAD * 2, scale = Math.min(boxW / photo.width, 760 / photo.height);
    const w = photo.width * scale, h = photo.height * scale, x = (W - w) / 2;
    if (draw) {
      ctx.save();
      ctx.beginPath(); ctx.roundRect(x, y, w, h, [w / 2, w / 2, 16, 16]); ctx.clip();
      ctx.filter = 'sepia(.35) saturate(.8) brightness(.92)';
      if (mirrored) { ctx.save(); ctx.translate(x * 2 + w, 0); ctx.scale(-1, 1); }
      ctx.drawImage(photo, x, y, w, h);
      if (mirrored) ctx.restore();
      ctx.filter = 'none';
      for (const name of LINE_ORDER) {
        const shape = lineShape(result.lines.find(line => line.name === name));
        if (!shape) continue;
        ctx.beginPath();
        shape.points.forEach(([px, py], i) => ctx[i ? 'lineTo' : 'moveTo'](x + (mirrored ? 1000 - px : px) / 1000 * w, y + py / 1000 * h));
        ctx.lineCap = ctx.lineJoin = 'round';
        ctx.strokeStyle = '#1a1a19'; ctx.lineWidth = 12; ctx.stroke();
        ctx.shadowColor = COLORS[name]; ctx.shadowBlur = 12;
        ctx.strokeStyle = COLORS[name]; ctx.lineWidth = 6; ctx.stroke();
        ctx.shadowBlur = 0;
      }
      ctx.restore();
    }
    y += h + 70;
  }

  for (const name of LINE_ORDER) {
    const line = result.lines.find(item => item.name === name);
    if (draw) { ctx.fillStyle = '#ead7ae33'; ctx.fillRect(PAD, y, W - PAD * 2, 1); }
    y += 62;
    text(LINE_MARKS[name], PAD, `30px ${SERIF}`, GOLD);
    text(LINE_NAMES[name], PAD + 70, `36px ${SERIF}`, INK);
    if (draw) { ctx.fillStyle = COLORS[name]; ctx.fillRect(W - PAD - 56, y - 14, 56, 5); }
    y += 46;
    ctx.font = `22px ${SANS}`;
    for (const row of wrap(ctx, line.visibility === 'visible' ? line.trait : '안개 속에 잠긴 선', W - PAD * 2 - 70)) {
      text(row, PAD + 70, `22px ${SANS}`, DIM);
      y += 34;
    }
    const scores = validScores(line);
    if (scores.length) {
      const R = 150, box = R * 2 + 130;
      if (draw) drawRadar(ctx, scores, W / 2, y + box / 2, R, COLORS[name], {label: `22px ${SANS}`, value: `24px 'IBM Plex Mono', monospace`});
      y += box;
    }
    y += 22;
    ctx.font = `30px ${SERIF}`;
    for (const row of wrap(ctx, line.reading, W - PAD * 2 - 70)) {
      text(row, PAD + 70, `30px ${SERIF}`, INK);
      y += 52;
    }
    y += 20;
  }
  if (draw) { ctx.fillStyle = '#ead7ae33'; ctx.fillRect(PAD, y, W - PAD * 2, 1); }
  y += 60;
  text('점수와 해석은 부스 체험용 오락 콘텐츠이며 실제 진단이나 예측이 아닙니다.', W / 2, `19px ${SANS}`, DIM, 'center');
  y += 40;
  text('수문 — A PALM ODYSSEY', W / 2, `17px 'IBM Plex Mono', monospace`, GOLD, 'center');
  return y + 90;
}

export async function renderResultImage(photoUrl, result, mirrored = false) {
  await Promise.all([`40px ${SERIF}`, `22px ${SANS}`, `18px 'IBM Plex Mono'`].map(font => document.fonts?.load(font).catch(() => {})));
  const photo = photoUrl ? await loadImage(photoUrl).catch(() => null) : null;
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  const height = layout(ctx, photo, result, false, mirrored);
  canvas.width = W;
  canvas.height = height;
  const background = ctx.createLinearGradient(0, 0, 0, height);
  background.addColorStop(0, '#1d3a42'); background.addColorStop(.55, '#142c33'); background.addColorStop(1, '#0b1a1f');
  ctx.fillStyle = background;
  ctx.fillRect(0, 0, W, height);
  const glow = ctx.createRadialGradient(W * .8, 160, 0, W * .8, 160, 700);
  glow.addColorStop(0, '#e3c7972a'); glow.addColorStop(1, '#e3c79700');
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, W, height);
  stars(ctx, height);
  ctx.textBaseline = 'alphabetic';
  layout(ctx, photo, result, true, mirrored);
  return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('이미지를 만들지 못했습니다.')), 'image/png'));
}

const KAKAO_SDK = {src: 'https://t1.kakaocdn.net/kakao_js_sdk/2.8.4/kakao.min.js',
  integrity: 'sha384-BGX7Wb16GmRFagri4bLJV2DgipVZaU2AI812GZtHtHzzDQJnfHasDXN5houxv45w'};
const KAKAO_IMAGE_LIMIT = 5 * 1024 * 1024;
let kakaoLoading = null;

function loadKakao(key) {
  kakaoLoading ||= new Promise((resolve, reject) => {
    const script = Object.assign(document.createElement('script'), {src: KAKAO_SDK.src, integrity: KAKAO_SDK.integrity, crossOrigin: 'anonymous'});
    script.onload = () => window.Kakao ? resolve(window.Kakao) : reject(new Error('카카오 연결을 불러오지 못했습니다.'));
    script.onerror = () => { kakaoLoading = null; reject(new Error('카카오 연결을 불러오지 못했습니다.')); };
    document.head.append(script);
  }).then(Kakao => { if (!Kakao.isInitialized()) Kakao.init(key); return Kakao; });
  return kakaoLoading;
}

// Smaller JPEG copy for Kakao's 5 MB upload limit.
async function kakaoImage(blob) {
  if (blob.size <= KAKAO_IMAGE_LIMIT && blob.type === 'image/jpeg') return blob;
  const bitmap = await createImageBitmap(blob);
  const canvas = Object.assign(document.createElement('canvas'), {width: bitmap.width, height: bitmap.height});
  canvas.getContext('2d').drawImage(bitmap, 0, 0);
  return new Promise((resolve, reject) => canvas.toBlob(b => b ? resolve(b) : reject(new Error('이미지를 만들지 못했습니다.')), 'image/jpeg', .86));
}

// KakaoTalk share via the Kakao SDK: the result image is uploaded to Kakao (kept up to 100 days) and sent as a feed message.
export async function shareToKakao(blob, key) {
  const Kakao = await loadKakao(key);
  const image = await kakaoImage(blob);
  const file = new File([image], 'sumun-palm.jpg', {type: 'image/jpeg'});
  const uploaded = await Kakao.Share.uploadImage({file: [file]});
  const imageUrl = uploaded?.infos?.original?.url;
  if (!imageUrl) throw new Error('결과 이미지를 카카오에 올리지 못했습니다.');
  const home = location.origin;
  const viewer = `${home}/result.html?img=${encodeURIComponent(imageUrl)}`;
  Kakao.Share.sendDefault({
    objectType: 'feed',
    content: {title: '수문 — 손에 새겨진 당신의 선', description: '생명선·감정선·두뇌선·운명선으로 읽은 나의 손금', imageUrl, link: {mobileWebUrl: home, webUrl: home}},
    // Kakao only opens links on registered domains, so the image opens through our own viewer page.
    buttons: [{title: '결과 이미지 보기', link: {mobileWebUrl: viewer, webUrl: viewer}}, {title: '나도 해보기', link: {mobileWebUrl: home, webUrl: home}}],
  });
  return 'kakao';
}

// Opens the system share sheet (KakaoTalk appears there on phones); saves the image where files can't be shared.
export async function shareResult(blob) {
  const file = new File([blob], 'sumun-palm.png', {type: 'image/png'});
  if (navigator.canShare?.({files: [file]})) {
    try {
      await navigator.share({files: [file], title: '수문 — 손에 새겨진 당신의 선'});
      return 'shared';
    } catch (error) {
      if (error?.name === 'AbortError') return 'cancelled';
    }
  }
  const url = URL.createObjectURL(blob);
  const link = Object.assign(document.createElement('a'), {href: url, download: file.name});
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
  return 'saved';
}

// Prints only the result image, via a print-only node that is removed afterwards.
export function printResult(blob) {
  const url = URL.createObjectURL(blob);
  const sheet = Object.assign(document.createElement('img'), {id: 'printSheet', alt: '손금 결과', src: url});
  const cleanup = () => { sheet.remove(); URL.revokeObjectURL(url); removeEventListener('afterprint', cleanup); };
  addEventListener('afterprint', cleanup);
  document.body.append(sheet);
  sheet.decode().catch(() => {}).then(() => window.print());
}

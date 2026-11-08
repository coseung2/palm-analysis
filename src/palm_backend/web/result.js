// Shows a KakaoTalk-shared result image. Only images on Kakao's own image hosts are displayed,
// so this page cannot be used to put arbitrary pictures under the booth's address.
(() => {
  const image = document.getElementById('result');
  const note = document.getElementById('note');
  const raw = new URLSearchParams(location.search).get('img') || '';
  let url = null;
  try {
    const parsed = new URL(raw);
    if (parsed.protocol === 'https:' && /(^|\.)kakaocdn\.net$/.test(parsed.hostname)) url = parsed.href;
  } catch {}
  if (!url) { note.textContent = '결과 이미지를 찾지 못했습니다.'; return; }
  image.onload = () => { image.hidden = false; note.textContent = '이미지를 길게 눌러 저장할 수 있습니다.'; };
  image.onerror = () => { note.textContent = '결과 이미지가 만료됐거나 불러오지 못했습니다.'; };
  image.src = url;
})();

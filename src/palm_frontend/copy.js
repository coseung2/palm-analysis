export const PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
export const PHOTO_LIMIT = 5 * 1024 * 1024;
export const LINE_NAMES = {life:'생명선', heart:'감정선', head:'두뇌선', fate:'운명선'};
export const LINE_MARKS = {life:'01', heart:'02', head:'03', fate:'04'};
export const LINE_ORDER = ['life', 'heart', 'head', 'fate'];
export const CHAPTERS = [
  {id:'present', numeral:'01', label:'손에 담긴 나', eyebrow:'손에 담긴 나', title:['지금, 당신의', '마음이 향하는 곳.']},
  {id:'past', numeral:'02', label:'먼 생의 기억', eyebrow:'먼 생의 기억', title:['아주 먼 생에서', '당신이 남긴 빛.']},
  {id:'future', numeral:'03', label:'펼쳐질 길', eyebrow:'펼쳐질 길', title:['아직 쓰이지 않은', '당신의 다음 장.']},
];
export const VISIBILITY = {
  visible:'관찰 가능한 선',
  unclear:'불명확한 선 · 해석에 한계가 있습니다',
  not_visible:'보이지 않는 선 · 해석을 보류합니다',
};

export function privacyCopy(temporaryPhotoStorage) {
  return temporaryPhotoStorage
    ? '사진은 Supabase 비공개 임시 저장소와 VM OCX를 통한 외부 AI 서비스로 전달됩니다. 완료·실패·취소·만료 시 사진 삭제를 요청하고, 실패하면 다시 처리합니다. 결과는 기본 1시간 보관됩니다. 외부 공급자의 로그·보관은 별도 정책을 따르며 완전 삭제를 보장하지 않습니다.'
    : '동의한 사진은 외부 AI 서비스로 전달됩니다. 사진은 서버 메모리에서 처리되며 결과는 기본 1시간 보관됩니다. 외부 공급자의 보관 정책은 별도로 적용됩니다. 여행을 마치거나 다시 촬영하면 기존 결과의 삭제를 요청합니다.';
}

export const ABOUT_FALLBACK = '손금·전생·미래 이야기는 오락용 해석이며 건강·수명·미래에 대한 사실 판단이 아닙니다. 화면의 스캔은 시각적 연출입니다.';

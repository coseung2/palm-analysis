export const PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
export const PHOTO_LIMIT = 5 * 1024 * 1024;
export const LINE_NAMES = {life:'생명선', heart:'감정선', head:'두뇌선', fate:'운명선'};
export const LINE_MARKS = {life:'01', heart:'02', head:'03', fate:'04'};
export const LINE_ORDER = ['life', 'heart', 'head', 'fate'];

export function privacyCopy(temporaryPhotoStorage) {
  return temporaryPhotoStorage
    ? '사진은 Supabase 비공개 임시 저장소와 VM OCX를 통한 외부 AI 서비스로 전달됩니다. 완료·실패·취소·만료 시 사진 삭제를 요청하고, 실패하면 다시 처리합니다. 결과는 기본 1시간 보관됩니다. 외부 공급자의 로그·보관은 별도 정책을 따르며 완전 삭제를 보장하지 않습니다.'
    : '동의한 사진은 외부 AI 서비스로 전달됩니다. 사진은 서버 메모리에서 처리되며 결과는 기본 1시간 보관됩니다. 외부 공급자의 보관 정책은 별도로 적용됩니다. 여행을 마치거나 다시 촬영하면 기존 결과의 삭제를 요청합니다.';
}

export const ABOUT_FALLBACK = '손금 해석은 오락용이며 건강·수명·미래에 대한 사실 판단이 아닙니다. 화면의 스캔은 시각적 연출입니다.';

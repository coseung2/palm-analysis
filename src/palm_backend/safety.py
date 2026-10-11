"""Conservative launch guard, not a complete medical/prediction safety classifier."""
from .errors import ProviderError
from .models import Story

BLOCKED_PHRASES = (
    '수명', '사망', '죽음', '질병', '진단', '치료', '임신',
    '암에 걸', '암을 앓', '반드시 성공', '반드시 부자', '확실히 성공',
    '과학적으로 검증', '실제 전생', '전생의 사실',
)


def validate_story(story: Story) -> Story:
    texts = [line.reading for line in story.readings] + story.visions
    if any(phrase in text for text in texts for phrase in BLOCKED_PHRASES):
        raise ProviderError('unsafe_provider_result', '안전 기준에 맞지 않아 결과를 표시하지 않습니다.')
    return story

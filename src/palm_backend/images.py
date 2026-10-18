import hashlib
import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from .enhancement import enhance_palm
from .errors import ApiError
from .palm_roi import locate_palm
from .timing import stage


@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    digest: str
    media_type: str = "image/jpeg"
    palm_detail: bytes | None = None
    enhanced_detail: bytes | None = None


def prepare_image(data: bytes, declared_type: str | None) -> PreparedImage:
    with stage('image_normalize'):
        return _prepare_image(data, declared_type)


def _prepare_image(data: bytes, declared_type: str | None) -> PreparedImage:
    allowed = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
    if declared_type not in allowed:
        raise ApiError(415, "unsupported_image", "JPEG, PNG, WebP 사진만 사용할 수 있습니다.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format != allowed[declared_type]:
                    raise ApiError(415, "image_type_mismatch", "파일 내용과 사진 형식이 다릅니다.")
                if getattr(image, "n_frames", 1) != 1:
                    raise ApiError(
                        422, "animated_image", "움직이는 이미지 대신 사진 한 장을 올려 주세요."
                    )
                if image.width * image.height > 16_000_000:
                    raise ApiError(
                        413, "image_dimensions", "사진 해상도를 1,600만 화소 이하로 줄여 주세요."
                    )
                if min(image.size) < 256:
                    raise ApiError(
                        422, "image_too_small", "손바닥이 잘 보이는 큰 사진을 올려 주세요."
                    )
                image.verify()
            with Image.open(io.BytesIO(data)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                detail = None
                try:
                    with stage('palm_roi'):
                        box = locate_palm(image)
                except Exception:
                    box = None  # A local detector failure must not reject a valid photo.
                if box:
                    crop = image.crop(box)
                    crop.thumbnail((2048, 2048))
                    out = io.BytesIO()
                    crop.save(out, format="JPEG", quality=95)
                    detail = out.getvalue()
                image.thumbnail((2048, 2048))
                enhanced = None
                try:
                    with stage('image_enhance'):
                        enhanced = enhance_palm(image)
                except Exception:
                    pass  # Auxiliary enhancement must not reject a usable original.
                out = io.BytesIO()
                image.save(out, format="JPEG", quality=95)
                normalized = out.getvalue()
    except ApiError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ApiError(
            422, "invalid_image", "사진을 읽을 수 없습니다. 다시 촬영해 주세요."
        ) from exc
    return PreparedImage(data=normalized, digest=hashlib.sha256(normalized).hexdigest(),
                         palm_detail=detail, enhanced_detail=enhanced)

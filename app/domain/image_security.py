# app/domain/image_security.py

"""
업로드 이미지 검증과 재인코딩.

**핵심은 원본을 저장하지 않는 것이다.** 받은 바이트를 Pillow로 열어 픽셀만 꺼낸 뒤
새 파일로 다시 인코딩한다. 그러면 원본에 무엇이 붙어 있었든 살아남지 못한다.

원본을 그대로 저장할 때 통과하는 것들:
    - 폴리글롯 파일. GIF 헤더로 시작하면서 뒷부분이 유효한 JavaScript나 PHP인 파일이
      있다. 확장자 검사도 매직 바이트 검사도 통과한다.
    - 이미지 뒤에 붙인 임의 데이터. 대부분의 디코더는 이미지가 끝나면 나머지를
      무시하므로 열리기는 열린다.
    - EXIF. 촬영 위치(GPS)와 기기 정보가 들어 있다. 판매자가 집에서 찍은 사진을
      올리면 집 좌표가 그대로 공개된다.

재인코딩 한 번이 이 셋을 동시에 해결한다. 검사를 늘리는 것보다 확실하다 —
검사는 우회 기법이 새로 나오면 뚫리지만, 픽셀만 옮겨 담으면 옮길 것이 픽셀뿐이다.

SVG는 아예 받지 않는다. 텍스트 포맷이고 안에 <script>가 들어간다. 래스터로
변환해서 받을 수도 있지만, 시연에 필요하지 않은 공격면이다.
"""

import io
import logging
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

# 받아들일 형식. Pillow가 판정한 결과로만 본다 — 확장자도 Content-Type도
# 클라이언트가 보내는 값이라 믿을 수 없다.
ALLOWED_FORMATS: frozenset[str] = frozenset({"JPEG", "PNG", "WEBP", "GIF"})

# 저장 형식. 무엇이 들어오든 JPEG 하나로 통일한다. 형식이 여러 개면 서빙할 때
# Content-Type을 형식별로 관리해야 하고, 확장자와 실제 내용이 어긋날 여지도 남는다.
OUTPUT_FORMAT = "JPEG"
OUTPUT_EXTENSION = ".jpg"
OUTPUT_QUALITY = 85

# 저장할 최대 변. 원본이 크면 이 크기에 맞춰 줄인다.
# 목록 썸네일과 상세 이미지에 이 이상은 필요 없다.
MAX_DIMENSION = 1600

# 디코딩을 허용할 최대 픽셀 수.
#
# 압축 폭탄 방어다. 100KB짜리 PNG가 50000x50000으로 풀리면 디코딩에만 수 GB가
# 필요하다. Pillow에도 기본 상한이 있지만 경고만 내고 넘어가는 설정이 있어,
# 여기서 명시적으로 막는다.
MAX_PIXELS = 40_000_000  # 약 6300x6300

# 받아들일 최대 바이트. 라우터가 스트림을 읽으며 이 값으로 먼저 끊는다.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024


class ImageRejected(ValueError):
    """이미지로 받아들일 수 없는 입력. 메시지는 사용자에게 그대로 보여도 된다."""


@dataclass(frozen=True, slots=True)
class SafeImage:
    """재인코딩을 마친 이미지. data를 그대로 파일로 쓰면 된다."""

    data: bytes
    width: int
    height: int
    extension: str = OUTPUT_EXTENSION


def sanitize_image(raw: bytes) -> SafeImage:
    """
    업로드 바이트를 검증하고 안전한 JPEG로 다시 인코딩한다.

    받아들일 수 없으면 ImageRejected를 올린다. 사유 문구는 사용자에게 보여줄 수
    있는 수준으로만 쓴다 — "PNG 청크 파싱 실패" 같은 내부 사정을 그대로 내보내면
    공격자에게 디코더 정보를 알려주는 셈이다.
    """
    if not raw:
        raise ImageRejected("빈 파일입니다.")

    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImageRejected(
            f"파일이 너무 큽니다. 최대 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB까지 가능합니다."
        )

    # 1단계: 헤더만 읽어 형식과 크기를 본다.
    #
    # verify()는 픽셀을 디코딩하지 않으므로, 압축 폭탄을 실제로 풀기 전에 크기를
    # 확인할 수 있다. 순서를 바꾸면 방어가 되지 않는다.
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            fmt = (probe.format or "").upper()
            width, height = probe.size
    except UnidentifiedImageError as exc:
        raise ImageRejected("이미지 파일로 읽을 수 없습니다.") from exc
    except Exception as exc:  # noqa: BLE001
        logger.debug("이미지 헤더 판독 실패: %s: %s", type(exc).__name__, exc)
        raise ImageRejected("이미지 파일로 읽을 수 없습니다.") from exc

    if fmt not in ALLOWED_FORMATS:
        raise ImageRejected(
            f"지원하지 않는 형식입니다. {', '.join(sorted(ALLOWED_FORMATS))}만 올릴 수 있습니다."
        )

    if width * height > MAX_PIXELS:
        raise ImageRejected("이미지 해상도가 너무 큽니다.")

    if width < 1 or height < 1:
        raise ImageRejected("이미지 크기를 읽을 수 없습니다.")

    # 2단계: 픽셀을 디코딩해 새로 인코딩한다.
    #
    # 여기서 원본의 모든 부가 정보가 사라진다. EXIF도, 이미지 뒤에 붙은 데이터도,
    # 폴리글롯의 나머지 절반도 새 파일에는 들어가지 않는다.
    try:
        with Image.open(io.BytesIO(raw)) as image:
            # RGB로 통일한다. JPEG는 알파 채널을 저장하지 못하고, 팔레트 이미지를
            # 그대로 저장하면 색이 뭉개진다. 투명 배경은 흰색으로 깔아 준다.
            if image.mode in ("RGBA", "LA", "P"):
                converted = image.convert("RGBA")
                canvas = Image.new("RGB", converted.size, (255, 255, 255))
                canvas.paste(converted, mask=converted.split()[-1])
                image = canvas
            elif image.mode != "RGB":
                image = image.convert("RGB")

            image.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

            buffer = io.BytesIO()
            # exif를 넘기지 않는다. 기본값이 그렇지만, 나중에 누가 원본 exif를
            # 옮기고 싶어질 때 이 줄이 이유를 상기시킨다.
            image.save(buffer, format=OUTPUT_FORMAT, quality=OUTPUT_QUALITY, optimize=True)

            return SafeImage(
                data=buffer.getvalue(),
                width=image.width,
                height=image.height,
            )
    except ImageRejected:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("이미지 재인코딩 실패: %s: %s", type(exc).__name__, exc)
        raise ImageRejected("이미지를 처리할 수 없습니다.") from exc

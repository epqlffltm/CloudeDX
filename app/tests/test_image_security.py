# app/tests/test_image_security.py
"""이미지 업로드 검증·재인코딩의 보안 계약."""

import io

import pytest
from PIL import Image

from app.domain import image_security
from app.domain.image_security import ImageRejected, sanitize_image


def _bytes(image: Image.Image, fmt: str, **save_kwargs) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **save_kwargs)
    return buffer.getvalue()


def test_empty_file_is_rejected():
    with pytest.raises(ImageRejected, match="빈 파일"):
        sanitize_image(b"")


def test_text_and_svg_are_rejected():
    for raw in (b"hello", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'):
        with pytest.raises(ImageRejected):
            sanitize_image(raw)


def test_png_is_reencoded_as_jpeg():
    raw = _bytes(Image.new("RGB", (20, 10), (10, 20, 30)), "PNG")

    safe = sanitize_image(raw)

    assert safe.extension == ".jpg"
    with Image.open(io.BytesIO(safe.data)) as result:
        assert result.format == "JPEG"
        assert result.size == (20, 10)


def test_transparent_png_is_flattened_on_white():
    raw = _bytes(Image.new("RGBA", (10, 10), (0, 0, 0, 0)), "PNG")

    safe = sanitize_image(raw)

    with Image.open(io.BytesIO(safe.data)) as result:
        pixel = result.convert("RGB").getpixel((5, 5))

    assert all(channel >= 245 for channel in pixel)


def test_large_dimension_is_downscaled():
    raw = _bytes(Image.new("RGB", (2000, 1000), (20, 30, 40)), "PNG")

    safe = sanitize_image(raw)

    assert (safe.width, safe.height) == (1600, 800)


def test_pixel_limit_is_checked_before_full_processing(monkeypatch):
    monkeypatch.setattr(image_security, "MAX_PIXELS", 100)
    raw = _bytes(Image.new("RGB", (11, 10), (0, 0, 0)), "PNG")

    with pytest.raises(ImageRejected, match="해상도가 너무 큽니다"):
        sanitize_image(raw)


def test_exif_is_removed():
    image = Image.new("RGB", (20, 20), (100, 80, 60))
    exif = Image.Exif()
    exif[270] = "private-metadata"
    raw = _bytes(image, "JPEG", exif=exif)

    safe = sanitize_image(raw)

    with Image.open(io.BytesIO(safe.data)) as result:
        assert len(result.getexif()) == 0


def test_trailing_payload_is_not_preserved():
    marker = b"<script>should-not-survive</script>"
    raw = _bytes(Image.new("RGB", (20, 20), (1, 2, 3)), "PNG") + marker

    safe = sanitize_image(raw)

    assert marker not in safe.data

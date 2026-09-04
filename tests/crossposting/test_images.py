"""PillowImageProcessor against real Pillow-generated images, not mocks."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from diffus.crossposting.domain.errors import InvalidImageError
from diffus.crossposting.infrastructure.media import images as images_module
from diffus.crossposting.infrastructure.media.images import PillowImageProcessor


def encode(image: Image.Image, image_format: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


def test_a_too_tall_image_is_centre_cropped_to_exactly_4_to_5():
    data = encode(Image.new("RGB", (1000, 3000), "red"))

    result = PillowImageProcessor().normalise(data)

    assert (result.width, result.height) == (1000, 1250)
    assert result.content_type == "image/jpeg"


def test_a_too_wide_image_is_cropped_to_1_91_to_1_and_then_downscaled():
    data = encode(Image.new("RGB", (3000, 1000), "blue"))

    result = PillowImageProcessor().normalise(data)

    assert result.width == 1440
    assert round(result.width / result.height, 2) == 1.91


def test_a_wide_upload_never_ends_up_wider_than_1440px_or_past_the_ratio_cap():
    data = encode(Image.new("RGB", (3000, 1500), "green"))

    result = PillowImageProcessor().normalise(data)

    assert result.width == 1440
    assert result.width / result.height <= images_module.MAX_RATIO + 0.01


def test_an_image_within_the_ratio_window_is_only_downscaled_not_cropped():
    # 1.5:1, comfortably inside 4:5 … 1.91:1: cropping would be a bug here.
    data = encode(Image.new("RGB", (3000, 2000), "yellow"))

    result = PillowImageProcessor().normalise(data)

    assert result.width == 1440
    assert result.height == 960


def test_an_image_with_an_alpha_channel_becomes_a_flattened_rgb_jpeg():
    data = encode(Image.new("RGBA", (500, 500), (255, 0, 0, 128)))

    result = PillowImageProcessor().normalise(data)

    assert result.content_type == "image/jpeg"
    decoded = Image.open(io.BytesIO(result.data))
    assert decoded.mode == "RGB"


def test_garbage_bytes_are_rejected_as_an_invalid_image():
    with pytest.raises(InvalidImageError):
        PillowImageProcessor().normalise(b"not an image at all")


def test_an_upload_over_the_size_limit_is_rejected_before_it_is_even_decoded(monkeypatch):
    monkeypatch.setattr(images_module, "MAX_UPLOAD_BYTES", 10)

    with pytest.raises(InvalidImageError):
        PillowImageProcessor().normalise(b"x" * 11)

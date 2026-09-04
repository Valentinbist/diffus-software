"""Normalises an uploaded image into what Instagram's `/media` endpoint accepts.

Meta's image spec (checked 2026-09-03): JPEG only, aspect ratio between 4:5
and 1.91:1, width 320–1440 px, at most 8 MB. Doing this once at upload time
means `PublishDraft` never has to reject an image Instagram would otherwise
bounce, and every stored draft image is already the exact bytes that get
served from the public media route.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

from diffus.crossposting.domain.entities import DraftImage
from diffus.crossposting.domain.errors import InvalidImageError

# Meta rejects an upload over 8 MB; enforced on the *input* bytes so a huge
# file never reaches Image.open().
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_WIDTH = 1440
MIN_RATIO = 4 / 5
MAX_RATIO = 1.91
JPEG_QUALITY = 85


class PillowImageProcessor:
    """ImageProcessor over Pillow. Synchronous and CPU-bound — run it via asyncio.to_thread."""

    def normalise(self, data: bytes) -> DraftImage:
        if len(data) > MAX_UPLOAD_BYTES:
            raise InvalidImageError("Ein Bild ist größer als 8 MB.")

        try:
            image = Image.open(io.BytesIO(data))
            image.load()
        except (UnidentifiedImageError, OSError) as exc:
            raise InvalidImageError(
                "Ein Bild konnte nicht gelesen werden (JPEG, PNG oder WebP?)."
            ) from exc

        # exif_transpose never actually returns None for in_place=False (the
        # default); the `or image` only satisfies the type checker's Optional
        # return annotation.
        image = ImageOps.exif_transpose(image) or image
        image = image.convert("RGB")
        image = self._crop_to_ratio(image)
        image = self._downscale(image)

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return DraftImage(
            content_type="image/jpeg",
            width=image.width,
            height=image.height,
            data=buffer.getvalue(),
        )

    @staticmethod
    def _crop_to_ratio(image: Image.Image) -> Image.Image:
        """Centre-crop to the nearest of Meta's 4:5 … 1.91:1 bounds, only if outside it."""
        width, height = image.size
        ratio = width / height
        if ratio < MIN_RATIO:
            target_height = round(width / MIN_RATIO)
            top = (height - target_height) // 2
            return image.crop((0, top, width, top + target_height))
        if ratio > MAX_RATIO:
            target_width = round(height * MAX_RATIO)
            left = (width - target_width) // 2
            return image.crop((left, 0, left + target_width, height))
        return image

    @staticmethod
    def _downscale(image: Image.Image) -> Image.Image:
        if image.width <= MAX_WIDTH:
            return image
        target_height = round(image.height * MAX_WIDTH / image.width)
        return image.resize((MAX_WIDTH, target_height), Image.Resampling.LANCZOS)

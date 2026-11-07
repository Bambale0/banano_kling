"""Pure, bounded photo normalization shared by private media consumers."""
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


class ImageNormalizationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def normalize_image(source: Path, destination: Path, *, strip_metadata: bool = False) -> dict:
    try:
        with Image.open(source) as image:
            if image.format not in {'PNG', 'JPEG', 'WEBP', 'HEIF', 'HEIC'}:
                raise ImageNormalizationError('image_format_not_supported')
            if image.width * image.height > 25000000:
                raise ImageNormalizationError('media_dimensions_limit')
            image = ImageOps.exif_transpose(image)
            image = image.convert('RGBA' if 'A' in image.getbands() else 'RGB')
            if strip_metadata:
                image.info.clear()
            image.save(destination, format='PNG')
            return {'width': image.width, 'height': image.height, 'mime': 'image/png'}
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ImageNormalizationError('media_decode_failed') from exc

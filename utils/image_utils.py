import io
from typing import Tuple, Optional
from PIL import Image


def create_thumbnail(
    image_data: bytes, size: Tuple[int, int] = (100, 100)
) -> bytes:
    image = Image.open(io.BytesIO(image_data))

    # 保持宽高比
    image.thumbnail(size, Image.Resampling.LANCZOS)

    # 转换为PNG格式
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def image_to_bytes(image: Image.Image, format: str = "PNG") -> bytes:
    output = io.BytesIO()
    image.save(output, format=format)
    return output.getvalue()


def bytes_to_image(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def get_image_size(image_data: bytes) -> Tuple[int, int]:
    image = Image.open(io.BytesIO(image_data))
    return image.size

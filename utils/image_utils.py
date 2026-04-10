import io
from typing import Tuple, Optional
from PIL import Image

# 限制最大图片像素数，防止解压炸弹导致内存耗尽（约 50M 像素）
Image.MAX_IMAGE_PIXELS = 50_000_000


def create_thumbnail(
    image_data: bytes, size: Tuple[int, int] = (100, 100)
) -> bytes:
    with Image.open(io.BytesIO(image_data)) as image:
        # 保持宽高比
        image.thumbnail(size, Image.Resampling.BILINEAR)

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
    with Image.open(io.BytesIO(image_data)) as image:
        return image.size


def compress_for_cloud(image_data: bytes, max_dimension: int = 2048) -> bytes:
    """
    压缩图片用于云端上传：
    - 长边不超过 max_dimension 像素
    - 转换为 JPEG 格式（质量 85）
    - RGBA/P/LA 模式转 RGB
    """
    with bytes_to_image(image_data) as img:
        w, h = img.size

        if max(w, h) > max_dimension:
            ratio = max_dimension / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

        if img.mode in ('RGBA', 'P', 'LA'):
            img = img.convert('RGB')

        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85, optimize=True)
        return buf.getvalue()

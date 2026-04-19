import io
from typing import Tuple, Optional
from PIL import Image

# 限制最大图片像素数，防止解压炸弹导致内存耗尽（约 50M 像素）
Image.MAX_IMAGE_PIXELS = 50_000_000


def create_thumbnail(
    image_data: bytes, size: Tuple[int, int] = (100, 100)
) -> bytes:
    with Image.open(io.BytesIO(image_data)) as image:
        image.thumbnail(size, Image.Resampling.BILINEAR)
        encode_src = _flatten_to_rgb(image)
        output = io.BytesIO()
        encode_src.save(output, format="JPEG", quality=80)
        return output.getvalue()


def _flatten_to_rgb(image: Image.Image, bg=(255, 255, 255)) -> Image.Image:
    """JPEG 不支持透明，RGBA/LA/P 合成白底；其他非 RGB 直接 convert。"""
    if image.mode in ("RGBA", "LA", "P"):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, bg)
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image if image.mode == "RGB" else image.convert("RGB")


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
    # resize/convert 返回新 Image 对象，旧对象由栈变量自然释放；此处手动 close 避免大图内存驻留
    src = bytes_to_image(image_data)
    try:
        w, h = src.size
        current = src
        if max(w, h) > max_dimension:
            ratio = max_dimension / max(w, h)
            resized = src.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
            current = resized
        if current.mode in ('RGBA', 'P', 'LA'):
            converted = current.convert('RGB')
            if current is not src:
                current.close()
            current = converted
        buf = io.BytesIO()
        try:
            current.save(buf, format='JPEG', quality=85, optimize=True)
            return buf.getvalue()
        finally:
            if current is not src:
                current.close()
    finally:
        src.close()

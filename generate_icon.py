"""
生成共享剪贴板应用图标
生成多种尺寸的 PNG 图标和 ICO 文件
"""

from PIL import Image, ImageDraw
import os


def create_clipboard_icon(size: int) -> Image.Image:
    """
    创建剪贴板图标

    Args:
        size: 图标尺寸（正方形）

    Returns:
        PIL Image 对象
    """
    # 创建透明背景图像
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 计算缩放因子
    scale = size / 512

    # 颜色定义
    board_color = "#0078D4"  # 微软蓝
    clip_color = "#005A9E"  # 深蓝色夹子
    paper_color = "#FFFFFF"  # 白色纸张
    line_color = "#0078D4"  # 文字线条颜色
    sync_color = "#00B294"  # 同步箭头颜色（青绿色）

    # 绘制剪贴板主体（圆角矩形）
    board_margin = int(60 * scale)
    board_top = int(80 * scale)
    board_radius = int(40 * scale)

    draw.rounded_rectangle(
        [board_margin, board_top, size - board_margin, size - board_margin],
        radius=board_radius,
        fill=board_color,
    )

    # 绘制夹子部分
    clip_width = int(160 * scale)
    clip_height = int(80 * scale)
    clip_x = (size - clip_width) // 2
    clip_y = int(30 * scale)

    # 夹子外圈
    draw.rounded_rectangle(
        [clip_x, clip_y, clip_x + clip_width, clip_y + clip_height],
        radius=int(20 * scale),
        fill=clip_color,
    )

    # 夹子内部（挖空效果）
    inner_margin = int(20 * scale)
    draw.rounded_rectangle(
        [
            clip_x + inner_margin,
            clip_y + inner_margin,
            clip_x + clip_width - inner_margin,
            clip_y + clip_height + int(20 * scale),
        ],
        radius=int(10 * scale),
        fill=board_color,
    )

    # 绘制纸张
    paper_margin = int(90 * scale)
    paper_top = int(130 * scale)
    paper_radius = int(20 * scale)

    draw.rounded_rectangle(
        [paper_margin, paper_top, size - paper_margin, size - paper_margin - int(30 * scale)],
        radius=paper_radius,
        fill=paper_color,
    )

    # 绘制文字线条
    line_start_x = int(120 * scale)
    line_end_x = size - int(120 * scale)
    line_y_start = int(180 * scale)
    line_spacing = int(50 * scale)
    line_width = max(int(8 * scale), 2)

    for i in range(4):
        y = line_y_start + i * line_spacing
        # 最后一行短一点
        end_x = line_end_x - int(80 * scale) if i == 3 else line_end_x
        draw.rounded_rectangle(
            [line_start_x, y, end_x, y + line_width],
            radius=line_width // 2,
            fill=line_color,
        )

    # 绘制同步箭头（表示共享）
    arrow_size = int(100 * scale)
    arrow_x = size - int(120 * scale)
    arrow_y = size - int(120 * scale)

    # 圆形背景
    draw.ellipse(
        [arrow_x - arrow_size // 2, arrow_y - arrow_size // 2,
         arrow_x + arrow_size // 2, arrow_y + arrow_size // 2],
        fill=sync_color,
    )

    # 绘制双向箭头符号
    arrow_line_width = max(int(6 * scale), 2)
    arrow_head_size = int(15 * scale)

    # 中心点
    cx, cy = arrow_x, arrow_y

    # 水平线
    draw.line(
        [(cx - int(25 * scale), cy), (cx + int(25 * scale), cy)],
        fill="white",
        width=arrow_line_width,
    )

    # 左箭头
    draw.polygon(
        [
            (cx - int(25 * scale), cy),
            (cx - int(25 * scale) + arrow_head_size, cy - arrow_head_size // 2),
            (cx - int(25 * scale) + arrow_head_size, cy + arrow_head_size // 2),
        ],
        fill="white",
    )

    # 右箭头
    draw.polygon(
        [
            (cx + int(25 * scale), cy),
            (cx + int(25 * scale) - arrow_head_size, cy - arrow_head_size // 2),
            (cx + int(25 * scale) - arrow_head_size, cy + arrow_head_size // 2),
        ],
        fill="white",
    )

    return img


def main():
    """生成所有尺寸的图标"""
    # 图标尺寸列表
    sizes = [16, 32, 48, 64, 128, 256, 512]

    # 输出目录
    output_dir = os.path.dirname(os.path.abspath(__file__))
    icons_dir = os.path.join(output_dir, "icons")
    os.makedirs(icons_dir, exist_ok=True)

    images = []
    for size in sizes:
        img = create_clipboard_icon(size)
        # 保存 PNG
        png_path = os.path.join(icons_dir, f"icon_{size}.png")
        img.save(png_path, "PNG")
        print(f"Generated: {png_path}")
        images.append(img)

    # 生成 ICO 文件（Windows）
    ico_path = os.path.join(icons_dir, "app.ico")
    # ICO 文件需要包含多个尺寸
    images[0].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in sizes if s <= 256],
        append_images=[img for img in images[1:] if img.size[0] <= 256],
    )
    print(f"Generated: {ico_path}")

    # 生成主图标 (512x512)
    main_icon_path = os.path.join(output_dir, "icon.png")
    images[-1].save(main_icon_path, "PNG")
    print(f"Generated: {main_icon_path}")

    # macOS 图标 (需要 icns 格式，这里先生成 PNG)
    icns_png_path = os.path.join(icons_dir, "icon_macos.png")
    # macOS 图标推荐 1024x1024
    macos_icon = create_clipboard_icon(1024)
    macos_icon.save(icns_png_path, "PNG")
    print(f"Generated: {icns_png_path}")

    print("\nAll icons generated successfully!")
    print(f"Icons directory: {icons_dir}")


if __name__ == "__main__":
    main()

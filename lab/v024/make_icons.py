from PIL import Image, ImageDraw, ImageFont
import pathlib

OUT = pathlib.Path(__file__).parent
BG = (79, 99, 238, 255)
FG = (255, 255, 255, 255)
FONT = "C:/Windows/Fonts/segoeuib.ttf"

for size in (192, 512):
    img = Image.new("RGBA", (size, size), BG)
    d = ImageDraw.Draw(img)
    # 内层浅色描边，缩到桌面图标尺寸仍能看出边界
    inset = int(size * 0.12)
    d.rounded_rectangle([inset, inset, size - inset, size - inset], radius=int(size * 0.14),
                        outline=(255, 255, 255, 60), width=max(2, size // 128))
    font = ImageFont.truetype(FONT, int(size * 0.38))
    text = "CC"
    box = d.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    d.text(((size - tw) / 2 - box[0], (size - th) / 2 - box[1] - size * 0.01), text, font=font, fill=FG)
    img.save(OUT / f"icon-{size}.png")
    print(OUT / f"icon-{size}.png", size)

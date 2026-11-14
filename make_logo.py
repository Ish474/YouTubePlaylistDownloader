"""Generate the app logo: red rounded tile, play triangle, download badge."""
import os
from PIL import Image, ImageDraw

S = 1024


def rounded(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def main():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # subtle vertical gradient background (deep red -> bright red)
    top = (232, 42, 60)
    bottom = (150, 12, 30)
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / S
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,)
        gd.line([(0, y), (S, y)], fill=c)
    mask = Image.new("L", (S, S), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((16, 16, S - 16, S - 16), radius=210, fill=255)
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)

    # white play triangle (centered, slightly left-shifted like YouTube's logo)
    cx, cy = S * 0.46, S * 0.44
    w, h = 300, 380
    tri = [(cx - w * 0.28, cy - h / 2), (cx - w * 0.28, cy + h / 2),
           (cx + w * 0.55, cy)]
    # soften: draw shadow then triangle
    d.polygon([(x + 0, y + 10) for x, y in tri], fill=(90, 0, 10, 90))
    d.polygon(tri, fill=(255, 255, 255, 255))

    # download badge: dark circle bottom-right with white down arrow
    bx, by, br = S * 0.74, S * 0.74, S * 0.21
    d.ellipse((bx - br, by - br, bx + br, by + br), fill=(22, 22, 28, 255),
              outline=(255, 255, 255, 230), width=14)
    aw, ah = br * 0.9, br * 1.05          # arrow dims
    shaft = ah * 0.52
    ax = bx
    # shaft
    d.rounded_rectangle((ax - aw * 0.11, by - shaft, ax + aw * 0.11, by + ah * 0.28),
                        radius=int(aw * 0.1), fill=(255, 255, 255, 255))
    # arrowhead (chevron)
    d.polygon([(ax - aw * 0.48, by + ah * 0.10), (ax + aw * 0.48, by + ah * 0.10),
               (ax, by + ah * 0.62)], fill=(255, 255, 255, 255))

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
    os.makedirs(out, exist_ok=True)
    png = os.path.join(out, "logo.png")
    img.save(png)

    # multi-size ICO for the exe/window icon
    ico = os.path.join(out, "icon.ico")
    img.resize((256, 256), Image.LANCZOS).save(
        ico, format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", png, "and", ico)


if __name__ == "__main__":
    main()

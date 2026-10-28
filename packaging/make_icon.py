"""Render the project's simple spectrum mark as a multi-size Windows icon."""

from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1]
image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((0, 0, 511, 511), radius=112, fill="#12213B")
draw.line([(80, 376), (432, 376)], fill="#7097D2", width=12)
points = [
    (80, 328),
    (148, 324),
    (172, 308),
    (196, 184),
    (216, 312),
    (268, 320),
    (300, 308),
    (336, 104),
    (364, 316),
    (432, 324),
]
draw.line(points, fill="#63B6FF", width=24, joint="curve")
draw.ellipse((316, 84, 356, 124), fill="#C2E4FF")
image.save(
    root / "assets" / "imespec.ico",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
print("Windows icon generated.")

"""Generate the application icon used by the EXE and Windows Installer."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        Path(r"C:\Windows\Fonts\segoeuib.ttf"),
        Path(r"C:\Windows\Fonts\arialbd.ttf"),
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: create_icon.py OUTPUT.ico")

    output = Path(sys.argv[1]).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((12, 16, 244, 248), fill="#B7C7DF")
    draw.ellipse((8, 8, 240, 240), fill="#0C66E4")
    draw.ellipse((27, 27, 221, 221), outline="#579DFF", width=5)

    font = _font(83)
    text = "JR"
    box = draw.textbbox((0, 0), text, font=font)
    text_width = box[2] - box[0]
    text_height = box[3] - box[1]
    draw.text(
        ((size - text_width) / 2, (size - text_height) / 2 - box[1] - 2),
        text,
        fill="white",
        font=font,
    )

    image.save(
        output,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


if __name__ == "__main__":
    main()

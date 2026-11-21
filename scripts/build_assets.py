# scripts/build_assets.py
import os
import sys
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PIL import Image

def build_brand_assets(base_dir=None):
    if base_dir is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assets_dir = os.path.join(base_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    svg_path = os.path.join(assets_dir, "daqiq_logo.svg")
    png_path = os.path.join(assets_dir, "daqiq_logo.png")
    ico_path = os.path.join(assets_dir, "daqiq_logo.ico")

    if not os.path.exists(svg_path):
        raise FileNotFoundError(f"SVG logo not found at {svg_path}")

    with open(svg_path, "rb") as f:
        svg_bytes = f.read()

    # Render at 512x512 via QSvgRenderer
    renderer = QSvgRenderer(QByteArray(svg_bytes))
    image = QImage(512, 512, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    # Save PNG via QImage
    image.save(png_path, "PNG")
    print(f"Rendered PNG saved to: {png_path} ({os.path.getsize(png_path)} bytes)")

    # Open with PIL to generate multi-resolution ICO
    pil_img = Image.open(png_path).convert("RGBA")
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    pil_img.save(ico_path, format="ICO", sizes=ico_sizes)
    print(f"Generated multi-resolution ICO saved to: {ico_path} ({os.path.getsize(ico_path)} bytes)")

if __name__ == "__main__":
    build_brand_assets()

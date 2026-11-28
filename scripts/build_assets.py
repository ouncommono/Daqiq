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

    # Generate distinct metallic wrench icon for Daqiq-Troubleshooter.exe (REQ-21)
    ts_svg = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0f172a"/>
      <stop offset="100%" stop-color="#0284c7"/>
    </linearGradient>
    <linearGradient id="metal" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#f8fafc"/>
      <stop offset="100%" stop-color="#cbd5e1"/>
    </linearGradient>
  </defs>
  <rect x="24" y="24" width="464" height="464" rx="108" fill="url(#bg)" stroke="#38bdf8" stroke-width="14"/>
  <circle cx="256" cy="256" r="184" fill="none" stroke="rgba(255,255,255,0.16)" stroke-width="6"/>
  <path d="M342 120c-36-8-76 6-100 34-21 25-26 60-14 91l-96 96c-16 16-16 42 0 58 16 16 42 16 58 0l96-96c31 12 66 7 91-14 28-24 42-64 34-100l-52 52-40-11-11-40 52-52c-6-10-11-14-18-18z"
        fill="url(#metal)" stroke="#0f172a" stroke-width="10" stroke-linejoin="round"/>
  <circle cx="163" cy="369" r="12" fill="#0284c7"/>
</svg>"""
    ts_png_path = os.path.join(assets_dir, "daqiq_troubleshooter.png")
    ts_ico_path = os.path.join(assets_dir, "daqiq_troubleshooter.ico")
    ts_renderer = QSvgRenderer(QByteArray(ts_svg))
    ts_img = QImage(512, 512, QImage.Format_ARGB32_Premultiplied)
    ts_img.fill(Qt.transparent)
    ts_p = QPainter(ts_img)
    ts_renderer.render(ts_p)
    ts_p.end()
    ts_img.save(ts_png_path, "PNG")
    ts_pil = Image.open(ts_png_path).convert("RGBA")
    ts_pil.save(ts_ico_path, format="ICO", sizes=ico_sizes)
    print(f"Generated troubleshooter ICO saved to: {ts_ico_path} ({os.path.getsize(ts_ico_path)} bytes)")

if __name__ == "__main__":
    build_brand_assets()

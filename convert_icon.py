"""Convert a PNG image to ICO format for the app icon.
Usage: python convert_icon.py input.png
"""
import sys
from PIL import Image

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "icon_source.png"
    img = Image.open(src).convert("RGBA")
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save("icon.ico", format="ICO", sizes=sizes)
    print(f"icon.ico created from {src}")

if __name__ == "__main__":
    main()

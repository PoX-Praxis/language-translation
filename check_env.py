"""
Screen Translator - Environment Check
Run this script on any PC to verify all dependencies are installed.
Usage: python check_env.py
"""
import sys
import os
import shutil

print("=" * 60)
print("  Screen Translator - Environment Check")
print("=" * 60)
print()

errors = []
warnings = []

# --- Python ---
print(f"Python: {sys.version}")
v = sys.version_info
if v.major < 3 or (v.major == 3 and v.minor < 9):
    errors.append("Python 3.9+ required")
else:
    print("  [OK]")
print()

# --- Core packages ---
print("Core packages:")
core_pkgs = {
    "PIL": "Pillow",
    "pytesseract": "pytesseract",
    "mss": "mss",
    "numpy": "numpy",
}
for import_name, pkg_name in core_pkgs.items():
    try:
        mod = __import__(import_name)
        ver = getattr(mod, "__version__", getattr(mod, "VERSION", "?"))
        print(f"  {pkg_name}: {ver} [OK]")
    except ImportError:
        print(f"  {pkg_name}: NOT INSTALLED [ERROR]")
        errors.append(f"{pkg_name} not installed. Run: pip install {pkg_name}")
print()

# --- Tesseract OCR ---
print("Tesseract OCR:")
tess_found = False
tess_paths = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]
# Check PATH
tess_in_path = shutil.which("tesseract")
if tess_in_path:
    tess_found = True
    print(f"  Found in PATH: {tess_in_path} [OK]")

for p in tess_paths:
    if os.path.exists(p):
        tess_found = True
        print(f"  Found: {p} [OK]")

if not tess_found:
    print("  NOT FOUND [ERROR]")
    errors.append("Tesseract OCR not installed. Download: https://github.com/UB-Mannheim/tesseract/wiki")

# Check Japanese data
jpn_paths = [
    r"C:\Program Files\Tesseract-OCR\tessdata\jpn.traineddata",
    r"C:\Program Files (x86)\Tesseract-OCR\tessdata\jpn.traineddata",
]
jpn_found = False
for p in jpn_paths:
    if os.path.exists(p):
        jpn_found = True
        print(f"  Japanese data: {p} [OK]")
if not jpn_found and tess_found:
    print("  Japanese data: NOT FOUND [WARNING]")
    warnings.append("Japanese OCR data not installed. Reinstall Tesseract with 'Japanese' checked.")
print()

# --- PyInstaller ---
print("PyInstaller (for building exe):")
try:
    import PyInstaller
    print(f"  {PyInstaller.__version__} [OK]")
except ImportError:
    print("  NOT INSTALLED [WARNING]")
    warnings.append("PyInstaller not installed. Run: pip install pyinstaller")
print()

# --- Optional: VLM packages ---
print("Optional VLM packages (Phase 3):")
vlm_pkgs = {"torch": "torch", "transformers": "transformers", "accelerate": "accelerate"}
vlm_all = True
for import_name, pkg_name in vlm_pkgs.items():
    try:
        mod = __import__(import_name)
        ver = getattr(mod, "__version__", "?")
        print(f"  {pkg_name}: {ver} [OK]")
    except ImportError:
        print(f"  {pkg_name}: NOT INSTALLED")
        vlm_all = False

if vlm_all:
    try:
        import torch
        if torch.cuda.is_available():
            print(f"  CUDA GPU: {torch.cuda.get_device_name(0)} [OK]")
        else:
            print("  CUDA GPU: Not available (CPU mode - slow)")
    except Exception:
        pass
    try:
        from local_ocr import is_available
        print(f"  VLM OCR available: {is_available()}")
    except ImportError:
        print("  local_ocr.py: not found in current directory")
else:
    print("  VLM re-OCR: DISABLED (optional, install with: pip install torch transformers accelerate)")
print()

# --- Inno Setup ---
print("Inno Setup (for building installer):")
inno_paths = [
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]
inno_found = False
for p in inno_paths:
    if os.path.exists(p):
        inno_found = True
        print(f"  Found: {p} [OK]")
        break
if not inno_found:
    print("  NOT FOUND [WARNING]")
    warnings.append("Inno Setup not installed. Download: https://jrsoftware.org/isinfo.php")
print()

# --- DeepL API Key ---
print("DeepL API Key:")
env_key = os.environ.get("DEEPL_API_KEY", "").strip()
if env_key:
    print(f"  Environment variable: set [OK]")
else:
    config_path = os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")),
        "ScreenTranslator", "config.json"
    )
    if os.path.exists(config_path):
        import json
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if cfg.get("deepl_api_key", "").strip():
                print(f"  Config file: set [OK]")
            else:
                print(f"  Config file exists but key is empty [WARNING]")
                warnings.append("DeepL API key not set. Will be asked on first launch.")
        except Exception:
            print(f"  Config file: error reading [WARNING]")
    else:
        print("  NOT SET [WARNING]")
        warnings.append("DeepL API key not set. Will be asked on first launch.")
print()

# --- Summary ---
print("=" * 60)
if not errors and not warnings:
    print("  ALL CHECKS PASSED - Ready to build and run!")
else:
    if errors:
        print(f"  ERRORS ({len(errors)}):")
        for e in errors:
            print(f"    x {e}")
    if warnings:
        print(f"  WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"    ! {w}")
print("=" * 60)

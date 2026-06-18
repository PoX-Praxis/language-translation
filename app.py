"""
Screen Translator
- Captures text within a movable/resizable overlay frame
- Control toolbar attached to top-right of the frame
- Uses DeepL API for high-quality translation
- Auto-translates when text changes; click overlay to dismiss
"""

import concurrent.futures
import json
import os
import re
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import traceback
import urllib.request
import urllib.error
import urllib.parse

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageTk
import mss
import pytesseract

APP_NAME = "Screen Translator"
APP_VERSION = "1.2.0"

# ---------------------------------------------------------------------------
# OCR settings (all tunable constants)
# ---------------------------------------------------------------------------

# --- Phase 1: Image preprocessing ---
OCR_UPSCALE = 2.5
OCR_CONTRAST = 1.6

# --- Phase 2: Tesseract config ---
TESS_PSM = 3    # 3=auto, 6=single block, 11=sparse text
TESS_OEM = 1    # 1=LSTM only
TESS_LANG = "jpn+eng"

# --- Phase 3: conf threshold / local LLM ---
CONF_THRESHOLD = 60
SMALL_CHAR_PX = 14
MAX_LLM_BLOCKS = 3
# --- Phase 4: Chart detection & rendering ---
ENABLE_CHART_DETECTION = True
PROTECT_NUMERIC = True
NUMERIC_UNITS = ("trn", "tn", "bn", "mn", "k", "tm", "%")

# --- Rendering box / auto-fit ---
MIN_FONT_PX = 9
MAX_FONT_PX = 48
BOX_PADDING_PX = 2
LINE_SPACING_RATIO = 1.1

# ---------------------------------------------------------------------------
# Config / Tesseract detection
# ---------------------------------------------------------------------------

def _find_tesseract():
    if getattr(sys, "frozen", False):
        app_dir = os.path.dirname(sys.executable)
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__))

    candidates = [
        os.path.join(app_dir, "tesseract", "tesseract.exe"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]

    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def _setup_tesseract():
    tess = _find_tesseract()
    if tess:
        pytesseract.pytesseract.tesseract_cmd = tess
        return True
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False

LANG_OPTIONS = {
    "日本語": "ja",
    "English": "en",
    "中文": "zh-cn",
    "한국어": "ko",
    "Français": "fr",
    "Deutsch": "de",
    "Español": "es",
    "Português": "pt",
    "Русский": "ru",
    "العربية": "ar",
    "हिन्दी": "hi",
    "Italiano": "it",
    "Nederlands": "nl",
    "Türkçe": "tr",
    "Tiếng Việt": "vi",
    "ไทย": "th",
}

BORDER_WIDTH = 14
MIN_FRAME_SIZE = BORDER_WIDTH * 4
TOOLBAR_HEIGHT = 28

def _get_config_path():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.path.expanduser("~")
    return os.path.join(base, "ScreenTranslator", "config.json")


def _load_api_key():
    env_key = os.environ.get("DEEPL_API_KEY", "").strip()
    if env_key:
        return env_key

    config_path = _get_config_path()
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            key = cfg.get("deepl_api_key", "").strip()
            if key:
                return key
        except Exception:
            pass

    return ""


def _save_api_key(key):
    config_path = _get_config_path()
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    cfg = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
    cfg["deepl_api_key"] = key
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def _ask_api_key():
    import tkinter.simpledialog as sd
    root = tk.Tk()
    root.withdraw()
    key = sd.askstring(
        APP_NAME,
        "DeepL API Key を入力してください:\n\n"
        "https://www.deepl.com/pro-api で取得できます（無料プランあり）",
        parent=root,
    )
    root.destroy()
    if key and key.strip():
        key = key.strip()
        _save_api_key(key)
        return key
    return ""


DEEPL_LANG_MAP = {
    "ja": "JA", "en": "EN", "zh-cn": "ZH", "ko": "KO",
    "fr": "FR", "de": "DE", "es": "ES", "pt": "PT-BR",
    "ru": "RU", "ar": "AR", "hi": "HI", "it": "IT",
    "nl": "NL", "tr": "TR", "vi": "VI", "th": "TH",
}


# ---------------------------------------------------------------------------
# Translation engine
# ---------------------------------------------------------------------------

class DeepLEngine:
    _FREE_URL = "https://api-free.deepl.com/v2/translate"
    _PRO_URL = "https://api.deepl.com/v2/translate"

    def __init__(self, api_key=""):
        self.api_key = api_key
        self._cache = {}
        self._cache_lock = threading.Lock()

    def translate(self, text, target_code):
        if not self.api_key:
            raise RuntimeError("DeepL API key is not set")
        cache_key = (text, target_code)
        with self._cache_lock:
            if cache_key in self._cache:
                return self._cache[cache_key]
        deepl_code = DEEPL_LANG_MAP.get(target_code, target_code.upper())
        is_free = self.api_key.endswith(":fx")
        url = self._FREE_URL if is_free else self._PRO_URL
        data = urllib.parse.urlencode({
            "text": text,
            "target_lang": deepl_code,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={"Authorization": f"DeepL-Auth-Key {self.api_key}"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        tr = body["translations"][0]
        result = (tr["text"], tr.get("detected_source_language", "auto").lower())
        with self._cache_lock:
            self._cache[cache_key] = result
        return result


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _find_system_font(size=16):
    if sys.platform == "win32":
        font_dirs = [
            os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
            os.path.join(
                os.environ.get("LOCALAPPDATA", ""),
                "Microsoft", "Windows", "Fonts",
            ),
        ]
        candidate_files = [
            "BIZ-UDPGothicR.ttc",
            "BIZUDPGothic-Regular.ttc",
            "NotoSansCJKjp-Regular.otf",
            "NotoSansJP-Regular.otf",
            "NotoSansJP-Regular.ttf",
            "YuGothR.ttc",
            "YuGothM.ttc",
            "meiryoui.ttc",
            "meiryo.ttc",
            "segoeui.ttf",
            "arial.ttf",
        ]
        for font_file in candidate_files:
            for font_dir in font_dirs:
                path = os.path.join(font_dir, font_file)
                if os.path.exists(path):
                    try:
                        return ImageFont.truetype(path, size)
                    except Exception:
                        continue
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def _otsu_threshold(gray_arr):
    hist, _ = np.histogram(gray_arr.ravel(), bins=256, range=(0, 256))
    total = gray_arr.size
    sum_total = np.dot(np.arange(256), hist)
    sum_bg = 0.0
    w_bg = 0
    max_var = 0.0
    threshold = 0
    for t in range(256):
        w_bg += hist[t]
        if w_bg == 0:
            continue
        w_fg = total - w_bg
        if w_fg == 0:
            break
        sum_bg += t * hist[t]
        mean_bg = sum_bg / w_bg
        mean_fg = (sum_total - sum_bg) / w_fg
        var_between = w_bg * w_fg * (mean_bg - mean_fg) ** 2
        if var_between > max_var:
            max_var = var_between
            threshold = t
    return threshold


def _preprocess_for_ocr(pil_img):
    w, h = pil_img.size
    new_w = int(w * OCR_UPSCALE)
    new_h = int(h * OCR_UPSCALE)
    upscaled = pil_img.resize((new_w, new_h), Image.LANCZOS)

    gray = upscaled.convert("L")

    enhanced = ImageEnhance.Contrast(gray).enhance(OCR_CONTRAST)

    arr = np.array(enhanced)
    thresh = _otsu_threshold(arr)
    binary = ((arr > thresh) * 255).astype(np.uint8)

    return Image.fromarray(binary)


def _region_colors(img, x, y, w, h):
    iw, ih = img.size
    x = max(0, x)
    y = max(0, y)
    x2 = min(iw, x + w)
    y2 = min(ih, y + h)
    if x2 <= x or y2 <= y:
        return (0, 0, 0), (255, 255, 255)

    edge_pixels = []
    region = img.crop((x, y, x2, y2))
    arr = np.array(region)
    rh, rw = arr.shape[:2]

    if rh >= 2 and rw >= 2:
        edge_pixels.append(arr[0, :])
        edge_pixels.append(arr[-1, :])
        edge_pixels.append(arr[:, 0])
        edge_pixels.append(arr[:, -1])
        edges = np.concatenate(edge_pixels, axis=0)
        bg = tuple(np.median(edges, axis=0).astype(int)[:3])
    else:
        bg = tuple(arr.mean(axis=(0, 1)).astype(int)[:3])

    center = arr[rh // 4 : rh * 3 // 4, rw // 4 : rw * 3 // 4]
    if center.size > 0:
        flat = center.reshape(-1, 3)
        bg_arr = np.array(bg)
        dists = np.linalg.norm(flat.astype(float) - bg_arr.astype(float), axis=1)
        far_mask = dists > 30
        if far_mask.sum() > 10:
            far_pixels = flat[far_mask]
            far_dists = dists[far_mask]
            top_n = max(1, len(far_dists) // 5)
            top_indices = np.argsort(far_dists)[-top_n:]
            fg = tuple(np.median(far_pixels[top_indices], axis=0).astype(int)[:3])
        else:
            fg = _text_color_for_bg(bg)
    else:
        fg = _text_color_for_bg(bg)

    return bg, _boost_fg(fg)


def _boost_fg(fg):
    luminance = 0.299 * fg[0] + 0.587 * fg[1] + 0.114 * fg[2]
    if luminance > 128:
        factor = 0.7
    else:
        factor = 1.3
    return tuple(max(0, min(255, int(c * factor))) for c in fg)


def _text_color_for_bg(bg_rgb):
    luminance = 0.299 * bg_rgb[0] + 0.587 * bg_rgb[1] + 0.114 * bg_rgb[2]
    return (30, 30, 30) if luminance > 128 else (230, 230, 230)


def _first_word(text):
    words = text.split()
    return words[0] if words else ""


_SENTENCE_ENDINGS = set("。.!?！？;；:：」』)）】》…")


_BULLET_RE = re.compile(r'^[•‣⁃◦▪○–—・･·•·\-\*]\s')

_DOT_LEADER_RE = re.compile(r'[.\s]*\.{4,}[.\s]*')
_OCR_NOISE_RE = re.compile(r'(?:\b[ceo]{1,3}\b[\s,]*){5,}')
_TRAILING_NOISE_RE = re.compile(r'\s+[ceo.\s]{10,}\s*\d*\s*$')
_DOT_CHARS = set('.·•‥…・･。｡●○◯◦⋅∙⠂⠄')
_REPEATED_CHAR_RE = re.compile(r'(.)\1{3,}')


def _is_repetitive_word(word):
    """True if the word is a single character repeated (e.g. ・・・・, cccc, eeee)."""
    s = word.strip()
    if len(s) < 3:
        return False
    if all(c in _DOT_CHARS for c in s):
        return True
    if len(set(s)) <= 2 and len(s) >= 4:
        return True
    if _REPEATED_CHAR_RE.search(s):
        return True
    return False


def _is_repetitive_line(line):
    """True if the line is mostly repetitive or dot-leader characters."""
    stripped = line.strip()
    if not stripped:
        return False
    if len(stripped) >= 4 and len(set(stripped.replace(' ', ''))) <= 2:
        return True
    dot_count = sum(1 for c in stripped if c in _DOT_CHARS or c.isspace())
    if dot_count >= len(stripped) * 0.7:
        return True
    words = stripped.split()
    if words and all(_is_repetitive_word(w) for w in words):
        return True
    return False


def _clean_dot_leaders(text):
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        if _is_repetitive_line(line):
            continue
        line = _DOT_LEADER_RE.sub(' ', line)
        line = _OCR_NOISE_RE.sub(' ', line)
        line = _TRAILING_NOISE_RE.sub('', line)
        words = line.split()
        words = [w for w in words if not _is_repetitive_word(w)]
        line = ' '.join(words)
        cleaned.append(line)
    text = '\n'.join(cleaned)
    text = re.sub(r'\s{2,}', ' ', text).strip()
    return text


# Table-of-contents line: <heading> <dot-leader or wide gap> <page number>
_TOC_PAGE_RE = re.compile(
    r'^(.*?\S)'                          # 1: heading (ends in non-space)
    r'(?:'
        r'\s*(?:[.·•‥…]\s*){2,}'      # space-separated dot leader (2+ dots)
        r'|\s{2,}'                        # OR a wide gap
    r')'
    r'[.·•‥…\s]*'                  # trailing leader remnants
    r'(\d{1,4})\s*$'                     # 2: page number
)
# OCR garbage remnants left on a heading tail (e.g. "Structure. cece eee")
_TOC_TAIL_NOISE_RE = re.compile(r'[\s.]*(?:\b[ceo]{1,3}\b[\s.]*){2,}$', re.IGNORECASE)


def _parse_toc_lines(lines):
    """Detect a table-of-contents block from raw OCR lines.

    Returns a list of (heading, page_number_or_None) tuples if the lines look
    like a TOC, otherwise None. Page numbers and dot leaders are stripped from
    the heading so only the heading is sent for translation.
    """
    clean = [l.strip() for l in lines if l.strip()]
    if len(clean) < 3:
        return None
    entries = []
    matched = 0
    for ln in clean:
        m = _TOC_PAGE_RE.match(ln)
        if m:
            heading = m.group(1).strip()
            heading = _TOC_TAIL_NOISE_RE.sub('', heading).strip()
            heading = heading.rstrip('.').strip()
            if heading:
                entries.append((heading, m.group(2)))
                matched += 1
                continue
        entries.append((ln, None))
    if matched >= 3 and matched >= 0.6 * len(clean):
        return entries
    return None



def _is_bullet_line(text):
    if _BULLET_RE.match(text):
        return True
    if re.match(r'^\d+[\.\)]\s', text):
        return True
    return False


def _join_hard_wraps(text):
    raw_lines = text.split("\n")
    paragraphs = []
    current = []

    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if _is_bullet_line(stripped):
            if current:
                paragraphs.append(" ".join(current))
            current = [stripped]
            continue
        if current:
            prev = current[-1]
            if prev and prev[-1] in _SENTENCE_ENDINGS:
                paragraphs.append(" ".join(current))
                current = [stripped]
            else:
                current.append(stripped)
        else:
            current.append(stripped)

    if current:
        paragraphs.append(" ".join(current))

    return "\n".join(paragraphs)


# ---------------------------------------------------------------------------
# GUI components
# ---------------------------------------------------------------------------

class CaptureFrame(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-transparentcolor", "#010101")
        self.configure(bg="#010101")
        self.geometry("500x300+200+200")

        self._drag_data = {"x": 0, "y": 0}
        self._resize_data = {"x": 0, "y": 0, "w": 0, "h": 0}
        self._zone = "none"
        self._on_move = None

        self.canvas = tk.Canvas(self, bg="#010101", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<Configure>", self._draw_border)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

    def set_on_move(self, cb):
        self._on_move = cb

    def _draw_border(self, event=None):
        self.canvas.delete("border")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        b = BORDER_WIDTH
        self.canvas.create_rectangle(
            0, 0, w, h, outline="#888888", width=b, tags="border",
        )
        grip_size = b + 4
        self.canvas.create_rectangle(
            w - grip_size, h - grip_size, w, h,
            fill="#666666", outline="#666666", tags="border",
        )
        self.canvas.create_rectangle(
            0, 0, grip_size, grip_size,
            fill="#666666", outline="#666666", tags="border",
        )

    def _hit_zone(self, x, y):
        w = self.winfo_width()
        h = self.winfo_height()
        grip = BORDER_WIDTH + 4
        if x >= w - grip and y >= h - grip:
            return "resize_br"
        if x <= grip and y <= grip:
            return "resize_tl"
        return "drag"

    def _on_press(self, event):
        zone = self._hit_zone(event.x, event.y)
        self._zone = zone
        if zone == "drag":
            self._drag_data["x"] = event.x_root - self.winfo_x()
            self._drag_data["y"] = event.y_root - self.winfo_y()
        elif zone in ("resize_br", "resize_tl"):
            self._resize_data["x"] = event.x_root
            self._resize_data["y"] = event.y_root
            self._resize_data["w"] = self.winfo_width()
            self._resize_data["h"] = self.winfo_height()
            self._resize_data["win_x"] = self.winfo_x()
            self._resize_data["win_y"] = self.winfo_y()

    def _on_motion(self, event):
        if self._zone == "drag":
            x = event.x_root - self._drag_data["x"]
            y = event.y_root - self._drag_data["y"]
            self.geometry(f"+{x}+{y}")
            if self._on_move:
                self._on_move()
        elif self._zone == "resize_br":
            dx = event.x_root - self._resize_data["x"]
            dy = event.y_root - self._resize_data["y"]
            new_w = max(MIN_FRAME_SIZE, self._resize_data["w"] + dx)
            new_h = max(MIN_FRAME_SIZE, self._resize_data["h"] + dy)
            self.geometry(f"{new_w}x{new_h}")
            if self._on_move:
                self._on_move()
        elif self._zone == "resize_tl":
            dx = event.x_root - self._resize_data["x"]
            dy = event.y_root - self._resize_data["y"]
            new_w = max(MIN_FRAME_SIZE, self._resize_data["w"] - dx)
            new_h = max(MIN_FRAME_SIZE, self._resize_data["h"] - dy)
            new_x = self._resize_data["win_x"] + (self._resize_data["w"] - new_w)
            new_y = self._resize_data["win_y"] + (self._resize_data["h"] - new_h)
            self.geometry(f"{new_w}x{new_h}+{new_x}+{new_y}")
            if self._on_move:
                self._on_move()

    def _on_release(self, event):
        self._zone = "none"

    def get_inner_region(self):
        self.update_idletasks()
        b = BORDER_WIDTH
        return {
            "left": self.winfo_x() + b,
            "top": self.winfo_y() + b,
            "width": max(1, self.winfo_width() - b * 2),
            "height": max(1, self.winfo_height() - b * 2),
        }


class TranslationOverlay(tk.Toplevel):
    def __init__(self, master, on_click=None):
        super().__init__(master)
        self.overrideredirect(True)
        self.configure(bg="#FFFFFF")

        self._on_click = on_click
        self._photo = None
        self._visible = False

        self.label = tk.Label(self, borderwidth=0, highlightthickness=0)
        self.label.pack(fill=tk.BOTH, expand=True)
        self.label.bind("<ButtonPress-1>", self._handle_click)

        self.withdraw()

    def _handle_click(self, event):
        self.hide()
        if self._on_click:
            self._on_click()

    def show_at(self, x, y, w, h, pil_image):
        self._photo = ImageTk.PhotoImage(pil_image)
        self.label.config(image=self._photo, width=w, height=h)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.update_idletasks()
        self.deiconify()
        self.attributes("-topmost", True)
        self.lift()
        self.focus_force()
        self._visible = True

    def hide(self):
        if self._visible:
            self.withdraw()
            self._visible = False

    @property
    def is_visible(self):
        return self._visible


class Toolbar(tk.Toplevel):
    def __init__(self, master, on_toggle=None, on_translate=None):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#444444")

        self._on_toggle = on_toggle
        self._on_translate = on_translate

        f = tk.Frame(self, bg="#444444")
        f.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        self.lang_var = tk.StringVar(value="日本語")
        lang_combo = ttk.Combobox(
            f, textvariable=self.lang_var,
            values=list(LANG_OPTIONS.keys()), state="readonly", width=8,
            font=("", 8),
        )
        lang_combo.pack(side=tk.LEFT, padx=1)

        self.fontsize_var = tk.StringVar(value="100")
        self.fontsize_var.trace_add("write", self._on_fontsize_change)
        fontsize_spin = tk.Spinbox(
            f, from_=50, to=200, increment=10, textvariable=self.fontsize_var,
            width=4, font=("", 8), bg="#555555", fg="white",
            buttonbackground="#666666",
        )
        fontsize_spin.pack(side=tk.LEFT, padx=1)
        tk.Label(f, text="%", font=("", 7), bg="#444444", fg="#AAAAAA").pack(
            side=tk.LEFT)

        self._on_fontsize = None

        self.toggle_btn = tk.Button(
            f, text="Start", command=self._do_toggle,
            font=("", 8), bg="#228B22", fg="white",
            activebackground="#1a6b1a", activeforeground="white",
            relief=tk.FLAT, padx=6, pady=0,
        )
        self.toggle_btn.pack(side=tk.LEFT, padx=1)

        self.translate_btn = tk.Button(
            f, text="Translate", command=self._do_translate,
            font=("", 8), bg="#4169E1", fg="white",
            activebackground="#3155b8", activeforeground="white",
            relief=tk.FLAT, padx=6, pady=0, state=tk.DISABLED,
        )
        self.translate_btn.pack(side=tk.LEFT, padx=1)

        self.close_btn = tk.Button(
            f, text="X", command=master.destroy,
            font=("", 8, "bold"), bg="#CC3333", fg="white",
            activebackground="#aa2222", activeforeground="white",
            relief=tk.FLAT, padx=4, pady=0,
        )
        self.close_btn.pack(side=tk.LEFT, padx=1)

    def _on_fontsize_change(self, *args):
        if self._on_fontsize:
            try:
                int(self.fontsize_var.get())
                self._on_fontsize()
            except ValueError:
                pass

    def _do_toggle(self):
        if self._on_toggle:
            self._on_toggle()

    def _do_translate(self):
        if self._on_translate:
            self._on_translate()

    def set_running(self, running):
        if running:
            self.toggle_btn.config(text="Stop", bg="#CC3333",
                                   activebackground="#aa2222")
            self.translate_btn.config(state=tk.NORMAL)
        else:
            self.toggle_btn.config(text="Start", bg="#228B22",
                                   activebackground="#1a6b1a")
            self.translate_btn.config(state=tk.DISABLED)

    def position_at(self, frame_x, frame_y, frame_w):
        self.update_idletasks()
        tw = self.winfo_reqwidth()
        x = frame_x + frame_w - tw
        y = frame_y - TOOLBAR_HEIGHT - 2
        self.geometry(f"+{x}+{y}")


def _extract_text_blocks(ocr_img, scale=1.0, dump_ocr=False):
    tess_config = f"--oem {TESS_OEM} --psm {TESS_PSM}"
    data = pytesseract.image_to_data(
        ocr_img, lang=TESS_LANG, config=tess_config,
        output_type=pytesseract.Output.DICT,
    )

    if dump_ocr:
        dump_path = os.path.join(
            os.path.expanduser("~"), "Desktop", "ocr_dump.txt"
        )
        with open(dump_path, "w", encoding="utf-8") as f:
            f.write("=== RAW OCR DATA ===\n")
            n = len(data["text"])
            for i in range(n):
                txt = data["text"][i]
                conf = int(data["conf"][i])
                blk = data["block_num"][i]
                ln = data["line_num"][i]
                if conf < 0 or not txt.strip():
                    continue
                chars = ' '.join(f'U+{ord(c):04X}' for c in txt.strip())
                skip = _is_repetitive_word(txt.strip())
                f.write(
                    f"blk={blk} ln={ln} conf={conf:3d} "
                    f"skip={skip} "
                    f"text={repr(txt.strip()):30s} "
                    f"unicode=[{chars}]\n"
                )
            f.write("\n=== END ===\n")
        print(f"[DEBUG] OCR dump saved to: {dump_path}")
    blocks = {}
    n = len(data["text"])
    for i in range(n):
        conf = int(data["conf"][i])
        text = data["text"][i].strip()
        if conf < 0 or not text:
            continue
        if _is_repetitive_word(text):
            continue
        block_id = data["block_num"][i]
        if block_id not in blocks:
            blocks[block_id] = {
                "x": data["left"][i],
                "y": data["top"][i],
                "x2": data["left"][i] + data["width"][i],
                "y2": data["top"][i] + data["height"][i],
                "words": [],
                "lines": {},
                "word_heights": [],
                "confs": [],
            }
        b = blocks[block_id]
        b["x"] = min(b["x"], data["left"][i])
        b["y"] = min(b["y"], data["top"][i])
        b["x2"] = max(b["x2"], data["left"][i] + data["width"][i])
        b["y2"] = max(b["y2"], data["top"][i] + data["height"][i])
        b["words"].append(text)
        b["word_heights"].append(data["height"][i])
        b["confs"].append(conf)
        line_id = data["line_num"][i]
        if line_id not in b["lines"]:
            b["lines"][line_id] = []
        b["lines"][line_id].append(text)

    inv_scale = 1.0 / scale

    result = []
    for bid in sorted(blocks.keys()):
        b = blocks[bid]
        line_texts = [
            " ".join(words)
            for _, words in sorted(b["lines"].items())
        ]
        toc_entries = _parse_toc_lines(line_texts)
        if toc_entries:
            full_text = "\n".join(h for h, _ in toc_entries)
        else:
            full_text = _join_hard_wraps("\n".join(line_texts))
            full_text = _clean_dot_leaders(full_text)
        if not full_text.strip():
            continue
        avg_h = int(np.median(b["word_heights"])) if b["word_heights"] else 16
        median_conf = int(np.median(b["confs"])) if b["confs"] else 0
        word_count = len(b["words"])
        text_len = len(full_text.strip())
        if word_count <= 2 and median_conf < CONF_THRESHOLD:
            continue
        if text_len < 3:
            continue
        pad_x = 6
        pad_y = 4
        raw_x = b["x"]
        raw_y = b["y"]
        raw_w = b["x2"] - b["x"]
        raw_h = b["y2"] - b["y"]
        result.append({
            "x": max(0, int(raw_x * inv_scale) - pad_x),
            "y": max(0, int(raw_y * inv_scale) - pad_y),
            "w": int(raw_w * inv_scale) + pad_x * 2,
            "h": int(raw_h * inv_scale) + pad_y * 2,
            "text": full_text,
            "median_char_h": int(avg_h * inv_scale),
            "median_conf": median_conf,
            "is_toc": bool(toc_entries),
            "toc_pages": [p for _, p in toc_entries] if toc_entries else None,
        })
    return result


_NUMERIC_RE = re.compile(
    r'[\$€¥£]?\s?\d[\d,\.]*\s?(?:' +
    '|'.join(re.escape(u) for u in NUMERIC_UNITS) +
    r')?\b'
    r'|\b(?:19|20)\d{2}\b'
    r'|\d+(?:\.\d+)?%',
    re.IGNORECASE,
)


def _protect_numerics(text):
    placeholders = {}
    counter = [0]
    def _replace(m):
        key = f"〔NUM_{counter[0]:02d}〕"
        placeholders[key] = m.group(0)
        counter[0] += 1
        return key
    protected = _NUMERIC_RE.sub(_replace, text)
    return protected, placeholders


def _restore_numerics(text, placeholders):
    for key, val in placeholders.items():
        text = text.replace(key, val)
    return text


def _is_chart_block(block, img):
    if not ENABLE_CHART_DETECTION:
        return False
    x, y, w, h = block["x"], block["y"], block["w"], block["h"]
    iw, ih = img.size
    crop = img.crop((max(0, x), max(0, y), min(iw, x + w), min(ih, y + h)))
    arr = np.array(crop)
    if arr.size == 0:
        return False
    unique_colors = len(np.unique(arr.reshape(-1, 3), axis=0))
    color_ratio = unique_colors / max(1, arr.shape[0] * arr.shape[1])
    has_many_numbers = sum(1 for w in block["text"].split() if re.match(r'[\$€¥£]?\d', w))
    total_words = max(1, len(block["text"].split()))
    number_ratio = has_many_numbers / total_words
    if number_ratio > 0.5:
        return True
    if color_ratio < 0.05 and block["median_char_h"] < 18:
        return True
    return False


def _wrap_text(text, font, max_w, draw):
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current_line = ""
        for char in paragraph:
            test = current_line + char
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] > max_w and current_line:
                lines.append(current_line)
                current_line = char
            else:
                current_line = test
        if current_line:
            lines.append(current_line)
    return lines


def _clamp_blocks(blocks):
    sorted_blocks = sorted(blocks, key=lambda b: (b["y"], b["x"]))
    for i, b in enumerate(sorted_blocks):
        b_bottom = b["y"] + b["h"]
        for j in range(i + 1, len(sorted_blocks)):
            other = sorted_blocks[j]
            if other["y"] < b_bottom and _blocks_overlap_x(b, other):
                b["h"] = max(1, other["y"] - b["y"])
                break
    return sorted_blocks


def _blocks_overlap_x(a, b):
    return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]


def _calc_wrapped_height(wrapped, font, fs, draw, line_spacing_px):
    total = 0
    for line in wrapped:
        if not line:
            total += fs // 2
        else:
            bbox = draw.textbbox((0, 0), line, font=font)
            total += bbox[3] - bbox[1] + line_spacing_px
    return total


def _calc_font_size(block, scale_pct):
    orig_char_h = block.get("median_char_h", 0)
    if orig_char_h >= MIN_FONT_PX:
        fs = int(orig_char_h * scale_pct / 100)
    else:
        fs = int(16 * scale_pct / 100)
    return max(MIN_FONT_PX, min(fs, MAX_FONT_PX))


def _expand_blocks(blocks, translations, img_h, scale_pct):
    sorted_blocks = sorted(blocks, key=lambda b: (b["y"], b["x"]))
    block_map = {id(b): i for i, b in enumerate(blocks)}

    dummy_img = Image.new("RGB", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)

    for i, b in enumerate(sorted_blocks):
        orig_idx = block_map.get(id(b))
        if orig_idx is None:
            continue
        if b.get("is_toc"):
            continue
        translated = translations[orig_idx]
        pad = BOX_PADDING_PX
        inner_w = max(1, b["w"] - pad * 2)

        b.setdefault("_orig_h", b["h"])
        b["h"] = b["_orig_h"]

        fs = _calc_font_size(b, scale_pct)
        line_spacing_px = max(1, int(fs * (LINE_SPACING_RATIO - 1.0)))
        font = _find_system_font(fs)
        wrapped = _wrap_text(translated, font, inner_w, dummy_draw)
        needed_h = _calc_wrapped_height(wrapped, font, fs, dummy_draw, line_spacing_px)
        needed_h += pad * 2

        if needed_h <= b["h"]:
            continue

        max_bottom = img_h
        for j in range(i + 1, len(sorted_blocks)):
            other = sorted_blocks[j]
            if _blocks_overlap_x(b, other):
                max_bottom = other["y"]
                break

        b["h"] = min(needed_h, max_bottom - b["y"])

    return blocks


def _render_toc_block(draw, block, translated, x, y, w, h, pad, fg_color, scale_pct):
    """Render a table-of-contents block: heading (left) + dot leader + page (right).

    The translated text is the headings joined by newlines, paired with the
    original page numbers stored in block["toc_pages"]. Falls back to plain
    wrapped rendering if the line counts don't line up.
    """
    headings = translated.split("\n")
    pages = block["toc_pages"]
    if len(headings) != len(pages):
        # Translation didn't preserve line structure; render headings only.
        pages = pages + [None] * (len(headings) - len(pages))
        pages = pages[:len(headings)]

    inner_w = max(1, w - pad * 2)
    inner_h = max(1, h - pad * 2)
    n = max(1, len(headings))

    fs = _calc_font_size(block, scale_pct)
    font = _find_system_font(fs)
    # Shrink so all entries fit vertically.
    while fs > MIN_FONT_PX:
        line_h = int(fs * LINE_SPACING_RATIO)
        if line_h * n <= inner_h:
            break
        fs -= 1
        font = _find_system_font(fs)
    line_h = max(fs + 1, int(fs * LINE_SPACING_RATIO))

    dot_w = max(1, draw.textlength(". ", font=font))

    dy = y + pad
    for heading, page in zip(headings, pages):
        if dy + line_h > y + h:
            break
        heading = heading.strip()
        if page is None:
            draw.text((x + pad, dy), heading, fill=fg_color, font=font)
            dy += line_h
            continue
        page_str = str(page)
        page_w = draw.textlength(page_str, font=font)
        head_max = max(dot_w, inner_w - page_w - dot_w * 2)
        # Trim heading if it would collide with the page number.
        while heading and draw.textlength(heading, font=font) > head_max:
            heading = heading[:-1]
        head_w = draw.textlength(heading, font=font)
        draw.text((x + pad, dy), heading, fill=fg_color, font=font)
        # Page number, right-aligned.
        draw.text((x + w - pad - page_w, dy), page_str, fill=fg_color, font=font)
        # Dot leader filling the gap.
        leader_start = x + pad + head_w + dot_w
        leader_end = x + w - pad - page_w - dot_w
        n_dots = int((leader_end - leader_start) / dot_w)
        if n_dots > 0:
            draw.text((leader_start, dy), ". " * n_dots, fill=fg_color, font=font)
        dy += line_h


def _render_inplace(base_img, blocks, translations, scale_pct):
    img = base_img.copy()
    draw = ImageDraw.Draw(img)

    img_h = base_img.size[1]
    _expand_blocks(blocks, translations, img_h, scale_pct)

    clamped = _clamp_blocks(blocks)

    block_map = {id(b): i for i, b in enumerate(blocks)}
    translation_order = []
    for b in clamped:
        orig_idx = block_map.get(id(b))
        if orig_idx is not None:
            translation_order.append((b, translations[orig_idx]))

    for block, translated in translation_order:
        x, y, w, h = block["x"], block["y"], block["w"], block["h"]
        is_chart = block.get("is_chart", False)
        bg_color, fg_color = _region_colors(base_img, x, y, w, h)

        pad = BOX_PADDING_PX
        draw.rectangle([x, y, x + w, y + h], fill=bg_color)

        if block.get("is_toc") and block.get("toc_pages"):
            _render_toc_block(
                draw, block, translated, x, y, w, h,
                pad, fg_color, scale_pct,
            )
            continue

        inner_w = max(1, w - pad * 2)
        inner_h = max(1, h - pad * 2)

        fs = _calc_font_size(block, scale_pct)
        line_spacing_px = max(1, int(fs * (LINE_SPACING_RATIO - 1.0)))
        font = _find_system_font(fs)
        wrapped = _wrap_text(translated, font, inner_w, draw)
        total_h = _calc_wrapped_height(wrapped, font, fs, draw, line_spacing_px)

        while total_h > inner_h and fs > MIN_FONT_PX:
            fs -= 1
            line_spacing_px = max(1, int(fs * (LINE_SPACING_RATIO - 1.0)))
            font = _find_system_font(fs)
            wrapped = _wrap_text(translated, font, inner_w, draw)
            total_h = _calc_wrapped_height(wrapped, font, fs, draw, line_spacing_px)

        dy = y + pad
        for line in wrapped:
            if not line:
                dy += fs // 2
                continue
            bbox = draw.textbbox((0, 0), line, font=font)
            line_h = bbox[3] - bbox[1] + line_spacing_px
            if dy + line_h > y + h:
                break
            draw.text((x + pad, dy), line, fill=fg_color, font=font)
            dy += line_h

    return img


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class ScreenTranslator(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()

        api_key = _load_api_key()
        if not api_key:
            api_key = _ask_api_key()
        if not api_key:
            messagebox.showerror(APP_NAME, "DeepL API Key が未設定です。終了します。")
            self.destroy()
            return
        self._engine = DeepLEngine(api_key)

        self.running = False
        self._lock = threading.Lock()
        self._prev_first_word = None
        self._last_render = None

        self.capture_frame = CaptureFrame(self)
        self.overlay = TranslationOverlay(self, on_click=self._on_overlay_click)
        self.toolbar = Toolbar(
            self,
            on_toggle=self._toggle,
            on_translate=self._manual_translate,
        )
        self.toolbar._on_fontsize = self._on_fontsize_change

        self.capture_frame.set_on_move(self._reposition_toolbar)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.bind_all("<Control-x>", self._hotkey_translate)
        self.bind_all("<Control-d>", self._hotkey_dump_ocr)

        self.after(100, self._reposition_toolbar)

    def _reposition_toolbar(self):
        self.capture_frame.update_idletasks()
        fx = self.capture_frame.winfo_x()
        fy = self.capture_frame.winfo_y()
        fw = self.capture_frame.winfo_width()
        self.toolbar.position_at(fx, fy, fw)

    # --- Start / Stop ---

    def _toggle(self):
        if self.running:
            self.running = False
            self.toolbar.set_running(False)
            self.overlay.hide()
            self._prev_first_word = None
        else:
            self.running = True
            self._prev_first_word = None
            self.toolbar.set_running(True)
            self._poll()

    def _poll(self):
        if not self.running:
            return
        if not self.overlay.is_visible:
            threading.Thread(
                target=self._scan_and_translate, daemon=True,
            ).start()
        self.after(2000, self._poll)

    def _manual_translate(self):
        if not self.running:
            return
        self.overlay.hide()
        self._prev_first_word = None
        threading.Thread(
            target=self._scan_and_translate, daemon=True,
        ).start()

    def _hotkey_translate(self, event=None):
        self.overlay.hide()
        self._prev_first_word = None
        threading.Thread(
            target=self._scan_and_translate, daemon=True,
        ).start()

    def _hotkey_dump_ocr(self, event=None):
        threading.Thread(target=self._dump_ocr, daemon=True).start()

    def _dump_ocr(self):
        try:
            region = self.capture_frame.get_inner_region()
            with mss.mss() as sct:
                screenshot = sct.grab(region)
            img = Image.frombytes(
                "RGB", screenshot.size, screenshot.bgra, "raw", "BGRX",
            )
            ocr_img = _preprocess_for_ocr(img)
            _extract_text_blocks(ocr_img, scale=OCR_UPSCALE, dump_ocr=True)
            self.after(0, lambda: messagebox.showinfo(
                APP_NAME,
                "OCRデータをデスクトップの ocr_dump.txt に保存しました。"
            ))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror(APP_NAME, str(e)))

    def _on_overlay_click(self):
        self._prev_first_word = None

    def _on_fontsize_change(self):
        if self._last_render and self.overlay.is_visible:
            lr = self._last_render
            scale_pct = int(self.toolbar.fontsize_var.get())
            result_img = _render_inplace(
                lr["img"], lr["blocks"], lr["translations"], scale_pct,
            )
            self.overlay.show_at(
                lr["x"], lr["y"], lr["w"], lr["h"], result_img,
            )

    # --- Core translation ---

    def _scan_and_translate(self):
        if not self._lock.acquire(blocking=False):
            return
        try:
            region = self.capture_frame.get_inner_region()
            with mss.mss() as sct:
                screenshot = sct.grab(region)
            img = Image.frombytes(
                "RGB", screenshot.size, screenshot.bgra, "raw", "BGRX",
            )

            ocr_img = _preprocess_for_ocr(img)
            blocks = _extract_text_blocks(ocr_img, scale=OCR_UPSCALE)

            blocks = self._refine_low_conf_blocks(blocks, img)

            if not blocks:
                self._prev_first_word = None
                return

            all_text = " ".join(b["text"] for b in blocks)
            current_first = _first_word(all_text)

            if (self._prev_first_word is not None
                    and current_first == self._prev_first_word):
                return

            for b in blocks:
                b["is_chart"] = _is_chart_block(b, img)

            target_code = LANG_OPTIONS.get(
                self.toolbar.lang_var.get(), "en",
            )

            block_texts = []
            placeholder_maps = []
            for b in blocks:
                text = b["text"]
                if PROTECT_NUMERIC:
                    text, pmap = _protect_numerics(text)
                else:
                    pmap = {}
                block_texts.append(text)
                placeholder_maps.append(pmap)

            if len(block_texts) == 1:
                t, _ = self._engine.translate(block_texts[0], target_code)
                translations = [t]
            else:
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=4,
                ) as pool:
                    futures = [
                        pool.submit(self._engine.translate, bt, target_code)
                        for bt in block_texts
                    ]
                    translations = [f.result()[0] for f in futures]

            if PROTECT_NUMERIC:
                translations = [
                    _restore_numerics(t, pm)
                    for t, pm in zip(translations, placeholder_maps)
                ]

            self._prev_first_word = current_first

            scale_pct = int(self.toolbar.fontsize_var.get())
            w, h = region["width"], region["height"]
            rx, ry = region["left"], region["top"]
            result_img = _render_inplace(img, blocks, translations, scale_pct)

            self._last_render = {
                "img": img, "blocks": blocks,
                "translations": translations,
                "x": rx, "y": ry, "w": w, "h": h,
            }

            self.after(
                0,
                self.overlay.show_at,
                rx, ry, w, h, result_img,
            )
        except Exception as e:
            traceback.print_exc()
        finally:
            self._lock.release()

    def _refine_low_conf_blocks(self, blocks, original_img):
        try:
            from local_ocr import is_available, local_ocr_image
            if not is_available():
                return blocks
        except ImportError:
            return blocks

        candidates = []
        for i, b in enumerate(blocks):
            needs_reocr = (
                b["median_conf"] < CONF_THRESHOLD
                or b["median_char_h"] < SMALL_CHAR_PX
            )
            if needs_reocr:
                candidates.append((i, b["median_conf"]))

        candidates.sort(key=lambda x: x[1])
        candidates = candidates[:MAX_LLM_BLOCKS]

        for idx, _ in candidates:
            b = blocks[idx]
            x, y, w, h = b["x"], b["y"], b["w"], b["h"]
            iw, ih = original_img.size
            crop_box = (
                max(0, x), max(0, y),
                min(iw, x + w), min(ih, y + h),
            )
            crop = original_img.crop(crop_box)
            result = local_ocr_image(crop)
            if result:
                blocks[idx]["text"] = result

        return blocks

    def _on_close(self):
        self.running = False
        self.overlay.destroy()
        self.capture_frame.destroy()
        self.toolbar.destroy()
        self.destroy()


def _run_diagnostics():
    lines = []
    lines.append(f"Screen Translator v{APP_VERSION}")
    lines.append(f"Python: {sys.version.split()[0]}")
    lines.append("")

    # Tesseract
    tess_ok = _setup_tesseract()
    if tess_ok:
        try:
            ver = pytesseract.get_tesseract_version()
            lines.append(f"[OK] Tesseract OCR: {ver}")
        except Exception:
            lines.append("[OK] Tesseract OCR: found")
    else:
        lines.append("[NG] Tesseract OCR: NOT FOUND")

    # Japanese data
    tess_cmd = getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract")
    tess_dir = os.path.dirname(tess_cmd)
    jpn_path = os.path.join(tess_dir, "tessdata", "jpn.traineddata")
    if os.path.exists(jpn_path):
        lines.append("[OK] Japanese OCR data: found")
    else:
        lines.append("[NG] Japanese OCR data: NOT FOUND")

    # Core packages
    lines.append(f"[OK] Pillow: {Image.__version__}")
    lines.append(f"[OK] numpy: {np.__version__}")

    # Font
    test_font = _find_system_font(16)
    font_name = getattr(test_font, "path", str(test_font)) if hasattr(test_font, "path") else "default"
    lines.append(f"[OK] Font: {os.path.basename(font_name)}")

    # VLM
    try:
        from local_ocr import is_available
        if is_available():
            import torch
            gpu = "GPU" if torch.cuda.is_available() else "CPU"
            lines.append(f"[OK] VLM re-OCR: enabled ({gpu})")
        else:
            lines.append("[--] VLM re-OCR: disabled (torch not installed)")
    except ImportError:
        lines.append("[--] VLM re-OCR: disabled (local_ocr.py not found)")

    # DeepL
    api_key = _load_api_key()
    if api_key:
        key_type = "Free" if api_key.endswith(":fx") else "Pro"
        lines.append(f"[OK] DeepL API Key: set ({key_type})")
    else:
        lines.append("[--] DeepL API Key: not set (will ask on launch)")

    return "\n".join(lines)


def main():
    if "--diag" in sys.argv:
        root = tk.Tk()
        root.withdraw()
        info = _run_diagnostics()
        messagebox.showinfo(f"{APP_NAME} - Diagnostics", info)
        root.destroy()
        return

    if not _setup_tesseract():
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            APP_NAME,
            "Tesseract OCR is not installed.\n\n"
            "Please install from:\n"
            "https://github.com/UB-Mannheim/tesseract/wiki",
        )
        root.destroy()
        return

    app = ScreenTranslator()
    app.mainloop()


if __name__ == "__main__":
    main()

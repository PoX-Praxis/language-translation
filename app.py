"""
Screen Translation Overlay App
- Captures text within a movable/resizable overlay frame
- Control toolbar attached to top-right of the frame
- Uses DeepL API for high-quality translation
- Auto-translates when text changes; click overlay to dismiss
"""

import concurrent.futures
import json
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk
import traceback
import urllib.request
import urllib.error
import urllib.parse

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk
import mss
import pytesseract

if sys.platform == "win32":
    _default_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(_default_path):
        pytesseract.pytesseract.tesseract_cmd = _default_path

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

LANG_NAMES_NATIVE = {v: k for k, v in LANG_OPTIONS.items()}

BORDER_WIDTH = 14
MIN_FRAME_SIZE = BORDER_WIDTH * 4
TOOLBAR_HEIGHT = 28

DEFAULT_DEEPL_KEY = "d4ba5dbe-ef4e-4735-bca2-3268722e0ecb:fx"

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

    def translate(self, text, target_code):
        if not self.api_key:
            raise RuntimeError("DeepL API key is not set")
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
        return tr["text"], tr.get("detected_source_language", "auto").lower()


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


def _dominant_color(img):
    arr = np.array(img.resize((50, 50)))
    avg = arr.mean(axis=(0, 1)).astype(int)
    return tuple(avg[:3])


def _text_color_for_bg(bg_rgb):
    luminance = 0.299 * bg_rgb[0] + 0.587 * bg_rgb[1] + 0.114 * bg_rgb[2]
    return (30, 30, 30) if luminance > 128 else (230, 230, 230)


def _first_word(text):
    words = text.split()
    return words[0] if words else ""


_SENTENCE_ENDINGS = set("。.!?！？;；:：」』)）】》…")


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

    def _hit_zone(self, x, y):
        w = self.winfo_width()
        h = self.winfo_height()
        grip = BORDER_WIDTH + 4
        if x >= w - grip and y >= h - grip:
            return "resize"
        return "drag"

    def _on_press(self, event):
        zone = self._hit_zone(event.x, event.y)
        self._zone = zone
        if zone == "drag":
            self._drag_data["x"] = event.x_root - self.winfo_x()
            self._drag_data["y"] = event.y_root - self.winfo_y()
        elif zone == "resize":
            self._resize_data["x"] = event.x_root
            self._resize_data["y"] = event.y_root
            self._resize_data["w"] = self.winfo_width()
            self._resize_data["h"] = self.winfo_height()

    def _on_motion(self, event):
        if self._zone == "drag":
            x = event.x_root - self._drag_data["x"]
            y = event.y_root - self._drag_data["y"]
            self.geometry(f"+{x}+{y}")
            if self._on_move:
                self._on_move()
        elif self._zone == "resize":
            dx = event.x_root - self._resize_data["x"]
            dy = event.y_root - self._resize_data["y"]
            new_w = max(MIN_FRAME_SIZE, self._resize_data["w"] + dx)
            new_h = max(MIN_FRAME_SIZE, self._resize_data["h"] + dy)
            self.geometry(f"{new_w}x{new_h}")
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

        self.fontsize_var = tk.StringVar(value="16")
        fontsize_spin = tk.Spinbox(
            f, from_=8, to=48, textvariable=self.fontsize_var,
            width=3, font=("", 8), bg="#555555", fg="white",
            buttonbackground="#666666",
        )
        fontsize_spin.pack(side=tk.LEFT, padx=1)

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


def _render_text_image(w, h, bg_color, fg_color, text, font_size):
    img = Image.new("RGB", (w, h), bg_color)
    draw = ImageDraw.Draw(img)
    font = _find_system_font(font_size)

    margin = 8
    max_w = w - margin * 2
    max_h = h - margin * 2

    wrapped = _wrap_text(text, font, max_w, draw)

    dy = margin
    for line in wrapped:
        if not line:
            dy += font_size // 2
            continue
        bbox = draw.textbbox((0, 0), line, font=font)
        line_h = bbox[3] - bbox[1] + 4
        if dy + line_h > margin + max_h:
            break
        draw.text((margin, dy), line, fill=fg_color, font=font)
        dy += line_h

    return img


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class ScreenTranslator(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()

        self._engine = DeepLEngine(DEFAULT_DEEPL_KEY)

        self.running = False
        self._lock = threading.Lock()
        self._prev_first_word = None
        self._prev_translated = ""
        self._prev_bg_color = (255, 255, 255)

        self.capture_frame = CaptureFrame(self)
        self.overlay = TranslationOverlay(self, on_click=self._on_overlay_click)
        self.toolbar = Toolbar(
            self,
            on_toggle=self._toggle,
            on_translate=self._manual_translate,
        )

        self.capture_frame.set_on_move(self._reposition_toolbar)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

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
        self.after(1000, self._poll)

    def _manual_translate(self):
        if not self.running:
            return
        self.overlay.hide()
        self._prev_first_word = None
        threading.Thread(
            target=self._scan_and_translate, daemon=True,
        ).start()

    def _on_overlay_click(self):
        self._prev_first_word = None

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

            gray = img.convert("L")
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                ocr_future = pool.submit(
                    pytesseract.image_to_string, gray,
                )
                bg_future = pool.submit(_dominant_color, img)

                raw_text = ocr_future.result().strip()
                bg_color = bg_future.result()

            if not raw_text:
                self._prev_first_word = None
                return

            ocr_text = _join_hard_wraps(raw_text)
            current_first = _first_word(ocr_text)

            if (self._prev_first_word is not None
                    and current_first == self._prev_first_word):
                return

            target_code = LANG_OPTIONS.get(
                self.toolbar.lang_var.get(), "en",
            )

            translated, src_lang = self._engine.translate(
                ocr_text, target_code,
            )

            self._prev_first_word = current_first
            self._prev_translated = translated
            self._prev_bg_color = bg_color

            fg_color = _text_color_for_bg(bg_color)
            font_size = int(self.toolbar.fontsize_var.get())
            w, h = region["width"], region["height"]
            text_img = _render_text_image(
                w, h, bg_color, fg_color, translated, font_size,
            )

            self.after(
                0,
                self.overlay.show_at,
                region["left"], region["top"], w, h, text_img,
            )
        except Exception as e:
            traceback.print_exc()
        finally:
            self._lock.release()

    def _on_close(self):
        self.running = False
        self.overlay.destroy()
        self.capture_frame.destroy()
        self.toolbar.destroy()
        self.destroy()


def main():
    app = ScreenTranslator()
    app.mainloop()


if __name__ == "__main__":
    main()

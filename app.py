"""
Screen Translation Overlay App
- Captures text within a movable/resizable overlay frame
- Detects the source language and translates to a selected target language
- Displays translated text directly inside the capture frame
- Auto-translates when text changes; click overlay to dismiss
"""

import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
import traceback

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk
import mss
import pytesseract
from googletrans import Translator, LANGUAGES

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

BORDER_WIDTH = 14
MIN_FRAME_SIZE = BORDER_WIDTH * 4


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


class CaptureFrame(tk.Toplevel):
    """Movable/resizable capture frame with gray border and transparent center."""

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

        self.canvas = tk.Canvas(self, bg="#010101", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<Configure>", self._draw_border)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)

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
        b = BORDER_WIDTH
        grip = b + 4
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
        elif self._zone == "resize":
            dx = event.x_root - self._resize_data["x"]
            dy = event.y_root - self._resize_data["y"]
            new_w = max(MIN_FRAME_SIZE, self._resize_data["w"] + dx)
            new_h = max(MIN_FRAME_SIZE, self._resize_data["h"] + dy)
            self.geometry(f"{new_w}x{new_h}")

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
    """Independent overlay window that shows translated text."""

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


def _render_text_image(w, h, bg_color, fg_color, text, font_size):
    img = Image.new("RGB", (w, h), bg_color)
    draw = ImageDraw.Draw(img)
    font = _find_system_font(font_size)

    margin = 8
    dx, dy = margin, margin
    max_w = w - margin * 2

    for line in text.split("\n"):
        words = line.split()
        current_line = ""
        for word in words:
            test = f"{current_line} {word}".strip()
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] > max_w and current_line:
                draw.text((dx, dy), current_line, fill=fg_color, font=font)
                dy += bbox[3] - bbox[1] + 4
                current_line = word
            else:
                current_line = test
        if current_line:
            bbox = draw.textbbox((0, 0), current_line, font=font)
            draw.text((dx, dy), current_line, fill=fg_color, font=font)
            dy += (bbox[3] - bbox[1]) + 4

    return img


class TranslationApp(tk.Tk):
    """Main control panel for screen translation."""

    def __init__(self):
        super().__init__()
        self.title("Screen Translator")
        self.geometry("420x220")
        self.resizable(False, False)
        self.attributes("-topmost", True)

        self.translator = Translator()
        self.running = False
        self._lock = threading.Lock()
        self._prev_first_word = None
        self._prev_translated = ""
        self._prev_bg_color = (255, 255, 255)

        self._build_ui()

        self.capture_frame = CaptureFrame(self)
        self.overlay = TranslationOverlay(self, on_click=self._on_overlay_click)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        settings_frame = ttk.LabelFrame(self, text="Settings", padding=8)
        settings_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(settings_frame, text="Target Language:").grid(
            row=0, column=0, sticky=tk.W, pady=2,
        )
        self.lang_var = tk.StringVar(value="日本語")
        lang_combo = ttk.Combobox(
            settings_frame, textvariable=self.lang_var,
            values=list(LANG_OPTIONS.keys()), state="readonly", width=18,
        )
        lang_combo.grid(row=0, column=1, padx=5, pady=2)

        ttk.Label(settings_frame, text="Font Size:").grid(
            row=1, column=0, sticky=tk.W, pady=2,
        )
        self.fontsize_var = tk.StringVar(value="16")
        fontsize_spin = ttk.Spinbox(
            settings_frame, from_=8, to=48, textvariable=self.fontsize_var,
            width=5,
        )
        fontsize_spin.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)

        self.toggle_btn = ttk.Button(
            btn_frame, text="▶  Start", command=self._toggle,
        )
        self.toggle_btn.pack(side=tk.LEFT, padx=5)

        self.translate_btn = ttk.Button(
            btn_frame, text="Translate", command=self._manual_translate,
            state=tk.DISABLED,
        )
        self.translate_btn.pack(side=tk.LEFT, padx=5)

        self.status_label = ttk.Label(
            btn_frame, text="Stopped", foreground="gray",
        )
        self.status_label.pack(side=tk.LEFT, padx=10)

        self.info_label = ttk.Label(
            self, text="", foreground="blue", wraplength=400,
        )
        self.info_label.pack(fill=tk.X, padx=10, pady=(0, 5))

    def _set_status(self, text, color="blue"):
        self.after(
            0, lambda t=text, c=color: self.info_label.config(
                text=t, foreground=c,
            ),
        )

    def _toggle(self):
        if self.running:
            self.running = False
            self.toggle_btn.config(text="▶  Start")
            self.translate_btn.config(state=tk.DISABLED)
            self.status_label.config(text="Stopped", foreground="gray")
            self.overlay.hide()
            self._prev_first_word = None
            self._set_status("")
        else:
            self.running = True
            self._prev_first_word = None
            self.toggle_btn.config(text="⏹  Stop")
            self.translate_btn.config(state=tk.NORMAL)
            self.status_label.config(text="Running", foreground="green")
            self._set_status("Scanning...")
            self._poll()

    def _poll(self):
        if not self.running:
            return
        if not self.overlay.is_visible:
            threading.Thread(target=self._scan_and_translate, daemon=True).start()
        self.after(1000, self._poll)

    def _manual_translate(self):
        if not self.running:
            return
        self.overlay.hide()
        self._prev_first_word = None
        self._set_status("Translating...")
        threading.Thread(target=self._scan_and_translate, daemon=True).start()

    def _on_overlay_click(self):
        self._prev_first_word = None
        self._set_status("Dismissed. Rescanning...")

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

            ocr_text = pytesseract.image_to_string(img).strip()
            if not ocr_text:
                self._set_status("No text detected in frame")
                self._prev_first_word = None
                return

            current_first = _first_word(ocr_text)

            if self._prev_first_word is not None and current_first == self._prev_first_word:
                return

            self._set_status(f"Translating: {ocr_text[:50]}...")

            bg_color = _dominant_color(img)
            target_code = LANG_OPTIONS.get(self.lang_var.get(), "en")
            result = self.translator.translate(ocr_text, dest=target_code)
            translated = result.text

            self._prev_first_word = current_first
            self._prev_translated = translated
            self._prev_bg_color = bg_color

            src_lang = LANGUAGES.get(result.src.lower(), result.src)
            self._set_status(
                f"[{src_lang}] → "
                f"[{LANGUAGES.get(target_code, target_code)}]",
            )

            fg_color = _text_color_for_bg(bg_color)
            font_size = int(self.fontsize_var.get())
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
            self._set_status(f"Error: {e}", "red")
            traceback.print_exc()
        finally:
            self._lock.release()

    def _on_close(self):
        self.running = False
        self.overlay.destroy()
        self.capture_frame.destroy()
        self.destroy()


def main():
    app = TranslationApp()
    app.mainloop()


if __name__ == "__main__":
    main()

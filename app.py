"""
Screen Translation Overlay App
- Captures text within a movable/resizable overlay frame
- Detects the source language and translates to a selected target language
- Displays translated text directly inside the capture frame
- Triggers translation when the first detected word changes
"""

import os
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
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
POLL_INTERVAL_MS = 800

TRANSPARENT_COLOR = "#010101"


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
    """Transparent movable/resizable capture frame with gray border."""

    def __init__(self, master, on_move=None):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-transparentcolor", TRANSPARENT_COLOR)
        self.configure(bg=TRANSPARENT_COLOR)
        self.geometry("500x300+200+200")

        self._on_move_cb = on_move
        self._drag_data = {"x": 0, "y": 0}
        self._resize_data = {"x": 0, "y": 0, "w": 0, "h": 0}
        self._zone = "none"

        self.canvas = tk.Canvas(
            self, bg=TRANSPARENT_COLOR, highlightthickness=0,
        )
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
        if x < b or y < b or x >= w - b or y >= h - b:
            return "drag"
        return "none"

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
            if self._on_move_cb:
                self._on_move_cb()
        elif self._zone == "resize":
            dx = event.x_root - self._resize_data["x"]
            dy = event.y_root - self._resize_data["y"]
            new_w = max(MIN_FRAME_SIZE, self._resize_data["w"] + dx)
            new_h = max(MIN_FRAME_SIZE, self._resize_data["h"] + dy)
            self.geometry(f"{new_w}x{new_h}")
            if self._on_move_cb:
                self._on_move_cb()

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
    """Overlay window that shows translated text inside the capture area."""

    def __init__(self, master):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#FFFFFF")

        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self._photo = None
        self._visible = False
        self.withdraw()

    def show_translation(self, region, bg_color, text, font_size=16):
        if not text:
            self.hide()
            return

        w, h = region["width"], region["height"]
        x, y = region["left"], region["top"]

        self.geometry(f"{w}x{h}+{x}+{y}")

        fg_color = _text_color_for_bg(bg_color)

        img = Image.new("RGB", (w, h), bg_color)
        draw = ImageDraw.Draw(img)
        font = _find_system_font(font_size)

        margin = 6
        draw_x, draw_y = margin, margin
        max_w = w - margin * 2

        for line in text.split("\n"):
            words = line.split()
            current_line = ""
            for word in words:
                test = f"{current_line} {word}".strip()
                bbox = draw.textbbox((0, 0), test, font=font)
                if bbox[2] - bbox[0] > max_w and current_line:
                    draw.text(
                        (draw_x, draw_y), current_line,
                        fill=fg_color, font=font,
                    )
                    draw_y += bbox[3] - bbox[1] + 4
                    current_line = word
                else:
                    current_line = test
            if current_line:
                bbox = draw.textbbox((0, 0), current_line, font=font)
                draw.text(
                    (draw_x, draw_y), current_line,
                    fill=fg_color, font=font,
                )
                draw_y += bbox[3] - bbox[1] + 4

        self._photo = ImageTk.PhotoImage(img)
        self.canvas.config(width=w, height=h)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self._photo)
        self.deiconify()
        self.lift()
        self._visible = True

    def hide(self):
        if self._visible:
            self.withdraw()
            self._visible = False

    @property
    def is_visible(self):
        return self._visible


class TranslationApp(tk.Tk):
    """Main control panel for screen translation."""

    def __init__(self):
        super().__init__()
        self.title("Screen Translator")
        self.geometry("400x200")
        self.resizable(False, False)
        self.attributes("-topmost", True)

        self.translator = Translator()
        self.running = False
        self._prev_first_word = ""
        self._overlay_showing = False
        self._lock = threading.Lock()

        self._build_ui()
        self.capture_frame = CaptureFrame(self, on_move=self._on_frame_move)
        self.overlay = TranslationOverlay(self)
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

        self.status_label = ttk.Label(
            btn_frame, text="Stopped", foreground="gray",
        )
        self.status_label.pack(side=tk.LEFT, padx=10)

        self.info_label = ttk.Label(
            self, text="", foreground="blue", wraplength=380,
        )
        self.info_label.pack(fill=tk.X, padx=10, pady=(0, 5))

    def _set_status(self, text, color="blue"):
        self.after(0, lambda: self.info_label.config(text=text, foreground=color))

    def _toggle(self):
        if self.running:
            self.running = False
            self.toggle_btn.config(text="▶  Start")
            self.status_label.config(text="Stopped", foreground="gray")
            self.overlay.hide()
            self._prev_first_word = ""
            self._set_status("")
        else:
            self.running = True
            self._prev_first_word = ""
            self.toggle_btn.config(text="⏹  Stop")
            self.status_label.config(text="Running", foreground="green")
            self._set_status("Scanning...")
            self._schedule_poll()

    def _schedule_poll(self):
        if not self.running:
            return
        threading.Thread(target=self._poll_and_translate, daemon=True).start()
        self.after(POLL_INTERVAL_MS, self._schedule_poll)

    def _poll_and_translate(self):
        if not self._lock.acquire(blocking=False):
            return
        try:
            if self.overlay.is_visible:
                self.after(0, self.overlay.hide)
                time.sleep(0.15)

            region = self.capture_frame.get_inner_region()

            with mss.mss() as sct:
                screenshot = sct.grab(region)
            img = Image.frombytes(
                "RGB", screenshot.size, screenshot.bgra, "raw", "BGRX",
            )

            ocr_text = pytesseract.image_to_string(img).strip()
            if not ocr_text:
                self._set_status("No text detected in frame")
                self._prev_first_word = ""
                return

            current_first = _first_word(ocr_text)
            self._set_status(f"Detected: {ocr_text[:60]}...")

            if current_first == self._prev_first_word:
                if self._prev_translated:
                    font_size = int(self.fontsize_var.get())
                    self.after(
                        0,
                        self.overlay.show_translation,
                        region, self._prev_bg_color,
                        self._prev_translated, font_size,
                    )
                return

            self._prev_first_word = current_first
            self._set_status("Translating...")

            bg_color = _dominant_color(img)
            target_code = LANG_OPTIONS.get(self.lang_var.get(), "en")
            result = self.translator.translate(ocr_text, dest=target_code)
            translated = result.text

            self._prev_translated = translated
            self._prev_bg_color = bg_color

            src_lang = LANGUAGES.get(result.src.lower(), result.src)
            self._set_status(
                f"[{src_lang}] → [{LANGUAGES.get(target_code, target_code)}] OK",
            )

            font_size = int(self.fontsize_var.get())
            self.after(
                0,
                self.overlay.show_translation,
                region, bg_color, translated, font_size,
            )
        except Exception as e:
            self._set_status(f"Error: {e}", "red")
            traceback.print_exc()
        finally:
            self._lock.release()

    def _on_frame_move(self):
        if self.running:
            self.overlay.hide()
            self._prev_first_word = ""

    def _on_close(self):
        self.running = False
        self.overlay.destroy()
        self.capture_frame.destroy()
        self.destroy()


def main():
    app = TranslationApp()
    app._prev_translated = ""
    app._prev_bg_color = (255, 255, 255)
    app.mainloop()


if __name__ == "__main__":
    main()

"""
Screen Translation Overlay App
- Captures text within a movable/resizable overlay frame
- Detects the source language and translates to a selected target language
- Start/stop translation with a button click
"""

import threading
import tkinter as tk
from tkinter import ttk
from io import BytesIO

from PIL import Image
import mss
import pytesseract
from googletrans import Translator, LANGUAGES


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

TESSERACT_LANG_MAP = {
    "ja": "jpn",
    "en": "eng",
    "zh-cn": "chi_sim",
    "ko": "kor",
    "fr": "fra",
    "de": "deu",
    "es": "spa",
    "pt": "por",
    "ru": "rus",
    "ar": "ara",
    "hi": "hin",
    "it": "ita",
    "nl": "nld",
    "tr": "tur",
    "vi": "vie",
    "th": "tha",
}

INTERVAL_MS = 2000
MIN_FRAME_SIZE = 50


class CaptureFrame(tk.Toplevel):
    """Semi-transparent movable and resizable capture frame."""

    def __init__(self, master):
        super().__init__(master)
        self.title("Capture Area")
        self.geometry("400x300+200+200")
        self.attributes("-alpha", 0.3)
        self.attributes("-topmost", True)
        self.configure(bg="blue")
        self.overrideredirect(True)

        self._drag_data = {"x": 0, "y": 0}
        self._resize_data = {"x": 0, "y": 0, "w": 0, "h": 0}

        self.border = tk.Frame(self, bg="blue", cursor="arrow")
        self.border.pack(fill=tk.BOTH, expand=True)

        self.resize_grip = tk.Label(
            self.border, text="◢", bg="blue", fg="white",
            font=("Arial", 14), cursor="bottom_right_corner",
        )
        self.resize_grip.place(relx=1.0, rely=1.0, anchor="se")

        self.border.bind("<ButtonPress-1>", self._on_drag_start)
        self.border.bind("<B1-Motion>", self._on_drag_motion)

        self.resize_grip.bind("<ButtonPress-1>", self._on_resize_start)
        self.resize_grip.bind("<B1-Motion>", self._on_resize_motion)

    def _on_drag_start(self, event):
        self._drag_data["x"] = event.x_root - self.winfo_x()
        self._drag_data["y"] = event.y_root - self.winfo_y()

    def _on_drag_motion(self, event):
        x = event.x_root - self._drag_data["x"]
        y = event.y_root - self._drag_data["y"]
        self.geometry(f"+{x}+{y}")

    def _on_resize_start(self, event):
        self._resize_data["x"] = event.x_root
        self._resize_data["y"] = event.y_root
        self._resize_data["w"] = self.winfo_width()
        self._resize_data["h"] = self.winfo_height()

    def _on_resize_motion(self, event):
        dx = event.x_root - self._resize_data["x"]
        dy = event.y_root - self._resize_data["y"]
        new_w = max(MIN_FRAME_SIZE, self._resize_data["w"] + dx)
        new_h = max(MIN_FRAME_SIZE, self._resize_data["h"] + dy)
        self.geometry(f"{new_w}x{new_h}")

    def get_region(self):
        self.update_idletasks()
        return {
            "left": self.winfo_x(),
            "top": self.winfo_y(),
            "width": self.winfo_width(),
            "height": self.winfo_height(),
        }


class TranslationApp(tk.Tk):
    """Main control panel for screen translation."""

    def __init__(self):
        super().__init__()
        self.title("Screen Translator")
        self.geometry("520x480")
        self.resizable(False, False)
        self.attributes("-topmost", True)

        self.translator = Translator()
        self.running = False

        self._build_ui()
        self.capture_frame = CaptureFrame(self)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        settings_frame = ttk.LabelFrame(self, text="Settings", padding=10)
        settings_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(settings_frame, text="Target Language:").grid(
            row=0, column=0, sticky=tk.W, pady=2,
        )
        self.lang_var = tk.StringVar(value="日本語")
        lang_combo = ttk.Combobox(
            settings_frame, textvariable=self.lang_var,
            values=list(LANG_OPTIONS.keys()), state="readonly", width=20,
        )
        lang_combo.grid(row=0, column=1, padx=5, pady=2)

        ttk.Label(settings_frame, text="Interval (sec):").grid(
            row=1, column=0, sticky=tk.W, pady=2,
        )
        self.interval_var = tk.StringVar(value="2")
        interval_spin = ttk.Spinbox(
            settings_frame, from_=1, to=30, textvariable=self.interval_var,
            width=5,
        )
        interval_spin.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)

        self.toggle_btn = ttk.Button(
            btn_frame, text="▶  Start", command=self._toggle,
        )
        self.toggle_btn.pack(side=tk.LEFT, padx=5)

        self.status_label = ttk.Label(btn_frame, text="Stopped", foreground="gray")
        self.status_label.pack(side=tk.LEFT, padx=10)

        result_frame = ttk.LabelFrame(self, text="Detected / Translated", padding=10)
        result_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        ttk.Label(result_frame, text="Original:").pack(anchor=tk.W)
        self.original_text = tk.Text(
            result_frame, height=5, wrap=tk.WORD, state=tk.DISABLED,
        )
        self.original_text.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        ttk.Label(result_frame, text="Translation:").pack(anchor=tk.W)
        self.translated_text = tk.Text(
            result_frame, height=5, wrap=tk.WORD, state=tk.DISABLED,
        )
        self.translated_text.pack(fill=tk.BOTH, expand=True)

    def _toggle(self):
        if self.running:
            self.running = False
            self.toggle_btn.config(text="▶  Start")
            self.status_label.config(text="Stopped", foreground="gray")
        else:
            self.running = True
            self.toggle_btn.config(text="⏹  Stop")
            self.status_label.config(text="Running", foreground="green")
            self._schedule_capture()

    def _schedule_capture(self):
        if not self.running:
            return
        threading.Thread(target=self._capture_and_translate, daemon=True).start()
        interval = int(float(self.interval_var.get()) * 1000)
        self.after(interval, self._schedule_capture)

    def _capture_and_translate(self):
        try:
            region = self.capture_frame.get_region()
            with mss.mss() as sct:
                screenshot = sct.grab(region)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

            ocr_text = pytesseract.image_to_string(img).strip()
            if not ocr_text:
                self._update_texts("(No text detected)", "")
                return

            target_code = LANG_OPTIONS.get(self.lang_var.get(), "en")
            result = self.translator.translate(ocr_text, dest=target_code)
            src_lang = LANGUAGES.get(result.src.lower(), result.src)
            translated = result.text

            self._update_texts(
                f"[{src_lang}]\n{ocr_text}",
                f"[{LANGUAGES.get(target_code, target_code)}]\n{translated}",
            )
        except Exception as e:
            self._update_texts(f"Error: {e}", "")

    def _update_texts(self, original, translated):
        def _update():
            self.original_text.config(state=tk.NORMAL)
            self.original_text.delete("1.0", tk.END)
            self.original_text.insert(tk.END, original)
            self.original_text.config(state=tk.DISABLED)

            self.translated_text.config(state=tk.NORMAL)
            self.translated_text.delete("1.0", tk.END)
            self.translated_text.insert(tk.END, translated)
            self.translated_text.config(state=tk.DISABLED)
        self.after(0, _update)

    def _on_close(self):
        self.running = False
        self.capture_frame.destroy()
        self.destroy()


def main():
    app = TranslationApp()
    app.mainloop()


if __name__ == "__main__":
    main()

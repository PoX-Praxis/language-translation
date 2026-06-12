"""
Screen Translation Overlay App
- Captures text within a movable/resizable overlay frame
- Detects the source language and translates to a selected target language
- Displays translated text directly inside the capture frame
- Supports Google Translate and local LLM (Ollama) as translation engines
- Auto-translates when text changes; click overlay to dismiss
"""

import concurrent.futures
import json
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
import traceback
import urllib.request
import urllib.error

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk
import mss
import pytesseract
import urllib.parse

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

ENGINE_GOOGLE = "Google Translate"
ENGINE_DEEPL = "DeepL"
ENGINE_OLLAMA = "Ollama (Local LLM)"

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "translator"

DEEPL_LANG_MAP = {
    "ja": "JA", "en": "EN", "zh-cn": "ZH", "ko": "KO",
    "fr": "FR", "de": "DE", "es": "ES", "pt": "PT-BR",
    "ru": "RU", "ar": "AR", "hi": "HI", "it": "IT",
    "nl": "NL", "tr": "TR", "vi": "VI", "th": "TH",
}


# ---------------------------------------------------------------------------
# Translation engines
# ---------------------------------------------------------------------------

class GoogleTranslateEngine:
    _TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"

    def _translate_one(self, text, target_code):
        params = urllib.parse.urlencode({
            "client": "gtx",
            "sl": "auto",
            "tl": target_code,
            "dt": "t",
            "q": text,
        })
        url = f"{self._TRANSLATE_URL}?{params}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        translated = "".join(seg[0] for seg in data[0] if seg[0])
        src_lang = data[2] if len(data) > 2 else "auto"
        return translated, src_lang

    def translate(self, text, target_code):
        paragraphs = [p for p in text.split("\n") if p.strip()]
        if len(paragraphs) <= 1:
            return self._translate_one(text, target_code)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(self._translate_one, p, target_code)
                for p in paragraphs
            ]
            results = [f.result() for f in futures]
        translated = "\n".join(r[0] for r in results)
        src_lang = results[0][1]
        return translated, src_lang


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


class OllamaEngine:
    """Uses /api/generate with a custom Modelfile-based model for speed."""

    GENERATE_OPTIONS = {
        "temperature": 0.1,
        "top_p": 0.9,
        "top_k": 20,
        "num_predict": 256,
        "num_ctx": 512,
        "num_batch": 128,
    }

    def __init__(self, base_url=DEFAULT_OLLAMA_URL, model=DEFAULT_OLLAMA_MODEL):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._status_cb = None

    def set_status_callback(self, cb):
        self._status_cb = cb

    def _report(self, msg, color="blue"):
        if self._status_cb:
            self._status_cb(msg, color)

    def _post(self, endpoint, payload_dict):
        data = json.dumps(payload_dict).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{endpoint}",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        return urllib.request.urlopen(req, timeout=300)

    @staticmethod
    def _clean_output(text):
        text = text.strip()
        quote_pairs = [
            ('"""', '"""'), ("'''", "'''"), ('``', "''"),
            ("“", "”"), ("「", "」"),
            ("『", "』"), ('"', '"'), ("'", "'"),
        ]
        for open_q, close_q in quote_pairs:
            if text.startswith(open_q) and text.endswith(close_q):
                text = text[len(open_q):-len(close_q)].strip()
                break
        lines = text.split("\n")
        cleaned = []
        for line in lines:
            low = line.strip().lower()
            if low.startswith("translation:") or low.startswith("here is"):
                continue
            if low.startswith("note:") or low.startswith("---"):
                break
            if low.startswith("```"):
                continue
            cleaned.append(line)
        return "\n".join(cleaned).strip()

    def translate(self, text, target_code):
        target_name = LANG_NAMES_NATIVE.get(target_code, target_code)
        prompt = f">{target_name}:\n{text}"

        use_stream = len(text) > 200

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": use_stream,
            "options": self.GENERATE_OPTIONS,
        }

        self._report("Ollama: translating...")

        try:
            resp = self._post("/api/generate", payload)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama HTTP {e.code}: {body}") from e

        try:
            if not use_stream:
                body = json.loads(resp.read().decode("utf-8"))
                if "error" in body:
                    raise RuntimeError(f"Ollama: {body['error']}")
                raw = body.get("response", "")
            else:
                chunks = []
                for raw_line in resp:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        obj = json.loads(raw_line.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    if "error" in obj:
                        raise RuntimeError(f"Ollama: {obj['error']}")
                    token = obj.get("response", "")
                    if token:
                        chunks.append(token)
                    if obj.get("done", False):
                        break
                raw = "".join(chunks)
        finally:
            resp.close()

        if not raw.strip():
            raise RuntimeError("Ollama returned empty response")

        translated = self._clean_output(raw)
        return translated, "auto"

    def warmup(self):
        try:
            self._report(f"Loading {self.model} into memory...")
            payload = {
                "model": self.model,
                "prompt": "Hi",
                "stream": False,
                "options": {"num_predict": 1},
            }
            resp = self._post("/api/generate", payload)
            resp.read()
            resp.close()
            self._report(f"{self.model} loaded and ready", "green")
            return True
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            self._report(f"Warmup failed: HTTP {e.code} - {body}", "red")
            return False
        except Exception as e:
            self._report(f"Warmup failed: {e}", "red")
            return False

    @staticmethod
    def list_models(base_url=DEFAULT_OLLAMA_URL):
        try:
            req = urllib.request.Request(
                f"{base_url.rstrip('/')}/api/tags",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return [m["name"] for m in body.get("models", [])]
        except Exception:
            return []

    @staticmethod
    def is_available(base_url=DEFAULT_OLLAMA_URL):
        try:
            req = urllib.request.Request(f"{base_url.rstrip('/')}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False


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

class TranslationApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Screen Translator")
        self.geometry("450x320")
        self.resizable(False, False)
        self.attributes("-topmost", True)

        self._google_engine = GoogleTranslateEngine()
        self._deepl_engine = DeepLEngine()
        self._ollama_engine = None

        self.running = False
        self._lock = threading.Lock()
        self._prev_first_word = None
        self._prev_translated = ""
        self._prev_bg_color = (255, 255, 255)

        self._build_ui()

        self.capture_frame = CaptureFrame(self)
        self.overlay = TranslationOverlay(self, on_click=self._on_overlay_click)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._check_ollama_status()

    def _build_ui(self):
        # --- Engine settings ---
        engine_frame = ttk.LabelFrame(self, text="Translation Engine", padding=8)
        engine_frame.pack(fill=tk.X, padx=10, pady=(5, 2))

        self.engine_var = tk.StringVar(value=ENGINE_GOOGLE)
        engine_combo = ttk.Combobox(
            engine_frame, textvariable=self.engine_var,
            values=[ENGINE_GOOGLE, ENGINE_DEEPL, ENGINE_OLLAMA],
            state="readonly", width=22,
        )
        engine_combo.grid(row=0, column=0, columnspan=2, padx=5, pady=2, sticky=tk.W)
        engine_combo.bind("<<ComboboxSelected>>", self._on_engine_change)

        self.deepl_frame = ttk.Frame(engine_frame)
        self.deepl_frame.grid(
            row=1, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2,
        )
        ttk.Label(self.deepl_frame, text="API Key:").grid(
            row=0, column=0, sticky=tk.W,
        )
        self.deepl_key_var = tk.StringVar()
        deepl_entry = ttk.Entry(
            self.deepl_frame, textvariable=self.deepl_key_var,
            width=32, show="*",
        )
        deepl_entry.grid(row=0, column=1, padx=5)
        ttk.Label(
            self.deepl_frame,
            text="Free API: https://www.deepl.com/pro-api",
            foreground="gray",
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W)
        self.deepl_frame.grid_remove()

        self.ollama_frame = ttk.Frame(engine_frame)
        self.ollama_frame.grid(
            row=2, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2,
        )

        ttk.Label(self.ollama_frame, text="URL:").grid(
            row=0, column=0, sticky=tk.W,
        )
        self.ollama_url_var = tk.StringVar(value=DEFAULT_OLLAMA_URL)
        url_entry = ttk.Entry(
            self.ollama_frame, textvariable=self.ollama_url_var, width=25,
        )
        url_entry.grid(row=0, column=1, padx=5)

        ttk.Label(self.ollama_frame, text="Model:").grid(
            row=1, column=0, sticky=tk.W,
        )
        self.ollama_model_var = tk.StringVar(value=DEFAULT_OLLAMA_MODEL)
        self.model_combo = ttk.Combobox(
            self.ollama_frame, textvariable=self.ollama_model_var, width=22,
        )
        self.model_combo.grid(row=1, column=1, padx=5, pady=2)

        self.refresh_btn = ttk.Button(
            self.ollama_frame, text="Refresh", width=8,
            command=self._refresh_models,
        )
        self.refresh_btn.grid(row=1, column=2, padx=2)

        self.ollama_status = ttk.Label(
            self.ollama_frame, text="", foreground="gray",
        )
        self.ollama_status.grid(row=2, column=0, columnspan=3, sticky=tk.W)

        self.warmup_btn = ttk.Button(
            self.ollama_frame, text="Load Model",
            command=self._warmup_model,
        )
        self.warmup_btn.grid(row=0, column=2, padx=2)

        self.ollama_frame.grid_remove()

        # --- Translation settings ---
        settings_frame = ttk.LabelFrame(self, text="Settings", padding=8)
        settings_frame.pack(fill=tk.X, padx=10, pady=2)

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

        # --- Controls ---
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
            self, text="", foreground="blue", wraplength=430,
        )
        self.info_label.pack(fill=tk.X, padx=10, pady=(0, 5))

    # --- Engine management ---

    def _on_engine_change(self, event=None):
        engine = self.engine_var.get()
        self.deepl_frame.grid_remove()
        self.ollama_frame.grid_remove()
        if engine == ENGINE_DEEPL:
            self.deepl_frame.grid()
            self.geometry("450x360")
        elif engine == ENGINE_OLLAMA:
            self.ollama_frame.grid()
            self.geometry("450x420")
            self._check_ollama_status()
        else:
            self.geometry("450x320")

    def _check_ollama_status(self):
        def _check():
            url = self.ollama_url_var.get()
            if OllamaEngine.is_available(url):
                models = OllamaEngine.list_models(url)
                self.after(0, lambda: self._update_ollama_ui(True, models))
            else:
                self.after(0, lambda: self._update_ollama_ui(False, []))
        threading.Thread(target=_check, daemon=True).start()

    def _update_ollama_ui(self, available, models):
        if available:
            self.ollama_status.config(
                text=f"Connected ({len(models)} models)",
                foreground="green",
            )
            self.model_combo["values"] = models
            if models and not self.ollama_model_var.get():
                self.ollama_model_var.set(models[0])
        else:
            self.ollama_status.config(
                text="Not connected - is Ollama running?",
                foreground="red",
            )
            self.model_combo["values"] = []

    def _refresh_models(self):
        self.ollama_status.config(text="Checking...", foreground="gray")
        self._check_ollama_status()

    def _warmup_model(self):
        self.warmup_btn.config(state=tk.DISABLED)
        self._set_status("Loading model into memory...")

        def _do():
            engine = self._get_engine()
            if isinstance(engine, OllamaEngine):
                engine.warmup()
            self.after(0, lambda: self.warmup_btn.config(state=tk.NORMAL))
        threading.Thread(target=_do, daemon=True).start()

    def _get_engine(self):
        engine = self.engine_var.get()
        if engine == ENGINE_DEEPL:
            self._deepl_engine.api_key = self.deepl_key_var.get().strip()
            return self._deepl_engine
        if engine == ENGINE_OLLAMA:
            url = self.ollama_url_var.get()
            model = self.ollama_model_var.get()
            if self._ollama_engine is None or \
               self._ollama_engine.base_url != url.rstrip("/") or \
               self._ollama_engine.model != model:
                self._ollama_engine = OllamaEngine(url, model)
                self._ollama_engine.set_status_callback(self._set_status)
            return self._ollama_engine
        return self._google_engine

    # --- Status ---

    def _set_status(self, text, color="blue"):
        self.after(
            0, lambda t=text, c=color: self.info_label.config(
                text=t, foreground=c,
            ),
        )

    # --- Start / Stop ---

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
            threading.Thread(
                target=self._scan_and_translate, daemon=True,
            ).start()
        self.after(1000, self._poll)

    def _manual_translate(self):
        if not self.running:
            return
        self.overlay.hide()
        self._prev_first_word = None
        self._set_status("Translating...")
        threading.Thread(
            target=self._scan_and_translate, daemon=True,
        ).start()

    def _on_overlay_click(self):
        self._prev_first_word = None
        self._set_status("Dismissed. Rescanning...")

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
                self._set_status("No text detected in frame")
                self._prev_first_word = None
                return

            ocr_text = _join_hard_wraps(raw_text)

            current_first = _first_word(ocr_text)

            if (self._prev_first_word is not None
                    and current_first == self._prev_first_word):
                return

            self._set_status(f"Translating: {ocr_text[:50]}...")

            target_code = LANG_OPTIONS.get(self.lang_var.get(), "en")

            engine = self._get_engine()
            translated, src_lang = engine.translate(ocr_text, target_code)

            self._prev_first_word = current_first
            self._prev_translated = translated
            self._prev_bg_color = bg_color

            engine_name = self.engine_var.get().split(" ")[0]
            target_name = LANG_NAMES_NATIVE.get(target_code, target_code)
            self._set_status(
                f"[{engine_name}] [{src_lang}] → [{target_name}]",
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
        except urllib.error.URLError as e:
            self._set_status(
                f"Ollama connection failed: {e.reason}", "red",
            )
            traceback.print_exc()
        except RuntimeError as e:
            self._set_status(f"Error: {e}", "red")
            traceback.print_exc()
        except Exception as e:
            self._set_status(f"Error: {type(e).__name__}: {e}", "red")
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

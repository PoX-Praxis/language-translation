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
            fg = tuple(np.median(flat[far_mask], axis=0).astype(int)[:3])
        else:
            fg = _text_color_for_bg(bg)
    else:
        fg = _text_color_for_bg(bg)

    return bg, fg


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


def _extract_text_blocks(gray_img):
    data = pytesseract.image_to_data(
        gray_img, output_type=pytesseract.Output.DICT,
    )
    blocks = {}
    n = len(data["text"])
    for i in range(n):
        conf = int(data["conf"][i])
        text = data["text"][i].strip()
        if conf < 0 or not text:
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
            }
        b = blocks[block_id]
        b["x"] = min(b["x"], data["left"][i])
        b["y"] = min(b["y"], data["top"][i])
        b["x2"] = max(b["x2"], data["left"][i] + data["width"][i])
        b["y2"] = max(b["y2"], data["top"][i] + data["height"][i])
        b["words"].append(text)
        b["word_heights"].append(data["height"][i])
        line_id = data["line_num"][i]
        if line_id not in b["lines"]:
            b["lines"][line_id] = []
        b["lines"][line_id].append(text)

    result = []
    for bid in sorted(blocks.keys()):
        b = blocks[bid]
        line_texts = [
            " ".join(words)
            for _, words in sorted(b["lines"].items())
        ]
        full_text = _join_hard_wraps("\n".join(line_texts))
        if not full_text.strip():
            continue
        avg_h = int(np.median(b["word_heights"])) if b["word_heights"] else 16
        pad_x = 6
        pad_y = 4
        result.append({
            "x": max(0, b["x"] - pad_x),
            "y": max(0, b["y"] - pad_y),
            "w": b["x2"] - b["x"] + pad_x * 2,
            "h": b["y2"] - b["y"] + pad_y * 2,
            "text": full_text,
            "median_char_h": avg_h,
        })
    return result


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


def _classify_blocks(blocks):
    if not blocks:
        return {}
    heights = [b["median_char_h"] for b in blocks]
    body_h = int(np.median(heights))
    sizes = {}
    for i, b in enumerate(blocks):
        diff = b["median_char_h"] - body_h
        if diff > body_h * 0.15:
            sizes[i] = 1
        elif diff < -body_h * 0.15:
            sizes[i] = -1
        else:
            sizes[i] = 0
    return sizes


def _render_inplace(base_img, blocks, translations, font_size):
    img = base_img.copy()
    draw = ImageDraw.Draw(img)
    iw, ih = img.size

    size_classes = _classify_blocks(blocks)

    block_renders = []
    for i, (block, translated) in enumerate(zip(blocks, translations)):
        x, y, w, h = block["x"], block["y"], block["w"], block["h"]
        offset = size_classes.get(i, 0)
        fs = font_size + offset
        font = _find_system_font(fs)
        line_spacing = int(fs * 0.35)

        margin = 4
        max_w = w - margin * 2
        wrapped = _wrap_text(translated, font, max_w, draw)

        total_h = margin * 2
        for line in wrapped:
            if not line:
                total_h += fs // 2
            else:
                bbox = draw.textbbox((0, 0), line, font=font)
                total_h += bbox[3] - bbox[1] + line_spacing

        render_h = max(h, total_h)

        block_renders.append({
            "x": x, "y": y, "w": w, "h": render_h,
            "wrapped": wrapped, "font": font, "fs": fs,
            "line_spacing": line_spacing, "margin": margin,
        })

    for i in range(len(block_renders) - 1):
        cur = block_renders[i]
        nxt = block_renders[i + 1]
        cur_bottom = cur["y"] + cur["h"]
        if cur_bottom > nxt["y"]:
            shift = cur_bottom - nxt["y"] + 4
            for j in range(i + 1, len(block_renders)):
                block_renders[j]["y"] += shift

    for i, br in enumerate(block_renders):
        x, y, w, h = br["x"], br["y"], br["w"], br["h"]
        orig_block = blocks[i]
        ox, oy = orig_block["x"], orig_block["y"]
        ow, oh = orig_block["w"], orig_block["h"]
        bg_color, fg_color = _region_colors(base_img, ox, oy, ow, oh)

        draw.rectangle([x, y, x + w, y + h], fill=bg_color)

        margin = br["margin"]
        dy = y + margin
        for line in br["wrapped"]:
            if not line:
                dy += br["fs"] // 2
                continue
            bbox = draw.textbbox((0, 0), line, font=br["font"])
            line_h = bbox[3] - bbox[1] + br["line_spacing"]
            draw.text((x + margin, dy), line, fill=fg_color, font=br["font"])
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
            blocks = _extract_text_blocks(gray)

            if not blocks:
                self._prev_first_word = None
                return

            all_text = " ".join(b["text"] for b in blocks)
            current_first = _first_word(all_text)

            if (self._prev_first_word is not None
                    and current_first == self._prev_first_word):
                return

            target_code = LANG_OPTIONS.get(
                self.toolbar.lang_var.get(), "en",
            )

            block_texts = [b["text"] for b in blocks]
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

            self._prev_first_word = current_first

            font_size = int(self.toolbar.fontsize_var.get())
            w, h = region["width"], region["height"]
            result_img = _render_inplace(img, blocks, translations, font_size)

            self.after(
                0,
                self.overlay.show_at,
                region["left"], region["top"], w, h, result_img,
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

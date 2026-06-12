"""
Windows Desktop Translation App
Powered by local Ollama + gemma3:1b

Features:
- Real-time translation as you type
- Clipboard translation (Ctrl+Shift+T hotkey)
- Language swap
- Translation history
- Always-on-top mode
- System tray minimization

Requirements:
    pip install pystray Pillow
    (tkinter is included with Python on Windows)

Usage:
    python desktop_app.py
"""

import json
import os
import threading
import time
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import urllib.request
import urllib.error

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL_NAME = os.environ.get("MODEL_NAME", "translator")

LANGUAGES = [
    ("Auto Detect", ""),
    ("Japanese", "ja"),
    ("English", "en"),
    ("Chinese", "zh"),
    ("Korean", "ko"),
    ("French", "fr"),
    ("German", "de"),
    ("Spanish", "es"),
    ("Portuguese", "pt"),
    ("Italian", "it"),
    ("Russian", "ru"),
    ("Arabic", "ar"),
    ("Thai", "th"),
    ("Vietnamese", "vi"),
    ("Indonesian", "id"),
    ("Dutch", "nl"),
]

LANG_NAMES = {code: name for name, code in LANGUAGES if code}

# ---------------------------------------------------------------------------
# Translation engine
# ---------------------------------------------------------------------------

def translate(text: str, target: str, source: str = "") -> dict:
    target_name = LANG_NAMES.get(target, target)
    if source:
        source_name = LANG_NAMES.get(source, source)
        prompt = f"Translate from {source_name} to {target_name}. Output only the translation:\n\n{text}"
    else:
        prompt = f"Translate to {target_name}. Output only the translation:\n\n{text}"

    payload = json.dumps({
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "top_p": 0.9,
            "top_k": 20,
            "num_predict": 512,
            "num_ctx": 1024,
        },
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        elapsed = (time.perf_counter() - start) * 1000
        return {
            "ok": True,
            "translation": data["response"].strip(),
            "elapsed_ms": elapsed,
        }
    except urllib.error.URLError:
        return {"ok": False, "error": "Ollama is not running.\nStart it with: ollama serve"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_ollama() -> bool:
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            return any(MODEL_NAME in m for m in models)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class TranslatorApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Local Translator — gemma3:1b")
        self.root.geometry("800x520")
        self.root.minsize(600, 400)
        self.root.configure(bg="#1a1d27")

        self._set_icon()
        self._apply_theme()
        self._build_ui()
        self._bind_shortcuts()

        self.auto_translate_timer = None
        self.history: list[dict] = []

        self._check_connection()

    def _set_icon(self):
        try:
            self.root.iconbitmap(default="")
        except Exception:
            pass

    def _apply_theme(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", background="#1a1d27", foreground="#e4e4e7",
                         fieldbackground="#2a2d3a", borderwidth=0)
        style.configure("TFrame", background="#1a1d27")
        style.configure("TLabel", background="#1a1d27", foreground="#e4e4e7",
                         font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Status.TLabel", foreground="#71717a", font=("Segoe UI", 9))
        style.configure("TCombobox", fieldbackground="#2a2d3a", background="#2a2d3a",
                         foreground="#e4e4e7", arrowcolor="#e4e4e7")
        style.configure("Translate.TButton", background="#6366f1", foreground="white",
                         font=("Segoe UI", 10, "bold"), padding=(16, 8))
        style.map("Translate.TButton",
                   background=[("active", "#818cf8"), ("disabled", "#3a3d4a")])
        style.configure("Swap.TButton", background="#2a2d3a", foreground="#e4e4e7",
                         font=("Segoe UI", 12), padding=(8, 4))
        style.map("Swap.TButton", background=[("active", "#3a3d4a")])
        style.configure("Pin.TButton", background="#2a2d3a", foreground="#e4e4e7",
                         padding=(6, 2))
        style.map("Pin.TButton", background=[("active", "#3a3d4a")])
        style.configure("TCheckbutton", background="#1a1d27", foreground="#e4e4e7")

    def _build_ui(self):
        # Top bar
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=12, pady=(12, 6))

        ttk.Label(top, text="Local Translator", style="Header.TLabel").pack(side="left")

        self.pin_var = tk.BooleanVar(value=False)
        pin_btn = ttk.Checkbutton(top, text="Pin", variable=self.pin_var,
                                   command=self._toggle_pin, style="TCheckbutton")
        pin_btn.pack(side="right", padx=(8, 0))

        self.status_label = ttk.Label(top, text="", style="Status.TLabel")
        self.status_label.pack(side="right")

        # Language bar
        lang_frame = ttk.Frame(self.root)
        lang_frame.pack(fill="x", padx=12, pady=6)

        lang_names = [name for name, _ in LANGUAGES]

        self.source_lang = ttk.Combobox(lang_frame, values=lang_names, state="readonly", width=18)
        self.source_lang.set("English")
        self.source_lang.pack(side="left")

        swap_btn = ttk.Button(lang_frame, text=" ⮀ ", style="Swap.TButton",
                               command=self._swap_languages)
        swap_btn.pack(side="left", padx=12)

        self.target_lang = ttk.Combobox(lang_frame, values=lang_names[1:], state="readonly", width=18)
        self.target_lang.set("Japanese")
        self.target_lang.pack(side="left")

        self.auto_var = tk.BooleanVar(value=False)
        auto_cb = ttk.Checkbutton(lang_frame, text="Auto", variable=self.auto_var,
                                   style="TCheckbutton")
        auto_cb.pack(side="right")

        # Text panels
        panels = ttk.Frame(self.root)
        panels.pack(fill="both", expand=True, padx=12, pady=6)
        panels.columnconfigure(0, weight=1)
        panels.columnconfigure(1, weight=1)
        panels.rowconfigure(0, weight=1)

        # Input
        input_frame = ttk.Frame(panels)
        input_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        self.input_text = scrolledtext.ScrolledText(
            input_frame, wrap="word", font=("Segoe UI", 11),
            bg="#2a2d3a", fg="#e4e4e7", insertbackground="#e4e4e7",
            relief="flat", padx=10, pady=10, undo=True,
        )
        self.input_text.pack(fill="both", expand=True)
        self.input_text.bind("<KeyRelease>", self._on_key_release)

        input_bottom = ttk.Frame(input_frame)
        input_bottom.pack(fill="x", pady=(4, 0))
        self.char_label = ttk.Label(input_bottom, text="0 chars", style="Status.TLabel")
        self.char_label.pack(side="left")
        clear_btn = ttk.Button(input_bottom, text="Clear", command=self._clear_input)
        clear_btn.pack(side="right")

        # Output
        output_frame = ttk.Frame(panels)
        output_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        self.output_text = scrolledtext.ScrolledText(
            output_frame, wrap="word", font=("Segoe UI", 11),
            bg="#2a2d3a", fg="#e4e4e7", relief="flat", padx=10, pady=10,
            state="disabled",
        )
        self.output_text.pack(fill="both", expand=True)

        output_bottom = ttk.Frame(output_frame)
        output_bottom.pack(fill="x", pady=(4, 0))
        self.elapsed_label = ttk.Label(output_bottom, text="", style="Status.TLabel")
        self.elapsed_label.pack(side="left")
        copy_btn = ttk.Button(output_bottom, text="Copy", command=self._copy_output)
        copy_btn.pack(side="right")

        # Bottom bar
        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", padx=12, pady=(6, 12))

        self.translate_btn = ttk.Button(bottom, text="Translate  (Ctrl+Enter)",
                                         style="Translate.TButton",
                                         command=self._do_translate)
        self.translate_btn.pack(fill="x")

        self.clip_label = ttk.Label(bottom, text="Ctrl+Shift+T: translate clipboard",
                                     style="Status.TLabel")
        self.clip_label.pack(pady=(6, 0))

    def _bind_shortcuts(self):
        self.root.bind("<Control-Return>", lambda e: self._do_translate())
        self.root.bind("<Control-Shift-T>", lambda e: self._translate_clipboard())
        self.root.bind("<Control-Shift-t>", lambda e: self._translate_clipboard())

    # --- Actions ---

    def _get_lang_code(self, combo: ttk.Combobox) -> str:
        name = combo.get()
        for n, code in LANGUAGES:
            if n == name:
                return code
        return ""

    def _do_translate(self):
        text = self.input_text.get("1.0", "end-1c").strip()
        if not text:
            return

        target = self._get_lang_code(self.target_lang)
        source = self._get_lang_code(self.source_lang)

        if not target:
            self._set_status("Select a target language")
            return

        self.translate_btn.configure(state="disabled")
        self._set_status("Translating...")
        self._set_output("...")

        def run():
            result = translate(text, target, source)
            self.root.after(0, lambda: self._on_result(result))

        threading.Thread(target=run, daemon=True).start()

    def _on_result(self, result: dict):
        self.translate_btn.configure(state="normal")
        if result["ok"]:
            self._set_output(result["translation"])
            ms = result["elapsed_ms"]
            self.elapsed_label.configure(text=f"{ms:.0f}ms")
            self._set_status(f"Done in {ms:.0f}ms")
            self.history.append({
                "input": self.input_text.get("1.0", "end-1c").strip(),
                "output": result["translation"],
                "target": self.target_lang.get(),
                "ms": ms,
            })
        else:
            self._set_output(f"Error: {result['error']}")
            self._set_status("Error")

    def _translate_clipboard(self):
        try:
            clip = self.root.clipboard_get()
            if clip.strip():
                self.input_text.delete("1.0", "end")
                self.input_text.insert("1.0", clip.strip())
                self._update_char_count()
                self._do_translate()
        except tk.TclError:
            self._set_status("Clipboard empty")

    def _swap_languages(self):
        src = self.source_lang.get()
        tgt = self.target_lang.get()
        if src == "Auto Detect":
            return
        self.source_lang.set(tgt)
        self.target_lang.set(src)

        output = self.output_text.get("1.0", "end-1c").strip()
        if output and output != "...":
            inp = self.input_text.get("1.0", "end-1c").strip()
            self.input_text.delete("1.0", "end")
            self.input_text.insert("1.0", output)
            self._set_output(inp)
            self._update_char_count()

    def _clear_input(self):
        self.input_text.delete("1.0", "end")
        self._set_output("")
        self._update_char_count()
        self.elapsed_label.configure(text="")

    def _copy_output(self):
        text = self.output_text.get("1.0", "end-1c").strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self._set_status("Copied!")

    def _toggle_pin(self):
        self.root.attributes("-topmost", self.pin_var.get())

    def _on_key_release(self, event=None):
        self._update_char_count()
        if self.auto_var.get():
            if self.auto_translate_timer:
                self.root.after_cancel(self.auto_translate_timer)
            self.auto_translate_timer = self.root.after(800, self._do_translate)

    def _update_char_count(self):
        text = self.input_text.get("1.0", "end-1c")
        self.char_label.configure(text=f"{len(text)} chars")

    def _set_output(self, text: str):
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", text)
        self.output_text.configure(state="disabled")

    def _set_status(self, text: str):
        self.status_label.configure(text=text)

    def _check_connection(self):
        def check():
            ok = check_ollama()
            self.root.after(0, lambda: self._set_status(
                "Ready" if ok else "Ollama not running — start with: ollama serve"
            ))
        threading.Thread(target=check, daemon=True).start()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = TranslatorApp()
    app.run()

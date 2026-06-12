"""
Windows Desktop Batch Translation App
High-throughput document translation powered by local Ollama + gemma3:1b

Features:
- Drag & drop files/folders or browse to select
- Parallel chunk-based translation with configurable workers
- Real-time progress: per-file, per-chunk, overall
- Quality scoring with cloud API fallback
- Live throughput stats (chars/sec, ETA)
- Translation log with per-chunk detail
- Pause / Cancel / Resume

Requirements:
    pip install httpx
    (tkinter is included with Python on Windows)

Usage:
    python desktop_app.py
"""

import asyncio
import json
import os
import re
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from dataclasses import dataclass
from pathlib import Path

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL_NAME = os.environ.get("MODEL_NAME", "translator")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

LANGUAGES = [
    ("Auto Detect", ""),
    ("Japanese", "ja"), ("English", "en"), ("Chinese", "zh"),
    ("Korean", "ko"), ("French", "fr"), ("German", "de"),
    ("Spanish", "es"), ("Portuguese", "pt"), ("Italian", "it"),
    ("Russian", "ru"), ("Arabic", "ar"), ("Thai", "th"),
    ("Vietnamese", "vi"), ("Indonesian", "id"), ("Dutch", "nl"),
]
LANG_NAMES = {code: name for name, code in LANGUAGES if code}
FILE_EXTENSIONS = [".txt", ".md", ".html", ".csv", ".json", ".srt", ".vtt"]


# ---------------------------------------------------------------------------
# Pipeline core (embedded from batch_pipeline.py)
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    index: int
    text: str
    translation: str = ""
    quality_score: float = 0.0
    source: str = "local"


@dataclass
class FileJob:
    path: Path
    status: str = "pending"  # pending, running, done, error, cancelled
    total_chunks: int = 0
    done_chunks: int = 0
    local_ok: int = 0
    cloud_used: int = 0
    failed: int = 0
    chars: int = 0
    elapsed_s: float = 0.0
    error_msg: str = ""


def split_into_chunks(text: str, max_chars: int = 500) -> list[Chunk]:
    paragraphs = re.split(r'\n\s*\n', text)
    chunks: list[Chunk] = []
    current = ""
    idx = 0
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) + 2 > max_chars and current:
            chunks.append(Chunk(index=idx, text=current.strip()))
            idx += 1
            current = ""
        if len(para) > max_chars:
            sentences = re.split(r'(?<=[.!?。！？])\s+', para)
            for sent in sentences:
                if len(current) + len(sent) + 1 > max_chars and current:
                    chunks.append(Chunk(index=idx, text=current.strip()))
                    idx += 1
                    current = ""
                current += sent + " "
        else:
            current += para + "\n\n"
    if current.strip():
        chunks.append(Chunk(index=idx, text=current.strip()))
    return chunks


def score_quality(chunk: Chunk) -> float:
    if not chunk.translation:
        return 0.0
    score = 1.0
    src_len = len(chunk.text)
    tgt_len = len(chunk.translation)
    if src_len > 0:
        ratio = tgt_len / src_len
        if ratio < 0.2 or ratio > 5.0:
            score -= 0.4
        elif ratio < 0.3 or ratio > 3.0:
            score -= 0.2
    if chunk.translation.strip() == chunk.text.strip():
        score -= 0.5
    if re.findall(r'(.{10,}?)\1{2,}', chunk.translation):
        score -= 0.3
    if any(m in chunk.translation.lower() for m in
           ["here is", "translation:", "note:", "i cannot", "i can't"]):
        score -= 0.4
    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Async translation engine
# ---------------------------------------------------------------------------

class BatchEngine:
    def __init__(self, on_progress=None, on_log=None):
        self.on_progress = on_progress or (lambda *a: None)
        self.on_log = on_log or (lambda *a: None)
        self._cancelled = False
        self._paused = False
        self._pause_event = asyncio.Event()
        self._pause_event.set()

    def cancel(self):
        self._cancelled = True
        self._pause_event.set()

    def pause(self):
        self._paused = True
        self._pause_event.clear()

    def resume(self):
        self._paused = False
        self._pause_event.set()

    @property
    def is_paused(self):
        return self._paused

    async def _wait_if_paused(self):
        await self._pause_event.wait()

    async def translate_chunk_local(self, client, chunk, target, source, semaphore, job):
        await self._wait_if_paused()
        if self._cancelled:
            return chunk

        target_name = LANG_NAMES.get(target, target)
        if source:
            source_name = LANG_NAMES.get(source, source)
            prompt = f"Translate from {source_name} to {target_name}. Output only the translation:\n\n{chunk.text}"
        else:
            prompt = f"Translate to {target_name}. Output only the translation:\n\n{chunk.text}"

        payload = {
            "model": MODEL_NAME, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.1, "top_p": 0.9, "top_k": 20,
                        "num_predict": 512, "num_ctx": 1024},
        }

        async with semaphore:
            try:
                resp = await client.post("/api/generate", json=payload)
                resp.raise_for_status()
                chunk.translation = resp.json()["response"].strip()
                chunk.source = "local"
                chunk.quality_score = score_quality(chunk)
            except Exception as e:
                chunk.translation = ""
                chunk.quality_score = 0.0
                self.on_log(f"  [chunk {chunk.index}] error: {e}")

            job.done_chunks += 1
            self.on_progress(job)

        return chunk

    async def translate_chunk_cloud(self, client, chunk, target, source, semaphore):
        if self._cancelled:
            return chunk
        await self._wait_if_paused()

        target_name = LANG_NAMES.get(target, target)
        if source:
            source_name = LANG_NAMES.get(source, source)
            instruction = f"Translate from {source_name} to {target_name}."
        else:
            instruction = f"Translate to {target_name}."

        payload = {
            "model": ANTHROPIC_MODEL, "max_tokens": 1024,
            "messages": [{"role": "user",
                          "content": f"{instruction} Output only the translation, no explanations.\n\n{chunk.text}"}],
        }
        headers = {
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        async with semaphore:
            try:
                resp = await client.post(ANTHROPIC_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                chunk.translation = data["content"][0]["text"].strip()
                chunk.source = "cloud"
                chunk.quality_score = 1.0
            except Exception as e:
                self.on_log(f"  [chunk {chunk.index}] cloud error: {e}")

        return chunk

    async def process_file(self, job: FileJob, target: str, source: str,
                           workers: int, chunk_size: int, quality_threshold: float,
                           use_fallback: bool, output_dir: Path | None) -> str | None:
        if self._cancelled:
            job.status = "cancelled"
            return None

        job.status = "running"
        start = time.perf_counter()

        try:
            text = job.path.read_text(encoding="utf-8")
        except Exception as e:
            job.status = "error"
            job.error_msg = str(e)
            self.on_log(f"ERROR reading {job.path.name}: {e}")
            return None

        if not text.strip():
            job.status = "done"
            self.on_log(f"SKIP (empty): {job.path.name}")
            return ""

        job.chars = len(text)
        chunks = split_into_chunks(text, max_chars=chunk_size)
        job.total_chunks = len(chunks)
        job.done_chunks = 0
        self.on_progress(job)
        self.on_log(f"START: {job.path.name} — {len(text)} chars, {len(chunks)} chunks")

        # Local parallel inference
        import httpx
        semaphore = asyncio.Semaphore(workers)
        async with httpx.AsyncClient(
            base_url=OLLAMA_URL,
            timeout=httpx.Timeout(120.0, connect=5.0),
            limits=httpx.Limits(max_connections=workers + 4,
                                max_keepalive_connections=workers),
        ) as client:
            tasks = [self.translate_chunk_local(client, c, target, source, semaphore, job)
                     for c in chunks]
            await asyncio.gather(*tasks)

        if self._cancelled:
            job.status = "cancelled"
            return None

        # Quality check
        job.local_ok = sum(1 for c in chunks if c.quality_score >= quality_threshold)
        low_q = [c for c in chunks if c.quality_score < quality_threshold]

        # Cloud fallback
        if use_fallback and low_q and ANTHROPIC_API_KEY:
            self.on_log(f"  Cloud fallback: {len(low_q)} chunks")
            cloud_sem = asyncio.Semaphore(4)
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as cloud_client:
                tasks = [self.translate_chunk_cloud(cloud_client, c, target, source, cloud_sem)
                         for c in low_q]
                await asyncio.gather(*tasks)
            job.cloud_used = sum(1 for c in low_q if c.source == "cloud")

        job.failed = sum(1 for c in chunks if not c.translation)

        # Merge
        sorted_chunks = sorted(chunks, key=lambda c: c.index)
        result = "\n\n".join(c.translation for c in sorted_chunks if c.translation)

        job.elapsed_s = time.perf_counter() - start
        job.status = "done"

        # Save
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            out_path = output_dir / f"{job.path.stem}.{target}{job.path.suffix}"
            out_path.write_text(result, encoding="utf-8")
            self.on_log(f"DONE: {job.path.name} → {out_path.name}  "
                        f"({job.elapsed_s:.1f}s, {job.chars / job.elapsed_s:.0f} chars/s)")
        else:
            self.on_log(f"DONE: {job.path.name}  "
                        f"({job.elapsed_s:.1f}s, {job.chars / job.elapsed_s:.0f} chars/s)")

        self.on_progress(job)
        return result

    async def run_batch(self, jobs: list[FileJob], target: str, source: str,
                        workers: int, chunk_size: int, quality_threshold: float,
                        use_fallback: bool, output_dir: Path | None):
        self._cancelled = False
        self._paused = False
        self._pause_event.set()

        for job in jobs:
            if self._cancelled:
                job.status = "cancelled"
                continue
            await self.process_file(job, target, source, workers, chunk_size,
                                    quality_threshold, use_fallback, output_dir)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class BatchTranslatorApp:
    BG = "#0f1117"
    SURFACE = "#1a1d27"
    PANEL = "#2a2d3a"
    BORDER = "#3a3d4a"
    TEXT = "#e4e4e7"
    MUTED = "#71717a"
    ACCENT = "#6366f1"
    GREEN = "#22c55e"
    RED = "#ef4444"
    YELLOW = "#eab308"

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Batch Translator — Ollama + gemma3:1b")
        self.root.geometry("960x680")
        self.root.minsize(760, 520)
        self.root.configure(bg=self.BG)

        self.jobs: list[FileJob] = []
        self.engine: BatchEngine | None = None
        self.running = False

        self._apply_theme()
        self._build_ui()
        self._check_connection()

    def _apply_theme(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", background=self.BG, foreground=self.TEXT, borderwidth=0)
        s.configure("TFrame", background=self.BG)
        s.configure("TLabel", background=self.BG, foreground=self.TEXT, font=("Segoe UI", 10))
        s.configure("Header.TLabel", font=("Segoe UI", 14, "bold"))
        s.configure("Sub.TLabel", foreground=self.MUTED, font=("Segoe UI", 9))
        s.configure("Stat.TLabel", font=("Segoe UI", 20, "bold"))
        s.configure("StatSub.TLabel", foreground=self.MUTED, font=("Segoe UI", 9))
        s.configure("TLabelframe", background=self.BG, foreground=self.TEXT)
        s.configure("TLabelframe.Label", background=self.BG, foreground=self.TEXT,
                     font=("Segoe UI", 10, "bold"))
        s.configure("TCombobox", fieldbackground=self.PANEL, background=self.PANEL,
                     foreground=self.TEXT, arrowcolor=self.TEXT)
        s.configure("TSpinbox", fieldbackground=self.PANEL, background=self.PANEL,
                     foreground=self.TEXT, arrowcolor=self.TEXT)
        s.configure("TCheckbutton", background=self.BG, foreground=self.TEXT)
        s.configure("Go.TButton", background=self.GREEN, foreground="white",
                     font=("Segoe UI", 11, "bold"), padding=(20, 10))
        s.map("Go.TButton", background=[("active", "#16a34a"), ("disabled", self.BORDER)])
        s.configure("Stop.TButton", background=self.RED, foreground="white",
                     font=("Segoe UI", 10, "bold"), padding=(14, 8))
        s.map("Stop.TButton", background=[("active", "#dc2626")])
        s.configure("Pause.TButton", background=self.YELLOW, foreground="#1a1d27",
                     font=("Segoe UI", 10, "bold"), padding=(14, 8))
        s.map("Pause.TButton", background=[("active", "#ca8a04")])
        s.configure("Add.TButton", background=self.ACCENT, foreground="white",
                     font=("Segoe UI", 10), padding=(12, 6))
        s.map("Add.TButton", background=[("active", "#818cf8")])
        s.configure("Flat.TButton", background=self.PANEL, foreground=self.TEXT,
                     font=("Segoe UI", 9), padding=(8, 4))
        s.map("Flat.TButton", background=[("active", self.BORDER)])

        s.configure("Custom.Horizontal.TProgressbar",
                     troughcolor=self.PANEL, background=self.ACCENT,
                     borderwidth=0, thickness=8)

    def _build_ui(self):
        # --- Header ---
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=16, pady=(14, 4))
        ttk.Label(header, text="Batch Translator", style="Header.TLabel").pack(side="left")
        self.conn_label = ttk.Label(header, text="Checking...", style="Sub.TLabel")
        self.conn_label.pack(side="right")

        # --- Settings row ---
        settings = ttk.Frame(self.root)
        settings.pack(fill="x", padx=16, pady=6)

        lang_names_src = [name for name, _ in LANGUAGES]
        lang_names_tgt = [name for name, _ in LANGUAGES[1:]]

        ttk.Label(settings, text="From:").pack(side="left")
        self.source_lang = ttk.Combobox(settings, values=lang_names_src, state="readonly", width=14)
        self.source_lang.set("Auto Detect")
        self.source_lang.pack(side="left", padx=(4, 12))

        ttk.Label(settings, text="To:").pack(side="left")
        self.target_lang = ttk.Combobox(settings, values=lang_names_tgt, state="readonly", width=14)
        self.target_lang.set("Japanese")
        self.target_lang.pack(side="left", padx=(4, 16))

        ttk.Label(settings, text="Workers:").pack(side="left")
        self.workers_var = tk.IntVar(value=8)
        workers_spin = ttk.Spinbox(settings, from_=1, to=32, textvariable=self.workers_var,
                                    width=4, font=("Segoe UI", 10))
        workers_spin.pack(side="left", padx=(4, 12))

        ttk.Label(settings, text="Chunk:").pack(side="left")
        self.chunk_var = tk.IntVar(value=500)
        chunk_spin = ttk.Spinbox(settings, from_=100, to=2000, increment=100,
                                  textvariable=self.chunk_var, width=5, font=("Segoe UI", 10))
        chunk_spin.pack(side="left", padx=(4, 12))

        self.fallback_var = tk.BooleanVar(value=False)
        fb_cb = ttk.Checkbutton(settings, text="Cloud fallback", variable=self.fallback_var)
        fb_cb.pack(side="left", padx=(8, 0))

        # --- File list ---
        file_frame = ttk.Frame(self.root)
        file_frame.pack(fill="both", expand=True, padx=16, pady=6)

        btn_row = ttk.Frame(file_frame)
        btn_row.pack(fill="x", pady=(0, 6))
        ttk.Button(btn_row, text="+ Add Files", style="Add.TButton",
                    command=self._add_files).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="+ Add Folder", style="Add.TButton",
                    command=self._add_folder).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="Clear All", style="Flat.TButton",
                    command=self._clear_files).pack(side="left", padx=(0, 6))

        self.output_label = ttk.Label(btn_row, text="Output: (same folder)", style="Sub.TLabel")
        self.output_label.pack(side="right", padx=(0, 6))
        ttk.Button(btn_row, text="Set Output", style="Flat.TButton",
                    command=self._set_output_dir).pack(side="right")
        self.output_dir: Path | None = None

        # Treeview for file list
        tree_frame = ttk.Frame(file_frame)
        tree_frame.pack(fill="both", expand=True)

        cols = ("file", "size", "chunks", "progress", "status", "speed")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=8)
        self.tree.heading("file", text="File")
        self.tree.heading("size", text="Size")
        self.tree.heading("chunks", text="Chunks")
        self.tree.heading("progress", text="Progress")
        self.tree.heading("status", text="Status")
        self.tree.heading("speed", text="Speed")
        self.tree.column("file", width=250)
        self.tree.column("size", width=80, anchor="e")
        self.tree.column("chunks", width=80, anchor="center")
        self.tree.column("progress", width=100, anchor="center")
        self.tree.column("status", width=90, anchor="center")
        self.tree.column("speed", width=100, anchor="e")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # --- Stats bar ---
        stats_frame = ttk.Frame(self.root)
        stats_frame.pack(fill="x", padx=16, pady=4)

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(stats_frame, variable=self.progress_var,
                                             maximum=100, style="Custom.Horizontal.TProgressbar")
        self.progress_bar.pack(fill="x", pady=(0, 6))

        stat_row = ttk.Frame(stats_frame)
        stat_row.pack(fill="x")
        for col in range(5):
            stat_row.columnconfigure(col, weight=1)

        self.stat_files = self._make_stat(stat_row, "Files", "0 / 0", 0)
        self.stat_chunks = self._make_stat(stat_row, "Chunks", "0 / 0", 1)
        self.stat_chars = self._make_stat(stat_row, "Chars", "0", 2)
        self.stat_speed = self._make_stat(stat_row, "Chars/sec", "-", 3)
        self.stat_eta = self._make_stat(stat_row, "ETA", "-", 4)

        # --- Log ---
        log_frame = ttk.LabelFrame(self.root, text="Log")
        log_frame.pack(fill="x", padx=16, pady=(4, 6))
        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=6, wrap="word", font=("Consolas", 9),
            bg=self.PANEL, fg=self.TEXT, relief="flat", padx=8, pady=6,
            state="disabled",
        )
        self.log_text.pack(fill="x")

        # --- Bottom buttons ---
        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", padx=16, pady=(2, 14))

        self.go_btn = ttk.Button(bottom, text="Start Batch Translation",
                                  style="Go.TButton", command=self._start)
        self.go_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.pause_btn = ttk.Button(bottom, text="Pause", style="Pause.TButton",
                                     command=self._toggle_pause, state="disabled")
        self.pause_btn.pack(side="left", padx=(0, 6))

        self.stop_btn = ttk.Button(bottom, text="Cancel", style="Stop.TButton",
                                    command=self._cancel, state="disabled")
        self.stop_btn.pack(side="left")

    def _make_stat(self, parent, label, value, col):
        f = ttk.Frame(parent)
        f.grid(row=0, column=col, sticky="nsew", padx=4)
        val_lbl = ttk.Label(f, text=value, style="Stat.TLabel")
        val_lbl.pack()
        ttk.Label(f, text=label, style="StatSub.TLabel").pack()
        return val_lbl

    # --- File management ---

    def _add_files(self):
        exts = " ".join(f"*{e}" for e in FILE_EXTENSIONS)
        paths = filedialog.askopenfilenames(
            title="Select files to translate",
            filetypes=[("Text files", exts), ("All files", "*.*")],
        )
        for p in paths:
            self._add_job(Path(p))

    def _add_folder(self):
        folder = filedialog.askdirectory(title="Select folder")
        if not folder:
            return
        folder_path = Path(folder)
        for ext in FILE_EXTENSIONS:
            for f in sorted(folder_path.glob(f"*{ext}")):
                self._add_job(f)

    def _add_job(self, path: Path):
        if any(j.path == path for j in self.jobs):
            return
        job = FileJob(path=path, chars=path.stat().st_size)
        self.jobs.append(job)
        self._refresh_tree()

    def _clear_files(self):
        if self.running:
            return
        self.jobs.clear()
        self._refresh_tree()
        self._reset_stats()

    def _set_output_dir(self):
        d = filedialog.askdirectory(title="Select output directory")
        if d:
            self.output_dir = Path(d)
            self.output_label.configure(text=f"Output: {self.output_dir}")

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for job in self.jobs:
            size = self._fmt_size(job.chars)
            if job.total_chunks > 0:
                chunks = f"{job.done_chunks}/{job.total_chunks}"
                pct = f"{job.done_chunks / job.total_chunks * 100:.0f}%"
            else:
                chunks = "-"
                pct = "-"
            speed = f"{job.chars / job.elapsed_s:.0f} c/s" if job.elapsed_s > 0 else "-"
            self.tree.insert("", "end", values=(
                job.path.name, size, chunks, pct, job.status, speed
            ))

    @staticmethod
    def _fmt_size(n: int) -> str:
        if n < 1024:
            return f"{n} B"
        if n < 1024 * 1024:
            return f"{n / 1024:.1f} KB"
        return f"{n / (1024 * 1024):.1f} MB"

    # --- Batch execution ---

    def _get_lang_code(self, combo: ttk.Combobox) -> str:
        name = combo.get()
        for n, code in LANGUAGES:
            if n == name:
                return code
        return ""

    def _start(self):
        if not self.jobs:
            messagebox.showwarning("No files", "Add files or a folder first.")
            return

        target = self._get_lang_code(self.target_lang)
        if not target:
            messagebox.showwarning("No target", "Select a target language.")
            return

        source = self._get_lang_code(self.source_lang)

        # Determine output dir
        output_dir = self.output_dir
        if not output_dir:
            output_dir = self.jobs[0].path.parent / "translated"

        self.output_label.configure(text=f"Output: {output_dir}")

        # Reset jobs
        for job in self.jobs:
            job.status = "pending"
            job.done_chunks = 0
            job.total_chunks = 0
            job.local_ok = 0
            job.cloud_used = 0
            job.failed = 0
            job.elapsed_s = 0.0

        self._refresh_tree()
        self._reset_stats()
        self._log("=" * 50)
        self._log(f"Batch start: {len(self.jobs)} files, {self.workers_var.get()} workers, "
                  f"chunk={self.chunk_var.get()}, target={target}")

        self.running = True
        self.go_btn.configure(state="disabled")
        self.pause_btn.configure(state="normal")
        self.stop_btn.configure(state="normal")

        self.engine = BatchEngine(
            on_progress=lambda job: self.root.after(0, self._on_chunk_done, job),
            on_log=lambda msg: self.root.after(0, self._log, msg),
        )

        self._batch_start_time = time.perf_counter()

        def run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    self.engine.run_batch(
                        self.jobs, target, source,
                        self.workers_var.get(), self.chunk_var.get(),
                        0.6, self.fallback_var.get(), output_dir,
                    )
                )
            except Exception as e:
                self.root.after(0, self._log, f"ERROR: {e}")
            finally:
                loop.close()
                self.root.after(0, self._on_batch_done)

        threading.Thread(target=run, daemon=True).start()

    def _toggle_pause(self):
        if not self.engine:
            return
        if self.engine.is_paused:
            self.engine.resume()
            self.pause_btn.configure(text="Pause")
            self._log("Resumed")
        else:
            self.engine.pause()
            self.pause_btn.configure(text="Resume")
            self._log("Paused")

    def _cancel(self):
        if self.engine:
            self.engine.cancel()
            self._log("Cancelling...")

    def _on_chunk_done(self, job: FileJob):
        self._refresh_tree()
        self._update_stats()

    def _on_batch_done(self):
        self.running = False
        self.go_btn.configure(state="normal")
        self.pause_btn.configure(state="disabled")
        self.stop_btn.configure(state="disabled")
        self.pause_btn.configure(text="Pause")

        elapsed = time.perf_counter() - self._batch_start_time
        done = sum(1 for j in self.jobs if j.status == "done")
        total_chars = sum(j.chars for j in self.jobs if j.status == "done")
        self._log("=" * 50)
        self._log(f"Batch complete: {done}/{len(self.jobs)} files, "
                  f"{total_chars} chars in {elapsed:.1f}s "
                  f"({total_chars / elapsed:.0f} chars/s)" if elapsed > 0 else "Done")
        self._refresh_tree()
        self._update_stats()
        self.progress_var.set(100)

    def _update_stats(self):
        total_files = len(self.jobs)
        done_files = sum(1 for j in self.jobs if j.status == "done")
        total_chunks = sum(j.total_chunks for j in self.jobs)
        done_chunks = sum(j.done_chunks for j in self.jobs)
        total_chars = sum(j.chars for j in self.jobs)
        done_chars = sum(j.chars for j in self.jobs if j.status == "done")

        self.stat_files.configure(text=f"{done_files} / {total_files}")
        self.stat_chunks.configure(text=f"{done_chunks} / {total_chunks}")
        self.stat_chars.configure(text=f"{done_chars:,}")

        elapsed = time.perf_counter() - self._batch_start_time if hasattr(self, '_batch_start_time') else 0
        if elapsed > 0 and done_chars > 0:
            cps = done_chars / elapsed
            self.stat_speed.configure(text=f"{cps:,.0f}")
            remaining_chars = total_chars - done_chars
            if cps > 0:
                eta_s = remaining_chars / cps
                if eta_s < 60:
                    self.stat_eta.configure(text=f"{eta_s:.0f}s")
                elif eta_s < 3600:
                    self.stat_eta.configure(text=f"{eta_s / 60:.1f}m")
                else:
                    self.stat_eta.configure(text=f"{eta_s / 3600:.1f}h")
            else:
                self.stat_eta.configure(text="-")
        else:
            self.stat_speed.configure(text="-")
            self.stat_eta.configure(text="-")

        if total_chunks > 0:
            self.progress_var.set(done_chunks / total_chunks * 100)

    def _reset_stats(self):
        self.stat_files.configure(text="0 / 0")
        self.stat_chunks.configure(text="0 / 0")
        self.stat_chars.configure(text="0")
        self.stat_speed.configure(text="-")
        self.stat_eta.configure(text="-")
        self.progress_var.set(0)

    # --- Log ---

    def _log(self, msg: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # --- Connection check ---

    def _check_connection(self):
        def check():
            import urllib.request
            try:
                req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read())
                    models = [m["name"] for m in data.get("models", [])]
                    found = any(MODEL_NAME in m for m in models)
                    self.root.after(0, lambda: self.conn_label.configure(
                        text=f"Ollama OK — model {'loaded' if found else 'not found: run make setup'}",
                        foreground=self.GREEN if found else self.YELLOW,
                    ))
            except Exception:
                self.root.after(0, lambda: self.conn_label.configure(
                    text="Ollama not running — start with: ollama serve",
                    foreground=self.RED,
                ))
        threading.Thread(target=check, daemon=True).start()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = BatchTranslatorApp()
    app.run()

"""
High-throughput batch translation pipeline.

Architecture:
  1. Document → chunk splitting
  2. Parallel local inference (Ollama, concurrent requests)
  3. Quality scoring per chunk
  4. Low-quality chunks → Cloud API fallback (Claude Batch API)
  5. Merge results

Usage:
    python batch_pipeline.py input.txt --target ja --workers 8
    python batch_pipeline.py docs/ --target en --workers 16 --fallback claude
"""

import argparse
import asyncio
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL_NAME = os.environ.get("MODEL_NAME", "translator")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

LANG_NAMES = {
    "ja": "Japanese", "en": "English", "zh": "Chinese",
    "ko": "Korean", "fr": "French", "de": "German",
    "es": "Spanish", "pt": "Portuguese", "it": "Italian",
    "ru": "Russian", "ar": "Arabic", "th": "Thai",
    "vi": "Vietnamese", "id": "Indonesian", "nl": "Dutch",
}

QUALITY_THRESHOLD = 0.6


# ---------------------------------------------------------------------------
# 1. Chunking
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    index: int
    text: str
    translation: str = ""
    quality_score: float = 0.0
    source: str = "local"  # "local" or "cloud"


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


# ---------------------------------------------------------------------------
# 2. Local parallel inference (Ollama)
# ---------------------------------------------------------------------------

async def translate_chunk_local(
    client: httpx.AsyncClient,
    chunk: Chunk,
    target: str,
    source: str | None,
    semaphore: asyncio.Semaphore,
) -> Chunk:
    target_name = LANG_NAMES.get(target, target)
    if source:
        source_name = LANG_NAMES.get(source, source)
        prompt = f"Translate from {source_name} to {target_name}. Output only the translation:\n\n{chunk.text}"
    else:
        prompt = f"Translate to {target_name}. Output only the translation:\n\n{chunk.text}"

    payload = {
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
    }

    async with semaphore:
        try:
            resp = await client.post("/api/generate", json=payload)
            resp.raise_for_status()
            chunk.translation = resp.json()["response"].strip()
            chunk.source = "local"
        except Exception as e:
            chunk.translation = ""
            chunk.quality_score = 0.0
            print(f"  [chunk {chunk.index}] local error: {e}", file=sys.stderr)

    return chunk


async def translate_all_local(
    chunks: list[Chunk],
    target: str,
    source: str | None,
    max_workers: int,
) -> list[Chunk]:
    semaphore = asyncio.Semaphore(max_workers)

    async with httpx.AsyncClient(
        base_url=OLLAMA_URL,
        timeout=httpx.Timeout(120.0, connect=5.0),
        limits=httpx.Limits(max_connections=max_workers + 4, max_keepalive_connections=max_workers),
    ) as client:
        tasks = [
            translate_chunk_local(client, c, target, source, semaphore)
            for c in chunks
        ]
        return await asyncio.gather(*tasks)


# ---------------------------------------------------------------------------
# 3. Quality scoring
# ---------------------------------------------------------------------------

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

    repeated = re.findall(r'(.{10,}?)\1{2,}', chunk.translation)
    if repeated:
        score -= 0.3

    if any(marker in chunk.translation.lower() for marker in
           ["here is", "translation:", "note:", "i cannot", "i can't"]):
        score -= 0.4

    return max(0.0, min(1.0, score))


def evaluate_quality(chunks: list[Chunk]) -> list[Chunk]:
    for c in chunks:
        c.quality_score = score_quality(c)
    return chunks


# ---------------------------------------------------------------------------
# 4. Cloud API fallback (Claude)
# ---------------------------------------------------------------------------

async def translate_chunk_cloud(
    client: httpx.AsyncClient,
    chunk: Chunk,
    target: str,
    source: str | None,
    semaphore: asyncio.Semaphore,
) -> Chunk:
    target_name = LANG_NAMES.get(target, target)
    if source:
        source_name = LANG_NAMES.get(source, source)
        instruction = f"Translate from {source_name} to {target_name}."
    else:
        instruction = f"Translate to {target_name}."

    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 1024,
        "messages": [
            {
                "role": "user",
                "content": f"{instruction} Output only the translation, no explanations.\n\n{chunk.text}",
            }
        ],
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
            print(f"  [chunk {chunk.index}] cloud error: {e}", file=sys.stderr)

    return chunk


async def fallback_cloud(
    chunks: list[Chunk],
    target: str,
    source: str | None,
    max_cloud_workers: int = 4,
) -> list[Chunk]:
    low_quality = [c for c in chunks if c.quality_score < QUALITY_THRESHOLD]

    if not low_quality:
        return chunks

    if not ANTHROPIC_API_KEY:
        print(f"  Warning: {len(low_quality)} low-quality chunks but ANTHROPIC_API_KEY not set. Skipping fallback.",
              file=sys.stderr)
        return chunks

    print(f"  Cloud fallback: {len(low_quality)}/{len(chunks)} chunks", file=sys.stderr)

    semaphore = asyncio.Semaphore(max_cloud_workers)
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        tasks = [
            translate_chunk_cloud(client, c, target, source, semaphore)
            for c in low_quality
        ]
        await asyncio.gather(*tasks)

    return chunks


# ---------------------------------------------------------------------------
# 5. Merge
# ---------------------------------------------------------------------------

def merge_chunks(chunks: list[Chunk]) -> str:
    sorted_chunks = sorted(chunks, key=lambda c: c.index)
    return "\n\n".join(c.translation for c in sorted_chunks if c.translation)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

@dataclass
class PipelineStats:
    total_chunks: int = 0
    local_ok: int = 0
    cloud_fallback: int = 0
    failed: int = 0
    total_chars: int = 0
    elapsed_s: float = 0.0
    chars_per_sec: float = 0.0


async def run_pipeline(
    text: str,
    target: str,
    source: str | None = None,
    max_workers: int = 8,
    chunk_size: int = 500,
    use_fallback: bool = True,
) -> tuple[str, PipelineStats]:
    start = time.perf_counter()
    stats = PipelineStats()

    # 1. Chunk
    chunks = split_into_chunks(text, max_chars=chunk_size)
    stats.total_chunks = len(chunks)
    stats.total_chars = sum(len(c.text) for c in chunks)
    print(f"  Chunks: {len(chunks)} (avg {stats.total_chars // max(len(chunks), 1)} chars)", file=sys.stderr)

    # 2. Parallel local inference
    print(f"  Local inference: {max_workers} workers...", file=sys.stderr)
    chunks = await translate_all_local(chunks, target, source, max_workers)

    # 3. Quality scoring
    chunks = evaluate_quality(chunks)
    stats.local_ok = sum(1 for c in chunks if c.quality_score >= QUALITY_THRESHOLD)
    low_q = stats.total_chunks - stats.local_ok
    print(f"  Quality: {stats.local_ok}/{stats.total_chunks} passed (threshold={QUALITY_THRESHOLD})", file=sys.stderr)

    # 4. Cloud fallback
    if use_fallback and low_q > 0:
        chunks = await fallback_cloud(chunks, target, source)
        stats.cloud_fallback = sum(1 for c in chunks if c.source == "cloud")

    stats.failed = sum(1 for c in chunks if not c.translation)

    # 5. Merge
    result = merge_chunks(chunks)

    stats.elapsed_s = time.perf_counter() - start
    stats.chars_per_sec = stats.total_chars / stats.elapsed_s if stats.elapsed_s > 0 else 0

    return result, stats


# ---------------------------------------------------------------------------
# File/directory handling
# ---------------------------------------------------------------------------

async def translate_file(
    path: Path,
    target: str,
    source: str | None,
    max_workers: int,
    chunk_size: int,
    use_fallback: bool,
    output_dir: Path | None,
):
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        print(f"  Skipping empty file: {path}", file=sys.stderr)
        return

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  File: {path} ({len(text)} chars)", file=sys.stderr)

    result, stats = await run_pipeline(text, target, source, max_workers, chunk_size, use_fallback)

    if output_dir:
        out_path = output_dir / f"{path.stem}.{target}{path.suffix}"
        out_path.write_text(result, encoding="utf-8")
        print(f"  Output: {out_path}", file=sys.stderr)
    else:
        print(result)

    print(f"  Stats: {stats.elapsed_s:.1f}s | {stats.chars_per_sec:.0f} chars/s | "
          f"local={stats.local_ok} cloud={stats.cloud_fallback} failed={stats.failed}",
          file=sys.stderr)


async def main_async(args):
    input_path = Path(args.input)
    output_dir = Path(args.output) if args.output else None

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

    if input_path.is_dir():
        files = sorted(input_path.glob("*.txt")) + sorted(input_path.glob("*.md"))
        if not files:
            print(f"No .txt/.md files in {input_path}", file=sys.stderr)
            sys.exit(1)
        print(f"Batch: {len(files)} files, {args.workers} workers", file=sys.stderr)
        for f in files:
            await translate_file(f, args.target, args.source, args.workers,
                                 args.chunk_size, not args.no_fallback, output_dir)
    else:
        await translate_file(input_path, args.target, args.source, args.workers,
                             args.chunk_size, not args.no_fallback, output_dir)


def main():
    parser = argparse.ArgumentParser(
        description="High-throughput batch translation pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python batch_pipeline.py document.txt --target ja --workers 8
  python batch_pipeline.py docs/ --target en --output translated/ --workers 16
  python batch_pipeline.py book.txt --target ja --chunk-size 300 --no-fallback
        """,
    )
    parser.add_argument("input", help="Input file or directory")
    parser.add_argument("--target", "-t", required=True, help="Target language code")
    parser.add_argument("--source", "-s", help="Source language code (auto-detect if omitted)")
    parser.add_argument("--workers", "-w", type=int, default=8, help="Parallel workers (default: 8)")
    parser.add_argument("--chunk-size", type=int, default=500, help="Max chars per chunk (default: 500)")
    parser.add_argument("--output", "-o", help="Output directory (stdout if omitted)")
    parser.add_argument("--no-fallback", action="store_true", help="Skip cloud API fallback")
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()

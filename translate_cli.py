#!/usr/bin/env python3
"""
Fast translation CLI client using Ollama.
Supports interactive mode, clipboard, and piped input.

Usage:
    python translate_cli.py ja "Hello world"
    python translate_cli.py -i ja          # interactive mode
    echo "Hello" | python translate_cli.py ja
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error

OLLAMA_URL = "http://localhost:11434"
MODEL_NAME = "translator"

LANG_NAMES = {
    "ja": "Japanese", "en": "English", "zh": "Chinese",
    "ko": "Korean", "fr": "French", "de": "German",
    "es": "Spanish", "pt": "Portuguese", "it": "Italian",
    "ru": "Russian", "ar": "Arabic", "th": "Thai",
    "vi": "Vietnamese", "id": "Indonesian", "nl": "Dutch",
}


def translate(text: str, target: str, source: str | None = None, stream: bool = False) -> str:
    target_name = LANG_NAMES.get(target, target)
    if source:
        source_name = LANG_NAMES.get(source, source)
        prompt = f"Translate from {source_name} to {target_name}. Output only the translation:\n\n{text}"
    else:
        prompt = f"Translate to {target_name}. Output only the translation:\n\n{text}"

    payload = json.dumps({
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": stream,
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

    if stream:
        result = []
        with urllib.request.urlopen(req) as resp:
            for line in resp:
                data = json.loads(line)
                token = data.get("response", "")
                print(token, end="", flush=True)
                result.append(token)
            print()
        return "".join(result).strip()

    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return data["response"].strip()


def interactive_mode(target: str, source: str | None, stream: bool):
    target_name = LANG_NAMES.get(target, target)
    print(f"Interactive translation → {target_name}")
    print("Type text to translate. Empty line or Ctrl+D to exit.\n")

    while True:
        try:
            text = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        if not text:
            break

        start = time.perf_counter()
        result = translate(text, target, source, stream=stream)
        elapsed = (time.perf_counter() - start) * 1000

        if not stream:
            print(result)
        print(f"  [{elapsed:.0f}ms]\n")


def main():
    parser = argparse.ArgumentParser(description="Fast local translation via Ollama")
    parser.add_argument("target", help="Target language code (ja, en, zh, ko, fr, de, es, ...)")
    parser.add_argument("text", nargs="*", help="Text to translate (or use stdin/interactive)")
    parser.add_argument("-s", "--source", help="Source language code (auto-detect if omitted)")
    parser.add_argument("-i", "--interactive", action="store_true", help="Interactive mode")
    parser.add_argument("--stream", action="store_true", help="Stream output token by token")
    parser.add_argument("--langs", action="store_true", help="List supported languages")
    args = parser.parse_args()

    if args.langs:
        for code, name in sorted(LANG_NAMES.items()):
            print(f"  {code:4s} {name}")
        return

    if args.interactive:
        interactive_mode(args.target, args.source, args.stream)
        return

    if args.text:
        text = " ".join(args.text)
    elif not sys.stdin.isatty():
        text = sys.stdin.read().strip()
    else:
        parser.print_help()
        sys.exit(1)

    if not text:
        print("Error: No text provided", file=sys.stderr)
        sys.exit(1)

    start = time.perf_counter()
    result = translate(text, args.target, args.source, stream=args.stream)
    elapsed = (time.perf_counter() - start) * 1000

    if not args.stream:
        print(result)

    print(f"  [{elapsed:.0f}ms]", file=sys.stderr)


if __name__ == "__main__":
    main()

#!/usr/bin/env bash
set -euo pipefail

MODEL_NAME="translator"
BASE_MODEL="gemma3:1b"
OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"

show_help() {
    cat <<'HELP'
Usage: ./translate.sh [OPTIONS] <target_lang> <text>
       echo "text" | ./translate.sh [OPTIONS] <target_lang>

Fast local translation powered by Ollama + gemma3:1b

Arguments:
  target_lang   Target language (e.g. ja, en, zh, ko, fr, de, es)
  text          Text to translate (or pipe via stdin)

Options:
  -s, --setup       Pull base model and create translator model
  -f, --file FILE   Translate a file
  -b, --batch FILE  Batch translate (one sentence per line)
  -h, --help        Show this help

Examples:
  ./translate.sh --setup
  ./translate.sh ja "Hello, how are you?"
  ./translate.sh en "こんにちは"
  echo "Bonjour" | ./translate.sh ja
  ./translate.sh -f document.txt en
HELP
}

setup() {
    echo "==> Pulling ${BASE_MODEL}..."
    ollama pull "${BASE_MODEL}"
    echo "==> Creating translator model..."
    ollama create "${MODEL_NAME}" -f Modelfile
    echo "==> Done! Model '${MODEL_NAME}' is ready."
    echo "==> Test: ./translate.sh ja \"Hello, world!\""
}

translate() {
    local target_lang="$1"
    local text="$2"

    local prompt="Translate the following text to ${target_lang}. Output only the translation:

${text}"

    ollama run "${MODEL_NAME}" "${prompt}" 2>/dev/null
}

translate_file() {
    local file="$1"
    local target_lang="$2"

    if [[ ! -f "$file" ]]; then
        echo "Error: File not found: $file" >&2
        exit 1
    fi

    local content
    content=$(<"$file")
    translate "$target_lang" "$content"
}

batch_translate() {
    local file="$1"
    local target_lang="$2"

    if [[ ! -f "$file" ]]; then
        echo "Error: File not found: $file" >&2
        exit 1
    fi

    while IFS= read -r line; do
        [[ -z "$line" ]] && echo && continue
        translate "$target_lang" "$line"
    done < "$file"
}

# --- Main ---

if [[ $# -eq 0 ]]; then
    show_help
    exit 0
fi

case "${1:-}" in
    -h|--help)
        show_help
        exit 0
        ;;
    -s|--setup)
        setup
        exit 0
        ;;
    -f|--file)
        [[ $# -lt 3 ]] && { echo "Usage: ./translate.sh -f FILE TARGET_LANG" >&2; exit 1; }
        translate_file "$2" "$3"
        exit 0
        ;;
    -b|--batch)
        [[ $# -lt 3 ]] && { echo "Usage: ./translate.sh -b FILE TARGET_LANG" >&2; exit 1; }
        batch_translate "$2" "$3"
        exit 0
        ;;
esac

target_lang="$1"
shift

if [[ $# -gt 0 ]]; then
    text="$*"
else
    text=$(cat)
fi

translate "$target_lang" "$text"

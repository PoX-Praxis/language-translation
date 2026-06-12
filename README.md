# language-translation

Ollama + gemma3:1b ベースの超高速ローカル翻訳ツール。

## セットアップ

```bash
# 1. Ollama インストール (未インストールの場合)
curl -fsSL https://ollama.com/install.sh | sh

# 2. ベースモデル取得 & 翻訳モデル作成
./translate.sh --setup
```

## CLI で翻訳

```bash
# 英語 → 日本語
./translate.sh ja "Hello, how are you?"

# 日本語 → 英語
./translate.sh en "お疲れ様です"

# パイプ入力
echo "Bonjour le monde" | ./translate.sh ja

# ファイル翻訳
./translate.sh -f document.txt ja

# バッチ翻訳 (1行1文)
./translate.sh -b sentences.txt en
```

## API サーバー

```bash
pip install -r requirements.txt
python translate_api.py
```

### エンドポイント

```bash
# 単文翻訳
curl -X POST http://localhost:8000/translate \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello world", "target": "ja"}'

# ストリーミング翻訳
curl -X POST http://localhost:8000/translate \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello world", "target": "ja", "stream": true}'

# バッチ翻訳
curl -X POST http://localhost:8000/translate/batch \
  -H "Content-Type: application/json" \
  -d '{"texts": ["Hello", "Goodbye"], "target": "ja"}'

# ヘルスチェック
curl http://localhost:8000/health
```

## 高速化のポイント

| 設定 | 値 | 理由 |
|------|-----|------|
| モデル | gemma3:1b | 1Bパラメータで超軽量・高速 |
| num_ctx | 1024 | コンテキスト長を最小限に抑えメモリ節約 |
| num_predict | 512 | 翻訳に必要十分な出力長 |
| temperature | 0.1 | 低温で安定した出力 |
| top_k | 20 | 候補を絞り推論高速化 |
| num_thread | 4 | CPUスレッド数 (環境に合わせて調整) |

## 対応言語

ja (日本語), en (English), zh (中文), ko (한국어), fr (Français), de (Deutsch), es (Español), pt (Português), it (Italiano), ru (Русский), ar (العربية), th (ไทย), vi (Tiếng Việt), id (Bahasa Indonesia), nl (Nederlands)

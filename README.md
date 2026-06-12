# Screen Translator

画面の指定領域内のテキストを検出し、選択した言語に翻訳するWindowsデスクトップアプリです。

## 機能

- **画面キャプチャ枠**: 青い半透明の枠で翻訳対象の領域を指定
- **枠の移動・リサイズ**: ドラッグで移動、右下のグリップでリサイズ
- **リアルタイム翻訳**: Start/Stopボタンで翻訳の開始・停止
- **多言語対応**: 16言語から翻訳先言語を選択可能

## 必要条件

- Python 3.9+
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) (Windows用インストーラーからインストール)
  - インストール時に必要な言語パックを選択してください
  - インストール後、`tesseract` にPATHを通すか、スクリプト内でパスを指定してください

## インストール

```bash
pip install -r requirements.txt
```

## 使い方

```bash
python app.py
```

1. アプリを起動すると、青い半透明の**キャプチャ枠**とコントロールパネルが表示されます
2. キャプチャ枠を翻訳したいテキストの上に移動・リサイズします
3. コントロールパネルで**翻訳先言語**を選択します
4. **Start** ボタンをクリックすると、定期的に枠内のテキストをOCRで読み取り翻訳します
5. **Stop** ボタンで停止します

## 対応言語

日本語, English, 中文, 한국어, Français, Deutsch, Español, Português, Русский, العربية, हिन्दी, Italiano, Nederlands, Türkçe, Tiếng Việt, ไทย

## 注意事項

- Tesseract OCRの認識精度はフォントや解像度に依存します
- 翻訳にはインターネット接続が必要です（Google Translate API使用）
- キャプチャ間隔は1〜30秒の間で設定できます

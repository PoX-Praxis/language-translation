# Screen Translator

画面上のテキストをリアルタイムで検出・翻訳し、元の位置にそのまま表示するWindowsデスクトップアプリです。画像や図のレイアウトを崩さず、テキスト部分のみを翻訳して置き換えます。

## 機能

- **画面キャプチャ枠**: グレーの枠で翻訳対象の領域を指定
- **In-place翻訳**: テキスト部分のみ検出し、元の位置に翻訳文を表示（画像・図はそのまま）
- **枠の移動・リサイズ**: ドラッグで移動、右下のグリップでリサイズ
- **ツールバー**: 枠の右上に言語選択・フォントサイズ・Start/Stop・Translateボタン
- **フォントサイズ調整**: 翻訳表示後もリアルタイムでサイズ変更可能
- **多言語対応**: 16言語から翻訳先言語を選択可能
- **DeepL翻訳**: 高品質な翻訳エンジン（DeepL API Free / Pro対応）

## インストール方法

### 方法1: インストーラ（推奨）

1. `ScreenTranslator_Setup.exe` をダウンロード
2. インストーラを実行
3. デスクトップのショートカットから起動

### 方法2: Python環境から実行

#### 必要条件

- Python 3.9+
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)
- [DeepL API Key](https://www.deepl.com/pro-api)（Free plan可）

```bash
pip install -r requirements.txt
python app.py
```

## 初回セットアップ

初回起動時にDeepL APIキーの入力画面が表示されます。

1. [DeepL API](https://www.deepl.com/pro-api) でアカウント作成（無料プランあり）
2. APIキーをコピー
3. 入力画面に貼り付けてOK

設定は `%APPDATA%\ScreenTranslator\config.json` に保存されます。

## 使い方

1. アプリを起動すると**キャプチャ枠**と右上の**ツールバー**が表示されます
2. キャプチャ枠を翻訳したいテキストの上に移動・リサイズします
3. ツールバーで**翻訳先言語**を選択します
4. **Start** で自動スキャン開始、**Translate** で手動翻訳
5. 翻訳表示をクリックすると消えて再スキャンします
6. **Stop** で停止、**X** で終了

## 対応言語

日本語, English, 中文, 한국어, Français, Deutsch, Español, Português, Русский, العربية, हिन्दी, Italiano, Nederlands, Türkçe, Tiếng Việt, ไทย

## ビルド方法（開発者向け）

### exe作成

```bash
build.bat
```

### インストーラ作成

1. [Inno Setup](https://jrsoftware.org/isinfo.php) をインストール
2. `build.bat` でexeをビルド
3. Inno Setupで `installer.iss` をコンパイル

## 注意事項

- Tesseract OCRの認識精度はフォントや解像度に依存します
- 翻訳にはインターネット接続が必要です（DeepL API使用）
- DeepL Free APIは月50万文字まで無料です

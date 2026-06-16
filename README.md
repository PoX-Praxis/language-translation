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
- **2モード対応**: RT（リアルタイム・ゲーム向け）/ STILL（PDF・画像向け高精度）
- **三段フォールバック**: UI Automation → PDF直接抽出 → OCR の優先順で最適ルートを自動選択
- **数値保護**: グラフの金額・年号などを翻訳で破壊しない

## インストール方法

### 方法1: インストーラ（推奨）

1. `ScreenTranslator_Setup.exe` をダウンロード
2. インストーラを実行
3. デスクトップのショートカットから起動

### 方法2: Python環境から実行

#### 必要条件

- Python 3.9+
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)（日本語データ含む、下記参照）
- [DeepL API Key](https://www.deepl.com/pro-api)（Free plan可）

```bash
pip install -r requirements.txt
python app.py
```

#### Tesseract 日本語OCRデータの導入

日本語を含む画面をOCRするには `jpn` 言語データが必要です。

- **Windowsインストーラ**: インストール時に「Additional language data」で「Japanese」にチェック
- **手動**: [tessdata](https://github.com/tesseract-ocr/tessdata) から `jpn.traineddata` をダウンロードし、Tesseractの `tessdata` フォルダに配置

## 初回セットアップ

### DeepL APIキーの設定

以下の優先順で読み込まれます:

1. 環境変数 `DEEPL_API_KEY`
2. 設定ファイル `%APPDATA%\ScreenTranslator\config.json` の `deepl_api_key`
3. どちらも未設定の場合、初回起動時に入力ダイアログが表示されます

入力したキーは `%APPDATA%\ScreenTranslator\config.json` に保存されます。

## 使い方

1. アプリを起動すると**キャプチャ枠**と右上の**ツールバー**が表示されます
2. ツールバーで**モード**を選択:
   - **RT**: ゲーム・ソフト向け（リアルタイムポーリング、速度優先）
   - **STILL**: PDF・画像向け（1回高精度処理）
3. キャプチャ枠を翻訳したいテキストの上に移動・リサイズします
4. ツールバーで**翻訳先言語**を選択します
5. **Start** で自動スキャン開始、**Translate** で手動翻訳
6. 翻訳表示をクリックすると消えて再スキャンします
7. **Stop** で停止、**X** で終了

### テキスト取得の優先順位

アプリは以下の順でテキスト取得を試み、最も精度の高い方法を自動選択します:

1. **UI Automation**: ウィンドウのアクセシビリティAPIからテキスト＋座標を直接取得（OCR不要・最高精度）
2. **OCR（Tesseract）**: 画面キャプチャから画像認識（ゲーム・独自描画アプリ向け）

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

## オプション機能

### PDF直接テキスト抽出

テキストPDFからOCRを使わず直接テキスト＋座標を抽出します。OCR誤認識ゼロ。

```bash
pip install PyMuPDF
```

### UI Automation（Windows）

ウィンドウのアクセシビリティAPIからテキストを直接取得します。ブラウザ・Office等で高精度。

```bash
pip install uiautomation
```

### ローカルLLM OCR（上級者向け）

Tesseractの認識精度が低いブロックを、ローカルVLM（GOT-OCR2.0）で自動的に再OCRする機能です。GPU推奨。

### 有効化

```bash
pip install torch transformers accelerate
```

インストール後、自動的に有効化されます。未インストールの場合はTesseractのみで動作します。

### GPU要件

- CUDA対応GPU（VRAM 4GB以上推奨）
- CPUでも動作しますが低速です

## 注意事項

- OCR前処理（拡大・二値化）により小さい文字の認識精度が向上しています
- Tesseract OCRの認識精度はフォントや解像度に依存します
- 翻訳にはインターネット接続が必要です（DeepL API使用）
- DeepL Free APIは月50万文字まで無料です

@echo off
echo ========================================
echo   Screen Translator - Build
echo ========================================
echo.

REM --- Step 1: Download Tesseract if not present ---
if not exist "tesseract\" (
    echo Downloading Tesseract OCR...
    mkdir tesseract 2>nul

    REM Download Tesseract portable zip from UB-Mannheim
    REM If curl fails, download manually from:
    REM   https://github.com/UB-Mannheim/tesseract/wiki
    REM   and extract to tesseract\ folder
    curl -L -o tesseract-ocr.zip "https://digi.bib.uni-mannheim.de/tesseract/tesseract-ocr-w64-setup-5.5.0.20241111.exe"
    if %errorlevel% neq 0 (
        echo.
        echo [INFO] Auto-download failed.
        echo Please download Tesseract manually:
        echo   1. Go to https://github.com/UB-Mannheim/tesseract/wiki
        echo   2. Download the Windows 64-bit installer
        echo   3. Install to this folder: %CD%\tesseract\
        echo   4. Re-run this script
        echo.
        rmdir tesseract 2>nul
        pause
        exit /b 1
    )

    echo Installing Tesseract to tesseract\ folder...
    tesseract-ocr.zip /S /D=%CD%\tesseract
    del tesseract-ocr.zip 2>nul

    if not exist "tesseract\tesseract.exe" (
        echo.
        echo [INFO] Tesseract installation needs manual setup.
        echo   1. Run the downloaded installer
        echo   2. Set install path to: %CD%\tesseract\
        echo   3. Select language packs: English + Japanese (recommended)
        echo   4. Re-run this script
        echo.
        pause
        exit /b 1
    )
    echo Tesseract installed successfully.
) else (
    echo Tesseract already present in tesseract\ folder.
)

echo.

REM --- Step 2: Install PyInstaller ---
pip install pyinstaller

REM --- Step 3: Build exe ---
echo Building executable...
pyinstaller --noconfirm --onedir --windowed ^
    --name "ScreenTranslator" ^
    --icon "icon.ico" ^
    --add-data "icon.ico;." ^
    --hidden-import "PIL._tkinter_finder" ^
    app.py

REM --- Step 4: Copy Tesseract into dist ---
echo Copying Tesseract into dist...
xcopy /E /I /Y "tesseract" "dist\ScreenTranslator\tesseract"

echo.
echo ========================================
echo   Build complete!
echo ========================================
echo   Output: dist\ScreenTranslator\
echo   Tesseract bundled: dist\ScreenTranslator\tesseract\
echo.
echo   Next: compile installer.iss with Inno Setup
echo ========================================
pause

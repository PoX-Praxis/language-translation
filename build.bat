@echo off
echo ========================================
echo   Screen Translator - Build
echo ========================================
echo.

REM --- Step 0: Convert icon if needed ---
if not exist "icon.ico" (
    if exist "icon_source.png" (
        echo Converting icon...
        python convert_icon.py icon_source.png
    ) else (
        echo [WARNING] icon.ico not found. Build will continue without custom icon.
    )
)

REM --- Step 1: Prepare Tesseract ---
if not exist "tesseract\tesseract.exe" (
    echo Tesseract not found in tesseract\ folder.
    echo Checking system installation...

    if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
        echo Found Tesseract at C:\Program Files\Tesseract-OCR\
        echo Copying to tesseract\ folder...
        xcopy /E /I /Y "C:\Program Files\Tesseract-OCR" "tesseract"
        echo Tesseract copied successfully.
    ) else (
        echo.
        echo [ERROR] Tesseract OCR not found.
        echo Please install Tesseract first:
        echo   1. Go to https://github.com/UB-Mannheim/tesseract/wiki
        echo   2. Download and install the Windows 64-bit version
        echo   3. During install, check "Japanese" in Additional language data
        echo   4. Re-run this script
        echo.
        pause
        exit /b 1
    )
) else (
    echo Tesseract already present in tesseract\ folder.
)

echo.

REM --- Step 2: Install build dependencies ---
echo Installing dependencies...
python -m pip install --upgrade pip
python -m pip install pyinstaller
python -m pip install Pillow pytesseract mss numpy

echo.

REM --- Step 3: Build exe ---
echo Building executable...
if exist "icon.ico" (
    python -m PyInstaller --noconfirm --onedir --windowed ^
        --name "ScreenTranslator" ^
        --icon "icon.ico" ^
        --add-data "icon.ico;." ^
        --hidden-import "PIL._tkinter_finder" ^
        app.py
) else (
    python -m PyInstaller --noconfirm --onedir --windowed ^
        --name "ScreenTranslator" ^
        --hidden-import "PIL._tkinter_finder" ^
        app.py
)

if not exist "dist\ScreenTranslator\ScreenTranslator.exe" (
    echo.
    echo [ERROR] Build failed. ScreenTranslator.exe not created.
    pause
    exit /b 1
)

REM --- Step 4: Copy Tesseract into dist ---
echo Copying Tesseract into dist...
xcopy /E /I /Y "tesseract" "dist\ScreenTranslator\tesseract"

REM --- Step 5: Copy local_ocr.py for optional VLM ---
if exist "local_ocr.py" (
    copy /Y "local_ocr.py" "dist\ScreenTranslator\"
)

REM --- Step 6: Copy icon ---
if exist "icon.ico" (
    copy /Y "icon.ico" "dist\ScreenTranslator\"
)

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

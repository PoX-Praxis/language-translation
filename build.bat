@echo off
echo ========================================
echo   Screen Translator - Build
echo ========================================
echo.

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
        echo [INFO] Tesseract OCR not found.
        echo Please install Tesseract first:
        echo   1. Go to https://github.com/UB-Mannheim/tesseract/wiki
        echo   2. Download and install the Windows 64-bit version
        echo   3. Re-run this script (it will copy from the install location)
        echo.
        echo Or manually copy Tesseract files to: %CD%\tesseract\
        echo.
        pause
        exit /b 1
    )
) else (
    echo Tesseract already present in tesseract\ folder.
)

echo.

REM --- Step 2: Install PyInstaller ---
python -m pip install pyinstaller

REM --- Step 3: Build exe ---
echo Building executable...
python -m PyInstaller --noconfirm --onedir --windowed ^
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

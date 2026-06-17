@echo off
chcp 65001 >nul
echo ========================================
echo   Screen Translator - Full Setup
echo ========================================
echo.

REM --- Check Python ---
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed.
    echo Download from: https://www.python.org/downloads/
    echo Install with "Add Python to PATH" checked.
    pause
    exit /b 1
)
echo [OK] Python found.

REM --- Install core pip packages ---
echo.
echo Installing core packages...
python -m pip install --upgrade pip
python -m pip install Pillow pytesseract mss numpy
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install core packages.
    pause
    exit /b 1
)
echo [OK] Core packages installed.

REM --- Install PyInstaller (for building exe) ---
echo.
echo Installing PyInstaller...
python -m pip install pyinstaller
echo [OK] PyInstaller installed.

REM --- Check Tesseract ---
echo.
echo Checking Tesseract OCR...
set TESS_FOUND=0

if exist "tesseract\tesseract.exe" (
    echo [OK] Tesseract found in tesseract\ folder.
    set TESS_FOUND=1
)

if %TESS_FOUND%==0 (
    if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
        echo [OK] Tesseract found at C:\Program Files\Tesseract-OCR\
        echo Copying to tesseract\ folder...
        xcopy /E /I /Y "C:\Program Files\Tesseract-OCR" "tesseract"
        echo [OK] Tesseract copied.
        set TESS_FOUND=1
    )
)

if %TESS_FOUND%==0 (
    echo.
    echo [WARNING] Tesseract OCR not found.
    echo.
    echo Please install Tesseract:
    echo   1. Download: https://github.com/UB-Mannheim/tesseract/wiki
    echo   2. Run the installer
    echo   3. IMPORTANT: Check "Japanese" in "Additional language data"
    echo   4. Re-run this setup script
    echo.
    echo Opening download page...
    start https://github.com/UB-Mannheim/tesseract/wiki
    pause
    exit /b 1
)

REM --- Check Japanese language data ---
if exist "tesseract\tessdata\jpn.traineddata" (
    echo [OK] Japanese OCR data found.
) else (
    echo [WARNING] Japanese OCR data (jpn.traineddata) not found.
    echo Re-install Tesseract with "Japanese" language data checked.
)

REM --- Convert icon if needed ---
echo.
if not exist "icon.ico" (
    if exist "icon_source.png" (
        echo Converting icon...
        python convert_icon.py icon_source.png
        echo [OK] Icon created.
    ) else (
        echo [INFO] No icon_source.png found. Using default icon.
    )
) else (
    echo [OK] icon.ico found.
)

echo.
echo ========================================
echo   Setup Complete!
echo ========================================
echo.
echo   Run the app:     python app.py
echo   Build exe:       cmd /c build.bat
echo   Build installer: Open installer.iss in Inno Setup
echo.
echo   Inno Setup (for installer):
echo     https://jrsoftware.org/isinfo.php
echo.
pause

@echo off
echo ========================================
echo   Screen Translator - Setup
echo ========================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed.
    echo Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Installing dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Setup complete!
echo ========================================
echo.
echo NOTE: Tesseract OCR is required.
echo   Download: https://github.com/UB-Mannheim/tesseract/wiki
echo.
echo Run the app with:  python app.py
echo.
pause

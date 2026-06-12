@echo off
echo === Building Screen Translator ===
echo.

pip install pyinstaller

pyinstaller --noconfirm --onedir --windowed ^
    --name "ScreenTranslator" ^
    --icon "icon.ico" ^
    --add-data "icon.ico;." ^
    --hidden-import "PIL._tkinter_finder" ^
    app.py

echo.
echo Build complete! Output in dist\ScreenTranslator\
pause

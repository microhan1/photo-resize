@echo off
rem Build photo-resize.exe (single file, no console) with PyInstaller.
rem Usage: build.bat          -> dist\photo-resize.exe
rem Before building: Get-Process photo-resize (do not overwrite an exe the user has open),
rem and keep dist\settings.json if there is one.
rem numpy is left out: Pillow and pillow-heif only use it for array conversions this tool never does.
setlocal
cd /d "%~dp0"

python -m PyInstaller --version >nul 2>&1 || python -m pip install pyinstaller
python -m pip install -r requirements.txt

python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name photo-resize ^
  --icon "assets\icon.ico" ^
  --add-data "assets\icon.png;assets" ^
  --add-data "lang;lang" ^
  --add-data "LICENSE;." ^
  --add-data "THIRD_PARTY_LICENSES.md;." ^
  --collect-data tkinterdnd2 ^
  --collect-data sv_ttk ^
  --collect-all pillow_heif ^
  --copy-metadata pillow_heif ^
  --copy-metadata pillow ^
  --exclude-module numpy ^
  main.py

if errorlevel 1 (
  echo Build failed.
  exit /b 1
)
echo.
echo Done: dist\photo-resize.exe
endlocal

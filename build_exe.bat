@echo off
chcp 65001 >nul
set "APP_VERSION=4.5.0"
echo Building Daqiq %APP_VERSION%...
echo Installing required libraries...
pip install -r requirements.txt

echo Building standalone Windows Executable (EXE)...
pyinstaller --noconfirm --onefile --windowed --name "Daqiq_%APP_VERSION%" --add-data "default_taxonomy.json;." main.py

echo.
echo Build %APP_VERSION% Completed Successfully!
echo Your executable file is located in: dist\Daqiq_%APP_VERSION%.exe
pause

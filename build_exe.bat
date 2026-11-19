@echo off
chcp 65001 >nul
set "APP_VERSION=4.7.0"
echo Building Daqiq %APP_VERSION%...
echo Installing required libraries...
pip install -r requirements.txt

echo Building standalone Windows Executable (EXE)...
pyinstaller --noconfirm --onefile --windowed --hidden-import sqlcipher3 --name "Daqiq_%APP_VERSION%" main.py

echo Copying companion default_taxonomy.json beside executable...
if not exist "dist" mkdir "dist"
copy /Y "default_taxonomy.json" "dist\default_taxonomy.json"

echo.
echo Build %APP_VERSION% Completed Successfully!
echo Your executable file is located in: dist\Daqiq_%APP_VERSION%.exe
echo Companion taxonomy file: dist\default_taxonomy.json
pause

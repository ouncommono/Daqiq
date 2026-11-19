@echo off
chcp 65001 >nul
set "APP_VERSION=4.6.0"
echo Building Daqiq %APP_VERSION%...
echo Installing required libraries...
pip install -r requirements.txt

echo Building standalone Windows Executable (EXE)...
pyinstaller --noconfirm --onefile --windowed --hidden-import sqlcipher3 --name "Daqiq_%APP_VERSION%" main.py

echo Copying companion default_taxonomy.json beside executable...
if not exist "dist" mkdir "dist"
copy /Y "default_taxonomy.json" "dist\default_taxonomy.json" >nul

echo Testing built binary with noninteractive self-test...
"dist\Daqiq_%APP_VERSION%.exe" --self-test
if errorlevel 1 (
    echo [ERROR] Binary self-test failed!
    exit /b 1
)

echo.
echo Build %APP_VERSION% Completed Successfully!
echo Executable: dist\Daqiq_%APP_VERSION%.exe
echo Companion taxonomy: dist\default_taxonomy.json
if not defined CI if "%~1"=="" pause

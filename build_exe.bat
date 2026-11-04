@echo off
chcp 65001 >nul
set "APP_NAME=Daqiq"
set "APP_VERSION=2.1.0"
echo Building %APP_NAME% (Daqiq) %APP_VERSION%...
echo Installing required libraries...
pip install -r requirements.txt

echo Building standalone Windows Executable (EXE)...
pyinstaller --noconfirm --onefile --windowed --name "%APP_NAME%_%APP_VERSION%" main.py

echo.
echo Build %APP_VERSION% Completed Successfully!
echo Your executable file is located in: dist\%APP_NAME%_%APP_VERSION%.exe
pause
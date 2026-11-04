@echo off
chcp 65001 >nul
set "APP_VERSION=1.2.0"
echo Building Accounting Software %APP_VERSION%...
echo Installing required libraries...
pip install -r requirements.txt

echo Building standalone Windows Executable (EXE)...
pyinstaller --noconfirm --onefile --windowed --name "ComputerShopERP_%APP_VERSION%" main.py

echo.
echo Build %APP_VERSION% Completed Successfully!
echo Your executable file is located in: dist\ComputerShopERP_%APP_VERSION%.exe
pause
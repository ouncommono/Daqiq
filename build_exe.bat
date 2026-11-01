@echo off
chcp 65001 >nul
echo Installing required libraries...
pip install -r requirements.txt

echo Building standalone Windows Executable (EXE)...
pyinstaller --noconfirm --onefile --windowed --name "ComputerShopERP" main.py

echo.
echo Build Completed Successfully!
echo Your executable file is located in: dist\ComputerShopERP.exe
pause
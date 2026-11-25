@echo off
chcp 65001 >nul
echo =======================================================
echo Building Daqiq Production Windows Executable with Nuitka
echo =======================================================
echo.
python scripts\build_local.py --mode onefile
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed! Check compiler logs above.
    exit /b 1
)
echo.
echo Build Completed Successfully!
echo Artifacts are located in the dist\ directory.

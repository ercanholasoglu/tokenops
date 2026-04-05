@echo off
REM ── TokenOps — Build Standalone Executable (Windows) ──
REM Run this from the backend\ directory:
REM   cd backend
REM   build.bat
REM
REM Output: dist\TokenOps.exe

echo.
echo ========================================
echo    TokenOps — Building for Windows
echo ========================================
echo.

if not exist "run.py" (
    echo ERROR: Run this from the backend\ directory
    echo   cd backend ^&^& build.bat
    exit /b 1
)

echo Installing dependencies...
pip install pyinstaller -q
pip install -r requirements.txt -q

echo Building standalone executable...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
pyinstaller tokenops.spec --clean --noconfirm

if exist "dist\TokenOps.exe" (
    echo.
    echo ========================================
    echo    Build successful!
    echo ========================================
    echo.
    echo   File: dist\TokenOps.exe
    echo   Size: 
    dir dist\TokenOps.exe | findstr "TokenOps"
    echo.
    echo   To run: dist\TokenOps.exe
    echo   Dashboard: http://localhost:8000/dashboard
) else (
    echo ERROR: Build failed
    exit /b 1
)

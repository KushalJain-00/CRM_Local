@echo off
setlocal
cd /d "%~dp0"
title CRM Local Windows build

rem One-shot build: dist\CRM_Local.exe (+ CRM_Local-Setup.exe if Inno Setup is installed).
rem CI builds the same artifacts on every push; this is the local path.

where py >nul 2>&1
if %errorlevel% equ 0 (set "PY=py -3") else (set "PY=python")

echo   Installing build dependencies...
%PY% -m pip install -q pyinstaller -r requirements.txt
if errorlevel 1 (
    echo   Dependency install failed.
    pause
    exit /b 1
)

echo   Running tests...
%PY% -m pytest -q
if errorlevel 1 (
    echo   Tests failed. Fix them before shipping.
    pause
    exit /b 1
)

echo   Building CRM_Local.exe...
%PY% -m PyInstaller CRM_Local.spec --noconfirm --clean
if errorlevel 1 (
    echo   PyInstaller build failed.
    pause
    exit /b 1
)

echo.
echo   Built: dist\CRM_Local.exe

set "ISCC="
where iscc >nul 2>&1 && set "ISCC=iscc"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if defined ISCC (
    echo   Building CRM_Local-Setup.exe...
    "%ISCC%" CRM_Local.iss
    if errorlevel 1 (
        echo   Inno Setup compile failed.
    ) else (
        echo   Built: dist\CRM_Local-Setup.exe
    )
) else (
    echo   Inno Setup not found - skipping installer. CRM_Local.exe alone is portable and works.
)

echo.
pause

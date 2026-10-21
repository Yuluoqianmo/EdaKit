@echo off
title edakit build
cd /d "%~dp0"

if not exist "%~dp0build_exe.ps1" (
    echo [ERROR] build_exe.ps1 is missing next to this file.
    echo         Please keep both files in the same folder.
    pause
    exit /b 1
)

where powershell >nul 2>nul
if errorlevel 1 (
    echo [ERROR] PowerShell not found on this system.
    pause
    exit /b 1
)

echo ============================================================
echo   edakit  build
echo   Everything is also written to build_log.txt
echo ============================================================

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_exe.ps1"

echo.
echo Full log: %~dp0build_log.txt
echo.
pause

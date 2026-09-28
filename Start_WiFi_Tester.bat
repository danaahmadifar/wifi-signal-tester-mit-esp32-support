@echo off
title WLAN Signal Tester
cd /d "%~dp0\python_gui"

:: Falls die kompilierte EXE vorhanden ist, wird diese bevorzugt gestartet
if exist "dist\WLAN_Signal_Tester.exe" (
    start "" "dist\WLAN_Signal_Tester.exe"
    exit /b
)

:: Andernfalls direkt ueber Python starten
py -3 main.py
if %ERRORLEVEL% NEQ 0 (
    python main.py
)
exit /b

@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   SandikRadar - yerel panel
echo   http://127.0.0.1:8800
echo   Kapatmak icin bu pencerede Ctrl+C
echo ============================================
python local-server\bridge.py
if errorlevel 1 pause

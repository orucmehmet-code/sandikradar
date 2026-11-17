@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo SandikRadar yerel kopru baslatiliyor...
echo Panel: http://127.0.0.1:8800
python local-serverridge.py
pause

@echo off
chcp 65001 >nul
rem SandikRadar veri pompasi - veriyi toplar, docs/data degistiyse commit+push eder
setlocal
cd /d "%~dp0.."
where py >nul 2>nul && (py -3.12 tools\pump.py %* & exit /b %errorlevel%)
python tools\pump.py %*

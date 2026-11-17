@echo off
chcp 65001 >nul
rem SandikRadar veri pompasi - veriyi toplar, docs/data degistiyse commit+push eder
rem Tum cikti logs\pump.log'a yazilir (500 KB'i gecince sifirlanir).
setlocal
cd /d "%~dp0.."
if not exist logs mkdir logs
for %%F in ("logs\pump.log") do if %%~zF GTR 512000 del "logs\pump.log"
echo ===== %DATE% %TIME% ===== >> "logs\pump.log"
where py >nul 2>nul && (py -3.12 tools\pump.py %* >> "logs\pump.log" 2>&1 & exit /b %errorlevel%)
python tools\pump.py %* >> "logs\pump.log" 2>&1

@echo off
cd /d "%~dp0"
echo Starting Czar pipeline scheduler...
python pipeline\scheduler.py
pause

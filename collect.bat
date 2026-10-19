@echo off
rem Double-click to collect today's new jobs.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe call start.bat
.venv\Scripts\python -m jobscan collect
pause

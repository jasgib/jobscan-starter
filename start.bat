@echo off
rem Opens the welcome page. First run also installs what jobscan needs (a minute or two).
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist .venv\Scripts\python.exe (
  echo First run: setting jobscan up...
  %PY% -m venv .venv || (echo Python 3 isn't installed. Get it from https://www.python.org/downloads/ and tick "Add to PATH". & pause & exit /b 1)
  .venv\Scripts\python -m pip install --quiet --upgrade pip
  .venv\Scripts\python -m pip install --quiet -r requirements.txt || (echo Setup failed - see the message above. & pause & exit /b 1)
)
.venv\Scripts\python -m jobscan.onboard
pause

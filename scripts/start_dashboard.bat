@echo off
setlocal
cd /d "%~dp0\.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m research_os.cli.main dashboard %*
  exit /b %errorlevel%
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -m research_os.cli.main dashboard %*
  exit /b %errorlevel%
)
python -m research_os.cli.main dashboard %*
exit /b %errorlevel%

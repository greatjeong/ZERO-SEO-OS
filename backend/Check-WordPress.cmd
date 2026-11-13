@echo off
setlocal
cd /d "%~dp0"
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 goto use_python
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 goto use_py
echo ERROR: Python 3.11 or newer was not found.
goto stopped
:use_python
python -u "%~dp0check_wordpress.py"
goto stopped
:use_py
py -3 -u "%~dp0check_wordpress.py"
:stopped
echo.
echo Share only result lines, never credentials.
pause
endlocal

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
python -u "%~dp0start_connector.py"
goto stopped
:use_py
py -3 -u "%~dp0start_connector.py"
:stopped
echo.
echo Connector stopped. Share only errors, never credentials.
pause
endlocal

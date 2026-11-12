@echo off
setlocal
title ZERO SEO OS - Dashboard (KEEP OPEN)
cd /d "%~dp0"
if not exist "frontend\package.json" (
 echo ERROR: Put Start-Dashboard.cmd in the project folder beside frontend and backend.
 goto stopped
)
where npm.cmd >nul 2>&1
if errorlevel 1 (
 echo ERROR: Node.js / npm was not found. Keep this error visible for support.
 goto stopped
)
cd /d "%~dp0frontend"
if not exist "node_modules\vite\bin\vite.js" (
 echo ERROR: Frontend dependencies are missing. Keep this error visible for support.
 goto stopped
)
echo ZERO SEO OS Dashboard: http://127.0.0.1:5173/
echo Keep this window open. The WordPress connector uses a separate window on port 8765.
echo Starting Vite. The browser opens when the dashboard is ready.
call npm.cmd run dev -- --open
:stopped
echo.
echo Dashboard process stopped. Keep the error above visible for support.
pause
endlocal

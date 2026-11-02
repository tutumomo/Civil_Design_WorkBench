@echo off
setlocal
rem Civil-design workbench. The same local server also serves the regulation lookup page.
rem 需要 PATH 上有 Python 3.10+（Windows 可用 "py -3"）。若沒裝，請先安裝並勾選 Add to PATH。
set "PYEXE="
if defined CIVIL_AI_PYTHON if exist "%CIVIL_AI_PYTHON%" set "PYEXE=%CIVIL_AI_PYTHON%"
if not defined PYEXE if exist "%~dp0.venv\Scripts\python.exe" set "PYEXE=%~dp0.venv\Scripts\python.exe"
if not defined PYEXE where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE (where py >nul 2>&1 && set "PYEXE=py -3")
if not defined PYEXE (
  echo [錯誤] 找不到 Python。請安裝 Python 3.10+ 並加入 PATH，或先啟用虛擬環境。
  pause
  exit /b 1
)
curl -s -o nul http://127.0.0.1:8765/api/design/health
if not errorlevel 1 (
  start "" http://127.0.0.1:8765/design
  exit /b 0
)
start "civil-design-workbench" /min %PYEXE% -E -P -X utf8 "%~dp0tools\regs\regs_server.py" --web
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8765/design
endlocal
exit /b 0

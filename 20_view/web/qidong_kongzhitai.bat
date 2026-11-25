@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d %~dp0

rem ============================================================
rem  Bumao XTGL console launcher - ONE byte-identical copy for all
rem  three editions. Pure ASCII on purpose: cmd parses a .bat with the
rem  console code page inherited at launch time, so any non-ASCII byte
rem  parses differently under cp936 vs cp65001 and can break the file.
rem  Chinese text is printed by serve.py instead (WriteConsoleW).
rem
rem  The port is NOT hardcoded here. serve.py reads it from
rem  web_config.json and walks up to 40 ports if it is taken, then
rem  prints the real URL and opens the browser itself.
rem
rem  Interpreter probing order (first working candidate wins):
rem    0) python_path.txt in this folder  (local override, one path)
rem    1) py -3
rem    2) python3
rem    3) python
rem    4) common install locations       (generic, no local path baked in)
rem  Every candidate is executed with "-c import sys", so the Windows
rem  Store stub (which exits 9009) is rejected instead of being used.
rem ============================================================

set "PYEXE="
set "PYARG="
set "OVERRIDE="

rem 0) local override: python_path.txt, one interpreter path per line
if exist "%~dp0python_path.txt" (
  for /f "usebackq delims=" %%L in ("%~dp0python_path.txt") do (
    if not defined OVERRIDE set "OVERRIDE=%%~L"
  )
)
if defined OVERRIDE (
  "%OVERRIDE%" -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PYEXE=%OVERRIDE%"
)

rem 1) py -3 launcher
if not defined PYEXE (
  py -3 -c "import sys" >nul 2>&1
  if not errorlevel 1 (
    set "PYEXE=py"
    set "PYARG=-3"
  )
)

rem 2) python3
if not defined PYEXE (
  python3 -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PYEXE=python3"
)

rem 3) python
if not defined PYEXE (
  python -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PYEXE=python"
)

rem 4) generic install locations (validated by execution, not just existence)
if not defined PYEXE (
  for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%ProgramFiles%\Python313\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python311\python.exe"
  ) do if not defined PYEXE if exist "%%~P" (
    "%%~P" -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PYEXE=%%~P"
  )
)

if not defined PYEXE (
  echo [Bumao XTGL] No usable Python 3 found.
  echo   Tried: python_path.txt, py -3, python3, python, common locations.
  echo   Put the full path of python.exe into python_path.txt in this folder.
  pause
  exit /b 1
)

echo [Bumao XTGL] Starting console...
echo Interpreter: %PYEXE% %PYARG%
echo Port comes from web_config.json; serve.py prints the URL and opens the browser.
echo Close this window to stop the service.
echo.
"%PYEXE%" %PYARG% serve.py
echo.
echo [Bumao XTGL] serve.py exited with code %errorlevel%.
pause

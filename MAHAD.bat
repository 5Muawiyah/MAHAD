@echo off
setlocal
title MAHAD Launcher

rem ===============================================================
rem  MAHAD - double-click launcher (Windows)
rem  Starts MAHAD with the project's own virtual environment, no
rem  manual activation needed. On the first run it creates .venv
rem  and installs the requirements - that one-time setup can take
rem  a few minutes. Simulated (virtual) USD portfolio - no real
rem  orders are placed; not financial advice.
rem
rem  MAHAD supports Python 3.11 to 3.13 (3.13 recommended). Python
rem  3.14 and newer are not validated for MAHAD yet, so the launcher
rem  selects a supported version (3.13 preferred).
rem ===============================================================

rem Work from this script's own folder so the launcher runs from any
rem location, including folder names with spaces and special
rem characters (every path below stays quoted).
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

rem Reuse an existing .venv only if its Python is in the supported
rem range; a .venv built by an older run on an unsupported Python
rem (for example 3.14) is rejected with a clear instruction.
if exist "%VENV_PY%" goto check_venv
goto first_run

:check_venv
"%VENV_PY%" -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>&1
if %ERRORLEVEL% EQU 0 goto launch
goto bad_venv

:first_run
echo.
echo [MAHAD] First run: the .venv environment does not exist yet.
echo [MAHAD] Setting it up now - this one-time step can take a few minutes.
echo.

rem ---- Find a supported Python (3.13 preferred; 3.11 to 3.13 accepted) ----
set "BASE_PY="
call :probe "py -3.13"
if defined BASE_PY goto found_python
call :probe "py -3.12"
if defined BASE_PY goto found_python
call :probe "py -3.11"
if defined BASE_PY goto found_python
call :probe "python"
if defined BASE_PY goto found_python
call :probe "py -3"
if defined BASE_PY goto found_python
goto no_python

:probe
rem Accept only Python 3.11, 3.12, or 3.13 (3.13 preferred). Anything
rem older than 3.11 or 3.14 and newer is rejected so setup never builds
rem on an unsupported interpreter.
%~1 -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>&1
if %ERRORLEVEL% EQU 0 set "BASE_PY=%~1"
exit /b 0

:found_python
echo [MAHAD] Found a supported base Python: %BASE_PY%
echo.
echo [MAHAD] Step 1 of 3: creating the virtual environment in .venv ...
%BASE_PY% -m venv .venv
if %ERRORLEVEL% NEQ 0 goto venv_failed
if not exist "%VENV_PY%" goto venv_failed

echo.
echo [MAHAD] Step 2 of 3: upgrading pip ...
"%VENV_PY%" -m pip install --upgrade pip
if %ERRORLEVEL% NEQ 0 echo [MAHAD] Warning: the pip upgrade failed; continuing with the bundled pip.

echo.
echo [MAHAD] Step 3 of 3: installing requirements.txt - the slow part, please wait ...
"%VENV_PY%" -m pip install -r "%~dp0requirements.txt"
if %ERRORLEVEL% NEQ 0 goto install_failed

echo.
echo [MAHAD] Setup finished.

:launch
echo.
echo [MAHAD] Starting MAHAD - simulated (virtual) portfolio ...
"%VENV_PY%" -m mahad
set "APP_EXIT=%ERRORLEVEL%"
if %APP_EXIT% EQU 0 exit /b 0

echo.
echo [MAHAD] MAHAD exited with an error - exit code %APP_EXIT%.
echo [MAHAD] The messages above show what went wrong, and the app's
echo [MAHAD] rotating log file has the full details:
echo [MAHAD]   %USERPROFILE%\.mahad\mahad.log
goto fail

:no_python
echo [MAHAD] ERROR: no supported Python was found on this machine.
echo [MAHAD] MAHAD needs Python 3.13 (the supported range is 3.11 to 3.13).
echo [MAHAD] Python 3.14 and newer are not supported yet - please install 3.13.
echo [MAHAD] Get it from: https://www.python.org/downloads/
echo [MAHAD] Pick a 3.13.x release, tick "Add python.exe to PATH" during the
echo [MAHAD] install, then double-click MAHAD.bat again.
goto fail

:bad_venv
echo.
echo [MAHAD] ERROR: the existing .venv uses an unsupported Python version.
echo [MAHAD] This usually means it was created by an older run on Python 3.14+.
echo [MAHAD] Delete the .venv folder in this directory, then double-click
echo [MAHAD] MAHAD.bat again to recreate it with Python 3.13.
goto fail

:venv_failed
echo.
echo [MAHAD] ERROR: creating the virtual environment failed.
echo [MAHAD] The messages above show the cause. Fix it, delete any
echo [MAHAD] half-created .venv folder, and double-click MAHAD.bat again.
goto fail

:install_failed
echo.
echo [MAHAD] ERROR: installing requirements.txt failed.
echo [MAHAD] Check your network connection and the messages above, then
echo [MAHAD] double-click MAHAD.bat again to retry the setup.
goto fail

:fail
echo.
pause
exit /b 1

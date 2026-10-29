@echo off
setlocal
cd /d "%~dp0"

REM Look for a compatible Python (3.10 - 3.13), preferably 3.11
set "PY="
for %%V in (3.11 3.12 3.10 3.13) do call :try_py %%V
if not defined PY call :try_python
if not defined PY goto :no_python

%PY% install.py %*
set "ERR=%ERRORLEVEL%"
echo.
pause
exit /b %ERR%

:try_py
if defined PY exit /b 0
py -%1 -c "import sys" >nul 2>nul && set "PY=py -%1"
exit /b 0

:try_python
python -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>nul && set "PY=python"
exit /b 0

:no_python
echo Python 3.10 - 3.13 was not found.
echo.
echo Install Python 3.11 from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during the installation.
echo Or, in a terminal:  winget install -e --id Python.Python.3.11
echo.
echo Then run install.bat again.
pause
exit /b 1

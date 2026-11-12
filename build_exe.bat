@echo off
setlocal
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto use_python
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto use_py
echo ERROR: Install Python 3.10 or newer ^(3.12 recommended^) and add it to PATH.
exit /b 1

:use_python
python "%~dp0build_exe.py" %*
exit /b %errorlevel%

:use_py
py -3 "%~dp0build_exe.py" %*
exit /b %errorlevel%

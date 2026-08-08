@echo off
REM Start the UVSS edge service. Arguments are passed through, e.g.
REM     run.bat --source 1 --classes Vehicles --port 9000
cd /d "%~dp0"

set PYEXE=python
if exist ".venv\Scripts\python.exe" set PYEXE=.venv\Scripts\python.exe

"%PYEXE%" server.py %*
pause

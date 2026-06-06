@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0tools\python_cmd.bat"
"%PYTHON_EXE%" AutoMediaProducer.py
pause

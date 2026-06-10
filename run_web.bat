@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0tools\python_cmd.bat"
"%PYTHON_EXE%" -X utf8 -m quanlan_dual_assistant.web_app %*
pause

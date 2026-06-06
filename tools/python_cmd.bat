@echo off
if exist "%USERPROFILE%\miniconda3\python.exe" (
  set "PYTHON_EXE=%USERPROFILE%\miniconda3\python.exe"
) else (
  set "PYTHON_EXE=python"
)


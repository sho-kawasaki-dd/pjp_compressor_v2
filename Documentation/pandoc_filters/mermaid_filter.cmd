@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
set "VENV_PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"

if exist "%VENV_PYTHON%" (
	"%VENV_PYTHON%" "%SCRIPT_DIR%mermaid_filter.py"
) else (
	python "%SCRIPT_DIR%mermaid_filter.py"
)

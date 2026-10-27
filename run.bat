@echo off
REM Starts the Laya service on port 9120 (creates .venv_laya on first run).
REM LABEL: Laya Service
REM DESCRIPTION: Shared HTTP service that owns the Laya models for every project.

cd /d "%~dp0"

if not exist ".venv_laya\Scripts\python.exe" (
    echo Creating virtual environment .venv_laya ...
    py -m venv .venv_laya
    call .venv_laya\Scripts\activate
    pip install -e ".[dev]"
) else (
    call .venv_laya\Scripts\activate
)

python src/app.py
pause

@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul && (start "" pythonw main.py) || (python main.py)

@echo off
rem Config review assistant: double-click to open the GUI
cd /d "%~dp0"
uv run config-review-gui
if errorlevel 1 pause

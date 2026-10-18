@echo off
rem Config review assistant: double-click to open the GUI
cd /d "%~dp0"

rem If uv is not on PATH (e.g. right after installing it), look in the winget install folder
set "UV=uv"
where uv >nul 2>nul || for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_*") do set "UV=%%D\uv.exe"

"%UV%" run config-review-gui
if errorlevel 1 (
  echo.
  echo Failed to start. Check that uv is installed: https://docs.astral.sh/uv/
  pause
)
